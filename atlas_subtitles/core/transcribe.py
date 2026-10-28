"""Speech-to-text with faster-whisper (CTranslate2), chunked for long files, cancellable."""
from __future__ import annotations

import os
import re
import threading
import wave
from dataclasses import dataclass
from typing import Callable, List, Optional

import numpy as np

from .errors import AtlasError, Cancelled
from .subtitles import Segment, sort_and_fix

SR = 16000
DEFAULT_COMPUTE = "int8"  # ~2.5x less RAM than float32 (small: ~0.85 GB vs ~2.1 GB), same accuracy in our tests
CHUNK_SEC = 600          # 10-minute windows keep memory flat for multi-hour files
SEARCH_SEC = 8           # look this far around a chunk border for the quietest point

# Phrases Whisper commonly hallucinates on silence/music in Arabic & English (from YouTube training captions)
HALLUCINATIONS = [
    r"اشتركوا? في القناة", r"لا تنسوا? الاشتراك", r"ترجمة نانسي قنقر", r"شكرا للمشاهدة", r"شكرا على المشاهدة",
    r"نسخ وترجمة", r"المترجم[:：]", r"subtitles by", r"thanks? for watching", r"please subscribe",
    r"amara\.org",
]
_HALL_RE = re.compile("|".join(HALLUCINATIONS), re.IGNORECASE)

DIALECT_PROMPTS = {
    # A short in-dialect prompt nudges the decoder towards Egyptian spelling (ده، إزاي، عايز...)
    "egyptian": "ده كلام باللهجة المصرية، إزيك عامل إيه، أنا عايز أقولك حاجة.",
    "msa": "",
}


@dataclass
class TranscribeResult:
    segments: List[Segment]
    language: str
    language_probability: float
    duration: float


def read_wav(path: str) -> np.ndarray:
    """Memory-map the 16 kHz mono s16 wav (int16, not loaded into RAM: a 3 h file would otherwise
    need ~1 GB as float32). Use `to_float()` on the slice you actually decode."""
    with wave.open(path, "rb") as w:
        if w.getframerate() != SR or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise AtlasError("bad_wav", "expected 16 kHz mono s16")
        n = w.getnframes()
    with open(path, "rb") as f:  # locate the 'data' chunk
        f.seek(12)
        while True:
            hdr = f.read(8)
            if len(hdr) < 8:
                raise AtlasError("bad_wav", "no data chunk")
            cid, size = hdr[:4], int.from_bytes(hdr[4:], "little")
            if cid == b"data":
                off = f.tell()
                break
            f.seek(size + (size & 1), 1)
    if n == 0:
        return np.zeros(0, dtype=np.int16)
    return np.memmap(path, dtype="<i2", mode="r", offset=off, shape=(n,))


def to_float(x: np.ndarray) -> np.ndarray:
    return np.asarray(x, dtype=np.float32) / 32768.0


def chunk_bounds(audio: np.ndarray, chunk_sec: int = CHUNK_SEC) -> List[tuple]:
    """Split into ~chunk_sec windows, moving each border to the quietest 100 ms nearby."""
    n = len(audio)
    step = chunk_sec * SR
    if n <= step + SEARCH_SEC * SR:
        return [(0, n)]
    bounds, start = [], 0
    win = SR // 10
    while start < n:
        target = start + step
        if target >= n - SEARCH_SEC * SR:
            bounds.append((start, n))
            break
        lo, hi = max(start + SR, target - SEARCH_SEC * SR), min(n - 1, target + SEARCH_SEC * SR)
        seg = np.asarray(audio[lo:hi], dtype=np.float32)
        k = len(seg) // win
        energy = (seg[:k * win].reshape(k, win) ** 2).mean(axis=1)
        cut = lo + int(np.argmin(energy)) * win + win // 2
        bounds.append((start, cut))
        start = cut
    return bounds


def resegment(segments: List[Segment], max_chars: int = 84, max_dur: float = 7.0) -> List[Segment]:
    """Break long Whisper segments into caption-sized pieces at word boundaries (uses word timings)."""
    out: List[Segment] = []
    for s in segments:
        if len(s.text) <= max_chars and s.duration() <= max_dur:
            out.append(s)
            continue
        words = s.words
        if len(words) < 2:  # no word timings: spread the words over the segment by character count
            toks = s.text.split()
            if len(toks) < 2:
                out.append(s)
                continue
            total = sum(len(t) + 1 for t in toks)
            t, words = s.start, []
            for tok in toks:
                d = s.duration() * (len(tok) + 1) / total
                words.append((t, t + d, " " + tok))
                t += d
        cur: list = []
        for w in words:
            cand = "".join(x[2] for x in cur + [w]).strip()
            too_long = cur and (len(cand) > max_chars or (w[1] - cur[0][0]) > max_dur)
            if too_long:
                out.append(Segment(cur[0][0], cur[-1][1], "".join(x[2] for x in cur).strip(), cur))
                cur = []
            cur.append(w)
            # prefer to break after sentence punctuation once the caption has some length
            if re.search(r"[.!?؟،,]$", w[2].strip()) and len("".join(x[2] for x in cur)) > max_chars * 0.5:
                out.append(Segment(cur[0][0], cur[-1][1], "".join(x[2] for x in cur).strip(), cur))
                cur = []
        if cur:
            out.append(Segment(cur[0][0], cur[-1][1], "".join(x[2] for x in cur).strip(), cur))
    return out


class Transcriber:
    """Loads a model once; `transcribe()` can be called repeatedly."""

    def __init__(self, model_path: str, device: str = "cpu", compute_type: str = DEFAULT_COMPUTE,
                 cpu_threads: int = 0):
        from faster_whisper import BatchedInferencePipeline, WhisperModel
        try:
            self.model = WhisperModel(model_path, device=device, compute_type=compute_type,
                                      cpu_threads=cpu_threads or min(8, os.cpu_count() or 4))
        except Exception as e:  # corrupt/partial model folder, unsupported CPU, ...
            raise AtlasError("model_load_failed", f"{type(e).__name__}: {e}"[:500])
        # Batched mode = Silero VAD cuts speech into <=30 s pieces that are decoded independently.
        # On our Arabic tests this avoided the sequential decoder's habit of stopping early and
        # silently skipping the rest of a 30 s window (see tests/RESULTS.md).
        self.batched = BatchedInferencePipeline(self.model)

    def detect_language(self, audio: np.ndarray) -> tuple:
        """Detect on speech only (VAD) over up to 3 x 30 s windows; more stable than the first 30 s."""
        try:
            lang, p, _all = self.model.detect_language(to_float(audio[: SR * 300]), vad_filter=True,
                                                       language_detection_segments=3,
                                                       language_detection_threshold=0.8)
            return lang, float(p)
        except Exception:
            lang, p, _all = self.model.detect_language(to_float(audio[: SR * 30]))
            return lang, float(p)

    def transcribe(self, wav_path: str, language: Optional[str] = None, dialect: str = "msa",
                   beam_size: int = 5, vad: bool = True, task: str = "transcribe",
                   progress: Optional[Callable[[float, str], None]] = None,
                   on_segment: Optional[Callable[[Segment], None]] = None,
                   cancel: Optional[threading.Event] = None,
                   chunk_sec: int = CHUNK_SEC, engine: str = "batched",
                   batch_size: int = 4) -> TranscribeResult:
        audio = read_wav(wav_path)
        try:
            return self._transcribe(audio, language, dialect, beam_size, vad, task, progress, on_segment,
                                    cancel, chunk_sec, engine, batch_size)
        finally:  # release the memory map now, so the temp wav can be deleted (Windows locks open files)
            mm = getattr(audio, "_mmap", None)
            del audio
            if mm is not None:
                try:
                    mm.close()
                except Exception:
                    pass

    def _transcribe(self, audio, language, dialect, beam_size, vad, task, progress, on_segment, cancel,
                    chunk_sec, engine, batch_size) -> TranscribeResult:
        total = len(audio) / SR
        if total < 0.1:
            raise AtlasError("no_speech", "audio shorter than 0.1 s")
        bounds = chunk_bounds(audio, chunk_sec)
        prompt = DIALECT_PROMPTS.get(dialect) or None
        lang, lang_p = language, 1.0
        if lang is None:
            if progress:
                progress(0.0, "")
            lang, lang_p = self.detect_language(audio)
        segments: List[Segment] = []
        for (a, b) in bounds:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            off = a / SR
            chunk = to_float(audio[a:b])
            try:
                if engine == "batched":
                    gen, info = self.batched.transcribe(
                        chunk, language=lang, task=task, beam_size=beam_size, word_timestamps=True,
                        initial_prompt=prompt, batch_size=batch_size, vad_filter=True,
                        vad_parameters={"min_silence_duration_ms": 500, "max_speech_duration_s": 25})
                else:
                    gen, info = self.model.transcribe(
                        chunk, language=lang, task=task, beam_size=beam_size, vad_filter=vad,
                        vad_parameters={"min_silence_duration_ms": 500}, word_timestamps=True,
                        condition_on_previous_text=False, initial_prompt=prompt,
                        no_speech_threshold=0.6, log_prob_threshold=-1.0, compression_ratio_threshold=2.4)
            except ValueError as e:
                if "No speech" in str(e) or "empty" in str(e).lower():
                    continue
                raise AtlasError("transcribe_failed", f"{type(e).__name__}: {e}"[:500])
            except Exception as e:
                raise AtlasError("transcribe_failed", f"{type(e).__name__}: {e}"[:500])
            for s in gen:
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                text = s.text.strip()
                if not text or _HALL_RE.search(text):
                    continue
                words = [(w.start + off, w.end + off, w.word) for w in (s.words or [])]
                seg = Segment(s.start + off, s.end + off, text, words)
                segments.append(seg)
                if on_segment:
                    on_segment(seg)
                if progress:
                    progress(min(0.999, seg.end / total), lang or "")
            if progress:
                progress(min(0.999, b / SR / total), lang or "")
        segments = sort_and_fix(resegment(segments))
        if progress:
            progress(1.0, lang or "")
        if not segments:
            raise AtlasError("no_speech")
        return TranscribeResult(segments, lang or "", lang_p, total)

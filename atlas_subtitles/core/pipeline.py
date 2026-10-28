"""End-to-end job: media -> wav -> segments -> files (+ optional burn-in). Used by both CLI and GUI."""
from __future__ import annotations

import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import ffmpeg, models, subtitles
from .errors import AtlasError
from .subtitles import Segment
from .transcribe import DEFAULT_COMPUTE, Transcriber, TranscribeResult

# stage weights for one overall progress bar
STAGES = {"model": 0.0, "extract": 0.10, "transcribe": 0.85, "burn": 0.0}
Progress = Optional[Callable[[str, float, str], None]]   # (stage, overall_fraction, detail)

_model_cache: Dict[tuple, Transcriber] = {}
_cache_lock = threading.Lock()


# Rough real-time factors (processing seconds per audio second) on a typical 4-core laptop CPU,
# extrapolated from measurements on the 8-vCPU build box (see tests/RESULTS.md). Used for ETA only.
TYPICAL_RTF = {"tiny": 0.1, "base": 0.15, "small": 0.35, "medium": 1.0, "large-v3-turbo": 1.0}


def get_transcriber(model: str, progress=None, cancel=None, compute_type: str = DEFAULT_COMPUTE) -> Transcriber:
    path = models.ensure_model(model, progress=progress, cancel=cancel)
    key = (path, compute_type)
    with _cache_lock:
        if key not in _model_cache:
            _model_cache.clear()  # keep only one model in RAM
            _model_cache[key] = Transcriber(path, compute_type=compute_type)
        return _model_cache[key]


@dataclass
class JobResult:
    segments: List[Segment]
    language: str
    language_probability: float
    duration: float
    timings: Dict[str, float] = field(default_factory=dict)


def transcribe_file(src: str, model: str = models.DEFAULT_MODEL, language: Optional[str] = None,
                    dialect: str = "msa", progress: Progress = None,
                    cancel: Optional[threading.Event] = None,
                    on_segment: Optional[Callable[[Segment], None]] = None,
                    compute_type: str = DEFAULT_COMPUTE) -> JobResult:
    timings: Dict[str, float] = {}
    info = ffmpeg.probe(src)
    if not info.has_audio:
        raise AtlasError("no_audio", src)
    t0 = time.time()

    def p_model(frac, mb):
        if progress:
            progress("download", 0.0, str(mb))

    if progress:
        progress("loading", 0.0, "")
    tr = get_transcriber(model, p_model, cancel, compute_type)
    timings["model_load"] = time.time() - t0
    tmp = Path(tempfile.mkdtemp(prefix="atlas_subs_"))
    try:
        wav = tmp / "audio.wav"
        t0 = time.time()
        ffmpeg.extract_audio(src, wav, info,
                             progress=(lambda f: progress("extract", f * STAGES["extract"], "")) if progress else None,
                             cancel=cancel)
        timings["extract"] = time.time() - t0
        t0 = time.time()
        res: TranscribeResult = tr.transcribe(
            str(wav), language=language, dialect=dialect, cancel=cancel, on_segment=on_segment,
            progress=(lambda f, lang: progress("transcribe", STAGES["extract"] + f * STAGES["transcribe"], lang))
            if progress else None)
        timings["transcribe"] = time.time() - t0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if progress:
        progress("done", 1.0, res.language)
    return JobResult(res.segments, res.language, res.language_probability, res.duration, timings)


def export_all(segments: List[Segment], base: Path, formats=("srt", "vtt", "txt"), max_chars: int = 42) -> List[Path]:
    out = []
    for f in formats:
        kw = {"max_chars": max_chars} if f in ("srt", "vtt") else {}
        out.append(subtitles.save(segments, base.with_suffix("." + f), f, **kw))
    return out


# UI name -> (family inside the bundled TTF, size factor). "Noto Sans" is a static Bold instance of
# Noto Sans Arabic renamed "Atlas Noto Sans Arabic" (no clash with installed fonts). Cairo was tried
# first and dropped: libass rendered isolated letters (ر و د ا ...) as empty boxes with it.
FONT_MAP = {"Noto Sans": ("Atlas Noto Sans Arabic", 1.0), "Amiri": ("Amiri", 1.2)}


def burn(src: str, segments: List[Segment], dst: str, font: str = "Noto Sans", size_pct: float = 5.5,
         box: bool = False, progress: Optional[Callable[[float], None]] = None,
         cancel: Optional[threading.Event] = None) -> Path:
    info = ffmpeg.probe(src)
    if not info.has_video:
        raise AtlasError("no_video", src)
    w, h = info.width or 1920, info.height or 1080
    # font size relative to the short side so vertical (Reels/TikTok) videos look right too
    family, factor = FONT_MAP.get(font, (font, 1.0))
    font_px = max(16, int(min(w, h) * size_pct / 100 * factor))
    max_chars = 42 if w >= h else 26
    ass = subtitles.to_ass(segments, font=family, font_size=font_px, width=w, height=h,
                           outline_w=max(1.5, font_px / 16), margin_v=int(h * 0.06), max_chars=max_chars, box=box)
    return ffmpeg.burn_in(src, ass, dst, info, progress=progress, cancel=cancel)

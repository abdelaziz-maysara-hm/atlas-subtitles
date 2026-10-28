"""Subtitle data model, editing operations, and SRT / VTT / TXT / ASS writers."""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable, List

ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
RLM = "\u200f"


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list = field(default_factory=list)  # optional [(start, end, word), ...]

    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self) -> dict:
        return asdict(self)


def is_rtl(text: str) -> bool:
    """True when the text is mostly Arabic-script."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    ar = sum(1 for c in letters if ARABIC_RE.match(c))
    return ar >= len(letters) / 2


# ---------- time formatting ----------
def _split_time(t: float):
    if t < 0:
        t = 0.0
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return h, m, s, ms


def fmt_srt_time(t: float) -> str:
    h, m, s, ms = _split_time(t)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def fmt_vtt_time(t: float) -> str:
    h, m, s, ms = _split_time(t)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def fmt_ass_time(t: float) -> str:
    h, m, s, ms = _split_time(t)
    return f"{h:d}:{m:02d}:{s:02d}.{ms // 10:02d}"


def parse_time(s: str) -> float:
    """Parse '00:01:02,345', '01:02.345', '62.3' -> seconds."""
    s = s.strip().replace(",", ".")
    if not s:
        raise ValueError("empty time")
    parts = s.split(":")
    if len(parts) > 3:
        raise ValueError(f"bad time: {s}")
    total = 0.0
    for p in parts:
        total = total * 60 + float(p)
    if total < 0:
        raise ValueError("negative time")
    return total


# ---------- line wrapping ----------
def wrap_text(text: str, max_chars: int = 42, max_lines: int = 2) -> str:
    """Wrap a caption into at most `max_lines` balanced lines (word boundaries only)."""
    text = " ".join(text.split())
    if len(text) <= max_chars or max_lines < 2:
        return text
    words = text.split(" ")
    best, best_score = text, None
    # try every split point for 2 lines; pick the most balanced one
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        score = max(len(a), len(b))
        if best_score is None or score < best_score:
            best, best_score = a + "\n" + b, score
    return best


# ---------- editing operations ----------
def sort_and_fix(segments: List[Segment], min_dur: float = 0.2) -> List[Segment]:
    """Sort by start, clamp negatives, remove overlaps, enforce minimum duration."""
    segs = sorted((Segment(max(0.0, s.start), max(0.0, s.end), s.text.strip(), list(s.words)) for s in segments),
                  key=lambda s: (s.start, s.end))
    segs = [s for s in segs if s.text]
    for i, s in enumerate(segs):
        if s.end < s.start + min_dur:
            s.end = s.start + min_dur
        if i + 1 < len(segs) and s.end > segs[i + 1].start:
            s.end = max(s.start + 0.05, segs[i + 1].start)
    return segs


def split_segment(segments: List[Segment], index: int, at_time: float | None = None) -> List[Segment]:
    """Split segment `index` in two. Uses word timings when available, else splits text in the middle."""
    seg = segments[index]
    words = seg.text.split()
    if len(words) < 2:
        raise ValueError("segment has a single word; nothing to split")
    if seg.words and len(seg.words) >= 2:
        # choose word boundary closest to at_time (or to the middle by count)
        if at_time is None:
            k = len(seg.words) // 2
        else:
            k = min(range(1, len(seg.words)), key=lambda j: abs(seg.words[j][0] - at_time))
        t = seg.words[k][0]
        first = Segment(seg.start, t, "".join(w[2] for w in seg.words[:k]).strip(), seg.words[:k])
        second = Segment(t, seg.end, "".join(w[2] for w in seg.words[k:]).strip(), seg.words[k:])
    else:
        k = len(words) // 2
        a, b = " ".join(words[:k]), " ".join(words[k:])
        if at_time is None or not (seg.start < at_time < seg.end):
            # proportional to characters
            at_time = seg.start + seg.duration() * len(a) / max(1, len(a) + len(b))
        first = Segment(seg.start, at_time, a)
        second = Segment(at_time, seg.end, b)
    return segments[:index] + [first, second] + segments[index + 1:]


def merge_segments(segments: List[Segment], index: int) -> List[Segment]:
    """Merge segment `index` with the next one."""
    if index < 0 or index + 1 >= len(segments):
        raise ValueError("no next segment to merge with")
    a, b = segments[index], segments[index + 1]
    merged = Segment(min(a.start, b.start), max(a.end, b.end), (a.text.strip() + " " + b.text.strip()).strip(),
                     list(a.words) + list(b.words))
    return segments[:index] + [merged] + segments[index + 2:]


def shift_segments(segments: List[Segment], offset: float, indices: Iterable[int] | None = None) -> List[Segment]:
    """Shift start/end by `offset` seconds (all segments, or only `indices`). Clamps at 0."""
    idx = set(range(len(segments))) if indices is None else set(indices)
    out = []
    for i, s in enumerate(segments):
        if i in idx:
            out.append(Segment(max(0.0, s.start + offset), max(0.0, s.end + offset), s.text,
                               [(max(0.0, w0 + offset), max(0.0, w1 + offset), w) for (w0, w1, w) in s.words]))
        else:
            out.append(s)
    return out


def validate(segments: List[Segment]) -> List[str]:
    """Return a list of human-readable timing problems (empty list == valid)."""
    problems = []
    prev_end = -1.0
    for i, s in enumerate(segments, 1):
        if s.start < 0 or s.end < 0:
            problems.append(f"#{i}: negative time")
        if s.end <= s.start:
            problems.append(f"#{i}: end <= start ({s.start:.3f} >= {s.end:.3f})")
        if s.start < prev_end - 1e-3:
            problems.append(f"#{i}: overlaps previous ({s.start:.3f} < {prev_end:.3f})")
        if not s.text.strip():
            problems.append(f"#{i}: empty text")
        prev_end = max(prev_end, s.end)
    return problems


# ---------- writers ----------
def _clean(text: str) -> str:
    return "\n".join(line.strip() for line in text.replace("\r", "").split("\n") if line.strip())


def to_srt(segments: List[Segment], max_chars: int = 42, rtl_mark: bool = True) -> str:
    out = []
    for i, s in enumerate(segments, 1):
        text = wrap_text(_clean(s.text), max_chars)
        if rtl_mark and is_rtl(text):
            # RLM at the start of each line keeps trailing punctuation on the correct side in players
            text = "\n".join(RLM + ln for ln in text.split("\n"))
        out.append(f"{i}\n{fmt_srt_time(s.start)} --> {fmt_srt_time(s.end)}\n{text}\n")
    return "\n".join(out)


def to_vtt(segments: List[Segment], max_chars: int = 42) -> str:
    out = ["WEBVTT", ""]
    for i, s in enumerate(segments, 1):
        text = wrap_text(_clean(s.text), max_chars)
        if is_rtl(text):
            text = "\n".join(RLM + ln for ln in text.split("\n"))
        out.append(f"{i}\n{fmt_vtt_time(s.start)} --> {fmt_vtt_time(s.end)}\n{text}\n")
    return "\n".join(out)


def to_txt(segments: List[Segment], timestamps: bool = False) -> str:
    lines = []
    for s in segments:
        t = " ".join(_clean(s.text).split("\n"))
        lines.append(f"[{fmt_vtt_time(s.start)}] {t}" if timestamps else t)
    return "\n".join(lines) + "\n"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def to_ass(segments: List[Segment], font: str = "Atlas Noto Sans Arabic", font_size: int = 48, width: int = 1920, height: int = 1080,
           primary: str = "&H00FFFFFF", outline: str = "&H00000000", outline_w: float = 3.0,
           bold: bool = True, margin_v: int = 60, max_chars: int = 42, box: bool = False) -> str:
    """ASS file for burn-in via libass. RTL lines get an RLM so bidi base direction is right-to-left."""
    border_style = 3 if box else 1
    back = "&H80000000"
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{font_size},{primary},&H000000FF,{outline},{back},{-1 if bold else 0},0,0,0,100,100,0,0,{border_style},{outline_w},1,2,40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for s in segments:
        text = wrap_text(_clean(s.text), max_chars)
        rtl = is_rtl(text)
        parts = [(RLM + ln if rtl else ln) for ln in text.split("\n")]
        body = "\\N".join(_ass_escape(p) for p in parts)
        lines.append(f"Dialogue: 0,{fmt_ass_time(s.start)},{fmt_ass_time(s.end)},Default,,0,0,0,,{body}")
    return header + "\n".join(lines) + "\n"


# ---------- reader ----------
_SRT_TIME = re.compile(r"(\d+:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d+:\d{2}:\d{2}[,.]\d{1,3})")


def parse_srt(text: str) -> List[Segment]:
    segs = []
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\ufeff", "").strip())
    for b in blocks:
        lines = b.split("\n")
        for j, ln in enumerate(lines):
            m = _SRT_TIME.search(ln)
            if m:
                body = "\n".join(lines[j + 1:]).replace(RLM, "").strip()
                segs.append(Segment(parse_time(m.group(1)), parse_time(m.group(2)), body))
                break
    return segs


def load_srt(path: str | Path) -> List[Segment]:
    return parse_srt(Path(path).read_text(encoding="utf-8-sig"))


def save(segments: List[Segment], path: str | Path, fmt: str | None = None, **kw) -> Path:
    path = Path(path)
    fmt = (fmt or path.suffix.lstrip(".")).lower()
    if fmt == "srt":
        data = to_srt(segments, **kw)
    elif fmt == "vtt":
        data = to_vtt(segments, **kw)
    elif fmt == "txt":
        data = to_txt(segments, **kw)
    elif fmt == "ass":
        data = to_ass(segments, **kw)
    else:
        raise ValueError(f"unknown format: {fmt}")
    path.parent.mkdir(parents=True, exist_ok=True)
    # UTF-8 with BOM for SRT: many Windows players (and old TVs) need it to show Arabic
    path.write_text(data, encoding="utf-8-sig" if fmt == "srt" else "utf-8")
    return path

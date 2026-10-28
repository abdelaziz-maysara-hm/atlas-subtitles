"""Fast unit tests (no model needed): python -m pytest tests/test_core.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pytest
from atlas_subtitles.core import subtitles as S
from atlas_subtitles.core.subtitles import Segment
from atlas_subtitles.core.transcribe import chunk_bounds, resegment, SR, _HALL_RE


def segs():
    return [Segment(0.0, 2.5, "مرحبا بكم في القناة"), Segment(2.4, 5.0, "النهارده هنتكلم عن حاجة مهمة"),
            Segment(6.0, 8.0, "Hello world")]


def test_time_formats():
    assert S.fmt_srt_time(3661.5) == "01:01:01,500"
    assert S.fmt_vtt_time(0.04) == "00:00:00.040"
    assert S.fmt_ass_time(62.257) == "0:01:02.25"  # centiseconds, truncated
    assert S.parse_time("00:01:02,250") == pytest.approx(62.25)
    assert S.parse_time("1:02.5") == pytest.approx(62.5)
    assert S.parse_time("12.75") == pytest.approx(12.75)


def test_rtl_detection():
    assert S.is_rtl("مرحبا") and not S.is_rtl("hello") and S.is_rtl("Hi يا جماعة")


def test_sort_and_fix_removes_overlap():
    out = S.sort_and_fix(segs())
    assert not S.validate(out)
    assert out[0].end <= out[1].start


def test_srt_roundtrip(tmp_path):
    fixed = S.sort_and_fix(segs())
    p = S.save(fixed, tmp_path / "a.srt", "srt")
    raw = p.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")            # BOM for Windows players/Notepad
    assert "\u200f" in raw.decode("utf-8-sig")         # RLM before Arabic lines
    back = S.load_srt(str(p))
    assert [b.text.replace("\n", " ") for b in back] == [s.text for s in fixed]
    assert all("\u200f" not in b.text for b in back)


def test_vtt_and_txt_and_ass():
    fixed = S.sort_and_fix(segs())
    assert S.to_vtt(fixed).startswith("WEBVTT")
    assert S.to_txt(fixed).count("\n") >= 2
    ass = S.to_ass(fixed, font="Amiri", font_size=40, width=1280, height=720, box=True)
    assert "PlayResX: 1280" in ass and "Amiri" in ass and ass.count("Dialogue:") == 3


def test_split_merge_shift():
    s = Segment(0, 4, "واحد اتنين تلاتة أربعة")
    lst = S.split_segment([s], 0)
    a, b = lst
    assert a.end <= b.start and 0 < a.end < 4 and a.text and b.text
    m = S.merge_segments(lst, 0)
    assert len(m) == 1 and m[0].start == 0 and m[0].end == 4 and m[0].text.split() == s.text.split()
    lst = S.shift_segments([Segment(1, 2, "x"), Segment(3, 4, "y")], -1.5)
    assert lst[0].start == 0 and lst[1].start == pytest.approx(1.5)  # clamped at 0
    lst = S.shift_segments([Segment(1, 2, "x"), Segment(3, 4, "y")], 2, [1])
    assert lst[0].start == 1 and lst[1].start == 5


def test_wrap_two_lines():
    t = S.wrap_text("دي جملة طويلة شوية علشان نجرب تقسيمها على سطرين بشكل متوازن", 42)
    assert 1 <= t.count("\n") + 1 <= 2


def test_chunk_bounds_cover_everything():
    audio = np.zeros(SR * 1500, dtype=np.float32)
    audio[::7] = 0.3
    b = chunk_bounds(audio, 600)
    assert b[0][0] == 0 and b[-1][1] == len(audio)
    assert all(x[1] == y[0] for x, y in zip(b, b[1:]))
    assert len(b) == 3


def test_resegment_limits():
    long = [Segment(0, 20, " ".join(["كلمة"] * 60))]
    out = resegment(long, max_chars=84, max_dur=7)
    assert len(out) > 1 and all(len(s.text) <= 90 for s in out)


def test_hallucination_filter():
    assert _HALL_RE.search("اشتركوا في القناة")
    assert not _HALL_RE.search("النهارده الجو حلو")


def test_linux_bidi_display_order(monkeypatch):
    pytest.importorskip("bidi")
    from atlas_subtitles.gui import bidi_fix
    monkeypatch.setattr(bidi_fix, "NEEDED", True)
    # words reversed (first word ends up on the right), letters inside a word stay in logical order
    assert bidi_fix.vis("أ ب ج") == "ج ب أ"
    assert bidi_fix.vis("مرحبا بكم") == "بكم مرحبا"
    assert bidi_fix.vis("تم الحفظ: \u202a/tmp/a.mp4\u202c") == "/tmp/a.mp4 :الحفظ تم"
    assert bidi_fix.vis("hello") == "hello"

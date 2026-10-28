"""Display-only fix for Arabic word order on Linux.

Tk on Windows (GDI/Uniscribe) and macOS (CoreText) lay out right-to-left text themselves. Tk 8.6 on X11 shapes
each word correctly but draws the words left-to-right (verified under Xvfb, see tests/RESULTS.md), so on Linux
we pre-order the words with the Unicode bidi algorithm. Only used for read-only widgets (labels, table rows);
text the user edits is left in logical order."""
from __future__ import annotations

import re
import sys
import textwrap

NEEDED = sys.platform.startswith("linux")
_RTL = re.compile(r"[\u0590-\u08FF\uFB1D-\uFDFF\uFE70-\uFEFF]")
# letters + diacritics (not Arabic punctuation like ، ؟ and not digits): runs that Tk itself reverses
_LETTER_RUN = re.compile(r"[\u0621-\u065F\u066E-\u06D3\u06D5-\u06FF\u0670\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF\u200c\u200d]+")

try:
    from bidi.algorithm import get_display
except Exception:  # python-bidi not installed: leave text alone
    get_display = None


class VStr(str):
    """Visual-order string that remembers its logical text (needed to wrap lines correctly)."""
    logical: str = ""


def vis(text: str) -> str:
    if not NEEDED or get_display is None or not text or not _RTL.search(text):
        return text
    r = VStr(_vis(text))
    r.logical = text
    return r


def wrap_vis(text: str, chars: int) -> str:
    """Tk wraps the *visual* string from the left, which puts an RTL sentence's end on the first line.
    Wrap the logical text ourselves, then reorder each line."""
    if not isinstance(text, VStr):
        return text
    lines = []
    for para in text.logical.split("\n"):
        lines += textwrap.wrap(para, chars) or [""]
    return "\n".join(_vis(l) if _RTL.search(l) else l for l in lines)


def _vis(text: str) -> str:
    out = []
    for line in text.split("\n"):
        v = get_display(line, base_dir="R")
        v = _LETTER_RUN.sub(lambda m: m.group(0)[::-1], v)
        out.append(re.sub("[\u202a-\u202e\u2066-\u2069]", "", v))
    return "\n".join(out)

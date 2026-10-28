"""Text normalisation used only for scoring (WER/CER)."""
import re
import unicodedata

_DIAC = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def norm_basic(t: str) -> str:
    t = unicodedata.normalize("NFKC", t).replace("\u200f", "")
    t = _DIAC.sub("", t)
    t = _PUNCT.sub(" ", t)
    return " ".join(t.lower().split())


def norm_arabic(t: str) -> str:
    """basic + common orthographic variants Whisper and humans mix up (أ/إ/آ/ا, ى/ي, ة/ه)."""
    t = norm_basic(t)
    t = re.sub("[إأآٱ]", "ا", t)
    t = t.replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي")
    t = re.sub(r"(\w)\1{2,}", r"\1\1", t)
    return t

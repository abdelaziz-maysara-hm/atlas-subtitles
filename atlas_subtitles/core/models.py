"""Whisper model catalogue, local cache, and first-use download from Hugging Face."""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from .errors import AtlasError

os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# approximate download sizes (MB) of the CTranslate2 conversions published by Systran (MIT)
MODELS = {
    "tiny": 75,
    "base": 145,
    "small": 484,
    "medium": 1530,
    "large-v3-turbo": 1620,
}
DEFAULT_MODEL = "small"
REPO = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}


def models_dir() -> Path:
    env = os.environ.get("ATLAS_MODELS_DIR")
    if env:
        p = Path(env)
    elif sys.platform == "win32":
        p = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AtlasSubtitles" / "models"
    else:
        p = Path.home() / ".cache" / "atlas-subtitles" / "models"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _dir_size(p: Path) -> int:
    total = 0
    for root, _d, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def local_path(name: str) -> Optional[str]:
    """Path of an already-downloaded model, or of a user-supplied model folder; None if missing."""
    if os.path.isdir(name) and os.path.isfile(os.path.join(name, "model.bin")):
        return name
    manual = models_dir() / name  # a model folder copied by hand, e.g. ...\models\small\model.bin
    if (manual / "model.bin").is_file():
        return str(manual)
    from faster_whisper.utils import download_model
    try:
        return download_model(REPO.get(name, name), cache_dir=str(models_dir()), local_files_only=True)
    except Exception:
        return None


def is_downloaded(name: str) -> bool:
    return local_path(name) is not None


def ensure_model(name: str, progress: Optional[Callable[[float, int], None]] = None,
                 cancel: Optional[threading.Event] = None) -> str:
    """Return a local folder for `name`, downloading it on first use.

    progress(fraction, mb_done) is called about twice a second during download.
    Raises AtlasError('model_download_failed') with a readable reason when offline / blocked.
    """
    p = local_path(name)
    if p:
        return p
    if name not in REPO:
        raise AtlasError("model_unknown", name)
    from faster_whisper.utils import download_model

    expected = MODELS.get(name, 500) * 1024 * 1024
    target = models_dir() / ("models--" + REPO[name].replace("/", "--"))
    done = threading.Event()
    result: dict = {}

    def worker():
        try:
            result["path"] = download_model(REPO[name], cache_dir=str(models_dir()))
        except BaseException as e:  # noqa: BLE001 - report every failure to the UI
            result["error"] = e
        finally:
            done.set()

    threading.Thread(target=worker, daemon=True).start()
    while not done.wait(0.5):
        if cancel is not None and cancel.is_set():
            from .errors import Cancelled
            raise Cancelled()  # partial files stay in the cache; HF resumes them next time
        if progress:
            size = _dir_size(target) if target.exists() else 0
            progress(min(0.99, size / expected), size // (1024 * 1024))
    if "error" in result:
        e = result["error"]
        msg = f"{type(e).__name__}: {e}"
        raise AtlasError("model_download_failed", msg[:500])
    if progress:
        progress(1.0, MODELS.get(name, 0))
    return result["path"]

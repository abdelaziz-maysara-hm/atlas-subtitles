"""FFmpeg helpers: locate binaries, probe media, extract audio, burn in subtitles."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .errors import AtlasError, Cancelled

ProgressCB = Optional[Callable[[float], None]]  # fraction 0..1


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _find(name: str) -> Optional[str]:
    here = app_dir()
    exe = name + (".exe" if sys.platform == "win32" else "")
    for p in [here / exe, here / "ffmpeg" / exe, here / "ffmpeg" / "bin" / exe, here / "_internal" / exe]:
        if p.exists():
            return str(p)
    return shutil.which(name)


def find_ffmpeg() -> Optional[str]:
    return os.environ.get("ATLAS_FFMPEG") or _find("ffmpeg")


def find_ffprobe() -> Optional[str]:
    return os.environ.get("ATLAS_FFPROBE") or _find("ffprobe")


def _popen_kwargs() -> dict:
    kw = {}
    if sys.platform == "win32":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kw["startupinfo"] = si
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return kw


@dataclass
class MediaInfo:
    path: str
    duration: float
    has_audio: bool
    has_video: bool
    width: int = 0
    height: int = 0
    size_bytes: int = 0


def probe(path: str | Path) -> MediaInfo:
    path = str(path)
    if not os.path.isfile(path):
        raise AtlasError("file_not_found", path)
    ff = find_ffmpeg()
    if not ff:
        raise AtlasError("ffmpeg_missing")
    fp = find_ffprobe()
    size = os.path.getsize(path)
    if fp:
        r = subprocess.run([fp, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", **_popen_kwargs())
        if r.returncode != 0:
            raise AtlasError("not_media", r.stderr.strip()[-400:])
        data = json.loads(r.stdout or "{}")
        streams = data.get("streams", [])
        a = [s for s in streams if s.get("codec_type") == "audio"]
        v = [s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")]
        dur = float(data.get("format", {}).get("duration") or 0) or max(
            [float(s.get("duration") or 0) for s in streams] or [0])
        w = int(v[0].get("width", 0)) if v else 0
        h = int(v[0].get("height", 0)) if v else 0
        return MediaInfo(path, dur, bool(a), bool(v), w, h, size)
    # fallback: parse `ffmpeg -i` banner (ffprobe not shipped)
    r = subprocess.run([ff, "-hide_banner", "-i", path], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", **_popen_kwargs())
    err = r.stderr
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", err)
    if not m and "Invalid data" in err:
        raise AtlasError("not_media", err[-400:])
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0
    vm = re.search(r"Video: .*?(\d{2,5})x(\d{2,5})", err)
    return MediaInfo(path, dur, "Audio:" in err, bool(vm), int(vm.group(1)) if vm else 0,
                     int(vm.group(2)) if vm else 0, size)


def _run_with_progress(cmd: list, duration: float, progress: ProgressCB, cancel: Optional[threading.Event],
                       cwd: Optional[str] = None) -> str:
    """Run ffmpeg with `-progress pipe:1`, report fraction, support cancel. Returns stderr tail."""
    cmd = cmd[:1] + ["-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats"] + cmd[1:]
    err_file = tempfile.TemporaryFile()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err_file, cwd=cwd, **_popen_kwargs())
    try:
        for raw in proc.stdout:
            if cancel is not None and cancel.is_set():
                proc.kill()
                proc.wait()
                raise Cancelled()
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    t = int(line.split("=", 1)[1]) / 1_000_000
                except ValueError:
                    continue
                if progress and duration > 0:
                    progress(min(1.0, max(0.0, t / duration)))
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
    err_file.seek(0)
    tail = err_file.read().decode("utf-8", "replace")[-2000:]
    err_file.close()
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    if proc.returncode != 0:
        raise AtlasError("ffmpeg_failed", tail)
    if progress:
        progress(1.0)
    return tail


def extract_audio(src: str | Path, dst_wav: str | Path, info: Optional[MediaInfo] = None,
                  progress: ProgressCB = None, cancel: Optional[threading.Event] = None) -> Path:
    """Decode the first audio stream to 16 kHz mono 16-bit WAV (what Whisper expects)."""
    info = info or probe(src)
    if not info.has_audio:
        raise AtlasError("no_audio", str(src))
    ff = find_ffmpeg()
    dst_wav = Path(dst_wav)
    cmd = [ff, "-i", str(src), "-map", "0:a:0", "-vn", "-sn", "-dn", "-ac", "1", "-ar", "16000",
           "-c:a", "pcm_s16le", "-f", "wav", str(dst_wav)]
    _run_with_progress(cmd, info.duration, progress, cancel)
    if not dst_wav.exists() or dst_wav.stat().st_size <= 44:
        raise AtlasError("no_audio", "decoded audio is empty")
    return dst_wav


def fonts_dir() -> Path:
    for p in [app_dir() / "assets" / "fonts", app_dir() / "_internal" / "assets" / "fonts"]:
        if p.is_dir():
            return p
    return app_dir() / "assets" / "fonts"


def burn_in(src: str | Path, ass_text: str, dst: str | Path, info: Optional[MediaInfo] = None,
            crf: int = 20, preset: str = "veryfast", progress: ProgressCB = None,
            cancel: Optional[threading.Event] = None) -> Path:
    """Render subtitles into the picture with libass (correct Arabic shaping + bidi).

    The .ass file and fonts are referenced by *relative* paths from a temp working directory, which
    sidesteps the painful escaping of Windows drive letters (C:) inside FFmpeg filter strings.
    """
    info = info or probe(src)
    if not info.has_video:
        raise AtlasError("no_video", str(src))
    ff = find_ffmpeg()
    dst = Path(dst).resolve()
    work = Path(tempfile.mkdtemp(prefix="atlas_burn_"))
    try:
        (work / "subs.ass").write_text(ass_text, encoding="utf-8")
        fdir = work / "fonts"
        fdir.mkdir()
        for f in fonts_dir().glob("*.ttf"):
            shutil.copy2(f, fdir / f.name)
        vf = "subtitles=subs.ass:fontsdir=fonts"
        cmd = [ff, "-i", str(Path(src).resolve()), "-vf", vf, "-map", "0:v:0", "-map", "0:a?",
               "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(dst)]
        try:
            _run_with_progress(cmd, info.duration, progress, cancel, cwd=str(work))
        except AtlasError as e:
            if e.code == "ffmpeg_failed" and "libx264" in e.detail:
                # LGPL builds have no libx264: fall back to the built-in mpeg4 encoder
                cmd = [c if c != "libx264" else "mpeg4" for c in cmd]
                i = cmd.index("-preset"); del cmd[i:i + 2]
                i = cmd.index("-crf"); cmd[i:i + 2] = ["-q:v", "3"]
                _run_with_progress(cmd, info.duration, progress, cancel, cwd=str(work))
            else:
                raise
    except Cancelled:
        try:
            dst.unlink()
        except OSError:
            pass
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return dst

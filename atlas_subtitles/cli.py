"""Command line: python -m atlas_subtitles.cli VIDEO [--model small] [--lang ar] [--burn]"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .core import models, pipeline, subtitles
from .core.errors import AtlasError


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="atlas-subtitles", description="Offline automatic subtitles (Arabic-first)")
    ap.add_argument("input")
    ap.add_argument("--model", default=models.DEFAULT_MODEL, help="tiny|base|small|medium|large-v3-turbo or a folder")
    ap.add_argument("--lang", default="auto", help="auto, ar, en, fr, ...")
    ap.add_argument("--dialect", default="msa", choices=["msa", "egyptian"])
    ap.add_argument("--out", default=None, help="output folder (default: next to the input)")
    ap.add_argument("--formats", default="srt,vtt,txt")
    ap.add_argument("--burn", action="store_true", help="also write VIDEO_subtitled.mp4 with hard subtitles")
    ap.add_argument("--font", default="Noto Sans", choices=["Noto Sans", "Amiri"])
    ap.add_argument("--srt-in", default=None, help="skip transcription; burn/convert this SRT")
    a = ap.parse_args(argv)

    src = Path(a.input)
    out_dir = Path(a.out) if a.out else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / src.stem
    last = [0.0]

    def prog(stage, frac, detail):
        now = time.time()
        if now - last[0] > 1 or frac >= 1:
            last[0] = now
            print(f"\r[{stage:10s}] {frac * 100:5.1f}% {detail}   ", end="", file=sys.stderr, flush=True)

    try:
        if a.srt_in:
            segs = subtitles.load_srt(a.srt_in)
            res = None
        else:
            res = pipeline.transcribe_file(str(src), a.model, None if a.lang == "auto" else a.lang, a.dialect, prog)
            segs = res.segments
            print(file=sys.stderr)
            print(f"language={res.language} p={res.language_probability:.2f} duration={res.duration:.1f}s "
                  f"timings={ {k: round(v, 2) for k, v in res.timings.items()} }", file=sys.stderr)
        for p in pipeline.export_all(segs, base, [f.strip() for f in a.formats.split(",") if f.strip()]):
            print(p)
        if a.burn:
            dst = base.parent / (src.stem + "_subtitled.mp4")
            pipeline.burn(str(src), segs, str(dst), font=a.font,
                          progress=lambda f: prog("burn", f, ""))
            print(file=sys.stderr)
            print(dst)
    except AtlasError as e:
        print(f"\nERROR {e.code}: {e.detail}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

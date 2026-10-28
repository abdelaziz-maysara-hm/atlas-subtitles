"""Edge-case checks of the core (no GUI). usage: python tests/edge_tests.py TESTDATA_DIR [long_model]
Prints PASS/FAIL lines; exit code = number of failures."""
import os, subprocess, sys, tempfile, threading, time, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atlas_subtitles.core import pipeline, subtitles, models, ffmpeg
from atlas_subtitles.core.errors import AtlasError, Cancelled

D = Path(sys.argv[1]); LONG_MODEL = sys.argv[2] if len(sys.argv) > 2 else "base"
fails = 0
def check(name, ok, info=""):
    global fails
    fails += (not ok); print(("PASS " if ok else "FAIL ") + name + ("  | " + str(info) if info else ""), flush=True)

def expect_err(name, code, fn):
    try:
        fn(); check(name, False, "no error raised")
    except AtlasError as e:
        check(name, e.code == code, f"code={e.code} detail={str(e.detail)[:80]!r}")
    except Exception as e:
        check(name, False, f"{type(e).__name__}: {e}")

expect_err("missing file", "file_not_found", lambda: pipeline.transcribe_file(str(D / "nope.mp4"), "tiny"))
expect_err("not a media file", "not_media", lambda: pipeline.transcribe_file(str(D / "garbage.mp4"), "tiny"))
expect_err("video without audio track", "no_audio", lambda: pipeline.transcribe_file(str(D / "noaudio.mp4"), "tiny"))
expect_err("silent audio track", "no_speech", lambda: pipeline.transcribe_file(str(D / "silent.mp4"), "small", "ar"))
expect_err("burn on audio-only file", "no_video",
           lambda: pipeline.burn(str(D / "msa_news.mp3"), [subtitles.Segment(0, 1, "اختبار")], "/tmp/x.mp4"))

# model download failure (offline): empty models dir + unreachable endpoint
env = dict(os.environ, ATLAS_MODELS_DIR=tempfile.mkdtemp(), HF_ENDPOINT="http://127.0.0.1:9", HF_HUB_ETAG_TIMEOUT="3",
           HF_HUB_DOWNLOAD_TIMEOUT="3")
code = ("import sys; sys.path.insert(0,'.');from atlas_subtitles.core import models\n"
        "from atlas_subtitles.core.errors import AtlasError\n"
        "try:\n models.ensure_model('tiny'); print('NOERR')\nexcept AtlasError as e: print('CODE', e.code, str(e.detail)[:120])")
t0 = time.time()
r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=180)
check("offline model download -> clean error", "CODE model_download_failed" in r.stdout,
      f"{time.time()-t0:.1f}s {r.stdout.strip()[:160]} {r.stderr.strip()[-200:]}")

# long file: chunking, monotonic progress, valid SRT
prog = []
t0 = time.time()
res = pipeline.transcribe_file(str(D / "long.mp4"), LONG_MODEL, "ar",
                               progress=lambda st, f, d: prog.append((round(time.time() - t0, 1), st, round(f, 3))))
wall = time.time() - t0
fr = [p[2] for p in prog]
check("long file progress monotonic", all(b >= a - 1e-9 for a, b in zip(fr, fr[1:])) and fr[-1] == 1.0,
      f"{len(prog)} updates, first={prog[:3]}")
segs = res.segments
probs = subtitles.validate(segs)
check("long file segments valid (no overlap/neg)", not probs, probs[:3])
check("long file covers whole duration", segs and segs[-1].end > res.duration - 30 and segs[0].start < 30,
      f"{len(segs)} segs, first {segs[0].start:.1f}s last end {segs[-1].end:.1f}s of {res.duration:.0f}s")
check("long file timings", True, f"model={LONG_MODEL} wall={wall:.1f}s RTF={wall/res.duration:.3f} {json.dumps({k: round(v,1) for k,v in res.timings.items()})}")
out = Path(tempfile.mkdtemp()) / "long"
files = pipeline.export_all(segs, out)
back = subtitles.load_srt(str(out.with_suffix(".srt")))
check("SRT round-trip", len(back) == len(segs) and all(abs(a.start - b.start) < 0.002 and a.text.replace("\n", " ") == b.text.replace("\n", " ") for a, b in zip(segs, back)),
      f"{len(back)} vs {len(segs)}")
# chunk boundary duplicates: identical consecutive texts
dups = sum(1 for a, b in zip(segs, segs[1:]) if a.text.strip() == b.text.strip())
check("no duplicated consecutive captions", dups == 0, f"dups={dups}")

# cancel during transcription
ev = threading.Event(); threading.Timer(4.0, ev.set).start(); t0 = time.time()
try:
    pipeline.transcribe_file(str(D / "long.mp4"), LONG_MODEL, "ar", cancel=ev); check("cancel transcription", False, "finished")
except Cancelled:
    check("cancel transcription", time.time() - t0 < 4.0 + 15, f"stopped after {time.time()-t0:.1f}s (cancel at 4s)")
# cancel during burn
ev = threading.Event(); threading.Timer(3.0, ev.set).start(); dst = "/tmp/edge_burn_cancel.mp4"; t0 = time.time()
try:
    pipeline.burn(str(D / "long.mp4"), segs, dst, cancel=ev); check("cancel burn", False, "finished")
except Cancelled:
    check("cancel burn", not Path(dst).exists() and time.time() - t0 < 10, f"{time.time()-t0:.1f}s, partial removed={not Path(dst).exists()}")
print("FAILURES:", fails)
sys.exit(fails)

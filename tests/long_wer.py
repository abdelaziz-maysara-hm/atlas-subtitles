"""WER on the 16.7-min concatenated FLEURS video (20 clips x5, alphabetical order) - exercises chunking."""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1])); sys.path.insert(0, str(Path(__file__).parent))
import jiwer
from arabic_norm import norm_arabic
from atlas_subtitles.core import pipeline
TD = Path(sys.argv[1])
man = {Path(m["file"]).name: m["ref"] for m in json.load(open(TD / "fleurs" / "manifest.json"))}
ref = " ".join([man[n] for n in sorted(man)] * 5)
for model in sys.argv[2].split(","):
    t0 = time.time()
    r = pipeline.transcribe_file(str(TD / "long.mp4"), model, "ar")
    hyp = " ".join(s.text for s in r.segments)
    w = jiwer.wer(norm_arabic(ref), norm_arabic(hyp)); c = jiwer.cer(norm_arabic(ref), norm_arabic(hyp))
    print(f"{model}: WER={w:.3f} CER={c:.3f} wall={time.time()-t0:.0f}s RTF={(time.time()-t0)/r.duration:.3f} segs={len(r.segments)}", flush=True)

"""Measure WER/CER and speed on real clips.  usage: python tests/eval_wer.py tiny,base,small batched,sequential"""
import json, os, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import jiwer
from arabic_norm import norm_basic, norm_arabic
from atlas_subtitles.core import models
from atlas_subtitles.core.transcribe import Transcriber

TD = Path(__file__).resolve().parents[2] / "testdata"
sys.path.insert(0, str(TD))
from texts import CLIPS

QURAN = ("بسم الله الرحمن الرحيم الحمد لله رب العالمين الرحمن الرحيم مالك يوم الدين إياك نعبد وإياك نستعين "
         "اهدنا الصراط المستقيم صراط الذين أنعمت عليهم غير المغضوب عليهم ولا الضالين")


def wav16(src: Path) -> Path:
    dst = TD / "wav16" / (src.stem + ".wav")
    if not dst.exists():
        dst.parent.mkdir(exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst)], check=True)
    return dst


def items():
    out = []
    for name, (voice, lang, text) in CLIPS.items():
        group = "tts_egyptian" if name.startswith("eg_") else ("tts_msa" if lang == "ar" else "tts_english")
        out.append((group, name, wav16(TD / f"{name}.mp3"), text, lang))
    out.append(("human_quran", "fatiha_husary", TD / "quran_fatiha_husary.wav", QURAN, "ar"))
    for i, it in enumerate(json.load(open(TD / "fleurs" / "manifest.json"))):
        out.append(("human_msa_fleurs", f"fleurs{i:02d}", wav16(TD / it["file"]), it["ref"], "ar"))
    return out


def main():
    sizes = (sys.argv[1] if len(sys.argv) > 1 else "small").split(",")
    engines = (sys.argv[2] if len(sys.argv) > 2 else "batched").split(",")
    dialect = sys.argv[3] if len(sys.argv) > 3 else "msa"
    compute = sys.argv[4] if len(sys.argv) > 4 else "int8"
    res = []
    for size in sizes:
        t0 = time.time(); tr = Transcriber(models.ensure_model(size), compute_type=compute); load = time.time() - t0
        for eng in engines:
            for group, name, wav, ref, lang in items():
                d = dialect if (dialect != "msa" and group == "tts_egyptian") else "msa"
                t0 = time.time()
                r = tr.transcribe(str(wav), language=lang, engine=eng, dialect=d)
                el = time.time() - t0
                hyp = " ".join(s.text for s in r.segments)
                n = norm_arabic if lang == "ar" else norm_basic
                res.append(dict(model=size, compute=compute, engine=eng, dialect=d, group=group, clip=name, dur=r.duration, secs=el,
                                wer=jiwer.wer(n(ref), n(hyp)), cer=jiwer.cer(n(ref), n(hyp)),
                                wer_basic=jiwer.wer(norm_basic(ref), norm_basic(hyp)), hyp=hyp, ref=ref, load=load))
                print(f"{size:6s} {eng:10s} {group:17s} {name:14s} WER={res[-1]['wer']:.3f} CER={res[-1]['cer']:.3f} RTF={el / r.duration:.3f}", flush=True)
    out = Path(__file__).resolve().parent / "results" / f"wer_{'-'.join(sizes)}_{'-'.join(engines)}_{dialect}_{compute}.json"
    out.parent.mkdir(exist_ok=True)
    json.dump(res, open(out, "w"), ensure_ascii=False, indent=1)
    # summary: corpus-level WER per group (total errors / total ref words)
    import collections
    agg = collections.defaultdict(lambda: [0, 0, 0.0, 0.0])
    for r in res:
        n = norm_arabic if r["group"] != "tts_english" else norm_basic
        refw = len(n(r["ref"]).split())
        k = (r["model"], r["engine"], r["group"])
        agg[k][0] += r["wer"] * refw; agg[k][1] += refw; agg[k][2] += r["secs"]; agg[k][3] += r["dur"]
    print("\nmodel  engine     group             WER    RTF")
    for k, (e, w, s, d) in sorted(agg.items()):
        print(f"{k[0]:6s} {k[1]:10s} {k[2]:17s} {e / w:.3f}  {s / d:.3f}")
    print("saved", out)


if __name__ == "__main__":
    main()

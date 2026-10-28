# Atlas Subtitles: test results

Test machine: Linux box, Intel Xeon (Sapphire Rapids, AMX), 8 vCPU, CPU only. The box was shared and loaded (load average 4–16), so speeds are noisy and probably pessimistic. RTF = processing time / audio duration (lower is faster).
Versions: faster-whisper 1.2.1, ctranslate2 4.8.4, BatchedInferencePipeline (VAD, batch 4), **int8** unless noted.

## 1. Accuracy (WER, lower is better): `tests/eval_wer.py`

Groups:
- human_msa_fleurs: 20 real read-speech clips (Google FLEURS ar_eg test set)
- human_quran: real recitation
- tts_egyptian: Egyptian dialect, synthesised with edge-tts (Salma/Shakir)
- tts_msa: MSA, synthesised
- tts_english: English, synthesised

| model | FLEURS MSA | Quran | Egyptian (TTS) | MSA (TTS) | English | RTF (FLEURS) |
|---|---|---|---|---|---|---|
| tiny   | 0.689 | 0.655 | 0.633 | 0.316 | 0.000 | 0.054 |
| base   | 0.495 | 0.345 | 0.517 | 0.215 | 0.000 | 0.094 |
| small  | 0.289 | 0.103 | 0.233 | 0.076 | 0.000 | 0.203 |
| medium | 0.176 | 0.069 | 0.233 | 0.025 | 0.000 | 0.599 |

float32 for comparison: small 0.286 / 0.069 / 0.217–0.233 / 0.076 / 0; medium 0.170 / 0.069 / 0.233 / 0.013 / 0.
So int8 costs almost no accuracy and uses about 2.5x less RAM.
Whisper's WER on Arabic is inflated by spelling variants (hamza, taa marbuta, alef maqsura). The scorer normalises these, but some remain.

Egyptian prompt ("dialect: Egyptian" initial_prompt): marginal effect (small 0.217 with the prompt vs 0.233 without).
Whisper writes Egyptian speech partly in MSA spelling. Expect good, editable drafts, not perfect dialect transcription.

## 2. Long file: `tests/long_wer.py`
The test file is 1004 s (16.7 min): the 20 FLEURS clips repeated 5 times, concatenated.

| model | WER | CER | wall | RTF | segments |
|---|---|---|---|---|---|
| tiny (earlier run)  | 0.668 | 0.360 | 16 s  | 0.016 | – |
| base (earlier run)  | 0.548 | 0.314 | 37 s  | 0.037 | – |
| small (int8)  | 0.339 | 0.177 | 67 s  | 0.066 | 153 |
| medium (int8) | 0.242 | 0.142 | 179 s | 0.178 | 151 |

Checks on all of these runs:
- No negative or overlapping timings.
- Coverage from 0.4 s to 1003.4 s.
- No duplicated consecutive captions (whisper's repetition-loop failure).
- SRT write/read round-trip is exact.

## 3. Huge file
The file is 3 hours (10 800 s), 97 MB mp4, run with tiny int8:
- probe 0.08 s, audio extraction 4.3 s, 18 chunks of 10 min
- 1428 segments in 225 s wall (RTF 0.021)
- peak RSS 1.16 GB (the 16 kHz wav is memory-mapped, not loaded)
- timings valid, last caption ends at 10 787.8 s

## 4. Resources per model
Measured on a 21.5 s clip, int8, including model load.

| model | download | peak RAM | wall | float32 peak RAM |
|---|---|---|---|---|
| tiny   | 75 MB   | 308 MB  | 1.4 s | 493 MB |
| base   | 145 MB  | 389 MB  | 1.7 s | 674 MB |
| small  | 484 MB  | 799 MB  | 3.6 s | 2098 MB |
| medium | 1530 MB | 2155 MB | 9.5 s | 6054 MB (was OOM-killed at 7.4 GB on the long eval) |

## 5. Edge cases: `tests/edge_tests.py` (14/14 pass), `tests/gui_edge.py`
- Errors come back as clean codes, not tracebacks: missing file, non-media file, video with no audio track, silent audio (no_speech), burn requested on audio-only input (no_video), model download while offline (fails in 0.3 s).
- Progress is monotonic.
- Cancel during transcription stops within about 1.7–4.6 s; the delay is one batch.
- Cancel during burn-in stops in 0.7–3.2 s and the partial output file is deleted.
- Offline use works with a copied model folder and HF_HUB_OFFLINE=1.
- GUI: each error dialog is shown exactly once (a double dialog on a garbage file was fixed).

## 6. Findings and fixes
1. **int8 produced garbage on this CPU.** The cause is Intel MKL's AMX int8 kernels on Sapphire Rapids. Setting `MKL_ENABLE_INSTRUCTIONS=AVX512` before ctranslate2 loads (in `atlas_subtitles/__init__.py`) makes int8 deterministic and accurate: 3 repeated runs gave identical WER. `CT2_FORCE_CPU_ISA` alone does not fix it. The GUI keeps a "Compatibility mode (float32)" checkbox as an escape hatch.
2. **Cairo font in libass** rendered some isolated Arabic letters (ر و د ا) as boxes in burned subtitles. It was replaced by a static Bold instance of Noto Sans Arabic, renamed "Atlas Noto Sans Arabic". Amiri is offered as the second font. Burned frames were checked visually: shaping, tashkeel and RTL are correct.
3. **Tk on Linux/X11 doesn't do bidi.** Arabic words were shaped but laid out left-to-right. `gui/bidi_fix.py` reorders the text for display and pre-wraps multi-line labels. This is Linux only. Windows (Uniscribe) handles bidi natively, but that has not been verified here.
4. Smaller fixes:
   - The left panel was cut off on 768 px screens; it is now scrollable.
   - The shift-timing label was truncated; it now has its own row.
   - The 3 h file took 1.7 GB for audio alone; it is now memory-mapped.
   - The temp wav is now closed, so Windows can delete it.

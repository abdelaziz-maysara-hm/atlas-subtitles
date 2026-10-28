"""Entry point for the GUI (used by PyInstaller).

Hidden self-test for builds:  Atlas_Subtitles.exe --selftest MEDIA OUT.json [model]
transcribes MEDIA with the bundled ffmpeg + model and writes the result to OUT.json (no window)."""
import multiprocessing
import sys


def selftest(argv) -> int:
    import json, time, traceback
    media, out = argv[0], argv[1]
    model = argv[2] if len(argv) > 2 else "tiny"
    rep = {"ok": False}
    try:
        from atlas_subtitles.core import ffmpeg, pipeline
        rep["ffmpeg"] = ffmpeg.find_ffmpeg()
        rep["fonts"] = str(ffmpeg.fonts_dir())
        t0 = time.time()
        r = pipeline.transcribe_file(media, model)
        rep.update(ok=True, language=r.language, segments=[s.text for s in r.segments], seconds=time.time() - t0)
    except Exception as e:  # report everything, this is a diagnostic
        rep["error"] = f"{type(e).__name__}: {e}"
        rep["trace"] = traceback.format_exc()
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if len(sys.argv) > 3 and sys.argv[1] == "--selftest":
        sys.exit(selftest(sys.argv[2:]))
    from atlas_subtitles.gui.app import main
    main()

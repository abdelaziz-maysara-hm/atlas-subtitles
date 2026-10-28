# Third-party components / مكونات من أطراف أخرى

| Component | Use | License |
|---|---|---|
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | speech recognition engine | MIT |
| [CTranslate2](https://github.com/OpenNMT/CTranslate2) | inference runtime (bundles Intel MKL / oneDNN) | MIT (MKL: Intel Simplified Software License) |
| Whisper model weights (OpenAI, converted by [Systran](https://huggingface.co/Systran)) | downloaded on first use, not shipped | MIT |
| Silero VAD (inside faster-whisper, via onnxruntime) | speech detection | MIT |
| [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) | GUI | MIT |
| [tkinterdnd2](https://github.com/Eliav2/tkinterdnd2) | drag & drop | MIT |
| [FFmpeg](https://ffmpeg.org) (BtbN `win64-gpl` build, shipped as separate ffmpeg.exe / ffprobe.exe) | audio extraction, burning subtitles (libass, libx264) | **GPL v3** for this build |
| Amiri font | burned subtitles | SIL OFL 1.1 |
| Noto Sans Arabic font (static Bold instance, renamed) | burned subtitles | SIL OFL 1.1 |
| Python, Tcl/Tk | runtime | PSF / Tcl license |

## License of this app — owner decision pending / رخصة التطبيق — لم تُحدد بعد

No license file has been added on purpose; the owner chooses. Notes for that decision:

- The FFmpeg build that the Windows package ships is **GPL** (it contains libx264). Shipping it next to the app is
  fine with any app license as long as the zip also offers the FFmpeg source / a link to the exact build and its
  license (BtbN publishes both). If you want to avoid GPL completely, switch the workflow to an **LGPL** FFmpeg build
  (`ffmpeg-master-latest-win64-lgpl.zip`) — burning then falls back to the `mpeg4` encoder automatically (bigger files,
  lower quality), because libx264 is GPL-only.
- Free code signing (e.g. SignPath Foundation) requires an OSI-approved open-source license (MIT, Apache-2.0, GPL...).
  Without signing, Windows SmartScreen shows "Windows protected your PC" on first run (More info → Run anyway).
- Everything else above is permissive (MIT / OFL), so MIT or Apache-2.0 for the app code are both straightforward.

Test data (FLEURS, CC-BY-4.0; Quran recitation from everyayah.com; TTS clips) is used only for local tests and is **not** in the repo or the package.

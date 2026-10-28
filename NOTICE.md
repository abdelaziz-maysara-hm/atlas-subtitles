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

## License of this app / رخصة التطبيق

The app's own code is **MIT** (see [LICENSE](LICENSE)). The components above keep their own licenses.

- The FFmpeg build that the Windows package ships is **GPL v3** (it contains libx264). It is shipped as separate,
  unmodified programs (`ffmpeg.exe`, `ffprobe.exe`) next to the app, not linked into it. The zip includes FFmpeg's license
  text as `FFmpeg-LICENSE.txt`. Corresponding source: FFmpeg https://github.com/FFmpeg/FFmpeg and the build scripts
  https://github.com/BtbN/FFmpeg-Builds (the exact build is from the `latest` release on the build date). Whoever
  redistributes the zip should check they meet the GPL's source-offer terms; this has not been reviewed by a lawyer. If you want to avoid GPL completely, switch the workflow to an **LGPL** FFmpeg build
  (`ffmpeg-master-latest-win64-lgpl.zip`) — burning then falls back to the `mpeg4` encoder automatically (bigger files,
  lower quality), because libx264 is GPL-only.
- Free code signing (e.g. SignPath Foundation) requires an OSI-approved open-source license (MIT, Apache-2.0, GPL...).
  Without signing, Windows SmartScreen shows "Windows protected your PC" on first run (More info → Run anyway).
- Everything else above is permissive (MIT / OFL), so MIT or Apache-2.0 for the app code are both straightforward.

Test data (FLEURS, CC-BY-4.0; Quran recitation from everyayah.com; TTS clips) is used only for local tests and is **not** in the repo or the package.

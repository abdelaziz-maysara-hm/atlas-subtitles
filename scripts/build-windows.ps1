# Builds dist/Atlas_Subtitles_Win.zip (PyInstaller one-folder app + ffmpeg.exe/ffprobe.exe + fonts).
# Run from the repo root after: pip install -r requirements-dev.txt, and ffmpeg.exe / ffprobe.exe in the repo root.
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path dist | Out-Null
$name = "Atlas_Subtitles"
$args = @(
  "--noconfirm", "--clean", "--onedir", "--windowed",
  "--name", $name,
  "--distpath", "build_out",
  "--collect-all", "customtkinter",
  "--collect-all", "tkinterdnd2",
  "--collect-all", "faster_whisper",
  "--collect-all", "ctranslate2",
  "--collect-data", "onnxruntime",
  "--collect-binaries", "onnxruntime",
  "--copy-metadata", "tqdm",
  "--copy-metadata", "huggingface-hub",
  "--add-data", "assets/fonts;assets/fonts",
  "run_gui.py"
)
python -m PyInstaller @args
$out = "build_out/$name"
if (-not (Test-Path "$out/$name.exe")) { throw "missing $out/$name.exe" }
foreach ($exe in @("ffmpeg.exe", "ffprobe.exe")) {
  if (-not (Test-Path $exe)) { throw "$exe not found in repo root" }
  Copy-Item $exe -Destination $out
}
Copy-Item README.md, MANUAL.md, NOTICE.md -Destination $out
# smoke test of the frozen core: probe a generated clip with the bundled ffmpeg (no model download)
& "$out/ffmpeg.exe" -v error -y -f lavfi -i "sine=frequency=440:duration=2" "$env:TEMP/atlas_t.wav"
if ($LASTEXITCODE -ne 0) { throw "bundled ffmpeg failed" }
Compress-Archive -Path $out -DestinationPath "dist/${name}_Win.zip" -Force
Get-ChildItem dist

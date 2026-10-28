"""Atlas Subtitles - offline automatic subtitles (Arabic-first)."""
__version__ = "0.1.0"
APP_NAME = "Atlas Subtitles"

import os as _os

# Intel MKL's AMX int8 kernels (Xeon Sapphire Rapids and newer) gave corrupted / truncated Whisper output
# in our tests; capping MKL at AVX-512 fixes it and changes nothing on normal laptop CPUs (AVX2 / AVX-512).
# Must be set before ctranslate2 (MKL) is loaded. See tests/RESULTS.md.
_os.environ.setdefault("MKL_ENABLE_INSTRUCTIONS", "AVX512")

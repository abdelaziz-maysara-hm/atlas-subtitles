# Bundled fonts (SIL Open Font License 1.1)

- `Amiri-Regular.ttf`, `Amiri-Bold.ttf` — Amiri, unmodified ([aliftype/amiri](https://github.com/aliftype/amiri)). Licence: `OFL-Amiri.txt`.
- `AtlasNotoSansArabic-Bold.ttf` — a **modified** version of Noto Sans Arabic ([notofonts/arabic](https://github.com/notofonts/arabic)):
  the variable font was frozen to a static Bold instance (wght=700, wdth=100) with fontTools `varLib.instancer` and the family
  renamed to "Atlas Noto Sans Arabic" so it never clashes with an installed copy. Licence: `OFL-NotoSansArabic.txt`.

Cairo was tried first and dropped: libass (the FFmpeg subtitle renderer) drew isolated letters such as ر و د ا as empty boxes.

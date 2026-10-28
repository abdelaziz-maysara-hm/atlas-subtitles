# دليل الاستخدام · User manual

## بالعربي

### 1) أول تشغيل
- شغّل `Atlas_Subtitles.exe` من المجلد بعد فك الضغط (لا تنقل الـ exe وحده — يحتاج الملفات التي بجانبه و`ffmpeg.exe`).
- تحذير «Windows protected your PC»: اضغط **More info** ثم **Run anyway** (البرنامج غير موقّع رقميًا).
- أول مرة تستخدم فيها نموذجًا يتم تنزيله من الإنترنت (مرة واحدة فقط). بعد ذلك يعمل البرنامج بدون إنترنت تمامًا.
  مكان النماذج: `%LOCALAPPDATA%\AtlasSubtitles\models`.

### 2) إنشاء الترجمة
1. اسحب ملف فيديو/صوت إلى المربع، أو «اختر ملفًا…». (mp4, mkv, mov, avi, webm, mp3, wav, m4a …)
2. **النموذج**: `small` هو الموصى به. `tiny/base` أسرع لكن أخطاؤها أكثر في العربي. `medium` الأدق لكنه أبطأ بحوالي 3 مرات ويحتاج ذاكرة أكبر.
3. **لغة الكلام**: العربية، أو «اكتشاف تلقائي»، أو لغة أخرى.
4. **نوع العربية**: «فصحى» أو «لهجة مصرية» (يعطي النموذج تلميحًا بأسلوب الكلام المصري؛ التحسن بسيط).
5. اضغط **إنشاء الترجمة**. ستظهر الأسطر في المحرر أثناء العمل. زر **إلغاء** يوقف العملية فورًا.
6. عند الانتهاء تُحفظ ملفات الترجمة تلقائيًا بجانب الفيديو (أو في المجلد الذي تختاره من «تغيير»).

### 3) المحرر
- اضغط على سطر لتعديله: غيّر البداية/النهاية (مثل `00:00:05,200` أو `5.2`) والنص، ثم **تطبيق**.
- **تقسيم**: يقسم السطر المحدد إلى اثنين. **دمج مع التالي**: يدمج السطر المحدد مع الذي بعده.
- **إضافة سطر** / **حذف** / **تراجع** (أو Ctrl+Z).
- **إزاحة التوقيت بالثواني**: اكتب رقمًا (مثل `0.5` أو `-1.2`) ثم «المحدد» أو «الكل» — مفيد إذا كانت الترجمة متقدمة أو متأخرة عن الصوت.
- **فتح ملف SRT…** لفتح ترجمة موجودة وتعديلها أو دمجها في فيديو.

### 4) التصدير والدمج
- اختر الصيغ (SRT / VTT / TXT) ثم **تصدير**. ملف SRT هو المناسب لـ YouTube و CapCut و Premiere و VLC.
- **دمج الترجمة في الفيديو**: يُنشئ `اسم_الفيديو_subtitled.mp4` والترجمة مطبوعة داخل الصورة (مناسب لـ TikTok / Reels / واتساب).
  اختر الخط (Noto Sans أو Amiri) والحجم (نسبة من ارتفاع الفيديو) و«خلفية داكنة» لو الفيديو فاتح.

### 5) مشاكل شائعة
| المشكلة | الحل |
|---|---|
| «تعذّر تنزيل النموذج» | اتصل بالإنترنت أول مرة فقط. أو انسخ مجلد نموذج (مثل `faster-whisper-small` من Hugging Face: Systran) إلى `%LOCALAPPDATA%\AtlasSubtitles\models\small`. |
| «ملفات النموذج تالفة» | احذف مجلد النموذج من المسار السابق وأعد المحاولة. |
| «الفيديو بدون صوت» / «لم يتم العثور على كلام» | الملف ليس به مسار صوت أو صامت. |
| البرنامج بطيء | استخدم `base` أو `small`، وأغلق البرامج الثقيلة. ملف ساعة مع `small` يأخذ تقريبًا 5–25 دقيقة حسب الجهاز (4 دقائق على معالج 8 أنوية في الاختبار). |
| الذاكرة غير كافية | لا تفعّل «وضع التوافق»؛ و`medium` يحتاج حوالي 2.5 جيجابايت ذاكرة متاحة (المقاس: 2.2)، و`small` حوالي 1 جيجابايت. |
| الترجمة متأخرة/متقدمة | «إزاحة التوقيت» على الكل. |

---

## English

1. **First run**: unzip, run `Atlas_Subtitles.exe` (keep it inside its folder, next to `ffmpeg.exe`). SmartScreen warning → *More info → Run anyway* (unsigned app).
   Each model downloads once (internet needed only then) into `%LOCALAPPDATA%\AtlasSubtitles\models`; afterwards everything is offline.
2. **Transcribe**: drop a video/audio file (or *Choose file…*), pick a model (`small` recommended; `tiny/base` faster but rougher for Arabic; `medium` most accurate, ~3x slower),
   the spoken language (or auto-detect) and *Standard (Fusha)* / *Egyptian dialect*, then **Generate subtitles**. Lines appear live; **Cancel** stops immediately.
   Results are auto-saved next to the video (or the folder chosen with *Change*).
3. **Editor**: click a line, edit start/end (`00:00:05,200` or `5.2`) and text, **Apply**. **Split**, **Merge with next**, **Add line**, **Delete**, **Undo** (Ctrl+Z).
   *Shift timing by seconds* (e.g. `0.5`, `-1.2`) for *Selected* or *All*. *Open SRT…* loads an existing subtitle file.
4. **Export / burn**: choose SRT/VTT/TXT and **Export**; **Burn subtitles into video** writes `NAME_subtitled.mp4` with the chosen font, size and optional dark box.
5. **Troubleshooting**: see the table above (download failure → connect once or copy a model folder; damaged model → delete its folder;
   *Compatibility mode* uses float32 and ~2.5x more RAM — only use it if results look broken).

Resources (measured, 8-vCPU Xeon, int8): peak RAM tiny 0.3 GB, base 0.4 GB, small 0.8 GB, medium 2.2 GB. A 1-hour file with `small` took ~4 min here; expect 5–25 min on a typical laptop. See `tests/RESULTS.md`.

Command line: `python run_cli.py VIDEO --model small --lang ar --dialect egyptian --formats srt,vtt --burn --font Amiri`

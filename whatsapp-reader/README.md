# خدمة واتساب المسابقة (whatsapp-reader)

نسخةٌ من خدمة واتساب **النظام اللوجستي** (`souq-saas/whatsapp-reader`، الإصدار 42) — `package.json`
و`package-lock.json` كما هما، و`server.js` كما هو **وعليه إضافتان** (أدناه). تُثبَّت في صورة الأداة (`Dockerfile`)
ويشغّلها الخادم (`xm_lines.py`، `start_embedded_reader`) داخل الحاوية على `127.0.0.1:3301` (`CONTEST_READER_PORT`):

- السرّ `WHATSAPP_READER_SECRET` يولّده الخادم ويحفظه مشفَّرًا في إعداد المسابقة — لا إعداد يدويّ.
- الجلسات في `data/wa-reader/sessions` على المجلد الدائم، وسجلّها في `data/wa-reader/reader.log`.
- تُعاد إن توقّفت، ولا تعمل إن ضُبطت خدمةٌ خارجية بـ `WHATSAPP_READER_URL`.

الربط من صفحة مدير المسابقة كالنظام اللوجستي: الرقم ← «ربط» ← رمز QR ← «مربوط». ولتحديثها: انسخ الملفات
الثلاثة من souq-saas، ثم أعِد الإضافتين إلى `server.js`.

## الإضافة: فيديو MP4 مقطعًا (تهنئة الفائزين في القناة)
في `POST /sessions/:tenant/send`: مرفقٌ `media_mime` فيه `video/mp4` يُرسل **مقطع فيديو** (`{video, caption}`) لا ملفًّا —
فيُشغَّل فيديو الفرز في منشور القناة. والصور كما هي، وما عداهما (‏WebM مثلًا) ملفٌّ كما كان.

## الإضافة: قنوات واتساب (منشور «أضيف مؤخرًا»)
`GET /sessions/:tenant/newsletter?invite=<الرمز>` (أو `?jid=<…@newsletter>`) ← `{ok, id, name, subscribers, role, invite}`
من `sock.newsletterMetadata` في Baileys: رابط القناة `whatsapp.com/channel/<الرمز>` لا يحمل معرّفها، والنشر فيها
يحتاجه — ثم يُنشر بـ `POST /sessions/:tenant/send {to: "<المعرّف>@newsletter", body}` كما هو (المعرّف يُستعمل كما هو).
و`role` دور الرقم المربوط في القناة (`OWNER` · `ADMIN` · `SUBSCRIBER` · `GUEST`)، والنشر للمالك والمشرفين وحدهم.
الأخطاء: `404 no_session` · `409 not_connected` · `422 invalid` · `404 channel_not_found` · `502 lookup_failed`.
وبلا الإضافة (خدمةٌ خارجية أقدم) تقبل صفحة المحتوى معرّف القناة ملصوقًا بدل رابطها.

تشغيلها محليًّا للتجربة: `cd whatsapp-reader && npm ci --omit=dev`، ثم `python3 xm_lines.py web`.

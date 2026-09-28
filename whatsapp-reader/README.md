# خدمة واتساب المسابقة (whatsapp-reader)

نسخةٌ من خدمة واتساب **النظام اللوجستي** (`souq-saas/whatsapp-reader`، الإصدار 42) — `server.js` و`package.json`
و`package-lock.json` كما هي بلا تعديل. تُثبَّت في صورة الأداة (`Dockerfile`) ويشغّلها الخادم (`xm_lines.py`،
`start_embedded_reader`) داخل الحاوية على `127.0.0.1:3301` (`CONTEST_READER_PORT`):

- السرّ `WHATSAPP_READER_SECRET` يولّده الخادم ويحفظه مشفَّرًا في إعداد المسابقة — لا إعداد يدويّ.
- الجلسات في `data/wa-reader/sessions` على المجلد الدائم، وسجلّها في `data/wa-reader/reader.log`.
- تُعاد إن توقّفت، ولا تعمل إن ضُبطت خدمةٌ خارجية بـ `WHATSAPP_READER_URL`.

الربط من صفحة مدير المسابقة كالنظام اللوجستي: الرقم ← «ربط» ← رمز QR ← «مربوط». ولتحديثها: انسخ الملفات
الثلاثة من souq-saas كما هي.

تشغيلها محليًّا للتجربة: `cd whatsapp-reader && npm ci --omit=dev`، ثم `python3 xm_lines.py web`.

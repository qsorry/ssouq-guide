# guide.ssouq.com

صفحة إنشاء يوزرات M3U Lines (Xtream-Masters) لمتجر ssouq.com. تعمل عبر Coolify من الـ Dockerfile.

- `xm_lines.py` سيرفر Python بدون مكتبات خارجية يقدّم الصفحة ويتواصل مع API الريسيلر.
- `xm_lines.html` واجهة الصفحة.
- متغيرات البيئة:
  - `XM_PASSWORD` كلمة مرور الصفحة (إجباري عند النشر، السيرفر لا يعمل بدونها)
  - `XM_USER` اسم الدخول (الافتراضي `admin`)
  - `XM_API_KEY` مفتاح API الريسيلر
  - `XM_BIND`، `XM_PORT`

محلياً: `python xm_lines.py web` ثم افتح http://127.0.0.1:8080

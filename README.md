# guide.ssouq.com

صفحة إنشاء يوزرات M3U Lines (Xtream-Masters) لمتجر ssouq.com. تعمل عبر Coolify من الـ Dockerfile.

- `xm_lines.py` سيرفر Python بدون مكتبات خارجية يقدّم الصفحة ويتواصل مع API الريسيلر.
- `xm_lines.html` واجهة الصفحة.
- الحسابات في قائمة `ACCOUNTS` أعلى `xm_lines.py`: لكل حساب اسم دخول وكلمة مرور و API وهوست مستقل. عدّل القيم `CHANGE_ME` قبل النشر.
- متغيرات البيئة الاختيارية: `XM_BIND`، `XM_PORT`.

محلياً: `python xm_lines.py web` ثم افتح http://127.0.0.1:8080

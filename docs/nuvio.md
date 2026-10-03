# Nuvio — ما تحقّقنا منه قبل أي كود

فحصنا هذا في 2026-10-03 من المستودع الرسمي `NuvioMedia/self-host` (Apache-2.0)، ومن الخادم الرسمي `api.nuvio.tv` نفسه. لا شيء هنا
افتراض. ما لم نتحقق منه موسوم «غير مؤكد».

## 1) الخادم
- خادم Nuvio الرسمي `https://api.nuvio.tv` هو **Supabase**: GoTrue للدخول، وPostgREST وPostgreSQL للبيانات، وEdge Functions، وKong.
- تطبيقات Nuvio (TV · Mobile · Desktop · Web/Tizen/webOS) تستعمل عنوان خادم واحد ومفتاحاً عاماً (publishable/anon key).
- **الاكتشاف**: `GET https://api.nuvio.tv/.well-known/nuvio` يرجع `backend_url` و`publishable_key` (عام، يحمله كل تطبيق) و`capabilities`:
  `{"email_password_auth": true, "tv_login": true}`.
- **إعدادات الدخول الحالية** (`GET /auth/v1/settings` مع `apikey`):
  - `disable_signup: false`: التسجيل مفتوح.
  - `mailer_autoconfirm: true`: **لا تأكيد بالبريد**.
  - مزوّدا الدخول: `email` و`anonymous_users`.
- الصحة: `GET /functions/v1/health-check` يرجع `{"status": "healthy", "database": "connected"}`.

## 2) الحساب
- إنشاء حساب: `POST /auth/v1/signup` بـ `{email, password}` والترويسة `apikey: <publishable_key>`، فترجع الجلسة: `access_token` و`refresh_token` و`user.id` (uuid).
- الدخول: `POST /auth/v1/token?grant_type=password`.
- تجديد الجلسة: `POST /auth/v1/token?grant_type=refresh_token`.
- عند إنشاء أي حساب، الـtrigger `handle_new_user_default_addons` يضيف تلقائياً Cinemeta وOpenSubtitles v3 للملف 1.
- الملفات الشخصية (profiles) من 1 إلى 6 لكل حساب.

## 3) الإضافات (المزامنة)
- الجدول `public.addons` بالأعمدة `(user_id, profile_id, url, name, enabled, sort_order)`. **الإضافة رابط manifest فقط**: Nuvio يقرأ
  إضافات Stremio بالرابط نفسه، ولا يخزّن الـmanifest.
- **القراءة**: `POST /rest/v1/rpc/sync_pull_addons {p_profile_id: 1}`.
- **الكتابة**: `POST /rest/v1/rpc/sync_push_addons {p_addons: [{url, name, enabled, sort_order}], p_profile_id: 1}`.
  - الترويستان: `Authorization: Bearer <access_token>` و`apikey`.
  - **تستبدل قائمة الملف كاملة** (تحذف ما ليس فيها). لذلك: اقرأ أولاً، ثم أضف رابطنا، ثم ادفع القائمة كاملة.
- كل الأجهزة المسجّلة بالحساب ترى التغيير بالمزامنة: الدالة `emit_sync_invalidation` تُخطرها.

## 4) دخول التلفاز بكود (QR)
1. التلفاز ينشئ جلسة: `start_tv_login_session(p_device_nonce, …)`، ويعرض كوداً أو QR.
2. **حسابٌ مسجّل يوافق على الكود**: `POST /rest/v1/rpc/approve_tv_login_session {p_code}` بجلسة ذلك الحساب.
3. التلفاز يستبدل الكود بجلسة: الدالة `tv-logins-exchange`.

**ما يعنيه هذا لنا**: الأداة (وهي مسجّلة بحساب العميل في Nuvio) تستطيع الموافقة على الكود الظاهر في تلفاز العميل.
- العميل يقرأ الكود للموظف، والموظف يكتبه في الأداة، فيدخل التلفاز بحسابه وإضافته جاهزة.
- العميل لا يكتب إيميلاً ولا كلمة مرور على التلفاز.

## 5) خادم خاص بنا (بديل)
- `NuvioMedia/self-host` (Docker Compose) يشغّل الخادم نفسه على خادمنا، والتطبيقات الرسمية تقبل «Backend URL» مخصّصاً عبر `/.well-known/nuvio`.
- **المزايا**: تحكّم كامل، وحسابات تُنشأ بمفتاح الخدمة، ولا اعتماد على خادمهم.
- **العيوب**:
  - خادم إضافي نديره.
  - **العميل يغيّر Backend URL في التطبيق مرة**.
  - الملف يصفه بأنه «للاستعمال الشخصي».

## 6) غير مؤكد (يجب التحقق قبل الإنتاج)
- **شروط استعمال `api.nuvio.tv`** لإنشاء حسابات لعملائنا آلياً، وحدود معدّل الطلبات. هذا مثل ما نفعله مع `api.strem.io`، لكن Nuvio مشروع صغير
  وقد يمنع ذلك.
- هل كل نسخ التطبيقات (خاصة Tizen وwebOS) تعرض «Backend URL» للمستخدم، أم يُضبط عند البناء فقط؟ الوثائق تذكر الاثنين.
- سلوك Nuvio مع خصائص manifest الخاصة بنا: الأنواع الخاصة («الحسابات» و«التصنيفات»)، و`androidTvUrl`، و`externalUrl`، و`stremio:///discover`.
  الروابط من نوع `stremio:///` غالباً لا تعمل في Nuvio.

## 7) ما بنيناه عليه (المرحلة 2)
مسار تسجيل **مستقل** عن Stremio: الموظف يختار المنصّة في صفحة الحسابات (Stremio | Nuvio). لا شيء من مسار Stremio تغيّر.

**الحساب** (`nuvio_accounts.py` و`nuvio_account` في `xm_lines.py`):
1. الموظف يبحث عن اليوزر في البوابة، ثم «إنشاء حساب Nuvio».
2. نتحقق أن اليوزر يعمل على سيرفره. يوزر لا يعمل ← لا حساب.
3. إيميل محايد `ssq<بصمة>@tv.ssouq.com` (لا يوزر Xtream فيه)، وكلمة مرور عشوائية 12 حرفاً، ثم `POST /auth/v1/signup`.
   - مسجَّل من قبل بكلمة مرورنا ← `POST /auth/v1/token?grant_type=password`.
4. رابط manifest برمز مختوم بقفلٍ خاص بهذا الحساب، ثم `sync_pull_addons` ثم `sync_push_addons` (إضافتنا أولاً، والباقي كما هو).
5. يُحفظ في `data/nuvio_accounts.json`، وكلمة المرور مشفّرة.

**ما يصل العميل**: الإيميل المحايد وكلمة المرور العشوائية فقط. رابط الإضافة رمز مختوم، والـmanifest والكتالوجات والمصادر بلا يوزر
ولا باسورد ولا رابط M3U، والتشغيل عبر `/play/…` على خادمنا ثم تحويل إلى اللوحة (اختيارك: «تحويل عبر سيرفرنا»).

**الأزرار**:
- «ربط تلفاز»: `approve_tv_login_session {p_code}` بجلسة حسابه. كود خاطئ أو منتهٍ ← رسالة واضحة.
- «تحديث الإضافة»: رابطنا نفسه يعود أول القائمة.
- «إعادة الربط»: قفل ورمز جديدان. الرابط القديم يتوقف فوراً (إن نُسخ لحساب آخر)، والجديد يُثبَّت مكانه.
- «إلغاء التفعيل»: تُزال إضافتنا من حسابه في Nuvio، ويتغيّر القفل فيتوقف رابطها. الحساب نفسه يبقى، و«إعادة الربط» أو «إنشاء» تعيده
  بالإيميل وكلمة المرور نفسيهما.

**المعرّفات لا تتغيّر**: معرّف الإضافة ومعرّفات الأعمال من الهوست واليوزر، لا من الرمز. فهي نفسها في Nuvio وفي Stremio، وبعد إعادة الربط.

**الاختبار**: `tests/mock_nuvio.py` خادم وهمي بالواجهة نفسها (المفتاح العام، الجلسة، استبدال القائمة، أكواد التلفاز)،
و`tests/test_nuvio.py` (67 فحصاً) و`tests/ui_nuvio_page.js` (22). **لم يُجرَّب على `api.nuvio.tv` الحقيقي** بحساب حقيقي، تجنّباً لإنشاء
حسابات على خادمهم قبل موافقتك على الشروط (القسم 6). أول تجربة حقيقية: حساب واحد من الأداة، ثم الدخول به في تطبيق Nuvio.

# التحقق من تنصيب اللوحة وتفعيل Reseller API — Xtream-Masters (Mr7tv)

دليل موجّه لصاحب السرفر. يغطّي أمرين مرتبطين:
1. **نطاق تنصيب اللوحة** بعد تغيير الدومين (سبب المشكلة الجذري).
2. **تفعيل Reseller API** والتحقق منه من اللوحة ومن السيرفر.

الأوامر جاهزة للنسخ واللصق، وعنوان خادمنا المصرّح له ثابت داخلها.

## القيم الأساسية

| العنصر | القيمة |
|---|---|
| عنوان خادمنا (يُصرَّح له في اللوحة) | `158.220.81.202` |
| رموز الوصول الحالية (Reseller API) | `msAPIufgk` و `resellerapi` |
| صيغة الرابط حسب الوثائق | `http://{server-dns}:{stream-port}/{code}/reseller/index.php` |
| النطاق القديم العالق في الـ API | `mr7-4k.live` (⚠️ لا يُترجَم — دومين تنصيب قديم) |
| نطاق اللوحة الحالي (الأدمن) | `mr7-4k.sbs:2052` (خلف Cloudflare) |
| عنوان الأصل (IP) | `205.237.107.54` |
| وثائق الـ API | https://ottpanel.tv/xm_reseller_api_doc.html |

**المطلوب تعبئته:** `{KEY}` = api_key من API Settings، `{PORT}` = منفذ البث،
`{PKG}` = رقم باقة للاختبار، `{NEW}` = الدومين النهائي المعتمد.

---

## القسم أ — نطاق تنصيب اللوحة (المشكلة الجذرية)

اللوحة نُصّبت على دومين ثم غُيّر، فبقيت مراجع الدومين القديم (`mr7-4k.live`) في
إعدادات البث/الـ API، ولذلك تُبنى روابط رموز الوصول على نطاق لا يُترجَم. يجب توحيد
كل المراجع على الدومين النهائي `{NEW}` (الأرجح `mr7-4k.sbs`):

1. **DNS:** سجل **A** لكل اسم مستخدم (الأدمن + البث + الـ API) في منطقة `{NEW}` →
   `205.237.107.54`. وإن كان على Cloudflare اجعل سجلات **منافذ البث DNS only (رمادي)**
   لأن Cloudflare يمرّر منافذ HTTP محددة فقط (80, 8080, 2052, 2082, 2086, 2095…).
2. **General Settings في اللوحة:** حدّث حقل **Panel URL / Access URL / Stream DNS**
   (النطاق الذي تُبنى منه روابط رموز الوصول والبث) من `mr7-4k.live` إلى `{NEW}`.
3. **Servers / Load Balancers:** لكل خادم حدّث حقل **Server Domain / DNS** إلى `{NEW}`
   (يُستخدم في روابط البث وقاعدة الـ Reseller API).
4. **nginx:** أضف `{NEW}` في `server_name` على منافذ الأدمن والبث، مع شهادة SSL صالحة له.
5. **رموز الوصول:** بعد التحديث افتح Access Codes وتأكد أن الرابط صار يستخدم `{NEW}`
   لا `mr7-4k.live` (أعد توليد/نسخ الرابط إن لزم).
6. **الدومين القديم:** أبقِ توجيهه مؤقتًا أثناء الانتقال أو أزل كل مراجعه نهائيًا.

**تحقق سريع:** رابط أي رمز في صفحة Access Codes يجب أن يظهر بنطاق `{NEW}` يُترجَم فعلًا.

---

## القسم ب — التحقق من إعداد الـ API داخل اللوحة

1. **رمز الوصول:** Access Codes ← رمز نوعه **Reseller API** حالته **Active**.
2. **قائمة الـ IP:** الرمز ← تبويب **Restrictions** ← **Allowed IP Addresses** يحتوي
   `158.220.81.202` (ظاهر داخل المربع ومحفوظ بـ Add).
3. **مجموعات الباقات:** تبويب **Groups** للرمز فيه مجموعات الباقات المُباعة، ولكل باقة
   **Bouquets** مُسندة.
4. **صلاحيات المجموعة** (Edit Group ← Permissions): Can Use Reseller API ✓،
   Can Generate Mass Paid ✓، Can Delete Users ✓، User Delete Refund ✓.
5. **api_key:** من **Manage end-points / API Settings** — انسخ المفتاح المرتبط بالرمز.
   (مفتاح صفحة *Admin API Management* مختلف ولا يصلح.)

---

## القسم ج — التحقق من السيرفر (اختبار فعلي)

تُنفَّذ من خادمنا `158.220.81.202`. لكل اختبار نسخة `curl` ونسخة `python3`.
استبدل `{NEW}` و`{PORT}` و`{KEY}` بقيمها ثم انسخ والصق.

### 1) هل الدومين يُترجَم؟
```
getent hosts {NEW} || nslookup {NEW}
```

### 2) هل النقطة ترد؟ (آمن، لا يُنشئ شيئًا) — action=user_info
curl:
```
curl -sS "http://{NEW}:{PORT}/msAPIufgk/reseller/index.php?api_key={KEY}&action=user_info"
```
python3:
```
python3 -c "import urllib.request as u;print(u.urlopen('http://{NEW}:{PORT}/msAPIufgk/reseller/index.php?api_key={KEY}&action=user_info',timeout=25).read().decode())"
```

### 3) قراءة الباقات — action=packages
curl:
```
curl -sS "http://{NEW}:{PORT}/msAPIufgk/reseller/index.php?api_key={KEY}&action=packages"
```
python3:
```
python3 -c "import urllib.request as u;print(u.urlopen('http://{NEW}:{PORT}/msAPIufgk/reseller/index.php?api_key={KEY}&action=packages',timeout=25).read().decode())"
```

### 4) اختبار إنشاء وهمي (dry_run=1، لا تنفيذ فعلي)
curl:
```
curl -sS -X POST "http://{NEW}:{PORT}/msAPIufgk/reseller/index.php" -d "api_key={KEY}&action=create_line&package_id={PKG}&dry_run=1"
```
python3:
```
python3 -c "import urllib.request as u,urllib.parse as p;d=p.urlencode({'api_key':'{KEY}','action':'create_line','package_id':'{PKG}','dry_run':'1'}).encode();print(u.urlopen(u.Request('http://{NEW}:{PORT}/msAPIufgk/reseller/index.php',data=d),timeout=25).read().decode())"
```

### 5) اختبار محلي على خادم اللوحة نفسه (يتجاوز DNS وقيد الـ IP)
يُنفَّذ على **خادم اللوحة** مباشرة لعزل المشكلة عن DNS/الشبكة:
```
curl -sS -H "Host: {NEW}" "http://127.0.0.1:{PORT}/msAPIufgk/reseller/index.php?api_key={KEY}&action=user_info"
```

> جرّب الرمز الآخر `resellerapi` بنفس الأوامر إن لزم (استبدل `msAPIufgk`).

---

## القسم د — تفسير النتائج

| الرد | المعنى | الإجراء |
|---|---|---|
| `{"status":"STATUS_SUCCESS",...}` | سليم | جاهز للربط |
| `IP FORBIDDEN` | العنوان غير مصرّح | أضف `158.220.81.202` في Restrictions |
| رسالة عن api_key / authentication | المفتاح خاطئ | خذ api_key من API Settings |
| `404 Not Found` (nginx) | نطاق/منفذ خاطئ أو server_name ناقص | نفّذ القسم أ (توحيد الدومين + nginx) |
| `could not resolve` / `Errno -3` | الدومين لا يُترجَم | نفّذ القسم أ (سجل A) |
| خطأ صلاحية عند create_line | صلاحية ناقصة | فعّل Generate Mass Paid للمجموعة |

---

## القسم هـ — ما نحتاج إرساله بعد نجاح الاختبار

عند وصول رد `STATUS_SUCCESS`:
1. **الرابط الكامل الناجح** (بالدومين النهائي والمنفذ والرمز).
2. **api_key** المرتبط بالرمز.
3. **الدومين والمنفذ** النهائيان المعتمدان.

ثم نربط البوابة في الأداة بوضع Reseller API مباشرة.

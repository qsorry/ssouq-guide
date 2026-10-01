# نظام Content SEO لـ guide.ssouq.com/content — تقرير التحليل وخطة التنفيذ

> مرحلة التحليل فقط. لم يُعدَّل أي كود. التنفيذ يبدأ بعد الموافقة على هذه الخطة.

---

## 1. Architecture الحالية (Audit)

| البند | الواقع |
|---|---|
| **Framework** | لا يوجد. Python 3.12 بالمكتبة القياسية فقط (`ThreadingHTTPServer` + راوتر يدوي في `xm_lines.py` ≈ 4,900 سطر). لا Flask/Django، لا Jinja، لا ORM. |
| **قاعدة البيانات** | لا يوجد SQL. كل شيء ملفات JSON تحت `data/content/` (Docker volume `/app/data`): `<server>.json` (الفهرس الكامل) · `.sum.json` (ملخص) · `.seen.json` · `.news.json` · `.adult.json` · `settings.json` · `img/` (كاش صور). |
| **وحدة الاشتراك** | **السيرفر هو الوحدة الأساسية**: لكل سيرفر (casper · smart · falcon · kon) فهرس مستقل. لا يوجد كيان "فيلم" مشترك بين السيرفرات. |
| **مصدر البيانات** | ملف M3U لكل سيرفر (يُسحب كل 24 ساعة من `get.php`) + إثراء من Xtream `player_api.php` (`get_vod_streams` · `get_series` · `get_live_streams` · الأقسام). **لا يُستدعى** `get_vod_info` ولا `get_series_info`. |
| **ما يُخزَّن للفيلم** | `n` الاسم · `y` السنة · `p` الملصق · `i` stream id · `r` التقييم · `a` تاريخ الإضافة · `g` ≤3 تصنيفات · `d` القصة ≤280 حرفًا. |
| **ما يُخزَّن للمسلسل** | نفسها + `b` خلفية + `s` = `[[رقم الموسم, عدد الحلقات]]`. **لا عناوين حلقات، لا ملخصات حلقات، لا تواريخ عرض.** |
| **ما لا يوجد إطلاقًا** | `tmdb_id` · الممثلون · المخرج · الكاتب · الدولة · اللغة · المدة · الاسم الأصلي · عنوان عربي/إنجليزي منفصل · aliases. (TMDB يُستعمل **فقط** كـ CDN للصور: `image.tmdb.org`.) |
| **الهوية (Identity)** | الفيلم: `norm(name)\|year` داخل السيرفر الواحد. المسلسل: `norm(name)` بلا سنة. التطبيع `_norm` جيد (NFKC، أرقام هندية، توحيد أ/إ/آ، ة/ه، ى/ي). **لا هوية عبر السيرفرات**. |
| **Routing الحالي للمحتوى** | `/content` → 302 لأول سيرفر · `/content/<server>` (+ `/en/content/<server>`) · `/content/<server>/img/<hash>` · `/api/content` · `/api/content/search`. أي مسار أعمق = 404. |
| **الصفحات الحالية** | صفحة واحدة لكل سيرفر بمتغيّرات `?t= ?g= ?p= ?q= ?view= ?y= ?genre= ?r= ?sort= ?all=`. تفاصيل الفيلم/المسلسل في **نافذة منبثقة JS** من `data-d` (لا URL). |
| **اللغتان** | `/content/...` عربي (x-default) و`/en/content/...` إنجليزي عبر `content_page.Lang.tr()`. hreflang موجود لصفحات السيرفرات فقط. |
| **Auth** | صفحات المحتوى عامة. الإدارة على `admin.ssouq.com` (host منفصل، جلسة + `XM_ADMIN_PASSWORD`)، ومسارات الإدارة `/api/content/admin/*`. |
| **Sitemap / Robots** | `/sitemap.xml` ملف urlset واحد (صفحات الدليل + الدوريات + 6 روابط محتوى: 3 سيرفرات × لغتين). `robots.txt`: `Allow: /` + Disallow للإدارة فقط. IndexNow موجود (`analytics.submit`). |
| **الحجم الحي (1 أكتوبر 2026)** | كاسبر 6,396 فيلم / 1,880 مسلسل / 45k حلقة · سمارت 20,456 / 9,886 / 318k · فالكون 17,571 / 14,302 / 238k. **التقدير بعد التوحيد: ~30k فيلم، ~20k مسلسل، ~500k حلقة.** |
| **الاختبارات** | `python tests/test_content.py` (بلا إنترنت، لوحة Xtream وهمية `tests/mock_xtream.py`) + `node tests/ui_content.js` (Playwright). |
| **النشر** | Docker (alpine) ينسخ الملفات **بالاسم** في `Dockerfile` — أي ملف جديد يجب إضافته هناك. |

### ما يمكن إعادة استخدامه (لا إعادة بناء)
- `content.py`: القراءة والإثراء والسحب اليومي والصور (`img_src`, `image`) و`_norm` و`servers()`.
- `content_page.py`: `Lang`/`tr()`، `card`, `_pos`, `_row`, `_pager`, `_utm`, `_ad`, `_cta`, `_catalog`، الـ CSS/JS، `_doc` (رأس HTML).
- `guide_pages.py`: `sitemap()`، أنماط hreflang/JSON-LD، FAQ schema (موجود بالفعل في صفحات الدليل).
- `analytics.py`: IndexNow.
- `crypto_store.py`: لتخزين مفتاح TMDB مشفَّرًا.
- `xm_lines.py`: `_redirect(to, 301)`، `_send`، دورة المحتوى `_content_loop`.

---

## 2. المشاكل الحالية (SEO Problems)

1. **لا صفحات كيانات**: 50k+ فيلم ومسلسل غير مرئية لمحركات البحث إلا كأسماء في بطاقات `<h3>` داخل 6 صفحات فقط. القصة والتقييم في `data-d` (JSON داخل attribute) لا يراها Google كمحتوى.
2. **التكرار معماري**: نفس الفيلم موجود 3 مرات (ملف لكل سيرفر) بلا معرّف مشترك. «ويوجد أيضًا في» بحث نصي، لا علاقة.
3. **نقص البيانات الوصفية**: لا ممثلين/مخرج/دولة/لغة/مدة/عناوين حلقات → القوالب المطلوبة (صفحة الممثل، المخرج، الدولة، اللغة، الحلقة) **مستحيلة من البيانات الحالية**. يلزم مصدر بيانات.
4. **Title/Description موحّد**: كل متغيّرات صفحة السيرفر لها نفس `<title>` ونفس الوصف.
5. **Structured Data شكلية**: BreadcrumbList من عنصرين فقط. لا Movie/TVSeries/Person.
6. **الصور**: كل `<img>` بـ `alt=""`. لا `width/height`. `og:image` صورة عامة واحدة. لا Twitter cards.
7. **صفحة النوع** (`?t=movie`) بلا H1.
8. **البحث**: بالاسم والسنة فقط، لا aliases، مسح خطي O(n) لكل سيرفر، و«ويوجد أيضًا في» يكرره × عدد السيرفرات + `suggest` (حتى 24 مسحًا إضافيًا).
9. **الأداء**: لا كاش للصفحة المرسومة (تُبنى في كل طلب)، و`CATALOG` يُقرأ ويُحلَّل من `index.html` مرتين في كل طلب.
10. **Sitemap**: 6 روابط للمحتوى، بلا sitemap index، و`lastmod` لكل الروابط = تاريخ اليوم (ليس حقيقيًا).
11. **الخادم**: لا gzip، لا ETag/Last-Modified/304 لأي استجابة؛ ورأس SEO (`<head>`) منسوخ يدويًا في 6 وحدات بلا helper مشترك.
12. **الجيد الذي يجب الحفاظ عليه**: الفلاتر والبحث `noindex` (لا faceted explosion اليوم)، hreflang صحيح، صفحات السيرفر مفهرسة وتعمل بلا JS.

---

## 3. ما الذي يجب تغييره (القرار المعماري)

**لا نستبدل النظام الحالي؛ نبني طبقة كيانات فوقه.**

```
M3U + Xtream (لكل سيرفر)  ──►  data/content/<server>.json   (كما هو، لا يُمسّ)
                                        │
                                        ▼  seo_build (بعد كل سحب، تزايدي)
                           data/content/seo.sqlite  ◄── TMDB API + Xtream info
                                        │
                     ┌──────────────────┼───────────────────┐
                     ▼                  ▼                   ▼
             صفحات الكيانات       Sitemap index         البحث الموحّد
        /content/movies/<slug>/   sitemap-movies-N    FTS + aliases
```

- **SQLite** (stdlib، لا اعتماديات جديدة، ملف واحد على الـ volume، WAL mode). يكفي لعشرات الآلاف من الكيانات ومئات الآلاف من الحلقات مع الفهارس الصحيحة.
- **مصدر البيانات الوصفية** (مطلوب لتنفيذ القوالب):
  - **Xtream** (مجاني، متاح الآن): `get_vod_streams` يعطي غالبًا `tmdb_id`، و`get_series` يعطي `tmdb`. و`get_vod_info` / `get_series_info` يعطيان cast · director · country · releasedate · duration · **والحلقات بعناوينها وملخصاتها وتواريخها**. نستدعيهما **تزايديًا** (الجديد والمتغيّر فقط) لا لكل العناصر كل يوم.
  - **TMDB API** (مفتاح مجاني، مطلوب من المدير): العنوان العربي + الإنجليزي + الأصلي، القصة باللغتين (`language=ar-SA` و`en-US`)، الممثلون والمخرج والكاتب بصورهم، الدولة، اللغة، المدة، الحالة، alternative titles، المواسم والحلقات. هو **مصدر الهوية الموثوق** (`tmdb_id`).
  - بلا مفتاح TMDB يعمل النظام ببيانات Xtream (لغة واحدة غالبًا) مع مطابقة محلية؛ لكن القوالب ثنائية اللغة وصفحات الأشخاص تحتاج TMDB.

---

## 4. Database (SQLite: `data/content/seo.sqlite`)

```sql
content(id PK, type 'movie'|'series', tmdb_id UNIQUE NULL, imdb_id,
        slug UNIQUE, slug_ar NULL,
        title_ar, title_en, original_title, overview_ar, overview_en,
        release_date, year, rating, votes, runtime, status, poster, backdrop,
        trailer_yt, match 'tmdb'|'xtream'|'local', quality_score,
        index_ar BOOL, index_en BOOL, first_seen, updated_at, content_hash)
content_alias(content_id, alias_norm, source)        -- UNIQUE(alias_norm, type)
content_service(content_id, service_key, stream_ref, added_at, seasons_json, UNIQUE(content_id, service_key))
person(id PK, tmdb_id UNIQUE, slug UNIQUE, name_ar, name_en, original_name, bio_ar, bio_en, photo, birthday, index BOOL)
content_person(content_id, person_id, role 'actor'|'director'|'writer'|'creator', character, ord)
genre(id, slug, name_ar, name_en)            content_genre(content_id, genre_id)
country(iso, slug, name_ar, name_en)         content_country(content_id, iso)
language(iso, slug, name_ar, name_en)        content_language(content_id, iso)
season(id PK, content_id, number, name, overview_ar, overview_en, poster, air_date, episode_count, index BOOL)
episode(id PK, season_id, number, title_ar, title_en, overview_ar, overview_en, air_date, runtime, still, index BOOL)
seo_override(entity 'content'|'person'|'season'|'episode'|'genre'|..., entity_id, lang,
             seo_title, meta_desc, slug, overview, intro, faq_json, index_flag, canonical, updated_at)
redirect(path UNIQUE, to, code 301, created_at)       -- تاريخ الـ slugs + تحويلات يدوية
api_cache(key UNIQUE, body, at)                       -- ردود TMDB/Xtream (إيجابية وسلبية)
fts5: content_fts(title_ar, title_en, original_title, aliases) content=''
```
الفهارس: `content(type, year)`, `content(index_ar, updated_at)`, `content_service(service_key)`, `content_person(person_id)`, `content_genre(genre_id)`, `episode(season_id, number)`, `content_alias(alias_norm)`.

**لا حذف ولا تعديل لملفات JSON الحالية.** قاعدة SEO مشتقة ويمكن إعادة بنائها من الصفر في أي وقت.

### حل التكرار (Duplicate-content)
ترتيب المطابقة عند بناء كل عنصر من كل سيرفر:
1. `tmdb_id` من Xtream (vod: `tmdb_id`، series: `tmdb`) → الكيان.
2. وإلا بحث TMDB: `type + norm(original_title) + year (±1)` → قبول عند تطابق قوي (اسم أو alias + سنة)، وتخزين النتيجة (والسلبية) في `api_cache`.
3. وإلا مفتاح محلي `type|norm(title)|year` → كيان بـ `match='local'` (**noindex افتراضيًا**، يظهر للمدير ليربطه يدويًا أو يبقى داخليًا).
- كل اسم رآه النظام (اسم الملف في كل سيرفر، title_ar/en/original من TMDB، alternative titles) يُسجَّل **alias** → «Breaking Bad» و«بريكنغ باد» و«بريكنج باد» تصل لنفس `content_id`. والمدير يستطيع **دمج** كيانين (يبقى الأول، الثاني يصير alias + redirect).

---

## 5. Routing

| الكيان | عربي (x-default) | إنجليزي |
|---|---|---|
| هب المحتوى | `/content/` | `/en/content/` |
| فيلم | `/content/movies/{slug}/` | `/en/content/movies/{slug}/` |
| مسلسل | `/content/series/{slug}/` | `/en/content/series/{slug}/` |
| موسم | `/content/series/{slug}/season-{n}/` | … |
| حلقة | `/content/series/{slug}/season-{n}/episode-{e}/` (فقط عند توفر محتوى فريد) | … |
| ممثل / مخرج | `/content/people/actors/{slug}/` · `/content/people/directors/{slug}/` | … |
| تصنيف | `/content/genres/{slug}/` + `/page/{n}/` | … |
| دولة / لغة / سنة | `/content/countries/{slug}/` · `/content/languages/{slug}/` · `/content/year/{yyyy}/` | … |
| الأحدث | `/content/latest/` (+ `/movies/` `/series/` `/episodes/`) | … |
| صفحة السيرفر (كما هي) | `/content/casper` … تبقى بلا تغيير ومفهرسة، وتربط للكيانات | … |

قرارات:
- **البادئة العربية**: المقترح إبقاء العربية على `/content/...` بلا `/ar/` (كما هو اليوم ومفهرس)، و`/en/...` للإنجليزية؛ و`/ar/content/...` يُقبل بتحويل 301 إلى `/content/...`. (إن أردت `/ar/` إلزاميًا نحوّل صفحات السيرفرات الست بـ 301، وهو مقبول لكنه خسارة مؤقتة بلا مكسب.)
- **Slug واحد لاتيني مشترك** للغتين، بأولوية: الاسم الإنجليزي ← الاصلي ← نقحرة (`wonder-woman`، وعند التعارض `wonder-woman-2017`)، صغير الحروف بلا رموز، يُولَّد مرة ولا يتغيّر مع تحديث البيانات؛ وأي تغيير slug (يدوي، أو ترقية من نقحرة إلى اسم إنجليزي من TMDB) يبقي المعرّف ويسجّل 301 في جدول `redirect`. الأسماء العربية aliases وبيانات عرض فقط.
- **كلمات محجوزة** في `content.key_ok` (movies, series, people, genres, countries, languages, year, latest, search) حتى لا يتعارض اسم سيرفر جديد معها.
- `/content/` الهب يبقى 302 لأول سيرفر الآن، ويصير صفحة هب حقيقية (أحدث المحتوى + التصنيفات + السيرفرات) في مرحلة لاحقة.
- الشرطة المائلة الأخيرة إلزامية للكيانات، وبدونها 301.

### Faceted navigation
- الفلاتر (`?y= ?genre= ?r= ?sort= ?q= ?view=`) تبقى على صفحات السيرفرات وصفحات التصنيفات **noindex + canonical للصفحة الأم**، و`robots.txt` يمنع `/*?q=` و`/api/`.
- لا تُنشأ أي صفحة SEO من تركيبة فلاتر. الصفحات الرسمية فقط: الكيانات + التصنيف/الدولة/اللغة/السنة (بُعد واحد) + latest.

---

## 6. SEO architecture

| العنصر | القاعدة |
|---|---|
| **Title** | فريد ومن قالب لكل نوع ولغة، قابل للتجاوز من اللوحة. مثال: `طبيعة الحب \| قصة المسلسل والحلقات والممثلين والمخرج` · `Tabiat Al Hob (2024) \| Story, Episodes, Cast & Director`. |
| **Meta description** | مولَّد من بيانات الصفحة الفعلية (السنة، الدولة، التصنيف، عدد المواسم، أبرز الممثلين)، لا نسخ القصة، ≤160 حرفًا، قابل للتجاوز. |
| **Canonical** | ذاتي لكل كيان ولغة. صفحات السيرفرات لا تُنشئ نسخًا بديلة للكيان؛ أي تحويل من إعلان سيرفر يمر عبر `utm` لا عبر مسار مختلف. |
| **Hreflang** | `ar` + `en` + `x-default`(ar) على كل زوج **مفهرس في اللغتين**. الصفحة الإنجليزية بلا overview إنجليزي تُرسم لكن `noindex` ولا تدخل الزوج. |
| **Index policy** | فيلم/مسلسل: `index` إذا `match∈{tmdb,xtream}` + poster + overview ≥ 120 حرفًا باللغة. موسم: noindex إلا بملخص موسم + حلقات بعناوين. حلقة: **لا صفحة** إلا بعنوان + ملخص ≥ 80 حرفًا + تاريخ. شخص: index إذا ≥ 2 أعمال في الكتالوج أو نبذة+صورة. تصنيف/دولة/لغة/سنة: index إذا ≥ 12 عنصرًا، pagination حتى 50 صفحة × 60. |
| **Schema.org** | `Movie` · `TVSeries` (+`numberOfSeasons/Episodes`) · `TVSeason` · `TVEpisode` · `Person` · `BreadcrumbList` (الرئيسية › المسلسلات › التركية › الاسم › الموسم › الحلقة) · `ItemList` للقوائم · `FAQPage` فقط حين تُعرض الإجابات في الصفحة · `VideoObject` فقط عند وجود trailer حقيقي مضمَّن (TMDB/Xtream `youtube_trailer`). لا حقول بلا بيانات. |
| **Open Graph / Twitter** | `og:type` = `video.movie` / `video.tv_show` / `video.episode` / `profile`، `og:image` = backdrop أو poster بأبعاده، `twitter:card=summary_large_image`. |
| **الصور** | `alt` وصفي («ملصق فيلم Wonder Woman (2017)»، «الممثل X في مسلسل Y»)، `width/height`، `srcset` بمقاسات TMDB، الصورة الأساسية `fetchpriority=high`، الباقي `loading=lazy`. الصور غير TMDB عبر `/content/<server>/img/` (موجود) مع تحويل WebP عند توفر Pillow. |
| **Internal linking** | من كل كيان: المخرج، الممثلون (≤12)، التصنيفات، الدولة، اللغة، السنة، المواسم، «قد يعجبك أيضًا» (≤12 بترتيب: مشاركة تصنيف + دولة + لغة + ممثل/مخرج + قرب السنة + التقييم، محسوب عند البناء ومخزَّن)، والسيرفرات المتوفر عليها. من صفحات الأشخاص والتصنيفات → الأعمال. من صفحات السيرفرات والبطاقات والبحث → الكيان. |
| **Sitemap** | `/sitemap.xml` يصبح **sitemap index** يشير إلى: `sitemap-guide.xml` (الحالي) · `sitemap-movies-{n}.xml` · `sitemap-series-{n}.xml` · `sitemap-seasons-{n}.xml` · `sitemap-episodes-{n}.xml` · `sitemap-people.xml` · `sitemap-taxonomy.xml` (10k رابط/ملف، `lastmod` من `updated_at`، `xhtml:link` للغتين). يُدرَج فقط ما `index=1`. يُولَّد ويُخزَّن على القرص بعد كل بناء. IndexNow للجديد والمتغيّر. |
| **robots.txt** | يُضاف: `Disallow: /api/` · `Disallow: /*?q=` · `Disallow: /*?view=grid` · `Disallow: /content/search` · الإدارة. يبقى `/static/` و`/content/*/img/` مسموحًا. |

---

## 7. Arabic / English architecture
- نفس `content_page.Lang` و`tr()` (تعمل اليوم)؛ كل قالب جديد يُكتب بالطريقة نفسها.
- بيانات الكيان ثنائية في الأعمدة (`title_ar/title_en/overview_ar/overview_en`)؛ الصفحة العربية تعرض `title_ar` وتضيف الاسم الأصلي تحته؛ الإنجليزية العكس.
- السقوط (fallback): إن غاب `title_ar` يُعرض الإنجليزي/الأصلي في العنوان ويبقى `index` معتمدًا على overview فقط.
- `og:locale` و`<html lang dir>` لكل لغة (موجود).

---

## 8. Redirect strategy
- **لا URL حالي يتغيّر**: `/content/<server>` و`/en/content/<server>` تبقى كما هي (6 روابط مفهرسة). نافذة التفاصيل تبقى وتضاف فيها «صفحة الفيلم ←».
- `/ar/content/*` → 301 → `/content/*`.
- كيان بلا شرطة أخيرة → 301 بالشرطة.
- جدول `redirect` لكل slug قديم عند تغييره أو دمج كيانين (301 للكيان الباقي).
- `/content/<server>?q=<name>` يبقى (بحث داخلي، noindex).
- الصفحات القديمة التي يختارها المدير لإلغائها لا تُحذف بل `noindex` ثم 410 بعد 90 يومًا (اختياري).

---

## 9. Implementation (ملفات)

**جديدة** (تُضاف إلى `Dockerfile` COPY):
- `seo_db.py` — المخطط، الفهارس، الترحيل بالنسخة، استعلامات القراءة (كيان، أشخاص، قوائم، مشابه، بحث FTS).
- `seo_match.py` — التطبيع والـ slugs والمطابقة والدمج والـ aliases.
- `seo_sources.py` — عميل TMDB (ar-SA/en-US، credits، alternative_titles، seasons) + Xtream `get_vod_info`/`get_series_info`، كاش في `api_cache`، تحديد سرعة، إعادة محاولة.
- `seo_build.py` — خط البناء التزايدي من فهارس السيرفرات → SQLite (يعمل في `_content_loop` بعد كل سحب، وخيط backfill قابل للاستئناف للكتالوج الحالي).
- `seo_pages.py` — القوالب: movie · series · season · episode · person · genre · country · language · year · latest · hub، + `seo_meta` (title/desc/canonical/hreflang/OG/JSON-LD) + كاش LRU للصفحات المرسومة (10 دقائق، يُبطَل عند البناء).
- `seo_sitemap.py` — sitemap index + الملفات المجزّأة + IndexNow.
- `seo_head.py` — helper مشترك لرأس الصفحة (title/desc/canonical/hreflang/OG/Twitter/JSON-LD) يستعمله الجديد، ويمكن لاحقًا للوحدات القديمة.
- `tests/test_dockerfile.py` يتحقق أن كل وحدة جديدة في سطر COPY؛ وتُضاف gzip + ETag/304 لصفحات الكيانات في `_send` (اختياري في المرحلة 3).
- `seo_admin.html` + مسارات `/api/content/seo/*` — الإحصاءات، البحث عن كيان، تحرير override، ربط tmdb_id يدويًا، دمج، إعادة بناء، مفتاح TMDB (مشفَّر بـ `crypto_store`).
- `tests/test_seo.py` + `tests/mock_tmdb.py` + `tests/ui_seo.js`.

**تُعدَّل** (بحد أدنى):
- `xm_lines.py`: توجيه المسارات الجديدة قبل `/content/<server>`، `robots.txt`، `/sitemap.xml` → index، 301 للشرطة و`/ar/`، استدعاء `seo_build.tick` في دورة المحتوى.
- `content.py`: كلمات محجوزة في `key_ok`؛ تصدير `tmdb_id`/`series_id` من ردود Xtream في الفهرس (حقول جديدة اختيارية `t`, `sid` لا تكسر القديم).
- `content_page.py`: رابط «صفحة الفيلم» في البطاقة والنافذة؛ نتائج البحث من FTS الموحّد مع «متوفر في: كاسبر · فالكون».
- `content_admin.html`: رابط إلى لوحة SEO.
- `README.md`: قسم جديد.

---

## 10. Migration plan (خطوة بخطوة، كل خطوة قابلة للنشر وحدها)

| # | الخطوة | الخطر | التحقق |
|---|---|---|---|
| 0 | نسخة احتياطية لمجلد `data/content/` (ملفات JSON لا تُمسّ أصلًا)، و`seo.sqlite` ملف جديد منفصل. | لا شيء | — |
| 1 | `seo_db` + `seo_match` + `seo_build` من الفهارس الحالية فقط (بلا شبكة): كيانات موحّدة بمفتاح محلي + `content_service` + aliases. لا صفحات عامة بعد. | لا شيء ظاهر للزائر | اختبارات وحدة؛ تقرير أعداد: كم كيانًا موحّدًا، كم مشتركًا بين السيرفرات |
| 2 | `seo_sources`: استخراج `tmdb_id` من Xtream، ثم TMDB backfill في الخلفية (مفتاح من اللوحة)، ثم `get_series_info` تزايديًا للمواسم/الحلقات. | حدود API | نسبة المطابقة في لوحة SEO |
| 3 | صفحات الأفلام والمسلسلات خلف علم `seo.enabled` و**noindex مبدئيًا** → مراجعة عينة → تفعيل `index` بالسياسة أعلاه. | متوسط | Rich Results Test، اختبارات UI 360px |
| 4 | sitemap index + robots + IndexNow + روابط من صفحات السيرفرات والنافذة والبحث. | منخفض | GSC coverage |
| 5 | لوحة التحكم (overrides، ربط يدوي، دمج). | منخفض | ui test |
| 6 | الأشخاص والتصنيفات والدول واللغات والسنوات و`/latest/` + «قد يعجبك». | منخفض | — |
| 7 | المواسم والحلقات (مشروطة بالمحتوى الفريد)، FAQ، trailer/VideoObject. | منخفض | — |
| 8 | هب `/content/` بدل التحويل 302 (اختياري). | منخفض | — |

**الأداء**: SQLite WAL + فهارس؛ لا استعلام يعيد أكثر من صفحة واحدة؛ كاش الصفحات المرسومة؛ الحلقات تُحمَّل بالموسم (≤ 100 لكل طلب) لا دفعة واحدة؛ `CATALOG` يُحلَّل مرة ويُخزَّن؛ الصور بمقاسات TMDB + lazy + أبعاد ثابتة.

---

## 11. أسئلة تحتاج قرارك قبل البدء

1. **مفتاح TMDB API**: هل تملك مفتاحًا (مجاني من themoviedb.org)؟ بدونه تُنفَّذ المراحل 1–5 ببيانات Xtream فقط، وتُؤجَّل الصفحات ثنائية اللغة الكاملة وصفحات الأشخاص.
2. **البادئة العربية**: `/content/...` (المقترح، بلا تحويلات) أم `/ar/content/...` (كما في مثالك، ويستلزم 301 للصفحات الست الحالية)؟
3. **صفحة `/content/`**: تبقى تحويلًا لأول سيرفر الآن، أم تصبح هب المحتوى من المرحلة 3؟
4. **الحلقات**: الموافقة على قاعدة «لا صفحة حلقة بلا عنوان + ملخص + تاريخ» (أي أغلب الـ 500k حلقة ستبقى نصًا داخل صفحة المسلسل/الموسم).
5. **الترتيب**: هل تبدأ المرحلة 1 فورًا بعد الموافقة؟


---

## 12. الضوابط المعتمدة (قرار المالك، 1 أكتوبر 2026)

1. TMDB API يُستعمل؛ مفتاحه في إعدادٍ مشفَّر (‏`crypto_store`) أو متغيّر بيئة، لا في الكود ولا Git.
2. العربية `/content/...` والإنجليزية `/en/content/...`؛ `/ar/content/...` → 301. لا تغيير لأي URL عربي حالي بلا خطة redirects.
3. `/content/` يصير Content Hub في مرحلته، ولا يُكسر سلوكه الحالي قبلها.
4. لا صفحة حلقة مفهرسة بلا بيانات حقيقية كافية؛ شروط الفهرسة في `seo_settings` لا في الكود.
5. لا حذف لأي بيانات، لا تغيير مباشر لأي URL، لا redirects جماعية قبل خريطة Old→New مُراجَعة ومختبرة، 301 واضح لكل تغيير، rollback لكل مرحلة.
6. قبل تفعيل الفهرسة: Feature Flag ووضع اختبار على عينة (HTTP status · canonical · hreflang · title · description · H1 · breadcrumb · schema · internal links · sitemap · robots · redirects · لا canonical مكرّر).
7. المطابقة: TMDB ID ← معرّف موثوق ← الاسم الأصلي + السنة + النوع ← النص آخرًا؛ الثقة المنخفضة إلى «Needs Review» لا دمج. وداخل السيرفر الواحد: نفس الاسم بسنة أو tmdb_id أو نوع مختلف = كيانان؛ الشك = مراجعة. وTMDB ID من مصدر خارجي يُتحقق منه (title · original title · year · type · country عند توفرها) قبل اعتماده.
8. مصدر كل معلومة ووقتها مسجَّل (Xtream · TMDB · Manual · Derived).
9. الإثراء قابل للاستئناف: كاش، retry، backoff، بلا تكرار طلبات.
10. لا توليد صفحات HTML ثابتة؛ قاعدة الكيانات ثم routing/templates ثم إثراء تدريجي ثم فهرسة تدريجية.
11. بعد كل مرحلة تقريرٌ ومراجعة قبل التالية.

## 13. حال التنفيذ

| المرحلة | الحال | ما أُنجز |
|---|---|---|
| 1 — طبقة الكيانات | **منجزة بتعديلات المالك، بانتظار المراجعة** | `seo_db.py` · `seo_match.py` · `seo_build.py` · بطاقة في `content_admin.html` · مسارات المدير · `tests/test_seo.py` (66 اختبارًا، منها الحالات العشر المطلوبة) · قسم في README. التعديلات: slug لاتيني بأولوية + `redirect` عند التغيير؛ فصل المتشابهين داخل السيرفر الواحد (سنة/tmdb مختلفان = كيانان، بلا قرينة = مراجعة)؛ `verify_tmdb` لا يعتمد المعرّف وحده؛ `provenance.prev` و`apply_fields` يحمي اليدوي. لا صفحة عامة ولا URL تغيّر. |
| 2 — Xtream info + TMDB + تصنيف التركي/الأنمي + البحث + صفحات المعاينة | **منجزة أوليًّا بقرارات المالك الأربعة، بانتظار النشر والعيّنة الحقيقية** (`docs/phase2-report.md`) | `seo_sources.py` · `seo_search.py` · `seo_pages.py` · الإدارة · 123 اختبارًا. لا فهرسة ولا sitemap ولا تغيير URL. |
| 3 — تفعيل الفهرسة التدريجي + sitemap + الربط من الصفحات القائمة | لم تبدأ (بعد فحص العيّنة وموافقتك) | — |
| 4 — sitemap/robots/IndexNow والربط | لم تبدأ | — |
| 5 — لوحة التحكم | لم تبدأ | — |
| 6 — الأشخاص والتصنيفات وlatest | لم تبدأ | — |
| 7 — المواسم والحلقات وFAQ | لم تبدأ | — |
| 8 — هب `/content/` | لم تبدأ | — |


## 14. قرار الـ slug النهائي (معتمد)

لاتيني دائمًا: الاسم الإنجليزي ← الأصلي ← نقحرة مؤقتة للعربي الأصيل تُرقّى عند ظهور اسم إنجليزي موثوق. لا اسم عربي في الرابط النهائي. أمثلة: `breaking-bad` · `kurulus-osman` · `attack-on-titan`. التغيير بسبب حقيقي فقط، ويحفظ `entity_id` ويولّد 301 بلا سلاسل.

# المرحلة الثانية — تصميم الإثراء والتصنيف (Turkish Hub · Anime Hub) — للاعتماد قبل التنفيذ

> وثيقة تصميم فقط. لا إثراء جماعي ولا صفحة عامة قبل الموافقة. تبني على المرحلة الأولى المعتمدة (`docs/content-seo-plan.md`).

## 0. حقائق من السيرفرات الحية (1 أكتوبر 2026) تحكم التصميم

| الملاحظة | الدليل | الأثر |
|---|---|---|
| **اسم القسم ليس مصدر تصنيف موثوقًا** | قسم «Anime أنمي» في فالكون يضم Batman: The Dark Knight Returns؛ قسم «مسلسلات انمي مدبلج» في سمارت يضم «مغامرات جاكي تشان» و«قصص الحيوان في القرآن» | القسم **قرينة ضعيفة** فقط؛ الحكم من TMDB |
| **المسلسلات التركية بأسماء عربية + لاحقة نسخة** | كاسبر: «طبيعة الحب مدبلج»، «الكرامة مترجم»، «السعادة العائلية مترجم سوفت»؛ سمارت: 3 أقسام تركية (مترجم/مدبلج/[TR] 2026) | تطبيع اللواحق، و**النسخة (مدبلج/مترجم) صفة على رابط السيرفر لا كيانًا** |
| **الأنمي في سمارت بأسماء إنجليزية** (787 مسلسلًا) | «Re:ZERO», «Mobile Suit Gundam: The Witch from Mercury» | مطابقة TMDB مباشرة |
| العمل الواحد في قسمين (مترجم ومدبلج) على السيرفر نفسه | «السعادة العائلية مترجم» و«… مترجم سوفت» | بعد تطبيع اللاحقة يلتقيان بقواعد المرحلة الأولى (الصورة/السنة) أو يذهبان للمراجعة |

## 1. مصدر بيانات الأنمي

- **الأساس: TMDB** (`/tv/{id}` و`/movie/{id}` مع `append_to_response=credits,keywords,alternative_titles,translations,external_ids`): `genres` (16 = Animation)، `original_language`، `origin_country`، `keywords` (210024 = anime)، `production_companies` (الاستوديو)، `networks`، `created_by`، `status`، المواسم والحلقات (`/tv/{id}/season/{n}`: عنوان وملخص وتاريخ ومدة وصورة لكل حلقة)، `aggregate_credits` (الممثلون ومؤدّو الأصوات بأدوارهم، المخرج، الكاتب).
- **قرينة ضعيفة: Xtream** (`get_series_info` / `get_vod_info`: `genre`، `cast`، `director`، `country` إن وُجد) واسم القسم.
- **اختياري لاحقًا (مرحلة 2ب، بعد موافقة مستقلة): AniList GraphQL** (مجاني، بلا مفتاح، 90 طلب/دقيقة): `format` (TV · MOVIE · OVA · ONA · SPECIAL)، الاستوديوهات، الحالة، `idMal`. هو المصدر الوحيد الموثوق لـ OVA/Special؛ TMDB لا يميّزها إلا كحلقات «Specials» في الموسم 0.

## 2. مصدر بيانات التركي

- **الأساس: TMDB**: `origin_country` يحوي `TR`، أو `original_language == "tr"`؛ الأسماء العربية من `translations` (ar) و`alternative_titles`.
- **قرائن ضعيفة**: Xtream `country` (إن أعطته اللوحة)، واسم القسم (TURKISH · [TR] · تركي · TURKEY)، ولاحقة الاسم (مدبلج/مترجم تدلّ على عمل غير عربي، لا على تركي بعينه).
- **المطابقة للأسماء العربية**: `search/tv?query=<الاسم بعد حذف اللاحقة>&language=ar-SA` (TMDB يبحث في الترجمات)، ثم `verify_tmdb`؛ وإن فشل: بحث بالاسم الإنجليزي إن كان في القسم أو alias.

## 3. كيف يُحكم أن العمل أنمي

```
anime = (TMDB genre 16 Animation) AND (original_language == "ja" OR "JP" in origin_country OR keyword 210024)
```
- `format` (عمود جديد في `content`): `series` · `movie` · `anime_series` · `anime_movie`؛ و`ova` · `special` محجوزان لمرحلة 2ب (AniList) أو تعيينٍ يدوي. الأنمي **ليس نوعًا منفصلًا**: `type` يبقى movie/series، و`format` صفة.
- مصدر الحكم ومستوى الثقة في `content_taxonomy.source/confidence`. تعارض القسم مع TMDB (قسم أنمي + TMDB يقول US Animation) → بند `taxonomy_mismatch` للمدير، ويُعتمد TMDB.
- بلا TMDB: لا يُعدّ أنمي ولو كان في قسم أنمي (الدليل في §0)؛ يُسجَّل `hint` معلّقًا يظهر للمدير.

## 4. كيف يُحكم أن العمل تركي

```
turkish = "TR" in origin_country OR original_language == "tr"      (TMDB أو manual)
```
- التركي **تصنيف (Taxonomy/Hub) لا نوع**: صفّ في `content_taxonomy` بمفتاح `country:TR`، والهب `/content/turkish/` استعلامٌ عليه.
- القسم/اللاحقة قرينة معلّقة (`hint`) لا تُدخل العمل الهب؛ تُستعمل لترتيب طابور الإثراء (التركي أولًا) ولمراجعة المدير.
- دبلجة/ترجمة: `content_service.versions_json` = `["dubbed","subbed"]` من اللاحقة؛ تُعرض في صفحة العمل («متوفر مدبلجًا في كاسبر، مترجمًا في سمارت») ولا تنشئ كيانًا.

## 5. الجداول والأعمدة الجديدة

| جدول/عمود | الغرض |
|---|---|
| `content.format`, `content.original_language`, `content.origin_country_json`, `content.status`, `content.tmdb_type`, `content.popularity`, `content.last_air_date` | صفات من TMDB |
| `content_service.versions_json` | مدبلج/مترجم/سوفت لكل سيرفر |
| `taxonomy(id, kind, key, slug, name_ar, name_en, intro_ar, intro_en, index_flag, sort)` | `kind`: hub (turkish · anime) · genre · country · language · year · studio · network |
| `content_taxonomy(content_id, taxonomy_id, source, confidence, at)` | العضوية؛ `source` ∈ tmdb · manual · hint؛ الهب يقرأ `source != 'hint'` فقط |
| `person(id, tmdb_id, slug, name_ar, name_en, original_name, bio_ar, bio_en, photo, known_for, index_flag)` و`content_person(content_id, person_id, role, character, ord, source)` | الممثلون ومؤدّو الأصوات والمخرج والكاتب والمؤلف (`role`: actor · voice · director · writer · creator) |
| `company(id, tmdb_id, slug, name, kind studio/network, logo)` و`content_company` | الاستوديو والشبكة |
| `episode(id, content_id, season, number, title_ar, title_en, overview_ar, overview_en, air_date, runtime, still, tmdb_id, index_flag)` | حلقات TMDB (و`season` القائم يكتمل بالاسم والملخص والصورة) |
| `genre_map(raw, taxonomy_id)` | «Action, Adventure» من اللوحات → التصنيف المعياري (TMDB genre ids) |
| `group_rule(pattern, hint_json, enabled)` | قواعد أسماء الأقسام (تركي/أنمي/كوري/هندي/نسخة) — **تُعدَّل من الإدارة** |
| `enrich_queue(content_id, source, state, attempts, next_at, error, updated_at)` | طابور الإثراء القابل للاستئناف |
| `api_cache` (قائم) | ردود TMDB/Xtream كاملة بوقتها؛ السلبي (لا نتيجة) يُخزَّن 30 يومًا |

كل كتابة عبر `seo_db.apply_fields` (المصدر، الوقت، القيمة السابقة؛ اليدوي محمي).

## 6. منع الكيانات المكرّرة

1. الهب والتصنيف **استعلامات** على `content_taxonomy`؛ لا جدول ولا صفّ يكرّر العمل.
2. ترتيب الهوية: `tmdb_id` مُتحقَّق (`verify_tmdb`: النوع والسنة ±1 واسم من الأسماء) ← ملصق TMDB ← الاسم الأصلي+السنة+النوع ← النص. والثقة المنخفضة → `review` لا دمج.
3. تطبيع اللواحق قبل المطابقة (`مدبلج` · `مترجم` · `سوفت` · `Dubbed` · `Subbed` · `[TR]`…) من `group_rule`، والاسم الخام يبقى alias.
4. عند حصول عملين على `tmdb_id` واحد مُتحقَّق: يُدمجان بقواعد المرحلة الأولى (الأقدم يبقى، الآخر `merged_into`، وredirect إن كان له رابط منشور) ويُسجَّل `merged_entities`.
5. `tmdb_id` فريد في `content` (قيد UNIQUE قائم) — محاولة إسناد معرّف مستعمل لكيان آخر ترفض وتذهب للمراجعة.

## 7. بنية الروابط

| الصفحة | عربي (x-default) | إنجليزي |
|---|---|---|
| هب التركي | `/content/turkish/` | `/en/content/turkish/` |
| أقسامه | `/content/turkish/series/` · `/content/turkish/movies/` · `/content/turkish/ongoing/` · `/content/turkish/completed/` · `/content/turkish/genres/{genre}/` · `/content/turkish/year/{yyyy}/` | `/en/…` |
| هب الأنمي | `/content/anime/` · `/content/anime/series/` · `/content/anime/movies/` · `/content/anime/ongoing/` · `/content/anime/completed/` · `/content/anime/genres/{genre}/` · `/content/anime/year/{yyyy}/` · `/content/anime/studios/{slug}/` | `/en/…` |
| ترقيم | `…/page/{n}/` | |
| العمل نفسه | يبقى `/content/series/{slug}/` و`/content/movies/{slug}/` **فقط** | |
| الأشخاص | `/content/people/actors/{slug}/` · `/content/people/directors/{slug}/` (والمؤلّف/مؤدّي الصوت أدوار داخل صفحة الشخص، لا مسارات جديدة) | |
| الدولة تركيا | `/content/countries/turkey/` → **301** إلى `/content/turkish/` (صفحة واحدة لا اثنتان) | |

الكلمات `turkish` و`anime` تُضاف إلى المحجوزات في `content.key_ok`. لا رابط للهب يحوي اسم سيرفر.

## 8. Canonical لكل هب

- كل صفحة هب (وكل صفحة ترقيم) **canonical لنفسها**.
- أي معامل (`?sort= ?genre= ?y= ?q=`) → `noindex` + canonical للصفحة الأم بلا معاملات.
- `/content/countries/turkey/` و`/content/genres/animation/` لا يحملان canonical إلى الهب: الأول يحوّل 301، والثاني صفحة مختلفة (Animation ≠ Anime) تربط إلى هب الأنمي.
- الصفحة الإنجليزية canonical لنفسها + hreflang للعربية و`x-default`.

## 9. الترقيم

- `page_size` 60 (إعداد)، `list_max_pages` 50 (إعداد): ما بعده لا يُربط ولا يدخل sitemap (ويبقى موصولًا من التصنيف/السنة الأضيق).
- ترتيب ثابت (آخر إضافة ثم `id`) فلا تتبدّل محتويات الصفحة بين زحفين؛ الصفحة 1 بلا `/page/1/` (301 إليها).
- روابط «السابق/التالي» في HTML (و`rel=prev/next` كمساعد لا كإشارة أساسية).

## 10. ما يُفهرس وما لا يُفهرس

| الصفحة | index | الشرط |
|---|---|---|
| هب التركي/الأنمي وأقسامه الثابتة (series/movies/ongoing/completed) | نعم | ≥ `list_min_items` (12) عملًا مؤكّدًا |
| هب حسب النوع / السنة | نعم | ≥ 12 عملًا؛ وإلا تُرسم noindex ولا تُربط |
| صفحات الترقيم حتى الحدّ | نعم | — |
| أي معامل استعلام | لا | — |
| عمل بلا TMDB (محلي) | لا، ولا يظهر في أي هب | حتى يُطابَق أو يُعيَّن يدويًا |
| استوديو | نعم إن ≥ 3 أعمال | |
| شخص | نعم إن ≥ 2 أعمال في الكتالوج أو نبذة + صورة | |
| الحلقات | لا صفحة إلا بعنوان + ملخص ≥ 80 + تاريخ (إعداد) | |

## 11. Schema لكل هب

- `CollectionPage` (+ `BreadcrumbList`) و`ItemList` بعناصر `TVSeries`/`Movie` (الاسم والرابط والصورة والتقييم عند وجوده) — لصفحة الهب وأقسامه.
- `FAQPage` فقط إن عُرضت الأسئلة وإجاباتها فعلًا (مثلًا «ما أحدث المسلسلات التركية المدبلجة؟» بقائمة مرئية).
- الاستوديو: `Organization`؛ الشخص: `Person` بـ `performerIn`/`director` حيث تتوفر.
- لا `VideoObject` في الهب (لا فيديو مضمَّن).

## 12. ربط الهب بالمحتوى الأساسي

- الهب ← العمل: كل بطاقة تشير إلى `/content/series/{slug}/`.
- العمل ← الهب: في رأس صفحة العمل رقاقات «مسلسل تركي» → `/content/turkish/`، «أنمي» → `/content/anime/`، النوع → `/content/turkish/genres/{g}/`، السنة → `…/year/`؛ وفي «قد يعجبك» أعمال من التصنيف نفسه أولًا.
- الهب ← الأشخاص والاستوديوهات ← أعمالهم؛ والهب ← أقسامه ← ترقيمه. والهب في `sitemap-taxonomy.xml`.

## 13. العربية والإنجليزية

- نصوص الواجهة بـ `Lang.tr()` كما هي؛ مقدمة كل هب نصّان أصليان في `taxonomy.intro_ar/intro_en` يحرّرهما المدير (وأكتب مسودة أولى)، لا ترجمة آلية.
- أسماء الأعمال من `title_ar`/`title_en` (TMDB `translations`)، وإلا الأصلي؛ لاحقة النسخة لا تدخل العنوان.
- الهب الإنجليزي يُفهرس دائمًا (نصّه لنا) مع hreflang؛ صفحة العمل الإنجليزية تظلّ مشروطة بـ overview إنجليزي.

## 14. الأعمال بلا بيانات كافية

- تبقى كيانات `match='local'` في القاعدة (لا تُحذف)، خارج الهب والفهرسة والأشخاص، وفي صفحة المدير: «غير مطابَق» بعدده، مع «عيّن TMDB ID» يدويًا (بعد `verify_tmdb` أو تجاوز صريح يُسجَّل manual) و«ادمج مع…».
- قرائن الأقسام تُحفظ `hint` فيراها المدير («في قسم تركي لكن بلا TMDB: 143 عملًا»).
- الإثراء يعيد المحاولة بتباعد (ساعة، يوم، أسبوع) ثم يتوقف ويسجّل السبب؛ وتغيّر الاسم في السيرفر يعيد العمل للطابور.

## 15. خطّ الإثراء (قابل للاستئناف، بلا تكرار)

1. **فحص أولي (Probe)** قبل أي إثراء: 20 فيلمًا و20 مسلسلًا من كل لوحة عبر `get_vod_info`/`get_series_info` لتثبيت الحقول الفعلية (tmdb_id؟ country؟ cast؟ الحلقات؟) — تقريره لك قبل المتابعة.
2. **Xtream** (مجاني، لوحة بلوحة، بحدّ 1 طلب/ثانية وفي نافذة ليلية): يملأ `tmdb_id` المرشّح والممثلين والمخرج والدولة والنسخة والحلقات؛ تزايديًّا بعد كل سحب (الجديد والمتغيّر فقط).
3. **TMDB** (مفتاح من الإدارة مشفّرًا بـ `crypto_store` أو `TMDB_API_KEY`): 4 طلبات/ثانية (حدّ TMDB ~50)؛ لكل عمل: تحقق المعرّف المرشّح أو بحث ← تفاصيل بـ append_to_response ← المواسم (للمسلسلات). تقدير أول دفعة: ~90 ألف طلب للأعمال و~60 ألفًا للمواسم ≈ 10–12 ساعة في الخلفية، تُستأنف من `enrich_queue` بعد أي توقف، وكل ردّ في `api_cache` فلا يُعاد.
4. **الترتيب**: التركي والأنمي (بقرائن الأقسام) أولًا، ثم الأحدث إضافة، ثم الباقي.
5. **بوابة قبل الفهرسة**: علم `seo.enabled` + وضع معاينة للمدير + عيّنة 30 عملًا (تركي، أنمي، عالمي، عربي) تُفحص: HTTP status · canonical · hreflang · title · description · H1 · breadcrumb · schema · internal links · sitemap · robots · redirects · لا canonical مكرّر — تقريرها قبل تفعيل `index`.

## 16. ما تسلّمه المرحلة الثانية (بعد الموافقة) وما لا تسلّمه

- **تسلّم**: الجداول والأعمدة أعلاه، `group_rule` و`genre_map` بقيم أولية، عميل TMDB وXtream info مع الكاش والطابور، الفحص الأولي، الإثراء التدريجي خلف الإدارة، التصنيف التركي/الأنمي كبيانات، إحصاءات الإدارة (مطابَق/غير مطابَق/تركي/أنمي/يحتاج مراجعة)، الاختبارات بلوحة TMDB وهمية.
- **لا تسلّم**: أي صفحة عامة (هب أو عمل)، sitemap، robots، فهرسة — تلك المرحلة الثالثة بعد تقرير المرحلة الثانية وموافقتك.

## 17. أسئلة تحتاج قرارك

1. اعتماد تعريف الأنمي (Animation + يابانية/JP/keyword) — أم تريد توسيعه ليشمل الأنمي الصيني/الكوري (donghua/aeni)؟
2. AniList لـ OVA/Special والاستوديوهات: الآن (مرحلة 2ب) أم لاحقًا؟
3. `/content/countries/turkey/` يحوّل إلى `/content/turkish/` (المقترح) أم يبقيان صفحتين بمحتوى مختلف؟
4. نافذة الإثراء من Xtream: ليلًا بتوقيت السعودية (المقترح 02:00–06:00) حتى لا يُحمَّل السيرفر وقت الذروة؟


## قاعدة hreflang (مواصفة — بعد اللقطة 13)
- **الأهلية باللغة**: صفحة العمل بلغةٍ ما تستحق الفهرسة بشروط `seo_settings` (مطابقة TMDB/Xtream، ملصق، قصة بتلك اللغة ≥ `index_min_overview`). الصفحتان تُرسمان دائمًا (200) ويربط بينهما رابط تبديل اللغة.
- **لغتان مستحقّتان**: الصفحتان تحملان المجموعة نفسها متبادلةً: `ar` ← العربية، `en` ← الإنجليزية، `x-default` ← العربية (اللغة الافتراضية بلا بادئة).
- **لغةٌ واحدة مستحقّة**: لا يُرسل أي `<link rel="alternate" hreflang>` في الصفحتين؛ كل صفحة canonical لنفسها. **التبرير**: hreflang علاقةٌ بين صفحاتٍ قابلة للفهرسة؛ الإشارة إلى صفحةٍ noindex (غير المستحقّة ستكون noindex في المرحلة 3) تُهمَل من محرّك البحث وتُعدّ خطأً في أدوات التدقيق، وتوجيه `x-default` إلى صفحةٍ noindex أسوأ. فالبديل الوحيد الصحيح للصفحة الوحيدة المستحقّة أن تقف وحدها. وليس هذا تخطّيًا للفحص: الفحص يتحقّق من **غياب** الوسوم ومن canonical الذاتي ورابط التبديل في هذه الحالة.
- **الخريطة**: تحمل رابط كل لغةٍ مستحقّة فقط، فعضوية الخريطة تساوي الأهلية لغةً لغة.
- **الفحص**: `hreflang_reciprocal` في العيّنة (بالحالة: bilingual / single:ar / single:en) و`global_hreflang_canonical_coverage` على كل كيانٍ مستحقٍّ بلغةٍ على الأقل (لا عيّنة)، مع أهلية اللغات على القاعدة كلها.

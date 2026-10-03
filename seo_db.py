# -*- coding: utf-8 -*-
"""طبقة كيانات المحتوى لمحرّكات البحث — قاعدة SQLite مشتقّة (‏data/content/seo.sqlite).

الفيلم أو المسلسل **كيانٌ واحد** مهما تعدّدت السيرفرات التي يتوفّر عليها (كاسبر · فالكون · سمارت): جدول ‏content
هو الأصل، و‏content_service يربطه بكل سيرفرٍ فيه. وهي قاعدةٌ مشتقّة من فهارس السيرفرات (‏<السيرفر>.json) التي لا
تُمسّ، ويُعاد بناؤها منها كاملةً في أي وقت (‏seo_build)، ولا يُحذف منها شيء: ما غاب من كل السيرفرات يُعلَّم
‏available=0 ويبقى بمعرّفه ورابطه.

كل معلومةٍ (عنوان، سنة، قصة، تقييم…) مسجَّلٌ مصدرها ووقتها في ‏provenance: ‏m3u (من ملف القائمة) · xtream (واجهة
اللوحة) · tmdb · manual (المدير، ولا يكتب فوقه البناء) · derived (محسوبة). والمطابقة بين السيرفرات محافظة: ما لم تكفِ
قرائنه يُترك في ‏review للمراجعة اليدوية بدل دمجه. وعتبات المطابقة وشروط الفهرسة في ‏seo_settings تُعدَّل بلا نشر.

بلا مكتبات خارجية: sqlite3 من المكتبة القياسية، وWAL فلا يحجب البناءُ القراءة.
"""
import json
import os
import sqlite3
import threading
import time

DIR = "content"
FILE = "seo.sqlite"
VERSION = 6                    # PRAGMA user_version — يرتفع مع كل ترحيل

SOURCES = ("m3u", "xtream", "tmdb", "manual", "derived")   # ‏m3u = ما في فهرس السيرفر الحالي (Existing)
MANUAL = "manual"
PRECEDENCE = {"m3u": 0, "derived": 0, "xtream": 1, "tmdb": 2, "manual": 3}   # مصدرٌ أدنى لا يكتب فوق أعلى
# مسارات الكيانات القادمة (المرحلة 3) — تُستعمل الآن لتسجيل تحويلات slug في ‏redirect
PATHS = {"movie": "/content/movies/{slug}/", "series": "/content/series/{slug}/"}
EN = "/en"
DEFAULT_LANG = "ar"            # بلا بادئة؛ وكل لغةٍ أخرى ببادئة /xx — من إعداد languages (العربية والإنجليزية الآن)


def lang_prefix(lang):
    """‏ar ← "" · en ← "/en" · tr ← "/tr" …: البنية تقبل لغةً جديدة بإضافتها إلى الإعداد، بلا ترحيل."""
    return "" if lang == DEFAULT_LANG else f"/{lang}"
TYPES = ("movie", "series")

# الإعدادات الافتراضية — ما في جدول seo_settings يغلبها (مفتاح ← قيمة JSON). لا شيء منها ثابتٌ في الكود المستهلك.
DEFAULTS = {
    # المطابقة بين السيرفرات (seo_match.pair_score): الاسم المطبَّع وحده لا يكفي للدمج
    "merge_min": 2,            # أقل مجموع قرائن يُدمج عنده عنصران بنفس الاسم
    "score_year": 2,           # نفس السنة في الطرفين
    "score_poster": 3,         # نفس ملف ملصق TMDB — يكاد يكون هويةً
    "score_plot": 2,           # قصّتان متشابهتان
    "plot_same": 0.5,          # تشابه الكلمات (Jaccard) الذي يُعدّ عنده القصّتان واحدة
    "plot_diff": 0.1,          # وما دونه قصّتان مختلفتان: تعارض
    "plot_min": 40,            # أقل طول قصة تُقارن
    "score_genre": 1,          # تصنيفٌ مشترك
    "score_tmdb": 5,           # ‏tmdb_id واحد (بعد التحقّق منه)
    "score_seasons": 1,        # في السيرفر نفسه: موسمٌ بعدد حلقاته نفسه في القسمين
    "tmdb_verify": {"type": True, "year": True, "year_tolerance": 1, "title": True},   # معرّف TMDB من لوحةٍ لا يُعتمد بلا تحقّق
    # سياسة الفهرسة (للمراحل التالية؛ تُقرأ من هنا لا من الكود)
    "index_min_overview": 120,     # أقل طول قصة باللغة لتُفهرس صفحة فيلم/مسلسل
    "index_require_poster": True,
    "index_match": ["tmdb", "xtream"],   # مصادر الهوية التي تُفهرس صفحتها؛ المحلي لا يُفهرس حتى يُراجَع
    "episode_page": {"title": True, "overview_min": 80, "air_date": True},   # شروط صفحة الحلقة
    "person_min_works": 2,
    "list_min_items": 12,
    "list_max_pages": 50,
    "page_size": 60,
    # النسخ: لواحق في أسماء السيرفرات صفةٌ على رابط السيرفر لا على هوية العمل («طبيعة الحب مدبلج» = «طبيعة الحب»)
    "version_tags": {"dubbed": ["مدبلج", "مدبلجة", "مدبلج للعربية", "dubbed", "dub", "ar dub", "arabic dub"],
                     "subbed_soft": ["مترجم سوفت", "سوفت", "soft sub", "softsub"],
                     "subbed": ["مترجم", "مترجمة", "متردم", "subbed", "sub", "subtitled", "ar sub"],
                     "multi": ["متعدد الترجمات", "متعدد اللغات والترجمات", "متعدد اللغات", "متعددة الترجمات", "multi sub", "multi-sub", "multisub", "multi"]},
    "score_version": 2,        # في السيرفر نفسه: الاسمان لا يختلفان إلا بلاحقة النسخة
    "score_season_split": 2,   # في السيرفر نفسه: مدخلان للعمل نفسه برمزَي موسمين مختلفين («… S03 …» و«… S04 …»)
    "name_tail_tokens": ["ar", "en", "tr", "arabic", "english"],   # ذيولٌ في اسم السيرفر بعد الاسم الأصلي تُحذف («YASAK ELMA Ar»)
    # الإثراء (المرحلة 2): نافذة ليلية بتوقيت السعودية، وسرعات، وتباعد المحاولات، ولا يُفترض اكتماله في ليلة
    "enrich_window": {"start": "02:00", "end": "06:00", "tz_offset": 3},
    "xtream_rps": 1.0, "tmdb_rps": 4.0,
    "enrich_backoff": [3600, 86400, 604800],          # ساعة، يوم، أسبوع — ثم يتوقف ويسجّل السبب
    "cache_ttl": {"ok": 30 * 86400, "miss": 30 * 86400, "error": 3600},
    "enrich_batch": 200,                              # لكل دورة (كل عشر دقائق داخل النافذة)
    # الأنمي: طبقات — is_animation (TMDB genre Animation) ← anime_family (لغةٌ أصلية/بلدُ منشأ من هذه الجداول) ← anime_kind؛
    # Animation وحدها لا تعني أنمي، وكلمة TMDB المفتاحية «anime» لا تحسم النوع (بلا لغة/بلد: غير محسوم)
    "anime_langs": {"ja": "japanese", "zh": "chinese", "ko": "korean"},
    "anime_countries": {"JP": "japanese", "CN": "chinese", "TW": "chinese", "HK": "chinese", "KR": "korean"},
    "anime_keyword_ids": [210024],                    # TMDB keyword «anime»
    "hub_countries": {"turkish": ["TR"]},             # الهب ← بلدان المنشأ
    "search_max_suggest": 5, "search_min_conf": 0.75,   # اقتراحٌ تحت العتبة لا يُعرض
    "tmdb_key": "",                                   # مشفَّرٌ في القاعدة (crypto_store)؛ أو TMDB_API_KEY في البيئة
    "preview": False,                                 # صفحات الكيانات والهبّات في وضع المعاينة (noindex) — المرحلة 2
    "index_live": False,                              # المرحلة 4: الصفحات **المعتمدة** (build_state.index_approved) تُخدم index؛ ما عداها noindex كما كان
    "sitemap_live": False,                            # المرحلة 5: المعتمد المستحقّ يدخل /sitemap.xml العامة (بعد بوابة المرحلة 5 وحدها)
    "identity_freeze": [],                            # معرّفات كياناتٍ مجمّدة أثناء مراجعة المالك: لا انقسام ولا دمج ولا تبديل رابط ولا تحويل ولا كتابة TMDB
    "scan_quiet_hours": {"start": 0, "end": 12, "utc_offset": 3},   # فحص السكّان كاملًا يعمل في وقت الهدوء فقط: من 12 صباحًا إلى 12 ظهرًا بتوقيت السعودية (UTC+3)
    "enrich_auto": False,                             # الإثراء الجماعي الليلي لا يبدأ قبل اعتماد العيّنة الحقيقية
    "languages": ["ar", "en"],                        # اللغات الفعّالة (الصفحات والإثراء)؛ تُضاف tr · es · fr … بلا ترحيل
}
SECRET_SETTINGS = ("tmdb_key",)

_locks = {}                    # مسار القاعدة ← قفل الكتابة (بناءٌ واحد في وقته)
_lk = threading.Lock()


def path(data_dir):
    return os.path.join(data_dir, DIR, FILE)


def lock(data_dir):
    with _lk:
        return _locks.setdefault(os.path.abspath(path(data_dir)), threading.RLock())


def connect(data_dir, create=True):
    """اتصالٌ جديد (رخيص؛ لكل عملية اتصالها) بعد ضمان المخطط. ‏None إن لم تُنشأ القاعدة بعد و‏create=False."""
    p = path(data_dir)
    if not create and not os.path.exists(p):
        return None
    os.makedirs(os.path.dirname(p), exist_ok=True)
    con = sqlite3.connect(p, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA foreign_keys=ON")
    migrate(con)
    return con


SCHEMA = """
CREATE TABLE IF NOT EXISTS content (
  id INTEGER PRIMARY KEY,
  type TEXT NOT NULL CHECK (type IN ('movie','series')),
  tmdb_id INTEGER, imdb_id TEXT,
  slug TEXT NOT NULL UNIQUE, slug_ar TEXT,
  slug_source TEXT NOT NULL DEFAULT 'original',   -- en · original · translit · manual: من أيّ اسمٍ صُنع (لا يتغيّر إلا بتحويل)
  title TEXT NOT NULL,                 -- الاسم كما في القوائم (أفضل صيغة)
  title_ar TEXT, title_en TEXT, original_title TEXT,
  overview TEXT, overview_ar TEXT, overview_en TEXT,
  release_date TEXT, year INTEGER,
  rating REAL, votes INTEGER, runtime INTEGER, status TEXT,
  poster TEXT, backdrop TEXT, trailer_yt TEXT,
  genres_json TEXT,                     -- التصنيفات الخام من اللوحات (والمعيارية في content_taxonomy)
  format TEXT NOT NULL DEFAULT '',      -- '' · anime_series · anime_movie · ova · special (الأنمي صفةٌ لا نوع)
  anime_kind TEXT,                      -- japanese · chinese · korean (لا تُخلط) — فقط عند الدليل (لغة/بلد المنشأ)
  is_animation INTEGER NOT NULL DEFAULT 0,  -- رسوم متحركة (TMDB genre Animation) — ليست أنمي بالضرورة
  anime_family INTEGER,                 -- NULL: لم يُحسم · 0: رسومٌ ليست أنمي (إسباني/أمريكي…) · 1: أنمي (بنوعه في anime_kind)
  episodes_official INTEGER, seasons_official INTEGER,   -- عدد الحلقات والمواسم الرسمي (TMDB) — لا يُخلط بالمدرج في القوائم
  original_language TEXT, origin_country_json TEXT, tmdb_type TEXT, popularity REAL, last_air_date TEXT,
  match TEXT NOT NULL DEFAULT 'local' CHECK (match IN ('local','xtream','tmdb','manual')),
  confidence INTEGER NOT NULL DEFAULT 0,
  available INTEGER NOT NULL DEFAULT 1,  -- 0: غاب من كل السيرفرات (لا يُحذف)
  merged_into INTEGER REFERENCES content(id),
  index_ar INTEGER NOT NULL DEFAULT 0, index_en INTEGER NOT NULL DEFAULT 0,
  first_seen INTEGER, last_seen INTEGER, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS content_type_year ON content(type, year);
CREATE INDEX IF NOT EXISTS content_tmdb ON content(tmdb_id);
CREATE INDEX IF NOT EXISTS content_avail ON content(available, updated_at);

CREATE TABLE IF NOT EXISTS content_alias (
  content_id INTEGER NOT NULL REFERENCES content(id),
  alias TEXT NOT NULL, alias_norm TEXT NOT NULL,
  lang TEXT, source TEXT NOT NULL, service_key TEXT, at INTEGER NOT NULL,
  kind TEXT NOT NULL DEFAULT 'raw',     -- raw · title · original · translation · alternative · manual
  phonetic TEXT,                        -- المفتاح الصوتي (seo_search.phonetic): «بريزن بريك» و«Prison Break» واحد
  verified INTEGER NOT NULL DEFAULT 1, confidence REAL NOT NULL DEFAULT 1.0,
  PRIMARY KEY (content_id, alias_norm)
);
CREATE INDEX IF NOT EXISTS alias_norm ON content_alias(alias_norm);
CREATE INDEX IF NOT EXISTS alias_phonetic ON content_alias(phonetic);

-- معرّفات المصادر الخارجية لأي كيان: TMDB · AniList · IMDb · Xtream … (يُضاف مصدرٌ بلا ترحيل)
CREATE TABLE IF NOT EXISTS external_id (
  entity TEXT NOT NULL, entity_id INTEGER NOT NULL,
  source TEXT NOT NULL,                -- tmdb · anilist · imdb · mal · xtream:<service>
  external_id TEXT NOT NULL,
  verified INTEGER NOT NULL DEFAULT 0, confidence REAL NOT NULL DEFAULT 0, how TEXT, at INTEGER NOT NULL,
  PRIMARY KEY (entity, entity_id, source)
);
CREATE UNIQUE INDEX IF NOT EXISTS external_unique ON external_id(entity, source, external_id) WHERE verified=1;

-- التصنيف: هبّات (turkish · anime) وأنواع وبلدان ولغات وسنوات واستوديوهات — والعمل يعضو فيها بلا نسخ
CREATE TABLE IF NOT EXISTS taxonomy (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,                  -- hub · genre · country · language · year · studio · network · anime_kind
  key TEXT NOT NULL,                   -- turkish · anime · 28 · TR · ja · 2024 · tmdb:1234 …
  slug TEXT NOT NULL,
  name_ar TEXT, name_en TEXT, intro_ar TEXT, intro_en TEXT,   -- المقدمة تحريرية من الإدارة
  seo_title_ar TEXT, seo_title_en TEXT, meta_ar TEXT, meta_en TEXT,
  index_flag INTEGER NOT NULL DEFAULT 1, sort INTEGER NOT NULL DEFAULT 0, updated_at INTEGER NOT NULL,
  UNIQUE (kind, key), UNIQUE (kind, slug)
);
CREATE TABLE IF NOT EXISTS content_taxonomy (
  content_id INTEGER NOT NULL REFERENCES content(id),
  taxonomy_id INTEGER NOT NULL REFERENCES taxonomy(id),
  source TEXT NOT NULL,                -- tmdb · manual · hint (القسم: قرينة لا تُدخل الهب) · disputed (TMDB خالف القسم: مراجعة، لا هب)
  confidence REAL NOT NULL DEFAULT 1.0, at INTEGER NOT NULL,
  PRIMARY KEY (content_id, taxonomy_id)
);
CREATE INDEX IF NOT EXISTS ct_tax ON content_taxonomy(taxonomy_id, source);

CREATE TABLE IF NOT EXISTS person (
  id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL, name_ar TEXT, name_en TEXT, original_name TEXT,
  bio_ar TEXT, bio_en TEXT, photo TEXT, birthday TEXT, known_for TEXT,
  name_norm TEXT,                      -- مفتاح الاسم (seo_match.person_key): بلا ترتيبٍ ولا تشكيلٍ ولا فاصلة عليا — للتوحيد قبل معرّف TMDB
  index_flag INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS person_norm ON person(name_norm);
CREATE TABLE IF NOT EXISTS content_person (
  content_id INTEGER NOT NULL REFERENCES content(id),
  person_id INTEGER NOT NULL REFERENCES person(id),
  role TEXT NOT NULL,                  -- actor · voice · director · writer · creator
  character TEXT, ord INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL,
  PRIMARY KEY (content_id, person_id, role)
);
CREATE INDEX IF NOT EXISTS cp_person ON content_person(person_id);

CREATE TABLE IF NOT EXISTS company (
  id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL, kind TEXT NOT NULL,   -- studio · network
  logo TEXT, country TEXT, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS content_company (
  content_id INTEGER NOT NULL REFERENCES content(id), company_id INTEGER NOT NULL REFERENCES company(id),
  role TEXT NOT NULL, source TEXT NOT NULL, PRIMARY KEY (content_id, company_id, role)
);

CREATE TABLE IF NOT EXISTS episode (
  id INTEGER PRIMARY KEY,
  content_id INTEGER NOT NULL REFERENCES content(id), season INTEGER NOT NULL, number INTEGER NOT NULL,
  title_ar TEXT, title_en TEXT, overview_ar TEXT, overview_en TEXT, air_date TEXT, runtime INTEGER, still TEXT,
  source TEXT,                                   -- tmdb · xtream: من أين جاء السجل (الموسم 0 = حلقات خاصة)
  index_flag INTEGER NOT NULL DEFAULT 0, updated_at INTEGER NOT NULL,
  UNIQUE (content_id, season, number)
);

CREATE TABLE IF NOT EXISTS genre_map (raw_norm TEXT PRIMARY KEY, taxonomy_id INTEGER REFERENCES taxonomy(id), source TEXT NOT NULL);

-- قواعد أسماء الأقسام: قرائن (hint) تُعدَّل من الإدارة — ليست مصدر الحقيقة
CREATE TABLE IF NOT EXISTS group_rule (
  id INTEGER PRIMARY KEY, pattern TEXT NOT NULL, hint_json TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, note TEXT
);

-- طابور الإثراء القابل للاستئناف: لكل عمل ومصدر حالٌ ومحاولات وموعد
CREATE TABLE IF NOT EXISTS enrich_queue (
  content_id INTEGER NOT NULL REFERENCES content(id), source TEXT NOT NULL,   -- xtream · tmdb · tmdb_seasons
  state TEXT NOT NULL DEFAULT 'pending',   -- pending · done · miss · error · skip
  priority INTEGER NOT NULL DEFAULT 5, attempts INTEGER NOT NULL DEFAULT 0, next_at INTEGER NOT NULL DEFAULT 0,
  error TEXT, updated_at INTEGER NOT NULL,
  PRIMARY KEY (content_id, source)
);
CREATE INDEX IF NOT EXISTS eq_state ON enrich_queue(source, state, priority, next_at);

CREATE TABLE IF NOT EXISTS content_service (
  content_id INTEGER NOT NULL REFERENCES content(id),
  service_key TEXT NOT NULL,
  kind TEXT NOT NULL, local_key TEXT NOT NULL,    -- مفتاح العنصر في فهرس السيرفر (content._ikey)
  name TEXT NOT NULL, year INTEGER, stream_id INTEGER, added INTEGER,
  seasons_json TEXT, groups_json TEXT,
  versions_json TEXT, raw_names_json TEXT,       -- النسخ (dubbed · subbed · subbed_soft) والأسماء كما جاءت
  series_id INTEGER,                             -- معرّف المسلسل في لوحة Xtream (لـ get_series_info)
  stream_ids_json TEXT,                          -- كل أرقام بثّ المدخلات المطويّة في هذا العنصر (مواسم مفرّقة بأسمائها)
  present INTEGER NOT NULL DEFAULT 1, first_seen INTEGER NOT NULL, seen_at INTEGER NOT NULL,
  PRIMARY KEY (service_key, kind, local_key)
);
CREATE INDEX IF NOT EXISTS cs_content ON content_service(content_id);
CREATE INDEX IF NOT EXISTS cs_service ON content_service(service_key, present);

CREATE TABLE IF NOT EXISTS season (
  content_id INTEGER NOT NULL REFERENCES content(id),
  number INTEGER NOT NULL,
  name TEXT, overview_ar TEXT, overview_en TEXT, poster TEXT, air_date TEXT,
  episode_count INTEGER NOT NULL DEFAULT 0,      -- المدرج في القوائم (أكبر ما في السيرفرات؛ قد يكون أجزاءً لا حلقات)
  episodes_official INTEGER,                     -- الرسمي من TMDB (حلقات الموسم)
  index_flag INTEGER NOT NULL DEFAULT 0, updated_at INTEGER NOT NULL,
  PRIMARY KEY (content_id, number)
);

CREATE TABLE IF NOT EXISTS provenance (
  entity TEXT NOT NULL, entity_id INTEGER NOT NULL, field TEXT NOT NULL,
  source TEXT NOT NULL CHECK (source IN ('m3u','xtream','tmdb','manual','derived')),
  service_key TEXT, at INTEGER NOT NULL,
  prev TEXT,                           -- القيمة السابقة (JSON) عند التغيير
  PRIMARY KEY (entity, entity_id, field)
);

CREATE TABLE IF NOT EXISTS review (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,                  -- name_only · conflict · year_conflict · merged_entities · …
  key TEXT NOT NULL UNIQUE,            -- ثابتٌ بين البناءات، فلا يتكرّر البند
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open', -- open · resolved · stale
  decision_json TEXT,
  created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS review_status ON review(status, kind);

CREATE TABLE IF NOT EXISTS seo_override (
  entity TEXT NOT NULL, entity_id INTEGER NOT NULL, lang TEXT NOT NULL,
  seo_title TEXT, meta_desc TEXT, slug TEXT, overview TEXT, intro TEXT, faq_json TEXT,
  index_flag INTEGER, canonical TEXT, updated_at INTEGER NOT NULL,
  PRIMARY KEY (entity, entity_id, lang)
);

CREATE TABLE IF NOT EXISTS redirect (
  path TEXT PRIMARY KEY, target TEXT NOT NULL, code INTEGER NOT NULL DEFAULT 301,
  reason TEXT, created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS api_cache (
  key TEXT PRIMARY KEY, body TEXT, status INTEGER NOT NULL, at INTEGER NOT NULL
);

-- نصوص الكيانات بأي لغة (العنوان والقصة ومقدمة SEO…): العربية والإنجليزية الآن (وتُعكس في أعمدة *_ar/*_en)، وأي لغةٍ
-- لاحقة بالصفّ نفسه — بلا ترحيل
CREATE TABLE IF NOT EXISTS content_text (
  entity TEXT NOT NULL, entity_id INTEGER NOT NULL, lang TEXT NOT NULL, field TEXT NOT NULL,
  value TEXT NOT NULL, source TEXT NOT NULL, updated_at INTEGER NOT NULL,
  PRIMARY KEY (entity, entity_id, lang, field)
);

CREATE TABLE IF NOT EXISTS seo_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS build_state (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at INTEGER NOT NULL);
"""


_V2_COLS = {"content": ["format TEXT NOT NULL DEFAULT ''", "anime_kind TEXT", "original_language TEXT", "origin_country_json TEXT",
                        "tmdb_type TEXT", "popularity REAL", "last_air_date TEXT"],
            "content_service": ["versions_json TEXT", "raw_names_json TEXT", "series_id INTEGER"],
            "content_alias": ["kind TEXT NOT NULL DEFAULT 'raw'", "phonetic TEXT", "verified INTEGER NOT NULL DEFAULT 1",
                              "confidence REAL NOT NULL DEFAULT 1.0"]}


_V5_COLS = {"episode": ["source TEXT"]}
_V6_COLS = {"person": ["name_norm TEXT"]}
_V4_COLS = {"content": ["is_animation INTEGER NOT NULL DEFAULT 0", "anime_family INTEGER", "episodes_official INTEGER", "seasons_official INTEGER"],
            "content_service": ["stream_ids_json TEXT"], "season": ["episodes_official INTEGER"]}


def _add_cols(con, table, cols):
    have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    for c in cols:
        if c.split()[0] not in have:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {c}")


def migrate(con):
    v = con.execute("PRAGMA user_version").fetchone()[0]
    if v >= VERSION:
        return
    with con:
        # الأعمدة الجديدة على الجداول القائمة **قبل** نصّ المخطط: فيه فهارس على أعمدةٍ جديدة (person.name_norm) تفشل على قاعدةٍ قديمة
        if v:                                  # قاعدةٌ قائمة: أعمدةٌ تُضاف بلا إعادة بناء (الجداول الناقصة ينشئها المخطط بعدها)
            for ver, cols_by_table in ((2, _V2_COLS), (4, _V4_COLS), (5, _V5_COLS), (6, _V6_COLS)):
                if v < ver:
                    for t, cols in cols_by_table.items():
                        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone():
                            _add_cols(con, t, cols)
        con.executescript(SCHEMA)              # الجداول والفهارس الجديدة (IF NOT EXISTS)
        con.execute(f"PRAGMA user_version={VERSION}")


# ================= الإعدادات =================
def settings(con):
    """الافتراضيات وفوقها ما حُفظ في القاعدة."""
    out = dict(DEFAULTS)
    for r in con.execute("SELECT key, value FROM seo_settings"):
        try:
            out[r["key"]] = json.loads(r["value"])
        except ValueError:
            pass
    return out


def set_setting(con, key, value):
    if key not in DEFAULTS:
        raise ValueError(f"إعدادٌ غير معروف: {key}")
    with con:
        con.execute("INSERT INTO seo_settings(key, value, updated_at) VALUES (?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (key, json.dumps(value, ensure_ascii=False), int(time.time())))


def state(con, key, default=None):
    r = con.execute("SELECT value FROM build_state WHERE key=?", (key,)).fetchone()
    if not r:
        return default
    try:
        return json.loads(r["value"])
    except ValueError:
        return default


def set_state(con, key, value):
    con.execute("INSERT INTO build_state(key, value, updated_at) VALUES (?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, json.dumps(value, ensure_ascii=False), int(time.time())))


# ================= المصدر =================
def provenance(con, entity, entity_id):
    """حقل ← (المصدر، السيرفر، الوقت)."""
    return {r["field"]: (r["source"], r["service_key"], r["at"])
            for r in con.execute("SELECT field, source, service_key, at FROM provenance WHERE entity=? AND entity_id=?",
                                 (entity, entity_id))}


def set_provenance(con, entity, entity_id, field, source, service_key=None, at=None, prev=None):
    con.execute("INSERT INTO provenance(entity, entity_id, field, source, service_key, at, prev) VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(entity, entity_id, field) DO UPDATE SET source=excluded.source, "
                "service_key=excluded.service_key, at=excluded.at, prev=excluded.prev",
                (entity, entity_id, field, source, service_key, at or int(time.time()),
                 json.dumps(prev, ensure_ascii=False) if prev is not None else None))


def manual_fields(con, entity, entity_id):
    return {r["field"] for r in con.execute("SELECT field FROM provenance WHERE entity=? AND entity_id=? AND source=?",
                                            (entity, entity_id, MANUAL))}


def apply_fields(con, entity, entity_id, fields, source, service_key=None, now=None, manual=None):
    """يكتب حقول كيانٍ من مصدرٍ ما — **ولا يمسّ ما كتبه المدير** (مصدره manual) إلا إن كان المصدر manual نفسه —
    ويسجّل لكل حقلٍ تغيّر مصدره ووقته وقيمته السابقة ← الحقول التي تغيّرت. ‏fields: حقل ← قيمة، أو حقل ← (قيمة، مصدر، سيرفر).
    تستعمله المزامنة التلقائية كلها (البناء، وXtream وTMDB لاحقًا)، فلا طريق لها إلى حقلٍ يدوي."""
    now = now or int(time.time())
    table = {"content": "content", "season": "season", "person": "person", "episode": "episode", "taxonomy": "taxonomy"}[entity]
    row = con.execute(f"SELECT * FROM {table} WHERE id=?", (entity_id,)).fetchone()
    if row is None:
        raise ValueError("no such entity")
    if manual is not None:
        keep = {f: MANUAL for f in manual}
    else:
        keep = {r["field"]: r["source"] for r in con.execute(
            "SELECT field, source FROM provenance WHERE entity=? AND entity_id=?", (entity, entity_id))}
    sets, args, changed = [], [], []
    for field, spec in fields.items():
        v, src, svc = spec if isinstance(spec, tuple) else (spec, source, service_key)
        if field not in row.keys() or row[field] == v:
            continue
        if PRECEDENCE.get(keep.get(field, ""), -1) > PRECEDENCE.get(src, 0):   # اليدوي فوق TMDB فوق Xtream فوق الفهرس
            continue
        if v is None and row[field] is not None and src != MANUAL:            # مصدرٌ آلي لا يمحو قيمةً بفراغ
            continue
        sets.append(f"{field}=?"); args.append(v); changed.append(field)
        set_provenance(con, entity, entity_id, field, src, svc, now, prev=row[field])
    if sets:
        sets.append("updated_at=?"); args.append(now)
        con.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE id=?", (*args, entity_id))
    return changed


def paths(typ, slug):
    """روابط الكيان باللغتين (كما ستُخدم في المرحلة 3)."""
    p = PATHS[typ].format(slug=slug)
    return [p, EN + p]


def change_slug(con, content_id, new_slug, source="manual", reason="", now=None, slug_source=None):
    """‏source: من كتب (manual · tmdb) للمصدر؛ ‏slug_source: من أي اسمٍ صُنع (en · original · translit · manual)."""
    """يبدّل رابط الكيان **بلا مسّ معرّفه**، ويسجّل القديم → الجديد 301 في ‏redirect (ويُحدّث ما كان يشير إلى القديم)."""
    now = now or int(time.time())
    row = con.execute("SELECT type, slug FROM content WHERE id=?", (content_id,)).fetchone()
    if row is None:
        raise ValueError("no such entity")
    if new_slug == row["slug"]:
        return False
    if con.execute("SELECT 1 FROM content WHERE slug=? AND id!=?", (new_slug, content_id)).fetchone():
        raise ValueError("slug مستعمل")
    con.execute("UPDATE content SET slug=?, slug_source=?, updated_at=? WHERE id=?", (new_slug, slug_source or source, now, content_id))
    set_provenance(con, "content", content_id, "slug", source, None, now, prev=row["slug"])
    for old, new in zip(paths(row["type"], row["slug"]), paths(row["type"], new_slug)):
        con.execute("DELETE FROM redirect WHERE path=?", (new,))              # لا حلقة: الجديد لم يعد قديمًا
        con.execute("UPDATE redirect SET target=? WHERE target=?", (new, old))   # ما كان يشير إلى القديم يقفز إلى الجديد
        con.execute("INSERT INTO redirect(path, target, code, reason, created_at) VALUES (?,?,301,?,?) "
                    "ON CONFLICT(path) DO UPDATE SET target=excluded.target, reason=excluded.reason, created_at=excluded.created_at",
                    (old, new, reason or f"slug {row['slug']} → {new_slug}", now))
    return True


def schema_text(con):
    """نصّ المخطط كما في القاعدة — للتقرير."""
    return "\n".join(r[0] + ";" for r in con.execute(
        "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type DESC, name"))


# ================= المعرّفات الخارجية والتصنيف =================
def set_external(con, entity, entity_id, source, ext_id, verified=False, confidence=0.0, how="", now=None):
    """يسجّل معرّف مصدرٍ خارجي لكيان — والمُتحقَّق منه فريدٌ لكل مصدر (معرّفٌ واحد لا يملكه كيانان)."""
    if verified:
        other = con.execute("SELECT entity_id FROM external_id WHERE entity=? AND source=? AND external_id=? AND verified=1 "
                            "AND entity_id!=?", (entity, source, str(ext_id), entity_id)).fetchone()
        if other:
            raise ValueError(f"{source}:{ext_id} مسجَّلٌ لكيانٍ آخر ({other[0]})")
    con.execute("INSERT INTO external_id(entity, entity_id, source, external_id, verified, confidence, how, at) VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(entity, entity_id, source) DO UPDATE SET external_id=excluded.external_id, verified=excluded.verified, "
                "confidence=excluded.confidence, how=excluded.how, at=excluded.at",
                (entity, entity_id, source, str(ext_id), 1 if verified else 0, float(confidence), how, now or int(time.time())))


def external(con, entity, entity_id):
    return {r["source"]: dict(r) for r in con.execute("SELECT * FROM external_id WHERE entity=? AND entity_id=?", (entity, entity_id))}


def taxonomy_id(con, kind, key, slug=None, name_ar=None, name_en=None, now=None):
    """معرّف صفّ التصنيف، ويُنشأ إن لم يوجد."""
    r = con.execute("SELECT id FROM taxonomy WHERE kind=? AND key=?", (kind, str(key))).fetchone()
    if r:
        return r["id"]
    base = slug or str(key).lower()
    slug, n = base, 2
    while con.execute("SELECT 1 FROM taxonomy WHERE kind=? AND slug=?", (kind, slug)).fetchone():   # استوديوهان باسمٍ واحد
        slug, n = f"{base}-{n}", n + 1
    cur = con.execute("INSERT INTO taxonomy(kind, key, slug, name_ar, name_en, updated_at) VALUES (?,?,?,?,?,?)",
                      (kind, str(key), slug, name_ar, name_en, now or int(time.time())))
    return cur.lastrowid


def set_membership(con, content_id, tax_id, source, confidence=1.0, now=None):
    """عضوية عملٍ في تصنيف. ‏hint لا يكتب فوق tmdb/manual، وmanual يغلب الكل."""
    rank = {"hint": 0, "disputed": 0, "tmdb": 1, "manual": 2}
    cur = con.execute("SELECT source FROM content_taxonomy WHERE content_id=? AND taxonomy_id=?", (content_id, tax_id)).fetchone()
    if cur and rank.get(cur["source"], 0) > rank.get(source, 0):
        return False
    con.execute("INSERT INTO content_taxonomy(content_id, taxonomy_id, source, confidence, at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(content_id, taxonomy_id) DO UPDATE SET source=excluded.source, confidence=excluded.confidence, at=excluded.at",
                (content_id, tax_id, source, float(confidence), now or int(time.time())))
    return True


def merge_content(con, loser, winner, reason="", now=None):
    """كيانان تبيّن أنهما عملٌ واحد (معرّف TMDB مُتحقَّق واحد): يبقى ‏winner ويُعلَّم ‏loser مدمجًا فيه — روابط السيرفرات
    والأسماء والتصنيف والأشخاص والمواسم تنتقل، ورابط المدمج يحوَّل 301، ويُسجَّل الدمج للمراجعة. لا حذف لصفّ الكيان."""
    now = now or int(time.time())
    if loser == winner:
        return False
    lrow, wrow = (con.execute("SELECT type, slug, title FROM content WHERE id=?", (i,)).fetchone() for i in (loser, winner))
    if not lrow or not wrow or lrow["type"] != wrow["type"]:
        raise ValueError("لا يُدمج نوعان مختلفان")
    con.execute("UPDATE content_service SET content_id=? WHERE content_id=?", (winner, loser))
    # أشخاص العمل المدمج: صفّ اسمٍ من اللوحة لا ينتقل إن كان للفائز أدوارٌ من TMDB (TMDB يغلب الأسماء) أو شخصٌ بالاسم نفسه أصلًا
    # (العمل نفسه = الشخص نفسه) — وإلا تكرّر «Wentworth Miller» ثلاثًا في «بطولة»
    con.execute("INSERT OR IGNORE INTO content_person(content_id, person_id, role, character, ord, source) "
                "SELECT ?, cp.person_id, cp.role, cp.character, cp.ord, cp.source FROM content_person cp JOIN person p ON p.id=cp.person_id WHERE cp.content_id=? "
                "AND NOT EXISTS (SELECT 1 FROM content_person w JOIN person wp ON wp.id=w.person_id WHERE w.content_id=? AND wp.name_norm=p.name_norm AND wp.name_norm IS NOT NULL) "
                "AND NOT (cp.source='xtream' AND EXISTS (SELECT 1 FROM content_person w WHERE w.content_id=? AND w.source='tmdb'))", (winner, loser, winner, winner))
    con.execute("DELETE FROM content_person WHERE content_id=?", (loser,))
    con.execute("DELETE FROM person WHERE id NOT IN (SELECT person_id FROM content_person) AND NOT EXISTS (SELECT 1 FROM external_id x WHERE x.entity='person' AND x.entity_id=person.id)")
    for table, cols in (("content_alias", "content_id, alias, alias_norm, lang, source, service_key, at, kind, phonetic, verified, confidence"),
                        ("content_taxonomy", "content_id, taxonomy_id, source, confidence, at"),
                        ("content_company", "content_id, company_id, role, source"),
                        ("season", "content_id, number, name, overview_ar, overview_en, poster, air_date, episode_count, episodes_official, index_flag, updated_at"),
                        ("episode", "content_id, season, number, title_ar, title_en, overview_ar, overview_en, air_date, runtime, still, source, index_flag, updated_at")):
        rest = cols.split(", ", 1)[1]
        con.execute(f"INSERT OR IGNORE INTO {table}({cols}) SELECT ?, {rest} FROM {table} WHERE content_id=?", (winner, loser))
        con.execute(f"DELETE FROM {table} WHERE content_id=?", (loser,))
    con.execute("DELETE FROM external_id WHERE entity='content' AND entity_id=? AND (verified=0 OR source IN "
                "(SELECT source FROM external_id WHERE entity='content' AND entity_id=?))", (loser, winner))
    con.execute("UPDATE external_id SET entity_id=? WHERE entity='content' AND entity_id=?", (winner, loser))
    con.execute("DELETE FROM enrich_queue WHERE content_id=?", (loser,))
    con.execute("UPDATE content SET merged_into=?, available=0, updated_at=? WHERE id=?", (winner, now, loser))
    by_season = {}                                     # المدرج في القوائم بعد انتقال الروابط: أكبر ما في كل موسم عبر السيرفرات
    for r in con.execute("SELECT seasons_json FROM content_service WHERE content_id=? AND present=1", (winner,)):
        for s, n in json.loads(r["seasons_json"] or "[]"):
            by_season[int(s)] = max(by_season.get(int(s), 0), int(n))
    con.executemany("INSERT INTO season(content_id, number, episode_count, updated_at) VALUES (?,?,?,?) ON CONFLICT(content_id, number) DO UPDATE SET "
                    "episode_count=excluded.episode_count, updated_at=excluded.updated_at", [(winner, s, n, now) for s, n in by_season.items()])
    for old, new in zip(paths(lrow["type"], lrow["slug"]), paths(wrow["type"], wrow["slug"])):
        con.execute("UPDATE redirect SET target=? WHERE target=?", (new, old))
        con.execute("INSERT INTO redirect(path, target, code, reason, created_at) VALUES (?,?,301,?,?) ON CONFLICT(path) DO UPDATE SET "
                    "target=excluded.target, reason=excluded.reason, created_at=excluded.created_at", (old, new, reason or f"merged {loser} → {winner}", now))
    con.execute("INSERT INTO review(kind, key, payload_json, status, created_at, updated_at) VALUES ('merged_entities', ?, ?, 'open', ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at",
                (f"merged:{winner}:{loser}", json.dumps({"name": wrow["title"], "type": wrow["type"], "why": [reason or "same verified tmdb id"],
                                                          "items": [{"name": lrow["title"], "slug": lrow["slug"]}, {"name": wrow["title"], "slug": wrow["slug"]}]}, ensure_ascii=False), now, now))
    set_provenance(con, "content", loser, "merged_into", "derived", None, now, prev=None)
    return True


# ================= النصوص بأي لغة =================
_COLS = {"content": {"title": "title_{l}", "overview": "overview_{l}"}, "person": {"name": "name_{l}", "bio": "bio_{l}"},
         "taxonomy": {"name": "name_{l}", "intro": "intro_{l}", "seo_title": "seo_title_{l}", "meta": "meta_{l}"},
         "season": {"overview": "overview_{l}"}, "episode": {"title": "title_{l}", "overview": "overview_{l}"}}


def set_text(con, entity, entity_id, lang, field, value, source, now=None):
    """نصٌّ بلغةٍ ما بأسبقية المصادر (يدوي > TMDB > Xtream > الفهرس). للعربية والإنجليزية يُعكس في العمود المقابل أيضًا
    (‏title_ar…) عبر apply_fields؛ وأي لغةٍ أخرى في ‏content_text وحده ← هل كُتب؟"""
    now = now or int(time.time())
    if value is None or value == "":
        return False
    cur = con.execute("SELECT source FROM content_text WHERE entity=? AND entity_id=? AND lang=? AND field=?", (entity, entity_id, lang, field)).fetchone()
    if cur and PRECEDENCE.get(cur[0], 0) > PRECEDENCE.get(source, 0):
        return False
    con.execute("INSERT INTO content_text(entity, entity_id, lang, field, value, source, updated_at) VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(entity, entity_id, lang, field) DO UPDATE SET value=excluded.value, source=excluded.source, updated_at=excluded.updated_at",
                (entity, entity_id, lang, field, value, source, now))
    col = (_COLS.get(entity) or {}).get(field)
    if col and lang in ("ar", "en"):
        apply_fields(con, entity, entity_id, {col.format(l=lang): value}, source, now=now)
    return True


def get_text(con, entity, entity_id, lang, field, default=""):
    """النصّ بلغته: من العمود للعربية والإنجليزية، ومن content_text لغيرهما."""
    col = (_COLS.get(entity) or {}).get(field)
    if col and lang in ("ar", "en"):
        table = {"content": "content", "person": "person", "taxonomy": "taxonomy", "season": "season", "episode": "episode"}[entity]
        r = con.execute(f"SELECT {col.format(l=lang)} FROM {table} WHERE id=?", (entity_id,)).fetchone()
        if r and r[0]:
            return r[0]
    r = con.execute("SELECT value FROM content_text WHERE entity=? AND entity_id=? AND lang=? AND field=?", (entity, entity_id, lang, field)).fetchone()
    return r[0] if r else default

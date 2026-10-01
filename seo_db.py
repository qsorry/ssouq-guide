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
VERSION = 1                    # PRAGMA user_version — يرتفع مع كل ترحيل

SOURCES = ("m3u", "xtream", "tmdb", "manual", "derived")
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
    # سياسة الفهرسة (للمراحل التالية؛ تُقرأ من هنا لا من الكود)
    "index_min_overview": 120,     # أقل طول قصة باللغة لتُفهرس صفحة فيلم/مسلسل
    "index_require_poster": True,
    "index_match": ["tmdb", "xtream"],   # مصادر الهوية التي تُفهرس صفحتها؛ المحلي لا يُفهرس حتى يُراجَع
    "episode_page": {"title": True, "overview_min": 80, "air_date": True},   # شروط صفحة الحلقة
    "person_min_works": 2,
    "list_min_items": 12,
    "list_max_pages": 50,
    "page_size": 60,
}

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
  title TEXT NOT NULL,                 -- الاسم كما في القوائم (أفضل صيغة)
  title_ar TEXT, title_en TEXT, original_title TEXT,
  overview TEXT, overview_ar TEXT, overview_en TEXT,
  release_date TEXT, year INTEGER,
  rating REAL, votes INTEGER, runtime INTEGER, status TEXT,
  poster TEXT, backdrop TEXT, trailer_yt TEXT,
  genres_json TEXT,                     -- التصنيفات الخام من اللوحات (الجداول المعيارية في المرحلة التالية)
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
  PRIMARY KEY (content_id, alias_norm)
);
CREATE INDEX IF NOT EXISTS alias_norm ON content_alias(alias_norm);

CREATE TABLE IF NOT EXISTS content_service (
  content_id INTEGER NOT NULL REFERENCES content(id),
  service_key TEXT NOT NULL,
  kind TEXT NOT NULL, local_key TEXT NOT NULL,    -- مفتاح العنصر في فهرس السيرفر (content._ikey)
  name TEXT NOT NULL, year INTEGER, stream_id INTEGER, added INTEGER,
  seasons_json TEXT, groups_json TEXT,
  present INTEGER NOT NULL DEFAULT 1, first_seen INTEGER NOT NULL, seen_at INTEGER NOT NULL,
  PRIMARY KEY (service_key, kind, local_key)
);
CREATE INDEX IF NOT EXISTS cs_content ON content_service(content_id);
CREATE INDEX IF NOT EXISTS cs_service ON content_service(service_key, present);

CREATE TABLE IF NOT EXISTS season (
  content_id INTEGER NOT NULL REFERENCES content(id),
  number INTEGER NOT NULL,
  name TEXT, overview_ar TEXT, overview_en TEXT, poster TEXT, air_date TEXT,
  episode_count INTEGER NOT NULL DEFAULT 0,
  index_flag INTEGER NOT NULL DEFAULT 0, updated_at INTEGER NOT NULL,
  PRIMARY KEY (content_id, number)
);

CREATE TABLE IF NOT EXISTS provenance (
  entity TEXT NOT NULL, entity_id INTEGER NOT NULL, field TEXT NOT NULL,
  source TEXT NOT NULL CHECK (source IN ('m3u','xtream','tmdb','manual','derived')),
  service_key TEXT, at INTEGER NOT NULL,
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

CREATE TABLE IF NOT EXISTS seo_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS build_state (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at INTEGER NOT NULL);
"""


def migrate(con):
    v = con.execute("PRAGMA user_version").fetchone()[0]
    if v >= VERSION:
        return
    with con:
        con.executescript(SCHEMA)
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


def set_provenance(con, entity, entity_id, field, source, service_key=None, at=None):
    con.execute("INSERT INTO provenance(entity, entity_id, field, source, service_key, at) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(entity, entity_id, field) DO UPDATE SET source=excluded.source, "
                "service_key=excluded.service_key, at=excluded.at",
                (entity, entity_id, field, source, service_key, at or int(time.time())))


def schema_text(con):
    """نصّ المخطط كما في القاعدة — للتقرير."""
    return "\n".join(r[0] + ";" for r in con.execute(
        "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type DESC, name"))

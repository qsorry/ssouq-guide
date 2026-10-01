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

SOURCES = ("m3u", "xtream", "tmdb", "manual", "derived")   # ‏m3u = ما في فهرس السيرفر الحالي (Existing)
MANUAL = "manual"
# مسارات الكيانات القادمة (المرحلة 3) — تُستعمل الآن لتسجيل تحويلات slug في ‏redirect
PATHS = {"movie": "/content/movies/{slug}/", "series": "/content/series/{slug}/"}
EN = "/en"
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
  slug_source TEXT NOT NULL DEFAULT 'original',   -- en · original · translit · manual: من أيّ اسمٍ صُنع (لا يتغيّر إلا بتحويل)
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
    table = {"content": "content", "season": "season", "person": "person"}[entity]
    row = con.execute(f"SELECT * FROM {table} WHERE id=?", (entity_id,)).fetchone()
    if row is None:
        raise ValueError("no such entity")
    keep = manual if manual is not None else (manual_fields(con, entity, entity_id) if source != MANUAL else set())
    sets, args, changed = [], [], []
    for field, spec in fields.items():
        v, src, svc = spec if isinstance(spec, tuple) else (spec, source, service_key)
        if field in keep or field not in row.keys() or row[field] == v:
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


def change_slug(con, content_id, new_slug, source="manual", reason="", now=None):
    """يبدّل رابط الكيان **بلا مسّ معرّفه**، ويسجّل القديم → الجديد 301 في ‏redirect (ويُحدّث ما كان يشير إلى القديم)."""
    now = now or int(time.time())
    row = con.execute("SELECT type, slug FROM content WHERE id=?", (content_id,)).fetchone()
    if row is None:
        raise ValueError("no such entity")
    if new_slug == row["slug"]:
        return False
    if con.execute("SELECT 1 FROM content WHERE slug=? AND id!=?", (new_slug, content_id)).fetchone():
        raise ValueError("slug مستعمل")
    con.execute("UPDATE content SET slug=?, slug_source=?, updated_at=? WHERE id=?", (new_slug, source, now, content_id))
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

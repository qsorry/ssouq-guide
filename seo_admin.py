# -*- coding: utf-8 -*-
"""لوحة تحكم طبقة الكيانات (المرحلة 5): بحثٌ عن كيان، تجاوزات العنوان والوصف والمقدمة والفهرسة (‏seo_override)،
حقولٌ يدوية (لا يكتب فوقها البناء ولا الإثراء)، تغيير الرابط (301)، ربطٌ يدوي بمعرّف TMDB، ودمج كيانين.
كل كتابةٍ تحترم ‏identity_freeze (كيانٌ مجمّد لا يُمسّ) وتُرجَع عند أي خطأ، ولا حذف لشيء."""
import time

import seo_db

OVERRIDE_FIELDS = ("seo_title", "meta_desc", "intro", "overview", "canonical")
MANUAL_FIELDS = ("title_ar", "title_en", "overview_ar", "overview_en", "poster", "backdrop", "year", "original_title", "trailer_yt")
LANGS_OK = ("ar", "en")


def _frozen(con, cid):
    return int(cid) in {int(x) for x in (seo_db.settings(con).get("identity_freeze") or [])}


def _entity(con, cid):
    r = con.execute("SELECT * FROM content WHERE id=?", (int(cid),)).fetchone()
    if not r:
        raise ValueError("لا كيان بهذا المعرّف")
    return r


def search(data_dir, q, limit=20):
    """بحثٌ عن كيان باسمه أو slug أو معرّفه."""
    con = seo_db.connect(data_dir, create=False)
    if con is None:
        return []
    try:
        q = (q or "").strip()
        if not q:
            return []
        if q.isdigit():
            rows = con.execute("SELECT * FROM content WHERE id=? OR tmdb_id=? LIMIT ?", (int(q), int(q), limit)).fetchall()
        else:
            like = f"%{q}%"
            rows = con.execute("SELECT * FROM content WHERE slug LIKE ? OR title LIKE ? OR title_ar LIKE ? OR title_en LIKE ? "
                               "ORDER BY available DESC, id LIMIT ?", (like, like, like, like, limit)).fetchall()
        return [{"id": r["id"], "type": r["type"], "slug": r["slug"], "title": r["title"], "year": r["year"], "tmdb_id": r["tmdb_id"],
                 "match": r["match"], "available": r["available"], "merged_into": r["merged_into"]} for r in rows]
    finally:
        con.close()


def get(data_dir, cid):
    """الكيان بتجاوزاته ومصادر حقوله اليدوية ومعرّفاته الخارجية."""
    con = seo_db.connect(data_dir, create=False)
    if con is None:
        raise ValueError("لا قاعدة")
    try:
        r = _entity(con, cid)
        ov = {x["lang"]: {k: x[k] for k in (*OVERRIDE_FIELDS, "index_flag")} for x in
              con.execute("SELECT * FROM seo_override WHERE entity='content' AND entity_id=?", (r["id"],))}
        return {"id": r["id"], "type": r["type"], "slug": r["slug"], "title": r["title"], "title_ar": r["title_ar"], "title_en": r["title_en"],
                "year": r["year"], "tmdb_id": r["tmdb_id"], "match": r["match"], "frozen": _frozen(con, r["id"]),
                "override": ov, "manual_fields": sorted(seo_db.manual_fields(con, "content", r["id"])),
                "external": seo_db.external(con, "content", r["id"])}
    finally:
        con.close()


def set_override(data_dir, cid, lang, fields):
    """يحفظ تجاوز لغةٍ (عنوان/وصف/مقدمة/علم فهرسة: 0 يخرج الصفحة من الفهرسة، 1 يعيدها لقرار السياسة). قيمةٌ فارغة تمسح الحقل."""
    if lang not in LANGS_OK:
        raise ValueError("لغة غير مدعومة")
    con = seo_db.connect(data_dir)
    try:
        r = _entity(con, cid)
        if _frozen(con, r["id"]):
            raise ValueError("الكيان مجمّد")
        cur = con.execute("SELECT * FROM seo_override WHERE entity='content' AND entity_id=? AND lang=?", (r["id"], lang)).fetchone()
        vals = {k: (cur[k] if cur else None) for k in (*OVERRIDE_FIELDS, "index_flag")}
        for k, v in (fields or {}).items():
            if k == "index_flag":
                vals[k] = None if v in (None, "") else (1 if int(v) else 0)
            elif k in OVERRIDE_FIELDS:
                v = (str(v).strip() if v is not None else "") or None
                if k == "meta_desc" and v:
                    v = v[:160]
                if k == "seo_title" and v:
                    v = v[:120]
                vals[k] = v
            else:
                raise ValueError(f"حقل غير معروف: {k}")
        con.execute("INSERT INTO seo_override(entity, entity_id, lang, seo_title, meta_desc, slug, overview, intro, faq_json, index_flag, canonical, updated_at) "
                    "VALUES ('content', ?, ?, ?, ?, NULL, ?, ?, NULL, ?, ?, ?) ON CONFLICT(entity, entity_id, lang) DO UPDATE SET "
                    "seo_title=excluded.seo_title, meta_desc=excluded.meta_desc, overview=excluded.overview, intro=excluded.intro, "
                    "index_flag=excluded.index_flag, canonical=excluded.canonical, updated_at=excluded.updated_at",
                    (r["id"], lang, vals["seo_title"], vals["meta_desc"], vals["overview"], vals["intro"], vals["index_flag"], vals["canonical"], int(time.time())))
        con.commit()
        return True
    finally:
        con.close()


def set_fields(data_dir, cid, fields):
    """حقولٌ يدوية على الكيان نفسه (مصدرها manual فلا يكتب فوقها البناء ولا TMDB)."""
    bad = [k for k in fields if k not in MANUAL_FIELDS]
    if bad:
        raise ValueError(f"حقل غير مسموح: {bad[0]}")
    con = seo_db.connect(data_dir)
    try:
        r = _entity(con, cid)
        if _frozen(con, r["id"]):
            raise ValueError("الكيان مجمّد")
        ch = seo_db.apply_fields(con, "content", r["id"], dict(fields), seo_db.MANUAL)
        con.commit()
        return ch
    finally:
        con.close()


def set_slug(data_dir, cid, slug):
    """رابطٌ جديد بتحويل 301 من القديم."""
    import re
    slug = (slug or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) or len(slug) > 80:
        raise ValueError("slug لاتيني صغير بشرطات فقط")
    con = seo_db.connect(data_dir)
    try:
        r = _entity(con, cid)
        if _frozen(con, r["id"]):
            raise ValueError("الكيان مجمّد")
        ch = seo_db.change_slug(con, r["id"], slug, "manual", "تغيير يدوي من الإدارة", slug_source="manual")
        con.commit()
        return ch
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def link_tmdb(data_dir, cid, tmdb_id):
    """ربطٌ يدوي بمعرّف TMDB (مُتحقَّق بقرار المدير؛ فريد لكل كيان)."""
    tmdb_id = int(tmdb_id)
    con = seo_db.connect(data_dir)
    try:
        r = _entity(con, cid)
        if _frozen(con, r["id"]):
            raise ValueError("الكيان مجمّد")
        seo_db.set_external(con, "content", r["id"], "tmdb", tmdb_id, verified=True, confidence=1.0, how="manual")
        seo_db.apply_fields(con, "content", r["id"], {"tmdb_id": tmdb_id}, seo_db.MANUAL)
        con.commit()
        return True
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def merge(data_dir, loser, winner, reason="دمج يدوي من الإدارة"):
    """دمج كيانين من النوع نفسه: يبقى الفائز ويُحوَّل رابط الخاسر 301. المجمّد لا يدخل دمجًا."""
    con = seo_db.connect(data_dir)
    try:
        for i in (loser, winner):
            if _frozen(con, i):
                raise ValueError("الكيان مجمّد")
        ok = seo_db.merge_content(con, int(loser), int(winner), reason)
        con.commit()
        return ok
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

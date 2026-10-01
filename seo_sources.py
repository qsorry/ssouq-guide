# -*- coding: utf-8 -*-
"""الإثراء من المصادر (المرحلة 2): واجهة لوحات Xtream (‏get_vod_info · get_series_info) وTMDB — تدريجيًّا، في نافذةٍ ليلية،
بطابورٍ قابل للاستئناف، وكل ردٍّ في ‏api_cache فلا يُعاد طلبه ما دام صالحًا، وبتباعدٍ للمحاولات.

الأولوية في الكتابة (‏seo_db.apply_fields): يدوي > TMDB > Xtream > الفهرس. والهوية: معرّف TMDB من اللوحة **مرشَّحٌ**
لا يُعتمد حتى يتحقّق (‏seo_match.verify_tmdb: النوع والسنة واسمٌ من الأسماء)؛ وبحث TMDB يقبل المطابقة القوية وحدها، وما
دونها بندُ مراجعة (‏tmdb_weak · tmdb_ambiguous) لا تخمين. والتصنيف (تركي · أنمي بنوعه · البلد · اللغة · النوع · السنة ·
الاستوديو) من TMDB، واسم القسم قرينةٌ (‏hint) من ‏group_rule لا تُدخل الهب.

ترتيب الإثراء لكل عمل: xtream (إن كان للسيرفر رابط) ← tmdb ← tmdb_seasons (للمسلسلات). والأولوية: التركي والأنمي
بقرائن الأقسام أولًا، ثم الأحدث إضافة، ثم الباقي — ولا يُفترض اكتمال شيءٍ في ليلةٍ واحدة.

    python seo_sources.py probe          # فحصٌ أولي: ماذا تعطي كل لوحة فعلًا (20 فيلمًا و20 مسلسلًا)
    python seo_sources.py run --limit=50 --force   # دفعةٌ الآن خارج النافذة
    python seo_sources.py queue
"""
import json
import os
import re
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import content as C
import crypto_store
import seo_db
import seo_match as M
import seo_search

TMDB_API = os.environ.get("TMDB_API", "https://api.themoviedb.org/3").rstrip("/")
TMDB_IMG = "https://image.tmdb.org/t/p/"
TIMEOUT = 20
UA = "ssouq-guide/2.0 (+https://guide.ssouq.com/)"

# أنواع TMDB بالعربية (تُزرع في taxonomy عند أول استعمال)
GENRES_AR = {28: "أكشن", 12: "مغامرة", 16: "رسوم متحركة", 35: "كوميديا", 80: "جريمة", 99: "وثائقي", 18: "دراما", 10751: "عائلي",
             14: "فانتازيا", 36: "تاريخي", 27: "رعب", 10402: "موسيقى", 9648: "غموض", 10749: "رومانسي", 878: "خيال علمي",
             10770: "فيلم تلفزيوني", 53: "إثارة", 10752: "حرب", 37: "غربي", 10759: "أكشن ومغامرة", 10762: "أطفال",
             10763: "أخبار", 10764: "تلفزيون الواقع", 10765: "خيال علمي وفانتازيا", 10766: "مسلسل درامي", 10767: "حواري",
             10768: "حرب وسياسة"}
COUNTRIES_AR = {"TR": "تركيا", "US": "الولايات المتحدة", "GB": "بريطانيا", "KR": "كوريا الجنوبية", "JP": "اليابان", "IN": "الهند",
                "EG": "مصر", "SA": "السعودية", "SY": "سوريا", "LB": "لبنان", "KW": "الكويت", "AE": "الإمارات", "FR": "فرنسا",
                "ES": "إسبانيا", "DE": "ألمانيا", "IT": "إيطاليا", "CN": "الصين", "CA": "كندا", "MX": "المكسيك", "BR": "البرازيل"}
LANGS_AR = {"ar": "العربية", "en": "الإنجليزية", "tr": "التركية", "ko": "الكورية", "ja": "اليابانية", "hi": "الهندية", "es": "الإسبانية",
            "fr": "الفرنسية", "de": "الألمانية", "it": "الإيطالية", "zh": "الصينية", "pt": "البرتغالية"}
ONGOING = ("Returning Series", "In Production", "Planned", "Pilot")

# قواعد الأقسام الافتراضية (قرائن): تُزرع في group_rule مرةً ويعدّلها المدير
GROUP_RULES = [
    (r"turk|ترك|\[tr\]", {"country": "TR", "hub": "turkish"}),
    (r"anime|انمي|أنمي|انيم", {"hub": "anime"}),
    (r"korea|كور", {"country": "KR"}),
    (r"india|hindi|هند|بوليوود|bollywood", {"country": "IN"}),
    (r"egypt|مصر", {"country": "EG"}),
    (r"syria|سور", {"country": "SY"}),
    (r"gulf|خليج", {"country": "SA"}),
    (r"arab|عرب", {"language": "ar"}),
]

_lock = threading.Lock()
_last_call = {}                     # المصدر ← وقت آخر طلب (تحديد السرعة)
_metrics = {}                       # المصدر ← {n, seconds, max, errors, cache_hits} — أداء الواجهات لتقرير العيّنة


def _metric(source, seconds=None, status=None, cache_hit=False):
    with _lock:
        m = _metrics.setdefault(source, {"n": 0, "seconds": 0.0, "max": 0.0, "errors": 0, "cache_hits": 0})
        if cache_hit:
            m["cache_hits"] += 1
            return
        m["n"] += 1
        m["seconds"] += seconds
        m["max"] = max(m["max"], seconds)
        if status and status >= 400:
            m["errors"] += 1


def metrics():
    return {k: {**v, "avg_ms": round(1000 * v["seconds"] / v["n"]) if v["n"] else None} for k, v in _metrics.items()}
_running = {}
_state = {}


class Skip(Exception):
    """لا يمكن الإثراء الآن (لا مفتاح، لا رابط سيرفر): يُؤجَّل بلا عدّه فشلًا."""


# ================= الإعداد =================
def tmdb_key(con, data_dir):
    k = os.environ.get("TMDB_API_KEY", "").strip()
    if k:
        return k
    enc = seo_db.settings(con).get("tmdb_key") or ""
    try:
        return crypto_store.decrypt(enc, data_dir).strip() if enc else ""
    except Exception:  # noqa: BLE001
        return ""


def set_tmdb_key(con, data_dir, key):
    key = str(key or "").strip()
    if key and not re.fullmatch(r"[A-Za-z0-9._\-]{6,512}", key):
        raise ValueError("مفتاح TMDB غير صالح")
    seo_db.set_setting(con, "tmdb_key", crypto_store.encrypt(key, data_dir) if key else "")


def window_open(st, now=None):
    """هل نحن داخل نافذة الإثراء (بتوقيت السعودية افتراضًا)؟"""
    w = st.get("enrich_window") or {}
    try:
        off = float(w.get("tz_offset", 3)) * 3600
        t = time.gmtime((now or time.time()) + off)
        cur = t.tm_hour * 60 + t.tm_min
        h1, m1 = map(int, str(w.get("start", "02:00")).split(":"))
        h2, m2 = map(int, str(w.get("end", "06:00")).split(":"))
    except (TypeError, ValueError):
        return False
    a, b = h1 * 60 + m1, h2 * 60 + m2
    return a <= cur < b if a <= b else (cur >= a or cur < b)


# ================= HTTP + كاش + سرعة =================
def _wait(source, rps):
    with _lock:
        gap = 1.0 / max(float(rps or 1), 0.1)
        delay = _last_call.get(source, 0) + gap - time.time()
        if delay > 0:
            time.sleep(delay)
        _last_call[source] = time.time()


def _http(url, headers=None, timeout=TIMEOUT):
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})})
    try:
        with urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:2000]
    except (URLError, OSError, ValueError) as e:
        raise ConnectionError(str(e)[:200])


def get_json(con, source, url, cache_key, st, rps, headers=None, now=None, write=True):
    """ردّ JSON من الكاش إن كان صالحًا، وإلا من الشبكة (بسرعة المصدر) ثم يُخزَّن (‏write=False: قراءةٌ بلا كتابة — للفحص الأولي) —
    الناجح والفارغ (404) طويلًا، والخطأ قصيرًا."""
    now = now or int(time.time())
    ttl = st.get("cache_ttl") or {}
    r = con.execute("SELECT body, status, at FROM api_cache WHERE key=?", (cache_key,)).fetchone()
    if r:
        life = ttl.get("ok", 2592000) if r["status"] == 200 else ttl.get("miss", 2592000) if r["status"] == 404 else ttl.get("error", 3600)
        if r["at"] + life > now:
            _metric(source.split(":")[0], cache_hit=True)
            return r["status"], (json.loads(r["body"]) if r["body"] else None), True
    _wait(source, rps)
    t0 = time.time()
    status, text = _http(url, headers)
    _metric(source.split(":")[0], time.time() - t0, status)
    body = None
    if status == 200:
        try:
            body = json.loads(text)
        except ValueError:
            status = 502
    if status == 429:                          # تجاوزنا السرعة: لا يُخزَّن، ويُعاد لاحقًا
        raise ConnectionError("rate limited (429)")
    if not write:
        return status, body, False
    con.execute("INSERT INTO api_cache(key, body, status, at) VALUES (?,?,?,?) ON CONFLICT(key) DO UPDATE SET body=excluded.body, "
                "status=excluded.status, at=excluded.at", (cache_key, json.dumps(body, ensure_ascii=False) if body is not None else None, status, now))
    return status, body, False


# ================= TMDB =================
def _tmdb(con, key, path, st, **params):
    q = urlencode({k: v for k, v in params.items() if v not in (None, "")})
    url = f"{TMDB_API}{path}?{q}&api_key={quote(key)}"
    status, body, _ = get_json(con, "tmdb", url, f"tmdb:{path}?{q}", st, st.get("tmdb_rps", 4))
    if status == 401:
        raise Skip("مفتاح TMDB مرفوض")
    if status >= 500:
        raise ConnectionError(f"TMDB {status}")
    return body if status == 200 else None


def tmdb_search(con, key, typ, query, st, year=None, lang="en-US"):
    kind = "movie" if typ == "movie" else "tv"
    params = {"query": query[:100], "language": lang, "include_adult": "false"}
    if year:
        params["year" if kind == "movie" else "first_air_date_year"] = year
    d = _tmdb(con, key, f"/search/{kind}", st, **params)
    out = []
    for r in (d or {}).get("results") or []:
        date = r.get("release_date") or r.get("first_air_date") or ""
        out.append({"id": r.get("id"), "type": typ, "title": r.get("title") or r.get("name") or "",
                    "original_title": r.get("original_title") or r.get("original_name") or "",
                    "year": int(date[:4]) if date[:4].isdigit() else 0, "popularity": r.get("popularity") or 0})
    return out


def tmdb_details(con, key, typ, tid, st):
    kind = "movie" if typ == "movie" else "tv"
    app = "credits,keywords,alternative_titles,translations,external_ids,videos" if kind == "movie" else \
          "aggregate_credits,keywords,alternative_titles,translations,external_ids,videos"
    return _tmdb(con, key, f"/{kind}/{int(tid)}", st, language="en-US", append_to_response=app)


def tmdb_season(con, key, tid, n, st):
    return _tmdb(con, key, f"/tv/{int(tid)}/season/{int(n)}", st, language="en-US", append_to_response="translations")


def _cand(d, typ):
    date = d.get("release_date") or d.get("first_air_date") or ""
    alts = [x.get("title") for x in ((d.get("alternative_titles") or {}).get("titles") or (d.get("alternative_titles") or {}).get("results") or []) if x.get("title")]
    for t in (d.get("translations") or {}).get("translations") or []:
        v = (t.get("data") or {}).get("title") or (t.get("data") or {}).get("name")
        if v:
            alts.append(v)
    return {"id": d.get("id"), "type": typ, "title": d.get("title") or d.get("name") or "",
            "original_title": d.get("original_title") or d.get("original_name") or "",
            "year": int(date[:4]) if date[:4].isdigit() else 0, "aliases": alts}


def _entity(con, cid):
    row = con.execute("SELECT * FROM content WHERE id=?", (cid,)).fetchone()
    if not row:
        return None
    e = dict(row)
    e["aliases"] = [r[0] for r in con.execute("SELECT alias FROM content_alias WHERE content_id=?", (cid,))]
    return e


def _strong(cand, e):
    """مطابقة قوية: اسمٌ مطبَّق حرفيًّا مع سنةٍ متفقة (أو بلا سنة عندنا)، أو اسمٌ مطبَّق + ملصقٌ/معرّفٌ من اللوحة."""
    mine = {M.norm(x) for x in [e.get("title"), e.get("title_en"), e.get("original_title")] + e["aliases"] if x}
    theirs = {M.norm(x) for x in [cand.get("title"), cand.get("original_title")] + list(cand.get("aliases") or []) if x}
    exact = bool(mine & theirs)
    year_ok = not e.get("year") or not cand.get("year") or abs(e["year"] - cand["year"]) <= 1
    return exact and year_ok and (bool(e.get("year")) or len(mine & theirs) > 0)


def resolve_tmdb(con, data_dir, cid, st, now=None):
    """يحدّد معرّف TMDB للعمل ← ("ok", id) · ("weak"|"ambiguous", [مرشّحون]) · ("miss", []). المرشّح من اللوحة أولًا."""
    key = tmdb_key(con, data_dir)
    if not key:
        raise Skip("لا مفتاح TMDB")
    e = _entity(con, cid)
    typ = e["type"]
    seen, verified = set(), []

    def consider(tid, how):
        if not tid or tid in seen:
            return
        seen.add(tid)
        d = tmdb_details(con, key, typ, tid, st)
        if not d:
            return
        cand = _cand(d, typ)
        ok, why = M.verify_tmdb(cand, e, st)
        if ok:
            verified.append((cand, d, how, _strong(cand, e)))
    ext = seo_db.external(con, "content", cid).get("tmdb")
    if ext and not ext["verified"]:
        consider(int(ext["external_id"]), "xtream")
    if verified and verified[0][3]:
        return "ok", verified[0]
    latin = [a for a in [e.get("title")] + e["aliases"] if a and re.search(r"[A-Za-z]", a)]
    arabic = [a for a in [e.get("title")] + e["aliases"] if a and re.search(r"[؀-ۿ]", a)]
    queries = [(a, "en-US") for a in dict.fromkeys(latin)][:2] + [(a, "ar-SA") for a in dict.fromkeys(arabic)][:2]
    for q, lang in queries:
        q = M.split_version(q, st)[0]
        for r in tmdb_search(con, key, typ, q, st, e.get("year") or None, lang)[:3]:
            consider(r["id"], f"search:{lang}")
        if verified and any(v[3] for v in verified):
            break
    strong = [v for v in verified if v[3]]
    ids = {v[0]["id"] for v in strong}
    if len(ids) == 1:
        return "ok", strong[0]
    if len(ids) > 1:
        return "ambiguous", [v[0] for v in strong]
    if verified:
        return "weak", [v[0] for v in verified]
    return "miss", []


def _img(path, size):
    return f"{TMDB_IMG}{size}{path}" if path else None


def _slug_for(con, table, name):
    return M.unique_slug(lambda s: con.execute(f"SELECT 1 FROM {table} WHERE slug=?", (s,)).fetchone() is not None, name)


def _person(con, p, now):
    """صفّ الشخص بمعرّف TMDB (يُنشأ مرةً)."""
    r = con.execute("SELECT entity_id FROM external_id WHERE entity='person' AND source='tmdb' AND external_id=?", (str(p["id"]),)).fetchone()
    if r:
        return r["entity_id"]
    name = p.get("name") or p.get("original_name") or ""
    if not name:
        return None
    cur = con.execute("INSERT INTO person(slug, name, name_en, original_name, photo, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                      (_slug_for(con, "person", name), name, name, p.get("original_name"), _img(p.get("profile_path"), "w185"), now, now))
    seo_db.set_external(con, "person", cur.lastrowid, "tmdb", p["id"], verified=True, confidence=1, how="tmdb", now=now)
    return cur.lastrowid


def _company(con, c, kind, now):
    r = con.execute("SELECT entity_id FROM external_id WHERE entity='company' AND source='tmdb' AND external_id=?", (str(c["id"]),)).fetchone()
    if r:
        return r["entity_id"]
    name = c.get("name") or ""
    if not name:
        return None
    cur = con.execute("INSERT INTO company(slug, name, kind, logo, country, created_at) VALUES (?,?,?,?,?,?)",
                      (_slug_for(con, "company", name), name, kind, _img(c.get("logo_path"), "w185"), c.get("origin_country"), now))
    con.execute("INSERT INTO external_id(entity, entity_id, source, external_id, verified, confidence, how, at) VALUES ('company',?,?,?,1,1,'tmdb',?)",
                (cur.lastrowid, "tmdb", str(c["id"]), now))
    return cur.lastrowid


def apply_tmdb(con, data_dir, cid, d, st, now=None):
    """يكتب تفاصيل TMDB في الكيان (بأسبقية المصادر)، والأسماء البديلة، والتصنيف (الأنمي بنوعه، التركي، البلد، اللغة،
    النوع، السنة، الاستوديو)، والأشخاص، والمعرّفات؛ ويرقّي الرابط المنقحر إلى الاسم الإنجليزي بتحويل 301؛ ويضع
    المسلسل في طابور مواسمه."""
    now = now or int(time.time())
    e = _entity(con, cid)
    typ = e["type"]
    date = d.get("release_date") or d.get("first_air_date") or ""
    tr_ar = next(((t.get("data") or {}) for t in (d.get("translations") or {}).get("translations") or [] if t.get("iso_639_1") == "ar"), {})
    title_en = d.get("title") or d.get("name") or ""
    title_ar = tr_ar.get("title") or tr_ar.get("name") or ""
    genres = [g for g in d.get("genres") or [] if g.get("id")]
    gids = {g["id"] for g in genres}
    lang, countries = d.get("original_language") or "", list(d.get("origin_country") or [])
    for pc in d.get("production_countries") or []:
        if pc.get("iso_3166_1") and pc["iso_3166_1"] not in countries:
            countries.append(pc["iso_3166_1"])
    kw = {k.get("id") for k in ((d.get("keywords") or {}).get("keywords") or (d.get("keywords") or {}).get("results") or [])}
    anime_kind = ""
    if 16 in gids:
        anime_kind = (st.get("anime_langs") or {}).get(lang, "")
        for c in countries:
            anime_kind = anime_kind or (st.get("anime_countries") or {}).get(c, "")
        if not anime_kind and kw & set(st.get("anime_keyword_ids") or []):
            anime_kind = "japanese"
    status = d.get("status") or ""
    trailer = next((v.get("key") for v in (d.get("videos") or {}).get("results") or [] if v.get("site") == "YouTube" and v.get("type") == "Trailer"), None)
    runtime = d.get("runtime") or ((d.get("episode_run_time") or [None])[0])
    fields = {
        "tmdb_id": d.get("id"), "match": "tmdb", "title_en": title_en or None, "title_ar": title_ar or None,
        "original_title": d.get("original_title") or d.get("original_name") or None,
        "overview_en": d.get("overview") or None, "overview_ar": tr_ar.get("overview") or None,
        "release_date": date or None, "year": int(date[:4]) if date[:4].isdigit() else None,
        "runtime": int(runtime) if runtime else None, "status": status or None, "tmdb_type": d.get("type") or None,
        "rating": round(float(d.get("vote_average") or 0), 1) or None, "votes": d.get("vote_count") or None,
        "popularity": d.get("popularity") or None, "last_air_date": d.get("last_air_date") or None,
        "poster": _img(d.get("poster_path"), "w500"), "backdrop": _img(d.get("backdrop_path"), "w780"), "trailer_yt": trailer,
        "original_language": lang or None, "origin_country_json": json.dumps(countries) if countries else None,
        "genres_json": json.dumps([g["name"] for g in genres], ensure_ascii=False) if genres else None,
        "format": ("anime_series" if typ == "series" else "anime_movie") if anime_kind else "", "anime_kind": anime_kind or None,
        "imdb_id": (d.get("external_ids") or {}).get("imdb_id") or d.get("imdb_id") or None,
    }
    # ‏title (اسم القوائم الذي يعرفه الجمهور: «طبيعة الحب») لا يُمسّ؛ TMDB يعطي title_ar/title_en جانبه
    seo_db.apply_fields(con, "content", cid, fields, "tmdb", now=now)
    for lang_, tt, ov in (("en", title_en, d.get("overview")), ("ar", title_ar, tr_ar.get("overview"))):
        seo_db.set_text(con, "content", cid, lang_, "title", tt, "tmdb", now)          # نصوص اللغات (content_text) — العربية والإنجليزية الآن
        seo_db.set_text(con, "content", cid, lang_, "overview", ov, "tmdb", now)
    seo_db.set_external(con, "content", cid, "tmdb", d["id"], verified=True, confidence=1, how="verified", now=now)
    if fields["imdb_id"]:
        seo_db.set_external(con, "content", cid, "imdb", fields["imdb_id"], verified=True, confidence=1, how="tmdb", now=now)
    # الأسماء البديلة
    rows = [(title_en, "title", "en"), (title_ar, "translation", "ar"), (fields["original_title"], "original", lang)]
    for x in ((d.get("alternative_titles") or {}).get("titles") or (d.get("alternative_titles") or {}).get("results") or []):
        rows.append((x.get("title"), "alternative", (x.get("iso_3166_1") or "").lower()))
    con.executemany("INSERT OR IGNORE INTO content_alias(content_id, alias, alias_norm, lang, source, service_key, at, kind, phonetic) "
                    "VALUES (?,?,?,?,'tmdb',NULL,?,?,?)",
                    [(cid, a, M.norm(a), lg or None, now, k, seo_search.phonetic(a)) for a, k, lg in rows if a and M.norm(a)])
    # التصنيف
    con.execute("DELETE FROM content_taxonomy WHERE content_id=? AND source='tmdb'", (cid,))
    for g in genres:
        tid = seo_db.taxonomy_id(con, "genre", g["id"], M.slugify(g["name"]), GENRES_AR.get(g["id"], g["name"]), g["name"], now)
        seo_db.set_membership(con, cid, tid, "tmdb", 1, now)
        con.execute("INSERT OR IGNORE INTO genre_map(raw_norm, taxonomy_id, source) VALUES (?,?,'tmdb')", (M.norm(g["name"]), tid))
    for c in countries:
        seo_db.set_membership(con, cid, seo_db.taxonomy_id(con, "country", c, c.lower(), COUNTRIES_AR.get(c, c), c, now), "tmdb", 1, now)
    if lang:
        seo_db.set_membership(con, cid, seo_db.taxonomy_id(con, "language", lang, lang, LANGS_AR.get(lang, lang), lang, now), "tmdb", 1, now)
    if fields["year"]:
        seo_db.set_membership(con, cid, seo_db.taxonomy_id(con, "year", fields["year"], str(fields["year"]), str(fields["year"]), str(fields["year"]), now), "tmdb", 1, now)
    for hub, cc in (st.get("hub_countries") or {}).items():
        if set(cc) & set(countries):
            seo_db.set_membership(con, cid, seo_db.taxonomy_id(con, "hub", hub, hub, None, None, now), "tmdb", 1, now)
    if anime_kind:
        seo_db.set_membership(con, cid, seo_db.taxonomy_id(con, "hub", "anime", "anime", "أنمي", "Anime", now), "tmdb", 1, now)
        seo_db.set_membership(con, cid, seo_db.taxonomy_id(con, "anime_kind", anime_kind, anime_kind, None, anime_kind.title(), now), "tmdb", 1, now)
    # قرائن الأقسام مقابل TMDB — متحفّظًا: اتفاقٌ = confirmed؛ اختلافٌ = **مراجعة** (taxonomy_mismatch) ولا يُعتمد TMDB تلقائيًّا في
    # البُعد المختلَف عليه (عضويّاته فيه تُعلَّم disputed فلا تدخل الهب ولا الصفحات حتى يحسمها المدير)؛ ونقص TMDB = unconfirmed
    hints = {f"{r['kind']}:{r['key']}" for r in con.execute("SELECT t.kind, t.key FROM content_taxonomy ct JOIN taxonomy t ON t.id=ct.taxonomy_id WHERE ct.content_id=? AND ct.source='hint'", (cid,))}
    confirmed = {f"{r['kind']}:{r['key']}" for r in con.execute("SELECT t.kind, t.key FROM content_taxonomy ct JOIN taxonomy t ON t.id=ct.taxonomy_id WHERE ct.content_id=? AND ct.source='tmdb'", (cid,))}
    diff = {h for h in hints if h.startswith(("hub:", "country:")) and h not in confirmed}
    if diff:
        prefixes = set()
        for h in diff:
            prefixes.update(("hub:anime", "anime_kind:") if h == "hub:anime" else ("hub:", "country:"))
        disputed = sorted(x for x in confirmed if any(x.startswith(pfx) for pfx in prefixes))
        for x in disputed:
            kind, key = x.split(":", 1)
            con.execute("UPDATE content_taxonomy SET source='disputed' WHERE content_id=? AND source='tmdb' AND taxonomy_id=(SELECT id FROM taxonomy WHERE kind=? AND key=?)",
                        (cid, kind, key))
        if "hub:anime" in diff or "hub:anime" in disputed:
            seo_db.apply_fields(con, "content", cid, {"format": "", "anime_kind": None}, "tmdb", now=now)   # لا صفة أنمي قبل الحسم
        _review(con, "taxonomy_mismatch", cid, e["title"], {"hints": sorted(diff), "tmdb": sorted(x for x in confirmed if x.startswith(("hub:", "country:"))),
                                                           "disputed": disputed, "decision": "review", "confidence": "low"}, now)
    else:
        con.execute("UPDATE review SET status='stale', updated_at=? WHERE key=? AND status='open'", (now, f"taxonomy_mismatch:{cid}"))
    con.execute("UPDATE review SET status='stale', updated_at=? WHERE key=? AND status='open'", (now, f"taxonomy_unconfirmed:{cid}"))
    # الأشخاص والشركات
    con.execute("DELETE FROM content_person WHERE content_id=? AND source IN ('tmdb','xtream')", (cid,))
    credits = d.get("credits") or d.get("aggregate_credits") or {}
    for i, p in enumerate((credits.get("cast") or [])[:15]):
        pid = _person(con, p, now)
        if pid:
            ch = p.get("character") or ((p.get("roles") or [{}])[0]).get("character") or ""
            role = "voice" if anime_kind or "(voice)" in ch.lower() else "actor"
            con.execute("INSERT OR IGNORE INTO content_person(content_id, person_id, role, character, ord, source) VALUES (?,?,?,?,?,'tmdb')",
                        (cid, pid, role, ch[:120] or None, i))
    jobs = {"Director": "director", "Writer": "writer", "Screenplay": "writer", "Story": "writer", "Novel": "writer", "Series Director": "director"}
    for p in credits.get("crew") or []:
        job = p.get("job") or ((p.get("jobs") or [{}])[0]).get("job")
        role = jobs.get(job)
        if role:
            pid = _person(con, p, now)
            if pid:
                con.execute("INSERT OR IGNORE INTO content_person(content_id, person_id, role, character, ord, source) VALUES (?,?,?,NULL,0,'tmdb')", (cid, pid, role))
    for p in d.get("created_by") or []:
        pid = _person(con, p, now)
        if pid:
            con.execute("INSERT OR IGNORE INTO content_person(content_id, person_id, role, character, ord, source) VALUES (?,?,'creator',NULL,0,'tmdb')", (cid, pid))
    con.execute("DELETE FROM content_company WHERE content_id=? AND source='tmdb'", (cid,))
    for c in (d.get("production_companies") or [])[:5]:
        coid = _company(con, c, "studio", now)
        if coid:
            con.execute("INSERT OR IGNORE INTO content_company(content_id, company_id, role, source) VALUES (?,?,'studio','tmdb')", (cid, coid))
            if anime_kind:
                seo_db.set_membership(con, cid, seo_db.taxonomy_id(con, "studio", f"tmdb:{c['id']}", M.slugify(c["name"]), c["name"], c["name"], now), "tmdb", 1, now)
    for c in (d.get("networks") or [])[:3]:
        coid = _company(con, c, "network", now)
        if coid:
            con.execute("INSERT OR IGNORE INTO content_company(content_id, company_id, role, source) VALUES (?,?,'network','tmdb')", (cid, coid))
    # الرابط: منقحرٌ ← الاسم الإنجليزي (301)
    row = con.execute("SELECT slug, slug_source FROM content WHERE id=?", (cid,)).fetchone()
    name, src = M.slug_source({"title_en": title_en, "original_title": fields["original_title"], "title": e["title"]})
    if row["slug_source"] == "translit" and src in ("en", "original"):
        new = M.unique_slug(lambda s: con.execute("SELECT 1 FROM content WHERE slug=? AND id!=?", (s, cid)).fetchone() is not None, name, fields["year"] or 0)
        seo_db.change_slug(con, cid, new, source="tmdb", reason="tmdb title", now=now, slug_source=src)
    if typ == "series":
        seasons = [s for s in d.get("seasons") or [] if s.get("season_number") is not None]
        for s in seasons:
            con.execute("INSERT INTO season(content_id, number, name, poster, air_date, episode_count, updated_at) VALUES (?,?,?,?,?,?,?) "
                        "ON CONFLICT(content_id, number) DO UPDATE SET name=COALESCE(excluded.name, season.name), poster=COALESCE(excluded.poster, season.poster), "
                        "air_date=COALESCE(excluded.air_date, season.air_date), episode_count=MAX(season.episode_count, excluded.episode_count), updated_at=excluded.updated_at",
                        (cid, s["season_number"], s.get("name"), _img(s.get("poster_path"), "w342"), s.get("air_date"), s.get("episode_count") or 0, now))
        enqueue(con, cid, ["tmdb_seasons"], 5, now)
    return fields


def apply_seasons(con, data_dir, cid, st, now=None):
    """حلقات كل موسم من TMDB: عنوانٌ وملخص (بالإنجليزية، والعربية من الترجمات) وتاريخٌ ومدة وصورة."""
    now = now or int(time.time())
    key = tmdb_key(con, data_dir)
    if not key:
        raise Skip("لا مفتاح TMDB")
    row = con.execute("SELECT tmdb_id FROM content WHERE id=?", (cid,)).fetchone()
    if not row or not row["tmdb_id"]:
        raise Skip("لا معرّف TMDB")
    n = 0
    for s in con.execute("SELECT number FROM season WHERE content_id=? ORDER BY number", (cid,)).fetchall():
        d = tmdb_season(con, key, row["tmdb_id"], s["number"], st)
        if not d:
            continue
        tr = next(((t.get("data") or {}) for t in (d.get("translations") or {}).get("translations") or [] if t.get("iso_639_1") == "ar"), {})
        con.execute("UPDATE season SET overview_en=COALESCE(?, overview_en), overview_ar=COALESCE(?, overview_ar), updated_at=? WHERE content_id=? AND number=?",
                    (d.get("overview") or None, tr.get("overview") or None, now, cid, s["number"]))
        for ep in d.get("episodes") or []:
            con.execute("INSERT INTO episode(content_id, season, number, title_en, overview_en, air_date, runtime, still, updated_at) VALUES (?,?,?,?,?,?,?,?,?) "
                        "ON CONFLICT(content_id, season, number) DO UPDATE SET title_en=COALESCE(excluded.title_en, episode.title_en), "
                        "overview_en=COALESCE(excluded.overview_en, episode.overview_en), air_date=COALESCE(excluded.air_date, episode.air_date), "
                        "runtime=COALESCE(excluded.runtime, episode.runtime), still=COALESCE(excluded.still, episode.still), updated_at=excluded.updated_at",
                        (cid, s["number"], ep.get("episode_number"), ep.get("name") or None, ep.get("overview") or None, ep.get("air_date") or None,
                         ep.get("runtime") or None, _img(ep.get("still_path"), "w300"), now))
            n += 1
    return n


# ================= Xtream =================
def _creds(data_dir, service_key):
    url = C.url_of(data_dir, service_key)
    return C.xtream_of(url) if url else None


def _xt_json(con, xt, action, st, write=True, **params):
    base, user, pw = xt
    q = urlencode({"username": user, "password": pw, "action": action, **params})
    url = f"{base}/player_api.php?{q}"
    status, body, _ = get_json(con, f"xtream:{base}", url, f"xtream:{base}:{action}:{urlencode(params)}", st, st.get("xtream_rps", 1),
                               headers={"User-Agent": C.UA}, write=write)
    if status >= 500:
        raise ConnectionError(f"xtream {status}")
    return body if status == 200 and isinstance(body, dict) else None


def _series_map(con, xt, st, write=True):
    """اسمٌ مطبَّع ← series_id من قائمة get_series (مرةً في اليوم في الكاش) — لرابطٍ بلا series_id."""
    base, user, pw = xt
    q = urlencode({"username": user, "password": pw, "action": "get_series"})
    status, body, _ = get_json(con, f"xtream:{base}", f"{base}/player_api.php?{q}", st, st.get("xtream_rps", 1), headers={"User-Agent": C.UA}, write=write)
    out = {}
    for o in body or [] if isinstance(body, list) else []:
        nm = M.norm(C._split_year(C._dequal(C._clean(str(o.get("name") or ""))))[0])
        if nm and o.get("series_id"):
            out.setdefault(nm, int(o["series_id"]))
    return out


def _people_xtream(con, cid, info, now):
    if con.execute("SELECT 1 FROM content_person WHERE content_id=? AND source='tmdb'", (cid,)).fetchone():
        return
    con.execute("DELETE FROM content_person WHERE content_id=? AND source='xtream'", (cid,))
    for role, raw in (("actor", info.get("cast") or info.get("actors") or ""), ("director", info.get("director") or "")):
        for i, name in enumerate([x.strip() for x in re.split(r"[,،/]", str(raw)) if x.strip()][:12]):
            r = con.execute("SELECT id FROM person WHERE name=?", (name,)).fetchone()
            pid = r["id"] if r else con.execute("INSERT INTO person(slug, name, created_at, updated_at) VALUES (?,?,?,?)",
                                                (_slug_for(con, "person", name), name, now, now)).lastrowid
            con.execute("INSERT OR IGNORE INTO content_person(content_id, person_id, role, character, ord, source) VALUES (?,?,?,NULL,?,'xtream')", (cid, pid, role, i))


def apply_xtream(con, data_dir, cid, st, now=None):
    """لكل سيرفرٍ فيه العمل وله رابط: تفاصيل اللوحة ← مرشّح TMDB، وحقولٌ بمصدر xtream، وقرينة بلد، وأشخاص إن لم يكن
    TMDB، وحلقات المسلسل بعناوينها إن أعطتها ← عدد السيرفرات التي أجابت."""
    now = now or int(time.time())
    e = _entity(con, cid)
    links = con.execute("SELECT * FROM content_service WHERE content_id=? AND present=1", (cid,)).fetchall()
    done = 0
    for ln in links:
        xt = _creds(data_dir, ln["service_key"])
        if not xt:
            continue
        if e["type"] == "movie":
            d = _xt_json(con, xt, "get_vod_info", st, vod_id=ln["stream_id"]) if ln["stream_id"] else None
        else:
            sid = ln["series_id"] or _series_map(con, xt, st).get(M.norm(ln["name"]))
            d = _xt_json(con, xt, "get_series_info", st, series_id=sid) if sid else None
        info = (d or {}).get("info") or {}
        if not info:
            continue
        done += 1
        tid = info.get("tmdb_id") or info.get("tmdb")
        if tid and str(tid).isdigit() and int(tid) and not seo_db.external(con, "content", cid).get("tmdb", {}).get("verified"):
            seo_db.set_external(con, "content", cid, "tmdb", int(tid), verified=False, confidence=0.5, how=f"xtream:{ln['service_key']}", now=now)
        date = str(info.get("releasedate") or info.get("releaseDate") or info.get("release_date") or "")[:10]
        secs = info.get("duration_secs")
        fields = {"overview": info.get("plot") or info.get("description") or None, "release_date": date or None,
                  "year": int(date[:4]) if date[:4].isdigit() else None,
                  "runtime": int(int(secs) // 60) if str(secs or "").isdigit() and int(secs) else None,
                  "backdrop": (info.get("backdrop_path") or [None])[0] if isinstance(info.get("backdrop_path"), list) else info.get("backdrop_path") or None,
                  "trailer_yt": (info.get("youtube_trailer") or "")[-11:] or None, "original_title": info.get("o_name") or None}
        seo_db.apply_fields(con, "content", cid, fields, "xtream", ln["service_key"], now=now)
        for c in [x.strip() for x in str(info.get("country") or "").split(",") if x.strip()][:3]:
            code = next((k for k, v in COUNTRIES_AR.items() if c.upper() == k or c.lower() in (v.lower(),)), None) or (c.upper() if len(c) == 2 else "")
            if code:
                seo_db.set_membership(con, cid, seo_db.taxonomy_id(con, "country", code, code.lower(), COUNTRIES_AR.get(code, code), code, now), "hint", 0.5, now)
        _people_xtream(con, cid, info, now)
        eps = (d or {}).get("episodes") or {}
        if isinstance(eps, dict):
            for sn, lst in eps.items():
                for ep in lst if isinstance(lst, list) else []:
                    inf = ep.get("info") or {}
                    num = ep.get("episode_num")
                    if not str(num or "").isdigit():
                        continue
                    con.execute("INSERT INTO episode(content_id, season, number, title_en, overview_en, air_date, runtime, still, updated_at) VALUES (?,?,?,?,?,?,?,?,?) "
                                "ON CONFLICT(content_id, season, number) DO UPDATE SET title_en=COALESCE(episode.title_en, excluded.title_en), "
                                "overview_en=COALESCE(episode.overview_en, excluded.overview_en), air_date=COALESCE(episode.air_date, excluded.air_date), "
                                "runtime=COALESCE(episode.runtime, excluded.runtime), still=COALESCE(episode.still, excluded.still)",
                                (cid, int(sn) if str(sn).isdigit() else 0, int(num), (ep.get("title") or None),
                                 inf.get("plot") or None, (str(inf.get("releasedate") or "")[:10]) or None,
                                 int(int(inf["duration_secs"]) // 60) if str(inf.get("duration_secs") or "").isdigit() and int(inf["duration_secs"]) else None,
                                 inf.get("movie_image") or None, now))
    return done


# ================= قرائن الأقسام =================
def seed_rules(con, now=None):
    if con.execute("SELECT 1 FROM group_rule").fetchone():
        return
    con.executemany("INSERT INTO group_rule(pattern, hint_json, enabled, note) VALUES (?,?,1,?)",
                    [(p, json.dumps(h), "افتراضي") for p, h in GROUP_RULES])


def rules(con):
    out = []
    for r in con.execute("SELECT pattern, hint_json FROM group_rule WHERE enabled=1"):
        try:
            out.append((re.compile(r["pattern"], re.I), json.loads(r["hint_json"])))
        except (re.error, ValueError):
            continue
    return out


def apply_hints(con, cid, groups, rls, st, now=None):
    """أسماء أقسام العمل في السيرفرات ← قرائن (hint) في content_taxonomy وأولويةٌ في الطابور — لا تُدخل الهب."""
    now = now or int(time.time())
    hints = {}
    for g in groups:
        for rx, h in rls:
            if rx.search(g):
                hints.update(h)
    prio = 5
    for k, v in hints.items():
        kind = {"country": "country", "hub": "hub", "language": "language"}.get(k)
        if kind:
            names = (COUNTRIES_AR.get(v, v), v) if kind == "country" else (LANGS_AR.get(v, v), v) if kind == "language" else (None, None)
            seo_db.set_membership(con, cid, seo_db.taxonomy_id(con, kind, v, str(v).lower(), names[0], names[1], now), "hint", 0.3, now)
            if k == "hub":
                prio = 1
    return prio


# ================= الطابور =================
def enqueue(con, cid, sources, priority=5, now=None):
    now = now or int(time.time())
    con.executemany("INSERT INTO enrich_queue(content_id, source, state, priority, next_at, updated_at) VALUES (?,?,'pending',?,0,?) "
                    "ON CONFLICT(content_id, source) DO UPDATE SET priority=MIN(enrich_queue.priority, excluded.priority), "
                    "state=CASE WHEN enrich_queue.state IN ('done','skip') THEN enrich_queue.state ELSE 'pending' END, updated_at=excluded.updated_at",
                    [(cid, s, int(priority), now) for s in sources])


def queue_stats(con):
    out = {}
    for r in con.execute("SELECT source, state, COUNT(*) n FROM enrich_queue GROUP BY 1, 2"):
        out.setdefault(r["source"], {})[r["state"]] = r["n"]
    return out


def _review(con, kind, cid, name, payload, now):
    con.execute("INSERT INTO review(kind, key, payload_json, status, created_at, updated_at) VALUES (?,?,?,'open',?,?) "
                "ON CONFLICT(key) DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at",
                (kind, f"{kind}:{cid}", json.dumps({"name": name, "content_id": cid, **payload}, ensure_ascii=False), now, now))


def _one(con, data_dir, cid, source, st, now):
    """عنصرٌ واحد من الطابور ← الحال الجديدة (done · miss · pending) ورسالة."""
    if source == "xtream":
        n = apply_xtream(con, data_dir, cid, st, now)
        return ("done" if n else "miss"), f"{n} servers"
    if source == "tmdb":
        res, data = resolve_tmdb(con, data_dir, cid, st, now)
        name = con.execute("SELECT title FROM content WHERE id=?", (cid,)).fetchone()[0]
        if res == "ok":
            cand, d, how, _ = data
            owner = con.execute("SELECT entity_id FROM external_id WHERE entity='content' AND source='tmdb' AND external_id=? AND verified=1 AND entity_id!=?",
                                (str(d["id"]), cid)).fetchone()
            if owner:                                   # العمل نفسه بكيانٍ آخر مُتحقَّق (اسمٌ عربي هنا ولاتيني هناك): يُدمجان
                seo_db.merge_content(con, cid, owner[0], reason=f"same tmdb {d['id']}", now=now)
                return "done", f"merged into {owner[0]} (tmdb {d['id']})"
            apply_tmdb(con, data_dir, cid, d, st, now)
            con.execute("UPDATE review SET status='stale', updated_at=? WHERE key IN (?,?) AND status='open'", (now, f"tmdb_weak:{cid}", f"tmdb_ambiguous:{cid}"))
            return "done", f"tmdb {d['id']} via {how}"
        hints = [f"{r['kind']}:{r['key']}" for r in con.execute("SELECT t.kind, t.key FROM content_taxonomy ct JOIN taxonomy t ON t.id=ct.taxonomy_id "
                                                               "WHERE ct.content_id=? AND ct.source='hint' AND t.kind='hub'", (cid,))]
        if hints:                                   # قسمٌ يقول تركي/أنمي وTMDB لم يحسم: لا تصنيف تلقائي — مراجعة
            _review(con, "taxonomy_unconfirmed", cid, name, {"hints": hints, "tmdb": res, "decision": "none", "confidence": "low"}, now)
        if res in ("weak", "ambiguous"):
            _review(con, f"tmdb_{res}", cid, name, {"candidates": [{k: c.get(k) for k in ("id", "title", "original_title", "year")} for c in data][:5]}, now)
            return "miss", res
        return "miss", "no candidate"
    if source == "tmdb_seasons":
        n = apply_seasons(con, data_dir, cid, st, now)
        return "done", f"{n} episodes"
    return "skip", "unknown source"


def run(data_dir, limit=None, force=False, now=None):
    """دفعةٌ من الطابور (داخل النافذة، أو ‏force) ← {processed, done, miss, error, skipped}. كل عنصرٍ في معاملته."""
    now = int(now or time.time())
    res = {"processed": 0, "done": 0, "miss": 0, "error": 0, "skipped": 0, "window": None}
    with seo_db.lock(data_dir):
        con = seo_db.connect(data_dir)
        try:
            st = seo_db.settings(con)
            res["window"] = window_open(st, now)
            if not force and not res["window"]:
                return res
            limit = int(limit or st.get("enrich_batch", 200))
            backoff = st.get("enrich_backoff") or [3600, 86400, 604800]
            seen, stop = set(), False
            while not stop and len(seen) < limit:
                rows = [r for r in con.execute(
                    "SELECT content_id, source, attempts FROM enrich_queue WHERE state='pending' AND next_at<=? "
                    "ORDER BY priority, CASE source WHEN 'xtream' THEN 0 WHEN 'tmdb' THEN 1 ELSE 2 END, next_at, content_id LIMIT ?",
                    (now, limit)).fetchall() if (r["content_id"], r["source"]) not in seen][:limit - len(seen)]
                if not rows:
                    break
                for r in rows:
                    seen.add((r["content_id"], r["source"]))
                    if _step(con, data_dir, r, st, backoff, res, now):
                        stop = True
                        break
            _state[os.path.abspath(data_dir)] = {"at": now, **res}
            return res
        finally:
            con.close()


def _step(con, data_dir, r, st, backoff, res, now):
    """عنصرٌ من الطابور في معاملته ← هل نتوقّف (مفتاحٌ مرفوض أو 429)؟"""
    cid, source = r["content_id"], r["source"]
    if source == "tmdb" and con.execute("SELECT 1 FROM enrich_queue WHERE content_id=? AND source='xtream' AND state='pending' AND next_at<=?",
                                        (cid, now)).fetchone():
        return False                             # Xtream أولًا (يعطي المرشّح)؛ يُعاد إليه في الجولة التالية
    try:
        with con:
            state, msg = _one(con, data_dir, cid, source, st, now)
            nxt = now + 30 * 86400 if state == "miss" else 0
            con.execute("UPDATE enrich_queue SET state=?, next_at=?, error=?, attempts=attempts+1, updated_at=? WHERE content_id=? AND source=?",
                        (state, nxt, msg[:200], now, cid, source))
        res["processed"] += 1
        res[state if state in res else "done"] += 1
    except Skip as e:
        res["skipped"] += 1
        con.execute("UPDATE enrich_queue SET next_at=?, error=?, updated_at=? WHERE content_id=? AND source=?",
                    (now + 3600, str(e)[:200], now, cid, source))
        con.commit()
        return "مفتاح" in str(e)
    except (ConnectionError, OSError, ValueError, KeyError, TypeError) as e:
        att = r["attempts"] + 1
        state = "error" if att > len(backoff) else "pending"
        con.execute("UPDATE enrich_queue SET state=?, attempts=?, next_at=?, error=?, updated_at=? WHERE content_id=? AND source=?",
                    (state, att, now + backoff[min(att, len(backoff)) - 1], f"{type(e).__name__}: {str(e)[:180]}", now, cid, source))
        con.commit()
        res["error"] += 1
        return isinstance(e, ConnectionError) and "429" in str(e)
    return False


def tick(data_dir):
    """في دورة المحتوى كل عشر دقائق: دفعةٌ إن كانت النافذة مفتوحة **والإثراء التلقائي مفعّلًا** (بعد اعتماد العيّنة) — ولا يرفع شيئًا."""
    try:
        con = seo_db.connect(data_dir, create=False)
        if con is None:
            return None
        try:
            auto = bool(seo_db.settings(con).get("enrich_auto"))
        finally:
            con.close()
        if not auto:
            return None
        return run(data_dir)
    except Exception as e:  # noqa: BLE001
        _state[os.path.abspath(data_dir)] = {"at": int(time.time()), "error": str(e)[:300]}
        return None


def start_run(data_dir, limit=None):
    k = os.path.abspath(data_dir)
    t = _running.get(k)
    if t and t.is_alive():
        return False
    t = _running[k] = threading.Thread(target=lambda: run(data_dir, limit, force=True), daemon=True)
    t.start()
    return True


def state(data_dir):
    k = os.path.abspath(data_dir)
    con = seo_db.connect(data_dir, create=False)
    try:
        st = seo_db.settings(con) if con else seo_db.DEFAULTS
        return {"running": bool(_running.get(k) and _running[k].is_alive()), "last": _state.get(k), "window_open": window_open(st),
                "window": st.get("enrich_window"), "has_key": bool(con and tmdb_key(con, data_dir)), "queue": queue_stats(con) if con else {}}
    finally:
        if con:
            con.close()


# ================= عيّنة حقيقية قبل الإثراء الجماعي =================
SAMPLE_SPEC = {"movie": 10, "series": 10, "turkish": 5, "anime": 5}


def sample(data_dir, spec=None, now=None):
    """يختار عيّنةً من القاعدة الحقيقية (10 أفلام · 10 مسلسلات · 5 بقرينة تركي · 5 بقرينة أنمي، الأحدث إضافةً)، يثريها
    وحدها الآن (Xtream ← TMDB ← المواسم) ← تقريرٌ لكل عمل بكل الحقول وحالات التصنيف والعدّادات وأداء الواجهات."""
    now = int(now or time.time())
    spec = {**SAMPLE_SPEC, **(spec or {})}
    with seo_db.lock(data_dir):
        con = seo_db.connect(data_dir)
        try:
            st = seo_db.settings(con)
            picked, seen = [], set()

            def take(label, sql, args, n):
                for r in con.execute(sql + " ORDER BY COALESCE(c.last_seen,0) DESC, c.id DESC LIMIT ?", (*args, n * 3)):
                    if r["id"] not in seen and len([p for p in picked if p[1] == label]) < n:
                        seen.add(r["id"]); picked.append((r["id"], label))
            base = "SELECT c.id FROM content c WHERE c.merged_into IS NULL AND c.available=1"
            hub = " AND c.id IN (SELECT ct.content_id FROM content_taxonomy ct JOIN taxonomy t ON t.id=ct.taxonomy_id WHERE t.kind='hub' AND t.key=?)"
            take("turkish", base + hub, ("turkish",), spec["turkish"])
            take("anime", base + hub, ("anime",), spec["anime"])
            take("movie", base + " AND c.type='movie'", (), spec["movie"])
            take("series", base + " AND c.type='series'", (), spec["series"])
            ids = [i for i, _ in picked]
            backoff = st.get("enrich_backoff") or [3600, 86400, 604800]
            res = {"processed": 0, "done": 0, "miss": 0, "error": 0, "skipped": 0}
            failures = []
            for cid in ids:
                try:                                  # فشل عملٍ لا يُسقط العيّنة: يُسجَّل ويُكمَل
                    enqueue(con, cid, ["xtream", "tmdb"], 0, now)
                    con.commit()
                    for source in ("xtream", "tmdb", "tmdb_seasons"):
                        r = con.execute("SELECT content_id, source, attempts FROM enrich_queue WHERE content_id=? AND source=? AND state='pending'", (cid, source)).fetchone()
                        if r and _step(con, data_dir, r, st, backoff, res, now):
                            failures.append({"id": cid, "source": source, "error": "stopped (key rejected or rate limited)"})
                            break
                except Exception as ex:  # noqa: BLE001
                    con.rollback()
                    failures.append({"id": cid, "error": f"{type(ex).__name__}: {str(ex)[:200]}"})
            works = []
            for cid in ids:
                try:
                    works.append(describe(con, cid, st))
                except Exception as ex:  # noqa: BLE001
                    works.append({"id": cid, "error": f"{type(ex).__name__}: {str(ex)[:200]}"})
            return {"ok": True, "at": now, "ids": ids, "run": res, "failures": failures, "works": works, "summary": summary(con), "api": metrics()}
        finally:
            con.close()


def describe(con, cid, st):
    """كل ما يُفحص في عمل العيّنة: المطابقة والمعرّف والعناوين والبلد واللغة والنوع والمخرج والممثلون والصور والمواسم والحلقات
    والتصنيف (تركي/أنمي) بحالته والأسماء البديلة والنسخ والمصادر — وعناوين الصفحة وcanonical وhreflang وJSON-LD."""
    import seo_pages
    c = con.execute("SELECT * FROM content WHERE id=?", (cid,)).fetchone()
    if not c:
        return {"id": cid, "error": "missing"}
    ext = seo_db.external(con, "content", cid)
    tax = {}
    for r in con.execute("SELECT t.kind, t.key, ct.source FROM content_taxonomy ct JOIN taxonomy t ON t.id=ct.taxonomy_id WHERE ct.content_id=?", (cid,)):
        tax.setdefault(f"{r['kind']}:{r['key']}", []).append(r["source"])
    hints = {k for k, v in tax.items() if "hint" in v and k.startswith("hub:")}
    links = con.execute("SELECT service_key, versions_json, raw_names_json, groups_json FROM content_service WHERE content_id=? AND present=1", (cid,)).fetchall()
    rls = rules(con)
    for ln in links:                                  # ما تقوله أقسام السيرفرات (ولو غلبتها عضوية TMDB بعد دمج)
        for g in json.loads(ln["groups_json"] or "[]"):
            for rx, h in rls:
                if rx.search(g) and h.get("hub"):
                    hints.add("hub:" + h["hub"])
    confirmed = {k for k, v in tax.items() if "tmdb" in v or "manual" in v}
    disputed = {k for k, v in tax.items() if "disputed" in v}
    reviews = [r["kind"] for r in con.execute("SELECT kind FROM review WHERE status='open' AND json_extract(payload_json,'$.content_id')=?", (cid,))]

    def classify(hub):
        key = f"hub:{hub}"
        tm = key in confirmed
        hint = key in hints
        if tm and hint:
            return {"decision": hub, "confidence": "high", "tmdb": True, "section": True, "note": "confirmed"}
        if tm:
            return {"decision": hub, "confidence": "high", "tmdb": True, "section": False, "note": "tmdb only"}
        if hint and c["match"] == "tmdb":
            return {"decision": "review", "confidence": "low", "tmdb": False, "section": True, "note": "section says " + hub + "; TMDB disagrees → taxonomy_mismatch (not in hub, TMDB not auto-adopted)"}
        if hint:
            return {"decision": "unconfirmed", "confidence": "low", "tmdb": None, "section": True, "note": "TMDB incomplete → taxonomy_unconfirmed (no automatic classification)"}
        return None
    people = {}
    for r in con.execute("SELECT p.name, cp.role FROM content_person cp JOIN person p ON p.id=cp.person_id WHERE cp.content_id=? ORDER BY cp.ord", (cid,)):
        people.setdefault(r["role"], []).append(r["name"])
    pv = seo_db.provenance(con, "content", cid)
    page = {}
    for lang in ("ar", "en"):
        tr = __import__("content_page").lang_of(lang)
        res = seo_pages.render_entity(con, "", c["type"], c["slug"], tr, st)
        if res and res[0] == "page":
            html = res[1]["html"].decode("utf-8")
            page[lang] = {"seo_title": res[1]["title"], "meta_description": res[1]["desc"], "canonical": res[1]["canonical"],
                          "hreflang": [u for _, u in res[1]["alts"]], "json_ld": re.findall(r'"@type": "(\w+)"', html)[:6],
                          "would_index": res[1]["index_ar" if lang == "ar" else "index_en"], "why": res[1]["why"][0 if lang == "ar" else 1]}
    return {"id": cid, "slug": c["slug"], "type": c["type"], "match": c["match"], "tmdb_id": c["tmdb_id"],
            "tmdb_candidate": {k: v for k, v in (ext.get("tmdb") or {}).items() if k in ("external_id", "verified", "how")} or None,
            "title": c["title"], "title_ar": c["title_ar"], "title_en": c["title_en"], "original_title": c["original_title"],
            "country": json.loads(c["origin_country_json"]) if c["origin_country_json"] else None, "language": c["original_language"],
            "genres": json.loads(c["genres_json"]) if c["genres_json"] else None, "director": people.get("director") or people.get("creator"),
            "cast": (people.get("actor") or people.get("voice") or [])[:6], "poster": bool(c["poster"]), "backdrop": bool(c["backdrop"]),
            "seasons": con.execute("SELECT COUNT(*) FROM season WHERE content_id=?", (cid,)).fetchone()[0],
            "episodes_detailed": con.execute("SELECT COUNT(*) FROM episode WHERE content_id=?", (cid,)).fetchone()[0],
            "format": c["format"] or None, "anime_kind": c["anime_kind"], "disputed": sorted(disputed),
            "turkish": classify("turkish"), "anime": classify("anime"),
            "aliases": [r[0] for r in con.execute("SELECT alias FROM content_alias WHERE content_id=?", (cid,))],
            "versions": {r["service_key"]: json.loads(r["versions_json"]) for r in links if r["versions_json"]},
            "raw_names": {r["service_key"]: json.loads(r["raw_names_json"]) for r in links if r["raw_names_json"]},
            "sections": {r["service_key"]: json.loads(r["groups_json"]) for r in links if r["groups_json"]},
            "provenance": {k: v[0] for k, v in pv.items()}, "reviews": reviews, "page": page}


def summary(con):
    q = lambda sql, *a: con.execute(sql, a).fetchone()[0]   # noqa: E731
    live = "merged_into IS NULL AND available=1"
    rv = {r["kind"]: r["n"] for r in con.execute("SELECT kind, COUNT(*) n FROM review WHERE status='open' GROUP BY kind")}
    return {"high_confidence_matches": q(f"SELECT COUNT(*) FROM content WHERE {live} AND match='tmdb'"),
            "needs_review": {"total": sum(rv.values()), "by_kind": rv},
            "no_tmdb": q("SELECT COUNT(*) FROM enrich_queue WHERE source='tmdb' AND state='miss'"),
            "conflicts": sum(v for k, v in rv.items() if k in ("conflict", "tmdb_ambiguous", "taxonomy_mismatch")),
            "turkish_confirmed": q("SELECT COUNT(*) FROM content_taxonomy ct JOIN taxonomy t ON t.id=ct.taxonomy_id JOIN content c ON c.id=ct.content_id "
                                   f"WHERE t.kind='hub' AND t.key='turkish' AND ct.source IN ('tmdb','manual') AND c.{live.replace(' AND ', ' AND c.')}"),
            "anime_confirmed": q("SELECT COUNT(*) FROM content_taxonomy ct JOIN taxonomy t ON t.id=ct.taxonomy_id JOIN content c ON c.id=ct.content_id "
                                 f"WHERE t.kind='hub' AND t.key='anime' AND ct.source IN ('tmdb','manual') AND c.{live.replace(' AND ', ' AND c.')}"),
            "anime_by_kind": {r["anime_kind"]: r["n"] for r in con.execute(f"SELECT anime_kind, COUNT(*) n FROM content WHERE {live} AND anime_kind IS NOT NULL GROUP BY 1")},
            "hints_only": {r["key"]: r["n"] for r in con.execute("SELECT t.key, COUNT(*) n FROM content_taxonomy ct JOIN taxonomy t ON t.id=ct.taxonomy_id WHERE t.kind='hub' AND ct.source='hint' GROUP BY t.key")},
            "aliases": q("SELECT COUNT(*) FROM content_alias"), "versions": q("SELECT COUNT(*) FROM content_service WHERE versions_json IS NOT NULL AND present=1"),
            "data_errors": [dict(r) for r in con.execute("SELECT source, error, COUNT(*) n FROM enrich_queue WHERE state='error' OR (error IS NOT NULL AND error LIKE '%Error%') GROUP BY 1, 2 ORDER BY n DESC LIMIT 10")],
            "queue": queue_stats(con), "people": q("SELECT COUNT(*) FROM person"), "episodes_detailed": q("SELECT COUNT(*) FROM episode")}


# ================= ختم الملفات وتنقيتها =================
def code_version():
    """نسخة الكود: commit من git إن وُجد، وبصمة ملفات الطبقة دائمًا (داخل الحاوية لا git)."""
    import hashlib
    import subprocess
    here = os.path.dirname(os.path.abspath(__file__))
    h = hashlib.sha1()
    for n in ("seo_db.py", "seo_match.py", "seo_build.py", "seo_search.py", "seo_sources.py", "seo_pages.py", "content.py"):
        try:
            with open(os.path.join(here, n), "rb") as f:
                h.update(f.read())
        except OSError:
            pass
    commit = ""
    try:
        commit = subprocess.run(["git", "-C", here, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return {"commit": commit or None, "code_fingerprint": h.hexdigest()[:16]}


def meta(data_dir):
    return {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **code_version(), "data": os.path.basename(os.path.abspath(data_dir))}


def secrets(data_dir):
    """ما يجب ألّا يظهر في أي ملف: مفتاح TMDB، ومستخدمو اللوحات وكلماتهم ومضيفوها."""
    out = set()
    con = seo_db.connect(data_dir, create=False)
    if con:
        try:
            k = tmdb_key(con, data_dir)
            if k:
                out.add(k)
        finally:
            con.close()
    for srv in C.servers(data_dir):
        xt = _creds(data_dir, srv["key"])
        if xt:
            base, user, pw = xt
            out.update(x for x in (user, pw, base, base.split("//", 1)[-1]) if x and len(x) >= 4)
    return out


def _scrub(text, secs):
    for sct in sorted(secs, key=len, reverse=True):
        text = text.replace(sct, "•••")
    return text


# ================= الفحص الأولي =================
def probe(data_dir, n=20):
    """ماذا تعطي كل لوحة فعلًا: n فيلمًا وn مسلسلًا من كل سيرفرٍ له رابط ← الحقول الموجودة وعددها — قبل أي إثراء.
    **قراءةٌ صرفة**: لا يكتب في القاعدة (ولا في كاش الردود)."""
    con = seo_db.connect(data_dir, create=False)
    if con is None:
        return {"error": "لم تُبنَ القاعدة بعد"}
    out = {}
    try:
        st = seo_db.settings(con)
        for srv in C.servers(data_dir):
            xt = _creds(data_dir, srv["key"])
            if not xt:
                out[srv["key"]] = {"error": "لا رابط Xtream"}
                continue
            rep = {}
            for kind, action, idf in (("movie", "get_vod_info", "vod_id"), ("series", "get_series_info", "series_id")):
                rows = con.execute("SELECT name, stream_id, series_id FROM content_service WHERE service_key=? AND kind=? AND present=1 "
                                   "ORDER BY added DESC LIMIT ?", (srv["key"], kind, n)).fetchall()
                smap = _series_map(con, xt, st, write=False) if kind == "series" and any(not r["series_id"] for r in rows) else {}
                fields, answered, eps_title, eps_plot, eps_n = {}, 0, 0, 0, 0
                for r in rows:
                    ident = r["stream_id"] if kind == "movie" else (r["series_id"] or smap.get(M.norm(r["name"])))
                    if not ident:
                        continue
                    try:
                        d = _xt_json(con, xt, action, st, write=False, **{idf: ident})
                    except ConnectionError as e:
                        rep[kind] = {"error": _scrub(str(e), secrets(data_dir))}
                        break
                    info = (d or {}).get("info") or {}
                    if not info:
                        continue
                    answered += 1
                    for k, v in info.items():
                        if v not in (None, "", [], {}, "0", 0):
                            fields[k] = fields.get(k, 0) + 1
                    for lst in ((d or {}).get("episodes") or {}).values() if isinstance((d or {}).get("episodes"), dict) else []:
                        for ep in lst if isinstance(lst, list) else []:
                            eps_n += 1
                            eps_title += bool(ep.get("title") and not re.fullmatch(r"(?i)(episode|ep\.?|حلقة)?\s*\d+", str(ep["title"]).strip()))
                            eps_plot += bool((ep.get("info") or {}).get("plot"))
                if kind not in rep:
                    rep[kind] = {"asked": len(rows), "answered": answered, "fields": dict(sorted(fields.items(), key=lambda kv: -kv[1])),
                                 **({"episodes": eps_n, "episodes_with_title": eps_title, "episodes_with_plot": eps_plot} if kind == "series" else {})}
            out[srv["key"]] = rep
        return out
    finally:
        con.close()


def bundle(data_dir, out, n=20):
    """لقطةٌ للمراجعة: probe وreport وsearch-report **قراءةٌ صرفة**؛ وsample وحده يثري أعماله الثلاثين. كل ملفٍ مختومٌ بالوقت
    ونسخة الكود، ومنقًّى من المفتاح وبيانات اللوحات. فشل جزءٍ لا يمنع كتابة الباقي (يُكتب خطؤه مكانه)."""
    import contextlib
    import io
    import seo_build
    os.makedirs(out, exist_ok=True)
    secs = secrets(data_dir)
    stamp = meta(data_dir)
    written = {}

    def dump_json(name, fn):
        try:
            data = fn()
        except Exception as ex:  # noqa: BLE001
            data = {"error": f"{type(ex).__name__}: {str(ex)[:300]}"}
        text = _scrub(json.dumps({"meta": stamp, **data} if isinstance(data, dict) else {"meta": stamp, "data": data}, ensure_ascii=False, indent=1), secs)
        with open(os.path.join(out, name), "w", encoding="utf-8") as f:
            f.write(text)
        written[name] = len(text)

    def dump_text(name, fn):
        try:
            text = fn()
        except Exception as ex:  # noqa: BLE001
            text = f"error: {type(ex).__name__}: {str(ex)[:300]}"
        head = "# " + json.dumps(stamp, ensure_ascii=False) + "\n"
        with open(os.path.join(out, name), "w", encoding="utf-8") as f:
            f.write(_scrub(head + text + "\n", secs))
        written[name] = len(text)

    def search_report():
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            seo_build.main(["seo_build.py", "search-report"])
        return buf.getvalue()
    dump_json("probe.json", lambda: probe(data_dir, n))                 # قراءة
    dump_json("sample.json", lambda: sample(data_dir))                  # الاستثناء الوحيد: إثراء الثلاثين
    dump_text("report.txt", lambda: seo_build.report(data_dir))         # قراءة
    dump_text("search-report.txt", search_report)                       # قراءة
    return {"out": out, "files": written, **stamp}


BUNDLE_FILES = ("probe.json", "sample.json", "report.txt", "search-report.txt")
_bundling = {}


def bundle_dir(data_dir):
    return os.path.join(data_dir, "content", "seo-review")


def start_bundle(data_dir, n=20):
    """«أنتج ملفات المراجعة» من بطاقة الإدارة: في خيطٍ (يستغرق دقائق: الفحص بطلبٍ في الثانية لكل لوحة ثم عيّنة الثلاثين)،
    وعمليةٌ واحدة في وقتها ← هل بدأت؟"""
    k = os.path.abspath(data_dir)
    t = _bundling.get(k)
    if t and t.is_alive():
        return False
    _state[k + ":bundle"] = {"at": int(time.time()), "running": True}

    def run_():
        try:
            res = bundle(data_dir, bundle_dir(data_dir), n)
            _state[k + ":bundle"] = {"at": int(time.time()), "running": False, "ok": True, **res}
        except Exception as e:  # noqa: BLE001
            _state[k + ":bundle"] = {"at": int(time.time()), "running": False, "ok": False, "error": str(e)[:300]}
    t = _bundling[k] = threading.Thread(target=run_, daemon=True)
    t.start()
    return True


def bundle_state(data_dir):
    """حال الإنتاج وآخر ملفاتٍ مكتوبة (الاسم والحجم والوقت) — لروابط التنزيل في البطاقة."""
    k = os.path.abspath(data_dir)
    d = bundle_dir(data_dir)
    files = []
    for n in BUNDLE_FILES:
        try:
            st_ = os.stat(os.path.join(d, n))
            files.append({"name": n, "size": st_.st_size, "at": int(st_.st_mtime)})
        except OSError:
            pass
    last = _state.get(k + ":bundle") or {}
    return {"running": bool(_bundling.get(k) and _bundling[k].is_alive()), "last": last, "files": files}


def bundle_file(data_dir, name):
    """ملفٌ من ملفات المراجعة بالاسم (من القائمة وحدها) ← (bytes, نوعه) أو None."""
    if name not in BUNDLE_FILES:
        return None
    try:
        with open(os.path.join(bundle_dir(data_dir), name), "rb") as f:
            return f.read(), ("application/json; charset=utf-8" if name.endswith(".json") else "text/plain; charset=utf-8")
    except OSError:
        return None


def main(argv):
    data_dir = os.environ.get("XM_DATA") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    cmd = argv[1] if len(argv) > 1 else "queue"
    opt = {a.lstrip("-").split("=")[0]: (a.split("=", 1)[1] if "=" in a else True) for a in argv[2:] if a.startswith("--")}
    if cmd == "probe":
        print(json.dumps(probe(data_dir, int(opt.get("n") or 20)), ensure_ascii=False, indent=1))
    elif cmd == "run":
        print(json.dumps(run(data_dir, int(opt["limit"]) if opt.get("limit") else None, force=bool(opt.get("force"))), ensure_ascii=False))
    elif cmd == "queue":
        print(json.dumps(state(data_dir), ensure_ascii=False, indent=1))
    elif cmd == "sample":                        # عيّنة 30 عملًا تُثرى الآن وتقريرها
        print(json.dumps(sample(data_dir), ensure_ascii=False, indent=1))
    elif cmd == "bundle":                        # الملفات الخام الأربعة للمراجعة في مجلدٍ واحد: probe.json · sample.json · report.txt · search-report.txt
        print(json.dumps(bundle(data_dir, str(opt.get("out") or "seo-review"), int(opt.get("n") or 20)), ensure_ascii=False))
    elif cmd == "key":
        con = seo_db.connect(data_dir)
        set_tmdb_key(con, data_dir, str(opt.get("set") or "")); con.close()
        print("saved" if opt.get("set") else "cleared")
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)

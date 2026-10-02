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

CREW_ROLES = {"Director": "director", "Series Director": "director", "Writer": "writer", "Screenplay": "screenwriter", "Story": "writer",
              "Novel": "writer", "Teleplay": "writer", "Comic Book": "writer", "Characters": "writer", "Original Story": "writer", "Author": "writer"}

_lock = threading.Lock()
_last_call = {}                     # المصدر ← وقت آخر طلب (تحديد السرعة)
_metrics = {}                       # المصدر ← {n, seconds, max, errors, cache_hits} — أداء الواجهات لتقرير العيّنة


def _metric(source, seconds=None, status=None, cache_hit=False):
    with _lock:
        m = _metrics.setdefault(source, {"n": 0, "seconds": 0.0, "max": 0.0, "errors": 0, "not_found": 0, "cache_hits": 0})
        if cache_hit:
            m["cache_hits"] += 1
            return
        m["n"] += 1
        m["seconds"] += seconds
        m["max"] = max(m["max"], seconds)
        if status == 404:                        # ردٌّ متوقَّع (لا شيء هناك) — يُعدّ على حدة ولا يُسمّى خطأ
            m["not_found"] += 1
        elif status and status >= 400:
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
    countries = list(d.get("origin_country") or []) + [pc.get("iso_3166_1") for pc in d.get("production_countries") or [] if pc.get("iso_3166_1")]
    return {"id": d.get("id"), "type": typ, "title": d.get("title") or d.get("name") or "",
            "original_title": d.get("original_title") or d.get("original_name") or "",
            "year": int(date[:4]) if date[:4].isdigit() else 0, "aliases": alts,
            "countries": list(dict.fromkeys(countries)), "language": d.get("original_language") or ""}


def _entity(con, cid):
    row = con.execute("SELECT * FROM content WHERE id=?", (cid,)).fetchone()
    if not row:
        return None
    e = dict(row)
    e["aliases"] = [r[0] for r in con.execute("SELECT alias FROM content_alias WHERE content_id=?", (cid,))]
    e["originals"] = [r[0] for r in con.execute("SELECT alias FROM content_alias WHERE content_id=? AND kind='original' AND source='m3u'", (cid,))]
    e["hint_countries"] = [r[0] for r in con.execute("SELECT t.key FROM content_taxonomy ct JOIN taxonomy t ON t.id=ct.taxonomy_id "
                                                     "WHERE ct.content_id=? AND ct.source='hint' AND t.kind='country'", (cid,))]
    return e


def _strong(cand, e):
    """مطابقة قوية: اسمٌ مطبَّق حرفيًّا مع سنةٍ متفقة (أو بلا سنة عندنا)، أو اسمٌ مطبَّق + ملصقٌ/معرّفٌ من اللوحة."""
    mine = {M.norm(x) for x in [e.get("title"), e.get("title_en"), e.get("original_title")] + e["aliases"] if x}
    theirs = {M.norm(x) for x in [cand.get("title"), cand.get("original_title")] + list(cand.get("aliases") or []) if x}
    exact = bool(mine & theirs)
    year_ok = not e.get("year") or not cand.get("year") or abs(e["year"] - cand["year"]) <= 1
    hint_c, cand_c = set(e.get("hint_countries") or []), set(cand.get("countries") or [])
    origin_ok = not hint_c or not cand_c or bool(hint_c & cand_c) \
        or bool({M.norm(x) for x in e.get("originals") or []} & theirs)   # الاسم الأصلي اللاتيني يطابق: القرينة لا تمنع
    return exact and year_ok and origin_ok and (bool(e.get("year")) or len(mine & theirs) > 0)


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
    latin = [a for a in e["originals"] + [e.get("title")] + e["aliases"] if a and re.search(r"[A-Za-z]", a)]   # الأصلي من القائمة أولًا
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
        best, details, likely = _evidence(con, cid, e, strong, st)
        if best:
            return "ok", (best[0], best[1], best[2] + "+evidence", True)
        return "ambiguous", [dict(v[0], evidence=next((x for x in details if x["id"] == v[0]["id"]), None), likely=(v[0]["id"] == likely)) for v in strong]
    if verified:
        return "weak", [v[0] for v in verified]
    return "miss", []


def _evidence(con, cid, e, strong, st):
    """مرشّحان قويان بالاسم («One Piece» 1999 و2023): قرائن الكيان نفسه تفصل — قرينة قسم «أنمي» مقابل نوع Animation، وعدد
    مواسم القائمة مقابل مواسم المرشّح، وحجم الحلقات المدرجة مقابل الرسمية (قرائن **قوية** تحسم من ينفرد بأعلى درجة).
    وبنية المواسم (حلقات كل موسم في القائمة مقابل حلقات موسم المرشّح) قرينةٌ **مرجِّحة** فقط: ترتّب «الأرجح» في بند المراجعة
    ولا تعتمد مطابقةً وحدها — لا دمج بالتخمين. ← (المختار أو None، تفاصيل كل مرشّح للتقرير)."""
    hints = {r[0] for r in con.execute("SELECT t.key FROM content_taxonomy ct JOIN taxonomy t ON t.id=ct.taxonomy_id WHERE ct.content_id=? AND ct.source='hint' AND t.kind='hub'", (cid,))}
    per_season = {r[0]: r[1] for r in con.execute("SELECT number, episode_count FROM season WHERE content_id=? AND number > 0 AND episode_count > 0", (cid,))}
    seasons = list(per_season)
    listed = sum(per_season.values())
    scored = []
    for v in strong:
        d, s, why, soft = v[1], 0, [], 0
        gids = {g.get("id") for g in d.get("genres") or []}
        if "anime" in hints:
            s += 2 if 16 in gids else -2
            why.append("anime_hint" if 16 in gids else "not_animation")
        if seasons and d.get("number_of_seasons"):
            if int(d["number_of_seasons"]) >= max(seasons):
                s += 1; why.append("seasons_fit")
            else:
                s -= 2; why.append("fewer_seasons_than_listed")
        if listed and d.get("number_of_episodes"):
            if listed <= 3 * int(d["number_of_episodes"]) + 5:
                s += 1; why.append("episodes_fit")
            else:
                s -= 1; why.append("more_listed_than_official")
        official_seasons = {int(x["season_number"]): int(x.get("episode_count") or 0) for x in d.get("seasons") or [] if x.get("season_number")}
        for n, k in per_season.items():                 # بنية المواسم: الموسم المدرج بعدد حلقاته ضمن [الرسمي، 3×الرسمي] = موافق
            o = official_seasons.get(n)
            if o and o <= k <= 3 * o:
                soft += 1
        if soft:
            why.append(f"season_structure:{soft}/{len(per_season)}")
        scored.append({"id": v[0]["id"], "title": v[0]["title"], "year": v[0]["year"], "score": s, "structure": soft, "why": why, "_v": v})
    scored.sort(key=lambda x: (-x["score"], -x["structure"]))
    best = None
    if len(scored) > 1 and scored[0]["score"] > scored[1]["score"] and scored[0]["why"]:
        best = scored[0]["_v"]
    details = [{k: x[k] for k in ("id", "title", "year", "score", "structure", "why")} for x in scored]
    likely = details[0]["id"] if not best and len(details) > 1 and details[0]["structure"] > details[1]["structure"] else None
    return best, details, likely


def _img(path, size):
    return f"{TMDB_IMG}{size}{path}" if path else None


def _slug_for(con, table, name):
    return M.unique_slug(lambda s: con.execute(f"SELECT 1 FROM {table} WHERE slug=?", (s,)).fetchone() is not None, name)


def _name_row(con, name, cid):
    """صفّ «اسمٍ» من لوحة Xtream (بلا معرّف) مرتبطٌ بهذا العمل نفسه — الاسم وحده ليس هويةً تجمع عملين."""
    key = M.person_key(name)
    if not key:
        return None
    pid = (_name_row.prior.get(cid) or {}).get(key)
    if pid and not con.execute("SELECT 1 FROM external_id x WHERE x.entity='person' AND x.entity_id=?", (pid,)).fetchone():
        return pid
    r = con.execute("SELECT p.id FROM person p JOIN content_person cp ON cp.person_id=p.id WHERE p.name_norm=? AND cp.content_id=? "
                    "AND NOT EXISTS (SELECT 1 FROM external_id x WHERE x.entity='person' AND x.entity_id=p.id) LIMIT 1", (key, cid)).fetchone()
    return r["id"] if r else None


_name_row.prior = {}        # العمل ← {مفتاح الاسم: صفّ الاسم} أثناء كتابة أدوار TMDB له


def _person(con, p, now, cid=None):
    """صفّ الشخص بمعرّف TMDB (الشخص الواحد صفٌّ واحد مهما تعدّدت أسماؤه). صفّ «اسمٍ» من اللوحة يُرقّى بالمعرّف **فقط** إن كان
    مرتبطًا بالعمل نفسه (الاسم نفسه في العمل نفسه = الشخص نفسه)؛ وإلا صفٌّ جديد — فالاسم وحده لا يدمج شخصين، ويبقى
    التشابه بندَ مراجعة (person_same_name) حتى يوجد دليل هوية خارجي."""
    r = con.execute("SELECT entity_id FROM external_id WHERE entity='person' AND source='tmdb' AND external_id=?", (str(p["id"]),)).fetchone()
    if r:
        return r["entity_id"]
    name = p.get("name") or p.get("original_name") or ""
    if not name:
        return None
    pid = None
    if cid:
        for nm in (name, p.get("original_name") or ""):
            pid = pid or (_name_row(con, nm, cid) if nm else None)
    if pid:
        con.execute("UPDATE person SET name_en=COALESCE(name_en, ?), original_name=COALESCE(original_name, ?), photo=COALESCE(photo, ?), updated_at=? WHERE id=?",
                    (name, p.get("original_name"), _img(p.get("profile_path"), "w185"), now, pid))
    else:
        cur = con.execute("INSERT INTO person(slug, name, name_en, original_name, photo, name_norm, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                          (_slug_for(con, "person", name), name, name, p.get("original_name"), _img(p.get("profile_path"), "w185"), M.person_key(name), now, now))
        pid = cur.lastrowid
    seo_db.set_external(con, "person", pid, "tmdb", p["id"], verified=True, confidence=1, how="tmdb", now=now)
    return pid


def review_same_names(con, now=None):
    """أسماءٌ متكرّرة بلا معرّفاتٍ مميِّزة (صفّان فأكثر لمفتاح اسمٍ واحد وعدد معرّفات TMDB أقل): بند مراجعة لكلٍّ — لا دمج تلقائي.
    ← عدد البنود المفتوحة."""
    now = now or int(time.time())
    groups = con.execute("SELECT name_norm, COUNT(*) n, GROUP_CONCAT(id) ids FROM person WHERE name_norm IS NOT NULL AND name_norm != '' GROUP BY name_norm HAVING COUNT(*) > 1").fetchall()
    open_keys = set()
    for g in groups:
        ids = [int(x) for x in g["ids"].split(",")]
        tm = {r[0] for r in con.execute(f"SELECT external_id FROM external_id WHERE entity='person' AND source='tmdb' AND entity_id IN ({','.join('?' * len(ids))})", ids)}
        if len(tm) >= len(ids):
            continue                                   # كلٌّ بمعرّفه: أشخاصٌ مختلفون بالاسم نفسه
        rows = [dict(r) for r in con.execute(f"SELECT p.id, p.name, p.slug, (SELECT external_id FROM external_id x WHERE x.entity='person' AND x.entity_id=p.id AND x.source='tmdb') tmdb, "
                                             f"(SELECT COUNT(*) FROM content_person cp WHERE cp.person_id=p.id) works FROM person p WHERE p.id IN ({','.join('?' * len(ids))})", ids)]
        key = f"person_same_name:{g['name_norm']}"
        open_keys.add(key)
        con.execute("INSERT INTO review(kind, key, payload_json, status, created_at, updated_at) VALUES ('person_same_name', ?, ?, 'open', ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at, status=CASE WHEN review.status='resolved' THEN 'resolved' ELSE 'open' END",
                    (key, json.dumps({"name": g["name_norm"], "rows": rows, "decision": "review", "note": "same name, no distinct external ids — not merged automatically"}, ensure_ascii=False), now, now))
    for r in con.execute("SELECT key FROM review WHERE kind='person_same_name' AND status='open'").fetchall():
        if r["key"] not in open_keys:
            con.execute("UPDATE review SET status='stale', updated_at=? WHERE key=?", (now, r["key"]))
    return len(open_keys)


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
    # الأنمي طبقاتٌ ثلاث: رسومٌ متحركة؟ (genre Animation) ← من عائلة الأنمي؟ (لغة المنشأ/بلده في جداول الإعدادات) ← نوعه
    # (japanese · chinese · korean). رسومٌ إسبانية/أمريكية = is_animation بلا anime_family؛ وكلمة TMDB المفتاحية «anime»
    # بلا لغة/بلد لا تحسم (anime_family = NULL ← مراجعة)، ولا تجعل عملًا غير يابانيّ يابانيًّا.
    is_animation = 16 in gids
    anime_kind, anime_family = "", 0
    if is_animation:
        anime_kind = (st.get("anime_langs") or {}).get(lang, "")
        for c in countries:
            anime_kind = anime_kind or (st.get("anime_countries") or {}).get(c, "")
        if anime_kind:
            anime_family = 1
        elif not lang and not countries:
            anime_family = None                   # TMDB لم يقل من أين: غير محسوم — والكلمة المفتاحية «anime» (kw) لا تحسمه ولا تجعله يابانيًّا
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
        "format": ("anime_series" if typ == "series" else "anime_movie") if anime_family == 1 else "", "anime_kind": anime_kind or None,
        "is_animation": 1 if is_animation else 0, "anime_family": anime_family,
        "episodes_official": d.get("number_of_episodes") or None, "seasons_official": d.get("number_of_seasons") or None,
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
    if anime_family == 1:
        seo_db.set_membership(con, cid, seo_db.taxonomy_id(con, "hub", "anime", "anime", "أنمي", "Anime", now), "tmdb", 1, now)
        seo_db.set_membership(con, cid, seo_db.taxonomy_id(con, "anime_kind", anime_kind, anime_kind, None, anime_kind.title(), now), "tmdb", 1, now)
    # قرائن الأقسام مقابل TMDB — متحفّظًا، وبلا قلبٍ لنتيجة TMDB الصحيحة:
    #   • قرينةٌ يؤكّدها TMDB (قسم «تركية» وTMDB يقول TR) = confirmed — وقرينةٌ أخرى معارضة (قسم «سورية» على العمل نفسه) لا تُسقطها،
    #     بل تُذكر في بند المراجعة (أقسامٌ مختلطة: غالبًا عملان بالاسم نفسه).
    #   • قرينةٌ لا يؤيّدها TMDB في بُعدها كلّه (قسم «تركية» وTMDB يقول SY فقط) = مراجعة (taxonomy_mismatch)، وعضويّات TMDB في ذلك
    #     البُعد تُعلَّم disputed فلا تدخل الهب ولا الصفحات حتى يحسمها المدير — ولا يُعتمد TMDB تلقائيًّا.
    #   • قسمٌ يقول أنمي وTMDB يقول رسومًا من بلدٍ آخر (إسبانيا) = مراجعة بلا صفة أنمي؛ وTMDB بلا لغة/بلد = unconfirmed.
    hints = {f"{r['kind']}:{r['key']}" for r in con.execute("SELECT t.kind, t.key FROM content_taxonomy ct JOIN taxonomy t ON t.id=ct.taxonomy_id WHERE ct.content_id=? AND ct.source='hint'", (cid,))}
    confirmed = {f"{r['kind']}:{r['key']}" for r in con.execute("SELECT t.kind, t.key FROM content_taxonomy ct JOIN taxonomy t ON t.id=ct.taxonomy_id WHERE ct.content_id=? AND ct.source='tmdb'", (cid,))}
    unsupported = {h for h in hints if h.startswith(("hub:", "country:")) and h not in confirmed}
    hub_hints, country_hints = {h for h in hints if h.startswith("hub:")}, {h for h in hints if h.startswith("country:")}
    disputed = set()
    if hub_hints and not (hub_hints & confirmed):           # لا هبَّ من أقسام العمل يؤيّده TMDB: هبّات TMDB (إن كانت) محلّ نزاع
        disputed |= {x for x in confirmed if x.startswith(("hub:", "anime_kind:"))}
    if country_hints and not (country_hints & confirmed):   # ولا بلدَ من أقسامه يؤيّده TMDB: بلدان TMDB محلّ نزاع
        disputed |= {x for x in confirmed if x.startswith("country:")}
    unconfirmed_anime = "hub:anime" in hub_hints and anime_family is None
    if unsupported and not (unconfirmed_anime and unsupported == {"hub:anime"}):
        for x in sorted(disputed):
            kind, key = x.split(":", 1)
            con.execute("UPDATE content_taxonomy SET source='disputed' WHERE content_id=? AND source='tmdb' AND taxonomy_id=(SELECT id FROM taxonomy WHERE kind=? AND key=?)",
                        (cid, kind, key))
        if "hub:anime" in unsupported or any(x.startswith("hub:anime") for x in disputed):
            seo_db.apply_fields(con, "content", cid, {"format": "", "anime_kind": None}, "tmdb", now=now)   # لا صفة أنمي قبل الحسم
        kept = sorted(x for x in confirmed if x.startswith(("hub:", "country:")) and x not in disputed)
        _review(con, "taxonomy_mismatch", cid, e["title"], {"hints": sorted(unsupported), "tmdb": sorted(x for x in confirmed if x.startswith(("hub:", "country:"))),
                                                           "disputed": sorted(disputed), "kept": kept, "decision": "review", "confidence": "low",
                                                           "mixed_sections": len(country_hints) > 1 or (bool(hub_hints & confirmed) and bool(unsupported)),
                                                           "note": ("animation but not anime per TMDB (country " + ",".join(countries) + ")") if "hub:anime" in unsupported and is_animation
                                                           else ("sections disagree with each other; TMDB-confirmed classification kept" if kept else "section hint unsupported by TMDB")}, now)
    else:
        con.execute("UPDATE review SET status='stale', updated_at=? WHERE key=? AND status='open'", (now, f"taxonomy_mismatch:{cid}"))
    if unconfirmed_anime:
        _review(con, "taxonomy_unconfirmed", cid, e["title"], {"hints": ["hub:anime"], "tmdb": "animation without origin language/country", "decision": "none", "confidence": "low"}, now)
    else:
        con.execute("UPDATE review SET status='stale', updated_at=? WHERE key=? AND status='open'", (now, f"taxonomy_unconfirmed:{cid}"))
    # الأشخاص والشركات
    _name_row.prior[cid] = {r["name_norm"]: r["id"] for r in con.execute(      # صفوف أسماء هذا العمل من اللوحة قبل استبدال الأدوار: تُرقّى بمعرّف TMDB (العمل نفسه = الشخص نفسه)
        "SELECT p.id, p.name_norm FROM person p WHERE p.name_norm IS NOT NULL AND NOT EXISTS (SELECT 1 FROM external_id x WHERE x.entity='person' AND x.entity_id=p.id) "
        "AND p.id IN (SELECT person_id FROM content_person WHERE content_id=?)", (cid,))}
    con.execute("DELETE FROM content_person WHERE content_id=? AND source IN ('tmdb','xtream')", (cid,))
    credits = d.get("credits") or d.get("aggregate_credits") or {}
    for i, p in enumerate((credits.get("cast") or [])[:15]):
        pid = _person(con, p, now, cid)
        if pid:
            ch = p.get("character") or ((p.get("roles") or [{}])[0]).get("character") or ""
            role = "voice" if is_animation or "(voice)" in ch.lower() else "actor"
            con.execute("INSERT OR IGNORE INTO content_person(content_id, person_id, role, character, ord, source) VALUES (?,?,?,?,?,'tmdb')",
                        (cid, pid, role, ch[:120] or None, i))
    # الكاتب نموذجٌ مستقل: writer (Writer · Story · Novel · Teleplay · Comic Book · Characters) · screenwriter (Screenplay) · creator (created_by)
    # — ولا يُخلط بالمخرج أو الممثل لتشابه الاسم: الدور في content_person والشخص واحد بمعرّفه
    for p in credits.get("crew") or []:
        for job in [p.get("job")] + [j.get("job") for j in p.get("jobs") or []]:
            role = CREW_ROLES.get(job or "")
            if role:
                pid = _person(con, p, now, cid)
                if pid:
                    con.execute("INSERT OR IGNORE INTO content_person(content_id, person_id, role, character, ord, source) VALUES (?,?,?,NULL,0,'tmdb')", (cid, pid, role))
    for p in d.get("created_by") or []:
        pid = _person(con, p, now, cid)
        if pid:
            con.execute("INSERT OR IGNORE INTO content_person(content_id, person_id, role, character, ord, source) VALUES (?,?,'creator',NULL,0,'tmdb')", (cid, pid))
    _name_row.prior.pop(cid, None)
    con.execute("DELETE FROM person WHERE id NOT IN (SELECT person_id FROM content_person) AND NOT EXISTS (SELECT 1 FROM external_id x WHERE x.entity='person' AND x.entity_id=person.id)")
    con.execute("DELETE FROM content_company WHERE content_id=? AND source='tmdb'", (cid,))
    for c in (d.get("production_companies") or [])[:5]:
        coid = _company(con, c, "studio", now)
        if coid:
            con.execute("INSERT OR IGNORE INTO content_company(content_id, company_id, role, source) VALUES (?,?,'studio','tmdb')", (cid, coid))
            if anime_family == 1:
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
            con.execute("INSERT INTO season(content_id, number, name, poster, air_date, episode_count, episodes_official, updated_at) VALUES (?,?,?,?,?,0,?,?) "
                        "ON CONFLICT(content_id, number) DO UPDATE SET name=COALESCE(excluded.name, season.name), poster=COALESCE(excluded.poster, season.poster), "
                        "air_date=COALESCE(excluded.air_date, season.air_date), episodes_official=excluded.episodes_official, updated_at=excluded.updated_at",
                        (cid, s["season_number"], s.get("name"), _img(s.get("poster_path"), "w342"), s.get("air_date"), s.get("episode_count") or None, now))
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
        con.execute("UPDATE season SET overview_en=COALESCE(?, overview_en), overview_ar=COALESCE(?, overview_ar), episodes_official=?, updated_at=? WHERE content_id=? AND number=?",
                    (d.get("overview") or None, tr.get("overview") or None, len(d.get("episodes") or []) or None, now, cid, s["number"]))
        for ep in d.get("episodes") or []:
            con.execute("INSERT INTO episode(content_id, season, number, title_en, overview_en, air_date, runtime, still, updated_at, source) VALUES (?,?,?,?,?,?,?,?,?,'tmdb') "
                        "ON CONFLICT(content_id, season, number) DO UPDATE SET title_en=COALESCE(excluded.title_en, episode.title_en), "
                        "overview_en=COALESCE(excluded.overview_en, episode.overview_en), air_date=COALESCE(excluded.air_date, episode.air_date), "
                        "runtime=COALESCE(excluded.runtime, episode.runtime), still=COALESCE(excluded.still, episode.still), updated_at=excluded.updated_at, source='tmdb'",
                        (cid, s["number"], ep.get("episode_number"), ep.get("name") or None, ep.get("overview") or None, ep.get("air_date") or None,
                         ep.get("runtime") or None, _img(ep.get("still_path"), "w300"), now))
            n += 1
    return n


# ================= تطبيع هوية كيانٍ واحد بقرار المالك =================
TMDB_FIELDS = ("tmdb_id", "title_en", "title_ar", "original_title", "overview_en", "overview_ar", "release_date", "year", "runtime", "status",
               "tmdb_type", "rating", "votes", "popularity", "last_air_date", "poster", "backdrop", "trailer_yt", "original_language",
               "origin_country_json", "genres_json", "format", "anime_kind", "is_animation", "anime_family", "episodes_official", "seasons_official")


def normalize_identity(data_dir, cid, tmdb_id, now=None):
    """قرار المالك لكيانٍ واحد: معرّف TMDB الذي يحمله جدول المعرّفات **مُتحقَّقًا** يُثبَّت على صفّ الكيان وتُنسخ حقول TMDB من
    مصدرها (التفاصيل والمواسم) — ولا شيء غير ذلك: لا دمج ولا انقسام ولا تبديل رابط ولا تحويل ولا مساس بعضوية السيرفرات ولا
    بكيانٍ آخر. كل ثابتٍ يُقارن قبل وبعد، وأي مخالفة = تراجعٌ كامل (rollback) ورفض. التجميد يبقى. ← QA صغير مكتوب في ملف."""
    now = now or int(time.time())
    cid, tmdb_id = int(cid), int(tmdb_id)
    with seo_db.lock(data_dir):
        con = seo_db.connect(data_dir)
        try:
            st = seo_db.settings(con)
            key = tmdb_key(con, data_dir)
            c = con.execute("SELECT * FROM content WHERE id=?", (cid,)).fetchone()
            if not c:
                return {"ok": False, "error": f"no entity {cid}"}
            if c["merged_into"] is not None:
                return {"ok": False, "error": f"entity {cid} is merged into {c['merged_into']}"}
            ext = seo_db.external(con, "content", cid)
            held = ext.get("tmdb") or {}
            if str(held.get("external_id")) != str(tmdb_id) or not held.get("verified"):
                return {"ok": False, "error": f"id table does not hold tmdb {tmdb_id} verified for entity {cid}", "held": {k: v.get("external_id") for k, v in ext.items()}}
            if not key:
                return {"ok": False, "error": "no TMDB key"}

            def snap():
                paths = seo_db.paths(c["type"], con.execute("SELECT slug FROM content WHERE id=?", (cid,)).fetchone()[0])
                return {"slug": con.execute("SELECT slug FROM content WHERE id=?", (cid,)).fetchone()[0],
                        "merged_into": con.execute("SELECT merged_into FROM content WHERE id=?", (cid,)).fetchone()[0],
                        "canonical": seo_db.PATHS[c["type"]].format(slug=con.execute("SELECT slug FROM content WHERE id=?", (cid,)).fetchone()[0]),
                        "redirects_to": [tuple(r) for r in con.execute(f"SELECT path, target, code FROM redirect WHERE target IN ({','.join('?' * len(paths))}) ORDER BY path", paths)],
                        "redirects_total": con.execute("SELECT COUNT(*) FROM redirect").fetchone()[0],
                        "membership": [tuple(r) for r in con.execute("SELECT service_key, kind, local_key, stream_id, present FROM content_service WHERE content_id=? ORDER BY 1,2,3", (cid,))],
                        "entities": con.execute("SELECT COUNT(*) FROM content").fetchone()[0],
                        "merged_total": con.execute("SELECT COUNT(*) FROM content WHERE merged_into IS NOT NULL").fetchone()[0],
                        "split_reviews": con.execute("SELECT COUNT(*) FROM review WHERE kind='split_entity'").fetchone()[0],
                        "imdb": (seo_db.external(con, "content", cid).get("imdb") or {}).get("external_id")}
            before = snap()
            d = tmdb_details(con, key, c["type"], tmdb_id, st)
            if not d or int(d.get("id") or 0) != tmdb_id:
                return {"ok": False, "error": f"TMDB did not return {tmdb_id}", "tmdb": (d or {}).get("id")}
            apply_tmdb(con, data_dir, cid, d, st, now)
            seasons = 0
            if c["type"] == "series":
                try:
                    seasons = apply_seasons(con, data_dir, cid, st, now)
                except Skip:
                    seasons = 0
            con.execute("UPDATE enrich_queue SET state='done', next_at=0, error=?, updated_at=? WHERE content_id=? AND source IN ('tmdb','tmdb_seasons')",
                        ("owner identity normalization", now, cid))
            after = snap()
            violations = [k for k in ("slug", "merged_into", "canonical", "redirects_to", "redirects_total", "membership", "entities", "merged_total", "split_reviews") if before[k] != after[k]]
            if before["imdb"] and after["imdb"] != before["imdb"]:
                violations.append("imdb")
            if violations:
                con.rollback()
                return {"ok": False, "error": "invariant violated — rolled back", "violations": violations, "before": {k: before[k] for k in violations}, "after": {k: after[k] for k in violations}}
            con.commit()
            row = con.execute("SELECT * FROM content WHERE id=?", (cid,)).fetchone()
            ext2 = seo_db.external(con, "content", cid)
            qa = {"ok": True, "at": now, "entity_id": cid, "tmdb_id": row["tmdb_id"], "imdb_id": (ext2.get("imdb") or {}).get("external_id"), "match": row["match"],
                  "title": row["title"], "title_en": row["title_en"], "title_ar": row["title_ar"], "year": row["year"],
                  "tmdb_fields_populated": [f for f in TMDB_FIELDS if row[f] not in (None, "", 0)], "tmdb_fields_empty": [f for f in TMDB_FIELDS if row[f] in (None, "")],
                  "seasons_episodes_written": seasons, "seasons_official": row["seasons_official"], "episodes_official": row["episodes_official"],
                  "canonical": {"before": before["canonical"], "after": after["canonical"], "unchanged": before["canonical"] == after["canonical"]},
                  "slug": {"before": before["slug"], "after": after["slug"], "unchanged": before["slug"] == after["slug"]},
                  "redirects": {"to_entity_before": len(before["redirects_to"]), "to_entity_after": len(after["redirects_to"]), "total_before": before["redirects_total"], "total_after": after["redirects_total"],
                                "unchanged": before["redirects_to"] == after["redirects_to"] and before["redirects_total"] == after["redirects_total"]},
                  "membership": {"before": before["membership"], "after": after["membership"], "unchanged": before["membership"] == after["membership"]},
                  "merge": after["merged_total"] - before["merged_total"], "split": after["split_reviews"] - before["split_reviews"],
                  "new_redirects": after["redirects_total"] - before["redirects_total"], "entities_delta": after["entities"] - before["entities"],
                  "frozen": cid in frozen_ids(st), "code_fingerprint": code_version()["code_fingerprint"]}
            out = os.path.join(bundle_dir(data_dir), f"normalize-{cid}.json")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                json.dump(qa, f, ensure_ascii=False, indent=1, default=str)
            return qa
        finally:
            con.close()


def normalizations(data_dir):
    """سجلّات التطبيع المكتوبة (normalize-<id>.json) — لتقرير qa.json ولتقدير كتابات TMDB المعتمدة على كيانٍ مجمّد."""
    out = []
    d = bundle_dir(data_dir)
    for n in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if n.startswith("normalize-") and n.endswith(".json"):
            try:
                with open(os.path.join(d, n), encoding="utf-8") as f:
                    out.append(json.load(f))
            except (OSError, ValueError):
                pass
    return out


# ================= Xtream =================
def classify_provider_error(msg):
    """تصنيف خطأ لوحة Xtream/TMDB لتقرير الفحص: من رمز HTTP في الرسالة («xtream 503») أو نصّ الشبكة — ليس فشل مطابقة ولا
    بياناتٍ: لا يُعلَّم محتوًى مفقودًا بسببه، والإثراء يبقي الصفّ pending بتباعده (لا دورة إعادة جماعية)."""
    m = re.search(r"\b(\d{3})\b", msg or "")
    code = int(m.group(1)) if m else None
    if code in (401, 403):
        cls = "authentication"
    elif code == 429:
        cls = "rate_limit"
    elif code and code >= 500:
        cls = "provider_unavailable"
    elif code and code >= 400:
        cls = "client_error"
    elif re.search(r"timed out|timeout|refused|unreachable|name or service|reset|EOF|ssl", msg or "", re.I):
        cls = "network"
    else:
        cls = "unknown"
    return {"class": cls, "http_status": code, "severity": "temporary" if cls in ("provider_unavailable", "rate_limit", "network") else "needs_attention",
            "effect": "blocked for now: no content marked missing or unmatched because of this; enrichment rows keep state pending with backoff; probe is read-only"}


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
    status, body, _ = get_json(con, f"xtream:{base}", f"{base}/player_api.php?{q}", f"xtream:{base}:get_series", st, st.get("xtream_rps", 1),
                               headers={"User-Agent": C.UA}, write=write)
    out = {}
    for o in body or [] if isinstance(body, list) else []:
        nm = M.norm(C._split_year(C._dequal(C._clean(str(o.get("name") or ""))))[0])
        if nm and o.get("series_id"):
            out.setdefault(nm, int(o["series_id"]))
    return out


def _people_xtream(con, cid, info, now):
    if con.execute("SELECT 1 FROM content_person WHERE content_id=? AND source='tmdb'", (cid,)).fetchone():
        return
    old = [r[0] for r in con.execute("SELECT person_id FROM content_person WHERE content_id=? AND source='xtream'", (cid,))]
    con.execute("DELETE FROM content_person WHERE content_id=? AND source='xtream'", (cid,))
    for role, raw in (("actor", info.get("cast") or info.get("actors") or ""), ("director", info.get("director") or "")):
        for i, name in enumerate([x.strip() for x in re.split(r"[,،/]", str(raw)) if x.strip()][:12]):
            # اسمٌ من اللوحة بلا معرّف: صفٌّ لهذا العمل (يُعاد استعماله له وحده)؛ لا يُربط بصفّ اسمٍ مماثل لعملٍ آخر ولا بشخصٍ
            # مُعرَّف في TMDB — التشابه يُراجَع (person_same_name) ولا يُدمج
            key = M.person_key(name)
            r = con.execute(f"SELECT id FROM person WHERE name_norm=? AND id IN ({','.join('?' * len(old)) or '0'}) AND NOT EXISTS "
                            f"(SELECT 1 FROM external_id x WHERE x.entity='person' AND x.entity_id=person.id) LIMIT 1", (key, *old)).fetchone()
            pid = r["id"] if r else con.execute("INSERT INTO person(slug, name, name_norm, created_at, updated_at) VALUES (?,?,?,?,?)",
                                               (_slug_for(con, "person", name), name, key, now, now)).lastrowid
            con.execute("INSERT OR IGNORE INTO content_person(content_id, person_id, role, character, ord, source) VALUES (?,?,?,NULL,?,'xtream')", (cid, pid, role, i))
    con.execute("DELETE FROM person WHERE id NOT IN (SELECT person_id FROM content_person) AND NOT EXISTS (SELECT 1 FROM external_id x WHERE x.entity='person' AND x.entity_id=person.id)")


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
                    con.execute("INSERT INTO episode(content_id, season, number, title_en, overview_en, air_date, runtime, still, updated_at, source) VALUES (?,?,?,?,?,?,?,?,?,'xtream') "
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
    hints = []                                        # (kind, value) — قسمان ببلدين (تركية + سورية) يُحفظان معًا لا آخرهما
    for g in groups:
        for rx, h in rls:
            if rx.search(g):
                hints += [(k, v) for k, v in h.items() if (k, v) not in hints]
    prio = 5
    for k, v in hints:
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


def frozen_ids(st):
    """معرّفات الكيانات المجمّدة (identity_freeze) أثناء مراجعة المالك."""
    return {int(x) for x in (st.get("identity_freeze") or []) if str(x).lstrip("-").isdigit()}


def _one(con, data_dir, cid, source, st, now):
    """عنصرٌ واحد من الطابور ← الحال الجديدة (done · miss · pending) ورسالة. الكيان المجمّد لا يُمسّ (لا TMDB ولا Xtream ولا دمج)."""
    if cid in frozen_ids(st):
        return "miss", "frozen: identity_freeze (no enrichment, no merge, no slug change)"
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
            if owner and owner[0] in frozen_ids(st):    # الحامل مجمّد: لا دمجٌ فيه أثناء المراجعة
                return "miss", f"frozen owner {owner[0]} holds tmdb {d['id']} (identity_freeze): no merge"
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
            holders = {str(r["external_id"]): r["entity_id"] for r in con.execute("SELECT external_id, entity_id FROM external_id WHERE entity='content' AND source='tmdb' AND verified=1")}
            _review(con, f"tmdb_{res}", cid, name, {"state": "unresolved_candidate", "why": "several verified candidates by name; strong evidence (anime hint, season/episode counts) does not separate them" if res == "ambiguous" else "candidate not strong (year/name/origin)",
                                                      "likely": next((c["id"] for c in data if c.get("likely")), None),
                                                      "candidates": [{**{k: c.get(k) for k in ("id", "title", "original_title", "year")}, "evidence": c.get("evidence"), "held_by_entity": holders.get(str(c.get("id")))} for c in data][:5]}, now)
            return "miss", res
        return "miss", "no candidate"
    if source == "tmdb_seasons":
        n = apply_seasons(con, data_dir, cid, st, now)
        return "done", f"{n} episodes"
    return "skip", "unknown source"


def reclassify(con, data_dir, st, limit=500, now=None):
    """أعمالٌ أُثريت بكودٍ أقدم (لا طبقات أنمي في إثباتاتها): تُعاد كتابة حقول TMDB وتصنيفها من **الكاش** (بلا طلبات) حتى لا يبقى
    عملٌ بصفة «أنمي» من قاعدةٍ قديمة أو بندُ نزاعٍ لم يعد قائمًا ← عدد ما أُعيد."""
    now = now or int(time.time())
    key = tmdb_key(con, data_dir)
    if not key:
        return 0
    n = 0
    for r in con.execute("SELECT id, type, tmdb_id FROM content WHERE match='tmdb' AND tmdb_id IS NOT NULL AND merged_into IS NULL AND id NOT IN "
                         "(SELECT entity_id FROM provenance WHERE entity='content' AND field='is_animation') LIMIT ?", (limit,)).fetchall():
        if r["id"] in frozen_ids(st):
            continue
        try:
            d = tmdb_details(con, key, r["type"], r["tmdb_id"], st)
            if d:
                apply_tmdb(con, data_dir, r["id"], d, st, now)
                n += 1
        except Exception:  # noqa: BLE001 — لا يُعطّل الدورة؛ يُعاد في المرة التالية
            con.rollback()
            continue
    # سجلات حلقاتٍ من قبل عمود المصدر: تُعاد حلقات TMDB من الكاش فتُعلَّم tmdb، وما بقي بلا مصدر كتبته اللوحة (الكاتبان الوحيدان)
    for r in con.execute("SELECT DISTINCT content_id FROM episode WHERE source IS NULL LIMIT ?", (limit,)).fetchall():
        try:
            if con.execute("SELECT 1 FROM content WHERE id=? AND tmdb_id IS NOT NULL", (r[0],)).fetchone():
                apply_seasons(con, data_dir, r[0], st, now)
            con.execute("UPDATE episode SET source='xtream' WHERE content_id=? AND source IS NULL", (r[0],))
        except Exception:  # noqa: BLE001
            con.rollback()
            continue
    review_same_names(con, now)
    con.commit()
    return n


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
            res["reclassified"] = reclassify(con, data_dir, st, now=now)
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
            res["same_name_reviews"] = review_same_names(con, now); con.commit()
            _state[os.path.abspath(data_dir)] = {"at": now, **res}
            return res
        finally:
            con.close()


def _step(con, data_dir, r, st, backoff, res, now, failures=None):
    """عنصرٌ من الطابور في معاملته ← هل نتوقّف (مفتاحٌ مرفوض أو 429)؟ وكل فشلٍ يُضاف إلى ‏failures (إن أُعطيت) بمعرّفه
    ومصدره وعمليته ونوع الخطأ ورسالته — فلا يكون ‏run.error > 0 مع قائمةٍ فارغة."""
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
        if failures is not None:
            failures.append({"content_id": cid, "source": source, "operation": "enrich", "error_type": "Skip", "error_message": str(e)[:200]})
        return "مفتاح" in str(e)
    except Exception as e:  # noqa: BLE001 — أي فشلٍ يُسجَّل ويُؤجَّل، ولا يُسقط الدفعة
        att = r["attempts"] + 1
        state = "error" if att > len(backoff) else "pending"
        con.execute("UPDATE enrich_queue SET state=?, attempts=?, next_at=?, error=?, updated_at=? WHERE content_id=? AND source=?",
                    (state, att, now + backoff[min(att, len(backoff)) - 1], f"{type(e).__name__}: {str(e)[:180]}", now, cid, source))
        con.commit()
        res["error"] += 1
        if failures is not None:
            failures.append({"content_id": cid, "source": source, "operation": {"xtream": "panel info", "tmdb": "tmdb resolve/apply", "tmdb_seasons": "tmdb seasons"}.get(source, source),
                             "error_type": type(e).__name__, "error_message": str(e)[:300]})
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
SAMPLE_SPEC = {"movie": 10, "series": 10, "turkish": 5, "anime": 5,
               "titles": ["Prison Break", "One Piece", "ون بيس"]}   # أعمالٌ بأسمائها تُثرى مع العيّنة لإثبات توحيد الهوية بالمعرّف


def _by_title(con, title):
    """كل الكيانات (الحيّة والمدمجة) التي تحمل هذا الاسم alias ← لتقرير توحيد الهوية."""
    return [dict(r) for r in con.execute(
        "SELECT DISTINCT c.id, c.slug, c.title, c.year, c.tmdb_id, c.match, c.merged_into, "
        "(SELECT GROUP_CONCAT(service_key) FROM content_service s WHERE s.content_id=c.id AND s.present=1) services, "
        "(SELECT COUNT(*) FROM season s WHERE s.content_id=c.id) seasons "
        "FROM content c JOIN content_alias a ON a.content_id=c.id WHERE a.alias_norm=? ORDER BY c.id", (M.norm(title),))]


def panel_ids(data_dir):
    """هوية اللوحة لكل سيرفر بلا كشف مضيفها: بصمة قصيرة لمضيف Xtream (أو «m3u-only» لسيرفرٍ بقائمةٍ بلا لوحة)."""
    import hashlib
    out = {}
    for srv in C.servers(data_dir):
        xt = _creds(data_dir, srv["key"])
        out[srv["key"]] = ("panel:" + hashlib.sha1(xt[0].encode("utf-8")).hexdigest()[:8]) if xt else "m3u-only"
    return out


def service_rows(con, cid, panels=None):
    """صفوف المصدر للكيان كما هي (صفٌّ لكل سجلّ قائمة): السيرفر وهوية لوحته ومفتاح السجلّ وأرقام بثّه ومعرّف مسلسله وأقسامه
    وأسماؤه الخام ونسخه ومواسمه — فلا يبدو تعدّد الصفوف لسيرفرٍ واحد تكرارًا عرضيًّا بلا سبب."""
    rows = []
    for r in con.execute("SELECT service_key, kind, local_key, stream_id, stream_ids_json, series_id, groups_json, raw_names_json, versions_json, seasons_json, present, first_seen, seen_at "
                         "FROM content_service WHERE content_id=? ORDER BY service_key, local_key", (cid,)):
        rows.append({"service": r["service_key"], "panel": (panels or {}).get(r["service_key"]), "local_key": r["local_key"], "stream_id": r["stream_id"],
                     "stream_ids": json.loads(r["stream_ids_json"] or "[]"), "series_id": r["series_id"], "sections": json.loads(r["groups_json"] or "[]"),
                     "raw_names": json.loads(r["raw_names_json"] or "[]"), "versions": json.loads(r["versions_json"] or "[]"),
                     "listed_episodes": sum(n for _, n in json.loads(r["seasons_json"] or "[]")), "present": bool(r["present"]), "first_seen": r["first_seen"], "seen_at": r["seen_at"]})
    return rows


def classify_same_service_rows(rows):
    """صفوف سيرفرٍ واحد للكيان نفسه ← لماذا هي صفوفٌ لا صفّ: duplicate_same_streams (أرقام البثّ نفسها: تكرارٌ في الطبقة) ·
    version_variants (نسخٌ مختلفة: مدبلج/مترجم) · different_sections (سجلّان في قسمين: قوائم السيرفر تكرّر العمل) ·
    same_section_distinct_streams (قسمٌ واحد وبثٌّ مختلف: لم يُطويا — مرشّح للطيّ بالسياسة)."""
    by = {}
    for r in rows:
        if r["present"]:
            by.setdefault(r["service"], []).append(r)
    out = {}
    for svc, rs in by.items():
        if len(rs) < 2:
            continue
        a, b = rs[0], rs[1]
        sa, sb = set(a["stream_ids"] or [a["stream_id"]]), set(b["stream_ids"] or [b["stream_id"]])
        if sa & sb:
            out[svc] = "duplicate_same_streams"
        elif set(a["versions"]) != set(b["versions"]) and (a["versions"] or b["versions"]):
            out[svc] = "version_variants"
        elif set(a["sections"]) & set(b["sections"]):
            out[svc] = "same_section_distinct_streams"
        else:
            out[svc] = "different_sections"
    return out


def source_rows_audit(con, panels, examples=10):
    """القاعدة كلها: كيانات لها أكثر من صفٍّ لسيرفرٍ واحد — العدد بالتصنيف وبالسيرفر، وأمثلة بصفوفها كاملة. قراءةٌ صرفة."""
    ids = [r[0] for r in con.execute("SELECT DISTINCT content_id FROM (SELECT content_id FROM content_service WHERE present=1 GROUP BY content_id, service_key HAVING COUNT(*) > 1) ORDER BY content_id")]
    by_class, by_service, ex = {}, {}, []
    for cid in ids:
        rows = service_rows(con, cid, panels)
        cls = classify_same_service_rows(rows)
        for svc, c in cls.items():
            by_class[c] = by_class.get(c, 0) + 1
            by_service[svc] = by_service.get(svc, 0) + 1
        if len(ex) < examples:
            c_ = con.execute("SELECT id, slug, title, tmdb_id FROM content WHERE id=?", (cid,)).fetchone()
            ex.append({"entity": dict(c_), "classes": cls, "rows": [r for r in rows if r["present"]]})
    return {"entities_with_multiple_rows_per_service": len(ids), "by_class": by_class, "by_service": by_service, "examples": ex,
            "definitions": {"duplicate_same_streams": "الصفّان يحملان رقم بثٍّ مشترك: تكرارٌ في طبقة SEO (يُبلَّغ ولا يُصلَح تلقائيًّا)",
                            "version_variants": "نسختان (مدبلج/مترجم…) للعمل نفسه في السيرفر: مقصود",
                            "different_sections": "سجلّان للعمل نفسه في قسمين مختلفين من قوائم السيرفر: صفّان مقصودان لسجلّين حقيقيين",
                            "same_section_distinct_streams": "سجلّان في القسم نفسه ببثٍّ مختلف لم يُطويا: مرشّح للطيّ — يُراجَع"},
            "effects": {"availability_display": "الصفحة تعرض السيرفر مرةً واحدة باتحاد نسخه (لا تكرار)", "versions": "تُجمع من كل الصفوف",
                        "entity_matching": "لا أثر: الهوية بالكيان لا بالصفوف", "sitemap": "لا أثر: رابطٌ واحد للكيان", "seo_rendering": "لا أثر: صفحةٌ واحدة؛ الحلقات المتاحة = أكبر ما في الصفوف لكل موسم"}}


def describe(con, cid, st, panels=None):
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
    links = con.execute("SELECT service_key, versions_json, raw_names_json, groups_json, seasons_json FROM content_service WHERE content_id=? AND present=1", (cid,)).fetchall()
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
            if hub == "anime" and c["is_animation"] and c["anime_family"] is None:
                return {"decision": "unconfirmed", "confidence": "low", "tmdb": None, "section": True, "note": "animation; TMDB gives no origin language/country → taxonomy_unconfirmed"}
            if hub == "anime" and c["is_animation"]:
                return {"decision": "review", "confidence": "low", "tmdb": False, "section": True,
                        "note": "section says anime; TMDB says animation from " + (",".join(json.loads(c["origin_country_json"] or "[]")) or c["original_language"] or "?") + " (not anime family) → taxonomy_mismatch (no anime attribute)"}
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
            codes = [c_ for c_, _ in res[1]["alts"]]
            page[lang] = {"seo_title": res[1]["title"], "meta_description": res[1]["desc"], "canonical": res[1]["canonical"],
                          "hreflang": [{"lang": c_, "url": u} for c_, u in res[1]["alts"]],
                          "hreflang_ok": len(codes) == len(set(codes)) and set(codes) <= {"ar", "en", "x-default"}
                          and dict(res[1]["alts"]).get("x-default") == dict(res[1]["alts"]).get("ar"),   # x-default = النسخة الافتراضية (العربية بلا بادئة)
                          "json_ld": re.findall(r'"@type": "(\w+)"', html)[:6],
                          "would_index": res[1]["index_ar" if lang == "ar" else "index_en"], "why": res[1]["why"][0 if lang == "ar" else 1]}
    raw_all = [r for ln in links for r in json.loads(ln["raw_names_json"] or "[]")]
    cleans = [M.clean_title(r, st) for r in raw_all] or [M.clean_title(c["title"], st)]
    clean = {"raw": raw_all, "base": c["title"], "seasons_from_names": sorted({x["season"] for x in cleans if x["season"]}),
             "originals": sorted({x["original"] for x in cleans if x["original"]}), "versions": sorted({v for x in cleans for v in x["versions"]}),
             "cleaned": any(x["cleaned"] for x in cleans)}
    enrich = {r["source"]: {"state": r["state"], "message": r["error"], "attempts": r["attempts"]}
              for r in con.execute("SELECT source, state, error, attempts FROM enrich_queue WHERE content_id=?", (cid,))}
    slug_prev = con.execute("SELECT prev FROM provenance WHERE entity='content' AND entity_id=? AND field='slug' AND prev IS NOT NULL", (cid,)).fetchone()
    return {"id": cid, "slug": c["slug"], "slug_prev": json.loads(slug_prev[0]) if slug_prev else None, "merged_into": c["merged_into"],
            "type": c["type"], "match": c["match"], "tmdb_id": c["tmdb_id"], "clean": clean, "enrich": enrich,
            "tmdb_candidate": {k: v for k, v in (ext.get("tmdb") or {}).items() if k in ("external_id", "verified", "how")} or None,
            "title": c["title"], "title_ar": c["title_ar"], "title_en": c["title_en"], "original_title": c["original_title"],
            "country": json.loads(c["origin_country_json"]) if c["origin_country_json"] else None, "language": c["original_language"],
            "genres": json.loads(c["genres_json"]) if c["genres_json"] else None, "director": people.get("director") or people.get("creator"),
            "cast": (people.get("actor") or people.get("voice") or [])[:6], "poster": bool(c["poster"]), "backdrop": bool(c["backdrop"]),
            "special_season_count": con.execute("SELECT COUNT(*) FROM season WHERE content_id=? AND number=0", (cid,)).fetchone()[0],   # الموسم 0 وحده؛ عدّ المواسم في episodes.*
            "episodes_detailed": con.execute("SELECT COUNT(*) FROM episode WHERE content_id=?", (cid,)).fetchone()[0],
            "format": c["format"] or None, "anime_kind": c["anime_kind"], "is_animation": bool(c["is_animation"]), "anime_family": c["anime_family"],
            "resolution_state": resolution_state(con, cid, c),
            "episodes": episode_counts(con, cid, c, links),
            "disputed": sorted(disputed),
            "turkish": classify("turkish"), "anime": classify("anime"),
            "aliases": [r[0] for r in con.execute("SELECT alias FROM content_alias WHERE content_id=?", (cid,))],
            "versions": {r["service_key"]: json.loads(r["versions_json"]) for r in links if r["versions_json"]},
            "raw_names": {r["service_key"]: json.loads(r["raw_names_json"]) for r in links if r["raw_names_json"]},
            "sections": {r["service_key"]: json.loads(r["groups_json"]) for r in links if r["groups_json"]},
            "service_rows": service_rows(con, cid, panels), "same_service_rows": classify_same_service_rows(service_rows(con, cid, panels)),
            "relations": relations(con, cid, st), "provenance": {k: v[0] for k, v in pv.items()}, "reviews": reviews, "page": page}


def splits_report(con, since):
    """الانقسامات منذ اللقطة السابقة: كم، ومتى (باليوم)، وعلى أي سيرفر، ولماذا (contradiction: سنتان/معرّفان مختلفان ·
    conflict: قصتان مختلفتان · no_evidence: غاب الدليل الذي كان يجمعهما · legacy: بندٌ من قبل تسجيل السبب)، وهل مسّت URL
    (لا: الانقسام كيانٌ جديد برابطٍ جديد والأصل يحتفظ برابطه)، وعشرة أمثلة: الأصل ← الجديد."""
    rows = con.execute("SELECT key, payload_json, created_at FROM review WHERE kind='split_entity' AND created_at>? ORDER BY created_at DESC", (since,)).fetchall()
    by_cause, by_service, by_day, examples = {}, {}, {}, []
    for r in rows:
        p = json.loads(r["payload_json"])
        cause = ",".join(p.get("cause") or ["legacy"])
        by_cause[cause] = by_cause.get(cause, 0) + 1
        for s in p.get("services") or sorted({i.get("service") for i in p.get("items") or [] if i.get("service")}):
            by_service[s] = by_service.get(s, 0) + 1
        day = time.strftime("%Y-%m-%d", time.gmtime(r["created_at"]))
        by_day[day] = by_day.get(day, 0) + 1
    for r in rows[:10]:
        p = json.loads(r["payload_json"])
        cid = int(r["key"].split(":")[1])
        new = con.execute("SELECT id, slug, title, year, tmdb_id, merged_into FROM content WHERE id=?", (cid,)).fetchone()
        origins = p.get("from") or []
        if not origins and new:                         # بندٌ قديم بلا «from»: الأصل المحتمل = كيانٌ حيّ بالاسم نفسه على سيرفرٍ آخر
            origins = [x[0] for x in con.execute("SELECT DISTINCT c.id FROM content c JOIN content_alias a ON a.content_id=c.id WHERE a.alias_norm=? AND c.id!=? AND c.merged_into IS NULL LIMIT 3", (M.norm(new["title"]), cid))]
        olds = [dict(con.execute("SELECT id, slug, title, year, tmdb_id FROM content WHERE id=?", (o,)).fetchone() or {"id": o}) for o in origins]
        final = dict(new) if new else {"id": cid}
        hops = 0
        while final.get("merged_into") and hops < 10:                   # الكيان النهائي بعد الدمج (إن دُمج الجديد لاحقًا بالمعرّف)
            final = dict(con.execute("SELECT id, slug, title, year, tmdb_id, merged_into FROM content WHERE id=?", (final["merged_into"],)).fetchone()); hops += 1
        typ = con.execute("SELECT type FROM content WHERE id=?", (cid,)).fetchone()
        new_path = seo_db.PATHS[typ["type"]].format(slug=new["slug"]) if new and typ else None
        red = con.execute("SELECT target FROM redirect WHERE path=?", (new_path,)).fetchone() if new_path else None
        final_path = seo_db.PATHS[typ["type"]].format(slug=final["slug"]) if typ and final.get("slug") else None
        examples.append({"old_entity": olds, "new_entity": dict(new) if new else {"id": cid}, "final_entity": {k: final.get(k) for k in ("id", "slug", "tmdb_id")},
                         "reason": p.get("cause") or ["legacy (cause not recorded)"], "pair": p.get("pair"), "services": p.get("services"),
                         "old_slug": [o.get("slug") for o in olds], "new_slug": new["slug"] if new else None, "final_slug": final.get("slug"),
                         "old_url_changed": False, "redirect": {"from": new_path, "to": red["target"], "direct_to_final": red["target"] == final_path,
                                                                "chain": bool(con.execute("SELECT 1 FROM redirect WHERE path=?", (red["target"],)).fetchone())} if red else None,
                         "canonical": final_path, "note": "split = new entity with a new URL; the origin keeps its URL; if the new one is later merged by verified id its URL redirects to the final canonical"})
    return {"total": len(rows), "by_cause": by_cause, "by_service": by_service, "by_day": by_day, "examples": examples,
            "url_changes": 0, "redirects_created": 0}


def slug_changes_report(con, since):
    """كل تبديل slug منذ اللقطة: الكيان، القديم، الجديد، هدف التحويل، وهل هو مباشر (القديم ← النهائي بلا سلسلة)."""
    out = []
    for r in con.execute("SELECT entity_id, prev, at, source FROM provenance WHERE entity='content' AND field='slug' AND prev IS NOT NULL AND at>?", (since,)):
        c = con.execute("SELECT id, type, slug, title FROM content WHERE id=?", (r["entity_id"],)).fetchone()
        old = json.loads(r["prev"])
        old_path = seo_db.PATHS[c["type"]].format(slug=old)
        red = con.execute("SELECT target FROM redirect WHERE path=?", (old_path,)).fetchone()
        final = seo_db.PATHS[c["type"]].format(slug=c["slug"])
        out.append({"entity_id": c["id"], "title": c["title"], "old_slug": old, "new_slug": c["slug"], "source": r["source"], "redirect_target": red["target"] if red else None,
                    "direct": bool(red and red["target"] == final), "chain": bool(red and con.execute("SELECT 1 FROM redirect WHERE path=?", (red["target"],)).fetchone())})
    return out


def episode_counts(con, cid, c, links):
    """حقول العدّ منفصلةً نهائيًّا — ولا يتحوّل مشتقٌّ إلى رسمي:
    official_* من TMDB وحده · available_* من قوائم M3U (أكبر ما في السيرفرات؛ الموسم 0 لا يُعدّ موسمًا) · service_* لكل سيرفر ·
    episode_record_count سجلات جدول الحلقات بمصدرها · special_episode_count حلقات الموسم 0."""
    per_service = {r["service_key"]: {int(s): n for s, n in json.loads(r["seasons_json"] or "[]")} for r in links if r["seasons_json"]}
    by_season = {}
    for d in per_service.values():
        for s, n in d.items():
            by_season[s] = max(by_season.get(s, 0), n)
    by_source = {r[0] or "unknown": r[1] for r in con.execute("SELECT source, COUNT(*) FROM episode WHERE content_id=? GROUP BY source", (cid,))}
    return {"official_episode_count": c["episodes_official"], "official_season_count": c["seasons_official"],
            "available_episode_count": sum(n for s, n in by_season.items() if s > 0), "available_season_count": len([s for s in by_season if s > 0]),
            "available_source": "m3u listing (max per season across services)", "service_episode_count": {k: sum(v.values()) for k, v in per_service.items()},
            "season_episode_count": {str(s): {"official": r[0], "available": by_season.get(s, 0)} for s, r in
                                     ((x[0], (x[1],)) for x in con.execute("SELECT number, episodes_official FROM season WHERE content_id=? ORDER BY number", (cid,)))},
            "episode_record_count": sum(by_source.values()), "episode_records_by_source": by_source,
            "special_episode_count": con.execute("SELECT COUNT(*) FROM episode WHERE content_id=? AND season=0", (cid,)).fetchone()[0],
            "seo_uses": "official" if c["episodes_official"] else "available (labelled 'listed')"}


def resolution_state(con, cid, c):
    """verified (معرّف TMDB مُتحقَّق) · unresolved_candidate (مرشّحون بلا حسم: بند tmdb_ambiguous/weak بأدلّته والأرجح ومن يحمل كل معرّف) ·
    unmatched (لا مرشّح) — ولا يُفهرس إلا verified."""
    if c["match"] == "tmdb" and c["tmdb_id"]:
        return {"state": "verified", "tmdb_id": c["tmdb_id"]}
    r = con.execute("SELECT kind, payload_json FROM review WHERE status='open' AND kind IN ('tmdb_ambiguous','tmdb_weak') AND key IN (?, ?)",
                    (f"tmdb_ambiguous:{cid}", f"tmdb_weak:{cid}")).fetchone()
    if r:
        p = json.loads(r["payload_json"])
        cands = p.get("candidates") or []
        for cnd in cands:                              # من يحمل كل معرّف **الآن** (قد يُثرى كيانٌ آخر بعد كتابة البند)
            h = con.execute("SELECT entity_id FROM external_id WHERE entity='content' AND source='tmdb' AND verified=1 AND external_id=?", (str(cnd.get("id")),)).fetchone()
            cnd["held_by_entity"] = h["entity_id"] if h else None
        return {"state": "unresolved_candidate", "kind": r["kind"], "why": p.get("why"), "likely": p.get("likely"), "candidates": cands, "indexable": False}
    return {"state": "unmatched", "indexable": False}


def people_pages_qa(con, st, n=3):
    """صفحات الأشخاص والشركات على البيانات الحقيقية: لكل فئة (ممثل · مخرج · كاتب · شركة) عيّنةٌ ممّن له عملان فأكثر — تُرسم
    باللغتين ويُفحص: الأعمال تظهر وتُربط، canonical، hreflang، Breadcrumb وPerson/Organization، الترقيم إن لزم، noindex."""
    import seo_pages
    out = []
    size = max(1, int(st.get("page_size", 60)))
    groups = (("actors", "actor", "voice"), ("directors", "director"), ("writers", "writer", "screenwriter", "creator"))
    picks = []
    for g in groups:
        qs = ",".join("?" * (len(g) - 1))
        for r in con.execute(f"SELECT p.slug, p.name, COUNT(DISTINCT cp.content_id) n FROM person p JOIN content_person cp ON cp.person_id=p.id JOIN content c ON c.id=cp.content_id "
                             f"WHERE cp.role IN ({qs}) AND c.merged_into IS NULL AND c.available=1 GROUP BY p.id ORDER BY n DESC, p.id LIMIT ?", (*g[1:], n)):
            picks.append(("person", g[0], r["slug"], r["name"], r["n"]))
    for r in con.execute("SELECT co.slug, co.name, COUNT(DISTINCT cc.content_id) n FROM company co JOIN content_company cc ON cc.company_id=co.id JOIN content c ON c.id=cc.content_id "
                         "WHERE c.merged_into IS NULL AND c.available=1 GROUP BY co.id ORDER BY n DESC, co.id LIMIT ?", (n,)):
        picks.append(("company", "companies", r["slug"], r["name"], r["n"]))
    for kind, path, slug, name, works in picks:
        row = {"kind": kind, "path": path, "name": name, "works": works, "checks": {}}
        for lang in ("ar", "en"):
            tr = __import__("content_page").lang_of(lang)
            res = seo_pages.render_person(con, "", path, slug, tr, st) if kind == "person" else seo_pages.render_company(con, "", slug, tr, st)
            if not res:
                row["checks"][lang] = {"renders": False}
                continue
            html = res[1]["html"].decode("utf-8")
            prefix = "/en" if lang == "en" else ""
            row["checks"][lang] = {"renders": True, "works_on_page": res[1]["works"], "links_to_works": html.count(prefix + "/content/movies/") + html.count(prefix + "/content/series/") > 0,
                                   "canonical": res[1]["canonical"], "hreflang": len(res[1]["alts"]), "breadcrumb": '"BreadcrumbList"' in html,
                                   "schema": "Person" if '"@type": "Person"' in html else "Organization" if '"@type": "Organization"' in html else None,
                                   "pages": res[1]["pages"], "paginated_ok": res[1]["pages"] == max(1, -(-res[1]["works"] // size)),
                                   "noindex": "noindex" in html, "would_index": res[1]["index_ar" if lang == "ar" else "index_en"], "why": res[1]["why"][0]}
        out.append(row)
    return out


def relations(con, cid, st):
    """علاقات العمل الحقيقية في القاعدة (لا نصوصًا في JSON): الممثلون والمخرجون والكتّاب (بأدوارهم) والشركات — لكلٍّ معرّفه
    ومصدره وعدد أعماله الأخرى ومسار صفحته وهل تُعرض (ويُفحص أنها تُرسم فعلًا)."""
    import seo_pages
    out = {"actors": [], "directors": [], "writers": [], "companies": []}
    groups = {"actor": "actors", "voice": "actors", "director": "directors", "writer": "writers", "screenwriter": "writers", "creator": "writers"}
    for r in con.execute("SELECT p.id, p.slug, p.name, cp.role, cp.source, (SELECT COUNT(DISTINCT content_id) FROM content_person WHERE person_id=p.id) works, "
                         "(SELECT external_id FROM external_id x WHERE x.entity='person' AND x.entity_id=p.id AND x.source='tmdb') tmdb "
                         "FROM content_person cp JOIN person p ON p.id=cp.person_id WHERE cp.content_id=? ORDER BY cp.role, cp.ord", (cid,)):
        g = groups.get(r["role"])
        if g and len(out[g]) < 4:
            res = seo_pages.render_person(con, "", seo_pages.PERSON_PATH[r["role"]], r["slug"], __import__("content_page").lang_of("ar"), st)
            out[g].append({"person_id": r["id"], "name": r["name"], "role": r["role"], "source": r["source"], "tmdb": r["tmdb"], "works": r["works"],
                           "page": seo_pages._person_path(r["role"], r["slug"], "ar"), "renders": bool(res), "would_index": bool(res and res[1]["index_ar"])})
    for r in con.execute("SELECT co.id, co.slug, co.name, co.kind, co.logo, co.country, cc.role, (SELECT COUNT(DISTINCT content_id) FROM content_company WHERE company_id=co.id) works "
                         "FROM content_company cc JOIN company co ON co.id=cc.company_id WHERE cc.content_id=?", (cid,)):
        res = seo_pages.render_company(con, "", r["slug"], __import__("content_page").lang_of("ar"), st)
        out["companies"].append({"company_id": r["id"], "name": r["name"], "role": r["role"], "logo": bool(r["logo"]), "country": r["country"], "works": r["works"],
                                 "page": seo_pages._company_path(r["slug"], "ar"), "renders": bool(res), "would_index": bool(res and res[1]["index_ar"])})
    return out


def people_qa(con, st):
    """شبكة الأشخاص والشركات في القاعدة كلها: الأعداد بالأدوار، التوحيد (أشخاصٌ بمفتاح اسمٍ واحد صفًّا واحدًا)، ومن له معرّف TMDB."""
    q = lambda sql, *a: con.execute(sql, a).fetchone()[0]   # noqa: E731
    dup = q("SELECT COUNT(*) FROM (SELECT name_norm FROM person WHERE name_norm IS NOT NULL GROUP BY name_norm HAVING COUNT(*) > 1 "
            "AND COUNT(*) > (SELECT COUNT(DISTINCT x.external_id) FROM external_id x JOIN person p2 ON p2.id=x.entity_id WHERE x.entity='person' AND x.source='tmdb' AND p2.name_norm=person.name_norm))")
    return {"persons": q("SELECT COUNT(*) FROM person"), "with_tmdb_id": q("SELECT COUNT(*) FROM external_id WHERE entity='person' AND source='tmdb'"),
            "by_role": {r[0]: r[1] for r in con.execute("SELECT role, COUNT(*) FROM content_person GROUP BY role")},
            "by_source": {r[0]: r[1] for r in con.execute("SELECT source, COUNT(*) FROM content_person GROUP BY source")},
            "same_name_rows_without_distinct_tmdb_ids": dup,      # تشابه أسماءٍ بلا معرّفات مميِّزة: بنود person_same_name — لا دمج تلقائي
            "same_name_reviews_open": q("SELECT COUNT(*) FROM review WHERE kind='person_same_name' AND status='open'"),
            "companies": q("SELECT COUNT(*) FROM company"), "company_links": q("SELECT COUNT(*) FROM content_company"),
            "companies_by_kind": {r[0]: r[1] for r in con.execute("SELECT kind, COUNT(*) FROM company GROUP BY kind")},
            "persons_with_2plus_works": q("SELECT COUNT(*) FROM (SELECT person_id FROM content_person GROUP BY person_id HAVING COUNT(DISTINCT content_id) >= 2)"),
            "companies_with_2plus_works": q("SELECT COUNT(*) FROM (SELECT company_id FROM content_company GROUP BY company_id HAVING COUNT(DISTINCT content_id) >= 2)")}


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
    for n in ("seo_db.py", "seo_match.py", "seo_build.py", "seo_search.py", "seo_sources.py", "seo_pages.py", "seo_qa.py", "seo_scan.py", "content.py"):
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
                        rep[kind] = {"error": _scrub(str(e), secrets(data_dir)), **classify_provider_error(str(e))}
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


def _tally(works, hub):
    out = {"confirmed": 0, "tmdb_only": 0, "review": 0, "unconfirmed": 0, "none": 0}
    for w in works:
        c = w.get(hub)
        if not c:
            out["none"] += 1
        elif c["note"] == "confirmed":
            out["confirmed"] += 1
        elif c["note"] == "tmdb only":
            out["tmdb_only"] += 1
        else:
            out[c["decision"] if c["decision"] in out else "review"] += 1
    return out


def sample(data_dir, spec=None, now=None, bundle_errors=None):
    """يختار عيّنةً من القاعدة الحقيقية (10 أفلام · 10 مسلسلات · 5 بقرينة تركي · 5 بقرينة أنمي، الأحدث إضافةً)، يثريها
    وحدها الآن (Xtream ← TMDB ← المواسم) ← تقريرٌ لكل عمل بكل الحقول وحالات التصنيف، وعدّادات العيّنة **مفصولةً** عن
    أخطاء الطابور السابقة وعن أخطاء اللقطة، وأداء الواجهات، وما تغيّر من هويات منذ اللقطة السابقة."""
    now = int(now or time.time())
    spec = {**SAMPLE_SPEC, **(spec or {})}
    with seo_db.lock(data_dir):
        con = seo_db.connect(data_dir)
        try:
            st = seo_db.settings(con)
            with _lock:
                _metrics.clear()                      # أداء هذه العيّنة وحدها
            prev_at = seo_db.state(con, "bundle_at") or 0
            picked, seen = [], set()

            def take(label, sql, args, n):
                for r in con.execute(sql + " ORDER BY COALESCE(c.last_seen,0) DESC, c.id DESC LIMIT ?", (*args, n * 3)):
                    if r["id"] not in seen and len([p for p in picked if p[1] == label]) < n:
                        seen.add(r["id"]); picked.append((r["id"], label))
            fz = ",".join(str(i) for i in frozen_ids(st)) or "0"
            base = f"SELECT c.id FROM content c WHERE c.merged_into IS NULL AND c.available=1 AND c.id NOT IN ({fz})"   # المجمّد لا يدخل العيّنة (لا إثراء)
            hub = " AND c.id IN (SELECT ct.content_id FROM content_taxonomy ct JOIN taxonomy t ON t.id=ct.taxonomy_id WHERE t.kind='hub' AND t.key=?)"
            resolution = {}
            for t in spec.get("titles") or []:
                before = _by_title(con, t)
                resolution[t] = {"before": before}
                for r in before:
                    if r["merged_into"] is None and r["id"] not in seen and r["id"] not in frozen_ids(st):
                        seen.add(r["id"]); picked.append((r["id"], "title"))
            take("turkish", base + hub, ("turkish",), spec["turkish"])
            take("anime", base + hub, ("anime",), spec["anime"])
            take("movie", base + " AND c.type='movie'", (), spec["movie"])
            take("series", base + " AND c.type='series'", (), spec["series"])
            ids = [i for i, _ in picked]
            qs = ",".join("?" * len(ids)) or "0"
            backoff = st.get("enrich_backoff") or [3600, 86400, 604800]
            pre_rows = con.execute(f"SELECT content_id, source, attempts, state, error, updated_at, next_at FROM enrich_queue WHERE error IS NOT NULL AND error LIKE '%Error%' AND content_id NOT IN ({qs}) ORDER BY updated_at", ids).fetchall()
            pre = {"count": len(pre_rows),
                   "by_error": [dict(r) for r in con.execute(f"SELECT source, error, COUNT(*) n FROM enrich_queue WHERE error IS NOT NULL AND error LIKE '%Error%' "
                                                            f"AND content_id NOT IN ({qs}) GROUP BY 1, 2 ORDER BY n DESC LIMIT 10", ids)],
                   "by_state": {k: sum(1 for r in pre_rows if r["state"] == k) for k in ("pending", "error")},
                   "recorded_between": [time.strftime("%Y-%m-%d %H:%M", time.gmtime(pre_rows[0]["updated_at"])), time.strftime("%Y-%m-%d %H:%M", time.gmtime(pre_rows[-1]["updated_at"]))] if pre_rows else None,
                   "code_fix_note": "get_json() missing 'rps': raised by the old seo_sources._series_map (fixed 2 Oct, PR 165); every current get_json call passes rps; rows keep the old text until their backoff retry",
                   "retry_probe": []}
            probe_res = {"processed": 0, "done": 0, "miss": 0, "error": 0, "skipped": 0}
            for r in pre_rows[:3]:                     # ثلاثة من الصفوف القديمة تُعاد الآن بالكود الحالي: هل يزول الخطأ؟
                before = r["error"]
                con.execute("UPDATE enrich_queue SET state='pending', next_at=0 WHERE content_id=? AND source=?", (r["content_id"], r["source"]))
                row = con.execute("SELECT content_id, source, attempts FROM enrich_queue WHERE content_id=? AND source=?", (r["content_id"], r["source"])).fetchone()
                err, fl = None, []
                try:
                    _step(con, data_dir, row, st, backoff, probe_res, now, fl)
                except Exception as ex:  # noqa: BLE001
                    con.rollback(); err = f"{type(ex).__name__}: {str(ex)[:200]}"
                after = con.execute("SELECT state, error FROM enrich_queue WHERE content_id=? AND source=?", (r["content_id"], r["source"])).fetchone()
                pre["retry_probe"].append({"content_id": r["content_id"], "source": r["source"], "before": before, "after_state": after["state"], "after_message": after["error"],
                                           "probe_error": err, "failures": fl})
            con.commit()
            backoff = st.get("enrich_backoff") or [3600, 86400, 604800]
            res = {"processed": 0, "done": 0, "miss": 0, "error": 0, "skipped": 0}
            res["reclassified"] = reclassify(con, data_dir, st, now=now)      # ما أُثري بكودٍ أقدم: تصنيفه يُعاد من الكاش
            failures = []
            stage_ = _bundle_stage.get(os.path.abspath(data_dir))
            for wi, cid in enumerate(ids):
                if stage_:
                    stage_("sample", wi, len(ids))
                try:                                  # فشل عملٍ لا يُسقط العيّنة: يُسجَّل ويُكمَل
                    enqueue(con, cid, ["xtream", "tmdb"], 0, now)
                    con.execute("UPDATE enrich_queue SET state='pending', next_at=0 WHERE content_id=? AND state IN ('miss','error')", (cid,))
                    con.commit()
                    for source in ("xtream", "tmdb", "tmdb_seasons"):
                        r = con.execute("SELECT content_id, source, attempts FROM enrich_queue WHERE content_id=? AND source=? AND state='pending'", (cid, source)).fetchone()
                        if r and _step(con, data_dir, r, st, backoff, res, now, failures):
                            break
                except Exception as ex:  # noqa: BLE001
                    con.rollback()
                    res["error"] += 1
                    failures.append({"content_id": cid, "source": "sample", "operation": "queue", "error_type": type(ex).__name__, "error_message": str(ex)[:300]})
            if res["error"] and not failures:          # لا يُسمح بـ error > 0 مع قائمةٍ فارغة
                failures.append({"content_id": None, "source": "sample", "operation": "accounting", "error_type": "Unknown", "error_message": "errors counted without detail"})
            for t, r in resolution.items():
                before_ids = [x["id"] for x in r["before"]]
                after = _by_title(con, t) + [dict(x) for x in con.execute(      # المدمج فقد أسماءه (انتقلت إلى الباقي): يُتابَع بمعرّفه
                    f"SELECT id, slug, title, year, tmdb_id, match, merged_into, NULL services, 0 seasons FROM content WHERE merged_into IS NOT NULL AND id IN ({','.join('?' * len(before_ids)) or '0'})", before_ids)]
                live = [x for x in after if x["merged_into"] is None]
                r.update({"after": after, "live_entities": len(live),
                          "merged": [{"id": x["id"], "into": x["merged_into"]} for x in after if x["merged_into"] is not None],
                          "verdict": ("one entity per tmdb id" if len({x["tmdb_id"] for x in live if x["tmdb_id"]}) == len(live) and all(x["tmdb_id"] for x in live)
                                      else "still separate: " + ", ".join(f"{x['id']}:{x['match']}" for x in live if not x["tmdb_id"]))})
            panels = panel_ids(data_dir)
            works = []
            for cid in ids:
                try:
                    works.append(describe(con, cid, st, panels))
                except Exception as ex:  # noqa: BLE001
                    works.append({"id": cid, "error": f"{type(ex).__name__}: {str(ex)[:200]}"})
            review_same_names(con, now); con.commit()
            cleaned = [w for w in works if (w.get("clean") or {}).get("cleaned")]
            counters = {
                "cleaned_names": len(cleaned),
                "tmdb_after_clean": sum(1 for w in cleaned if w.get("match") == "tmdb"),
                "tmdb_matched": sum(1 for w in works if w.get("match") == "tmdb"),
                "turkish": _tally(works, "turkish"), "anime": _tally(works, "anime"),
            }
            builds = [b for b in (seo_db.state(con, "reconciliations") or []) if b.get("at", 0) > prev_at]
            ident = {"definitions": {
                         "split_reviews_opened_since_last_bundle": "عدد بنود split_entity التي فُتحت منذ اللقطة السابقة — عبر **كل** البناءات بينهما (بناءٌ كل عشر دقائق عند تغيّر فهرس)، لا آخر بناء وحده",
                         "builds_since_last_bundle": "تسوية كل بناءٍ منذ اللقطة السابقة (قبل/بعد/جديد/انفصال/مدمج/غاب)؛ مجموع «انفصال» فيها = بنود الانقسام الجديدة",
                         "reconciliation": "آخر بناءٍ وحده"},
                     "builds_since_last_bundle": builds,
                     "split_sum_over_builds": sum(b.get("split", 0) for b in builds),
                     "splits": splits_report(con, prev_at), "slug_changes": slug_changes_report(con, prev_at),
                     "redirect_chains": con.execute("SELECT COUNT(*) FROM redirect a JOIN redirect b ON b.path=a.target").fetchone()[0],   # يجب أن يكون صفرًا: القديم ← النهائي مباشرة
                     "redirects_added": [{"from": r["path"], "to": r["target"], "code": r["code"], "reason": r["reason"],
                                          "direct_to_final": not con.execute("SELECT 1 FROM redirect WHERE path=?", (r["target"],)).fetchone()
                                          and bool(con.execute("SELECT 1 FROM content WHERE merged_into IS NULL AND (? LIKE '%/' || slug || '/')", (r["target"],)).fetchone()),
                                          "chain": bool(con.execute("SELECT 1 FROM redirect WHERE path=?", (r["target"],)).fetchone())}
                                         for r in con.execute("SELECT path, target, code, reason FROM redirect WHERE created_at>? ORDER BY created_at, path", (prev_at,))],
                     "stream_id_reused_last_build": (seo_db.state(con, "reconciliation") or {}).get("stream_id_reused"),
                     "merged_since_last_bundle": con.execute("SELECT COUNT(*) FROM review WHERE kind='merged_entities' AND created_at>?", (prev_at,)).fetchone()[0],
                     "split_reviews_opened_since_last_bundle": con.execute("SELECT COUNT(*) FROM review WHERE kind='split_entity' AND created_at>?", (prev_at,)).fetchone()[0],
                     "slug_changed_since_last_bundle": con.execute("SELECT COUNT(*) FROM provenance WHERE entity='content' AND field='slug' AND prev IS NOT NULL AND at>?", (prev_at,)).fetchone()[0],
                     "redirects_added_since_last_bundle": con.execute("SELECT COUNT(*) FROM redirect WHERE created_at>?", (prev_at,)).fetchone()[0],
                     "in_sample": [{"id": w["id"], "slug": w.get("slug"), "merged_into": w.get("merged_into")} for w in works if w.get("merged_into") or (w.get("slug_prev"))]}
            seo_db.set_state(con, "bundle_at", now); con.commit()
            return {"ok": True, "at": now, "ids": ids, "run": res, "failures": failures, "reconciliation": seo_db.state(con, "reconciliation"),
                    "resolution": resolution, "people": people_qa(con, st), "people_pages": people_pages_qa(con, st),
                    "source_rows": source_rows_audit(con, panels),
                    "errors": {"sample": failures, "queue_preexisting": pre, "bundle": list(bundle_errors or [])},
                    "counters": counters, "identity_changes": ident, "works": works, "summary": summary(con), "api": metrics()}
        finally:
            con.close()


def bundle(data_dir, out, n=20):
    """لقطةٌ للمراجعة: probe وreport وsearch-report وqa (الفحص النهائي بخريطةٍ تجريبية) **قراءةٌ صرفة**؛ وsample وحده يثري أعماله الثلاثين. كل ملفٍ مختومٌ بالوقت
    ونسخة الكود، ومنقًّى من المفتاح وبيانات اللوحات. فشل جزءٍ لا يمنع كتابة الباقي (يُكتب خطؤه مكانه)."""
    import contextlib
    import io
    import seo_build
    import traceback
    os.makedirs(out, exist_ok=True)
    secs = secrets(data_dir)
    stamp = meta(data_dir)
    stamp["bundle_id"] = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())      # معرّف اللقطة الواحد في الملفات الأربعة
    written = {}
    bundle_errors = []
    bk = os.path.abspath(data_dir) + ":bundle"
    def stage(name, done=0, total=0):
        _state[bk] = {**(_state.get(bk) or {}), "running": True, "stage": name, "done": done, "total": total, "elapsed": int(time.time() - (_state.get(bk) or {}).get("at", time.time()))}
    _bundle_stage[os.path.abspath(data_dir)] = stage
    for name in BUNDLE_FILES:                      # أولًا: لا يبقى ملفٌ من لقطةٍ سابقة — كلٌّ يُستبدل بختم هذه اللقطة ولو فشل جزءٌ لاحقًا
        with open(os.path.join(out, name), "w", encoding="utf-8") as f:
            f.write(("# " if name.endswith(".txt") else "") + json.dumps({**stamp, "status": "not generated yet (bundle in progress or aborted)"}, ensure_ascii=False) + "\n")
    for name in BUNDLE_EXTRA + tuple(n for n in os.listdir(out) if _ZIP_RX.fullmatch(n)):   # ولا أرشيف لقطةٍ سابقة
        try:
            os.remove(os.path.join(out, name))
        except OSError:
            pass
    probe_result = {}

    def dump_json(name, fn):
        try:
            data = fn()
            text = json.dumps({"meta": stamp, **data} if isinstance(data, dict) else {"meta": stamp, "data": data}, ensure_ascii=False, indent=1, default=str)
        except Exception as ex:  # noqa: BLE001
            err = f"{type(ex).__name__}: {str(ex)[:300]}"
            bundle_errors.append({"file": name, "error": err, "traceback": traceback.format_exc()[-1500:]})
            text = json.dumps({"meta": stamp, "error": err, "traceback": traceback.format_exc()[-1500:]}, ensure_ascii=False, indent=1)
        text = _scrub(text, secs)
        with open(os.path.join(out, name), "w", encoding="utf-8") as f:
            f.write(text)
        written[name] = len(text)

    def dump_text(name, fn):
        try:
            text = fn()
        except Exception as ex:  # noqa: BLE001
            text = f"error: {type(ex).__name__}: {str(ex)[:300]}\n{traceback.format_exc()[-1500:]}"
            bundle_errors.append({"file": name, "error": f"{type(ex).__name__}: {str(ex)[:300]}"})
        head = "# " + json.dumps(stamp, ensure_ascii=False) + "\n"
        with open(os.path.join(out, name), "w", encoding="utf-8") as f:
            f.write(_scrub(head + text + "\n", secs))
        written[name] = len(text)

    def search_report():
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            seo_build.main(["seo_build.py", "search-report"])
        return buf.getvalue()
    def probe_():
        r = probe(data_dir, n)
        probe_result.update(r if isinstance(r, dict) else {})
        if isinstance(r, dict) and r.get("error"):
            bundle_errors.append({"file": "probe.json", "error": r["error"]})
        for k, v in (r.items() if isinstance(r, dict) else []):
            for kind in ("movie", "series"):
                if isinstance(v, dict) and isinstance(v.get(kind), dict) and v[kind].get("error"):
                    bundle_errors.append({"file": "probe.json", "service": k, "kind": kind, "error": v[kind]["error"]})
        return r
    stage("probe"); dump_json("probe.json", probe_)                                     # قراءة
    stage("report"); dump_text("report.txt", lambda: seo_build.report(data_dir))         # قراءة — قبل العيّنة: التقرير يصف القاعدة التي تُعيَّن منها
    stage("search-report"); dump_text("search-report.txt", search_report)                # قراءة
    stage("sample"); dump_json("sample.json", lambda: sample(data_dir, bundle_errors=bundle_errors))   # الاستثناء الوحيد: إثراء الثلاثين
    import seo_qa
    stage("qa"); dump_json("qa.json", lambda: seo_qa.run(data_dir, probe=probe_result, sitemap_out=os.path.join(out, "sitemap-staging.xml")))   # قراءة: الفحص النهائي وخريطةٌ تجريبية لا تُخدم
    for name in BUNDLE_EXTRA:
        try:
            written[name] = os.path.getsize(os.path.join(out, name))
        except OSError:
            pass
    _bundle_stage.pop(os.path.abspath(data_dir), None)
    with open(os.path.join(out, "bundle.json"), "w", encoding="utf-8") as f:    # ملخّص اللقطة: الختم والملفات وأخطاؤها
        f.write(json.dumps({"meta": stamp, "files": written, "errors": bundle_errors}, ensure_ascii=False, indent=1))
    zip_name = bundle_zip(out, stamp["bundle_id"])                               # الملفات كلها في أرشيفٍ واحد بأسماءٍ تحمل معرّف اللقطة
    return {"out": out, "files": written, "errors": bundle_errors, "zip": zip_name, **stamp}


_ZIP_RX = re.compile(r"seo-review-\d{8}T\d{6}Z\.zip")


def bundle_zip(out, bundle_id):
    """أرشيف اللقطة: `seo-review-<bundle_id>.zip` وفيه كل ملفٍ باسمه ومعرّف اللقطة (`qa_<bundle_id>.json` …) فلا تختلط
    نسخ اللقطات عند التنزيل ← اسم الأرشيف."""
    import zipfile
    name = f"seo-review-{bundle_id}.zip"
    with zipfile.ZipFile(os.path.join(out, name), "w", zipfile.ZIP_DEFLATED) as z:
        for n in BUNDLE_FILES + BUNDLE_EXTRA:
            path = os.path.join(out, n)
            if os.path.exists(path):
                stem, ext = n.rsplit(".", 1)
                z.write(path, f"{stem}_{bundle_id}.{ext}")
    return name


BUNDLE_FILES = ("probe.json", "sample.json", "report.txt", "search-report.txt", "qa.json", "bundle.json")
BUNDLE_EXTRA = ("sitemap-staging.xml",)       # خريطة الموقع التجريبية من الفحص النهائي: تُنزَّل من البطاقة ولا تُخدم على الموقع
_bundling = {}
_bundle_stage = {}            # مسار البيانات ← دالة تحديث مرحلة اللقطة (تستعملها العيّنة لعدّ أعمالها)


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
            import traceback
            _state[k + ":bundle"] = {"at": int(time.time()), "running": False, "ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}", "traceback": traceback.format_exc()[-1500:]}
    t = _bundling[k] = threading.Thread(target=run_, daemon=True)
    t.start()
    return True


def bundle_state(data_dir):
    """حال الإنتاج وآخر ملفاتٍ مكتوبة (الاسم والحجم والوقت) — لروابط التنزيل في البطاقة."""
    k = os.path.abspath(data_dir)
    d = bundle_dir(data_dir)
    files = []
    zips = sorted(n for n in (os.listdir(d) if os.path.isdir(d) else []) if _ZIP_RX.fullmatch(n))
    for n in tuple(zips[-1:]) + BUNDLE_FILES + BUNDLE_EXTRA:
        try:
            st_ = os.stat(os.path.join(d, n))
            files.append({"name": n, "size": st_.st_size, "at": int(st_.st_mtime)})
        except OSError:
            pass
    last = _state.get(k + ":bundle") or {}
    return {"running": bool(_bundling.get(k) and _bundling[k].is_alive()), "last": last, "files": files}


def bundle_file(data_dir, name):
    """ملفٌ من ملفات المراجعة بالاسم (من القائمة وحدها) ← (bytes, نوعه) أو None."""
    if name not in BUNDLE_FILES + BUNDLE_EXTRA and not _ZIP_RX.fullmatch(name):
        return None
    try:
        with open(os.path.join(bundle_dir(data_dir), name), "rb") as f:
            return f.read(), ("application/json; charset=utf-8" if name.endswith(".json") else "application/xml; charset=utf-8" if name.endswith(".xml")
                              else "application/zip" if name.endswith(".zip") else "text/plain; charset=utf-8")
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

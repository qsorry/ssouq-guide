# -*- coding: utf-8 -*-
"""«أعجبني» وتوصيات «قد تعجبك» بحسب سلوك الزائر — بلا حسابات ولا كوكيز: ما أعجبه وما شاهده يُحفظان في **جهازه** (localStorage)
ويُرسل الخادم أسماء (slugs) العناوين وحدها ليحسب منها ملفّه (profile) ويقترح ما يشبهه، ولا يُخزَّن شيءٌ عنه.

ملفّ الزائر: لكل عنوانٍ أعجبه وزن 3 وما شاهده 1 (ويخفت بالأقدم)، فتُجمَّع سماتها — التصنيف والدولة واللغة والهب (تركي/أنمي) والمخرج
والممثلون الأوائل والنوع (فيلم/مسلسل) والعقد — بأوزان نُدرة (IDF: السمة النادرة أدلّ من «دراما»). ثم يُسجَّل كل عملٍ متاح يشارك سماته
بمجموع أوزانها، ويُستبعد ما أعجبه أو شاهده. وعدّاد الإعجابات مجهول (رقمٌ لكل عمل) بحدّ طلباتٍ لكل عنوان.
وبلا أي سلوكٍ بعد: الأشهر (الشعبية) من الأعمال المطابَقة."""
import math
import re
import threading
import time

import seo_db
import seo_guide

W_LIKE, W_SEEN, DECAY = 3.0, 1.0, 0.97
W_HINT = 0.7                          # قرينة القسم (مثلًا «مسلسلات تركية»): تغطّي كل الأعمال حتى قبل إثراء TMDB، لكنها أضعف من التأكيد
SRC = "('tmdb','manual','hint')"
MAX_LIKES, MAX_SEEN, TOP_FEATURES, DEFAULT_N = 40, 80, 14, 12
W_INTEREST, MIN_REL = 2.5, 0.30      # وزن الاهتمام الصريح (جولة المشاهدة) · وأدنى نسبةٍ من أعلى اقتراحٍ تُعدّ ذات صلة
SLUG_RX = re.compile(r"^[a-z0-9][a-z0-9-]{0,100}$")
TAX_KINDS = ("genre", "country", "language", "hub", "anime_kind", "network")
_rate = {}
_lock = threading.Lock()
LIKE_PER_HOUR = 60


def rate_ok(ip, limit=LIKE_PER_HOUR):
    """حدّ الإعجابات بالساعة لكل عنوان (في الذاكرة): لا يُحصى الإعجاب من جهازٍ واحد آلاف المرات."""
    now = time.time()
    with _lock:
        q = [t for t in _rate.get(ip, []) if now - t < 3600]
        if len(q) >= limit:
            _rate[ip] = q
            return False
        q.append(now)
        _rate[ip] = q
        if len(_rate) > 20000:
            for k in [k for k, v in _rate.items() if not v or now - v[-1] > 3600]:
                _rate.pop(k, None)
    return True


def slugs(raw, cap):
    """نصّ مفصولٌ بفواصل أو قائمة ← slugs صالحة بلا تكرار (بترتيبها)."""
    items = raw.split(",") if isinstance(raw, str) else (raw or [])
    out = []
    for x in items:
        x = str(x).strip().lower()
        if SLUG_RX.match(x) and x not in out:
            out.append(x)
        if len(out) >= cap:
            break
    return out


def _split_interests(con, interests):
    """اهتمامات الجولة ← (أصول: بلدٌ/لغةٌ/هب تركي، وغيرها: تصنيفٌ/أنمي) — لاشتراط الأصل المختار."""
    if not interests:
        return set(), set()
    origin, other = set(), set()
    for r in con.execute(f"SELECT id, kind, key FROM taxonomy WHERE id IN ({','.join('?' * len(interests))})", interests):
        (origin if r["kind"] in ("country", "language") or (r["kind"] == "hub" and r["key"] != "anime") else other).add(r["id"])
    return origin, other


def ids(raw, cap):
    """أرقام تصنيفاتٍ مفصولة بفواصل (أو قائمة) ← أعدادٌ صحيحة موجبة بلا تكرار."""
    items = raw.split(",") if isinstance(raw, str) else (raw or [])
    out = []
    for x in items:
        try:
            v = int(x)
        except (TypeError, ValueError):
            continue
        if v > 0 and v not in out:
            out.append(v)
        if len(out) >= cap:
            break
    return out


# ================= الإعجابات =================
def like_count(con, content_id):
    r = con.execute("SELECT likes FROM content_like WHERE content_id=?", (content_id,)).fetchone()
    return int(r["likes"]) if r else 0


def like(data_dir, slug, on):
    """يزيد أو ينقص عدّاد إعجاب عملٍ (لا ينزل تحت الصفر) ← العدد الجديد، أو None إن لم يوجد العمل."""
    if not SLUG_RX.match(slug or ""):
        return None
    con = seo_db.connect(data_dir, create=False)
    if con is None:
        return None
    try:
        row = con.execute("SELECT id FROM content WHERE slug=? AND merged_into IS NULL", (slug,)).fetchone()
        if not row:
            return None
        d = 1 if on else -1
        with con:
            con.execute("INSERT INTO content_like(content_id, likes, updated_at) VALUES (?, MAX(0, ?), ?) "
                        "ON CONFLICT(content_id) DO UPDATE SET likes=MAX(0, likes + ?), updated_at=excluded.updated_at", (row["id"], d, int(time.time()), d))
        return like_count(con, row["id"])
    finally:
        con.close()


# ================= ملفّ الزائر والتوصية =================
def _features(con, cid):
    """سمات عملٍ ← {سمة: وزن}: ‏('t', taxonomy_id) · ('p', person_id) · ('k', النوع) · ('y', العقد)."""
    f = {}
    for r in con.execute(f"SELECT ct.taxonomy_id, ct.source FROM content_taxonomy ct JOIN taxonomy t ON t.id=ct.taxonomy_id WHERE ct.content_id=? AND ct.source IN {SRC} "
                         f"AND t.kind IN ({','.join('?' * len(TAX_KINDS))})", (cid, *TAX_KINDS)):
        f[("t", r[0])] = max(f.get(("t", r[0]), 0.0), W_HINT if r[1] == "hint" else 1.0)
    for r in con.execute("SELECT person_id, role FROM content_person WHERE content_id=? AND role IN ('director','creator','actor','voice') ORDER BY ord LIMIT 8", (cid,)):
        f[("p", r["person_id"])] = 1.6 if r["role"] in ("director", "creator") else 0.8
    return f


def _idf(con, feats, total):
    out = {}
    for kind, fid in feats:
        if kind == "t":
            n = con.execute(f"SELECT COUNT(*) FROM content_taxonomy WHERE taxonomy_id=? AND source IN {SRC}", (fid,)).fetchone()[0]
        else:
            n = con.execute("SELECT COUNT(DISTINCT content_id) FROM content_person WHERE person_id=?", (fid,)).fetchone()[0]
        out[(kind, fid)] = max(0.2, math.log((total + 1) / (n + 1)))
    return out


def recommend(data_dir, likes, seen, n=DEFAULT_N, interests=(), types=(), age=0, unrated=False):
    """age ∈ (6,10,13,16,18): مشاهدٌ بهذا العمر — لا يُرشَّح ما دليله أعلى منه، ولا غير المُصنَّف إلا إن طُلب (unrated).
    ← {profile: {...}, items: [{slug, type, title_ar, title_en, year, poster, rating, score, why: {slug, liked}}], cold: bool}."""
    con = seo_db.connect(data_dir, create=False)
    if con is None:
        return {"items": [], "cold": True}
    try:
        likes, seen = slugs(likes, MAX_LIKES), slugs(seen, MAX_SEEN)
        interests = ids(interests, 8)
        types = [t for t in (types.split(",") if isinstance(types, str) else types or []) if t in ("movie", "series")]
        tfilter = f" AND c.type IN ({','.join('?' * len(types))})" if types else ""
        weights = {}
        for s in seen:                                      # الأحدث أولًا (يخفت بالأقدم)
            weights[s] = max(weights.get(s, 0), W_SEEN * (DECAY ** seen.index(s)))
        for s in likes:
            weights[s] = W_LIKE
        rows = {}
        if weights:
            qs = ",".join("?" * len(weights))
            for r in con.execute(f"SELECT id, slug, type, year FROM content WHERE slug IN ({qs}) AND merged_into IS NULL", list(weights)):
                rows[r["slug"]] = r
        exclude = {r["id"] for r in rows.values()}
        total = con.execute("SELECT COUNT(*) FROM content WHERE merged_into IS NULL AND available=1").fetchone()[0] or 1
        # ملفّ الزائر: مجموع أوزان سمات أعماله
        item_feats, prof = {}, {}
        for slug, r in rows.items():
            f = _features(con, r["id"])
            item_feats[slug] = f
            for k, v in f.items():
                prof[k] = prof.get(k, 0.0) + v * weights[slug]
        kinds, decades = {}, {}
        for slug, r in rows.items():
            kinds[r["type"]] = kinds.get(r["type"], 0.0) + weights[slug]
            if r["year"]:
                decades[r["year"] // 10] = decades.get(r["year"] // 10, 0.0) + weights[slug]
        for tid in interests:                                # ما اختاره في الجولة: سماتٌ صريحة بوزنٍ أعلى من المشاهدة
            prof[("t", tid)] = prof.get(("t", tid), 0.0) + W_INTEREST
        if not prof:                                         # لا سلوك بعد: الأشهر من المطابَق
            cold = con.execute("SELECT c.id, c.slug, c.type, c.title, c.title_ar, c.title_en, c.year, c.poster, c.rating FROM content c WHERE c.merged_into IS NULL AND c.available=1 AND c.poster IS NOT NULL "
                               f"AND c.match IN ('tmdb','manual'){tfilter} ORDER BY COALESCE(c.popularity,0) DESC, c.id LIMIT ?", (*types, (n + len(exclude)) * (12 if age else 1))).fetchall()
            if age:
                okc = seo_guide.allowed(con, [r["id"] for r in cold], int(age), unrated)
                cold = [r for r in cold if r["id"] in okc]
            return {"cold": True, "profile": {}, "items": [_item(r, 0.0, None) for r in cold if r["id"] not in exclude][:n]}
        top = sorted(prof, key=lambda k: -prof[k])[:TOP_FEATURES]
        idf = _idf(con, top, total)
        wf = {k: prof[k] * idf[k] for k in top}
        for tid in interests:                                # الاهتمام الصريح يدخل السمات العليا دائمًا
            if ("t", tid) not in top:
                top.append(("t", tid))
                idf.update(_idf(con, [("t", tid)], total))
                wf[("t", tid)] = prof[("t", tid)] * idf[("t", tid)]
        cand = {}                                            # عمل ← [مجموع الأوزان، عدد السمات المتطابقة]
        origin_ids, other_ids = _split_interests(con, interests)
        hit_origin, hit_other = set(), set()
        tids = [fid for kind, fid in top if kind == "t"]
        pids = [fid for kind, fid in top if kind == "p"]
        base = "c.available=1 AND c.merged_into IS NULL AND c.poster IS NOT NULL AND (c.rating IS NULL OR c.rating>=5)" + tfilter
        if tids:
            qs = ",".join("?" * len(tids))
            for r in con.execute(f"SELECT ct.content_id, ct.taxonomy_id, ct.source FROM content_taxonomy ct JOIN content c ON c.id=ct.content_id WHERE ct.taxonomy_id IN ({qs}) "
                                 f"AND ct.source IN {SRC} AND {base}", (*tids, *types)):
                c_ = cand.setdefault(r[0], [0.0, 0])
                c_[0] += wf[("t", r[1])] * (W_HINT if r[2] == "hint" else 1.0)
                c_[1] += 1
                if r[1] in origin_ids:
                    hit_origin.add(r[0])
                if r[1] in other_ids:
                    hit_other.add(r[0])
        if pids:
            qs = ",".join("?" * len(pids))
            for r in con.execute(f"SELECT cp.content_id, cp.person_id FROM content_person cp JOIN content c ON c.id=cp.content_id WHERE cp.person_id IN ({qs}) AND {base}", (*pids, *types)):
                c_ = cand.setdefault(r[0], [0.0, 0])
                c_[0] += wf[("p", r[1])]
                c_[1] += 1
        for cid in exclude:
            cand.pop(cid, None)
        # الصلة: ما اختاره صراحةً شرط (من اهتماماتك واحدٌ على الأقل)، وبلا سلوك عميق يكفي سمةٌ واحدة، ومعه سمتان فأكثر؛ ثم عتبة نسبية من الأفضل
        need = 2 if (rows and len(top) >= 4) else 1
        # اختيار الأصل (تركي/أمريكي/…) شرطٌ: لا يُعرض عملٌ من غير أصله؛ وبلا أصلٍ يُشترط تصنيفٌ مما اختاره
        gate = hit_origin if origin_ids else hit_other if other_ids else None
        cand = {c: v for c, v in cand.items() if v[1] >= need and (gate is None or c in gate)}
        if age and cand:
            okc = seo_guide.allowed(con, list(cand), int(age), unrated)
            cand = {c: v for c, v in cand.items() if c in okc}
        if not cand:
            return {"cold": False, "profile": {"likes": len(likes), "seen": len(seen)}, "items": []}
        peak = max(v[0] for v in cand.values())
        cand = {c: v[0] for c, v in cand.items() if v[0] >= MIN_REL * peak}
        best = sorted(cand.items(), key=lambda kv: -kv[1])[:max(n * 6, 60)]
        meta = {r["id"]: r for r in con.execute(
            f"SELECT id, slug, type, title, title_ar, title_en, year, poster, rating, popularity FROM content WHERE id IN ({','.join('?' * len(best))})", [c for c, _ in best])}
        ktot = sum(kinds.values()) or 1.0
        scored = []
        for cid, sc in best:
            r = meta.get(cid)
            if not r:
                continue
            s = sc * (1.0 + 0.25 * kinds.get(r["type"], 0.0) / ktot)               # يفضَّل نوعه المعتاد (فيلم/مسلسل) قليلًا
            if r["year"] and decades:
                s *= 1.0 + 0.15 * max(0.0, 1.0 - min(abs(r["year"] // 10 - d) for d in decades) / 3.0)
            s += 0.06 * (r["rating"] or 0) + 0.02 * math.log1p(r["popularity"] or 0)   # كسر التعادل بالجودة والشعبية
            scored.append((s, cid, r))
        scored.sort(key=lambda t: (-t[0], t[1]))
        out, per_year = [], {}
        for s, cid, r in scored:
            if per_year.get(r["year"], 0) >= 4:          # لا تتكتّل سنةٌ واحدة
                continue
            per_year[r["year"]] = per_year.get(r["year"], 0) + 1
            out.append(_item(r, s, _why(con, cid, item_feats, weights, likes)))
            if len(out) >= n:
                break
        top_feats = [{"kind": k[0], "id": k[1], "w": round(wf[k], 2)} for k in top[:6]]
        return {"cold": False, "profile": {"features": top_feats, "likes": len(likes), "seen": len(seen), "types": kinds}, "items": out}
    finally:
        con.close()


def _why(con, cid, item_feats, weights, likes):
    """العمل الذي يتشارك أكثر السمات وزنًا مع المقترَح ← {slug، liked}."""
    f = _features(con, cid)
    best, bs = None, 0.0
    for slug, fs in item_feats.items():
        sc = sum(v for k, v in fs.items() if k in f) * weights.get(slug, 0)
        if sc > bs:
            best, bs = slug, sc
    return {"slug": best, "liked": best in likes} if best else None


def _item(r, score, why):
    return {"id": r["id"], "slug": r["slug"], "type": r["type"], "title_ar": r["title_ar"] or r["title"], "title_en": r["title_en"] or r["title"], "year": r["year"],
            "poster": r["poster"], "rating": r["rating"], "score": round(score, 3), "why": why}


def api(data_dir, params, lang="ar"):
    """ردّ ‏/api/content/recommend ← قاموس JSON جاهز للصفحة: مساراتٌ بلغة الصفحة، وصورٌ مصغّرة، وسبب كل اقتراح بالاسم."""
    import seo_pages
    age = int(params.get("age") or 0)
    age = age if age in seo_guide.AGES else 0
    res = recommend(data_dir, params.get("likes") or "", params.get("seen") or "", int(params.get("n") or DEFAULT_N), params.get("interests") or "", params.get("types") or "",
                    age=age, unrated=bool(params.get("unrated")))
    en = lang == "en"
    pre = seo_db.lang_prefix("en" if en else "ar")
    names = {}
    con = seo_db.connect(data_dir, create=False)
    try:
        for it in res["items"]:
            w = (it.get("why") or {}).get("slug")
            if w and w not in names:
                r = con.execute("SELECT title, title_ar, title_en FROM content WHERE slug=?", (w,)).fetchone()
                names[w] = ((r["title_en"] or r["title"]) if en else (r["title_ar"] or r["title"])) if r else w
    finally:
        con.close()
    items = []
    ages, skeys = {}, {}
    con3 = seo_db.connect(data_dir, create=False)
    try:
        for it in res["items"]:                              # ملصق اللوحة لا يُجلب إلا بمفتاح سيرفره (وإلا ظهرت الحروف بدل الصورة)
            if it.get("poster") and "image.tmdb.org" not in it["poster"]:
                skeys[it["id"]] = seo_pages.skey_of(con3, it["id"])
    finally:
        con3.close()
    if age and res["items"]:
        con2 = seo_db.connect(data_dir, create=False)
        try:
            ages = seo_guide.ages_of(con2, [it["id"] for it in res["items"]])
        finally:
            con2.close()
    for it in res["items"]:
        w = it.get("why")
        items.append({"slug": it["slug"], "path": pre + f"/content/{'movies' if it['type'] == 'movie' else 'series'}/{it['slug']}/",
                      "title": it["title_en"] if en else it["title_ar"], "year": it["year"], "rating": it["rating"],
                      "poster": seo_pages._img(it["poster"], "w342", skeys.get(it["id"], "")),
                      "guide": (f"{ages[it['id']]}+ · " + seo_guide.AGE_NAMES[ages[it["id"]]][1 if en else 0]) if ages.get(it["id"]) else "",
                      "why": ((("لأنك أعجبت بـ " if w["liked"] else "لأنك شاهدت ") if not en else ("Because you liked " if w["liked"] else "Because you viewed ")) + names.get(w["slug"], w["slug"])) if w else ""})
    return {"ok": True, "cold": res["cold"], "items": items, "profile": res.get("profile", {})}


# ================= البحث الذكي (يقبل الأخطاء) =================
_idx = {"key": None, "at": 0, "idx": None}


def _index(con, data_dir):
    import seo_search
    now = time.time()
    if _idx["idx"] is None or now - _idx["at"] > 600 or _idx["key"] != data_dir:
        _idx.update({"idx": seo_search.load(con), "at": now, "key": data_dir})
    return _idx["idx"]


def find(data_dir, q, lang="ar", n=8):
    """بحثٌ بالاسم يقبل الأخطاء الإملائية والكتابة بحرفٍ آخر («بريزن بريك» · «prison brek» · «person break»): الدقيق أولًا ثم الأقرب صوتيًّا ثم البادئة
    ← عناصر بملصقها وسنتها وتقييمها (الأعمال المتاحة وحدها)."""
    import seo_pages
    q = (q or "").strip()[:80]
    if len(q) < 2:
        return {"ok": True, "items": []}
    con = seo_db.connect(data_dir, create=False)
    if con is None:
        return {"ok": True, "items": []}
    try:
        res = _index(con, data_dir).search(q, max_suggest=n + 4, min_conf=0.5)
        order = list(res["exact"]) + [c for c, *_ in res.get("also", [])] + [x[0] for x in res["suggest"]]
        seen_ids, out = set(), []
        en = lang == "en"
        pre = seo_db.lang_prefix("en" if en else "ar")
        for cid in order:
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            r = con.execute("SELECT slug, type, title, title_ar, title_en, year, poster, rating FROM content WHERE id=? AND merged_into IS NULL AND available=1", (cid,)).fetchone()
            if not r:
                continue
            out.append({"slug": r["slug"], "path": pre + f"/content/{'movies' if r['type'] == 'movie' else 'series'}/{r['slug']}/",
                        "title": (r["title_en"] or r["title"]) if en else (r["title_ar"] or r["title"]), "year": r["year"], "rating": r["rating"],
                        "poster": seo_pages._img(r["poster"], "w342", seo_pages.skey_of(con, cid) if r["poster"] and "image.tmdb.org" not in r["poster"] else ""), "type": r["type"]})
            if len(out) >= n:
                break
        return {"ok": True, "items": out, "exact": bool(res["exact"])}
    finally:
        con.close()


DEMONYMS = {"US": ("أمريكي", "American"), "TR": ("تركي", "Turkish"), "GB": ("بريطاني", "British"), "KR": ("كوري", "Korean"), "IN": ("هندي", "Indian"), "JP": ("ياباني", "Japanese"),
            "EG": ("مصري", "Egyptian"), "SA": ("خليجي", "Gulf"), "SY": ("سوري", "Syrian"), "FR": ("فرنسي", "French"), "ES": ("إسباني", "Spanish"), "DE": ("ألماني", "German"),
            "IT": ("إيطالي", "Italian"), "CN": ("صيني", "Chinese"), "CA": ("كندي", "Canadian"), "MX": ("مكسيكي", "Mexican"), "RU": ("روسي", "Russian"), "BR": ("برازيلي", "Brazilian"),
            "LB": ("لبناني", "Lebanese"), "JO": ("أردني", "Jordanian"), "KW": ("كويتي", "Kuwaiti"), "AE": ("إماراتي", "Emirati"), "AU": ("أسترالي", "Australian"), "TH": ("تايلندي", "Thai")}


def interests(data_dir, lang="ar"):
    """اهتمامات الجولة ← [{id, name, kind, group}]: «origin» (الأصل: تركي · أمريكي · كوري · عربي…) و«genre» (التصنيف + الأنمي). تُعدّ بقرائن الأقسام أيضًا
    فيظهر التركي وغيره ولو لم يُثرَ بعد كل أعماله."""
    con = seo_db.connect(data_dir, create=False)
    if con is None:
        return []
    en = lang == "en"
    try:
        rows = con.execute(
            f"SELECT t.id, t.kind, t.key, t.slug, t.name_ar, t.name_en, COUNT(DISTINCT c.id) n FROM taxonomy t JOIN content_taxonomy ct ON ct.taxonomy_id=t.id JOIN content c ON c.id=ct.content_id "
            f"WHERE t.kind IN ('hub','genre','country','language') AND ct.source IN {SRC} AND c.available=1 AND c.merged_into IS NULL GROUP BY t.id").fetchall()
        origins, genres = [], []
        for r in rows:
            if r["n"] < 12:
                continue
            if r["kind"] == "hub":
                if r["key"] == "turkish":
                    origins.append((r["n"] + 10 ** 6, {"id": r["id"], "name": "Turkish" if en else "تركي", "kind": "hub", "group": "origin"}))    # التركي أولًا
                elif r["key"] == "anime":
                    genres.append((r["n"] + 10 ** 6, {"id": r["id"], "name": "Anime" if en else "أنمي", "kind": "hub", "group": "genre"}))
            elif r["kind"] == "country":
                if r["slug"] == "tr":
                    continue                                    # التركي هبٌّ واحد
                dm = DEMONYMS.get(str(r["key"]).upper())
                origins.append((r["n"], {"id": r["id"], "name": (dm[1] if en else dm[0]) if dm else ((r["name_en"] or r["name_ar"]) if en else (r["name_ar"] or r["name_en"])), "kind": "country", "group": "origin"}))
            elif r["kind"] == "language" and str(r["key"]).lower() == "ar":
                origins.append((r["n"], {"id": r["id"], "name": "Arabic" if en else "عربي", "kind": "language", "group": "origin"}))
            elif r["kind"] == "genre":
                genres.append((r["n"], {"id": r["id"], "name": (r["name_en"] or r["name_ar"]) if en else (r["name_ar"] or r["name_en"]), "kind": "genre", "group": "genre"}))
        return [x for _, x in sorted(origins, key=lambda t: -t[0])[:12]] + [x for _, x in sorted(genres, key=lambda t: -t[0])[:16]]
    finally:
        con.close()

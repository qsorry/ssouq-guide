# -*- coding: utf-8 -*-
"""بناء طبقة الكيانات (‏seo.sqlite) من فهارس السيرفرات — تزايديًّا، بلا شبكة، وبلا مسّ الفهارس.

يُقرأ ‏data/content/<السيرفر>.json لكل سيرفرٍ (الأفلام والمسلسلات؛ لا القنوات، ولا الأقسام التي أخفاها المدير)،
ويُطابَق العنصر نفسه بين السيرفرات مطابقةً محافظة (‏seo_match)، فيصير كيانًا واحدًا في ‏content مربوطًا بسيرفراته في
‏content_service، وكل اسمٍ رُئي له ‏alias، ومصدر كل حقلٍ في ‏provenance، وما لم تكفِ قرائنه في ‏review.

- **ثبات**: الكيان يحتفظ بمعرّفه وslug بين البناءات (يُعرف بروابطه إلى السيرفرات)؛ وما غاب يُعلَّم ‏available=0 ولا يُحذف.
- **المدير يغلب**: حقلٌ مصدره ‏manual لا يكتب البناء فوقه.
- **تزايدي**: لا يُعاد البناء ما لم يتغيّر ملف سيرفرٍ أو أقسامه المخفية (بصمة في ‏build_state) — إلا بـ ‏force.
- يعمل في دورة المحتوى بعد السحب (‏tick من ‏xm_lines._content_loop)، ومن سطر الأوامر:

    python seo_build.py build [--force]     # ‏XM_DATA أو ./data
    python seo_build.py stats | report | review [--kind name_only] [--limit 50]
"""
import json
import os
import sys
import threading
import time

import content as C
import seo_db
import seo_match as M
import seo_sources

AUTO_KINDS = ("name_only", "conflict", "same_server_ambiguous", "merged_entities", "split_entity")
STATE_KINDS = ("name_only", "conflict", "same_server_ambiguous")     # حالٌ تزول بزوال سببها؛ والدمج والانفصال أحداثٌ تبقى حتى تُراجَع
REVIEW_SNIPPET = 160
GENRES_MAX = 5

_running = {}                 # مسار البيانات ← خيط البناء الجاري (زرّ «ابنِ الآن»)
_progress = {}                # مسار البيانات ← {stage, done, total, percent, started, elapsed}: عدّاد البناء لبطاقة الإدارة

STAGES = (("indexes", "قراءة الفهارس", 10), ("cluster", "العنقدة", 25), ("apply", "كتابة الكيانات", 55), ("finish", "المراجعات والتسوية", 10))


def _prog(data_dir, stage, done=0, total=0):
    """تحديث عدّاد البناء: المرحلة ومقدارها ← نسبةٌ مئوية تراكمية حسب أوزان المراحل."""
    k = os.path.abspath(data_dir)
    p = _progress.setdefault(k, {"started": time.time()})
    pct, found = 0, False
    for key, _, w in STAGES:
        if key == stage:
            pct += w * (done / total if total else 0); found = True; break
        pct += w
    p.update({"stage": stage, "stage_name": dict((a, b) for a, b, _ in STAGES).get(stage, stage), "done": done, "total": total,
              "percent": int(min(100, pct)) if found else 100, "elapsed": int(time.time() - p["started"])})


def progress(data_dir):
    return _progress.get(os.path.abspath(data_dir))
_last = {}                    # مسار البيانات ← نتيجة آخر بناء أو خطؤه (لصفحة المدير)


# ================= القراءة من فهارس السيرفرات =================
def _signature(data_dir, srv):
    p = C._cat_path(data_dir, srv["key"])
    try:
        st = os.stat(p)
    except OSError:
        return None
    return [st.st_ino, st.st_mtime_ns, st.st_size, sorted(srv.get("hidden") or [])]


def _entry(kind, key, g, it, st):
    """عنصر فهرس السيرفر ← مدخلٌ باسمه الأساسي (بلا رمز موسم ولا نسخة ولا جودة)، ورمز موسمه، ونسخه، واسمه الأصلي إن
    حملته القائمة (‏seo_match.clean_title) — والاسم الخام يبقى."""
    c = M.clean_title(it["n"], st)
    seasons = {int(a): int(b) for a, b in (it.get("s") or ())}
    if c["season"] and set(seasons) <= {0, 1}:      # القائمة فرّقت المواسم باسمها: حلقات هذا المدخل كلها لموسمه
        seasons = {c["season"]: sum(seasons.values())} if seasons else {}
    return {"type": kind, "service": key, "kind": kind, "name": c["base"], "raw_name": c["raw"], "versions": c["versions"],
            "season_token": c["season"], "original": c["original"], "cleaned": c["cleaned"],
            "year": int(it.get("y") or 0) or c["year"],
            "poster": it.get("p") or "", "backdrop": it.get("b") or "", "plot": it.get("d") or "",
            "genres": list(it.get("g") or ()), "rating": float(it.get("r") or 0), "added": int(it.get("a") or 0),
            "stream_id": int(it.get("i") or 0), "stream_ids": [int(it.get("i") or 0)] if it.get("i") else [],
            "tmdb_id": int(it.get("t") or 0), "series_id": int(it.get("sid") or 0),
            "seasons": seasons, "groups": [g["name"]] if g.get("name") else []}


def _merge_entries(es):
    """مداخل قسمٍ أو أكثر لعنصرٍ واحد في السيرفر ← عنصرٌ واحد (أكبر ما رُئي: المواسم والتقييم والرقم؛ وأطول قصة)."""
    rec = dict(es[0], genres=list(es[0]["genres"]), seasons=dict(es[0]["seasons"]), groups=list(es[0]["groups"]),
               versions=list(es[0]["versions"]), raw_names=[es[0]["raw_name"]], originals=[es[0]["original"]] if es[0]["original"] else [],
               stream_ids=list(es[0].get("stream_ids") or []))
    for e in es[1:]:
        rec["stream_ids"] += [x for x in e.get("stream_ids") or [] if x not in rec["stream_ids"]]   # كل أرقام البثّ المطويّة: تُعرَف بها الكيانات القديمة
        for v in e["versions"]:
            if v not in rec["versions"]:
                rec["versions"].append(v)
        if e["raw_name"] not in rec["raw_names"]:
            rec["raw_names"].append(e["raw_name"])
        if e["original"] and e["original"] not in rec["originals"]:
            rec["originals"].append(e["original"])
        for f in ("poster", "backdrop", "plot", "year", "tmdb_id", "series_id"):
            if not rec[f] and e[f]:
                rec[f] = e[f]
        if len(e["plot"]) > len(rec["plot"]):
            rec["plot"] = e["plot"]
        for x in e["genres"]:
            if x not in rec["genres"]:
                rec["genres"].append(x)
        for x in e["groups"]:
            if x not in rec["groups"]:
                rec["groups"].append(x)
        rec["rating"] = max(rec["rating"], e["rating"])
        rec["added"] = max(rec["added"], e["added"])
        rec["stream_id"] = max(rec["stream_id"], e["stream_id"])
        for sn, n in e["seasons"].items():
            rec["seasons"][sn] = max(rec["seasons"].get(sn, 0), n)
    rec["min_stream"] = min(e["stream_id"] for e in es)
    return rec


def _items_of(data_dir, srv, st):
    """عناصر السيرفر الظاهرة (أفلامٌ ومسلسلات) ← (العناصر، ما غمض). الاسم نفسه في قسمين **لا يُعدّ واحدًا تلقائيًّا**
    (‏seo_match.cluster_in_server): الصورة نفسها أو السنة نفسها أو موسمٌ بحلقاته تجمع، وسنتان مختلفتان تفرّقان، وبلا
    قرينة عنصران وبند مراجعة. ومفتاح العنصر ‏norm|year (و‏|2 |3… لمن شاركه الاسم والسنة، الأقدم رقمًا أولًا)."""
    cat = C._read(C._cat_path(data_dir, srv["key"]))
    if not cat:
        return [], []
    cat = C._upgrade(cat)
    hidden, key = set(srv.get("hidden") or []), srv["key"]
    by_name = {}
    for kind in ("movie", "series"):
        for g in cat.get(kind) or []:
            if g.get("id") in hidden:
                continue
            for it in g.get("items") or []:
                if isinstance(it, dict) and it.get("n"):
                    e = _entry(kind, key, g, it, st)
                    by_name.setdefault((kind, M.norm(e["name"])), []).append(e)
    out, reviews = [], []
    for (kind, nm), es in by_name.items():
        groups, ambiguous = M.cluster_in_server(es, st) if len(es) > 1 else ([list(range(len(es)))], False)
        recs = sorted((_merge_entries([es[i] for i in g]) for g in groups), key=lambda r: r["min_stream"])
        seen = {}
        for r in recs:
            base = f"{nm}|{r['year'] or ''}"
            n = seen[base] = seen.get(base, 0) + 1
            r["local_key"] = base if n == 1 else f"{base}|{n}"
            out.append(r)
        if ambiguous:
            reviews.append({"kind": "same_server_ambiguous", "key": f"same_server:{key}:{kind}:{nm}", "type": kind,
                            "name": es[0]["name"], "service": key, "entries": [_snippet(r) for r in recs]})
    return out, reviews


def signatures(data_dir):
    """بصمة فهرس كل سيرفر (ومخفيّه) — رخيصة، تُقارن قبل أي قراءة."""
    out = {}
    for srv in C.servers(data_dir):
        sig = _signature(data_dir, srv)
        if sig is not None:
            out[srv["key"]] = sig
    return out


def load_items(data_dir, st):
    """كل السيرفرات ← (العناصر، ما غمض داخل السيرفرات، البصمات)."""
    items, conflicts, sigs = [], [], {}
    servers = C.servers(data_dir)
    for i, srv in enumerate(servers):
        _prog(data_dir, "indexes", i, len(servers))
        sig = _signature(data_dir, srv)
        if sig is None:
            continue
        sigs[srv["key"]] = sig
        its, cf = _items_of(data_dir, srv, st)
        items += its
        conflicts += cf
    return items, conflicts, sigs


# ================= الحقول =================
def _entity_fields(members):
    """قيم الكيان من أعضائه (عنصر كل سيرفر) ← {حقل: (القيمة، المصدر، السيرفر)}."""
    by_tmdb = lambda m: (0 if M.poster_file(m.get("poster")) else 1, -m.get("added", 0))   # noqa: E731
    f = {}
    title = M.pick_title(members)
    f["title"] = (title, "m3u", next(m["service"] for m in members if m["name"] == title))
    year = next((m["year"] for m in members if m["year"]), 0)
    f["year"] = (year or None, "m3u", next((m["service"] for m in members if m["year"]), members[0]["service"]))
    for field in ("poster", "backdrop"):
        v, m = M.pick(members, field, by_tmdb)
        f[field] = (v, "m3u" if field == "poster" else "xtream", m["service"] if m else None)
    v, m = M.pick(members, "plot", lambda m: -len(m.get("plot") or ""))
    f["overview"] = (v, "xtream", m["service"] if m else None)
    rated = [m for m in members if m.get("rating")]
    best = max(rated, key=lambda m: m["rating"]) if rated else None
    f["rating"] = (best["rating"] if best else None, "xtream", best["service"] if best else None)
    freq = {}
    for m in members:
        for g in m.get("genres") or ():
            freq[g] = freq.get(g, 0) + 1
    genres = [g for g, _ in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[:GENRES_MAX]]
    ids = {m["tmdb_id"] for m in members if m.get("tmdb_id")}
    f["tmdb_id"] = (ids.pop() if len(ids) == 1 else None, "xtream", next((m["service"] for m in members if m.get("tmdb_id")), None))
    f["genres_json"] = (json.dumps(genres, ensure_ascii=False) if genres else None,
                        "derived" if len({m["service"] for m in members if m.get("genres")}) > 1 else "xtream",
                        next((m["service"] for m in members if m.get("genres")), None))
    return f


def _snippet(m):
    return {"service": m["service"], "name": m["name"], "year": m["year"] or None, "groups": m.get("groups") or [],
            "poster": M.poster_file(m.get("poster")) or ("panel" if m.get("poster") else ""),
            "plot": (m.get("plot") or "")[:REVIEW_SNIPPET], "genres": m.get("genres") or [],
            "seasons": len(m.get("seasons") or {}) or None}


# ================= البناء =================
def build(data_dir, force=False, now=None):
    """يبني أو يحدّث القاعدة من الفهارس ← إحصاءات البناء، أو ‏None إن لم يتغيّر شيء (و‏force=False)."""
    now = int(now or time.time())
    with seo_db.lock(data_dir):
        con = seo_db.connect(data_dir)
        try:
            t0 = time.time()
            if not force and seo_db.state(con, "built_at") and seo_db.state(con, "signatures") == signatures(data_dir):
                return None                   # لا فهرس تغيّر: لا قراءة أصلًا (الدورة كل عشر دقائق)
            st = seo_db.settings(con)
            _progress[os.path.abspath(data_dir)] = {"started": time.time()}
            items, conflicts, sigs = load_items(data_dir, st)
            _prog(data_dir, "cluster", 0, 1)
            clusters, reviews = M.cluster(items, st)
            _prog(data_dir, "apply", 0, max(1, len(clusters)))
            with con:
                res = _apply(con, data_dir, items, clusters, reviews + conflicts, sigs, now)
                res["phonetic_refreshed"] = refresh_phonetic(con)
                res["person_norm_refreshed"] = refresh_person_norm(con)
            _prog(data_dir, "finish", 1, 1)
            res["seconds"] = round(time.time() - t0, 2)
            _last[os.path.abspath(data_dir)] = {"ok": True, "at": now, **res}
            with con:
                seo_db.set_state(con, "last_build", _last[os.path.abspath(data_dir)])   # تبقى بعد إعادة تشغيل الخادم (النشر)
            _stats_cache.pop(os.path.abspath(data_dir), None)      # الأعداد المحفوظة قبل البناء لم تعد صالحة
            return res
        finally:
            con.close()


def _apply(con, data_dir, items, clusters, reviews, sigs, now):
    links, by_stream = {}, {}
    for r in con.execute("SELECT service_key, kind, local_key, stream_id, stream_ids_json, content_id FROM content_service"):
        links[(r["service_key"], r["kind"], r["local_key"])] = r["content_id"]
        for sid in set(json.loads(r["stream_ids_json"] or "[]")) | ({r["stream_id"]} if r["stream_id"] else set()):
            by_stream[(r["service_key"], r["kind"], sid)] = r["content_id"]

    alias_of = {}
    for r in con.execute("SELECT content_id, alias_norm FROM content_alias"):
        alias_of.setdefault(r["content_id"], set()).add(r["alias_norm"])
    stream_reuse = []                             # رقم بثٍّ عاد باسمٍ آخر تمامًا: اللوحة أعادت استعماله لعملٍ آخر — لا يُربط
    known_cache = {}

    def known(m):
        """الكيانات التي رُبط بها عضوٌ من قبل: بمفتاحه، وبكل أرقام بثّه (مدخلاتٌ كانت كياناتٍ مفرّقة بالمواسم ثم طُويت
        في عنصرٍ واحد: كلها تُعرَف فتُدمج بتحويلٍ ومراجعة — لا تُترك غائبةً بلا أثر). رقم البثّ وحده لا يكفي: يجب أن يبقى
        الاسم من أسماء الكيان، وإلا فاللوحة أعادت استعمال الرقم لعملٍ آخر (6616: «محكوم - السجين» ← «المحنك»)."""
        ck = (m["service"], m["kind"], m["local_key"])
        if ck in known_cache:                     # يُسأل مرتين (تثبيت الهوية ثم الحلقة): نتيجةٌ واحدة وتسجيلٌ واحد لإعادة الاستعمال
            return known_cache[ck]
        out = known_cache[ck] = set()
        k = links.get(ck)
        if k:
            out.add(k)
        nm = M.norm(m["name"])
        for sid in m.get("stream_ids") or ([m["stream_id"]] if m.get("stream_id") else []):
            k = by_stream.get((m["service"], m["kind"], sid))
            if k and k not in out:
                if nm in alias_of.get(canon(k), set()) or M.phonetic(m["name"]) in {M.phonetic(a) for a in alias_of.get(canon(k), set())}:
                    out.add(k)
                else:
                    stream_reuse.append({"service": m["service"], "stream_id": sid, "name": m["name"], "old_entity": canon(k)})
        return out
    live_before = {r[0] for r in con.execute("SELECT id FROM content WHERE merged_into IS NULL AND available=1")}
    merged = {r["id"]: r["merged_into"] for r in con.execute("SELECT id, merged_into FROM content WHERE merged_into IS NOT NULL")}

    def canon(cid):
        seen = set()
        while merged.get(cid) and cid not in seen:
            seen.add(cid)
            cid = merged[cid]
        return cid

    slugs = {r["slug"] for r in con.execute("SELECT slug FROM content")}
    manual = {}                                   # (content_id) ← {الحقول اليدوية}
    for r in con.execute("SELECT entity_id, field FROM provenance WHERE entity='content' AND source='manual'"):
        manual.setdefault(r["entity_id"], set()).add(r["field"])
    claimed, extra_reviews = set(), []
    n_new = n_merged = n_split = 0
    seo_sources.seed_rules(con, now)
    rls = seo_sources.rules(con)
    st = seo_db.settings(con)
    # هوية TMDB المُتحقَّقة لا تُفكّ بغياب دليل القوائم: عناقيد أعضاؤها كانوا معًا في كيانٍ واحد بمعرّفٍ مُتحقَّق تبقى معًا ما لم
    # **يتناقض** الدليل (سنتان/معرّفان مختلفان أو قصّتان) — وإلا انقسم عضو فالكون كل بناء ثم عاد مدمجًا بالمعرّف نفسه (دوّامة
    # «انفصال ← دمج» برابطٍ جديد وتحويلٍ جديد في كل مرة، كما في Prison Break وOne Piece).
    verified = {r[0] for r in con.execute("SELECT id FROM content WHERE match='tmdb' AND tmdb_id IS NOT NULL AND merged_into IS NULL")}
    owners, kept_by_identity = {}, 0
    for ci, members_idx in enumerate(clusters):
        for k in {canon(k) for i in members_idx for k in known(items[i])} & verified:
            owners.setdefault(k, []).append(ci)
    parent = list(range(len(clusters)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for k, cis in owners.items():
        base = cis[0]
        for ci in cis[1:]:
            sc, _ = M.pair_score(items[clusters[base][0]], items[clusters[ci][0]], st)
            if sc is not None and sc != M.DISTINCT and find(ci) != find(base):
                parent[find(ci)] = find(base)
                kept_by_identity += 1
    if kept_by_identity:
        grouped = {}
        for ci, members_idx in enumerate(clusters):
            grouped.setdefault(find(ci), []).extend(members_idx)
        clusters = list(grouped.values())
    cid_of = {}                                   # فهرس العضو ← معرّف الكيان
    inserted, merged_now = set(), set()
    claimed_by = {}                               # الكيان ← فهارس أعضاء العنقود الذي ادّعاه في هذا البناء
    for ci_, members_idx in enumerate(clusters):
        if ci_ % 500 == 0:
            _prog(data_dir, "apply", ci_, len(clusters))
        members = [items[i] for i in members_idx]
        ids_all = {canon(k) for m in members for k in known(m)}
        ids = {i for i in ids_all if i not in claimed}
        if not ids:
            cid = _insert(con, members, slugs, now)
            n_new += 1
            inserted.add(cid)
            if ids_all:
                n_split += 1                      # كان عضوًا في كيانٍ ادّعاه عنقودٌ آخر: كيانٌ جديد ويُراجَع — ولماذا لم يبقَ معه
                causes, why = set(), []
                for old in sorted(ids_all):
                    other = [items[i] for i in claimed_by.get(old, [])]
                    if not other:
                        continue
                    sc, w = M.pair_score(members[0], other[0], st)
                    causes.add("contradiction" if sc == M.DISTINCT else "conflict" if sc is None else "no_evidence")
                    why += w
                extra_reviews.append({"kind": "split_entity", "key": f"split:{cid}", "type": members[0]["type"],
                                      "name": members[0]["name"], "items": members_idx, "from": sorted(ids_all),
                                      "cause": sorted(causes) or ["unknown"], "pair": sorted(set(why)),
                                      "services": sorted({m["service"] for m in members}), "why": ["links_moved"]})
        else:
            cid = min(ids)
            for other in sorted(ids - {cid}):   # كيانان كانا منفصلين واجتمعت قرائنهما الآن: يبقى الأقدم، والآخر يُدمج فيه
                seo_db.merge_content(con, other, cid, reason=f"links joined in build ({members[0]['service']}: {members[0]['name']})", now=now)   # 301 + بند مراجعة
                merged[other] = cid
                merged_now.add(other)
                n_merged += 1
            _update(con, cid, members, manual.get(cid, set()), now)
        claimed.add(cid)
        claimed_by[cid] = list(members_idx)
        for i in members_idx:
            cid_of[i] = cid
        _link(con, cid, members, now)
        _aliases(con, cid, members, now)
        if members[0]["type"] == "series":
            _seasons(con, cid, members, now)
        groups = [g for m in members for g in m.get("groups") or []]
        prio = seo_sources.apply_hints(con, cid, groups, rls, st, now)       # قرائن الأقسام (لا تُدخل الهب) والأولوية
        if any(m.get("added") and m["added"] > now - 30 * 86400 for m in members):
            prio = min(prio, 2)                                             # الأحدث إضافةً قبل الباقي
        has_xt = any(C.url_of(data_dir, m["service"]) for m in members)
        seo_sources.enqueue(con, cid, (["xtream"] if has_xt else []) + ["tmdb"], prio, now)
    # ما لم يُرَ في هذا البناء من روابط السيرفرات الموجودة: غائبٌ (لا يُحذف)
    seen_keys = {(m["service"], m["kind"], m["local_key"]) for m in items}
    for k, cid in links.items():
        if k not in seen_keys and k[0] in sigs:
            con.execute("UPDATE content_service SET present=0 WHERE service_key=? AND kind=? AND local_key=? AND present=1", k)
    con.execute("UPDATE content SET available=0, updated_at=? WHERE merged_into IS NULL AND available=1 AND id NOT IN "
                "(SELECT content_id FROM content_service WHERE present=1)", (now,))
    con.execute("UPDATE content SET available=1, updated_at=? WHERE merged_into IS NULL AND available=0 AND id IN "
                "(SELECT content_id FROM content_service WHERE present=1)", (now,))
    _prog(data_dir, "finish", 0, 1)
    n_rev = _reviews(con, items, reviews + extra_reviews, now)
    # تسوية عدد الكيانات: من أين جاء كل فرقٍ بين ما قبل البناء وما بعده (لا «تم الدمج» وحدها)
    live_after = {r[0] for r in con.execute("SELECT id FROM content WHERE merged_into IS NULL AND available=1")}
    lost, gained = live_before - live_after, live_after - live_before
    recon = {"at": now, "before": len(live_before), "after": len(live_after), "delta": len(live_after) - len(live_before),
             "inserted": len(gained & inserted), "split": n_split, "returned": len(gained - inserted),
             "merged": len(lost & merged_now), "went_unavailable": len(lost - merged_now),
             "unavailable_total": con.execute("SELECT COUNT(*) FROM content WHERE merged_into IS NULL AND available=0").fetchone()[0],
             "merged_total": con.execute("SELECT COUNT(*) FROM content WHERE merged_into IS NOT NULL").fetchone()[0]}
    recon["explained"] = recon["inserted"] + recon["returned"] - recon["merged"] - recon["went_unavailable"] == recon["delta"]
    recon["stream_id_reused"] = len(stream_reuse)
    recon["kept_by_verified_identity"] = kept_by_identity
    seo_db.set_state(con, "reconciliation", recon)
    seo_db.set_state(con, "reconciliations", ((seo_db.state(con, "reconciliations") or []) + [recon])[-100:])   # تاريخ البناءات: يفسّر العدّادات بين لقطتين
    seo_db.set_state(con, "stream_reuse", stream_reuse[:200])
    seo_db.set_state(con, "signatures", sigs)
    seo_db.set_state(con, "built_at", now)
    return {"items": len(items), "clusters": len(clusters), "new": n_new, "merged": n_merged, "split": n_split,
            "reviews_open": n_rev, "services": sorted(sigs), "reconciliation": recon}


def refresh_phonetic(con):
    """تغيّر المفتاح الصوتي في الكود (‏seo_search.PHONETIC_VERSION) ← تُعاد مفاتيح كل الأسماء المخزَّنة مرةً واحدة، فلا يبقى
    اسمٌ قديم بمفتاحٍ قديم («One Piece» = «n bs» بينما الجديد «wn bs»). ← عدد ما أُعيد."""
    import seo_search
    if seo_db.state(con, "phonetic_version") == seo_search.PHONETIC_VERSION:
        return 0
    rows = con.execute("SELECT rowid, alias, phonetic FROM content_alias").fetchall()
    upd = [(seo_search.phonetic(r["alias"]), r["rowid"]) for r in rows if seo_search.phonetic(r["alias"]) != (r["phonetic"] or "")]
    con.executemany("UPDATE content_alias SET phonetic=? WHERE rowid=?", upd)
    seo_db.set_state(con, "phonetic_version", seo_search.PHONETIC_VERSION)
    return len(upd)


def refresh_person_norm(con):
    """مفتاح اسم الشخص لمن لا مفتاح له (قاعدةٌ أقدم) — مرةً واحدة."""
    rows = con.execute("SELECT id, name FROM person WHERE name_norm IS NULL").fetchall()
    con.executemany("UPDATE person SET name_norm=? WHERE id=?", [(M.person_key(r["name"]), r["id"]) for r in rows])
    return len(rows)


def _insert(con, members, slugs, now):
    f = _entity_fields(members)
    title, year = f["title"][0], f["year"][0] or 0
    name, src = M.slug_source({"title": title})          # الإنجليزي ثم الأصلي ثم النقحرة — ويُولَّد مرةً واحدة
    slug = M.unique_slug(lambda s: s in slugs, name, year)
    slugs.add(slug)
    added = [m["added"] for m in members if m.get("added")]
    cur = con.execute(
        "INSERT INTO content(type, slug, slug_source, title, year, overview, rating, poster, backdrop, genres_json, tmdb_id, "
        "match, confidence, available, first_seen, last_seen, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?)",
        (members[0]["type"], slug, src, title, year or None, f["overview"][0], f["rating"][0], f["poster"][0], f["backdrop"][0],
         f["genres_json"][0], None, "local", len(members),
         min(added) if added else now, max(added) if added else now, now, now))
    cid = cur.lastrowid
    seo_db.set_provenance(con, "content", cid, "slug", "derived", None, now)
    cand = f.pop("tmdb_id")[0]
    if cand:                                   # معرّف اللوحة مرشَّحٌ لا يُعتمد حتى يتحقّق (seo_sources.resolve_tmdb)
        seo_db.set_external(con, "content", cid, "tmdb", cand, verified=False, confidence=0.5, how="xtream-list", now=now)
    for field, (v, src, svc) in f.items():
        if v is not None:
            seo_db.set_provenance(con, "content", cid, field, src, svc, now)
    return cid


def _update(con, cid, members, manual, now):
    """حقول الكيان من أعضائه عبر ‏apply_fields: الحقل اليدوي لا يُمسّ، والمتغيّر يُسجَّل بمصدره وقيمته السابقة.
    ‏slug لا يُمسّ هنا أبدًا (يتبدّل بـ ‏change_slug وحده، بتحويل 301)."""
    f = {k: v for k, v in _entity_fields(members).items() if not (v[0] is None and k == "title")}
    cur = con.execute("SELECT title FROM content WHERE id=?", (cid,)).fetchone()
    names = {M.norm(m["name"]): m for m in members}
    if cur and cur["title"] and M.norm(cur["title"]) in names and "title" in f:
        f["title"] = (cur["title"], "m3u", names[M.norm(cur["title"])]["service"])   # العنوان المستقرّ يبقى ما دام من أسماء الأعضاء (لا يتقلّب بين السيرفرات)
    cand = f.pop("tmdb_id")[0]
    if cand and not seo_db.external(con, "content", cid).get("tmdb", {}).get("verified"):
        seo_db.set_external(con, "content", cid, "tmdb", cand, verified=False, confidence=0.5, how="xtream-list", now=now)
    seo_db.apply_fields(con, "content", cid, f, "m3u", now=now, manual=manual)
    row = con.execute("SELECT last_seen, confidence, merged_into FROM content WHERE id=?", (cid,)).fetchone()
    added = [m["added"] for m in members if m.get("added")]
    sets, args = [], []
    if added and (row["last_seen"] or 0) < max(added):
        sets.append("last_seen=?"); args.append(max(added))
    if row["confidence"] != len(members):
        sets.append("confidence=?"); args.append(len(members))
    if row["merged_into"] is not None:
        sets.append("merged_into=NULL")
    if sets:
        sets.append("updated_at=?"); args.append(now)
        con.execute(f"UPDATE content SET {', '.join(sets)} WHERE id=?", (*args, cid))


def _link(con, cid, members, now):
    con.executemany(
        "INSERT INTO content_service(content_id, service_key, kind, local_key, name, year, stream_id, added, seasons_json, "
        "groups_json, versions_json, raw_names_json, series_id, stream_ids_json, present, first_seen, seen_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?) "
        "ON CONFLICT(service_key, kind, local_key) DO UPDATE SET content_id=excluded.content_id, name=excluded.name, "
        "year=excluded.year, stream_id=excluded.stream_id, added=excluded.added, seasons_json=excluded.seasons_json, "
        "groups_json=excluded.groups_json, versions_json=excluded.versions_json, raw_names_json=excluded.raw_names_json, "
        "series_id=excluded.series_id, stream_ids_json=excluded.stream_ids_json, present=1, seen_at=excluded.seen_at",
        [(cid, m["service"], m["kind"], m["local_key"], m["name"], m["year"] or None, m["stream_id"] or None,
          m["added"] or None, json.dumps(sorted(m["seasons"].items())) if m["seasons"] else None,
          json.dumps(m["groups"], ensure_ascii=False) if m["groups"] else None,
          json.dumps(m.get("versions") or []) if m.get("versions") else None,
          json.dumps(m.get("raw_names") or [m.get("raw_name")], ensure_ascii=False), m.get("series_id") or None,
          json.dumps(m.get("stream_ids") or ([m["stream_id"]] if m.get("stream_id") else [])), now, now)
         for m in members])


def _aliases(con, cid, members, now):
    """الاسم بلا لاحقة (‏title) والأسماء كما جاءت من السيرفر (‏raw، بلاحقتها) — كلها إلى الكيان نفسه، بمفتاحها الصوتي."""
    rows = []
    for m in members:
        names = [(m["name"], "title")] + [(r, "raw") for r in (m.get("raw_names") or [m.get("raw_name") or ""]) if r and r != m["name"]] \
            + [(o, "original") for o in (m.get("originals") or ([m["original"]] if m.get("original") else []))]
        for n, kind in names:
            if M.norm(n):
                rows.append((cid, n, M.norm(n), None, "m3u", m["service"], now, kind, M.phonetic(n)))
    con.executemany("INSERT OR IGNORE INTO content_alias(content_id, alias, alias_norm, lang, source, service_key, at, kind, phonetic) "
                    "VALUES (?,?,?,?,?,?,?,?,?)", rows)


def _seasons(con, cid, members, now):
    seasons = {}
    for m in members:
        for s, n in m["seasons"].items():
            seasons[s] = max(seasons.get(s, 0), n)
    if not seasons:
        return
    con.executemany(
        "INSERT INTO season(content_id, number, episode_count, updated_at) VALUES (?,?,?,?) "
        "ON CONFLICT(content_id, number) DO UPDATE SET episode_count=excluded.episode_count, updated_at=excluded.updated_at "
        "WHERE season.episode_count != excluded.episode_count",
        [(cid, s, n, now) for s, n in seasons.items()])
    seo_db.set_provenance(con, "content", cid, "seasons", "derived", None, now)


def _reviews(con, items, reviews, now):
    keys = set()
    for r in reviews:
        keys.add(r["key"])
        payload = {"type": r.get("type"), "name": r.get("name"), "why": r.get("why") or [],
                   "items": [_snippet(items[i]) for i in r.get("items") or []]}
        for k in ("service", "entries", "from", "cause", "pair", "services"):
            if k in r:
                payload[k] = r[k]
        con.execute(
            "INSERT INTO review(kind, key, payload_json, status, created_at, updated_at) VALUES (?,?,?,'open',?,?) "
            "ON CONFLICT(key) DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at, "
            "status=CASE WHEN review.status='stale' THEN 'open' ELSE review.status END",
            (r["kind"], r["key"], json.dumps(payload, ensure_ascii=False), now, now))
    # بنودٌ آلية لم تعد قائمة (اندمج العنصران أو غاب أحدهما): قديمة، لا تُحذف
    rows = con.execute("SELECT id, key FROM review WHERE status='open' AND kind IN (%s)"
                       % ",".join("?" * len(STATE_KINDS)), STATE_KINDS).fetchall()
    stale = [r["id"] for r in rows if r["key"] not in keys]
    con.executemany("UPDATE review SET status='stale', updated_at=? WHERE id=?", [(now, i) for i in stale])
    con.execute("UPDATE review SET status='stale', updated_at=? WHERE status='open' AND kind='split_entity' AND "
                "CAST(substr(key, 7) AS INTEGER) IN (SELECT id FROM content WHERE merged_into IS NOT NULL)", (now,))   # عاد إلى كيانه
    return con.execute("SELECT COUNT(*) FROM review WHERE status='open'").fetchone()[0]


# ================= الدورة وصفحة المدير =================
def tick(data_dir):
    """في دورة المحتوى بعد السحب: يبني إن تغيّر فهرسٌ. لا يرفع شيئًا."""
    try:
        return build(data_dir)
    except Exception as e:  # noqa: BLE001 — الدورة لا تتوقّف
        _last[os.path.abspath(data_dir)] = {"ok": False, "at": int(time.time()), "error": str(e)[:300]}
        return None


def start_build(data_dir, force=True):
    """«ابنِ الآن» من صفحة المدير: في خيطٍ، وبناءٌ واحد في وقته ← هل بدأ؟"""
    k = os.path.abspath(data_dir)
    t = _running.get(k)
    if t and t.is_alive():
        return False

    def run():
        try:
            build(data_dir, force=force)
        except Exception as e:  # noqa: BLE001
            _last[k] = {"ok": False, "at": int(time.time()), "error": str(e)[:300]}

    t = _running[k] = threading.Thread(target=run, daemon=True)
    t.start()
    return True


_stats_cache = {}             # مسار البيانات ← (وقت، إحصاءات): أثناء البناء تُعاد آخر إحصاءاتٍ محسوبة بدل انتظار استعلاماتٍ ثقيلة


def stats(data_dir, light=False):
    """أعداد الطبقة لصفحة المدير والتقرير — من القاعدة وحدها، ولا تبني. ‏light أو بناءٌ جارٍ: آخر نسخةٍ محسوبة (إن وُجدت)
    مع حال التشغيل، فلا ينتظر المدير دقائق حتى تُحسب الأعداد على قاعدةٍ كبيرة."""
    con = seo_db.connect(data_dir, create=False)
    k = os.path.abspath(data_dir)
    running = bool(_running.get(k) and _running[k].is_alive())
    if con is None:
        return {"ok": True, "built": False, "running": running, "last": _last.get(k)}
    last = _last.get(k) or seo_db.state(con, "last_build")    # من الذاكرة، وإلا من القاعدة (بعد إعادة التشغيل)
    cached = _stats_cache.get(k)
    if cached and (light or running or time.time() - cached[0] < 15):
        con.close()
        return {**cached[1], "running": running, "last": last, "cached_at": int(cached[0]), "progress": progress(data_dir) if running else None}
    try:
        q = lambda sql, *a: con.execute(sql, a).fetchone()[0]   # noqa: E731
        live = "merged_into IS NULL AND available=1"
        per_service = {}
        for r in con.execute("SELECT service_key, kind, COUNT(*) n, SUM(present) p FROM content_service GROUP BY 1, 2"):
            per_service.setdefault(r["service_key"], {})[r["kind"]] = {"linked": r["n"], "present": r["p"]}
        shared = {}
        for r in con.execute(f"SELECT c.type, n, COUNT(*) k FROM (SELECT content_id, COUNT(*) n FROM content_service "
                             f"WHERE present=1 GROUP BY content_id) s JOIN content c ON c.id=s.content_id WHERE {live} "
                             f"GROUP BY c.type, n"):
            shared.setdefault(r["type"], {})[str(r["n"])] = r["k"]
        reviews = {r["kind"]: r["n"] for r in con.execute("SELECT kind, COUNT(*) n FROM review WHERE status='open' GROUP BY kind")}
        out = {
            "ok": True, "built": bool(seo_db.state(con, "built_at")), "running": running, "last": last, "progress": progress(data_dir) if running else None,
            "built_at": seo_db.state(con, "built_at"), "services": sorted(seo_db.state(con, "signatures") or {}),
            "entities": {"total": q(f"SELECT COUNT(*) FROM content WHERE {live}"),
                         "movie": q(f"SELECT COUNT(*) FROM content WHERE {live} AND type='movie'"),
                         "series": q(f"SELECT COUNT(*) FROM content WHERE {live} AND type='series'"),
                         "unavailable": q("SELECT COUNT(*) FROM content WHERE merged_into IS NULL AND available=0"),
                         "merged": q("SELECT COUNT(*) FROM content WHERE merged_into IS NOT NULL"),
                         "by_match": {r["match"]: r["n"] for r in con.execute(
                             f"SELECT match, COUNT(*) n FROM content WHERE {live} GROUP BY match")}},
            "by_services": shared,                       # النوع ← {عدد السيرفرات: عدد الكيانات}
            "per_service": per_service,
            "links": q("SELECT COUNT(*) FROM content_service WHERE present=1"),
            "aliases": q("SELECT COUNT(*) FROM content_alias"),
            "seasons": q("SELECT COUNT(*) FROM season"),
            "episodes": q("SELECT COALESCE(SUM(episode_count),0) FROM season"),
            "episodes_official": q("SELECT COALESCE(SUM(episodes_official),0) FROM season"),
            "series_with_official": q("SELECT COUNT(*) FROM content WHERE merged_into IS NULL AND episodes_official IS NOT NULL"),
            "reconciliation": seo_db.state(con, "reconciliation"),
            "reviews": {"open": sum(reviews.values()), "by_kind": reviews,
                        "resolved": q("SELECT COUNT(*) FROM review WHERE status='resolved'"),
                        "stale": q("SELECT COUNT(*) FROM review WHERE status='stale'")},
            "provenance": {r["source"]: r["n"] for r in con.execute("SELECT source, COUNT(*) n FROM provenance GROUP BY source")},
            "queue": seo_sources.queue_stats(con),
            "taxonomy": {f"{r['kind']}:{r['key']}": {"confirmed": r["c"], "hint": r["h"]} for r in con.execute(
                "SELECT t.kind, t.key, SUM(ct.source IN ('tmdb','manual')) c, SUM(ct.source='hint') h FROM taxonomy t JOIN content_taxonomy ct ON ct.taxonomy_id=t.id "
                "JOIN content c ON c.id=ct.content_id AND c.merged_into IS NULL AND c.available=1 WHERE t.kind IN ('hub','anime_kind') GROUP BY 1, 2")},
            "people": q("SELECT COUNT(*) FROM person"), "episodes_detailed": q("SELECT COUNT(*) FROM episode"),
            "settings": {k: ("•••" if k in seo_db.SECRET_SETTINGS and v else v) for k, v in seo_db.settings(con).items()},
            "db_bytes": os.path.getsize(seo_db.path(data_dir)),
        }
        _stats_cache[k] = (time.time(), out)
        return out
    finally:
        con.close()


def reviews(data_dir, status="open", kind="", limit=100, offset=0):
    con = seo_db.connect(data_dir, create=False)
    if con is None:
        return []
    try:
        sql, args = "SELECT id, kind, key, payload_json, status, created_at, updated_at FROM review WHERE status=?", [status]
        if kind:
            sql += " AND kind=?"; args.append(kind)
        sql += " ORDER BY kind, id LIMIT ? OFFSET ?"
        args += [max(1, min(int(limit), 500)), max(0, int(offset))]
        return [{"id": r["id"], "kind": r["kind"], "key": r["key"], "status": r["status"], "created_at": r["created_at"],
                 "updated_at": r["updated_at"], **json.loads(r["payload_json"])} for r in con.execute(sql, args)]
    finally:
        con.close()


def report(data_dir):
    """تقرير المرحلة نصًّا (للمدير بعد النشر): الأعداد والمراجعات والمخطط."""
    s = stats(data_dir)
    if not s.get("built"):
        return "لم تُبنَ القاعدة بعد." + (f" آخر محاولة: {s['last']}" if s.get("last") else "")
    e, lines = s["entities"], []
    lines.append(f"الكيانات الموحّدة: {e['total']:,} (أفلام {e['movie']:,} · مسلسلات {e['series']:,}) — "
                 f"غائب {e['unavailable']:,} · مدمج {e['merged']:,}")
    for typ, d in s["by_services"].items():
        lines.append(f"  {typ}: " + " · ".join(f"في {n} سيرفر: {k:,}" for n, k in sorted(d.items(), key=lambda kv: int(kv[0]))))
    for svc, d in s["per_service"].items():
        lines.append(f"  {svc}: " + " · ".join(f"{kind} {v['present']:,}" for kind, v in sorted(d.items())))
    lines.append(f"الروابط كيان↔سيرفر: {s['links']:,} · الأسماء البديلة: {s['aliases']:,} · المواسم: {s['seasons']:,} · "
                 f"الحلقات المدرجة في القوائم (عناصر، قد تكون أجزاءً): {s['episodes']:,} · الرسمية (TMDB، لـ {s['series_with_official']:,} مسلسلًا): {s['episodes_official']:,}")
    rc = s.get("reconciliation")
    if rc:
        lines.append(f"تسوية آخر بناء: قبل {rc['before']:,} ← بعد {rc['after']:,} (الفرق {rc['delta']:+,}) = جديد {rc['inserted']:,} (منها انفصال {rc['split']:,}) "
                     f"+ عاد {rc['returned']:,} − مدمج {rc['merged']:,} − غاب {rc['went_unavailable']:,} — {'متّسقة' if rc['explained'] else 'غير متّسقة!'} · "
                     f"إجمالي الغائب {rc['unavailable_total']:,} · إجمالي المدمج {rc['merged_total']:,}")
    r = s["reviews"]
    lines.append(f"تحتاج مراجعة: {r['open']:,} — " + " · ".join(f"{k}: {n:,}" for k, n in sorted(r["by_kind"].items())))
    lines.append(f"المصادر: " + " · ".join(f"{k}: {n:,}" for k, n in sorted(s["provenance"].items())))
    lines.append(f"حجم القاعدة: {s['db_bytes'] / 1048576:.1f} MB · آخر بناء: {time.strftime('%Y-%m-%d %H:%M', time.gmtime(s['built_at']))} UTC")
    con = seo_db.connect(data_dir, create=False)
    if con:
        sm = seo_sources.summary(con); con.close()
        lines.append(f"المرحلة 2: مطابقات عالية الثقة {sm['high_confidence_matches']:,} · بلا TMDB {sm['no_tmdb']:,} · تعارضات {sm['conflicts']:,} · "
                     f"تحتاج مراجعة {sm['needs_review']['total']:,} · تركي مؤكّد {sm['turkish_confirmed']:,} · أنمي مؤكّد {sm['anime_confirmed']:,} {sm['anime_by_kind']} · "
                     f"قرائن أقسام بلا تأكيد {sm['hints_only']} · نسخ {sm['versions']:,} · أشخاص {sm['people']:,} · حلقات مفصّلة {sm['episodes_detailed']:,} · الطابور {sm['queue']}")
    return "\n".join(lines)


def main(argv):
    data_dir = os.environ.get("XM_DATA") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    cmd = argv[1] if len(argv) > 1 else "stats"
    opt = {a.lstrip("-").split("=")[0]: (a.split("=", 1)[1] if "=" in a else True) for a in argv[2:] if a.startswith("--")}
    if cmd == "build":
        res = build(data_dir, force=bool(opt.get("force")))
        print(json.dumps(res, ensure_ascii=False, indent=1) if res else "لم يتغيّر شيء (أضف --force لإعادة البناء)")
    elif cmd == "stats":
        print(json.dumps(stats(data_dir), ensure_ascii=False, indent=1))
    elif cmd == "report":
        print(report(data_dir))
        con = seo_db.connect(data_dir, create=False)
        if con and opt.get("schema"):
            print("\n" + seo_db.schema_text(con))
    elif cmd == "search-report":                 # جودة البحث: ما يصير إليه كل اسم (كيان · اقتراح · لا شيء)
        import seo_search
        con = seo_db.connect(data_dir, create=False)
        if con is None:
            print("لم تُبنَ القاعدة بعد"); return
        idx, st = seo_search.load(con), seo_db.settings(con)
        names = [a for a in argv[2:] if not a.startswith("--")] or ["Prison Break", "person break", "Prison Brek", "بريزن بريك", "بريزون بريك",
                                                                     "طبيعة الحب", "طبيعة الحب مدبلج", "طبيعة الحب مترجم", "One Piece", "ون بيس", "وان بيس", "السجين", "العهد",
                                                                     "Dune 1984", "Dune 2021", "Breaking Bad", "بريكنغ باد", "بريكنج باد"]
        for q in names:
            print(json.dumps(seo_search.explain(con, idx, q, st), ensure_ascii=False))
        con.close()
    elif cmd == "review":
        for r in reviews(data_dir, kind=str(opt.get("kind") or ""), limit=int(opt.get("limit") or 50)):
            print(json.dumps(r, ensure_ascii=False))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)

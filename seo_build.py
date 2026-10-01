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

AUTO_KINDS = ("name_only", "conflict", "same_server_ambiguous", "merged_entities", "split_entity")
STATE_KINDS = ("name_only", "conflict", "same_server_ambiguous")     # حالٌ تزول بزوال سببها؛ والدمج والانفصال أحداثٌ تبقى حتى تُراجَع
REVIEW_SNIPPET = 160
GENRES_MAX = 5

_running = {}                 # مسار البيانات ← خيط البناء الجاري (زرّ «ابنِ الآن»)
_last = {}                    # مسار البيانات ← نتيجة آخر بناء أو خطؤه (لصفحة المدير)


# ================= القراءة من فهارس السيرفرات =================
def _signature(data_dir, srv):
    p = C._cat_path(data_dir, srv["key"])
    try:
        st = os.stat(p)
    except OSError:
        return None
    return [st.st_ino, st.st_mtime_ns, st.st_size, sorted(srv.get("hidden") or [])]


def _entry(kind, key, g, it):
    return {"type": kind, "service": key, "kind": kind, "name": it["n"], "year": int(it.get("y") or 0),
            "poster": it.get("p") or "", "backdrop": it.get("b") or "", "plot": it.get("d") or "",
            "genres": list(it.get("g") or ()), "rating": float(it.get("r") or 0), "added": int(it.get("a") or 0),
            "stream_id": int(it.get("i") or 0), "tmdb_id": int(it.get("t") or 0),
            "seasons": {int(a): int(b) for a, b in (it.get("s") or ())}, "groups": [g["name"]] if g.get("name") else []}


def _merge_entries(es):
    """مداخل قسمٍ أو أكثر لعنصرٍ واحد في السيرفر ← عنصرٌ واحد (أكبر ما رُئي: المواسم والتقييم والرقم؛ وأطول قصة)."""
    rec = dict(es[0], genres=list(es[0]["genres"]), seasons=dict(es[0]["seasons"]), groups=list(es[0]["groups"]))
    for e in es[1:]:
        for f in ("poster", "backdrop", "plot", "year", "tmdb_id"):
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
                    by_name.setdefault((kind, M.norm(it["n"])), []).append(_entry(kind, key, g, it))
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
    for srv in C.servers(data_dir):
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
            items, conflicts, sigs = load_items(data_dir, st)
            clusters, reviews = M.cluster(items, st)
            with con:
                res = _apply(con, items, clusters, reviews + conflicts, sigs, now)
            res["seconds"] = round(time.time() - t0, 2)
            _last[os.path.abspath(data_dir)] = {"ok": True, "at": now, **res}
            return res
        finally:
            con.close()


def _apply(con, items, clusters, reviews, sigs, now):
    links, by_stream = {}, {}
    for r in con.execute("SELECT service_key, kind, local_key, stream_id, content_id FROM content_service"):
        links[(r["service_key"], r["kind"], r["local_key"])] = r["content_id"]
        if r["stream_id"]:
            by_stream[(r["service_key"], r["kind"], r["stream_id"])] = r["content_id"]

    def known(m):
        """الكيان الذي رُبط به عضوٌ من قبل: بمفتاحه، وإلا برقم بثّه (مفتاحٌ تبدّل لزوال غموضٍ أو زواله)."""
        k = (m["service"], m["kind"], m["local_key"])
        return links.get(k) or by_stream.get((m["service"], m["kind"], m["stream_id"]))
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
    cid_of = {}                                   # فهرس العضو ← معرّف الكيان
    for members_idx in clusters:
        members = [items[i] for i in members_idx]
        ids = {canon(known(m)) for m in members if known(m)}
        ids = {i for i in ids if i not in claimed}
        if not ids:
            cid = _insert(con, members, slugs, now)
            n_new += 1
            if any(known(m) for m in members):
                n_split += 1                      # كان عضوًا في كيانٍ ادّعاه عنقودٌ آخر: كيانٌ جديد ويُراجَع
                extra_reviews.append({"kind": "split_entity", "key": f"split:{cid}", "type": members[0]["type"],
                                      "name": members[0]["name"], "items": members_idx, "why": ["links_moved"]})
        else:
            cid = min(ids)
            for other in sorted(ids - {cid}):   # كيانان كانا منفصلين واجتمعت قرائنهما الآن: يبقى الأقدم
                con.execute("UPDATE content SET merged_into=?, available=0, updated_at=? WHERE id=?", (cid, now, other))
                merged[other] = cid
                n_merged += 1
                extra_reviews.append({"kind": "merged_entities", "key": f"merged:{cid}:{other}", "type": members[0]["type"],
                                      "name": members[0]["name"], "items": members_idx,
                                      "why": [f"entity {other} merged into {cid}"]})
            _update(con, cid, members, manual.get(cid, set()), now)
        claimed.add(cid)
        for i in members_idx:
            cid_of[i] = cid
        _link(con, cid, members, now)
        _aliases(con, cid, members, now)
        if members[0]["type"] == "series":
            _seasons(con, cid, members, now)
    # ما لم يُرَ في هذا البناء من روابط السيرفرات الموجودة: غائبٌ (لا يُحذف)
    seen_keys = {(m["service"], m["kind"], m["local_key"]) for m in items}
    for k, cid in links.items():
        if k not in seen_keys and k[0] in sigs:
            con.execute("UPDATE content_service SET present=0 WHERE service_key=? AND kind=? AND local_key=? AND present=1", k)
    con.execute("UPDATE content SET available=0, updated_at=? WHERE merged_into IS NULL AND available=1 AND id NOT IN "
                "(SELECT content_id FROM content_service WHERE present=1)", (now,))
    con.execute("UPDATE content SET available=1, updated_at=? WHERE merged_into IS NULL AND available=0 AND id IN "
                "(SELECT content_id FROM content_service WHERE present=1)", (now,))
    n_rev = _reviews(con, items, reviews + extra_reviews, now)
    seo_db.set_state(con, "signatures", sigs)
    seo_db.set_state(con, "built_at", now)
    return {"items": len(items), "clusters": len(clusters), "new": n_new, "merged": n_merged, "split": n_split,
            "reviews_open": n_rev, "services": sorted(sigs)}


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
         f["genres_json"][0], f["tmdb_id"][0], "xtream" if f["tmdb_id"][0] else "local", len(members),
         min(added) if added else now, max(added) if added else now, now, now))
    cid = cur.lastrowid
    seo_db.set_provenance(con, "content", cid, "slug", "derived", None, now)
    for field, (v, src, svc) in f.items():
        if v is not None:
            seo_db.set_provenance(con, "content", cid, field, src, svc, now)
    return cid


def _update(con, cid, members, manual, now):
    """حقول الكيان من أعضائه عبر ‏apply_fields: الحقل اليدوي لا يُمسّ، والمتغيّر يُسجَّل بمصدره وقيمته السابقة.
    ‏slug لا يُمسّ هنا أبدًا (يتبدّل بـ ‏change_slug وحده، بتحويل 301)."""
    f = {k: v for k, v in _entity_fields(members).items() if not (v[0] is None and k == "title")}
    if f["tmdb_id"][0]:
        f["match"] = ("xtream", "derived", None)
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
        "groups_json, present, first_seen, seen_at) VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?) "
        "ON CONFLICT(service_key, kind, local_key) DO UPDATE SET content_id=excluded.content_id, name=excluded.name, "
        "year=excluded.year, stream_id=excluded.stream_id, added=excluded.added, seasons_json=excluded.seasons_json, "
        "groups_json=excluded.groups_json, present=1, seen_at=excluded.seen_at",
        [(cid, m["service"], m["kind"], m["local_key"], m["name"], m["year"] or None, m["stream_id"] or None,
          m["added"] or None, json.dumps(sorted(m["seasons"].items())) if m["seasons"] else None,
          json.dumps(m["groups"], ensure_ascii=False) if m["groups"] else None, now, now) for m in members])


def _aliases(con, cid, members, now):
    con.executemany(
        "INSERT OR IGNORE INTO content_alias(content_id, alias, alias_norm, lang, source, service_key, at) VALUES (?,?,?,?,?,?,?)",
        [(cid, m["name"], M.norm(m["name"]), None, "m3u", m["service"], now) for m in members if M.norm(m["name"])])


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
        for k in ("service", "entries"):
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


def stats(data_dir):
    """أعداد الطبقة لصفحة المدير والتقرير — من القاعدة وحدها، ولا تبني."""
    con = seo_db.connect(data_dir, create=False)
    k = os.path.abspath(data_dir)
    running = bool(_running.get(k) and _running[k].is_alive())
    if con is None:
        return {"ok": True, "built": False, "running": running, "last": _last.get(k)}
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
        return {
            "ok": True, "built": bool(seo_db.state(con, "built_at")), "running": running, "last": _last.get(k),
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
            "reviews": {"open": sum(reviews.values()), "by_kind": reviews,
                        "resolved": q("SELECT COUNT(*) FROM review WHERE status='resolved'"),
                        "stale": q("SELECT COUNT(*) FROM review WHERE status='stale'")},
            "provenance": {r["source"]: r["n"] for r in con.execute("SELECT source, COUNT(*) n FROM provenance GROUP BY source")},
            "settings": seo_db.settings(con),
            "db_bytes": os.path.getsize(seo_db.path(data_dir)),
        }
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
                 f"الحلقات (عدًّا): {s['episodes']:,}")
    r = s["reviews"]
    lines.append(f"تحتاج مراجعة: {r['open']:,} — " + " · ".join(f"{k}: {n:,}" for k, n in sorted(r["by_kind"].items())))
    lines.append(f"المصادر: " + " · ".join(f"{k}: {n:,}" for k, n in sorted(s["provenance"].items())))
    lines.append(f"حجم القاعدة: {s['db_bytes'] / 1048576:.1f} MB · آخر بناء: {time.strftime('%Y-%m-%d %H:%M', time.gmtime(s['built_at']))} UTC")
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
    elif cmd == "review":
        for r in reviews(data_dir, kind=str(opt.get("kind") or ""), limit=int(opt.get("limit") or 50)):
            print(json.dumps(r, ensure_ascii=False))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)

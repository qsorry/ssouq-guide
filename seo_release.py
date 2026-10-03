# -*- coding: utf-8 -*-
"""النشر الإنتاجي لطبقة الكيانات — المراحل 4–9، كلٌّ خلف بوابةٍ لا تُتجاوز (فشل البوابة = STOP وتراجع):

  4  رفع noindex عن **السكّان المستحقّين في اللقطة المعتمدة** وحدهم (sitemap-staging.xml للقطة = قائمة الاعتماد؛ ولا رابط خارجها):
     يُكتب `build_state.index_approved` ويُفعَّل `index_live`، ثم بوابة: كل مسارٍ معتمد 200 · وسم index بلا رأس noindex · canonical ذاتي ·
     `<html lang>` · قاعدة hreflang · لا مسار index خارج الاعتماد (على كل السكّان) · لا تبديل slug ولا تحويل ولا كيان — وإلا تراجعٌ كامل.
  5  خريطة الموقع العامة: المعتمد المستحقّ وحده يدخل /sitemap.xml (`sitemap_live`) بعد بوابة: العدد = المعتمد، لا تكرار، لا تحويلات،
     لا noindex، لا غير 200، لا canonical مخالف.
  6  IndexNow للمعتمد نفسه فقط (المفتاح يُخدم على الموقع). القبول (200/202) استلامٌ لا فهرسة.
  7  فحصٌ بعد النشر على المعتمد مقارنةً باللقطة: HTTP · canonical · hreflang · الفهرسة · عضوية الخريطة · التحويلات · slug · المعرّفات ·
     لا رابط غير متوقّع — وأي تراجع = STOP. (ومعه فحص HTTP حقيقي على الموقع إن طُلب.)
  8  التوسيع بدفعاتٍ محدودة (100 كيانٍ افتراضًا): إثراء TMDB ← هوية ← تسوية ← canonical ← hreflang ← أهلية ← تحويلات ← خريطة، ثم
     checkpoint (اعتماد الجديد وIndexNow له). دمجٌ أو انقسامٌ غير مفسَّر، تعارض هوية، تحويلٌ شاذّ، فشل canonical/hreflang = STOP عند الدفعة
     (تراجعٌ عن إثرائها كلّه، لا اعتماد).
  9  الاستمرار دفعةً بعد دفعة ما دامت السابقة PASS. ولا تتحوّل القاعدة كلها إلى indexable: يُفصل بين exists · enriched · live · eligible · indexable.

    python seo_release.py go --snapshot=20261003T004434Z [--expected=92] [--http]   # 4 ← 5 ← 6 ← 7 بالتتابع، STOP عند أول فشل
    python seo_release.py phase4|phase5|phase6|phase7 --snapshot=…                 # مرحلةٌ بعينها
    python seo_release.py batch [--n=100]                                           # دفعة توسيعٍ واحدة (المرحلة 8)
    python seo_release.py expand [--n=100] [--max=10]                               # دفعاتٌ متتابعة (المرحلة 9)
    python seo_release.py final                                                     # الحزمة النهائية للمراجعة (release-final.json/.txt)
    python seo_release.py status
"""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

import analytics
import content as C
import content_page as P
import guide_pages
import seo_db
import seo_pages
import seo_qa
import seo_sources

SITE = seo_pages.SITE
HOST = SITE.split("//", 1)[1]
STATE_KEY = "release"                       # build_state: حال المراحل {snapshot, phases: {"4": …}, batches: […], updated_at}
APPROVED_KEY = seo_pages.APPROVED_KEY
LOC_RX = re.compile(r"<loc>(.*?)</loc>")
_threads, _progress = {}, {}


# ================= أدوات =================
def _now(now):
    return int(now or time.time())


def _t(name, ok, detail=""):
    return seo_qa._t(name, ok, detail)


def _state(con):
    return seo_db.state(con, STATE_KEY) or {"snapshot": None, "phases": {}, "batches": [], "blocked": None}


def _save_state(con, rel, now):
    rel["updated_at"] = now
    rel["code"] = seo_sources.code_version()
    with con:
        seo_db.set_state(con, STATE_KEY, rel)


def _write(data_dir, name, obj):
    d = seo_sources.bundle_dir(data_dir)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, default=str)
    return p


def bundle_meta(data_dir):
    """bundle.json للقطة الحالية في مجلد المراجعة (معرّفها وبصمة كودها) أو None."""
    try:
        with open(os.path.join(seo_sources.bundle_dir(data_dir), "bundle.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def snapshot_urls(data_dir):
    """روابط خريطة الموقع التجريبية للقطة (sitemap-staging.xml التي كتبها الفحص النهائي مع bundle.json نفسها) ← مجموعة، أو None."""
    try:
        with open(os.path.join(seo_sources.bundle_dir(data_dir), "sitemap-staging.xml"), encoding="utf-8") as f:
            return {seo_pages._esc(u).replace("&amp;", "&") for u in LOC_RX.findall(f.read())}
    except OSError:
        return None


def _row(con, cid):
    return con.execute("SELECT * FROM content WHERE id=?", (cid,)).fetchone()


def _ar(path):
    return path[len(seo_db.EN):] if path.startswith(seo_db.EN + "/") else path


def invariants(con, ids):
    """الثوابت التي يجب ألّا تتغيّر بالنشر: التحويلات (عددًا وبصمةً)، الكيانات، المدمج، بنود الانقسام، وslug كلّ كيانٍ معتمد."""
    import hashlib
    red = [f"{r['path']}>{r['target']}" for r in con.execute("SELECT path, target FROM redirect ORDER BY path")]
    ids = sorted(set(int(i) for i in ids))
    slugs = {str(r["id"]): r["slug"] for r in con.execute(f"SELECT id, slug FROM content WHERE id IN ({','.join('?' * len(ids)) or 'NULL'})", ids)} if ids else {}
    return {"redirects": len(red), "redirects_hash": hashlib.sha1("\n".join(red).encode()).hexdigest()[:16],
            "entities": con.execute("SELECT COUNT(*) FROM content").fetchone()[0],
            "live": con.execute("SELECT COUNT(*) FROM content WHERE merged_into IS NULL AND available=1").fetchone()[0],
            "merged": con.execute("SELECT COUNT(*) FROM content WHERE merged_into IS NOT NULL").fetchone()[0],
            "split_reviews": con.execute("SELECT COUNT(*) FROM review WHERE kind='split_entity'").fetchone()[0], "slugs": slugs}


def redirect_audit(con):
    """جدول التحويلات كلّه: سلاسل (الهدف مسار تحويلٍ آخر)، حلقات، أهدافٌ بلا كيان، أهدافٌ لكيانٍ مدمج (ليس canonical النهائي)."""
    rows = {r["path"]: r["target"] for r in con.execute("SELECT path, target FROM redirect")}
    chains = [p for p, t in rows.items() if t in rows]
    loops, resolve, canon = [], [], []
    for p, t in rows.items():
        seen, cur = {p}, t
        while cur in rows and cur not in seen and len(seen) < 20:
            seen.add(cur); cur = rows[cur]
        if cur in seen:
            loops.append(p)
        m = re.fullmatch(r"/content/(movies|series)/([^/]+)/", t)
        if not m:
            resolve.append(p); continue
        e = con.execute("SELECT merged_into FROM content WHERE type=? AND slug=?", ("movie" if m.group(1) == "movies" else "series", m.group(2))).fetchone()
        if not e:
            if t not in rows:
                resolve.append(p)
        elif e["merged_into"] is not None:
            canon.append(p)
    return {"total": len(rows), "chains": len(chains), "loops": len(loops), "resolve_failures": len(resolve), "canonical_target_failures": len(canon),
            "examples": {"chains": chains[:5], "loops": loops[:5], "resolve_failures": resolve[:5], "canonical_target_failures": canon[:5]}}


def unexpected_indexable(con, st, approved):
    """على كل السكّان الأحياء (بلا رسم: الدالة نفسها التي يقرّر بها الرسم): مسارات index خارج الاعتماد = 0، والمعتمد غير المستحقّ الآن."""
    unexpected, live, approved_not_live, eligible = [], 0, [], 0
    for r in con.execute("SELECT * FROM content WHERE merged_into IS NULL AND available=1 ORDER BY id"):
        for lang in ("ar", "en"):
            elig = seo_pages.indexable(r, lang, st)[0]
            eligible += elig
            ok = seo_pages.live_index(r, lang, st, approved)[0]
            live += ok
            if ok and (r["id"], lang) not in approved:
                unexpected.append(seo_pages._path(r, lang))
            if not ok and (r["id"], lang) in approved:
                approved_not_live.append(seo_pages._path(r, lang))
    return {"live_indexable_routes": live, "eligible_routes": eligible, "unexpected_indexable": len(unexpected), "unexpected_examples": unexpected[:10],
            "approved_not_indexable": len(approved_not_live), "approved_not_indexable_examples": approved_not_live[:10]}


def gate_routes(data_dir, con, st, approved, expect_index=True, ids=None):
    """بوابة المسارات المعتمدة بالرسم كما تُخدم: HTTP 200 · وسم index بلا رأس noindex (أو noindex إن لم يُطلب) · canonical ذاتي
    مطابق · `<html lang>` · قاعدة hreflang على صفحتَي كل كيان · slug والمسار كما اعتُمدا · الكيان حيٌّ غير مدمج ← المقاييس وتفاصيل الفشل."""
    m = {"routes": 0, "expected_indexable": 0, "indexable_ok": 0, "http_failures": 0, "robots_failures": 0, "canonical_failures": 0, "hreflang_failures": 0,
         "language_failures": 0, "slug_changes": 0, "entity_changes": 0}
    fails, by_id = [], {}
    for (cid, lang), a in approved.items():
        if ids is not None and cid not in ids:
            continue
        by_id.setdefault(cid, {})[lang] = a
    for cid, langs in sorted(by_id.items()):
        r = _row(con, cid)
        if not r or r["merged_into"] is not None or not r["available"]:
            m["entity_changes"] += len(langs); m["routes"] += len(langs); fails.append({"id": cid, "problem": "entity missing/merged/unavailable"}); continue
        pages = {}
        for lang in ("ar", "en"):
            try:
                pages[lang] = seo_qa._page(data_dir, con, r, lang, st)
            except Exception as ex:  # noqa: BLE001
                pages[lang] = None; fails.append({"id": cid, "lang": lang, "problem": f"render error: {type(ex).__name__}: {str(ex)[:120]}"})
        for lang, a in langs.items():
            m["routes"] += 1
            bad = []
            path = seo_pages._path(r, lang)
            if a.get("slug") != r["slug"] or a.get("path") != path:
                m["slug_changes"] += 1; bad.append(f"slug/path changed: approved {a.get('path')} now {path}")
            p = pages.get(lang)
            if not p or p["code"] != 200:
                m["http_failures"] += 1; bad.append(f"http={p['code'] if p else None}")
                fails.append({"id": cid, "lang": lang, "path": path, "problems": bad}); continue
            want_index = expect_index and bool(p["index_ar"] if lang == "ar" else p["index_en"])
            if expect_index:
                m["expected_indexable"] += 1
                idx_ok = 'name="robots" content="index, follow' in p["text"] and "X-Robots-Tag" not in p["headers"] and not p.get("noindex")
                if idx_ok and want_index:
                    m["indexable_ok"] += 1
                else:
                    tag = "index" if 'content="index' in p["text"] else "noindex"
                    m["robots_failures"] += 1; bad.append(f"robots: tag={tag} header={p['headers'].get('X-Robots-Tag')} why={p['why']}")
            else:
                if 'name="robots" content="noindex, follow"' not in p["text"] or p["headers"].get("X-Robots-Tag") != "noindex":
                    m["robots_failures"] += 1; bad.append("expected noindex")
            if p["canonical"] != SITE + path or f'<link rel="canonical" href="{p["canonical"]}">' not in p["text"]:
                m["canonical_failures"] += 1; bad.append(f"canonical {p['canonical']}")
            if f'<html lang="{lang}"' not in p["text"]:
                m["language_failures"] += 1; bad.append("html lang")
            if bad:
                fails.append({"id": cid, "lang": lang, "path": path, "problems": bad})
        if pages.get("ar") and pages.get("en") and pages["ar"]["code"] == 200 and pages["en"]["code"] == 200:
            ok, det = seo_qa.hreflang_check(pages)
            if not ok:
                m["hreflang_failures"] += 1; fails.append({"id": cid, "problem": "hreflang", "detail": det})
    m["failures_total"] = len(fails)
    return m, fails[:50]


def _live_paths(con, st, approved=None):
    """مسارات خريطة الموقع: المعتمد المستحقّ فعلًا بالترتيب (كيانٌ حيّ، slug كما اعتُمد، مستحقٌّ بالسياسة، ليس مسار تحويل) ← [(path, id, lang)]."""
    approved = seo_pages.approved_routes(con) if approved is None else approved
    redirects = {r["path"] for r in con.execute("SELECT path FROM redirect")}
    out = []
    for (cid, lang), a in sorted(approved.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        r = _row(con, cid)
        if not r or r["merged_into"] is not None or not r["available"]:
            continue
        if not seo_pages.live_index(r, lang, st, approved)[0]:
            continue
        p = seo_pages._path(r, lang)
        if _ar(p) in redirects:
            continue
        out.append((p, cid, lang))
    return out


def sitemap_entries(data_dir):
    """صفحات الكيانات في /sitemap.xml العامة — المرحلة 5 وحدها تُفعّلها (sitemap_live مع index_live): [(المسار، changefreq، priority)]."""
    con = seo_db.connect(data_dir, create=False)
    if con is None:
        return []
    try:
        st = seo_db.settings(con)
        if not st.get("index_live") or not st.get("sitemap_live"):
            return []
        return [(p, "weekly", "0.7") for p, _, _ in _live_paths(con, st)]
    finally:
        con.close()


def _public_entity_locs(data_dir, entries):
    """روابط الكيانات كما ستظهر في XML العامة (الدليل + صفحات السيرفرات + المدخلات) ← مجموعة."""
    xml = guide_pages.sitemap(C.sitemap(data_dir) + list(entries)).decode("utf-8", "replace")
    return {u for u in LOC_RX.findall(xml) if "/content/movies/" in u or "/content/series/" in u}, xml


def _fail(rel, phase, reason, extra=None, con=None, now=None, data_dir=None):
    rec = {"status": "FAIL", "at": now, "reason": reason, **(extra or {})}
    rel["phases"][str(phase)] = rec
    rel["blocked"] = {"phase": phase, "reason": reason, "at": now}
    if con is not None:
        _save_state(con, rel, now)
    if data_dir:
        rec["file"] = _write(data_dir, f"release-phase{phase}.json", {"phase": phase, **rec, "code": seo_sources.code_version()})
    return {"ok": False, "phase": phase, **rec}


def _pass(rel, phase, rec, con, now, data_dir):
    rec = {"status": "PASS", "at": now, **rec}
    rel["phases"][str(phase)] = rec
    if phase == 7 or (rel.get("blocked") or {}).get("phase") == phase:   # العائق يُرفع بفحصٍ لا بزرّ: نجاح المرحلة 7 (QA بعد النشر) أو نجاح المرحلة التي فشلت نفسها
        rel["blocked"] = None
    rec["file"] = _write(data_dir, f"release-phase{phase}.json", {"phase": phase, **rec, "code": seo_sources.code_version()})
    _save_state(con, rel, now)
    return {"ok": True, "phase": phase, **rec}


def _requires(rel, st, *phases, live=True):
    missing = [p for p in phases if (rel["phases"].get(str(p)) or {}).get("status") != "PASS"]
    if missing:
        return f"requires PASS of phase(s) {missing}"
    if live and not st.get("index_live"):
        return "index_live is off"
    return ""


# ================= المرحلة 4 — رفع noindex عن السكّان المعتمدين =================
def phase4(data_dir, snapshot, expected_routes=None, now=None):
    """يعتمد **روابط اللقطة** (sitemap-staging.xml المكتوبة مع bundle.json بمعرّف اللقطة) بعد التأكد أنها هي المستحقّة الآن تمامًا، ثم يفعّل
    index_live ويفحص البوابة كاملةً؛ أي شرطٍ يفشل = تراجعٌ كامل (index_live كما كان، قائمة الاعتماد كما كانت) وSTOP."""
    now = _now(now)
    with seo_db.lock(data_dir):
        con = seo_db.connect(data_dir, create=False)
        if con is None:
            return {"ok": False, "phase": 4, "error": "no database"}
        try:
            st = seo_db.settings(con)
            rel = _state(con)
            rel["snapshot"] = snapshot
            if not st.get("preview"):
                return _fail(rel, 4, "preview is off: entity routes return 404", con=con, now=now, data_dir=data_dir)
            meta = bundle_meta(data_dir)
            if not meta or str(meta.get("bundle_id")) != str(snapshot):
                return _fail(rel, 4, f"snapshot mismatch: review folder holds {meta.get('bundle_id') if meta else None}, resume point is {snapshot}", con=con, now=now, data_dir=data_dir)
            snap = snapshot_urls(data_dir)
            if snap is None:
                return _fail(rel, 4, "sitemap-staging.xml of the snapshot is missing: the approved population cannot be proven", con=con, now=now, data_dir=data_dir)
            if expected_routes is not None and len(snap) != int(expected_routes):
                return _fail(rel, 4, f"snapshot carries {len(snap)} routes, expected {expected_routes}", {"snapshot_routes": len(snap)}, con=con, now=now, data_dir=data_dir)
            cur = seo_qa.sitemap_urls(con, st) if not st.get("index_live") else [(SITE + seo_pages._path(r, l), l, r["id"]) for r in con.execute("SELECT * FROM content WHERE merged_into IS NULL AND available=1 ORDER BY id") for l in ("ar", "en") if seo_pages.indexable(r, l, st)[0]]
            cur_set = {u for u, _, _ in cur}
            if cur_set != snap:
                return _fail(rel, 4, "population drift: eligible routes now differ from the snapshot — re-snapshot and re-approve, nothing changed",
                             {"snapshot_routes": len(snap), "eligible_now": len(cur_set), "missing_now": sorted(snap - cur_set)[:10], "new_now": sorted(cur_set - snap)[:10]}, con=con, now=now, data_dir=data_dir)
            routes = []
            for u, lang, cid in cur:
                r = _row(con, cid)
                routes.append({"id": cid, "lang": lang, "path": u[len(SITE):], "slug": r["slug"], "type": r["type"], "batch": 0})
            ids = {x["id"] for x in routes}
            before = invariants(con, ids)
            prev_approved, prev_live = seo_db.state(con, APPROVED_KEY), bool(st.get("index_live"))
            with con:
                seo_db.set_state(con, APPROVED_KEY, {"snapshot": snapshot, "at": now, "routes": routes})
            seo_db.set_setting(con, "index_live", True)
            st = seo_db.settings(con)
            approved = seo_pages.approved_routes(con)
            g, fails = gate_routes(data_dir, con, st, approved)
            u = unexpected_indexable(con, st, approved)
            after = invariants(con, ids)
            ra = redirect_audit(con)
            # عيّنة من غير المعتمد (أول 20 كيانًا حيًّا خارج الاعتماد) تُرسم: يجب أن تبقى noindex بلا alternate إلى صفحةٍ noindex
            others = [dict(r) for r in con.execute(f"SELECT * FROM content WHERE merged_into IS NULL AND available=1 AND id NOT IN ({','.join('?' * len(ids))}) ORDER BY id LIMIT 20", sorted(ids))]
            still_noindex = 0
            for o in others:
                rr = _row(con, o["id"])
                for lang in ("ar", "en"):
                    p = seo_qa._page(data_dir, con, rr, lang, st)
                    still_noindex += bool(p and p["code"] == 200 and 'content="noindex, follow"' in p["text"] and p["headers"].get("X-Robots-Tag") == "noindex")
            metrics = {"snapshot_routes": len(snap), "approved_routes": len(routes), "approved_entities": len(ids),
                       "expected_indexable": g["indexable_ok"], "unexpected_indexable": u["unexpected_indexable"], "http_failures": g["http_failures"], "robots_failures": g["robots_failures"],
                       "canonical_failures": g["canonical_failures"], "hreflang_failures": g["hreflang_failures"], "language_failures": g["language_failures"],
                       "slug_changes": g["slug_changes"] + sum(1 for k in before["slugs"] if before["slugs"][k] != after["slugs"].get(k)),
                       "redirect_changes": int(before["redirects_hash"] != after["redirects_hash"]) + abs(after["redirects"] - before["redirects"]),
                       "entity_changes": g["entity_changes"] + abs(after["entities"] - before["entities"]) + abs(after["merged"] - before["merged"]) + abs(after["split_reviews"] - before["split_reviews"]),
                       "approved_not_indexable": u["approved_not_indexable"], "non_approved_sample_pages": len(others) * 2, "non_approved_sample_still_noindex": still_noindex,
                       "redirect_chains": ra["chains"], "redirect_loops": ra["loops"]}
            want = len(routes) if expected_routes is None else int(expected_routes)
            ok = (metrics["expected_indexable"] == want and metrics["unexpected_indexable"] == 0 and metrics["http_failures"] == 0 and metrics["robots_failures"] == 0
                  and metrics["canonical_failures"] == 0 and metrics["hreflang_failures"] == 0 and metrics["language_failures"] == 0 and metrics["slug_changes"] == 0
                  and metrics["redirect_changes"] == 0 and metrics["entity_changes"] == 0 and metrics["approved_not_indexable"] == 0
                  and still_noindex == len(others) * 2 and ra["chains"] == 0 and ra["loops"] == 0)
            rec = {"snapshot": snapshot, "metrics": metrics, "gate": {k: v for k, v in g.items()}, "population_check": u, "invariants": {"before": {k: v for k, v in before.items() if k != "slugs"}, "after": {k: v for k, v in after.items() if k != "slugs"}},
                   "redirect_audit": ra, "failures": fails,
                   "tests": [_t("phase4_expected_indexable", metrics["expected_indexable"] == want, {"got": metrics["expected_indexable"], "want": want}),
                             _t("phase4_unexpected_indexable_zero", metrics["unexpected_indexable"] == 0, u["unexpected_examples"]),
                             _t("phase4_http_canonical_hreflang_language", metrics["http_failures"] == 0 and metrics["canonical_failures"] == 0 and metrics["hreflang_failures"] == 0 and metrics["language_failures"] == 0, metrics),
                             _t("phase4_no_slug_redirect_entity_change", metrics["slug_changes"] == 0 and metrics["redirect_changes"] == 0 and metrics["entity_changes"] == 0, metrics),
                             _t("phase4_non_approved_still_noindex", still_noindex == len(others) * 2, {"sampled": len(others) * 2, "noindex": still_noindex})]}
            if not ok:
                with con:                                             # تراجعٌ كامل: لا شيء يُفهرس
                    if prev_approved is None:
                        con.execute("DELETE FROM build_state WHERE key=?", (APPROVED_KEY,))
                    else:
                        seo_db.set_state(con, APPROVED_KEY, prev_approved)
                seo_db.set_setting(con, "index_live", prev_live)
                rec["rolled_back"] = True
                return _fail(rel, 4, "gate failed — rolled back (index_live and approval list restored)", rec, con=con, now=now, data_dir=data_dir)
            rec["rolled_back"] = False
            return _pass(rel, 4, rec, con, now, data_dir)
        finally:
            con.close()


# ================= المرحلة 5 — خريطة الموقع العامة =================
def phase5(data_dir, now=None):
    now = _now(now)
    with seo_db.lock(data_dir):
        con = seo_db.connect(data_dir, create=False)
        if con is None:
            return {"ok": False, "phase": 5, "error": "no database"}
        try:
            st = seo_db.settings(con)
            rel = _state(con)
            why = _requires(rel, st, 4)
            if why:
                return _fail(rel, 5, why, con=con, now=now, data_dir=data_dir)
            approved = seo_pages.approved_routes(con)
            paths = _live_paths(con, st, approved)
            locs = [SITE + p for p, _, _ in paths]
            redirects = {r["path"] for r in con.execute("SELECT path FROM redirect")}
            m = {"sitemap_expected": len(approved), "sitemap_actual": len(paths), "duplicates": len(locs) - len(set(locs)),
                 "redirect_urls": sum(1 for p, _, _ in paths if _ar(p) in redirects), "noindex_urls": 0, "non200": 0, "canonical_mismatch": 0,
                 "query_or_faceted": sum(1 for u in locs if "?" in u or "#" in u or "/page/" in u), "non_canonical_form": sum(1 for u in locs if not u.endswith("/") or "//" in u[len(SITE) + 1:])}
            fails = []
            for p, cid, lang in paths:
                r = _row(con, cid)
                pg = seo_qa._page(data_dir, con, r, lang, st)
                if not pg or pg["code"] != 200:
                    m["non200"] += 1; fails.append({"path": p, "problem": f"http={pg['code'] if pg else None}"}); continue
                if 'content="index, follow' not in pg["text"] or "X-Robots-Tag" in pg["headers"]:
                    m["noindex_urls"] += 1; fails.append({"path": p, "problem": "noindex"})
                if pg["canonical"] != SITE + p:
                    m["canonical_mismatch"] += 1; fails.append({"path": p, "problem": f"canonical {pg['canonical']}"})
            entries = [(p, "weekly", "0.7") for p, _, _ in paths]
            public, xml = _public_entity_locs(data_dir, entries)
            m["public_sitemap_entity_urls"] = len(public)
            m["public_sitemap_mismatch"] = len(public ^ set(locs))
            m["old_urls_in_sitemap"] = sum(1 for u in public if _ar(u[len(SITE):]) in redirects)
            ok = (m["sitemap_actual"] == m["sitemap_expected"] and m["duplicates"] == 0 and m["redirect_urls"] == 0 and m["noindex_urls"] == 0 and m["non200"] == 0
                  and m["canonical_mismatch"] == 0 and m["query_or_faceted"] == 0 and m["non_canonical_form"] == 0 and m["public_sitemap_mismatch"] == 0 and m["old_urls_in_sitemap"] == 0)
            rec = {"metrics": m, "failures": fails[:50], "sample": locs[:10],
                   "tests": [_t("phase5_count", m["sitemap_actual"] == m["sitemap_expected"], m), _t("phase5_no_duplicates_redirects_noindex_non200", m["duplicates"] == 0 and m["redirect_urls"] == 0 and m["noindex_urls"] == 0 and m["non200"] == 0, m),
                             _t("phase5_canonical_only", m["canonical_mismatch"] == 0 and m["query_or_faceted"] == 0 and m["non_canonical_form"] == 0, m),
                             _t("phase5_public_xml_matches", m["public_sitemap_mismatch"] == 0 and m["old_urls_in_sitemap"] == 0, m)]}
            if not ok:
                seo_db.set_setting(con, "sitemap_live", False)
                return _fail(rel, 5, "sitemap gate failed — sitemap not activated", rec, con=con, now=now, data_dir=data_dir)
            seo_db.set_setting(con, "sitemap_live", True)
            served = sitemap_entries(data_dir)
            rec["served_entries"] = len(served)
            rec["tests"].append(_t("phase5_served_after_activation", len(served) == m["sitemap_expected"], {"served": len(served)}))
            if len(served) != m["sitemap_expected"]:
                seo_db.set_setting(con, "sitemap_live", False)
                return _fail(rel, 5, "served sitemap entries differ from the gate — deactivated", rec, con=con, now=now, data_dir=data_dir)
            rec["activated"] = True
            return _pass(rel, 5, rec, con, now, data_dir)
        finally:
            con.close()


# ================= المرحلة 6 — IndexNow =================
def phase6(data_dir, now=None, submit=None):
    """يرسل المعتمد المستحقّ نفسه (ما في الخريطة) إلى IndexNow — لا تحويلات ولا قديم ولا noindex ولا خارج الاعتماد. القبول ≠ فهرسة."""
    now = _now(now)
    submit = submit or analytics.submit
    with seo_db.lock(data_dir):
        con = seo_db.connect(data_dir, create=False)
        if con is None:
            return {"ok": False, "phase": 6, "error": "no database"}
        try:
            st = seo_db.settings(con)
            rel = _state(con)
            why = _requires(rel, st, 4, 5)
            if why or not st.get("sitemap_live"):
                return _fail(rel, 6, why or "sitemap_live is off", con=con, now=now, data_dir=data_dir)
            approved = seo_pages.approved_routes(con)
            paths = _live_paths(con, st, approved)
            urls = [SITE + p for p, _, _ in paths]
            approved_urls = {SITE + a["path"] for a in approved.values()}
            redirects = {r["path"] for r in con.execute("SELECT path FROM redirect")}
            pre = {"urls": len(urls), "expected": len(approved), "duplicates": len(urls) - len(set(urls)), "outside_population": len(set(urls) - approved_urls),
                   "redirect_urls": sum(1 for u in urls if _ar(u[len(SITE):]) in redirects), "off_host": sum(1 for u in urls if not u.startswith(SITE + "/"))}
            if pre["urls"] != pre["expected"] or pre["duplicates"] or pre["outside_population"] or pre["redirect_urls"] or pre["off_host"]:
                return _fail(rel, 6, "IndexNow population check failed — nothing sent", {"precheck": pre}, con=con, now=now, data_dir=data_dir)
            ix = analytics.indexnow(data_dir)                       # المفتاح يُولَّد مرةً ويُخدم على /<key>.txt
            key_ok = bool(ix["key"]) and analytics.indexnow_key_file(data_dir, f"/{ix['key']}.txt") == ix["key"]
            if not key_ok:
                return _fail(rel, 6, "IndexNow key file route not ready — nothing sent", {"precheck": pre}, con=con, now=now, data_dir=data_dir)
            res = submit(data_dir, HOST, urls, kind="phase6")
            accepted = res["n"] if res.get("ok") else 0
            rec = {"precheck": pre, "submitted": res.get("n", 0), "accepted": accepted, "failed": res.get("n", 0) - accepted, "code": res.get("code"), "msg": res.get("msg"),
                   "endpoint": analytics.INDEXNOW_URL, "key_file": f"{SITE}/{ix['key']}.txt",
                   "note": "IndexNow acceptance (200/202) is a receipt; it does not mean the search engine indexed the pages",
                   "tests": [_t("phase6_submitted_equals_population", res.get("n") == len(approved), {"submitted": res.get("n"), "population": len(approved)}),
                             _t("phase6_accepted", bool(res.get("ok")), {"code": res.get("code"), "msg": res.get("msg")})]}
            if not res.get("ok") or res.get("n") != len(approved):
                return _fail(rel, 6, f"IndexNow not accepted: {res.get('code')} {res.get('msg')}", rec, con=con, now=now, data_dir=data_dir)
            return _pass(rel, 6, rec, con, now, data_dir)
        finally:
            con.close()


# ================= المرحلة 7 — فحصٌ بعد النشر =================
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_probe(urls, timeout=20):
    """فحص HTTP حقيقي على الموقع (بلا اتّباع التحويلات): 200 · بلا رأس noindex · وسم index · canonical ذاتي ← المقاييس والأمثلة."""
    op = urllib.request.build_opener(_NoRedirect)
    m = {"probed": 0, "http_200": 0, "non200": 0, "noindex_header": 0, "noindex_tag": 0, "canonical_failures": 0, "errors": 0}
    bad = []
    for u in urls:
        m["probed"] += 1
        try:
            with op.open(urllib.request.Request(u, headers={"User-Agent": "ssouq-release-qa/1.0"}), timeout=timeout) as r:
                code, hdr, body = r.status, dict(r.headers), r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            code, hdr, body = e.code, dict(e.headers), ""
        except Exception as ex:  # noqa: BLE001
            m["errors"] += 1; bad.append({"url": u, "error": f"{type(ex).__name__}: {str(ex)[:100]}"}); continue
        if code != 200:
            m["non200"] += 1; bad.append({"url": u, "status": code}); continue
        m["http_200"] += 1
        if any(k.lower() == "x-robots-tag" and "noindex" in v.lower() for k, v in hdr.items()):
            m["noindex_header"] += 1; bad.append({"url": u, "problem": "X-Robots-Tag noindex"})
        if 'content="index, follow' not in body:
            m["noindex_tag"] += 1; bad.append({"url": u, "problem": "robots tag not index"})
        if f'<link rel="canonical" href="{u}">' not in body:
            m["canonical_failures"] += 1; bad.append({"url": u, "problem": "canonical"})
    m["ok"] = m["probed"] == m["http_200"] and not (m["noindex_header"] or m["noindex_tag"] or m["canonical_failures"] or m["errors"])
    return {**m, "examples": bad[:20]}


def phase7(data_dir, snapshot=None, http=False, now=None):
    now = _now(now)
    with seo_db.lock(data_dir):
        con = seo_db.connect(data_dir, create=False)
        if con is None:
            return {"ok": False, "phase": 7, "error": "no database"}
        try:
            st = seo_db.settings(con)
            rel = _state(con)
            snapshot = snapshot or rel.get("snapshot")
            why = _requires(rel, st, 4, 5, 6)
            if why or not st.get("sitemap_live"):
                return _fail(rel, 7, why or "sitemap_live is off", con=con, now=now, data_dir=data_dir)
            approved = seo_pages.approved_routes(con)
            ids = {cid for cid, _ in approved}
            snap = snapshot_urls(data_dir) if (bundle_meta(data_dir) or {}).get("bundle_id") == snapshot else None
            approved_urls = {SITE + a["path"] for a in approved.values()}
            g, fails = gate_routes(data_dir, con, st, approved)
            u = unexpected_indexable(con, st, approved)
            p4 = rel["phases"].get("4") or {}
            base = ((p4.get("invariants") or {}).get("before")) or {}
            inv = invariants(con, ids)
            ra = redirect_audit(con)
            paths = _live_paths(con, st, approved)
            public, _ = _public_entity_locs(data_dir, [(p, "weekly", "0.7") for p, _, _ in paths])
            smap = {SITE + p for p, _, _ in paths}
            m = {"routes": g["routes"], "http_failures": g["http_failures"], "canonical_failures": g["canonical_failures"], "hreflang_failures": g["hreflang_failures"],
                 "language_failures": g["language_failures"], "indexable": g["indexable_ok"], "robots_failures": g["robots_failures"], "unexpected_indexable": u["unexpected_indexable"],
                 "sitemap_members": len(smap), "sitemap_missing": len(approved_urls - smap), "sitemap_unexpected": len(public - approved_urls), "sitemap_public_mismatch": len(public ^ smap),
                 "redirect_changes_since_phase4": int(bool(base) and (base.get("redirects_hash") != inv["redirects_hash"] or base.get("redirects") != inv["redirects"])),
                 "redirect_chains": ra["chains"], "redirect_loops": ra["loops"], "slug_changes": g["slug_changes"], "entity_changes": g["entity_changes"],
                 "snapshot_compared": snap is not None, "snapshot_mismatch": len(snap - approved_urls) if snap is not None else None,   # روابط اللقطة التي خرجت من الاعتماد = تراجع
                 "beyond_snapshot": len(approved_urls - snap) if snap is not None else None,                                            # ما اعتُمد بعدها بدفعات التوسيع (معلومة لا فشل)
                 "approved_routes": len(approved), "approved_entities": len(ids)}
            ok = (m["http_failures"] == 0 and m["canonical_failures"] == 0 and m["hreflang_failures"] == 0 and m["language_failures"] == 0 and m["robots_failures"] == 0
                  and m["indexable"] == len(approved) and m["unexpected_indexable"] == 0 and m["sitemap_missing"] == 0 and m["sitemap_unexpected"] == 0 and m["sitemap_public_mismatch"] == 0
                  and m["redirect_changes_since_phase4"] == 0 and m["redirect_chains"] == 0 and m["redirect_loops"] == 0 and m["slug_changes"] == 0 and m["entity_changes"] == 0
                  and (m["snapshot_mismatch"] in (0, None)))
            rec = {"snapshot": snapshot, "metrics": m, "failures": fails, "population_check": u, "redirect_audit": ra, "invariants_now": {k: v for k, v in inv.items() if k != "slugs"},
                   "baseline": None, "http": None,
                   "tests": [_t("phase7_routes_http_canonical_hreflang_language", m["http_failures"] == 0 and m["canonical_failures"] == 0 and m["hreflang_failures"] == 0 and m["language_failures"] == 0, m),
                             _t("phase7_indexability", m["indexable"] == len(approved) and m["robots_failures"] == 0 and m["unexpected_indexable"] == 0, m),
                             _t("phase7_sitemap_membership", m["sitemap_missing"] == 0 and m["sitemap_unexpected"] == 0 and m["sitemap_public_mismatch"] == 0, m),
                             _t("phase7_redirects_slugs_entities", m["redirect_changes_since_phase4"] == 0 and m["redirect_chains"] == 0 and m["redirect_loops"] == 0 and m["slug_changes"] == 0 and m["entity_changes"] == 0, m),
                             _t("phase7_snapshot_population", m["snapshot_mismatch"] in (0, None), {"compared": snap is not None, "missing_from_approval": m["snapshot_mismatch"], "beyond_snapshot": m["beyond_snapshot"]})]}
            try:
                rec["baseline"] = {k: v for k, v in seo_qa.baseline(con, st, data_dir).items() if k not in ("changed_examples",)}
            except Exception as ex:  # noqa: BLE001
                rec["baseline"] = {"error": f"{type(ex).__name__}: {str(ex)[:120]}"}
            if http:
                rec["http"] = http_probe(sorted(approved_urls))
                rec["tests"].append(_t("phase7_live_http", rec["http"]["ok"], {k: v for k, v in rec["http"].items() if k != "examples"}))
                ok = ok and rec["http"]["ok"]
            if not ok:
                return _fail(rel, 7, "post-production QA found a regression — STOP (nothing changed by this phase)", rec, con=con, now=now, data_dir=data_dir)
            return _pass(rel, 7, rec, con, now, data_dir)
        finally:
            con.close()


# ================= المرحلة 8 — التوسيع بدفعات =================
def candidates(con, st, approved, n):
    """الدفعة التالية: كيانات حيّة متاحة غير معتمدة وغير مجمّدة، الأشهر أولًا ثم بالمعرّف (حتمي)."""
    ids = sorted({cid for cid, _ in approved} | seo_sources.frozen_ids(st))
    sql = f"SELECT * FROM content WHERE merged_into IS NULL AND available=1 AND id NOT IN ({','.join('?' * len(ids)) or 'NULL'}) ORDER BY COALESCE(popularity,0) DESC, id LIMIT ?"
    return [r for r in con.execute(sql, (*ids, int(n)))]


def phase8_batch(data_dir, n=100, now=None, submit=None):
    """دفعة توسيعٍ واحدة بثماني خطواتٍ ثم checkpoint. إثراء الدفعة كلّه في معاملةٍ واحدة: فشلُ أي بوابة قبل الاعتماد = rollback (لا أثر إلا التقرير)."""
    now = _now(now)
    submit = submit or analytics.submit
    with seo_db.lock(data_dir):
        con = seo_db.connect(data_dir, create=False)
        if con is None:
            return {"ok": False, "phase": 8, "error": "no database"}
        try:
            st = seo_db.settings(con)
            rel = _state(con)
            k = len(rel.get("batches") or []) + 1
            why = _requires(rel, st, 4, 5, 6, 7)
            if why or not st.get("sitemap_live"):
                return _batch_fail(rel, k, why or "sitemap_live is off", con=con, now=now, data_dir=data_dir)
            if rel.get("blocked"):
                return _batch_fail(rel, k, f"release is blocked at {rel['blocked']}: resolve before expanding", con=con, now=now, data_dir=data_dir)
            key = seo_sources.tmdb_key(con, data_dir)
            if not key:
                return _batch_fail(rel, k, "no TMDB key: enrichment impossible", con=con, now=now, data_dir=data_dir)
            approved = seo_pages.approved_routes(con)
            approved_ids = {cid for cid, _ in approved}
            cands = candidates(con, st, approved, n)
            if not cands:
                rec = {"status": "EMPTY", "at": now, "batch": k, "note": "no candidates left (all live entities approved or frozen)"}
                rel.setdefault("batches", []).append(rec); _save_state(con, rel, now)
                return {"ok": True, "phase": 8, **rec}
            cand_ids = [r["id"] for r in cands]
            before = invariants(con, approved_ids | set(cand_ids))
            red_before = {r["path"]: r["target"] for r in con.execute("SELECT path, target FROM redirect")}
            # 1 — إثراء TMDB (معاملةٌ واحدة، بلا commit حتى تمرّ بوابات الهوية والتسوية)
            en = {"attempted": 0, "enriched": 0, "miss": 0, "failed": 0, "merged": [], "seasons": 0, "errors": []}
            for r in cands:
                en["attempted"] += 1
                try:
                    state, msg = seo_sources._one(con, data_dir, r["id"], "tmdb", st, now)
                    if state == "done" and msg.startswith("merged into"):
                        en["merged"].append({"loser": r["id"], "msg": msg})
                    elif state == "done":
                        en["enriched"] += 1
                        if r["type"] == "series":
                            try:
                                en["seasons"] += int(seo_sources._one(con, data_dir, r["id"], "tmdb_seasons", st, now)[1].split()[0])
                            except Exception:  # noqa: BLE001 — المواسم ليست بوابة
                                pass
                    else:
                        en["miss"] += 1
                    con.execute("UPDATE enrich_queue SET state=?, next_at=0, error=?, updated_at=? WHERE content_id=? AND source='tmdb' AND state='pending'",
                                ("done" if state == "done" else "miss", f"release batch {k}: {msg}"[:200], now, r["id"]))
                except seo_sources.Skip as ex:
                    en["miss"] += 1; en["errors"].append({"id": r["id"], "skip": str(ex)[:120]})
                except Exception as ex:  # noqa: BLE001
                    en["failed"] += 1; en["errors"].append({"id": r["id"], "error": f"{type(ex).__name__}: {str(ex)[:120]}"})
            # 2 — الهوية: كل مرشّحٍ إمّا حيٌّ بمعرّفه، أو مدمجٌ دمجًا مفسَّرًا (نفس tmdb مُتحقَّق، تحويلٌ مباشر إلى كيانٍ حيّ)؛ ولا كيانان حيّان بمعرّف TMDB واحد
            ident = {"conflicts": [], "unexplained_merges": [], "explained_merges": [], "tmdb_mismatch": []}
            red_after = {r["path"]: r["target"] for r in con.execute("SELECT path, target FROM redirect")}
            for cid in cand_ids:
                r = _row(con, cid)
                if r["merged_into"] is not None:
                    w = _row(con, r["merged_into"])
                    rv = con.execute("SELECT payload_json FROM review WHERE key=?", (f"merged:{r['merged_into']}:{cid}",)).fetchone()
                    direct = all(red_after.get(p) == t and t not in red_after for p, t in zip(seo_db.paths(r["type"], r["slug"]), seo_db.paths(w["type"], w["slug"]))) if w else False
                    same = (w is not None and w["merged_into"] is None and str(w["tmdb_id"] or "") and
                            str((seo_db.external(con, "content", w["id"]).get("tmdb") or {}).get("external_id")) == str(w["tmdb_id"]))
                    (ident["explained_merges"] if (rv and direct and same) else ident["unexplained_merges"]).append({"loser": cid, "winner": r["merged_into"], "direct_redirect": direct, "review": bool(rv), "same_verified_tmdb": same})
                    continue
                ext = (seo_db.external(con, "content", cid).get("tmdb") or {})
                if r["tmdb_id"] and ext.get("verified") and str(ext.get("external_id")) != str(r["tmdb_id"]):
                    ident["tmdb_mismatch"].append(cid)
            for row in con.execute("SELECT x.external_id, COUNT(*) n FROM external_id x JOIN content c ON c.id=x.entity_id WHERE x.entity='content' AND x.source='tmdb' AND x.verified=1 "
                                   "AND c.merged_into IS NULL GROUP BY x.external_id HAVING COUNT(*)>1"):
                ident["conflicts"].append({"tmdb": row["external_id"], "live_entities": row["n"]})
            # 3 — التسوية: لا انقسام، لا تغيّر في المعتمد (slug، دمج، تحويلاته)، التحويلات الجديدة مباشرةٌ بلا سلاسل/حلقات
            after = invariants(con, approved_ids | set(cand_ids))
            ra = redirect_audit(con)
            new_red = {p: t for p, t in red_after.items() if red_before.get(p) != t}
            recon = {"entities_before": before["entities"], "entities_after": after["entities"], "merged_delta": after["merged"] - before["merged"], "split_delta": after["split_reviews"] - before["split_reviews"],
                     "new_redirects": len(new_red), "new_redirects_direct": sum(1 for t in new_red.values() if t not in red_after), "redirect_chains": ra["chains"], "redirect_loops": ra["loops"],
                     "approved_slug_changes": sum(1 for i in approved_ids if before["slugs"].get(str(i)) != after["slugs"].get(str(i))),
                     "approved_merged": sum(1 for i in approved_ids if (_row(con, i) or {"merged_into": 1})["merged_into"] is not None),
                     "approved_redirect_targets_changed": sum(1 for p, t in red_before.items() if red_after.get(p) != t)}
            # 4/5/6 — canonical · hreflang · الأهلية على المرشّحين الأحياء (غير معتمدين بعد: noindex بلا alternate)
            live_c = [cid for cid in cand_ids if (_row(con, cid) or {"merged_into": 1})["merged_into"] is None]
            tmp = {(cid, l): {"id": cid, "lang": l, "path": seo_pages._path(_row(con, cid), l), "slug": _row(con, cid)["slug"]} for cid in live_c for l in ("ar", "en")}
            g0, f0 = gate_routes(data_dir, con, st, tmp, expect_index=False)
            newly = [(cid, l) for cid in live_c for l in ("ar", "en") if seo_pages.indexable(_row(con, cid), l, st)[0]]
            elig = {"candidates_live": len(live_c), "newly_eligible_routes": len(newly), "newly_eligible_entities": len({c for c, _ in newly}),
                    "by_reason": {}}
            for cid in live_c:
                for l in ("ar", "en"):
                    why_ = seo_pages.indexable(_row(con, cid), l, st)[1]
                    elig["by_reason"][why_] = elig["by_reason"].get(why_, 0) + 1
            gate_ok = (not ident["conflicts"] and not ident["unexplained_merges"] and not ident["tmdb_mismatch"] and recon["split_delta"] == 0 and recon["approved_slug_changes"] == 0
                       and recon["approved_merged"] == 0 and recon["approved_redirect_targets_changed"] == 0 and recon["new_redirects"] == recon["new_redirects_direct"]
                       and ra["chains"] == 0 and ra["loops"] == 0 and ra["resolve_failures"] == 0 and g0["http_failures"] == 0 and g0["canonical_failures"] == 0 and g0["hreflang_failures"] == 0
                       and g0["language_failures"] == 0 and g0["robots_failures"] == 0 and en["failed"] == 0)
            rec = {"batch": k, "n": len(cands), "candidate_ids": cand_ids[:200], "tmdb": {kk: v for kk, v in en.items() if kk != "merged"}, "merges": en["merged"], "identity": ident, "reconciliation": recon,
                   "redirect_audit": ra, "canonical_hreflang_gate": g0, "gate_failures": f0, "eligibility": elig}
            if not gate_ok:
                con.rollback()                                              # لا أثر للدفعة في القاعدة
                rec["rolled_back"] = True
                return _batch_fail(rel, k, "batch gate failed (identity/reconciliation/redirect/canonical/hreflang) — rolled back, nothing approved", rec, con=con, now=now, data_dir=data_dir)
            con.commit()                                                     # الإثراء اجتاز بواباته
            # checkpoint — اعتماد المستحقّ الجديد ثم بوابة الخريطة (7/8) عليه؛ فشلها = تراجعٌ عن الاعتماد وحده
            ap = seo_db.state(con, APPROVED_KEY) or {"routes": []}
            prev = json.loads(json.dumps(ap))
            for cid, l in newly:
                r = _row(con, cid)
                ap["routes"].append({"id": cid, "lang": l, "path": seo_pages._path(r, l), "slug": r["slug"], "type": r["type"], "batch": k})
            ap["at"] = now
            with con:
                seo_db.set_state(con, APPROVED_KEY, ap)
            approved2 = seo_pages.approved_routes(con)
            g1, f1 = gate_routes(data_dir, con, st, approved2, ids={c for c, _ in newly})
            u = unexpected_indexable(con, st, approved2)
            paths = _live_paths(con, st, approved2)
            locs = [SITE + p for p, _, _ in paths]
            public, _ = _public_entity_locs(data_dir, [(p, "weekly", "0.7") for p, _, _ in paths])
            smap = {"expected": len(approved2), "actual": len(paths), "duplicates": len(locs) - len(set(locs)), "redirect_urls": sum(1 for p, _, _ in paths if _ar(p) in red_after),
                    "public_mismatch": len(public ^ set(locs)), "unexpected_indexable": u["unexpected_indexable"], "approved_not_indexable": u["approved_not_indexable"]}
            smap_ok = (smap["actual"] == smap["expected"] and smap["duplicates"] == 0 and smap["redirect_urls"] == 0 and smap["public_mismatch"] == 0 and smap["unexpected_indexable"] == 0
                       and smap["approved_not_indexable"] == 0 and g1["http_failures"] == 0 and g1["robots_failures"] == 0 and g1["canonical_failures"] == 0 and g1["hreflang_failures"] == 0
                       and g1["language_failures"] == 0 and g1["indexable_ok"] == len(newly))
            rec.update({"new_routes_gate": g1, "new_routes_failures": f1, "sitemap": smap})
            if not smap_ok:
                with con:
                    seo_db.set_state(con, APPROVED_KEY, prev)
                rec["approval_rolled_back"] = True
                return _batch_fail(rel, k, "sitemap/indexability gate failed on the new routes — approval rolled back (enrichment kept)", rec, con=con, now=now, data_dir=data_dir)
            ix = {"submitted": 0, "accepted": 0, "failed": 0, "code": None, "msg": "nothing new to submit"}
            if newly:
                new_urls = [SITE + seo_pages._path(_row(con, c), l) for c, l in newly]
                res = submit(data_dir, HOST, new_urls, kind=f"phase8-batch{k}")
                ix = {"submitted": res.get("n", 0), "accepted": res.get("n", 0) if res.get("ok") else 0, "failed": res.get("n", 0) - (res.get("n", 0) if res.get("ok") else 0), "code": res.get("code"), "msg": res.get("msg")}
            rec.update({"indexnow": ix, "approved_routes_total": len(approved2), "approved_entities_total": len({c for c, _ in approved2}), "status": "PASS", "at": now})
            rec["file"] = _write(data_dir, f"release-batch-{k}.json", {"phase": 8, **rec, "code": seo_sources.code_version()})
            rel.setdefault("batches", []).append({kk: v for kk, v in rec.items() if kk not in ("candidate_ids", "gate_failures", "new_routes_failures")})
            rel["blocked"] = None
            _save_state(con, rel, now)
            return {"ok": True, "phase": 8, **rec}
        finally:
            con.close()


def _batch_fail(rel, k, reason, extra=None, con=None, now=None, data_dir=None):
    rec = {"status": "FAIL", "at": now, "batch": k, "reason": reason, **(extra or {})}
    rel.setdefault("batches", []).append({kk: v for kk, v in rec.items() if kk not in ("candidate_ids", "gate_failures", "new_routes_failures")})
    rel["blocked"] = {"phase": 8, "batch": k, "reason": reason, "at": now}
    if data_dir:
        rec["file"] = _write(data_dir, f"release-batch-{k}.json", {"phase": 8, **rec, "code": seo_sources.code_version()})
    if con is not None:
        _save_state(con, rel, now)
    return {"ok": False, "phase": 8, **rec}


def expand(data_dir, n=100, max_batches=None, now=None, submit=None, progress=None):
    """المرحلة 9: دفعاتٌ متتابعة ما دامت السابقة PASS؛ تتوقف عند أول فشل أو نفاد المرشّحين أو بلوغ الحدّ."""
    out = []
    while max_batches is None or len(out) < int(max_batches):
        if progress:
            progress(len(out) + 1)
        r = phase8_batch(data_dir, n, now=now, submit=submit)
        out.append({k: r.get(k) for k in ("ok", "batch", "status", "reason", "n", "approved_routes_total")})
        if not r.get("ok") or r.get("status") == "EMPTY":
            break
    return {"batches": out, "ok": all(b["ok"] for b in out), "stopped_at": next((b for b in out if not b["ok"]), None)}


# ================= التتابع 4 ← 5 ← 6 ← 7 =================
def go(data_dir, snapshot, expected_routes=None, http=False, now=None, submit=None, progress=None):
    """Phase 4 ← Gate ← Phase 5 ← Gate ← Phase 6 ← Gate ← Phase 7. فشل بوابةٍ = STOP (لا يُتجاوز)."""
    steps = []
    for name, fn in (("4", lambda: phase4(data_dir, snapshot, expected_routes, now)), ("5", lambda: phase5(data_dir, now)),
                     ("6", lambda: phase6(data_dir, now, submit)), ("7", lambda: phase7(data_dir, snapshot, http, now))):
        if progress:
            progress(f"phase {name}")
        r = fn()
        steps.append({"phase": name, "ok": r.get("ok"), "status": r.get("status"), "reason": r.get("reason") or r.get("error"), "metrics": r.get("metrics")})
        if not r.get("ok"):
            return {"ok": False, "stopped_at": name, "steps": steps}
    return {"ok": True, "steps": steps}


# ================= الحال والخيط الخلفي =================
def status(data_dir):
    con = seo_db.connect(data_dir, create=False)
    k = os.path.abspath(data_dir)
    if con is None:
        return {"running": False, "release": None, "error": "no database"}
    try:
        st = seo_db.settings(con)
        rel = _state(con)
        approved = seo_pages.approved_routes(con)
        return {"running": bool(_threads.get(k) and _threads[k].is_alive()), "progress": _progress.get(k), "release": {kk: v for kk, v in rel.items() if kk != "batches"},
                "batches": [{kk: v for kk, v in b.items() if kk in ("batch", "status", "n", "reason", "at", "approved_routes_total", "indexnow", "eligibility")} for b in rel.get("batches") or []],
                "index_live": bool(st.get("index_live")), "sitemap_live": bool(st.get("sitemap_live")), "preview": bool(st.get("preview")),
                "approved_routes": len(approved), "approved_entities": len({c for c, _ in approved}), "approved_snapshot": (seo_db.state(con, APPROVED_KEY) or {}).get("snapshot"),
                "bundle": bundle_meta(data_dir), "snapshot_routes": len(snapshot_urls(data_dir) or []), **seo_sources.code_version()}
    finally:
        con.close()


def start(data_dir, action, **kw):
    """تشغيل go/phase/batch/expand/final في خيطٍ (المرحلة 8 تطلب TMDB فتستغرق)، وعمليةٌ واحدة في وقتها ← هل بدأت؟"""
    k = os.path.abspath(data_dir)
    t = _threads.get(k)
    if t and t.is_alive():
        return False
    _progress[k] = {"action": action, "at": int(time.time()), "stage": "starting"}

    def prog(x):
        _progress[k] = {**_progress[k], "stage": str(x)}

    def run_():
        try:
            if action == "go":
                res = go(data_dir, kw.get("snapshot"), kw.get("expected"), bool(kw.get("http")), progress=prog)
            elif action in ("phase4", "phase5", "phase6", "phase7"):
                res = {"phase4": lambda: phase4(data_dir, kw.get("snapshot"), kw.get("expected")), "phase5": lambda: phase5(data_dir), "phase6": lambda: phase6(data_dir),
                       "phase7": lambda: phase7(data_dir, kw.get("snapshot"), bool(kw.get("http")))}[action]()
            elif action == "batch":
                res = phase8_batch(data_dir, int(kw.get("n") or 100))
            elif action == "expand":
                res = expand(data_dir, int(kw.get("n") or 100), kw.get("max"), progress=lambda i: prog(f"batch {i}"))
            elif action == "final":
                res = final_bundle(data_dir)
            else:
                res = {"ok": False, "error": f"unknown action {action}"}
            _progress[k] = {**_progress[k], "stage": "done", "ok": bool(res.get("ok")), "result": {kk: v for kk, v in res.items() if kk in ("ok", "phase", "status", "reason", "stopped_at", "steps", "batches", "file")}}
        except Exception as e:  # noqa: BLE001
            import traceback
            _progress[k] = {**_progress[k], "stage": "error", "ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}", "traceback": traceback.format_exc()[-1500:]}
    t = _threads[k] = threading.Thread(target=run_, daemon=True)
    t.start()
    return True


# ================= الحزمة النهائية =================
def final_bundle(data_dir, now=None):
    """FINAL STATUS بالصيغة المطلوبة للمراجعة: من حال النشر وQA والقاعدة — READY فقط إن كانت كل البوابات المنفَّذة PASS ولا شيء غير مثبت."""
    now = _now(now)
    con = seo_db.connect(data_dir, create=False)
    if con is None:
        return {"ok": False, "error": "no database"}
    try:
        import seo_scan
        st = seo_db.settings(con)
        rel = _state(con)
        ph = rel.get("phases") or {}
        batches = rel.get("batches") or []
        approved = seo_pages.approved_routes(con)
        meta = bundle_meta(data_dir) or {}
        cv = seo_sources.code_version()
        inv = invariants(con, {c for c, _ in approved})
        ra = redirect_audit(con)
        u = unexpected_indexable(con, st, approved)
        fp = seo_scan.summary(seo_scan.load(data_dir))
        try:
            bl = seo_qa.baseline(con, st, data_dir)
        except Exception as ex:  # noqa: BLE001
            bl = {"error": str(ex)[:120]}
        p7 = (ph.get("7") or {}).get("metrics") or {}
        p6 = ph.get("6") or {}
        watch = []
        for n in seo_sources.normalizations(data_dir):
            r = _row(con, n.get("entity_id"))
            if r:
                ext = seo_db.external(con, "content", r["id"])
                watch.append({"entity": r["id"], "title": r["title_en"] or r["title"], "tmdb": r["tmdb_id"], "imdb": (ext.get("imdb") or {}).get("external_id"), "slug": r["slug"],
                              "changes": "none" if (n.get("slug") or {}).get("after") == r["slug"] and r["merged_into"] is None else f"slug {(n.get('slug') or {}).get('after')} → {r['slug']}; merged_into={r['merged_into']}"})
        tmdb = {"enriched": sum((b.get("tmdb") or {}).get("enriched", 0) for b in batches), "failed": sum((b.get("tmdb") or {}).get("failed", 0) for b in batches),
                "conflicts": sum(len((b.get("identity") or {}).get("conflicts") or []) for b in batches)}
        recon = {"merges": sum((b.get("reconciliation") or {}).get("merged_delta", 0) for b in batches), "splits": sum((b.get("reconciliation") or {}).get("split_delta", 0) for b in batches),
                 "unexplained_changes": sum(len((b.get("identity") or {}).get("unexplained_merges") or []) for b in batches)}
        ixn = {"submitted": p6.get("submitted", 0) + sum((b.get("indexnow") or {}).get("submitted", 0) for b in batches), "accepted": p6.get("accepted", 0) + sum((b.get("indexnow") or {}).get("accepted", 0) for b in batches),
               "failed": p6.get("failed", 0) + sum((b.get("indexnow") or {}).get("failed", 0) for b in batches)}
        tests = [t for p in ph.values() for t in p.get("tests") or []]
        qa = {"total": len(tests), "pass": sum(1 for t in tests if t["ok"]), "fail": sum(1 for t in tests if not t["ok"])}
        def pst(i):
            if i == 1: return "CLOSED"
            if i == 2: return "PASS" if fp.get("verdict") == "PASS" else fp.get("verdict", "NOT PROVEN")
            if i == 3: return "PASS" if meta.get("bundle_id") else "NOT RUN"
            if i in (4, 5, 6, 7): return (ph.get(str(i)) or {}).get("status", "NOT RUN")
            if i == 8: return ("PASS" if batches and batches[-1].get("status") == "PASS" else batches[-1].get("status")) if batches else "NOT RUN"
            if i == 9: return f"{sum(1 for b in batches if b.get('status') == 'PASS')} batches PASS" if len(batches) > 1 else "NOT RUN"
        phases = {i: pst(i) for i in range(1, 10)}
        blockers = []
        if rel.get("blocked"): blockers.append(f"release blocked: {rel['blocked']}")
        for i in (4, 5, 6, 7):
            if phases[i] == "NOT RUN": blockers.append(f"Phase {i} not executed")
        if fp.get("verdict") != "PASS": blockers.append(f"Global SEO Coverage {fp.get('verdict')}")
        if u["unexpected_indexable"]: blockers.append(f"unexpected indexable routes {u['unexpected_indexable']}")
        if u["approved_not_indexable"]: blockers.append(f"approved routes no longer indexable {u['approved_not_indexable']}")
        if ra["chains"] or ra["loops"] or ra["resolve_failures"]: blockers.append(f"redirect audit: chains {ra['chains']} loops {ra['loops']} resolve {ra['resolve_failures']}")
        executed = [phases[i] for i in (4, 5, 6, 7)] + [b.get("status") for b in batches]
        ready = all(s == "PASS" for s in executed) and len(executed) >= 4 and not blockers
        smap_paths = _live_paths(con, st, approved) if st.get("sitemap_live") else []
        out = {"at": now, "snapshot": rel.get("snapshot") or meta.get("bundle_id"), "code_fingerprint": cv["code_fingerprint"], "commit": cv["commit"],
               "entities": {"live": inv["live"], "total": inv["entities"], "new": bl.get("entities_new"), "merged": inv["merged"], "split": inv["split_reviews"],
                            "unavailable": con.execute("SELECT COUNT(*) FROM content WHERE merged_into IS NULL AND available=0").fetchone()[0]},
               "watched_entities": watch,
               "global_seo": {"entities": fp.get("entities_total"), "routes": fp.get("routes_total"), "tested": fp.get("tested_entities"), "coverage": fp.get("coverage_percent"), "failures": fp.get("failures"), "verdict": fp.get("verdict")},
               "indexability": {"eligible": u["eligible_routes"], "indexable": u["live_indexable_routes"], "noindex": inv["live"] * 2 - u["live_indexable_routes"], "unexpected": u["unexpected_indexable"], "approved": len(approved)},
               "canonical": {"total": p7.get("routes"), "failures": p7.get("canonical_failures")},
               "hreflang": {"bilingual": sum(1 for c in {c for c, _ in approved} if (c, "ar") in approved and (c, "en") in approved), "complete": None, "incomplete": p7.get("hreflang_failures"),
                            "reciprocity_failures": p7.get("hreflang_failures"), "missing_x_default": p7.get("hreflang_failures")},
               "sitemap": {"production": bool(st.get("sitemap_live")), "urls": len(smap_paths), "duplicates": ((ph.get("5") or {}).get("metrics") or {}).get("duplicates"),
                           "redirect_urls": ((ph.get("5") or {}).get("metrics") or {}).get("redirect_urls"), "noindex_urls": ((ph.get("5") or {}).get("metrics") or {}).get("noindex_urls"), "non200": ((ph.get("5") or {}).get("metrics") or {}).get("non200")},
               "redirects": {"total": ra["total"], "new": sum((b.get("reconciliation") or {}).get("new_redirects", 0) for b in batches), **{k: ra[k] for k in ("chains", "loops", "resolve_failures", "canonical_target_failures")}},
               "indexnow": ixn, "tmdb": tmdb, "reconciliation": recon, "qa": qa, "phases": phases, "blockers": blockers, "final": "READY" if ready else "BLOCKED", "ok": True}
        if out["hreflang"]["bilingual"] is not None and p7:
            out["hreflang"]["complete"] = out["hreflang"]["bilingual"] - (p7.get("hreflang_failures") or 0)
        _write(data_dir, "release-final.json", out)
        with open(os.path.join(seo_sources.bundle_dir(data_dir), "release-final.txt"), "w", encoding="utf-8") as f:
            f.write(final_text(out))
        out["file"] = os.path.join(seo_sources.bundle_dir(data_dir), "release-final.json")
        return out
    finally:
        con.close()


def final_text(o):
    e, g, i, c, h, s, r, x, t, rc, q = (o[k] for k in ("entities", "global_seo", "indexability", "canonical", "hreflang", "sitemap", "redirects", "indexnow", "tmdb", "reconciliation", "qa"))
    w = "\n".join(f"  {k}: {v}" for k, v in (("entity", "/".join(str(x_["entity"]) for x_ in o["watched_entities"]) or "-"), ("TMDB", "/".join(str(x_["tmdb"]) for x_ in o["watched_entities"]) or "-"),
                                             ("IMDb", "/".join(str(x_["imdb"]) for x_ in o["watched_entities"]) or "-"), ("slug", "/".join(str(x_["slug"]) for x_ in o["watched_entities"]) or "-"),
                                             ("changes", "; ".join(str(x_["changes"]) for x_ in o["watched_entities"]) or "-")))
    lines = ["FINAL STATUS", f"snapshot: {o['snapshot']}", f"code_fingerprint: {o['code_fingerprint']}", "",
             f"entities: {e['live']} live / {e['total']} total", f"new: {e['new']}", f"merged: {e['merged']}", f"split: {e['split']}", f"unavailable: {e['unavailable']}", "",
             "Watched entities (" + ", ".join(str(x_["title"]) for x_ in o["watched_entities"]) + "):", w, "",
             "GLOBAL SEO:", f"  entities: {g['entities']}", f"  routes: {g['routes']}", f"  tested: {g['tested']}", f"  coverage: {g['coverage']}%", f"  failures: {g['failures']}", f"  verdict: {g['verdict']}", "",
             "INDEXABILITY:", f"  eligible: {i['eligible']}", f"  indexable: {i['indexable']}", f"  noindex: {i['noindex']}", f"  unexpected: {i['unexpected']}", f"  approved: {i['approved']}", "",
             "CANONICAL:", f"  total: {c['total']}", f"  failures: {c['failures']}", "",
             "HREFLANG:", f"  bilingual: {h['bilingual']}", f"  complete: {h['complete']}", f"  incomplete: {h['incomplete']}", f"  reciprocity_failures: {h['reciprocity_failures']}", f"  missing_x_default: {h['missing_x_default']}", "",
             "SITEMAP:", f"  production: {s['production']}", f"  URLs: {s['urls']}", f"  duplicates: {s['duplicates']}", f"  redirect_urls: {s['redirect_urls']}", f"  noindex_urls: {s['noindex_urls']}", f"  non200: {s['non200']}", "",
             "REDIRECTS:", f"  total: {r['total']}", f"  new: {r['new']}", f"  chains: {r['chains']}", f"  loops: {r['loops']}", f"  resolve_failures: {r['resolve_failures']}", f"  canonical_target_failures: {r['canonical_target_failures']}", "",
             "INDEXNOW:", f"  submitted: {x['submitted']}", f"  accepted: {x['accepted']}", f"  failed: {x['failed']}", "",
             "TMDB:", f"  enriched: {t['enriched']}", f"  failed: {t['failed']}", f"  conflicts: {t['conflicts']}", "",
             "RECONCILIATION:", f"  merges: {rc['merges']}", f"  splits: {rc['splits']}", f"  unexplained_changes: {rc['unexplained_changes']}", "",
             "QA:", f"  total: {q['total']}", f"  pass: {q['pass']}", f"  fail: {q['fail']}", "",
             "PHASE STATUS:"] + [f"  Phase {k}: {v}" for k, v in o["phases"].items()] + ["", "BLOCKERS:"] + ([f"  - {b}" for b in o["blockers"]] or ["  none"]) + ["", f"FINAL: {o['final']}"]
    return "\n".join(lines) + "\n"


def main(argv):
    data_dir = os.environ.get("XM_DATA") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    cmd = argv[1] if len(argv) > 1 else "status"
    opt = {a.lstrip("-").split("=")[0]: (a.split("=", 1)[1] if "=" in a else True) for a in argv[2:] if a.startswith("--")}
    snap = opt.get("snapshot")
    exp = int(opt["expected"]) if opt.get("expected") else None
    if cmd == "go":
        res = go(data_dir, snap, exp, bool(opt.get("http")))
    elif cmd == "phase4":
        res = phase4(data_dir, snap, exp)
    elif cmd == "phase5":
        res = phase5(data_dir)
    elif cmd == "phase6":
        res = phase6(data_dir)
    elif cmd == "phase7":
        res = phase7(data_dir, snap, bool(opt.get("http")))
    elif cmd == "batch":
        res = phase8_batch(data_dir, int(opt.get("n") or 100))
    elif cmd == "expand":
        res = expand(data_dir, int(opt.get("n") or 100), int(opt["max"]) if opt.get("max") else None)
    elif cmd == "final":
        res = final_bundle(data_dir)
        print(final_text(res) if res.get("ok") else res)
        return
    else:
        res = status(data_dir)
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    import sys
    main(sys.argv)

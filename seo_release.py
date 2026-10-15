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
    python seo_release.py extras [--expected=N]                                     # المرحلة 10: اعتماد القوائم والمواسم والحلقات والهبّات (بعد 4 و5 و7)
    python seo_release.py final                                                     # الحزمة النهائية للمراجعة (release-final.json/.txt)
    python seo_release.py status
"""
import json
import os
import re
import http.client
import random
import sqlite3
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
HOST = seo_pages.guide_pages.SITE_NETLOC            # المضيف وحده: IndexNow يطلب host بلا مجلد، والمفتاح يُخدم على جذر المضيف
STATE_KEY = "release"                       # build_state: حال المراحل {snapshot, phases: {"4": …}, batches: […], updated_at}
APPROVED_KEY = seo_pages.APPROVED_KEY
LOC_RX = re.compile(r"<loc>(.*?)</loc>")
_threads, _progress = {}, {}


# ================= أدوات =================
def _tick(data_dir, stage, done=None, total=None):
    """يحدّث عدّاد التقدّم الحيّ الذي يقرؤه المعالج في الإدارة (‏done/total والمرحلة) — لا أثر له خارج `start` (سطر الأوامر)."""
    p = _progress.get(os.path.abspath(data_dir))
    if p is not None:
        p["stage"] = stage
        if total is not None:
            p["done"], p["total"] = done, total


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
    """bundle.json للقطة الحالية في مجلد المراجعة (معرّفها وبصمة كودها) أو None.
    يكتبه seo_sources.bundle كـ {"meta": الختم, "files": …, "errors": …} والختم (bundle_id · code_fingerprint · generated_at) داخل meta؛
    فيُرفع الختم إلى المستوى الأعلى (مع إبقاء meta كما هي) حتى يقرأه القرّاء كلّهم — المرحلتان 4 و7 والحزمة النهائية وسطر الحالة في
    اللوحة — بالمفتاح نفسه، وإلا قُرئ bundle_id على أنه None ورُفضت كل لقطةٍ مهما طابقت."""
    try:
        with open(os.path.join(seo_sources.bundle_dir(data_dir), "bundle.json"), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    stamp = d.get("meta") if isinstance(d.get("meta"), dict) else {}
    return {**stamp, **d}


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
        m = re.fullmatch(r"(?:/[a-z]{2})?/content/(movies|series)/([^/]+)/", t)     # الهدف بأي بادئة لغة (/en/…) كالعربي: الصفّان ar وen يُحلّان إلى الكيان نفسه
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
    for ci_, (cid, langs) in enumerate(sorted(by_id.items())):
        if ci_ % 10 == 0:
            _tick(data_dir, "فحص الصفحات كما تُخدم", ci_, len(by_id))
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


PHASE7_FULL_KEY = "phase7_full"        # build_state: {at: آخر فحصٍ كاملٍ ناجح، count: كم مسارًا من قائمة الاعتماد (بترتيبها) تحقّق منها الفحص الأخير}
PHASE7_MIN_SAMPLE = 100


def _phase7_scope(con, st, approved, quick, now):
    """أي المسارات المعتمدة تُرسَم وتُفحص كما تُخدم؟ ← (المجموعة، الوضع، عدد الجديد، عدد العيّنة).
    الفحص الكامل (الافتراضي) يرسم كل المعتمد — وتكلفته تكبر مع الاعتماد (نحو ثانيتين للمسار). والسريع (الطيار الآلي وزرّ «ابدأ كل شيء») يفحص **ما اعتُمد بعد
    آخر فحصٍ ناجح** + عيّنةً عشوائية (`phase7_sample_pct` بحدٍّ أدنى) من القديم، ويعود كاملًا إن مرّ `phase7_full_every_days` (يومٌ افتراضًا) أو لم يُجرَ كاملٌ قط.
    بقية فحوص المرحلة (الخريطة والتحويلات والسلاسل والفهرسة غير المتوقَّعة) كاملةٌ دائمًا: لا ترسم صفحات."""
    keys = list(approved)
    meta = seo_db.state(con, PHASE7_FULL_KEY) or {}
    days = max(0.0, float(st.get("phase7_full_every_days", 1)))
    if not (quick and meta.get("at") and now - int(meta["at"]) < days * 86400 and 0 < int(meta.get("count") or 0) <= len(keys)):
        return approved, "full", len(keys), 0
    done = int(meta["count"])
    new, older = keys[done:], keys[:done]
    k = min(len(older), max(PHASE7_MIN_SAMPLE, int(len(older) * max(0, int(st.get("phase7_sample_pct", 10))) / 100)))
    sample = random.sample(older, k) if k else []
    return {key: approved[key] for key in new + sample}, "quick", len(new), len(sample)


def phase7(data_dir, snapshot=None, http=False, now=None, quick=False):
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
            scope, mode, n_new, n_sample = _phase7_scope(con, st, approved, quick, now)
            g, fails = gate_routes(data_dir, con, st, scope)
            u = unexpected_indexable(con, st, approved)
            p4 = rel["phases"].get("4") or {}
            base = ((p4.get("invariants") or {}).get("before")) or {}
            inv = invariants(con, ids)
            ra = redirect_audit(con)
            # التحويلات: ما يهمّ المعتمد ألّا يُحوَّل أي مسارٍ منه (صفحةٌ تُخدم 301 بدل 200) وألّا تنشأ سلاسل/حلقات/أهدافٌ مكسورة. أما **عدد/بصمة جدول التحويلات كله** فيتغيّر
            # مشروعًا بدفعات التوسيع الناجحة (دمجٌ مفسَّر بمعرّف TMDB واحد، وكل دفعةٍ بوابتها: تحويلاتٌ مباشرة) — فلا يُشترط ثباته بعد أول دفعة، ويبقى شرطًا قبلها.
            approved_paths = {a["path"] for a in approved.values()}
            approved_redirected = sum(1 for r in con.execute("SELECT path FROM redirect") if r["path"] in approved_paths)
            passed_batches = [b for b in rel.get("batches") or [] if b.get("status") == "PASS"]
            strict_changed = bool(base) and (base.get("redirects_hash") != inv["redirects_hash"] or base.get("redirects") != inv["redirects"])
            paths = _live_paths(con, st, approved)
            public, _ = _public_entity_locs(data_dir, [(p, "weekly", "0.7") for p, _, _ in paths])
            smap = {SITE + p for p, _, _ in paths}
            m = {"routes": g["routes"], "http_failures": g["http_failures"], "canonical_failures": g["canonical_failures"], "hreflang_failures": g["hreflang_failures"],
                 "language_failures": g["language_failures"], "indexable": g["indexable_ok"], "robots_failures": g["robots_failures"], "unexpected_indexable": u["unexpected_indexable"],
                 "sitemap_members": len(smap), "sitemap_missing": len(approved_urls - smap), "sitemap_unexpected": len(public - approved_urls), "sitemap_public_mismatch": len(public ^ smap),
                 "redirect_changes_since_phase4": int(approved_redirected > 0 or (strict_changed and not passed_batches)),
                 "approved_paths_redirected": approved_redirected, "redirects_total_delta": inv["redirects"] - int(base.get("redirects") or 0) if base else None,
                 "passed_batches": len(passed_batches), "redirect_target_failures": ra["canonical_target_failures"], "redirect_resolve_failures": ra["resolve_failures"],
                 "redirect_chains": ra["chains"], "redirect_loops": ra["loops"], "slug_changes": g["slug_changes"], "entity_changes": g["entity_changes"],
                 "snapshot_compared": snap is not None, "snapshot_mismatch": len(snap - approved_urls) if snap is not None else None,   # روابط اللقطة التي خرجت من الاعتماد = تراجع
                 "beyond_snapshot": len(approved_urls - snap) if snap is not None else None,                                            # ما اعتُمد بعدها بدفعات التوسيع (معلومة لا فشل)
                 "approved_routes": len(approved), "approved_entities": len(ids), "mode": mode, "checked_routes": len(scope), "checked_new": n_new, "checked_sample": n_sample}
            ok = (m["http_failures"] == 0 and m["canonical_failures"] == 0 and m["hreflang_failures"] == 0 and m["language_failures"] == 0 and m["robots_failures"] == 0
                  and m["indexable"] == len(scope) and m["unexpected_indexable"] == 0 and m["sitemap_missing"] == 0 and m["sitemap_unexpected"] == 0 and m["sitemap_public_mismatch"] == 0
                  and m["redirect_changes_since_phase4"] == 0 and m["redirect_chains"] == 0 and m["redirect_loops"] == 0 and m["slug_changes"] == 0 and m["entity_changes"] == 0
                  and m["redirect_target_failures"] == 0 and m["redirect_resolve_failures"] == 0
                  and (m["snapshot_mismatch"] in (0, None)))
            rec = {"snapshot": snapshot, "metrics": m, "failures": fails, "population_check": u, "redirect_audit": ra, "invariants_now": {k: v for k, v in inv.items() if k != "slugs"},
                   "baseline": None, "http": None,
                   "tests": [_t("phase7_routes_http_canonical_hreflang_language", m["http_failures"] == 0 and m["canonical_failures"] == 0 and m["hreflang_failures"] == 0 and m["language_failures"] == 0, m),
                             _t("phase7_indexability", m["indexable"] == len(scope) and m["robots_failures"] == 0 and m["unexpected_indexable"] == 0, m),
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
            res = _pass(rel, 7, rec, con, now, data_dir)
            full_at = now if mode == "full" else int((seo_db.state(con, PHASE7_FULL_KEY) or {}).get("at") or now)
            with con:
                seo_db.set_state(con, PHASE7_FULL_KEY, {"at": full_at, "count": len(approved)})      # ما اعتُمد حتى الآن تحقّق منه فحصٌ ناجح
            return res
        finally:
            con.close()


# ================= المرحلة 8 — التوسيع بدفعات =================
SEEN_KEY = "expand_seen"        # build_state: {معرّف الكيان: وقت آخر تجربةٍ له في دفعة} — ما جُرّب ولم يُعتمد لا يُعاد فورًا (وإلا دارت الدفعات على الأشهر نفسه)


def _seen_active(con, st, now=None):
    """معرّفات ما جُرّب حديثًا (ضمن expand_retry_days) — وتُقلَّم القديمة."""
    now = int(now or time.time())
    keep = now - int(st.get("expand_retry_days", 14)) * 86400
    return {int(k) for k, v in (seo_db.state(con, SEEN_KEY) or {}).items() if int(v or 0) >= keep}


def _seen_mark(con, ids, st, now=None):
    now = int(now or time.time())
    keep = now - int(st.get("expand_retry_days", 14)) * 86400 * 2
    cur = {k: v for k, v in (seo_db.state(con, SEEN_KEY) or {}).items() if int(v or 0) >= keep}
    for i in ids:
        cur[str(i)] = now
    with con:
        seo_db.set_state(con, SEEN_KEY, cur)


def _candidate_clause(con, st, approved):
    """شرط المرشّحين: حيٌّ متاح، غير معتمد، غير مجمّد، وغير مجرَّبٍ حديثًا (جدولٌ مؤقت: بلا حدّ متغيّرات SQLite)."""
    skip = {cid for cid, _ in approved} | seo_sources.frozen_ids(st) | _seen_active(con, st)
    con.execute("CREATE TEMP TABLE IF NOT EXISTS _skip(id INTEGER PRIMARY KEY)")
    con.execute("DELETE FROM _skip")
    con.executemany("INSERT OR IGNORE INTO _skip(id) VALUES (?)", [(i,) for i in skip])
    return "merged_into IS NULL AND available=1 AND id NOT IN (SELECT id FROM _skip)"


def candidates(con, st, approved, n):
    """الدفعة التالية: كيانات حيّة متاحة غير معتمدة وغير مجمّدة **وغير مجرَّبة حديثًا**، الأشهر أولًا ثم بالمعرّف (حتمي) — فتتقدّم الدفعات على الجديد بدل أن تعيد ما لا يستحق."""
    where = _candidate_clause(con, st, approved)
    return [r for r in con.execute(f"SELECT * FROM content WHERE {where} ORDER BY COALESCE(popularity,0) DESC, id LIMIT ?", (int(n),))]


def candidates_count(con, st, approved):
    return con.execute(f"SELECT COUNT(*) FROM content WHERE {_candidate_clause(con, st, approved)}").fetchone()[0]


TRANSIENT_ERRORS = (ConnectionError, TimeoutError, OSError, http.client.HTTPException)   # انقطاعٌ في الشبكة/ردٌّ مبتور من TMDB: ليس عيبًا في المحتوى
TMDB_RETRIES, TMDB_RETRY_PAUSE = 3, 1.0


def _tmdb_one(con, data_dir, cid, st, now):
    """إثراء كيانٍ من TMDB، وينتظر ويعيد عند الانقطاع العابر (3 محاولات: 1ث ثم 2ث) قبل أن يُحسب فشلًا."""
    for i in range(TMDB_RETRIES):
        try:
            return seo_sources._one(con, data_dir, cid, "tmdb", st, now)
        except seo_sources.Skip:
            raise
        except TRANSIENT_ERRORS:
            if i == TMDB_RETRIES - 1:
                raise
            time.sleep(TMDB_RETRY_PAUSE * (2 ** i))


def approved_redirect_changes(con, approved_ids, red_before, red_after):
    """كم تحويلًا **مصدره مسارُ عملٍ معتمد** تغيّر هدفه (أو زال) في الدفعة؟ — وهذا وحده عيب: المعتمد المفهرَس لا يبدأ بالتحويل ولا يتغيّر هدفه.
    أمّا تحويلات غير المعتمد التي أُعيد توجيهها إلى فائزٍ حين يُدمج مرشّحٌ فيه (مسار الخاسر وأسماؤه القديمة) فهي تقصيرٌ سليم للسلاسل، لا تُحسب."""
    paths = set()
    for i in approved_ids:
        r = _row(con, i)
        if r:
            paths.update(seo_db.paths(r["type"], r["slug"]))
    return sum(1 for p, t in red_before.items() if p in paths and red_after.get(p) != t)


BUSY_WAIT_MS = 120000        # أطول انتظارٍ لقفل الكتابة قبل أن تُؤجَّل الدفعة (الإثراء كلّه معاملةٌ واحدة تحتاج القفل من أولها)
BUSY_RETRIES = 10            # مرات إعادة الدفعة المؤجَّلة في المهمة (بفاصل BUSY_PAUSE ثانية) قبل أن تتوقف
BUSY_PAUSE = 60


def _write_lock(con):
    """يحجز قفل الكتابة من بداية الدفعة. ‏False إن بقي مشغولًا بعد BUSY_WAIT_MS (بدل أن تفشل كل عمليات الإثراء بـ «database is locked»)."""
    if con.in_transaction:
        con.commit()
    con.execute(f"PRAGMA busy_timeout={int(BUSY_WAIT_MS)}")
    try:
        con.execute("BEGIN IMMEDIATE")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        con.execute("PRAGMA busy_timeout=30000")


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
            if not _write_lock(con):        # عملية أخرى تكتب في القاعدة (بناءٌ/إثراءٌ آخر): ليس فشلَ دفعة ولا يوقف الإصدار — تُعاد لاحقًا
                return {"ok": False, "phase": 8, "status": "BUSY", "batch": k, "reason": "database busy: another process holds the write lock — will retry"}
            before = invariants(con, approved_ids | set(cand_ids))
            red_before = {r["path"]: r["target"] for r in con.execute("SELECT path, target FROM redirect")}
            # 1 — إثراء TMDB (معاملةٌ واحدة، بلا commit حتى تمرّ بوابات الهوية والتسوية)
            en = {"attempted": 0, "enriched": 0, "miss": 0, "failed": 0, "failed_transient": 0, "merged": [], "seasons": 0, "errors": []}
            failed_ids = set()
            for ri_, r in enumerate(cands):
                if ri_ % 5 == 0:
                    _tick(data_dir, "إثراء الدفعة من TMDB", ri_, len(cands))
                en["attempted"] += 1
                try:
                    state, msg = _tmdb_one(con, data_dir, r["id"], st, now)
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
                    tr_ = isinstance(ex, TRANSIENT_ERRORS)
                    en["failed"] += 1; en["failed_transient"] += int(tr_); failed_ids.add(r["id"])
                    en["errors"].append({"id": r["id"], "error": f"{type(ex).__name__}: {str(ex)[:120]}", "transient": tr_})
            hard_failed = en["failed"] - en["failed_transient"]
            tol = max(3, len(cands) // 50)                       # انقطاعاتٌ عابرة قليلة (≤ 2% أو 3) لا تُسقط دفعةً من 300 كيان: يُستثنى كيانها فقط ويُعاد لاحقًا
            if hard_failed == 0 and en["failed_transient"] > tol:     # الشبكة/TMDB غير مستقرّين: لا عيب في المحتوى ولا يُحظر الإصدار — تُعاد الدفعة نفسها لاحقًا
                con.rollback()
                return {"ok": False, "phase": 8, "status": "BUSY", "batch": k, "reason": f"TMDB/network unstable: {en['failed_transient']} transient failures in {len(cands)} — will retry"}
            # 2 — الهوية: كل مرشّحٍ إمّا حيٌّ بمعرّفه، أو مدمجٌ دمجًا مفسَّرًا (نفس tmdb مُتحقَّق، تحويلٌ مباشر إلى كيانٍ حيّ)؛ ولا كيانان حيّان بمعرّف TMDB واحد
            ident = {"conflicts": [], "unexplained_merges": [], "explained_merges": [], "tmdb_mismatch": []}
            red_after = {r["path"]: r["target"] for r in con.execute("SELECT path, target FROM redirect")}
            for cid in cand_ids:
                r = _row(con, cid)
                if r["merged_into"] is not None:
                    w = _row(con, r["merged_into"])
                    rv = con.execute("SELECT payload_json FROM review WHERE key=?", (f"merged:{r['merged_into']}:{cid}",)).fetchone()
                    direct = all(red_after.get(p) == t and t not in red_after for p, t in zip(seo_db.paths(r["type"], r["slug"]), seo_db.paths(w["type"], w["slug"]))) if w else False
                    wx = (seo_db.external(con, "content", w["id"]).get("tmdb") or {}) if w else {}      # الحامل قد يكون موثَّقًا في external_id وعمود tmdb_id فيه فارغ (كيانٌ أقدم)
                    same = bool(w is not None and w["merged_into"] is None and wx.get("verified") and str(wx.get("external_id") or "") and
                                (not str(w["tmdb_id"] or "") or str(wx.get("external_id")) == str(w["tmdb_id"])))
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
                     "approved_redirect_targets_changed": approved_redirect_changes(con, approved_ids, red_before, red_after),
                     "redirects_retargeted_other": sum(1 for p, t in red_before.items() if red_after.get(p) != t)}      # معلومة: تحويلاتٌ لغير المعتمد أُعيد توجيهها (دمج مرشّحٍ في فائز) — لا تُفشل البوابة
            # 4/5/6 — canonical · hreflang · الأهلية على المرشّحين الأحياء (غير معتمدين بعد: noindex بلا alternate)
            live_c = [cid for cid in cand_ids if (_row(con, cid) or {"merged_into": 1})["merged_into"] is None]
            tmp = {(cid, l): {"id": cid, "lang": l, "path": seo_pages._path(_row(con, cid), l), "slug": _row(con, cid)["slug"]} for cid in live_c for l in ("ar", "en")}
            g0, f0 = gate_routes(data_dir, con, st, tmp, expect_index=False)
            newly = [(cid, l) for cid in live_c if cid not in failed_ids for l in ("ar", "en") if seo_pages.indexable(_row(con, cid), l, st)[0]]
            elig = {"candidates_live": len(live_c), "newly_eligible_routes": len(newly), "newly_eligible_entities": len({c for c, _ in newly}),
                    "by_reason": {}}
            for cid in live_c:
                for l in ("ar", "en"):
                    why_ = seo_pages.indexable(_row(con, cid), l, st)[1]
                    elig["by_reason"][why_] = elig["by_reason"].get(why_, 0) + 1
            gate_ok = (not ident["conflicts"] and not ident["unexplained_merges"] and not ident["tmdb_mismatch"] and recon["split_delta"] == 0 and recon["approved_slug_changes"] == 0
                       and recon["approved_merged"] == 0 and recon["approved_redirect_targets_changed"] == 0 and recon["new_redirects"] == recon["new_redirects_direct"]
                       and ra["chains"] == 0 and ra["loops"] == 0 and ra["resolve_failures"] == 0 and g0["http_failures"] == 0 and g0["canonical_failures"] == 0 and g0["hreflang_failures"] == 0
                       and g0["language_failures"] == 0 and g0["robots_failures"] == 0 and hard_failed == 0)
            checks = {"identity_conflicts": not ident["conflicts"], "unexplained_merges": not ident["unexplained_merges"], "tmdb_mismatch": not ident["tmdb_mismatch"],
                      "split_delta": recon["split_delta"] == 0, "approved_slug_changes": recon["approved_slug_changes"] == 0, "approved_merged": recon["approved_merged"] == 0,
                      "approved_redirect_targets_changed": recon["approved_redirect_targets_changed"] == 0, "new_redirects_not_direct": recon["new_redirects"] == recon["new_redirects_direct"],
                      "redirect_chains": ra["chains"] == 0, "redirect_loops": ra["loops"] == 0, "redirect_resolve_failures": ra["resolve_failures"] == 0,
                      "http_failures": g0["http_failures"] == 0, "canonical_failures": g0["canonical_failures"] == 0, "hreflang_failures": g0["hreflang_failures"] == 0,
                      "language_failures": g0["language_failures"] == 0, "robots_failures": g0["robots_failures"] == 0, "tmdb_hard_failures": hard_failed == 0}
            failed_checks = [kk for kk, ok_ in checks.items() if not ok_]
            rec = {"batch": k, "n": len(cands), "failed_checks": failed_checks, "candidate_ids": cand_ids[:200], "tmdb": {kk: v for kk, v in en.items() if kk != "merged"}, "merges": en["merged"], "identity": ident, "reconciliation": recon,
                   "redirect_audit": ra, "canonical_hreflang_gate": g0, "gate_failures": f0, "eligibility": elig}
            if not gate_ok:
                con.rollback()                                              # لا أثر للدفعة في القاعدة
                rec["rolled_back"] = True
                return _batch_fail(rel, k, "batch gate failed (identity/reconciliation/redirect/canonical/hreflang: " + ", ".join(failed_checks) + ") — rolled back, nothing approved", rec, con=con, now=now, data_dir=data_dir)
            con.commit()                                                     # الإثراء اجتاز بواباته
            _seen_mark(con, [c for c in cand_ids if c not in failed_ids], st, now)                               # جُرّبت: لا تُعاد قبل expand_retry_days (المعتمد منها يخرج بالاعتماد)
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


# ================= مهمة التوسيع المستمرة (تكمل بنفسها بعد إعادة النشر) =================
JOB_KEY = "expand_job"      # build_state: {active, n, remaining, done, auto_resume, started_at, updated_at, last, stopped}
JOB_WATCHDOG_EVERY = 60


def job_get(data_dir):
    con = seo_db.connect(data_dir, create=False)
    if con is None:
        return {}
    try:
        return seo_db.state(con, JOB_KEY) or {}
    finally:
        con.close()


def _job_save(data_dir, job):
    con = seo_db.connect(data_dir)
    try:
        job["updated_at"] = int(time.time())
        with con:
            seo_db.set_state(con, JOB_KEY, job)
    finally:
        con.close()
    return job


def job_start(data_dir, n=100, max_batches=5, auto_resume=True, autopilot=False, every=5, pipeline=False, notify=False, trigger="manual"):
    """يُنشئ مهمة توسيعٍ محفوظة في القاعدة: n كيانًا للدفعة، وعدد دفعاتٍ أقصى، وإن كان `auto_resume` فالحارس يستأنفها وحده بعد أي إعادة تشغيل (نشرٌ أو سقوط)."""
    now = int(time.time())
    return _job_save(data_dir, {"active": True, "n": max(1, min(1000, int(n or 100))), "remaining": max(1, min(500, int(max_batches or 5))), "done": 0,
                                "auto_resume": bool(auto_resume), "started_at": now, "last": None, "stopped": None,
                                "autopilot": bool(autopilot or pipeline), "every": max(1, min(50, int(every or 5))), "cycles": 0, "cycle_log": [],
                                "pipeline": bool(pipeline), "launched": False, "final_file": None, "notify": bool(notify), "trigger": trigger,
                                "approved_before": _approved_counts(data_dir)})


def job_stop(data_dir, reason="stopped by admin"):
    job = job_get(data_dir)
    if job.get("active"):
        job.update({"active": False, "stopped": reason})
        _job_save(data_dir, job)
    return job


def run_job(data_dir, now=None, submit=None, progress=None):
    """ينفّذ دفعات المهمة المحفوظة واحدةً بعد أخرى، ويُحدّث الحالة بعد كل دفعة (فتبقى بعد إعادة التشغيل). يتوقف عند أول فشل أو نفاد المرشّحين أو
    انتهاء العدد أو أمر الإيقاف (يُقرأ قبل كل دفعة)."""
    out = []
    busy = 0
    job = job_get(data_dir)
    if job.get("active") and job.get("pipeline") and not job.get("launched"):
        ok_, why_ = _pipeline_launch(data_dir, progress)
        job = job_get(data_dir)
        if not ok_:
            job.update({"active": False, "stopped": f"pipeline: {why_}"})
            _job_save(data_dir, job)
            return {"ok": False, "batches": [], "job": job}
        job["launched"] = True
        _job_save(data_dir, job)
    while True:
        job = job_get(data_dir)
        if not job.get("active"):
            break
        if job.get("autopilot") and int(job.get("done") or 0) >= 2000:          # سقفٌ أمان
            job.update({"active": False, "stopped": "safety cap: 2000 batches"})
            _job_save(data_dir, job)
            break
        if not job.get("autopilot") and int(job.get("remaining") or 0) <= 0:
            job.update({"active": False, "stopped": "completed"})
            _job_save(data_dir, job)
            break
        if progress:
            progress(int(job.get("done") or 0) + 1)
        r = phase8_batch(data_dir, int(job.get("n") or 100), now=now, submit=submit)
        if r.get("status") == "BUSY":                 # القاعدة مشغولة بكاتبٍ آخر: انتظر وأعد الدفعة نفسها بلا فشلٍ ولا عدّ
            busy += 1
            if busy <= BUSY_RETRIES:
                job = job_get(data_dir)
                job["busy_retries"] = busy
                _job_save(data_dir, job)
                time.sleep(BUSY_PAUSE)
                continue
        else:
            busy = 0
        rec = {k: r.get(k) for k in ("ok", "batch", "status", "reason", "n", "approved_routes_total")}
        out.append(rec)
        job = job_get(data_dir)
        if not job.get("active"):          # أُوقفت أثناء الدفعة
            break
        job["last"] = {**rec, "at": int(time.time())}
        if not r.get("ok"):
            job.update({"active": False, "stopped": f"batch failed: {r.get('reason') or r.get('status')}"})
        elif r.get("status") == "EMPTY":
            job.update({"active": False, "stopped": "no candidates left"})
            if job.get("autopilot"):                      # ختامٌ آلي: فحصٌ ثم اعتماد القوائم والمواسم لما اعتُمد أخيرًا
                ok_, why_ = _autopilot_cycle(data_dir, job, progress)
                if not ok_:
                    job.update({"stopped": f"autopilot: {why_}"})
                elif job.get("pipeline"):                   # الختام: الحزمة النهائية للمراجعة
                    try:
                        fb = final_bundle(data_dir)
                        job.update({"final_file": fb.get("file"), "stopped": "completed: no candidates left"})
                    except Exception as ex:  # noqa: BLE001
                        job.update({"stopped": f"completed: no candidates left (final bundle failed: {type(ex).__name__})"})
        else:
            job["done"] = int(job.get("done") or 0) + 1
            job["remaining"] = int(job.get("remaining") or 0) - 1
            if job.get("autopilot") and job["done"] % int(job.get("every") or 5) == 0:
                _job_save(data_dir, job)
                ok_, why_ = _autopilot_cycle(data_dir, job, progress)
                if not ok_:
                    job.update({"active": False, "stopped": f"autopilot: {why_}"})
        _job_save(data_dir, job)
    return {"ok": all(b["ok"] for b in out), "batches": out, "job": job_get(data_dir)}


def _pipeline_launch(data_dir, progress=None):
    """الإطلاق الأول بزرٍّ واحد: المراحل 4 ← 5 ← 6 ← 7 على اللقطة الموجودة في مجلد المراجعة، كلٌّ منها **إن لم تكن PASS** (يُستأنف بعد انقطاع) — والمرحلة 7 دائمًا
    (تُرفع بها وسوم الإيقاف). أي فشلٍ = توقّف بسببه ← (نجح؟، السبب)."""
    meta = bundle_meta(data_dir)
    snap = (meta or {}).get("bundle_id")
    urls = snapshot_urls(data_dir)
    if not snap or urls is None:
        return False, "لا لقطة في مجلد المراجعة — أنتج «ملفات المراجعة» أولًا"
    con = seo_db.connect(data_dir, create=False)
    if con is None:
        return False, "no database"
    try:
        ph = _state(con)["phases"]
    finally:
        con.close()
    steps = ((4, lambda: phase4(data_dir, snap, len(urls))), (5, lambda: phase5(data_dir)), (6, lambda: phase6(data_dir)), (7, lambda: phase7(data_dir, snap, quick=True)))
    for n, fn in steps:
        if n < 7 and (ph.get(str(n)) or {}).get("status") == "PASS":
            continue
        if progress:
            progress(f"الإطلاق: المرحلة {n}")
        r = fn()
        if not r.get("ok"):
            return False, f"phase{n} failed — {str(r.get('reason') or r.get('error') or '')[:150]}"
    return True, ""


def _autopilot_cycle(data_dir, job, progress=None):
    """دورة الطيار الآلي: المرحلة 7 (فحصٌ بعد النشر) ← المرحلة 10 (القوائم والمواسم والهبّات لما اعتُمد حتى الآن). أي فشلٍ = توقّف بسببه ← (نجح؟، السبب)."""
    if progress:
        progress("autopilot: فحص بعد النشر")
    r7 = phase7(data_dir, None, quick=True)
    if not r7.get("ok"):
        return False, f"phase7 failed — {str(r7.get('reason') or '')[:150]}"
    if progress:
        progress("autopilot: اعتماد القوائم والمواسم")
    r10 = extras(data_dir, None)
    if not r10.get("ok"):
        return False, f"phase10 failed — {str(r10.get('reason') or '')[:150]}"
    job["cycles"] = int(job.get("cycles") or 0) + 1
    job["cycle_log"] = (job.get("cycle_log") or [])[-9:] + [{"at": int(time.time()), "done": job.get("done"), "routes": (r10.get("precheck") or {}).get("approved_routes")}]
    return True, ""


def job_watchdog_tick(data_dir):
    """مهمةٌ نشطةٌ بلا خيطٍ حيّ (أُعيد تشغيل الخادم): تُستأنف وحدها إن كان `auto_resume`، وإلا تُوقف بسبب الانقطاع."""
    job = job_get(data_dir)
    if not job.get("active"):
        return _auto_publish_tick(data_dir)
    k = os.path.abspath(data_dir)
    t = _threads.get(k)
    if t and t.is_alive():
        return None
    if not job.get("auto_resume"):
        job_stop(data_dir, "interrupted (server restarted; auto-resume off)")
        return "stopped"
    return "resumed" if start(data_dir, "expand_job") else None


KSA = 3 * 3600                    # توقيت السعودية UTC+3 (بلا توقيت صيفي)
NOTIFY = {"fn": None}             # دالة إرسال بريد التنبيه (تضبطها xm_lines): fn(subject, body) ← {ok، error}


def set_notifier(fn):
    NOTIFY["fn"] = fn


def _approved_counts(data_dir):
    con = seo_db.connect(data_dir, create=False)
    if con is None:
        return {"entities": 0, "routes": 0, "extras": 0}
    try:
        ap = seo_pages.approved_routes(con)
        return {"entities": len({c for c, _ in ap}), "routes": len(ap), "extras": len((seo_db.state(con, seo_pages.EXTRA_KEY) or {}).get("routes") or [])}
    finally:
        con.close()


def notify_job(data_dir, job, res=None, error=None):
    """بريدٌ بنتيجة مهمة النشر الآلي (اكتملت أو توقّفت بفشل) إن طُلب (`notify`): ما اعتُمد قبل/بعد، الدفعات، وسبب التوقّف مع اسم تقريره. لا يُسقط شيئًا إن تعذّر البريد."""
    fn = NOTIFY["fn"]
    if not fn or not job or not job.get("notify"):
        return None
    try:
        stopped = str(job.get("stopped") or "")
        failed = bool(error) or not stopped.startswith(("completed", "no candidates", "safety cap")) and stopped not in ("stopped by admin",)
        before, after = job.get("approved_before") or {}, _approved_counts(data_dir)
        con = seo_db.connect(data_dir, create=False)
        try:
            fail = _failure(_state(con), job) if con is not None and failed else None
        finally:
            if con is not None:
                con.close()
        when = time.strftime("%Y-%m-%d %H:%M", time.gmtime(time.time() + KSA))
        d_ent = after["entities"] - int(before.get("entities") or 0)
        if failed:
            subject = f"✖ SEO — توقّف النشر الآلي{(' عند ' + fail['where']) if fail and fail.get('where') else ''}"
        else:
            subject = f"✔ SEO — اكتمل النشر الآلي: +{d_ent} كيانًا"
        lines = [f"الوقت (السعودية): {when}", f"التشغيل: {'مجدول يوميًا' if job.get('trigger') == 'scheduled' else 'يدوي (الزرّ الواحد)'}",
                 f"الدفعات المنفّذة: {job.get('done', 0)} · دورات الفحص والاعتماد: {job.get('cycles', 0)}",
                 f"المعتمد (كيانات): {before.get('entities', 0)} ← {after['entities']} ({d_ent:+d})",
                 f"مسارات الكيانات: {before.get('routes', 0)} ← {after['routes']} · قوائم ومواسم: {before.get('extras', 0)} ← {after['extras']}"]
        if failed:
            lines += ["", f"السبب: {(fail or {}).get('reason') or stopped or error}"]
            if fail and fail.get("file"):
                lines.append(f"التقرير: {fail['file']} (admin ← المحتوى ← ملفات المراجعة)")
        else:
            lines += ["", f"النتيجة: {stopped or 'اكتمل'}"]
        return fn(subject, "\n".join(lines))
    except Exception:  # noqa: BLE001
        return None


def _ksa_day_hour(now):
    t = time.gmtime(int(now) + KSA)
    return time.strftime("%Y-%m-%d", t), t.tm_hour


AUTO_PUBLISH_EVERY = 1800        # (قديم) لم يعد يُستعمل: التشغيل يوميًا في الساعة المضبوطة


def _auto_publish_tick(data_dir, now=None):
    """نشرٌ آلي للمحتوى الجديد: إن فُعِّل `auto_publish` ولا مهمةٌ ولا عمليةٌ جارية وظهر مرشّحٌ جديد (كيانٌ لم يُجرَّب) ← تبدأ مهمة توسيعٍ آلية (دفعات ← فحص ← قوائم) حتى النفاد.
    بفاصلٍ لا يقلّ عن نصف ساعة، وتفشل بسببها ولا تتكرّر في حلقةٍ ضيقة."""
    now = int(now or time.time())
    k = os.path.abspath(data_dir)
    t = _threads.get(k)
    if t and t.is_alive():
        return None
    con = seo_db.connect(data_dir, create=False)
    if con is None:
        return None
    try:
        st = seo_db.settings(con)
        if not st.get("auto_publish") or not st.get("index_live"):
            return None
        today, hour = _ksa_day_hour(now)
        if hour < int(st.get("auto_publish_hour", 1)) or (seo_db.state(con, "auto_publish_state") or {}).get("day") == today:
            return None                                              # مرةً في اليوم، من الساعة المضبوطة (الواحدة صباحًا بتوقيت السعودية)
        rel = _state(con)
        if rel.get("blocked") or any((rel["phases"].get(str(n)) or {}).get("status") != "PASS" for n in (4, 5, 6, 7)):
            return None
        approved = seo_pages.approved_routes(con)
        has_new = bool(candidates(con, st, approved, 1))
        with con:
            seo_db.set_state(con, "auto_publish_state", {"day": today, "at": now, "ran": has_new})    # يومٌ مُنجَز ولو لم يكن جديد (بلا بريدٍ يوميٍّ فارغ)
        if not has_new:
            return None
    finally:
        con.close()
    job_start(data_dir, 300, 500, True, autopilot=True, every=5, notify=True, trigger="scheduled")
    return "auto_started" if start(data_dir, "expand_job") else None


def start_job_watchdog(data_dir):
    """خيط الحارس من إقلاع الخادم: يستأنف مهمة التوسيع بعد إعادة النشر دون تدخّل."""
    def loop():
        time.sleep(20)
        while True:
            try:
                job_watchdog_tick(data_dir)
            except Exception:  # noqa: BLE001 — الحارس لا يسقط
                pass
            time.sleep(JOB_WATCHDOG_EVERY)
    threading.Thread(target=loop, daemon=True, name="seo-expand-watchdog").start()


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
def _failure(rel, job):
    """سبب توقّف الزرّ الواحد (إن توقّف بفشل) ← {stopped، where، reason، file، at}: آخر مرحلةٍ أو دفعةٍ فشلت وسببها واسم تقريرها — ليُفحص ما حدث."""
    stopped = (job or {}).get("stopped") or ""
    if not job or job.get("active") or not stopped.startswith(("pipeline:", "autopilot:", "batch failed")):
        return None
    cand = []
    for n, p in (rel.get("phases") or {}).items():
        if p.get("status") == "FAIL":
            cand.append((p.get("at") or 0, f"المرحلة {n}", p, f"release-phase{n}.json"))
    for b in rel.get("batches") or []:
        if b.get("status") == "FAIL":
            cand.append((b.get("at") or 0, f"دفعة التوسيع {b.get('batch')}", b, f"release-batch-{b.get('batch')}.json"))
    latest = max(cand, key=lambda t: t[0]) if cand else None
    return {"stopped": stopped, "where": latest[1] if latest else None, "reason": (latest[2].get("reason") if latest else None) or stopped,
            "file": latest[3] if latest else None, "at": (latest[2].get("at") if latest else None) or job.get("updated_at")}


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
                "expand_candidates": candidates_count(con, st, approved), "auto_publish": bool(st.get("auto_publish")), "auto_publish_hour": int(st.get("auto_publish_hour", 1)), "auto_publish_state": seo_db.state(con, "auto_publish_state"), "notify_ready": bool(NOTIFY["fn"]), "expand_job": seo_db.state(con, JOB_KEY) or None, "failure": _failure(rel, seo_db.state(con, JOB_KEY) or {}),
                "live_entities_note": None, "index_extra_live": bool(st.get("index_extra_live")), "extras_approved_routes": len((seo_db.state(con, seo_pages.EXTRA_KEY) or {}).get("routes") or []),
                "approved_routes": len(approved), "approved_entities": len({c for c, _ in approved}),
                "live_entities": con.execute("SELECT COUNT(*) FROM content WHERE merged_into IS NULL AND available=1").fetchone()[0], "approved_snapshot": (seo_db.state(con, APPROVED_KEY) or {}).get("snapshot"),
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
        _progress[k] = {**{a: b for a, b in _progress[k].items() if a not in ("done", "total")}, "stage": str(x)}

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
            elif action == "expand_job":
                res = run_job(data_dir, progress=lambda i: prog(f"batch {i}"))
                notify_job(data_dir, res.get("job") or job_get(data_dir), res)
            elif action == "extras":
                res = extras(data_dir, kw.get("expected"))
            elif action == "final":
                res = final_bundle(data_dir)
            else:
                res = {"ok": False, "error": f"unknown action {action}"}
            _progress[k] = {**{a: b for a, b in _progress[k].items() if a not in ("done", "total")}, "stage": "done", "ok": bool(res.get("ok")), "result": {kk: v for kk, v in res.items() if kk in ("ok", "phase", "status", "reason", "stopped_at", "steps", "batches", "file")}}
        except Exception as e:  # noqa: BLE001
            import traceback
            if action == "expand_job":
                jb_ = job_get(data_dir)
                if jb_.get("active"):
                    jb_.update({"active": False, "stopped": f"error: {type(e).__name__}: {str(e)[:150]}"})
                    _job_save(data_dir, jb_)
                notify_job(data_dir, jb_, None, error=f"{type(e).__name__}: {str(e)[:200]}")
            _progress[k] = {**{a: b for a, b in _progress[k].items() if a not in ("done", "total")}, "stage": "error", "ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}", "traceback": traceback.format_exc()[-1500:]}
    t = _threads[k] = threading.Thread(target=run_, daemon=True)
    t.start()
    return True


# ================= المرحلة 10 — اعتماد القوائم والمواسم والحلقات والهبّات =================
EXTRA_STATE = "release_extras"     # build_state: آخر تشغيل {at, routes, kinds, submitted: [مسارات أُرسلت إلى IndexNow]}


def extras_candidates(con, st):
    """مرشّحو الاعتماد من غير الكيانات ← [(المسار العربي، النوع، معرّف المسلسل الأب أو None، اللغات المسموحة أو None)].
    تُعدَّد من القاعدة (لا زحف) بالعتبات نفسها التي يرسم بها seo_pages؛ والرسم وحده يحكم الأهلية بعد ذلك (index_ar/index_en)."""
    size, max_pages, min_items = int(st.get("page_size", 60)), int(st.get("list_max_pages", 50)), int(st.get("list_min_items", 12))
    out = []

    def paged(base, total, kind, first=True):
        pages = min(max_pages, max(1, -(-total // size)))
        for pg in range(1 if first else 2, pages + 1):
            out.append((base + (f"page/{pg}/" if pg > 1 else ""), kind, None, None))

    for facet, kind in seo_pages.TAX_KINDS.items():
        for r in con.execute("SELECT t.slug, COUNT(DISTINCT c.id) n FROM taxonomy t JOIN content_taxonomy ct ON ct.taxonomy_id=t.id JOIN content c ON c.id=ct.content_id "
                             "WHERE t.kind=? AND ct.source IN ('tmdb','manual') AND c.merged_into IS NULL AND c.available=1 GROUP BY t.id HAVING n>=? ORDER BY t.slug", (kind, min_items)):
            if kind == "country" and r["slug"] == "tr":
                continue                        # التركي هبٌّ مستقل (لا صفحتان تتنافسان)
            paged(f"/content/{facet}/{r['slug']}/", r["n"], "list")
    for r in con.execute("SELECT year, COUNT(*) n FROM content WHERE merged_into IS NULL AND available=1 AND year BETWEEN 1900 AND 2100 GROUP BY year HAVING n>=? ORDER BY year", (min_items,)):
        paged(f"/content/year/{r['year']}/", r["n"], "list")
    for sec in ("", "movies", "series"):
        where, wargs = seo_pages._tax_where("latest", "", sec)
        n = con.execute(f"SELECT COUNT(*) {where}", wargs).fetchone()[0]
        paged("/content/latest/" + (f"{sec}/" if sec else ""), n, "list")
    for hub in seo_pages.HUBS:
        base = f"/content/{hub}/"
        out.append((base, "hub", None, None))
        total_all = seo_pages._hub_rows(con, hub, "", None, None, 1, 1)[0]
        paged(base, total_all, "hub", first=False)
        for sec in seo_pages.HUB_SECTIONS:
            n = seo_pages._hub_rows(con, hub, sec, None, None, 1, 1)[0]
            if n:
                paged(f"{base}{sec}/", n, "hub")
        for sec in ("",) + seo_pages.HUB_SECTIONS:
            sql, args = seo_pages._hub_query(con, hub, sec)
            for g in con.execute("SELECT t.slug FROM taxonomy t WHERE t.kind='genre'"):
                n = seo_pages._hub_rows(con, hub, sec, g["slug"], None, 1, 1)[0]
                if n >= min_items:
                    paged(f"{base}{sec + '/' if sec else ''}genres/{g['slug']}/", n, "hub")
            for y in con.execute(f"SELECT c.year, COUNT(*) n FROM ({sql}) c WHERE c.year IS NOT NULL GROUP BY c.year HAVING n>=?", (*args, min_items)):
                paged(f"{base}{sec + '/' if sec else ''}year/{y['year']}/", y["n"], "hub")
    if st.get("content_hub"):
        out.append(("/content/", "hub_root", None, None))
    # المواسم والحلقات: لمسلسلات معتمدة فقط، وباللغات المعتمدة لها، وبالشروط نفسها (season_ok / episode_ok)
    approved = seo_pages.approved_routes(con)
    langs_of = {}
    for (cid, lang) in approved:
        langs_of.setdefault(cid, set()).add(lang)
    for cid, langs in sorted(langs_of.items()):
        r = _row(con, cid)
        if not r or r["type"] != "series" or r["merged_into"] is not None or not r["available"]:
            continue
        for s_ in con.execute("SELECT * FROM season WHERE content_id=? AND number>0 ORDER BY number", (cid,)):
            eps = con.execute("SELECT * FROM episode WHERE content_id=? AND season=? ORDER BY number LIMIT 300", (cid, s_["number"])).fetchall()
            ls = {l for l in langs if seo_pages.season_ok(s_, eps, l, st)[0]}
            if ls:
                out.append((f"/content/series/{r['slug']}/season-{s_['number']}/", "season", cid, ls))
            for e in eps:
                le = {l for l in langs if seo_pages.episode_ok(e, l, st)}
                if le:
                    out.append((f"/content/series/{r['slug']}/season-{s_['number']}/episode-{e['number']}/", "episode", cid, le))
    return out


def _extra_expected_tags(path, both):
    return {"ar": SITE + path, "en": SITE + seo_db.EN + path, "x-default": SITE + path} if both else {}


def extras_gate(data_dir, con, st, routes, candidates_ineligible=()):
    """بوابة الصفحات غير الكيانية كما تُخدم فعلًا ← (مقاييس، فشل): 200 · وسم index بلا رأس noindex · canonical ذاتي · lang · hreflang
    (متبادلةٌ حين تُعتمد اللغتان، وإلا بلا وسوم) · لا استعلام · لا تحويل · لا canonical مكرّر · وغير المعتمد المرشَّح noindex."""
    redirects = {r["path"] for r in con.execute("SELECT path FROM redirect")}
    have = {(x["path"], x["lang"]) for x in routes}
    m = {"routes": len(routes), "http_failures": 0, "robots_failures": 0, "canonical_failures": 0, "language_failures": 0, "hreflang_failures": 0,
         "redirect_urls": 0, "query_urls": 0, "duplicate_canonical": 0, "not_noindex": 0, "checked_not_approved": 0}
    fails, seen = [], {}
    for xi_, x in enumerate(routes):
        if xi_ % 25 == 0:
            _tick(data_dir, "فحص الصفحات المعتمدة كما تُخدم", xi_, len(routes))
        path, lang = x["path"], x["lang"]
        full = seo_db.lang_prefix(lang) + path
        bad = []
        if "?" in full or "#" in full:
            m["query_urls"] += 1; bad.append("query")
        if path in redirects:
            m["redirect_urls"] += 1; bad.append("redirect path")
        res = seo_pages.handle(data_dir, full, lang)
        if not res or res[0] != 200:
            m["http_failures"] += 1; fails.append({"path": full, "problems": bad + [f"http={res[0] if res else None}"]}); continue
        text = res[1].decode("utf-8", "replace")
        if "X-Robots-Tag" in res[2] or 'name="robots" content="index, follow' not in text:
            m["robots_failures"] += 1; bad.append("not index")
        can = re.search(r'<link rel="canonical" href="([^"]+)"', text)
        if not can or can.group(1) != SITE + full:
            m["canonical_failures"] += 1; bad.append(f"canonical {can.group(1) if can else None}")
        else:
            if can.group(1) in seen:
                m["duplicate_canonical"] += 1; bad.append("duplicate canonical")
            seen[can.group(1)] = 1
        if f'<html lang="{lang}"' not in text:
            m["language_failures"] += 1; bad.append("html lang")
        tags = dict(seo_qa.ALT_RX.findall(text))
        if tags != _extra_expected_tags(path, (path, "ar") in have and (path, "en") in have):
            m["hreflang_failures"] += 1; bad.append(f"hreflang {tags}")
        if bad:
            fails.append({"path": full, "problems": bad})
    for path, lang in list(candidates_ineligible)[:300]:      # مرشّحٌ غير مستحقّ بتلك اللغة يبقى noindex (لا يتسرّب)
        res = seo_pages.handle(data_dir, seo_db.lang_prefix(lang) + path, lang)
        m["checked_not_approved"] += 1
        if res and res[0] == 200 and "X-Robots-Tag" not in res[2]:
            m["not_noindex"] += 1; fails.append({"path": seo_db.lang_prefix(lang) + path, "problems": ["not approved but served index"]})
    m["failures_total"] = len(fails)
    return m, fails[:50]


def extras_paths(con, st):
    """مسارات الخريطة للصفحات غير الكيانية: المعتمد المستحقّ (يُخدم index فعلًا) ← [(مسار بالبادئة، النوع)] — فارغٌ قبل index_extra_live."""
    if not (st.get("index_live") and st.get("index_extra_live")):
        return []
    stt = seo_db.state(con, seo_pages.EXTRA_KEY) or {}
    redirects = {r["path"] for r in con.execute("SELECT path FROM redirect")}
    return [(seo_db.lang_prefix(x["lang"]) + x["path"], x.get("kind", "")) for x in stt.get("routes") or [] if x["path"] not in redirects]


# ================= عدّاد الصفحات: ما اعتُمد، وما في الخريطة، وما فُهرس فعلًا عند قوقل (عيّنة) =================
GSC_STATE = "gsc_sample"
_gsc_threads = {}


def gsc_bucket(state, verdict=""):
    """نصّ coverageState عند جوجل ← فئة: indexed · crawled (زُحف ولم يُفهرس) · discovered (اكتُشف ولم يُزحَف) · unknown (لا يعرفه) · other."""
    low = (state or "").lower()
    if "not indexed" in low and "crawled" in low:
        return "crawled"
    if "not indexed" in low and "discovered" in low:
        return "discovered"
    if "unknown to google" in low:
        return "unknown"
    if "indexed" in low and "not" not in low or verdict == "PASS":
        return "indexed"
    return "other"


def visibility(data_dir):
    """← أعداد صفحات المحتوى بمراحلها: معتمدة للفهرسة (كيانات ومساراتها ثم القوائم والمواسم) ← في الخريطة ← أُرسلت إلى IndexNow ← (عيّنة) مفهرسةٌ عند قوقل."""
    con = seo_db.connect(data_dir, create=False)
    if con is None:
        return {"error": "no database"}
    try:
        st = seo_db.settings(con)
        approved = seo_pages.approved_routes(con)
        rel = _state(con)
        ix = {"submitted": 0, "accepted": 0}
        for b in rel.get("batches") or []:
            n = b.get("indexnow") or {}
            ix["submitted"] += int(n.get("submitted") or 0)
            ix["accepted"] += int(n.get("accepted") or 0)
        for k in ("6", "10"):
            n = (rel.get("phases", {}).get(k) or {}).get("indexnow") or {}
            ix["submitted"] += int(n.get("submitted") or 0)
            ix["accepted"] += int(n.get("accepted") or 0)
        extras = len(seo_pages.extra_approved(con))
        sample = seo_db.state(con, GSC_STATE) or None
        k = os.path.abspath(data_dir)
        creds = analytics.google_creds(data_dir)
        out = {"entities": len({c for c, _ in approved}), "entity_routes": len(approved), "extra_routes": extras, "index_live": bool(st.get("index_live")),
               "sitemap_live": bool(st.get("sitemap_live")), "indexnow": ix,
               "gsc": {"connected": bool(creds and creds.get("site")), "site": (creds or {}).get("site", ""), "sample": sample,
                       "running": bool(_gsc_threads.get(k) and _gsc_threads[k].is_alive())}}
    finally:
        con.close()
    out["sitemap_urls"] = len(public_sitemap_entries(data_dir))
    return out


def gsc_sample_start(data_dir, n=40):
    """يفحص عيّنةً عشوائية (حتى 100) من الصفحات المعتمدة عند جوجل في الخلفية ← هل بدأ؟ (لا يبدأ إن كان يعمل، أو الربط ناقص)."""
    import random
    import google_api
    k = os.path.abspath(data_dir)
    t = _gsc_threads.get(k)
    if t and t.is_alive():
        return False, "يعمل الآن"
    creds = analytics.google_creds(data_dir)
    if not creds or not creds.get("site"):
        return False, "اربط Search Console أولًا (صفحة الإحصائيات ← ربط جوجل)"
    paths = [p for p, *_ in public_sitemap_entries(data_dir)]
    if not paths:
        return False, "لا صفحات معتمدة في الخريطة بعد"
    n = max(5, min(100, int(n or 40)))
    pick = random.sample(paths, min(n, len(paths)))
    site_url = guide_pages.SITE

    def save(state):
        c = seo_db.connect(data_dir, create=False)
        try:
            with c:
                seo_db.set_state(c, GSC_STATE, state)
        finally:
            c.close()

    def work():
        state = {"running": True, "started": int(time.time()), "total": len(pick), "done": 0, "counts": {}, "samples": [], "error": None, "site": creds["site"], "sitemap_total": len(paths)}
        save(state)
        try:
            tok = google_api.token(creds["sa"])
            for p in pick:
                try:
                    r = google_api.inspect_url(tok, creds["site"], site_url + p)
                except google_api.GoogleError as e:
                    state["error"] = f"{e.msg} {e.hint}".strip()[:300]
                    if e.code in (401, 403, 429):
                        break
                    state["done"] += 1
                    continue
                b = gsc_bucket(r["state"], r["verdict"])
                state["counts"][b] = state["counts"].get(b, 0) + 1
                if len(state["samples"]) < 12:
                    state["samples"].append({"path": p, "state": r["state"], "bucket": b})
                state["done"] += 1
                if state["done"] % 5 == 0:
                    save(state)
                time.sleep(0.4)
        except Exception as e:  # noqa: BLE001
            state["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        state["running"] = False
        state["at"] = int(time.time())
        save(state)

    th = _gsc_threads[k] = threading.Thread(target=work, daemon=True)
    th.start()
    return True, ""


def public_sitemap_entries(data_dir):
    """كل ما تضيفه طبقة الكيانات إلى /sitemap.xml: صفحات الكيانات (المرحلة 5) + القوائم والمواسم والحلقات والهبّات المعتمدة (المرحلة 10)."""
    ents = sitemap_entries(data_dir)
    con = seo_db.connect(data_dir, create=False)
    if con is None:
        return ents
    try:
        st = seo_db.settings(con)
        if not st.get("sitemap_live"):
            return ents
        return ents + [(p, "daily" if "/latest/" in p or k == "hub_root" else "weekly", "0.5") for p, k in extras_paths(con, st)]
    finally:
        con.close()


def _xfail(rel, reason, extra=None, con=None, now=None, data_dir=None):
    rec = {"status": "FAIL", "at": now, "reason": reason, **(extra or {})}
    rel["phases"]["10"] = rec                      # لا يُرفع به عائق الدفعات: فشل هذه المرحلة يتراجع عن نفسه فقط
    if con is not None:
        _save_state(con, rel, now)
    if data_dir:
        rec["file"] = _write(data_dir, "release-phase10.json", {"phase": 10, **rec, "code": seo_sources.code_version()})
    return {"ok": False, "phase": 10, **rec}


def extras(data_dir, expected=None, now=None, submit=None):
    """اعتماد القوائم والمواسم والحلقات والهبّات (وهب /content/ إن فُعّل): تُعدَّد المرشّحة، ويحكم الرسم أهلية كل لغة، ثم تُكتب قائمة الاعتماد
    (`index_approved_extra`) ويُفعَّل `index_extra_live` ويُفحص الناتج كما يُخدم (بوابة extras_gate) وعضوية الخريطة العامة، ثم IndexNow للجديد وحده.
    أي فشل = تراجعٌ كامل (الاعتماد والإعداد كما كانا) ولا شيء يُرسل. يشترط نجاح المراحل 4 و5 و7 (الكيانات حيّة وخريطتها مفعّلة)."""
    now = _now(now)
    submit = submit or analytics.submit
    with seo_db.lock(data_dir):
        con = seo_db.connect(data_dir, create=False)
        if con is None:
            return {"ok": False, "phase": 10, "error": "no database"}
        try:
            st = seo_db.settings(con)
            rel = _state(con)
            why = _requires(rel, st, 4, 5, 7) or ("" if st.get("sitemap_live") else "sitemap_live is off") or ("" if st.get("preview") else "preview is off")
            if why:
                return _xfail(rel, why, con=con, now=now, data_dir=data_dir)
            prev_state, prev_live = seo_db.state(con, seo_pages.EXTRA_KEY), bool(st.get("index_extra_live"))
            routes, ineligible, kinds, not_rendered = [], [], {}, 0
            cands_ = extras_candidates(con, st)
            for ci_, (path, kind, parent, langs) in enumerate(cands_):
                if ci_ % 25 == 0:
                    _tick(data_dir, "تقييم أهلية الصفحات المرشّحة", ci_, len(cands_))
                info = seo_pages.handle(data_dir, path, "ar", _info=True)      # الرسم يحكم الأهلية (index_ar / index_en)
                if not isinstance(info, dict):
                    not_rendered += 1
                    continue
                for lang in ("ar", "en"):
                    if info.get("index_" + lang) and (langs is None or lang in langs):
                        routes.append({"path": path, "lang": lang, "kind": kind, "parent": parent})
                        kinds[kind] = kinds.get(kind, 0) + 1
                    else:
                        ineligible.append((path, lang))
            pre = {"candidates": len(routes) + len(ineligible), "approved_routes": len(routes), "kinds": kinds, "not_rendered": not_rendered}
            if expected is not None and len(routes) != int(expected):
                return _xfail(rel, f"extras carry {len(routes)} routes, expected {expected}", {"precheck": pre}, con=con, now=now, data_dir=data_dir)
            if not routes:      # لا قوائم/مواسم/حلقات مؤهلة بعد: ليس فشلًا (لا شيء يُعتمد) — فلا يُسجَّل ولا يوقف الطيار الآلي
                return {"ok": True, "phase": 10, "skipped": True, "reason": "no eligible extra pages", "precheck": pre}

            def restore():
                with con:
                    if prev_state is None:
                        con.execute("DELETE FROM build_state WHERE key=?", (seo_pages.EXTRA_KEY,))
                    else:
                        seo_db.set_state(con, seo_pages.EXTRA_KEY, prev_state)
                seo_db.set_setting(con, "index_extra_live", prev_live)
                seo_pages._extra_cache.clear()

            with con:
                seo_db.set_state(con, seo_pages.EXTRA_KEY, {"at": now, "routes": routes})
            seo_db.set_setting(con, "index_extra_live", True)
            seo_pages._extra_cache.clear()
            st2 = seo_db.settings(con)
            m, fails = extras_gate(data_dir, con, st2, routes, ineligible)
            served = extras_paths(con, st2)
            entries = public_sitemap_entries(data_dir)
            xml = guide_pages.sitemap(C.sitemap(data_dir) + list(entries)).decode("utf-8", "replace")
            public = set(LOC_RX.findall(xml))
            want = {SITE + p for p, _ in served}
            m.update({"served_entries": len(served), "public_sitemap_mismatch": len(want - public), "duplicates": len(served) - len(want)})
            ok = (m["failures_total"] == 0 and len(served) == len(routes) and m["public_sitemap_mismatch"] == 0 and m["duplicates"] == 0)
            rec = {"precheck": pre, "metrics": m, "failures": fails, "sample": [SITE + p for p, _ in served[:10]],
                   "tests": [_t("phase10_served_as_index", m["http_failures"] == 0 and m["robots_failures"] == 0 and m["canonical_failures"] == 0 and m["language_failures"] == 0, m),
                             _t("phase10_hreflang", m["hreflang_failures"] == 0, m),
                             _t("phase10_no_leak", m["not_noindex"] == 0 and m["redirect_urls"] == 0 and m["query_urls"] == 0 and m["duplicate_canonical"] == 0, m),
                             _t("phase10_sitemap", len(served) == len(routes) and m["public_sitemap_mismatch"] == 0 and m["duplicates"] == 0, m)]}
            if not ok:
                restore()
                return _xfail(rel, "extras gate failed — rolled back, nothing approved", rec, con=con, now=now, data_dir=data_dir)
            done = set((seo_db.state(con, EXTRA_STATE) or {}).get("submitted") or [])
            fresh = [SITE + p for p, _ in served if SITE + p not in done]
            sent, accepted = 0, True
            for i in range(0, len(fresh), 10000):
                res = submit(data_dir, HOST, fresh[i:i + 10000], kind="extras")
                sent += res.get("n", 0)
                if not res.get("ok"):
                    accepted = False; rec["indexnow_error"] = f"{res.get('code')} {res.get('msg')}"
                    break
            rec["indexnow"] = {"new": len(fresh), "submitted": sent, "accepted": accepted,
                               "note": "IndexNow acceptance (200/202) is a receipt; it does not mean the search engine indexed the pages"}
            if not accepted:      # الاعتماد صحيح والصفحات تُخدم؛ الإرسال وحده يُعاد (لا يُسجَّل المُرسَل فيُعاد كله)
                rec["tests"].append(_t("phase10_indexnow", False, rec["indexnow"]))
                return _xfail(rel, "IndexNow not accepted — approval kept, resend by running extras again", rec, con=con, now=now, data_dir=data_dir)
            with con:
                seo_db.set_state(con, EXTRA_STATE, {"at": now, "routes": len(routes), "kinds": kinds, "submitted": sorted(done | set(fresh))})
            rec["tests"].append(_t("phase10_indexnow", True, rec["indexnow"]))
            return _pass(rel, 10, rec, con, now, data_dir)
        finally:
            con.close()


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
    elif cmd == "extras":
        res = extras(data_dir, exp)
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

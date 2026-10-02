# -*- coding: utf-8 -*-
"""الفحص النهائي قبل المرحلة 3 (**قراءةٌ صرفة**): عيّنة 30 عملًا بصفحاتها، والتحويلات، وخريطة موقعٍ تجريبية لا تُخدم،
وتجربة IndexNow بلا إرسال، وأخطاء الطابور، وحال كاسبر — كلٌّ اختبارٌ له ناجح/فاشل وتفصيله. لا يكتب في القاعدة شيئًا:
لا دمج ولا روابط ولا تحويلات ولا إثراء، ولا يُرسل إلى أي خدمة.

    python seo_qa.py                       # التقرير JSON
    python seo_qa.py --sitemap=staging.xml  # ومعه خريطة الموقع التجريبية في ملفٍ (لا تُخدم)
    python seo_qa.py --redirects=audit.json # تدقيق التحويلات غير الحية كلها وحده (16 حقلًا وتصنيفٌ لكلٍّ)
"""
import json
import os
import re
import sys
import time

import analytics
import content as C
import content_page as P
import seo_db
import seo_pages
import seo_sources

SITE = seo_pages.SITE
HOST = SITE.split("//", 1)[1]
SPEC = {"movie": 10, "series": 10, "turkish": 5, "anime": 5, "titles": ["Prison Break", "One Piece"]}   # أعمالٌ بأسمائها تُفحص دائمًا (فالكون بصفّين)
LD_RX = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
SRV_RX = re.compile(r'<ul class="srv">(.*?)</ul>', re.S)


def _t(name, ok, detail=""):
    return {"test": name, "ok": bool(ok), "detail": detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False, default=str)[:400]}


def _lds(html):
    out = []
    for s in LD_RX.findall(html):
        try:
            out.append(json.loads(s.replace("<\\/", "</")))
        except ValueError:
            out.append(None)
    return out


def pick(con, spec=None):
    """العيّنة: 10 أفلام · 10 مسلسلات · 5 تركي · 5 أنمي — من الحيّ المتاح، المطابَق بـ TMDB أولًا (صفحاته تُقيَّم كما ستُفهرس)،
    ثم غيره إن قلّ. التركي والأنمي من عضوية الهب (مؤكّدةً أو قرينةً)."""
    spec = {**SPEC, **(spec or {})}
    picked, seen = [], set()
    base = "SELECT c.id, c.type, c.slug FROM content c WHERE c.merged_into IS NULL AND c.available=1"
    hub = " AND c.id IN (SELECT ct.content_id FROM content_taxonomy ct JOIN taxonomy t ON t.id=ct.taxonomy_id WHERE t.kind='hub' AND t.key=?)"

    for t in spec.get("titles") or []:
        for r in seo_sources._by_title(con, t):
            if r["merged_into"] is None and r["id"] not in seen:
                seen.add(r["id"]); picked.append({"id": r["id"], "type": con.execute("SELECT type FROM content WHERE id=?", (r["id"],)).fetchone()[0], "slug": r["slug"], "group": "title"})

    def take(label, where, args, n):
        for order in (" AND c.match='tmdb' ORDER BY COALESCE(c.popularity,0) DESC, c.id", " ORDER BY COALESCE(c.last_seen,0) DESC, c.id DESC"):
            for r in con.execute(base + where + order + " LIMIT ?", (*args, n * 3)):
                if r["id"] not in seen and sum(1 for p in picked if p["group"] == label) < n:
                    seen.add(r["id"]); picked.append({"id": r["id"], "type": r["type"], "slug": r["slug"], "group": label})
    take("turkish", hub, ("turkish",), spec["turkish"])
    take("anime", hub, ("anime",), spec["anime"])
    take("movie", " AND c.type='movie'", (), spec["movie"])
    take("series", " AND c.type='series'", (), spec["series"])
    return picked


def _page(data_dir, con, row, lang, st):
    tr = P.lang_of(lang)
    res = seo_pages.render_entity(con, data_dir, row["type"], row["slug"], tr, st)
    if not res or res[0] != "page":
        return None
    code, body, hdr = seo_pages.handle(data_dir, seo_pages._path(row, lang), lang)
    return {**res[1], "text": res[1]["html"].decode("utf-8"), "code": code, "headers": hdr, "served": body}


ALT_RX = re.compile(r'<link rel="alternate" hreflang="([^"]+)" href="([^"]+)">')


def hreflang_check(pages):
    """قاعدة hreflang (المواصفة §hreflang في phase2-design): المجموعة ar/en/x-default **متبادلةً** في الصفحتين حين تستحق اللغتان
    الفهرسة؛ وحين تستحق لغةٌ واحدة لا تُرسل أي وسم alternate (hreflang إلى صفحة noindex يُهمَل ويُعدّ خطأً) وتبقى كل صفحة canonical
    لنفسها مع رابط تبديل اللغة. يُفحص السلوك المطلوب في الحالتين لا يُتخطّى ← (ناجح؟، التفصيل بـ hreflang_mode)."""
    ok_ar, ok_en = bool(pages["ar"]["index_ar"]), bool(pages["en"]["index_en"])
    tags = {l: dict(ALT_RX.findall(p["text"])) for l, p in pages.items()}
    canon_self = all(f'rel="canonical" href="{p["canonical"]}"' in p["text"] for p in pages.values())
    switch = all('class="lang"' in p["text"] for p in pages.values())
    detail = {"eligibility": {"ar": pages["ar"]["why"][0], "en": pages["en"]["why"][1]}, "tags": tags}
    if ok_ar and ok_en:
        want = {"ar": pages["ar"]["canonical"], "en": pages["en"]["canonical"], "x-default": pages["ar"]["canonical"]}
        ok = tags["ar"] == want and tags["en"] == want and canon_self
        detail.update({"hreflang_mode": "bilingual", "expected": want, "reciprocal": tags["ar"] == tags["en"] == want})
    else:
        ok = not tags["ar"] and not tags["en"] and canon_self and switch
        detail.update({"hreflang_mode": "single:" + ("ar" if ok_ar else "en" if ok_en else "none"), "rule": "one eligible language → no alternate tags on either page; canonical self; language switch link",
                       "no_alternate_tags": not tags["ar"] and not tags["en"], "canonical_self": canon_self, "language_switch": switch})
    return ok, detail


def _snip(html, rx):
    return [m.group(0) for m in re.finditer(rx, html)]


def coverage(data_dir, con, st, limit=1500):
    """تغطيةٌ شاملة لا عيّنة، حتميةٌ (بترتيب المعرّف، بلا عشوائية): كل كيانٍ حيّ يستحق الفهرسة بلغةٍ واحدة على الأقل (ما ستحمله
    خريطة المرحلة 3) تُرسم صفحتاه وتُفحص: HTTP، canonical ذاتي ومطابق للمسار، `<html lang>`، قاعدة hreflang (كاملة متبادلة مع
    x-default حين تستحق اللغتان؛ ولا وسم حين تستحق واحدة)، عضوية الخريطة، لا canonical مكرّر، لا استعلامات، لا مسارات تحويلٍ
    قديمة. ومع ذلك أهلية اللغات على القاعدة كلها بلا رسم. `limit` يحمي من رسم آلاف الصفحات: ما لم يُرسم يُعدّ ويُعلَن
    coverage_complete=false. وأمثلةٌ فعلية من HTML المرسوم تثبت السلوك في الحالتين."""
    elig = {"both": 0, "ar_only": 0, "en_only": 0, "none": 0}
    pop = []
    total_live = 0
    for r in con.execute("SELECT * FROM content WHERE merged_into IS NULL AND available=1 ORDER BY id"):
        total_live += 1
        a, e = seo_pages.indexable(r, "ar", st)[0], seo_pages.indexable(r, "en", st)[0]
        elig["both" if a and e else "ar_only" if a else "en_only" if e else "none"] += 1
        if a or e:
            pop.append(r)
    smap_rows = sitemap_urls(con, st)
    smap = {u for u, _, _ in smap_rows}
    redirect_paths = {r["path"] for r in con.execute("SELECT path FROM redirect")}
    m = {"total_canonical_entities": total_live, "intended_indexable_population": len(pop), "tested_population": 0, "coverage_pct": 0.0,
         "ar_routes": 0, "en_routes": 0, "ar_routes_200": 0, "en_routes_200": 0, "would_index_true_pages": len(smap_rows),
         "bilingual_indexable_pairs": elig["both"], "hreflang_complete": 0, "hreflang_incomplete": 0, "single_language_pages_without_alternates": 0, "single_language_pages_with_stray_alternates": 0,
         "canonical_self_failures": 0, "canonical_mismatch": 0, "missing_x_default": 0, "language_mismatch": 0, "http_non_200": 0, "reciprocity_failures": 0,
         "duplicate_canonical": 0, "faceted_or_query_urls": 0, "old_redirect_urls_in_sitemap": 0, "sitemap_membership_mismatch": 0}
    canon_seen, fails, modes, examples = {}, [], {"bilingual": 0, "single:ar": 0, "single:en": 0}, {}
    for r in pop[:limit]:
        pages = {l: _page(data_dir, con, r, l, st) for l in ("ar", "en")}
        m["ar_routes"] += 1; m["en_routes"] += 1
        m["tested_population"] += 1
        bad = []
        for l, p in pages.items():
            if p and p["code"] == 200:
                m[f"{l}_routes_200"] += 1
            else:
                m["http_non_200"] += 1; bad.append(f"http_{l}={p['code'] if p else None}")
        if bad:
            fails.append({"id": r["id"], "slug": r["slug"], "problems": bad}); continue
        for l, p in pages.items():
            expected = SITE + seo_pages._path(r, l)
            if p["canonical"] != expected:
                m["canonical_mismatch"] += 1; bad.append(f"canonical_mismatch_{l}")
            if f'<link rel="canonical" href="{p["canonical"]}">' not in p["text"]:
                m["canonical_self_failures"] += 1; bad.append(f"canonical_self_{l}")
            if f'<html lang="{l}"' not in p["text"] or (l == "en") != p["canonical"].startswith(SITE + seo_db.EN + "/"):
                m["language_mismatch"] += 1; bad.append(f"language_{l}")
            if p["canonical"] in canon_seen and canon_seen[p["canonical"]] != r["id"]:
                m["duplicate_canonical"] += 1; bad.append(f"duplicate_canonical_{l}")
            canon_seen[p["canonical"]] = r["id"]
            if "?" in p["canonical"] or "#" in p["canonical"] or "/page/" in p["canonical"]:
                m["faceted_or_query_urls"] += 1; bad.append(f"faceted_{l}")
            if (p["canonical"] in smap) != bool(p["index_ar"] if l == "ar" else p["index_en"]):
                m["sitemap_membership_mismatch"] += 1; bad.append(f"sitemap_membership_{l}")
        ok, det = hreflang_check(pages)
        modes[det["hreflang_mode"]] = modes.get(det["hreflang_mode"], 0) + 1
        if det["hreflang_mode"] == "bilingual":
            if ok:
                m["hreflang_complete"] += 1
            else:
                m["hreflang_incomplete"] += 1; bad.append("hreflang_incomplete")
                if not det["reciprocal"]:
                    m["reciprocity_failures"] += 1
                if any("x-default" not in t for t in det["tags"].values()):
                    m["missing_x_default"] += 1
        else:
            if det["no_alternate_tags"]:
                m["single_language_pages_without_alternates"] += 1
            else:
                m["single_language_pages_with_stray_alternates"] += 1
            if not ok:
                bad.append("single_language_rule")
        key = "bilingual" if det["hreflang_mode"] == "bilingual" else "single"
        if key not in examples:                       # دليلٌ من HTML المرسوم نفسه
            examples[key] = {"id": r["id"], "slug": r["slug"], "mode": det["hreflang_mode"], "eligibility": det["eligibility"],
                             "html": {l: _snip(p["text"], r'<link rel="(?:canonical|alternate)"[^>]*>') + _snip(p["text"], r'<html lang="[^"]+"') for l, p in pages.items()}}
        if bad:
            fails.append({"id": r["id"], "slug": r["slug"], "problems": bad})
    m["old_redirect_urls_in_sitemap"] = sum(1 for u in smap if u[len(SITE):].replace(seo_db.EN, "", 1) in redirect_paths)
    m["faceted_or_query_urls"] += sum(1 for u in smap if "?" in u or "#" in u or "/page/" in u)
    m["coverage_pct"] = round(100.0 * m["tested_population"] / len(pop), 2) if pop else 100.0
    complete = m["tested_population"] >= len(pop)
    m["hreflang_failures"] = m["hreflang_incomplete"] + m["single_language_pages_with_stray_alternates"]
    m["canonical_failures"] = m["canonical_self_failures"] + m["canonical_mismatch"]
    return {"eligibility_all_live": elig, "population": len(pop), "entities_checked": m["tested_population"], "pages_rendered": m["tested_population"] * 2, "by_mode": modes,
            "coverage_complete": complete, "metrics": m, "failures": fails[:20], "failures_total": len(fails), "sitemap_urls": len(smap), "examples": examples,
            "deterministic": "ordered by content.id; no sampling; same DB → same result",
            "rule": "hreflang set (ar, en, x-default=ar) reciprocal on both pages iff both languages are indexable; otherwise no alternate tags, canonical self, language switch link",
            "tests": [_t("global_hreflang_canonical_coverage", not fails and complete, {"population": len(pop), "checked": m["tested_population"], "coverage_pct": m["coverage_pct"], "failures": len(fails), "complete": complete, "by_mode": modes}),
                      _t("global_hreflang_bilingual_complete", m["hreflang_incomplete"] == 0 and m["missing_x_default"] == 0 and m["reciprocity_failures"] == 0 and complete,
                         {"bilingual_pairs": modes.get("bilingual", 0), "complete": m["hreflang_complete"], "incomplete": m["hreflang_incomplete"], "missing_x_default": m["missing_x_default"], "reciprocity_failures": m["reciprocity_failures"]}),
                      _t("global_single_language_rule", m["single_language_pages_with_stray_alternates"] == 0 and complete,
                         {"single_language_entities": modes.get("single:ar", 0) + modes.get("single:en", 0), "without_alternates": m["single_language_pages_without_alternates"], "stray": m["single_language_pages_with_stray_alternates"]}),
                      _t("global_canonical_integrity", m["canonical_failures"] == 0 and m["duplicate_canonical"] == 0 and m["language_mismatch"] == 0 and m["http_non_200"] == 0 and complete,
                         {"canonical_failures": m["canonical_failures"], "duplicate_canonical": m["duplicate_canonical"], "language_mismatch": m["language_mismatch"], "http_non_200": m["http_non_200"]}),
                      _t("global_sitemap_integrity", m["faceted_or_query_urls"] == 0 and m["old_redirect_urls_in_sitemap"] == 0 and m["sitemap_membership_mismatch"] == 0,
                         {"faceted_or_query": m["faceted_or_query_urls"], "old_redirect_urls": m["old_redirect_urls_in_sitemap"], "membership_mismatch": m["sitemap_membership_mismatch"]})]}


def check_work(data_dir, con, item, st, srv_names):
    """كل اختبارات العمل الواحد ← {id, …, tests: [...]}."""
    row = con.execute("SELECT * FROM content WHERE id=?", (item["id"],)).fetchone()
    tests = []
    live_same = [r["id"] for r in con.execute("SELECT id FROM content WHERE tmdb_id=? AND type=? AND merged_into IS NULL", (row["tmdb_id"], row["type"]))] if row["tmdb_id"] else [row["id"]]
    tests.append(_t("one_entity", row["merged_into"] is None and row["available"] == 1 and live_same == [row["id"]],
                    {"tmdb_id": row["tmdb_id"], "live_with_same_tmdb_id": live_same}))
    prov = con.execute("SELECT at, prev FROM provenance WHERE entity='content' AND entity_id=? AND field='slug' AND prev IS NOT NULL", (row["id"],)).fetchone()   # تبديلٌ فعلي لا إنشاء
    bundle_at = seo_db.state(con, "bundle_at") or 0
    stale = con.execute("SELECT 1 FROM redirect WHERE path=?", (seo_db.PATHS[row["type"]].format(slug=row["slug"]),)).fetchone()
    tests.append(_t("slug_stable", not stale and not (prov and prov["at"] > bundle_at),
                    {"slug": row["slug"], "slug_source": row["slug_source"], "changed_since_last_bundle": bool(prov and prov["at"] > bundle_at),
                     "previous": prov["prev"] if prov else None, "slug_is_old_redirect": bool(stale)}))
    pages = {}
    for lang in ("ar", "en"):
        pages[lang] = _page(data_dir, con, row, lang, st)
    ok_pages = all(p and p["code"] == 200 and p["text"].count("<h1") == 1 and p["title"] and p["desc"] for p in pages.values())
    tests.append(_t("ar_en_render", ok_pages, {l: (p["code"] if p else None) for l, p in pages.items()}))
    if not ok_pages:
        return {**item, "tests": tests}
    canon_ok = all(p["canonical"] == SITE + seo_pages._path(row, l) and f'rel="canonical" href="{p["canonical"]}"' in p["text"] for l, p in pages.items())
    tests.append(_t("canonical", canon_ok, {l: p["canonical"] for l, p in pages.items()}))
    h_ok, h_det = hreflang_check(pages)
    tests.append(_t("hreflang_reciprocal", h_ok, {"hreflang_mode": h_det["hreflang_mode"], **h_det}))   # الحالة أولًا فلا يبترها حدّ التفصيل
    item = {**item, "hreflang_mode": h_det["hreflang_mode"]}
    want = "Movie" if row["type"] == "movie" else "TVSeries"
    sch = []
    for l, p in pages.items():
        lds = _lds(p["text"])
        main = next((x for x in lds if isinstance(x, dict) and x.get("@type") == want), None)
        crumbs = any(isinstance(x, dict) and x.get("@type") == "BreadcrumbList" for x in lds)
        official = row["episodes_official"] or con.execute("SELECT SUM(episodes_official) FROM season WHERE content_id=?", (row["id"],)).fetchone()[0]
        counts_ok = row["type"] == "movie" or official or ("numberOfEpisodes" not in (main or {}))
        sch.append(bool(main) and crumbs and None not in lds and main.get("url") == p["canonical"] and counts_ok)
    tests.append(_t("schema", all(sch), {"type": want, "ar_en": sch}))
    rows = con.execute("SELECT service_key, COUNT(*) n FROM content_service WHERE content_id=? AND present=1 GROUP BY 1", (row["id"],)).fetchall()
    per_service = {r["service_key"]: r["n"] for r in rows}
    avail = {}
    for l, p in pages.items():
        m = SRV_RX.search(p["text"])
        items = re.findall(r"<li>.*?<b>(.*?)</b>", m.group(1), re.S) if m else []
        avail[l] = items
    expected = [srv_names[l][k] for l in ("ar", "en") for k in per_service if k in srv_names[l]]
    uniq = all(len(v) == len(set(v)) and len(v) == len([k for k in per_service if k in srv_names[l]]) for l, v in avail.items())
    tests.append(_t("availability_unique", uniq, {"rows_per_service": per_service, "shown": avail}))
    if per_service.get("falcon", 0) >= 2:
        f_ar, f_en = srv_names["ar"].get("falcon"), srv_names["en"].get("falcon")
        tests.append(_t("falcon_once", avail["ar"].count(f_ar) == 1 and avail["en"].count(f_en) == 1
                        and pages["ar"]["text"].count(f"اشتراكات {f_ar}") <= 1 and f"{f_ar}، {f_ar}" not in pages["ar"]["text"] and f"{f_en}, {f_en}" not in pages["en"]["text"],
                        {"falcon_rows": per_service["falcon"], "shown_ar": avail["ar"].count(f_ar), "shown_en": avail["en"].count(f_en)}))
    else:
        tests.append(_t("falcon_once", True, {"skipped": "falcon rows < 2", "falcon_rows": per_service.get("falcon", 0)}))
    dup = con.execute(
        "SELECT DISTINCT o.content_id, c.slug FROM content_service s JOIN content_service o ON o.service_key=s.service_key AND o.kind=s.kind AND o.content_id!=s.content_id AND o.present=1 "
        "AND o.stream_id IS NOT NULL AND o.stream_id=s.stream_id JOIN content c ON c.id=o.content_id AND c.merged_into IS NULL WHERE s.content_id=? AND s.present=1", (row["id"],)).fetchall()
    tests.append(_t("no_service_duplicate_urls", not dup, {"other_live_entities_sharing_a_stream": [dict(r) for r in dup]}))
    noindex = all('name="robots" content="noindex, follow"' in p["text"] and p["headers"].get("X-Robots-Tag") == "noindex" for p in pages.values())
    tests.append(_t("noindex", noindex, {l: p["headers"].get("X-Robots-Tag") for l, p in pages.items()}))
    return {**item, "title": row["title"], "tmdb_id": row["tmdb_id"], "match": row["match"], "would_index": {"ar": pages["ar"]["index_ar"], "en": pages["en"]["index_en"]},
            "why": {"ar": pages["ar"]["why"][0], "en": pages["en"]["why"][1]}, "urls": {l: p["canonical"] for l, p in pages.items()}, "tests": tests}


def check_redirects(data_dir, con, sample_ids, limit=200):
    """كل صفوف ‏redirect (العربية والإنجليزية معًا كما يسجّلها change_slug/merge): الهدف صفحةٌ حيّة (لا تحويلٌ آخر = سلسلة،
    ولا كيانٌ مدمج/غائب)، وكل صفٍّ عربيّ تخدمه الطبقة 301 مباشرةً إلى هدفه باللغتين (كلّ ما يخصّ أعمال العيّنة، وعيّنةٌ من
    الباقي)، وصفّ الإنجليزية يطابق صفّ العربية. لا يُنشئ تحويلًا."""
    rows = con.execute("SELECT path, target, code, reason, created_at FROM redirect ORDER BY created_at DESC").fetchall()
    targets = {r["path"]: r["target"] for r in rows}
    chains = [{"from": r["path"], "to": r["target"], "then": targets[r["target"]]} for r in rows if r["target"] in targets]
    live = set()
    for r in con.execute("SELECT type, slug FROM content WHERE merged_into IS NULL AND available=1"):
        live.update(seo_db.paths(r["type"], r["slug"]))
    bad_target = [{"from": r["path"], "to": r["target"]} for r in rows if r["target"] not in live and r["target"] not in targets]
    en_rows = [r for r in rows if r["path"].startswith(seo_db.EN + "/")]
    ar_rows = [r for r in rows if not r["path"].startswith(seo_db.EN + "/")]
    en_mismatch = [{"en": r["path"], "to": r["target"]} for r in en_rows
                   if targets.get(r["path"][len(seo_db.EN):]) != r["target"][len(seo_db.EN):] if r["target"].startswith(seo_db.EN + "/")]
    sample_paths = {p for t, s in con.execute(f"SELECT type, slug FROM content WHERE id IN ({','.join('?' * len(sample_ids)) or '0'})", sample_ids) for p in seo_db.paths(t, s)}
    todo = [r for r in ar_rows if r["target"] in sample_paths] + [r for r in ar_rows if r["target"] not in sample_paths][:limit]
    served, direct, fails = 0, 0, []
    for r in todo:
        for lang, pre in (("ar", ""), ("en", seo_db.EN)):
            code, _, hdr = seo_pages.handle(data_dir, pre + r["path"], lang) or (None, b"", {})
            served += 1
            if code == 301 and hdr.get("Location") == pre + r["target"] and (pre + r["target"]) in live:
                direct += 1
            else:
                fails.append({"path": pre + r["path"], "code": code, "location": hdr.get("Location"), "expected": pre + r["target"]})
    audit = audit_redirect_targets(data_dir, con) if bad_target else {"total_non_live": 0, "audited": 0, "audit_complete": True, "by_classification": {c: 0 for c in CLASSES}, "with_identity_alternative": 0, "route_404": 0, "items": []}
    unresolved = [it for it in audit["items"] if not it["resolved_to_final"]]        # 404 · مسارٌ مفقود · سلسلة · كيانٌ مفقود · مدمجٌ لا يصل إلى canonical النهائي
    unavailable = [it for it in audit["items"] if it["classification"] == "TARGET_UNAVAILABLE_BUT_CANONICAL"]
    canonical_live = [it for it in audit["items"] if it["route_status"] == 200 and it["canonical_self"] and not it["route_chain"]]
    n_before = len(rows)
    n_after = con.execute("SELECT COUNT(*) FROM redirect").fetchone()[0]
    return {"total": n_before, "ar_rows": len(ar_rows), "en_rows": len(en_rows), "chains": len(chains), "chain_examples": chains[:10],
            "targets_not_live": len(bad_target), "targets_not_live_examples": bad_target[:10], "targets_not_live_audit": audit, "en_rows_mismatching_ar": en_mismatch[:10],
            "served_checked": served, "served_direct": direct, "failures": fails[:20], "created_during_qa": n_after - n_before,
            "catalog_availability": {"targets_not_in_live_set": len(bad_target), "targets_available_false": len(unavailable), "distinct_entities_available_false": len({it["target_entity_id"] for it in unavailable}),
                                     "blocker": False, "note": "availability is a catalog state (available=0 = absent from all servers now), not a routing fault; detail in targets_not_live_audit"},
            "tests": [_t("redirect_chain_zero", not chains, {"chains": len(chains)}),
                      # يفشل فقط عند: 404 · مسارٌ مفقود · 301 إلى تحويلٍ آخر · كيانٌ مفقود · مدمجٌ لا يصل إلى canonical النهائي. 200 canonical = ناجح ولو available=0
                      _t("redirect_targets_resolve", not unresolved, {"unresolved": len(unresolved), "by_classification": {c: audit["by_classification"].get(c, 0) for c in CLASSES},
                                                                      "examples": [{"to": it["to"], "class": it["classification"], "route": it["route_status"]} for it in unresolved[:5]]}),
                      # كل هدفٍ خارج مجموعة «الحيّ» بتعريف القاعدة: المسار 200 والصفحة تعلن canonical نفسه وبلا سلسلة (أو 301 مباشر إلى canonical النهائي لمدمج)
                      _t("redirect_targets_canonical_live", all(it["resolved_to_final"] for it in audit["items"]),
                         {"checked": audit["audited"], "http_200_canonical_self": len(canonical_live), "direct_301_to_final": sum(1 for it in audit["items"] if it["route_status"] == 301 and it["resolved_to_final"]),
                          "failing": len(unresolved), "audit_complete": audit["audit_complete"]}),
                      # مقياسٌ لا blocker: كم هدفًا كيانه غائبٌ من السيرفرات الآن (available=0) مع بقائه canonical نفسه
                      _t("redirect_targets_catalog_availability", True, {"targets_available_false": len(unavailable), "distinct_entities": len({it["target_entity_id"] for it in unavailable}),
                                                                          "with_identity_alternative": audit["with_identity_alternative"], "metric_only": True}),
                      _t("redirect_en_rows_match_ar", not en_mismatch, {"mismatch": len(en_mismatch)}),
                      _t("redirect_served_direct", not fails and (served > 0 or not ar_rows), {"checked": served, "direct": direct, "failures": len(fails)}),
                      _t("no_new_redirects", n_after == n_before, {"before": n_before, "after": n_after})]}


def _final_entity(con, cid, hops=10):
    """يتبع merged_into حتى الكيان الحيّ ← (الصفّ النهائي، عدد القفزات)."""
    row = con.execute("SELECT id, type, slug, merged_into, available, tmdb_id, title, last_seen FROM content WHERE id=?", (cid,)).fetchone()
    n = 0
    while row and row["merged_into"] is not None and n < hops:
        row = con.execute("SELECT id, type, slug, merged_into, available, tmdb_id, title, last_seen FROM content WHERE id=?", (row["merged_into"],)).fetchone()
        n += 1
    return row, n


CLASSES = ("VALID_LIVE_TARGET", "TARGET_UNAVAILABLE_BUT_CANONICAL", "TARGET_MERGED", "TARGET_REDIRECT_CHAIN", "TARGET_ROUTE_MISSING", "TARGET_ENTITY_MISSING", "OTHER")


def audit_redirect_targets(data_dir, con, limit=None):
    """تدقيقٌ (قراءةٌ صرفة) لكل تحويلٍ هدفه ليس صفحةً حيّة — **كلها** لا عيّنة (audit_complete عندها فقط). لكل هدف: الكيان
    ومعرّفه وslug الحالي وحاله (متاح/مدمج/آخر رؤية)، وجواب المسار **من الخدمة نفسها** (200/301 بوجهته/404)، وcanonical الكيان،
    والكيان النهائي بتتبّع merged_into كاملًا (أو تاريخ slug إن اختفى الرابط)، والبدائل الحيّة بدليل هوية، والسبب والتوصية
    وتصنيفٌ واحد من CLASSES — بلا تنفيذ."""
    rows = con.execute("SELECT path, target, reason, created_at FROM redirect ORDER BY target, path").fetchall()
    targets = {r["path"]: r["target"] for r in rows}
    live = set()
    for r in con.execute("SELECT type, slug FROM content WHERE merged_into IS NULL AND available=1"):
        live.update(seo_db.paths(r["type"], r["slug"]))
    non_live = [r for r in rows if r["target"] not in live and r["target"] not in targets]
    out = []
    for r in non_live[:limit] if limit else non_live:
        en = r["target"].startswith(seo_db.EN + "/")
        lang = "en" if en else "ar"
        ar_target = r["target"][len(seo_db.EN):] if en else r["target"]
        m = re.match(r"^/content/(movies|series)/([a-z0-9-]+)/$", ar_target)
        typ, slug = ("movie" if m.group(1) == "movies" else "series", m.group(2)) if m else (None, None)
        trow = con.execute("SELECT id, type, slug, merged_into, available, tmdb_id, title, last_seen, match FROM content WHERE type=? AND slug=?", (typ, slug)).fetchone() if typ else None
        code, _, hdr = seo_pages.handle(data_dir, r["target"], lang) or (None, b"", {})
        loc = hdr.get("Location") if code == 301 else None
        chain = bool(loc and (loc[len(seo_db.EN):] if loc.startswith(seo_db.EN + "/") else loc) in targets)
        item = {"from": r["path"], "to": r["target"], "redirect_reason": r["reason"], "lang": lang,
                "target_entity_id": trow["id"] if trow else None, "target_current_slug": trow["slug"] if trow else None, "entity_exists": bool(trow),
                "available": bool(trow["available"]) if trow else None, "merged_into": trow["merged_into"] if trow else None,
                "last_seen": time.strftime("%Y-%m-%d %H:%M", time.gmtime(trow["last_seen"])) if trow and trow["last_seen"] else None,
                "tmdb_id": trow["tmdb_id"] if trow else None, "route_status": code, "route_redirect_target": loc, "route_chain": chain,
                "canonical_url": SITE + seo_pages._path(trow, lang) if trow else None,
                "final_canonical_entity_id": None, "final_canonical_url": None, "merge_path": [], "canonical_alternative": []}
        fin = None
        if trow:
            fin, path_ids = trow, [trow["id"]]
            while fin and fin["merged_into"] is not None and len(path_ids) < 12:
                fin = con.execute("SELECT id, type, slug, merged_into, available, tmdb_id, title, last_seen, match FROM content WHERE id=?", (fin["merged_into"],)).fetchone()
                if fin:
                    path_ids.append(fin["id"])
            item["merge_path"] = path_ids
            alt = []
            if trow["tmdb_id"]:
                alt += [{"id": a["id"], "slug": a["slug"], "evidence": "same tmdb id"} for a in con.execute(
                    "SELECT id, slug FROM content WHERE tmdb_id=? AND type=? AND merged_into IS NULL AND available=1 AND id!=?", (trow["tmdb_id"], trow["type"], trow["id"]))]
            alt += [{"id": a["id"], "slug": a["slug"], "evidence": "shares a stream id on the same service"} for a in con.execute(
                "SELECT DISTINCT c.id, c.slug FROM content_service s JOIN content_service o ON o.service_key=s.service_key AND o.kind=s.kind AND o.content_id!=s.content_id "
                "AND o.present=1 AND o.stream_id IS NOT NULL AND o.stream_id=s.stream_id JOIN content c ON c.id=o.content_id AND c.merged_into IS NULL AND c.available=1 WHERE s.content_id=?", (trow["id"],))]
            alt += [{"id": a["id"], "slug": a["slug"], "evidence": "same name only (no identity evidence)"} for a in con.execute(
                "SELECT DISTINCT c.id, c.slug FROM content_alias a JOIN content_alias b ON b.alias_norm=a.alias_norm AND b.content_id!=a.content_id "
                "JOIN content c ON c.id=b.content_id AND c.type=? AND c.merged_into IS NULL AND c.available=1 WHERE a.content_id=? LIMIT 5", (trow["type"], trow["id"]))
                    if a["id"] not in {x["id"] for x in alt}]
            item["canonical_alternative"] = alt[:5]
        else:
            prov = con.execute("SELECT entity_id FROM provenance WHERE entity='content' AND field='slug' AND prev=?", (json.dumps(slug),)).fetchone() if slug else None
            if prov:
                fin = con.execute("SELECT id, type, slug, merged_into, available, tmdb_id, title, last_seen, match FROM content WHERE id=?", (prov["entity_id"],)).fetchone()
                item["merge_path"] = [fin["id"]] if fin else []
                while fin and fin["merged_into"] is not None and len(item["merge_path"]) < 12:
                    fin = con.execute("SELECT id, type, slug, merged_into, available, tmdb_id, title, last_seen, match FROM content WHERE id=?", (fin["merged_into"],)).fetchone()
                    if fin:
                        item["merge_path"].append(fin["id"])
                item["slug_history"] = "provenance: previous slug of entity %s" % prov["entity_id"]
        if fin:
            item["final_canonical_entity_id"] = fin["id"]
            item["final_canonical_url"] = SITE + seo_pages._path(fin, lang)
            item["final_available"] = bool(fin["available"])
        item["canonical_self"] = False                 # الصفحة المخدومة تعلن canonical = رابط الهدف نفسه (من الرسم لا من القاعدة)
        if trow and code == 200:
            res = seo_pages.render_entity(con, data_dir, trow["type"], trow["slug"], P.lang_of(lang), seo_db.settings(con))
            item["canonical_self"] = bool(res and res[0] == "page" and res[1]["canonical"] == SITE + r["target"])
        item["resolved_to_final"] = bool(code == 200 and item["canonical_self"] and (not fin or fin["id"] == (trow["id"] if trow else None))) or bool(
            code == 301 and not chain and item["final_canonical_url"] and loc == item["final_canonical_url"][len(SITE):])
        strong = [a for a in item["canonical_alternative"] if a["evidence"] != "same name only (no identity evidence)"]
        if trow and trow["merged_into"] is not None:
            cls = "TARGET_MERGED"
            item["reason_non_live"] = "target entity is merged into %s (merge path %s); the route answers %s → %s" % (trow["merged_into"], item["merge_path"], code, loc)
            item["recommendation"] = ("update target → %s (final canonical) — and fix merge re-pointing in merge_content" % item["final_canonical_url"]) if fin and fin["merged_into"] is None else "fix route generation (merge path does not end at a live entity)"
        elif chain:
            cls = "TARGET_REDIRECT_CHAIN"
            item["reason_non_live"] = "the route answers 301 to %s which is itself a redirect path" % loc
            item["recommendation"] = "update target → %s (final canonical)" % (item["final_canonical_url"] or targets.get(loc))
        elif not trow and code == 404:
            cls = "TARGET_ENTITY_MISSING"
            item["reason_non_live"] = "no entity carries this slug" + (" (slug history leads to entity %s)" % fin["id"] if fin else " and no slug history leads to one")
            item["recommendation"] = ("update target → %s (after review)" % item["final_canonical_url"]) if fin else "investigate how this target was generated before touching the row (fix route generation)"
        elif trow and code == 404:
            cls = "TARGET_ROUTE_MISSING"
            item["reason_non_live"] = "entity exists but the route answers 404"
            item["recommendation"] = "fix route generation"
        elif trow and not trow["available"] and code == 200:
            cls = "TARGET_UNAVAILABLE_BUT_CANONICAL"
            item["reason_non_live"] = "entity exists and is its own canonical, but it is absent from all servers now (available=0): route live 200 (noindex, outside sitemap)"
            item["recommendation"] = ("keep as-is; review merge candidates by identity evidence first (%s) — the redirect then follows the merge, never re-pointed by hand" % ", ".join(f"{a['id']}:{a['slug']} [{a['evidence']}]" for a in strong)
                                      if strong else "keep as-is (canonical entity unchanged; becomes live again when a catalog lists it)")
        elif trow and trow["available"] and code == 200:
            cls = "VALID_LIVE_TARGET"
            item["reason_non_live"] = "none: live entity and route 200 (state changed since the live set was computed)"
            item["recommendation"] = "keep as-is"
        else:
            cls = "OTHER"
            item["reason_non_live"] = "entity_exists=%s available=%s route=%s" % (bool(trow), item["available"], code)
            item["recommendation"] = "investigate"
        item["classification"] = cls
        out.append(item)
    by_class = {c: sum(1 for it in out if it["classification"] == c) for c in CLASSES}
    ents = {it["target_entity_id"] for it in out if it["target_entity_id"] is not None}
    by_lang = {l: sum(1 for it in out if it["lang"] == l) for l in ("ar", "en")}
    pairs = sum(1 for it in out if it["lang"] == "ar" and any(o["lang"] == "en" and o["to"] == seo_db.EN + it["to"] for o in out))
    return {"total_non_live": len(non_live), "audited": len(out), "audit_complete": len(out) == len(non_live), "by_classification": by_class,
            "sum_by_classification": sum(by_class.values()), "distinct_target_entities": len(ents), "by_lang": by_lang, "ar_en_pairs": pairs,
            "with_identity_alternative": sum(1 for it in out if any(a["evidence"] != "same name only (no identity evidence)" for a in it["canonical_alternative"])),
            "route_404": sum(1 for it in out if it["route_status"] == 404), "redirect_rows_before": len(rows), "redirect_rows_after": con.execute("SELECT COUNT(*) FROM redirect").fetchone()[0],
            "items": out}


def sitemap_urls(con, st):
    """روابط الكيانات التي تستحق الفهرسة بسياسة ‏seo_settings (كما ستدخل خريطة المرحلة 3) ← [(loc, lang, id)]. الهبّات
    وصفحات الأشخاص خارجها الآن (قرارها مع المرحلة 3)."""
    out = []
    for r in con.execute("SELECT * FROM content WHERE merged_into IS NULL AND available=1 ORDER BY id"):
        for lang in ("ar", "en"):
            if seo_pages.indexable(r, lang, st)[0]:
                out.append((SITE + seo_pages._path(r, lang), lang, r["id"]))
    return out


def sitemap_xml(urls):
    today = time.strftime("%Y-%m-%d", time.gmtime())
    rows = [f"  <url>\n    <loc>{seo_pages._esc(u)}</loc>\n    <lastmod>{today}</lastmod>\n    <changefreq>weekly</changefreq>\n    <priority>0.7</priority>\n  </url>" for u, _, _ in urls]
    return '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "\n".join(rows) + "\n</urlset>\n"


def check_sitemap(data_dir, con, st, out_path=None):
    """خريطةٌ تجريبية في ملفٍ لا يُخدم ولا يُرسَل: كلّ loc رابطٌ canonical واحد لكيانٍ حيّ (لا استعلامات ولا تصفّح page/
    ولا تحويلات قديمة ولا كيانين على رابطٍ واحد)."""
    urls = sitemap_urls(con, st)
    locs = [u for u, _, _ in urls]
    dup_loc = {u for u in locs if locs.count(u) > 1}
    redirects = {r["path"] for r in con.execute("SELECT path FROM redirect")}
    faceted = [u for u in locs if "?" in u or "#" in u or "/page/" in u or "/genres/" in u or "/year/" in u]
    non_canon = [u for u in locs if not u.startswith(SITE + "/") or not u.endswith("/") or "//" in u[len(SITE) + 1:]]
    old = [u for u in locs if u[len(SITE):].replace(seo_db.EN, "", 1) in redirects]
    by_id = {}
    for u, lang, cid in urls:
        by_id.setdefault((cid, lang), []).append(u)
    multi = {k: v for k, v in by_id.items() if len(v) > 1}
    by_lang = {"ar": sum(1 for _, l, _ in urls if l == "ar"), "en": sum(1 for _, l, _ in urls if l == "en")}
    xml = sitemap_xml(urls)
    try:                                          # الخريطة العامة (الدليل وصفحات السيرفرات) تُبنى للمقارنة فقط: لا صفحة كيانٍ فيها
        import guide_pages
        public_xml = guide_pages.sitemap(C.sitemap(data_dir))
        public_xml = public_xml.decode("utf-8", "replace") if isinstance(public_xml, bytes) else str(public_xml)
    except Exception as ex:  # noqa: BLE001
        public_xml = f"error: {type(ex).__name__}: {ex}"
    leaked = [u for u in locs if u in public_xml]
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(xml)
    return {"urls": len(urls), "by_lang": by_lang, "entities": len({cid for _, _, cid in urls}), "bytes": len(xml), "file": out_path, "served": False, "submitted": False,
            "sample": locs[:10],
            "tests": [_t("sitemap_canonical_only", not non_canon, {"bad": non_canon[:5]}),
                      _t("sitemap_no_duplicate_urls", not dup_loc and not multi, {"dup": sorted(dup_loc)[:5], "entity_with_two_urls": len(multi)}),
                      _t("sitemap_no_faceted_or_query_urls", not faceted, {"bad": faceted[:5]}),
                      _t("sitemap_no_old_redirect_paths", not old, {"bad": old[:5]}),
                      _t("sitemap_not_served", not leaked and "/content/movies/" not in public_xml and "/content/series/" not in public_xml,
                         {"entity_urls_in_public_sitemap": len(leaked), "public_sitemap_ok": not str(public_xml).startswith("error"), "staging_file": out_path})]}


def indexnow_dry_run(data_dir, urls):
    """الحمولة كما سيرسلها ‏analytics.submit — بلا إرسال، وبلا توليد مفتاحٍ إن لم يكن."""
    ix = analytics.indexnow(data_dir, create=False)
    key = ix["key"]
    on_host = [u for u in dict.fromkeys(urls) if u.startswith(f"https://{HOST}/")]
    off = [u for u in urls if not u.startswith(f"https://{HOST}/")]
    key_path = f"/{key}.txt" if key else None
    key_served = bool(key) and analytics.indexnow_key_file(data_dir, key_path) == key
    payload = {"host": HOST, "key": "•••" if key else "", "keyLocation": f"https://{HOST}/{'•••' if key else ''}.txt", "urlList": on_host[:10000]}
    return {"sent": False, "endpoint": analytics.INDEXNOW_URL, "key_present": bool(key), "key_file_route_ok": key_served, "auto": ix["auto"], "confirmed": ix["confirmed"],
            "last_real_submission": ix["last"], "payload_preview": {**payload, "urlList": payload["urlList"][:5], "urlList_count": len(payload["urlList"])},
            "tests": [_t("indexnow_not_sent", True, "dry-run: no request made"),
                      _t("indexnow_urls_on_host", not off and len(on_host) <= 10000, {"off_host": off[:3], "count": len(on_host)}),
                      _t("indexnow_key_ready", key_served or not key, {"key_present": bool(key), "route_ok": key_served, "note": "" if key else "no key yet: generated on first real use (Phase 3)"})]}


def check_queue(con):
    """أخطاء الطابور: لا خطأ ‏rps جديدًا منذ اللقطة السابقة؛ القديم يبقى (لا تنظيف قسريّ)."""
    bundle_at = seo_db.state(con, "bundle_at") or 0
    old = con.execute("SELECT COUNT(*) FROM enrich_queue WHERE error LIKE '%rps%'").fetchone()[0]
    new = con.execute("SELECT COUNT(*) FROM enrich_queue WHERE error LIKE '%rps%' AND updated_at>? AND attempts>0 AND state='error'", (bundle_at,)).fetchone()[0]
    newest = con.execute("SELECT MAX(updated_at) FROM enrich_queue WHERE error LIKE '%rps%'").fetchone()[0]
    by = [dict(r) for r in con.execute("SELECT source, state, COUNT(*) n FROM enrich_queue WHERE error LIKE '%rps%' GROUP BY 1, 2")]
    return {"historical_rps_rows": old, "new_rps_errors_since_last_bundle": new, "newest_rps_row_at": newest, "by_source_state": by, "cleanup": "not forced (history kept)",
            "tests": [_t("no_new_rps_errors", new == 0, {"new": new, "historical": old})]}


def check_casper(con, probe):
    """كاسبر 503: provider_unavailable مؤقّت — لا شيء غاب بسببه ولا تغيّرت مطابقة."""
    rec = seo_db.state(con, "reconciliation") or {}
    present = con.execute("SELECT COUNT(*) FROM content_service WHERE service_key='casper' AND present=1").fetchone()[0]
    p = (probe or {}).get("casper") or {}
    errs = {k: v for k, v in p.items() if isinstance(v, dict) and v.get("error")}
    classes = {k: v.get("class") for k, v in errs.items()}
    return {"probe": {k: {"error": v.get("error"), "class": v.get("class"), "severity": v.get("severity")} for k, v in errs.items()} or "no error in this probe",
            "casper_rows_present": present, "last_build_went_unavailable": rec.get("went_unavailable"), "last_build_merged": rec.get("merged"),
            "tests": [_t("casper_503_is_provider_unavailable", all(c == "provider_unavailable" for c in classes.values()), classes),
                      _t("casper_503_marks_nothing_missing", present > 0 and (rec.get("went_unavailable") or 0) == 0, {"present": present, "went_unavailable": rec.get("went_unavailable")}),
                      _t("casper_503_changes_no_matching", (rec.get("merged") or 0) == 0 and (rec.get("split") or 0) <= 1, {"merged": rec.get("merged"), "split": rec.get("split")})]}


def check_freeze(con, st):
    """الكيانات المجمّدة (identity_freeze): حالها الآن، وأنه لم يحدث لها منذ اللقطة السابقة انقسامٌ ولا دمج ولا تبديل رابط ولا تحويلٌ
    جديد ولا كتابة TMDB — لقطةٌ ثابتة قابلة للتحقّق."""
    bundle_at = seo_db.state(con, "bundle_at") or 0
    rec = seo_db.state(con, "reconciliation") or {}
    items = []
    for fid in sorted(seo_sources.frozen_ids(st)):
        c = con.execute("SELECT id, type, slug, title, tmdb_id, match, merged_into, available, updated_at FROM content WHERE id=?", (fid,)).fetchone()
        if not c:
            items.append({"id": fid, "exists": False, "ok": False}); continue
        ext = [dict(r) for r in con.execute("SELECT source, external_id, verified FROM external_id WHERE entity='content' AND entity_id=?", (fid,))]
        paths_ = seo_db.paths(c["type"], c["slug"])
        red_total = con.execute(f"SELECT COUNT(*) FROM redirect WHERE target IN ({','.join('?' * len(paths_))})", paths_).fetchone()[0]
        red_new = con.execute(f"SELECT COUNT(*) FROM redirect WHERE target IN ({','.join('?' * len(paths_))}) AND created_at>?", (*paths_, bundle_at)).fetchone()[0]
        slug_prov = con.execute("SELECT at, prev FROM provenance WHERE entity='content' AND entity_id=? AND field='slug' AND prev IS NOT NULL", (fid,)).fetchone()   # تبديلٌ فعلي لا إنشاء
        tmdb_prov = con.execute("SELECT at FROM provenance WHERE entity='content' AND entity_id=? AND field='tmdb_id'", (fid,)).fetchone()
        merged_in = con.execute("SELECT COUNT(*) FROM content WHERE merged_into=? AND updated_at>?", (fid, bundle_at)).fetchone()[0]
        splits = con.execute("SELECT COUNT(*) FROM review WHERE kind='split_entity' AND created_at>? AND payload_json LIKE ?", (bundle_at, f'%"from": [{fid}]%')).fetchone()[0]
        members = con.execute("SELECT service_key, COUNT(*) n FROM content_service WHERE content_id=? AND present=1 GROUP BY 1", (fid,)).fetchall()
        it = {"id": fid, "exists": True, "title": c["title"], "entity_state": "merged" if c["merged_into"] is not None else "live" if c["available"] else "unavailable",
              "merged_into": c["merged_into"], "slug": c["slug"], "tmdb_id_on_content": c["tmdb_id"], "match": c["match"], "external_ids": ext,
              "members": {r["service_key"]: r["n"] for r in members}, "redirect_count_to_entity": red_total, "new_redirects_since_previous_snapshot": red_new,
              "slug_changed_since_previous_snapshot": bool(slug_prov and slug_prov["at"] > bundle_at), "tmdb_written_since_previous_snapshot": bool(tmdb_prov and tmdb_prov["at"] > bundle_at),
              "merged_into_it_since_previous_snapshot": merged_in, "split_reviews_since_previous_snapshot": splits,
              "kept_by_freeze_last_build": rec.get("kept_by_freeze"), "freeze_conflicts_last_build": [x for x in (rec.get("freeze_conflicts") or []) if fid in (x.get("frozen"), x.get("other"))]}
        it["ok"] = c["merged_into"] is None and red_new == 0 and not it["slug_changed_since_previous_snapshot"] and not it["tmdb_written_since_previous_snapshot"] and merged_in == 0 and splits == 0
        items.append(it)
    return {"frozen": [it["id"] for it in items], "items": items, "previous_snapshot_at": bundle_at,
            "tests": [_t("identity_freeze_respected", all(it["ok"] for it in items), {"frozen": len(items), "violations": [it["id"] for it in items if not it["ok"]]})] if items else []}


def release_blockers(cov, fz, cs):
    """عوائق الإصدار (لا فشل اختبارات): التغطية على كامل السكّان غير مثبتة، كياناتٌ مجمّدة قيد المراجعة، مزوّدٌ متعطّل."""
    out = []
    m = cov["metrics"]
    if m["tested_population"] < m["total_canonical_entities"]:
        out.append({"gate": "Global SEO Coverage", "status": "NOT PROVEN",
                    "detail": f"100% of current intended population ({m['tested_population']} entities / {m['tested_population'] * 2} routes) — not the {m['total_canonical_entities']} live canonical entities"})
    if fz["frozen"]:
        out.append({"gate": "Identity freeze (owner review)", "status": "FROZEN", "detail": f"entities {fz['frozen']} frozen: no merge/split/slug/redirect/TMDB until the owner decides"})
    probe = cs.get("probe") if isinstance(cs.get("probe"), dict) else {}
    if any(isinstance(v, dict) and v.get("class") == "provider_unavailable" for v in probe.values()):
        out.append({"gate": "Casper", "status": "provider_unavailable (temporary)", "detail": "503 from the panel; nothing marked missing/unmatched; no matching change"})
    return out


def run(data_dir, spec=None, probe=None, sitemap_out=None):
    con = seo_db.connect(data_dir, create=False)
    if con is None:
        return {"error": "لم تُبنَ القاعدة"}
    try:
        st = seo_db.settings(con)
        srv_names = {l: {s["key"]: P.lang_of(l).name(s) for s in C.servers(data_dir)} for l in ("ar", "en")}
        snap_before = [con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("content", "content_service", "redirect", "review", "enrich_queue", "content_alias")]
        items = pick(con, spec)
        works = [check_work(data_dir, con, it, st, srv_names) for it in items]
        red = check_redirects(data_dir, con, [w["id"] for w in works])
        sm = check_sitemap(data_dir, con, st, sitemap_out)
        ix = indexnow_dry_run(data_dir, [u for u, _, _ in sitemap_urls(con, st)])
        q = check_queue(con)
        cs = check_casper(con, probe)
        cov = coverage(data_dir, con, st)
        fz = check_freeze(con, st)
        snap_after = [con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("content", "content_service", "redirect", "review", "enrich_queue", "content_alias")]
        ro = _t("read_only", snap_before == snap_after, {"before": snap_before, "after": snap_after})
        all_tests = [t for w in works for t in w["tests"]] + red["tests"] + sm["tests"] + ix["tests"] + q["tests"] + cs["tests"] + cov["tests"] + fz["tests"] + [ro]
        rb = release_blockers(cov, fz, cs)
        fails = [t for t in all_tests if not t["ok"]]
        work_fail = [{"id": w["id"], "slug": w["slug"], "group": w["group"], "failed": [t["test"] for t in w["tests"] if not t["ok"]]} for w in works if any(not t["ok"] for t in w["tests"])]
        return {"ok": not fails, "summary": {"automated_qa": f"{len(all_tests) - len(fails)}/{len(all_tests)} PASS", "test_failures": len(fails), "release_blockers": len(rb),
                                            "phase_3": "BLOCKED" if rb or fails else "gates passed (owner decision required)"},
                "release_blockers": rb, "freeze": fz,
                "sample": {"n": len(works), "by_group": {g: sum(1 for w in works if w["group"] == g) for g in ("movie", "series", "turkish", "anime", "title")},
                                            "would_index_both": sum(1 for w in works if w.get("would_index", {}).get("ar") and w.get("would_index", {}).get("en"))},
                "tests": {"total": len(all_tests), "pass": len(all_tests) - len(fails), "fail": len(fails)},
                "blockers": [{"test": t["test"], "detail": t["detail"]} for t in fails if not t["test"].startswith(("slug_stable",))][:50],
                "hreflang": {"sample_by_mode": {m: sum(1 for w in works if w.get("hreflang_mode") == m) for m in ("bilingual", "single:ar", "single:en", "single:none")},
                             "sample_failures": sum(1 for w in works for t in w["tests"] if t["test"] == "hreflang_reciprocal" and not t["ok"]),
                             "rule": cov["rule"]},
                "failed_works": work_fail, "works": works, "redirects": red, "sitemap": sm, "indexnow": ix, "queue": q, "casper": cs, "coverage": cov, "read_only": ro,
                "not_done_by_design": ["no production indexing", "no sitemap deploy", "no IndexNow submission", "no mass enrichment", "no slug change", "no merge", "no source row deleted"]}
    finally:
        con.close()


def main(argv):
    data_dir = os.environ.get("XM_DATA") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    opt = {a.lstrip("-").split("=")[0]: (a.split("=", 1)[1] if "=" in a else True) for a in argv[1:] if a.startswith("--")}
    if opt.get("redirects"):                   # python seo_qa.py --redirects[=out.json]: تدقيق الأهداف غير الحية وحده (قراءةٌ صرفة)
        con = seo_db.connect(data_dir, create=False)
        try:
            rep = {"meta": seo_sources.meta(data_dir), "redirect_targets_audit": audit_redirect_targets(data_dir, con)}
        finally:
            con.close()
        text = json.dumps(rep, ensure_ascii=False, indent=1, default=str)
        if isinstance(opt["redirects"], str):
            with open(opt["redirects"], "w", encoding="utf-8") as f:
                f.write(text)
            print(opt["redirects"])
        else:
            print(text)
        return
    rep = run(data_dir, sitemap_out=str(opt["sitemap"]) if opt.get("sitemap") else None)
    print(json.dumps({"meta": seo_sources.meta(data_dir), **rep}, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv)

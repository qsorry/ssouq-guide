#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""طبقة الكيانات (‏seo_db · seo_match · seo_build): الفيلم أو المسلسل كيانٌ واحد مهما تعدّدت سيرفراته — بلا إنترنت.

  - المطابقة محافظة: الاسم وحده لا يدمج (‏name_only للمراجعة)، والسنة أو ملصق TMDB أو القصة تدمج، وسنتان
    مختلفتان فيلمان مختلفان بلا مراجعة، وقصّتان مختلفتان تعارضٌ يُراجَع، والاسم العربي يلتقي بالإنجليزي عبر الملصق.
  - البناء: من فهارس السيرفرات نفسها ولا يمسّها (بصمتها قبل وبعد)، تزايدي (لا يُعاد ما لم يتغيّر ملف)، ثابت
    (المعرّف وslug لا يتغيّران)، ما غاب يُعلَّم ولا يُحذف، الأقسام المخفية لا تدخل، القنوات لا تدخل، والحقل اليدوي لا
    يُكتب فوقه، ومصدر كل حقل مسجَّل، والمواسم والأسماء البديلة.
  - على خادم حيّ: ‏/api/content/seo و‏/review للمدير وحده، و«ابنِ الآن» من صفحة المدير، ولا مسار عام جديد.

تشغيل:  python tests/test_seo.py
"""
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["CONTENT_IMG_PRIVATE"] = "1"
import threading  # noqa: E402

import mock_tmdb  # noqa: E402
import mock_xtream  # noqa: E402
import content as C  # noqa: E402
import seo_pages  # noqa: E402
import seo_qa  # noqa: E402
import seo_search  # noqa: E402
import seo_sources  # noqa: E402
import seo_build  # noqa: E402
import seo_db  # noqa: E402
import seo_match as M  # noqa: E402

_p = _f = 0


def check(label, cond, extra=""):
    global _p, _f
    if cond:
        _p += 1
        print("  PASS  " + label + (("  (%s)" % extra) if extra else ""))
    else:
        _f += 1
        print("  FAIL  " + label + (("  (%s)" % extra) if extra else ""))


TMDB = "https://image.tmdb.org/t/p/w500/"
ST = dict(seo_db.DEFAULTS)


def it(typ, name, service, year=0, poster="", plot="", genres=(), seasons=None, **kw):
    return {"type": typ, "kind": typ, "name": name, "service": service, "local_key": C._ikey(typ, {"n": name, "y": year}),
            "year": year, "poster": poster, "backdrop": "", "plot": plot, "genres": list(genres), "rating": 0,
            "added": 0, "stream_id": 0, "seasons": seasons or {}, "groups": [], **kw}


def unit_match():
    print("== المطابقة ==")
    check("slug لاتيني", M.slugify("Wonder Woman (2017)") == "wonder-woman-2017" and M.slugify("Wonder Woman") == "wonder-woman")
    check("slug بلا علامات أوروبية", M.slugify("Amélie") == "amelie")
    check("slug لاتيني دائمًا: العربي يُنقحر بلا تشكيل", M.slugify("المؤسّس عثمان") == "almwss-athman", M.slugify("المؤسّس عثمان"))
    check("slug بأرقام هندية", M.slugify("ولاد رزق ٣") == "wlad-rzq-3")
    check("أولوية الاسم: الإنجليزي ثم الأصلي ثم النقحرة",
          M.slug_source({"title": "بريكنغ باد", "title_en": "Breaking Bad", "original_title": "Breaking Bad"}) == ("Breaking Bad", "en")
          and M.slug_source({"title": "بريكنغ باد", "original_title": "Breaking Bad"}) == ("Breaking Bad", "original")
          and M.slug_source({"title": "باب الحارة"}) == ("باب الحارة", "translit"))
    taken = {"dune"}
    check("الفريد: الاسم ثم الاسم-السنة ثم -2", M.unique_slug(taken.__contains__, "Dune", 2021) == "dune-2021"
          and M.unique_slug({"dune", "dune-2021"}.__contains__, "Dune", 2021) == "dune-2021-2")
    a, b = it("movie", "Dune", "casper", 2021), it("movie", "Dune", "falcon", 1984)
    check("سنتان مختلفتان: مختلفان يقينًا", M.pair_score(a, b, ST)[0] == M.DISTINCT)
    a, b = it("movie", "Dune", "casper", 2021), it("movie", "Dune", "falcon", 2021)
    check("نفس السنة تدمج", M.pair_score(a, b, ST)[0] >= ST["merge_min"])
    a, b = it("series", "The Office", "casper"), it("series", "The Office", "falcon")
    s, why = M.pair_score(a, b, ST)
    check("الاسم وحده لا يدمج", s is not None and s < ST["merge_min"] and not why)
    a, b = it("series", "Breaking Bad", "casper", poster=TMDB + "bb.jpg"), it("series", "بريكنغ باد", "falcon", poster=TMDB + "bb.jpg")
    check("ملصق TMDB واحد يدمج ولو اختلف الاسم", M.pair_score(a, b, ST)[0] >= ST["merge_min"])
    a, b = it("series", "X", "casper", poster="http://p1/1.png"), it("series", "X", "falcon", poster="http://p2/1.png")
    check("صور اللوحات لا تُقارن", "poster" not in M.pair_score(a, b, ST)[1])
    p1 = "A chemistry teacher turns to making meth with a former student to secure his family"
    a, b = it("series", "X", "casper", plot=p1), it("series", "X", "falcon", plot=p1 + " after a cancer diagnosis")
    check("قصّة واحدة تدمج", M.pair_score(a, b, ST)[0] >= ST["merge_min"])
    a, b = it("series", "X", "casper", plot=p1), it("series", "X", "falcon", plot="Mockumentary about office workers in a paper company in Scranton Pennsylvania")
    check("قصّتان مختلفتان: تعارضٌ يُراجَع", M.pair_score(a, b, ST)[0] is None)
    a, b = it("movie", "Dune", "casper", 2021, poster=TMDB + "d.jpg"), it("movie", "Dune", "falcon", 1984, poster=TMDB + "d.jpg")
    check("سنتان مختلفتان بملصقٍ واحد: تعارض (خطأ سنة)", M.pair_score(a, b, ST)[0] is None)
    a, b = it("movie", "X", "casper", genres=["Action"]), it("movie", "X", "falcon", genres=["action", "Drama"])
    check("التصنيف قرينة لا تكفي وحدها", 0 < M.pair_score(a, b, ST)[0] < ST["merge_min"])
    items = [it("series", "Breaking Bad", "casper", poster=TMDB + "bb.jpg", plot=p1), it("series", "بريكنغ باد", "falcon", poster=TMDB + "bb.jpg"),
             it("series", "Breaking Bad", "smart", 2008, plot=p1), it("series", "The Office", "casper"), it("series", "The Office", "falcon"),
             it("movie", "Dune", "casper", 2021), it("movie", "Dune", "falcon", 1984), it("movie", "Dune", "smart", 2021)]
    clusters, reviews = M.cluster(items, ST)
    sizes = sorted(len(c) for c in clusters)
    check("التجميع: بريكنغ باد واحدٌ في ثلاثة (الملصق ثم الاسم)، Dune 2021 في اثنين، Dune 1984 وحده، The Office اثنان",
          sizes == [1, 1, 1, 2, 3], str(sizes))
    check("مراجعةٌ واحدة: The Office بالاسم وحده", [r["kind"] for r in reviews] == ["name_only"] and reviews[0]["name"] == "The Office")
    a, b, c = it("series", "Y", "casper", plot=p1), it("series", "Y", "falcon", 2009), it("series", "Y", "smart", 2009, plot=p1)
    clusters, reviews = M.cluster([a, b, c], ST)
    check("يلتقيان عبر ثالث: عنقودٌ واحد بلا مراجعة", len(clusters) == 1 and not reviews)


def _cat(movies, series, live=(), series2=()):
    return {"v": 2, "at": time.time(),
            "movie": [{"id": "m1", "name": "Movies", "items": movies}, {"id": "m2", "name": "Kids", "items": []}],
            "series": [{"id": "s1", "name": "Series", "items": series}, {"id": "s2", "name": "Netflix", "items": list(series2)}],
            "live": [{"id": "l1", "name": "Live", "items": list(live)}]}


def _write(d, key, cat):
    p = os.path.join(d, "content", key + ".json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(cat, f, ensure_ascii=False)
    os.utime(p, (time.time() + 2, time.time() + 2))    # بصمةٌ جديدة ولو كُتب في الثانية نفسها


def _hash(d):
    out = {}
    for n in sorted(os.listdir(os.path.join(d, "content"))):
        if n.endswith(".json"):
            with open(os.path.join(d, "content", n), "rb") as f:
                out[n] = hashlib.sha1(f.read()).hexdigest()
    return out


def _dataset(d):
    os.makedirs(os.path.join(d, "content"), exist_ok=True)
    with open(os.path.join(d, "content", "settings.json"), "w", encoding="utf-8") as f:
        json.dump({"servers": [{"key": "casper", "name": "كاسبر", "hidden": ["m2"]}, {"key": "falcon", "name": "فالكون"},
                               {"key": "smart", "name": "سمارت"}]}, f, ensure_ascii=False)
    plot = "A chemistry teacher turns to making meth with a former student to secure his family"
    _write(d, "casper", _cat(
        [{"n": "Wonder Woman", "y": 2017, "p": TMDB + "ww.jpg", "r": 7.2, "i": 10, "a": 100, "g": ["Action"]},
         {"n": "Dune", "y": 2021, "p": TMDB + "d.jpg", "d": "Paul Atreides travels to Arrakis the desert planet", "i": 11}],
        [{"n": "Breaking Bad", "p": TMDB + "bb.jpg", "s": [[1, 7], [2, 13]], "d": plot, "i": 20, "r": 9.4},
         {"n": "The Office", "s": [[1, 6]], "i": 21},
         {"n": "Shameless", "y": 2011, "s": [[1, 12]], "i": 22}],
        [{"n": "MBC 1", "i": 99}]))
    with open(os.path.join(d, "content", "casper.json"), encoding="utf-8") as f:
        cat = json.load(f)
    cat["movie"][1]["items"] = [{"n": "Hidden Kids Movie", "y": 2020, "i": 12}]      # قسمٌ أخفاه المدير
    _write(d, "casper", cat)
    _write(d, "falcon", _cat(
        [{"n": "Wonder Woman", "y": 2017, "p": "http://panel/1.png", "r": 6.9, "i": 30, "a": 200, "g": ["Adventure", "Action"]},
         {"n": "Dune", "y": 1984, "p": TMDB + "d84.jpg", "i": 31}],
        [{"n": "بريكنغ باد", "p": TMDB + "bb.jpg", "s": [[1, 7], [2, 13], [3, 13]], "i": 40},
         {"n": "The Office", "s": [[1, 14]], "d": "Mockumentary on a group of office workers in Scranton", "i": 41},
         {"n": "Shameless", "y": 2004, "s": [[1, 7]], "i": 42}]))
    _write(d, "smart", _cat(
        [{"n": "Wonder Woman", "p": TMDB + "ww.jpg", "i": 50}],
        [{"n": "Breaking Bad", "y": 2008, "s": [[1, 7]], "d": plot, "i": 60}]))


def unit_build():
    print("== البناء ==")
    d = tempfile.mkdtemp(prefix="seo_")
    try:
        _dataset(d)
        before = _hash(d)
        res = seo_build.build(d)
        check("يبني من ثلاثة سيرفرات", res and res["services"] == ["casper", "falcon", "smart"] and res["items"] == 12, str(res))
        check("فهارس السيرفرات لم تُمسّ", _hash(d) == before)
        s = seo_build.stats(d)
        e = s["entities"]
        check("8 كيانات: 3 أفلام (Wonder Woman، Dune 2021، Dune 1984) و5 مسلسلات", e["total"] == 8 and e["movie"] == 3 and e["series"] == 5, str(e))
        check("Wonder Woman في ثلاثة سيرفرات (السنة، ثم الملصق لمن بلا سنة)", s["by_services"]["movie"].get("3") == 1, str(s["by_services"]))
        check("بريكنغ باد واحدٌ في ثلاثة: الملصق جمع العربي بالإنجليزي، والقصة جمعت سمارت", s["by_services"]["series"].get("3") == 1)
        check("القنوات لا تدخل، والقسم المخفي لا يدخل", s["links"] == 12 and e["total"] == 8)
        rv = seo_build.reviews(d)
        check("للمراجعة: The Office بالاسم وحده فقط (Dune وShameless بسنتين: مختلفان بلا مراجعة)",
              [r["kind"] for r in rv] == ["name_only"] and rv[0]["name"] == "The Office", json.dumps(rv, ensure_ascii=False)[:200])
        con = seo_db.connect(d)
        bb = con.execute("SELECT * FROM content WHERE slug='breaking-bad'").fetchone()
        check("الكيان: الاسم الأكثر تكرارًا، والسنة من سمارت، والتقييم الأعلى، والقصة", bb and bb["year"] == 2008 and bb["rating"] == 9.4
              and bb["overview"].startswith("A chemistry") and bb["confidence"] == 3)
        pv = seo_db.provenance(con, "content", bb["id"])
        check("مصدر كل حقل مسجَّل: السنة من سمارت (m3u)، التقييم من كاسبر (xtream)، المواسم محسوبة",
              pv["year"][:2] == ("m3u", "smart") and pv["rating"][:2] == ("xtream", "casper") and pv["seasons"][0] == "derived", str(pv))
        seasons = {r["number"]: r["episode_count"] for r in con.execute("SELECT number, episode_count FROM season WHERE content_id=?", (bb["id"],))}
        check("المواسم أكبر ما رُئي في كل سيرفر", seasons == {1: 7, 2: 13, 3: 13}, str(seasons))
        al = {r["alias"] for r in con.execute("SELECT alias FROM content_alias WHERE content_id=?", (bb["id"],))}
        check("الأسماء البديلة: الإنجليزي والعربي", al == {"Breaking Bad", "بريكنغ باد"}, str(al))
        ww = con.execute("SELECT poster, year FROM content WHERE slug='wonder-woman'").fetchone()
        check("الملصق المفضَّل من TMDB لا من اللوحة", ww["poster"].startswith(TMDB) and ww["year"] == 2017)
        slugs = {r["slug"] for r in con.execute("SELECT slug FROM content")}
        check("slug فريد: dune وdune-1984 وبالعربي", {"dune", "dune-1984", "the-office", "the-office-2"} <= slugs, str(slugs))
        ids = {r["slug"]: r["id"] for r in con.execute("SELECT id, slug FROM content")}
        con.close()

        check("تزايدي: لا يُعاد البناء ما لم يتغيّر شيء", seo_build.build(d) is None)
        res = seo_build.build(d, force=True)
        con = seo_db.connect(d)
        check("إعادة البناء بالقوة: لا جديد ولا مدمج، والمعرّفات وslug كما هي", res["new"] == 0 and res["merged"] == 0
              and {r["slug"]: r["id"] for r in con.execute("SELECT id, slug FROM content")} == ids)
        # المدير يغلب: عنوانٌ يدوي لا يكتب البناء فوقه
        con.execute("UPDATE content SET title='بريكنج باد' WHERE id=?", (ids["breaking-bad"],))
        seo_db.set_provenance(con, "content", ids["breaking-bad"], "title", "manual")
        con.commit(); con.close()
        seo_build.build(d, force=True)
        con = seo_db.connect(d)
        check("الحقل اليدوي يبقى بعد البناء", con.execute("SELECT title FROM content WHERE id=?", (ids["breaking-bad"],)).fetchone()[0] == "بريكنج باد")
        con.close()
        # يغيب فيلمٌ من سمارت ويصل مسلسلٌ جديد: يُعلَّم الغائب ولا يُحذف، ويُبنى لتغيّر الملف
        plot = "A chemistry teacher turns to making meth with a former student to secure his family"
        _write(d, "smart", _cat([], [{"n": "Breaking Bad", "y": 2008, "s": [[1, 7]], "d": plot, "i": 60}, {"n": "Shōgun", "y": 2024, "s": [[1, 10]], "i": 61}]))
        res = seo_build.build(d)
        con = seo_db.connect(d)
        ww = con.execute("SELECT confidence FROM content WHERE slug='wonder-woman'").fetchone()
        link = con.execute("SELECT present FROM content_service WHERE service_key='smart' AND kind='movie'").fetchone()
        check("ما غاب من سيرفرٍ: رابطه present=0 (لا يُحذف) والكيان باقٍ بسيرفريه", res["new"] == 1 and link["present"] == 0 and ww["confidence"] == 2)
        check("الجديد كيانٌ جديد بـ slug", con.execute("SELECT slug FROM content WHERE title='Shōgun'").fetchone()[0] == "shogun")
        # تغيّرت قرائن عضوٍ (ضاعت قصّته) فلم يعد يلتقي بكيانه: ينفصل كيانًا جديدًا ويُسجَّل (لا يُدمج بالاسم وحده)
        _write(d, "smart", _cat([], [{"n": "Breaking Bad", "y": 2008, "s": [[1, 7]], "i": 60}, {"n": "Shōgun", "y": 2024, "s": [[1, 10]], "i": 61}]))
        res = seo_build.build(d)
        con.close(); con = seo_db.connect(d)
        check("فقدان القرينة يفصل العضو كيانًا جديدًا مسجَّلًا للمراجعة", res["split"] == 1 and res["new"] == 1
              and con.execute("SELECT COUNT(*) FROM review WHERE kind='split_entity' AND status='open'").fetchone()[0] == 1
              and con.execute("SELECT COUNT(*) FROM content WHERE slug LIKE 'breaking-bad%' AND merged_into IS NULL").fetchone()[0] == 2)
        _write(d, "smart", _cat([], [{"n": "Breaking Bad", "y": 2008, "s": [[1, 7]], "d": plot, "i": 60}, {"n": "Shōgun", "y": 2024, "s": [[1, 10]], "i": 61}]))
        seo_build.build(d)
        con.close(); con = seo_db.connect(d)
        check("وبعودتها يعود إلى كيانه الأصلي والمنفصل يُعلَّم مدمجًا فيه", res and
              con.execute("SELECT COUNT(*) FROM content WHERE slug LIKE 'breaking-bad%' AND merged_into IS NOT NULL").fetchone()[0] == 1
              and con.execute("SELECT status FROM review WHERE kind='split_entity'").fetchone()[0] == "stale")
        # يغيب كيانٌ من كل السيرفرات: available=0 لا حذف
        for k in ("casper", "falcon"):
            with open(os.path.join(d, "content", k + ".json"), encoding="utf-8") as f:
                cat = json.load(f)
            cat["series"][0]["items"] = [x for x in cat["series"][0]["items"] if x["n"] != "Shameless"]
            _write(d, k, cat)
        seo_build.build(d)
        con.close(); con = seo_db.connect(d)
        sh = con.execute("SELECT COUNT(*), SUM(available) FROM content WHERE title='Shameless'").fetchone()
        check("ما غاب من كل السيرفرات يبقى بمعرّفه وavailable=0", sh[0] == 2 and sh[1] == 0, str(tuple(sh)))
        # تدقيق التحويلات غير الحية (قراءةٌ صرفة): هدفٌ لكيانٍ غاب (الصفحة 200 noindex، الكيان يبقى canonical ← يُبقى كما هو)،
        # وهدفٌ لا كيان له (404 ← يُحقَّق في توليده) — ولا يُكتب شيء
        shr = con.execute("SELECT id, type, slug FROM content WHERE title='Shameless' AND merged_into IS NULL ORDER BY id").fetchone()
        con.execute("INSERT INTO redirect(path, target, code, reason, created_at) VALUES ('/content/series/shameless-old/', ?, 301, 'test', 1)", (seo_db.PATHS["series"].format(slug=shr["slug"]),))
        con.execute("INSERT INTO redirect(path, target, code, reason, created_at) VALUES ('/content/series/ghost-old/', '/content/series/ghost-none/', 301, 'test', 1)")
        seo_db.set_setting(con, "preview", True); con.commit()
        n_red = con.execute("SELECT COUNT(*) FROM redirect").fetchone()[0]
        au = seo_qa.audit_redirect_targets(d, con)
        by = {it["to"]: it for it in au["items"]}
        g = by.get("/content/series/ghost-none/"); u = by.get(seo_db.PATHS["series"].format(slug=shr["slug"]))
        check("تدقيق الأهداف غير الحية: الغائب = كيانٌ موجود بمعرّفه، 200، غير مدمج، available=0، التوصية keep as-is؛ والمفقود = لا كيان، 404، fix route generation؛ وبلا كتابة",
              au["count"] == 2 and au["by_state"] == {"unavailable": 1, "missing": 1} and u and u["target_entity_exists"] and u["target_entity_id"] == shr["id"] and u["route"]["code"] == 200
              and u["unavailable"] and not u["merged"] and u["recommendation"].startswith("keep as-is") and g and not g["target_entity_exists"] and g["route"]["code"] == 404
              and g["recommendation"].startswith("fix route generation") and con.execute("SELECT COUNT(*) FROM redirect").fetchone()[0] == n_red, str(au)[:600])
        con.execute("DELETE FROM redirect WHERE reason='test'"); seo_db.set_setting(con, "preview", False); con.commit()
        check("بند المراجعة يبقى ثابتًا بين البناءات (لا يتكرّر)",
              con.execute("SELECT COUNT(*) FROM review WHERE kind='name_only' AND status='open'").fetchone()[0] == 1)
        # الإعدادات تُعدَّل بلا كود
        seo_db.set_setting(con, "merge_min", 0)
        con.close()
        seo_build.build(d, force=True)
        con = seo_db.connect(d)
        check("بعتبة 0 يُدمج The Office ويُسجَّل الدمج للمراجعة، ويبقى الكيان المدمج بمعرّفه",
              con.execute("SELECT COUNT(*) FROM content WHERE slug LIKE 'the-office%' AND merged_into IS NOT NULL").fetchone()[0] == 1
              and con.execute("SELECT COUNT(*) FROM review WHERE key LIKE 'merged:%' AND status='open'").fetchone()[0] == 2
              and con.execute("SELECT status FROM review WHERE kind='name_only'").fetchone()[0] == "stale")
        try:
            seo_db.set_setting(con, "nope", 1); bad = False
        except ValueError:
            bad = True
        check("إعدادٌ غير معروف يُرفض", bad)
        con.close()
        rep = seo_build.report(d)
        check("التقرير نصٌّ بالأعداد", "الكيانات الموحّدة" in rep and "تحتاج مراجعة" in rep)
        # سيرفرٌ بفهرسٍ من النسخة الأولى
        _write(d, "falcon", {"v": 1, "movie": [{"id": "m1", "name": "Movies", "items": ["Old Movie (2001) FHD", "Old Movie (2001) HD"]}],
                             "series": [{"id": "s1", "name": "S", "items": [["Old Show (2003)", [[1, 5]]]]}], "live": []})
        res = seo_build.build(d)
        con = seo_db.connect(d)
        om = con.execute("SELECT slug, year FROM content WHERE title='Old Movie'").fetchone()
        check("فهرس النسخة الأولى يُقرأ بسنته وجودته مفصولتين", om and om["year"] == 2001 and om["slug"] == "old-movie")
        con.close()
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ================= على خادمٍ حيّ =================
PORT = 9593
ADMIN_PW = "envpass123"
AUTH = "Basic " + base64.b64encode(f"admin:{ADMIN_PW}".encode()).decode()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def req(base, path, data=None, auth=None, host=None):
    """بلا اتّباع التحويلات: 301 يُرى كما هو."""
    r = urllib.request.Request(base + path, data=json.dumps(data).encode() if data is not None else None,
                               headers={**({"Authorization": auth} if auth else {}), **({"Host": host} if host else {}),
                                        **({"Content-Type": "application/json"} if data is not None else {})})
    try:
        with _opener.open(r, timeout=20) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def live():
    print("== على خادم حيّ ==")
    d = tempfile.mkdtemp(prefix="seo_live_")
    _dataset(d)
    env = dict(os.environ, XM_DATA=d, XM_BIND="127.0.0.1", XM_PORT=str(PORT), XM_ADMIN_PASSWORD=ADMIN_PW)
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "xm_lines.py"), "web"], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{PORT}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(base + "/robots.txt", timeout=2); break
            except Exception:  # noqa: BLE001
                time.sleep(0.15)
        c, b = req(base, "/admin/api/content/seo")
        check("الأعداد للمدير وحده (بلا دخول: 401)", c == 401, str(c))
        c, b = req(base, "/admin/api/content/seo", auth=AUTH)
        j = json.loads(b)
        check("قبل البناء: built=false", c == 200 and j["ok"] and not j["built"], b[:120])
        c, b = req(base, "/admin/api/content/admin/seo-build", {"force": True}, auth=AUTH)
        check("«ابنِ الآن» يبدأ في الخلفية", c == 200 and json.loads(b)["started"])
        for _ in range(100):
            j = json.loads(req(base, "/admin/api/content/seo", auth=AUTH)[1])
            if j.get("built") and not j.get("running"):
                break
            time.sleep(0.1)
        check("بعد البناء: 8 كيانات و3 سيرفرات", j.get("built") and j["entities"]["total"] == 8 and j["services"] == ["casper", "falcon", "smart"], b[:200])
        c, b = req(base, "/admin/api/content/seo/review?kind=name_only", auth=AUTH)
        check("قائمة المراجعة", c == 200 and [r["name"] for r in json.loads(b)["reviews"]] == ["The Office"], b[:200])
        c, b = req(base, "/admin/content", auth=AUTH)
        check("صفحة المدير فيها بطاقة الطبقة", c == 200 and 'id="seo"' in b and "eBuild" in b)
        c, b = req(base, "/api/content/seo", host="guide.ssouq.com")
        check("لا مسار عام جديد", c == 404, str(c))
        c, b = req(base, "/content/series/breaking-bad/", host="guide.ssouq.com")
        check("مسارات الطبقة 404 على الموقع العام ما دامت المعاينة موقوفة", c == 404, str(c))
        c, b = req(base, "/admin/api/content/admin/seo-settings", {"settings": {"preview": True}}, auth=AUTH)
        c2, b2 = req(base, "/content/series/breaking-bad/", host="guide.ssouq.com")
        check("بتفعيل المعاينة: الصفحة 200 وnoindex", c == 200 and c2 == 200 and 'content="noindex, follow"' in b2, f"{c} {c2}")
        c, b = req(base, "/ar/content/series/breaking-bad/", host="guide.ssouq.com")
        check("‏/ar/content/… يحوّل 301 إلى /content/…", c == 301, str(c))
        c, b = req(base, "/content/casper", host="guide.ssouq.com")
        check("صفحة السيرفر لم تتأثر", c == 200 and 'rel="canonical" href="https://guide.ssouq.com/content/casper"' in b)
        c, b = req(base, "/admin/api/content/admin/seo-audit", {"n": 5}, auth=AUTH)
        check("فحص العيّنة من الإدارة", c == 200 and json.loads(b)["audit"]["pages"] >= 2, b[:120])
        c, b = req(base, "/admin/api/content/seo/search?q=person%20break", auth=AUTH)
        check("تجربة البحث من الإدارة", c == 200 and json.loads(b)["result"] in ("suggest", "entity", "none"))
        c, b = req(base, "/admin/api/content/seo/enrich", auth=AUTH)
        check("حال الإثراء من الإدارة (بلا مفتاح)", c == 200 and json.loads(b)["has_key"] is False and "window" in json.loads(b))
        c, b = req(base, "/admin/api/content/admin/seo-bundle", {"n": 2}, auth=AUTH)
        check("«أنتج ملفات المراجعة» يبدأ في الخلفية", c == 200 and json.loads(b)["started"] is True, b[:120])
        for _ in range(200):
            j = json.loads(req(base, "/admin/api/content/seo/bundle", auth=AUTH)[1])
            if not j["running"]:
                break
            time.sleep(0.2)
        check("الملفات الأربعة مكتوبة في data/content/seo-review (بلا مفتاح: العيّنة تُسجَّل skipped لا فشلًا)",
              not j["running"] and {f["name"] for f in j["files"]} == set(seo_sources.BUNDLE_FILES + seo_sources.BUNDLE_EXTRA) and j["last"].get("ok") is True, b[:160])
        c, b = req(base, "/admin/api/content/seo/bundle/sitemap-staging.xml", auth=AUTH)
        check("خريطة الموقع التجريبية تُنزَّل من البطاقة (XML) ولا تُخدم على الموقع", c == 200 and b.startswith("<?xml") and "<urlset" in b, b[:120])
        c, b = req(base, "/admin/api/content/seo/bundle/qa.json", auth=AUTH)
        check("qa.json بختمه وملخّص اختباراته", c == 200 and '"generated_at"' in b and '"tests"' in b and '"indexnow"' in b, b[:160])
        c, b = req(base, "/admin/api/content/seo/bundle/sample.json", auth=AUTH)
        check("تنزيل sample.json للمدير بختمه", c == 200 and '"generated_at"' in b and '"works"' in b)
        c, _ = req(base, "/admin/api/content/seo/bundle/sample.json")
        c2, _ = req(base, "/admin/api/content/seo/bundle/../settings.json", auth=AUTH)
        c3, _ = req(base, "/api/content/seo/bundle/sample.json", host="guide.ssouq.com")
        check("بلا دخول 401، واسمٌ خارج القائمة 404، ولا مسار عام", c == 401 and c2 == 404 and c3 == 404, f"{c} {c2} {c3}")
        c, b = req(base, "/content/casper", host="guide.ssouq.com")
        check("صفحة السيرفر العامة كما هي (مفهرسة بـ canonical)", c == 200 and 'rel="canonical" href="https://guide.ssouq.com/content/casper"' in b, str(c))
        check("القاعدة في data/content/seo.sqlite", os.path.exists(os.path.join(d, "content", "seo.sqlite")))
    finally:
        p.terminate(); p.wait(timeout=10)
        shutil.rmtree(d, ignore_errors=True)


def unit_ten():
    """الحالات العشر التي طلبها المالك قبل المرحلة الثانية — كلٌّ باسمها."""
    print("== الحالات العشر ==")
    d = tempfile.mkdtemp(prefix="seo_ten_")
    try:
        _dataset(d)
        plot = "A chemistry teacher turns to making meth with a former student to secure his family"
        with open(os.path.join(d, "content", "casper.json"), encoding="utf-8") as f:
            cat = json.load(f)
        # داخل السيرفر الواحد: نفس الاسم في قسمين
        cat["series"][0]["items"] += [{"n": "Fargo", "p": "http://panel/fargo.png", "s": [[1, 10]], "i": 70},
                                      {"n": "Lupin", "p": "http://panel/lupin1.png", "s": [[1, 5]], "i": 72},
                                      {"n": "Shameless", "y": 2011, "s": [[1, 12]], "i": 22}]
        cat["series"][1]["items"] = [{"n": "Fargo", "p": "http://panel/fargo.png", "s": [[1, 10], [2, 10]], "i": 71},
                                     {"n": "Lupin", "p": "http://panel/lupin2.png", "s": [[1, 5]], "i": 73},
                                     {"n": "Shameless", "y": 2004, "s": [[1, 7]], "i": 74},
                                     {"n": "Narcos", "y": 2015, "s": [[1, 10]], "i": 75, "t": 63351},
                                     {"n": "Narcos", "y": 2015, "s": [[1, 10]], "i": 76, "t": 73911}]
        cat["series"][0]["items"] = [x for x in cat["series"][0]["items"] if not (x["n"] == "Shameless" and x["i"] == 22)] + \
            [{"n": "Shameless", "y": 2011, "s": [[1, 12]], "i": 22}]
        _write(d, "casper", cat)
        res = seo_build.build(d)
        con = seo_db.connect(d)
        q = lambda sql, *a: con.execute(sql, a).fetchall()   # noqa: E731
        bb = q("SELECT id, slug FROM content WHERE slug='breaking-bad' AND merged_into IS NULL")
        al = {r[0] for r in q("SELECT alias FROM content_alias WHERE content_id=?", bb[0][0])} if bb else set()
        check("1. Breaking Bad العربي/الإنجليزي → نفس الكيان", len(bb) == 1 and "بريكنغ باد" in al and "Breaking Bad" in al
              and len(q("SELECT 1 FROM content_service WHERE content_id=?", bb[0][0])) == 3, str(al))
        dune = q("SELECT slug, year FROM content WHERE title='Dune' ORDER BY year")
        check("2. Dune 1984 وDune 2021 → كيانان", [tuple(r) for r in dune] == [("dune-1984", 1984), ("dune", 2021)], str([tuple(r) for r in dune]))
        sh = q("SELECT slug, year FROM content WHERE title='Shameless' AND merged_into IS NULL ORDER BY year")
        check("3. مسلسل بنفس الاسم وسنوات مختلفة (في سيرفر واحد وبين السيرفرات) → كيانان",
              [tuple(r) for r in sh] == [("shameless-2004", 2004), ("shameless", 2011)]
              and not q("SELECT 1 FROM review WHERE status='open' AND json_extract(payload_json,'$.name')='Shameless'"), str([tuple(r) for r in sh]))
        na = q("SELECT c.slug, c.tmdb_id, c.match, x.external_id, x.verified FROM content c JOIN external_id x ON x.entity='content' AND x.entity_id=c.id "
               "AND x.source='tmdb' WHERE c.title='Narcos' AND c.merged_into IS NULL ORDER BY x.external_id")
        check("4. نفس الاسم + TMDB IDs مختلفة → كيانان؛ ومعرّف اللوحة مرشَّحٌ غير مُتحقَّق (لا يُكتب في الكيان قبل التحقق)",
              [tuple(r) for r in na] == [("narcos", None, "local", "63351", 0), ("narcos-2015", None, "local", "73911", 0)]
              and not q("SELECT 1 FROM review WHERE status='open' AND json_extract(payload_json,'$.name')='Narcos'"), str([tuple(r) for r in na]))
        lu = q("SELECT COUNT(*) FROM content WHERE title='Lupin' AND merged_into IS NULL")[0][0]
        rv = q("SELECT kind FROM review WHERE status='open' AND json_extract(payload_json,'$.name')='Lupin'")
        fa = q("SELECT COUNT(*) FROM content WHERE title='Fargo' AND merged_into IS NULL")[0][0]
        check("5. الغامض (الاسم نفسه في قسمين بلا قرينة) → مراجعة لا دمج؛ وبالصورة نفسها (Fargo) واحد",
              lu == 2 and [r[0] for r in rv] == ["same_server_ambiguous"] and fa == 1
              and [r[0] for r in q("SELECT kind FROM review WHERE status='open' AND json_extract(payload_json,'$.name')='The Office'")] == ["name_only"], f"lupin={lu} fargo={fa} {rv}")
        cid, old = bb[0][0], bb[0][1]
        seo_db.change_slug(con, cid, "breaking-bad-tv", reason="test"); con.commit()
        row = q("SELECT id, slug, slug_source FROM content WHERE id=?", cid)[0]
        check("6. تغيير slug → لا يغيّر entity_id", tuple(row) == (cid, "breaking-bad-tv", "manual"))
        rd = {r[0]: (r[1], r[2]) for r in q("SELECT path, target, code FROM redirect")}
        check("7. تغيير slug → يسجّل redirect 301 باللغتين، والقيمة السابقة في provenance",
              rd == {"/content/series/breaking-bad/": ("/content/series/breaking-bad-tv/", 301),
                     "/en/content/series/breaking-bad/": ("/en/content/series/breaking-bad-tv/", 301)}
              and json.loads(q("SELECT prev FROM provenance WHERE entity='content' AND entity_id=? AND field='slug'", cid)[0][0]) == "breaking-bad", str(rd))
        seo_db.change_slug(con, cid, "breaking-bad-2008", reason="test2"); con.commit()
        rd = {r[0]: r[1] for r in q("SELECT path, target FROM redirect")}
        check("7b. تغييرٌ ثانٍ: القديمان كلاهما إلى الأحدث (لا سلسلة ولا حلقة)",
              rd["/content/series/breaking-bad/"] == "/content/series/breaking-bad-2008/"
              and rd["/content/series/breaking-bad-tv/"] == "/content/series/breaking-bad-2008/" and "/content/series/breaking-bad-2008/" not in rd)
        scr = seo_sources.slug_changes_report(con, 0)
        check("7c. تقرير تبديلات slug: الكيان والقديم والجديد وهدف التحويل، مباشرٌ بلا سلسلة", scr and all(x["direct"] and not x["chain"] for x in scr) and scr[-1]["new_slug"] == "breaking-bad-2008"
              and con.execute("SELECT COUNT(*) FROM redirect a JOIN redirect b ON b.path=a.target").fetchone()[0] == 0, str(scr))
        seo_build.build(d, force=True)
        con.close(); con = seo_db.connect(d)
        check("6b. إعادة البناء لا تمسّ slug ولا المعرّف", tuple(q("SELECT id, slug FROM content WHERE id=?", cid)[0]) == (cid, "breaking-bad-2008"))
        seo_db.apply_fields(con, "content", cid, {"title": "بريكنج باد", "overview_ar": "قصة يدوية"}, "manual"); con.commit()
        changed = seo_db.apply_fields(con, "content", cid, {"title": "Breaking Bad (TMDB)", "overview_ar": "من TMDB", "overview_en": "From TMDB", "runtime": 47}, "tmdb")
        con.commit()
        row = q("SELECT title, overview_ar, overview_en, runtime FROM content WHERE id=?", cid)[0]
        pv = seo_db.provenance(con, "content", cid)
        prev = q("SELECT prev FROM provenance WHERE entity='content' AND entity_id=? AND field='overview_en'", cid)[0][0]
        check("8. البيانات اليدوية لا تستبدلها مزامنة TMDB (والباقي يُكتب بمصدره وقيمته السابقة)",
              tuple(row) == ("بريكنج باد", "قصة يدوية", "From TMDB", 47) and sorted(changed) == ["overview_en", "runtime"]
              and pv["title"][0] == "manual" and pv["overview_en"][0] == "tmdb" and prev is None, str(tuple(row)))
        seo_build.build(d, force=True)
        con.close(); con = seo_db.connect(d)
        check("8b. ولا يستبدلها البناء من الفهارس", q("SELECT title FROM content WHERE id=?", cid)[0][0] == "بريكنج باد")
        check("9. الاسم الإنجليزي يولّد slug لاتينيًّا، والعربي وحده نقحرةً (مصدره مسجَّل)",
              tuple(q("SELECT slug, slug_source FROM content WHERE title='Wonder Woman'")[0]) == ("wonder-woman", "original")
              and all(re.fullmatch(r"[a-z0-9-]+", r[0]) for r in q("SELECT slug FROM content")))
        _write(d, "smart", _cat([], [{"n": "Breaking Bad", "y": 2008, "s": [[1, 7]], "d": plot, "i": 60},
                                     {"n": "بريكنج باد", "p": TMDB + "bb.jpg", "s": [[1, 7]], "i": 62}]))
        res = seo_build.build(d)
        con.close(); con = seo_db.connect(d)
        n = q("SELECT COUNT(*) FROM content WHERE merged_into IS NULL AND id IN (SELECT content_id FROM content_alias WHERE alias_norm=?)", M.norm("بريكنج باد"))[0][0]
        check("10. اسمٌ عربي جديد لعملٍ معروف (بقرينة الملصق) → alias لا كيانًا جديدًا", res["new"] == 0 and n == 1
              and q("SELECT id FROM content WHERE id IN (SELECT content_id FROM content_alias WHERE alias_norm=?)", M.norm("بريكنج باد"))[0][0] == cid, str(res))
        con.close()
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _serve(srv):
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}"


def unit_production_cases():
    """ما كشفته عيّنة الإنتاج الأولى (1 أكتوبر 2026): خطأ استدعاء Xtream، أسماء فالكون بالموسم والاسم الأصلي، لواحق
    «متعدد الترجمات»، الفاصلة العليا، قائمة الفشل الإلزامية، فصل عدّادات العيّنة، وعتبة الاقتراح."""
    print("== حالات الإنتاج ==")
    st = dict(seo_db.DEFAULTS)
    c = M.clean_title("التفاح الحرام مدبلج S06 YASAK ELMA Ar", st)
    check("تنظيف: «التفاح الحرام مدبلج S06 YASAK ELMA Ar» ← التفاح الحرام · موسم 6 · مدبلج · الأصلي YASAK ELMA",
          (c["base"], c["season"], c["versions"], c["original"]) == ("التفاح الحرام", 6, ["dubbed"], "YASAK ELMA"), str(c))
    c = M.clean_title("هذا البحر سوف يفيض مدبلج S01 Deep.In.Love", st)
    check("تنظيف: النقاط في الاسم الأصلي فراغات", (c["base"], c["original"]) == ("هذا البحر سوف يفيض", "Deep In Love"))
    c = M.clean_title("Heart of Stone - FHD - متعدد الترجمات", st)
    check("تنظيف: الجودة في الوسط و«متعدد الترجمات» نسخة multi", (c["base"], c["versions"]) == ("Heart of Stone", ["multi"]), str(c))
    c = M.clean_title("وطن ع وتر 2019 S01 Watan.A.Watar.2023", st)
    check("تنظيف: السنة من الاسم، والذيل 2023 يُحذف من الأصلي", (c["base"], c["year"], c["original"]) == ("وطن ع وتر", 2019, "Watan A Watar"), str(c))
    c = M.clean_title("D.Gray-man HALLOW S02", st)
    check("تنظيف: رمز الموسم في الآخر بلا أصلي", (c["base"], c["season"], c["original"]) == ("D.Gray-man HALLOW", 2, ""))
    check("تنظيف لا يمسّ الأسماء العادية", M.clean_title("Sub Zero", st)["base"] == "Sub Zero" and M.clean_title("S01 Something", st)["base"] == "S01 Something"
          and not M.clean_title("One Piece", st)["cleaned"])
    check("التطبيع يحذف الفاصلة العليا: Wayne's World = Waynes World", M.norm("Wayne's World") == M.norm("Waynes World") == "waynes world")
    xt = mock_xtream.serve(0); tm = mock_tmdb.serve(0)
    xbase, tbase = _serve(xt), _serve(tm)
    seo_sources.TMDB_API = tbase + "/3"
    d = tempfile.mkdtemp(prefix="seo_prod_")
    try:
        os.makedirs(os.path.join(d, "content"))
        with open(os.path.join(d, "content", "settings.json"), "w", encoding="utf-8") as f:
            json.dump({"servers": [{"key": "falcon", "name": "فالكون"}, {"key": "smart", "name": "سمارت"}]}, f, ensure_ascii=False)
        C.set_url(d, "smart", f"{xbase}/get.php?username=u&password=p&type=m3u_plus")
        C.refresh(d, "smart")
        # فالكون كما في الإنتاج: مواسم مفرّقة بأسمائها (الموسم 0 من القارئ)، وبلا series_id
        cat = _cat([{"n": "Heart of Stone - FHD - متعدد الترجمات", "i": 1}, {"n": "Waynes World", "i": 2}],
                   [{"n": "التفاح الحرام مدبلج S03 YASAK ELMA Ar", "s": [[0, 81]], "i": 10, "p": "http://panel/ye.png"},
                    {"n": "التفاح الحرام مدبلج S04 YASAK ELMA Ar", "s": [[0, 99]], "i": 11, "p": "http://panel/ye4.png"},
                    {"n": "التفاح الحرام مدبلج S05 YASAK ELMA Ar", "s": [[0, 95]], "i": 12, "p": "http://panel/ye5.png"},
                    {"n": "D.Gray-man HALLOW S01", "s": [[0, 103]], "i": 20}, {"n": "D.Gray-man HALLOW S02", "s": [[0, 13]], "i": 21}])
        cat["series"][0]["name"] = "Turkish - تركية مدبلجة"
        cat["series"][1]["name"] = "Anime - أنمي آسيوي"
        cat["series"][1]["items"] = [x for x in cat["series"][0]["items"] if x["n"].startswith("D.Gray")]
        cat["series"][0]["items"] = [x for x in cat["series"][0]["items"] if not x["n"].startswith("D.Gray")]
        _write(d, "falcon", cat)
        seo_build.build(d)
        con = seo_db.connect(d)
        q = lambda sql, *a: con.execute(sql, a).fetchall()   # noqa: E731
        ye = q("SELECT id, title, slug FROM content WHERE title='التفاح الحرام' AND merged_into IS NULL")
        seasons = {r[0]: r[1] for r in q("SELECT number, episode_count FROM season WHERE content_id=?", ye[0][0])} if ye else {}
        al = {r[0] for r in q("SELECT alias FROM content_alias WHERE content_id=?", ye[0][0])} if ye else set()
        check("فالكون: ثلاثة مدخلات S03/S04/S05 ← كيانٌ واحد بمواسمه 3 و4 و5، الاسم الأساسي «التفاح الحرام»، والأصلي YASAK ELMA alias",
              len(ye) == 1 and seasons == {3: 81, 4: 99, 5: 95} and "YASAK ELMA" in al and "التفاح الحرام مدبلج S03 YASAK ELMA Ar" in al, f"{[tuple(r) for r in ye]} {seasons} {al}")
        ver = q("SELECT versions_json, raw_names_json FROM content_service WHERE content_id=?", ye[0][0])[0]
        check("النسخة dubbed على رابط السيرفر، والأسماء الخام الثلاثة محفوظة", json.loads(ver[0]) == ["dubbed"] and len(json.loads(ver[1])) == 3)
        dg = q("SELECT id FROM content WHERE title='D.Gray-man HALLOW' AND merged_into IS NULL")
        check("D.Gray-man HALLOW S01 وS02 ← كيانٌ واحد بموسمين", len(dg) == 1 and {r[0] for r in q("SELECT number FROM season WHERE content_id=?", dg[0][0])} == {1, 2})
        hs = q("SELECT title FROM content WHERE slug='heart-of-stone'")
        check("«Heart of Stone - FHD - متعدد الترجمات» ← Heart of Stone بنسخة multi", hs and hs[0][0] == "Heart of Stone"
              and json.loads(q("SELECT versions_json FROM content_service WHERE content_id=(SELECT id FROM content WHERE slug='heart-of-stone')")[0][0]) == ["multi"])
        xtc = C.xtream_of(C.url_of(d, "smart"))
        smap = seo_sources._series_map(con, xtc, st, write=False)
        check("خريطة المسلسلات من اللوحة (الاستدعاء الذي أخطأ في الإنتاج) تعمل قراءةً", isinstance(smap, dict) and "breaking bad" in smap and q("SELECT COUNT(*) FROM api_cache")[0][0] == 0)
        seo_sources.set_tmdb_key(con, d, "testkey"); con.commit(); con.close()
        smp = seo_sources.sample(d, {"movie": 5, "series": 5, "turkish": 3, "anime": 3})
        works = {w["title"]: w for w in smp["works"]}
        check("لا فشل: failures فارغة فقط لأن run.error = 0", smp["run"]["error"] == 0 and smp["failures"] == [] and smp["errors"]["sample"] == [], str(smp["run"]))
        check("عدّادات منفصلة: أخطاء العيّنة · أخطاء الطابور السابقة · أخطاء اللقطة", set(smp["errors"]) == {"sample", "queue_preexisting", "bundle"} and "count" in smp["errors"]["queue_preexisting"])
        y = works.get("التفاح الحرام", {})
        check("التفاح الحرام ← TMDB عبر الاسم الأصلي YASAK ELMA: تركي confirmed (القسم + TMDB)، والرابط من الاسم الإنجليزي (forbidden-fruit) بتحويل 301",
              y.get("tmdb_id") == 98001 and y.get("turkish", {}).get("note") == "confirmed" and y.get("slug") == "forbidden-fruit" and y.get("slug_prev"), str({k: y.get(k) for k in ("tmdb_id", "turkish", "slug", "enrich")}))
        g = works.get("D.Gray-man HALLOW", {})
        check("D.Gray-man HALLOW ← TMDB: أنمي ياباني confirmed (القسم + TMDB)", g.get("tmdb_id") == 98002 and g.get("anime", {}).get("note") == "confirmed" and g.get("anime_kind") == "japanese", str(g.get("anime")))
        w = works.get("Waynes World", {})
        check("Waynes World ← Wayne's World (بلا فاصلة عليا)", w.get("tmdb_id") == 8870, str(w.get("enrich")))
        h = works.get("Heart of Stone", {})
        check("Heart of Stone بعد التنظيف ← TMDB", h.get("tmdb_id") == 99003, str(h.get("enrich")))
        cnt = smp["counters"]
        check("العدّادات: أسماءٌ نُظّفت، ونجاح TMDB بعد التنظيف، وتركي/أنمي confirmed", cnt["cleaned_names"] >= 3 and cnt["tmdb_after_clean"] >= 3
              and cnt["turkish"]["confirmed"] >= 1 and cnt["anime"]["confirmed"] >= 1, str(cnt))
        check("لكل عمل رسالة الطابور لكل مصدر", all("enrich" in w_ and "tmdb" in w_["enrich"] for w_ in smp["works"]) and y["enrich"]["tmdb"]["state"] == "done")
        check("تغيّرات الهوية مذكورة بعددها (ترقية slug بـ 301 موثّقة)", smp["identity_changes"]["slug_changed_since_last_bundle"] >= 1 and smp["identity_changes"]["redirects_added_since_last_bundle"] >= 1, str(smp["identity_changes"]))
        # فشلٌ حقيقي يظهر في failures بتفاصيله، ولا يُسقط العيّنة
        con = seo_db.connect(d)
        con.execute("UPDATE enrich_queue SET state='pending', next_at=0 WHERE source='tmdb'"); con.execute("DELETE FROM api_cache WHERE key LIKE 'tmdb:%'"); con.commit(); con.close()
        tm.down = True
        smp2 = seo_sources.sample(d, {"movie": 2, "series": 1, "turkish": 1, "anime": 1})
        tm.down = False
        check("تعطّل TMDB: run.error = عدد failures، ولكل فشل content_id وsource وoperation وerror_type وerror_message",
              smp2["run"]["error"] >= 1 and len(smp2["failures"]) == smp2["run"]["error"]
              and all({"content_id", "source", "operation", "error_type", "error_message"} <= set(f) for f in smp2["failures"]), str(smp2["failures"][:2]))
        con = seo_db.connect(d); con.execute("DELETE FROM api_cache WHERE key LIKE 'tmdb:%' AND status >= 500"); con.commit(); con.close()   # ردود التعطّل المخزَّنة (في الإنتاج لم تُخزَّن: الخطأ كان قبل الطلب)
        smp3 = seo_sources.sample(d, {"movie": 1, "series": 1, "turkish": 0, "anime": 0, "titles": []})
        pre = smp3["errors"]["queue_preexisting"]
        check("أخطاء الطابور السابقة: عدٌّ بحالها وتاريخها، وثلاثةٌ منها تُعاد الآن بالكود الحالي فتزول (retry_probe)",
              pre["count"] >= 1 and "by_state" in pre and pre["recorded_between"] and pre["retry_probe"] and all(x["after_state"] in ("done", "miss") and "Error" not in (x["after_message"] or "") for x in pre["retry_probe"]), str(pre["retry_probe"]))
        con = seo_db.connect(d)
        idx = seo_search.load(con); st2 = seo_db.settings(con)
        r = seo_search.explain(con, idx, "طبيعة الحب مترجم", st2)
        check("البحث: لاحقة النسخة تُحذف من الاستعلام، ولا اقتراح تحت العتبة 0.75", r["result"] == "none" or all(x["confidence"] >= 0.75 for x in r.get("suggest", [])), str(r)[:200])
        check("البحث بعد التنظيف: «التفاح الحرام» كيان، و«yasak elma» كيان (alias أصلي)", seo_search.explain(con, idx, "التفاح الحرام", st2)["result"] == "entity"
              and seo_search.explain(con, idx, "yasak elma", st2)["result"] == "entity")
        con.close()
    finally:
        xt.shutdown(); tm.shutdown()
        shutil.rmtree(d, ignore_errors=True)


def unit_sample2_cases():
    """ما كشفته عيّنة الإنتاج الثانية (2 أكتوبر 2026): دمج عملَين مختلفَين في السيرفر بدليل الموسم رغم قسمَين متعارضَين،
    التحقّق من TMDB باسمٍ عربي عام، طبقات الأنمي (رسوم ≠ أنمي)، الحلقات الرسمية مقابل المدرجة، تسوية عدد الكيانات
    (الكيانات المطويّة تُدمج بتحويلٍ لا تُترك غائبة)، وبحث «ون بيس»/«Prison Break» بكيانين."""
    print("== حالات عيّنة الإنتاج الثانية ==")
    st = dict(seo_db.DEFAULTS)
    e = lambda name, group, sid, **kw: dict(seo_build._entry("series", "falcon", {"name": group}, {"n": name, "i": sid, **kw}, st), local_key=name)   # noqa: E731
    a, b = e("السجين S01 Mahkum", "Turkish - تركية مترجمة", 1), e("السجين S01", "Syria - سورية", 2)
    sc, why = M.pair_score(e("السجين S02 Mahkum", "Turkish - تركية مترجمة", 3), b, st, same_server=True)
    check("رمزا موسمين من قسمين مختلفين لا يجمعان", "season_split_sections_differ" in why and "season_split" not in why and (sc is None or sc < st["merge_min"]), str((sc, why)))
    sc, why = M.pair_score(e("السجين S02 Mahkum", "Turkish - تركية مترجمة", 3), a, st, same_server=True)
    check("ورمزا موسمين من القسم نفسه يجمعان", "season_split" in why and sc >= st["merge_min"], str((sc, why)))
    sc, why = M.pair_score(e("X S02 Yasak Elma", "تركية مدبلجة", 4), e("X S01 YASAK ELMA Ar", "تركية مترجمة", 5), st, same_server=True)
    check("وقسمان مختلفان بالاسم الأصلي نفسه يجمعان", "season_split" in why, str((sc, why)))
    ent = {"type": "series", "title": "العهد", "aliases": ["العهد", "العهد مترجم S01 SOZ", "SOZ"], "originals": ["SOZ"], "hint_countries": ["TR"]}
    check("التحقّق: مرشّحٌ سوري لاسمٍ عربي عام مع أصلٍ لاتيني تركي يُرفض (origin)",
          M.verify_tmdb({"type": "series", "title": "Alahed", "original_title": "العهد", "aliases": [], "countries": ["SY"], "year": 2018}, ent, st) == (False, "origin"))
    check("والمرشّح التركي بالأصل نفسه يُقبل", M.verify_tmdb({"type": "series", "title": "Söz", "original_title": "Söz", "aliases": ["SOZ"], "countries": ["TR"], "year": 2017}, ent, st)[0])
    ce = seo_sources.classify_provider_error
    check("تصنيف أخطاء اللوحة: 503 = provider_unavailable (مؤقّت) · 401 = authentication · 429 = rate_limit · timed out = network",
          ce("xtream 503")["class"] == "provider_unavailable" and ce("xtream 503")["severity"] == "temporary" and ce("xtream 401")["class"] == "authentication"
          and ce("xtream 429")["class"] == "rate_limit" and ce("timed out")["class"] == "network", str(ce("xtream 503")))
    check("البحث: «ون بيس» و«وان بيس» و«One Piece» مفتاحٌ صوتي واحد، و«أوفيس» = Office",
          seo_search.phonetic("ون بيس") == seo_search.phonetic("One Piece") == seo_search.phonetic("وان بيس") and seo_search.phonetic("أوفيس") == seo_search.phonetic("Office"),
          str((seo_search.phonetic("ون بيس"), seo_search.phonetic("One Piece"), seo_search.phonetic("أوفيس"), seo_search.phonetic("Office"))))
    xt = mock_xtream.serve(0); tm = mock_tmdb.serve(0)
    xbase, tbase = _serve(xt), _serve(tm)
    seo_sources.TMDB_API = tbase + "/3"
    d = tempfile.mkdtemp(prefix="seo_s2_")
    try:
        os.makedirs(os.path.join(d, "content"))
        with open(os.path.join(d, "content", "settings.json"), "w", encoding="utf-8") as f:
            json.dump({"servers": [{"key": "falcon", "name": "فالكون"}, {"key": "smart", "name": "سمارت"}]}, f, ensure_ascii=False)
        C.set_url(d, "smart", f"{xbase}/get.php?username=u&password=p&type=m3u_plus")
        C.refresh(d, "smart")
        cat = _cat([], [])
        cat["series"] = [
            {"id": "t", "name": "Turkish - تركية مترجمة", "items": [
                {"n": "السجين S01 Mahkum", "s": [[0, 10]], "i": 30, "p": "http://panel/mk.png"}, {"n": "السجين S02 Mahkum", "s": [[0, 8]], "i": 31, "p": "http://panel/mk2.png"},
                {"n": "العهد مترجم S01 SOZ", "s": [[0, 20]], "i": 32},
                {"n": "التفاح الحرام مدبلج S03 YASAK ELMA Ar", "s": [[0, 81]], "i": 10}, {"n": "التفاح الحرام مدبلج S04 YASAK ELMA Ar", "s": [[0, 99]], "i": 11}]},
            {"id": "sy", "name": "Syria - سورية", "items": [{"n": "السجين S01", "s": [[0, 30]], "i": 40, "p": "http://panel/sy.png"}, {"n": "العهد S01 Al-Ahd", "s": [[0, 32]], "i": 41}]},
            {"id": "an", "name": "Anime - أنمي آسيوي", "items": [{"n": "Memorias de Idhún S01", "s": [[0, 10]], "i": 50}, {"n": "The King's Avatar S01", "s": [[0, 12]], "i": 51},
                                                             {"n": "Lookism S01", "s": [[0, 8]], "i": 52}, {"n": "Mystery Toon S01", "s": [[0, 6]], "i": 53}, {"n": "Attack on Titan S01", "s": [[0, 25]], "i": 55}]},
            {"id": "k", "name": "KIDS - كرتون مترجم", "items": [{"n": "Batman Beyond S01", "s": [[0, 13]], "i": 54}]},
            {"id": "f", "name": "Series", "items": [{"n": "Foo Bar S01", "s": [[0, 5]], "i": 60, "p": "http://panel/f1.png"}]},
            {"id": "g", "name": "Netflix", "items": [{"n": "Foo Bar S02", "s": [[0, 7]], "i": 61, "p": "http://panel/f2.png"}]}]
        _write(d, "falcon", cat)
        r1 = seo_build.build(d)
        con = seo_db.connect(d)
        q = lambda sql, *a: con.execute(sql, a).fetchall()   # noqa: E731
        sj = q("SELECT id, slug FROM content WHERE title='السجين' AND merged_into IS NULL ORDER BY id")
        hints = {r[0]: sorted(x[0] for x in q("SELECT t.key FROM content_taxonomy ct JOIN taxonomy t ON t.id=ct.taxonomy_id WHERE ct.content_id=? AND t.kind='country'", r[0])) for r in sj}
        check("«السجين» في «تركية» و«سورية» ← كيانان (لا دمج بدليل الموسم) وبند same_server_ambiguous، لكلٍّ قرينة بلده",
              len(sj) == 2 and sorted(hints.values()) == [["SY"], ["TR"]] and q("SELECT 1 FROM review WHERE kind='same_server_ambiguous' AND key LIKE '%السجين%' AND status='open'"), str((sj, hints)))
        check("«العهد» كذلك كيانان", len(q("SELECT id FROM content WHERE title='العهد' AND merged_into IS NULL")) == 2)
        check("«Foo Bar» بموسمين في قسمين مختلفين بلا قرينة ← كيانان الآن (غموض)", len(q("SELECT id FROM content WHERE title='Foo Bar' AND merged_into IS NULL")) == 2)
        rc = r1["reconciliation"]
        check("تسوية البناء الأول: قبل 0، والفرق = الجديد، متّسقة", rc["before"] == 0 and rc["after"] == rc["inserted"] and rc["explained"], str(rc))
        seo_sources.set_tmdb_key(con, d, "testkey"); con.commit(); con.close()
        r = seo_sources.run(d, limit=400, force=True)
        con = seo_db.connect(d)
        st2 = seo_db.settings(con)
        works = {}
        for r_ in q("SELECT id FROM content WHERE merged_into IS NULL"):
            w = seo_sources.describe(con, r_[0], st2)
            works.setdefault(w["title"], []).append(w)
        by_tmdb = {w["tmdb_id"]: w for ws in works.values() for w in ws if w["tmdb_id"]}
        # مصفوفة التركي
        mk, sy = by_tmdb.get(153515), by_tmdb.get(99006)
        check("تركي: «السجين S01/S02 Mahkum» ← Mahkum (TR/tr) عبر الأصلي، confirmed (القسم + TMDB)، البلد TR غير منازَع",
              mk and mk["turkish"]["note"] == "confirmed" and mk["country"] == ["TR"] and not mk["disputed"] and "Mahkum" in mk["aliases"], str(mk and (mk["turkish"], mk["disputed"], mk["enrich"])))
        check("و«السجين S01» السوري ← المسلسل السوري (SY/ar)، لا تركي، ولا يأخذ Mahkum رغم الاسم الواحد",
              sy and sy["country"] == ["SY"] and sy["turkish"] is None and sy["sections"] == {"falcon": ["Syria - سورية"]}, str(sy and (sy["country"], sy["turkish"], sy["enrich"])))
        soz, ahd = by_tmdb.get(99007), by_tmdb.get(281452)
        check("«العهد مترجم S01 SOZ» ← Söz (TR) لا Alahed السوري: الأصلي اللاتيني يُبحث به أولًا والقرينة تفصل",
              soz and soz["turkish"]["note"] == "confirmed" and "SOZ" in soz["aliases"], str(soz and (soz["turkish"], soz["enrich"])))
        check("و«العهد S01 Al-Ahd» السوري ← Alahed (SY)", ahd and ahd["country"] == ["SY"] and ahd["turkish"] is None, str(ahd and (ahd["country"], ahd["enrich"])))
        ye = works.get("التفاح الحرام", [{}])[0]
        check("التفاح الحرام (قسمٌ تركي واحد بمواسمه) ← كيانٌ واحد، تركي confirmed", len(works.get("التفاح الحرام", [])) == 1 and ye.get("turkish", {}).get("note") == "confirmed", str(ye.get("turkish")))
        tr_m = [(w["title"], w["turkish"] and w["turkish"]["decision"]) for ws in works.values() for w in ws if w["turkish"] and "falcon" in w["sections"]]
        check("مصفوفة التركي (فالكون): 3 confirmed · 0 review · 0 unconfirmed (لا قلب لنتيجة TMDB الصحيحة)، ولا بند taxonomy_mismatch تركي",
              sorted(x[1] for x in tr_m) == ["turkish"] * 3 and not q("SELECT 1 FROM review WHERE kind='taxonomy_mismatch' AND status='open' AND (payload_json LIKE '%turkish%' OR payload_json LIKE '%country:TR%' OR payload_json LIKE '%country:SY%')"),
              str(tr_m) + str([tuple(r) for r in q("SELECT kind, payload_json FROM review WHERE kind='taxonomy_mismatch' AND status='open'")]))
        # مصفوفة الأنمي
        idh, ka, lk, mt, bb, aot = (by_tmdb.get(i) for i in (87846, 99004, 99005, 99008, 99002, 1429))
        check("رسومٌ إسبانية (Memorias de Idhún، ES/es + كلمة «anime»): is_animation بلا anime_family، لا format ولا anime_kind، قسم «أنمي» ← مراجعة لا هب",
              idh and idh["is_animation"] and idh["anime_family"] == 0 and idh["format"] is None and idh["anime_kind"] is None and idh["anime"]["decision"] == "review"
              and "hub:anime" not in {k for k in idh["aliases"]} and not q("SELECT 1 FROM content_taxonomy ct JOIN taxonomy t ON t.id=ct.taxonomy_id WHERE ct.content_id=? AND t.key='anime' AND ct.source IN ('tmdb','manual')", idh["id"])
              and q("SELECT 1 FROM review WHERE key=? AND status='open'", f"taxonomy_mismatch:{idh['id']}"), str(idh and (idh["is_animation"], idh["anime_family"], idh["format"], idh["anime_kind"], idh["anime"])))
        check("دونغهوا صيني (zh/CN): أنمي confirmed بنوع chinese", ka and ka["anime_family"] == 1 and ka["anime_kind"] == "chinese" and ka["anime"]["note"] == "confirmed" and ka["format"] == "anime_series", str(ka and ka["anime"]))
        check("رسوم كورية (ko/KR): أنمي confirmed بنوع korean", lk and lk["anime_kind"] == "korean" and lk["anime"]["note"] == "confirmed", str(lk and lk["anime"]))
        check("ياباني (ja/JP): japanese confirmed", aot and aot["anime_kind"] == "japanese" and aot["anime"]["note"] == "confirmed", str(aot and aot["anime"]))
        check("رسومٌ أمريكية في قسم «كرتون» (بلا قرينة أنمي): is_animation، لا أنمي، لا مراجعة", bb and bb["is_animation"] and bb["anime_family"] == 0 and bb["anime"] is None and bb["anime_kind"] is None, str(bb and (bb["anime_family"], bb["anime"])))
        check("رسومٌ بلا لغةٍ ولا بلد + كلمة «anime» + قسم أنمي: غير محسوم (unconfirmed) لا «ياباني»",
              mt and mt["anime_family"] is None and mt["anime_kind"] is None and mt["anime"]["decision"] == "unconfirmed" and q("SELECT 1 FROM review WHERE key=? AND status='open'", f"taxonomy_unconfirmed:{mt['id']}"), str(mt and (mt["anime_family"], mt["anime"])))
        # الحلقات: رسمي مقابل مدرج
        ep = ye.get("episodes") or {}
        seas = {r[0]: (r[1], r[2]) for r in q("SELECT number, episode_count, episodes_official FROM season WHERE content_id=? ORDER BY number", ye["id"])}
        check("الحلقات: الرسمي من TMDB (6×5=30) منفصلٌ عن المدرج في القوائم (81+99=180) وعن سجلات الحلقات، ولكل سيرفر عدّه",
              ep.get("official_episode_count") == 30 and ep.get("official_season_count") == 6 and ep.get("available_episode_count") == 180 and ep.get("service_episode_count") == {"falcon": 180} and ep.get("episode_record_count") == 30
              and seas.get(3) == (81, 5) and seas.get(4) == (99, 5) and seas.get(1) == (0, 5), str((ep, seas)))
        check("الصفحة تذكر الرسمي (30 حلقة) لا 180", "30" in ye["page"]["ar"]["meta_description"] and "180" not in ye["page"]["ar"]["meta_description"], ye["page"]["ar"]["meta_description"])
        yeh = seo_pages.render_entity(con, d, "series", ye["slug"], __import__("content_page").lang_of("en"), st2)[1]["html"].decode()
        check("D.GRAY-MAN RULE: الرسمي (30) في JSON-LD وليس المتاح (180) — والمتاح يظهر «as listed» في المواسم فقط", '"numberOfEpisodes": 30' in yeh and '"numberOfEpisodes": 180' not in yeh and "180 episodes" not in yeh.split("<dl")[0], "")
        fb = works.get("Foo Bar", [{}])[0]
        check("Foo Bar بلا TMDB: الصفحة تقول «مدرجة على فالكون» (سيرفر واحد) لا رقمًا رسميًّا", fb.get("episodes", {}).get("official_episode_count") is None and "مدرجة على فالكون" in fb["page"]["ar"]["meta_description"], fb.get("page", {}).get("ar", {}).get("meta_description"))
        # البحث: اسمان لعملين، والتجميع للعرض
        idx = seo_search.load(con)
        r = seo_search.explain(con, idx, "السجين", st2)
        check("البحث «السجين» ← كيانان بالاسم نفسه مجمّعان للعرض مع سبب الانفصال (معرّفان مختلفان بعد الإثراء)",
              r["result"] == "entity" and len(r["entities"]) == 2 and len(r["grouped"]) == 1 and r["grouped"][0]["why_separate"] == ["different tmdb ids"], str(r)[:300])
        slug_changes = q("SELECT COUNT(*) FROM provenance WHERE entity='content' AND field='slug' AND prev IS NOT NULL")[0][0]   # ترقيات TMDB (translit ← en) موثّقة
        con.close()
        # طيّ المواسم: ما كان كيانين يصير عنصرًا واحدًا ← الكيان الآخر يُدمج بتحويلٍ ومراجعة، لا يُترك غائبًا — والتسوية تفسّر الفرق
        cat["series"][5]["items"] = []
        cat["series"][4]["items"].append({"n": "Foo Bar S02", "s": [[0, 7]], "i": 61, "p": "http://panel/f2.png"})
        _write(d, "falcon", cat)
        r2 = seo_build.build(d)
        con = seo_db.connect(d)
        fb = q("SELECT id, merged_into, available, slug FROM content WHERE title='Foo Bar' ORDER BY id")
        rc = r2["reconciliation"]
        check("Foo Bar S01+S02 في قسمٍ واحد الآن ← عنصرٌ واحد: الكيان الثاني merged_into الأول مع 301 وبند merged_entities، لا غائب",
              len(fb) == 2 and fb[1][1] == fb[0][0] and fb[0][2] == 1 and q("SELECT 1 FROM redirect WHERE path=?", f"/content/series/{fb[1][3]}/")
              and q("SELECT 1 FROM review WHERE key=? AND status='open'", f"merged:{fb[0][0]}:{fb[1][0]}") and {r[0] for r in q("SELECT number FROM season WHERE content_id=?", fb[0][0])} == {1, 2},
              str(([tuple(r) for r in fb], rc)))
        check("التسوية: الفرق −1 = مدمج 1، غاب 0، متّسقة", rc["delta"] == -1 and rc["merged"] == 1 and rc["went_unavailable"] == 0 and rc["explained"], str(rc))
        pg = seo_build.progress(d)
        check("عدّاد البناء: بعد الاكتمال المرحلة الأخيرة 100% مع الوقت المنقضي، ومراحله الأربع بأوزانٍ مجموعها 100",
              pg and pg["stage"] == "finish" and pg["percent"] == 100 and "elapsed" in pg and sum(w for _, _, w in seo_build.STAGES) == 100, str(pg))
        hist = seo_db.state(con, "reconciliations") or []
        check("تاريخ التسويات: بناءان مسجَّلان بترتيبهما", len(hist) == 2 and hist[-1]["merged"] == 1 and hist[0]["before"] == 0, str(hist))
        seo_build._last.clear(); seo_build._stats_cache.clear()           # كأن الخادم أُعيد تشغيله بعد النشر
        st_ = seo_build.stats(d)
        check("نتيجة آخر بناء تبقى بعد إعادة التشغيل (من القاعدة): الأعداد والثواني لا الوقت وحده", st_["last"] and st_["last"].get("ok") and "seconds" in st_["last"] and st_["last"]["merged"] == 1, str(st_["last"]))
        check("ولا يتغيّر slug أي كيانٍ في البناء الثاني (التغييرات كلها ترقيات TMDB الموثّقة قبله)",
              q("SELECT COUNT(*) FROM provenance WHERE entity='content' AND field='slug' AND prev IS NOT NULL")[0][0] == slug_changes)
        smp = seo_sources.sample(d, {"movie": 1, "series": 2, "turkish": 2, "anime": 2})
        check("العيّنة تحمل التسوية وعدّادات التركي/الأنمي بالحالات الثلاث", smp.get("reconciliation", {}).get("explained") and set(smp["counters"]["anime"]) >= {"confirmed", "review", "unconfirmed"}, str(smp.get("reconciliation")))

        ic = smp["identity_changes"]
        check("عدّادات الهوية مُعرَّفة ومتصالحة: بنود الانقسام منذ اللقطة = مجموع «انفصال» في بناءاتها، وتاريخ البناءات موجود",
              "definitions" in ic and ic["split_reviews_opened_since_last_bundle"] == ic["split_sum_over_builds"] == ic["splits"]["total"] and len(ic["builds_since_last_bundle"]) >= 1, str({k: ic[k] for k in ("split_reviews_opened_since_last_bundle", "split_sum_over_builds", "builds_since_last_bundle")}))
        con.close()
    finally:
        xt.shutdown(); tm.shutdown()
        shutil.rmtree(d, ignore_errors=True)


def unit_identity_cases():
    """الانقسامات مفسَّرة: من أين، ولماذا (غاب الدليل أم تناقض)، وبلا تغيير URL؛ رقم بثٍّ أعيد استعماله لعملٍ آخر لا يُربط؛ والعنوان لا يتقلّب."""
    print("== الهوية: الانقسام وإعادة استعمال رقم البثّ وثبات العنوان ==")
    d = tempfile.mkdtemp(prefix="seo_id_")
    try:
        os.makedirs(os.path.join(d, "content"))
        with open(os.path.join(d, "content", "settings.json"), "w", encoding="utf-8") as f:
            json.dump({"servers": [{"key": "casper", "name": "كاسبر"}, {"key": "falcon", "name": "فالكون"}]}, f, ensure_ascii=False)
        _write(d, "casper", _cat([{"n": "Alpha Film", "y": 2010, "i": 90, "p": TMDB + "alpha.jpg"}], [{"n": "Foo Show", "s": [[1, 10]], "i": 50, "p": TMDB + "foo.jpg"}, {"n": "ون بيس", "s": [[1, 5]], "i": 51, "p": TMDB + "op.jpg"}]))
        _write(d, "falcon", _cat([], [{"n": "Foo Show", "s": [[1, 10]], "i": 60, "p": TMDB + "foo.jpg"}, {"n": "One Piece", "s": [[1, 5]], "i": 61, "p": TMDB + "op.jpg"}]))
        seo_build.build(d)
        con = seo_db.connect(d)
        q = lambda sql, *a: con.execute(sql, a).fetchall()   # noqa: E731
        foo = q("SELECT id, slug, title FROM content WHERE title='Foo Show' AND merged_into IS NULL")
        check("كاسبر وفالكون بالملصق نفسه ← كيانٌ واحد", len(foo) == 1 and len(q("SELECT 1 FROM content_service WHERE content_id=?", foo[0][0])) == 2)
        op = q("SELECT id, title FROM content WHERE title IN ('ون بيس','One Piece') AND merged_into IS NULL")
        check("«ون بيس» و«One Piece» بالملصق نفسه ← كيانٌ واحد بعنوانٍ أول", len(op) == 1)
        t0 = op[0][1]
        con.close()
        # كاسبر يُحدَّث بلا ملصقات (لوحةٌ متدهورة) ورقم البثّ 90 يحمل الآن عملًا آخر تمامًا
        _write(d, "casper", _cat([{"n": "Zeta Different", "y": 2019, "i": 90}], [{"n": "Foo Show", "s": [[1, 10]], "i": 50}, {"n": "ون بيس", "s": [[1, 5]], "i": 51, "p": TMDB + "op.jpg"}]))
        r2 = seo_build.build(d)
        con = seo_db.connect(d)
        foo2 = q("SELECT id, slug, title, available FROM content WHERE title='Foo Show' AND merged_into IS NULL ORDER BY id")
        rv = q("SELECT payload_json FROM review WHERE kind='split_entity' AND status='open'")
        p = json.loads(rv[0][0]) if rv else {}
        check("غاب الدليل (الملصق) ← كاسبر ينفصل كيانًا جديدًا (سياسة الدليل كما هي) — وبند الانقسام يحمل الأصل والسبب no_evidence والسيرفر",
              len(foo2) == 2 and len(rv) == 1 and p.get("from") == [foo[0][0]] and p.get("cause") == ["no_evidence"] and p.get("services") in (["casper"], ["falcon"]), str((foo2, p)))
        check("الانقسام لا يمسّ URL الأصل ولا يُنشئ تحويلًا", foo2[0][1] == foo[0][1] and not q("SELECT 1 FROM redirect"))
        rep = seo_sources.splits_report(con, 0)
        ex = rep["examples"][0]
        check("تقرير الانقسامات: العدد والسبب والسيرفر واليوم ومثالٌ (الأصل ← الجديد، القديم والجديد من slug، بلا تغيير URL)",
              rep["total"] == 1 and rep["by_cause"] == {"no_evidence": 1} and list(rep["by_service"].values()) == [1] and ex["old_entity"][0]["id"] == foo[0][0]
              and ex["old_slug"] == [foo[0][1]] and ex["new_slug"] != foo[0][1] and ex["old_url_changed"] is False and rep["url_changes"] == 0, str(rep)[:400])
        za = q("SELECT id, title, available FROM content WHERE title IN ('Alpha Film','Zeta Different') ORDER BY id")
        check("رقم البثّ 90 عاد باسمٍ آخر: لا يُربط بـ Alpha Film (يبقى بعنوانه، غائبًا) بل كيانٌ جديد — وعدد إعادة الاستعمال في التسوية",
              [(r[1], r[2]) for r in za] == [("Alpha Film", 0), ("Zeta Different", 1)] and r2["reconciliation"]["stream_id_reused"] == 1, str((za, r2["reconciliation"])))
        op2 = q("SELECT id, title FROM content WHERE id=?", op[0][0])
        check("العنوان المستقرّ لا يتقلّب بين السيرفرات في إعادة البناء", op2[0][1] == t0, str((t0, op2)))
        con.close()
    finally:
        shutil.rmtree(d, ignore_errors=True)


def unit_migrate():
    """قاعدةٌ من إصدارٍ أقدم (بلا أعمدة الإصدارات 4–6) تُرحَّل بلا خطأ — ما فشل في الإنتاج: فهرس person_norm قبل العمود."""
    print("== الترحيل ==")
    d = tempfile.mkdtemp(prefix="seo_mig_")
    try:
        con = seo_db.connect(d)
        for sql in ("DROP INDEX IF EXISTS person_norm", "ALTER TABLE person DROP COLUMN name_norm", "ALTER TABLE episode DROP COLUMN source",
                    "ALTER TABLE content DROP COLUMN is_animation", "ALTER TABLE content DROP COLUMN anime_family", "ALTER TABLE content DROP COLUMN episodes_official",
                    "ALTER TABLE content DROP COLUMN seasons_official", "ALTER TABLE season DROP COLUMN episodes_official", "ALTER TABLE content_service DROP COLUMN stream_ids_json",
                    "PRAGMA user_version=3"):
            con.execute(sql)
        con.commit(); con.close()
        try:
            con = seo_db.connect(d)
            cols = {t: {r[1] for r in con.execute(f"PRAGMA table_info({t})")} for t in ("person", "episode", "content", "season", "content_service")}
            ok = ("name_norm" in cols["person"] and "source" in cols["episode"] and {"is_animation", "anime_family", "episodes_official", "seasons_official"} <= cols["content"]
                  and "episodes_official" in cols["season"] and "stream_ids_json" in cols["content_service"]
                  and con.execute("PRAGMA user_version").fetchone()[0] == seo_db.VERSION
                  and con.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='person_norm'").fetchone())
            con.close()
            check("قاعدة الإصدار 3 ← الإصدار الحالي: الأعمدة كلها والفهرس person_norm بلا خطأ", bool(ok), str(cols))
        except Exception as ex:  # noqa: BLE001
            check("قاعدة الإصدار 3 ← الإصدار الحالي: الأعمدة كلها والفهرس person_norm بلا خطأ", False, f"{type(ex).__name__}: {ex}")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def unit_sample3_cases():
    """ما طلبته مراجعة العيّنة الثالثة: Prison Break وOne Piece كيانًا واحدًا لكل معرّف TMDB (لا دمج بالاسم)، «ون بيس» alias،
    شبكة الأشخاص (ممثل · مخرج · كاتب · شركة) علاقاتٍ حقيقية بصفحاتٍ وروابط، توحيد الشخص، الحلقات، ومصفوفة البحث."""
    print("== حالات عيّنة الإنتاج الثالثة ==")
    xt = mock_xtream.serve(0); tm = mock_tmdb.serve(0)
    xbase, tbase = _serve(xt), _serve(tm)
    seo_sources.TMDB_API = tbase + "/3"
    d = tempfile.mkdtemp(prefix="seo_s3_")
    try:
        os.makedirs(os.path.join(d, "content"))
        with open(os.path.join(d, "content", "settings.json"), "w", encoding="utf-8") as f:
            json.dump({"servers": [{"key": "casper", "name": "كاسبر"}, {"key": "falcon", "name": "فالكون"}, {"key": "smart", "name": "سمارت"}]}, f, ensure_ascii=False)
        C.set_url(d, "smart", f"{xbase}/get.php?username=u&password=p&type=m3u_plus")
        C.refresh(d, "smart")
        ccat = _cat([], [{"n": "Prison Break", "y": 2005, "s": [[1, 22]], "i": 23, "p": "http://panel/pb.png"},
                         {"n": "One Piece", "s": [[1, 61], [2, 50]], "i": 22}, {"n": "ون بيس", "s": [[1, 61], [2, 50], [3, 40]], "i": 24},
                         {"n": "Stub Show", "s": [[1, 54]], "i": 25}])
        ccat["series"][1]["name"] = "NETFLIX نتفلكس |AR|"
        ccat["series"][1]["items"] = [{"n": "One Piece", "s": [[1, 8], [2, 8]], "i": 26}]      # كما في الإنتاج (7074): لا سنة، موسمان من 8
        _write(d, "casper", ccat)
        cat = _cat([], [])
        cat["series"] = [{"id": "s", "name": "Series", "items": [{"n": "Prison Break S01 Prison.Break", "s": [[0, 22]], "i": 70, "p": "http://panel/pb1.png"}]},
                         {"id": "n", "name": "Netflix", "items": [{"n": "Prison Break S05 Prison.Break", "s": [[0, 9]], "i": 71, "p": "http://panel/pb5.png"},
                                                                  {"n": "One Piece S01", "y": 2023, "s": [[0, 8]], "i": 73}]},
                         {"id": "a", "name": "Anime - أنمي", "items": [{"n": "ONE PIECE S01 One.Piece", "s": [[0, 61]], "i": 72}]}]
        _write(d, "falcon", cat)
        seo_build.build(d)
        con = seo_db.connect(d)
        q = lambda sql, *a: con.execute(sql, a).fetchall()   # noqa: E731
        pb0 = q("SELECT id FROM content WHERE title='Prison Break' AND merged_into IS NULL")
        check("قبل الإثراء: Prison Break ثلاثة كيانات (كاسبر، وفالكون S01 وS05 في قسمين بلا دليل) — لا دمج بالاسم", len(pb0) == 3, str(pb0))
        for r_ in pb0:                                    # كما في الإنتاج: لوحة كل سيرفر أعطت أسماء الممثلين قبل TMDB
            seo_sources._people_xtream(con, r_[0], {"cast": "Wentworth Miller, Dominic Purcell", "director": ""}, 900)
        con.commit()
        seo_sources.set_tmdb_key(con, d, "testkey"); con.commit(); con.close()
        smp = seo_sources.sample(d, {"movie": 2, "series": 3, "turkish": 1, "anime": 1, "titles": ["Prison Break", "One Piece", "ون بيس"]})
        con = seo_db.connect(d)
        st2 = seo_db.settings(con)
        pb = q("SELECT id, slug, tmdb_id, merged_into FROM content WHERE title='Prison Break' ORDER BY id")
        live = [r for r in pb if r[3] is None]
        srv = sorted(x[0] for x in q("SELECT service_key FROM content_service WHERE content_id=? AND present=1", live[0][0])) if live else []
        seas = {r[0] for r in q("SELECT number FROM season WHERE content_id=?", live[0][0])} if live else set()
        check("A) Prison Break: بعد TMDB (2288 لكلٍّ) ← كيانٌ واحد حيّ، والآخران merged_into بتحويل 301، خدماته كاسبر+فالكون، ومواسمه 1 و5 (المواسم انتقلت)",
              len(pb) == 3 and len(live) == 1 and live[0][2] == 2288 and all(r[3] == live[0][0] for r in pb if r[3] is not None)
              and srv == ["casper", "falcon", "falcon"] and {1, 5} <= seas and len(q("SELECT 1 FROM redirect WHERE target LIKE '%prison%'")) >= 2, str((pb, srv, seas)))
        wm_rows = q("SELECT p.id, p.name, cp.source FROM content_person cp JOIN person p ON p.id=cp.person_id WHERE cp.content_id=? AND p.name_norm='miller wentworth'", live[0][0])
        pb_desc = seo_pages.render_entity(con, d, "series", live[0][1], __import__("content_page").lang_of("ar"), st2)[1]["desc"]
        check("دمج الكيانات الثلاثة لا يكرّر الممثل: صفّ TMDB وحده يبقى (أسماء اللوحة من المدمجين تُسقط)، و«بطولة» تذكر Wentworth Miller مرةً واحدة",
              len(wm_rows) == 1 and wm_rows[0][2] == "tmdb" and pb_desc.count("Wentworth Miller") == 1, str((wm_rows, pb_desc)))
        rs = smp["resolution"]
        check("تقرير التوحيد في العيّنة: Prison Break قبل 3 ← بعد كيانٌ حيٌّ واحد بمعرّفه (one entity per tmdb id)",
              rs["Prison Break"]["live_entities"] == 1 and rs["Prison Break"]["verdict"] == "one entity per tmdb id" and len(rs["Prison Break"]["merged"]) == 2, str(rs["Prison Break"]))
        op = q("SELECT id, title, year, tmdb_id, merged_into FROM content WHERE tmdb_id IN (37854, 111110) AND merged_into IS NULL ORDER BY tmdb_id")
        links = {r[3]: sorted(x[0] for x in q("SELECT service_key FROM content_service WHERE content_id=? AND present=1", r[0])) for r in op}
        al = {r[0] for r in q("SELECT alias FROM content_alias WHERE content_id=(SELECT id FROM content WHERE tmdb_id=37854 AND merged_into IS NULL)")}
        check("B) One Piece: كيانان بمعرّفين (1999 أنمي: كاسبر One Piece + كاسبر «ون بيس» + فالكون ONE PIECE S01 — 2023 الحيّ: فالكون One Piece S01)، و«ون بيس» alias على الأنمي لا كيانًا، وكاسبر NETFLIX بلا حسم",
              [r[3] for r in op] == [37854, 111110] and links[37854] == ["casper", "casper", "falcon"] and links[111110] == ["falcon"] and "ون بيس" in al
              and not q("SELECT 1 FROM content WHERE title='ون بيس' AND merged_into IS NULL") and len(q("SELECT 1 FROM content WHERE title='One Piece' AND match='local' AND merged_into IS NULL")) == 1, str((op, links, sorted(al)[:6])))
        msgs = [x[0] for x in q("SELECT error FROM enrich_queue WHERE source='tmdb' AND content_id IN (SELECT id FROM content WHERE tmdb_id=37854)")]
        check("التوحيد بالدليل لا بالاسم: «One Piece» بلا سنة بين مرشّحين قويين حُسم بمواسم القائمة/قرينة أنمي (via search…+evidence)",
              any("+evidence" in (m_ or "") for m_ in msgs), str(msgs))
        # C) العلاقات والصفحات
        pbw = next(w for w in smp["works"] if w.get("tmdb_id") == 2288)
        rel = pbw["relations"]
        check("C) Prison Break ← ممثلان (TMDB) ومبتكر وكاتب وشركة، كلٌّ بمعرّفه ومسار صفحته وتُرسم",
              [a["name"] for a in rel["actors"]] == ["Wentworth Miller", "Dominic Purcell"] and {w_["name"] for w_ in rel["writers"]} == {"Paul Scheuring", "Some Writer"}
              and rel["companies"][0]["name"] == "20th Century Fox Television" and all(x["renders"] for g in rel.values() for x in g)
              and rel["actors"][0]["page"].startswith("/content/people/actors/") and rel["writers"][0]["page"].startswith("/content/people/writers/") and rel["companies"][0]["page"].startswith("/content/companies/"), json.dumps(rel, ensure_ascii=False)[:400])
        tr_ar, tr_en = __import__("content_page").lang_of("ar"), __import__("content_page").lang_of("en")
        ent = seo_pages.render_entity(con, d, "series", live[0][1], tr_ar, st2)[1]["html"].decode()
        wm = q("SELECT slug FROM person WHERE name='Wentworth Miller'")[0][0]
        co = q("SELECT slug FROM company WHERE name='20th Century Fox Television'")[0][0]
        check("روابط صفحة العمل: الممثل ← /people/actors/، الكاتب ← /people/writers/، الشركة ← /companies/ (والسيرفرات في «متوفر عبر» لا في الإنتاج)",
              f"/content/people/actors/{wm}/" in ent and "/content/people/writers/" in ent and f"/content/companies/{co}/" in ent and '"productionCompany"' in ent and '"author"' in ent, "")
        con.close()
        seo_sources.run(d, limit=400, force=True)          # بقية الأعمال (Breaking Bad من سمارت…) لشبكة الأشخاص كاملة
        con = seo_db.connect(d)
        pp = seo_pages.render_person(con, d, "actors", wm, tr_ar, st2)[1]
        html = pp["html"].decode()
        hl = pbw["page"]["ar"]["hreflang"]
        check("HREFLANG: ar وen وx-default بلا تكرار رمز، وx-default = النسخة العربية الافتراضية (بلا بادئة)، والتقرير يعرضها برموزها",
              pbw["page"]["ar"]["hreflang_ok"] and [h["lang"] for h in hl] == ["ar", "en", "x-default"] and hl[2]["url"] == hl[0]["url"] and "/en/" in hl[1]["url"] and "/en/" not in hl[0]["url"], str(hl))
        ra = smp["identity_changes"]["redirects_added"]
        check("REDIRECTS: كل تحويلٍ منذ اللقطة بسببه ووجهته، مباشرٌ إلى الكيان النهائي وبلا سلسلة؛ وعددها = redirects_added_since_last_bundle",
              ra and len(ra) == smp["identity_changes"]["redirects_added_since_last_bundle"] and all(x["direct_to_final"] and not x["chain"] and x["code"] == 301 for x in ra), str(ra)[:300])
        check("D) صفحة الممثل: أعماله كلها (Prison Break + ONE PIECE الحيّ)، canonical، hreflang عربي/إنجليزي، BreadcrumbList، Person، noindex، وروابط إلى صفحات أعماله",
              pp["works"] == 2 and pp["canonical"].endswith(f"/content/people/actors/{wm}/") and len(pp["alts"]) == 3 and '"BreadcrumbList"' in html and '"@type": "Person"' in html
              and "noindex" in html and f"/content/series/{live[0][1]}/" in html and pp["index_ar"], str({k: pp[k] for k in ("works", "canonical", "alts", "index_ar")}))
        check("مسار الدور يجب أن يحمله الشخص: Wentworth Miller ليس في /people/directors/ (404)", seo_pages.render_person(con, d, "directors", wm, tr_ar, st2) is None)
        vg = q("SELECT id, slug FROM person WHERE name='Vince Gilligan'")
        roles = sorted(r[0] for r in q("SELECT role FROM content_person WHERE person_id=?", vg[0][0])) if vg else []
        check("WRITER MODEL: Vince Gilligan صفٌّ واحد بدورَين creator وwriter (بمعرّف TMDB الواحد)، وSome Writer في Breaking Bad screenwriter",
              len(vg) == 1 and roles == ["creator", "writer"] and q("SELECT 1 FROM content_person cp JOIN person p ON p.id=cp.person_id WHERE p.name='Some Writer' AND cp.role='screenwriter'"), str((vg, roles)))
        wp = seo_pages.render_person(con, d, "writers", vg[0][1], tr_en, st2)[1]
        check("صفحة الكاتب الإنجليزية: /en/content/people/writers/…، jobTitle في Person", wp["canonical"].endswith(f"/en/content/people/writers/{vg[0][1]}/") and '"jobTitle"' in wp["html"].decode())
        cp = seo_pages.render_company(con, d, co, tr_ar, st2)[1]
        chtml = cp["html"].decode()
        check("صفحة الشركة: Organization، breadcrumb، canonical، رابط العمل، وعملٌ واحد ← بلا فهرسة (few works) لكنها تُرسم noindex",
              '"@type": "Organization"' in chtml and '"BreadcrumbList"' in chtml and cp["canonical"].endswith(f"/content/companies/{co}/") and f"/content/series/{live[0][1]}/" in chtml
              and cp["index_ar"] is False and "noindex" in chtml, str({k: cp[k] for k in ("canonical", "index_ar", "works")}))
        check("الشركة ليست سيرفرًا: Casper/Smart/Falcon لا تظهر في company", not q("SELECT 1 FROM company WHERE lower(name) IN ('casper','smart','falcon','كاسبر','سمارت','فالكون')"))
        # pagination
        con.execute("INSERT INTO seo_settings(key, value, updated_at) VALUES ('page_size', '1', 0) ON CONFLICT(key) DO UPDATE SET value='1'"); con.commit()
        st_small = seo_db.settings(con)
        p1 = seo_pages.render_person(con, d, "actors", wm, tr_ar, st_small)[1]; p2 = seo_pages.render_person(con, d, "actors", wm, tr_ar, st_small, 2)[1]
        check("ترقيم الصفحات: صفحتان بعملٍ لكلٍّ، rel=next في الأولى وrel=prev في الثانية، canonical بالصفحة، والثالثة 404",
              p1["pages"] == 2 and 'rel="next"' in p1["html"].decode() and 'rel="prev"' in p2["html"].decode() and p2["canonical"].endswith("/page/2/")
              and seo_pages.render_person(con, d, "actors", wm, tr_ar, st_small, 3) is None)
        con.execute("DELETE FROM seo_settings WHERE key='page_size'"); con.commit()
        # E) توحيد الشخص
        bc = q("SELECT p.id, p.name_norm, (SELECT external_id FROM external_id x WHERE x.entity='person' AND x.entity_id=p.id AND x.source='tmdb') FROM person p WHERE p.name_norm='bryan cranston'")
        check("E) Bryan Cranston من لوحة Xtream (بالاسم) ثم TMDB (بالمعرّف) ← صفٌّ واحد حمل المعرّف", len(bc) == 1 and bc[0][2] is not None, str(bc))
        check("مفتاح الاسم: ترتيبٌ وتشكيلٌ وفاصلة عليا لا تفرّق", M.person_key("Miller, Wentworth") == M.person_key("Wentworth Miller") and M.person_key("O'Neil") == M.person_key("ONeil"))
        pq = seo_sources.people_qa(con, st2)
        check("إحصاء الشبكة: كل تشابه أسماءٍ بلا معرّفات مميِّزة له بند person_same_name (لا دمج تلقائي)، وأدوار writer/screenwriter/creator منفصلة، والعيّنة تحمل الإحصاء",
              pq["same_name_rows_without_distinct_tmdb_ids"] == pq["same_name_reviews_open"] and {"writer", "screenwriter", "creator", "actor", "director"} <= set(pq["by_role"]) and "persons" in smp["people"], str(pq))
        # الاسم وحده لا يدمج: «John Smith» من اللوحة في عملين مختلفين بلا TMDB ← صفّان وبند مراجعة
        dummies = []
        for i in (1, 2):
            dummies.append(con.execute("INSERT INTO content(type, slug, title, created_at, updated_at) VALUES ('series', ?, ?, 1, 1)", (f"dedup-test-{i}", f"Dedup Test {i}")).lastrowid)
            seo_sources._people_xtream(con, dummies[-1], {"cast": "John Smith, Someone Else", "director": ""}, 1000 + i)
        con.commit()
        js = q("SELECT id FROM person WHERE name_norm='john smith'")
        seo_sources.review_same_names(con); con.commit()
        check("PEOPLE DEDUP: شخصان بالاسم نفسه بلا معرّف TMDB في عملين ← صفّان لا يُدمجان، وبند person_same_name مفتوح لهما",
              len(js) == 2 and q("SELECT 1 FROM review WHERE key='person_same_name:john smith' AND status='open'"), str(js))
        seo_sources._people_xtream(con, dummies[0], {"cast": "John Smith", "director": ""}, 1003); con.commit()
        check("وإعادة الإثراء للعمل نفسه تعيد استعمال صفّه لا تُنشئ ثالثًا، وتحذف الاسم اليتيم", len(q("SELECT id FROM person WHERE name_norm='john smith'")) == 2 and not q("SELECT 1 FROM person WHERE name='Someone Else' AND id NOT IN (SELECT person_id FROM content_person)"))
        # مرشّحٌ غير محسوم: «One Piece» على كاسبر في قسم NETFLIX بموسمين من 8 — الأدلّة القوية متعادلة؛ بنية المواسم ترجّح 2023 ولا تعتمد
        up = next((w for w in smp["works"] if w["title"] == "One Piece" and w["match"] == "local"), None)
        rs_ = up and up["resolution_state"]
        check("CASPER ONE PIECE: unresolved_candidate بأدلّة كل مرشّح ومن يحمل معرّفه، likely = 2023 (بنية المواسم 2×8) بلا اعتماد، وغير قابل للفهرسة",
              rs_ and rs_["state"] == "unresolved_candidate" and rs_["likely"] == 111110 and {c["id"] for c in rs_["candidates"]} == {37854, 111110}
              and all(c["held_by_entity"] for c in rs_["candidates"]) and all(c["evidence"] for c in rs_["candidates"]) and rs_["indexable"] is False and up["page"]["ar"]["would_index"] is False,
              json.dumps(rs_, ensure_ascii=False))
        # F) الحلقات
        stub = next(w for w in smp["works"] if w.get("tmdb_id") == 99009)
        check("F) سجلّ TMDB ناقص (حلقة واحدة) لعملٍ بـ 54 في القوائم: الصفحة لا تعرض 1 رسميًّا بل «54 في القوائم»، والحقول منفصلة",
              stub["episodes"]["official_episode_count"] == 1 and stub["episodes"]["available_episode_count"] == 54 and "54 حلقة مدرجة على كاسبر" in stub["page"]["ar"]["meta_description"]
              and stub["episodes"]["seo_uses"].startswith("official"), stub["page"]["ar"]["meta_description"])
        pbe = pbw["episodes"]
        check("الحقول النهائية منفصلة: official/available/service/record(by source)/special، والسجلات بمصدرها",
              {"official_episode_count", "official_season_count", "available_episode_count", "available_season_count", "service_episode_count", "season_episode_count",
               "episode_record_count", "episode_records_by_source", "special_episode_count"} <= set(pbe) and pbe["episode_records_by_source"].get("tmdb", 0) >= 1, str(pbe))
        # G) البحث
        idx = seo_search.load(con)
        ex = lambda s_: seo_search.explain(con, idx, s_, st2)   # noqa: E731
        r = ex("Prison Break")
        check("G) «Prison Break» ← كيانٌ واحد", r["result"] == "entity" and len(r["entities"]) == 1, str(r)[:200])
        vs = {s_: ex(s_) for s_ in ("Prison Brek", "person break", "بريزن بريك", "بريزون بريك")}
        check("«Prison Brek» و«person break» و«بريزن بريك» و«بريزون بريك» ← اقتراحٌ واحد (0.95) للكيان نفسه",
              all((x["result"] == "suggest" and len(x["suggest"]) == 1 and x["suggest"][0]["id"] == live[0][0]) or (x["result"] == "entity" and [e_["id"] for e_ in x["entities"]] == [live[0][0]]) for x in vs.values()),
              str({k: (v["result"], [(s["id"], s["slug"], s["confidence"]) for s in v.get("suggest", [])]) for k, v in vs.items()}))   # «بريزون بريك» ترجمة TMDB نفسها ← الكيان مباشرة
        r = ex("One Piece")
        ids_ = {e_["identity"]: e_.get("tmdb_id") for e_ in r["entities"]}
        check("«One Piece» ← ثلاثة كيانات بهويتها الصريحة: 1999 = 37854 verified · 2023 = 111110 verified · كاسبر unresolved_candidate (لا يوحي البحث أنها عملٌ واحد)",
              r["result"] == "entity" and len(r["entities"]) == 3 and {e_["tmdb_id"] for e_ in r["entities"] if e_["identity"] == "verified"} == {37854, 111110} and "unresolved_candidate" in ids_, str(r)[:400])
        r = ex("ون بيس")
        check("«ون بيس» ← alias من ترجمة TMDB على العملين (الأنمي والحيّ يحملان الاسم العربي نفسه): كيانان مجمّعان بسبب «different tmdb ids»، لا كيان «ون بيس» مستقل",
              r["result"] == "entity" and {x["id"] for x in r["entities"]} == {op[0][0], op[1][0]} and r["grouped"][0]["why_separate"] == ["different tmdb ids"], str(r)[:300])
        r = ex("وان بيس")
        check("«وان بيس» ← اقتراحٌ صوتي للكيانين المُتحقَّقين وغير المحسوم بهويته", r["result"] == "suggest" and {op[0][0], op[1][0]} <= {x["id"] for x in r["suggest"]} and all("identity" in x for x in r["suggest"]), str(r)[:200])
        sr = pbw["service_rows"]; cl = pbw["same_service_rows"]
        check("SOURCE ROWS: Prison Break صفوفه بهوية كل صفّ (السيرفر، اللوحة، المفتاح، أرقام البثّ، القسم، الأسماء الخام)، وفالكون بصفّين من قسمين مختلفين مصنَّفين different_sections لا تكرارًا",
              len([r for r in sr if r["present"]]) == 3 and all(k in sr[0] for k in ("panel", "local_key", "stream_ids", "sections", "raw_names")) and cl.get("falcon") == "different_sections"
              and {r["stream_ids"][0] for r in sr if r["service"] == "falcon"} == {70, 71}, str((sr, cl)))
        sra = smp["source_rows"]
        check("تدقيق صفوف المصدر في القاعدة كلها: العدد بالتصنيف وبالسيرفر، وأمثلة بصفوفها، وتعريفات وآثار", sra["entities_with_multiple_rows_per_service"] >= 1 and "different_sections" in sra["by_class"]
              and sra["examples"] and "effects" in sra, str({k: v for k, v in sra.items() if k != "examples"}))
        r_ = seo_search.explain(con, seo_search.load(con), "Prison Break", st2)["entities"][0]
        check("البحث: كل سيرفر مرةً واحدة بعدد صفوفه ونسخه (smart 1، falcon 2) إلى جانب الصفوف الخام", [(s_["service"], s_["rows"]) for s_ in r_["services"]] == [("casper", 1), ("falcon", 2)] or [(s_["service"], s_["rows"]) for s_ in r_["services"]] == [("falcon", 2), ("casper", 1)], str(r_["services"]))
        pbp = pbw["page"]["ar"]["meta_description"]
        pbh = seo_pages.render_entity(con, d, "series", live[0][1], tr_en, st2)[1]["html"].decode()
        check("PRISON BREAK SEO: الخاصة تظهر صفًّا مستقلًا «Specials: 2» ولا تُعدّ موسمًا؛ «6 seasons»-نمط (3 هنا) غائب من الصفحة كلها",
              "<dt>Specials</dt><dd>2</dd>" in pbh and "3 seasons" not in pbh and "3 مواسم" not in seo_pages.render_entity(con, d, "series", live[0][1], tr_ar, st2)[1]["html"].decode(), "")
        check("EPISODE SEMANTICS: Prison Break (موسمان + حلقتان خاصتان في TMDB): لا «3 seasons» في العنوان/الوصف/JSON-LD بل «2 seasons»؛ الخاصة حقلٌ مستقل؛ لا حقل seasons عام",
              "3 seasons" not in pbh and '"numberOfSeasons": 2' in pbh and pbe["official_season_count"] == 2 and pbe["special_season_count" if "special_season_count" in pbe else "official_season_count"] in (1, 2)
              and pbw["special_season_count"] == 1 and pbe["special_episode_count"] == 2 and pbe["episode_record_count"] == pbe["official_episode_count"] + 2 and "seasons" not in pbw, str({k: v for k, v in pbe.items() if k != "season_episode_count"}))
        check("Prison Break: المواسم بلا الموسم 0 (الخاصة) والرقم الرسمي في الوصف، وعدّ المتاح من القوائم وحدها", f"{tr_ar.count(pbe['official_season_count'] or 0, 'seasons')}" in pbp
              and pbe["available_season_count"] == len([k for k, v in pbe["season_episode_count"].items() if k != "0" and v["available"]]) and pbe["available_season_count"] == 2, str((pbp, pbe["season_episode_count"])))
        check("صفحات الأشخاص والشركات في العيّنة: كل فئة مفحوصة باللغتين (تُرسم، أعمالٌ وروابط، canonical، hreflang، schema، noindex، ترقيم)",
              smp["people_pages"] and all(c.get("renders") and c["links_to_works"] and c["breadcrumb"] and c["schema"] and c["noindex"] and c["paginated_ok"] for row in smp["people_pages"] for c in row["checks"].values()), str(smp["people_pages"])[:400])
        seo_db.set_setting(con, "preview", True); con.commit()
        snap_q = lambda: [con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("content", "content_service", "redirect", "review", "enrich_queue", "content_alias", "provenance")]   # noqa: E731
        s_before = snap_q()
        qa = seo_qa.run(d, {"movie": 2, "series": 3, "turkish": 1, "anime": 1}, probe={"casper": {"movie": {"error": "xtream 503", **seo_sources.classify_provider_error("xtream 503")}}},
                        sitemap_out=os.path.join(d, "sitemap-staging.xml"))
        qpb = next(w for w in qa["works"] if w["slug"] == live[0][1])
        qt = {t["test"]: t for t in qpb["tests"]}
        check("FINAL QA: Prison Break (فالكون صفّان) — كيانٌ واحد، رابطٌ ثابت، canonical، عربي/إنجليزي، hreflang متبادل، schema، التوفّر بلا تكرار، فالكون مرةً واحدة، لا روابط مكرّرة، noindex",
              all(t["ok"] for t in qt.values()) and qt["falcon_once"]["detail"] and '"falcon_rows": 2' in qt["falcon_once"]["detail"], str([t for t in qt.values() if not t["ok"]])[:500])
        check("FINAL QA: العيّنة بمجموعاتها، كل الاختبارات ناجحة، ولا blocker", qa["ok"] and qa["tests"]["fail"] == 0 and qa["sample"]["by_group"]["series"] == 3 and qa["blockers"] == [], str((qa["tests"], qa["blockers"]))[:600])
        rd = qa["redirects"]
        check("FINAL QA: التحويلات كلها مباشرة إلى صفحةٍ حيّة (سلاسل 0)، تُخدم 301 باللغتين، ولم يُنشأ تحويلٌ جديد", rd["chains"] == 0 and rd["targets_not_live"] == 0 and rd["served_direct"] == rd["served_checked"] >= 4 and rd["created_during_qa"] == 0, str(rd)[:400])
        sm = qa["sitemap"]
        check("FINAL QA: خريطة الموقع التجريبية في ملفٍ لا يُخدم: canonical فقط، لا تكرار، لا استعلامات/تصفّح، لا مسارات تحويل، وتعدّ الكيانات المستحقّة باللغتين",
              os.path.exists(os.path.join(d, "sitemap-staging.xml")) and all(t["ok"] for t in sm["tests"]) and sm["urls"] >= 2 and sm["urls"] == sm["by_lang"]["ar"] + sm["by_lang"]["en"] and not sm["served"], str({k: v for k, v in sm.items() if k != "tests"})[:300])
        ix = qa["indexnow"]
        check("FINAL QA: IndexNow تجربةٌ بلا إرسال: لا طلب، الروابط على النطاق، والمفتاح لا يُولَّد في الفحص", not ix["sent"] and all(t["ok"] for t in ix["tests"]) and ix["key_present"] is False and ix["payload_preview"]["urlList_count"] == sm["urls"], str(ix)[:300])
        check("FINAL QA: لا أخطاء rps جديدة، وكاسبر 503 = provider_unavailable بلا غيابٍ ولا دمج، والفحص قراءةٌ صرفة (الأعداد قبل = بعد)",
              qa["queue"]["new_rps_errors_since_last_bundle"] == 0 and all(t["ok"] for t in qa["casper"]["tests"]) and qa["read_only"]["ok"] and snap_q() == s_before, str((qa["queue"], qa["casper"], s_before, snap_q()))[:400])
        con.close()
        _write(d, "falcon", cat)                                   # إعادة بناء بلا تغيير في القوائم: الهوية المُتحقَّقة تثبت
        r3 = seo_build.build(d, force=True)
        con = seo_db.connect(d)
        pb3 = q("SELECT id, merged_into FROM content WHERE title='Prison Break' ORDER BY id")
        check("هوية TMDB المُتحقَّقة لا تُفكّ: إعادة البناء لا تنتزع فالكون من Prison Break (لا كيان رابع، لا انقسام، لا تحويل جديد)، والتسوية تعدّ ما ثُبّت",
              len(pb3) == 3 and r3["split"] == 0 and r3["reconciliation"]["kept_by_verified_identity"] >= 1 and not q("SELECT 1 FROM review WHERE kind='split_entity' AND status='open' AND payload_json LIKE '%Prison Break%'"),
              str((pb3, r3["split"], r3["reconciliation"].get("kept_by_verified_identity"))))
        con.close()
    finally:
        xt.shutdown(); tm.shutdown()
        shutil.rmtree(d, ignore_errors=True)


def unit_enrich():
    """الإثراء من Xtream وTMDB (وهميّان، بلا إنترنت): المرشّح يُتحقَّق منه، والتصنيف، والأشخاص، والحلقات، والنافذة،
    والتباعد، والكاش — وجودة البحث على الأسماء المطلوبة."""
    print("== الإثراء والتصنيف والبحث ==")
    xt = mock_xtream.serve(0); tm = mock_tmdb.serve(0)
    xbase, tbase = _serve(xt), _serve(tm)
    seo_sources.TMDB_API = tbase + "/3"
    os.environ["TMDB_API_KEY"] = ""
    d = tempfile.mkdtemp(prefix="seo_enr_")
    try:
        os.makedirs(os.path.join(d, "content"))
        with open(os.path.join(d, "content", "settings.json"), "w", encoding="utf-8") as f:
            json.dump({"servers": [{"key": "smart", "name": "سمارت"}, {"key": "casper", "name": "كاسبر"}]}, f, ensure_ascii=False)
        C.set_url(d, "smart", f"{xbase}/get.php?username=u&password=p&type=m3u_plus")
        ok, err = C.refresh(d, "smart")
        check("سمارت يُسحب من اللوحة الوهمية (ومعرّفات TMDB في الفهرس)", ok, err)
        _write(d, "casper", _cat([{"n": "Dune", "y": 1984, "i": 11}, {"n": "Dune", "y": 2021, "i": 12, "p": TMDB + "d.jpg"}, {"n": "ون بيس فيلم ريد", "y": 2022, "i": 13}],
                                 [{"n": "طبيعة الحب مدبلج", "s": [[1, 39]], "i": 20, "p": "http://panel/tah.png"},
                                  {"n": "طبيعة الحب مترجم", "s": [[1, 39], [2, 12]], "i": 21, "p": "http://panel/tah.png"},
                                  {"n": "One Piece", "s": [[1, 61]], "i": 22}, {"n": "Prison Break", "y": 2005, "s": [[1, 22]], "i": 23},
                                  {"n": "The Office", "s": [[1, 6]], "i": 24}, {"n": "Attack on Titan", "s": [[1, 25]], "i": 25}],
                                 series2=[{"n": "Kuruluş Osman مترجم", "s": [[1, 27]], "i": 26, "p": "http://panel/ko.png"}]))
        res = seo_build.build(d)
        con = seo_db.connect(d)
        q = lambda sql, *a: con.execute(sql, a).fetchall()   # noqa: E731
        tah = q("SELECT id, slug, slug_source FROM content WHERE title='طبيعة الحب' AND merged_into IS NULL")
        vers = q("SELECT versions_json, raw_names_json FROM content_service WHERE content_id=?", tah[0][0]) if tah else []
        check("النسخ: «طبيعة الحب مدبلج» و«… مترجم» كيانٌ واحد (الصورة نفسها)، والنسختان على رابط السيرفر، والأسماء الخام aliases",
              len(tah) == 1 and vers and sorted(json.loads(vers[0][0])) == ["dubbed", "subbed"] and len(json.loads(vers[0][1])) == 2
              and {r[0] for r in q("SELECT alias FROM content_alias WHERE content_id=?", tah[0][0])} == {"طبيعة الحب", "طبيعة الحب مدبلج", "طبيعة الحب مترجم"},
              str([tuple(r) for r in tah]) + str([tuple(r) for r in vers]))
        check("slug منقحر مؤقتًا للعربي الأصيل، ومصدره مسجَّل", tah and tah[0][2] == "translit" and re.fullmatch(r"[a-z0-9-]+", tah[0][1]))
        ko = q("SELECT id, slug FROM content WHERE title='Kuruluş Osman'")
        check("لاحقة النسخة تُحذف من اسم لاتيني أيضًا، والslug بلا علامات", ko and ko[0][1] == "kurulus-osman", str([tuple(r) for r in ko]))
        gh = q("SELECT c.id, x.external_id, x.verified FROM content c JOIN external_id x ON x.entity='content' AND x.entity_id=c.id WHERE c.title='Game of Thrones'")
        check("معرّف اللوحة من القائمة (tmdb) مرشَّحٌ غير مُتحقَّق", gh and gh[0][1] == "1399" and gh[0][2] == 0, str([tuple(r) for r in gh]))
        hints = q("SELECT t.kind, t.key, ct.source FROM content_taxonomy ct JOIN taxonomy t ON t.id=ct.taxonomy_id JOIN content c ON c.id=ct.content_id WHERE c.title='المؤسس عثمان'")
        check("قرينة القسم «مسلسلات تركية مدبلجة» ← hint لا عضوية", sorted(tuple(r) for r in hints) == [("country", "TR", "hint"), ("hub", "turkish", "hint")], str(hints))
        qs = seo_sources.queue_stats(con)
        check("الطابور: xtream لمن له رابط (سمارت) وtmdb للكل، بانتظار النافذة", qs.get("tmdb", {}).get("pending", 0) >= 17 and qs.get("xtream", {}).get("pending", 0) >= 20, str(qs))
        st = seo_db.settings(con)
        import calendar
        noon = calendar.timegm((2026, 10, 2, 9, 0, 0))        # 12:00 بتوقيت السعودية
        night = calendar.timegm((2026, 10, 2, 0, 30, 0))      # 03:30 بتوقيت السعودية
        check("النافذة: 02:00–06:00 بتوقيت السعودية", seo_sources.window_open(st, now=noon) is False and seo_sources.window_open(st, now=night) is True)
        r = seo_sources.run(d, force=False, now=noon)
        check("خارج النافذة لا يعمل بلا force", r["processed"] == 0 and r["window"] is False, str(r))
        check("بلا مفتاح TMDB: يُتخطّى بلا عدّه فشلًا", seo_sources.run(d, limit=3, force=True)["skipped"] >= 1)
        seo_sources.set_tmdb_key(con, d, "testkey"); con.commit()
        check("المفتاح مشفَّر في القاعدة ومقنَّع في الإحصاءات", seo_db.settings(con)["tmdb_key"] != "testkey" and seo_sources.tmdb_key(con, d) == "testkey"
              and seo_build.stats(d)["settings"]["tmdb_key"] == "•••")
        con.close()
        r = seo_sources.run(d, limit=200, force=True)
        con = seo_db.connect(d)
        check("دفعة كاملة بالقوة", r["processed"] >= 20 and r["error"] == 0, str(r))
        pb = q("SELECT c.id, c.tmdb_id, c.match, c.title_ar, c.title_en, c.overview_ar, c.status, c.slug, c.format FROM content c WHERE c.slug='prison-break'")[0]
        check("Prison Break: TMDB مُتحقَّق، عنوانٌ عربي وقصة عربية، ومنتهٍ", tuple(pb[1:4]) == (2288, "tmdb", "بريزون بريك") and pb[5].startswith("قصة") and pb[6] == "Ended" and pb[8] == "")
        people = q("SELECT p.name, cp.role, cp.character FROM content_person cp JOIN person p ON p.id=cp.person_id WHERE cp.content_id=? ORDER BY cp.role, cp.ord", pb[0])
        check("الأشخاص من TMDB: ممثلان بشخصيتيهما ومبتكر وكاتب", [(r[0], r[1]) for r in people] == [("Wentworth Miller", "actor"), ("Dominic Purcell", "actor"), ("Paul Scheuring", "creator"), ("Some Writer", "writer")], str([tuple(r) for r in people]))
        op = q("SELECT format, anime_kind, status FROM content WHERE slug='one-piece'")[0]
        tax = {f"{r[0]}:{r[1]}" for r in q("SELECT t.kind, t.key FROM content_taxonomy ct JOIN taxonomy t ON t.id=ct.taxonomy_id JOIN content c ON c.id=ct.content_id WHERE c.slug='one-piece' AND ct.source='tmdb'")}
        check("One Piece: أنمي ياباني (format + anime_kind) في هب الأنمي، مستمر، بالاستوديو والنوع والسنة واللغة والبلد",
              tuple(op) == ("anime_series", "japanese", "Returning Series") and {"hub:anime", "anime_kind:japanese", "country:JP", "language:ja", "year:1999", "genre:16", "studio:tmdb:3785400"} <= tax, str(tax))
        ko = q("SELECT slug, slug_source, title_ar, title_en FROM content WHERE tmdb_id=89456")[0]
        tax = {f"{r[0]}:{r[1]}:{r[2]}" for r in q("SELECT t.kind, t.key, ct.source FROM content_taxonomy ct JOIN taxonomy t ON t.id=ct.taxonomy_id JOIN content c ON c.id=ct.content_id WHERE c.tmdb_id=89456")}
        check("المؤسس عثمان (قسم تركي، اسم عربي) ← TMDB عبر البحث العربي: هب التركي مؤكّدًا (tmdb) بعد القرينة (hint)",
              "hub:turkish:tmdb" in tax and "country:TR:tmdb" in tax and ko[2] == "المؤسس عثمان" and ko[3] == "Kuruluş Osman", str(tax))
        check("ترقية الرابط: من النقحرة إلى الاسم الإنجليزي (kurulus-osman-2019 لأن kurulus-osman مأخوذ) مع 301",
              ko[0] == "kurulus-osman-2019" and ko[1] == "en" and q("SELECT target FROM redirect WHERE path LIKE '/content/series/%'")
              and all(r[0] == "/content/series/kurulus-osman-2019/" for r in q("SELECT target FROM redirect WHERE path NOT LIKE '/en/%' AND target LIKE '%kurulus%'")), str(tuple(ko)))
        tah = q("SELECT tmdb_id, title_en, slug FROM content WHERE title='طبيعة الحب' AND merged_into IS NULL")[0]
        check("طبيعة الحب ← Love Is in the Air عبر بديل العنوان العربي، والرابط إنجليزي", tah[0] == 120089 and tah[2] == "love-is-in-the-air", str(tuple(tah)))
        bb = q("SELECT c.tmdb_id, c.match FROM content c WHERE c.title='Breaking Bad'")[0]
        check("معرّف اللوحة الخاطئ (999999) رُفض بالتحقّق واعتُمد البحث (1396)", tuple(bb) == (1396, "tmdb"), str(tuple(bb)))
        off = q("SELECT tmdb_id FROM content WHERE title='The Office'")[0]
        rv = q("SELECT kind, payload_json FROM review WHERE kind='tmdb_ambiguous' AND status='open'")
        check("The Office: مرشّحان قويان (US وUK) ← مراجعة لا تخمين", off[0] is None and len(rv) == 1 and len(json.loads(rv[0][1])["candidates"]) == 2)
        dn = q("SELECT year, tmdb_id, slug FROM content WHERE title='Dune' ORDER BY year")
        check("Dune 1984 → 841 وDune 2021 → 438631 بالسنة (slug لكلٍّ)", [tuple(r[:2]) for r in dn] == [(1984, 841), (2021, 438631)] and dn[0][2] != dn[1][2], str([tuple(r) for r in dn]))
        opr = q("SELECT slug, tmdb_id, format FROM content WHERE tmdb_id=900001")
        check("«ون بيس فيلم ريد» (عربي) ← One Piece Film: Red فيلم أنمي، slug إنجليزي", opr and opr[0][0] == "one-piece-film-red" and opr[0][2] == "anime_movie", str(opr))
        gh = q("SELECT c.id, c.tmdb_id FROM content c WHERE c.title='Game of Thrones'")[0]
        eps = q("SELECT season, number, title_en, overview_en FROM episode WHERE content_id=? ORDER BY season, number", gh[0])
        check("حلقات من TMDB (بعد مواسمه) بعناوين وملخصات", gh[1] == 1399 and len(eps) >= 8 and all(e[2] and e[3] for e in eps), str(len(eps)))
        pv = seo_db.provenance(con, "content", gh[0])
        check("المصدر: القصة من TMDB فوق Xtream فوق الفهرس، والقيمة السابقة محفوظة",
              pv["overview_en"][0] == "tmdb" and pv["overview"][0] in ("xtream", "m3u")
              and q("SELECT prev FROM provenance WHERE entity='content' AND entity_id=? AND field='poster'", gh[0])[0][0] is not None, str({k: v[0] for k, v in pv.items()}))
        xp = q("SELECT COUNT(*) FROM content_person WHERE source='xtream'")[0][0]
        check("أشخاص Xtream يبقون لمن لا TMDB له فقط", xp >= 0 and not q("SELECT 1 FROM content_person WHERE content_id=? AND source='xtream'", pb[0]))
        hits = len(mock_tmdb.Handler.hits)
        r = seo_sources.run(d, limit=200, force=True)
        check("لا تكرار: الدفعة التالية لا تطلب شيئًا جديدًا (الكاش والطابور)", len(mock_tmdb.Handler.hits) == hits and r["processed"] == 0, str(r))
        # التباعد عند تعطّل TMDB
        con.execute("UPDATE enrich_queue SET state='pending', next_at=0 WHERE content_id=? AND source='tmdb'", (off[0] if False else q("SELECT id FROM content WHERE title='The Office'")[0][0],))
        con.execute("DELETE FROM api_cache WHERE key LIKE 'tmdb:%'"); con.commit()
        tm.down = True
        r = seo_sources.run(d, limit=5, force=True)
        row = q("SELECT state, attempts, next_at, error FROM enrich_queue WHERE source='tmdb' AND attempts>0 AND state='pending' ORDER BY updated_at DESC LIMIT 1")
        check("تعطّل TMDB: خطأٌ مسجَّل ومحاولةٌ لاحقة بعد ساعة (backoff)", r["error"] >= 1 and row and row[0][2] > time.time() + 3000 and "503" in (row[0][3] or ""), str([tuple(x) for x in row]))
        tm.down = False
        # جودة البحث
        idx = seo_search.load(con)
        ex = lambda s: seo_search.explain(con, idx, s, st)   # noqa: E731
        pbid = pb[0]
        check("بحث: Prison Break كيانٌ مباشر", ex("Prison Break")["result"] == "entity" and ex("Prison Break")["entities"][0]["id"] == pbid)
        check("بحث: «person break» اقتراح (صوتي) لا كيان", ex("person break")["result"] == "suggest" and ex("person break")["suggest"][0]["id"] == pbid and ex("person break")["suggest"][0]["why"] == "phonetic")
        check("بحث: «Prison Brek» اقتراح", ex("Prison Brek")["suggest"][0]["id"] == pbid)
        check("بحث: «بريزن بريك» اقتراحٌ صوتي، و«بريزون بريك» كيانٌ مباشر (ترجمة TMDB alias)",
              ex("بريزن بريك")["suggest"][0]["id"] == pbid and ex("بريزون بريك")["result"] == "entity" and ex("بريزون بريك")["entities"][0]["id"] == pbid)
        t1 = q("SELECT id FROM content WHERE title='طبيعة الحب' AND merged_into IS NULL")[0][0]
        check("بحث: «طبيعة الحب» و«… مدبلج» و«… مترجم» كلها الكيان نفسه بنسختيه", all(ex(s)["result"] == "entity" and ex(s)["entities"][0]["id"] == t1 for s in ("طبيعة الحب", "طبيعة الحب مدبلج", "طبيعة الحب مترجم"))
              and sorted(json.loads(ex("طبيعة الحب")["entities"][0]["versions"][0][1])) == ["dubbed", "subbed"])
        opid = q("SELECT id FROM content WHERE slug='one-piece'")[0][0]
        check("بحث: One Piece وون بيس (ترجمة TMDB) الكيان نفسه", ex("One Piece")["entities"][0]["id"] == opid and ex("ون بيس")["entities"][0]["id"] == opid)
        dune = {r[0]: r[1] for r in q("SELECT year, id FROM content WHERE title='Dune'")}
        hit = lambda s: (ex(s).get("entities") or ex(s).get("suggest") or [{}])[0].get("id")   # noqa: E731
        check("بحث: Dune 1984 وDune 2021 كيانان مختلفان", hit("Dune 1984") == dune[1984] and hit("Dune 2021") == dune[2021] and dune[1984] != dune[2021])
        bbid = q("SELECT id FROM content WHERE title='Breaking Bad'")[0][0]
        check("بحث: بريكنغ باد (صوتي) وبريكنج باد (ترجمة) → Breaking Bad", ex("بريكنج باد")["entities"][0]["id"] == bbid and ex("بريكنغ باد")["suggest"][0]["id"] == bbid)
        check("بحث: اسمٌ لا وجود له → لا شيء (لا كيان ولا دمج)", ex("xqzv plork")["result"] == "none")
        # صفحات المعاينة
        import seo_pages
        check("بلا معاينة: مسارات الطبقة 404", seo_pages.handle(d, "/content/series/prison-break/", "ar")[0] == 404
              and seo_pages.handle(d, "/content/casper", "ar") is None)
        seo_db.set_setting(con, "preview", True); con.commit()
        code, body, hdr = seo_pages.handle(d, "/content/series/prison-break/", "ar")
        html = body.decode()
        check("صفحة المسلسل (معاينة): 200 وnoindex وسمًا ورأسًا، canonical ذاتي، H1 واحد", code == 200 and hdr["X-Robots-Tag"] == "noindex"
              and 'name="robots" content="noindex, follow"' in html and 'rel="canonical" href="https://guide.ssouq.com/content/series/prison-break/"' in html and html.count("<h1") == 1)
        check("فيها: قصة H2، الأبطال بروابطهم، المواسم والحلقات، متوفر عبر كاسبر، الأسئلة الشائعة، TVSeries + BreadcrumbList + FAQPage",
              "<h2>قصة مسلسل" in html and "/content/people/actors/wentworth-miller/" in html and 'id="seasons"' in html and "متوفر عبر" in html
              and '"@type": "TVSeries"' in html and '"BreadcrumbList"' in html and '"FAQPage"' in html and 'utm_campaign=content-entity' in html)
        check("hreflang للغتين فقط إن استحقّت كلتاهما الفهرسة (Prison Break نعم)", 'hreflang="en" href="https://guide.ssouq.com/en/content/series/prison-break/"' in html)
        en = seo_pages.handle(d, "/en/content/series/prison-break/", "en")[1].decode()
        check("النسخة الإنجليزية: lang=en، العنوان الإنجليزي، Story of", 'lang="en" dir="ltr"' in en and "<h1" in en and "Story of Prison Break" in en)
        check("بلا شرطة أخيرة: 301 إليها", seo_pages.handle(d, "/content/series/prison-break", "ar")[:1] == (301,))
        check("الرابط القديم المنقحر لـ Kuruluş Osman يحوّل 301 إلى الإنجليزي", seo_pages.handle(d, "/content/series/kurulus-osman/", "ar")[0] == 301)
        check("كيانٌ مدمج يحوّل إلى الباقي", seo_pages.handle(d, "/content/series/" + q("SELECT slug FROM content WHERE merged_into IS NOT NULL LIMIT 1")[0][0] + "/", "ar")[0] == 301)
        hub = seo_pages.handle(d, "/content/turkish/", "ar")[1].decode()
        check("هب التركي: مقدمة، أقسام، CollectionPage + ItemList يشير إلى روابط الأعمال لا نسخها", "<h1>المسلسلات والأفلام التركية</h1>" in hub
              and '"CollectionPage"' in hub and '"ItemList"' in hub and "/content/series/kurulus-osman-2019/" in hub and 'class="intro"' in hub)
        an = seo_pages.handle(d, "/en/content/anime/", "en")[1].decode()
        check("هب الأنمي بالإنجليزية يضم One Piece وAttack on Titan وفيلم الأنمي", "/en/content/series/one-piece/" in an and "/en/content/series/attack-on-titan/" in an and "/en/content/movies/one-piece-film-red/" in an)
        check("page/1 يحوّل، وصفحةٌ خارج الحدّ 404، وقسمٌ فارغ 404", seo_pages.handle(d, "/content/anime/page/1/", "ar")[0] == 301
              and seo_pages.handle(d, "/content/anime/page/99/", "ar")[0] == 404 and seo_pages.handle(d, "/content/anime/genres/nope/", "ar")[0] == 404)
        pp = seo_pages.handle(d, "/content/people/actors/wentworth-miller/", "ar")[1].decode()
        check("صفحة الممثل: أعماله بروابطها وPerson schema", '"@type": "Person"' in pp and "/content/series/prison-break/" in pp)
        # قرارات ما بعد المرحلة 2: تركيا → الهب، لغاتٌ فعّالة، الإثراء التلقائي موقوف، العيّنة الحقيقية، البحث اقتراحًا لا كتابة
        check("‏/content/countries/turkey/ → 301 إلى هب التركي (باللغتين)", seo_pages.handle(d, "/content/countries/turkey/", "ar")[2]["Location"] == "/content/turkish/"
              and seo_pages.handle(d, "/en/content/countries/turkey", "en")[2]["Location"] == "/en/content/turkish/")
        check("لغةٌ غير فعّالة (fr) 404 حتى تُضاف إلى languages؛ والبادئة تُشتقّ من اللغة", seo_pages.handle(d, "/fr/content/turkish/", "fr")[0] == 404 and seo_db.lang_prefix("fr") == "/fr")
        seo_db.set_setting(con, "languages", ["ar", "en", "fr"]); con.commit()
        check("وبإضافتها تُخدم بلا ترحيل", seo_pages.handle(d, "/fr/content/turkish/", "fr")[0] == 200)
        seo_db.set_setting(con, "languages", ["ar", "en"]); con.commit()
        ct = q("SELECT lang, field, source FROM content_text WHERE entity='content' AND entity_id=? ORDER BY lang, field", pb[0])
        check("نصوص TMDB معكوسة في content_text (ar/en) بمصدرها — جاهزة لأي لغة", [tuple(r) for r in ct] == [("ar", "overview", "tmdb"), ("ar", "title", "tmdb"), ("en", "overview", "tmdb"), ("en", "title", "tmdb")], str([tuple(r) for r in ct]))
        seo_db.set_text(con, "content", pb[0], "tr", "title", "Büyük Kaçış", "manual"); con.commit()
        check("لغةٌ ثالثة تُخزَّن في content_text بلا عمود", seo_db.get_text(con, "content", pb[0], "tr", "title") == "Büyük Kaçış")
        before = {t: q(f"SELECT COUNT(*) FROM {t}")[0][0] for t in ("content", "content_alias", "redirect", "review", "content_text")}
        for s_ in ("person break", "بريزن بريك", "Prison Brek", "xqzv"):
            ex(s_)
        check("البحث اقتراحٌ فقط: لا كيان ولا alias ولا redirect ولا مراجعة تُكتب", {t: q(f"SELECT COUNT(*) FROM {t}")[0][0] for t in before} == before)
        con.execute("UPDATE enrich_queue SET state='pending', next_at=0 WHERE content_id=? AND source='tmdb'", (q("SELECT id FROM content WHERE title='The Office'")[0][0],)); con.commit()
        import calendar
        night = calendar.timegm((2026, 10, 2, 0, 30, 0))
        check("tick لا يثري شيئًا ما دام enrich_auto موقوفًا (ولو داخل النافذة)", seo_sources.tick(d) is None
              and q("SELECT state FROM enrich_queue WHERE content_id=? AND source='tmdb'", q("SELECT id FROM content WHERE title='The Office'")[0][0])[0][0] == "pending")
        seo_db.set_setting(con, "enrich_auto", True); con.commit()
        r = seo_sources.run(d, limit=5, force=False, now=night)
        check("وبتفعيله يعمل في النافذة", r["window"] is True and r["processed"] >= 1, str(r))
        seo_db.set_setting(con, "enrich_auto", False); con.commit()
        # حالات التصنيف في العيّنة: قسم «أنمي» يضم Batman Beyond (TMDB: رسوم أمريكية) → mismatch؛ قيامة أرطغرل (قسم تركي، بلا TMDB) → unconfirmed
        with open(os.path.join(d, "content", "casper.json"), encoding="utf-8") as f:
            cat = json.load(f)
        cat["series"].append({"id": "s9", "name": "Anime أنمي", "items": [{"n": "Batman Beyond", "y": 1999, "s": [[1, 13]], "i": 90}]})
        _write(d, "casper", cat)
        seo_build.build(d)
        smp = seo_sources.sample(d, {"movie": 2, "series": 2, "turkish": 3, "anime": 5})
        works = {w["title"]: w for w in smp["works"]}
        bb_ = works.get("Batman Beyond", {})
        check("عيّنة: Batman Beyond في قسم أنمي → TMDB يقول لا أنمي: اختلافٌ = مراجعة (لا اعتماد TMDB تلقائيًّا)، خارج الهب، والقسم hint",
              bb_.get("anime", {}).get("decision") == "review" and bb_["anime"]["confidence"] == "low" and bb_["anime"]["section"] is True
              and "taxonomy_mismatch" in bb_.get("reviews", []) and bb_.get("format") is None, str(bb_.get("anime")) + str(bb_.get("reviews")))
        check("وTMDB الذي خالف القسم لا يُعتمد في البُعد المختلَف عليه: لا يظهر Batman في هب الأنمي، ومعرّف TMDB نفسه مُتحقَّق",
              "batman-beyond" not in seo_pages.handle(d, "/en/content/anime/", "en")[1].decode() and bb_.get("tmdb_id") == 99002)
        er = works.get("قيامة أرطغرل", {})
        check("عيّنة: قيامة أرطغرل (قسم تركي، TMDB لم يحسم) → unconfirmed، confidence low، مراجعة taxonomy_unconfirmed، خارج الهب",
              er.get("turkish", {}).get("decision") == "unconfirmed" and er["turkish"]["confidence"] == "low" and "taxonomy_unconfirmed" in er.get("reviews", [])
              and "qyama" not in seo_pages.handle(d, "/content/turkish/", "ar")[1].decode(), str(er.get("turkish")) + str(er.get("reviews")))
        # لقطة المراجعة (bundle): probe وreport وsearch-report قراءة؛ sample وحده يثري؛ ختمٌ ولا أسرار؛ وتشغيلها مرتين بلا طلباتٍ جديدة
        snap = lambda: {t: q(f"SELECT COUNT(*) FROM {t}")[0][0] for t in ("content", "content_alias", "api_cache", "review", "enrich_queue", "provenance", "content_taxonomy")}   # noqa: E731
        s0 = snap(); h0 = len(mock_tmdb.Handler.hits); x0 = len(mock_xtream.Handler.hits)
        pr = seo_sources.probe(d, 3)
        check("probe قراءةٌ صرفة: يقرأ اللوحة (أو كاشها) ولا يكتب صفًّا واحدًا (ولا في api_cache)", snap() == s0 and pr["smart"]["movie"]["answered"] >= 1,
              f"before={s0} after={snap()} hits={len(mock_xtream.Handler.hits) - x0}")
        seo_build.report(d); __import__("seo_search").explain(con, seo_search.load(con), "person break", st)
        check("report وsearch-report قراءة", snap() == s0 and len(mock_tmdb.Handler.hits) == h0)
        outdir = tempfile.mkdtemp(prefix="bundle_")
        b1 = seo_sources.bundle(d, outdir, n=3)
        files = {n: open(os.path.join(outdir, n), encoding="utf-8").read() for n in ("probe.json", "sample.json", "report.txt", "search-report.txt", "qa.json")}
        check("الملفات مكتوبة ومختومة بالوقت ونسخة الكود (ومعها qa.json وخريطة الموقع التجريبية)", set(files) | {"sitemap-staging.xml"} == set(b1["files"]) and all('"generated_at"' in t and '"code_fingerprint"' in t for t in files.values()) and b1["code_fingerprint"]
              and os.path.exists(os.path.join(outdir, "sitemap-staging.xml")), str(b1["files"]))
        secs = ["testkey", "username=u", "password=p", xbase.split("//")[1]]
        check("لا مفتاح ولا بيانات دخول ولا مضيف لوحةٍ في أي ملف", not any(sc in t for sc in secs for t in files.values()), str([sc for sc in secs if any(sc in t for t in files.values())]))
        bid = b1["bundle_id"]
        check("اللقطة الواحدة: معرّف bundle_id واحد في الملفات الأربعة وbundle.json", bid and all(bid in t for t in files.values()) and bid in open(os.path.join(outdir, "bundle.json"), encoding="utf-8").read(), bid)
        real_sample = seo_sources.sample
        seo_sources.sample = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom in sample"))
        try:
            bx = seo_sources.bundle(d, outdir, n=3)
        finally:
            seo_sources.sample = real_sample
        fx = {n: open(os.path.join(outdir, n), encoding="utf-8").read() for n in seo_sources.BUNDLE_FILES}
        check("فشل العيّنة لا يترك ملفاتٍ من لقطةٍ سابقة: الخمسة بختم اللقطة الفاشلة نفسها، وsample.json يحمل الخطأ وتتبّعه، وbundle.json يسجّله",
              all(bx["bundle_id"] in t for t in fx.values()) and "boom in sample" in fx["sample.json"] and "traceback" in fx["sample.json"] and any(e["file"] == "sample.json" for e in bx["errors"]), str(bx["errors"])[:200])
        b1 = seo_sources.bundle(d, outdir, n=3)
        files = {n: open(os.path.join(outdir, n), encoding="utf-8").read() for n in ("probe.json", "sample.json", "report.txt", "search-report.txt")}
        s1 = snap(); h1 = len(mock_tmdb.Handler.hits)
        b2 = seo_sources.bundle(d, outdir, n=3)
        check("تشغيل bundle مرةً ثانية: لا طلبات TMDB جديدة (الكاش) ولا كيانات أو أسماء بديلة جديدة", len(mock_tmdb.Handler.hits) == h1
              and {k: v for k, v in snap().items() if k not in ("enrich_queue",)} == {k: v for k, v in s1.items() if k not in ("enrich_queue",)}, str((s1, snap())))
        smp2 = json.loads(files["sample.json"])
        check("عيّنة العيّنة: 30 عملًا على الأكثر هي كل ما أُثري، ولا فشل جزئي", len(smp2["ids"]) <= 30 and smp2["failures"] == [] and smp2["run"]["processed"] >= 0)
        ko_ = next((w for w in smp["works"] if w["tmdb_id"] == 89456), {})
        check("عيّنة: المؤسس عثمان → TMDB تركيا + قسم تركي: confirmed", ko_.get("turkish", {}).get("note") == "confirmed")
        op_ = works.get("One Piece", {})
        check("عيّنة: One Piece بلا قسم أنمي → TMDB وحده: أنمي ياباني بثقة عالية", op_.get("anime", {}).get("decision") == "anime" and op_["anime"]["section"] is False and op_["anime_kind"] == "japanese")
        check("تقرير العيّنة: الحقول المطلوبة لكل عمل والعدّادات وأداء الواجهات",
              all(k in bb_ for k in ("tmdb_id", "title_ar", "title_en", "original_title", "country", "language", "genres", "director", "cast", "poster", "backdrop",
                                     "special_season_count", "episodes_detailed", "aliases", "versions", "provenance", "page"))
              and {"seo_title", "meta_description", "canonical", "hreflang", "json_ld"} <= set(bb_["page"]["ar"])
              and {"high_confidence_matches", "needs_review", "no_tmdb", "conflicts", "turkish_confirmed", "anime_confirmed", "aliases", "versions", "data_errors"} <= set(smp["summary"])
              and "tmdb" in smp["api"] and smp["api"]["tmdb"]["n"] >= 1, str(list(bb_.keys()))[:300])
        rep = seo_pages.audit(d, 12)
        check("فحص العيّنة: كل الصفحات سليمة (status · canonical · hreflang · title · description · H1 · breadcrumb · schema · روابط · لا canonical مكرّر)",
              rep["pages"] >= 20 and rep["fail"] == 0, str({k: v for k, v in rep.items() if k != "results"}))
        why = {r["why"] for r in rep["results"] if not r["would_index"]}
        check("وسياسة الفهرسة تُقيَّم بسبب لكل صفحة (قصة قصيرة، غير مطابَق، أقل من 12)", why <= {"overview_ar < 120", "overview_en < 120", "unmatched", "items < 12"}, str(why))
        con.close()
    finally:
        xt.shutdown(); tm.shutdown()
        shutil.rmtree(d, ignore_errors=True)


def main():
    unit_match()
    unit_build()
    unit_ten()
    unit_production_cases()
    unit_sample2_cases()
    unit_sample3_cases()
    unit_identity_cases()
    unit_migrate()
    unit_enrich()
    live()
    print("\nResult: %d passed, %d failed" % (_p, _f))
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

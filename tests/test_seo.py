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
import content as C  # noqa: E402
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


def req(base, path, data=None, auth=None, host=None):
    r = urllib.request.Request(base + path, data=json.dumps(data).encode() if data is not None else None,
                               headers={**({"Authorization": auth} if auth else {}), **({"Host": host} if host else {}),
                                        **({"Content-Type": "application/json"} if data is not None else {})})
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
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
        na = q("SELECT slug, tmdb_id, match FROM content WHERE title='Narcos' AND merged_into IS NULL ORDER BY tmdb_id")
        check("4. نفس الاسم + TMDB IDs مختلفة → كيانان (بمعرّفيهما، match=xtream)",
              [tuple(r) for r in na] == [("narcos", 63351, "xtream"), ("narcos-2015", 73911, "xtream")]
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


def main():
    unit_match()
    unit_build()
    unit_ten()
    live()
    print("\nResult: %d passed, %d failed" % (_p, _f))
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

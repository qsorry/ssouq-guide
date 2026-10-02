#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
المكتبة الموحدة لحساب Stremio متعدد البوابات (‏stremio_library.py · stremio_addon): المطابقة (TMDB/IMDb ← الاسم + النوع +
السنة + الموسم ← الاسم بخطٍّ آخر بقرينة)، والدمج بلا تكرار، والبحث الموحد، وصفحة العمل بمصادره وحلقاتها، و«تلقائي» مع
الانتقال للمصدر التالي إن تعطّل، وتحديث المكتبة حين تتغيّر قوائم الخطوط — مقابل ثلاث لوحاتٍ وهمية (بلا إنترنت).

    python tests/test_stremio_library.py
"""
import json
import os
import shutil
import sys
import tempfile
import time
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import mock_panels as MP  # noqa: E402
import stremio_addon as S  # noqa: E402
import stremio_library as LIB  # noqa: E402

_p = _f = 0


def check(label, cond, extra=""):
    global _p, _f
    if cond:
        _p += 1
        print("  \033[32mPASS\033[0m  " + label + (("  (%s)" % extra) if extra else ""))
    else:
        _f += 1
        print("  \033[31mFAIL\033[0m  " + label + (("  (%s)" % extra) if extra else ""))


def L(kind, rows, cats=(("1", "مسلسلات تركية"), ("2", "مسلسلات مترجمة"))):
    """قائمةٌ من صفوفٍ مختصرة: (رقم، اسم، سنة، قسم[، إضافات])."""
    raw = []
    key = {"series": "series_id", "movie": "stream_id", "tv": "stream_id"}[kind]
    for r in rows:
        iid, name, year, cat = r[:4]
        d = {key: iid, "name": name, "category_id": cat, "last_modified": str(1000 - iid), "added": str(1000 - iid)}
        if year:
            d["releaseDate"] = f"{year}-01-01"
        if len(r) > 4:
            d.update(r[4])
        raw.append(d)
    return S.Lists(kind, [{"category_id": c, "category_name": n} for c, n in cats], raw)


def names(lib):
    return sorted(sorted(s.item.name for s in w.sources) for w in lib.works)


# ================= المطابقة والدمج (بلا شبكة) =================
def matching():
    print("== المفاتيح ==")
    check("الموسم بالعربية والإنجليزية صفةٌ لا هوية", LIB.season_of("علي كارا الموسم الأول") == ("علي كارا", 1)
          and LIB.season_of("علي كارا - الموسم 3") == ("علي كارا", 3) and LIB.season_of("Ali Kara Season 2") == ("Ali Kara", 2)
          and LIB.season_of("الجزء الثاني عشر") == ("الجزء الثاني عشر", 0) and LIB.season_of("Squid Game") == ("Squid Game", 0))
    check("الجودة من الاسم أو القسم", LIB.quality_of("beIN 1 FHD") == "FHD" and LIB.quality_of("X", "أفلام 4K") == "4K"
          and LIB.quality_of("Movie 720p") == "HD" and LIB.quality_of("HDTV Show") == "" and LIB.quality_of("Plain") == "")
    k = LIB.item_key(S.Item(1, "Ali Kara - Arabic Sub", "", "2", 0, None, "", "", "2024", ""), "مسلسلات مترجمة")
    check("«مترجم» «Arabic Sub» تُحذف من مفتاح المطابقة وحده وتصير نسخة المصدر", k.nkey == "ali kara" and k.versions == ("subbed",)
          and k.pkey == "l kr" and k.year == 2024, str(k))
    k2 = LIB.item_key(S.Item(2, "علي كارا", "", "1", 0, None, "", "", None, ""), "مسلسلات تركية مدبلجة")
    check("ونسخة القسم («… مدبلجة»)", k2.versions == ("dubbed",) and k2.pkey == "l kr")

    print("== أسماء البوابات المختلفة للعمل نفسه ==")
    smart = L("series", [(1, "علي كارا", 2024, "1"), (2, "Squid Game", 0, "1"), (3, "علي كارا مدبلج", 2024, "1")])
    casper = L("series", [(11, "علي كارا (مترجم)", 2024, "2"), (12, "Squid Game (2021)", 0, "1"), (13, "Dune", 1984, "1")])
    falcon = L("series", [(21, "Ali Kara - Arabic Sub", 2024, "2"), (22, "علي كارا الموسم الأول", 0, "1"),
                          (23, "Dune", 2021, "1"), (24, "Ali Kara", 0, "1")])
    parts = [(0, "aaaaaa", "سمارت", smart), (1, "bbbbbb", "كاسبر", casper), (2, "cccccc", "فالكون", falcon)]
    lib = LIB.build("series", parts)
    ali = next(w for w in lib.works if "علي كارا" in w.name)
    check("علي كارا / علي كارا مدبلج / (مترجم) / Ali Kara - Arabic Sub / الموسم الأول / Ali Kara ← عملٌ واحد",
          sorted(s.item.name for s in ali.sources) == sorted(["علي كارا", "علي كارا مدبلج", "علي كارا (مترجم)", "Ali Kara - Arabic Sub",
                                                               "علي كارا الموسم الأول", "Ali Kara"]), str(names(lib)))
    check("واسمه المعروض بلا لاحقة، والاسم الأصلي لكل مصدرٍ محفوظٌ فيه", ali.name == "علي كارا"
          and {s.item.name for s in ali.sources if s.label == "فالكون"} == {"Ali Kara - Arabic Sub", "علي كارا الموسم الأول", "Ali Kara"})
    check("وكل مصدرٍ بنسخته وموسمه", {(s.item.name, s.key.versions, s.key.season) for s in ali.sources} >=
          {("علي كارا (مترجم)", ("subbed",), 0), ("علي كارا مدبلج", ("dubbed",), 0), ("علي كارا الموسم الأول", (), 1)})
    check("المصادر بترتيب الخطوط (صاحب الحساب أولًا) والمرساة منه", [s.label for s in ali.sources][:2] == ["سمارت", "سمارت"]
          and ali.anchor.item.id == 1 and ali.labels == ["سمارت", "كاسبر", "فالكون"])
    check("بلا سنةٍ في طرف: الاسم المطبَّع يكفي («Squid Game» = «Squid Game (2021)»)",
          ["Squid Game", "Squid Game (2021)"] in names(lib))
    check("سنتان مختلفتان ← عملان («Dune» 1984 و2021)", ["Dune"] in names(lib) and sum(1 for n in names(lib) if n == ["Dune"]) == 2)
    check("بلا تكرار: كل مصدرٍ في عملٍ واحد", sum(len(w.sources) for w in lib.works) == 10
          and len({(s.hk, s.item.id) for w in lib.works for s in w.sources}) == 10 and len(lib.works) == 4, str(len(lib.works)))
    check("البحث بأي خطّ يجد العمل مرةً واحدة", [w.name for w in lib.search("Ali Kara")] == ["علي كارا"]
          and [w.name for w in lib.search("علي كارا")] == ["علي كارا"] and [w.name for w in lib.search("مترجم")] == ["علي كارا"])
    check("وبالمفتاح الصوتي: «Alee Kara» يجد «علي كارا»", [w.name for w in lib.search("Alee Kara")] == ["علي كارا"])

    print("== لا دمج بلا تأكّد ==")
    a = LIB.build("series", [(0, "aaaaaa", "سمارت", L("series", [(1, "علي كارا", 0, "1")])),
                             (1, "bbbbbb", "فالكون", L("series", [(2, "Ali Kara", 0, "1")]))])
    check("الاسم بخطٍّ آخر بلا قرينة (بلا سنةٍ ولا ملصق) ← عملان", len(a.works) == 2, str(names(a)))
    b = LIB.build("series", [(0, "aaaaaa", "سمارت", L("series", [(1, "علي كارا", 2023, "1")])),
                             (1, "bbbbbb", "فالكون", L("series", [(2, "Ali Kara", 2024, "1")]))])
    check("وسنتان مختلفتان ← عملان", len(b.works) == 2)
    poster = {"cover": "https://image.tmdb.org/t/p/w600/abcDEF123.jpg"}
    c = LIB.build("series", [(0, "aaaaaa", "سمارت", L("series", [(1, "علي كارا", 0, "1", poster)])),
                             (1, "bbbbbb", "فالكون", L("series", [(2, "Ali Kara", 0, "1", poster)]))])
    check("وملف ملصق TMDB نفسه قرينةٌ كافية", len(c.works) == 1)
    tm = LIB.build("series", [(0, "aaaaaa", "سمارت", L("series", [(1, "La Casa de Papel", 2017, "1", {"tmdb": "71446"}),
                                                                   (2, "Lupin", 2021, "1", {"tmdb": "96677"})])),
                              (1, "bbbbbb", "كاسبر", L("series", [(5, "Money Heist", 2017, "1", {"tmdb": "71446"}),
                                                                   (6, "Lupin", 2021, "1", {"tmdb": "111"})]))])
    check("معرّف TMDB نفسه ← عملٌ واحد مهما اختلف الاسم، ومختلفان ← عملان مهما تطابق الاسم",
          ["La Casa de Papel", "Money Heist"] in names(tm) and ["Lupin"] in names(tm) and len(tm.works) == 3, str(names(tm)))
    im = LIB.build("movie", [(0, "aaaaaa", "سمارت", L("movie", [(1, "الأب الروحي", 1972, "1", {"imdb_id": "tt0068646"})])),
                             (1, "bbbbbb", "كاسبر", L("movie", [(2, "The Godfather", 1972, "1", {"imdb": "tt0068646"})]))])
    check("ومعرّف IMDb كذلك", len(im.works) == 1)
    amb = LIB.build("movie", [(0, "aaaaaa", "سمارت", L("movie", [(1, "Dune (1984)", 0, "1"), (2, "Dune", 0, "1")])),
                              (1, "bbbbbb", "كاسبر", L("movie", [(3, "Dune (2021)", 0, "1")]))])
    check("«Dune» بلا سنة بين «Dune 1984» و«Dune 2021» يبقى وحده (لا يُخمَّن لأيّهما)", len(amb.works) == 3, str(names(amb)))
    sp = LIB.build("series", [(0, "aaaaaa", "سمارت", L("series", [(1, "التفاح الحرام S05", 2022, "1"), (2, "التفاح الحرام S06", 2023, "1")])),
                              (1, "bbbbbb", "كاسبر", L("series", [(3, "التفاح الحرام", 2019, "1")]))])
    check("مواسم مفرّقة بسنواتها ← مسلسلٌ واحد", len(sp.works) == 1, str(names(sp)))
    mv = LIB.build("movie", [(0, "aaaaaa", "سمارت", L("movie", [(1, "Oppenheimer (2023)", 0, "1")])),
                             (1, "bbbbbb", "كاسبر", L("movie", [(2, "Oppenheimer - FHD", 0, "1"), (3, "اوبنهايمر (2023)", 0, "1")]))])
    w = mv.works[0]
    check("الأفلام: الجودة ليست من الهوية، والاسم المعروض بسنته", len(mv.works) == 1 and w.name == "Oppenheimer (2023)"
          and {s.key.quality for s in w.sources} == {"", "FHD"}, str(names(mv)))

    print("== القنوات ==")
    tv = LIB.build("tv", [(0, "aaaaaa", "سمارت", L("tv", [(1, "beIN SPORTS 1 HD", 0, "1"), (2, "beIN SPORTS 1 FHD", 0, "1"),
                                                           (3, "MBC 1", 0, "1")])),
                          (1, "bbbbbb", "كاسبر", L("tv", [(7, "beIN SPORTS 1", 0, "1"), (8, "SSC 1", 0, "1")]))])
    bein = tv.works[0]
    check("القناة نفسها بجوداتها وبواباتها ← قناةٌ واحدة بمصادرها، والجودة الأعلى أولًا في خطّها",
          len(tv.works) == 3 and bein.name == "beIN SPORTS 1" and [s.item.name for s in bein.sources] ==
          ["beIN SPORTS 1 FHD", "beIN SPORTS 1 HD", "beIN SPORTS 1"], str([s.item.name for s in bein.sources]))
    check("بترتيب السيرفر (لا بالأحدث)", [w.name for w in tv.latest] == ["beIN SPORTS 1", "MBC 1", "SSC 1"])


# ================= عبر الإضافة: ثلاث بوابات وهمية =================
def panels():
    smart, casper, falcon = MP.Panel("smart"), MP.Panel("casper", "cu", "cp"), MP.Panel("falcon", "fu", "fp")
    for p in (smart, casper, falcon):
        p.cat("series", 1, "مسلسلات تركية")
        p.cat("series", 2, "مسلسلات مترجمة")
        p.cat("vod", 10, "أفلام")
        p.cat("live", 20, "رياضة")
    smart.series = [{"series_id": 1, "name": "علي كارا", "category_id": "1", "releaseDate": "2024-09-01", "last_modified": "100",
                     "cover": "https://image.tmdb.org/t/p/w600/ali.jpg", "genre": "دراما"},
                    {"series_id": 2, "name": "Squid Game", "category_id": "1", "last_modified": "50"}]
    casper.series = [{"series_id": 11, "name": "علي كارا (مترجم)", "category_id": "2", "releaseDate": "2024", "last_modified": "90"},
                     {"series_id": 12, "name": "مسلسل كاسبر وحده", "category_id": "1", "last_modified": "40"}]
    falcon.series = [{"series_id": 21, "name": "Ali Kara - Arabic Sub", "category_id": "2", "releaseDate": "2024-02-02", "last_modified": "80"},
                     {"series_id": 22, "name": "علي كارا الموسم الثاني", "category_id": "1", "last_modified": "70"}]
    smart.episodes(1, {1: 3}, height=1080)
    smart.episodes(2, {1: 2})
    casper.episodes(11, {1: 4})
    casper.episodes(12, {1: 1})
    falcon.episodes(21, {1: 4})
    falcon.episodes(22, {1: 5})                    # مدخل الموسم الثاني ترقّم لوحته حلقاته موسمًا أول
    smart.vod = [{"stream_id": 101, "name": "Oppenheimer (2023)", "category_id": "10", "added": "100", "container_extension": "mkv",
                  "height": 2160}]                 # بلا جودةٍ في الاسم، والملف نفسه 4K (من تفاصيله)
    casper.vod = [{"stream_id": 201, "name": "Oppenheimer - FHD", "category_id": "10", "added": "90", "container_extension": "mp4"}]
    falcon.vod = [{"stream_id": 301, "name": "Oppenheimer (2023) مترجم", "category_id": "10", "added": "80", "container_extension": "mp4"}]
    smart.live = [{"stream_id": 501, "name": "beIN SPORTS 1 HD", "category_id": "20"}]
    casper.live = [{"stream_id": 601, "name": "beIN SPORTS 1 FHD", "category_id": "20"}]
    falcon.live = [{"stream_id": 701, "name": "beIN SPORTS 1", "category_id": "20"}]
    return smart, casper, falcon


def through_addon():
    S.reset()
    smart, casper, falcon = panels()
    s1, s2, s3 = MP.serve(smart), MP.serve(casper), MP.serve(falcon, bind="127.0.0.2")
    h1 = f"http://127.0.0.1:{s1.server_address[1]}"
    h2 = f"http://localhost:{s2.server_address[1]}"
    h3 = f"http://127.0.0.2:{s3.server_address[1]}"
    c1, c2, c3 = S.Cfg(h1, "u", "p"), S.Cfg(h2, "cu", "cp"), S.Cfg(h3, "fu", "fp")
    lines = [{"cfg": c1, "label": "سمارت"}, {"cfg": c2, "label": "كاسبر"}, {"cfg": c3, "label": "فالكون"}]
    pre = S.prefix(c1)
    d = tempfile.mkdtemp(prefix="stremio_lib_")
    try:
        print("== البناء المسبق ==")
        n_hits = len(smart.hits)
        check("لا يُبنى مسبقًا ما لم تكن قوائم خطوطه في الذاكرة (لا يسأل السيرفرات شيئًا جديدًا)",
              S.warm_library(lines) == 0 and len(smart.hits) == n_hits)
        for c in (c1, c2, c3):
            S.warm(c)
        check("وقوائمه في الذاكرة ← تُبنى مكتباته الثلاث", S.warm_library(lines) == 3)

        print("== الكتالوج الموحد ==")
        ser = S.lib_catalog(lines, "series", "sq_series", {}, pre)["metas"]
        check("مكتبةٌ واحدة: «علي كارا» مرةً واحدة من خمسة مداخل في ثلاث بوابات، والأحدث أولًا",
              [m["name"] for m in ser] == ["علي كارا", "Squid Game", "مسلسل كاسبر وحده"], str([m["name"] for m in ser]))
        ali = ser[0]
        check("معرّفه بصيغة خط صاحب الحساب القديمة (المكتبة و«تابع المشاهدة» كما هي)", ali["id"] == f"{pre}s:1", ali["id"])
        check("ومؤشّر المصادر في وصفه", ali["description"].endswith("المصادر: سمارت · كاسبر (مترجم) · فالكون (مترجم) ×2"), ali["description"])
        only = ser[2]
        check("وعملٌ في خطٍّ آخر وحده: معرّفه ببصمة سيرفره", only["id"] == f"{pre}ws:{S.line_hk(c2)}.12", only["id"])
        found = S.lib_catalog(lines, "series", "sq_series", {"search": "Ali Kara"}, pre)["metas"]
        check("البحث في كل الحسابات معًا: نتيجةٌ واحدة", [m["id"] for m in found] == [ali["id"]], str([m["name"] for m in found]))
        check("«مصدر: كاسبر» ← كل ما في كاسبر", [m["name"] for m in S.lib_catalog(lines, "series", "sq_series", {"genre": "مصدر: كاسبر"}, pre)["metas"]]
              == ["علي كارا", "مسلسل كاسبر وحده"])
        check("والقسم بعدده من أي بوابة", [m["name"] for m in S.lib_catalog(lines, "series", "sq_series", {"genre": "مسلسلات مترجمة (1)"}, pre)["metas"]]
              == ["علي كارا"])
        man = S.manifest(c1, "https://g", "سمارت", lines=lines)
        cat = {c["type"]: c for c in man["catalogs"]}
        opts = next(e["options"] for e in cat["series"]["extra"] if e["name"] == "genre")
        check("الـmanifest: الصفوف باسم المتجر وعدد الأعمال الموحدة، و«مصدر: …» لكل بوابة",
              cat["series"]["name"] == "سمارت سوق (3)" and cat["movie"]["name"] == "سمارت سوق (1)" and cat["tv"]["name"] == "سمارت سوق (1)"
              and opts[-3:] == ["مصدر: سمارت", "مصدر: كاسبر", "مصدر: فالكون"] and "مكتبةٌ واحدة" in man["description"], str(opts))
        same_pkg = [{"cfg": S.Cfg(h1, "u", "p", None), "label": "سمارت"}, lines[1], lines[2]]
        check("حسابان بالباقات نفسها يشتركان في مكتبةٍ واحدة", S.library(same_pkg, "series") is S.library(lines, "series"))
        shell = S.manifest(c2, "https://g", "كاسبر", accounts=False, catalogs=False)
        check("وإضافة الخط المرتبط بلا كتالوجات (تفاصيل ما في مكتبة Stremio ببادئتها تبقى)",
              shell["catalogs"] == [] and shell["resources"][1]["idPrefixes"] == [S.prefix(c2)])

        print("== صفحة العمل: مصادره وحلقاتها ==")
        m = S.lib_meta(lines, "series", ali["id"], "https://g/stremio/T/manifest.json", pre)["meta"]
        seasons = sorted({(v["season"], v["episode"]) for v in m["videos"]})
        check("الحلقات مرةً واحدة من كل المصادر، ومدخل «الموسم الثاني» بموسمه",
              seasons == [(1, e) for e in range(1, 5)] + [(2, e) for e in range(1, 6)] and len(m["videos"]) == 9, str(seasons))
        check("معرّف الحلقة الموحد", m["videos"][0]["id"] == f"{pre}we:{S.line_hk(c1)}.1:1:1", m["videos"][0]["id"])
        chips = [l["name"] for l in m["links"] if l["category"] == "المصادر"]
        check("المصادر روابطَ: البوابة ونسختها ومواسمها وحلقاتها (بمداخلها كلها)", chips == ["سمارت · S01 · 3 حلقات", "كاسبر · مترجم · S01 · 4 حلقات",
              "فالكون · مترجم · S01–S02 · 9 حلقات"], json.dumps(chips, ensure_ascii=False))
        check("والضغط على مصدرٍ ← كل ما فيه", m["links"][-1]["url"].endswith("/series/sq_series?genre=" + quote("مصدر: فالكون", safe="")))

        print("== التشغيل: «تلقائي» ثم كل مصدر ==")
        ep = f"{pre}we:{S.line_hk(c1)}.1:1:4"            # الحلقة الرابعة: في كاسبر وفالكون لا في سمارت
        play_url = "https://g/stremio/T/play/series/" + quote(ep, safe="")
        sts = S.lib_streams(lines, "series", ep, pre, play_url)["streams"]
        check("الحلقة في مصدرين: «تلقائي» أولًا ثم مصادرها وحدها", [x["name"] for x in sts] == ["سمارت سوق", "كاسبر", "فالكون"]
              and sts[0]["url"] == play_url, json.dumps([x["name"] for x in sts], ensure_ascii=False))
        check("وكل مصدرٍ باسمه الأصلي ونسخته ورقم الحلقة", sts[1]["title"].startswith("علي كارا (مترجم)\n") and "مترجم" in sts[1]["title"]
              and "S01E04" in sts[1]["title"] and sts[1]["url"] == f"{h2}/series/cu/cp/11104.mkv", sts[1]["title"] + " " + sts[1]["url"])
        e1 = S.lib_streams(lines, "series", f"{pre}we:{S.line_hk(c1)}.1:1:1", pre, "x")["streams"]
        check("الحلقة الأولى في الثلاثة: المترجمان أولًا ثم سمارت بجودة ملفّه (1080p من تفاصيله)",
              [x["name"] for x in e1] == ["سمارت سوق", "كاسبر", "فالكون", "سمارت"] and "FHD (1080p)" in e1[3]["title"],
              json.dumps([(x["name"], x["title"]) for x in e1], ensure_ascii=False))
        e2 = f"{pre}we:{S.line_hk(c1)}.1:2:3"
        st2 = S.lib_streams(lines, "series", e2, pre, "x")["streams"]
        check("حلقة الموسم الثاني من مدخل فالكون وحده: بلا «تلقائي»", [x["name"] for x in st2] == ["فالكون"]
              and st2[0]["url"] == f"{h3}/series/fu/fp/22103.mkv", json.dumps(st2, ensure_ascii=False)[:200])
        mv = S.lib_catalog(lines, "movie", "sq_movies", {}, pre)["metas"]
        check("الفيلم: عملٌ واحد من ثلاث بوابات", [x["name"] for x in mv] == ["Oppenheimer (2023)"])
        ms = S.lib_streams(lines, "movie", mv[0]["id"], pre, "auto")["streams"]
        check("ومصادره بالأفضل: الترجمة العربية (مترجم) ← الجودة الأعلى من الملف نفسه (4K) ← من الاسم (FHD)",
              [x["name"] for x in ms] == ["سمارت سوق", "فالكون", "سمارت", "كاسبر"] and ms[1]["url"].endswith("/movie/fu/fp/301.mp4")
              and ms[2]["url"].endswith("/movie/u/p/101.mkv") and "4K (2160p)" in ms[2]["title"] and "مترجم" in ms[1]["title"]
              and "FHD" in ms[3]["title"], json.dumps([(x["name"], x["title"]) for x in ms], ensure_ascii=False))
        lv = S.lib_catalog(lines, "tv", "sq_live", {}, pre)["metas"]
        ls = S.lib_streams(lines, "tv", lv[0]["id"], pre, "auto")["streams"]
        check("القناة: واحدةٌ بمصادرها الثلاثة (HLS وTS لكلٍّ)، والجودة الأعلى أولًا", len(lv) == 1 and lv[0]["name"] == "beIN SPORTS 1"
              and len(ls) == 1 + 6 and ls[1]["name"] == "كاسبر", json.dumps([x["name"] for x in ls], ensure_ascii=False))

        print("== الانتقال للمصدر التالي ==")
        mid = mv[0]["id"]
        falcon.dead.add(301)
        check("أفضل مصدرٍ معطّل (404) ← التالي", S.play(lines, "movie", mid, pre) == f"{h1}/movie/u/p/101.mkv")
        n = len(falcon.hits)
        S.play(lines, "movie", mid, pre)
        check("ونتيجة الفحص محفوظةٌ دقيقة (لا يُسأل المعطّل كل مرة)", len(falcon.hits) == n, f"{len(falcon.hits) - n} طلبات")
        S._probes.clear()
        s1.shutdown()
        s1.server_close()                                 # سيرفر سمارت سقط
        check("وسيرفرٌ ساقط ← الذي بعده", S.play(lines, "movie", mid, pre) == f"{h2}/movie/cu/cp/201.mp4")
        S._probes.clear()
        casper.dead.add(201)
        check("وكلها معطّلة ← الأول (يُظهر المشغّل خطأه)", S.play(lines, "movie", mid, pre) == f"{h3}/movie/fu/fp/301.mp4")
        S._probes.clear()
        falcon.dead.clear()
        casper.dead.clear()
        falcon.rejected = True                            # اشتراك فالكون انتهى
        with S._lock:
            S._accounts.clear()
        ms2 = S.lib_streams(lines, "movie", mid, pre, "auto")["streams"]
        check("اشتراكٌ منتهٍ: مصدره آخرًا وعليه تنبيه، و«تلقائي» يتخطّاه (وإن كان مترجمًا)", ms2[-1]["name"] == "فالكون"
              and ms2[-1]["title"].startswith("⚠️") and S.play(lines, "movie", mid, pre) == f"{h2}/movie/cu/cp/201.mp4",
              json.dumps([x["name"] for x in ms2], ensure_ascii=False))
        falcon.rejected = False
        with S._lock:
            S._accounts.clear()
        S._probes.clear()

        print("== عبر المسارات ==")
        tok = S.make_token(d, h1, "u", "p")
        s1b = MP.serve(smart, port=s1.server_address[1])  # سمارت عاد
        S._probes.clear()
        lf = lambda cfg: lines if S.host_key(cfg.host) == "127.0.0.1" else None
        code, body, _, hdr = S.handle(d, f"/stremio/{tok}/play/movie/{quote(mv[0]['id'], safe='')}", "https://g", lines_for=lf)
        check("‏/play ← تحويلٌ (302) إلى أول مصدرٍ يعمل", code == 302 and hdr["Location"] == f"{h3}/movie/fu/fp/301.mp4", str((code, hdr.get("Location"))))
        code, body, _, _ = S.handle(d, f"/stremio/{tok}/stream/movie/{quote(mv[0]['id'], safe='')}.json", "https://g", lines_for=lf)
        st = json.loads(body)["streams"]
        check("ورابط «تلقائي» في قائمة التشغيل يشير إليه", code == 200 and st[0]["url"] == f"https://g/stremio/{tok}/play/movie/{quote(mv[0]['id'], safe='')}")
        tok2 = S.make_token(d, h2, "cu", "cp")
        code, body, _, _ = S.handle(d, f"/stremio/{tok2}/catalog/series/sq_series.json", "https://g", lines_for=lf)
        check("كتالوج إضافة الخط المرتبط ← فارغ (صفوفه القديمة تختفي)", code == 200 and json.loads(body)["metas"] == [])
        code, body, _, _ = S.handle(d, f"/stremio/{tok}/meta/series/{quote(ali['id'], safe='')}.json", "https://g", lines_for=lf)
        check("والمعرّف القديم يفتح العمل الموحد بمصادره كلها", code == 200 and len(json.loads(body)["meta"]["videos"]) == 9)

        print("== التحديث الدوري: إضافةٌ وحذفٌ وتعديل في البوابات ==")
        casper.series = [{"series_id": 11, "name": "علي كارا (مترجم)", "category_id": "2", "releaseDate": "2024", "last_modified": "90"},
                         {"series_id": 13, "name": "Ali Kara", "category_id": "1", "releaseDate": "2024", "last_modified": "99"},
                         {"series_id": 14, "name": "مسلسل جديد", "category_id": "1", "last_modified": "200"}]
        old_lib = S.library(lines, "series")
        with S._lock:
            k = S._list_keys[(c2, "series")]
            t, val = S._lists[k]
            S._lists[k] = (t - S.TTL - 1, val)            # انتهى عمر قائمة كاسبر
        S.library(lines, "series")                        # تُعرض القديمة ويُحدَّث في الخلفية
        for _ in range(100):
            time.sleep(0.05)
            if S.library(lines, "series") is not old_lib:
                break
        names_now = [m["name"] for m in S.lib_catalog(lines, "series", "sq_series", {}, pre)["metas"]]
        check("الجديد يظهر، والمحذوف («مسلسل كاسبر وحده») يختفي، والمضاف بخطٍّ آخر يلتحق بعمله",
              names_now == ["مسلسل جديد", "علي كارا", "Squid Game"]
              and len(next(w for w in S.library(lines, "series").works if w.name == "علي كارا").sources) == 5,
              str(names_now))
        s1b.shutdown()
    finally:
        for srv in (s2, s3):
            srv.shutdown()
        shutil.rmtree(d, ignore_errors=True)


def main():
    matching()
    through_addon()
    print("\n" + "-" * 40)
    print(f"Result: \033[32m{_p} passed\033[0m, " + (f"\033[31m{_f} failed\033[0m" if _f else "0 failed"))
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

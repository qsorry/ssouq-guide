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


def panel(lines, url):
    """رابط مصدرٍ في قائمة التشغيل (على خادمنا) ← رابطه في اللوحة كما يحوّل إليه /play."""
    return S.src_url(lines, url.rsplit("/", 1)[1])


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

    print("== أسماء البوابات كما في «اكتشف ← تركي» ==")
    tr = LIB.build("series", [(0, "aaaaaa", "مرح", L("series", [(1, "علي كارا", 2024, "1"), (2, "أنت من أحب", 2025, "1"),
                                                                 (3, "مرعشلي", 2024, "1"), (4, "حيث تشرق الشمس", 2025, "1"),
                                                                 (5, "الحفرة", 2017, "1")])),
                              (1, "bbbbbb", "مرح1", L("series", [(11, "علي كارا مترجم 2025", 0, "2"), (12, "أنت من أحب مترجم 2025", 0, "2"),
                                                                  (13, "مرعشلي نسخة شاهد", 2024, "1"), (14, "حيث تشرق الشمس مترجم", 2024, "2"),
                                                                  (15, "الحفرة (مترجم) 2017", 0, "2")]))])
    check("«علي كارا مترجم 2025» · «الحفرة (مترجم) 2017»: النسخة قبل السنة تُحذف من المفتاح ← عملٌ واحد مع الأصل، وكذلك «نسخة شاهد»",
          len(tr.works) == 5 and all(len(w.sources) == 2 for w in tr.works), str(names(tr)))
    check("وسنتا مسلسلٍ متقاربتان (2024 · 2025: أول موسمٍ وآخره) لا تفصلانه", any(w.name == "حيث تشرق الشمس" and len(w.sources) == 2 for w in tr.works))
    check("والاسم في القائمة بلا «مترجم» ولا «نسخة شاهد» (النسخة في صفحة العمل)",
          sorted(w.name for w in tr.works) == sorted(["علي كارا", "أنت من أحب", "مرعشلي", "حيث تشرق الشمس", "الحفرة"]), str(sorted(w.name for w in tr.works)))
    one = LIB.build("series", [(0, "aaaaaa", "مرح", L("series", [(1, "أنت من أحب مترجم", 0, "1")]))])
    check("ومصدرٌ واحد كذلك: «أنت من أحب مترجم» ← «أنت من أحب» (ونسخته «مترجم» في مصادره)",
          one.works[0].name == "أنت من أحب" and one.works[0].sources[0].key.versions == ("subbed",), one.works[0].name)
    far = LIB.build("series", [(0, "aaaaaa", "سمارت", L("series", [(1, "The Office", 2001, "1")])),
                               (1, "bbbbbb", "فالكون", L("series", [(2, "The Office", 2005, "1")]))])
    check("وسنتان متباعدتان (2001 · 2005: نسختان مختلفتان) ← عملان", len(far.works) == 2)
    check("و«نسخة طبق الأصل» اسمٌ لا وصف نسخة", LIB.clean_title("نسخة طبق الأصل")["base"] == "نسخة طبق الأصل"
          and LIB.clean_title("فيلم نسخة طبق الأصل")["base"] == "فيلم نسخة طبق الأصل")

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
        cat = {c["type"]: c for c in man["catalogs"] if not c["id"].startswith(S.CAT_PREFIX)}
        opts = next(e["options"] for e in cat["series"]["extra"] if e["name"] == "genre")
        check("الـmanifest: الصفوف باسم المتجر وعدد الأعمال الموحدة، و«مصدر: …» لكل بوابة",
              cat["series"]["name"] == "سمارت سوق (3)" and cat["movie"]["name"] == "سمارت سوق (1)" and cat["tv"]["name"] == "سمارت سوق (1)"
              and opts[-3:] == ["مصدر: سمارت", "مصدر: كاسبر", "مصدر: فالكون"] and "مكتبةٌ واحدة" in man["description"], str(opts))
        same_pkg = [{"cfg": S.Cfg(h1, "u", "p", None), "label": "سمارت"}, lines[1], lines[2]]
        check("حسابان بالباقات نفسها يشتركان في مكتبةٍ واحدة", S.library(same_pkg, "series") is S.library(lines, "series"))
        shell = S.manifest(c2, "https://g", "كاسبر", accounts=False, catalogs=False)
        check("وإضافة الخط المرتبط بلا كتالوجات (تفاصيل ما في مكتبة Stremio ببادئتها تبقى)",
              shell["catalogs"] == [] and shell["resources"][1]["idPrefixes"] == [S.prefix(c2)])
        check("ومصادره في أعمال المكتبة (بادئة صاحب الحساب): مصادر إضافته لكل بادئاتنا",
              shell["resources"][2] == {"name": "stream", "types": shell["types"], "idPrefixes": [S.prefix(c2), "sq"]}
              and man["resources"][2]["idPrefixes"] == [pre], json.dumps(shell["resources"][2], ensure_ascii=False))

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
              and "S01E04" in sts[1]["title"] and panel(lines, sts[1]["url"]) == f"{h2}/series/cu/cp/11104.mkv"
              and sts[1]["url"].startswith(play_url + "/") and "cu" not in sts[1]["url"].split("/play/")[1], sts[1]["title"] + " " + sts[1]["url"])
        e1 = S.lib_streams(lines, "series", f"{pre}we:{S.line_hk(c1)}.1:1:1", pre, "x")["streams"]
        check("الحلقة الأولى في الثلاثة: المترجمان أولًا ثم سمارت بجودة ملفّه (1080p من تفاصيله)",
              [x["name"] for x in e1] == ["سمارت سوق", "كاسبر", "فالكون", "سمارت"] and "FHD (1080p)" in e1[3]["title"],
              json.dumps([(x["name"], x["title"]) for x in e1], ensure_ascii=False))
        e2 = f"{pre}we:{S.line_hk(c1)}.1:2:3"
        st2 = S.lib_streams(lines, "series", e2, pre, "x")["streams"]
        check("حلقة الموسم الثاني من مدخل فالكون وحده: بلا «تلقائي»", [x["name"] for x in st2] == ["فالكون"]
              and panel(lines, st2[0]["url"]) == f"{h3}/series/fu/fp/22103.mkv", json.dumps(st2, ensure_ascii=False)[:200])
        mv = S.lib_catalog(lines, "movie", "sq_movies", {}, pre)["metas"]
        check("الفيلم: عملٌ واحد من ثلاث بوابات", [x["name"] for x in mv] == ["Oppenheimer (2023)"])
        ms = S.lib_streams(lines, "movie", mv[0]["id"], pre, "auto")["streams"]
        check("ومصادره بالأفضل: الترجمة العربية (مترجم) ← الجودة الأعلى من الملف نفسه (4K) ← من الاسم (FHD)",
              [x["name"] for x in ms] == ["سمارت سوق", "فالكون", "سمارت", "كاسبر"] and panel(lines, ms[1]["url"]).endswith("/movie/fu/fp/301.mp4")
              and panel(lines, ms[2]["url"]).endswith("/movie/u/p/101.mkv") and "4K (2160p)" in ms[2]["title"] and "مترجم" in ms[1]["title"]
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

        print("== القنوات: أقسامها تصنيفات، وملصقٌ مرسوم باسمها ورقمها وختم جودتها ==")
        tcat = next(c for c in S.manifest(c1, "https://g", "سمارت", lines=lines)["catalogs"] if c["type"] == "tv")
        check("أقسام القنوات في التصنيف بأعدادها", next(e["options"] for e in tcat["extra"] if e["name"] == "genre")[0] == "رياضة (1)",
              json.dumps(tcat["extra"], ensure_ascii=False)[:200])
        mk = S._poster_maker(d, "https://g")
        lvp = S.lib_catalog(lines, "tv", "sq_live", {}, pre, mk)["metas"]
        check("بطاقة القناة بملصقٍ من الموقع (رابطه مختوم)", lvp[0]["poster"].startswith("https://g/stremio/p/") and lvp[0]["poster"].endswith(".png"))
        tok_p = lvp[0]["poster"].rsplit("/", 1)[1][:-4]
        raw = S.crypto_store.open_token(tok_p, d, S.POSTER_LABEL)
        check("ومعطياته: رقمها في القائمة، وأعلى جودات مصادرها (FHD من كاسبر)، وقسمها واسمها", raw == "1\nFHD\nرياضة\nbeIN SPORTS 1", repr(raw))
        check("والرابط نفسه للقناة نفسها (يحفظه Stremio)", S.lib_catalog(lines, "tv", "sq_live", {}, pre, mk)["metas"][0]["poster"] == lvp[0]["poster"])
        mtv = S.lib_meta(lines, "tv", lvp[0]["id"], "https://g/stremio/T/manifest.json", pre, mk)["meta"]
        check("وصفحتها بالملصق نفسه", mtv["poster"] == lvp[0]["poster"])
        code, body, ctype, hdr = S.poster_response(d, tok_p)
        check("‏/stremio/p/<رمز>.png ← الصورة (PNG بـ Pillow، وإلا SVG)، تُحفظ شهرًا",
              code == 200 and (body[:8] == b"\x89PNG\r\n\x1a\n" if ctype == "image/png" else ctype == "image/svg+xml" and b"<svg" in body)
              and "immutable" in hdr["Cache-Control"], f"{ctype} {len(body)}")
        bad = tok_p[:-2] + ("AA" if not tok_p.endswith("AA") else "BB")
        check("ورابطٌ معبوثٌ به (نصٌّ لم يصدر منّا) ← 404", S.poster_response(d, bad)[0] == 404 and S.poster_response(d, "x")[0] == 404)
        code, body, ctype, hdr = S.handle(d, f"/stremio/p/{tok_p}.png", "https://g")
        check("وعبر المسارات", code == 200 and ctype in ("image/png", "image/svg+xml") and hdr.get("Access-Control-Allow-Origin") == "*")
        import stremio_posters as P
        check("اسم الملصق بلا بادئة اللغة ولا رمز الجودة (الختم يقولها)", P.display_name("AR: MBC 1 HD") == "MBC 1"
              and P.display_name("beIN SPORTS 1 FHD") == "beIN SPORTS 1")
        svg = P._svg("قناة السعودية", 37, "4K", "قنوات عربية").decode()
        check("والتصميم نفسه بلا Pillow (SVG): الرقم والختم والاسم والقسم", ">37<" in svg and ">4K<" in svg and "قناة السعودية" in svg
              and "قنوات عربية" in svg and 'direction="rtl"' in svg)
        check("وبلا ختمٍ لجودةٍ لا تُعرف", "rotate(" not in P._svg("Al Jazeera", 3, "", "").decode())

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

        print("== لكل بوابةٍ زرّها فوق قائمة التشغيل (إضافة الخط المرتبط تعرض مصادره) ==")
        own = [lines[0], {**lines[1], "own": True}, {**lines[2], "own": True}]
        S.forget_lines()
        lf2 = lambda cfg: own if S.host_key(cfg.host) == "127.0.0.1" else None
        gf = lambda cfg: own if S.host_key(cfg.host) != "127.0.0.1" else None
        mid_q = quote(mv[0]["id"], safe="")
        code, body, _, _ = S.handle(d, f"/stremio/{tok}/stream/movie/{mid_q}.json", "https://g", lines_for=lf2, group_for=gf)
        root_st = json.loads(body)["streams"]
        check("صاحب الحساب: «تلقائي» (يجرّب المصادر كلها) ومصادر خطّه وحده", code == 200
              and [x["name"] for x in root_st] == ["سمارت سوق", "سمارت"], json.dumps([x["name"] for x in root_st], ensure_ascii=False))
        code, body, _, _ = S.handle(d, f"/stremio/{tok2}/stream/movie/{mid_q}.json", "https://g", lines_for=lf2, group_for=gf)
        cp_st = json.loads(body)["streams"]
        check("وإضافة كاسبر: مصدر كاسبر وحده في العمل نفسه (زرّ «سمارت سوق · كاسبر»)", code == 200
              and [x["name"] for x in cp_st] == ["كاسبر"] and panel(own, cp_st[0]["url"]) == f"{h2}/movie/cu/cp/201.mp4", body.decode()[:200])
        tok3 = S.make_token(d, h3, "fu", "fp")
        code, body, _, _ = S.handle(d, f"/stremio/{tok3}/stream/series/{quote(ep, safe='')}.json", "https://g", lines_for=lf2, group_for=gf)
        fc_st = json.loads(body)["streams"]
        check("وفالكون: حلقته من عمل المسلسل الموحد", code == 200 and [x["name"] for x in fc_st] == ["فالكون"]
              and panel(own, fc_st[0]["url"]).startswith(f"{h3}/series/fu/fp/"), body.decode()[:200])
        code, body, _, _ = S.handle(d, f"/stremio/{tok2}/stream/movie/sqffffff:m:1.json", "https://g", lines_for=lf2, group_for=gf)
        check("ومعرّفٌ من إضافةٍ أخرى ← لا مصادر", code == 200 and json.loads(body)["streams"] == [])
        code, body, _, _ = S.handle(d, f"/stremio/{tok2}/stream/movie/{quote(S.prefix(c2), safe='')}m:201.json", "https://g",
                                    lines_for=lf2, group_for=gf)
        check("ومعرّفه القديم ببادئته يعمل كما كان", code == 200 and panel(own, json.loads(body)["streams"][0]["url"]) == f"{h2}/movie/cu/cp/201.mp4", body.decode()[:200])
        old_url = json.loads(body)["streams"][0]["url"]
        code, _, _, hdr = S.handle(d, old_url[len("https://g"):], "https://g", lines_for=lf2, group_for=gf)
        check("ورابط المصدر على خادمنا يحوّل (302) إلى اللوحة — وإضافة الخط المرتبط من خطوط حسابه", code == 302
              and hdr["Location"] == f"{h2}/movie/cu/cp/201.mp4", str((code, hdr.get("Location"))))
        all_json = json.dumps([root_st, cp_st, fc_st, json.loads(body)], ensure_ascii=False)
        check("ولا يوزر Xtream ولا باسورد في أي ردٍّ للإضافة (قوائم التشغيل)", all(f"/{x}/" not in all_json for x in ("u/p", "cu/cp", "fu/fp")),
              all_json[:200])
        code, _, _, _ = S.handle(d, f"/stremio/{tok}/play/movie/x/ffffff.m1.mp4", "https://g", lines_for=lf2, group_for=gf)
        check("ومصدرٌ من خطٍّ ليس في هذا الحساب ← 404 (لا يُصنع رابطٌ لسيرفرٍ آخر)", code == 404)
        S.forget_lines()
        code, body, _, _ = S.handle(d, f"/stremio/{tok}/stream/movie/{mid_q}.json", "https://g", lines_for=lf)
        check("وإضافة خطٍّ مرتبط لم تُحدَّث بعد (بلا own): مصادره عند صاحب الحساب كما كانت",
              [x["name"] for x in json.loads(body)["streams"]][0] == "سمارت سوق"
              and sorted(x["name"] for x in json.loads(body)["streams"][1:]) == sorted(["سمارت", "كاسبر", "فالكون"]), body.decode()[:300])
        S.forget_lines()
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


def slow_line():
    """خطٌّ بطيءٌ أو متعثّر لا يؤخّر المكتبة: كاسبر يتعثّر في قائمة أفلامه — كان صفّ الأفلام كله ينتظره حتى يفشل، مع كل
    طلب، فلا تظهر الأفلام."""
    print("== خطٌّ بطيء أو متعثّر ==")
    S.reset()
    smart, casper = MP.Panel("smart"), MP.Panel("casper", "cu", "cp")
    for p in (smart, casper):
        p.cat("vod", 10, "أفلام")
        p.cat("series", 1, "مسلسلات")
    smart.vod = [{"stream_id": 101, "name": "فيلم سمارت (2024)", "category_id": "10", "added": "100", "container_extension": "mkv"}]
    casper.vod = [{"stream_id": 201, "name": "فيلم كاسبر (2023)", "category_id": "10", "added": "90", "container_extension": "mp4"}]
    smart.series = [{"series_id": 1, "name": "مسلسل سمارت", "category_id": "1", "last_modified": "100"},
                    {"series_id": 2, "name": "علي كارا", "category_id": "1", "releaseDate": "2024", "last_modified": "50"}]
    casper.series = [{"series_id": 11, "name": "مسلسل كاسبر", "category_id": "1", "last_modified": "90"},
                     {"series_id": 12, "name": "علي كارا (مترجم)", "category_id": "1", "releaseDate": "2024", "last_modified": "40"}]
    smart.episodes(2, {1: 2})
    casper.episodes(12, {1: 4})
    s1, s2 = MP.serve(smart), MP.serve(casper, bind="127.0.0.2")
    c1 = S.Cfg(f"http://127.0.0.1:{s1.server_address[1]}", "u", "p")
    c2 = S.Cfg(f"http://127.0.0.2:{s2.server_address[1]}", "cu", "cp")
    lines = [{"cfg": c1, "label": "سمارت"}, {"cfg": c2, "label": "كاسبر"}]
    pre = S.prefix(c1)
    wait0 = S.LIB_WAIT
    S.LIB_WAIT = 0.5
    try:
        casper.slow["get_vod_streams"] = 2.0
        t = time.time()
        mv = S.lib_catalog(lines, "movie", "sq_movies", {}, pre)["metas"]
        took = time.time() - t
        check("قائمة كاسبر بطيئة: صفّ الأفلام لا ينتظرها — يُعرض بعد ثوانٍ بالخط الجاهز", took < 1.5
              and [m["name"] for m in mv] == ["فيلم سمارت (2024)"], f"{took:.1f} ث")
        t = time.time()
        S.lib_catalog(lines, "movie", "sq_movies", {}, pre)
        check("والطلب التالي فوري (لا ينتظر تحميلًا بدأه طلبٌ قبله)", time.time() - t < 0.3, f"{time.time() - t:.2f} ث")
        got = []
        for _ in range(100):
            time.sleep(0.05)
            got = [m["name"] for m in S.lib_catalog(lines, "movie", "sq_movies", {}, pre)["metas"]]
            if len(got) == 2:
                break
        check("ويدخل كاسبر المكتبة حين تصل قائمته", got == ["فيلم سمارت (2024)", "فيلم كاسبر (2023)"], str(got))
        S.drop_lists(c2, "movie")
        S.lib_catalog(lines, "movie", "sq_movies", {}, pre)
        man = S.manifest(c1, "https://g", "سمارت", lines=lines)
        cat = {c["type"]: c for c in man["catalogs"]}
        check("والـmanifest (يُثبَّت مرة) ينتظر الخطوط كلها: أعداده و«مصدر: …» منها كلها",
              cat["movie"]["name"] == "سمارت سوق (2)" and "مصدر: كاسبر" in next(e["options"] for e in cat["movie"]["extra"] if e["name"] == "genre"),
              cat["movie"]["name"])

        ali = next(m for m in S.lib_catalog(lines, "series", "sq_series", {}, pre)["metas"] if m["name"] == "علي كارا")
        casper.slow["get_series_info"] = 2.0
        t = time.time()
        vids = S.lib_meta(lines, "series", ali["id"], None, pre)["meta"]["videos"]
        took = time.time() - t
        check("صفحة مسلسلٍ مصدره في كاسبر بطيء: تُفتح بعد ثوانٍ بحلقات المصدر الجاهز", took < 1.5 and len(vids) == 2,
              f"{took:.1f} ث، {len(vids)} حلقات")
        for _ in range(100):
            time.sleep(0.05)
            vids = S.lib_meta(lines, "series", ali["id"], None, pre)["meta"]["videos"]
            if len(vids) == 4:
                break
        check("وحلقات كاسبر تظهر حين تصل تفاصيله", len(vids) == 4, str(len(vids)))

        casper.down.add("get_series")                     # تعثّرٌ دائم (القائمة كاملةً وقسمًا قسمًا)
        S.drop_lists(c2, "series")
        S.lib_catalog(lines, "series", "sq_series", {}, pre)   # السابقة تُعرض حتى يُعاد البناء
        for _ in range(200):
            time.sleep(0.05)
            f = S._line_jobs.get((c2, "series"))
            if f and f.done() and [m["name"] for m in S.lib_catalog(lines, "series", "sq_series", {}, pre)["metas"]] == ["مسلسل سمارت", "علي كارا"]:
                break
        n = len(casper.hits)
        t = time.time()
        ser = S.lib_catalog(lines, "series", "sq_series", {}, pre)["metas"]
        check("قائمة مسلسلات كاسبر تتعثّر: الصفّ بالخط الجاهز، وتعثّره يُذكر دقيقة (الطلب التالي فوري ولا يسأل كاسبر من جديد)",
              time.time() - t < 0.3 and len(casper.hits) == n and [m["name"] for m in ser] == ["مسلسل سمارت", "علي كارا"],
              f"{time.time() - t:.2f} ث، {len(casper.hits) - n} طلبات، {[m['name'] for m in ser]}")
        smart.down.add("get_series")
        with S._lock:
            S._lists.clear()
            S._list_keys.clear()
            S._cats.clear()
            S._libs.clear()
        try:
            S.lib_catalog(lines, "series", "sq_series", {}, pre)
            ok = False
        except S.XtreamError:
            ok = True
        check("وكل الخطوط تتعثّر ← الخطأ (لا كتالوجٌ فارغ)", ok)
    finally:
        S.LIB_WAIT = wait0
        for srv in (s1, s2):
            srv.shutdown()


CATALOG = S.CATALOG


def movie_genres():
    print("== تصنيف العمل بلغتين، وكل أفلامه (من تفاصيلها حين لا تذكره القائمة) ==")
    S.reset()
    a, b = MP.Panel("ga"), MP.Panel("gb", "bu", "bp")
    for p in (a, b):
        p.cat("vod", 10, "أفلام")
        p.cat("series", 1, "مسلسلات")
    a.vod = [{"stream_id": 1, "name": "Heat (1995)", "category_id": "10", "added": "10", "info_genre": "Crime, Drama"},
             {"stream_id": 2, "name": "Up (2009)", "category_id": "10", "added": "20", "info_genre": "Animation"},
             {"stream_id": 3, "name": "Se7en (1995)", "category_id": "10", "added": "30", "genre": "Crime"}]
    b.vod = [{"stream_id": 7, "name": "الجزيرة (2007)", "category_id": "10", "added": "40", "info_genre": "جريمة، دراما"}]
    a.series = [{"series_id": 1, "name": "Dark", "category_id": "1", "last_modified": "5", "genre": "Drama, Mystery"}]
    b.series = [{"series_id": 5, "name": "الهيبة", "category_id": "1", "last_modified": "9", "genre": "دراما، إثارة"},
                {"series_id": 6, "name": "Friends", "category_id": "1", "last_modified": "8", "genre": "Comedy"}]
    sa, sb = MP.serve(a), MP.serve(b, bind="127.0.0.2")
    ca = S.Cfg(f"http://127.0.0.1:{sa.server_address[1]}", "u", "p")
    cb = S.Cfg(f"http://127.0.0.2:{sb.server_address[1]}", "bu", "bp")
    lines = [{"cfg": ca, "label": "سمارت"}, {"cfg": cb, "label": "فالكون"}]
    pre = S.prefix(ca)
    d = tempfile.mkdtemp(prefix="stremio_genres_")
    names = lambda kind, g: [m["name"] for m in S.lib_catalog(lines, kind, CATALOG[kind], {"genre": g}, pre)["metas"]]
    try:
        for c in (ca, cb):
            S.warm(c)
        check("المسلسلات: «دراما» ← ما كُتب «Drama» في بوابةٍ و«دراما» في أخرى", names("series", "دراما") == ["الهيبة", "Dark"]
              and names("series", "Drama") == names("series", "دراما"), str(names("series", "دراما")))
        check("و«Mystery» = «غموض»، و«Comedy» = «كوميديا»", names("series", "غموض") == ["Dark"] == names("series", "Mystery")
              and names("series", "كوميديا") == ["Friends"])
        check("الأفلام قبل الجمع: ما في القائمة وحده", names("movie", "جريمة") == ["Se7en (1995)"], str(names("movie", "جريمة")))
        n_info = lambda p: sum(1 for h in p.hits if h == "/player_api.php")
        n = S.crawl_genres(ca, d, rps=1000) + S.crawl_genres(cb, d, rps=1000)
        check("الجمع في الخلفية: تفاصيل ما لا تصنيف له في القائمة وحده (3 أفلام)", n == 3, str(n))
        before = n_info(a) + n_info(b)
        check("ولا يُطلب فيلمٌ مرتين", S.crawl_genres(ca, d, rps=1000) + S.crawl_genres(cb, d, rps=1000) == 0 and n_info(a) + n_info(b) == before)
        check("«جريمة» ← كل أفلامها من البوابتين بالأحدث (و«Crime» النتيجة نفسها)",
              names("movie", "جريمة") == ["الجزيرة (2007)", "Se7en (1995)", "Heat (1995)"] and names("movie", "Crime") == names("movie", "جريمة"),
              str(names("movie", "جريمة")))
        check("و«رسوم متحركة» من «Animation»", names("movie", "رسوم متحركة") == ["Up (2009)"])
        heat = next(m for m in S.lib_catalog(lines, "movie", "sq_movies", {}, pre)["metas"] if m["name"] == "Heat (1995)")
        hm = S.lib_meta(lines, "movie", heat["id"], "https://g/stremio/T/manifest.json", pre)["meta"]
        check("صفحة الفيلم: تصنيفاته بالعربية روابطَ", hm["genres"] == ["جريمة", "دراما"]
              and [x["name"] for x in hm["links"] if x["category"] == "Genres"] == ["جريمة", "دراما"]
              and [x for x in hm["links"] if x["category"] == "Genres"][-1]["url"].endswith("?genre=" + quote("دراما", safe="")),
              json.dumps(hm.get("links"), ensure_ascii=False)[:300])
        check("وفي ملفٍّ على القرص لكل سيرفر", len(os.listdir(os.path.join(d, "stremio_genres"))) == 2)
        S.reset()
        S.genre_dir(d)
        check("يُقرأ بعد إعادة التشغيل", S.genre_ids(ca, "Crime") == {1} and S.genre_ids(cb, "جريمة") == {7})
        check("و‏STREMIO_GENRE_RPS=0 ← لا جمع", S.crawl_genres(ca, d, rps=0) == 0)
        S.warm(ca)
        check("وخطٌّ وحده (بلا مكتبة) كذلك", [it.name for it in S._tagged(ca, "movie", S.lists(ca, "movie"), "crime")] == ["Se7en (1995)", "Heat (1995)"])
    finally:
        for srv in (sa, sb):
            srv.shutdown()
        shutil.rmtree(d, ignore_errors=True)


def categories():
    print("== تصنيفات سمارت سوق: واحدةٌ لكل البوابات، صفوفٌ في الرئيسية، وتُحرَّر ==")
    import stremio_categories as K
    S.reset()
    a, b = MP.Panel("ca"), MP.Panel("cb", "bu", "bp")
    a.cat("series", 1, "مسلسلات تركية")
    a.cat("series", 2, "مسلسلات رمضان 2026")
    a.cat("series", 3, "Kurdish Series")
    b.cat("series", 1, "TR | Turkish")
    b.cat("series", 2, "مسلسلات تركية مدبلجة عربي")
    b.cat("series", 3, "مسلسلات عربية")
    a.cat("vod", 10, "أفلام")
    b.cat("vod", 20, "VOD | HORROR")
    a.cat("live", 30, "beIN SPORTS")
    b.cat("live", 40, "قنوات MBC")
    a.series = [{"series_id": 1, "name": "علي كارا", "category_id": "1", "releaseDate": "2024", "last_modified": "50"},
                {"series_id": 2, "name": "مسلسل رمضاني", "category_id": "2", "last_modified": "40"},
                {"series_id": 3, "name": "Kurdish Show", "category_id": "3", "last_modified": "30"}]
    b.series = [{"series_id": 11, "name": "Ali Kara - Arabic Sub", "category_id": "1", "releaseDate": "2024", "last_modified": "45"},
                {"series_id": 12, "name": "مسلسل مدبلج", "category_id": "2", "last_modified": "35"},
                {"series_id": 13, "name": "مسلسل عربي", "category_id": "3", "last_modified": "20"}]
    a.vod = [{"stream_id": 1, "name": "Speed (1994)", "category_id": "10", "added": "10", "genre": "Action"}]
    b.vod = [{"stream_id": 5, "name": "Scream (1996)", "category_id": "20", "added": "20"}]
    a.live = [{"stream_id": 7, "name": "beIN SPORTS 1 HD", "category_id": "30"}]
    b.live = [{"stream_id": 8, "name": "MBC 1", "category_id": "40"}]
    sa, sb = MP.serve(a), MP.serve(b, bind="127.0.0.2")
    ca = S.Cfg(f"http://127.0.0.1:{sa.server_address[1]}", "u", "p")
    cb = S.Cfg(f"http://127.0.0.2:{sb.server_address[1]}", "bu", "bp")
    lines = [{"cfg": ca, "label": "سمارت"}, {"cfg": cb, "label": "فالكون"}]
    pre = S.prefix(ca)
    d = tempfile.mkdtemp(prefix="stremio_cats_")
    try:
        for c in (ca, cb):
            S.warm(c)
        check("‏cached_library: لا تُبنى ولا تُحمَّل (للصفحات التي لا تنتظر)", S.cached_library(lines, "series") is None)
        import threading
        calls, real = [], S.LIB.build
        S.LIB.build = lambda kind, parts: (calls.append(kind), time.sleep(0.3), real(kind, parts))[2]
        try:
            ts = [threading.Thread(target=S.library, args=(lines, "series", True)) for _ in range(4)]   # بقوائم خطوطها كلها
            for t in ts:
                t.start()
            for t in ts:
                t.join()
        finally:
            S.LIB.build = real
        check("أربعة طلباتٍ متزامنة للمكتبة نفسها ← تُبنى مرةً واحدة", calls == ["series"], str(calls))
        check("وبعدها في الذاكرة", S.cached_library(lines, "series") is S.library(lines, "series"))
        row = lambda kind, cid, ln=lines: [m["name"] for m in S.lib_catalog(ln, kind, CATALOG[kind], {}, pre)["metas"]] if cid is None else \
            [m["name"] for m in S.lib_catalog(ln, kind, S.CAT_PREFIX + cid, {}, pre)["metas"]]
        check("«مسلسلات تركية» في سمارت و«TR | Turkish» في فالكون ← «تركي»، والعمل مرةً واحدة", row("series", "s_turkish") == ["علي كارا", "مسلسل مدبلج"],
              str(row("series", "s_turkish")))
        check("و«-ترك» تُخرج «تركية مدبلجة عربي» من «عربي»", row("series", "s_arabic") == ["مسلسل عربي"], str(row("series", "s_arabic")))
        check("و«رمضان 2026» ← «رمضان»", row("series", "s_ramadan") == ["مسلسل رمضاني"])
        check("وما لم يدخل تصنيفًا ← «أخرى» (من «اكتشف»)", [m["name"] for m in S.lib_catalog(lines, "series", "sq_series", {"genre": "أخرى (1)"}, pre)["metas"]]
              == ["Kurdish Show"])
        check("الأفلام: تصنيف العمل نفسه («Action» ← «أكشن») وقسم اللوحة («VOD | HORROR» ← «رعب»)",
              row("movie", "m_action") == ["Speed (1994)"] and row("movie", "m_horror") == ["Scream (1996)"])
        check("والقنوات: «beIN SPORTS» ← «رياضة»، و«قنوات MBC» ← «عربية»", row("tv", "t_sports") == ["beIN SPORTS 1 HD"] and row("tv", "t_arabic") == ["MBC 1"])
        check("وتصنيفٌ حُذف ← صفّه فارغ (يختفي من Stremio)", row("series", "nope") == [])
        man = S.manifest(ca, "https://g", "سمارت", lines=lines)
        rows = [(c["type"], c["name"]) for c in man["catalogs"] if c["id"].startswith(S.CAT_PREFIX)]
        check("الـmanifest: صفوف الرئيسية ما فيه محتوى من تصنيفات «في الرئيسية» بترتيبها",
              rows == [("series", "رمضان"), ("series", "تركي"), ("series", "عربي"), ("movie", "أكشن"), ("movie", "رعب"), ("tv", "رياضة"), ("tv", "عربية")],
              json.dumps(rows, ensure_ascii=False))
        sopts = next(e["options"] for c in man["catalogs"] if c["id"] == "sq_series" for e in c["extra"] if e["name"] == "genre")
        check("وقائمة «اكتشف»: تصنيفاتنا بأعدادها (وما ليس في الرئيسية منها: «مدبلج»)، ثم «أخرى»، ثم «مصدر: …»",
              sopts == ["رمضان (1)", "تركي (2)", "عربي (1)", "مدبلج (1)", "أخرى (1)", "مصدر: سمارت", "مصدر: فالكون"], json.dumps(sopts, ensure_ascii=False))
        mk = S._poster_maker(d, "https://g")
        lv = S.lib_catalog(lines, "tv", "sq_live", {}, pre, mk)["metas"]
        raw = S.crypto_store.open_token(lv[0]["poster"].rsplit("/", 1)[1][:-4], d, S.POSTER_LABEL)
        check("وملصق القناة بتصنيفها الموحد", raw.split("\n")[2] == "رياضة", repr(raw))

        print("== صفّ «التصنيفات» أُزيل (لم يعمل «عرض الكل» في التطبيقات) ==")
        check("لا صفّ «التصنيفات» في الـmanifest ولا نوعه", S.TILES not in man["types"] and all(c["id"] != S.TILES_ID for c in man["catalogs"])
              and man["types"][:2] == [S.ACCOUNTS, "series"], json.dumps(man["types"], ensure_ascii=False))
        check("وصفوف التصنيفات نفسها باقية («تركي - المسلسلات»)", any(c["id"] == S.CAT_PREFIX + "s_turkish" for c in man["catalogs"]))
        check("وقائمة «اكتشف» بالتصنيف: كل ما في «تركي»", [m["name"] for m in S.lib_catalog(lines, "series", "sq_series", {"genre": "تركي"}, pre)["metas"]]
              == row("series", "s_turkish"))
        tok_c = S.make_token(d, ca.host, "u", "p")
        lf = lambda cfg: lines if S.host_key(cfg.host) == S.host_key(ca.host) else None   # noqa: E731
        code, body, _, _ = S.handle(d, f"/stremio/{tok_c}/catalog/{quote(S.TILES, safe='')}/{S.TILES_ID}.json", "https://g", lines_for=lf)
        check("نسخةٌ مثبّتةٌ قبل التحديث تطلبه ← فارغ (فيختفي صفّه بلا إعادة تثبيت)", code == 200 and json.loads(body) == {"metas": []}, str(code))
        code, _, _, _ = S.handle(d, f"/stremio/{tok_c}/stream/{quote(S.TILES, safe='')}/{quote(pre + 'c:series:s_turkish', safe='')}.json",
                                 "https://g", lines_for=lf)
        check("وبطاقاته القديمة ← 404", code == 404, str(code))

        print("== تحرير التصنيفات ==")
        mine = [{"id": "s_kurd", "kind": "series", "name": "كردي", "keys": "kurdish, كردي", "home": True},
                {"kind": "series", "name": "تركي", "keys": "ترك, turk, tr", "home": False},
                {"kind": "series", "name": "مخفي", "keys": "رمضان", "home": True, "on": False}]
        own = [{**lines[0], "cats": K.clean(mine)}, lines[1]]
        man2 = S.manifest(ca, "https://g", "سمارت", lines=own)
        rows2 = [(c["type"], c["name"]) for c in man2["catalogs"] if c["id"].startswith(S.CAT_PREFIX)]
        sopts2 = next(e["options"] for c in man2["catalogs"] if c["id"] == "sq_series" for e in c["extra"] if e["name"] == "genre")
        check("تصنيفات العميل: صفّ «كردي» وحده، و«تركي» في «اكتشف» وحدها، والمخفي لا يظهر", rows2 == [("series", "كردي")]
              and sopts2[:3] == ["كردي (1)", "تركي (2)", "أخرى (2)"], json.dumps([rows2, sopts2], ensure_ascii=False))
        check("ومحتوى صفّه من الخادم فورًا", row("series", "s_kurd", own) == ["Kurdish Show"])
        bad = lambda cats: (lambda: K.clean(cats))
        def raises(f):
            try:
                f()
            except ValueError:
                return True
            return False
        check("التحقّق: اسمٌ مكرّر في النوع، و«أخرى»، ونوعٌ غير معروف، واسمٌ فارغ ← خطأ",
              raises(bad([{"kind": "series", "name": "أ", "keys": "x"}, {"kind": "series", "name": "أ", "keys": "y"}]))
              and raises(bad([{"kind": "movie", "name": "أخرى", "keys": "x"}])) and raises(bad([{"kind": "x", "name": "أ"}]))
              and raises(bad([{"kind": "tv", "name": " "}])) and raises(bad([{"kind": "tv", "name": f"ت{i}"} for i in range(31)])))
        check("والاسم نفسه في نوعين مسموح، ومعرّفٌ يُصنع لما لا معرّف له", len({c["id"] for c in K.clean(
              [{"kind": "series", "name": "تركي"}, {"kind": "movie", "name": "تركي"}])}) == 2)
        K.save(d, "acct1", mine)
        check("الحفظ لحساب الأداة والقراءة", [c["name"] for c in K.get(d, "acct1")] == ["كردي", "تركي", "مخفي"] and K.edited(d, "acct1")
              and [c["name"] for c in K.get(d, "acct2")] == [c["name"] for c in K.DEFAULTS] and not K.edited(d, "acct2"))
        check("و«الافتراضي» يعيده", [c["name"] for c in K.reset(d, "acct1")] == [c["name"] for c in K.DEFAULTS] and not K.edited(d, "acct1"))
    finally:
        for srv in (sa, sb):
            srv.shutdown()
        shutil.rmtree(d, ignore_errors=True)


def main():
    matching()
    through_addon()
    slow_line()
    movie_genres()
    categories()
    print("\n" + "-" * 40)
    print(f"Result: \033[32m{_p} passed\033[0m, " + (f"\033[31m{_f} failed\033[0m" if _f else "0 failed"))
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

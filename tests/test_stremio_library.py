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
    """لكل سيرفرٍ أقسامه وحده (لا دمج): إضافة كل خطٍّ بكتالوجاته ومعرّفاته، وإضافة Nuvio الواحدة بكتالوجاتٍ لكل خط؛ والمعرّفات
    القديمة من المكتبة الموحدة تعمل؛ والقنوات بطاقةٌ لكل قسمٍ بشعار شركته والقنوات داخلها."""
    S.reset()
    smart, casper, falcon = panels()
    smart.cat("live", 21, "MBC HD")
    smart.cat("live", 22, "MBC")
    smart.live += [{"stream_id": 511, "name": "MBC 1", "category_id": "22", "stream_icon": "https://logo.example/mbc1.png"},
                   {"stream_id": 512, "name": "MBC 2", "category_id": "22"},
                   {"stream_id": 513, "name": "MBC 1 HD", "category_id": "21", "stream_icon": "https://logo.example/mbc1hd.png"}]
    s1, s2, s3 = MP.serve(smart), MP.serve(casper), MP.serve(falcon, bind="127.0.0.2")
    h1 = f"http://127.0.0.1:{s1.server_address[1]}"
    h2 = f"http://localhost:{s2.server_address[1]}"
    h3 = f"http://127.0.0.2:{s3.server_address[1]}"
    c1, c2, c3 = S.Cfg(h1, "u", "p"), S.Cfg(h2, "cu", "cp"), S.Cfg(h3, "fu", "fp")
    lines = [{"cfg": c1, "label": "سمارت"}, {"cfg": c2, "label": "كاسبر"}, {"cfg": c3, "label": "فالكون"}]
    pre, pre2, pre3 = S.prefix(c1), S.prefix(c2), S.prefix(c3)
    d = tempfile.mkdtemp(prefix="stremio_lib_")
    tok, tok2, tok3 = S.make_token(d, h1, "u", "p"), S.make_token(d, h2, "cu", "cp"), S.make_token(d, h3, "fu", "fp")
    labels = {S.host_key(h1): "سمارت", S.host_key(h2): "كاسبر", S.host_key(h3): "فالكون"}
    lf = lambda cfg: lines if S.host_key(cfg.host) == S.host_key(h1) else None   # noqa: E731
    gf = lambda cfg: lines if S.host_key(cfg.host) != S.host_key(h1) else None   # noqa: E731

    def get(t, path, lines_for=lf):
        code, body, ctype, hdr = S.handle(d, f"/stremio/{t}/{path}", "https://g", label_for=lambda c: labels.get(S.host_key(c.host), ""),
                                          lines_for=lines_for, group_for=gf)
        try:
            return code, json.loads(body), hdr
        except ValueError:
            return code, body, hdr
    try:
        print("== البناء المسبق ==")
        n_hits = len(smart.hits)
        check("لا يُبنى مسبقًا ما لم تكن قوائم خطوطه في الذاكرة (لا يسأل السيرفرات شيئًا جديدًا)",
              S.warm_library(lines) == 0 and len(smart.hits) == n_hits)
        for c in (c1, c2, c3):
            S.warm(c)
        check("وقوائمه في الذاكرة ← تُبنى مكتبة كل نوعٍ لكل خطٍّ وحده (3 × 3)", S.warm_library(lines) == 9)

        print("== لكل سيرفرٍ أقسامه وحده: «سمارت» و«كاسبر» و«فالكون» ==")
        code, man, _ = get(tok, "manifest.json")
        main = {c["type"]: c for c in man["catalogs"] if c["id"] in S.CATALOG.values()}
        check("إضافة صاحب الحساب: «الحسابات» ثم كتالوجات خطّه وحده باسم سيرفره وعدده", code == 200 and man["catalogs"][0]["id"] == S.ACCOUNTS_ID
              and main["series"]["name"] == "سمارت (2)" and main["movie"]["name"] == "سمارت (1)" and main["tv"]["name"] == "سمارت (4)",
              json.dumps([c["name"] for c in man["catalogs"]], ensure_ascii=False))
        check("ومعرّفات خطّه وحده (لا بادئات غيره)، ومصادره كذلك", man["idPrefixes"] == [pre] and man["resources"][2]["idPrefixes"] == [pre])
        code, man2, _ = get(tok2, "manifest.json")
        check("وإضافة الخط المرتبط: كتالوجات خطّه (لا «الحسابات»)، وبادئته وحدها", code == 200 and S.ACCOUNTS not in man2["types"]
              and [c["name"] for c in man2["catalogs"] if c["id"] in S.CATALOG.values()] == ["كاسبر (2)", "كاسبر (1)", "كاسبر (1)"]
              and man2["resources"][2]["idPrefixes"] == [pre2], json.dumps(man2["catalogs"], ensure_ascii=False)[:300])
        code, ser, _ = get(tok, "catalog/series/sq_series.json")
        check("مسلسلات سمارت وحدها، بأسمائها في لوحته (لا دمج)", [m["name"] for m in ser["metas"]] == ["علي كارا", "Squid Game"]
              and ser["metas"][0]["id"] == f"{pre}s:1", json.dumps([(m["name"], m["id"]) for m in ser["metas"]], ensure_ascii=False))
        code, ser2, _ = get(tok2, "catalog/series/sq_series.json")
        check("ومسلسلات كاسبر في إضافته، بمعرّفاته", [m["name"] for m in ser2["metas"]] == ["علي كارا (مترجم)", "مسلسل كاسبر وحده"]
              and ser2["metas"][0]["id"] == f"{pre2}s:11", json.dumps([(m["name"], m["id"]) for m in ser2["metas"]], ensure_ascii=False))
        code, ser3, _ = get(tok3, "catalog/series/sq_series.json")
        check("وفالكون: مدخلاه كما في لوحته (لا يُدمج «الموسم الثاني» ولا «Arabic Sub»)",
              [m["name"] for m in ser3["metas"]] == ["Ali Kara - Arabic Sub", "علي كارا الموسم الثاني"])
        code, found, _ = get(tok, "catalog/series/sq_series/search=Ali%20Kara.json")
        check("والبحث في سيرفره وحده", [m["id"] for m in found["metas"]] == [f"{pre}s:1"], str(found))

        print("== صفحة العمل وتشغيله من سيرفره وحده ==")
        code, mt, _ = get(tok, f"meta/series/{quote(pre + 's:1', safe='')}.json")
        vids = mt["meta"]["videos"]
        check("«علي كارا» في سمارت: حلقاته هو (3)، بمعرّفاتها كما كانت", len(vids) == 3 and vids[0]["id"].startswith(f"{pre}e:"),
              json.dumps(vids[:1], ensure_ascii=False))
        code, st, _ = get(tok, f"stream/series/{quote(vids[0]['id'], safe='')}.json")
        check("ومصدره من سمارت وحده، باسم سيرفره", code == 200 and len(st["streams"]) == 1 and st["streams"][0]["name"] == "سمارت"
              and panel(lines, st["streams"][0]["url"]).startswith(f"{h1}/series/u/p/"), json.dumps(st, ensure_ascii=False)[:200])
        code, mv, _ = get(tok3, "catalog/movie/sq_movies.json")
        code, ms, _ = get(tok3, f"stream/movie/{quote(mv['metas'][0]['id'], safe='')}.json")
        check("فيلم فالكون: مصدره وحده بلا «تلقائي»", [x["name"] for x in ms["streams"]] == ["فالكون"]
              and panel(lines, ms["streams"][0]["url"]) == f"{h3}/movie/fu/fp/301.mp4", json.dumps(ms, ensure_ascii=False)[:200])
        code, _, hdr = get(tok3, f"play/movie/{quote(mv['metas'][0]['id'], safe='')}")
        check("و‏/play ← تحويلٌ (302) إلى مصدره", code == 302 and hdr["Location"] == f"{h3}/movie/fu/fp/301.mp4", str((code, hdr.get("Location"))))
        code, st, _ = get(tok2, f"stream/movie/{quote(pre + 'm:101', safe='')}.json")
        check("ومعرّف سيرفرٍ آخر ← لا مصادر من هذه الإضافة", code == 200 and st["streams"] == [])
        code, _, _ = get(tok, "play/movie/x/ffffff.m1.mp4")
        check("ومصدرٌ من خطٍّ ليس في هذا الحساب ← 404 (لا يُصنع رابطٌ لسيرفرٍ آخر)", code == 404)

        print("== المعرّفات القديمة (المكتبة الموحدة) تعمل من سيرفرها ==")
        old = f"{pre}ws:{S.line_hk(c2)}.12"
        code, mt, _ = get(tok, f"meta/series/{quote(old, safe='')}.json")
        check("عملٌ مرساته في كاسبر («تابع المشاهدة») ← صفحته من كاسبر، بمعرّفه كما طُلب", code == 200 and mt["meta"]["id"] == old
              and mt["meta"]["name"] == "مسلسل كاسبر وحده", json.dumps(mt, ensure_ascii=False)[:200])
        old_ep = f"{pre}we:{S.line_hk(c2)}.11:1:2"
        code, st, _ = get(tok, f"stream/series/{quote(old_ep, safe='')}.json")
        check("وحلقته القديمة ← مصدرها من كاسبر", code == 200 and [x["name"] for x in st["streams"]] == ["كاسبر"]
              and panel(lines, st["streams"][0]["url"]) == f"{h2}/series/cu/cp/11102.mkv", json.dumps(st, ensure_ascii=False)[:200])
        code, _, hdr = get(tok, st["streams"][0]["url"].split(f"/stremio/{tok}/", 1)[1])
        check("ورابط المصدر على خادمنا يحوّل (302) إلى اللوحة", code == 302 and hdr["Location"] == f"{h2}/series/cu/cp/11102.mkv")

        print("== إضافة Nuvio الواحدة: «مسلسلات (سمارت)» · «مسلسلات (كاسبر)» … كلٌّ وحده ==")
        S.forget_lines()
        nl = [{**lines[0], "nuvio": True}] + lines[1:]
        nlf = lambda cfg: nl if S.host_key(cfg.host) == S.host_key(h1) else None   # noqa: E731
        code, nman, _ = get(tok, "manifest.json", nlf)
        nm = [c["name"] for c in nman["catalogs"] if c["name"].split(" (")[0] in S.SECTION_AR.values()]
        check("كتالوجاتٌ لكل خطٍّ باسم القسم والسيرفر", nm == ["مسلسلات (سمارت)", "أفلام (سمارت)", "بث مباشر (سمارت)", "مسلسلات (كاسبر)",
                                                              "أفلام (كاسبر)", "بث مباشر (كاسبر)", "مسلسلات (فالكون)", "أفلام (فالكون)",
                                                              "بث مباشر (فالكون)"] and nman["idPrefixes"] == [pre, pre2, pre3], str(nm))
        print("== الـmanifest محفوظ: فورًا بعد إعادة النشر، وبلا نسخةٍ نسخةٌ سريعة بمعرّفات الكتالوجات نفسها ==")
        with S._lock:
            S._mans.clear()                               # كإعادة تشغيل: الذاكرة فارغة والقرص فيه آخر نسخة
        orig_bm, built_n = S.build_manifest, []

        def slow_bm(*a, **k):
            if not (len(a) > 8 and a[8]) and not k.get("quick"):
                built_n.append(1)
                time.sleep(0.6)
            return orig_bm(*a, **k)
        S.build_manifest = slow_bm
        try:
            t0 = time.time()
            code, again_man, hdr = get(tok, "manifest.json", nlf)
            check("بعد إعادة التشغيل: آخر نسخةٍ من القرص فورًا (لا ينتظر بناء المكتبات)", code == 200 and again_man == nman
                  and time.time() - t0 < 0.5 and not built_n, f"{time.time() - t0:.2f}s")
            with S._lock:
                S._mans.clear()
            for f in os.listdir(os.path.join(d, "stremio_lists", "manifests")):
                os.remove(os.path.join(d, "stremio_lists", "manifests", f))
            S.MANIFEST_WAIT, wait0 = 0.05, S.MANIFEST_WAIT
            code, qman, hdr = get(tok, "manifest.json", nlf)
            S.MANIFEST_WAIT = wait0
            qids = [c["id"] for c in qman["catalogs"]]
            check("وبلا نسخةٍ والبناء طويل: نسخةٌ سريعة فورًا بكتالوجات كل سيرفرٍ بمعرّفاتها نفسها (فتجد المجلدات إضافتها)، وتُطلب قريبًا",
                  code == 200 and qman["id"] == nman["id"] and all(c["id"] in qids for c in nman["catalogs"] if c["id"].startswith("sq_"))
                  and "max-age=60" in hdr.get("Cache-Control", ""), str(hdr.get("Cache-Control")))
            for _ in range(60):
                if S._mans:
                    break
                time.sleep(0.05)
            code, full_man, _ = get(tok, "manifest.json", nlf)
            check("ويكمل البناء في الخلفية: الطلب التالي بالنسخة الكاملة", code == 200 and full_man == nman and len(built_n) == 1)
        finally:
            S.build_manifest = orig_bm
        fid = next(c["id"] for c in nman["catalogs"] if c["name"] == "مسلسلات (فالكون)")
        code, fs, _ = get(tok, f"catalog/series/{fid}.json", nlf)
        check("وكتالوج فالكون فيها: ما في فالكون وحده بمعرّفاته", fid == "sq_series_" + S.line_hk(c3)
              and [m["id"] for m in fs["metas"]] == [f"{pre3}s:21", f"{pre3}s:22"], json.dumps(fs, ensure_ascii=False)[:200])
        code, st, _ = get(tok, f"stream/movie/{quote(pre3 + 'm:301', safe='')}.json", nlf)
        check("ومصادره من فالكون", code == 200 and panel(lines, st["streams"][0]["url"]) == f"{h3}/movie/fu/fp/301.mp4")
        code, fm, _ = get(tok, f"meta/series/{quote(pre3 + 's:21', safe='')}.json", nlf)
        vids = (fm.get("meta") or {}).get("videos") or [] if isinstance(fm, dict) else []
        code2, fst, _ = get(tok, f"stream/series/{quote(vids[0]['id'], safe='')}.json", nlf) if vids else (0, {}, {})
        check("وحلقة مسلسلٍ من فالكون: صفحته بحلقاته، ومصادر الحلقة من فالكون", code == 200 and code2 == 200 and vids
              and fst.get("streams") and panel(lines, fst["streams"][0]["url"]).startswith(f"{h3}/series/fu/fp/"),
              json.dumps([code, code2, vids[:1], fst], ensure_ascii=False)[:300])
        S.forget_lines()

        print("== البث المباشر: بطاقةٌ بشعار كل قسم، والقنوات داخلها (عريضة) ==")
        code, tv, _ = get(tok, "catalog/tv/sq_live.json")
        groups = [(m["name"], m["description"], m["posterShape"]) for m in tv["metas"]]
        check("بلا تصنيف: بطاقةٌ لكل قسمٍ في اللوحة — الرياضة ثم العربية (بترتيب تصنيفات القنوات)", groups ==
              [("رياضة", "قناة واحدة", "landscape"), ("MBC HD", "قناة واحدة", "landscape"), ("MBC", "قناتان", "landscape")], str(groups))
        mbc = next(m for m in tv["metas"] if m["name"] == "MBC")
        check("وصورة البطاقة شعار شركتها (من أول قناةٍ فيها لها شعار)، وبلا شعار ← ملصقٌ مرسوم", mbc["poster"] == "https://logo.example/mbc1.png"
              and tv["metas"][0]["poster"].startswith("https://g/stremio/p/"))
        code, gm, _ = get(tok, f"meta/tv/{quote(mbc['id'], safe='')}.json")
        check("وصفحة البطاقة: قنواتها", code == 200 and gm["meta"]["name"] == "MBC" and "MBC 1 · MBC 2" in gm["meta"]["description"])
        vids = gm["meta"].get("videos") or []
        check("وقنواته «حلقاتٌ» مرقّمة بترتيب اللوحة (زر «التالي» في Nuvio ← القناة التالية) بشعاراتها",
              [(v["title"], v["season"], v["episode"]) for v in vids] == [("MBC 1", 1, 1), ("MBC 2", 1, 2)]
              and vids[0]["thumbnail"] == "https://logo.example/mbc1.png" and gm["meta"]["behaviorHints"]["defaultVideoId"] == mbc["id"],
              json.dumps(vids, ensure_ascii=False)[:300])
        code, nx, _ = get(tok, f"stream/tv/{quote(vids[1]['id'], safe='')}.json")
        check("والحلقة الثانية ← بثّ «MBC 2» وحده («تلقائي» أولًا ثم صيغه)", code == 200 and nx["streams"]
              and all((panel(lines, x["url"]) or "").startswith(f"{h1}/live/u/p/512.") for x in nx["streams"][1:])
              and nx["streams"][0]["url"].endswith(quote(vids[1]["id"], safe="")), json.dumps(nx, ensure_ascii=False)[:200])
        code, gs, _ = get(tok, f"stream/tv/{quote(mbc['id'], safe='')}.json")
        check("والضغط عليها ← قائمة التشغيل: قناةٌ لكل سطر", [x["title"].split("\n")[0] for x in gs["streams"]] == ["MBC 1", "MBC 2"]
              and panel(lines, gs["streams"][0]["url"]) == f"{h1}/live/u/p/511.m3u8", json.dumps(gs, ensure_ascii=False)[:200])
        code, ch, _ = get(tok, "catalog/tv/sq_live/genre=MBC%20(2).json")
        check("و«اكتشف» ← القسم ← قنواته عريضةً بشعاراتها (وبلا شعار ملصقٌ مرسوم عريض)",
              [(m["name"], m["posterShape"]) for m in ch["metas"]] == [("MBC 1", "landscape"), ("MBC 2", "landscape")]
              and ch["metas"][0]["poster"] == "https://logo.example/mbc1.png" and ch["metas"][1]["poster"].startswith("https://g/stremio/p/"))
        raw = S.crypto_store.open_token(ch["metas"][1]["poster"].rsplit("/", 1)[1][:-4], d, S.POSTER_LABEL)
        check("والمرسوم عريضٌ برقمها وقسمها واسمها", raw.startswith("w") and raw.endswith("\nMBC\nMBC 2"), repr(raw))
        code, body, ctype, _ = S.poster_response(d, ch["metas"][1]["poster"].rsplit("/", 1)[1][:-4])
        check("‏/stremio/p/<رمز>.png العريض ← صورةٌ 16:9", code == 200 and (b'width="711"' in body if ctype == "image/svg+xml" else body[:4] == b"\x89PNG"))
        code, opt, _ = get(tok, "manifest.json")
        tvc = next(c for c in opt["catalogs"] if c["id"] == "sq_live")
        check("وأقسام اللوحة في قائمة تصنيف البث بأعدادها", next(e["options"] for e in tvc["extra"] if e["name"] == "genre") ==
              ["رياضة (1)", "MBC HD (1)", "MBC (2)"])
        all_json = json.dumps([ser, ser2, ser3, mt, st, ms, tv, gm, gs, ch, man, man2, nman], ensure_ascii=False)
        check("ولا يوزر Xtream ولا باسورد في أي ردٍّ للإضافة", all(f"/{x}/" not in all_json for x in ("u/p", "cu/cp", "fu/fp")))

        print("== التحديث الدوري: إضافةٌ وحذفٌ وتعديل في اللوحة ==")
        casper.series = [{"series_id": 11, "name": "علي كارا (مترجم)", "category_id": "2", "releaseDate": "2024", "last_modified": "90"},
                         {"series_id": 14, "name": "مسلسل جديد", "category_id": "1", "last_modified": "200"}]
        one = [lines[1]]
        old_lib = S.library(one, "series")
        with S._lock:
            k = S._list_keys[(c2, "series")]
            t, val = S._lists[k]
            S._lists[k] = (t - S.TTL - 1, val)            # انتهى عمر قائمة كاسبر
        S.library(one, "series")                          # تُعرض القديمة ويُحدَّث في الخلفية
        for _ in range(100):
            time.sleep(0.05)
            if S.library(one, "series") is not old_lib:
                break
        code, now2, _ = get(tok2, "catalog/series/sq_series.json")
        check("الجديد يظهر، والمحذوف («مسلسل كاسبر وحده») يختفي", [m["name"] for m in now2["metas"]] == ["مسلسل جديد", "علي كارا (مترجم)"],
              str(now2))
        lib_now, list_now = S.library(one, "series"), S.lists(c2, "series")
        with S._lock:
            k = S._list_keys[(c2, "series")]
            t, val = S._lists[k]
            S._lists[k] = (t - S.TTL - 1, val)            # انتهى عمرها ولم يتغيّر شيءٌ في اللوحة
        S.lists(c2, "series")
        for _ in range(100):
            time.sleep(0.05)
            with S._lock:
                fresh = time.time() - S._lists[k][0] < S.TTL
            if fresh:
                break
        check("وتحديثٌ لم يجد جديدًا في اللوحة: القائمة نفسها (لا تُعاد بناء المكتبة — بعد إعادة النشر لا تُبنى مرتين)",
              fresh and S.lists(c2, "series") is list_now and S.library(one, "series") is lib_now)
    finally:
        for srv in (s1, s2, s3):
            srv.shutdown()
        shutil.rmtree(d, ignore_errors=True)


def slow_line():
    """سيرفرٌ بطيءٌ أو متعثّر لا يؤخّر غيره (لكل سيرفرٍ أقسامه وحده)، ولا يُعرض كتالوجه فارغًا وهو يُحمَّل."""
    print("== سيرفرٌ بطيء أو متعثّر ==")
    S.reset()
    smart, casper = MP.Panel("smart"), MP.Panel("casper", "cu", "cp")
    for p in (smart, casper):
        p.cat("vod", 10, "أفلام")
        p.cat("series", 1, "مسلسلات")
    smart.vod = [{"stream_id": 101, "name": "فيلم سمارت (2024)", "category_id": "10", "added": "100", "container_extension": "mkv"}]
    casper.vod = [{"stream_id": 201, "name": "فيلم كاسبر (2023)", "category_id": "10", "added": "90", "container_extension": "mp4"}]
    smart.series = [{"series_id": 1, "name": "مسلسل سمارت", "category_id": "1", "last_modified": "100"}]
    casper.series = [{"series_id": 11, "name": "مسلسل كاسبر", "category_id": "1", "last_modified": "90"}]
    s1, s2 = MP.serve(smart), MP.serve(casper, bind="127.0.0.2")
    c1 = S.Cfg(f"http://127.0.0.1:{s1.server_address[1]}", "u", "p")
    c2 = S.Cfg(f"http://127.0.0.2:{s2.server_address[1]}", "cu", "cp")
    books = S._books([{"cfg": c1, "label": "سمارت"}, {"cfg": c2, "label": "كاسبر"}])
    sfx = books[1][1]
    names = lambda kind, cid: [m["name"] for m in S.lib_catalog(books, kind, cid, {})["metas"]]   # noqa: E731
    wait0 = S.LIB_WAIT
    S.LIB_WAIT = 0.5
    try:
        casper.slow["get_vod_streams"] = 1.5
        t = time.time()
        got = names("movie", "sq_movies")
        check("قائمة كاسبر بطيئة: أفلام سمارت لا تنتظرها", time.time() - t < 1.0 and got == ["فيلم سمارت (2024)"], f"{time.time() - t:.1f} ث")
        t = time.time()
        got = names("movie", "sq_movies" + sfx)
        check("وأفلام كاسبر تنتظر قائمته (لا تُعرض فارغةً فيظنّها Stremio انتهت)", time.time() - t >= 0.8 and got == ["فيلم كاسبر (2023)"],
              f"{time.time() - t:.1f} ث، {got}")
        casper.down.add("get_series")                     # تعثّرٌ دائم (القائمة كاملةً وقسمًا قسمًا)
        try:
            names("series", "sq_series" + sfx)
            ok = False
        except S.XtreamError:
            ok = True
        n = len(casper.hits)
        t = time.time()
        try:
            names("series", "sq_series" + sfx)
        except S.XtreamError:
            pass
        check("قائمة مسلسلات كاسبر تتعثّر ← الخطأ (لا كتالوجٌ فارغ)، وتعثّره يُذكر دقيقة (لا يسأل كاسبر من جديد)",
              ok and time.time() - t < 0.3 and len(casper.hits) == n, f"{len(casper.hits) - n} طلبات")
        check("ومسلسلات سمارت كما هي", names("series", "sq_series") == ["مسلسل سمارت"])
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
    books = S._books(lines)
    d = tempfile.mkdtemp(prefix="stremio_genres_")
    one = lambda kind, g, b: [m["name"] for m in S.lib_catalog(books, kind, CATALOG[kind] + books[b][1], {"genre": g})["metas"]]   # noqa: E731
    names = lambda kind, g: one(kind, g, 0) + one(kind, g, 1)   # noqa: E731
    try:
        for c in (ca, cb):
            S.warm(c)
        check("المسلسلات: «دراما» ← ما كُتب «Drama» في سيرفرٍ و«دراما» في آخر (كلٌّ في سيرفره)", one("series", "دراما", 0) == ["Dark"]
              and one("series", "دراما", 1) == ["الهيبة"] and names("series", "Drama") == names("series", "دراما"), str(names("series", "دراما")))
        check("و«Mystery» = «غموض»، و«Comedy» = «كوميديا»", names("series", "غموض") == ["Dark"] == names("series", "Mystery")
              and names("series", "كوميديا") == ["Friends"])
        check("الأفلام قبل الجمع: ما في القائمة وحده", names("movie", "جريمة") == ["Se7en (1995)"], str(names("movie", "جريمة")))
        n_info = lambda p: sum(1 for h in p.hits if h == "/player_api.php")
        n = S.crawl_genres(ca, d, rps=1000) + S.crawl_genres(cb, d, rps=1000)
        check("الجمع في الخلفية: تفاصيل ما لا تصنيف له في القائمة وحده (3 أفلام)", n == 3, str(n))
        before = n_info(a) + n_info(b)
        check("ولا يُطلب فيلمٌ مرتين", S.crawl_genres(ca, d, rps=1000) + S.crawl_genres(cb, d, rps=1000) == 0 and n_info(a) + n_info(b) == before)
        check("«جريمة» ← كل أفلامها في كل سيرفرٍ بالأحدث (و«Crime» النتيجة نفسها)",
              one("movie", "جريمة", 0) == ["Se7en (1995)", "Heat (1995)"] and one("movie", "جريمة", 1) == ["الجزيرة (2007)"]
              and names("movie", "Crime") == names("movie", "جريمة"), str(names("movie", "جريمة")))
        check("و«رسوم متحركة» من «Animation»", names("movie", "رسوم متحركة") == ["Up (2009)"])
        heat = next(m for m in S.lib_catalog(books, "movie", "sq_movies", {})["metas"] if m["name"] == "Heat (1995)")
        hm = S.lib_meta(lines[:1], "movie", heat["id"], "https://g/stremio/T/manifest.json", pre)["meta"]
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


def disk_copy():
    print("== نسخة القوائم على القرص: بعد إعادة التشغيل تُعرض فورًا وتُحدَّث في الخلفية ==")
    S.reset()
    a = MP.Panel("dk")
    a.cat("series", 1, "مسلسلات")
    a.series = [{"series_id": i, "name": f"مسلسل {i}", "category_id": "1", "last_modified": str(i), "releaseDate": "2025",
                 "tmdb": str(1000 + i) if i == 3 else ""} for i in range(1, 6)]
    sa = MP.serve(a)
    ca = S.Cfg(f"http://127.0.0.1:{sa.server_address[1]}", "u", "p")
    d = tempfile.mkdtemp(prefix="stremio_disk_")
    try:
        S.disk_dir(d)
        L1 = S.lists(ca, "series")
        key = S._lkey(ca, "series")
        for _ in range(50):
            if S._dpath(key) and os.path.exists(S._dpath(key)):
                break
            time.sleep(0.05)
        check("تُحفظ نسختها على القرص مضغوطةً (في الخلفية)", os.path.exists(S._dpath(key)) and S._dpath(key).endswith(".json.gz"))
        S.reset()                                         # «إعادة تشغيل الخادم»: الذاكرة فارغة
        S.disk_dir(d)
        a.slow["get_series"] = 3                          # والسيرفر بطيءٌ في القائمة الكاملة (مرح بعد النشر)
        t = time.time()
        L2 = S.lists(ca, "series")
        took = time.time() - t
        check("بعدها: القائمة فورًا من القرص (لا تنتظر السيرفر البطيء)", took < 1.5 and [it.name for it in L2.items] == [it.name for it in L1.items],
              f"{took:.2f}s")
        check("بعناصرها كما هي (السنة ومعرّف TMDB والقسم)", L2.by_id[3].tmdb == 1003 and L2.by_id[3].year == L1.by_id[3].year
              and L2.cat_of(L2.by_id[3]) == "مسلسلات")
        a.series.append({"series_id": 9, "name": "مسلسل جديد", "category_id": "1", "last_modified": "99"})
        for _ in range(100):
            L3 = S._cached_lists(ca, "series")
            if L3 is not L2 and any(it.id == 9 for it in L3.items):
                break
            time.sleep(0.1)
        check("وتُحدَّث من السيرفر في الخلفية (الجديد يظهر بعد وصولها)", any(it.id == 9 for it in S._cached_lists(ca, "series").items))
        check("ونسخةٌ تالفة لا تُسقط شيئًا (تُتجاهل)", (open(S._dpath(key), "wb").write(b"broken") and S.disk_load(key, "series")) is None)

        print("== تفاصيل ما فُتح على القرص («تابع المشاهدة» بعد إعادة التشغيل) ==")
        a.info[3] = {"info": {"name": "مسلسل 3", "cover": "https://image.tmdb.org/t/p/w500/c3.jpg"}, "episodes": {"1": []}}
        d1 = S._details(ca, "get_series_info", "series_id", 3)
        ik = (S.host_key(ca.host), "get_series_info", 3)
        for _ in range(50):
            if os.path.exists(S._ipath(ik)):
                break
            time.sleep(0.05)
        check("تُحفظ تفاصيل المسلسل المفتوح على القرص", d1 and os.path.exists(S._ipath(ik)))
        S.reset()
        S.disk_dir(d)
        a.down.add("get_series_info")                     # اللوحة لا تردّ على التفاصيل بعد إعادة التشغيل
        d2 = S._details(ca, "get_series_info", "series_id", 3)
        check("وبعد إعادة التشغيل تُقرأ من القرص (الاسم والصورة) ولو لم تردّ اللوحة", d2 == d1, json.dumps(d2, ensure_ascii=False)[:120])
        a.down.discard("get_series_info")

        print("== صورة الخلفية العريضة للواجهة الكبيرة (Nuvio) ==")
        a.series[0]["backdrop_path"] = ["https://image.tmdb.org/t/p/w1280/bg1.jpg"]
        S.drop_lists(ca, "series")
        L4 = S.lists(ca, "series")
        m4 = S._preview(S.prefix(ca), "series", L4.by_id[1])
        check("من ‏backdrop_path في قائمة اللوحة إلى «background» في بطاقة العمل", m4.get("background") == "https://image.tmdb.org/t/p/w1280/bg1.jpg"
              and "background" not in S._preview(S.prefix(ca), "series", L4.by_id[2]), json.dumps(m4, ensure_ascii=False)[:160])
    finally:
        sa.shutdown()
        shutil.rmtree(d, ignore_errors=True)
        S.reset()


def akhi_and_inspect():
    print("== «أخي» في مرح وفالكون، و«فحص عمل» (‏S.inspect_work) ==")
    S.reset()
    a, b = MP.Panel("ia"), MP.Panel("ib", "bu", "bp")
    a.cat("series", 1, "[TR] 2026 تركي مترجم (يعرض الآن)")
    a.cat("series", 2, "[TR] 2026 تركي مدبلج (يعرض الآن)")
    b.cat("series", 1, "Turkish - تركية مترجمة")
    b.cat("series", 2, "Turkish - تركية مدبلجة")
    # الأسماء كما في اللوحتين فعلًا (صفحة المحتوى، أكتوبر 2026)
    t = int(time.time())                                  # «آه يا أخي» في «يعرض الآن» وآخر حلقاته قبل 6 أشهر (كما في سمارت فعلًا)
    a.series = [{"series_id": 1, "name": "أخي مترجم", "category_id": "1", "releaseDate": "2026-09-01", "last_modified": str(t - 2 * 86400)},
                {"series_id": 2, "name": "أخي", "category_id": "2", "releaseDate": "2026-09-01", "last_modified": str(t - 2 * 86400 - 1)},
                {"series_id": 3, "name": "آه يا أخي", "category_id": "1", "last_modified": str(t - 180 * 86400)}]
    b.series = [{"series_id": 11, "name": "أخي (مترجم)", "category_id": "1", "releaseDate": "2026", "last_modified": "18"},
                {"series_id": 12, "name": "أخي (مترجم) S01", "category_id": "1", "last_modified": "17"},
                {"series_id": 13, "name": "أخي (مدبلج) S01", "category_id": "2", "last_modified": "16"},
                {"series_id": 14, "name": "اخي العزيز", "category_id": "1", "last_modified": "4", "tmdb": "500"},
                {"series_id": 15, "name": "اخي العزيز (مترجم)", "category_id": "1", "last_modified": "3", "tmdb": "600"},
                # تركيٌّ نزلت حلقته أمس، وآخر آخرُ حلقاته قبل 40 يومًا (لا «يعرض الآن» في أقسام فالكون)
                {"series_id": 16, "name": "مسلسل تركي جديد", "category_id": "1", "last_modified": str(int(time.time()) - 86400)},
                {"series_id": 17, "name": "مسلسل تركي قديم", "category_id": "1", "last_modified": str(int(time.time()) - 40 * 86400)}]
    sa, sb = MP.serve(a), MP.serve(b, bind="127.0.0.2")
    ca = S.Cfg(f"http://127.0.0.1:{sa.server_address[1]}", "u", "p")
    cb = S.Cfg(f"http://127.0.0.2:{sb.server_address[1]}", "bu", "bp")
    lines = [{"cfg": ca, "label": "مرح"}, {"cfg": cb, "label": "فالكون"}]
    pre = S.prefix(ca)
    try:
        res = S.inspect_work(lines, "اخي")
        ser = next((k for k in res["kinds"] if k["kind"] == "series"), {})
        check("قبل التحميل: «لم تُحمَّل بعد» لكل خط (ويبدأ تحميلها في الخلفية)، ولا مكتبة", ser and ser["library"] is False
              and [l["loaded"] for l in ser["lines"]] == [False, False], json.dumps(ser, ensure_ascii=False)[:200])
        for c in (ca, cb):
            S.warm(c)
        S.warm_library(lines)
        books = S._books(lines)
        fb = books[1][1]
        sr = lambda q, b=0, kind="series": [m["name"] for m in S.lib_catalog(books, kind, CATALOG[kind] + books[b][1], {"search": q})["metas"]]   # noqa: E731
        check("لا دمج: «أخي» في مرح مدخلاه كما في لوحته (المترجم والمدبلج)، والبحث بلا همزة («اخي») يجدهما أولًا",
              set(sr("اخي")[:2]) == {"أخي مترجم", "أخي"} and "آه يا أخي" in sr("اخي"), str(sr("اخي")))
        check("وفي فالكون مداخله هو، في إضافته", set(sr("اخي", 1)) == {"أخي (مترجم)", "أخي (مترجم) S01", "أخي (مدبلج) S01", "اخي العزيز",
                                                                         "اخي العزيز (مترجم)"}, str(sr("اخي", 1)))
        res = S.inspect_work(lines, "اخي")
        ser = next(k for k in res["kinds"] if k["kind"] == "series")
        check("«فحص عمل»: ما في الإضافة بهذا الاسم في كل سيرفرٍ وحده", ser["library"] and {x["sources"][0]["hk"] for x in ser["works"]}
              == {S.line_hk(ca), S.line_hk(cb)} and all(len(x["sources"]) == 1 for x in ser["works"]), json.dumps(ser["works"], ensure_ascii=False)[:240])
        mr = ser["lines"][0]
        check("وما في قائمة كل خطٍّ بالاسم والسنة والقسم", mr["loaded"] and mr["label"] == "مرح"
              and [(x["name"], x["year"], x["cat"]) for x in mr["items"]][:2] == [("أخي مترجم", 2026, "[TR] 2026 تركي مترجم (يعرض الآن)"),
                                                                                 ("أخي", 2026, "[TR] 2026 تركي مدبلج (يعرض الآن)")],
              json.dumps(mr["items"], ensure_ascii=False)[:200])
        check("واسمٌ لا يوجد ← لا شيء", S.inspect_work(lines, "لا يوجد أبدًا")["kinds"] == [])

        print("== «تركي» ← «يعرض الآن مترجم» و«يعرض الآن مدبلج»: من قسم «يعرض الآن» في اللوحة ==")
        idx = lambda b: S._cat_index([books[b][0]], S.library([books[b][0]], "series"), "series")["by"]   # noqa: E731
        by = idx(0)
        sub_now, dub_now = [w.anchor.item.name for w in by.get("s_tr_now", [])], [w.anchor.item.name for w in by.get("s_trd_now", [])]
        check("مرح «[TR] 2026 تركي مترجم (يعرض الآن)» ← «يعرض الآن مترجم» ما فيه ونزلت له حلقةٌ خلال 10 أيام", sub_now == ["أخي مترجم"], str(sub_now))
        check("وما بقي في قسم «يعرض الآن» وتوقّف من 6 أشهر («آه يا أخي») ليس فيه، ويبقى في «تركي»", "آه يا أخي" not in sub_now
              and "آه يا أخي" in [w.anchor.item.name for w in by.get("s_turkish", [])])
        check("و«[TR] 2026 تركي مدبلج (يعرض الآن)» ← «يعرض الآن مدبلج» وحده", dub_now == ["أخي"], str(dub_now))
        fby = idx(1)
        check("وفالكون (بلا قسم «يعرض الآن»): ما نزلت له حلقةٌ خلال 10 أيام، لا ما توقّف قبل 40 يومًا",
              [w.anchor.item.name for w in fby.get("s_tr_now", [])] == ["مسلسل تركي جديد"], str([w.anchor.item.name for w in fby.get("s_tr_now", [])]))
        man = S.manifest(ca, "https://g", "مرح", lines=lines)
        main_opts = next(e["options"] for c in man["catalogs"] if c["id"] == "sq_series" for e in c["extra"] if e["name"] == "genre")
        tk = next(c for c in man["catalogs"] if c["id"] == S.MAIN_PREFIX + "s_turkish")
        check("قائمة تصنيف المسلسلات: الرئيسية وحدها («تركي (3)»)، و«تركي» كتالوجٌ قائمة تصنيفه «الكل» ثم الفرعية",
              main_opts[0] == "تركي (3)" and tk["name"] == "تركي" and tk["extra"][0]["isRequired"] is True
              and tk["extra"][0]["options"][:5] == ["الكل (3)", "يعرض الآن مترجم (1)", "يعرض الآن مدبلج (1)", "مترجم (2)", "مدبلج (1)"],
              json.dumps([main_opts, tk], ensure_ascii=False)[:400])
        sub = lambda g, b=0: [m["name"] for m in S.lib_catalog(books, "series", S.MAIN_PREFIX + "s_turkish" + books[b][1], {"genre": g})["metas"]]   # noqa: E731
        check("والفرعي يفتح أعماله: «مدبلج» ← المدبلج وحده، و«الكل» ← التركي كله", sub("مدبلج (1)") == ["أخي"]
              and set(sub("الكل")) == {"أخي مترجم", "أخي", "آه يا أخي"} and sub("مترجم") == ["أخي مترجم", "آه يا أخي"], str(sub("مترجم")))
        check("وفي فالكون: «مدبلج» من اسم قسمه («تركية مدبلجة»)", sub("مدبلج", 1) == ["أخي (مدبلج) S01"], str(sub("مدبلج", 1)))
        check("وتبويب السنة في الرئيسي («2026») ← أعماله في تلك السنة وحدها", "2026 (2)" in tk["extra"][0]["options"]
              and sub("2026 (2)") == ["أخي مترجم", "أخي"], str(sub("2026")))

        print("== اختيار السنة: «حسب السنة» في «اكتشف»، والسنة تصنيفٌ في كتالوج النوع ==")
        yc = next((c for c in man["catalogs"] if c["id"] == S.YEARS["series"]), {})
        ex = (yc.get("extra") or [{}])[0]
        check("كتالوج «حسب السنة» للمسلسلات: السنوات بأعدادها الأحدث أولًا، والسنة مطلوبة (فلا يظهر صفًّا في الرئيسية)",
              yc.get("name") == S.YEARS_NAME and ex.get("isRequired") is True and ex.get("options", [None])[0] == "2026 (2)",
              json.dumps(yc, ensure_ascii=False)[:200])
        check("ولا «حسب السنة» للقنوات", all(not c["id"].endswith("_years") or c["type"] != "tv" for c in man["catalogs"]))
        y26 = [m["name"] for m in S.lib_catalog(books, "series", S.YEARS["series"], {"genre": "2026 (2)"})["metas"]]
        check("اختيار 2026 ← أعمال 2026 وحدها", y26 == ["أخي مترجم", "أخي"], str(y26))
        check("والسنة تصنيفٌ في كتالوج المسلسلات نفسه («2026» — مجلد السنة في Nuvio)",
              [m["name"] for m in S.lib_catalog(books, "series", "sq_series", {"genre": "2026"})["metas"]] == ["أخي مترجم", "أخي"])
        check("و«حسب السنة» بلا سنة ← لا شيء", S.lib_catalog(books, "series", S.YEARS["series"], {})["metas"] == [])

        print("== البحث في تصنيفٍ وحده: «تركي: اخي» ==")
        check("بلا تصنيف ← في السيرفر كله", {"أخي مترجم", "أخي", "آه يا أخي"} <= set(sr("اخي")))
        check("«يعرض الآن مترجم: اخي» (فرعي) ← ما يُعرض الآن وحده", sr("يعرض الآن مترجم: اخي") == ["أخي مترجم"], str(sr("يعرض الآن مترجم: اخي")))
        check("والاسم بعدده وبنقطتين عريضتين «：» وبلا مسافات", sr("يعرض الآن مدبلج (1)：اخي") == ["أخي"] and sr("تركي:اخي")[:2] == sr("اخي")[:2])
        check("«2026: اخي» و«سنة 2026: اخي» ← أعمال تلك السنة", set(sr("2026: اخي")) == {"أخي مترجم", "أخي"} == set(sr("سنة 2026: اخي")),
              str(sr("2026: اخي")))
        check("«يعرض الآن مدبلج:» وحده ← التصنيف كله", sr("يعرض الآن مدبلج:") == ["أخي"])
        check("تصنيفٌ من نوعٍ آخر («رعب» للأفلام) ← لا شيء في المسلسلات، وسنةٌ في القنوات ← لا شيء",
              sr("رعب: اخي") == [] and sr("2026: اخي", 0, "tv") == [])
        check("وما قبل النقطتين ليس تصنيفًا ولا سنةً ولا مصدرًا ← بحثٌ عاديٌّ بالنص كله («Mission: Impossible»)",
              S._scoped_search([books[0][0]], S.library([books[0][0]], "series"), "series", "Mission: اخي")
              == S.library([books[0][0]], "series").search("Mission: اخي"))
        check("‏_takes_key يميّز lines_for(cfg، القفل) (لا يظلّله اسمٌ آخر — إضافة Nuvio بخطوطها)",
              S._takes_key(lambda c, k: 0) is True and S._takes_key(lambda c: 0) is False)
    finally:
        for srv in (sa, sb):
            srv.shutdown()


def now_showing():
    print("== «يعرض الآن» في لوحاتٍ أخرى: قسمٌ يجمع المترجم والمدبلج (كاسبر)، ووقتٌ «يُحدَّث» للقسم كله، وبلا قسم «يعرض الآن» ==")
    S.reset()
    now = int(time.time())
    c, f, k = MP.Panel("nc"), MP.Panel("nf", "fu", "fp"), MP.Panel("nk", "ku", "kp")
    c.cat("series", 1, "يعرض الان تركي")                 # كاسبر: الأسماء كما في لوحته (أكتوبر 2026)
    c.cat("series", 2, "TURKISH تركي |AR|")
    c.series = [{"series_id": 1, "name": "طبيعة الحب مدبلج", "category_id": "1", "last_modified": str(now - 2 * 86400)},
                {"series_id": 2, "name": "الكرامة مترجم", "category_id": "1", "last_modified": str(now - 2 * 86400)},
                {"series_id": 3, "name": "الغرفة المجاورة", "category_id": "1", "last_modified": str(now - 2 * 86400)}] + \
               [{"series_id": 10 + i, "name": f"مسلسل قديم {i}", "category_id": "2", "last_modified": str(now - 86400)} for i in range(25)]
    f.cat("series", 1, "Turkish - تركية مترجمة")          # فالكون: بلا قسم «يعرض الآن»
    f.cat("series", 2, "Turkish - تركية مدبلجة")
    f.series = [{"series_id": 1, "name": "حلقة أمس", "category_id": "1", "last_modified": str(now - 86400)},
                {"series_id": 2, "name": "توقّف من شهر", "category_id": "1", "last_modified": str(now - 40 * 86400)},
                {"series_id": 3, "name": "طائر الرفراف", "category_id": "2", "last_modified": str(now - 86400)}] + \
               [{"series_id": 10 + i, "name": f"قديم {i}", "category_id": "1", "last_modified": str(now - 200 * 86400)} for i in range(25)]
    k.cat("series", 1, "TURKISH تركي")                    # لوحةٌ «حدّثت» القسم كله أمس، وبلا قسم «يعرض الآن»
    k.series = [{"series_id": 1 + i, "name": f"عمل {i}", "category_id": "1", "last_modified": str(now - 86400)} for i in range(25)]
    servers = [MP.serve(c, bind="127.0.0.3"), MP.serve(f, bind="127.0.0.4"), MP.serve(k, bind="127.0.0.5")]
    cc, cf, ck = (S.Cfg(f"http://127.0.0.{3 + i}:{srv.server_address[1]}", u, p)
                  for i, (srv, u, p) in enumerate(zip(servers, ("u", "fu", "ku"), ("p", "fp", "kp"))))
    try:
        for cfg in (cc, cf, ck):
            S.warm(cfg)

        def now_of(lines):
            by = S._cat_index(lines, S.library(lines, "series"), "series")["by"]
            return sorted(w.name for w in by.get("s_tr_now", [])), sorted(w.name for w in by.get("s_trd_now", []))
        sub, dub = now_of([{"cfg": cc, "label": "كاسبر"}])
        check("كاسبر «يعرض الان تركي» ← المترجم وما لم يُذكر في «تركي مترجم يعرض الآن»، و«… مدبلج» من اسمه في «تركي مدبلج يعرض الآن»",
              sub == ["الغرفة المجاورة", "الكرامة"] and dub == ["طبيعة الحب"], str((sub, dub)))
        check("وقسمه العادي «حُدّث» كله أمس ← ليس منه شيءٌ فيهما", not any(n.startswith("مسلسل قديم") for n in sub + dub))
        sub, dub = now_of([{"cfg": cf, "label": "فالكون"}])
        check("بلا قسم «يعرض الآن» (فالكون) ← ما نزلت له حلقةٌ خلال 10 أيام، والمترجم وحده والمدبلج وحده",
              sub == ["حلقة أمس"] and dub == ["طائر الرفراف"], str((sub, dub)))
        sub, dub = now_of([{"cfg": ck, "label": "ك"}])
        check("ولوحةٌ «حدّثت» أكثر من نصف القسم معًا ← وقتها لا يدلّ: لا شيء (بدل الأعمال القديمة كلها)", sub == [] and dub == [], str(sub[:3]))
    finally:
        for srv in servers:
            srv.shutdown()


def categories():
    print("== تصنيفات سمارت سوق: رئيسيةٌ وفرعيةٌ تحتها، لكل سيرفرٍ في أقسامه، وتُحرَّر ==")
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
    books = S._books(lines)
    d = tempfile.mkdtemp(prefix="stremio_cats_")

    def row(kind, cid, b=0, bk=None):                    # صفّ تصنيفٍ (‏sqc_) في سيرفر
        bk = bk or books
        return [m["name"] for m in S.lib_catalog(bk, kind, S.CAT_PREFIX + cid + bk[b][1], {})["metas"]]
    try:
        for c in (ca, cb):
            S.warm(c)
        one = [lines[0]]
        check("‏cached_library: لا تُبنى ولا تُحمَّل (للصفحات التي لا تنتظر)", S.cached_library(one, "series") is None)
        import threading
        calls, real = [], S.LIB.build
        S.LIB.build = lambda kind, parts, **kw: (calls.append(kind), time.sleep(0.3), real(kind, parts, **kw))[2]
        try:
            ts = [threading.Thread(target=S.library, args=(one, "series", True)) for _ in range(4)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
        finally:
            S.LIB.build = real
        check("أربعة طلباتٍ متزامنة للمكتبة نفسها ← تُبنى مرةً واحدة", calls == ["series"], str(calls))
        check("وبعدها في الذاكرة", S.cached_library(one, "series") is S.library(one, "series"))
        check("«مسلسلات تركية» في سمارت ← «تركي»، و«TR | Turkish» في فالكون ← «تركي» فالكون (كلٌّ في سيرفره)",
              row("series", "s_turkish") == ["علي كارا"] and row("series", "s_turkish", 1) == ["Ali Kara - Arabic Sub", "مسلسل مدبلج"])
        check("و«-ترك» تُخرج «تركية مدبلجة عربي» من «عربي»", row("series", "s_arabic", 1) == ["مسلسل عربي"], str(row("series", "s_arabic", 1)))
        check("و«رمضان 2026» ← «عربي» ← «رمضان» (فرعي)", row("series", "s_arabic") == ["مسلسل رمضاني"] and row("series", "s_ramadan") == ["مسلسل رمضاني"])
        check("والفرعي من أعمال رئيسيّه وحدها: «مدبلج» تحت «تركي» = التركي المدبلج", row("series", "s_tr_dub", 1) == ["مسلسل مدبلج"]
              and row("series", "s_tr_sub", 1) == ["Ali Kara - Arabic Sub"])
        check("وما لم يدخل تصنيفًا ← «أخرى» (من «اكتشف»)", [m["name"] for m in S.lib_catalog(books, "series", "sq_series", {"genre": "أخرى (1)"})["metas"]]
              == ["Kurdish Show"])
        check("الأفلام: تصنيف العمل نفسه («Action» ← «أكشن») وقسم اللوحة («VOD | HORROR» ← «رعب»)",
              row("movie", "m_action") == ["Speed (1994)"] and row("movie", "m_horror", 1) == ["Scream (1996)"])
        check("والقنوات: «beIN SPORTS» ← «رياضة»، و«قنوات MBC» ← «عربية»", row("tv", "t_sports") == ["beIN SPORTS 1 HD"] and row("tv", "t_arabic", 1) == ["MBC 1"])
        check("وتصنيفٌ حُذف ← صفّه فارغ (يختفي من Stremio)", row("series", "nope") == [])
        man = S.manifest(ca, "https://g", "سمارت", lines=lines)
        rows = [(c["type"], c["name"]) for c in man["catalogs"] if c["id"].startswith(S.CAT_PREFIX)]
        check("الرئيسية أقسام: «الحسابات» ثم المسلسلات ثم الأفلام ثم القنوات — بلا صفوف تصنيفات (افتراضًا)",
              rows == [] and [c["type"] for c in man["catalogs"] if c["id"] in S.CATALOG.values() or c["id"] == S.ACCOUNTS_ID]
              == [S.ACCOUNTS, "series", "movie", "tv"], json.dumps(rows, ensure_ascii=False))
        sopts = next(e["options"] for c in man["catalogs"] if c["id"] == "sq_series" for e in c["extra"] if e["name"] == "genre")
        check("وفي «اكتشف» ← «تصنيف»: الرئيسية بأعدادها وترتيبها، ثم «أخرى»", sopts == ["تركي (1)", "عربي (1)", "أخرى (1)"],
              json.dumps(sopts, ensure_ascii=False))
        ar = next(c for c in man["catalogs"] if c["id"] == S.MAIN_PREFIX + "s_arabic")
        check("وكل رئيسيٍّ كتالوجٌ قائمته «الكل» ثم فرعيّاته التي فيها محتوى (مطلوبة: لا صفّ في الرئيسية)",
              ar["extra"][0] == {"name": "genre", "options": ["الكل (1)", "رمضان (1)"], "isRequired": True}, json.dumps(ar, ensure_ascii=False))
        mk = S._poster_maker(d, "https://g")
        lv = S.lib_catalog(books, "tv", "sq_live", {"genre": "beIN SPORTS"}, mk)["metas"]
        raw = S.crypto_store.open_token(lv[0]["poster"].rsplit("/", 1)[1][:-4], d, S.POSTER_LABEL)
        check("وقناةٌ بلا شعار: ملصقٌ عريض باسم قسمها في اللوحة", raw.startswith("w") and raw.split("\n")[2] == "beIN SPORTS", repr(raw))

        print("== صفّ «التصنيفات» أُزيل (لم يعمل «عرض الكل» في التطبيقات) ==")
        check("لا صفّ «التصنيفات» في الـmanifest ولا نوعه", S.TILES not in man["types"] and all(c["id"] != S.TILES_ID for c in man["catalogs"])
              and man["types"][:2] == [S.ACCOUNTS, "series"], json.dumps(man["types"], ensure_ascii=False))
        tok_c = S.make_token(d, ca.host, "u", "p")
        lf = lambda cfg: lines if S.host_key(cfg.host) == S.host_key(ca.host) else None   # noqa: E731
        code, body, _, _ = S.handle(d, f"/stremio/{tok_c}/catalog/{quote(S.TILES, safe='')}/{S.TILES_ID}.json", "https://g", lines_for=lf)
        check("نسخةٌ مثبّتةٌ قبل التحديث تطلبه ← فارغ (فيختفي صفّه بلا إعادة تثبيت)", code == 200 and json.loads(body) == {"metas": []}, str(code))
        code, _, _, _ = S.handle(d, f"/stremio/{tok_c}/stream/{quote(S.TILES, safe='')}/{quote(S.prefix(ca) + 'c:series:s_turkish', safe='')}.json",
                                 "https://g", lines_for=lf)
        check("وبطاقاته القديمة ← 404", code == 404, str(code))

        print("== ما حُفظ قبل الرئيسية والفرعية (LAYOUT 4) ==")
        v3 = lambda cid, name, keys, **kw: {"id": cid, "kind": "series", "name": name, "keys": keys, "genres": "", "home": False, "on": True, **kw}   # noqa: E731
        turk = v3("s_turkish", "تركي", "ترك, turk, turkish, tr")
        ram = v3("s_ramadan", "رمضان", "رمضان, ramadan")
        arab = v3("s_arabic", "عربي", K._V3["s_arabic"][1])
        mixed = v3(K.NOW_ID, "تركي يعرض الآن", "ترك, turk, turkish, tr", recent=10)
        with open(os.path.join(d, "stremio_categories.json"), "w", encoding="utf-8") as f:
            json.dump({"9": {"cats": [dict(turk, home=True), dict(ram, home=True)], "at": 1},
                       "8": {"cats": [ram, turk, arab], "at": 1, "layout": 2},
                       "7": {"cats": [mixed, ram, turk], "at": 1, "layout": 3},
                       "6": {"cats": [dict(mixed, keys="ترك, يعرض"), turk], "at": 1, "layout": 3},
                       "5": {"cats": [turk], "at": 1, "layout": 3}}, f, ensure_ascii=False)
        check("قبل LAYOUT 2: صفوفها في الرئيسية تُطفأ (تبقى داخل أقسامها)", not any(c.get("home") for c in K.get(d, "9")))
        mine1 = K.get(d, "9")
        mine1[0]["home"] = True
        K.save(d, "9", mine1)
        check("وبعده «صفٌّ في الرئيسية أيضًا» يُحفظ لمن أراده", [c["home"] for c in K.get(d, "9")][:2] == [True, False])
        g8 = K.get(d, "8")
        check("ما لم يُحرَّر يصير كالجديد: «رمضان» تحت «عربي»، و«تركي» ← «يعرض الآن مترجم» · «يعرض الآن مدبلج» · «مترجم» · «مدبلج»",
              [(c["id"], c.get("parent", "")) for c in g8] == [("s_turkish", ""), (K.NOW_ID, "s_turkish"), (K.DUB_NOW_ID, "s_turkish"),
                                                              ("s_tr_sub", "s_turkish"), ("s_tr_dub", "s_turkish"), ("s_arabic", ""),
                                                              ("s_ramadan", "s_arabic"), ("s_ar_egypt", "s_arabic"), ("s_ar_gulf", "s_arabic"),
                                                              ("s_ar_sham", "s_arabic")]
              and g8[1]["recent"] == 10 and "رمضان" in g8[5]["keys"], json.dumps([(c["id"], c.get("parent")) for c in g8], ensure_ascii=False))
        g7, g6, g5 = K.get(d, "7"), K.get(d, "6"), K.get(d, "5")
        check("و«تركي يعرض الآن» القديم (المترجم والمدبلج معًا) ← «يعرض الآن مترجم» تحت «تركي» (بلا «مدبلج»)، و«رمضان» بلا «عربي» يبقى رئيسيًّا",
              [(c["id"], c["name"], c.get("parent", "")) for c in g7][:3] == [("s_ramadan", "رمضان", ""), ("s_turkish", "تركي", ""),
                                                                              (K.NOW_ID, "يعرض الآن مترجم", "s_turkish")]
              and g7[2]["keys"] == "-مدبلج, -dubbed", json.dumps([(c["id"], c.get("parent")) for c in g7], ensure_ascii=False))
        check("وما حرّره صاحب الحساب يبقى كما هو، وما حذفه لا يعود (والجديد تحت «تركي»)",
              g6[0]["keys"] == "ترك, يعرض" and g6[0]["name"] == "تركي يعرض الآن" and not g6[0].get("parent")
              and K.NOW_ID not in [c["id"] for c in g5] and [c["id"] for c in g5][:2] == ["s_turkish", K.DUB_NOW_ID],
              json.dumps([[c["id"] for c in g6], [c["id"] for c in g5]], ensure_ascii=False))
        m = K.matcher({"keys": "ترك, tr, +مدبلج, +dubbed, -كرتون"})
        check("«+كلمة» مطلوبة مع غيرها: «ترك، +مدبلج» ← «تركي مدبلج» لا «تركي مترجم» ولا «مسلسلات مدبلجة» وحدها",
              [m(K.norm(n)) for n in ("TURKEY - تركي مدبلج", "[TR] 2026 تركي مترجم (يعرض الآن)", "Dubbed Series - مسلسلات مدبلجه",
                                      "TR Dubbed", "كرتون تركي مدبلج")] == [True, False, False, True, False])
        check("وفرعيٌّ بـ«-كلمة» وحدها: ما لا تُخرجه؛ وبلا كلماتٍ ← لا شرط على القسم", K.matcher({"keys": "-مدبلج"}, loose=True)("تركي مترجم")
              and not K.matcher({"keys": "-مدبلج"}, loose=True)("تركي مدبلج") and K.matcher({"keys": ""}, loose=True) is None)
        check("ومدته تُحرَّر (حتى 60 يومًا) وتُحفظ", K.clean([{"kind": "series", "name": "س", "keys": "x", "recent": "90"}])[0]["recent"] == 60
              and "recent" not in K.clean([{"kind": "series", "name": "س", "keys": "x", "recent": ""}])[0])

        print("== تحرير التصنيفات ==")
        mine = [{"id": "s_kurd", "kind": "series", "name": "كردي", "keys": "kurdish, كردي", "home": True},
                {"id": "s_tk", "kind": "series", "name": "تركي", "keys": "ترك, turk, tr", "home": False},
                {"id": "s_tk_dub", "kind": "series", "name": "مدبلج", "keys": "مدبلج", "parent": "s_tk"},
                {"kind": "series", "name": "مخفي", "keys": "رمضان", "home": True, "on": False}]
        own = S._books([{**lines[0], "cats": K.clean(mine)}, lines[1]])
        man2 = S.manifest(ca, "https://g", "سمارت", lines=[own[0][0]])
        rows2 = [(c["type"], c["name"]) for c in man2["catalogs"] if c["id"].startswith(S.CAT_PREFIX)]
        sopts2 = next(e["options"] for c in man2["catalogs"] if c["id"] == "sq_series" for e in c["extra"] if e["name"] == "genre")
        check("تصنيفات العميل: صفّ «كردي» وحده، و«تركي» في «اكتشف» وحدها، والمخفي لا يظهر", rows2 == [("series", "كردي")]
              and sopts2[:3] == ["كردي (1)", "تركي (1)", "أخرى (1)"], json.dumps([rows2, sopts2], ensure_ascii=False))
        check("ومحتوى صفّه من الخادم فورًا", row("series", "s_kurd", 0, own) == ["Kurdish Show"])
        check("وفرعيّه في سيرفرٍ آخر بتصنيفات الحساب نفسها", row("series", "s_tk_dub", 1, own) == ["مسلسل مدبلج"])
        bad = lambda cats: (lambda: K.clean(cats))   # noqa: E731

        def raises(f):
            try:
                f()
            except ValueError:
                return True
            return False
        check("التحقّق: اسمٌ مكرّر في الموضع نفسه، و«أخرى»، ونوعٌ غير معروف، واسمٌ فارغ، وأكثر من 60 ← خطأ",
              raises(bad([{"kind": "series", "name": "أ", "keys": "x"}, {"kind": "series", "name": "أ", "keys": "y"}]))
              and raises(bad([{"kind": "movie", "name": "أخرى", "keys": "x"}])) and raises(bad([{"kind": "x", "name": "أ"}]))
              and raises(bad([{"kind": "tv", "name": " "}])) and raises(bad([{"kind": "tv", "name": f"ت{i}"} for i in range(61)])))
        tree = K.clean([{"id": "s_a", "kind": "series", "name": "أجنبي"}, {"id": "s_b", "kind": "series", "name": "عربي"},
                        {"kind": "series", "name": "أكشن", "parent": "s_b"}, {"kind": "series", "name": "أكشن", "parent": "s_a"},
                        {"kind": "series", "name": "يتيم", "parent": "s_none"}, {"kind": "movie", "name": "نوعٌ آخر", "parent": "s_a"}])
        check("والاسم نفسه تحت رئيسيَّين مسموح، وكل فرعيٍّ بعد رئيسيّه، وفرعيٌّ رئيسيّه غائبٌ أو من نوعٍ آخر ← رئيسي",
              [(c["name"], c.get("parent", "")) for c in tree] == [("أجنبي", ""), ("أكشن", "s_a"), ("عربي", ""), ("أكشن", "s_b"), ("يتيم", ""),
                                                                   ("نوعٌ آخر", "")], json.dumps(tree, ensure_ascii=False)[:300])
        check("والاسم نفسه في نوعين مسموح، ومعرّفٌ يُصنع لما لا معرّف له", len({c["id"] for c in K.clean(
              [{"kind": "series", "name": "تركي"}, {"kind": "movie", "name": "تركي"}])}) == 2)
        K.save(d, "acct1", mine)
        check("الحفظ لحساب الأداة والقراءة", [c["name"] for c in K.get(d, "acct1")] == ["كردي", "تركي", "مدبلج", "مخفي"] and K.edited(d, "acct1")
              and [c["name"] for c in K.get(d, "acct2")] == [c["name"] for c in K.DEFAULTS] and not K.edited(d, "acct2"))
        check("و«الافتراضي» يعيده", [c["name"] for c in K.reset(d, "acct1")] == [c["name"] for c in K.DEFAULTS] and not K.edited(d, "acct1"))
    finally:
        for srv in (sa, sb):
            srv.shutdown()
        shutil.rmtree(d, ignore_errors=True)


def auto_probe():
    """«تلقائي» يفحص المصادر فقط حين يوجد بديلٌ فعلًا: القناة (صيغتاها لبثٍّ واحد) والمصدر الواحد ← التحويل مباشرةً بلا فحص (الفحص
    يفتح اتصالًا باللوحة قبل المشغّل ويؤخّر «Starting stream»)."""
    print("== «تلقائي»: لا فحص بلا بديل ==")
    calls = []
    orig_c, orig_p = S.candidates, S.probe
    S.probe = lambda url: calls.append(url) or False
    try:
        mk = lambda src, url, rank=0: {"src": src, "url": url, "rank": rank, "line": 0, "name": "x", "title": ""}   # noqa: E731
        S.candidates = lambda lines, kind, sid, pre: [mk("abc123.l5.m3u8", "U1"), mk("abc123.l5.ts", "U2")]
        check("القناة (صيغتاها) ← أولاها مباشرةً بلا فحص", S.play([], "tv", "x", "p") == "U1" and calls == [])
        S.candidates = lambda lines, kind, sid, pre: [mk("abc123.m7.mkv", "M1")]
        check("ومصدرٌ واحد ← مباشرةً بلا فحص", S.play([], "movie", "x", "p") == "M1" and calls == [])
        S.candidates = lambda lines, kind, sid, pre: [mk("abc123.m7.mkv", "M1"), mk("abc123.m8.mp4", "M2")]
        r = S.play([], "movie", "x", "p")
        check("ونسختان فعلًا ← تُفحصان (وكلتاهما معطّلة ← الأولى)", r == "M1" and calls == ["M1", "M2"], str(calls))
        check("ومهلة الفحص قصيرة (2.5 ثانية) ومصدران على الأكثر", S.PROBE_TIMEOUT <= 2.5 and S.PROBE_MAX <= 2)
        check("والقوائم في الذاكرة لا أقل من المكتبات (قائمةٌ تُطرد تعيد بناء مكتبتها)", S.LISTS_MAX >= S.LIB_MAX)
    finally:
        S.candidates, S.probe = orig_c, orig_p


def main():
    auto_probe()
    matching()
    through_addon()
    slow_line()
    movie_genres()
    disk_copy()
    akhi_and_inspect()
    now_showing()
    categories()
    print("\n" + "-" * 40)
    print(f"Result: \033[32m{_p} passed\033[0m, " + (f"\033[31m{_f} failed\033[0m" if _f else "0 failed"))
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

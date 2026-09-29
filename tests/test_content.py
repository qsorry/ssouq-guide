#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""صفحة المحتوى (content.py وcontent_page.py): قراءة ملفات M3U وإثراؤها من واجهة Xtream وصفحة /content
ولوحة المدير، بلا إنترنت (سيرفرات IPTV وهمية على 127.0.0.1، ومنها tests/mock_xtream.py).

  - القراءة: النوع من رابط Xtream ومن الاسم، والمسلسل وموسمه وحلقته بصيغها (S01E01، 1x01،
    «الموسم الخامس الحلقة 13»، «ج3 ح12»)، والسنة والجودة («The Batman (2022) FHD»)، والصورة ورقم العنصر،
    وبادئة اللغة، والفواصل، وأقسام الكبار، وgzip وCRLF وBOM، وحدّ الحجم بعد فكّ الضغط.
  - الأعداد: المسلسل في قسمين يُعدّ مرة بمواسمه كلها، والحلقة المكرّرة مرة، والمخفي من الأقسام لا يُعدّ.
  - الإثراء: التقييم والتصنيف والقصة وتاريخ الإضافة من ‏player_api.php، وما تعلّمه للكبار يسقط، وفشلها
    لا يمنع الحفظ؛ ولا بيانات دخول في الفهرس.
  - ما أُسقط للكبار (بالقسم وبالاسم وما تعلّمه الواجهة): يُحفظ للمدير وحده، لا في الفهرس ولا الصفحة ولا البحث،
    والتنبيه بما جدّ منه وحده بالبريد وواتساب، وما جرى له، ومن يصله التنبيه وتجربته.
  - الصفحة: الواجهة المتحرّكة، والأعداد، و«أضيف مؤخرًا»، وصفحة النوع والقسم والتصفية وصفحاتها، والبحث
    بالاسم وأين يوجد في السيرفرات الأخرى، ونافذة التفاصيل بمواسمها، والفهرسة للصفحة الرئيسية وحدها،
    ولا رابط ولا بيانات دخول ولا وسم من الملف، والفهرس القديم (النسخة الأولى).
  - الصور: TMDB مباشرةً، وغيرها عبر خادمنا بلا العناوين الداخلية، وتخزينها بحدّ، وما تعذّر لا يُعاد قبل يوم.
  - السيرفرات: الافتراضية الأربعة، والإضافة والتعديل والترتيب والمسح، والرابط مشفَّرًا ومخفيًّا،
    والسحب منه والفشل والدورة اليومية.
  - على خادم حيّ: الرفع (خامًا ومضغوطًا) وصلاحياته، والرابط من سيرفر Xtream وهمي، والصفحات والصور
    والواجهات، وخريطة الموقع، والنطاقان — والتنبيه يصل فعلًا ببريدٍ وهمي (SMTP) وخدمة واتساب وهمية.

تشغيل:  python tests/test_content.py
"""
import base64
import email
import email.policy
import gzip
import html as _html
import http.server
import json
import os
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import content as C  # noqa: E402
import content_page as P  # noqa: E402
import mock_xtream  # noqa: E402

_api_open = C._api_open


def _offline_api(xt, action):
    """بلا إنترنت: واجهة Xtream من السيرفرات الوهمية المحلية وحدها، وغيرها (panel.example في العيّنة) يفشل فورًا."""
    if not xt[0].startswith("http://127.0.0.1:"):
        raise urllib.error.URLError("offline test")
    return _api_open(xt, action)


C._api_open = _offline_api

_p = _f = 0


def check(l, c, x=""):
    global _p, _f
    print((f"  \033[32mPASS\033[0m  {l}" if c else f"  \033[31mFAIL\033[0m  {l}") + (f"  ({x})" if x else ""))
    _p += 1 if c else 0
    _f += 0 if c else 1


HOST = "http://panel.example:8080"
CRED = "user123/pass456"


def entry(title, group, kind="live", n=1, attrs=""):
    path = {"live": f"live/{CRED}/{n}.ts", "movie": f"movie/{CRED}/{n}.mkv", "series": f"series/{CRED}/{n}.mkv"}[kind]
    return f'#EXTINF:-1 tvg-id="" tvg-name="{title}" tvg-logo="{HOST}/images/{n}.png" group-title="{group}"{attrs},{title}\n{HOST}/{path}\n'


SAMPLE = ("#EXTM3U\n"
          + entry("##### ARABIC #####", "AR | MBC", n=1)
          + entry("AR: MBC 1 HD", "AR | MBC", n=2)
          + entry("AR: MBC 1 HD", "AR | MBC", n=3)
          + entry("AL Jazeera", "AR | News", n=4)
          + entry("|AR| beIN SPORTS 1 ᴴᴰ", "beIN SPORTS", n=5)
          + entry("Hot Stuff", "XXX | Adults", n=6)
          + entry("Night Club", "For Adults +18", n=7)
          + entry("The Batman (2022)", "VOD | English Movies", "movie", 8)
          + '#EXTINF:-1 tvg-name="Love, Death" group-title="VOD | English Movies",Love, Death & Robots: The Movie (2021)\n'
          + f"{HOST}/movie/{CRED}/9.mp4\n"
          + entry("الفيل الأزرق ج2", "أفلام عربية", "movie", 10)
          + entry("Horror Night", "Movies 2018+", "movie", 11)
          + entry("Breaking Bad S01 E01", "SERIES | Drama", "series", 12)
          + entry("Breaking Bad S01 E02", "SERIES | Drama", "series", 13)
          + entry("Breaking Bad S01 E02", "SERIES | Drama", "series", 14)
          + entry("EN - Breaking Bad S02 E01", "SERIES | Drama", "series", 15)
          + entry("Breaking Bad S02 E02", "Netflix", "series", 16)
          + entry("Breaking Bad S03 E01", "Netflix", "series", 17)
          + entry("Sex Education S01 E01", "Netflix", "series", 18)
          + entry("Seinfeld S03E05", "SERIES | Comedy", "series", 19)
          + entry("المؤسس عثمان الموسم ٥ الحلقة ١٢", "مسلسلات رمضان 2026", "series", 20)
          + entry("المؤسس عثمان الموسم الخامس الحلقة 13", "مسلسلات رمضان 2026", "series", 21)
          + entry("باب الحارة ج3 ح12", "مسلسلات شامية", "series", 22)
          + entry("قيامة أرطغرل الحلقة 45", "مسلسلات تركية", "series", 23)
          + entry("The 100 S01E01", "Old panel", "movie", 24)
          + entry("Stranger Things 1x03", "Old panel", "series", 25)
          + entry('<script>alert(1)</script> S01 E01', "SERIES | Drama", "series", 26)
          + "#EXTINF:-1,Plain Channel\nhttp://1.2.3.4/stream\n"
          + '#EXTINF:0 tvg-id=unquoted tvg-name="Odd, Name" group-title="Misc",Odd Title\nhttp://1.2.3.4/stream2\n')


def reader(data):
    import io
    return io.BytesIO(data).read


def catalog(text):
    return C.parse(reader(text.encode("utf-8")))


def items(cat, kind):
    return {g["name"]: g["items"] for g in cat[kind]}


def names(cat, kind):
    return {g["name"]: [it["n"] for it in g["items"]] for g in cat[kind]}


def seasons(cat):
    return {g["name"]: {it["n"]: it["s"] for it in g["items"]} for g in cat["series"]}


def fresh():
    d = tempfile.mkdtemp(prefix="content_")
    C._cache.clear()
    C._found.clear()
    C._busy.clear()
    return d


def unit_parse():
    print("سطر ‏#EXTINF")
    a, t = C._extinf('#EXTINF:-1 tvg-name="a,b" group-title="G | 1",Love, Death & Robots')
    check("الفاصلة في القيمة وفي العنوان لا تقطعهما", a == {"tvg-name": "a,b", "group-title": "G | 1"}
          and t == "Love, Death & Robots", (a, t))
    a, t = C._extinf('#EXTINF:0 tvg-id=x tvg-name="Odd, Name" group-title="Misc",Odd Title')
    check("خصائص بلا تنصيص: العنوان بعد آخر قيمة", a.get("group-title") == "Misc" and t == "Odd Title", (a, t))
    check("بلا خصائص", C._extinf("#EXTINF:-1,Just Title") == ({}, "Just Title"))

    print("الاسم")
    for raw, want in [("AR: MBC 1 HD", "MBC 1 HD"), ("|EN| Breaking Bad", "Breaking Bad"), ("[TR] Kurulus Osman", "Kurulus Osman"),
                      ("EN - The Office", "The Office"), ("UK: BBC One", "BBC One"), ("|AR| 4K: beIN 1", "beIN 1"),
                      ("AL Jazeera", "AL Jazeera"), ("AL-Arabiya", "AL-Arabiya"), ("CSI: Miami", "CSI: Miami"),
                      ("It: Chapter Two", "It: Chapter Two"), ("USA Network", "USA Network"), ("AR:", "AR:"),
                      ("  MBC\u202e 2  ", "MBC 2")]:
        check(f"«{raw.strip()}» ← «{want}»", C._clean(raw) == want, C._clean(raw))

    print("المسلسل وموسمه وحلقته")
    cases = [("Breaking Bad S01 E01", ("Breaking Bad", 1, 1, True)), ("Seinfeld S03E05", ("Seinfeld", 3, 5, True)),
             ("Supernatural Season 3 Episode 4", ("Supernatural", 3, 4, True)), ("S.W.A.T. S02-E07", ("S.W.A.T", 2, 7, True)),
             ("Stranger Things 1x03", ("Stranger Things", 1, 3, False)),
             ("المؤسس عثمان الموسم ٥ الحلقة ١٢", ("المؤسس عثمان", 5, 12, True)),
             ("المؤسس عثمان الموسم الخامس الحلقة 13", ("المؤسس عثمان", 5, 13, True)),
             ("باب الحارة ج3 ح12", ("باب الحارة", 3, 12, False)), ("قيامة أرطغرل الحلقة 45", ("قيامة أرطغرل", 0, 45, True)),
             ("Dark (2017) - S01E01 - Secrets", ("Dark (2017)", 1, 1, True)), ("Show E05", ("Show", 0, 5, False)),
             ("الفيل الأزرق ج2", ("الفيل الأزرق", 2, None, False))]
    for title, want in cases:
        ep = C._episode(title)
        got = (C._tidy(ep[0]), ep[1], ep[2], ep[3]) if ep else None
        check(f"«{title}»", got == want, got)
    check("فيلمٌ بلا علامة", C._episode("The Batman (2022)") is None and C._episode("Rocky 2") is None
          and C._episode("Star Wars: Episode IV") is None)

    print("الفهرس")
    cat = catalog(SAMPLE)
    ss, m, lv = seasons(cat), names(cat, "movie"), names(cat, "live")
    check("الأعداد الخام", cat["n"] == {"series": 15, "movie": 4, "live": 6}, cat["n"])
    check("الكبار والفواصل تسقط", cat["skipped"] == {"adult": 2, "sep": 1, "bad": 0}, cat["skipped"])
    check("قسم الكبار لا يُحفظ اسمه", "XXX | Adults" not in json.dumps(cat) and "Night Club" not in json.dumps(cat))
    dr = C._run(reader(SAMPLE.encode("utf-8"))).dropped()
    check("وما أُسقط للمدير: القسمان بعددهما", dr["groups"] == [["XXX | Adults", 1], ["For Adults +18", 1]]
          and dr["titles"] == [] and dr["count"] == 2 and dr["more"] == 0 and len(dr["marks"]) == 2, dr)
    dr = C._run(reader(("#EXTM3U\n" + entry("xXx (2002)", "VOD | English Movies", "movie", 1)
                        + entry("xXx (2002)", "VOD | 4K", "movie", 2)).encode())).dropped()
    check("والاسم من قسمٍ عادي بقسمه، والمكرّر مرة بعدده", dr["titles"] == [["xXx (2002)", "VOD | English Movies", 2]]
          and dr["groups"] == [] and dr["count"] == 2 and dr["more"] == 0, dr)
    check("«Movies 2018+» ليس قسم كبار", "Horror Night" in m.get("Movies 2018+", []))
    check("«Sex Education» في قسمٍ عادي يبقى", "Sex Education" in ss["Netflix"])
    check("القناة بجوداتها واحدة وبلا بادئة", lv["AR | MBC"] == ["MBC 1"] and lv["beIN SPORTS"] == ["beIN SPORTS 1"], lv)
    check("«AL Jazeera» كما هي", lv["AR | News"] == ["AL Jazeera"])
    check("بلا قسم ← «بلا قسم»", lv.get("بلا قسم") == ["Plain Channel"])
    check("المواسم وحلقاتها، والمكرّرة تُعدّ مرة", ss["SERIES | Drama"]["Breaking Bad"] == [[1, 2], [2, 1]])
    check("الأقسام بترتيب ظهورها", [g["name"] for g in cat["series"]][:3] == ["SERIES | Drama", "Netflix", "SERIES | Comedy"])
    mv = {it["n"]: it for g in cat["movie"] for it in g["items"]}
    check("الفيلم: الاسم بلا سنة، والسنة والصورة ورقمه", mv["The Batman"] == {"n": "The Batman", "y": 2022,
          "p": f"{HOST}/images/8.png", "i": 8}, mv.get("The Batman"))
    check("الفيلم بفاصلته، وبلا صورةٍ لا مفتاح لها", mv["Love, Death & Robots: The Movie"] == {"n": "Love, Death & Robots: The Movie",
          "y": 2021, "i": 9}, mv.get("Love, Death & Robots: The Movie"))
    check("«ج2» في رابط فيلم يبقى فيلمًا", m["أفلام عربية"] == ["الفيل الأزرق ج2"])
    bb = next(it for it in items(cat, "series")["SERIES | Drama"] if it["n"] == "Breaking Bad")
    check("المسلسل: أكبر رقم حلقةٍ وأول صورة", bb["i"] == 15 and bb["p"] == f"{HOST}/images/12.png", bb)
    check("حلقةٌ برابط فيلم (لوحة قديمة) تُقرأ حلقة", ss["Old panel"] == {"The 100": [[1, 1]], "Stranger Things": [[1, 1]]})
    check("الموسم بالعربية والأرقام الهندية", ss["مسلسلات رمضان 2026"] == {"المؤسس عثمان": [[5, 2]]})
    check("الحلقة بلا موسم = الموسم 0", ss["مسلسلات تركية"] == {"قيامة أرطغرل": [[0, 1]]})
    dump = json.dumps(cat, ensure_ascii=False)
    check("لا بيانات دخول في الفهرس", "pass456" not in dump and "user123" not in dump)
    check("ولا روابط تشغيل: الصور وحدها", all("/images/" in u for u in re.findall(r"https?://[^\"]*", dump)),
          re.findall(r"https?://[^\"]*", dump)[:3])
    c3, xt = C._parse(reader(SAMPLE.encode("utf-8")))
    check("بيانات واجهة Xtream من روابط الملف، خارج الفهرس", xt == (HOST, "user123", "pass456") and c3 == cat)

    print("ملفات أخرى")
    other = ("\ufeff#EXTM3U\r\n#EXTINF:-1,Show S02E03\r\nhttps://cdn.example/show/203.m3u8\r\n"
             "#EXTINF:-1,Some Film (2019)\r\nhttps://cdn.example/films/film.mp4?token=1\r\n"
             "#EXTGRP:News\r\n#EXTINF:-1,Channel One\r\nhttps://cdn.example/live/one.m3u8\r\n"
             "#EXTINF:-1,Channel Two\r\n#EXTVLCOPT:http-user-agent=x\r\nhttps://cdn.example/two.ts\r\n")
    c2 = catalog(other)
    check("BOM وCRLF و‏#EXTGRP وسطر خيارات قبل الرابط", names(c2, "live").get("News") == ["Channel One", "Channel Two"],
          names(c2, "live"))
    check("بلا Xtream: الحلقة من اسمها والفيلم من امتداده", items(c2, "series") == {"بلا قسم": [{"n": "Show", "i": 203, "s": [[2, 1]]}]}
          and items(c2, "movie") == {"بلا قسم": [{"n": "Some Film", "y": 2019}]}, (items(c2, "series"), items(c2, "movie")))
    check("ولا بيانات واجهة بلا روابط Xtream", C._parse(reader(other.encode("utf-8")))[1] is None)
    gz = gzip.compress(SAMPLE.encode("utf-8"))
    check("gzip يُفكّ وهو يُقرأ", C.parse(reader(gz)) == cat)
    check("سطورٌ بين قطعتين", C.parse(reader(SAMPLE.encode("utf-8"))) == cat
          and list(C.iter_lines(reader(b"a\nb\r\nc\rd"), chunk=1)) == ["a", "b", "c", "d"])
    try:
        list(C.iter_lines(reader(gzip.compress(b"x" * 5000)), limit=1000, chunk=64))
        check("حدّ الحجم بعد فكّ الضغط", False)
    except ValueError:
        check("حدّ الحجم بعد فكّ الضغط", True)
    for bad, what in [(gz[:len(gz) // 2], "ناقص"), (b"\x1f\x8b" + b"not really gzip" * 10, "تالف")]:
        try:
            C.parse(reader(bad))
            check(f"gzip {what} يُرفض ولا يُحفظ نصفه", False)
        except ValueError as e:
            check(f"gzip {what} يُرفض ولا يُحفظ نصفه", what in str(e), str(e))
    check("ملفٌّ فارغ أو صفحة خطأ: لا عناصر", catalog("<html>403 Forbidden</html>")["entries"] == 0
          and catalog("")["entries"] == 0)

    check("رابط الصورة: المسافة مرمَّزة، وغير الرابط يسقط", C._poster(" http://h/logos/MBC 1.png ") == "http://h/logos/MBC%201.png"
          and C._poster("https://image.tmdb.org/t/p/w600/a.jpg") == "https://image.tmdb.org/t/p/w600/a.jpg"
          and C._poster("javascript:alert(1)") == "" and C._poster('http://h/a".png') == "" and C._poster("") == "")

    print("البحث والعدّ")
    check("الهمزات والتشكيل والتاء المربوطة", C._norm("أُسامة") == C._norm("اسامه") == "اسامه")
    check("حالة الأحرف والرموز والأرقام", C._norm("Breaking-Bad ᴴᴰ ٢") == "breaking bad hd 2", C._norm("Breaking-Bad ᴴᴰ ٢"))
    forms = [(1, "مسلسل واحد"), (2, "مسلسلان"), (3, "3 مسلسلات"), (10, "10 مسلسلات"), (11, "11 مسلسلًا"),
             (100, "100 مسلسل"), (101, "101 مسلسل"), (103, "103 مسلسلات"), (111, "111 مسلسلًا"),
             (3210, "3,210 مسلسلات"), (12345, "12,345 مسلسلًا")]
    check("العدد ومعدوده", all(C._count(n, C.N_SERIES) == w for n, w in forms),
          [C._count(n, C.N_SERIES) for n, _ in forms])


def seed(d, key="smart", text=SAMPLE):
    return C.ingest(d, key, reader(text.encode("utf-8")), "file", "sample.m3u")


def unit_store():
    print("السيرفرات")
    d = fresh()
    check("الأربعة الافتراضية بترتيبها", [s["key"] for s in C.servers(d)] == ["kon", "casper", "smart", "falcon"]
          and [s["name"] for s in C.servers(d)] == ["كون", "كاسبر", "سمارت", "فالكون"])
    k = C.save_server(d, {"new": True, "name": "  نجم   تي في ", "key": "najm", "full": "NAJM TV"})
    check("إضافة سيرفر برابطه", k == "najm" and C._server(d, "najm")["name"] == "نجم تي في")
    for form, err in [({"new": True, "name": "x", "key": "najm"}, "لسيرفرٍ آخر"),
                      ({"new": True, "name": "x", "key": "نجم"}, "حروفٌ إنجليزية"),
                      ({"new": True, "name": "", "key": "zz"}, "اسم السيرفر"),
                      ({"new": True, "name": "x", "buy": "javascript:alert(1)"}, "رابط الشراء"),
                      ({"name": "x", "key": "nope"}, "غير معروف")]:
        try:
            C.save_server(d, form)
            check(f"يُرفض: {err}", False)
        except ValueError as e:
            check(f"يُرفض: {err}", err in str(e), str(e))
    check("بلا رابط: مفتاحٌ يُولَّد", C.save_server(d, {"new": True, "name": "آخر"}) == "server-1")
    C.save_server(d, {"key": "najm", "name": "نجم", "buy": "https://ssouq.com/p1"})
    check("تعديل الاسم ورابط الشراء", C._server(d, "najm")["name"] == "نجم" and C._server(d, "najm")["buy"] == "https://ssouq.com/p1")
    C.move_server(d, "najm", -1)
    check("الترتيب", [s["key"] for s in C.servers(d)][3:5] == ["najm", "falcon"], [s["key"] for s in C.servers(d)])
    C.clear(d, "server-1", drop=True)
    check("حذف سيرفر", C._server(d, "server-1") is None)

    print("الرابط")
    url = "http://panel.example:8080/get.php?username=user123&password=pass456&type=m3u_plus"
    for bad in ("ftp://x/y", "panel.example/get.php", "http://"):
        try:
            C.set_url(d, "smart", bad)
            check(f"رابطٌ غير صالح يُرفض: {bad}", False)
        except ValueError:
            check(f"رابطٌ غير صالح يُرفض: {bad}", True)
    C.set_url(d, "smart", url)
    raw = open(os.path.join(d, "content", "settings.json"), encoding="utf-8").read()
    check("يُحفظ مشفَّرًا", "pass456" not in raw and "user123" not in raw and C.url_of(d, "smart") == url)
    check("ويُعرض مخفيًّا", C.mask_url(url) == "http://panel.example:8080/•••")
    st = C.admin_state(d)
    check("حال المدير بلا بيانات الدخول", "pass456" not in json.dumps(st) and
          next(s for s in st["servers"] if s["key"] == "smart")["url"] == "http://panel.example:8080/•••")
    C.set_url(d, "smart", "")
    check("حذف الرابط", C.url_of(d, "smart") == "")

    print("الإدخال والأعداد")
    res = seed(d)
    check("ملخّص الإدخال", res["entries"] == 25 and res["skipped"]["adult"] == 2, res)
    v = C._view(d, "smart")[1]
    check("المسلسل في قسمين يُعدّ مرة، ومواسمه اتحادها", v["counts"]["series"] == 9
          and v["counts"]["seasons"] == 11 and v["counts"]["episodes"] == 13, v["counts"])
    check("الأفلام والقنوات بلا تكرار", v["counts"]["movie"] == 4 and v["counts"]["live"] == 5, v["counts"])
    try:
        C.ingest(d, "smart", reader(b"<html>expired</html>"), "file")
        check("ملفٌّ بلا عناصر يُرفض", False)
    except ValueError:
        check("ملفٌّ بلا عناصر يُرفض ويبقى المحتوى", C._view(d, "smart")[1]["counts"]["series"] == 9)
    try:
        C.ingest(d, "nope", reader(SAMPLE.encode()), "file")
        check("سيرفرٌ لا وجود له", False)
    except ValueError:
        check("سيرفرٌ لا وجود له", True)
    C._claim("smart", "read")
    try:
        seed(d)
        check("قراءتان معًا لا تجوزان", False)
    except C.Busy:
        check("قراءتان معًا لا تجوزان", True)
    C._release("smart")

    drama = next(g for g in v["cat"]["series"] if g["name"] == "SERIES | Drama")
    C.set_hidden(d, "smart", drama["id"], True)
    v2 = C._view(d, "smart")[1]
    check("القسم المخفي لا يُعدّ ولا يُعرض", drama["id"] not in v2["byid"]["series"]
          and v2["counts"]["series"] == 8 and P.render(d, "smart", {"t": "series", "g": drama["id"]})[0] == 404, v2["counts"])
    check("وحال المدير يعلّمه مخفيًّا", [g for g in next(s for s in C.admin_state(d)["servers"] if s["key"] == "smart")
                                         ["groups"]["series"] if g[0] == drama["id"]][0][3] is True)
    C.set_hidden(d, "smart", drama["id"], False)
    check("ويعود بإظهاره", C._view(d, "smart")[1]["counts"]["series"] == 9)
    C.clear(d, "smart")
    check("مسح المحتوى يخفي الصفحة ويُبقي السيرفر", C._view(d, "smart")[1] is None and C._server(d, "smart"))
    shutil.rmtree(d, ignore_errors=True)


def wait_alert(d, key, after, t=5.0):
    """ما أُسقط بعد أن يُحفظ فيه تنبيهٌ أُرسل بعد `after` (التنبيه في خيطٍ مستقل)."""
    for _ in range(int(t / .05)):
        a = C._adult_view(d, key)
        if a and (a.get("alert") or {}).get("at", 0) >= after:
            return a
        time.sleep(.05)
    return C._adult_view(d, key) or {}


def unit_adult():
    print("ما أُسقط للكبار والتنبيه به")
    d = fresh()
    sent, ev = [], threading.Event()

    def fake(subject, body):
        sent.append((subject, body))
        ev.set()
        return {"mail": {"ok": True, "to": "me@example.com"}, "wa": {"ok": False, "to": "966500000000", "error": "رقم المسابقة غير مربوط"}}

    C.notifier = fake
    try:
        t0 = time.time()
        seed(d)
        check("تنبيهٌ بأول ما أُسقط", ev.wait(5) and len(sent) == 1, len(sent))
        subject, body = sent[0]
        check("العنوان باسم السيرفر", subject == "تنبيه: محتوى للكبار في ملف سيرفر سمارت (حُذف ولم يُنشر)", subject)
        check("والنص بالقسمين وعددهما، وأنه لم يُنشر", "• XXX | Adults (عنصر واحد)" in body
              and "• For Adults +18 (عنصر واحد)" in body and "ولم يُنشر" in body
              and "لم يكن في سحبه السابق" not in body and "المحذوف للكبار من ملفه كله: عنصران." in body, body)
        a = wait_alert(d, "smart", t0)
        check("وما جرى يُحفظ للمدير", a.get("alert", {}).get("mail", {}).get("ok") is True
              and a["alert"]["wa"]["error"] == "رقم المسابقة غير مربوط", a.get("alert"))
        sm = next(s for s in C.admin_state(d)["servers"] if s["key"] == "smart")
        check("حال المدير: ما أُسقط بأقسامه، بلا بصماته", sm["adult"]["groups"] == [["XXX | Adults", 1], ["For Adults +18", 1]]
              and sm["adult"]["count"] == 2 and sm["adult"]["source"] == "file" and "marks" not in sm["adult"], sm["adult"])
        raw = open(C._cat_path(d, "smart"), encoding="utf-8").read()
        html = P.render(d, "smart", {})[1].decode("utf-8")
        check("وليس في فهرس الصفحة ولا فيها ولا في بحثها", "Adults" not in raw and "Night Club" not in raw
              and "Adults" not in html and all(f"لا يوجد «{q}»" in P.api_search(d, "smart", q)["html"]
                                               for q in ("Hot Stuff", "Night Club", "Adults")))

        sent.clear()
        ev.clear()
        seed(d)
        check("السحب التالي بلا جديد: لا تنبيه", not ev.wait(.5) and not sent)
        t1 = time.time()
        seed(d, text=SAMPLE + entry("xXx: Return of Xander Cage (2017)", "VOD | English Movies", "movie", 90))
        check("وما جدّ وحده", ev.wait(5) and "• xXx: Return of Xander Cage (2017) — في «VOD | English Movies»" in sent[0][1]
              and "XXX | Adults" not in sent[0][1] and "لم يكن في سحبه السابق" in sent[0][1]
              and "من ملفه كله: 3 عناصر." in sent[0][1], sent[0][1] if sent else "")
        a = wait_alert(d, "smart", t1)
        check("والاسم المحذوف من قسمٍ عادي بقسمه", a.get("titles") == [["xXx: Return of Xander Cage (2017)", "VOD | English Movies", 1]]
              and a.get("count") == 3 and a.get("alert", {}).get("at", 0) >= t1, a)

        sent.clear()
        ev.clear()
        seed(d, text="#EXTM3U\n" + entry("MBC 1", "AR | MBC", n=1))
        check("ملفٌّ بلا شيءٍ للكبار يمحو السجل ولا يُنبَّه به", C._adult_view(d, "smart") is None and not ev.wait(.3))
        t2 = time.time()
        seed(d)
        check("وما يعود بعده يُنبَّه به", ev.wait(5) and "لم يكن في سحبه السابق" not in sent[0][1])
        wait_alert(d, "smart", t2)

        C.notifier = lambda s, b: 1 / 0
        t3 = time.time()
        seed(d, "kon")
        a = wait_alert(d, "kon", t3)
        check("فشل التنبيه يُحفظ سببه ولا يُسقط الإدخال", "division" in a.get("alert", {}).get("error", "")
              and C._view(d, "kon")[1]["counts"]["series"] == 9, a.get("alert"))
        C.clear(d, "kon")
        check("مسح المحتوى يمسح ما أُسقط", not os.path.exists(C._adult_path(d, "kon")))

        C.notifier = fake
        sent.clear()
        ev.clear()
        many = ("#EXTM3U\n" + "".join(entry(f"Clip {i}", f"XXX | Studio {i:03d}", n=i) for i in range(250))
                + "".join(entry(f"Brazzers Night {i}", "VOD | Mix", "movie", 1000 + i) for i in range(20))
                + entry("Normal News", "News", n=5000))
        t4 = time.time()
        seed(d, "falcon", many)
        a = wait_alert(d, "falcon", t4)
        check("الحدّ: 200 قسم والباقي عدد", len(a.get("groups") or []) == C.ADULT_LIST and a.get("more") == 50
              and len(a.get("titles") or []) == 20 and a.get("count") == 270, (len(a.get("groups") or []), a.get("more")))
        body = sent[0][1] if sent else ""
        check("والتنبيه بأوّلها وعدد الباقي", body.count("• XXX | Studio") == C.ALERT_LINES
              and body.count("• Brazzers Night") == C.ALERT_LINES and "• و240 غيرها في صفحة المحتوى" in body, body[-200:])

        print("من يصله التنبيه")
        check("لم يُحفظ بعد", C.alert_to(d) is None)
        C.save_alert_to(d, "me@example.com", "966500000000")
        C.save_server(d, {"new": True, "name": "نجم", "key": "najm"})
        check("يُحفظ، ويبقى بعد حفظ السيرفرات", C.alert_to(d) == {"mail": "me@example.com", "wa": "966500000000"}
              and C._server(d, "najm") is not None)
        C.alert_info = lambda: {"mail": "me@example.com"}
        check("وحاله مع حال المدير", C.admin_state(d)["alert"] == {"mail": "me@example.com"})
        C.alert_info = lambda: 1 / 0
        check("وتعذّره لا يُسقط الصفحة", C.admin_state(d)["alert"] is None)
    finally:
        C.notifier = C.alert_info = None
        shutil.rmtree(d, ignore_errors=True)


def big(n_movies=650, prefix="Film"):
    return "#EXTM3U\n" + "".join(entry(f"{prefix} {i:04d} (2020)", "VOD | Big", "movie", 1000 + i) for i in range(n_movies))


def titles(html):
    """أسماء البطاقات بترتيبها."""
    return re.findall(r'<h3 dir="auto">(.*?)</h3>', html)


def section(html, head):
    """الصفّ أو القسم الذي عنوانه head إلى الذي يليه."""
    i = html.index(f"<h2>{head}</h2>")
    j = html.find('<section class="', i)
    return html[i:j if j > 0 else len(html)]


def cards(html):
    """ما في نافذة التفاصيل لكل بطاقة (‏data-d)."""
    return [json.loads(_html.unescape(x)) for x in re.findall(r'data-d="([^"]*)"', html)]


def page(d, key, **q):
    code, body, _ = P.render(d, key, q)
    return code, body.decode("utf-8")


def unit_render():
    print("الصفحة الرئيسية للسيرفر")
    d = fresh()
    seed(d)
    seed(d, "falcon", "#EXTM3U\n" + entry("Only In Falcon S01 E01", "Falcon Series", "series", 1)
         + entry("Breaking Bad S05 E01", "Falcon Series", "series", 2) + big(650))
    code, body, age = P.render(d, "smart", {})
    html = body.decode("utf-8")
    check("200 ومخزَّنة عشر دقائق", code == 200 and age == 600)
    check("العنوان والوصف بالأعداد", "<title>محتوى اشتراك سمارت: المسلسلات بمواسمها والأفلام والقنوات | سمارت سوق</title>" in html
          and "9 مسلسلات بمواسمها و4 أفلام و5 قنوات" in html)
    check("تُفهرس ولها canonical", 'content="index, follow' in html and
          '<link rel="canonical" href="https://guide.ssouq.com/content/smart">' in html)
    check("السيرفرات التي لها محتوى، كلٌّ بشعاره واسمه", '<a href="/content/smart" aria-current=page><img class="lg" '
          'src="/static/img/brands/smart.webp"' in html and "<b>سمارت</b><small>MR7 TV</small>" in html
          and '<a href="/content/falcon"><img class="lg" src="/static/img/brands/falcon.webp"' in html
          and "<b>فالكون</b><small>FALCON TV PRO</small>" in html and "/content/kon" not in html)
    check("الرأس: الأنواع و«أضيف مؤخرًا» والبحث", '<a href="/content/smart" class=home aria-current=page>الرئيسية</a>' in html
          and '<a href="/content/smart?t=series">المسلسلات</a>' in html and '<a href="/content/smart?t=new">أضيف مؤخرًا</a>' in html
          and '<form class="search" role="search" action="/content/smart" method="get">' in html)
    check("خانات الأعداد", all(f"<b>{n}</b><small>{w}</small>" in html for n, w in
                               (("4", "أفلام"), ("9", "مسلسلات"), ("5", "قنوات"), ("13", "حلقة"), ("11", "موسمًا"))))
    check("تبويبات الأنواع بأعدادها", "المسلسلات <small>9</small></a>" in html and "الأفلام <small>4</small></a>" in html
          and "القنوات <small>5</small></a>" in html)
    first = re.search(r'class="slide on".*?<h2 dir="auto">(.*?)</h2>', html, re.S)
    check("الواجهة: أحدث ما له صورة، ثلاثة أفلام ومسلسلان", html.count('<article class="slide') == 5
          and html.count('class="slide on"') == 1 and first and first.group(1) == "Horror Night"
          and html.count('<button type="button" data-go=') == 9, first and first.group(1))
    check("أحدث الأفلام برقمها في اللوحة", titles(section(html, "أفلام أضيفت مؤخرًا"))
          == ["Horror Night", "الفيل الأزرق ج2", "Love, Death &amp; Robots: The Movie", "The Batman"],
          titles(section(html, "أفلام أضيفت مؤخرًا")))
    rs = titles(section(html, "مسلسلات جديدة أو بحلقاتٍ جديدة"))
    check("والمسلسلات بآخر حلقة، والمسلسل في قسمين مرة", rs[:3] == ["&lt;script&gt;alert(1)&lt;/script&gt;", "Stranger Things", "The 100"]
          and rs.count("Breaking Bad") == 1 and len(rs) == 9, rs)
    check("والقنوات", titles(section(html, "قنوات أضيفت مؤخرًا")) == ["beIN SPORTS 1", "AL Jazeera", "MBC 1"])
    check("صفٌّ لكل قسم برابط «عرض الكل»", "<h2>VOD | English Movies <small>· فيلم</small></h2>" in html
          and "عرض الكل (2)" in html and html.count('class="more"') == 3 + 3 + 3 + 2)
    bb = next(x for x in cards(html) if x["n"] == "Breaking Bad")
    check("المسلسل بمواسمه كلها من قسميه، وحلقات كل موسم", bb["ss"] == "3 مواسم · 4 حلقات"
          and bb["sc"] == ["الموسم 1 (حلقتان)", "الموسم 2 (حلقة واحدة)", "الموسم 3 (حلقة واحدة)"], bb)
    check("والبطاقة بعدد مواسمه", '<h3 dir="auto">Breaking Bad</h3><p class="sub">3 مواسم</p>' in html)
    ertugrul = next(x for x in cards(html) if x["n"] == "قيامة أرطغرل")
    check("وبلا موسم: حلقاته وحدها", ertugrul["ss"] == "حلقة واحدة" and "sc" not in ertugrul, ertugrul)
    bat = next(x for x in cards(html) if x["n"] == "The Batman")
    u8 = C.img_hash(HOST + "/images/8.png")
    check("الفيلم بسنته وقسمه وصورته عبر خادمنا", bat == {"k": "movie", "n": "The Batman", "y": 2022, "c": "VOD | English Movies",
                                                   "p": f"/content/smart/img/{u8}"} and f'src="/content/smart/img/{u8}"' in html, bat)
    check("الجانب: «أضيف مؤخرًا» مرقّمة وباقات سمارت بحملة الصفحة", html.count('<span class="n">') == 6
          and "p2091471394?utm_source=guide.ssouq.com&amp;utm_medium=referral&amp;utm_campaign=content" in html
          and 'data-cta="https://' in html)
    check("لا رابط ولا بيانات دخول ولا وسم من الملف", "pass456" not in html and "user123" not in html and "panel.example" not in html
          and "<script>alert(1)" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html)

    print("صفحة النوع والقسم")
    code, html = page(d, "smart", t="series")
    check("صفحة المسلسلات: الأقسام صورًا ثم صفٌّ لكل قسم", code == 200 and html.count('<a class="chip"') == 7
          and 'class="chip more"' not in html and html.count("عرض الكل (") == 7
          and '<a href="/content/smart?t=series" aria-current=page>المسلسلات</a>' in html)
    check("وتصفيتها: القسم والترتيب، وبلا سنةٍ ولا تقييمٍ لا خانة لهما", "تصفية المسلسلات" in html and 'name="g"' in html
          and 'name="sort"' in html and 'name="y"' not in html and 'name="r"' not in html
          and '<input type="hidden" name="t" value="series"><input type="hidden" name="view" value="grid">' in html)
    check("لا تُفهرس ولا canonical لها", 'content="noindex, follow"' in html and 'rel="canonical"' not in html)
    drama = C._view(d, "smart")[1]["kinds"]["series"][0]
    code, html = page(d, "smart", t="series", g=drama["id"])
    check("صفحة القسم: الأحدث أولًا", code == 200 and "<h1>SERIES | Drama</h1>" in html and "مسلسلان" in html
          and titles(html.split('<aside class="side">')[0]) == ["&lt;script&gt;alert(1)&lt;/script&gt;", "Breaking Bad"],
          titles(html))
    check("والقسم مختارٌ في التصفية", f'<option value="{drama["id"]}" selected>SERIES | Drama</option>' in html)
    code, html = page(d, "smart", t="series", g="0000000000")
    check("قسمٌ لم يعد موجودًا: 404 بالأقسام الحالية", code == 404 and "لم يعد موجودًا" in html and 'class="chip"' in html)
    code, html = page(d, "smart", t="movie", all="1")
    check("كل الأقسام", code == 200 and "<h1>أقسام الأفلام</h1>" in html and "3 أقسام" in html
          and html.count('<a class="chip"') == 3)

    print("أضيف مؤخرًا")
    code, html = page(d, "smart", t="new")
    check("صفحته: الأنواع كلها الأحدث أولًا", code == 200 and "أضيف مؤخرًا في سمارت" in html
          and '<a href="/content/smart?t=new" aria-current=page>أضيف مؤخرًا</a>' in html
          and titles(section(html, "أفلام"))[0] == "Horror Night" and titles(section(html, "قنوات")) == ["beIN SPORTS 1", "AL Jazeera", "MBC 1"]
          and 'content="noindex, follow"' in html)

    print("التصفية")
    code, html = page(d, "smart", t="movie", view="grid", y="2022")
    check("بالسنة", code == 200 and "<h1>الأفلام في سمارت</h1>" in html and "فيلم واحد · 2022" in html
          and titles(html.split('<aside class="side">')[0]) == ["The Batman"])
    check("وبلا نتائج", "لا نتائج بهذا الفلتر" in page(d, "smart", t="movie", view="grid", y="1999")[1])
    code, html = page(d, "smart", t="movie", view="grid", sort="az")
    check("بالاسم", titles(html.split('<aside class="side">')[0])
          == ["Horror Night", "Love, Death &amp; Robots: The Movie", "The Batman", "الفيل الأزرق ج2"])
    code, html = page(d, "smart", t="movie", view="grid", y="abc", r="99", sort="evil", p="-3")
    check("وقيمٌ غير صالحة: الكل", code == 200 and len(titles(html.split('<aside class="side">')[0])) == 4)
    code, html = page(d, "smart", t="movie", view="grid", genre="x" * 99)
    check("وتصنيفٌ لا وجود له: لا نتائج", code == 200 and "لا نتائج بهذا الفلتر" in html)
    code, html = page(d, "smart", t="evil")
    check("نوعٌ لا وجود له: الرئيسية بلا فهرسة", code == 200 and "<article class=\"slide on\"" in html
          and 'content="noindex, follow"' in html)

    print("الصفحات")
    fbig = C._view(d, "falcon")[1]["kinds"]["movie"][0]["id"]
    code, html = page(d, "falcon", t="movie", g=fbig, p="2")
    main = html.split('<aside class="side">')[0]
    check("القسم صفحاتٌ من 60", code == 200 and len(titles(main)) == P.GRID and titles(main)[0] == "Film 0589"
          and "صفحة 2 من 11" in html and f"?t=movie&amp;g={fbig}&amp;p=3" in html and f"?t=movie&amp;g={fbig}&amp;p=1" in html,
          titles(main)[:1])
    code, html = page(d, "falcon", t="movie", g=fbig, p="999")
    main = html.split('<aside class="side">')[0]
    check("وآخرها بما بقي", "صفحة 11 من 11" in html and len(titles(main)) == 50 and titles(main)[-1] == "Film 0000"
          and "التالي ←" not in html)

    print("البحث بالاسم")
    r = P.api_search(d, "smart", "breaking")["html"]
    check("المسلسل مرةً بمواسمه كلها", "نتائج «breaking» في سمارت <small>نتيجة واحدة</small>" in r
          and "المسلسلات <small>(1)</small>" in r and titles(r) == ["Breaking Bad"]
          and cards(r)[0]["sc"][-1] == "الموسم 3 (حلقة واحدة)", r[:300])
    check("ويوجد أيضًا في السيرفرات الأخرى، بشعارها", 'ويوجد أيضًا في: <a href="/content/falcon?q=breaking"><img class="lg sm" '
          'src="/static/img/brands/falcon.webp"' in r and "فالكون (1)</a>" in r)
    r = P.api_search(d, "smart", "only in falcon")["html"]
    check("ما ليس هنا: أين يوجد", "لا يوجد «only in falcon» في سمارت" in r and "لكنه موجود في" in r and "فالكون (1)" in r)
    r = P.api_search(d, "smart", "عثمان")["html"]
    check("بالعربية", titles(r) == ["المؤسس عثمان"] and cards(r)[0]["sc"] == ["الموسم 5 (حلقتان)"])
    check("بلا همزة", "المؤسس عثمان" in P.api_search(d, "smart", "الموسس")["html"])
    check("وبالسنة", titles(P.api_search(d, "smart", "batman 2022")["html"]) == ["The Batman"])
    check("حرفٌ واحد لا يُبحث", P.api_search(d, "smart", "b")["html"] == "")
    r = P.api_search(d, "falcon", "film")["html"]
    check("الواسع: أولها وعددها كله", len(titles(r)) == C.SEARCH_MAX and "(650)" in r and "و610 نتائج أخرى" in r, r[:160])
    check("كل الكلمات", titles(P.api_search(d, "falcon", "film 0007")["html"]) == ["Film 0007"])
    r = P.api_search(d, "smart", "zzzz qqqq")["html"]
    check("لا نتائج", "لا يوجد «zzzz qqqq» في سمارت" in r and "جرّب جزءًا من الاسم" in r)
    code, html = page(d, "smart", q="breaking")
    check("وبلا سكربت: ?q= على الصفحة نفسها", code == 200 and '<div id="cres" aria-live="polite"><section class="results">' in html
          and 'value="breaking"' in html and 'content="noindex, follow"' in html)
    code, html = page(d, "smart", q='"><img src=x onerror=alert(1)>')
    check("والبحث مهرَّبًا", "<img src=x" not in html and "&lt;img src=x onerror=alert(1)&gt;" in html)

    print("لا محتوى")
    check("وسيرفرٌ بلا شعار: أول حرفٍ من اسمه", P._logo("kon", "كون") == '<span class="lg bi" style="--h:%d" aria-hidden="true">ك</span>'
          % P._hue("كون") and P._logo("x", "<b>")[-11:] == "&lt;</span>")
    code, body = P.render_missing(d, "kon")
    check("سيرفرٌ بلا محتوى: 404 تدلّ على غيره", code == 404 and 'href="/content/smart"' in body.decode()
          and 'href="/content/falcon"' in body.decode() and "noindex" in body.decode())
    check("وسيرفرٌ لا وجود له", P.render(d, "nope", {})[0] == 404 and P.render(d, "kon", {})[:1] == (404,)
          and P.api_search(d, "nope", "x") is None)
    check("‏/content إلى أوّلها", C.first_key(d) == "smart")
    b = C.brief(d)
    check("للرئيسية: السيرفرات وأعدادها", [s["key"] for s in b["servers"]] == ["smart", "falcon"]
          and b["servers"][0]["series"] == 9 and b["servers"][1]["movies"] == 650, b)
    check("خريطة الموقع", C.sitemap(d) == [("/content/smart", "daily", "0.7"), ("/content/falcon", "daily", "0.7")])

    print("فهرسٌ من النسخة الأولى")
    C._write(C._cat_path(d, "kon"), {
        "key": "kon", "at": time.time(), "entries": 4, "n": {"series": 3, "movie": 1, "live": 0}, "skipped": {},
        "series": [{"id": C._gid("series", "Old"), "name": "Old", "items": [["Old Show", [[1, 2], [2, 1]]]]}],
        "movie": [{"id": C._gid("movie", "Films"), "name": "Films",
                   "items": ["Old Film (2019) FHD", "Old Film (2019) HD", "Blade Runner 2049"]}],
        "live": [{"id": C._gid("live", "TV"), "name": "TV", "items": ["MBC 1 HD", "MBC 1 FHD"]}]})
    code, html = page(d, "kon")
    check("يُعرض حتى يُسحب ثانية", code == 200 and "Old Show" in html and "موسمان" in html
          and "?t=new" not in html and 'class="slide' not in html)
    check("والسنة والجودة تُفصلان منه من الآن", '<h3 dir="auto">Old Film</h3><p class="sub">2019</p>' in html
          and '<h3 dir="auto">Blade Runner 2049</h3>' in html and '<h3 dir="auto">MBC 1</h3>' in html
          and C._view(d, "kon")[1]["counts"] == {"series": 1, "seasons": 2, "episodes": 3, "movie": 2, "live": 1},
          C._view(d, "kon")[1]["counts"])

    print("الحرفان مكان الصورة")
    check("بلا أقواسٍ ولا سنة", [P._initials(n) for n in ("UNABOMBER (2026)", "Mother Mary (2026)", "12 Strong (2018)",
                                                          "(500) Days of Summer", "2020", "350 جرام", "مُسلسل رائع", "", "---")]
          == ["U", "MM", "S", "DO", "2", "ج", "مر", "•", "•"])

    print("التاريخ")
    now = time.time()
    check("«أضيف»: اليوم وأمس ومنذ", [P._ago(now - x * 86400, now) for x in (.2, 1.5, 2, 3, 11, 14, 60, 400, 800)]
          == ["اليوم", "أمس", "منذ يومين", "منذ 3 أيام", "منذ أسبوع", "منذ أسبوعين", "منذ شهرين", "منذ سنة", "منذ سنتين"]
          and P._ago(0) == "")
    shutil.rmtree(d, ignore_errors=True)


def unit_images():
    print("الصور")
    tm = "https://image.tmdb.org/t/p/w600_and_h900_bestv2/abc.jpg"
    check("TMDB مباشرةً بالمقاس", C.img_src("smart", tm) == "https://image.tmdb.org/t/p/w342/abc.jpg"
          and C.img_src("smart", tm, "w780") == "https://image.tmdb.org/t/p/w780/abc.jpg")
    u = HOST + "/images/8.png"
    check("وغيرها عبر خادمنا بلا مضيفها", C.img_src("smart", u) == "/content/smart/img/" + C.img_hash(u)
          and len(C.img_hash(u)) == 16 and C.img_src("smart", "") == "")
    check("نوع الصورة من بايتاتها", C._img_type(b"\xff\xd8\xff\xe0") == "image/jpeg" and C._img_type(mock_xtream.png(1)) == "image/png"
          and C._img_type(b"RIFF1234WEBPVP8 ") == "image/webp" and C._img_type(b"GIF89a..") == "image/gif"
          and C._img_type(b"<html>") == "")
    check("العناوين الداخلية لا تُطلب", not any(C._public_host(h) for h in (
        "127.0.0.1", "10.1.2.3", "192.168.1.1", "169.254.169.254", "::1", "localhost", "panel.example"))
          and C._public_host("8.8.8.8"))
    try:
        C._SafeRedirect().redirect_request(urllib.request.Request("http://8.8.8.8/a.png"), None, 302, "Found", {},
                                           "http://169.254.169.254/latest")
        check("ولا تحويلٌ إليها", False)
    except urllib.error.URLError:
        check("ولا تحويلٌ إليها", True)
    check("وصورةٌ لا تُفتح تُقدَّم كما هي", C._shrink(b"abc", "image/png") == (b"abc", "image/png"))

    srv = mock_xtream.serve(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    d = fresh()
    good, missing, notimg = base + "/images/7.png", base + "/nothing.png", base + "/player_api.php?username=u&password=p"
    C.ingest(d, "smart", reader(("#EXTM3U\n" + "".join(
        f'#EXTINF:-1 tvg-logo="{logo}" group-title="Ch",Channel {n}\n{base}/live/a/b/{n}.ts\n'
        for n, logo in enumerate((good, missing, notimg), 1))).encode()), "file", "x.m3u")
    folder = os.path.join(d, "content", "img")
    try:
        hits = len(mock_xtream.Handler.hits)
        code, _, _ = C.image(d, "smart", C.img_hash(good))
        check("عنوانٌ داخلي في الملف: لا يُطلب ويُعلَّم", code == 404 and len(mock_xtream.Handler.hits) == hits
              and os.path.exists(os.path.join(folder, C.img_hash(good) + ".x")))
        C.IMG_PRIVATE = True
        os.remove(os.path.join(folder, C.img_hash(good) + ".x"))
        code, data, ctype = C.image(d, "smart", C.img_hash(good))
        check("صورةٌ تُجلب وتُحفظ", code == 200 and ctype == "image/png" and data[:4] == b"\x89PNG"
              and os.path.exists(os.path.join(folder, C.img_hash(good))))
        hits = len(mock_xtream.Handler.hits)
        check("والمرة الثانية من القرص", C.image(d, "smart", C.img_hash(good))[:2] == (200, data)
              and len(mock_xtream.Handler.hits) == hits)
        check("وما تعذّر (404) لا يُعاد قبل يوم", C.image(d, "smart", C.img_hash(missing))[0] == 404
              and C.image(d, "smart", C.img_hash(missing))[0] == 404 and len(mock_xtream.Handler.hits) == hits + 1)
        check("وما ليس صورةً لا يُقدَّم", C.image(d, "smart", C.img_hash(notimg))[0] == 404)
        check("رمزٌ ليس في الفهرس أو بصيغةٍ أخرى: 404", C.image(d, "smart", "0" * 16)[0] == 404
              and C.image(d, "smart", "../../settings")[0] == 404 and C.image(d, "smart", C.img_hash(good).upper())[0] == 404
              and C.image(d, "nope", "1" * 16)[0] == 404)
    finally:
        C.IMG_PRIVATE = False
        srv.shutdown()
        shutil.rmtree(d, ignore_errors=True)

    tmp, cap = tempfile.mkdtemp(prefix="img_"), C.IMG_CACHE
    C.IMG_CACHE = 1000
    try:
        for n in range(3):
            C._img_save(tmp, os.path.join(tmp, f"{n:016x}"), bytes([n]) * 400)
            os.utime(os.path.join(tmp, f"{n:016x}"), (1000 + n, 1000 + n))
        check("حدّ حجم الصور: يُحذف الأقدم", sorted(os.listdir(tmp)) == [f"{1:016x}", f"{2:016x}"], os.listdir(tmp))
    finally:
        C.IMG_CACHE = cap
        shutil.rmtree(tmp, ignore_errors=True)


def unit_enrich():
    print("واجهة Xtream")
    check("من رابط get.php", C.xtream_of("http://h.example:8080/get.php?username=a&password=b&type=m3u_plus")
          == ("http://h.example:8080", "a", "b") and C.xtream_of("http://h.example/list.m3u") is None
          and C.xtream_of("http://h.example/get.php?username=a") is None and C.xtream_of("nonsense") is None)
    arr = json.dumps([{"stream_id": 1, "name": "A ] , [ {x}", "genre": "دراما"}, 5, {"stream_id": 2, "plot": "ب" * 50}],
                     ensure_ascii=False).encode()
    got = list(C._json_items(reader(arr), chunk=7))
    check("مصفوفة JSON عنصرًا عنصرًا وهي تصل", [o.get("stream_id") for o in got] == [1, 2] and got[0]["genre"] == "دراما"
          and got[0]["name"] == "A ] , [ {x}" and got[1]["plot"] == "ب" * 50, got)
    check("وردٌّ ليس مصفوفة (رفض الدخول) لا يُخرج شيئًا", list(C._json_items(reader(b'{"user_info":{"auth":0}}'))) == [])
    check("وردٌّ انقطع: ما اكتمل منه", [o["a"] for o in C._json_items(reader(b'[{"a":1},{"a":2},{"a":'), chunk=5)] == [1, 2])
    try:
        list(C._json_items(reader(b"[" + b'{"a":1},' * 1000 + b"]"), chunk=64, limit=500))
        check("وحدّ الحجم", False)
    except ValueError:
        check("وحدّ الحجم", True)
    check("التقييم من 10", [C._rating(x) for x in ("7.8", "8/10", "7,5", "0", "11", "", None, "abc")]
          == [7.8, 8.0, 7.5, 0, 0, 0, 0, 0])
    check("والتصنيف ثلاثةٌ بلا تكرار", C._genres("Action, Drama / Comedy | Horror") == ["Action", "Drama", "Comedy"]
          and C._genres("تاريخي، دراما") == ["تاريخي", "دراما"] and C._genres("Drama, drama") == ["Drama"]
          and C._genres(["A", "B"]) == ["A", "B"] and C._genres("") == [])
    long = "كلمة " * 100
    check("والقصة بحدّها", len(C._plot(long)) <= C.PLOT_MAX + 1 and C._plot(long).endswith("…") and C._plot(" a  b ") == "a b")
    check("والسنة", C._year("2024-05-01") == 2024 and C._year("") == 0 and C._year("3024") == 0 and C._year(1999) == 1999)

    srv = mock_xtream.serve(0)
    down = mock_xtream.serve(0, api_down=True)
    for s in (srv, down):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    d = fresh()
    try:
        C.set_url(d, "smart", f"{base}/get.php?username=u&password=p&type=m3u_plus")
        mock_xtream.Handler.hits.clear()
        sent, ev = [], threading.Event()
        C.notifier = lambda subject, body: (sent.append(body), ev.set(), {"mail": {"ok": True, "to": "me@example.com"}})[2]
        ok, err = C.refresh(d, "smart")
        st = next(s for s in C.admin_state(d)["servers"] if s["key"] == "smart")
        check("القائمة ثم الواجهة: طلبٌ للأفلام وطلبٌ للمسلسلات", ok and mock_xtream.Handler.hits
              == ["/get.php", "/player_api.php?action=get_vod_streams", "/player_api.php?action=get_series"], mock_xtream.Handler.hits)
        check("وحاله للمدير", st["api"] == {"ok": True, "movies": 32, "series": 10}, st["api"])
        v = C._view(d, "smart")[1]
        check("الأعداد", v["counts"] == {"series": 10, "seasons": 43, "episodes": 645, "movie": 32, "live": 14}, v["counts"])
        check("وما تعلّمه الواجهة للكبار يسقط", st["skipped"]["adult"] == 3 and "Hidden Adult Film" not in json.dumps(v["cat"]))
        check("ويُعرض للمدير وحده في «ما أُسقط للكبار» بقسمه", st["adult"]["panel"] == [["Hidden Adult Film", "أفلام عربية"]]
              and st["adult"]["groups"] == [["XXX | Adults", 2]] and st["adult"]["count"] == 3 and st["adult"]["more"] == 0,
              st["adult"])
        check("والتنبيه به", ev.wait(5) and "أفلامٌ علّمتها لوحة السيرفر للكبار:\n• Hidden Adult Film — في «أفلام عربية»" in sent[0]
              and "• XXX | Adults (عنصران)" in sent[0] and "من ملفه كله: 3 عناصر." in sent[0], sent[0] if sent else "")
        C.notifier = None
        mv = {it["n"]: it for g in v["kinds"]["movie"] for it in g["items"]}
        f1 = mv["F1 The Movie"]
        check("الفيلم: تقييمه وتصنيفه وتاريخ إضافته", f1["r"] == 7.8 and f1["g"] == ["Action", "Drama"] and f1["y"] == 2025
              and f1["a"] == mock_xtream.NOW - 86400 and f1["p"].startswith("https://image.tmdb.org/"), f1)
        ser = {it["n"]: it for g in v["kinds"]["series"] for it in g["items"]}
        bb = ser["Breaking Bad"]
        check("المسلسل: قصته وخلفيته وسنته وتاريخ آخر حلقة", bb["r"] == 9.5 and bb["y"] == 2008 and bb["d"].startswith("معلّم كيمياء")
              and bb["b"].startswith("https://image.tmdb.org/") and bb["a"] == mock_xtream.NOW - 500 * 86400, bb)
        check("والتصنيف بفاصلةٍ عربية", ser["المؤسس عثمان"]["g"] == ["تاريخي", "دراما"], ser["المؤسس عثمان"].get("g"))
        rec = [v["kinds"]["movie"][gi]["items"][ii]["n"] for gi, ii in v["recent"]["movie"][:3]]
        check("«أضيف مؤخرًا» بتاريخ الواجهة", rec == ["F1 The Movie", "M3GAN 2.0", "The Fantastic Four: First Steps"], rec)
        rec = [v["kinds"]["series"][gi]["items"][ii]["n"] for gi, ii in v["recent"]["series"][:3]]
        check("والمسلسل بآخر حلقة", rec == ["المؤسس عثمان", "Stranger Things", "Squid Game"], rec)
        dump = json.dumps(v["cat"], ensure_ascii=False) + open(os.path.join(d, "content", "settings.json"), encoding="utf-8").read()
        check("ولا بيانات دخولٍ في الفهرس ولا في الإعدادات", "password" not in dump and "/u/p/" not in dump and "username" not in dump)

        code, html = page(d, "smart")
        first = re.search(r'class="slide on".*?<h2 dir="auto">(.*?)</h2>', html, re.S)
        check("الواجهة المتحرّكة: أحدث فيلم بتقييمه وتصنيفه", first and first.group(1) == "F1 The Movie"
              and "2025 · Action • Drama" in html and "</svg>7.8</p>" in html)
        check("وشارة «جديد» وتاريخ الإضافة", '<span class="badge">جديد</span>' in html and "2025 · أضيف أمس" in html
              and "حُدّث أمس" in html)
        check("وصور TMDB بمقاسها، وغيرها عبر خادمنا", "https://image.tmdb.org/t/p/w342/" in html and "/content/smart/img/" in html
              and "127.0.0.1" not in html)
        code, html = page(d, "smart", t="movie")
        check("تصفية الأفلام: السنة والتصنيف والتقييم والترتيب", all(f'name="{n}"' in html for n in ("y", "g", "genre", "r", "sort"))
              and '<option value="rate">الأعلى تقييمًا</option>' in html and '<option value="2025">2025</option>' in html)
        code, html = page(d, "smart", t="movie", view="grid", genre="Horror")
        main = html.split('<aside class="side">')[0]
        check("بالتصنيف", titles(main) == ["M3GAN 2.0", "The Platform 2"] and "فيلمان · Horror" in html, titles(main))
        code, html = page(d, "smart", t="movie", view="grid", r="8", sort="rate")
        rates = [float(x) for x in re.findall(r"</svg>([\d.]+)</p>", html.split('<aside class="side">')[0])]
        check("وبالتقييم مرتّبًا", len(rates) == 5 and rates == sorted(rates, reverse=True) and min(rates) >= 8, rates)

        C.set_url(d, "falcon", f"http://127.0.0.1:{down.server_address[1]}/get.php?username=u&password=p")
        ok, err = C.refresh(d, "falcon")
        st = next(s for s in C.admin_state(d)["servers"] if s["key"] == "falcon")
        check("الواجهة معطّلة: القائمة تُحفظ بما فيها والسبب للمدير", ok and st["has"] and st["api"]["ok"] is False
              and "500" in st["api"]["error"], st["api"])
        v2 = C._view(d, "falcon")[1]
        check("بلا تقييمٍ ولا تاريخ، والأحدث برقمه", v2["counts"]["movie"] == 33
              and not any(it.get("r") or it.get("a") for g in v2["kinds"]["movie"] for it in g["items"]), v2["counts"])

        print("ملفٌّ بلا أقسام (‏type=m3u)")
        C.set_url(d, "kon", f"{base}/get.php?username=u&password=p&type=m3u")
        mock_xtream.Handler.hits.clear()
        ok, err = C.refresh(d, "kon")
        kon = next(s for s in C.admin_state(d)["servers"] if s["key"] == "kon")
        v3 = C._view(d, "kon")[1]
        check("طلبات الأقسام وشعارات القنوات", ok and set(mock_xtream.Handler.hits) >= {
              "/player_api.php?action=get_live_streams", "/player_api.php?action=get_vod_categories",
              "/player_api.php?action=get_series_categories", "/player_api.php?action=get_live_categories"}, err)
        check("كل عنصرٍ في قسمه من الواجهة، بترتيبها", [g["name"] for g in v3["kinds"]["movie"]] == list(mock_xtream.MOVIES)
              and [g["name"] for g in v3["kinds"]["series"]] == list(mock_xtream.SERIES)
              and [g["name"] for g in v3["kinds"]["live"]] == list(mock_xtream.CHANNELS),
              [[g["name"] for g in v3["kinds"][k]] for k in C.KINDS])
        check("والأعداد كما في الملف بأقسامه", v3["counts"] == {"series": 10, "seasons": 43, "episodes": 645, "movie": 32,
                                                              "live": 14} and kon["api"]["grouped"] == 56, (v3["counts"], kon["api"]))
        check("وقسم الكبار في الواجهة يُسقط ما فيه، وللمدير", kon["skipped"]["adult"] == 3 and kon["adult"]["count"] == 3
              and "Hot Stuff" not in json.dumps(v3["cat"]) and ["Hot Stuff", "XXX | Adults"] in kon["adult"]["panel"],
              (kon["skipped"], kon["adult"]))
        logos = [it.get("p") for g in v3["kinds"]["live"] for it in g["items"]]
        check("وشعار القناة من الواجهة", all(logos) and f"{base}/images/106.png" in logos, logos[:3])
        code, html = page(d, "kon", t="movie")
        check("والصفحة بأقسامها", code == 200 and "بلا قسم" not in html and html.count('<a class="chip"') == 3)

        text = mock_xtream.build(base)[0]
        res = C.ingest(d, "casper", reader(text.encode()), "file", "casper.m3u")
        check("والملف المرفوع يُثرى من روابطه", res["api"] == {"ok": True, "movies": 32, "series": 10}, res["api"])
        C.set_url(d, "kon", "")
        res = C.ingest(d, "kon", reader(text.replace("/u/p/", "/u/old/").encode()), "file", "kon.m3u")
        check("واشتراكٌ في الملف لا تقبله الواجهة: السبب للمدير", res["api"]["ok"] is False
              and "لم تُرجع شيئًا" in res["api"]["error"] and C._view(d, "kon")[1]["counts"]["movie"] == 33, res["api"])
    finally:
        C.notifier = None
        srv.shutdown()
        down.shutdown()
        shutil.rmtree(d, ignore_errors=True)


class _M3U(http.server.BaseHTTPRequestHandler):
    """سيرفر IPTV وهمي: ‏/get.php?username=…&password=… يرد القائمة، و‏/expired يرد 403."""
    body = SAMPLE.encode("utf-8")
    hits = []

    def do_GET(self):
        _M3U.hits.append((self.path, self.headers.get("User-Agent")))
        if self.path.startswith("/get.php") and "password=pass456" in self.path:
            data = gzip.compress(_M3U.body) if "gz=1" in self.path else _M3U.body
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif self.path.startswith("/empty"):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"#EXTM3U\n")
        else:
            self.send_response(403)
            self.end_headers()

    def log_message(self, *a):
        pass


def mock_iptv():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _M3U)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def unit_fetch():
    print("السحب من الرابط")
    srv, base = mock_iptv()
    d = fresh()
    try:
        C.set_url(d, "casper", base + "/get.php?username=user123&password=pass456&type=m3u_plus")
        ok, err = C.refresh(d, "casper")
        v = C._view(d, "casper")[1]
        check("يُسحب ويُقرأ", ok and v and v["counts"]["series"] == 9, err)
        check("بوكيل مشغّل", _M3U.hits[-1][1] == C.UA)
        a = next(s for s in C.admin_state(d)["servers"] if s["key"] == "casper")
        check("المصدر: الرابط، مخفيًّا", a["source"] == "url" and a["label"] == C.mask_url(base + "/x") and a["error"] == "")
        C.set_url(d, "casper", base + "/get.php?username=user123&password=pass456&gz=1")
        check("والمضغوط", C.refresh(d, "casper")[0])
        C.set_url(d, "casper", base + "/get.php?username=user123&password=WRONG")
        ok, err = C.refresh(d, "casper")
        check("اشتراكٌ منتهٍ (403): خطأٌ محفوظ والمحتوى باقٍ", not ok and "403" in err
              and C._server(d, "casper")["error"] == err and C._view(d, "casper")[1]["counts"]["series"] == 9, err)
        C.set_url(d, "casper", base + "/empty")
        ok, err = C.refresh(d, "casper")
        check("قائمةٌ فارغة لا تمسح المحتوى", not ok and "لا عناصر" in err and C._view(d, "casper")[1] is not None, err)
        C.set_url(d, "casper", "http://127.0.0.1:9/nothing")
        ok, err = C.refresh(d, "casper")
        check("سيرفرٌ لا يرد", not ok and "تعذّر الاتصال" in err, err)

        print("الدورة اليومية")
        C.set_url(d, "casper", base + "/get.php?username=user123&password=pass456")
        lists = lambda: len([h for h in _M3U.hits if h[0].startswith(("/get.php", "/nothing"))])  # noqa: E731
        n0 = lists()
        C.tick(d)
        check("محتوى اليوم لا يُسحب ثانية", lists() == n0)
        C.tick(d, now=time.time() + C.REFRESH + 1)
        check("بعد يوم يُسحب", lists() == n0 + 1)
        C._update(d, "casper", url=C.crypto_store.encrypt(base + "/nothing-here", d))
        later = time.time() + 2 * C.REFRESH
        C.tick(d, now=later)
        n1 = lists()
        C.tick(d, now=later + 60)
        check("والفشل لا يُعاد قبل RETRY", lists() == n1 and C._server(d, "casper")["error"])
        C.tick(d, now=later + C.RETRY + 60)
        check("ويُعاد بعده", lists() == n1 + 1)
        try:
            C.start_refresh(d, "kon")
            check("«اسحب الآن» بلا رابط", False)
        except ValueError:
            check("«اسحب الآن» بلا رابط", True)

        print("محتوى القراءة الأولى")
        old = {"entries": 1, "n": {"series": 0, "movie": 1, "live": 0}, "skipped": {}, "series": [], "live": [],
               "movie": [{"id": C._gid("movie", "M"), "name": "M", "items": ["Old Film (2019)"]}]}
        state = lambda k: next(x for x in C.admin_state(d)["servers"] if x["key"] == k)  # noqa: E731
        C._write(C._cat_path(d, "smart"), old)
        check("بلا رابط: للمدير «أعد رفع الملف»", state("smart")["old"] is True and C._cat_old(d, "smart")
              and not C._cat_old(d, "falcon"))
        C.tick(d)
        check("والدورة لا تمسّه", C._cat_old(d, "smart"))
        C._write(C._cat_path(d, "casper"), old)
        C.set_url(d, "casper", base + "/get.php?username=user123&password=pass456")
        n0 = lists()
        C.tick(d)
        check("وبرابط: يُسحب في أول دورة لا بعد يوم", lists() == n0 + 1 and not C._cat_old(d, "casper")
              and state("casper")["old"] is False and C._view(d, "casper")[1]["counts"]["series"] == 9)
        C.tick(d)
        check("ثم كل يومٍ كعادته", lists() == n0 + 1)
    finally:
        srv.shutdown()
        shutil.rmtree(d, ignore_errors=True)


# ---------- خادمٌ حيّ ----------
AUTH = "Basic " + base64.b64encode(b"admin:envpass123").decode()


def req(url, data=None, auth=False, headers=None, method=None):
    r = urllib.request.Request(url, data=data, method=method or ("POST" if data is not None else "GET"),
                               headers=dict(headers or {}))
    if auth:
        r.add_header("Authorization", AUTH)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def jpost(url, body, auth=True):
    code, raw, _ = req(url, json.dumps(body).encode(), auth, {"Content-Type": "application/json"})
    return code, json.loads(raw or b"{}")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def live():
    print("خادمٌ حيّ")
    port = 9795
    data = tempfile.mkdtemp(prefix="content_live_")
    xt = mock_xtream.serve(0)
    threading.Thread(target=xt.serve_forever, daemon=True).start()
    xbase = f"http://127.0.0.1:{xt.server_address[1]}"
    env = {k: v for k, v in os.environ.items() if not k.startswith("SALLA_ADMIN_TOKEN")}
    env.update(XM_DATA=data, XM_BIND="127.0.0.1", XM_PORT=str(port), XM_ADMIN_PASSWORD="envpass123", CONTENT_IMG_PRIVATE="1")
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "xm_lines.py"), "web"], env=env)
    base, adm = f"http://127.0.0.1:{port}", f"http://127.0.0.1:{port}/admin"
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/robots.txt", timeout=2)
                break
            except Exception:
                time.sleep(.2)
        code, body, _ = req(base + "/content")
        check("قبل أي ملف: ‏/content صفحةٌ لا تُفهرس", code == 404 and b"noindex" in body)
        check("والرئيسية بلا سيرفرات", json.loads(req(base + "/api/content")[1]) == {"ok": True, "servers": []})
        try:
            urllib.request.build_opener(_NoRedirect).open(adm + "/content", timeout=10)
            check("صفحة المدير تطلب الدخول", False)
        except urllib.error.HTTPError as e:
            check("صفحة المدير تطلب الدخول", e.code == 302 and e.headers["Location"] == "/admin/login"
                  and req(adm + "/api/content/admin")[0] == 401, e.headers.get("Location"))
        code, _, _ = req(adm + "/api/content/admin/upload?s=smart", SAMPLE.encode())
        check("والرفع كذلك", code == 401)
        code, raw, _ = req(adm + "/content", auth=True)
        check("صفحة المدير", code == 200 and "محتوى السيرفرات".encode() in raw)
        code, raw, _ = req(adm + "/api/content/admin/upload?s=smart&name=smart.m3u",
                           gzip.compress(SAMPLE.encode()), True, {"Content-Type": "application/octet-stream"})
        d = json.loads(raw)
        check("الرفع مضغوطًا", code == 200 and d["ok"] and d["result"]["entries"] == 25, raw[:200])
        code, raw, _ = req(adm + "/api/content/admin/upload?s=kon&name=kon.m3u",
                           ("#EXTM3U\n" + entry("Kon Only S01 E01", "Kon", "series", 1)).encode(), True)
        check("وخامًا", code == 200 and json.loads(raw)["result"]["entries"] == 1)
        code, raw, _ = req(adm + "/api/content/admin/upload?s=casper", b"not a playlist", True)
        check("ملفٌّ ليس قائمة", code == 400 and "لا عناصر".encode() in raw)
        import socket
        sk = socket.create_connection(("127.0.0.1", port), timeout=15)
        sk.sendall(b"POST /admin/api/content/admin/upload?s=casper HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: "
                   + AUTH.encode() + b"\r\nContent-Length: 100000\r\n\r\n" + SAMPLE.encode()[:3000])
        sk.shutdown(socket.SHUT_WR)
        got = b""
        while True:
            b = sk.recv(65536)
            if not b:
                break
            got += b
        sk.close()
        check("رفعٌ انقطع في منتصفه لا يُحفظ نصفه", got.startswith(b"HTTP/1.0 400") and "انقطع الرفع".encode() in got
              and not next(s for s in json.loads(req(adm + "/api/content/admin", auth=True)[1])["servers"]
                           if s["key"] == "casper")["has"], got[:120])
        code, raw, _ = req(adm + "/api/content/admin/upload?s=../../x", SAMPLE.encode(), True)
        check("سيرفرٌ بمسارٍ خارج المجلد", code == 400)
        st = json.loads(req(adm + "/api/content/admin", auth=True)[1])
        sm = next(s for s in st["servers"] if s["key"] == "smart")
        check("حال المدير", sm["has"] and sm["label"] == "smart.m3u" and sm["counts"]["series"] == 9
              and st["refresh_hours"] == 24)

        print("ما أُسقط للكبار والتنبيه به")
        for _ in range(50):
            sm = next(s for s in json.loads(req(adm + "/api/content/admin", auth=True)[1])["servers"] if s["key"] == "smart")
            if (sm.get("adult") or {}).get("alert"):
                break
            time.sleep(.1)
        al = (sm.get("adult") or {}).get("alert") or {}
        check("ما أُسقط للمدير، وتنبيهٌ به (ولا بريد ولا رقم بعد)", sm["adult"]["groups"] == [["XXX | Adults", 1], ["For Adults +18", 1]]
              and al.get("mail", {}).get("error") == "لا بريد للتنبيه" and al.get("wa", {}).get("error") == "لا رقم واتساب للتنبيه",
              sm.get("adult"))
        check("لمن يصل التنبيه: لا شيء مضبوط", st["alert"] == {"mail": "", "wa": "", "saved": False, "smtp": False, "wa_from": ""},
              st.get("alert"))
        for body, err in [({"mail": "not-an-email", "wa": ""}, "بريدًا صحيحًا"),
                          ({"mail": "a@b.co\nBcc: x@y.z", "wa": ""}, "بريدًا صحيحًا"), ({"mail": "", "wa": "12"}, "رقم واتساب")]:
            code, d = jpost(adm + "/api/content/admin/alert", body)
            check(f"يُرفض: {err} ({body['mail'] or body['wa']!r})", code == 400 and err in d.get("error", ""), d)
        code, st = jpost(adm + "/api/content/admin/alert", {"mail": " me@example.com ", "wa": "0551234567"})
        check("يُحفظ البريد والرقم بصيغته", code == 200 and st["alert"]["mail"] == "me@example.com"
              and st["alert"]["wa"] == "966551234567" and st["alert"]["saved"] is True, st.get("alert"))
        code, d = jpost(adm + "/api/content/admin/alert-test", {})
        check("رسالةٌ تجريبية: نتيجة كلٍّ منهما، وسببها بالعربية", code == 200 and "خادم البريد غير مضبوط" in d["test"]["mail"]["error"]
              and d["test"]["mail"]["to"] == "me@example.com" and d["test"]["wa"]["ok"] is False
              and d["test"]["wa"]["to"] == "966551234567" and "Errno" not in d["test"]["wa"]["error"]
              and re.search("[ء-ي]", d["test"]["wa"]["error"]), d.get("test"))
        check("وللمدير وحده", jpost(adm + "/api/content/admin/alert-test", {}, auth=False)[0] == 401
              and jpost(adm + "/api/content/admin/alert", {"mail": ""}, auth=False)[0] == 401)

        code, st = jpost(adm + "/api/content/admin/url",
                         {"s": "falcon", "url": xbase + "/get.php?username=u&password=p&type=m3u_plus"})
        check("الرابط يُحفظ ويُسحب في الخلفية", code == 200 and st["servers"][3]["url"].endswith("/•••")
              and "username=u" not in json.dumps(st))
        for _ in range(100):
            fal = next(s for s in json.loads(req(adm + "/api/content/admin", auth=True)[1])["servers"] if s["key"] == "falcon")
            if fal["has"] and not fal["busy"]:
                break
            time.sleep(.1)
        check("وصار له محتوى، مُثرًى من واجهة السيرفر", fal["has"] and fal["source"] == "url"
              and fal["api"] == {"ok": True, "movies": 32, "series": 10}, (fal.get("error"), fal.get("api")))
        code, st = jpost(adm + "/api/content/admin/refresh", {"s": "kon"})
        check("«اسحب الآن» بلا رابط", code == 400)
        code, st = jpost(adm + "/api/content/admin/server", {"new": True, "name": "نجم", "key": "najm"})
        check("إضافة سيرفر", code == 200 and st["servers"][-1]["key"] == "najm")
        groups = next(s for s in st["servers"] if s["key"] == "smart")["groups"]["series"]
        g, drama = (next(x for x in groups if x[1] == name) for name in ("Netflix", "SERIES | Drama"))
        code, st = jpost(adm + "/api/content/admin/hide", {"s": "smart", "g": g[0], "hidden": True})
        check("إخفاء قسم (وما فيه وحده لا يُعدّ)", code == 200
              and next(s for s in st["servers"] if s["key"] == "smart")["counts"]["series"] == 8)

        print("الصفحات العامة")
        op = urllib.request.build_opener(_NoRedirect)
        try:
            op.open(base + "/content?q=x", timeout=10)
            check("‏/content يحوّل", False)
        except urllib.error.HTTPError as e:
            check("‏/content يحوّل إلى أوّل سيرفرٍ له محتوى ومعه البحث", e.code == 302
                  and e.headers["Location"] == "/content/kon?q=x", e.headers.get("Location"))
        code, raw, hd = req(base + "/content/smart")
        html = raw.decode()
        check("صفحة السيرفر", code == 200 and "محتوى اشتراك سمارت" in html and "public, max-age=600" in hd.get("Cache-Control", ""))
        check("القسم المخفي ليس فيها", "Netflix" not in html and "Sex Education" not in html)
        check("السيرفرات الثلاثة", all(f'href="/content/{k}"' in html for k in ("kon", "smart", "falcon")))
        check("بشرطةٍ في آخره", req(base + "/content/smart/")[0] == 200)
        code, raw, _ = req(base + f"/content/smart?t=series&g={drama[0]}")
        check("صفحة القسم", code == 200 and "Breaking Bad" in raw.decode() and "noindex" in raw.decode())
        code, raw, _ = req(base + "/content/smart?t=new")
        check("وأضيف مؤخرًا", code == 200 and "أضيف مؤخرًا في سمارت" in raw.decode())
        check("وقسمٌ لا وجود له", req(base + "/content/smart?t=series&g=nothing")[0] == 404)
        code, raw, _ = req(base + "/api/content/search?s=smart&q=" + urllib.parse.quote("باب"))
        check("البحث", code == 200 and "باب الحارة" in json.loads(raw)["html"])
        r = json.loads(req(base + "/api/content/search?s=kon&q=breaking")[1])["html"]
        check("وأين يوجد", "لكنه موجود في" in r and "فالكون" in r and "سمارت" in r)
        check("سيرفرٌ أو مسارٌ لا وجود له", req(base + "/api/content/search?s=nope&q=xx")[0] == 404
              and req(base + "/content/nope")[0] == 404 and req(base + "/content/smart/extra")[0] == 404
              and req(base + f"/api/content/group?s=smart&t=series&g={drama[0]}")[0] == 404)
        check("HEAD", req(base + "/content/smart", method="HEAD")[0] == 200)
        code, raw, _ = req(base + "/content/falcon")
        html = raw.decode()
        check("سيرفرٌ مُثرًى: التقييم وشارة «جديد»", code == 200 and "F1 The Movie" in html and "</svg>7.8</p>" in html
              and '<span class="badge">جديد</span>' in html)
        check("ولا يظهر فيها سيرفر اللوحة ولا بيانات الدخول", "127.0.0.1" not in html and "password" not in html)
        h = re.search(r"/content/falcon/img/([0-9a-f]{16})", html)
        code, raw, hd = req(base + f"/content/falcon/img/{h.group(1) if h else 'x'}")
        check("الصورة عبر خادمنا ومخزَّنة شهرًا", code == 200 and raw[:4] == b"\x89PNG" and hd.get("Content-Type") == "image/png"
              and "max-age=2592000" in hd.get("Cache-Control", ""), (code, hd.get("Content-Type")))
        check("ورمزٌ لا صورة له: 404", req(base + "/content/falcon/img/" + "0" * 16)[0] == 404
              and req(base + "/content/falcon/img/zz")[0] == 404)
        sm = req(base + "/sitemap.xml")[1].decode()
        check("خريطة الموقع", "/content/smart</loc>" in sm and "/content/kon</loc>" in sm and "/content/casper" not in sm)
        b = json.loads(req(base + "/api/content")[1])
        check("للرئيسية", [s["key"] for s in b["servers"]] == ["kon", "smart", "falcon"])
        home = req(base + "/")[1].decode()
        check("الرئيسية: روابط المحتوى تنتظر ‏/api/content", 'id="menu-content" hidden' in home
              and 'id="content-entry" href="/content" hidden' in home and "/api/content" in home
              and 'href="/content"' in home)

        print("النطاقان")
        code, raw, _ = req(base + "/content", auth=True, headers={"Host": "admin.ssouq.com"})
        check("نطاق الأداة: ‏/content صفحة المدير", code == 200 and "محتوى السيرفرات".encode() in raw)
        check("والموقع العام: لا صفحة مدير", req(base + "/admin/content", auth=True, headers={"Host": "guide.ssouq.com"})[0] == 404
              and req(base + "/admin/api/content/admin", auth=True, headers={"Host": "guide.ssouq.com"})[0] == 404)
        code, raw, _ = req(base + "/content/smart", headers={"Host": "guide.ssouq.com"})
        check("والصفحة العامة عليه", code == 200)
        code, _, _ = req(base + "/api/content/admin/upload?s=smart", SAMPLE.encode(), True, {"Host": "guide.ssouq.com"})
        check("ولا رفع عليه", code == 404)
        code, _, _ = req(base + "/api/content/admin/alert-test", b"{}", True, {"Host": "guide.ssouq.com"})
        check("ولا تنبيه منه", code == 404)
        pub = req(base + "/content/smart", headers={"Host": "guide.ssouq.com"})[1].decode()
        check("وما أُسقط للكبار ليس في صفحته", "Adults" not in pub and "Night Club" not in pub)
        code, st = jpost(adm + "/api/content/admin/clear", {"s": "najm", "drop": True})
        check("حذف سيرفر", code == 200 and all(s["key"] != "najm" for s in st["servers"]))
    finally:
        p.terminate()
        p.wait(timeout=10)
        xt.shutdown()
        shutil.rmtree(data, ignore_errors=True)


MAILS = []


class _SMTP(socketserver.StreamRequestHandler):
    """خادم بريدٍ وهمي بلا TLS (كالذي في test_split_web): يحفظ كل رسالةٍ كما وصلت."""

    def handle(self):
        self.wfile.write(b"220 fake ESMTP\r\n")
        data, buf = False, []
        while True:
            line = self.rfile.readline()
            if not line:
                break
            if data:
                if line in (b".\r\n", b".\n"):
                    MAILS.append(email.message_from_bytes(b"".join(buf), policy=email.policy.default))
                    buf, data = [], False
                    self.wfile.write(b"250 OK\r\n")
                else:
                    buf.append(line[1:] if line.startswith(b"..") else line)
                continue
            cmd = line.strip().upper()
            if cmd.startswith(b"EHLO"):
                self.wfile.write(b"250-fake\r\n250 8BITMIME\r\n")
            elif cmd == b"DATA":
                data = True
                self.wfile.write(b"354 go\r\n")
            elif cmd == b"QUIT":
                self.wfile.write(b"221 bye\r\n")
                break
            else:
                self.wfile.write(b"250 OK\r\n")


def live_alert():
    """التنبيه يصل فعلًا: بريدٌ من خادم «بريد التنبيه» وواتساب من رقم المسابقة (خدمةٌ وهمية)."""
    print("خادمٌ حيّ: تنبيه الكبار يصل بالبريد وواتساب")
    port, wport = 9796, 9786
    data = tempfile.mkdtemp(prefix="content_alert_")
    smtp = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _SMTP)
    threading.Thread(target=smtp.serve_forever, daemon=True).start()
    reader = f"http://127.0.0.1:{wport}"
    rdp = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_reader.py"), str(wport), "rdr_content"])
    env = {k: v for k, v in os.environ.items() if not k.startswith(("WHATSAPP_READER_", "SALLA_ADMIN_TOKEN"))}
    env.update(XM_DATA=data, XM_BIND="127.0.0.1", XM_PORT=str(port), XM_ADMIN_PASSWORD="envpass123",
               WHATSAPP_READER_URL=reader, WHATSAPP_READER_SECRET="rdr_content")
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "xm_lines.py"), "web"], env=env)
    adm = f"http://127.0.0.1:{port}/admin"

    def rd(method, path, body=None):
        rq = urllib.request.Request(reader + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                    headers={"Content-Type": "application/json", "X-Reader-Secret": "rdr_content"})
        with urllib.request.urlopen(rq, timeout=20) as r:
            return json.loads(r.read())

    def casper():
        return next(s for s in json.loads(req(adm + "/api/content/admin", auth=True)[1])["servers"] if s["key"] == "casper")

    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/robots.txt", timeout=2)
                rd("GET", "/_test/log")
                break
            except Exception:
                time.sleep(.2)
        code, d = jpost(adm + "/api/renew/config", {"renew": {"alert": {
            "host": "127.0.0.1", "port": smtp.server_address[1], "to": "owner@example.com", "from": "alerts@example.com",
            "tls": False}}})
        check("بريد التنبيه في صفحة التجديد", code == 200 and d.get("ok"), d)
        jpost(adm + "/api/contest/admin/wa/connect", {"number": "0500000009"})
        rd("POST", "/_test/scan/ssouq-guide--contest", {})
        req(adm + "/api/contest/admin", auth=True)          # صفحة المسابقة تجدّد حال الرقم
        code, d = jpost(adm + "/api/contest/admin/settings", {"notify": True, "admin_phone": "0551112222"})
        check("ورقم المدير في صفحة المسابقة", code == 200 and d["settings"]["admin_phone"] == "966551112222", d)
        st = json.loads(req(adm + "/api/content/admin", auth=True)[1])
        check("بلا حفظٍ في صفحة المحتوى: يصل إليهما، ومن رقم المسابقة",
              st["alert"] == {"mail": "owner@example.com", "wa": "966551112222", "saved": False, "smtp": True,
                              "wa_from": "966500000009"}, st["alert"])

        playlist = ("#EXTM3U\n" + entry("MBC 1", "AR | MBC", n=1) + entry("Hot Stuff", "XXX | Adults", n=2)
                    + entry("xXx (2002)", "VOD | English Movies", "movie", 3))
        wa0 = len(rd("GET", "/_test/log")["sent"])
        code, _, _ = req(adm + "/api/content/admin/upload?s=casper&name=casper.m3u", playlist.encode(), True)
        for _ in range(100):
            if MAILS and len(rd("GET", "/_test/log")["sent"]) > wa0 and (casper().get("adult") or {}).get("alert"):
                break
            time.sleep(.1)
        m = MAILS[-1] if MAILS else {}
        body = m.get_body().get_content() if MAILS else ""
        check("وصل البريد بما أُسقط وأين يُراجع", code == 200 and len(MAILS) == 1
              and str(m["Subject"]) == "تنبيه: محتوى للكبار في ملف سيرفر كاسبر (حُذف ولم يُنشر)"
              and str(m["To"]) == "owner@example.com" and "• XXX | Adults (عنصر واحد)" in body
              and "• xXx (2002) — في «VOD | English Movies»" in body and "https://admin.ssouq.com/content" in body, body)
        sent = rd("GET", "/_test/log")["sent"][wa0:]
        check("ووصل واتساب رقم المدير", len(sent) == 1 and sent[0]["to"] == "966551112222"
              and sent[0]["body"].startswith("*تنبيه: محتوى للكبار في ملف سيرفر كاسبر") and "xXx (2002)" in sent[0]["body"], sent)
        al = casper()["adult"]["alert"]
        check("ونتيجته في صفحة المدير: وصلا", al["mail"] == {"ok": True, "to": "owner@example.com"}
              and al["wa"] == {"ok": True, "to": "966551112222", "error": ""}, al)
        req(adm + "/api/content/admin/upload?s=casper&name=casper.m3u", playlist.encode(), True)
        time.sleep(1)
        check("والملف نفسه ثانيةً: لا تنبيه", len(MAILS) == 1 and len(rd("GET", "/_test/log")["sent"]) == wa0 + 1)

        code, st = jpost(adm + "/api/content/admin/alert", {"mail": "me@example.com", "wa": ""})
        check("ما يُحفظ في صفحة المحتوى يغلب", code == 200 and st["alert"]["mail"] == "me@example.com" and st["alert"]["wa"] == ""
              and st["alert"]["saved"] is True, st.get("alert"))
        code, d = jpost(adm + "/api/content/admin/alert-test", {})
        check("والتجربة إليه، والخانة الفارغة لا يُرسل إليها", code == 200 and d["test"]["mail"] == {"ok": True, "to": "me@example.com"}
              and d["test"]["wa"]["error"] == "لا رقم واتساب للتنبيه" and str(MAILS[-1]["To"]) == "me@example.com"
              and str(MAILS[-1]["Subject"]) == "تجربة تنبيه محتوى الكبار"
              and len(rd("GET", "/_test/log")["sent"]) == wa0 + 1, d.get("test"))
    finally:
        p.terminate()
        p.wait(timeout=10)
        rdp.terminate()
        rdp.wait(timeout=10)
        smtp.shutdown()
        shutil.rmtree(data, ignore_errors=True)


def main():
    unit_parse()
    unit_store()
    unit_adult()
    unit_render()
    unit_images()
    unit_fetch()
    unit_enrich()
    live()
    live_alert()
    print(f"\nResult: {_p} passed, {_f} failed")
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""صفحة المحتوى (content.py): قراءة ملفات M3U وصفحة /content ولوحة المدير، بلا إنترنت.

  - القراءة: النوع من رابط Xtream ومن الاسم، والمسلسل وموسمه وحلقته بصيغها (S01E01، 1x01،
    «الموسم الخامس الحلقة 13»، «ج3 ح12»)، وبادئة اللغة، والفواصل، وأقسام الكبار، وgzip وCRLF وBOM،
    وحدّ الحجم بعد فكّ الضغط.
  - الأعداد: المسلسل في قسمين يُعدّ مرة، والحلقة المكرّرة مرة، والمخفي من الأقسام لا يُعدّ.
  - الصفحة: الأقسام والقائمة بصفحاتها والبحث بالاسم وأين يوجد في السيرفرات الأخرى، ولا رابط ولا
    بيانات دخول ولا وسم من الملف، والفهرسة للصفحة الرئيسية وحدها.
  - السيرفرات: الافتراضية الأربعة، والإضافة والتعديل والترتيب والمسح، والرابط مشفَّرًا ومخفيًّا،
    والسحب منه والفشل والدورة اليومية.
  - على خادم حيّ: الرفع (خامًا ومضغوطًا) وصلاحياته، والرابط من سيرفرٍ وهمي، والصفحات والواجهات،
    وخريطة الموقع، والنطاقان.

تشغيل:  python tests/test_content.py
"""
import base64
import gzip
import http.server
import json
import os
import re
import shutil
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

import content as C  # noqa: E402

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
    s, m, lv = items(cat, "series"), items(cat, "movie"), items(cat, "live")
    check("الأعداد الخام", cat["n"] == {"series": 15, "movie": 4, "live": 6}, cat["n"])
    check("الكبار والفواصل تسقط", cat["skipped"] == {"adult": 2, "sep": 1, "bad": 0}, cat["skipped"])
    check("قسم الكبار لا يُحفظ اسمه", "XXX | Adults" not in json.dumps(cat) and "Night Club" not in json.dumps(cat))
    check("«Movies 2018+» ليس قسم كبار", "Horror Night" in m.get("Movies 2018+", []))
    check("«Sex Education» في قسمٍ عادي يبقى", any(it[0] == "Sex Education" for it in s["Netflix"]))
    check("القناة المكرّرة مرة وبلا بادئة", lv["AR | MBC"] == ["MBC 1 HD"], lv["AR | MBC"])
    check("«AL Jazeera» كما هي", lv["AR | News"] == ["AL Jazeera"])
    check("بلا قسم ← «بلا قسم»", lv.get("بلا قسم") == ["Plain Channel"])
    bb = dict((it[0], it[1]) for it in s["SERIES | Drama"])
    check("المواسم وحلقاتها، والمكرّرة تُعدّ مرة", bb["Breaking Bad"] == [[1, 2], [2, 1]], bb.get("Breaking Bad"))
    check("الأقسام بترتيب ظهورها", [g["name"] for g in cat["series"]][:3] == ["SERIES | Drama", "Netflix", "SERIES | Comedy"])
    check("الفيلم بفاصلته", "Love, Death & Robots: The Movie (2021)" in m["VOD | English Movies"])
    check("«ج2» في رابط فيلم يبقى فيلمًا", m["أفلام عربية"] == ["الفيل الأزرق ج2"])
    check("حلقةٌ برابط فيلم (لوحة قديمة) تُقرأ حلقة", ["The 100", [[1, 1]]] in s["Old panel"] and
          ["Stranger Things", [[1, 1]]] in s["Old panel"])
    check("الموسم بالعربية والأرقام الهندية", s["مسلسلات رمضان 2026"] == [["المؤسس عثمان", [[5, 2]]]])
    check("الحلقة بلا موسم = الموسم 0", s["مسلسلات تركية"] == [["قيامة أرطغرل", [[0, 1]]]])
    dump = json.dumps(cat, ensure_ascii=False)
    check("لا رابط ولا بيانات دخول ولا شعار في الفهرس", "pass456" not in dump and "panel.example" not in dump
          and "http" not in dump, re.findall(r"http[^\"]*", dump)[:2])

    print("ملفات أخرى")
    other = ("\ufeff#EXTM3U\r\n#EXTINF:-1,Show S02E03\r\nhttps://cdn.example/show/203.m3u8\r\n"
             "#EXTINF:-1,Some Film (2019)\r\nhttps://cdn.example/films/film.mp4?token=1\r\n"
             "#EXTGRP:News\r\n#EXTINF:-1,Channel One\r\nhttps://cdn.example/live/one.m3u8\r\n"
             "#EXTINF:-1,Channel Two\r\n#EXTVLCOPT:http-user-agent=x\r\nhttps://cdn.example/two.ts\r\n")
    c2 = catalog(other)
    check("BOM وCRLF و‏#EXTGRP وسطر خيارات قبل الرابط", items(c2, "live").get("News") == ["Channel One", "Channel Two"],
          items(c2, "live"))
    check("بلا Xtream: الحلقة من اسمها والفيلم من امتداده", items(c2, "series") == {"بلا قسم": [["Show", [[2, 1]]]]}
          and items(c2, "movie") == {"بلا قسم": ["Some Film (2019)"]}, (items(c2, "series"), items(c2, "movie")))
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
          and v2["counts"]["series"] == 8 and C.api_group(d, "smart", "series", drama["id"]) is None, v2["counts"])
    check("وحال المدير يعلّمه مخفيًّا", [g for g in next(s for s in C.admin_state(d)["servers"] if s["key"] == "smart")
                                         ["groups"]["series"] if g[0] == drama["id"]][0][3] is True)
    C.set_hidden(d, "smart", drama["id"], False)
    check("ويعود بإظهاره", C._view(d, "smart")[1]["counts"]["series"] == 9)
    C.clear(d, "smart")
    check("مسح المحتوى يخفي الصفحة ويُبقي السيرفر", C._view(d, "smart")[1] is None and C._server(d, "smart"))
    shutil.rmtree(d, ignore_errors=True)


def big(n_movies=650, prefix="Film"):
    return "#EXTM3U\n" + "".join(entry(f"{prefix} {i:04d} (2020)", "VOD | Big", "movie", 1000 + i) for i in range(n_movies))


def unit_render():
    print("الصفحة")
    d = fresh()
    seed(d)
    seed(d, "falcon", "#EXTM3U\n" + entry("Only In Falcon S01 E01", "Falcon Series", "series", 1)
         + entry("Breaking Bad S05 E01", "Falcon Series", "series", 2) + big(650))
    code, body, age = C.render(d, "smart", {})
    html = body.decode("utf-8")
    check("200 ومخزَّنة عشر دقائق", code == 200 and age == 600)
    check("العنوان والوصف بالأعداد", "<title>محتوى اشتراك سمارت: المسلسلات بمواسمها والأفلام والقنوات | سمارت سوق</title>" in html
          and "9 مسلسلات بمواسمها و4 أفلام و5 قنوات" in html)
    check("تُفهرس ولها canonical", 'content="index, follow' in html and
          '<link rel="canonical" href="https://guide.ssouq.com/content/smart">' in html)
    check("تبويب لكل سيرفرٍ له محتوى", '<a href="/content/smart" aria-current=page>سمارت</a>' in html
          and '<a href="/content/falcon">فالكون</a>' in html and "/content/kon" not in html)
    check("خانات الأعداد", "<b>9</b><small>مسلسلات</small>" in html and "<b>11</b><small>موسمًا</small>" in html)
    check("الأقسام بعددها وفتحها بلا سكربت", 'data-g="' in html and "اعرض القائمة</a>" in html and "مسلسلان</small>" in html)
    check("لا رابط ولا بيانات دخول ولا وسم من الملف", "pass456" not in html and "panel.example" not in html
          and "<script>alert(1)" not in html)
    check("باقات سمارت من CATALOG بحملة الصفحة", "p2091471394?utm_source=guide.ssouq.com&amp;utm_medium=referral&amp;utm_campaign=content" in html)

    drama = C._view(d, "smart")[1]["kinds"]["series"][0]
    code, body, _ = C.render(d, "smart", {"t": "series", "g": drama["id"]})
    html = body.decode("utf-8")
    check("صفحة القسم: المسلسل بمواسمه", code == 200 and "<b>Breaking Bad</b>" in html
          and "الموسم 1 <i>(حلقتان)</i>" in html and "الموسم 2 <i>(حلقة واحدة)</i>" in html)
    check("الاسم مهرَّبًا", "&lt;script&gt;alert(1)&lt;/script&gt;" in html and "<script>alert(1)" not in html)
    check("لا تُفهرس ولا canonical لها", 'content="noindex, follow"' in html and 'rel="canonical"' not in html)
    code, body, _ = C.render(d, "smart", {"t": "series", "g": "0000000000"})
    check("قسمٌ لم يعد موجودًا: 404 بالأقسام الحالية", code == 404 and "لم يعد موجودًا" in body.decode())

    fbig = C._view(d, "falcon")[1]["kinds"]["movie"][0]["id"]
    g1 = C.api_group(d, "falcon", "movie", fbig, 1)
    g3 = C.api_group(d, "falcon", "movie", fbig, 3)
    check("القسم صفحاتٌ من 300", g1["items"].count("<li>") == 300 and 'data-p="2"' in g1["more"]
          and "بقي 350 فيلمًا" in g1["more"] and g3["items"].count("<li>") == 50 and g3["more"] == "", g1["more"])
    code, body, _ = C.render(d, "falcon", {"t": "movie", "g": fbig, "p": "2"})
    html = body.decode()
    check("وبلا سكربت: التالي والسابق", "صفحة 2 من 3" in html and f"g={fbig}&amp;p=3" in html and f"g={fbig}&amp;p=1" in html)

    print("البحث بالاسم")
    r = C.api_search(d, "smart", "breaking")["html"]
    check("المسلسل بقسمه ومواسمه", "<b>Breaking Bad</b>" in r and "· SERIES | Drama" in r and "· Netflix" in r
          and "الموسم 3" in r, r[:200])
    check("ويوجد أيضًا في السيرفرات الأخرى", 'ويوجد أيضًا في: <a class="link" href="/content/falcon?q=breaking">فالكون (1)</a>' in r)
    r = C.api_search(d, "smart", "only in falcon")["html"]
    check("ما ليس هنا: أين يوجد", "لا يوجد «only in falcon» في سمارت" in r and "لكنه موجود في" in r and "فالكون (1)" in r)
    r = C.api_search(d, "smart", "عثمان")["html"]
    check("بالعربية", "المؤسس عثمان" in r and "الموسم 5 <i>(حلقتان)</i>" in r)
    check("بلا همزة", "المؤسس عثمان" in C.api_search(d, "smart", "الموسس")["html"])
    check("حرفٌ واحد لا يُبحث", C.api_search(d, "smart", "b")["html"] == "")
    r = C.api_search(d, "falcon", "film")["html"]
    check("الواسع: أولها وعددها كله", r.count("<li>") == C.SEARCH_MAX and "(650)" in r and "610 نتائج أخرى" in r, r[:160])
    r = C.api_search(d, "falcon", "film 0007")["html"]
    check("كل الكلمات، والمطابق تمامًا أولًا", "<li>Film 0007 (2020)" in r and r.count("<li>") == 1, r[-300:])
    check("لا نتائج", "لا يوجد" in C.api_search(d, "smart", "zzzz qqqq")["html"])
    code, body, _ = C.render(d, "smart", {"q": "breaking"})
    check("وبلا سكربت: ?q= على الصفحة نفسها", code == 200 and "نتائج «breaking»" in body.decode()
          and 'content="noindex, follow"' in body.decode())

    print("لا محتوى")
    code, body = C.render_missing(d, "kon")
    check("سيرفرٌ بلا محتوى: 404 تدلّ على غيره", code == 404 and 'href="/content/smart"' in body.decode()
          and "noindex" in body.decode())
    check("وسيرفرٌ لا وجود له", C.render(d, "nope", {})[0] == 404 and C.api_group(d, "nope", "movie", fbig) is None
          and C.api_search(d, "nope", "x") is None)
    check("‏/content إلى أوّلها", C.first_key(d) == "smart")
    b = C.brief(d)
    check("للرئيسية: السيرفرات وأعدادها", [s["key"] for s in b["servers"]] == ["smart", "falcon"]
          and b["servers"][0]["series"] == 9 and b["servers"][1]["movies"] == 650, b)
    check("خريطة الموقع", C.sitemap(d) == [("/content/smart", "daily", "0.7"), ("/content/falcon", "daily", "0.7")])
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
        n0 = len(_M3U.hits)
        C.tick(d)
        check("محتوى اليوم لا يُسحب ثانية", len(_M3U.hits) == n0)
        C.tick(d, now=time.time() + C.REFRESH + 1)
        check("بعد يوم يُسحب", len(_M3U.hits) == n0 + 1)
        C._update(d, "casper", url=C.crypto_store.encrypt(base + "/nothing-here", d))
        later = time.time() + 2 * C.REFRESH
        C.tick(d, now=later)
        n1 = len(_M3U.hits)
        C.tick(d, now=later + 60)
        check("والفشل لا يُعاد قبل RETRY", len(_M3U.hits) == n1 and C._server(d, "casper")["error"])
        C.tick(d, now=later + C.RETRY + 60)
        check("ويُعاد بعده", len(_M3U.hits) == n1 + 1)
        try:
            C.start_refresh(d, "kon")
            check("«اسحب الآن» بلا رابط", False)
        except ValueError:
            check("«اسحب الآن» بلا رابط", True)
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
    srv, iptv = mock_iptv()
    env = {k: v for k, v in os.environ.items() if not k.startswith("SALLA_ADMIN_TOKEN")}
    env.update(XM_DATA=data, XM_BIND="127.0.0.1", XM_PORT=str(port), XM_ADMIN_PASSWORD="envpass123")
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

        code, st = jpost(adm + "/api/content/admin/url",
                         {"s": "falcon", "url": iptv + "/get.php?username=user123&password=pass456&type=m3u_plus"})
        check("الرابط يُحفظ ويُسحب في الخلفية", code == 200 and st["servers"][3]["url"].endswith("/•••")
              and "pass456" not in json.dumps(st))
        for _ in range(50):
            fal = next(s for s in json.loads(req(adm + "/api/content/admin", auth=True)[1])["servers"] if s["key"] == "falcon")
            if fal["has"] and not fal["busy"]:
                break
            time.sleep(.1)
        check("وصار له محتوى", fal["has"] and fal["source"] == "url", fal.get("error"))
        code, st = jpost(adm + "/api/content/admin/refresh", {"s": "kon"})
        check("«اسحب الآن» بلا رابط", code == 400)
        code, st = jpost(adm + "/api/content/admin/server", {"new": True, "name": "نجم", "key": "najm"})
        check("إضافة سيرفر", code == 200 and st["servers"][-1]["key"] == "najm")
        g = next(x for x in next(s for s in st["servers"] if s["key"] == "smart")["groups"]["series"] if x[1] == "Netflix")
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
        check("القسم المخفي ليس فيها", "Netflix" not in html)
        check("تبويبات السيرفرات الثلاثة", all(f'href="/content/{k}"' in html for k in ("kon", "smart", "falcon")))
        code, raw, _ = req(base + "/content/smart/")
        check("بشرطةٍ في آخره", code == 200)
        code, raw, _ = req(base + "/api/content/search?s=smart&q=" + urllib.parse.quote("باب"))
        check("البحث", code == 200 and "باب الحارة" in json.loads(raw)["html"])
        code, raw, _ = req(base + "/api/content/search?s=kon&q=breaking")
        check("وأين يوجد", "لكنه موجود في" in json.loads(raw)["html"] and "فالكون" in json.loads(raw)["html"]
              and "سمارت" in json.loads(raw)["html"])
        grp = re.search(r'data-g="(\w+)"', html).group(1)
        code, raw, _ = req(base + f"/api/content/group?s=smart&t=series&g={grp}&p=1")
        check("فتح القسم", code == 200 and json.loads(raw)["items"].count("<li>") >= 1)
        check("قسمٌ أو سيرفرٌ لا وجود له", req(base + "/api/content/group?s=smart&t=series&g=xx")[0] == 404
              and req(base + "/api/content/search?s=nope&q=xx")[0] == 404)
        check("HEAD", req(base + "/content/smart", method="HEAD")[0] == 200)
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
        code, st = jpost(adm + "/api/content/admin/clear", {"s": "najm", "drop": True})
        check("حذف سيرفر", code == 200 and all(s["key"] != "najm" for s in st["servers"]))
    finally:
        p.terminate()
        p.wait(timeout=10)
        srv.shutdown()
        shutil.rmtree(data, ignore_errors=True)


def main():
    unit_parse()
    unit_store()
    unit_render()
    unit_fetch()
    live()
    print(f"\nResult: {_p} passed, {_f} failed")
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""إحصائيات الدليل (analytics.py وgoogle_api.py) بلا إنترنت — جوجل وIndexNow وهميّان (tests/mock_google.py):

  - التصنيف: المصدر من المُحيل وتطبيق أندرويد وutm_source و?ref=wa ومتصفح سناب، والداخلي والودجت، والجهاز والنظام
    والدولة، والزواحف (البحث والذكاء الاصطناعي ومعاينات المشاركة).
  - الزيارة: الزائر مرةً في يومه ولو أُعيد تشغيل الخادم، والدخول من خارج الموقع وحده زيارة، والأحداث بتفاصيلها،
    ومدة القراءة على دفعات، وما يُرفض (زاحف، بلا واجهة، من موقعٍ آخر، ضخم، مسارٌ غريب، فوق الحدّ). ومنتصف الليل يمحو
    ملح الأمس وبصماته، وتنظيف الأيام القديمة.
  - الربط: المعرّف من الكود الملصوق كاملًا، والحقن قبل </head>، والفارغ يزيل، والخاطئ يُرفض باسمه.
  - IndexNow: المفتاح وملفه، والإرسال لنطاق الموقع وحده، واليومي بعد السادسة مرةً في اليوم.
  - جوجل: مفتاح PKCS#8 وPKCS#1، وتوقيع RS256 (ويطابق OpenSSL إن وُجد)، ورمز الوصول يُحفظ، وتقارير GA4 وSearch Console
    وخرائط الموقع، وخاصية النطاق تُقصر على الدليل، والأخطاء تُشرح بالعربية.
  - على خادمٍ حيّ: الحقن في الصفحات العامة وحدها، و/api/hit، والزواحف، وملف IndexNow، وواجهات المدير وحمايتها، والمفتاح
    مشفّرٌ على القرص، وأعداد اليوم تُكتب حين يُطفأ الخادم.

تشغيل:  python tests/test_analytics.py
"""
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import analytics as A  # noqa: E402
import google_api as G  # noqa: E402
import mock_google as M  # noqa: E402

_p = _f = 0


def check(l, c, x=""):
    global _p, _f
    print((f"  \033[32mPASS\033[0m  {l}" if c else f"  \033[31mFAIL\033[0m  {l}") + (f"  ({x})" if x else ""))
    _p += 1 if c else 0
    _f += 0 if c else 1


T = datetime.datetime(2026, 9, 29, 9, 0, tzinfo=datetime.timezone.utc).timestamp()      # الظهر بتوقيت السعودية
OWN = {"guide.ssouq.com", "admin.ssouq.com"}
IPH = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
       "Version/17.5 Mobile/15E148 Safari/604.1")
WIN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
IPAD = ("Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 "
        "Mobile/15E148 Safari/604.1")
MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15"
AND = "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36"
TAB = "Mozilla/5.0 (Linux; Android 13; SM-X700) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
TIZEN = ("Mozilla/5.0 (SMART-TV; LINUX; Tizen 6.0) AppleWebKit/537.36 (KHTML, like Gecko) 85.0.4183.93/6.0 "
         "TV Safari/537.36")
WEBOS = ("Mozilla/5.0 (Web0S; Linux/SmartTV) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.88 Safari/537.36 "
         "WebAppManager")
FIRETV = "Mozilla/5.0 (Linux; Android 9; AFTMM Build/PS7285) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
GBOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"


def H(ua=IPH, origin="https://guide.ssouq.com", **kw):
    return {"User-Agent": ua, "Origin": origin, **kw}


def pv(p="/", r="", q="", tz="Asia/Riyadh", tp=0):
    return json.dumps({"t": "pv", "p": p, "r": r, "q": q, "tz": tz, "tp": tp}).encode()


def ev(n, l="", p="/"):
    return json.dumps({"t": "ev", "n": n, "l": l, "p": p}).encode()


def end(d, f, p="/"):
    return json.dumps({"t": "end", "d": d, "f": f, "p": p}).encode()


def day_file(d, day):
    return os.path.join(d, "analytics", "days", day + ".json")


def unit_classify():
    print("التصنيف: المصدر والجهاز والدولة والزواحف")
    src = lambda r, q="", ua=WIN: A.source(r, q, ua, OWN)[0]
    check("جوجل من المُحيل (ونطاقاتها الوطنية)", src("https://www.google.com.sa/") == "google" and src("https://www.google.com/") == "google")
    check("واتساب من تطبيق أندرويد (android-app://)", src("android-app://com.whatsapp/") == "whatsapp")
    check("t.co إكس، وsnapchat.com سناب، وbing بينج", src("https://t.co/xyz") == "x" and src("https://www.snapchat.com/") == "snapchat"
          and src("https://www.bing.com/search?q=x") == "bing")
    check("Gemini قبل جوجل، وChatGPT وPerplexity", src("https://gemini.google.com/app") == "gemini" and src("https://chatgpt.com/") == "chatgpt"
          and src("https://www.perplexity.ai/search") == "perplexity")
    check("المتجر ssouq.com", src("https://ssouq.com/p479880741") == "store")
    check("التنقّل داخل الموقع ولوحة الإدارة ليسا دخولًا", src("https://guide.ssouq.com/iphone") == "internal"
          and src("https://admin.ssouq.com/stats") == "internal")
    check("ودجت المتجر (iframe من موقعنا في رئيسية سلة)", src("https://guide.ssouq.com/gulf-cup/widget") == "widget")
    check("متصفح سناب بلا مُحيل = سناب، وتيك توك وإنستغرام كذلك",
          src("", ua=IPH + " Snapchat/12.90.0.46 (like Safari/8618)") == "snapchat"
          and src("", ua=AND + " musical_ly_2023501030 JsSdk/1.0 BytedanceWebview/d8a21c6") == "tiktok"
          and src("", ua=IPH + " Instagram 312.0.0.34.111 (iPhone15,2; iOS 17_5)") == "instagram")
    check("بلا مُحيل ولا ما يدلّ = مباشر", src("", ua=IPH) == "direct")
    s, ext, camp = A.source("", "?t=new&ref=wa", IPH, OWN)
    check("?ref=wa (رابط القناة) = واتساب بحملته", s == "whatsapp" and camp == "ref / wa" and ext == "", (s, camp))
    s, ext, camp = A.source("https://www.google.com/", "?utm_source=snap&utm_medium=paid_social&utm_campaign=Ramadan", WIN, OWN)
    check("utm_source يغلب المُحيل، والاسم المختصر يُفهم", s == "snapchat" and camp == "snap / paid_social / ramadan"
          and ext == "www.google.com", (s, camp, ext))
    s, ext, _ = A.source("https://forum.example.org/t/1", "", WIN, OWN)
    check("وموقعٌ غيرها يُحفظ نطاقه", s == "other" and ext == "forum.example.org")

    got = [(A.device(u, t), A.os_name(u, t)) for u, t in ((IPH, 5), (IPAD, 5), (MAC, 5), (MAC, 0), (AND, 5), (TAB, 5), (WIN, 0),
                                                         (TIZEN, 0), (WEBOS, 0), (FIRETV, 0))]
    check("الأجهزة والأنظمة (والآيباد الذي يعرّف نفسه ماك يكشفه اللمس)", got == [
        ("mobile", "ios"), ("tablet", "ios"), ("tablet", "ios"), ("desktop", "macos"), ("mobile", "android"), ("tablet", "android"),
        ("desktop", "windows"), ("tv", "tizen"), ("tv", "webos"), ("tv", "android")], got)
    check("الدولة من المنطقة الزمنية، وCF-IPCountry أولى منها", A.country("Asia/Riyadh") == "SA" and A.country("Asia/Kuwait") == "KW"
          and A.country("America/Chicago") == "US" and A.country("Asia/Riyadh", "ae") == "AE" and A.country("Mars/Base") == "??"
          and A.country("", "XX") == "??")
    check("الزواحف بأسمائها", A.crawler(GBOT) == "Google" and A.crawler("WhatsApp/2.23.20.0 A") == "WhatsApp"
          and A.crawler("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)") == "ChatGPT"
          and A.crawler("Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)") == "Bing" and A.crawler(IPH) == "")
    check("المسار: بلا استعلامٍ ولا شرطةٍ أخيرة، والغريب يُرفض", A.clean_path("/iphone?x=1#y") == "/iphone"
          and A.clean_path("/content/kon/") == "/content/kon" and A.clean_path("javascript:alert(1)") == ""
          and A.clean_path("/<script>") == "" and A.clean_path("/") == "/")


def unit_hits():
    print("الزيارة: تُعدّ مرةً للزائر في يومه، والدخول من خارج الموقع وحده زيارة")
    d = tempfile.mkdtemp(prefix="an_")
    try:
        A.hit(d, pv("/", "https://www.google.com/"), H(), "1.1.1.1", OWN, now=T)
        A.hit(d, pv("/iphone", "https://guide.ssouq.com/"), H(), "1.1.1.1", OWN, now=T + 30)
        A.hit(d, pv("/", "", tz="Asia/Kuwait"), H(WIN), "2.2.2.2", OWN, now=T + 60)
        r = A.report(d, 7, now=T + 90)
        t = r["totals"]
        check("ثلاث مشاهدات لزائرين، وزيارتان", (t["pv"], t["uv"], t["in"]) == (3, 2, 2), t)
        check("صفحات الدخول ومصادرها", dict(r["landing"]) == {"/": 2} and dict(r["sources"]) == {"google": 1, "direct": 1}
              and dict(r["refs"]) == {"www.google.com": 1}, (r["landing"], r["sources"]))
        check("الجهاز والنظام والدولة لكل زائرٍ مرة", dict(r["devices"]) == {"mobile": 1, "desktop": 1}
              and dict(r["os"]) == {"ios": 1, "windows": 1} and dict(r["countries"]) == {"SA": 1, "KW": 1})
        check("والساعة بتوقيت السعودية، ومن في الموقع الآن", r["hours"][12] == 3 and r["live"]["n"] == 2
              and dict(r["live"]["pages"]) == {"/iphone": 1, "/": 1}, (r["hours"][12], r["live"]))
        check("وأيام المدة كلها بأرقامها (الفارغ صفر)", len(r["daily"]) == 7 and r["daily"][-1] == {"d": "2026-09-29", "pv": 3, "uv": 2, "in": 2}
              and r["daily"][0]["pv"] == 0 and r["from"] == "2026-09-23")

        A.hit(d, ev("store_click", "p479880741"), H(), "1.1.1.1", OWN, now=T + 100)
        A.hit(d, ev("store_click", "p479880741"), H(WIN), "2.2.2.2", OWN, now=T + 101)
        A.hit(d, ev("whatsapp_click", "channel"), H(), "1.1.1.1", OWN, now=T + 102)
        bad = A.hit(d, ev("Bad Name!"), H(), "1.1.1.1", OWN, now=T + 103)
        r = A.report(d, 1, now=T + 110)
        e = {x["n"]: x for x in r["events"]}
        check("نقرات الشراء برقم المنتج، وواتساب بنوعه", e["store_click"]["c"] == 2 and e["store_click"]["top"] == [["p479880741", 2]]
              and e["whatsapp_click"]["top"] == [["channel", 1]] and r["totals"]["store"] == 2, r["events"])
        check("واسم حدثٍ غير صالح يُهمل", not bad and set(e) == {"store_click", "whatsapp_click"})

        A.hit(d, end(40, 1), H(), "1.1.1.1", OWN, now=T + 120)
        A.hit(d, end(20, 0), H(), "1.1.1.1", OWN, now=T + 130)            # دفعةٌ ثانية للمشاهدة نفسها
        A.hit(d, end(99999, 1, "/iphone"), H(), "1.1.1.1", OWN, now=T + 140)
        r = A.report(d, 1, now=T + 150)
        pages = {p[0]: p for p in r["pages"]}
        check("مدة القراءة: الدفعات تُجمع للمشاهدة الواحدة، والطويلة تُقصّ عند نصف ساعة",
              pages["/"][2] == 60 and pages["/iphone"][2] == 1800 and r["totals"]["dur"] == 930, (pages, r["totals"]["dur"]))

        print("ما لا يُعدّ")
        check("زاحفٌ ليس زائرًا", not A.hit(d, pv(), H(GBOT), "3.3.3.3", OWN, now=T + 161))
        check("ولا متصفحٌ بلا واجهة", not A.hit(d, pv(), H("Mozilla/5.0 (X11; Linux) HeadlessChrome/128.0 Safari/537.36"), "3.3.3.3", OWN, now=T + 161))
        check("ولا إرسالٌ من موقعٍ آخر، ولا بلا Origin وReferer", not A.hit(d, pv(), H(origin="https://evil.example"), "3.3.3.3", OWN, now=T + 161)
              and not A.hit(d, pv(), {"User-Agent": IPH}, "3.3.3.3", OWN, now=T + 161))
        check("وOrigin «null» يُقبل مع Referer من موقعنا", A.hit(d, pv("/mac"), {"User-Agent": IPH, "Origin": "null",
                                                                             "Referer": "https://guide.ssouq.com/mac"}, "3.3.3.3", OWN, now=T + 162))
        check("ولا جسمٌ ضخم أو تالف، ولا مسارٌ غريب", not A.hit(d, b"x" * 5000, H(), "3.3.3.3", OWN, now=T + 163)
              and not A.hit(d, b"{bad", H(), "3.3.3.3", OWN, now=T + 163)
              and not A.hit(d, pv("javascript:alert(1)"), H(), "3.3.3.3", OWN, now=T + 163))
        n = sum(A.hit(d, pv("/android"), H(AND), "4.4.4.4", OWN, now=T + 170) for _ in range(A.RATE + 20))
        check("وحدّ الإرسال للزائر في الدقيقة", n == A.RATE, n)

        print("إعادة التشغيل ومنتصف الليل")
        A.flush(d, force=True)
        today = json.load(open(day_file(d, "2026-09-29")))
        check("ملف اليوم يحفظ الملح والبصمات ما دام اليوم يومه", today.get("_salt") and len(today.get("_seen", [])) == 4)
        uv = today["uv"]
        A._S.update(dir=None, day=None, agg=None)                          # كأن الخادم أُعيد تشغيله
        A.hit(d, pv("/windows"), H(WIN), "2.2.2.2", OWN, now=T + 400)
        check("وزائر اليوم يبقى زائرًا واحدًا بعد إعادة التشغيل", A.report(d, 1, now=T + 401)["totals"]["uv"] == uv)
        T2 = T + 86400
        A.hit(d, pv("/"), H(WIN), "2.2.2.2", OWN, now=T2)
        A.flush(d, force=True)
        y = json.load(open(day_file(d, "2026-09-29")))
        check("منتصف الليل: الأمس يُكتب بلا ملحٍ ولا بصمات", "_salt" not in y and "_seen" not in y and y["uv"] == uv)
        r = A.report(d, 2, now=T2 + 10)
        check("واليوم الجديد يبدأ عدّه (زائر الأمس زائرٌ جديد اليوم)", A.report(d, 1, now=T2 + 10)["totals"]["uv"] == 1
              and r["totals"]["uv"] == uv + 1 and [x["d"] for x in r["daily"]] == ["2026-09-29", "2026-09-30"])
        r7 = A.report(d, 1, now=T2 + 20)
        check("والمقارنة: «اليوم» بالأمس", r7["prev"]["uv"] == uv and r7["prev"]["pv"] == y["pv"])

        old = (datetime.date(2026, 9, 30) - datetime.timedelta(days=A.KEEP_DAYS + 3)).isoformat()
        json.dump(A.blank(), open(day_file(d, old), "w"))
        leak = dict(A.blank(), _salt="s", _seen=["x"])
        json.dump(leak, open(day_file(d, "2026-09-20"), "w"))
        A.prune(d, now=T2)
        check("التنظيف: الأقدم من المدة يُحذف، وملحٌ بقي في يومٍ مضى يُمحى", not os.path.exists(day_file(d, old))
              and "_salt" not in json.load(open(day_file(d, "2026-09-20"))) and os.path.exists(day_file(d, "2026-09-29")))

        print("الزواحف والمشاركات تُعدّ من الخادم")
        A.crawl(d, GBOT, "/iphone", now=T2 + 30)
        A.crawl(d, "WhatsApp/2.24.1.1 A", "/predict?x=1", now=T2 + 31)
        A.crawl(d, "WhatsApp/2.24.1.1 i", "/predict", now=T2 + 32)
        check("وزائرٌ عادي ليس زاحفًا", A.crawl(d, IPH, "/", now=T2 + 33) == "")
        r = A.report(d, 1, now=T2 + 40)
        check("بأسمائها وأنواعها، وصفحات المشاركة", ["Google", 1, "search"] in r["bots"] and ["WhatsApp", 2, "share"] in r["bots"]
              and r["shared"] == [["/predict", 2]] and r["totals"]["pv"] == 1, (r["bots"], r["shared"]))
        A.count(d, "m3u_generate", now=T2 + 50)
        check("وحدثٌ من الخادم نفسه", any(e["n"] == "m3u_generate" for e in A.report(d, 1, now=T2 + 60)["events"]))
    finally:
        A._S.update(dir=None, day=None, agg=None)
        shutil.rmtree(d, ignore_errors=True)


GA_SNIP = """<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-AB12CD34EF"></script>
<script>window.dataLayer = window.dataLayer || []; function gtag(){dataLayer.push(arguments);} gtag('js', new Date());
gtag('config', 'G-AB12CD34EF');</script>"""


def unit_tags():
    print("الربط: المعرّفات ووسوم التحقّق في رأس كل صفحة")
    d = tempfile.mkdtemp(prefix="an_")
    try:
        A.head(d), A.report(d, 7, now=T), A.summary(d, now=T), A.prune(d, now=T), A.flush(d, force=True)
        A.crawl(d, IPH, "/", now=T)
        check("القراءة والعامل الخلفي لا يكتبان على القرص شيئًا", not os.path.exists(os.path.join(d, "analytics"))
              and not A.daily_due(d, now=T))
        h = A.head(d)
        check("بلا ربطٍ: سكربت العدّاد وحده", b"/static/sq.js?v=" in h and b"window.sq=" in h and b"googletagmanager" not in h
              and b"google-site-verification" not in h)
        tags = A.save_tags(d, {
            "ga": GA_SNIP,
            "gsv": '<meta name="google-site-verification" content="Zx9_abcdefghijklmnopqrstuvwxyz0123456789-AB" />',
            "bing": '<meta name="msvalidate.01" content="0123456789abcdef0123456789abcdef" />',
            "snap": "snaptr('init', 'A1B2C3D4-1111-2222-3333-444455556666', {'user_email': '__INSERT_USER_EMAIL__'});",
            "meta": "fbq('init', '123456789012345'); fbq('track', 'PageView');",
            "tiktok": "ttq.load('CABCDEFGHIJKLMNOPQRS'); ttq.page();",
            "clarity": '})(window, document, "clarity", "script", "abcd1234ef");',
            "gtm": "gtm-5abc123",
        })
        check("المعرّف يُستخرج من الكود الملصوق كاملًا", tags == {
            "ga": "G-AB12CD34EF", "gtm": "GTM-5ABC123", "clarity": "abcd1234ef", "meta": "123456789012345",
            "snap": "a1b2c3d4-1111-2222-3333-444455556666", "tiktok": "CABCDEFGHIJKLMNOPQRS",
            "gsv": "Zx9_abcdefghijklmnopqrstuvwxyz0123456789-AB", "bing": "0123456789ABCDEF0123456789ABCDEF"}, tags)
        h = A.head(d).decode()
        need = ['<meta name="google-site-verification" content="Zx9_abcdefghijklmnopqrstuvwxyz0123456789-AB">',
                '<meta name="msvalidate.01" content="0123456789ABCDEF0123456789ABCDEF">', "gtag/js?id=G-AB12CD34EF",
                'gtag("config","G-AB12CD34EF",c)', '"dataLayer","GTM-5ABC123"', '"clarity","script","abcd1234ef"',
                'fbq("init","123456789012345")', 'snaptr("init","a1b2c3d4-1111-2222-3333-444455556666",{})',
                'ttq.load("CABCDEFGHIJKLMNOPQRS")', "window.SQ_GTM=1"]
        check("وكلها في رأس الصفحة", all(x in h for x in need), [x for x in need if x not in h])
        check("ولا يُحمَّل شيءٌ منها لمن استثنى زياراته (?sq=off)", h.count("if(!window.sqOff)") == 6)
        body = b"<!doctype html><html><head><title>x</title></head><body><p>a</p></body></html>"
        out = A.inject(body, d)
        check("الحقن قبل أول </head>، والصفحة كما هي", out.index(b"sq.js") < out.index(b"</head>") and out.replace(A.head(d), b"") == body)
        check("وصفحةٌ بلا </head> لا تُمسّ", A.inject(b"<p>x</p>", d) == b"<p>x</p>")
        try:
            A.save_tags(d, {"ga": "UA-12345-1", "meta": ""})
            err = ""
        except ValueError as e:
            err = str(e)
        check("قيمةٌ خاطئة ترفض الحفظ كله باسم حقلها", "Google Analytics" in err and A.settings(d)["tags"]["meta"] == "123456789012345")
        A.save_tags(d, {"meta": "", "gsv": "google-site-verification=Zx9_abcdefghijklmnopqrstuvwxyz0123456789-AC"})
        h = A.head(d)
        check("والفارغ يُزيل، وصيغة سجل DNS تُفهم", b"fbevents" not in h and b"Zx9_abcdefghijklmnopqrstuvwxyz0123456789-AC" in h)
        pub = A.public_settings(d)
        check("الإعداد للصفحة: المعرّفات وIndexNow بلا أسرار", pub["tags"]["ga"] == "G-AB12CD34EF" and len(pub["indexnow"]["key"]) == 32
              and pub["google"] == {"email": "", "project": "", "has_key": False, "ga": "", "site": ""})
    finally:
        shutil.rmtree(d, ignore_errors=True)


def unit_google_form():
    print("ربط جوجل: ما يُكتب في الحقول")
    d = tempfile.mkdtemp(prefix="an_")
    try:
        check("معرّف القياس بلا «G-» يُكمَل", A.save_tags(d, {"ga": "fcvqwzygsk"})["ga"] == "G-FCVQWZYGSK")
        errs = []
        for bad in ("FCVQWZYGSK", "G-FCVQWZYGSK", "G-1AB2C3D4E5"):
            try:
                A.save_google(d, {"ga": bad}, G.load_key)
                errs.append("")
            except ValueError as e:
                errs.append(str(e))
        check("ومعرّف القياس في حقل رقم الخاصية يُرفض ويُدلّ على حقله (ولا تُؤخذ أرقامه رقمَ خاصية)",
              all("معرّف القياس" in e and "أعلى الصفحة" in e for e in errs) and A.public_settings(d)["google"]["ga"] == "", errs)
        g = A.save_google(d, {"ga": " properties/282146447 ", "site": "https://guide.ssouq.com"}, G.load_key)
        check("ورقم الخاصية بصيغة properties/…، والموقع بلا «/» في آخره يُكمَل", g["ga"] == "282146447"
              and g["site"] == "https://guide.ssouq.com/", g)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def start_mock(pub):
    M.H.pub = pub
    srv = ThreadingHTTPServer(("127.0.0.1", 0), M.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def unit_indexnow(base):
    print("IndexNow: المفتاح وملفه، والإرسال، واليومي")
    d = tempfile.mkdtemp(prefix="an_")
    A.INDEXNOW_URL = base + "/indexnow"
    try:
        pages = [("/", "weekly"), ("/content/kon", "daily"), ("/watch", "hourly"), ("/iphone", "monthly")]
        check("بلا مفتاح: لا ملفّ يُقدَّم ولا إرسالٌ يومي، ولا يُكتب شيء", A.indexnow_key_file(d, "/" + "a" * 32 + ".txt") is None
              and A.daily_submit(d, "guide.ssouq.com", pages, now=T) is None and not os.path.exists(os.path.join(d, "analytics")))
        ix = A.indexnow(d)
        check("المفتاح يُولَّد مرةً ويبقى، واليومي مفعّل افتراضًا", len(ix["key"]) == 32 and A.indexnow(d)["key"] == ix["key"] and ix["auto"]
              and not ix["confirmed"])
        n0 = len(M.STATE["indexnow"])
        check("واليومي لا يبدأ قبل أول إرسالٍ ناجح منك", A.daily_submit(d, "guide.ssouq.com", pages, now=T) is None
              and len(M.STATE["indexnow"]) == n0)
        check("وملفه على /<المفتاح>.txt وحده", A.indexnow_key_file(d, f"/{ix['key']}.txt") == ix["key"]
              and A.indexnow_key_file(d, "/" + "0" * 32 + ".txt") is None and A.indexnow_key_file(d, "/robots.txt") is None)
        res = A.submit(d, "guide.ssouq.com", ["https://guide.ssouq.com/", "https://guide.ssouq.com/iphone", "https://evil.com/x",
                                              "https://guide.ssouq.com/"], now=T)
        check("الإرسال: صفحات النطاق وحدها بلا تكرار، والمفتاح ومكان ملفه", res["ok"] and res["n"] == 2 and M.STATE["indexnow"][-1] == {
            "host": "guide.ssouq.com", "key": ix["key"], "keyLocation": f"https://guide.ssouq.com/{ix['key']}.txt",
            "urlList": ["https://guide.ssouq.com/", "https://guide.ssouq.com/iphone"]}, M.STATE["indexnow"][-1:])
        check("ويُحفظ آخر إرسال، ويُفعَّل اليومي", A.indexnow(d)["last"]["n"] == 2 and A.indexnow(d)["last"]["kind"] == "manual"
              and A.indexnow(d)["confirmed"])
        M.STATE["mode"]["indexnow"] = 403
        res = A.submit(d, "guide.ssouq.com", ["https://guide.ssouq.com/"], now=T)
        M.STATE["mode"]["indexnow"] = 200
        check("ورفض المفتاح يُشرح (واليومي باقٍ)", not res["ok"] and res["code"] == 403 and "المفتاح" in res["msg"]
              and A.indexnow(d)["confirmed"], res)
        check("اليومي: لا قبل السادسة صباحًا", A.daily_submit(d, "guide.ssouq.com", pages, now=T - 9 * 3600) is None)
        r1 = A.daily_submit(d, "guide.ssouq.com", pages, now=T)
        check("وبعدها الصفحات التي تتغيّر يوميًا وحدها", r1 and r1["kind"] == "auto"
              and M.STATE["indexnow"][-1]["urlList"] == ["https://guide.ssouq.com/content/kon", "https://guide.ssouq.com/watch"])
        check("ومرةً في اليوم", A.daily_submit(d, "guide.ssouq.com", pages, now=T + 3600) is None
              and A.daily_submit(d, "guide.ssouq.com", pages, now=T + 86400) is not None)
        A.set_indexnow_auto(d, False)
        check("والمعطّل لا يُرسل", A.daily_submit(d, "guide.ssouq.com", pages, now=T + 2 * 86400) is None and not A.indexnow(d)["auto"])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def unit_google(base, pem, pub):
    print("جوجل: المفتاح والتوقيع ورمز الوصول")
    k8 = G.load_key(pem)
    pem1, _ = M.make_key(1024, seed=11, pkcs1=True)
    k1 = G.load_key(pem1)
    check("المفتاح يُقرأ بصيغتيه PKCS#8 وPKCS#1، والـ\\n المهرّبة", k8["n"] == pub["n"] and k1 == G.load_key(M.make_key(1024, seed=11)[0])
          and G.load_key(pem.replace("\n", "\\n")) == k8)
    sa = M.service_account(pem)
    check("JWT موقَّع RS256 تقبله جوجل: المُصدِر والنطاقات والجمهور وساعة الصلاحية", M.verify(G.jwt(sa), pub) is not None)
    if shutil.which("openssl"):
        tmp = tempfile.mkdtemp(prefix="an_")
        kp, mp = os.path.join(tmp, "k.pem"), os.path.join(tmp, "m")
        open(kp, "w").write(pem)
        open(mp, "wb").write(b"header.claims")
        ref = subprocess.run(["openssl", "dgst", "-sha256", "-sign", kp, mp], capture_output=True).stdout
        check("والتوقيع يطابق OpenSSL بايتًا ببايت", ref and G.sign(k8, b"header.claims") == ref)
        shutil.rmtree(tmp, ignore_errors=True)
    try:
        G.load_key("-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----")
        broken = False
    except Exception:
        broken = True
    check("ومفتاحٌ تالف يُرفض", broken)

    G.TOKEN_URL, G.GA_API, G.GA_ADMIN, G.GSC_API = base + "/token", base + "/ga/v1beta", base + "/gaadmin/v1beta", base + "/gsc"
    G.clear_cache()
    creds = {"sa": sa, "email": sa["client_email"], "ga": "424242", "site": "https://guide.ssouq.com/"}
    M.STATE["gsc_queries"].clear()
    r = G.report(creds, 7, "guide.ssouq.com")
    ga = r["ga"]
    check("GA4: المجموع ولكل يوم، والقنوات والمصادر والدول والصفحات", r["ok"] and ga["totals"] == {"users": 728, "sessions": 868,
          "views": 1834, "engagement": 0.61} and len(ga["daily"]) == 7 and ga["daily"][0] == {"d": "2026-09-01", "users": 101,
          "sessions": 121, "views": 253} and ga["channels"][0] == ["Organic Search", 820] and ga["countries"][0] == ["SA", 1500]
          and ga["pages"][0] == ["/", 900], ga.get("totals"))
    check("و«الآن» من التقرير اللحظي", ga["realtime"]["users"] == 7 and len(ga["realtime"]["pages"]) == 2)
    sc = r["gsc"]
    today = datetime.datetime.now(G.RIYADH).date()
    rng = {(q["startDate"], q["endDate"]) for q in M.STATE["gsc_queries"] if not q.get("dimensions")}
    check("Search Console: المجموع ومقارنته بالمدة التي قبلها بطولها", sc["totals"]["clicks"] == 120 and sc["prev"]["clicks"] == 80
          and rng == {((today - datetime.timedelta(days=6)).isoformat(), today.isoformat()),
                      ((today - datetime.timedelta(days=13)).isoformat(), (today - datetime.timedelta(days=7)).isoformat())}, rng)
    check("والاستعلامات والصفحات ولكل يوم (مرتّبة)", sc["queries"][0] == ["اشتراك iptv", 40, 900, 0.044, 6.2] and len(sc["pages"]) == 2
          and sc["daily"][0]["d"] == "2026-09-01" and all(q.get("dataState") == "all" for q in M.STATE["gsc_queries"]))
    check("وموقعٌ ببادئة عنوان: بلا تصفية", not any(q.get("dimensionFilterGroups") for q in M.STATE["gsc_queries"]))
    tokens = sum(1 for m, p in M.STATE["log"] if p == "/token")
    calls = len(M.STATE["log"])
    G.report(creds, 7, "guide.ssouq.com")
    check("والرمز والتقارير محفوظة: لا طلب جديد لجوجل خلال دقائق", len(M.STATE["log"]) == calls
          and sum(1 for m, p in M.STATE["log"] if p == "/token") == tokens == 1, (tokens, len(M.STATE["log"]) - calls))
    res = G.send_sitemaps(creds, ["https://guide.ssouq.com/sitemap.xml", "https://guide.ssouq.com/store-sitemap.xml"])
    r = G.report(creds, 7, "guide.ssouq.com")
    check("إرسال خريطتي الموقع، ثم حالهما عند جوجل (بلا انتظار الحفظ)", all(x["ok"] for x in res)
          and [s["path"] for s in r["gsc"]["sitemaps"]] == ["https://guide.ssouq.com/sitemap.xml", "https://guide.ssouq.com/store-sitemap.xml"]
          and r["gsc"]["sitemaps"][0]["urls"] == 64)
    M.STATE["gsc_queries"].clear()
    G.report(dict(creds, site="sc-domain:ssouq.com"), 7, "guide.ssouq.com")
    check("وخاصية النطاق (sc-domain) تُقصر على صفحات الدليل", all(q["dimensionFilterGroups"][0]["filters"][0]["expression"] == "://guide.ssouq.com/"
                                                                for q in M.STATE["gsc_queries"]) and M.STATE["gsc_queries"])

    print("جوجل: الأخطاء تُشرح")
    r = G.report(dict(creds, ga="403", site=""), 7, "guide.ssouq.com", fresh=True)
    check("خاصيةٌ بلا إذن: التلميح بإضافة بريد الحساب", r["ok"] and r["ga"]["error"]["code"] == 403
          and "أضف بريد حساب الخدمة" in r["ga"]["error"]["hint"] and r["gsc"] is None, r["ga"])
    M.STATE["mode"]["ga"] = "disabled"
    r = G.report(dict(creds, ga="555", site=""), 7, "guide.ssouq.com", fresh=True)
    M.STATE["mode"]["ga"] = "ok"
    check("وواجهةٌ غير مفعّلة: رابط تفعيلها", "فعّل" in r["ga"]["error"]["hint"]
          and r["ga"]["error"]["url"].startswith("https://console.developers.google.com/apis/api/analyticsdata"), r["ga"])
    other, _ = M.make_key(1024, seed=99)
    r = G.report(dict(creds, sa=M.service_account(other, "x@y.iam.gserviceaccount.com")), 7, "guide.ssouq.com", fresh=True)
    check("ومفتاحٌ لا تعرفه جوجل: لا رمز، والسبب", not r["ok"] and "رفضت المفتاح" in r["hint"], r)
    c = G.check(creds)
    check("«اختبر الربط»: الخصائص والمواقع التي يراها الحساب", c["ok"] and c["properties"] == [{"id": "424242", "name": "guide.ssouq.com",
          "account": "سمارت سوق"}] and [s["url"] for s in c["sites"]] == ["https://guide.ssouq.com/", "sc-domain:ssouq.com"])
    M.STATE["mode"]["admin"] = "disabled"
    c = G.check(creds)
    M.STATE["mode"]["admin"] = "ok"
    check("وبلا Admin API تبقى المواقع ويُشرح ما ينقص", c["ok"] and c["properties"] == [] and c["properties_error"]["url"]
          and len(c["sites"]) == 2)
    M.STATE["mode"]["gsc"] = "restricted"
    res = G.send_sitemaps(creds, ["https://guide.ssouq.com/sitemap.xml"])
    M.STATE["mode"]["gsc"] = "ok"
    check("وإرسال الخريطة بإذنٍ مقيَّد يُشرح", not res[0]["ok"] and res[0]["code"] == 403 and res[0]["hint"])


# ================= على خادمٍ حيّ =================
PORT, MPORT = 9761, 9762
ADMIN_PW = "stats-pass-1"


def req(path, host="guide.ssouq.com", method="GET", body=None, headers=None, auth=False, raw=False):
    h = dict(headers or {})
    if host:
        h["Host"] = host
    if auth:
        import base64
        h["Authorization"] = "Basic " + base64.b64encode(f"admin:{ADMIN_PW}".encode()).decode()
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
    rq = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=data, headers=h, method=method)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    try:
        r = urllib.request.build_opener(NoRedirect).open(rq, timeout=20)
        code, out = r.getcode(), r.read()
    except urllib.error.HTTPError as e:
        code, out = e.code, e.read()
    if raw:
        return code, out
    try:
        return code, json.loads(out or b"{}")
    except ValueError:
        return code, out.decode("utf-8", "replace")


def wait_up(url):
    for _ in range(80):
        try:
            urllib.request.urlopen(url, timeout=0.5)
            return
        except urllib.error.HTTPError:
            return
        except Exception:
            time.sleep(0.1)


def live(pem, pub):
    print("على خادمٍ حيّ")
    data = tempfile.mkdtemp(prefix="an_live_")
    keyf = os.path.join(data, "pub.json")
    json.dump(pub, open(keyf, "w"))
    mock = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_google.py"), str(MPORT), keyf],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    g = f"http://127.0.0.1:{MPORT}"
    env = dict(os.environ, XM_DATA=data, XM_BIND="127.0.0.1", XM_PORT=str(PORT), XM_ADMIN_PASSWORD=ADMIN_PW,
               XM_GOOGLE_TOKEN_URL=g + "/token", XM_GA_API=g + "/ga/v1beta", XM_GA_ADMIN_API=g + "/gaadmin/v1beta",
               XM_GSC_API=g + "/gsc", XM_INDEXNOW_URL=g + "/indexnow")
    app = subprocess.Popen([sys.executable, os.path.join(ROOT, "xm_lines.py"), "web"], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_up(f"http://127.0.0.1:{PORT}/robots.txt")
        wait_up(g + "/_test/state")
        code, home = req("/", raw=True)
        head = home.split(b"</head>", 1)[0]
        check("الرئيسية: سكربت العدّاد في رأسها", code == 200 and b'<script src="/static/sq.js?v=' in head and b"window.sq=" in head)
        check("وصفحات الأجهزة والمشاهدة والترتيب كذلك", all(b"/static/sq.js" in req(p, raw=True)[1] for p in ("/samsung-lg", "/watch", "/predict")))
        check("وودجت المتجر لا (زوار المتجر ليسوا زوار الدليل)", b"sq.js" not in req("/gulf-cup/widget", raw=True)[1])
        check("ولا صفحات الأداة", b"sq.js" not in req("/admin/login", host="127.0.0.1", raw=True)[1]
              and b"sq.js" not in req("/login", host="admin.ssouq.com", raw=True)[1])
        code, js = req("/static/sq.js", raw=True)
        check("والسكربت نفسه", code == 200 and b"/api/hit" in js and b"sendBeacon" in js)

        hh = {"Origin": "https://guide.ssouq.com", "User-Agent": IPH, "X-Forwarded-For": "5.5.5.5"}
        code, _ = req("/api/hit", method="POST", body=pv("/samsung-lg", "https://www.google.com/"), headers=hh)
        req("/api/hit", method="POST", body=ev("store_click", "p1859503976", "/samsung-lg"), headers=hh)
        c2, _ = req("/api/hit", method="POST", body=pv(), headers=dict(hh, **{"User-Agent": GBOT}))
        c3, _ = req("/api/hit", method="POST", body=pv(), headers=dict(hh, Origin="https://evil.example"))
        check("/api/hit: ‏204 لكل إرسال (ما لا يُعدّ لا يُقال لمرسله)", code == c2 == c3 == 204)
        req("/iphone", headers={"User-Agent": GBOT})
        req("/predict", headers={"User-Agent": "WhatsApp/2.24.1.1 A"})
        code, r = req("/admin/api/analytics/report?days=7", host="127.0.0.1", auth=True)
        check("التقرير: الزيارة والنقرة والزواحف والمشاركة", code == 200 and r["totals"]["pv"] == 1 and r["totals"]["uv"] == 1
              and r["sources"] == [["google", 1]] and r["totals"]["store"] == 1 and ["Google", 1, "search"] in r["bots"]
              and r["shared"] == [["/predict", 1]] and r["products"]["p1859503976"].startswith("اشتراك IPTV لسامسونج"), r.get("totals"))
        code, s = req("/admin/api/analytics/summary", host="127.0.0.1", auth=True)
        check("وبطاقة رئيسية اللوحة", code == 200 and s["today"]["uv"] == 1 and s["live"] == 1)

        code, _ = req("/admin/api/analytics/report", host="127.0.0.1")
        c2, _ = req("/admin/stats", host="127.0.0.1")
        c3, _ = req("/stats")
        c4, _ = req("/admin/stats", host="guide.ssouq.com")
        check("المدير وحده: الواجهة 401 والصفحة إلى الدخول، ولا شيء منها على الموقع العام", code == 401 and c2 == 302 and c3 == 404 and c4 == 404,
              (code, c2, c3, c4))
        code, page = req("/stats", host="admin.ssouq.com", auth=True, raw=True)
        check("وعلى نطاق الأداة من الجذر", code == 200 and "إحصائيات الدليل".encode() in page)

        code, st = req("/admin/api/analytics/settings", host="127.0.0.1", auth=True)
        key = st["indexnow"]["key"]
        code, body = req(f"/{key}.txt", raw=True)
        c2, _ = req("/" + "a" * 32 + ".txt", raw=True)
        check("ملف مفتاح IndexNow على الموقع العام، وغيره 404", code == 200 and body.decode() == key and c2 == 404)
        check("وصفحات الموقع للإرسال كخريطته", "/" in st["pages"] and "/samsung-lg" in st["pages"] and "/predict" in st["pages"])
        code, sm = req("/sitemap.xml", raw=True)
        check("وخريطة الموقع كما كانت", code == 200 and b"<loc>https://guide.ssouq.com/samsung-lg</loc>" in sm
              and b"<loc>https://guide.ssouq.com/predict</loc>" in sm and b"/standings/" in sm)

        code, d = req("/admin/api/analytics/tags", host="127.0.0.1", method="POST", body={"ga": "G-TEST12345", "bing": "bad"}, auth=True)
        check("معرّفٌ خاطئ: 400 باسمه ولا يُحفظ شيء", code == 400 and "Bing" in d["error"] and b"G-TEST12345" not in req("/", raw=True)[1])
        code, d = req("/admin/api/analytics/tags", host="127.0.0.1", method="POST", body={"ga": "G-TEST12345"}, auth=True)
        check("وبعد الحفظ وسم GA4 في صفحات الدليل وحدها", code == 200 and b"gtag/js?id=G-TEST12345" in req("/", raw=True)[1]
              and b"G-TEST12345" not in req("/admin/login", host="127.0.0.1", raw=True)[1])

        code, d = req("/admin/api/analytics/google", host="127.0.0.1", method="POST", body={"key": "not json"}, auth=True)
        c2, d2 = req("/admin/api/analytics/google", host="127.0.0.1", method="POST", body={"key": json.dumps({"type": "user"})}, auth=True)
        check("ملف المفتاح: غير JSON وغير حساب خدمة يُرفضان بسببهما", code == 400 and "JSON" in d["error"] and c2 == 400
              and "service account" in d2["error"])
        code, d = req("/admin/api/analytics/google-check", host="127.0.0.1", method="POST", body={}, auth=True)
        check("و«اختبر الربط» قبل المفتاح يطلبه", code == 400)
        sa = M.service_account(pem)
        code, d = req("/admin/api/analytics/google", host="127.0.0.1", method="POST", body={"key": json.dumps(sa)}, auth=True)
        disk = open(os.path.join(data, "analytics", "settings.json"), encoding="utf-8").read()
        code2, st = req("/admin/api/analytics/settings", host="127.0.0.1", auth=True)
        check("المفتاح يُحفظ مشفَّرًا ولا يعود للمتصفح", code == 200 and d["google"]["email"] == sa["client_email"]
              and "PRIVATE KEY" not in disk and "enc:1:" in disk and st["google"]["has_key"] and "PRIVATE" not in json.dumps(st))
        code, c = req("/admin/api/analytics/google-check", host="127.0.0.1", method="POST", body={}, auth=True)
        check("«اختبر الربط»: الخاصية والموقعان", code == 200 and c["ok"] and c["properties"][0]["id"] == "424242" and len(c["sites"]) == 2)
        code, r = req("/admin/api/analytics/google?days=7", host="127.0.0.1", auth=True)
        check("وقبل اختيارهما: الربط قائم بلا تقارير", code == 200 and r["connected"] and r["ok"] and r["ga"] is None and r["gsc"] is None)
        code, d = req("/admin/api/analytics/google", host="127.0.0.1", method="POST", body={"ga": "properties/424242", "site": "https://guide.ssouq.com/"}, auth=True)
        check("الخاصية تُفهم بصيغة properties/…، والمفتاح باقٍ", code == 200 and d["google"]["ga"] == "424242" and d["google"]["has_key"])
        code, d = req("/admin/api/analytics/google", host="127.0.0.1", method="POST", body={"site": "guide.ssouq.com"}, auth=True)
        check("وموقعٌ بصيغةٍ خاطئة يُرفض", code == 400 and "sc-domain" in d["error"])
        code, r = req("/admin/api/analytics/google?days=7", host="127.0.0.1", auth=True)
        check("تقرير جوجل للصفحة: GA4 وSearch Console", code == 200 and r["ga"]["totals"]["users"] == 728 and r["gsc"]["totals"]["clicks"] in (80, 120))
        code, d = req("/admin/api/analytics/sitemaps", host="127.0.0.1", method="POST", body={}, auth=True)
        state = json.load(urllib.request.urlopen(g + "/_test/state"))
        check("وإرسال خريطتي الموقع", code == 200 and d["ok"] and state["sitemaps"] == ["https://guide.ssouq.com/sitemap.xml",
                                                                                       "https://guide.ssouq.com/store-sitemap.xml"])
        code, d = req("/admin/api/analytics/indexnow", host="127.0.0.1", method="POST", body={"submit": True}, auth=True)
        state = json.load(urllib.request.urlopen(g + "/_test/state"))
        sent = [x for x in state["indexnow"] if len(x["urlList"]) == d["result"]["n"]][-1]
        check("IndexNow: كل صفحات الموقع الآن (فيبدأ اليومي)", code == 200 and d["ok"] and d["result"]["kind"] == "manual"
              and "https://guide.ssouq.com/samsung-lg" in sent["urlList"] and sent["key"] == key and d["indexnow"]["last"]["ok"]
              and d["indexnow"]["confirmed"])
        code, d = req("/admin/api/analytics/indexnow", host="127.0.0.1", method="POST", body={"auto": False}, auth=True)
        check("وإيقاف الإرسال اليومي", code == 200 and d["indexnow"]["auto"] is False)
        code, d = req("/admin/api/analytics/google", host="127.0.0.1", method="POST", body={"remove": True}, auth=True)
        code2, r = req("/admin/api/analytics/google", host="127.0.0.1", auth=True)
        check("وإزالة ربط جوجل", code == 200 and not d["google"]["has_key"] and r == {"ok": False, "connected": False})

        req("/api/hit", method="POST", body=pv("/mac"), headers=dict(hh, **{"X-Forwarded-For": "6.6.6.6"}))   # قد يُكتب فورًا…
        req("/api/hit", method="POST", body=pv("/windows"), headers=dict(hh, **{"X-Forwarded-For": "7.7.7.7"}))  # …وهذا لا (بعده بلحظة)
        app.terminate()
        app.wait(timeout=10)
        today = datetime.datetime.now(A.RIYADH).strftime("%Y-%m-%d")
        f = json.load(open(day_file(data, today))) if os.path.exists(day_file(data, today)) else {}
        check("وأعداد اليوم تُكتب حين يُطفأ الخادم (SIGTERM)", f.get("pv") == 3 and f.get("pages", {}).get("/windows") == 1, f.get("pages"))
    finally:
        if app.poll() is None:
            app.terminate()
            app.wait(timeout=10)
        mock.terminate()
        mock.wait(timeout=10)
        shutil.rmtree(data, ignore_errors=True)


def main():
    unit_classify()
    unit_hits()
    unit_tags()
    unit_google_form()
    pem, pub = M.make_key(1024, seed=7)
    srv, base = start_mock(pub)
    try:
        unit_indexnow(base)
        unit_google(base, pem, pub)
    finally:
        srv.shutdown()
    live(pem, pub)
    print(f"\nResult: {_p} passed, {_f} failed")
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

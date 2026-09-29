#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""أعداد المحتوى في منتجات المتجر (store_sync.py) بلا إنترنت — واجهة سلة وهمية (tests/mock_salla_api.py) ووصف منتجات
المتجر الحقيقي (tests/store_products.json: كاسبر وفالكون وسمارت كما كانت في سلة):

  - النص: التقريبي («6,100+» «+6100» «أكثر من» وما عُطف عليه) دون العدد، والدقيق زوجًا بمعدوده، وتاريخ «آخر تحديث»
    باليوم والهجري (أم القرى)، وما سوى ذلك حرفًا بحرف: الدقيق المنفرد والهدف («حتى تصل إلى 20,000») وما في وسوم HTML،
    والإعادة لا تغيّر شيئًا، والبعيد (خارج 70%–200%) معلَّم.
  - الربط: الرمز يصل بويبهوك التطبيق (موقَّعًا) ويُجدَّد قبل انتهائه برمز تجديدٍ يُستعمل مرة، وبعد 401، وفشله يُنبَّه
    به مرة؛ والأسرار مشفّرة لا تظهر في الملف ولا في حال الصفحة؛ وتوكن الخدمة احتياطًا.
  - المنتجات: الاقتراح من الاسم وبادئة الرمز، والمعاينة لا تكتب، وأول تحديثٍ بيد المدير ثم وحده بعد كل سحب، والكتابة
    جزئية (الوصف ووصف محركات البحث وحدهما)، والبعيد يُعلَّق ويُنبَّه مرة ويُكتب بموافقة، وتغيّر ما لم يُطلب يوقف التلقائي.
  - على خادمٍ حيّ: المسارات للمدير وحده، والويبهوك يرفض غير الموقَّع، ورفع ملف ثم ربط منتج وتحديثه.

تشغيل:  python tests/test_store_sync.py
"""
import base64
import datetime
import hashlib
import hmac
import io
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
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import content as C  # noqa: E402
import store_sync as S  # noqa: E402
import mock_salla_api as M  # noqa: E402

_p = _f = 0


def check(l, c, x=""):
    global _p, _f
    print((f"  \033[32mPASS\033[0m  {l}" if c else f"  \033[31mFAIL\033[0m  {l}") + (f"  ({x})" if x else ""))
    _p += 1 if c else 0
    _f += 0 if c else 1


FIX = json.load(open(os.path.join(HERE, "store_products.json"), encoding="utf-8"))
CASPER, FALCON, SMART = FIX["1557813796"], FIX["153695876"], FIX["889146346"]
# أعداد صفحة المحتوى يوم أُخذ الوصف (29 سبتمبر 2026)
COUNTS = {"casper": {"movies": 6045, "series": 1330, "channels": 4693, "episodes": 28592, "seasons": 1674},
          "falcon": {"movies": 17562, "series": 14302, "channels": 13322, "episodes": 237763, "seasons": 14390},
          "smart": {"movies": 20453, "series": 9874, "channels": 8942, "episodes": 317192, "seasons": 14583}}
WHEN = datetime.datetime(2026, 10, 3, 6, 43, tzinfo=datetime.timezone.utc).timestamp()   # السبت 3 أكتوبر 9:43 بتوقيت السعودية
_NUMS = re.compile(r"[0-9٠-٩][0-9٠-٩,٬]*")
_WORDS = re.compile("|".join(sorted(list(S._GM) + list(S._HM) + list(C._DAYS) + ["الأحد", "الاحد"], key=len, reverse=True)))


def skeleton(s):
    """الوصف بلا أعدادٍ ولا أسماء أيامٍ وأشهر — ما يجب ألا يتغيّر أبدًا."""
    return _WORDS.sub("@", _NUMS.sub("#", s))


def pairs(ch):
    return [(x["what"], x["mode"], x["old"], x["new"]) for x in ch]


def unit_engine():
    print("النص: ما يُعرف في الوصف ويُبدَّل")
    new, ch = S.plan(CASPER["description"], COUNTS["casper"], WHEN)
    got = pairs(ch)
    want = [("movies", "approx", "6,100+ فيلم", "6,000+ فيلم"),
            ("series", "approx", "1,700+ مسلسل", "1,300+ مسلسل"),
            ("date", "date", "الثلاثاء 29 سبتمبر 2026", "السبت 3 أكتوبر 2026"),
            ("date", "date", "الثلاثاء 29 سبتمبر 2026م (18 ربيع الآخر 1448هـ)", "السبت 3 أكتوبر 2026م (22 ربيع الآخر 1448هـ)"),
            ("movies", "exact", "6,184 فيلمًا", "6,045 فيلمًا"),
            ("series", "exact", "1,788 مسلسلًا", "1,330 مسلسلًا"),
            ("total", "approx", "أكثر من 7,900 فيلم ومسلسل", "أكثر من 7,300 فيلم ومسلسل"),
            ("movies", "approx", "أكثر من 6,100 فيلم", "أكثر من 6,000 فيلم"),
            ("series", "approx", "أكثر من 1,700 مسلسل", "أكثر من 1,300 مسلسل"),
            ("date", "date", "29 سبتمبر 2026", "3 أكتوبر 2026")]
    check("كاسبر: كل موضعٍ معروف (التقريبي والزوج والتواريخ الثلاثة)", sorted(got) == sorted(want + [want[4], want[5]]),
          [g for g in got if g not in want])
    check("ولا بعيد فيها (أعداد صفحة المحتوى قريبةٌ مما في الوصف)", not any(x["far"] for x in ch))
    check("وما سوى الأعداد والتواريخ حرفًا بحرف", skeleton(new) == skeleton(CASPER["description"]))
    check("والإعادة بالأعداد نفسها لا تغيّر شيئًا", S.plan(new, COUNTS["casper"], WHEN) == (new, []))
    for lone in ("<strong>2,647 فيلمًا</strong> جديدًا", "<strong>418 فيلمًا</strong>", "<strong>311 مسلسلًا</strong> جديدًا",
                 "<strong>119 مسلسلًا تركيًا</strong>", "حتى تصل المكتبة إلى 20,000 فيلم ومسلسل",
                 "الجديد منذ تحديث 27 سبتمبر", 'alt="آخر تحديث لأفلام كاسبر 29 سبتمبر 2026 - 6184 فيلم"'):
        check(f"لا يُمسّ: {lone[:48]}", lone in CASPER["description"] and lone in new)

    seo, ch = S.plan(CASPER["metadata"]["description"], COUNTS["casper"], WHEN)
    check("وصف محركات البحث: ‏«+6100 فيلم و+1700 مسلسل» بلا فاصلةٍ كما كُتب", "+6000 فيلم و+1300 مسلسل" in seo
          and [x["mode"] for x in ch] == ["approx", "approx"], seo)

    new, ch = S.plan(FALCON["description"], COUNTS["falcon"], WHEN)
    check("فالكون: «19,000+» و«8,700+» في خاناتها (بين الأسطر)", ("movies", "approx", "19,000+ فيلم", "17,000+ فيلم") in pairs(ch)
          and ("series", "approx", "8,700+ مسلسل", "14,000+ مسلسل") in pairs(ch))
    check("و«أكثر من 10,000 قناة» (القنوات)", ("channels", "approx", "أكثر من 10,000 قناة", "أكثر من 13,000 قناة") in pairs(ch))
    check("و«أكثر من 19,000 فيلم و8,700 مسلسل»: المعطوف تقريبيٌّ كذلك",
          ("movies", "approx", "أكثر من 19,000 فيلم", "أكثر من 17,000 فيلم") in pairs(ch)
          and ("series", "approx", "8,700 مسلسل", "14,000 مسلسل") in pairs(ch))
    check("وalt الصور كما هو («أكثر من 19,000 فيلم» لقطةٌ من يومها)", 'alt="مكتبة الأفلام في تطبيق فالكون أكثر من 19,000 فيلم"' in new)
    check("وكود التحميل «1683248» لا يُمسّ", "هذا الكود: 1683248." in new)
    check("وما سواها حرفًا بحرف", skeleton(new) == skeleton(FALCON["description"]))
    seo, ch = S.plan(FALCON["metadata"]["description"], COUNTS["falcon"], WHEN)
    check("ووصف محركات البحث: ثلاثةٌ معطوفة", "أكثر من 13,000 قناة و17,000 فيلم و14,000 مسلسل" in seo, seo)

    new, ch = S.plan(SMART["description"], COUNTS["smart"], WHEN)
    check("سمارت: «20,000+ فيلم» باقٍ (20,453) و«10,000+ مسلسل» ← «9,800+»",
          pairs(ch) == [("series", "approx", "10,000+ مسلسل", "9,800+ مسلسل"),
                        ("series", "approx", "أكثر من 10,000 مسلسل", "أكثر من 9,800 مسلسل")], pairs(ch))

    # المعدود بحسب العدد، والصفة بعده تمنع تغييره
    text = "بلغت المكتبة 6,184 فيلمًا و1,788 مسلسلًا، وفيها 2,000 فيلم جديد."
    for n, noun in ((6203, "أفلام"), (6200, "فيلم"), (6211, "فيلمًا"), (6250, "فيلمًا"), (99, "فيلمًا"), (5, "أفلام")):
        out = S.plan(text, {"movies": n, "series": 1788}, None)[0]
        check(f"المعدود: {n:,} {noun}", f"{n:,} {noun} و1,788 مسلسلًا،" in out, out)
    out = S.plan("فيها 6,184 فيلمًا و1,788 مسلسلًا جديدًا.", {"movies": 6203, "series": 1803}, None)[0]
    check("وصفةٌ بعد المعدود («مسلسلًا جديدًا») تبقيه كما هو ويتغيّر العدد وحده، وقبل العطف يتغيّر",
          out == "فيها 6,203 أفلام و1,803 مسلسلًا جديدًا.", out)
    src = "فيها 6,184 فيلمًا جديدًا و1,788 مسلسلًا."
    check("وما بين العددين غير العطف ليس زوجًا — لا يُمسّ", S.plan(src, {"movies": 6203, "series": 1803}, None)[0] == src)

    out = S.plan("6,000+ فيلم · أكثر من 6,000 فيلم", {"movies": 6000}, None)[0]
    check("«+» يعني العدد فما فوقه، و«أكثر من» ما دونه حقًّا", out == "6,000+ فيلم · أكثر من 5,900 فيلم", out)
    check("والتقريب: عشراتٌ تحت الألف، ومئاتٌ تحت العشرة آلاف، وآلافٌ فوقها",
          (S.approx(987, False), S.approx(6045, False), S.approx(17562, False)) == (980, 6000, 17000))
    out = S.plan("أكثر من ٦٬١٠٠ فيلم و+٦١٠٠ مسلسل", {"movies": 6245, "series": 6245}, None)[0]
    check("الأرقام الهندية وفاصلتها كما كُتبت", out == "أكثر من ٦٬٢٠٠ فيلم و+٦٢٠٠ مسلسل", out)
    out = S.plan("أكثر من 900 قناة و120 حلقة و30 موسمًا", {"channels": 4693, "episodes": 125, "seasons": 31}, None)
    check("القناة والحلقة والموسم", out[0] == "أكثر من 4,600 قناة و120 حلقة و30 موسمًا"
          and [x["far"] for x in out[1]] == [True], pairs(out[1]))
    _, ch = S.plan("<p>6,184 فيلمًا و1,788 مسلسلًا</p>", {"movies": 2000, "series": 5000}, None)
    check("البعيد: أقل من 70% أو فوق الضعف معلَّم", [x["far"] for x in ch] == [True, True])
    _, ch = S.plan("<p>6,184 فيلمًا و1,788 مسلسلًا</p>", {"movies": 4400, "series": 3500}, None)
    check("والقريب (71% و196%) لا", [x["far"] for x in ch] == [False, False])
    check("عددٌ ليس بعده معدود لا يُمسّ", S.plan("باقة 12 شهرًا و3 أشهر هدية، 4K", COUNTS["casper"], WHEN)[1] == [])
    check("وسيرفرٌ بلا عددٍ لنوعٍ (بلا حلقات) لا يكتب صفرًا", S.plan("أكثر من 120 حلقة", {"movies": 5}, None)[1] == [])
    check("والوصف الفارغ", S.plan("", COUNTS["casper"], WHEN) == ("", []) and S.plan(None, COUNTS["casper"], WHEN) == ("", []))

    # التاريخ
    cases = [("آخر تحديث: 29 سبتمبر 2026", "آخر تحديث: 3 أكتوبر 2026"),
             ("آخر تحديث الثلاثاء، 29 سبتمبر 2026م", "آخر تحديث السبت، 3 أكتوبر 2026م"),
             ("اخر تحديث ٢٩ سبتمبر ٢٠٢٦ (١٨ ربيع الثاني ١٤٤٨ هـ)", "اخر تحديث ٣ أكتوبر ٢٠٢٦ (٢٢ ربيع الثاني ١٤٤٨ هـ)"),
             ("منذ تحديث 29 سبتمبر 2026", "منذ تحديث 29 سبتمبر 2026"),
             ("آخر تحديث للمكتبة. صدر في 29 سبتمبر 2026", "آخر تحديث للمكتبة. صدر في 29 سبتمبر 2026"),
             ("<h3>آخر تحديث</h3><p>29 سبتمبر 2026</p>", "<h3>آخر تحديث</h3><p>29 سبتمبر 2026</p>")]
    for src, want in cases:
        out = S.plan(src, COUNTS["casper"], WHEN)[0]
        check(f"التاريخ: {src[:40]}", out == want, out)
    far_day = datetime.datetime(2049, 1, 5, 9, tzinfo=datetime.timezone.utc).timestamp()
    src = "آخر تحديث 29 سبتمبر 2026م (18 ربيع الآخر 1448هـ)"
    check("وبعد جدول أم القرى (2048) يبقى التاريخ كله — لا ميلاديٌّ جديد بهجريٍّ قديم",
          S.plan(src, {}, far_day)[0] == src and S.plan("آخر تحديث 29 سبتمبر 2026", {}, far_day)[0] == "آخر تحديث 5 يناير 2049")
    for g, h in (((2024, 7, 7), (1446, 1, 1)), ((2025, 3, 1), (1446, 9, 1)), ((2026, 2, 18), (1447, 9, 1)),
                 ((2026, 9, 29), (1448, 4, 18)), ((2030, 6, 15), (1452, 2, 14)), ((2048, 10, 8), (1470, 12, 29))):
        check(f"أم القرى: {g} ← {h}", S.hijri(datetime.date(*g)) == h)
    check("وخارج الجدول: None", S.hijri(datetime.date(2024, 7, 6)) is None and S.hijri(datetime.date(2048, 10, 9)) is None)


# ================= الربط والمنتجات =================
def m3u(movies, series=30, channels=45):
    h, c = "http://panel.example:8080", "u/p"
    out, n = ["#EXTM3U"], 1
    for i in range(movies):
        out += [f'#EXTINF:-1 tvg-name="Film {i}" group-title="VOD",Film {i:04d} (2020)', f"{h}/movie/{c}/{n}.mkv"]
        n += 1
    for i in range(series):
        for e in (1, 2):
            out += [f'#EXTINF:-1 group-title="Series",Show {i:03d} S01 E0{e}', f"{h}/series/{c}/{n}.mkv"]
            n += 1
    for i in range(channels):
        out += [f'#EXTINF:-1 group-title="Live",Channel {i:03d}', f"{h}/live/{c}/{n}.ts"]
        n += 1
    return ("\n".join(out) + "\n").encode()


def ingest(d, key, movies, series=30):
    C.ingest(d, key, io.BytesIO(m3u(movies, series)).read, "file", key + ".m3u")


DESC = ("<p>مكتبة كاسبر: <strong>600+</strong></p><p class=\"ql-align-center\">فيلم مترجم</p>"
        "<h3>آخر تحديث للمكتبة — الثلاثاء 1 سبتمبر 2026</h3>"
        "<p>وصلت إلى <strong>640 فيلمًا</strong> و<strong>28 مسلسلًا</strong>، وقسم 2026 وحده فيه <strong>40 فيلمًا</strong>.</p>")
SEO = "اشتراك كاسبر: +600 فيلم و+20 مسلسل بتحديث يومي"


def signed(secret, obj):
    raw = json.dumps(obj).encode()
    return raw, {"X-Salla-Signature": hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()}


class _H(dict):
    def get(self, k, d=None):
        return next((v for kk, v in self.items() if kk.lower() == k.lower()), d)


def unit_flow():
    print("الربط والمنتجات (سلة وهمية)")
    d = tempfile.mkdtemp(prefix="store_")
    C._cache.clear()
    C._sums.clear()
    C._busy.clear()
    srv = M.serve(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    ms = srv.store
    S.API = S.ACCOUNTS = "http://127.0.0.1:%d" % srv.server_address[1]
    sent = []
    S.notifier = lambda subject, body: sent.append((subject, body)) or {"mail": {"ok": True}}
    S.fallback_token = None
    try:
        ms.add(1557813796, "اشتراك كاسبر IPTV لمدة 6 أشهر", DESC, SEO)
        ms.add(153695876, "اشتراك فالكون IPTV لمدة 3 أشهر | FALCON TV PRO", "", "", sku="FAL-PRO-03M")
        ms.add(889146346, "اشتراك IPTV لمدة 3 أشهر | جميع الأجهزة", "", "", sku="MRH-03M")
        ms.add(1646070905, "لوحة تحكم IPTV بأسعار الجملة للموزعين", "", "", status="hidden", type_="service")
        ms.add(1701747243, "كاسبر محذوف", "", "", status="deleted")
        ingest(d, "casper", 650)

        r = S.preview(d)
        check("بلا ربط: المعاينة تقول إن المتجر غير مربوط", not r["ok"] and "غير مربوط" in r["error"], r)
        st = S.state(d)
        check("والحال: غير جاهز، بلا رمز", not st["ready"] and not st["auth"]["own"] and st["hook_url"].endswith("/salla/webhook"))

        S.fallback_token = lambda: "tok-1"
        check("توكن الخدمة احتياطًا", S.check(d) == {"ok": True, "total": 5} and S.state(d)["auth"]["fallback"], S.check(d))
        S.fallback_token = None

        S.save_auth(d, {"client_id": "cid-1", "secret": "csecret-1", "hook": "hooksecret"})
        st = S.state(d)["auth"]
        check("حُفظ التطبيق (معرّفه وسرّاه) ولا رمز بعد", st["client_id"] == "cid-1" and st["secret"] and st["hook"] and not st["own"])
        payload = {"event": "app.store.authorize", "merchant": 831097886, "created_at": "2026-09-29 12:00:00",
                   "data": {"access_token": "tok-1", "refresh_token": "ref-1", "expires": int(time.time()) + 14 * 86400,
                            "scope": "products.read_write offline_access", "token_type": "bearer"}}
        raw, hdr = signed("hooksecret", payload)
        check("الويبهوك: حدث التطبيق يُعرف", S.app_event(raw) == "app.store.authorize"
              and S.app_event(b'{"event":"order.created"}') == "" and S.app_event(b"junk") == "")
        check("وتوقيعه بسرّ الويبهوك يُقبل، وغيره لا", S.verify(d, raw, _H(hdr))
              and not S.verify(d, raw, _H({"X-Salla-Signature": "00" * 32}))
              and S.verify(d, raw, _H({"Authorization": "Bearer hooksecret"})))
        S.on_app_event(d, payload)
        st = S.state(d)["auth"]
        check("وصل الرمز: مربوطٌ ويتجدّد وحده", st["own"] and st["renews"] and st["source"] == "webhook"
              and st["merchant"] == "831097886" and "products.read_write" in st["scope"], st)
        disk = open(os.path.join(d, "content", "_store.json"), encoding="utf-8").read()
        check("والأسرار مشفّرة على القرص", not any(x in disk for x in ("tok-1", "ref-1", "csecret-1", "hooksecret"))
              and "enc:1:" in disk)
        view = json.dumps(S.state(d), ensure_ascii=False)
        check("ولا تصل حال الصفحة", not any(x in view for x in ("tok-1", "ref-1", "csecret-1", "hooksecret", "enc:1:")))

        cat = S.catalog(d)
        sug = {p["id"]: p["suggest"] for p in cat["products"]}
        check("المقترحة: كاسبر بالاسم، وفالكون بالاسم وبادئة FAL، وسمارت ببادئة MRH",
              sug.get("1557813796") == "casper" and sug.get("153695876") == "falcon" and sug.get("889146346") == "smart", sug)
        check("والمحذوف لا يُعرض", "1701747243" not in sug)
        cat = S.catalog(d, "لوحة")
        check("والبحث بالاسم، وبلا اقتراحٍ لما لا يطابق سيرفرًا", [(p["id"], p["suggest"]) for p in cat["products"]]
              == [("1646070905", "")], cat)

        try:
            S.save(d, {"links": [{"id": "1557813796", "server": "nope"}]})
            check("سيرفرٌ غير معروف يُرفض", False)
        except ValueError:
            check("سيرفرٌ غير معروف يُرفض", True)
        S.save(d, {"on": True, "links": [{"id": "1557813796", "server": "casper", "name": "كاسبر 6"}, {"id": "x", "server": "casper"}]})
        st = S.state(d)
        check("الربط: المنتج وسيرفره (ومعرّفٌ ليس رقمًا يسقط)", [(l["id"], l["server"], l["approved"]) for l in st["links"]]
              == [("1557813796", "casper", False)] and st["on"])

        check("قبل الاعتماد: الدورة لا تكتب شيئًا", S.tick(d) is None and ms.puts == [])
        pv = S.preview(d)
        p0 = pv["products"][0]
        check("المعاينة تقرأ ولا تكتب", pv["ok"] and p0["changes"] and ms.puts == [])
        want = {("movies", "600+ فيلم", "650+ فيلم"), ("movies", "640 فيلمًا", "650 فيلمًا"), ("series", "28 مسلسلًا", "30 مسلسلًا")}
        check("وفيها الأعداد والتاريخ ووصف محركات البحث", want <= {(x["what"], x["old"], x["new"]) for x in p0["changes"]}
              and any(x["what"] == "date" for x in p0["changes"]) and any(x.get("seo") for x in p0["changes"]),
              [(x["what"], x["old"], x["new"]) for x in p0["changes"]])

        r = S.run(d, manual=True)
        body = ms.puts[-1][1] if ms.puts else {}
        check("«حدّث الآن»: كتابةٌ واحدة بالوصف ووصف محركات البحث وحدهما", r["ok"] and r["n"] == 1 and len(ms.puts) == 1
              and set(body) == {"description", "metadata_description"}, (r, list(body)))
        prod = ms.products["1557813796"]
        check("والوصف في سلة: 650+ و«650 فيلمًا و30 مسلسلًا»، و«40 فيلمًا» كما هو",
              "<strong>650+</strong>" in prod["description"] and "650 فيلمًا</strong> و<strong>30 مسلسلًا" in prod["description"]
              and "<strong>40 فيلمًا</strong>" in prod["description"], prod["description"])
        check("ووصف محركات البحث", prod["metadata"]["description"] == "اشتراك كاسبر: +650 فيلم و+30 مسلسل بتحديث يومي",
              prod["metadata"]["description"])
        st = S.state(d)["links"][0]
        check("والمنتج معتمَد ومطابقٌ لآخر سحب", st["approved"] and st["fresh"] and st["put_at"] and st["changes"])
        check("وتحديثٌ ثانٍ بلا تغيير لا يكتب", S.run(d, manual=True)["n"] == 0 and len(ms.puts) == 1)

        time.sleep(1.1)                      # وقت السحب بالثانية: سحبٌ جديد بوقتٍ جديد
        ingest(d, "casper", 700)
        r = S.tick(d)
        check("سحبٌ جديد: الدورة تكتب وحدها", r and r["n"] == 1 and len(ms.puts) == 2
              and "<strong>700+</strong>" in ms.products["1557813796"]["description"], r)
        check("ولا تعيد ما كتبته", S.tick(d) is None and len(ms.puts) == 2)

        time.sleep(1.1)
        ingest(d, "casper", 150)             # ملفٌّ ناقص: 150 فيلمًا بعد 700
        r = S.tick(d)
        st = S.state(d)["links"][0]
        check("عددٌ بعيد (150 بعد 700): يُعلَّق المنتج كله ولا يُكتب", r and r["n"] == 0 and len(ms.puts) == 2
              and st["held"] and not st["fresh"], (r, st["held"]))
        check("ويُنبَّه المدير", len(sent) == 1 and "علّقتُه" in sent[0][1] and "700" in sent[0][1], sent)
        check("ولا يُعاد ولا يُنبَّه ثانيةً على المحتوى نفسه", S.tick(d) is None and len(sent) == 1 and len(ms.puts) == 2)
        time.sleep(1.1)
        ingest(d, "casper", 140)             # سحبٌ آخر وما زال بعيدًا
        r = S.tick(d)
        check("وسحبٌ آخر ما زال بعيدًا: يبقى معلَّقًا ولا يُنبَّه ثانيةً بالحال نفسها", r and r["n"] == 0 and len(sent) == 1
              and len(ms.puts) == 2, len(sent))
        time.sleep(1.1)
        ingest(d, "casper", 150)
        r = S.run(d, manual=True)
        check("و«حدّث الآن» وحده يعلّقه كذلك", r["n"] == 0 and len(ms.puts) == 2 and r["results"]["1557813796"]["held"])
        r = S.run(d, manual=True, force=True)
        check("ومع «ومعه ما فيه فرقٌ كبير» يُكتب", r["n"] == 1 and len(ms.puts) == 3
              and "<strong>150+</strong>" in ms.products["1557813796"]["description"], r)
        check("ويزول التعليق", not S.state(d)["links"][0]["held"])
        time.sleep(1.1)
        ingest(d, "casper", 700)             # بعيدٌ من جديد بعد أن زال التعليق
        S.tick(d)
        check("وتعليقٌ جديد بعد أن زال يُنبَّه به", len(sent) == 2 and len(ms.puts) == 3, len(sent))
        S.run(d, manual=True, force=True)
        check("(ويُكتب بموافقة)", len(ms.puts) == 4 and "<strong>700+</strong>" in ms.products["1557813796"]["description"])
        time.sleep(1.1)
        ingest(d, "casper", 150)
        S.run(d, manual=True, force=True)

        # الرمز يُجدَّد قبل انتهائه، ورمز التجديد يُستعمل مرة
        S._change(d, lambda s: s["auth"].update(expires=time.time() + 86400))
        S.tick(d)
        a = S._load(d)["auth"]
        check("الرمز قبل انتهائه بيومٍ: يُجدَّد في الدورة (ولو لم يجدّ محتوى)", ms.renewals == 1
              and S._dec(d, a["token"]) == "tok-2" and S._dec(d, a["refresh"]) == "ref-2"
              and a["expires"] > time.time() + 13 * 86400 and a["renewed"], (ms.renewals, a.get("error")))
        check("ورمز التجديد القديم لم يعد يُقبل في سلة", "ref-1" not in ms.refresh and "ref-2" in ms.refresh)
        S.tick(d)
        check("ولا يُجدَّد ثانيةً قبل موعده", ms.renewals == 1)

        ms.tokens.discard("tok-2")            # أُلغي الرمز قبل موعده
        time.sleep(1.1)
        ingest(d, "casper", 160)
        r = S.run(d, manual=True)
        check("401: يُجدَّد الرمز مرةً ويُعاد", r["ok"] and r["n"] == 1 and ms.renewals == 2
              and S._dec(d, S._load(d)["auth"]["token"]) == "tok-3", r)
        ms.sell = True                        # كودٌ بيع في لحظة الكتابة
        time.sleep(1.1)
        ingest(d, "casper", 165)
        r = S.run(d, manual=True)
        check("كودٌ بيع في لحظة الكتابة (الكمية والحال) ليس تغيّرًا غير مطلوب", r["ok"] and r["n"] == 1 and S.state(d)["on"], r)
        ms.sell = False

        ms.refresh.clear()
        S._change(d, lambda s: s["auth"].update(expires=time.time() - 60))
        n = len(sent)
        time.sleep(1.1)
        ingest(d, "casper", 168)             # ومحتوى جديد ينتظر الكتابة: السبب واحد، فتنبيهٌ واحد
        S.tick(d)
        a = S.state(d)["auth"]
        check("رمز تجديدٍ مرفوض ورمزٌ منتهٍ: يُحفظ السبب ويُنبَّه المدير مرةً واحدة (لا سطرٌ لكل منتج)", a["error"]
              and len(sent) == n + 1 and "رمز سلة" in sent[-1][0], (a["error"], [x[0] for x in sent[n:]]))
        posts = ms.renewals
        S.tick(d)
        check("ولا يُنبَّه ثانيةً بالسبب نفسه", len(sent) == n + 1)
        a = S._load(d)["auth"]
        check("ورمز التجديد المرفوض يُترك فلا يُعاد به إلى سلة (إعادته إساءةٌ قد تُلغي الربط)", not a.get("refresh")
              and not S._renewable(d) and not S.state(d)["auth"]["renews"], a.get("error"))
        r = S.run(d, manual=True)
        check("والتحديث يقول السبب", not r["ok"] and "رمز" in r["results"]["1557813796"]["error"], r)

        S.save_auth(d, {"token": "tok-1"})    # رمزٌ يُلصق
        a = S.state(d)["auth"]
        check("رمزٌ ملصوق وحده: مربوطٌ بلا تجديد", a["own"] and a["source"] == "paste" and not a["renews"] and not a["refresh"])
        ms.scope403 = True
        time.sleep(1.1)
        ingest(d, "casper", 170)
        r = S.run(d, manual=True)
        check("403: السبب صلاحية المنتجات", not r["ok"] and "صلاحية" in r["results"]["1557813796"]["error"], r)
        ms.scope403 = False
        ms.drift = True
        r = S.run(d, manual=True)
        st = S.state(d)
        check("تغيّر في المنتج ما لم يُطلب (نوعه): يُقال، ويتوقّف التحديث التلقائي",
              not r["ok"] and "نوع المنتج" in r["results"]["1557813796"]["error"] and not st["on"], r)
        ms.drift = False

        S.save_auth(d, {"token": "tok-1", "refresh": "ref-9", "client_id": "cid-1", "secret": "csecret-1"})
        S._change(d, lambda s: s["auth"].update(expires=time.time() + 3600))
        S.ACCOUNTS, real = "http://127.0.0.1:9", S.ACCOUNTS    # سلة لا تُجيب
        try:
            S.tick(d)
            a = S._load(d)["auth"]
            first = a.get("renew_fail")
            S.tick(d)
            check("تعذّر الوصول إلى سلة للتجديد: يُحفظ السبب ولا يُعاد قبل ساعة (ورمز التجديد باقٍ)",
                  first and S._load(d)["auth"].get("renew_fail") == first and a.get("refresh") and "لم يُجدَّد" in a["error"],
                  a.get("error"))
        finally:
            S.ACCOUNTS = real
        S.save(d, {"on": True, "links": [{"id": "1557813796", "server": "smart"}]})
        check("منتجٌ تغيّر سيرفره يبدأ من جديد: أول تحديثٍ بيد المدير", not S.state(d)["links"][0]["approved"])
        S.on_app_event(d, {"event": "app.uninstalled", "data": {}})
        a = S.state(d)["auth"]
        check("app.uninstalled يفصل الرمز ويقول السبب", not a["own"] and "أُزيل" in a["error"])
        S.save_auth(d, {"clear": True})
        check("و«افصل» يمحو الربط كله", S.state(d)["auth"] == dict(S.state(d)["auth"], own=False, client_id="", secret=False, hook=False))
        try:
            S.save_auth(d, {"client_id": "bad id!"})
            check("معرّف تطبيقٍ غير صالح يُرفض", False)
        except ValueError:
            check("معرّف تطبيقٍ غير صالح يُرفض", True)
    finally:
        srv.shutdown()
        S.notifier = S.fallback_token = None
        shutil.rmtree(d, ignore_errors=True)


# ================= على خادمٍ حيّ =================
AUTH = "Basic " + base64.b64encode(b"admin:envpass123").decode()


def req(url, data=None, auth=False, headers=None, method=None):
    r = urllib.request.Request(url, data=data, method=method or ("POST" if data is not None else "GET"),
                               headers=dict(headers or {}))
    if auth:
        r.add_header("Authorization", AUTH)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def jpost(url, body, auth=True):
    code, raw = req(url, json.dumps(body).encode(), auth, {"Content-Type": "application/json"})
    return code, json.loads(raw or b"{}")


def live():
    print("خادمٌ حيّ")
    port = 9812
    data = tempfile.mkdtemp(prefix="store_live_")
    srv = M.serve(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    ms = srv.store
    ms.add(1557813796, "اشتراك كاسبر IPTV لمدة 6 أشهر", DESC, SEO)
    mock = "http://127.0.0.1:%d" % srv.server_address[1]
    env = {k: v for k, v in os.environ.items() if not k.startswith("SALLA_ADMIN_TOKEN")}
    env.update(XM_DATA=data, XM_BIND="127.0.0.1", XM_PORT=str(port), XM_ADMIN_PASSWORD="envpass123",
               SALLA_API=mock, SALLA_ACCOUNTS=mock)
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "xm_lines.py"), "web"], env=env)
    base, adm = "http://127.0.0.1:%d" % port, "http://127.0.0.1:%d/admin" % port
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/robots.txt", timeout=2)
                break
            except Exception:
                time.sleep(.2)
        check("المسارات للمدير وحده", req(adm + "/api/content/admin/store-preview", b"{}")[0] == 401
              and req(adm + "/api/content/admin/store-auth", b"{}")[0] == 401)
        code, raw = req(adm + "/api/content/admin/upload?s=casper&name=c.m3u", m3u(650), True,
                        {"Content-Type": "application/octet-stream"})
        check("رفع ملف كاسبر", code == 200, raw[:200])
        d = json.loads(req(adm + "/api/content/admin", auth=True)[1])
        check("حال الصفحة فيها بطاقة المتجر", "store" in d and d["store"]["links"] == [] and not d["store"]["ready"])
        code, d = jpost(adm + "/api/content/admin/store-auth", {"client_id": "cid-1", "secret": "csecret-1", "hook": "hooksecret"})
        check("حفظ التطبيق، والتجربة تقول إنه غير مربوط بعد", code == 200 and not d["check"]["ok"] and d["store"]["auth"]["hook"], d.get("check"))
        payload = {"event": "app.store.authorize", "merchant": 831097886,
                   "data": {"access_token": "tok-1", "refresh_token": "ref-1", "expires": int(time.time()) + 14 * 86400,
                            "scope": "products.read_write offline_access"}}
        raw, hdr = signed("wrong", payload)
        check("الويبهوك: توقيعٌ خاطئ يُرفض", req(base + "/salla/webhook", raw, headers=hdr)[0] == 401)
        raw, hdr = signed("hooksecret", payload)
        code, body = req(base + "/salla/webhook", raw, headers=hdr)
        check("وبسرّ التطبيق يُقبل (وخدمة الطلبات موقوفة)", code == 200 and json.loads(body)["event"] == "app.store.authorize", body)
        code, d = jpost(adm + "/api/content/admin/store-check", {})
        check("«جرّب الربط»: يعمل", d["check"] == {"ok": True, "total": 1} and d["store"]["auth"]["renews"], d.get("check"))
        code, d = jpost(adm + "/api/content/admin/store-products", {})
        check("المقترحة من المتجر", [(x["id"], x["suggest"]) for x in d["products"]] == [("1557813796", "casper")], d)
        code, d = jpost(adm + "/api/content/admin/store", {"on": True, "links": [{"id": "1557813796", "server": "casper",
                                                                                  "name": "كاسبر 6", "url": "https://ssouq.com/p1557813796"}]})
        check("حفظ الربط", code == 200 and d["store"]["links"][0]["server_name"] == "كاسبر" and d["store"]["on"])
        code, d = jpost(adm + "/api/content/admin/store-preview", {})
        check("المعاينة", code == 200 and d["products"][0]["changes"] and ms.puts == [], d)
        code, d = jpost(adm + "/api/content/admin/store-run", {})
        check("«حدّث الآن» يكتب في سلة", code == 200 and d["run"]["n"] == 1 and len(ms.puts) == 1
              and d["store"]["links"][0]["approved"] and "650+" in ms.products["1557813796"]["description"], d.get("run"))
        code, d = jpost(adm + "/api/content/admin/store", {"links": [{"id": "1", "server": "nope"}]})
        check("وربطٌ بسيرفرٍ غير معروف يُرفض", code == 400 and d.get("error"))
        code, raw = req(adm + "/content", auth=True)
        check("صفحة المدير فيها البطاقة", code == 200 and "أعداد المحتوى في منتجات المتجر".encode() in raw)
        disk = open(os.path.join(data, "content", "_store.json"), encoding="utf-8").read()
        check("والرمز مشفّرٌ على القرص", "tok-1" not in disk and "hooksecret" not in disk)
    finally:
        p.terminate()
        p.wait(timeout=10)
        srv.shutdown()
        shutil.rmtree(data, ignore_errors=True)


def main():
    unit_engine()
    unit_flow()
    live()
    print(f"\nResult: {_p} passed, {_f} failed")
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""أعداد المحتوى في منتجات المتجر: بعد كل سحبٍ لملف M3U تُكتب أعداد صفحة المحتوى (‏/content) في وصف منتجات
سلة المربوطة بسيرفرها — وحدها كل يوم، بلا يدٍ ولا ذكاءٍ اصطناعي.

لا يُكتب الوصف من جديد: يُقرأ من سلة كما هو، ويُبدَّل فيه ما يُعرف بشكله وحده، وما سواه يبقى حرفًا بحرف:

  • العدد التقريبي: «6,100+ فيلم» و«+6100 فيلم» و«أكثر من 6,100 فيلم»، وما عُطف عليه («أكثر من 19,000 فيلم
    و8,700 مسلسل»). يُقرَّب إلى ما دون العدد فيبقى صادقًا: 6,045 ← «6,000+» و«أكثر من 6,000».
  • العدد الدقيق زوجًا: «6,184 فيلمًا و1,788 مسلسلًا» ← «6,045 فيلمًا و1,330 مسلسلًا»، والمعدود بحسب العدد كما
    في صفحة المحتوى (فيلمًا · أفلام · فيلم). والعدد الدقيق وحده لا يُمسّ («2,647 فيلمًا جديدًا»، «قسم 2026 فيه 418
    فيلمًا»): لا يُعرف أهو المكتبة كلها أم جزءٌ منها.
  • تاريخ «آخر تحديث»: «آخر تحديث بتاريخ الثلاثاء 29 سبتمبر 2026م (18 ربيع الآخر 1448هـ)» ← يوم آخر سحب،
    باليوم وبالهجري (تقويم أم القرى) إن كُتبا.
  • المعدود: فيلم · مسلسل · قناة · حلقة · موسم، و«فيلم ومسلسل» مجموعهما. والعدد الذي ليس بعده معدودٌ منها لا يُمسّ.

وما في وسوم HTML لا يُمسّ (‏alt الصورة لقطةٌ من يومها). ويُعامل وصف محركات البحث (SEO) كالوصف.

الحرّاس: أول تحديثٍ لكل منتجٍ بيد المدير بعد المعاينة، وبعده وحده؛ والعدد الجديد إن نقص عن 70% مما في الوصف أو
زاد على ضعفه (ملفٌّ ناقص، أو عددٌ ليس للمكتبة) لا يُكتب وحده — يُعلَّق المنتج كله ويُنبَّه المدير؛ وبعد الكتابة
يُقارن نوع المنتج وسعره وحاله وكميته بما كانت، فإن تغيّر شيءٌ منها توقّف التحديث التلقائي ونُبّه المدير.

الربط بسلة: رمز واجهة الإدارة (‏Bearer) من تطبيقٍ في سلة يتجدّد وحده — يعيش الرمز 14 يومًا، ورمز التجديد شهرًا
ويُستعمل مرةً واحدة — ويصل بويبهوك ‏app.store.authorize أو يُلصق؛ وإلا فتوكن إدارة سلة من إعداد الخدمة. والأسرار
مشفّرة على القرص ولا تصل المتصفح.

التخزين: ‏data/content/_store.json (والشرطة السفلى أولًا فلا يكون ملف سيرفر: مفتاحه يبدأ بحرفٍ أو رقم). بلا مكتبات
خارجية.
"""
import datetime
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import content
import crypto_store
import guide_pages
import salla_api

API = os.environ.get("SALLA_API", "https://api.salla.dev").rstrip("/")            # يُغيَّر في الاختبارات وحدها
ACCOUNTS = os.environ.get("SALLA_ACCOUNTS", "https://accounts.salla.sa").rstrip("/")
ADMIN_URL = "https://s.salla.sa/products/"
HOOK_URL = guide_pages.SITE + "/salla/webhook"
TIMEOUT = 30
UA = "ssouq-guide-store/1.0"
FILE = "_store.json"
LOW, HIGH = 0.7, 2.0          # العدد الجديد إلى ما في الوصف: خارجهما لا يُكتب وحده
RETRY = 3600                  # منتجٌ فشل تحديثه يُعاد بعد ساعة
RENEW_BEFORE = 3 * 86400      # الرمز يُجدَّد قبل انتهائه بثلاثة أيام
MAX_LINKS = 60
SEARCH_PAGES = 3              # صفحات البحث في منتجات المتجر (50 في الصفحة)
# بادئات رموز المنتجات (SKU) التي تعرّف السيرفر في هذا المتجر: ‏MRH مرح (سمارت) · ‏FAL فالكون
SKU_PREFIX = {"smart": ("MRH",), "falcon": ("FAL",)}

notifier = None               # (العنوان، النص) ← نتيجة الإرسال — يضبطه الخادم: بريد المدير وواتسابه
fallback_token = None         # () ← توكن إدارة سلة من إعداد الخدمة إن لم يُربط تطبيق هنا — يضبطه الخادم

_lock = threading.RLock()     # الملف: قراءةٌ ثم كتابة
_auth_lock = threading.Lock() # تجديد الرمز: رمز التجديد يُستعمل مرةً واحدة، فلا تجديدان معًا
_run_lock = threading.Lock()  # تحديثٌ واحد للمتجر في وقته: التلقائي و«حدّث الآن» لا يلتقيان


class SallaError(RuntimeError):
    def __init__(self, msg, code=0):
        super().__init__(msg)
        self.code = code


# ================= النص: ما يُعرف في الوصف ويُبدَّل =================
_DG = "0-9٠-٩"
_EN = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_AR = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
_TASH = "ً-ْ"
_TAG = re.compile(r"<[^<>]*>")
_BLOCK = re.compile(r"</?\s*(?:p|div|h[1-6]|li|ul|ol|br|hr|tr|td|th|table|tbody|thead|section|article|blockquote|"
                    r"pre|figure|img)\b", re.I)
# بين العدد ومعدوده: مسافاتٌ ووسوم — والسطر إلى السطر («<strong>6,100+</strong></p><p>فيلم مترجم»)
_GAP = r"(?:[\s ‎‏]|&nbsp;|<[\x01\x02]*>){0,12}"
_IGAP = r"(?:[\s ‎‏]|&nbsp;|<\x01*>){0,8}"     # وسومٌ داخل السطر وحدها
_W = rf"[{_TASH}]*(?![\w{_TASH}])"
_MOV = r"أفلام|افلام|فيلم(?:ًا|اً|ا|ٍ)?"
_SER = r"مسلسلات|مسلسل(?:ًا|اً|ا|ٍ)?"
_NOUN = (rf"(?:(?P<total>(?:{_MOV}){_W}\s*و\s*(?:{_SER}){_W}|(?:{_SER}){_W}\s*و\s*(?:{_MOV}){_W})"
         rf"|(?P<movies>(?:{_MOV}){_W})|(?P<series>(?:{_SER}){_W})|(?P<channels>(?:قنوات|قناة|قناه){_W})"
         rf"|(?P<episodes>(?:حلقات|حلقة|حلقه){_W})|(?P<seasons>(?:مواسم|موسم(?:ًا|اً|ا)?){_W}))")
KINDS = ("total", "movies", "series", "channels", "episodes", "seasons")
_TOKEN = re.compile(rf"(?<![{_DG}.,٬/A-Za-z])(?P<num>[{_DG}]{{1,3}}(?:[,٬][{_DG}]{{3}})+|[{_DG}]{{1,7}})"
                    rf"(?![{_DG}]|[,٬][{_DG}])(?P<plus>\s*\+)?{_GAP}{_NOUN}")
_MORE = re.compile(rf"(?:أكثر|اكثر)\s+من{_GAP}\+?\s*$")
_PLUS = re.compile(r"\+\s*$")
_CHAIN = re.compile(rf"{_GAP}و{_GAP}\+?\s*")               # «… فيلم و8,700 مسلسل» «و+1700»
# بعد المعدود ما يجيز تغييره (فيلمًا ← أفلام): نهاية الجملة أو عطف — لا صفةٌ تتبعه («فيلمًا جديدًا» يبقى كما هو)
_SAFE = re.compile(rf"{_IGAP}(?:$|[،,.؛;:!؟?)\]»\"'…]|<\x02|و(?=[\s{_DG}+<]))")
FORMS = {"movies": content.N_MOVIES, "series": content.N_SERIES, "channels": content.N_CHANNELS,
         "episodes": content.N_EPISODES, "seasons": content.N_SEASONS}
WHAT = {"total": "الأفلام والمسلسلات", "movies": "الأفلام", "series": "المسلسلات", "channels": "القنوات",
        "episodes": "الحلقات", "seasons": "المواسم", "date": "تاريخ آخر تحديث"}

# تاريخ «آخر تحديث»
_WD = "الأحد|الاحد|الاثنين|الإثنين|الأثنين|الثلاثاء|الأربعاء|الاربعاء|الخميس|الجمعة|الجمعه|السبت"
_GM = {"يناير": 1, "فبراير": 2, "مارس": 3, "أبريل": 4, "ابريل": 4, "إبريل": 4, "مايو": 5, "يونيو": 6, "يوليو": 7,
       "أغسطس": 8, "اغسطس": 8, "سبتمبر": 9, "أكتوبر": 10, "اكتوبر": 10, "نوفمبر": 11, "ديسمبر": 12}
_HM = {"محرم": 1, "المحرم": 1, "صفر": 2, "ربيع الأول": 3, "ربيع الاول": 3, "ربيع أول": 3, "ربيع الآخر": 4,
       "ربيع الاخر": 4, "ربيع آخر": 4, "ربيع الثاني": 4, "ربيع الثانى": 4, "ربيع ثاني": 4, "جمادى الأولى": 5,
       "جمادى الاولى": 5, "جمادي الأولى": 5, "جمادي الاولى": 5, "جمادى الأول": 5, "جمادى الآخرة": 6, "جمادى الاخرة": 6,
       "جمادى الآخر": 6, "جمادي الآخرة": 6, "جمادي الاخرة": 6, "جمادى الثانية": 6, "جمادي الثانية": 6, "رجب": 7,
       "شعبان": 8, "رمضان": 9, "شوال": 10, "ذو القعدة": 11, "ذي القعدة": 11, "ذو القعده": 11, "ذو الحجة": 12,
       "ذي الحجة": 12, "ذو الحجه": 12}
HIJRI_MONTHS = ("محرم", "صفر", "ربيع الأول", "ربيع الآخر", "جمادى الأولى", "جمادى الآخرة", "رجب", "شعبان", "رمضان",
                "شوال", "ذو القعدة", "ذو الحجة")
_alt = lambda xs: "|".join(sorted(xs, key=len, reverse=True))   # noqa: E731 — الأطول أولًا
_CTX = re.compile(r"(?:آخر|اخر|أخر)\s+تحديث")
_DATE = re.compile(rf"(?:(?P<wd>{_WD})\s*[،,]?{_IGAP})?(?P<d>[{_DG}]{{1,2}})\s+(?P<m>{_alt(_GM)})\s*[،,]?\s+"
                   rf"(?P<y>[{_DG}]{{4}})(?![{_DG}])")
_HIJRI = re.compile(rf"\s*م?(?![\w]){_IGAP}\(\s*(?P<hd>[{_DG}]{{1,2}})\s+(?P<hm>{_alt(_HM)})\s+(?P<hy>[{_DG}]{{4}})"
                    rf"\s*(?:هـ|ه)?\s*\)")
_STOP = re.compile(r"[.!؟?\n]|<\x02")

# تقويم أم القرى: أطوال الأشهر من محرم 1446 (7 يوليو 2024) إلى ذي الحجة 1470 (8 أكتوبر 2048) — بتٌّ لكل شهر، 1 = ثلاثون
# يومًا و0 = تسعةٌ وعشرون، من جداول أم القرى (مكتبة hijridate). وخارجها يبقى الهجري المكتوب كما هو.
_UQ_YEAR = 1446
_UQ_START = datetime.date(2024, 7, 7).toordinal()
_UQ_BITS = bin(int("764baa5b52b6a56d2ae9572a75535a95d49ba4dd26d535aaaad4b6a57527a95b4ab5536c9ae", 16))[2:].zfill(300)


def hijri(day):
    """التاريخ الميلادي ← (السنة، الشهر، اليوم) بتقويم أم القرى، أو None خارج الجدول."""
    o = day.toordinal() - _UQ_START
    if o < 0:
        return None
    for i, b in enumerate(_UQ_BITS):
        n = 30 if b == "1" else 29
        if o < n:
            return _UQ_YEAR + i // 12, i % 12 + 1, o + 1
        o -= n
    return None


def _mask(html):
    """الوسوم بطولها نفسه وحشوٍ لا يطابق شيئًا (‏\\x02 للكتل: الفقرة والعنوان والسطر، و‏\\x01 لغيرها) — فتُبحث النصوص
    وحدها ويُبدَّل في الأصل بالمواضع نفسها، ولا يُمسّ ما في الوسوم."""
    return _TAG.sub(lambda m: "<" + ("\x02" if _BLOCK.match(m.group(0)) else "\x01") * (len(m.group(0)) - 2) + ">", html)


def _num(s):
    return int(re.sub(r"[,٬]", "", s.translate(_EN)))


def _fmt(n, like):
    """العدد بشكل ما كان مكانه: الفاصلة («6,100») أو بدونها («+6100») أو الفاصلة العربية، والأرقام الهندية إن كانت."""
    digits = re.sub(r"\D", "", like.translate(_EN))
    sep = "٬" if "٬" in like else "," if ("," in like or len(digits) < 4) else ""
    s = f"{n:,}".replace(",", sep)
    return s.translate(_AR) if re.search("[٠-٩]", like) else s


def approx(n, strict):
    """العدد التقريبي دون العدد: بالعشرات تحت الألف، وبالمئات تحت عشرة آلاف، وبالآلاف فوقها. و«أكثر من» (‏strict) دونه
    حقًّا: 6,000 فيلم بالضبط «أكثر من 5,900» و«6,000+»."""
    step = 10 if n < 1000 else 100 if n < 10000 else 1000
    v = (n - 1 if strict else n) // step * step
    return v if v > 0 else max(n - (1 if strict else 0), 0)


def counted(n, forms):
    """معدود العدد بعده كما في content._count: جمعٌ لما آخره 3–10، ومفردٌ منصوب لـ11–99، ومفردٌ للمئات."""
    r = n % 100
    return forms[2] if 3 <= r <= 10 else forms[3] if (r > 10 or n < 100) else forms[4]


def _bare(s):
    return re.sub(rf"[{_TASH}]", "", s)


def _text(html):
    """مقطعٌ من الوصف نصًّا للمدير: بلا وسوم."""
    s = re.sub(r"<[^<>]*>", " ", html).replace("&nbsp;", " ")
    return " ".join(s.split())


def _local_day(ts):
    return datetime.date(*time.gmtime(ts + content.RIYADH)[:3])


def plan(html, counts, when=None):
    """الوصف ← (الوصف الجديد، التغييرات). counts أعداد السيرفر {movies, series, channels, episodes, seasons}، وwhen وقت
    آخر سحب (لتاريخ «آخر تحديث»). والتغيير {what, mode, old, new, far}: far عددٌ خارج LOW–HIGH مما كان — يُكتب
    بموافقة المدير وحدها. وما سوى المواضع المعروفة يبقى حرفًا بحرف."""
    html = html if isinstance(html, str) else ""
    if not html:
        return html, []
    m = _mask(html)
    edits, changes = [], []

    # ----- الأعداد -----
    toks = []
    for mt in _TOKEN.finditer(m):
        s = mt.start("num")
        before = m[max(0, s - 90):s]
        more, plus = _MORE.search(before), _PLUS.search(before)
        toks.append({"mt": mt, "kind": next(k for k in KINDS if mt.group(k)), "more": bool(more),
                     "plus": bool(mt.group("plus")) or bool(plus), "mode": "",
                     "lead": s - len(before) + (more.start() if more else plus.start() if plus else len(before))})
    for i, t in enumerate(toks):
        prev = toks[i - 1] if i else None
        linked = bool(prev) and prev["kind"] != t["kind"] and bool(
            _CHAIN.fullmatch(m, prev["mt"].end(), t["mt"].start("num")))
        if t["plus"] or t["more"]:
            t["mode"], t["strict"] = "approx", t["more"] and not t["plus"]
        elif linked and prev["mode"] == "approx":
            t["mode"], t["strict"] = "approx", prev["strict"]
        elif linked and prev["mode"] in ("", "exact"):          # زوجٌ: «6,184 فيلمًا و1,788 مسلسلًا»
            prev["mode"] = t["mode"] = "exact"
    for t in toks:
        if not t["mode"]:
            continue
        mt, kind = t["mt"], t["kind"]
        n = (counts.get("movies", 0) + counts.get("series", 0)) if kind == "total" else counts.get(kind, 0)
        if not n:
            continue
        old_txt = mt.group("num")
        old, new = _num(old_txt), approx(n, t["strict"]) if t["mode"] == "approx" else n
        mine = [(mt.start("num"), mt.end("num"), _fmt(new, old_txt))]
        if t["mode"] == "exact" and kind in FORMS and new > 2 and _SAFE.match(m, mt.end()):
            a, b = mt.span(kind)
            noun = counted(new, FORMS[kind])
            if _bare(html[a:b]) != _bare(noun):
                mine.append((a, b, noun))
        if mine[0][2] == old_txt and len(mine) == 1:
            continue
        a, b = t["lead"], mt.end()
        seg = html[a:b]
        for x, y, r in sorted(mine, reverse=True):
            seg = seg[:x - a] + r + seg[y - a:]
        edits += mine
        changes.append({"what": kind, "mode": t["mode"], "old": _text(html[a:b]), "new": _text(seg),
                        "far": bool(old) and not LOW <= new / old <= HIGH})

    # ----- تاريخ «آخر تحديث» -----
    if when:
        day, seen = _local_day(when), set()
        for c in _CTX.finditer(m):
            win = m[c.end():c.end() + 100]
            stop = _STOP.search(win)
            d = _DATE.search(m, c.end(), c.end() + (stop.start() if stop else len(win)))
            if not d or d.start() in seen:
                continue
            seen.add(d.start())
            mine = []
            if d.group("wd"):
                mine.append((d.start("wd"), d.end("wd"), content._DAYS[day.weekday()]))
            mine += [(d.start("d"), d.end("d"), _fmt(day.day, d.group("d"))),
                     (d.start("m"), d.end("m"), content._MONTHS[day.month - 1]),
                     (d.start("y"), d.end("y"), _fmt(day.year, d.group("y")).replace(",", "").replace("٬", ""))]
            end = d.end()
            h = _HIJRI.match(m, d.end())
            if h:
                hj = hijri(day)
                if not hj:                       # خارج جدول أم القرى: يبقى التاريخ كله، لا ميلاديٌّ جديد بهجريٍّ قديم
                    continue
                hm = HIJRI_MONTHS[hj[1] - 1]
                if hj[1] in (4, 6) and re.search("الثاني|الثانى|الثانية", h.group("hm")):
                    hm = ("ربيع الثاني", "جمادى الثانية")[hj[1] == 6]
                mine += [(h.start("hd"), h.end("hd"), _fmt(hj[2], h.group("hd"))),
                         (h.start("hm"), h.end("hm"), hm),
                         (h.start("hy"), h.end("hy"), _fmt(hj[0], h.group("hy")).replace(",", "").replace("٬", ""))]
                end = h.end()
            a = d.start()
            seg = html[a:end]
            for x, y, r in sorted(mine, reverse=True):
                seg = seg[:x - a] + r + seg[y - a:]
            if seg == html[a:end]:
                continue
            edits += mine
            changes.append({"what": "date", "mode": "date", "old": _text(html[a:end]), "new": _text(seg), "far": False})

    out = html
    last = len(html) + 1
    for x, y, r in sorted(edits, reverse=True):
        if y > last:                         # تداخلٌ لا ينبغي — يُترك الأول ولا يُفسد الوصف
            continue
        out = out[:x] + r + out[y:]
        last = x
    return out, changes


# ================= واجهة سلة =================
def _call(method, url, token=None, body=None, form=None):
    headers = {"Accept": "application/json", "User-Agent": UA}
    data = None
    if token:
        headers["Authorization"] = "Bearer " + token
    if body is not None:
        data, headers["Content-Type"] = json.dumps(body, ensure_ascii=False).encode("utf-8"), "application/json"
    elif form is not None:
        data, headers["Content-Type"] = urllib.parse.urlencode(form).encode(), "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace") if e.fp else ""
        raise SallaError(_http_error(e.code, raw), e.code)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SallaError("تعذّر الوصول إلى سلة (%s)" % (getattr(e, "reason", "") or type(e).__name__))
    try:
        return json.loads(raw or "{}")
    except ValueError:
        raise SallaError("ردّت سلة بما ليس JSON")


def _http_error(code, raw):
    try:
        d = json.loads(raw or "{}")
    except ValueError:
        d = {}
    err = d.get("error") if isinstance(d, dict) else None
    msg = ""
    if isinstance(err, dict):
        msg = str(err.get("message") or "")
        fields = err.get("fields")
        if isinstance(fields, dict) and fields:
            msg += " — " + "؛ ".join("%s: %s" % (k, " ".join(map(str, v)) if isinstance(v, list) else v)
                                     for k, v in list(fields.items())[:3])
    elif isinstance(d, dict):
        msg = str(d.get("error_description") or d.get("message") or err or "")
    msg = msg.strip()[:200]
    if code == 401:
        return "سلة لم تقبل الرمز (401) — انتهى أو أُلغي" + (": " + msg if msg else "")
    if code == 403:
        return "الرمز لا يملك صلاحية المنتجات في سلة (403) — أضف صلاحية «المنتجات: قراءة وكتابة» لتطبيقك"
    if code == 404:
        return "غير موجود في المتجر (404)"
    if code == 429:
        return "طلباتٌ كثيرة على سلة الآن (429) — يُعاد لاحقًا"
    return "ردّت سلة برمز %d%s" % (code, (": " + msg) if msg else "")


def get_product(token, pid):
    d = _call("GET", "%s/admin/v2/products/%s" % (API, urllib.parse.quote(str(pid))), token)
    p = d.get("data") if isinstance(d, dict) else None
    if not isinstance(p, dict):
        raise SallaError("ردّت سلة بلا بيانات المنتج")
    return p


def put_product(token, pid, fields):
    """تحديثٌ جزئي: ما في fields وحده (الوصف ووصف محركات البحث)، وما سواه في المنتج كما هو."""
    d = _call("PUT", "%s/admin/v2/products/%s" % (API, urllib.parse.quote(str(pid))), token, body=fields)
    p = d.get("data") if isinstance(d, dict) else None
    return p if isinstance(p, dict) else {}


def search_products(token, keyword="", pages=SEARCH_PAGES):
    """منتجات المتجر (بالاسم أو الرمز) ← [{id, name, sku, status, type, url}] بلا المحذوف."""
    out = []
    for page in range(1, pages + 1):
        q = {"per_page": 50, "page": page}
        if keyword:
            q["keyword"] = keyword
        d = _call("GET", "%s/admin/v2/products?%s" % (API, urllib.parse.urlencode(q)), token)
        rows = d.get("data") if isinstance(d, dict) else None
        for p in rows if isinstance(rows, list) else []:
            if not isinstance(p, dict) or str(p.get("status") or "") == "deleted" or not str(p.get("id") or "").isdigit():
                continue
            out.append({"id": str(p["id"]), "name": " ".join(str(p.get("name") or "").split())[:200],
                        "sku": str(p.get("sku") or "")[:64], "status": str(p.get("status") or ""),
                        "type": str(p.get("type") or ""), "url": _url(p)})
        pg = d.get("pagination") if isinstance(d, dict) else None
        if not rows or not isinstance(pg, dict) or page >= int(pg.get("totalPages") or 1):
            break
    return out


def _url(p):
    u = p.get("urls") if isinstance(p.get("urls"), dict) else {}
    u = u.get("customer") or u.get("url") or p.get("url") or ""
    return u if isinstance(u, str) and u.startswith("https://") else ""


def _drift(before, after):
    """ما تغيّر بالكتابة ولم يُطلب: نوع المنتج (بطاقات الأكواد) وسعره — وما لم يرجع في الردّ لا يُقارن. والكمية والحال لا
    تُقارنان: كودٌ يُباع في اللحظة نفسها يغيّرهما بحق."""
    def amount(v):
        return v.get("amount") if isinstance(v, dict) else v
    out = []
    if "type" in after and "type" in before and after["type"] != before["type"]:
        out.append("نوع المنتج: %s ← %s" % (before["type"], after["type"]))
    if "price" in after and "price" in before and amount(after["price"]) != amount(before["price"]):
        out.append("سعره: %s ← %s" % (amount(before["price"]), amount(after["price"])))
    return out


# ================= الإعداد والحال =================
def _path(data_dir):
    return os.path.join(data_dir, content.DIR, FILE)


def _load(data_dir):
    s = content._read(_path(data_dir)) or {}
    links = []
    for x in s.get("links") or []:
        if isinstance(x, dict) and str(x.get("id") or "").isdigit() and content.key_ok(x.get("server")):
            links.append({"id": str(x["id"]), "server": content.key_ok(x["server"]),
                          "name": str(x.get("name") or "")[:200], "url": str(x.get("url") or "")[:500]})
    st = s.get("state") if isinstance(s.get("state"), dict) else {}
    return {"on": bool(s.get("on")), "links": links[:MAX_LINKS],
            "state": {k: v for k, v in st.items() if isinstance(v, dict)},
            "auth": s.get("auth") if isinstance(s.get("auth"), dict) else {},
            "last": s.get("last") if isinstance(s.get("last"), dict) else None,
            "alerted": str(s.get("alerted") or "")}


def _save(data_dir, s):
    content._write(_path(data_dir), s)


def _change(data_dir, fn):
    with _lock:
        s = _load(data_dir)
        out = fn(s)
        _save(data_dir, s)
        return out


def _dec(data_dir, v):
    return crypto_store.decrypt(v, data_dir) if isinstance(v, str) and v else ""


def _contents(data_dir):
    """السيرفرات التي لها محتوى ← {المفتاح: {name, at, counts, sig}} — الأعداد كما في صفحة المحتوى (بلا المخفي)."""
    out = {}
    for x in content.brief(data_dir)["servers"]:
        counts = {k: int(x[k]) for k in ("movies", "series", "channels", "episodes", "seasons")}
        out[x["key"]] = {"name": x["name"], "at": int(x["at"]), "counts": counts,
                         "sig": "|".join(str(v) for v in [int(x["at"])] + list(counts.values()))}
    return out


def suggest(p, servers):
    """السيرفر المقترح لمنتج من اسمه ورمزه: اسم السيرفر أو ما تحته أو مفتاحه كلمةً فيه، أو بادئة رمزه (‏FAL فالكون ·
    ‏MRH سمارت) — وإن احتمل أكثر من سيرفر فلا اقتراح."""
    text = content._norm("%s %s" % (p.get("name", ""), p.get("sku", "")))
    words, sku = set(text.split()), str(p.get("sku") or "").upper()
    hits = []
    for s in servers:
        toks = {content._norm(s.get("name", "")), content._norm(s.get("full", "")), s["key"]} - {""}
        if any((t in words) if " " not in t else (" %s " % t in " %s " % text) for t in toks) or \
                any(sku.startswith(x) for x in SKU_PREFIX.get(s["key"], ())):
            hits.append(s["key"])
    return hits[0] if len(hits) == 1 else ""


def state(data_dir):
    """لبطاقة المتجر في صفحة المحتوى: الربط (بلا أسرار)، والمنتجات المربوطة بحالها، وآخر تحديث."""
    s = _load(data_dir)
    a = s["auth"]
    cur = _contents(data_dir)
    names = {x["key"]: x["name"] for x in content.servers(data_dir)}
    links = []
    for l in s["links"]:
        st, c = s["state"].get(l["id"]) or {}, cur.get(l["server"])
        links.append(dict(l, server_name=names.get(l["server"], l["server"]), has=bool(c),
                          fresh=bool(c) and st.get("sig") == c["sig"], approved=bool(st.get("approved")),
                          at=st.get("at") or 0, put_at=st.get("put_at") or 0, ok=st.get("ok", True),
                          error=str(st.get("error") or ""), changes=st.get("changes") or [],
                          held=st.get("held") or [] if c and st.get("held_sig") == c["sig"] else [],
                          admin=ADMIN_URL + l["id"]))
    try:
        fb = bool(fallback_token and fallback_token())
    except Exception:  # noqa: BLE001 — حال الربط لا يُسقط الصفحة
        fb = False
    own = bool(a.get("token"))
    return {"on": s["on"], "links": links, "last": s["last"], "hook_url": HOOK_URL, "ready": own or fb,
            "auth": {"own": own, "fallback": fb, "refresh": bool(a.get("refresh")), "client_id": str(a.get("client_id") or ""),
                     "secret": bool(a.get("secret")), "hook": bool(a.get("hook")), "expires": a.get("expires") or 0,
                     "source": str(a.get("source") or ""), "scope": str(a.get("scope") or ""),
                     "merchant": str(a.get("merchant") or ""), "at": a.get("at") or 0, "renewed": a.get("renewed") or 0,
                     "error": str(a.get("error") or ""),
                     "renews": own and bool(a.get("refresh") and a.get("client_id") and a.get("secret"))}}


def save(data_dir, body):
    """المنتجات المربوطة وسيرفر كلٍّ منها، والتحديث التلقائي."""
    keys = {x["key"] for x in content.servers(data_dir)}
    links, seen = [], set()
    for x in body.get("links") or []:
        if not isinstance(x, dict):
            continue
        pid, srv = str(x.get("id") or "").strip(), content.key_ok(x.get("server"))
        if not pid.isdigit() or pid in seen:
            continue
        if srv not in keys:
            raise ValueError("اختر سيرفرًا من القائمة لكل منتج")
        seen.add(pid)
        url = str(x.get("url") or "")
        links.append({"id": pid, "server": srv, "name": " ".join(str(x.get("name") or "").split())[:200],
                      "url": url[:500] if url.startswith("https://") else ""})
    if len(links) > MAX_LINKS:
        raise ValueError("الحد %d منتجًا" % MAX_LINKS)

    def fn(s):
        old = {l["id"]: l["server"] for l in s["links"]}
        s["links"], s["on"] = links, bool(body.get("on"))
        for pid in list(s["state"]):             # منتجٌ فُكّ أو تغيّر سيرفره يبدأ من جديد: أول تحديثٍ بيد المدير
            if old.get(pid) != next((l["server"] for l in links if l["id"] == pid), None):
                s["state"].pop(pid, None)
    _change(data_dir, fn)


def save_auth(data_dir, body):
    """ربط تطبيق سلة: معرّفه وسرّه وسرّ الويبهوك، أو رمزٌ يُلصق (ورمز تجديده). والخانة الفارغة تُبقي المحفوظ، و«clear»
    يفصل الربط كله."""
    if body.get("clear"):
        return _change(data_dir, lambda s: s.__setitem__("auth", {}))
    cid = str(body.get("client_id") or "").strip()
    if cid and not re.fullmatch(r"[A-Za-z0-9._-]{4,100}", cid):
        raise ValueError("معرّف التطبيق (Client ID) حروفٌ إنجليزية وأرقام")
    vals = {k: str(body.get(k) or "").strip() for k in ("secret", "hook", "token", "refresh")}
    for k, v in vals.items():
        if v and (len(v) > 4000 or re.search(r"\s", v)):
            raise ValueError("الصق القيمة كما هي بلا مسافات")

    def fn(s):
        a = s["auth"]
        if cid:
            a["client_id"] = cid
        for k in ("secret", "hook"):
            if vals[k]:
                a[k] = crypto_store.encrypt(vals[k], data_dir)
        if vals["token"]:                        # رمزٌ لُصق: يُستعمل حتى ينتهي، ويُجدَّد إن لُصق رمز تجديده
            a.update(token=crypto_store.encrypt(vals["token"], data_dir), source="paste", at=time.time(), error="",
                     expires=0, scope="", renew_fail=0)
            a.pop("refresh", None)
            s["alerted"] = ""
        if vals["refresh"]:
            a.update(refresh=crypto_store.encrypt(vals["refresh"], data_dir), renew_fail=0)
            if vals["token"]:
                a["expires"] = time.time() + 14 * 86400 - 3600   # لا يُعرف من الرمز نفسه: يُعدّ من لحظة لصقه
    _change(data_dir, fn)


# ================= الرمز: يُستعمل ويُجدَّد =================
def _renew(data_dir, now):
    """يجدّد الرمز برمز التجديد (يُستعمل مرةً واحدة، ويُحفظ الجديد قبل أي شيء) ← الرمز الجديد. تحت ‏_auth_lock."""
    a = _load(data_dir)["auth"]
    form = {"grant_type": "refresh_token", "refresh_token": _dec(data_dir, a.get("refresh")),
            "client_id": str(a.get("client_id") or ""), "client_secret": _dec(data_dir, a.get("secret"))}
    try:
        d = _call("POST", ACCOUNTS + "/oauth2/token", form=form)
    except SallaError as e:
        err = str(e)
        if e.code in (400, 401):                 # رفضٌ قاطع: لا يُعاد به (إعادة رمز التجديد عند سلة إساءةٌ قد تُلغي الربط كله)
            err = "لم تقبل سلة رمز التجديد — افتح تطبيقك في متجرك (أو أعد تثبيته) فيصل رمزٌ جديد"
            _change(data_dir, lambda s: s["auth"].update(error=err, refresh="", renew_fail=now))
        else:                                    # شبكةٌ أو خطأٌ عندها: يُعاد بعد ساعة، لا في كل دورة
            _change(data_dir, lambda s: s["auth"].update(error=("لم يُجدَّد رمز سلة: " + err)[:300], renew_fail=now))
        raise SallaError(err, e.code)
    tok, ref = str(d.get("access_token") or ""), str(d.get("refresh_token") or "")
    if not tok:
        raise SallaError("ردّت سلة بلا رمز")

    def fn(s):
        s["auth"].update(token=crypto_store.encrypt(tok, data_dir), expires=now + int(d.get("expires_in") or 14 * 86400),
                         renewed=now, error="", **({"refresh": crypto_store.encrypt(ref, data_dir)} if ref else {}),
                         **({"scope": str(d["scope"])[:500]} if d.get("scope") else {}))
        s["alerted"] = ""                        # فشلٌ لاحق يُنبَّه به من جديد
    _change(data_dir, fn)
    return tok


def token(data_dir, now=None, force=False):
    """رمز واجهة الإدارة: رمز التطبيق المربوط هنا (ويُجدَّد قبل انتهائه، أو الآن بـ force بعد 401)، وإلا توكن إدارة سلة
    من إعداد الخدمة."""
    now = now or time.time()
    with _auth_lock:
        a = _load(data_dir)["auth"]
        tok = _dec(data_dir, a.get("token"))
        if tok:
            exp = float(a.get("expires") or 0)
            can = bool(a.get("refresh") and a.get("client_id") and a.get("secret"))
            if can and not force and now - float(a.get("renew_fail") or 0) < RETRY:
                can = False                      # فشل تجديدٌ قبل أقل من ساعة
            if can and (force or (exp and exp - now < RENEW_BEFORE)):
                try:
                    return _renew(data_dir, now)
                except SallaError:
                    if force or (exp and exp <= now):
                        raise
            if exp and exp <= now:               # والسبب ما حُفظ إن كان (تجديدٌ مرفوض): سببٌ واحد، فتنبيهٌ واحد
                raise SallaError(str(a.get("error") or "انتهى رمز سلة — افتح تطبيقك في متجرك أو الصق رمزًا جديدًا"), 401)
            return tok
    fb = ""
    try:
        fb = fallback_token() if fallback_token else ""
    except Exception:  # noqa: BLE001
        fb = ""
    if fb:
        return fb
    raise SallaError("المتجر غير مربوط — اربطه من بطاقة «أعداد المحتوى في المتجر»")


def _renewable(data_dir):
    a = _load(data_dir)["auth"]
    return bool(a.get("token") and a.get("refresh") and a.get("client_id") and a.get("secret"))


def check(data_dir):
    """أيعمل الربط؟ منتجٌ واحد من المتجر ← {ok, total} أو {ok: False, error}."""
    try:
        tok = token(data_dir)
        d = _call("GET", "%s/admin/v2/products?per_page=1" % API, tok)
    except SallaError as e:
        return {"ok": False, "error": str(e)}
    pg = d.get("pagination") if isinstance(d, dict) else None
    return {"ok": True, "total": int(pg.get("total") or 0) if isinstance(pg, dict) else 0}


def catalog(data_dir, q=""):
    """منتجات المتجر للربط، ولكلٍّ سيرفره المقترح: ما يطابق ما كُتب، أو ما يطابق أسماء السيرفرات وبادئات رموزها."""
    servers = content.servers(data_dir)
    q = " ".join(str(q or "").split())[:60]
    kws = [q] if q else list(dict.fromkeys([x["name"] for x in servers if x["name"]]
                                           + [p for x in servers for p in SKU_PREFIX.get(x["key"], ())]))
    try:
        tok = token(data_dir)
        seen, out = set(), []
        for kw in kws[:12]:
            for p in search_products(tok, kw, pages=SEARCH_PAGES if q else 1):
                if p["id"] not in seen:
                    seen.add(p["id"])
                    out.append(dict(p, suggest=suggest(p, servers)))
    except SallaError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "products": out[:200]}


# ================= التحديث =================
def sync_product(tok, pid, c, force=False, write=True):
    """منتجٌ واحد بأعداد سيرفره c ({counts, at}) ← {ok, name, changes, held, written, error}. held التغييرات البعيدة
    (خارج LOW–HIGH): لا يُكتب شيءٌ من المنتج معها إلا بـ force. وwrite=False معاينةٌ لا تكتب."""
    p = get_product(tok, pid)
    desc = p.get("description") if isinstance(p.get("description"), str) else ""
    meta = p.get("metadata") if isinstance(p.get("metadata"), dict) else {}
    seo = meta.get("description") if isinstance(meta.get("description"), str) else ""
    nd, cd = plan(desc, c["counts"], c["at"])
    ns, cs = plan(seo, c["counts"], c["at"])
    changes = cd + [dict(x, seo=True) for x in cs]
    far = [x for x in changes if x["far"]]
    out = {"ok": True, "name": " ".join(str(p.get("name") or "").split())[:200], "url": _url(p), "changes": changes,
           "held": [], "written": False, "error": ""}
    if not write or not changes:
        return dict(out, held=far)
    if far and not force:
        return dict(out, held=far)
    fields = {}
    if nd != desc:
        fields["description"] = nd
    if ns != seo:
        fields["metadata_description"] = ns
    after = put_product(tok, pid, fields)
    bad = _drift(p, after)
    if bad:
        return dict(out, ok=False, written=True, danger=True,
                    error="كُتب الوصف لكن تغيّر في المنتج ما لم يُطلب: " + "؛ ".join(bad) + " — راجعه في سلة")
    return dict(out, written=True)


def _pick(s, ids):
    have = {l["id"]: l for l in s["links"]}
    return [have[i] for i in dict.fromkeys(str(x) for x in ids) if i in have] if ids is not None else list(s["links"])


def preview(data_dir, ids=None):
    """ما سيتغيّر في كل منتجٍ مربوط الآن — بلا كتابة ← {ok, products: [{id, server, name, changes, held, error}]}."""
    s = _load(data_dir)
    cur = _contents(data_dir)
    try:
        tok = token(data_dir)
    except SallaError as e:
        return {"ok": False, "error": str(e)}
    out = []
    for l in _pick(s, ids):
        c = cur.get(l["server"])
        row = {"id": l["id"], "server": l["server"], "name": l["name"], "admin": ADMIN_URL + l["id"]}
        if not c:
            out.append(dict(row, ok=False, error="لا محتوى لهذا السيرفر بعد", changes=[], held=[]))
            continue
        try:
            out.append(dict(row, **sync_product(tok, l["id"], c, write=False)))
        except SallaError as e:
            out.append(dict(row, ok=False, error=str(e), changes=[], held=[]))
    return {"ok": True, "products": out}


def run(data_dir, ids=None, manual=False, force=False, now=None):
    """يكتب الأعداد في المنتجات المربوطة (أو ids منها) ← {ok, results}. اليدوي («حدّث الآن») يعتمد المنتج فيصير تحديثه
    بعده تلقائيًّا، وforce يكتب البعيد أيضًا؛ والتلقائي يعلّق المنتج ذا التغيير البعيد وينبّه المدير."""
    if not _run_lock.acquire(blocking=False):
        return {"ok": False, "error": "يُحدَّث المتجر الآن — انتظر حتى ينتهي"}
    try:
        now = now or time.time()
        s = _load(data_dir)
        cur = _contents(data_dir)
        links = _pick(s, ids)
        try:
            tok, terr = token(data_dir, now), ""
        except SallaError as e:
            tok, terr = "", str(e)
        results, retried = {}, False
        for l in links:
            c = cur.get(l["server"])
            if not c:
                results[l["id"]] = {"ok": False, "error": "لا محتوى لهذا السيرفر بعد", "changes": [], "held": []}
                continue
            if not tok:
                results[l["id"]] = {"ok": False, "error": terr, "changes": [], "held": []}
                continue
            try:
                r = sync_product(tok, l["id"], c, force=force)
            except SallaError as e:
                if e.code == 401 and not retried and _renewable(data_dir):   # رمزٌ أُلغي قبل موعده: يُجدَّد مرةً ويُعاد
                    retried = True
                    try:
                        tok = token(data_dir, now, force=True)
                        r = sync_product(tok, l["id"], c, force=force)
                    except SallaError as e2:
                        r = {"ok": False, "error": str(e2), "changes": [], "held": []}
                else:
                    r = {"ok": False, "error": str(e), "changes": [], "held": []}
            r["sig"] = c["sig"]
            results[l["id"]] = r
        _record(data_dir, results, manual, now)
        if terr:                                 # بلا رمزٍ فالسبب واحد: تنبيهٌ به، لا سطرٌ لكل منتج
            if not manual:
                _alert_auth(data_dir, terr)
        else:                                    # واليدوي يراه المدير أمامه: يُعلَّم ولا يُنبَّه به
            _alert(data_dir, results, links, send=not manual)
        return {"ok": all(r["ok"] and not r.get("held") for r in results.values()),
                "results": results, "n": sum(1 for r in results.values() if r.get("written"))}
    finally:
        _run_lock.release()


def _record(data_dir, results, manual, now):
    def fn(s):
        for pid, r in results.items():
            st = s["state"].setdefault(pid, {})
            st.update(at=now, ok=bool(r["ok"]), error=str(r.get("error") or "")[:300], manual=manual)
            if r.get("name"):
                for l in s["links"]:
                    if l["id"] == pid:
                        l["name"] = r["name"]
                        l["url"] = r.get("url") or l.get("url", "")
            if r.get("held"):
                st.update(held=r["held"][:20], held_sig=r.get("sig", ""))
                continue
            if r["ok"]:
                st.update(sig=r.get("sig", ""), held=[], held_sig="")
                if manual:
                    st["approved"] = True
                if r.get("written"):
                    st.update(changes=r["changes"][:40], put_at=now)
            if r.get("danger"):                  # تغيّر في المنتج ما لم يُطلب: يتوقّف التلقائي حتى يراجعه المدير
                s["on"] = False
                st["sig"] = r.get("sig", "")
        n = sum(1 for r in results.values() if r.get("written"))
        errs = [r["error"] for r in results.values() if r.get("error")]
        s["last"] = {"at": now, "manual": manual, "n": n, "total": len(results),
                     "held": sum(1 for r in results.values() if r.get("held")),
                     "ok": not errs, "error": errs[0][:300] if errs else ""}
    _change(data_dir, fn)


def _alert(data_dir, results, links, send=True):
    """تنبيه المدير بما لم يُكتب وحده (تعليقٌ أو خطأ) — مرةً لكل منتجٍ في كل حال، لا في كل سحب: تعليقٌ باقٍ على سيرفرٍ
    يُسحب كل يوم لا يُنبَّه به كل يوم، ويعود التنبيه إن زال ثم رجع. وsend=False يعلّم الحال بلا تنبيه (اليدوي)."""
    names = {l["id"]: l["name"] or l["id"] for l in links}
    s, lines, marks = _load(data_dir), [], {}
    for pid, r in results.items():
        cond = ("held:" + ",".join(sorted({x["what"] for x in r["held"]}))) if r.get("held") else \
            ("err:" + r["error"]) if r.get("error") else ""
        marks[pid] = cond
        if not cond or cond == (s["state"].get(pid) or {}).get("alerted", ""):
            continue
        if r.get("held"):
            lines.append("• %s: علّقتُه — %s" % (names[pid], "، ".join(
                "%s «%s» ← «%s»" % (WHAT.get(x["what"], ""), x["old"], x["new"]) for x in r["held"][:3])))
        else:
            lines.append("• %s: %s" % (names[pid], r["error"]))

    def fn(x):
        x["alerted"] = ""                        # الرمز يعمل ما دام التحديث وصل سلة
        for pid, cond in marks.items():
            x["state"].setdefault(pid, {})["alerted"] = cond
    _change(data_dir, fn)
    if not lines or not notifier or not send:
        return None
    body = ("لم تُكتب أعداد المحتوى في هذه المنتجات وحدها:\n\n" + "\n".join(lines[:15])
            + "\n\nالتعليق يكون حين يبعد العدد الجديد عمّا في الوصف (أقل من 70% أو أكثر من ضعفه): راجع المعاينة في بطاقة "
              "«أعداد المحتوى في المتجر» ثم «حدّث الآن» إن كان صحيحًا.")
    try:
        return notifier("أعداد المحتوى في المتجر: لم يُحدَّث بعضها", body)
    except Exception:  # noqa: BLE001 — التنبيه لا يُسقط الدورة
        return None


def tick(data_dir, now=None):
    """دورة الخلفية (بعد سحب المحتوى): يُجدَّد الرمز قبل انتهائه — ولو كان التلقائي موقوفًا، فرمز التجديد يموت بعد شهر —
    ثم يُكتب في كل منتجٍ معتمَد تغيّر محتوى سيرفره منذ آخر كتابة. والفاشل يُعاد بعد RETRY، والمعلَّق ينتظر محتوى
    جديدًا أو المدير ← نتيجة التحديث أو None."""
    now = now or time.time()
    a = _load(data_dir)["auth"]
    if a.get("token") and a.get("expires") and float(a["expires"]) - now < RENEW_BEFORE and _renewable(data_dir):
        try:
            token(data_dir, now)
        except SallaError as e:
            _alert_auth(data_dir, str(e))
    s = _load(data_dir)
    if not s["on"] or not s["links"]:
        return None
    cur = _contents(data_dir)
    due = []
    for l in s["links"]:
        c, st = cur.get(l["server"]), s["state"].get(l["id"]) or {}
        if not c or not st.get("approved") or st.get("sig") == c["sig"] or st.get("held_sig") == c["sig"]:
            continue
        if st.get("error") and now - float(st.get("at") or 0) < RETRY:
            continue
        due.append(l["id"])
    return run(data_dir, due, now=now) if due else None


def _alert_auth(data_dir, err):
    key = "auth:" + hashlib.sha1(err.encode()).hexdigest()[:12]
    if _load(data_dir)["alerted"] == key:
        return
    _change(data_dir, lambda x: x.__setitem__("alerted", key))
    if notifier:
        try:
            notifier("أعداد المحتوى في المتجر: رمز سلة", "لم يُجدَّد رمز سلة: %s\n\nبدونه لا تُكتب أعداد المحتوى في "
                     "المنتجات. افتح تطبيقك في متجر سلة (أو أعد تثبيته) فيصل رمزٌ جديد وحده." % err)
        except Exception:  # noqa: BLE001
            pass


# ================= ويبهوك تطبيق سلة: الرمز يصل وحده =================
def app_event(raw):
    """اسم حدث التطبيق (‏app.*) في جسم الويبهوك، أو "" لغيره (الطلبات)."""
    try:
        d = json.loads(raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw or "{}")
    except ValueError:
        return ""
    ev = str(d.get("event") or "") if isinstance(d, dict) else ""
    return ev if ev.startswith("app.") else ""


def verify(data_dir, raw, headers):
    """الويبهوك من تطبيقنا؟ بسرّ ويبهوكه المحفوظ هنا: توقيعًا (‏Signature) أو رمزًا في الترويسة (‏Token) — أيّهما اختير
    في سلة."""
    hook = _dec(data_dir, _load(data_dir)["auth"].get("hook"))
    return bool(hook) and salla_api.verify(hook, hook, raw, headers)


def on_app_event(data_dir, payload):
    """‏app.store.authorize: الرمز ورمز تجديده عند تثبيت التطبيق أو تحديثه ← يُحفظان مشفّرين. و‏app.uninstalled يفصل الربط."""
    ev = str(payload.get("event") or "")
    d = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    now = time.time()
    if ev == "app.store.authorize" and d.get("access_token"):
        try:
            exp = float(d.get("expires") or 0)
        except (TypeError, ValueError):
            exp = 0.0
        exp = exp if exp > now else now + 14 * 86400

        def fn(s):
            a = s["auth"]
            a.update(token=crypto_store.encrypt(str(d["access_token"]), data_dir), expires=exp, source="webhook", at=now,
                     scope=str(d.get("scope") or "")[:500], merchant=str(payload.get("merchant") or "")[:40], error="",
                     renew_fail=0)
            if d.get("refresh_token"):
                a["refresh"] = crypto_store.encrypt(str(d["refresh_token"]), data_dir)
            s["alerted"] = ""
        _change(data_dir, fn)
    elif ev in ("app.uninstalled", "app.store.token.revoked"):
        _change(data_dir, lambda s: s["auth"].update(token="", refresh="", expires=0,
                                                     error="أُزيل التطبيق من المتجر — ثبّته من جديد ليصل الرمز"))
    return ev

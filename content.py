# -*- coding: utf-8 -*-
"""صفحة المحتوى (‏/content): ما في كل سيرفر من مسلسلات بمواسمها وأفلام وقنوات — ليعرف الزائر
المحتوى ويبحث عن مسلسله بالاسم قبل أن يشتري.

لكل سيرفر ملف M3U (كون · كاسبر · سمارت · فالكون، ويضيف المدير غيرها): يُرفع من
admin.ssouq.com/content، أو يُحفظ رابطه فيُسحب منه كل يوم وحده. ويُقرأ سطرًا سطرًا بلا تحميله كله
في الذاكرة:

  • النوع من رابط كل عنصر كما يكتبه Xtream: ‏/series/ حلقة، ‏/movie/ فيلم، وغيرهما قناة — وبلا Xtream
    من الاسم (S01E01) وامتداد الملف.
  • المسلسل وموسمه وحلقته من اسم الحلقة: «Breaking Bad S01 E01» و«1x01» و«الموسم 2 الحلقة 5»
    و«ج3 ح12»؛ فيُعدّ لكل مسلسل مواسمه وحلقات كل موسم (والحلقة المكرّرة بجودتين تُعدّ مرة).
  • الأقسام كما سمّاها السيرفر (‏group-title)، وبادئة اللغة من الاسم تُحذف («AR: » «|EN| »)،
    وسطور الفواصل (‏«##### ARABIC #####») تُتخطّى، وأقسام الكبار تُسقط كلها ولا تُحفظ.

لا يُحفظ من الملف رابطٌ ولا شعار ولا اسم مستخدم: الناتج أسماءٌ وأعداد فقط. ورابط السيرفر (فيه بيانات
الدخول) مشفَّرٌ على القرص ولا يصل المتصفح إلا مخفيًّا.

والصفحة تُرسم على الخادم كلها — الأقسام وأعدادها، وقائمة كل قسم بصفحاتها، والبحث — فتعمل بلا
سكربت؛ وسكربتها الصغير يفتح القسم في مكانه ويبحث مع الكتابة من الواجهات نفسها.

التخزين في data/content/: ‏<السيرفر>.json لكل سيرفر، وsettings.json بالسيرفرات وروابطها وما أخفاه
المدير من أقسام. بلا مكتبات خارجية.
"""
import codecs
import hashlib
import itertools
import json
import os
import re
import socket
import threading
import time
import unicodedata
import zlib
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

import crypto_store
import guide_pages
import league
import tournament

PATH = "/content"
DIR = "content"
SETTINGS = "settings.json"
KINDS = ("series", "movie", "live")
KIND_TAB = {"series": "المسلسلات", "movie": "الأفلام", "live": "القنوات"}
# العدد ومعدوده كما في league.count: واحد، اثنان، جمع 3–10، مفرد 11–99، مفرد المئات
N_SERIES = ("مسلسل واحد", "مسلسلان", "مسلسلات", "مسلسلًا", "مسلسل")
N_SEASONS = ("موسم واحد", "موسمان", "مواسم", "موسمًا", "موسم")
N_EPISODES = ("حلقة واحدة", "حلقتان", "حلقات", "حلقة", "حلقة")
N_MOVIES = ("فيلم واحد", "فيلمان", "أفلام", "فيلمًا", "فيلم")
N_CHANNELS = ("قناة واحدة", "قناتان", "قنوات", "قناة", "قناة")
N_RESULTS = ("نتيجة واحدة", "نتيجتان", "نتائج", "نتيجة", "نتيجة")
N_OF = {"series": N_SERIES, "movie": N_MOVIES, "live": N_CHANNELS}

# السيرفرات كما يسمّيها المتجر، لكلٍّ ملف M3U. المفتاح آخر رابط صفحته (‏/content/smart) ولا يتغيّر،
# والاسم وما تحته يُعدَّلان من صفحة المدير، ويُضاف غيرها منها.
DEFAULT_SERVERS = (
    {"key": "kon", "name": "كون", "full": ""},
    {"key": "casper", "name": "كاسبر", "full": "CASPER FLIX"},
    {"key": "smart", "name": "سمارت", "full": "MR7 TV"},
    {"key": "falcon", "name": "فالكون", "full": "FALCON TV PRO"},
)
MAX_SERVERS = 12
# باقات بطاقة الاشتراك تحت المحتوى، من CATALOG في index.html (مصدر الباقات الوحيد) بترتيبها —
# لسيرفرٍ له باقاتٌ هناك. وغيرها يأخذ «رابط الشراء» من صفحة المدير، أو زرّي الدليل.
PLANS = {"smart": ("p2091471394", "p971439862", "p1112367445"),
         "falcon": ("p479880741", "p2083342610", "p153695876")}
UTM_CAMPAIGN = "content"

REFRESH = 24 * 3600          # الرابط يُسحب مرةً في اليوم
RETRY = 3 * 3600             # وبعد الفشل بعد ثلاث ساعات — والمحتوى السابق باقٍ لا يُمسح
FETCH_TIMEOUT = 90
MAX_BYTES = 1 << 30          # حدّ الملف بعد فكّ ضغطه (1 GB)
NAME_MAX = 150
GROUP_MAX = 100
PAGE = 300                   # عناصر القسم في الصفحة الواحدة وفي كل «عرض المزيد»
SEARCH_MAX = 40              # نتائج البحث المعروضة لكل نوع
QUERY_MAX = 60
UA = "VLC/3.0.20 LibVLC/3.0.20"   # لوحات Xtream تقبل المشغّلات وقد تردّ غيرها

_lock = threading.RLock()     # الإعداد: قراءةٌ ثم كتابة
_busy = {}                    # السيرفر ← {stage, bytes, at} ما دام يُقرأ ملفه
_cache = {}                   # السيرفر ← (البصمة، العرض المشتق)
_found = {}                   # كاش البحث: (السيرفر، البصمة، الكلمات) ← النتيجة


class Busy(Exception):
    """السيرفر يُقرأ ملفه الآن (رفعٌ أو سحب) — فلا قراءتان معًا."""


# ================= قراءة ملف M3U =================
_DIG = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_ATTR = re.compile(r'([A-Za-z][\w-]*)\s*=\s*"([^"]*)"')
_HEAD = re.compile(r'\s*-?\d*(?:\.\d+)?((?:\s*[A-Za-z][\w-]*\s*=\s*"[^"]*")*)\s*,')
_CTRL = re.compile(r"[\x00-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
_VIDEO = (".mp4", ".mkv", ".avi", ".mov", ".m4v", ".wmv", ".flv", ".webm", ".mpg", ".mpeg", ".divx")
# بادئة اللغة أو الجودة في أول الاسم: «AR: » «|EN| » «[TR] » «EN - » — بحروفٍ كبيرة وبفاصل، فلا يُمسّ
# «AL Jazeera» ولا «CSI: Miami» ولا «It: Chapter Two». و«AL» ليست منها: «AL-Arabiya».
_CODES = ("AR|ARA|ARAB|ARABIC|EN|ENG|FR|TR|TUR|DE|ES|IT|NL|PT|RU|IN|PK|KU|KR|FA|IR|US|USA|UK|GB|CA|AU|BR|PL|"
          "SE|NO|DK|FI|GR|MA|DZ|TN|EG|SA|KSA|AE|UAE|KW|QA|BH|OM|IQ|SY|LB|JO|PS|YE|SD|LY|AF|CN|JP|PH|"
          "4K|8K|UHD|FHD|HD|HEVC|VIP|MULTI")
_PREFIX = re.compile(r"^(?:[\[(|]\s*(?:%s)\s*[\])|]\s*[:|\-–•]?|(?:%s)\s*[:|•]|(?:%s)\s+[-–](?=\s))\s*"
                     % (_CODES, _CODES, _CODES))
_TAIL = re.compile(r"[\s\-–_.:|,،(\[]+$")
_WORD = re.compile(r"[^\W_]")
# سطر فاصلٍ بين الأقسام يضعه السيرفر قناةً وهمية: «##### ARABIC #####» «====== BEIN ======»
_SEPLINE = re.compile(r"(?:[#=*~•●★☆■◆▬━─_]\s*){3,}|(?:-\s*){4,}")
# أقسام الكبار تُسقط كلها — بالقسم بمعناه الواسع، وبالاسم بما لا يحتمل غيره
# (فلا يسقط «Sex Education» ولا «Essex» من قسمٍ عادي)
_ADULT_GROUP = re.compile(
    r"(?i)(?:\b(?:adults?|xxx+|porn\w*|erotic\w*|playboy|hustler|brazzers|redlight|dorcel|penthouse|sex|sexy|"
    r"onlyfans|hentai|vixen|bangbros|nsfw)\b|(?<!\d)(?:18|21)\s*\+|\+\s*(?:18|21)(?!\d)|للكبار|كبار\s*فقط|"
    r"إباحي|اباحي|جنسي)")
_ADULT_TITLE = re.compile(
    r"(?i)(?:\b(?:xxx+|porn\w*|brazzers|playboy|hustler|penthouse|onlyfans|hentai|bangbros|nsfw)\b|للكبار|إباحي|اباحي)")

# علامات الحلقة. قبلها فاصلٌ أو أول الاسم، فلا تُقرأ «s» آخر كلمةٍ موسمًا.
_B = r"(?:^|(?<=[\s\-–_.:|,،(\[]))"
_EP_SE = re.compile(_B + r"S(?:eason)?\s*\.?\s*(\d{1,3})\s*[\s\-_.:|,]*\s*E(?:p(?:isode)?)?\s*\.?\s*(\d{1,4})(?!\d)", re.I)
_EP_X = re.compile(r"(?<![\w])(\d{1,2})x(\d{1,3})(?![\w])", re.I)
_AR_ORD = {"الاول": 1, "الأول": 1, "الثاني": 2, "الثانى": 2, "الثالث": 3, "الرابع": 4, "الخامس": 5,
           "السادس": 6, "السابع": 7, "الثامن": 8, "التاسع": 9, "العاشر": 10}
_AR_SEASON = re.compile(_B + r"(?:الموسم|موسم|الجزء|جزء|ج)\s*[:.]?\s*(\d{1,3}|%s)(?![\w])" % "|".join(_AR_ORD))
_AR_EP = re.compile(_B + r"(الحلقة|الحلقه|حلقة|حلقه|ح)\s*[:.]?\s*(\d{1,4})(?!\d)")
_EP_ONLY = re.compile(_B + r"(?:E|Ep|Episode)\s*\.?\s*(\d{1,4})(?!\d)", re.I)
_SEASON_ONLY = re.compile(_B + r"(?:S|Season)\s*\.?\s*(\d{1,3})(?!\d)", re.I)


def _extinf(line):
    """سطر ‏#EXTINF ← (الخصائص، العنوان). الفاصلة بين الخصائص والعنوان أول فاصلةٍ خارج علامتي
    التنصيص — فلا يقطع «Love, Death & Robots» ولا قيمةٌ فيها فاصلة."""
    body = line[8:]
    m = _HEAD.match(body)
    if m:
        return {k.lower(): v for k, v in _ATTR.findall(m.group(1))}, body[m.end():]
    i = body.rfind('",')
    if i >= 0:
        return {k.lower(): v for k, v in _ATTR.findall(body[:i + 1])}, body[i + 2:]
    return {}, body.partition(",")[2]


def _clean(s):
    """الاسم كما يُعرض: بلا محارف تحكّم ولا مسافات زائدة ولا بادئة لغة."""
    s = " ".join(_CTRL.sub("", unicodedata.normalize("NFC", s or "")).split())
    for _ in range(3):
        m = _PREFIX.match(s)
        if not m or m.end() >= len(s):
            break
        s = s[m.end():]
    return s[:NAME_MAX].strip()


def _group(s):
    return " ".join(_CTRL.sub("", unicodedata.normalize("NFC", s or "")).split())[:GROUP_MAX] or "بلا قسم"


def _is_sep(name):
    return bool(_SEPLINE.search(name)) or not _WORD.search(name)


def _tidy(s):
    return _TAIL.sub("", s).strip()


def _episode(title):
    """اسم الحلقة ← (اسم المسلسل، الموسم، الحلقة، علامةٌ قاطعة؟) أو None بلا علامة.
    الموسم 0 = غير مذكور، والحلقة None = غير مذكورة. والقاطعة (S01E01، «الحلقة 5») تجعل العنصر
    حلقةً وإن جاء رابطه فيلمًا — لوحاتٌ قديمة تضع الحلقات أفلامًا."""
    t = title.translate(_DIG)
    m = _EP_SE.search(t)
    if m:
        return t[:m.start()], int(m.group(1)), int(m.group(2)), True
    m = _EP_X.search(t)
    if m:
        return t[:m.start()], int(m.group(1)), int(m.group(2)), False
    ms, me = _AR_SEASON.search(t), _AR_EP.search(t)
    if ms or me:
        cut = min(x.start() for x in (ms, me) if x)
        g = ms.group(1) if ms else ""
        season = (int(g) if g.isdigit() else _AR_ORD.get(g, 0)) if ms else 0
        return t[:cut], season, (int(me.group(2)) if me else None), bool(me and me.group(1) != "ح")
    m = _EP_ONLY.search(t)
    if m:
        return t[:m.start()], 0, int(m.group(1)), False
    m = _SEASON_ONLY.search(t)
    if m:
        return t[:m.start()], int(m.group(1)), None, False
    return None


def _url_kind(url):
    u = url.lower().split("?", 1)[0]
    if "/series/" in u:
        return "series"
    if "/movie/" in u or "/movies/" in u or "/vod/" in u:
        return "movie"
    if "/live/" in u:
        return "live"
    return "file" if u.endswith(_VIDEO) else ""


def _gid(kind, name):
    return hashlib.sha1(f"{kind}|{name}".encode("utf-8")).hexdigest()[:10]


class Parser:
    """يأخذ سطور الملف واحدًا واحدًا (‏line) ويُخرج الفهرس (‏result)."""

    def __init__(self):
        self.pending = None
        self.extgrp = ""
        self.groups = {k: {} for k in KINDS}
        self.n = {k: 0 for k in KINDS}
        self.skipped = {"adult": 0, "sep": 0, "bad": 0}

    def line(self, s):
        s = s.strip()
        if not s:
            return
        if s[0] == "#":
            tag = s[:8].upper()
            if tag == "#EXTINF:":
                self.pending = _extinf(s)
            elif tag == "#EXTGRP:":
                self.extgrp = s[8:].strip()
            return
        if self.pending is None:            # رابطٌ بلا ‏#EXTINF قبله: لا اسم له
            return
        attrs, title = self.pending
        self.pending = None
        self._add(attrs, title, s)

    def _add(self, attrs, title, url):
        name = _clean(title) or _clean(attrs.get("tvg-name", ""))
        group = _group(attrs.get("group-title") or self.extgrp)
        if not name:
            self.skipped["bad"] += 1
            return
        if _ADULT_GROUP.search(group) or _ADULT_TITLE.search(name):
            self.skipped["adult"] += 1
            return
        if _is_sep(name):
            self.skipped["sep"] += 1
            return
        uk = _url_kind(url)
        ep = None if uk == "live" else _episode(name)
        if uk == "series" or (ep and ep[3]):
            kind = "series"
        else:
            kind = "movie" if uk in ("movie", "file") else "live"
        self.n[kind] += 1
        acc = self.groups[kind].setdefault(group, {})
        if kind != "series":
            k = _norm(name)
            if k and k not in acc:
                acc[k] = name
            return
        sname, season, num = (_clean(_tidy(ep[0])), ep[1], ep[2]) if ep else (name, 0, None)
        sname = sname or group
        k = _norm(sname)
        rec = acc.get(k)
        if rec is None:
            rec = acc[k] = [sname, {}]
        eps = rec[1].get(season)
        if eps is None:
            eps = rec[1][season] = [set(), 0]
        if num is None:
            eps[1] += 1
        else:
            eps[0].add(num)

    def result(self):
        out = {"entries": sum(self.n.values()), "n": dict(self.n), "skipped": dict(self.skipped)}
        for kind in KINDS:
            gs = []
            for gname, acc in self.groups[kind].items():
                if kind == "series":
                    items = [[v[0], [[s, len(e[0]) + e[1]] for s, e in sorted(v[1].items())]] for v in acc.values()]
                else:
                    items = list(acc.values())
                if items:
                    gs.append({"id": _gid(kind, gname), "name": gname, "items": items})
            out[kind] = gs
        return out


def _chunks(read, chunk):
    """قطع الملف كما هي، أو مفكوكةً إن كان gzip — وكل قطعةٍ مفكوكة بحدّها، فلا يصير ملفٌّ صغير
    مضغوط جيجاتٍ في الذاكرة دفعةً واحدة."""
    raw = read(chunk)
    if raw[:2] != b"\x1f\x8b":
        while raw:
            yield raw
            raw = read(chunk)
        return
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        while raw:
            data = d.decompress(raw, chunk)
            while True:
                if data:
                    yield data
                if not d.unconsumed_tail:
                    break
                data = d.decompress(d.unconsumed_tail, chunk)
            raw = read(chunk)
        tail = d.flush()
    except zlib.error:
        raise ValueError("الملف المضغوط تالف (gzip)") from None
    if tail:
        yield tail
    if not d.eof:                          # انقطع قبل آخره: لا يُحفظ نصف محتوى على أنه كله
        raise ValueError("الملف المضغوط ناقص — انقطع قبل أن يكتمل")


def iter_lines(read, progress=None, limit=MAX_BYTES, chunk=1 << 20):
    """سطور الملف من دالة قراءة (رفعٌ أو رابط) بلا تحميله كله: UTF-8، ويُفكّ ضغطه إن كان gzip
    (‏.m3u.gz أو ما يضغطه المتصفح قبل الرفع)، وأيّ فاصل أسطر."""
    dec = codecs.getincrementaldecoder("utf-8")(errors="replace")
    buf, total = "", 0
    for data in _chunks(read, chunk):
        total += len(data)
        if total > limit:
            raise ValueError("الملف أكبر من الحد (1 GB)")
        if progress:
            progress(total)
        buf += dec.decode(data)
        if "\r" in buf:                     # و«\r» في آخر القطعة ينتظر: قد يليه «\n» في التالية
            cr = buf.endswith("\r")
            buf = (buf[:-1] if cr else buf).replace("\r\n", "\n").replace("\r", "\n") + ("\r" if cr else "")
        parts = buf.split("\n")
        buf = parts.pop()
        yield from parts
    buf += dec.decode(b"", final=True)
    yield from buf.replace("\r", "\n").split("\n")


def parse(read, progress=None):
    p = Parser()
    for i, line in enumerate(iter_lines(read, progress)):
        if i == 0:
            line = line.lstrip("\ufeff")
        p.line(line)
    return p.result()


# ================= البحث والعدّ =================
_TASHKEEL = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")
_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي"})
_NONW = re.compile(r"[\W_]+")


def _norm(s):
    """للمقارنة والبحث: بلا تشكيل ولا همزات ولا حالة أحرف ولا رموز («Ⅱ» «ᴴᴰ» كما تُقرأ)."""
    s = unicodedata.normalize("NFKC", s or "").translate(_DIG).casefold()
    s = _TASHKEEL.sub("", s).translate(_FOLD)
    return " ".join(_NONW.sub(" ", s).split())


def _count(n, forms):
    one, two, few, many, hundred = forms
    if n == 1:
        return one
    if n == 2:
        return two
    r = n % 100
    return f"{n:,} {few if 3 <= r <= 10 else (many if n < 100 or r > 10 else hundred)}"


def _unit(n, forms):
    """معدود العدد وحده لخانات الأرقام: «3,210» فوق «مسلسلات»."""
    r = n % 100
    return forms[1] if n == 2 else forms[2] if 3 <= r <= 10 else (forms[3] if r > 10 else forms[4])


# ================= التخزين =================
def _dir(data_dir):
    return os.path.join(data_dir, DIR)


def _cat_path(data_dir, key):
    return os.path.join(_dir(data_dir), key + ".json")


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def key_ok(v):
    """مفتاح السيرفر حروفًا لاتينية صغيرة وأرقامًا — آخر رابط صفحته واسم ملفه، فلا يخرج من المجلد."""
    s = str(v or "").strip().lower()
    return s if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,23}", s) else ""


def _float(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _load(data_dir):
    s = _read(os.path.join(_dir(data_dir), SETTINGS))
    rows = s.get("servers") if s and isinstance(s.get("servers"), list) else [dict(x) for x in DEFAULT_SERVERS]
    out, seen = [], set()
    for x in rows:
        k = key_ok(x.get("key")) if isinstance(x, dict) else ""
        if not k or k in seen:
            continue
        seen.add(k)
        out.append({"key": k, "name": str(x.get("name") or k).strip()[:40],
                    "full": str(x.get("full") or "").strip()[:40], "buy": str(x.get("buy") or "").strip()[:500],
                    "url": x.get("url") if isinstance(x.get("url"), str) else "",
                    "hidden": [h for h in (x.get("hidden") or []) if isinstance(h, str)][:5000],
                    "try_at": _float(x.get("try_at")), "error": str(x.get("error") or "")[:300]})
    return out


def _save(data_dir, rows):
    _write(os.path.join(_dir(data_dir), SETTINGS), {"servers": rows})


def servers(data_dir):
    with _lock:
        return _load(data_dir)


def _server(data_dir, key):
    return next((s for s in servers(data_dir) if s["key"] == key), None)


def _update(data_dir, key, **kw):
    with _lock:
        rows = _load(data_dir)
        for r in rows:
            if r["key"] == key:
                r.update(kw)
                _save(data_dir, rows)
                return r
    return None


def _settle(data_dir, key, error, now=None):
    _update(data_dir, key, error=str(error or "")[:300], try_at=now or time.time())


def url_of(data_dir, key):
    s = _server(data_dir, key)
    return crypto_store.decrypt(s["url"], data_dir) if s and s["url"] else ""


def mask_url(url):
    """الرابط كما يراه المدير: السيرفر ومنفذه وحدهما، وما بعدهما (اسم المستخدم وكلمة المرور) مخفي."""
    try:
        p = urlsplit(url)
        return f"{p.scheme}://{p.hostname}{':' + str(p.port) if p.port else ''}/•••" if p.hostname else ""
    except ValueError:
        return ""


# ================= الإدخال: رفعٌ أو رابط =================
def _claim(key, stage):
    with _lock:
        if key in _busy:
            raise Busy()
        _busy[key] = {"stage": stage, "bytes": 0, "at": time.time()}


def _release(key):
    with _lock:
        _busy.pop(key, None)


def ingest(data_dir, key, read, source, label="", claimed=False):
    """يقرأ ملف السيرفر (دالة قراءة) ويحفظ فهرسه ← ملخّصه. ملفٌّ بلا عناصر لا يمسح المحتوى السابق:
    رابطٌ انتهى اشتراكه يردّ قائمةً فارغة أو صفحة خطأ."""
    if not _server(data_dir, key):
        raise ValueError("سيرفر غير معروف")
    if not claimed:
        _claim(key, "read")
    try:
        state = _busy.get(key) or {}
        state["stage"] = "read"
        cat = parse(read, progress=lambda n: state.__setitem__("bytes", n))
        if not cat["entries"]:
            raise ValueError("لا عناصر في الملف (‏#EXTINF) — تأكّد أنه قائمة M3U نفسها لا صفحة خطأ")
        cat.update(v=1, key=key, at=time.time(), source=source, label=str(label or "")[:80])
        _write(_cat_path(data_dir, key), cat)
        _cache.pop(key, None)
        _settle(data_dir, key, "")
        _view(data_dir, key)                    # يُبنى فهرس البحث الآن، فلا ينتظره أول زائر
        return {"entries": cat["entries"], "n": cat["n"], "skipped": cat["skipped"]}
    finally:
        if not claimed:
            _release(key)


def _fetch_error(e):
    if isinstance(e, HTTPError):
        return f"السيرفر ردّ برمز {e.code} — تأكّد أن الاشتراك في الرابط فعّال"
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "انتهت مهلة الاتصال بالسيرفر"
    if isinstance(e, URLError):
        return f"تعذّر الاتصال بالسيرفر ({e.reason})"
    if isinstance(e, ValueError):
        return str(e)
    return f"تعذّر السحب ({type(e).__name__})"


def refresh(data_dir, key, claimed=False, now=None):
    """يسحب ملف السيرفر من رابطه ← (نجح؟، الخطأ). والفشل يُحفظ ليظهر للمدير ويُعاد بعد RETRY،
    والمحتوى السابق باقٍ."""
    if not claimed:
        try:
            _claim(key, "connect")
        except Busy:
            return False, "يُقرأ ملف هذا السيرفر الآن"
    try:
        url = url_of(data_dir, key)
        if not url:
            return False, "لا رابط لهذا السيرفر"
        req = Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
        with urlopen(req, timeout=FETCH_TIMEOUT) as r:
            ingest(data_dir, key, r.read, "url", mask_url(url), claimed=True)
        return True, ""
    except Exception as e:  # noqa: BLE001 — أي فشلٍ يُحفظ نصًّا ويُعاد لاحقًا
        err = _fetch_error(e)
        _settle(data_dir, key, err, now)
        return False, err
    finally:
        _release(key)


def start_refresh(data_dir, key):
    """سحبٌ الآن في الخلفية (زرّ المدير أو رابطٌ جديد) — والحال «يتصل» من لحظته، فتراه الصفحة."""
    if not url_of(data_dir, key):
        raise ValueError("احفظ رابط M3U لهذا السيرفر أولًا")
    _claim(key, "connect")
    threading.Thread(target=refresh, args=(data_dir, key, True), daemon=True).start()


def tick(data_dir, now=None):
    """دورة الخلفية: كل سيرفرٍ له رابط يُسحب إن مرّ يومٌ على آخر محتوى، ولا يُعاد فشلٌ قبل RETRY."""
    now = now or time.time()
    for s in servers(data_dir):
        if not s["url"] or s["key"] in _busy:
            continue
        cat_at = _cat_at(data_dir, s["key"])
        if now - cat_at >= REFRESH and now - s["try_at"] >= RETRY:
            refresh(data_dir, s["key"], now=now)


def _cat_at(data_dir, key):
    """وقت آخر محتوى من وقت ملفه — بلا قراءته، فلا تبني الدورة فهرسَ سيرفرٍ لم يزره أحد."""
    try:
        return os.stat(_cat_path(data_dir, key)).st_mtime
    except OSError:
        return 0.0


# ================= إدارة السيرفرات =================
def set_url(data_dir, key, url):
    url = str(url or "").strip()
    if url and (not url.lower().startswith(("http://", "https://")) or len(url) > 2000 or not mask_url(url)):
        raise ValueError("الرابط يبدأ بـ http:// أو https://")
    if _update(data_dir, key, url=crypto_store.encrypt(url, data_dir) if url else "", error="", try_at=0.0) is None:
        raise ValueError("سيرفر غير معروف")
    return bool(url)


def set_hidden(data_dir, key, gid, hidden):
    with _lock:
        rows = _load(data_dir)
        r = next((x for x in rows if x["key"] == key), None)
        if not r:
            raise ValueError("سيرفر غير معروف")
        gid = str(gid or "")[:20]
        h = [x for x in r["hidden"] if x != gid]
        if hidden and gid:
            h.append(gid)
        r["hidden"] = h
        _save(data_dir, rows)


def save_server(data_dir, form):
    """يضيف سيرفرًا (بلا key قائم) أو يعدّل اسمه وما تحته ورابط شرائه."""
    name = " ".join(str(form.get("name") or "").split())[:40]
    full = " ".join(str(form.get("full") or "").split())[:40]
    buy = str(form.get("buy") or "").strip()[:500]
    if buy and not buy.lower().startswith(("http://", "https://")):
        raise ValueError("رابط الشراء يبدأ بـ https://")
    if not name:
        raise ValueError("اكتب اسم السيرفر")
    raw_key = str(form.get("key") or "").strip()
    key = key_ok(raw_key)
    with _lock:
        rows = _load(data_dir)
        if form.get("new"):
            if raw_key and not key:
                raise ValueError("رابط الصفحة حروفٌ إنجليزية صغيرة وأرقام (مثل kon)")
            if key and any(r["key"] == key for r in rows):
                raise ValueError("هذا الرابط لسيرفرٍ آخر")
            if len(rows) >= MAX_SERVERS:
                raise ValueError(f"الحد {MAX_SERVERS} سيرفرًا")
            taken = {r["key"] for r in rows}
            key = key or next(f"server-{i}" for i in range(1, 100) if f"server-{i}" not in taken)
            rows.append({"key": key, "name": name, "full": full, "buy": buy, "url": "", "hidden": [],
                         "try_at": 0.0, "error": ""})
        else:
            r = next((r for r in rows if r["key"] == key), None)
            if not r:
                raise ValueError("سيرفر غير معروف")
            r.update(name=name, full=full, buy=buy)
        _save(data_dir, rows)
        return key


def move_server(data_dir, key, step):
    with _lock:
        rows = _load(data_dir)
        i = next((n for n, r in enumerate(rows) if r["key"] == key), -1)
        j = i + (1 if step > 0 else -1)
        if i >= 0 and 0 <= j < len(rows):
            rows[i], rows[j] = rows[j], rows[i]
            _save(data_dir, rows)


def clear(data_dir, key, drop=False):
    """يمسح محتوى السيرفر ورابطه (فتختفي صفحته)، و`drop` يحذف السيرفر نفسه من القائمة."""
    with _lock:
        if key in _busy:
            raise Busy()
        rows = _load(data_dir)
        rows = [r for r in rows if r["key"] != key] if drop else rows
        for r in rows:
            if r["key"] == key:
                r.update(url="", error="", try_at=0.0, hidden=[])
        _save(data_dir, rows)
        try:
            os.remove(_cat_path(data_dir, key))
        except OSError:
            pass
        _cache.pop(key, None)


# ================= العرض المشتق (للصفحة والبحث) =================
def _view(data_dir, key):
    """← (السيرفر، العرض): أقسامه الظاهرة وأعداده وفهرس البحث — يُبنى مرةً لكل نسخةٍ من الملف
    وما أُخفي منه، ويبقى في الذاكرة."""
    srv = _server(data_dir, key)
    if not srv:
        return None, None
    try:
        st = os.stat(_cat_path(data_dir, key))
    except OSError:
        return srv, None
    sig = (st.st_mtime_ns, st.st_size, tuple(srv["hidden"]))
    c = _cache.get(key)
    if c and c[0] == sig:
        return srv, c[1]
    cat = _read(_cat_path(data_dir, key))
    if not cat:
        return srv, None
    v = _build(cat, set(srv["hidden"]))
    _cache[key] = (sig, v)
    return srv, v


_versions = itertools.count(1)       # رقمٌ لكل عرضٍ يُبنى — مفتاح كاش البحث


def _build(cat, hidden):
    v = {"at": float(cat.get("at") or 0), "cat": cat, "kinds": {}, "byid": {}, "index": {}, "ver": next(_versions)}
    for kind in KINDS:
        gs = [g for g in cat.get(kind) or [] if g.get("id") not in hidden and g.get("items")]
        v["kinds"][kind] = gs
        v["byid"][kind] = {g["id"]: i for i, g in enumerate(gs)}
        v["index"][kind] = [(_norm(it[0] if kind == "series" else it), gi, ii)
                            for gi, g in enumerate(gs) for ii, it in enumerate(g["items"])]
    ser = {}
    for k, gi, ii in v["index"]["series"]:
        d = ser.setdefault(k, {})
        for s, n in v["kinds"]["series"][gi]["items"][ii][1]:
            if n > d.get(s, 0):
                d[s] = n
    v["counts"] = {"series": len(ser), "seasons": sum(len(d) for d in ser.values()),
                   "episodes": sum(sum(d.values()) for d in ser.values()),
                   "movie": len({x[0] for x in v["index"]["movie"]}),
                   "live": len({x[0] for x in v["index"]["live"]})}
    return v


def _has(v):
    return bool(v) and any(v["counts"][k] for k in KINDS)


def _words(q):
    words = _norm(q).split()
    return words if len("".join(words)) >= 2 else []


def _search(key, v, q):
    """← ({النوع: ([(القسم، العنصر)] أولها SEARCH_MAX، عددها كله)}، المجموع). كل كلمةٍ من البحث في الاسم؛
    والمطابق تمامًا أولًا ثم ما يبدأ بها ثم ما فيه. ويُحفظ الأول وحده، فلا يملأ الذاكرةَ بحثٌ واسع
    كـ«ال»."""
    words = _words(q)
    if not words:
        return {k: ([], 0) for k in KINDS}, 0
    ck = (key, v["ver"], tuple(words))
    if ck in _found:
        return _found[ck]
    full = " ".join(words)
    out, total = {}, 0
    for kind in KINDS:
        tiers, n = ([], [], []), 0
        for norm, gi, ii in v["index"][kind]:
            if all(w in norm for w in words):
                n += 1
                t = tiers[0 if norm == full else 1 if norm.startswith(full) else 2]
                if len(t) < SEARCH_MAX:
                    t.append((gi, ii))
        out[kind] = ((tiers[0] + tiers[1] + tiers[2])[:SEARCH_MAX], n)
        total += n
    if len(_found) > 500:
        _found.clear()
    _found[ck] = (out, total)
    return out, total


# ================= الرسم =================
_esc = league._esc


def _series_li(item, group=None):
    name, seasons = item
    known = [(s, n) for s, n in seasons if s]
    eps = sum(n for _, n in seasons)
    meta = (f"{_count(len(seasons), N_SEASONS)} · {_count(eps, N_EPISODES)}" if known
            else _count(eps, N_EPISODES))
    chips = "".join(f'<span>{f"الموسم {s}" if s else "بلا موسم"} <i>({_count(n, N_EPISODES)})</i></span>'
                    for s, n in seasons) if known else ""
    grp = f' <small class="cgn">· {_esc(group)}</small>' if group else ""
    return (f'<li><b>{_esc(name)}</b>{grp}<small class="cm">{meta}</small>'
            + (f'<span class="ss">{chips}</span>' if chips else "") + "</li>")


def _flat_li(name, group=None):
    return f'<li>{_esc(name)}' + (f' <small class="cgn">· {_esc(group)}</small>' if group else "") + "</li>"


def _items_html(kind, items):
    return "".join(_series_li(it) if kind == "series" else _flat_li(it) for it in items)


def _ul(kind, inner):
    return f'<ul class="ci{"" if kind == "series" else " flat"}">{inner}</ul>'


def _more_btn(kind, n_left, page):
    return (f'<button class="cmore" type="button" data-p="{page}">عرض المزيد — بقي '
            f'{_count(n_left, N_OF[kind])}</button>') if n_left > 0 else ""


def _slice(g, page):
    items = g["items"]
    page = max(1, min(page, (len(items) + PAGE - 1) // PAGE or 1))
    part = items[(page - 1) * PAGE:page * PAGE]
    return page, part, max(0, len(items) - page * PAGE)


def api_group(data_dir, key, kind, gid, page=1):
    """عناصر قسمٍ صفحةً صفحة لفتحه في مكانه ← dict أو None."""
    srv, v = _view(data_dir, key)
    if kind not in KINDS or not v or gid not in v["byid"][kind]:
        return None
    g = v["kinds"][kind][v["byid"][kind][gid]]
    page, part, left = _slice(g, page)
    return {"ok": True, "kind": kind, "items": _items_html(kind, part), "more": _more_btn(kind, left, page + 1)}


def _results_html(data_dir, key, srv, v, q):
    """نتائج البحث بالاسم: لكل نوعٍ أوّل SEARCH_MAX بقسمها (والمسلسل بمواسمه)، ثم أين يوجد الاسم
    في السيرفرات الأخرى — فمن لم يجد مسلسله هنا يعرف أيّ اشتراكٍ فيه."""
    q = " ".join(str(q or "").split())[:QUERY_MAX]
    if not _words(q):
        return ""
    hits, total = _search(key, v, q)
    parts = []
    for kind in KINDS:
        top, n = hits[kind]
        if not n:
            continue
        gs = v["kinds"][kind]
        lis = "".join(_series_li(gs[gi]["items"][ii], gs[gi]["name"]) if kind == "series"
                      else _flat_li(gs[gi]["items"][ii], gs[gi]["name"]) for gi, ii in top)
        more = (f'<p class="sub">و{_count(n - len(top), N_RESULTS)} أخرى — اكتب الاسم أدقّ.</p>'
                if n > len(top) else "")
        parts.append(f'<h3>{KIND_TAB[kind]} <small>({n:,})</small></h3>{_ul(kind, lis)}{more}')
    elsewhere = []
    for s in servers(data_dir):
        ov = _view(data_dir, s["key"])[1] if s["key"] != key else None
        n = _search(s["key"], ov, q)[1] if _has(ov) else 0
        if n:
            elsewhere.append(f'<a class="link" href="{PATH}/{s["key"]}?q={quote(q)}">{_esc(s["name"])} ({n:,})</a>')
    other = (f'<p class="cother">{"ويوجد أيضًا في" if total else "لكنه موجود في"}: {" · ".join(elsewhere)}</p>'
             if elsewhere else "")
    if not total:
        return (f'<section class="card cres"><h2>لا يوجد «{_esc(q)}» في {_esc(srv["name"])}</h2>'
                + (other or '<p class="sub">جرّب جزءًا من الاسم، أو اكتبه بالإنجليزية أو بالعربية.</p>')
                + "</section>")
    return (f'<section class="card cres"><h2>نتائج «{_esc(q)}» في {_esc(srv["name"])} '
            f'<small>{_count(total, N_RESULTS)}</small></h2>{"".join(parts)}{other}</section>')


def api_search(data_dir, key, q):
    srv, v = _view(data_dir, key)
    if not _has(v):
        return None
    return {"ok": True, "html": _results_html(data_dir, key, srv, v, q)}


def _stats(c):
    tiles = [(c["series"], N_SERIES), (c["seasons"], N_SEASONS), (c["episodes"], N_EPISODES),
             (c["movie"], N_MOVIES), (c["live"], N_CHANNELS)]
    return '<div class="cstats">' + "".join(
        f'<div><b>{n:,}</b><small>{_unit(n, f)}</small></div>' for n, f in tiles if n) + "</div>"


def _summary_text(c):
    """«3,210 مسلسلات بمواسمها و45,678 فيلمًا و4,321 قناة» — بما في السيرفر وحده."""
    bits = [f"{_count(c['series'], N_SERIES)} بمواسمها" if c["series"] else "",
            _count(c["movie"], N_MOVIES) if c["movie"] else "", _count(c["live"], N_CHANNELS) if c["live"] else ""]
    return " و".join(b for b in bits if b)


def _utm(url):
    """روابط المتجر بحملة هذه الصفحة لتُعرف المبيعات منها، وغيرها كما هي."""
    host = (urlsplit(url).hostname or "").lower()
    if host != "ssouq.com" and not host.endswith(".ssouq.com"):
        return url
    if "utm_campaign=" in url:
        return re.sub(r"utm_campaign=[^&#]*", "utm_campaign=" + UTM_CAMPAIGN, url)
    return (url + ("&" if "?" in url else "?")
            + "utm_source=guide.ssouq.com&utm_medium=referral&utm_campaign=" + UTM_CAMPAIGN)


def _cta(srv):
    """بطاقة الاشتراك تحت المحتوى: رابط شراء السيرفر من صفحة المدير، أو باقاته من CATALOG، أو الدليل."""
    name = _esc(srv["name"])
    rows = []
    if not srv["buy"]:
        plans = {p["id"]: p for b in tournament._catalog().values() for p in b.get("plans", [])}
        for pid in PLANS.get(srv["key"], ()):
            p = plans.get(pid)
            if not p:
                continue
            was = f'<s>{_esc(p["was"])} ر.س</s>' if p.get("was") else ""
            rows.append(
                f'<a class="planrow" href="{_esc(_utm(p["url"]))}" target="_blank" rel="noopener">'
                f'<img src="{_esc(p["img"])}" alt="" width="46" height="46" loading="lazy">'
                f'<span class="who"><b>{_esc(p["name"])}</b><small>{_esc(p.get("tag") or p.get("desc") or "")}</small></span>'
                f'<span class="money">{_esc(p["price"])} ر.س{was}</span></a>')
    buy = (f'<a class="btn buy" href="{_esc(_utm(srv["buy"]))}" target="_blank" rel="noopener">اشترك في {name}</a>'
           if srv["buy"] else "")
    return (f'<section class="card ccta"><h2>اشترك في {name}</h2>'
            '<p class="sub">دفعة واحدة بلا تجديد تلقائي، وتفعيل خلال دقائق، ودعم فني مباشر على واتساب.</p>'
            + (f'<div class="planlist">{"".join(rows)}</div>' if rows else "") + buy
            + '<div class="nav"><a class="btn go" href="/#buy">ساعدني في الاختيار</a>'
            '<a class="btn ghost" href="/#plans">كل الباقات</a></div></section>')


CSS = """
nav.crumb{font-size:14px;opacity:.75;margin:0 0 14px}
.cstats{display:grid;grid-template-columns:repeat(auto-fit,minmax(92px,1fr));gap:8px;margin:0 0 14px}
.cstats div{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:10px 6px;text-align:center}
.cstats b{display:block;font-size:1.2rem;line-height:1.35;color:var(--brand-text);font-variant-numeric:tabular-nums}
.cstats small{color:var(--mute);font-size:.76rem}
.csearch{display:flex;gap:8px;margin:0 0 14px}
.csearch input{flex:1;min-width:0;padding:12px 14px;border:1.5px solid var(--line);border-radius:12px;
  background:var(--card);color:var(--ink);font:inherit}
.csearch input:focus{outline:none;border-color:var(--brand)}
.csearch .btn{flex:0 0 auto;padding:12px 18px}
.cres h2{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px;font-size:1.1rem}
.cres h2 small,.cres h3 small{color:var(--mute);font-weight:400;font-size:.8rem}
.cres h3{font-size:1rem;margin:14px 0 2px}
.cother{margin:12px 0 0}
.ltabs{flex-wrap:wrap;overflow:visible;padding-inline-end:0;-webkit-mask-image:none;mask-image:none}
.ckinds small{opacity:.8;font-weight:400;margin-inline-start:5px}
.cg{border-top:1px solid var(--line)}
.cg:first-child{border-top:0}
.cg summary{display:flex;align-items:center;gap:10px;padding:12px 2px;cursor:pointer;list-style:none;font-weight:600}
.cg summary::-webkit-details-marker{display:none}
.cg summary::after{content:"";flex:0 0 auto;width:8px;height:8px;margin-inline-start:4px;border-right:2px solid var(--mute);
  border-bottom:2px solid var(--mute);transform:rotate(45deg);transition:transform .15s}
.cg[open] summary::after{transform:rotate(-135deg)}
.cg summary span{flex:1;min-width:0;overflow-wrap:anywhere}
.cg summary small{color:var(--mute);font-weight:400;font-size:.8rem;white-space:nowrap}
.cgb{padding:0 0 12px}
ul.ci{list-style:none;margin:0;padding:0}
ul.ci li{padding:9px 0;border-top:1px dashed var(--line);overflow-wrap:anywhere}
ul.ci li:first-child{border-top:0}
ul.ci li b{font-weight:600}
ul.ci .cm{display:block;color:var(--mute);font-size:.78rem}
ul.ci .cgn{color:var(--mute);font-size:.76rem}
.ss{display:flex;flex-wrap:wrap;gap:5px;margin-top:6px}
.ss span{font-size:.74rem;background:var(--soft);border-radius:999px;padding:3px 10px;white-space:nowrap}
.ss i{font-style:normal;color:var(--mute)}
ul.ci.flat{columns:2 170px;column-gap:18px}
ul.ci.flat li{break-inside:avoid;padding:6px 0;font-size:.9rem}
.cmore{display:block;width:100%;margin-top:8px;padding:10px;border:1.5px solid var(--line);border-radius:12px;
  background:transparent;color:var(--brand-text);font:inherit;font-weight:600;cursor:pointer}
.cmore:hover{border-color:var(--brand)}
.cpager{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-top:12px;font-size:.9rem}
.cempty{color:var(--mute);font-size:.8rem;font-weight:400}
.cmiss{margin:4px 0 0;padding-inline-start:20px;line-height:2}
.ccta .planlist{margin:12px 0}
.ccta a.planrow{text-decoration:none}
.ccta .btn.buy{display:block;margin:4px 0 0}
#cres[aria-busy="true"]{opacity:.5}
"""

JS = """
(function(){
  var K = document.body.getAttribute("data-server");
  function $(s, r){ return (r || document).querySelector(s); }
  function load(det, p){
    var box = $(".cgb", det);
    return fetch("/api/content/group?s=" + K + "&t=" + det.getAttribute("data-t") + "&g=" + det.getAttribute("data-g") + "&p=" + p)
      .then(function(r){ return r.json(); })
      .then(function(d){
        if (!d || !d.ok) throw 0;
        var ul = $("ul.ci", box);
        if (!ul) { box.innerHTML = '<ul class="ci' + (d.kind === "series" ? "" : " flat") + '"></ul>'; ul = $("ul.ci", box); }
        ul.insertAdjacentHTML("beforeend", d.items);
        var old = $(".cmore", box); if (old) old.remove();
        if (d.more) box.insertAdjacentHTML("beforeend", d.more);
      })
      .catch(function(){ var b = $(".cmore", box); if (b) b.disabled = false; });
  }
  document.addEventListener("toggle", function(e){
    var det = e.target;
    if (!det.classList || !det.classList.contains("cg") || !det.open || det.getAttribute("data-done")) return;
    det.setAttribute("data-done", "1"); load(det, 1);
  }, true);
  document.addEventListener("click", function(e){
    var b = e.target.closest && e.target.closest(".cmore[data-p]"); if (!b) return;
    e.preventDefault(); b.disabled = true; load(b.closest(".cg"), b.getAttribute("data-p"));
  });
  var f = $(".csearch"); if (!f) return;
  var inp = f.elements.q, box = document.getElementById("cres"), timer = 0, last = inp.value.trim(), seq = 0;
  function run(){
    var v = inp.value.trim(); if (v === last) return; last = v;
    try { history.replaceState(null, "", v ? "?q=" + encodeURIComponent(v) : location.pathname); } catch (e) {}
    if (v.replace(/\\s/g, "").length < 2) { box.innerHTML = ""; return; }
    var n = ++seq; box.setAttribute("aria-busy", "true");
    fetch("/api/content/search?s=" + K + "&q=" + encodeURIComponent(v))
      .then(function(r){ return r.json(); })
      .then(function(d){ if (n === seq && d && d.ok) box.innerHTML = d.html; })
      .catch(function(){})
      .then(function(){ if (n === seq) box.removeAttribute("aria-busy"); });
  }
  inp.addEventListener("input", function(){ clearTimeout(timer); timer = setTimeout(run, 250); });
  f.addEventListener("submit", function(e){ e.preventDefault(); clearTimeout(timer); last = null; run(); });
})();
"""


def _doc(title, desc, url, index, crumb, body, key=""):
    """الصفحة كاملة. ‏`index` للصفحة الرئيسية للسيرفر وحدها؛ والقسم والبحث وما بعد الصفحة الأولى
    لا تُفهرس ولا canonical لها (فلا تتعارض الإشارتان)."""
    site = guide_pages.SITE
    crumbs = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "دليل سمارت سوق", "item": site + "/"},
        {"@type": "ListItem", "position": 2, "name": title.split(" | ")[0].split(":")[0], "item": url}]}
    robots = ('<meta name="robots" content="index, follow, max-snippet:-1">\n<link rel="canonical" href="%s">' % url
              if index else '<meta name="robots" content="noindex, follow">')
    return f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
<meta name="description" content="{_esc(desc)}">
{robots}
<meta name="theme-color" content="#004D73" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0B1826" media="(prefers-color-scheme: dark)">
<meta name="color-scheme" content="light dark">
<meta property="og:type" content="website">
<meta property="og:locale" content="ar_SA">
<meta property="og:site_name" content="سمارت سوق">
<meta property="og:title" content="{_esc(title)}">
<meta property="og:description" content="{_esc(desc)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{site}/static/og-image.png">
<link rel="icon" href="/favicon.ico">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<script type="application/ld+json">{json.dumps(crumbs, ensure_ascii=False)}</script>
<style>{guide_pages._style()}
{CSS}</style>
</head>
<body data-server="{_esc(key)}">
<main id="view">
<nav class="crumb"><a class="link" href="/">دليل سمارت سوق</a> ← {crumb}</nav>
{body}
</main>
<script>{JS}</script>
</body>
</html>""".encode("utf-8")


def first_key(data_dir):
    """أول سيرفرٍ له محتوى — إليه يذهب ‏/content."""
    for s in servers(data_dir):
        if _has(_view(data_dir, s["key"])[1]):
            return s["key"]
    return ""


def _tabs(data_dir, key):
    shown = [s for s in servers(data_dir) if s["key"] == key or _has(_view(data_dir, s["key"])[1])]
    if len(shown) < 2:
        return ""
    return ('<nav class="ltabs" aria-label="السيرفرات">' + "".join(
        f'<a href="{PATH}/{s["key"]}"{" aria-current=page" if s["key"] == key else ""}>{_esc(s["name"])}</a>'
        for s in shown) + "</nav>")


def render_missing(data_dir, key=""):
    """لا محتوى بعد (أو سيرفرٌ لا وجود له): صفحةٌ تدلّ على ما وُجد، لا تُفهرس ← (404، بايتات)."""
    others = [s for s in servers(data_dir) if s["key"] != key and _has(_view(data_dir, s["key"])[1])]
    links = "".join(f'<li><a class="link" href="{PATH}/{s["key"]}">محتوى {_esc(s["name"])}</a></li>' for s in others)
    body = ('<h1>محتوى الاشتراكات</h1><section class="card"><p>لم يُنشر محتوى هذا السيرفر بعد.</p>'
            + (f'<p class="sub">وهذه السيرفرات منشورٌ محتواها:</p><ul class="cmiss">{links}</ul>' if links else "")
            + '<div class="nav"><a class="btn go" href="/#buy">ساعدني في الاختيار</a>'
            '<a class="btn ghost" href="/">الدليل</a></div></section>')
    return 404, _doc("محتوى الاشتراكات | سمارت سوق", "المسلسلات بمواسمها والأفلام والقنوات في كل اشتراك.",
                     guide_pages.SITE + PATH, False, "المحتوى", body)


def render(data_dir, key, query):
    """صفحة السيرفر ← (رمز HTTP، بايتات، ثواني الكاش). ‏query: t النوع، g القسم، p الصفحة، q البحث."""
    srv, v = _view(data_dir, key)
    if not srv or not _has(v):
        code, body = render_missing(data_dir, key)
        return code, body, 300
    c, name = v["counts"], srv["name"]
    kinds = [k for k in KINDS if v["kinds"][k]]
    kind = query.get("t") if query.get("t") in kinds else kinds[0]
    gid, q = str(query.get("g") or ""), " ".join(str(query.get("q") or "").split())[:QUERY_MAX]
    try:
        page = int(query.get("p") or 1)
    except ValueError:
        page = 1
    base, url = f"{PATH}/{key}", guide_pages.SITE + f"{PATH}/{key}"
    summary = _summary_text(c)
    full = f' <span class="season" dir="ltr">{_esc(srv["full"])}</span>' if srv["full"] else ""
    head = (f'<h1>محتوى اشتراك {_esc(name)}{full}</h1>'
            f'<p class="sub">{_esc(summary)} — من قائمة الاشتراك نفسها، لتعرف ما ستشاهده وتبحث عن مسلسلك '
            f'بالاسم قبل أن تشتري.</p>' + _tabs(data_dir, key) + _stats(c)
            + f'<form class="csearch" role="search" action="{base}" method="get">'
            f'<input type="search" name="q" value="{_esc(q)}" placeholder="ابحث عن مسلسل أو فيلم" '
            f'aria-label="ابحث باسم المسلسل أو الفيلم أو القناة في محتوى {_esc(name)}" autocomplete="off" enterkeyhint="search" maxlength="{QUERY_MAX}">'
            f'<button class="btn go" type="submit">بحث</button></form>'
            f'<div id="cres" aria-live="polite">{_results_html(data_dir, key, srv, v, q) if q else ""}</div>')
    at = datetime_label(v["at"])
    code, index = 200, not (q or gid or query.get("t") or query.get("p"))
    ktabs = ('<nav class="ltabs ckinds" aria-label="نوع المحتوى">' + "".join(
        f'<a href="{base}?t={k}"{" aria-current=page" if k == kind else ""}>{KIND_TAB[k]}'
        f'<small>{c[k]:,}</small></a>' for k in kinds) + "</nav>")
    gi = v["byid"][kind].get(gid) if gid else None
    if gid and gi is None:
        code = 404
    if gi is not None:
        g = v["kinds"][kind][gi]
        page, part, left = _slice(g, page)
        pages = (len(g["items"]) + PAGE - 1) // PAGE
        pager = ""
        if pages > 1:
            prev = (f'<a class="link" href="{base}?t={kind}&amp;g={gid}&amp;p={page - 1}">→ السابق</a>'
                    if page > 1 else "<span></span>")
            nxt = (f'<a class="link" href="{base}?t={kind}&amp;g={gid}&amp;p={page + 1}">التالي ←</a>'
                   if left else "<span></span>")
            pager = f'<nav class="cpager">{prev}<span>صفحة {page} من {pages}</span>{nxt}</nav>'
        browse = (f'<section class="card"><nav class="crumb"><a class="link" href="{base}?t={kind}">{KIND_TAB[kind]}</a>'
                  f' ← {_esc(g["name"])}</nav><h2>{_esc(g["name"])} <small class="cempty">'
                  f'{_count(len(g["items"]), N_OF[kind])}</small></h2>{_ul(kind, _items_html(kind, part))}{pager}</section>')
    else:
        rows = "".join(
            f'<details class="cg" data-t="{kind}" data-g="{g["id"]}"><summary><span>{_esc(g["name"])}</span>'
            f'<small>{_count(len(g["items"]), N_OF[kind])}</small></summary><div class="cgb">'
            f'<a class="link" href="{base}?t={kind}&amp;g={g["id"]}">اعرض القائمة</a></div></details>'
            for g in v["kinds"][kind])
        miss = '<p class="sub">هذا القسم لم يعد موجودًا، واختر من الأقسام الحالية.</p>' if code == 404 else ""
        browse = (f'<section class="card">{ktabs}{miss}<div class="cgroups">{rows}</div>'
                  f'<p class="lsrc">آخر تحديث: {at} بتوقيت السعودية · من قائمة الاشتراك نفسها</p></section>')
    what = " و".join(x for k, x in (("series", "المسلسلات بمواسمها"), ("movie", "الأفلام"), ("live", "القنوات"))
                     if c[k])
    title = f"محتوى اشتراك {name}: {what} | سمارت سوق"
    desc = (f"ما في اشتراك {name} قبل أن تشتري: {summary}. ابحث بالاسم عن أي مسلسل أو فيلم أو قناة"
            + (" واعرف مواسم المسلسل وحلقات كل موسم" if c["series"] else "")
            + ". يُحدَّث تلقائيًا من قائمة الاشتراك نفسها.")
    crumb = (f'<a class="link" href="{base}">محتوى {_esc(name)}</a>' if (gi is not None or q)
             else f"محتوى {_esc(name)}")
    body = head + browse + _cta(srv)
    return code, _doc(title, desc, url, index and code == 200, crumb, body, key), 600


def datetime_label(ts):
    return league._when(ts) if ts else ""


# ================= الواجهات الأخرى =================
def brief(data_dir):
    """للرئيسية ومسار الشراء: السيرفرات التي لها محتوى وأعدادها."""
    out = []
    for s in servers(data_dir):
        v = _view(data_dir, s["key"])[1]
        if _has(v):
            out.append({"key": s["key"], "name": s["name"], "url": f"{PATH}/{s['key']}", "at": int(v["at"]),
                        "series": v["counts"]["series"], "seasons": v["counts"]["seasons"],
                        "episodes": v["counts"]["episodes"], "movies": v["counts"]["movie"],
                        "channels": v["counts"]["live"]})
    return {"ok": True, "servers": out}


def sitemap(data_dir):
    return [(f"{PATH}/{s['key']}", "daily", "0.7") for s in servers(data_dir)
            if _has(_view(data_dir, s["key"])[1])]


def admin_state(data_dir):
    """صفحة المدير: كل سيرفر بحاله وأعداده وأقسامه كلها (المخفية معلَّمة) — ورابطه مخفيًّا."""
    out = []
    for s in servers(data_dir):
        v = _view(data_dir, s["key"])[1]
        cat = v["cat"] if v else {}
        hidden = set(s["hidden"])
        url = crypto_store.decrypt(s["url"], data_dir) if s["url"] else ""
        out.append({
            "key": s["key"], "name": s["name"], "full": s["full"], "buy": s["buy"], "page": f"{PATH}/{s['key']}",
            "has": _has(v), "at": v["at"] if v else 0, "source": cat.get("source", ""), "label": cat.get("label", ""),
            "counts": v["counts"] if v else None, "entries": cat.get("entries", 0), "n": cat.get("n", {}),
            "skipped": cat.get("skipped", {}), "url": mask_url(url) if url else "", "try_at": s["try_at"],
            "error": s["error"], "busy": dict(_busy[s["key"]]) if s["key"] in _busy else None,
            "groups": {k: [[g["id"], g["name"], len(g["items"]), g["id"] in hidden] for g in cat.get(k) or []]
                       for k in KINDS}})
    return {"servers": out, "refresh_hours": REFRESH // 3600}

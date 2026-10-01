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
    وسطور الفواصل (‏«##### ARABIC #####») تُتخطّى، وأقسام الكبار تُسقط كلها فلا تُنشر.

لا يُحفظ من الملف رابطٌ ولا شعار ولا اسم مستخدم: الناتج أسماءٌ وأعداد فقط. ورابط السيرفر (فيه بيانات
الدخول) مشفَّرٌ على القرص ولا يصل المتصفح إلا مخفيًّا.

وما أُسقط للكبار يُحفظ للمدير وحده في ملفٍ مستقل لا تقرؤه الصفحة العامة: أقسامٌ حُذفت كلها بعددها،
وأسماءٌ حُذفت من أقسامٍ عادية (قد يكون بينها فيلمٌ عادي)، وأفلامٌ علّمتها واجهة السيرفر للكبار. وإن ظهر في سحبٍ ما لم يكن في سابقه وصل
المديرَ تنبيهٌ به بالبريد وواتساب (‏notifier يضبطه الخادم).

وكل سحبٍ يُقارن بما رُئي من ملف السيرفر قبله فيُسجَّل ما جدّ فيه: أفلامٌ ومسلسلاتٌ جديدة، ومواسمُ وحلقاتٌ جديدة
لمسلسلاتٍ قائمة. ومنه منشور «أضيف مؤخرًا» في قناة واتساب كل يومٍ في ساعته (‏channel_sender يضبطه الخادم).

والصفحة تُرسم على الخادم كلها — الأقسام وأعدادها، وقائمة كل قسم بصفحاتها، والبحث — فتعمل بلا
سكربت؛ وسكربتها الصغير يفتح القسم في مكانه ويبحث مع الكتابة من الواجهات نفسها.

التخزين في data/content/: ‏<السيرفر>.json لكل سيرفر، و‏<السيرفر>.adult.json بما أُسقط منه للكبار،
و‏<السيرفر>.seen.json بما رُئي منه و‏<السيرفر>.news.json بما جدّ فيه سحبًا بعد سحب، و‏<السيرفر>.sum.json بملخّصه (أعداده
وأقسامه) فتُفتح صفحة المدير بلا قراءة فهرسه الكبير، وsettings.json بالسيرفرات وروابطها وما أخفاه المدير من أقسام ومن يصله
التنبيه وقناة واتساب. بلا مكتبات خارجية.
"""
import bisect
import codecs
import hashlib
import io
import ipaddress
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
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

import crypto_store
import guide_pages

PATH = "/content"
PATH_EN = "/en/content"      # الصفحة نفسها بالإنجليزية (‏content_page)، وصورها من ‏PATH
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
N_ITEMS = ("عنصر واحد", "عنصران", "عناصر", "عنصرًا", "عنصر")
N_OF = {"series": N_SERIES, "movie": N_MOVIES, "live": N_CHANNELS}

# السيرفرات كما يسمّيها المتجر، لكلٍّ ملف M3U. المفتاح آخر رابط صفحته (‏/content/smart) ولا يتغيّر،
# والاسم وما تحته واسمه بالإنجليزية (‏en، للصفحة الإنجليزية) تُعدَّل من صفحة المدير، ويُضاف غيرها منها.
DEFAULT_SERVERS = (
    {"key": "kon", "name": "كون", "full": "", "en": "Kon"},
    {"key": "casper", "name": "كاسبر", "full": "CASPER FLIX", "en": "Casper"},
    {"key": "smart", "name": "سمارت", "full": "MR7 TV", "en": "Smart"},
    {"key": "falcon", "name": "فالكون", "full": "FALCON TV PRO", "en": "Falcon"},
)
EN_NAMES = {s["key"]: s["en"] for s in DEFAULT_SERVERS}   # وللسيرفر الافتراضي المحفوظ قبل الاسم الإنجليزي
MAX_SERVERS = 12
# باقات بطاقة الاشتراك تحت المحتوى، من CATALOG في index.html (مصدر الباقات الوحيد) بترتيبها —
# لسيرفرٍ له باقاتٌ هناك. وغيرها يأخذ «رابط الشراء» من صفحة المدير، أو زرّي الدليل.
PLANS = {"smart": ("p2091471394", "p971439862", "p1112367445"),
         "falcon": ("p479880741", "p2083342610", "p153695876"),
         "casper": ("p1147637724", "p1557813796")}
UTM_CAMPAIGN = "content"

REFRESH = 24 * 3600          # الرابط يُسحب مرةً في اليوم
RETRY = 3 * 3600             # وبعد الفشل بعد ثلاث ساعات — والمحتوى السابق باقٍ لا يُمسح
FETCH_TIMEOUT = 90
MAX_BYTES = 1 << 30          # حدّ الملف بعد فكّ ضغطه (1 GB)
NAME_MAX = 150
GROUP_MAX = 100
PAGE = 300                   # عناصر القسم في الصفحة الواحدة وفي كل «عرض المزيد»
SEARCH_MAX = 40              # نتائج البحث المعروضة لكل نوع
SEARCH_KINDS = ("series", "movie")   # البحث باسم المسلسل أو الفيلم وحده — لا القنوات، ومنها قنوات 24/7 تعرض
                                     # حلقات مسلسلٍ باسمه («SOLO باب الحارة»، «… S01») فتبدو حلقاتٍ في النتائج
QUERY_MAX = 60
ADULT_LIST = 200             # ما يُحفظ للمدير من أقسام الكبار ومن الأسماء المحذوفة (والباقي عددٌ)
ADULT_MARKS = 5000           # بصمات ما أُسقط، لمعرفة الجديد منه في كل سحب
ALERT_LINES = 15             # سطور التنبيه لكلٍّ منهما، والقائمة كاملة في صفحة المدير
UA = "VLC/3.0.20 LibVLC/3.0.20"   # لوحات Xtream تقبل المشغّلات وقد تردّ غيرها

_lock = threading.RLock()     # الإعداد: قراءةٌ ثم كتابة
_busy = {}                    # السيرفر ← {stage, bytes, at} ما دام يُقرأ ملفه
_cache = {}                   # السيرفر ← (البصمة، العرض المشتق)
_building = {}                # السيرفر ← قفل بناء عرضه: بناءٌ واحد في وقته، ومن طلبه معه ينتظره ولا يبني مثله
_sums = {}                    # السيرفر ← (البصمة، ملخّصه) — آخر ما عُرف، من العرض أو من ملفه على القرص
_warming = set()              # سيرفراتٌ تُبنى عروضها في الخلفية الآن
_files = {}                   # ملفٌّ صغير يُقرأ مع كل تحميلٍ لصفحة المدير ← (نسخته، ما فيه)
_found = {}                   # كاش البحث: (السيرفر، البصمة، الكلمات) ← النتيجة

# تنبيه المدير بما أُسقط للكبار — يضبطهما الخادم (xm_lines)، وبدونهما لا تنبيه:
notifier = None               # (العنوان، النص) ← {"mail": {ok, to, error}, "wa": {…}}
alert_info = None             # () ← لمن يصل التنبيه ومن أين يُرسل، لصفحة المدير


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
    s = " ".join(_CTRL.sub("", unicodedata.normalize("NFKC", s or "")).split())
    for _ in range(3):
        m = _PREFIX.match(s)
        if not m or m.end() >= len(s):
            break
        s = s[m.end():]
    return s[:NAME_MAX].strip()


NO_GROUP = "بلا قسم"          # عنصرٌ بلا ‏group-title (ملف ‏type=m3u) — ويُنقل إلى قسمه في الواجهة إن أمكن


def _group(s):
    return " ".join(_CTRL.sub("", unicodedata.normalize("NFC", s or "")).split())[:GROUP_MAX] or NO_GROUP


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


# السنة من آخر الاسم: «The Batman (2022)» «Dune [2021]» «Dune - 2021» «اسم الفيلم 2023» — والتي بين قوسين من أي
# موضع («Movie (2022) 4K»). وسنةٌ بلا قوسين بعد الحدّ المعقول جزءٌ من الاسم: «Blade Runner 2049».
_Y = r"((?:19|20)\d{2})"
_YEAR_PAREN = re.compile(r"\s*[\(\[]\s*" + _Y + r"\s*[\)\]]")
_YEAR_TAIL = re.compile(r"(?:\s*[-–|]\s*|\s+)" + _Y + r"\s*$")
YEAR_MAX = time.gmtime().tm_year + 1
# رقم العنصر في آخر رابطه: Xtream يرقّم ما يُضاف تصاعديًّا، فالأكبر أحدث — «أضيف مؤخرًا» بلا تاريخ
_SID = re.compile(r"/(\d{1,12})(?:\.[A-Za-z0-9]{2,5})?$")
# رابط فيلم أو حلقة من Xtream: منه قاعدة الواجهة واسم المستخدم وكلمة المرور — في الذاكرة وقت القراءة وحدها
_XT = re.compile(r"^(https?://[^/?#]+)/(?:movie|series)/([^/?#]+)/([^/?#]+)/\d+", re.I)


# الجودة في آخر الاسم: «The Batman FHD» «MBC 1 HD» «Film (2020) [MULTI-SUB]» — فيُجمع الفيلم أو القناة بجوداتها
# عنصرًا واحدًا. بحروفها الكبيرة، فلا يُمسّ آخر اسمٍ عادي (و«RAW» ليست منها: «WWE RAW»).
_QUAL = re.compile(r"(?:[\s\-_|]*[\[(]?\s*(?:4K|8K|UHD|FHD|HD|SD|HQ|HEVC|H\.?26[45]|[xX]26[45]|(?:2160|1080|720|480)[pP]|"
                   r"MULTI[\s-]?SUBS?|MULTI|VOSTFR|DUAL(?:[\s-]?AUDIO)?|3D|BACKUP|Backup)\s*[\])]?)+\s*$")


def _dequal(s):
    t = _QUAL.sub("", s).strip()
    return t or s


def _split_year(name):
    """← (الاسم بلا سنة، السنة أو 0)."""
    hits = [m for m in _YEAR_PAREN.finditer(name) if 1900 <= int(m.group(1)) <= YEAR_MAX]
    if hits:
        m = hits[-1]
        base = " ".join((name[:m.start()] + " " + name[m.end():]).split())
        return (_tidy(base), int(m.group(1))) if _tidy(base) else (name, 0)
    m = _YEAR_TAIL.search(name)
    if m and 1900 <= int(m.group(1)) <= YEAR_MAX and _tidy(name[:m.start()]):
        return _tidy(name[:m.start()]), int(m.group(1))
    return name, 0


def _sid(url):
    m = _SID.search(url.split("?", 1)[0].split("#", 1)[0])
    return int(m.group(1)) if m else 0


def _poster(v):
    """رابط الصورة كما يُطلب — والمسافة فيه (‏«…/logos/MBC 1.png» في لوحاتٍ كثيرة) مرمَّزة لا مُسقِطة."""
    v = (v or "").strip().replace(" ", "%20")
    return v if v.lower().startswith(("http://", "https://")) and len(v) <= 600 and not re.search(r"[\s\"<>]", v) else ""


def _slim(d):
    """العنصر بلا مفاتيحه الفارغة — أصغر على القرص."""
    return {k: v for k, v in d.items() if v}


class Parser:
    """يأخذ سطور الملف واحدًا واحدًا (‏line) ويُخرج الفهرس (‏result). والعنصر:
    فيلم {n الاسم، y السنة، p الصورة، i رقمه}، وقناة {n، p، i}، ومسلسل {n، y، p، i أكبر رقم حلقة، s المواسم}."""

    def __init__(self):
        self.pending = None
        self.extgrp = ""
        self.groups = {k: {} for k in KINDS}
        self.n = {k: 0 for k in KINDS}
        self.skipped = {"adult": 0, "sep": 0, "bad": 0}
        self.xt = None                       # (القاعدة، المستخدم، الكلمة) لواجهة Xtream — لا تُحفظ
        self.adult_groups = {}               # قسم الكبار ← عدد ما فيه (حُذف كله)
        self.adult_titles = {}               # بصمة الاسم ← [الاسم، قسمه، عدده]: حُذف باسمه من قسمٍ عادي

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
        if _ADULT_GROUP.search(group):
            self.skipped["adult"] += 1
            if group in self.adult_groups or len(self.adult_groups) < ADULT_MARKS:
                self.adult_groups[group] = self.adult_groups.get(group, 0) + 1
            return
        if _ADULT_TITLE.search(name):
            self.skipped["adult"] += 1
            k = _norm(name)
            if k in self.adult_titles:
                self.adult_titles[k][2] += 1
            elif len(self.adult_titles) < ADULT_MARKS:
                self.adult_titles[k] = [name, group, 1]
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
        if self.xt is None and uk in ("movie", "series"):
            m = _XT.match(url)
            if m:
                self.xt = (m.group(1), m.group(2), m.group(3))
        sid, poster = _sid(url), _poster(attrs.get("tvg-logo"))
        acc = self.groups[kind].setdefault(group, {})
        if kind == "live":
            name = _dequal(name)
            rec = acc.get(_norm(name))
            if rec is None:
                acc[_norm(name)] = {"n": name, "p": poster, "i": sid}
            else:
                rec["i"] = max(rec["i"], sid)
                rec["p"] = rec["p"] or poster
            return
        if kind == "movie":
            title, year = _split_year(_dequal(name))
            title = _dequal(title)
            k = f"{_norm(title)}|{year}"
            rec = acc.get(k)
            if rec is None:
                acc[k] = {"n": title, "y": year, "p": poster, "i": sid}
            else:                               # الفيلم نفسه بجودةٍ أخرى: رقمه الأحدث وأول صورة
                rec["i"] = max(rec["i"], sid)
                rec["p"] = rec["p"] or poster
            return
        sname, season, num = (_clean(_tidy(ep[0])), ep[1], ep[2]) if ep else (name, 0, None)
        sname, year = _split_year(_dequal(sname or group))
        k = _norm(sname)
        rec = acc.get(k)
        if rec is None:
            rec = acc[k] = {"n": sname, "y": year, "p": poster, "i": sid, "_s": {}}
        else:
            rec["i"] = max(rec["i"], sid)
            rec["p"] = rec["p"] or poster
            rec["y"] = rec["y"] or year
        eps = rec["_s"].get(season)
        if eps is None:
            eps = rec["_s"][season] = [set(), 0]
        if num is None:
            eps[1] += 1
        else:
            eps[0].add(num)

    def result(self):
        out = {"v": 2, "entries": sum(self.n.values()), "n": dict(self.n), "skipped": dict(self.skipped)}
        for kind in KINDS:
            gs = []
            for gname, acc in self.groups[kind].items():
                items = []
                for rec in acc.values():
                    if kind == "series":
                        rec = dict(rec, s=[[s, len(e[0]) + e[1]] for s, e in sorted(rec.pop("_s").items())])
                    items.append(_slim(rec))
                if items:
                    gs.append({"id": _gid(kind, gname), "name": gname, "items": items})
            out[kind] = gs
        return out

    def dropped(self, flagged=()):
        """ما أُسقط للكبار — للمدير وحده، ولا يدخل الفهرس: الأقسام بعدد ما فيها، والأسماء من أقسامٍ
        عادية بقسمها، والأفلام التي علّمتها واجهة السيرفر للكبار (‏flagged من enrich: [الاسم، قسمه])،
        وما لم يتّسع له الحدّ عددًا (‏more)، وبصمات الكل لمعرفة الجديد في السحب التالي."""
        groups = [[g, n] for g, n in self.adult_groups.items()][:ADULT_LIST]
        titles = list(self.adult_titles.values())[:ADULT_LIST]
        panel = [list(x) for x in flagged[:ADULT_LIST]]
        marks = ({_gid("adult-g", _norm(g)) for g in self.adult_groups} | {_gid("adult-t", k) for k in self.adult_titles}
                 | {_gid("adult-t", _norm(x[0])) for x in flagged[:ADULT_MARKS]})
        count = self.skipped["adult"] + len(flagged)
        return {"count": count, "groups": groups, "titles": titles, "panel": panel,
                "more": count - sum(g[1] for g in groups) - sum(t[2] for t in titles) - len(panel),
                "marks": sorted(marks)}


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


def _run(read, progress=None):
    p = Parser()
    for i, line in enumerate(iter_lines(read, progress)):
        if i == 0:
            line = line.lstrip("\ufeff")
        p.line(line)
    return p


def _parse(read, progress=None):
    """← (الفهرس، بيانات واجهة Xtream من روابط الملف أو None). الثانية للإثراء وقت القراءة وحدها،
    ولا تدخل الفهرس."""
    p = _run(read, progress)
    return p.result(), p.xt


def parse(read, progress=None):
    return _parse(read, progress)[0]


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


def _adult_path(data_dir, key):
    """ما أُسقط للكبار — بنقطةٍ في اسمه فلا يكون ملف سيرفرٍ آخر، ولا تقرؤه الصفحة العامة."""
    return os.path.join(_dir(data_dir), key + ".adult.json")


def _seen_path(data_dir, key):
    """بصمات ما رُئي في ملف السيرفر (لمعرفة الجديد في كل سحب) — يُقرأ ويُكتب وقت الإدخال وحده."""
    return os.path.join(_dir(data_dir), key + ".seen.json")


def _news_path(data_dir, key):
    """ما جدّ في ملف السيرفر سحبًا بعد سحب — لمنشور القناة ولصفحة المدير، ولا تقرؤه الصفحة العامة."""
    return os.path.join(_dir(data_dir), key + ".news.json")


def _sum_path(data_dir, key):
    """ملخّص الفهرس (أعداده وأقسامه وحال ملفه) لصفحة المدير والرئيسية والمتجر — يُكتب مع كل بناءٍ لعرضه، فيبقى بعد
    إعادة تشغيل الخادم ولا تنتظر الصفحة قراءة الفهرس الكبير."""
    return os.path.join(_dir(data_dir), key + ".sum.json")


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _read_ro(path):
    """‏_read لما يُقرأ ولا يُعدَّل (سجلّ الجديد وما أُسقط للكبار، مع كل تحميلٍ لصفحة المدير) — مرةً لكل نسخةٍ من الملف."""
    try:
        st = os.stat(path)
    except OSError:
        _files.pop(path, None)
        return None
    ver, c = (st.st_ino, st.st_mtime_ns, st.st_size), _files.get(path)
    if c and c[0] == ver:
        return c[1]
    d = _read(path)
    _files[path] = (ver, d)
    return d


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


RESERVED_KEYS = frozenset(("movies", "series", "people", "genres", "countries", "languages", "year", "latest", "search",
                           "turkish", "anime", "page", "img", "api", "admin"))   # مسارات طبقة الكيانات: لا تكون اسم سيرفر


def key_ok(v):
    """مفتاح السيرفر حروفًا لاتينية صغيرة وأرقامًا — آخر رابط صفحته واسم ملفه، فلا يخرج من المجلد — وليس كلمةً محجوزة."""
    s = str(v or "").strip().lower()
    return s if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,23}", s) and s not in RESERVED_KEYS else ""


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
                    "full": str(x.get("full") or "").strip()[:40],
                    "en": str((x.get("en") if "en" in x else EN_NAMES.get(k)) or "").strip()[:40],
                    "buy": str(x.get("buy") or "").strip()[:500],
                    "url": x.get("url") if isinstance(x.get("url"), str) else "",
                    "hidden": [h for h in (x.get("hidden") or []) if isinstance(h, str)][:5000],
                    "try_at": _float(x.get("try_at")), "error": str(x.get("error") or "")[:300]})
    return out


def _save(data_dir, rows):
    path = os.path.join(_dir(data_dir), SETTINGS)
    s = _read(path) or {}                   # ويبقى ما سوى السيرفرات فيه (من يصله التنبيه)
    s["servers"] = rows
    _write(path, s)


def alert_to(data_dir):
    """من يصله تنبيه الكبار كما حفظه المدير ← {mail, wa} (والفارغ لا يُرسل إليه)، أو None إن لم يحفظه
    بعد — فيأخذ الخادم بريد التنبيه ورقم واتساب المدير من إعداداتهما."""
    a = (_read(os.path.join(_dir(data_dir), SETTINGS)) or {}).get("alert")
    if not isinstance(a, dict):
        return None
    return {"mail": str(a.get("mail") or "")[:200], "wa": str(a.get("wa") or "")[:20]}


def save_alert_to(data_dir, mail, wa):
    """يحفظ من يصله التنبيه — والتحقّق من البريد والرقم على الخادم قبله."""
    with _lock:
        path = os.path.join(_dir(data_dir), SETTINGS)
        s = _read(path) or {}
        s["alert"] = {"mail": str(mail or "")[:200], "wa": str(wa or "")[:20]}
        _write(path, s)


def servers(data_dir):
    with _lock:
        return _load(data_dir)


_ARABIC = re.compile(r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\ufb50-\ufdff\ufe70-\ufeff]")


def en_name(srv):
    """اسم السيرفر في الصفحة الإنجليزية: ما كتبه المدير، أو اسمه إن كان بحروفٍ لاتينية، أو السطر تحته («FALCON TV PRO»)،
    أو رابط صفحته («najm» ← Najm)."""
    name = srv.get("name") or ""
    return (srv.get("en") or ("" if _ARABIC.search(name) else name) or srv.get("full")
            or srv["key"].replace("-", " ").title())


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


def ingest(data_dir, key, read, source, label="", claimed=False, xt=None):
    """يقرأ ملف السيرفر (دالة قراءة) ويحفظ فهرسه ← ملخّصه. ملفٌّ بلا عناصر لا يمسح المحتوى السابق:
    رابطٌ انتهى اشتراكه يردّ قائمةً فارغة أو صفحة خطأ. ثم يُثريه من واجهة Xtream (‏xt، أو من روابط
    الملف نفسه) إن أمكن، وفشلها لا يمنع الحفظ."""
    if not _server(data_dir, key):
        raise ValueError("سيرفر غير معروف")
    if not claimed:
        _claim(key, "read")
    try:
        state = _busy.get(key) or {}
        state["stage"] = "read"
        p = _run(read, progress=lambda n: state.__setitem__("bytes", n))
        cat, found = p.result(), p.xt
        if not cat["entries"]:
            raise ValueError("لا عناصر في الملف (‏#EXTINF) — تأكّد أنه قائمة M3U نفسها لا صفحة خطأ")
        api, flagged = xt or found, []
        if api:
            state["stage"] = "meta"
            try:
                cat["api"] = {"ok": True, **enrich(cat, api, flagged)}
            except Exception as e:  # noqa: BLE001 — الصفحة بما في الملف، والسبب للمدير
                cat["api"] = {"ok": False, "error": _fetch_error(e)}
        now = time.time()
        cat.update(key=key, at=now, source=source, label=str(label or "")[:80])
        _write(_cat_path(data_dir, key), cat)
        _cache.pop(key, None)
        _settle(data_dir, key, "")
        try:
            news = _record_news(data_dir, key, cat)
        except Exception as e:  # noqa: BLE001 — تسجيل الجديد لا يُسقط الإدخال، وسببه للمدير
            news = {"error": str(e)[:200]}
        new = _record_adult(data_dir, key, p.dropped(flagged), source, now)
        if new and notifier:
            subject, body = alert_text(_server(data_dir, key)["name"], new, cat["skipped"]["adult"])
            threading.Thread(target=_alert, args=(data_dir, key, subject, body), daemon=True).start()
        _view(data_dir, key)                    # يُبنى فهرس البحث الآن، فلا ينتظره أول زائر
        return {"entries": cat["entries"], "n": cat["n"], "skipped": cat["skipped"], "api": cat.get("api"), "news": news}
    finally:
        if not claimed:
            _release(key)


def _record_adult(data_dir, key, rep, source, at):
    """يحفظ ما أُسقط للكبار للمدير ← ما لم يكن في السحب السابق {groups, titles, panel, other, first}، أو None
    إن لم يجدّ شيء. وملفٌّ لا شيء فيه للكبار يمحو السابق، فما يعود بعده جديد."""
    path = _adult_path(data_dir, key)
    with _lock:
        old = _read(path)
        if not rep["count"]:
            try:
                os.remove(path)
            except OSError:
                pass
            return None
        _write(path, dict(rep, at=at, source=source, alert=(old or {}).get("alert")))
    new = set(rep["marks"]) - set((old or {}).get("marks") or [])
    if not new:
        return None
    groups = [g for g in rep["groups"] if _gid("adult-g", _norm(g[0])) in new]
    titles = [t for t in rep["titles"] if _gid("adult-t", _norm(t[0])) in new]
    panel = [t for t in rep.get("panel") or [] if _gid("adult-t", _norm(t[0])) in new]
    return {"groups": groups, "titles": titles, "panel": panel,
            "other": max(0, len(new) - len(groups) - len(titles) - len(panel)), "first": old is None}


def alert_text(name, new, count):
    """تنبيه المدير بما جدّ للكبار في ملف سيرفر (للبريد وواتساب) ← (العنوان، النص)."""
    lines = [f"ظهر في ملف سيرفر {name} محتوى للكبار{'' if new['first'] else ' لم يكن في سحبه السابق'}، "
             "فحُذف من صفحة المحتوى ولم يُنشر."]
    if new["groups"]:
        lines += ["", "أقسامٌ حُذفت كلها:"]
        lines += [f"• {g} ({_count(n, N_ITEMS)})" for g, n in new["groups"][:ALERT_LINES]]
    if new["titles"]:
        lines += ["", "أسماءٌ حُذفت من أقسامٍ عادية — راجِعها، فقد يكون بينها فيلمٌ عادي:"]
        lines += [f"• {t} — في «{g}»" for t, g, _n in new["titles"][:ALERT_LINES]]
    if new["panel"]:
        lines += ["", "أفلامٌ علّمتها لوحة السيرفر للكبار:"]
        lines += [f"• {t} — في «{g}»" for t, g in new["panel"][:ALERT_LINES]]
    left = sum(max(0, len(new[k]) - ALERT_LINES) for k in ("groups", "titles", "panel")) + new["other"]
    if left:
        lines.append(f"• و{left:,} غيرها في صفحة المحتوى")
    lines += ["", f"المحذوف للكبار من ملفه كله: {_count(count, N_ITEMS)}."]
    return f"تنبيه: محتوى للكبار في ملف سيرفر {name} (حُذف ولم يُنشر)", "\n".join(lines)


def _alert(data_dir, key, subject, body):
    """يرسل التنبيه ويحفظ ما جرى ليراه المدير — في خيطٍ مستقل، فلا ينتظره رفعٌ ولا سحب."""
    try:
        res = notifier(subject, body)
    except Exception as e:  # noqa: BLE001 — التنبيه لا يُسقط شيئًا، وسببه يُحفظ
        res = {"error": str(e)[:200]}
    with _lock:
        path = _adult_path(data_dir, key)
        rec = _read(path)
        if rec:                                 # ومُسح المحتوى قبل أن يُرسل: لا شيء يُحفظ
            rec["alert"] = dict(res if isinstance(res, dict) else {}, at=time.time())
            _write(path, rec)


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
            ingest(data_dir, key, r.read, "url", mask_url(url), claimed=True, xt=xtream_of(url))
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
    """دورة الخلفية: كل سيرفرٍ له رابط يُسحب إن مرّ يومٌ على آخر محتوى — أو كان محتواه من القراءة الأولى (بلا صور
    ولا تقييم) فيُسحب في أول دورة — ولا يُعاد فشلٌ قبل RETRY."""
    now = now or time.time()
    for s in servers(data_dir):
        if not s["url"] or s["key"] in _busy:
            continue
        due = now - _cat_at(data_dir, s["key"]) >= REFRESH or _cat_old(data_dir, s["key"])
        if due and now - s["try_at"] >= RETRY:
            refresh(data_dir, s["key"], now=now)


def _cat_at(data_dir, key):
    """وقت آخر محتوى من وقت ملفه — بلا قراءته، فلا تبني الدورة فهرسَ سيرفرٍ لم يزره أحد."""
    try:
        return os.stat(_cat_path(data_dir, key)).st_mtime
    except OSError:
        return 0.0


_V2 = re.compile(rb'^\{\s*"v"\s*:\s*2\b')


def _cat_old(data_dir, key):
    """فهرسٌ قرأته النسخة الأولى (بلا صور ولا أرقام ولا تقييم) — من أول بايتاته: النسخة الحالية تبدأ بـ ‏"v":2."""
    try:
        with open(_cat_path(data_dir, key), "rb") as f:
            return not _V2.match(f.read(32))
    except OSError:
        return False


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
    """يضيف سيرفرًا (‏new، والمفتاح المطلوب في key) أو يعدّل اسمه وما تحته واسمه بالإنجليزية ورابط شرائه (المفتاح
    في key، أو في s كما ترسله بطاقة السيرفر في صفحة المدير)."""
    name = " ".join(str(form.get("name") or "").split())[:40]
    full = " ".join(str(form.get("full") or "").split())[:40]
    en = " ".join(str(form.get("en") or "").split())[:40]
    buy = str(form.get("buy") or "").strip()[:500]
    if buy and not buy.lower().startswith(("http://", "https://")):
        raise ValueError("رابط الشراء يبدأ بـ https://")
    if not name:
        raise ValueError("اكتب اسم السيرفر")
    raw_key = str(form.get("key") or ("" if form.get("new") else form.get("s")) or "").strip()
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
            rows.append({"key": key, "name": name, "full": full, "en": en, "buy": buy, "url": "", "hidden": [],
                         "try_at": 0.0, "error": ""})
        else:
            r = next((r for r in rows if r["key"] == key), None)
            if not r:
                raise ValueError("سيرفر غير معروف")
            r.update(name=name, full=full, buy=buy, **({"en": en} if "en" in form else {}))
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
        for path in (_cat_path(data_dir, key), _adult_path(data_dir, key), _seen_path(data_dir, key),
                     _news_path(data_dir, key), _sum_path(data_dir, key)):
            try:
                os.remove(path)
            except OSError:
                pass
        _cache.pop(key, None)
        _sums.pop(key, None)


# ================= العرض المشتق (للصفحة والبحث) =================
SUM_V = 1                            # نسخة الملخّص: تُزاد إن تغيّر ما فيه أو طريقة العدّ، فيُعاد بناء ما حُفظ قبلها


def _sig(st, srv):
    """بصمة العرض: نسخة ملف الفهرس (رقمه على القرص — ‏_write يكتب ملفًّا جديدًا كل مرة — ووقته وحجمه) وما أُخفي منه."""
    return [st.st_ino, st.st_mtime_ns, st.st_size, list(srv["hidden"])]


def _view(data_dir, key):
    """← (السيرفر، العرض): أقسامه الظاهرة وأعداده وفهرس البحث — يُبنى مرةً لكل نسخةٍ من الملف وما أُخفي منه، ويبقى
    في الذاكرة، ويُحفظ ملخّصه على القرص. وبناءٌ واحد لكل سيرفرٍ في وقته: من يطلبه وهو يُبنى ينتظره ثم يأخذه، فلا تبني
    الطلبات الفهرسَ نفسه معًا (بعد إعادة التشغيل أو سحبٍ جديد) فيطول انتظارها كلها."""
    srv = _server(data_dir, key)
    if not srv:
        return None, None
    try:
        st = os.stat(_cat_path(data_dir, key))
    except OSError:
        return srv, None
    c = _cache.get(key)
    if c and c[0] == _sig(st, srv):
        return srv, c[1]
    with _lock:
        lock = _building.setdefault(key, threading.Lock())
    with lock:
        srv = _server(data_dir, key)
        if not srv:
            return None, None
        try:
            with open(_cat_path(data_dir, key), encoding="utf-8") as f:
                sig = _sig(os.fstat(f.fileno()), srv)      # بصمة ما يُقرأ نفسه، ولو استُبدل الملف بعدها
                c = _cache.get(key)
                if c and c[0] == sig:                      # بناه من سبق وهذا ينتظره
                    return srv, c[1]
                try:
                    cat = json.load(f)
                except ValueError:
                    cat = None
        except OSError:
            return srv, None
        try:
            v = _build(cat, set(srv["hidden"])) if isinstance(cat, dict) else None   # والتالف يُحفظ بلا عرض فلا يُعاد
        except Exception:
            _sums[key] = (sig, None)                       # فلا تنتظره صفحة المدير أبدًا، ويُحاوَل ثانيةً مع الطلب التالي
            raise
        m = _summarize(v) if v else None
        _cache[key], _sums[key] = (sig, v), (sig, m)
        if m:
            try:
                _write(_sum_path(data_dir, key), dict(m, v=SUM_V, sig=sig))
            except OSError:
                pass
    return srv, v


def _summarize(v):
    """ما تحتاجه صفحة المدير والرئيسية والمتجر وقائمة السيرفرات من العرض ← {has, at, counts، cat: حال الملف،
    groups: {النوع: [[id، الاسم، عدد عناصره]]}} — بالأقسام كلها، والمخفي منها معها."""
    cat = v["cat"]
    return {"has": _has(v), "at": v["at"], "counts": v["counts"],
            "cat": {k: cat[k] for k in ("source", "label", "entries", "n", "skipped", "api", "old") if k in cat},
            "groups": {k: [[g.get("id"), g.get("name"), len(g.get("items") or [])] for g in cat.get(k) or []]
                       for k in KINDS}}


def _summary(data_dir, key, srv=None, wait=True):
    """ملخّص محتوى السيرفر (‏_summarize) لنسخة ملفه الآن ← (الملخّص أو None بلا محتوى، حديث؟) — من العرض إن بُني وإلا من
    ملفه الصغير، بلا قراءة الفهرس الكبير. وما لم يُبنَ لها بعد (أول مرة، أو بعد سحبٍ أو إخفاء قسم) يُبنى الآن (‏wait)، أو
    يُعاد آخر ملخّصٍ عُرف له (أو None) ويُبنى في الخلفية — لصفحة المدير، فتُفتح فورًا وتُكمل أعدادها بعد لحظات."""
    srv = srv or _server(data_dir, key)
    if not srv:
        return None, True
    try:
        sig = _sig(os.stat(_cat_path(data_dir, key)), srv)
    except OSError:
        return None, True
    m = _sums.get(key)
    if not m or m[0] != sig:
        rec = _read(_sum_path(data_dir, key))
        if rec and rec.get("v") == SUM_V and isinstance(rec.get("counts"), dict) and isinstance(rec.get("groups"), dict) \
                and (rec.get("sig") == sig or not m):
            m = (rec.get("sig"), rec)
            if m[0] == sig:
                _sums[key] = m
    if m and m[0] == sig:
        return m[1], True
    if wait:
        v = _view(data_dir, key)[1]
        return (_summarize(v) if v else None), True
    warm(data_dir, [key])
    return (m[1] if m else None), False


def has(data_dir, key, srv=None):
    """للسيرفر محتوى يُنشر؟ — من ملخّصه، فلا يُبنى عرض كل سيرفرٍ لقائمة السيرفرات في صفحة غيره."""
    m = _summary(data_dir, key, srv)[0]
    return bool(m and m["has"])


def _ready(data_dir, key):
    """العرض إن كان مبنيًّا لنسخة الملف الآن، بلا انتظار ← العرض، أو None بلا محتوى، أو False إن لم يُبنَ بعد (ويُبنى
    في الخلفية)."""
    srv = _server(data_dir, key)
    if not srv:
        return None
    try:
        sig = _sig(os.stat(_cat_path(data_dir, key)), srv)
    except OSError:
        return None
    c = _cache.get(key)
    if c and c[0] == sig:
        return c[1]
    warm(data_dir, [key])
    return False


def warm(data_dir, keys=None):
    """يبني عروض السيرفرات (وملخّصاتها) في الخلفية واحدًا بعد واحد، وما يُبنى منها الآن لا يُعاد ← الخيط أو None — عند
    إقلاع الخادم فلا ينتظرها أول زائرٍ ولا صفحة المدير، ولما طلبته صفحة المدير ولم يُبنَ بعد."""
    with _lock:
        keys = [k for k in (keys if keys is not None else [s["key"] for s in _load(data_dir)]) if k not in _warming]
        _warming.update(keys)
    if not keys:
        return None

    def run():
        for k in keys:
            try:
                _view(data_dir, k)
            except Exception:  # noqa: BLE001 — فهرسٌ لا يُبنى لا يوقف غيره، ويُبنى حين يُطلب
                pass
            finally:
                with _lock:
                    _warming.discard(k)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def _upgrade(cat):
    """فهرسٌ من النسخة الأولى (الفيلم والقناة نصًّا، والمسلسل [الاسم، المواسم]) بصيغة العناصر الحالية — والسنة
    والجودة تُفصلان من الاسم كما في القراءة الحالية، فيُعرض الفيلم بسنته وبجوداته عنصرًا واحدًا من الآن، لا بعد
    السحب التالي."""
    if cat.get("v") == 2:
        return cat
    cat["old"] = True                        # للمدير: يُعاد رفعه أو يُسحب لتظهر الصور والتقييمات
    for kind in KINDS:
        for g in cat.get(kind) or []:
            items = {}
            for n, it in enumerate(g.get("items") or []):
                if isinstance(it, dict):
                    rec = it
                elif kind == "series" and isinstance(it, list):
                    name, year = _split_year(_dequal(str(it[0])))
                    rec = _slim({"n": name, "y": year, "s": it[1]})
                elif kind == "movie":
                    name, year = _split_year(_dequal(str(it)))
                    rec = _slim({"n": _dequal(name), "y": year})
                else:
                    rec = {"n": _dequal(str(it))}
                items.setdefault(n if kind == "series" else _ikey(kind, rec), rec)
            g["items"] = list(items.values())
    cat["v"] = 2
    return cat


_versions = itertools.count(1)       # رقمٌ لكل عرضٍ يُبنى — مفتاح كاش البحث
RECENT_MAX = 120                     # «أضيف مؤخرًا»: أحدث ما يُحفظ لكل نوع


def _ikey(kind, it):
    """مفتاح العنصر بين الأقسام: الفيلم باسمه وسنته، وغيره باسمه."""
    return f"{_norm(it.get('n', ''))}|{it.get('y') or ''}" if kind == "movie" else _norm(it.get("n", ""))


def _build(cat, hidden):
    cat = _upgrade(cat)
    v = {"at": float(cat.get("at") or 0), "cat": cat, "kinds": {}, "byid": {}, "index": {}, "recent": {},
         "years": {}, "genres": {}, "rated": {}, "imgs": {}, "ver": next(_versions)}
    for kind in KINDS:
        gs = [g for g in cat.get(kind) or [] if g.get("id") not in hidden and g.get("items")]
        v["kinds"][kind] = gs
        v["byid"][kind] = {g["id"]: i for i, g in enumerate(gs)}
        idx, best, years, genres, rated = [], {}, set(), {}, False
        for gi, g in enumerate(gs):
            for ii, it in enumerate(g["items"]):
                name = it.get("n", "")
                if kind in SEARCH_KINDS:
                    idx.append((_norm(f"{name} {it['y']}" if it.get("y") else name), gi, ii))
                for u in (it.get("p"), it.get("b")):
                    if u and not _TMDB.match(u):
                        v["imgs"][img_hash(u)] = u
                if it.get("y"):
                    years.add(it["y"])
                for x in it.get("g") or ():
                    genres[x] = genres.get(x, 0) + 1
                rated = rated or bool(it.get("r"))
                rank = (it.get("a") or 0, it.get("i") or 0)
                if rank != (0, 0):
                    k = _ikey(kind, it)
                    if k not in best or rank > best[k][0]:
                        best[k] = (rank, gi, ii)
        v["index"][kind] = idx
        v["recent"][kind] = [(gi, ii) for _, gi, ii in sorted(best.values(), key=lambda b: b[0], reverse=True)[:RECENT_MAX]]
        v["years"][kind] = sorted(years, reverse=True)
        v["genres"][kind] = [x for x, _ in sorted(genres.items(), key=lambda kv: (-kv[1], kv[0]))[:40]]
        v["rated"][kind] = rated
    ser = {}
    for g in v["kinds"]["series"]:
        for it in g["items"]:
            d = ser.setdefault(_ikey("series", it), {})
            for s, n in it.get("s") or ():
                if n > d.get(s, 0):
                    d[s] = n
    for g in v["kinds"]["series"]:             # والمسلسل في قسمين يُعرض بمواسمه كلها في كلٍّ منهما
        for it in g["items"]:
            it["s"] = [[s, n] for s, n in sorted(ser[_ikey("series", it)].items())]
    v["counts"] = {"series": len(ser), "seasons": sum(len(d) for d in ser.values()),
                   "episodes": sum(sum(d.values()) for d in ser.values()),
                   "movie": len({_ikey("movie", it) for g in v["kinds"]["movie"] for it in g["items"]}),
                   "live": len({_ikey("live", it) for g in v["kinds"]["live"] for it in g["items"]})}
    return v


def _has(v):
    return bool(v) and any(v["counts"][k] for k in KINDS)


def _words(q):
    words = _norm(q).split()
    return words if len("".join(words)) >= 2 else []


def _search(key, v, q):
    """← ({النوع: ([(القسم، العنصر)] أولها SEARCH_MAX، عددها كله)}، المجموع). كل كلمةٍ من البحث في الاسم
    (والسنة)؛ والمطابق تمامًا أولًا ثم ما يبدأ بها ثم ما فيه، والاسم في قسمين نتيجةٌ واحدة. ويُحفظ الأول
    وحده، فلا يملأ الذاكرةَ بحثٌ واسع كـ«ال»."""
    words = _words(q)
    if not words:
        return {k: ([], 0) for k in KINDS}, 0
    ck = (key, v["ver"], tuple(words))
    if ck in _found:
        return _found[ck]
    full = " ".join(words)
    out, total = {}, 0
    for kind in KINDS:
        tiers, n, seen = ([], [], []), 0, set()
        for norm, gi, ii in v["index"][kind]:
            if norm not in seen and all(w in norm for w in words):
                seen.add(norm)
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


def _near(a, b):
    """بين الكلمتين تعديلٌ واحد: حرفٌ مختلف («ياب» «باب») أو زائد أو ناقص، أو حرفان متجاوران مقلوبان."""
    la, lb = len(a), len(b)
    if la > lb:
        a, b, la, lb = b, a, lb, la
    if lb - la > 1 or a == b:
        return False
    i = 0
    while i < la and a[i] == b[i]:
        i += 1
    if la < lb:
        return a[i:] == b[i + 1:]
    return a[i + 1:] == b[i + 1:] or (i + 1 < la and a[i] == b[i + 1] and a[i + 1] == b[i] and a[i + 2:] == b[i + 2:])


def _vocab(v):
    """كلمات أسماء المسلسلات والأفلام بطولها، الأكثر تكرارًا أولًا — لتصحيح خطأٍ في كتابة البحث. تُبنى أول مرة."""
    voc = v.get("_vocab")
    if voc is None:
        freq = {}
        for kind in SEARCH_KINDS:
            for norm, _, _ in v["index"][kind]:
                for w in norm.split():
                    if len(w) >= 3 and not w.isdigit():
                        freq[w] = freq.get(w, 0) + 1
        voc = {}
        for w, n in freq.items():
            voc.setdefault(len(w), []).append((n, w))
        for lst in voc.values():
            lst.sort(key=lambda x: (-x[0], x[1]))
        v["_vocab"] = voc
    return voc


def suggest(key, v, q):
    """أقرب بحثٍ له نتائج لبحثٍ بلا نتائج — خطأٌ في حرفٍ واحد من كلمة («ياب الحارة» ← «باب الحارة»، «braking bad»
    ← «breaking bad»): لكل كلمةٍ من ثلاثة أحرفٍ فأكثر أقرب كلمات الأسماء إليها الأكثر تكرارًا، ويُجرَّب تصحيح كلمةٍ
    ثم كلمتين. ← الكلمات المصحَّحة نصًّا، أو "" إن لم يُعرف."""
    words = _words(q)
    if not words or len(words) > 4 or _search(key, v, q)[1]:
        return ""
    voc = _vocab(v)
    alts = []
    for w in words:
        near = sorted(((n, x) for size in (len(w) - 1, len(w), len(w) + 1) for n, x in voc.get(size, ())
                       if _near(w, x)), key=lambda p: (-p[0], p[1])) if len(w) >= 3 and not w.isdigit() else []
        alts.append([x for _, x in near[:3]])
    tries = [{i: a} for i in range(len(words)) for a in alts[i]]
    tries += [{i: a, j: b} for i in range(len(words)) for j in range(i + 1, len(words))
              for a in alts[i][:2] for b in alts[j][:2]]
    for t in tries[:24]:
        fixed = " ".join(t.get(i, w) for i, w in enumerate(words))
        if _search(key, v, fixed)[1]:
            return fixed
    return ""


def select(v, kind, gid="", year=0, genre="", rating=0, sort="new"):
    """عناصر نوعٍ (أو قسمٍ منه) بمرشّحات الصفحة ← [(القسم، العنصر)] مرتّبة، بلا تكرارٍ بين الأقسام."""
    gs = v["kinds"][kind]
    groups = [v["byid"][kind][gid]] if gid in v["byid"][kind] else range(len(gs))
    seen, out = set(), []
    for gi in groups:
        for ii, it in enumerate(gs[gi]["items"]):
            if year and it.get("y") != year or genre and genre not in (it.get("g") or ()) \
                    or rating and (it.get("r") or 0) < rating:
                continue
            k = _ikey(kind, it)
            if k in seen:
                continue
            seen.add(k)
            out.append((gi, ii))
    item = lambda p: gs[p[0]]["items"][p[1]]  # noqa: E731
    if sort == "az":
        out.sort(key=lambda p: _norm(item(p).get("n", "")))
    elif sort == "rate":
        out.sort(key=lambda p: -(item(p).get("r") or 0))
    else:
        out.sort(key=lambda p: (item(p).get("a") or 0, item(p).get("i") or 0), reverse=True)
    return out


def first_key(data_dir):
    """أول سيرفرٍ له محتوى — إليه يذهب ‏/content."""
    for s in servers(data_dir):
        if has(data_dir, s["key"], s):
            return s["key"]
    return ""


# ================= الصور =================
# صورة كل عنصر من ملفه (‏tvg-logo) أو من واجهة Xtream: ما على TMDB يُطلب منها مباشرةً بالمقاس المناسب، وغيره
# (غالبًا على سيرفر اللوحة نفسه، وبـ http) يمرّ بخادمنا: فلا يظهر سيرفر اللوحة في الصفحة، ولا يحجبه المتصفح
# في صفحة https. ويُحفظ ما جُلب في data/content/img/ بحدٍّ لحجمه، ويُصغَّر إن كانت Pillow مثبّتة.
IMG_DIR = "img"
IMG_MAX = 3 * 1024 * 1024            # أكبر صورةٍ تُجلب
IMG_CACHE = int(os.environ.get("CONTENT_IMG_CACHE_MB", "400") or 400) * 1024 * 1024
IMG_FAIL_TTL = 24 * 3600             # صورةٌ تعذّر جلبها لا يُعاد طلبها قبل يوم
IMG_TIMEOUT = 10
_TMDB = re.compile(r"^https?://image\.tmdb\.org/t/p/[^/]+/([^/?#]+)$", re.I)
_img_sem = threading.BoundedSemaphore(6)     # لا تُغرق اللوحة بطلبات الصور معًا
_img_lock = threading.Lock()
_img_bytes = {}                              # المجلد ← حجمه


def img_hash(url):
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def img_src(key, url, size="w342"):
    """رابط الصورة كما تطلبها الصفحة ← "" بلا صورة."""
    if not url:
        return ""
    m = _TMDB.match(url)
    if m:
        return f"https://image.tmdb.org/t/p/{size}/{m.group(1)}"
    return f"{PATH}/{key}/img/{img_hash(url)}"


IMG_PRIVATE = os.environ.get("CONTENT_IMG_PRIVATE") == "1"   # للاختبارات وحدها: صورٌ من خادمٍ وهمي محلي


def _public_host(host):
    """المضيف عنوانٌ عام — لا يُطلب من خادمنا ما في شبكته الداخلية وإن كان في ملف M3U."""
    if IMG_PRIVATE:
        return bool(host)
    try:
        infos = socket.getaddrinfo(host, None)
    except (OSError, UnicodeError):
        return False
    try:
        return bool(infos) and all(ipaddress.ip_address(i[4][0].split("%")[0]).is_global for i in infos)
    except ValueError:
        return False


class _SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _public_host(urlsplit(newurl).hostname or ""):
            raise URLError("redirect to a non-public address")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_img_opener = build_opener(_SafeRedirect)


def _img_type(b):
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return ""


def _shrink(data, ctype):
    """الصورة بعرض الملصق (400×600) إن كانت Pillow مثبّتة وكانت أكبر — وإلا كما هي."""
    try:
        from PIL import Image
    except ImportError:
        return data, ctype
    try:
        im = Image.open(io.BytesIO(data))
        if max(im.size) <= 600:
            return data, ctype
        im.thumbnail((400, 600))
        out = io.BytesIO()
        if im.mode in ("RGBA", "LA", "P"):
            im.save(out, "PNG", optimize=True)
            t = "image/png"
        else:
            im.convert("RGB").save(out, "JPEG", quality=82, optimize=True)
            t = "image/jpeg"
        return (out.getvalue(), t) if out.tell() < len(data) else (data, ctype)
    except Exception:  # noqa: BLE001 — صورةٌ لا تُفتح تُقدَّم كما هي
        return data, ctype


def _img_save(folder, path, data):
    os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    with _img_lock:
        if folder not in _img_bytes:
            _img_bytes[folder] = sum(e.stat().st_size for e in os.scandir(folder) if e.is_file())
        else:
            _img_bytes[folder] += len(data)
        if _img_bytes[folder] <= IMG_CACHE:
            return
        for e in sorted((e for e in os.scandir(folder) if e.is_file()), key=lambda e: e.stat().st_mtime):
            if _img_bytes[folder] <= IMG_CACHE * 0.8:
                break
            try:
                size = e.stat().st_size
                os.remove(e.path)
                _img_bytes[folder] -= size
            except OSError:
                pass


def image(data_dir, key, h):
    """صورةٌ من خادمنا ← (الرمز، البايتات، النوع): من المجلد إن جُلبت، وإلا من رابطها في فهرس السيرفر وحده."""
    if not re.fullmatch(r"[0-9a-f]{16}", h or ""):
        return 404, b"", ""
    folder = os.path.join(_dir(data_dir), IMG_DIR)
    path = os.path.join(folder, h)
    try:
        with open(path, "rb") as f:
            data = f.read()
        return 200, data, _img_type(data) or "application/octet-stream"
    except OSError:
        pass
    try:
        if time.time() - os.path.getmtime(path + ".x") < IMG_FAIL_TTL:
            return 404, b"", ""
    except OSError:
        pass
    v = _view(data_dir, key)[1]
    url = v["imgs"].get(h) if v else None
    if not url:
        return 404, b"", ""
    with _img_sem:
        try:
            if not _public_host(urlsplit(url).hostname or ""):
                raise URLError("non-public address")
            with _img_opener.open(Request(url, headers={"User-Agent": UA}), timeout=IMG_TIMEOUT) as r:
                data = r.read(IMG_MAX + 1)
            ctype = _img_type(data)
            if len(data) > IMG_MAX or not ctype:
                raise ValueError("not an image")
            data, ctype = _shrink(data, ctype)
        except Exception:  # noqa: BLE001 — أي فشلٍ يُعلَّم فلا يُعاد قبل يوم
            os.makedirs(folder, exist_ok=True)
            with open(path + ".x", "wb"):
                pass
            return 404, b"", ""
    _img_save(folder, path, data)
    return 200, data, ctype


# ================= الإثراء من واجهة Xtream =================
# ملف M3U فيه الأسماء والمواسم والصور، ولا تقييم فيه ولا تاريخ إضافة ولا تصنيف. وسيرفرات Xtream تعطي ذلك من
# واجهتها (‏player_api.php) بالمستخدم وكلمة المرور أنفسهما: من الرابط المحفوظ، أو من روابط الملف المرفوع وقت
# قراءته وحدها (لا تُحفظ). طلبان: الأفلام (‏get_vod_streams) والمسلسلات (‏get_series)، يُقرأ كلٌّ منهما عنصرًا
# عنصرًا وهو يصل. وأي فشلٍ لا يمسّ الفهرس: تبقى الصفحة بما في الملف.
API_TIMEOUT = 45
PLOT_MAX = 280


def xtream_of(url):
    """رابط M3U بصيغة Xtream (‏…/get.php?username=…&password=…) ← (القاعدة، المستخدم، الكلمة) أو None."""
    try:
        p = urlsplit(url)
        q = parse_qs(p.query)
        ok = p.hostname and p.path.rstrip("/").endswith("get.php") and q.get("username") and q.get("password")
    except ValueError:
        return None
    return (f"{p.scheme}://{p.netloc}", q["username"][0], q["password"][0]) if ok else None


def _api_open(xt, action):
    base, user, pw = xt
    url = f"{base}/player_api.php?" + urlencode({"username": user, "password": pw, "action": action})
    return urlopen(Request(url, headers={"User-Agent": UA, "Accept": "application/json"}), timeout=API_TIMEOUT)


def _json_items(read, chunk=1 << 16, limit=MAX_BYTES):
    """عناصر مصفوفة JSON واحدًا واحدًا وهي تصل — ردّ الأفلام قد يبلغ عشرات الميجات. وردٌّ ليس مصفوفة
    (رفض الدخول مثلًا) لا يُخرج شيئًا."""
    dec = json.JSONDecoder()
    text = codecs.getincrementaldecoder("utf-8")(errors="replace")
    st = {"buf": "", "i": 0, "total": 0, "eof": False}

    def more():
        b = read(chunk)
        if not b:
            st["eof"] = True
            st["buf"] += text.decode(b"", final=True)
            return
        st["total"] += len(b)
        if st["total"] > limit:
            raise ValueError("ردّ الواجهة أكبر من الحد")
        if st["i"] > 1 << 20:
            st["buf"], st["i"] = st["buf"][st["i"]:], 0
        st["buf"] += text.decode(b)

    started = False
    while True:
        buf, i = st["buf"], st["i"]
        while i < len(buf) and buf[i] in " \t\r\n,":
            i += 1
        st["i"] = i
        if i >= len(buf):
            if st["eof"]:
                return
            more()
            continue
        if not started:
            if buf[i] != "[":
                return
            started, st["i"] = True, i + 1
            continue
        if buf[i] == "]":
            return
        try:
            obj, end = dec.raw_decode(buf, i)
        except ValueError:
            if st["eof"]:
                return
            more()
            continue
        st["i"] = end
        if isinstance(obj, dict):
            yield obj


def _int(v):
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return 0


def _rating(v):
    try:
        r = float(str(v).split("/")[0].strip().replace(",", "."))
    except (TypeError, ValueError):
        return 0
    return round(r, 1) if 0 < r <= 10 else 0


def _genres(v):
    parts = v if isinstance(v, list) else re.split(r"\s*[,/|،]\s*", str(v or ""))
    out = []
    for p in parts:
        p = " ".join(str(p).split())[:24]
        if p and p.lower() not in {x.lower() for x in out}:
            out.append(p)
    return out[:3]


def _plot(v):
    s = " ".join(str(v or "").split())
    return s if len(s) <= PLOT_MAX else s[:PLOT_MAX].rsplit(" ", 1)[0] + "…"


def _year(v):
    m = re.match(r"\s*((?:19|20)\d{2})", str(v or ""))
    return int(m.group(1)) if m and int(m.group(1)) <= YEAR_MAX else 0


def _cid(o):
    """قسم العنصر في الواجهة: ‏category_id، أو أوّل ‏category_ids في اللوحات الأحدث."""
    c = o.get("category_id")
    if c in (None, "") and isinstance(o.get("category_ids"), list) and o["category_ids"]:
        c = o["category_ids"][0]
    return str(c).strip() if c not in (None, "") else ""


def _optional(xt, action, each):
    """طلبٌ لا يُفشل الإثراء إن فشل (الأقسام وشعارات القنوات): ‏each لكل عنصر ← نجح؟"""
    try:
        with _api_open(xt, action) as r:
            for o in _json_items(r.read):
                each(o)
        return True
    except Exception:  # noqa: BLE001 — الصفحة بلا هذا وحده
        return False


def enrich(cat, xt, flagged=None):
    """يُثري الفهرس من واجهة Xtream: تقييم الفيلم والمسلسل وتاريخ إضافته، وتصنيفه وقصته، وخلفية المسلسل —
    ويُسقط ما تعلّمه الواجهة للكبار (واسمه وقسمه في ‏flagged للمدير وحده، مرةً لكل فيلم). وملفٌّ بلا أقسام
    (‏type=m3u: كل شيءٍ في «بلا قسم») يُقسَّم بأقسام الواجهة وبترتيبها، وشعار القناة منها إن لم يكن في الملف.
    ← {movies، series، grouped} عدد ما أُثري وما قُسِّم. والفشل استثناء، والفهرس كما هو قبله."""
    movies, series, lives = {}, {}, {}
    for g in cat.get("movie") or []:
        for it in g["items"]:
            if it.get("i"):
                movies.setdefault(it["i"], []).append(it)
    for g in cat.get("series") or []:
        for it in g["items"]:
            series.setdefault(_norm(it["n"]), []).append(it)
    for g in cat.get("live") or []:
        for it in g["items"]:
            if it.get("i"):
                lives.setdefault(it["i"], []).append(it)
    want = {k for k in KINDS if any(g["name"] == NO_GROUP for g in cat.get(k) or [])}   # ما يحتاج أقسام الواجهة
    found, adult, done, heard, cids = {}, set(), {"movies": 0, "series": 0}, 0, {}
    if movies:
        with _api_open(xt, "get_vod_streams") as r:
            for o in _json_items(r.read):
                heard += 1
                sid = _int(o.get("stream_id"))
                if sid not in movies:
                    continue
                if str(o.get("is_adult") or "0").strip().lower() not in ("0", "", "false"):
                    adult.add(sid)
                    continue
                found[sid] = _slim({"r": _rating(o.get("rating")), "a": _int(o.get("added")), "g": _genres(o.get("genre")),
                                    "d": _plot(o.get("plot") or o.get("description")), "p": _poster(o.get("stream_icon")),
                                    "y": _year(o.get("year") or o.get("releasedate")), "c": _cid(o),
                                    "t": _int(o.get("tmdb_id") or o.get("tmdb"))})   # معرّف TMDB إن أعطته اللوحة (لطبقة الكيانات)
    got = {}
    if series:
        with _api_open(xt, "get_series") as r:
            for o in _json_items(r.read):
                heard += 1
                nm, yr = _split_year(_dequal(_clean(str(o.get("name") or ""))))
                its = series.get(_norm(nm))
                if not its:
                    continue
                yr = yr or _year(o.get("releaseDate") or o.get("release_date") or o.get("year"))
                bd = o.get("backdrop_path")
                bd = bd[0] if isinstance(bd, list) and bd else bd
                meta = _slim({"r": _rating(o.get("rating")), "a": _int(o.get("last_modified")), "g": _genres(o.get("genre")),
                              "d": _plot(o.get("plot")), "b": _poster(bd if isinstance(bd, str) else ""),
                              "p": _poster(o.get("cover")), "y": yr, "c": _cid(o),
                              "sid": _int(o.get("series_id")), "t": _int(o.get("tmdb") or o.get("tmdb_id"))})   # لطبقة الكيانات
                for it in its:                  # مسلسلان بالاسم نفسه: السنة تفصل بينهما
                    if not (yr and it.get("y") and it["y"] != yr) and id(it) not in got:
                        got[id(it)] = (it, meta)
    if (movies or series) and not heard:      # رفض الدخول يُردّ كائنًا لا مصفوفة: اشتراكٌ منتهٍ أو واجهةٌ مغلقة
        raise ValueError("الواجهة لم تُرجع شيئًا — الاشتراك منتهٍ أو السيرفر لا يتيحها")
    logos = {}
    if lives and ("live" in want or any(not it.get("p") for its in lives.values() for it in its)):
        def live(o):
            sid = _int(o.get("stream_id"))
            if sid in lives:
                logos[sid] = (_poster(o.get("stream_icon")), _cid(o))
        _optional(xt, "get_live_streams", live)
    names = {}

    def category(d):
        def add(o):
            name = _group(str(o.get("category_name") or ""))
            if _cid(o) and name != NO_GROUP:
                d.setdefault(_cid(o), name)
        return add
    for kind, action in (("movie", "get_vod_categories"), ("series", "get_series_categories"),
                         ("live", "get_live_categories")):
        if kind in want:
            names[kind] = {}
            _optional(xt, action, category(names[kind]))
    # لا يُمسّ الفهرس إلا بعد أن تُقرأ الردود كاملة
    for sid, meta in found.items():
        for it in movies[sid]:
            cids[id(it)] = meta.get("c", "")
            it.update({k: val for k, val in meta.items() if k != "c" and (k not in ("p", "y") or not it.get(k))})
        done["movies"] += 1
    for it, meta in got.values():
        cids[id(it)] = meta.get("c", "")
        it.update({k: val for k, val in meta.items() if k != "c" and (k not in ("p", "y") or not it.get(k))})
    done["series"] = len(got)
    for sid, (logo, cid) in logos.items():
        for it in lives[sid]:
            cids[id(it)] = cid
            if logo and not it.get("p"):
                it["p"] = logo
    if adult:
        told = set()
        for g in cat.get("movie") or []:
            if flagged is not None:
                for x in g["items"]:
                    if x.get("i") in adult and x["i"] not in told:
                        told.add(x["i"])
                        flagged.append([f"{x['n']} ({x['y']})" if x.get("y") else x["n"], g["name"]])
            g["items"] = [x for x in g["items"] if x.get("i") not in adult]
        cat["movie"] = [g for g in cat.get("movie") or [] if g["items"]]
        cat["skipped"]["adult"] = cat["skipped"].get("adult", 0) + len(adult)
    grouped = sum(_regroup(cat, kind, names.get(kind) or {}, cids, flagged) for kind in want)
    if grouped:
        done["grouped"] = grouped
    return done


def _regroup(cat, kind, names, cids, flagged):
    """ما في «بلا قسم» إلى قسمه في الواجهة (‏names: رقم القسم ← اسمه، بترتيب الواجهة) — وقسمٌ للكبار يُسقط ما فيه
    (وفي ‏flagged للمدير). وما لم يُعرف قسمه يبقى في «بلا قسم» آخرها. ← عدد ما نُقل."""
    groups = cat.get(kind) or []
    loose = next((g for g in groups if g["name"] == NO_GROUP), None)
    if loose is None or not names:
        return 0
    by, rest = {}, []
    for it in loose["items"]:
        name = names.get(cids.get(id(it), ""))
        (by.setdefault(name, []) if name else rest).append(it)
    out = [g for g in groups if g is not loose]
    named = {g["name"]: g for g in out}
    moved = 0
    for name in dict.fromkeys(names.values()):
        its = by.get(name)
        if not its:
            continue
        if _ADULT_GROUP.search(name):
            cat["skipped"]["adult"] = cat["skipped"].get("adult", 0) + len(its)
            if flagged is not None:
                flagged.extend([f"{x['n']} ({x['y']})" if x.get("y") else x["n"], name] for x in its)
            continue
        if name in named:
            named[name]["items"].extend(its)
        else:
            named[name] = {"id": _gid(kind, name), "name": name, "items": its}
            out.append(named[name])
        moved += len(its)
    if rest:
        loose["items"] = rest
        out.append(loose)
    cat[kind] = out
    return moved


# ================= الواجهات الأخرى =================
def brief(data_dir, wait=True):
    """للرئيسية ومسار الشراء وبطاقة المتجر: السيرفرات التي لها محتوى وأعدادها — من ملخّص كلٍّ منها. وبلا انتظار
    (‏wait=False، لصفحة المدير): آخر ما عُرف، وسيرفرٌ لم يُعرف له ملخّصٌ بعد لا يُذكر حتى يُبنى."""
    out = []
    for s in servers(data_dir):
        m = _summary(data_dir, s["key"], s, wait)[0]
        if m and m["has"]:
            c = m["counts"]
            out.append({"key": s["key"], "name": s["name"], "url": f"{PATH}/{s['key']}", "at": int(m["at"]),
                        "series": c["series"], "seasons": c["seasons"], "episodes": c["episodes"],
                        "movies": c["movie"], "channels": c["live"]})
    return {"ok": True, "servers": out}


def sitemap(data_dir):
    """صفحة كل سيرفرٍ له محتوى، ثم الإنجليزية منها."""
    keys = [s["key"] for s in servers(data_dir) if has(data_dir, s["key"], s)]
    return [(f"{PATH}/{k}", "daily", "0.7") for k in keys] + [(f"{PATH_EN}/{k}", "daily", "0.6") for k in keys]


def _adult_view(data_dir, key):
    """ما أُسقط من ملف السيرفر للكبار وآخر تنبيهٍ به — لصفحة المدير وحدها."""
    rec = _read_ro(_adult_path(data_dir, key))
    return {k: rec.get(k) for k in ("count", "groups", "titles", "panel", "more", "at", "source", "alert")} if rec else None


def admin_state(data_dir):
    """صفحة المدير: كل سيرفر بحاله وأعداده وأقسامه كلها (المخفية معلَّمة) وما أُسقط منه للكبار وما جدّ في
    آخر سحب — ورابطه مخفيًّا. ومعها لمن يصل تنبيه الكبار، وقناة واتساب ومنشورها. ولا تنتظر بناء عرض: الأعداد والأقسام
    من ملخّص كل سيرفر، وما لم يُبنَ لنسخة ملفه الحالية بعد يُعلَّم ‏loading ويُبنى في الخلفية، فتعود إليه الصفحة بعد لحظات."""
    try:
        alert = alert_info() if alert_info else None
    except Exception:  # noqa: BLE001 — حال التنبيه لا يُسقط الصفحة
        alert = None
    out = []
    for s in servers(data_dir):
        m, fresh = _summary(data_dir, s["key"], s, wait=False)
        m = m or {}
        cat = m.get("cat") or {}
        hidden = set(s["hidden"])
        url = crypto_store.decrypt(s["url"], data_dir) if s["url"] else ""
        out.append({
            "key": s["key"], "name": s["name"], "full": s["full"], "en": s["en"], "en_name": en_name(s), "buy": s["buy"],
            "page": f"{PATH}/{s['key']}", "page_en": f"{PATH_EN}/{s['key']}",
            "has": bool(m.get("has")), "at": m.get("at", 0), "source": cat.get("source", ""), "label": cat.get("label", ""),
            "counts": m.get("counts"), "entries": cat.get("entries", 0), "n": cat.get("n", {}),
            "skipped": cat.get("skipped", {}), "api": cat.get("api"), "old": bool(cat.get("old")), "loading": not fresh,
            "adult": _adult_view(data_dir, s["key"]),
            "news": (_read_ro(_news_path(data_dir, s["key"])) or {}).get("last"),
            "url": mask_url(url) if url else "", "try_at": s["try_at"],
            "error": s["error"], "busy": dict(_busy[s["key"]]) if s["key"] in _busy else None,
            "groups": {k: [[g, name, n, g in hidden] for g, name, n in (m.get("groups") or {}).get(k) or []]
                       for k in KINDS}})
    return {"servers": out, "refresh_hours": REFRESH // 3600, "alert": alert,
            "channel": channel_state(data_dir, wait=False)}


# ================= الجديد: ما أضيف في كل سحب، ومنشوره اليومي في قناة واتساب =================
# كل إدخالٍ (رفعٌ أو سحب) يُقارن فهرسه بما رُئي من ملف السيرفر قبله: الفيلم جديدٌ باسمه وسنته، والمسلسل
# باسمه، والحلقات بما زاد على أكثر ما رُئي من كل موسم. وما غاب ثم عاد ليس جديدًا، وأول فهرسٍ بدايةٌ لا جديد
# فيها. والقنوات لا تُعدّ: قنوات المباريات والأحداث تتبدّل أسماؤها كل يوم.
NEWS_KEEP = 14 * 86400        # ما جدّ يبقى في السجلّ أسبوعين
NEWS_LOG = 5000               # وحدّ السجلّ (الأحدث)
NEWS_SEEN = 100000            # بصمات ما رُئي لكل نوع: ما في الملف الآن كله، ثم الأحدث مما غاب
NEWS_FLOOD = 300              # أكثر من هذا ومن نصف النوع جديدًا في سحبٍ واحد: ملفٌّ تغيّرت أسماؤه لا جديد — بدايةٌ جديدة
_news_lock = threading.Lock() # السجلّ: الإدخال يكتب فيه والمنشور يقطعه عند لحظة، فلا يتداخلان (ولا ينتظرهما زوّار الصفحة)


def _news_state(cat):
    """الفهرس ← {movie: {بصمة: رصيد}، series: {…}}، والرصيد {it: العنصر، gs: أقسامه، s: {الموسم: الحلقات}} —
    والاسم في قسمين عنصرٌ واحد بأقسامه كلها ومواسمه منها كلها، كما في العرض."""
    out = {"movie": {}, "series": {}}
    for kind in out:
        for g in cat.get(kind) or []:
            for it in g.get("items") or []:
                if not isinstance(it, dict) or not it.get("n"):
                    continue
                rec = out[kind].setdefault(_gid(kind, _ikey(kind, it)), {"it": it, "gs": [], "s": {}})
                if g.get("id") and g["id"] not in rec["gs"]:
                    rec["gs"].append(g["id"])
                for s, n in it.get("s") or ():
                    if n > rec["s"].get(s, 0):
                        rec["s"][s] = n
    return out


def _record_news(data_dir, key, cat):
    """يسجّل ما جدّ في الفهرس عمّا رُئي من ملف السيرفر قبله ← ملخّصه {at, movie, series, eps, first?, flood?} (والمسلسلات
    ما جدّ فيه شيء: الجديدة وما زادت حلقاته). وبلا ذاكرةٍ بعدُ فهو بدايةٌ لا جديد فيها، ووقتها «start» في السجلّ: ما قبله
    يُعرف من تاريخ الإضافة في واجهة السيرفر (‏_panel). وما جدّ بأكثر من NEWS_FLOOD ومن نصف نوعه بدايةٌ جديدة: يُحفظ
    أنه رُئي ولا يُعدّ جديدًا."""
    cur = _news_state(cat)
    with _news_lock:
        now = time.time()                    # داخل القفل: منشور القناة يقطع السجلّ عند لحظةٍ لا يتخطّاها سحب
        mem = _read(_seen_path(data_dir, key))
        first = mem is None
        mem = mem or {}
        seen_m = [h for h in mem.get("movie") or [] if isinstance(h, str)]
        seen_s = {h: {int(s): int(n) for s, n in v} for h, v in (mem.get("series") or {}).items() if isinstance(v, list)}
        known = set(seen_m)
        movies = [] if first else [h for h in cur["movie"] if h not in known]
        fresh, more = [], []
        for h, rec in ([] if first else cur["series"].items()):
            was = seen_s.get(h)
            if was is None:
                fresh.append(h)
                continue
            # [الموسم، كم زاد، كم صار، موسمٌ جديد؟]
            add = [[s, n - was.get(s, 0), n, int(s not in was)] for s, n in sorted(rec["s"].items()) if n > was.get(s, 0)]
            if add:
                more.append((h, add))
        flood = []
        for kind, got, total in (("movie", movies, len(cur["movie"])), ("series", fresh, len(cur["series"])),
                                 ("eps", more, len(cur["series"]))):
            if len(got) > max(NEWS_FLOOD, total // 2):
                flood.append([kind, len(got)])
                got.clear()
        entries = []
        for h in movies:
            it = cur["movie"][h]["it"]
            entries.append(_slim({"t": now, "k": "movie", "h": h, "n": it["n"], "y": it.get("y"), "r": it.get("r"),
                                  "gs": cur["movie"][h]["gs"]}))
        for h in fresh:
            rec = cur["series"][h]
            entries.append(_slim({"t": now, "k": "series", "new": 1, "h": h, "n": rec["it"]["n"], "y": rec["it"].get("y"),
                                  "r": rec["it"].get("r"), "gs": rec["gs"], "s": sorted(rec["s"].items())}))
        for h, add in more:
            rec = cur["series"][h]
            entries.append(_slim({"t": now, "k": "series", "h": h, "n": rec["it"]["n"], "y": rec["it"].get("y"),
                                  "r": rec["it"].get("r"), "gs": rec["gs"], "add": add}))
        # ما في الملف الآن آخرًا (فلا يُقصّ)، وقبله ما غاب منه بترتيبه — والقصّ من أقدمه
        seen_m = [h for h in seen_m if h not in cur["movie"]] + list(cur["movie"])
        for h, rec in cur["series"].items():
            was = seen_s.pop(h, {})
            for s, n in rec["s"].items():
                was[s] = max(was.get(s, 0), n)
            seen_s[h] = was
        _write(_seen_path(data_dir, key), {"movie": seen_m[-NEWS_SEEN:],
                                            "series": {h: sorted(v.items()) for h, v in list(seen_s.items())[-NEWS_SEEN:]}})
        eps = sum(sum(cur["series"][h]["s"].values()) for h in fresh) + sum(a[1] for _h, add in more for a in add)
        last = _slim({"at": now, "movie": len(movies), "series": len(fresh) + len(more), "eps": eps, "first": first,
                      "flood": flood})
        old = _read(_news_path(data_dir, key)) or {}
        log = [e for e in old.get("log") or [] if isinstance(e, dict) and (e.get("t") or 0) >= now - NEWS_KEEP] + entries
        _write(_news_path(data_dir, key), {"log": log[-NEWS_LOG:], "last": last, "start": _news_start(old) or now})
    return last


def _news_start(rec):
    """من متى يعرف سجلّ السيرفر ما جدّ: وقت أول سحبٍ سُجّل بعد هذه الميزة (بدايته) — أو None بلا سجلّ. (وسجلٌّ من نسخةٍ
    لم تحفظه: أول ما فيه.)"""
    if not rec:
        return None
    if rec.get("start"):
        return _float(rec["start"])
    ts = [e.get("t") or 0 for e in rec.get("log") or [] if isinstance(e, dict)]
    return min(ts) if ts else _float((rec.get("last") or {}).get("at")) or None


def _pending(data_dir, key, since, until, hidden=(), wait=True):
    """ما جدّ في السيرفر في (since, until] ← (الأفلام، المسلسلات الجديدة، مسلسلاتٌ جدّت حلقاتها)، كلٌّ {بصمة: عنصر}:
    من السجلّ الفيلم والمسلسل مرة، وحلقات المسلسل من كل سحبٍ مجموعةً بموسمها {الموسم: [زادت، صارت، جديد؟]} (والمسلسل
    الجديد يضمّ ما جدّ من حلقاته بعده) — وما قبل بداية السجلّ (أو بلا سجلٍّ بعد) من تاريخ الإضافة في واجهة السيرفر
    كما في «أضيف مؤخرًا» في الصفحة (‏_panel). وما أقسامه كلها مخفيةٌ من الصفحة لا يُعدّ. وبلا انتظار (‏wait=False) ← None
    إن احتاج عرض السيرفر ولم يُبنَ بعد."""
    movies, fresh, more = {}, {}, {}
    rec = _read_ro(_news_path(data_dir, key)) or {}
    for e in rec.get("log") or []:
        if not isinstance(e, dict) or not e.get("h") or not since < (e.get("t") or 0) <= until:
            continue
        if e.get("gs") and all(g in hidden for g in e["gs"]):
            continue
        h = e["h"]
        if e.get("k") == "movie":
            movies[h] = e
        elif e.get("new"):
            fresh[h] = dict(e, s={int(s): n for s, n in e.get("s") or ()})
        elif h in fresh:
            for s, _d, n, _new in e.get("add") or ():
                fresh[h]["s"][int(s)] = max(fresh[h]["s"].get(int(s), 0), n)
        else:
            m = more.setdefault(h, {"add": {}})
            m.update({k: e.get(k) for k in ("h", "n", "y", "r", "gs")})
            for s, d, n, new in e.get("add") or ():
                a = m["add"].setdefault(int(s), [0, 0, 0])
                a[0], a[1], a[2] = a[0] + d, max(a[1], n), a[2] or new
    start = _news_start(rec)
    edge = until if start is None else min(until, start)
    if since < edge:                         # ما قبل السجلّ: لا يلتقي به (السجلّ ما لم يكن في سحب بدايته)
        got = _panel(data_dir, key, since, edge, set(movies) | set(fresh) | set(more), wait)
        if got is None:
            return None
        movies.update(got[0])
        more.update(got[1])
    return movies, fresh, more


def _panel(data_dir, key, since, until, known=(), wait=True):
    """ما أضافته لوحة السيرفر في (since, until] بتاريخه من واجهة Xtream (‏a: إضافة الفيلم، وآخر تحديثٍ للمسلسل) —
    ما يعرضه «أضيف مؤخرًا» في الصفحة — من أقسامها الظاهرة، بلا ما في known ← (أفلام، مسلسلات) كعناصر _pending، والمسلسل
    بموسمه الأخير وحلقاته (‏cur) إذ لا يُعرف كم جدّ منها. ونوعٌ غيّرت اللوحة تواريخه كلها (أكثر من NEWS_FLOOD ومن
    نصفه) لا يُعدّ منه شيء. وبلا انتظار (‏wait=False) ← None إن لم يُبنَ عرض السيرفر بعد."""
    v = _view(data_dir, key)[1] if wait else _ready(data_dir, key)
    if v is False:
        return None
    out = {"movie": {}, "series": {}}
    if not v:
        return out["movie"], out["series"]
    for kind, got in out.items():
        gs = v["kinds"][kind]
        for gi, ii in _added(v, kind, since, until):
            g, it = gs[gi], gs[gi]["items"][ii]
            h = _gid(kind, _ikey(kind, it))
            if h in known:
                continue
            x = got.get(h)
            if x is None:
                x = got[h] = dict(_slim({"h": h, "n": it.get("n"), "y": it.get("y"), "r": it.get("r"), "a": it["a"]}), gs=[])
                if kind == "series":
                    ss = [(s, n) for s, n in it.get("s") or () if s] or [(0, sum(n for _s, n in it.get("s") or ()))]
                    x.update(add={}, cur=list(max(ss)))
            x["gs"].append(g["id"])
        if len(got) > max(NEWS_FLOOD, v["counts"][kind] // 2):
            got.clear()
    return out["movie"], out["series"]


_INF = float("inf")


def _added(v, kind, since, until):
    """مواضع عناصر النوع التي أضافتها لوحة السيرفر في (since, until] ← [(القسم، العنصر)] بترتيب الصفحة — من قائمةٍ مرتّبةٍ
    بتاريخ الإضافة تُبنى أول مرة، فلا يُمرّ على الفهرس كله مع كل تحميلٍ لصفحة المدير."""
    dated = v.get("_dated")
    if dated is None:
        dated = v["_dated"] = {k: sorted((it["a"], gi, ii) for gi, g in enumerate(v["kinds"][k])
                                         for ii, it in enumerate(g["items"])
                                         if isinstance(it.get("a"), (int, float)) and it["a"] > 0)
                               for k in ("movie", "series")}
    lst = dated[kind]
    lo, hi = bisect.bisect_right(lst, (since, _INF)), bisect.bisect_right(lst, (until, _INF))
    return sorted((gi, ii) for _a, gi, ii in lst[lo:hi])


def _tally(movies, fresh, more):
    """الأعداد {movie، series، eps}: المسلسلات ما جدّ فيه شيء، والحلقات ما في المسلسلات الجديدة وما جدّ في غيرها (وما
    حدّثته اللوحة لا يُعرف كم جدّ فيه)."""
    return {"movie": len(movies), "series": len(fresh) + len(more),
            "eps": sum(sum(x["s"].values()) for x in fresh.values()) + sum(a[0] for x in more.values() for a in x["add"].values())}


# ----- المنشور: «أضيف مؤخرًا» بتنسيق واتساب -----
RIYADH = 3 * 3600             # توقيت السعودية (بلا توقيتٍ صيفي)
_DAYS = ("الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد")
_MONTHS = ("يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر")
POST_LINES = {"movie": 8, "series": 5, "eps": 8}   # سطور كل قسمٍ لسيرفرٍ واحد، وتقلّ بعدد السيرفرات (ولا تنقص عن 3)
POST_NAME = 60                # طول الاسم في السطر
RLM = "‏"                # أول سطر العنصر: يبقى من اليمين وإن بدأ باسمٍ إنجليزي
SEP = "━━━━━━━━━━━━"
_WA_MARKS = str.maketrans({"*": "∗", "_": " ", "~": "-", "`": "'"})   # علامات تنسيق واتساب في الأسماء لا تنسّق شيئًا


def _local(ts):
    return time.gmtime(ts + RIYADH)


def _day(ts):
    """يوم الوقت بتوقيت السعودية «2026-09-29» — يوم المنشور المجدول."""
    return time.strftime("%Y-%m-%d", _local(ts))


def ar_date(ts):
    """«الثلاثاء 29 سبتمبر 2026» بتوقيت السعودية."""
    t = _local(ts)
    return f"{_DAYS[t.tm_wday]} {t.tm_mday} {_MONTHS[t.tm_mon - 1]} {t.tm_year}"


def _wa(s):
    return " ".join(str(s or "").translate(_WA_MARKS).split())


def _title(x, year=True):
    n = _wa(x.get("n"))
    n = n if len(n) <= POST_NAME else n[:POST_NAME - 1].rstrip() + "…"
    return f"{n} ({x['y']})" if year and x.get("y") else n


def _stars(x):
    return f" ⭐ {float(x['r']):.1f}" if x.get("r") else ""


def _movie_line(x):
    return _title(x) + _stars(x)


def _series_line(x):
    """«Shōgun (2024) · 10 حلقات ⭐ 8.7» — والمسلسل بأكثر من موسمٍ بعدد مواسمه."""
    seasons = [s for s in x["s"] if s]
    size = _count(len(seasons), N_SEASONS) if len(seasons) > 1 else _count(sum(x["s"].values()), N_EPISODES)
    return f"{_title(x)} · {size}{_stars(x)}"


def _more_line(x):
    """«The Boys · الموسم 4 · 3 حلقات» · «House of the Dragon · الموسم 2 (جديد) · 8 حلقات» — وما حدّثته اللوحة ولا يُعرف
    كم جدّ فيه: موسمه الأخير وحلقاته «The Boys · الموسم 4 (8 حلقات)»."""
    if not x["add"]:
        s, n = x.get("cur") or (0, 0)
        return f"{_title(x, year=False)} · الموسم {s} ({_count(n, N_EPISODES)})" if s else \
            f"{_title(x, year=False)} ({_count(n, N_EPISODES)})"
    ss = sorted(s for s in x["add"] if s)
    if len(ss) == 1:
        where = f"الموسم {ss[0]}" + (" (جديد)" if x["add"][ss[0]][2] else "")
    else:
        where = "المواسم " + "، ".join(map(str, ss[:-1])) + f" و{ss[-1]}" if ss else ""
    eps = _count(sum(a[0] for a in x["add"].values()), N_EPISODES)
    return " · ".join(p for p in (_title(x, year=False), where, eps) if p)


def _lines(rows, limit, line, forms):
    """سطور القسم بأوّلها والباقي عدد — وواحدٌ زائد يُعرض بدل «ووحدٌ غيره»."""
    if len(rows) == limit + 1:
        limit += 1
    out = [f"{RLM}• {line(x)}" for x in rows[:limit]]
    if len(rows) > limit:
        out.append(f"{RLM}   …و{_count(len(rows) - limit, forms)} غيرها")
    return out


def _counts(n):
    return " · ".join(p for p in (_count(n["movie"], N_MOVIES) if n["movie"] else "",
                                  _count(n["series"], N_SERIES) if n["series"] else "",
                                  _count(n["eps"], N_EPISODES) if n["eps"] else "") if p)


def channel_text(data_dir, keys, since, until, now=None):
    """منشور «أضيف مؤخرًا» لما سُجّل في (since, until] من السيرفرات keys (بترتيبها في الصفحة) ← (النص، الأعداد
    {movie، series، eps}) — والنص فارغٌ إن لم يجدّ شيء. الإصدارات الحديثة أولًا ثم الأعلى تقييمًا، والمواسم
    الجديدة أولًا، ولكل سيرفرٍ رابط «أضيف مؤخرًا» في صفحته."""
    now = now or time.time()
    parts, total = [], {"movie": 0, "series": 0, "eps": 0}
    for s in servers(data_dir):
        if s["key"] not in keys:
            continue
        movies, fresh, more = _pending(data_dir, s["key"], since, until, set(s["hidden"]))
        if movies or fresh or more:
            n = _tally(movies, fresh, more)
            parts.append((s, movies, fresh, more, n))
            total = {k: total[k] + n[k] for k in total}
    if not parts:
        return "", total
    yr = _local(now).tm_year

    def rank(x):
        y = x.get("y") or 0
        return y < yr - 1, -(x.get("r") or 0), -y, _norm(x.get("n", ""))

    def rank_more(x):
        return (not any(a[2] for a in x["add"].values()), -(x.get("r") or 0),
                -sum(a[0] for a in x["add"].values()), _norm(x.get("n", "")))

    single = len(parts) == 1
    lim = {k: max(3, v * 2 // (len(parts) + 1)) for k, v in POST_LINES.items()}
    out = [f"🆕 *أضيف مؤخرًا{' في ' + _wa(parts[0][0]['name']) if single else ''}*", f"🗓️ {ar_date(now)}"]
    for s, movies, fresh, more, n in parts:
        out += ["", f"✨ الجديد: {_counts(n)}"] if single else ["", SEP, f"📡 *{_wa(s['name'])}*", f"✨ {_counts(n)}"]
        if movies:
            out += ["", "🎬 *أفلام جديدة*"] + _lines(sorted(movies.values(), key=rank), lim["movie"], _movie_line, N_MOVIES)
        if fresh:
            out += ["", "📺 *مسلسلات جديدة*"] + _lines(sorted(fresh.values(), key=rank), lim["series"], _series_line, N_SERIES)
        if more:
            out += ["", "🎞️ *حلقات ومواسم جديدة*"] + _lines(sorted(more.values(), key=rank_more), lim["eps"],
                                                             _more_line, N_SERIES)
        link = f"{guide_pages.SITE}{PATH}/{s['key']}?t=new&ref=wa"    # ref=wa: زيارات القناة باسمها في الإحصائيات
        out += ["", "🔗 القائمة كاملة، وابحث باسم ما تريد:", link] if single else ["", f"🔗 القائمة كاملة: {link}"]
    return "\n".join(out), total


# ----- قناة واتساب: ربطها، ومنشورها اليومي في ساعته -----
CHANNEL_HOUR = 21             # ساعة المنشور الافتراضية بتوقيت السعودية (9 مساءً)
CHANNEL_RETRY = 1800          # منشور اليوم إن لم يُرسل يُعاد بعد نصف ساعة، في يومه
CHANNEL_WINDOW = 3 * 86400    # ولا يعود أبعد من ثلاثة أيام: قناةٌ توقّفت أسبوعًا لا تنشر أسبوعًا دفعةً
CHANNEL_FIRST = 86400         # وأول منشورٍ بعد ربط القناة بما جدّ في اليوم الذي قبله
_JID = re.compile(r"\d{5,30}@newsletter")
_INVITE = re.compile(r"(?:https?://)?(?:www\.)?whatsapp\.com/channel/([A-Za-z0-9]{10,40})", re.I)
channel_sender = None         # (معرّف القناة، النص) ← {ok, error} — يضبطه الخادم: من رقم المسابقة المربوط
_posting = threading.Lock()   # منشورٌ واحد في وقته: المجدول و«انشر الآن» لا يلتقيان


def channel_ref(v):
    """ما يلصقه المدير ← ("invite"، الرمز) من رابط القناة (‏whatsapp.com/channel/<الرمز>)، أو ("jid"، المعرّف) من
    معرّفها (‏…@newsletter أو أرقامه)، أو None."""
    v = str(v or "").strip()
    m = _INVITE.search(v)
    if m:
        return "invite", m.group(1)
    j = re.sub(r"\s+", "", v).lower()
    if _JID.fullmatch(j):
        return "jid", j
    if re.fullmatch(r"\d{5,30}", j):
        return "jid", j + "@newsletter"
    if re.fullmatch(r"0029[A-Za-z0-9]{6,36}", v):
        return "invite", v
    return None


def channel(data_dir):
    """قناة واتساب كما حُفظت ← {on, jid, name, invite, role, subs, servers, hour, since, day, last, posted}: day يوم
    آخر منشورٍ مجدول (أُرسل أو لم يجدّ فيه شيء)، وsince ما بعده جديدٌ لم يُنشر، وlast آخر محاولة وposted آخر ما نُشر."""
    c = (_read(os.path.join(_dir(data_dir), SETTINGS)) or {}).get("channel")
    c = c if isinstance(c, dict) else {}
    jid, hour = str(c.get("jid") or ""), c.get("hour")
    return {"on": bool(c.get("on")), "jid": jid if _JID.fullmatch(jid) else "", "name": str(c.get("name") or "")[:100],
            "invite": str(c.get("invite") or "")[:60], "role": str(c.get("role") or "")[:20], "subs": int(_float(c.get("subs"))),
            "servers": [k for k in c.get("servers") or [] if isinstance(k, str) and key_ok(k) == k][:MAX_SERVERS],
            "hour": hour if type(hour) is int and 0 <= hour <= 23 else CHANNEL_HOUR,
            "since": _float(c.get("since")), "day": str(c.get("day") or "")[:10],
            "last": c.get("last") if isinstance(c.get("last"), dict) else None,
            "posted": c.get("posted") if isinstance(c.get("posted"), dict) else None}


def save_channel(data_dir, **kw):
    """يحفظ ما تغيّر من إعداد القناة (والباقي كما هو) ← الإعداد كله. والتحقّق من القيم على الخادم قبله."""
    with _lock:
        path = os.path.join(_dir(data_dir), SETTINGS)
        s = _read(path) or {}
        c = s.get("channel") if isinstance(s.get("channel"), dict) else {}
        c.update(kw)
        s["channel"] = c
        _write(path, s)
    return channel(data_dir)


def link_channel(data_dir, jid, name="", invite="", role="", subs=0):
    """يحفظ القناة التي عرفها رقم المسابقة. وقناةٌ غير المحفوظة تبدأ من جديد: أول منشورٍ بما جدّ في اليوم الذي قبله."""
    extra = {} if jid == channel(data_dir)["jid"] else {"since": time.time() - CHANNEL_FIRST, "day": "", "last": None,
                                                         "posted": None}
    return save_channel(data_dir, jid=jid, name=str(name or "")[:100], invite=str(invite or "")[:60],
                        role=str(role or "")[:20], subs=int(_float(subs)), **extra)


def channel_preview(data_dir, keys=None, days=0, now=None):
    """المنشور كما سيُنشر الآن ← {text, n, since, until}: ما جدّ منذ آخر منشور (وأبعده CHANNEL_WINDOW)، أو ما جدّ
    في آخر `days` يومًا للمعاينة. وkeys سيرفراتٌ غير المحفوظة (ما اختاره المدير ولم يحفظه بعد)."""
    c = channel(data_dir)
    keys = [k for k in keys if isinstance(k, str)] if isinstance(keys, list) else c["servers"]
    with _news_lock:
        until = time.time()
        since = until - min(int(days), NEWS_KEEP // 86400) * 86400 if days else max(c["since"], until - CHANNEL_WINDOW)
        text, n = channel_text(data_dir, keys, since, until, now)
    return {"text": text, "n": n, "since": since, "until": until}


def channel_run(data_dir, manual=False, now=None):
    """ينشر في القناة ما جدّ منذ آخر منشور ← {ok, empty?, error?, n?}. ويوم المجدول يُعلَّم (أُرسل أو لم يجدّ شيء)
    فلا يُعاد، وفشله يُعاد بعد CHANNEL_RETRY؛ و«انشر الآن» (‏manual) لا يمسّ اليوم، وبلا جديدٍ لا يُحفظ."""
    if not _posting.acquire(blocking=False):
        return {"ok": False, "error": "يُنشر الآن في القناة"}
    try:
        now = now or time.time()
        c = channel(data_dir)
        if not c["jid"]:
            return {"ok": False, "error": "اربط قناة واتساب أولًا"}
        if not c["servers"]:
            return {"ok": False, "error": "اختر السيرفرات في المنشور واحفظ"}
        with _news_lock:                     # لحظة القطع داخل القفل: ما سُجّل بعدها للمنشور التالي
            until = time.time()
            text, n = channel_text(data_dir, c["servers"], max(c["since"], until - CHANNEL_WINDOW), until, now)
        if not text:
            if manual:
                return {"ok": False, "empty": True, "error": "لا جديد منذ آخر منشور"}
            save_channel(data_dir, day=_day(now), last={"at": now, "ok": True, "empty": True})
            return {"ok": True, "empty": True}
        try:
            res = channel_sender(c["jid"], text) if channel_sender else {"error": "النشر غير مضبوط على هذا الخادم"}
        except Exception as e:  # noqa: BLE001 — الفشل يُحفظ سببه ويُعاد
            res = {"error": str(e)[:200]}
        ok = bool(isinstance(res, dict) and res.get("ok"))
        last = {"at": now, "ok": ok, "n": n, "manual": manual,
                "error": "" if ok else str((res if isinstance(res, dict) else {}).get("error") or "تعذّر النشر")[:200]}
        upd = {"last": last}
        if ok:
            upd.update(since=until, posted=last, **({} if manual else {"day": _day(now)}))
        save_channel(data_dir, **upd)
        return dict(last)
    finally:
        _posting.release()


def channel_tick(data_dir, now=None):
    """دورة الخلفية: منشور اليوم إن كانت القناة مفعّلة، وبلغت ساعته بتوقيت السعودية، ولم يُنشر اليوم — وفشلٌ
    قبل أقل من CHANNEL_RETRY ينتظر. ← نتيجة المنشور أو None."""
    now = now or time.time()
    c = channel(data_dir)
    if not (c["on"] and c["jid"] and c["servers"]) or _local(now).tm_hour < c["hour"] or c["day"] == _day(now):
        return None
    last = c["last"] or {}
    if not last.get("manual") and not last.get("ok") and now - (last.get("at") or 0) < CHANNEL_RETRY:
        return None
    return channel_run(data_dir, now=now)


def channel_state(data_dir, wait=True):
    """قناة واتساب لصفحة المدير: إعدادها وآخر منشورٍ فيها، وأعداد ما جدّ منذه (‏pending) من سيرفراتها — لقناةٍ مربوطة.
    وبلا انتظار (‏wait=False): ‏pending ‏None إن احتاج عرض سيرفرٍ لم يُبنَ بعد، ويُبنى في الخلفية."""
    c = channel(data_dir)
    until = time.time()
    since = max(c["since"], until - CHANNEL_WINDOW)
    pending, wanting = {"movie": 0, "series": 0, "eps": 0}, False
    for s in servers(data_dir) if c["jid"] else ():
        if s["key"] in c["servers"]:
            got = _pending(data_dir, s["key"], since, until, set(s["hidden"]), wait)
            if got is None:
                wanting = True
                continue
            n = _tally(*got)
            pending = {k: pending[k] + n[k] for k in pending}
    return dict({k: v for k, v in c.items() if k != "since"}, pending=None if wanting else pending, since=since)

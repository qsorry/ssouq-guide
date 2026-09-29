# -*- coding: utf-8 -*-
"""إحصائيات الدليل (guide.ssouq.com): عدّادٌ من خادمنا بلا كوكيز ولا بياناتٍ شخصية، وما يُربط بالموقع لزيادة زوّاره.

- **الزيارة**: سكربتٌ صغير في كل صفحة عامة (‏`/static/sq.js`) يرسل إلى `/api/hit` المشاهدةَ ومصدرها ومدة
  قراءتها، ونقراتِ الشراء وواتساب والمشاركة وخطوات المعالج. تُجمع **أعدادًا** في ملفٍّ لكل يوم بتوقيت السعودية
  (‏`data/analytics/days/2026-09-29.json`): لا يُحفظ عنوان IP ولا مسار زائرٍ بعينه.
- **الزائر الفريد** في يومه بصمةٌ من (IP + المتصفح + ملح اليوم)، والملح يُولَّد لكل يوم ويُمحى بانتهائه، فلا
  تُربط بصمة يومٍ بيومٍ غيره (طريقة Plausible). وزوّار المدة = مجموع زوّار أيامها.
- **المصدر** من المُحيل ومن `utm_source` و`?ref=wa` ومن متصفح التطبيق (سناب وإنستغرام وتيك توك وفيسبوك تفتح
  الروابط في متصفحها بلا مُحيل)، والدولة من `CF-IPCountry` إن وُجد وإلا من المنطقة الزمنية للجهاز (تقريبية).
- **الزواحف**: زيارات جوجل وبينج ومساعدي الذكاء الاصطناعي، ومعاينات الروابط (واتساب وغيره: كل معاينةٍ مشاركةُ
  رابطٍ في محادثة) تُعدّ من الخادم لكل صفحة، فلا تدخل أعداد الزوّار.
- **الربط** (من صفحة الإحصائيات): Google Analytics 4 وTag Manager وClarity وبيكسلات سناب وتيك توك وميتا،
  ووسما التحقّق لـ Search Console وBing — كلها تُحقن في `<head>` كل صفحة عامة من مكانٍ واحد (‏`inject`).
- **IndexNow**: مفتاحٌ يُقدَّم على `/<المفتاح>.txt`، وصفحات الموقع تُرسَل إلى Bing وYandex وغيرهما — يدويًا،
  ثم كل يوم وحدها للصفحات التي تتغيّر يوميًا (بعد أول إرسالٍ ناجح).
"""
import datetime
import hashlib
import json
import os
import re
import secrets
import threading
import time
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import crypto_store

HIT = "/api/hit"                        # نقطة السكربت (عامة، بلا تسجيل)
SCRIPT = "/static/sq.js"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RIYADH = datetime.timezone(datetime.timedelta(hours=3))
SUBDIR = "analytics"
SETTINGS = "settings.json"
KEEP_DAYS = 800                         # ملفات الأيام الأقدم تُحذف (أكثر من سنتين للمقارنة بالعام الماضي)
FLUSH_EVERY = 10                        # ثوانٍ: أعداد اليوم تُكتب على القرص بعدها
LIVE = 300                              # «الآن» = من أرسل شيئًا في آخر خمس دقائق
RATE = 90                               # حدّ الإرسال للزائر في الدقيقة (ما زاد يُهمل)
MAX_SEEN = 300000                       # بصمات اليوم: ما بعدها لا يُعدّ زائرًا جديدًا (سيلٌ مصطنع لا يملأ الذاكرة)
MAX_BODY = 4096
CAP = 400                               # أقصى مفاتيح القائمة الواحدة في اليوم (الصفحات، المُحيلون…) — والزائد «أخرى»
CAP_EVENTS, CAP_LABELS = 40, 150
OTHER = "(other)"
MAX_DUR = 1800                          # مدة قراءة الصفحة تُقصّ عند نصف ساعة

# ================= التصنيف: الجهاز والنظام والمصدر والدولة =================
_BOT_UA = re.compile(r"bot|crawl|spider|slurp|headless|lighthouse|pagespeed|preview|monitor|pingdom|uptime|"
                     r"curl|wget|python|axios|node-fetch|go-http|java/|okhttp|httpclient|scrapy|phantom|"
                     r"facebookexternalhit|^whatsapp/", re.I)
_TV = re.compile(r"SmartTV|SMART-TV|Tizen.*TV|Web0S|WebOS|NetCast|HbbTV|BRAVIA|AFT[A-Z]|Android TV|GoogleTV|"
                 r"CrKey|AppleTV|Roku|TV Safari|; TV;|VIDAA", re.I)

# المُحيل (نطاقه أو حزمة تطبيق أندرويد من `android-app://…`) ← المصدر. الترتيب مقصود: gemini قبل جوجل.
_SOURCES = [(k, re.compile(p, re.I)) for k, p in (
    ("gemini", r"^gemini\.google\.com$|^bard\.google\.com$"),
    ("email", r"^mail\.google\.com$|(^|\.)outlook\.(live|office)\.com$|^mail\.yahoo\.com$|^com\.google\.android\.gm$"),
    ("google", r"(^|\.)google\.(com|[a-z]{2}|com?\.[a-z]{2})$|^com\.google\.android\.(googlequicksearchbox|apps\.searchlite)$"),
    ("copilot", r"^copilot\.microsoft\.com$"),
    ("bing", r"(^|\.)bing\.com$"),
    ("yahoo", r"(^|\.)yahoo\.(com|co\.jp)$"),
    ("duckduckgo", r"(^|\.)duckduckgo\.com$"),
    ("yandex", r"(^|\.)yandex\.[a-z.]+$|^ya\.ru$"),
    ("chatgpt", r"(^|\.)(chatgpt\.com|openai\.com)$|^com\.openai\.chatgpt$"),
    ("perplexity", r"(^|\.)perplexity\.ai$"),
    ("claude", r"(^|\.)claude\.ai$"),
    ("whatsapp", r"(^|\.)(whatsapp\.com|whatsapp\.net|wa\.me)$|^com\.whatsapp(\.w4b)?$"),
    ("snapchat", r"(^|\.)snapchat\.com$|^com\.snapchat\.android$"),
    ("tiktok", r"(^|\.)tiktok\.com$|^com\.(zhiliaoapp\.musically|ss\.android\.ugc\.trill)$"),
    ("instagram", r"(^|\.)instagram\.com$|^com\.instagram\.android$"),
    ("facebook", r"(^|\.)(facebook\.com|fb\.com|messenger\.com)$|^com\.facebook\.(katana|orca|lite)$"),
    ("x", r"^t\.co$|(^|\.)(twitter\.com|x\.com)$|^com\.twitter\.android$"),
    ("youtube", r"(^|\.)(youtube\.com|youtu\.be)$|^com\.google\.android\.youtube$"),
    ("telegram", r"^t\.me$|(^|\.)telegram\.(org|me)$|^org\.telegram\.(messenger|plus)$"),
    ("linkedin", r"(^|\.)(linkedin\.com|lnkd\.in)$"),
    ("reddit", r"(^|\.)reddit\.com$"),
    ("store", r"(^|\.)ssouq\.com$|(^|\.)salla\.(sa|com)$"),
)]
# متصفح داخل تطبيق يفتح الروابط بلا مُحيل: هو نفسه يدلّ على المصدر
_INAPP = [(k, re.compile(p)) for k, p in (
    ("snapchat", r"Snapchat"), ("instagram", r"Instagram"), ("facebook", r"FBAN|FBAV|FB_IAB"),
    ("tiktok", r"musical_ly|BytedanceWebview|TikTok"), ("google", r"\bGSA/"),
)]
# أسماء مختصرة يكتبها المدير في utm_source أو ?ref= ← المصدر نفسه الذي يُصنّف به المُحيل
_ALIAS = {"wa": "whatsapp", "whatsapp": "whatsapp", "wa-channel": "whatsapp", "snap": "snapchat", "sc": "snapchat",
          "snapchat": "snapchat", "tt": "tiktok", "tiktok": "tiktok", "ig": "instagram", "insta": "instagram",
          "instagram": "instagram", "fb": "facebook", "facebook": "facebook", "meta": "facebook", "x": "x",
          "twitter": "x", "tw": "x", "yt": "youtube", "youtube": "youtube", "tg": "telegram", "telegram": "telegram",
          "google": "google", "bing": "bing", "store": "store", "ssouq": "store", "ssouq.com": "store",
          "salla": "store", "email": "email", "mail": "email", "sms": "sms", "qr": "qr", "chatgpt": "chatgpt"}

# المنطقة الزمنية للجهاز ← الدولة (تقريبية؛ تُفضَّل عليها CF-IPCountry إن مرّ الموقع بـ Cloudflare)
_TZ = dict(p.split("=") for p in (
    "Asia/Riyadh=SA Asia/Aden=YE Asia/Kuwait=KW Asia/Bahrain=BH Asia/Qatar=QA Asia/Dubai=AE Asia/Muscat=OM "
    "Asia/Baghdad=IQ Asia/Amman=JO Asia/Damascus=SY Asia/Beirut=LB Asia/Gaza=PS Asia/Hebron=PS Africa/Cairo=EG "
    "Africa/Khartoum=SD Africa/Tripoli=LY Africa/Tunis=TN Africa/Algiers=DZ Africa/Casablanca=MA "
    "Africa/El_Aaiun=MA Africa/Nouakchott=MR Africa/Mogadishu=SO Africa/Djibouti=DJ Asia/Tehran=IR "
    "Europe/Istanbul=TR Asia/Istanbul=TR Asia/Karachi=PK Asia/Kolkata=IN Asia/Calcutta=IN Asia/Dhaka=BD "
    "Asia/Kathmandu=NP Asia/Colombo=LK Asia/Manila=PH Asia/Jakarta=ID Asia/Kuala_Lumpur=MY Asia/Singapore=SG "
    "Asia/Bangkok=TH Asia/Shanghai=CN Asia/Hong_Kong=HK Asia/Tokyo=JP Asia/Seoul=KR Asia/Tashkent=UZ "
    "Asia/Almaty=KZ Asia/Kabul=AF Africa/Addis_Ababa=ET Africa/Nairobi=KE Africa/Lagos=NG "
    "Africa/Johannesburg=ZA Europe/London=GB Europe/Dublin=IE Europe/Berlin=DE Europe/Paris=FR "
    "Europe/Amsterdam=NL Europe/Brussels=BE Europe/Luxembourg=LU Europe/Zurich=CH Europe/Vienna=AT "
    "Europe/Stockholm=SE Europe/Oslo=NO Europe/Copenhagen=DK Europe/Helsinki=FI Europe/Madrid=ES "
    "Europe/Lisbon=PT Europe/Rome=IT Europe/Athens=GR Europe/Warsaw=PL Europe/Prague=CZ Europe/Budapest=HU "
    "Europe/Bucharest=RO Europe/Sofia=BG Europe/Kiev=UA Europe/Kyiv=UA Europe/Moscow=RU "
    "America/Toronto=CA America/Vancouver=CA America/Edmonton=CA America/Winnipeg=CA America/Halifax=CA "
    "America/Mexico_City=MX America/Sao_Paulo=BR America/Argentina/Buenos_Aires=AR "
    "Australia/Sydney=AU Australia/Melbourne=AU Australia/Brisbane=AU Australia/Perth=AU "
    "Australia/Adelaide=AU Pacific/Auckland=NZ").split())
_US_TZ = re.compile(r"^America/(New_York|Chicago|Denver|Los_Angeles|Phoenix|Detroit|Anchorage|Boise|"
                    r"Indiana/|Kentucky/|North_Dakota/)|^Pacific/Honolulu$")

# زواحف تُعدّ من الخادم: (الاسم، النوع، النمط). search محركات البحث · ai مساعدو الذكاء الاصطناعي ·
# share معاينة رابطٍ لصقه أحدٌ في محادثة أو منشور (فهي مشاركة)
_CRAWLERS = [(n, k, re.compile(p, re.I)) for n, k, p in (
    ("Google", "search", r"Googlebot|Google-InspectionTool|GoogleOther|Storebot-Google|AdsBot-Google"),
    ("Bing", "search", r"bingbot|BingPreview|msnbot|adidxbot"),
    ("Apple", "search", r"Applebot"),
    ("Yandex", "search", r"Yandex(Bot|Mobile|Images)"),
    ("DuckDuckGo", "search", r"DuckDuckBot|DuckAssistBot"),
    ("Baidu", "search", r"Baiduspider"),
    ("Petal", "search", r"PetalBot"),
    ("ChatGPT", "ai", r"GPTBot|OAI-SearchBot|ChatGPT-User"),
    ("Claude", "ai", r"ClaudeBot|Claude-User|Claude-SearchBot|anthropic-ai"),
    ("Perplexity", "ai", r"PerplexityBot|Perplexity-User"),
    ("Meta AI", "ai", r"meta-externalagent|meta-externalfetcher"),
    ("ByteDance", "ai", r"Bytespider"),
    ("Amazon", "ai", r"Amazonbot"),
    ("Common Crawl", "ai", r"CCBot"),
    ("WhatsApp", "share", r"^WhatsApp/"),
    ("Facebook", "share", r"facebookexternalhit|facebookcatalog|Facebot"),
    ("X", "share", r"Twitterbot"),
    ("Telegram", "share", r"TelegramBot"),
    ("Snapchat", "share", r"Snap URL Preview"),
    ("Discord", "share", r"Discordbot"),
    ("Slack", "share", r"Slackbot"),
    ("LinkedIn", "share", r"LinkedInBot"),
)]
BOT_KINDS = {n: k for n, k, _ in _CRAWLERS}

_PATH_OK = re.compile(r"^/[\w\-./%~@:+,]*$")
_EVENT = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
_CTRL = re.compile(r"[\x00-\x1f\x7f<>\"'`\\]")


def device(ua, touch=0):
    if _TV.search(ua):
        return "tv"
    if re.search(r"iPad|Tablet|PlayBook|Silk|Kindle", ua) or ("Android" in ua and "Mobile" not in ua):
        return "tablet"
    if "Macintosh" in ua and touch > 1:            # iPadOS يعرّف نفسه ماك، ويكشفه اللمس
        return "tablet"
    if re.search(r"Mobi|iPhone|iPod|Android|Windows Phone|BlackBerry|Opera Mini", ua):
        return "mobile"
    return "desktop"


def os_name(ua, touch=0):
    if re.search(r"iPhone|iPad|iPod", ua) or ("Macintosh" in ua and touch > 1):
        return "ios"
    if "Android" in ua:
        return "android"
    if "Windows" in ua:
        return "windows"
    if "CrOS" in ua:
        return "chromeos"
    if "Tizen" in ua:
        return "tizen"
    if re.search(r"Web0S|WebOS", ua, re.I):
        return "webos"
    if "Macintosh" in ua or "Mac OS X" in ua:
        return "macos"
    if "Linux" in ua:
        return "linux"
    return "other"


def country(tz="", cf=""):
    cf = str(cf or "").strip().upper()
    if re.fullmatch(r"[A-Z]{2}", cf) and cf not in ("XX", "T1"):
        return cf
    tz = str(tz or "").strip()[:64]
    if tz in _TZ:
        return _TZ[tz]
    if _US_TZ.search(tz):
        return "US"
    return "??"


def crawler(ua):
    """اسم الزاحف من ترويسة المتصفح، أو "" لزائرٍ عادي."""
    ua = str(ua or "")
    for name, _kind, rx in _CRAWLERS:
        if rx.search(ua):
            return name
    return ""


def _clean(v, n=40, lower=True):
    v = _CTRL.sub("", str(v or "")).strip()[:n]
    return v.lower() if lower else v


def _host(url):
    """نطاق المُحيل ← (المخطّط، النطاق، المسار)؛ `android-app://com.whatsapp/` نطاقه اسم الحزمة."""
    try:
        u = urlsplit(str(url or "").strip())
    except ValueError:
        return "", "", ""
    return (u.scheme or "").lower(), (u.hostname or "").lower().rstrip("."), u.path or ""


def source(ref, qs="", ua="", own=()):
    """مصدر الزيارة ← (المصدر، نطاق المُحيل الخارجي أو ""، الحملة "مصدر / وسيط / حملة" أو "").
    المصدر "internal" تنقّلٌ داخل الموقع (فليس دخولًا جديدًا)، و"direct" بلا مُحيل ولا ما يدلّ عليه."""
    q = parse_qs(str(qs or "").lstrip("?"), keep_blank_values=False)
    first = lambda k: _clean((q.get(k) or [""])[0])
    us, um, uc, ref_p = first("utm_source"), first("utm_medium"), first("utm_campaign"), first("ref")
    camp = " / ".join(p for p in (us, um, uc) if p)
    scheme, host, path = _host(ref)
    ext = ""
    if host and host not in own:
        ext = host
    if us or ref_p:
        tag = us or ref_p
        return _ALIAS.get(tag, re.sub(r"[^a-z0-9._\-]", "", tag)[:30] or "other"), ext, camp or ("ref / " + ref_p)
    if host and host in own:
        if path.rstrip("/").endswith("/widget"):   # ودجت المتجر: iframe من موقعنا في رئيسية سلة
            return "widget", "", ""
        return "internal", "", ""
    if host:
        for key, rx in _SOURCES:
            if rx.search(host):
                return key, ext, ""
        return "other", ext, ""
    for key, rx in _INAPP:
        if rx.search(ua or ""):
            return key, "", ""
    return "direct", "", ""


def clean_path(p):
    p = str(p or "/").split("?", 1)[0].split("#", 1)[0][:160] or "/"
    p = re.sub(r"/{2,}", "/", p)
    if len(p) > 1:
        p = p.rstrip("/") or "/"
    return p if _PATH_OK.match(p) else ""


# ================= التخزين: يومٌ في ملف =================
def _path(data_dir, *parts):
    """مسارٌ في مجلد الإحصائيات — بلا إنشاء: القراءة لا تكتب شيئًا على القرص، والكتابة وحدها تُنشئ مجلدها."""
    return os.path.join(data_dir, SUBDIR, *parts)


def _day(now=None):
    return datetime.datetime.fromtimestamp(now if now is not None else time.time(), RIYADH).strftime("%Y-%m-%d")


def _hour(now=None):
    return datetime.datetime.fromtimestamp(now if now is not None else time.time(), RIYADH).hour


def blank():
    return {"v": 1, "pv": 0, "uv": 0, "in": 0, "pages": {}, "land": {}, "src": {}, "ref": {}, "utm": {},
            "dev": {}, "os": {}, "cc": {}, "hr": [0] * 24, "ev": {}, "evl": {}, "dur": [0, 0], "pdur": {},
            "bot": {}, "shp": {}}


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


def _inc(m, key, n=1, cap=CAP):
    if key in m or len(m) < cap:
        m[key] = m.get(key, 0) + n
    else:
        m[OTHER] = m.get(OTHER, 0) + n


_lock = threading.RLock()
# اليوم الجاري في الذاكرة: أعداده وملحه وبصمات زوّاره — تُكتب كل FLUSH_EVERY ثانية، والملح والبصمات تُمحى من
# ملف اليوم حين ينتهي
_S = {"dir": None, "day": None, "agg": None, "salt": "", "seen": set(), "dirty": False, "flushed": 0.0}
_live = {}                  # بصمة ← (آخر وقت، الصفحة، المصدر)
_rate = {}                  # بصمة ← [الدقيقة، العدد]
_files = {}                 # ملفات الأيام الماضية: المسار ← (mtime، البيانات)


def _day_path(data_dir, day):
    return _path(data_dir, "days", day + ".json")


def _save_today(private=True):
    """يكتب اليوم الجاري؛ والملح والبصمات معه ما دام اليوم يومه (لتبقى البصمات بعد إعادة التشغيل)."""
    if _S["agg"] is None:
        return
    out = dict(_S["agg"])
    if private:
        out["_salt"], out["_seen"] = _S["salt"], sorted(_S["seen"])
    _write(_day_path(_S["dir"], _S["day"]), out)
    _S["dirty"], _S["flushed"] = False, time.time()


def _ensure(data_dir, now=None):
    """يضمن أن اليوم في الذاكرة هو يوم `now` بتوقيت السعودية — وإن انقضى يُكتب بلا ملحٍ ولا بصمات."""
    day = _day(now)
    if _S["dir"] == data_dir and _S["day"] == day:
        return
    if _S["agg"] is not None:
        try:
            _save_today(private=(_S["day"] == day))
        except OSError:
            pass
    d = _read(_day_path(data_dir, day)) or blank()
    salt, seen = d.pop("_salt", "") or secrets.token_hex(16), set(d.pop("_seen", []) or [])
    base = blank()
    for k, v in base.items():                 # ملفٌّ من نسخةٍ أقدم: ما نقص منه يُكمَّل
        if not isinstance(d.get(k), type(v)):
            d[k] = v
    _S.update(dir=data_dir, day=day, agg=d, salt=salt, seen=seen, dirty=False, flushed=time.time())
    _live.clear()
    _rate.clear()


def flush(data_dir, force=False):
    with _lock:
        if _S["dir"] != data_dir or not _S["dirty"]:
            return
        if force or time.time() - _S["flushed"] >= FLUSH_EVERY:
            try:
                _save_today()
            except OSError:
                pass


def _visitor(ip, ua):
    return hashlib.sha256((_S["salt"] + "|" + str(ip) + "|" + str(ua)).encode()).hexdigest()[:16]


def _limited(vh, now):
    minute = int(now // 60)
    r = _rate.get(vh)
    if not r or r[0] != minute:
        if len(_rate) > 20000:
            _rate.clear()
        _rate[vh] = [minute, 1]
        return False
    r[1] += 1
    return r[1] > RATE


def _same_site(headers, own):
    """الإرسال من صفحات موقعنا وحدها: Origin أو Referer بنطاقٍ من نطاقاتنا (وOrigin قد يكون "null")."""
    return any(_host(headers.get(h))[1] in own for h in ("Origin", "Referer") if headers.get(h))


def hit(data_dir, raw, headers, ip, own, now=None):
    """زيارة أو حدثٌ من سكربت الصفحة ← صحيح إن حُسب. `own` نطاقات الموقع (للتفريق بين الداخلي والخارجي)."""
    if not raw or len(raw) > MAX_BODY:
        return False
    ua = str(headers.get("User-Agent") or "")[:400]
    if not ua or _BOT_UA.search(ua) or not _same_site(headers, own):
        return False
    try:
        o = json.loads(raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw)
    except ValueError:
        return False
    if not isinstance(o, dict):
        return False
    t = o.get("t")
    path = clean_path(o.get("p"))
    if t not in ("pv", "ev", "end") or not path:
        return False
    now = time.time() if now is None else now
    try:
        touch = max(0, min(int(o.get("tp") or 0), 20))
    except (TypeError, ValueError):
        touch = 0
    with _lock:
        _ensure(data_dir, now)
        a = _S["agg"]
        vh = _visitor(ip, ua)
        if _limited(vh, now):
            return False
        if t == "pv":
            src, ext, camp = source(o.get("r"), o.get("q"), ua, own)
            new = vh not in _S["seen"] and len(_S["seen"]) < MAX_SEEN
            if new:
                _S["seen"].add(vh)
                a["uv"] += 1
                _inc(a["dev"], device(ua, touch))
                _inc(a["os"], os_name(ua, touch))
                _inc(a["cc"], country(o.get("tz"), headers.get("CF-IPCountry")))
            a["pv"] += 1
            _inc(a["pages"], path)
            a["hr"][_hour(now)] += 1
            if src != "internal":               # دخولٌ من خارج الموقع = زيارة (جلسة)
                a["in"] += 1
                _inc(a["land"], path)
                _inc(a["src"], src)
                if ext:
                    _inc(a["ref"], ext)
                if camp:
                    _inc(a["utm"], camp)
            prev = _live.get(vh)
            _live[vh] = (now, path, src if src != "internal" else (prev[2] if prev else "direct"))
            if len(_live) > 5000:                # «الآن» خمس دقائق فقط: ما قبلها يُحذف
                for k in [k for k, v in _live.items() if now - v[0] > LIVE]:
                    del _live[k]
        elif t == "ev":
            name = str(o.get("n") or "")
            if not _EVENT.match(name) or (name not in a["ev"] and len(a["ev"]) >= CAP_EVENTS):
                return False
            a["ev"][name] = a["ev"].get(name, 0) + 1
            label = _clean(o.get("l"), 80, lower=False)
            if label:
                _inc(a["evl"].setdefault(name, {}), label, cap=CAP_LABELS)
            if vh in _live:
                _live[vh] = (now,) + _live[vh][1:]
        else:                                    # end: مدة قراءة الصفحة (ترسل على دفعات، والأولى تُعدّ مشاهدة)
            try:
                d = max(0, min(int(o.get("d") or 0), MAX_DUR))
            except (TypeError, ValueError):
                return False
            if not d:
                return False
            first = 1 if o.get("f") else 0
            a["dur"][0] += d
            a["dur"][1] += first
            pd = a["pdur"].get(path)
            if pd is not None or len(a["pdur"]) < CAP:
                pd = pd or [0, 0]
                pd[0] += d
                pd[1] += first
                a["pdur"][path] = pd
        _S["dirty"] = True
        if now - _S["flushed"] >= FLUSH_EVERY:
            try:
                _save_today()
            except OSError:
                pass
    return True


def crawl(data_dir, ua, path, now=None):
    """زاحفٌ طلب صفحةً عامة ← اسمه أو "". ومعاينات الروابط تُعدّ لصفحتها: هي مشاركاتها."""
    name = crawler(ua)
    if not name:
        return ""
    with _lock:
        _ensure(data_dir, now)
        a = _S["agg"]
        _inc(a["bot"], name, cap=60)
        if BOT_KINDS.get(name) == "share":
            p = clean_path(path)
            if p:
                _inc(a["shp"], p, cap=200)
        _S["dirty"] = True
    return name


def count(data_dir, name, label="", now=None):
    """حدثٌ من الخادم نفسه (بلا زائر): توليد M3U مثلًا."""
    if not _EVENT.match(name):
        return
    with _lock:
        _ensure(data_dir, now)
        a = _S["agg"]
        a["ev"][name] = a["ev"].get(name, 0) + 1
        if label:
            _inc(a["evl"].setdefault(name, {}), _clean(label, 80, lower=False), cap=CAP_LABELS)
        _S["dirty"] = True


# ================= التقرير =================
def _past(data_dir, day):
    path = _day_path(data_dir, day)
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return None
    c = _files.get(path)
    if c and c[0] == mt:
        return c[1]
    d = _read(path)
    if d is not None:
        d.pop("_salt", None)
        d.pop("_seen", None)
        if len(_files) > 1000:
            _files.clear()
        _files[path] = (mt, d)
    return d


def _merge(days):
    out = blank()
    for d in days:
        if not d:
            continue
        try:
            _merge_one(out, d)
        except (TypeError, ValueError, AttributeError):   # ملفٌّ تالف لا يُسقط التقرير
            pass
    return out


def _merge_one(out, d):
    for k in ("pv", "uv", "in"):
        out[k] += int(d.get(k) or 0)
    for k in ("pages", "land", "src", "ref", "utm", "dev", "os", "cc", "ev", "bot", "shp"):
        for key, n in (d.get(k) or {}).items():
            out[k][key] = out[k].get(key, 0) + int(n or 0)
    for name, labels in (d.get("evl") or {}).items():
        m = out["evl"].setdefault(name, {})
        for key, n in labels.items():
            m[key] = m.get(key, 0) + int(n or 0)
    for i, n in enumerate((d.get("hr") or [])[:24]):
        out["hr"][i] += int(n or 0)
    dur = d.get("dur") or [0, 0]
    out["dur"][0] += int(dur[0] or 0)
    out["dur"][1] += int(dur[1] or 0)
    for p, (s, n) in (d.get("pdur") or {}).items():
        pd = out["pdur"].setdefault(p, [0, 0])
        pd[0] += int(s or 0)
        pd[1] += int(n or 0)


def _top(m, n=30):
    rows = sorted(((k, v) for k, v in m.items() if k != OTHER), key=lambda x: (-x[1], x[0]))
    top = [[k, v] for k, v in rows[:n]]
    rest = sum(v for _, v in rows[n:]) + int(m.get(OTHER, 0))
    if rest:
        top.append([OTHER, rest])
    return top


def _avg(dur):
    return round(dur[0] / dur[1]) if dur and dur[1] else 0


def _totals(m):
    return {"pv": m["pv"], "uv": m["uv"], "in": m["in"], "dur": _avg(m["dur"]),
            "store": int(m["ev"].get("store_click", 0))}


def live(data_dir, now=None):
    now = time.time() if now is None else now
    with _lock:
        _ensure(data_dir, now)
        for k in [k for k, v in _live.items() if now - v[0] > LIVE]:
            del _live[k]
        rows = list(_live.values())
    pages, srcs = {}, {}
    for _, p, s in rows:
        pages[p] = pages.get(p, 0) + 1
        srcs[s] = srcs.get(s, 0) + 1
    return {"n": len(rows), "pages": _top(pages, 8), "src": _top(srcs, 8)}


def report(data_dir, days=30, now=None):
    """أعداد آخر `days` يومًا (واليوم منها) ← ما تعرضه صفحة الإحصائيات، والمدة التي قبلها للمقارنة."""
    now = time.time() if now is None else now
    days = max(1, min(int(days or 30), 400))
    with _lock:
        _ensure(data_dir, now)
        today = _S["day"]
        snap = json.loads(json.dumps(_S["agg"]))        # نسخة اليوم تُقرأ خارج القفل
    base = datetime.date.fromisoformat(today)
    rng = [(base - datetime.timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    prev = [(base - datetime.timedelta(days=days + i)).isoformat() for i in range(days - 1, -1, -1)]
    cur = {d: (snap if d == today else _past(data_dir, d)) for d in rng}
    m, pm = _merge(cur.values()), _merge(_past(data_dir, d) for d in prev)
    pages = []
    for p, n in _top(m["pages"], 40):
        pd = m["pdur"].get(p) or [0, 0]
        pages.append([p, n, _avg(pd)])
    events = []
    for name, c in sorted(m["ev"].items(), key=lambda x: -x[1]):
        events.append({"n": name, "c": c, "top": _top(m["evl"].get(name, {}), 15)})
    first = ""
    try:
        files = sorted(f[:-5] for f in os.listdir(_path(data_dir, "days")) if f.endswith(".json"))
        first = files[0] if files else ""
    except OSError:
        pass
    return {
        "ok": True, "days": days, "from": rng[0], "to": rng[-1], "today": today, "first": first or today,
        "totals": _totals(m), "prev": _totals(pm),
        "daily": [{"d": d, "pv": (a or {}).get("pv", 0), "uv": (a or {}).get("uv", 0), "in": (a or {}).get("in", 0)}
                  for d, a in cur.items()],
        "hours": m["hr"], "pages": pages, "landing": _top(m["land"], 30), "sources": _top(m["src"], 30),
        "refs": _top(m["ref"], 30), "utm": _top(m["utm"], 30), "devices": _top(m["dev"], 10),
        "os": _top(m["os"], 12), "countries": _top(m["cc"], 25), "events": events,
        "bots": [[n, c, BOT_KINDS.get(n, "search")] for n, c in _top(m["bot"], 40)],
        "shared": _top(m["shp"], 20), "live": live(data_dir, now),
    }


def summary(data_dir, now=None):
    """رئيسية لوحة الإدارة: زوّار اليوم ومشاهداته، ومن في الموقع الآن."""
    now = time.time() if now is None else now
    with _lock:
        _ensure(data_dir, now)
        a = _S["agg"]
        t = {"uv": a["uv"], "pv": a["pv"], "in": a["in"], "store": int(a["ev"].get("store_click", 0))}
    return {"ok": True, "today": t, "live": live(data_dir, now)["n"]}


def prune(data_dir, now=None):
    """ملفات الأيام الأقدم من KEEP_DAYS تُحذف، وملح يومٍ مضى وبصماته تُمحى إن بقيت (خادمٌ توقّف منتصف الليل)."""
    today = _day(now)
    cut = (datetime.date.fromisoformat(today) - datetime.timedelta(days=KEEP_DAYS)).isoformat()
    d = _path(data_dir, "days")
    if not os.path.isdir(d):
        return
    for f in sorted(os.listdir(d)):
        if not f.endswith(".json") or f[:-5] >= today:
            continue
        path = os.path.join(d, f)
        if f[:-5] < cut:
            try:
                os.remove(path)
            except OSError:
                pass
            continue
        x = _read(path)
        if x is not None and ("_salt" in x or "_seen" in x):
            x.pop("_salt", None)
            x.pop("_seen", None)
            try:
                _write(path, x)
            except OSError:
                pass


# ================= الربط: المعرّفات ووسوم التحقّق =================
# الحقل ← (نمط القيمة، الاسم في رسالة الخطأ). يقبل لصق الكود كاملًا: تُستخرج القيمة منه.
FIELDS = {
    "ga": (r"G-[A-Z0-9]{4,15}", "معرّف Google Analytics (يبدأ بـ G-)"),
    "gtm": (r"GTM-[A-Z0-9]{4,12}", "معرّف Tag Manager (يبدأ بـ GTM-)"),
    "clarity": (r"[a-z0-9]{8,14}", "معرّف مشروع Microsoft Clarity"),
    "meta": (r"[0-9]{10,20}", "معرّف بيكسل ميتا (أرقام)"),
    "snap": (r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "معرّف بيكسل سناب شات"),
    "tiktok": (r"[A-Z0-9]{16,24}", "معرّف بيكسل تيك توك"),
    "gsv": (r"[A-Za-z0-9_\-]{30,70}", "رمز التحقّق من Google Search Console"),
    "bing": (r"[A-F0-9]{32}", "رمز التحقّق من Bing Webmaster"),
}
_META_CONTENT = re.compile(r"content\s*=\s*[\"']([^\"']+)[\"']", re.I)


def _field(key, raw):
    """القيمة المُلصقة ← المعرّف وحده (أو "" للفراغ)، أو ValueError باسم الحقل."""
    rx, name = FIELDS[key]
    v = str(raw or "").strip()
    if not v:
        return ""
    if key in ("gsv", "bing"):
        m = _META_CONTENT.search(v)
        if m:
            v = m.group(1).strip()
        v = re.sub(r"^google-site-verification\s*[=:]\s*", "", v, flags=re.I)   # صيغة سجل DNS
    if key == "bing":
        v = v.upper()
    if key in ("ga", "gtm", "tiktok"):
        v = v.upper() if re.fullmatch(r"[A-Za-z0-9\-]+", v) else v
    if key == "clarity":
        m = re.search(r"clarity\.ms/tag/([a-z0-9]+)|[\"']clarity[\"']\s*,\s*[\"']script[\"']\s*,\s*[\"']([a-z0-9]+)", v)
        v = (m.group(1) or m.group(2)) if m else v.lower()
    if key == "meta":
        m = re.search(r"fbq\(\s*['\"]init['\"]\s*,\s*['\"](\d+)", v)
        v = m.group(1) if m else v
    if key == "snap":
        m = re.search(r"snaptr\(\s*['\"]init['\"]\s*,\s*['\"]([0-9a-f-]{36})", v, re.I)
        v = (m.group(1) if m else v).lower()
    if key == "tiktok":
        m = re.search(r"ttq\.load\(\s*['\"]([A-Z0-9]+)", v, re.I)
        v = (m.group(1) if m else v).upper()
    if key in ("ga", "gtm"):
        m = re.search(rx, v)
        v = m.group(0) if m else v
    if not re.fullmatch(rx, v):
        raise ValueError("قيمة غير صحيحة: " + name)
    return v


def _settings_path(data_dir):
    return _path(data_dir, SETTINGS)


_snip = {"key": None, "html": b""}


def settings(data_dir):
    s = _read(_settings_path(data_dir)) or {}
    return s if isinstance(s, dict) else {}


def _save_settings(data_dir, s):
    _write(_settings_path(data_dir), s)
    _snip["key"] = None


def public_settings(data_dir):
    """الإعداد كما تعرضه الصفحة: المعرّفات، وحال ربط جوجل بلا مفتاحه، وIndexNow."""
    s = settings(data_dir)
    tags = {k: str((s.get("tags") or {}).get(k) or "") for k in FIELDS}
    g = s.get("google") if isinstance(s.get("google"), dict) else {}
    ix = indexnow(data_dir)
    return {"tags": tags,
            "google": {"email": g.get("email", ""), "project": g.get("project", ""), "has_key": bool(g.get("sa")),
                       "ga": g.get("ga", ""), "site": g.get("site", "")},
            "indexnow": {"key": ix["key"], "auto": ix["auto"], "confirmed": ix["confirmed"], "last": ix["last"],
                         "day": ix["day"]}}


def save_tags(data_dir, body):
    """يحفظ ما أُرسل من المعرّفات (والباقي كما هو) ← المعرّفات كلها. قيمةٌ غير صحيحة ترفض الحفظ كله."""
    with _lock:
        s = settings(data_dir)
        tags = dict(s.get("tags") or {})
        for k in FIELDS:
            if k in body:
                tags[k] = _field(k, body[k])
        s["tags"] = {k: v for k, v in tags.items() if k in FIELDS and v}
        _save_settings(data_dir, s)
        return {k: s["tags"].get(k, "") for k in FIELDS}


def _script_version():
    try:
        with open(os.path.join(BASE_DIR, SCRIPT.lstrip("/")), "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:10]
    except OSError:
        return "0"


_VER = _script_version()


def head(data_dir):
    """ما يُحقن قبل `</head>` في كل صفحة عامة: وسما التحقّق، وسكربت العدّاد، ثم ما رُبط من أدوات.
    وكلها تُحترم «استثناء زياراتي» (‏?sq=off يحفظ sq_off في المتصفح): لا تُحمَّل الأدوات ولا يُرسل شيء."""
    path = _settings_path(data_dir)
    try:
        mt = os.path.getmtime(path)
    except OSError:
        mt = 0
    key = (path, mt)
    if _snip["key"] == key:
        return _snip["html"]
    t = {k: v for k, v in ((settings(data_dir).get("tags") or {}).items()) if k in FIELDS}
    for k in list(t):                       # ملفٌّ عُدّل يدويًا: ما لا يطابق النمط لا يُحقن
        try:
            t[k] = _field(k, t[k])
        except ValueError:
            t.pop(k)
    out = []
    if t.get("gsv"):
        out.append(f'<meta name="google-site-verification" content="{t["gsv"]}">')
    if t.get("bing"):
        out.append(f'<meta name="msvalidate.01" content="{t["bing"]}">')
    out.append('<script>window.sq=window.sq||function(){(window.sq.q=window.sq.q||[]).push(arguments)};'
               'try{window.sqOff=/[?&]sq=off\\b/.test(location.search)||(localStorage.getItem("sq_off")==="1"'
               '&&!/[?&]sq=on\\b/.test(location.search))}catch(e){}'
               + ('window.SQ_GTM=1;' if t.get("gtm") else "") + '</script>')
    out.append(f'<script src="{SCRIPT}?v={_VER}" defer></script>')
    if t.get("ga"):
        g = t["ga"]
        out.append('<script>if(!window.sqOff){(function(){var s=document.createElement("script");s.async=1;'
                   f's.src="https://www.googletagmanager.com/gtag/js?id={g}";document.head.appendChild(s)}})()}}'
                   'window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments)}'
                   'gtag("js",new Date());(function(){var c={};try{var u=new URL(location.href),p=u.searchParams;'
                   'if(p.get("ref")&&!p.get("utm_source")){p.set("utm_source",p.get("ref"));p.set("utm_medium","ref");'
                   f'c.page_location=u.href}}}}catch(e){{}}gtag("config","{g}",c)}})()</script>')
    if t.get("gtm"):
        out.append('<script>if(!window.sqOff){(function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({"gtm.start":'
                   'new Date().getTime(),event:"gtm.js"});var f=d.getElementsByTagName(s)[0],j=d.createElement(s);'
                   'j.async=true;j.src="https://www.googletagmanager.com/gtm.js?id="+i;f.parentNode.insertBefore(j,f)'
                   f'}})(window,document,"script","dataLayer","{t["gtm"]}")}}</script>')
    if t.get("clarity"):
        out.append('<script>if(!window.sqOff){(function(c,l,a,r,i,t,y){c[a]=c[a]||function(){(c[a].q=c[a].q||[])'
                   '.push(arguments)};t=l.createElement(r);t.async=1;t.src="https://www.clarity.ms/tag/"+i;'
                   'y=l.getElementsByTagName(r)[0];y.parentNode.insertBefore(t,y)})(window,document,"clarity",'
                   f'"script","{t["clarity"]}")}}</script>')
    if t.get("meta"):
        out.append('<script>if(!window.sqOff){!function(f,b,e,v,n,t,s){if(f.fbq)return;n=f.fbq=function(){'
                   'n.callMethod?n.callMethod.apply(n,arguments):n.queue.push(arguments)};if(!f._fbq)f._fbq=n;'
                   'n.push=n;n.loaded=!0;n.version="2.0";n.queue=[];t=b.createElement(e);t.async=!0;t.src=v;'
                   's=b.getElementsByTagName(e)[0];s.parentNode.insertBefore(t,s)}(window,document,"script",'
                   f'"https://connect.facebook.net/en_US/fbevents.js");fbq("init","{t["meta"]}");'
                   'fbq("track","PageView")}</script>')
    if t.get("snap"):
        out.append('<script>if(!window.sqOff){(function(e,t,n){if(e.snaptr)return;var a=e.snaptr=function(){'
                   'a.handleRequest?a.handleRequest.apply(a,arguments):a.queue.push(arguments)};a.queue=[];'
                   'var r=t.createElement("script");r.async=!0;r.src=n;var u=t.getElementsByTagName("script")[0];'
                   'u.parentNode.insertBefore(r,u)})(window,document,"https://sc-static.net/scevent.min.js");'
                   f'snaptr("init","{t["snap"]}",{{}});snaptr("track","PAGE_VIEW")}}</script>')
    if t.get("tiktok"):
        out.append('<script>if(!window.sqOff){!function(w,d,t){w.TiktokAnalyticsObject=t;var ttq=w[t]=w[t]||[];'
                   'ttq.methods=["page","track","identify","instances","debug","on","off","once","ready","alias",'
                   '"group","enableCookie","disableCookie"];ttq.setAndDefer=function(t,e){t[e]=function(){'
                   't.push([e].concat(Array.prototype.slice.call(arguments,0)))}};for(var i=0;i<ttq.methods.length;'
                   'i++)ttq.setAndDefer(ttq,ttq.methods[i]);ttq.instance=function(t){for(var e=ttq._i[t]||[],n=0;'
                   'n<ttq.methods.length;n++)ttq.setAndDefer(e,ttq.methods[n]);return e};ttq.load=function(e,n){'
                   'var r="https://analytics.tiktok.com/i18n/pixel/events.js";ttq._i=ttq._i||{};ttq._i[e]=[];'
                   'ttq._i[e]._u=r;ttq._t=ttq._t||{};ttq._t[e]=+new Date;ttq._o=ttq._o||{};ttq._o[e]=n||{};'
                   'var o=d.createElement("script");o.type="text/javascript";o.async=!0;o.src=r+"?sdkid="+e+"&lib="+t;'
                   'var a=d.getElementsByTagName("script")[0];a.parentNode.insertBefore(o,a)};'
                   f'ttq.load("{t["tiktok"]}");ttq.page()}}(window,document,"ttq")}}</script>')
    html = ("\n".join(out) + "\n").encode("utf-8")
    _snip.update(key=key, html=html)
    return html


def inject(body, data_dir):
    """صفحةٌ عامة ← هي نفسها وقبل أول `</head>` فيها ما في `head()`. صفحةٌ بلا `</head>` تبقى كما هي."""
    i = body.find(b"</head>")
    if i < 0:
        return body
    return body[:i] + head(data_dir) + body[i:]


# ================= IndexNow: إرسال الصفحات إلى Bing وYandex وغيرهما =================
INDEXNOW_URL = os.environ.get("XM_INDEXNOW_URL", "https://api.indexnow.org/indexnow")
_KEY_RX = re.compile(r"[0-9a-f]{32}")
DAILY_FREQ = ("always", "hourly", "daily")      # ما يتغيّر كل يوم يُرسَل وحده كل يوم


def indexnow(data_dir, create=True):
    """{key, auto, confirmed, last, day}: المفتاح يُولَّد مرةً ويبقى (و`create=False` لا يولّده: "" إن لم يكن)،
    والإرسال اليومي مفعّلٌ افتراضًا ويبدأ بعد أول إرسالٍ ناجح (‏confirmed)."""
    s = settings(data_dir)
    ix = s.get("indexnow") if isinstance(s.get("indexnow"), dict) else {}
    key = str(ix.get("key") or "")
    if not _KEY_RX.fullmatch(key) and not create:
        key = ""
    elif not _KEY_RX.fullmatch(key):
        with _lock:
            s = settings(data_dir)
            ix = s.get("indexnow") if isinstance(s.get("indexnow"), dict) else {}
            key = str(ix.get("key") or "")
            if not _KEY_RX.fullmatch(key):
                key = secrets.token_hex(16)
                ix["key"] = key
                ix.setdefault("auto", True)
                s["indexnow"] = ix
                _save_settings(data_dir, s)
    return {"key": key, "auto": ix.get("auto", True) is not False, "confirmed": bool(ix.get("confirmed")),
            "last": ix.get("last") if isinstance(ix.get("last"), dict) else None, "day": str(ix.get("day") or "")}


def indexnow_key_file(data_dir, path):
    """`/<المفتاح>.txt` ← المفتاح نصًّا (هكذا يتحقّق Bing أن الإرسال منّا)، أو None لغيره."""
    m = re.fullmatch(r"/([0-9a-f]{32})\.txt", path or "")
    if not m:
        return None
    key = indexnow(data_dir, create=False)["key"]
    return key if key and m.group(1) == key else None


def _ix_update(data_dir, **kw):
    with _lock:
        s = settings(data_dir)
        ix = s.get("indexnow") if isinstance(s.get("indexnow"), dict) else {}
        ix.update(kw)
        s["indexnow"] = ix
        _save_settings(data_dir, s)


def set_indexnow_auto(data_dir, on):
    indexnow(data_dir)
    _ix_update(data_dir, auto=bool(on))
    return indexnow(data_dir)


_IX_MSG = {200: "استُلمت الصفحات", 202: "استُلمت — والمفتاح قيد التحقّق",
           400: "طلبٌ غير صالح", 403: "المفتاح غير صالح: تأكّد أن ملفه يفتح على الموقع",
           422: "صفحاتٌ لا تتبع نطاق الموقع أو المفتاح لا يطابق", 429: "إرسالٌ كثير — يُعاد لاحقًا"}


def submit(data_dir, site_host, urls, kind="manual", now=None):
    """يرسل `urls` (عناوين كاملة على site_host) إلى IndexNow ← {ok, code, n, msg, at, kind} ويحفظه آخرَ إرسال."""
    now = time.time() if now is None else now
    key = indexnow(data_dir)["key"]
    urls = [u for u in dict.fromkeys(urls) if _host(u)[1] == site_host][:10000]
    res = {"at": int(now), "kind": kind, "n": len(urls), "code": 0, "ok": False, "msg": ""}
    if not urls:
        res["msg"] = "لا صفحات للإرسال"
        return res
    body = json.dumps({"host": site_host, "key": key, "keyLocation": f"https://{site_host}/{key}.txt",
                       "urlList": urls}).encode()
    try:
        r = urlopen(Request(INDEXNOW_URL, data=body, method="POST",
                            headers={"Content-Type": "application/json; charset=utf-8",
                                     "User-Agent": "ssouq-guide/1.0"}), timeout=20)
        res["code"] = r.getcode()
    except HTTPError as e:
        res["code"] = e.code
    except Exception as e:                      # الشبكة: يُذكر السبب ولا يسقط شيء
        res["msg"] = "تعذّر الاتصال: " + str(e)[:120]
    res["ok"] = res["code"] in (200, 202)
    res["msg"] = res["msg"] or _IX_MSG.get(res["code"], f"ردّ غير متوقّع ({res['code']})")
    _ix_update(data_dir, last=res, **({"confirmed": True} if res["ok"] else {}))
    return res


def daily_due(data_dir, now=None):
    """حان إرسال اليوم؟ مرةً في اليوم بعد السادسة صباحًا بتوقيت السعودية، ما دام التلقائي مفعّلًا — وبعد أول إرسالٍ
    ناجح من الصفحة: فخادمٌ محليٌّ أو للاختبار لا يرسل شيئًا إلى IndexNow وحده، ولا يكتب شيئًا."""
    ix = indexnow(data_dir, create=False)
    return bool(ix["key"] and ix["auto"] and ix["confirmed"] and ix["day"] != _day(now) and _hour(now) >= 6)


def daily_submit(data_dir, site_host, pages, now=None):
    """الصفحات التي تتغيّر يوميًا ← IndexNow، مرةً في اليوم. `pages` [(المسار، changefreq)] من خريطة الموقع
    نفسها. ← نتيجة الإرسال، أو None إن لم يحن أو كان معطّلًا."""
    now = time.time() if now is None else now
    if not daily_due(data_dir, now):
        return None
    _ix_update(data_dir, day=_day(now))
    urls = [f"https://{site_host}{p}" for p, freq in pages if freq in DAILY_FREQ]
    return submit(data_dir, site_host, urls, kind="auto", now=now)


# ================= العامل: الكتابة الدورية، وتنظيف الأيام، وإرسال IndexNow اليومي =================
def start(data_dir, site_host, pages_fn):
    """يشغّل عاملًا خلفيًا: يكتب أعداد اليوم كل FLUSH_EVERY ثانية، وينقل اليوم عند منتصف الليل، ويحذف القديم،
    ويرسل صفحات اليوم إلى IndexNow. `pages_fn()` ← [(المسار، changefreq)] كخريطة الموقع."""
    def loop():
        last_day = None
        while True:
            time.sleep(FLUSH_EVERY)
            try:
                with _lock:
                    _ensure(data_dir)
                flush(data_dir)
                day = _day()
                if day != last_day:
                    last_day = day
                    prune(data_dir)
                if site_host and daily_due(data_dir):
                    daily_submit(data_dir, site_host, pages_fn())
            except Exception:
                pass
    threading.Thread(target=loop, daemon=True).start()


# ================= ربط جوجل: مفتاح حساب الخدمة (مشفَّرًا) والخاصية والموقع =================
def google_creds(data_dir):
    """{sa: JSON حساب الخدمة مفكوكًا، email، ga، site} أو None إن لم يُربط."""
    g = settings(data_dir).get("google")
    if not isinstance(g, dict) or not g.get("sa"):
        return None
    raw = crypto_store.decrypt(g["sa"], data_dir)
    try:
        sa = json.loads(raw)
    except ValueError:
        return None
    return {"sa": sa, "email": g.get("email", ""), "ga": g.get("ga", ""), "site": g.get("site", "")}


def save_google(data_dir, body, parse_key):
    """يحفظ ربط جوجل: ملف مفتاح حساب الخدمة (JSON) إن أُرسل، ورقم خاصية GA4، وموقع Search Console.
    `parse_key(pem)` يتحقّق من المفتاح الخاص. «remove» يمحو الربط كله."""
    with _lock:
        s = settings(data_dir)
        g = s.get("google") if isinstance(s.get("google"), dict) else {}
        if body.get("remove"):
            s.pop("google", None)
            _save_settings(data_dir, s)
            return public_settings(data_dir)["google"]
        raw = str(body.get("key") or "").strip()
        if raw:
            try:
                sa = json.loads(raw)
            except ValueError:
                raise ValueError("الملف ليس JSON — انسخ محتوى ملف المفتاح كاملًا كما نزّلته من Google Cloud")
            if not isinstance(sa, dict) or sa.get("type") != "service_account" or not sa.get("client_email") \
                    or not sa.get("private_key"):
                raise ValueError("هذا ليس مفتاح حساب خدمة (service account) — نزّل مفتاحًا بصيغة JSON من حساب الخدمة")
            try:
                parse_key(sa["private_key"])
            except Exception:
                raise ValueError("المفتاح الخاص في الملف لا يُقرأ")
            keep = {k: sa[k] for k in ("type", "project_id", "private_key_id", "private_key", "client_email",
                                       "token_uri") if k in sa}
            g["sa"] = crypto_store.encrypt(json.dumps(keep), data_dir)
            g["email"] = str(sa["client_email"])[:200]
            g["project"] = str(sa.get("project_id") or "")[:100]
        if "ga" in body:
            ga = re.sub(r"\D", "", str(body.get("ga") or "").replace("properties/", ""))
            if body.get("ga") and not ga:
                raise ValueError("رقم الخاصية أرقامٌ فقط (Property ID) — من إعدادات الخاصية في Google Analytics")
            g["ga"] = ga[:20]
        if "site" in body:
            site = str(body.get("site") or "").strip()
            if site and not re.fullmatch(r"sc-domain:[a-z0-9.\-]+|https?://[^\s]+/", site):
                raise ValueError("موقع Search Console: رابطٌ ينتهي بـ / (مثل https://guide.ssouq.com/) أو sc-domain:ssouq.com")
            g["site"] = site[:200]
        s["google"] = g
        _save_settings(data_dir, s)
        return public_settings(data_dir)["google"]

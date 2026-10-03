#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
إضافة Stremio لاشتراكات Xtream — كل المحتوى لا أوّله: الأفلام كلها، والمسلسلات بمواسمها وحلقاتها، والقنوات.

لماذا إضافةٌ خاصة: الإضافات العامة (Xtremio وأخواتها) تعرض صفحةً أو صفحتين من كل قسم ثم تتوقّف، أو أقسامًا دون
أخرى. Stremio يطلب الكتالوج صفحةً بعد صفحة (‏skip = ما وصله حتى الآن)، ويحكم بانتهائه متى جاءته صفحةٌ أقلّ من
100 عنصر (‏CATALOG_PAGE_SIZE في stremio-core) — فكل صفحةٍ هنا 100 تمامًا إلا الأخيرة، والقائمة كاملةً من
السيرفر بطلبٍ واحد لكل نوع (‏get_vod_streams · get_series · get_live_streams)، لا قسمًا قسمًا.

  الكتالوجات     بترتيب تطبيقات IPTV: الحسابات · المسلسلات · الأفلام · البث المباشر. «الحسابات» حال الاشتراك
                 (الحالة والانتهاء والمتبقّي والاتصالات) لكل خطوط حساب Stremio، ورابط التجديد. والمحتوى بلا تصنيف
                 = الكل (الأحدث إضافةً أولًا، والقنوات بترتيب السيرفر)، وأقسام السيرفر تصنيفاتٌ (genre) في صفحة
                 «اكتشف» للثلاثة؛ والبحث بالاسم في الثلاثة (صفوفه بالترتيب نفسه). وملصق القناة مرسوم: اسمها ورقمها
                 وختم جودتها (‏stremio_posters).
  التفاصيل      الفيلم من get_vod_info، والمسلسل بمواسمه وحلقاته من get_series_info، والقناة من القائمة.
  التشغيل       روابط السيرفر نفسه: ‏/movie/ · ‏/series/ · ‏/live/ (‏HLS ثم TS حسب ما يسمح به الاشتراك).

الرابط: ‏/stremio/<رمز>/manifest.json — الرمز مختومٌ بمفتاح الخادم (‏crypto_store.seal_token): فيه الهوست واليوزر
والباسورد مشفَّرةً، فلا تُقرأ من الرابط ولا يُصنع رابطٌ لسيرفرٍ آخر، والاشتراك نفسه يعطي الرمز نفسه دائمًا.
والكبار: تُسقط أقسامهم كلها (بعلامة السيرفر أو باسم القسم) وما علّمه السيرفر للكبار — لا بالعنوان، فلا يسقط
فيلم «xXx» ولا مسلسل «The Penthouse».

بلا مكتبات خارجية. ‏handle() يردّ على المسارات، وxm_lines يمرّر الطلب إليه ويضيف قائمة الهوستات المسموحة.
"""
import datetime
import gzip
import hashlib
import http.client
import inspect
import itertools
import json
import os
import re
import threading
import time
from collections import OrderedDict, namedtuple
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, parse_qsl, quote, unquote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

import content as C
import crypto_store
import stremio_categories as CATS
import stremio_library as LIB
import stremio_posters as POSTERS

PATH = "/stremio"
LABEL = "stremio"                    # وسم الرمز: رمزٌ صدر لغير الإضافة لا يُقبل فيها
BRAND = "سمارت سوق"
VERSION = "1.6.1"                    # يرتفع مع كل تغييرٍ في الـmanifest فيحدّثه Stremio
PAGE = 100                           # صفحة الكتالوج كما يعدّها Stremio — أقلّ منها = آخر القائمة
TTL = int(os.environ.get("STREMIO_TTL", "1800"))          # عمر قوائم السيرفر في الذاكرة (ثوانٍ)
RETRY = 60                           # فشل التحديث وفي الذاكرة نسخةٌ: تُعرض، ويُعاد بعد دقيقة
ACCOUNT_TTL = 300                    # حالة الاشتراك (‏user_info)
INFO_TTL = 6 * 3600                  # تفاصيل فيلمٍ أو مسلسل
INFO_MAX = 3000
# تصنيفات الأفلام من تفاصيلها (انظر note_genre · crawl_genres): طلبات get_vod_info في الثانية لكل سيرفر في الخلفية (‏0 = لا)
GENRE_RPS = float(os.environ.get("STREMIO_GENRE_RPS", "2") or 0)
GENRE_BATCH = 300                    # أفلامٌ في الدفعة الواحدة لكل سيرفر (ثم السيرفر التالي)
LISTS_MAX = int(os.environ.get("STREMIO_CACHE", "18"))    # قوائم (سيرفر × باقة × نوع) في الذاكرة معًا
API_TIMEOUT = 60
MAX_BYTES = 256 << 20
UA = C.UA                            # لوحات Xtream تقبل المشغّلات وقد تردّ غيرها
RATE = 20                            # روابط تُصنع بالساعة لكل عنوان من الصفحة العامة

TYPES = ("movie", "series", "tv")
_ACTION = {"movie": ("get_vod_categories", "get_vod_streams", "stream_id"),
           "series": ("get_series_categories", "get_series", "series_id"),
           "tv": ("get_live_categories", "get_live_streams", "stream_id")}
CATALOG = {"movie": "sq_movies", "series": "sq_series", "tv": "sq_live"}
# ترتيب الكتالوجات كتطبيقات IPTV: «الحسابات» أولًا (إن كانت لهذه الإضافة) ثم المسلسلات ثم الأفلام ثم البث المباشر
ORDER = ("series", "movie", "tv")
# «الحسابات» نوعٌ خاصّ (Stremio يقبل أي نوع): يظهر باسمه في «اكتشف»، ولا يختلط بالمحتوى ولا يدخل البحث
ACCOUNTS = "الحسابات"
ACCOUNTS_ID = "sq_accounts"
ACCOUNTS_AGE = 300                   # عمر صفّ «الحسابات» عند Stremio (ثوانٍ): المتبقّي يتغيّر كل يوم
# أقسام السيرفر تصنيفاتٌ في الثلاثة (والقنوات بلا تصنيف = كلها بترتيب السيرفر)؛ وتصنيف العمل نفسه («جريمة» في صفحته)
# للأفلام والمسلسلات وحدها
GENRE_TYPES = ("movie", "series")
POSTER_LABEL = "poster"              # وسم رمز ملصق القناة (‏/stremio/p/<رمز>.png)
CAT_PREFIX = "sqc_"                  # كتالوج تصنيفٍ من تصنيفات سمارت سوق (صفٌّ في الرئيسية — stremio_categories)
# صفّ «التصنيفات» (بطاقة لكل تصنيف ← «عرض الكل») أُزيل — لم يعمل «عرض الكل» في التطبيقات. ونسخٌ مثبّتةٌ قبل تحديثها ما زالت
# تطلبه: يُردّ فارغًا فيختفي صفّه
TILES = "التصنيفات"
TILES_ID = "sq_cats"
CAT_TTL = 120                        # أعمال كل تصنيفٍ تُحسب مرةً كل دقيقتين لكل مكتبة (تصنيفات الأفلام تزيد بالجمع)
_UNIT = {"movie": "فيلم", "series": "مسلسل", "tv": "قناة"}
_CODE = {"movie": "m", "series": "s", "tv": "l"}   # بادئة المعرّف بعد بادئة السيرفر؛ و‏e للحلقة

# ‏origin: هوست الرمز حين يُحوَّل الاشتراك إلى هوستٍ جديد (السيرفر نفسه غيّر عنوانه) — منه بادئة المعرّفات ومعرّف
# الإضافة فتبقى المكتبة و«تابع المشاهدة»؛ والطلبات وروابط التشغيل إلى host.
Cfg = namedtuple("Cfg", "host user pw origin", defaults=(None,))
Item = namedtuple("Item", "id name poster cat added rating ext plot year genre tmdb imdb bg", defaults=(0, "", ""))
# ‏bg: صورة الخلفية العريضة من القائمة (‏backdrop_path) إن أعطتها اللوحة — للواجهة الكبيرة أعلى رئيسية Nuvio


class XtreamError(Exception):
    """تعذّر الوصول إلى السيرفر أو ردّ بما لا يُفهم — رسالته للعرض."""


class AuthError(XtreamError):
    """السيرفر رفض الاشتراك (منتهٍ أو موقوف أو بياناتٌ خاطئة)."""


# ================= الهوست والرمز =================
_HOSTNAME = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*")


def norm_host(h):
    """«mrha.ink:80» · «http://mrha.ink:80/» · «HTTP://Mrha.ink» ← ‏http://mrha.ink:80 (أو None).
    المنفذ يبقى كما كُتب (فيه يُبنى رابط التشغيل)، والمسار والاستعلام يُحذفان."""
    h = str(h or "").strip()
    if not h:
        return None
    if "://" not in h:
        h = "http://" + h
    try:
        p = urlsplit(h)
        port = p.port
    except ValueError:
        return None
    host = (p.hostname or "").lower()
    if p.scheme.lower() not in ("http", "https") or p.username or p.password or not _HOSTNAME.fullmatch(host):
        return None
    return f"{p.scheme.lower()}://{host}" + (f":{port}" if port else "")


def host_key(h):
    """اسم السيرفر وحده (بلا بروتوكول ولا منفذ) — به تُقارن قائمة الهوستات المسموحة."""
    n = norm_host(h)
    return urlsplit(n).hostname if n else ""


def make_token(data_dir, host, user, pw, key=None):
    """(الهوست، اليوزر، الباسورد) ← رمز الرابط. ‏key: قفل إضافة حسابٍ جاهز — رمزه لا يعمل إلا ما دام قفله هو
    المحفوظ لحسابه (تغييره يوقف كل نسخةٍ نُقلت لحسابٍ آخر). ‏ValueError لبياناتٍ لا تصلح."""
    host, user, pw = norm_host(host), str(user or "").strip(), str(pw or "").strip()
    if not host or not user or not pw or any(len(x) > 128 or re.search(r"\s", x) for x in (user, pw)):
        raise ValueError("بيانات الاشتراك غير صالحة")
    if key is not None and not re.fullmatch(r"[A-Za-z0-9_-]{4,32}", str(key)):
        raise ValueError("قفلٌ غير صالح")
    h = host[len("http://"):] if host.startswith("http://") else host    # ‏http الافتراضي يُختصر من الرمز
    return crypto_store.seal_token("\n".join((h, user, pw) + ((str(key),) if key is not None else ())), data_dir, LABEL)


def read_token_key(data_dir, token):
    """الرمز ← (‏Cfg، قفله أو None)، أو (None، None) لرمزٍ معبوثٍ به أو من مفتاحٍ آخر."""
    token = str(token or "")
    if not 20 <= len(token) <= 400 or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
        return None, None
    parts = (crypto_store.open_token(token, data_dir, LABEL) or "").split("\n")
    if len(parts) not in (3, 4) or (len(parts) == 4 and not parts[3]):
        return None, None
    host = norm_host(parts[0])
    if not (host and parts[1] and parts[2]):
        return None, None
    return Cfg(host, parts[1], parts[2]), (parts[3] if len(parts) == 4 else None)


def read_token(data_dir, token):
    """الرمز ← ‏Cfg، أو None لرمزٍ معبوثٍ به أو من مفتاحٍ آخر."""
    return read_token_key(data_dir, token)[0]


_LINE = re.compile(r"(?is)\bhost\b\s*[:=]?\s*(\S+).*?\buser(?:name)?\b\s*[:=]?\s*(\S+).*?\bpass(?:word)?\b\s*[:=]?\s*(\S+)")
_M3U = re.compile(r"(?i)\bhttps?://\S+?/(?:get|player_api)\.php\?\S+")


def parse_line(text):
    """سطر الاشتراك كما نرسله («Host … User … Pass …» أو نص الشرح بـ«Host: …») أو رابط M3U بصيغة Xtream
    ← (الهوست، اليوزر، الباسورد) أو None."""
    t = str(text or "")
    m = _M3U.search(t)
    if m:
        p = urlsplit(m.group(0))
        q = parse_qs(p.query)
        if q.get("username") and q.get("password"):
            return f"{p.scheme}://{p.netloc}", q["username"][0], q["password"][0]
    m = _LINE.search(t)
    return (m.group(1), m.group(2), m.group(3)) if m else None


def prefix(cfg):
    """بادئة معرّفات السيرفر في Stremio — بالهوست وحده: اشتراكٌ جديد على السيرفر نفسه يُبقي المكتبة
    و«تابع المشاهدة» كما هما، وسيرفران مختلفان لا يتداخلان."""
    return "sq" + hashlib.sha256(host_key(cfg.origin or cfg.host).encode()).hexdigest()[:6] + ":"


def routed(cfg, host):
    """الاشتراك نفسه على هوستٍ جديد (تحويل الهوست): الطلبات إليه، والمعرّفات كما كانت."""
    host = norm_host(host)
    return Cfg(host, cfg.user, cfg.pw, cfg.origin or cfg.host) if host and host != cfg.host else cfg


# ================= واجهة Xtream =================
def _api(cfg, action=None, **params):
    q = {"username": cfg.user, "password": cfg.pw}
    if action:
        q["action"] = action
    q.update({k: str(v) for k, v in params.items()})
    url = f"{cfg.host}/player_api.php?" + urlencode(q)
    try:
        with urlopen(Request(url, headers={"User-Agent": UA, "Accept": "application/json"}), timeout=API_TIMEOUT) as r:
            raw = r.read(MAX_BYTES + 1)
    except HTTPError as e:
        if e.code in (401, 403):
            raise AuthError("السيرفر رفض الاشتراك") from None
        raise XtreamError(f"ردّ السيرفر بخطأ {e.code}") from None
    except (URLError, OSError, ValueError, http.client.HTTPException):
        raise XtreamError("تعذّر الوصول إلى السيرفر") from None
    if len(raw) > MAX_BYTES:
        raise XtreamError("ردّ السيرفر أكبر من المسموح")
    try:
        return json.loads(raw.decode("utf-8", "replace") or "null")
    except ValueError:
        raise XtreamError("ردّ السيرفر ليس بالصيغة المتوقّعة") from None


_lock = threading.Lock()
_accounts = OrderedDict()            # cfg ← (الوقت، user_info، server_info)


def account(cfg, fresh=False):
    """(user_info، server_info) — أو AuthError إن رفض السيرفر الاشتراك."""
    now = time.time()
    with _lock:
        hit = _accounts.get(cfg)
    if hit and not fresh and now - hit[0] < ACCOUNT_TTL:
        return hit[1], hit[2]
    d = _api(cfg)
    ui = d.get("user_info") if isinstance(d, dict) else None
    if not isinstance(ui, dict) or str(ui.get("auth")) != "1":
        raise AuthError("بيانات الاشتراك مرفوضة أو الاشتراك منتهٍ")
    si = d.get("server_info") if isinstance(d.get("server_info"), dict) else {}
    with _lock:
        _accounts[cfg] = (now, ui, si)
        _accounts.move_to_end(cfg)
        while len(_accounts) > 2000:
            _accounts.popitem(last=False)
    return ui, si


def _list_of(d):
    """قائمةٌ من ردّ السيرفر: بعض اللوحات تردّ {} أو null للفارغ، وردٌّ برفض الدخول = AuthError."""
    if isinstance(d, list):
        return d
    if isinstance(d, dict) and isinstance(d.get("user_info"), dict) and str(d["user_info"].get("auth")) != "1":
        raise AuthError("بيانات الاشتراك مرفوضة أو الاشتراك منتهٍ")
    if not d:
        return []
    if isinstance(d, dict) and all(isinstance(v, dict) for v in d.values()):
        return list(d.values())          # لوحاتٌ تردّ القائمة كائنًا مفهرسًا {"0": {…}, "1": {…}}
    raise XtreamError("ردّ السيرفر ليس قائمة")


# ================= القوائم: كل عناصر النوع، مرتّبةً ومفهرسة =================
def _int(v, default=0):
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return default


def _rating(v):
    try:
        r = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return f"{r:.1f}" if 0 < r <= 10 else None


_YEAR = re.compile(r"\((19\d\d|20\d\d)\)")


def _year(name, date=""):
    m = _YEAR.search(name or "")
    if m:
        return m.group(1)
    d = str(date or "")[:4]
    return d if re.fullmatch(r"(19|20)\d\d", d) else None


def _ext(v):
    v = str(v or "").strip().lower().lstrip(".")
    return v if re.fullmatch(r"[a-z0-9]{2,5}", v) else ""


def _adult_cat(c):
    return str(c.get("is_adult")) in ("1", "true", "True") or bool(C._ADULT_GROUP.search(str(c.get("category_name") or "")))


def _norm(s):
    return C._norm(s)


_serials = itertools.count(1)
_TT = re.compile(r"tt\d{5,10}")


def _ids(x):
    """(معرّف TMDB، معرّف IMDb) من عنصر القائمة إن أعطتهما اللوحة — هويةٌ للمطابقة بين البوابات."""
    t = _int(x.get("tmdb") or x.get("tmdb_id"), 0)
    m = _TT.search(str(x.get("imdb") or x.get("imdb_id") or ""))
    return (t if t > 0 else 0), (m.group(0) if m else "")


class Lists:
    """عناصر نوعٍ واحد لاشتراكٍ واحد: بترتيب السيرفر، وبالأحدث، وبالقسم، وبالمعرّف، والبحث."""

    def __init__(self, kind, cats, raw):
        self.kind = kind
        cat_name, hidden = {}, set()
        for c in cats or []:
            if not isinstance(c, dict):
                continue
            cid, name = str(c.get("category_id", "")), " ".join(str(c.get("category_name") or "").split())
            if _adult_cat(c):
                hidden.add(cid)
            elif name:
                cat_name[cid] = name
        key = _ACTION[kind][2]
        items, seen = [], set()
        for x in raw if raw is not None else ():
            if not isinstance(x, dict):
                continue
            iid, name, cat = _int(x.get(key), None), " ".join(str(x.get("name") or "").split()), str(x.get("category_id", ""))
            if iid is None or not name or iid in seen or cat in hidden or str(x.get("is_adult")) == "1":
                continue
            seen.add(iid)
            if kind == "series":
                plot = " ".join(str(x.get("plot") or "").split())
                items.append(Item(iid, name, str(x.get("cover") or ""), cat, _int(x.get("last_modified")),
                                  _rating(x.get("rating")), "", plot[:200] + ("…" if len(plot) > 200 else ""),
                                  _year(name, x.get("releaseDate") or x.get("release_date")), str(x.get("genre") or ""),
                                  *_ids(x), _first(x.get("backdrop_path"))[:300]))
            else:
                items.append(Item(iid, name, str(x.get("stream_icon") or ""), cat, _int(x.get("added")),
                                  _rating(x.get("rating")) if kind == "movie" else None,
                                  _ext(x.get("container_extension")), "", _year(name) if kind == "movie" else None,
                                  str(x.get("genre") or "") if kind == "movie" else "", *(_ids(x) if kind == "movie" else (0, "")),
                                  _first(x.get("backdrop_path"))[:300] if kind == "movie" else ""))
        self._setup(kind, cat_name, items)

    @classmethod
    def restore(cls, kind, cats, rows):
        """قائمةٌ من نسختها على القرص (‏disk_save): الأقسام كما هي، والعناصر صفوفًا بترتيب حقول Item."""
        L = cls(kind, cats, None)
        n = len(Item._fields)
        L._setup(kind, L._cat_name, [Item(*r) for r in rows if isinstance(r, list) and n - 1 <= len(r) <= n])
        return L

    def _setup(self, kind, cat_name, items):
        self.items = items                                   # ترتيب السيرفر (ترتيب تطبيقات IPTV)
        self.by_id = {it.id: it for it in items}
        by_genre = OrderedDict()
        for cid, name in cat_name.items():                   # الأقسام بترتيب السيرفر، والاسم المكرّر قسمٌ واحد
            by_genre.setdefault(name, [])
        name_of = cat_name.get
        for it in items:
            g = name_of(it.cat)
            if g:
                by_genre[g].append(it)
        self.by_genre = OrderedDict((g, v) for g, v in by_genre.items() if v)
        self._cat_name = cat_name
        self.genres = list(self.by_genre)
        # «الكل»: الأحدث إضافةً أولًا للأفلام والمسلسلات؛ والقنوات بترتيب السيرفر (أقسامها متجاورة)
        self.latest = items if kind == "tv" else sorted(items, key=lambda it: -it.added)
        self._keys = None
        self._tags = None
        self._klock = threading.Lock()
        self._mkeys = None
        self._mlock = threading.Lock()
        self.serial = next(_serials)                          # نسخة القائمة: تغيّرها يعيد بناء المكتبة الموحدة

    def match_keys(self, fn):
        """مفاتيح مطابقة العناصر (‏stremio_library.item_key) — تُحسب مرةً لكل نسخةٍ من القائمة."""
        with self._mlock:
            if self._mkeys is None:
                self._mkeys = [fn(it, self.cat_of(it)) for it in self.items]
        return self._mkeys

    def cat_of(self, it):
        """اسم قسم العنصر كما في السيرفر (أو "")."""
        return self._cat_name.get(it.cat, "") if it else ""

    def prepare(self):
        """فهرس البحث (الأسماء بلا تشكيل ولا همزات) — يُبنى مرةً مع التحميل."""
        with self._klock:
            if self._keys is None:
                self._keys = [_norm(it.name) for it in self.items]
        return self

    def tagged(self, g):
        """عناصر تصنيف الفيلم أو المسلسل («جريمة» · «Crime»، من حقل genre في قائمة السيرفر) بالأحدث — فهرسه يُبنى مرةً
        عند أول طلب."""
        with self._klock:
            if self._tags is None:
                tags = {}
                for it in self.latest:
                    for k in LIB.genre_keys(it.genre):           # بلغتين: «Crime» و«جريمة» مفتاحٌ واحد
                        tags.setdefault(k, []).append(it)
                self._tags = tags
        ks = LIB.genre_keys(g)
        if len(ks) == 1:
            return self._tags.get(next(iter(ks)), [])
        seen = {id(it) for k in ks for it in self._tags.get(k, ())}
        return [it for it in self.latest if id(it) in seen]

    def search(self, q):
        """كل الكلمات في الاسم (بلا تشكيل ولا همزات ولا حالة أحرف): المطابق ثم ما يبدأ بها ثم ما يحويها."""
        words = _norm(q).split()
        if not words:
            return []
        self.prepare()
        phrase = " ".join(words)
        hits = []
        for it, k in zip(self.items, self._keys):
            if all(w in k for w in words):
                rank = 0 if k == phrase else 1 if k.startswith(phrase) else 2 if (" " + phrase) in (" " + k) else 3
                hits.append((rank, -it.added, it))
        hits.sort(key=lambda h: (h[0], h[1]))
        return [h[2] for h in hits]


_cats = OrderedDict()                # (cfg، النوع) ← (الوقت، الأقسام) — لكل مشترك: منها باقته وصلاحية اشتراكه
_lists = OrderedDict()               # (الهوست، النوع، بصمة الأقسام) ← (الوقت، Lists) — مشتركةٌ بين مشتركي الباقة
_list_keys = OrderedDict()           # (cfg، النوع) ← مفتاح قائمته في _lists
_loading = {}                        # المفتاح ← قفل التحميل: طلباتٌ متزامنة تنتظر تحميلًا واحدًا


def _fill(store, key, ttl, load, cap, lk, shared=False, short=None):
    """التحميل نفسه تحت قفله: يُحفظ قبل فكّ القفل فلا يبدأ طلبٌ لاحق تحميلًا ثانيًا. فشل السيرفر وعندنا نسخة: تُعرض
    ويُعاد بعد دقيقة. ورفض الاشتراك يُسقط نسخته — إلا المشتركة (رفض مشتركٍ واحد لا يُسقط قائمة الباقة). ‏short(val):
    قيمةٌ تُحفظ دقيقةً لا أكثر (فارغةٌ ليوزرٍ لم يُفعَّل بعد)."""
    with lk:
        with _lock:
            hit = store.get(key)
            if hit and time.time() - hit[0] < ttl:
                return hit[1]
        try:
            val = load()
        except (AuthError, XtreamError) as e:
            if isinstance(e, AuthError) and not (shared and hit):
                with _lock:
                    store.pop(key, None)
                raise
            if not hit:
                raise
            with _lock:
                store[key] = (time.time() - ttl + RETRY, hit[1])
            return hit[1]
        else:
            with _lock:
                store[key] = (time.time() - (ttl - RETRY if short and short(val) else 0), val)
                store.move_to_end(key)
                while len(store) > cap:
                    store.popitem(last=False)
            return val
        finally:
            with _lock:
                _loading.pop((id(store), key), None)


def _cached(store, key, ttl, load, cap, shared=False, short=None):
    """قيمةٌ محفوظة ما دامت حديثة؛ وقديمةٌ تُعرض فورًا ويُحدَّث نسختها في الخلفية (فلا ينتظر أحدٌ تحميل السيرفر
    إلا أول مرة)؛ ولا شيء ← تُحمَّل مرةً واحدة مهما تزامنت الطلبات."""
    with _lock:
        hit = store.get(key)
        if hit and time.time() - hit[0] < ttl:
            store.move_to_end(key)
            return hit[1]
        busy = (id(store), key) in _loading
        lk = _loading.setdefault((id(store), key), threading.Lock())
        if hit:
            store.move_to_end(key)
    if hit:                              # قديمة: تُعرض، ويُحدَّث في الخلفية (إلا وتحديثٌ جارٍ)
        if not busy:
            def bg():
                try:
                    _fill(store, key, ttl, load, cap, lk, shared, short)
                except Exception:
                    pass
            threading.Thread(target=bg, daemon=True, name="stremio-refresh").start()
        return hit[1]
    return _fill(store, key, ttl, load, cap, lk, shared, short)


def categories(cfg, kind):
    return _cached(_cats, (cfg, kind), TTL, lambda: _list_of(_api(cfg, _ACTION[kind][0])), 2000, short=lambda v: not v)


def _bouquet(cats):
    """بصمة باقة المشترك: أقسامه — من لهم الأقسام نفسها على السيرفر نفسه يرون العناصر نفسها."""
    ids = sorted({str(c.get("category_id")) for c in cats or [] if isinstance(c, dict)})
    return hashlib.sha1(",".join(ids).encode()).hexdigest()[:16]


PART_WORKERS = 4                     # طلبات الأقسام معًا حين تتعثّر القائمة كاملة
# قوائم كاملةٌ تُحمَّل معًا في الخادم كله: قائمة لوحةٍ كبيرة (مرح: 21 ألف فيلم) عشرات الميجا وهي تُقرأ — فتحميلها كلها معًا (التشغيل
# والتحديث لكل الحسابات وتصفّح العملاء) يستنزف الذاكرة ويوقف الخادم عن الرد لحظات؛ والباقي ينتظر دوره
_list_sem = threading.Semaphore(max(1, int(os.environ.get("STREMIO_LIST_LOADS", "2"))))


def _all_items(cfg, kind, cats):
    """كل عناصر النوع بطلبٍ واحد؛ وسيرفرٌ يتعثّر في القائمة كاملة (كاسبر يردّ 503 لقائمة أفلامه الكبيرة) ← قسمًا
    قسمًا (‏category_id، كلٌّ بمحاولتين بعده) ثم تُجمع بترتيب أقسامه بلا تكرار. تعثّر قسمٍ بعدها ← XtreamError."""
    action, key = _ACTION[kind][1], _ACTION[kind][2]
    try:
        return _list_of(_api(cfg, action))
    except AuthError:
        raise
    except XtreamError:
        ids = list(dict.fromkeys(str(c["category_id"]) for c in cats
                                 if isinstance(c, dict) and str(c.get("category_id") or "").strip()))
        if not ids:
            raise

    def part(cid):
        for attempt in range(3):
            try:
                return _list_of(_api(cfg, action, category_id=cid))
            except AuthError:
                raise
            except XtreamError:
                if attempt == 2:
                    raise
                time.sleep(1 + attempt)
    with ThreadPoolExecutor(max_workers=min(PART_WORKERS, len(ids))) as ex:
        parts = list(ex.map(part, ids))
    seen, out = set(), []
    for items in parts:
        for it in items:
            k = it.get(key) if isinstance(it, dict) else None
            if k is None or k not in seen:
                seen.add(k)
                out.append(it)
    return out


def _lkey(cfg, kind, cats=None):
    """مفتاح قائمة المشترك في _lists (‏None إن لم تُعرف أقسامه بعد)."""
    with _lock:
        if cats is None:
            return _list_keys.get((cfg, kind))
        key = (host_key(cfg.host), kind, _bouquet(cats))
        _list_keys[(cfg, kind)] = key
        _list_keys.move_to_end((cfg, kind))
        while len(_list_keys) > 20000:
            _list_keys.popitem(last=False)
        return key


# نسخة القوائم على القرص: بعد إعادة تشغيل الخادم (النشر) تُعرض فورًا وتُحدَّث من السيرفر في الخلفية — كان أول طلبٍ ينتظر قائمة
# مرح الكاملة دقائق. نسخةٌ لكل (سيرفر × باقة × نوع) بآخر ما وصل، مضغوطة؛ وما لم يُحدَّث أسبوعًا يُحذف.
DISK_DAYS = 7
_ddir = [None]


def disk_dir(data_dir):
    """مجلد نسخ القوائم (يُضبط مرةً من الخادم عند التشغيل)."""
    if data_dir and not _ddir[0]:
        _ddir[0] = os.path.join(data_dir, "stremio_lists")


def _dpath(key):
    return os.path.join(_ddir[0], hashlib.sha1(repr(key).encode()).hexdigest()[:20] + ".json.gz") if _ddir[0] else None


def disk_save(key, cats, L):
    """يحفظ نسخة قائمةٍ على القرص (في الخلفية — لا ينتظرها أحد). لا يحفظ قائمةً فارغة."""
    path = _dpath(key)
    if not path or not L.items:
        return False
    try:
        os.makedirs(_ddir[0], exist_ok=True)
        body = json.dumps({"v": 1, "key": list(key), "kind": L.kind, "at": int(time.time()), "cats": cats,
                           "items": [list(it) for it in L.items]}, ensure_ascii=False, separators=(",", ":"))
        tmp = path + ".tmp"
        with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=5) as f:
            f.write(body)
        os.replace(tmp, path)
        cut = time.time() - DISK_DAYS * 86400
        for folder in (_ddir[0], os.path.join(_ddir[0], "info")):   # نسخٌ لم تُحدَّث أسبوعًا (باقةٌ لم تعد تُستعمل)
            for name in os.listdir(folder) if os.path.isdir(folder) else ():
                fp = os.path.join(folder, name)
                if name.endswith(".json.gz") and os.path.getmtime(fp) < cut:
                    os.remove(fp)
        return True
    except (OSError, TypeError, ValueError):
        return False


def disk_load(key, kind):
    """نسخة القائمة على القرص ← (وقت حفظها، Lists)، أو None."""
    path = _dpath(key)
    if not path or not os.path.exists(path):
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            d = json.load(f)
        if d.get("v") != 1 or d.get("kind") != kind or tuple(d.get("key") or ()) != tuple(key):
            return None
        L = Lists.restore(kind, d.get("cats") or [], d.get("items") or [])
        L.prepare()
        return (float(d.get("at") or 0), L) if L.items else None
    except (OSError, ValueError, TypeError, EOFError):
        return None


def _from_disk(key, kind):
    """قائمةٌ ليست في الذاكرة ولها نسخةٌ على القرص ← تُوضع في الذاكرة قديمةً (فتُعرض فورًا ويُحدَّثها _cached في الخلفية)."""
    with _lock:
        if key in _lists:
            return
    hit = disk_load(key, kind)
    if not hit:
        return
    with _lock:
        if key not in _lists:
            _lists[key] = (min(hit[0], time.time() - TTL), hit[1])     # قديمةٌ دائمًا: التحديث يبدأ من أول طلب
            _lists.move_to_end(key)
            while len(_lists) > LISTS_MAX:
                _lists.popitem(last=False)


def lists(cfg, kind):
    """كل عناصر النوع (‏movie · series · tv). مشتركةٌ بين مشتركي الباقة نفسها على السيرفر نفسه (تحميلٌ واحد لهم كلهم
    لا لكل مشترك)، وقديمتها تُعرض فورًا وتُحدَّث في الخلفية — فالبحث والتصفّح لا ينتظران السيرفر إلا أول مرة. وأقسام
    المشترك نفسه تُقرأ له (منها باقته، وتتحقّق من اشتراكه)."""
    cats = categories(cfg, kind)
    key = _lkey(cfg, kind, cats)
    _from_disk(key, kind)                # بعد إعادة التشغيل: آخر نسخةٍ على القرص فورًا

    def load():
        with _list_sem:
            L = Lists(kind, cats, _all_items(cfg, kind, cats))
            L.prepare()                  # فهرس البحث مع التحميل: أول بحثٍ لا يبنيه
        _bg(disk_save, key, cats, L)
        return L
    return _cached(_lists, key, TTL, load, LISTS_MAX, shared=True, short=lambda L: not L.items)


def warm(cfg):
    """يحمّل قوائم اشتراكٍ (الأنواع الثلاثة) مسبقًا — لسيرفرات الحسابات عند التشغيل وكل حين، فيجدها أول بحث. ← كم
    حُمّل."""
    n = 0
    for kind in TYPES:
        try:
            lists(cfg, kind)
            n += 1
        except XtreamError:
            pass
    return n


def _cached_lists(cfg, kind):
    """القوائم إن كانت في الذاكرة فقط (بلا تحميل) — للتفاصيل والتشغيل حين يكفي غيرها."""
    key = _lkey(cfg, kind)
    with _lock:
        hit = _lists.get(key) if key else None
    return hit[1] if hit else None


def set_lists(cfg, kind, L, age=0):
    """يضع قائمةً لمشتركٍ في الذاكرة (للاختبارات): بعمرٍ age ثانية."""
    key = _lkey(cfg, kind) or _lkey(cfg, kind, [])
    with _lock:
        _lists[key] = (time.time() - age, L)


def drop_lists(cfg, kind):
    """ينسى قائمة مشتركٍ ومفتاحها وأقسامه (للاختبارات ولإعادة القراءة)."""
    with _lock:
        key = _list_keys.pop((cfg, kind), None)
        cats = _cats.pop((cfg, kind), None)
        if not key and cats:                 # لم يُطلب بعد: مفتاح باقته من أقسامه
            key = (host_key(cfg.host), kind, _bouquet(cats[1]))
        if key:
            _lists.pop(key, None)


def has_lists(cfg, kind):
    return _cached_lists(cfg, kind) is not None


_info = OrderedDict()                # (الهوست، الإجراء، المعرّف) ← (الوقت، الرد)


_info_busy = set()


def _ipath(key):
    return os.path.join(_ddir[0], "info", hashlib.sha1(repr(key).encode()).hexdigest()[:20] + ".json.gz") if _ddir[0] else None


def _info_disk(key):
    """تفاصيل عنصرٍ فُتح قبلُ من القرص ← (وقتها، الرد) أو None — «تابع المشاهدة» بعد إعادة التشغيل يجد اسمه وصورته فورًا."""
    path = _ipath(key)
    if not path or not os.path.exists(path):
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            d = json.load(f)
        return (float(d["at"]), d["d"]) if isinstance(d.get("d"), dict) and d.get("key") == list(key) else None
    except (OSError, ValueError, TypeError, KeyError, EOFError):
        return None


def _info_save(key, d):
    path = _ipath(key)
    if not path:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=5) as f:
            json.dump({"key": list(key), "at": int(time.time()), "d": d}, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except (OSError, TypeError, ValueError):
        pass


def _details(cfg, action, field, iid):
    """تفاصيل فيلمٍ أو مسلسل (تُحفظ ساعات، ونسختها على القرص) — وفشلها None لا خطأ: تبقى بيانات القائمة. وقديمتها
    (من الذاكرة أو القرص) تُعرض فورًا وتُجدَّد في الخلفية."""
    key = (host_key(cfg.host), action, iid)      # تفاصيل العنصر واحدةٌ لكل مشتركي السيرفر
    with _lock:
        hit = _info.get(key)
    if not hit:
        hit = _info_disk(key)
        if hit:
            with _lock:
                _info[key] = hit
                _info.move_to_end(key)
    if hit and time.time() - hit[0] < INFO_TTL:
        return hit[1]
    if hit:                                      # قديمة: تُعرض الآن، وتُجدَّد في الخلفية مرةً واحدة
        with _lock:
            busy = key in _info_busy
            _info_busy.add(key)
        if not busy:
            def refresh():
                try:
                    _fetch_details(cfg, action, field, iid, key, None)
                except Exception:
                    pass
                finally:
                    with _lock:
                        _info_busy.discard(key)
            _bg(refresh)
        return hit[1]
    return _fetch_details(cfg, action, field, iid, key, hit)


def _fetch_details(cfg, action, field, iid, key, hit):
    try:
        d = _api(cfg, action, **{field: iid})
    except AuthError:
        raise
    except XtreamError:
        return hit[1] if hit else None
    if not isinstance(d, dict) or not d:
        return hit[1] if hit else None   # ردٌّ فارغ لا يُحفظ ساعات: قد يكون عابرًا
    if action == "get_vod_info" and isinstance(d.get("info"), dict):
        note_genre(cfg, iid, d["info"].get("genre"))
    with _lock:
        _info[key] = (time.time(), d)
        _info.move_to_end(key)
        while len(_info) > INFO_MAX:
            _info.popitem(last=False)
    _bg(_info_save, key, d)
    return d


# ---- تصنيفات الأفلام: كثيرٌ من السيرفرات لا يذكر genre في قائمة الأفلام (get_vod_streams) بل في تفاصيل الفيلم وحدها،
# فكان «جريمة» في صفحة فيلمٍ لا يجد إلا ما فُتح. تُجمع لكل سيرفر (مشتركةً بين مشتركيه) ممّا يُفتح، وفي الخلفية بتمهّل
# (‏crawl_genres: الأحدث أولًا)، وتُحفظ على القرص فلا يُطلب فيلمٌ مرتين.
_genres = {}                         # بصمة السيرفر ← {"ids": {المعرّف: genre}، "rev": {مفتاح التصنيف: {المعرّفات}}، "dirty"}
_gdir = [None]


def _ghk(cfg):
    return host_key(cfg.origin or cfg.host)


def genre_dir(data_dir):
    """مجلد حفظ التصنيفات (مرةً من handle أو من الجمع في الخلفية)."""
    if data_dir and not _gdir[0]:
        _gdir[0] = os.path.join(data_dir, "stremio_genres")


def _gpath(hk):
    return os.path.join(_gdir[0], hashlib.sha1(hk.encode()).hexdigest()[:16] + ".json") if _gdir[0] else None


def _gstore(hk):
    """مخزن السيرفر (يُقرأ من القرص أول مرة) — يُستدعى و_lock مقفل."""
    st = _genres.get(hk)
    if st is None:
        ids = {}
        path = _gpath(hk)
        try:
            with open(path, encoding="utf-8") as f:
                ids = {int(k): str(v) for k, v in json.load(f).items()}
        except (TypeError, OSError, ValueError, AttributeError):
            pass
        rev = {}
        for iid, raw in ids.items():
            for k in LIB.genre_keys(raw):
                rev.setdefault(k, set()).add(iid)
        st = _genres[hk] = {"ids": ids, "rev": rev, "dirty": False}
    return st


def note_genre(cfg, iid, raw):
    """تصنيف فيلمٍ من تفاصيله (‏"" لا تصنيف له: لا يُطلب ثانيةً)."""
    hk, raw = _ghk(cfg), " ".join(str(raw or "").split())[:200]
    with _lock:
        st = _gstore(hk)
        old = st["ids"].get(iid)
        if old == raw:
            return
        for k in LIB.genre_keys(old):
            st["rev"].get(k, set()).discard(iid)
        st["ids"][iid] = raw
        for k in LIB.genre_keys(raw):
            st["rev"].setdefault(k, set()).add(iid)
        st["dirty"] = True


def genre_ids(cfg, g):
    """معرّفات أفلام السيرفر في تصنيفٍ («جريمة» = «Crime») ممّا عُرف من التفاصيل."""
    ks = LIB.genre_keys(g)
    with _lock:
        st = _gstore(_ghk(cfg))
        return set().union(*(st["rev"].get(k, ()) for k in ks)) if ks else set()


def save_genres():
    """يحفظ ما تغيّر من المخازن على القرص."""
    with _lock:
        todo = [(hk, dict(st["ids"])) for hk, st in _genres.items() if st["dirty"]]
        for hk, _ in todo:
            _genres[hk]["dirty"] = False
    for hk, ids in todo:
        path = _gpath(hk)
        if not path:
            continue
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({str(k): v for k, v in ids.items()}, f, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp, path)
        except OSError:
            with _lock:
                _genres[hk]["dirty"] = True


def crawl_genres(cfg, data_dir=None, limit=GENRE_BATCH, rps=None, stop=None):
    """دفعةٌ في الخلفية: تفاصيل أفلامٍ بلا تصنيفٍ في قائمة السيرفر ولا في المخزن — الأحدث إضافةً أولًا، بتمهّل (‏rps في
    الثانية)، ومن قائمةٍ في الذاكرة وحدها (لا يُحمّل شيئًا جديدًا). سيرفرٌ يتعثّر أو يرفض ← تتوقف الدفعة. ← عدد ما طُلب."""
    genre_dir(data_dir)
    rps = GENRE_RPS if rps is None else rps
    L = _cached_lists(cfg, "movie")
    if rps <= 0 or not L:
        return 0
    with _lock:
        known = set(_gstore(_ghk(cfg))["ids"])
    todo = [it.id for it in L.latest if not it.genre and it.id not in known][:limit]
    n = 0
    for iid in todo:
        if stop and stop():
            break
        try:
            d = _api(cfg, "get_vod_info", vod_id=iid)
        except (AuthError, XtreamError):
            break
        info = d.get("info") if isinstance(d, dict) and isinstance(d.get("info"), dict) else {}
        note_genre(cfg, iid, info.get("genre"))
        n += 1
        time.sleep(1 / rps)
    save_genres()
    return n


def reset():
    """تفريغ الذاكرة (للاختبارات)."""
    with _lock:
        for s in (_accounts, _cats, _lists, _list_keys, _info, _rate, _libs, _probes, _lines_cache, _genres, _line_jobs):
            s.clear()
        _loading.clear()
        _gdir[0] = None
        _ddir[0] = None


# ================= ما يراه Stremio =================
def _clean(d):
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


def _split(v):
    return [x.strip() for x in re.split(r"[,،/|]", str(v or "")) if x.strip()][:12]


def _first(v):
    if isinstance(v, list):
        v = next((x for x in v if isinstance(x, str) and x.strip()), "")
    return v.strip() if isinstance(v, str) else ""


def _released(v):
    """تاريخ الحلقة بصيغة ISO كما يقبله Stremio — وتاريخٌ لا يُفهم يُحذف (تاريخٌ خاطئ يُسقط الصفحة كلها)."""
    s = str(v or "").strip()[:10]
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d").strftime("%Y-%m-%dT00:00:00.000Z")
    except ValueError:
        return None


def _preview(pre, kind, it):
    return _clean({"id": f"{pre}{_CODE[kind]}:{it.id}", "type": kind, "name": it.name, "poster": it.poster,
                   "background": it.bg or None, "posterShape": "square" if kind == "tv" else "poster", "releaseInfo": it.year,
                   "imdbRating": it.rating, "description": it.plot or None, "genres": LIB.genre_names(it.genre)})


_COUNT = re.compile(r"\s*\([\d,]+\)$")       # «مسلسلات تركية (855)» ← عدد القسم في قائمة التصنيف


def _fmt(n):
    return f"{n:,}"


def _kind_info(cfg, kind):
    """(الأقسام بأعدادها، المجموع) لنوعٍ — من القوائم نفسها (ما يُعرض فعلًا، بلا الكبار)، وإلا أسماء الأقسام بلا
    أعداد، وإلا لا شيء. ‏AuthError تصعد: اشتراكٌ يرفضه السيرفر."""
    try:
        L = lists(cfg, kind)
        return [(g, len(L.by_genre[g])) for g in L.genres], len(L.items)
    except AuthError:
        raise
    except XtreamError:
        pass
    try:
        seen, out = set(), []
        for c in categories(cfg, kind):
            name = " ".join(str(c.get("category_name") or "").split()) if isinstance(c, dict) else ""
            if name and name not in seen and not _adult_cat(c):
                seen.add(name)
                out.append((name, None))
        return out, None
    except AuthError:
        raise
    except XtreamError:
        return [], None


def manifest(cfg, base, label="", accounts=True, lines=None, catalogs=True):
    return build_manifest(cfg, base, label, accounts, lines, catalogs)[0]


def _lib_info(lines, kind):
    """(الأقسام بأعدادها، المجموع، أسماء الخطوط) لنوعٍ من المكتبة الموحدة — أو None إن تعذّرت كل خطوطها."""
    try:
        lib = library(lines, kind, full=True)          # الـmanifest يُثبَّت مرة: بأقسام خطوطه كلها وأعدادها
    except XtreamError:
        return None
    return lib.genres, len(lib.works), lib.labels


def manifest_id(cfg):
    """معرّف الإضافة للخط (ثابتٌ من هوسته الأصلي ويوزره) — به تعرف تطبيقات Nuvio كتالوجاتها في المجموعات وترتيب الرئيسية."""
    return "com.ssouq.xtream." + hashlib.sha256(f"{cfg.origin or cfg.host}\n{cfg.user}".encode()).hexdigest()[:10]


NUVIO_TITLES = {"series": "المسلسلات", "movie": "الأفلام", "tv": "القنوات"}   # أسماء كتالوجات إضافة Nuvio (عربيةٌ ومختلفة)


def build_manifest(cfg, base, label="", accounts=True, lines=None, catalogs=True):
    """(وصف الإضافة، حاله) بترتيب تطبيقات IPTV: «الحسابات» (‏accounts: لصاحب حساب Stremio أو رابطٍ وحده — والخط
    المرتبط بلاها، فلا يتكرّر صفّها) ثم المسلسلات ثم الأفلام ثم البث المباشر، باسم السيرفر وعدد محتوى كلٍّ («سمارت
    (10,329)»، ويُلحق Stremio النوع)، وأقسام السيرفر تصنيفاتٌ بعدد كلٍّ («مسلسلات تركية (855)» · «رياضة (120)»).
    الأنواع الثلاثة تُحمَّل معًا. فشل نوعٍ لا يُسقط الإضافة: يبقى كتالوجه بلا أعداد أو بلا تصنيفات؛
    واشتراكٌ يرفضه السيرفر تُثبَّت إضافته كما هي وتعمل متى جُدِّد. الحال: "ok" حُمّلت الأنواع كلها وفيها محتوى ·
    "pending" رُفض الاشتراك أو جاء فارغًا (يوزرٌ لم يُفعَّل بعد: يُعاد بعد قليل) · "error" تعذّر نوعٌ من السيرفر نفسه
    (انقطاعٌ أو مهلة: الإعادة الفورية لا تفيد).
    ‏lines: خطوط الحساب (صاحبه أولًا) ← الأعداد والأقسام من المكتبة الموحدة، وبأكثر من خط: الكتالوج باسم المتجر وفي التصنيف
    «مصدر: كاسبر» لكل خط. ‏catalogs=False: إضافة خطٍّ مرتبط — بلا كتالوجات (محتواه في مكتبة صاحب الحساب)، وتبقى تفاصيل
    ما في مكتبة Stremio ببادئتها وتشغيله، ومصادره في أعمال المكتبة الموحدة (زرٌّ باسمه فوق قائمة التشغيل)."""
    pre = prefix(cfg)
    uid = manifest_id(cfg).rsplit(".", 1)[1]
    tag = f" · {label}" if label else ""

    def one(kind):
        try:
            genres, total = _kind_info(cfg, kind)
            return genres, total, "error" if total is None else None
        except AuthError:
            return [], None, "auth"
    with ThreadPoolExecutor(max_workers=len(TYPES)) as ex:
        info = dict(zip(TYPES, ex.map(one, TYPES)))
    nuvio = bool(lines and lines[0].get("nuvio"))         # إضافة حساب Nuvio: أسماء كتالوجاتها عربيةٌ لكل نوع
    cats = [{"type": ACCOUNTS, "id": ACCOUNTS_ID, "name": "حساباتي" if nuvio else BRAND, "extra": [], "extraSupported": []}] if accounts else []
    totals = []
    multi = bool(lines and len(lines) > 1)
    for kind in ORDER:
        genres, total, _ = info[kind]
        srcs, rows = [], []
        if lines and catalogs:
            li = _lib_info(lines, kind)
            if li:
                genres, total, labels = li
                srcs = [SRC_TAG + lb for lb in labels] if multi else []
                # تصنيفات سمارت سوق بدل أقسام كل لوحة (ما لم يدخل منها شيءٌ تصنيفًا: أقسام اللوحات كما كانت)
                by = _cat_index(lines, library(lines, kind, full=True), kind)["by"]
                mine = CATS.of_kind(_ucats(lines), kind)
                unified = [(c["name"], len(by[c["id"]])) for c in mine if by.get(c["id"])]
                if unified:
                    genres = unified + ([(CATS.OTHERS, len(by[CATS.OTHERS_ID]))] if by.get(CATS.OTHERS_ID) else [])
                    rows = [c for c in mine if c.get("home") and by.get(c["id"])]
        if not catalogs:
            if total:
                totals.append(f"{_fmt(total)} {_UNIT[kind]}")
            continue
        opts = [f"{g} ({_fmt(n)})" if n is not None else g for g, n in genres] + srcs
        extra = ([{"name": "genre", "options": opts, "isRequired": False}] if opts else []) + \
            [{"name": "search", "isRequired": False}, {"name": "skip", "isRequired": False}]
        # الاسم بلا كلمة النوع: Stremio يُلحق النوع بلغة واجهته («سمارت (10,329) - المسلسلات» · «… - Series»)
        cats.append({"type": kind, "id": CATALOG[kind], "extra": extra, "extraSupported": [e["name"] for e in extra],
                     "name": (NUVIO_TITLES[kind] if nuvio else BRAND if multi else label or BRAND) + (f" ({_fmt(total)})" if total else "")})
        # صفوف الرئيسية: تصنيفٌ لكلٍّ («تركي - المسلسلات»)، بلا بحث (فلا تتكرّر نتائجه) ولا قائمة تصنيف
        cats += [{"type": kind, "id": CAT_PREFIX + c["id"], "name": c["name"], "extra": [{"name": "skip", "isRequired": False}],
                  "extraSupported": ["skip"]} for c in rows]
        if total:
            totals.append(f"{_fmt(total)} {_UNIT[kind]}")
    errs = {info[k][2] for k in TYPES}
    state = "error" if "error" in errs else "pending" if "auth" in errs or not totals else "ok"
    types = ([ACCOUNTS] if accounts else []) + list(ORDER)
    res = {"types": types, "idPrefixes": [pre]}
    if not catalogs:
        about = "خطٌّ ضمن مكتبة حسابك الموحدة: محتواه مع باقي اشتراكاتك في صفوف «" + BRAND + "»، بلا تكرار."
    elif multi:
        about = ("مكتبةٌ واحدة لكل اشتراكاتك: العمل مرةً واحدة ومصادره كلها معه، و«تلقائي» ينتقل للمصدر التالي إن تعطّل؛ "
                 "بترتيب تطبيقات IPTV: الحسابات ثم المسلسلات ثم الأفلام ثم البث المباشر، والبحث في كل الاشتراكات معًا.")
    else:
        about = "اشتراكك في Stremio بترتيب تطبيقات IPTV: " + ("الحسابات (حال اشتراكك وانتهاؤه)، ثم " if accounts else "") + \
            "المسلسلات بمواسمها وحلقاتها، والأفلام والبث المباشر بأقسام السيرفر نفسها، والبحث بالاسم في الثلاثة."
    return {
        "id": f"com.ssouq.xtream.{uid}",
        "version": VERSION,
        "name": BRAND + tag,
        "description": (" · ".join(totals) + " — " if totals else "") + about,
        "logo": f"{base}/static/icons/icon-512.png",
        "background": f"{base}/static/og-image.png",
        "types": types,
        "idPrefixes": [pre],
        # الخط المرتبط: مصادره في أعمال المكتبة الموحدة (معرّفاتها ببادئة صاحب الحساب، وكل بادئاتنا تبدأ بـ sq) — انظر line_streams
        "resources": ["catalog", {"name": "meta", **res}, {"name": "stream", **res, **({} if catalogs else {"idPrefixes": [pre, "sq"]})}],
        "catalogs": cats,
        "behaviorHints": {"configurable": True, "configurationRequired": False},
    }, state


def forget_empty(cfg):
    """ينسى حالة اشتراكٍ وما حُفظ له فارغًا من أقسامٍ وقوائم (يوزرٌ لم يُفعَّل بعد) — فيُقرأ من السيرفر من جديد،
    وما حُمّل بمحتواه يبقى."""
    with _lock:
        _accounts.pop(cfg, None)
        for kind in TYPES:
            for store, key, empty in ((_cats, (cfg, kind), lambda v: not v),
                                      (_lists, _list_keys.get((cfg, kind)), lambda v: not v.items)):
                hit = store.get(key) if key else None
                if hit and empty(hit[1]):
                    store.pop(key, None)


def parse_extra(s):
    """«genre=English%20Movies&skip=100» ← {"genre": …، "skip": …} (القيم مرمّزة بـ encodeURIComponent)."""
    return dict(parse_qsl(s or "", keep_blank_values=False))


def catalog(cfg, kind, cid, extra):
    """صفحةٌ من الكتالوج: بحث، أو قسم، أو الكل — 100 عنصر من ‏skip."""
    if kind not in CATALOG or cid != CATALOG[kind]:
        return None
    L = lists(cfg, kind)
    skip = max(0, _int(extra.get("skip"), 0))
    if extra.get("search"):
        seq = L.search(extra["search"])
    elif extra.get("genre"):
        g = " ".join(extra["genre"].split())          # بعددٍ («… (855)») من manifest اليوم، أو بلا عدد من أقدم
        seq = L.by_genre.get(g) or L.by_genre.get(_COUNT.sub("", g)) or _tagged(cfg, kind, L, g)
    else:
        seq = L.latest
    pre = prefix(cfg)
    metas = [_preview(pre, kind, it) for it in seq[skip:skip + PAGE]]
    if kind == "tv":                                  # القناة: اسم قسمها وصفًا يميّزها عن مثيلاتها
        for m, it in zip(metas, seq[skip:skip + PAGE]):
            if L.cat_of(it):
                m["description"] = L.cat_of(it)
    return {"metas": metas}


def _tagged(cfg, kind, L, g):
    """تصنيف الفيلم أو المسلسل (رابطٌ في صفحته: «جريمة» ← كل ما في الاشتراك منه، و«Crime» معه): من قائمة السيرفر، ومعها
    أفلامٌ عُرف تصنيفها من تفاصيلها (سيرفراتٌ لا تذكره في القائمة — انظر note_genre · crawl_genres)."""
    if kind not in GENRE_TYPES:
        return []
    seq = L.tagged(g)
    if kind != "movie":
        return seq
    have = {it.id for it in seq}
    more = [L.by_id[i] for i in genre_ids(cfg, g) if i not in have and i in L.by_id]
    return sorted(seq + more, key=lambda it: -it.added) if more else seq


def _links(man, kind, name, rating, genres):
    """روابط صفحة العنصر: تصنيفاته إلى كتالوجنا مصفًّى بها (Stremio يربط التصنيفات وحدها بـ Cinemeta، فلا تُظهر محتوى
    الاشتراك)، والتقييم إلى بحث IMDb بالاسم. ‏man: رابط الـmanifest كما ثُبّت (‏None: بلا روابط)."""
    if not man:
        return None
    url = f"stremio:///discover/{quote(man, safe='')}/{kind}/{CATALOG[kind]}?genre="
    out = [{"name": rating, "category": "imdb", "url": "https://imdb.com/find/?q=" + quote(name, safe="")}] if rating else []
    return out + [{"name": g, "category": "Genres", "url": url + quote(g, safe="")} for g in genres]


def _parse_id(cfg, sid):
    """«sqXXXXXX:m:447178» ← ("m"، 447178، ""). و«…:e:384084:mp4» ← ("e"، 384084، "mp4")."""
    pre = prefix(cfg)
    if not str(sid).startswith(pre):
        return None
    parts = str(sid)[len(pre):].split(":")
    if len(parts) < 2 or parts[0] not in ("m", "s", "l", "e"):
        return None
    num = _int(parts[1], None)
    return (parts[0], num, _ext(parts[2]) if len(parts) > 2 else "") if num is not None and num >= 0 else None


def _ep_title(title, series, season, episode):
    """«احتمال حب (2026) - S01E01» ← «الحلقة 1»؛ وعنوانٌ للحلقة غير اسم المسلسل يبقى."""
    t = " ".join(str(title or "").split())
    for name in {series, _YEAR.sub("", series).strip()}:
        if name and t.lower().startswith(name.lower()):
            t = t[len(name):]
    t = re.sub(r"(?i)\bS\s*\d{1,3}\s*[\s._-]*E\s*\d{1,4}\b", " ", t)
    t = _YEAR.sub(" ", t).strip(" -–—|:._")
    return t if re.search(r"[^\W\d_]", t) else f"الحلقة {episode}"


def _movie_meta(cfg, pre, num, man=None):
    d = _details(cfg, "get_vod_info", "vod_id", num) or {}
    info = d.get("info") if isinstance(d.get("info"), dict) else {}
    md = d.get("movie_data") if isinstance(d.get("movie_data"), dict) else {}
    L = _cached_lists(cfg, "movie")
    it = (L.by_id.get(num) if L else None)
    if not info and not md and not it:
        L = lists(cfg, "movie")
        it = L.by_id.get(num)
        if not it:
            return None
    name = " ".join(str(md.get("name") or (it.name if it else "") or info.get("name") or "").split())
    secs = _int(info.get("duration_secs"))
    trailer = str(info.get("youtube_trailer") or "").strip()
    rating = _rating(info.get("rating")) or (it.rating if it else None)
    genres = LIB.genre_names(info.get("genre")) or LIB.genre_names(it.genre if it else "")
    return _clean({
        "id": f"{pre}m:{num}", "type": "movie", "name": name,
        "poster": str(info.get("movie_image") or info.get("cover_big") or (it.poster if it else "") or ""),
        "background": _first(info.get("backdrop_path")), "posterShape": "poster",
        "description": " ".join(str(info.get("plot") or info.get("description") or "").split()),
        "releaseInfo": _year(name, info.get("releasedate")), "imdbRating": rating,
        "runtime": f"{secs // 60} min" if secs >= 60 else None, "links": _links(man, "movie", name, rating, genres),
        "genres": genres, "cast": _split(info.get("cast") or info.get("actors")),
        "director": _split(info.get("director")), "country": str(info.get("country") or "").strip(),
        "trailers": [{"source": trailer, "type": "Trailer"}] if re.fullmatch(r"[\w-]{6,20}", trailer) else [],
        "behaviorHints": {"defaultVideoId": f"{pre}m:{num}"},
    })


Ep = namedtuple("Ep", "season episode eid ext video height", defaults=(0,))


def _episodes(d, name, season_as=0):
    """تفاصيل المسلسل ← حلقاته بترتيب (الموسم، الحلقة): رقمها في السيرفر وامتدادها وما يعرضه Stremio (‏video بلا id).
    ‏season_as: مدخلٌ لموسمٍ واحد («علي كارا الموسم الثاني») ترقّم لوحته حلقاته موسمًا أول ← يُعاد ترقيمه بموسمه."""
    eps = d.get("episodes") if isinstance(d, dict) else None
    groups = eps.items() if isinstance(eps, dict) else [("", eps if isinstance(eps, list) else [])]
    out, seen = [], set()
    for skey, arr in groups:
        for n, e in enumerate(arr if isinstance(arr, list) else [], 1):
            if not isinstance(e, dict):
                continue
            eid = _int(e.get("id"), None)
            if eid is None or eid in seen:
                continue
            seen.add(eid)
            ei = e.get("info") if isinstance(e.get("info"), dict) else {}
            season = _int(e.get("season"), None)
            season = season if season is not None else _int(ei.get("season"), _int(skey, 1))
            episode = _int(e.get("episode_num"), 0) or n
            out.append(Ep(season, episode, eid, _ext(e.get("container_extension")) or "mp4", {
                "title": _ep_title(e.get("title"), name, season, episode),
                "season": season, "episode": episode, "released": _released(ei.get("releasedate") or ei.get("air_date")),
                "thumbnail": str(ei.get("movie_image") or ""), "overview": " ".join(str(ei.get("plot") or "").split())},
                _height(ei)))
    if season_as and out and len({e.season for e in out}) == 1 and out[0].season != season_as:
        out = [e._replace(season=season_as, video={**e.video, "season": season_as}) for e in out]
    out.sort(key=lambda e: (e.season, e.episode))
    return out


def _series_meta(cfg, pre, num, man=None):
    d = _details(cfg, "get_series_info", "series_id", num)
    if not d:
        L = lists(cfg, "series")
        it = L.by_id.get(num)
        return _clean({**_preview(pre, "series", it), "videos": [],
                       "links": _links(man, "series", it.name, it.rating, LIB.genre_names(it.genre))}) if it else None
    info = d.get("info") if isinstance(d.get("info"), dict) else {}
    L = _cached_lists(cfg, "series")
    it = L.by_id.get(num) if L else None
    name = " ".join(str(info.get("name") or (it.name if it else "")).split())
    videos = [_clean({"id": f"{pre}e:{e.eid}:{e.ext}", **e.video}) for e in _episodes(d, name)]
    trailer = str(info.get("youtube_trailer") or "").strip()
    run = _int(info.get("episode_run_time"))
    rating = _rating(info.get("rating"))
    genres = LIB.genre_names(info.get("genre")) or LIB.genre_names(it.genre if it else "")
    return _clean({
        "id": f"{pre}s:{num}", "type": "series", "name": name,
        "poster": str(info.get("cover") or (it.poster if it else "") or ""), "posterShape": "poster",
        "background": _first(info.get("backdrop_path")),
        "description": " ".join(str(info.get("plot") or "").split()),
        "releaseInfo": _year(name, info.get("releaseDate") or info.get("release_date")),
        "imdbRating": rating, "runtime": f"{run} min" if run > 0 else None, "links": _links(man, "series", name, rating, genres),
        "genres": genres, "cast": _split(info.get("cast")), "director": _split(info.get("director")),
        "trailers": [{"source": trailer, "type": "Trailer"}] if re.fullmatch(r"[\w-]{6,20}", trailer) else [],
        "videos": videos,
    })


def meta(cfg, kind, sid, man=None):
    """تفاصيل عنصر. ‏man رابط الـmanifest كما ثُبّت: منه روابط التصنيفات إلى كتالوجنا (انظر _links)."""
    p = _parse_id(cfg, sid)
    if not p:
        return None
    code, num, _ = p
    pre = prefix(cfg)
    if code == "m" and kind == "movie":
        m = _movie_meta(cfg, pre, num, man)
    elif code == "s" and kind == "series":
        m = _series_meta(cfg, pre, num, man)
    elif code == "l" and kind == "tv":
        L = lists(cfg, "tv")
        it = L.by_id.get(num)
        cat = L.cat_of(it)
        # بلا «logo»: صفحة Stremio تعرضه مكان الاسم، فتظهر صورة القناة وحدها؛ واسم قسمها يميّزها، ورابطه كل قنوات القسم
        m = _clean({**_preview(pre, "tv", it), "description": cat, "genres": [cat] if cat else [],
                    "links": _links(man, "tv", it.name, None, [cat] if cat else []),
                    "behaviorHints": {"defaultVideoId": f"{pre}l:{num}"}}) if it else None
    else:
        m = None
    return {"meta": m} if m else None


def _formats(cfg):
    """صيغ البث المباشر المسموحة للاشتراك (‏allowed_output_formats) — ‏HLS أولًا."""
    try:
        ui, _ = account(cfg)
        fm = [str(f).lower() for f in (ui.get("allowed_output_formats") or []) if str(f).lower() in ("m3u8", "ts")]
    except AuthError:
        raise
    except XtreamError:
        fm = []
    return sorted(set(fm), key=["m3u8", "ts"].index) or ["m3u8", "ts"]


def streams(cfg, kind, sid, play_url=None):
    """مصادر معرّفٍ بصيغته القديمة — ‏play_url: رابطها على خادمنا (يحوّل إلى اللوحة) فلا يصل العميلَ يوزرُ Xtream ولا باسورده؛
    وبلاه رابط اللوحة نفسه (للأدوات)."""
    p = _parse_id(cfg, sid)
    if not p:
        return None
    code, num, ext = p
    u, pw = quote(cfg.user, safe=""), quote(cfg.pw, safe="")
    hk = line_hk(cfg)
    via = lambda k, n, e, direct: f"{play_url}/{hk}.{k}{n}.{e}" if play_url else direct
    hints = {"notWebReady": True, "bingeGroup": "ssouq-" + prefix(cfg).rstrip(":")}
    if code == "m" and kind == "movie":
        # الامتداد: من القائمة في الذاكرة، ثم من تفاصيل الفيلم، ثم من القائمة بتحميلها — فامتدادٌ مخمَّن
        # (‏mp4 والملف mkv) رابطٌ لا يعمل
        L = _cached_lists(cfg, "movie")
        it = L.by_id.get(num) if L else None
        ext = it.ext if it and it.ext else ""
        if not ext:
            d = _details(cfg, "get_vod_info", "vod_id", num) or {}
            md = d.get("movie_data") if isinstance(d.get("movie_data"), dict) else {}
            ext = _ext(md.get("container_extension"))
        if not ext:
            it = lists(cfg, "movie").by_id.get(num)
            ext = (it.ext if it else "") or "mp4"
        return {"streams": [{"url": via("m", num, ext, f"{cfg.host}/movie/{u}/{pw}/{num}.{ext}"), "name": BRAND,
                             "title": f"تشغيل · {ext.upper()}", "behaviorHints": hints}]}
    if code == "e" and kind == "series":
        ext = ext or "mp4"
        return {"streams": [{"url": via("e", num, ext, f"{cfg.host}/series/{u}/{pw}/{num}.{ext}"), "name": BRAND,
                             "title": f"تشغيل · {ext.upper()}", "behaviorHints": hints}]}
    if code == "l" and kind == "tv":
        L = _cached_lists(cfg, "tv")
        it = L.by_id.get(num) if L else None
        ch = f"{it.name}\n" if it else ""              # اسم القناة فوق نوع البث في قائمة التشغيل
        label = {"m3u8": "بث مباشر · HLS", "ts": "بث مباشر · TS"}
        return {"streams": [{"url": via("l", num, f, f"{cfg.host}/live/{u}/{pw}/{num}.{f}"), "name": BRAND, "title": ch + label[f],
                             "behaviorHints": {"notWebReady": True}} for f in _formats(cfg)]}
    return None


# ================= «الحسابات»: حال خطوط حساب Stremio كشاشة الحساب في تطبيقات IPTV =================
# ‏lines: [{"cfg": اشتراك الخط على هوسته الحالي، "label": اسم سيرفره، "art": شعاره (مسارٌ على الموقع) أو ""}] — صاحب
# حساب Stremio أولًا ثم ما رُبط به. المعرّفات ببادئة الإضافة التي تعرضها، فتفاصيلها وتجديدها يُطلبان منها.
_STATUS = {"active": "نشط", "expired": "منتهٍ", "banned": "موقوف", "disabled": "موقوف"}
# لغة الترجمة إعدادٌ في Stremio على كل جهاز (لا يُضبط من الحساب): «تلقائي» يختار المترجم بالعربية، وهذا يكمّله للترجمات
# المضمَّنة في الملف (سوفت)
SUBS_TIP = "للترجمة العربية تلقائيًا: إعدادات Stremio ← المشغّل ← لغة الترجمة ← العربية (مرةً على كل جهاز)"
# إعدادٌ في تطبيق Stremio على تلفاز أندرويد نفسه (من نسخته 1.9.0) — لا يُضبط من الإضافة ولا من الحساب
TITLE_TIP = "لتظهر الأسماء تحت الصور على تلفاز أندرويد: إعدادات Stremio ← فعّل «Show title under catalog items» (مرةً على كل جهاز)"
DAY = 86400


def mask_user(user):
    """يوزر Xtream لا يُعرض للعميل كاملًا («•••567»): يكفي ليعرف خطّه ويذكره للدعم."""
    user = str(user or "")
    return "•••" + (user[-3:] if len(user) > 4 else "")


def line_id(pre, cfg):
    """معرّف خطٍّ في «الحسابات»: من سيرفره الأصلي ويوزره — يبقى كما هو بتحويل الهوست."""
    return f"{pre}a:" + hashlib.sha256(f"{host_key(cfg.origin or cfg.host)}\n{cfg.user}".encode()).hexdigest()[:10]


def remaining(exp, now=None):
    """تاريخ الانتهاء (ثوانٍ) ← «باقي 59 يومًا» بعدده الصحيح بالعربية (جزء اليوم يومٌ)، و«منتهٍ» لما مضى."""
    left = exp - (time.time() if now is None else now)
    if left <= 0:
        return "منتهٍ"
    d = -int(-left // DAY)
    if d <= 2:
        return ("باقي يوم", "باقي يومان")[d - 1]
    r = d % 100
    unit = "أيام" if 3 <= r <= 10 else "يوم" if d > 10 and r in (0, 1, 2) else "يومًا"
    return f"باقي {_fmt(d)} {unit}"


def account_card(line, pre, base, now=None):
    """خطٌّ ← بطاقته في «الحسابات»: اسم سيرفره بحاله («مرح · باقي 59 يومًا»)، وتفاصيله كشاشة الحساب في تطبيقات
    IPTV (الحالة، والانتهاء، والاتصالات، واليوزر، والمحتوى). بلا كلمة المرور."""
    cfg = line["cfg"]
    art = str(line.get("art") or "")
    facts, date = [], None
    try:
        ui, _ = account(cfg)
    except AuthError:
        short = "منتهٍ أو موقوف"
        facts.append("السيرفر لا يقبل الاشتراك الآن (منتهٍ أو موقوف) — جدّده فيعود المحتوى كما هو")
    except XtreamError:
        short = "تعذّر الفحص"
        facts.append("تعذّر الوصول إلى السيرفر الآن — حاول بعد قليل")
    else:
        st = str(ui.get("status") or "").strip()
        st_ar = _STATUS.get(st.lower(), st or "—")
        exp = _int(ui.get("exp_date"), 0)
        left = remaining(exp, now) if exp > 0 else "غير محدود"
        short = left if st.lower() == "active" else st_ar
        facts.append(f"الحالة: {st_ar}" + (" (تجريبي)" if str(ui.get("is_trial")) == "1" else ""))
        if exp > 0:
            date = datetime.datetime.fromtimestamp(exp, datetime.timezone.utc).strftime("%Y-%m-%d")
            facts.append(f"ينتهي {date} ({left})")
        else:
            facts.append("بلا تاريخ انتهاء")
        maxc, act = _int(ui.get("max_connections"), 0), ui.get("active_cons")
        if maxc:
            facts.append(f"الاتصالات: {_int(act)} من {maxc}" if str(act or "").strip() != "" else f"الاتصالات المسموحة: {maxc}")
    facts.append(f"اليوزر: {mask_user(cfg.user)}")
    counts = [f"{_fmt(len(L.items))} {_UNIT[k]}" for k in ORDER for L in [_cached_lists(cfg, k)] if L and L.items]
    if counts:
        facts.append("المحتوى: " + " · ".join(counts))
    facts += [SUBS_TIP, TITLE_TIP]
    lid = line_id(pre, cfg)
    return _clean({"id": lid, "type": ACCOUNTS, "name": f"{line.get('label') or mask_user(cfg.user)} · {short}",
                   "poster": f"{base}{art}" if art.startswith("/") else f"{base}/static/icons/icon-512.png",
                   "posterShape": "square", "releaseInfo": f"حتى {date}" if date else None, "description": " · ".join(facts),
                   "behaviorHints": {"defaultVideoId": lid}})


def accounts_catalog(lines, pre, base):
    """صفّ «الحسابات»: بطاقات الخطوط بترتيبها (حالها يُقرأ معًا، ومحفوظٌ دقائق)."""
    lines = list(lines or [])
    if not lines:
        return {"metas": []}
    with ThreadPoolExecutor(max_workers=min(8, len(lines))) as ex:
        return {"metas": list(ex.map(lambda ln: account_card(ln, pre, base), lines))}


def _line_of(lines, pre, sid):
    return next((ln for ln in lines or [] if line_id(pre, ln["cfg"]) == sid), None)


def accounts_meta(lines, pre, base, sid):
    ln = _line_of(lines, pre, sid)
    return {"meta": account_card(ln, pre, base)} if ln else None


def accounts_streams(lines, pre, sid):
    """«تجديد الاشتراك» في صفحة الخط: يفتح المتجر في المتصفح (‏externalUrl) — كزرّ التجديد في تطبيقات IPTV."""
    if not _line_of(lines, pre, sid):
        return None
    return {"streams": [{"name": BRAND, "title": "تجديد الاشتراك\nمن متجر سمارت سوق", "externalUrl": CONFIGURE_URL}]}


# ================= المكتبة الموحدة: خطوط الحساب كلها مكتبةً واحدة (stremio_library) =================
# إضافة صاحب حساب Stremio تعرض كل خطوطه مكتبةً واحدة: العمل الواحد مرةً واحدة مهما اختلف اسمه بين البوابات، ومصادره
# كلها في صفحته وفي قائمة التشغيل، و«تلقائي» أولها: يجرّب المصادر بالترتيب وينتقل للتالي إن تعطّل. وإضافة الخط المرتبط
# بلا كتالوجات (محتواه في المكتبة)، ويبقى عندها ما في مكتبة Stremio ببادئتها.
#   معرّف العمل: من مصدره المرساة — في خط صاحب الحساب بالصيغة القديمة نفسها («sqXXXX:s:123»، فلا تتغيّر المكتبة و«تابع
#   المشاهدة»)، وفي غيره «sqXXXX:ws:<بصمة السيرفر>.<رقمه>»؛ وأي مصدرٍ في العمل يدلّ عليه. والحلقة «…:we:<بصمة>.<رقم>:<موسم>:<حلقة>».
# مكتبات (باقات الخطوط × نوع) في الذاكرة — مكتبة حسابٍ بثلاث لوحاتٍ كبيرة ~200 ميجا للأنواع الثلاثة، فالحدّ بالذاكرة
LIB_MAX = int(os.environ.get("STREMIO_LIBS", "12"))
_build_sem = threading.Semaphore(1)  # مكتبةٌ تُبنى في المرة الواحدة: ذروة الذاكرة والمعالج محدودة، والطلبات الأخرى تُجاب أثناءه
SRC_TAG = "مصدر: "                   # تصنيف «مصدر: كاسبر» ← كل ما في الخط
PROBE_TIMEOUT = float(os.environ.get("STREMIO_PROBE_TIMEOUT", "4"))   # مهلة فحص المصدر قبل الانتقال للتالي (ثوانٍ)
PROBE_TTL = 60                       # نتيجة فحص رابطٍ تُحفظ دقيقة
PROBE_MAX = 4                        # مصادر تُفحص للتشغيل التلقائي على الأكثر
# خطٌّ بطيءٌ لا يؤخّر المكتبة: سيرفرٌ يتعثّر في قائمته (كاسبر يردّ 503 لقائمة أفلامه فتُحمَّل قسمًا قسمًا) كان يُبقي صفّ
# الأفلام كله ينتظره حتى يفشل، مع كل طلب — فلا تظهر الأفلام. الآن تنتظره المكتبة ثوانيَ ثم تُعرض بالخطوط الجاهزة، ويكمل
# تحميله في الخلفية فيدخلها حين يصل؛ وكذلك تفاصيل مصادر المسلسل وحال خطوط قائمة التشغيل.
LIB_WAIT = float(os.environ.get("STREMIO_LIB_WAIT", "5"))
_libs = OrderedDict()                # (النوع، بصمة الخطوط) ← (نسخ القوائم، Library)
_lib_busy = set()
_lib_build = {}                      # المكتبة ← قفل بنائها الأول: طلباتٌ متزامنة (التحميل المسبق والتحديث والتصفّح) تبنيها مرةً واحدة
_line_jobs = {}                      # (cfg، النوع) ← تحميل قائمة خطٍّ للمكتبة (جارٍ، أو فشلٌ يُذكر دقيقة)
_probes = {}                         # الرابط ← (الوقت، يعمل؟)


def line_hk(cfg):
    """بصمة سيرفر الخط (من هوسته الأصلي) — في معرّفات المكتبة ومصادرها."""
    return hashlib.sha256(host_key(cfg.origin or cfg.host).encode()).hexdigest()[:6]


def _bg(fn, *args):
    """‏fn(*args) في خيطٍ في الخلفية ← Future. يكمل ولو لم ينتظره أحد (فيجد الطلب التالي نتيجته في الذاكرة)."""
    f = Future()

    def run():
        try:
            f.set_result(fn(*args))
        except BaseException as e:   # noqa: BLE001 — الخطأ لمن ينتظره
            f.set_exception(e)
    threading.Thread(target=run, daemon=True, name="stremio-bg").start()
    return f


def _settle(futs, ok, fresh=None):
    """ينتظر ما بدأ الآن (‏fresh، افتراضًا futs كلها) حتى LIB_WAIT ثانية — وما بدأه طلبٌ قبله لا يُنتظر ثانيةً؛ وإن لم يجهز
    بعدها ما يُعرض (‏ok) فأولَ ما يجهز، أو حتى تنتهي كلها."""
    wait(futs if fresh is None else fresh, timeout=LIB_WAIT)
    pending = [f for f in futs if not f.done()]
    while pending and not any(f.done() and ok(f) for f in futs):
        pending = list(wait(pending, return_when=FIRST_COMPLETED)[1])


def _line_job(cfg, kind):
    """تحميل قائمة خطٍّ للمكتبة ← (Future، بدأ الآن؟): واحدٌ مهما تزامنت الطلبات؛ وتعثّر السيرفر يُذكر دقيقة (‏RETRY) فلا يعيد كل
    طلبٍ انتظاره. ورفض الاشتراك لا يُذكر (يُفعَّل اليوزر فيعمل من الطلب التالي)."""
    k = (cfg, kind)
    with _lock:
        f = _line_jobs.get(k)
        if f and (not f.done() or time.time() - f.failed < RETRY):
            return f, False
        f = _line_jobs[k] = Future()
        f.failed = 0

    def run():
        try:
            L = lists(cfg, kind)
        except BaseException as e:   # noqa: BLE001
            with _lock:
                if isinstance(e, XtreamError) and not isinstance(e, AuthError):
                    f.failed = time.time()
                elif _line_jobs.get(k) is f:
                    _line_jobs.pop(k, None)
            f.set_exception(e)
        else:
            with _lock:
                if _line_jobs.get(k) is f:
                    _line_jobs.pop(k, None)
            f.set_result(L)
    threading.Thread(target=run, daemon=True, name="stremio-line").start()
    return f, True


def _lib_parts(lines, kind, full=False):
    """قوائم الخطوط لنوعٍ معًا ← [(رقم الخط، بصمته، اسمه، Lists أو None)]. خطٌّ لم تصل قائمته بعد LIB_WAIT ثانية ‏None
    هذه المرة (ما دام غيره جاهزًا) ويكمل تحميله في الخلفية — إلا ‏full: تُنتظر كلها؛ وخطٌّ يتعثّر يُتخطّى (والمكتبة
    بباقيها)، وكلها تتعثّر ← الخطأ."""
    started = [_line_job(ln["cfg"], kind) for ln in lines]
    jobs = [f for f, _ in started]
    if full:
        wait(jobs)
    else:
        _settle(jobs, lambda f: f.exception() is None, [f for f, fresh in started if fresh])
    parts, errs = [], []
    for li, (ln, f) in enumerate(zip(lines, jobs)):
        L = None
        if f.done():
            e = f.exception()
            if e is None:
                L = f.result()
            elif isinstance(e, XtreamError):
                errs.append(e)
            else:
                raise e
        parts.append((li, line_hk(ln["cfg"]), ln.get("label") or "", L))
    if errs and all(L is None for *_, L in parts):
        raise errs[0]
    return parts


def library(lines, kind, full=False):
    """مكتبة خطوط الحساب الموحدة لنوع. تُبنى مرةً لكل نسخةٍ من قوائم خطوطها: تجدُّد قائمة خطٍّ (إضافةٌ أو حذفٌ أو تعديلٌ في
    السيرفر) يعيد بناءها في الخلفية والقديمة تُعرض حتى تكتمل. ‏full: بقوائم خطوطها كلها (تُنتظر)، ومحفوظةٌ ينقصها خطٌّ وصل
    الآن تُبنى الآن لا في الخلفية."""
    parts = _lib_parts(lines, kind, full)
    # مفتاحها: سيرفر كل خطٍّ واسمه وقائمته (باقته) — حساباتٌ بالباقات نفسها تشترك في مكتبةٍ واحدة
    gkey = (kind,) + tuple((line_hk(ln["cfg"]), ln.get("label") or "", _lkey(ln["cfg"], kind)) for ln in lines)
    lsig = tuple(L.serial if L else 0 for *_, L in parts)
    with _lock:
        hit = _libs.get(gkey)
        if hit:
            _libs.move_to_end(gkey)
    if hit and (hit[0] == lsig or not any(lsig)):
        return hit[1]
    if full and hit and any(new and not old for old, new in zip(hit[0], lsig)):
        hit = None

    def store(lib):
        with _lock:
            _libs[gkey] = (lsig, lib)
            _libs.move_to_end(gkey)
            while len(_libs) > LIB_MAX:
                _libs.popitem(last=False)
    if hit:
        with _lock:
            busy = gkey in _lib_busy
            _lib_busy.add(gkey)
        if not busy:
            def bg():
                try:
                    store(_build(kind, parts))
                except Exception:
                    pass
                finally:
                    with _lock:
                        _lib_busy.discard(gkey)
            threading.Thread(target=bg, daemon=True, name="stremio-library").start()
        return hit[1]
    with _lock:
        lk = _lib_build.setdefault(gkey, threading.Lock())
    with lk:                                             # بناءٌ جارٍ للمكتبة نفسها: تُنتظر نتيجته ولا تُبنى ثانيةً
        with _lock:
            hit = _libs.get(gkey)
        if hit and hit[0] == lsig:                       # بُنيت من القوائم نفسها أثناء الانتظار
            return hit[1]
        lib = _build(kind, parts)
        store(lib)
    return lib


def _build(kind, parts):
    with _build_sem:
        return LIB.build(kind, parts)


def cached_library(lines, kind):
    """مكتبة خطوط الحساب لنوعٍ إن كانت في الذاكرة — بلا تحميلٍ ولا بناء (لصفحاتٍ لا تنتظر: معاينة التصنيفات) — أو None."""
    keys = [_lkey(ln["cfg"], kind) for ln in lines]
    if not keys or not all(keys):
        return None
    gkey = (kind,) + tuple((line_hk(ln["cfg"]), ln.get("label") or "", k) for ln, k in zip(lines, keys))
    with _lock:
        hit = _libs.get(gkey)
    return hit[1] if hit else None


INSPECT_MAX = 12


def inspect_work(lines, q):
    """«فحص عمل» في الأداة: لماذا لم يظهر عملٌ (أو مصدرٌ له) — من الذاكرة وحدها، بلا انتظار سيرفر. لكل نوع (مسلسلات وأفلام):
    ‏works: أعمال المكتبة الموحدة بهذا الاسم ومصادرها (الخط، الاسم كما في لوحته، السنة، الموسم، TMDB)؛ ‏lines: لكل خطٍّ ما في
    قائمته بهذا الاسم (أو «لم تُحمَّل بعد» — ويبدأ تحميلها في الخلفية). ‏conflicts: الاسم نفسه بمعرّفَي TMDB مختلفين (فيبقيان
    عملين)."""
    words = LIB.norm(q).split()
    out = {"q": str(q or ""), "kinds": []}
    if not words:
        return out
    for kind in ("series", "movie"):
        per, keys = [], {}
        for ln in lines:
            cfg = ln["cfg"]
            L = _cached_lists(cfg, kind)
            row = {"label": ln.get("label") or "", "hk": line_hk(cfg), "loaded": L is not None, "items": []}
            if L is None:
                try:
                    _line_job(cfg, kind)                 # تبدأ في الخلفية: الفحص التالي يجدها
                except Exception:
                    pass
            else:
                for it in L.items:
                    n = LIB.norm(it.name)
                    if all(w in n for w in words):
                        k = LIB.item_key(it, L.cat_of(it))
                        row["items"].append({"name": it.name, "year": k.year or None, "season": k.season or None,
                                             "tmdb": k.tmdb or None, "cat": L.cat_of(it), "key": k.nkey})
                        if k.tmdb:
                            keys.setdefault(k.nkey, set()).add(k.tmdb)
                        if len(row["items"]) >= INSPECT_MAX:
                            break
            per.append(row)
        lib = cached_library(lines, kind)
        if lib is None and all(r["loaded"] for r in per):
            _bg(warm_library, lines)                     # قوائمها جاهزة ولم تُبنَ مكتبتها بعد: تُبنى في الخلفية
        works = []
        for w in (lib.search(q)[:INSPECT_MAX] if lib else []):
            works.append({"name": w.name, "year": w.year, "id": w.anchor.key.nkey,
                          "sources": [{"label": src.label, "hk": src.hk, "name": src.item.name, "year": src.key.year or None,
                                       "season": src.key.season or None, "tmdb": src.key.tmdb or None} for src in w.sources]})
        if works or any(r["items"] or not r["loaded"] for r in per):
            out["kinds"].append({"kind": kind, "library": lib is not None, "works": works, "lines": per,
                                 "conflicts": sorted(k for k, ids in keys.items() if len(ids) > 1)})
    return out


def warm_library(lines):
    """يبني مكتبات حسابٍ مسبقًا — لكل نوعٍ قوائم خطوطه كلها في الذاكرة (فلا يسأل السيرفرات شيئًا جديدًا)؛ فأول تصفّحٍ أو
    بحثٍ لا ينتظر المطابقة. ← كم بُني."""
    n = 0
    for kind in TYPES:
        if all(has_lists(ln["cfg"], kind) for ln in lines):
            try:
                library(lines, kind)
                n += 1
            except XtreamError:
                pass
    return n


def work_id(pre, w):
    s = w.anchor
    code = _CODE[w.kind]
    return f"{pre}{code}:{s.item.id}" if s.line == 0 else f"{pre}w{code}:{s.hk}.{s.item.id}"


_KIND_OF = {"m": "movie", "s": "series", "l": "tv"}


def _ref(lines, pre, sid):
    """معرّفٌ في المكتبة ← (النوع، بصمة سيرفر المصدر، رقمه، (الموسم، الحلقة) أو None)، أو None."""
    sid = str(sid)
    if not sid.startswith(pre):
        return None
    p = sid[len(pre):].split(":")
    if len(p) == 2 and p[0] in _KIND_OF:
        num = _int(p[1], None)
        return (_KIND_OF[p[0]], line_hk(lines[0]["cfg"]), num, None) if num is not None else None
    if len(p) == 2 and p[0] in ("wm", "ws", "wl") and "." in p[1]:
        hk, num = p[1].split(".", 1)
        num = _int(num, None)
        return (_KIND_OF[p[0][1]], hk, num, None) if num is not None and re.fullmatch(r"[0-9a-f]{6}", hk) else None
    if len(p) == 4 and p[0] == "we" and "." in p[1]:
        hk, num = p[1].split(".", 1)
        num, se, ep = _int(num, None), _int(p[2], None), _int(p[3], None)
        return ("series", hk, num, (se, ep)) if None not in (num, se, ep) and re.fullmatch(r"[0-9a-f]{6}", hk) else None
    return None


def _work(lines, kind, pre, sid):
    """معرّف ← (العمل، (الموسم، الحلقة) أو None) أو (None، None)."""
    r = _ref(lines, pre, sid)
    if not r or r[0] != kind:
        return None, None
    return library(lines, kind).find(r[1], r[2]), r[3]


def _versions_ar(versions):
    return list(dict.fromkeys(LIB.VERSION_AR[v] for v in versions if v in LIB.VERSION_AR))


def _sources_line(w):
    """«سمارت · كاسبر (مترجم) · فالكون ×2» — مؤشّر المصادر في وصف البطاقة."""
    out = []
    for lb in w.labels:
        ss = [x for x in w.sources if x.label == lb]
        vers = _versions_ar([v for x in ss for v in x.key.versions])
        out.append(lb + (f" ({'، '.join(vers)})" if vers else "") + (f" ×{len(ss)}" if len(ss) > 1 else ""))
    return " · ".join(out)


def channel_poster(lib, w, poster_url, cat=None):
    """ملصق القناة المرسوم (‏stremio_posters): اسمها ورقمها في القائمة الموحدة وختم أعلى جوداتها وتصنيفها (من تصنيفات
    سمارت سوق، وإلا قسم لوحتها) — أو None."""
    if not poster_url or w.kind != "tv":
        return None
    best = max(w.sources, key=lambda s: LIB.QUALITY_RANK.get(s.key.quality, 1)).key.quality
    return poster_url(w.name, lib.number(w), best, cat or w.anchor.cat or "")


def _ucats(lines):
    """تصنيفات سمارت سوق لحساب Stremio هذا (يمرّرها الخادم مع خطوطه: ‏cats — تحرير حساب الأداة)، وإلا الافتراضية."""
    return lines[0]["cats"] if lines and isinstance(lines[0].get("cats"), list) else CATS.DEFAULTS


_cidx = OrderedDict()                # (النوع، المكتبة، التصنيفات) ← (الوقت، المكتبة، الفهرس)


def _cat_index(lines, lib, kind):
    """أعمال كل تصنيفٍ من تصنيفات سمارت سوق في المكتبة ← {"by": {المعرّف: [الأعمال بترتيب المكتبة]}، "first": {العمل: اسم
    أول تصنيفٍ له}}. العمل في تصنيفٍ إن كان قسمٌ من أقسام مصادره يطابق كلمات ربطه (والقناة باسمها أيضًا)، أو (للأفلام
    والمسلسلات) تصنيفه هو («أكشن» من حقل genre، وللأفلام ما عُرف من تفاصيلها)؛ وما لم يدخل شيئًا في «أخرى». محفوظٌ دقيقتين."""
    mine = CATS.of_kind(_ucats(lines), kind)
    key = (kind, id(lib), CATS.sig(mine))
    now = time.time()
    with _lock:
        hit = _cidx.get(key)
    if hit and hit[1] is lib and now - hit[0] < CAT_TTL:
        return hit[2]
    match = [(c, CATS.matcher(c)) for c in mine]
    by_name = {}
    for w in lib.works:
        for n in w.cats:
            if n not in by_name:
                by_name[n] = {c["id"] for c, m in match if m(n)}
    gkeys = {c["id"]: LIB.genre_keys(c.get("genres")) for c in mine if kind in GENRE_TYPES and c.get("genres")}
    known = {}                                           # أفلامٌ عُرف تصنيفها من تفاصيلها
    if kind == "movie":
        for cid in gkeys:
            ids = set()
            g = next(c["genres"] for c in mine if c["id"] == cid)
            for ln in lines:
                lhk = line_hk(ln["cfg"])
                ids.update(id(w) for w in (lib.find(lhk, i) for i in genre_ids(ln["cfg"], g)) if w)
            known[cid] = ids
    names = {c["id"]: c["name"] for c in mine}
    by = {c["id"]: [] for c in mine}
    by[CATS.OTHERS_ID] = []
    first = {}
    for w in lib.latest:
        got = set().union(*(by_name.get(n, ()) for n in w.cats)) if w.cats else set()
        if kind == "tv":                                 # والقناة باسمها أيضًا («beIN SPORTS 1» ← «رياضة» أيًّا كان قسمها)
            n = LIB.norm(w.name)
            got |= {c["id"] for c, m in match if c["id"] not in got and m(n)}
        for cid, ks in gkeys.items():
            if cid not in got and (w.tags & ks or id(w) in known.get(cid, ())):
                got.add(cid)
        if not got:
            by[CATS.OTHERS_ID].append(w)
            continue
        for c in mine:
            if c["id"] in got:
                by[c["id"]].append(w)
                first.setdefault(id(w), names[c["id"]])
    idx = {"by": by, "first": first}
    with _lock:
        _cidx[key] = (now, lib, idx)
        _cidx.move_to_end(key)
        while len(_cidx) > LIB_MAX * 3:
            _cidx.popitem(last=False)
    return idx


def _unified(lines, lib, kind, g):
    """أعمال تصنيفٍ باسمه («تركي» · «تركي (855)» · «أخرى») من تصنيفات سمارت سوق — أو None إن لم يكن منها."""
    norm_name = LIB.norm(_COUNT.sub("", g).strip())
    if not norm_name:
        return None
    if norm_name == LIB.norm(CATS.OTHERS):
        by = CATS.OTHERS_ID
    else:
        by = next((c["id"] for c in CATS.of_kind(_ucats(lines), kind) if LIB.norm(c["name"]) == norm_name), None)
    return _cat_index(lines, lib, kind)["by"].get(by) if by else None


def work_preview(pre, w, multi, poster=None):
    """بطاقة العمل: بمصدرٍ واحد كما كانت بطاقة عنصره، وبمصادر شتّى بأسمائها في وصفها (يظهر في «اكتشف» بجانب الملصق).
    ‏poster: ملصقٌ مرسوم يحلّ محلّ صورة السيرفر (القنوات)."""
    it = w.anchor.item
    if len(w.sources) == 1:
        m = _preview(pre, w.kind, it)
        m["id"] = work_id(pre, w)
    else:
        m = _clean({"id": work_id(pre, w), "type": w.kind, "name": w.name, "poster": w.poster,
                    "background": next((x.item.bg for x in w.sources if x.item.bg), None),
                    "posterShape": "square" if w.kind == "tv" else "poster", "releaseInfo": w.year,
                    "imdbRating": w.rating, "description": w.plot or None, "genres": _split(w.genre)})
    if multi and w.kind != "tv":
        line = "المصادر: " + _sources_line(w)
        m["description"] = f"{m['description']} — {line}" if m.get("description") else line
    if poster:
        m["poster"] = poster
    return m


def _lib_tagged(lines, lib, kind, g):
    """تصنيف الفيلم أو المسلسل في المكتبة («جريمة» = «Crime»): من قوائم الخطوط، ومعها أفلامٌ عُرف تصنيفها من تفاصيلها
    (‏note_genre · crawl_genres)."""
    seq = lib.tagged(g)
    if kind != "movie":
        return seq
    have, more = {id(w) for w in seq}, []
    for ln in lines:
        lhk = line_hk(ln["cfg"])
        for iid in genre_ids(ln["cfg"], g):
            w = lib.find(lhk, iid)
            if w and id(w) not in have:
                have.add(id(w))
                more.append(w)
    return sorted(seq + more, key=lambda w: -w.added) if more else seq


def lib_catalog(lines, kind, cid, extra, pre, poster_url=None):
    """صفحةٌ من كتالوج المكتبة الموحدة: بحثٌ في كل الخطوط معًا (العمل مرةً واحدة)، أو قسم، أو «مصدر: …»، أو تصنيف عمل،
    أو الكل — 100 عملٍ من ‏skip."""
    row = cid[len(CAT_PREFIX):] if kind in CATALOG and cid.startswith(CAT_PREFIX) else None
    if kind not in CATALOG or (cid != CATALOG[kind] and row is None):
        return None
    lib = library(lines, kind)
    skip = max(0, _int(extra.get("skip"), 0))
    if row is not None:                                  # صفّ تصنيفٍ في الرئيسية (وتصنيفٌ حُذف ← فارغ)
        seq = _cat_index(lines, lib, kind)["by"].get(row) or []
    elif extra.get("search"):
        seq = lib.search(extra["search"])
    elif extra.get("genre"):
        g = " ".join(extra["genre"].split())
        if g.startswith(SRC_TAG.strip()):
            seq = lib.from_source(_COUNT.sub("", g[len(SRC_TAG.strip()):]).strip())
        else:
            seq = _unified(lines, lib, kind, g)
            if seq is None:                              # قسم لوحةٍ (‏manifest أقدم)، أو تصنيف العمل («جريمة» في صفحته)
                seq = lib.in_category(g) or lib.in_category(_COUNT.sub("", g)) or _lib_tagged(lines, lib, kind, g)
    else:
        seq = lib.latest
    multi = len(lines) > 1
    page = seq[skip:skip + PAGE]
    first = _cat_index(lines, lib, kind)["first"] if kind == "tv" and poster_url else {}
    metas = [work_preview(pre, w, multi, channel_poster(lib, w, poster_url, first.get(id(w)))) for w in page]
    if kind == "tv":
        for m, w in zip(metas, page):
            if w.anchor.cat:
                m["description"] = w.anchor.cat
    return {"metas": metas}


def _src_links(man, w, extra=None):
    """المصادر روابطَ في صفحة العمل (فئة «المصادر»): كل بوابةٍ بنسختها، والضغط عليها ← كل ما في ذلك الخط."""
    if not man:
        return []
    url = f"stremio:///discover/{quote(man, safe='')}/{w.kind}/{CATALOG[w.kind]}?genre="
    out = []
    for lb in w.labels:
        ss = [x for x in w.sources if x.label == lb]
        bits = _versions_ar([v for x in ss for v in x.key.versions]) + [q for q in dict.fromkeys(x.key.quality for x in ss) if q]
        name = " · ".join([lb] + bits + ([extra[lb]] if extra and extra.get(lb) else []))
        out.append({"name": name, "category": "المصادر", "url": url + quote(SRC_TAG + lb, safe="")})
    return out


def _work_genres(m, w, man):
    """تصنيفات العمل من تفاصيله ومن مصادره كلها، بلغتين ← واحدة بالعربية («Crime» من بوابةٍ و«جريمة» من أخرى = «جريمة»)،
    وكلٌّ رابطٌ إلى كتالوجنا مصفًّى به."""
    g = LIB.genre_names(", ".join((m.get("genres") or []) + [w.genre]))
    if not g:
        return m
    m["genres"] = g
    links = [x for x in m.get("links") or [] if x.get("category") != "Genres"]
    if man:
        url = f"stremio:///discover/{quote(man, safe='')}/{w.kind}/{CATALOG[w.kind]}?genre="
        links += [{"name": x, "category": "Genres", "url": url + quote(x, safe="")} for x in g]
    if links:
        m["links"] = links
    return m


def _with_sources(m, w, man, multi, extra=None):
    if w.kind in GENRE_TYPES:
        _work_genres(m, w, man)
    if multi or len(w.sources) > 1:
        m["links"] = (m.get("links") or []) + _src_links(man, w, extra)
    return m


def _series_sources(lines, w):
    """حلقات كل مصدرٍ من مصادر المسلسل (تفاصيله تُقرأ معًا وتُحفظ ساعات) ← [(المصدر، [Ep]، التفاصيل أو None)] بترتيب
    المصادر. مصدرٌ لم تصل تفاصيله بعد LIB_WAIT ثانية (ما دام غيره وصل) بلا حلقاتٍ هذه المرة، ويكمل في الخلفية."""
    def one(src):
        cfg = lines[src.line]["cfg"]
        try:
            d = _details(cfg, "get_series_info", "series_id", src.item.id)
        except XtreamError:
            d = None
        info = d.get("info") if isinstance(d, dict) and isinstance(d.get("info"), dict) else {}
        name = " ".join(str(info.get("name") or src.item.name).split())
        return src, (_episodes(d, name, src.key.season) if d else []), d
    jobs = [_bg(one, src) for src in w.sources]
    _settle(jobs, lambda f: f.exception() is None and f.result()[2])
    out = []
    for src, f in zip(w.sources, jobs):
        if f.done() and f.exception() is not None and not isinstance(f.exception(), XtreamError):
            raise f.exception()
        out.append(f.result() if f.done() and f.exception() is None else (src, [], None))
    return out


def lib_meta(lines, kind, sid, man, pre, poster_url=None):
    """تفاصيل عملٍ في المكتبة: من أفضل مصادره، ومصادره كلها روابطَ في صفحته؛ والمسلسل بحلقات مصادره كلها (الحلقة الواحدة مرةً
    واحدة، ولكلٍّ مصادرها في التشغيل)."""
    w, _ = _work(lines, kind, pre, sid)
    if w is None:
        return meta(lines[0]["cfg"], kind, sid, man) if _parse_id(lines[0]["cfg"], sid) else None
    multi, top = len(lines) > 1, w.sources[0]
    cfg, wid = lines[top.line]["cfg"], work_id(pre, w)
    if kind == "movie":
        m = _movie_meta(cfg, pre, top.item.id, man)
        if not m:
            return None
        m.update({"id": wid, "behaviorHints": {"defaultVideoId": wid}})
        if len(w.sources) > 1:
            m["name"] = w.name
        return {"meta": _with_sources(m, w, man, multi)}
    if kind == "tv":
        L = _cached_lists(cfg, "tv") or lists(cfg, "tv")
        it = L.by_id.get(top.item.id) or top.item
        cat = L.cat_of(it)
        m = _clean({**_preview(pre, "tv", it), "id": wid, "name": w.name, "description": cat, "genres": [cat] if cat else [],
                    "links": _links(man, "tv", it.name, None, [cat] if cat else []), "behaviorHints": {"defaultVideoId": wid}})
        tlib = library(lines, "tv")
        pst = channel_poster(tlib, w, poster_url, _cat_index(lines, tlib, "tv")["first"].get(id(w)) if poster_url else None)
        if pst:
            m["poster"] = pst
        return {"meta": _with_sources(m, w, man, multi)}
    per = _series_sources(lines, w)
    if len(w.sources) == 1 and w.anchor.line == 0:              # مصدرٌ واحد في خط صاحب الحساب: كما كان (معرّفات حلقاته)
        m = _series_meta(cfg, pre, top.item.id, man)
        return {"meta": _with_sources(m, w, man, multi)} if m else None
    best = next((src for src, _, d in per if d), per[0][0])      # أول مصدرٍ قُرئت تفاصيله: منه بيانات الصفحة
    m = _series_meta(lines[best.line]["cfg"], pre, best.item.id, man)
    if not m:
        return None
    a = w.anchor
    videos, seen, have = [], set(), OrderedDict()
    for src, eps, _ in per:
        have.setdefault(src.label, set()).update((e.season, e.episode) for e in eps)   # البوابة بمداخلها كلها
        for e in eps:
            if (e.season, e.episode) in seen:
                continue
            seen.add((e.season, e.episode))
            videos.append(_clean({"id": f"{pre}we:{a.hk}.{a.item.id}:{e.season}:{e.episode}", **e.video}))
    videos.sort(key=lambda v: (v["season"], v["episode"]))
    counts = {}
    for lb, got in have.items():
        seasons = sorted({se for se, _ in got})
        if seasons:
            sp = f"S{seasons[0]:02d}" + (f"–S{seasons[-1]:02d}" if len(seasons) > 1 else "")
            counts[lb] = f"{sp} · {_eps_count(len(got))}"
    m.update({"id": wid, "name": w.name if len(w.sources) > 1 else m.get("name"), "videos": videos})
    return {"meta": _with_sources(m, w, man, multi, counts)}


def _eps_count(n):
    return "حلقة واحدة" if n == 1 else "حلقتان" if n == 2 else f"{n} حلقات" if 3 <= n % 100 <= 10 else f"{_fmt(n)} حلقة"


def _height(info):
    """ارتفاع الصورة من تفاصيل الملف كما يقرؤها السيرفر (‏info.video.height، وإلا العرض) — الجودة الحقيقية لا ما في الاسم."""
    v = info.get("video") if isinstance(info, dict) and isinstance(info.get("video"), dict) else {}
    h, w = _int(v.get("height"), 0), _int(v.get("width"), 0)
    return h or (w * 9 // 16 if w else 0)


def _quality(src, height=0):
    """جودة المصدر: من الملف نفسه إن عُرف ارتفاعه (‏2160 ← 4K · 1080 ← FHD · 720 ← HD · أقلّ ← SD)، وإلا من اسمه وقسمه."""
    if height >= 1800:
        return "4K"
    if height >= 1000:
        return "FHD"
    if height >= 700:
        return "HD"
    if height > 0:
        return "SD"
    return src.key.quality


def _lang_rank(versions):
    """الترجمة العربية أولًا: مترجمٌ (أو سوفت أو متعدد الترجمات) ← 0، وما لا يُعرف ← 1، والمدبلج ← 2."""
    v = set(versions or ())
    return 0 if v & {"subbed", "subbed_soft", "multi"} else 2 if "dubbed" in v else 1


def _status_rank(cfg):
    """0 الاشتراك فعّال · 1 لا يُعرف (السيرفر لا يردّ) · 2 يرفضه السيرفر — المصادر تُرتَّب به."""
    try:
        ui, _ = account(cfg)
        return 0 if str(ui.get("status", "")).lower() in ("active", "") else 2
    except AuthError:
        return 2
    except XtreamError:
        return 1


def candidates(lines, kind, sid, pre):
    """مصادر تشغيل عنصرٍ في المكتبة بترتيب الأفضل ← [{url, name, title, binge, rank, line}]، أو None لمعرّفٍ ليس من المكتبة
    (حلقةٌ بصيغتها القديمة: تشغيلها كما كان). الترتيب — وبه يختار «تلقائي»: الاشتراك فعّال ← الترجمة العربية (مترجم ·
    سوفت · متعدد الترجمات، ثم ما لا يُعرف، ثم المدبلج) ← الجودة الأعلى (من الملف نفسه إن عرفها السيرفر، وإلا من اسمه) ←
    ترتيب الخطوط."""
    w, ep = _work(lines, kind, pre, sid)
    if w is None:
        return None
    jobs = [_bg(_status_rank, ln["cfg"]) for ln in lines]           # حال كل خط — ولا يُنتظر خطٌّ لا يردّ (1: لا يُعرف)
    wait(jobs, timeout=LIB_WAIT)
    ranks = {li: f.result() if f.done() and f.exception() is None else 1 for li, f in enumerate(jobs)}
    files = {}                                         # المصدر ← (الرابط، الامتداد، الارتفاع، الحلقة)
    if kind == "series":
        for src, eps, _ in _series_sources(lines, w):
            e = next((x for x in eps if (x.season, x.episode) == ep), None)
            if e:
                files[src] = (e.eid, e.ext, e.height, e)
    elif kind == "movie":
        def one(src):
            try:
                d = _details(lines[src.line]["cfg"], "get_vod_info", "vod_id", src.item.id) or {}
            except XtreamError:
                d = {}
            md = d.get("movie_data") if isinstance(d.get("movie_data"), dict) else {}
            return src, (src.item.id, src.item.ext or _ext(md.get("container_extension")) or "mp4", _height(d.get("info")), None)
        jobs = [_bg(one, src) for src in w.sources]                    # تفاصيل الملف (الجودة): لا يُنتظر مصدرٌ لا يردّ
        wait(jobs, timeout=LIB_WAIT)
        files = dict(f.result() if f.done() and f.exception() is None else (src, (src.item.id, src.item.ext or "mp4", 0, None))
                     for src, f in zip(w.sources, jobs))
    else:
        files = {src: (src.item.id, "", 0, None) for src in w.sources}
    qual = {src: _quality(src, f[2]) for src, f in files.items()}
    order = sorted(files, key=lambda x: (ranks.get(x.line, 1), _lang_rank(x.key.versions),
                                         -LIB.QUALITY_RANK.get(qual[x], 1), x.line, x.item.id))
    out = []
    for src in order:
        cfg = lines[src.line]["cfg"]
        u, pw = quote(cfg.user, safe=""), quote(cfg.pw, safe="")
        label, rank = src.label or BRAND, ranks.get(src.line, 1)
        num, ext, height, e = files[src]
        bits = [x for x in [qual[src] + (f" ({height}p)" if height else "")] + _versions_ar(src.key.versions) if x]
        warn = "⚠️ الاشتراك منتهٍ — " if rank == 2 else ""
        if kind == "movie":
            out.append({"url": f"{cfg.host}/movie/{u}/{pw}/{num}.{ext}", "src": f"{src.hk}.m{num}.{ext}", "name": label, "rank": rank, "line": src.line,
                        "title": warn + f"{src.item.name}\n" + " · ".join(bits + [ext.upper()]), "binge": None})
        elif kind == "series":
            out.append({"url": f"{cfg.host}/series/{u}/{pw}/{num}.{ext}", "src": f"{src.hk}.e{num}.{ext}", "name": label, "rank": rank, "line": src.line,
                        "title": warn + f"{src.item.name}\n" + " · ".join(bits + [f"S{e.season:02d}E{e.episode:02d}", ext.upper()]),
                        "binge": f"ssouq-{src.hk}-{'-'.join(src.key.versions) or 'x'}"})
        else:
            for f in _formats(cfg):
                out.append({"url": f"{cfg.host}/live/{u}/{pw}/{num}.{f}", "src": f"{src.hk}.l{num}.{f}", "name": label, "rank": rank, "line": src.line,
                            "title": warn + f"{src.item.name}\n" + " · ".join(bits + ["بث مباشر", {"m3u8": "HLS", "ts": "TS"}[f]]),
                            "binge": None})
    return out


def _stream(c, play_url):
    """مصدرٌ في قائمة التشغيل — رابطه على خادمنا (‏/play/…/<المصدر>) يحوّل إلى اللوحة: لا يصل العميلَ في ردود الإضافة يوزرُ Xtream
    ولا باسورده."""
    hints = {"notWebReady": True}
    if c["binge"]:
        hints["bingeGroup"] = c["binge"]
    return {"url": f"{play_url}/{c['src']}", "name": c["name"], "title": c["title"], "behaviorHints": hints}


def lib_streams(lines, kind, sid, pre, play_url):
    """قائمة التشغيل: «تلقائي» أولها حين تتعدّد المصادر (يجرّبها بالترتيب — كل الخطوط — وينتقل للتالي إن تعطّل)، ثم كل
    مصدرٍ ببوابته واسمه الأصلي وجودته ونسخته. خطٌّ مرتبطٌ تعرض إضافته مصادره (‏own، انظر line_streams) لا تتكرّر هنا: يظهر
    باسمه في أعلى قائمة Stremio («سمارت سوق · فالكون»)، فلكل بوابةٍ زرّها."""
    cands = candidates(lines, kind, sid, pre)
    if cands is None:
        return streams(lines[0]["cfg"], kind, sid, play_url)
    out = []
    if len(cands) > 1:
        out.append({"url": play_url, "name": BRAND, "title": "⚡ تلقائي — المترجم بالعربية بأعلى جودة\nإن تعطّل مصدرٌ انتقل للتالي",
                    "behaviorHints": {"notWebReady": True, "bingeGroup": "ssouq-auto"}})
    out += [_stream(c, play_url) for c in cands if not lines[c["line"]].get("own")]
    return {"streams": out}


def line_streams(group, me, kind, sid, play_url):
    """إضافة خطٍّ مرتبط: مصادره هو من عمل المكتبة الموحدة (‏group: خطوط الحساب، صاحبه أولًا · me: رقم الخط فيها) — Stremio
    يجمع المصادر في قائمة العمل بإضافاتها، فلكل بوابةٍ زرٌّ باسمها فوق القائمة، و«تلقائي» عند صاحب الحساب."""
    cands = candidates(group, kind, sid, prefix(group[0]["cfg"])) or []
    return {"streams": [_stream(c, play_url) for c in cands if c["line"] == me]}


_SRC = re.compile(r"([0-9a-f]{6})\.([mel])(\d{1,12})\.([a-z0-9]{2,5})")
_SRC_PATH = {"m": "movie", "e": "series", "l": "live"}


def src_url(lines, src):
    """مصدرٌ من قائمة التشغيل («‏<بصمة الخط>.m<رقم>.<امتداد>») ← رابطه في اللوحة، من خطوط هذا الحساب وحدها — أو None."""
    m = _SRC.fullmatch(str(src or ""))
    ln = next((ln for ln in lines or () if m and line_hk(ln["cfg"]) == m.group(1)), None)
    if not ln:
        return None
    cfg, code, num, ext = ln["cfg"], m.group(2), m.group(3), m.group(4)
    if code == "l" and ext not in ("m3u8", "ts"):
        return None
    return f"{cfg.host}/{_SRC_PATH[code]}/{quote(cfg.user, safe='')}/{quote(cfg.pw, safe='')}/{num}.{ext}"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_probe_opener = build_opener(_NoRedirect)


def probe(url):
    """هل يردّ المصدر؟ طلبٌ واحد قصير (أول بايتين) بلا اتّباع التحويل: 200/206 أو تحويلٌ إلى خادم البث ← يعمل؛ ورفضٌ أو
    غيابٌ (4xx/5xx) أو مهلةٌ أو انقطاع ← معطّل. النتيجة تُحفظ دقيقة."""
    now = time.time()
    with _lock:
        hit = _probes.get(url)
    if hit and now - hit[0] < PROBE_TTL:
        return hit[1]
    try:
        r = _probe_opener.open(Request(url, headers={"User-Agent": UA, "Range": "bytes=0-1"}), timeout=PROBE_TIMEOUT)
        ok = r.getcode() < 400
        r.close()
    except HTTPError as e:
        ok = e.code in (301, 302, 303, 307, 308)
    except (URLError, OSError, ValueError, http.client.HTTPException):
        ok = False
    with _lock:
        _probes[url] = (now, ok)
        if len(_probes) > 5000:
            for k in [k for k, (t, _) in _probes.items() if now - t > PROBE_TTL]:
                _probes.pop(k, None)
    return ok


def play(lines, kind, sid, pre):
    """«تلقائي»: أول مصدرٍ يعمل (الاشتراك فعّال أولًا) ← رابطه؛ ومعطّلٌ ← التالي. كلها معطّلة ← الأول (يُظهر المشغّل خطأه).
    ← الرابط أو None."""
    cands = candidates(lines, kind, sid, pre)
    if not cands:
        return None
    ok_first = [c for c in cands if c["rank"] < 2] or cands
    for c in ok_first[:PROBE_MAX]:
        if probe(c["url"]):
            return c["url"]
    return ok_first[0]["url"]


# ================= حالة الاشتراك للصفحة، والروابط =================
def links(base, token):
    """روابط التثبيت لرمزٍ: الصفحة، والـmanifest، وتطبيق Stremio، وStremio Web."""
    man = f"{base}{PATH}/{token}/manifest.json"
    return {"page": f"{base}{PATH}/{token}", "manifest": man,
            "install": "stremio://" + man.split("://", 1)[1],
            "web": "https://web.stremio.com/#/addons?addon=" + quote(man, safe="")}


def status(cfg, base, token, label=""):
    """ما تعرضه صفحة التثبيت: الحالة والانتهاء وعدد المحتوى (ويُحمَّل به المحتوى فيصل Stremio جاهزًا)."""
    out = {"ok": True, "name": BRAND + (f" · {label}" if label else ""), "label": label, **links(base, token)}
    try:
        ui, _ = account(cfg, fresh=True)
    except AuthError as e:
        return {**out, "ok": False, "auth": False, "error": str(e)}
    except XtreamError as e:
        return {**out, "ok": False, "error": str(e)}
    exp = _int(ui.get("exp_date"), 0)
    out.update({"auth": True, "active": str(ui.get("status", "")).lower() == "active",
                "status": str(ui.get("status") or ""), "max_connections": _int(ui.get("max_connections"), 0) or None,
                "exp": datetime.datetime.fromtimestamp(exp, datetime.timezone.utc).strftime("%Y-%m-%d") if exp > 0 else None})
    counts = {}
    for kind in TYPES:
        try:
            counts[kind] = len(lists(cfg, kind).items)
        except XtreamError:
            counts[kind] = None
    out["counts"] = counts
    return out


_rate = {}


def rate_ok(ip, limit=RATE, now=None):
    """حدّ الروابط بالساعة لكل عنوان (بصمته لا هو) — الصفحة العامة تسأل السيرفر بكل طلب."""
    if not ip:
        return True
    hour = int((now or time.time()) // 3600)
    k = hashlib.sha256(str(ip).encode()).hexdigest()[:16] + ":" + str(hour)
    with _lock:
        for old in [x for x in _rate if not x.endswith(":" + str(hour))]:
            _rate.pop(old, None)
        _rate[k] = _rate.get(k, 0) + 1
        return _rate[k] <= limit


def link(data_dir, base, req, allowed):
    """طلب الصفحة العامة ‏{line} أو ‏{host, user, pass} ← (رمز الحالة، الرد). السيرفر يجب أن يكون من سيرفراتنا
    (‏allowed(host)) — فلا تصير الصفحة بابًا لسؤال أي عنوانٍ على الإنترنت — والاشتراك فعّالًا عليه."""
    parsed = parse_line(req.get("line")) if req.get("line") else None
    host, user, pw = parsed or (req.get("host"), req.get("user"), req.get("pass"))
    if not norm_host(host) or not str(user or "").strip() or not str(pw or "").strip():
        return 400, {"ok": False, "error": "اكتب الهوست واليوزر والباسورد، أو الصق رسالة اشتراكك كما وصلتك"}
    if not allowed(host):
        return 400, {"ok": False, "error": "هذا السيرفر ليس من سيرفراتنا — تأكّد من الهوست في رسالة اشتراكك"}
    try:
        token = make_token(data_dir, host, user, pw)
    except ValueError as e:
        return 400, {"ok": False, "error": str(e)}
    cfg = read_token(data_dir, token)
    try:
        account(cfg, fresh=True)
    except AuthError:
        return 400, {"ok": False, "error": "السيرفر رفض البيانات: تأكّد من اليوزر والباسورد، أو أن اشتراكك فعّال"}
    except XtreamError as e:
        return 502, {"ok": False, "error": f"{e} — حاول بعد قليل"}
    return 200, {"ok": True, "token": token, **links(base, token)}


# ================= المسارات =================
_JSON = "application/json; charset=utf-8"
_CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*"}
_PAGE_HDR = {"X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer"}
_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stremio.html")
# زرّ «Configure» في Stremio يفتح موقع المتجر — لا صفحة التثبيت (فيها نسخ الرابط والتثبيت في حسابٍ آخر)
CONFIGURE_URL = (os.environ.get("STREMIO_CONFIGURE_URL") or os.environ.get("SALLA_STORE_URL") or "https://ssouq.com").rstrip("/") + "/"


def _json(code, obj, age=0):
    cache = f"public, max-age={age}" if age and code == 200 else "no-store"
    return code, json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode(), _JSON, {**_CORS, "Cache-Control": cache}


def page():
    with open(_HTML, "rb") as f:
        return 200, f.read(), "text/html; charset=utf-8", {**_PAGE_HDR, "Cache-Control": "no-store"}


LINES_TTL = 15                       # خطوط حسابٍ تُقرأ مرةً كل ربع دقيقة (لا مع كل صفحةٍ من الكتالوج)
_lines_cache = OrderedDict()


def _takes_key(fn):
    """‏lines_for(cfg، القفل)؟ — دالةٌ تميّز إضافة حساب Nuvio من إضافة Stremio للخط نفسه بقفل رمزها."""
    try:
        return len(inspect.signature(fn).parameters) >= 2
    except (TypeError, ValueError):
        return False


def _lines_of(cfg0, cfg, label, lines_for, key=None, fallback=..., lock=None):
    """خطوط الإضافة (انظر handle) — محفوظةٌ ثوانيَ."""
    if not lines_for:
        return [{"cfg": cfg, "label": label}]
    key = key or (cfg0, lock)
    now = time.time()
    with _lock:
        hit = _lines_cache.get(key)
    if hit and now - hit[0] < LINES_TTL:
        return hit[1]
    try:
        val = lines_for(cfg0, lock) if lock and _takes_key(lines_for) else lines_for(cfg0)
    except Exception:
        val = hit[1] if hit else [{"cfg": cfg, "label": label}] if fallback is ... else fallback
    with _lock:
        _lines_cache[key] = (now, val)
        _lines_cache.move_to_end(key)
        while len(_lines_cache) > 2000:
            _lines_cache.popitem(last=False)
    return val


def _poster_maker(data_dir, base):
    """(اسم، رقم، جودة، قسم) ← رابط ملصق القناة على الموقع: معطياته مختومةٌ في الرابط (حتمي: القناة نفسها = الرابط نفسه،
    فيحفظه Stremio)، فلا يُرسم بالرابط نصٌّ لم يصدر منّا."""
    def make(name, num, quality, cat):
        tok = crypto_store.seal_token(f"{int(num or 0)}\n{quality or ''}\n{cat or ''}\n{name}", data_dir, POSTER_LABEL)
        return f"{base}{PATH}/p/{tok}.png"
    return make


def poster_response(data_dir, tok):
    """‏/stremio/p/<رمز>.png ← صورة الملصق (PNG، أو SVG بلا Pillow)، تُحفظ عند Stremio شهرًا (معطياتها في رابطها)."""
    raw = crypto_store.open_token(tok, data_dir, POSTER_LABEL) if 20 <= len(tok) <= 900 else None
    bits = raw.split("\n", 3) if raw else []
    if len(bits) != 4 or not bits[3].strip():
        return 404, b"", "text/plain; charset=utf-8", {**_CORS, "Cache-Control": "no-store"}
    body, ctype = POSTERS.render(bits[3], _int(bits[0], 0), bits[1], bits[2])
    return 200, body, ctype, {**_CORS, "Cache-Control": "public, max-age=2592000, immutable"}


def forget_lines():
    """ينسى خطوط الحسابات المحفوظة ثوانيَ — بعد ربط خطٍّ أو فصله تظهر المكتبة الجديدة من أول طلب."""
    with _lock:
        _lines_cache.clear()


def handle(data_dir, path, base, label_for=None, allowed=None, route=None, lines_for=None, group_for=None):
    """طلب GET تحت ‏/stremio ← (الرمز، الجسم، النوع، الترويسات)، أو None لمسارٍ ليس لها.
    ‏label_for(cfg) اسم السيرفر كما في الدليل (سمارت · كاسبر · فالكون) للاسم في Stremio.
    ‏allowed(cfg، القفل) هل الرمز ساري — رمزٌ أُوقف (قفل حسابه تغيّر) يُردّ كرمزٍ غير صالح.
    ‏route(cfg) الاشتراك على هوسته الحالي (‏routed) إن غيّر السيرفر عنوانه، أو كما هو.
    ‏lines_for(cfg) خطوط حساب Stremio لهذه الإضافة (صاحب الحساب أولًا): مكتبتها الموحدة و«الحسابات» (انظر
    accounts_catalog · library)؛ أو None لخطٍّ مرتبطٍ بحساب (بلا كتالوجات: محتواه في مكتبة صاحب الحساب). بلاه: الخط وحده.
    ‏group_for(cfg) لخطٍّ مرتبط: خطوط حسابه (صاحبه أولًا) — فتعرض إضافته مصادره في أعمال المكتبة (‏line_streams)."""
    if path != PATH and not path.startswith(PATH + "/"):
        return None
    parts = [unquote(p) for p in path[len(PATH):].split("/") if p != ""]
    if parts and len(parts) <= 2 and parts[-1] == "configure":   # زرّ «Configure» في Stremio ← موقع المتجر
        return 302, b"", "text/plain; charset=utf-8", {**_PAGE_HDR, "Location": CONFIGURE_URL, "Cache-Control": "no-store"}
    if len(parts) == 2 and parts[0] == "p" and parts[1].endswith(".png"):   # ملصق قناةٍ مرسوم (رابطه مختومٌ منّا)
        return poster_response(data_dir, parts[1][:-len(".png")])
    if not parts or len(parts) == 1:
        return page()                                    # الصفحة العامة، وصفحة التثبيت برمزها
    cfg, key = read_token_key(data_dir, parts[0])
    if not cfg:
        return _json(404, {"ok": False, "error": "رابطٌ غير صالح — اطلب رابطًا جديدًا"})
    genre_dir(data_dir)
    disk_dir(data_dir)
    if allowed and not allowed(cfg, key):
        return _json(404, {"ok": False, "error": "أُوقف هذا الرابط — الإضافة مقفلةٌ على حسابها"})
    rest = parts[1:]
    # «تلقائي»: /play/<النوع>/<المعرّف> ← تحويلٌ إلى مصدرٍ يعمل؛ ومصدرٌ بعينه: /play/<النوع>/<المعرّف>/<المصدر> ← تحويلٌ إليه
    is_play = rest[0] == "play" and len(rest) in (3, 4)
    if not is_play:
        if not rest[-1].endswith(".json"):
            return _json(404, {"error": "not found"})
        rest[-1] = rest[-1][:-len(".json")]
    acc = len(rest) > 1 and rest[1] == ACCOUNTS
    til = len(rest) > 1 and rest[1] == TILES
    need_lines = rest[0] in ("manifest", "catalog", "meta", "stream", "play")
    label = ""
    if (rest[0] in ("manifest", "status") or acc or (need_lines and not lines_for)) and label_for:
        try:
            label = label_for(cfg) or ""
        except Exception:
            label = ""
    cfg0 = cfg
    if route:
        try:
            cfg = route(cfg) or cfg
        except Exception:
            pass
    # خطوط الحساب: صاحبه (أو رابطٌ وحده) ← مكتبةٌ موحدة و«الحسابات»؛ والخط المرتبط ← None (محتواه في مكتبة صاحبه)
    lines = _lines_of(cfg0, cfg, label, lines_for, lock=key) if need_lines else None
    pre = prefix(cfg)
    try:
        if rest == ["manifest"]:
            return _json(200, manifest(cfg, base, label, accounts=lines is not None, lines=lines, catalogs=lines is not None), 3600)
        if rest == ["status"]:
            return _json(200, status(cfg, base, parts[0], label))
        if acc:                                          # «الحسابات»: حال خطوط الحساب، وتجديدها
            if lines is None:
                res = None
            elif rest[0] == "catalog" and len(rest) == 3 and rest[2] == ACCOUNTS_ID:
                return _json(200, accounts_catalog(lines, pre, base), ACCOUNTS_AGE)
            elif rest[0] == "meta" and len(rest) == 3:
                res = accounts_meta(lines, pre, base, rest[2])
            elif rest[0] == "stream" and len(rest) == 3:
                res = accounts_streams(lines, pre, rest[2])
            else:
                res = None
            if res:
                return _json(200, res, ACCOUNTS_AGE)
            return _json(404, {"metas": []} if rest[0] == "catalog" else {"meta": None} if rest[0] == "meta" else {"streams": []})
        if til:                                          # صفّ «التصنيفات» المُزال: نسخةٌ قديمة تطلبه ← فارغٌ فيختفي
            if rest[0] == "catalog":
                return _json(200, {"metas": []}, 3600)
            return _json(404, {"meta": None} if rest[0] == "meta" else {"streams": []})
        if is_play:
            if len(rest) == 4:                           # مصدرٌ بعينه: من خطوط الحساب (وللخط المرتبط خطوط حسابه)
                pool = lines if lines is not None else \
                    (_lines_of(cfg0, cfg, label, group_for, ("group", cfg0), None) if group_for else None) or [{"cfg": cfg}]
                url = src_url(pool, rest[3])
            else:
                url = play(lines, rest[1], rest[2], pre) if lines is not None else None
            if not url:
                return _json(404, {"error": "not found"})
            return 302, b"", "text/plain; charset=utf-8", {**_CORS, **_PAGE_HDR, "Location": url, "Cache-Control": "no-store"}
        if rest[0] == "catalog" and len(rest) in (3, 4):
            if lines is None:                            # الخط المرتبط: صفوفه القديمة تختفي (محتواه في المكتبة الموحدة)
                return _json(200, {"metas": []}, 900) if rest[1] in CATALOG else _json(404, {"metas": []})
            extra = parse_extra(path.rsplit("/", 1)[-1][:-5]) if len(rest) == 4 else {}
            res = lib_catalog(lines, rest[1], rest[2], extra, pre, _poster_maker(data_dir, base))
            return _json(200, res, 900) if res is not None else _json(404, {"metas": []})
        if rest[0] == "meta" and len(rest) == 3:
            man = links(base, parts[0])["manifest"]
            res = meta(cfg, rest[1], rest[2], man) if lines is None else \
                lib_meta(lines, rest[1], rest[2], man, pre, _poster_maker(data_dir, base))
            return _json(200, res, 3600) if res else _json(404, {"meta": None})
        if rest[0] == "stream" and len(rest) == 3:
            play_url = f"{base}{PATH}/{parts[0]}/play/{quote(rest[1], safe='')}/{quote(rest[2], safe='')}"
            group = _lines_of(cfg0, cfg, label, group_for, ("group", cfg0), None) if lines is None and group_for else None
            me = next((i for i, ln in enumerate(group or ())
                       if host_key(ln["cfg"].origin or ln["cfg"].host) == host_key(cfg.origin or cfg.host) and ln["cfg"].user == cfg.user), None)
            if me is not None and rest[2].startswith(prefix(group[0]["cfg"])):
                res = line_streams(group, me, rest[1], rest[2], play_url)     # مصادر الخط في عملٍ من المكتبة الموحدة
            elif lines is None:
                res = streams(cfg, rest[1], rest[2], play_url) if rest[2].startswith(pre) else {"streams": []}
            else:
                res = lib_streams(lines, rest[1], rest[2], pre, play_url)
            return _json(200, res, 600) if res else _json(404, {"streams": []})
    except AuthError as e:
        return _json(403, {"error": str(e)})
    except XtreamError as e:
        return _json(502, {"error": str(e)})
    return _json(404, {"error": "not found"})

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
إضافة Stremio لاشتراكات Xtream — كل المحتوى لا أوّله: الأفلام كلها، والمسلسلات بمواسمها وحلقاتها، والقنوات.

لماذا إضافةٌ خاصة: الإضافات العامة (Xtremio وأخواتها) تعرض صفحةً أو صفحتين من كل قسم ثم تتوقّف، أو أقسامًا دون
أخرى. Stremio يطلب الكتالوج صفحةً بعد صفحة (‏skip = ما وصله حتى الآن)، ويحكم بانتهائه متى جاءته صفحةٌ أقلّ من
100 عنصر (‏CATALOG_PAGE_SIZE في stremio-core) — فكل صفحةٍ هنا 100 تمامًا إلا الأخيرة، والقائمة كاملةً من
السيرفر بطلبٍ واحد لكل نوع (‏get_vod_streams · get_series · get_live_streams)، لا قسمًا قسمًا.

  الكتالوجات     ثلاثة: أفلام · مسلسلات · قنوات. بلا تصنيف = الكل (الأحدث إضافةً أولًا)، وأقسام الأفلام والمسلسلات
                 تصنيفاتٌ (genre) في صفحة «اكتشف»، والقنوات كلها تصنيفٌ واحد؛ والبحث بالاسم في الثلاثة.
  التفاصيل      الفيلم من get_vod_info، والمسلسل بمواسمه وحلقاته من get_series_info، والقناة من القائمة.
  التشغيل       روابط السيرفر نفسه: ‏/movie/ · ‏/series/ · ‏/live/ (‏HLS ثم TS حسب ما يسمح به الاشتراك).

الرابط: ‏/stremio/<رمز>/manifest.json — الرمز مختومٌ بمفتاح الخادم (‏crypto_store.seal_token): فيه الهوست واليوزر
والباسورد مشفَّرةً، فلا تُقرأ من الرابط ولا يُصنع رابطٌ لسيرفرٍ آخر، والاشتراك نفسه يعطي الرمز نفسه دائمًا.
والكبار: تُسقط أقسامهم كلها (بعلامة السيرفر أو باسم القسم) وما علّمه السيرفر للكبار — لا بالعنوان، فلا يسقط
فيلم «xXx» ولا مسلسل «The Penthouse».

بلا مكتبات خارجية. ‏handle() يردّ على المسارات، وxm_lines يمرّر الطلب إليه ويضيف قائمة الهوستات المسموحة.
"""
import datetime
import hashlib
import http.client
import json
import os
import re
import threading
import time
from collections import OrderedDict, namedtuple
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, parse_qsl, quote, unquote, urlencode, urlsplit
from urllib.request import Request, urlopen

import content as C
import crypto_store

PATH = "/stremio"
LABEL = "stremio"                    # وسم الرمز: رمزٌ صدر لغير الإضافة لا يُقبل فيها
BRAND = "سمارت سوق"
VERSION = "1.1.0"                    # يرتفع مع كل تغييرٍ في الـmanifest فيحدّثه Stremio
PAGE = 100                           # صفحة الكتالوج كما يعدّها Stremio — أقلّ منها = آخر القائمة
TTL = int(os.environ.get("STREMIO_TTL", "1800"))          # عمر قوائم السيرفر في الذاكرة (ثوانٍ)
RETRY = 60                           # فشل التحديث وفي الذاكرة نسخةٌ: تُعرض، ويُعاد بعد دقيقة
ACCOUNT_TTL = 300                    # حالة الاشتراك (‏user_info)
INFO_TTL = 6 * 3600                  # تفاصيل فيلمٍ أو مسلسل
INFO_MAX = 3000
LISTS_MAX = int(os.environ.get("STREMIO_CACHE", "12"))    # قوائم (اشتراك × نوع) في الذاكرة معًا
API_TIMEOUT = 60
MAX_BYTES = 256 << 20
UA = C.UA                            # لوحات Xtream تقبل المشغّلات وقد تردّ غيرها
RATE = 20                            # روابط تُصنع بالساعة لكل عنوان من الصفحة العامة

TYPES = ("movie", "series", "tv")
_ACTION = {"movie": ("get_vod_categories", "get_vod_streams", "stream_id"),
           "series": ("get_series_categories", "get_series", "series_id"),
           "tv": ("get_live_categories", "get_live_streams", "stream_id")}
CATALOG = {"movie": "sq_movies", "series": "sq_series", "tv": "sq_live"}
# أقسام السيرفر تصنيفاتٌ للأفلام والمسلسلات؛ والقنوات تصنيفٌ واحد: كلها في كتالوجها بترتيب السيرفر وبحثٍ بالاسم
GENRE_TYPES = ("movie", "series")
_TITLE = {"movie": "أفلام", "series": "مسلسلات", "tv": "قنوات"}
_CODE = {"movie": "m", "series": "s", "tv": "l"}   # بادئة المعرّف بعد بادئة السيرفر؛ و‏e للحلقة

Cfg = namedtuple("Cfg", "host user pw")
Item = namedtuple("Item", "id name poster cat added rating ext plot year genre")


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


def make_token(data_dir, host, user, pw):
    """(الهوست، اليوزر، الباسورد) ← رمز الرابط. ‏ValueError لبياناتٍ لا تصلح."""
    host, user, pw = norm_host(host), str(user or "").strip(), str(pw or "").strip()
    if not host or not user or not pw or any(len(x) > 128 or re.search(r"\s", x) for x in (user, pw)):
        raise ValueError("بيانات الاشتراك غير صالحة")
    h = host[len("http://"):] if host.startswith("http://") else host    # ‏http الافتراضي يُختصر من الرمز
    return crypto_store.seal_token("\n".join((h, user, pw)), data_dir, LABEL)


def read_token(data_dir, token):
    """الرمز ← ‏Cfg، أو None لرمزٍ معبوثٍ به أو من مفتاحٍ آخر."""
    token = str(token or "")
    if not 20 <= len(token) <= 400 or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
        return None
    parts = (crypto_store.open_token(token, data_dir, LABEL) or "").split("\n")
    if len(parts) != 3:
        return None
    host = norm_host(parts[0])
    return Cfg(host, parts[1], parts[2]) if host and parts[1] and parts[2] else None


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
    return "sq" + hashlib.sha256(host_key(cfg.host).encode()).hexdigest()[:6] + ":"


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
        for x in raw:
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
                                  _year(name, x.get("releaseDate") or x.get("release_date")), str(x.get("genre") or "")))
            else:
                items.append(Item(iid, name, str(x.get("stream_icon") or ""), cat, _int(x.get("added")),
                                  _rating(x.get("rating")) if kind == "movie" else None,
                                  _ext(x.get("container_extension")), "", _year(name) if kind == "movie" else None, ""))
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
        self.genres = list(self.by_genre)
        # «الكل»: الأحدث إضافةً أولًا للأفلام والمسلسلات؛ والقنوات بترتيب السيرفر (أقسامها متجاورة)
        self.latest = items if kind == "tv" else sorted(items, key=lambda it: -it.added)
        self._keys = None
        self._klock = threading.Lock()

    def search(self, q):
        """كل الكلمات في الاسم (بلا تشكيل ولا همزات ولا حالة أحرف): المطابق ثم ما يبدأ بها ثم ما يحويها."""
        words = _norm(q).split()
        if not words:
            return []
        with self._klock:
            if self._keys is None:
                self._keys = [_norm(it.name) for it in self.items]
        phrase = " ".join(words)
        hits = []
        for it, k in zip(self.items, self._keys):
            if all(w in k for w in words):
                rank = 0 if k == phrase else 1 if k.startswith(phrase) else 2 if (" " + phrase) in (" " + k) else 3
                hits.append((rank, -it.added, it))
        hits.sort(key=lambda h: (h[0], h[1]))
        return [h[2] for h in hits]


_cats = OrderedDict()                # (cfg، النوع) ← (الوقت، الأقسام)
_lists = OrderedDict()               # (cfg، النوع) ← (الوقت، Lists)
_loading = {}                        # (cfg، النوع) ← قفل التحميل: طلباتٌ متزامنة تنتظر تحميلًا واحدًا


def _cached(store, key, ttl, load, cap):
    """قيمةٌ محفوظة ما دامت حديثة؛ وإلا تُحمَّل مرةً واحدة مهما تزامنت الطلبات. فشل التحميل وعندنا نسخة: تُعرض
    ويُعاد بعد دقيقة — فلا يختفي المحتوى لانقطاعٍ عابر في السيرفر."""
    with _lock:
        hit = store.get(key)
        if hit and time.time() - hit[0] < ttl:
            store.move_to_end(key)
            return hit[1]
        lk = _loading.setdefault((id(store), key), threading.Lock())
    with lk:
        with _lock:
            hit = store.get(key)
            if hit and time.time() - hit[0] < ttl:
                return hit[1]
        try:
            val = load()
        except AuthError:
            with _lock:
                store.pop(key, None)
            raise
        except XtreamError:
            if not hit:
                raise
            with _lock:
                store[key] = (time.time() - ttl + RETRY, hit[1])
            return hit[1]
        else:                            # يُحفظ قبل فكّ قفل التحميل: لا يبدأ طلبٌ لاحق تحميلًا ثانيًا
            with _lock:
                store[key] = (time.time(), val)
                store.move_to_end(key)
                while len(store) > cap:
                    store.popitem(last=False)
            return val
        finally:
            with _lock:
                _loading.pop((id(store), key), None)


def categories(cfg, kind):
    return _cached(_cats, (cfg, kind), TTL, lambda: _list_of(_api(cfg, _ACTION[kind][0])), 2000)


def lists(cfg, kind):
    """كل عناصر النوع (‏movie · series · tv) — من الذاكرة إن حديثة، وإلا من السيرفر بطلبٍ واحد."""
    def load():
        cats = categories(cfg, kind)
        return Lists(kind, cats, _list_of(_api(cfg, _ACTION[kind][1])))
    return _cached(_lists, (cfg, kind), TTL, load, LISTS_MAX)


def _cached_lists(cfg, kind):
    """القوائم إن كانت في الذاكرة فقط (بلا تحميل) — للتفاصيل والتشغيل حين يكفي غيرها."""
    with _lock:
        hit = _lists.get((cfg, kind))
    return hit[1] if hit else None


_info = OrderedDict()                # (الهوست، الإجراء، المعرّف) ← (الوقت، الرد)


def _details(cfg, action, field, iid):
    """تفاصيل فيلمٍ أو مسلسل (تُحفظ ساعات) — وفشلها None لا خطأ: تبقى بيانات القائمة."""
    key = (cfg, action, iid)
    with _lock:
        hit = _info.get(key)
        if hit and time.time() - hit[0] < INFO_TTL:
            return hit[1]
    try:
        d = _api(cfg, action, **{field: iid})
    except AuthError:
        raise
    except XtreamError:
        return hit[1] if hit else None
    if not isinstance(d, dict) or not d:
        return hit[1] if hit else None   # ردٌّ فارغ لا يُحفظ ساعات: قد يكون عابرًا
    with _lock:
        _info[key] = (time.time(), d)
        _info.move_to_end(key)
        while len(_info) > INFO_MAX:
            _info.popitem(last=False)
    return d


def reset():
    """تفريغ الذاكرة (للاختبارات)."""
    with _lock:
        for s in (_accounts, _cats, _lists, _info, _rate):
            s.clear()
        _loading.clear()


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
                   "posterShape": "square" if kind == "tv" else "poster", "releaseInfo": it.year,
                   "imdbRating": it.rating, "description": it.plot or None, "genres": _split(it.genre)})


def manifest(cfg, base, label=""):
    """وصف الإضافة: ثلاثة كتالوجات، وأقسام السيرفر تصنيفاتٍ فيها. فشل أقسام نوعٍ لا يُسقط الإضافة: يبقى
    كتالوجه بلا تصنيفات."""
    pre = prefix(cfg)
    uid = hashlib.sha256(f"{cfg.host}\n{cfg.user}".encode()).hexdigest()[:10]
    tag = f" · {label}" if label else ""
    cats, denied = [], False
    for kind in TYPES:
        seen, genres = set(), []
        try:                             # اشتراكٌ منتهٍ تُثبَّت إضافته ولا تُرفض: يعمل كما هو متى جُدِّد
            for c in ([] if denied or kind not in GENRE_TYPES else categories(cfg, kind)):
                name = " ".join(str(c.get("category_name") or "").split()) if isinstance(c, dict) else ""
                if name and name not in seen and not _adult_cat(c):
                    seen.add(name)
                    genres.append(name)
        except AuthError:
            denied = True
        except XtreamError:
            pass
        extra = ([{"name": "genre", "options": genres, "isRequired": False}] if genres else []) + \
            [{"name": "search", "isRequired": False}, {"name": "skip", "isRequired": False}]
        cats.append({"type": kind, "id": CATALOG[kind], "name": _TITLE[kind] + tag, "extra": extra,
                     "extraSupported": [e["name"] for e in extra]})
    res = {"types": list(TYPES), "idPrefixes": [pre]}
    return {
        "id": f"com.ssouq.xtream.{uid}",
        "version": VERSION,
        "name": BRAND + tag,
        "description": "كل محتوى اشتراكك في Stremio: الأفلام والمسلسلات بمواسمها وحلقاتها بأقسام السيرفر نفسها، "
                       "والقنوات المباشرة كلها في تصنيفٍ واحد، وبحثٌ بالاسم.",
        "logo": f"{base}/static/icons/icon-512.png",
        "background": f"{base}/static/og-image.png",
        "types": list(TYPES),
        "idPrefixes": [pre],
        "resources": ["catalog", {"name": "meta", **res}, {"name": "stream", **res}],
        "catalogs": cats,
        "behaviorHints": {"configurable": True, "configurationRequired": False},
    }


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
        seq = L.by_genre.get(" ".join(extra["genre"].split()), [])
    else:
        seq = L.latest
    pre = prefix(cfg)
    return {"metas": [_preview(pre, kind, it) for it in seq[skip:skip + PAGE]]}


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


def _movie_meta(cfg, pre, num):
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
    return _clean({
        "id": f"{pre}m:{num}", "type": "movie", "name": name,
        "poster": str(info.get("movie_image") or info.get("cover_big") or (it.poster if it else "") or ""),
        "background": _first(info.get("backdrop_path")), "posterShape": "poster",
        "description": " ".join(str(info.get("plot") or info.get("description") or "").split()),
        "releaseInfo": _year(name, info.get("releasedate")), "imdbRating": _rating(info.get("rating")) or (it.rating if it else None),
        "runtime": f"{secs // 60} min" if secs >= 60 else None,
        "genres": _split(info.get("genre")), "cast": _split(info.get("cast") or info.get("actors")),
        "director": _split(info.get("director")), "country": str(info.get("country") or "").strip(),
        "trailers": [{"source": trailer, "type": "Trailer"}] if re.fullmatch(r"[\w-]{6,20}", trailer) else [],
        "behaviorHints": {"defaultVideoId": f"{pre}m:{num}"},
    })


def _series_meta(cfg, pre, num):
    d = _details(cfg, "get_series_info", "series_id", num)
    if not d:
        L = lists(cfg, "series")
        it = L.by_id.get(num)
        return _clean({**_preview(pre, "series", it), "videos": []}) if it else None
    info = d.get("info") if isinstance(d.get("info"), dict) else {}
    L = _cached_lists(cfg, "series")
    it = L.by_id.get(num) if L else None
    name = " ".join(str(info.get("name") or (it.name if it else "")).split())
    eps = d.get("episodes")
    groups = eps.items() if isinstance(eps, dict) else [("", eps if isinstance(eps, list) else [])]
    videos, seen = [], set()
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
            ext = _ext(e.get("container_extension")) or "mp4"
            videos.append(_clean({
                "id": f"{pre}e:{eid}:{ext}", "title": _ep_title(e.get("title"), name, season, episode),
                "season": season, "episode": episode, "released": _released(ei.get("releasedate") or ei.get("air_date")),
                "thumbnail": str(ei.get("movie_image") or ""), "overview": " ".join(str(ei.get("plot") or "").split()),
            }))
    videos.sort(key=lambda v: (v["season"], v["episode"]))
    trailer = str(info.get("youtube_trailer") or "").strip()
    run = _int(info.get("episode_run_time"))
    return _clean({
        "id": f"{pre}s:{num}", "type": "series", "name": name,
        "poster": str(info.get("cover") or (it.poster if it else "") or ""), "posterShape": "poster",
        "background": _first(info.get("backdrop_path")),
        "description": " ".join(str(info.get("plot") or "").split()),
        "releaseInfo": _year(name, info.get("releaseDate") or info.get("release_date")),
        "imdbRating": _rating(info.get("rating")), "runtime": f"{run} min" if run > 0 else None,
        "genres": _split(info.get("genre")), "cast": _split(info.get("cast")), "director": _split(info.get("director")),
        "trailers": [{"source": trailer, "type": "Trailer"}] if re.fullmatch(r"[\w-]{6,20}", trailer) else [],
        "videos": videos,
    })


def meta(cfg, kind, sid):
    p = _parse_id(cfg, sid)
    if not p:
        return None
    code, num, _ = p
    pre = prefix(cfg)
    if code == "m" and kind == "movie":
        m = _movie_meta(cfg, pre, num)
    elif code == "s" and kind == "series":
        m = _series_meta(cfg, pre, num)
    elif code == "l" and kind == "tv":
        it = lists(cfg, "tv").by_id.get(num)
        m = _clean({**_preview(pre, "tv", it), "logo": it.poster,
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


def streams(cfg, kind, sid):
    p = _parse_id(cfg, sid)
    if not p:
        return None
    code, num, ext = p
    u, pw = quote(cfg.user, safe=""), quote(cfg.pw, safe="")
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
        return {"streams": [{"url": f"{cfg.host}/movie/{u}/{pw}/{num}.{ext}", "name": BRAND,
                             "title": f"تشغيل · {ext.upper()}", "behaviorHints": hints}]}
    if code == "e" and kind == "series":
        ext = ext or "mp4"
        return {"streams": [{"url": f"{cfg.host}/series/{u}/{pw}/{num}.{ext}", "name": BRAND,
                             "title": f"تشغيل · {ext.upper()}", "behaviorHints": hints}]}
    if code == "l" and kind == "tv":
        label = {"m3u8": "بث مباشر · HLS", "ts": "بث مباشر · TS"}
        return {"streams": [{"url": f"{cfg.host}/live/{u}/{pw}/{num}.{f}", "name": BRAND, "title": label[f],
                             "behaviorHints": {"notWebReady": True}} for f in _formats(cfg)]}
    return None


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


def _json(code, obj, age=0):
    cache = f"public, max-age={age}" if age and code == 200 else "no-store"
    return code, json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode(), _JSON, {**_CORS, "Cache-Control": cache}


def page():
    with open(_HTML, "rb") as f:
        return 200, f.read(), "text/html; charset=utf-8", {**_PAGE_HDR, "Cache-Control": "no-store"}


def handle(data_dir, path, base, label_for=None):
    """طلب GET تحت ‏/stremio ← (الرمز، الجسم، النوع، الترويسات)، أو None لمسارٍ ليس لها.
    ‏label_for(host) اسم السيرفر كما في الدليل (سمارت · كاسبر · فالكون) للاسم في Stremio."""
    if path != PATH and not path.startswith(PATH + "/"):
        return None
    parts = [unquote(p) for p in path[len(PATH):].split("/") if p != ""]
    if not parts or (len(parts) in (1, 2) and parts[-1] in (parts[0], "configure")):
        return page()                                    # الصفحة العامة، وصفحة التثبيت وزرّ «Configure» في Stremio
    cfg = read_token(data_dir, parts[0])
    if not cfg:
        return _json(404, {"ok": False, "error": "رابطٌ غير صالح — اطلب رابطًا جديدًا"})
    rest = parts[1:]
    if not rest[-1].endswith(".json"):
        return _json(404, {"error": "not found"})
    rest[-1] = rest[-1][:-len(".json")]
    label = ""
    if rest[0] in ("manifest", "status") and label_for:
        try:
            label = label_for(cfg.host) or ""
        except Exception:
            label = ""
    try:
        if rest == ["manifest"]:
            return _json(200, manifest(cfg, base, label), 3600)
        if rest == ["status"]:
            return _json(200, status(cfg, base, parts[0], label))
        if rest[0] == "catalog" and len(rest) in (3, 4):
            res = catalog(cfg, rest[1], rest[2], parse_extra(path.rsplit("/", 1)[-1][:-5]) if len(rest) == 4 else {})
            return _json(200, res, 900) if res is not None else _json(404, {"metas": []})
        if rest[0] == "meta" and len(rest) == 3:
            res = meta(cfg, rest[1], rest[2])
            return _json(200, res, 3600) if res else _json(404, {"meta": None})
        if rest[0] == "stream" and len(rest) == 3:
            res = streams(cfg, rest[1], rest[2])
            return _json(200, res, 600) if res else _json(404, {"streams": []})
    except AuthError as e:
        return _json(403, {"error": str(e)})
    except XtreamError as e:
        return _json(502, {"error": str(e)})
    return _json(404, {"error": "not found"})

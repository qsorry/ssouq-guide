#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
حساب Stremio جاهز للعميل: إيميلٌ وكلمة مرور يدخل بهما Stremio على أي جهاز فيجد محتوى اشتراكه كله مثبّتًا —
بلا رابطٍ ولا «تثبيت».

  الإيميل       يوزر البوابة على دومين المتجر: ‏<اليوزر>@ssouq.com (‏STREMIO_EMAIL_DOMAIN). Stremio لا يطلب تفعيل
                الإيميل، فلا يُنشأ صندوق بريد؛ وتوجيه البريد الشامل (catch-all) على الدومين اختياريٌّ لاستعادة كلمة المرور.
  كلمة المرور   باسورد البوابة نفسه — وإن رفضها Stremio أُضيف إليها «A» (‏STREMIO_PASS_SUFFIX) وأعيد المحاولة.
  الإضافة       إضافة المحتوى (‏stremio_addon) تُثبَّت في الحساب أولَ قائمته، وتحلّ محلّ إضافةٍ سابقةٍ لنا على السيرفر
                نفسه (يوزرٌ بديل)، وتبقى إضافات Stremio الافتراضية كما هي.

بلا مبالغة: الحساب يُنشأ عند الطلب (زرٌّ في الأداة) لا لكل يوزرٍ يُنشأ، وطلبٌ واحد في الوقت، وحدٌّ بالساعة
(‏STREMIO_SIGNUPS_PER_HOUR، الافتراضي 30). وما أُنشئ يُحفظ (كلمة المرور مشفَّرة) فيُعاد بلا طلبٍ ثانٍ لـ Stremio.

واجهة Stremio نفسها التي تستعملها تطبيقاته (‏POST ‏https://api.strem.io/api/<الإجراء>، والرد ‏{"result": …} أو
‏{"error": {"code", "message"}}). بلا مكتبات خارجية.
"""
import datetime
import http.client
import json
import os
import re
import secrets
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import crypto_store

API = os.environ.get("STREMIO_API", "https://api.strem.io").rstrip("/")
DOMAIN = os.environ.get("STREMIO_EMAIL_DOMAIN", "ssouq.com").strip().lower().lstrip("@")
SUFFIX = os.environ.get("STREMIO_PASS_SUFFIX", "A")
PER_HOUR = int(os.environ.get("STREMIO_SIGNUPS_PER_HOUR", "30"))
TIMEOUT = 25
OURS = "com.ssouq.xtream."           # بادئة معرّف إضافتنا (stremio_addon.manifest)


class StremioError(Exception):
    """ردّ Stremio بخطأ أو تعذّر الوصول إليه — رسالته للعرض."""

    def __init__(self, message, code=None, raw=None):
        super().__init__(message)
        self.code = code
        self.raw = raw or {}


# ================= واجهة Stremio =================
def _call(method, body):
    req = Request(f"{API}/api/{method}", data=json.dumps(body).encode(), method="POST",
                  headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urlopen(req, timeout=TIMEOUT) as r:
            d = json.loads(r.read() or b"{}")
    except HTTPError as e:
        try:
            d = json.loads(e.read() or b"{}")
        except ValueError:
            raise StremioError(f"ردّ Stremio بخطأ {e.code}") from None
    except (URLError, OSError, ValueError, http.client.HTTPException):
        raise StremioError("تعذّر الوصول إلى Stremio — حاول بعد قليل") from None
    err = d.get("error") if isinstance(d, dict) else None
    if err:
        err = err if isinstance(err, dict) else {"message": str(err)}
        raise StremioError(str(err.get("message") or "خطأ من Stremio"), err.get("code"), err)
    if not isinstance(d, dict) or "result" not in d:
        raise StremioError("ردّ Stremio بما لا يُفهم")
    return d["result"]


def _auth(result):
    key = result.get("authKey") if isinstance(result, dict) else None
    if not key:
        raise StremioError("ردّ Stremio بلا مفتاح دخول")
    return key


def register(email, password):
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return _auth(_call("register", {"type": "Register", "email": email, "password": password,
                                    "gdpr_consent": {"tos": True, "privacy": True, "marketing": False,
                                                     "time": now, "from": "web"}}))


def login(email, password):
    return _auth(_call("login", {"type": "Login", "email": email, "password": password, "facebook": False}))


def logout(auth):
    try:
        _call("logout", {"type": "Logout", "authKey": auth})
    except StremioError:
        pass                             # الخروج تنظيفٌ لا يُفشل شيئًا


def install(auth, descriptor):
    """يثبّت إضافتنا أولَ قائمة الحساب، ويُسقط إضافةً سابقةً لنا على السيرفر نفسه (نفس بادئة المعرّفات)."""
    res = _call("addonCollectionGet", {"type": "AddonCollectionGet", "authKey": auth, "update": True})
    addons = res.get("addons") if isinstance(res, dict) else None
    addons = [a for a in (addons or []) if isinstance(a, dict)]
    pre = set(descriptor["manifest"].get("idPrefixes") or [])

    def ours(a):
        m = a.get("manifest") or {}
        return a.get("transportUrl") == descriptor["transportUrl"] or (
            str(m.get("id", "")).startswith(OURS) and pre & set(m.get("idPrefixes") or []))
    keep = [a for a in addons if not ours(a)]
    _call("addonCollectionSet", {"type": "AddonCollectionSet", "authKey": auth, "addons": [descriptor] + keep})
    return len(keep) + 1


# ================= الإيميل وكلمة المرور =================
def email_for(username, domain=None):
    """يوزر البوابة ← إيميله: حروفه الصالحة في الإيميل وحدها (أرقام وحروف لاتينية صغيرة و. _ -)."""
    local = re.sub(r"[^a-z0-9._-]", "", str(username or "").strip().lower()).strip(".")
    local = re.sub(r"\.{2,}", ".", local)
    if not local:
        raise ValueError("يوزرٌ لا يصلح اسمًا لإيميل")
    return f"{local[:64]}@{domain or DOMAIN}"


def _exists(e):
    """ردّ Stremio لإيميلٍ مسجّل: ‏{"code": 36, "existingUser": true, "message": "User with this email already exists"}."""
    t = str(e).lower()
    return bool(e.raw.get("existingUser")) or e.code == 36 or any(w in t for w in ("exist", "already", "taken"))


def _weak(e):
    return "password" in str(e).lower()


# ================= الحفظ =================
_lock = threading.Lock()                 # الملف
_signup = threading.Lock()               # تسجيلٌ واحد في الوقت
_rate = {}


def _path(data_dir):
    return os.path.join(data_dir, "stremio_accounts.json")


def _key(host_key, username):
    return f"{host_key}|{username}"


def _load(data_dir):
    try:
        with open(_path(data_dir), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data_dir, d):
    os.makedirs(data_dir, exist_ok=True)
    tmp = f"{_path(data_dir)}.{secrets.token_hex(4)}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _path(data_dir))


def _plain(data_dir, rec):
    return {**rec, "password": crypto_store.decrypt(rec.get("password", ""), data_dir)}


def get(data_dir, host_key, username):
    """حساب Stremio المحفوظ ليوزرٍ على سيرفر (كلمة المرور مفكوكة)، أو None."""
    with _lock:
        rec = _load(data_dir).get(_key(host_key, username))
    return _plain(data_dir, rec) if rec else None


def known(data_dir, host_key, usernames):
    """حسابات يوزراتٍ كثيرة بقراءةٍ واحدة (لنتائج البحث): ‏{اليوزر: الحساب}."""
    with _lock:
        d = _load(data_dir)
    out = {}
    for u in usernames:
        rec = d.get(_key(host_key, u))
        if rec:
            out[u] = _plain(data_dir, rec)
    return out


def rate_ok(now=None, limit=None):
    """حدّ التسجيل بالساعة (للخادم كله) — Stremio لا يُغرق بحساباتٍ متتالية."""
    hour = int((now or time.time()) // 3600)
    with _lock:
        for old in [h for h in _rate if h != hour]:
            _rate.pop(old, None)
        if _rate.get(hour, 0) >= (PER_HOUR if limit is None else limit):
            return False
        _rate[hour] = _rate.get(hour, 0) + 1
        return True


def ensure(data_dir, host_key, username, password, descriptor, owner=None):
    """حساب Stremio ليوزر: المحفوظ كما هو، وإلا يُسجَّل (أو يُستعاد إن سبق تسجيله بكلمة مرورنا) وتُثبَّت فيه
    الإضافة ويُحفظ. ‏descriptor دالةٌ تبني وصف الإضافة (لا يُبنى إلا عند الحاجة). ← (الحساب، أُنشئ الآن؟).
    StremioError برسالةٍ للعرض، وValueError ليوزرٍ لا يصلح أو حدٍّ تجاوزه."""
    rec = get(data_dir, host_key, username)
    if rec:
        return rec, False
    email = email_for(username)
    password = str(password or "").strip()
    if not password:
        raise ValueError("اليوزر بلا باسورد")
    with _signup:
        rec = get(data_dir, host_key, username)      # طلبٌ سبقه وهو ينتظر
        if rec:
            return rec, False
        if not rate_ok():
            raise ValueError(f"بلغت حسابات Stremio حدّها لهذه الساعة ({PER_HOUR}) — حاول بعد قليل")
        pw, auth, adopted = password, None, False
        try:
            auth = register(email, pw)
        except StremioError as e:
            if _exists(e):                           # سُجّل من قبل (من هنا أو يدويًا): نجرّب كلمتَي مرورنا
                for cand in (pw, pw + SUFFIX) if SUFFIX else (pw,):
                    try:
                        auth, pw, adopted = login(email, cand), cand, True
                        break
                    except StremioError:
                        continue
                if not auth:
                    raise StremioError(f"الإيميل {email} مسجّلٌ في Stremio بكلمة مرورٍ أخرى") from None
            elif SUFFIX and not pw.endswith(SUFFIX) and (_weak(e) or pw.isdigit()):
                pw = pw + SUFFIX                     # رفض Stremio كلمة المرور (أو كانت أرقامًا فقط): يُضاف حرفٌ كبير
                auth = register(email, pw)
            else:
                raise
        try:
            install(auth, descriptor())
        finally:
            logout(auth)
        rec = {"email": email, "password": crypto_store.encrypt(pw, data_dir), "username": username,
               "host": host_key, "created": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M"),
               **({"adopted": True} if adopted else {}), **(owner or {})}
        with _lock:
            d = _load(data_dir)
            d[_key(host_key, username)] = rec
            _save(data_dir, d)
        return _plain(data_dir, rec), True

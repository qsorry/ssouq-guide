# -*- coding: utf-8 -*-
"""حسابات Nuvio الجاهزة — مسار تسجيلٍ مستقل عن Stremio، على خادم Nuvio الرسمي (‏api.nuvio.tv) وبواجهته التي تستعملها تطبيقاته
نفسها (تحقّقنا منها في docs/nuvio.md): Supabase — ‏/auth/v1 للحساب، و‏/rest/v1/rpc للإضافات ودخول التلفاز.

  الحساب      إيميلٌ محايد من خطّه (‏ssq<بصمة>@tv.ssouq.com — لا يوزر Xtream فيه) وكلمة مرورٍ عشوائية تُحفظ مشفَّرة؛ التسجيل
              مفتوحٌ بلا تأكيد بريد (‏mailer_autoconfirm).
  الإضافة     رابط manifest إضافتنا (رمزٌ مختوم، لا بيانات Xtream فيه) في قائمة إضافات الملف 1 — ‏sync_push_addons تستبدل القائمة
              كاملة، فتُقرأ أولًا وتبقى إضافات العميل الأخرى كما هي، وإضافتنا أولها.
  التلفاز     ‏approve_tv_login_session: الكود الظاهر في تلفاز العميل يوافَق عليه من الأداة بجلسة حسابه — فيدخل التلفاز وإضافته
              جاهزة بلا كتابة إيميلٍ ولا كلمة مرور.

الحفظ: ‏data/nuvio_accounts.json ‏{«هوست|يوزر»: {email, password (مشفَّرة), user_id, token, addon_key, acct, gate, status, …}}.
"""
import datetime
import hashlib
import json
import os
import secrets
import string
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import crypto_store

BACKEND = os.environ.get("NUVIO_BACKEND", "https://api.nuvio.tv").rstrip("/")
DOMAIN = os.environ.get("NUVIO_EMAIL_DOMAIN") or os.environ.get("STREMIO_EMAIL_DOMAIN", "tv.ssouq.com")
TIMEOUT = 20
FILE = "nuvio_accounts.json"
CONFIG_TTL = 3600
PROFILE = 1                          # ملف Nuvio الأول (الافتراضي في كل التطبيقات)
UA = "ssouq-guide/2.0 (+https://guide.ssouq.com/)"

_lock = threading.Lock()
_conf = {"at": 0, "value": None}


class NuvioError(Exception):
    """خطأٌ من خادم Nuvio برسالةٍ للعرض."""


# ---- خادم Nuvio ----
def _http(method, url, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = Request(url, data=data, method=method, headers={"Content-Type": "application/json", "User-Agent": UA, **(headers or {})})
    try:
        with urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
            return json.loads(raw) if raw.strip() else None
    except HTTPError as e:
        try:
            d = json.loads(e.read() or b"{}")
        except ValueError:
            d = {}
        msg = d.get("msg") or d.get("message") or d.get("error_description") or d.get("error") or f"HTTP {e.code}"
        raise NuvioError(str(msg)) from None
    except (URLError, OSError, ValueError):
        raise NuvioError("تعذّر الوصول إلى خادم Nuvio") from None


def config():
    """إعدادات الاتصال العامة (‏/.well-known/nuvio): عنوان الخادم والمفتاح العام — محفوظةٌ ساعة."""
    now = time.time()
    with _lock:
        if _conf["value"] and now - _conf["at"] < CONFIG_TTL:
            return _conf["value"]
    d = _http("GET", f"{BACKEND}/.well-known/nuvio")
    if not isinstance(d, dict) or not d.get("publishable_key"):
        raise NuvioError("ردٌّ غير متوقع من خادم Nuvio")
    if not (d.get("capabilities") or {}).get("email_password_auth", True):
        raise NuvioError("خادم Nuvio لا يقبل الدخول بالإيميل الآن")
    value = {"backend": str(d.get("backend_url") or BACKEND).rstrip("/"), "key": d["publishable_key"],
             "tv_login": bool((d.get("capabilities") or {}).get("tv_login"))}
    with _lock:
        _conf.update(at=now, value=value)
    return value


def _api(method, path, body=None, token=None):
    c = config()
    return _http(method, c["backend"] + path, body, {"apikey": c["key"], "Authorization": f"Bearer {token or c['key']}"})


def _session(d):
    if not isinstance(d, dict) or not d.get("access_token"):
        raise NuvioError("لم يُنشئ خادم Nuvio جلسة")
    return {"access_token": d["access_token"], "refresh_token": d.get("refresh_token", ""),
            "user_id": str((d.get("user") or {}).get("id") or "")}


def login(email, password):
    return _session(_api("POST", "/auth/v1/token?grant_type=password", {"email": email, "password": password}))


def signup(email, password):
    """حسابٌ جديد ← جلسته؛ ومسجَّلٌ من قبل (بكلمة المرور نفسها) ← دخولٌ إليه."""
    try:
        d = _api("POST", "/auth/v1/signup", {"email": email, "password": password})
    except NuvioError as e:
        if "already" in str(e).lower() or "registered" in str(e).lower():
            return login(email, password)
        raise
    if isinstance(d, dict) and not d.get("access_token") and (d.get("id") or (d.get("user") or {}).get("id")):
        return login(email, password)              # خادمٌ يطلب تأكيد البريد لا يردّ جلسة
    return _session(d)


def pull_addons(sess, profile=PROFILE):
    d = _api("POST", "/rest/v1/rpc/sync_pull_addons", {"p_profile_id": profile}, sess["access_token"])
    return [a for a in d or [] if isinstance(a, dict) and a.get("url")]


def push_addons(sess, addons, profile=PROFILE):
    items = [{"url": a["url"], "name": a.get("name") or "", "enabled": a.get("enabled", True) is not False, "sort_order": i}
             for i, a in enumerate(addons)]
    _api("POST", "/rest/v1/rpc/sync_push_addons", {"p_addons": items, "p_profile_id": profile}, sess["access_token"])
    return items


def install(sess, manifest_url, name, ours, profile=PROFILE):
    """إضافتنا أول قائمة الملف (ونسختها السابقة تُزال — ‏ours(رابط) يعرفها)، وإضافات العميل الأخرى كما هي ← القائمة."""
    keep = [a for a in pull_addons(sess, profile) if not ours(a["url"]) and a["url"] != manifest_url]
    return push_addons(sess, [{"url": manifest_url, "name": name, "enabled": True}] + keep, profile)


def uninstall(sess, ours, profile=PROFILE):
    return push_addons(sess, [a for a in pull_addons(sess, profile) if not ours(a["url"])], profile)


def approve_tv(sess, code):
    """الكود الظاهر في تلفاز العميل ← يدخل التلفاز بهذا الحساب. ‏ValueError لكودٍ فارغ أو انتهى أو لم يوجد، و‏NuvioError
    لخادمٍ لا يردّ."""
    code = "".join(str(code or "").split()).upper()
    if not code or len(code) > 32:
        raise ValueError("اكتب الكود الظاهر في التلفاز")
    d = _api("POST", "/rest/v1/rpc/approve_tv_login_session", {"p_code": code}, sess["access_token"])
    row = (d[0] if isinstance(d, list) and d else d) or {}
    if not isinstance(row, dict) or not row.get("success"):
        raise ValueError("الكود غير صحيح أو انتهت مدته — اطلب من العميل كودًا جديدًا من التلفاز")
    return True


# ---- الحسابات المحفوظة ----
def email_for(host_key, username):
    """إيميلٌ محايدٌ ثابتٌ للخط — لا يوزر Xtream فيه."""
    return f"ssq{hashlib.sha256(f'{host_key}|{username}'.encode()).hexdigest()[:10]}@{DOMAIN}"


def new_password():
    abc = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(abc) for _ in range(12))
        if any(c.isdigit() for c in pw) and any(c.isalpha() for c in pw):
            return pw


def _path(data_dir):
    return os.path.join(data_dir, FILE)


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
    tmp = _path(data_dir) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _path(data_dir))


def _plain(data_dir, rec):
    return {**rec, "password": crypto_store.decrypt(rec.get("password", ""), data_dir)} if rec else None


def get(data_dir, host_key, username):
    with _lock:
        rec = _load(data_dir).get(_key(host_key, username))
    return _plain(data_dir, rec)


def put(data_dir, host_key, username, **fields):
    """يحفظ الحساب (كلمة المرور تُشفَّر) ← المحفوظ."""
    if "password" in fields:
        fields["password"] = crypto_store.encrypt(fields["password"], data_dir)
    with _lock:
        d = _load(data_dir)
        rec = d.setdefault(_key(host_key, username), {"host": host_key, "username": username,
                                                      "created": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M"),
                                                      "ts": round(time.time(), 3)})
        rec.update(fields)
        _save(data_dir, d)
        return _plain(data_dir, dict(rec))


def owned(data_dir, acct_id, gate_id=None):
    """حسابات Nuvio لحساب أداةٍ (ولبوابةٍ منه) — الأحدث أولًا."""
    with _lock:
        d = _load(data_dir)
    out = [_plain(data_dir, r) for r in d.values() if isinstance(r, dict) and r.get("acct") == acct_id
           and (gate_id is None or r.get("gate") == gate_id)]
    return sorted(out, key=lambda r: -(r.get("ts") or 0))


_idx = {"mtime": None, "map": {}}


def _indexed(data_dir, host_key, username):
    """(قفل الإضافة الساري، صاحبه في الأداة {acct, gate}) ليوزر — يُسأل في كل طلبٍ للإضافة، ففهرسه في الذاكرة ما دام
    الملف لم يتغيّر (بلا كلمات مرور). ‏(None، None) لا حساب."""
    try:
        mtime = os.path.getmtime(_path(data_dir))
    except OSError:
        return None, None
    with _lock:
        if _idx["mtime"] != (data_dir, mtime):
            _idx["map"] = {k: (r.get("addon_key") if r.get("status") != "off" else None, {"acct": r.get("acct"), "gate": r.get("gate")})
                           for k, r in _load(data_dir).items() if isinstance(r, dict)}
            _idx["mtime"] = (data_dir, mtime)
        return _idx["map"].get(_key(host_key, username), (None, None))


def addon_key(data_dir, host_key, username):
    """قفل رابط إضافة Nuvio لهذا الخط (رابطٌ أُلغي تفعيله أو أُعيد ربطه يتوقف)، أو None."""
    return _indexed(data_dir, host_key, username)[0]


def owner(data_dir, host_key, username):
    """صاحب حساب Nuvio لهذا الخط في الأداة ‏{acct, gate} (لتصنيفاته واسم سيرفره)، أو None."""
    return _indexed(data_dir, host_key, username)[1]

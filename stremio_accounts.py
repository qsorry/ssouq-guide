#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
حساب Stremio جاهز للعميل: إيميلٌ وكلمة مرور يدخل بهما Stremio على أي جهاز فيجد محتوى اشتراكه كله مثبّتًا —
بلا رابطٍ ولا «تثبيت».

  الإيميل       يوزر البوابة على الدومين الفرعي للبريد: ‏<اليوزر>@tv.ssouq.com (‏STREMIO_EMAIL_DOMAIN). Stremio لا يطلب
                تفعيل الإيميل، فلا يُنشأ صندوق بريد؛ وما يصل لهذه العناوين (رابط «نسيت كلمة المرور») يستقبله خادمنا
                (‏mail_inbox) ويظهر في الأداة عند اليوزر.
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
DOMAIN = os.environ.get("STREMIO_EMAIL_DOMAIN", "tv.ssouq.com").strip().lower().lstrip("@")
SUFFIX = os.environ.get("STREMIO_PASS_SUFFIX", "A")
PER_HOUR = int(os.environ.get("STREMIO_SIGNUPS_PER_HOUR", "60"))   # دفعةٌ من 30 وما يتبعها في الساعة نفسها
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


def _ours(a):
    return str((a.get("manifest") or {}).get("id", "")).startswith(OURS)


def _with_extras(addons, extras):
    """القائمة ومعها ما ليس فيها من «الإضافات الأخرى» (بالرابط أو بالمعرّف) — بعد إضافاتنا مباشرة (قبل Cinemeta
    وغيرها: إضافة بياناتٍ مثل AIOMetadata تُقدَّم عليها)."""
    urls = {a.get("transportUrl") for a in addons}
    ids = {(a.get("manifest") or {}).get("id") for a in addons}
    add = [e for e in extras or () if e.get("transportUrl") not in urls and (e.get("manifest") or {}).get("id") not in ids]
    if not add:
        return addons
    at = max((n + 1 for n, a in enumerate(addons) if _ours(a)), default=0)
    return addons[:at] + list(add) + addons[at:]


def set_extras(auth, extras, remove=False):
    """«الإضافات الأخرى» في حسابٍ: تُثبَّت ما ليس فيه منها، أو تُسقط (بروابطها). ← كم تغيّر."""
    res = _call("addonCollectionGet", {"type": "AddonCollectionGet", "authKey": auth, "update": True})
    addons = [a for a in ((res.get("addons") if isinstance(res, dict) else None) or []) if isinstance(a, dict)]
    if remove:
        urls = {e.get("transportUrl") for e in extras}
        new = [a for a in addons if a.get("transportUrl") not in urls]
    else:
        new = _with_extras(addons, extras)
    if len(new) != len(addons):
        _call("addonCollectionSet", {"type": "AddonCollectionSet", "authKey": auth, "addons": new})
    return abs(len(new) - len(addons))


def install(auth, descriptor, first=True, extras=()):
    """يثبّت إضافتنا أولَ قائمة الحساب (أو بعد إضافاتنا فيه: خطٌّ يُربط بحسابٍ فيه غيره)، ويحلّ محلّ إضافةٍ سابقةٍ
    لنا على السيرفر نفسه (نفس بادئة المعرّفات) في مكانها؛ ومعها «الإضافات الأخرى» (‏extras) ما لم تكن فيه."""
    res = _call("addonCollectionGet", {"type": "AddonCollectionGet", "authKey": auth, "update": True})
    addons = res.get("addons") if isinstance(res, dict) else None
    addons = [a for a in (addons or []) if isinstance(a, dict)]
    pre = set(descriptor["manifest"].get("idPrefixes") or [])

    def ours(a):
        m = a.get("manifest") or {}
        return a.get("transportUrl") == descriptor["transportUrl"] or (
            str(m.get("id", "")).startswith(OURS) and pre & set(m.get("idPrefixes") or []))
    keep = [a for a in addons if not ours(a)]
    old = next((n for n, a in enumerate(addons) if ours(a)), None)
    if old is not None:                              # تحديثٌ لإضافةٍ فيه: مكانها نفسه
        at = sum(1 for a in addons[:old] if not ours(a))
    else:
        at = 0 if first else max((n + 1 for n, a in enumerate(keep) if _ours(a)), default=0)
    new = _with_extras(keep[:at] + [descriptor] + keep[at:], extras)
    _call("addonCollectionSet", {"type": "AddonCollectionSet", "authKey": auth, "addons": new})
    return len(new)


def uninstall(auth, prefixes):
    """يُسقط من الحساب إضافتنا لسيرفرٍ (ببادئة معرّفاته) — خطٌّ فُصل عن الحساب. ← كم أُسقط."""
    res = _call("addonCollectionGet", {"type": "AddonCollectionGet", "authKey": auth, "update": True})
    addons = [a for a in ((res.get("addons") if isinstance(res, dict) else None) or []) if isinstance(a, dict)]
    pre = set(prefixes or [])
    keep = [a for a in addons if not (_ours(a) and pre & set((a.get("manifest") or {}).get("idPrefixes") or []))]
    if len(keep) != len(addons):
        _call("addonCollectionSet", {"type": "AddonCollectionSet", "authKey": auth, "addons": keep})
    return len(addons) - len(keep)


# ================= الإيميل وكلمة المرور =================
def email_for(username, domain=None):
    """يوزر البوابة ← إيميله: حروفه الصالحة في الإيميل وحدها (أرقام وحروف لاتينية صغيرة و. _ -)."""
    local = re.sub(r"[^a-z0-9._-]", "", str(username or "").strip().lower()).strip(".")
    local = re.sub(r"\.{2,}", ".", local)
    if not local:
        raise ValueError("يوزرٌ لا يصلح اسمًا لإيميل")
    return f"{local[:64]}@{domain or DOMAIN}"


def custom_email(name, domain=None):
    """إيميلٌ يختاره الموظف لحساب Stremio: اسمٌ (أو اسم@دومين بريدنا — ليصل بريده هنا) بحروفٍ لاتينية صغيرة وأرقام
    و. _ - (3–64). ‏ValueError برسالةٍ للعرض."""
    dom = domain or DOMAIN
    s = str(name or "").strip().lower()
    if "@" in s:
        s, at = s.rsplit("@", 1)
        if at != dom:
            raise ValueError(f"الإيميل على دومين بريدنا وحده (@{dom}) — ليصل بريده هنا")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,62}[a-z0-9]", s) or ".." in s:
        raise ValueError("اسم الإيميل: حروفٌ لاتينية وأرقام و. _ - (3 أحرف فأكثر)")
    return f"{s}@{dom}"


def custom_password(password):
    """كلمة مرورٍ يختارها الموظف كما هي (6–64 بلا مسافات). ‏ValueError برسالةٍ للعرض."""
    pw = str(password or "")
    if not 6 <= len(pw) <= 64 or re.search(r"\s", pw):
        raise ValueError("كلمة المرور: 6 أحرف فأكثر بلا مسافات")
    return pw


def email_taken(data_dir, email):
    """هل لإيميلٍ حسابٌ عندنا (لأي يوزر)؟"""
    email = str(email or "").strip().lower()
    with _lock:
        d = _load(data_dir)
    return any(isinstance(r, dict) and str(r.get("email", "")).lower() == email for r in d.values())


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


_idx = {"mtime": None, "map": {}}


def _indexed(data_dir, host_key, username):
    """(قفل الإضافة، صاحب الحساب في الأداة) ليوزرٍ — يُسأل في كل طلبٍ للإضافة، ففهرسه في الذاكرة ما دام الملف لم
    يتغيّر. ‏(None، None) لا حساب."""
    try:
        mtime = os.path.getmtime(_path(data_dir))
    except OSError:
        return None, None
    with _lock:
        if _idx["mtime"] != (data_dir, mtime):
            _idx["map"] = {k: (r.get("addon_key"), r.get("acct")) for k, r in _load(data_dir).items() if isinstance(r, dict)}
            _idx["mtime"] = (data_dir, mtime)
        return _idx["map"].get(_key(host_key, username), (None, None))


def addon_key(data_dir, host_key, username):
    """قفل إضافة حساب يوزرٍ، أو None لحسابٍ غير مقفل أو لا حساب."""
    return _indexed(data_dir, host_key, username)[0]


def acct_of(data_dir, host_key, username):
    """حساب الأداة الذي أنشأ حساب Stremio ليوزرٍ (لتحويل هوسته)، أو None."""
    return _indexed(data_dir, host_key, username)[1]


_emails = {"mtime": None, "map": {}}


def by_email(data_dir, addr):
    """الحساب الذي له هذا الإيميل (بلا كلمة مرور)، أو None — يسأله مستقبِل البريد عن كل مستلم، فالفهرس يُبنى
    مرةً لكل تعديلٍ في الملف."""
    try:
        mtime = os.path.getmtime(_path(data_dir))
    except OSError:
        return None
    with _lock:
        if _emails["mtime"] != (data_dir, mtime):
            _emails["map"] = {str(r.get("email", "")).lower(): {k: v for k, v in r.items() if k != "password"}
                              for r in _load(data_dir).values() if isinstance(r, dict)}
            _emails["mtime"] = (data_dir, mtime)
        return _emails["map"].get(str(addr or "").strip().lower())


def owned(data_dir, acct_id, gate_id, username):
    """حساب Stremio ليوزرٍ أنشأه هذا الحساب من هذه البوابة ← (مفتاح السيرفر، الحساب)، أو None — فلا يرى أحدٌ
    بريد يوزرات غيره."""
    with _lock:
        d = _load(data_dir)
    for rec in d.values():
        if (isinstance(rec, dict) and rec.get("username") == username and rec.get("acct") == acct_id
                and rec.get("gate") == gate_id):
            return rec.get("host"), _plain(data_dir, rec)
    return None


def owned_all(data_dir, acct_id):
    """كل حسابات Stremio التي أنشأها هذا الحساب (كلمات المرور مفكوكة) — لصفحة Stremio: الأحدث أولًا."""
    with _lock:
        d = _load(data_dir)
    recs = [_plain(data_dir, r) for r in d.values() if isinstance(r, dict) and r.get("acct") == acct_id]
    return sorted(recs, key=lambda r: (r.get("ts") or 0, r.get("created", "")), reverse=True)


def note(data_dir, host_key, username, **fields):
    """يحفظ مع الحساب ما يُعرف عنه لاحقًا (انتهاء يوزره وحاله) — بلا مسّ كلمة المرور."""
    fields.pop("password", None)
    with _lock:
        d = _load(data_dir)
        r = d.get(_key(host_key, username))
        if not r:
            return False
        r.update(fields)
        _save(data_dir, d)
    return True


def reinstall(data_dir, host_key, username, descriptor, extras=()):
    """يعيد تثبيت الإضافة في حسابٍ محفوظ (بأحدث أقسامها وأعدادها) — تحلّ محلّ نسختنا السابقة فيه."""
    rec = get(data_dir, host_key, username)
    if not rec:
        raise ValueError("لا حساب Stremio لهذا اليوزر")
    auth = login(rec["email"], rec["password"])
    try:
        install(auth, descriptor(), extras=extras)
    finally:
        logout(auth)
    return rec


MAX_LINES = int(os.environ.get("STREMIO_MAX_LINES", "8"))   # خطوطٌ (سيرفرات) في حساب Stremio واحد


def group(data_dir, host_key, username):
    """حساب Stremio وكل خطوطه: [صاحب الحساب، ثم الخطوط المرتبطة به بترتيب ربطها] — كلمات المرور مفكوكة، وكلٌّ معه
    "key" مفتاحه. ‏[] لا حساب."""
    with _lock:
        d = _load(data_dir)
    k = _key(host_key, username)
    if not isinstance(d.get(k), dict):
        return []
    root = d[k].get("linked_to") if d[k].get("linked_to") in d else k
    kids = sorted(((kk, r) for kk, r in d.items() if isinstance(r, dict) and r.get("linked_to") == root),
                  key=lambda x: x[1].get("ts") or 0)
    return [{**_plain(data_dir, r), "key": kk} for kk, r in [(root, d[root])] + kids]


def link(data_dir, root_host_key, root_username, host_key, username, descriptor, owner=None, extras=()):
    """يربط خطًّا (يوزرًا على سيرفرٍ آخر) بحساب Stremio قائم: تُثبَّت إضافته فيه بجانب إضافاتنا الأخرى، ويُحفظ له
    حسابٌ بإيميل صاحب الحساب وكلمة مروره (‏linked_to). ← (الخط، رُبط الآن؟). ‏ValueError: لا حساب، أو لليوزر حسابٌ
    آخر، أو في الحساب خطٌّ من السيرفر نفسه (إضافتهما تتزاحمان)، أو بلغ الحدّ. ‏StremioError برسالةٍ للعرض."""
    with _signup:
        with _lock:
            d = _load(data_dir)
        rk = _key(root_host_key, root_username)
        root = d.get(rk)
        if not isinstance(root, dict):
            raise ValueError("لا حساب Stremio لهذا اليوزر")
        if root.get("linked_to") in d:             # خطٌّ مرتبط: يُربط الجديد بصاحب حسابه
            rk = root["linked_to"]
            root = d[rk]
        k = _key(host_key, username)
        cur = d.get(k)
        if isinstance(cur, dict):
            if k == rk or cur.get("linked_to") == rk:
                return _plain(data_dir, cur), False
            raise ValueError(f"لليوزر {username} حساب Stremio آخر ({cur.get('email', '')})")
        members = [root] + [r for r in d.values() if isinstance(r, dict) and r.get("linked_to") == rk]
        if any(r.get("host") == host_key for r in members):
            raise ValueError("في هذا الحساب خطٌّ من السيرفر نفسه — اربط خطًّا من سيرفرٍ آخر")
        if len(members) >= MAX_LINES:
            raise ValueError(f"بلغ الحساب حدّه ({MAX_LINES} خطوط)")
        email = root["email"]
        auth = login(email, crypto_store.decrypt(root.get("password", ""), data_dir))
        try:
            install(auth, descriptor(), first=False, extras=extras)
        finally:
            logout(auth)
        rec = {"email": email, "password": root.get("password", ""), "username": username, "host": host_key,
               "created": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M"),
               "ts": round(time.time(), 3), **(owner or {}), "linked_to": rk}
        with _lock:
            d = _load(data_dir)
            d[k] = rec
            _save(data_dir, d)
        return _plain(data_dir, rec), True


def unlink(data_dir, host_key, username, prefixes):
    """يفصل خطًّا مرتبطًا عن حسابه: تُسقط إضافته من الحساب ويُنسى. ‏ValueError لخطٍّ غير مرتبط (صاحب الحساب لا
    يُفصل)، وStremioError برسالةٍ للعرض (ولا يُنسى شيء)."""
    rec = get(data_dir, host_key, username)
    if not rec or not rec.get("linked_to"):
        raise ValueError("هذا الخط ليس مرتبطًا بحسابٍ آخر")
    auth = login(rec["email"], rec["password"])
    try:
        uninstall(auth, prefixes)
    finally:
        logout(auth)
    with _lock:
        d = _load(data_dir)
        d.pop(_key(host_key, username), None)
        _save(data_dir, d)
    return rec


def set_password(data_dir, host_key, username, password):
    """كلمة مرورٍ جديدة غيّرها العميل أو الموظف في Stremio (من رابط «نسيت كلمة المرور»): تُجرَّب بالدخول أولًا،
    ثم تُحفظ مشفَّرة. ‏ValueError إن لم يكن له حساب، وStremioError إن رفضها Stremio."""
    password = str(password or "").strip()
    rec = get(data_dir, host_key, username)
    if not rec:
        raise ValueError("لا حساب Stremio لهذا اليوزر")
    if not password:
        raise ValueError("اكتب كلمة المرور الجديدة")
    try:
        logout(login(rec["email"], password))
    except StremioError as e:
        raise StremioError("Stremio لم يقبل كلمة المرور هذه — تأكّد أنها الجديدة" if "password" in str(e).lower() else str(e),
                           e.code, e.raw) from None
    enc, when = crypto_store.encrypt(password, data_dir), datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
    with _lock:
        d = _load(data_dir)
        for r in d.values():                         # الحساب نفسه بكل خطوطه المرتبطة
            if isinstance(r, dict) and r.get("email") == rec["email"]:
                r["password"], r["changed"] = enc, when
        _save(data_dir, d)
    return get(data_dir, host_key, username)


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


def ensure(data_dir, host_key, username, password, descriptor, owner=None, email=None, extras=()):
    """حساب Stremio ليوزر: المحفوظ كما هو، وإلا يُسجَّل (أو يُستعاد إن سبق تسجيله بكلمة مرورنا) وتُثبَّت فيه
    الإضافة ويُحفظ. ‏descriptor دالةٌ تبني وصف الإضافة (لا يُبنى إلا عند الحاجة). ‏email: إيميلٌ يختاره الموظف
    (‏custom_email) بدل إيميل اليوزر، وpassword حينها كلمة مروره كما كُتبت (بلا «A»). ← (الحساب، أُنشئ الآن؟).
    StremioError برسالةٍ للعرض، وValueError ليوزرٍ لا يصلح أو حدٍّ تجاوزه أو إيميلٍ مستخدم."""
    rec = get(data_dir, host_key, username)
    if rec:
        return rec, False
    custom = email is not None
    email = custom_email(email) if custom else email_for(username)
    password = custom_password(password) if custom else str(password or "").strip()
    if not password:
        raise ValueError("اليوزر بلا باسورد")
    with _signup:
        rec = get(data_dir, host_key, username)      # طلبٌ سبقه وهو ينتظر
        if rec:
            return rec, False
        if custom and email_taken(data_dir, email):
            raise ValueError(f"الإيميل {email} لحسابٍ آخر عندنا — اختر اسمًا آخر، أو اربط الخط بذلك الحساب")
        if not rate_ok():
            raise ValueError(f"بلغت حسابات Stremio حدّها لهذه الساعة ({PER_HOUR}) — حاول بعد قليل")
        pw, auth, adopted = password, None, False
        try:
            auth = register(email, pw)
        except StremioError as e:
            if _exists(e):                           # سُجّل من قبل (من هنا أو يدويًا): نجرّب كلمتَي مرورنا
                for cand in (pw, pw + SUFFIX) if SUFFIX and not custom else (pw,):
                    try:
                        auth, pw, adopted = login(email, cand), cand, True
                        break
                    except StremioError:
                        continue
                if not auth:
                    raise StremioError(f"الإيميل {email} مسجّلٌ في Stremio بكلمة مرورٍ أخرى") from None
            elif SUFFIX and not custom and not pw.endswith(SUFFIX) and (_weak(e) or pw.isdigit()):
                pw = pw + SUFFIX                     # رفض Stremio كلمة المرور (أو كانت أرقامًا فقط): يُضاف حرفٌ كبير
                auth = register(email, pw)
            else:
                raise
        try:
            install(auth, descriptor(), extras=extras)
        finally:
            logout(auth)
        rec = {"email": email, "password": crypto_store.encrypt(pw, data_dir), "username": username,
               "host": host_key, "created": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M"),
               "ts": round(time.time(), 3),             # للترتيب: حساباتٌ كثيرة في الدقيقة نفسها
               **({"adopted": True} if adopted else {}), **({"custom": True} if custom else {}), **(owner or {})}
        with _lock:
            d = _load(data_dir)
            d[_key(host_key, username)] = rec
            _save(data_dir, d)
        return _plain(data_dir, rec), True

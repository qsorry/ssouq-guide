#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Xtream-Masters — إنشاء يوزرات M3U Lines (متعدد الحسابات)
--------------------------------------------------------
التشغيل:
  python xm_lines.py web      ← يشغّل الصفحة على http://127.0.0.1:8080
  python xm_lines.py          ← وضع سطر الأوامر
  python xm_lines.py debug    ← يطبع رد get_packages الخام

الصفحة الرئيسية / دليل تفعيل عام، والأداة على نطاقها: https://admin.ssouq.com/
أول مرة تفتحه تضع كلمة مرور المدير، ثم من /accounts تضيف الحسابات
(لكل حساب: اسم دخول، كلمة مرور، رابط API، مفتاح API، هوست).
ولا وجود لها على الموقع العام: guide.ssouq.com/admin لا يفتح شيئًا (404).
البيانات تُحفظ في data/accounts.json. لا يحتاج أي مكتبات خارجية (Python 3.8+).
"""
import json, os, re, sys, secrets, datetime, base64, hmac, hashlib, threading, time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import copy

import guide_pages
import store_sitemap
import xm_web
import falcon_api
import crypto_store
import salla_api
import wa_send
import renew
import renew_import
import salla_web

# كلمة مرور الدخول تُخزَّن مُجزّأة (hash) لا مشفَّرة، فلا تُسترجع أبدًا.
# أسرار اللوحات تبقى مشفَّرة (نحتاجها للدخول للّوحة) لكنها لا تُرسَل للمتصفح.
_SENSITIVE_ACCT = ()
_SENSITIVE_GATE = ("panel_pass", "api_key")
_SENSITIVE_SVC = ("salla_secret", "salla_token")   # أسرار خدمة سلة المشفَّرة
_SENSITIVE_WA = ("token", "secret")                # أسرار قناة الواتساب المشفَّرة
_SENSITIVE_ALERT = ("password",)                   # كلمة مرور بريد تنبيه التجديد
_SENSITIVE_RENEW = ("panel_cookie",)               # كوكيز جلسة لوحة سلة


def _is_hash(v):
    return isinstance(v, dict) and "salt" in v and "hash" in v


def _crypt_store(st, fn):
    out = copy.deepcopy(st)
    for a in out.get("accounts", []):
        for k in _SENSITIVE_ACCT:
            if k in a:
                a[k] = fn(a[k], DATA_DIR)
        for g in a.get("gates", []) or []:
            for k in _SENSITIVE_GATE:
                if k in g:
                    g[k] = fn(g[k], DATA_DIR)
    svc = out.get("service")
    if isinstance(svc, dict):
        for k in _SENSITIVE_SVC:
            if svc.get(k):
                svc[k] = fn(svc[k], DATA_DIR)
        wa = svc.get("wa")
        if isinstance(wa, dict):
            for k in _SENSITIVE_WA:
                if wa.get(k):
                    wa[k] = fn(wa[k], DATA_DIR)
    rnw = out.get("renew")
    if isinstance(rnw, dict):
        for k in _SENSITIVE_RENEW:
            if rnw.get(k):
                rnw[k] = fn(rnw[k], DATA_DIR)
        if isinstance(rnw.get("alert"), dict):
            for k in _SENSITIVE_ALERT:
                if rnw["alert"].get(k):
                    rnw["alert"][k] = fn(rnw["alert"][k], DATA_DIR)
    return out

# ================= الإعدادات =================
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.environ.get("XM_DATA", os.path.join(BASE_DIR, "data"))
ACC_FILE  = os.path.join(DATA_DIR, "accounts.json")
TXT_FILE  = os.path.join(DATA_DIR, "lines.txt")
STATS_FILE = os.path.join(DATA_DIR, "stats.json")   # عدّاد أداة M3U العامة

def load_stats():
    try:
        with open(STATS_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

def bump_stat(key):
    os.makedirs(DATA_DIR, exist_ok=True)
    d = load_stats(); d[key] = int(d.get(key, 0)) + 1
    tmp = STATS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, STATS_FILE)
    return d[key]
# ----- النطاقان -----
# الأداة لها نطاقها الخاص وتُقدَّم عليه من الجذر (admin.ssouq.com/ = صفحة الأداة)،
# والموقع العام يبقى دليل التفعيل وحده: `guide.ssouq.com/admin` **لا يفتح شيئًا**
# (‏404 كأن المسار لم يوجد) — لا تحويل ولا صفحة دخول، فلا أثر للوحة على الموقع العام.
# `XM_ADMIN_HOST` فارغًا = لا نطاق للأداة، فتبقى تحت /admin كما كانت — وهو ما
# يحدث محليًا وفي الاختبارات أصلاً لأن الطلب يصل بـ Host = 127.0.0.1 لا بالنطاق.
SITE_HOST  = os.environ.get("XM_SITE_HOST", "guide.ssouq.com").strip().lower()
ADMIN_HOST = os.environ.get("XM_ADMIN_HOST", "admin.ssouq.com").strip().lower()
ADMIN_PATH = "/admin"                                 # مسار الأداة حين لا نطاق لها
# صفحات الأداة بمسارها الداخلي (تحت /admin على الموقع العام، ومن الجذر على نطاقها)
PAGES     = {"/": "xm_lines.html", "/accounts": "admin.html",
             "/setup": "setup.html", "/login": "login.html"}
STATIC_DIR = os.path.join(BASE_DIR, "static")
MIME      = {".css": "text/css", ".js": "application/javascript", ".png": "image/png", ".jpg": "image/jpeg",
             ".jpeg": "image/jpeg", ".webp": "image/webp", ".svg": "image/svg+xml", ".ico": "image/x-icon",
             ".webmanifest": "application/manifest+json", ".xml": "application/xml; charset=utf-8", ".txt": "text/plain; charset=utf-8"}
# ملفات عامة تُقدَّم من جذر الموقع (للأيقونات والأرشفة)
ROOT_FILES = {"/favicon.ico": "icons/favicon.ico", "/apple-touch-icon.png": "icons/apple-touch-icon.png",
              "/site.webmanifest": "site.webmanifest"}
PUBLIC_HTML_CACHE = "public, max-age=1800"     # كاش صفحات الموقع العامة
SESSION_TTL = 30 * 24 * 3600                          # مدة الجلسة (30 يوم)
PORT      = int(os.environ.get("XM_PORT", "8080"))
BIND      = os.environ.get("XM_BIND", "127.0.0.1")   # في الحاوية: 0.0.0.0
ADMIN_USER = "admin"                                  # اسم دخول المدير
# كلمة مرور المدير من متغيّر البيئة (يبقى عبر إعادات النشر) — يلغي صفحة الإعداد
ADMIN_ENV_PW = os.environ.get("XM_ADMIN_PASSWORD", "").strip()
DIGITS    = 12                                        # طول اليوزر والباسورد (أرقام)
# ============================================


def admin_configured(st):
    """المدير مُعدّ إمّا بكلمة مرور محفوظة أو بمتغيّر بيئة (لا صفحة إعداد حينها)."""
    return bool(st.get("admin")) or bool(ADMIN_ENV_PW)

_lock = threading.Lock()
_sessions = {}   # token -> {"role","user","exp"}


def new_session(role, user):
    for t, v in list(_sessions.items()):
        if v["exp"] < time.time():
            _sessions.pop(t, None)
    tok = secrets.token_urlsafe(32)
    _sessions[tok] = {"role": role, "user": user, "exp": time.time() + SESSION_TTL}
    return tok


# ---------------- التخزين ----------------
def load_store():
    try:
        with open(ACC_FILE, encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    st.setdefault("admin", None)
    st.setdefault("accounts", [])
    st = _crypt_store(st, crypto_store.decrypt)     # فكّ التشفير في الذاكرة
    st["service"] = normalize_service(st.get("service"))
    st["renew"] = renew.normalize_config(st.get("renew"))
    # ترقية غير مدمّرة: كل حساب قديم → شخص ببوابة واحدة.
    migrated = False
    for i, a in enumerate(st["accounts"]):
        if "gates" not in a:                        # نسخة قديمة فقط (لا وجود للمفتاح)
            st["accounts"][i] = migrate_account(a)
            migrated = True
        # ترقية أمنية: كلمة مرور دخول مخزَّنة كنص → hash لا يُسترجع.
        elif isinstance(st["accounts"][i].get("password"), str):
            st["accounts"][i]["password"] = hash_pw(st["accounts"][i]["password"])
            migrated = True
    if migrated:
        try:
            save_store(st)
        except OSError:
            pass
    return st


def save_store(st):
    os.makedirs(DATA_DIR, exist_ok=True)
    enc = _crypt_store(st, crypto_store.encrypt)    # يُكتب مشفَّرًا على القرص
    tmp = ACC_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(enc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ACC_FILE)


def hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100_000).hex()
    return {"salt": salt, "hash": h}


def check_pw(pw, rec):
    if not rec:
        return False
    return hmac.compare_digest(hash_pw(pw, rec["salt"])["hash"], rec["hash"])


def _hash_password(value, old_hash):
    """يرجّع hash لكلمة مرور الدخول. فارغ عند التعديل = يبقي القديمة."""
    if _is_hash(value):
        return value
    pw = str(value or "")
    if pw:
        if len(pw) < 4:
            raise ValueError("كلمة المرور قصيرة (4 أحرف على الأقل)")
        return hash_pw(pw)
    return old_hash if _is_hash(old_hash) else (hash_pw(old_hash) if isinstance(old_hash, str) and old_hash else None)


def _clean_digits(v):
    """طول اليوزر/الباسورد لبوابة: عدد صحيح بين 6 و20؛ الفراغ = الافتراضي العام."""
    if v in (None, ""):
        return DIGITS
    try:
        n = int(str(v).strip())
    except ValueError:
        raise ValueError("طول اليوزر والباسورد يجب أن يكون رقمًا (6 إلى 20)")
    if not 6 <= n <= 20:
        raise ValueError("طول اليوزر والباسورد يجب أن يكون بين 6 و20 رقمًا")
    return n


def gate_digits(gate):
    return int(gate.get("digits") or DIGITS)


def _clean_cost(v):
    """سعر النقطة بالريال. الفراغ يعني «غير محدَّد» لا صفرًا — فصفرٌ تكلفةٌ."""
    if v is None or str(v).strip() == "":
        return ""
    try:
        c = round(float(str(v).strip()), 3)
    except (TypeError, ValueError):
        return ""
    return "" if c < 0 or c > 10000 else c


def clean_gate(g, old=None):
    """بوابة توليد واحدة داخل حساب: لها اسمها وطريقة ربطها (api/web) وهوستها
    ورابط شرحها الخاص. لا تحذف بيانات قديمة عند التعديل."""
    old = old or {}
    mode = str(g.get("mode", "")).strip().lower() or old.get("mode", "api")
    if mode not in ("api", "web", "falcon"):
        mode = "api"
    out = {
        "id":         str(g.get("id") or old.get("id") or secrets.token_hex(4)),
        "name":       str(g.get("name", "")).strip() or old.get("name", ""),
        "mode":       mode,
        "host":       str(g.get("host", "")).strip().rstrip("/") or old.get("host", ""),
        "guide_url":  str(g.get("guide_url", old.get("guide_url", ""))).strip(),
        "panel_base": str(g.get("panel_base", "")).strip().rstrip("/") or old.get("panel_base", ""),
        "panel_user": str(g.get("panel_user", "")).strip() or old.get("panel_user", ""),
        "panel_pass": str(g.get("panel_pass", "")) or old.get("panel_pass", ""),
        "api_url":    str(g.get("api_url", "")).strip().rstrip("/") or old.get("api_url", ""),
        "api_key":    str(g.get("api_key", "")).strip() or old.get("api_key", ""),
        # طول اليوزر والباسورد المولَّدين (أرقام) — لكل بوابة رقمها: كاسبر ١٠، وغيرها ١٢ افتراضًا.
        "digits":     _clean_digits(g.get("digits", old.get("digits"))),
        # سعر النقطة بالريال عند هذا المزوّد — يكتبه صاحب الحساب، فهو وحده يعرف
        # ما اشترى به نقاطه. منه تُحسب تكلفة التجديد.
        "point_cost": _clean_cost(g.get("point_cost", old.get("point_cost"))),
    }
    if not out["name"]:
        raise ValueError("اسم البوابة مطلوب")
    # الهوست اختياري لفالكون (يُقرأ من /me)؛ إلزامي لغيرها.
    if out["host"] and not out["host"].startswith(("http://", "https://")):
        raise ValueError("هوست البوابة \"%s\" يجب أن يبدأ بـ http:// أو https://" % out["name"])
    if not out["host"] and mode != "falcon":
        raise ValueError("هوست البوابة \"%s\" مطلوب" % out["name"])
    if out["guide_url"] and not out["guide_url"].startswith(("http://", "https://")):
        raise ValueError("رابط الشرح للبوابة \"%s\" يجب أن يبدأ بـ http:// أو https://" % out["name"])
    if mode == "web":
        if not out["panel_base"].startswith(("http://", "https://")):
            raise ValueError("رابط لوحة البوابة \"%s\" يجب أن يبدأ بـ http://" % out["name"])
        if not out["panel_user"] or not out["panel_pass"]:
            raise ValueError("اسم الدخول وكلمة المرور للوحة مطلوبان للبوابة \"%s\"" % out["name"])
    else:
        if not out["api_url"].startswith(("http://", "https://")):
            raise ValueError("رابط API للبوابة \"%s\" يجب أن يبدأ بـ http://" % out["name"])
        if not out["api_key"]:
            raise ValueError("مفتاح API مطلوب للبوابة \"%s\"" % out["name"])
    return out


def clean_account(a, old=None):
    """حساب = شخص له اسم دخول وكلمة مرور للأداة، وبداخله بوابات توليد.
    كل بوابة لها ربطها الخاص (انظر clean_gate)."""
    old = old or {}
    out = {
        "id":        old.get("id") or secrets.token_hex(4),
        "name":      str(a.get("name", "")).strip() or old.get("name", ""),
        "user":      str(a.get("user", "")).strip() or old.get("user", ""),
        "password":  _hash_password(a.get("password", ""), old.get("password")),
        # رابط شرح واحد لكل بوابات الشخص (يُستعمل حين تُترك البوابة بلا رابط خاص).
        "guide_url": str(a.get("guide_url", old.get("guide_url", ""))).strip(),
    }
    if not out["name"]:
        raise ValueError("الاسم مطلوب")
    if not out["user"] or ":" in out["user"] or out["user"] == ADMIN_USER:
        raise ValueError("اسم الدخول غير صالح أو محجوز")
    if not _is_hash(out["password"]):
        raise ValueError("كلمة المرور مطلوبة")
    if out["guide_url"] and not out["guide_url"].startswith(("http://", "https://")):
        raise ValueError("رابط الشرح يجب أن يبدأ بـ http:// أو https://")

    old_gates = {g.get("id"): g for g in (old.get("gates") or [])}
    gates = []
    seen = set()
    for g in (a.get("gates") or []):
        cg = clean_gate(g, old_gates.get(str(g.get("id"))))
        if cg["id"] in seen:
            cg["id"] = secrets.token_hex(4)
        seen.add(cg["id"])
        gates.append(cg)
    # يجوز إنشاء دخول بلا بوابات — يضيفها الشخص بنفسه بعد الدخول.
    out["gates"] = gates
    return out


def migrate_account(a):
    """يحوّل حساب النسخة القديمة (لوحة واحدة على مستوى الحساب) إلى شخص ببوابة
    واحدة — دون فقد أي بيانات. وجود مفتاح gates (ولو فارغًا) = نسخة جديدة."""
    if "gates" in a:
        return a
    gate = {
        "id": secrets.token_hex(4),
        "name": a.get("name") or "البوابة",
        "mode": a.get("mode", "api"),
        "host": a.get("host", ""),
        "guide_url": "",
        "panel_base": a.get("panel_base", ""),
        "panel_user": a.get("user", ""),      # بيانات اللوحة القديمة = دخول الحساب
        "panel_pass": a.get("password", ""),
        "api_url": a.get("api_url", ""),
        "api_key": a.get("api_key", ""),
    }
    pw = a.get("password", "")
    return {
        "id": a.get("id") or secrets.token_hex(4),
        "name": a.get("name", ""),
        "user": a.get("user", ""),
        "password": pw if _is_hash(pw) else (hash_pw(str(pw)) if str(pw) else None),
        "gates": [gate],
    }


def _redact_gates(gates):
    out = copy.deepcopy(gates or [])
    for g in out:
        g["has_panel_pass"] = bool(g.get("panel_pass"))
        g["has_api_key"] = bool(g.get("api_key"))
        g["panel_pass"] = ""
        g["api_key"] = ""
    return out


def redact_account(a):
    """نسخة صالحة للإرسال للمتصفح: بلا كلمة مرور الدخول وبلا أسرار اللوحات."""
    out = copy.deepcopy(a)
    out.pop("password", None)
    out["has_password"] = bool(a.get("password"))
    out["gates"] = _redact_gates(a.get("gates", []))
    return out


def find_gate(acct, gate_id):
    if not acct:
        return None
    for g in acct.get("gates", []):
        if str(g.get("id")) == str(gate_id):
            return g
    return None


def format_line(gate, username, password):
    """السطر بالصيغة الجديدة: Host .. User .. Pass .. [Guide ..]."""
    host = str(gate.get("host", "")).strip()
    line = "Host {h} User {u} Pass {p}".format(h=host, u=username, p=password)
    guide = str(gate.get("guide_url", "")).strip()
    if guide:
        line += " Guide " + guide
    return line


# ================= خدمة سلة → واتساب (تسليم تلقائي) =================
FULFILL_FILE = os.path.join(DATA_DIR, "fulfillments.json")
POLL_INTERVAL = int(os.environ.get("SALLA_POLL_INTERVAL", "300"))
_MAX_UNITS = 10                                       # حد أقصى للتوليد في الطلب الواحد


def _now_iso():
    tz = datetime.timezone(datetime.timedelta(hours=3))   # توقيت السعودية للعرض
    return datetime.datetime.now(tz).strftime("%Y-%m-%d %H:%M")


def default_service():
    return {"enabled": False, "dry_run": True, "poll": False,
            "salla_secret": "", "salla_token": "",
            "wa": {"type": "none", "url": "", "secret": "", "token": "", "phone_id": "", "version": "v21.0"},
            "template": "اشتراكك جاهز ✅\n{line}\n\nشكرًا لطلبك 🌟",
            "map": []}


def _clean_map_row(m):
    return {"product_id": str(m.get("product_id", "")).strip(),
            "account_id": str(m.get("account_id", "")).strip(),
            "gate_id": str(m.get("gate_id", "")).strip(),
            "package_id": str(m.get("package_id", "")).strip(),
            "package_name": str(m.get("package_name", "")).strip()}


def normalize_service(svc):
    d = default_service()
    if isinstance(svc, dict):
        for k in ("enabled", "dry_run", "poll"):
            d[k] = bool(svc.get(k, d[k]))
        for k in ("salla_secret", "salla_token", "template"):
            d[k] = str(svc.get(k, d[k]) or "")
        wa = svc.get("wa") if isinstance(svc.get("wa"), dict) else {}
        for k in d["wa"]:
            d["wa"][k] = str(wa.get(k, d["wa"][k]) or "")
        d["wa"]["type"] = (d["wa"]["type"] or "none").lower()
        d["map"] = [_clean_map_row(m) for m in (svc.get("map") or []) if isinstance(m, dict)]
    return d


def clean_service(cfg, old):
    """يبني إعداد الخدمة ويُبقي الأسرار عند تركها فارغة (كالبوابات)."""
    old = normalize_service(old)
    out = normalize_service(cfg)
    for k in _SENSITIVE_SVC:
        if not out[k]:
            out[k] = old[k]
    for k in _SENSITIVE_WA:
        if not out["wa"][k]:
            out["wa"][k] = old["wa"][k]
    return out


def redact_service(cfg):
    """نسخة صالحة للمتصفح: بلا أسرار، مع أعلام has_*."""
    c = normalize_service(cfg)
    return {"enabled": c["enabled"], "dry_run": c["dry_run"], "poll": c["poll"],
            "template": c["template"], "map": c["map"],
            "has_salla_secret": bool(c["salla_secret"]), "has_salla_token": bool(c["salla_token"]),
            "wa": {"type": c["wa"]["type"], "url": c["wa"]["url"], "phone_id": c["wa"]["phone_id"],
                   "version": c["wa"]["version"], "has_token": bool(c["wa"]["token"]),
                   "has_secret": bool(c["wa"]["secret"])}}


def load_fulfillments():
    try:
        with open(FULFILL_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_fulfillments(d):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = FULFILL_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, FULFILL_FILE)


def _find_account(st, account_id):
    return next((a for a in st["accounts"] if str(a.get("id")) == str(account_id)), None)


def _gen_for_map(st, m, simulate):
    """يولّد سطر اشتراك لصفّ ربط واحد. simulate=True: سطر تجريبي بلا لمس اللوحة."""
    acct = _find_account(st, m["account_id"])
    gate = find_gate(acct, m["gate_id"]) if acct else None
    if not gate:
        return {"ok": False, "error": "بوابة الربط غير موجودة (عدّل الربط)"}
    g = gate
    if not g.get("guide_url") and acct.get("guide_url"):
        g = {**g, "guide_url": acct["guide_url"]}
    if simulate:
        return {"ok": True, "line": format_line(g, "TEST-USER", "TEST-PASS"),
                "username": "TEST-USER", "password": "TEST-PASS", "simulated": True}
    pkg = {"id": m["package_id"], "name": m["package_name"] or ("باقة " + m["package_id"])}
    r = create_line(g, pkg)
    return {"ok": True, "line": r["line"], "username": r["username"],
            "password": r["password"], "verified": r.get("verified", True)}


def _wa_base(wa):
    """أصل خدمة واتساب من رابط الإرسال (يحذف /send الأخير)."""
    u = str((wa or {}).get("url", "")).strip()
    if u.endswith("/send"):
        u = u[:-5]
    return u.rstrip("/")


def build_message(template, line, name):
    t = template or default_service()["template"]
    return t.replace("{line}", line).replace("{lines}", line).replace("{name}", name or "")


def fulfill_order(st, order, source="webhook", force=False):
    """يولّد الاشتراك(ات) للطلب ويرسلها على واتساب، محترمًا enabled/dry_run والتكرار."""
    svc = st["service"]
    oid = order.get("order_id") or ""
    res = {"order_id": oid, "reference": order.get("reference", ""), "source": source,
           "at": _now_iso(), "phone": order.get("phone", ""),
           "name": order.get("customer_name", ""), "lines": [], "status": "ignored"}
    if not svc.get("enabled"):
        res["status"] = "disabled"; return res
    if not salla_api.is_paid(order):
        res["status"] = "unpaid"; return res
    fulfilled = load_fulfillments()
    prev = fulfilled.get(oid)
    if prev and prev.get("status") in ("sent", "dry") and not force:
        return {**prev, "skipped": "already"}
    matched = [(item, m) for item in order.get("items", [])
               for m in svc.get("map", []) if m["product_id"] and m["product_id"] == item["product_id"]]
    if not matched:
        res["status"] = "no_match"; fulfilled[oid] = res; save_fulfillments(fulfilled); return res
    if not order.get("phone"):
        res["status"] = "no_phone"; fulfilled[oid] = res; save_fulfillments(fulfilled); return res
    simulate = bool(svc.get("dry_run"))
    wa_cfg = {"type": "none"} if simulate else svc.get("wa", {})
    any_ok = any_fail = False
    for item, m in matched:
        for _ in range(min(int(item.get("quantity", 1) or 1), _MAX_UNITS)):
            try:
                g = _gen_for_map(st, m, simulate)
            except xm_web.CaptchaNeeded:
                g = {"ok": False, "error": "بوابة الويب تحتاج كود تحقّق — سجّل الدخول لها من صفحة الإنشاء أولًا"}
            except Exception as e:
                g = {"ok": False, "error": str(e)[:200]}
            row = {"product_id": m["product_id"], "product": item.get("name", "")}
            if not g.get("ok"):
                row["error"] = g.get("error"); any_fail = True; res["lines"].append(row); continue
            msg = build_message(svc.get("template"), g["line"], order.get("customer_name", ""))
            wr = wa_send.send(wa_cfg, order["phone"], msg)
            row.update({"line": g["line"], "wa": wr, "simulated": g.get("simulated", False)})
            any_ok = any_ok or bool(wr.get("ok")); any_fail = any_fail or not wr.get("ok")
            res["lines"].append(row)
    res["status"] = ("dry" if simulate else
                     ("sent" if any_ok and not any_fail else ("partial" if any_ok else "failed")))
    fulfilled[oid] = res; save_fulfillments(fulfilled)
    return res


def _poll_loop():
    while True:
        time.sleep(POLL_INTERVAL)
        try:
            with _lock:
                st = load_store()
                svc = st["service"]
                if not (svc.get("enabled") and svc.get("poll") and svc.get("salla_token")):
                    continue
                fulfilled = load_fulfillments()
                for o in salla_api.fetch_orders(svc["salla_token"], per_page=25, page=1):
                    if o.get("order_id") and o["order_id"] not in fulfilled:
                        fulfill_order(st, o, source="poll")
        except Exception:
            pass


def start_poller():
    threading.Thread(target=_poll_loop, daemon=True).start()

# ================= تجديد الاشتراك على مرح =================
# `renew.py` يحمل القاعدة والطابور والتنبيه ولا يعرف شيئًا عن اللوحات؛ وهذا
# القسم هو الجسر: يسأل اللوحة ويُنشئ عليها، فيبقى الملفان قابلين للاختبار وحدهما.

def renew_exists(gate, username):
    """أهذا اليوزر موجود على اللوحة؟ هذا هو الحارس ضدّ الإنشاء مرتين: إنشاءٌ نجح
    وضاع ردّه يُكتشف هنا فلا يُعاد. الشكّ يُرفع استثناءً لا يُبتلع — أن نُبقي
    الطلب معلّقًا أهون من أن نُنشئ خطًّا ثانيًا بنفس اليوزر."""
    u = str(username or "").strip()
    if not u:
        return False
    mode = gate.get("mode")
    if mode == "web":
        rows = web_session(gate).search(u)
    elif mode == "falcon":
        rows = falcon_api.search(gate["api_url"], gate["api_key"], u)
    else:
        r = api(gate, "get_line", {"username": u})
        rows = _unwrap(r) if isinstance(r, (list, dict)) else []
    return any(str(x.get("username", "")).strip() == u for x in rows if isinstance(x, dict))


def renew_packages(st):
    """باقات بوابة مرح كما تسمّيها اللوحة، ومعها نقاطها ومدتها.

    النقاط مكتوبة في الاسم نفسه («اشتراك سنة + جهازين (6 نقاط)») فتُقرأ منه ولا
    تُخمَّن — وهي ليست حاصل ضرب: السنة بأربع نقاط، والسنة بجهازين بستٍّ لا بثمانٍ."""
    cfg = renew.normalize_config(st.get("renew"))
    acct = next((a for a in st["accounts"]
                 if str(a.get("id")) == str(cfg["target"]["account_id"])), None)
    gate = find_gate(acct, cfg["target"]["gate_id"]) if acct else None
    ok, why = renew.gate_allowed(gate)
    if not ok:
        raise RuntimeError(why if gate else "بوابة مرح غير مضبوطة في إعداد التجديد")
    out = []
    for p in get_packages(gate):
        info = parse_package_name(p.get("name", ""))
        credits = p.get("credits")
        if credits in (None, "") and info["credits"]:
            credits = info["credits"]
        out.append({"id": str(p.get("id")), "name": p.get("name", ""),
                    "months": info["months"], "devices": info["devices"],
                    "credits": credits, "virtual": bool(p.get("virtual"))})
    return out, (gate.get("point_cost") if gate else "")



# ---- السحب المباشر من سلة (خلفيّ، لأنه يطول) ----
_pull = {"running": False, "phase": "", "done": 0, "total": 0, "units": 0,
         "found": 0, "error": "", "at": "", "cancel": False, "applied": False}


def renew_salla_token(st):
    return (st.get("service") or {}).get("salla_token") or ""


def _pull_worker(token, with_history, apply_index):
    def progress(d):
        _pull.update(d)

    try:
        st = load_store()
        units, meta = renew_import.pull_from_salla(
            token, progress=progress, with_history=with_history,
            stop=lambda: _pull["cancel"],
            credentials_for=lambda sid, url: renew_credentials_for(st, sid, url))
        if not units:
            _pull["error"] = "لم يرجع أي طلب صالح من سلة"
            return
        agg = renew_import.analyze(units, meta)
        renew.save_analysis(DATA_DIR, agg)
        if apply_index:
            renew.save_index(DATA_DIR, renew_import.build_index(units, meta))
            _pull["applied"] = True
        _pull.update({"units": len(units), "found": meta.get("with_credentials", 0),
                      "phase": "done", "session_expired": meta.get("session_expired", False)})
        if meta.get("session_expired"):
            # التحقّق الثنائي في سلة إلزاميّ، فلا تُجدَّد الجلسة إلا بيد المشغّل.
            renew.alert_session_expired(DATA_DIR, st.get("renew"))
    except Exception as e:
        _pull["error"] = str(e)[:300]
    finally:
        _pull["running"] = False
        _pull["at"] = renew.now_iso()


def start_renew_pull(st, with_history=True, apply_index=True):
    if _pull["running"]:
        return {"ok": False, "error": "سحبٌ جارٍ بالفعل"}
    token = renew_salla_token(st)
    if not token:
        return {"ok": False, "error": "رمز سلة غير مضبوط — اضبطه في إعداد خدمة سلة"}
    _pull.update({"running": True, "phase": "orders", "done": 0, "total": 0,
                  "units": 0, "found": 0, "error": "", "cancel": False,
                  "applied": False, "session_expired": False})
    threading.Thread(target=_pull_worker, args=(token, with_history, apply_index),
                     daemon=True).start()
    return {"ok": True}



# ---- تصدير خطوط اللوحة (خلفيّ) ----
_lines_job = {"running": False, "done": 0, "total": 0, "error": "", "at": "", "cancel": False}


def _lines_worker(gate, chunk=500):
    try:
        sess = web_session(gate)
        rows, seen, page = [], set(), 0
        while True:
            if _lines_job["cancel"]:
                break
            got = sess.search("", limit=chunk * (page + 1))
            fresh = [r for r in got if r.get("username") and r["username"] not in seen]
            for r in fresh:
                seen.add(r["username"])
            rows += fresh
            _lines_job.update({"done": len(rows), "total": len(rows)})
            if len(fresh) == 0 or len(got) < chunk * (page + 1):
                break
            page += 1
            if page > 40:                      # سقفٌ يمنع دورانًا بلا نهاية
                break
        n = renew.save_lines(DATA_DIR, rows, gate.get("name", ""), gate.get("host", ""))
        _lines_job.update({"done": n, "total": n})
    except xm_web.CaptchaNeeded:
        _lines_job["error"] = "اللوحة تطلب كود تحقّق — سجّل الدخول لها من صفحة الإنشاء"
    except Exception as e:
        _lines_job["error"] = str(e)[:300]
    finally:
        _lines_job["running"] = False
        _lines_job["at"] = renew.now_iso()


def start_lines_export(st, side="source"):
    if _lines_job["running"]:
        return {"ok": False, "error": "تصديرٌ جارٍ بالفعل"}
    cfg = renew.normalize_config(st.get("renew"))
    acct = next((a for a in st["accounts"]
                 if str(a.get("id")) == str(cfg[side]["account_id"])), None)
    gate = find_gate(acct, cfg[side]["gate_id"]) if acct else None
    ok, why = renew.gate_allowed(gate)
    if not ok:
        return {"ok": False, "error": why if gate else "البوابة غير مضبوطة"}
    if gate.get("mode") != "web":
        return {"ok": False, "error": "التصدير الكامل متاح على بوابات جلسة الويب"}
    _lines_job.update({"running": True, "done": 0, "total": 0, "error": "", "cancel": False})
    threading.Thread(target=_lines_worker, args=(gate,), daemon=True).start()
    return {"ok": True}



def renew_panel_session(st):
    """جلسة لوحة سلة من الكوكيز الملصوقة، أو None إن لم تُلصق."""
    cookie = renew.normalize_config(st.get("renew")).get("panel_cookie") or ""
    if not cookie:
        return None
    try:
        return salla_web.Session(cookie)
    except salla_web.WebError:
        return None


def renew_credentials_for(st, sid, admin_url=""):
    """اعتماد طلبٍ واحد من مصادره بالترتيب: سجلّ الطلب، ثم بطاقته من الواجهة،
    ثم لوحةُ سلة بجلسة المتصفّح — وهذه الأخيرة لا تُسأل إلا في الحصاد، لأن
    `admin_url` لا يُمرَّر إلا منه: جلستها تنتهي خلال ساعات، فلا يُعلَّق عليها
    عميلٌ ينتظر."""
    token = renew_salla_token(st)
    if token and sid:
        try:
            notes = salla_api.history_notes(token, sid)
            got = renew_import.parse_credentials(notes)
            if got:
                return got, "history"
            if salla_api.code_ids_from_notes(notes):
                got = renew_import.parse_credentials(salla_api.order_code_text(token, sid))
                if got:
                    return got, "card"
        except Exception:
            pass
    sess = renew_panel_session(st)
    tok = salla_web.admin_token(admin_url)
    if sess and tok:
        try:
            got = renew_import.parse_credentials(sess.order_text(tok))
            if got:
                return got, "panel"
        except salla_web.SessionExpired:
            return {}, "session_expired"
        except Exception:
            pass
    return {}, ""



# ---- الحصاد: نافذة الجلسة القصيرة تُستنفد جمعًا ----
_harvest = {"running": False, "done": 0, "total": 0, "found": 0, "error": "",
            "at": "", "cancel": False, "expired": False, "merged": 0,
            "counts": {}, "scope": {}}
HARVEST_WORKERS = int(os.environ.get("RENEW_HARVEST_WORKERS", "6"))
_HARVEST_BATCH = 25                      # كل كم سجلًّا يُكتب القرص


def _harvest_worker(st, sids):
    """يستنزف المعلّق بخيوط متوازية. أول انتهاءٍ للجلسة يوقف الجولة: البقية
    ستنتهي مثلها، والاستمرار يحرق المعلّق تعليمًا بلا فائدة."""
    import queue
    q = queue.Queue()
    for sid, url in sids:
        q.put((sid, url))
    buf, lock = [], threading.Lock()
    stop = threading.Event()

    def flush(force=False):
        with lock:
            if not buf or (len(buf) < _HARVEST_BATCH and not force):
                return
            rows, buf[:] = list(buf), []
        _harvest["found"] = renew.harvest_record(DATA_DIR, rows)

    def run():
        while not stop.is_set() and not _harvest["cancel"]:
            try:
                sid, url = q.get_nowait()
            except queue.Empty:
                return
            try:
                cred, why = renew_credentials_for(st, sid, url)
            except Exception:
                cred, why = {}, ""
            if why == "session_expired":
                _harvest["expired"] = True
                stop.set()
                return                      # لا يُعلَّم: تُعاد محاولته بجلسة جديدة
            with lock:
                buf.append((sid, cred))
            _harvest["done"] += 1
            flush()

    threads = [threading.Thread(target=run, daemon=True) for _ in range(HARVEST_WORKERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    flush(force=True)


def _harvest_main(scope):
    try:
        st = load_store()
        rows, counts = renew.harvest_scope(DATA_DIR, **scope)
        todo = [(r["sid"], r["admin_url"]) for r in rows]
        _harvest.update({"total": len(todo), "done": 0, "counts": counts,
                         "scope": scope})
        if not todo:
            _harvest["merged"] = renew.harvest_into_index(DATA_DIR)
            return
        _harvest_worker(st, todo)
        _harvest["merged"] = renew.harvest_into_index(DATA_DIR)
        if _harvest["expired"]:
            renew.alert_session_expired(DATA_DIR, st.get("renew"))
    except Exception as e:
        _harvest["error"] = str(e)[:300]
    finally:
        _harvest["running"] = False
        _harvest["at"] = renew.now_iso()


def harvest_scope_args(req):
    """نطاق الحصاد كما يطلبه المدير: من تاريخ، إلى تاريخ، وأنُسقط المنتهي."""
    return {"from_date": str(req.get("from_date", "") or "").strip(),
            "to_date": str(req.get("to_date", "") or "").strip(),
            "active_only": bool(req.get("active_only", True))}


def start_harvest(st, scope=None):
    if _harvest["running"]:
        return {"ok": False, "error": "حصادٌ جارٍ بالفعل"}
    if not renew.load_index(DATA_DIR).get("orders"):
        return {"ok": False, "error": "لا فهرس بعد — اسحب من سلة أو ارفع الملفات أولًا"}
    scope = scope or {}
    _rows, counts = renew.harvest_scope(DATA_DIR, **scope)
    if not counts["pending"]:
        return {"ok": False, "error": "لا طلب في هذا النطاق يحتاج حصادًا", "counts": counts}
    _harvest.update({"running": True, "done": 0, "total": counts["pending"], "error": "",
                     "cancel": False, "expired": False, "merged": 0, "counts": counts})
    threading.Thread(target=_harvest_main, args=(scope,), daemon=True).start()
    return {"ok": True, "counts": counts}


def renew_prov():
    return renew.Provisioner(renew_exists, create_line, find_gate)


def renew_source_gate(st):
    cfg = st.get("renew") or {}
    acct = next((a for a in st["accounts"]
                 if str(a.get("id")) == str((cfg.get("source") or {}).get("account_id"))), None)
    return find_gate(acct, (cfg.get("source") or {}).get("gate_id")) if acct else None


def renew_lookup(st, order_no="", phone="", username="", password=""):
    """يتعرّف على العميل ويحسب ما يستحقّه، بلا إنشاء ولا تسجيل.

    مدخلان مقبولان (كما في المواصفة): رقم الطلب مع الجوال، أو يوزر الاشتراك.
      • **الطلب والجوال** يثبتان الاستحقاق: الفهرس يعطي تاريخ الشراء ومدة الباقة.
      • **اليوزر** يعطي الهوية التي نُبقيها كما هي على مرح.

    وتبقى كلمة المرور: ملفات سلة لا تحملها. تُقرأ من اللوحة القديمة إن كانت
    مضبوطة وحيّة، وإلا **يكتبها العميل** من رسالة اشتراكه — وهذا ليس حالة
    نادرة: اللوحة القديمة قد تكون هي سببَ النقل أصلًا."""
    cfg = renew.normalize_config(st.get("renew"))
    out = {"ok": False}
    order_no, phone = renew.norm_order(order_no), renew.norm_phone(phone)
    username, password = str(username or "").strip(), str(password or "").strip()

    plan = None
    if order_no:
        if not phone:
            return {"ok": False, "error": "اكتب رقم الجوال المسجَّل في الطلب"}
        rec = renew.find_order(DATA_DIR, order_no, phone)
        if not rec:
            return {"ok": False, "error": "لم نجد طلبًا بهذا الرقم والجوال معًا. "
                                          "تأكّد من رقم الطلب، والجوال كما كتبته وقت الشراء."}
        plan = renew.plan_from_order(rec)
        out["devices"] = int(rec.get("devices") or 1)
        # اعتمادٌ كُتب يدويًا في الطلب ونُقل إلى الفهرس: يُعفي العميل من كتابته.
        username = username or str(rec.get("username", "") or "")
        password = password or str(rec.get("password", "") or "")
        if not (username and password) and rec.get("sid"):
            # المحصود أولًا — قرصٌ لا شبكة، فلا يعتمد العميل على جلسةٍ قد ماتت.
            got = renew.load_harvest(DATA_DIR)["found"].get(str(rec["sid"])) or {}
            if not got and renew_salla_token(st):
                # لم يُحصد بعد: محاولةٌ واحدة الآن تُغني العميل عن الكتابة. ولا
                # تُسأل لوحةُ سلة هنا — جلستها قصيرة وبطيئة، وموضعها الحصاد.
                got, _why = renew_credentials_for(st, rec["sid"], "")
                if got:
                    renew.harvest_record(DATA_DIR, [(rec["sid"], got)])
            username = username or got.get("username", "")
            password = password or got.get("password", "")
            if got.get("host"):
                out["old_host"] = got["host"]
        if rec.get("host"):
            out["old_host"] = rec["host"]

    # اللوحة القديمة إن أمكن — لا تُوقف التدفّق إن غابت أو سقطت.
    found, panel_down = {}, False
    if username:
        # التصدير المحفوظ أولًا: يوزرٌ وباسوردٌ بلا شبكة ولا انتظار.
        saved = renew.find_line(DATA_DIR, username)
        if saved:
            found = {"username": saved["username"], "password": saved["password"],
                     "exp": saved.get("exp", ""), "connections": saved.get("connections", "")}
        gate = renew_source_gate(st)
        if not found and gate and renew.gate_allowed(gate)[0]:
            try:
                found = next((r for r in web_session(gate).search(username)
                              if str(r.get("username", "")).strip() == username), {})
            except Exception:
                panel_down = True
        if found.get("password"):
            password = password or found["password"]
        if not plan and found:
            plan = renew.plan_from_expiry(renew.parse_date(found.get("exp")))
            if str(found.get("connections", "")).isdigit():
                out["devices"] = max(1, int(found["connections"]))

    if not plan:
        if username and (panel_down or not renew_source_gate(st)):
            # لا فهرس ولا لوحة: لا سبيل لمعرفة ما يستحقّه
            return {"ok": False, "error": "اكتب رقم طلبك ورقم جوالك — بهما نعرف ما تبقّى لك."}
        if username:
            return {"ok": False, "error": "لم نجد يوزرًا بهذا الاسم. "
                                          "انسخه كما هو، أو استخدم رقم طلبك وجوالك."}
        return {"ok": False, "error": "اكتب رقم الطلب مع الجوال، أو يوزر اشتراكك"}
    if plan.get("expired"):
        return {"ok": False, "expired": True, "expiry": plan.get("expiry", ""),
                "error": "اشتراكك منتهٍ — التجديد هنا لمن بقيت له مدة. تفضّل بالشراء من المتجر."}

    key = renew.claim_key(order_no, username)
    prev = renew.load_db(DATA_DIR)["claims"].get(key) if key else None
    out.update({"ok": True, "plan": plan, "username": username, "password": password,
                "need_username": not username,
                "need_password": bool(username) and not password,
                "panel_down": panel_down,
                "claimed": renew.public_view(prev, cfg["promise_hours"]) if prev else None})
    return out


def renew_run_queue(st=None):
    st = st or load_store()
    return renew.run_queue(DATA_DIR, st, st.get("renew"), renew_prov())


def _renew_loop():
    """يعيد المحاولة دوريًا: ما إن يعود الوصل بمرح حتى تُنشأ المعلّقات تباعًا."""
    while True:
        try:
            st = load_store()
            cfg = renew.normalize_config(st.get("renew"))
            time.sleep(max(60, int(cfg["retry_minutes"]) * 60))
            if not cfg.get("enabled") or not renew.pending(DATA_DIR):
                continue
            with _lock:
                renew_run_queue(load_store())
        except Exception:
            time.sleep(300)


def start_renew_worker():
    threading.Thread(target=_renew_loop, daemon=True).start()




# ---------------- API الريسيلر ----------------
def api(acct, action, params=None, post=False):
    q = {"api_key": acct["api_key"], "action": action}
    body = None
    if post:
        body = urlencode(params or {}, doseq=True).encode()
    else:
        q.update(params or {})
    url = acct["api_url"] + "?" + urlencode(q, doseq=True)
    req = Request(url, data=body, headers={"User-Agent": "Mozilla/5.0",
              "Content-Type": "application/x-www-form-urlencoded"})
    with urlopen(req, timeout=30) as r:
        raw = r.read().decode("utf-8", "replace")
    try:
        return json.loads(raw)
    except ValueError:
        raise RuntimeError("رد غير JSON من السيرفر: " + raw[:300])


def _unwrap(r):
    if isinstance(r, dict):
        for k in ("data", "packages", "result", "items"):
            if k in r and isinstance(r[k], (list, dict)):
                r = r[k]
                break
    if isinstance(r, dict):
        r = list(r.values())
    return r if isinstance(r, list) else []


def _ids(v):
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            v = [x for x in v.replace("[", "").replace("]", "").split(",") if x.strip()]
    return [int(x) for x in (v or []) if str(x).strip().isdigit()]


def web_session(gate):
    """جلسة ويب لبوابة واحدة، بكوكيز مستقلة على القرص لكل بوابة."""
    return xm_web.PanelWebSession({
        "id": "gate_" + str(gate.get("id", "")),
        "user": gate.get("panel_user", ""),
        "password": gate.get("panel_pass", ""),
        "panel_base": gate.get("panel_base", ""),
        "host": gate.get("host", ""),
    }, DATA_DIR)


# ================= باقات افتراضية: إنشاء + تمديد (مرح) =================
# باقة لا توجد في اللوحة تُصنع من باقة حقيقية: يُنشأ اليوزر بالباقة الأساسية ثم
# يُمدَّد بها نفسها (ExtendUser) فتتضاعف مدته — كما يفعل سكربت السيلينيوم المثبت.
# القاعدة الحالية: كل باقة مدتها ١٥ شهرًا (سنة + ٣ أشهر) تُولّد باقة «٣٠ شهر».
VIRTUAL_PREFIX = "x2:"                                # معرّف الباقة الافتراضية: x2:<معرّف الأساس>
DOUBLE_MONTHS = (15,)                                 # مدد الأساس التي تُضاعَف
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def _first_int(part, default=None):
    m = re.search(r"\d+", part)
    return int(m.group()) if m else default


def parse_package_name(text):
    """يفهم اسم الباقة (عربيًا أو إنجليزيًا) → {months, devices, credits}.
    'اشتراك سنة + 3 اشهر + جهازين (6 نقاط)' → months=15 devices=2 credits=6
    '1 Year + 3 Months (6 credits)'          → months=15 devices=1 credits=6"""
    s = str(text or "").translate(_AR_DIGITS)
    main, _, paren = s.partition("(")
    months, devices = 0, 1
    for part in re.split(r"[+،,]", main):
        low = part.lower()
        if "جهازين" in part:
            devices = 2
        elif re.search(r"جهاز|اجهزة|أجهزة|device|connection", low):
            devices = _first_int(part, devices)
        elif "سنتين" in part:
            months += 24
        elif re.search(r"سن[ةه]|سنوات|year", low):
            months += 12 * (_first_int(part, 1) or 1)
        elif "شهرين" in part:
            months += 2
        elif re.search(r"شهر|اشهر|أشهر|شهور|month", low):
            months += _first_int(part, 1) or 1
    credits = None
    if paren:
        credits = 2 if "نقطتين" in paren else _first_int(paren, 1 if re.search(r"نقط[ةه]", paren) else None)
    return {"months": months, "devices": devices, "credits": credits}


def package_label(name="", months=None, devices=None):
    """تسمية قصيرة لنوع الباقة: 'اشتراك سنة + 3 اشهر + جهازين (12 نقطة)' → '15 شهر جهازين'."""
    if months is None or devices is None:
        info = parse_package_name(name)
        months = info["months"] if months is None else months
        devices = info["devices"] if devices is None else devices
    if not months:
        return re.sub(r"\s*\(.*?\)\s*", " ", str(name or "")).strip()
    m = {1: "شهر", 2: "شهرين", 12: "سنة", 24: "سنتين"}.get(months) or "%d شهر" % months
    d = "" if not devices or devices < 2 else ("جهازين" if devices == 2 else "%d أجهزة" % devices)
    return (m + " " + d).strip()


def _parse_date(s):
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.datetime.strptime(str(s).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _logged_package(gate, username):
    """اسم الباقة لليوزر كما سُجّل في lines.txt عند إنشائه من الأداة (أحدث سطر له)."""
    try:
        with open(TXT_FILE, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return ""
    needle = " User %s " % username
    for ln in reversed(lines):
        if needle in ln and ("|  %s  |" % gate.get("name", "")) in ln:
            parts = [x.strip() for x in ln.split("|")]
            if len(parts) >= 4:
                return re.sub(r"\s*\[.*?\]\s*$", "", parts[3])
    return ""


def annotate_package_type(gate, rows, pkgs=None):
    """يضيف لكل صف من جدول اللوحة نوع باقته ('15 شهر جهازين'): من سجل الأداة إن أنشأناه
    نحن، وإلا من اسم الباقة إن ظهر في الصف، وإلا يُستنتج من الأجهزة ومدة الاشتراك
    (تاريخ الإنشاء ↔ الانتهاء)."""
    names = [p.get("name", "") for p in (pkgs or []) if p.get("name")]
    for r in rows:
        name = _logged_package(gate, r.get("username", "")) or r.get("package", "")
        if not name and names:
            text = r.get("text", "")
            name = next((n for n in sorted(names, key=len, reverse=True) if n and n in text), "")
        months, devices = None, None
        if name:
            info = parse_package_name(name)
            months, devices = info["months"], info["devices"]
        conns = str(r.get("connections") or "")
        if conns.isdigit() and int(conns) > 0:
            devices = int(conns)
        if not months:
            end = _parse_date(r.get("exp", ""))
            start = _parse_date(r.get("created", ""))
            if end and not start:
                ds = [d for d in (_parse_date(x) for x in r.get("dates", [])) if d and d < end]
                start = min(ds) if ds else None
            if end and start:
                months = int(round((end - start).days / 30.4375))
        r["package_name"] = name
        r["package_type"] = package_label(name, months, devices or 1) if (months or name) else ""
        for k in ("dates", "text"):
            r.pop(k, None)
    return rows


def virtual_base(pkg_id):
    """معرّف الباقة الافتراضية 'x2:15' → ('15', عدد مرات التمديد)؛ وإلا None."""
    pid = str(pkg_id or "")
    if not pid.startswith(VIRTUAL_PREFIX):
        return None
    return pid[len(VIRTUAL_PREFIX):], 1


def virtual_packages(pkgs):
    """الباقات الافتراضية المشتقة من قائمة باقات اللوحة (بنفس شكل عناصرها)."""
    out = []
    for p in pkgs:
        info = parse_package_name(p.get("name", ""))
        if info["months"] not in DOUBLE_MONTHS:
            continue
        name = "اشتراك %d شهر" % (info["months"] * 2)
        if info["devices"] == 2:
            name += " + جهازين"
        elif info["devices"] > 2:
            name += " + %d أجهزة" % info["devices"]
        if info["credits"]:
            name += " (%d نقاط)" % (info["credits"] * 2)
        out.append({"id": VIRTUAL_PREFIX + str(p["id"]), "name": name, "credits": p.get("credits"),
                    "max_connections": p.get("max_connections", 1), "bouquets": [],
                    "virtual": True, "base_id": str(p["id"]), "base_name": p.get("name", ""),
                    "hint": "إنشاء بباقة %d شهر ثم تمديدها مرة" % info["months"]})
    return out


def get_packages(gate):
    if gate.get("mode") == "web":                      # جلسة ويب بدل الـ API
        sess = web_session(gate)
        pkgs = [{"id": p["value"], "name": p["text"], "credits": None,
                 "max_connections": 1, "bouquets": []}
                for p in sess.packages()]
        # الباقات الافتراضية (إنشاء + تمديد) فقط حين للوحة نافذة تمديد (مرح)، لا على
        # لوحة بلا تمديد (كاسبر) حيث سينتهي الأمر بيوزر بالمدة الأساسية فقط.
        virt = virtual_packages(pkgs)
        if virt and sess.supports_extend():
            pkgs += virt
        return pkgs
    if gate.get("mode") == "falcon":                   # لوحة فالكون (Bearer)
        return falcon_api.packages(gate["api_url"], gate["api_key"])
    pkgs = []
    for p in _unwrap(api(gate, "get_packages")):
        if not isinstance(p, dict):
            continue
        if str(p.get("is_line", "1")) == "0":      # نعرض باقات M3U Lines فقط
            continue
        pkgs.append({
            "id": p.get("id"),
            "name": p.get("package_name") or p.get("name") or f"باقة {p.get('id')}",
            "credits": p.get("official_credits", p.get("credits")),
            "max_connections": p.get("max_connections", 1),
            "bouquets": _ids(p.get("bouquets")),     # كل الـ Subscribed
        })
    return pkgs


def rand_digits(n=DIGITS):
    return str(secrets.randbelow(9) + 1) + "".join(str(secrets.randbelow(10)) for _ in range(n - 1))


def _log_txt(gate, line, pkg_name):
    now = datetime.datetime.now()
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(TXT_FILE, "a", encoding="utf-8") as f:
            f.write(f"{now:%d-%m-%Y %H:%M}  |  {gate.get('name','')}  |  {line}  |  {pkg_name}\n")
    except OSError:
        pass
    return now


def create_line(gate, pkg, username=None, password=None):
    # اليوزر والباسورد يُولَّدان هنا — من جهتنا لا من اللوحة — بطول البوابة نفسها،
    # فلا يعتمد الطول على المزوّد (فالكون/جلسة ويب/API) ولا على ما تولّده لوحته.
    username = username or rand_digits(gate_digits(gate))
    password = password or rand_digits(gate_digits(gate))
    vb = virtual_base(pkg["id"])
    if vb and gate.get("mode") == "web":              # باقة افتراضية: إنشاء بالأساس ثم تمديد
        return _create_extended(gate, pkg, vb[0], vb[1], username, password)
    if vb:
        raise RuntimeError("الباقة «%s» (إنشاء + تمديد) متاحة على جلسة الويب فقط" % pkg["name"])
    if gate.get("mode") == "web":                      # الإنشاء عبر نموذج اللوحة
        r = web_session(gate).create_line(pkg["id"], username, password, gate.get("host"))
        line = format_line(gate, r["username"], r["password"])
        _log_txt(gate, line, pkg["name"])
        return {"line": line, "username": r["username"], "password": r["password"],
                "package": pkg["name"], "verified": r.get("verified", True), "time": r["time"],
                "timing": r.get("timing")}
    if gate.get("mode") == "falcon":                   # الإنشاء عبر لوحة فالكون
        r = falcon_api.create_line(gate["api_url"], gate["api_key"], pkg["id"],
                                   username, password, pkg.get("max_connections"))
        g2 = dict(gate)
        if not g2.get("host"):
            g2["host"] = falcon_api.host(gate["api_url"], gate["api_key"])
        line = format_line(g2, r["username"], r["password"])
        _log_txt(g2, line, pkg["name"])
        return {"line": line, "username": r["username"], "password": r["password"],
                "package": pkg["name"], "verified": True,
                "time": datetime.datetime.now().isoformat(timespec="seconds")}
    # وضع الـ API
    params = {
        "username": username,
        "password": password,
        "package": pkg["id"],
        "max_connections": pkg.get("max_connections") or 1,
        "bouquets_selected[]": pkg["bouquets"],  # اختيار كل Subscribed
    }
    r = api(gate, "create_line", params, post=True)
    ok = isinstance(r, dict) and (
        r.get("status") in ("STATUS_SUCCESS", "success", True) or r.get("result") is True)
    if not ok:
        raise RuntimeError("فشل الإنشاء: " + json.dumps(r, ensure_ascii=False)[:400])
    data = r.get("data") if isinstance(r.get("data"), dict) else {}
    username = data.get("username", username)
    password = data.get("password", password)
    line = format_line(gate, username, password)
    now = _log_txt(gate, line, pkg["name"])
    return {"line": line, "username": username, "password": password,
            "package": pkg["name"], "verified": True, "time": now.isoformat(timespec="seconds")}


def _create_extended(gate, pkg, base_id, times, username, password):
    """يوزر بباقة افتراضية: يُنشأ بالباقة الأساسية ثم يُمدَّد بها `times` مرة.
    فشل التمديد بعد الإنشاء لا يُخفي اليوزر: يُسجَّل في lines.txt بملاحظة واضحة
    ويُرفع خطأ يحمل بياناته (خُصم رصيده فلا يضيع)."""
    sess = web_session(gate)
    r = sess.create_line(base_id, username, password, gate.get("host"))
    u, p = r["username"], r["password"]
    ends = []
    try:
        for _ in range(times):
            ends.append(sess.extend_line(u, base_id, pkg.get("base_name", ""), line_id=r.get("line_id", "")))
    except (xm_web.CaptchaNeeded, xm_web.LoginFailed):
        raise
    except Exception as e:
        base_name = pkg.get("base_name") or ("باقة " + str(base_id))
        _log_txt(gate, format_line(gate, u, p), base_name + "  [فشل التمديد — بالباقة الأساسية فقط]")
        raise RuntimeError("أُنشئ اليوزر %s / %s بالباقة الأساسية «%s» فقط وفشل تمديده: %s"
                           % (u, p, base_name, str(e)[:160]))
    line = format_line(gate, u, p)
    _log_txt(gate, line, pkg["name"])
    return {"line": line, "username": u, "password": p, "package": pkg["name"],
            "verified": r.get("verified", True), "time": r["time"], "timing": r.get("timing"),
            "extended": {"times": times, "from": ends[0]["before"] if ends else "",
                         "to": ends[-1]["after"] if ends else ""}}


def create_lines(gate, pkg, count, username=None, password=None):
    """دفعة يوزرات: (النتائج، رسالة خطأ أو None). على جلسة الويب تحضير واحد للدفعة كلها
    (دخول + صفحة الإضافة مرة) ثم إرسال واحد لكل يوزر؛ وعلى API/فالكون نداء لكل يوزر
    كما كان. يوزر يفشل في المنتصف لا يُخفي ما نجح قبله."""
    if gate.get("mode") == "web" and count > 1 and not virtual_base(pkg["id"]):
        pairs = [(rand_digits(gate_digits(gate)), rand_digits(gate_digits(gate))) for _ in range(count)]
        out = []
        for r in web_session(gate).create_many(pkg["id"], pairs, gate.get("host")):
            if r.get("error"):
                return out, r["error"]
            line = format_line(gate, r["username"], r["password"])
            _log_txt(gate, line, pkg["name"])
            out.append({"line": line, "username": r["username"], "password": r["password"],
                        "package": pkg["name"], "verified": r.get("verified", True), "time": r["time"],
                        "timing": r.get("timing")})
        return out, None
    out = []
    for i in range(count):
        try:
            out.append(create_line(gate, pkg, username if count == 1 else None, password if count == 1 else None))
        except (xm_web.CaptchaNeeded, xm_web.LoginFailed):
            raise
        except Exception as e:
            if not out:
                raise
            return out, str(e)[:200]
    return out, None


# ---------------- وضع سطر الأوامر ----------------
def pick_account():
    accts = load_store()["accounts"]
    if not accts:
        sys.exit("لا توجد حسابات. شغّل الصفحة وأضف الحسابات من صفحة الحسابات أولاً.")
    if len(accts) == 1:
        return accts[0]
    for i, a in enumerate(accts, 1):
        print(f"{i}) {a['name']}")
    return accts[int(input("\nرقم الحساب: ").strip()) - 1]


def cli():
    acct = pick_account()
    gates = acct.get("gates", [])
    if not gates:
        sys.exit("لا توجد بوابات في هذا الحساب.")
    if len(gates) == 1:
        gate = gates[0]
    else:
        for i, g in enumerate(gates, 1):
            print(f"{i}) {g['name']}  —  {g['host']}")
        gate = gates[int(input("\nرقم البوابة: ").strip()) - 1]
    pkgs = get_packages(gate)
    if not pkgs:
        print("لا توجد باقات. شغّل: python xm_lines.py debug")
        return
    for i, p in enumerate(pkgs, 1):
        print(f"{i}) {p['name']}  —  {len(p['bouquets'])} بوكيه")
    n = int(input("\nرقم الباقة: ").strip())
    count = int((input("عدد اليوزرات [1]: ").strip() or "1"))
    for _ in range(count):
        print(create_line(gate, pkgs[n - 1])["line"])
    print(f"\n✓ تم الحفظ في {TXT_FILE}")


# ---------------- وضع الصفحة ----------------
class Handler(BaseHTTPRequestHandler):
    # يُعاد ضبطها من `_bind_host()` مع كل طلب؛ وهذه قيمها قبله.
    P = ADMIN_PATH
    on_tool_host = False
    off_site = False

    def _send(self, code, obj=None, ctype="application/json; charset=utf-8", raw=None, extra=None):
        body = raw if raw is not None else json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        extra = extra or {}
        # الافتراضي no-store، ما لم يمرّر النداء Cache-Control خاصًّا به.
        # (كان يُرسل دائمًا فتخرج ترويستان متعارضتان على الملفات الثابتة.)
        if not any(k.lower() == "cache-control" for k in extra):
            self.send_header("Cache-Control", "no-store")
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()
        if not getattr(self, "_head_only", False):
            self.wfile.write(body)

    def _page(self, name, cache=None):
        with open(os.path.join(BASE_DIR, name), "rb") as f:
            self._send(200, raw=f.read(), ctype="text/html; charset=utf-8",
                       extra={"Cache-Control": cache} if cache else None)

    def _redirect(self, to, code=302):
        self._send(code, raw=b"", ctype="text/plain", extra={"Location": to})

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def _q(self, name):
        from urllib.parse import parse_qs, urlparse
        return (parse_qs(urlparse(self.path).query).get(name, [""]) or [""])[0]

    def log_message(self, *a):
        pass

    def _cookie(self, name):
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return ""

    def _secure(self):
        return self.headers.get("X-Forwarded-Proto", "").lower() == "https"

    def _set_cookie(self, tok, clear=False):
        c = f"xm_session={tok}; Path={self.P or '/'}; HttpOnly; SameSite=Lax"
        c += "; Max-Age=0" if clear else f"; Max-Age={SESSION_TTL}"
        if self._secure():
            c += "; Secure"
        return {"Set-Cookie": c}

    def _who(self, st):
        """('admin', None) أو ('account', acct) أو (None, None) بدون إرسال رد."""
        tok = self._cookie("xm_session")
        ses = _sessions.get(tok)
        if ses and ses["exp"] > time.time():
            if ses["role"] == "admin":
                return "admin", None
            a = next((a for a in st["accounts"] if a["user"] == ses["user"]), None)
            if a:
                return "account", a
            _sessions.pop(tok, None)
        # دعم Basic Auth للأدوات مثل curl
        h = self.headers.get("Authorization", "")
        if h.startswith("Basic "):
            try:
                u, _, p = base64.b64decode(h[6:]).decode("utf-8", "replace").partition(":")
                return self._login(st, u, p)
            except Exception:
                pass
        return None, None

    @staticmethod
    def _login(st, u, p):
        if u == ADMIN_USER and ((ADMIN_ENV_PW and hmac.compare_digest(p, ADMIN_ENV_PW)) or check_pw(p, st["admin"])):
            return "admin", None
        for a in st["accounts"]:
            if not hmac.compare_digest(u, a.get("user", "")):
                continue
            stored = a.get("password")
            ok = check_pw(p, stored) if _is_hash(stored) else hmac.compare_digest(p, str(stored or ""))
            if ok:
                return "account", a
        return None, None

    def _deny(self, path):
        """`path` داخلي (بلا بادئة) — فردّ الـ API 401 لا تحويلًا إلى صفحة."""
        if path.startswith("/api/"):
            self._send(401, {"error": "سجّل الدخول أولاً", "login": True})
        else:
            self._redirect(self._url("/login"))

    # ---------- النطاق الذي وصل عليه الطلب ----------
    @staticmethod
    def _bare_host(h):
        """اسم النطاق وحده: بلا منفذ ولا أقواس IPv6 ولا قائمة وكلاء."""
        h = (h or "").split(",")[0].strip().lower()
        if h.startswith("["):                        # IPv6: [::1]:8080
            return h.partition("]")[0][1:]
        return h.partition(":")[0]

    def _bind_host(self):
        """يحدّد من النطاق أين تُقدَّم الأداة: من الجذر، أم تحت /admin، أم لا تُقدَّم."""
        host = self._bare_host(self.headers.get("X-Forwarded-Host") or self.headers.get("Host"))
        self.on_tool_host = bool(ADMIN_HOST) and host == ADMIN_HOST
        self.off_site = bool(ADMIN_HOST) and host == SITE_HOST   # الموقع العام: لا أداة عليه
        self.P = "" if self.on_tool_host else ADMIN_PATH

    def _url(self, sub="/"):
        """عنوان صفحة من الأداة كما يراه المتصفح على هذا النطاق."""
        return (self.P + sub) if sub != "/" else (self.P or "/")

    def _static(self, path):
        rel = os.path.normpath(path[len("/static/"):]).replace("\\", "/")
        full = os.path.join(STATIC_DIR, rel)
        if rel.startswith("..") or not os.path.isfile(full):
            return self._send(404, {"error": "not found"})
        with open(full, "rb") as f:
            self._send(200, raw=f.read(), ctype=MIME.get(os.path.splitext(rel)[1].lower(), "application/octet-stream"),
                       extra={"Cache-Control": "public, max-age=2592000"})

    # ---------- GET ----------
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        qs = self.path[len(path):]              # ما بعد "؟" — يُحمَل مع التحويل
        self._bind_host()
        if self.on_tool_host:                   # نطاق الأداة: الجذر هو الأداة، بلا موقع عام
            if path == "/robots.txt":           # لوحة الإدارة لا تُفهرس
                return self._send(200, raw=b"User-agent: *\nDisallow: /\n",
                                  ctype="text/plain; charset=utf-8")
            if path in ROOT_FILES:
                return self._static("/static/" + ROOT_FILES[path])
            if path.startswith("/static/"):
                return self._static(path)
            if path == ADMIN_PATH or path.startswith(ADMIN_PATH + "/"):
                return self._redirect((path[len(ADMIN_PATH):] or "/") + qs, 301)  # العنوان القديم
            return self._tool_get(path)
        # ----- الجزء العام -----
        if path == "/robots.txt":
            # حين تكون الأداة على نطاقها لا يبقى هنا مسار يُمنع — ومنعُ مسارٍ غير
            # موجود إعلانٌ عنه.
            block = "" if self.off_site else f"Disallow: {ADMIN_PATH}\n"
            return self._send(200, raw=f"User-agent: *\n{block}Allow: /\n\n"
                              f"Sitemap: https://guide.ssouq.com/sitemap.xml\n"
                              f"Sitemap: https://guide.ssouq.com/store-sitemap.xml\n".encode(),
                              ctype="text/plain; charset=utf-8")
        if path == "/store-sitemap.xml":        # خريطة منتجات المتجر (إرسال متقاطع)
            return self._send(200, raw=store_sitemap.sitemap(),
                              ctype="application/xml; charset=utf-8",
                              extra={"Cache-Control": PUBLIC_HTML_CACHE})
        if path == "/store-sitemap.json":       # تشخيص: المصدر والعدد وحالة البتر
            return self._send(200, raw=store_sitemap.status(),
                              ctype="application/json; charset=utf-8",
                              extra={"Cache-Control": "no-store"})
        if path == "/sitemap.xml":
            return self._send(200, raw=guide_pages.sitemap(),
                              ctype="application/xml; charset=utf-8",
                              extra={"Cache-Control": PUBLIC_HTML_CACHE})
        if path in ROOT_FILES:
            return self._static("/static/" + ROOT_FILES[path])
        if path == "/api/stats":
            return self._send(200, {"m3u": int(load_stats().get("m3u", 0))})
        if path == "/renew":                    # صفحة التجديد (عامة، بلا تسجيل دخول)
            return self._page("renew.html", cache=PUBLIC_HTML_CACHE)
        if path == "/api/renew/ticket":         # متابعة طلب معلّق برقم تذكرته
            return self._renew_ticket()
        if path in ("/", "/index.html"):
            return self._page("index.html", cache=PUBLIC_HTML_CACHE)
        if path in guide_pages.PAGES:                 # صفحات الأجهزة الثابتة (للأرشفة)
            return self._send(200, raw=guide_pages.render(path), ctype="text/html; charset=utf-8",
                              extra={"Cache-Control": PUBLIC_HTML_CACHE})
        if path.startswith("/static/"):
            return self._static(path)
        if path == ADMIN_PATH + "/":
            path = ADMIN_PATH
        if self.off_site or (path != ADMIN_PATH and not path.startswith(ADMIN_PATH + "/")):
            # الأداة على نطاقها وحده — فـ /admin هنا مسار لا وجود له
            return self._send(404, raw="404".encode(), ctype="text/plain; charset=utf-8")
        return self._tool_get(path[len(ADMIN_PATH):] or "/")

    # ---------- الأداة ----------
    def _tool_get(self, path):
        """الأداة نفسها. `path` داخلي: "/" · "/login" · "/accounts" · "/api/…"."""
        st = load_store()
        if not admin_configured(st):               # الإعداد الأول: لا يوجد مدير بعد
            return self._page(PAGES["/setup"]) if path == "/setup" else self._redirect(self._url("/setup"))
        if path == "/setup":
            return self._redirect(self._url())
        if path == "/logout":
            _sessions.pop(self._cookie("xm_session"), None)
            return self._send(302, raw=b"", ctype="text/plain",
                              extra={"Location": self._url("/login"), **self._set_cookie("", clear=True)})
        role, acct = self._who(st)
        if path == "/login":
            return self._redirect(self._url()) if role else self._page(PAGES["/login"])
        if not role:
            return self._deny(path)
        try:
            if path == "/":
                return self._redirect(self._url("/accounts")) if role == "admin" else self._page(PAGES["/"])
            if path == "/accounts":
                return self._page(PAGES["/accounts"]) if role == "admin" else self._send(403, {"error": "للمدير فقط"})
            if path == "/api/me":
                gates = [{"id": g["id"], "name": g["name"], "mode": g["mode"],
                          "host": g["host"], "guide_url": g.get("guide_url", ""),
                          "digits": gate_digits(g), "point_cost": g.get("point_cost", "")}
                         for g in (acct.get("gates", []) if acct else [])]
                return self._send(200, {"role": role, "account": acct["name"] if acct else None,
                                        "guide_url": acct.get("guide_url", "") if acct else "",
                                        "gates": gates})
            if path == "/api/mygates":            # بوابات الشخص كاملةً (لتحريرها)
                if role != "account":
                    return self._send(403, {"error": "غير متاح"})
                return self._send(200, {"gates": _redact_gates(acct.get("gates", [])),
                                        "guide_url": acct.get("guide_url", "")})
            if path == "/api/gate-status":        # النقاط + آخر يوزر للبوابة
                gate = find_gate(acct, self._q("gate")) if acct else None
                if role != "account" or not gate:
                    return self._send(403, {"error": "غير متاح"})
                if gate.get("mode") == "falcon":
                    return self._send(200, falcon_api.status(gate["api_url"], gate["api_key"]))
                if gate.get("mode") == "web":     # الرصيد من صفحة اللوحة نفسها
                    try:
                        stt = web_session(gate).status()
                        annotate_package_type(gate, stt.get("today_lines") or [])
                        return self._send(200, stt)
                    except xm_web.CaptchaNeeded:
                        return self._send(200, {"provider": "web", "credits": None, "need_login": True})
                    except xm_web.LoginFailed as e:
                        return self._send(200, {"provider": "web", "credits": None, "login_error": str(e)})
                    except Exception:
                        return self._send(200, {"provider": "web", "credits": None,
                                                "error": "تعذّر قراءة الرصيد من اللوحة"})
                return self._send(200, {"provider": gate.get("mode"), "credits": None,
                                        "unsupported": True})
            if path == "/api/search":             # بحث بالـ username/password
                gate = find_gate(acct, self._q("gate")) if acct else None
                if role != "account" or not gate:
                    return self._send(403, {"error": "غير متاح"})
                q = self._q("q").strip()
                if not q:
                    return self._send(200, {"results": []})
                if gate.get("mode") == "falcon":
                    return self._send(200, {"results": falcon_api.search(gate["api_url"], gate["api_key"], q)})
                if gate.get("mode") == "web":     # بحث جدول اللوحة نفسه
                    try:
                        return self._send(200, {"results": annotate_package_type(gate, web_session(gate).search(q))})
                    except xm_web.CaptchaNeeded:
                        return self._send(200, {"results": [], "need_login": True})
                    except xm_web.LoginFailed as e:
                        return self._send(200, {"results": [], "login_error": str(e)})
                    except Exception:
                        return self._send(200, {"results": [], "error": "تعذّر البحث في اللوحة"})
                return self._send(200, {"results": [], "unsupported": True})
            if path == "/api/web/diag":           # تشخيص مؤقّت لاستخراج الرصيد
                gate = find_gate(acct, self._q("gate")) if acct else None
                want = (self._q("name") or "").strip().lower()      # ?name=كاسبر يختار بالاسم
                if not gate and acct and want:
                    gate = next((g for g in acct.get("gates", []) if g.get("mode") == "web"
                                 and want in str(g.get("name", "")).lower()), None)
                if not gate and acct:
                    gate = next((g for g in acct.get("gates", []) if g.get("mode") == "web"), None)
                if role != "account" or not gate or gate.get("mode") != "web":
                    return self._send(403, {"error": "غير متاح"})
                try:
                    return self._send(200, {"gate": gate.get("name"), **web_session(gate).diag_web()})
                except xm_web.CaptchaNeeded:
                    return self._send(200, {"need_login": True})
                except Exception as e:
                    return self._send(200, {"error": str(e)[:200]})
            if path == "/api/web/captcha":        # صورة كود التحقّق (وضع الويب)
                gate = find_gate(acct, self._q("gate")) if acct else None
                if role != "account" or not gate or gate.get("mode") != "web":
                    return self._send(403, {"error": "غير متاح"})
                s = web_session(gate)
                s.begin()
                ct, img = s.fetch_captcha()
                return self._send(200, raw=img, ctype=ct or "image/jpeg")
            if path == "/api/packages":
                if role != "account":
                    return self._send(403, {"error": "ادخل بحساب مستخدم وليس المدير"})
                gate = find_gate(acct, self._q("gate"))
                if not gate:
                    return self._send(400, {"error": "اختر بوابة"})
                base = {"account": acct["name"], "gate": gate["id"], "host": gate["host"],
                        "guide_url": gate.get("guide_url") or acct.get("guide_url", "")}
                try:
                    pkgs = get_packages(gate)
                except xm_web.CaptchaNeeded:
                    return self._send(200, {**base, "need_captcha": True})
                except xm_web.LoginFailed as e:
                    return self._send(200, {**base, "login_error": str(e)})
                return self._send(200, {**base, "packages": pkgs})
            if path == "/api/accounts":
                if role != "admin":
                    return self._send(403, {"error": "للمدير فقط"})
                return self._send(200, {"accounts": [redact_account(a) for a in st["accounts"]]})
            if path == "/api/service":
                if role != "admin":
                    return self._send(403, {"error": "للمدير فقط"})
                return self._send(200, redact_service(st["service"]))
            if path == "/api/renew/config":       # إعداد التجديد (المدير)
                if role != "admin":
                    return self._send(403, {"error": "للمدير فقط"})
                return self._send(200, {"renew": renew.redact_config(st.get("renew")),
                                        "index": renew.index_stats(DATA_DIR),
                                        "tiers": list(renew.TIERS)})
            if path == "/renew":                  # صفحة الرفع والتحليل والإعداد
                if role != "admin":
                    return self._send(403, {"error": "للمدير فقط"})
                return self._page("renew_admin.html")
            if path == "/api/renew/analysis":      # آخر تحليل محفوظ
                if role != "admin":
                    return self._send(403, {"error": "للمدير فقط"})
                return self._send(200, {"analysis": renew.load_analysis(DATA_DIR),
                                        "index": renew.index_stats(DATA_DIR)})
            if path == "/api/renew/report":        # التحليل صفحةً تُحفَظ وتُرسَل
                if role != "admin":
                    return self._send(403, {"error": "للمدير فقط"})
                agg = renew.load_analysis(DATA_DIR)
                if not agg:
                    return self._send(404, {"error": "لا تحليل بعد — ارفع الملفات أولًا"})
                return self._send(200, raw=renew_import.report_html(agg).encode(),
                                  ctype="text/html; charset=utf-8",
                                  extra={"Content-Disposition":
                                         'attachment; filename="renew-analysis.html"'})
            if path == "/api/renew/packages":     # باقات مرح بنقاطها (للربط والتكلفة)
                if role != "admin":
                    return self._send(403, {"error": "للمدير فقط"})
                try:
                    pkgs, cost = renew_packages(st)
                except xm_web.CaptchaNeeded:
                    return self._send(200, {"packages": [],
                                            "error": "اللوحة تطلب كود تحقّق — سجّل الدخول لها من صفحة الإنشاء"})
                except Exception as e:
                    return self._send(200, {"packages": [], "error": str(e)[:200]})
                return self._send(200, {"packages": pkgs, "point_cost": cost})
            if path == "/api/renew/lines-status":  # تقدّم تصدير خطوط اللوحة
                if role != "admin":
                    return self._send(403, {"error": "للمدير فقط"})
                return self._send(200, {**_lines_job, "saved": renew.lines_stats(DATA_DIR)})
            if path == "/api/renew/harvest-status":
                if role != "admin":
                    return self._send(403, {"error": "للمدير فقط"})
                return self._send(200, {**_harvest,
                                        "saved": renew.harvest_stats(DATA_DIR)})
            if path == "/api/renew/pull-status":   # تقدّم السحب من سلة
                if role != "admin":
                    return self._send(403, {"error": "للمدير فقط"})
                return self._send(200, {**_pull,
                                        "has_token": bool(renew_salla_token(st))})
            if path == "/api/renew/queue":        # الطلبات: المعلّق والمنجز
                if role != "admin":
                    return self._send(403, {"error": "للمدير فقط"})
                db = renew.load_db(DATA_DIR)
                rows = sorted(db["claims"].values(), key=lambda r: r.get("at", ""), reverse=True)
                counts = {}
                for r in db["claims"].values():
                    counts[r.get("state", "?")] = counts.get(r.get("state", "?"), 0) + 1
                return self._send(200, {"rows": rows[:200], "counts": counts,
                                        "total": len(db["claims"]),
                                        "alert_at": db.get("alert_at", "")})
            if path == "/api/service/log":
                if role != "admin":
                    return self._send(403, {"error": "للمدير فقط"})
                rows = sorted(load_fulfillments().values(), key=lambda r: r.get("at", ""), reverse=True)[:100]
                return self._send(200, {"log": rows})
            if path == "/api/service/wa-status":
                if role != "admin":
                    return self._send(403, {"error": "للمدير فقط"})
                wa = st["service"].get("wa", {})
                if wa.get("type") != "http" or not wa.get("url"):
                    return self._send(200, {"applicable": False})
                base = _wa_base(wa)
                link = base + "/?" + urlencode({"key": wa.get("secret", "")})
                try:
                    rq = Request(base + "/status", headers={"Authorization": "Bearer " + wa.get("secret", "")})
                    with urlopen(rq, timeout=8) as r:
                        d = json.loads(r.read().decode("utf-8", "replace") or "{}")
                    return self._send(200, {"applicable": True, "connected": bool(d.get("connected")),
                                            "me": d.get("me", ""), "link": link})
                except Exception as e:
                    return self._send(200, {"applicable": True, "connected": False,
                                            "error": str(e)[:120], "link": link})
            self._send(404, {"error": "not found"})
        except Exception as e:
            self._send(500, {"error": str(e)})

    # ---------- HEAD ----------
    def do_HEAD(self):
        # BaseHTTPRequestHandler يرجع 501 لأي method غير معرّفة، وبعض الزواحف
        # والمراقبات تستعمل HEAD. نعيد ترويسات GET نفسها بلا جسم.
        self._head_only = True
        try:
            self.do_GET()
        finally:
            self._head_only = False




    def _renew_upload(self, st):
        """يرفع المدير ملفات سلة (الطلبات والمنتجات معًا) فيُبنى الفهرس ويُعرض
        التحليل. الملفات لا تُحفظ على القرص — يُحفظ ما استُخلص منها فقط."""
        n = int(self.headers.get("Content-Length", 0) or 0)
        if n <= 0:
            return self._send(400, {"error": "لا ملفات"})
        if n > renew_import.MAX_UPLOAD:
            return self._send(413, {"error": "الحجم أكبر من %d ميغابايت"
                                             % (renew_import.MAX_UPLOAD // (1024 * 1024))})
        body = self.rfile.read(n)
        fields, files = renew_import.parse_multipart(self.headers.get("Content-Type", ""), body)
        files = [(fn, raw) for _, fn, raw in files if raw]
        if not files:
            return self._send(400, {"error": "لم يصل أي ملف"})
        yes = lambda k: str(fields.get(k, "")).lower() in ("1", "true", "on", "yes")
        try:
            units, meta, _prods, agg = renew_import.ingest(
                files, keep_unconfirmed=yes("keep_unconfirmed"),
                include_falcon=yes("include_falcon"))
        except Exception as e:
            return self._send(400, {"error": "تعذّرت قراءة الملفات: " + str(e)[:200]})
        if not units:
            return self._send(200, {"ok": False, "analysis": agg,
                                    "error": "لم يُقرأ أي طلب صالح من الملفات"})
        renew.save_analysis(DATA_DIR, agg)
        applied = False
        if yes("apply"):                       # اعتماده فهرسًا تعمل عليه الصفحة العامة
            renew.save_index(DATA_DIR, renew_import.build_index(units, meta))
            applied = True
        return self._send(200, {"ok": True, "applied": applied, "analysis": agg,
                                "index": renew.index_stats(DATA_DIR)})

    # ---------- تجديد الاشتراك (المدير) ----------
    def _renew_admin(self, path, st):
        req = self._body()
        if path == "/api/renew/config":
            st["renew"] = renew.clean_config(req.get("renew") or {}, st.get("renew"))
            save_store(st)
            return self._send(200, {"ok": True, "renew": renew.redact_config(st["renew"])})
        if path == "/api/renew/pull":             # سحب الطلبات من سلة مباشرة
            return self._send(200, start_renew_pull(
                st, with_history=req.get("with_history", True),
                apply_index=req.get("apply", True)))
        if path == "/api/renew/lines-export":
            return self._send(200, start_lines_export(st, req.get("side", "source")))
        if path == "/api/renew/lines-cancel":
            _lines_job["cancel"] = True
            return self._send(200, {"ok": True})
        if path == "/api/renew/candidates":       # مرشّحو الخط لمن لا يعرف يوزره
            rec = renew.find_order(DATA_DIR, req.get("order", ""), req.get("phone", ""))
            if not rec:
                return self._send(404, {"error": "لا طلب بهذا الرقم والجوال"})
            return self._send(200, {"ok": True, "candidates": renew.match_candidates(
                DATA_DIR, rec.get("date"), rec.get("months"), rec.get("devices", 1))})
        if path == "/api/renew/harvest":
            return self._send(200, start_harvest(st, harvest_scope_args(req)))
        if path == "/api/renew/harvest-preview":   # كم سيُحصد قبل أن يبدأ
            _rows, counts = renew.harvest_scope(DATA_DIR, **harvest_scope_args(req))
            return self._send(200, {"ok": True, "counts": counts})
        if path == "/api/renew/harvest-cancel":
            _harvest["cancel"] = True
            return self._send(200, {"ok": True})
        if path == "/api/renew/harvest-retry":     # يُعاد على من لم يُعطِ شيئًا
            return self._send(200, {"ok": True, "kept": renew.harvest_reset(DATA_DIR)})
        if path == "/api/renew/pull-cancel":
            _pull["cancel"] = True
            return self._send(200, {"ok": True})
        if path == "/api/renew/run":              # تفريغ الطابور الآن
            return self._send(200, {"ok": True, "result": renew_run_queue(st)})
        if path == "/api/renew/retry":            # إعادة طلب متوقّف إلى الطابور
            key = str(req.get("key", ""))
            db = renew.load_db(DATA_DIR)
            rec = db["claims"].get(key)
            if not rec:
                return self._send(404, {"error": "لا طلب بهذا المفتاح"})
            if rec.get("state") == "done":
                return self._send(400, {"error": "منجز — لا يُعاد، وإلا أُنشئ يوزر ثانٍ"})
            rec["state"] = "queued"
            rec["attempts"] = 0
            db["claims"][key] = rec
            renew.save_db(DATA_DIR, db)
            return self._send(200, {"ok": True, "claim": rec})
        if path == "/api/renew/panel-test":       # أما زالت كوكيز اللوحة صالحة؟
            sess = renew_panel_session(st)
            if not sess:
                return self._send(200, {"ok": False, "error": "لم تُلصق كوكيز اللوحة"})
            alive, why = sess.alive()
            return self._send(200, {"ok": alive, "error": why,
                                    "cookies": len(salla_web.cookie_names(sess.cookie))})
        if path == "/api/renew/alert-test":       # اختبار بريد التنبيه
            ok, why = renew.alert_disconnect(DATA_DIR, {**renew.normalize_config(st.get("renew")),
                                                        "alert": {**renew.normalize_config(st.get("renew"))["alert"],
                                                                  "gap_minutes": 0}},
                                             "رسالة اختبار — لا انقطاع فعلي", len(renew.pending(DATA_DIR)))
            return self._send(200, {"ok": ok, "error": why})
        return self._send(404, {"error": "not found"})

    # ---------- تجديد الاشتراك (عام) ----------
    def _client_ip(self):
        fwd = self.headers.get("X-Forwarded-For", "")
        return (fwd.split(",")[0].strip() if fwd else self.client_address[0])

    def _renew_ticket(self):
        rec = renew.by_ticket(DATA_DIR, self._q("t"))
        if not rec:
            return self._send(404, {"error": "لا طلب بهذا الرقم"})
        hours = renew.normalize_config(load_store().get("renew"))["promise_hours"]
        return self._send(200, {"ok": True, "claim": renew.public_view(rec, hours)})

    def _renew_public(self, path):
        """التعرّف والتقديم. لا تسجيل دخول — فالحارس هو مطابقة الطلب بالجوال
        وحدّ المحاولات بالساعة، وإلا صارت أرقام الطلبات قابلة للتخمين."""
        with _lock:
            st = load_store()
        cfg = renew.normalize_config(st.get("renew"))
        if not cfg.get("enabled"):
            return self._send(503, {"error": "صفحة التجديد غير مفعّلة حاليًا"})
        try:
            req = self._body()
        except ValueError:
            return self._send(400, {"error": "طلب غير صالح"})
        if not renew.rate_ok(DATA_DIR, self._client_ip(), cfg["rate_per_hour"]):
            return self._send(429, {"error": "محاولات كثيرة. انتظر ساعة ثم أعد المحاولة."})

        order = str(req.get("order", ""))
        phone = str(req.get("phone", ""))
        user = str(req.get("username", "")).strip()
        pw = str(req.get("password", ""))
        try:
            look = renew_lookup(st, order, phone, user, pw)
        except Exception:
            return self._send(200, {"ok": False, "offline": True,
                                    "error": "تعذّر الوصول للوحة الآن",
                                    "promise_hours": cfg["promise_hours"]})
        if path == "/api/renew/lookup" or not look.get("ok"):
            return self._send(200, look)

        # ----- التقديم -----
        if look.get("need_username"):
            return self._send(200, {**look, "error": "اكتب يوزر اشتراكك الحالي لنُبقيه كما هو"})
        if look.get("need_password"):
            return self._send(200, {**look, "error": "اكتب كلمة مرور اشتراكك — هي في رسالة اشتراكك بعد Pass"})
        plan = look["plan"]
        with _lock:
            st = load_store()
            rec, created = renew.submit(
                DATA_DIR, st, st.get("renew"), renew_prov(),
                order_no=order, phone=phone, username=look["username"],
                password=look.get("password", ""), months=plan["months"],
                tier=plan["tier"], expiry=plan["expiry"],
                devices=look.get("devices", 1), source="page")
        if not rec:
            return self._send(400, {"error": "تعذّر تسجيل الطلب"})
        if rec.get("state") == "queued":        # الوصل مقطوع: وعدٌ بالمدة وتنبيهٌ لنا
            renew.alert_disconnect(DATA_DIR, st.get("renew"),
                                   rec.get("last_error", ""), len(renew.pending(DATA_DIR)))
        return self._send(200, {"ok": True, "created": created,
                                "claim": renew.public_view(rec, cfg["promise_hours"])})

    # ---------- POST ----------
    def do_POST(self):
        path = self.path.split("?", 1)[0]
        self._bind_host()
        if not self.on_tool_host:                   # مسارات الموقع العام وحده
            if path == "/api/m3u-generated":        # عدّاد عام لأداة M3U (بدون تسجيل دخول)
                with _lock:
                    return self._send(200, {"m3u": bump_stat("m3u")})
            if path == "/salla/webhook":            # ويبهوك سلة (عام، موقَّع)
                return self._salla_webhook()
            if path in ("/api/renew/lookup", "/api/renew/claim"):
                return self._renew_public(path)
        if self.off_site or not path.startswith(self.P + "/api/"):
            return self._send(404, {"error": "not found"})
        path = path[len(self.P):]
        try:
            with _lock:
                st = load_store()
                if path == "/api/setup":
                    if admin_configured(st):
                        return self._send(400, {"error": "تم الإعداد مسبقاً"})
                    pw = str(self._body().get("password", ""))
                    if len(pw) < 6:
                        return self._send(400, {"error": "كلمة المرور قصيرة (6 أحرف على الأقل)"})
                    st["admin"] = hash_pw(pw)
                    save_store(st)
                    return self._send(200, {"ok": True}, extra=self._set_cookie(new_session("admin", ADMIN_USER)))
                if not admin_configured(st):
                    return self._send(400, {"error": "أكمل الإعداد أولاً"})
                if path == "/api/login":
                    req = self._body()
                    role, acct = self._login(st, str(req.get("user", "")).strip(), str(req.get("password", "")))
                    if not role:
                        return self._send(401, {"error": "اسم الدخول أو كلمة المرور غير صحيحة"})
                    tok = new_session(role, ADMIN_USER if role == "admin" else acct["user"])
                    return self._send(200, {"ok": True, "role": role}, extra=self._set_cookie(tok))
                role, acct = self._who(st)
                if not role:
                    return self._deny(path)
                if path.startswith("/api/accounts"):
                    if role != "admin":
                        return self._send(403, {"error": "للمدير فقط"})
                    return self._admin_post(path, st)
                if path == "/api/renew/upload":
                    if role != "admin":
                        return self._send(403, {"error": "للمدير فقط"})
                    return self._renew_upload(st)
                if path.startswith("/api/renew/"):
                    if role != "admin":
                        return self._send(403, {"error": "للمدير فقط"})
                    return self._renew_admin(path, st)
                if path.startswith("/api/service"):
                    if role != "admin":
                        return self._send(403, {"error": "للمدير فقط"})
                    return self._service_post(path, st)
                if path.startswith("/api/mygates"):    # الشخص يدير بواباته بنفسه
                    if role != "account":
                        return self._send(403, {"error": "غير متاح"})
                    return self._mygates_post(path, st, acct)
                if path == "/api/myguide":              # رابط شرح واحد لكل البوابات
                    if role != "account":
                        return self._send(403, {"error": "غير متاح"})
                    gu = str(self._body().get("guide_url", "")).strip()
                    if gu and not gu.startswith(("http://", "https://")):
                        return self._send(400, {"error": "رابط الشرح يجب أن يبدأ بـ http://"})
                    acct["guide_url"] = gu
                    save_store(st)
                    return self._send(200, {"ok": True, "guide_url": gu})
            if path == "/api/web/login":              # إدخال كود التحقّق يدويًا (وضع الويب)
                body = self._body()
                gate = find_gate(acct, body.get("gate")) if acct else None
                if role != "account" or not gate or gate.get("mode") != "web":
                    return self._send(403, {"error": "غير متاح"})
                code = str(body.get("captcha", "")).strip()
                if not code:
                    return self._send(400, {"error": "اكتب الكود"})
                try:
                    web_session(gate).login(captcha=code)
                    return self._send(200, {"ok": True})
                except xm_web.LoginFailed as e:
                    return self._send(200, {"ok": False, "kind": "login", "error": str(e)})
                except xm_web.CaptchaNeeded:
                    return self._send(200, {"ok": False, "kind": "captcha", "error": "الكود غير صحيح"})
            if path == "/api/create":
                if role != "account":
                    return self._send(403, {"error": "ادخل بحساب مستخدم وليس المدير"})
                try:
                    return self._create(acct)
                except xm_web.CaptchaNeeded:
                    return self._send(200, {"need_captcha": True})
                except xm_web.LoginFailed as e:
                    return self._send(200, {"login_error": str(e)})
            self._send(404, {"error": "not found"})
        except ValueError as e:
            self._send(400, {"error": str(e)})
        except Exception as e:
            self._send(500, {"error": str(e)})

    def _admin_post(self, path, st):
        req = self._body()
        accts = st["accounts"]
        if path == "/api/accounts":                      # إضافة أو تعديل
            old = next((a for a in accts if a["id"] == req.get("id")), None)
            new = clean_account(req, old)
            if any(a["user"] == new["user"] and a["id"] != new["id"] for a in accts):
                return self._send(400, {"error": "اسم الدخول مستخدم لحساب آخر"})
            if old:
                accts[accts.index(old)] = new
            else:
                accts.append(new)
        elif path == "/api/accounts/delete":
            st["accounts"] = [a for a in accts if a["id"] != req.get("id")]
        elif path == "/api/accounts/import":
            imported = [clean_account(a) for a in req.get("accounts", [])]
            seen = set()
            for a in imported:
                if a["user"] in seen:
                    return self._send(400, {"error": f"اسم الدخول مكرر: {a['user']}"})
                seen.add(a["user"])
            st["accounts"] = imported
        elif path == "/api/accounts/admin-password":
            pw = str(req.get("password", ""))
            if len(pw) < 6:
                return self._send(400, {"error": "كلمة المرور قصيرة (6 أحرف على الأقل)"})
            st["admin"] = hash_pw(pw)
            mine = self._cookie("xm_session")
            for t, v in list(_sessions.items()):
                if v["role"] == "admin" and t != mine:
                    _sessions.pop(t, None)
        else:
            return self._send(404, {"error": "not found"})
        save_store(st)
        self._send(200, {"ok": True, "accounts": [redact_account(a) for a in st["accounts"]]})

    def _mygates_post(self, path, st, acct):
        req = self._body()
        gates = acct.setdefault("gates", [])
        if path == "/api/mygates":                     # إضافة/تعديل بوابة
            old = next((g for g in gates if g["id"] == req.get("id")), None)
            ng = clean_gate(req, old)
            if old:
                gates[gates.index(old)] = ng
            else:
                gates.append(ng)
        elif path == "/api/mygates/delete":
            acct["gates"] = [g for g in gates if g["id"] != req.get("id")]
        else:
            return self._send(404, {"error": "not found"})
        save_store(st)
        self._send(200, {"ok": True, "gates": _redact_gates(acct["gates"])})

    def _create(self, acct):
        req = self._body()
        gate = find_gate(acct, req.get("gate"))
        if not gate:
            return self._send(400, {"error": "اختر بوابة"})
        # رابط الشرح: خاص بالبوابة، وإلا رابط الشخص العام لكل بواباته.
        if not gate.get("guide_url") and acct.get("guide_url"):
            gate = {**gate, "guide_url": acct["guide_url"]}
        pkg = next((p for p in get_packages(gate) if str(p["id"]) == str(req.get("package_id"))), None)
        if not pkg:
            return self._send(400, {"error": "الباقة غير موجودة"})
        count = max(1, min(int(req.get("count", 1)), 50))
        t_start = time.time()
        out, err = create_lines(gate, pkg, count,
                                req.get("username") if count == 1 else None,
                                req.get("password") if count == 1 else None)
        resp = {"lines": out, "total_ms": int((time.time() - t_start) * 1000)}
        if err:
            # ما أُنشئ قبل الخطأ أُنشئ فعلًا (وخُصم)، فيُعاد مع الخطأ لا بدلًا منه.
            resp["error"] = err if not out else "أُنشئ %d من %d ثم توقفت اللوحة: %s" % (len(out), count, err)
        self._send(200, resp)


    def _salla_webhook(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(n) if n > 0 else b""
        with _lock:
            st = load_store()
            svc = st["service"]
            if not svc.get("enabled"):
                return self._send(200, {"ok": True, "ignored": "disabled"})
            if not salla_api.verify(svc.get("salla_secret", ""), svc.get("salla_token", ""), raw, self.headers):
                return self._send(401, {"error": "توقيع غير صالح"})
            try:
                payload = json.loads(raw.decode("utf-8", "replace") or "{}")
            except ValueError:
                return self._send(400, {"error": "جسم غير صالح"})
            order = salla_api.parse_order(payload)
            if not order.get("order_id"):
                return self._send(200, {"ok": True, "ignored": "no_order"})
            res = fulfill_order(st, order, source="webhook")
            return self._send(200, {"ok": True, "status": res.get("status")})

    def _service_post(self, path, st):
        req = self._body()
        if path == "/api/service":
            st["service"] = clean_service(req, st.get("service"))
            save_store(st)
            return self._send(200, {"ok": True, "service": redact_service(st["service"])})
        if path == "/api/service/test":
            to = salla_api.normalize_phone(req.get("phone", ""), req.get("code", ""))
            if not to:
                return self._send(400, {"error": "اكتب رقم واتساب صحيح"})
            text = str(req.get("text") or "رسالة اختبار من خدمة سلة ← واتساب ✅")
            r = wa_send.send(st["service"].get("wa", {}), to, text)
            return self._send(200, {"ok": bool(r.get("ok")), "result": r, "to": to})
        if path == "/api/service/fulfill":       # تنفيذ يدوي (اختبار الربط/إعادة إرسال)
            order = {"order_id": str(req.get("order_id") or ("manual-" + secrets.token_hex(3))),
                     "reference": str(req.get("order_id") or ""),
                     "phone": salla_api.normalize_phone(req.get("phone", ""), req.get("code", "")),
                     "customer_name": str(req.get("name", "")), "status": "paid",
                     "items": [{"product_id": str(req.get("product_id", "")), "name": "",
                                "sku": "", "quantity": max(1, min(int(req.get("count", 1) or 1), 10))}]}
            res = fulfill_order(st, order, source="manual", force=bool(req.get("force")))
            return self._send(200, {"ok": res.get("status") in ("sent", "dry", "partial"), "result": res})
        return self._send(404, {"error": "not found"})


def web():
    print(f"الصفحة تعمل: http://{BIND}:{PORT}   (Ctrl+C للإيقاف)", flush=True)
    start_poller()
    start_renew_worker()
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "cli"
    if mode == "web":
        web()
    elif mode == "debug":
        print(json.dumps(api(pick_account()["gates"][0], "get_packages"), ensure_ascii=False, indent=2)[:4000])
    else:
        cli()

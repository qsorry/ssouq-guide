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
import io, zipfile
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import copy

import guide_pages
import store_sitemap
import league
import tournament
import watch
import predict_page
import contest
import content
import xm_web
import falcon_api
import crypto_store
import salla_api
import wa_send
import renew
import renew_import
import panels
import xlsx_write
import users_export
import user_links
import salla_web
import split_subs

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
# البطولات: دوري الأمم (tournament) وكأس الخليج (نسخةٌ من الوحدة نفسها بإعدادها). وصفحاتهما تقرأ
# مسابقاتها والقناة الناقلة لكل مباراة من مجلد البيانات هذا
CUPS = (tournament, tournament.instance("gulf_cup", **tournament.GULF))
HUB_CUPS = (CUPS[1], CUPS[0])                 # ودجت المتجر: كأس الخليج أولًا


def tv_map():
    """القنوات الناقلة: ما كتبه المدير لكل مباراة وبطولة، وقناة كل بطولةٍ من إعدادها ما لم يغيّرها."""
    tv = contest.channels(DATA_DIR)
    for t in CUPS:
        tv.setdefault("cup:" + t.PATH, t.CUP.get("tv", ""))
    return tv


for _cup in CUPS:
    _cup.contests = lambda: contest.summaries(DATA_DIR)
    _cup.channels = tv_map


def cup_matches():
    """مباريات البطولات كلها من كاش ESPN (والمتعذّرة تُتخطّى) ← (المباريات، أتاحت كلها؟)."""
    ms, ok = [], True
    for t in CUPS:
        data = t._feed.get()[0]
        ok = ok and bool(data)
        ms += (data or {}).get("matches", [])
    return ms, ok

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
EXTENSION_DIR = os.path.join(BASE_DIR, "extension", "salla-cookie")


def build_extension_zip():
    """إضافة المتصفّح مضغوطةً في الذاكرة من مصدرها — فلا يُحفظ ملفٌّ ثنائيّ في
    المستودع يتقادم عن الكود. الملفات في **جذر** الحزمة (‏`manifest.json` أولها)
    لا داخل مجلّد فرعي: ويندوز يفكّ الضغط إلى مجلّد باسم الملف، فلو كان تحته
    مجلّدٌ ثانٍ لصار البيان على عمق طبقتين ورفضه كروم («البيان مفقود»)."""
    if not os.path.isdir(EXTENSION_DIR):
        return b""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(EXTENSION_DIR):
            for fn in sorted(files):
                full = os.path.join(root, fn)
                z.write(full, os.path.relpath(full, EXTENSION_DIR))
    return buf.getvalue()
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
# الجلسات تُحفَظ على القرص (نفس مجلّد البيانات الدائم) لا في الذاكرة فقط — وإلا
# فكل نشرٍ/إعادة تشغيلٍ للحاوية يمسحها فيُخرَج الجميع رغم صلاحية الكوكي (٣٠ يوم).
SESSIONS_FILE = os.path.join(DATA_DIR, "sessions.json")


def _load_sessions():
    try:
        with open(SESSIONS_FILE, encoding="utf-8") as f:
            d = json.load(f)
        now = time.time()
        return {t: v for t, v in d.items()
                if isinstance(v, dict) and v.get("exp", 0) > now}
    except Exception:
        return {}


_sessions = _load_sessions()   # token -> {"role","user","exp"}


def _save_sessions():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = SESSIONS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_sessions, f)
        os.replace(tmp, SESSIONS_FILE)
    except Exception:
        pass                    # الحفظ مساعدٌ لا يُفشل الطلب


def new_session(role, user):
    for t, v in list(_sessions.items()):
        if v["exp"] < time.time():
            _sessions.pop(t, None)
    tok = secrets.token_urlsafe(32)
    _sessions[tok] = {"role": role, "user": user, "exp": time.time() + SESSION_TTL}
    _save_sessions()
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


# ============================ مساحة عمل renew لكل حساب ============================
# الأدمن يبقى على المساحة العامة (data/) توافقًا مع بياناته الحالية وخدمة العميل.
# كل حساب يوزر له مجلده المعزول (data/renew_ws/<id>/) وإعداده الخاص (acct["renew"])
# فلا يرى غيره — «كل شيء مثل الأدمن لكن يقتصر على أعماله».
def renew_ws(role, acct):
    """(مجلّد البيانات، مالك الإعداد). الأدمن: (DATA_DIR, None) → الإعداد في st.
    الحساب: (مجلّده، acct) → الإعداد في acct["renew"]."""
    if role == "admin" or not acct:
        return DATA_DIR, None
    d = os.path.join(DATA_DIR, "renew_ws", str(acct.get("id") or "x"))
    os.makedirs(d, exist_ok=True)
    return d, acct


def renew_cfg(st, owner):
    """إعداد renew لهذه المساحة: من acct إن كان حسابًا، وإلا من st (الأدمن)."""
    return (owner or st).get("renew")


def _own_job(job, ws):
    """حالة المهمة إن كانت لهذه المساحة، وإلا «خاملة» — فلا يرى يوزرٌ تقدّم غيره."""
    return dict(job) if job.get("owner") == ws else {"running": False}


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
        # نكهة جلسة الويب: xtream (table_search الافتراضي) أو casper (لوحة كاسبر/c4k
        # بترقيم index.php/users/index). لا أثر لها على بوابات api/falcon.
        "web_flavor": (str(g.get("web_flavor", "")).strip().lower()
                       or old.get("web_flavor", "") or "xtream"),
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
        if out["web_flavor"] not in ("xtream", "casper"):
            out["web_flavor"] = "xtream"
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


# نص الشرح الافتراضي لخيار «نسخ نص الشرح» — يعدّله المدير لكل عميل. تملأ صفحة
# الإنشاء {guide} {host} {user} {pass} بقيم البوابة واليوزر لحظة النسخ، و{server}
# باسم اشتراك البوابة كما في الدليل (انظر guide_sub).
DEFAULT_GUIDE_TEXT = """📲 طريقة التثبيت والتفعيل

🔗 شرح التثبيت:
{guide}

يرجى اتباع الخطوات الموجودة في الشرح واختيار سيرفر {server} ✅

📌 بيانات الاشتراك:

Host: {host}
User: {user}
Pass: {pass}

⚠️ مهم جدًا:
يرجى استخدام التطبيق الموصى به في الشرح فقط، حيث إن الاشتراك لن يعمل عند استخدام تطبيق آخر.

يرجى حذف أي تطبيق سابق للخدمة، ثم تثبيت التطبيق الموصى به واتباع خطوات التفعيل الموجودة في الدليل."""
GUIDE_TEXT_MAX = 4000


def _clean_guide_text(v):
    """نص الشرح كما كتبه المدير، بأسطر \\n وبلا فراغ حوله. النص الافتراضي نفسه يُحفظ
    فارغًا فيتبع الافتراضي — والفراغ عند القراءة = الافتراضي (انظر guide_text_of)."""
    t = str(v or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(t) > GUIDE_TEXT_MAX:
        raise ValueError("نص الشرح طويل (الحد %d حرف)" % GUIDE_TEXT_MAX)
    # والافتراضي قبل {server} («كاسبر» للجميع) — من صفحة حسابات فُتحت قبل التحديث — مثله.
    return "" if t in (DEFAULT_GUIDE_TEXT, DEFAULT_GUIDE_TEXT.replace("{server}", "كاسبر")) else t


def guide_text_of(acct):
    """ما تنسخه صفحة الإنشاء لهذا العميل بدل السطر: نصه أو الافتراضي، و"" إن لم يُفعَّل."""
    if not acct or not acct.get("copy_guide"):
        return ""
    return acct.get("guide_text") or DEFAULT_GUIDE_TEXT


# أسماء الاشتراكات كما يعرضها الدليل (SUBS في index.html) — فما يُطلب من العميل
# اختياره هو ما يراه في الشرح. «مرح» اسم سمارت القديم (legacySub هناك).
GUIDE_SUBS = {"smart": "سمارت", "falcon": "فالكون", "casper": "كاسبر"}
_SUB_WORDS = {"smart": ("smart", "marah", "mr7", "سمارت", "مرح"),
              "falcon": ("falcon", "فالكون"),
              "casper": ("casper", "كاسبر")}


def guide_sub(gate, guide_url=""):
    """اسم اشتراك البوابة في الدليل ({server} في نص الشرح): من رابط شرحها
    (#activate/<الاشتراك>) لأنه ما سيفتحه العميل، وإلا من اسمها، وإلا من نوعها،
    وآخرًا اسمها نفسه بلا «بوابة»."""
    m = re.search(r"#activate/([a-z]+)", guide_url or gate.get("guide_url", ""))
    key = m.group(1) if m else ""
    key = "smart" if key == "marah" else key
    if key not in GUIDE_SUBS:
        name = str(gate.get("name", "")).lower()
        key = next((k for k, words in _SUB_WORDS.items() if any(w in name for w in words)), "")
    if not key and gate.get("mode") == "falcon":
        key = "falcon"
    if not key and gate.get("mode") == "web" and gate.get("web_flavor") == "casper":
        key = "casper"
    if key:
        return GUIDE_SUBS[key]
    return re.sub(r"^\s*بوابة\s+", "", str(gate.get("name", ""))).strip()


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
        # نسخ نص الشرح: يفعّله المدير لهذا العميل، فينسخ البحث (نتائجه واليوزر البديل)
        # النص كاملًا بقيم اليوزر بدل السطر الواحد. الإنشاء يبقى سطرًا.
        "copy_guide": bool(a.get("copy_guide", old.get("copy_guide", False))),
        "guide_text": _clean_guide_text(a.get("guide_text", old.get("guide_text", ""))),
        # الاشتراكات المجزّأة (بيع ٦ · ٣ · شهر من باقة ١٥ شهرًا وتغيير اسم المستخدم عند
        # انتهاء الجزء): يفتحها المدير لعميلٍ بعينه، ومغلقةٌ لغيره فلا يتغيّر عليه شيء.
        "split": bool(a.get("split", old.get("split", False))),
    }
    if not out["name"]:
        raise ValueError("الاسم مطلوب")
    if not out["user"] or ":" in out["user"] or out["user"] == ADMIN_USER:
        raise ValueError("اسم الدخول غير صالح أو محجوز")
    if not _is_hash(out["password"]):
        raise ValueError("كلمة المرور مطلوبة")
    if out["guide_url"] and not out["guide_url"].startswith(("http://", "https://")):
        raise ValueError("رابط الشرح يجب أن يبدأ بـ http:// أو https://")
    # نصٌّ بلا اليوزر أو الباسورد يُنسخ للعميل بلا بيانات اشتراكه — يُرفض ما دام مفعّلًا.
    missing = [k for k in ("{user}", "{pass}") if k not in guide_text_of(out)]
    if out["copy_guide"] and missing:
        raise ValueError("نص الشرح يجب أن يحتوي %s — وإلا نُسخ بلا بيانات الاشتراك" % " و".join(missing))

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
    # ما لا يديره هذا النموذج — كإعداد التجديد (renew) الذي يحفظه الحساب لنفسه — يبقى
    # كما هو، وإلا مسحه أي حفظٍ للحساب من صفحة الحسابات.
    for k, v in old.items():
        out.setdefault(k, v)
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
                if not (svc.get("enabled") and svc.get("poll")):
                    continue
                orders = _poll_salla_orders(st, svc, per_page=25)
                if not orders:
                    continue
                fulfilled = load_fulfillments()
                for o in orders:
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


def renew_packages(cfg, accounts):
    """باقات بوابة مرح كما تسمّيها اللوحة، ومعها نقاطها ومدتها.

    النقاط مكتوبة في الاسم نفسه («اشتراك سنة + جهازين (6 نقاط)») فتُقرأ منه ولا
    تُخمَّن — وهي ليست حاصل ضرب: السنة بأربع نقاط، والسنة بجهازين بستٍّ لا بثمانٍ."""
    cfg = renew.normalize_config(cfg)
    acct = next((a for a in accounts
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


def renew_salla_token(st, cfg=None):
    """رمز سلة لهذه المساحة: رمز الإعداد الخاص إن وُجد (لكل حساب رمزه)، وإلا
    رمز الخدمة العام (يستعمله الأدمن)."""
    if cfg and (cfg.get("salla_token") or ""):
        return cfg["salla_token"]
    return (st.get("service") or {}).get("salla_token") or ""


def salla_service_cookie(st):
    """كوكيز جلسة لوحة سلة المشتركة (تُربط بضغطة واحدة عبر إضافة المتصفح، وتُخزَّن
    في إعداد تجديد الأدمن `panel_cookie`). يستعملها كلٌّ من التجديد والتسليم
    التلقائي — ربطٌ واحدٌ لسلة يكفي الاثنين."""
    return str((st.get("renew") or {}).get("panel_cookie") or "").strip()


def _poll_salla_orders(st, svc, per_page=25):
    """أحدث طلبات سلة للتسليم التلقائي: بجلسة اللوحة (الإضافة) أوّلًا — لا توكن —
    وإلا بتوكن الإدارة إن ضُبط. تُعاد مُحلَّلةً جاهزةً للتنفيذ."""
    cookie = salla_service_cookie(st)
    if cookie:
        try:
            rows = salla_web.Session(cookie).recent_orders(per_page)
            return [salla_api.parse_order(r) for r in rows]
        except salla_web.SessionExpired:
            renew.alert_session_expired(DATA_DIR, st.get("renew"))
            return []
        except Exception:
            return []
    if svc.get("salla_token"):
        return list(salla_api.fetch_orders(svc["salla_token"], per_page=per_page, page=1))
    return []


def _pull_worker(token, with_history, apply_index, ws, cfg):
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
        renew.save_analysis(ws, agg)
        panels.save_store_lines(ws, units)         # لتغذية مقارنة اللوحات
        if apply_index:
            renew.save_index(ws, renew_import.build_index(units, meta))
            _pull["applied"] = True
        _pull.update({"units": len(units), "found": meta.get("with_credentials", 0),
                      "phase": "done", "session_expired": meta.get("session_expired", False)})
        if meta.get("session_expired"):
            # التحقّق الثنائي في سلة إلزاميّ، فلا تُجدَّد الجلسة إلا بيد المشغّل.
            renew.alert_session_expired(ws, cfg)
    except Exception as e:
        _pull["error"] = str(e)[:300]
    finally:
        _pull["running"] = False
        _pull["at"] = renew.now_iso()


def start_renew_pull(st, ws, cfg, with_history=True, apply_index=True):
    if _pull["running"]:
        return {"ok": False, "error": "سحبٌ جارٍ بالفعل"}
    token = renew_salla_token(st, cfg)
    if not token:
        return {"ok": False, "error": "رمز سلة غير مضبوط — اضبطه في إعداد المساحة"}
    _pull.update({"running": True, "owner": ws, "phase": "orders", "done": 0, "total": 0,
                  "units": 0, "found": 0, "error": "", "cancel": False,
                  "applied": False, "session_expired": False})
    threading.Thread(target=_pull_worker, args=(token, with_history, apply_index, ws, cfg),
                     daemon=True).start()
    return {"ok": True}



# ---- تصدير خطوط اللوحة (خلفيّ) ----
_lines_job = {"running": False, "done": 0, "total": 0, "error": "", "at": "", "cancel": False}


def _lines_worker(gate, ws):
    try:
        def prog(seen, last=1, page=1):
            _lines_job.update({"done": seen, "total": max(seen, (last or 1) * 50)})

        rows = _all_web_lines(gate, prog)
        n = renew.save_lines(ws, rows, gate.get("name", ""), gate.get("host", ""))
        _lines_job.update({"done": n, "total": n})
    except xm_web.CaptchaNeeded:
        _lines_job["error"] = "اللوحة تطلب كود تحقّق — سجّل الدخول لها من صفحة الإنشاء"
    except Exception as e:
        _lines_job["error"] = str(e)[:300]
    finally:
        _lines_job["running"] = False
        _lines_job["at"] = renew.now_iso()


def start_lines_export(st, ws, cfg, accounts, side="source"):
    if _lines_job["running"]:
        return {"ok": False, "error": "تصديرٌ جارٍ بالفعل"}
    cfg = renew.normalize_config(cfg)
    acct = next((a for a in accounts
                 if str(a.get("id")) == str(cfg[side]["account_id"])), None)
    gate = find_gate(acct, cfg[side]["gate_id"]) if acct else None
    ok, why = renew.gate_allowed(gate)
    if not ok:
        return {"ok": False, "error": why if gate else "البوابة غير مضبوطة"}
    if gate.get("mode") != "web":
        return {"ok": False, "error": "التصدير الكامل متاح على بوابات جلسة الويب"}
    _lines_job.update({"running": True, "owner": ws, "done": 0, "total": 0,
                       "error": "", "cancel": False})
    threading.Thread(target=_lines_worker, args=(gate, ws), daemon=True).start()
    return {"ok": True}


# ---- سحب كل يوزرات البوابة إلى Excel (خلفيّ، بعدّاد حيّ) ----
# لكل (حساب، بوابة) مهمّةٌ مستقلّة، فيرى كلُّ شخصٍ عدّاد سحبه هو. الحالة تُقرأ
# من /api/users-export/progress كل ثانيةٍ تقريبًا لعرض «جاري السحب… N».
_export_jobs = {}
_export_lock = threading.Lock()


def _export_key(acct_id, gate_id):
    return "%s__%s" % (acct_id, gate_id)


def _all_gate_lines(gate, progress=None):
    """كل يوزرات البوابة للتصدير — بوابةُ ويب (كاسبر/Xtream) أو فالكون."""
    if gate.get("mode") == "falcon":
        return falcon_api.all_lines(gate["api_url"], gate["api_key"], progress)
    return _all_web_lines(gate, progress)


def _export_host(gate):
    """هوست البوابة للتصدير؛ يُحلّ من فالكون إن لم يكن مضبوطًا في البوابة."""
    h = (gate.get("host") or "").strip()
    if h or gate.get("mode") != "falcon":
        return h
    try:
        return falcon_api.host(gate["api_url"], gate["api_key"]) or ""
    except Exception:
        return ""


def _export_worker(acct_id, gate_id, gate, key):
    job = _export_jobs[key]
    try:
        def prog(seen, last=1, page=1):
            job.update({"done": seen, "total": max(seen, (last or 1) * 50)})

        rows = _all_gate_lines(gate, prog)
        n = users_export.replace_all(DATA_DIR, acct_id, gate_id, gate.get("name"),
                                     rows, _export_host(gate))
        job.update({"count": n, "done": n, "total": n})
    except xm_web.CaptchaNeeded:
        job["error"] = "اللوحة تطلب كود تحقّق — سجّل الدخول لها من الصفحة"
    except xm_web.LoginFailed as e:
        job["error"] = str(e)[:200]
    except falcon_api.FalconError as e:
        job["error"] = str(e)[:200]
    except Exception as e:
        job["error"] = str(e)[:200]
    finally:
        job["running"] = False
        job["at"] = time.strftime("%Y-%m-%d %H:%M")


def start_users_export(acct_id, gate_id, gate):
    key = _export_key(acct_id, gate_id)
    with _export_lock:
        j = _export_jobs.get(key)
        if j and j.get("running"):
            return {"ok": False, "running": True, "error": "سحبٌ جارٍ بالفعل"}
        _export_jobs[key] = {"running": True, "done": 0, "total": 0, "count": 0,
                             "error": "", "at": ""}
    threading.Thread(target=_export_worker, args=(acct_id, gate_id, gate, key),
                     daemon=True).start()
    return {"ok": True, "running": True}


def export_progress(acct_id, gate_id):
    j = _export_jobs.get(_export_key(acct_id, gate_id))
    if not j:
        return {"running": False, "idle": True, "done": 0, "total": 0}
    return {k: j.get(k) for k in ("running", "done", "total", "count", "error", "at")}


# ---- سحب يوزرات لوحات المقارنة (خلفيّ) ----
# لكل لوحةٍ بوابتُها (account_id/gate_id)؛ تُسحب يوزراتها كلها وتُخزَّن باسم
# اللوحة، ثم تُقارَن بخطوط سلة. يمرّ على كل اللوحات المضبوطة في طلبةٍ واحدة.
_panels_job = {"running": False, "phase": "", "panel": "", "done": 0, "total": 0,
               "error": "", "at": "", "cancel": False, "results": []}


def _panels_worker(entries, ws):
    results = []
    try:
        for (panel_id, name, gate) in entries:
            if _panels_job["cancel"]:
                break
            _panels_job.update({"phase": "pull", "panel": name, "done": 0, "total": 0})

            def prog(seen, last, page, _n=name):
                _panels_job.update({"done": seen, "total": max(seen, (last or 1) * 50)})

            try:
                rows = _all_web_lines(gate, prog)
                n = panels.save_panel_lines(ws, panel_id, name, rows)
                results.append({"panel": name, "count": n, "ok": True,
                                "error": "" if n else "رجعت اللوحة صفر يوزر — تحقّق من نوع البوابة (casper/Xtream) وبياناتها"})
            except xm_web.CaptchaNeeded:
                results.append({"panel": name, "ok": False,
                                "error": "اللوحة تطلب كود تحقّق"})
            except Exception as e:
                results.append({"panel": name, "ok": False, "error": str(e)[:200]})
            _panels_job["results"] = list(results)
    finally:
        _panels_job.update({"running": False, "phase": "done", "panel": "",
                            "at": renew.now_iso(), "results": results})


def start_panels_pull(st, ws, cfg, accounts):
    if _panels_job["running"]:
        return {"ok": False, "error": "سحبٌ جارٍ بالفعل"}
    cfg = renew.normalize_config(cfg)
    entries = []
    for p in cfg["panels"]:
        acct = next((a for a in accounts
                     if str(a.get("id")) == str(p.get("account_id"))), None)
        gate = find_gate(acct, p.get("gate_id")) if acct else None
        if not gate:
            return {"ok": False, "error": "اللوحة «%s» بلا بوابة مضبوطة" % p["name"]}
        if gate.get("mode") != "web":
            return {"ok": False,
                    "error": "سحب اليوزرات متاح على بوابات جلسة الويب (اللوحة «%s»)" % p["name"]}
        entries.append((p["id"], p["name"], gate))
    if not entries:
        return {"ok": False, "error": "لا لوحات مضبوطة — أضف لوحةً وهوستاتها أولًا"}
    _panels_job.update({"running": True, "owner": ws, "phase": "start", "panel": "",
                        "done": 0, "total": 0, "error": "", "cancel": False, "results": []})
    threading.Thread(target=_panels_worker, args=(entries, ws), daemon=True).start()
    return {"ok": True, "panels": len(entries)}


# ---- تصدير Excel: المقارنة ويوزرات اللوحات ----
_KIND_AR = {
    panels.DURATION_MISMATCH: "فرق مدّة",
    panels.MISSING: "مفقود على اللوحة",
    panels.WRONG_PANEL: "لوحة مختلفة",
    panels.HOST_UNMAPPED: "هوست غير مربوط",
    panels.OK: "مطابق",
}


def _days_arg(v):
    """معامل days من الرابط → عددٌ في [1,365] أو None (فيُستعمل المحفوظ)."""
    try:
        n = int(str(v or "").strip())
        return max(1, min(365, n))
    except (TypeError, ValueError):
        return None


def _compare_xlsx(ws, cfg, days=None):
    res = panels.compare(cfg, ws, days)
    headers = ["الحالة", "اليوزر", "رقم الطلب", "التاريخ", "الهوست", "اللوحة (بالهوست)",
               "وُجد على", "سلة (أشهر)", "اللوحة (أشهر)", "الفرق", "باقة اللوحة",
               "انتهاء اللوحة", "المنتج", "SKU"]
    rows = [[_KIND_AR.get(r["kind"], r["kind"]), r["username"], r["order"], r["date"],
             r["host"], r["panel_name"], r["found_panel_name"], r["store_months"],
             r["panel_months"], r.get("months_diff", ""), r["panel_package"],
             r["panel_exp"], r["product"], r["sku"]] for r in res["rows"]]
    s = res["summary"]
    summary = [["إجمالي خطوط سلة", s.get("store_lines", 0)],
               ["مطابق", s.get(panels.OK, 0)],
               ["فرق مدّة", s.get(panels.DURATION_MISMATCH, 0)],
               ["مفقود على اللوحة", s.get(panels.MISSING, 0)],
               ["لوحة مختلفة", s.get(panels.WRONG_PANEL, 0)],
               ["هوست غير مربوط", s.get(panels.HOST_UNMAPPED, 0)],
               ["بلا يوزر (لا يُطابَق)", s.get("no_username", 0)]]
    return xlsx_write.build_xlsx([("المقارنة", headers, rows),
                                  ("ملخّص", ["البند", "العدد"], summary)])


def _renewal_xlsx(ws, cfg, days=None):
    r = panels.renewal_list(cfg, ws, days)
    headers = ["الحالة", "أيام متبقّية", "اليوزر", "جوال العميل", "رقم الطلب",
               "اللوحة", "انتهاء اللوحة", "المدّة المباعة", "المنتج"]
    rows = [["منتهٍ" if x["expired"] else "قريب الانتهاء", x["days_left"],
             x["username"], x.get("phone", ""), x["order"],
             x["found_panel_name"] or x["panel_name"], x["panel_exp"],
             x["store_months"], x["product"]] for x in r["rows"]]
    return xlsx_write.build_xlsx([("للتجديد", headers, rows)])


def _panel_users_xlsx(ws):
    data = panels.load_panel_lines(ws)["panels"]
    headers = ["اليوزر", "كلمة المرور", "الباقة", "المدة (أشهر)", "الإنشاء",
               "الانتهاء", "الاتصالات", "الحالة"]
    sheets = []
    for pid, p in data.items():
        rows = [[r.get("username", ""), r.get("password", ""), r.get("package", ""),
                 r.get("months", 0), r.get("created", ""), r.get("exp", ""),
                 r.get("connections", ""), r.get("status", "")]
                for r in p.get("by_user", {}).values()]
        sheets.append((p.get("name", pid) or pid, headers, rows))
    if not sheets:
        sheets = [("اليوزرات", headers, [])]
    return xlsx_write.build_xlsx(sheets)


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
    """جلسة ويب لبوابة واحدة، بكوكيز مستقلة على القرص لكل بوابة.

    نكهة كاسبر (c4k وأخواتها) لها صنفها الخاص لأن دخولها وقائمة يوزراتها
    يختلفان عن Xtream؛ وما عداها يبقى على PanelWebSession كما كان."""
    acct = {
        "id": "gate_" + str(gate.get("id", "")),
        "user": gate.get("panel_user", ""),
        "password": gate.get("panel_pass", ""),
        "panel_base": gate.get("panel_base", ""),
        "host": gate.get("host", ""),
    }
    if str(gate.get("web_flavor", "")).lower() == "casper":
        return xm_web.CasperWebSession(acct, DATA_DIR)
    return xm_web.PanelWebSession(acct, DATA_DIR)


def _all_web_lines(gate, progress=None):
    """كل يوزرات بوابة ويب، أيًّا كان نوعها ومهما ضُبط:
      - كاسبر (بالنوع أو بالاكتشاف): صفحاتٌ بترقيم، نشطٌ ومنتهٍ معًا.
      - Xtream: استعلامُ الجدول الفارغ يرجّع الكل (search الفارغ لا يصلح).
    وإن ضُبطت لوحة كاسبر بنوع Xtream خطأً (لا جدول DataTables، فيرجع صفرًا)،
    تُعاد المحاولة كاسبر تلقائيًا على نفس البوابة — فيعمل السحب دون ضبطٍ دقيق."""
    sess = web_session(gate)
    if isinstance(sess, xm_web.CasperWebSession):
        return sess.all_users(views=("", "expired"), progress=progress)
    t = sess._table_query("", 100000, force=True)
    rows = [sess._row_out(r) for r in t["rows"]]
    if not rows:                       # لا جدول DataTables؟ غالبًا لوحة PHP كاسبر
        try:
            csess = web_session({**gate, "web_flavor": "casper"})
            rows = csess.all_users(views=("", "expired"), progress=progress)
        except Exception:
            rows = []
    if progress:
        progress(len(rows), 1, 1)
    return rows


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
    # بلا نمطٍ سهل التخمين (777 · 123 · 987): لوحة مرح ترفض اليوزر «الضعيف».
    return xm_web.rand_digits(n)


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
    # وما ولّدناه (لا ما كتبه المشغّل) تستبدله جلسة الويب إن رفضته اللوحة لضعفه.
    regen = tuple(k for k, v in (("username", username), ("password", password)) if not v)
    username = username or rand_digits(gate_digits(gate))
    password = password or rand_digits(gate_digits(gate))
    vb = virtual_base(pkg["id"])
    if vb and gate.get("mode") == "web":              # باقة افتراضية: إنشاء بالأساس ثم تمديد
        return _create_extended(gate, pkg, vb[0], vb[1], username, password, regen)
    if vb:
        raise RuntimeError("الباقة «%s» (إنشاء + تمديد) متاحة على جلسة الويب فقط" % pkg["name"])
    if gate.get("mode") == "web":                      # الإنشاء عبر نموذج اللوحة
        r = web_session(gate).create_line(pkg["id"], username, password, gate.get("host"), regen=regen)
        line = format_line(gate, r["username"], r["password"])
        _log_txt(gate, line, pkg["name"])
        return {"line": line, "username": r["username"], "password": r["password"],
                "package": pkg["name"], "exp": r.get("exp", ""),
                "verified": r.get("verified", True), "time": r["time"],
                "timing": r.get("timing"), "weak_retries": r.get("weak_retries", 0)}
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


def _create_extended(gate, pkg, base_id, times, username, password, regen=()):
    """يوزر بباقة افتراضية: يُنشأ بالباقة الأساسية ثم يُمدَّد بها `times` مرة.
    فشل التمديد بعد الإنشاء لا يُخفي اليوزر: يُسجَّل في lines.txt بملاحظة واضحة
    ويُرفع خطأ يحمل بياناته (خُصم رصيده فلا يضيع)."""
    sess = web_session(gate)
    r = sess.create_line(base_id, username, password, gate.get("host"), regen=regen)
    u, p = r["username"], r["password"]
    confirmed = bool(r.get("line_id"))   # اللوحة أثبتت وجود اليوزر (id) — لا مجرّد افتراض نجاح
    ends = []
    try:
        for _ in range(times):
            ends.append(sess.extend_line(u, base_id, pkg.get("base_name", ""), line_id=r.get("line_id", "")))
    except (xm_web.CaptchaNeeded, xm_web.LoginFailed):
        raise
    except Exception as e:
        base_name = pkg.get("base_name") or ("باقة " + str(base_id))
        if confirmed:   # اليوزر موجود فعلًا على اللوحة (بالأساسية فقط) — التمديد وحده فشل
            _log_txt(gate, format_line(gate, u, p), base_name + "  [فشل التمديد — بالباقة الأساسية فقط]")
            raise RuntimeError("أُنشئ اليوزر %s / %s بالباقة الأساسية «%s» فقط وفشل تمديده: %s"
                               % (u, p, base_name, str(e)[:160]))
        # لم تؤكّد اللوحة وجود اليوزر (لا id ولا في أحدث الصفوف): قد لا يكون أُنشئ أصلًا.
        _log_txt(gate, format_line(gate, u, p), base_name + "  [غير مؤكَّد — راجع اللوحة]")
        raise RuntimeError("تعذّر تأكيد إنشاء اليوزر %s / %s على اللوحة (قد لا يكون أُنشئ). "
                           "راجع اللوحة وابحث عن الأحدث قبل إعادة المحاولة." % (u, p))
    line = format_line(gate, u, p)
    _log_txt(gate, line, pkg["name"])
    return {"line": line, "username": u, "password": p, "package": pkg["name"],
            "verified": r.get("verified", True), "time": r["time"], "timing": r.get("timing"),
            "weak_retries": r.get("weak_retries", 0),
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
                        "package": pkg["name"], "exp": r.get("exp", ""),
                        "verified": r.get("verified", True), "time": r["time"],
                        "timing": r.get("timing"), "weak_retries": r.get("weak_retries", 0)})
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


# ================= الاشتراكات المجزّأة (٦ · ٣ · شهر من باقة ١٥ شهرًا) =================
# `split_subs.py` يحمل الأجزاء والمواعيد والإشعارات ولا يعرف شيئًا عن اللوحات؛ وهذا
# القسم هو الجسر: يغيّر اسم المستخدم على لوحة الخط (مرح/كاسبر بجلسة ويب، وفالكون)
# ويُرسل بريد الملخّص، ويشغّل الدورة. الميزة لكل عميلٍ على حدة (`split` في حسابه).
SPLIT_MODES = ("web", "falcon")              # مرح وكاسبر (جلسة ويب) وفالكون
SPLIT_TICK = max(1, int(os.environ.get("SPLIT_TICK_SECONDS", "300")))


def split_on(acct):
    """هل فُتحت الميزة لهذا العميل؟ (المدير يفتحها من نافذة الحساب)"""
    return bool(acct and acct.get("split"))


def split_gate_ok(gate):
    return bool(gate) and gate.get("mode") in SPLIT_MODES


def split_base_months(pkg):
    """مدة الباقة بالأشهر كما يقرؤها الاسم (وفالكون باسمها الإنجليزي أيضًا)."""
    months = parse_package_name(pkg.get("name", ""))["months"]
    if not months and pkg.get("name_en"):
        months = parse_package_name(pkg["name_en"])["months"]
    return months


def split_package_ok(pkg):
    """باقةٌ تُجزّأ: مدتها ١٥ شهرًا، وليست افتراضيةً (x2 = ٣٠ شهرًا)."""
    return bool(pkg) and not virtual_base(pkg.get("id")) and split_subs.eligible(split_base_months(pkg))


def split_create_error(acct, gate, pkg, slice_m):
    """سبب رفض إنشاءٍ مجزّأ، أو "" إن صلح."""
    if not split_on(acct):
        return "الاشتراكات المجزّأة غير مفعّلة لهذا الحساب"
    if slice_m not in split_subs.SLICES:
        return "نوع البيع غير صالح"
    if not split_gate_ok(gate):
        return "التجزئة متاحة لبوابات مرح وكاسبر وفالكون فقط"
    if not split_package_ok(pkg):
        return "التجزئة من باقات ١٥ شهرًا فقط"
    return ""


def split_register_created(acct, gate, pkg, slice_m, out):
    """يسجّل الخطوط المُنشأة للتوّ كأجزاء مبيعة. التسجيل مساعدٌ لا يُفشل الإنشاء: ما
    أُنشئ خُصم وسُلِّم، فخطأ التسجيل يُعاد مع الخط ليُسجَّل من الصفحة."""
    months = split_base_months(pkg)
    days = split_subs.load(DATA_DIR, acct["id"])["cfg"].get("remind_days") or 0
    res = []
    for r in out:
        host = (re.search(r"Host\s+(\S+)", r.get("line", "")) or [None, ""])[1] or gate.get("host", "")
        try:
            now = split_subs.now_dt()
            reckoned = renew.add_months(now.date(), months)
            rec, _new = split_subs.register(
                DATA_DIR, acct["id"], gate, r["username"], r["password"], slice_m,
                package=pkg.get("name", ""), base_months=months, host=host,
                expiry=split_subs.trust_expiry(r.get("exp"), reckoned),
                line_id=r.get("line_id", ""), source="create", now=now)
            v = split_subs.decorate(rec)
            due = split_subs.parse_dt(rec["slice"]["due"])
            res.append({"id": rec["id"], "username": rec["username"], "due": rec["slice"]["due"],
                        "months": slice_m, "remaining_after": v.get("remaining_after", 0),
                        # موعد بريد التذكير (قبل التغيير بأيام الإعداد)، "" = بلا تذكير
                        "remind": (due - datetime.timedelta(days=days)).date().isoformat() if days and due else ""})
        except Exception as e:
            res.append({"username": r.get("username", ""), "error": str(e)[:200]})
    return res


def split_change(gate, rec, pend):
    """الجسر: يغيّر اسم مستخدم خطٍّ مجزّأ على لوحته — كلمة المرور كما هي — ويتحقّق.
    يُترجم أعطال اللوحات إلى ما يفهمه split_subs: عابرٌ يُعاد لاحقًا (Transient)،
    ومرفوضٌ قبل أي إرسال يدويّ (Unsupported)، وما سواهما بعد الإرسال «راجع اللوحة»."""
    mode, name = gate.get("mode"), gate.get("name", "")
    try:
        if mode == "web":
            return web_session(gate).edit_line(rec["username"], pend["username"],
                                               line_id=rec.get("line_id", ""), package=rec.get("package", ""))
        if mode == "falcon":
            return falcon_api.rename_line(gate["api_url"], gate["api_key"], rec["username"],
                                          pend["username"], line_id=rec.get("line_id", ""))
        raise split_subs.Unsupported("بوابات Reseller API خارج هذا النظام — غيّر اسم المستخدم من اللوحة ثم أكّد")
    except xm_web.CaptchaNeeded:
        raise split_subs.Transient("اللوحة تطلب كود تحقّق — افتح صفحة الإنشاء وادخل بوابة «%s» ليُكمَل التغيير" % name)
    except xm_web.EditUnsupported as e:
        raise split_subs.Unsupported(str(e))
    except xm_web.LoginFailed as e:
        raise split_subs.Transient("تعذّر الدخول إلى لوحة «%s»: %s" % (name, e))
    except falcon_api.FalconUnsupported as e:
        raise split_subs.Unsupported(str(e))
    except falcon_api.FalconOffline as e:
        raise split_subs.Transient(str(e))
    except OSError as e:                       # URLError ومهلة الشبكة: اللوحة لم تردّ
        raise split_subs.Transient("تعذّر الوصول إلى لوحة «%s»: %s" % (name, getattr(e, "reason", e)))


def split_find_line(gate, username):
    """الخط كما تُظهره لوحته الآن: {password, exp, line_id} أو {} إن لم يوجد."""
    username = str(username or "").strip()
    if gate.get("mode") == "web":
        rows = web_session(gate).search(username)
    elif gate.get("mode") == "falcon":
        rows = falcon_api.search(gate["api_url"], gate["api_key"], username)
    else:
        rows = []
    r = next((x for x in rows if str(x.get("username", "")).strip() == username), None)
    return {"password": str(r.get("password") or ""), "exp": r.get("exp") or "",
            "line_id": str(r.get("id") or "")} if r else {}


def split_texts(acct, gate, rec):
    """ما يُنسخ للعميل التالي ببيانات الخط الحالية: السطر، ونصّ الشرح إن فعّله المدير
    لهذا العميل (بنفس خانات صفحة الإنشاء: {host} {user} {pass} {guide} {server})."""
    g = dict(gate)
    g["host"] = rec.get("host") or gate.get("host", "")
    if not g.get("guide_url") and acct.get("guide_url"):
        g["guide_url"] = acct["guide_url"]
    out = {"line": format_line(g, rec.get("username", ""), rec.get("password", "")), "message": ""}
    text = guide_text_of(acct)
    if text:
        vals = {"host": g["host"], "user": rec.get("username", ""), "pass": rec.get("password", ""),
                "guide": g.get("guide_url", ""), "server": guide_sub(g, g.get("guide_url", ""))}
        out["message"] = re.sub(r"\{(host|user|pass|guide|server)\}", lambda m: vals[m.group(1)], text)
    return out


class _SplitBridge:
    change = staticmethod(split_change)


SPLIT_BRIDGE = _SplitBridge()


def _split_alert(st, acct):
    """(إعداد البريد، مصدره): بريد تنبيه الحساب (إعداد التجديد في مساحته)، وإلا بريد
    المدير — ومصدره "account" أو "admin" أو "" إن لم يُضبط أيّهما."""
    own = renew.normalize_config((acct or {}).get("renew"))["alert"]
    if own.get("host") and own.get("to"):
        return own, "account"
    adm = renew.normalize_config(st.get("renew"))["alert"]
    if adm.get("host") and adm.get("to"):
        return adm, "admin"
    return None, ""


def split_mailer(st, acct):
    """mailer لـ split_subs: (الموضوع، النص) → (نجح؟، الخطأ)؛ None = لا بريد مضبوط."""
    alert, _src = _split_alert(st, acct)
    if not alert:
        return lambda subject, body: (None, "بريد التذكير غير مضبوط — اضبط «بريد التنبيه» في صفحة التجديد")

    def send(subject, body):
        try:
            renew._smtp_send(alert, subject, body)   # خادم البريد نفسه الذي ينبّه بانقطاع مرح
            return True, ""
        except Exception as e:
            return False, str(e)[:200]
    return send


def split_mail_status(st, acct, role):
    alert, src = _split_alert(st, acct)
    if not alert:
        return {"configured": False}
    # بريد المدير لا يُكشف لحساب عميل — يكفيه أن يعرف أن التذكير يصل إلى المدير.
    return {"configured": True, "source": src,
            "to": alert["to"] if (role == "admin" or src == "account") else ""}


def split_page_url():
    return ("https://%s/remaining" % ADMIN_HOST) if ADMIN_HOST else \
        ("https://%s%s/remaining" % (SITE_HOST, ADMIN_PATH))


def split_flush_async(st, acct):
    """يرسل بريد ما جدّ لهذا العميل الآن — في خيطٍ مستقل فلا تنتظر الصفحةُ خادمَ البريد.
    لما يفعله المشغّل بيده («غيّر الآن»، بريدٌ تجريبي نجح)؛ والدورة تكفي ما عداه."""
    def run():
        try:
            split_subs.flush_mail(DATA_DIR, acct["id"], split_mailer(st, acct),
                                  page_url=split_page_url(), title=acct.get("name", ""))
        except Exception:
            pass                               # البريد مساعدٌ لا يُفشل شيئًا؛ والدورة تعيده
    threading.Thread(target=run, daemon=True).start()


def split_tick(now=None):
    """دورةٌ واحدة لكل عميلٍ فُتحت له الميزة: تذكير، ثم تغيير اسم ما حان جزؤه، ثم بريد."""
    st = load_store()
    out = {}
    for a in st["accounts"]:
        if not split_on(a) or not split_subs.has_data(DATA_DIR, a["id"]):
            continue
        gates = {str(g.get("id")): g for g in (a.get("gates") or [])}
        try:
            out[a["id"]] = split_subs.process(DATA_DIR, a["id"], gates, SPLIT_BRIDGE, now=now,
                                              mailer=split_mailer(st, a), page_url=split_page_url(),
                                              title=a.get("name", ""))
        except Exception as e:                  # حسابٌ متعثّر لا يوقف البقية
            out[a["id"]] = {"error": str(e)[:200]}
    return out


def _split_loop():
    while True:
        time.sleep(SPLIT_TICK)
        try:
            split_tick()
        except Exception:
            pass


def start_split_worker():
    threading.Thread(target=_split_loop, daemon=True).start()


# ============================ مسابقة التوقّعات ============================
# الفرز آليٌّ في دورة كل دقيقة: كل مسابقةٍ انتهت مباراتها تُفرز ويُبلَّغ فائزوها على
# واتساب بقناة خدمة سلة نفسها. وأول زائرٍ لصفحة المباراة بعد النهاية يسبق الدورة إن سبقها.
CONTEST_TICK = 60


def cup_match(eid):
    """مباراةٌ من البطولات بمعرّفها من كاش ESPN، أو None."""
    eid = contest.eid_of(eid)
    if not eid:
        return None
    for t in CUPS:
        m = next((m for m in (t._feed.get()[0] or {}).get("matches", []) if m["id"] == eid), None)
        if m:
            return m
    return None


def contest_link(rec):
    mt = rec.get("match") or {}
    return f"https://{SITE_HOST}{contest.cup_path(mt)}/{mt.get('slug') or rec['eid']}#predict"


# خدمة واتساب النظام اللوجستي (whatsapp-reader): جلسة المسابقة فيها، تُربط بـ QR من صفحة المدير.
CONTEST_INBOUND_URL = os.environ.get("CONTEST_INBOUND_URL", "").strip()   # للاختبار؛ وإلا من SITE_HOST
_reader_cache = {"at": 0.0, "d": None}
READER_DIR = os.path.join(BASE_DIR, "whatsapp-reader")
_embed = {"proc": None, "why": "", "started": 0.0}


def contest_inbound_url():
    """أين تمرّر الخدمة رسائل رقم المسابقة: المدمجة من داخل الحاوية، والخارجية بالرابط العام."""
    if CONTEST_INBOUND_URL:
        return CONTEST_INBOUND_URL
    if contest.reader_config(DATA_DIR)["embedded"]:
        return f"http://127.0.0.1:{PORT}/api/contest/wa-inbound"
    return f"https://{SITE_HOST}/api/contest/wa-inbound"


def start_embedded_reader():
    """نسخة whatsapp-reader (خدمة النظام اللوجستي) داخل الحاوية على 127.0.0.1، بسرٍّ مولَّد وجلساتٍ
    في مجلد البيانات الدائم — فربط رقم المسابقة رقمٌ ثم رمز QR، بلا إعداد. تُعاد إن توقّفت. ولا تعمل
    إن ضُبطت خدمةٌ خارجية (WHATSAPP_READER_URL) أو لم تُثبَّت (node ومكتباتها)."""
    import shutil
    import subprocess
    cfg = contest.reader_config(DATA_DIR)
    if not cfg["embedded"]:
        return
    node, server = shutil.which("node"), os.path.join(READER_DIR, "server.js")
    if not node or not os.path.isfile(server) or not os.path.isdir(os.path.join(READER_DIR, "node_modules")):
        _embed["why"] = "خدمة الواتساب غير مثبّتة على هذا الخادم (node ومكتباتها)"
        return
    data = os.path.join(DATA_DIR, "wa-reader")
    os.makedirs(data, exist_ok=True)
    env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "HOME": data, "NODE_ENV": "production",
           "PORT": str(contest.EMBED_PORT), "WHATSAPP_READER_SECRET": cfg["secret"],
           "READER_DATA_DIR": os.path.join(data, "sessions"), "LOG_LEVEL": "warn",
           "READER_DISK_FLOOR_BYTES": str(64 * 1024 * 1024)}

    def loop():
        wait = 5
        while True:
            logf = os.path.join(data, "reader.log")
            try:
                if os.path.getsize(logf) > 2 * 1024 * 1024:
                    os.replace(logf, logf + ".1")
            except OSError:
                pass
            t0 = time.time()
            try:
                with open(logf, "ab") as out:
                    p = subprocess.Popen([node, server], cwd=READER_DIR, env=env, stdout=out, stderr=out,
                                         stdin=subprocess.DEVNULL)
                    _embed.update(proc=p, why="", started=t0)
                    code = p.wait()
                _embed["why"] = f"توقّفت خدمة الواتساب (رمز {code}) — تُعاد تلقائيًّا"
            except Exception as e:                  # لا تُسقط الخادم أبدًا
                _embed["why"] = "تعذّر تشغيل خدمة الواتساب: " + str(e)[:160]
            _embed["proc"] = None
            _reader_cache["d"] = None
            wait = 5 if time.time() - t0 > 300 else min(wait * 2, 300)
            time.sleep(wait)

    threading.Thread(target=loop, daemon=True).start()


def reader_call(method, path, body=None, timeout=15):
    """نداءٌ لخدمة الواتساب بسرّها ← (رمز HTTP أو 0، الرد أو {}، الخطأ)."""
    cfg = contest.reader_config(DATA_DIR)
    if not cfg["url"] or not cfg["secret"]:
        return 0, {}, "not_configured"
    data = json.dumps(body).encode() if body is not None else None
    rq = Request(cfg["url"] + path, data=data, method=method,
                 headers={"X-Reader-Secret": cfg["secret"], "Content-Type": "application/json",
                          "Accept": "application/json"})
    try:
        with urlopen(rq, timeout=timeout) as r:
            return r.getcode(), json.loads(r.read().decode("utf-8", "replace") or "{}"), ""
    except HTTPError as e:
        raw = e.read().decode("utf-8", "replace") if e.fp else ""
        try:
            d = json.loads(raw or "{}")
        except ValueError:
            d = {}
        return e.code, d, f"HTTP {e.code}: {(d.get('error') if isinstance(d, dict) else '') or raw[:160]}"
    except Exception as e:                      # شبكة، شهادة، مهلة
        return 0, {}, str(getattr(e, "reason", e))[:300]


def reader_status(fresh=False):
    """حال جلسة المسابقة في الخدمة ← {configured, ok, status, number, qr, error} — دقيقة في
    الذاكرة لزوّار الموقع، وطازجةٌ لصفحة المدير."""
    now = time.time()
    c = _reader_cache
    if not fresh and c["d"] is not None and now - c["at"] < (60 if c["d"].get("ok") else 20):
        return dict(c["d"])
    code, d, err = reader_call("GET", "/sessions/" + contest.READER_TENANT, timeout=10)
    if err == "not_configured":
        out = {"configured": False, "ok": False, "status": "", "number": "", "qr": None,
               "error": "WHATSAPP_READER_SECRET غير مضبوط مع WHATSAPP_READER_URL"}
    elif code == 0 and contest.reader_config(DATA_DIR)["embedded"] and (
            not _embed["proc"] or time.time() - _embed["started"] < 20):
        out = {"configured": True, "ok": False, "status": "", "number": "", "qr": None,
               "error": _embed["why"] or "خدمة الواتساب تبدأ الآن… أعد المحاولة بعد لحظات"}
    elif code == 200:
        out = {"configured": True, "ok": True, "status": str(d.get("status") or ""),
               "number": re.sub(r"\D", "", str(d.get("number") or "")), "qr": d.get("qr"),
               "version": str(d.get("version") or ""), "error": ""}
    else:
        out = {"configured": True, "ok": False, "status": "", "number": "", "qr": None,
               "error": "الخدمة رفضت السر (403) — طابِق WHATSAPP_READER_SECRET" if code == 403 else err}
    c.update(at=now, d=out)
    return dict(out)


def contest_wa_number(st=None):
    """الرقم الذي تُرسل إليه رسائل التوقّع: رقم جلسة المسابقة وهي متصلة، وإلا لا تسجيل."""
    r = reader_status()
    return r["number"] if r.get("status") == "connected" else ""


def reader_send(to, text):
    """رسالةٌ من رقم المسابقة ← {ok, error}."""
    code, d, err = reader_call("POST", f"/sessions/{contest.READER_TENANT}/send", {"to": to, "body": text})
    if code == 200:
        return {"ok": True}
    return {"ok": False, "error": {"not_connected": "رقم المسابقة غير مربوط", "not_on_whatsapp": "الرقم ليس على واتساب",
                                   "no_session": "رقم المسابقة غير مربوط"}.get(d.get("error"), err or "تعذّر الإرسال")}


def contest_notify(rec):
    """رسائل الفرز: للفائزين (إن فُعّل التبليغ) ولرقم المدير — من رقم المسابقة، وتُسجَّل نتيجة كلٍّ منها."""
    try:
        out = []
        for msg in contest.messages(rec, contest.load_settings(DATA_DIR), contest_link(rec)):
            r = reader_send(msg["to"], msg["text"])
            out.append({"to": msg["to"], "kind": msg["kind"], "n": msg.get("n"), "ok": bool(r.get("ok")),
                        "dry": False, "error": str(r.get("error") or "")[:200]})
        if out:
            contest.mark_sent(DATA_DIR, rec["eid"], out)
        return out
    except Exception as e:                  # التبليغ لا يُسقط الفرز؛ ويُعاد من صفحة المدير
        return [{"ok": False, "error": str(e)[:200]}]


def store_products(st, fresh=False):
    """منتجات المتجر لاختيار الجائزة: بالرمز الإداري إن وُجد، وإلا الواجهة العامة ومعها باقات الدليل."""
    ids = [p["id"] for b in tournament._catalog().values() for p in b.get("plans", [])]
    return store_sitemap.products(renew_salla_token(st), ids, fresh=fresh)


def contest_tick(now=None):
    """دورةٌ واحدة ← معرّفات ما فُرز فيها."""
    ids = contest.waiting(DATA_DIR)
    if not ids:
        return []                           # لا مسابقة تنتظر: لا نداء لـ ESPN
    ms = {m["id"]: m for m in cup_matches()[0]}
    done = []
    for eid in ids:
        rec, drawn = contest.settle(DATA_DIR, eid, ms.get(eid), now)
        if drawn:
            done.append(eid)
            contest_notify(rec)
    return done


def _contest_loop():
    while True:
        time.sleep(CONTEST_TICK)
        try:
            contest_tick()
        except Exception:
            pass


def start_contest_worker():
    threading.Thread(target=_contest_loop, daemon=True).start()


CONTENT_TICK = 600                  # كل عشر دقائق: أيّ سيرفرٍ له رابط M3U مرّ يومٌ على محتواه يُسحب


def _content_loop():
    time.sleep(60)                  # بعد الإقلاع بدقيقة، لا معه
    while True:
        try:
            content.tick(DATA_DIR)
        except Exception:
            pass
        time.sleep(CONTENT_TICK)


def start_content_worker():
    threading.Thread(target=_content_loop, daemon=True).start()


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
            return self._send(200, raw=guide_pages.sitemap(league.SITEMAP + watch.SITEMAP
                                                           + [(predict_page.PATH, "daily", "0.7")]
                                                           + [u for t in CUPS for u in t.sitemap()]
                                                           + content.sitemap(DATA_DIR)),
                              ctype="application/xml; charset=utf-8",
                              extra={"Cache-Control": PUBLIC_HTML_CACHE})
        if path in ROOT_FILES:
            return self._static("/static/" + ROOT_FILES[path])
        if path == "/api/stats":
            return self._send(200, {"m3u": int(load_stats().get("m3u", 0))})
        if path == "/api/league":               # بطاقة ترتيب الدوريات في الرئيسية
            t = league.api(self._q("l"))        # الفشل لا يُحفظ في المتصفح فيُعاد مع الزيارة التالية
            if t is None:
                return self._send(404, {"ok": False, "error": "unknown league"})
            return self._send(200, t, extra={"Cache-Control": "public, max-age=300" if t["ok"] else "no-store"})
        if path == predict_page.PATH:           # مسابقة التوقّعات: البطولتان، والفائزون، والشروط
            code, body, age = predict_page.render(HUB_CUPS, contest.summaries(DATA_DIR), tv_map())
            return self._send(code, raw=body, ctype="text/html; charset=utf-8",
                              extra={"Cache-Control": f"public, max-age={age}"})
        for t in CUPS:                          # البطولات: صفحتها وودجتها ومسابقتها ومبارياتها
            page = self._cup_page(t, path)
            if page is not None:
                return page
        if path == "/api/contest":              # حال مسابقة المباراة (للبطاقة في صفحتها)
            return self._contest_public()
        if path == "/api/contest/ticket":       # الصفحة تنتظر رسالة الواتساب برمزها
            return self._send(200, contest.ticket_status(DATA_DIR, self._q("m"), self._q("c")))
        if path in ("/standings", "/standings/"):
            return self._redirect(league.PATH + league.DEFAULT, 301)
        if path.startswith(league.PATH):        # صفحة ترتيب لكل دوري (للأرشفة)
            page = league.render(path[len(league.PATH):])
            if page:
                code, body = page
                return self._send(code, raw=body, ctype="text/html; charset=utf-8",
                                  extra={"Cache-Control": "public, max-age=300"} if code == 200
                                  else {"Retry-After": str(league.RETRY)})
        if path == watch.PATH + "/":
            return self._redirect(watch.PATH, 301)
        if path == watch.PATH or path.startswith(watch.PATH + "/"):   # المشاهدة: المدخل وصفحة لكل دوري وبطولة
            page = (watch.render_hub(CUPS) if path == watch.PATH
                    else watch.render(path[len(watch.PATH) + 1:], CUPS))
            if page:
                code, body, age = page
                return self._send(code, raw=body, ctype="text/html; charset=utf-8",
                                  extra={"Cache-Control": f"public, max-age={age}"} if code == 200
                                  else {"Retry-After": str(league.RETRY)})
        if path in (content.PATH, content.PATH + "/"):   # محتوى الاشتراكات: إلى أول سيرفرٍ له محتوى
            key = content.first_key(DATA_DIR)
            if key:
                return self._redirect(f"{content.PATH}/{key}{qs}")
            code, body = content.render_missing(DATA_DIR)
            return self._send(code, raw=body, ctype="text/html; charset=utf-8",
                              extra={"Cache-Control": "public, max-age=300"})
        if path.startswith(content.PATH + "/"):     # صفحة سيرفر: المسلسلات بمواسمها والأفلام والقنوات، والبحث
            code, body, age = content.render(DATA_DIR, content.key_ok(path[len(content.PATH) + 1:].strip("/")),
                                             {k: self._q(k) for k in ("t", "g", "p", "q")})
            return self._send(code, raw=body, ctype="text/html; charset=utf-8",
                              extra={"Cache-Control": f"public, max-age={age}"})
        if path == "/api/content":              # الرئيسية ومسار الشراء: السيرفرات التي لها محتوى وأعدادها
            b = content.brief(DATA_DIR)           # والفارغ لا يُحفظ في المتصفح: يظهر الرابط فور أول ملف
            return self._send(200, b, extra={"Cache-Control": "public, max-age=300" if b["servers"] else "no-store"})
        if path in ("/api/content/group", "/api/content/search"):   # قسمٌ يُفتح في مكانه · البحث بالاسم
            key = content.key_ok(self._q("s"))
            if path.endswith("/search"):
                res = content.api_search(DATA_DIR, key, self._q("q"))
            else:
                try:
                    page = int(self._q("p") or 1)
                except ValueError:
                    page = 1
                res = content.api_group(DATA_DIR, key, self._q("t"), self._q("g"), page)
            if res is None:
                return self._send(404, {"ok": False, "error": "not found"})
            return self._send(200, res, extra={"Cache-Control": "public, max-age=600"})
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
            _save_sessions()
            return self._send(302, raw=b"", ctype="text/plain",
                              extra={"Location": self._url("/login"), **self._set_cookie("", clear=True)})
        role, acct = self._who(st)
        if path == "/login":
            return self._redirect(self._url()) if role else self._page(PAGES["/login"])
        if not role:
            return self._deny(path)
        # مساحة renew لهذه الجلسة: الأدمن عامّة، والحساب معزولة (انظر renew_ws).
        rws, rown = renew_ws(role, acct)
        rcfg = renew_cfg(st, rown)
        racs = st["accounts"] if role == "admin" else ([acct] if acct else [])
        try:
            if path == "/":
                return self._redirect(self._url("/accounts")) if role == "admin" else self._page(PAGES["/"])
            if path == "/accounts":
                return self._page(PAGES["/accounts"]) if role == "admin" else self._send(403, {"error": "للمدير فقط"})
            if path == "/api/me":
                gates = [{"id": g["id"], "name": g["name"], "mode": g["mode"],
                          "host": g["host"], "guide_url": g.get("guide_url", ""),
                          "digits": gate_digits(g), "point_cost": g.get("point_cost", ""),
                          "web_flavor": g.get("web_flavor", ""),
                          "guide_sub": guide_sub(g, g.get("guide_url") or acct.get("guide_url", ""))}
                         for g in (acct.get("gates", []) if acct else [])]
                return self._send(200, {"role": role, "account": acct["name"] if acct else None,
                                        "guide_url": acct.get("guide_url", "") if acct else "",
                                        "guide_text": guide_text_of(acct),
                                        "split": split_on(acct),
                                        "split_slices": list(split_subs.SLICES) if split_on(acct) else [],
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
                # روابط الاستبدال (قديم↔جديد) لهذا الرقم — لتتبّع «استُبدل بـ / بديل عن»
                links = user_links.find(DATA_DIR, acct["id"], gate["id"], q)
                if gate.get("mode") == "falcon":
                    return self._send(200, {"results": falcon_api.search(gate["api_url"], gate["api_key"], q), "links": links})
                if gate.get("mode") == "web":     # بحث جدول اللوحة نفسه
                    try:
                        return self._send(200, {"results": annotate_package_type(gate, web_session(gate).search(q)), "links": links})
                    except xm_web.CaptchaNeeded:
                        return self._send(200, {"results": [], "links": links, "need_login": True})
                    except xm_web.LoginFailed as e:
                        return self._send(200, {"results": [], "links": links, "login_error": str(e)})
                    except Exception:
                        return self._send(200, {"results": [], "links": links, "error": "تعذّر البحث في اللوحة"})
                return self._send(200, {"results": [], "links": links, "unsupported": True})
            if path == "/api/users-export/status":   # حالة ملف الإكسل لهذه البوابة
                gate = find_gate(acct, self._q("gate")) if acct else None
                if role != "account" or not gate:
                    return self._send(403, {"error": "غير متاح"})
                return self._send(200, users_export.status(DATA_DIR, acct["id"], gate["id"]))
            if path == "/api/users-export/progress":  # تقدّم السحب الحيّ (عدّاد)
                gate = find_gate(acct, self._q("gate")) if acct else None
                if role != "account" or not gate:
                    return self._send(403, {"error": "غير متاح"})
                return self._send(200, export_progress(acct["id"], gate["id"]))
            if path == "/api/users-export/download":  # تنزيل ملف الإكسل المحفوظ
                gate = find_gate(acct, self._q("gate")) if acct else None
                if role != "account" or not gate:
                    return self._send(403, {"error": "غير متاح"})
                _jsonl, xlsx_path = users_export.paths(DATA_DIR, acct["id"], gate["id"])
                if not os.path.exists(xlsx_path):
                    return self._send(404, {"error": "لا يوجد ملف بعد — اسحب اليوزرات أولًا"})
                fn = "users-%s.xlsx" % re.sub(r"[^A-Za-z0-9_.-]+", "_", str(gate.get("name") or gate["id"]))
                with open(xlsx_path, "rb") as f:
                    return self._send(200, raw=f.read(),
                                      ctype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                      extra={"Content-Disposition": 'attachment; filename="%s"' % fn,
                                             "Cache-Control": "no-store"})
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
                if split_on(acct) and split_gate_ok(gate):   # باقات ١٥ شهرًا تُباع أجزاءً
                    for p in pkgs:
                        if split_package_ok(p):
                            p["split"] = True
                return self._send(200, {**base, "packages": pkgs})
            if path == "/content" or path.startswith("/api/content/"):   # محتوى السيرفرات من ملفات M3U (للمدير)
                if role != "admin":
                    return self._send(403, {"error": "للمدير فقط"})
                if path == "/content":
                    return self._page("content_admin.html")
                if path == "/api/content/admin":
                    return self._send(200, content.admin_state(DATA_DIR))
                return self._send(404, {"error": "not found"})
            if path == "/contest" or path.startswith("/api/contest/"):   # مسابقة التوقّعات (للمدير)
                if role != "admin":
                    return self._send(403, {"error": "للمدير فقط"})
                return self._page("contest_admin.html") if path == "/contest" else self._contest_admin_get(path)
            if path == "/remaining":              # الحسابات المتبقية (الاشتراكات المجزّأة)
                if role == "account" and not split_on(acct):
                    return self._redirect(self._url())
                return self._page("remaining.html")
            if path == "/api/split/state":
                return self._send(200, self._split_state(st, role, acct))
            if path == "/api/split/notes":        # الجرس: عدد غير المقروء وأحدث الإشعارات
                return self._send(200, self._split_notes(st, role, acct))
            if path == "/api/accounts":
                if role != "admin":
                    return self._send(403, {"error": "للمدير فقط"})
                return self._send(200, {"accounts": [redact_account(a) for a in st["accounts"]],
                                        "default_guide_text": DEFAULT_GUIDE_TEXT})
            if path == "/api/service":
                if role != "admin":
                    return self._send(403, {"error": "للمدير فقط"})
                return self._send(200, redact_service(st["service"]))
            if path == "/api/renew/config":       # إعداد المساحة (الأدمن أو الحساب لنفسه)
                return self._send(200, {"renew": renew.redact_config(rcfg),
                                        "index": renew.index_stats(rws),
                                        "tiers": list(renew.TIERS),
                                        "is_admin": role == "admin"})
            if path == "/renew":                  # صفحة الرفع والتحليل والإعداد
                return self._page("renew_admin.html")
            if path == "/api/renew/analysis":      # آخر تحليل محفوظ
                return self._send(200, {"analysis": renew.load_analysis(rws),
                                        "index": renew.index_stats(rws)})
            if path == "/api/renew/report":        # التحليل صفحةً تُحفَظ وتُرسَل
                agg = renew.load_analysis(rws)
                if not agg:
                    return self._send(404, {"error": "لا تحليل بعد — ارفع الملفات أولًا"})
                return self._send(200, raw=renew_import.report_html(agg).encode(),
                                  ctype="text/html; charset=utf-8",
                                  extra={"Content-Disposition":
                                         'attachment; filename="renew-analysis.html"'})
            if path == "/api/renew/extension.zip":  # إضافة المتصفّح جاهزة للتحميل
                data = build_extension_zip()
                if not data:
                    return self._send(404, {"error": "ملف الإضافة غير متوفّر"})
                return self._send(200, raw=data, ctype="application/zip",
                                  extra={"Content-Disposition":
                                         'attachment; filename="salla-cookie-extension.zip"',
                                         "Cache-Control": "no-store"})
            if path == "/api/renew/packages":     # باقات مرح بنقاطها (للربط والتكلفة)
                try:
                    pkgs, cost = renew_packages(rcfg, racs)
                except xm_web.CaptchaNeeded:
                    return self._send(200, {"packages": [],
                                            "error": "اللوحة تطلب كود تحقّق — سجّل الدخول لها من صفحة الإنشاء"})
                except Exception as e:
                    return self._send(200, {"packages": [], "error": str(e)[:200]})
                return self._send(200, {"packages": pkgs, "point_cost": cost})
            if path == "/api/renew/lines-status":  # تقدّم تصدير خطوط اللوحة
                return self._send(200, {**_own_job(_lines_job, rws),
                                        "saved": renew.lines_stats(rws)})
            if path == "/api/renew/panels":       # لوحات المقارنة وهوستاتها + خيارات البوابات
                cfg = renew.normalize_config(rcfg)
                gates = [{"account_id": a["id"], "account": a.get("name", ""),
                          "gate_id": g["id"], "gate": g.get("name", ""),
                          "mode": g.get("mode"), "flavor": g.get("web_flavor", "")}
                         for a in racs for g in (a.get("gates") or [])
                         if g.get("mode") == "web"]
                return self._send(200, {"panels": cfg["panels"], "gates": gates,
                                        "lines": panels.panel_lines_stats(rws),
                                        "store": {k: v for k, v in
                                                  panels.load_store_lines(rws).items()
                                                  if k != "lines"}})
            if path == "/api/renew/panels-status":  # تقدّم سحب يوزرات اللوحات
                return self._send(200, {**_own_job(_panels_job, rws),
                                        "saved": panels.panel_lines_stats(rws)})
            if path == "/api/renew/compare":       # نتيجة المطابقة (سلة ↔ اللوحات)
                return self._send(200, panels.compare(rcfg, rws, _days_arg(self._q("days"))))
            if path == "/api/renew/compare.xlsx":   # المطابقة ملفَّ Excel
                return self._send(200, raw=_compare_xlsx(rws, rcfg, _days_arg(self._q("days"))),
                                  ctype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                  extra={"Content-Disposition":
                                         'attachment; filename="salla-vs-panels.xlsx"'})
            if path == "/api/renew/users.xlsx":     # كل يوزرات اللوحات المسحوبة Excel
                return self._send(200, raw=_panel_users_xlsx(rws),
                                  ctype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                  extra={"Content-Disposition":
                                         'attachment; filename="panel-users.xlsx"'})
            if path == "/api/renew/renewal":       # العملاء المستحقّون للتجديد
                return self._send(200, panels.renewal_list(rcfg, rws, _days_arg(self._q("days"))))
            if path == "/api/renew/renewal.xlsx":   # قائمة التجديد Excel
                return self._send(200, raw=_renewal_xlsx(rws, rcfg, _days_arg(self._q("days"))),
                                  ctype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                  extra={"Content-Disposition":
                                         'attachment; filename="renewal-due.xlsx"'})
            if path == "/api/renew/harvest-status":
                if role != "admin":
                    return self._send(403, {"error": "للمدير فقط"})
                return self._send(200, {**_harvest,
                                        "saved": renew.harvest_stats(DATA_DIR)})
            if path == "/api/renew/pull-status":   # تقدّم السحب من سلة
                return self._send(200, {**_own_job(_pull, rws),
                                        "has_token": bool(renew_salla_token(st, rcfg))})
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
            if path == "/api/service/salla-status":   # حالة ربط سلة (الجلسة المشتركة)
                if role != "admin":
                    return self._send(403, {"error": "للمدير فقط"})
                cookie = salla_service_cookie(st)
                if not cookie:
                    return self._send(200, {"connected": False})
                out = {"connected": True, "cookies": len(salla_web.cookie_names(cookie))}
                try:
                    alive, why = salla_web.Session(cookie).alive()
                    out["alive"] = alive
                    if not alive:
                        out["alive_error"] = why
                    else:
                        try:
                            out["orders"] = len(salla_web.Session(cookie).recent_orders(25))
                        except Exception:
                            out["orders"] = None
                except Exception as e:
                    out["alive"] = False
                    out["alive_error"] = str(e)[:200]
                return self._send(200, out)
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




    def _renew_upload(self, st, ws):
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
        renew.save_analysis(ws, agg)
        panels.save_store_lines(ws, units)     # ليغذّي المقارنة من الملفات أيضًا
        applied = False
        if yes("apply"):                       # اعتماده فهرسًا تعمل عليه الصفحة العامة
            renew.save_index(ws, renew_import.build_index(units, meta))
            applied = True
        return self._send(200, {"ok": True, "applied": applied, "analysis": agg,
                                "index": renew.index_stats(ws)})

    # ---------- تجديد الاشتراك: عمليات المساحة (أدمن أو حساب لنفسه) ----------
    def _renew_admin(self, path, st, role, acct):
        req = self._body()
        rws, rown = renew_ws(role, acct)
        rcfg = renew_cfg(st, rown)
        racs = st["accounts"] if role == "admin" else ([acct] if acct else [])
        owner = rown or st                        # مالك الإعداد: acct للحساب، st للأدمن

        if path == "/api/renew/config":
            owner["renew"] = renew.clean_config(req.get("renew") or {}, rcfg)
            save_store(st)
            return self._send(200, {"ok": True, "renew": renew.redact_config(owner["renew"])})
        if path == "/api/renew/pull":             # سحب الطلبات من سلة مباشرة
            return self._send(200, start_renew_pull(
                st, rws, rcfg, with_history=req.get("with_history", True),
                apply_index=req.get("apply", True)))
        if path == "/api/renew/lines-export":
            return self._send(200, start_lines_export(st, rws, rcfg, racs, req.get("side", "source")))
        if path == "/api/renew/lines-cancel":
            _lines_job["cancel"] = True
            return self._send(200, {"ok": True})
        if path == "/api/renew/panels":           # حفظ لوحات المقارنة وهوستاتها
            cur = renew.normalize_config(rcfg)
            cur["panels"] = renew.normalize_panels(req.get("panels"))
            owner["renew"] = renew.clean_config(cur, rcfg)
            save_store(st)
            return self._send(200, {"ok": True,
                                    "panels": renew.normalize_config(owner["renew"])["panels"]})
        if path == "/api/renew/panel-cookie":     # ضبط كوكيز لوحة سلة وحدها — من إضافة المتصفح
            # طريق ثانٍ للصق «Copy as cURL»: الإضافة تقرأ كوكيز s.salla.sa من
            # المتصفّح وترسلها هنا (بترويسة Basic، فتمرّ بـ `_who` كأي أداة).
            # نضبط `panel_cookie` وحده ونُبقي بقية الإعداد كما هو عبر clean_config.
            raw = req.get("cookie") or req.get("curl") or ""
            cookie = salla_web.clean_cookie(raw)
            if not cookie:
                return self._send(400, {"error": "لا كوكيز في المُرسَل"})
            cur = renew.normalize_config(rcfg)
            cur["panel_cookie"] = cookie
            owner["renew"] = renew.clean_config(cur, rcfg)
            save_store(st)
            resp = {"ok": True, "cookies": len(salla_web.cookie_names(cookie))}
            if req.get("test"):                    # اختبار فوري اختياري للإضافة
                try:
                    alive, why = salla_web.Session(cookie).alive()
                    resp["alive"] = alive
                    if not alive:
                        resp["alive_error"] = why
                except Exception as e:
                    resp["alive"] = False
                    resp["alive_error"] = str(e)[:200]
            return self._send(200, resp)
        if path == "/api/renew/panels-pull":      # سحب يوزرات كل اللوحات المضبوطة
            return self._send(200, start_panels_pull(st, rws, rcfg, racs))
        if path == "/api/renew/panels-cancel":
            _panels_job["cancel"] = True
            return self._send(200, {"ok": True})
        if path == "/api/renew/pull-cancel":
            _pull["cancel"] = True
            return self._send(200, {"ok": True})

        # ---- خدمة العميل المشتركة: للأدمن فقط (طابور/حصاد/إنشاء على مرح) ----
        if role != "admin":
            return self._send(403, {"error": "هذه العملية للمدير فقط"})
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

    def _cup_page(self, t, path):
        """صفحات بطولة: صفحتها، وودجت المتجر، وصفحة مسابقتها، وصفحات مبارياتها — أو None."""
        if path == t.PATH:                      # صفحة البطولة: النتائج والمباريات وإعلان الاشتراكات
            code, body, age = t.render()
            return self._send(code, raw=body, ctype="text/html; charset=utf-8",
                              extra={"Cache-Control": f"public, max-age={age}"} if code == 200
                              else {"Retry-After": str(league.RETRY)})
        if path == t.PATH + "/widget":          # ودجت رئيسية متجر سلة (iframe): مباريات اليوم من البطولتين
            code, body, age = tournament.render_hub(HUB_CUPS, self._q("theme"))
            return self._send(code, raw=body, ctype="text/html; charset=utf-8",
                              extra={"Cache-Control": f"public, max-age={age}"} if code == 200
                              else {"Retry-After": str(league.RETRY)})
        if path == t.PREDICT:                   # صفحة المسابقة لكل بطولة صارت صفحةً واحدة للبطولتين
            return self._redirect(predict_page.PATH, 301)
        if path.startswith(t.PATH + "/"):       # صفحة مباراة من البطولة
            page = t.render_match(path[len(t.PATH) + 1:])
            if page and page[0] == "redirect":
                return self._redirect(page[1], 301)
            if page:
                code, body, age = page
                return self._send(code, raw=body, ctype="text/html; charset=utf-8",
                                  extra={"Cache-Control": f"public, max-age={age}"})
        return None

    # ---------- مسابقة التوقّعات ----------
    def _contest_public(self):
        m = cup_match(self._q("m"))
        rec = contest.load(DATA_DIR, self._q("m"))
        if rec and m and contest.due(rec, m):          # زائرٌ سبق الدورة بعد صافرة النهاية
            rec, drawn = contest.settle(DATA_DIR, m["id"], m)
            if drawn:
                threading.Thread(target=contest_notify, args=(rec,), daemon=True).start()
        d = contest.public(rec, m) if rec else {"ok": True, "state": "off"}
        if (d.get("match") or {}).get("ts"):
            d["when"] = tournament.when_label(d["match"]["ts"])
        if d.get("state") == "open":                 # التسجيل برسالة واتساب: أرقم المسابقة متصل؟
            d["reg"] = bool(contest_wa_number())
        return self._send(200, d)

    def _contest_start(self):
        if int(self.headers.get("Content-Length", 0) or 0) > 4096:
            return self._send(413, {"error": "طلب كبير"})
        try:
            form = self._body()
        except ValueError:
            return self._send(400, {"error": "طلب غير صالح"})
        if not isinstance(form, dict):
            return self._send(400, {"error": "طلب غير صالح"})
        wa = contest_wa_number()
        if not wa:
            return self._send(503, {"error": "التسجيل عبر واتساب متوقّفٌ الآن. حاول بعد قليل."})
        code, res = contest.start(DATA_DIR, cup_match(form.get("m")), form, self._client_ip())
        if code == 200:
            res["wa"] = wa
            res["url"] = f"https://wa.me/{wa}?text={quote(res['text'], safe='')}"
        return self._send(code, res)

    def _contest_inbound(self):
        """من خدمة واتساب النظام اللوجستي: رسالةٌ خاصة وصلت رقم المسابقة ({sender_number, body,
        sent_at}، موقَّعة بـ X-Reader-Token). رسالة التوقّع تُسجَّل ويُردّ على مرسلها من رقم المسابقة،
        وما عداها يُجاب عنه بـ ignored فلا يُردّ على أحد."""
        tok = contest.reader_config(DATA_DIR)["token"].encode()
        got = (self.headers.get("X-Reader-Token") or "").encode()
        if not tok or not hmac.compare_digest(got, tok):
            return self._send(401, {"ok": False, "error": "unauthorized"})
        n = int(self.headers.get("Content-Length", 0) or 0)
        if n > 65536:                   # صورةٌ أو ملف (حتى 5MB): ليس توقّعًا — يُقرأ ويُهمل، فلا تعيده الخدمة
            if n > 16 * 1024 * 1024:
                self.close_connection = True
                return self._send(413, {"ok": False, "error": "too large"})
            while n > 0:
                chunk = self.rfile.read(min(n, 65536))
                if not chunk:
                    break
                n -= len(chunk)
            return self._send(200, {"ok": True, "status": "ignored"})
        try:
            body = self._body()
        except ValueError:
            return self._send(400, {"ok": False, "error": "bad json"})
        if not isinstance(body, dict) or body.get("type") == "ping":    # فحص الخدمة لرابطنا
            return self._send(200, {"ok": True, "status": "ok"})
        if body.get("type") == "ack":                   # إيصال تسليمٍ/قراءةٍ لرسالةٍ أرسلناها
            return self._send(200, {"ok": True, "status": "ignored"})
        ms = {m["id"]: m for m in cup_matches()[0]}
        res = contest.confirm(DATA_DIR, body.get("body"), body.get("sender_number"), body.get("sent_at"), ms,
                              contest_link)
        if res.get("reply"):                          # الردّ بعد إجابة الخدمة، لا قبلها
            threading.Thread(target=reader_send, args=(contest.norm_phone(body.get("sender_number")), res["reply"]),
                             daemon=True).start()
        return self._send(200, {"ok": True, "status": "ignored" if res["status"] == "ignored" else "ok",
                                "contest": res["status"]})

    def _contest_admin_get(self, path):
        if path == "/api/contest/admin/summary":       # أرقام لوحة الإدارة: من الملخّصات وحدها، بلا ESPN ولا واتساب
            summ = contest.summaries(DATA_DIR).values()
            live = [s for s in summ if s["on"] and not s["draw"] and not s["void"]]
            return self._send(200, {"ok": True, "active": len(live), "predictions": sum(s["count"] for s in summ),
                                    "done": sum(1 for s in summ if s["draw"]),
                                    "winners": sum(len(s.get("won") or []) for s in summ)})
        ms, feed_ok = cup_matches()
        if path == "/api/contest/admin":
            rows = contest.admin_rows(DATA_DIR, ms)
            tv = tv_map()
            for r in rows:
                r["when"] = tournament.when_label(r["match"]["ts"]) if r["match"].get("ts") else ""
                r["tv"] = contest.channel_for(tv, r["eid"], contest.cup_path(r["match"]))   # للعرض والرسالة
                r["tv_own"] = tv.get(r["eid"], "")                                       # ما كُتب لها وحدها
            return self._send(200, {"ok": True, "rows": rows, "feed": feed_ok or bool(ms),
                                    "channels": sorted({v for v in tv.values() if v} | set(contest.TV_SUGGEST)),
                                    "cups": [{"path": t.PATH, "name": t.CUP["name"], "tv": tv["cup:" + t.PATH],
                                              "default": t.CUP.get("tv", "")} for t in HUB_CUPS],
                                    "settings": contest.load_settings(DATA_DIR), "reader": self._reader_view(),
                                    "announce": tournament.announcement(rows),
                                    "announce_by": {r["eid"]: tournament.announcement([r]) for r in rows
                                                    if r["state"] == "open"}})
        if path == "/api/contest/admin/wa":            # حال ربط رقم المسابقة (والـ QR ما دام ينتظر)
            return self._send(200, {"ok": True, **self._reader_view()})
        if path == "/api/contest/admin/products":      # منتجات المتجر لاختيار الجائزة
            items, source, error = store_products(load_store(), fresh=self._q("fresh") == "1")
            return self._send(200, {"ok": bool(items), "products": items, "source": source, "error": error})
        if path == "/api/contest/admin/match":
            eid = contest.eid_of(self._q("m"))
            d = contest.admin_detail(DATA_DIR, eid, next((x for x in ms if x["id"] == eid), None))
            if not d:
                return self._send(404, {"error": "لا مسابقة على هذه المباراة"})
            if d["match"].get("ts"):
                d["when"] = d["public"]["when"] = tournament.when_label(d["match"]["ts"])
            d["link"] = contest_link(d)
            return self._send(200, d)
        if path == "/api/contest/admin/export.xlsx":      # التوقّعات Excel: مباراةٌ أو كلها
            eid = contest.eid_of(self._q("m"))
            raw = xlsx_write.build_xlsx(contest.export_sheets(DATA_DIR, eid))
            return self._send(200, raw=raw, ctype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                              extra={"Content-Disposition": f'attachment; filename="contest-{eid or "all"}.xlsx"'})
        return self._send(404, {"error": "not found"})

    @staticmethod
    def _reader_view():
        r = reader_status(fresh=True)
        return {"configured": r["configured"], "embedded": contest.reader_config(DATA_DIR)["embedded"],
                "status": r.get("status", ""), "number": r.get("number", ""),
                "qr": r.get("qr") if r.get("status") == "qr" else None, "error": r.get("error", "")}

    def _content_upload(self):
        """ملف M3U في جسم الطلب كما هو (أو مضغوطًا gzip من صفحة المدير) — يُقرأ وهو يصل، فلا يُحفظ
        الملف ولا يُحمَّل كله في الذاكرة."""
        key = content.key_ok(self._q("s"))
        try:
            left = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            left = 0
        if not key or left <= 0:
            return self._send(400, {"error": "اختر ملف M3U"})
        box = [left]

        def read(n):
            if box[0] <= 0:
                return b""
            b = self.rfile.read(min(n, box[0]))
            if not b:                           # انقطع الرفع: لا يُحفظ نصف الملف على أنه كله
                raise ValueError("انقطع الرفع قبل أن يكتمل — أعد المحاولة")
            box[0] -= len(b)
            return b
        try:
            res = content.ingest(DATA_DIR, key, read, "file", self._q("name"))
        except content.Busy:
            self.close_connection = True
            return self._send(409, {"error": "يُقرأ ملف هذا السيرفر الآن، انتظر حتى ينتهي"})
        except ValueError as e:
            self.close_connection = True
            return self._send(400, {"error": str(e)})
        return self._send(200, {"ok": True, "result": res, **content.admin_state(DATA_DIR)})

    def _content_admin_post(self, path):
        if path == "/api/content/admin/upload":
            return self._content_upload()
        body = self._body()
        key = content.key_ok(body.get("s"))
        try:
            if path == "/api/content/admin/url":            # رابط M3U: يُحفظ مشفَّرًا ويُسحب الآن ثم كل يوم
                if content.set_url(DATA_DIR, key, body.get("url")):
                    content.start_refresh(DATA_DIR, key)
            elif path == "/api/content/admin/refresh":      # «اسحب الآن»
                content.start_refresh(DATA_DIR, key)
            elif path == "/api/content/admin/hide":         # إخفاء قسمٍ من الصفحة العامة أو إظهاره
                content.set_hidden(DATA_DIR, key, body.get("g"), bool(body.get("hidden")))
            elif path == "/api/content/admin/server":       # إضافة سيرفر أو تعديل اسمه ورابط شرائه
                content.save_server(DATA_DIR, body)
            elif path == "/api/content/admin/move":         # ترتيب السيرفرات في الصفحة
                content.move_server(DATA_DIR, key, int(body.get("dir") or 0))
            elif path == "/api/content/admin/clear":        # مسح محتوى السيرفر (و«drop» يحذفه من القائمة)
                content.clear(DATA_DIR, key, drop=bool(body.get("drop")))
            else:
                return self._send(404, {"error": "not found"})
        except content.Busy:
            return self._send(409, {"error": "يُقرأ ملف هذا السيرفر الآن، انتظر حتى ينتهي"})
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        return self._send(200, {"ok": True, **content.admin_state(DATA_DIR)})

    def _contest_admin_post(self, path):
        req = self._body()
        if path == "/api/contest/admin/settings":
            return self._send(200, {"ok": True, "settings": contest.save_settings(DATA_DIR, req)})
        if path == "/api/contest/admin/wa/connect":      # ربط رقم: الخدمة تبدأ الجلسة ويظهر QR
            number = contest.norm_phone(req.get("number"))
            if not contest.phone_ok(number):
                return self._send(400, {"error": "اكتب رقم الواتساب الذي تربطه، مثل 05xxxxxxxx"})
            cfg = contest.reader_config(DATA_DIR)
            code, d, err = reader_call("POST", "/sessions", {
                "tenant": contest.READER_TENANT, "number": number, "callbackUrl": contest_inbound_url(),
                "ingestToken": cfg["token"], "dmCallbackUrl": contest_inbound_url()}, timeout=30)
            _reader_cache["d"] = None
            if code != 200:
                return self._send(502, {"error": err or "تعذّر بدء الربط"})
            return self._send(200, {"ok": True, **self._reader_view()})
        if path == "/api/contest/admin/wa/disconnect":   # فصل الرقم (يُمسح ربطه من الخدمة)
            code, d, err = reader_call("DELETE", "/sessions/" + contest.READER_TENANT)
            _reader_cache["d"] = None
            return self._send(200 if code == 200 else 502, {"ok": code == 200, "error": err, **self._reader_view()})
        if path == "/api/contest/admin/tv":              # القناة الناقلة لمباراة، أو الافتراضية لبطولة
            if req.get("cup"):
                cup = str(req["cup"])
                if cup not in {t.PATH for t in CUPS}:
                    return self._send(404, {"error": "بطولةٌ غير معروفة"})
                return self._send(200, {"ok": True, "channel": contest.set_channel(DATA_DIR, "cup:" + cup, req.get("channel"))})
            if not cup_match(req.get("m")):
                return self._send(404, {"error": "المباراة ليست في جدول البطولات"})
            return self._send(200, {"ok": True, "channel": contest.set_channel(DATA_DIR, req.get("m"), req.get("channel"))})
        if path == "/api/contest/admin/wa/test":         # رسالة تجربة من رقم المسابقة
            to = contest.norm_phone(req.get("to"))
            if not contest.phone_ok(to):
                return self._send(400, {"error": "اكتب رقمًا صحيحًا"})
            r = reader_send(to, "رسالة تجربة من مسابقة سمارت سوق ✅")
            return self._send(200 if r["ok"] else 502, r)
        m = cup_match(req.get("m"))
        if path == "/api/contest/admin/set":
            if not m:
                return self._send(404, {"error": "المباراة ليست في جدول البطولة"})
            product = None
            pid = str(req.get("prize_id") or "").strip()
            if pid and req.get("on"):                 # الإيقاف لا يمسّ الجائزة
                saved = contest.saved_prize(DATA_DIR, m["id"])
                product = (next((x for x in store_products(load_store())[0] if x["id"] == pid), None)
                           or (saved if saved and saved["id"] == pid else None))
                if not product:
                    return self._send(400, {"error": "هذا الاشتراك غير موجود في المتجر الآن — حدّث القائمة"})
            code, res = contest.configure(DATA_DIR, m, bool(req.get("on")), req.get("prize"), req.get("winners"),
                                          product=product, extra=req.get("extra"), mode=req.get("mode"))
            return self._send(code, res)
        if path == "/api/contest/admin/settle":       # «افرز الآن»: ما تفعله الدورة كل دقيقة
            rec, drawn = contest.settle(DATA_DIR, contest.eid_of(req.get("m")), m)
            if not rec or not rec.get("draw"):
                why = "أُلغيت المباراة فلا فرز." if rec and rec.get("void") else "لم تنتهِ المباراة بعد."
                return self._send(409, {"error": why})
            return self._send(200, {"ok": True, "drawn": drawn, "sent": contest_notify(rec) if drawn else []})
        if path == "/api/contest/admin/redraw":       # إعادة فرزٍ بطريقة فوزٍ أخرى (بالمدخلات نفسها)
            rec = contest.redraw(DATA_DIR, contest.eid_of(req.get("m")), str(req.get("mode") or ""))
            if not rec:
                return self._send(409, {"error": "لم تُفرز بعد."})
            # لا رسائل تلقائية: من بقي فائزًا بُلّغ من قبل، و«أعد إرسال الرسائل» في يد المدير
            return self._send(200, {"ok": True, "picks": len(rec["draw"]["picks"])})
        if path == "/api/contest/admin/notify":       # إعادة رسائل الفرز
            rec = contest.load(DATA_DIR, req.get("m"))
            if not rec or not rec.get("draw"):
                return self._send(409, {"error": "لم تُفرز بعد."})
            return self._send(200, {"ok": True, "sent": contest_notify(rec)})
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
            if path == "/api/contest/start":         # النتيجة والاسم من الصفحة ← رمزٌ ورسالةٌ جاهزة
                return self._contest_start()
            if path == "/api/contest/wa-inbound":    # رسالة توقّعٍ وصلت خدمة واتساب (موقَّعة بسرّها)
                return self._contest_inbound()
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
                    ws, own = renew_ws(role, acct)
                    return self._renew_upload(st, ws)
                if path.startswith("/api/renew/"):
                    return self._renew_admin(path, st, role, acct)
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
            if path.startswith("/api/content/"):      # خارج القفل: رفع ملف M3U وقراءته يطولان
                if role != "admin":
                    return self._send(403, {"error": "للمدير فقط"})
                return self._content_admin_post(path)
            if path.startswith("/api/contest/"):      # خارج القفل: التبليغ ينتظر واتساب
                if role != "admin":
                    return self._send(403, {"error": "للمدير فقط"})
                return self._contest_admin_post(path)
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
            if path == "/api/users-export/pull":      # سحب كل اليوزرات وحفظها Excel
                if role != "account":
                    return self._send(403, {"error": "ادخل بحساب مستخدم وليس المدير"})
                gate = find_gate(acct, self._body().get("gate"))
                if not gate:
                    return self._send(400, {"error": "اختر بوابة"})
                if gate.get("mode") not in ("web", "falcon"):
                    return self._send(200, {"error": "السحب الكامل متاحٌ لبوابات الويب أو فالكون"})
                return self._send(200, start_users_export(acct["id"], gate["id"], gate))
            if path.startswith("/api/split/"):        # خارج القفل: تغيير الاسم يلمس اللوحة
                return self._split_post(path, st, role, acct)
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
            _save_sessions()
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

    # ---------- الاشتراكات المجزّأة ----------
    @staticmethod
    def _split_scope(st, role, acct):
        """حسابات هذه الجلسة: العميل نفسه إن فُتحت له الميزة؛ والمدير كلُّ عميلٍ فُتحت
        له أو بقيت له خطوطٌ مسجَّلة (فلا تختفي خطوطُ عميلٍ أُغلقت عنه الميزة)."""
        if role == "admin":
            return [a for a in st["accounts"] if split_on(a) or split_subs.has_data(DATA_DIR, a["id"])]
        return [acct] if split_on(acct) else []

    def _split_state(self, st, role, acct):
        now = split_subs.now_dt()
        accounts, lines, notes, unread = [], [], [], 0
        for a in self._split_scope(st, role, acct):
            v = split_subs.view(DATA_DIR, a["id"], now)
            gates = {str(g.get("id")): g for g in (a.get("gates") or [])}
            mstat = split_mail_status(st, a, role)
            merr = v["mail"].get("last_error", "")
            if mstat.get("configured") and "غير مضبوط" in merr:
                merr = ""                            # خطأٌ قديمٌ من قبل ضبط البريد — لم يعد صحيحًا
            accounts.append({
                "id": a["id"], "name": a.get("name", ""), "enabled": split_on(a),
                "cfg": v["cfg"], "unread": v["unread"],
                "mail": {**mstat, "last_sent": v["mail"].get("last_sent", ""),
                         "last_error": merr, "hint": split_subs.mail_hint(merr)},
                "gates": [{"id": g.get("id"), "name": g.get("name", ""), "mode": g.get("mode"),
                           "flavor": g.get("web_flavor", ""), "supported": split_gate_ok(g),
                           "edit": v["gates"].get(str(g.get("id")), {})}
                          for g in (a.get("gates") or [])]})
            for rec in v["lines"]:
                g = gates.get(rec.get("gate_id")) or {"host": rec.get("host", ""), "name": rec.get("gate_name", "")}
                rec.update(split_texts(a, g, rec))
                rec["account_name"] = a.get("name", "")
                lines.append(rec)
            notes += [{**n, "account_id": a["id"], "account_name": a.get("name", "")} for n in v["notes"]]
            unread += v["unread"]
        notes.sort(key=lambda n: n.get("at", ""), reverse=True)
        return {"role": role, "accounts": accounts, "lines": lines, "notes": notes[:150],
                "unread": unread, "slices": list(split_subs.SLICES),
                "base_months": list(split_subs.BASE_MONTHS), "now": split_subs.fmt(now)}

    def _split_notes(self, st, role, acct):
        scope = self._split_scope(st, role, acct)
        notes, unread = [], 0
        for a in scope:
            db = split_subs.load(DATA_DIR, a["id"])
            unread += split_subs.unread(db)
            notes += [{**n, "account_name": a.get("name", "")} for n in db["notes"][:20]]
        notes.sort(key=lambda n: n.get("at", ""), reverse=True)
        return {"enabled": bool(scope), "unread": unread, "notes": notes[:20]}

    def _split_post(self, path, st, role, acct):
        req = self._body()
        scope = self._split_scope(st, role, acct)
        if not scope:
            return self._send(403, {"error": "الاشتراكات المجزّأة غير مفعّلة لهذا الحساب"})
        if path == "/api/split/read":             # تعليم الإشعارات مقروءة (كلها أو بعضها)
            ids = [str(x) for x in (req.get("ids") or [])]
            for a in scope:
                split_subs.mark_read(DATA_DIR, a["id"], ids or None)
            return self._send(200, {"ok": True})
        if path in ("/api/split/cfg", "/api/split/test-email", "/api/split/register", "/api/split/test-rename"):
            want = str(req.get("account_id") or "")
            a = next((x for x in scope if str(x["id"]) == want), None) if want else \
                (scope[0] if len(scope) == 1 else None)
            if not a:
                return self._send(400, {"error": "اختر الحساب"})
            if path == "/api/split/cfg":
                cfg = split_subs.set_cfg(DATA_DIR, a["id"],
                                         {k: req[k] for k in ("auto", "remind_days") if k in req})
                return self._send(200, {"ok": True, "cfg": cfg})
            if path == "/api/split/test-email":
                ok, err = split_mailer(st, a)(
                    "حسابات متبقية — بريد تجريبي",
                    "هذا بريدٌ تجريبي من صفحة «حسابات متبقية» (%s).\n"
                    "هنا تصلك تذكيرات انتهاء الأجزاء المبيعة وتغيير أسماء المستخدمين.\n\n%s\n"
                    % (a.get("name", ""), split_page_url()))
                if ok:                              # البريد يعمل: تُمحى أخطاؤه ويُرسَل المنتظر الآن
                    split_subs.mail_verified(DATA_DIR, a["id"])
                    split_flush_async(st, a)
                return self._send(200, {"ok": bool(ok), "error": "" if ok else err,
                                        "hint": "" if ok else split_subs.mail_hint(err)})
            if path == "/api/split/test-rename":
                return self._split_test_rename(a, req)
            return self._split_register(a, req)
        rid = str(req.get("id") or "")
        a = next((x for x in scope if rid and rid in split_subs.load(DATA_DIR, x["id"])["lines"]), None)
        if not a:
            return self._send(404, {"error": "لا خط بهذا المعرّف"})
        try:
            if path == "/api/split/sell":
                rec = split_subs.sell(DATA_DIR, a["id"], rid, req.get("months", 0), req.get("customer", ""))
            elif path == "/api/split/customer":
                rec = split_subs.set_customer(DATA_DIR, a["id"], rid, req.get("customer", ""))
            elif path == "/api/split/confirm":
                rec = split_subs.confirm_manual(DATA_DIR, a["id"], rid, req.get("username", ""),
                                                req.get("password", ""))
            elif path == "/api/split/delete":
                split_subs.delete(DATA_DIR, a["id"], rid)
                return self._send(200, {"ok": True})
            elif path == "/api/split/rotate":         # «غيّر الآن»: قبل موعده أو بعد تعذّره
                if not split_on(a):
                    return self._send(403, {"error": "الميزة مغلقة لهذا العميل — لا تغيير"})
                cur = split_subs.load(DATA_DIR, a["id"])["lines"][rid]
                gate = find_gate(a, cur.get("gate_id"))
                if not gate:
                    return self._send(400, {"error": "بوابة هذا الخط لم تعد موجودة في الحساب"})
                rec, res = split_subs.rotate(DATA_DIR, a["id"], rid, gate, SPLIT_BRIDGE, how="now")
                if res not in ("busy", "skip"):
                    split_flush_async(st, a)             # بريد التغيير (أو تعذّره) الآن لا بعد الدورة
                if res == "busy":
                    return self._send(409, {"error": "جارٍ تغيير هذا الخط الآن — انتظر لحظة"})
                if res == "skip":
                    return self._send(400, {"error": "لا جزء مبيعًا ينتظر التغيير في هذا الخط"})
                if res != "ok":
                    return self._send(200, {"ok": False, "result": res,
                                            "error": (rec or {}).get("last_error", "") or "تعذّر التغيير",
                                            "line": split_subs.decorate(rec) if rec else None})
            elif path == "/api/split/undo":           # «تراجع»: يعيد الاسم القديم على اللوحة والجزء كما كان
                if not split_on(a):
                    return self._send(403, {"error": "الميزة مغلقة لهذا العميل — لا تغيير"})
                cur = split_subs.load(DATA_DIR, a["id"])["lines"][rid]
                gate = find_gate(a, cur.get("gate_id"))
                if not gate:
                    return self._send(400, {"error": "بوابة هذا الخط لم تعد موجودة في الحساب"})
                rec, res = split_subs.undo(DATA_DIR, a["id"], rid, gate, SPLIT_BRIDGE)
                if res == "busy":
                    return self._send(409, {"error": "جارٍ تغيير هذا الخط الآن — انتظر لحظة"})
                if res == "skip":
                    return self._send(400, {"error": "لا تغيير اسمٍ يُتراجع عنه — التراجع لخطٍّ متاحٍ لم يُبَع بعد تغييره"})
                if res != "ok":
                    return self._send(200, {"ok": False, "result": res,
                                            "error": (rec or {}).get("last_error", "") or "تعذّر التراجع",
                                            "line": split_subs.decorate(rec) if rec else None})
            else:
                return self._send(404, {"error": "not found"})
        except KeyError as e:
            return self._send(404, {"error": str(e.args[0] if e.args else e)})
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        return self._send(200, {"ok": True, "line": split_subs.decorate(rec)})

    def _split_test_rename(self, a, req):
        """«تجربة على خطٍّ تجريبي»: يغيّر اسم خطٍّ تجريبي على لوحته الحقيقية كما سيحدث
        عند انتهاء الأجزاء (كلمة المرور كما هي، وبالحرّاس أنفسهم)، ويسجّل للبوابة أنها
        جُرِّبت. لا يُمسّ خطٌّ متابَع — فالتجربة لا تقطع عميلًا."""
        if not split_on(a):
            return self._send(403, {"error": "الميزة مغلقة لهذا العميل"})
        gate = find_gate(a, req.get("gate"))
        if not split_gate_ok(gate):
            return self._send(400, {"error": "اختر بوابة مرح أو كاسبر أو فالكون"})
        user = str(req.get("username", "")).strip()
        if not user:
            return self._send(400, {"error": "اكتب اسم مستخدم الخط التجريبي"})
        if split_subs.find(split_subs.load(DATA_DIR, a["id"]), gate["id"], user):
            return self._send(400, {"error": "هذا خطٌّ متابَع لعميل — جرّب على خطٍّ تجريبي لا على خطّ عميل"})
        try:
            found = split_find_line(gate, user)
        except xm_web.CaptchaNeeded:
            return self._send(200, {"ok": False, "kind": "transient",
                                    "error": "اللوحة تطلب كود تحقّق — افتح صفحة الإنشاء وادخل بوابة «%s» ثم أعد التجربة"
                                             % gate.get("name", "")})
        except Exception as e:
            return self._send(200, {"ok": False, "kind": "transient", "error": "تعذّر البحث في اللوحة: %s" % str(e)[:160]})
        if not found:
            return self._send(400, {"error": "لم أجد «%s» في اللوحة — انسخ اسم الخط التجريبي كما هو" % user})
        new = split_subs.new_username(gate, user)
        rec = {"username": user, "password": found.get("password", ""), "line_id": found.get("line_id", "")}
        name = gate.get("name", "")
        try:
            res = split_change(gate, rec, {"username": new, "password": rec["password"]}) or {}
        except split_subs.Transient as e:
            return self._send(200, {"ok": False, "kind": "transient", "error": str(e)})
        except split_subs.Unsupported as e:
            split_subs.record_test(DATA_DIR, a["id"], gate, False,
                                   "🧪 تجربة على «%s»: اللوحة لم تتح تغيير الاسم — لم يُرسَل إليها شيء (%s)." % (name, e),
                                   error=str(e))
            return self._send(200, {"ok": False, "kind": "unsupported", "error": str(e)})
        except Exception as e:                  # أُرسل التعديل ولم يتأكّد: راجع اللوحة
            split_subs.record_test(DATA_DIR, a["id"], gate, None,
                                   "🧪 تجربة على «%s»: أُرسل تغيير الخط %s ← %s ولم يتأكّد: %s — راجع اللوحة."
                                   % (name, user, new, str(e)[:200]))
            return self._send(200, {"ok": False, "kind": "failed", "old": user, "new": new, "error": str(e)[:300]})
        split_subs.record_test(DATA_DIR, a["id"], gate, True,
                               "🧪 نجحت التجربة على «%s»: تغيّر اسم الخط التجريبي %s ← %s، وكلمة المرور كما هي."
                               % (name, user, new))
        return self._send(200, {"ok": True, "old": user, "new": new,
                                "password": res.get("password") or rec["password"],
                                "same_password": (res.get("password") or rec["password"]) == rec["password"],
                                "exp": str(res.get("exp") or "")})

    def _split_register(self, a, req):
        """يُدخل خطًّا قائمًا (بِيع جزؤه الأول قبل تفعيل الميزة) في المتابعة. كلمة المرور
        وتاريخ الانتهاء من اللوحة إن أمكن، وإلا مما كتبه المشغّل."""
        gate = find_gate(a, req.get("gate"))
        if not split_gate_ok(gate):
            return self._send(400, {"error": "اختر بوابة مرح أو كاسبر أو فالكون"})
        user = str(req.get("username", "")).strip()
        pw = str(req.get("password", "")).strip()
        if not user:
            return self._send(400, {"error": "اكتب اسم المستخدم"})
        try:
            months = int(req.get("months") or 0)
        except (TypeError, ValueError):
            months = 0
        if months not in split_subs.SLICES:
            return self._send(400, {"error": "اختر نوع البيع (٦ · ٣ · شهر)"})
        now = split_subs.now_dt()
        day = split_subs.to_date(req.get("start")) if req.get("start") else now.date()
        if not day:
            return self._send(400, {"error": "تاريخ البيع غير مفهوم (سنة-شهر-يوم)"})
        if day > now.date():
            return self._send(400, {"error": "تاريخ البيع في المستقبل"})
        start = datetime.datetime.combine(day, now.time())
        found, why = {}, ""
        try:
            found = split_find_line(gate, user)
        except xm_web.CaptchaNeeded:
            why = "اللوحة تطلب كود تحقّق — ادخل البوابة من صفحة الإنشاء أو اكتب كلمة المرور"
        except Exception as e:
            why = "تعذّر البحث في اللوحة: %s" % str(e)[:120]
        if not found and not pw:
            return self._send(400, {"error": why or "لم أجد اليوزر في اللوحة — تأكّد منه أو اكتب كلمة المرور"})
        reckoned = renew.add_months(start.date(), split_subs.BASE_MONTHS[0])
        expiry = split_subs.to_date(req.get("expiry")) or split_subs.to_date(found.get("exp"))
        if not expiry or not (start.date() < expiry <= renew.add_months(start.date(), 16)):
            expiry = reckoned                      # تاريخٌ لا يُصدَّق (صيغة مقلوبة) = المحسوب
        try:
            rec, new = split_subs.register(
                DATA_DIR, a["id"], gate, user, pw or found.get("password", ""), months,
                base_months=split_subs.BASE_MONTHS[0], start=start, expiry=expiry,
                customer=req.get("customer", ""), line_id=found.get("line_id", ""), source="manual")
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        return self._send(200, {"ok": True, "created": new, "line": split_subs.decorate(rec)})

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
        # بيعٌ مجزّأ (٦ · ٣ · شهر من باقة ١٥ شهرًا): يُفحص قبل أي إنشاء، فالرفض لا يخصم.
        try:
            slice_m = int(req.get("slice_months") or 0)
        except (TypeError, ValueError):
            slice_m = -1
        if slice_m:
            why = split_create_error(acct, gate, pkg, slice_m)
            if why:
                return self._send(400, {"error": why})
        t_start = time.time()
        out, err = create_lines(gate, pkg, count,
                                req.get("username") if count == 1 else None,
                                req.get("password") if count == 1 else None)
        resp = {"lines": out, "total_ms": int((time.time() - t_start) * 1000)}
        if err:
            # ما أُنشئ قبل الخطأ أُنشئ فعلًا (وخُصم)، فيُعاد مع الخطأ لا بدلًا منه.
            resp["error"] = err if not out else "أُنشئ %d من %d ثم توقفت اللوحة: %s" % (len(out), count, err)
        if out:                                    # تعبئة ملف الإكسل تلقائيًا باليوزرات المُنشأة
            try:
                users_export.merge(DATA_DIR, acct["id"], gate["id"], gate.get("name"),
                                   out, gate.get("host", ""))
            except Exception:
                pass                               # التصدير مساعدٌ لا يُفشل الإنشاء
        replaces = str(req.get("replaces") or "").strip()   # ربط القديم بالجديد (بديل)
        if replaces and out:
            try:
                linked = [user_links.add(DATA_DIR, acct["id"], gate["id"],
                                         replaces, r["username"], r.get("package", ""))
                          for r in out]
                resp["linked"] = [x for x in linked if x]
            except Exception:
                pass                               # الربط مساعدٌ لا يُفشل الإنشاء
        if slice_m and out:                        # يُتابَع الجزء المبيع حتى يتغيّر اسمه
            resp["split"] = split_register_created(acct, gate, pkg, slice_m, out)
            resp["split_mail"] = split_mail_status(load_store(), acct, "account")   # أيصل التذكير بالبريد؟
            label = "%s · جزء %s" % (pkg.get("name", ""), split_subs.months_ar(slice_m))
            for r in out:
                r["package"] = label               # السجل في المتصفح يفصل المجزّأ عن الكامل
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
    start_split_worker()
    start_contest_worker()
    start_content_worker()
    start_embedded_reader()
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "cli"
    if mode == "web":
        web()
    elif mode == "debug":
        print(json.dumps(api(pick_account()["gates"][0], "get_packages"), ensure_ascii=False, indent=2)[:4000])
    else:
        cli()

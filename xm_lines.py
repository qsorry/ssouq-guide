#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Xtream-Masters — إنشاء يوزرات M3U Lines (متعدد الحسابات)
--------------------------------------------------------
التشغيل:
  python xm_lines.py web      ← يشغّل الصفحة على http://127.0.0.1:8080
  python xm_lines.py          ← وضع سطر الأوامر
  python xm_lines.py debug    ← يطبع رد get_packages الخام

الصفحة الرئيسية / دليل تفعيل عام. الأداة كلها تحت /admin:
أول مرة تفتح /admin تضع كلمة مرور المدير، ثم من /admin/accounts تضيف الحسابات
(لكل حساب: اسم دخول، كلمة مرور، رابط API، مفتاح API، هوست).
البيانات تُحفظ في data/accounts.json. لا يحتاج أي مكتبات خارجية (Python 3.8+).
"""
import json, os, sys, secrets, datetime, base64, hmac, hashlib, threading, time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import copy

import guide_pages
import store_sitemap
import xm_web
import falcon_api
import crypto_store

# كلمة مرور الدخول تُخزَّن مُجزّأة (hash) لا مشفَّرة، فلا تُسترجع أبدًا.
# أسرار اللوحات تبقى مشفَّرة (نحتاجها للدخول للّوحة) لكنها لا تُرسَل للمتصفح.
_SENSITIVE_ACCT = ()
_SENSITIVE_GATE = ("panel_pass", "api_key")


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
P         = "/admin"                                  # كل الأداة تحت هذا المسار
PAGES     = {P: "xm_lines.html", P + "/accounts": "admin.html", P + "/setup": "setup.html", P + "/login": "login.html"}
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
DIGITS    = 12                                        # طول اليوزر والباسورد (أرقام)
# ============================================

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


def get_packages(gate):
    if gate.get("mode") == "web":                      # جلسة ويب بدل الـ API
        return [{"id": p["value"], "name": p["text"], "credits": None,
                 "max_connections": 1, "bouquets": []}
                for p in web_session(gate).packages()]
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
    if gate.get("mode") == "web":                      # الإنشاء عبر نموذج اللوحة
        r = web_session(gate).create_line(pkg["id"], username, password, gate.get("host"))
        line = format_line(gate, r["username"], r["password"])
        _log_txt(gate, line, pkg["name"])
        return {"line": line, "username": r["username"], "password": r["password"],
                "package": pkg["name"], "verified": r.get("verified", True), "time": r["time"]}
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
    username = username or rand_digits()
    password = password or rand_digits()
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


# ---------------- وضع سطر الأوامر ----------------
def pick_account():
    accts = load_store()["accounts"]
    if not accts:
        sys.exit("لا توجد حسابات. شغّل الصفحة وأضف الحسابات من /admin/accounts أولاً.")
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

    def _redirect(self, to):
        self._send(302, raw=b"", ctype="text/plain", extra={"Location": to})

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
        c = f"xm_session={tok}; Path={P}; HttpOnly; SameSite=Lax"
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
        if u == ADMIN_USER and check_pw(p, st["admin"]):
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
        if path.startswith(P + "/api/"):
            self._send(401, {"error": "سجّل الدخول أولاً", "login": True})
        else:
            self._redirect(P + "/login")

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
        # ----- الجزء العام -----
        if path == "/robots.txt":
            return self._send(200, raw=f"User-agent: *\nDisallow: {P}\nAllow: /\n\n"
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
        if path in ("/", "/index.html"):
            return self._page("index.html", cache=PUBLIC_HTML_CACHE)
        if path in guide_pages.PAGES:                 # صفحات الأجهزة الثابتة (للأرشفة)
            return self._send(200, raw=guide_pages.render(path), ctype="text/html; charset=utf-8",
                              extra={"Cache-Control": PUBLIC_HTML_CACHE})
        if path.startswith("/static/"):
            return self._static(path)
        if path == "/admin/":
            return self._redirect(P)
        if path != P and not path.startswith(P + "/"):
            return self._send(404, raw="404".encode(), ctype="text/plain; charset=utf-8")
        # ----- الأداة تحت /admin -----
        st = load_store()
        if not st["admin"]:                       # الإعداد الأول: لا يوجد مدير بعد
            return self._page(PAGES[P + "/setup"]) if path == P + "/setup" else self._redirect(P + "/setup")
        if path == P + "/setup":
            return self._redirect(P)
        if path == P + "/logout":
            _sessions.pop(self._cookie("xm_session"), None)
            return self._send(302, raw=b"", ctype="text/plain",
                              extra={"Location": P + "/login", **self._set_cookie("", clear=True)})
        role, acct = self._who(st)
        if path == P + "/login":
            return self._redirect(P) if role else self._page(PAGES[P + "/login"])
        if not role:
            return self._deny(path)
        try:
            if path == P:
                return self._redirect(P + "/accounts") if role == "admin" else self._page(PAGES[P])
            if path == P + "/accounts":
                return self._page(PAGES[P + "/accounts"]) if role == "admin" else self._send(403, {"error": "للمدير فقط"})
            if path == P + "/api/me":
                gates = [{"id": g["id"], "name": g["name"], "mode": g["mode"],
                          "host": g["host"], "guide_url": g.get("guide_url", "")}
                         for g in (acct.get("gates", []) if acct else [])]
                return self._send(200, {"role": role, "account": acct["name"] if acct else None,
                                        "guide_url": acct.get("guide_url", "") if acct else "",
                                        "gates": gates})
            if path == P + "/api/mygates":            # بوابات الشخص كاملةً (لتحريرها)
                if role != "account":
                    return self._send(403, {"error": "غير متاح"})
                return self._send(200, {"gates": _redact_gates(acct.get("gates", [])),
                                        "guide_url": acct.get("guide_url", "")})
            if path == P + "/api/gate-status":        # النقاط + آخر يوزر للبوابة
                gate = find_gate(acct, self._q("gate")) if acct else None
                if role != "account" or not gate:
                    return self._send(403, {"error": "غير متاح"})
                if gate.get("mode") == "falcon":
                    return self._send(200, falcon_api.status(gate["api_url"], gate["api_key"]))
                return self._send(200, {"provider": gate.get("mode"), "credits": None,
                                        "unsupported": True})
            if path == P + "/api/search":             # بحث بالـ username/password
                gate = find_gate(acct, self._q("gate")) if acct else None
                if role != "account" or not gate:
                    return self._send(403, {"error": "غير متاح"})
                q = self._q("q").strip()
                if not q:
                    return self._send(200, {"results": []})
                if gate.get("mode") == "falcon":
                    return self._send(200, {"results": falcon_api.search(gate["api_url"], gate["api_key"], q)})
                return self._send(200, {"results": [], "unsupported": True})
            if path == P + "/api/web/captcha":        # صورة كود التحقّق (وضع الويب)
                gate = find_gate(acct, self._q("gate")) if acct else None
                if role != "account" or not gate or gate.get("mode") != "web":
                    return self._send(403, {"error": "غير متاح"})
                s = web_session(gate)
                s.begin()
                ct, img = s.fetch_captcha()
                return self._send(200, raw=img, ctype=ct or "image/jpeg")
            if path == P + "/api/packages":
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
            if path == P + "/api/accounts":
                if role != "admin":
                    return self._send(403, {"error": "للمدير فقط"})
                return self._send(200, {"accounts": [redact_account(a) for a in st["accounts"]]})
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

    # ---------- POST ----------
    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/m3u-generated":            # عدّاد عام لأداة M3U (بدون تسجيل دخول)
            with _lock:
                return self._send(200, {"m3u": bump_stat("m3u")})
        if not path.startswith(P + "/api/"):
            return self._send(404, {"error": "not found"})
        path = path[len(P):]
        try:
            with _lock:
                st = load_store()
                if path == "/api/setup":
                    if st["admin"]:
                        return self._send(400, {"error": "تم الإعداد مسبقاً"})
                    pw = str(self._body().get("password", ""))
                    if len(pw) < 6:
                        return self._send(400, {"error": "كلمة المرور قصيرة (6 أحرف على الأقل)"})
                    st["admin"] = hash_pw(pw)
                    save_store(st)
                    return self._send(200, {"ok": True}, extra=self._set_cookie(new_session("admin", ADMIN_USER)))
                if not st["admin"]:
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
        out = [create_line(gate, pkg, req.get("username") if count == 1 else None,
                           req.get("password") if count == 1 else None) for _ in range(count)]
        self._send(200, {"lines": out})


def web():
    print(f"الصفحة تعمل: http://{BIND}:{PORT}   (Ctrl+C للإيقاف)", flush=True)
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "cli"
    if mode == "web":
        web()
    elif mode == "debug":
        print(json.dumps(api(pick_account()["gates"][0], "get_packages"), ensure_ascii=False, indent=2)[:4000])
    else:
        cli()

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

import guide_pages
import store_sitemap
import renewals

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
PAGES     = {P: "xm_lines.html", P + "/accounts": "admin.html", P + "/whatsapp": "renewals.html", P + "/setup": "setup.html", P + "/login": "login.html"}
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
_wa_lock = threading.Lock()      # تخزين التجديدات مستقل عن الحسابات
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
    return st


def save_store(st):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = ACC_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ACC_FILE)


def hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100_000).hex()
    return {"salt": salt, "hash": h}


def check_pw(pw, rec):
    if not rec:
        return False
    return hmac.compare_digest(hash_pw(pw, rec["salt"])["hash"], rec["hash"])


def clean_account(a, old=None):
    """يتحقق من حقول الحساب ويرجع نسخة نظيفة أو يرفع ValueError."""
    old = old or {}
    out = {
        "id":       old.get("id") or secrets.token_hex(4),
        "name":     str(a.get("name", "")).strip() or old.get("name", ""),
        "user":     str(a.get("user", "")).strip() or old.get("user", ""),
        "password": str(a.get("password", "")) or old.get("password", ""),
        "api_url":  str(a.get("api_url", "")).strip().rstrip("/") or old.get("api_url", ""),
        "api_key":  str(a.get("api_key", "")).strip() or old.get("api_key", ""),
        "host":     str(a.get("host", "")).strip().rstrip("/") or old.get("host", ""),
    }
    if not out["name"]:
        raise ValueError("الاسم مطلوب")
    if not out["user"] or ":" in out["user"] or out["user"] == ADMIN_USER:
        raise ValueError("اسم الدخول غير صالح أو محجوز")
    if len(out["password"]) < 4:
        raise ValueError("كلمة المرور قصيرة (4 أحرف على الأقل)")
    if not out["api_url"].startswith(("http://", "https://")):
        raise ValueError("رابط API يجب أن يبدأ بـ http:// أو https://")
    if not out["api_key"]:
        raise ValueError("مفتاح API مطلوب")
    if not out["host"].startswith(("http://", "https://")):
        raise ValueError("الهوست يجب أن يبدأ بـ http:// أو https://")
    return out


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


def get_packages(acct):
    pkgs = []
    for p in _unwrap(api(acct, "get_packages")):
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


def create_line(acct, pkg, username=None, password=None, host=None):
    host = (host or acct["host"]).strip().rstrip("/")
    username = username or rand_digits()
    password = password or rand_digits()
    params = {
        "username": username,
        "password": password,
        "package": pkg["id"],
        "max_connections": pkg.get("max_connections") or 1,
        "bouquets_selected[]": pkg["bouquets"],  # اختيار كل Subscribed
    }
    r = api(acct, "create_line", params, post=True)
    ok = isinstance(r, dict) and (
        r.get("status") in ("STATUS_SUCCESS", "success", True) or r.get("result") is True)
    if not ok:
        raise RuntimeError("فشل الإنشاء: " + json.dumps(r, ensure_ascii=False)[:400])
    data = r.get("data") if isinstance(r.get("data"), dict) else {}
    username = data.get("username", username)
    password = data.get("password", password)
    line = f"Host {host}  Password {password} Username {username}"
    now = datetime.datetime.now()
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(TXT_FILE, "a", encoding="utf-8") as f:
            f.write(f"{now:%d-%m-%Y %H:%M}  |  {acct['name']}  |  {line}  |  {pkg['name']}\n")
    except OSError:
        pass
    return {"line": line, "username": username, "password": password,
            "package": pkg["name"], "time": now.isoformat(timespec="seconds")}


# ---------------- وضع سطر الأوامر ----------------
def pick_account():
    accts = load_store()["accounts"]
    if not accts:
        sys.exit("لا توجد حسابات. شغّل الصفحة وأضف الحسابات من /admin/accounts أولاً.")
    if len(accts) == 1:
        return accts[0]
    for i, a in enumerate(accts, 1):
        print(f"{i}) {a['name']}  —  {a['host']}")
    return accts[int(input("\nرقم الحساب: ").strip()) - 1]


def cli():
    acct = pick_account()
    pkgs = get_packages(acct)
    if not pkgs:
        print("لا توجد باقات. شغّل: python xm_lines.py debug")
        return
    for i, p in enumerate(pkgs, 1):
        print(f"{i}) {p['name']}  —  {len(p['bouquets'])} بوكيه")
    n = int(input("\nرقم الباقة: ").strip())
    count = int((input("عدد اليوزرات [1]: ").strip() or "1"))
    for _ in range(count):
        print(create_line(acct, pkgs[n - 1])["line"])
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
            if hmac.compare_digest(u, a["user"]) and hmac.compare_digest(p, a["password"]):
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
            return self._send(200, raw=f"User-agent: *\nDisallow: {P}\nDisallow: /offer/\nAllow: /\n\n"
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
        if path.startswith("/offer/"):          # رابط العرض الخاص — عام بلا تسجيل دخول
            off = renewals.get_offer(path[len("/offer/"):].strip("/"), bump=True)
            return self._send(200 if off else 404, raw=renewals.offer_page(off),
                              ctype="text/html; charset=utf-8", extra={"Cache-Control": "no-store"})
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
            if path == P + "/whatsapp":                 # بيانات عملاء وأكواد: للمدير وحده
                return self._page(PAGES[P + "/whatsapp"]) if role == "admin" else self._send(403, {"error": "للمدير فقط"})
            if path == P + "/api/wa/data":
                return self._wa_data() if role == "admin" else self._send(403, {"error": "للمدير فقط"})
            if path == P + "/api/me":
                return self._send(200, {"role": role, "account": acct["name"] if acct else None})
            if path == P + "/api/packages":
                if role != "account":
                    return self._send(403, {"error": "ادخل بحساب مستخدم وليس المدير"})
                return self._send(200, {"account": acct["name"], "host": acct["host"], "packages": get_packages(acct)})
            if path == P + "/api/accounts":
                if role != "admin":
                    return self._send(403, {"error": "للمدير فقط"})
                return self._send(200, {"accounts": st["accounts"]})
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
            if path.startswith("/api/wa/"):          # التجديدات: تخزينها وقفلها مستقلان
                st = load_store()
                if not st["admin"]:
                    return self._send(400, {"error": "أكمل الإعداد أولاً"})
                role_ = self._who(st)[0]
                if not role_:
                    return self._deny(path)
                if role_ != "admin":                    # حسابات M3U لا ترى بيانات العملاء
                    return self._send(403, {"error": "للمدير فقط"})
                with _wa_lock:
                    return self._wa_post(path)
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
            if path == "/api/create":
                if role != "account":
                    return self._send(403, {"error": "ادخل بحساب مستخدم وليس المدير"})
                return self._create(acct)
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
        self._send(200, {"ok": True, "accounts": st["accounts"]})

    # ---------- التجديدات ----------
    def _raw_body(self):
        n = int(self.headers.get("Content-Length", 0))
        if n > 40 * 1024 * 1024:
            raise ValueError("الملف أكبر من 40 ميجابايت")
        return self.rfile.read(n)

    def _wa_data(self):
        cs = renewals.customers()
        sf = renewals.shortfalls()
        for x in sf:
            x["message"] = renewals.render_compensation(x)
        wa = renewals.load_wa()
        self._send(200, {"customers": cs, "shortfalls": sf, "stats": renewals.stats(cs),
                         "settings": wa["settings"], "optout": wa["optout"],
                         "sent_today": renewals.sent_today()})

    def _wa_post(self, path):
        if path == "/api/wa/upload":
            name = ""
            if "?" in self.path:
                from urllib.parse import parse_qs
                name = (parse_qs(self.path.split("?", 1)[1]).get("name") or [""])[0]
            rows, kind = renewals.read_upload(self._raw_body())
            rep = renewals.ingest(rows, name)
            rep["kind"] = kind
            return self._send(200, rep)

        req = self._body()
        if path == "/api/wa/settings":
            wa = renewals.load_wa(); s = wa["settings"]
            s["daily_cap"] = max(1, min(int(req.get("daily_cap", s["daily_cap"])), 500))
            s["gap_min"]   = max(5, int(req.get("gap_min", s["gap_min"])))
            s["gap_max"]   = max(s["gap_min"], int(req.get("gap_max", s["gap_max"])))
            s["send_url"]  = str(req.get("send_url", s.get("send_url", ""))).strip()
            s["send_token"] = str(req.get("send_token", s.get("send_token", ""))).strip()
            s["discount"]   = max(1, min(int(req.get("discount", s.get("discount", 20))), 90))
            s["offer_days"] = max(1, min(int(req.get("offer_days", s.get("offer_days", 3))), 60))
            s["coupon"]     = str(req.get("coupon", s.get("coupon", ""))).strip()
            s["salla_token"] = str(req.get("salla_token", s.get("salla_token", ""))).strip()
            s["enabled"]   = bool(s["send_url"])
            renewals.save_wa(wa)
            return self._send(200, {"ok": True, "settings": s})

        if path == "/api/wa/offer":
            pct = req.get("pct"); days = req.get("days")
            coupon = str(req.get("coupon", "")).strip()
            token_ = str(req.get("salla_token", "")).strip()
            targets = []
            if req.get("phone"):
                ph = renewals.norm_phone(str(req["phone"]))
                targets = [c for c in renewals.customers() if c["phone"] == ph]
            elif req.get("segment"):
                lim = max(1, min(int(req.get("limit", 100)), 1000))
                targets = [c for c in renewals.customers()
                           if c["segment"] == req["segment"] and not c["optout"]][:lim]
            if not targets:
                return self._send(404, {"error": "لا عملاء في هذا الاختيار"})
            made, failed, err1 = [], 0, ""
            for c in targets:
                if renewals.offer_for(c["phone"]):      # لا نكرّر عرضًا حيًّا
                    continue
                off, err = renewals.make_offer(c, pct, days, coupon, token_)
                if off:
                    made.append({"phone": c["phone"], "name": c["name"], "token": off["token"],
                                 "url": renewals.offer_url(off), "final": off["final"],
                                 "coupon": off["coupon"]})
                else:
                    failed += 1; err1 = err1 or err
                    if "سلة" in err or "كوبون" in err:   # خطأ إعداد: لا تُكرّره ٥٠٠ مرة
                        break
            return self._send(200, {"made": made, "failed": failed, "error": err1})

        if path == "/api/wa/offer/hide":
            off = renewals.hide_offer(str(req.get("token", "")), bool(req.get("on", True)))
            return self._send(200 if off else 404, {"ok": bool(off)})

        if path == "/api/wa/optout":
            return self._send(200, {"optout": renewals.set_optout(str(req.get("phone", "")),
                                                                 bool(req.get("on", True)))})

        phone = renewals.norm_phone(str(req.get("phone", "")))
        kind = str(req.get("kind", "d7"))
        cust = next((c for c in renewals.customers() if c["phone"] == phone), None)
        if not cust:
            return self._send(404, {"error": "العميل غير موجود"})
        text = renewals.render(cust, kind)

        if path == "/api/wa/message":
            return self._send(200, {"text": text})

        if path == "/api/wa/send":
            wa = renewals.load_wa(); s = wa["settings"]
            if phone in wa["optout"]:
                return self._send(400, {"error": "هذا الرقم في قائمة لا تراسلني"})
            sent = renewals.sent_today()
            if sent >= int(s.get("daily_cap", 80)):
                return self._send(200, {"sent_today": sent, "warn":
                    f"بلغت السقف اليومي ({s['daily_cap']} رسالة). توقّف اليوم — تجاوزه يعرّض رقمك للحظر."})
            link, note, ok = "", "يدوي", True
            if s.get("send_url"):
                try:
                    body = json.dumps({"phone": phone, "text": text}).encode()
                    rq = Request(s["send_url"], data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + s.get("send_token", "")})
                    with urlopen(rq, timeout=25) as r:
                        r.read()
                    note = "آلي"
                except Exception as e:
                    ok, note = False, f"فشل الإرسال: {e}"
            else:
                link = renewals.wa_link(phone, text)
            renewals.log_send(phone, kind, ok, note)
            return self._send(200, {"link": link, "text": text, "ok": ok, "note": note,
                                    "sent_today": sent + 1,
                                    "warn": "" if ok else note})
        return self._send(404, {"error": "not found"})

    def _create(self, acct):
        req = self._body()
        host = str(req.get("host") or "").strip()
        if host and not host.startswith(("http://", "https://")):
            return self._send(400, {"error": "الهوست يجب أن يبدأ بـ http:// أو https://"})
        pkg = next((p for p in get_packages(acct) if str(p["id"]) == str(req.get("package_id"))), None)
        if not pkg:
            return self._send(400, {"error": "الباقة غير موجودة"})
        count = max(1, min(int(req.get("count", 1)), 50))
        out = [create_line(acct, pkg, req.get("username") if count == 1 else None,
                           req.get("password") if count == 1 else None, host) for _ in range(count)]
        self._send(200, {"lines": out})


def web():
    print(f"الصفحة تعمل: http://{BIND}:{PORT}   (Ctrl+C للإيقاف)", flush=True)
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "cli"
    if mode == "web":
        web()
    elif mode == "debug":
        print(json.dumps(api(pick_account(), "get_packages"), ensure_ascii=False, indent=2)[:4000])
    else:
        cli()

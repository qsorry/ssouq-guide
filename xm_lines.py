#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Xtream-Masters — إنشاء يوزرات M3U Lines (متعدد الحسابات)
--------------------------------------------------------
التشغيل:
  python xm_lines.py web      ← يشغّل الصفحة على http://127.0.0.1:8080
  python xm_lines.py          ← وضع سطر الأوامر
  python xm_lines.py debug    ← يطبع رد get_packages الخام

أول مرة تفتح الصفحة تضع كلمة مرور المدير، ثم من /admin تضيف الحسابات
(لكل حساب: اسم دخول، كلمة مرور، رابط API، مفتاح API، هوست).
البيانات تُحفظ في data/accounts.json. لا يحتاج أي مكتبات خارجية (Python 3.8+).
"""
import json, os, sys, secrets, datetime, base64, hmac, hashlib, threading
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ================= الإعدادات =================
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.environ.get("XM_DATA", os.path.join(BASE_DIR, "data"))
ACC_FILE  = os.path.join(DATA_DIR, "accounts.json")
TXT_FILE  = os.path.join(DATA_DIR, "lines.txt")
PAGES     = {"/": "xm_lines.html", "/admin": "admin.html", "/setup": "setup.html"}
PORT      = int(os.environ.get("XM_PORT", "8080"))
BIND      = os.environ.get("XM_BIND", "127.0.0.1")   # في الحاوية: 0.0.0.0
ADMIN_USER = "admin"                                  # اسم دخول المدير
DIGITS    = 12                                        # طول اليوزر والباسورد (أرقام)
# ============================================

_lock = threading.Lock()


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
        sys.exit("لا توجد حسابات. شغّل الصفحة وأضف الحسابات من /admin أولاً.")
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
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _page(self, name):
        with open(os.path.join(BASE_DIR, name), "rb") as f:
            self._send(200, raw=f.read(), ctype="text/html; charset=utf-8")

    def _redirect(self, to):
        self._send(302, raw=b"", ctype="text/plain", extra={"Location": to})

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def log_message(self, *a):
        pass

    def _who(self, st):
        """('admin', None) أو ('account', acct) أو (None, None) بعد إرسال 401."""
        h = self.headers.get("Authorization", "")
        if h.startswith("Basic "):
            try:
                u, _, p = base64.b64decode(h[6:]).decode("utf-8", "replace").partition(":")
                if u == ADMIN_USER and check_pw(p, st["admin"]):
                    return "admin", None
                for a in st["accounts"]:
                    if hmac.compare_digest(u, a["user"]) and hmac.compare_digest(p, a["password"]):
                        return "account", a
            except Exception:
                pass
        self._send(401, raw=b"", ctype="text/plain; charset=utf-8",
                   extra={"WWW-Authenticate": 'Basic realm="XM Lines", charset="UTF-8"'})
        return None, None

    # ---------- GET ----------
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/robots.txt":
            return self._send(200, raw=b"User-agent: *\nDisallow: /\n", ctype="text/plain; charset=utf-8")
        st = load_store()
        # الإعداد الأول: لا يوجد مدير بعد
        if not st["admin"]:
            if path == "/setup":
                return self._page(PAGES["/setup"])
            return self._redirect("/setup")
        if path == "/setup":
            return self._redirect("/")
        if path == "/logout":
            return self._send(401, raw="تم تسجيل الخروج".encode(), ctype="text/plain; charset=utf-8",
                              extra={"WWW-Authenticate": 'Basic realm="XM Lines", charset="UTF-8"'})
        role, acct = self._who(st)
        if not role:
            return
        try:
            if path == "/":
                return self._redirect("/admin") if role == "admin" else self._page(PAGES["/"])
            if path == "/admin":
                return self._page(PAGES["/admin"]) if role == "admin" else self._send(403, {"error": "للمدير فقط"})
            if path == "/api/me":
                return self._send(200, {"role": role, "account": acct["name"] if acct else None})
            if path == "/api/packages":
                if role != "account":
                    return self._send(403, {"error": "ادخل بحساب مستخدم وليس المدير"})
                return self._send(200, {"account": acct["name"], "host": acct["host"], "packages": get_packages(acct)})
            if path == "/api/accounts":
                if role != "admin":
                    return self._send(403, {"error": "للمدير فقط"})
                return self._send(200, {"accounts": st["accounts"]})
            self._send(404, {"error": "not found"})
        except Exception as e:
            self._send(500, {"error": str(e)})

    # ---------- POST ----------
    def do_POST(self):
        path = self.path.split("?", 1)[0]
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
                    return self._send(200, {"ok": True})
                if not st["admin"]:
                    return self._send(400, {"error": "أكمل الإعداد أولاً"})
                role, acct = self._who(st)
                if not role:
                    return
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
        else:
            return self._send(404, {"error": "not found"})
        save_store(st)
        self._send(200, {"ok": True, "accounts": st["accounts"]})

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

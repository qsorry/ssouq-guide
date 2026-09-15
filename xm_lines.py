#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Xtream-Masters — إنشاء يوزرات M3U Lines
---------------------------------------
التشغيل:
  python xm_lines.py          ← وضع سطر الأوامر: يعرض الباقات، تختار رقم، ينشئ اليوزر ويحفظه في lines.txt
  python xm_lines.py web      ← يشغّل الصفحة على http://127.0.0.1:8080 (ضع xm_lines.html بجانب هذا الملف)
  python xm_lines.py debug    ← يطبع رد get_packages الخام (للتأكد من أسماء الحقول)

لا يحتاج أي مكتبات خارجية (Python 3.8+).
"""
import json, os, sys, secrets, datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ================= الإعدادات =================
API_URL  = "http://mr7-4k.live:80/msAPIufgk/reseller/index.php"
API_KEY  = os.environ.get("XM_API_KEY", "5d8e14c6870a10f36379418ee1a60993")
HOST     = "http://mr7-4k.live:80"          # الهوست الذي يظهر للعميل في السطر
TXT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lines.txt")
HTML_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xm_lines.html")
PORT     = int(os.environ.get("XM_PORT", "8080"))
BIND     = os.environ.get("XM_BIND", "127.0.0.1")   # في الحاوية: 0.0.0.0
DIGITS   = 12                                # طول اليوزر والباسورد (أرقام)
# ============================================


def api(action, params=None, post=False):
    q = {"api_key": API_KEY, "action": action}
    body = None
    if post:
        body = urlencode(params or {}, doseq=True).encode()
    else:
        q.update(params or {})
    url = API_URL + "?" + urlencode(q, doseq=True)
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


def get_packages():
    pkgs = []
    for p in _unwrap(api("get_packages")):
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


def create_line(pkg, username=None, password=None, host=None):
    host = (host or HOST).strip().rstrip("/")
    username = username or rand_digits()
    password = password or rand_digits()
    params = {
        "username": username,
        "password": password,
        "package": pkg["id"],
        "max_connections": pkg.get("max_connections") or 1,
        "bouquets_selected[]": pkg["bouquets"],  # اختيار كل Subscribed
    }
    r = api("create_line", params, post=True)
    ok = isinstance(r, dict) and (
        r.get("status") in ("STATUS_SUCCESS", "success", True) or r.get("result") is True)
    if not ok:
        raise RuntimeError("فشل الإنشاء: " + json.dumps(r, ensure_ascii=False)[:400])
    data = r.get("data") if isinstance(r.get("data"), dict) else {}
    username = data.get("username", username)
    password = data.get("password", password)
    line = f"Host {host}  Password {password} Username {username}"
    now = datetime.datetime.now()
    with open(TXT_FILE, "a", encoding="utf-8") as f:
        f.write(f"{now:%d-%m-%Y %H:%M}  |  {line}  |  {pkg['name']}\n")
    return {"line": line, "username": username, "password": password,
            "package": pkg["name"], "time": now.isoformat(timespec="seconds")}


# ---------------- وضع سطر الأوامر ----------------
def cli():
    pkgs = get_packages()
    if not pkgs:
        print("لا توجد باقات. شغّل: python xm_lines.py debug")
        return
    for i, p in enumerate(pkgs, 1):
        print(f"{i}) {p['name']}  —  {len(p['bouquets'])} بوكيه")
    n = int(input("\nرقم الباقة: ").strip())
    count = int((input("عدد اليوزرات [1]: ").strip() or "1"))
    lines = []
    for _ in range(count):
        res = create_line(pkgs[n - 1])
        lines.append(res["line"])
        print(res["line"])
    print(f"\n✓ تم الحفظ في {TXT_FILE}")


# ---------------- وضع الصفحة ----------------
class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj=None, ctype="application/json; charset=utf-8", raw=None):
        body = raw if raw is not None else json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass

    def do_GET(self):
        try:
            if self.path in ("/", "/index.html"):
                with open(HTML_FILE, "rb") as f:
                    return self._send(200, raw=f.read(), ctype="text/html; charset=utf-8")
            if self.path == "/api/packages":
                return self._send(200, {"host": HOST, "packages": get_packages()})
            if self.path == "/robots.txt":
                return self._send(200, raw=b"User-agent: *\nDisallow: /\n", ctype="text/plain; charset=utf-8")
            self._send(404, {"error": "not found"})
        except Exception as e:
            self._send(500, {"error": str(e)})

    def do_POST(self):
        try:
            if self.path != "/api/create":
                return self._send(404, {"error": "not found"})
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
            host = str(req.get("host") or "").strip()
            if host and not host.startswith(("http://", "https://")):
                return self._send(400, {"error": "الهوست يجب أن يبدأ بـ http:// أو https://"})
            pkg = next((p for p in get_packages() if str(p["id"]) == str(req.get("package_id"))), None)
            if not pkg:
                return self._send(400, {"error": "الباقة غير موجودة"})
            count = max(1, min(int(req.get("count", 1)), 50))
            out = [create_line(pkg, req.get("username") if count == 1 else None,
                               req.get("password") if count == 1 else None, host) for _ in range(count)]
            self._send(200, {"lines": out})
        except Exception as e:
            self._send(500, {"error": str(e)})


def web():
    print(f"الصفحة تعمل: http://{BIND}:{PORT}   (Ctrl+C للإيقاف)", flush=True)
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "cli"
    if mode == "web":
        web()
    elif mode == "debug":
        print(json.dumps(api("get_packages"), ensure_ascii=False, indent=2)[:4000])
    else:
        cli()

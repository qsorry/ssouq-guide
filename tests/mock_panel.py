#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
لوحة Xtream-Masters وهمية لاختبار جلسة الويب (xm_web) بلا إنترنت ولا خدمة حقيقية.

تشغيل:  python tests/mock_panel.py 9077 demo secret

تحاكي التدفّق الحقيقي:
  GET  /token.php                     → توكن التحقّق البشري (نص)
  GET  /login                         → نموذج فيه lkey + كابتشا (captcha.php)
  GET  /captcha.php                   → صورة؛ الكود يُحفظ للجلسة ويُكشف في ترويسة
                                        X-Captcha-Code (للاختبار فقط)
  POST /login.php                     → 302 ?error=captcha / ?error=credentials
                                        أو 302 /dashboard عند النجاح
  GET  /user_reseller.php             → صفحة الإضافة (#user_form + member_id + باقات)
  GET  /user_reseller.php?action=get_package&package_id=..  → JSON بوكيهات
  POST /user_reseller.php (submit_user=1)  → إنشاء اليوزر
  GET  /table_search.php?search[value]=..  → صف اللاين المُنشأ
  أي مسار محمي بلا جلسة → 302 /login
"""
import sys
import re
import json
import time
import secrets
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9077
USER = sys.argv[2] if len(sys.argv) > 2 else "demo"
PASS = sys.argv[3] if len(sys.argv) > 3 else "secret"

SESSIONS = {}   # phpsessid -> {captcha, auth}
LINES = []      # created lines
PACKAGES = [(1, "1 Month (5 credits)"), (3, "3 Months (13 credits)"), (12, "12 Months (45 credits)")]
BOUQUETS = {1: [1, 2, 3], 3: [1, 2, 3, 4, 5], 12: [1, 2, 3, 4, 5, 6, 7]}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _sid(self):
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "PHPSESSID":
                return v
        return ""

    def _ensure_sid(self, extra=None):
        sid = self._sid()
        headers = {}
        if not sid:
            sid = secrets.token_hex(12)
            headers["Set-Cookie"] = f"PHPSESSID={sid}; Path=/"
        SESSIONS.setdefault(sid, {"captcha": "", "auth": False})
        if extra:
            headers.update(extra)
        return sid, headers

    def _send(self, code, body=b"", ctype="text/html; charset=utf-8", headers=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _has_human(self):
        return "xm_simple_security_check=" in self.headers.get("Cookie", "")

    # ---------------- GET ----------------
    def do_GET(self):
        u = urlparse(self.path)
        path, qs = u.path, parse_qs(u.query)

        if path == "/token.php":
            return self._send(200, secrets.token_urlsafe(32), "text/plain")

        # بوابة التحقّق البشري
        if not self._has_human() and path not in ("/token.php",):
            return self._send(200, 'xm_simple_security_check<script>fetch("token.php")'
                                    '.then(r=>r.text()).then(t=>{document.cookie='
                                    '"xm_simple_security_check="+t+";path=/";location.href="login";});</script>')

        sid, hdr = self._ensure_sid()

        if path == "/captcha.php":
            code = str(secrets.randbelow(900) + 100)  # 3 أرقام
            SESSIONS[sid]["captcha"] = code
            hdr2 = dict(hdr)
            hdr2["X-Captcha-Code"] = code   # للاختبار فقط
            # صورة GIF 1×1 بسيطة (يكفي أن يكون نوعها صورة)
            gif = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!"
                   b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01"
                   b"\x00\x00\x02\x02D\x01\x00;")
            return self._send(200, gif, "image/gif", hdr2)

        if path == "/login":
            SESSIONS[sid].setdefault("lkey", secrets.token_hex(4))
            err = ""
            if "error" in qs:
                err = '<p class="alert">error: %s</p>' % qs["error"][0]
            html = (
                '<!DOCTYPE html><html><head><title>Login</title></head><body>' + err +
                '<form action="./login.php" method="POST" id="login_form">'
                '<input type="hidden" name="referrer" value="">'
                '<input type="hidden" name="access_code" value="">'
                '<input type="text" name="username" id="username">'
                '<input type="password" name="password" id="password">'
                '<input type="text" name="lkey" value="%s">'
                '<img src="captcha.php?a=1"><input type="text" name="captcha">'
                '<button type="submit">Login</button></form></body></html>' % SESSIONS[sid]["lkey"])
            return self._send(200, html, headers=hdr)

        # محمي
        if not SESSIONS[sid].get("auth"):
            return self._send(302, b"", "text/plain", {**hdr, "Location": "/login"})

        if path == "/user_reseller.php" and qs.get("action", [""])[0] == "get_package":
            pid = int(qs.get("package_id", ["0"])[0] or 0)
            body = json.dumps({"bouquets": [{"id": b} for b in BOUQUETS.get(pid, [])]})
            return self._send(200, body, "application/json", hdr)

        if path in ("/user_reseller.php", "/line.php", "/user.php"):
            opts = "".join('<option value="%d">%s</option>' % (i, t) for i, t in PACKAGES)
            html = (
                '<!DOCTYPE html><html><body><form id="user_form" action="./user_reseller.php" method="post">'
                '<input type="hidden" name="member_id" value="8842">'
                '<input type="hidden" name="is_official" value="1">'
                '<input type="hidden" name="custom_playlist_id" value="">'
                '<input type="text" name="username"><input type="password" name="password">'
                '<select name="package"><option value="">Select</option>' + opts + '</select>'
                '<button name="submit_user" value="1">Create</button></form></body></html>')
            return self._send(200, html, headers=hdr)

        if path == "/table_search.php":
            if qs.get("id", [""])[0] != "users":   # اللوحة تتطلب id=users
                return self._send(200, json.dumps({"draw": 1, "recordsFiltered": 0, "data": []}),
                                  "application/json", hdr)
            term = qs.get("search[value]", [""])[0]
            desc = qs.get("order[0][dir]", ["asc"])[0] == "desc"      # الأحدث أولًا
            length = int(qs.get("length", ["10"])[0] or 10)
            data = []
            for ln in (list(reversed(LINES)) if desc else LINES):
                if not term or term in ln["username"] or term in ln["password"]:   # بحث كل الأعمدة
                    row = ('<a href="?userid=%s">edit</a> User: %s Pass: %s End: %s '
                           '<a>1 / %s</a>' % (ln["id"], ln["username"], ln["password"],
                                              ln["end"], ln["conns"]))
                    data.append([row])
            data = data[:length]
            return self._send(200, json.dumps({"draw": 1, "recordsTotal": len(LINES),
                                               "recordsFiltered": len(data), "data": data}),
                              "application/json", hdr)

        if path in ("/", "/dashboard"):
            credits = 1002
            active = 253 + len(LINES)
            html = (
                '<!DOCTYPE html><html><body>'
                '<div class="topbar"><span class="credits-box">Credits: %d</span>'
                '<span class="user">Okyesno</span></div>'
                '<div class="cards">'
                '<div class="card"><h3>6</h3><p>ONLINE USERS</p></div>'
                '<div class="card"><h3>26</h3><p>CREATED TODAY</p></div>'
                '<div class="card"><h3>253</h3><p>CREATED THIS MONTH</p></div>'
                '<div class="card"><h3>%d</h3><p>ACTIVE SUBSCRIPTIONS</p></div>'
                '<div class="card"><h3>6</h3><p>OPEN CONNECTIONS</p></div>'
                '</div></body></html>' % (credits, active))
            return self._send(200, html, headers=hdr)

        return self._send(404, "404", "text/plain", hdr)

    def do_HEAD(self):
        self.do_GET()

    # ---------------- POST ----------------
    def do_POST(self):
        u = urlparse(self.path)
        path = u.path
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n).decode("utf-8", "replace")
        form = {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}
        # قوائم (selected_bouquets تأتي كنص JSON، لا مشكلة)
        sid, hdr = self._ensure_sid()

        if path == "/login.php":
            want = SESSIONS[sid].get("captcha", "")
            if not want or form.get("captcha", "") != want:
                return self._send(302, b"", "text/plain", {**hdr, "Location": "?error=captcha"})
            if form.get("username") != USER or form.get("password") != PASS:
                # كما اللوحة الحقيقية: 200 + صفحة الدخول مع تنبيه، لا تحويل ?error=
                html = ('<!DOCTYPE html><html><head><title>Xtream-Masters - Login</title></head><body>'
                        '<div class="alert alert-danger alert-dismissible" role="alert">'
                        'Incorrect username or password! Please try again.</div>'
                        '<form action="./login.php" method="POST" id="login_form">'
                        '<input type="text" name="username"><input type="password" name="password">'
                        '<input type="text" name="captcha"></form></body></html>')
                return self._send(200, html, headers=hdr)
            SESSIONS[sid]["auth"] = True
            return self._send(302, b"", "text/plain", {**hdr, "Location": "/dashboard"})

        if not SESSIONS[sid].get("auth"):
            return self._send(302, b"", "text/plain", {**hdr, "Location": "/login"})

        if path in ("/user_reseller.php", "/line.php", "/user.php") and form.get("submit_user") == "1":
            uname = form.get("username", "")
            if not uname:
                return self._send(200, '<div class="alert">username required</div>', headers=hdr)
            LINES.append({
                "id": str(secrets.randbelow(9000) + 1000),
                "username": uname, "password": form.get("password", ""),
                "package": form.get("package", ""), "member_id": form.get("member_id", ""),
                "bouquets": form.get("selected_bouquets", ""),
                "end": "2026-12-31", "conns": "1",
            })
            return self._send(200, '<div class="alert alert-success">created</div>', headers=hdr)

        return self._send(404, "404", "text/plain", hdr)


if __name__ == "__main__":
    print(f"mock panel :{PORT} user={USER}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()

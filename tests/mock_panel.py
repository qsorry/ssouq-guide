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
# alt = لوحة بشكل آخر (ككاسبر): صفحة الدخول على /login.php لا /login، وصورة الكابتشا على
# img/verify.php لا captcha.php (الذي يرد 404 HTML) — تختبر اكتشاف الرابط من الصفحة.
VARIANT = sys.argv[4] if len(sys.argv) > 4 else ""
ALT = VARIANT == "alt"
# nocap = لوحة بلا كود تحقق إطلاقًا (ككاسبر): لا صورة في صفحة الدخول ولا حقل captcha، و/captcha.php يرد 404.
NOCAP = VARIANT == "nocap"
LOGIN_PATH = "/login.php" if ALT else "/login"
CAPTCHA_PATH = "/img/verify.php" if ALT else "/captcha.php"
CAPTCHA_SRC = "img/verify.php?x=1" if ALT else "captcha.php?a=1"

SESSIONS = {}   # phpsessid -> {captcha, auth}
LINES = []      # created lines
PACKAGES = [(1, "1 Month (5 credits)"), (3, "3 Months (13 credits)"), (12, "12 Months (45 credits)"),
            (15, "اشتراك سنة + 3 اشهر (6 نقاط)")]
BOUQUETS = {1: [1, 2, 3], 3: [1, 2, 3, 4, 5], 12: [1, 2, 3, 4, 5, 6, 7], 15: [1, 2, 3, 4, 5, 6, 7]}
# extend_fail = لوحة تقبل الإنشاء لكن تمديدها يفشل (لاختبار «أُنشئ بالباقة الأساسية فقط»).
EXTEND_FAIL = VARIANT == "extend_fail"
EXTENDS = []    # (line id, package) لكل تمديد ناجح


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

        if path == CAPTCHA_PATH and not NOCAP:
            code = str(secrets.randbelow(900) + 100)  # 3 أرقام
            SESSIONS[sid]["captcha"] = code
            hdr2 = dict(hdr)
            hdr2["X-Captcha-Code"] = code   # للاختبار فقط
            # صورة GIF 1×1 بسيطة (يكفي أن يكون نوعها صورة)
            gif = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!"
                   b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01"
                   b"\x00\x00\x02\x02D\x01\x00;")
            return self._send(200, gif, "image/gif", hdr2)

        if path == LOGIN_PATH:
            SESSIONS[sid].setdefault("lkey", secrets.token_hex(4))
            err = ""
            if "error" in qs:
                err = '<p class="alert">error: %s</p>' % qs["error"][0]
            cap = '' if NOCAP else '<img src="%s"><input type="text" name="captcha">' % CAPTCHA_SRC
            html = (
                '<!DOCTYPE html><html><head><title>Login</title></head><body>' + err +
                '<form action="./login.php" method="POST" id="login_form">'
                '<input type="hidden" name="referrer" value="">'
                '<input type="hidden" name="access_code" value="">'
                '<input type="text" name="username" id="username">'
                '<input type="password" name="password" id="password">'
                '<input type="text" name="lkey" value="' + SESSIONS[sid]["lkey"] + '">' + cap +
                '<button type="submit">Login</button></form></body></html>')
            return self._send(200, html, headers=hdr)

        # محمي
        if not SESSIONS[sid].get("auth"):
            return self._send(302, b"", "text/plain", {**hdr, "Location": LOGIN_PATH})

        # nocap (Xtream Codes الأصلي): لا نداء get_package أصلًا — أي action يُعيد صفحة الإضافة
        # نفسها HTML، والبوكيهات يحدّدها الخادم من الباقة.
        if path == "/user_reseller.php" and qs.get("action", [""])[0] == "get_package" and not NOCAP:
            pid = int(qs.get("package_id", ["0"])[0] or 0)
            body = json.dumps({"bouquets": [{"id": b} for b in BOUQUETS.get(pid, [])]})
            return self._send(200, body, "application/json", hdr)

        if path == "/user_reseller_extend_modal.php" and not NOCAP:
            lid = qs.get("id", [""])[0]
            ln = next((l for l in LINES if l["id"] == lid), None)
            if not ln:
                return self._send(200, '<div class="alert alert-danger">Line not found</div>', headers=hdr)
            # كما اللوحة: تمديد بباقات نفس عدد الاتصالات فقط، والخيار يحمل data-connections
            opts = "".join('<option value="%d" data-connections="1">%s</option>' % (i, t) for i, t in PACKAGES)
            html = ('<div class="modal-body"><form id="extend_user_form" method="post">'
                    '<input type="hidden" name="edit" value="%s">'
                    '<input type="hidden" name="keep_remaining_days" value="0">'
                    '<input type="hidden" name="group_change_confirmed" value="0">'
                    '<select name="package" id="ext_package"><option value="">Select package</option>' + opts + '</select>'
                    '<input type="hidden" name="selected_connections" value="1">'
                    '<button name="submit_user" value="1">Extend</button></form></div>') % ln["id"]
            return self._send(200, html, headers=hdr)

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

        if path == "/table_search.php" and NOCAP:   # Xtream Codes: الجدول موجود لكنه لا يجد يوزرنا أبدًا (أعمدة/بحث آخران)
            return self._send(200, json.dumps({"draw": 1, "recordsTotal": 0, "recordsFiltered": 0, "data": []}),
                              "application/json", hdr)
        if path == "/table_search.php":
            if qs.get("id", [""])[0] != "users":   # اللوحة تتطلب id=users
                return self._send(200, json.dumps({"draw": 1, "recordsFiltered": 0, "data": []}),
                                  "application/json", hdr)
            term = qs.get("search[value]", [""])[0]
            desc = qs.get("order[0][dir]", ["asc"])[0] == "desc"      # الأحدث أولًا
            length = int(qs.get("length", ["10"])[0] or 10)
            c_from, c_to = qs.get("date_created_from", [""])[0], qs.get("date_created_to", [""])[0]
            data = []
            for ln in (list(reversed(LINES)) if desc else LINES):
                if c_from and ln["created"] < c_from:
                    continue
                if c_to and ln["created"] > c_to:
                    continue
                if not term or term in ln["username"] or term in ln["password"]:   # بحث كل الأعمدة
                    row = ('<a href="?userid=%s">edit</a> User: %s Pass: %s End: %s '
                           '<a>1 / %s</a>' % (ln["id"], ln["username"], ln["password"],
                                              ln["end"], ln["conns"]))
                    data.append([row])
            filtered = len(data)
            data = data[:length]
            return self._send(200, json.dumps({"draw": 1, "recordsTotal": len(LINES),
                                               "recordsFiltered": filtered, "data": data}),
                              "application/json", hdr)

        if path == "/":                       # الجذر يحوّل للوحة كاللوحة الحقيقية
            return self._send(302, b"", "text/plain", {**hdr, "Location": "/dashboard"})
        if path == "/dashboard" and NOCAP:
            html = ('<!DOCTYPE html><html><body><ul class="sidebar"><li><a>Credits</a><span class="badge">1</span></li></ul>'
                    '<div class="card"><h3>1</h3><p>OPEN CONNECTIONS</p></div>'
                    '<div class="card"><h3>%d</h3><p>ACTIVE ACCOUNTS</p></div>'
                    '<div class="card-bg credits"><h3><span data-plugin="counterup" class="entry">0</span></h3><p>Credits</p></div>'
                    '<small>[<b>User Panel</b>] New M3U with Package [YEAR], Credits: <font color="green">3976</font> -> <font color="red">3975.5</font></small>'
                    '</body></html>' % (4742 + len(LINES)))
            return self._send(200, html, headers=hdr)
        if path == "/dashboard":
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
            if not NOCAP and (not want or form.get("captcha", "") != want):
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
            return self._send(302, b"", "text/plain", {**hdr, "Location": LOGIN_PATH})

        if path in ("/user_reseller.php", "/line.php", "/user.php") and form.get("submit_user") == "1":
            uname = form.get("username", "")
            if not uname:
                return self._send(200, '<div class="alert">username required</div>', headers=hdr)
            if NOCAP and "selected_bouquets" in form:   # Xtream Codes لا يعرف هذا الحقل
                return self._send(200, '<div class="alert alert-danger">Error: unknown field selected_bouquets</div>', headers=hdr)
            LINES.append({
                "id": str(secrets.randbelow(9000) + 1000),
                "username": uname, "password": form.get("password", ""),
                "package": form.get("package", ""), "member_id": form.get("member_id", ""),
                "bouquets": form.get("selected_bouquets", ""),
                "end": "2026-12-31", "conns": "1",
                # يوزر اسمه يبدأ بـ old_ يُعدّ مُنشأً بالأمس (لاختبار «اشتراكات اليوم»)
                "created": "2000-01-01" if uname.startswith("old") else time.strftime("%Y-%m-%d"),
            })
            return self._send(200, '<div class="alert alert-success">created</div>', headers=hdr)

        if path == "/user_reseller_extend_modal.php" and not NOCAP:
            lid = urlparse(self.path).query.split("id=")[-1].split("&")[0] if "id=" in self.path else ""
            ln = next((l for l in LINES if l["id"] == (form.get("edit") or lid)), None)
            if not ln or form.get("submit_user") != "1" or not form.get("package"):
                return self._send(200, json.dumps({"status": "error", "message": "Invalid extend request"}),
                                  "application/json", hdr)
            if EXTEND_FAIL:
                return self._send(200, json.dumps({"status": "error", "message": "Insufficient credits"}),
                                  "application/json", hdr)
            # يضيف أشهر الباقة على تاريخ الانتهاء (السنة فقط تكفي للاختبار)
            months = int(form["package"]) if form["package"].isdigit() else 1
            y, m, d = (int(x) for x in ln["end"].split("-"))
            m += months
            y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
            ln["end"] = "%04d-%02d-%02d" % (y, m, d)
            EXTENDS.append((ln["id"], form["package"]))
            return self._send(200, json.dumps({"status": "success", "message": "User extended",
                                               "new_credits": "994"}), "application/json", hdr)

        return self._send(404, "404", "text/plain", hdr)


if __name__ == "__main__":
    print(f"mock panel :{PORT} user={USER}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()

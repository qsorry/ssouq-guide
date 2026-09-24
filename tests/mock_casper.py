#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""لوحة كاسبر وهمية تحاكي c4kpanel: دخولٌ بسيط بلا كابتشا، وقائمة يوزرات
بترقيم صفحاتٍ بنفس ترتيب أعمدة اللوحة الحقيقية. تكفي لاختبار CasperWebSession
بلا شبكة. تُشغَّل في خيط داخل الاختبار.

الأعمدة كما في اللوحة: ID · · Reseller · Fullname · Username · Password ·
Package · Lock · Created · Expire · Notes · MAX Conn. · · Options.
"""

import http.server
import threading


PER_PAGE = 50


def _make_users(n):
    out = []
    for i in range(n):
        mo = (15, 6, 12)[i % 3]
        pkg = {15: "15 Months", 6: "6 Months", 12: "1 Year"}[mo]
        out.append({
            "id": str(100000 + i),
            "username": "u%05d" % i,
            "password": "p%05d" % i,
            "package": pkg,
            "created": "2026-01-01",
            "exp": "2027-04-01 12:00" if mo == 15 else "2026-07-01 12:00",
            "conns": "0/1",
        })
    return out


class _Handler(http.server.BaseHTTPRequestHandler):
    users = _make_users(120)          # تُستبدل من الخادم
    ctx = "/iptv"

    def log_message(self, *a):
        pass

    def _html(self, code, body):
        raw = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    def _authed(self):
        return "casper_sess=1" in (self.headers.get("Cookie") or "")

    def _login_page(self, err=False):
        return ("<!DOCTYPE html><html><head><title>Casper Vip</title></head><body>"
                "<form class='form-signin' method='POST'>"
                "<input type='text' name='username' required>"
                "<input type='password' name='password' required>"
                "<button type='submit'>Login</button>"
                "<input type='hidden' name='maa' value='do_login' /></form></body></html>")

    def _rows_html(self, page):
        total = len(self.users)
        last = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        chunk = self.users[(page - 1) * PER_PAGE: page * PER_PAGE]
        trs = []
        for u in chunk:
            trs.append(
                "<tr>"
                "<td>%s</td>"                       # 0 id
                "<td><a>on</a></td>"                # 1 online
                "<td>reseller1</td>"                # 2 reseller (يتكرّر — فخّ)
                "<td>Full</td>"                     # 3 fullname
                "<td>%s</td>"                       # 4 username
                "<td>%s</td>"                       # 5 password
                "<td>%s</td>"                       # 6 package
                "<td></td>"                         # 7 lock
                "<td>%s</td>"                       # 8 created
                "<td><span class='edit' data-name=\"exp_date\">%s</span></td>"  # 9 expire
                "<td></td>"                         # 10 notes
                "<td>%s</td>"                       # 11 max conn
                "<td></td>"                         # 12
                "<td><a>opts</a></td>"              # 13 options
                "</tr>" % (u["id"], u["username"], u["password"], u["package"],
                           u["created"], u["exp"], u["conns"]))
        pag = "".join(
            "<li><a href='/iptv/index.php/users/index?&amp;page=%d'>%d</a></li>" % (p, p)
            for p in range(1, last + 1))
        return ("<!DOCTYPE html><html><head><title>Casper Vip</title></head><body>"
                "<table id='table_codes'><thead><tr>"
                "<th>ID</th><th></th><th>Reseller</th><th>Fullname</th><th>Username</th>"
                "<th>Password</th><th>Package</th><th>Lock</th><th>Created on</th>"
                "<th>Expire</th><th>Notes</th><th>MAX Conn.</th><th></th><th>Options</th>"
                "</tr></thead><tbody>%s</tbody></table>"
                "<ul class='pagination'>%s</ul></body></html>" % ("".join(trs), pag))

    def do_GET(self):
        p = self.path
        if "login.php" in p:
            return self._html(200, self._login_page())
        if not self._authed():
            self.send_response(303)
            self.send_header("Location", self.ctx + "/login.php?auth=0")
            self.end_headers()
            return
        if "index.php/home/index" in p:
            return self._html(200, "<html><body>Dashboard OK</body></html>")
        if "index.php/users/index" in p:
            page = 1
            if "page=" in p:
                try:
                    page = int(p.split("page=")[1].split("&")[0])
                except ValueError:
                    page = 1
            return self._html(200, self._rows_html(page))
        return self._html(404, "<html>404</html>")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n).decode("utf-8", "replace")
        if "login.php" in self.path and "do_login" in body and "username=" in body:
            # نجاح إن أُرسلت بيانات (المحاكاة لا تتحقّق من الصحّة)
            self.send_response(303)
            self.send_header("Location", self.ctx + "/index.php/home/index")
            self.send_header("Set-Cookie", "casper_sess=1; path=/")
            self.end_headers()
            return
        self._html(400, "bad")


def start(user_count=120, host="127.0.0.1", port=0):
    """يشغّل لوحة كاسبر وهمية ويعيد (server, base_url, thread)."""
    _Handler.users = _make_users(user_count)
    srv = http.server.ThreadingHTTPServer((host, port), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = "http://%s:%d/iptv" % (host, srv.server_address[1])
    return srv, base, t

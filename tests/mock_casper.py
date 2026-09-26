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
import urllib.parse


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
            "online": (i % 5 == 0),          # بعضهم «متصل الآن» لاختبار عمود النشاط
        })
    return out


class _Handler(http.server.BaseHTTPRequestHandler):
    users = _make_users(120)          # تُستبدل من الخادم
    ctx = "/iptv"
    _gen = [0]                         # عدّاد اليوزرات المولَّدة من اللوحة
    _lock = threading.Lock()

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

    def _rows_html(self, page, users=None):
        src = self.users if users is None else users
        total = len(src)
        last = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        chunk = src[(page - 1) * PER_PAGE: page * PER_PAGE]
        trs = []
        for u in chunk:
            trs.append(
                "<tr>"
                "<td>%s</td>"                       # 0 id
                "<td title=\"%s\"><a>on</a></td>"   # 1 online (نقطة الحالة)
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
                "</tr>" % (u["id"], "online" if u.get("online") else "offline",
                           u["username"], u["password"], u["package"],
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

    def _add_form_html(self):
        """نموذج «إضافة يوزر» كما في اللوحة الحقيقية: يوزرٌ مملوءٌ سلفًا ومولَّدٌ
        من اللوحة (username/usernameold)، وحقلُ كلمة المرور **معطَّل** (disabled)
        قيمتُه «Auto Generated» — فلا يرسله المتصفح، فتولّد اللوحة كلمةً عشوائية."""
        with self._lock:
            self._gen[0] += 1
            u = "3%011d" % self._gen[0]        # يوزرٌ رقميّ بطول ١٢
        return ("<!DOCTYPE html><html><head><title>Casper Vip</title></head><body>"
                "<form method=\"POST\" name=\"form_add\" id='frmUsers' "
                "action=\"/iptv/index.php/users/doAdd\" enctype=\"multipart/form-data\">"
                "<input type=\"text\" name=\"username\" value=\"%s\" class=\"form-control\">"
                "<input type=\"text\" name=\"password\" disabled='' value=\"Auto Generated\" "
                "placeholder=\"Leave empty for random password\">"
                "<input type=\"hidden\" name=\"app_name\" value=\"users\">"
                "<input type=\"hidden\" name=\"t\" value=\"add\">"
                "<input type=\"hidden\" name=\"userid\" value=\"0\">"
                "<input type=\"hidden\" name=\"usernameold\" value=\"%s\">"
                "<input type=\"hidden\" name=\"id\" value=\"0\">"
                "<input type=\"hidden\" name=\"IF\" value=\"0\">"
                "<input type=\"hidden\" name=\"page\" value=\"0\">"
                "<input type=\"hidden\" name=\"setChosePkg\" value=\"\">"
                "<input type=\"hidden\" name=\"owner_mem_group\" value=\"0\">"
                "<select name=\"package\" id=\"package\">"
                "<option value=\"\">Choose Package</option>"
                "<option value=\"726\">15 Months [Credit: 1]</option>"
                "<option value=\"594\">1 Year [Credit: 1]</option>"
                "<option value=\"580\">6 Months [Credit: 0.5]</option>"
                "<option value=\"727\">1 Day</option></select>"
                "<select name=\"liveBq[]\" id=\"mag_bouquetLive\"></select>"
                "<select name=\"vodBq[]\" id=\"mag_bouquetVod\"></select>"
                "</form></body></html>" % (u, u))

    @staticmethod
    def _bouquets_html():
        return ("<select name=\"liveBq[]\" id=\"mag_bouquetLive\">"
                "<option value=\"1\">Live A</option><option value=\"2\">Live B</option></select>"
                "<select name=\"vodBq[]\" id=\"mag_bouquetVod\">"
                "<option value=\"10\">Vod A</option></select>")

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
            return self._html(200, "<html><body>Dashboard OK Credit : 6303</body></html>")
        if "index.php/users/Form" in p and "t=add" in p:
            return self._html(200, self._add_form_html())
        if "index.php/users/index" in p:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(p).query)
            if q.get("username"):                # فلتر الخادم بالاسم (كما في اللوحة الحقيقية)
                term = q["username"][0].replace("*", "").lower()
                hits = [u for u in self.users if term in u["username"].lower()]
                return self._html(200, self._rows_html(1, hits))
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
        if "global_ajax/getBouquets" in self.path:
            return self._html(200, self._bouquets_html())
        if "index.php/users/doAdd" in self.path:
            fields = urllib.parse.parse_qs(body, keep_blank_values=True)
            user = (fields.get("username") or [""])[0].strip()
            pkg = (fields.get("package") or [""])[0].strip()
            # حقلُ كلمة المرور معطَّلٌ في النموذج فلا يصل المتصفحُ به: غيابُه =
            # «اتركه فارغًا لكلمةٍ عشوائية» → نولّد رقمية. حضورُه = تُخزَّن كما هي
            # (نمذجةٌ للعطب القديم الذي كان يرسل «Auto Generated»).
            pw = (fields.get("password") or [None])[0]
            if not user:
                return self._html(400, "no username")
            if pw is None or pw == "":
                with self._lock:
                    self._gen[0] += 1
                    pw = "8%011d" % self._gen[0]      # كلمة مرورٍ رقمية مولَّدة
            names = {"726": "15 Months", "594": "1 Year", "580": "6 Months", "727": "1 Day"}
            with self._lock:
                self.users.insert(0, {                 # الأحدث أولًا (id:desc)
                    "id": str(1000000 + self._gen[0]),
                    "username": user, "password": pw,
                    "package": names.get(pkg, "15 Months"),
                    "created": "2026-09-25", "exp": "2027-12-25 22:54", "conns": "0/1"})
            return self._html(200, "<html><body>OK</body></html>")
        self._html(400, "bad")


def start(user_count=120, host="127.0.0.1", port=0):
    """يشغّل لوحة كاسبر وهمية ويعيد (server, base_url, thread)."""
    _Handler.users = _make_users(user_count)
    srv = http.server.ThreadingHTTPServer((host, port), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = "http://%s:%d/iptv" % (host, srv.server_address[1])
    return srv, base, t

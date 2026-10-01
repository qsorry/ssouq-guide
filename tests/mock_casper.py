#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""لوحة كاسبر وهمية تحاكي c4kpanel: دخولٌ بسيط بلا كابتشا، وقائمة يوزرات
بترقيم صفحاتٍ بنفس ترتيب أعمدة اللوحة الحقيقية. تكفي لاختبار CasperWebSession
بلا شبكة. تُشغَّل في خيط داخل الاختبار.

الأعمدة كما في اللوحة: ID · · Reseller · Fullname · Username · Password ·
Package · Lock · Created · Expire · Notes · MAX Conn. · · Options.

وللاشتراكات المجزّأة: رابط «تعديل» في خيارات كل صف، ونموذج تعديلٍ (Form?t=edit)
بالاسم وكلمة المرور والبوكيهات المحدَّدة، و doEdit يُنمذِج أخطارها: كلمة مرورٍ
فارغة تُولَّد جديدة، وبوكيهاتٌ غائبة تُمسح. `edits` يسجّل ما وصل.
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
    edits = []                         # (id, الحقول) لكل تعديلٍ وصل
    # سلوك الدخول كما في اللوحة الحقيقية (معطَّلٌ افتراضًا فلا يتغيّر ما سبقه من اختبارات):
    creds = None                       # (اليوزر، الباسورد) المقبولان؛ None = يُقبل أي شيء
    block = 0                          # حالة HTTP يحجب بها Cloudflare كل طلب (403/429)، 0 = لا حجب
    drop_logins = 0                    # كم دخولًا ناجحًا تسقط جلسته فورًا (دخولٌ آخر بالحساب)
    logins = []                        # كل محاولة دخول: (اليوزر، قُبلت؟)

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
        # رفض اللوحة الحقيقية: تنبيهٌ `alert bg-danger` (لا alert-danger) فوق النموذج نفسه،
        # وسكربت Cloudflare `challenge-platform` في كل صفحةٍ سليمة (ليس حجبًا).
        return ("<!DOCTYPE html><html><head><title>Casper Vip</title></head><body>"
                + ("<div class=\"alert bg-danger\" role=\"alert\">"
                   "<a href=\"#\" class=\"close\" data-dismiss=\"alert\">&times;</a>"
                   " Login error. Please check admin name/password. </div>" if err else "")
                + "<script src='/cdn-cgi/challenge-platform/scripts/jsd/main.js'></script>"
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
                "<td><a href='/iptv/index.php/users/Form?t=edit&amp;id=%s'>Edit</a> <a>opts</a></td>"  # 13 options
                "</tr>" % (u["id"], "online" if u.get("online") else "offline",
                           u["username"], u["password"], u["package"],
                           u["created"], u["exp"], u["conns"], u["id"]))
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

    def _edit_form_html(self, uid):
        u = next((x for x in self.users if x["id"] == uid), None)
        if not u:
            return None
        bq = u.get("bq", {"live": ["1", "2"], "vod": ["10"]})
        pk = {"15 Months": "726", "1 Year": "594", "6 Months": "580", "1 Day": "727"}.get(u["package"], "726")
        opt = lambda v, t, cur: '<option value="%s"%s>%s</option>' % (v, " selected" if v in cur else "", t)
        return ("<!DOCTYPE html><html><body>"
                "<form method=\"POST\" id='frmUsers' action=\"/iptv/index.php/users/doEdit\">"
                "<input type=\"text\" name=\"username\" value=\"%s\">"
                "<input type=\"text\" name=\"password\" value=\"%s\" placeholder=\"Leave empty for random password\">"
                "<input type=\"hidden\" name=\"usernameold\" value=\"%s\">"
                "<input type=\"hidden\" name=\"t\" value=\"edit\">"
                "<input type=\"hidden\" name=\"id\" value=\"%s\">"
                "<select name=\"package\"><option value=\"\">Choose Package</option>%s</select>"
                "<select name=\"liveBq[]\" multiple>%s</select>"
                "<select name=\"vodBq[]\" multiple>%s</select>"
                "<button type=\"submit\" class=\"btn\">Save</button>"
                "</form></body></html>" % (
                    u["username"], u["password"], u["username"], u["id"],
                    "".join(opt(v, t, [pk]) for v, t in (("726", "15 Months"), ("594", "1 Year"), ("580", "6 Months"))),
                    "".join(opt(v, t, bq["live"]) for v, t in (("1", "Live A"), ("2", "Live B"))),
                    "".join(opt(v, t, bq["vod"]) for v, t in (("10", "Vod A"),))))

    @staticmethod
    def _bouquets_html():
        return ("<select name=\"liveBq[]\" id=\"mag_bouquetLive\">"
                "<option value=\"1\">Live A</option><option value=\"2\">Live B</option></select>"
                "<select name=\"vodBq[]\" id=\"mag_bouquetVod\">"
                "<option value=\"10\">Vod A</option></select>")

    def _blocked(self):
        """حجب Cloudflare لخادمنا: صفحة تحدٍّ 403 أو حدّ طلبات 429 (error code: 1015)."""
        if not self.block:
            return False
        body = ("error code: 1015" if self.block == 429 else
                "<!DOCTYPE html><html><head><title>Just a moment...</title></head><body>"
                "Checking your browser · Cloudflare</body></html>")
        self._html(self.block, body)
        return True

    def do_GET(self):
        if self._blocked():
            return
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
        if "index.php/users/Form" in p and "t=edit" in p:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(p).query)
            html = self._edit_form_html((q.get("id") or [""])[0])
            return self._html(200 if html else 404, html or "<html>no user</html>")
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
        if self._blocked():
            return
        if "login.php" in self.path and "do_login" in body and "username=" in body:
            # نجاح إن أُرسلت بيانات؛ ومع `creds` تُطابَق كاللوحة الحقيقية، والخطأ يعيد
            # صفحة الدخول بتنبيه الرفض (200، لا تحويل).
            f = urllib.parse.parse_qs(body, keep_blank_values=True)
            got = ((f.get("username") or [""])[0], (f.get("password") or [""])[0])
            ok = self.creds is None or got == tuple(self.creds)
            with self._lock:
                self.logins.append((got[0], ok))
            if not ok:
                return self._html(200, self._login_page(err=True))
            with self._lock:
                dropped = self.drop_logins > 0
                if dropped:
                    _Handler.drop_logins -= 1
            self.send_response(303)
            self.send_header("Location", self.ctx + "/index.php/home/index")
            self.send_header("Set-Cookie", "casper_sess=%s; path=/" % ("0" if dropped else "1"))
            self.end_headers()
            return
        if "global_ajax/getBouquets" in self.path:
            return self._html(200, self._bouquets_html())
        if "index.php/users/doEdit" in self.path:
            f = urllib.parse.parse_qs(body, keep_blank_values=True)
            one = lambda k: (f.get(k) or [""])[0]
            with self._lock:
                self.edits.append((one("id"), f))
                u = next((x for x in self.users if x["id"] == one("id")), None)
                if not u or one("usernameold") != u["username"]:
                    return self._html(400, "bad user")
                new = one("username").strip() or u["username"]
                if any(x is not u and x["username"] == new for x in self.users):
                    return self._html(200, "<div class='alert alert-danger'>Username exists</div>")
                u["username"] = new
                pw = one("password")
                u["password"] = pw if pw else "gen%05d" % len(self.edits)   # فارغة = جديدة
                u["bq"] = {"live": f.get("liveBq[]", []), "vod": f.get("vodBq[]", [])}  # غائبة = مُسحت
            return self._html(200, "<html><body>OK</body></html>")
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
    _Handler.creds, _Handler.block, _Handler.drop_logins, _Handler.logins = None, 0, 0, []
    srv = http.server.ThreadingHTTPServer((host, port), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = "http://%s:%d/iptv" % (host, srv.server_address[1])
    return srv, base, t

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اختبار تكامل: الاشتراكات المجزّأة عبر HTTP كما يفعل المتصفح — الخادم الحقيقي مقابل
لوحاتٍ وهمية (مرح/Xtream، كاسبر، فالكون) وخادم بريدٍ وهمي، والدورة كل ثانية.

  • الميزة لعميلٍ بعينه: من لم تُفتح له لا يرى ولا يستطيع شيئًا.
  • إنشاء جزء ٦/٣/شهر من باقة ١٥ شهرًا على البوابات الثلاث، وبديلٍ عن رقمٍ مفقود بمدة ١٢
    شهرًا (الربط يحمل المدة، والباقي ٣ أشهر في «حسابات متبقية»).
  • عند انتهاء الجزء يتغيّر **اسم المستخدم وحده** على اللوحة — كلمة المرور والانتهاء
    والقنوات كما هي، ولا تمديد مدفوع — ويصير الخط «متاحًا» بما تبقّى.
  • لوحةٌ تقفل الاسم أو لا تتيح التعديل: لا يُرسَل شيء، ويصير «يحتاج تدخّلًا» ثم يُؤكَّد يدويًا.
  • الإشعارات (الجرس) وبريد الملخّص بلا كلمة مرور.

تشغيل:  python tests/test_split_web.py
"""
import datetime
import email
import email.policy
import glob
import http.cookiejar
import json
import os
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import mock_casper                                              # noqa: E402

P_MARAH, P_LOCK, P_FALCON, P_NOPATCH, P_APP = 9461, 9462, 9463, 9464, 9465
MARAH, LOCK = "http://127.0.0.1:%d" % P_MARAH, "http://127.0.0.1:%d" % P_LOCK
FALCON, NOPATCH = "http://127.0.0.1:%d/api/v1" % P_FALCON, "http://127.0.0.1:%d/api/v1" % P_NOPATCH
APP = "http://127.0.0.1:%d" % P_APP

_p = _f = 0


def check(label, cond, extra=""):
    global _p, _f
    if cond:
        _p += 1
        print("  \033[32mPASS\033[0m  %s%s" % (label, ("  (%s)" % extra) if extra else ""))
    else:
        _f += 1
        print("  \033[31mFAIL\033[0m  %s%s" % (label, ("  (%s)" % extra) if extra else ""))


# ---------------- خادم بريدٍ وهمي (SMTP بلا TLS) ----------------
MAILS = []


class _SMTP(socketserver.StreamRequestHandler):
    def handle(self):
        self.wfile.write(b"220 fake ESMTP\r\n")
        data, buf = False, []
        while True:
            line = self.rfile.readline()
            if not line:
                break
            if data:
                if line in (b".\r\n", b".\n"):
                    MAILS.append(b"".join(buf))
                    buf, data = [], False
                    self.wfile.write(b"250 OK\r\n")
                else:
                    buf.append(line[1:] if line.startswith(b"..") else line)
                continue
            cmd = line.strip().upper()
            if cmd.startswith(b"EHLO"):
                self.wfile.write(b"250-fake\r\n250 8BITMIME\r\n")
            elif cmd == b"DATA":
                data = True
                self.wfile.write(b"354 go\r\n")
            elif cmd == b"QUIT":
                self.wfile.write(b"221 bye\r\n")
                break
            else:
                self.wfile.write(b"250 OK\r\n")


def mails():
    out = []
    for raw in MAILS:
        m = email.message_from_bytes(raw, policy=email.policy.default)
        out.append((str(m["Subject"]), m.get_body().get_content()))
    return out


def up(url):
    for _ in range(80):
        try:
            urllib.request.urlopen(url, timeout=0.3)
            return True
        except urllib.error.HTTPError:
            return True
        except Exception:
            time.sleep(0.1)
    return False


class Client:
    """متصفّحٌ بكوكيزه: jreq(path, obj) → (رمز، JSON)."""

    def __init__(self):
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def jreq(self, path, obj=None):
        data = json.dumps(obj).encode() if obj is not None else None
        req = urllib.request.Request(APP + path, data=data, headers={"Content-Type": "application/json"},
                                     method="POST" if obj is not None else "GET")
        try:
            r = self.op.open(req, timeout=60)
            return r.getcode(), json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"{}")
            except Exception:
                return e.code, {}

    def status(self, path):
        class NoRedir(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        op = urllib.request.build_opener(NoRedir, *[h for h in self.op.handlers
                                                    if isinstance(h, urllib.request.HTTPCookieProcessor)])
        try:
            r = op.open(APP + path, timeout=15)
            return r.getcode(), ""
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("Location", "")


def panel_state(base):
    return json.loads(urllib.request.urlopen(base + "/__lines", timeout=10).read())


def solve_captcha(c, data_dir, gid, panel):
    """كما يفعل المشغّل: صورة الكود من الأداة، والكود من اللوحة الوهمية نفسها."""
    c.op.open(APP + "/admin/api/web/captcha?gate=" + gid, timeout=15).read()
    jar = http.cookiejar.MozillaCookieJar(os.path.join(data_dir, "sessions", "gate_" + gid + ".cookies"))
    jar.load(ignore_discard=True, ignore_expires=True)
    pop = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    r = pop.open(panel + "/captcha.php?a=1", timeout=10)
    r.read()
    return c.jreq("/admin/api/web/login", {"gate": gid, "captcha": r.headers.get("X-Captcha-Code", "")})


def split_file(data_dir, acct_id):
    return os.path.join(data_dir, "split", acct_id + ".json")


def set_due_past(data_dir, acct_id, rid, days=1):
    """يعيد موعد الجزء إلى الماضي — كأن ستة أشهر مضت — لتلتقطه الدورة التالية.

    الخادم يحفظ الملف نفسه في دورته (كل ثانية هنا)، وكتابتُنا من خارجه تضيع إن وقعت بين
    قراءته وحفظه: يبقى الخط «يجري» بموعده القديم فلا تلتقطه الدورة أبدًا. فبعد الكتابة
    ننتظر دورةً ونتحقّق أن الموعد بقي — أو أن الدورة التقطته فتجاوزه الخط — ونعيدها إن ضاع."""
    p = split_file(data_dir, acct_id)
    past = (datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3)))
            - datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
    for _ in range(20):
        try:
            with open(p, encoding="utf-8") as f:
                db = json.load(f)
            rec = db["lines"][rid]
            if rec.get("state") != "active" or (rec.get("slice") or {}).get("due") == past:
                return True
            rec["slice"]["due"] = past
            tmp = p + ".t"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(db, f, ensure_ascii=False)
            os.replace(tmp, p)
        except (OSError, ValueError, KeyError, TypeError):
            pass
        time.sleep(1.5)                          # أطول من دورة: ما ضاع يظهر قبل التحقّق التالي
    return False


def wait_line(c, rid, pred, secs=25):
    rec = {}
    for _ in range(int(secs / 0.5)):
        _, d = c.jreq("/admin/api/split/state")
        rec = next((l for l in d.get("lines", []) if l["id"] == rid), {})
        if pred(rec):
            return rec
        time.sleep(0.5)
    return rec


def main():
    smtp = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _SMTP)
    threading.Thread(target=smtp.serve_forever, daemon=True).start()
    csrv, CASPER, _t = mock_casper.start(4)
    data_dir = tempfile.mkdtemp(prefix="splitweb_")
    procs = [
        subprocess.Popen([sys.executable, os.path.join(HERE, "mock_panel.py"), str(P_MARAH), "demo", "secret"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
        subprocess.Popen([sys.executable, os.path.join(HERE, "mock_panel.py"), str(P_LOCK), "demo", "secret", "lockuser"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
        subprocess.Popen([sys.executable, os.path.join(HERE, "mock_falcon.py"), str(P_FALCON), "fk"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
        subprocess.Popen([sys.executable, os.path.join(HERE, "mock_falcon.py"), str(P_NOPATCH), "fk", "nopatch"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
    ]
    env = dict(os.environ, XM_DATA=data_dir, XM_BIND="127.0.0.1", XM_PORT=str(P_APP), SPLIT_TICK_SECONDS="1")
    procs.append(subprocess.Popen([sys.executable, os.path.join(ROOT, "xm_lines.py"), "web"], env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    try:
        for u in (MARAH + "/token.php", LOCK + "/token.php", APP + "/admin/login"):
            up(u)
        time.sleep(0.5)
        adm = Client()
        print("== 1. المدير: عميلٌ فُتحت له الميزة وآخر لم تُفتح ==")
        adm.jreq("/admin/api/setup", {"password": "admin123"})
        code, d = adm.jreq("/admin/api/renew/config", {"renew": {"alert": {
            "host": "127.0.0.1", "port": smtp.server_address[1], "to": "owner@example.com",
            "from": "alerts@example.com", "tls": False}}})
        check("alert email configured (the renew SMTP settings)", code == 200 and d.get("ok"), d.get("error", ""))
        gates_a = [
            {"name": "بوابة مرح", "mode": "web", "host": "http://mrha.ink", "panel_base": MARAH,
             "panel_user": "demo", "panel_pass": "secret", "guide_url": "https://guide.ssouq.com/#activate/smart"},
            {"name": "بوابة كاسبر", "mode": "web", "web_flavor": "casper", "host": "http://kasper.tv",
             "panel_base": CASPER, "panel_user": "u", "panel_pass": "p", "digits": "10"},
            {"name": "بوابة فالكون", "mode": "falcon", "api_url": FALCON, "api_key": "fk", "host": "http://falcon.host"},
            {"name": "مرح مقفلة", "mode": "web", "host": "http://lock.host", "panel_base": LOCK,
             "panel_user": "demo", "panel_pass": "secret"},
            {"name": "فالكون بلا تعديل", "mode": "falcon", "api_url": NOPATCH, "api_key": "fk", "host": "http://f2.host"},
            {"name": "بوابة API", "mode": "api", "host": "http://api.host", "api_url": "http://127.0.0.1:9/x",
             "api_key": "k"},
        ]
        code, d = adm.jreq("/admin/api/accounts", {"name": "عميل التجزئة", "user": "split", "password": "pw_split",
                                                   "split": True, "gates": gates_a})
        check("client A saved with the switch on", code == 200 and d.get("ok"), d.get("error", ""))
        acc_a = next(a for a in d["accounts"] if a["user"] == "split")
        check("switch stored on the account", acc_a.get("split") is True)
        gid = {g["name"]: g["id"] for g in acc_a["gates"]}
        code, d = adm.jreq("/admin/api/accounts", {"name": "عميل عادي", "user": "plain", "password": "pw_plain",
                                                   "gates": [dict(gates_a[0])]})
        acc_b = next(a for a in d["accounts"] if a["user"] == "plain")
        check("client B saved without it (off by default)", not acc_b.get("split"))
        # حفظ الحساب مجددًا بلا المفتاح (صفحة حسابات قديمة) لا يُطفئ الميزة
        a2 = {k: v for k, v in acc_a.items() if k not in ("split", "has_password")}
        a2["gates"] = [{**g, "panel_pass": "", "api_key": ""} for g in acc_a["gates"]]
        code, d = adm.jreq("/admin/api/accounts", a2)
        check("re-saving without the key keeps the switch", code == 200 and
              next(a for a in d["accounts"] if a["user"] == "split").get("split") is True, d.get("error", ""))

        print("\n== 2. العميل الذي لم تُفتح له: لا شيء يتغيّر ==")
        b = Client()
        b.jreq("/admin/api/login", {"user": "plain", "password": "pw_plain"})
        _, me = b.jreq("/admin/api/me")
        check("me: split off", me.get("split") is False and me.get("split_slices") == [])
        code, d = b.jreq("/admin/api/split/notes")
        check("notes: disabled, nothing unread", d.get("enabled") is False and d.get("unread") == 0)
        code, d = b.jreq("/admin/api/split/cfg", {"auto": False})
        check("split actions refused (403)", code == 403, str(code))
        st, loc = b.status("/admin/remaining")
        check("remaining page sends him back to his page", st == 302 and loc == "/admin", "%s %s" % (st, loc))
        gb = acc_b["gates"][0]["id"]
        solve_captcha(b, data_dir, gb, MARAH)
        _, d = b.jreq("/admin/api/packages?gate=" + gb)
        check("his packages carry no split flag", d.get("packages") and not any(p.get("split") for p in d["packages"]))
        code, d = b.jreq("/admin/api/create", {"gate": gb, "package_id": "15", "count": 1, "slice_months": 6})
        check("slice creation refused before anything is created", code == 400 and "غير مفعّلة" in d.get("error", ""),
              d.get("error", ""))
        before = len(panel_state(MARAH)["lines"])
        code, d = b.jreq("/admin/api/create", {"gate": gb, "package_id": "15", "count": 1, "slice_months": 12,
                                               "replaces": "555000999888"})
        _, s = b.jreq("/admin/api/search?gate=%s&q=555000999888" % gb)
        check("a replacement with a duration is refused too — nothing created, nothing linked",
              code == 400 and "غير مفعّلة" in d.get("error", "") and s.get("links") == []
              and len(panel_state(MARAH)["lines"]) == before, d.get("error", ""))

        print("\n== 3. العميل المفتوحة له: إنشاء أجزاء من باقة ١٥ شهرًا ==")
        a = Client()
        a.jreq("/admin/api/login", {"user": "split", "password": "pw_split"})
        _, me = a.jreq("/admin/api/me")
        check("me: split on with 12/6/3/1, and «مدة أخرى» up to 14",
              me.get("split") is True and me.get("split_slices") == [12, 6, 3, 1] and me.get("split_max") == 14)
        st, _ = a.status("/admin/remaining")
        check("remaining page opens for him", st == 200, str(st))
        g_m = gid["بوابة مرح"]
        code, d = solve_captcha(a, data_dir, g_m, MARAH)
        check("Marah gate logged in", d.get("ok") is True, d.get("error", ""))
        _, d = a.jreq("/admin/api/packages?gate=" + g_m)
        flags = {str(p["id"]): bool(p.get("split")) for p in d.get("packages", [])}
        check("only the 15-month package is splittable", flags.get("15") is True and not flags.get("12")
              and not flags.get("x2:15"), json.dumps(flags))
        code, d = a.jreq("/admin/api/create", {"gate": g_m, "package_id": "12", "count": 1, "slice_months": 6})
        check("a 12-month package is refused", code == 400 and "١٥" in d.get("error", ""), d.get("error", ""))
        before = len(panel_state(MARAH)["lines"])
        code, d = a.jreq("/admin/api/create", {"gate": g_m, "package_id": "15", "count": 1, "slice_months": 15})
        check("a slice as long as the whole line is refused", code == 400)
        check("…and nothing was created on the panel", len(panel_state(MARAH)["lines"]) == before)
        code, d = a.jreq("/admin/api/create", {"gate": g_m, "package_id": "15", "count": 1, "slice_months": 6,
                                               "password": "999988887777"})
        sp = (d.get("split") or [{}])[0]
        m_user = (d.get("lines") or [{}])[0].get("username", "")
        check("Marah: 6-month slice created and tracked", code == 200 and sp.get("id") and sp.get("months") == 6,
              json.dumps(sp, ensure_ascii=False))
        check("…9 months remain after it", sp.get("remaining_after") == 9, str(sp.get("remaining_after")))
        due_d = datetime.date.fromisoformat(sp.get("due", "2000-01-01")[:10])
        check("…reminder email date = 3 days before the change",
              sp.get("remind") == (due_d - datetime.timedelta(days=3)).isoformat(), str(sp.get("remind")))
        check("…says the reminder goes to the admin's email (address hidden from the client)",
              d.get("split_mail") == {"configured": True, "source": "admin", "to": ""}, json.dumps(d.get("split_mail")))
        _, nd = a.jreq("/admin/api/split/notes")
        check("…the sale is logged in the notifications, without raising the badge",
              any(n["kind"] == "sold" and n["read"] for n in nd.get("notes", [])) and nd.get("unread") == 0,
              json.dumps(nd, ensure_ascii=False)[:120])
        check("…the history groups it apart", "جزء 6 أشهر" in d["lines"][0].get("package", ""),
              d["lines"][0].get("package", ""))
        m_id = sp.get("id")
        # كاسبر: جزء ٣ أشهر
        g_c = gid["بوابة كاسبر"]
        _, d = a.jreq("/admin/api/packages?gate=" + g_c)
        p15 = next((p for p in d.get("packages", []) if p.get("split")), {})
        check("Casper: the 15-month package is splittable", p15.get("id") == "726", json.dumps(d.get("packages", []))[:120])
        code, d = a.jreq("/admin/api/create", {"gate": g_c, "package_id": "726", "count": 1, "slice_months": 3})
        spc = (d.get("split") or [{}])[0]
        check("Casper: 3-month slice created (12 remain after)", code == 200 and spc.get("remaining_after") == 12,
              json.dumps(d, ensure_ascii=False)[:160])
        c_id, c_user = spc.get("id"), spc.get("username")
        # فالكون: جزء شهر
        g_f = gid["بوابة فالكون"]
        _, d = a.jreq("/admin/api/packages?gate=" + g_f)
        check("Falcon: 'سنة + 3 أشهر' is splittable", any(p.get("split") and p["id"] == 190 for p in d.get("packages", [])))
        code, d = a.jreq("/admin/api/create", {"gate": g_f, "package_id": "190", "count": 1, "slice_months": 1})
        spf = (d.get("split") or [{}])[0]
        check("Falcon: 1-month slice created (14 remain after)", code == 200 and spf.get("remaining_after") == 14,
              json.dumps(d, ensure_ascii=False)[:160])
        f_id, f_user = spf.get("id"), spf.get("username")

        print("\n== 3b. بديلٌ عن رقمٍ لم يُعثر عليه: مدة البديل ١٢ شهرًا من باقة ١٥ ==")
        old_no = "555000111222"
        _, d = a.jreq("/admin/api/search?gate=%s&q=%s" % (g_m, old_no))
        check("the old number is not on the panel, nothing linked yet", d.get("results") == [] and d.get("links") == [],
              json.dumps(d, ensure_ascii=False)[:120])
        code, d = a.jreq("/admin/api/create", {"gate": g_m, "package_id": "15", "count": 1, "replaces": old_no,
                                               "slice_months": 12})
        spr = (d.get("split") or [{}])[0]
        r_line = (d.get("lines") or [{}])[0]
        r_user = r_line.get("username", "")
        check("replacement created on the 15-month package, given 12 months and tracked",
              code == 200 and r_user and spr.get("id") and spr.get("months") == 12 and not d.get("error"),
              json.dumps(d, ensure_ascii=False)[:200])
        check("…3 months remain on the line after it", spr.get("remaining_after") == 3, str(spr.get("remaining_after")))
        today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3))).date()
        due_r = datetime.date.fromisoformat(spr.get("due", "2000-01-01")[:10])
        check("…its username changes a year from now, not after 15 months", 364 <= (due_r - today).days <= 366,
              spr.get("due", ""))
        check("…the history labels it with the duration given", "جزء 12 شهرًا" in r_line.get("package", ""),
              r_line.get("package", ""))
        check("…the link to the old number carries that label",
              [(x["old"], x["new"], x["package"]) for x in d.get("linked", [])] == [(old_no, r_user, r_line.get("package"))],
              json.dumps(d.get("linked"), ensure_ascii=False))
        _, d = a.jreq("/admin/api/search?gate=%s&q=%s" % (g_m, old_no))
        lk = (d.get("links") or [{}])[0]
        check("searching the old number later names its replacement and the 12 months",
              lk.get("direction") == "replaced_by" and lk.get("new") == r_user and "جزء 12 شهرًا" in lk.get("package", ""),
              json.dumps(d.get("links"), ensure_ascii=False))
        r_id = spr.get("id")

        print("\n== 3b2. البحث يجد خط مرح رغم علامة «لا جدول» (من الملف فورًا، ومن اللوحة بعد حذفه) ==")
        # بحثٌ سابقٌ على جلسة مرح المنتهية كان يُحفظ «لوحة بلا جدول» فيرجع كل بحثٍ بعده فارغًا،
        # في كل البوابات وفي مرح وحدها. الحال كما تُركت عند العميل:
        mpath = os.path.join(data_dir, "sessions", "gate_" + g_m + ".meta.json")
        with open(mpath, encoding="utf-8") as f:
            meta = json.load(f)
        with open(mpath, "w", encoding="utf-8") as f:
            json.dump({**meta, "no_table_search": True}, f)
        # (أ) اللقطة المحفوظة تتجاوز العلامة أصلًا: خطٌّ مُصدَّر يُوجد فورًا بلا لمس اللوحة،
        #     فلا تبلغه العلامة. والعلامة تبقى كما هي (لم نحتج اللوحة لنمحوها).
        _, d = a.jreq("/admin/api/search?gate=%s&q=%s" % (g_m, m_user))
        check("an exported line is found from the file, stale flag notwithstanding",
              d.get("source") == "file" and [r["username"] for r in d.get("results", [])] == [m_user], str(d)[:140])
        with open(mpath, encoding="utf-8") as f:
            check("…file hit leaves the panel flag untouched", json.load(f).get("no_table_search") is True)
        # (ب) خطٌّ ليس في الملف يصل اللوحةَ رغم العلامة فيُوجد، وتُمحى العلامة (الإصلاح الأصلي).
        #     نحذف لقطة البوابة لنفرض مسار اللوحة — كأنّ الخط لم يُصدَّر بعد.
        for fp in glob.glob(os.path.join(data_dir, "users_export", "*%s*" % g_m)):
            os.remove(fp)
        _, d = a.jreq("/admin/api/search?gate=all&q=%s" % m_user)
        hits = {x["id"]: [r["username"] for r in x["results"]] for x in d.get("gates", []) if x["results"]}
        check("all gates: Marah's line is found under Marah (via the panel)", hits.get(g_m) == [m_user], json.dumps(d, ensure_ascii=False)[:200])
        with open(mpath, encoding="utf-8") as f:
            check("…and the stale flag is cleared", not json.load(f).get("no_table_search"))
        _, d = a.jreq("/admin/api/search?gate=%s&q=%s" % (g_m, m_user))
        check("Marah alone finds it too", [r["username"] for r in d.get("results", [])] == [m_user], str(d)[:120])

        print("\n== 3c. «مدة أخرى»: أي عددٍ من الأشهر — ١٠ مثلًا ==")
        old_f = "555000333444"
        code, d = a.jreq("/admin/api/create", {"gate": g_f, "package_id": "190", "count": 1, "replaces": old_f,
                                               "slice_months": "١٠"})
        sp10 = (d.get("split") or [{}])[0]
        l10 = (d.get("lines") or [{}])[0]
        check("a replacement given 10 months (typed in Arabic digits) is tracked, 5 left after it",
              code == 200 and sp10.get("months") == 10 and sp10.get("remaining_after") == 5
              and "جزء 10 أشهر" in l10.get("package", ""), json.dumps(d, ensure_ascii=False)[:200])
        check("…and its link to the old number names the 10 months",
              [(x["old"], x["package"]) for x in d.get("linked", [])] == [(old_f, l10.get("package"))],
              json.dumps(d.get("linked"), ensure_ascii=False))
        t10_id = sp10.get("id")
        before = len(panel_state(MARAH)["lines"])
        for bad in (15, "abc", -2):
            code, d = a.jreq("/admin/api/create", {"gate": g_m, "package_id": "15", "count": 1, "slice_months": bad})
            check("%r months refused, saying the range" % (bad,), code == 400 and "من شهر إلى 14 شهرًا" in d.get("error", ""),
                  d.get("error", ""))
        check("…and nothing was created for any of them", len(panel_state(MARAH)["lines"]) == before)

        code, d = a.jreq("/admin/api/split/state")
        lines = {l["id"]: l for l in d.get("lines", [])}
        check("state lists the running slices, the replacements among them",
              all(lines.get(x, {}).get("state") == "active" for x in (m_id, c_id, f_id, r_id, t10_id))
              and lines.get(r_id, {}).get("slice", {}).get("months") == 12
              and lines.get(t10_id, {}).get("slice", {}).get("months") == 10, str(list(lines)))
        check("state: 12 is a sale type, 6 stays the preselected one, «مدة أخرى» up to 14",
              d.get("slices") == [12, 6, 3, 1] and d.get("default_slice") == 6 and d.get("max_slice") == 14,
              "%s %s %s" % (d.get("slices"), d.get("default_slice"), d.get("max_slice")))
        check("line text ready to copy (host · user · pass · guide)",
              lines.get(m_id, {}).get("line", "").startswith("Host http://mrha.ink User %s Pass 999988887777" % m_user),
              lines.get(m_id, {}).get("line", ""))

        print("\n== 4. «غيّر الآن» على مرح: الاسم وحده يتغيّر ==")
        pl0 = next(l for l in panel_state(MARAH)["lines"] if l["username"] == m_user)
        code, d = a.jreq("/admin/api/split/rotate", {"id": m_id})
        new_m = (d.get("line") or {}).get("username", "")
        check("rotated", code == 200 and d.get("ok") and new_m and new_m != m_user, json.dumps(d, ensure_ascii=False)[:160])
        pl = next((l for l in panel_state(MARAH)["lines"] if l["id"] == pl0["id"]), {})
        check("panel: new username, same length", pl.get("username") == new_m and len(new_m) == len(m_user), new_m)
        check("panel: password unchanged", pl.get("password") == "999988887777")
        check("panel: channels (bouquets) kept", pl.get("bouquets") == pl0["bouquets"] and pl0["bouquets"] not in ("", "[]"),
              pl.get("bouquets", ""))
        check("panel: expiry unchanged, no paid extension", pl.get("end") == pl0["end"]
              and not panel_state(MARAH)["extends"])
        check("line is now available with 15 months left (sliced early)",
              d["line"]["state"] == "available" and d["line"]["remaining_months"] == 15, str(d["line"].get("remaining_months")))
        code, d = a.jreq("/admin/api/split/sell", {"id": m_id, "months": 6, "customer": "أبو محمد"})
        check("sold again: slice #2 running", code == 200 and d["line"]["state"] == "active"
              and d["line"]["slice"]["n"] == 2 and d["line"]["slice"]["customer"] == "أبو محمد", d.get("error", ""))
        code, d = a.jreq("/admin/api/split/sell", {"id": m_id, "months": 6})
        check("a running line cannot be sold twice", code == 400)

        print("\n== 5. الدورة: انتهى الجزء ← يتغيّر الاسم تلقائيًا (كاسبر وفالكون) ==")
        check("move Casper due to the past", set_due_past(data_dir, acc_a["id"], c_id))
        check("move Falcon due to the past", set_due_past(data_dir, acc_a["id"], f_id))
        rc = wait_line(adm, c_id, lambda r: r.get("state") == "available")
        rf = wait_line(adm, f_id, lambda r: r.get("state") == "available")
        cu = next((u for u in mock_casper._Handler.users if u["username"] == rc.get("username")), {})
        check("Casper: renamed by the scheduler", rc.get("state") == "available" and cu, json.dumps(rc, ensure_ascii=False)[:160])
        check("Casper: password unchanged on the panel", cu.get("password") == rc.get("password") and
              rc.get("password") == rc.get("history", [{}])[0].get("password"))
        check("Casper: old name gone from the panel",
              not any(u["username"] == c_user for u in mock_casper._Handler.users))
        code, d = a.jreq("/admin/api/split/undo", {"id": c_id})
        cu2 = next((u for u in mock_casper._Handler.users if u["id"] == cu.get("id")), {})
        check("undo: the old name is back on the panel, password kept",
              d.get("ok") is True and cu2.get("username") == c_user and cu2.get("password") == cu.get("password"),
              json.dumps(d, ensure_ascii=False)[:160])
        check("undo: its slice is back — date passed, so it waits for the operator",
              d.get("line", {}).get("state") == "due" and d["line"]["username"] == c_user
              and not d["line"].get("history"))
        code, d = a.jreq("/admin/api/split/undo", {"id": c_id})
        check("undo twice refused (nothing left to undo)", code == 400, str(code))
        fl = json.loads(urllib.request.urlopen(urllib.request.Request(
            FALCON + "/lines?per=50&q=" + rf.get("username", "-"), headers={"Authorization": "Bearer fk"})).read())
        check("Falcon: renamed by the scheduler, password kept",
              rf.get("state") == "available" and fl["lines"] and fl["lines"][0]["password"] == rf.get("password"),
              json.dumps(rf, ensure_ascii=False)[:120])
        check("Falcon: old name recorded in the line history", rf.get("history", [{}])[0].get("username") == f_user)

        print("\n== 6. لوحةٌ تقفل الاسم، وفالكون بلا تعديل: يدويّ بلا أي إرسال ==")
        g_l = gid["مرح مقفلة"]
        solve_captcha(a, data_dir, g_l, LOCK)
        code, d = a.jreq("/admin/api/create", {"gate": g_l, "package_id": "15", "count": 1, "slice_months": 6})
        l_id = ((d.get("split") or [{}])[0]).get("id")
        check("locked gate: slice created", code == 200 and l_id, json.dumps(d, ensure_ascii=False)[:120])
        code, d = a.jreq("/admin/api/split/rotate", {"id": l_id})
        check("early 'change now' refused by the panel → slice keeps running",
              d.get("ok") is False and d["line"]["state"] == "active" and "لا تسمح" in d.get("error", ""), d.get("error", ""))
        check("…and nothing was submitted to the panel", not panel_state(LOCK)["edits"])
        set_due_past(data_dir, acc_a["id"], l_id)
        rl = wait_line(adm, l_id, lambda r: r.get("state") == "failed")
        check("at its due time it becomes 'needs attention'", rl.get("state") == "failed", rl.get("last_error", ""))
        code, d = a.jreq("/admin/api/split/confirm", {"id": l_id, "username": "123123123123"})
        check("operator changed it by hand and confirmed", code == 200 and d["line"]["state"] == "available"
              and d["line"]["username"] == "123123123123", d.get("error", ""))
        check("an available line offers «مدة أخرى» up to what it has left", d["line"].get("max_sell", 0) >= 14,
              str(d["line"].get("max_sell")))
        code, d = a.jreq("/admin/api/split/sell", {"id": l_id, "months": 16})
        check("selling more months than the line has is refused", code == 400 and "أقصر" in d.get("error", ""),
              d.get("error", ""))
        code, d = a.jreq("/admin/api/split/sell", {"id": l_id, "months": "10", "customer": "عميل العشرة"})
        check("sold with «مدة أخرى»: 10 months, 5 left after", code == 200 and d["line"]["state"] == "active"
              and d["line"]["slice"]["months"] == 10 and d["line"].get("remaining_after") == 5, d.get("error", ""))
        g_n = gid["فالكون بلا تعديل"]
        start = (datetime.date.today() - datetime.timedelta(days=200)).isoformat()
        code, d = a.jreq("/admin/api/split/register", {"gate": g_n, "username": "user002", "months": 6, "start": start})
        n_line = d.get("line") or {}
        check("existing line registered; password read from the panel", code == 200 and
              n_line.get("password") == "pass002", json.dumps(d, ensure_ascii=False)[:160])
        check("its slice ended before registration → waits for the operator", n_line.get("state") == "due")
        code, d = a.jreq("/admin/api/split/rotate", {"id": n_line.get("id")})
        check("Falcon without PATCH → needs attention", d.get("ok") is False and d["line"]["state"] == "failed",
              d.get("error", ""))
        exp = (datetime.date.today() + datetime.timedelta(days=450)).isoformat()
        code, d = a.jreq("/admin/api/split/register", {"gate": g_n, "username": "user003", "months": "١١", "expiry": exp})
        check("an existing line registered with «مدة أخرى» (11 months, Arabic digits)", code == 200 and
              (d.get("line") or {}).get("slice", {}).get("months") == 11 and d["line"]["state"] == "active",
              json.dumps(d, ensure_ascii=False)[:160])
        code, d = a.jreq("/admin/api/split/register", {"gate": g_n, "username": "user004", "months": 15})
        check("…but not 15 months — that is the whole line", code == 400 and "14" in d.get("error", ""), d.get("error", ""))
        code, d = a.jreq("/admin/api/split/register", {"gate": gid["بوابة API"], "username": "x", "months": 6})
        check("Reseller-API gates are outside the system", code == 400)
        code, d = a.jreq("/admin/api/split/register", {"gate": g_m, "username": "nobody000000", "months": 6})
        check("unknown user without a password refused", code == 400, d.get("error", ""))

        print("\n== 7. الإشعارات والبريد ==")
        code, d = a.jreq("/admin/api/split/notes")
        kinds = [n["kind"] for n in d.get("notes", [])]
        check("bell: unread notifications", d.get("enabled") and d.get("unread", 0) >= 3, "unread=%s" % d.get("unread"))
        check("…rotated + failed kinds present", "rotated" in kinds and "failed" in kinds, ",".join(kinds))
        for _ in range(30):
            if any("تغيّرت" in s for s, _b in mails()):
                break
            time.sleep(0.5)
        ms = mails()
        check("a digest email arrived", ms and any(s.startswith("حسابات متبقية") for s, _b in ms),
              " | ".join(s for s, _b in ms)[:160])
        body = "\n".join(b_ for _s, b_ in ms)
        check("digest names the renamed line and what remains", rc.get("username", "-") in body and "متبقي" in body)
        check("no password in any email", "999988887777" not in body and rc.get("password", "-") not in body)
        code, d = a.jreq("/admin/api/split/test-email", {})
        check("test email sent", d.get("ok") is True, d.get("error", ""))
        a.jreq("/admin/api/renew/config", {"renew": {"alert": {"host": "127.0.0.1", "port": 9, "to": "c@example.com",
                                                                "tls": False}}})
        code, d = a.jreq("/admin/api/split/test-email", {})
        check("broken mail server: the error comes back with a plain explanation",
              d.get("ok") is False and d.get("error") and "المنفذ" in d.get("hint", ""), json.dumps(d, ensure_ascii=False))
        a.jreq("/admin/api/renew/config", {"renew": {"alert": {"host": "", "to": ""}}})    # يعود لبريد المدير
        sp_file = split_file(data_dir, acc_a["id"])
        with open(sp_file, encoding="utf-8") as f:
            sdb = json.load(f)
        sdb["mail"]["last_error"] = "بريد التذكير غير مضبوط"         # من قبل أن يُضبط البريد
        with open(sp_file, "w", encoding="utf-8") as f:
            json.dump(sdb, f, ensure_ascii=False)
        _, stx = a.jreq("/admin/api/split/state")
        check("a stale 'mail not configured' error is hidden once mail is configured",
              stx["accounts"][0]["mail"]["last_error"] == "", stx["accounts"][0]["mail"]["last_error"])
        sdb["mail"]["last_error"] = "SMTP boom"
        with open(sp_file, "w", encoding="utf-8") as f:
            json.dump(sdb, f, ensure_ascii=False)
        a.jreq("/admin/api/split/test-email", {})
        _, stx = a.jreq("/admin/api/split/state")
        check("a successful test email clears the old mail error", stx["accounts"][0]["mail"]["last_error"] == "",
              stx["accounts"][0]["mail"]["last_error"])
        code, d = a.jreq("/admin/api/split/read", {})
        _, d = a.jreq("/admin/api/split/notes")
        check("mark all read → badge clears", d.get("unread") == 0, str(d.get("unread")))
        code, d = a.jreq("/admin/api/split/cfg", {"auto": False, "remind_days": 5})
        check("settings saved (manual mode, 5-day reminder)", code == 200 and d["cfg"] == {"auto": False, "remind_days": 5})

        print("\n== 7b. تجربة على خطٍّ تجريبي (قبل الاعتماد على اللوحة) ==")
        code, d = a.jreq("/admin/api/create", {"gate": g_m, "package_id": "1", "count": 1, "password": "111000111000"})
        trial = (d.get("lines") or [{}])[0].get("username", "")
        check("a trial line exists on the panel (plain create, not tracked)", code == 200 and trial and not d.get("split"))
        code, d = a.jreq("/admin/api/split/test-rename", {"gate": g_m, "username": trial})
        pl = next((l for l in panel_state(MARAH)["lines"] if l["username"] == d.get("new")), {})
        check("test renamed it on the panel", d.get("ok") is True and pl and d.get("old") == trial,
              json.dumps(d, ensure_ascii=False)[:160])
        check("…password unchanged (on the panel and reported)", pl.get("password") == "111000111000"
              and d.get("same_password") is True)
        _, st8 = a.jreq("/admin/api/split/state")
        gm = next(g for g in st8["accounts"][0]["gates"] if g["id"] == g_m)
        check("gate marked 'tested OK' in settings", gm["edit"].get("edit") == "ok")
        check("a test notification recorded (no email)", any(n["kind"] == "test" and n.get("mail") == "skip"
                                                            for n in st8["notes"]))
        check("the trial line is not tracked", not any(l["username"] == d.get("new") for l in st8["lines"]))
        _, cur = a.jreq("/admin/api/split/state")
        tracked = next(l for l in cur["lines"] if l["id"] == m_id)["username"]
        code, d = a.jreq("/admin/api/split/test-rename", {"gate": g_m, "username": tracked})
        check("refuses a customer's tracked line", code == 400 and "متابَع" in d.get("error", ""), d.get("error", ""))
        code, d = a.jreq("/admin/api/split/test-rename", {"gate": g_m, "username": "000000000001"})
        check("unknown username refused", code == 400)
        code, d = a.jreq("/admin/api/create", {"gate": g_l, "package_id": "1", "count": 1})
        ltrial = (d.get("lines") or [{}])[0].get("username", "")
        edits0 = len(panel_state(LOCK)["edits"])
        code, d = a.jreq("/admin/api/split/test-rename", {"gate": g_l, "username": ltrial})
        check("locked panel: test reports 'not allowed', nothing sent",
              d.get("ok") is False and d.get("kind") == "unsupported" and len(panel_state(LOCK)["edits"]) == edits0,
              d.get("error", ""))
        code, d = b.jreq("/admin/api/split/test-rename", {"gate": gb, "username": trial})
        check("client without the feature cannot run tests", code == 403)

        print("\n== 8. العزل: لا يرى عميلٌ خطوط غيره ==")
        code, d = b.jreq("/admin/api/split/rotate", {"id": m_id})
        check("client B cannot touch client A's line", code == 403, str(code))
        adm.jreq("/admin/api/accounts", {"name": "عميل ثالث", "user": "third", "password": "pw_third", "split": True,
                                         "gates": [dict(gates_a[2])]})
        c3 = Client()
        c3.jreq("/admin/api/login", {"user": "third", "password": "pw_third"})
        code, d = c3.jreq("/admin/api/split/sell", {"id": m_id, "months": 1})
        check("another split client gets 404 for it", code == 404, str(code))
        _, d = c3.jreq("/admin/api/split/state")
        check("…and sees none of its lines", d.get("lines") == [])
        _, d = adm.jreq("/admin/api/split/state")
        names = [x["name"] for x in d.get("accounts", [])]
        check("admin sees every client with the feature", "عميل التجزئة" in names and "عميل ثالث" in names
              and "عميل عادي" not in names, ",".join(names))
        check("admin sees the alert address", any(x["mail"].get("to") == "owner@example.com" for x in d["accounts"]))
        _, d = a.jreq("/admin/api/split/state")
        mail = d["accounts"][0]["mail"]
        check("client sees 'admin email' without its address",
              {k: mail.get(k) for k in ("configured", "source", "to", "last_error")} ==
              {"configured": True, "source": "admin", "to": "", "last_error": ""}, json.dumps(mail))
    finally:
        for p in procs:
            p.kill()
        csrv.shutdown()
        smtp.shutdown()
    print("\nResult: %d passed, %d failed" % (_p, _f))
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

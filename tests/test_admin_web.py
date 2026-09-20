#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اختبار تكامل: خادم الأدمن (xm_lines.py) في "وضع الويب" مقابل اللوحة الوهمية.
يتحقق أن مسارات /admin تُنشئ الحساب، تطلب الكابتشا عند غياب OCR، تقبل الكود
اليدوي، ثم تقرأ الباقات وتُنشئ يوزرًا — كله عبر HTTP كما يفعل المتصفح.

تشغيل:  python tests/test_admin_web.py
"""
import os
import sys
import json
import time
import shutil
import tempfile
import subprocess
import http.cookiejar
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

PANEL_PORT = int(os.environ.get("PANEL_PORT", "9078"))
ADMIN_PORT = int(os.environ.get("ADMIN_PORT", "9079"))
PUSER, PPASS = "demo", "secret"      # بيانات دخول اللوحة الوهمية
PANEL = f"http://127.0.0.1:{PANEL_PORT}"
ADMIN = f"http://127.0.0.1:{ADMIN_PORT}"

_p = _f = 0


def check(label, cond, extra=""):
    global _p, _f
    if cond:
        _p += 1
        print(f"  \033[32mPASS\033[0m  {label}" + (f"  ({extra})" if extra else ""))
    else:
        _f += 1
        print(f"  \033[31mFAIL\033[0m  {label}" + (f"  ({extra})" if extra else ""))


def main():
    data_dir = tempfile.mkdtemp(prefix="adminweb_")
    env = dict(os.environ, XM_DATA=data_dir, XM_BIND="127.0.0.1", XM_PORT=str(ADMIN_PORT))
    panel = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_panel.py"), str(PANEL_PORT), PUSER, PPASS],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    admin = subprocess.Popen([sys.executable, os.path.join(ROOT, "xm_lines.py"), "web"],
                             env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def up(url):
        for _ in range(60):
            try:
                urllib.request.urlopen(url, timeout=0.3)
                return True
            except urllib.error.HTTPError:
                return True
            except Exception:
                time.sleep(0.1)
        return False

    try:
        up(PANEL + "/token.php")
        up(ADMIN + "/admin/login")
        print(f"panel :{PANEL_PORT}  admin :{ADMIN_PORT}\n")

        cj = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

        def jreq(path, obj=None):
            data = json.dumps(obj).encode() if obj is not None else None
            req = urllib.request.Request(ADMIN + path, data=data,
                                         headers={"Content-Type": "application/json"},
                                         method="POST" if obj is not None else "GET")
            try:
                r = op.open(req, timeout=15)
                return r.getcode(), json.loads(r.read() or b"{}")
            except urllib.error.HTTPError as e:
                try:
                    return e.code, json.loads(e.read() or b"{}")
                except Exception:
                    return e.code, {}

        print("== 1. Admin setup + add a person with a WEB gate ==")
        code, d = jreq("/admin/api/setup", {"password": "admin123"})
        check("admin setup ok", code == 200 and d.get("ok"))
        code, d = jreq("/admin/api/accounts", {
            "name": "MR7", "user": PUSER, "password": PPASS,
            "gates": [{"name": "بوابة كاسبر", "mode": "web", "host": "http://mrha.ink",
                       "panel_base": PANEL, "panel_user": PUSER, "panel_pass": PPASS,
                       "guide_url": "https://guide.ssouq.com/", "digits": "10"}],
        })
        check("account with gate added", code == 200 and d.get("ok"), d.get("error") or "ok")
        # طول اليوزر/الباسورد لكل بوابة: خارج 6–20 يُرفض، وكاسبر يُحفظ بـ 10.
        code, bad = jreq("/admin/api/accounts", {
            "name": "Bad", "user": "bad", "password": "badpass",
            "gates": [{"name": "x", "mode": "web", "host": "http://h", "panel_base": PANEL,
                       "panel_user": "u", "panel_pass": "p", "digits": "3"}],
        })
        check("digits outside 6–20 rejected", code != 200 or not bad.get("ok"), bad.get("error") or "accepted?!")
        acc = next((a for a in d.get("accounts", []) if a["user"] == PUSER), {})
        gate = (acc.get("gates") or [{}])[0]
        gid = gate.get("id", "")
        check("gate stored as web mode", gate.get("mode") == "web" and gate.get("name") == "بوابة كاسبر")
        check("gate keeps its 10-digit setting", gate.get("digits") == 10, str(gate.get("digits")))
        check("gate id keyed session (gate_<id>)", bool(gid))

        print("\n== 2. Log in as the person; the gate's packages ask for captcha (no OCR) ==")
        op.open(ADMIN + "/admin/logout")
        code, d = jreq("/admin/api/login", {"user": PUSER, "password": PPASS})
        check("account login ok", code == 200 and d.get("role") == "account")
        code, d = jreq("/admin/api/me")
        check("me lists the gate", any(g.get("id") == gid for g in d.get("gates", [])))
        check("me carries the gate digits", any(g.get("id") == gid and g.get("digits") == 10 for g in d.get("gates", [])))
        code, d = jreq("/admin/api/packages?gate=" + gid)
        check("packages requests captcha (OCR off)", d.get("need_captcha") is True,
              json.dumps(d, ensure_ascii=False)[:80])

        print("\n== 3. Fetch captcha, read it, submit the code ==")
        r = op.open(ADMIN + "/admin/api/web/captcha?gate=" + gid, timeout=15)
        img = r.read()
        check("captcha image returned", r.getcode() == 200 and len(img) > 0,
              "%s %dB" % (r.headers.get("Content-Type"), len(img)))
        # جلسة البوابة مفتاحها gate_<id>
        jar_path = os.path.join(data_dir, "sessions", "gate_" + gid + ".cookies")
        cjar = http.cookiejar.MozillaCookieJar(jar_path)
        cjar.load(ignore_discard=True, ignore_expires=True)
        pop = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cjar))
        cr = pop.open(PANEL + "/captcha.php?a=1", timeout=10)
        cr.read()
        real_code = cr.headers.get("X-Captcha-Code", "")
        check("read the panel captcha code", real_code != "", real_code)
        code, d = jreq("/admin/api/web/login", {"gate": gid, "captcha": real_code})
        check("manual captcha login accepted", code == 200 and d.get("ok") is True,
              d.get("error") or "ok")

        print("\n== 4. Packages load; a line is created in the new format ==")
        code, d = jreq("/admin/api/packages?gate=" + gid)
        pk = d.get("packages") if isinstance(d.get("packages"), list) else []
        check("packages loaded after login: 4 panel packages + 1 virtual (30 months = create + extend)", len(pk) == 5,
              "count=%s" % (len(pk) if isinstance(d.get("packages"), list) else "?"))
        virt = next((p for p in pk if p.get("id") == "x2:15"), {})
        check("virtual 30-month package derived from the 15-month one", virt.get("name") == "اشتراك 30 شهر (12 نقاط)"
              and virt.get("base_id") == "15" and virt.get("virtual") is True, json.dumps(virt, ensure_ascii=False)[:100])
        code, d = jreq("/admin/api/create", {"gate": gid, "package_id": "3",
                                             "username": "", "password": "", "count": 1})
        lines = d.get("lines", [])
        ln = lines[0]["line"] if lines else ""
        check("line created via gate web session", bool(lines) and " User " in ln and " Pass " in ln,
              (ln[:60] + "…") if ln else json.dumps(d, ensure_ascii=False)[:80])
        check("line carries the gate's Guide url", "Guide https://guide.ssouq.com/" in ln, ln[-40:])
        u, pw = (lines[0].get("username", ""), lines[0].get("password", "")) if lines else ("", "")
        check("username generated on our side: exactly 10 digits", u.isdigit() and len(u) == 10, u)
        check("password generated on our side: exactly 10 digits", pw.isdigit() and len(pw) == 10, pw)
        code, d = jreq("/admin/api/create", {"gate": gid, "package_id": "1", "username": "", "password": "", "count": 4})
        ls = d.get("lines", [])
        check("batch of 4 via API: 4 distinct 10-digit users", len(ls) == 4 and len({x["username"] for x in ls}) == 4
              and all(x["username"].isdigit() and len(x["username"]) == 10 for x in ls), json.dumps(d, ensure_ascii=False)[:100])

        print("\n== 4b. Virtual 30-month package: create with 15 months then extend once ==")
        code, d = jreq("/admin/api/create", {"gate": gid, "package_id": "x2:15", "username": "", "password": "", "count": 2})
        ls = d.get("lines", [])
        check("2 users created + extended", len(ls) == 2 and not d.get("error"), json.dumps(d, ensure_ascii=False)[:120])
        check("each line reports the extension (end moved 15 months)",
              all(x.get("extended", {}).get("times") == 1 and x["extended"].get("from") == "2026-12-31"
                  and x["extended"].get("to") == "2028-03-31" for x in ls), json.dumps([x.get("extended") for x in ls], ensure_ascii=False))
        check("line labelled with the virtual package name", all(x.get("package") == "اشتراك 30 شهر (12 نقاط)" for x in ls))
        code, d = jreq("/admin/api/create", {"gate": gid, "package_id": "x2:999", "username": "", "password": "", "count": 1})
        check("unknown virtual base rejected", code == 400 and "غير موجودة" in d.get("error", ""), d.get("error"))

        print("\n== 4c. Gate status lists today's subscriptions from the panel table ==")
        code, d = jreq("/admin/api/gate-status?gate=" + gid)
        tl = d.get("today_lines") or []
        check("created_today counts every line made today (1 + 4 + 2)", d.get("created_today") == 7, str(d.get("created_today")))
        check("today_lines carry username/password/status/exp", len(tl) == 7 and all(x.get("username") and x.get("password") and x.get("exp") for x in tl),
              json.dumps(tl[:1], ensure_ascii=False)[:100])

        print("\n== 5. Self-service: person adds their own gate; data encrypted at rest ==")
        # log back in as admin (password set at setup) and create a LOGIN-ONLY person
        op.open(ADMIN + "/admin/logout")
        jreq("/admin/api/login", {"user": "admin", "password": "admin123"})
        code, d = jreq("/admin/api/accounts", {"name": "Ok", "user": "Ok", "password": "998661", "gates": []})
        okacc = next((a for a in d.get("accounts", []) if a.get("user") == "Ok"), None)
        check("login-only person created (0 gates)", okacc is not None and len(okacc.get("gates", [])) == 0,
              (d.get("error") or "ok"))

        # log in as that person, add a gate via self-service
        op.open(ADMIN + "/admin/logout")
        jreq("/admin/api/login", {"user": "Ok", "password": "998661"})
        code, d = jreq("/admin/api/mygates")
        check("mygates empty at first", d.get("gates") == [])
        code, d = jreq("/admin/api/mygates", {"name": "بوابة مرح", "mode": "web", "host": "http://mrha.ink",
                                              "panel_base": PANEL, "panel_user": PUSER, "panel_pass": "topsecretpass",
                                              "guide_url": "https://guide.ssouq.com/"})
        check("person added their own gate", d.get("ok") and len(d.get("gates", [])) == 1, d.get("error") or "ok")
        check("gate without digits defaults to 12", d.get("gates", [{}])[0].get("digits") == 12,
              str(d.get("gates", [{}])[0].get("digits")))

        # encryption at rest: the raw file must not contain the plaintext secret
        raw = open(os.path.join(data_dir, "accounts.json"), encoding="utf-8").read()
        check("panel password encrypted on disk", "topsecretpass" not in raw and "enc:1:" in raw)
        check("tool password encrypted on disk", "998661" not in raw)

        # delete it
        gid2 = d["gates"][0]["id"]
        code, d = jreq("/admin/api/mygates/delete", {"id": gid2})
        check("person deleted their gate", d.get("ok") and d.get("gates") == [])
    finally:
        for pr in (admin, panel):
            pr.terminate()
            try:
                pr.wait(timeout=5)
            except Exception:
                pr.kill()
        shutil.rmtree(data_dir, ignore_errors=True)

    print("\n----------------------------------------")
    print(f"Result: \033[32m{_p} passed\033[0m, " + (f"\033[31m{_f} failed\033[0m" if _f else "0 failed"))
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

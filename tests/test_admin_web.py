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

        print("== 1. Admin setup + add a WEB-mode account ==")
        code, d = jreq("/admin/api/setup", {"password": "admin123"})
        check("admin setup ok", code == 200 and d.get("ok"))
        code, d = jreq("/admin/api/accounts", {
            "mode": "web", "name": "MR7", "user": PUSER, "password": PPASS,
            "panel_base": PANEL, "host": "http://mrha.ink",
        })
        check("web account added", code == 200 and d.get("ok"),
              d.get("error") or "ok")
        acc = next((a for a in d.get("accounts", []) if a["user"] == PUSER), {})
        check("account stored as web mode", acc.get("mode") == "web")
        acc_id = acc.get("id", "")

        print("\n== 2. Log in as the account, then packages asks for captcha (no OCR) ==")
        # سجّل خروج الأدمن ثم ادخل بالحساب
        op.open(ADMIN + "/admin/logout")
        code, d = jreq("/admin/api/login", {"user": PUSER, "password": PPASS})
        check("account login ok", code == 200 and d.get("role") == "account")
        code, d = jreq("/admin/api/packages")
        check("packages requests captcha (OCR off)", d.get("need_captcha") is True,
              json.dumps(d, ensure_ascii=False)[:80])

        print("\n== 3. Fetch captcha, read it, submit the code ==")
        # حمّل صورة الكابتشا (تبدأ جلسة اللوحة وتحفظ الكوكيز على قرص الأدمن)
        r = op.open(ADMIN + "/admin/api/web/captcha", timeout=15)
        img = r.read()
        check("captcha image returned", r.getcode() == 200 and len(img) > 0,
              "%s %dB" % (r.headers.get("Content-Type"), len(img)))
        # اقرأ الكود الحالي من اللوحة الوهمية بجلسة الحساب نفسها (كوكيز على قرص الأدمن)
        jar_path = os.path.join(data_dir, "sessions", acc_id + ".cookies")
        cjar = http.cookiejar.MozillaCookieJar(jar_path)
        cjar.load(ignore_discard=True, ignore_expires=True)
        pop = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cjar))
        cr = pop.open(PANEL + "/captcha.php?a=1", timeout=10)
        cr.read()
        real_code = cr.headers.get("X-Captcha-Code", "")
        check("read the panel captcha code", real_code != "", real_code)
        code, d = jreq("/admin/api/web/login", {"captcha": real_code})
        check("manual captcha login accepted", code == 200 and d.get("ok") is True,
              d.get("error") or "ok")

        print("\n== 4. Now packages load, and a line can be created ==")
        code, d = jreq("/admin/api/packages")
        check("packages loaded after login", isinstance(d.get("packages"), list) and len(d["packages"]) == 3,
              "count=%s" % (len(d.get("packages", [])) if isinstance(d.get("packages"), list) else "?"))
        code, d = jreq("/admin/api/create", {"package_id": "3", "host": "http://mrha.ink",
                                             "username": "", "password": "", "count": 1})
        lines = d.get("lines", [])
        check("line created via web session", bool(lines) and "Username" in lines[0].get("line", ""),
              (lines[0]["line"][:48] + "…") if lines else json.dumps(d, ensure_ascii=False)[:80])
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

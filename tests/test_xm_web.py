#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اختبار جلسة الويب (xm_web) مقابل اللوحة الوهمية — بلا إنترنت.
يغطّي: تخطّي التحقّق البشري، الكابتشا الآلي (OCR محاكى)، fallback البشري،
حفظ الكوكيز، قراءة الباقات، إنشاء يوزر والتأكد منه، إعادة استخدام الجلسة.

تشغيل:  python tests/test_xm_web.py
"""
import os
import sys
import time
import shutil
import tempfile
import subprocess
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import xm_web  # noqa: E402

PORT = int(os.environ.get("MOCK_PANEL_PORT", "9077"))
USER, PASS = "demo", "secret"
BASE = f"http://127.0.0.1:{PORT}"

_p = 0
_f = 0


def check(label, cond, extra=""):
    global _p, _f
    if cond:
        _p += 1
        print(f"  \033[32mPASS\033[0m  {label}" + (f"  ({extra})" if extra else ""))
    else:
        _f += 1
        print(f"  \033[31mFAIL\033[0m  {label}" + (f"  ({extra})" if extra else ""))


def mock_code(session):
    """يقرأ كود الكابتشا الحالي من اللوحة الوهمية عبر نفس opener الجلسة (نفس الكوكيز)،
    فيصبح هو الكود الصالح للطلب التالي — يحاكي إنسانًا يقرأ الصورة."""
    r = session.opener.open(BASE + "/captcha.php?a=1", timeout=10)
    r.read()
    return r.headers.get("X-Captcha-Code", "")


def main():
    srv = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_panel.py"), str(PORT), USER, PASS],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(BASE + "/token.php", timeout=0.3)
                break
            except Exception:
                time.sleep(0.1)
        print(f"mock panel up on {BASE} (pid {srv.pid})\n")

        data_dir = tempfile.mkdtemp(prefix="xmweb_")
        acct = {"id": "acc1", "user": USER, "password": PASS,
                "panel_base": BASE, "host": "http://mrha.ink"}

        # ---- 1) المسار الآلي (OCR محاكى يقرأ الكود الصحيح) ----
        print("== 1. Auto-captcha login (simulated OCR) ==")
        s = xm_web.PanelWebSession(acct, data_dir)
        # نحاكي OCR ناجحًا: نقرأ كود اللوحة الوهمية بنفس جلسة الحساب بعد fetch.
        orig_fetch = s.fetch_captcha
        holder = {}

        def fetch_and_remember():
            ct, img = orig_fetch()
            holder["code"] = mock_code(s)  # آخر كابتشا = الصالحة (عبر opener الجلسة)
            return ct, img
        s.fetch_captcha = fetch_and_remember
        xm_web.solve_captcha = lambda img: holder.get("code", "")  # OCR محاكى
        s.use_ocr = True

        ok = s.login()
        check("auto login succeeded", ok is True)
        check("human-check cookie saved", any(c.name == "xm_simple_security_check" for c in s.cj))
        check("PHPSESSID saved", any(c.name == "PHPSESSID" for c in s.cj))
        check("is_authenticated() true", s.is_authenticated())

        print("\n== 2. Read packages from the add page ==")
        pkgs = s.packages()
        check("packages parsed", len(pkgs) == 3, "count=%d" % len(pkgs))
        check("package has id+name", bool(pkgs and pkgs[0].get("id") and pkgs[0].get("name")),
              pkgs[0]["name"] if pkgs else "-")

        print("\n== 3. Create a line and verify it ==")
        line = s.create_line(package_id=3, username="webuser1", password="pass1234")
        check("create returned a line id", bool(line.get("line_id")), "id=%s" % line.get("line_id"))
        check("line text formatted", "webuser1" in line["line"] and "mrha.ink" in line["line"])
        check("selected package recorded", line["package_id"] == "3")

        print("\n== 4. Session reused from disk (new object) ==")
        s2 = xm_web.PanelWebSession(acct, data_dir)
        check("reloaded session authenticated", s2.is_authenticated())

        # ---- 5) fallback بشري: OCR يفشل → CaptchaNeeded → إدخال يدوي ----
        print("\n== 5. Human fallback when OCR fails ==")
        data_dir2 = tempfile.mkdtemp(prefix="xmweb2_")
        s3 = xm_web.PanelWebSession(acct | {"id": "acc2"}, data_dir2)
        xm_web.solve_captcha = lambda img: ""   # OCR يفشل دائمًا
        s3.use_ocr = True
        needed = None
        try:
            s3.login(auto_attempts=2)
            check("raises CaptchaNeeded when OCR fails", False, "no exception")
        except xm_web.CaptchaNeeded as e:
            needed = e
            check("raises CaptchaNeeded when OCR fails", True, "reason=%s" % e.reason)
            check("carries a captcha image", bool(e.image), "%d bytes" % len(e.image))
        # المشغّل يقرأ الصورة ويكتب الكود؛ نقرأه من اللوحة الوهمية (آخر كابتشا صالحة)
        human_code = mock_code(s3)
        ok = s3.login(captcha=human_code)
        check("manual captcha logs in", ok is True, "code=%s" % human_code)

        print("\n== 6. Wrong password surfaces LoginFailed ==")
        data_dir3 = tempfile.mkdtemp(prefix="xmweb3_")
        bad = xm_web.PanelWebSession(acct | {"id": "acc3", "password": "WRONG"}, data_dir3)
        bad.begin()
        code = mock_code(bad)
        try:
            bad.login(captcha=code)
            check("correct captcha + wrong password -> LoginFailed(credentials), NOT captcha", False, "no exception")
        except xm_web.LoginFailed as e:
            # هذا هو الخطأ الذي كان يُخفى كـ«الكود غير صحيح»: يجب أن يكون credentials.
            check("correct captcha + wrong password -> LoginFailed(credentials), NOT captcha",
                  e.code == "credentials", "code=%s msg=%s" % (e.code, str(e)[:40]))
        except xm_web.CaptchaNeeded:
            check("correct captcha + wrong password -> LoginFailed(credentials), NOT captcha",
                  False, "BUG: mislabeled a credentials failure as a captcha error")

        for d in (data_dir, data_dir2, data_dir3):
            shutil.rmtree(d, ignore_errors=True)
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()

    print("\n----------------------------------------")
    print(f"Result: \033[32m{_p} passed\033[0m, " + (f"\033[31m{_f} failed\033[0m" if _f else "0 failed"))
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

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
        print("== 0. _field_value: input / select / textarea / unquoted ==")
        FV = xm_web.PanelWebSession._field_value
        check("input, quoted value", FV('<input type=hidden name="member_id" value="8842">', "member_id") == "8842")
        check("input, value before name", FV('<input value="77" name="member_id">', "member_id") == "77")
        check("input, single quotes", FV("<input name='member_id' value='55'>", "member_id") == "55")
        check("input, unquoted value", FV('<input name=member_id value=8842>', "member_id") == "8842")
        check("select, selected option", FV('<select name="member_id"><option value="1">a</option>'
              '<option value="8842" selected>me</option></select>', "member_id") == "8842")
        check("select, first option when none selected", FV('<select name="member_id">'
              '<option value="">--</option><option value="900">x</option></select>', "member_id") == "900")
        check("textarea", FV('<textarea name="member_id">4242</textarea>', "member_id") == "4242")
        check("absent -> empty", FV('<input name="other" value="z">', "member_id") == "")

        print("\n== 0b. credits / dashboard number parsing ==")
        EC = xm_web.PanelWebSession._extract_credits
        DN = xm_web.PanelWebSession._dashboard_number
        check("Credits: N (same node)", EC('<span class="credits-box">Credits: 1002</span>') == 1002)
        check("Credits with tags between", EC('<div>Credits:</div> <b>1,250</b>') == 1250)
        check("Arabic الرصيد", EC('<div>الرصيد: 340</div>') == 340)
        check("data-credits attribute", EC('<i data-credits="88"></i>') == 88)
        check("no credits -> None", EC('<div>Dashboard</div>') is None)
        check("card number precedes label", DN('<h3>253</h3><p>ACTIVE SUBSCRIPTIONS</p>', r"active\s+subscription") == 253)
        check("distinct label, not the earlier number",
              DN('<h3>26</h3><p>CREATED TODAY</p><h3>253</h3><p>ACTIVE SUBSCRIPTIONS</p>', r"active\s+subscription") == 253)

        for _ in range(50):
            try:
                urllib.request.urlopen(BASE + "/token.php", timeout=0.3)
                break
            except Exception:
                time.sleep(0.1)
        print(f"\nmock panel up on {BASE} (pid {srv.pid})\n")

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

        print("\n== 3b. Create stays non-fatal if verification can't find the line ==")
        orig_search = s._search_line
        s._search_line = lambda u: {}      # محاكاة فشل/تأخّر table_search
        try:
            line2 = s.create_line(package_id=1, username="webuser2", password="pw2")
            check("line still returned when search fails",
                  line2.get("username") == "webuser2" and "webuser2" in line2["line"])
            check("flagged as unverified", line2.get("verified") is False)
        finally:
            s._search_line = orig_search

        print("\n== 3c. Panel dashboard status (credits from the page) ==")
        st = s.status()
        check("status reads credits from the panel page", st.get("credits") == 1002, "credits=%s" % st.get("credits"))
        check("status carries active subscriptions as total", isinstance(st.get("total"), int) and st["total"] >= 253,
              "total=%s" % st.get("total"))
        check("status reads created-today and online counts", st.get("created_today") == 26 and st.get("online") == 6,
              "today=%s online=%s" % (st.get("created_today"), st.get("online")))
        check("status reports the newest line as last user", st.get("last_username") == "webuser2",
              "last=%s" % st.get("last_username"))
        rows = s.search("webuser1")
        check("search by username on the panel table", len(rows) == 1 and rows[0]["username"] == "webuser1"
              and rows[0]["password"] == "pass1234", str(rows)[:80])
        rows = s.search("pw2")
        check("search by password on the panel table", len(rows) == 1 and rows[0]["username"] == "webuser2", str(rows)[:80])
        check("empty search returns nothing", s.search("  ") == [])

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

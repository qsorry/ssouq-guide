#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اختبار جلسة الويب (xm_web) مقابل اللوحة الوهمية — بلا إنترنت.
يغطّي: تخطّي التحقّق البشري، الكابتشا الآلي (OCR محاكى)، fallback البشري،
حفظ الكوكيز، قراءة الباقات، إنشاء يوزر والتأكد منه، إعادة استخدام الجلسة.

تشغيل:  python tests/test_xm_web.py
"""
import os
import json
import sys
import time
import shutil
import tempfile
import subprocess
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import xm_web  # noqa: E402
import mock_casper  # noqa: E402

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


def _raises(fn):
    try:
        fn()
        return ""
    except Exception as e:
        return str(e)


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

        print("\n== 0a. captcha url + image sniffing ==")
        CS = xm_web.PanelWebSession._captcha_src
        LI = xm_web.PanelWebSession._looks_like_image
        check("img src captcha.php", CS('<img src="captcha.php?a=1"><input name="captcha">') == "captcha.php?a=1")
        check("securimage path", CS('<img id="c" src="/securimage/securimage_show.php?sid=1">') == "/securimage/securimage_show.php?sid=1")
        check("captcha in id, not src", CS('<img id="captcha_img" src="/img/x.png">') == "/img/x.png")
        check("ignores logo", CS('<img src="/logo.png" alt="logo">') == "")
        check("ignores data: uri", CS('<img src="data:image/png;base64,AAA" class="captcha">') == "")
        check("png magic without content-type", LI("", b"\x89PNG\r\n"))
        check("jpeg magic", LI("application/octet-stream", b"\xff\xd8\xff\xe0"))
        check("html is not an image", not LI("text/html", b"<!DOCTYPE html>"))
        check("image/* content-type wins", LI("image/webp", b"RIFF"))

        print("\n== 0a2. bouquet ids from any JSON shape ==")
        BI = xm_web.PanelWebSession._bouquet_ids
        check("marah shape", BI('{"bouquets":[{"id":1},{"id":"2"}]}') == [1, 2])
        check("nested bouquet_ids strings", BI({"data": {"bouquet_ids": ["3", "4"]}}) == [3, 4])
        check("plain int list under bouquets", BI({"bouquets": [5, 6, 6]}) == [5, 6])
        check("json-in-string", BI({"bouquets": "[7,8]"}) == [7, 8])
        check("comma string", BI({"bouquets": "9,10"}) == [9, 10])
        check("preferred over unrelated lists", BI({"ids": [99], "bouquets": [{"id": 1}]}) == [1])
        check("fallback to any id list", BI({"data": [{"id": 11}, {"id": 12}]}) == [11, 12])
        check("html -> empty", BI("<html>404</html>") == [])
        PB = xm_web.PanelWebSession._page_bouquets
        check("page checkboxes", PB('<input type="checkbox" name="bouquets[]" value="3"><input name="x" value="9">'
                                    '<select name="bouquet_ids[]"><option value="1">a</option><option value="2">b</option></select>') == [1, 2, 3])

        print("\n== 0a3. table row: package / created date / dates for the package type ==")
        PR = xm_web.PanelWebSession._parse_row
        r0 = PR('<a href="?userid=5">e</a> User: u1 Pass: p1 Created: 2026-09-20 End: 2027-12-20 <a>0 / 2</a> <span>Package: اشتراك سنة + 3 اشهر + جهازين (12 نقطة)</span>')
        check("row: package name, created, conns, dates", r0["package"] == "اشتراك سنة + 3 اشهر + جهازين (12 نقطة)" and r0["created"] == "2026-09-20"
              and r0["conns"] == "2" and r0["dates"] == ["2026-09-20", "2027-12-20"], str(r0)[:120])
        r1 = PR('User: u2 Pass: p2 End: 2027-01-01 <a>0 / 1</a>')
        check("row without package/created stays parseable", r1["package"] == "" and r1["created"] == "" and r1["dates"] == ["2027-01-01"])

        print("\n== 0b. credits / dashboard number parsing ==")
        EC = xm_web.PanelWebSession._extract_credits
        DN = xm_web.PanelWebSession._dashboard_number
        check("Credits: N (same node)", EC('<span class="credits-box">Credits: 1002</span>') == 1002)
        check("Credits with tags between", EC('<div>Credits:</div> <b>1,250</b>') == 1250)
        check("Arabic الرصيد", EC('<div>الرصيد: 340</div>') == 340)
        check("data-credits attribute", EC('<i data-credits="88"></i>') == 88)
        check("Arabic رصيدك with suffix + colon", EC('<div>رصيدك: 1002</div>') == 1002)
        check("Arabic نقاطك suffix", EC('<span>نقاطك</span> <b>7</b>') == 7)
        check("number before نقاط", EC('<h3>1,250</h3><small>نقاط</small>') == 1250)
        check("English endpoints does NOT match points", EC('<div>endpoints ready 99</div>') is None)
        check("no credits -> None", EC('<div>Dashboard total 5</div>') is None)
        check("card CREDITS beats a sidebar badge 1",
              EC('<li><a>Credits</a><span class="badge">1</span></li><div><h3>3,975.50</h3><p>CREDITS</p></div>') == 3975.5)
        check("decimal credits kept", EC('<h3>3,975.50</h3><p>CREDITS</p>') == 3975.5)
        XC = ('<div class="card-bg credits"><h3><span data-plugin="counterup" class="entry">0</span></h3><p>Credits</p></div>'
              '<small>New M3U with Package [YEAR], Credits: <font color="green">3974.5</font> -> <font color="red">3973.5</font></small>'
              '<small>New M3U with Package [6 Month], Credits: <font color="green">3976</font> -> <font color="red">3975.5</font></small>')
        check("Xtream Codes: newest log line after the arrow, not the JS counter 0", EC(XC) == 3973.5, str(EC(XC)))
        check("counter 0 alone is ignored", EC('<span data-plugin="counterup" class="entry">0</span></h3><p>Credits</p>') is None)
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
        check("packages parsed", len(pkgs) == 4, "count=%d" % len(pkgs))
        check("package has id+name", bool(pkgs and pkgs[0].get("id") and pkgs[0].get("name")),
              pkgs[0]["name"] if pkgs else "-")

        print("\n== 3. Create a line and verify it ==")
        line = s.create_line(package_id=3, username="webuser1", password="pass1234")
        check("create returned a line id", bool(line.get("line_id")), "id=%s" % line.get("line_id"))
        check("line text formatted", "webuser1" in line["line"] and "mrha.ink" in line["line"])
        check("selected package recorded", line["package_id"] == "3")

        print("\n== 3b. Create a second line and verify it ==")
        line2 = s.create_line(package_id=1, username="webuser2", password="pw2")
        check("second create returned a line id", bool(line2.get("line_id")), "id=%s" % line2.get("line_id"))
        check("second line verified", line2.get("verified") is True)

        print("\n== 3x. Extend a line (ExtendUser modal), as the Selenium script does ==")
        EF = xm_web.PanelWebSession._extend_form
        f = EF('<div><form id="extend_user_form"><input type="hidden" name="edit" value="9"><input type="hidden" name="keep_remaining_days" value="0">'
               '<input type="text" name="note" value="x"><select name="package"><option value="">Select</option>'
               '<option value="15" data-connections="2">اشتراك سنة + 3 اشهر</option></select></form></div>')
        check("extend-form reader: hidden fields + options + data-connections",
              f["found"] and f["fields"] == {"edit": "9", "keep_remaining_days": "0"} and f["options"] == [
                  {"value": "15", "text": "اشتراك سنة + 3 اشهر", "connections": "2"}], str(f)[:120])
        check("extend-form reader: missing form -> found False", EF('<div class="alert alert-danger">no</div>')["found"] is False)
        check("supports_extend() true on Xtream-Masters and cached", s.supports_extend() is True and s._meta().get("extend_modal") is True)
        base = s.create_line(package_id=15, username="extuser1", password="extpw1")
        check("15-month base line created", base.get("line_id") and base.get("exp") == "2026-12-31", str(base.get("exp")))
        ext = s.extend_line("extuser1", 15, "اشتراك سنة + 3 اشهر")
        check("extend: end date moved by the package duration", ext["before"] == "2026-12-31" and ext["after"] == "2028-03-31",
              "%s -> %s" % (ext["before"], ext["after"]))
        check("extend: panel message + credits surfaced", ext["message"] == "User extended" and ext["credits"] == "994", str(ext)[:80])
        try:
            s.extend_line("nosuchuser", 15)
            check("extend of unknown user raises before sending", False, "no exception")
        except RuntimeError as e:
            check("extend of unknown user raises before sending", "غير موجود" in str(e), str(e)[:60])
        try:
            s.extend_line("extuser1", 999)
            check("extend with a package not in the modal raises before sending", False, "no exception")
        except RuntimeError as e:
            check("extend with a package not in the modal raises before sending", "غير متاحة للتمديد" in str(e), str(e)[:60])

        print("\n== 3c. Panel dashboard status (credits from the page) ==")
        s.create_line(package_id=1, username="old_user9", password="oldpw")   # اللوحة الوهمية تعدّه مُنشأً بالأمس
        td = s.today_lines()
        check("today_lines: only lines created today, newest first, with the server count",
              td["count"] == 3 and [x["username"] for x in td["lines"]] == ["extuser1", "webuser2", "webuser1"], str(td)[:120])
        check("today's date is Riyadh's", td["date"] == xm_web.PanelWebSession._today() and len(td["date"]) == 10, td["date"])
        st = s.status()
        check("status carries created_today + today_lines from the table (not the JS counter)", st.get("created_today") == 3
              and len(st.get("today_lines", [])) == 3 and st["today_lines"][0]["password"] == "extpw1", str(st.get("created_today")))
        check("status reads credits from the panel page", st.get("credits") == 1002, "credits=%s" % st.get("credits"))
        # الجدول فيه لاينان (webuser1/webuser2) بينما بطاقة اللوحة تقول 255 —
        # فالعدد يجب أن يأتي من الجدول الموثوق لا من البطاقة.
        check("total comes from the users table, not the JS dashboard card", st.get("total") == 4,
              "total=%s" % st.get("total"))
        check("JS-placeholder counts are not surfaced", "online" not in st)
        check("status reports the newest line as last user", st.get("last_username") == "old_user9",
              "last=%s" % st.get("last_username"))
        rows = s.search("webuser1")
        check("search by username on the panel table", len(rows) == 1 and rows[0]["username"] == "webuser1"
              and rows[0]["password"] == "pass1234", str(rows)[:80])
        rows = s.search("pw2")
        check("search by password on the panel table", len(rows) == 1 and rows[0]["username"] == "webuser2", str(rows)[:80])
        check("empty search returns nothing", s.search("  ") == [])

        print("\n== 3d. Recent-rows scan captures the id when term-search lags ==")
        orig_search = s._search_line
        s._search_line = lambda u, force=False: {}   # بحث الجدول بالمصطلح يتأخّر بالفهرسة
        try:                                          # لكن أحدث الصفوف (المسح الاحتياطي) يجده
            line3 = s.create_line(package_id=3, username="webuser3", password="pw3")
            check("id captured via recent-rows fallback", bool(line3.get("line_id")),
                  "id=%s" % line3.get("line_id"))
            check("flagged verified via fallback", line3.get("verified") is True)
        finally:
            s._search_line = orig_search

        print("\n== 3e. Unconfirmed create on a proven-search panel raises (no phantom user) ==")
        # على لوحةٍ أثبت بحثها أنه يجد يوزرنا، غياب اليوزر عن الجدول وعن أحدث الصفوف = فشلٌ
        # صامتٌ للإنشاء، فيُرفع خطأ بدل تلفيق يوزرٍ لا وجود له (سبب مشكلة اليوزر «المفقود»).
        orig_search, orig_recent = s._search_line, s._recent_line
        s._search_line = lambda u, force=False: {}
        s._recent_line = lambda u, scan=80: {}
        raised = ""
        try:
            s.create_line(package_id=1, username="phantom1", password="pw9")
        except RuntimeError as e:
            raised = str(e)
        finally:
            s._search_line, s._recent_line = orig_search, orig_recent
        check("phantom (unconfirmed) create raises instead of fabricating a user",
              "لم تُنشئ اللوحة اليوزر" in raised, raised[:80])

        print("\n== 4. Session reused from disk (new object) ==")
        s2 = xm_web.PanelWebSession(acct, data_dir)
        check("reloaded session authenticated", s2.is_authenticated())

        print("\n== 4b. Search reaches a gate that was not opened (expired session) ==")
        # البحث في كل البوابات يصل بوابةً لم تُفتح: بلا دخولٍ كان الجدول يرجع تحويلًا لصفحة الدخول،
        # فيُقرأ «لوحة بلا جدول» وتُحفظ العلامة — فيرجع كل بحثٍ بعدها فارغًا (اليوزر في مرح لا يظهر).
        s._save_meta(no_table_search=True)                  # بوابةٌ أفسدتها تلك العلامة من قبل
        rows = s.search("webuser1")
        check("search still asks the panel and finds the user", [r["username"] for r in rows] == ["webuser1"], str(rows)[:80])
        check("…and a find clears the stale «no table» flag", not s._meta().get("no_table_search"))
        os.remove(s.jar_path)                               # جلسةٌ منتهية: لا كوكيز
        cold = xm_web.PanelWebSession(acct, data_dir)
        t = cold._table_query("webuser1", 10, force=True)
        check("a redirect to the login page is not taken for «no table»", t["rows"] == []
              and not cold._meta().get("no_table_search"), str(cold._meta().get("no_table_search")))
        xm_web.solve_captcha = lambda img: ""               # لا OCR: الدخول يحتاج إنسانًا
        cold.use_ocr = True
        try:
            cold.search("webuser1")
            check("search on an expired session logs in first (needs the code), not «not found»", False, "returned rows")
        except xm_web.CaptchaNeeded:
            check("search on an expired session logs in first (needs the code), not «not found»", True)
        check("…and still no «no table» flag", not cold._meta().get("no_table_search"))
        late = xm_web.PanelWebSession(acct, data_dir)       # طلبٌ بُني قبل أن يدخل غيره…
        s._save_cookies()                                   # …ثم دخل طلبٌ آخر وحفظ جلسته
        logins = []
        late.login = lambda *a, **k: logins.append(1)
        late.ensure_login()
        check("a request that waited on the login lock takes the new session, no second login",
              logins == [] and late.is_authenticated(), str(logins))

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

        # ---- 5) لوحة بشكل آخر (ككاسبر): /login.php وصورة على مسار غير captcha.php ----
        print("\n== 5. Alt-shaped panel: login page + captcha url discovered from the page itself ==")
        ALT_PORT = PORT + 1
        ALT = f"http://127.0.0.1:{ALT_PORT}"
        alt_srv = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_panel.py"), str(ALT_PORT), USER, PASS, "alt"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        data_dir4 = tempfile.mkdtemp(prefix="xmweb_")
        try:
            for _ in range(50):
                try:
                    urllib.request.urlopen(ALT + "/token.php", timeout=0.3)
                    break
                except Exception:
                    time.sleep(0.1)
            s5 = xm_web.PanelWebSession({"id": "alt", "user": USER, "password": PASS,
                                         "panel_base": ALT, "host": "http://mrha.ink"}, data_dir4)
            s5.begin()
            meta = s5._meta()
            check("login page found at /login.php (not /login)", meta.get("login_path") == "/login.php", str(meta.get("login_path")))
            check("lkey scraped from the alt login page", bool(meta.get("lkey")))
            check("captcha url read from the page", meta.get("captcha_url") == "img/verify.php?x=1", str(meta.get("captcha_url")))
            ct, img = s5.fetch_captcha()
            check("captcha fetched from the discovered url as an image", ct.startswith("image/") and img.startswith(b"GIF8"), "%s %dB" % (ct, len(img)))
            # الكود الصالح هو آخر صورة جُلبت بجلستنا؛ نقرأه من الترويسة كإنسان يقرأ الصورة
            r = s5.opener.open(ALT + "/img/verify.php?x=1", timeout=10); r.read()
            ok5 = s5.login(captcha=r.headers.get("X-Captcha-Code", ""))
            check("manual login works on the alt-shaped panel", ok5 is True)

            # مسار كابتشا خاطئ (كما لو كانت اللوحة ردّت 404 HTML) → خطأ مقروء لا بايتات HTML كصورة
            s6 = xm_web.PanelWebSession({"id": "alt2", "user": USER, "password": PASS,
                                         "panel_base": ALT, "host": "http://mrha.ink"}, data_dir4)
            s6.begin(); s6._save_meta(captcha_url="/captcha.php?a=1")
            try:
                s6.fetch_captcha()
                check("non-image captcha response raises a readable error", False, "no exception")
            except RuntimeError as e:
                check("non-image captcha response raises a readable error", "لم تُرجع صورة" in str(e) and "HTTP" in str(e), str(e)[:80])
        finally:
            alt_srv.terminate()
            try:
                alt_srv.wait(timeout=5)
            except Exception:
                alt_srv.kill()
            shutil.rmtree(data_dir4, ignore_errors=True)

        # ---- 6) لوحة بلا كود تحقق (ككاسبر): دخول مباشر بلا صورة، ثم باقات وإنشاء ----
        print("\n== 6. Panel without captcha (Kasper-shaped): direct login, packages, create ==")
        NC_PORT = PORT + 2
        NC = f"http://127.0.0.1:{NC_PORT}"
        nc_srv = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_panel.py"), str(NC_PORT), USER, PASS, "nocap"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        data_dir5 = tempfile.mkdtemp(prefix="xmweb_")
        try:
            for _ in range(50):
                try:
                    urllib.request.urlopen(NC + "/token.php", timeout=0.3)
                    break
                except Exception:
                    time.sleep(0.1)
            PF = xm_web.PanelWebSession._parse_login_form
            f = PF('<form action="./login.php" method="post"><input type="hidden" name="lkey" value="ab">'
                   '<input type="text" name="user_name"><input type="password" name="pass_word">'
                   '<button type="submit" name="go">Login</button></form>')
            check("form parser: action + fields + detected names",
                  f["action"] == "./login.php" and f["fields"].get("lkey") == "ab" and f["user_field"] == "user_name"
                  and f["pass_field"] == "pass_word" and not f["captcha_field"] and "go" not in f["fields"], str(f)[:100])
            f2 = PF('<form><input name="username"><input type="password" name="password"><input name="captcha"></form>')
            check("form parser: captcha field detected", f2["captcha_field"] == "captcha")

            s7 = xm_web.PanelWebSession({"id": "nocap", "user": USER, "password": PASS,
                                         "panel_base": NC, "host": "http://mrha.ink"}, data_dir5)
            xm_web.solve_captcha = lambda img: ""   # لا OCR — يجب ألا يُطلب أصلًا
            s7.fetch_captcha = lambda: (_ for _ in ()).throw(AssertionError("captcha fetched on a no-captcha panel"))
            ok7 = s7.login()
            check("logs in directly with no captcha fetch", ok7 is True)
            check("needs_captcha() is False", s7.needs_captcha() is False)
            pk = s7.packages()
            check("packages load on no-captcha panel", len(pk) == 4, "count=%d" % len(pk))
            check("no extend modal on this panel -> supports_extend() False (cached)",
                  s7.supports_extend() is False and s7._meta().get("extend_modal") is False)
            r7 = s7.create_line(pk[0]["id"], "1234567890", "0987654321")
            check("line created with our 10-digit pair", r7["username"] == "1234567890" and r7["password"] == "0987654321", r7["line"][:60])
            check("no get_package on this panel -> bouquets left to the panel", r7.get("bouquets") == "panel", str(r7.get("bouquets")))
            m7 = s7._meta()
            check("panel facts cached (bouquets_by_panel) + first confirm miss counted",
                  m7.get("bouquets_by_panel") is True and m7.get("confirm_misses") == 1 and not m7.get("no_table_search"),
                  str({k: m7.get(k) for k in ("bouquets_by_panel", "no_table_search", "confirm_misses")}))
            t0 = time.time()
            r7b = s7.create_line(pk[1]["id"], "1111111111", "2222222222")
            dt = time.time() - t0
            check("second create skips discovery + confirmation waits (< 2s)", r7b["username"] == "1111111111" and dt < 2.0, "%.2fs" % dt)
            pairs = [("30000000%02d" % i, "40000000%02d" % i) for i in range(5)]
            t0 = time.time()
            seen7 = []
            many = s7.create_many(pk[0]["id"], pairs, progress=seen7.append)
            dt = time.time() - t0
            check("create_many: 5 users in order, all created", [m.get("username") for m in many] == [p[0] for p in pairs], str([m.get("username") for m in many]))
            check("create_many: live counter after each confirmed user (1..5)", seen7 == [1, 2, 3, 4, 5], str(seen7))
            check("create_many: one prepare + one request per user (< 3s for 5)", dt < 3.0, "%.2fs" % dt)
            check("a table that never finds us is given up after 3 misses", s7._meta().get("no_table_search") is True, str(s7._meta().get("confirm_misses")))
            t0 = time.time(); s7.create_many(pk[0]["id"], [("5555555555", "6666666666")] * 3); dt = time.time() - t0
            check("after giving up: 3 users with no confirmation wait (< 1s)", dt < 1.0, "%.2fs" % dt)
            st7 = s7.status()
            check("status reads the CREDITS card, not the badge", st7.get("credits") == 3975.5, str(st7.get("credits")))
            check("status total from ACTIVE ACCOUNTS card when no table", st7.get("total") == 4742 + 10, str(st7.get("total")))
            AF = xm_web.PanelWebSession._add_form
            f8 = AF('<form action="./user_reseller.php" method="post"><input type="hidden" name="member_id" value="8842">'
                    '<input type="text" name="username"><input type="password" name="password">'
                    '<select name="package"><option value="">Select</option><option value="1">1 Month</option></select>'
                    '<input type="checkbox" name="allow_epg" checked><input type="checkbox" name="is_trial">'
                    '<button name="submit_user" value="1">Create</button></form>')
            check("add-form reader: fields/package/submit", f8["fields"].get("member_id") == "8842" and f8["package_field"] == "package"
                  and f8["submit"] == "submit_user" and "allow_epg" in f8["fields"] and "is_trial" not in f8["fields"], str(f8)[:120])

            # آخر اتصال في لوحات Xtream (مرح): «Never» = لم يُستخدم، وإلا تاريخ
            PR = xm_web.PanelWebSession._parse_row
            never = PR('<a href="?userid=5">edit</a> User: 111 Pass: 222 Created: 2026-01-01 '
                       'End: 2027-01-01 <a>0 / 1</a> Info: Never')
            check("Xtream row: 'Never' captured as last_conn (unused)", never.get("last_conn") == "Never", str(never.get("last_conn")))
            used = PR('<a href="?userid=6">edit</a> User: 333 Pass: 444 Created: 2026-01-01 '
                      'End: 2027-01-01 <a>1 / 1</a> Last Connection: 2026-09-20 14:30')
            check("Xtream row: a dated last connection is captured",
                  used.get("last_conn", "").startswith("2026-09-20"), str(used.get("last_conn")))
            none = PR('<a href="?userid=7">edit</a> User: 555 Pass: 666 End: 2027-01-01 <a>0 / 1</a>')
            check("Xtream row: no last-connection field -> blank", none.get("last_conn") == "", str(none.get("last_conn")))

            bad7 = xm_web.PanelWebSession({"id": "nocapbad", "user": USER, "password": "wrong",
                                           "panel_base": NC, "host": "http://mrha.ink"}, data_dir5)
            try:
                bad7.login()
                check("wrong password on no-captcha panel -> LoginFailed", False, "no exception")
            except xm_web.LoginFailed as e:
                check("wrong password on no-captcha panel -> LoginFailed", e.code == "credentials", "code=%s" % e.code)
        finally:
            nc_srv.terminate()
            try:
                nc_srv.wait(timeout=5)
            except Exception:
                nc_srv.kill()
            shutil.rmtree(data_dir5, ignore_errors=True)

        # ---- 7) الباقة الافتراضية (٣٠ شهر = ١٥ + تمديد) من طبقة xm_lines، وفشل التمديد لا يُضيع اليوزر ----
        print("\n== 7. xm_lines virtual package: create + extend; extend failure keeps the user ==")
        EF_PORT = PORT + 3
        EFB = f"http://127.0.0.1:{EF_PORT}"
        ef_srv = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_panel.py"), str(EF_PORT), USER, PASS, "extend_fail"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        data_dir6 = tempfile.mkdtemp(prefix="xmweb_")
        os.environ["XM_DATA"] = data_dir6
        try:
            import xm_lines  # noqa: E402  (DATA_DIR يُقرأ عند الاستيراد)
            for _ in range(50):
                try:
                    urllib.request.urlopen(EFB + "/token.php", timeout=0.3)
                    break
                except Exception:
                    time.sleep(0.1)
            gate = {"id": "g1", "name": "مرح", "mode": "web", "host": "http://mrha.ink", "guide_url": "",
                    "panel_base": EFB, "panel_user": USER, "panel_pass": PASS, "digits": 12}
            sx = xm_lines.web_session(gate)
            sx.begin()
            rr = sx.opener.open(EFB + "/captcha.php?a=1", timeout=10); rr.read()
            sx.login(captcha=rr.headers.get("X-Captcha-Code", ""))
            pk = xm_lines.get_packages(gate)
            ids = [p["id"] for p in pk]
            check("get_packages(web) appends x2:15 after the panel's own packages", ids == ["1", "3", "12", "15", "x2:15"], str(ids))
            v = pk[-1]
            check("virtual package carries base + hint for the UI", v["base_id"] == "15" and v["virtual"] and "15 شهر" in v["hint"], str(v)[:100])
            # التمديد يفشل على هذه اللوحة: اليوزر أُنشئ (خُصم) فيجب أن يُعاد في الخطأ وفي lines.txt
            try:
                xm_lines.create_line(gate, v)
                check("extend failure raises", False, "no exception")
            except RuntimeError as e:
                m = str(e)
                check("extend failure raises with the created user + base package named",
                      "بالباقة الأساسية" in m and "اشتراك سنة + 3 اشهر" in m and "Insufficient credits" in m, m[:120])
                u = m.split("اليوزر ")[1].split(" ")[0] if "اليوزر " in m else ""
                check("username in the error is our 12-digit one", u.isdigit() and len(u) == 12, u)
                txt = open(os.path.join(data_dir6, "lines.txt"), encoding="utf-8").read()
                check("lines.txt logs it as base-only", u in txt and "فشل التمديد" in txt, txt.strip()[-80:])
            # لوحة لا تمديد فيها → لا باقات افتراضية أصلًا (nocap mock بلا نافذة تمديد)
            NC2 = PORT + 4
            nc2 = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_panel.py"), str(NC2), USER, PASS, "nocap"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for _ in range(50):
                    try:
                        urllib.request.urlopen(f"http://127.0.0.1:{NC2}/token.php", timeout=0.3)
                        break
                    except Exception:
                        time.sleep(0.1)
                g2 = dict(gate, id="g2", panel_base=f"http://127.0.0.1:{NC2}")
                ids2 = [p["id"] for p in xm_lines.get_packages(g2)]
                check("panel without an extend modal gets no virtual package", ids2 == ["1", "3", "12", "15"], str(ids2))
                check("API-mode gate cannot use a virtual id",
                      "جلسة الويب فقط" in _raises(lambda: xm_lines.create_line(dict(g2, mode="api"), v)))
            finally:
                nc2.terminate(); nc2.wait(timeout=5)
        finally:
            ef_srv.terminate()
            try:
                ef_srv.wait(timeout=5)
            except Exception:
                ef_srv.kill()
            shutil.rmtree(data_dir6, ignore_errors=True)

        # == 8. CasperWebSession: الإنشاء يطابق سكربت المتصفح العامل ==
        print("\n== 8. Casper (c4kpanel): create uses the panel's own username + generated password ==")
        cas_srv, cas_base, _ = mock_casper.start(user_count=20)
        data_dir7 = tempfile.mkdtemp(prefix="xmweb_casper_")
        try:
            cs = xm_web.CasperWebSession(
                {"id": "cas", "user": USER, "password": PASS,
                 "panel_base": cas_base + "/login.php", "host": "http://ssouqhost.vip:80"},
                data_dir7, use_ocr=False)
            check("casper logs in", cs.login() is True)
            cpk = cs.packages()
            check("casper packages parsed (4, Arabic names)", len(cpk) == 4, "count=%d" % len(cpk))
            check("15-month package id 726 present", any(p["id"] == "726" for p in cpk))

            # النشاط الآن (online/offline) يُلتقط من نقطة الحالة في العمود [1]
            allu = cs.all_users()
            check("rows carry the online/offline activity flag",
                  all("active" in r for r in allu) and any(r["active"] == "online" for r in allu)
                  and any(r["active"] == "offline" for r in allu),
                  str({r["active"] for r in allu}))

            # الإنشاء المفرد: اليوزر من اللوحة، وكلمة المرور رقميّةٌ نضبطها نحن.
            # كلمة مرورٍ غير رقمية ممرَّرة → تُستبدَل بواحدةٍ رقمية مولّدة.
            r = cs.create_line("726", "IGNORED_USER", "NOTdigits!!", "http://ssouqhost.vip:80")
            check("username comes from the PANEL, not the caller",
                  r["username"] != "IGNORED_USER" and r["username"].isdigit(), r["username"])
            check("password is forced NUMERIC (never letters / sentinel)",
                  r["password"] not in ("", "Auto Generated", "AutoGenerated") and r["password"].isdigit(),
                  repr(r["password"]))
            check("create_line reports verified", r.get("verified") is True)
            found = cs._find_user(r["username"])
            check("created user is findable on the panel with that password",
                  bool(found) and found["password"] == r["password"], str(found)[:80])
            # كلمة مرورٍ رقميّةٌ ممرَّرة → تُحترَم كما هي
            r2 = cs.create_line("726", None, "135792468013", "http://ssouqhost.vip:80")
            check("a numeric password we pass is used verbatim",
                  r2["password"] == "135792468013", repr(r2["password"]))

            # الدفعة: العدد صحيح، كلٌّ بيوزرٍ فريد وكلمة مرورٍ رقمية مولّدة، بلا تكرار
            t0 = time.time()
            seen_c = []
            many = cs.create_many("726", [(None, None)] * 5, "http://ssouqhost.vip:80",
                                  progress=lambda n, ph: seen_c.append((n, ph)))
            dt = time.time() - t0
            check("create_many (casper): counter per send, then one confirm step",
                  seen_c == [(1, "send"), (2, "send"), (3, "send"), (4, "send"), (5, "send"), (5, "confirm")],
                  str(seen_c))
            errs = [m for m in many if m.get("error")]
            check("create_many: 5/5 created, no errors", len(many) == 5 and not errs,
                  str([m.get("error") for m in many if m.get("error")])[:120])
            unames = [m["username"] for m in many if not m.get("error")]
            check("create_many: all usernames unique", len(set(unames)) == len(unames), str(unames))
            check("create_many: every password generated numeric (regression: disabled field skipped)",
                  all(m["password"].isdigit() and m["password"] not in ("", "AutoGenerated")
                      for m in many if not m.get("error")),
                  str([m["password"] for m in many])[:120])
            # السرعة: لا فواصل زمنية لكل يوزر (كانت 2ث/يوزر) — الدفعة شبه فورية على المحاكاة
            check("create_many: no per-user sleeps (5 users well under 1s on mock)", dt < 1.0, "%.2fs" % dt)
            # القياس: مفاتيح التوقيت مملوءة (لا أصفار كلها) — لواجهة «أين ذهب الوقت»
            tm0 = many[0].get("timing") or {}
            check("timing populated: login/bouquets on first line, page/post/confirm per user",
                  all(k in tm0 for k in ("login_ms", "page_ms", "bouquets_ms", "post_ms", "confirm_ms")),
                  str(tm0))
            check("timing: one verify request shared across the batch (confirm_ms small & equal)",
                  all((m.get("timing") or {}).get("confirm_ms") == tm0.get("confirm_ms") for m in many),
                  str([(m.get("timing") or {}).get("confirm_ms") for m in many]))
        finally:
            cas_srv.shutdown()
            shutil.rmtree(data_dir7, ignore_errors=True)

        # == 9. يوزر «ضعيف» (مرح: Week username): يُستبدل المولَّد ولا تتوقّف الدفعة ==
        # كانت دفعة من ١٠ تتوقّف عند ٥: رفضت اللوحة السادس لضعفه، وقرأ المصنِّفُ «username»
        # في الرسالة فعدّها خطأ دخول فانتظر ~١٢ ثانية تأكيدًا ثم أوقف الدفعة.
        print("\n== 9. Weak username (Marah 'Week username'): replace it, don't stop the batch ==")
        WF = xm_web.weak_field
        check("weak_field: Marah's exact text -> username", WF("Week username, Please use stronge username") == "username")
        check("weak_field: password / 'too weak' / Arabic forms",
              WF("Weak password, please use a stronger password") == "password" and WF("Username is too weak") == "username"
              and WF("اسم المستخدم ضعيف جدًا") == "username" and WF("كلمة المرور ضعيفة") == "password")
        check("weak_field: login and duplicate errors are not 'weak'",
              not WF("Incorrect username or password! Please try again.") and not WF("Username already exists")
              and not WF("") and not WF(None))
        AE = xm_web.PanelWebSession._add_error
        check("weak text read from a JSON reply and from an alert-danger reply",
              WF(AE('{"result":false,"message":"Week username, Please use stronge username"}')) == "username"
              and WF(AE('<div class="alert alert-danger">Week username, Please use stronge username</div>')) == "username")
        WD = xm_web._weak_digits
        check("_weak_digits: repeats and runs, up or down, wrap-around included",
              all(WD(x) for x in ("123", "987", "777", "890", "098", "4120003")) and not any(WD(x) for x in ("135792", "5", "")))
        samples = [xm_web.rand_digits(12) for _ in range(3000)]
        check("rand_digits: 12 digits, no leading zero, never an easy pattern",
              all(len(x) == 12 and x.isdigit() and x[0] != "0" and not WD(x) for x in samples))
        check("rand_digits: still random (3000 distinct)", len(set(samples)) == len(samples))
        import xm_lines  # noqa: E402
        g10 = [xm_lines.rand_digits(10) for _ in range(500)]
        check("xm_lines.rand_digits uses it at the gate's length",
              all(len(x) == 10 and not WD(x) for x in g10), g10[0])

        WK_PORT = PORT + 5
        WKB = f"http://127.0.0.1:{WK_PORT}"
        wk_srv = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_panel.py"), str(WK_PORT), USER, PASS, "weak"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        data_dir8 = tempfile.mkdtemp(prefix="xmweb_weak_")
        orig_rand = xm_web.rand_digits
        orig_dirs = (xm_lines.DATA_DIR, xm_lines.TXT_FILE)
        panel = lambda: json.loads(urllib.request.urlopen(WKB + "/__lines", timeout=5).read())   # noqa: E731
        try:
            for _ in range(50):
                try:
                    urllib.request.urlopen(WKB + "/token.php", timeout=0.3)
                    break
                except Exception:
                    time.sleep(0.1)

            def logged_in(sess):
                sess.begin()
                rr = sess.opener.open(WKB + "/captcha.php?a=1", timeout=10); rr.read()
                sess.login(captcha=rr.headers.get("X-Captcha-Code", ""))
                return sess

            sw = logged_in(xm_web.PanelWebSession({"id": "weak", "user": USER, "password": PASS,
                                                   "panel_base": WKB, "host": "http://mrha.ink"}, data_dir8))
            ok1 = sw.create_line(1, "135792468024", "246813579135")
            check("a strong username is created as before", ok1["username"] == "135792468024"
                  and ok1.get("verified") is True and ok1.get("weak_retries") == 0, str(ok1)[:100])

            pairs = [("192837465019", "564738291056"), ("283746519283", "675849302167"),
                     ("111222333444", "786950413278"), ("394857610394", "897061524389")]
            t0 = time.time(); many = sw.create_many(1, pairs); dt = time.time() - t0
            users = [m.get("username") for m in many]
            check("batch with a weak username completes: 4/4, no error",
                  len(many) == 4 and not any(m.get("error") for m in many), str(many)[-160:])
            check("only the weak one is replaced (12 digits, not weak); the rest kept, in order",
                  users[:2] == [pairs[0][0], pairs[1][0]] and users[3] == pairs[3][0] and users[2] != pairs[2][0]
                  and len(users[2] or "") == 12 and users[2].isdigit() and not WD(users[2]), str(users))
            check("the replacement keeps its generated password and is verified",
                  many[2]["password"] == pairs[2][1] and many[2].get("verified") is True)
            check("weak_retries counts the replacement", [m.get("weak_retries") for m in many] == [0, 0, 1, 0],
                  str([m.get("weak_retries") for m in many]))
            check("no ~12s confirmation wait on the rejection", dt < 3.0, "%.2fs" % dt)
            p = panel()
            on_panel = [x["username"] for x in p["lines"]]
            check("the rejected name was never created; its replacement was",
                  pairs[2][0] not in on_panel and users[2] in on_panel, str(on_panel))

            m2 = sw.create_many(1, [("405968172405", "555000111222")])
            check("a weak generated password is replaced too (username kept)",
                  not m2[0].get("error") and m2[0]["username"] == "405968172405"
                  and m2[0]["password"] != "555000111222" and m2[0].get("weak_retries") == 1, str(m2)[:140])

            before = len(panel()["lines"])
            try:
                sw.create_line(1, "777000", "13579246")
                check("an operator-typed weak username is NOT replaced", False, "no exception")
            except xm_web.WeakRejected as e:
                check("an operator-typed weak username is NOT replaced: Arabic error naming it + the panel's text",
                      e.field == "username" and "777000" in str(e) and "Week username" in str(e)
                      and "اترك الخانة فارغة" in str(e), str(e)[:140])
            check("...and nothing was created for it", len(panel()["lines"]) == before)

            seq = iter(["999888777666"])            # أول يوزرٍ يُولَّد هنا ضعيف
            xm_web.rand_digits = lambda n=12: next(seq, None) or orig_rand(n)
            try:
                r1 = sw.create_line(1, None, "86420864")
            finally:
                xm_web.rand_digits = orig_rand
            check("create_line with no username: the generated weak one is replaced",
                  r1["username"] != "999888777666" and r1.get("weak_retries") == 1 and r1["password"] == "86420864",
                  str(r1)[:120])

            xm_web.rand_digits = lambda n=12: "1" * n   # لوحةٌ ترفض كل بديل: لا حلقة بلا نهاية
            try:
                m3 = sw.create_many(1, [("111111111111", "246802468024")])
            finally:
                xm_web.rand_digits = orig_rand
            err = (m3[0] if m3 else {}).get("error", "")
            check("a panel rejecting every replacement stops with its reason", len(m3) == 1
                  and "Week username" in err and "بدائل" in err, err[:140])
            sent = [x for x in panel()["weak_posts"] if x[0] == "111111111111"]
            check("exactly 1 + WEAK_TRIES attempts were sent", len(sent) == 1 + xm_web.PanelWebSession.WEAK_TRIES,
                  "%d posts" % len(sent))

            # طبقة xm_lines: دفعة على بوابة ويب (جلسة جديدة لم يُثبت بحثها بعد) أولُ يوزرٍ فيها
            # ضعيف → يُستبدل (لا يوزرٌ وهمي على لوحةٍ غير مثبتة)، ويصل weak_retries للصفحة.
            xm_lines.DATA_DIR, xm_lines.TXT_FILE = data_dir8, os.path.join(data_dir8, "lines.txt")
            gate = {"id": "gw", "name": "مرح", "mode": "web", "host": "http://mrha.ink", "guide_url": "",
                    "panel_base": WKB, "panel_user": USER, "panel_pass": PASS, "digits": 12}
            logged_in(xm_lines.web_session(gate))
            pk1 = next(x for x in xm_lines.get_packages(gate) if str(x["id"]) == "1")
            seq = iter(["444555666777"])
            xm_web.rand_digits = lambda n=12: next(seq, None) or orig_rand(n)
            seen_l = []
            try:
                out, err = xm_lines.create_lines(gate, pk1, 3, progress=seen_l.append)
            finally:
                xm_web.rand_digits = orig_rand
            check("xm_lines batch: 3/3 created, no error, weak one replaced",
                  err is None and len(out) == 3 and "444555666777" not in [x["username"] for x in out],
                  "%s %s" % (err, [x["username"] for x in out]))
            check("xm_lines batch: progress reaches the counter (1, 2, 3)", seen_l == [1, 2, 3], str(seen_l))
            check("xm_lines batch: weak_retries reaches the page", sum(x.get("weak_retries", 0) for x in out) == 1,
                  str([x.get("weak_retries") for x in out]))
            check("xm_lines: an operator-typed weak username raises (never swapped for another)",
                  "اترك الخانة فارغة" in _raises(lambda: xm_lines.create_line(gate, pk1, "000999", None)))
        finally:
            xm_web.rand_digits = orig_rand
            xm_lines.DATA_DIR, xm_lines.TXT_FILE = orig_dirs
            wk_srv.terminate()
            try:
                wk_srv.wait(timeout=5)
            except Exception:
                wk_srv.kill()
            shutil.rmtree(data_dir8, ignore_errors=True)

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

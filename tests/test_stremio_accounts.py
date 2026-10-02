#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
حسابات Stremio الجاهزة (‏stremio_accounts.py): الإيميل = اليوزر @tv.ssouq.com وكلمة المرور = الباسورد (و«A» إن
رفضها Stremio)، والإضافة مثبّتةٌ أولَ الحساب، والحفظ المشفَّر، وحساب سبق تسجيله، والحدّ بالساعة — مقابل واجهة
Stremio وهمية وسيرفر Xtream وهمي (بلا إنترنت)، ثم عبر الخادم بزرّ الأداة.

    python tests/test_stremio_accounts.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import http.cookiejar
import smtplib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import mock_stremio_api  # noqa: E402
import mock_xtream  # noqa: E402
import stremio_accounts as A  # noqa: E402
import stremio_addon as S  # noqa: E402

PORT = int(os.environ.get("STREMIO_ACC_TEST_PORT", "9593"))
MAIL_PORT = int(os.environ.get("STREMIO_MAIL_TEST_PORT", "9594"))
FALCON_PORT = int(os.environ.get("STREMIO_FALCON_TEST_PORT", "9595"))
_p = _f = 0


def check(label, cond, extra=""):
    global _p, _f
    if cond:
        _p += 1
        print("  \033[32mPASS\033[0m  " + label + (("  (%s)" % extra) if extra else ""))
    else:
        _f += 1
        print("  \033[31mFAIL\033[0m  " + label + (("  (%s)" % extra) if extra else ""))


def start(srv):
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}"


def raises(fn, kind):
    try:
        fn()
    except kind as e:
        return str(e) or True
    return False


def descriptor_for(xt_host, d, user="u", pw="p"):
    tok = S.make_token(d, xt_host, user, pw)
    cfg = S.read_token(d, tok)
    return lambda: {"manifest": S.manifest(cfg, "https://guide.ssouq.com", "سمارت"),
                    "transportUrl": S.links("https://guide.ssouq.com", tok)["manifest"],
                    "flags": {"official": False, "protected": False}}


def unit():
    print("== الإيميل ==")
    check("اليوزر @tv.ssouq.com", A.email_for("0504998661ali") == "0504998661ali@tv.ssouq.com")
    check("حروفٌ كبيرة ومسافات ورموز تُنظَّف", A.email_for(" Ab C+1/ ") == "abc1@tv.ssouq.com")
    check("دومينٌ آخر", A.email_for("123", "tv.example.com") == "123@tv.example.com")
    check("يوزرٌ بلا حرفٍ صالح ← ValueError", raises(lambda: A.email_for("أحمد"), ValueError))


def against_mocks():
    api = mock_stremio_api.serve(0)
    xt = mock_xtream.serve(0)
    A.API, xt_host = start(api), start(xt)
    d = tempfile.mkdtemp(prefix="stracc_")
    S.reset()
    try:
        print("== حسابٌ جديد ==")
        rec, created = A.ensure(d, "127.0.0.1", "0504998661ali", "0568803105", descriptor_for(xt_host, d))
        check("أُنشئ: الإيميل اليوزر وكلمة المرور الباسورد نفسه", created and rec["email"] == "0504998661ali@tv.ssouq.com"
              and rec["password"] == "0568803105" and api.users.get("0504998661ali@tv.ssouq.com") == "0568803105", json.dumps(rec)[:120])
        col = api.collections["0504998661ali@tv.ssouq.com"]
        check("إضافتنا أولَ الحساب وإضافات Stremio الافتراضية باقية",
              col[0]["manifest"]["id"].startswith("com.ssouq.xtream.") and [a["manifest"]["name"] for a in col[1:]] == ["Cinemeta", "OpenSubtitles v3"],
              str([a["manifest"]["name"] for a in col]))
        check("الإضافة برابطها على الموقع ووصفها كاملًا (الكتالوجات الثلاثة)",
              col[0]["transportUrl"].startswith("https://guide.ssouq.com/stremio/") and len(col[0]["manifest"]["catalogs"]) == 3
              and col[0]["flags"] == {"official": False, "protected": False})
        check("خرج من الجلسة بعد التثبيت", not api.sessions)
        raw = json.load(open(os.path.join(d, "stremio_accounts.json"), encoding="utf-8"))
        check("كلمة المرور محفوظةٌ مشفَّرة", "0568803105" not in json.dumps(raw) and raw["127.0.0.1|0504998661ali"]["password"].startswith("enc:1:"))

        n = len(api.hits)
        rec2, created2 = A.ensure(d, "127.0.0.1", "0504998661ali", "0568803105", descriptor_for(xt_host, d))
        check("المرة الثانية: المحفوظ بلا طلبٍ لـ Stremio", not created2 and rec2 == rec and len(api.hits) == n)
        check("قراءة حساباتٍ كثيرة مرةً واحدة (للبحث)", A.known(d, "127.0.0.1", ["0504998661ali", "x"]) == {"0504998661ali": rec})

        print("== كلمة مرورٍ يرفضها Stremio ==")
        api.require_letter = True
        rec, _ = A.ensure(d, "127.0.0.1", "777001", "12345678", descriptor_for(xt_host, d, "777001", "12345678"))
        check("أرقامٌ فقط ورفضها Stremio ← يُضاف «A»", rec["password"] == "12345678A" and api.users["777001@tv.ssouq.com"] == "12345678A")
        api.require_letter = False
        e36 = A.StremioError("User with this email already exists", 36, {"code": 36, "existingUser": True})
        check("ردّ Stremio الحقيقي للإيميل المسجّل يُعرف (بعلامته لا بنصّه وحده)", A._exists(e36)
              and A._exists(A.StremioError("x", 36, {"existingUser": True})) and not A._exists(A.StremioError("User not found", 2, {})))

        print("== إيميلٌ مسجّلٌ من قبل ==")
        api.users["555@tv.ssouq.com"] = "pass555A"
        api.collections["555@tv.ssouq.com"] = []
        rec, created = A.ensure(d, "127.0.0.1", "555", "pass555", descriptor_for(xt_host, d, "555", "pass555"))
        check("سُجّل بكلمة مرورنا (بـA): يُستعاد ويُثبَّت فيه", created and rec.get("adopted") and rec["password"] == "pass555A"
              and api.collections["555@tv.ssouq.com"][0]["manifest"]["id"].startswith("com.ssouq.xtream."))
        api.users["666@tv.ssouq.com"] = "someone-else"
        msg = raises(lambda: A.ensure(d, "127.0.0.1", "666", "p666", descriptor_for(xt_host, d, "666", "p666")), A.StremioError)
        check("مسجّلٌ بكلمة مرورٍ أخرى ← رسالةٌ واضحة ولا يُحفظ", msg and "بكلمة مرورٍ أخرى" in msg and not A.get(d, "127.0.0.1", "666"), str(msg))

        print("== يوزرٌ بديل على السيرفر نفسه ==")
        auth = A.login("0504998661ali@tv.ssouq.com", "0568803105")
        A.install(auth, descriptor_for(xt_host, d, "u", "p")())       # إضافة يوزرٍ آخر على السيرفر نفسه
        col = api.collections["0504998661ali@tv.ssouq.com"]
        ours = [a for a in col if a["manifest"]["id"].startswith("com.ssouq.xtream.")]
        check("تحلّ محلّ إضافتنا السابقة (لا تكرار للمحتوى)", len(ours) == 1 and col[0] is not None and "/stremio/" in col[0]["transportUrl"]
              and len(col) == 3, str([a["manifest"]["name"] for a in col]))
        other = {"manifest": {"id": "com.ssouq.xtream.other", "idPrefixes": ["sq999999:"], "name": "x"}, "transportUrl": "https://g/x/manifest.json"}
        api.collections["0504998661ali@tv.ssouq.com"].append(other)
        A.install(auth, descriptor_for(xt_host, d, "u", "p")())
        check("وإضافتنا لسيرفرٍ آخر تبقى", any(a["transportUrl"] == "https://g/x/manifest.json" for a in api.collections["0504998661ali@tv.ssouq.com"]))
        A.logout(auth)

        print("== الحدود والأعطال ==")
        A._rate.clear()
        old = A.PER_HOUR
        A.PER_HOUR = 1
        A.ensure(d, "127.0.0.1", "901", "pw9019", descriptor_for(xt_host, d, "901", "pw9019"))
        msg = raises(lambda: A.ensure(d, "127.0.0.1", "902", "pw9029", descriptor_for(xt_host, d, "902", "pw9029")), ValueError)
        check("الحدّ بالساعة", msg and "حدّها" in msg, str(msg))
        A.PER_HOUR = old
        A._rate.clear()
        api.down = True
        msg = raises(lambda: A.ensure(d, "127.0.0.1", "903", "pw9039", descriptor_for(xt_host, d, "903", "pw9039")), A.StremioError)
        check("Stremio لا يردّ ← StremioError ولا يُحفظ شيء", msg and not A.get(d, "127.0.0.1", "903"), str(msg))
        api.down = False
        check("باسوردٌ فارغ ← ValueError", raises(lambda: A.ensure(d, "127.0.0.1", "904", "", descriptor_for(xt_host, d)), ValueError))
        check("تثبيتٌ فشل بعد التسجيل: لا يُحفظ، والمحاولة التالية تستعيده وتكمل",
              _install_fails_then_recovers(api, d, xt_host))
    finally:
        api.shutdown()
        xt.shutdown()
        shutil.rmtree(d, ignore_errors=True)


def _install_fails_then_recovers(api, d, xt_host):
    def bad():
        raise S.XtreamError("x")
    try:
        A.ensure(d, "127.0.0.1", "905", "pw9059", bad)
        return False
    except S.XtreamError:
        pass
    if A.get(d, "127.0.0.1", "905") or "905@tv.ssouq.com" not in api.users or api.sessions:
        return False
    rec, created = A.ensure(d, "127.0.0.1", "905", "pw9059", descriptor_for(xt_host, d, "905", "pw9059"))
    return created and rec.get("adopted") and api.collections["905@tv.ssouq.com"][0]["manifest"]["id"].startswith("com.ssouq.xtream.")


def through_server():
    api = mock_stremio_api.serve(0)
    xt = mock_xtream.serve(0)
    api_url, xt_host = start(api), start(xt)
    d = tempfile.mkdtemp(prefix="stracc_web_")
    with open(os.path.join(d, "accounts.json"), "w", encoding="utf-8") as f:
        json.dump({"admin": None, "accounts": [{"id": "a1", "name": "MR7", "user": "mr7", "password": "pw123456", "stremio": True,
                                                "gates": [{"id": "g1", "name": "بوابة مرح", "mode": "web", "host": xt_host},
                                                          {"id": "g2", "name": "بوابة فالكون", "mode": "falcon", "host": xt_host,
                                                           "api_url": f"http://127.0.0.1:{FALCON_PORT}/api/v1", "api_key": "fk"},
                                                          {"id": "g3", "name": "أرشيف", "mode": "web", "host": xt_host, "archive_only": True}]},
                                               {"id": "a2", "name": "Other", "user": "other", "password": "pw654321", "stremio": True,
                                                "gates": [{"id": "g1", "name": "بوابة مرح", "mode": "web", "host": xt_host}]},
                                               {"id": "a3", "name": "بلا Stremio", "user": "nost", "password": "pw333333",
                                                "gates": [{"id": "g1", "name": "بوابة مرح", "mode": "web", "host": xt_host}]}]}, f)
    env = dict(os.environ, XM_DATA=d, XM_BIND="127.0.0.1", XM_PORT=str(PORT), XM_ADMIN_PASSWORD="adminpw1", STREMIO_API=api_url,
               XM_MAIL_PORT=str(MAIL_PORT), STREMIO_ACTIVATION_WAIT="0.2,0.2,0.2")
    env.pop("XM_SECRET_KEY", None)
    app = subprocess.Popen([sys.executable, os.path.join(ROOT, "xm_lines.py"), "web"], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    falcon = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_falcon.py"), str(FALCON_PORT), "fk"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{PORT}/admin"
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def post(path, obj, opener=None):
        r = urllib.request.Request(base + path, data=json.dumps(obj).encode() if obj is not None else None,
                                   headers={"Content-Type": "application/json"}, method="POST" if obj is not None else "GET")
        try:
            x = (opener or op).open(r, timeout=30)
            return x.getcode(), json.loads(x.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")
    try:
        for _ in range(80):
            try:
                urllib.request.urlopen(base + "/login", timeout=0.3)
                break
            except Exception:
                time.sleep(0.1)
        print("== عبر الأداة ==")
        c, _ = post("/api/stremio/account", {"gate": "g1", "username": "u", "password": "p"})
        check("بلا دخول ← مرفوض", c == 401, str(c))
        op3 = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        post("/api/login", {"user": "nost", "password": "pw333333"}, op3)
        c, r = post("/api/me", None, op3)
        check("عميلٌ لم يفتح له المدير Stremio: ‏/api/me يقول ذلك", c == 200 and r.get("stremio") is False, json.dumps(r)[:80])
        codes = [post(p, b, op3)[0] for p, b in (("/api/stremio/account", {"gate": "g1", "username": "u", "password": "p"}),
                                                  ("/api/stremio/password", {"gate": "g1", "username": "u", "password": "p"}),
                                                  ("/api/stremio/mail?gate=g1&username=u", None))]
        check("ولا حساب Stremio ولا بريده ولا كلمة مروره ← 403", codes == [403, 403, 403], str(codes))
        check("ولم يُسجَّل في Stremio شيء", not api.users)
        c, r = post("/api/login", {"user": "mr7", "password": "pw123456"})
        check("دخول الحساب", c == 200 and r.get("role") == "account", json.dumps(r)[:80])
        c, r = post("/api/stremio/account", {"gate": "g1", "username": "u", "password": "p"})
        check("زرّ «حساب Stremio» ← إيميلٌ وكلمة مرور", c == 200 and r.get("ok") and r["email"] == "u@tv.ssouq.com" and r["password"] == "p"
              and r["created"] is True, json.dumps(r, ensure_ascii=False))
        col = api.collections.get("u@tv.ssouq.com") or [{}]
        check("وإضافة المحتوى مثبّتةٌ في الحساب باسم السيرفر", col[0].get("manifest", {}).get("name") == "سمارت سوق · سمارت",
              col[0].get("manifest", {}).get("name"))
        c, r = post("/api/stremio/account", {"gate": "g1", "username": "u", "password": "p"})
        check("المرة الثانية: الحساب نفسه بلا إنشاء", c == 200 and r["created"] is False and len(api.users) == 1)


        print("== البريد على خادمنا ==")
        link = "https://www.stremio.com/reset-password/tok123"
        with smtplib.SMTP("127.0.0.1", MAIL_PORT, timeout=10) as s:
            s.sendmail("no-reply@strem.io", ["u@tv.ssouq.com"], f"Subject: Reset your password\r\n\r\nOpen {link}\r\n")
            s.mail("x@example.com")
            check("عنوانٌ ليس لحسابٍ عندنا يُرفض عند الاستلام", s.rcpt("nobody@tv.ssouq.com")[0] == 550)
        c, r = post("/api/stremio/mail?gate=g1&username=u", None)
        check("الرسالة تظهر عند اليوزر في الأداة برابطها", c == 200 and r["receiving"] and r["email"] == "u@tv.ssouq.com"
              and r["messages"][0]["subject"] == "Reset your password" and r["messages"][0]["links"] == [link], json.dumps(r, ensure_ascii=False)[:200])
        op2 = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        post("/api/login", {"user": "other", "password": "pw654321"}, op2)
        c, r = post("/api/stremio/mail?gate=g1&username=u", None, op2)
        check("حسابٌ آخر لا يرى بريد يوزرات غيره", c == 404, str(c))

        print("== صفحة Stremio: مكانٌ لكل بوابة ==")
        c, r = post("/api/stremio/accounts?gate=g1", None)
        acc = (r.get("accounts") or [{}])[0]
        g1 = next((g for g in r.get("gates", []) if g["id"] == "g1"), {})
        check("بوابات العميل بعدد حساباتها", c == 200 and g1.get("name") == "بوابة مرح" and g1.get("count") == 1
              and [g["id"] for g in r["gates"]] == ["g1", "g2", "g3"], json.dumps(r, ensure_ascii=False)[:160])
        check("حسابات البوابة: الإيميل وكلمة المرور ورابط التثبيت وعدد البريد", acc.get("email") == "u@tv.ssouq.com" and acc.get("password") == "p"
              and acc.get("link", "").startswith("https://guide.ssouq.com/stremio/") and acc.get("mail_count") == 1 and acc.get("last_mail"),
              json.dumps(acc, ensure_ascii=False)[:200])
        c, r = post("/api/stremio/accounts", None, op2)
        check("حسابٌ آخر يرى بواباته وحدها بلا حسابات غيره", c == 200 and r["accounts"] == [] and r["gates"][0]["count"] == 0, json.dumps(r, ensure_ascii=False)[:120])
        c, r = post("/api/stremio/accounts?gate=nope", None)
        check("بوابةٌ ليست له ← 404", c == 404)
        c, r = post("/api/stremio/accounts", None, op3)
        check("ومن لم يُفتح له ← 403", c == 403)
        c, r = post("/api/stremio/password", {"gate": "g1", "username": "u", "password": "x"}, op2)
        check("ولا يغيّر كلمة مرورها", c == 404, str(c))
        c, r = post("/api/stremio/reinstall", {"gate": "g1", "username": "u"}, op2)
        check("ولا يحدّث إضافتها", c == 404, str(c))
        c, r = post("/api/stremio/reinstall", {"gate": "g1", "username": "u"}, op3)
        check("ومن لم يُفتح له ← 403", c == 403)
        api.down = True
        c, r = post("/api/stremio/reinstall", {"gate": "g1", "username": "u"})
        api.down = False
        check("وStremio لا يردّ ← 502 برسالة", c == 502 and r["error"].startswith("Stremio:"), json.dumps(r, ensure_ascii=False))

        print("== كلمة مرورٍ جديدة ==")
        api.users["u@tv.ssouq.com"] = "NewPass9"                     # غيّرها الموظف في Stremio من رابط البريد
        c, r = post("/api/stremio/password", {"gate": "g1", "username": "u", "password": "WrongOne"})
        check("كلمةٌ لا يقبلها Stremio لا تُحفظ", c == 400 and "لم يقبل" in r["error"], json.dumps(r, ensure_ascii=False))
        c, r = post("/api/stremio/password", {"gate": "g1", "username": "u", "password": "NewPass9"})
        check("الجديدة تُجرَّب ثم تُحفظ", c == 200 and r["ok"] and r["password"] == "NewPass9", json.dumps(r, ensure_ascii=False))
        c, r = post("/api/stremio/account", {"gate": "g1", "username": "u", "password": "p"})
        check("ونسخ الحساب بعدها بكلمة المرور الجديدة", c == 200 and r["password"] == "NewPass9" and r["created"] is False)
        check("لا جلسة Stremio مفتوحة بعد الفحص", not api.sessions)
        c, r = post("/api/stremio/account", {"gate": "nope", "username": "u", "password": "p"})
        check("بوابةٌ ليست له ← 400", c == 400)
        api.down = True
        c, r = post("/api/stremio/account", {"gate": "g1", "username": "u2", "password": "p2"})
        check("Stremio لا يردّ ← 502 برسالة", c == 502 and r["error"].startswith("Stremio:"), json.dumps(r, ensure_ascii=False))
        api.down = False

        print("== «إنشاء يوزر Stremio»: يوزرٌ في البوابة ← البريد ← الإضافة ==")
        c, r = post("/api/stremio/create", {"gate": "g2", "package_id": "167"})
        line, acc = r.get("line") or {}, r.get("stremio_account") or {}
        check("بضغطةٍ واحدة: يوزرٌ جديد في البوابة وحساب Stremio له", c == 200 and r.get("ok") and line.get("username")
              and acc.get("email") == line["username"] + "@tv.ssouq.com" and acc.get("password") == line.get("password"),
              json.dumps(r, ensure_ascii=False)[:200])
        col = api.collections.get(acc.get("email"), [{}])
        check("والإضافة مثبّتةٌ أوله، والسطر برابط تثبيته", col[0].get("manifest", {}).get("id", "").startswith("com.ssouq.xtream.")
              and line.get("stremio", "").startswith("https://guide.ssouq.com/stremio/") and line.get("line", "").startswith("Host "))
        c, r = post("/api/stremio/accounts?gate=g2", None)
        check("ويظهر في قائمة بوابته", c == 200 and [a["username"] for a in r["accounts"]] == [line.get("username")]
              and next(g for g in r["gates"] if g["id"] == "g2")["count"] == 1)
        api.down = True
        c, r = post("/api/stremio/create", {"gate": "g2", "package_id": "167"})
        kept = r.get("line") or {}
        check("Stremio تعثّر بعد إنشاء اليوزر: اليوزر لا يضيع (يعود مع السبب)", c == 200 and r.get("ok") and kept.get("username")
              and "stremio_account" not in r and "تعذّر حساب Stremio" in r.get("stremio_error", ""), json.dumps(r, ensure_ascii=False)[:200])
        api.down = False
        c, r = post("/api/stremio/account", {"gate": "g2", "username": kept.get("username"), "password": kept.get("password"), "line": kept.get("line", "")})
        check("و«إعادة المحاولة» تكمل حسابه", c == 200 and r.get("email") == kept.get("username") + "@tv.ssouq.com")
        c, r = post("/api/stremio/create", {"gate": "g2", "package_id": "999"})
        check("باقةٌ لا توجد ← 400 ولا يُنشأ شيء", c == 400 and "باقة" in r.get("error", ""))
        c, r = post("/api/stremio/create", {"gate": "g3", "package_id": "1"})
        check("بوابة أرشيف ← 400", c == 400 and "أرشيف" in r.get("error", ""))
        c, r = post("/api/stremio/create", {"gate": "g2", "package_id": "167"}, op3)
        check("ومن لم يُفتح له ← 403", c == 403)

        print("== متى تنتهي: من السيرفر نفسه ==")
        c, r = post("/api/stremio/accounts?gate=g1", None)
        u = next((a for a in r.get("accounts", []) if a["username"] == "u"), {})
        check("يوزرٌ سارٍ: تاريخ انتهائه من السيرفر لحظة إنشاء حسابه", u.get("status") == "Active" and u.get("exp", 0) > time.time() + 300 * 86400
              and u.get("exp_checked", 0) > 0, json.dumps(u, ensure_ascii=False)[:200])
        c, r = post("/api/stremio/accounts?gate=g2", None)
        rej = [a for a in r.get("accounts", []) if a.get("status") == "رُفض"]
        g2 = next(g for g in r["gates"] if g["id"] == "g2")
        check("يوزرٌ يرفضه السيرفر (منتهٍ أو موقوف) يُعلَّم، ويُعدّ على تبويب بوابته", len(rej) == len(r["accounts"]) >= 2
              and g2["due"] == g2["count"], json.dumps(g2, ensure_ascii=False))
        check("والسارية لا تُعدّ", next(g for g in r["gates"] if g["id"] == "g1")["due"] == 0)
        c, r = post("/api/stremio/refresh", {"gate": "g1"})
        check("«تحديث الانتهاء» يعيد فحص البوابة ويعيد قائمتها", c == 200 and r.get("checked") == 1 and r.get("accounts"))
        c, r = post("/api/stremio/refresh", {"gate": "g1", "stale": True})
        check("والفحص في الخلفية يتخطّى ما فُحص حديثًا", c == 200 and r.get("checked") == 0)
        c, r = post("/api/stremio/refresh", {"gate": "g1"}, op3)
        check("ومن لم يُفتح له ← 403", c == 403)

        print("== يوزرٌ لم تُفعّله اللوحة بعد (ما حدث في مرح) ==")
        ours = lambda email: [a for a in api.collections.get(email, []) if a.get("manifest", {}).get("id", "").startswith("com.ssouq.")]
        genre_opts = lambda m: [e.get("options") for c in m.get("catalogs", []) for e in c.get("extra", []) if e.get("name") == "genre"]
        xt.users["late"], xt.pending["late"] = "lp", 2               # يُرفض مرتين ثم يُقبل
        c, r = post("/api/stremio/account", {"gate": "g1", "username": "late", "password": "lp"})
        m = (ours("late@tv.ssouq.com") or [{}])[0].get("manifest", {})
        check("يُنتظر حتى يقبله السيرفر ثم تُثبَّت الإضافة بأقسامها وأعدادها", c == 200 and xt.pending["late"] == 0
              and len(genre_opts(m)) == 2 and all(genre_opts(m)) and m["catalogs"][0]["name"].endswith(")"), json.dumps(m, ensure_ascii=False)[:200])
        c, r = post("/api/stremio/account", {"gate": "g1", "username": "nv", "password": "np"})   # يرفضه السيرفر طوال الانتظار
        m = (ours("nv@tv.ssouq.com") or [{}])[0].get("manifest", {})
        check("وما بقي مرفوضًا: الحساب يُنشأ والإضافة تُثبَّت بلا أقسام", c == 200 and r.get("email") == "nv@tv.ssouq.com" and not genre_opts(m))
        c, r = post("/api/stremio/accounts?gate=g1", None)
        flags = {a["username"]: a.get("addon_full") for a in r.get("accounts", [])}
        check("وتُعلَّم في القائمة (والمكتملة لا)", flags == {"u": True, "late": True, "nv": False}, str(flags))
        xt.users["nv"] = "np"                                         # فُعّل بعدها
        c, r = post("/api/stremio/reinstall", {"gate": "g1", "username": "nv"})
        m = [a["manifest"] for a in ours("nv@tv.ssouq.com")]
        check("«تحديث الإضافة» يعيد تثبيتها بأقسامها — نسخةً واحدة مكان القديمة", c == 200 and r.get("addon_full") is True
              and len(m) == 1 and all(genre_opts(m[0])) and len(genre_opts(m[0])) == 2, json.dumps(r, ensure_ascii=False))
        c, r = post("/api/stremio/accounts?gate=g1", None)
        nv = next(a for a in r["accounts"] if a["username"] == "nv")
        check("ويزول التعليم، ويُقرأ حاله من السيرفر من جديد", nv.get("addon_full") is True and nv.get("status") == "Active", json.dumps(nv, ensure_ascii=False)[:200])
        check("ولا جلسة Stremio مفتوحة بعده", not api.sessions)
        c, r = post("/api/stremio/reinstall", {"gate": "g1", "username": "nobody"})
        check("يوزرٌ بلا حساب ← 404", c == 404, str(c))
    finally:
        falcon.terminate()
        app.terminate()
        app.wait(timeout=10)
        api.shutdown()
        xt.shutdown()

    print("== في نتائج البحث ==")
    os.environ["XM_DATA"] = d
    import xm_lines as X
    X.DATA_DIR = d
    rows = X.with_stremio({"host": xt_host}, [{"username": "u", "password": "p"}, {"username": "zz", "password": "p"}])
    check("الصف الذي له حساب يحمله (‏{stremio_email} ‏{stremio_pass})", rows[0].get("stremio_email") == "u@tv.ssouq.com"
          and rows[0].get("stremio_pass") == "NewPass9" and "stremio_email" not in rows[1])   # كلمة المرور بعد تغييرها
    shutil.rmtree(d, ignore_errors=True)


def main():
    unit()
    against_mocks()
    through_server()
    print("\n----------------------------------------")
    print("Result: \033[32m%d passed\033[0m, %s" % (_p, ("\033[31m%d failed\033[0m" % _f) if _f else "0 failed"))
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
حسابات Stremio الجاهزة (‏stremio_accounts.py): الإيميل = اليوزر @tv.ssouq.com وكلمة المرور = الباسورد (و«A» إن
رفضها Stremio)، والإضافة مثبّتةٌ أولَ الحساب، والحفظ المشفَّر، وحساب سبق تسجيله، والحدّ بالساعة — مقابل واجهة
Stremio وهمية وسيرفر Xtream وهمي (بلا إنترنت)، ثم عبر الخادم بزرّ الأداة.

    python tests/test_stremio_accounts.py
"""
import json
import re
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
from urllib.parse import quote
import urllib.request
import http.cookiejar
import smtplib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import mock_addon  # noqa: E402
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
        check("الإضافة برابطها على الموقع ووصفها كاملًا (الحسابات ثم المسلسلات ثم الأفلام ثم البث)",
              col[0]["transportUrl"].startswith("https://guide.ssouq.com/stremio/")
              and [c["type"] for c in col[0]["manifest"]["catalogs"] if not c["id"].startswith(S.CAT_PREFIX) and c["id"] not in S.YEARS.values()] == [S.ACCOUNTS, "series", "movie", "tv"]
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
                                                          {"id": "g3", "name": "أرشيف", "mode": "web", "host": xt_host, "archive_only": True},
                                                          # سيرفرٌ آخر (localhost) — لربط خطوطٍ من أكثر من بوابة في حسابٍ واحد
                                                          {"id": "g4", "name": "بوابة كاسبر", "mode": "web", "host": xt_host.replace("127.0.0.1", "localhost")},
                                                          {"id": "g5", "name": "بوابة فالكون 2", "mode": "falcon", "host": xt_host.replace("127.0.0.1", "localhost"),
                                                           "api_url": f"http://127.0.0.1:{FALCON_PORT}/api/v1", "api_key": "fk"}]},
                                               {"id": "a2", "name": "Other", "user": "other", "password": "pw654321", "stremio": True,
                                                "gates": [{"id": "g1", "name": "بوابة مرح", "mode": "web", "host": xt_host}]},
                                               {"id": "a3", "name": "بلا Stremio", "user": "nost", "password": "pw333333",
                                                "gates": [{"id": "g1", "name": "بوابة مرح", "mode": "web", "host": xt_host}]}]}, f)
    env = dict(os.environ, XM_DATA=d, XM_BIND="127.0.0.1", XM_PORT=str(PORT), XM_ADMIN_PASSWORD="adminpw1", STREMIO_API=api_url,
               XM_MAIL_PORT=str(MAIL_PORT), STREMIO_ACTIVATION_WAIT="0.2,0.2,0.2", STREMIO_EXTRAS_ALLOW_LOCAL="1")
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
              and [g["id"] for g in r["gates"]] == ["g1", "g2", "g3", "g4", "g5"], json.dumps(r, ensure_ascii=False)[:160])
        check("حسابات البوابة: الإيميل وكلمة المرور وعدد البريد، والإضافة مقفلةٌ عليه بلا رابط تثبيت", acc.get("email") == "u@tv.ssouq.com"
              and acc.get("password") == "p" and acc.get("locked") is True and acc.get("link") == "" and acc.get("mail_count") == 1
              and acc.get("last_mail"), json.dumps(acc, ensure_ascii=False)[:200])
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
        check("والإضافة مثبّتةٌ أوله، والسطر بلا رابط تثبيتٍ عامّ (مقفلةٌ على حسابه)", col[0].get("manifest", {}).get("id", "").startswith("com.ssouq.xtream.")
              and "stremio" not in line and line.get("line", "").startswith("Host "), json.dumps(line, ensure_ascii=False)[:160])
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
        genre_opts = lambda m: [e.get("options") for c in m.get("catalogs", []) if c.get("id") not in S.YEARS.values()   # بلا «حسب السنة»
                                for e in c.get("extra", []) if e.get("name") == "genre"]
        xt.users["late"], xt.pending["late"] = "lp", 2               # يُرفض مرتين ثم يُقبل
        c, r = post("/api/stremio/account", {"gate": "g1", "username": "late", "password": "lp"})
        m = (ours("late@tv.ssouq.com") or [{}])[0].get("manifest", {})
        check("يُنتظر حتى يقبله السيرفر ثم تُثبَّت الإضافة بأقسامها وأعدادها", c == 200 and xt.pending["late"] == 0
              and len(genre_opts(m)) == 3 and all(genre_opts(m)) and next(c for c in m["catalogs"] if c["id"] == "sq_series")["name"].endswith(")"),
              json.dumps(m, ensure_ascii=False)[:200])
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
              and len(m) == 1 and all(genre_opts(m[0])) and len(genre_opts(m[0])) == 3, json.dumps(r, ensure_ascii=False))
        c, r = post("/api/stremio/accounts?gate=g1", None)
        nv = next(a for a in r["accounts"] if a["username"] == "nv")
        check("ويزول التعليم، ويُقرأ حاله من السيرفر من جديد", nv.get("addon_full") is True and nv.get("status") == "Active", json.dumps(nv, ensure_ascii=False)[:200])
        check("ولا جلسة Stremio مفتوحة بعده", not api.sessions)
        c, r = post("/api/stremio/reinstall", {"gate": "g1", "username": "nobody"})
        check("يوزرٌ بلا حساب ← 404", c == 404, str(c))

        print("== الإضافة مقفلةٌ على حسابها: لا تُنقل لحسابٍ آخر ==")
        root = f"http://127.0.0.1:{PORT}"
        local = lambda tu: root + tu[tu.index("/stremio/"):]

        def code_of(url):
            try:
                return urllib.request.urlopen(url, timeout=30).getcode()
            except urllib.error.HTTPError as e:
                return e.code
        os.environ["XM_DATA"] = d
        public = S.make_token(d, xt_host, "u", "p")       # رابط اليوزر العام (كما في رسالة الاشتراك)
        old = ours("u@tv.ssouq.com")[0]["transportUrl"]
        check("إضافة الحساب تعمل، ورابط اليوزر العام لا (فلا يُثبَّت في حسابٍ آخر)",
              code_of(local(old)) == 200 and code_of(f"{root}/stremio/{public}/manifest.json") == 404)
        api.down = True
        c, r = post("/api/stremio/lock", {"gate": "g1", "username": "u"})
        api.down = False
        check("تغيير القفل وStremio لا يردّ ← 502، والإضافة كما هي تعمل", c == 502 and code_of(local(old)) == 200, str(c))
        c, r = post("/api/stremio/lock", {"gate": "g1", "username": "u"})
        new = [a["transportUrl"] for a in ours("u@tv.ssouq.com")]
        check("«إيقاف الإضافة في الحسابات الأخرى»: رابطٌ جديد في الحساب مكان القديم", c == 200 and r.get("locked") is True and len(new) == 1
              and new[0] != old, json.dumps(r, ensure_ascii=False))
        check("والنسخة التي نُقلت لحسابٍ آخر (بالرابط القديم) تتوقف، والجديدة تعمل",
              code_of(local(old)) == 404 and code_of(local(new[0])) == 200 and code_of(local(new[0]).replace("manifest.json", "status.json")) == 200)
        c, r = post("/api/stremio/lock", {"gate": "g1", "username": "u"}, op2)
        check("حسابٌ آخر لا يغيّر قفلها", c == 404, str(c))
        c, r = post("/api/stremio/lock", {"gate": "g1", "username": "u"}, op3)
        check("ومن لم يُفتح له ← 403", c == 403)
        c, r = post("/api/stremio/lock", {"gate": "g1", "username": "nobody"})
        check("يوزرٌ بلا حساب ← 404", c == 404)

        print("== أكثر من بوابة في حساب Stremio واحد (مرح · كاسبر · فالكون…) ==")
        xt.users["k1"] = "kp"
        c, r = post("/api/stremio/link", {"gate": "g1", "username": "u", "line_gate": "g4", "line_username": "k1", "line_password": "kp"})
        names = [a["manifest"]["name"] for a in ours("u@tv.ssouq.com")]
        check("خطٌّ من بوابة كاسبر يُربط بحساب يوزر مرح: يدخل العميل بالإيميل نفسه", c == 200 and r.get("linked") is True
              and r.get("email") == "u@tv.ssouq.com" and r.get("password") == "NewPass9", json.dumps(r, ensure_ascii=False))
        check("وإضافته في الحساب نفسه بعد إضافة مرح، باسم سيرفرها", names == ["سمارت سوق · سمارت", "سمارت سوق · كاسبر"], str(names))
        k1m = ours("u@tv.ssouq.com")[1]["manifest"]
        root_m = ours("u@tv.ssouq.com")[0]
        n_series = sum(len(v) for v in mock_xtream.SERIES.values())
        check("إضافة الخط المرتبط بلا كتالوجات (محتواه في مكتبة صاحب الحساب الموحدة، فلا يتكرّر)، وبادئتها لها",
              k1m["catalogs"] == [] and S.ACCOUNTS not in k1m["types"]
              and set(k1m["idPrefixes"]).isdisjoint(root_m["manifest"]["idPrefixes"]), json.dumps(k1m["catalogs"]))
        check("والإضافتان تعملان", all(code_of(local(a["transportUrl"])) == 200 for a in ours("u@tv.ssouq.com")))
        k1_stream = next(r_ for r_ in k1m["resources"] if isinstance(r_, dict) and r_["name"] == "stream")
        k1_rec = next((x for x in A.all_records(d) if x.get("username") == "k1"), {})
        check("وتعرض إضافة الخط مصادره في أعمال المكتبة (بادئاتنا كلها)، ونسختها محفوظةٌ مع الخط",
              "sq" in k1_stream["idPrefixes"] and k1_rec.get("addon_v") == S.VERSION, json.dumps(k1_stream, ensure_ascii=False))
        get_json = lambda url: json.loads(urllib.request.urlopen(url, timeout=60).read())
        root_tu, k1_tu = (local(a["transportUrl"]) for a in ours("u@tv.ssouq.com"))
        mv0 = get_json(root_tu.replace("manifest.json", "catalog/movie/sq_movies.json"))["metas"][0]["id"]
        st_root = [x["name"] for x in get_json(root_tu.replace("manifest.json", f"stream/movie/{quote(mv0, safe='')}.json"))["streams"]]
        st_k1 = [x["name"] for x in get_json(k1_tu.replace("manifest.json", f"stream/movie/{quote(mv0, safe='')}.json"))["streams"]]
        check("لكل بوابةٍ زرّها فوق قائمة التشغيل: صاحب الحساب «تلقائي» ومصادر خطّه، وإضافة كاسبر مصادر كاسبر في العمل نفسه",
              st_root[:1] == ["سمارت سوق"] and "كاسبر" not in st_root and st_k1 and set(st_k1) == {"كاسبر"},
              json.dumps([st_root, st_k1], ensure_ascii=False))
        rcats = {c["type"]: c for c in root_m["manifest"]["catalogs"] if not c["id"].startswith(S.CAT_PREFIX) and c["id"] not in S.YEARS.values()}
        sopts = next((e["options"] for e in rcats["series"]["extra"] if e["name"] == "genre"), [])
        check("وإضافة صاحب الحساب أُعيدت بالمكتبة الموحدة: «الحسابات» أولها، والصفوف باسم المتجر، و«مصدر: …» لكل خط",
              root_m["manifest"]["catalogs"][0]["type"] == S.ACCOUNTS and rcats["series"]["name"] == f"سمارت سوق ({n_series})"
              and sopts[-2:] == ["مصدر: سمارت", "مصدر: كاسبر"], json.dumps([c["name"] for c in root_m["manifest"]["catalogs"]], ensure_ascii=False) + str(sopts[-3:]))
        cat_url = lambda a, kind, cid, extra="": local(a["transportUrl"]).replace("manifest.json", f"catalog/{kind}/{cid}{extra}.json")
        get = lambda u: json.loads(urllib.request.urlopen(u, timeout=30).read())
        ser = get(cat_url(root_m, "series", "sq_series"))["metas"]
        check("مكتبةٌ واحدة: كل مسلسلٍ مرةً واحدة وإن كان في الخطّين، ومصادره في وصفه",
              len(ser) == n_series and len({m["id"] for m in ser}) == len(ser)
              and all(re.search(r"المصادر: سمارت( \(مدبلج\))? · كاسبر", m.get("description", "")) for m in ser)
              and "المصادر: سمارت (مدبلج) · كاسبر (مدبلج)" in next(m["description"] for m in ser if m["name"] == "المؤسس عثمان"),
              str(len(ser)) + " " + json.dumps([(m["name"], m.get("description", "")[-40:]) for m in ser], ensure_ascii=False)[:600])
        found = get(cat_url(root_m, "series", "sq_series", "/search=" + quote("breaking", safe="")))["metas"]
        check("والبحث في كل الحسابات معًا بلا تكرار", [m["name"] for m in found] == ["Breaking Bad"], str([m["name"] for m in found]))
        check("وطلب كتالوجات إضافة الخط ← فارغة (صفوفها القديمة تختفي من Stremio)",
              get(cat_url(ours("u@tv.ssouq.com")[1], "series", "sq_series"))["metas"] == [])
        gid = next(m["id"] for m in ser if m["name"] == "Game of Thrones")
        gm = get(local(root_m["transportUrl"]).replace("manifest.json", f"meta/series/{quote(gid, safe='')}.json"))["meta"]
        chips = [l["name"] for l in gm.get("links", []) if l["category"] == "المصادر"]
        check("صفحة المسلسل: مصادره ببوابتها ومواسمها وحلقاتها، وحلقاته مرةً واحدة",
              len(chips) == 2 and chips[0].startswith("سمارت · ") and "حلقات" in chips[0] and chips[1].startswith("كاسبر · ")
              and len(gm["videos"]) == len({(v["season"], v["episode"]) for v in gm["videos"]}) == 6, str(chips))
        ep = gm["videos"][0]["id"]
        sts = get(local(root_m["transportUrl"]).replace("manifest.json", f"stream/series/{quote(ep, safe='')}.json"))["streams"]
        k1_sts = get(local(ours("u@tv.ssouq.com")[1]["transportUrl"]).replace("manifest.json", f"stream/series/{quote(ep, safe='')}.json"))["streams"]
        check("الحلقة: «تلقائي» أولًا ثم مصدر صاحب الحساب، ومصدر كاسبر من إضافته (زرٌّ باسمها)", [x["name"] for x in sts] == ["سمارت سوق", "سمارت"]
              and "/play/series/" in sts[0]["url"] and [x["name"] for x in k1_sts] == ["كاسبر"] and "/series/k1/kp/" in location(local(k1_sts[0]["url"]))
              and "/k1/kp/" not in json.dumps([sts, k1_sts]),
              json.dumps([[x["name"] for x in sts], [x["name"] for x in k1_sts]], ensure_ascii=False))
        c, r = post("/api/stremio/accounts?gate=g4", None)
        k = next((a for a in r.get("accounts", []) if a["username"] == "k1"), {})
        check("الخط في قائمة بوابته: مرتبطٌ، وخطوط الحساب كلها للتنقّل", k.get("linked") is True and k.get("email") == "u@tv.ssouq.com"
              and [(l["gate"], l["username"], l["main"], l["self"]) for l in k.get("lines", [])] == [("g1", "u", True, False), ("g4", "k1", False, True)]
              and k["lines"][1]["gate_name"] == "بوابة كاسبر", json.dumps(k, ensure_ascii=False)[:300])
        c, r = post("/api/stremio/accounts?gate=g1", None)
        u0 = next(a for a in r["accounts"] if a["username"] == "u")
        check("وعلى بطاقة صاحب الحساب كذلك", [l["username"] for l in u0["lines"]] == ["u", "k1"] and u0["lines"][0]["self"] and not u0["linked"])
        c, r = post("/api/stremio/link", {"gate": "g1", "username": "u", "line_gate": "g4", "line_username": "k1", "line_password": "kp"})
        check("ربطه مرةً ثانية: كما هو", c == 200 and r.get("linked") is False and len(ours("u@tv.ssouq.com")) == 2)
        c, r = post("/api/stremio/account", {"gate": "g4", "username": "k1", "password": "kp"})
        check("ونسخ حساب الخط: حساب صاحبه", c == 200 and r.get("email") == "u@tv.ssouq.com" and r.get("created") is False)
        c, r = post("/api/stremio/link", {"gate": "g1", "username": "u", "line_gate": "g2", "line_username": "zz", "line_password": "p"})
        check("خطٌّ ثانٍ من السيرفر نفسه ← 400 (إضافتاهما تتزاحمان)", c == 400 and "السيرفر نفسه" in r.get("error", ""), json.dumps(r, ensure_ascii=False))
        c, r = post("/api/stremio/link", {"gate": "g4", "username": "k1", "line_gate": "g1", "line_username": "late", "line_password": "lp"})
        check("ويوزرٌ له حسابه ← 400", c == 400 and "حساب Stremio آخر" in r.get("error", ""), json.dumps(r, ensure_ascii=False))
        c, r = post("/api/stremio/link", {"gate": "g1", "username": "u", "line_gate": "g1", "line_username": "k2", "line_password": "x"}, op2)
        check("وحسابٌ آخر لا يربط بحسابات غيره", c == 400 and "لا حساب" in r.get("error", ""), str(c))
        api.users["u@tv.ssouq.com"] = "Third3"
        c, r = post("/api/stremio/password", {"gate": "g1", "username": "u", "password": "Third3"})
        c, r = post("/api/stremio/accounts?gate=g4", None)
        check("كلمة مرورٍ جديدة للحساب تصل خطوطه كلها", next(a for a in r["accounts"] if a["username"] == "k1")["password"] == "Third3")
        c, r = post("/api/stremio/lock", {"gate": "g4", "username": "k1"})
        check("وتغيير رابط إضافة الخط يُبقيها مكانها (وبلا «الحسابات»)", c == 200 and [a["manifest"]["name"] for a in ours("u@tv.ssouq.com")] == names
              and S.ACCOUNTS not in ours("u@tv.ssouq.com")[1]["manifest"]["types"])

        print("== «التصنيفات»: تصنيفات سمارت سوق لكل البوابات ==")
        c, r = post("/api/stremio/categories", None)
        check("الافتراضية، ومعاينتها على حسابٍ من الحسابات قوائمه في الذاكرة", c == 200 and not r.get("edited")
              and [x["name"] for x in r.get("cats", [])][:4] == ["تركي مترجم يعرض الآن", "تركي مدبلج يعرض الآن", "رمضان", "تركي"] and r.get("preview", {}).get("series", {}).get("total", 0) > 0
              and r.get("sample"), json.dumps({k: r.get(k) for k in ("edited", "sample", "preview")}, ensure_ascii=False)[:300])
        mine = r["cats"] + [{"id": "s_pick", "kind": "series", "name": "مختارات", "keys": "أجنبية", "home": True}]
        c, r = post("/api/stremio/categories", {"cats": mine, "preview": True})
        check("المعاينة قبل الحفظ: أعداد التصنيف الجديد، بلا حفظ", c == 200 and r["preview"]["series"]["counts"].get("s_pick", 0) > 0
              and not r.get("edited") and r.get("saved") is False, json.dumps(r.get("preview", {}).get("series"), ensure_ascii=False)[:200])
        c, r = post("/api/stremio/categories", {"cats": [{"kind": "series", "name": "أ"}, {"kind": "series", "name": "أ"}]})
        check("اسمٌ مكرّر في النوع ← 400 برسالة", c == 400 and "مكرّر" in r.get("error", ""), str(r))
        c, r = post("/api/stremio/categories", {"cats": mine})
        check("الحفظ لحساب الأداة", c == 200 and r.get("edited") and any(x["name"] == "مختارات" for x in r["cats"]))
        get_json = lambda url: json.loads(urllib.request.urlopen(url, timeout=60).read())
        row = get_json(local(ours("u@tv.ssouq.com")[0]["transportUrl"]).replace("manifest.json", f"catalog/series/{S.CAT_PREFIX}s_pick.json"))["metas"]
        check("ومحتوى صفّه من الخادم فورًا (قبل تحديث الإضافة)", len(row) > 0, str(len(row)))
        c, r = post("/api/stremio/categories", None, op3)
        check("ومن لم يُفتح له Stremio ← 403", c == 403)
        c, r = post("/api/stremio/categories", None, op2)
        check("وحساب أداةٍ آخر: تصنيفاته هو (الافتراضية)", c == 200 and not r.get("edited"))

        print("== «تحديث الإضافة لكل الحسابات» ==")
        c, r = post("/api/stremio/update-all", None)
        n_accts = r.get("accounts", 0)
        check("عدد حسابات Stremio للعميل (الحساب مرةً مهما كثرت خطوطه)، وبلا عمليةٍ بعد", c == 200 and n_accts >= 2 and r.get("job") is None,
              json.dumps(r, ensure_ascii=False))
        col = api.collections["u@tv.ssouq.com"]
        others_before = [a["manifest"]["name"] for a in col if not a.get("manifest", {}).get("id", "").startswith("com.ssouq.")]
        for a in ours("u@tv.ssouq.com"):                  # إضافتان من نسخةٍ قديمة (قبل المكتبة الموحدة)
            a["manifest"] = {**a["manifest"], "version": "1.0.0", "catalogs": [{"type": "movie", "id": "sq_movies", "name": "أفلام · قديم"}]}
        c, r = post("/api/stremio/update-all", {})
        check("يبدأ في الخلفية", c == 200 and r.get("ok") and r["job"]["total"] == n_accts, json.dumps(r, ensure_ascii=False)[:200])
        for _ in range(200):
            c, r = post("/api/stremio/update-all", None)
            if not (r.get("job") or {}).get("running"):
                break
            time.sleep(0.1)
        j = r.get("job") or {}
        check("وينتهي: كل الحسابات حُدّثت بلا تعثّر، وكل خطوطها", not j.get("running") and j.get("done") == j.get("total") == n_accts
              and j.get("changed") == n_accts and j.get("failed") == [] and j.get("lines", 0) > n_accts, json.dumps(j, ensure_ascii=False))
        root_m, k1m = ours("u@tv.ssouq.com")[0]["manifest"], ours("u@tv.ssouq.com")[1]["manifest"]
        check("إضافة صاحب الحساب بأحدث نسخة: المكتبة الموحدة و«الحسابات»", root_m["version"] == S.VERSION
              and root_m["catalogs"][0]["type"] == S.ACCOUNTS and next(c for c in root_m["catalogs"] if c["id"] == "sq_series")["name"].startswith("سمارت سوق ("),
              json.dumps([c["name"] for c in root_m["catalogs"]], ensure_ascii=False))
        check("وإضافة الخط المرتبط بلا كتالوجات", k1m["version"] == S.VERSION and k1m["catalogs"] == [])
        check("وصفوف الرئيسية بتصنيفات العميل المحفوظة («مختارات - المسلسلات»)",
              any(c_["id"] == f"{S.CAT_PREFIX}s_pick" and c_["name"] == "مختارات" for c_ in root_m["catalogs"]),
              json.dumps([c_["name"] for c_ in root_m["catalogs"]], ensure_ascii=False))
        c, r = post("/api/stremio/categories", {"reset": True})
        check("و«إعادة التصنيفات الافتراضية»", c == 200 and not r.get("edited") and not any(x["name"] == "مختارات" for x in r["cats"]))
        col = api.collections["u@tv.ssouq.com"]
        check("كلٌّ في مكانه، والإضافات الأخرى كما هي", [a["manifest"]["name"] for a in ours("u@tv.ssouq.com")] == names
              and [a["manifest"]["name"] for a in col if not a.get("manifest", {}).get("id", "").startswith("com.ssouq.")] == others_before,
              str([a["manifest"]["name"] for a in col]))
        check("وخرج من كل الجلسات", not api.sessions)
        api.down = True
        c, r = post("/api/stremio/update-all", {})
        for _ in range(200):
            c, r = post("/api/stremio/update-all", None)
            if not (r.get("job") or {}).get("running"):
                break
            time.sleep(0.1)
        api.down = False
        check("Stremio لا يردّ: كل حسابٍ في «ما تعذّر» بإيميله وسببه (لا يتوقف)", len(r["job"]["failed"]) == n_accts and r["job"]["changed"] == 0
              and all(f.get("email") and f.get("error") for f in r["job"]["failed"]), json.dumps(r["job"], ensure_ascii=False)[:200])
        c, r = post("/api/stremio/update-all", {}, op3)
        check("ومن لم يُفتح له Stremio ← 403", c == 403)

        c, r = post("/api/stremio/create", {"gate": "g2", "package_id": "167", "link_gate": "g1", "link_username": "u"})
        check("«خطٌّ جديد» من سيرفرٍ في الحساب ← 400 قبل إنشاء اليوزر", c == 400 and "سيرفر هذه البوابة" in r.get("error", ""), json.dumps(r, ensure_ascii=False))
        c, r = post("/api/stremio/create", {"gate": "g5", "package_id": "167", "link_gate": "g1", "link_username": "late"})
        acc5, line5 = r.get("stremio_account") or {}, r.get("line") or {}
        check("«خطٌّ جديد»: يوزرٌ في بوابة فالكون يُنشأ ويُربط بحساب late", c == 200 and r.get("ok") and acc5.get("email") == "late@tv.ssouq.com"
              and acc5.get("linked") is True and len(ours("late@tv.ssouq.com")) == 2   # (هوست g5 هو هوست كاسبر هنا: اسمه منه)
              and ours("late@tv.ssouq.com")[1]["manifest"]["name"] == "سمارت سوق · كاسبر",
              json.dumps(r, ensure_ascii=False)[:200])
        c, r = post("/api/stremio/create", {"gate": "g5", "package_id": "167", "link_gate": "g1", "link_username": "nobody"})
        check("وحسابٌ لا يوجد ← 400 قبل إنشاء اليوزر", c == 400 and "لا حساب" in r.get("error", ""))

        c, r = post("/api/stremio/unlink", {"gate": "g1", "username": "u"})
        check("صاحب الحساب لا يُفصل", c == 400, str(c))
        c, r = post("/api/stremio/unlink", {"gate": "g4", "username": "k1"})
        check("«فصل الخط»: تُسقط إضافته من الحساب ويُنسى", c == 200 and [a["manifest"]["name"] for a in ours("u@tv.ssouq.com")] == ["سمارت سوق · سمارت"])
        c, r = post("/api/stremio/accounts?gate=g4", None)
        check("ويخرج من قائمة بوابته", r.get("accounts") == [] and next(g for g in r["gates"] if g["id"] == "g4")["count"] == 0)
        c, r = post("/api/stremio/unlink", {"gate": "g4", "username": "k1"}, op3)
        check("ومن لم يُفتح له ← 403", c == 403)

        print("== تغيير الهوست لكل الحسابات دفعةً واحدة ==")
        new_host = xt_host.replace("127.0.0.1", "localhost")
        c, r = post("/api/stremio/hosts", None)
        h127 = next((h for h in r.get("hosts", []) if h["key"] == "127.0.0.1"), {})
        check("هوستات الحسابات بعددها وبواباتها", c == 200 and h127.get("host") == xt_host and h127.get("count", 0) >= 5
              and "بوابة مرح" in h127.get("gates", []) and h127.get("to") == "", json.dumps(r, ensure_ascii=False)[:200])
        tu = local(ours("u@tv.ssouq.com")[0]["transportUrl"])

        def stream_url():
            """أول مصدرٍ لأول فيلم ← (معرّفه، رابط اللوحة الذي يحوّل إليه رابطه على خادمنا)."""
            meta_id = json.loads(urllib.request.urlopen(tu.replace("manifest.json", "catalog/movie/sq_movies.json"), timeout=30).read())["metas"][0]["id"]
            st = json.loads(urllib.request.urlopen(tu.replace("manifest.json", f"stream/movie/{meta_id}.json"), timeout=30).read())
            return meta_id, location(st["streams"][0]["url"])
        id0, url0 = stream_url()
        c, r = post("/api/stremio/host", {"from": "127.0.0.1", "to": "http://127.0.0.1:1"})
        check("هوستٌ جديد لا يقبل يوزرات الحسابات ← 400 ولا يُحفظ", c == 400 and "لم يقبل" in r.get("error", ""), json.dumps(r, ensure_ascii=False))
        c, r = post("/api/stremio/host", {"from": "127.0.0.1", "to": "ftp://x"})
        check("وهوستٌ غير صالح ← 400", c == 400 and "غير صالح" in r.get("error", ""))
        c, r = post("/api/stremio/host", {"from": "127.0.0.1", "to": new_host})
        check("«تغيير الهوست»: كل حسابات الهوست دفعةً واحدة", c == 200 and r.get("count") == h127["count"] and r.get("to") == new_host
              and next(h for h in r["hosts"] if h["key"] == "127.0.0.1")["to"] == new_host, json.dumps(r, ensure_ascii=False)[:200])
        id1, url1 = stream_url()
        check("فالإضافة نفسها (بلا إعادة تثبيت) تعمل من الجديد، ومعرّفاتها كما هي", url1.startswith(new_host + "/movie/") and id1 == id0
              and url0.startswith(xt_host + "/movie/"), f"{url0} → {url1}")
        c, r = post("/api/stremio/accounts?gate=g1", None)
        check("وانتهاء اليوزرات يُقرأ من الجديد", c == 200 and post("/api/stremio/refresh", {"gate": "g1"})[1].get("checked", 0) >= 1)
        c, r = post("/api/stremio/host", {"from": "127.0.0.1", "to": "http://127.0.0.1:1", "force": True})
        check("ويُحفظ هوستٌ لم يُجرَّب إن أُكّد", c == 200 and r.get("to") == "http://127.0.0.1:1")
        c, r = post("/api/stremio/host", {"from": "127.0.0.1", "to": ""})
        check("«إلغاء التحويل»: تعود إلى هوستها", c == 200 and r.get("to") == "" and stream_url()[1].startswith(xt_host + "/movie/"))
        c, r = post("/api/stremio/host", {"from": "127.0.0.1", "to": new_host}, op2)
        check("حسابٌ آخر لا يحوّل حسابات غيره", c == 400 and "لا حسابات" in r.get("error", ""), json.dumps(r, ensure_ascii=False))
        c, r = post("/api/stremio/host", {"from": "127.0.0.1", "to": new_host}, op3)
        check("ومن لم يُفتح له ← 403", c == 403)

        print("== حساب Stremio بإيميلٍ وكلمة مرورٍ تختارهما ==")
        xt.users["k3"], xt.users["u9"] = "k3p", "u9p"
        c, r = post("/api/stremio/custom", {"email": "Ahmed.Family", "password": "Fam12345", "line_gate": "g4",
                                            "line_username": "k3", "line_password": "k3p"})
        check("إيميلٌ تختاره وكلمة مروره، وأول خطوطه يوزرٌ موجود في بوابة", c == 200 and r.get("email") == "ahmed.family@tv.ssouq.com"
              and r.get("password") == "Fam12345" and api.users.get("ahmed.family@tv.ssouq.com") == "Fam12345"
              and [a["manifest"]["name"] for a in ours("ahmed.family@tv.ssouq.com")] == ["سمارت سوق · كاسبر"], json.dumps(r, ensure_ascii=False))
        c, r = post("/api/stremio/accounts?gate=g4", None)
        k3 = next((a for a in r.get("accounts", []) if a["username"] == "k3"), {})
        check("ويظهر في بوابة خطه بإيميله وكلمة مروره، مقفلًا", k3.get("email") == "ahmed.family@tv.ssouq.com" and k3.get("password") == "Fam12345"
              and k3.get("locked") is True, json.dumps(k3, ensure_ascii=False)[:200])
        c, r = post("/api/stremio/link", {"gate": "g4", "username": "k3", "line_gate": "g1", "line_username": "u9", "line_password": "u9p"})
        check("وتُربط به خطوط بواباتٍ أخرى", c == 200 and r.get("linked") is True and r.get("email") == "ahmed.family@tv.ssouq.com"
              and [a["manifest"]["name"] for a in ours("ahmed.family@tv.ssouq.com")] == ["سمارت سوق · كاسبر", "سمارت سوق · سمارت"])
        with smtplib.SMTP("127.0.0.1", MAIL_PORT, timeout=10) as sm:
            sm.mail("no-reply@strem.io")
            check("وبريده يصل خادمنا", sm.rcpt("ahmed.family@tv.ssouq.com")[0] == 250)
        bad = [post("/api/stremio/custom", {"email": e, "password": p_, "line_gate": "g1", "line_username": "u9b", "line_password": "x"})
               for e, p_ in (("a b", "Fam12345"), ("x@gmail.com", "Fam12345"), ("ok.name", "123"), ("Ahmed.Family", "Fam12345"))]
        check("إيميلٌ لا يصلح، أو على دومينٍ آخر، أو كلمة مرورٍ قصيرة، أو إيميلٌ مستخدمٌ عندنا ← 400",
              [c for c, _ in bad] == [400] * 4 and "دومين" in bad[1][1]["error"] and "6" in bad[2][1]["error"] and "لحسابٍ آخر" in bad[3][1]["error"],
              json.dumps([r_.get("error") for _, r_ in bad], ensure_ascii=False))
        c, r = post("/api/stremio/custom", {"email": "newname", "password": "Fam12345", "line_gate": "g1", "line_username": "late", "line_password": "lp"})
        check("ويوزرٌ له حسابٌ من قبل ← 400 (يُربط بحسابه بدل ذلك)", c == 400 and "من قبل" in r.get("error", ""), json.dumps(r, ensure_ascii=False))
        api.users["taken@tv.ssouq.com"] = "Someone1"
        xt.users["u8"] = "u8p"
        c, r = post("/api/stremio/custom", {"email": "taken", "password": "Fam12345", "line_gate": "g1", "line_username": "u8", "line_password": "u8p"})
        check("إيميلٌ مسجّلٌ في Stremio بكلمة مرورٍ أخرى ← 502 برسالته ولا يُحفظ", c == 502 and "كلمة مرورٍ أخرى" in r.get("error", "")
              and post("/api/stremio/account", {"gate": "g1", "username": "u8", "password": "u8p"})[1].get("email") == "u8@tv.ssouq.com",
              json.dumps(r, ensure_ascii=False))
        c, r = post("/api/stremio/create", {"gate": "g5", "package_id": "167", "custom_email": "a b", "custom_password": "Fam12345"})
        check("«خطٌّ جديد» بإيميلٍ لا يصلح ← 400 قبل إنشاء اليوزر", c == 400 and "اسم الإيميل" in r.get("error", ""))
        c, r = post("/api/stremio/create", {"gate": "g5", "package_id": "167", "custom_email": "family2", "custom_password": "Fam54321"})
        sa = r.get("stremio_account") or {}
        check("«خطٌّ جديد»: يوزرٌ في البوابة وحسابه بالإيميل المختار", c == 200 and sa.get("email") == "family2@tv.ssouq.com"
              and sa.get("password") == "Fam54321" and api.users.get("family2@tv.ssouq.com") == "Fam54321", json.dumps(r, ensure_ascii=False)[:200])
        c, r = post("/api/stremio/custom", {"email": "x9", "password": "Fam12345", "line_gate": "g1", "line_username": "u9b", "line_password": "x"}, op3)
        check("ومن لم يُفتح له ← 403", c == 403)

        print("== إضافاتٌ أخرى (مثل AIOMetadata) في الحسابات الجديدة والسابقة ==")
        aio_srv = mock_addon.serve()
        threading.Thread(target=aio_srv.serve_forever, daemon=True).start()
        aio = f"http://127.0.0.1:{aio_srv.server_address[1]}/aio/manifest.json"
        mine = lambda: sorted({e.lower() for e in api.collections if e.endswith("@tv.ssouq.com") and e != "taken@tv.ssouq.com"})
        has_aio = lambda e: [a["manifest"]["id"] for a in api.collections.get(e, [])].count("community.aiometadata")

        def wait_job():
            for _ in range(200):
                c_, r_ = post("/api/stremio/extras", None)
                if not (r_.get("job") or {}).get("running"):
                    return r_
                time.sleep(0.1)
            return r_
        c, r = post("/api/stremio/extras", {"action": "add", "url": f"http://127.0.0.1:{aio_srv.server_address[1]}/needs/manifest.json"})
        check("إضافةٌ تحتاج إعدادًا ← 400 برسالته ورابط صفحة إعدادها", c == 400 and "تحتاج إعدادًا" in r.get("error", "")
              and r.get("configure", "").endswith("/needs/configure"), json.dumps(r, ensure_ascii=False))
        c, r = post("/api/stremio/extras", {"action": "add", "url": local(ours("u@tv.ssouq.com")[0]["transportUrl"])})
        check("وإضافتنا نفسها ← 400", c == 400 and "إضافتنا" in r.get("error", ""), json.dumps(r, ensure_ascii=False))
        c, r = post("/api/stremio/extras", {"action": "add", "url": aio})
        aid = r.get("added")
        check("«إضافة»: تُقرأ وتُحفظ باسمها، ومعها عدد الحسابات", c == 200 and [x["name"] for x in r.get("extras", [])] == ["AIOMetadata"]
              and r.get("accounts") == len(mine()), json.dumps(r, ensure_ascii=False)[:200])
        c, r = post("/api/stremio/extras", {"action": "apply", "id": aid})
        check("«تثبيت في كل الحسابات» يبدأ في الخلفية", c == 200 and (r.get("job") or {}).get("total") == len(mine()), json.dumps(r.get("job"), ensure_ascii=False))
        r = wait_job()
        j = r.get("job") or {}
        check("وتنتهي: كل الحسابات السابقة فيها الإضافة مرةً واحدة", j.get("running") is False and j.get("done") == j.get("total") == len(mine())
              and j.get("failed") == [] and all(has_aio(e) == 1 for e in mine()), json.dumps(j, ensure_ascii=False))
        col = [a["manifest"]["id"] for a in api.collections["ahmed.family@tv.ssouq.com"]]
        check("بعد إضافاتنا مباشرةً (قبل Cinemeta)", col.index("community.aiometadata") == 2 and col[0].startswith("com.ssouq.") and col[1].startswith("com.ssouq."), str(col))
        c, r = post("/api/stremio/extras", {"action": "apply", "id": aid})
        r = wait_job()
        check("وإعادتها لا تكرّر شيئًا", r["job"]["changed"] == 0 and all(has_aio(e) == 1 for e in mine()))
        xt.users["n1"] = "n1p"
        c, r = post("/api/stremio/account", {"gate": "g1", "username": "n1", "password": "n1p"})
        check("وكل حسابٍ جديد تأتيه معه", c == 200 and has_aio("n1@tv.ssouq.com") == 1)
        c, r = post("/api/stremio/extras", {"action": "apply", "id": aid, "remove": True})
        r = wait_job()
        check("«إسقاط من كل الحسابات»", r["job"]["op"] == "remove" and all(has_aio(e) == 0 for e in mine()), json.dumps(r["job"], ensure_ascii=False))
        c, r = post("/api/stremio/extras", {"action": "remove", "id": aid})
        xt.users["n2"] = "n2p"
        post("/api/stremio/account", {"gate": "g1", "username": "n2", "password": "n2p"})
        check("و«حذف من القائمة»: لا تأتي الجديدة بعده", c == 200 and r.get("extras") == [] and has_aio("n2@tv.ssouq.com") == 0)
        c, r = post("/api/stremio/extras", {"action": "add", "url": aio, "apply": True})
        r = wait_job()
        check("«إضافة لجميع اليوزرات»: تُضاف وتُثبَّت في كل الحسابات بطلبٍ واحد", c == 200 and r["job"]["op"] == "install"
              and r["job"]["done"] == len(mine()) and all(has_aio(e) == 1 for e in mine()), json.dumps(r.get("job"), ensure_ascii=False))
        c, r = post("/api/stremio/extras", None, op2)
        check("وقائمة كل عميلٍ له وحده", c == 200 and r.get("extras") == [] and r.get("accounts") == 0)
        c, r = post("/api/stremio/extras", {"action": "add", "url": aio}, op3)
        check("ومن لم يُفتح له ← 403", c == 403)
        aio_srv.shutdown()

        print("== رابط لوحةٍ يتغيّر للجميع (مثل مرح) ==")
        c, r = post("/api/stremio/panels", None)
        g1p = next((g for g in r.get("gates", []) if g["id"] == "g1"), {})
        n127 = next((h["count"] for h in post("/api/stremio/hosts", None)[1]["hosts"] if h["key"] == "127.0.0.1"), 0)
        check("روابط اللوحات: كل بوابة بهوستها وعدد حسابات سيرفرها", c == 200 and g1p.get("host") == xt_host and g1p.get("count") == n127 > 0,
              json.dumps(r, ensure_ascii=False)[:200])
        c, r = post("/api/stremio/panel-host", {"gate": "g1", "host": "http://127.0.0.1:1"})
        check("رابطٌ لا يقبل يوزراتها ← 400 ولا يتغيّر شيء", c == 400 and "لم يقبل" in r.get("error", "")
              and post("/api/mygates", None)[1]["gates"][0]["host"] == xt_host, json.dumps(r, ensure_ascii=False))
        c, r = post("/api/stremio/panel-host", {"gate": "g1", "host": "ftp://x"})
        check("ورابطٌ غير صالح ← 400", c == 400 and "غير صالح" in r.get("error", ""))
        c, r = post("/api/stremio/panel-host", {"gate": "nope", "host": new_host})
        check("وبوابةٌ ليست له ← 400", c == 400)
        c, r = post("/api/stremio/panel-host", {"gate": "g1", "host": new_host})
        mg = {g["id"]: g.get("host") for g in post("/api/mygates", None)[1]["gates"]}
        check("«تغيير للجميع»: البوابة (ومثيلاتها على السيرفر نفسه) بالرابط الجديد لليوزرات الجديدة", c == 200 and r.get("gates_changed") == 3
              and mg["g1"] == mg["g2"] == mg["g3"] == new_host, json.dumps(mg))
        check("وكل حسابات سيرفرها تعمل منه فورًا بلا إعادة تثبيت", r.get("count") == n127 and stream_url()[1].startswith(new_host + "/movie/"),
              json.dumps(r, ensure_ascii=False)[:160])
        c, r = post("/api/stremio/panel-host", {"gate": "g1", "host": new_host}, op3)
        check("ومن لم يُفتح له ← 403", c == 403)
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
          and rows[0].get("stremio_pass") == "Third3" and "stremio_email" not in rows[1])   # كلمة المرور بعد تغييرها
    check("وبلا رابط تثبيتٍ عامّ (إضافته مقفلةٌ على حسابه)، ويوزرٌ بلا حساب برابطه", "stremio" not in rows[0]
          and rows[1].get("stremio", "").startswith("https://guide.ssouq.com/stremio/"))
    shutil.rmtree(d, ignore_errors=True)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def location(url):
    """رابط مصدرٍ على خادمنا ← رابط اللوحة الذي يحوّل إليه (بلا اتّباعه)."""
    try:
        urllib.request.build_opener(_NoRedirect).open(url, timeout=30)
    except urllib.error.HTTPError as e:
        return e.headers.get("Location", "")
    return ""


def update_job_unit():
    print("== «تحديث الإضافة لكل الحسابات»: مهلةٌ لكل خط، وما يجري الآن ==")
    import xm_lines as X
    check("‏_in_time: القيمة في المهلة", X._in_time(lambda: 7, 2) == 7)
    try:
        X._in_time(lambda: time.sleep(1.5), 0.2)
        late = False
    except TimeoutError:
        late = True
    check("وبعدها ← TimeoutError (والخيط يكمل في الخلفية)", late)
    try:
        X._in_time(lambda: 1 / 0, 2)
        err = False
    except ZeroDivisionError:
        err = True
    check("وخطؤها يصل كما هو", err)
    d = tempfile.mkdtemp(prefix="stremio_upd_")
    keep = {k: getattr(X, k) for k in ("DATA_DIR", "stremio_update_groups", "stremio_descriptor", "find_gate", "STREMIO_UPDATE_LINE_SECS")}
    keep_a = {k: getattr(X.stremio_accounts, k) for k in ("login", "install", "logout", "note")}
    installed = []
    try:
        X.DATA_DIR = d
        X.STREMIO_UPDATE_LINE_SECS = 0.4
        X.stremio_update_groups = lambda acct_id: {
            "a@x": [{"email": "a@x", "password": "p", "token": "T1", "gate": "g1", "username": "u1", "host": "h"},
                    {"email": "a@x", "password": "p", "token": "SLOW", "gate": "g2", "username": "u2", "host": "h", "linked_to": "k"}],
            "b@x": [{"email": "b@x", "password": "p", "token": "T3", "gate": "g1", "username": "u3", "host": "h"}]}
        X.find_gate = lambda acct, gid: {"id": gid, "name": {"g1": "سمارت", "g2": "كاسبر"}[gid], "host": "http://h"}

        def desc(tok, host, gate=None, accounts=None, patient=True):
            built = []

            def make():
                if tok == "SLOW":
                    time.sleep(1.5)                       # لوحةٌ بطيئة
                built.append(True)
                return {"manifest": {"id": tok}}
            return make, built
        X.stremio_descriptor = desc
        X.stremio_accounts.login = lambda email, pw: "auth"
        X.stremio_accounts.install = lambda auth, desc, first=False, extras=(): installed.append(desc["manifest"]["id"])
        X.stremio_accounts.logout = lambda auth: None
        X.stremio_accounts.note = lambda *a, **k: True
        X.stremio_update_all({"id": "acctT"})
        seen = []
        for _ in range(100):
            j = X.stremio_update_job("acctT")
            seen += [a["text"] for a in j.get("active", [])]
            if not j["running"]:
                break
            time.sleep(0.05)
        check("ما يجري الآن في كل حساب (تعرضه الصفحة)", any("«كاسبر»" in t for t in seen), str(seen[:3]))
        check("خطٌّ لوحته بطيئة يُتخطّى بعد المهلة ويُذكر بسببه، وباقي الخطوط والحسابات تُثبَّت",
              not j["running"] and j["done"] == 2 and j["lines"] == 2 and j["changed"] == 1 and sorted(installed) == ["T1", "T3"]
              and len(j["failed"]) == 1 and j["failed"][0]["email"] == "a@x" and "«كاسبر»: لوحتها بطيئة" in j["failed"][0]["error"]
              and j["active"] == [], json.dumps(j, ensure_ascii=False)[:300])
    finally:
        for k, v in keep.items():
            setattr(X, k, v)
        for k, v in keep_a.items():
            setattr(X.stremio_accounts, k, v)
        shutil.rmtree(d, ignore_errors=True)


def main():
    unit()
    update_job_unit()
    against_mocks()
    through_server()
    print("\n----------------------------------------")
    print("Result: \033[32m%d passed\033[0m, %s" % (_p, ("\033[31m%d failed\033[0m" % _f) if _f else "0 failed"))
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

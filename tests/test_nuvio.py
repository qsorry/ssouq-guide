#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
حسابات Nuvio الجاهزة (‏nuvio_accounts.py ومساراتها في xm_lines): كحساب Stremio الجاهز — الإيميل اليوزر @tv.ssouq.com
وكلمة المرور باسورده (و«A» إن رفضها Nuvio) — وإضافتنا أول قائمة إضافاته وإضافاته الأخرى باقية، ورابطها وردودها بلا بيانات
Xtream، و«تحديث الإضافة» و«إلغاء التفعيل» و«إعادة الربط» — مقابل خادم Nuvio وهمي بواجهة api.nuvio.tv نفسها (‏tests/mock_nuvio.py) وسيرفر Xtream وهمي، بلا إنترنت.

    python tests/test_nuvio.py
"""
import http.cookiejar
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import quote, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import mock_nuvio  # noqa: E402
import mock_xtream  # noqa: E402
import nuvio_accounts as N  # noqa: E402
import stremio_addon as S  # noqa: E402

PORT = int(os.environ.get("NUVIO_TEST_PORT", "9596"))
XUSER, XPASS = "c0505xyz", "SecretPw9z"          # بيانات Xtream — لا تظهر في رابط الإضافة ولا في ردودها
_p = _f = 0


def check(label, cond, extra=""):
    global _p, _f
    if cond:
        _p += 1
        print("  \033[32mPASS\033[0m  " + label + (("  (%s)" % extra) if extra else ""))
    else:
        _f += 1
        print("  \033[31mFAIL\033[0m  " + label + (("  (%s)" % extra) if extra else ""))


def raises(fn, kind):
    try:
        fn()
    except kind as e:
        return str(e) or True
    return False


def use(srv):
    N.BACKEND = f"http://127.0.0.1:{srv.server_address[1]}"
    N._conf.update(at=0, value=None)


def secret_free(text):
    return XUSER not in text and XPASS not in text and "player_api" not in text and "get.php" not in text


def unit():
    print("== الإيميل وكلمة المرور ==")
    check("الإيميل اليوزر @tv.ssouq.com كما في Stremio", N.email_for(XUSER) == "c0505xyz@tv.ssouq.com"
          and N.email_for(" Ab C+1/ ") == "abc1@tv.ssouq.com")
    check("يوزرٌ بلا حرفٍ صالح ← ValueError", raises(lambda: N.email_for("أحمد"), ValueError))
    check("كلمة المرور الباسورد نفسه، ثم هو و«A»", N.passwords_for(XPASS) == [XPASS, XPASS + "A"])
    check("وباسوردٌ أقصر من 6 أحرف (لا يقبله Nuvio): «A» حتى يبلغها", N.passwords_for("1234") == ["1234AA"]
          and N.passwords_for("12345") == ["12345A"] and N.passwords_for("123456") == ["123456", "123456A"])


def test_nuvio_auth(srv):
    print("== test_nuvio_auth: الاتصال والدخول ==")
    c = N.config()
    check("الإعدادات من ‏/.well-known/nuvio (المفتاح العام ودخول التلفاز)", c["key"] == mock_nuvio.KEY and c["tv_login"] is True
          and c["backend"] == N.BACKEND, json.dumps(c))
    srv.state.users["known@tv.ssouq.com"] = {"id": "u-known", "password": "Right123"}
    s = N.login("known@tv.ssouq.com", "Right123")
    check("دخولٌ صحيح ← جلسة", s["access_token"] and s["user_id"] == "u-known")
    check("كلمة مرورٍ خاطئة ← NuvioError برسالة Nuvio", "Invalid login" in str(raises(lambda: N.login("known@tv.ssouq.com", "x"), N.NuvioError)))
    check("جلسةٌ منتهية ← NuvioError", raises(lambda: N.pull_addons({"access_token": "expired"}), N.NuvioError))
    srv.state.down = True
    check("الخادم لا يردّ ← NuvioError", raises(lambda: N.login("known@tv.ssouq.com", "Right123"), N.NuvioError))
    srv.state.down = False


def test_nuvio_registration(srv):
    print("== test_nuvio_registration: إنشاء الحساب ==")
    e = N.email_for("reg1")
    s = N.signup(e, "Pass1234ab")
    check("حسابٌ جديد ← جلسته مباشرةً (بلا تأكيد بريد)", s["access_token"] and s["user_id"] and e in srv.state.users)
    check("وفيه إضافات Nuvio الافتراضية", [a["name"] for a in N.pull_addons(s)] == ["Cinemeta", "OpenSubtitles v3"])
    s2 = N.signup(e, "Pass1234ab")
    check("مسجَّلٌ من قبل ← دخولٌ إليه لا خطأ", s2["user_id"] == s["user_id"] and len(srv.state.users) == 2)
    check("مسجَّلٌ بكلمة مرورٍ أخرى ← NuvioError", raises(lambda: N.signup(e, "Other999x"), N.NuvioError))
    s3, pw = N.register(N.email_for("short"), "1234")
    check("باسوردٌ قصير ← يُسجَّل به و«A»", pw == "1234AA" and srv.state.users["short@tv.ssouq.com"]["password"] == "1234AA" and s3["user_id"])
    s4, pw = N.register(N.email_for("short"), "1234")
    check("وإعادته تدخل الحساب نفسه", pw == "1234AA" and s4["user_id"] == s3["user_id"])
    srv.state.users["taken@tv.ssouq.com"] = {"id": "u-taken", "password": "SomeoneElse1"}
    check("إيميلٌ مسجّلٌ بكلمة مرورٍ أخرى ← رسالةٌ واضحة", "بكلمة مرورٍ أخرى" in str(raises(lambda: N.register("taken@tv.ssouq.com", "Mine12345"), N.NuvioError)))
    srv.state.down = True
    check("والخادم لا يردّ ← NuvioError (لا يُجرَّب غيرها)", raises(lambda: N.register(N.email_for("x9"), "Mine12345"), N.NuvioError))
    srv.state.down = False


def test_addon_install(srv):
    print("== test_addon_install: تثبيت إضافتنا ==")
    s = N.signup(N.email_for("inst"), "Pass1234ab")
    ours = lambda u: u.startswith("https://guide.ssouq.com/stremio/")    # noqa: E731
    v1, v2 = "https://guide.ssouq.com/stremio/TOKEN1/manifest.json", "https://guide.ssouq.com/stremio/TOKEN2/manifest.json"
    items = N.install(s, v1, "سمارت سوق", ours)
    got = N.pull_addons(s)
    check("إضافتنا أولًا، وCinemeta وOpenSubtitles باقيتان بترتيبهما", [a["url"] for a in got] == [v1, mock_nuvio.DEFAULTS[0]["url"],
          mock_nuvio.DEFAULTS[1]["url"]] and got[0]["name"] == "سمارت سوق" and got[0]["enabled"] is True, json.dumps(got)[:200])
    check("‏sort_order متتابع", [a["sort_order"] for a in items] == [0, 1, 2])
    N.install(s, v2, "سمارت سوق", ours)
    got = N.pull_addons(s)
    check("نسخةٌ جديدة من رابطنا تحلّ محل القديمة (لا تتكرّر)", [a["url"] for a in got].count(v2) == 1 and v1 not in [a["url"] for a in got]
          and len(got) == 3)
    N.install(s, v2, "سمارت سوق", ours)
    check("وتثبيتها مرةً أخرى لا يكرّرها", len(N.pull_addons(s)) == 3)


def test_addon_sync(srv):
    print("== test_addon_sync: المزامنة لا تمسّ إضافات العميل ==")
    s = N.signup(N.email_for("sync"), "Pass1234ab")
    ours = lambda u: "/stremio/" in u    # noqa: E731
    mine = {"url": "https://torrentio.strem.fun/manifest.json", "name": "Torrentio", "enabled": False}
    N.push_addons(s, N.pull_addons(s) + [mine])
    N.install(s, "https://guide.ssouq.com/stremio/T/manifest.json", "سمارت سوق", ours)
    got = N.pull_addons(s)
    check("إضافة العميل (وتعطيله لها) تبقى بعد تثبيت إضافتنا", got[-1]["url"] == mine["url"] and got[-1]["enabled"] is False
          and got[0]["url"].endswith("/T/manifest.json"), json.dumps(got)[:200])
    N.uninstall(s, ours)
    got = N.pull_addons(s)
    check("وإزالة إضافتنا تزيلها وحدها", [a["name"] for a in got] == ["Cinemeta", "OpenSubtitles v3", "Torrentio"], str([a["name"] for a in got]))
    check("القراءة من جدول addons كتطبيقات Nuvio — لا دالة sync_pull_addons (لا توجد على خادمهم)",
          "GET /rest/v1/addons" in srv.state.calls and "/rest/v1/rpc/sync_pull_addons" not in srv.state.calls)
    check("ودالةٌ لا توجد ← NuvioError برسالة الخادم (PGRST202)", "Could not find the function" in str(raises(
        lambda: N._api("POST", "/rest/v1/rpc/sync_pull_addons", {"p_profile_id": 1}, s["access_token"]), N.NuvioError)))


def store_unit():
    print("== الحفظ ==")
    d = tempfile.mkdtemp(prefix="nuvio_store_")
    try:
        N.put(d, "127.0.0.1", XUSER, email="e@x", password="Clear123pw", acct="a1", gate="g1", addon_key="k1", status="active")
        raw = open(os.path.join(d, N.FILE), encoding="utf-8").read()
        check("كلمة المرور محفوظةٌ مشفَّرة", "Clear123pw" not in raw and "enc:1:" in raw)
        check("وتُقرأ واضحةً للأداة", N.get(d, "127.0.0.1", XUSER)["password"] == "Clear123pw")
        check("قفل الإضافة وصاحب الحساب من الفهرس", N.addon_key(d, "127.0.0.1", XUSER) == "k1"
              and N.owner(d, "127.0.0.1", XUSER) == {"acct": "a1", "gate": "g1"})
        time.sleep(0.02)
        N.put(d, "127.0.0.1", XUSER, status="off")
        check("حسابٌ أُلغي تفعيله ← لا قفل ساري (رابطه يتوقف)", N.addon_key(d, "127.0.0.1", XUSER) is None)
        check("ويبقى في قائمة حساب الأداة وحده", [r["username"] for r in N.owned(d, "a1")] == [XUSER] and N.owned(d, "a2") == []
              and N.owned(d, "a1", "g9") == [])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def against_mock():
    srv = mock_nuvio.serve()
    use(srv)
    try:
        test_nuvio_auth(srv)
        test_nuvio_registration(srv)
        test_addon_install(srv)
        test_addon_sync(srv)
        srv.state.addons.clear()
        bad = mock_nuvio.serve()
        use(bad)
        bad.shutdown()
        bad.server_close()
        check("خادمٌ مغلق ← NuvioError بلا تفاصيل", "تعذّر الوصول" in str(raises(N.config, N.NuvioError)))
    finally:
        srv.shutdown()


def through_server():
    nv = mock_nuvio.serve()
    xt = mock_xtream.serve(0)
    xt.users[XUSER] = XPASS
    threading.Thread(target=xt.serve_forever, daemon=True).start()
    xt_host = f"http://127.0.0.1:{xt.server_address[1]}"
    d = tempfile.mkdtemp(prefix="nuvio_web_")
    with open(os.path.join(d, "accounts.json"), "w", encoding="utf-8") as f:
        json.dump({"admin": None, "accounts": [
            {"id": "a1", "name": "MR7", "user": "mr7", "password": "pw123456", "stremio": True,
             "gates": [{"id": "g1", "name": "بوابة مرح", "mode": "web", "host": xt_host},
                       # سيرفرٌ آخر (localhost) — لربط خطٍّ من بوابةٍ أخرى بحساب Nuvio
                       {"id": "g2", "name": "بوابة كاسبر", "mode": "web", "host": xt_host.replace("127.0.0.1", "localhost")}]},
            {"id": "a2", "name": "Other", "user": "other", "password": "pw654321", "stremio": True,
             "gates": [{"id": "g1", "name": "بوابة مرح", "mode": "web", "host": xt_host}]},
            {"id": "a3", "name": "بلا Stremio", "user": "nost", "password": "pw333333",
             "gates": [{"id": "g1", "name": "بوابة مرح", "mode": "web", "host": xt_host}]}]}, f)
    env = dict(os.environ, XM_DATA=d, XM_BIND="127.0.0.1", XM_PORT=str(PORT), XM_ADMIN_PASSWORD="adminpw1",
               NUVIO_BACKEND=f"http://127.0.0.1:{nv.server_address[1]}", STREMIO_API="http://127.0.0.1:9/")
    env.pop("XM_SECRET_KEY", None)
    app = subprocess.Popen([sys.executable, os.path.join(ROOT, "xm_lines.py"), "web"], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    site = f"http://127.0.0.1:{PORT}"
    base = site + "/admin"
    jar = lambda: urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))   # noqa: E731
    op, op2, op3 = jar(), jar(), jar()

    def post(path, obj, opener=None):
        r = urllib.request.Request(base + path, data=json.dumps(obj).encode() if obj is not None else None,
                                   headers={"Content-Type": "application/json"}, method="POST" if obj is not None else "GET")
        try:
            x = (opener or op).open(r, timeout=60)
            return x.getcode(), json.loads(x.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def addon(url, path=""):
        """رابط الإضافة كما في Nuvio (‏https://guide.ssouq.com/stremio/…) ← (الرمز، النص) من خادم الاختبار."""
        u = urlsplit(url).path.rsplit("/manifest.json", 1)[0] + path
        try:
            x = urllib.request.urlopen(site + u, timeout=120)
            return x.getcode(), x.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def ours_in_nuvio(email):
        uid = nv.state.users[email]["id"]
        return [a for a in nv.state.addons[(uid, 1)]]

    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(base + "/login", timeout=0.3)
                break
            except Exception:
                time.sleep(0.1)
        print("== عبر الأداة: الصلاحيات ==")
        c, _ = post("/api/nuvio/account", {"gate": "g1", "username": XUSER, "password": XPASS})
        check("بلا دخول ← مرفوض", c == 401, str(c))
        post("/api/login", {"user": "nost", "password": "pw333333"}, op3)
        codes = [post("/api/nuvio/account", {"gate": "g1", "username": XUSER, "password": XPASS}, op3)[0],
                 post("/api/nuvio/accounts?gate=g1", None, op3)[0]]
        check("عميلٌ لم يُفتح له Stremio/Nuvio ← 403", codes == [403, 403], str(codes))
        check("ولم يُسجَّل في Nuvio شيء", not nv.state.users)
        c, r = post("/api/login", {"user": "mr7", "password": "pw123456"})
        check("دخول الحساب", c == 200 and r.get("role") == "account")

        print("== test_nuvio_registration (عبر الخادم) ==")
        c, r = post("/api/nuvio/account", {"gate": "g1", "username": XUSER, "password": "wrong-pass"})
        check("يوزرٌ لا يعمل على سيرفره ← لا حساب Nuvio", c in (400, 502) and not nv.state.users, json.dumps(r, ensure_ascii=False)[:120])
        c, r = post("/api/nuvio/account", {"gate": "g1", "username": XUSER, "password": XPASS})
        email, pw = r.get("email", ""), r.get("password", "")
        check("زرّ «حساب Nuvio» ← الإيميل اليوزر @tv.ssouq.com وكلمة المرور باسورده (كحساب Stremio)", c == 200 and r.get("ok")
              and r.get("created") is True and email == "c0505xyz@tv.ssouq.com" and pw == XPASS, json.dumps(r, ensure_ascii=False))
        check("والحساب في Nuvio بهذه البيانات", nv.state.users.get(email, {}).get("password") == pw)
        lst = ours_in_nuvio(email)
        url1 = lst[0]["url"] if lst else ""
        check("إضافتنا أول قائمة إضافاته باسم «سمارت سوق» وإضافات Nuvio الافتراضية باقية",
              lst and lst[0]["name"] == "سمارت سوق" and url1.startswith("https://") and url1.endswith("/manifest.json")
              and "/stremio/" in url1 and [a["name"] for a in lst[1:]] == ["Cinemeta", "OpenSubtitles v3"], json.dumps(lst, ensure_ascii=False)[:240])
        check("test_m3u_secret_not_exposed: رابط الإضافة في Nuvio بلا بيانات Xtream ولا رابط M3U", secret_free(url1) and "password" not in url1, url1)

        print("== test_addon_install: الإضافة تعمل من رابطها في Nuvio ==")
        c, txt = addon(url1, "/manifest.json")
        man = json.loads(txt) if c == 200 else {}
        check("الـmanifest يُخدَم ‏(200) بكتالوجاته", c == 200 and man.get("catalogs") and man.get("resources"), str(c))
        check("وبلا بيانات Xtream فيه", secret_free(txt))
        cat = next((x for x in man.get("catalogs", []) if x["type"] == "movie" and not x["id"].startswith(S.CAT_PREFIX)), {})
        c, txt = addon(url1, f"/catalog/movie/{quote(cat.get('id', 'x'))}.json")
        metas = json.loads(txt).get("metas", []) if c == 200 else []
        check("كتالوج الأفلام يعمل", c == 200 and metas, f"{c} {txt[:80]}")
        check("وبلا بيانات Xtream", secret_free(txt))
        mid = metas[0]["id"] if metas else "x"
        c, txt = addon(url1, f"/stream/movie/{quote(mid)}.json")
        streams = json.loads(txt).get("streams", []) if c == 200 else []
        urls = [s.get("url", "") for s in streams if s.get("url")]
        check("test_credentials_not_returned_to_client: روابط التشغيل عبر خادمنا ‏(/play/) بلا يوزر ولا باسورد",
              c == 200 and urls and all("/play/" in u and secret_free(u) and xt_host not in u for u in urls), json.dumps(urls)[:200])
        check("ونصّ ردّ المصادر كله بلا بيانات Xtream", secret_free(txt))

        print("== test_existing_ids_unchanged ==")
        pub = S.links("https://guide.ssouq.com", S.make_token(d, xt_host, XUSER, XPASS))["manifest"]
        c2, txt2 = addon(pub, "/manifest.json")
        man2 = json.loads(txt2) if c2 == 200 else {}
        c3, txt3 = addon(pub, f"/catalog/movie/{quote(cat.get('id', 'x'))}.json")
        ids2 = [m["id"] for m in json.loads(txt3).get("metas", [])] if c3 == 200 else []
        check("معرّف الإضافة نفسه في Nuvio وفي رابط Stremio للخط", man2.get("id") and man2.get("id") == man.get("id"), f"{man.get('id')} {man2.get('id')}")
        check("ومعرّفات الأعمال نفسها (لا يتغيّر أي ID)", ids2 and ids2 == [m["id"] for m in metas])

        print("== واجهة الجوال والتلفاز: المجموعات وترتيب الرئيسية ==")
        uid = nv.state.users[email]["id"]
        aid = man.get("id")
        cols = nv.state.collections.get((uid, 1)) or []
        check("ثلاث مجموعاتٍ مثبّتة أعلى الرئيسية: المسلسلات · الأفلام · القنوات", [(c["id"], c["title"], c["pinToTop"]) for c in cols]
              == [("ssouq_series", "المسلسلات", True), ("ssouq_movie", "الأفلام", True), ("ssouq_tv", "القنوات", True)],
              json.dumps([c.get("title") for c in cols], ensure_ascii=False))
        f0 = (cols[0]["folders"] or [{}])[0] if cols else {}
        check("أول مجلدٍ «الكل»: كتالوج المسلسلات من إضافتنا (بمعرّفها)", f0.get("title") == "الكل"
              and f0.get("sources") == [{"provider": "addon", "addonId": aid, "type": "series", "catalogId": "sq_series"}], json.dumps(f0, ensure_ascii=False)[:200])
        tr = next((f for c in cols for f in c["folders"] if f["title"] == "تركي" and c["id"] == "ssouq_series"), {})
        check("ومجلدٌ لكل تصنيف: الكتالوج نفسه بالتصنيف («تركي»)، وصورته مرسومةٌ على خادمنا", tr.get("sources", [{}])[0].get("genre") == "تركي"
              and tr.get("coverImageUrl", "").startswith("https://") and "/stremio/p/" in tr.get("coverImageUrl", "") and tr.get("tileShape") == "square",
              json.dumps(tr, ensure_ascii=False)[:200])
        c, _ = addon(url1.replace("/manifest.json", "") + "/manifest.json", "")
        cov = tr.get("coverImageUrl", "")
        try:
            cv = urllib.request.urlopen(site + urlsplit(cov).path, timeout=30)
            cov_ok = cv.getcode() == 200 and cv.headers.get("Content-Type", "").startswith("image/")
        except Exception:
            cov_ok = False
        check("والصورة تُخدَم (صورة)", cov_ok)
        c, txt = addon(url1, "/catalog/series/sq_series/genre=" + quote("أجنبي", safe="") + ".json")
        check("ومجلدٌ يفتح قائمته كاملة: الكتالوج بالتصنيف باسمه بلا عدد", c == 200 and json.loads(txt).get("metas"), f"{c} {txt[:80]}")
        home = nv.state.home.get((uid, 1, "home_catalog_shared")) or {}
        keys = [i["key"] for i in home.get("items", [])]
        check("ترتيب الرئيسية (للجوال والتلفاز معًا): المجموعات ثم «أحدث المسلسلات» «أحدث الأفلام» «القنوات» ثم «حساباتي»",
              keys[:7] == ["collection_ssouq_series", "collection_ssouq_movie", "collection_ssouq_tv", f"{aid}:series:sq_series",
                           f"{aid}:movie:sq_movies", f"{aid}:tv:sq_live", f"{aid}:{S.ACCOUNTS}:{S.ACCOUNTS_ID}"]
              and [i["custom_title"] for i in home["items"][3:7]] == ["أحدث المسلسلات", "أحدث الأفلام", "القنوات", "حساباتي"]
              and [i["order"] for i in home["items"]] == list(range(len(home["items"]))), json.dumps(keys[:8], ensure_ascii=False))
        check("بلا لاحقة النوع الإنجليزية (Series/Movies)، وصفوف Cinemeta مطفأة (لا تُشغَّل عناوينها)", home.get("show_catalog_type") is False
              and all(i["enabled"] is False for i in home["items"] if i["key"].startswith("com.linvo.cinemeta:"))
              and sum(1 for i in home["items"] if i["key"].startswith("com.linvo.cinemeta:")) == 6)
        names = {x["type"]: x["name"] for x in man["catalogs"] if x["id"] in ("sq_series", "sq_movies", "sq_live", S.ACCOUNTS_ID)}
        check("وأسماء كتالوجات إضافة Nuvio عربيةٌ لكل نوع («المسلسلات (N)» · «حساباتي»)، وإضافة Stremio كما كانت",
              names.get("series", "").startswith("المسلسلات") and names.get("movie", "").startswith("الأفلام")
              and names.get("tv", "").startswith("القنوات") and names.get(S.ACCOUNTS) == "حساباتي"
              and all(not x["name"].startswith(("المسلسلات", "الأفلام", "القنوات")) for x in man2["catalogs"]), json.dumps(names, ensure_ascii=False))
        # العميل أضاف مجموعته، وأعاد صفّ Cinemeta، ورتّب إضافته الأخرى — «تحديث الإضافة» لا يمسّها
        nv.state.collections[(uid, 1)] = cols + [{"id": "mine1", "title": "مفضلتي", "folders": [{"id": "f", "title": "x", "sources": []}]}]
        for i in home["items"]:
            if i["key"] == "com.linvo.cinemeta:movie:top":
                i["enabled"] = True
        home["items"].append({"key": "org.other:movie:pop", "addon_id": "org.other", "type": "movie", "catalog_id": "pop", "order": 99,
                              "enabled": True, "custom_title": "", "is_collection": False, "collection_id": ""})
        c, r = post("/api/nuvio/reinstall", {"gate": "g1", "username": XUSER})
        cols2 = nv.state.collections.get((uid, 1)) or []
        home2 = nv.state.home.get((uid, 1, "home_catalog_shared")) or {}
        by2 = {i["key"]: i for i in home2.get("items", [])}
        check("«تحديث الإضافة» يجدّدها: مجموعاتنا أولًا، ومجموعة العميل باقية", [c_["id"] for c_ in cols2] == ["ssouq_series", "ssouq_movie", "ssouq_tv", "mine1"],
              str([c_["id"] for c_ in cols2]))
        check("وما أعاده العميل من Cinemeta يبقى كما اختار، وإضافته الأخرى بعد صفوفنا", by2.get("com.linvo.cinemeta:movie:top", {}).get("enabled") is True
              and by2.get("org.other:movie:pop", {}).get("order", 0) > by2[f"{aid}:{S.ACCOUNTS}:{S.ACCOUNTS_ID}"]["order"])
        ser2 = next(c_ for c_ in cols2 if c_["id"] == "ssouq_series")
        fy = ser2["folders"][1]
        check("وثاني مجلدٍ أحدث سنة («2026»…): كتالوج المسلسلات بالسنة", fy["title"].isdigit() and len(fy["title"]) == 4
              and fy["sources"][0]["genre"] == fy["title"] and fy["sources"][0]["catalogId"] == "sq_series", json.dumps(fy, ensure_ascii=False)[:160])
        c, txt = addon(url1, "/catalog/series/sq_series/genre=" + quote(fy["title"], safe="") + ".json")
        check("ويفتح أعمال تلك السنة", c == 200 and json.loads(txt).get("metas") and all(m.get("releaseInfo") == fy["title"] for m in json.loads(txt)["metas"]),
              txt[:120])
        check("وبعد أن بُنيت المكتبة: مجلدات التصنيفات التي فيها محتوى وحدها", ser2["folders"][0]["title"] == "الكل"
              and {f["title"] for f in ser2["folders"][2:]} <= {"تركي مترجم يعرض الآن", "تركي مدبلج يعرض الآن", "تركي", "أجنبي", "عربي", "رمضان", "آسيوي", "أنمي", "أطفال وكرتون", "هندي", "وثائقي", "مدبلج", "أخرى"}
              and len(ser2["folders"]) < len(cols[0]["folders"]), str([f["title"] for f in ser2["folders"]]))
        c, r = post("/api/nuvio/accounts?gate=g1", None)
        row = next((a for a in r.get("accounts", []) if a["username"] == XUSER), {})
        check("والبطاقة تقول إن الواجهة ضُبطت", row.get("home_at") and not row.get("home_err"))

        print("== «تحديث الإضافة لكل الحسابات» يشمل Nuvio ==")
        nv.state.collections[(uid, 1)] = []
        c, r = post("/api/stremio/update-all", {})
        for _ in range(100):
            c2, r2 = post("/api/stremio/update-all", None)
            if not (r2.get("job") or {}).get("running"):
                break
            time.sleep(0.2)
        job = r2.get("job") or {}
        check("يبدأ ويشمل حسابات Nuvio (الإضافة والواجهة)", c == 200 and job.get("total", 0) >= 1 and job.get("done") == job.get("total")
              and [c_["id"] for c_ in nv.state.collections.get((uid, 1)) or []][:3] == ["ssouq_series", "ssouq_movie", "ssouq_tv"],
              json.dumps(job, ensure_ascii=False)[:200])

        print("== «فحص عمل» ==")
        q = quote("game of thrones")
        c, r = post(f"/api/stremio/inspect?platform=nuvio&gate=g1&username={XUSER}&q={q}", None)
        ser = next((k for k in r.get("kinds", []) if k["kind"] == "series"), {})
        ln0 = (ser.get("lines") or [{}])[0]
        check("لحساب Nuvio: ما في قائمة خطّه والعمل في الإضافة", c == 200 and ln0.get("loaded") and ln0.get("items")
              and ln0["items"][0]["name"] == "Game of Thrones" and ser.get("works") and ser["works"][0]["sources"],
              json.dumps(r, ensure_ascii=False)[:240])
        check("وبلا بيانات Xtream (اليوزر مخفي)", c == 200 and secret_free(json.dumps(r)) and r["accounts"][0]["user"].startswith("•••"))
        c, r = post(f"/api/stremio/inspect?platform=stremio&gate=g1&username={XUSER}&q={q}", None)
        check("ولـ Stremio: لا حساب Stremio لهذا اليوزر ← 400", c == 400, json.dumps(r, ensure_ascii=False))
        post("/api/login", {"user": "other", "password": "pw654321"}, op2)
        c, r = post(f"/api/stremio/inspect?platform=nuvio&gate=g1&username={XUSER}&q={q}", None, op2)
        check("وحسابٌ آخر لا يفحص حسابات غيره", c == 400)

        print("== المرة الثانية والقائمة ==")
        c, r = post("/api/nuvio/account", {"gate": "g1", "username": XUSER, "password": XPASS})
        check("المرة الثانية: الحساب نفسه بلا إنشاء", c == 200 and r["created"] is False and r["email"] == email and r["password"] == pw
              and len(nv.state.users) == 1)
        c, r = post("/api/nuvio/accounts?gate=g1", None)
        row = (r.get("accounts") or [{}])[0]
        check("قائمة حسابات Nuvio للبوابة: الإيميل وكلمة المرور والحال والإضافة", c == 200 and row.get("email") == email
              and row.get("password") == pw and row.get("status") == "active" and row.get("addon_v") == S.VERSION and row.get("addon_at"),
              json.dumps(r, ensure_ascii=False)[:200])
        check("والقائمة بلا رابط إضافة", "/stremio/" not in json.dumps(r))
        raw = open(os.path.join(d, N.FILE), encoding="utf-8").read()
        check("كلمة مرور Nuvio محفوظةٌ مشفَّرة على القرص", pw not in raw and XPASS not in raw)
        post("/api/login", {"user": "other", "password": "pw654321"}, op2)
        c, r = post("/api/nuvio/accounts?gate=g1", None, op2)
        check("حسابٌ آخر لا يرى حسابات غيره", c == 200 and r["accounts"] == [])
        codes = [post(p, {"gate": "g1", "username": XUSER}, op2)[0] for p in ("/api/nuvio/reinstall", "/api/nuvio/disable")]
        check("ولا يحدّث إضافتها ولا يلغيها", codes == [400, 400], str(codes))
        check("بوابةٌ ليست له ← 404", post("/api/nuvio/accounts?gate=nope", None)[0] == 404)

        print("== باسوردٌ قصير ==")
        xt.users["short1"] = "1234"
        c, r = post("/api/nuvio/account", {"gate": "g1", "username": "short1", "password": "1234"})
        check("باسوردٌ أقصر من 6 أحرف: كلمة المرور هو و«A» (كما يُبلَّغ العميل)", c == 200 and r.get("email") == "short1@tv.ssouq.com"
              and r.get("password") == "1234AA" and nv.state.users.get("short1@tv.ssouq.com", {}).get("password") == "1234AA",
              json.dumps(r, ensure_ascii=False))

        print("== «تحديث الإضافة» ==")
        uid = nv.state.users[email]["id"]
        nv.state.addons[(uid, 1)].append({"url": "https://torrentio.strem.fun/manifest.json", "name": "Torrentio", "enabled": True, "sort_order": 9})
        nv.state.addons[(uid, 1)].reverse()                 # العميل رتّبها بنفسه
        c, r = post("/api/nuvio/reinstall", {"gate": "g1", "username": XUSER})
        lst = ours_in_nuvio(email)
        check("إضافتنا تعود أول القائمة برابطها نفسه، وإضافة العميل باقية", c == 200 and lst[0]["url"] == url1
              and [a["url"] for a in lst].count(url1) == 1 and "Torrentio" in [a["name"] for a in lst] and len(lst) == 4,
              json.dumps([a["name"] for a in lst], ensure_ascii=False))

        print("== «إلغاء التفعيل» ==")
        c, r = post("/api/nuvio/disable", {"gate": "g1", "username": XUSER})
        lst = ours_in_nuvio(email)
        check("الحال «off» وإضافتنا أُزيلت من حسابه وحدها", c == 200 and r.get("status") == "off" and "/stremio/" not in json.dumps(lst)
              and sorted(a["name"] for a in lst) == ["Cinemeta", "OpenSubtitles v3", "Torrentio"], json.dumps(r, ensure_ascii=False))
        check("ورابطها القديم يتوقف (لو نُسخ)", addon(url1, "/manifest.json")[0] == 404)
        check("والحساب نفسه باقٍ في Nuvio", email in nv.state.users)
        c, r = post("/api/nuvio/account", {"gate": "g1", "username": XUSER, "password": XPASS})
        check("«حساب Nuvio» مرةً أخرى يعيد تفعيله بالحساب نفسه (لا حساب جديد)", c == 200 and r["created"] is False and r["email"] == email and r["password"] == pw
              and r["status"] == "active" and len(nv.state.users) == 2, json.dumps(r, ensure_ascii=False))
        url2 = ours_in_nuvio(email)[0]["url"]
        check("برابطٍ جديد يعمل، والقديم يبقى متوقفًا", url2 != url1 and addon(url2, "/manifest.json")[0] == 200
              and addon(url1, "/manifest.json")[0] == 404)
        post("/api/nuvio/disable", {"gate": "g1", "username": XUSER})

        print("== «إعادة الربط» ==")
        c, r = post("/api/nuvio/reinstall", {"gate": "g1", "username": XUSER, "relink": True})
        url3 = ours_in_nuvio(email)[0]["url"]
        check("بعد الإلغاء: يعود مفعّلًا برابطٍ جديد", c == 200 and r["status"] == "active" and url3 not in (url1, url2)
              and addon(url3, "/manifest.json")[0] == 200 and addon(url2, "/manifest.json")[0] == 404, json.dumps(r, ensure_ascii=False))
        c, r = post("/api/nuvio/reinstall", {"gate": "g1", "username": XUSER, "relink": True})
        url4 = ours_in_nuvio(email)[0]["url"]
        check("وهو مفعّل: رابطٌ جديد يُبطل السابق فورًا", c == 200 and url4 != url3 and addon(url4, "/manifest.json")[0] == 200
              and addon(url3, "/manifest.json")[0] == 404 and [a["url"] for a in ours_in_nuvio(email)].count(url4) == 1)
        check("والمعرّفات بعد إعادة الربط كما كانت", json.loads(addon(url4, "/manifest.json")[1]).get("id") == man.get("id"))

        print("== «ربط خط آخر»: مكتبةٌ واحدة بخطوط بوابتين ==")
        srcs = lambda url: {m.group(1) for m in (re.search(r"/play/[^/]+/[^/]+/([0-9a-f]{6})\.", x.get("url", "")) for x in   # noqa: E731
                            json.loads(addon(url, f"/stream/movie/{quote(mid)}.json")[1]).get("streams", [])) if m}   # بصمة خطّ كل مصدر
        check("قبل الربط: مصادر خطٍّ واحد", len(srcs(url4)) == 1, str(srcs(url4)))
        c, r = post("/api/nuvio/link", {"gate": "g1", "username": XUSER, "line_gate": "g2", "line_username": "u", "line_password": "p"})
        check("يُربط خطٌّ من بوابةٍ أخرى بالحساب نفسه", c == 200 and r.get("created") is True and r.get("email") == email, json.dumps(r, ensure_ascii=False))
        check("ولا يُثبَّت شيءٌ جديد في Nuvio (الإضافة نفسها)", [a["url"] for a in ours_in_nuvio(email)].count(url4) == 1
              and sum("/stremio/" in a["url"] for a in ours_in_nuvio(email)) == 1)
        got = srcs(url4)
        check("وإضافته تعرض العمل بمصادر الخطين", len(got) == 2, str(got))
        check("ومعرّف الإضافة كما هو", json.loads(addon(url4, "/manifest.json")[1]).get("id") == man.get("id"))
        c, r = post("/api/nuvio/accounts?gate=g2", None)
        row = (r.get("accounts") or [{}])[0]
        check("الخط المرتبط في بوابته ببيانات حسابه وخطّيه", row.get("username") == "u" and row.get("linked") is True and row.get("email") == email
              and [(l["gate"], l["username"], l["main"]) for l in row.get("lines", [])] == [("g1", XUSER, True), ("g2", "u", False)],
              json.dumps(row, ensure_ascii=False)[:240])
        check("ويُعدّ في بوابته", r.get("counts", {}).get("g2") == 1)
        c, r = post("/api/nuvio/link", {"gate": "g2", "username": "u", "line_gate": "g2", "line_username": "u", "line_password": "p"})
        check("ربطه مرةً أخرى (من بطاقة أي خطٍّ في الحساب) ← مرتبطٌ من قبل", c == 200 and r.get("created") is False, json.dumps(r, ensure_ascii=False))
        c, r = post("/api/nuvio/link", {"gate": "g1", "username": XUSER, "line_gate": "g1", "line_username": XUSER, "line_password": XPASS})
        check("صاحب الحساب لا يُربط بنفسه", c == 400, json.dumps(r, ensure_ascii=False))
        c, r = post("/api/nuvio/account", {"gate": "g2", "username": "u", "password": "p"})
        check("ولا حساب Nuvio مستقل لخطٍّ مرتبط", c == 400 and "مرتبط" in r.get("error", ""), json.dumps(r, ensure_ascii=False))
        c, r = post("/api/nuvio/reinstall", {"gate": "g2", "username": "u"})
        check("«تحديث الإضافة» من بطاقة الخط المرتبط ← لحساب صاحبه", c == 200 and r.get("email") == email
              and ours_in_nuvio(email)[0]["url"] == url4, json.dumps(r, ensure_ascii=False))
        c, r = post("/api/nuvio/unlink", {"gate": "g1", "username": XUSER})
        check("صاحب الحساب لا يُفصل", c == 400)
        c, r = post("/api/nuvio/unlink", {"gate": "g2", "username": "u"})
        check("«فصل الخط» يخرجه من الحساب", c == 200 and post("/api/nuvio/accounts?gate=g2", None)[1]["accounts"] == [] and len(srcs(url4)) == 1)

        print("== «حساب Nuvio بإيميلٍ تختاره» ==")
        xt.users["cust1"] = "pw1"
        c, r = post("/api/nuvio/custom", {"email": "Ahmed.K", "password": "MyPass77", "line_gate": "g1", "line_username": "cust1", "line_password": "pw1"})
        check("الإيميل وكلمة المرور كما اختارهما الموظف", c == 200 and r.get("email") == "ahmed.k@tv.ssouq.com" and r.get("password") == "MyPass77"
              and nv.state.users.get("ahmed.k@tv.ssouq.com", {}).get("password") == "MyPass77", json.dumps(r, ensure_ascii=False))
        check("وإضافتنا أول قائمة إضافاته", ours_in_nuvio("ahmed.k@tv.ssouq.com")[0]["name"] == "سمارت سوق")
        c, r = post("/api/nuvio/accounts?gate=g1", None)
        check("ويظهر في قائمة بوابته", "ahmed.k@tv.ssouq.com" in [a["email"] for a in r.get("accounts", [])])
        xt.users["cust2"] = "pw2"
        bad = [post("/api/nuvio/custom", {"email": e, "password": p, "line_gate": "g1", "line_username": u, "line_password": lp})
               for e, p, u, lp in (("ahmed.k", "MyPass77", "cust2", "pw2"), ("x@gmail.com", "MyPass77", "cust2", "pw2"),
                                   ("a", "MyPass77", "cust2", "pw2"), ("good.name", "123", "cust2", "pw2"),
                                   ("other.name", "MyPass77", XUSER, XPASS))]
        check("إيميلٌ لحسابٍ آخر عندنا، أو دومينٌ آخر، أو اسمٌ قصير، أو كلمة مرورٍ قصيرة، أو خطٌّ له حساب ← 400 برسالة",
              [c for c, _ in bad] == [400] * 5 and "لحساب Nuvio آخر" in bad[0][1].get("error", "") and "حساب Nuvio من قبل" in bad[4][1].get("error", ""),
              str([(c, r.get("error")) for c, r in bad]))
        nv.state.users["taken2@tv.ssouq.com"] = {"id": "u-t2", "password": "Someone99"}
        c, r = post("/api/nuvio/custom", {"email": "taken2", "password": "MyPass77", "line_gate": "g1", "line_username": "cust2", "line_password": "pw2"})
        check("إيميلٌ مسجّلٌ في Nuvio بكلمة مرورٍ أخرى ← رسالةٌ واضحة ولا يُحفظ", c == 502 and "بكلمة مرورٍ أخرى" in r.get("error", "")
              and not N.get(d, S.host_key(xt_host), "cust2"), json.dumps(r, ensure_ascii=False))

        print("== Nuvio لا يردّ ==")
        nv.state.down = True
        c, r = post("/api/nuvio/reinstall", {"gate": "g1", "username": XUSER})
        check("‏502 برسالة «Nuvio:»", c == 502 and r.get("error", "").startswith("Nuvio:"), json.dumps(r, ensure_ascii=False))
        c, r = post("/api/nuvio/account", {"gate": "g1", "username": "u", "password": "p"})
        check("وحسابٌ جديد لا يُحفظ نصف حساب", c == 502 and not N.get(d, S.host_key(xt_host), "u"))
        nv.state.down = False
        xt.users["half1"] = "pw7777"
        real_push = mock_nuvio.Handler.do_POST
        def push_fails(self):                                          # الحساب يُنشأ ثم يتعثّر تثبيت الإضافة
            if self.path.startswith("/rest/v1/rpc/sync_push_addons"):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                return self._send(500, {"message": "boom"})
            return real_push(self)
        mock_nuvio.Handler.do_POST = push_fails
        c, r = post("/api/nuvio/account", {"gate": "g1", "username": "half1", "password": "pw7777"})
        mock_nuvio.Handler.do_POST = real_push
        c2, r2 = post("/api/nuvio/accounts?gate=g1", None)
        half = next((a for a in r2.get("accounts", []) if a["username"] == "half1"), {})
        check("تعثّر تثبيت الإضافة بعد إنشاء الحساب ← 502، والبطاقة تقول إن الإضافة لم تُثبَّت", c == 502 and half and not half.get("addon_at"),
              json.dumps(half, ensure_ascii=False)[:160])
        c, r = post("/api/nuvio/account", {"gate": "g1", "username": "half1", "password": "pw7777"})
        check("و«إنشاء حساب Nuvio» مرةً أخرى يكمل التثبيت", c == 200 and ours_in_nuvio("half1@tv.ssouq.com")[0]["name"] == "سمارت سوق",
              json.dumps(r, ensure_ascii=False))
        check("وإضافته العاملة لا تتأثر بتعطّل Nuvio", addon(url4, "/manifest.json")[0] == 200)
    finally:
        app.terminate()
        try:
            app.wait(timeout=5)
        except subprocess.TimeoutExpired:
            app.kill()
        nv.shutdown()
        xt.shutdown()
        shutil.rmtree(d, ignore_errors=True)


def main():
    unit()
    store_unit()
    against_mock()
    through_server()
    print("\n----------------------------------------")
    print("Result: \033[32m%d passed\033[0m, %s" % (_p, ("\033[31m%d failed\033[0m" % _f) if _f else "0 failed"))
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

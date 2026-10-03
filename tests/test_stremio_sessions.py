"""اختبارات التحكّم في الأجهزة المتزامنة (stremio_sessions) — نسخة «session» من الإضافة."""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import stremio_sessions as SS  # noqa: E402
import stremio_addon as S  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mock_xtream  # noqa: E402
import threading  # noqa: E402
from urllib.parse import quote  # noqa: E402

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  \033[32mPASS\033[0m  {name}" + (f"  ({detail})" if detail else ""))
    else:
        failed += 1
        print(f"  \033[31mFAIL\033[0m  {name}" + (f"  ({detail})" if detail else ""))


NUVIO_PHONE = "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
NUVIO_TV = "Mozilla/5.0 (Linux; Android 13; Android TV) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def core():
    print("== المخزن والبصمة ==")
    d = tempfile.mkdtemp(prefix="sessions_")
    try:
        SS.reset()
        SS.setup(d)
        A = SS.account_key("Panel.example", "u1")
        check("مفتاح الاشتراك «هوست|يوزر»", A == "panel.example|u1")
        check("بلا ضبطٍ: النسخة «standard» (الإضافة كما كانت)", SS.variant(A) == "standard")
        check("فئة التطبيق بلا أرقام الإصدار (تحديث التطبيق ليس جهازًا جديدًا)",
              SS.ua_class("NuvioTV/1.0 okhttp/4.12.0") == SS.ua_class("NuvioTV/1.3 okhttp/4.12.1"))
        check("IPv6: أول 64 بتًّا (عناوين الخصوصية تتبدّل داخلها)", SS.ip_net("2001:db8:1:2::abcd") == SS.ip_net("2001:db8:1:2:ffff::1")
              and SS.ip_net("2001:db8:1:2::1") != SS.ip_net("2001:db8:1:3::1"))
        check("البصمة من الشبكة: نفسها للجهاز نفسه وإن اختلف User-Agent مكوّناته (التطبيق والمشغّل)، وغيرها لشبكةٍ أخرى",
              SS.device_key(A, "1.2.3.4", NUVIO_PHONE) == SS.device_key(A, "1.2.3.4", "okhttp/4.12.0")
              != SS.device_key(A, "5.6.7.8", NUVIO_PHONE))
        check("وبصمة اشتراكٍ آخر غيرها", SS.device_key(A, "1.2.3.4", NUVIO_PHONE) != SS.device_key("x|y", "1.2.3.4", NUVIO_PHONE))

        print("== الحد: Device A يُسمح، وDevice B يُرفض، وA لا يُقطع ==")
        SS.set_account(A, owner="acct1", variant="session", max_devices=1)
        r1 = SS.check(A, "1.2.3.4", NUVIO_PHONE, "s:1:1:1", "series", now=1000)
        check("الجهاز A ← سماح وجلسةٌ جديدة بمعرّفٍ عشوائي", r1["allowed"] and r1["reason"] is None and len(r1["session_id"]) >= 20
              and r1["active_devices"] == 1 and r1["max_devices"] == 1, json.dumps(r1))
        r1b = SS.check(A, "1.2.3.4", "okhttp/4.12.0", "s:1:1:2", "series", now=1300)
        check("والجهاز نفسه بحلقةٍ أخرى (ومكوّنٍ آخر يطلب) ← الجلسة نفسها، لا جهازٌ جديد", r1b["allowed"] and r1b["session_id"] == r1["session_id"])
        r2 = SS.check(A, "9.9.9.9", NUVIO_TV, "m:5", "movie", now=1400)
        check("الجهاز B ← رفضٌ بحالةٍ واضحة", r2 == {"allowed": False, "reason": "CONCURRENT_DEVICE_LIMIT", "active_devices": 1, "max_devices": 1,
                                                  "session_id": None, "message": "الحساب مستخدم حاليًا على جهاز آخر."}, json.dumps(r2, ensure_ascii=False))
        s = {x["session_id"]: x for x in SS.sessions([A], now=1400)}
        check("وجلسة A باقيةٌ نشطة بآخر محتوى وآخر ظهور (لا تُقطع)", s[r1["session_id"]]["status"] == "active"
              and s[r1["session_id"]]["last_seen"] == 1300 and s[r1["session_id"]]["content_id"] == "s:1:1:2" and len(s) == 1)
        check("‏dry: القرار بلا إنشاء جلسة", SS.check(A, "9.9.9.9", NUVIO_TV, dry=True, now=1400)["reason"] == "CONCURRENT_DEVICE_LIMIT"
              and len(SS.sessions([A], now=1400)) == 1)

        print("== المهلة (من الأداة) ==")
        check("الافتراضي: 3 ساعات للأفلام والمسلسلات وساعة للبث", SS.settings("acct1") == {"timeout_vod": 10800, "timeout_live": 3600, "default_max": 1})
        r3 = SS.check(A, "9.9.9.9", NUVIO_TV, "m:5", "movie", now=1300 + 10801)
        check("بعد 3 ساعاتٍ بلا تشغيل: جلسة A انتهت ← B يُسمح", r3["allowed"] and r3["active_devices"] == 1)
        st = {x["session_id"]: x["status"] for x in SS.sessions([A], now=1300 + 10801)}
        check("وA «expired» في القائمة", st[r1["session_id"]] == "expired" and st[r3["session_id"]] == "active")
        SS.set_settings("acct1", timeout_live=120)
        rl = SS.check(A, "9.9.9.9", NUVIO_TV, "l:7", "live", now=20000)
        check("والبث بمهلته: تغييرها من الأداة يسري", rl["allowed"] and SS.settings("acct1")["timeout_live"] == 120
              and SS.check(A, "1.2.3.4", NUVIO_PHONE, "m:1", "movie", now=20000 + 121)["allowed"])
        try:
            SS.set_settings("acct1", timeout_vod=5)
            bad = False
        except ValueError:
            bad = True
        check("ومهلةٌ أقل من دقيقة ← ValueError", bad)

        print("== الحد من اللوحة، ومن الأداة ==")
        B = SS.account_key("panel.example", "u2")
        SS.set_account(B, owner="acct1", variant="session")          # بلا حدٍّ مضبوط: من اللوحة
        ok2 = [SS.check(B, f"10.0.0.{i}", NUVIO_PHONE, panel_max=2, now=5000)["allowed"] for i in (1, 2, 3)]
        check("بلا حدٍّ مضبوط: ‏max_connections من اللوحة (2) — لا 1 إجباري", ok2 == [True, True, False], str(ok2))
        check("ويُحفظ آخر ما عُرف منها (حين تتعذّر اللوحة)", SS.account(B)["panel_max"] == 2
              and SS.check(B, "10.0.0.9", NUVIO_PHONE, dry=True, now=5001)["max_devices"] == 2)
        SS.set_account(B, max_devices=3)
        check("والموظف يرفعه إلى 3 ← الثالث يُسمح", SS.check(B, "10.0.0.3", NUVIO_PHONE, panel_max=2, now=5002)["allowed"])
        C = SS.account_key("panel.example", "u3")
        SS.set_account(C, owner="acct1", variant="session")
        check("ولا لوحة ولا حد ← ‏default_max (1)", SS.check(C, "1.1.1.1", NUVIO_PHONE, now=1)["max_devices"] == 1)
        try:
            SS.set_account(C, max_devices=0)
            bad = False
        except ValueError:
            bad = True
        check("حدٌّ 0 ← ValueError", bad)

        print("== الإلغاء، والخروج من كل الأجهزة ==")
        D = SS.account_key("panel.example", "u4")
        SS.set_account(D, owner="acct1", variant="session", max_devices=1)
        a = SS.check(D, "1.2.3.4", NUVIO_PHONE, "m:1", "movie", now=100)
        check("إلغاء جلسة ← اشتراكها", SS.revoke(a["session_id"]) == D)
        rv = SS.check(D, "1.2.3.4", NUVIO_PHONE, "m:2", "movie", now=200)
        check("والجهاز الملغى ← لا /play جديد (SESSION_REVOKED)", not rv["allowed"] and rv["reason"] == "SESSION_REVOKED"
              and rv["message"] == "تم تسجيل الدخول من جهاز آخر.", json.dumps(rv, ensure_ascii=False))
        check("ومكانه في الحد يتحرّر لجهازٍ آخر", SS.check(D, "5.5.5.5", NUVIO_TV, "m:2", "movie", now=200)["allowed"])
        check("وفي القائمة «revoked»", any(x["status"] == "revoked" for x in SS.sessions([D], now=200)))
        v = SS.logout_all(D)
        check("الخروج من كل الأجهزة: ‏version += 1 والجلسات القديمة «logged_out»", v == 2
              and all(x["status"] in ("logged_out", "revoked") for x in SS.sessions([D], now=201)))
        nw = SS.check(D, "5.5.5.5", NUVIO_TV, "m:3", "movie", now=202)
        check("وأول /play بعده ← جلسةٌ جديدة بالإصدار الجديد", nw["allowed"] and nw["session_id"] not in {a["session_id"]})

        print("== القرص، والنسخة ==")
        SS.reset()
        SS.setup(d)
        check("بعد إعادة التشغيل: الإعداد والجلسات من القرص", SS.variant(A) == "session" and SS.account(B)["max_devices"] == 3
              and len(SS.sessions([D], now=202)) >= 2)
        raw = open(os.path.join(d, SS.FILE), encoding="utf-8").read()
        check("ولا كلمة مرور ولا رابط بثّ في المخزن", "password" not in raw and "/live/" not in raw and "/movie/" not in raw)
        SS.set_account(A, variant="standard")
        check("والعودة إلى «standard»", SS.variant(A) == "standard")
        try:
            SS.set_account(A, variant="x")
            bad = False
        except ValueError:
            bad = True
        check("ونسخةٌ غير معروفة ← ValueError", bad)
        os.chmod(d, 0o500)
        try:
            r = SS.check(D, "7.7.7.7", NUVIO_PHONE, now=300)
            check("القرص لا يُكتب ← يعمل من الذاكرة (لا يتعطّل التشغيل)", "allowed" in r)
        finally:
            os.chmod(d, 0o700)
    finally:
        SS.reset()
        shutil.rmtree(d, ignore_errors=True)


def through_play():
    print("== /play: الفحص قبل التحويل، والتحويل 302 إلى اللوحة كما هو ==")
    srv = mock_xtream.serve(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    host = f"http://127.0.0.1:{srv.server_address[1]}"
    d = tempfile.mkdtemp(prefix="sessions_play_")
    S.reset()
    SS.reset()
    try:
        tok = S.make_token(d, host, mock_xtream.USER, mock_xtream.PASS)
        cfg = S.read_token(d, tok)
        A_ = {"ip": "1.2.3.4", "ua": NUVIO_PHONE}
        B_ = {"ip": "9.9.9.9", "ua": NUVIO_TV}

        def get(path, client=None):
            code, body, ctype, hdr = S.handle(d, f"/stremio/{tok}/{path}", "https://g", client=client)
            try:
                return code, json.loads(body), hdr
            except ValueError:
                return code, body, hdr
        code, cat, _ = get("catalog/movie/sq_movies.json")
        mids = [m["id"] for m in cat["metas"]][:2]
        code, st, _ = get(f"stream/movie/{quote(mids[0], safe='')}.json")
        play1 = st["streams"][-1]["url"].split(f"/stremio/{tok}/", 1)[1]
        code, st2, _ = get(f"stream/movie/{quote(mids[1], safe='')}.json")
        play2 = st2["streams"][-1]["url"].split(f"/stremio/{tok}/", 1)[1]
        code, _, h0 = get(play1, A_)
        panel_url = h0.get("Location", "")
        check("«standard» (بلا ضبط): التحويل 302 إلى اللوحة كما كان، لأي جهاز", code == 302 and panel_url.startswith(host)
              and get(play1, B_)[2].get("Location") == panel_url and "X-Ssouq-Session" not in h0, panel_url[:60])
        check("وروابط قائمة التشغيل بصيغتها (‏/play/<النوع>/<المعرّف>/<المصدر>)", play1.startswith("play/movie/"))
        acct = S.session_account(cfg)
        SS.set_account(acct, owner="acct1", variant="session")
        S.account(cfg)                                    # ‏max_connections من اللوحة في الذاكرة (1)
        code, _, ha = get(play1, A_)
        check("«session»: الجهاز A ← التحويل نفسه إلى اللوحة (لا وسيط)", code == 302 and ha.get("Location") == panel_url)
        code, _, hb = get(play1, B_)
        verdict = json.loads(hb.get("X-Ssouq-Session") or "{}")
        check("والجهاز B ← رفضٌ بحالةٍ واضحة من اللوحة (‏max_connections = 1)", code == 302 and verdict ==
              {"allowed": False, "reason": "CONCURRENT_DEVICE_LIMIT", "active_devices": 1, "max_devices": 1}, json.dumps(verdict))
        check("وتحويله إلى فيديو التنبيه (احتياطًا للعرض)، لا إلى اللوحة", hb.get("Location") == "https://g/static/stremio/alert-limit.mp4"
              and host not in hb.get("Location", "") and hb.get("Cache-Control") == "no-store")
        code, sl, hs = get(f"stream/movie/{quote(mids[0], safe='')}.json", B_)
        check("وقائمة التشغيل للجهاز B: أول سطرٍ الرسالة بعدد الأجهزة، ولا تُحفظ", sl["streams"][0]["name"].startswith("⚠️")
              and sl["streams"][0]["title"].startswith("الحساب مستخدم حاليًا على جهاز آخر.") and "1 من 1" in sl["streams"][0]["title"]
              and hs.get("Cache-Control") == "no-store" and len(sl["streams"]) == len(st["streams"]) + 1, json.dumps(sl["streams"][0], ensure_ascii=False))
        code, sa, _ = get(f"stream/movie/{quote(mids[0], safe='')}.json", A_)
        check("وللجهاز A: القائمة كما هي بلا رسالة", [x["url"] for x in sa["streams"]] == [x["url"] for x in st["streams"]])
        check("وفيديوهات التنبيه موجودة على الموقع (‏static/stremio)", all(os.path.getsize(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
              "static", "stremio", f)) > 1000 for f in S.ALERT_FILE.values()))
        code, _, ha2 = get(play2, A_)
        check("والجهاز A بفيلمٍ آخر ← يُسمح (جلسته نفسها)", code == 302 and ha2.get("Location", "").startswith(host)
              and len(SS.sessions([acct])) == 1 and SS.sessions([acct])[0]["content_id"] == mids[1])
        SS.revoke(SS.sessions([acct])[0]["session_id"])
        code, _, hr = get(play1, A_)
        check("بعد إلغاء جلسة A ← لا /play جديد منه (فيديو «تم تسجيل الدخول من جهاز آخر»)",
              hr.get("Location") == "https://g/static/stremio/alert-revoked.mp4"
              and json.loads(hr["X-Ssouq-Session"])["reason"] == "SESSION_REVOKED")
        check("والجهاز B الآن ← يُسمح", get(play1, B_)[2].get("Location") == panel_url)
        SS.set_account(acct, variant="standard")
        check("والعودة إلى «standard» ← كما كانت لكل جهاز", get(play1, A_)[2].get("Location") == panel_url)
        code, sx, hx = get(f"stream/movie/{quote(mids[0], safe='')}.json", B_)
        check("و«standard»: قائمة التشغيل تُحفظ كما كانت (10 دقائق) بلا رسالة", "max-age=600" in hx.get("Cache-Control", "")
              and not sx["streams"][0]["name"].startswith("⚠️"))
        code, man, _ = get("manifest.json")
        check("ومعرّف الإضافة لم يتغيّر بالنسخة", man["id"] == S.manifest_id(cfg))
    finally:
        srv.shutdown()
        S.reset()
        SS.reset()
        shutil.rmtree(d, ignore_errors=True)


def admin():
    print("== الأداة: لا يمسّ إلا خطوط العميل وجلساتها ==")
    d = tempfile.mkdtemp(prefix="sessions_admin_")
    os.environ["XM_DATA"] = d
    import xm_lines as X
    X.DATA_DIR = d
    SS.reset()
    SS.setup(d)
    mine, other = SS.account_key("h.example", "me"), SS.account_key("h.example", "them")
    X.stremio_session_lines = lambda acct: {mine: {"username": "me", "gate": "سمارت", "platforms": ["Nuvio"], "token": ""}}
    acct = {"id": "acctA"}
    try:
        data = X.stremio_sessions_post(acct, {"action": "account", "key": mine, "variant": "session", "max_devices": ""})
        check("خطّه ← «session» وحدّه من اللوحة (فارغ)", data["accounts"][0]["variant"] == "session" and data["accounts"][0]["max_devices"] is None
              and SS.account(mine)["owner"] == "acctA")
        theirs = SS.check(other, "1.1.1.1", NUVIO_PHONE, now=10)
        try:
            X.stremio_sessions_post(acct, {"action": "revoke", "session_id": SS.check(other, "1.1.1.1", NUVIO_PHONE)["session_id"] or "x"})
            refused = False
        except ValueError:
            refused = True
        check("وجلسة خطٍّ ليس له ← لا يلغيها", refused and theirs is not None)
        try:
            X.stremio_sessions_post(acct, {"action": "logout_all", "key": other})
            refused = False
        except ValueError:
            refused = True
        check("ولا «خروج من كل الأجهزة» لخطٍّ ليس له", refused and SS.account(other)["version"] == 1)
        s1 = SS.check(mine, "2.2.2.2", NUVIO_PHONE, "m:1", "movie", panel_max=1)
        data = X.stremio_sessions_post(acct, {"action": "revoke", "session_id": s1["session_id"]})
        check("وإلغاء جلسةٍ من خطّه ← «ملغاة» في القائمة", [x["status"] for x in data["sessions"]] == ["revoked"] and data["sessions"][0]["username"] == "me")
        data = X.stremio_sessions_post(acct, {"action": "settings", "timeout_vod_h": "2", "timeout_live_h": "0.5", "default_max": "2"})
        check("والمهلة بالساعات من الصفحة", data["settings"] == {"timeout_vod": 7200, "timeout_live": 1800, "default_max": 2})
        try:
            X.stremio_sessions_post(acct, {"action": "settings", "timeout_vod_h": "abc"})
            refused = False
        except ValueError:
            refused = True
        check("وقيمةٌ لا تصلح ← رسالة", refused)
    finally:
        SS.reset()
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    core()
    through_play()
    admin()
    print(f"\nResult: \033[32m{passed} passed\033[0m, " + (f"\033[31m{failed} failed\033[0m" if failed else "0 failed"))
    sys.exit(1 if failed else 0)

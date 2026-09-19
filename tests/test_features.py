#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ميزات جديدة عبر بوابة فالكون وهمية: أسماء عربية، حالة (نقاط/آخر يوزر)،
بحث بالـ user/pass، رابط شرح عام لكل البوابات، وكشف الإنشاء المباشر.
تشغيل:  python tests/test_features.py
"""
import os, sys, json, time, shutil, tempfile, subprocess, http.cookiejar, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
FALCON_PORT = int(os.environ.get("FALCON_PORT", "9677")); ADMIN_PORT = int(os.environ.get("ADMIN_PORT2", "9679"))
ADMIN = f"http://127.0.0.1:{ADMIN_PORT}"; FALCON = f"http://127.0.0.1:{FALCON_PORT}/api/v1"
_p = _f = 0
def check(l, c, x=""):
    global _p, _f
    print((f"  \033[32mPASS\033[0m  {l}" if c else f"  \033[31mFAIL\033[0m  {l}") + (f"  ({x})" if x else ""))
    _p += 1 if c else 0; _f += 0 if c else 1

def main():
    global _p, _f
    data_dir = tempfile.mkdtemp(prefix="feat_")
    env = dict(os.environ, XM_DATA=data_dir, XM_BIND="127.0.0.1", XM_PORT=str(ADMIN_PORT))
    falcon = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_falcon.py"), str(FALCON_PORT), "testkey"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    app = subprocess.Popen([sys.executable, os.path.join(ROOT, "xm_lines.py"), "web"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cj = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    def jreq(path, obj=None):
        data = json.dumps(obj).encode() if obj is not None else None
        req = urllib.request.Request(ADMIN + path, data=data, headers={"Content-Type": "application/json"}, method="POST" if obj is not None else "GET")
        try: r = op.open(req, timeout=15); return r.getcode(), json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try: return e.code, json.loads(e.read() or b"{}")
            except Exception: return e.code, {}
    def up(u):
        for _ in range(60):
            try: urllib.request.urlopen(u, timeout=0.3); return
            except urllib.error.HTTPError: return
            except Exception: time.sleep(0.1)
    try:
        up(ADMIN + "/admin/login"); up(FALCON + "/me")
        jreq("/admin/api/setup", {"password": "admin123"})
        jreq("/admin/api/accounts", {"name": "Ali", "user": "ali", "password": "pw_ali", "gates": [
            {"name": "فالكون", "mode": "falcon", "api_url": FALCON, "api_key": "testkey"}]})
        op.open(ADMIN + "/admin/logout")
        jreq("/admin/api/login", {"user": "ali", "password": "pw_ali"})
        _, me = jreq("/admin/api/me"); gid = me["gates"][0]["id"]

        print("== 1. Arabic package names ==")
        _, d = jreq("/admin/api/packages?gate=" + gid)
        names = [p["name"] for p in d.get("packages", [])]
        check("packages show Arabic", "شهر" in names and "3 أشهر" in names and any("جهاز" in n for n in names), " / ".join(names))

        print("\n== 2. Gate status (credits + last user) ==")
        _, s = jreq("/admin/api/gate-status?gate=" + gid)
        check("status has credits", s.get("credits") == 100.0, str(s.get("credits")))
        check("status has total + last user", s.get("total") == 5 and s.get("last_username") == "user005",
              "total=%s last=%s" % (s.get("total"), s.get("last_username")))

        print("\n== 3. Search by username and by password ==")
        _, d = jreq("/admin/api/search?gate=" + gid + "&q=user003")
        check("search by username", len(d.get("results", [])) == 1 and d["results"][0]["username"] == "user003")
        _, d = jreq("/admin/api/search?gate=" + gid + "&q=pass004")
        check("search by password (client-side scan)", len(d.get("results", [])) == 1 and d["results"][0]["username"] == "user004")

        print("\n== 4. Global guide URL for all gates ==")
        _, d = jreq("/admin/api/myguide", {"guide_url": "https://guide.ssouq.com/"})
        check("guide saved", d.get("ok") and d.get("guide_url") == "https://guide.ssouq.com/")
        _, d = jreq("/admin/api/packages?gate=" + gid)
        check("packages reflect the account guide", d.get("guide_url") == "https://guide.ssouq.com/")

        print("\n== 5. Create uses Falcon + Arabic + guide; status detects the new user ==")
        _, d = jreq("/admin/api/create", {"gate": gid, "package_id": "167", "username": "newone", "password": "np", "count": 1})
        ln = (d.get("lines") or [{}])[0].get("line", "")
        check("line new-format with host + guide", " User newone " in ln and "s.falconiptv.ink" in ln and "Guide https://guide.ssouq.com/" in ln, ln[:70])
        _, s2 = jreq("/admin/api/gate-status?gate=" + gid)
        check("status now shows the new last user + fewer credits", s2.get("last_username") == "newone" and s2.get("credits") == 99.5,
              "last=%s credits=%s" % (s2.get("last_username"), s2.get("credits")))
    finally:
        for pr in (app, falcon):
            pr.terminate()
            try: pr.wait(timeout=5)
            except Exception: pr.kill()
        shutil.rmtree(data_dir, ignore_errors=True)
    print("\n----------------------------------------")
    print(f"Result: \033[32m{_p} passed\033[0m, " + (f"\033[31m{_f} failed\033[0m" if _f else "0 failed"))
    sys.exit(1 if _f else 0)

if __name__ == "__main__":
    main()

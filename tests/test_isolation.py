#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
عزل الأشخاص: كل شخص يوزر مستقل، يضيف بواباته، ولا يرى/يستخدم بوابات غيره.
تشغيل:  python tests/test_isolation.py
"""
import os, sys, json, time, shutil, tempfile, subprocess, http.cookiejar, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
PANEL_PORT = int(os.environ.get("PANEL_PORT", "9478")); ADMIN_PORT = int(os.environ.get("ADMIN_PORT", "9479"))
ADMIN = f"http://127.0.0.1:{ADMIN_PORT}"; PANEL = f"http://127.0.0.1:{PANEL_PORT}"
_p = _f = 0
def check(l, c, x=""):
    global _p, _f
    print((f"  \033[32mPASS\033[0m  {l}" if c else f"  \033[31mFAIL\033[0m  {l}") + (f"  ({x})" if x else ""));
    globals().__setitem__("_p", _p + 1) if c else globals().__setitem__("_f", _f + 1)

def session():
    cj = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    def jreq(path, obj=None, method=None):
        data = json.dumps(obj).encode() if obj is not None else None
        req = urllib.request.Request(ADMIN + path, data=data, headers={"Content-Type": "application/json"},
                                     method=method or ("POST" if obj is not None else "GET"))
        try:
            r = op.open(req, timeout=15); return r.getcode(), json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try: return e.code, json.loads(e.read() or b"{}")
            except Exception: return e.code, {}
    return op, jreq

def main():
    data_dir = tempfile.mkdtemp(prefix="iso_")
    env = dict(os.environ, XM_DATA=data_dir, XM_BIND="127.0.0.1", XM_PORT=str(ADMIN_PORT))
    panel = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_panel.py"), str(PANEL_PORT), "demo", "secret"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    app = subprocess.Popen([sys.executable, os.path.join(ROOT, "xm_lines.py"), "web"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    def up(u):
        for _ in range(60):
            try: urllib.request.urlopen(u, timeout=0.3); return
            except urllib.error.HTTPError: return
            except Exception: time.sleep(0.1)
    try:
        up(ADMIN + "/admin/login")
        # admin creates two LOGIN-ONLY persons
        opA, aReq = session()   # will be admin, then person A
        aReq("/admin/api/setup", {"password": "admin123"})
        aReq("/admin/api/accounts", {"name": "Ahmed", "user": "ahmed", "password": "pw_ahmed", "gates": []})
        aReq("/admin/api/accounts", {"name": "Sara", "user": "sara", "password": "pw_sara", "gates": []})

        # Person A (ahmed) logs in and adds their own gate
        opA, aReq = session()
        aReq("/admin/api/login", {"user": "ahmed", "password": "pw_ahmed"})
        _, d = aReq("/admin/api/mygates", {"name": "بوابة أحمد", "mode": "web", "host": "http://a.host",
                                           "panel_base": PANEL, "panel_user": "demo", "panel_pass": "secret"})
        gA = d["gates"][0]["id"]
        check("A added their own gate", len(d["gates"]) == 1)

        # Person B (sara) logs in and adds their own gate
        opB, bReq = session()
        bReq("/admin/api/login", {"user": "sara", "password": "pw_sara"})
        _, d = bReq("/admin/api/mygates", {"name": "بوابة سارة", "mode": "web", "host": "http://b.host",
                                           "panel_base": PANEL, "panel_user": "demo", "panel_pass": "secret"})
        gB = d["gates"][0]["id"]
        check("B added their own gate", len(d["gates"]) == 1)

        print("\n-- isolation --")
        # A sees only A's gate
        _, me = aReq("/admin/api/me")
        ids = [g["id"] for g in me.get("gates", [])]
        check("A's /me lists only A's gate", ids == [gA], ",".join(ids))
        _, mg = aReq("/admin/api/mygates")
        check("A's mygates lists only A's gate", [g["id"] for g in mg.get("gates", [])] == [gA])

        # A cannot load B's packages
        _, d = aReq("/admin/api/packages?gate=" + gB)
        check("A cannot use B's gate for packages", d.get("error") == "اختر بوابة" or d.get("packages") is None, json.dumps(d, ensure_ascii=False)[:60])
        # A cannot fetch B's captcha (raw GET -> 403)
        code = None
        try:
            r = opA.open(ADMIN + "/admin/api/web/captcha?gate=" + gB, timeout=10); code = r.getcode()
        except urllib.error.HTTPError as e:
            code = e.code
        check("A cannot fetch B's gate captcha (403)", code == 403, "http=%s" % code)
        # A cannot create on B's gate
        c, d = aReq("/admin/api/create", {"gate": gB, "package_id": "1", "count": 1})
        check("A cannot create on B's gate", d.get("error") == "اختر بوابة", json.dumps(d, ensure_ascii=False)[:60])
        # A deleting B's gate id does nothing to B
        aReq("/admin/api/mygates/delete", {"id": gB})
        _, mg = bReq("/admin/api/mygates")
        check("A cannot delete B's gate", [g["id"] for g in mg.get("gates", [])] == [gB])

        # B still independent and intact
        _, meB = bReq("/admin/api/me")
        check("B's gate intact and only B's", [g["id"] for g in meB.get("gates", [])] == [gB])
    finally:
        for pr in (app, panel):
            pr.terminate()
            try: pr.wait(timeout=5)
            except Exception: pr.kill()
        shutil.rmtree(data_dir, ignore_errors=True)
    print("\n----------------------------------------")
    print(f"Result: \033[32m{_p} passed\033[0m, " + (f"\033[31m{_f} failed\033[0m" if _f else "0 failed"))
    sys.exit(1 if _f else 0)

if __name__ == "__main__":
    main()

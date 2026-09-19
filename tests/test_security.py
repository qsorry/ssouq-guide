#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
أمن البيانات:
  - كلمة مرور الدخول تُخزَّن hash (لا تُسترجع)، ولا تظهر في أي رد للمتصفح.
  - أسرار اللوحات (panel_pass/api_key) تبقى مشفَّرة على القرص، وتُحجب في الردود.
  - التعديل بحقل فارغ يُبقي القيمة القديمة (والدخول يظل يعمل).
تشغيل:  python tests/test_security.py
"""
import os, sys, json, time, shutil, tempfile, subprocess, http.cookiejar, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
PANEL_PORT = int(os.environ.get("PANEL_PORT", "9578")); ADMIN_PORT = int(os.environ.get("ADMIN_PORT", "9579"))
ADMIN = f"http://127.0.0.1:{ADMIN_PORT}"; PANEL = f"http://127.0.0.1:{PANEL_PORT}"
_p = _f = 0
def check(l, c, x=""):
    global _p, _f
    print((f"  \033[32mPASS\033[0m  {l}" if c else f"  \033[31mFAIL\033[0m  {l}") + (f"  ({x})" if x else ""))
    _p += 1 if c else 0; _f += 0 if c else 1

def sess():
    cj = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    def jreq(path, obj=None):
        data = json.dumps(obj).encode() if obj is not None else None
        req = urllib.request.Request(ADMIN + path, data=data, headers={"Content-Type": "application/json"},
                                     method="POST" if obj is not None else "GET")
        try:
            r = op.open(req, timeout=15); return r.getcode(), json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try: return e.code, json.loads(e.read() or b"{}")
            except Exception: return e.code, {}
    return op, jreq

def main():
    global _p, _f
    data_dir = tempfile.mkdtemp(prefix="sec_")
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
        op, jreq = sess()
        jreq("/admin/api/setup", {"password": "admin123"})
        _, d = jreq("/admin/api/accounts", {"name": "Ali", "user": "okyesno", "password": "998661plain",
                    "gates": [{"name": "مرح", "mode": "web", "host": "http://h", "panel_base": PANEL,
                               "panel_user": "demo", "panel_pass": "PANELSECRET"}]})
        acc = next((a for a in d["accounts"] if a["user"] == "okyesno"), {})
        print("== responses never carry secrets ==")
        check("account response has NO tool password", "password" not in acc)
        check("account response flags has_password", acc.get("has_password") is True)
        g = (acc.get("gates") or [{}])[0]
        check("gate response has NO panel_pass value", g.get("panel_pass") == "")
        check("gate response flags has_panel_pass", g.get("has_panel_pass") is True)
        blob = json.dumps(d, ensure_ascii=False)
        check("no plaintext secret anywhere in the response", "998661plain" not in blob and "PANELSECRET" not in blob)

        print("\n== stored form on disk ==")
        raw = open(os.path.join(data_dir, "accounts.json"), encoding="utf-8").read()
        disk = json.loads(raw)
        pw = disk["accounts"][0]["password"]
        check("tool password stored as a HASH (salt+hash), not text", isinstance(pw, dict) and "salt" in pw and "hash" in pw)
        check("tool plaintext NOT on disk", "998661plain" not in raw)
        check("panel secret encrypted on disk", "PANELSECRET" not in raw and "enc:1:" in raw)

        print("\n== login still works, and edit keeps old secrets ==")
        op2, jreq2 = sess()
        c, d = jreq2("/admin/api/login", {"user": "okyesno", "password": "998661plain"})
        check("login works with the original password", d.get("role") == "account")
        # edit the account (as admin) with EMPTY password + EMPTY panel_pass -> keep both
        gid = acc["gates"][0]["id"]
        _, d = jreq("/admin/api/accounts", {"id": acc["id"], "name": "Ali", "user": "okyesno", "password": "",
                    "gates": [{"id": gid, "name": "مرح", "mode": "web", "host": "http://h", "panel_base": PANEL,
                               "panel_user": "demo", "panel_pass": ""}]})
        check("edit with empty fields succeeds", any(a["user"] == "okyesno" for a in d.get("accounts", [])), d.get("error") or "ok")
        op3, jreq3 = sess()
        c, d = jreq3("/admin/api/login", {"user": "okyesno", "password": "998661plain"})
        check("login STILL works after empty-password edit (old kept)", d.get("role") == "account")
        raw2 = open(os.path.join(data_dir, "accounts.json"), encoding="utf-8").read()
        check("panel secret still stored (kept on empty edit)", "enc:1:" in raw2)
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

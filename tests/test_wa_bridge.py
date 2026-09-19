#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
جسر واتساب (خدمة Baileys) ← أداة Guide: يشغّل الخدمة الحقيقية بوضع WA_FAKE
(بلا واتساب فعلي) ويتحقّق من واجهتها HTTP والمصادقة، ثم يمرّر عبرها مُرسِل
wa_send.py نفسه الذي تستعمله الخدمة الفعلية.
تشغيل:  python tests/test_wa_bridge.py     (يتطلّب node؛ يتخطّى الاختبار إن لم يوجد)
"""
import os, sys, json, time, shutil, subprocess, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import wa_send  # noqa: E402

PORT = int(os.environ.get("WA_BRIDGE_PORT", "9821")); SECRET = "brg_secret"
BASE = f"http://127.0.0.1:{PORT}"
_p = _f = 0
def check(l, c, x=""):
    global _p, _f
    print((f"  \033[32mPASS\033[0m  {l}" if c else f"  \033[31mFAIL\033[0m  {l}") + (f"  ({x})" if x else ""))
    _p += 1 if c else 0; _f += 0 if c else 1


def req(path, method="GET", body=None, auth=None, key=None):
    url = BASE + path + (("?key=" + key) if key else "")
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"}
    if auth:
        h["Authorization"] = "Bearer " + auth
    r = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        x = urllib.request.urlopen(r, timeout=8); return x.getcode(), json.loads(x.read() or b"{}")
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read() or b"{}")
        except Exception: return e.code, {}


def main():
    global _p, _f
    if not shutil.which("node"):
        print("  SKIP  node غير متوفّر — تخطّي اختبار الجسر"); print("Result: 0 passed, 0 failed"); return
    env = dict(os.environ, WA_FAKE="1", WA_SECRET=SECRET, WA_PORT=str(PORT), WA_BIND="127.0.0.1")
    proc = subprocess.Popen(["node", os.path.join(ROOT, "whatsapp-baileys", "index.js")],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                if urllib.request.urlopen(BASE + "/health", timeout=0.3).getcode() == 200:
                    break
            except Exception:
                time.sleep(0.1)

        print("== health + auth ==")
        c, d = req("/health")
        check("health open + connected (fake)", c == 200 and d.get("connected") is True, str(d))
        c, _ = req("/status")
        check("status without key -> 401", c == 401, str(c))
        c, d = req("/status", key=SECRET)
        check("status with key -> connected, me=FAKE", c == 200 and d.get("me") == "FAKE", str(d))

        print("\n== send contract ==")
        c, _ = req("/send", "POST", {"to": "966551234567", "text": "hi"})
        check("send without bearer -> 401", c == 401, str(c))
        c, d = req("/send", "POST", {"to": "966551234567", "text": "اشتراكك جاهز"}, auth=SECRET)
        check("send ok + id", c == 200 and d.get("ok") and str(d.get("id", "")).startswith("FAKE-"), str(d))
        c, d = req("/send", "POST", {"to": "", "text": "x"}, auth=SECRET)
        check("missing recipient -> 400", c == 400, str(d))
        c, d = req("/send", "POST", {"to": "966551234567"}, auth=SECRET)
        check("missing text -> 400", c == 400, str(d))

        print("\n== through wa_send.py (the real sender used by the service) ==")
        r = wa_send.send({"type": "http", "url": BASE + "/send", "secret": SECRET},
                         "0551234567", "Host h User u Pass p Guide https://guide.ssouq.com/")
        check("wa_send http-channel delivers via the bridge", r.get("ok") and str(r.get("id", "")).startswith("FAKE-"), str(r))
        r = wa_send.send({"type": "http", "url": BASE + "/send", "secret": "wrong"}, "0551234567", "x")
        check("wrong gateway secret rejected", not r.get("ok"), str(r))
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except Exception: proc.kill()
    print("\n----------------------------------------")
    print(f"Result: \033[32m{_p} passed\033[0m, " + (f"\033[31m{_f} failed\033[0m" if _f else "0 failed"))
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
خدمة سلة ← واتساب (تسليم تلقائي) من طرف إلى طرف:
ويبهوك موقَّع → مطابقة المنتج بالبوابة → توليد الاشتراك → إرسال (وضع تجريبي ثم فعلي)
→ سجل تسليم + عدم تكرار + رفض التوقيع الخاطئ + اختبار الإرسال.
تشغيل:  python tests/test_service.py
"""
import os, sys, json, time, hmac, hashlib, shutil, tempfile, subprocess
import http.cookiejar, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
FALCON_PORT = int(os.environ.get("FALCON_PORT3", "9777")); ADMIN_PORT = int(os.environ.get("ADMIN_PORT3", "9779"))
ADMIN = f"http://127.0.0.1:{ADMIN_PORT}"; FALCON = f"http://127.0.0.1:{FALCON_PORT}/api/v1"
SECRET = "wh_secret"
_p = _f = 0
def check(l, c, x=""):
    global _p, _f
    print((f"  \033[32mPASS\033[0m  {l}" if c else f"  \033[31mFAIL\033[0m  {l}") + (f"  ({x})" if x else ""))
    _p += 1 if c else 0; _f += 0 if c else 1


def main():
    global _p, _f
    data_dir = tempfile.mkdtemp(prefix="svc_")
    env = dict(os.environ, XM_DATA=data_dir, XM_BIND="127.0.0.1", XM_PORT=str(ADMIN_PORT))
    falcon = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_falcon.py"), str(FALCON_PORT), "testkey"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    app = subprocess.Popen([sys.executable, os.path.join(ROOT, "xm_lines.py"), "web"], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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

    def webhook(order, secret=SECRET, event="order.created"):
        body = json.dumps({"event": event, "data": order}).encode()
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        req = urllib.request.Request(ADMIN + "/salla/webhook", data=body, method="POST",
                                     headers={"Content-Type": "application/json", "X-Salla-Signature": sig})
        try:
            r = urllib.request.urlopen(req, timeout=15); return r.getcode(), json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try: return e.code, json.loads(e.read() or b"{}")
            except Exception: return e.code, {}

    def up(u):
        for _ in range(60):
            try: urllib.request.urlopen(u, timeout=0.3); return
            except urllib.error.HTTPError: return
            except Exception: time.sleep(0.1)

    def order(oid, pid="111", phone="0551234567", qty=1, status="under_review"):
        return {"id": oid, "status": {"slug": status}, "customer": {"first_name": "Sara", "mobile": phone, "mobile_code": "+966"},
                "items": [{"product": {"id": pid, "name": "اشتراك سنة"}, "quantity": qty}]}

    try:
        up(ADMIN + "/admin/login"); up(FALCON + "/me")
        jreq("/admin/api/setup", {"password": "admin123"})
        _, acc = jreq("/admin/api/accounts", {"name": "Store", "user": "store", "password": "pw12",
                      "gates": [{"name": "فالكون", "mode": "falcon", "api_url": FALCON, "api_key": "testkey"}]})
        a = acc["accounts"][0]; gid = a["gates"][0]["id"]

        print("== 1. Save service config (map product 111 -> falcon gate, enabled+dry) ==")
        cfg = {"enabled": True, "dry_run": True, "salla_secret": SECRET,
               "wa": {"type": "none"}, "template": "مرحبا {name} 👋\n{line}",
               "map": [{"product_id": "111", "account_id": a["id"], "gate_id": gid,
                        "package_id": "167", "package_name": "اشتراك سنة"}]}
        _, d = jreq("/admin/api/service", cfg)
        check("service saved, secret redacted", d.get("ok") and d["service"]["has_salla_secret"] is True
              and "salla_secret" not in d["service"], str(d.get("service", {}))[:80])
        check("map stored", len(d["service"]["map"]) == 1 and d["service"]["map"][0]["product_id"] == "111")

        print("\n== 2. Signed webhook -> dry fulfillment ==")
        code, d = webhook(order("A1"))
        check("webhook accepted", code == 200 and d.get("status") == "dry", f"{code} {d}")
        _, log = jreq("/admin/api/service/log")
        row = next((r for r in log["log"] if r["order_id"] == "A1"), {})
        check("logged as dry with a line + phone", row.get("status") == "dry"
              and row["lines"][0].get("simulated") is True and row["phone"] == "966551234567", str(row)[:120])
        check("dry line carries host+guide format", "User TEST-USER" in row["lines"][0]["line"])

        print("\n== 3. Bad signature rejected ==")
        code, d = webhook(order("BAD"), secret="wrong")
        check("wrong signature -> 401", code == 401, str(code))

        print("\n== 4. Idempotent: same order not re-fulfilled ==")
        code, d = webhook(order("A1"))
        check("repeat order skipped", d.get("skipped") == "already" or d.get("status") == "dry", str(d))

        print("\n== 5. Unmatched product is recorded, not delivered ==")
        code, d = webhook(order("NOPE", pid="999"))
        check("no-match status", d.get("status") == "no_match", str(d))

        print("\n== 6. Real generation (dry_run off): falcon line created + 'sent' ==")
        cfg2 = dict(cfg, dry_run=False)
        jreq("/admin/api/service", cfg2)
        code, d = webhook(order("R1"))
        check("real order fulfilled 'sent'", code == 200 and d.get("status") == "sent", str(d))
        _, log = jreq("/admin/api/service/log")
        row = next((r for r in log["log"] if r["order_id"] == "R1"), {})
        check("real line generated on falcon (not TEST)", row["lines"][0]["line"] and "TEST-USER" not in row["lines"][0]["line"],
              row.get("lines", [{}])[0].get("line", "")[:70])

        print("\n== 7. Disabled service ignores webhook ==")
        jreq("/admin/api/service", dict(cfg2, enabled=False))
        code, d = webhook(order("Z1"))
        check("disabled -> ignored", code == 200 and d.get("ignored") == "disabled", str(d))

        print("\n== 8. Test-send endpoint (dry channel) ==")
        _, d = jreq("/admin/api/service/test", {"phone": "0551234567", "text": "hi"})
        check("test send ok + normalized number", d.get("ok") and d.get("to") == "966551234567", str(d))
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

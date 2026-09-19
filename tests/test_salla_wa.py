#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
وحدات موصّل سلة ومُرسِل واتساب: التوقيع، الهاتف، تحليل الطلب، الإرسال (none/http).
تشغيل:  python tests/test_salla_wa.py
"""
import os, sys, json, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import salla_api, wa_send  # noqa: E402

_p = _f = 0
def check(l, c, x=""):
    global _p, _f
    print((f"  \033[32mPASS\033[0m  {l}" if c else f"  \033[31mFAIL\033[0m  {l}") + (f"  ({x})" if x else ""))
    _p += 1 if c else 0; _f += 0 if c else 1


class _Hdr(dict):
    def get(self, k, d=None):
        for kk, v in self.items():
            if kk.lower() == k.lower():
                return v
        return d


def main():
    global _p, _f
    print("== salla: signature ==")
    body = b'{"event":"order.created","data":{"id":123}}'
    sig = salla_api.sign("shh", body)
    check("valid HMAC signature accepted", salla_api.verify("shh", "", body, _Hdr({"x-salla-signature": sig})))
    check("prefixed sha256= accepted", salla_api.verify("shh", "", body, _Hdr({"X-Salla-Signature": "sha256=" + sig})))
    check("wrong signature rejected", not salla_api.verify("shh", "", body, _Hdr({"x-salla-signature": "deadbeef"})))
    check("token strategy accepted", salla_api.verify("", "tok123", body, _Hdr({"Authorization": "Bearer tok123"})))
    check("no secret/token -> rejected", not salla_api.verify("", "", body, _Hdr({})))

    print("\n== salla: phone normalization ==")
    check("local 05 -> 9665..", salla_api.normalize_phone("0551234567", "+966") == "966551234567")
    check("bare with code field", salla_api.normalize_phone("551234567", "966") == "966551234567")
    check("00 international", salla_api.normalize_phone("00201004", "") == "201004")
    check("already full stays", salla_api.normalize_phone("966551234567", "+966") == "966551234567")
    check("empty -> empty", salla_api.normalize_phone("", "966") == "")

    print("\n== salla: parse order ==")
    payload = {"event": "order.created", "data": {
        "id": 987654, "reference_id": 5001,
        "status": {"slug": "under_review", "name": "قيد المراجعة"},
        "customer": {"first_name": "Sara", "last_name": "M", "mobile": "0551234567", "mobile_code": "+966"},
        "items": [{"product": {"id": 111, "name": "اشتراك سنة", "sku": "IPTV-Y"}, "quantity": 2},
                  {"product": {"id": 222, "name": "اشتراك شهر"}, "quantity": 1}]}}
    o = salla_api.parse_order(payload)
    check("order id", o["order_id"] == "987654", o["order_id"])
    check("phone parsed", o["phone"] == "966551234567", o["phone"])
    check("customer name", o["customer_name"] == "Sara M", o["customer_name"])
    check("two items with product ids", len(o["items"]) == 2 and o["items"][0]["product_id"] == "111", str(o["items"]))
    check("quantity read", o["items"][0]["quantity"] == 2)
    check("paid/confirmed order", salla_api.is_paid(o))
    check("cancelled not paid", not salla_api.is_paid({"status": "canceled"}))
    check("pending payment not paid", not salla_api.is_paid({"status": "pending_payment"}))

    print("\n== wa: none (dry) ==")
    r = wa_send.send({"type": "none"}, "966551234567", "hi")
    check("dry-run ok, marked dry", r["ok"] and r.get("dry") is True)
    check("empty recipient rejected", not wa_send.send({"type": "none"}, "", "hi")["ok"])
    check("cloud missing creds -> error", not wa_send.send({"type": "cloud"}, "966...", "hi")["ok"])

    print("\n== wa: http gateway (mock) ==")
    seen = {}
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            seen["body"] = json.loads(self.rfile.read(n) or b"{}")
            seen["auth"] = self.headers.get("Authorization", "")
            out = json.dumps({"ok": True, "id": "wamid.MOCK"}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H); port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    r = wa_send.send({"type": "http", "url": f"http://127.0.0.1:{port}/send", "secret": "S3"},
                     "966551234567", "Host x User u Pass p")
    check("http send ok + id", r["ok"] and r.get("id") == "wamid.MOCK", str(r))
    check("payload carried to+text", seen["body"].get("to") == "966551234567" and "User u" in seen["body"].get("text", ""))
    check("bearer secret sent", seen["auth"] == "Bearer S3", seen["auth"])
    srv.shutdown()

    print("\n----------------------------------------")
    print(f"Result: \033[32m{_p} passed\033[0m, " + (f"\033[31m{_f} failed\033[0m" if _f else "0 failed"))
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

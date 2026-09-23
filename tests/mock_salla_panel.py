#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""لوحة سلة مزيّفة: تحمي بالكوكيز، وتحوّل إلى /auth بدونها، وتعطي JSON بها."""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GOOD = "salla_session=abc123"
ORDER = {"data": {"id": 708964564, "reference_id": 272053873, "items": [
    {"name": "اشتراك ترفيهي رقمي لمدة 12 شهر", "sku": "MRH-12M-ENT", "codes": [
        {"code": "username:346731410391\nPassowrd:266061955108 host http://ssouqhost.vip"}]}]}}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _ok(self, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _to_auth(self):
        self.send_response(302)
        self.send_header("Location", "/auth?intended_to=%s" % self.path)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if GOOD not in (self.headers.get("Cookie") or ""):
            return self._to_auth()
        if self.path == "/orders":
            b = b"<html>ok</html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            return self.wfile.write(b)
        # المسار الأول من المرشّحات مفقود عمدًا، ليُختبر التجريب بالترتيب
        if self.path.startswith("/api/orders/order/"):
            return self._ok(ORDER)
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9078
    print("mock salla panel :%d" % port, flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()

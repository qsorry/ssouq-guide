#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""لوحة فالكون وهمية للاختبار.  python tests/mock_falcon.py 9077 testkey"""
import sys, json, secrets
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9077
KEY = sys.argv[2] if len(sys.argv) > 2 else "testkey"
CREDITS = [100.0]
PACKAGES = [
    {"id": 167, "package_name": "1months", "official_credits": 0.5, "max_connections": 1},
    {"id": 169, "package_name": "3months", "official_credits": 1.0, "max_connections": 1},
    {"id": 180, "package_name": "1years 2 contact", "official_credits": 4.0, "max_connections": 2},
]
LINES = [{"id": 1000 + i, "username": "user%03d" % i, "password": "pass%03d" % i,
          "status": "active", "expires_at": 1830000000, "max_connections": 1, "package_id": 167}
         for i in range(1, 6)]  # newest = highest id


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _auth(self):
        return self.headers.get("Authorization", "") == "Bearer " + KEY

    def _json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path); path = u.path; qs = parse_qs(u.query)
        if not self._auth():
            return self._json(401, {"ok": False, "error": "unauthorized"})
        if path == "/api/v1/me":
            return self._json(200, {"ok": True, "reseller": {"id": 1543, "username": "okyesno",
                                    "credits": CREDITS[0], "host": "http://s.falconiptv.ink"}})
        if path == "/api/v1/packages":
            return self._json(200, {"ok": True, "packages": PACKAGES})
        if path == "/api/v1/lines":
            per = int(qs.get("per", ["50"])[0]); page = int(qs.get("page", ["1"])[0])
            q = qs.get("q", [""])[0]
            rows = sorted(LINES, key=lambda l: l["id"], reverse=True)
            if q:
                rows = [l for l in rows if q in str(l["username"])]  # server: username only
            total = len(rows)
            start = (page - 1) * per
            return self._json(200, {"ok": True, "total": total, "page": page, "per": per,
                                    "lines": rows[start:start + per]})
        return self._json(404, {"ok": False, "error": "not_found"})

    def do_POST(self):
        if not self._auth():
            return self._json(401, {"ok": False, "error": "unauthorized"})
        if urlparse(self.path).path != "/api/v1/lines":
            return self._json(404, {"ok": False, "error": "not_found"})
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        pid = int(body.get("package_id", 0))
        pkg = next((p for p in PACKAGES if p["id"] == pid), None)
        if not pkg:
            return self._json(400, {"ok": False, "error": "package_not_available"})
        nid = max(l["id"] for l in LINES) + 1
        line = {"id": nid, "username": body.get("username") or str(nid),
                "password": body.get("password") or secrets.token_hex(4),
                "status": "active", "expires_at": 1830000000,
                "max_connections": body.get("max_connections", 1), "package_id": pid}
        LINES.append(line)
        CREDITS[0] = round(CREDITS[0] - pkg["official_credits"], 2)
        return self._json(200, {"ok": True, "line": line})


if __name__ == "__main__":
    print("mock falcon :%d" % PORT, flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()

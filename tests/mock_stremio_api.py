#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""واجهة Stremio وهمية (‏POST /api/<الإجراء>) لاختبار حسابات Stremio الجاهزة بلا إنترنت:
register · login · logout · addonCollectionGet · addonCollectionSet، بالرد نفسه: ‏{"result": …} أو
‏{"error": {"code", "message"}} (كما ردّت api.strem.io: ‏User not found برمز 2، والإيميل المسجّل برمز 36).

  srv.require_letter = True   كلمة مرورٍ أرقامٌ فقط تُرفض (لاختبار إضافة «A»)
  srv.down = True             ‏500 لكل طلب
  srv.users · srv.collections · srv.sessions   الحال للفحص

    python tests/mock_stremio_api.py 9792
"""
import json
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT = [{"manifest": {"id": "com.linvo.cinemeta", "version": "3.0.12", "name": "Cinemeta", "resources": ["catalog", "meta"],
                         "types": ["movie", "series"], "idPrefixes": ["tt"], "catalogs": []},
            "transportUrl": "https://v3-cinemeta.strem.io/manifest.json", "flags": {"official": True, "protected": True}},
           {"manifest": {"id": "org.stremio.opensubtitlesv3", "version": "1.0.0", "name": "OpenSubtitles v3",
                         "resources": ["subtitles"], "types": ["movie", "series"], "catalogs": []},
            "transportUrl": "https://opensubtitles-v3.strem.io/manifest.json", "flags": {"official": True, "protected": False}}]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _out(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        srv = self.server
        srv.hits.append(self.path)
        if srv.down:
            return self._out({"error": "down"}, 500)
        try:
            b = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except ValueError:
            return self._out({"error": {"code": 1, "message": "Invalid JSON"}})
        m = self.path.rsplit("/", 1)[-1]
        err = lambda code, msg, **k: self._out({"error": {"code": code, "message": msg, **k}})  # noqa: E731
        if m == "register":
            email, pw = str(b.get("email", "")).lower(), str(b.get("password", ""))
            if b.get("type") != "Register" or not (b.get("gdpr_consent") or {}).get("tos"):
                return err(1, "Invalid request")
            if email in srv.users:
                return err(36, "User with this email already exists", existingUser=True)   # كما ردّت api.strem.io
            if not pw or (srv.require_letter and pw.isdigit()):
                return err(5, "Password must contain at least one letter")
            srv.users[email] = pw
            srv.collections[email] = json.loads(json.dumps(DEFAULT))
        elif m == "login":
            email, pw = str(b.get("email", "")).lower(), str(b.get("password", ""))
            if email not in srv.users:
                return err(2, "User not found", wrongEmail=True)
            if srv.users[email] != pw:
                return err(3, "Wrong password", wrongPass=True)
        elif m in ("logout", "addonCollectionGet", "addonCollectionSet"):
            email = srv.sessions.get(b.get("authKey"))
            if not email:
                return err(1, "Session does not exist")
            if m == "logout":
                srv.sessions.pop(b.get("authKey"), None)
                return self._out({"result": {"success": True}})
            if m == "addonCollectionGet":
                return self._out({"result": {"addons": srv.collections[email], "lastModified": "2026-10-02T00:00:00Z"}})
            srv.collections[email] = b.get("addons") or []
            return self._out({"result": {"success": True}})
        else:
            return err(1, "Unknown method")
        key = secrets.token_hex(16)
        srv.sessions[key] = email
        self._out({"result": {"authKey": key, "user": {"email": email, "_id": secrets.token_hex(12)}}})


def serve(port):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.users, srv.collections, srv.sessions, srv.hits = {}, {}, {}, []
    srv.require_letter = srv.down = False
    return srv


if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 9792).serve_forever()

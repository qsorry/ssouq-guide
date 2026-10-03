#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""خادم Nuvio وهمي بالواجهة نفسها التي تحقّقنا منها في api.nuvio.tv (‏docs/nuvio.md) — للاختبارات:

  GET  /.well-known/nuvio                          ‏backend_url · publishable_key · capabilities
  POST /auth/v1/signup                             ‏{email, password} ← جلسة (التسجيل بلا تأكيد بريد)؛ مسجَّلٌ ← 422
  POST /auth/v1/token?grant_type=password          ← جلسة؛ كلمة مرورٍ خاطئة ← 400
  POST /rest/v1/rpc/sync_pull_addons               ‏{p_profile_id} ← [{url, name, enabled, sort_order}]
  POST /rest/v1/rpc/sync_push_addons               ‏{p_addons, p_profile_id} — تستبدل القائمة

كل طلبٍ بلا apikey ← 401، وطلبات rpc بلا Bearer جلسةٍ صالحة ← 401. حسابٌ جديد فيه Cinemeta وOpenSubtitles كما في Nuvio.

    srv = serve(); state = srv.state   # users · tokens · addons

ولاختبارات المتصفح (عمليةٌ مستقلة): ‏python tests/mock_nuvio.py 9790، و‏GET /_mock/state الحسابات وإضافاتها.
"""
import json
import secrets
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

KEY = "anon-public-key"
DEFAULTS = [{"url": "https://v3-cinemeta.strem.io/manifest.json", "name": "Cinemeta", "enabled": True, "sort_order": 0},
            {"url": "https://opensubtitles-v3.strem.io", "name": "OpenSubtitles v3", "enabled": True, "sort_order": 1}]


class State:
    def __init__(self):
        self.users = {}          # email ← {id, password}
        self.tokens = {}         # access_token ← user id
        self.addons = {}         # (user id, profile) ← [items]
        self.calls = []
        self.down = False
        self.lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _session(self, st, uid, email):
        tok = secrets.token_hex(16)
        st.tokens[tok] = uid
        return {"access_token": tok, "refresh_token": secrets.token_hex(8), "token_type": "bearer", "expires_in": 3600,
                "user": {"id": uid, "email": email}}

    def do_GET(self):
        st = self.server.state
        if urlsplit(self.path).path == "/_mock/state":
            with st.lock:
                uid = {v["id"]: e for e, v in st.users.items()}
                return self._send(200, {"users": {e: v["password"] for e, v in st.users.items()},
                                        "addons": {uid.get(k[0], k[0]): v for k, v in st.addons.items()}})
        if urlsplit(self.path).path == "/.well-known/nuvio":
            base = f"http://127.0.0.1:{self.server.server_address[1]}"
            return self._send(200, {"version": 1, "service": "nuvio", "self_hosted": True, "backend_url": base,
                                    "publishable_key": KEY, "capabilities": {"email_password_auth": True, "tv_login": True}})
        return self._send(404, {"message": "not found"})

    def do_POST(self):
        st = self.server.state
        u = urlsplit(self.path)
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        with st.lock:
            st.calls.append(u.path)
            if st.down:
                return self._send(503, {"message": "down"})
            if self.headers.get("apikey") != KEY:
                return self._send(401, {"message": "No API key found in request"})
            if u.path == "/auth/v1/signup":
                email, pw = str(body.get("email") or "").lower(), str(body.get("password") or "")
                if email in st.users:
                    return self._send(422, {"code": 422, "msg": "User already registered"})
                if len(pw) < 6:
                    return self._send(422, {"code": 422, "msg": "Password should be at least 6 characters"})
                uid = str(uuid.uuid4())
                st.users[email] = {"id": uid, "password": pw}
                st.addons[(uid, 1)] = [dict(a) for a in DEFAULTS]
                return self._send(200, self._session(st, uid, email))
            if u.path == "/auth/v1/token" and "grant_type=password" in (u.query or ""):
                email, pw = str(body.get("email") or "").lower(), str(body.get("password") or "")
                rec = st.users.get(email)
                if not rec or rec["password"] != pw:
                    return self._send(400, {"error": "invalid_grant", "error_description": "Invalid login credentials"})
                return self._send(200, self._session(st, rec["id"], email))
            auth = self.headers.get("Authorization", "")
            uid = st.tokens.get(auth[7:]) if auth.startswith("Bearer ") else None
            if u.path.startswith("/rest/v1/rpc/") and not uid:
                return self._send(401, {"message": "JWT expired"})
            if u.path == "/rest/v1/rpc/sync_pull_addons":
                return self._send(200, list(st.addons.get((uid, int(body.get("p_profile_id") or 1)), [])))
            if u.path == "/rest/v1/rpc/sync_push_addons":
                items = body.get("p_addons") or []
                st.addons[(uid, int(body.get("p_profile_id") or 1))] = [
                    {"url": i["url"], "name": i.get("name"), "enabled": i.get("enabled", True), "sort_order": i.get("sort_order", 0)}
                    for i in items]
                return self._send(200, None)
        return self._send(404, {"message": "not found"})


def serve(port=0):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.state = State()
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    import sys
    import time
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 9790)
    while True:
        time.sleep(3600)

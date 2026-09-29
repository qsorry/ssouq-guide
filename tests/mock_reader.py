#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""خدمة واتساب النظام اللوجستي (whatsapp-reader) وهميةً للاختبار، ومعها منتجات سلة.
  python tests/mock_reader.py 9783 rdr_live

واجهة الخدمة كما في souq-saas/whatsapp-reader/server.js، وكلها بترويسة X-Reader-Secret (وإلا 403):
  POST   /sessions                {tenant, number, callbackUrl, ingestToken, dmCallbackUrl} ← لقطة الجلسة (qr)
  GET    /sessions/<tenant>       ← اللقطة، أو {status: disconnected} بلا جلسة
  POST   /sessions/<tenant>/send  {to, body, media_base64?, media_mime?, media_filename?} ← {ok, waMessageId}
                                  · 404 no_session · 409 not_connected · 422 media_invalid
                                  (و‏to معرّفٌ فيه «@» — قناةٌ ‏…@newsletter — يُرسل إليه كما هو)
  DELETE /sessions/<tenant>       ← {status: disconnected}
وإضافة ssouq-guide (قنوات واتساب):
  GET    /sessions/<tenant>/newsletter?invite=<الرمز>|jid=<…@newsletter> ← {ok, id, name, subscribers, role, invite}
                                  · 404 channel_not_found (القنوات في CHANNELS)
ومفاتيح الاختبار (بالسرّ نفسه):
  POST   /_test/scan/<tenant>     «مُسح الرمز»: تتصل الجلسة برقمها
  POST   /_test/dm/<tenant>       {payload} تُرسل إلى dmCallbackUrl بـ X-Reader-Token كما تفعل الخدمة
                                  ← {code, answer, sent: ما أُرسل بعدها خلال ثانيتين}
  GET    /_test/log               ← {sessions, sent, posts}
ومنتجات سلة العامة (بلا سرّ، SALLA_API=http://127.0.0.1:<port>):
  GET    /store/v1/products?per_page=50 · /store/v1/products/<id>/details
"""
import base64
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SECRET = sys.argv[2] if len(sys.argv) > 2 else "rdr_test"
QR = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
_lock = threading.Lock()
sessions, sent, posts = {}, [], []

PRODUCTS = [
    {"id": 1001, "name": "اشتراك سمارت 3 أشهر | IPTV", "status": "sale", "url": "https://ssouq.com/smart-3m/p1001",
     "price": 99, "sale_price": 79, "image": {"url": "https://cdn.salla.sa/p1001.png"}, "is_out_of_stock": False},
    {"id": 1002, "name": "اشتراك سمارت 12 شهر", "status": "out", "url": "https://ssouq.com/smart-12m/p1002",
     "price": 249, "sale_price": 0, "image": {"url": "https://cdn.salla.sa/p1002.png"}, "is_out_of_stock": True},
    {"id": 1003, "name": "منتج مخفي", "status": "hidden", "url": "https://ssouq.com/hidden/p1003", "price": 10},
]
DETAILS = {"1004": {"id": 1004, "name": "اشتراك يومي", "status": "sale", "url": "https://ssouq.com/day/p1004",
                    "price": 9, "image": {"url": "https://cdn.salla.sa/p1004.png"}}}
# قنوات واتساب: رمز رابطها ← القناة، والرقم المربوط مشرفٌ في الأولى ومتابعٌ في الثانية
CHANNELS = {"0029VaSsouqNews000000000": {"id": "120363000000000001@newsletter", "name": "سمارت سوق | الجديد",
                                         "subscribers": 1520, "role": "ADMIN"},
            "0029VaFollowOnly00000000": {"id": "120363000000000002@newsletter", "name": "قناةٌ أتابعها",
                                         "subscribers": 99, "role": "SUBSCRIBER"}}


def snap(s):
    return {"version": "42", "library": "baileys-mock", "status": s["status"],
            "qr": QR if s["status"] == "qr" else None, "pairingCode": None,
            "number": s["number"], "groups": []}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        raw = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def _store(self):
        path = self.path.split("?")[0]
        if self.headers.get("Store-Identifier") != "831097886":
            return self._send(401, {"error": "store"})
        if path == "/store/v1/products":
            return self._send(200, {"data": PRODUCTS})
        m = re.fullmatch(r"/store/v1/products/(\d+)/details", path)
        if m and m.group(1) in DETAILS:
            return self._send(200, {"data": DETAILS[m.group(1)]})
        return self._send(404, {"error": "not found"})

    def _auth(self):
        if self.headers.get("X-Reader-Secret") != SECRET:
            self._send(403, {"error": "forbidden"})
            return False
        return True

    def do_GET(self):
        if self.path.startswith("/store/"):
            return self._store()
        if not self._auth():
            return
        if self.path == "/_test/log":
            with _lock:
                return self._send(200, {"sessions": sessions, "sent": sent, "posts": posts})
        u = urllib.parse.urlsplit(self.path)
        m = re.fullmatch(r"/sessions/([^/]+)/newsletter", u.path)
        if m:
            s = sessions.get(m.group(1))
            if not s:
                return self._send(404, {"error": "no_session"})
            if s["status"] != "connected":
                return self._send(409, {"error": "not_connected"})
            q = urllib.parse.parse_qs(u.query)
            inv, jid = (q.get("invite") or [""])[0], (q.get("jid") or [""])[0]
            code = inv or next((k for k, c in CHANNELS.items() if c["id"] == jid), "")
            if code not in CHANNELS:
                return self._send(404, {"error": "channel_not_found"})
            return self._send(200, dict(CHANNELS[code], ok=True, invite=code))
        m = re.fullmatch(r"/sessions/([^/]+)", self.path)
        if m:
            s = sessions.get(m.group(1))
            return self._send(200, snap(s) if s else {"version": "42", "status": "disconnected", "groups": []})
        self._send(404, {"error": "not found"})

    def do_DELETE(self):
        if not self._auth():
            return
        m = re.fullmatch(r"/sessions/([^/]+)", self.path)
        if not m:
            return self._send(404, {"error": "not found"})
        with _lock:
            sessions.pop(m.group(1), None)
        self._send(200, {"status": "disconnected", "groups": []})

    def do_POST(self):
        if not self._auth():
            return
        body = self._body()
        if self.path == "/sessions":
            if not body.get("tenant"):
                return self._send(422, {"error": "tenant required"})
            with _lock:
                s = sessions[body["tenant"]] = {
                    "status": "qr", "number": re.sub(r"\D", "", str(body.get("number") or "")),
                    "callbackUrl": body.get("callbackUrl") or "", "dmCallbackUrl": body.get("dmCallbackUrl") or "",
                    "ingestToken": body.get("ingestToken") or ""}
            return self._send(200, snap(s))
        m = re.fullmatch(r"/_test/scan/([^/]+)", self.path)
        if m:
            with _lock:
                s = sessions.get(m.group(1))
                if not s:
                    return self._send(404, {"error": "no_session"})
                s["status"] = "connected"
            return self._send(200, snap(s))
        m = re.fullmatch(r"/_test/dm/([^/]+)", self.path)
        if m:
            s = sessions.get(m.group(1))
            if not s or not s["dmCallbackUrl"]:
                return self._send(404, {"error": "no_session"})
            with _lock:
                mark = len(sent)
            token = body.pop("_token", None) or s["ingestToken"]        # _token: توقيعٌ خاطئ للاختبار
            data = json.dumps(body, ensure_ascii=False).encode()
            rq = urllib.request.Request(s["dmCallbackUrl"], data=data, method="POST", headers={
                "Content-Type": "application/json", "X-Reader-Token": token})
            try:
                with urllib.request.urlopen(rq, timeout=15) as r:
                    code, answer = r.status, json.loads(r.read() or b"{}")
            except urllib.error.HTTPError as e:
                code, answer = e.code, {}
            with _lock:
                posts.append({"code": code, "answer": answer})
            out = []
            for _ in range(20 if code == 200 and answer.get("status") != "ignored" else 3):
                with _lock:
                    out = sent[mark:]
                if out:
                    break
                time.sleep(.1)
            return self._send(200, {"code": code, "answer": answer, "sent": out})
        m = re.fullmatch(r"/sessions/([^/]+)/send", self.path)
        if m:
            s = sessions.get(m.group(1))
            if not s:
                return self._send(404, {"error": "no_session"})
            if s["status"] != "connected":
                return self._send(409, {"error": "not_connected"})
            raw = str(body.get("to") or "")
            to = raw if "@" in raw else re.sub(r"\D", "", raw)      # المعرّف (قناةٌ أو مجموعة) كما هو
            if not to or not body.get("body"):
                return self._send(422, {"error": "to_and_body_required"})
            if to.startswith("966599"):                   # رقمٌ ليس على واتساب
                return self._send(409, {"error": "not_on_whatsapp"})
            item = {"to": to, "body": body["body"]}
            if body.get("media_base64"):                  # مرفقٌ (فيديو الفرز): يُحفظ نوعه وحجمه لا محتواه
                try:
                    size = len(base64.b64decode(body["media_base64"], validate=True))
                except ValueError:
                    return self._send(422, {"error": "media_invalid"})
                item.update(media_mime=body.get("media_mime") or "", media_size=size,
                            media_filename=body.get("media_filename") or "")
            with _lock:
                sent.append(item)
                n = len(sent)
            return self._send(200, {"ok": True, "waMessageId": f"MOCK{n}"})
        self._send(404, {"error": "not found"})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()

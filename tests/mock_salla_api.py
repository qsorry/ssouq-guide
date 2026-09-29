#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""واجهة سلة وهمية لأعداد المحتوى في المتجر (store_sync): منتجاتٌ تُقرأ وتُكتب ويُبحث فيها، ورمزٌ يُجدَّد — بلا إنترنت.

  GET  /admin/v2/products/<id>          المنتج
  PUT  /admin/v2/products/<id>          تحديثٌ جزئي: description وmetadata_description وحدهما يُكتبان، وكل طلبٍ يُسجَّل
  GET  /admin/v2/products?keyword=&page=&per_page=   بحثٌ في الاسم والرمز
  POST /oauth2/token                    grant_type=refresh_token: رمز التجديد يُستعمل مرةً واحدة كما في سلة

والرمز (‏Bearer) من مجموعة الرموز الصالحة وإلا 401. وللاختبارات: ‏drift يغيّر نوع المنتج عند الكتابة، وscope403 يرفض
الكتابة بـ403.

    python tests/mock_salla_api.py 9811
"""
import json
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Store:
    def __init__(self):
        self.products = {}
        self.tokens = {"tok-1"}
        self.refresh = {"ref-1"}
        self.client = ("cid-1", "csecret-1")
        self.puts = []            # (المعرّف، جسم الطلب)
        self.gets = 0
        self.renewals = 0
        self.drift = False
        self.sell = False             # كودٌ يُباع في لحظة الكتابة: الكمية تنقص بحق
        self.scope403 = False
        self.n = 1
        self.lock = threading.Lock()

    def add(self, pid, name, description="", seo="", sku="", status="sale", type_="codes", price=20, quantity=5):
        self.products[str(pid)] = {"id": int(pid), "name": name, "sku": sku, "status": status, "type": type_,
                                   "price": {"amount": price, "currency": "SAR"}, "quantity": quantity,
                                   "description": description, "metadata": {"title": name, "description": seo},
                                   "urls": {"customer": "https://ssouq.com/p%s" % pid, "admin": "https://s.salla.sa/products/%s" % pid}}


def handler(store):
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

        def _auth(self):
            tok = (self.headers.get("Authorization") or "").split(" ", 1)[-1]
            if tok not in store.tokens:
                self._send(401, {"status": 401, "success": False, "error": {"code": "Unauthorized", "message": "The access token is invalid"}})
                return False
            return True

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(n) if n else b""

        def do_GET(self):
            u = urllib.parse.urlsplit(self.path)
            if u.path == "/__state":                    # للاختبارات: المنتجات وما كُتب فيها
                with store.lock:
                    return self._send(200, {"products": store.products, "puts": store.puts, "renewals": store.renewals})
            if not self._auth():
                return
            with store.lock:
                store.gets += 1
                if u.path.startswith("/admin/v2/products/"):
                    p = store.products.get(u.path.rsplit("/", 1)[1])
                    return self._send(200, {"status": 200, "success": True, "data": p}) if p else \
                        self._send(404, {"status": 404, "success": False, "error": {"code": "NotFound", "message": "not found"}})
                if u.path == "/admin/v2/products":
                    q = urllib.parse.parse_qs(u.query)
                    kw = (q.get("keyword") or [""])[0].lower()
                    per, page = int((q.get("per_page") or ["15"])[0]), int((q.get("page") or ["1"])[0])
                    rows = [p for p in store.products.values() if not kw or kw in p["name"].lower() or kw in p["sku"].lower()]
                    pages = max(1, -(-len(rows) // per))
                    return self._send(200, {"status": 200, "success": True, "data": rows[(page - 1) * per:page * per],
                                            "pagination": {"count": len(rows), "total": len(rows), "perPage": per,
                                                           "currentPage": page, "totalPages": pages}})
            self._send(404, {"error": "not found"})

        def do_PUT(self):
            u = urllib.parse.urlsplit(self.path)
            if not self._auth():
                return
            body = json.loads(self._body() or b"{}")
            with store.lock:
                p = store.products.get(u.path.rsplit("/", 1)[1])
                if not p:
                    return self._send(404, {"status": 404, "success": False, "error": {"message": "not found"}})
                if store.scope403:
                    return self._send(403, {"status": 403, "success": False, "error": {"code": "Forbidden", "message": "scope"}})
                store.puts.append((str(p["id"]), body))
                if "description" in body:
                    p["description"] = body["description"]
                if "metadata_description" in body:
                    p["metadata"]["description"] = body["metadata_description"]
                if store.drift:
                    p["type"] = "product"
                if store.sell:
                    p["quantity"] -= 1
                    p["status"] = "out" if p["quantity"] <= 0 else p["status"]
                return self._send(200, {"status": 200, "success": True, "data": p})

        def do_POST(self):
            u = urllib.parse.urlsplit(self.path)
            if u.path != "/oauth2/token":
                return self._send(404, {"error": "not found"})
            f = {k: v[0] for k, v in urllib.parse.parse_qs(self._body().decode()).items()}
            with store.lock:
                if (f.get("grant_type") != "refresh_token" or (f.get("client_id"), f.get("client_secret")) != store.client
                        or f.get("refresh_token") not in store.refresh):
                    return self._send(400, {"error": "invalid_grant", "error_description": "The refresh token is invalid"})
                store.refresh.discard(f["refresh_token"])       # يُستعمل مرةً واحدة
                store.n += 1
                store.renewals += 1
                tok, ref = "tok-%d" % store.n, "ref-%d" % store.n
                store.tokens.add(tok)
                store.refresh.add(ref)
            self._send(200, {"access_token": tok, "expires_in": 1209600, "refresh_token": ref,
                             "scope": "products.read_write offline_access", "token_type": "bearer"})
    return H


def serve(port=0, store=None):
    store = store or Store()
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler(store))
    srv.store = store
    return srv


if __name__ == "__main__":
    s = serve(int(sys.argv[1]) if len(sys.argv) > 1 else 9811)
    s.store.add(1557813796, "اشتراك كاسبر IPTV لمدة 6 أشهر",
                "<p>مكتبة كاسبر: <strong>600+</strong></p><p class=\"ql-align-center\">فيلم مترجم</p>"
                "<h3>آخر تحديث للمكتبة — الثلاثاء 1 سبتمبر 2026</h3>"
                "<p>وصلت إلى <strong>640 فيلمًا</strong> و<strong>28 مسلسلًا</strong>، وقسم 2026 وحده فيه <strong>40 فيلمًا</strong>.</p>",
                "اشتراك كاسبر: +600 فيلم و+20 مسلسل بتحديث يومي")
    s.store.add(153695876, "اشتراك فالكون IPTV لمدة 3 أشهر | FALCON TV PRO", "<p>أكثر من 19,000 فيلم</p>", "", sku="FAL-PRO-03M")
    s.store.add(889146346, "اشتراك IPTV لمدة 3 أشهر | جميع الأجهزة", "<p>20,000+ فيلم</p>", "", sku="MRH-03M")
    print("mock salla on", s.server_address, flush=True)
    s.serve_forever()

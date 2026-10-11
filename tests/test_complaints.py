#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبار الردّ على الشكاوى: معرفة الاشتراك من المنتج/الرمز/الهوست، ونصّ الردّ بجدول تطبيقات اشتراكه،
والبحث برقم الطلب من ثلاثة مصادر (اشتراكات سلة المسحوبة ← فهرس الطلبات وسجلّ سلة ← الطلب من سلة إن لم يُسحب،
بواجهة سلة وهمية بلا إنترنت)، وربط يوزرٍ أُنشئ له، والإرسال وتسجيله.

تشغيل:  python tests/test_complaints.py
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import complaints      # noqa: E402
import panels          # noqa: E402
import renew           # noqa: E402
import salla_api       # noqa: E402
import xm_lines as X   # noqa: E402

_p = _f = 0


def check(label, cond, extra=""):
    global _p, _f
    if cond:
        _p += 1
        print(f"  \033[32mPASS\033[0m  {label}" + (f"  ({extra})" if extra else ""))
    else:
        _f += 1
        print(f"  \033[31mFAIL\033[0m  {label}" + (f"  ({extra})" if extra else ""))


def test_sub_and_text():
    print("== الاشتراك من المنتج، ونصّ الردّ ==")
    check("falcon by name even with the generic IPTV word", complaints.sub_of("اشتراك فالكون IPTV لمدة 3 أشهر | FALCON TV PRO") == "falcon")
    check("falcon by SKU prefix", complaints.sub_of("اشتراك 15 شهر", "FAL-PRO-15M") == "falcon")
    check("smart by SKU prefix MRH", complaints.sub_of("اشتراك IPTV لمدة 15 شهر لجهازين", "MRH-15M-2D") == "smart")
    check("casper by name", complaints.sub_of("اشتراك كاسبر لمدة سنة") == "casper")
    check("gate sub when the product does not say", complaints.sub_of("اشتراك IPTV Smarters Pro لمدة سنة", "", "http://x", gate_sub="casper") == "casper")
    check("host words as the last resort", complaints.sub_of("اشتراك سنة", "", "http://casper-vip.tv:80") == "casper")
    check("unknown stays empty", complaints.sub_of("اشتراك IPTV لمدة سنة") == "")
    check("arabic digits in the order number", complaints.norm_order("٢٨٧ ٣١٤-٦٦٠") == "287314660")
    line = X.guide_copy_text({}, {"host": "http://ssouqhost.vip:80", "guide_url": "https://guide.ssouq.com/#activate/casper"},
                             "333426852552", "4784316512", "http://ssouqhost.vip:80")
    t = complaints.reply_text("ali", "138", line, "casper", [{"username": "999", "password": "888"}])
    check("head names the customer and the order", t.startswith("السلام عليكم ورحمة الله *ali* 👋") and "طلبكم رقم *138*" in t)
    check("the usual guide text with the credentials and the casper server", "📲 طريقة التثبيت والتفعيل" in t
          and "https://guide.ssouq.com/#activate/casper" in t and "سيرفر كاسبر ✅" in t
          and "Host: http://ssouqhost.vip:80\nUser: 333426852552\nPass: 4784316512" in t and "احذف التطبيق القديم" in t, t)
    check("casper app table per device", "اشتراك كاسبر" in t and "آيفون وآيباد: CASPER VIP (أو AroPlayer)" in t
          and "شاشات سامسونج و LG: 0Player برمز 59820658" in t and "هايسنس (VIDAA): Duplecast" in t and "ويندوز وماك: IPTV Smarters Pro" in t)
    check("look-alike apps warning and how to ask for help", "ليس لتطبيق IPTV Smarters Pro وحده" in t and "تطبيقًا عشوائيًا" in t
          and "صورة الشاشة" in t)
    check("a second user of a 2-copy order is appended", "اليوزر 2:*\nUser: 999\nPass: 888" in t)
    check("the order of blocks: head, guide, apps, foot", t.index("📲") < t.index("📱") < t.index("⚠️ *انتبه") < t.index("❓"))
    tf = complaints.reply_text("", "5", "x", "falcon")
    check("falcon table and default name", "عميلنا العزيز" in tf and "تطبيق فالكون" in tf and "0Player برمز 75710072" in tf and "CASPER" not in tf)
    tu = complaints.reply_text("a", "5", "x", "")
    check("unknown sub: generic awareness, no table", "لكل اشتراكٍ وجهاز" in tu and "•" not in tu)
    pb = complaints.product_blurb("smart")
    check("product blurb: before-buy warning + smart table + guide link", pb.startswith("⚠️ قبل الشراء") and "NEXT+" in pb
          and pb.rstrip().endswith("https://guide.ssouq.com/#activate/smart"))


class _Salla:
    """واجهة سلة وهمية: طلبٌ برقمه، وسجلّه بتعليق البيانات (أو بلا تعليق)."""
    def __init__(self):
        self.orders = {}       # ref -> raw
        self.notes = {}        # id -> [note]
        self.calls = []

    def start(self):
        me = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                u = urllib.parse.urlsplit(self.path)
                me.calls.append(u.path + ("?" + u.query if u.query else ""))
                if (self.headers.get("Authorization") or "") != "Bearer tok":
                    return self._out(401, {"error": "bad token"})
                if u.path == "/admin/v2/orders":
                    ref = urllib.parse.parse_qs(u.query).get("reference_id", [""])[0]
                    o = me.orders.get(ref)
                    return self._out(200, {"data": [o] if o else [], "pagination": {"currentPage": 1, "totalPages": 1}})
                m = u.path.split("/")
                if len(m) == 6 and m[-1] == "histories":
                    return self._out(200, {"data": [{"note": n} for n in me.notes.get(m[4], [])]})
                return self._out(404, {"data": []})

            def _out(self, code, obj):
                raw = json.dumps(obj, ensure_ascii=False).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return "http://127.0.0.1:%d" % self.srv.server_address[1]


def _raw_order(ref, oid, name, product, sku="", mobile="0500000009", status="طلبك مؤكد", qty=1):
    return {"id": oid, "reference_id": int(ref), "status": {"name": status}, "date": {"date": "2026-09-01 10:00:00"},
            "customer": {"name": name, "first_name": name, "mobile": mobile, "mobile_code": "+966"},
            "items": [{"name": product, "sku": sku, "quantity": qty, "price": "80"}], "urls": {"admin": "https://s.salla.sa/orders/%s" % oid}}


def test_lookup():
    print("\n== البحث برقم الطلب: المسحوب، والفهرس وسجلّ سلة، والطلب من سلة، والربط، والإرسال ==")
    d = tempfile.mkdtemp(prefix="reply_")
    keep = {k: getattr(X, k) for k in ("DATA_DIR", "dup_wa_send", "reader_status")}
    api_keep = salla_api.API
    sal = _Salla()
    salla_api.API = sal.start()
    try:
        X.DATA_DIR = d
        gates = [{"id": "g1", "name": "بوابة كاسبر", "host": "http://ssouqhost.vip:80", "mode": "web", "web_flavor": "casper"},
                 {"id": "g2", "name": "بوابة مرح", "host": "http://m.ink", "mode": "web"}]
        acct = {"id": "acc1", "guide_url": "https://guide.ssouq.com/", "gates": gates}
        st = {"service": {"salla_token": "tok", "wa": {"type": "none"}}, "renew": {"panels": []}, "accounts": [acct]}
        cfg = st["renew"]
        # 1) طلبٌ مسحوب بيوزره (نسختان)
        panels.save_store_lines(d, [
            {"order": "138", "date": "2026-09-01", "phone": "0500000001", "customer": "ali", "username": "333426852552",
             "password": "4784316512", "host": "http://ssouqhost.vip:80", "months": 3, "expiry": "2026-12-01",
             "product": "اشتراك كاسبر IPTV لمدة 3 أشهر", "sku": ""},
            {"order": "138", "date": "2026-09-01", "phone": "0500000001", "customer": "ali", "username": "111", "password": "222",
             "host": "http://ssouqhost.vip:80", "months": 3, "expiry": "2026-12-01", "product": "اشتراك كاسبر IPTV لمدة 3 أشهر"},
            {"order": "200", "date": "2026-09-01", "phone": "0500000002", "customer": "سارة", "username": "", "password": "",
             "host": "http://m.ink", "months": 12, "expiry": "2027-09-01", "product": "اشتراك IPTV لمدة سنة"}])
        r = X.reply_lookup(st, cfg, d, [acct], "١٣٨")
        check("pulled order: ready from the store lines, both users, casper by gate host", r["state"] == "ready" and r["src"] == "store"
              and [c["username"] for c in r["creds"]] == ["333426852552", "111"] and r["sub"] == "casper"
              and r["gate"]["gate_id"] == "g1" and r["wa"] == "966500000001" and r["qty"] == 2, str(r)[:300])
        check("text carries the gate guide link and both users", "#activate/casper" in r["text"]
              and "User: 333426852552\nPass: 4784316512" in r["text"] and "اليوزر 2:*\nUser: 111\nPass: 222" in r["text"], r["text"])
        check("no Salla call for a pulled order", not sal.calls, str(sal.calls))
        # 2) طلبٌ في الفهرس بلا يوزر، وسجلّه في سلة يحمل البيانات
        renew._write_json(renew.index_path(d), {"orders": {"300": {"phone": "0500000003", "date": "2026-09-05", "months": 12, "sid": "9300"}}})
        sal.notes["9300"] = ["تم التنفيذ", "Host: http://m.ink\nUsername: 777\nPassword: 888"]
        r = X.reply_lookup(st, cfg, d, [acct], "300")
        check("index order: credentials from the Salla history, smart by host gate", r["state"] == "ready" and r["src"] == "history"
              and r["creds"][0]["username"] == "777" and r["sub"] == "smart" and "سيرفر سمارت" in r["text"]
              and "NEXT+" in r["text"], str(r)[:300])
        # 3) طلبٌ غير مسحوب أصلًا: من سلة برقمه، بلا يوزر ⇒ no_user ويقول أنشئ له
        sal.orders["400"] = _raw_order("400", 9400, "محمد", "اشتراك فالكون IPTV لمدة 3 أشهر | FALCON TV PRO", "FAL-PRO-3M")
        r = X.reply_lookup(st, cfg, d, [acct], "400")
        check("unpulled order fetched from Salla by reference: no user yet", r["state"] == "no_user" and r["customer"] == "محمد"
              and r["phone"] == "966500000009" and r["months"] == 3 and r["sub"] == "falcon" and r["text"] == ""
              and "أنشئ له يوزرًا" in r["hint"] and "فالكون" in r["hint"], str(r)[:300])
        check("Salla asked by reference_id then the history of that order",
              any("reference_id=400" in c for c in sal.calls) and any("/orders/9400/histories" in c for c in sal.calls), str(sal.calls))
        check("gates are listed for the create step", any(g["gate_id"] == "g1" and g["sub"] == "casper" for g in r["gates"]))
        # 3b) أُنشئ له يوزر: الصق سطره ⇒ يُربط بالطلب (بمعلوماته من سلة) ويعود الردّ جاهزًا
        code, b = X.reply_link(st, cfg, d, [acct], {"order": "400", "line": "Host http://falcon.tv:80 User 4001 Pass 4002 Guide x"})
        check("pasted line links the order and the reply is ready", code == 200 and b["state"] == "ready" and b["src"] == "store"
              and b["creds"][0] == {"username": "4001", "password": "4002", "host": "http://falcon.tv:80"}
              and "Host: http://falcon.tv:80" in b["text"] and "تطبيق فالكون" in b["text"] and b["customer"] == "محمد", str(b)[:300])
        ln = next(x for x in panels.load_store_lines(d)["lines"] if x["order"] == "400")
        check("the linked line carries the Salla order info (phone, date, months, product)", ln["phone"] == "966500000009"
              and ln["date"] == "2026-09-01" and ln["months"] == 3 and "فالكون" in ln["product"], str(ln))
        check("linking without a user is refused", X.reply_link(st, cfg, d, [acct], {"order": "400", "line": "bla"})[0] == 400)
        # 4) لا طلب في أي مصدر
        r = X.reply_lookup(st, cfg, d, [acct], "999")
        check("unknown everywhere: not_found", r["state"] == "not_found" and not r.get("text"))
        check("empty query: not_found without a Salla call", X.reply_lookup(st, cfg, d, [acct], "")["state"] == "not_found")
        # 5) الإرسال: يدوي يُسجَّل، وبالرقم المربوط عبر dup_wa_send، ويظهر في السجل بنوع reply
        sent = []
        X.reader_status = lambda fresh=False: {"status": "connected", "configured": True}
        X.dup_wa_send = lambda st_, ph, tx: (sent.append((ph, tx)) or {"ok": True}, "contest")
        code, b = X.reply_send(st, d, {"order": "138", "phone": "0500000001", "name": "ali", "text": "ردّ"})
        check("send via the linked number", code == 200 and b["ok"] and sent == [("966500000001", "ردّ")], str(b))
        code, b = X.reply_send(st, d, {"order": "138", "phone": "", "name": "ali", "text": "ردّ", "mode": "manual"})
        check("manual send is only logged", code == 200 and b["how"] == "manual")
        check("no phone and not manual is refused", X.reply_send(st, d, {"order": "1", "phone": "", "text": "x"})[0] == 400)
        check("empty text is refused", X.reply_send(st, d, {"order": "1", "phone": "0500000001", "text": ""})[0] == 400)
        log = panels.load_dup_log(d)
        check("both attempts are in the messages log as reply", [m["kind"] for m in log[:2]] == ["reply", "reply"]
              and {m["how"] for m in log[:2]} == {"manual", "contest"} and log[1]["order"] == "138", str(log[:2]))
    finally:
        salla_api.API = api_keep
        sal.srv.shutdown()
        for k, v in keep.items():
            setattr(X, k, v)
        shutil.rmtree(d, ignore_errors=True)


def test_complaints_pull():
    print("\n== مراجعة الشكاوى: سجل لوحة سلة بالجلسة، وما ينتظر التاجر وحده ==")
    import salla_web
    check("open statuses: the two merchant-waiting ones (and Salla's own wording)", complaints.is_open("بانتظار الحل من التاجر")
          and complaints.is_open("بانتظار رد التاجر") and complaints.is_open(" بانتظار  استجابة التاجر ") and complaints.is_open("awaiting_merchant"))
    check("not open: waiting for the customer, closed, at Salla", not complaints.is_open("بانتظار رد العميل") and not complaints.is_open("مغلقة")
          and not complaints.is_open("قيد التحقق من سلة") and not complaints.is_open(""))
    rows_json = {"data": [
        {"id": 51, "status": {"name": "بانتظار رد التاجر"}, "order": {"reference_id": 138}, "customer": {"name": "ali", "mobile": "0500000001"}, "type": "الاشتراك لا يعمل", "content": "ما يشتغل"},
        {"id": 52, "status": "بانتظار الحل من التاجر", "order_reference": "400", "customer_name": "محمد"},
        {"id": 53, "status": "بانتظار رد العميل", "order_id": 999, "customer": {"first_name": "س", "last_name": "م"}},
        {"id": 54, "status": "مغلقة", "reference_id": 5, "customer": "x"}]}
    html = ("<table><tr><th>رقم الشكوى</th><th>العميل</th><th>الطلب</th><th>الحالة</th></tr>"
            "<tr><td>#61</td><td>سارة</td><td>287314660</td><td>2026-10-01</td><td>بانتظار الحل من التاجر</td><td><a href=\"/complaints/61\">عرض</a></td></tr>"
            "<tr><td>#62</td><td>خالد</td><td>111222333</td><td>2026-10-02</td><td>مغلقة</td></tr>"
            "<tr><td colspan=3>لا شيء</td></tr></table>")
    mode = {"json": True}
    calls = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            calls.append(self.path)
            if "sess=1" not in (self.headers.get("Cookie") or ""):
                self.send_response(302); self.send_header("Location", "/auth?x"); self.send_header("Content-Length", "0"); self.end_headers(); return
            u = urllib.parse.urlsplit(self.path)
            page = urllib.parse.parse_qs(u.query).get("page", ["1"])[0]
            if mode["json"] and u.path == "/api/v1/complaints":          # المسار الأول مفقود عمدًا: يُجرَّب الثاني ويُحفظ
                return self._out(200, json.dumps(rows_json if page == "1" else {"data": []}, ensure_ascii=False).encode(), "application/json")
            if not mode["json"] and u.path == "/complaints" and "format" not in u.query:
                return self._out(200, (html if page == "1" else "<table></table>").encode(), "text/html")
            self._out(404, b"", "text/html")

        def _out(self, code, raw, ct):
            self.send_response(code); self.send_header("Content-Type", ct + "; charset=utf-8")
            self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    keep = {k: getattr(X, k) for k in ("renew_pull_session",)}
    try:
        sess = salla_web.Session("sess=1", base=base)
        rows = sess.complaints()
        check("json: complaints found on the second candidate path and normalized", len(rows) == 4 and rows[0]["order"] == "138"
              and rows[0]["customer"] == "ali" and rows[0]["status"] == "بانتظار رد التاجر" and rows[0]["type"] == "الاشتراك لا يعمل"
              and rows[1]["order"] == "400" and rows[1]["customer"] == "محمد" and rows[2]["customer"] == "س م", str(rows)[:300])
        n0 = len(calls); sess.complaints()
        check("the path that worked is remembered (one list call + one empty page 2)", calls[n0] .startswith("/api/v1/complaints") and len(calls) - n0 == 2, str(calls[n0:]))
        X.renew_pull_session = lambda st_, cfg=None: sess
        d = X.complaints_open({"renew": {}})
        check("complaints_open keeps only the merchant-waiting ones, with the total", [r["id"] for r in d["rows"]] == ["51", "52"] and d["total"] == 4, str(d)[:200])
        mode["json"] = False
        sess2 = salla_web.Session("sess=1", base=base)
        rows = sess2.complaints()
        check("html fallback: table rows parsed (id, customer, order, status, date, link)", len(rows) == 2 and rows[0] == {"id": "61", "order": "287314660",
              "customer": "سارة", "status": "بانتظار الحل من التاجر", "type": "", "text": "", "date": "2026-10-01", "phone": "", "url": "/complaints/61"}, str(rows))
        X.renew_pull_session = lambda st_, cfg=None: sess2
        check("html: only the open one is shown", [r["id"] for r in X.complaints_open({})["rows"]] == ["61"])
        X.renew_pull_session = lambda st_, cfg=None: None
        check("no session: an error with a hint, not a crash", X.complaints_open({})["error"] == "no_session")
        # السحب من جهاز المشغّل عبر الإضافة: صفحات خام (JSON ثم HTML) تُجمع بلا تكرار وتُحفظ، وتُقدَّم على اللوحة
        ws = tempfile.mkdtemp(prefix="cqfeed_")
        try:
            check("no stored file and no session: hint points at the extension", "سحب الشكاوى من جهازي" in X.complaints_open({}, None, ws)["hint"])
            X.complaints_feed(ws, {"op": "start"})
            r1 = X.complaints_feed(ws, {"op": "page", "path": "/api/complaints", "body": json.dumps(rows_json, ensure_ascii=False)})
            r2 = X.complaints_feed(ws, {"op": "page", "path": "/api/complaints", "body": json.dumps(rows_json, ensure_ascii=False)})
            r3 = X.complaints_feed(ws, {"op": "page", "path": "/complaints", "body": html})
            check("feed: json page parsed, a repeated page adds nothing, html page adds its rows", r1["found"] == 4 and r1["new"] == 4
                  and r2["new"] == 0 and r3["found"] == 2 and r3["total"] == 6, str((r1, r2, r3)))
            check("feed: a page with nothing says found 0", X.complaints_feed(ws, {"op": "page", "body": "<html>nope</html>"})["found"] == 0)
            fin = X.complaints_feed(ws, {"op": "finish"})
            d = X.complaints_open({}, None, ws)
            check("finish saves; open reads the stored rows first (merchant-waiting only) with time and source", fin["saved"] and fin["open"] == 3
                  and [r["id"] for r in d["rows"]] == ["51", "52", "61"] and d["total"] == 6 and d["source"] == "extension" and d["at"], str(d)[:200])
            X.renew_pull_session = lambda st_, cfg=None: sess
            check("stored rows win over the server session", X.complaints_open({}, None, ws)["source"] == "extension")
            X.complaints_feed(ws, {"op": "start"})
            check("finish with nothing found does not overwrite the stored file", not X.complaints_feed(ws, {"op": "finish"})["saved"]
                  and X.complaints_open({}, None, ws)["total"] == 6)
        finally:
            shutil.rmtree(ws, ignore_errors=True)
        X.renew_pull_session = lambda st_, cfg=None: salla_web.Session("other=1", base=base)
        check("expired session reported", X.complaints_open({})["error"] == "session_expired")
    finally:
        srv.shutdown()
        for k, v in keep.items():
            setattr(X, k, v)


if __name__ == "__main__":
    test_sub_and_text()
    test_lookup()
    test_complaints_pull()
    print("\n----------------------------------------")
    print(f"Result: \033[32m{_p} passed\033[0m, " + (f"\033[31m{_f} failed\033[0m" if _f else "0 failed"))
    sys.exit(1 if _f else 0)

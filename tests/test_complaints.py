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


if __name__ == "__main__":
    test_sub_and_text()
    test_lookup()
    print("\n----------------------------------------")
    print(f"Result: \033[32m{_p} passed\033[0m, " + (f"\033[31m{_f} failed\033[0m" if _f else "0 failed"))
    sys.exit(1 if _f else 0)

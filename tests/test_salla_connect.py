#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ربط سلة بالجلسة (إضافة المتصفح): استخراج قائمة الطلبات من ردّ اللوحة، والسحب
الدوري يفضّل الجلسة المربوطة على توكن الإدارة."""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

os.environ["XM_DATA"] = tempfile.mkdtemp(prefix="xmsalla_")

import salla_web  # noqa: E402
import xm_lines as X  # noqa: E402

_p = _f = 0


def check(label, cond, extra=""):
    global _p, _f
    if cond:
        _p += 1
        print("  \033[32mPASS\033[0m  " + label + (("  (%s)" % extra) if extra else ""))
    else:
        _f += 1
        print("  \033[31mFAIL\033[0m  " + label + (("  (%s)" % extra) if extra else ""))


ORDER = {"id": 123, "reference_id": 456, "status": "بانتظار الدفع",
         "total": {"amount": 100}, "customer": {"mobile": "0501234567"},
         "items": [{"product_id": 99, "name": "اشتراك", "quantity": 1}]}


def main():
    # استخراج قائمة الطلبات من أشكال ردّ مختلفة
    check("_find_orders: under data[]", salla_web._find_orders({"data": [ORDER]}) == [ORDER])
    check("_find_orders: under nested orders[]",
          salla_web._find_orders({"x": {"orders": [ORDER, ORDER]}}) == [ORDER, ORDER])
    check("_find_orders: top-level list", salla_web._find_orders([ORDER]) == [ORDER])
    check("_find_orders: ignores non-orders", salla_web._find_orders({"data": [{"foo": 1}]}) == [])
    check("_find_orders: empty on junk", salla_web._find_orders({"a": 1, "b": "x"}) == [])

    # recent_orders يستخرج القائمة ويحفظ أوّل مسارٍ ناجح
    s = salla_web.Session("sess=1; k=v")
    calls = []

    def fake_json(path):
        calls.append(path)
        return {"data": [ORDER, ORDER]} if "per_page" in path else None
    s._json = fake_json
    rows = s.recent_orders(25)
    check("recent_orders returns the order rows", rows == [ORDER, ORDER], str(len(rows)))
    check("recent_orders memoizes the working path", getattr(s, "_list_path", None) is not None)
    n_before = len(calls)
    s.recent_orders(25)
    check("memoized path is tried first (fewer probes next time)", len(calls) - n_before == 1, str(len(calls) - n_before))

    # parse_order يفهم صفّ اللوحة
    o = X.salla_api.parse_order(ORDER)
    check("parse_order reads id + phone from a panel row",
          o.get("order_id") and o.get("phone", "").endswith("501234567"), str(o)[:80])

    # السحب الدوري يفضّل الجلسة المربوطة على التوكن
    st = {"renew": {"panel_cookie": "sess=1; k=v"}, "service": {"salla_token": "TOK"}}
    used = {"which": None}

    class FakeSess:
        def __init__(self, cookie): used["which"] = "session"
        def recent_orders(self, n): return [ORDER]
    orig_sess, orig_fetch = salla_web.Session, X.salla_api.fetch_orders
    salla_web.Session = FakeSess
    X.salla_api.fetch_orders = lambda *a, **k: (used.__setitem__("which", "token") or [ORDER])
    try:
        out = X._poll_salla_orders(st, st["service"])
        check("poll uses the linked session when a cookie exists", used["which"] == "session", used["which"])
        check("poll returns parsed orders", bool(out) and out[0].get("order_id"), str(out[:1])[:80])
        used["which"] = None
        out2 = X._poll_salla_orders({"renew": {}, "service": {"salla_token": "TOK"}}, {"salla_token": "TOK"})
        check("poll falls back to admin token when no session", used["which"] == "token", used["which"])
        check("poll returns [] when neither session nor token", X._poll_salla_orders({"renew": {}}, {}) == [])
    finally:
        salla_web.Session, X.salla_api.fetch_orders = orig_sess, orig_fetch


    # ---- السحب بكوكيز اللوحة (HTML): القائمة، صفحة الطلب، الكود ثم الملاحظات ----
    import renew_import
    LIST = """<table><tbody id="table_list_orders">
<tr class="table-row order-row  row_order" id="row_order_111" data-order_id="111" data-customer=" اصيل  "
 data-order-link="https://s.salla.sa/orders/order/111" data-row-order-id="111">
<td><div class="order-customer-name">اصيل</div><div class="order-number font-12">#293119145</div>
<div class="order-status"><span>●</span> طلبك مؤكد</div></td><td class="order-total text-right"><h6>23 SAR</h6></td></tr>
<tr class="table-row order-row  row_order" id="row_order_222" data-order_id="222" data-customer=" Hassan "
 data-order-link="https://s.salla.sa/orders/order/222" data-row-order-id="222">
<td><div class="order-number font-12">#293118217</div><div class="order-status"><span>●</span> ملغي</div></td></tr>
</tbody></table><ul><li class="page-item"><a class="page-link next-page-link" href="/orders?page=2">التالي</a></li></ul>"""
    rows, more = salla_web.parse_orders_list(LIST)
    check("parse_orders_list reads sid/order/customer/status", len(rows) == 2 and rows[0] == {
        "sid": "111", "order": "293119145", "customer": "اصيل", "status": "طلبك مؤكد",
        "total": "23 SAR", "admin_url": "https://s.salla.sa/orders/order/111"}, str(rows[0]))
    check("parse_orders_list sees the next-page link", more)
    check("parse_orders_list: last page has no next", salla_web.parse_orders_list(LIST.split("<ul>")[0])[1] is False)

    def order_html(code, notes=(), cnote="لا توجد ملاحظات!", qty=1, no="293119145"):
        hist = [{"note": n, "created_at": {"time": "2026-10-10"}} for n in notes]
        return ("""<div class="rec-order-no" style="x">\n """ + no + """\n <div class="tag"></div></div>
<div class="rec-order-date">Saturday 10 October 2026 | 08:20 PM</div>
<span id="order_status_btn">طلبك مؤكد</span>
<div data-card-customer-buyer><h6><a href="https://s.salla.sa/customers/abc" target="_blank">\n اصيل \n</a></h6>
<a class="direct-phone" href="tel:+966500933277">+966500933277</a></div>
<h6 class="panel-title"><i></i>&nbsp;\n المنتجات\n</h6><table><tbody><tr class="table-row"><td>
<h6 class="no-margin"><a href="https://s.salla.sa/products/1557813796">\n اشتراك كاسبر IPTV لمدة 6 أشهر\n</a></h6>
<ul>""" + "".join('<li><span class="text-muted">الكود:</span>\n<span>%s</span></li>' % c for c in code) + """</ul></td>
<td data-title="الكمية">\n %d\n</td><td data-title="الوزن">-</td><td data-title="السعر">20 SAR</td></tr></tbody></table>
<h6 class="panel-title">ملاحظة العميل</h6></div><div class="panel-body"><p>%s</p></div>
<script>var initialData = %s;</script>""" % (qty, cnote, json.dumps({"statusHistories": hist, "order_id": 111}, ensure_ascii=False)))
    import json
    CODE = "Host http://ssouqhost.vip:80 User 328137953493 Pass 4083691844 Guide https://guide.ssouq.com/#activate/casper"
    d = salla_web.parse_order_page(order_html([CODE], ["تم شراء الكود #1"]), "111")
    check("parse_order_page: number/date/status/customer", (d["reference_id"], d["date"]["date"], d["status"]["name"],
          d["customer"]["name"], d["customer"]["mobile"]) == ("293119145", "2026-10-10", "طلبك مؤكد", "اصيل", "+966500933277"), str(d)[:160])
    check("parse_order_page: item with its code", d["items"][0]["name"] == "اشتراك كاسبر IPTV لمدة 6 أشهر"
          and d["items"][0]["codes"] == [CODE] and d["items"][0]["quantity"] == 1, str(d["items"]))
    check("parse_order_page: history notes kept", d["notes"] == ["تم شراء الكود #1"] and d["customer_note"] == "", str(d["notes"]))
    check("the bare-token card parses (User 3281… Pass 4083…)",
          renew_import.parse_credentials(CODE) == {"username": "328137953493", "password": "4083691844",
                                                   "host": "http://ssouqhost.vip:80"})

    class FakeSess:
        pages = {1: (LIST, True), 2: (LIST.replace('"111"', '"333"').replace("293119145", "293110000").split("<ul>")[0], False)}
        orders = {"111": order_html([CODE]),
                  "333": order_html(["بطاقة بلا اعتماد"], ["تم التنفيذ", "Username: 555666777 Password: 888999000 Host http://h2.vip"], no="293110000"),
                  "222": order_html([CODE])}
        opened = []
        def orders_page(self, page): return salla_web.parse_orders_list(self.pages.get(page, ("", False))[0])
        def order_details(self, sid): self.opened.append(sid); return salla_web.parse_order_page(self.orders[sid], sid)
    fs = FakeSess()
    units, meta = renew_import.pull_from_salla("", session=fs)
    check("panel pull walks all pages (a sid seen twice counts once)", meta["source"] == "panel" and meta["orders_total"] == 3, str(meta))
    check("panel pull skips unconfirmed rows without opening them", "222" not in fs.opened and meta["skipped"]["unconfirmed"] == 1, str(fs.opened))
    by = {u["order"]: u for u in units}
    check("unit from the code field", by.get("293119145", {}).get("username") == "328137953493"
          and by["293119145"]["months"] == 6 and by["293119145"]["phone"] == "966500933277", str(by.get("293119145")))
    check("unit falls back to history notes when the code has none",
          by.get("293110000", {}).get("username") == "555666777" and by["293110000"].get("host") == "http://h2.vip", str(by.get("293110000")))
    check("with_credentials counts both", meta["with_credentials"] == 2 and "code" not in by["293119145"], str(meta["with_credentials"]))

    # منتجات لا علاقة لها بالاشتراكات تُتجاوز ولا يُسجَّل منها شيء
    check("is_subscription_item: by name", renew_import.is_subscription_item({"name": "اشتراك كاسبر IPTV لمدة 6 أشهر", "codes": []}))
    check("is_subscription_item: by credentials code", renew_import.is_subscription_item({"name": "منتج", "codes": [CODE]}))
    check("is_subscription_item: a device is not", not renew_import.is_subscription_item({"name": "رسيفر أندرويد 4K مع ضمان سنة", "codes": []}))
    check("is_subscription_item: trial is not", not renew_import.is_subscription_item({"name": "اشتراك تجريبي يوم", "codes": []}))

    class DevSess(FakeSess):
        pages = {1: (LIST.split("<ul>")[0], False)}
        orders = {"111": order_html([]).replace("اشتراك كاسبر IPTV لمدة 6 أشهر", "رسيفر أندرويد 4K مع ضمان سنة")}
        opened = []
    us2, m2 = renew_import.pull_from_salla("", session=DevSess())
    check("panel pull records nothing for non-subscription orders", us2 == [] and m2["skipped"]["not_subscription"] == 1, str(m2["skipped"]))

    # ‏403 من Cloudflare حجبٌ لعنوان الخادم لا جلسةٌ منتهية
    cf = salla_web.denied_error(403, {"Server": "cloudflare", "cf-mitigated": "challenge"}, b"<title>Just a moment...</title>")
    check("cf-mitigated challenge → WebError (not session)", isinstance(cf, salla_web.WebError) and "Cloudflare" in str(cf))
    cf2 = salla_web.denied_error(403, {"Server": "cloudflare"}, b"<html><title>Attention Required! | Cloudflare</title>")
    check("cloudflare block page → WebError", isinstance(cf2, salla_web.WebError))
    se = salla_web.denied_error(403, {"Server": "cloudflare"}, b'{"status":403,"success":false,"error":{"message":"salla unauthorized"}}')
    check("salla's own 403 → SessionExpired", isinstance(se, salla_web.SessionExpired))

    # مهلةُ شبكةٍ عابرة تُعاد ثم تنجح؛ ودائمةٌ تصير WebError
    import urllib.error, urllib.request
    s4 = salla_web.Session("sess=1"); calls = {"n": 0}
    class FakeResp:
        status = 200; headers = {}
        def read(self): return b"ok"
        def __enter__(self): return self
        def __exit__(self, *a): pass
    class FakeOpener:
        def open(self, req, timeout=0):
            calls["n"] += 1
            if calls["n"] < 3: raise urllib.error.URLError("handshake timed out")
            return FakeResp()
    orig_build, orig_sleep = urllib.request.build_opener, salla_web.time.sleep
    urllib.request.build_opener, salla_web.time.sleep = lambda *a: FakeOpener(), lambda s: None
    try:
        code, _, body = s4._get("/orders")
        check("transient network error is retried", code == 200 and body == b"ok" and calls["n"] == 3, str(calls))
        calls["n"] = -10
        try:
            s4._get("/orders"); check("persistent network error → WebError", False)
        except salla_web.WebError as e:
            check("persistent network error → WebError", "تعذّر" in str(e))
    finally:
        urllib.request.build_opener, salla_web.time.sleep = orig_build, orig_sleep

    # ‏429 يُمهَل ويُعاد (Retry-After محترم، حتى دقيقة)
    s5 = salla_web.Session("sess=1"); hits = {"n": 0}; waits = []
    class RL:
        def open(self, req, timeout=0):
            hits["n"] += 1
            if hits["n"] < 3:
                raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {"Retry-After": "7"}, None)
            return FakeResp()
    urllib.request.build_opener, salla_web.time.sleep = lambda *a: RL(), lambda sec: waits.append(sec)
    try:
        code, _, _ = s5._get("/orders")
        check("429 is retried after Retry-After", code == 200 and hits["n"] == 3 and waits == [7.0, 7.0], str(waits))
        check("retry_after caps at a minute", salla_web._retry_after({"Retry-After": "900"}, 2) == 60.0 and salla_web._retry_after({}, 2) == 2)
    finally:
        urllib.request.build_opener, salla_web.time.sleep = orig_build, orig_sleep

    s3 = salla_web.Session("sess=1")
    s3._get = lambda path, accept="application/json": (200, {"Server": "cloudflare"}, "<title>\n الطلبات | سلة </title>".encode())
    dg = s3.diagnose()
    check("diagnose: 200 is ok with title", dg["ok"] and dg["code"] == 200 and dg["title"].startswith("الطلبات"), str(dg))
    s3._get = lambda path, accept="application/json": (302, {"Location": "https://s.salla.sa/auth?x=1"}, b"")
    check("diagnose: auth redirect is expired session", not s3.diagnose()["ok"] and "انتهت" in s3.diagnose()["verdict"])

    # السحب من جهاز المشغّل: الإضافة تُغذّي الخادم بصفحات اللوحة خامًا
    st3 = {"renew": {}, "service": {}}
    X._pull["running"] = False
    r = X.panel_feed(st3, "ws", {}, {"op": "start", "max_months": 15})
    check("feed start opens a job", r["ok"] and X._pull["running"] and X._pull["source"] == "extension", str(r))
    r = X.panel_feed(st3, "ws", {}, {"op": "list", "page": 1, "html": LIST})
    check("feed list returns confirmed sids only", r["ok"] and r["sids"] == ["111"] and r["more"] is True, str(r))
    r = X.panel_feed(st3, "ws", {}, {"op": "orders", "orders": {"111": order_html([CODE])}})
    check("feed orders parses units with credentials", r["ok"] and r["units"] == 1 and r["found"] == 1 and r["too_old"] is False, str(r))
    check("feed progress mirrors into pull status", X._pull["units"] == 1 and X._pull["page"] == 1)
    check("a live feed refuses a second start", X.panel_feed(st3, "ws", {}, {"op": "start"})["ok"] is False)
    orig_fin = X._pull_finish
    fin = {}
    X._pull_finish = lambda units, meta, ws, cfg, apply, **k: fin.update(n=len(units), src=meta["source"]) or X._pull.update(phase="done")
    try:
        r = X.panel_feed(st3, "ws", {}, {"op": "finish"})
    finally:
        X._pull_finish = orig_fin
    check("feed finish finalizes like the direct pull", r["ok"] and fin == {"n": 1, "src": "extension"} and not X._pull["running"], str(r))
    check("after finish the job is closed", X.panel_feed(st3, "ws", {}, {"op": "list", "page": 2, "html": ""})["ok"] is False)

    # أُغلق المتصفّح في المنتصف: البدء ثانيةً يستأنف من الصفحة التالية بما جُمع
    X._pull["running"] = False
    X.panel_feed(st3, "ws", {}, {"op": "start", "max_months": 15})
    X.panel_feed(st3, "ws", {}, {"op": "list", "page": 3, "html": LIST})
    X.panel_feed(st3, "ws", {}, {"op": "orders", "orders": {"111": order_html([CODE])}})
    X._pull["heartbeat"] = time.time() - 999                       # انقطع
    r = X.panel_feed(st3, "ws", {}, {"op": "start", "max_months": 15, "resume": True})
    check("a stale extension pull resumes from the next page with its units", r["ok"] and r.get("resume_page") == 4 and r["units"] == 1, str(r))
    X._pull_finish = lambda units, meta, ws, cfg, apply, **k: fin.update(n=len(units)) or X._pull.update(phase="done")
    try:
        r = X.panel_feed(st3, "ws", {}, {"op": "save"})
        check("save keeps the pull open after writing", r["ok"] and r["saved"] == 1 and X._pull["running"], str(r))
        X._pull["heartbeat"] = time.time() - 999
        r = X.panel_feed(st3, "ws", {}, {"op": "start", "max_months": 3})
        check("a fresh start with another cutoff saves the old units first", r["ok"] and not r.get("resume_page") and fin["n"] == 1, str(r))
    finally:
        X._pull_finish = orig_fin
        X._pull["running"] = False

    # رابط «التالي» يختفي والصفحات تستمرّ: النهاية صفحةٌ بلا طلبات جديدة
    class EndlessSess(FakeSess):
        pages = {1: (LIST.split("<ul>")[0], False), 2: (LIST.split("<ul>")[0].replace('"111"', '"444"').replace("293119145", "293100004"), False),
                 3: (LIST.split("<ul>")[0], False)}
        orders = {"111": order_html([CODE]), "444": order_html([CODE], no="293100004"), "222": order_html([CODE])}
        opened = []
        def orders_page(self, page): return salla_web.parse_orders_list(self.pages[min(page, 3)][0])
    us3, m3 = renew_import.pull_from_salla("", session=EndlessSess())
    check("pull continues past a missing next link and stops at a page with no new orders",
          m3["pages"] == 3 and sorted(u["order"] for u in us3) == ["293100004", "293119145"], str(m3))
    fj = renew_import.PanelFeed()
    a = fj.list(1, LIST.split("<ul>")[0]); b = fj.list(2, LIST.split("<ul>")[0])
    check("feed list: a repeated page means the end", a["more"] is True and b["more"] is False and b["sids"] == [], str(b))

    # فالكون يُسحب من اللوحة معلَّمًا، ويُستثنى من التجديد عند الختام
    fal = salla_web.parse_order_page(order_html(["Host http://falcon.tv:80 User 111222333 Pass 444555666"]).replace("اشتراك كاسبر IPTV لمدة 6 أشهر", "اشتراك فالكون IPTV لمدة 12 شهر"), "7")
    fu, _, why = renew_import.panel_order_units(fal)
    check("falcon order is pulled from the panel, flagged", len(fu) == 1 and fu[0]["falcon"] is True and not why, str(fu)[:120])
    cu, _, _ = renew_import.panel_order_units(salla_web.parse_order_page(order_html([CODE]), "8"))
    check("non-falcon unit is not flagged", cu and cu[0]["falcon"] is False)
    import tempfile as _tf
    calls = {}
    orig_an, orig_ix = X.renew_import.analyze, X.renew_import.build_index
    X.renew_import.analyze = lambda units, meta: calls.update(analyze=len(units)) or {"units": []}
    X.renew_import.build_index = lambda units, meta: calls.update(index=len(units)) or {}
    try:
        X._pull_finish(fu + cu, {"with_credentials": 2, "source": "panel"}, _tf.mkdtemp(), {}, True)
    finally:
        X.renew_import.analyze, X.renew_import.build_index = orig_an, orig_ix
    check("finish: renewal analysis/index exclude falcon, store lines keep it",
          calls == {"analyze": 1, "index": 1} and X._pull["units"] == 2, str(calls))

    # إكمالٌ من حيث توقّف: الطلبات المعروفة لا تُفتح، وصفحةٌ كلها معروفة تُنهي السحب
    class K(FakeSess):
        pages = {1: (LIST.split("<ul>")[0], False),
                 2: (LIST.split("<ul>")[0].replace('"111"', '"555"').replace("293119145", "293100005"), False)}
        orders = {"111": order_html([CODE]), "555": order_html([CODE], no="293100005"), "222": order_html([CODE])}
        opened = []
    ks = K()
    uk, mk = renew_import.pull_from_salla("", session=ks, known={"293100005"})
    check("known order is not opened; page 2 all-known stops the pull",
          ks.opened == ["111"] and mk["skipped"]["known"] == 1 and [u["order"] for u in uk] == ["293119145"], str(ks.opened))
    fj = renew_import.PanelFeed(known={"293119145", "293118217"})
    r = fj.list(1, LIST.split("<ul>")[0])
    check("feed: a page with only known orders ends the pull", r["sids"] == [] and r["more"] is False and fj.skipped["known"] == 2, str(r))
    fj2 = renew_import.PanelFeed(known={"293119145"})
    r2 = fj2.list(1, LIST.split("<ul>")[0])
    check("feed: a page with an unknown (even unconfirmed) order keeps going", r2["more"] is True and r2["sids"] == [], str(r2))

    # دمج الخطوط: الجديد يغلب القديم بلا تكرار، وأرقام الطلبات المعروفة تُقرأ من المحفوظ
    import tempfile as _tf, panels as _pn
    wsd = _tf.mkdtemp()
    _pn.save_store_lines(wsd, [{"order": "1", "username": "111111111111", "months": 6, "password": "a"},
                               {"order": "2", "username": "222222222222", "months": 6}])
    merged = _pn.merge_store_lines(wsd, [{"order": "1", "username": "111111111111", "months": 12, "password": "b"},
                                         {"order": "3", "username": "333333333333", "months": 6}])
    check("merge: same order+user replaced, others kept", sorted((m["order"], m["months"]) for m in merged) == [("1", 12), ("2", 6), ("3", 6)], str(merged))
    check("known_orders reads saved order numbers", _pn.known_orders(wsd) == {"1", "2"})

    # ملف الاشتراكات الذي تولّده الأداة يُقرأ من جديد كوحدات (ذهابًا وإيابًا)
    _pn.save_store_lines(wsd, [{"order": "293119145", "date": "2026-10-10", "customer": "اصيل", "phone": "966500933277",
                                "product": "اشتراك كاسبر IPTV لمدة 6 أشهر", "months": 6, "devices": 1, "expiry": "2027-04-10",
                                "host": "http://ssouqhost.vip:80", "username": "328137953493", "password": "4083691844",
                                "admin_url": "https://s.salla.sa/orders/order/2098223628", "price": "20", "status": "طلبك مؤكد"}])
    xl = X._store_lines_xlsx(wsd)
    check("our xlsx is recognised as a store-lines file", renew_import.is_store_lines_file(xl) and not renew_import.is_store_lines_file(b"abc,def\n1,2"))
    back = renew_import.read_store_lines(xl)
    check("read_store_lines round-trips the unit", len(back) == 1 and back[0]["order"] == "293119145" and back[0]["username"] == "328137953493"
          and back[0]["sid"] == "2098223628" and back[0]["months"] == 6 and back[0]["expiry"] == "2027-04-10" and back[0]["falcon"] is False, str(back)[:200])

    # الكمية ٢ بكودين → يوزر لكل نسخة
    d2 = salla_web.parse_order_page(order_html([CODE, CODE.replace("328137953493", "111222333444")], qty=2), "9")
    us, _ = renew_import.salla_order_units(d2)
    check("one unit per copy, each with its own code", [u.get("code", "")[:40] for u in us] == [CODE[:40], CODE.replace("328137953493", "111222333444")[:40]], str(len(us)))

    # بدء السحب: بلا توكن يُستعمل كوكيز اللوحة؛ وبلا الاثنين يُرفض
    st2 = {"renew": {"panel_cookie": "sess=1; k=v"}, "service": {}}
    check("pull is ready with a cookie only", X.renew_pull_ready(st2, {}) is True)
    check("pull is not ready with neither", X.renew_pull_ready({"renew": {}, "service": {}}, {}) is False)
    check("pull is ready with the workspace's own cookie", X.renew_pull_ready({"renew": {}, "service": {}}, {"panel_cookie": "s=1"}) is True)
    r = X.start_renew_pull({"renew": {}, "service": {}}, "ws", {"panel_cookie": "s=1"})
    check("start accepts the workspace cookie", r["ok"] is True, str(r))
    X._pull["cancel"] = True; time.sleep(0.3); X._pull["running"] = False
    r = X.start_renew_pull({"renew": {}, "service": {}}, "ws", {})
    check("start refuses with neither token nor cookie", r["ok"] is False and "كوكيز" in r["error"], str(r))
    orig_worker = X._pull_worker
    got = {}
    X._pull_worker = lambda token, wh, ap, ws, cfg, session=None, *a, **k: got.update(token=token, session=session) or X._pull.update(running=False)
    # سحبٌ معلّق (بلا نبض) يُستبدل بسحبٍ جديد؛ وجارٍ بنبضٍ حيّ يُرفض
    X._pull.update(running=True, owner="ws", heartbeat=time.time() - 999, gen=5)
    check("stale pull is detected", X.pull_is_stale())
    r = X.start_renew_pull(st2, "ws", {})
    time.sleep(0.2)
    check("stale pull is replaced by a new generation", r["ok"] and r["replaced_stale"] and X._pull["gen"] == 6, str(r))
    X._pull.update(running=True, heartbeat=time.time())
    r = X.start_renew_pull(st2, "ws", {})
    check("live pull is not replaced, and the refusal carries details", r["ok"] is False and "آخر نشاط" in r["error"], str(r))
    X._pull.update(source="extension", page=7, owner="admin-ws")
    f = X.pull_status_for("other-ws")
    check("another workspace sees the running pull as foreign with its progress", f["running"] and f["foreign"] and f["page"] == 7 and "cancel" not in f, str(f))
    check("the owner sees the full status", "cancel" in X.pull_status_for("admin-ws"))
    X._pull["running"] = False
    try:
        r = X.start_renew_pull(st2, "ws", {})
        time.sleep(0.2)
        check("start uses the panel session when no token", r["ok"] and got["token"] == "" and isinstance(got["session"], salla_web.Session), str(got))
    finally:
        X._pull_worker = orig_worker
        X._pull["running"] = False

    print("\n----------------------------------------")
    print("Result: \033[32m%d passed\033[0m, %s" % (_p, ("\033[31m%d failed\033[0m" % _f) if _f else "0 failed"))
    import shutil
    shutil.rmtree(os.environ["XM_DATA"], ignore_errors=True)
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

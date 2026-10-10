#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ربط سلة بالجلسة (إضافة المتصفح): استخراج قائمة الطلبات من ردّ اللوحة، والسحب
الدوري يفضّل الجلسة المربوطة على توكن الإدارة."""
import os
import sys
import tempfile

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
        def orders_page(self, page): return salla_web.parse_orders_list(self.pages[page][0])
        def order_details(self, sid): self.opened.append(sid); return salla_web.parse_order_page(self.orders[sid], sid)
    fs = FakeSess()
    units, meta = renew_import.pull_from_salla("", session=fs)
    check("panel pull walks all pages", meta["source"] == "panel" and meta["orders_total"] == 4, str(meta))
    check("panel pull skips unconfirmed rows without opening them", "222" not in fs.opened and meta["skipped"]["unconfirmed"] == 2, str(fs.opened))
    by = {u["order"]: u for u in units}
    check("unit from the code field", by.get("293119145", {}).get("username") == "328137953493"
          and by["293119145"]["months"] == 6 and by["293119145"]["phone"] == "966500933277", str(by.get("293119145")))
    check("unit falls back to history notes when the code has none",
          by.get("293110000", {}).get("username") == "555666777" and by["293110000"].get("host") == "http://h2.vip", str(by.get("293110000")))
    check("with_credentials counts both", meta["with_credentials"] == 2 and "code" not in by["293119145"], str(meta["with_credentials"]))

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
    X._pull["cancel"] = True; import time; time.sleep(0.3); X._pull["running"] = False
    r = X.start_renew_pull({"renew": {}, "service": {}}, "ws", {})
    check("start refuses with neither token nor cookie", r["ok"] is False and "كوكيز" in r["error"], str(r))
    orig_worker = X._pull_worker
    got = {}
    X._pull_worker = lambda token, wh, ap, ws, cfg, session=None: got.update(token=token, session=session) or X._pull.update(running=False)
    try:
        r = X.start_renew_pull(st2, "ws", {})
        import time; time.sleep(0.2)
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

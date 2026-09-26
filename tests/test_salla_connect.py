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

    print("\n----------------------------------------")
    print("Result: \033[32m%d passed\033[0m, %s" % (_p, ("\033[31m%d failed\033[0m" % _f) if _f else "0 failed"))
    import shutil
    shutil.rmtree(os.environ["XM_DATA"], ignore_errors=True)
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

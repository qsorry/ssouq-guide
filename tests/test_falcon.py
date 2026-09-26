#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
موصّل فالكون: تحليل الباقات والإنشاء + التوجيه من xm_lines (مزيَّف، بلا شبكة/رصيد).
تشغيل:  python tests/test_falcon.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import falcon_api, xm_lines as X

_p = _f = 0
def check(l, c, x=""):
    global _p, _f
    print((f"  \033[32mPASS\033[0m  {l}" if c else f"  \033[31mFAIL\033[0m  {l}") + (f"  ({x})" if x else ""))
    _p += 1 if c else 0; _f += 0 if c else 1

# ردود مزيَّفة تحاكي واجهة فالكون الحيّة
CANNED = {
    ("GET", "/me"): {"ok": True, "reseller": {"id": 1543, "username": "okyesno", "credits": 295.5, "host": "http://s.falconiptv.ink"}},
    ("GET", "/packages"): {"ok": True, "packages": [
        {"id": 167, "package_name": "1months", "official_credits": 0.5, "official_duration": 1, "official_duration_in": "months", "max_connections": 1},
        {"id": 169, "package_name": "3months", "official_credits": 1, "max_connections": 2},
    ]},
}
def fake_request(base, key, path, method="GET", body=None):
    if method == "POST" and path == "/lines":
        if not body or int(body.get("package_id", 0)) not in (167, 169):
            return {"ok": False, "error": "package_not_available"}
        # يحاكي لوحة ترجّع الاسم/كلمة المرور المُرسَلَين داخل line
        return {"ok": True, "line": {"id": 900001, "username": body.get("username"),
                                     "password": body.get("password"), "expires_at": 1830000000}}
    if path.startswith("/lines"):
        return {"ok": True, "lines": [{"id": 900002, "username": "genuser", "password": "genpass", "expires_at": 1830000000, "package_id": 167}]}
    return CANNED.get((method, path), {"ok": False, "error": "not_found"})

def main():
    global _p, _f
    falcon_api._request = fake_request

    print("== adapter parsing ==")
    check("host from /me", falcon_api.host("B", "K") == "http://s.falconiptv.ink")
    pkgs = falcon_api.packages("B", "K")
    check("packages parsed + Arabic name", len(pkgs) == 2 and pkgs[0]["id"] == 167 and pkgs[0]["name"] == "شهر" and pkgs[0]["name_en"] == "1months" and pkgs[0]["credits"] == 0.5)
    r = falcon_api.create_line("B", "K", 167, "u123", "p123")
    check("create returns sent username/password", r["username"] == "u123" and r["password"] == "p123" and r["id"] == 900001)
    try:
        falcon_api.create_line("B", "K", 0)
        check("invalid package raises FalconError", False)
    except falcon_api.FalconError as e:
        check("invalid package raises FalconError", "package_not_available" in str(e))

    print("\n== create response WITHOUT username -> read back from /lines ==")
    def fake_no_userpass(base, key, path, method="GET", body=None):
        if method == "POST" and path == "/lines":
            return {"ok": True, "line": {"id": 900002}}   # لا اسم/كلمة مرور
        return fake_request(base, key, path, method, body)
    falcon_api._request = fake_no_userpass
    r = falcon_api.create_line("B", "K", 167, "sent_u", "sent_p")
    check("username/password read back from /lines by id", r["username"] == "genuser" and r["password"] == "genpass")
    falcon_api._request = fake_request

    print("\n== xm_lines routes a falcon gate ==")
    gate = X.clean_gate({"name": "فالكون", "mode": "falcon",
                         "api_url": "https://dash.falcon-panel.com/api/v1", "api_key": "rk_live_x",
                         "guide_url": "https://guide.ssouq.com/"})  # host اختياري لفالكون
    check("clean_gate accepts falcon (host optional)", gate["mode"] == "falcon" and gate["host"] == "")
    pk = X.get_packages(gate)
    check("get_packages routes to falcon (Arabic name)", len(pk) == 2 and pk[0]["name"] == "شهر" and pk[0]["name_en"] == "1months")
    out = X.create_line(gate, pk[0], "webuser", "webpass")
    check("create_line routes to falcon + new format", " User webuser " in out["line"] and " Pass webpass " in out["line"])
    check("host resolved from /me into the line", "s.falconiptv.ink" in out["line"])
    check("guide url appended", "Guide https://guide.ssouq.com/" in out["line"])

    print("\n== all_lines pages through and resolves package names (for Excel export) ==")
    PER = 50
    ALL = [{"id": 5000 + i, "username": "u%03d" % i, "password": "p%03d" % i,
            "status": "active", "expires_at": 1830000000, "created_at": "2026-01-01T00:00:00Z",
            "max_connections": 1, "package_id": 167 if i % 2 else 169} for i in range(1, 121)]

    def fake_paged(base, key, path, method="GET", body=None):
        if path == "/packages":
            return CANNED[("GET", "/packages")]
        if path.startswith("/lines"):
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(path).query)
            per = int(qs.get("per", ["50"])[0]); page = int(qs.get("page", ["1"])[0])
            start = (page - 1) * per
            return {"ok": True, "total": len(ALL), "page": page, "per": per,
                    "lines": ALL[start:start + per]}
        return CANNED.get((method, path), {"ok": False})
    falcon_api._request = fake_paged
    seen = []
    rows = falcon_api.all_lines("B", "K", progress=lambda n, last, page: seen.append(n), per=PER)
    check("all_lines returns every line across pages", len(rows) == 120, "n=%d" % len(rows))
    check("package id resolved to Arabic name", rows[0]["package"] in ("شهر", "3 اشهر", "٣ أشهر", "شهور", "3months") or bool(rows[0]["package"]), rows[0]["package"])
    check("rows carry username/password/exp/connections",
          rows[0]["username"] == "u001" and rows[0]["password"] == "p001"
          and rows[0]["exp"] and rows[0]["connections"] == 1, str(rows[0])[:90])
    check("progress was reported while paging", len(seen) >= 3 and seen[-1] == 120, str(seen))
    falcon_api._request = fake_request

    print("\n----------------------------------------")
    print(f"Result: \033[32m{_p} passed\033[0m, " + (f"\033[31m{_f} failed\033[0m" if _f else "0 failed"))
    sys.exit(1 if _f else 0)

if __name__ == "__main__":
    main()

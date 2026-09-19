#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
النطاقان: الأداة على نطاقها من الجذر، والموقع العام دليلُ تفعيل وحده.
  - admin.ssouq.com/        = الأداة (لا صفحات الدليل عليه، ولا فهرسة).
  - guide.ssouq.com/admin   = **لا يفتح شيئًا**: 404 كأن المسار لم يوجد.
  - Host آخر (محليًا/الاختبارات) = الأداة تحت /admin كما كانت، بلا تغيير.
  - XM_ADMIN_HOST فارغًا = لا نطاق للأداة ولا تحويل (طريق الرجوع).
تشغيل:  python tests/test_hosts.py
"""
import os, sys, json, time, shutil, tempfile, subprocess, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
ADMIN_PW = "envpass123"
_p = _f = 0


def check(l, c, x=""):
    global _p, _f
    print((f"  \033[32mPASS\033[0m  {l}" if c else f"  \033[31mFAIL\033[0m  {l}") + (f"  ({x})" if x else ""))
    _p += 1 if c else 0; _f += 0 if c else 1


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def req(base, path, host=None, method="GET", obj=None, proto=None, cookie=None):
    """(status, Location, body, Set-Cookie) بلا اتّباع أي تحويل."""
    h = {}
    if host:
        h["Host"] = host                       # urllib يحترم Host المُمرَّر
    if proto:
        h["X-Forwarded-Proto"] = proto
    if cookie:
        h["Cookie"] = cookie
    data = None
    if obj is not None:
        data = json.dumps(obj).encode(); h["Content-Type"] = "application/json"
    r = urllib.request.Request(base + path, data=data, headers=h, method=method)
    op = urllib.request.build_opener(_NoRedirect)
    try:
        x = op.open(r, timeout=15)
        return x.getcode(), x.headers.get("Location", ""), x.read().decode("utf-8", "replace"), x.headers.get("Set-Cookie", "")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location", ""), e.read().decode("utf-8", "replace"), e.headers.get("Set-Cookie", "")


def _up(u):
    for _ in range(60):
        try: urllib.request.urlopen(u, timeout=0.3); return
        except urllib.error.HTTPError: return
        except Exception: time.sleep(0.1)


def _start(port, data_dir, extra_env=None):
    env = dict(os.environ, XM_DATA=data_dir, XM_BIND="127.0.0.1", XM_PORT=str(port),
               XM_ADMIN_PASSWORD=ADMIN_PW)
    env.update(extra_env or {})
    return subprocess.Popen([sys.executable, os.path.join(ROOT, "xm_lines.py"), "web"],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    global _p, _f
    port, port_off = 9585, 9586
    base, base_off = f"http://127.0.0.1:{port}", f"http://127.0.0.1:{port_off}"
    d1 = tempfile.mkdtemp(prefix="hosts_"); d2 = tempfile.mkdtemp(prefix="hostsoff_")
    app = _start(port, d1)
    app_off = _start(port_off, d2, {"XM_ADMIN_HOST": ""})        # لا نطاق للأداة
    GUIDE, TOOL = "guide.ssouq.com", "admin.ssouq.com"
    try:
        _up(base + "/admin/login"); _up(base_off + "/admin/login")

        print("== الموقع العام يبقى دليلًا ==")
        c, _, body, _ = req(base, "/", GUIDE)
        check("‏/ على الموقع العام = صفحة الدليل", c == 200 and "guide.ssouq.com" in body, str(c))
        c, _, _, _ = req(base, "/samsung-lg", GUIDE)
        check("صفحات الأجهزة تعمل", c == 200, str(c))
        c, _, body, _ = req(base, "/robots.txt", GUIDE)
        check("robots العام فيه خريطة الموقع", "Sitemap:" in body, "")
        check("ولا يذكر /admin (لا مسار يُمنع)", "/admin" not in body, body.strip().replace("\n", " · "))

        print("\n== الموقع العام لا أداة عليه إطلاقًا ==")
        for u in ("/admin", "/admin/", "/admin/login", "/admin/accounts?x=1"):
            c, loc, body, _ = req(base, u, GUIDE)
            check(f"‏{u} = 404 بلا تحويل ولا صفحة دخول",
                  c == 404 and not loc and "تسجيل الدخول" not in body, f"{c} {loc}")
        c, _, body, _ = req(base, "/admin/login", GUIDE, proto="https")
        check("وخلف الوكيل كذلك", c == 404, str(c))
        c, _, body, _ = req(base, "/admin/api/login", GUIDE, method="POST",
                            obj={"user": "admin", "password": ADMIN_PW})
        check("‏POST على /admin/api = 404 (لا دخول من هنا)", c == 404, str(c))

        print("\n== نطاق الأداة: الأداة من الجذر ==")
        c, loc, _, _ = req(base, "/", TOOL)
        check("‏/ = الأداة لا الدليل (تحويل إلى الدخول)", c == 302 and loc == "/login", f"{c} -> {loc}")
        c, _, body, _ = req(base, "/login", TOOL)
        check("صفحة الدخول على الجذر", c == 200 and "تسجيل الدخول" in body, str(c))
        c, _, body, cook = req(base, "/api/login", TOOL, method="POST",
                               obj={"user": "admin", "password": ADMIN_PW})
        d = json.loads(body or "{}")
        check("دخول المدير من الجذر", c == 200 and d.get("role") == "admin", str(d))
        check("الكوكي على Path=/ لا /admin", "Path=/;" in cook and "Path=/admin" not in cook, cook.split(";")[1:2])
        tok = cook.split(";")[0]
        c, _, body, _ = req(base, "/accounts", TOOL, cookie=tok)
        check("صفحة الحسابات على /accounts", c == 200 and "إدارة الحسابات" in body, str(c))
        c, _, body, _ = req(base, "/api/accounts", TOOL, cookie=tok)
        check("‏API من الجذر", c == 200 and "accounts" in body, str(c))
        c, loc, _, _ = req(base, "/admin/accounts", TOOL)
        check("العنوان القديم على النطاق الجديد → 301 للجذر", c == 301 and loc == "/accounts", f"{c} -> {loc}")

        print("\n== نطاق الأداة لا يحمل الموقع العام ==")
        c, loc, body, _ = req(base, "/samsung-lg", TOOL)
        check("صفحة جهاز على نطاق الأداة ليست الدليل (تذهب للدخول)",
              c == 302 and loc == "/login", f"{c} -> {loc}")
        c, _, body, _ = req(base, "/samsung-lg", TOOL, cookie=tok)
        check("وبعد الدخول: 404 لا صفحة جهاز", c == 404 and "guide.ssouq.com" not in body, str(c))
        c, _, body, _ = req(base, "/robots.txt", TOOL)
        check("robots يمنع الفهرسة كلها", "Disallow: /" in body and "Sitemap:" not in body, body.strip().replace("\n", " · "))
        c, _, _, _ = req(base, "/static/logo.jpg", TOOL)
        check("الثابتات تُقدَّم (الأيقونات)", c == 200, str(c))
        c, _, _, _ = req(base, "/api/m3u-generated", TOOL, method="POST", obj={})
        check("عدّاد الموقع العام ليس على نطاق الأداة", c != 200, str(c))

        print("\n== Host آخر (محليًا) لا ينتقل شيء ==")
        c, loc, _, cook = req(base, "/admin", None)
        check("‏/admin على 127.0.0.1 يعمل كما كان", c == 302 and loc == "/admin/login", f"{c} -> {loc}")
        c, _, _, cook = req(base, "/admin/api/login", None, method="POST",
                            obj={"user": "admin", "password": ADMIN_PW})
        check("الكوكي يبقى على Path=/admin", "Path=/admin" in cook, cook.split(";")[1:2])
        c, _, body, _ = req(base, "/", None)
        check("الجذر محليًا = الدليل", c == 200 and "<!doctype html>" in body.lower(), str(c))

        print("\n== XM_ADMIN_HOST فارغًا = طريق الرجوع ==")
        c, loc, _, _ = req(base_off, "/admin", GUIDE)
        check("لا تحويل: /admin يبقى على الموقع العام", c == 302 and loc == "/admin/login", f"{c} -> {loc}")
        c, _, body, _ = req(base_off, "/", TOOL)
        check("النطاق الآخر يرى الدليل (لا نطاق للأداة)", c == 200 and "guide.ssouq.com" in body, str(c))
    finally:
        for pr in (app, app_off):
            pr.terminate()
            try: pr.wait(timeout=5)
            except Exception: pr.kill()
        shutil.rmtree(d1, ignore_errors=True); shutil.rmtree(d2, ignore_errors=True)
    print("\n----------------------------------------")
    print(f"Result: \033[32m{_p} passed\033[0m, " + (f"\033[31m{_f} failed\033[0m" if _f else "0 failed"))
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

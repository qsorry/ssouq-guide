#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
كلمة مرور المدير من متغيّر البيئة (XM_ADMIN_PASSWORD):
  - تُلغي صفحة الإعداد بعد كل إعادة نشر (قاعدة بيانات فارغة = لا setup).
  - تسجيل دخول المدير يعمل بها، والخطأ يُرفض.
  - بدونها، القاعدة الفارغة تُظهر صفحة الإعداد كالسابق (اختبار انحدار).
تشغيل:  python tests/test_admin_env.py
"""
import os, sys, json, time, shutil, tempfile, subprocess, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
_p = _f = 0
def check(l, c, x=""):
    global _p, _f
    print((f"  \033[32mPASS\033[0m  {l}" if c else f"  \033[31mFAIL\033[0m  {l}") + (f"  ({x})" if x else ""))
    _p += 1 if c else 0; _f += 0 if c else 1


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _opener():
    return urllib.request.build_opener(_NoRedirect)


def _location(base, path):
    """يرجّع (status, Location) دون اتّباع التحويل."""
    op = _opener()
    try:
        r = op.open(urllib.request.Request(base + path), timeout=15)
        return r.getcode(), r.headers.get("Location", "")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location", "")


def _post(base, path, obj):
    op = _opener()
    req = urllib.request.Request(base + path, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        r = op.open(req, timeout=15); return r.getcode(), json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read() or b"{}")
        except Exception: return e.code, {}


def _up(u):
    for _ in range(60):
        try: urllib.request.urlopen(u, timeout=0.3); return
        except urllib.error.HTTPError: return
        except Exception: time.sleep(0.1)


def _start(port, data_dir, extra_env=None):
    env = dict(os.environ, XM_DATA=data_dir, XM_BIND="127.0.0.1", XM_PORT=str(port))
    env.update(extra_env or {})
    return subprocess.Popen([sys.executable, os.path.join(ROOT, "xm_lines.py"), "web"],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    global _p, _f
    port_env, port_bare = 9581, 9582
    base_env, base_bare = f"http://127.0.0.1:{port_env}", f"http://127.0.0.1:{port_bare}"
    dir_env = tempfile.mkdtemp(prefix="env_"); dir_bare = tempfile.mkdtemp(prefix="bare_")
    app_env = _start(port_env, dir_env, {"XM_ADMIN_PASSWORD": "envpass123"})
    app_bare = _start(port_bare, dir_bare)                       # لا متغيّر بيئة
    try:
        _up(base_env + "/admin/login"); _up(base_bare + "/admin/login")

        print("== مع XM_ADMIN_PASSWORD وقاعدة فارغة ==")
        code, loc = _location(base_env, "/admin")
        check("/admin لا يحوّل إلى صفحة الإعداد", "/admin/setup" not in loc, f"{code} -> {loc}")
        check("/admin يحوّل إلى الدخول", loc.endswith("/admin/login"), loc)
        code, _ = _location(base_env, "/admin/setup")
        check("/admin/setup يحوّل بعيدًا (الإعداد مكتمل)", code in (301, 302), str(code))
        c, d = _post(base_env, "/admin/api/setup", {"password": "another"})
        check("POST setup مرفوض: تم الإعداد مسبقاً", c == 400 and "مسبق" in str(d.get("error", "")), str(d))
        c, d = _post(base_env, "/admin/api/login", {"user": "admin", "password": "envpass123"})
        check("دخول المدير يعمل بكلمة مرور البيئة", d.get("role") == "admin", str(d))
        c, d = _post(base_env, "/admin/api/login", {"user": "admin", "password": "wrong"})
        check("كلمة مرور خاطئة تُرفض", c == 401, str(c))

        print("\n== بدون متغيّر البيئة وقاعدة فارغة (انحدار) ==")
        code, loc = _location(base_bare, "/admin")
        check("/admin يحوّل إلى صفحة الإعداد كالسابق", loc.endswith("/admin/setup"), f"{code} -> {loc}")
    finally:
        for pr in (app_env, app_bare):
            pr.terminate()
            try: pr.wait(timeout=5)
            except Exception: pr.kill()
        shutil.rmtree(dir_env, ignore_errors=True); shutil.rmtree(dir_bare, ignore_errors=True)
    print("\n----------------------------------------")
    print(f"Result: \033[32m{_p} passed\033[0m, " + (f"\033[31m{_f} failed\033[0m" if _f else "0 failed"))
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

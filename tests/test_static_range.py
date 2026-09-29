#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
الملفات الثابتة بمقاطع (Range): سفاري الآيفون لا يشغّل فيديو MP4 إلا إن ردّ الخادم على
«Range: bytes=0-1» بـ 206 ومقطعٍ صحيح، فيُفحص هنا على فيديو SS IPTV نفسه: النوع، والمقاطع
الثلاثة (بداية-نهاية، ومن موضعٍ إلى الآخر، وآخر N بايت)، والمقطع غير الصالح يُتجاهل،
وما وراء الملف 416 — ولا يفتح شيءٌ منها بابًا خارج static.
تشغيل:  python tests/test_static_range.py
"""
import os, sys, time, shutil, tempfile, subprocess, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
PORT = 9852
BASE = f"http://127.0.0.1:{PORT}"
VIDEO = "/static/video/ssiptv-ar.mp4"
_p = _f = 0


def check(l, c, x=""):
    global _p, _f
    print((f"  \033[32mPASS\033[0m  {l}" if c else f"  \033[31mFAIL\033[0m  {l}") + (f"  ({x})" if x else ""))
    _p += 1 if c else 0; _f += 0 if c else 1


def get(path, rng=None, method="GET"):
    """(الحالة، الرؤوس، الجسم)"""
    r = urllib.request.Request(BASE + path, headers={"Range": rng} if rng else {}, method=method)
    try:
        x = urllib.request.urlopen(r, timeout=15)
        return x.getcode(), x.headers, x.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def main():
    data = tempfile.mkdtemp(prefix="range_")
    app = subprocess.Popen([sys.executable, os.path.join(ROOT, "xm_lines.py"), "web"],
                           env=dict(os.environ, XM_DATA=data, XM_BIND="127.0.0.1", XM_PORT=str(PORT)),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(80):
            try: urllib.request.urlopen(BASE + "/", timeout=0.3); break
            except Exception: time.sleep(0.1)
        raw = open(os.path.join(ROOT, VIDEO.lstrip("/")), "rb").read()
        n = len(raw)

        print("الملف كاملًا")
        c, h, b = get(VIDEO)
        check("200 بنوع video/mp4", c == 200 and h.get("Content-Type") == "video/mp4", h.get("Content-Type"))
        check("يعلن Accept-Ranges: bytes", h.get("Accept-Ranges") == "bytes")
        check("الجسم هو الملف كله", b == raw, f"{len(b)} من {n}")
        c, h, b = get(VIDEO, method="HEAD")
        check("HEAD بلا جسم وبطول الملف", c == 200 and b == b"" and h.get("Content-Length") == str(n))

        print("\nالمقاطع")
        c, h, b = get(VIDEO, "bytes=0-1")
        check("bytes=0-1 → 206 وبايتان (أول ما يطلبه سفاري)", c == 206 and b == raw[:2] and h.get("Content-Range") == f"bytes 0-1/{n}",
              f"{c} {h.get('Content-Range')}")
        c, h, b = get(VIDEO, "bytes=1000-")
        check("bytes=1000- → من الموضع إلى الآخر", c == 206 and b == raw[1000:] and h.get("Content-Range") == f"bytes 1000-{n - 1}/{n}")
        c, h, b = get(VIDEO, "bytes=-500")
        check("bytes=-500 → آخر 500 بايت", c == 206 and b == raw[-500:] and h.get("Content-Length") == "500")
        c, h, b = get(VIDEO, f"bytes=10-{n + 99}")
        check("نهايةٌ وراء الملف تُقصَر على آخره", c == 206 and b == raw[10:] and h.get("Content-Range") == f"bytes 10-{n - 1}/{n}")
        c, h, b = get(VIDEO, "bytes=50-10")
        check("مقطعٌ مقلوب غير صالح يُتجاهل: الملف كاملًا 200", c == 200 and b == raw)
        c, h, b = get(VIDEO, f"bytes={n}-")
        check("بدايةٌ وراء الملف → 416 مع حجمه", c == 416 and h.get("Content-Range") == f"bytes */{n}", f"{c} {h.get('Content-Range')}")
        c, h, b = get(VIDEO, "bytes=-0")
        check("آخر 0 بايت → 416", c == 416)
        c, h, b = get(VIDEO, "bytes=0-1,5-6")
        check("مقاطع متعددة تُتجاهل: الملف كاملًا", c == 200 and b == raw)

        print("\nبقية الملفات الثابتة")
        c, h, b = get("/static/video/ssiptv-ar.webp", "bytes=0-3")
        check("الغلاف webp بمقطع أيضًا", c == 206 and h.get("Content-Type") == "image/webp" and b == b"RIFF")
        c, h, b = get("/static/../xm_lines.py", "bytes=0-10")
        check("لا خروج من static ولو بمقطع", c == 404)
        c, h, b = get("/static/video/none.mp4", "bytes=0-1")
        check("ملفٌ غير موجود 404", c == 404)
    finally:
        app.terminate()
        try: app.wait(timeout=5)
        except Exception: app.kill()
        shutil.rmtree(data, ignore_errors=True)
    print(f"\nResult: {_p} passed, {_f} failed")
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""الشروحات على نطاق المتجر: صفحات الدليل تتحوّل إلى ssouq.com بـ 301 حين يُضبط XM_STORE_URL،
وما ليس له مقابل في المتجر (المسابقة، التجديد، Stremio، الواجهات، الصور، الخرائط) يبقى هنا.
وبلا XM_STORE_URL لا يتغيّر شيء.

تشغيل:  python tests/test_store_redirect.py
"""
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import guide_pages as G  # noqa: E402

_p = _f = 0
STORE = "https://ssouq.com"


def check(l, c, x=""):
    global _p, _f
    print((f"  \033[32mPASS\033[0m  {l}" if c else f"  \033[31mFAIL\033[0m  {l}") + (f"  ({x})" if x else ""))
    _p += 1 if c else 0
    _f += 0 if c else 1


class _NoFollow(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def req(base, path):
    op = urllib.request.build_opener(_NoFollow)
    r = urllib.request.Request(base + path, headers={"Host": "guide.ssouq.com"})
    try:
        with op.open(r, timeout=30) as x:
            return x.status, dict(x.headers)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers)


def unit():
    print("المسارات")
    want = {"/": "/guide", "/index.html": "/guide", "/compare": "/choose", "/samsung-lg": "/guide/samsung-lg",
            "/iphone/": "/guide/iphone", "/report": "/report", "/content": "/content", "/content/smart": "/content/smart",
            "/en/content/casper": "/en/content/casper", "/watch": "/watch", "/watch/saudi-pro-league": "/watch/saudi-pro-league",
            "/standings/la-liga": "/standings/la-liga"}
    for path, to in want.items():
        check(f"{path} ← {to}", G.store_path(path) == to, G.store_path(path))
    for path in ("/predict", "/gulf-cup", "/gulf-cup/x-vs-y", "/nations-league", "/renew", "/stremio", "/api/content",
                 "/api/report/servers", "/static/img/a.webp", "/content/smart/img/a.webp", "/sitemap.xml", "/robots.txt",
                 "/store-sitemap.xml", "/admin", "/content/smart/movie/x"):
        check(f"{path} يبقى هنا", G.store_path(path) is None, G.store_path(path))
    for path in G.PAGES:
        check(f"كل صفحات الدليل لها مقابل: {path}", G.store_path(path) is not None)


def _up(url):
    for _ in range(300):
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except Exception:
            time.sleep(0.1)


def live():
    print("\nعلى الخادم")
    procs = []
    bases = {}
    for name, port, store in (("on", 9641, STORE + "/"), ("off", 9642, "")):
        env = dict(os.environ, XM_DATA=tempfile.mkdtemp(prefix="redir_"), XM_BIND="127.0.0.1", XM_PORT=str(port),
                   XM_ADMIN_PASSWORD="envpass123", XM_STORE_URL=store)
        procs.append(subprocess.Popen([sys.executable, os.path.join(ROOT, "xm_lines.py"), "web"], env=env,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        bases[name] = f"http://127.0.0.1:{port}"
    try:
        for b in bases.values():
            _up(b + "/robots.txt")
        on, off = bases["on"], bases["off"]
        c, h = req(on, "/")
        check("الرئيسية ← ssouq.com/guide (301)", c == 301 and h.get("Location") == STORE + "/guide", h.get("Location"))
        c, h = req(on, "/samsung-lg?utm_source=x")
        check("صفحة جهاز ← صفحتها مع الاستعلام", c == 301 and h.get("Location") == STORE + "/guide/samsung-lg?utm_source=x", h.get("Location"))
        c, h = req(on, "/content/smart")
        check("المحتوى ← المسار نفسه", c == 301 and h.get("Location") == STORE + "/content/smart", h.get("Location"))
        c, _ = req(on, "/robots.txt")
        check("robots يبقى", c == 200)
        c, _ = req(on, "/api/content")
        check("واجهة المحتوى (يقرؤها المتجر) تبقى", c == 200)
        c, _ = req(on, "/static/guide-data.json")
        check("الملفات الثابتة تبقى", c == 200)
        c, _ = req(on, "/predict")
        check("مسابقة التوقّعات تبقى", c != 301)
        c, _ = req(off, "/")
        check("بلا XM_STORE_URL: الرئيسية كما هي", c == 200)
        c, _ = req(off, "/samsung-lg")
        check("بلا XM_STORE_URL: صفحة الجهاز كما هي", c == 200)
    finally:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    unit()
    live()
    print(f"\n{_p} PASS · {_f} FAIL")
    sys.exit(1 if _f else 0)

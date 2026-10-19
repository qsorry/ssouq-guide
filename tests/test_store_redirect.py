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


def req(base, path, via_store=False, body=False):
    op = urllib.request.build_opener(_NoFollow)
    hd = {"Host": "guide.ssouq.com", **({G.VIA_STORE: "1"} if via_store else {})}
    r = urllib.request.Request(base + path, headers=hd)
    try:
        with op.open(r, timeout=30) as x:
            return (x.status, dict(x.headers), x.read()) if body else (x.status, dict(x.headers))
    except urllib.error.HTTPError as e:
        return (e.code, dict(e.headers), e.read()) if body else (e.code, dict(e.headers))


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

    print("طبقة الكيانات")
    layer = ("/content/series/the-boys/", "/content/series/the-boys/season-2/episode-3/", "/en/content/movies/dune-2021/",
             "/content/latest", "/content/latest/series/page/2/", "/content/genres/drama/", "/content/turkish/", "/content/anime",
             "/content/people/actors/x/", "/content/for-you/")
    for path in layer:
        check(f"قبل النقل تبقى هنا: {path}", G.store_path(path) is None, G.store_path(path))
    G.CONTENT_MOVED = True
    try:
        for path in layer:
            check(f"بعد النقل ← المسار نفسه: {path}", G.store_path(path) == path, G.store_path(path))
        for path, to in (("/content/smart", "/content/smart"), ("/content/smart/img/a.webp", None), ("/samsung-lg", "/guide/samsung-lg")):
            check(f"وغيرها كما كان: {path}", G.store_path(path) == to, G.store_path(path))
    finally:
        G.CONTENT_MOVED = False

    print("خريطة المحتوى")
    ents = [("/content/series/a/", "weekly", "0.7"), ("/en/content/series/a/", "weekly", "0.7"), ("/content/movies/b/", "weekly", "0.7"),
            ("/content/latest/", "daily", "0.5")]
    xml = G.content_sitemap(ents).decode()
    check("روابط الطبقة وحدها (بلا الرئيسية وصفحات الأجهزة)", xml.count("<loc>") == 4 and "/samsung-lg<" not in xml and f"<loc>{G.SITE}/</loc>" not in xml)
    check("ولا خريطة فرعية ما دامت واحدة", G.content_sitemap(ents, "sitemap-content-static.xml") is None)
    old_max, old_part = G.SITEMAP_SINGLE_MAX, G.SITEMAP_PART_MAX
    G.SITEMAP_SINGLE_MAX, G.SITEMAP_PART_MAX = 2, 1
    try:
        idx = G.content_sitemap(ents).decode()
        check("فوق الحد: فهرسٌ بخرائط sitemap-content-…", "<sitemapindex" in idx and f"{G.SITE}/sitemap-content-series-ar.xml" in idx
              and f"{G.SITE}/sitemap-content-movies-ar.xml" in idx and f"{G.SITE}/sitemap-content-series-en.xml" in idx, idx)
        part = (G.content_sitemap(ents, "sitemap-content-series-ar.xml") or b"").decode()
        check("والخريطة الفرعية بروابط قسمها", "/content/series/a/" in part and "/en/" not in part)
    finally:
        G.SITEMAP_SINGLE_MAX, G.SITEMAP_PART_MAX = old_max, old_part


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
    for name, port, store, site in (("on", 9641, STORE + "/", ""), ("off", 9642, "", ""), ("moved", 9643, STORE, STORE)):
        env = dict(os.environ, XM_DATA=tempfile.mkdtemp(prefix="redir_"), XM_BIND="127.0.0.1", XM_PORT=str(port),
                   XM_ADMIN_PASSWORD="envpass123", XM_STORE_URL=store, XM_SITE_URL=site)
        env.pop("XM_SITE_HOST", None)
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
        c, _ = req(on, "/content/series/x/")
        check("طبقة الكيانات قبل النقل: لا تحويل", c != 301)
        mv = bases["moved"]
        c, h = req(mv, "/content/series/x/season-1/?a=1")
        check("بعد النقل: صفحة الطبقة ← المسار نفسه في المتجر", c == 301 and h.get("Location") == STORE + "/content/series/x/season-1/?a=1", h.get("Location"))
        c, h = req(mv, "/content/series/x/", via_store=True)
        check("وما مرّره وسيط المتجر يُرسم هنا لا يُحوَّل (لا حلقة)", c != 301, (c, h.get("Location")))
        c, h = req(mv, "/samsung-lg", via_store=True)
        check("والوسيط لا يمرّ بتحويل الشروحات أيضًا", c == 200, c)
        c, _ = req(mv, "/admin/login")
        check("بعد النقل: لا أداة على guide.ssouq.com (يبقى مضيف هذه الخدمة)", c == 404, c)
        c, h, b = req(mv, "/sitemap-content.xml", via_store=True, body=True)
        check("خريطة المحتوى تُخدم", c == 200 and b"<urlset" in b and "xml" in h.get("Content-Type", ""), c)
        c, _ = req(mv, "/sitemap-content-series-ar.xml", via_store=True)
        check("وخريطةٌ فرعية غير موجودة ← 404", c == 404, c)
        c, _ = req(mv, "/api/content")
        check("بعد النقل: واجهة المحتوى تبقى", c == 200, c)
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

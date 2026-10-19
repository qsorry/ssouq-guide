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
    mixed = ents + [("/content/series/a/season-1/", "weekly", "0.5"), ("/content/people/actors/z/", "weekly", "0.5"), ("/en/content/movies/b/", "weekly", "0.7"), ("/content/turkish/", "daily", "0.5")]
    ex = G.content_sitemap(mixed, extras=True).decode()
    check("extras: بلا المسلسلات والأفلام العربية (يخدمها المتجر)", f"{G.SITE}/content/series/a/<" not in ex and f"{G.SITE}/content/movies/b/<" not in ex and f"{G.SITE}/content/series/a/season-1/<" in ex, ex[:300])
    check("وفيها الإنجليزية والمواسم والأشخاص والهبّات والأحدث", all(x in ex for x in ("/en/content/series/a/<", "/en/content/movies/b/<", "/content/people/actors/z/<", "/content/turkish/<", "/content/latest/<")))
    check("والكاملة كما هي (فيها العربية)", f"{G.SITE}/content/series/a/<" in G.content_sitemap(mixed).decode())
    old_max2, old_part2 = G.SITEMAP_SINGLE_MAX, G.SITEMAP_PART_MAX
    G.SITEMAP_SINGLE_MAX, G.SITEMAP_PART_MAX = 3, 100
    try:
        ix2 = G.content_sitemap(mixed, extras=True).decode()
        check("extras فوق الحد: فهرسٌ بأجزاءٍ باسمها sitemap-content-extras-…", "<sitemapindex" in ix2 and "/sitemap-content-extras-" in ix2 and "/sitemap-content-series" not in ix2, ix2[:400])
    finally:
        G.SITEMAP_SINGLE_MAX, G.SITEMAP_PART_MAX = old_max2, old_part2
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


def sitemap_cache():
    print("كاش الخرائط")
    import xm_lines as X
    calls = []

    def build():
        calls.append(1)
        return b"v%d" % len(calls)

    def settle(n):
        for _ in range(200):
            if len(calls) >= n and not X._sitemap_refreshing:
                return
            time.sleep(0.01)
    X._sitemap_cache.clear()
    a, b = X.cached_sitemap("/t.xml", build), X.cached_sitemap("/t.xml", build)
    check("الأولى تُبنى مرةً واحدة وتُعاد من الكاش", len(calls) == 1 and a == b == b"v1", len(calls))
    keep = X._sitemap_version
    try:
        X._sitemap_version = lambda: ("changed",)
        stale = X.cached_sitemap("/t.xml", build)
        check("تبدّلت قاعدة SEO: تُعاد النسخة القديمة فورًا", stale == b"v1")
        settle(2)
        check("وتُجدَّد في الخلفية مرةً واحدة فتصير الجديدة", len(calls) == 2 and X.cached_sitemap("/t.xml", build) == b"v2", len(calls))
    finally:
        X._sitemap_version = keep
    ttl = X.SITEMAP_TTL
    try:
        X.SITEMAP_TTL = 0
        old = X.cached_sitemap("/t.xml", build)
        settle(3)
        check("وانقضاء المهلة كذلك: القديمة فورًا ثم الجديدة", old == b"v2" and len(calls) == 3, (old, len(calls)))
    finally:
        X.SITEMAP_TTL = ttl
    X._sitemap_cache.clear()
    check("غير الموجودة (None) لا تُخزَّن", X.cached_sitemap("/none.xml", lambda: None) is None and "/none.xml" not in X._sitemap_cache)
    n0 = len(calls)
    X._sitemap_cache["/b.xml"] = (0, ("old",), b"stale")
    ts = [__import__("threading").Thread(target=lambda: X.cached_sitemap("/b.xml", build)) for _ in range(6)]
    [t.start() for t in ts]; [t.join() for t in ts]
    settle(n0 + 1)
    check("تزاحم الطلبات على المنتهية: بناءٌ واحدٌ في الخلفية", len(calls) == n0 + 1, len(calls) - n0)


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
        c, _ = req(on, "/sitemap-content-extras.xml", via_store=True)
        check("خريطة extras تُخدم (200) وبأجزاءٍ غير موجودة 404", c == 200 and req(on, "/sitemap-content-extras-series-ar.xml", via_store=True)[0] == 404, c)
        for pth in ("/api/content/entities/index", "/api/content/entities?keys=series:x", "/api/content/entities/index?lang=en"):
            c, _ = req(on, pth)
            check(f"التصدير الدفعي مغلقٌ (404) قبل المعاينة والفهرسة: {pth}", c == 404, c)
        c, _ = req(off, "/")
        check("بلا XM_STORE_URL: الرئيسية كما هي", c == 200)
        c, _ = req(off, "/samsung-lg")
        check("بلا XM_STORE_URL: صفحة الجهاز كما هي", c == 200)
    finally:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    unit()
    sitemap_cache()
    live()
    print(f"\n{_p} PASS · {_f} FAIL")
    sys.exit(1 if _f else 0)

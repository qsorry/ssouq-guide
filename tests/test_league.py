#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ترتيب الدوريات (league.py): القراءة والتعريب والكاش والصفحات، بلا إنترنت.

  - رد ESPN ← جداول مرتّبة بأسماء عربية، ومناطق التأهل والهبوط، والغرب قبل الشرق.
  - الكاش: جلبٌ واحد في المدة، والمحفوظ يُقدَّم فورًا ويُجدَّد في الخلفية، والفشل
    يُبقي آخر نسخة، والنسخة الأقدم من يومين لا تُعرض.
  - /api/league و/standings/… وخريطة الموقع على خادم حيّ مع ESPN وهمية
    (tests/mock_espn.py)، ومع ESPN لا تردّ.

تشغيل:  python tests/test_league.py
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import guide_pages  # noqa: E402
import league as L  # noqa: E402
import mock_espn  # noqa: E402

_p = _f = 0


def check(l, c, x=""):
    global _p, _f
    print((f"  \033[32mPASS\033[0m  {l}" if c else f"  \033[31mFAIL\033[0m  {l}") + (f"  ({x})" if x else ""))
    _p += 1 if c else 0
    _f += 0 if c else 1


def reset(fetch):
    """كاش فارغ كأن الخادم أقلع للتوّ، وجلبٌ من الدالة المعطاة."""
    for feed in L._state.values():
        feed.reset()
    L._fetch = fetch


def idle(slug, timeout=5):
    end = time.time() + timeout
    while L._state[slug].busy and time.time() < end:
        time.sleep(0.01)


def unit():
    print("القراءة والتعريب")
    t = L.parse(mock_espn.payload("ksa.1"))
    rows = t["groups"][0]["rows"]
    check("الموسم من الرد", t["season"] == "2026-27", t["season"])
    check("الصفوف مرتّبة بالمركز وإن جاءت مقلوبة", [r["rank"] for r in rows] == list(range(1, 19)))
    check("المتصدّر بالعربية", rows[0]["name"] == "الهلال", rows[0]["name"])
    check("نادٍ مجهول يبقى باسمه الإنجليزي", rows[-1]["name"] == 'New <b>Club</b> & "Co"')
    check("الشعار مصغّرًا من خادم ESPN",
          rows[0]["logo"] == "https://a.espncdn.com/combiner/i?img=/i/teamlogos/soccer/500/929.png&w=48&h=48",
          rows[0]["logo"])
    check("شعار من خادم غريب يُسقط", rows[-1]["logo"] == "")
    check("نادٍ بلا شعار", next(r for r in rows if r["name"] == "الفيصلي")["logo"] == "")
    check("الأرقام أعداد صحيحة", all(isinstance(r[k], int) for r in rows
                                     for k in ("p", "w", "d", "l", "gf", "ga", "gd", "pts")))
    check("الدوري السعودي بلا مناطق", t["zones"] == {} and all(r["zone"] == "" for r in rows))

    e = L.parse(mock_espn.payload("eng.1"))
    zr = [r["zone"] for r in e["groups"][0]["rows"]]
    check("مناطق الإنجليزي بترتيب ظهورها", list(e["zones"]) == ["ucl", "uel", "ueclq", "rel"], str(list(e["zones"])))
    check("التصفيات لا تُقرأ دوريَ المؤتمر نفسه", zr[5] == "ueclq" and e["zones"]["ueclq"]["label"] == "تصفيات دوري المؤتمر الأوروبي")
    check("الهبوط لآخر ثلاثة", zr[-3:] == ["rel"] * 3 and zr[6] == "")

    u = L.parse(mock_espn.payload("uefa.champions"))
    check("36 فريقًا في أبطال أوروبا", len(u["groups"][0]["rows"]) == 36)
    check("المصنّف وغير المصنّف منطقتان", {"kos", "kou"} <= set(u["zones"]))
    unk = [z for k, z in u["zones"].items() if k.startswith("x-")]
    check("ملاحظة غير معروفة تبقى بنصّها", unk and unk[0]["label"] == "Mystery Zone")

    a = L.parse(mock_espn.payload("afc.champions"))
    check("أبطال آسيا: الغرب أولًا ثم الشرق", [g["name"] for g in a["groups"]] == ["منطقة الغرب", "منطقة الشرق"],
          str([g["name"] for g in a["groups"]]))

    for bad in ({}, {"children": []}, {"children": [{"standings": {"entries": []}}]}):
        try:
            L.parse(bad)
            check(f"رد بلا جدول يُرفض: {bad}", False)
        except ValueError:
            check(f"رد بلا جدول يُرفض: {json.dumps(bad)[:40]}", True)

    print("\nالأسماء")
    check("كل الأسماء عربية", not [v for v in L.AR.values() if re.search("[A-Za-z]", v)])
    check("لا اسمين لناديين", len(set(L.AR.values())) == len(L.AR))
    check("كل أندية الوهمية معرَّبة (عدا المجهول)",
          all(tid in L.AR for tid, _ in mock_espn.SAUDI[:-1] + mock_espn.EUROPE + mock_espn.WEST + mock_espn.EAST))
    check("العدد مع معدوده", [L.count(n, L.POINTS) for n in (1, 2, 7, 10, 11, 18, 100, 101, 103, 111)]
          == ["نقطة واحدة", "نقطتين", "7 نقاط", "10 نقاط", "11 نقطة", "18 نقطة", "100 نقطة", "101 نقطة",
              "103 نقاط", "111 نقطة"])
    check("المجموعات بأسمائها العربية", [L._group(n, 0)[1] for n in ("Group A", "Group F", "Group A2", "Group D1")]
          == ["المجموعة الأولى", "المجموعة السادسة", "المجموعة الثانية", "المجموعة الأولى"])

    print("\nالكاش")
    calls = []

    def ok(code):
        calls.append(code)
        return mock_espn.payload(code)

    def down(code):
        calls.append(code)
        raise OSError("connection refused")

    reset(ok)
    t = L.table("premier-league")
    check("أول طلب ينتظر الجلب الأول فيعود بالجدول", t["ok"] and len(calls) == 1)
    L.table("premier-league")
    check("لا جلب ثانٍ في المدة", len(calls) == 1)
    L.table("champions-league")
    check("لكل دوري كاشه", calls == ["eng.1", "uefa.champions"], str(calls))
    L._state["premier-league"].next = 0            # انتهت المدة
    L._fetch = down
    t = L.table("premier-league")
    check("بعد المدة يُقدَّم المحفوظ فورًا", t["ok"])
    idle("premier-league")
    st = L._state["premier-league"]
    check("الفشل في الخلفية يُبقي النسخة ويؤجّل المحاولة",
          st.data and st.error == "connection refused" and 0 < st.next - time.time() <= L.RETRY)
    n = len(calls)
    L.table("premier-league")
    check("لا محاولة قبل دقيقتين", len(calls) == n)
    st.at, st.next = time.time() - L.MAX_AGE - 1, time.time() + 999
    check("نسخة أقدم من يومين لا تُعرض", L.table("premier-league")["ok"] is False)
    reset(down)
    t = L.table()
    check("بلا نسخة وفشل أول جلب = ok:false بسببه", t["ok"] is False and t["error"] == "connection refused")
    check("الافتراضي هو الدوري السعودي", t["slug"] == L.DEFAULT == "saudi-pro-league")
    check("مفتاح غير معروف = None", L.table("nope") is None and L.api("nope") is None and L.render("nope") is None)

    print("\nالبطاقة والصفحة")
    reset(ok)
    c = L.api()
    h = c["html"]
    check("البطاقة: 6 صفوف وقائمة الدوريات كاملة",
          h.count("<tr") == 7 and [m["slug"] for m in c["leagues"]] == list(L.LEAGUES), str(h.count("<tr")))
    check("البطاقة بلا عمودَي له/عليه، وتربط الصفحة", "gfga" not in h and 'href="/standings/saudi-pro-league"' in h)
    h = L.api("afc-champions-league")["html"]
    check("مجموعتان: 4 صفوف لكل واحدة", h.count("<tr") == 2 * 5 and h.index("منطقة الغرب") < h.index("منطقة الشرق"))
    h = L.api("premier-league")["html"]
    check("دليل الألوان لما ظهر وحده في البطاقة", 'class="zones"' in h and "الهبوط" not in h and "دوري أبطال أوروبا" in h)
    code, raw = L.render("saudi-pro-league")
    page = raw.decode("utf-8")
    check("الصفحة 200 كاملة", code == 200 and page.count("<tr") == 19)
    check("العنوان بالموسم", "<title>جدول ترتيب دوري روشن السعودي 2026-27 | سمارت سوق</title>" in page)
    check("canonical", f'rel="canonical" href="{guide_pages.SITE}/standings/saudi-pro-league"' in page)
    check("الوصف يذكر المتصدّر بعدد صحيح", "يتصدّر الهلال برصيد 54 نقطة بعد 6 مباريات." in page)
    check("روابط كل الدوريات، والحالي معلَّم", all(f'href="/standings/{k}"' in page for k in L.LEAGUES)
          and 'href="/standings/saudi-pro-league" aria-current=page' in page)
    check("الاسم الإنجليزي مُهرَّب", "<b>Club</b>" not in page and "New &lt;b&gt;Club&lt;/b&gt; &amp; &quot;Co&quot;" in page)
    blocks = re.findall(r'application/ld\+json">(.*?)</script>', page, re.S)
    try:
        crumbs = json.loads(blocks[0])
        check("BreadcrumbList صالح", crumbs["@type"] == "BreadcrumbList" and len(crumbs["itemListElement"]) == 2)
    except Exception as e:
        check("BreadcrumbList صالح", False, str(e)[:60])
    check("أنماط المعالج نفسها", ".standings{" in page and "--crest" in page)
    page = L.render("premier-league")[1].decode("utf-8")
    check("المنطقة تُقرأ لا لونًا وحده", '<span class="sr"> — الهبوط</span>' in page
          and 'title="دوري أبطال أوروبا"' in page)
    reset(down)
    code, raw = L.render("premier-league")
    page = raw.decode("utf-8")
    check("تعذّر الجلب = 503 برسالة وروابط", code == 503 and "تعذّر تحميل الترتيب الآن" in page
          and "<table" not in page and 'href="/standings/la-liga"' in page)

    print("\nالرئيسية وخريطة الموقع")
    idx = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    fb = idx[idx.index('<div id="fallback">'):idx.index("</main>")]
    check("النسخة الثابتة تربط كل الدوريات", all(f'href="/standings/{k}"' in fb for k in L.LEAGUES))
    check("القائمة تربط الترتيب", f'href="/standings/{L.DEFAULT}"' in idx[:idx.index("</nav>")])
    sm = guide_pages.sitemap(L.SITEMAP).decode("utf-8")
    check("كل صفحات الترتيب في المخطط", all(f"<loc>{guide_pages.SITE}/standings/{k}</loc>" in sm for k in L.LEAGUES))
    check("وصفحات الأجهزة باقية", all(f"<loc>{guide_pages.SITE}{p}</loc>" in sm for p in guide_pages.PAGES))


def req(base, path, host=None):
    """(الحالة، الترويسات، النص) بلا اتّباع تحويل."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    r = urllib.request.Request(base + path, headers={"Host": host} if host else {})
    try:
        x = urllib.request.build_opener(NoRedirect).open(r, timeout=20)
        return x.getcode(), x.headers, x.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read().decode("utf-8", "replace")


def _up(url):
    for _ in range(80):
        try:
            urllib.request.urlopen(url, timeout=0.3)
            return
        except urllib.error.HTTPError:
            return
        except Exception:
            time.sleep(0.1)


def live():
    mport, port, dport = 9596, 9597, 9598
    base, dead = f"http://127.0.0.1:{port}", f"http://127.0.0.1:{dport}"
    procs = [subprocess.Popen([sys.executable, os.path.join(HERE, "mock_espn.py"), str(mport)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
    for p, api in ((port, f"http://127.0.0.1:{mport}"), (dport, "http://127.0.0.1:9")):
        env = dict(os.environ, XM_DATA=tempfile.mkdtemp(prefix="league_"), XM_BIND="127.0.0.1",
                   XM_PORT=str(p), XM_ADMIN_PASSWORD="envpass123", LEAGUE_API=api)
        procs.append(subprocess.Popen([sys.executable, os.path.join(ROOT, "xm_lines.py"), "web"],
                                      env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    try:
        _up(f"http://127.0.0.1:{mport}/ksa.1/standings"); _up(base + "/robots.txt"); _up(dead + "/robots.txt")
        print("\nعلى الخادم")
        c, h, b = req(base, "/api/league")
        d = json.loads(b)
        check("/api/league = الدوري السعودي", c == 200 and d["ok"] and d["slug"] == "saudi-pro-league" and "<table" in d["html"])
        check("يُحفظ في المتصفح خمس دقائق", h.get("Cache-Control") == "public, max-age=300", h.get("Cache-Control"))
        c, _, b = req(base, "/api/league?l=premier-league")
        check("?l= يختار الدوري", c == 200 and json.loads(b)["league"] == "الدوري الإنجليزي الممتاز")
        c, _, _ = req(base, "/api/league?l=nope")
        check("دوري غير معروف = 404", c == 404)
        c, h, _ = req(base, "/standings")
        check("/standings ← الدوري الافتراضي (301)", c == 301 and h.get("Location") == "/standings/saudi-pro-league")
        c, h, b = req(base, "/standings/afc-champions-league", "guide.ssouq.com")
        check("صفحة أبطال آسيا على الموقع العام", c == 200 and "text/html" in h.get("Content-Type", "")
              and b.index("منطقة الغرب") < b.index("منطقة الشرق"))
        c, _, _ = req(base, "/standings/nope")
        check("صفحة دوري غير معروف = 404", c == 404)
        c, _, b = req(base, "/sitemap.xml")
        check("المخطط يحمل صفحات الترتيب", c == 200 and "/standings/premier-league</loc>" in b)
        c, _, b = req(base, "/api/league", "admin.ssouq.com")
        check("نطاق الأداة لا يقدّم الترتيب", c != 200 or '"leagues"' not in b, str(c))
        c, _, b = req(base, "/standings/premier-league", "admin.ssouq.com")
        check("ولا صفحاته", c != 200 or "جدول ترتيب" not in b, str(c))

        print("\nESPN لا تردّ")
        c, h, b = req(dead, "/api/league")
        d = json.loads(b)
        check("ok:false بلا جدول", c == 200 and d["ok"] is False and "html" not in d and d.get("error"))
        check("والفشل لا يُحفظ في المتصفح", h.get("Cache-Control") == "no-store", h.get("Cache-Control"))
        c, h, b = req(dead, "/standings/premier-league")
        check("الصفحة 503 مع Retry-After", c == 503 and h.get("Retry-After") == str(L.RETRY)
              and "تعذّر تحميل الترتيب الآن" in b)
        c, _, _ = req(dead, "/")
        check("والرئيسية تعمل", c == 200)
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            p.wait(timeout=10)


def main():
    unit()
    live()
    print(f"\n{_p} نجح · {_f} فشل")
    return 1 if _f else 0


if __name__ == "__main__":
    sys.exit(main())

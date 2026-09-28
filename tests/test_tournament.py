#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""صفحة البطولة (tournament.py): دوري الأمم الأوروبية — المستوى الأول، بلا إنترنت.

  - المستوى الأول وحده: مجموعاته وأدواره الإقصائية وملحقٌ طرفه منه، لا الثاني.
  - الحالات: منتهية، ترجيح، تمديد، مباشرة، استراحة، مؤجلة، وأطرافٌ لم تُعرف بعد.
  - الأقسام: «اليوم» فيه الجارية دائمًا، والنتائج الأحدث أولًا، والقادمة بالموعد.
  - الترتيب بمناطق المراكز لا بملاحظات ESPN المختلطة، وإعلان الاشتراكات من CATALOG.
  - صفحة المباراة: رابطها، وموعدها أو نتيجتها، وأهدافها وإحصاءاتها، ومجموعتها، وSportsEvent.
  - /nations-league وخريطة الموقع على خادم حيّ مع ESPN وهمية، ومع ESPN لا تردّ.

تشغيل:  python tests/test_tournament.py
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

import league as L  # noqa: E402
import mock_espn  # noqa: E402
import tournament as T  # noqa: E402

_p = _f = 0


def check(l, c, x=""):
    global _p, _f
    print((f"  \033[32mPASS\033[0m  {l}" if c else f"  \033[31mFAIL\033[0m  {l}") + (f"  ({x})" if x else ""))
    _p += 1 if c else 0
    _f += 0 if c else 1


def fake_espn(path):
    """league.get_json من الوهمية مباشرة، بلا خادم."""
    m = re.fullmatch(r"/site/v2/sports/soccer/([\w.]+)/scoreboard\?dates=(\d+)", path)
    if m:
        return mock_espn.scoreboard(m.group(1), m.group(2))
    m = re.fullmatch(r"/site/v2/sports/soccer/([\w.]+)/summary\?event=(\d+)", path)
    if m:
        got = mock_espn.summary(m.group(1), m.group(2))
        if got is None:
            raise OSError("HTTP Error 400")
        return got
    m = re.fullmatch(r"/v2/sports/soccer/([\w.]+)/standings", path)
    return mock_espn.payload(m.group(1))


def section(page, key):
    m = re.search(rf'<section class="card" id="{key}".*?</section>', page, re.S)
    return m.group(0) if m else ""


def unit():
    print("المباريات")
    ms = T.matches(mock_espn.scoreboard("uefa.nations", "2026")["events"])
    ids = [m["id"] for m in ms]
    check("المستوى الأول وحده: لا الثاني ولا ملحق C/D", "9" not in ids and "14" not in ids, str(ids))
    check("ملحقٌ طرفه من المستوى الأول يدخل", "13" in ids)
    check("الأدوار الإقصائية تدخل", {"10", "11", "12"} <= set(ids))
    check("مرتّبة بالموعد", [m["ts"] for m in ms] == sorted(m["ts"] for m in ms))
    by = {m["id"]: m for m in ms}
    check("الأسماء بالعربية", by["1"]["home"]["name"] == "فرنسا" and by["1"]["away"]["name"] == "بلجيكا")
    check("اسم المجموعة بالعربية", by["1"]["stage"] == "المجموعة الأولى" and by["4"]["stage"] == "المجموعة الرابعة")
    check("أسماء الأدوار", by["11"]["stage"] == "ربع النهائي" and by["13"]["stage"] == "ملحق الصعود والهبوط")
    check("أطرافٌ لم تُعرف بعد", (by["10"]["home"]["name"], by["10"]["away"]["name"])
          == ("متصدّر المجموعة الأولى", "وصيف المجموعة الثانية"))
    check("ركلات الترجيح", (by["11"]["home"]["so"], by["11"]["away"]["so"]) == (5, 4) and by["11"]["home"]["win"])
    check("ساعة لم تُعتمد", by["10"]["time_ok"] is False and by["6"]["time_ok"] is True)
    check("العلم مصغّرًا من ESPN", by["1"]["home"]["logo"].startswith(L.LOGO_HOST + "/combiner/i?img=/i/teamlogos/countries/"))
    check("أسماء مؤقتة أخرى", [T._placeholder(n) for n in ("TBD", "Quarterfinal 2 Winner", "Semifinal 1 Loser")]
          == ["يُحدَّد لاحقًا", "الفائز في ربع النهائي 2", "الخاسر في نصف النهائي 1"])

    print("\nالكاش")
    data = {"matches": ms, "groups": []}
    check("دقيقة واحدة ومباراة جارية", T._ttl(data) == T.LIVE_TTL)
    calm = [dict(m, state="post") for m in ms]
    check("ربع ساعة بلا مباريات قريبة", T._ttl({"matches": calm}) == L.TTL)
    soon = calm + [dict(ms[0], state="pre", time_ok=True, ts=time.time() + 20 * 60)]
    check("دقيقة واحدة قبل الانطلاق بنصف ساعة", T._ttl({"matches": soon}) == T.LIVE_TTL)
    late = calm + [dict(ms[0], state="pre", time_ok=False, ts=time.time() + 20 * 60)]
    check("ساعة غير معتمدة لا تسرّع التحديث", T._ttl({"matches": late}) == L.TTL)

    print("\nالترتيب")
    groups = T._groups(mock_espn.payload("uefa.nations"))
    check("المجموعات الأربع للمستوى الأول وحده", [g["name"] for g in groups]
          == ["المجموعة الأولى", "المجموعة الثانية", "المجموعة الثالثة", "المجموعة الرابعة"])
    check("المناطق بالمراكز لا بملاحظات ESPN", all([r["zone"] for r in g["rows"]] == ["qf", "qf", "rpo", "rel"] for g in groups))

    print("\nالصفحة")
    L.get_json = fake_espn
    T._feed.reset()
    code, raw, age = T.render()
    page = raw.decode("utf-8")
    check("200، وتتحدّث كل دقيقة والمباراة جارية", code == 200 and age == T.LIVE_TTL
          and '<meta http-equiv="refresh" content="60">' in page)
    check("العنوان", "<title>نتائج دوري الأمم الأوروبية 2026-27 — المستوى الأول ومباريات اليوم | سمارت سوق</title>" in page)
    check("canonical", f'rel="canonical" href="{T.guide_pages.SITE}/nations-league"' in page)
    check("الوصف بآخر نتيجة والفائز أولًا", "آخر نتيجة: فوز إسبانيا على إنجلترا 3-2." in page)
    order = [m.group(1) for m in re.finditer(r'<section class="card" id="(\w+)"', page)]
    check("الأقسام بترتيبها", order == ["today", "results", "upcoming", "groups"], str(order))
    today = section(page, "today")
    check("الجارية في «اليوم»: الدقيقة والاستراحة", "مباشر 67&#x27;" in today and "بين الشوطين" in today
          and today.count('class="match live"') == 2, today[:200])
    results = section(page, "results")
    pos = [results.find(n) for n in ("اليونان", "فرنسا", "الدنمارك", "اسكتلندا")]   # قبل يومين، 3، 9، 20
    check("النتائج الأحدث أولًا", -1 not in pos and pos == sorted(pos), str(pos))
    check("ترجيح وتمديد", 'ترجيح <span class="pens"><b>5</b>-<b>4</b></span>' in results and "بعد التمديد" in results)
    check("النتيجة: صاحب الأرض أولًا", '<span class="score"><b>2</b><i>-</i><b>1</b></span>' in results)
    up = section(page, "upcoming")
    check("القادمة: الساعة، والمؤجلة، وما لم تُعتمد ساعته",
          re.search(r'class="kick">\d{1,2}:\d\d [صم]<', up) and "مؤجلة" in up and "يُعلن لاحقًا" in up)
    check("الاسم الإنجليزي مُهرَّب", "<b>Evil</b>" not in page and "&lt;b&gt;Evil&lt;/b&gt; &amp; Co" in page)
    g = section(page, "groups")
    check("جداول المجموعات الأربع ودليل المناطق", g.count('<table class="standings">') == 4
          and "التأهل إلى ربع النهائي" in g and "الهبوط إلى المستوى الثاني" in g and "Relegation" not in g)
    check("لا يذكر المستوى الثاني", "السويد" not in page and "لاتفيا" not in page)

    print("\nالإعلان")
    cat = {p["id"]: p for b in T._catalog().values() for p in b["plans"]}
    check("باقات الإعلان موجودة في CATALOG", all(pid in cat for pid in T.ADS))
    ads = re.findall(r'<aside class="card ad (cup-ad-\w+)"', page)
    check("مرتان: بطاقة للجوال وعمود جانبي", ads == ["cup-ad-inline", "cup-ad-side"], str(ads))
    first = page.index('<section class="card" id="today"')
    check("بطاقة الجوال بعد القسم الأول", first < page.index('<aside class="card ad cup-ad-inline"') < page.index('id="results"'))
    for pid in T.ADS:
        p = cat[pid]
        check(f"{p['name']}: السعر من CATALOG ورابطه بحملة الصفحة",
              f"{p['price']} ر.س" in page and f"/{pid}?utm_source=guide.ssouq.com&amp;utm_medium=referral&amp;utm_campaign=nations-league" in page)
    check("لا قنوات بث في الصفحة", not re.search(r"(?i)bein|ssc|قناة", page[page.index("<body>"):]))

    print("\nصفحة المباراة")
    check("روابط المباريات بأسماء الفريقين", [by[i]["slug"] for i in ("1", "5", "10")]
          == ["1-france-belgium", "5-italy-turkiye", "10-group-a1-winner-group-a2-2nd-place"])
    check("صفحة البطولة تربط كل مباراة", 'href="/nations-league/1-france-belgium"' in page
          and page.count('<a class="match') == len(ms))
    check("رابطٌ مختصر أو خاطئ يحوَّل إلى رابطها",
          T.render_match("1") == ("redirect", "/nations-league/1-france-belgium") == T.render_match("1-x"))
    check("مباراةٌ ليست من البطولة = لا صفحة",
          T.render_match("999") is None and T.render_match("9-sweden-hungary") is None and T.render_match("abc") is None)
    code, raw, age = T.render_match("1-france-belgium")
    mp = raw.decode("utf-8")
    check("200 بعنوانها", code == 200 and "<title>فرنسا وبلجيكا في دوري الأمم الأوروبية: موعد المباراة والنتيجة | سمارت سوق</title>" in mp)
    check("وصف المنتهية بنتيجتها", "انتهت مباراة فرنسا وبلجيكا في دوري الأمم الأوروبية (المجموعة الأولى) بفوز فرنسا على بلجيكا 2-1." in mp)
    check("canonical رابطها", 'rel="canonical" href="https://guide.ssouq.com/nations-league/1-france-belgium"' in mp)
    goals = re.search(r'<ul class="goals">(.*?)</ul>', mp, re.S)
    g = goals.group(1) if goals else ""
    check("الأهداف بدقائقها وأصحابها ونوعها", g.count("<li") == 3 and '<span class="min" dir="ltr">12&#x27;</span>' in g
          and "Romelu Lukaku" in g and "(برأسية)" in g and "(ركلة جزاء)" in g)
    check("هدف الضيف في جهته", re.search(r'<li class="away">[^<]*<span class="min"[^>]*>40', g) is not None
          and g.count('class="home"') == 2)
    check("الإحصاءات بقيمتي الفريقين وشريط النسبة", "الاستحواذ" in mp and "<b>55%</b>" in mp and "<b>45%</b>" in mp
          and 'style="width:55%"' in mp and 'style="width:70%"' in mp)
    check("ترتيب مجموعتها ومبارياتها الأخرى", "ترتيب المجموعة الأولى" in mp and "مباريات المجموعة الأولى الأخرى" in mp
          and 'href="/nations-league/5-italy-turkiye"' in mp and 'href="/nations-league/1-france-belgium"' not in mp)
    blocks = [json.loads(b) for b in re.findall(r'application/ld\+json">(.*?)</script>', mp, re.S)]
    ev = next((b for b in blocks if b.get("@type") == "SportsEvent"), {})
    check("SportsEvent صالح", ev.get("homeTeam", {}).get("name") == "فرنسا" and ev.get("awayTeam", {}).get("name") == "بلجيكا"
          and ev.get("location", {}).get("name") == "Stade de France" and ev.get("startDate", "").endswith("+03:00"))
    check("مسار التنقّل ثلاث درجات", any(b.get("@type") == "BreadcrumbList" and len(b["itemListElement"]) == 3 for b in blocks))
    check("وإعلان الاشتراكات فيها", mp.count('<aside class="card ad') == 2)
    code, raw, age = T.render_match("4-portugal-wales")
    lp = raw.decode("utf-8")
    check("الجارية: مباشرة، وتتحدّث كل دقيقة", age == T.LIVE_TTL and '<meta http-equiv="refresh" content="60">' in lp
          and "مباشرة الآن: البرتغال 1، ويلز 0." in lp and "Cristiano Ronaldo" in lp)
    code, raw, age = T.render_match("6-netherlands-serbia")
    pp = raw.decode("utf-8")
    check("القادمة: موعدها بالساعة، بلا أهداف ولا إحصاءات", code == 200 and "موعد مباراة هولندا وصربيا" in pp
          and re.search(r"الساعة \d{1,2}:\d\d [صم] بتوقيت السعودية", pp) and "<h2>الأهداف</h2>" not in pp
          and "<h2>إحصاءات المباراة</h2>" not in pp)
    code, raw, age = T.render_match("10-group-a1-winner-group-a2-2nd-place")
    qp = raw.decode("utf-8")
    check("ربع نهائي لم تُعرف أطرافه ولا ساعته", "متصدّر المجموعة الأولى" in qp and "والساعة تُعلن لاحقًا" in qp
          and "مباريات ربع النهائي الأخرى" in qp and "11-spain-portugal" in qp and "12-denmark-norway" not in qp)
    code, raw, age = T.render_match("7-croatia-czechia")
    check("ملخّصٌ متعذّر لا يُسقط الصفحة", code == 200 and "كرواتيا" in raw.decode("utf-8"))
    sm = [p for p, _, _ in T.sitemap()]
    check("خريطة الموقع: الصفحة وصفحة المسابقة ومبارياتها", sm[0] == "/nations-league" and len(sm) == 2 + len(ms)
          and T.PREDICT in sm and "/nations-league/1-france-belgium" in sm)

    print("\nالأداة المدمجة في متجر سلة")
    code, raw, age = T.render_widget()
    wp = raw.decode("utf-8")
    heads = re.findall(r"<h2>([^<]+)</h2>", wp)
    check("مباريات اليوم والقادمة، بلا «آخر النتائج»", heads == ["مباريات اليوم", "المباريات القادمة"]
          and "آخر النتائج" not in wp, str(heads))
    check("لا نتيجة منتهية من أمسٍ فيها", 'href="/nations-league/1-france-belgium"' not in wp
          and 'href="/nations-league/4-portugal-wales"' in wp)
    check("روابطها تُفتح في نافذة جديدة", wp.count('target="_blank"') == wp.count("<a ") and wp.count("<a ") > 1)
    check("لا تُفهرس، ورابطها القانوني الصفحة", '<meta name="robots" content="noindex">' in wp
          and f'rel="canonical" href="{T.guide_pages.SITE}/nations-league"' in wp)
    check("تبلّغ الحاضنة بطولها", "parent.postMessage({ssouqWidget:" in wp)
    check("وضعها كوضع جهاز الزائر (كالمتجر)، ويُفرض بـ theme", "data-theme" not in wp.split("<head>")[0]
          and 'data-theme="dark"' in T.render_widget("dark")[1].decode("utf-8")
          and 'data-theme="light"' in T.render_widget("light")[1].decode("utf-8")
          and "data-theme" not in T.render_widget("<x>")[1].decode("utf-8").split("<head>")[0])
    check("بلا color-scheme فتبقى شفافة فوق المتجر (وتتبع prefers-color-scheme)",
          not re.search(r"(?<!prefers-)color-scheme", wp) and "prefers-color-scheme" in wp)
    check("بلا إعلان داخل المتجر", "cup-ad" not in wp.split("<body>")[1])
    check("والجارية تتحدّث كل دقيقة", age == T.LIVE_TTL and '<meta http-equiv="refresh" content="60">' in wp)

    print("\nتعذّر الجلب")

    def down(path):
        raise OSError("connection refused")
    L.get_json = down
    T._feed.reset()
    code, raw, age = T.render()
    page = raw.decode("utf-8")
    check("503 برسالة والإعلان باقٍ", code == 503 and "تعذّر تحميل المباريات الآن" in page and "cup-ad-side" in page)


def unit_gulf():
    """كأس الخليج: نسخةٌ من الوحدة نفسها بإعدادها، مستقلةٌ بكاشها وصفحاتها — والقناة الناقلة."""
    print("\nكأس الخليج")
    G = T.instance("gulf_cup_test", **T.GULF)
    check("نسخةٌ مستقلة: مسارها ومسابقتها وكاشها", G.PATH == "/gulf-cup" and G.PREDICT == "/gulf-cup/predict"
          and T.PATH == "/nations-league" and T.PREDICT == "/nations-league/predict" and G._feed is not T._feed
          and G.CUP["code"] == "global.gulf_cup" and T.CUP["code"] == "uefa.nations")
    L.get_json = fake_espn
    G._feed.reset()
    data = G._feed.get()[0]
    by = {m["id"]: m for m in data["matches"]}
    check("مبارياتها كلها: المجموعتان ونصف النهائي", set(by) == {"101", "102", "103", "104", "105", "106"}, str(sorted(by)))
    check("وتحمل بطولتها", by["103"]["path"] == "/gulf-cup" and by["103"]["cup"] == "كأس الخليج العربي")
    check("المجموعة من الترتيب لا من تسمية ESPN المعكوسة", by["103"]["group"] == "Group A"
          and by["103"]["stage"] == "المجموعة الأولى" and by["105"]["stage"] == "المجموعة الثانية")
    check("أطراف نصف النهائي قبل أن تُعرف", (by["106"]["home"]["name"], by["106"]["away"]["name"], by["106"]["stage"])
          == ("متصدّر المجموعة الأولى", "وصيف المجموعة الثانية", "نصف النهائي"))
    check("الأسماء بالعربية", (by["103"]["home"]["name"], by["103"]["away"]["name"]) == ("السعودية", "العراق"))
    G.channels = lambda: {"103": "AL KASS One"}
    code, raw, age = G.render()
    page = raw.decode("utf-8")
    check("صفحة كأس الخليج", code == 200 and "<title>نتائج كأس الخليج العربي 2026 — خليجي 27 ومباريات اليوم | سمارت سوق</title>" in page
          and f'rel="canonical" href="{T.guide_pages.SITE}/gulf-cup"' in page and "المجموعتين" in page)
    g = section(page, "groups")
    check("جدولا المجموعتين، والأول والثاني إلى نصف النهائي", g.count('<table class="standings">') == 2
          and "التأهل إلى نصف النهائي" in g and "ربع النهائي" not in g)
    check("القناة الناقلة في صف المباراة", 'class="tv"' in page and ">AL KASS One</span>" in page
          and page.count('class="tv"') == 1)
    check("وروابط المباريات تحت مسارها", 'href="/gulf-cup/103-saudi-arabia-iraq"' in page and "/nations-league/" not in page.split("<main")[1].split("cupmain")[0])
    code, raw, age = G.render_match("103-saudi-arabia-iraq")
    mp = raw.decode("utf-8")
    check("صفحة المباراة: القناة الناقلة وبطولتها ومجموعتها الصحيحة", code == 200 and "القناة الناقلة: <b dir=\"ltr\">AL KASS One</b>" in mp
          and "كأس الخليج العربي · خليجي 27 · المجموعة الأولى" in mp and "ترتيب المجموعة الأولى" in mp)
    code, raw, _ = G.render_match("101-saudi-arabia-kuwait")
    check("ولا سطر قناة لمباراةٍ بلا قناة", code == 200 and "القناة الناقلة" not in raw.decode("utf-8"))
    check("وليست من دوري الأمم", T.render_match("103-saudi-arabia-iraq") is None)
    code, raw, _ = G.render_widget()
    check("ودجت كأس الخليج", code == 200 and "كأس الخليج العربي" in raw.decode("utf-8"))
    sm = [u for u, *_ in G.sitemap()]
    check("في خريطة الموقع بمبارياتها", "/gulf-cup" in sm and "/gulf-cup/predict" in sm and "/gulf-cup/103-saudi-arabia-iraq" in sm)
    G.channels = lambda: {}


def req(base, path, host=None):
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
    mport, port, dport = 9601, 9602, 9603
    base, dead = f"http://127.0.0.1:{port}", f"http://127.0.0.1:{dport}"
    procs = [subprocess.Popen([sys.executable, os.path.join(HERE, "mock_espn.py"), str(mport)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
    for p, api in ((port, f"http://127.0.0.1:{mport}"), (dport, "http://127.0.0.1:9")):
        env = dict(os.environ, XM_DATA=tempfile.mkdtemp(prefix="cup_"), XM_BIND="127.0.0.1",
                   XM_PORT=str(p), XM_ADMIN_PASSWORD="envpass123", LEAGUE_API=api)
        procs.append(subprocess.Popen([sys.executable, os.path.join(ROOT, "xm_lines.py"), "web"],
                                      env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    try:
        _up(f"http://127.0.0.1:{mport}/v2/sports/soccer/ksa.1/standings")
        _up(base + "/robots.txt"); _up(dead + "/robots.txt")
        print("\nعلى الخادم")
        c, h, b = req(base, "/nations-league", "guide.ssouq.com")
        check("/nations-league على الموقع العام", c == 200 and "text/html" in h.get("Content-Type", "")
              and "المجموعة الرابعة" in b)
        check("كاش دقيقة والمباراة جارية", h.get("Cache-Control") == "public, max-age=60", h.get("Cache-Control"))
        c, _, b = req(base, "/sitemap.xml")
        check("في خريطة الموقع بمبارياتها", c == 200 and "/nations-league</loc>" in b
              and "/nations-league/1-france-belgium</loc>" in b)
        c, h, _ = req(base, "/nations-league/1")
        check("رابط المباراة المختصر ← 301 إلى رابطها", c == 301 and h.get("Location") == "/nations-league/1-france-belgium")
        c, h, b = req(base, "/nations-league/1-france-belgium")
        check("صفحة المباراة 200 بأهدافها", c == 200 and "Kylian Mbappé" in b and h.get("Cache-Control") == "public, max-age=300")
        c, _, _ = req(base, "/nations-league/999-nobody")
        check("مباراة غير موجودة = 404", c == 404)
        c, h, b = req(base, "/nations-league/widget")
        check("/nations-league/widget للمتجر", c == 200 and "data-theme" not in b.split("<head>")[0] and "noindex" in b)
        c, _, b = req(base, "/")
        check("الرئيسية تربطها", 'href="/nations-league"' in b)
        c, _, b = req(base, "/nations-league", "admin.ssouq.com")
        check("نطاق الأداة لا يقدّمها", c != 200 or "دوري الأمم" not in b, str(c))
        c, h, b = req(dead, "/nations-league")
        check("ESPN لا تردّ: 503 مع Retry-After", c == 503 and h.get("Retry-After") == str(L.RETRY))
        c, h, b = req(base, "/gulf-cup", "guide.ssouq.com")
        check("/gulf-cup على الموقع العام", c == 200 and "كأس الخليج العربي" in b and "المجموعة الثانية" in b)
        c, h, b = req(base, "/gulf-cup/103-saudi-arabia-iraq")
        check("صفحة مباراة من كأس الخليج", c == 200 and "السعودية" in b and "ترتيب المجموعة الأولى" in b)
        c, h, _ = req(base, "/gulf-cup/103")
        check("ورابطها المختصر ← 301", c == 301 and h.get("Location") == "/gulf-cup/103-saudi-arabia-iraq")
        c, _, b = req(base, "/gulf-cup/predict")
        check("صفحة مسابقة كأس الخليج", c == 200 and "مسابقة توقّع النتيجة" in b and 'href="/gulf-cup">كأس الخليج العربي' in b)
        c, _, _ = req(base, "/gulf-cup/1-france-belgium")
        check("ومباراةٌ من دوري الأمم ليست تحتها", c == 404)
        c, _, b = req(base, "/sitemap.xml")
        check("كأس الخليج في خريطة الموقع", "/gulf-cup</loc>" in b and "/gulf-cup/103-saudi-arabia-iraq</loc>" in b)
        c, _, b = req(base, "/")
        check("والرئيسية تربطها", 'href="/gulf-cup"' in b)
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            p.wait(timeout=10)


def main():
    unit()
    unit_gulf()
    live()
    print(f"\n{_p} نجح · {_f} فشل")
    return 1 if _f else 0


if __name__ == "__main__":
    sys.exit(main())

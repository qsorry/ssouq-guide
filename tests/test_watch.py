#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""صفحات المشاهدة (watch.py): /watch/<المسابقة> ومدخلها /watch، بلا إنترنت.

  - مباريات الدوري من scoreboard بالشهر: الماضي والحالي والقادم، والمكرَّر مرة، والأسماء بالعربية،
    والدور (مرحلة الدوري، منطقة الغرب) والملعب.
  - الأقسام: الجارية في «اليوم» دائمًا، و«القادمة» أسبوعٌ بلا ما فات موعده، و«النتائج» الجولة الأخيرة.
  - الصفحة: العنوان والوصف للبحث، والناقل تحت ما لم ينتهِ، والترتيب، والأجهزة، والأسئلة وFAQPage
    وSportsEvent وBreadcrumbList، وإعلانٌ بحملة الصفحة؛ وتعذّر ESPN = 503 والمحتوى الثابت باقٍ.
  - البطولتان من كاش صفحتيهما، وصفوفهما روابط إلى صفحات مبارياتهما.
  - المدخل، وخريطة الموقع، والروابط إليها من الرئيسية والترتيب والبطولة.
  - على خادم حيّ مع ESPN وهمية (بـ gzip كما تردّ ESPN)، ومع ESPN لا تردّ.

تشغيل:  python tests/test_watch.py
"""
import datetime
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
import tournament as T  # noqa: E402
import watch as W  # noqa: E402

_p = _f = 0


def check(l, c, x=""):
    global _p, _f
    print((f"  \033[32mPASS\033[0m  {l}" if c else f"  \033[31mFAIL\033[0m  {l}") + (f"  ({x})" if x else ""))
    _p += 1 if c else 0
    _f += 0 if c else 1


def fake_espn(path):
    """league.get_json من الوهمية مباشرة، بلا خادم — وما لا تغطيه يرفع كما ترفع ESPN (400)."""
    m = re.fullmatch(r"/site/v2/sports/soccer/([\w.]+)/scoreboard\?dates=(\d+)(?:&limit=\d+)?", path)
    got = None
    if m:
        got = mock_espn.scoreboard(m.group(1), m.group(2))
    m2 = re.fullmatch(r"/site/v2/sports/soccer/([\w.]+)/summary\?event=(\d+)", path)
    if m2:
        got = mock_espn.summary(m2.group(1), m2.group(2))
    m3 = re.fullmatch(r"/v2/sports/soccer/([\w.]+)/standings", path)
    if m3:
        got = mock_espn.payload(m3.group(1))
    if got is None:
        raise OSError("HTTP Error 400: Bad Request")
    return got


def down(path):
    raise OSError("connection refused")


def reset(get, cups):
    """كاشٌ فارغ كأن الخادم أقلع للتوّ، وESPN من الدالة المعطاة."""
    L.get_json = get
    for f in list(L._state.values()) + list(W._feeds.values()) + [t._feed for t in cups]:
        f.reset()


def ld(page):
    return [json.loads(b) for b in re.findall(r'application/ld\+json">(.*?)</script>', page, re.S)]


def section(page, key):
    m = re.search(rf'<section class="card[^"]*" id="{key}".*?</section>', page, re.S)
    return m.group(0) if m else ""


def text(html):
    return re.sub(r"<[^>]+>", "", html)


def unit():
    cups = (T, T.instance("gulf_cup_watch_test", **T.GULF))
    now = time.time()

    print("المسابقات")
    check("كل دوري له صفحة، بترتيب الدوريات", [k for k in W.COMPS if not W.COMPS[k].get("cup")] == list(L.LEAGUES))
    check("البطولتان بمسار صفحتيهما", sorted(k for k in W.COMPS if W.COMPS[k].get("cup"))
          == sorted(t.PATH.strip("/") for t in cups))
    check("رابط المشاهدة في league هو مسار watch", L.WATCH == W.PATH + "/")
    check("لكل مسابقة ناقلٌ واسمٌ مختصر", all(c["tv"] and c["badge"] and c["short"] for c in W.COMPS.values()))
    check("روابط الأجهزة صفحاتٌ موجودة", all(p in guide_pages.PAGES for p, _ in W.DEVICES))
    check("بلا البطولتين لا صفحة لهما", W.available(()) == list(L.LEAGUES) and W.render("nations-league") is None)
    check("مسابقة غير معروفة = None", W.render("nope", cups) is None)
    check("حرف الجرّ على الاسم", [W._li(n) for n in ("دوري روشن", "الدوري الإنجليزي", "كأس الخليج")]
          == ["لدوري روشن", "للدوري الإنجليزي", "لكأس الخليج"])

    print("\nالأشهر والمباريات")
    ts = lambda y, mo, d: datetime.datetime(y, mo, d, 12, tzinfo=L.RIYADH).timestamp()  # noqa: E731
    check("الماضي والحالي والقادم", W.months(ts(2026, 9, 28)) == ["202608", "202609", "202610"])
    check("وعلى حدّ السنة", W.months(ts(2026, 12, 3)) == ["202611", "202612", "202701"]
          and W.months(ts(2027, 1, 30)) == ["202612", "202701", "202702"])
    ev = mock_espn.league_events("ksa.1")
    ms = W.fixtures(ev + ev[:3])
    by = {m["id"]: m for m in ms}
    check("المكرَّر على حدّ شهرين مرة", len(ms) == len(ev) == 10)
    check("مرتّبة بالموعد", [m["ts"] for m in ms] == sorted(m["ts"] for m in ms))
    check("الأسماء بالعربية", (by["3001"]["home"]["name"], by["3001"]["away"]["name"]) == ("الهلال", "النصر"))
    check("الحال والدقيقة", by["3001"]["state"] == "in" and by["3001"]["clock"] == "30'" and by["3001"]["home"]["score"] == 1)
    check("الساعة غير المعتمدة", by["3007"]["time_ok"] is False and by["3006"]["time_ok"] is True)
    check("الدوري المحلي بلا دور، والملعب من ESPN", by["3006"]["stage"] == ""
          and (by["3006"]["venue"], by["3006"]["city"]) == ("Kingdom Arena", "Riyadh"))
    ucl = W.fixtures(mock_espn.league_events("uefa.champions"))
    afc = W.fixtures(mock_espn.league_events("afc.champions"))
    check("أبطال أوروبا: مرحلة الدوري", {m["stage"] for m in ucl} == {"مرحلة الدوري"})
    check("أبطال آسيا: المنطقة", {m["stage"] for m in afc} == {"منطقة الغرب", "منطقة الشرق"})
    check("حدثٌ بلا طرفين أو موعد يُتخطّى", W.fixtures([{"id": "1", "date": "2026-10-01T12:00Z",
                                                          "competitions": [{"competitors": []}]}, {"id": "2"}]) == [])

    print("\nالأقسام")
    todays, later, done = W.split(ms, now)
    ids = lambda xs: {m["id"] for m in xs}  # noqa: E731
    check("الجارية في اليوم", "3001" in ids(todays))
    check("القادمة: أسبوعٌ من أولها، والمؤجلة فيها", ids(later) == {"3006", "3007", "3008"}, str(ids(later)))
    check("ما فات موعده ولم يُلعب لا يُعرض", "3010" not in ids(todays + later + done))
    check("النتائج: الجولة الأخيرة لا الأقدم", {"3003", "3004"} <= ids(done) and "3005" not in ids(done), str(ids(done)))
    check("منتهيةٌ اليوم في اليوم أو في النتائج", "3002" in ids(todays + done))
    far = [dict(by["3006"], id=str(i), ts=now + 2 * 86400 + i * 3600) for i in range(30)]
    check("حدّ كل قسم", len(W.split(far, now)[1]) == W.MAX_ROWS)

    print("\nصفحة الدوري")
    reset(fake_espn, cups)
    code, raw, age = W.render("saudi-pro-league", cups)
    page = raw.decode("utf-8")
    check("200 ومدة كاش دقيقة والمباراة جارية", code == 200 and age == T.LIVE_TTL and 'http-equiv="refresh"' in page)
    check("العنوان للبحث بالموسم",
          "<title>مشاهدة دوري روشن السعودي 2026-27 بث مباشر: مباريات اليوم والقنوات الناقلة | سمارت سوق</title>" in page)
    desc = re.search(r'name="description" content="(.*?)"', page).group(1)
    check("الوصف: الناقل والجارية بنتيجتها", "(ثمانية)" in desc and "مباشر الآن: الهلال 1-0 النصر." in desc, desc)
    check("canonical", f'rel="canonical" href="{guide_pages.SITE}/watch/saudi-pro-league"' in page)
    check("h1 والاسم الآخر في التعريف", "<h1>مشاهدة دوري روشن السعودي" in page
          and "دوري روشن السعودي (الدوري السعودي للمحترفين)" in page)
    heads = [text(h) for h in re.findall(r"<h2[^>]*>(.*?)</h2>", page)]
    check("عناوين الأقسام بكلمات البحث", {"مباريات دوري روشن اليوم", "مواعيد مباريات دوري روشن القادمة",
                                           "آخر نتائج دوري روشن", "القنوات الناقلة لدوري روشن", "ترتيب دوري روشن",
                                           "أسئلة شائعة عن مشاهدة دوري روشن"} <= set(heads), str(heads))
    up, res = section(page, "upcoming"), section(page, "results")
    check("الناقل تحت القادمة", up.count('class="tv"') == 2 and "ثمانية" in up, str(up.count('class="tv"')))
    check("لا ناقل تحت المؤجلة ولا تحت النتائج", "مؤجلة" in up and 'class="tv"' not in res)
    check("يُعلن لاحقًا لساعةٍ لم تُعتمد", "يُعلن لاحقًا" in up)
    check("النتائج الأحدث أولًا", 0 < res.index("الخلود") < res.index("الاتحاد"))   # قبل يومين، ثم قبل ثلاثة
    check("صفوف الدوري بلا روابط (لا صفحات لمبارياته)", '<a class="match' not in page and '<div class="match' in page)
    st = section(page, "standings")
    check("الترتيب ستة صفوف ورابط الجدول الكامل", st.count("<tr") == 7 and 'href="/standings/saudi-pro-league"' in st)
    tabs = re.search(r'<nav class="ltabs" aria-label="المسابقات">(.*?)</nav>', page).group(1)
    check("روابط المسابقات كلها، والحالية معلَّمة", all(f'href="/watch/{k}"' in tabs for k in W.COMPS)
          and 'href="/watch/saudi-pro-league" aria-current=page' in tabs)
    check("روابط تشغيل الاشتراك على كل جهاز", all(f'href="{p}"' in section(page, "devices") for p, _ in W.DEVICES))
    check("الإعلان بحملة الصفحة", "utm_campaign=watch-saudi-pro-league" in page and "utm_campaign=nations-league" not in page)
    blocks = ld(page)
    crumbs = next(b for b in blocks if b["@type"] == "BreadcrumbList")
    check("BreadcrumbList بثلاث درجات", [i["item"] for i in crumbs["itemListElement"]]
          == [guide_pages.SITE + "/", guide_pages.SITE + "/watch", guide_pages.SITE + "/watch/saudi-pro-league"])
    faq = next(b for b in blocks if b["@type"] == "FAQPage")
    qs = [q["name"] for q in faq["mainEntity"]]
    check("FAQPage يطابق الأسئلة الظاهرة", qs == [text(h) for h in re.findall(r"<h3>(.*?)</h3>", section(page, "faq"))])
    ans = {q["name"]: q["acceptedAnswer"]["text"] for q in faq["mainEntity"]}
    check("جواب القنوات الناقلة", ans["ما القنوات الناقلة لدوري روشن؟"] == W.COMPS["saudi-pro-league"]["tv"])
    check("جواب المباراة القادمة بموعدها", ans.get("متى المباراة القادمة في دوري روشن؟", "").startswith("مباراة الحزم والرياض ")
          and "بتوقيت السعودية" in ans["متى المباراة القادمة في دوري روشن؟"], ans.get("متى المباراة القادمة في دوري روشن؟"))
    check("جواب المتصدّر بعدد صحيح", ans.get("من يتصدّر دوري روشن الآن؟") == "يتصدّر الهلال برصيد 54 نقطة بعد 6 مباريات.")
    check("جواب عدد الفرق من الترتيب", ans.get("كم عدد فرق دوري روشن؟")
          == "يتنافس 18 ناديًا في دوري روشن السعودي موسم 2026-27، يلعب كلٌّ منها 34 مباراة ذهابًا وإيابًا.",
          ans.get("كم عدد فرق دوري روشن؟"))
    events = next(b for b in blocks if b["@type"] == "ItemList")["itemListElement"]
    names = [e["item"]["name"] for e in events]
    check("SportsEvent للجارية والقادمة لا المنتهية", "الهلال × النصر" in names and "الحزم × الرياض" in names
          and not any(n.startswith("الاتحاد × الأهلي") for n in names), str(names))
    by_name = {e["item"]["name"]: e["item"] for e in events}
    check("SportsEvent: الملعب، والمؤجلة مؤجلة", by_name["الحزم × الرياض"].get("location", {}).get("name") == "Kingdom Arena"
          and any(e["eventStatus"].endswith("EventPostponed") for e in by_name.values()))
    check("SportsEvent: البطولة الأم بموسمها", by_name["الهلال × النصر"]["superEvent"]["name"] == "دوري روشن السعودي 2026-27")
    check("الاسم الإنجليزي مُهرَّب", "<b>Club</b>" not in page)
    check("آخر تحديث بتوقيت السعودية", "بتوقيت السعودية · يُحدَّث تلقائيًا · المواعيد من ESPN" in page)

    print("\nدوريات أخرى")
    page = W.render("premier-league", cups)[1].decode("utf-8")
    check("الإنجليزي: «للدوري» والناقل beIN SPORTS", "القنوات الناقلة للدوري الإنجليزي" in page
          and "(beIN SPORTS)" in page and "(البريميرليغ)" in page)
    page = W.render("champions-league", cups)[1].decode("utf-8")
    check("أبطال أوروبا: الدور تحت المباراة، وبلا سؤال عدد الفرق", "مرحلة الدوري" in page and "كم عدد فرق" not in page)
    page = W.render("afc-champions-league", cups)[1].decode("utf-8")
    check("أبطال آسيا: جدولان وبلا سؤال المتصدّر", page.count('class="lgroup"') == 2 and "من يتصدّر" not in page)
    code, raw, age = W.render("la-liga", cups)
    page = raw.decode("utf-8")
    check("بلا مباريات من ESPN = 503 برسالة", code == 503 and "تعذّر تحميل المباريات الآن" in page)
    check("والقنوات والأجهزة والأسئلة باقية، وبلا ترتيب", section(page, "tv") and section(page, "devices")
          and section(page, "faq") and not section(page, "standings") and "<title>مشاهدة الدوري الإسباني بث مباشر" in page)

    print("\nالبطولتان")
    code, raw, _ = W.render("nations-league", cups)
    page = raw.decode("utf-8")
    check("دوري الأمم 200 بالموسم والمستوى", code == 200 and "مشاهدة دوري الأمم الأوروبية 2026-27 بث مباشر" in page
          and "دوري الأمم الأوروبية (المستوى الأول)" in page)
    check("الصفوف روابط إلى صفحات المباريات", 'href="/nations-league/4-portugal-wales"' in section(page, "today"))
    check("ترتيب المجموعات ورابط الصفحة كاملة", section(page, "standings").count('class="lgroup"') == 4
          and 'href="/nations-league"' in section(page, "standings"))
    ev = next(b for b in ld(page) if b["@type"] == "ItemList")["itemListElement"]
    check("SportsEvent برابط صفحة المباراة", all(e["item"]["url"].startswith(guide_pages.SITE + "/nations-league/") for e in ev))
    check("الإعلان بحملة الصفحة", "utm_campaign=watch-nations-league" in page)
    page = W.render("gulf-cup", cups)[1].decode("utf-8")
    check("كأس الخليج: خليجي 27 وناقلوها", "كأس الخليج العربي (خليجي 27)" in page and "منصة شاشا" in page
          and 'href="/gulf-cup/' in page)

    print("\nالمدخل")
    code, raw, age = W.render_hub(cups)
    page = raw.decode("utf-8")
    check("200، ودقيقة والمباريات جارية", code == 200 and age == T.LIVE_TTL)
    cards = re.findall(r'<section class="card wcomp" aria-labelledby="c-([\w-]+)"', page)
    check("بطاقةٌ لكل مسابقة", sorted(cards) == sorted(W.available(cups)), str(cards))
    check("الجارية أولًا وما تعذّر أخيرًا", cards[:1] == ["saudi-pro-league"] and cards[-1] in ("la-liga", "serie-a", "bundesliga", "ligue-1"),
          str(cards))
    check("اسم كل مسابقة رابطٌ إلى صفحتها", all(f'<a href="/watch/{k}">مشاهدة ' in page for k in cards))
    tv = section(page, "tv")
    check("جدول القنوات الناقلة للمسابقات كلها", tv.count("<tr>") == len(cards) and "stc tv" in tv and "شاهد" in tv)
    check("الوصف بعدد مباريات اليوم", re.search(r'name="description" content="[^"]*عدد مباريات اليوم: \d+\."', page))
    check("الإعلان بحملة المدخل", "utm_campaign=watch&" in page or "utm_campaign=watch\"" in page)
    reset(down, cups)
    code, raw, _ = W.render_hub(cups)
    check("ESPN لا تردّ: المدخل 503", code == 503 and "تعذّر تحميل المباريات الآن" in raw.decode("utf-8"))
    code, raw, _ = W.render("saudi-pro-league", cups)
    check("وصفحة الدوري 503 بلا ترتيب", code == 503 and 'id="standings"' not in raw.decode("utf-8"))

    print("\nالروابط وخريطة الموقع")
    reset(fake_espn, cups)
    sm = guide_pages.sitemap(L.SITEMAP + W.SITEMAP).decode("utf-8")
    check("المدخل وكل صفحات المشاهدة في المخطط", f"<loc>{guide_pages.SITE}/watch</loc>" in sm
          and all(f"<loc>{guide_pages.SITE}/watch/{k}</loc>" in sm for k in W.COMPS))
    page = L.render("saudi-pro-league")[1].decode("utf-8")
    check("صفحة الترتيب تربط صفحة المشاهدة", 'href="/watch/saudi-pro-league">مشاهدة دوري روشن السعودي' in page)
    page = T.render()[1].decode("utf-8")
    check("صفحة البطولة تربط صفحة مشاهدتها", 'href="/watch/nations-league">مشاهدة دوري الأمم الأوروبية' in page)
    page = cups[1].render()[1].decode("utf-8")
    check("وكأس الخليج كذلك", 'href="/watch/gulf-cup">مشاهدة كأس الخليج العربي' in page)
    idx = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    fb = idx[idx.index('<div id="fallback">'):idx.index("</main>")]
    check("النسخة الثابتة للرئيسية تربط المدخل وكل المسابقات",
          'href="/watch"' in fb and all(f'href="/watch/{k}"' in fb for k in W.COMPS))
    check("القائمة تربط المدخل", 'href="/watch"' in idx[:idx.index("</nav>")])
    check("وفي الرئيسية مدخلٌ إليها", '<a class="entry watch" href="/watch">' in idx)


def req(base, path, host=None):
    """(الحالة، الترويسات، النص) بلا اتّباع تحويل."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    r = urllib.request.Request(base + path, headers={"Host": host} if host else {})
    try:
        x = urllib.request.build_opener(NoRedirect).open(r, timeout=30)
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
    mport, port, dport = 9621, 9622, 9623
    base, dead = f"http://127.0.0.1:{port}", f"http://127.0.0.1:{dport}"
    procs = [subprocess.Popen([sys.executable, os.path.join(HERE, "mock_espn.py"), str(mport)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
    for p, api in ((port, f"http://127.0.0.1:{mport}"), (dport, "http://127.0.0.1:9")):
        env = dict(os.environ, XM_DATA=tempfile.mkdtemp(prefix="watch_"), XM_BIND="127.0.0.1",
                   XM_PORT=str(p), XM_ADMIN_PASSWORD="envpass123", LEAGUE_API=api)
        procs.append(subprocess.Popen([sys.executable, os.path.join(ROOT, "xm_lines.py"), "web"],
                                      env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    try:
        _up(f"http://127.0.0.1:{mport}/v2/sports/soccer/ksa.1/standings"); _up(base + "/robots.txt"); _up(dead + "/robots.txt")
        print("\nعلى الخادم")
        r = urllib.request.Request(f"http://127.0.0.1:{mport}/site/v2/sports/soccer/ksa.1/scoreboard?dates="
                                   + W.months()[1], headers={"Accept-Encoding": "gzip"})
        with urllib.request.urlopen(r, timeout=5) as x:
            check("ESPN الوهمية تضغط gzip لمن يطلبه", x.headers.get("Content-Encoding") == "gzip")
        c, h, b = req(base, "/watch/saudi-pro-league", "guide.ssouq.com")
        check("صفحة الدوري على الموقع العام (والرد مضغوط من ESPN)", c == 200 and "text/html" in h.get("Content-Type", "")
              and "مواعيد مباريات دوري روشن القادمة" in b and "الهلال" in b)
        check("تُخزَّن دقيقة والمباراة جارية", h.get("Cache-Control") == f"public, max-age={T.LIVE_TTL}", h.get("Cache-Control"))
        c, h, b = req(base, "/watch")
        check("المدخل 200 ببطاقات المسابقات", c == 200 and b.count('class="card wcomp"') == len(W.COMPS))
        c, h, _ = req(base, "/watch/")
        check("/watch/ ← /watch (301)", c == 301 and h.get("Location") == "/watch")
        c, _, b = req(base, "/watch/nations-league")
        check("صفحة دوري الأمم", c == 200 and 'href="/nations-league/' in b)
        c, h, b = req(base, "/watch/la-liga")
        check("دوري لا تغطيه الوهمية = 503 مع Retry-After", c == 503 and h.get("Retry-After") == str(L.RETRY)
              and "القنوات الناقلة للدوري الإسباني" in b)
        c, _, _ = req(base, "/watch/nope")
        check("مسابقة غير معروفة = 404", c == 404)
        c, _, b = req(base, "/sitemap.xml")
        check("المخطط يحمل صفحات المشاهدة", c == 200 and "/watch</loc>" in b and "/watch/saudi-pro-league</loc>" in b
              and "/watch/gulf-cup</loc>" in b)
        c, _, b = req(base, "/standings/saudi-pro-league")
        check("صفحة الترتيب تربطها", c == 200 and 'href="/watch/saudi-pro-league"' in b)
        c, _, b = req(base, "/watch", "admin.ssouq.com")
        check("نطاق الأداة لا يقدّمها", c != 200 or "مشاهدة مباريات اليوم" not in b, str(c))

        print("\nESPN لا تردّ")
        c, h, b = req(dead, "/watch")
        check("المدخل 503 مع Retry-After", c == 503 and h.get("Retry-After") == str(L.RETRY))
        c, h, b = req(dead, "/watch/saudi-pro-league")
        check("صفحة الدوري 503، والقنوات والأسئلة فيها", c == 503 and "القنوات الناقلة لدوري روشن" in b and 'id="faq"' in b)
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

# -*- coding: utf-8 -*-
"""صفحات المشاهدة: صفحةٌ لكل دوري وبطولة (‏/watch/<المسابقة>) ومدخلٌ لها كلها (‏/watch).

مكتوبةٌ لمن يبحث «مشاهدة دوري روشن» و«القنوات الناقلة للدوري الإنجليزي» و«مباريات اليوم»: في كل
صفحة مباريات اليوم (والجارية بنتيجتها ودقيقتها)، ومواعيد القادمة وآخر النتائج بتوقيت السعودية،
والقنوات الناقلة الرسمية في المنطقة، والترتيب مختصرًا، وروابط تشغيل الاشتراك على كل جهاز، وأسئلة
شائعة (‏FAQPage) أجوبتها من البيانات نفسها، وإعلان الاشتراكات. والمدخل مباريات اليوم من المسابقات
كلها، وجدول القنوات الناقلة لكلٍّ منها.

من أين المباريات:
  - الدوريات الثمانية (مفاتيح league.LEAGUES) من scoreboard في ESPN بالشهر: الماضي والحالي
    والقادم، فلا تسقط جولةٌ على حدّ شهر (‏ESPN تردّ 400 على مدى أيام dates=YYYYMMDD-YYYYMMDD،
    وتقبل الشهر). كاشٌ لكل دوري (league.Feed): ربع ساعة، ودقيقة حول المباريات (tournament._ttl).
  - البطولتان (دوري الأمم وكأس الخليج) من كاش صفحتَيهما نفسه (‏t._feed)، فلا طلب زائد على ESPN،
    وصفوفهما روابط إلى صفحات مبارياتهما بقناتها وشارة المسابقة.

القنوات الناقلة في COMPS مكتوبةٌ يدويًا — ESPN لا تعطي ناقلي المنطقة — ومُتحقَّقٌ منها لموسم 2026-27،
فتُراجع مع بداية كل موسم. والناقل يُكتب تحت المباريات القادمة والجارية، لا تحت نتيجةٍ انتهت.
"""
import concurrent.futures
import datetime
import json
import re
import time

import guide_pages
import league
import tournament
from league import RIYADH, _esc

PATH = "/watch"
LIMIT = 200                       # مباريات الشهر في طلب واحد (الافتراضي عند ESPN مئة)
MONTHS_AROUND = (-1, 0, 1)        # الشهر الماضي والحالي والقادم
WINDOW = 7 * 24 * 3600            # «القادمة»: أسبوعٌ من أول مباراة قادمة
LAST_ROUND = 4 * 24 * 3600        # «النتائج»: الجولة الأخيرة — أربعة أيام قبل آخر نتيجة (الجمعة إلى الاثنين)
MAX_ROWS = 20                     # حدّ كل قسم (جولة أبطال أوروبا 18 مباراة)
HUB_NEXT = 2                      # المدخل: أقرب مباراتين لمسابقةٍ ليس فيها مباريات اليوم
OFF = ("STATUS_POSTPONED", "STATUS_CANCELED")

BEIN = ("شبكة beIN SPORTS الناقل الحصري في الشرق الأوسط وشمال أفريقيا، وعلى الإنترنت "
        "تطبيقا TOD وbeIN CONNECT.")

# المسابقات بترتيب عرضها. المفتاح آخر الرابط: مفاتيح league.LEAGUES للدوريات، ومسار صفحة البطولة
# بلا الشرطة للبطولتين (cup، واسمهما وموسمهما من CUP في وحدتيهما).
#   short: الاسم كما يُبحث به («مشاهدة دوري روشن»)، alt: اسمٌ آخر يُذكر معه في التعريف
#   badge: الناقل مختصرًا (تحت المباريات وفي الوصف)، tv: جملة القنوات الناقلة كاملة
#   rounds: دوري ذهاب وإياب — عدد مباريات كل نادٍ من عدد الأندية
COMPS = {
    "saudi-pro-league": dict(
        short="دوري روشن", alt="الدوري السعودي للمحترفين", badge="ثمانية", rounds=True,
        tv="شركة ثمانية الناقل الحصري في الشرق الأوسط وشمال أفريقيا من موسم 2025-26 حتى 2030-31، "
           "على قنواتها الفضائية المفتوحة ومنصّتها الرقمية باشتراك."),
    "premier-league": dict(short="الدوري الإنجليزي", alt="البريميرليغ", badge="beIN SPORTS", rounds=True, tv=BEIN),
    "la-liga": dict(short="الدوري الإسباني", alt="الليغا", badge="beIN SPORTS", rounds=True, tv=BEIN),
    "serie-a": dict(short="الدوري الإيطالي", alt="الكالتشيو", badge="stc tv", rounds=True,
                    tv="في السعودية منصة stc tv، وفي بقية المنطقة منصة STARZPLAY."),
    "bundesliga": dict(short="الدوري الألماني", alt="البوندسليغا", badge="شاهد", rounds=True,
                       tv="مجموعة MBC: كل المباريات على منصة شاهد، وثلاث مباريات كل أسبوع على قناة MBC Action المفتوحة."),
    "ligue-1": dict(short="الدوري الفرنسي", alt="", badge="beIN SPORTS", rounds=True, tv=BEIN),
    "champions-league": dict(short="دوري أبطال أوروبا", alt="التشامبيونزليغ", badge="beIN SPORTS", tv=BEIN),
    "afc-champions-league": dict(short="دوري أبطال آسيا", alt="", badge="beIN SPORTS",
                                 tv="شبكة beIN SPORTS صاحبة الحقوق الحصرية، وعلى الإنترنت تطبيق TOD."),
    "nations-league": dict(cup=True, short="دوري الأمم", alt="", badge="beIN SPORTS", tv=BEIN),
    "gulf-cup": dict(cup=True, short="كأس الخليج", alt="", badge="الكأس وأبوظبي الرياضية وشاشا",
                     tv="اشترت حقوق نقلها خمس جهات: قنوات الكأس (قطر)، وأبوظبي الرياضية (الإمارات)، "
                        "والكويت الرياضية، وعُمان الرياضية، ومنصة شاشا."),
}
SITEMAP = [(PATH, "daily", "0.8")] + [(f"{PATH}/{k}", "daily", "0.8") for k in COMPS]

# صفحات تشغيل الاشتراك على كل جهاز (guide_pages.PAGES) بأسماء أجهزتها
DEVICES = [("/samsung-lg", "شاشات سامسونج و LG"), ("/vidaa", "شاشات هايسنس و VIDAA"),
           ("/android-tv", "شاشات وبوكسات أندرويد"), ("/iphone", "الآيفون والآيباد"), ("/android", "جوالات أندرويد"),
           ("/windows", "كمبيوتر ويندوز"), ("/mac", "أجهزة ماك"), ("/carplay", "شاشة السيارة CarPlay")]

# أدوار البطولات القارية عند ESPN (‏season.slug) ← أسماؤها، فوق أسماء أدوار tournament
STAGES = dict(tournament.STAGES, **{"league-phase": "مرحلة الدوري", "league-stage": "مرحلة الدوري",
                                    "knockout-round-playoffs": "ملحق دور الـ16", "round-of-16": "دور الـ16"})
CLUBS = ("نادٍ واحد", "ناديين", "أندية", "ناديًا", "نادٍ")


# ---------- القراءة ----------
def fixtures(events):
    """أحداث scoreboard لدوري ← مبارياته مرتّبةً بالموعد، بشكل مباريات tournament نفسه (فتُرسم
    بدوالّه) ومعها ملعبها. الحدث المكرّر (على حدّ شهرين) يدخل مرة."""
    out, seen = [], set()
    for e in events:
        eid = str(e.get("id") or "")
        c = (e.get("competitions") or [{}])[0]
        comp = c.get("competitors") or []
        if not eid or eid in seen or len(comp) != 2 or not e.get("date"):
            continue
        seen.add(eid)
        sides = {x.get("homeAway"): x for x in comp}
        st = c.get("status") or e.get("status") or {}
        kind = st.get("type") or {}
        group = (c.get("group") or {}).get("name") or ""
        venue = c.get("venue") or {}
        h, a = tournament._side(sides.get("home", comp[0])), tournament._side(sides.get("away", comp[1]))
        out.append({
            "id": eid, "slug": "-".join(x for x in (eid, tournament._slug(h["en"], a["en"])) if x),
            "ts": tournament._ts(e["date"]), "time_ok": c.get("timeValid") is not False,
            "home": h, "away": a,
            "state": kind.get("state") or "pre", "status": kind.get("name") or "",
            "clock": str(st.get("displayClock") or ""),
            "stage": league._group(group, 0)[1] if group else STAGES.get((e.get("season") or {}).get("slug") or "", ""),
            "venue": venue.get("fullName") or (e.get("venue") or {}).get("displayName") or "",
            "city": (venue.get("address") or {}).get("city") or "",
        })
    out.sort(key=lambda m: (m["ts"], m["id"]))
    return out


def months(now=None):
    """الأشهر التي تُجلب مبارياتها بتوقيت السعودية: ["202609", "202610", "202611"]."""
    t = datetime.datetime.fromtimestamp(time.time() if now is None else now, RIYADH)
    out = []
    for d in MONTHS_AROUND:
        y, m = divmod(t.year * 12 + t.month - 1 + d, 12)
        out.append(f"{y}{m + 1:02d}")
    return out


def _fetch(code, ym):
    return league.get_json(f"/site/v2/sports/soccer/{code}/scoreboard?dates={ym}&limit={LIMIT}")


def load(code):
    events = []
    for ym in months():
        events += _fetch(code, ym).get("events") or []
    return {"matches": fixtures(events)}


# `_fetch` يُقرأ وقت الجلب لا وقت التعريف، فتستبدله الاختبارات.
_feeds = {k: league.Feed(lambda code=v["code"]: load(code), tournament._ttl) for k, v in league.LEAGUES.items()}


def _cup(cups, slug):
    return next((t for t in cups if t.PATH.strip("/") == slug), None)


def available(cups):
    """مفاتيح المسابقات التي لها صفحة: الدوريات كلها، والبطولة إن كانت وحدتها بين cups."""
    return [k for k, c in COMPS.items() if not c.get("cup") or _cup(cups, k)]


def _name(slug, cups):
    t = _cup(cups, slug)
    return t.CUP["name"] if t else league.LEAGUES[slug]["name"]


def _get(slug, cups):
    """(البيانات أو None إن تعذّرت، وقت جلبها) من كاش الدوري أو من كاش صفحة البطولة:
    {"matches": […]}، وللبطولة معها "groups" (ترتيب مجموعاتها)."""
    t = _cup(cups, slug)
    data, at, _ = (t._feed if t else _feeds[slug]).get()
    return data, at


def _all(fns):
    """نداءات الكاش معًا: أول زيارة بعد الإقلاع تنتظر أبطأها لا مجموعها."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(fns)) as ex:
        return [f.result() for f in [ex.submit(fn) for fn in fns]]


def split(ms, now=None):
    """(اليوم، القادمة، النتائج): اليوم بتوقيت السعودية والجارية دائمًا وإن بدأت أمس؛ والقادمة أسبوعٌ من
    أول مباراةٍ لم تُلعب (ما فات موعده ولم يُلعب — مؤجلٌ بلا موعد — لا يُعرض)؛ والنتائج الجولة الأخيرة."""
    now = time.time() if now is None else now
    today = tournament._day(now)
    todays = [m for m in ms if tournament._day(m["ts"]) == today or m["state"] == "in"]
    later = [m for m in ms if m["state"] == "pre" and m not in todays and m["ts"] > now]
    done = [m for m in ms if m["state"] == "post" and m not in todays]
    if later:
        later = [m for m in later if m["ts"] < later[0]["ts"] + WINDOW][:MAX_ROWS]
    if done:
        done = [m for m in done if m["ts"] > done[-1]["ts"] - LAST_ROUND][-MAX_ROWS:]
    return todays, later, done


# ---------- الرسم ----------
def _li(name):
    """حرف الجرّ على الاسم: الدوري ← للدوري، دوري ← لدوري."""
    return "لل" + name[2:] if name.startswith("ال") else "ل" + name


def match_url(k, m):
    return f"{PATH}/{k}/{m['slug']}"


def _row(m, badge="", k=None, new_tab=False):
    """صف مباراةٍ من دوري: رابطٌ إلى صفحتها إن عُرف الدوري `k`، والناقل تحت ما لم ينتهِ."""
    mid, note, cls = tournament._status(m)
    stage = f'<small class="stage">{_esc(m["stage"])}</small>' if m["stage"] else ""
    tv = (f'<small class="tv">{tournament.TV_ICON}<span dir="auto">{_esc(badge)}</span></small>'
          if badge and m["state"] != "post" and m["status"] not in OFF else "")
    inner = (f'{tournament._team(m["home"])}<span class="mid">{mid}{note}{stage}{tv}</span>'
             f'{tournament._team(m["away"], True)}')
    if not k:
        return f'<li><div class="match{cls}">{inner}</div></li>'
    target = ' target="_blank" rel="noopener"' if new_tab else ""
    return f'<li><a class="match{cls}" href="{match_url(k, m)}"{target}>{inner}</a></li>'


def _days(ms, row, newest_first=False):
    days = {}
    for m in ms:
        days.setdefault(tournament._day(m["ts"]), []).append(m)
    return "".join(f'<h3 class="mday">{tournament._day_label(d)}</h3><ul class="matches">'
                   + "".join(row(m) for m in days[d]) + "</ul>" for d in sorted(days, reverse=newest_first))


def _painter(slug, cups, ms):
    """دالة رسم الأيام لمسابقة: صفوف البطولة روابطُ إلى صفحات مبارياتها بقناتها وشارة مسابقتها."""
    t = _cup(cups, slug)
    if t:
        pz = t._contests(ms)
        return lambda xs, newest=False: t._by_day(xs, newest_first=newest, pz=pz)
    badge = COMPS[slug]["badge"]
    return lambda xs, newest=False: _days(xs, lambda m: _row(m, badge, slug), newest)


def _when(m):
    day = tournament._day_label(tournament._day(m["ts"]))
    return f"{day} الساعة {tournament._clock(m['ts'])} بتوقيت السعودية" if m["time_ok"] else f"{day}، والساعة تُعلن لاحقًا"


def _next(ms, now):
    return next((m for m in ms if m["state"] == "pre" and m["ts"] > now and m["status"] not in OFF), None)


def _lead(ms, now):
    """جملة الوصف: الجارية بنتيجتها، وإلا المباراة القادمة بموعدها."""
    live = [m for m in ms if m["state"] == "in"]
    if live:
        h, a = live[0]["home"], live[0]["away"]
        return f" مباشر الآن: {h['name']} {h['score']}-{a['score']} {a['name']}."
    m = _next(ms, now)
    if m:
        when = tournament.when_label(m["ts"]) if m["time_ok"] else tournament._day_label(tournament._day(m["ts"]))
        return f" المباراة القادمة: {m['home']['name']} و{m['away']['name']}، {when}."
    return ""


def faq(slug, name, season, ms, table, now=None):
    """الأسئلة الشائعة وأجوبتها (نصًّا) من البيانات نفسها: تُكتب في الصفحة وفي FAQPage معًا."""
    c, now = COMPS[slug], time.time() if now is None else now
    short = c["short"]
    qa = [(f"ما القنوات الناقلة {_li(short)}؟", c["tv"])]
    m = _next(ms, now)
    if m:
        qa.append((f"متى المباراة القادمة في {short}؟", f"مباراة {m['home']['name']} و{m['away']['name']} {_when(m)}."))
    groups = (table or {}).get("groups") or []
    if len(groups) == 1 and groups[0]["rows"] and groups[0]["rows"][0]["p"]:
        top = groups[0]["rows"][0]
        qa.append((f"من يتصدّر {short} الآن؟", f"يتصدّر {top['name']} برصيد {league.count(top['pts'], league.POINTS)} "
                                               f"بعد {league.count(top['p'], league.MATCHES)}."))
    if c.get("rounds") and len(groups) == 1 and len(groups[0]["rows"]) > 1:
        n = len(groups[0]["rows"])
        qa.append((f"كم عدد فرق {short}؟", f"يتنافس {league.count(n, CLUBS)} في {name}{' موسم ' + season if season else ''}، "
                                           f"يلعب كلٌّ منها {league.count(2 * (n - 1), league.MATCHES)} ذهابًا وإيابًا."))
    qa.append(("بأي توقيت مواعيد المباريات في هذه الصفحة؟",
               "بتوقيت السعودية (مكة المكرمة)، والصفحة تتحدّث تلقائيًا: كل دقيقة والمباريات جارية، وكل ربع ساعة في غيرها."))
    return qa


def _events(ms, sup, url_of):
    """المباريات القادمة وجاريتها SportsEvent في ItemList، بالشكل الذي تكتبه صفحة المباراة."""
    items = []
    for i, m in enumerate(ms, 1):
        h, a = m["home"]["name"], m["away"]["name"]
        ev = {"@type": "SportsEvent", "name": f"{h} × {a}", "sport": "Soccer",
              "startDate": datetime.datetime.fromtimestamp(m["ts"], RIYADH).isoformat(),
              "eventStatus": "https://schema.org/" + ("EventPostponed" if m["status"] == "STATUS_POSTPONED"
                                                     else "EventCancelled" if m["status"] == "STATUS_CANCELED"
                                                     else "EventScheduled"),
              "homeTeam": {"@type": "SportsTeam", "name": h}, "awayTeam": {"@type": "SportsTeam", "name": a},
              "superEvent": {"@type": "SportsEvent", "name": sup}}
        if url_of:
            ev["url"] = url_of(m)
        if m.get("venue"):
            ev["location"] = {"@type": "Place", "name": m["venue"], "address": m.get("city") or m["venue"]}
        items.append({"@type": "ListItem", "position": i, "item": ev})
    return {"@context": "https://schema.org", "@type": "ItemList", "name": f"مباريات {sup}", "itemListElement": items}


def _crumbs(*items):
    site = guide_pages.SITE
    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i, "name": n, "item": site + p}
        for i, (n, p) in enumerate((("دليل سمارت سوق", "/"),) + items, 1)]}


def _tabs(cups, current=""):
    return ('<nav class="ltabs" aria-label="المسابقات">' + "".join(
        f'<a href="{PATH}/{k}"{" aria-current=page" if k == current else ""}>{_esc(COMPS[k]["short"])}</a>'
        for k in available(cups)) + "</nav>")


def _devices():
    items = "".join(f'<li><a href="{p}">{_esc(n)}</a></li>' for p, n in DEVICES)
    return ('<section class="card" id="devices" aria-labelledby="devices-h"><h2 id="devices-h">شغّل اشتراكك على جهازك</h2>'
            '<p class="sub">خطوات تشغيل اشتراك سمارت سوق بالصور على كل جهاز، من التحميل حتى أول قناة:</p>'
            f'<ul class="devs">{items}</ul>'
            '<p class="sub">لم تشترك بعد؟ <a class="link" href="/compare">قارن الباقات حسب جهازك</a> '
            'أو <a class="link" href="/#buy">دعنا نرشّح لك الباقة</a>.</p></section>')


def _updated(at):
    return (f'<p class="lsrc">آخر تحديث: <time datetime="{datetime.datetime.fromtimestamp(at, RIYADH).isoformat()}">'
            f'{league._when(at)}</time> بتوقيت السعودية · يُحدَّث تلقائيًا · المواعيد من ESPN</p>')


def render(slug, cups=(), now=None):
    """صفحة مشاهدة مسابقة ← (رمز HTTP، بايتات، مدة الكاش)، أو None لمسابقة لا صفحة لها.
    تعذّر المباريات = 503 بالصفحة نفسها (القنوات والأجهزة والأسئلة باقية)، فلا تُفهرس بلا مواعيد."""
    if "/" in slug:
        return render_match(*slug.split("/", 1), now=now)
    if slug not in available(cups):
        return None
    c, cup, now = COMPS[slug], _cup(cups, slug), time.time() if now is None else now
    if cup:                                  # البطولة: اسمها وموسمها من إعدادها، وترتيبها مع مبارياتها
        data, at = _get(slug, cups)
        name, season, table = cup.CUP["name"], cup.CUP["season"], None
    else:                                    # الدوري: الترتيب من كاشه في league (وفيه الموسم) مع المباريات
        (data, at), table = _all([lambda: _get(slug, cups), lambda: league.table(slug)])
        name, table = league.LEAGUES[slug]["name"], table if table["ok"] else None
        season = (table or {}).get("season", "")
    ms, groups = (data["matches"], data.get("groups")) if data else (None, None)
    short, url = c["short"], f"{guide_pages.SITE}{PATH}/{slug}"
    ss = f" {season}" if season else ""
    also = f" ({cup.CUP['level']})" if cup else f" ({c['alt']})" if c["alt"] else ""
    title = f"مشاهدة {name}{ss} بث مباشر: مباريات اليوم والقنوات الناقلة | سمارت سوق"
    desc = (f"مشاهدة {name}{ss} بث مباشر: مواعيد مباريات اليوم والقادمة بتوقيت السعودية، والقنوات الناقلة "
            f"({c['badge']})، وآخر النتائج والترتيب.{_lead(ms or [], now)}")
    ld = [_crumbs(("مشاهدة المباريات", PATH), (f"مشاهدة {name}", f"{PATH}/{slug}"))]

    cards = []
    if ms is None:
        cards.append(('<section class="card" id="today"><p>تعذّر تحميل المباريات الآن، ونعيد المحاولة تلقائيًا. '
                      'حدّث الصفحة بعد دقائق.</p></section>'))
    else:
        paint = _painter(slug, cups, ms)
        todays, later, done = split(ms, now)
        for key, head, body in (("today", f"مباريات {short} اليوم", todays and paint(todays)),
                                ("upcoming", f"مواعيد مباريات {short} القادمة", later and paint(later)),
                                ("results", f"آخر نتائج {short}", done and paint(done, True))):
            if body:
                cards.append(f'<section class="card" id="{key}" aria-labelledby="{key}-h"><h2 id="{key}-h">{_esc(head)}</h2>'
                             f'{body}</section>')
        if not cards:
            cards.append(f'<section class="card" id="upcoming"><h2>مواعيد مباريات {_esc(short)}</h2>'
                         '<p>لا مباريات في الأسابيع القريبة. تظهر مواعيد الجولة القادمة هنا حين تُعلن.</p></section>')
        soon = [m for m in todays + later if m["state"] != "post"][:MAX_ROWS]
        if soon:
            ld.append(_events(soon, f"{name}{ss}", (lambda m: guide_pages.SITE + cup.url(m)) if cup else None))
    cards.insert(1, tournament._ad("cup-ad-inline", f"watch-{slug}"))

    per_match = "والقناة الناقلة لكل مباراة تظهر تحتها متى أُعلنت." if cup else "والقناة المحدّدة لكل مباراة يعلنها الناقل قبلها."
    cards.append(f'<section class="card" id="tv" aria-labelledby="tv-h"><h2 id="tv-h">القنوات الناقلة {_esc(_li(short))}</h2>'
                 f'<p>{_esc(c["tv"])}</p><p class="sub">المواعيد في هذه الصفحة بتوقيت السعودية، {per_match}</p></section>')
    if table:
        cards.append(f'<section class="card league" id="standings" aria-labelledby="standings-h"><h2 id="standings-h">'
                     f'ترتيب {_esc(short)}</h2>{league.tables_html(table, limit=league.PREVIEW)}'
                     f'<a class="lfull" href="{league.PATH}{slug}">جدول ترتيب {_esc(name)} كاملًا ←</a></section>')
    elif cup and groups:
        cards.append(f'<section class="card league" id="standings" aria-labelledby="standings-h"><h2 id="standings-h">'
                     f'ترتيب {_esc(short)}</h2>'
                     + league.tables_html({"league": cup.CUP["level"], "groups": groups, "zones": cup.ZONES},
                                          limit=league.PREVIEW)
                     + f'<a class="lfull" href="{cup.PATH}">كل نتائج {_esc(name)} وترتيبها ←</a></section>')
    cards.append(_devices())
    qa = faq(slug, name, season, ms or [], table, now)
    ld.append({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in qa]})
    cards.append(f'<section class="card faq" id="faq" aria-labelledby="faq-h"><h2 id="faq-h">أسئلة شائعة عن مشاهدة '
                 f'{_esc(short)}</h2>' + "".join(f"<h3>{_esc(q)}</h3><p>{_esc(a)}</p>" for q, a in qa) + "</section>")
    if ms is not None:
        cards.append(_updated(at))

    live = any(m["state"] == "in" for m in ms or [])
    head = (f'<h1>مشاهدة {_esc(name)}{league._season({"season": season})}</h1>\n'
            f'<p class="sub">كل ما تحتاجه لمشاهدة {_esc(name + also)} في صفحة واحدة تتحدّث تلقائيًا: مباريات اليوم '
            'والجولة القادمة بمواعيدها بتوقيت السعودية، والقنوات الناقلة، وآخر النتائج والترتيب.</p>\n' + _tabs(cups, slug))
    crumb = f'<a class="link" href="{PATH}">مشاهدة المباريات</a> ← {_esc(name)}'
    body = _doc(title, desc, url, ld, crumb, head, "".join(cards), live, f"watch-{slug}")
    return (200 if ms is not None else 503), body, (tournament.LIVE_TTL if live else 300)


def render_hub(cups=(), now=None):
    """المدخل ‏/watch ← (رمز، بايتات، مدة الكاش): بطاقةٌ لكل مسابقة بمباريات اليوم أو أقرب مباراتين،
    الجارية ثم ذات مباريات اليوم أولًا، ثم جدول القنوات الناقلة. بلا مباريات من أي مسابقة = 503."""
    now = time.time() if now is None else now
    slugs = available(cups)
    got = dict(zip(slugs, _all([lambda s=s: _get(s, cups) for s in slugs])))
    rows, total, live, newest = [], 0, False, 0.0
    for i, k in enumerate(slugs):
        data, at = got[k]
        name = _name(k, cups)
        if not data:
            rows.append(((3, 0, i), k, name, "", '<p class="sub">تعذّر تحميل المباريات الآن.</p>'))
            continue
        ms, newest = data["matches"], max(newest, at)
        todays, later, _ = split(ms, now)
        paint = _painter(k, cups, ms)
        on = any(m["state"] == "in" for m in todays)
        live = live or on
        total += len(todays)
        if todays:
            note = "مباشر الآن" if on else f"مباريات اليوم: {len(todays)}"
            rows.append(((0 if on else 1, 0, i), k, name, note, paint(todays)))
        elif later:
            rows.append(((2, later[0]["ts"], i), k, name, "المباريات القادمة", paint(later[:HUB_NEXT])))
        else:
            rows.append(((2, float("inf"), i), k, name, "", '<p class="sub">لا مباريات في الأسابيع القريبة.</p>'))
    cards = []
    for n, (_, k, name, note, body) in enumerate(sorted(rows, key=lambda r: r[0])):
        c = COMPS[k]
        cards.append(f'<section class="card wcomp" aria-labelledby="c-{k}"><h2 id="c-{k}"><a href="{PATH}/{k}">مشاهدة '
                     f'{_esc(name)}</a></h2><p class="sub">'
                     + (f"<b>{_esc(note)}</b> · " if note else "") + f'الناقل: {_esc(c["badge"])}</p>{body}'
                     f'<a class="more" href="{PATH}/{k}">كل مواعيد {_esc(c["short"])} ←</a></section>')
        if n == 0:
            cards.append(tournament._ad("cup-ad-inline", "watch"))
    tv = "".join(f'<tr><th scope="row"><a href="{PATH}/{k}">{_esc(_name(k, cups))}</a></th>'
                 f'<td>{_esc(COMPS[k]["tv"])}</td></tr>' for k in slugs)
    cards.append('<section class="card" id="tv" aria-labelledby="tv-h"><h2 id="tv-h">القنوات الناقلة للدوريات والبطولات</h2>'
                 f'<div class="lwrap"><table class="tvt"><tbody>{tv}</tbody></table></div></section>')
    cards.append(_devices())
    if newest:
        cards.append(_updated(newest))

    title = "مشاهدة مباريات اليوم بث مباشر والقنوات الناقلة: دوري روشن والدوريات الأوروبية | سمارت سوق"
    today = f" عدد مباريات اليوم: {total}." if total else ""
    desc = ("مباريات اليوم بتوقيت السعودية من دوري روشن والدوري الإنجليزي والإسباني والإيطالي والألماني والفرنسي "
            f"ودوري أبطال أوروبا وآسيا ودوري الأمم وكأس الخليج، والقنوات الناقلة لكل مسابقة.{today}")
    head = ('<h1>مشاهدة مباريات اليوم</h1>\n<p class="sub">مباريات اليوم والجولات القادمة بتوقيت السعودية من دوري روشن '
            'والدوريات الأوروبية الخمسة ودوري أبطال أوروبا وآسيا ودوري الأمم وكأس الخليج، مع القنوات الناقلة لكل مسابقة. '
            'اختر المسابقة لمواعيدها كاملة وترتيبها.</p>\n' + _tabs(cups))
    body = _doc(title, desc, guide_pages.SITE + PATH, [_crumbs(("مشاهدة المباريات", PATH))],
                "مشاهدة المباريات", head, "".join(cards), live, "watch")
    return (200 if newest else 503), body, (tournament.LIVE_TTL if live else 300)


# ---------- صفحة المباراة ----------
_summaries = {}                                      # (الدوري، المعرّف) ← كاش ملخّص المباراة (مباريات الخلاصة وحدها)


def _summary_of(k, m):
    f = _summaries.get((k, m["id"]))
    if f is None:
        code = league.LEAGUES[k]["code"]
        f = _summaries[(k, m["id"])] = league.Feed(
            lambda: tournament.summary(league.get_json(f"/site/v2/sports/soccer/{code}/summary?event={m['id']}")),
            lambda d: tournament.LIVE_TTL if d["state"] == "in" else tournament.DONE_TTL if d["state"] == "post"
            else league.TTL)
    return f.get()[0]


def sitemap():
    """صفحات مباريات الدوريات لخريطة الموقع (من كاش الدوريات؛ ما تعذّر جلبه يُترك)."""
    out = []
    for k in league.LEAGUES:
        data = _feeds[k].get()[0]
        out += [(match_url(k, m), "daily", "0.5") for m in (data or {}).get("matches", [])]
    return out


def render_match(k, tail, now=None):
    """صفحة مباراةٍ من دوري (‏/watch/<الدوري>/<المعرّف-الفريقان>) ← (رمز، بايتات، مدة الكاش)، أو
    ("redirect", الرابط) لرابطٍ غير رابطها، أو None لدوريٍّ غير معروف أو مباراةٍ ليست في كاشه."""
    mt = re.fullmatch(r"(\d+)(?:-[a-z0-9-]*)?", tail or "")
    if k not in league.LEAGUES or not mt:
        return None
    now = time.time() if now is None else now
    data = _get(k, ())[0]
    m = next((x for x in (data or {}).get("matches", []) if x["id"] == mt.group(1)), None)
    if m is None:
        return None
    if tail != m["slug"]:
        return "redirect", match_url(k, m)
    s = _summary_of(k, m) or {"goals": [], "stats": {}, "venue": "", "city": "", "attendance": None}
    c, h, a = COMPS[k], m["home"], m["away"]
    name = league.LEAGUES[k]["name"]
    page_url = guide_pages.SITE + match_url(k, m)
    when = _when(m)
    h1 = f"مباراة {h['name']} و{a['name']}"
    title = f"{h['name']} و{a['name']} في {name}: موعد المباراة والقناة الناقلة والنتيجة | سمارت سوق"
    place = ", ".join(x for x in (s["venue"] or m["venue"], s["city"] or m["city"]) if x)
    mid, note, cls = tournament._status(m)
    off = m["status"] in OFF
    tv = "" if m["state"] == "post" or off else (
        f'<p class="when tvline">{tournament.TV_ICON}القناة الناقلة: <b dir="auto">{_esc(c["badge"])}</b></p>')
    hero = (f'<section class="card mhero" aria-label="{_esc(h1)}"><span class="stage">{_esc(name)}'
            + (f' · {_esc(m["stage"])}' if m["stage"] else "") + '</span>'
            f'<div class="match{cls}">{tournament._team(h)}<span class="mid">{mid}{note}</span>'
            f'{tournament._team(a, True)}</div><p class="when">{_esc(when)}</p>{tv}'
            + (f'<p class="when">الملعب: <span dir="auto">{_esc(place)}</span></p>' if place else "") + "</section>")
    parts = [hero]
    goals = tournament._goals_html(m, s)
    if goals:
        parts.append(f'<section class="card"><h2>الأهداف</h2>{goals}</section>')
    parts.append(tournament._ad("cup-ad-inline", f"watch-{k}-match"))
    stats = tournament._stats_html(m, s)
    if stats:
        parts.append(f'<section class="card"><h2>إحصاءات المباراة</h2>{stats}</section>')
    ans = (f"تُقام مباراة {h['name']} و{a['name']} في {name}: {when}." if m["state"] == "pre" and not off
           else f"أُقيمت مباراة {h['name']} و{a['name']} في {name}: {when}." if m["state"] == "post"
           else f"مباراة {h['name']} و{a['name']} في {name} {'مؤجلة' if m['status'] == 'STATUS_POSTPONED' else 'ملغاة'}."
           if off else f"مباراة {h['name']} و{a['name']} في {name} جارية الآن.")
    qa = [(f"متى مباراة {h['name']} و{a['name']}؟", ans),
          (f"ما القناة الناقلة لمباراة {h['name']} و{a['name']}؟", c["tv"])]
    parts.append('<section class="card faq"><h2>تفاصيل المباراة</h2>'
                 + "".join(f"<h3>{_esc(q)}</h3><p>{_esc(r)}</p>" for q, r in qa) + "</section>")
    todays = [x for x in (data or {}).get("matches", []) if x is not m
              and tournament._day(x["ts"]) == tournament._day(m["ts"])]
    if todays:
        parts.append(f'<section class="card"><h2>مباريات {_esc(name)} في اليوم نفسه</h2>'
                     + _days(todays, lambda x: _row(x, c["badge"], k)) + "</section>")
    parts.append(f'<p class="lsrc"><a class="link" href="{PATH}/{k}">مشاهدة {_esc(name)}: كل المواعيد والقنوات ←</a> · '
                 f'<a class="link" href="{league.PATH}{k}">جدول الترتيب ←</a></p>')
    event = {"@context": "https://schema.org", "@type": "SportsEvent", "name": f"{h['name']} × {a['name']}",
             "sport": "Soccer", "startDate": datetime.datetime.fromtimestamp(m["ts"], RIYADH).isoformat(),
             "eventStatus": "https://schema.org/" + ("EventPostponed" if m["status"] == "STATUS_POSTPONED"
                                                    else "EventCancelled" if m["status"] == "STATUS_CANCELED"
                                                    else "EventScheduled"),
             "homeTeam": {"@type": "SportsTeam", "name": h["name"]},
             "awayTeam": {"@type": "SportsTeam", "name": a["name"]},
             "superEvent": {"@type": "SportsEvent", "name": name}, "url": page_url}
    if place:
        event["location"] = {"@type": "Place", "name": s["venue"] or m["venue"] or place, "address": place}
    ld = [_crumbs(("مشاهدة المباريات", PATH), (f"مشاهدة {name}", f"{PATH}/{k}"), (h1, match_url(k, m))), event,
          {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
              {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": r}} for q, r in qa]}]
    live = m["state"] == "in"
    desc = (f"مباراة {h['name']} و{a['name']} في {name}: {when}. القناة الناقلة {c['badge']}"
            + (f"، والنتيجة {h['score']}-{a['score']}" if m["state"] != "pre" else "") + ".")
    crumb = (f'<a class="link" href="{PATH}">مشاهدة المباريات</a> ← <a class="link" href="{PATH}/{k}">{_esc(name)}</a>'
             f' ← {_esc(h1)}')
    body = _doc(title, desc, page_url, ld, crumb, f"<h1>{_esc(h1)}</h1>", "".join(parts), live, f"watch-{k}-match")
    return 200, body, (tournament.LIVE_TTL if live else 300)


# ---------- ودجت رئيسية متجر سلة ----------
# الدوريات الخمسة بترتيب أولويتها في الرئيسية. ما لا مباريات له في الفترة الحالية لا يظهر (فدوري أبطال
# أوروبا يظهر «عند وجود مباريات»، وكل دوري يغيب في فترات التوقف الدولي) — فالرئيسية تعرض المتاح فقط.
WIDGET_LEAGUES = ("premier-league", "saudi-pro-league", "champions-league", "afc-champions-league", "la-liga")
WIDGET_AHEAD = 10 * 24 * 3600     # «الفترة الحالية»: ما بعد اليوم يُعرض إن كان خلال عشرة أيام
# «المهمة فقط»: مباراةٌ فيها نادٍ من أندية الدوري الكبرى بمعرّفه عند ESPN (ومثل ذلك لأبطال آسيا: الأندية السعودية)
_SAUDI = {"929", "817", "2276", "8346"}                                  # الهلال النصر الاتحاد الأهلي
_EURO = {"86", "83", "1068", "382", "359", "364", "360", "363", "367", "361", "132", "160", "110", "103", "111",
         "124", "114"}                                                   # الكبار في إنجلترا وإسبانيا وأوروبا
WIDGET_BIG = {"premier-league": _EURO, "saudi-pro-league": _SAUDI, "champions-league": _EURO,
              "afc-champions-league": _SAUDI | {"22022"}, "la-liga": _EURO}
WIDGET_FOCUS = 2                  # الأولان (الإنجليزي وروشن، الأكثر متابعةً عند السعوديين) يأخذان مساحةً أكبر
WIDGET_ROWS_FOCUS = 4             # أكثر مباريات الدوري المُركَّز عليه
WIDGET_ROWS_OTHER = 3             # وغيره


def render_widget(theme="", now=None):
    """ودجت رئيسية متجر سلة (‏/watch/widget داخل iframe في قسم «محتوى HTML»): الدوريات الخمسة
    (‏WIDGET_LEAGUES) بالترتيب، لكلٍّ مباريات اليوم الجارية أو التي لم تبدأ (لا المنتهية) — وإلا أقرب مباريات خلال WIDGET_AHEAD — بقناتها
    الناقلة. دوريٌ بلا مباريات في الفترة لا يظهر. والتحديث الحيّ والوضع والشفافية كودجت البطولتين
    (‏tournament.WIDGET_JS وWIDGET_CSS). ← (رمز، بايتات، مدة الكاش): 503 إن تعذّر كل شيء."""
    now = time.time() if now is None else now
    got = dict(zip(WIDGET_LEAGUES, _all([lambda s=s: _get(s, ()) for s in WIDGET_LEAGUES])))
    blocks, all_ms, live = [], [], False
    for i, k in enumerate(WIDGET_LEAGUES):
        data = got[k][0]
        if not data:
            continue
        ms = data["matches"]
        all_ms += ms
        todays, later, _ = split(ms, now)
        big = WIDGET_BIG[k]
        important = lambda m: m["home"]["id"] in big or m["away"]["id"] in big          # noqa: E731
        later = [m for m in later if m["ts"] < now + WIDGET_AHEAD and m["status"] not in OFF and important(m)]
        todays = [m for m in todays if m["status"] not in OFF and m["state"] != "post"
                  and important(m)]                                       # المتاح والمهم فقط: لا منتهية
        cap = WIDGET_ROWS_FOCUS if i < WIDGET_FOCUS else WIDGET_ROWS_OTHER
        rows, note = (todays[:cap], "") if todays else (later[:cap], "المباريات القادمة")
        if not rows:
            continue
        live = live or any(m["state"] == "in" for m in rows)
        badge = COMPS[k]["badge"]
        blocks.append(f'<div class="wcup"><h2><span>{_esc(league.LEAGUES[k]["name"])}'
                      + (f' <small class="n">· {note}</small>' if note else "")
                      + f'</span><a href="{PATH}/{k}" target="_blank" rel="noopener">كل المواعيد ←</a></h2>'
                      + _days(rows, lambda m: _row(m, badge, k, True)) + "</div>")
    if blocks:
        body = f'<div class="{"wcols" if len(blocks) > 1 else "wone"}">{"".join(blocks)}</div>'
    elif all_ms:
        body = '<p class="sub">لا مباريات في الدوريات خلال الأيام القادمة (توقّفٌ للمنتخبات غالبًا).</p>'
    else:
        body = '<p class="sub">تعذّر تحميل المباريات الآن، ونعيد المحاولة تلقائيًا.</p>'
    names = " · ".join(league.LEAGUES[k]["tab"] for k in WIDGET_LEAGUES)
    doc = f"""<!doctype html>
<html lang="ar" dir="rtl"{f' data-theme="{theme}"' if theme in ("light", "dark") else ""}>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>مباريات الدوريات — {_esc(names)} | سمارت سوق</title>
<meta name="robots" content="noindex">
<link rel="canonical" href="{guide_pages.SITE}{PATH}">
<link rel="preconnect" href="{league.LOGO_HOST}">
<style>{guide_pages._style()}
{tournament.CSS}
{tournament.WIDGET_CSS}
{tournament.HUB_CSS}
.wcup h2 .n{{font-weight:600;color:var(--mute);font-size:.78rem}}
.wcols .wcup,.wone .wcup{{min-width:0}}</style>
</head>
<body>
<main>
<section class="card wcard"{tournament._live_attrs(all_ms)}>
<a class="whead" href="{PATH}" target="_blank" rel="noopener" style="text-decoration:none">{tournament.BALL}<span><b>مباريات الدوريات</b>
<small>{_esc(tournament._day_label(tournament._day(now)))} · بتوقيت السعودية</small></span></a>
{body}
<p class="lsrc">يُحدَّث تلقائيًا · المصدر {tournament._source(all_ms)}</p>
</section>
</main>
<script>
{tournament.WIDGET_JS}
</script>
</body>
</html>"""
    return (200 if all_ms else 503), doc.encode("utf-8"), (tournament.LIVE_TTL if live else 300)


CSS = """
.faq h3{margin:16px 0 6px;font-size:1rem}
.faq p{margin:0}
.devs{list-style:none;margin:10px 0 12px;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px}
.devs a{display:block;height:100%;padding:10px 12px;border:1.5px solid var(--line);border-radius:12px;background:var(--soft);
  color:var(--ink);font-weight:600;font-size:.9rem;text-decoration:none}
.devs a:hover,.devs a:focus-visible{border-color:var(--brand)}
.tvt{width:100%;border-collapse:collapse;font-size:.88rem}
.tvt th,.tvt td{padding:10px 6px;border-top:1px solid var(--line);text-align:start;vertical-align:top}
.tvt tr:first-child th,.tvt tr:first-child td{border-top:0}
.tvt th{width:34%;font-weight:600}
.wcomp h2 a{color:inherit;text-decoration:none}
.wcomp h2 a:hover,.wcomp h2 a:focus-visible{text-decoration:underline}
.wcomp .more{display:block;margin-top:10px;font-weight:700;text-align:center}
"""


def _json(x):
    """JSON-LD داخل ‎<script>‎: «</» يُهرَّب، فاسمٌ من ESPN فيه ‎</script>‎ لا يُغلق الوسم."""
    return json.dumps(x, ensure_ascii=False).replace("</", "<\\/")


def _doc(title, desc, url, ld, crumb, head, body, live, campaign):
    """قالب صفحات المشاهدة: رأس صفحات البطولة وأنماطها، ثم عمود المحتوى وبجانبه عمود الاشتراكات."""
    site = guide_pages.SITE
    ld_html = "".join(f'<script type="application/ld+json">{_json(x)}</script>' for x in ld)
    doc = f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
<meta name="description" content="{_esc(desc)}">
<meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1">
{'<meta http-equiv="refresh" content="60">' if live else ''}
<link rel="canonical" href="{url}">
<link rel="alternate" hreflang="ar" href="{url}">
<link rel="alternate" hreflang="x-default" href="{url}">
<meta name="theme-color" content="#004D73" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0B1826" media="(prefers-color-scheme: dark)">
<meta name="color-scheme" content="light dark">
<meta property="og:type" content="website">
<meta property="og:locale" content="ar_SA">
<meta property="og:site_name" content="سمارت سوق">
<meta property="og:title" content="{_esc(title)}">
<meta property="og:description" content="{_esc(desc)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{site}/static/og-image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/favicon.ico">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="preconnect" href="{league.LOGO_HOST}">
{ld_html}
<style>{guide_pages._style()}
nav.crumb{{font-size:14px;opacity:.75;margin:0 0 14px}}
{tournament.CSS}{CSS}</style>
</head>
<body>
<main id="view">
<nav class="crumb"><a class="link" href="/">دليل سمارت سوق</a> ← {crumb}</nav>
{head}
<div class="cupgrid">
<div class="cupmain">
{body}
</div>
{tournament._ad("cup-ad-side", campaign)}
</div>
</main>
</body>
</html>"""
    return doc.encode("utf-8")

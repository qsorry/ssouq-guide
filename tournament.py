# -*- coding: utf-8 -*-
"""صفحة بطولة بعينها (‏/nations-league): النتائج ومباريات اليوم والقادمة وترتيب
المجموعات، ومعها إعلان الاشتراكات.

البطولة الآن دوري الأمم الأوروبية 2026-27 — المستوى الأول (League A) وحده:
مجموعاته الأربع، وأدواره الإقصائية (ربع النهائي والنهائيات)، وملحق الصعود والهبوط
حين يكون أحد طرفيه من منتخباته. المباريات من scoreboard في ESPN (كل سنةٍ من سنتي
البطولة في طلب واحد) والترتيب من standings عبر league.parse، والأسماء العربية
من league.AR. المواعيد بتوقيت السعودية، وما لم تعتمد ESPN ساعته يظهر «يُعلن لاحقًا».

الكاش (league.Feed) ربع ساعة، ودقيقة واحدة من قبل انطلاق مباراة بنصف ساعة حتى
تنتهي؛ والصفحة نفسها تتحدّث كل دقيقة ما دامت فيها مباراة جارية.

الإعلان من CATALOG في index.html — مصدر الباقات الوحيد — فلا يُنسخ هنا سعرٌ ولا
صورة ولا رابط. والصفحة لا تذكر قنوات البث: ESPN لا تعطي ناقلي المنطقة.
"""
import datetime
import json
import os
import re
import time

import guide_pages
import league
from league import RIYADH, MONTHS, _esc

PATH = "/nations-league"
CUP = dict(
    code="uefa.nations", years=("2026", "2027"),
    name="دوري الأمم الأوروبية", level="المستوى الأول", season="2026-27",
    group="Group A",                                   # مجموعات المستوى الأول: A1…A4
    knockout=("quarterfinals", "semifinals", "3rd-place-match", "final"),
    playoffs="relegation-playoffs",
)
# مركز المنتخب في مجموعته ← منطقته (نظام 2026-27: الأول والثاني إلى ربع النهائي،
# والثالث إلى ملحق الهبوط، والرابع يهبط). ملاحظات ESPN هنا تخلط المستويات الأربعة.
RANK_ZONES = {1: "qf", 2: "qf", 3: "rpo", 4: "rel"}
ZONES = {"qf": {"label": "التأهل إلى ربع النهائي", "color": "#16A34A"},
         "rpo": {"label": "ملحق الهبوط", "color": "#F59E0B"},
         "rel": {"label": "الهبوط إلى المستوى الثاني", "color": "#DC2626"}}
STAGES = {"quarterfinals": "ربع النهائي", "semifinals": "نصف النهائي",
          "3rd-place-match": "تحديد المركز الثالث", "final": "النهائي",
          "relegation-playoffs": "ملحق الصعود والهبوط"}
ADS = ("p153695876", "p479880741", "p2083342610")    # باقات الإعلان من CATALOG، بترتيبها
UTM_CAMPAIGN = "nations-league"
DAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
LIVE_TTL = 60


# ---------- القراءة ----------
def _placeholder(name):
    """أطراف الأدوار الإقصائية قبل أن تُعرف: "Group A1 Winner" ← «متصدّر المجموعة الأولى»."""
    s = str(name or "").strip()
    if not s or re.fullmatch(r"(?i)tbd|to be determined", s):
        return "يُحدَّد لاحقًا"
    m = re.fullmatch(r"(?i)group (\w+) (winner|2nd place|runner-up)", s)
    if m:
        g = league._group("group " + m.group(1), 0)[1]
        return ("متصدّر " if m.group(2).lower() == "winner" else "وصيف ") + g
    m = re.fullmatch(r"(?i)(quarterfinal|semifinal) (\d+) (winner|loser)", s)
    if m:
        what = "الفائز" if m.group(3).lower() == "winner" else "الخاسر"
        return f"{what} في {STAGES[m.group(1).lower() + 's']} {m.group(2)}"
    return s


def _side(x):
    t = x.get("team") or {}
    name = league.AR.get(str(t.get("id") or "")) or _placeholder(t.get("displayName") or t.get("name"))
    so = x.get("shootoutScore")
    return {"id": str(t.get("id") or ""), "name": name, "logo": league.logo(t.get("logo")),
            "score": int(float(x.get("score") or 0)), "so": None if so is None else int(float(so)),
            "win": bool(x.get("winner"))}


def _ts(s):
    return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()


def matches(events):
    """أحداث scoreboard ← مباريات المستوى الأول مرتّبةً بالموعد."""
    def stage_of(e):
        return (e.get("season") or {}).get("slug") or ""

    def group_of(e):
        return ((e.get("competitions") or [{}])[0].get("group") or {}).get("name") or ""

    ours = {str(x.get("team", {}).get("id")) for e in events if group_of(e).startswith(CUP["group"])
            for x in (e.get("competitions") or [{}])[0].get("competitors") or []}
    out = []
    for e in events:
        c = (e.get("competitions") or [{}])[0]
        comp = c.get("competitors") or []
        stage, group = stage_of(e), group_of(e)
        if not (group.startswith(CUP["group"]) or stage in CUP["knockout"]
                or (stage == CUP["playoffs"] and ours & {str(x.get("team", {}).get("id")) for x in comp})):
            continue
        if len(comp) != 2:
            continue
        sides = {x.get("homeAway"): x for x in comp}
        home, away = sides.get("home", comp[0]), sides.get("away", comp[1])
        st = c.get("status") or e.get("status") or {}
        kind = st.get("type") or {}
        out.append({
            "id": str(e.get("id") or ""), "ts": _ts(e.get("date")),
            "time_ok": c.get("timeValid") is not False,
            "stage": league._group(group, 0)[1] if group else STAGES.get(stage, stage),
            "home": _side(home), "away": _side(away),
            "state": kind.get("state") or "pre", "status": kind.get("name") or "",
            "clock": str(st.get("displayClock") or ""),
        })
    out.sort(key=lambda m: (m["ts"], m["id"]))
    return out


def _groups(standings):
    """مجموعات المستوى الأول من standings، بمناطق المراكز لا بملاحظات ESPN."""
    groups = [g for g in league.parse(standings)["groups"] if g["key"].startswith(CUP["group"])]
    for g in groups:
        for r in g["rows"]:
            r["zone"] = RANK_ZONES.get(r["rank"], "")
    return groups


def load():
    events = []
    for y in CUP["years"]:
        events += league.get_json(f"/site/v2/sports/soccer/{CUP['code']}/scoreboard?dates={y}").get("events") or []
    ms = matches(events)
    if not ms:
        raise ValueError("no matches for this tournament")
    return {"matches": ms, "groups": _groups(league.get_json(f"/v2/sports/soccer/{CUP['code']}/standings"))}


def _ttl(data):
    """دقيقة واحدة حول المباريات (من قبل انطلاقها بنصف ساعة)، وإلا المدة العادية."""
    now = time.time()
    for m in data["matches"]:
        if m["state"] == "in" or (m["state"] == "pre" and m["time_ok"] and m["ts"] - 1800 <= now <= m["ts"] + 3 * 3600):
            return LIVE_TTL
    return league.TTL


_feed = league.Feed(lambda: load(), _ttl)


# ---------- الرسم ----------
def _day(ts):
    return datetime.datetime.fromtimestamp(ts, RIYADH).date()


def _day_label(d):
    return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]} {d.year}"


def _clock(ts):
    t = datetime.datetime.fromtimestamp(ts, RIYADH)
    return f"{t.hour % 12 or 12}:{t.minute:02d} {'ص' if t.hour < 12 else 'م'}"


def _team(s, away=False):
    crest = (f'<img src="{_esc(s["logo"])}" alt="" width="26" height="26" loading="lazy">'
             if s["logo"] else '<i class="crest"></i>')
    name = f'<b dir="auto">{_esc(s["name"])}</b>'
    return (f'<span class="side{" away" if away else ""}{" win" if s["win"] else ""}">'
            f'{name + crest if away else crest + name}</span>')


def _row(m):
    h, a = m["home"], m["away"]
    score = (f'<span class="score"><b>{h["score"]}</b><i>-</i><b>{a["score"]}</b></span>')
    if m["state"] == "in":
        now = "بين الشوطين" if m["status"] == "STATUS_HALFTIME" else f"مباشر {_esc(m['clock'])}"
        mid, note, cls = score, f'<small class="now">{now}</small>', " live"
    elif m["state"] == "post":
        if h["so"] is not None and a["so"] is not None:
            how = f'ترجيح <span class="pens"><b>{h["so"]}</b>-<b>{a["so"]}</b></span>'
        else:
            how = "بعد التمديد" if m["status"] == "STATUS_FINAL_AET" else "انتهت"
        mid, note, cls = score, f"<small>{how}</small>", " done"
    else:
        off = {"STATUS_POSTPONED": "مؤجلة", "STATUS_CANCELED": "ملغاة"}.get(m["status"])
        when = off or (_clock(m["ts"]) if m["time_ok"] else "يُعلن لاحقًا")
        mid, note, cls = f'<span class="kick">{when}</span>', "", ""
    return (f'<li class="match{cls}">{_team(h)}<span class="mid">{mid}{note}'
            f'<small class="stage">{_esc(m["stage"])}</small></span>{_team(a, True)}</li>')


def _by_day(ms, newest_first=False):
    days = {}
    for m in ms:
        days.setdefault(_day(m["ts"]), []).append(m)
    out = []
    for d in sorted(days, reverse=newest_first):
        out.append(f'<h3 class="mday">{_day_label(d)}</h3><ul class="matches">'
                   + "".join(_row(m) for m in days[d]) + "</ul>")
    return "".join(out)


def _catalog():
    with open(os.path.join(guide_pages.BASE_DIR, "index.html"), encoding="utf-8") as f:
        m = re.search(r"^const CATALOG = (.*);\s*$", f.read(), re.M)
    return json.loads(m.group(1)) if m else {}


def _ad(cls):
    """إعلان الاشتراكات: باقات ADS كما هي في CATALOG، وروابطها بحملة هذه الصفحة."""
    plans = {p["id"]: p for b in _catalog().values() for p in b.get("plans", [])}
    cards = []
    for pid in ADS:
        p = plans.get(pid)
        if not p:
            continue
        url = re.sub(r"utm_campaign=[^&]*", "utm_campaign=" + UTM_CAMPAIGN, p["url"])
        was = f'<s>{_esc(p["was"])} ر.س</s>' if p.get("was") else ""
        cards.append(
            f'<a class="planrow" href="{_esc(url)}" target="_blank" rel="noopener">'
            f'<img src="{_esc(p["img"])}" alt="" width="46" height="46" loading="lazy">'
            f'<span class="who"><b>{_esc(p["name"])}</b><small>{_esc(p.get("tag") or p.get("desc") or "")}</small></span>'
            f'<span class="money">{_esc(p["price"])} ر.س{was}</span></a>')
    if not cards:
        return ""
    return (f'<aside class="card ad {cls}" aria-label="اشتراكات سمارت سوق">'
            '<span class="eyebrow">إعلان</span><h2>اشتراكات سمارت سوق</h2>'
            '<p class="sub">دفعة واحدة بلا تجديد تلقائي، وتفعيل خلال دقائق، ودعم فني مباشر على واتساب.</p>'
            f'<div class="planlist">{"".join(cards)}</div>'
            '<a class="btn buy" href="/#buy">ساعدني في اختيار الباقة</a>'
            '<a class="more" href="/#plans">كل الباقات ←</a></aside>')


def _lead(ms):
    """جملة آخر نتيجة للوصف: «فازت إسبانيا على إنجلترا 3-2» (الفائز أولًا)."""
    done = [m for m in ms if m["state"] == "post"]
    if not done:
        return ""
    m = done[-1]
    h, a = m["home"], m["away"]
    if h["score"] == a["score"] and not (h["win"] or a["win"]):
        return f" آخر نتيجة: تعادل {h['name']} و{a['name']} {h['score']}-{a['score']}."
    w, l = (h, a) if h["win"] or (not a["win"] and h["score"] > a["score"]) else (a, h)
    return f" آخر نتيجة: فوز {w['name']} على {l['name']} {w['score']}-{l['score']}."


CSS = """
main{max-width:1040px}
.cupgrid{display:grid;grid-template-columns:minmax(0,1fr);gap:16px}
.cupgrid>*{min-width:0}
.cup-ad-side{display:none}
@media (min-width:960px){.cupgrid{grid-template-columns:minmax(0,1fr) 320px;align-items:start}
  .cup-ad-side{display:block;position:sticky;top:16px}.cup-ad-inline{display:none}}
.matches{list-style:none;margin:0;padding:0}
.mday{font-size:.92rem;margin:16px 0 4px;color:var(--brand-text)}
.mday:first-child{margin-top:0}
.match{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);align-items:center;gap:8px;
  padding:10px 0;border-top:1px solid var(--line)}
.match .side{display:flex;align-items:center;gap:8px;min-width:0}
.match .side.away{justify-content:flex-end;text-align:end}
.match .side b{font-weight:600;font-size:.92rem;line-height:1.35}
.match .side.win b{font-weight:800}
.match .side img,.match .crest{width:26px;height:26px;flex:0 0 auto;border-radius:50%;object-fit:cover;background:var(--soft)}
.match .crest{display:inline-block}
.match .mid{display:flex;flex-direction:column;align-items:center;min-width:92px;text-align:center}
.match .score{display:flex;gap:6px;font-size:1.2rem;font-weight:800;font-variant-numeric:tabular-nums}
.match .score i{font-style:normal;color:var(--mute);font-weight:400}
.match .kick{font-weight:700;font-size:.98rem;color:var(--brand-text)}
.match small{font-size:.72rem;color:var(--mute);line-height:1.5}
.match .pens{display:inline-flex;gap:2px}
.match.live .score{color:#DC2626}
.match .now{color:#DC2626;font-weight:700}
.match .now::before{content:"";display:inline-block;width:7px;height:7px;border-radius:50%;background:#DC2626;
  margin-inline-end:5px;vertical-align:1px;animation:blink 1.2s infinite}
@keyframes blink{50%{opacity:.25}}
.ad .planlist{margin:12px 0}
.ad a.planrow{text-decoration:none}
.ad .btn{display:block;margin-top:4px}
.ad .more{display:block;text-align:center;margin-top:10px;font-weight:700}
.cup-ad-inline{margin:0}
"""


def render():
    """الصفحة كاملة ← (رمز HTTP، بايتات، مدة الكاش بالثواني)."""
    data, at, error = _feed.get()
    site, url = guide_pages.SITE, guide_pages.SITE + PATH
    title = f"نتائج {CUP['name']} {CUP['season']} — {CUP['level']} ومباريات اليوم | سمارت سوق"
    h1 = f"{CUP['name']} {CUP['season']} — {CUP['level']}"
    ms = data["matches"] if data else []
    desc = (f"نتائج مباريات {CUP['level']} في {CUP['name']} {CUP['season']} أولًا بأول، ومواعيد المباريات "
            f"القادمة بتوقيت السعودية، وترتيب المجموعات الأربع.{_lead(ms)}")
    crumbs = {
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "دليل سمارت سوق", "item": site + "/"},
            {"@type": "ListItem", "position": 2, "name": h1, "item": url},
        ],
    }
    live = any(m["state"] == "in" for m in ms)
    if data:
        # الجارية في «اليوم» دائمًا وإن بدأت قبل منتصف الليل، وما لم يُلعب بعد (ولو
        # فات تاريخه: مؤجلة أو لم تُحدَّث) في «القادمة» — فلا تسقط مباراة من الصفحة
        today = _day(time.time())
        todays = [m for m in ms if _day(m["ts"]) == today or m["state"] == "in"]
        results = [m for m in ms if m["state"] == "post" and m not in todays]
        upcoming = [m for m in ms if m["state"] == "pre" and m not in todays]
        sections = []
        if todays:
            sections.append(("today", "مباريات اليوم", _by_day(todays)))
        if results:
            sections.append(("results", "النتائج", _by_day(results, newest_first=True)))
        if upcoming:
            sections.append(("upcoming", "المباريات القادمة", _by_day(upcoming)))
        groups = {"league": CUP["level"], "groups": data["groups"], "zones": ZONES}
        if data["groups"]:
            sections.append(("groups", "ترتيب المجموعات", league.tables_html(groups)))
        chips = "".join(f'<a href="#{k}">{t}</a>' for k, t, _ in sections)
        cards = []
        for i, (k, t, body) in enumerate(sections):
            cards.append(f'<section class="card" id="{k}" aria-labelledby="{k}-h"><h2 id="{k}-h">{t}</h2>{body}</section>')
            if i == 0:
                cards.append(_ad("cup-ad-inline"))
        body = (f'<nav class="ltabs" aria-label="أقسام الصفحة">{chips}</nav>' + "".join(cards)
                + f'<p class="lsrc">آخر تحديث: <time datetime="{datetime.datetime.fromtimestamp(at, RIYADH).isoformat()}">'
                f'{league._when(at)}</time> بتوقيت السعودية · يُحدَّث تلقائيًا · المصدر ESPN</p>')
    else:
        body = ('<section class="card"><p>تعذّر تحميل المباريات الآن، ونعيد المحاولة تلقائيًا. '
                'حدّث الصفحة بعد دقائق.</p></section>' + _ad("cup-ad-inline"))

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
<link rel="icon" href="/favicon.ico">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="preconnect" href="{league.LOGO_HOST}">
<script type="application/ld+json">{json.dumps(crumbs, ensure_ascii=False)}</script>
<style>{guide_pages._style()}
nav.crumb{{font-size:14px;opacity:.75;margin:0 0 14px}}
{CSS}</style>
</head>
<body>
<main id="view">
<nav class="crumb"><a class="link" href="/">دليل سمارت سوق</a> ← {_esc(CUP['name'])}</nav>
<h1>{_esc(h1)}</h1>
<p class="sub">نتائج المباريات أولًا بأول، ومواعيد القادمة بتوقيت السعودية، وترتيب المجموعات الأربع.</p>
<div class="cupgrid">
<div class="cupmain">
{body}
</div>
{_ad("cup-ad-side")}
</div>
</main>
</body>
</html>"""
    return (200 if data else 503), doc.encode("utf-8"), (LIVE_TTL if live else 300)

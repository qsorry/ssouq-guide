# -*- coding: utf-8 -*-
"""صفحة بطولة بعينها (‏/nations-league): النتائج ومباريات اليوم والقادمة وترتيب
المجموعات، ومعها إعلان الاشتراكات — وصفحة لكل مباراة (‏/nations-league/<المعرّف>-<الفريقان>)
بموعدها أو نتيجتها وأهدافها وإحصاءاتها وترتيب مجموعتها.

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
import unicodedata

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
DONE_TTL = 6 * 3600                                  # ملخّص مباراة انتهت لا يتغيّر
# إحصاءات صفحة المباراة بترتيبها: (اسمها عند ESPN، اسمها هنا)
STATS = [("possessionPct", "الاستحواذ"), ("totalShots", "التسديدات"), ("shotsOnTarget", "على المرمى"),
         ("wonCorners", "الركنيات"), ("foulsCommitted", "الأخطاء"), ("offsides", "التسلل"),
         ("yellowCards", "البطاقات الصفراء"), ("redCards", "البطاقات الحمراء"), ("saves", "التصديات")]
# نوع الهدف من نصّ ESPN ← ما يُكتب بجانبه (الأدق أولًا)
GOAL_KINDS = [("own goal", "هدف عكسي"), ("penalty", "ركلة جزاء"), ("header", "برأسية"), ("free", "ركلة حرة")]


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
    return {"id": str(t.get("id") or ""), "name": name, "en": str(t.get("displayName") or ""),
            "logo": league.logo(t.get("logo")),
            "score": int(float(x.get("score") or 0)), "so": None if so is None else int(float(so)),
            "win": bool(x.get("winner"))}


def _slug(*names):
    """«Türkiye» ← turkiye: حروف لاتينية وأرقام بشرطات، لرابط المباراة."""
    s = unicodedata.normalize("NFKD", " ".join(names)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


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
        eid = str(e.get("id") or "")
        h, a = _side(home), _side(away)
        out.append({
            "id": eid, "slug": "-".join(x for x in (eid, _slug(h["en"], a["en"])) if x),
            "ts": _ts(e.get("date")), "group": group,
            "time_ok": c.get("timeValid") is not False,
            "stage": league._group(group, 0)[1] if group else STAGES.get(stage, stage),
            "home": h, "away": a,
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


def summary(d):
    """ملخّص مباراة من ESPN ← الأهداف (بمعرّف فريقها) والإحصاءات والملعب."""
    comp = ((d.get("header") or {}).get("competitions") or [{}])[0]
    state = ((comp.get("status") or {}).get("type") or {}).get("state") or "pre"
    goals = []
    for k in d.get("keyEvents") or []:
        if not k.get("scoringPlay"):
            continue
        kind = ((k.get("type") or {}).get("text") or "").lower()
        who = ((k.get("participants") or [{}])[0].get("athlete") or {}).get("displayName") or ""
        goals.append({"team": str((k.get("team") or {}).get("id") or ""),
                      "min": str((k.get("clock") or {}).get("displayValue") or ""), "who": who,
                      "kind": next((ar for en, ar in GOAL_KINDS if en in kind), "")})
    stats = {str((t.get("team") or {}).get("id") or ""): {s.get("name"): s.get("displayValue")
                                                            for s in t.get("statistics") or []}
             for t in (d.get("boxscore") or {}).get("teams") or []}
    gi = d.get("gameInfo") or {}
    venue = gi.get("venue") or {}
    return {"state": state, "goals": goals, "stats": stats, "venue": venue.get("fullName") or "",
            "city": (venue.get("address") or {}).get("city") or "", "attendance": gi.get("attendance")}


_summaries = {}                                      # معرّف المباراة ← كاش ملخّصها (مباريات البطولة وحدها)


def _summary_of(m):
    f = _summaries.get(m["id"])
    if f is None:
        f = _summaries[m["id"]] = league.Feed(
            lambda eid=m["id"]: summary(league.get_json(f"/site/v2/sports/soccer/{CUP['code']}/summary?event={eid}")),
            lambda d: LIVE_TTL if d["state"] == "in" else DONE_TTL if d["state"] == "post" else league.TTL)
    return f.get()[0]


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


def url(m):
    return f"{PATH}/{m['slug']}"


def _status(m):
    """(الوسط: النتيجة أو الموعد، سطر الحال تحته، صنف الصف)."""
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
    return mid, note, cls


def _row(m):
    mid, note, cls = _status(m)
    return (f'<li><a class="match{cls}" href="{url(m)}">{_team(m["home"])}<span class="mid">{mid}{note}'
            f'<small class="stage">{_esc(m["stage"])}</small></span>{_team(m["away"], True)}</a></li>')


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


def _result(m):
    """«فوز إسبانيا على إنجلترا 3-2» (الفائز أولًا) أو «تعادل … 1-1»، وبالترجيح إن كان."""
    h, a = m["home"], m["away"]
    if h["score"] == a["score"] and not (h["win"] or a["win"]):
        return f"تعادل {h['name']} و{a['name']} {h['score']}-{a['score']}"
    w, l = (h, a) if h["win"] or (not a["win"] and h["score"] > a["score"]) else (a, h)
    pens = f" بركلات الترجيح {w['so']}-{l['so']}" if w["so"] is not None and l["so"] is not None else ""
    return f"فوز {w['name']} على {l['name']} {w['score']}-{l['score']}{pens}"


def _lead(ms):
    """جملة آخر نتيجة للوصف."""
    done = [m for m in ms if m["state"] == "post"]
    return f" آخر نتيجة: {_result(done[-1])}." if done else ""


CSS = """
main{max-width:1040px}
.cupgrid{display:grid;grid-template-columns:minmax(0,1fr);gap:16px}
.cupgrid>*{min-width:0}
.cup-ad-side{display:none}
@media (min-width:960px){.cupgrid{grid-template-columns:minmax(0,1fr) 320px;align-items:start}
  .cup-ad-side{display:block;position:sticky;top:16px}.cup-ad-inline{display:none}}
.matches{list-style:none;margin:0;padding:0}
.matches a.match{color:inherit;text-decoration:none}
.matches a.match:hover .side b,.matches a.match:focus-visible .side b{text-decoration:underline}
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
.mhero{text-align:center}
.mhero .stage{display:block;color:var(--mute);font-size:.82rem;margin-bottom:12px}
.mhero .match{border-top:0;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);gap:10px}
.mhero .match .side{flex-direction:column;justify-content:center;text-align:center}
.mhero .match .side.away{justify-content:center}
.mhero .match .side.away img,.mhero .match .side.away .crest{order:-1}
.mhero .match .side img,.mhero .match .crest{width:56px;height:56px}
.mhero .match .side b{font-size:1.05rem}
.mhero .match .score{font-size:2rem}
.mhero .match .kick{font-size:1.3rem}
.mhero .when{margin:10px 0 0;color:var(--mute);font-size:.86rem}
.goals{list-style:none;margin:0;padding:0}
.goals li{display:flex;gap:8px;align-items:baseline;padding:7px 0;border-top:1px solid var(--line)}
.goals li:first-child{border-top:0}
.goals li.away{justify-content:flex-end}
.goals .min{font-weight:700;color:var(--brand-text);font-variant-numeric:tabular-nums}
.goals small{color:var(--mute)}
.stat{display:grid;grid-template-columns:3.5em 1fr 3.5em;align-items:center;gap:4px 10px;padding:8px 0;
  border-top:1px solid var(--line);font-variant-numeric:tabular-nums}
.stat:first-child{border-top:0}
.stat>b{text-align:center}
.stat>span{text-align:center;color:var(--mute);font-size:.84rem}
.stat .bar{grid-column:1/-1;display:flex;height:6px;border-radius:3px;overflow:hidden;background:var(--line)}
.stat .bar i{background:var(--brand)}
.stat .bar i+i{background:var(--gold)}
.stats-head{display:flex;justify-content:space-between;font-weight:700;margin-bottom:6px}
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

    main = (f'<h1>{_esc(h1)}</h1>\n<p class="sub">نتائج المباريات أولًا بأول، ومواعيد القادمة بتوقيت '
            f'السعودية، وترتيب المجموعات الأربع.</p>')
    return ((200 if data else 503), _doc(title, desc, url, [crumbs], _esc(CUP["name"]), main, body, live),
            (LIVE_TTL if live else 300))


def _doc(title, desc, url, ld, crumb, head, body, live):
    """قالب الصفحتين: الرأس والأنماط، ثم عمود المحتوى وبجانبه عمود الاشتراكات."""
    site = guide_pages.SITE
    ld_html = "".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False)}</script>' for x in ld)
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
{ld_html}
<style>{guide_pages._style()}
nav.crumb{{font-size:14px;opacity:.75;margin:0 0 14px}}
{CSS}</style>
</head>
<body>
<main id="view">
<nav class="crumb"><a class="link" href="/">دليل سمارت سوق</a> ← {crumb}</nav>
{head}
<div class="cupgrid">
<div class="cupmain">
{body}
</div>
{_ad("cup-ad-side")}
</div>
</main>
</body>
</html>"""
    return doc.encode("utf-8")


def _goals_html(m, s):
    """الأهداف بترتيبها: هدف صاحب الأرض يمينًا والضيف يسارًا، بالدقيقة واللاعب."""
    items = []
    for g in s["goals"]:
        away = g["team"] == m["away"]["id"]
        kind = f' <small>({_esc(g["kind"])})</small>' if g["kind"] else ""
        items.append(f'<li class="{"away" if away else "home"}"><span class="min" dir="ltr">{_esc(g["min"])}</span>'
                     f'<b dir="auto">{_esc(g["who"])}</b>{kind}</li>')
    return f'<ul class="goals">{"".join(items)}</ul>' if items else ""


def _num(v):
    try:
        return float(str(v).rstrip("%"))
    except (TypeError, ValueError):
        return None


def _stats_html(m, s):
    """صفوف المقارنة: قيمة صاحب الأرض يمينًا والضيف يسارًا، وشريطٌ بنسبتهما."""
    hs, as_ = s["stats"].get(m["home"]["id"]) or {}, s["stats"].get(m["away"]["id"]) or {}
    rows = []
    for key, label in STATS:
        h, a = _num(hs.get(key)), _num(as_.get(key))
        if h is None or a is None:
            continue
        pct = key == "possessionPct"
        share = 50 if h + a == 0 else round(100 * h / (h + a))
        show = (lambda v: f"{round(v)}%") if pct else (lambda v: f"{int(v)}")
        rows.append(f'<div class="stat"><b>{show(h)}</b><span>{label}</span><b>{show(a)}</b>'
                    f'<span class="bar" aria-hidden="true"><i style="width:{share}%"></i><i style="flex:1"></i></span></div>')
    if not rows:
        return ""
    return (f'<div class="stats-head"><span dir="auto">{_esc(m["home"]["name"])}</span>'
            f'<span dir="auto">{_esc(m["away"]["name"])}</span></div>' + "".join(rows))


def _desc(m, when):
    names = f"{m['home']['name']} و{m['away']['name']}"
    if m["state"] == "post":
        return f"انتهت مباراة {names} في {CUP['name']} ({m['stage']}) ب{_result(m)}."
    if m["state"] == "in":
        return (f"مباراة {names} في {CUP['name']} مباشرة الآن: {m['home']['name']} {m['home']['score']}، "
                f"{m['away']['name']} {m['away']['score']}.")
    return f"موعد مباراة {names} في {CUP['name']} ({CUP['level']}، {m['stage']}): {when}."


def render_match(tail):
    """صفحة مباراة ← (رمز، بايتات، مدة الكاش)، أو ("redirect", الرابط) لرابطٍ غير رابطها،
    أو None لمباراة ليست من البطولة."""
    mt = re.fullmatch(r"(\d+)(?:-[a-z0-9-]*)?", tail or "")
    if not mt:
        return None
    data, at, error = _feed.get()
    m = next((x for x in (data or {}).get("matches", []) if x["id"] == mt.group(1)), None)
    if m is None:
        return None
    if tail != m["slug"]:
        return "redirect", url(m)
    s = _summary_of(m) or {"goals": [], "stats": {}, "venue": "", "city": "", "attendance": None}
    h, a = m["home"], m["away"]
    page_url = guide_pages.SITE + url(m)
    day = _day_label(_day(m["ts"]))
    when = f"{day} الساعة {_clock(m['ts'])} بتوقيت السعودية" if m["time_ok"] else f"{day}، والساعة تُعلن لاحقًا"
    title = f"{h['name']} و{a['name']} في {CUP['name']}: موعد المباراة والنتيجة | سمارت سوق"
    h1 = f"مباراة {h['name']} و{a['name']}"
    place = ", ".join(x for x in (s["venue"], s["city"]) if x)          # بالإنجليزية كما عند ESPN
    mid, note, cls = _status(m)
    hero = (f'<section class="card mhero" aria-label="{_esc(h1)}"><span class="stage">{_esc(CUP["name"])} · '
            f'{_esc(CUP["level"])} · {_esc(m["stage"])}</span>'
            f'<div class="match{cls}">{_team(h)}<span class="mid">{mid}{note}</span>{_team(a, True)}</div>'
            f'<p class="when">{_esc(when)}</p>'
            + (f'<p class="when">الملعب: <span dir="auto">{_esc(place)}</span></p>' if place else "") + "</section>")
    parts = [hero]
    goals = _goals_html(m, s)
    if goals:
        parts.append(f'<section class="card"><h2>الأهداف</h2>{goals}</section>')
    parts.append(_ad("cup-ad-inline"))
    stats = _stats_html(m, s)
    if stats:
        parts.append(f'<section class="card"><h2>إحصاءات المباراة</h2>{stats}</section>')
    group = next((g for g in data["groups"] if g["key"] == m["group"]), None) if m["group"] else None
    if group:
        parts.append(f'<section class="card"><h2>ترتيب {_esc(group["name"])}</h2>'
                     + league.tables_html({"league": CUP["level"], "groups": [group], "zones": ZONES}) + "</section>")
    others = [x for x in data["matches"] if x is not m
              and (x["group"] == m["group"] if m["group"] else not x["group"] and x["stage"] == m["stage"])]
    if others:
        parts.append(f'<section class="card"><h2>مباريات {_esc(group["name"] if group else m["stage"])} الأخرى</h2>'
                     + _by_day(others) + "</section>")
    parts.append(f'<p class="lsrc"><a class="link" href="{PATH}">كل نتائج {_esc(CUP["name"])} ومبارياته ←</a></p>')
    event = {"@context": "https://schema.org", "@type": "SportsEvent", "name": f"{h['name']} × {a['name']}",
             "sport": "Soccer", "startDate": datetime.datetime.fromtimestamp(m["ts"], RIYADH).isoformat(),
             "eventStatus": "https://schema.org/" + ("EventPostponed" if m["status"] == "STATUS_POSTPONED"
                                                    else "EventCancelled" if m["status"] == "STATUS_CANCELED"
                                                    else "EventScheduled"),
             "homeTeam": {"@type": "SportsTeam", "name": h["name"]},
             "awayTeam": {"@type": "SportsTeam", "name": a["name"]},
             "superEvent": {"@type": "SportsEvent", "name": f"{CUP['name']} {CUP['season']}"}, "url": page_url}
    if place:
        event["location"] = {"@type": "Place", "name": s["venue"] or place, "address": s["city"] or place}
    crumbs = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "دليل سمارت سوق", "item": guide_pages.SITE + "/"},
        {"@type": "ListItem", "position": 2, "name": CUP["name"], "item": guide_pages.SITE + PATH},
        {"@type": "ListItem", "position": 3, "name": h1, "item": page_url}]}
    live = m["state"] == "in"
    body = _doc(title, _desc(m, when), page_url, [crumbs, event],
                f'<a class="link" href="{PATH}">{_esc(CUP["name"])}</a> ← {_esc(h1)}',
                f"<h1>{_esc(h1)}</h1>", "".join(parts), live)
    return 200, body, (LIVE_TTL if live else 300)


def sitemap():
    """صفحة البطولة وصفحات مبارياتها لخريطة الموقع."""
    data = _feed.get()[0]
    return [(PATH, "daily", "0.8")] + [(url(m), "daily", "0.6") for m in (data or {}).get("matches", [])]

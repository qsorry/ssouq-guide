# -*- coding: utf-8 -*-
"""صفحة بطولة بعينها (‏/nations-league): النتائج ومباريات اليوم والقادمة وترتيب
المجموعات، ومعها إعلان الاشتراكات — وصفحة لكل مباراة (‏/nations-league/<المعرّف>-<الفريقان>)
بموعدها أو نتيجتها وأهدافها وإحصاءاتها وترتيب مجموعتها.

والوحدة نفسها تخدم أكثر من بطولة: هذه النسخة دوري الأمم، و`instance(**GULF)` نسخةٌ ثانية منها
(‏/gulf-cup: كأس الخليج العربي — خليجي 27) بكاشها وصفحاتها، يصنعها الخادم عند إقلاعه.

دوري الأمم الأوروبية 2026-27 — المستوى الأول (League A) وحده:
مجموعاته الأربع، وأدواره الإقصائية (ربع النهائي والنهائيات)، وملحق الصعود والهبوط
حين يكون أحد طرفيه من منتخباته. المباريات من scoreboard في ESPN (كل سنةٍ من سنتي
البطولة في طلب واحد) والترتيب من standings عبر league.parse، والأسماء العربية
من league.AR. المواعيد بتوقيت السعودية، وما لم تعتمد ESPN ساعته يظهر «يُعلن لاحقًا».

الكاش (league.Feed) ربع ساعة، ودقيقة واحدة من قبل انطلاق مباراة بنصف ساعة حتى
تنتهي؛ والصفحة نفسها تتحدّث كل دقيقة ما دامت فيها مباراة جارية.

الإعلان من CATALOG في index.html — مصدر الباقات الوحيد — فلا يُنسخ هنا سعرٌ ولا
صورة ولا رابط. والقناة الناقلة يكتبها المدير لكل مباراة (ESPN لا تعطي ناقلي المنطقة)،
فتظهر في صف المباراة وصفحتها ورسالة القناة.
"""
import datetime
import functools
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
import unicodedata

import contest
import guide_pages
import league
from league import RIYADH, MONTHS, _esc

PATH = "/nations-league"
CUP = dict(
    code="uefa.nations", years=("2026", "2027"),
    name="دوري الأمم الأوروبية", level="المستوى الأول", season="2026-27",
    group="Group A",                                   # مجموعات المستوى الأول: A1…A4
    knockout=("quarterfinals", "semifinals", "3rd-place-match", "final"),
    playoffs="relegation-playoffs", groups_word="المجموعات الأربع",
    tv="beIN SPORTS",                                  # ناقل منتخبات UEFA في المنطقة؛ يغيّرها المدير أو يمسحها
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
PREDICT = PATH + "/predict"                          # كانت صفحة المسابقة؛ تحوَّل الآن إلى /predict
DAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
LIVE_TTL = 60
DONE_TTL = 6 * 3600                                  # ملخّص مباراة انتهت لا يتغيّر
# إحصاءات صفحة المباراة بترتيبها: (اسمها عند ESPN، اسمها هنا)
STATS = [("possessionPct", "الاستحواذ"), ("totalShots", "التسديدات"), ("shotsOnTarget", "على المرمى"),
         ("wonCorners", "الركنيات"), ("foulsCommitted", "الأخطاء"), ("offsides", "التسلل"),
         ("yellowCards", "البطاقات الصفراء"), ("redCards", "البطاقات الحمراء"), ("saves", "التصديات")]
# نوع الهدف من نصّ ESPN ← ما يُكتب بجانبه (الأدق أولًا)
GOAL_KINDS = [("own goal", "هدف عكسي"), ("penalty", "ركلة جزاء"), ("header", "برأسية"), ("free", "ركلة حرة")]


# مسابقة التوقّعات (contest.py): الخادم يضبط هذه بمجلد بياناته فتعيد {المعرّف: ملخّص}،
# وبدونه (الاختبارات بلا خادم) لا مسابقة.
def contests():
    return {}


# القناة الناقلة (يكتبها المدير): الخادم يضبط هذه فتعيد {معرّف المباراة أو cup:<المسار>: القناة}،
# وقناة البطولة فيها ما كتبه المدير، وإلا CUP["tv"].
def channels():
    return {}


TV_ICON = ('<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="7" width="18" height="12" rx="2"/>'
           '<path d="m8 3 4 4 4-4"/></svg>')


def _tv(m):
    """سطر القناة الناقلة إن كُتبت."""
    ch = contest.channel_for(channels(), m["id"], PATH)                # قناتها، وإلا قناة البطولة الافتراضية
    return f'<small class="tv">{TV_ICON}<span dir="ltr">{_esc(ch)}</span></small>' if ch else ""


def _contests(ms, now=None):
    """مسابقات هذه المباريات التي لم تُطفأ: {المعرّف: (الملخّص، الحالة)}."""
    cs, now = contests(), time.time() if now is None else now
    out = {}
    for m in ms:
        s = cs.get(m["id"])
        st = contest.state_of(s, m, now) if s else "off"
        if st != "off":
            out[m["id"]] = (s, st)
    return out


@functools.lru_cache(maxsize=None)
def _ver(name):
    """بصمة ملفٍّ ثابت للرابط (?v=) — فالملفات الثابتة مخزَّنة شهرًا ويصل التعديل مع النشر.
    تُحسب مرةً في عمر العملية: الملف لا يتغيّر إلا بنشرٍ يعيد تشغيلها."""
    try:
        with open(os.path.join(guide_pages.BASE_DIR, "static", name), "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()[:10]
    except OSError:
        return "0"


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
            "clock": str(st.get("displayClock") or ""), "path": PATH, "cup": CUP["name"],
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
    groups = _groups(league.get_json(f"/v2/sports/soccer/{CUP['code']}/standings"))
    # مجموعة المباراة من الترتيب بمنتخبَيها: ESPN تخلط أحيانًا تسمية المجموعة في المباريات (كأس الخليج
    # 2026: السعودية والعراق «Group B» في المباريات و«Group A» في الترتيب) — والترتيب هو المرجع
    by_team = {r["name"]: g for g in groups for r in g["rows"]}
    for m in ms:
        g = by_team.get(m["home"]["name"])
        if m["group"] and g and by_team.get(m["away"]["name"]) is g and g["key"] != m["group"]:
            m["group"], m["stage"] = g["key"], g["name"]
    return {"matches": ms, "groups": groups}


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


def when_label(ts):
    """«الاثنين 28 سبتمبر 2026 · 9:45 م» بتوقيت السعودية."""
    return f"{_day_label(_day(ts))} · {_clock(ts)}"


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


def _row(m, new_tab=False, pz=None):
    """صف مباراة؛ و`pz` مسابقات الصفحة ({المعرّف: (الملخّص، الحالة)}) فتحمل المفتوحةُ شارتها."""
    mid, note, cls = _status(m)
    target = ' target="_blank" rel="noopener"' if new_tab else ""
    open_ = (pz or {}).get(m["id"], (None, ""))[1] == "open"
    badge = '<small class="pz">توقّع واربح</small>' if open_ else ""
    return (f'<li><a class="match{cls}" href="{url(m)}{"#predict" if open_ else ""}"{target}>{_team(m["home"])}'
            f'<span class="mid">{mid}{note}<small class="stage">{_esc(m["stage"])}</small>{_tv(m)}{badge}</span>'
            f'{_team(m["away"], True)}</a></li>')


def _by_day(ms, newest_first=False, new_tab=False, pz=None):
    days = {}
    for m in ms:
        days.setdefault(_day(m["ts"]), []).append(m)
    out = []
    for d in sorted(days, reverse=newest_first):
        out.append(f'<h3 class="mday">{_day_label(d)}</h3><ul class="matches">'
                   + "".join(_row(m, new_tab, pz) for m in days[d]) + "</ul>")
    return "".join(out)


GIFT = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 12v9H4v-9M2 7h20v5H2zM12 21V7"/>'
        '<path d="M12 7H7.5a2.5 2.5 0 1 1 0-5C11 2 12 7 12 7zM12 7h4.5a2.5 2.5 0 1 0 0-5C13 2 12 7 12 7z"/></svg>')


def _banner(ms, pz, new_tab=False):
    """شريط المسابقة أعلى الصفحة: أقرب مباراةٍ مفتوحةٍ للتوقّع وجائزتها."""
    opens = [m for m in ms if pz.get(m["id"], (None, ""))[1] == "open"]
    if not opens:
        return ""
    m = min(opens, key=lambda x: x["ts"])
    s = pz[m["id"]][0]
    target = ' target="_blank" rel="noopener"' if new_tab else ""
    more = " · ومسابقات أخرى" if len(opens) > 1 else ""
    return (f'<a class="pbanner" href="{url(m)}#predict"{target}>{GIFT}<span><b>توقّع نتيجة '
            f'{_esc(m["home"]["name"])} و{_esc(m["away"]["name"])} واربح {_esc(s["prize"])}</b>'
            f'<small>مجانًا · تُقفل التوقّعات {_esc(when_label(contest.lock_at(s, m["ts"])))}{more}</small></span>'
            f'<span class="pgo">توقّع الآن ←</span></a>')


def _prize_row(s):
    """الجائزة منتجٌ من المتجر: صورته واسمه ورابطه (يُفتح في نافذة)."""
    if not s.get("prize_url"):
        return ""
    img = (f'<img src="{_esc(s["prize_img"])}" alt="" width="46" height="46" loading="lazy">'
           if s.get("prize_img") else "")
    return (f'<a class="pprize" href="{_esc(s["prize_url"])}" target="_blank" rel="noopener">{img}'
            f'<span><small>الجائزة</small><b>{_esc(s["prize"])}</b></span><span class="pgo">صفحة الاشتراك ←</span></a>')


def _predict_card(m, s, st):
    """بطاقة المسابقة في صفحة المباراة. الحالة والنموذج من /api/contest بالمتصفح، فتبقى
    الصفحة مخزَّنةً كما هي ولا يعرض الكاش حالةً قديمة."""
    return (f'<section class="card predict" id="predict" data-m="{_esc(m["id"])}" '
            f'data-draw="{_ver("contest-draw.js")}" data-rules="/predict#rules" aria-labelledby="predict-h">'
            f'<span class="eyebrow">مسابقة مجانية</span>'
            f'<h2 id="predict-h">توقّع النتيجة واربح {_esc(s["prize"])}</h2>' + _prize_row(s) +
            f'<div class="pbody"><p class="sub">{_esc(contest.STATE_MSG.get(st, "") if st != "open" else "")}'
            f'</p><noscript><p>فعّل JavaScript لتسجّل توقّعك.</p></noscript></div>'
            f'<p class="prules"><a class="link" href="/predict#rules">شروط المسابقة وكيف يتم الفرز</a> · '
            f'<a class="link" href="/predict">كل المسابقات</a></p>'
            f'</section><script src="/static/contest.js?v={_ver("contest.js")}" defer></script>')


def _catalog():
    with open(os.path.join(guide_pages.BASE_DIR, "index.html"), encoding="utf-8") as f:
        m = re.search(r"^const CATALOG = (.*);\s*$", f.read(), re.M)
    return json.loads(m.group(1)) if m else {}


def _ad(cls, campaign=None):
    """إعلان الاشتراكات: باقات ADS كما هي في CATALOG، وروابطها بحملة هذه الصفحة (أو `campaign`
    لصفحةٍ أخرى تعرضه، كصفحات المشاهدة في watch.py)."""
    plans = {p["id"]: p for b in _catalog().values() for p in b.get("plans", [])}
    cards = []
    for pid in ADS:
        p = plans.get(pid)
        if not p:
            continue
        url = re.sub(r"utm_campaign=[^&]*", "utm_campaign=" + (campaign or UTM_CAMPAIGN), p["url"])
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
.match .tv{display:inline-flex;align-items:center;gap:4px;margin-top:3px;padding:1px 8px;border-radius:999px;
  background:var(--soft);border:1px solid var(--line);color:var(--brand-text);font-weight:700;font-size:.7rem;line-height:1.6}
.match .tv svg,.tvline svg{width:13px;height:13px;flex:0 0 auto;fill:none;stroke:currentColor;stroke-width:2;
  stroke-linecap:round;stroke-linejoin:round}
.mhero .tvline{display:flex;align-items:center;justify-content:center;gap:5px;color:var(--brand-text)}
.mhero .tvline svg{width:16px;height:16px}
.match .pz{margin-top:3px;font-size:.68rem;font-weight:800;color:var(--gold-ink);background:var(--gold);
  border-radius:999px;padding:0 8px;line-height:1.7}
.pbanner{display:flex;align-items:center;gap:12px;padding:14px 16px;margin-bottom:16px;border-radius:16px;
  background:linear-gradient(200deg,#F7B447 0%,#E0900F 100%);color:#2A1D04;text-decoration:none;box-shadow:var(--shadow)}
.pbanner svg{width:30px;height:30px;flex:0 0 auto;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.pbanner b{display:block;font-size:.98rem;line-height:1.45}
.pbanner small{display:block;font-size:.78rem;opacity:.85}
.pbanner .pgo{margin-inline-start:auto;flex:0 0 auto;font-weight:800;font-size:.86rem;white-space:nowrap}
.predict{border:2px solid var(--gold)}
.predict h2{font-size:1.2rem}
.predict h3{font-size:.98rem;margin:14px 0 6px}
.prules{margin:10px 0 0;font-size:.82rem}
.pprize{display:flex;align-items:center;gap:10px;padding:10px 12px;margin:0 0 12px;border:1px solid var(--line);
  border-radius:14px;background:var(--soft);color:inherit;text-decoration:none}
.pprize img{width:46px;height:46px;border-radius:10px;object-fit:cover;flex:0 0 auto;background:var(--card)}
.pprize small{display:block;color:var(--mute);font-size:.74rem}
.pprize b{display:block;font-size:.92rem;line-height:1.4}
.pprize .pgo{margin-inline-start:auto;flex:0 0 auto;font-weight:700;font-size:.8rem;color:var(--brand-text);white-space:nowrap}
.pscore{display:inline-flex;gap:5px;align-items:baseline;font-weight:800;font-variant-numeric:tabular-nums}
.pscore i{font-style:normal;color:var(--mute);font-weight:400}
.pcount{color:var(--mute);font-size:.88rem;margin:0 0 10px}
.pcount b{color:var(--ink)}
.pcount .hms{display:inline-block;direction:ltr;unicode-bidi:isolate;font-variant-numeric:tabular-nums}
.pteams{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);align-items:center;gap:8px;margin:6px 0 4px}
.pteam{display:flex;flex-direction:column;align-items:center;gap:6px;text-align:center;min-width:0}
.pteam img,.pteam .crest{width:44px;height:44px;border-radius:50%;object-fit:cover;background:var(--soft)}
.pteam b{font-size:.92rem;line-height:1.35}
.pvs{color:var(--mute);font-size:1.4rem;font-weight:700;align-self:end;margin-bottom:6px}
.stepper{display:flex;align-items:center;gap:6px}
.stepper button{width:40px;height:40px;border-radius:12px;border:1.5px solid var(--line);background:var(--soft);
  color:var(--ink);font:inherit;font-size:1.35rem;font-weight:700;line-height:1;cursor:pointer}
.stepper button:hover{border-color:var(--brand)}
.stepper output{min-width:46px;text-align:center;font-size:2rem;font-weight:800;font-variant-numeric:tabular-nums}
.pform label.pl{display:block;font-size:.85rem;color:var(--mute);margin:12px 0 4px}
.pform input[type=text],.pform input[type=tel]{width:100%;padding:12px;border:1.5px solid var(--line);border-radius:12px;
  background:var(--card);color:var(--ink);font:inherit}
.pform input[type=tel]{direction:ltr;text-align:right}
.pform input:focus{outline:0;border-color:var(--brand)}
.pform input.bad{border-color:#DC2626}
.pform .hint{display:block;color:var(--mute);font-size:.76rem;margin-top:4px}
.pform .chk{display:flex;gap:8px;align-items:flex-start;font-size:.86rem;margin-top:10px;cursor:pointer}
.pform .chk input{margin-top:5px;width:17px;height:17px;flex:0 0 auto;accent-color:var(--brand)}
.pform .hp{position:absolute;inset-inline-start:-9999px;width:1px;height:1px;opacity:0}
.pform .btn{display:block;width:100%;margin-top:14px}
.pmsg{min-height:1.4em;margin:8px 0 0;font-size:.9rem}
.pmsg.err{color:#DC2626}
.pmine{background:var(--soft);border-radius:12px;padding:12px 14px;margin:10px 0;font-size:.92rem}
.pmine .ph,.pwait code{direction:ltr;unicode-bidi:isolate;font-variant-numeric:tabular-nums}
.btn.wa{display:flex;align-items:center;justify-content:center;gap:8px}
.btn.wa svg{width:20px;height:20px;fill:currentColor;stroke:none;margin:0}
.pshare{display:block;text-align:center;margin-top:4px}
.pwait{background:var(--soft);border-radius:14px;padding:14px;margin:10px 0}
.pwait>b{display:block;font-size:1rem;margin-bottom:4px}
.pwait code{font:700 1.05rem ui-monospace,Menlo,Consolas,monospace;letter-spacing:.08em;background:var(--card);
  border:1px solid var(--line);border-radius:8px;padding:1px 8px}
.pwait .btn{margin:10px 0 6px}
.pstat{display:flex;gap:8px;align-items:flex-start;color:var(--mute);font-size:.86rem;margin:6px 0}
.spin{flex:0 0 auto;width:14px;height:14px;margin-top:4px;border-radius:50%;border:2px solid var(--line);
  border-top-color:var(--brand);animation:spin 1s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.plink{background:none;border:0;padding:0;font:inherit;font-size:.84rem;color:var(--brand-text);text-decoration:underline;cursor:pointer}
.pbars{display:grid;gap:6px;margin:6px 0 4px}
.pbar{display:grid;grid-template-columns:7.5em 1fr 3em;align-items:center;gap:8px;font-size:.84rem}
.pbar span:first-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pbar i{display:block;height:9px;border-radius:5px;background:var(--brand);min-width:3px}
.pbar b{text-align:end;font-variant-numeric:tabular-nums}
.ptop{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:6px}
.ptop li{border:1px solid var(--line);border-radius:999px;padding:2px 10px;font-size:.84rem}
.ptop small{color:var(--mute)}
.pfp{margin-top:12px;font-size:.84rem}
.pfp summary{cursor:pointer;color:var(--brand-text);font-weight:700}
.pfp code{display:block;margin:6px 0 4px;padding:8px 10px;border-radius:10px;background:var(--soft);direction:ltr;
  text-align:left;overflow-wrap:anywhere;font:600 .74rem/1.6 ui-monospace,Menlo,Consolas,monospace;color:var(--ink)}
.pfp p{color:var(--mute);margin:4px 0}
.pwin{background:linear-gradient(200deg,var(--brand) 0%,#012E45 100%);color:#fff;border-radius:16px;padding:14px 16px;margin:4px 0 12px}
.pwin .eyebrow{background:rgba(255,255,255,.14);color:#FFD79A;margin-bottom:6px}
.wrow{padding:8px 0;border-top:1px solid rgba(255,255,255,.16)}
.wrow:first-of-type{border-top:0}
.wrow b{font-size:1.15rem;margin-inline-end:10px}
.wrow .ph{direction:ltr;unicode-bidi:isolate;color:#BFD8E6;margin-inline-start:8px;font-variant-numeric:tabular-nums}
.wrow small{display:block;color:#BFD8E6;font-size:.8rem}
.pplay{display:flex;align-items:center;justify-content:center;gap:8px;width:100%}
.pplay svg{width:18px;height:18px;fill:currentColor}
.pvid{position:fixed;inset:0;z-index:60;background:rgba(3,12,22,.86);display:flex;flex-direction:column;
  align-items:center;justify-content:center;gap:12px;padding:16px}
.pvid canvas{height:min(76vh,calc((100vw - 32px) * 16 / 9));aspect-ratio:9/16;border-radius:16px;
  box-shadow:0 20px 60px rgba(0,0,0,.5);background:#012E45}
.pvid .bar{display:flex;gap:8px;flex-wrap:wrap;justify-content:center}
.pvid .btn{flex:0 0 auto;padding:11px 18px}
.pvid .ghost{color:#fff;border-color:rgba(255,255,255,.35)}
.pvid .pmsg{color:#BFD8E6;text-align:center}
.pcal{list-style:none;margin:0;padding:0}
.pcal li{padding:12px 0;border-top:1px solid var(--line)}
.pcal li:first-child{border-top:0}
.pcal a{display:flex;align-items:center;gap:10px;color:inherit;text-decoration:none}
.pcal a:hover b{text-decoration:underline}
.pcal .pi{flex:1;min-width:0}
.pcal b{display:block;font-size:.98rem}
.pcal small{display:block;color:var(--mute);font-size:.8rem}
.pcal .pgo{flex:0 0 auto;font-weight:800;font-size:.84rem;color:var(--brand-text);white-space:nowrap}
.prulelist{margin:0;padding-inline-start:1.3em}
.prulelist li{margin:0 0 8px}
"""


def render():
    """الصفحة كاملة ← (رمز HTTP، بايتات، مدة الكاش بالثواني)."""
    data, at, error = _feed.get()
    site, url = guide_pages.SITE, guide_pages.SITE + PATH
    title = f"نتائج {CUP['name']} {CUP['season']} — {CUP['level']} ومباريات اليوم | سمارت سوق"
    h1 = f"{CUP['name']} {CUP['season']} — {CUP['level']}"
    ms = data["matches"] if data else []
    desc = (f"نتائج مباريات {CUP['level']} في {CUP['name']} {CUP['season']} أولًا بأول، ومواعيد المباريات "
            f"القادمة بتوقيت السعودية، وترتيب {CUP['groups_word']}.{_lead(ms)}")
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
        pz = _contests(ms)
        sections = []
        if todays:
            sections.append(("today", "مباريات اليوم", _by_day(todays, pz=pz)))
        if results:
            sections.append(("results", "النتائج", _by_day(results, newest_first=True, pz=pz)))
        if upcoming:
            sections.append(("upcoming", "المباريات القادمة", _by_day(upcoming, pz=pz)))
        groups = {"league": CUP["level"], "groups": data["groups"], "zones": ZONES}
        if data["groups"]:
            sections.append(("groups", "ترتيب المجموعات", league.tables_html(groups)))
        chips = "".join(f'<a href="#{k}">{t}</a>' for k, t, _ in sections)
        cards = []
        for i, (k, t, body) in enumerate(sections):
            cards.append(f'<section class="card" id="{k}" aria-labelledby="{k}-h"><h2 id="{k}-h">{t}</h2>{body}</section>')
            if i == 0:
                cards.append(_ad("cup-ad-inline"))
        body = (_banner(ms, pz) + f'<nav class="ltabs" aria-label="أقسام الصفحة">{chips}</nav>' + "".join(cards)
                + f'<p class="lsrc">آخر تحديث: <time datetime="{datetime.datetime.fromtimestamp(at, RIYADH).isoformat()}">'
                f'{league._when(at)}</time> بتوقيت السعودية · يُحدَّث تلقائيًا · المصدر ESPN</p>')
    else:
        body = ('<section class="card"><p>تعذّر تحميل المباريات الآن، ونعيد المحاولة تلقائيًا. '
                'حدّث الصفحة بعد دقائق.</p></section>' + _ad("cup-ad-inline"))

    main = (f'<h1>{_esc(h1)}</h1>\n<p class="sub">نتائج المباريات أولًا بأول، ومواعيد القادمة بتوقيت '
            f'السعودية، وترتيب {CUP["groups_word"]}.</p>\n<p class="sub"><a class="link" href="{league.WATCH}'
            f'{PATH.strip("/")}">مشاهدة {_esc(CUP["name"])}: القنوات الناقلة ومباريات اليوم ←</a></p>')
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
            + (f'<p class="when tvline">{TV_ICON}القناة الناقلة: <b dir="ltr">{_esc(tv_name)}</b></p>'
               if (tv_name := contest.channel_for(channels(), m["id"], PATH)) else "")
            + (f'<p class="when">الملعب: <span dir="auto">{_esc(place)}</span></p>' if place else "") + "</section>")
    parts = [hero]
    pz = _contests(data["matches"])
    if m["id"] in pz:
        parts.append(_predict_card(m, *pz[m["id"]]))
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
                     + _by_day(others, pz=pz) + "</section>")
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


CLOCKS = "🕛🕐🕑🕒🕓🕔🕕🕖🕗🕘🕙🕚"
# رمز الدولة في شعار ESPN (…/countries/500/ksa.png) ← رمزها في ISO؛ ومنه علمها رمزًا تعبيريًّا
FLAG_CODES = {
    "ksa": "SA", "irq": "IQ", "oma": "OM", "kuw": "KW", "uae": "AE", "yem": "YE", "qat": "QA", "bhr": "BH",
    "jor": "JO", "syr": "SY", "leb": "LB", "pal": "PS", "egy": "EG", "mar": "MA", "alg": "DZ", "tun": "TN",
    "lby": "LY", "sud": "SD", "irn": "IR", "jpn": "JP", "kor": "KR", "chn": "CN", "aus": "AU", "uzb": "UZ",
    "ind": "IN", "idn": "ID", "tha": "TH", "vie": "VN", "mas": "MY", "phi": "PH", "prk": "KP", "kgz": "KG",
    "tjk": "TJ", "tkm": "TM", "afg": "AF", "pak": "PK", "sin": "SG", "hkg": "HK", "bra": "BR", "arg": "AR",
    "usa": "US", "mex": "MX", "can": "CA", "uru": "UY", "col": "CO", "chi": "CL", "sen": "SN", "nga": "NG",
    "alb": "AL", "and": "AD", "arm": "AM", "fifa.armenia": "AM", "aut": "AT", "aze": "AZ", "bel": "BE",
    "bih": "BA", "blr": "BY", "bul": "BG", "cro": "HR", "cyp": "CY", "cze": "CZ", "den": "DK", "esp": "ES",
    "est": "EE", "fin": "FI", "fra": "FR", "fro": "FO", "geo": "GE", "ger": "DE", "gib": "GI", "gre": "GR",
    "hun": "HU", "irl": "IE", "isl": "IS", "isr": "IL", "ita": "IT", "kaz": "KZ", "kosovo": "XK", "kos": "XK",
    "lie": "LI", "ltu": "LT", "lux": "LU", "lva": "LV", "mda": "MD", "mkd": "MK", "mlt": "MT", "mtg": "ME",
    "mne": "ME", "ned": "NL", "nor": "NO", "pol": "PL", "por": "PT", "rom": "RO", "rou": "RO", "sba": "RS",
    "srb": "RS", "smr": "SM", "sui": "CH", "svk": "SK", "svn": "SI", "swe": "SE", "tur": "TR", "ukr": "UA",
    "rus": "RU",
}
SUBFLAGS = {"eng": "gbeng", "sco": "gbsct", "wal": "gbwls"}      # أعلام إنجلترا واسكتلندا وويلز


def flag(logo):
    """علم المنتخب رمزًا تعبيريًّا من رابط شعاره عند ESPN (‏ksa ← 🇸🇦)، أو فارغ لما لا يُعرف."""
    m = re.search(r"/countries/500/([a-z0-9_.-]+)\.png", str(logo or ""))
    if not m:
        return ""
    code = m.group(1)
    if code in SUBFLAGS:
        return "\U0001F3F4" + "".join(chr(0xE0000 + ord(ch)) for ch in SUBFLAGS[code]) + "\U000E007F"
    iso = FLAG_CODES.get(code, "")
    return "".join(chr(0x1F1E6 + ord(ch) - 65) for ch in iso)


def _mins(n):
    return f"{n} دقائق" if 3 <= n <= 10 else f"{n} دقيقة"


def _clock_word(ts):
    """«8:30 مساءً»: الساعة في رسالة القناة بكلمتها لا بحرفها."""
    t = datetime.datetime.fromtimestamp(ts, RIYADH)
    return f"{t.hour % 12 or 12}:{t.minute:02d} {'صباحًا' if t.hour < 12 else 'مساءً'}"


def announcement(rows, now=None):
    """رسالة «تحدّي التوقعات» للقناة بصيغة المتجر، جاهزةً للنسخ من صفحة المدير: المباريات المفتوحة للتوقّع
    بأعلام منتخبيها وموعدها وقناتها (ورابط كلٍّ منها إن كانت أكثر من واحدة)، والجائزة وعدد الفائزين،
    والشروط، ورابط صفحة التحدي (صفوف contest.admin_rows). ولا مسابقة مفتوحة ← نصٌّ فارغ."""
    now = time.time() if now is None else now
    ms = sorted((r for r in rows if r.get("state") == "open" and r.get("contest")), key=lambda r: r["match"]["ts"])
    if not ms:
        return ""
    today, single = _day(now), len(ms) == 1
    one_day = len({_day(r["match"]["ts"]) for r in ms}) == 1

    def when(ts):                                  # الليلة · اليوم · الغد · الخميس 1 أكتوبر
        d = _day(ts)
        return (("الليلة" if datetime.datetime.fromtimestamp(ts, RIYADH).hour >= 17 else "اليوم") if d == today
                else "الغد" if d == today + datetime.timedelta(days=1)
                else f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}")

    def at(ts):                                    # 🕗 الساعة 8:30 مساءً — ويومها قبلها إن اختلفت الأيام
        clock = CLOCKS[datetime.datetime.fromtimestamp(ts, RIYADH).hour % 12]
        return f"{clock} {'' if one_day else when(ts) + ' '}الساعة {_clock_word(ts)}"

    def teams(r):
        mt = r["match"]
        fh, fa = flag(mt.get("home_logo")), flag(mt.get("away_logo"))
        return f"{fh + ' ' if fh else ''}{mt['home']} × {mt['away']}{' ' + fa if fa else ''}"

    def link(r):                                   # رابطٌ خاص بالمباراة: بطاقة التوقّع فيها مباشرةً
        slug, path = r["match"].get("slug"), contest.cup_path(r["match"])
        return f"{guide_pages.SITE}{path}/{slug}#predict" if slug else f"{guide_pages.SITE}{path}/predict"

    def cup(r):
        return r["match"].get("cup") or contest.DEFAULT_CUP

    mixed = len({cup(r) for r in ms}) > 1
    first = ms[0]["match"]["ts"]
    out = ["⚽🎉 تحدّي التوقعات مع سمارت سوق",
           f"شاركنا توقعك لنتيجة مباراة {when(first)}:" if single
           else f"شاركنا توقعك لنتائج مباريات {when(first)}:" if one_day else "شاركنا توقعك لنتائج هذه المباريات:"]
    for r in ms:                                   # مباراةٌ واحدة كما كتبها المتجر؛ وأكثر: كتلةٌ لكلٍّ برابطها
        block = [teams(r)] + ([f"🏆 {cup(r)}"] if mixed else []) + [at(r["match"]["ts"])]
        if r.get("tv"):
            block.append(f"📺 القناة الناقلة: {r['tv']}")
        out += block if single else ["", *block, f"🔗 {link(r)}"]
    if not single:
        out.append("")

    def picked(w):                                 # «سيتم اختيار …»
        return "فائز واحد" if w == 1 else "فائزَين" if w == 2 else f"{w} فائزين"

    prizes = [(r["contest"].get("prize") or "[اكتب الجائزة هنا]", int(r["contest"].get("winners") or 1)) for r in ms]
    out.append("💬 اكتب توقعك للنتيجة في التعليقات أو في صفحة التحدي.")
    if len(set(prizes)) == 1:
        prize, w = prizes[0]
        gets = "ويحصل على:" if w == 1 else "ويحصل كلٌّ منهما على:" if w == 2 else "ويحصل كلٌّ منهم على:"
        out += [f"🎁 سيتم اختيار {picked(w)}{'' if single else ' في كل مباراة'} وفق شروط المسابقة المعلنة، {gets}",
                f"⭐ {prize}"]
    else:
        out.append("🎁 سيتم اختيار الفائزين وفق شروط المسابقة المعلنة، والجوائز:")
        out += [f"⭐ {r['match']['home']} × {r['match']['away']}: {prize}"
                + ("" if w == 1 else " — فائزان" if w == 2 else f" — {w} فائزين") for r, (prize, w) in zip(ms, prizes)]
    many = not single or prizes[0][1] > 1
    out += ["📌 شروط المشاركة:", "✅ المشاركة متاحة للجميع",
            "✅ توقع واحد فقط لكل مشارك" + ("" if single else " في كل مباراة"),
            f"✅ يتم الإعلان عن {'الفائزين' if many else 'الفائز'} بعد نهاية {'المباراة' if single else 'كل مباراة'}",
            "✅ لا يوجد أي رسوم أو شراء مطلوب للمشاركة",
            "للتفاصيل:", f"🔗 {link(ms[0]) if single else guide_pages.SITE + '/predict'}",   # صفحة المسابقات للبطولتين
            f"🔥 شارك توقعك واستمتع بأجواء {'المباراة' if single else 'المباريات'}!"]
    return "\n".join(out)


def sitemap():
    """صفحة البطولة وصفحات مبارياتها لخريطة الموقع."""
    data = _feed.get()[0]
    return ([(PATH, "daily", "0.8")]
            + [(url(m), "daily", "0.6") for m in (data or {}).get("matches", [])])


WIDGET_ROWS = 4
WIDGET_CSS = """
body{background:transparent}
main{max-width:1100px;padding:2px 2px 14px}
.wcard{margin:0}
.wtop{display:flex;align-items:center;gap:12px;padding:12px 14px;margin:-4px -4px 14px;border-radius:14px;
  background:linear-gradient(200deg,var(--brand) 0%,#012E45 100%);color:#fff;text-decoration:none}
.wtop svg{width:30px;height:30px;flex:0 0 auto;stroke:#FFD79A;fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.wtop b{display:block;font-size:1.05rem;line-height:1.35}
.wtop small{display:block;color:#BFD8E6;font-size:.76rem}
.wtop .all{margin-inline-start:auto;flex:0 0 auto;font-size:.8rem;font-weight:700;color:#FFD79A;white-space:nowrap}
.wcols{display:grid;gap:14px}
.wcols h2{font-size:1rem;margin:0 0 6px}
@media (min-width:720px){.wcols{grid-template-columns:1fr 1fr;gap:24px}}
"""
BALL = ('<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/>'
        '<path d="m12 7 3.6 2.6-1.4 4.2H9.8L8.4 9.6z"/><path d="M12 3v4M4.2 9.6l3.9 1.4M6.9 19l2.6-3.4M17.1 19l-2.6-3.4M19.8 9.6l-3.9 1.4"/></svg>')


def render_widget(theme=""):
    """النسخة المدمجة في رئيسية متجر سلة (‏/nations-league/widget داخل iframe في قسم «محتوى
    HTML»): مباريات اليوم والقادمة — بلا «آخر النتائج» (طلب المتجر) — ورابط الصفحة كاملة.
    خلفيتها شفافة، ووضعها **كوضع المتجر**: المتجر (قالب رائد) يتبع إعداد جهاز الزائر،
    والإطار يرى الإعداد نفسه فتتبعه الأنماط (prefers-color-scheme) نهاريةً أو ليلية، إلا
    إن فُرض ?theme=light أو dark. ولا تُعلن color-scheme: لو اختلف عن وضع صفحة المتجر
    لرسم المتصفح خلف الإطار خلفيةً معتمة بدل الشفافة. وروابطها تُفتح في نافذة جديدة،
    وتبلّغ الصفحة الحاضنة بطولها فيتّسع الإطار لها بلا تمرير داخلي. ← (رمز، بايتات، مدة الكاش)."""
    data = _feed.get()[0]
    ms = data["matches"] if data else []
    today = _day(time.time())
    todays = [m for m in ms if _day(m["ts"]) == today or m["state"] == "in"]
    upcoming = [m for m in ms if m["state"] == "pre" and m not in todays]
    cols = ([("مباريات اليوم", todays[:WIDGET_ROWS]), ("المباريات القادمة", upcoming[:WIDGET_ROWS])] if todays
            else [("المباريات القادمة", upcoming[:2 * WIDGET_ROWS])])
    pz = _contests(ms)
    body = ("".join(f"<div><h2>{t}</h2>{_by_day(rows, new_tab=True, pz=pz)}</div>" for t, rows in cols if rows) if ms
            else '<p class="sub">تعذّر تحميل المباريات الآن، ونعيد المحاولة تلقائيًا.</p>')
    live = any(m["state"] == "in" for m in ms)
    doc = f"""<!doctype html>
<html lang="ar" dir="rtl"{f' data-theme="{theme}"' if theme in ("light", "dark") else ""}>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(CUP['name'])} — {_esc(CUP['level'])} | سمارت سوق</title>
<meta name="robots" content="noindex">
{'<meta http-equiv="refresh" content="60">' if live else ''}
<link rel="canonical" href="{guide_pages.SITE}{PATH}">
<link rel="preconnect" href="{league.LOGO_HOST}">
<style>{guide_pages._style()}
{CSS}
{WIDGET_CSS}</style>
</head>
<body>
<main>
<section class="card wcard">
<a class="wtop" href="{PATH}" target="_blank" rel="noopener">{BALL}<span><b>{_esc(CUP['name'])}</b>
<small>{_esc(CUP['level'])} · {_esc(CUP['season'])}</small></span><span class="all">كل النتائج ←</span></a>
{_banner(ms, pz, new_tab=True)}
<div class="wcols">{body}</div>
<p class="lsrc">يُحدَّث تلقائيًا · المصدر ESPN</p>
</section>
</main>
<script>
(function(){{function h(){{parent.postMessage({{ssouqWidget:Math.ceil(document.documentElement.getBoundingClientRect().height)}},"*")}}
addEventListener("load",h);if(window.ResizeObserver)new ResizeObserver(h).observe(document.body);}})();
</script>
</body>
</html>"""
    return (200 if ms else 503), doc.encode("utf-8"), (LIVE_TTL if live else 300)


HUB_ROWS = 6                                         # القادمة لكل بطولة في «المباريات القادمة»
HUB_CSS = """
.whead{display:flex;align-items:center;gap:12px;padding:12px 14px;margin:-4px -4px 14px;border-radius:14px;
  background:linear-gradient(200deg,var(--brand) 0%,#012E45 100%);color:#fff}
.whead svg{width:30px;height:30px;flex:0 0 auto;stroke:#FFD79A;fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.whead b{display:block;font-size:1.05rem;line-height:1.35}
.whead small{display:block;color:#BFD8E6;font-size:.76rem}
.wcup h2{display:flex;align-items:baseline;justify-content:space-between;gap:8px;font-size:1rem;margin:0 0 6px}
.wcup h2 a{font-size:.8rem;font-weight:700;white-space:nowrap}
.wnone{margin:0 0 6px}
.wmore{margin-top:14px}
.wmore>summary{list-style:none;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:8px;
  padding:11px 14px;border-radius:12px;border:1px solid var(--line);background:var(--soft);font-weight:800;
  color:var(--brand-text);user-select:none}
.wmore>summary::-webkit-details-marker{display:none}
.wmore>summary svg{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:2.2;stroke-linecap:round;
  stroke-linejoin:round;transition:transform .2s}
.wmore[open]>summary svg{transform:rotate(180deg)}
.wmore>summary .n{font-weight:600;color:var(--mute);font-size:.8rem}
.wmore>.wcols,.wmore>.wone{margin-top:14px}
"""
CHEVRON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>'


def render_hub(cups, theme=""):
    """ودجت رئيسية متجر سلة لأكثر من بطولة (كأس الخليج ودوري الأمم): مباريات اليوم من كلٍّ — والجارية
    دائمًا — بقنواتها، وأقرب مسابقةٍ مفتوحة، و«المباريات القادمة» زرٌّ يفتحها (‏<details>، بلا سكربت).
    الإطار يتّسع معها: الصفحة تبلّغ الحاضنة بطولها كلما تغيّر. وبلا مباريات اليوم تُفتح القادمة وحدها.
    والوضع والشفافية ونافذة الروابط كـ render_widget. ← (رمز، بايتات، مدة الكاش)."""
    today = _day(time.time())
    todays, ups, live, banner, any_ms = [], [], False, None, False
    for c in cups:
        ms = (c._feed.get()[0] or {}).get("matches", [])
        any_ms = any_ms or bool(ms)
        pz = c._contests(ms)
        t = [m for m in ms if c._day(m["ts"]) == today or m["state"] == "in"]
        u = [m for m in ms if m["state"] == "pre" and m not in t][:HUB_ROWS]
        live = live or any(m["state"] == "in" for m in ms)
        head = (f'<h2><span>{_esc(c.CUP["name"])}</span><a href="{c.PATH}" target="_blank" rel="noopener">'
                f'كل النتائج ←</a></h2>')
        if t:
            todays.append(f'<div class="wcup">{head}<ul class="matches">'
                          + "".join(c._row(m, True, pz) for m in t) + "</ul></div>")
        if u:
            ups.append((len(u), f'<div class="wcup">{head}{c._by_day(u, new_tab=True, pz=pz)}</div>'))
        opens = [m for m in ms if pz.get(m["id"], (None, ""))[1] == "open"]
        if opens:
            m = min(opens, key=lambda x: x["ts"])
            if banner is None or m["ts"] < banner[0]:
                banner = (m["ts"], c._banner(opens, pz, new_tab=True))
    names = " · ".join(c.CUP["name"] for c in cups)
    if not any_ms:
        body = '<p class="sub">تعذّر تحميل المباريات الآن، ونعيد المحاولة تلقائيًا.</p>'
    else:
        cols = lambda xs: f'<div class="{"wcols" if len(xs) > 1 else "wone"}">{"".join(xs)}</div>'   # عمودان لبطولتين
        body = cols(todays) if todays else '<p class="sub wnone">لا مباريات اليوم — أقرب المباريات تحت.</p>'
        if ups:
            n = sum(k for k, _ in ups)
            body += (f'<details class="wmore" id="more"{"" if todays else " open"}><summary>المباريات القادمة '
                     f'<span class="n">({n})</span>{CHEVRON}</summary>'
                     f'{cols([h for _, h in ups])}</details>')
    doc = f"""<!doctype html>
<html lang="ar" dir="rtl"{f' data-theme="{theme}"' if theme in ("light", "dark") else ""}>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>مباريات اليوم — {_esc(names)} | سمارت سوق</title>
<meta name="robots" content="noindex">
{'<meta http-equiv="refresh" content="60">' if live else ''}
<link rel="canonical" href="{guide_pages.SITE}{cups[0].PATH}">
<link rel="preconnect" href="{league.LOGO_HOST}">
<style>{guide_pages._style()}
{CSS}
{WIDGET_CSS}
{HUB_CSS}</style>
</head>
<body>
<main>
<section class="card wcard">
<div class="whead">{BALL}<span><b>مباريات اليوم</b><small>{_esc(_day_label(today))} · {_esc(names)}</small></span></div>
{banner[1] if banner else ""}
{body}
<p class="lsrc">بتوقيت السعودية · يُحدَّث تلقائيًا · المصدر ESPN</p>
</section>
</main>
<script>
(function(){{function h(){{parent.postMessage({{ssouqWidget:Math.ceil(document.documentElement.getBoundingClientRect().height)}},"*")}}
addEventListener("load",h);if(window.ResizeObserver)new ResizeObserver(h).observe(document.body);
var d=document.getElementById("more");if(d){{try{{if(sessionStorage.getItem("ssouqMore")==="1")d.open=true}}catch(e){{}}
d.addEventListener("toggle",function(){{try{{sessionStorage.setItem("ssouqMore",d.open?"1":"0")}}catch(e){{}}h()}})}}}})();
</script>
</body>
</html>"""
    return (200 if any_ms else 503), doc.encode("utf-8"), (LIVE_TTL if live else 300)

# ---------- نسخةٌ لبطولةٍ أخرى ----------
# كأس الخليج العربي 2026 (خليجي 27 في السعودية): مجموعتان من أربعة منتخبات، يتأهل الأول والثاني من
# كلٍّ إلى نصف النهائي، ثم النهائي. رمزها عند ESPN ‏global.gulf_cup.
GULF = dict(
    PATH="/gulf-cup",
    CUP=dict(code="global.gulf_cup", years=("2026",), name="كأس الخليج العربي", level="خليجي 27", season="2026",
             group="Group", knockout=("semifinals", "3rd-place-match", "final"), playoffs=None,
             groups_word="المجموعتين", tv="AL KASS"),       # الكأس القطرية تنقل مبارياتها (One وTwo)
    RANK_ZONES={1: "sf", 2: "sf"},
    ZONES={"sf": {"label": "التأهل إلى نصف النهائي", "color": "#16A34A"}},
    UTM_CAMPAIGN="gulf-cup",
)


def instance(name, **cfg):
    """نسخةٌ مستقلة من هذه الوحدة لبطولةٍ أخرى — كاشها وملخّصاتها وصفحاتها — بإعدادها (PATH وCUP
    ومناطق الترتيب وحملة الروابط)، ومسار مسابقتها منه. يصنعها الخادم مرةً عند إقلاعه."""
    spec = importlib.util.spec_from_file_location(name, os.path.abspath(__file__))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for k, v in cfg.items():
        setattr(mod, k, v)
    mod.PREDICT = mod.PATH + "/predict"
    sys.modules[name] = mod
    return mod

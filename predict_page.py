# -*- coding: utf-8 -*-
"""صفحة مسابقة التوقّعات (‏/predict) للبطولات كلها — كأس الخليج العربي ودوري الأمم الأوروبية.

ليلية التصميم افتراضًا (ملعبٌ ليلًا وكأسٌ ذهبية) وتتبدّل إلى النهاري بزرّ يُحفظ في المتصفح، ومصمَّمة
للجوال أولًا: شريطٌ علويّ بالأقسام، وواجهةٌ بالكأس وزرّ «كيف أشارك؟» وثلاث بطاقات (الجوائز، والخطوات،
وعدد التوقّعات الحقيقي)، ثم أزرار تصفية (الكل · مفتوحة للتوقّع · جارية الآن · منتهية)، ثم بطاقةٌ لكل
مسابقة: بطولتها، والمنتخبان بعلميهما، والموعد والقناة الناقلة، وزرّ «شارك الآن» إلى بطاقة التوقّع في
صفحة المباراة (أو حالها: مغلقة، بانتظار الفرز، النتيجة والفائز)، والجائزة بصورتها ورابطها. وبعدها
الفائزون، و«كيف أشارك؟» بخطواتها، والشروط وطريقة الفرز بالأرقام.

البيانات كلها من الخادم عند الطلب (المسابقات وقنواتها ومباريات ESPN من كاش البطولات)، والصفحة
مخزَّنةٌ دقيقة؛ والتصفية وتوقّع الزائر نفسه («توقّعك: 2-0» من متصفحه) بسكربتٍ صغير لا تتوقف الصفحة عليه.
"""
import datetime
import json
import time

import contest
import guide_pages
import league
import tournament
from league import RIYADH, _esc

PATH = "/predict"
STORE = "https://ssouq.com/?utm_source=guide.ssouq.com&utm_medium=referral&utm_campaign=contest"
TABS = [("all", "كل المسابقات"), ("open", "مفتوحة للتوقّع"), ("live", "جارية الآن"), ("done", "منتهية")]
TAB_OF = {"open": "open", "hold": "open", "closed": "live", "pending": "live", "done": "done", "void": "done"}

# أيقونات خطّية بلون النص (‏stroke)، والكأس الكبيرة بتدرّجٍ ذهبي
ICON = {
    "trophy": '<path d="M8 21h8M12 17v4M7 4h10v4a5 5 0 0 1-10 0V4zM7 6H4a3 3 0 0 0 3 4M17 6h3a3 3 0 0 1-3 4"/>',
    "ball": '<circle cx="12" cy="12" r="9"/><path d="m12 7 3.6 2.6-1.4 4.2H9.8L8.4 9.6z"/>'
            '<path d="M12 3v4M4.2 9.6l3.9 1.4M6.9 19l2.6-3.4M17.1 19l-2.6-3.4M19.8 9.6l-3.9 1.4"/>',
    "gift": '<path d="M20 12v9H4v-9M2 7h20v5H2zM12 21V7"/>'
            '<path d="M12 7H7.5a2.5 2.5 0 1 1 0-5C11 2 12 7 12 7zM12 7h4.5a2.5 2.5 0 1 0 0-5C13 2 12 7 12 7z"/>',
    "chart": '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
             '<path d="M22 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "tv": '<rect x="3" y="7" width="18" height="12" rx="2"/><path d="m8 3 4 4 4-4"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "live": '<circle cx="12" cy="12" r="2"/><path d="M16.2 7.8a6 6 0 0 1 0 8.4M7.8 16.2a6 6 0 0 1 0-8.4M19 5a10 10 0 0 1 0 14M5 19A10 10 0 0 1 5 5"/>',
    "cal": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "check": '<path d="m5 12 5 5 9-10"/>',
    "fire": '<path d="M12 22c4 0 7-3 7-7 0-4-3-6-4-10-2 2-3 4-3 6-1-1-2-2-2-4-3 2-5 5-5 8 0 4 3 7 7 7z"/>',
    "wa": '<path d="M12 3a9 9 0 0 0-7.8 13.5L3 21l4.6-1.2A9 9 0 1 0 12 3z"/>'
          '<path d="M9 9.5c0 3 2.5 5.5 5.5 5.5l1.2-1.4-1.9-1-1 .8a4.2 4.2 0 0 1-2-2l.8-1-1-1.9z"/>',
    "q": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .9-1 1.7M12 17h.01"/>',
    "moon": '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "store": '<path d="M3 9l1.5-5h15L21 9M4 9v11h16V9M3 9h18M9 20v-6h6v6"/>',
    "arrow": '<path d="m15 18-6-6 6-6"/>',
}


def _i(name, cls="i"):
    return f'<svg class="{cls}" viewBox="0 0 24 24" aria-hidden="true">{ICON[name]}</svg>'


TROPHY = """<svg class="cup" viewBox="0 0 220 240" aria-hidden="true"><defs>
<linearGradient id="tg" x1="0" x2="1"><stop offset="0" stop-color="#7A4D0C"/><stop offset=".3" stop-color="#FFE08A"/>
<stop offset=".55" stop-color="#F4B73E"/><stop offset=".8" stop-color="#C98A1C"/><stop offset="1" stop-color="#6E450A"/></linearGradient>
<linearGradient id="tb" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#3A2A10"/><stop offset="1" stop-color="#15100A"/></linearGradient>
<radialGradient id="tglow" cx=".5" cy=".42" r=".5"><stop offset="0" stop-color="#FFD27A" stop-opacity=".6"/>
<stop offset="1" stop-color="#FFD27A" stop-opacity="0"/></radialGradient></defs>
<circle cx="110" cy="100" r="104" fill="url(#tglow)"/>
<path d="M64 52c-34 2-38 50 4 58M156 52c34 2 38 50-4 58" fill="none" stroke="url(#tg)" stroke-width="11" stroke-linecap="round"/>
<path d="M58 30h104v38c0 44-24 72-52 76-28-4-52-32-52-76z" fill="url(#tg)"/>
<path d="M74 40h14v30c0 26 10 44 22 52-20-4-36-24-36-52z" fill="#FFF3C4" opacity=".35"/>
<path d="M100 144h20l4 30h-28z" fill="url(#tg)"/>
<rect x="72" y="172" width="76" height="16" rx="4" fill="url(#tg)"/>
<rect x="62" y="188" width="96" height="30" rx="6" fill="url(#tb)"/>
<rect x="84" y="197" width="52" height="12" rx="3" fill="url(#tg)" opacity=".85"/>
<path d="M110 70l6 12 13 2-9 9 2 13-12-6-12 6 2-13-9-9 13-2z" fill="#FFF6D6" opacity=".9"/></svg>"""


def _big(logo):
    """شعار المنتخب بمقاسٍ يكفي دائرة البطاقة على شاشات الجوال الحادة."""
    return str(logo or "").replace("&w=48&h=48", "&w=96&h=96")


def _when(ts):
    return tournament.when_label(ts) if ts else ""


def _cards(cups, summ, tv, now):
    """بطاقات المسابقات مرتّبةً: المفتوحة بموعدها، ثم الجارية، ثم المنتهية الأحدث أولًا."""
    feed = {}
    for c in cups:
        for m in (c._feed.get()[0] or {}).get("matches", []):
            feed[m["id"]] = m
    rows = contest.listing(summ, list(feed.values()), now)
    today, out = tournament._day(now), []
    for r in rows:
        s, mt, st = summ.get(r["eid"]) or {}, r["match"], r["state"]
        m = feed.get(r["eid"])
        path = contest.cup_path(mt)
        href = f"{path}/{mt.get('slug') or r['eid']}#predict"
        ts = mt.get("ts") or 0
        live = bool(m and m["state"] == "in")
        # الوسط: × قبل البداية، والنتيجة الحيّة أو النهائية بعدها
        if st == "done" and r.get("score"):
            mid = f'<span class="sc">{r["score"][0]}<i>-</i>{r["score"][1]}</span>'
        elif m and m["state"] in ("in", "post"):
            mid = f'<span class="sc{" live" if live else ""}">{m["home"]["score"]}<i>-</i>{m["away"]["score"]}</span>'
        else:
            mid = '<span class="vs">×</span>'
        day = tournament._day(ts) if ts else None
        badge = ""
        if st == "open" and day == today:
            night = datetime.datetime.fromtimestamp(ts, RIYADH).hour >= 17
            badge = f'<span class="bdg hot">{_i("fire")}{"مباراة الليلة" if night else "مباراة اليوم"}</span>'
        elif st == "open" and day and day == today + datetime.timedelta(days=1):
            badge = f'<span class="bdg">{_i("cal")}غدًا</span>'
        elif live:
            badge = '<span class="bdg red"><i class="dot"></i>مباشر الآن</span>'
        elif st == "pending":
            badge = f'<span class="bdg">{_i("clock")}بانتظار الفرز</span>'
        w = int(s.get("winners") or 1)
        if st == "open":
            closes = r.get("closes") or ts
            cta = (f'<a class="cta go" href="{_esc(href)}">شارك الآن {_i("arrow")}</a>'
                   + (f'<small class="closes">التوقّع مفتوحٌ حتى {_esc(tournament._clock(closes))} — بعد صافرة البداية بـ '
                      f'{_esc(tournament._mins(int(round((closes - ts) / 60))))}</small>' if closes > ts else ""))
        elif st == "hold":
            cta = f'<span class="cta shut">{_i("clock")}موقوفة حتى يُعلن موعد المباراة</span>'
        elif st in ("closed", "pending"):
            cta = (f'<span class="cta shut">{_i("lock")}المسابقة مغلقة'
                   f'{" — الفرز بعد صافرة النهاية" if st == "closed" else " — الفرز خلال دقائق"}</span>'
                   f'<a class="more" href="{_esc(href)}">تابع المباراة ←</a>')
        elif st == "done":
            won = r.get("won") or []
            res = (f'<p class="won">{_i("trophy")}{"الفائزون" if len(won) > 1 else "الفائز"}: '
                   f'<b>{_esc("، ".join(won))}</b></p>' if won else
                   '<p class="won none">لم يُصب أحدٌ النتيجة بالضبط، فلا فائز.</p>'
                   if contest.mode_of(s) == "exact" else '<p class="won none">لا فائز في هذه المباراة.</p>')
            cta = res + f'<a class="cta ghost" href="{_esc(href)}">{_i("chart")}عرض النتيجة وفيديو الفرز</a>'
        else:
            cta = '<span class="cta shut">أُلغيت المباراة فلا فرز</span>'
        meta = [f'{_i("clock")}<span>{_esc(_when(ts))}</span>']
        if tv.get(r["eid"]):
            meta.append(f'{_i("tv")}<span dir="ltr">{_esc(tv[r["eid"]])}</span>')
        img = (f'<img src="{_esc(s["prize_img"])}" alt="" width="52" height="52" loading="lazy">'
               if s.get("prize_img") else f'<span class="gi">{_i("gift")}</span>')
        many = f'<small class="w">لـ{"فائزَين" if w == 2 else f"{w} فائزين"}</small>' if w > 1 else ""
        prize = (f'<span class="pl">الجائزة</span><b>{_esc(s.get("prize") or r.get("prize") or "")}</b>{many}')
        prize_box = (f'<a class="prz" href="{_esc(s["prize_url"])}" target="_blank" rel="noopener">{img}<span>{prize}'
                     f'<small class="lnk">صفحة الاشتراك ←</small></span></a>' if s.get("prize_url")
                     else f'<div class="prz">{img}<span>{prize}</span></div>')
        count = int(s.get("count") or r.get("count") or 0)

        def team(name, logo, away=False):
            fl = (f'<img class="fl" src="{_esc(_big(logo))}" alt="" width="46" height="46" loading="lazy">'
                  if logo else '<i class="fl"></i>')
            return f'<span class="tm{" away" if away else ""}">{fl}<b dir="auto">{_esc(name)}</b></span>'

        out.append((TAB_OF.get(st, "done"), (
            f'<article class="mc {st}{" hot" if "hot" in badge else ""}" data-tab="{TAB_OF.get(st, "done")}" data-m="{_esc(r["eid"])}">'
            f'<div class="mcm"><div class="mtop"><span class="cupn">{_i("trophy")}{_esc(mt.get("cup") or contest.DEFAULT_CUP)}'
            f'<small>{_esc(mt.get("stage") or "")}</small></span>{badge}</div>'
            f'<a class="teams" href="{_esc(href)}">{team(mt.get("home"), mt.get("home_logo"))}{mid}'
            f'{team(mt.get("away"), mt.get("away_logo"), True)}</a>'
            f'<p class="meta">{"".join(f"<span>{x}</span>" for x in meta)}</p>'
            f'<div class="act">{cta}</div>'
            f'<p class="mine" hidden></p>'
            f'<p class="cnt">{contest_count(count)}</p></div>{prize_box}</article>')))
    return out


def contest_count(n):
    if not n:
        return "كن أول من يتوقّع"
    return f"{n:,} توقّعًا حتى الآن" if n > 10 else ("توقّعٌ واحد" if n == 1 else "توقّعان" if n == 2 else f"{n} توقّعات")


def _winners(summ, limit=8):
    """آخر الفائزين: الاسم الأول، والمباراة، والجائزة."""
    done = sorted((s for s in summ.values() if s.get("draw") and s.get("won")),
                  key=lambda s: -(s.get("match") or {}).get("ts", 0))[:limit]
    items = []
    for s in done:
        mt = s.get("match") or {}
        for name in s["won"]:
            items.append(f'<li>{_i("trophy")}<span><b>{_esc(name)}</b><small>{_esc(mt.get("home", ""))} × '
                         f'{_esc(mt.get("away", ""))} · {_esc(s.get("prize") or "")}</small></span></li>')
    return items[:limit]


CSS = """
:root{--pg:#22C58B;--pg2:#12A873;--pg-ink:#04261A;--red:#EF4444}
body{background:var(--paper)}
.wrap{max-width:1040px;margin:0 auto;padding:0 14px 40px}
.i{width:18px;height:18px;flex:0 0 auto;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
/* الشريط العلوي */
.top{position:sticky;top:0;z-index:30;background:color-mix(in srgb,var(--card) 88%,transparent);backdrop-filter:blur(10px);
  border-bottom:1px solid var(--line)}
.top>div{max-width:1040px;margin:0 auto;padding:10px 14px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:10px;text-decoration:none;color:var(--ink);margin-inline-end:auto}
.brand .i{width:34px;height:34px;color:var(--gold);stroke-width:1.8}
.brand b{display:block;font-size:1.08rem;line-height:1.25}
.brand small{display:block;color:var(--mute);font-size:.74rem}
.nav{display:flex;gap:4px;order:3;width:100%;overflow-x:auto;scrollbar-width:none;margin:0 -4px}
.nav::-webkit-scrollbar{display:none}
.nav a{display:inline-flex;align-items:center;gap:6px;padding:7px 12px;border-radius:10px;color:var(--mute);
  text-decoration:none;font-weight:700;font-size:.88rem;white-space:nowrap}
@media (max-width:480px){.nav{justify-content:space-between}.nav a{padding:7px 7px;gap:4px;font-size:.82rem}.nav .i{width:16px;height:16px}}
.nav a:hover,.nav a.on{color:var(--ink);background:var(--soft)}
.nav a.on .i{color:var(--gold)}
.tbtn{width:42px;height:42px;border-radius:12px;border:1px solid var(--line);background:var(--soft);color:var(--ink);
  display:grid;place-items:center;cursor:pointer}
.tbtn .sun{display:none}
[data-theme="light"] .tbtn .sun{display:block}[data-theme="light"] .tbtn .moon{display:none}
@media (min-width:860px){.nav{order:0;width:auto;margin:0}}
/* الواجهة */
.hero{position:relative;overflow:hidden;margin:16px 0;border-radius:22px;padding:22px 18px 16px;color:#fff;
  border:1px solid rgba(120,170,230,.25);box-shadow:var(--shadow);
  background:radial-gradient(55% 60% at 12% -10%,rgba(150,200,255,.42),transparent 62%),
    radial-gradient(35% 45% at 70% -12%,rgba(255,214,150,.30),transparent 60%),
    radial-gradient(90% 55% at 50% 125%,rgba(34,197,139,.28),transparent 62%),
    repeating-radial-gradient(circle at 30% 18%,rgba(255,255,255,.07) 0 1px,transparent 1px 9px),
    linear-gradient(180deg,#0B2548 0%,#071427 100%)}
.hero .ht{position:relative;z-index:1;max-width:560px}
.hero h1{margin:0 0 8px;font-size:clamp(1.5rem,6vw,2.3rem);line-height:1.25;text-shadow:0 2px 12px rgba(0,0,0,.4)}
.hero p{margin:0 0 14px;color:#C9DBEE;font-size:.98rem}
.hero .cup{position:absolute;inset-inline-end:-14px;top:8px;width:118px;height:auto;opacity:.95;
  filter:drop-shadow(0 12px 22px rgba(0,0,0,.45))}
.hero .ht{padding-inline-end:92px}
@media (min-width:720px){.hero{padding:34px 34px 20px}.hero .cup{width:190px;inset-inline-end:40px;top:14px}
  .hero .ht{padding-inline-end:230px;min-height:196px;max-width:none}}
.gold{display:inline-flex;align-items:center;gap:8px;padding:10px 18px;border-radius:14px;font-weight:800;
  background:linear-gradient(180deg,#FFD27A,#F0A12B);color:#3A2907;text-decoration:none;box-shadow:0 6px 18px -8px rgba(240,161,43,.8)}
.feats{position:relative;z-index:1;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:22px}
.feat{display:flex;align-items:center;gap:10px;padding:10px;border-radius:14px;background:rgba(10,30,60,.55);
  border:1px solid rgba(120,170,230,.22);min-width:0}
.feat .ic{width:40px;height:40px;border-radius:50%;display:grid;place-items:center;flex:0 0 auto}
.feat .ic .i{width:20px;height:20px}
.feat b{display:block;font-size:.9rem;line-height:1.3}
.feat small{display:block;color:#A9C1DA;font-size:.72rem;line-height:1.35}
.feat:nth-child(1) .ic{background:rgba(244,114,182,.18);color:#F9A8D4}
.feat:nth-child(2) .ic{background:rgba(96,165,250,.18);color:#93C5FD}
.feat:nth-child(3) .ic{background:rgba(52,211,153,.18);color:#6EE7B7}
@media (max-width:560px){.feat{flex-direction:column;text-align:center;gap:6px;padding:10px 6px}
  .feat .ic{width:36px;height:36px}.feat b{font-size:.82rem}.feat small{font-size:.68rem}}
/* التصفية */
.tabs{display:grid;grid-template-columns:repeat(4,max-content);gap:8px;padding:6px;margin:0 0 14px;border-radius:16px;
  background:var(--card);border:1px solid var(--line)}
@media (max-width:620px){.tabs{grid-template-columns:1fr 1fr}}
.tabs button{display:inline-flex;align-items:center;justify-content:center;gap:7px;padding:10px 14px;border-radius:12px;
  border:1px solid var(--line);background:transparent;color:var(--ink);font:inherit;font-weight:700;font-size:.9rem;cursor:pointer}
.tabs button.on{background:linear-gradient(180deg,var(--pg),var(--pg2));color:var(--pg-ink);border-color:transparent}
.tabs button .n{font-size:.75rem;opacity:.75}
/* البطاقات */
.sec{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:16px;box-shadow:var(--shadow);margin-bottom:16px}
.sec>h2{margin:0;font-size:1.2rem}
.sec>.sub{margin:2px 0 14px;color:var(--mute);font-size:.88rem}
.list{display:grid;gap:12px}
.mc{display:grid;grid-template-columns:minmax(0,1fr);gap:12px;padding:14px;border-radius:18px;background:var(--soft);
  border:1px solid var(--line);position:relative}
.mc.hot{border-color:color-mix(in srgb,var(--gold) 70%,transparent);box-shadow:0 0 0 1px color-mix(in srgb,var(--gold) 35%,transparent),
  0 12px 30px -18px rgba(240,161,43,.6)}
@media (min-width:760px){.mc{grid-template-columns:minmax(0,1fr) 260px;align-items:stretch}}
.mtop{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap}
.cupn{display:inline-flex;align-items:center;gap:6px;color:var(--gold);font-weight:800;font-size:.9rem}
.cupn small{color:var(--mute);font-weight:600;font-size:.76rem}
.bdg{display:inline-flex;align-items:center;gap:5px;padding:3px 10px;border-radius:999px;font-size:.76rem;font-weight:800;
  background:var(--card);border:1px solid var(--line);color:var(--brand-text)}
.bdg .i{width:14px;height:14px}
.bdg.hot{background:linear-gradient(180deg,#FFD27A,#F0A12B);color:#3A2907;border-color:transparent}
.bdg.red{color:var(--red)}
.bdg .dot{width:7px;height:7px;border-radius:50%;background:var(--red);animation:blink 1.2s infinite}
@keyframes blink{50%{opacity:.25}}
.teams{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);align-items:center;gap:8px;margin:12px 0 6px;
  text-decoration:none;color:var(--ink)}
.tm{display:flex;align-items:center;gap:10px;min-width:0}
.tm.away{flex-direction:row-reverse;text-align:end}
.tm b{font-size:1.02rem;line-height:1.3;overflow-wrap:anywhere}
.fl{width:46px;height:46px;border-radius:50%;object-fit:cover;flex:0 0 auto;background:var(--card);
  box-shadow:0 0 0 2px var(--card),0 0 0 3px var(--line);display:inline-block}
.vs{font-size:1.2rem;color:var(--mute);font-weight:700;padding:0 4px}
.sc{display:inline-flex;gap:6px;font-size:1.5rem;font-weight:900;font-variant-numeric:tabular-nums;direction:ltr}
.sc i{font-style:normal;color:var(--mute);font-weight:400}
.sc.live{color:var(--red)}
.meta{display:flex;justify-content:center;flex-wrap:wrap;gap:6px 14px;margin:0 0 12px;color:var(--mute);font-size:.86rem}
.meta>span{display:inline-flex;align-items:center;gap:5px}
.meta .i{width:15px;height:15px}
.meta span[dir="ltr"]{font-weight:800;color:var(--brand-text)}
.act{display:grid;gap:6px;justify-items:center}
.cta{display:flex;align-items:center;justify-content:center;gap:8px;width:100%;padding:11px 14px;border-radius:13px;
  font-weight:800;text-decoration:none;font-size:.98rem}
.cta.go{background:linear-gradient(180deg,var(--pg),var(--pg2));color:var(--pg-ink);box-shadow:0 8px 20px -12px rgba(34,197,139,.9)}
.cta.shut{background:var(--card);border:1px solid var(--line);color:var(--mute)}
.cta.ghost{background:var(--card);border:1px solid var(--line);color:var(--ink)}
.cta .i{width:17px;height:17px}
.closes,.more{font-size:.78rem;color:var(--mute)}
.more{font-weight:700;color:var(--brand-text)}
.won{margin:0;display:flex;align-items:center;gap:6px;font-size:.92rem}
.won .i{color:var(--gold)}
.won.none{color:var(--mute);font-size:.86rem}
.mine{margin:8px 0 0;text-align:center;font-weight:800;color:var(--pg2);font-size:.88rem}
.cnt{margin:6px 0 0;text-align:center;color:var(--mute);font-size:.76rem}
.prz{display:flex;align-items:center;gap:12px;padding:12px;border-radius:16px;background:var(--card);border:1px solid var(--line);
  text-decoration:none;color:var(--ink);align-self:center}
.prz img,.prz .gi{width:52px;height:52px;border-radius:14px;flex:0 0 auto;object-fit:cover}
.prz .gi{display:grid;place-items:center;background:rgba(167,139,250,.18);color:#A78BFA}
.prz .gi .i{width:26px;height:26px}
.prz .pl{display:block;color:#A78BFA;font-weight:800;font-size:.8rem}
.prz b{display:block;font-size:.95rem;line-height:1.4}
.prz .w,.prz .lnk{display:block;color:var(--mute);font-size:.74rem}
.prz .lnk{color:var(--brand-text);font-weight:700}
.empty{color:var(--mute);text-align:center;padding:20px 8px}
/* الفائزون والخطوات والشروط */
.wins{list-style:none;margin:0;padding:0;display:grid;gap:8px}
.wins li{display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:14px;background:var(--soft);border:1px solid var(--line)}
.wins .i{color:var(--gold)}
.wins small{display:block;color:var(--mute);font-size:.78rem}
.steps{list-style:none;margin:0;padding:0;display:grid;gap:10px}
@media (min-width:760px){.steps{grid-template-columns:repeat(4,1fr)}}
.steps li{padding:14px;border-radius:16px;background:var(--soft);border:1px solid var(--line)}
.steps .k{display:grid;place-items:center;width:34px;height:34px;border-radius:50%;margin-bottom:8px;font-weight:900;
  background:linear-gradient(180deg,var(--pg),var(--pg2));color:var(--pg-ink)}
.steps b{display:block;margin-bottom:2px}
.steps small{color:var(--mute);font-size:.84rem}
.rules{margin:0;padding-inline-start:1.3em}
.rules li{margin:0 0 8px}
.foot{text-align:center;color:var(--mute);font-size:.8rem;margin-top:20px}
"""

JS = """
(function(){
var root=document.documentElement;
document.getElementById("tbtn").onclick=function(){var t=root.getAttribute("data-theme")==="light"?"dark":"light";
 root.setAttribute("data-theme",t);try{localStorage.setItem("ssouq_theme",t)}catch(e){}};
var tabs=document.querySelectorAll(".tabs button"),cards=document.querySelectorAll(".mc"),none=document.getElementById("none");
function pick(k){tabs.forEach(function(b){b.classList.toggle("on",b.dataset.k===k);b.setAttribute("aria-pressed",b.dataset.k===k)});
 var n=0;cards.forEach(function(c){var on=k==="all"||c.dataset.tab===k;c.hidden=!on;if(on)n++});if(none)none.hidden=n>0;}
tabs.forEach(function(b){b.onclick=function(){pick(b.dataset.k);try{history.replaceState(null,"","#"+(b.dataset.k==="all"?"contests":b.dataset.k))}catch(e){}}});
var h=location.hash.slice(1);if(h==="open"||h==="live"||h==="done")pick(h);
document.querySelectorAll('.nav a[data-k]').forEach(function(a){a.addEventListener("click",function(){pick(a.dataset.k)})});
cards.forEach(function(c){var v=null;try{v=JSON.parse(localStorage.getItem("ssouq_predict_"+c.dataset.m)||"null")}catch(e){}
 var p=c.querySelector(".mine");if(v&&v.n&&p){p.hidden=false;p.textContent="✓ توقّعك مسجّل"+(v.h!=null?": "+v.h+"-"+v.a:"")+" · رقم توقّعك "+v.n;}});
document.querySelectorAll("img.fl").forEach(function(im){im.addEventListener("error",function(){var i=document.createElement("i");i.className="fl";im.replaceWith(i)})});
var gift=document.getElementById("giftTpl");
document.querySelectorAll(".prz img").forEach(function(im){im.addEventListener("error",function(){if(gift)im.replaceWith(gift.content.firstElementChild.cloneNode(true))})});
})();
"""


def render(cups, summ, tv, now=None):
    """الصفحة ← (رمز، بايتات، مدة الكاش)."""
    now = time.time() if now is None else now
    cards = _cards(cups, summ, tv, now)
    counts = {k: sum(1 for t, _ in cards if t == k) for k, _ in TABS}
    counts["all"] = len(cards)
    preds = sum(int(s.get("count") or 0) for s in summ.values())
    names = " و".join(c.CUP["name"] for c in cups)                   # «كأس الخليج العربي ودوري الأمم الأوروبية»
    title = "مسابقة التوقّعات — توقّع النتيجة واربح اشتراكًا | سمارت سوق"
    desc = (f"توقّع نتائج مباريات {names} مجانًا واربح اشتراكات سمارت سوق. "
            "التسجيل برسالة واتساب، والفرز آليٌّ بعد صافرة النهاية بفيديو يشرح كيف تم.")
    url = guide_pages.SITE + PATH
    tabs = "".join(f'<button type="button" data-k="{k}" class="{"on" if k == "all" else ""}" aria-pressed="{str(k == "all").lower()}">'
                   f'{t} <span class="n">({counts.get(k, 0)})</span></button>' for k, t in TABS)
    lst = "".join(h for _, h in cards)
    wins = _winners(summ)
    feat3 = ((f"{preds:,} توقّعًا", "من المشاركين حتى الآن") if preds >= 10
             else ("مجانية بالكامل", "بلا شراء، برسالة واتساب"))
    rules = "".join(f"<li>{_esc(x)}</li>" for x in contest.RULES)
    ld = [{"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "دليل سمارت سوق", "item": guide_pages.SITE + "/"},
        {"@type": "ListItem", "position": 2, "name": "مسابقة التوقّعات", "item": url}]}]
    ld_html = "".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False)}</script>' for x in ld)
    doc = f"""<!doctype html>
<html lang="ar" dir="rtl" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
<meta name="description" content="{_esc(desc)}">
<meta name="robots" content="index, follow, max-image-preview:large">
<link rel="canonical" href="{url}">
<meta name="theme-color" content="#0B1826">
<meta property="og:type" content="website">
<meta property="og:locale" content="ar_SA">
<meta property="og:site_name" content="سمارت سوق">
<meta property="og:title" content="{_esc(title)}">
<meta property="og:description" content="{_esc(desc)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{guide_pages.SITE}/static/og-image.png">
<link rel="icon" href="/favicon.ico">
<link rel="preconnect" href="{league.LOGO_HOST}">
<script>try{{var t=localStorage.getItem("ssouq_theme");if(t)document.documentElement.setAttribute("data-theme",t)}}catch(e){{}}</script>
{ld_html}
<style>{guide_pages._style()}
{CSS}</style>
</head>
<body>
<header class="top"><div>
<a class="brand" href="{PATH}">{_i("trophy")}<span><b>مسابقة التوقّعات</b><small>توقّع النتيجة واربح الجوائز</small></span></a>
<nav class="nav" aria-label="أقسام الصفحة">
<a class="on" href="#contests" data-k="all">{_i("trophy")}المسابقات</a>
<a href="#done" data-k="done">{_i("chart")}النتائج</a>
<a href="#winners">{_i("gift")}الفائزون</a>
<a href="{STORE}" target="_blank" rel="noopener">{_i("store")}المتجر</a>
</nav>
<button class="tbtn" id="tbtn" type="button" aria-label="تبديل الوضع الليلي">{_i("moon", "i moon")}{_i("sun", "i sun")}</button>
</div></header>
<main class="wrap">
<section class="hero" aria-labelledby="h1">
{TROPHY}
<div class="ht"><h1 id="h1">توقّع النتائج واربح الجوائز</h1>
<p>شارك مجانًا في مسابقات مباريات {_esc(names)}، واربح اشتراكات سمارت سوق.</p>
<a class="gold" href="#how">{_i("q")}كيف أشارك؟</a></div>
<div class="feats">
<div class="feat"><span class="ic">{_i("gift")}</span><span><b>جوائز مميزة</b><small>اشتراكات IPTV من المتجر</small></span></div>
<div class="feat"><span class="ic">{_i("chart")}</span><span><b>توقّع المباريات</b><small>بخطوات بسيطة عبر واتساب</small></span></div>
<div class="feat"><span class="ic">{_i("users")}</span><span><b>{_esc(feat3[0])}</b><small>{_esc(feat3[1])}</small></span></div>
</div>
</section>
<div class="tabs" role="toolbar" aria-label="تصفية المسابقات">{tabs}</div>
<section class="sec" id="contests" aria-labelledby="contests-h">
<h2 id="contests-h">المسابقات</h2>
<p class="sub">اختر المباراة وتوقّع نتيجتها واربح — التوقّع من صفحة المباراة برسالة واتساب.</p>
<div class="list">{lst}</div>
<p class="empty" id="none" {"hidden" if cards else ""}>لا مسابقات هنا الآن. نعلن المسابقة القادمة في قناتنا على واتساب.</p>
<span id="open"></span><span id="live"></span><span id="done"></span>
</section>
<section class="sec" id="winners" aria-labelledby="winners-h">
<h2 id="winners-h">الفائزون</h2>
<p class="sub">آخر الفائزين بأسمائهم الأولى — ونبلّغ كل فائزٍ على واتساب.</p>
{f'<ul class="wins">{"".join(wins)}</ul>' if wins else '<p class="empty">لا فائزين بعد — قد تكون أول فائز!</p>'}
</section>
<section class="sec" id="how" aria-labelledby="how-h">
<h2 id="how-h">كيف أشارك؟</h2>
<p class="sub">أربع خطوات، مجانًا وبلا شراء.</p>
<ol class="steps">
<li><span class="k">1</span><b>ادخل صفحة المباراة</b><small>من زرّ «شارك الآن» في بطاقتها.</small></li>
<li><span class="k">2</span><b>اكتب توقّعك واسمك</b><small>النتيجة بزرّين لكل فريق.</small></li>
<li><span class="k">3</span><b>أرسل الرسالة الجاهزة</b><small>«أرسل توقّعي على واتساب» ثم أرسلها كما هي.</small></li>
<li><span class="k">4</span><b>يصلك التأكيد</b><small>على واتساب برقم توقّعك ✅</small></li>
</ol>
</section>
<section class="sec" id="rules" aria-labelledby="rules-h">
<h2 id="rules-h">الشروط وطريقة الفرز</h2>
<ol class="rules">{rules}</ol>
<h3>الفرز بالأرقام</h3>
<p class="sub">عند الإقفال تُحسب <b>بصمة التوقّعات</b> (SHA-256 لقائمتها) وتظهر في صفحة المباراة. وبعد صافرة النهاية:
<b>رقم القرعة</b> = SHA-256(البصمة | رقم المباراة | النتيجة)، ورقم الفائز الأول = أول 12 خانة من SHA-256(رقم القرعة:0)
عددًا عشريًّا، والفائز هو المؤهّل الذي ترتيبه (بترتيب التسجيل) باقي قسمة ذلك الرقم على عدد المؤهّلين، مبتدئًا من الصفر.
وكل أرقام الفرز منشورة في صفحة المباراة ليتحقّق منها من شاء.</p>
</section>
<p class="foot"><a href="/">دليل سمارت سوق</a> · {" · ".join(f'<a href="{c.PATH}">{_esc(c.CUP["name"])}</a>' for c in cups)}
· <a href="{STORE}" target="_blank" rel="noopener">متجر سمارت سوق</a></p>
</main>
<template id="giftTpl"><span class="gi">{_i("gift")}</span></template>
<script>{JS}</script>
</body>
</html>"""
    return 200, doc.encode("utf-8"), 60

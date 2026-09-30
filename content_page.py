# -*- coding: utf-8 -*-
"""صفحة المحتوى كما يراها الزائر (‏/content/<السيرفر>) بتصميم تطبيقات المشاهدة — وبالإنجليزية على
‏/en/content/<السيرفر>: الصفحة نفسها من اليسار، وزرٌّ في رأس كلٍّ منهما إلى الأخرى بما فيها من قسمٍ وبحث.

رأسٌ بالأقسام والبحث، وواجهةٌ متحرّكة بأحدث ما أضيف، وخانات الأعداد، وتبويب لكل نوع ومعه «أضيف مؤخرًا»،
وأقسام السيرفر صورًا، وصفّ ملصقات لكل قسم، وجانبٌ بالتصفية (السنة والقسم والتصنيف والتقييم) وقائمة
«أضيف مؤخرًا» وباقات الاشتراك، ونافذة تفاصيل فيها المواسم وحلقات كل موسم.

البيانات من content.py، والصفحة كلها تُرسم على الخادم وتعمل بلا سكربت (روابط ‏?t= ?g= ?view=grid ?q=)؛
والسكربت للحركة والنافذة والبحث مع الكتابة. والصفحة الرئيسية لكل سيرفر وحدها تُفهرس، بلغتيها (‏hreflang).
وأسماء المسلسلات والأفلام والأقسام كما في ملف السيرفر في اللغتين: لا تُترجم.
"""
import datetime
import json
import re
import time
from urllib.parse import quote, urlencode

import content as C
import guide_pages
import league
import tournament

_esc = league._esc
ROW_MAX = 14                 # ملصقات كل صفّ
ROWS_MAX = 8                 # صفوف الأقسام في صفحة النوع
CHIPS_MAX = 9                # أقسامٌ صورًا فوق الصفوف، والباقي في «كل الأقسام»
GRID = 60                    # ملصقات الصفحة الواحدة في الشبكة
HERO_MAX = 5
SIDE_MAX = 6
NEW_MAX = {"movie": 48, "series": 48, "live": 24}
NEW_DAYS = 14                # شارة «جديد» لما أضيف خلالها (بتاريخ الواجهة)
KIND_ONE = {"movie": "فيلم", "series": "مسلسل", "live": "قناة"}
N_GROUPS = ("قسم واحد", "قسمان", "أقسام", "قسمًا", "قسم")
ART = {k: f"/static/img/brands/{k}.webp" for k in ("smart", "falcon", "casper")}   # شعار السيرفر إن كان له
DAYS = ("يوم", "يومين", "أيام", "يومًا", "يوم")
WEEKS = ("أسبوع", "أسبوعين", "أسابيع", "أسبوعًا", "أسبوع")
MONTHS = ("شهر", "شهرين", "أشهر", "شهرًا", "شهر")
YEARS = ("سنة", "سنتين", "سنوات", "سنة", "سنة")
QUERY = ("t", "g", "p", "q", "view", "y", "genre", "r", "sort", "all")   # ما تقرؤه الصفحة من الرابط، ويحمله زرّ اللغة

# ---- الإنجليزية ----
KIND_TAB_EN = {"series": "Series", "movie": "Movies", "live": "Channels"}
KIND_ONE_EN = {"movie": "Movie", "series": "Series", "live": "Channel"}
N_AR = {"series": C.N_SERIES, "movie": C.N_MOVIES, "live": C.N_CHANNELS, "seasons": C.N_SEASONS,
        "episodes": C.N_EPISODES, "results": C.N_RESULTS, "groups": N_GROUPS}
N_EN = {"series": ("series", "series"), "movie": ("movie", "movies"), "live": ("channel", "channels"),
        "seasons": ("season", "seasons"), "episodes": ("episode", "episodes"), "results": ("result", "results"),
        "groups": ("category", "categories")}
MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
BRAND_EN = "Smart Souq"
# باقات CATALOG بالإنجليزية: اسمها «Falcon · 15 months» من اسم السيرفر ومدّتها، إلا ما هنا، ووسمها مترجمًا أو مدّتها
PLAN_EN = {"سنة كاملة": "Full year", "سنة ترفيهية": "Entertainment year", "سنتان": "2 years", "يوم تجريبي": "1-day trial"}
PLAN_FOR_EN = (("لجهازين", "for 2 devices"), ("لسامسونج و LG", "for Samsung & LG"))
TAG_EN = {"الأقصر مدة": "Shortest", "الأكثر توازنًا": "Best balance", "الأوفر": "Best value", "جهازان": "2 devices",
          "جرّب أولًا": "Try it first", "الأكثر مبيعًا": "Best seller", "أفلام ومسلسلات": "Movies & series",
          "3 أشهر هدية": "3 months free"}
_DUR_EN = (("ساع", "hour"), ("يوم", "day"), ("أسبوع|أسابيع", "week"), ("شهر|أشهر", "month"), ("سنة|سنت|سنوات", "year"))


class Lang:
    """لغة الصفحة: ‏tr("نصٌّ عربي", "English") يختار أحدهما — ومعها ما يختلف بينهما: مسار الصفحة، والعدد ومعدوده،
    واسم النوع، واسم السيرفر."""

    def __init__(self, code):
        self.code, self.en = code, code == "en"
        self.dir = "ltr" if self.en else "rtl"
        self.path = C.PATH_EN if self.en else C.PATH

    def __call__(self, ar, en):
        return en if self.en else ar

    def count(self, n, what):
        """«3 مواسم» · «3 seasons» — ‏what من ‏N_AR."""
        if self.en:
            return f"{n:,} {N_EN[what][n != 1]}"
        return C._count(n, N_AR[what])

    def unit(self, n, what):
        """معدود العدد وحده لخانات الأرقام: «مواسم» · «seasons»."""
        return N_EN[what][n != 1] if self.en else C._unit(n, N_AR[what])

    def tab(self, kind):
        return (KIND_TAB_EN if self.en else C.KIND_TAB)[kind]

    def one(self, kind):
        return (KIND_ONE_EN if self.en else KIND_ONE)[kind]

    def name(self, srv):
        return C.en_name(srv) if self.en else srv["name"]

    def full(self, srv):
        """السطر تحت اسم السيرفر — إلا إن كان هو اسمه (سيرفرٌ بلا اسمٍ إنجليزي يُسمّى به)."""
        return "" if srv["full"].casefold() == self.name(srv).casefold() else srv["full"]

    def join(self, parts):
        """«أ وب وج» · «A, B and C»."""
        parts = list(parts)
        if not self.en:
            return " و".join(parts)
        return " and ".join([", ".join(parts[:-1]), parts[-1]] if len(parts) > 2 else parts)

    def quote(self, s):
        return f"“{s}”" if self.en else f"«{s}»"


AR, EN = Lang("ar"), Lang("en")


def lang_of(code):
    return EN if code == "en" else AR

ICON = {
    "movie": '<path d="M4 11h16v8a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1z"/><path d="m4 11-.6-2.5a1 1 0 0 1 .7-1.2l13.6-3.7a1 1 0 0 1 1.2.7l.7 2.5"/><path d="m8 6.3 2.4 3.3M13.2 4.9l2.4 3.3"/>',
    "series": '<rect x="3" y="5" width="18" height="12" rx="2"/><path d="M8 21h8M12 17v4M10 8.5l4 2.5-4 2.5z"/>',
    "live": '<circle cx="12" cy="10" r="1.6"/><path d="M12 12v9M9 21h6M8.5 6.5a5 5 0 0 0 0 7M15.5 6.5a5 5 0 0 1 0 7M5.6 3.6a9 9 0 0 0 0 12.8M18.4 3.6a9 9 0 0 1 0 12.8"/>',
    "episodes": '<path d="M4 6h16M4 12h9M4 18h7"/><path d="m16 14.5 5 3-5 3z"/>',
    "seasons": '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
    "new": '<path d="M12 3l1.8 4.6L18.5 9l-4.7 1.4L12 15l-1.8-4.6L5.5 9l4.7-1.4z"/><path d="M19 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>',
    "home": '<path d="M3 10.5 12 3l9 7.5M5 9.5V21h14V9.5"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "filter": '<path d="M3 5h18l-7 8.5V20l-4-2v-4.5z"/>',
    "chev": '<path d="m15 18-6-6 6-6"/>',
    "chevr": '<path d="m9 18 6-6-6-6"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
}
STAR = ('<svg class="star" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="m12 2.8 2.8 5.8 6.3.9-4.6 4.4'
        ' 1.1 6.3L12 17.2l-5.6 3 1.1-6.3-4.6-4.4 6.3-.9z"/></svg>')


def _i(name, cls="i"):
    return f'<svg class="{cls}" viewBox="0 0 24 24" aria-hidden="true">{ICON[name]}</svg>'


def _ago(ts, now=None, tr=AR):
    """تاريخ الإضافة من الواجهة: «اليوم» «أمس» «منذ 3 أيام» «منذ أسبوعين» «منذ 5 أشهر» — «3 days ago» «a week ago»."""
    if not ts:
        return ""
    d = int(((now or time.time()) - ts) // 86400)
    if d < 1:
        return tr("اليوم", "today")
    if d < 2:
        return tr("أمس", "yesterday")
    for size, forms, word in ((365, YEARS, "year"), (30, MONTHS, "month"), (7, WEEKS, "week"), (1, DAYS, "day")):
        if d >= size:
            n = d // size
            return tr("منذ " + C._count(n, forms), f"a {word} ago" if n == 1 else f"{n} {word}s ago")
    return ""


def _when(ts, tr=AR):
    """وقتٌ بتوقيت السعودية: «29 سبتمبر 2026، 2:04 م» · «Sep 29, 2026, 2:04 PM»."""
    if not tr.en:
        return league._when(ts)
    t = datetime.datetime.fromtimestamp(ts, league.RIYADH)
    return f"{MONTHS_EN[t.month - 1]} {t.day}, {t.year}, {t.hour % 12 or 12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def _hue(s):
    return sum(map(ord, s or "")) * 37 % 360


def _logo(key, name, cls="lg"):
    """شعار السيرفر (‏ART)، أو أول حرفٍ من اسمه بلونٍ منه لسيرفرٍ بلا شعار."""
    if key in ART:
        return f'<img class="{cls}" src="{ART[key]}" alt="" width="40" height="40" decoding="async">'
    return f'<span class="{cls} bi" style="--h:{_hue(name)}" aria-hidden="true">{_esc((name or "•")[:1])}</span>'


def _initials(name):
    """حرفا الملصق بلا صورة: أول حرفٍ من أول كلمتين — بلا الأقواس والرموز، والأرقام («(2026)» «12 Strong»)
    إلا إن لم يكن غيرها («2020»)."""
    words = re.findall(r"[^\W_]+", C._TASHKEEL.sub("", name or ""))
    words = [w for w in words if not w.isdigit()] or words
    return "".join(w[0] for w in words[:2]).upper() or "•"


def _seasons(it, tr=AR):
    """ملخّص المواسم ورقاقاتها: («5 مواسم · 62 حلقة»، [«الموسم 1 (7 حلقات)»، …]) · «Season 1 (7 episodes)»."""
    ss = it.get("s") or []
    if not ss:
        return "", []
    known = any(s for s, _ in ss)
    eps = sum(n for _, n in ss)
    text = (tr.count(len(ss), "seasons") + " · " if known else "") + tr.count(eps, "episodes")
    chips = [f'{tr(f"الموسم {s}", f"Season {s}") if s else tr("بلا موسم", "No season")} ({tr.count(n, "episodes")})'
             for s, n in ss] if known else []
    return text, chips


def _fresh(it, now=None):
    a = it.get("a")
    return bool(a) and (now or time.time()) - a < NEW_DAYS * 86400


def _data(key, kind, it, gname, tr=AR):
    """ما تعرضه نافذة التفاصيل — نصًّا في ‏data-d، فلا طلب ثانيًا."""
    ss, sc = _seasons(it, tr)
    d = {"k": kind, "n": it.get("n"), "y": it.get("y"), "r": it.get("r"), "g": it.get("g"), "d": it.get("d"),
         "c": gname, "ss": ss, "sc": sc, "a": _ago(it.get("a"), tr=tr),
         "p": C.img_src(key, it.get("p"), "w500"), "b": C.img_src(key, it.get("b") or "", "w780")}
    return _esc(json.dumps({k: v for k, v in d.items() if v}, ensure_ascii=False, separators=(",", ":")))


def _pos(key, it, size="w342", lazy=True):
    """الملصق: الحرفان الأولان بلونٍ من الاسم تحت الصورة، فإن تعذّرت بقيا."""
    name = it.get("n", "")
    src = C.img_src(key, it.get("p"), size)
    img = (f'<img src="{_esc(src)}" alt=""{" loading=lazy" if lazy else ""} decoding="async">' if src else "")
    return f'<span class="ph">{_esc(_initials(name))}</span>{img}', _hue(name)


def card(key, kind, it, gname="", when=False, now=None, tr=AR):
    name = it.get("n", "")
    face, hue = _pos(key, it)
    sub = [str(it["y"])] if it.get("y") else []
    if kind == "series":
        ss = it.get("s") or []
        if ss:
            known = any(s for s, _ in ss)
            sub.append(tr.count(len(ss), "seasons") if known else tr.count(sum(n for _, n in ss), "episodes"))
    if when and it.get("a"):
        sub.append((tr("حُدّث ", "Updated ") if kind == "series" else tr("أضيف ", "Added ")) + _ago(it["a"], now, tr))
    badge = f'<span class="badge">{tr("جديد", "New")}</span>' if _fresh(it, now) else ""
    rt = f'<p class="rt">{STAR}{it["r"]:g}</p>' if it.get("r") else ""
    tags = ('<p class="tags">' + "".join(f"<span>{_esc(g)}</span>" for g in it["g"][:2]) + "</p>") if it.get("g") else ""
    return (f'<article class="card{" ch" if kind == "live" else ""}" tabindex="0" data-d="{_data(key, kind, it, gname, tr)}">'
            f'<div class="pos" style="--h:{hue}">{face}{badge}</div><h3 dir="auto">{_esc(name)}</h3>'
            + (f'<p class="sub">{_esc(" · ".join(sub))}</p>' if sub else "") + rt + tags + "</article>")


def _cards(key, v, kind, picks, when=False, tr=AR):
    gs = v["kinds"][kind]
    return "".join(card(key, kind, gs[gi]["items"][ii], gs[gi]["name"], when, tr=tr) for gi, ii in picks)


def _row(title, inner, more_href="", more="", tr=AR):
    """صفّ ملصقاتٍ بسهمين — وأيقونتاهما تنقلبان في الإنجليزية (‏CSS)، فالسابق إلى البداية في اللغتين."""
    return (f'<section class="row"><div class="rh"><h2>{title}</h2>'
            + (f'<a class="more" href="{more_href}">{more}</a>' if more_href else "")
            + f'<span class="rbtn"><button type="button" class="arrow prev" aria-label="{tr("السابق", "Previous")}">'
            + _i("chevr") + f'</button><button type="button" class="arrow next" aria-label="{tr("التالي", "Next")}">'
            + _i("chev") + f'</button></span></div><div class="cards">{inner}</div></section>')


def _sel(v, kind, **kw):
    """‏C.select بكاشٍ صغير في العرض نفسه — تُطلب الصفحة كثيرًا وأقسامها كبيرة."""
    cache = v.setdefault("_sel", {})
    ck = (kind,) + tuple(sorted(kw.items()))
    if ck not in cache:
        if len(cache) > 96:
            cache.clear()
        cache[ck] = C.select(v, kind, **kw)
    return cache[ck]


def _link(base, **kw):
    q = urlencode([(k, val) for k, val in kw.items() if val not in ("", None, 0)])
    return _esc(base + ("?" + q if q else ""))


# ================= أجزاء الصفحة =================
def _switch(tr, href):
    """زرّ اللغة الأخرى: «English» في العربية و«العربية» في الإنجليزية، إلى الصفحة نفسها بما فيها من قسمٍ وبحث."""
    code, label = ("ar", "العربية") if tr.en else ("en", "English")
    return f'<a class="lang" href="{_esc(href)}" hreflang="{code}" lang="{code}">{_i("globe")}{label}</a>'


def _header(base, srv, v, t, q, key, tr=AR, alt=""):
    art = (f'<img src="{ART[key]}" alt="" width="42" height="42">' if key in ART
           else f'<span class="bi">{_i("series")}</span>')
    name, full = tr.name(srv), tr.full(srv)
    nav = [("", tr("الرئيسية", "Home"))] + [(k, tr.tab(k)) for k in C.KINDS if v["kinds"][k]]
    if any(v["recent"][k] for k in C.KINDS):
        nav.append(("new", tr("أضيف مؤخرًا", "New")))            # قصيرةٌ بالإنجليزية فيتّسع لها الرأس على الجوال
    links = "".join(f'<a href="{_link(base, t=k)}"{" class=home" if not k else ""}{" aria-current=page" if k == t else ""}>'
                    f'{label}</a>' for k, label in nav)
    return (f'<header class="top"><div class="wrap"><a class="brand" href="{_esc(base)}">{art}<span><b>{_esc(name)}</b>'
            + (f'<small>{_esc(full)}</small>' if full else "") + '</span></a>'
            f'<nav class="nav" aria-label="{tr("أقسام المحتوى", "Content sections")}">{links}</nav>'
            f'<form class="search" role="search" action="{_esc(base)}" method="get">'
            f'<input type="search" name="q" value="{_esc(q)}" '
            f'placeholder="{tr("ابحث باسم المسلسل أو الفيلم…", "Search by series or movie name…")}" '
            f'aria-label="{tr("ابحث باسم المسلسل أو الفيلم في ", "Search series and movies in ")}{_esc(name)}" autocomplete="off" '
            f'enterkeyhint="search" maxlength="{C.QUERY_MAX}"><button type="submit" aria-label="{tr("بحث", "Search")}">'
            f'{_i("search")}</button></form>' + (_switch(tr, alt) if alt else "") + '</div></header>')


def _servers(data_dir, key, tr=AR):
    shown = [s for s in C.servers(data_dir) if s["key"] == key or C.has(data_dir, s["key"], s)]
    if len(shown) < 2:
        return ""
    return (f'<nav class="servers" aria-label="{tr("السيرفرات", "Servers")}"><span class="lbl">{tr("السيرفر:", "Server:")}</span>'
            + "".join(f'<a href="{tr.path}/{s["key"]}"{" aria-current=page" if s["key"] == key else ""}>'
                      f'{_logo(s["key"], tr.name(s))}<span><b>{_esc(tr.name(s))}</b>'
                      + (f'<small>{_esc(tr.full(s))}</small>' if tr.full(s) else "") + "</span></a>"
                      for s in shown) + "</nav>")


def _hero(key, v, tr=AR):
    """أحدث ما أضيف بصورته: ثلاثة أفلام ومسلسلان، أو ما وُجد منهما."""
    pools = {}
    for kind in ("movie", "series"):
        gs = v["kinds"][kind]
        pools[kind] = [(kind, gs[gi]["items"][ii], gs[gi]["name"]) for gi, ii in v["recent"][kind]
                       if gs[gi]["items"][ii].get("p")][:HERO_MAX]
    picks = pools["movie"][:3] + pools["series"][:2]
    picks += [p for p in pools["movie"][3:] + pools["series"][2:] if p not in picks][:HERO_MAX - len(picks)]
    if not picks:
        return ""
    slides, dots, side = [], [], []
    for n, (kind, it, gname) in enumerate(picks):
        bg = C.img_src(key, it.get("b") or it.get("p"), "w780")
        facts = [str(it["y"])] if it.get("y") else []
        if it.get("g"):
            facts.append(" • ".join(it["g"]))
        ss, _ = _seasons(it, tr)
        if ss:
            facts.append(ss)
        lazy = "" if n == 0 else ' loading="lazy"'
        slides.append(
            f'<article class="slide{" on" if n == 0 else ""}" data-d="{_data(key, kind, it, gname, tr)}">'
            f'<img class="bg" src="{_esc(bg)}" alt=""{lazy}>'
            f'<div class="info"><span class="kick">{_i("new")}{tr("أضيف مؤخرًا", "Recently added")} · {tr.one(kind)}</span>'
            f'<h2 dir="auto">{_esc(it["n"])}</h2>' + (f'<p class="facts">{_esc(" · ".join(facts))}</p>' if facts else "")
            + (f'<p class="rt">{STAR}{it["r"]:g}</p>' if it.get("r") else "")
            + (f'<p class="plot">{_esc(it["d"])}</p>' if it.get("d") else "")
            + f'<button type="button" class="btn">{tr("عرض التفاصيل", "View details")}</button></div>'
            f'<img class="poster" src="{_esc(C.img_src(key, it["p"], "w342"))}" alt=""{lazy}></article>')
        dots.append(f'<button type="button" data-go="{n}" aria-label="{tr("الشريحة", "Slide")} {n + 1}"'
                    f'{" aria-current=true" if n == 0 else ""}></button>')
        face, hue = _pos(key, it, "w185")
        side.append(f'<button type="button" data-go="{n}"{" aria-current=true" if n == 0 else ""}>'
                    f'<span class="pos" style="--h:{hue}">{face}</span><span><b dir="auto">{_esc(it["n"])}</b>'
                    f'<small>{_esc(" · ".join(facts[:1] + [tr.one(kind)]))}</small></span></button>')
    arrows = (f'<button type="button" class="harrow prev" aria-label="{tr("السابق", "Previous")}">{_i("chevr")}</button>'
              f'<button type="button" class="harrow next" aria-label="{tr("التالي", "Next")}">{_i("chev")}</button>'
              if len(picks) > 1 else "")
    return (f'<div class="herobox"><section class="hero" data-hero aria-roledescription="{tr("عرض", "carousel")}" '
            f'aria-label="{tr("أضيف مؤخرًا", "Recently added")}">'
            f'{"".join(slides)}{arrows}<div class="dots">{"".join(dots) if len(picks) > 1 else ""}</div></section>'
            f'<div class="hlist">{"".join(side[:4])}</div></div>')


def _stats(c, tr=AR):
    tiles = [("movie", c["movie"], "movie"), ("series", c["series"], "series"), ("live", c["live"], "live"),
             ("episodes", c["episodes"], "episodes"), ("seasons", c["seasons"], "seasons")]
    return '<div class="stats">' + "".join(
        f'<div class="stat">{_i(icon)}<span><b>{n:,}</b><small>{tr.unit(n, what)}</small></span></div>'
        for icon, n, what in tiles if n) + "</div>"


def _kinds(base, v, t, tr=AR):
    tabs = [(k, tr.tab(k), v["counts"][k]) for k in C.KINDS if v["kinds"][k]]
    if any(v["recent"][k] for k in C.KINDS):
        tabs.append(("new", tr("أضيف مؤخرًا", "New"), 0))
    return f'<nav class="kinds" aria-label="{tr("نوع المحتوى", "Content type")}">' + "".join(
        f'<a href="{_link(base, t=k)}"{" aria-current=page" if k == t else ""}>{_i(k)}{label}'
        + (f' <small>{n:,}</small>' if n else "") + "</a>" for k, label, n in tabs) + "</nav>"


def _chip(key, base, v, kind, gi, g, tr=AR):
    top = _sel(v, kind, gid=g["id"])
    pic = next((g["items"][ii].get("p") for _, ii in top[:40] if g["items"][ii].get("p")), "")
    src = C.img_src(key, pic, "w185")
    return (f'<a class="chip" href="{_link(base, t=kind, g=g["id"])}">'
            + (f'<img src="{_esc(src)}" alt="" loading="lazy">' if src else "")
            + f'<span><b>{_esc(g["name"])}</b><small>{tr.count(len(g["items"]), kind)}</small></span></a>')


def _chips(key, base, v, kind, tr=AR):
    gs = v["kinds"][kind]
    out = [_chip(key, base, v, kind, gi, g, tr) for gi, g in enumerate(gs[:CHIPS_MAX])]
    if len(gs) > CHIPS_MAX:
        out.append(f'<a class="chip more" href="{_link(base, t=kind, all=1)}"><span>{_i("grid")}'
                   f'<b>{tr("كل الأقسام", "All categories")}</b><small>{len(gs):,}</small></span></a>')
    return f'<div class="chips">{"".join(out)}</div>'


def _filters(base, v, kind, cur, tr=AR):
    if kind not in C.KINDS or not v["kinds"][kind]:
        return ""
    def opts(pairs, sel):
        return "".join(f'<option value="{_esc(val)}"{" selected" if str(val) == str(sel) else ""}>{_esc(label)}</option>'
                       for val, label in pairs)
    every = tr("الكل", "All")
    parts = [f'<input type="hidden" name="t" value="{kind}"><input type="hidden" name="view" value="grid">']
    if v["years"][kind]:
        parts.append(f'<label for="fy">{tr("السنة", "Year")}</label><select id="fy" name="y">'
                     + opts([("", every)] + [(y, y) for y in v["years"][kind]], cur["y"] or "") + "</select>")
    parts.append(f'<label for="fg">{tr("القسم", "Category")}</label><select id="fg" name="g">'
                 + opts([("", tr("كل الأقسام", "All categories"))] + [(g["id"], g["name"]) for g in v["kinds"][kind]],
                        cur["g"]) + "</select>")
    if v["genres"][kind]:
        parts.append(f'<label for="fn">{tr("التصنيف", "Genre")}</label><select id="fn" name="genre">'
                     + opts([("", every)] + [(x, x) for x in v["genres"][kind]], cur["genre"]) + "</select>")
    if v["rated"][kind]:
        parts.append(f'<label for="fr">{tr("التقييم", "Rating")}</label><select id="fr" name="r">'
                     + opts([("", every)] + [(n, tr(f"{n} فأعلى", f"{n}+")) for n in (9, 8, 7, 6, 5)], cur["r"] or "")
                     + "</select>")
    sorts = ([("new", tr("الأحدث إضافة", "Recently added")), ("az", tr("الاسم", "Name"))]
             + ([("rate", tr("الأعلى تقييمًا", "Top rated"))] if v["rated"][kind] else []))
    parts.append(f'<label for="fs">{tr("الترتيب", "Sort by")}</label><select id="fs" name="sort">'
                 + opts(sorts, cur["sort"]) + "</select>")
    return (f'<section class="panel"><h2>{_i("filter")} {tr("تصفية " + tr.tab(kind), "Filter " + tr.tab(kind).lower())}</h2>'
            f'<form class="filter" action="{_esc(base)}" method="get">{"".join(parts)}'
            f'<button class="btn" type="submit">{tr("تطبيق الفلتر", "Apply filter")}</button></form></section>')


def _recent_list(key, v, kinds, tr=AR):
    """«أضيف مؤخرًا» في الجانب: أحدث ما في الأنواع المعطاة معًا، مرقّمًا."""
    pool = []
    for kind in kinds:
        gs = v["kinds"][kind]
        for gi, ii in v["recent"][kind][:SIDE_MAX]:
            it = gs[gi]["items"][ii]
            pool.append(((it.get("a") or 0, it.get("i") or 0), kind, it, gs[gi]["name"]))
    pool.sort(key=lambda p: p[0], reverse=True)
    if not pool:
        return ""
    rows = []
    for n, (_, kind, it, gname) in enumerate(pool[:SIDE_MAX], 1):
        face, hue = _pos(key, it, "w185")
        sub = [str(it["y"])] if it.get("y") else []
        sub.append(_ago(it["a"], tr=tr) if it.get("a") else tr.one(kind))
        rows.append(f'<li tabindex="0" data-d="{_data(key, kind, it, gname, tr)}"><span class="n">{n}</span>'
                    f'<span class="pos" style="--h:{hue}">{face}</span><span class="t"><b dir="auto">{_esc(it["n"])}</b>'
                    f'<small>{_esc(" · ".join(sub))}</small></span>'
                    + (f'<span class="rt">{STAR}{it["r"]:g}</span>' if it.get("r") else "") + "</li>")
    return (f'<section class="panel"><h2>{_i("new")} {tr("أضيف مؤخرًا", "Recently added")}</h2>'
            f'<ol class="recent">{"".join(rows)}</ol></section>')


def _utm(url, campaign=""):
    """روابط المتجر بحملة هذه الصفحة (أو ‏campaign) لتُعرف المبيعات منها، وغيرها كما هي."""
    campaign = campaign or C.UTM_CAMPAIGN
    host = (re.match(r"^https?://([^/?#:]+)", url or "") or [None, ""])[1].lower()
    if host != "ssouq.com" and not host.endswith(".ssouq.com"):
        return url
    if "utm_campaign=" in url:
        return re.sub(r"utm_campaign=[^&#]*", "utm_campaign=" + campaign, url)
    return (url + ("&" if "?" in url else "?")
            + "utm_source=guide.ssouq.com&utm_medium=referral&utm_campaign=" + campaign)


AD_CAMPAIGN = "content-ad"      # نقرات الإعلان منفصلةً في تقارير المتجر عن باقات الجانب (‏content)


def _money(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


PITCH = ("دفعة واحدة بلا تجديد تلقائي، وتفعيل خلال دقائق، ودعم فني مباشر على واتساب.",
         "One-time payment with no auto-renewal, activation within minutes, and live support on WhatsApp.")
_TWO = re.compile("ساعتان|ساعتين|يومان|يومين|أسبوعان|أسبوعين|شهران|شهرين|سنتان|سنتين")


def _catalog():
    """باقات CATALOG بمعرّفها، ومع كلٍّ سيرفرها (‏brand) لاسمها بالإنجليزية، وكود خصم علامته (‏promo) إن كان لها
    ولم تُستثنَ الباقة منه (‏nopromo، كاليوم التجريبي)."""
    return {p["id"]: dict(p, brand=k, promo=None if p.get("nopromo") else b.get("promo"))
            for k, b in tournament._catalog().items() for p in b.get("plans", [])}


def _promo(p, tr=AR):
    """كود الخصم لأول طلب على باقةٍ من _catalog (‏promo في CATALOG: كوبون سلة نفسه) وما يدفعه صاحب أول طلب به:
    «53.20 ر.س بكود NEW30» — أو "" لباقةٍ بلا كود."""
    pr = p.get("promo")
    if not pr:
        return ""
    v = round(_money(p.get("price")) * (100 - pr["pct"])) / 100
    after = str(int(v)) if v == int(v) else f"{v:.2f}"
    return tr(f"{after} ر.س بكود {pr['code']}", f"{after} SAR with code {pr['code']}")


def _dur_en(s):
    """مدّةٌ من CATALOG بالإنجليزية: «15 شهرًا» ← «15 months»، «شهر» ← «1 month»، «24 ساعة» ← «24 hours»."""
    s = str(s or "").translate(C._DIG)
    for ar, word in _DUR_EN:
        if re.search(ar, s):
            m = re.search(r"\d+", s)
            n = int(m.group()) if m else 2 if _TWO.search(s) else 1
            return f"{n} {word}" + ("" if n == 1 else "s")
    return ""


def _plan(p, tr=AR, srv=None):
    """اسم الباقة وسطرها تحته كما في CATALOG («فالكون · 15 شهرًا»، «الأكثر توازنًا») — وبالإنجليزية اسم سيرفرها
    ومدّتها («Falcon · 15 months»، «Best balance»)، ووسمٌ لم يُترجم (‏TAG_EN) مكانه المدّة."""
    if not tr.en:
        return p["name"], p.get("tag") or p.get("dur") or ""
    rest = p["name"].rpartition(" · ")[2]
    what = " ".join([PLAN_EN.get(rest) or _dur_en(rest) or _dur_en(p.get("dur"))]
                    + [en for ar, en in PLAN_FOR_EN if ar in rest]).strip()
    brand = (tr.name(srv) if srv and srv["key"] == p.get("brand")
             else C.EN_NAMES.get(p.get("brand")) or str(p.get("brand") or "").title())
    return " · ".join(x for x in (brand, what) if x), TAG_EN.get(p.get("tag") or "") or _dur_en(p.get("dur"))


def _ad(srv, c, tr=AR):
    """إعلان الاشتراك في أعلى الصفحة تحت السيرفرات — أول ما يراه الزائر، وعلى الجوال قبل الجانب بكثير: باقات السيرفر نفسه من CATALOG
    (‏C.PLANS) بأسعارها وخصمها، أو رابط شرائه من صفحة المدير، أو باقات إعلان الموقع (‏tournament.ADS) لسيرفرٍ
    بلا هذا ولا ذاك. وروابطه بحملة ‏content-ad."""
    catalog = _catalog()
    own = [catalog[i] for i in C.PLANS.get(srv["key"], ()) if i in catalog]
    plans = own or ([] if srv["buy"] else [catalog[i] for i in tournament.ADS if i in catalog])
    if not plans and not srv["buy"]:
        return ""
    cards, code = [], None
    for p in plans[:3]:
        price, was = _money(p.get("price")), _money(p.get("was"))
        off = round((1 - price / was) * 100) if was > price > 0 else 0
        pct = off if off >= 5 else (p["promo"]["pct"] if p.get("promo") else 0)   # الشطب أولًا، وإلا خصم الكود
        code = code or (p.get("promo") or {}).get("code")
        pname, psub = _plan(p, tr, srv)
        cards.append(f'<a class="adplan" href="{_esc(_utm(p["url"], AD_CAMPAIGN))}" target="_blank" rel="noopener">'
                     + (f'<span class="off">-{pct}%</span>' if pct else "")
                     + f'<img src="{_esc(p["img"])}" alt="" width="56" height="56" loading="lazy">'
                     f'<span class="t"><b>{_esc(pname)}</b><small>{_esc(psub)}</small></span>'
                     f'<em>{_esc(p["price"])} {tr("ر.س", "SAR")}' + (f'<s>{_esc(p["was"])}</s>' if off >= 5 else "")
                     + "</em>" + (f'<span class="aft">{_esc(_promo(p, tr))}</span>' if p.get("promo") else "") + "</a>")
    name = _esc(tr.name(srv))
    buy = _utm(srv["buy"], AD_CAMPAIGN) if srv["buy"] else _utm(plans[0]["url"], AD_CAMPAIGN)
    mine = bool(own or srv["buy"])
    summary = _summary_text(c, tr)
    pitch = tr(*PITCH)
    brand = tr("اشتراكات سمارت سوق", f"{BRAND_EN} subscriptions")
    return (f'<aside class="ad" aria-label="{tr("إعلان: ", "Ad: ")}'
            f'{(tr("اشتراك " + name, name + " subscription") if mine else brand)}">'
            f'<div class="adtext"><span class="eyebrow">{tr("إعلان", "Ad")}</span>'
            + (f'<h2>{tr(f"كل هذا المحتوى في اشتراك {name}", f"All this content in a {name} subscription")}</h2>'
               f'<p>{_esc(summary)} — {tr(pitch, pitch[:1].lower() + pitch[1:])}' if mine else f'<h2>{brand}</h2><p>{pitch}')
            + '</p>'
            + (f'<p class="adcode">{tr("لأول طلب: اكتب الكود", "First order: enter code")} <code>{_esc(code)}</code> '
               f'{tr("في «عندك كوبون خصم؟» بصفحة الدفع", "in the coupon field at checkout")}</p>' if code else "")
            + f'<div class="adbtns"><a class="btn" href="{_esc(buy)}" target="_blank" rel="noopener">'
            + (tr(f"اشترك في {name}", f'Subscribe<span class="wide"> to {name}</span>') if mine
               else tr("اشترك الآن", "Subscribe now")) + '</a>'
            f'<a class="btn ghost" href="/#buy">{tr("ساعدني في الاختيار", "Help me choose")}</a></div></div>'
            + (f'<div class="adplans">{"".join(cards)}</div>' if cards else "") + "</aside>")


def _cta(srv, tr=AR):
    """باقات الاشتراك: رابط شراء السيرفر من صفحة المدير، أو باقاته من CATALOG في index.html، أو الدليل.
    ← (HTML، رابط زرّ الاشتراك في النافذة)."""
    name = _esc(tr.name(srv))
    rows, first = [], ""
    if not srv["buy"]:
        plans = _catalog()
        for pid in C.PLANS.get(srv["key"], ()):
            p = plans.get(pid)
            if not p:
                continue
            url = _utm(p["url"])
            first = first or url
            pname, psub = _plan(p, tr, srv)
            rows.append(f'<a class="plan" href="{_esc(url)}" target="_blank" rel="noopener">'
                        f'<img src="{_esc(p["img"])}" alt="" width="42" height="42" loading="lazy">'
                        f'<span><b>{_esc(pname)}</b><small>{_esc(psub)}</small></span>'
                        f'<em>{_esc(p["price"])} {tr("ر.س", "SAR")}'
                        + (f'<i class="aft">{_esc(_promo(p, tr))}</i>' if p.get("promo") else "") + '</em></a>')
    buy = _utm(srv["buy"]) if srv["buy"] else ""
    link = buy or first or "/#buy"
    subscribe = tr(f"اشترك في {name}", f"Subscribe to {name}")
    html = (f'<section class="panel cta"><h2>{subscribe}</h2><p>{tr(*PITCH)}</p>'
            + "".join(rows)
            + (f'<a class="btn" href="{_esc(buy)}" target="_blank" rel="noopener">{subscribe}</a>' if buy else "")
            + f'<div class="btns"><a class="btn ghost" href="/#buy">{tr("ساعدني في الاختيار", "Help me choose")}</a>'
            f'<a class="btn ghost" href="/#plans">{tr("كل الباقات", "All plans")}</a></div></section>')
    return html, link


def _pager(base, page, pages, tr=AR, **kw):
    if pages < 2:
        return ""
    prev = f'<a href="{_link(base, **kw, p=page - 1)}">{tr("→ السابق", "← Previous")}</a>' if page > 1 else "<span></span>"
    nxt = f'<a href="{_link(base, **kw, p=page + 1)}">{tr("التالي ←", "Next →")}</a>' if page < pages else "<span></span>"
    return (f'<nav class="pager" aria-label="{tr("الصفحات", "Pages")}">{prev}'
            f'<span>{tr(f"صفحة {page} من {pages}", f"Page {page} of {pages}")}</span>{nxt}</nav>')


def results_html(data_dir, key, srv, v, q, tr=AR):
    """نتائج البحث بالاسم ملصقاتٍ: لكل نوعٍ أوّل C.SEARCH_MAX بقسمها، ثم أين يوجد الاسم في السيرفرات الأخرى —
    فمن لم يجد مسلسله هنا يعرف أيّ اشتراكٍ فيه."""
    q = " ".join(str(q or "").split())[:C.QUERY_MAX]
    if not C._words(q):
        return ""
    hits, total = C._search(key, v, q)
    fixed = C.suggest(key, v, q) if not total else ""        # «ياب الحارة» ← «باب الحارة»
    shown = q
    if fixed:
        hits, total = C._search(key, v, fixed)
        surf = {}                    # الكلمة المصحَّحة كما في أسماء النتائج («الموسس» ← «المؤسس»)
        for kind in C.SEARCH_KINDS:
            for gi, ii in hits[kind][0][:12]:
                for t in v["kinds"][kind][gi]["items"][ii].get("n", "").split():
                    surf.setdefault(C._norm(t), t)
        typed, fx = q.split(), fixed.split()
        shown = (" ".join(t if C._norm(t) == f else surf.get(f, f) for t, f in zip(typed, fx))
                 if len(typed) == len(fx) else " ".join(surf.get(f, f) for f in fx))
    look = fixed or q
    parts = []
    for kind in C.KINDS:
        top, n = hits[kind]
        if not n:
            continue
        more = ('<p class="empty">' + tr(f"و{C._count(n - len(top), C.N_RESULTS)} أخرى — اكتب الاسم أدقّ.",
                                         f"{n - len(top):,} more — type the name more precisely.") + "</p>"
                if n > len(top) else "")
        parts.append(f'<h3>{tr.tab(kind)} <small>({n:,})</small></h3>'
                     f'<div class="grid">{_cards(key, v, kind, top, tr=tr)}</div>{more}')
    elsewhere = []
    for s in C.servers(data_dir):
        ov = C._view(data_dir, s["key"])[1] if s["key"] != key else None
        if not C._has(ov):
            continue
        there = look if C._search(s["key"], ov, look)[1] or total else (C.suggest(s["key"], ov, q) or q)
        n = C._search(s["key"], ov, there)[1]
        if n:
            elsewhere.append(f'<a href="{tr.path}/{s["key"]}?q={quote(shown if there == look else there)}">'
                             f'{_logo(s["key"], tr.name(s), "lg sm")}'
                             f'{_esc(tr.name(s))} ({n:,})</a>')
    other = (f'<p class="other">{tr("ويوجد أيضًا في", "Also on") if total else tr("لكنه موجود في", "But it’s on")}: '
             f'{" · ".join(elsewhere)}</p>' if elsewhere else "")
    name = _esc(tr.name(srv))
    if not total:
        live = (tr(" — والقنوات في ", " — channels are in ") + f'<a class="link" href="{tr.path}/{key}?t=live">'
                + tr("تبويبها", "their own tab") + "</a>" if v["kinds"]["live"] else "")
        return (f'<section class="results"><div class="rh"><h2>'
                f'{tr("لا يوجد ", "No results for ")}{tr.quote(_esc(q))}{tr(" في ", " in ")}{name}</h2></div>'
                + (other or '<p class="empty">'
                   + tr("البحث باسم المسلسل أو الفيلم: جرّب جزءًا من الاسم، أو اكتبه بالإنجليزية أو بالعربية",
                        "Search by series or movie name: try part of the name, or type it in English or Arabic")
                   + live + '.</p>')
                + "</section>")
    fix = (f'<p class="fix">{tr("لا يوجد ", "No exact match for ")}{tr.quote(_esc(q))}'
           f'{tr(" كما كُتب، فهذه نتائج أقرب اسمٍ إليه.", ", so these are the results for the closest name.")}</p>'
           if fixed else "")
    return (f'<section class="results"><div class="rh"><h2>{tr("نتائج ", "Results for ")}{tr.quote(_esc(shown))}'
            f'{tr(" في ", " in ")}{name} <small>{tr.count(total, "results")}</small></h2></div>'
            f'{fix}{"".join(parts)}{other}</section>')


def api_search(data_dir, key, q, lang="ar"):
    srv, v = C._view(data_dir, key)
    if not C._has(v):
        return None
    return {"ok": True, "html": results_html(data_dir, key, srv, v, q, lang_of(lang))}


# ================= الصفحة =================
def _int(v, lo=0, hi=10 ** 6):
    try:
        n = int(str(v or "").strip())
    except ValueError:
        return 0
    return n if lo <= n <= hi else 0


def _alt(tr, key, query):
    """الصفحة نفسها باللغة الأخرى بما فيها من قسمٍ وتصفيةٍ وبحث — لزرّ اللغة."""
    keep = [(k, str(query.get(k) or "").strip()) for k in QUERY]
    keep = [(k, x) for k, x in keep if x]
    return f"{(AR if tr.en else EN).path}/{key}" + ("?" + urlencode(keep) if keep else "")


def render(data_dir, key, query, lang="ar"):
    """صفحة السيرفر ← (رمز HTTP، بايتات، ثواني الكاش). ‏query: ‏t النوع (أو new)، g القسم، view=grid التصفية
    (y السنة، genre التصنيف، r أدنى تقييم، sort الترتيب)، all=1 كل الأقسام، p الصفحة، q البحث. و‏lang: ‏ar أو en."""
    tr = lang_of(lang)
    srv, v = C._view(data_dir, key)
    if not srv or not C._has(v):
        code, body = render_missing(data_dir, key, lang)
        return code, body, 300
    get = lambda k: str(query.get(k) or "").strip()  # noqa: E731
    kinds = [k for k in C.KINDS if v["kinds"][k]]
    t = get("t") if get("t") in kinds + ["new"] else ""
    if t == "new" and not any(v["recent"][k] for k in C.KINDS):
        t = ""
    gid, q = get("g"), " ".join(get("q").split())[:C.QUERY_MAX]
    cur = {"y": _int(get("y"), 1900, C.YEAR_MAX), "genre": get("genre")[:40], "r": _int(get("r"), 1, 9),
           "sort": get("sort") if get("sort") in ("new", "az", "rate") else "new", "g": gid}
    page = max(1, _int(get("p"), 1))
    base = f"{tr.path}/{key}"
    c, name, code = v["counts"], tr.name(srv), 200
    cta, cta_link = _cta(srv, tr)
    main, side, head = [], [], ""
    kind = t if t in C.KINDS else ""
    gi = v["byid"][kind].get(gid) if kind and gid else None
    if kind and gid and gi is None:
        code = 404
    if t == "" and not gid:
        head = _hero(key, v, tr) + _stats(c, tr) + _kinds(base, v, t, tr)
        for k in ("movie", "series", "live"):
            if v["recent"][k]:
                label = {"movie": tr("أفلام أضيفت مؤخرًا", "Recently added movies"),
                         "series": tr("مسلسلات جديدة أو بحلقاتٍ جديدة", "New series and new episodes"),
                         "live": tr("قنوات أضيفت مؤخرًا", "Recently added channels")}[k]
                main.append(_row(label, _cards(key, v, k, v["recent"][k][:ROW_MAX], when=True, tr=tr),
                                 _link(base, t="new"), tr("عرض الكل", "View all"), tr))
        for k, n in (("movie", 3), ("series", 3), ("live", 2)):
            for g in v["kinds"][k][:n]:
                top = _sel(v, k, gid=g["id"])[:ROW_MAX]
                main.append(_row(f'{_esc(g["name"])} <small>· {tr.one(k)}</small>', _cards(key, v, k, top, tr=tr),
                                 _link(base, t=k, g=g["id"]), tr("عرض الكل", "View all") + f' ({len(g["items"]):,})', tr))
        side += [_recent_list(key, v, ("movie", "series"), tr), cta]
    elif t == "new":
        head = _stats(c, tr) + _kinds(base, v, t, tr)
        main.append(f'<div class="gh"><h1>{_i("new")} {tr("أضيف مؤخرًا في ", "Recently added to ")}{_esc(name)}</h1>'
                    '<span class="sub">' + tr("الأحدث أولًا، بترتيب إضافتها إلى السيرفر",
                                              "Newest first, in the order they were added to the server") + '</span></div>')
        for k in C.KINDS:
            if v["recent"][k]:
                label = {"movie": tr("أفلام", "Movies"), "live": tr("قنوات", "Channels"),
                         "series": tr("مسلسلات جديدة أو بحلقاتٍ جديدة", "New series and new episodes")}[k]
                main.append(f'<section class="row"><div class="rh"><h2>{label}</h2></div><div class="grid">'
                            f'{_cards(key, v, k, v["recent"][k][:NEW_MAX[k]], when=True, tr=tr)}</div></section>')
        side += [cta]
    elif kind and get("all"):
        head = _stats(c, tr) + _kinds(base, v, t, tr)
        chips = "".join(_chip(key, base, v, kind, n, g, tr) for n, g in enumerate(v["kinds"][kind]))
        main.append(f'<div class="gh"><h1>{tr("أقسام " + tr.tab(kind), tr.one(kind) + " categories")}</h1>'
                    f'<span class="sub">{tr.count(len(v["kinds"][kind]), "groups")}</span>'
                    f'</div><div class="chipgrid">{chips}</div>')
        side += [_filters(base, v, kind, cur, tr), _recent_list(key, v, (kind,), tr), cta]
    elif kind and (gi is not None or get("view") == "grid"):
        head = _kinds(base, v, t, tr)
        picks = _sel(v, kind, gid=gid if gi is not None else "", year=cur["y"], genre=cur["genre"],
                     rating=cur["r"], sort=cur["sort"])
        pages = max(1, (len(picks) + GRID - 1) // GRID)
        page = min(page, pages)
        title = (_esc(v["kinds"][kind][gi]["name"]) if gi is not None
                 else f'{tr.tab(kind)}{tr(" في ", " in ")}{_esc(name)}')
        chosen = [str(cur["y"]) if cur["y"] else "", cur["genre"],
                  tr(f"تقييم {cur['r']} فأعلى", f"rated {cur['r']}+") if cur["r"] else ""]
        chosen = " · ".join(x for x in chosen if x)
        main.append(f'<div class="gh"><h1>{title}</h1><span class="sub">{tr.count(len(picks), kind)}'
                    + (f" · {_esc(chosen)}" if chosen else "") + "</span></div>"
                    + (f'<div class="grid">{_cards(key, v, kind, picks[(page - 1) * GRID:page * GRID], tr=tr)}</div>'
                       if picks else '<p class="empty">' + tr("لا نتائج بهذا الفلتر — وسّعه أو اختر «الكل».",
                                                              "No results with this filter — widen it or choose “All”.")
                       + "</p>")
                    + _pager(base, page, pages, tr, t=kind, g=gid if gi is not None else "",
                             view="grid" if gi is None else "", y=cur["y"], genre=cur["genre"], r=cur["r"],
                             sort=cur["sort"] if cur["sort"] != "new" else ""))
        side += [_filters(base, v, kind, cur, tr), _recent_list(key, v, (kind,), tr), cta]
    else:                                   # صفحة النوع: الأقسام صورًا ثم صفٌّ لكل قسم
        kind = kind or kinds[0]
        t = kind
        head = _stats(c, tr) + _kinds(base, v, t, tr)
        miss = ('<p class="empty">' + tr("هذا القسم لم يعد موجودًا، واختر من الأقسام الحالية.",
                                         "This category no longer exists — choose one of the current categories.")
                + "</p>" if code == 404 else "")
        main.append(miss + _chips(key, base, v, kind, tr))
        for g in v["kinds"][kind][:ROWS_MAX]:
            top = _sel(v, kind, gid=g["id"])[:ROW_MAX]
            main.append(_row(_esc(g["name"]), _cards(key, v, kind, top, tr=tr), _link(base, t=kind, g=g["id"]),
                             tr("عرض الكل", "View all") + f' ({len(g["items"]):,})', tr))
        if len(v["kinds"][kind]) > ROWS_MAX:
            n = f'({len(v["kinds"][kind]):,})'
            main.append(f'<p class="empty"><a class="link" href="{_link(base, t=kind, all=1)}">'
                        + tr(f"كل أقسام {tr.tab(kind)} {n} ←", f"All {tr.one(kind).lower()} categories {n} →") + "</a></p>")
        side += [_filters(base, v, kind, cur, tr), _recent_list(key, v, (kind,), tr), cta]
    ad = _ad(srv, c, tr) if code == 200 else ""    # في أعلى الصفحة تحت السيرفرات — ونتائج البحث قبله
    summary = _summary_text(c, tr)
    what = tr.join(x for k, x in (("series", tr("المسلسلات بمواسمها", "series with their seasons")),
                                  ("movie", tr("الأفلام", "movies")), ("live", tr("القنوات", "channels"))) if c[k])
    title = tr(f"محتوى اشتراك {name}: {what} | سمارت سوق", f"{name} subscription content: {what} | {BRAND_EN}")
    desc = (tr(f"ما في اشتراك {name} قبل أن تشتري: {summary}. ابحث باسم أي مسلسل أو فيلم",
               f"What’s in the {name} subscription before you buy: {summary}. Search any series or movie by name")
            + (tr(" واعرف مواسم المسلسل وحلقات كل موسم", ", see each series’ seasons and episodes") if c["series"] else "")
            + tr("، وتصفّح ما أضيف مؤخرًا. يُحدَّث تلقائيًا من قائمة الاشتراك نفسها.",
                 ", and browse what was recently added. Updated automatically from the subscription’s own playlist."))
    index = code == 200 and not (q or gid or get("t") or get("view") or get("p") or get("all"))
    body = (_header(base, srv, v, t, q, key, tr, _alt(tr, key, query)) + '<main class="wrap">' + _servers(data_dir, key, tr)
            + (f'<h1 class="sr">{tr(f"محتوى اشتراك {_esc(name)}", f"{_esc(name)} subscription content")}</h1>'
               if t == "" and not gid else "")
            + '<div id="cres" aria-live="polite">' + (results_html(data_dir, key, srv, v, q, tr) if q else "") + "</div>"
            + ad + head + '<div class="layout"><div class="col">' + "".join(main) + "</div>"
            + f'<aside class="side">{"".join(side)}</aside></div></main>' + _footer(base, name, v, summary, tr))
    pair = [(x.code, f"{guide_pages.SITE}{x.path}/{key}") for x in (AR, EN)]
    return code, _doc(title, desc, guide_pages.SITE + base, index, body, key, name, cta_link, tr,
                      pair + [("x-default", pair[0][1])]), 600


def _summary_text(c, tr=AR):
    """«3,210 مسلسلات بمواسمها و45,678 فيلمًا و4,321 قناة» — بما في السيرفر وحده."""
    bits = [tr.count(c["series"], "series") + tr(" بمواسمها", " with their seasons") if c["series"] else "",
            tr.count(c["movie"], "movie") if c["movie"] else "", tr.count(c["live"], "live") if c["live"] else ""]
    return tr.join(b for b in bits if b)


def _footer(base, name, v, summary, tr=AR):
    at = _when(v["at"], tr) if v["at"] else ""
    return (f'<footer class="foot"><div class="wrap"><p><a href="/">{tr("دليل سمارت سوق", BRAND_EN + " guide")}</a> '
            f'{tr("←", "→")} <a href="{_esc(base)}">{tr("محتوى " + _esc(name), _esc(name) + " content")}</a></p>'
            f'<p>{_esc(summary)} — {tr("من قائمة الاشتراك نفسها", "from the subscription’s own playlist")}'
            + (tr(f" · آخر تحديث: {at} بتوقيت السعودية", f" · Last updated: {at} (Saudi time)") if at else "")
            + "</p>" + ("" if tr.en else          # صفحة البلاغ عربيةٌ وحدها، وسيرفر الصفحة مختارٌ فيها
                        f'<p><a class="link" href="/report?s={_esc(base.rsplit("/", 1)[-1])}">مشترك وفيديو لا يعمل أو يقطع؟ بلّغنا</a></p>')
            + "</div></footer>")


def render_missing(data_dir, key="", lang="ar"):
    """لا محتوى بعد (أو سيرفرٌ لا وجود له): صفحةٌ تدلّ على ما وُجد، لا تُفهرس ← (404، بايتات)."""
    tr = lang_of(lang)
    others = [s for s in C.servers(data_dir) if s["key"] != key and C.has(data_dir, s["key"], s)]
    links = "".join(f'<li><a class="link" href="{tr.path}/{s["key"]}">{_logo(s["key"], tr.name(s), "lg sm")}'
                    f'{tr("محتوى " + _esc(tr.name(s)), _esc(tr.name(s)) + " content")}</a></li>' for s in others)
    here = f"{tr.path}/{key}" if C._server(data_dir, key) else tr.path
    other = f"{(AR if tr.en else EN).path}" + here[len(tr.path):]
    body = (f'<main class="wrap"><section class="panel missing"><h1>{tr("محتوى الاشتراكات", "Subscription content")}</h1>'
            f'<p>{tr("لم يُنشر محتوى هذا السيرفر بعد.", "This server’s content hasn’t been published yet.")}</p>'
            + (f'<p class="empty">{tr("وهذه السيرفرات منشورٌ محتواها:", "These servers have published content:")}</p>'
               f'<ul>{links}</ul>' if links else "")
            + f'<div class="btns"><a class="btn" href="/#buy">{tr("ساعدني في الاختيار", "Help me choose")}</a>'
            f'<a class="btn ghost" href="/">{tr("الدليل", "Guide")}</a>{_switch(tr, other)}</div></section></main>')
    return 404, _doc(tr("محتوى الاشتراكات | سمارت سوق", f"Subscription content | {BRAND_EN}"),
                     tr("المسلسلات بمواسمها والأفلام والقنوات في كل اشتراك.",
                        "Series with their seasons, movies and channels in every subscription."),
                     guide_pages.SITE + tr.path, False, body, key, "", "/#buy", tr)


CSS = """
:root{color-scheme:dark;--bg:#060b17;--bg2:#0a1223;--card:#0e172c;--card2:#132039;--line:#1c2a4a;--line2:#29406b;
  --ink:#eaf0ff;--mute:#8fa2c6;--acc:#2f8cff;--acc2:#1767d8;--gold:#f6c343;--green:#22c493}
*{box-sizing:border-box}
html{scroll-padding-top:84px}
body{margin:0;background:radial-gradient(1100px 520px at 100% -8%,rgba(47,140,255,.16),transparent 60%),
  radial-gradient(900px 480px at 0 0,rgba(124,58,237,.10),transparent 60%),var(--bg);color:var(--ink);
  font:15px/1.6 "IBM Plex Sans Arabic","Amazon-Ember",Tahoma,sans-serif;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
a.link{color:var(--acc)}
img{display:block;max-width:100%}
button{font:inherit;color:inherit}
[hidden]{display:none!important}
:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.i{width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;flex:none}
.star{width:14px;height:14px;flex:none}
.wrap{max-width:1280px;margin:0 auto;padding:0 18px}
/* الرأس */
.top{position:sticky;top:0;z-index:40;background:rgba(6,11,23,.84);backdrop-filter:saturate(1.4) blur(14px);border-bottom:1px solid var(--line)}
.top .wrap{display:flex;align-items:center;gap:18px;min-height:68px}
.brand{display:flex;align-items:center;gap:10px;flex:none}
.brand img,.brand .bi{width:42px;height:42px;border-radius:12px;object-fit:cover;background:var(--card2)}
.brand .bi{display:grid;place-items:center;color:var(--acc)}
.brand b{display:block;font-size:1.2rem;line-height:1.15}
.brand small{display:block;color:var(--mute);font-size:.72rem;letter-spacing:.04em;direction:ltr;text-align:right}
.nav{display:flex;gap:2px;overflow-x:auto;scrollbar-width:none}
.nav::-webkit-scrollbar{display:none}
.nav a{padding:9px 13px;border-radius:10px;color:var(--mute);font-weight:600;white-space:nowrap}
.nav a:hover{color:var(--ink);background:var(--card)}
.nav a[aria-current]{color:var(--acc)}
.search{margin-inline-start:auto;display:flex;align-items:center;gap:8px;min-width:290px;background:var(--card);
  border:1px solid var(--line);border-radius:12px;padding:0 12px}
.search:focus-within{border-color:var(--acc)}
.search input{flex:1;min-width:0;background:transparent;border:0;outline:0;color:var(--ink);font:inherit;padding:11px 0}
.search input::placeholder{color:var(--mute)}
.search button{background:none;border:0;color:var(--mute);cursor:pointer;padding:4px;display:grid}
.lang{display:inline-flex;align-items:center;gap:6px;flex:none;padding:8px 12px;border-radius:10px;border:1px solid var(--line);
  color:var(--mute);font-weight:600;font-size:.9rem;white-space:nowrap}
.lang:hover{color:var(--ink);border-color:var(--line2)}
.lang .i{width:17px;height:17px}
@media (max-width:900px){.top{position:static}.top .wrap{flex-wrap:wrap;gap:8px 12px;padding-block:10px}
  .search{order:3;min-width:0;flex:1 1 100%}.nav{order:2;flex:1 1 100%}.top .lang{order:1;margin-inline-start:auto}}
.servers{display:flex;align-items:center;gap:10px;margin-top:16px;overflow-x:auto;scrollbar-width:none;padding:2px}
.servers::-webkit-scrollbar{display:none}
.servers .lbl{color:var(--mute);font-size:.88rem;flex:none}
.servers a{display:flex;align-items:center;gap:10px;flex:none;padding:6px;padding-inline-end:16px;border-radius:14px;
  border:1px solid var(--line);background:var(--card);color:var(--ink)}
.servers a:hover{border-color:var(--line2)}
.servers a[aria-current]{border-color:var(--acc);background:linear-gradient(135deg,rgba(47,140,255,.24),rgba(47,140,255,.07));
  box-shadow:inset 0 0 0 1px var(--acc)}
.servers b{display:block;font-size:.95rem;line-height:1.25}
.servers small{display:block;color:var(--mute);font-size:.68rem;letter-spacing:.04em;direction:ltr;text-align:right}
.lg{width:40px;height:40px;border-radius:10px;object-fit:cover;flex:none;background:var(--card2)}
.lg.bi{display:grid;place-items:center;font-weight:700;color:#fff;background:linear-gradient(135deg,hsl(var(--h) 50% 34%),hsl(var(--h) 55% 18%))}
.lg.sm{width:22px;height:22px;border-radius:6px;font-size:.72rem}
@media (max-width:520px){.servers .lbl,.servers small{display:none}.servers a{gap:8px;padding-inline-end:12px}.servers .lg{width:34px;height:34px}}
/* الواجهة */
.herobox{display:grid;grid-template-columns:minmax(0,1fr) 290px;gap:14px;margin-top:16px}
.hero{position:relative;border-radius:22px;overflow:hidden;border:1px solid var(--line);background:var(--card);min-height:340px}
.slide{position:absolute;inset:0;display:none;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:28px;
  padding:34px 64px 44px;cursor:pointer}
.slide.on{display:grid;animation:fade .6s ease}
@keyframes fade{from{opacity:.25}to{opacity:1}}
.slide .bg{position:absolute;inset:-24px;width:calc(100% + 48px);height:calc(100% + 48px);max-width:none;object-fit:cover;
  filter:blur(18px) saturate(1.25) brightness(.5)}
.slide::after{content:"";position:absolute;inset:0;background:linear-gradient(270deg,rgba(6,11,23,.92),rgba(6,11,23,.55) 55%,rgba(6,11,23,.15))}
.slide>*:not(.bg){position:relative;z-index:1}
.slide .info{max-width:600px}
.kick{display:inline-flex;align-items:center;gap:6px;font-size:.8rem;font-weight:700;color:#bfe0ff;
  background:rgba(47,140,255,.18);border:1px solid rgba(47,140,255,.35);border-radius:999px;padding:4px 12px}
.kick .i{width:15px;height:15px}
.slide h2{font-size:clamp(1.5rem,3.4vw,2.6rem);line-height:1.2;margin:12px 0 8px;text-shadow:0 4px 24px rgba(0,0,0,.6)}
.facts{color:#c9d6f0;margin:0 0 6px;font-weight:500}
.plot{color:#aebbd6;margin:10px 0 0;font-size:.92rem;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:12px 22px;border:0;border-radius:12px;
  background:linear-gradient(135deg,var(--acc),var(--acc2));color:#fff;font-weight:700;cursor:pointer;box-shadow:0 10px 26px -12px var(--acc)}
.btn:hover{filter:brightness(1.08)}
.btn.ghost{background:transparent;border:1px solid var(--line2);box-shadow:none}
.slide .btn{margin-top:18px}
.slide .rt{display:flex;width:max-content}
.slide .poster{width:190px;aspect-ratio:2/3;object-fit:cover;border-radius:14px;box-shadow:0 24px 48px -16px rgba(0,0,0,.8);
  border:1px solid rgba(255,255,255,.08)}
.harrow{position:absolute;top:50%;transform:translateY(-50%);z-index:2;width:40px;height:40px;border-radius:50%;
  border:1px solid rgba(255,255,255,.2);background:rgba(6,11,23,.55);color:#fff;cursor:pointer;display:grid;place-items:center}
.harrow.prev{inset-inline-start:12px}.harrow.next{inset-inline-end:12px}
.dots{position:absolute;bottom:14px;inset-inline:0;display:flex;justify-content:center;gap:6px;z-index:2}
.dots button{width:8px;height:8px;border-radius:99px;border:0;background:rgba(255,255,255,.35);cursor:pointer;padding:0;transition:width .2s}
.dots button[aria-current]{width:22px;background:#fff}
.hlist{display:flex;flex-direction:column;gap:10px}
.hlist button{display:flex;align-items:center;gap:12px;text-align:start;padding:9px;border-radius:16px;border:1px solid var(--line);
  background:var(--card);cursor:pointer;flex:1;min-height:0}
.hlist button[aria-current]{border-color:var(--acc);background:var(--card2)}
.hlist .pos{width:52px;flex:none;border-radius:10px}
.hlist .ph{font-size:.9rem}
.hlist b{display:block;font-size:.93rem;line-height:1.35;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.hlist small{color:var(--mute)}
@media (max-width:900px){.herobox{grid-template-columns:1fr}.hlist{display:none}.slide{padding:26px 22px 44px;grid-template-columns:1fr}
  .slide .poster{display:none}.hero{min-height:310px}.harrow{display:none}}
/* الأعداد والتبويبات */
.stats{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin-top:16px}
.stat{display:flex;align-items:center;gap:14px;padding:16px 18px;border-radius:16px;border:1px solid var(--line);
  background:linear-gradient(160deg,var(--card2),var(--card))}
.stat .i{width:34px;height:34px;color:var(--acc)}
.stat b{display:block;font-size:1.55rem;line-height:1.2;font-variant-numeric:tabular-nums}
.stat small{color:var(--mute)}
@media (max-width:900px){.stats{display:flex;flex-wrap:wrap}.stat{flex:1 1 30%;min-width:0}}   /* 3 ثم ما بقي بعرض الصف */
@media (max-width:520px){.stats{gap:8px}
  .stat{flex-direction:column;align-items:center;text-align:center;gap:4px;padding:10px 4px}
  .stat .i{width:24px;height:24px}.stat b{font-size:1.12rem}.stat small{font-size:.74rem}
  .nav a.home{display:none}.nav a{padding:8px 9px;font-size:.9rem}}
.kinds{display:flex;gap:10px;margin:18px 0 4px;flex-wrap:wrap}
.kinds a{display:inline-flex;align-items:center;gap:9px;padding:12px 20px;border-radius:14px;border:1px solid var(--line);
  background:var(--card);font-weight:700}
.kinds a:hover{border-color:var(--line2)}
.kinds a[aria-current]{background:linear-gradient(135deg,var(--acc),var(--acc2));border-color:transparent;box-shadow:0 10px 26px -14px var(--acc)}
.kinds .i{width:22px;height:22px}
.kinds small{opacity:.8;font-weight:500}
@media (max-width:520px){.kinds a{flex:1 1 40%;justify-content:center;padding:11px 12px}}
/* التخطيط */
.layout{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:24px;margin-top:10px}
.col{min-width:0}
@media (max-width:1000px){.layout{grid-template-columns:1fr}}
/* الأقسام صورًا */
.chips{display:grid;grid-auto-flow:column;grid-auto-columns:130px;gap:10px;overflow-x:auto;padding:10px 0;scroll-snap-type:x proximity;scrollbar-width:thin}
.chip{position:relative;min-height:104px;border-radius:14px;overflow:hidden;border:1px solid var(--line);
  background:linear-gradient(135deg,var(--card2),var(--card));scroll-snap-align:start;display:flex;align-items:flex-end;
  justify-content:center;text-align:center;padding:10px}
.chip img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:.55;transition:opacity .2s,transform .3s}
.chip:hover img{opacity:.75;transform:scale(1.05)}
.chip::after{content:"";position:absolute;inset:0;background:linear-gradient(0deg,rgba(6,11,23,.92),transparent 75%)}
.chip span{position:relative;z-index:1}
.chip b{display:block;font-size:.86rem;line-height:1.3}
.chip small{color:#c9d6f0;font-size:.72rem}
.chip.more{align-items:center;border-style:dashed;color:var(--acc)}
.chip.more .i{margin:0 auto 4px}
.chipgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px}
/* الصفوف والشبكة */
.row{margin:24px 0}
.rh{display:flex;align-items:center;gap:12px;margin-bottom:12px}
.rh h2{margin:0;font-size:1.25rem;border-inline-start:4px solid var(--acc);padding-inline-start:10px;line-height:1.3}
.rh small{color:var(--mute);font-weight:500;font-size:.85rem}
.rh .more{margin-inline-start:auto;color:var(--acc);font-weight:600;font-size:.92rem;white-space:nowrap}
.rbtn{display:flex;gap:6px}
.arrow{width:32px;height:32px;border-radius:50%;border:1px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer;display:grid;place-items:center}
.arrow .i{width:16px;height:16px}
@media (max-width:700px){.rbtn{display:none}}
.cards{display:grid;grid-auto-flow:column;grid-auto-columns:clamp(126px,14.6vw,168px);gap:14px;overflow-x:auto;
  scroll-snap-type:x proximity;padding:4px 2px 12px;scrollbar-width:thin}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(148px,1fr));gap:18px 16px}
@media (max-width:520px){.grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:14px 12px}}
/* الملصق */
.card{min-width:0;scroll-snap-align:start;cursor:pointer;border-radius:14px}
.pos{position:relative;display:block;aspect-ratio:2/3;border-radius:14px;overflow:hidden;border:1px solid var(--line);
  background:linear-gradient(135deg,hsl(var(--h,220) 45% 27%),hsl(calc(var(--h,220) + 40) 55% 12%))}
.card .pos{box-shadow:0 14px 30px -18px rgba(0,0,0,.9);transition:transform .2s,border-color .2s}
.card:hover .pos,.card:focus-visible .pos{transform:translateY(-4px);border-color:var(--acc)}
.pos img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.ph{position:absolute;inset:0;display:grid;place-items:center;font-size:1.8rem;font-weight:700;color:rgba(255,255,255,.72);
  text-align:center;padding:8px;line-height:1.2}
.badge{position:absolute;top:8px;inset-inline-start:8px;z-index:1;background:var(--green);color:#04221a;font-size:.68rem;
  font-weight:800;border-radius:6px;padding:2px 7px}
.card h3,.recent b,.hlist b,.slide h2,.sheet h2{text-align:right}
.card h3{margin:9px 0 2px;font-size:.92rem;line-height:1.35;font-weight:600;display:-webkit-box;-webkit-line-clamp:2;
  -webkit-box-orient:vertical;overflow:hidden}
.card .sub{margin:0;color:var(--mute);font-size:.8rem}
.rt{display:inline-flex;align-items:center;gap:4px;color:var(--gold);font-weight:700;font-size:.84rem;margin:4px 0 0}
.tags{display:flex;flex-wrap:wrap;gap:4px;margin:6px 0 0}
.tags span{font-size:.7rem;color:var(--mute);border:1px solid var(--line2);border-radius:6px;padding:1px 7px}
.card.ch .pos{aspect-ratio:1;background:#eef3fb}
.card.ch .pos img{object-fit:contain;padding:14%}
.card.ch .ph{color:#1d2c4f;font-size:1.4rem}
/* الإعلان */
.ad{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.45fr);gap:20px;align-items:center;margin:16px 0 0;padding:22px;
  border-radius:20px;border:1px solid rgba(246,195,67,.38);
  background:radial-gradient(520px 220px at 100% 0,rgba(246,195,67,.16),transparent 62%),linear-gradient(135deg,#15305e,#0b1530)}
.ad .eyebrow{display:inline-block;font-size:.7rem;font-weight:800;color:#1b1400;background:var(--gold);border-radius:6px;padding:2px 9px}
.ad h2{margin:10px 0 6px;font-size:1.4rem;line-height:1.3}
.ad p{margin:0;color:#c9d6f0;font-size:.9rem}
.adbtns{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}
.adbtns .btn{padding:11px 18px;flex:1 1 auto;white-space:nowrap}
.adplans{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(0,1fr);gap:10px}   /* عمودٌ لكل باقة (حتى ثلاث) */
.adplan{position:relative;display:flex;flex-direction:column;align-items:center;text-align:center;gap:6px;padding:16px 10px 12px;
  border-radius:16px;border:1px solid var(--line2);background:rgba(6,11,23,.55);transition:border-color .2s,transform .2s}
.adplan:hover{border-color:var(--gold);transform:translateY(-2px)}
.adplan img{width:56px;height:56px;border-radius:12px;object-fit:cover}
.adplan .t{min-width:0}
.adplan b{display:block;font-size:.86rem;line-height:1.35}
.adplan small{display:block;color:var(--mute);font-size:.74rem}
.adplan em{font-style:normal;font-weight:800;color:var(--gold);font-size:1.06rem;white-space:nowrap}
.adplan s{color:var(--mute);font-weight:500;font-size:.78rem;margin-inline-start:6px}
.adplan .off{position:absolute;top:8px;inset-inline-end:8px;background:#e5484d;color:#fff;font-size:.68rem;font-weight:800;
  border-radius:6px;padding:1px 6px}
.adplan .aft{font-size:.72rem;font-weight:700;line-height:1.4;color:var(--ink);background:rgba(246,195,67,.14);
  border:1px dashed rgba(246,195,67,.55);border-radius:7px;padding:2px 7px}   /* ما يدفعه صاحب أول طلب بكود الخصم */
.ad .adcode{margin:10px 0 0;color:var(--ink);font-size:.86rem}
.ad .adcode code{display:inline-block;background:var(--gold);color:#1b1400;border-radius:6px;padding:1px 8px;direction:ltr;
  font:800 .9rem/1.4 ui-monospace,Consolas,monospace;letter-spacing:.06em;user-select:all}
@media (max-width:760px){.ad{grid-template-columns:1fr;padding:18px}}
@media (max-width:520px){.ad{padding:14px;gap:12px}.ad h2{font-size:1.1rem;margin:8px 0 4px}   /* مختصرٌ في الأعلى */
  .ad p{font-size:.82rem;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
  .adplans{gap:6px}.adplan{padding:12px 4px 8px;gap:4px;border-radius:12px}.adplan img{width:40px;height:40px;border-radius:9px}
  .adplan b{font-size:.74rem}.adplan small{display:none}.adplan em{font-size:.9rem}.adplan s{display:none}
  .adplan .off{top:4px;inset-inline-end:4px;font-size:.62rem;padding:0 4px}.adplan .aft{font-size:.6rem;padding:1px 4px}
  .adbtns{margin-top:10px}.adbtns .btn{padding:10px 12px}.adbtns .ghost{flex:0 0 auto}.adbtns .wide{display:none}}
/* الجانب */
.side{display:flex;flex-direction:column;gap:16px;min-width:0}
.panel{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:18px}
.panel h2{display:flex;align-items:center;gap:8px;margin:0 0 12px;font-size:1.08rem}
.panel h2 .i{color:var(--acc)}
.filter label{display:block;color:var(--mute);font-size:.85rem;margin:12px 0 5px}
.filter select{width:100%;padding:10px 12px;border-radius:10px;border:1px solid var(--line);background:var(--bg2);color:var(--ink);font:inherit}
.filter .btn{width:100%;margin-top:16px}
.recent{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:12px}
.recent li{display:flex;align-items:center;gap:10px;cursor:pointer;border-radius:12px;min-width:0}
.recent .n{width:26px;height:26px;border-radius:50%;background:var(--acc);display:grid;place-items:center;font-weight:700;font-size:.8rem;flex:none}
.recent .pos{width:46px;flex:none;border-radius:8px}
.recent .ph{font-size:.8rem}
.recent .t{flex:1;min-width:0}
.recent b{display:block;font-size:.9rem;line-height:1.3;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.recent small{color:var(--mute);font-size:.78rem}
.recent .rt{margin:0}
.cta p{color:var(--mute);margin:0 0 12px;font-size:.9rem}
.plan{display:flex;align-items:center;gap:10px;padding:10px;border:1px solid var(--line);border-radius:12px;margin-bottom:8px}
.plan:hover{border-color:var(--acc)}
.plan img{width:42px;height:42px;border-radius:10px;object-fit:cover}
.plan span{flex:1;min-width:0}
.plan b{display:block;font-size:.88rem}
.plan small{color:var(--mute);font-size:.75rem}
.plan em{font-style:normal;font-weight:700;color:var(--gold);white-space:nowrap}
.plan em .aft{display:block;font-style:normal;font-size:.7rem;font-weight:600;color:var(--ink)}
.cta>.btn{width:100%;margin-top:4px}
.btns{display:flex;gap:8px;margin-top:10px}
.btns .btn{flex:1;padding:10px}
/* الشبكة والصفحات */
.gh{display:flex;align-items:center;gap:8px 12px;flex-wrap:wrap;margin:22px 0 16px}
.gh h1{display:flex;align-items:center;gap:8px;margin:0;font-size:1.45rem}
.gh .sub{color:var(--mute)}
.pager{display:flex;justify-content:center;align-items:center;gap:14px;margin:24px 0;color:var(--mute)}
.pager a{padding:8px 14px;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--ink)}
.results{margin:18px 0 8px;padding:18px;border-radius:18px;border:1px solid var(--line2);background:rgba(14,23,44,.72)}
.results h3{margin:16px 0 10px;font-size:1rem}
.results .other{margin:16px 0 0;color:var(--mute)}
.results .fix{margin:-4px 0 8px;color:var(--gold);font-size:.92rem}
.results .other a{display:inline-flex;align-items:center;gap:6px;color:var(--acc);font-weight:600;vertical-align:middle}
.missing li a{display:inline-flex;align-items:center;gap:8px}
#cres[aria-busy="true"]{opacity:.5}
#cres:empty{display:none}
.empty{color:var(--mute)}
.missing{max-width:620px;margin:40px auto}
.missing ul{line-height:2}
/* النافذة */
.modal{position:fixed;inset:0;z-index:60;display:grid;place-items:center;padding:16px;background:rgba(2,6,14,.74);backdrop-filter:blur(6px)}
.sheet{position:relative;width:min(760px,100%);max-height:92vh;overflow:auto;border-radius:22px;border:1px solid var(--line2);
  background:var(--bg2);box-shadow:0 30px 80px -20px rgba(0,0,0,.9)}
.sheet .cover{height:170px;background:linear-gradient(135deg,#132b5a,#0a1223) center/cover;position:relative}
.sheet .cover::after{content:"";position:absolute;inset:0;background:linear-gradient(0deg,var(--bg2),rgba(10,18,35,.25))}
.sheet .body{display:grid;grid-template-columns:170px minmax(0,1fr);gap:20px;padding:0 22px 22px;margin-top:-86px;position:relative}
.sheet .body>.pos{box-shadow:0 20px 40px -16px #000}
.sheet .txt{padding-top:96px;min-width:0}
.sheet h2{margin:10px 0 4px;font-size:1.45rem;line-height:1.25}
.sheet .x{position:absolute;top:12px;inset-inline-end:12px;z-index:2;width:38px;height:38px;border-radius:50%;
  border:1px solid rgba(255,255,255,.2);background:rgba(6,11,23,.6);color:#fff;cursor:pointer;display:grid;place-items:center}
.sheet .plot{-webkit-line-clamp:unset;display:block}
.seasons{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.seasons span{background:var(--card2);border:1px solid var(--line2);border-radius:999px;padding:4px 12px;font-size:.8rem}
.sheet .btn{margin-top:18px}
@media (max-width:560px){.sheet .body{grid-template-columns:104px minmax(0,1fr);gap:14px;padding:0 16px 18px;margin-top:-56px}
  .sheet .txt{padding-top:62px}.sheet h2{font-size:1.15rem}.sheet .cover{height:120px}}
footer.foot{margin:40px 0 0;padding:22px 0 30px;border-top:1px solid var(--line);color:var(--mute);font-size:.85rem}
footer.foot p{margin:4px 0}
footer.foot a{color:var(--acc)}
/* الإنجليزية: من اليسار — وما لم يُكتب بخصائص البداية والنهاية ينقلب هنا */
:root[dir=ltr] .brand small,:root[dir=ltr] .servers small{text-align:left}
:root[dir=ltr] .card h3,:root[dir=ltr] .recent b,:root[dir=ltr] .hlist b,:root[dir=ltr] .slide h2,:root[dir=ltr] .sheet h2{text-align:left}
:root[dir=ltr] .slide::after{background:linear-gradient(90deg,rgba(6,11,23,.92),rgba(6,11,23,.55) 55%,rgba(6,11,23,.15))}
:root[dir=ltr] .arrow .i,:root[dir=ltr] .harrow .i{transform:scaleX(-1)}
:root[dir=ltr] .ad{background:radial-gradient(520px 220px at 0 0,rgba(246,195,67,.16),transparent 62%),linear-gradient(135deg,#15305e,#0b1530)}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""

JS = """
(function(){
  var K = document.body.getAttribute("data-server"), NAME = document.body.getAttribute("data-name"),
      CTA = document.body.getAttribute("data-cta") || "/#buy";
  // الإنجليزية على /en/content: نصوص النافذة، والصفحة من اليسار فالتالي إلى اليمين
  var EN = document.documentElement.lang === "en", RTL = document.documentElement.dir !== "ltr";
  var T = EN ? {kind: {movie: "Movie", series: "Series", live: "Channel"}, close: "Close", upd: "Updated ", add: "Added ",
                sub: "Subscribe to "}
             : {kind: {movie: "فيلم", series: "مسلسل", live: "قناة"}, close: "إغلاق", upd: "حُدّث ", add: "أضيف ",
                sub: "اشترك في "};
  function $(s, r){ return (r || document).querySelector(s); }
  function $$(s, r){ return Array.prototype.slice.call((r || document).querySelectorAll(s)); }
  function esc(s){ return String(s == null ? "" : s).replace(/[&<>"']/g, function(c){
    return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]; }); }
  // صورةٌ تعذّرت: يبقى تحتها الحرفان الأولان
  document.addEventListener("error", function(e){
    var t = e.target; if (t && t.tagName === "IMG" && t.closest(".pos,.chip,.slide")) t.remove();
  }, true);
  // وما تعذّر قبل أن يصل السكربت (ردٌّ سريع بـ 404)
  $$(".pos img,.chip img,.slide img").forEach(function(i){ if (i.complete && !i.naturalWidth) i.remove(); });
  // الواجهة المتحرّكة
  var hero = $("[data-hero]");
  if (hero) {
    var slides = $$(".slide", hero), dots = $$(".dots button", hero), list = $$(".hlist button"), cur = 0, timer = 0;
    var show = function(i){
      cur = (i + slides.length) % slides.length;
      slides.forEach(function(s, n){ s.classList.toggle("on", n === cur); });
      dots.concat(list).forEach(function(b){
        if (+b.getAttribute("data-go") === cur) b.setAttribute("aria-current", "true"); else b.removeAttribute("aria-current");
      });
    };
    var play = function(){
      clearInterval(timer);
      if (slides.length > 1 && !(window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches))
        timer = setInterval(function(){ if (!document.hidden) show(cur + 1); }, 7000);
    };
    hero.addEventListener("click", function(e){
      var b = e.target.closest(".harrow,.dots button"); if (!b) return;
      e.stopPropagation();
      if (b.classList.contains("prev")) show(cur - 1); else if (b.classList.contains("next")) show(cur + 1);
      else show(+b.getAttribute("data-go"));
      play();
    });
    list.forEach(function(b){ b.addEventListener("click", function(){ show(+b.getAttribute("data-go")); play(); }); });
    hero.addEventListener("mouseenter", function(){ clearInterval(timer); });
    hero.addEventListener("mouseleave", play);
    var x0 = null;
    hero.addEventListener("touchstart", function(e){ x0 = e.touches[0].clientX; }, {passive: true});
    hero.addEventListener("touchend", function(e){
      if (x0 === null) return;
      var dx = e.changedTouches[0].clientX - x0; x0 = null;
      if (Math.abs(dx) > 40) { hero.dataset.swiped = "1"; show(cur + ((dx > 0) === RTL ? 1 : -1)); play(); }
    }, {passive: true});
    play();
  }
  // أسهم الصفوف
  document.addEventListener("click", function(e){
    var a = e.target.closest(".arrow"); if (!a) return;
    var box = $(".cards", a.closest(".row")); if (!box) return;
    box.scrollBy({left: box.clientWidth * .85 * (a.classList.contains("next") ? -1 : 1) * (RTL ? 1 : -1), behavior: "smooth"});
  });
  // نافذة التفاصيل
  var modal = $("#cx-modal"), last = null;
  var hue = function(s){ var n = 0; for (var i = 0; i < s.length; i++) n += s.charCodeAt(i); return n * 37 % 360; };
  var ini = function(s){      // كـ _initials في الخادم
    var w = s.replace(/\\p{M}/gu, "").match(/[\\p{L}\\p{N}]+/gu) || [];
    var l = w.filter(function(x){ return !/^\\p{N}+$/u.test(x); });
    return (l.length ? l : w).slice(0, 2).map(function(x){ return x[0]; }).join("").toUpperCase() || "•";
  };
  function open(d, from){
    var facts = [d.y, (d.g || []).join(" • ")].filter(Boolean).join(" · ");
    $(".sheet", modal).innerHTML = '<button class="x" type="button" aria-label="' + T.close + '">✕</button><div class="cover"></div>'
      + '<div class="body"><div class="pos" style="--h:' + hue(d.n || "") + '"><span class="ph">' + esc(ini(d.n || "")) + '</span>'
      + (d.p ? '<img src="' + esc(d.p) + '" alt="">' : '') + '</div><div class="txt">'
      + '<span class="kick">' + esc(T.kind[d.k] || "") + (d.c ? ' · ' + esc(d.c) : '') + '</span>'
      + '<h2 id="cx-title" dir="auto">' + esc(d.n) + '</h2>' + (facts ? '<p class="facts">' + esc(facts) + '</p>' : '')
      + (d.r ? '<p class="rt">★ ' + esc(d.r) + '</p>' : '')
      + (d.ss ? '<p class="facts">' + esc(d.ss) + '</p>' : '')
      + (d.sc ? '<div class="seasons">' + d.sc.map(function(t){ return '<span>' + esc(t) + '</span>'; }).join('') + '</div>' : '')
      + (d.a ? '<p class="empty">' + (d.k === "series" ? T.upd : T.add) + esc(d.a) + '</p>' : '')
      + (d.d ? '<p class="plot">' + esc(d.d) + '</p>' : '')
      + '<a class="btn" href="' + esc(CTA) + '" target="_blank" rel="noopener">' + T.sub + esc(NAME) + '</a></div></div>';
    if (d.b || d.p) $(".cover", modal).style.backgroundImage = "url(" + JSON.stringify(d.b || d.p) + ")";
    modal.hidden = false; document.body.style.overflow = "hidden"; last = from;
    $(".x", modal).focus();
  }
  function close(){ modal.hidden = true; document.body.style.overflow = ""; if (last && last.focus) last.focus(); }
  function pick(el){ try { open(JSON.parse(el.getAttribute("data-d")), el); } catch (err) {} }
  document.addEventListener("click", function(e){
    if (!modal.hidden || e.target.closest("a,.arrow,.harrow,.dots,.hlist")) return;
    var el = e.target.closest("[data-d]");
    if (el) { if (hero && hero.dataset.swiped) { delete hero.dataset.swiped; return; } pick(el); }
  });
  document.addEventListener("keydown", function(e){
    if (e.key === "Escape" && !modal.hidden) return close();
    if (e.key === "Enter" && e.target.matches && e.target.matches("[data-d]")) pick(e.target);
  });
  modal.addEventListener("click", function(e){ if (e.target === modal || e.target.closest(".x")) close(); });
  // البحث مع الكتابة
  var f = $(".search"), box = $("#cres"), sw = $(".top .lang");
  if (f && box) {
    var inp = f.elements.q, timer2 = 0, lastq = inp.value.trim(), seq = 0;
    var run = function(){
      var v = inp.value.trim(); if (v === lastq) return; lastq = v;
      var at = v ? "?q=" + encodeURIComponent(v) : "";
      try { history.replaceState(null, "", location.pathname + at); } catch (e) {}
      if (sw) sw.href = sw.pathname + at;          // واللغة الأخرى على البحث نفسه
      if (v.replace(/\\s/g, "").length < 2) { box.innerHTML = ""; return; }
      var n = ++seq; box.setAttribute("aria-busy", "true");
      fetch("/api/content/search?s=" + K + (EN ? "&lang=en" : "") + "&q=" + encodeURIComponent(v))
        .then(function(r){ return r.json(); })
        .then(function(d){ if (n === seq && d && d.ok) { box.innerHTML = d.html; if (v) box.scrollIntoView({block: "nearest"}); } })
        .catch(function(){})
        .then(function(){ if (n === seq) box.removeAttribute("aria-busy"); });
    };
    var sqt = 0, sqlast = "";            // الإحصائيات: ما بحثوا عنه، حين يتوقّفون عن الكتابة (لا كل حرف)
    var sqrun = function(){
      var v = inp.value.trim().toLowerCase();
      if (v.replace(/\\s/g, "").length >= 2 && v !== sqlast && window.sq) { sqlast = v; window.sq("search", v); }
    };
    inp.addEventListener("input", function(){ clearTimeout(timer2); timer2 = setTimeout(run, 250); clearTimeout(sqt); sqt = setTimeout(sqrun, 1500); });
    f.addEventListener("submit", function(e){ e.preventDefault(); clearTimeout(timer2); lastq = null; run(); });
  }
})();
"""


def _doc(title, desc, url, index, body, key, name, cta, tr=AR, alts=()):
    """الصفحة كاملة. ‏alts: ‏[(اللغة، الرابط)] للصفحة نفسها بلغتيها (‏hreflang) — للمفهرَسة وحدها."""
    site = guide_pages.SITE
    crumbs = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": tr("دليل سمارت سوق", BRAND_EN + " guide"), "item": site + "/"},
        {"@type": "ListItem", "position": 2, "name": title.split(" | ")[0].split(":")[0], "item": url}]}
    ld = json.dumps(crumbs, ensure_ascii=False).replace("</", "<\\/")     # اسم سيرفرٍ فيه «</script>» لا يقطع السكربت
    robots = (f'<meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large">\n'
              f'<link rel="canonical" href="{url}">' + "".join(f'\n<link rel="alternate" hreflang="{h}" href="{u}">'
                                                                for h, u in alts)
              if index else '<meta name="robots" content="noindex, follow">')
    locale, other = tr(("ar_SA", "en_US"), ("en_US", "ar_SA"))
    return f"""<!doctype html>
<html lang="{tr.code}" dir="{tr.dir}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
<meta name="description" content="{_esc(desc)}">
{robots}
<meta name="theme-color" content="#060b17">
<meta name="color-scheme" content="dark">
<meta property="og:type" content="website">
<meta property="og:locale" content="{locale}">
<meta property="og:locale:alternate" content="{other}">
<meta property="og:site_name" content="{tr("سمارت سوق", BRAND_EN)}">
<meta property="og:title" content="{_esc(title)}">
<meta property="og:description" content="{_esc(desc)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{site}/static/og-image.png">
<link rel="icon" href="/favicon.ico">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="preconnect" href="https://image.tmdb.org">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;500;600;700&display=swap" rel="stylesheet">
<script type="application/ld+json">{ld}</script>
<style>{CSS}</style>
</head>
<body data-server="{_esc(key)}" data-name="{_esc(name)}" data-cta="{_esc(cta)}">
{body}
<div class="modal" id="cx-modal" role="dialog" aria-modal="true" aria-labelledby="cx-title" hidden><div class="sheet"></div></div>
<script>{JS}</script>
</body>
</html>""".encode("utf-8")

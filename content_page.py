# -*- coding: utf-8 -*-
"""صفحة المحتوى كما يراها الزائر (‏/content/<السيرفر>) بتصميم تطبيقات المشاهدة.

رأسٌ بالأقسام والبحث، وواجهةٌ متحرّكة بأحدث ما أضيف، وخانات الأعداد، وتبويب لكل نوع ومعه «أضيف مؤخرًا»،
وأقسام السيرفر صورًا، وصفّ ملصقات لكل قسم، وجانبٌ بالتصفية (السنة والقسم والتصنيف والتقييم) وقائمة
«أضيف مؤخرًا» وباقات الاشتراك، ونافذة تفاصيل فيها المواسم وحلقات كل موسم.

البيانات من content.py، والصفحة كلها تُرسم على الخادم وتعمل بلا سكربت (روابط ‏?t= ?g= ?view=grid ?q=)؛
والسكربت للحركة والنافذة والبحث مع الكتابة. والصفحة الرئيسية لكل سيرفر وحدها تُفهرس.
"""
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
ART = {k: f"/static/img/brands/{k}.webp" for k in ("smart", "falcon", "casper")}   # شعار السيرفر في الرأس إن كان له
DAYS = ("يوم", "يومين", "أيام", "يومًا", "يوم")
WEEKS = ("أسبوع", "أسبوعين", "أسابيع", "أسبوعًا", "أسبوع")
MONTHS = ("شهر", "شهرين", "أشهر", "شهرًا", "شهر")
YEARS = ("سنة", "سنتين", "سنوات", "سنة", "سنة")

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
}
STAR = ('<svg class="star" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="m12 2.8 2.8 5.8 6.3.9-4.6 4.4'
        ' 1.1 6.3L12 17.2l-5.6 3 1.1-6.3-4.6-4.4 6.3-.9z"/></svg>')


def _i(name, cls="i"):
    return f'<svg class="{cls}" viewBox="0 0 24 24" aria-hidden="true">{ICON[name]}</svg>'


def _ago(ts, now=None):
    """تاريخ الإضافة من الواجهة: «اليوم» «أمس» «منذ 3 أيام» «منذ أسبوعين» «منذ 5 أشهر»."""
    if not ts:
        return ""
    d = int(((now or time.time()) - ts) // 86400)
    if d < 1:
        return "اليوم"
    if d < 2:
        return "أمس"
    for size, forms in ((365, YEARS), (30, MONTHS), (7, WEEKS), (1, DAYS)):
        if d >= size:
            return "منذ " + C._count(d // size, forms)
    return ""


def _hue(s):
    return sum(map(ord, s or "")) * 37 % 360


def _initials(name):
    """حرفا الملصق بلا صورة: أول حرفٍ من أول كلمتين — بلا الأقواس والرموز، والأرقام («(2026)» «12 Strong»)
    إلا إن لم يكن غيرها («2020»)."""
    words = re.findall(r"[^\W_]+", C._TASHKEEL.sub("", name or ""))
    words = [w for w in words if not w.isdigit()] or words
    return "".join(w[0] for w in words[:2]).upper() or "•"


def _seasons(it):
    """ملخّص المواسم ورقاقاتها: («5 مواسم · 62 حلقة»، [«الموسم 1 (7 حلقات)»، …])."""
    ss = it.get("s") or []
    if not ss:
        return "", []
    known = any(s for s, _ in ss)
    eps = sum(n for _, n in ss)
    text = (C._count(len(ss), C.N_SEASONS) + " · " if known else "") + C._count(eps, C.N_EPISODES)
    chips = [f'{f"الموسم {s}" if s else "بلا موسم"} ({C._count(n, C.N_EPISODES)})' for s, n in ss] if known else []
    return text, chips


def _fresh(it, now=None):
    a = it.get("a")
    return bool(a) and (now or time.time()) - a < NEW_DAYS * 86400


def _data(key, kind, it, gname):
    """ما تعرضه نافذة التفاصيل — نصًّا في ‏data-d، فلا طلب ثانيًا."""
    ss, sc = _seasons(it)
    d = {"k": kind, "n": it.get("n"), "y": it.get("y"), "r": it.get("r"), "g": it.get("g"), "d": it.get("d"),
         "c": gname, "ss": ss, "sc": sc, "a": _ago(it.get("a")),
         "p": C.img_src(key, it.get("p"), "w500"), "b": C.img_src(key, it.get("b") or "", "w780")}
    return _esc(json.dumps({k: v for k, v in d.items() if v}, ensure_ascii=False, separators=(",", ":")))


def _pos(key, it, size="w342", lazy=True):
    """الملصق: الحرفان الأولان بلونٍ من الاسم تحت الصورة، فإن تعذّرت بقيا."""
    name = it.get("n", "")
    src = C.img_src(key, it.get("p"), size)
    img = (f'<img src="{_esc(src)}" alt=""{" loading=lazy" if lazy else ""} decoding="async">' if src else "")
    return f'<span class="ph">{_esc(_initials(name))}</span>{img}', _hue(name)


def card(key, kind, it, gname="", when=False, now=None):
    name = it.get("n", "")
    face, hue = _pos(key, it)
    sub = [str(it["y"])] if it.get("y") else []
    if kind == "series":
        ss = it.get("s") or []
        if ss:
            known = any(s for s, _ in ss)
            sub.append(C._count(len(ss), C.N_SEASONS) if known else C._count(sum(n for _, n in ss), C.N_EPISODES))
    if when and it.get("a"):
        sub.append(("حُدّث " if kind == "series" else "أضيف ") + _ago(it["a"], now))
    badge = '<span class="badge">جديد</span>' if _fresh(it, now) else ""
    rt = f'<p class="rt">{STAR}{it["r"]:g}</p>' if it.get("r") else ""
    tags = ('<p class="tags">' + "".join(f"<span>{_esc(g)}</span>" for g in it["g"][:2]) + "</p>") if it.get("g") else ""
    return (f'<article class="card{" ch" if kind == "live" else ""}" tabindex="0" data-d="{_data(key, kind, it, gname)}">'
            f'<div class="pos" style="--h:{hue}">{face}{badge}</div><h3 dir="auto">{_esc(name)}</h3>'
            + (f'<p class="sub">{_esc(" · ".join(sub))}</p>' if sub else "") + rt + tags + "</article>")


def _cards(key, v, kind, picks, when=False):
    gs = v["kinds"][kind]
    return "".join(card(key, kind, gs[gi]["items"][ii], gs[gi]["name"], when) for gi, ii in picks)


def _row(title, inner, more_href="", more=""):
    return (f'<section class="row"><div class="rh"><h2>{title}</h2>'
            + (f'<a class="more" href="{more_href}">{more}</a>' if more_href else "")
            + '<span class="rbtn"><button type="button" class="arrow prev" aria-label="السابق">'
            + _i("chevr") + '</button><button type="button" class="arrow next" aria-label="التالي">' + _i("chev")
            + f'</button></span></div><div class="cards">{inner}</div></section>')


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
def _header(base, srv, v, t, q, key):
    art = (f'<img src="{ART[key]}" alt="" width="42" height="42">' if key in ART
           else f'<span class="bi">{_i("series")}</span>')
    nav = [("", "الرئيسية")] + [(k, C.KIND_TAB[k]) for k in C.KINDS if v["kinds"][k]]
    if any(v["recent"][k] for k in C.KINDS):
        nav.append(("new", "أضيف مؤخرًا"))
    links = "".join(f'<a href="{_link(base, t=k)}"{" class=home" if not k else ""}{" aria-current=page" if k == t else ""}>'
                    f'{label}</a>' for k, label in nav)
    return (f'<header class="top"><div class="wrap"><a class="brand" href="{_esc(base)}">{art}<span><b>{_esc(srv["name"])}</b>'
            + (f'<small>{_esc(srv["full"])}</small>' if srv["full"] else "") + '</span></a>'
            f'<nav class="nav" aria-label="أقسام المحتوى">{links}</nav>'
            f'<form class="search" role="search" action="{_esc(base)}" method="get">'
            f'<input type="search" name="q" value="{_esc(q)}" placeholder="ابحث عن فيلم أو مسلسل أو قناة…" '
            f'aria-label="ابحث باسم المسلسل أو الفيلم أو القناة في {_esc(srv["name"])}" autocomplete="off" '
            f'enterkeyhint="search" maxlength="{C.QUERY_MAX}"><button type="submit" aria-label="بحث">{_i("search")}</button>'
            '</form></div></header>')


def _servers(data_dir, key):
    shown = [s for s in C.servers(data_dir) if s["key"] == key or C._has(C._view(data_dir, s["key"])[1])]
    if len(shown) < 2:
        return ""
    return ('<nav class="servers" aria-label="السيرفرات"><span>السيرفر:</span>' + "".join(
        f'<a href="{C.PATH}/{s["key"]}"{" aria-current=page" if s["key"] == key else ""}>{_esc(s["name"])}</a>'
        for s in shown) + "</nav>")


def _hero(key, v):
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
        ss, _ = _seasons(it)
        if ss:
            facts.append(ss)
        lazy = "" if n == 0 else ' loading="lazy"'
        slides.append(
            f'<article class="slide{" on" if n == 0 else ""}" data-d="{_data(key, kind, it, gname)}">'
            f'<img class="bg" src="{_esc(bg)}" alt=""{lazy}>'
            f'<div class="info"><span class="kick">{_i("new")}أضيف مؤخرًا · {KIND_ONE[kind]}</span>'
            f'<h2 dir="auto">{_esc(it["n"])}</h2>' + (f'<p class="facts">{_esc(" · ".join(facts))}</p>' if facts else "")
            + (f'<p class="rt">{STAR}{it["r"]:g}</p>' if it.get("r") else "")
            + (f'<p class="plot">{_esc(it["d"])}</p>' if it.get("d") else "")
            + '<button type="button" class="btn">عرض التفاصيل</button></div>'
            f'<img class="poster" src="{_esc(C.img_src(key, it["p"], "w342"))}" alt=""{lazy}></article>')
        dots.append(f'<button type="button" data-go="{n}" aria-label="الشريحة {n + 1}"'
                    f'{" aria-current=true" if n == 0 else ""}></button>')
        face, hue = _pos(key, it, "w185")
        side.append(f'<button type="button" data-go="{n}"{" aria-current=true" if n == 0 else ""}>'
                    f'<span class="pos" style="--h:{hue}">{face}</span><span><b dir="auto">{_esc(it["n"])}</b>'
                    f'<small>{_esc(" · ".join(facts[:1] + [KIND_ONE[kind]]))}</small></span></button>')
    arrows = ('<button type="button" class="harrow prev" aria-label="السابق">' + _i("chevr") + '</button>'
              '<button type="button" class="harrow next" aria-label="التالي">' + _i("chev") + '</button>'
              if len(picks) > 1 else "")
    return (f'<div class="herobox"><section class="hero" data-hero aria-roledescription="عرض" aria-label="أضيف مؤخرًا">'
            f'{"".join(slides)}{arrows}<div class="dots">{"".join(dots) if len(picks) > 1 else ""}</div></section>'
            f'<div class="hlist">{"".join(side[:4])}</div></div>')


def _stats(c):
    tiles = [("movie", c["movie"], C.N_MOVIES), ("series", c["series"], C.N_SERIES), ("live", c["live"], C.N_CHANNELS),
             ("episodes", c["episodes"], C.N_EPISODES), ("seasons", c["seasons"], C.N_SEASONS)]
    return '<div class="stats">' + "".join(
        f'<div class="stat">{_i(icon)}<span><b>{n:,}</b><small>{C._unit(n, forms)}</small></span></div>'
        for icon, n, forms in tiles if n) + "</div>"


def _kinds(base, v, t):
    tabs = [(k, C.KIND_TAB[k], v["counts"][k]) for k in C.KINDS if v["kinds"][k]]
    if any(v["recent"][k] for k in C.KINDS):
        tabs.append(("new", "أضيف مؤخرًا", 0))
    return '<nav class="kinds" aria-label="نوع المحتوى">' + "".join(
        f'<a href="{_link(base, t=k)}"{" aria-current=page" if k == t else ""}>{_i(k)}{label}'
        + (f' <small>{n:,}</small>' if n else "") + "</a>" for k, label, n in tabs) + "</nav>"


def _chip(key, base, v, kind, gi, g):
    top = _sel(v, kind, gid=g["id"])
    pic = next((g["items"][ii].get("p") for _, ii in top[:40] if g["items"][ii].get("p")), "")
    src = C.img_src(key, pic, "w185")
    return (f'<a class="chip" href="{_link(base, t=kind, g=g["id"])}">'
            + (f'<img src="{_esc(src)}" alt="" loading="lazy">' if src else "")
            + f'<span><b>{_esc(g["name"])}</b><small>{C._count(len(g["items"]), C.N_OF[kind])}</small></span></a>')


def _chips(key, base, v, kind):
    gs = v["kinds"][kind]
    out = [_chip(key, base, v, kind, gi, g) for gi, g in enumerate(gs[:CHIPS_MAX])]
    if len(gs) > CHIPS_MAX:
        out.append(f'<a class="chip more" href="{_link(base, t=kind, all=1)}"><span>{_i("grid")}<b>كل الأقسام</b>'
                   f'<small>{len(gs):,}</small></span></a>')
    return f'<div class="chips">{"".join(out)}</div>'


def _filters(base, v, kind, cur):
    if kind not in C.KINDS or not v["kinds"][kind]:
        return ""
    def opts(pairs, sel):
        return "".join(f'<option value="{_esc(val)}"{" selected" if str(val) == str(sel) else ""}>{_esc(label)}</option>'
                       for val, label in pairs)
    parts = [f'<input type="hidden" name="t" value="{kind}"><input type="hidden" name="view" value="grid">']
    if v["years"][kind]:
        parts.append('<label for="fy">السنة</label><select id="fy" name="y">'
                     + opts([("", "الكل")] + [(y, y) for y in v["years"][kind]], cur["y"] or "") + "</select>")
    parts.append('<label for="fg">القسم</label><select id="fg" name="g">'
                 + opts([("", "كل الأقسام")] + [(g["id"], g["name"]) for g in v["kinds"][kind]], cur["g"]) + "</select>")
    if v["genres"][kind]:
        parts.append('<label for="fn">التصنيف</label><select id="fn" name="genre">'
                     + opts([("", "الكل")] + [(x, x) for x in v["genres"][kind]], cur["genre"]) + "</select>")
    if v["rated"][kind]:
        parts.append('<label for="fr">التقييم</label><select id="fr" name="r">'
                     + opts([("", "الكل")] + [(n, f"{n} فأعلى") for n in (9, 8, 7, 6, 5)], cur["r"] or "") + "</select>")
    sorts = [("new", "الأحدث إضافة"), ("az", "الاسم")] + ([("rate", "الأعلى تقييمًا")] if v["rated"][kind] else [])
    parts.append('<label for="fs">الترتيب</label><select id="fs" name="sort">' + opts(sorts, cur["sort"]) + "</select>")
    return (f'<section class="panel"><h2>{_i("filter")} تصفية {C.KIND_TAB[kind]}</h2><form class="filter" action="{_esc(base)}"'
            f' method="get">{"".join(parts)}<button class="btn" type="submit">تطبيق الفلتر</button></form></section>')


def _recent_list(key, v, kinds):
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
        sub.append(_ago(it["a"]) if it.get("a") else KIND_ONE[kind])
        rows.append(f'<li tabindex="0" data-d="{_data(key, kind, it, gname)}"><span class="n">{n}</span>'
                    f'<span class="pos" style="--h:{hue}">{face}</span><span class="t"><b dir="auto">{_esc(it["n"])}</b>'
                    f'<small>{_esc(" · ".join(sub))}</small></span>'
                    + (f'<span class="rt">{STAR}{it["r"]:g}</span>' if it.get("r") else "") + "</li>")
    return f'<section class="panel"><h2>{_i("new")} أضيف مؤخرًا</h2><ol class="recent">{"".join(rows)}</ol></section>'


def _utm(url):
    """روابط المتجر بحملة هذه الصفحة لتُعرف المبيعات منها، وغيرها كما هي."""
    host = (re.match(r"^https?://([^/?#:]+)", url or "") or [None, ""])[1].lower()
    if host != "ssouq.com" and not host.endswith(".ssouq.com"):
        return url
    if "utm_campaign=" in url:
        return re.sub(r"utm_campaign=[^&#]*", "utm_campaign=" + C.UTM_CAMPAIGN, url)
    return (url + ("&" if "?" in url else "?")
            + "utm_source=guide.ssouq.com&utm_medium=referral&utm_campaign=" + C.UTM_CAMPAIGN)


def _cta(srv):
    """باقات الاشتراك: رابط شراء السيرفر من صفحة المدير، أو باقاته من CATALOG في index.html، أو الدليل.
    ← (HTML، رابط زرّ الاشتراك في النافذة)."""
    name = _esc(srv["name"])
    rows, first = [], ""
    if not srv["buy"]:
        plans = {p["id"]: p for b in tournament._catalog().values() for p in b.get("plans", [])}
        for pid in C.PLANS.get(srv["key"], ()):
            p = plans.get(pid)
            if not p:
                continue
            url = _utm(p["url"])
            first = first or url
            rows.append(f'<a class="plan" href="{_esc(url)}" target="_blank" rel="noopener">'
                        f'<img src="{_esc(p["img"])}" alt="" width="42" height="42" loading="lazy">'
                        f'<span><b>{_esc(p["name"])}</b><small>{_esc(p.get("tag") or p.get("dur") or "")}</small></span>'
                        f'<em>{_esc(p["price"])} ر.س</em></a>')
    buy = _utm(srv["buy"]) if srv["buy"] else ""
    link = buy or first or "/#buy"
    html = (f'<section class="panel cta"><h2>اشترك في {name}</h2>'
            '<p>دفعة واحدة بلا تجديد تلقائي، وتفعيل خلال دقائق، ودعم فني مباشر على واتساب.</p>'
            + "".join(rows)
            + (f'<a class="btn" href="{_esc(buy)}" target="_blank" rel="noopener">اشترك في {name}</a>' if buy else "")
            + '<div class="btns"><a class="btn ghost" href="/#buy">ساعدني في الاختيار</a>'
            '<a class="btn ghost" href="/#plans">كل الباقات</a></div></section>')
    return html, link


def _pager(base, page, pages, **kw):
    if pages < 2:
        return ""
    prev = f'<a href="{_link(base, **kw, p=page - 1)}">→ السابق</a>' if page > 1 else "<span></span>"
    nxt = f'<a href="{_link(base, **kw, p=page + 1)}">التالي ←</a>' if page < pages else "<span></span>"
    return f'<nav class="pager" aria-label="الصفحات">{prev}<span>صفحة {page} من {pages}</span>{nxt}</nav>'


def results_html(data_dir, key, srv, v, q):
    """نتائج البحث بالاسم ملصقاتٍ: لكل نوعٍ أوّل C.SEARCH_MAX بقسمها، ثم أين يوجد الاسم في السيرفرات الأخرى —
    فمن لم يجد مسلسله هنا يعرف أيّ اشتراكٍ فيه."""
    q = " ".join(str(q or "").split())[:C.QUERY_MAX]
    if not C._words(q):
        return ""
    hits, total = C._search(key, v, q)
    parts = []
    for kind in C.KINDS:
        top, n = hits[kind]
        if not n:
            continue
        more = (f'<p class="empty">و{C._count(n - len(top), C.N_RESULTS)} أخرى — اكتب الاسم أدقّ.</p>'
                if n > len(top) else "")
        parts.append(f'<h3>{C.KIND_TAB[kind]} <small>({n:,})</small></h3>'
                     f'<div class="grid">{_cards(key, v, kind, top)}</div>{more}')
    elsewhere = []
    for s in C.servers(data_dir):
        ov = C._view(data_dir, s["key"])[1] if s["key"] != key else None
        n = C._search(s["key"], ov, q)[1] if C._has(ov) else 0
        if n:
            elsewhere.append(f'<a href="{C.PATH}/{s["key"]}?q={quote(q)}">{_esc(s["name"])} ({n:,})</a>')
    other = (f'<p class="other">{"ويوجد أيضًا في" if total else "لكنه موجود في"}: {" · ".join(elsewhere)}</p>'
             if elsewhere else "")
    if not total:
        return (f'<section class="results"><div class="rh"><h2>لا يوجد «{_esc(q)}» في {_esc(srv["name"])}</h2></div>'
                + (other or '<p class="empty">جرّب جزءًا من الاسم، أو اكتبه بالإنجليزية أو بالعربية.</p>')
                + "</section>")
    return (f'<section class="results"><div class="rh"><h2>نتائج «{_esc(q)}» في {_esc(srv["name"])} '
            f'<small>{C._count(total, C.N_RESULTS)}</small></h2></div>{"".join(parts)}{other}</section>')


def api_search(data_dir, key, q):
    srv, v = C._view(data_dir, key)
    if not C._has(v):
        return None
    return {"ok": True, "html": results_html(data_dir, key, srv, v, q)}


# ================= الصفحة =================
def _int(v, lo=0, hi=10 ** 6):
    try:
        n = int(str(v or "").strip())
    except ValueError:
        return 0
    return n if lo <= n <= hi else 0


def render(data_dir, key, query):
    """صفحة السيرفر ← (رمز HTTP، بايتات، ثواني الكاش). ‏query: ‏t النوع (أو new)، g القسم، view=grid التصفية
    (y السنة، genre التصنيف، r أدنى تقييم، sort الترتيب)، all=1 كل الأقسام، p الصفحة، q البحث."""
    srv, v = C._view(data_dir, key)
    if not srv or not C._has(v):
        code, body = render_missing(data_dir, key)
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
    base = f"{C.PATH}/{key}"
    c, name, code = v["counts"], srv["name"], 200
    cta, cta_link = _cta(srv)
    main, side, head = [], [], ""
    kind = t if t in C.KINDS else ""
    gi = v["byid"][kind].get(gid) if kind and gid else None
    if kind and gid and gi is None:
        code = 404
    if t == "" and not gid:
        head = _hero(key, v) + _stats(c) + _kinds(base, v, t)
        for k in ("movie", "series", "live"):
            if v["recent"][k]:
                label = {"movie": "أفلام أضيفت مؤخرًا", "series": "مسلسلات جديدة أو بحلقاتٍ جديدة",
                         "live": "قنوات أضيفت مؤخرًا"}[k]
                main.append(_row(label, _cards(key, v, k, v["recent"][k][:ROW_MAX], when=True),
                                 _link(base, t="new"), "عرض الكل"))
        for k, n in (("movie", 3), ("series", 3), ("live", 2)):
            for g in v["kinds"][k][:n]:
                top = _sel(v, k, gid=g["id"])[:ROW_MAX]
                main.append(_row(f'{_esc(g["name"])} <small>· {KIND_ONE[k]}</small>', _cards(key, v, k, top),
                                 _link(base, t=k, g=g["id"]), f'عرض الكل ({len(g["items"]):,})'))
        side += [_recent_list(key, v, ("movie", "series")), cta]
    elif t == "new":
        head = _stats(c) + _kinds(base, v, t)
        main.append(f'<div class="gh"><h1>{_i("new")} أضيف مؤخرًا في {_esc(name)}</h1>'
                    '<span class="sub">الأحدث أولًا، بترتيب إضافتها إلى السيرفر</span></div>')
        for k in C.KINDS:
            if v["recent"][k]:
                label = {"movie": "أفلام", "series": "مسلسلات جديدة أو بحلقاتٍ جديدة", "live": "قنوات"}[k]
                main.append(f'<section class="row"><div class="rh"><h2>{label}</h2></div><div class="grid">'
                            f'{_cards(key, v, k, v["recent"][k][:NEW_MAX[k]], when=True)}</div></section>')
        side += [cta]
    elif kind and get("all"):
        head = _stats(c) + _kinds(base, v, t)
        chips = "".join(_chip(key, base, v, kind, n, g) for n, g in enumerate(v["kinds"][kind]))
        main.append(f'<div class="gh"><h1>أقسام {C.KIND_TAB[kind]}</h1><span class="sub">{C._count(len(v["kinds"][kind]), N_GROUPS)}</span>'
                    f'</div><div class="chipgrid">{chips}</div>')
        side += [_filters(base, v, kind, cur), _recent_list(key, v, (kind,)), cta]
    elif kind and (gi is not None or get("view") == "grid"):
        head = _kinds(base, v, t)
        picks = _sel(v, kind, gid=gid if gi is not None else "", year=cur["y"], genre=cur["genre"],
                     rating=cur["r"], sort=cur["sort"])
        pages = max(1, (len(picks) + GRID - 1) // GRID)
        page = min(page, pages)
        title = _esc(v["kinds"][kind][gi]["name"]) if gi is not None else f"{C.KIND_TAB[kind]} في {_esc(name)}"
        chosen = [str(cur["y"]) if cur["y"] else "", cur["genre"], f"تقييم {cur['r']} فأعلى" if cur["r"] else ""]
        chosen = " · ".join(x for x in chosen if x)
        main.append(f'<div class="gh"><h1>{title}</h1><span class="sub">{C._count(len(picks), C.N_OF[kind])}'
                    + (f" · {_esc(chosen)}" if chosen else "") + "</span></div>"
                    + (f'<div class="grid">{_cards(key, v, kind, picks[(page - 1) * GRID:page * GRID])}</div>' if picks
                       else '<p class="empty">لا نتائج بهذا الفلتر — وسّعه أو اختر «الكل».</p>')
                    + _pager(base, page, pages, t=kind, g=gid if gi is not None else "",
                             view="grid" if gi is None else "", y=cur["y"], genre=cur["genre"], r=cur["r"],
                             sort=cur["sort"] if cur["sort"] != "new" else ""))
        side += [_filters(base, v, kind, cur), _recent_list(key, v, (kind,)), cta]
    else:                                   # صفحة النوع: الأقسام صورًا ثم صفٌّ لكل قسم
        kind = kind or kinds[0]
        t = kind
        head = _stats(c) + _kinds(base, v, t)
        miss = '<p class="empty">هذا القسم لم يعد موجودًا، واختر من الأقسام الحالية.</p>' if code == 404 else ""
        main.append(miss + _chips(key, base, v, kind))
        for g in v["kinds"][kind][:ROWS_MAX]:
            top = _sel(v, kind, gid=g["id"])[:ROW_MAX]
            main.append(_row(_esc(g["name"]), _cards(key, v, kind, top), _link(base, t=kind, g=g["id"]),
                             f'عرض الكل ({len(g["items"]):,})'))
        if len(v["kinds"][kind]) > ROWS_MAX:
            main.append(f'<p class="empty"><a class="link" href="{_link(base, t=kind, all=1)}">كل أقسام '
                        f'{C.KIND_TAB[kind]} ({len(v["kinds"][kind]):,}) ←</a></p>')
        side += [_filters(base, v, kind, cur), _recent_list(key, v, (kind,)), cta]
    summary = _summary_text(c)
    what = " و".join(x for k, x in (("series", "المسلسلات بمواسمها"), ("movie", "الأفلام"), ("live", "القنوات")) if c[k])
    title = f"محتوى اشتراك {name}: {what} | سمارت سوق"
    desc = (f"ما في اشتراك {name} قبل أن تشتري: {summary}. ابحث بالاسم عن أي مسلسل أو فيلم أو قناة"
            + (" واعرف مواسم المسلسل وحلقات كل موسم" if c["series"] else "")
            + "، وتصفّح ما أضيف مؤخرًا. يُحدَّث تلقائيًا من قائمة الاشتراك نفسها.")
    index = code == 200 and not (q or gid or get("t") or get("view") or get("p") or get("all"))
    body = (_header(base, srv, v, t, q, key) + '<main class="wrap">' + _servers(data_dir, key)
            + (f'<h1 class="sr">محتوى اشتراك {_esc(name)}</h1>' if t == "" and not gid else "")
            + '<div id="cres" aria-live="polite">' + (results_html(data_dir, key, srv, v, q) if q else "") + "</div>"
            + head + '<div class="layout"><div class="col">' + "".join(main) + "</div>"
            + f'<aside class="side">{"".join(side)}</aside></div></main>' + _footer(base, name, v, summary))
    return code, _doc(title, desc, guide_pages.SITE + base, index, body, key, name, cta_link), 600


def _summary_text(c):
    """«3,210 مسلسلات بمواسمها و45,678 فيلمًا و4,321 قناة» — بما في السيرفر وحده."""
    bits = [f"{C._count(c['series'], C.N_SERIES)} بمواسمها" if c["series"] else "",
            C._count(c["movie"], C.N_MOVIES) if c["movie"] else "", C._count(c["live"], C.N_CHANNELS) if c["live"] else ""]
    return " و".join(b for b in bits if b)


def _footer(base, name, v, summary):
    at = league._when(v["at"]) if v["at"] else ""
    return (f'<footer class="foot"><div class="wrap"><p><a href="/">دليل سمارت سوق</a> ← <a href="{_esc(base)}">محتوى '
            f'{_esc(name)}</a></p><p>{_esc(summary)} — من قائمة الاشتراك نفسها'
            + (f' · آخر تحديث: {at} بتوقيت السعودية' if at else "") + "</p></div></footer>")


def render_missing(data_dir, key=""):
    """لا محتوى بعد (أو سيرفرٌ لا وجود له): صفحةٌ تدلّ على ما وُجد، لا تُفهرس ← (404، بايتات)."""
    others = [s for s in C.servers(data_dir) if s["key"] != key and C._has(C._view(data_dir, s["key"])[1])]
    links = "".join(f'<li><a class="link" href="{C.PATH}/{s["key"]}">محتوى {_esc(s["name"])}</a></li>' for s in others)
    body = ('<main class="wrap"><section class="panel missing"><h1>محتوى الاشتراكات</h1>'
            '<p>لم يُنشر محتوى هذا السيرفر بعد.</p>'
            + (f'<p class="empty">وهذه السيرفرات منشورٌ محتواها:</p><ul>{links}</ul>' if links else "")
            + '<div class="btns"><a class="btn" href="/#buy">ساعدني في الاختيار</a>'
            '<a class="btn ghost" href="/">الدليل</a></div></section></main>')
    return 404, _doc("محتوى الاشتراكات | سمارت سوق", "المسلسلات بمواسمها والأفلام والقنوات في كل اشتراك.",
                     guide_pages.SITE + C.PATH, False, body, key, "", "/#buy")


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
@media (max-width:900px){.top{position:static}.top .wrap{flex-wrap:wrap;gap:8px 12px;padding-block:10px}
  .search{order:3;min-width:0;flex:1 1 100%}.nav{order:2;flex:1 1 100%}}
.servers{display:flex;align-items:center;gap:8px;margin-top:14px;flex-wrap:wrap;color:var(--mute);font-size:.88rem}
.servers a{padding:6px 14px;border-radius:999px;border:1px solid var(--line);background:var(--card);color:var(--ink);font-weight:600}
.servers a[aria-current]{background:var(--acc);border-color:var(--acc)}
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
.results .other a{color:var(--acc);font-weight:600}
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
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""

JS = """
(function(){
  var K = document.body.getAttribute("data-server"), NAME = document.body.getAttribute("data-name"),
      CTA = document.body.getAttribute("data-cta") || "/#buy";
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
      if (Math.abs(dx) > 40) { hero.dataset.swiped = "1"; show(cur + (dx > 0 ? 1 : -1)); play(); }
    }, {passive: true});
    play();
  }
  // أسهم الصفوف
  document.addEventListener("click", function(e){
    var a = e.target.closest(".arrow"); if (!a) return;
    var box = $(".cards", a.closest(".row")); if (!box) return;
    box.scrollBy({left: box.clientWidth * .85 * (a.classList.contains("next") ? -1 : 1), behavior: "smooth"});
  });
  // نافذة التفاصيل
  var modal = $("#cx-modal"), last = null;
  var KIND = {movie: "فيلم", series: "مسلسل", live: "قناة"};
  var hue = function(s){ var n = 0; for (var i = 0; i < s.length; i++) n += s.charCodeAt(i); return n * 37 % 360; };
  var ini = function(s){      // كـ _initials في الخادم
    var w = s.replace(/\\p{M}/gu, "").match(/[\\p{L}\\p{N}]+/gu) || [];
    var l = w.filter(function(x){ return !/^\\p{N}+$/u.test(x); });
    return (l.length ? l : w).slice(0, 2).map(function(x){ return x[0]; }).join("").toUpperCase() || "•";
  };
  function open(d, from){
    var facts = [d.y, (d.g || []).join(" • ")].filter(Boolean).join(" · ");
    $(".sheet", modal).innerHTML = '<button class="x" type="button" aria-label="إغلاق">✕</button><div class="cover"></div>'
      + '<div class="body"><div class="pos" style="--h:' + hue(d.n || "") + '"><span class="ph">' + esc(ini(d.n || "")) + '</span>'
      + (d.p ? '<img src="' + esc(d.p) + '" alt="">' : '') + '</div><div class="txt">'
      + '<span class="kick">' + esc(KIND[d.k] || "") + (d.c ? ' · ' + esc(d.c) : '') + '</span>'
      + '<h2 id="cx-title" dir="auto">' + esc(d.n) + '</h2>' + (facts ? '<p class="facts">' + esc(facts) + '</p>' : '')
      + (d.r ? '<p class="rt">★ ' + esc(d.r) + '</p>' : '')
      + (d.ss ? '<p class="facts">' + esc(d.ss) + '</p>' : '')
      + (d.sc ? '<div class="seasons">' + d.sc.map(function(t){ return '<span>' + esc(t) + '</span>'; }).join('') + '</div>' : '')
      + (d.a ? '<p class="empty">' + (d.k === "series" ? "حُدّث " : "أضيف ") + esc(d.a) + '</p>' : '')
      + (d.d ? '<p class="plot">' + esc(d.d) + '</p>' : '')
      + '<a class="btn" href="' + esc(CTA) + '" target="_blank" rel="noopener">اشترك في ' + esc(NAME) + '</a></div></div>';
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
  var f = $(".search"), box = $("#cres");
  if (f && box) {
    var inp = f.elements.q, timer2 = 0, lastq = inp.value.trim(), seq = 0;
    var run = function(){
      var v = inp.value.trim(); if (v === lastq) return; lastq = v;
      try { history.replaceState(null, "", v ? location.pathname + "?q=" + encodeURIComponent(v) : location.pathname); } catch (e) {}
      if (v.replace(/\\s/g, "").length < 2) { box.innerHTML = ""; return; }
      var n = ++seq; box.setAttribute("aria-busy", "true");
      fetch("/api/content/search?s=" + K + "&q=" + encodeURIComponent(v))
        .then(function(r){ return r.json(); })
        .then(function(d){ if (n === seq && d && d.ok) { box.innerHTML = d.html; if (v) box.scrollIntoView({block: "nearest"}); } })
        .catch(function(){})
        .then(function(){ if (n === seq) box.removeAttribute("aria-busy"); });
    };
    inp.addEventListener("input", function(){ clearTimeout(timer2); timer2 = setTimeout(run, 250); });
    f.addEventListener("submit", function(e){ e.preventDefault(); clearTimeout(timer2); lastq = null; run(); });
  }
})();
"""


def _doc(title, desc, url, index, body, key, name, cta):
    site = guide_pages.SITE
    crumbs = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "دليل سمارت سوق", "item": site + "/"},
        {"@type": "ListItem", "position": 2, "name": title.split(" | ")[0].split(":")[0], "item": url}]}
    ld = json.dumps(crumbs, ensure_ascii=False).replace("</", "<\\/")     # اسم سيرفرٍ فيه «</script>» لا يقطع السكربت
    robots = (f'<meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large">\n'
              f'<link rel="canonical" href="{url}">' if index else '<meta name="robots" content="noindex, follow">')
    return f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
<meta name="description" content="{_esc(desc)}">
{robots}
<meta name="theme-color" content="#060b17">
<meta name="color-scheme" content="dark">
<meta property="og:type" content="website">
<meta property="og:locale" content="ar_SA">
<meta property="og:site_name" content="سمارت سوق">
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

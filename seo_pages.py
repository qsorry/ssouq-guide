# -*- coding: utf-8 -*-
"""صفحات طبقة الكيانات (المرحلة 2 — معاينة): الفيلم والمسلسل والشخص وهبّا التركي والأنمي — من ‏seo.sqlite، باللغتين.

**وضع المعاينة**: لا تُخدم إلا إن كان إعداد ‏preview مفعّلًا، وكلها ‏noindex (وسمٌ ورأس ‏X-Robots-Tag) ولا تدخل خريطة
الموقع ولا يُربط إليها من الصفحات العامة — حتى تُفحص العيّنة ويُوافَق على الفهرسة (المرحلة 3). ومع ذلك تُرسم كما ستكون:
canonical ذاتي، hreflang للغتين حين تُفهرس كلتاهما، عنوانٌ ووصفٌ فريدان، H1 واحد، فتات خبز، JSON-LD بما في الصفحة
فقط (‏Movie · TVSeries · Person · CollectionPage + ItemList · BreadcrumbList · FAQPage حين يُعرض)، روابط داخلية إلى
الأشخاص والتصنيفات والمشابه والسيرفرات، وصورٌ بـ alt وأبعاد وlazy.

الروابط: ‏/content/movies/<slug>/ · /content/series/<slug>/ · /content/people/actors|directors/<slug>/ ·
/content/turkish/ و/content/anime/ (وأقسامهما: series · movies · ongoing · completed · genres/<g>/ · year/<y>/ · page/<n>/)
— والإنجليزية بـ ‏/en قبلها. والعمل على رابطه الواحد مهما تعدّدت الهبّات والسيرفرات.

    python seo_pages.py audit --n=30      # فحص عيّنة: status · canonical · hreflang · title · description · H1 · breadcrumb · schema · links · duplicates
"""
import datetime
import json
import os
import re
import sys
import threading
import time

import content as C
import content_page as P
import guide_pages
import seo_db
import seo_guide
import seo_reco
import tournament

SITE = guide_pages.SITE
_esc = P._esc
HUBS = ("turkish", "anime")
HUB_NAMES = {"turkish": ("المسلسلات والأفلام التركية", "Turkish Series & Movies"), "anime": ("الأنمي", "Anime")}
HUB_SECTIONS = ("series", "movies", "ongoing", "completed")
SECTION_NAMES = {"series": ("المسلسلات", "Series"), "movies": ("الأفلام", "Movies"), "ongoing": ("المستمرة", "Ongoing"),
                 "completed": ("المكتملة", "Completed")}
ROLE_NAMES = {"actor": ("الممثلون", "Cast"), "voice": ("مؤدّو الأصوات", "Voice cast"), "director": ("المخرج", "Director"),
              "writer": ("الكاتب", "Writer"), "screenwriter": ("كاتب السيناريو", "Screenwriter"), "creator": ("المبتكر", "Creator")}
PERSON_PATH = {"actor": "actors", "voice": "actors", "director": "directors", "writer": "writers", "screenwriter": "writers", "creator": "writers"}
PATH_ROLES = {"actors": ("actor", "voice"), "directors": ("director",), "writers": ("writer", "screenwriter", "creator")}
PATH_NAMES = {"actors": ("الممثلون", "Actors"), "directors": ("المخرجون", "Directors"), "writers": ("الكتّاب", "Writers")}
# مقدمات تحريرية افتراضية (يحرّرها المدير من taxonomy.intro_*)
HUB_INTRO = {
    "turkish": ("دليلك إلى المسلسلات والأفلام التركية المتوفرة في اشتراكات سمارت سوق: الأعمال المدبلجة والمترجمة، الدراما التاريخية "
                "والرومانسية والأكشن، مع قصة كل عمل وأبطاله ومخرجه ومواسمه وحلقاته، وأين يتوفر بالضبط. القوائم تُحدَّث تلقائيًا من "
                "محتوى السيرفرات نفسها، فكل ما تراه هنا متاحٌ فعلًا للمشاهدة.",
                "Your guide to the Turkish series and movies available on Smart Souq subscriptions: dubbed and subtitled titles, "
                "historical drama, romance and action, with each title's story, cast, director, seasons and episodes, and exactly "
                "where it is available. Lists update automatically from the servers' own catalogs."),
    "anime": ("كل الأنمي المتوفر في اشتراكات سمارت سوق في مكانٍ واحد: المسلسلات المستمرة والمكتملة وأفلام الأنمي، مرتبةً حسب النوع "
              "والسنة والاستوديو، مع قصة كل عمل ومواسمه وحلقاته ومؤدّي الأصوات. القوائم تُحدَّث تلقائيًا من محتوى السيرفرات نفسها.",
              "All the anime available on Smart Souq subscriptions in one place: ongoing and completed series and anime films, by "
              "genre, year and studio, with each title's story, seasons, episodes and voice cast. Lists update automatically from "
              "the servers' own catalogs."),
}


# ================= الإعداد والسياسة =================
def enabled(con):
    return bool(seo_db.settings(con).get("preview"))


def indexable(row, lang, st):
    """هل تستحق صفحة العمل الفهرسة بهذه اللغة (سياسة ‏seo_settings) ← (نعم؟، السبب)."""
    if row["merged_into"] is not None or not row["available"]:
        return False, "unavailable"
    if row["match"] not in (st.get("index_match") or ["tmdb", "xtream"]) and row["match"] != "manual":
        return False, "unmatched"
    if st.get("index_require_poster", True) and not row["poster"]:
        return False, "no poster"
    ov = (row["overview_ar"] if lang == "ar" else row["overview_en"]) or (row["overview"] if lang == "ar" and not row["overview_en"] else "")
    if len(ov or "") < int(st.get("index_min_overview", 120)):
        return False, f"overview_{lang} < {st.get('index_min_overview', 120)}"
    return True, "ok"


# ================= الفهرسة الإنتاجية (المرحلة 4: seo_release) =================
APPROVED_KEY = "index_approved"     # build_state: السكّان المعتمدون للفهرسة — {snapshot, at, routes: [{id, lang, path, slug, type, batch}]}


def approved_routes(con):
    """المسارات المعتمدة للفهرسة (قائمة اعتماد المالك، تُكتب بعد بوابة المرحلة 4 أو دفعة توسيعٍ ناجحة) ← {(id, lang): بند}.
    فارغةٌ = لا شيء يُفهرس مهما كانت الأهلية."""
    ap = seo_db.state(con, APPROVED_KEY) or {}
    return {(int(r["id"]), r["lang"]): r for r in ap.get("routes") or [] if isinstance(r, dict)}


def live_index(row, lang, st, approved):
    """هل تُخدم صفحة العمل **index** فعلًا بهذه اللغة ← (نعم؟، السبب). الشرط الثلاثي، لا يُغني أحدها عن الآخر:
    index_live مفعّل (المرحلة 4) · المسار معتمدٌ بمعرّف الكيان ولغته **وبالرابط نفسه الذي اعتُمد** (slug تبدّل = لا فهرسة حتى يُعاد الاعتماد)
    · ومستحقٌّ بالسياسة الآن (indexable). فالأهلية وحدها لا تفهرس (الفصل: exists · enriched · live · eligible · indexable)."""
    if not st.get("index_live"):
        return False, "index_live off"
    a = approved.get((row["id"], lang))
    if not a:
        return False, "not approved"
    if a.get("path") != _path(row, lang) or a.get("slug") != row["slug"]:
        return False, "slug changed since approval"
    ok, why = indexable(row, lang, st)
    return (True, "ok") if ok else (False, f"approved but not eligible now: {why}")


def index_flags(con, row, st, approved=None):
    """علما الصفحتين كما تُخدمان: قبل المرحلة 4 (index_live موقوف) هما الأهلية (المعاينة noindex، لكن hreflang كما سيكون)؛
    وبعدها هما الفهرسة الفعلية (معتمدٌ ومستحقّ) ← (ar, en, live?)."""
    if not st.get("index_live"):
        return indexable(row, "ar", st)[0], indexable(row, "en", st)[0], False
    approved = approved_routes(con) if approved is None else approved
    return live_index(row, "ar", st, approved)[0], live_index(row, "en", st, approved)[0], True


# ================= اعتماد الصفحات غير الكيانية (القوائم · المواسم والحلقات · الهبّات · هب المحتوى) =================
EXTRA_KEY = "index_approved_extra"     # build_state: {at, routes: [{path (عربي بلا بادئة), lang, kind, parent}]} — يكتبه seo_release.extras
_extra_cache = {}


def extra_approved(con):
    """مسارات الصفحات غير الكيانية المعتمدة للفهرسة ← {(المسار العربي، اللغة)} (مخزَّنةٌ بوقت تحديث الحالة فلا يُحلَّل JSON كل طلب)."""
    r = con.execute("SELECT updated_at FROM build_state WHERE key=?", (EXTRA_KEY,)).fetchone()
    if not r:
        return set()
    k = (con.execute("PRAGMA database_list").fetchone()[2], r["updated_at"])
    hit = _extra_cache.get(k)
    if hit is None:
        stt = seo_db.state(con, EXTRA_KEY) or {}
        hit = {(x["path"], x["lang"]) for x in stt.get("routes") or [] if isinstance(x, dict)}
        _extra_cache.clear()
        _extra_cache[k] = hit
    return hit


def extra_flags(con, st, key, ok_ar, ok_en, parent_id=None):
    """علما صفحتَي غير-الكيان كما تُخدمان ← (ar, en, live?): قبل `index_extra_live` هما الأهلية (معاينة noindex، hreflang كما سيكون)؛ وبعده
    الفهرسة الفعلية: معتمدةٌ بمسارها ولغتها **ومستحقّةٌ الآن** — وللموسم والحلقة يُشترط أيضًا أن يكون مسلسلها معتمدًا بتلك اللغة."""
    if not (st.get("index_live") and st.get("index_extra_live")):
        return bool(ok_ar), bool(ok_en), False
    ap = extra_approved(con)
    ent = approved_routes(con) if parent_id else None

    def one(lang, ok):
        return bool(ok) and (key, lang) in ap and (not parent_id or (parent_id, lang) in ent)
    return one("ar", ok_ar), one("en", ok_en), True


# ================= أدوات =================
def _img(url, size, key=""):
    """صورة TMDB بمقاسها، وصورة لوحةٍ عبر خادمنا (‏content.img_src) بمفتاح سيرفرها — ولا رابط لوحةٍ مباشرًا."""
    if not url:
        return ""
    if "image.tmdb.org" in url:
        return C.img_src(key, url, size)
    return C.img_src(key, url, size) if key else ""


def _title(row, tr):
    ar = re.search(r"[؀-ۿ]", row["title"] or "")
    if tr.en:
        return row["title_en"] or row["original_title"] or row["title"]
    return row["title"] if ar else (row["title_ar"] or row["title"])


def _cut(s, n):
    """قصّ عند حدّ الكلمة بلا تجاوز n حرفًا."""
    if len(s) <= n:
        return s
    return s[:n].rsplit(" ", 1)[0].rstrip(" ،,:-|")


def _seo_title(title, kind_ar, typ, tr):
    """≤60 حرفًا: الكلمة المفتاحية (الاسم) + طُعم. يُقصّ الاسم الطويل لا الطُّعم."""
    if tr.en:
        hook = "Guide: Plot, Cast, Seasons & Where to Watch" if typ == "series" else "Plot, Cast & Where to Watch"
        sep = " " if typ == "series" else ": "
        names = (title, _cut(title, 60 - len(sep) - len(hook)))
    else:
        hook = "القصة، الحلقات، وأين تشاهد" if typ == "series" else "القصة، الممثلون، وأين تشاهد"
        names = (f"{kind_ar} {title}", _cut(f"{kind_ar} {title}", 60 - 2 - len(hook)))
        sep = ": "
    for n in names:
        t = f"{n}{sep}{hook}"
        if len(t) <= 60:
            return t
    return _cut(names[-1], 60)


def _seo_desc(desc, tr):
    """≤155 حرفًا بدعوةٍ إلى الفعل حين يتّسع المكان."""
    cta = tr(" اكتشف التفاصيل الآن!", " Explore the full guide now!")
    d = desc.rstrip(" ،,.") + "."
    return d + cta if len(d + cta) <= 155 else _cut(d, 154).rstrip(" ،,.") + "."


def _overview(row, tr):
    return (row["overview_en"] or "") if tr.en else (row["overview_ar"] or row["overview"] or "")


def _loads(s, default=None):
    try:
        return json.loads(s) if s else (default if default is not None else [])
    except ValueError:
        return default if default is not None else []


def _path(row, lang="ar"):
    return seo_db.lang_prefix(lang) + seo_db.PATHS[row["type"]].format(slug=row["slug"])


def _hub_path(hub, section="", lang="ar", page=1):
    return seo_db.lang_prefix(lang) + f"/content/{hub}/" + (f"{section}/" if section else "") + (f"page/{page}/" if page > 1 else "")


def _person_path(role, slug, lang="ar", page=1):
    return seo_db.lang_prefix(lang) + f"/content/people/{PERSON_PATH.get(role, 'actors')}/{slug}/" + (f"page/{page}/" if page > 1 else "")


def _company_path(slug, lang="ar", page=1):
    return seo_db.lang_prefix(lang) + f"/content/companies/{slug}/" + (f"page/{page}/" if page > 1 else "")


_MONTHS_AR = ("يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر")
_MONTHS_EN = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")


def _fdate(iso, tr):
    """‏2026-10-21 ← «21 أكتوبر 2026» / «October 21, 2026» (وما لا يُحلَّل يُعاد كما هو)."""
    try:
        y, m, d = (int(x) for x in str(iso)[:10].split("-"))
        return f"{_MONTHS_EN[m - 1]} {d}, {y}" if tr.en else f"{d} {_MONTHS_AR[m - 1]} {y}"
    except (ValueError, IndexError):
        return str(iso or "")


def airing_info(row, seasons, n_seasons, n_eps_txt, tr, today=None):
    """حال عرض مسلسلٍ كما في TMDB ← None (لا حال معروف أو فيلم) أو {live, status, head, detail, faq_a}.
    ‏live: ما زال يُعرض أو موسمٌ قادم (فأعداده «حتى الآن»). لا يُدّعى ما لا تدعمه البيانات (الحلقة القادمة والتواريخ من TMDB وقت آخر تجديد)."""
    st = (row["status"] or "")
    if row["type"] != "series" or not st:
        return None
    today = today or datetime.date.today().isoformat()
    nxt, nxt_s, nxt_e = row["next_air_date"], row["next_air_season"], row["next_air_episode"]
    last, last_s, last_n = row["last_ep_date"] or row["last_air_date"], row["last_ep_season"], row["last_ep_number"]
    fut = next((x for x in seasons if x["number"] > 0 and x["air_date"] and x["air_date"] > today), None)

    def ep(season, number):
        if season and number:
            return tr(f"الموسم {season} الحلقة {number}", f"season {season}, episode {number}")
        return tr(f"الحلقة {number}", f"episode {number}") if number else ""
    last_txt = ""
    if last and last_n:
        last_txt = tr(f"آخر حلقة عُرضت: {ep(last_s, last_n)} ({_fdate(last, tr)}).", f"Latest aired: {ep(last_s, last_n)} ({_fdate(last, tr)}).")
    elif last:
        last_txt = tr(f"آخر عرض: {_fdate(last, tr)}.", f"Last aired: {_fdate(last, tr)}.")
    live, short, head, detail = False, "", "", ""
    recent = False
    try:
        recent = bool(last) and (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(str(last)[:10])).days <= 100
    except ValueError:
        pass
    if st == "Canceled":
        short, head = tr("أُوقف", "Cancelled"), tr("أُوقف المسلسل", "This series was cancelled")
        detail = tr(f"أُوقف بعد {tr.count(n_seasons, 'seasons')}، ولا مواسم جديدة بحسب TMDB.", f"It ended after {tr.count(n_seasons, 'seasons')}; no new seasons according to TMDB.") if n_seasons else tr("لا مواسم جديدة بحسب TMDB.", "No new seasons according to TMDB.")
    elif st == "Ended":
        short, head = tr("منتهٍ", "Ended"), tr("انتهى عرض المسلسل", "This series has ended")
        detail = tr(f"اكتمل بعد {n_eps_txt}، ولم يُعلن عن موسمٍ جديد بحسب TMDB.", f"It finished after {n_eps_txt}; no new season announced according to TMDB.") if n_eps_txt else tr("لم يُعلن عن موسمٍ جديد بحسب TMDB.", "No new season announced according to TMDB.")
    elif st in ("In Production", "Planned", "Pilot"):
        live, short, head = True, tr("قيد الإنتاج", "In production"), tr("قيد الإنتاج", "In production")
        detail = tr(f"القادمة: {ep(nxt_s, nxt_e)} — {_fdate(nxt, tr)}." if nxt else "لم يبدأ عرضه بعد أو لم يُحدَّد موعد حلقته القادمة.",
                    f"Next: {ep(nxt_s, nxt_e)} — {_fdate(nxt, tr)}." if nxt else "It has not started airing or no next date is set.")
    elif st == "Returning Series":
        live = True
        if nxt and nxt >= today:
            short, head = tr("ما زال يُعرض", "Still airing"), tr("ما زال يُعرض الآن", "Still airing now")
            detail = tr(f"الحلقة القادمة: {ep(nxt_s, nxt_e)} — {_fdate(nxt, tr)}. {last_txt}", f"Next episode: {ep(nxt_s, nxt_e)} — {_fdate(nxt, tr)}. {last_txt}").strip()
        elif recent:
            short, head = tr("ما زال يُعرض", "Still airing"), tr("ما زال يُعرض", "Still airing")
            detail = tr(f"{last_txt} لم يُعلن موعد الحلقة القادمة بعد.", f"{last_txt} The next episode date has not been announced yet.").strip()
        elif fut:
            short, head = tr("موسم قادم", "New season coming"), tr("موسمٌ جديد قادم", "A new season is coming")
            detail = tr(f"الموسم {fut['number']} يبدأ {_fdate(fut['air_date'], tr)}. {last_txt}", f"Season {fut['number']} starts {_fdate(fut['air_date'], tr)}. {last_txt}").strip()
        else:
            short, head = tr("مستمر", "Ongoing"), tr("مسلسلٌ مستمر (بين المواسم)", "Ongoing (between seasons)")
            detail = tr(f"{last_txt} لم يُعلن عن حلقةٍ أو موسمٍ قادم بعد.", f"{last_txt} No upcoming episode or season has been announced yet.").strip()
    else:
        return None
    upd = row["tmdb_refreshed_at"]
    note = tr(f"بحسب TMDB، آخر تحديثٍ للبيانات {_fdate(datetime.date.fromtimestamp(upd).isoformat(), tr)}.", f"According to TMDB; data last refreshed {_fdate(datetime.date.fromtimestamp(upd).isoformat(), tr)}.") if upd else tr("بحسب TMDB.", "According to TMDB.")
    return {"live": live, "short": short, "head": head, "detail": detail, "note": note, "faq_a": f"{head}. {detail} {note}".replace("  ", " ").strip()}


_tl = threading.local()          # اتصال الطلب الجاري: البطاقات تجد منه سيرفر صورة العمل بلا تغيير كل استعلام قوائم


def skey_of(con, cid):
    """مفتاح السيرفر الذي يخدم صورة عملٍ (ملصق اللوحة لا يُجلب إلا بمفتاح سيرفره) ← "" إن لم يكن."""
    r = con.execute("SELECT service_key FROM content_service WHERE content_id=? AND present=1 ORDER BY seen_at DESC LIMIT 1", (int(cid),)).fetchone()
    return r[0] if r else ""


def _card_skey(row):
    keys = row.keys()
    if "skey" in keys:
        return row["skey"]
    url = row["poster"] if "poster" in keys else None
    con = getattr(_tl, "con", None)
    if not url or "image.tmdb.org" in url or con is None or "id" not in keys:      # ملصق TMDB لا يحتاج مفتاحًا
        return ""
    return skey_of(con, row["id"])


def _card(row, tr, lazy=True):
    t = _title(row, tr)
    sub = " · ".join(x for x in (str(row["year"] or ""), f"{row['rating']:g} ★" if row["rating"] else "") if x)
    img = _img(row["poster"], "w342", _card_skey(row))
    alt = _esc(tr(f"ملصق {'مسلسل' if row['type'] == 'series' else 'فيلم'} {t}", f"{t} poster"))
    pic = (f'<img src="{_esc(img)}" alt="{alt}" width="342" height="513"{" loading=lazy decoding=async" if lazy else ""}>'
           if img else f'<span class="ph" aria-hidden="true">{_esc(P._initials(t))}</span>')
    return (f'<a class="card" href="{_esc(_path(row, tr.code))}"><span class="pos">{pic}</span>'
            f'<b dir="auto">{_esc(t)}</b>{f"<small>{_esc(sub)}</small>" if sub else ""}</a>')


def _grid(rows, tr):
    return '<div class="grid">' + "".join(_card(r, tr) for r in rows) + "</div>"


def _crumbs(items):
    """[(الاسم، الرابط أو "")] ← (HTML، JSON-LD)."""
    html = '<nav class="crumbs" aria-label="breadcrumb"><ol>' + "".join(
        f'<li><a href="{_esc(u)}">{_esc(n)}</a></li>' if u else f'<li aria-current="page">{_esc(n)}</li>' for n, u in items) + "</ol></nav>"
    ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": n, **({"item": SITE + u} if u else {})} for i, (n, u) in enumerate(items)]}
    return html, ld


def _ld(obj):
    return '<script type="application/ld+json">' + json.dumps(obj, ensure_ascii=False).replace("</", "<\\/") + "</script>"


def _doc(tr, title, desc, canonical, alts, body, lds, og_image="", og_type="website", noindex=True, extra_head=""):
    """الوثيقة: الرأس (robots · canonical · hreflang · OG · Twitter · JSON-LD) والجسم بالـ CSS."""
    alt_links = "".join(f'<link rel="alternate" hreflang="{c}" href="{_esc(u)}">' for c, u in alts)
    robots = "noindex, follow" if noindex else "index, follow, max-snippet:-1, max-image-preview:large"
    img = og_image or f"{SITE}/static/og-image.png"
    return (f'<!doctype html>\n<html lang="{tr.code}" dir="{tr.dir}">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">\n<title>{_esc(title)}</title>\n'
            f'<meta name="description" content="{_esc(desc)}">\n<meta name="robots" content="{robots}">\n'
            f'<link rel="canonical" href="{_esc(canonical)}">\n{alt_links}\n'
            f'<meta property="og:type" content="{og_type}"><meta property="og:locale" content="{"en_US" if tr.en else "ar_SA"}">'
            f'<meta property="og:site_name" content="{_esc(tr("سمارت سوق", "Smart Souq"))}"><meta property="og:title" content="{_esc(title)}">'
            f'<meta property="og:description" content="{_esc(desc)}"><meta property="og:url" content="{_esc(canonical)}">'
            f'<meta property="og:image" content="{_esc(img)}">\n<meta name="twitter:card" content="summary_large_image">'
            f'<meta name="twitter:title" content="{_esc(title)}"><meta name="twitter:description" content="{_esc(desc)}">'
            f'<meta name="twitter:image" content="{_esc(img)}">\n<meta name="theme-color" content="#060b17">\n'
            f'<link rel="icon" href="/favicon.ico">\n<link rel="preconnect" href="https://image.tmdb.org">\n{extra_head}'
            + "".join(_ld(x) for x in lds) + f"\n<style>{CSS}</style>\n</head>\n<body>\n{body}\n</body>\n</html>").encode("utf-8")


def _header(tr, hub=""):
    home = tr.path
    links = [(tr("المحتوى", "Content"), home), (HUB_NAMES["turkish"][tr.en], _hub_path("turkish", "", tr.code)),
             (HUB_NAMES["anime"][tr.en], _hub_path("anime", "", tr.code))]
    nav = "".join(f'<a href="{_esc(u)}"{" aria-current=page" if hub and u == _hub_path(hub, "", tr.code) else ""}>{_esc(n)}</a>' for n, u in links)
    return (f'<header class="top"><div class="wrap"><a class="brand" href="{home}"><b>{_esc(tr("سمارت سوق", "Smart Souq"))}</b>'
            f'<small>{_esc(guide_pages.SITE_NETLOC)}</small></a><nav class="nav">{nav}</nav></div></header>')


def _switch(tr, other_path):
    other = P.EN if not tr.en else P.AR
    return f'<a class="lang" href="{_esc(other_path)}" hreflang="{other.code}" lang="{other.code}">{other("العربية", "English")}</a>'


def _footer(tr):
    return (f'<footer class="foot"><div class="wrap"><p>{_esc(tr("القوائم تُحدَّث تلقائيًا من محتوى اشتراكات سمارت سوق.", "Lists update automatically from Smart Souq subscription catalogs."))}'
            f' <a href="{tr.path}">{_esc(tr("ماذا في كل اشتراك؟", "What is in each subscription?"))}</a></p></div></footer>')


# ================= صفحة العمل =================
def _services(con, cid, tr):
    """متوفر عبر: السيرفرات التي فيها العمل (بنسخه) وباقاتها من CATALOG — وCTA."""
    srvs = {s["key"]: s for s in C.servers(_services.data_dir)}
    links = con.execute("SELECT service_key, versions_json, seasons_json FROM content_service WHERE content_id=? AND present=1", (cid,)).fetchall()
    if not links:
        return "", []
    cat = P._catalog()
    VER = {"dubbed": ("مدبلج", "Dubbed"), "subbed": ("مترجم", "Subtitled"), "subbed_soft": ("مترجم (سوفت)", "Soft-subtitled")}
    by_srv = {}                                    # السيرفر مرةً واحدة مهما تعدّدت صفوفه (قسمان في قوائمه): نسخه اتحاد نسخ صفوفه
    for ln in links:
        vs = by_srv.setdefault(ln["service_key"], [])
        vs.extend(v for v in _loads(ln["versions_json"]) if v in VER and v not in vs)
    out, names = [], []
    for key in [s["key"] for s in srvs.values() if s["key"] in by_srv]:
        srv = srvs[key]
        name = tr.name(srv)
        names.append(name)
        vers = " · ".join(VER[v][tr.en] for v in by_srv[key])
        plans = [cat[i] for i in C.PLANS.get(srv["key"], ()) if i in cat][:1]
        url = srv.get("buy") or (plans[0]["url"] if plans else "/#buy")
        price = f'{P._money(plans[0]["price"]):g} {tr("ر.س", "SAR")}' if plans and P._money(plans[0]["price"]) else ""
        out.append(f'<li>{P._logo(srv["key"], name, "logo")}<span><b>{_esc(name)}</b>{f"<small>{_esc(vers)}</small>" if vers else ""}</span>'
                   f'<a class="btn" href="{_esc(P._utm(url, "content-entity"))}" rel="nofollow">{_esc(tr("اشترك", "Subscribe"))}{f" · {price}" if price else ""}</a></li>')
    html = (f'<section class="avail" id="available"><h2>{_esc(tr("أين يمكنك المشاهدة؟", "Streaming Platforms & Availability"))}</h2><ul class="srv">{"".join(out)}</ul>'
            f'<p class="cta">{_esc(tr("اشترك الآن للوصول إلى آلاف الأفلام والمسلسلات.", "Subscribe now for thousands of movies and series."))}</p></section>')
    return html, names


def _people(con, cid, tr):
    rows = con.execute("SELECT p.id, p.slug, p.name, p.name_ar, p.name_en, p.photo, cp.role, cp.character FROM content_person cp JOIN person p ON p.id=cp.person_id "
                       "WHERE cp.content_id=? ORDER BY CASE cp.role WHEN 'director' THEN 0 WHEN 'creator' THEN 1 WHEN 'writer' THEN 2 ELSE 3 END, cp.ord", (cid,)).fetchall()
    by, seen = {}, set()
    for r in rows:
        k = (r["role"], r["id"])
        if k in seen:
            continue
        seen.add(k)
        by.setdefault(r["role"], []).append(r)
    return by


def _companies(con, cid):
    return con.execute("SELECT co.id, co.slug, co.name, co.kind, co.logo, co.country, cc.role FROM content_company cc JOIN company co ON co.id=cc.company_id "
                       "WHERE cc.content_id=? ORDER BY CASE cc.role WHEN 'studio' THEN 0 ELSE 1 END, co.id", (cid,)).fetchall()


def _pname(p, tr):
    return (p["name_en"] if tr.en else p["name_ar"]) or p["name"]


def _person_chip(p, tr, work=""):
    img = _img(p["photo"], "w185")
    name = _pname(p, tr)
    alt = _esc(tr(f"{name} في {work}", f"{name} in {work}") if work else name)
    pic = f'<img src="{_esc(img)}" alt="{alt}" width="185" height="278" loading=lazy decoding=async>' if img else f'<span class="ph">{_esc(P._initials(name))}</span>'
    character = f"<small>{_esc(p['character'])}</small>" if p["character"] else ""
    return f'<a class="person" href="{_esc(_person_path(p["role"], p["slug"], tr.code))}"><span class="pos">{pic}</span><b>{_esc(name)}</b>{character}</a>'


def _similar(con, row, tr, st):
    """قد يعجبك أيضًا: أكبر اشتراكٍ في التصنيف (النوع والبلد واللغة والهب) ثم القرب في السنة ثم التقييم — 12 عملًا."""
    mine = [r[0] for r in con.execute("SELECT taxonomy_id FROM content_taxonomy WHERE content_id=? AND source!='hint'", (row["id"],))]
    if not mine:
        return []
    qs = ",".join("?" * len(mine))
    return con.execute(f"SELECT c.*, COUNT(*) shared FROM content_taxonomy ct JOIN content c ON c.id=ct.content_id "
                       f"WHERE ct.taxonomy_id IN ({qs}) AND ct.source IN ('tmdb','manual') AND c.id!=? AND c.merged_into IS NULL AND c.available=1 AND c.poster IS NOT NULL "
                       f"GROUP BY c.id ORDER BY shared DESC, ABS(COALESCE(c.year,0)-?) ASC, COALESCE(c.rating,0) DESC LIMIT 12",
                       (*mine, row["id"], row["year"] or 0)).fetchall()


def _tax(con, cid):
    return con.execute("SELECT t.* FROM content_taxonomy ct JOIN taxonomy t ON t.id=ct.taxonomy_id WHERE ct.content_id=? AND ct.source IN ('tmdb','manual') ORDER BY t.kind, t.sort, t.id", (cid,)).fetchall()


def _tname(t, tr):
    return (t["name_en"] if tr.en else t["name_ar"]) or t["name_en"] or t["name_ar"] or t["key"]


def _override(con, entity, entity_id, lang):
    """تجاوز المدير (المرحلة 5: seo_override) للغةٍ بعينها ← dict أو {} — العنوان والوصف والمقدمة وعلم الفهرسة."""
    r = con.execute("SELECT * FROM seo_override WHERE entity=? AND entity_id=? AND lang=?", (entity, entity_id, lang)).fetchone()
    return dict(r) if r else {}


def _like_widget(con, row, tr):
    """زرّ «أعجبني» + قسم «مقترحات لك» (يُملأ بسكربتٍ صغير من سلوك الزائر المحفوظ في جهازه) + السكربت ← (شريط الإعجاب، قسم المقترحات، السكربت)."""
    n = seo_reco.like_count(con, row["id"])
    bar = (f'<div class="like-bar"><button type="button" class="like-btn" id="likeBtn" aria-pressed="false"><span class="heart" aria-hidden="true">♡</span> '
           f'<span class="lbl">{_esc(tr("أعجبني", "Like"))}</span> <b id="likeN">{n if n else ""}</b></button></div>')
    fy = (f'<section id="foryou" class="foryou" hidden><h2>{_esc(tr("مقترحات لك", "Picked for you"))}</h2><p class="meta" id="fyWhy"></p>'
          f'<div class="grid" id="fyGrid"></div><p class="meta">{_esc(tr("تُحفظ تفضيلاتك في جهازك فقط، ولا نخزّن شيئًا عنك.", "Your preferences stay on your device only; we store nothing about you."))}</p></section>')
    labels = {"like": tr("أعجبني", "Like"), "liked": tr("أعجبك", "Liked")}
    js = ("(function(){var slug=%s,lang=%s,L=%s;"
          "function rd(k){try{var v=JSON.parse(localStorage.getItem(k)||'[]');return Array.isArray(v)?v:[]}catch(e){return[]}}"
          "function wr(k,v){try{localStorage.setItem(k,JSON.stringify(v))}catch(e){}}"
          "var likes=rd('ssq_likes'),seen=rd('ssq_seen');"
          "seen=[slug].concat(seen.filter(function(x){return x!==slug})).slice(0,80);wr('ssq_seen',seen);"
          "var btn=document.getElementById('likeBtn'),nEl=document.getElementById('likeN'),box=document.getElementById('foryou');"
          "if(!btn||!box)return;"
          "function paint(){var on=likes.indexOf(slug)>-1;btn.setAttribute('aria-pressed',on?'true':'false');btn.classList.toggle('on',on);"
          "btn.querySelector('.heart').textContent=on?'\u2665':'\u2661';btn.querySelector('.lbl').textContent=on?L.liked:L.like}"
          "function card(it){var a=document.createElement('a');a.className='card';a.href=it.path;var p=document.createElement('span');p.className='pos';"
          "if(it.poster){var im=document.createElement('img');im.src=it.poster;im.alt=it.title;im.width=342;im.height=513;im.loading='lazy';p.appendChild(im)}"
          "if(it.rating){var rb=document.createElement('i');rb.className='rt-badge';rb.textContent='\\u2605 '+(Math.round(it.rating*10)/10);p.appendChild(rb)}"
          "var b=document.createElement('b');b.dir='auto';b.textContent=it.title;a.appendChild(p);a.appendChild(b);"
          "var t=[it.year||'',it.rating?(Math.round(it.rating*10)/10)+' \u2605':''].filter(Boolean).join(' \u00b7 ');"
          "if(t){var s=document.createElement('small');s.textContent=t;a.appendChild(s)}a.addEventListener('click',function(){if(window.sq)sq('reco_click',it.path.replace(/^\\/en/,'').split('/')[3]||'')});return a}"
          "function render(d){var g=document.getElementById('fyGrid');if(!d||!d.items||!d.items.length||d.cold){box.hidden=true;return}"
          "g.textContent='';d.items.forEach(function(it){g.appendChild(card(it))});"
          "var w=d.items.filter(function(i){return i.why})[0];document.getElementById('fyWhy').textContent=w?w.why:'';box.hidden=false}"
          "function reco(){if(!likes.length&&seen.length<2){box.hidden=true;return}"
          "fetch('/api/content/recommend?lang='+lang+'&likes='+encodeURIComponent(likes.slice(0,30).join(','))+'&seen='+encodeURIComponent(seen.slice(0,60).join(','))+'&interests='+encodeURIComponent(rd('ssq_interests').join(','))+'&types='+encodeURIComponent(rd('ssq_types').join(',')))"
          ".then(function(r){return r.json()}).then(render).catch(function(){})}"
          "btn.onclick=function(){var on=likes.indexOf(slug)<0;likes=likes.filter(function(x){return x!==slug});if(on)likes.unshift(slug);likes=likes.slice(0,40);wr('ssq_likes',likes);paint();if(on&&window.sq)sq('like',slug);"
          "fetch('/api/content/like',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({slug:slug,on:on})})"
          ".then(function(r){return r.json()}).then(function(d){if(d&&typeof d.count==='number')nEl.textContent=d.count>0?d.count:''}).catch(function(){});reco()};"
          "paint();reco()})();") % (json.dumps(row["slug"]), json.dumps(tr.code), json.dumps(labels, ensure_ascii=False))
    return bar, fy, f"<script>{js}</script>"


def render_entity(con, data_dir, typ, slug, tr, st, query=None):
    _services.data_dir = data_dir
    row = con.execute("SELECT * FROM content WHERE type=? AND slug=?", (typ, slug)).fetchone()
    if not row:
        r = con.execute("SELECT target FROM redirect WHERE path=?", (seo_db.PATHS[typ].format(slug=slug),)).fetchone()
        return ("redirect", (seo_db.EN if tr.en else "") + r["target"]) if r else None
    if row["merged_into"] is not None:
        w = con.execute("SELECT type, slug FROM content WHERE id=?", (row["merged_into"],)).fetchone()
        return "redirect", _path(w, tr.code)
    title, kind_ar = _title(row, tr), "مسلسل" if typ == "series" else "فيلم"
    ov = _overview(row, tr)
    tax = _tax(con, row["id"])
    by_kind = {}
    for t in tax:
        by_kind.setdefault(t["kind"], []).append(t)
    people = _people(con, row["id"], tr)
    seasons = con.execute("SELECT * FROM season WHERE content_id=? ORDER BY number", (row["id"],)).fetchall() if typ == "series" else []
    # الحلقات: الرسمي من TMDB إن وُجد، وإلا المدرج في القوائم (عناصر قد تكون أجزاءً) — ويُقال أيّهما
    # قاعدة الرقم: الرسمي (TMDB) إن وُجد وكان موثوقًا؛ وإلا المدرج في القوائم بصياغةٍ صريحة «X حلقة مدرجة على فالكون» — ولا يصير
    # المدرج رسميًّا في العنوان أو الوصف أو JSON-LD. والموسم 0 (الخاصة) لا يُعدّ موسمًا.
    n_official = row["episodes_official"] or (sum(s["episodes_official"] or 0 for s in seasons) or None)
    n_listed = sum(s["episode_count"] for s in seasons if s["number"] > 0)
    if n_official and n_listed and n_official < 3 and n_listed > 3 * n_official:
        n_official = None                        # سجلّ TMDB ناقص (حلقة واحدة لعملٍ بعشرات الحلقات في القوائم): لا يُعرض رقمًا رسميًّا
    n_eps = n_official or n_listed
    n_seasons = row["seasons_official"] if n_official and row["seasons_official"] else len([s for s in seasons if s["number"] > 0])
    n_specials = next((s["episodes_official"] or 0 for s in seasons if s["number"] == 0), 0)   # الموسم 0 = الحلقات الخاصة: صفٌّ مستقل، لا موسم
    _srv_names = [tr.name(s) for s in C.servers(_services.data_dir) if s["key"] in {ln[0] for ln in con.execute("SELECT service_key FROM content_service WHERE content_id=? AND present=1", (row["id"],))}]
    listed_tail = tr(f" مدرجة على {_srv_names[0]}", f" listed on {_srv_names[0]}") if len(_srv_names) == 1 else tr(" في القوائم", " as listed")
    eps_label = (lambda n: tr.count(n, "episodes") + ("" if n_official else listed_tail))
    hubs = [t for t in by_kind.get("hub", [])]
    countries = by_kind.get("country", [])
    langs = by_kind.get("language", [])
    genres = by_kind.get("genre", [])
    director = (people.get("director") or people.get("creator") or [None])[0]
    cast = people.get("actor") or people.get("voice") or []
    avail_html, srv_names = _services(con, row["id"], tr)
    airing = airing_info(row, seasons, n_seasons, (f"{tr.count(n_seasons, 'seasons')} {tr('و', 'and ')}{eps_label(n_eps)}" if seasons and n_eps else ""), tr)
    # العنوان والوصف
    bits = [tr("قصة " + kind_ar, "Story"), tr("الممثلون", "Cast")] + ([tr("المواسم والحلقات", "Seasons & Episodes")] if typ == "series" else [])
    if director:
        bits.append(tr("المخرج", "Director"))
    page_title = _seo_title(title, kind_ar, typ, tr)
    desc_bits = []
    if row["year"]:
        desc_bits.append(tr(f"إنتاج {row['year']}", f"{row['year']}"))
    if countries:
        desc_bits.append(_tname(countries[0], tr))
    if genres:
        desc_bits.append(tr("، ", ", ").join(_tname(g, tr) for g in genres[:3]))
    if typ == "series" and seasons:
        desc_bits.append(tr(f"{tr.count(n_seasons, 'seasons')} و{eps_label(n_eps)}", f"{tr.count(n_seasons, 'seasons')}, {eps_label(n_eps)}") + (tr(" حتى الآن", " so far") if airing and airing["live"] else ""))
    if airing and airing["live"]:
        desc_bits.append(airing["short"])
    if cast:
        desc_bits.append(tr("بطولة ", "Starring ") + tr("، ", ", ").join(_pname(p, tr) for p in cast[:3]))
    desc = tr(f"تعرف على قصة {kind_ar} {title}", f"{title}: story, cast") + (tr("، ", ". ") + tr("، ", ", ").join(desc_bits) if desc_bits else "") \
        + (tr(f". متوفر عبر {tr.join(srv_names)}.", f". Available on {tr.join(srv_names)}.") if srv_names else ".")
    desc = _seo_desc(desc, tr)
    # الفتات
    crumbs = [(tr("الرئيسية", "Home"), "/"), (tr("المحتوى", "Content"), tr.path), (tr("المسلسلات" if typ == "series" else "الأفلام", "Series" if typ == "series" else "Movies"), tr.path)]
    if hubs:
        crumbs.append((HUB_NAMES.get(hubs[0]["key"], (hubs[0]["key"], hubs[0]["key"]))[tr.en], _hub_path(hubs[0]["key"], "", tr.code)))
    crumbs.append((title, ""))
    crumb_html, crumb_ld = _crumbs(crumbs)
    # الرأس
    skey = (con.execute("SELECT service_key FROM content_service WHERE content_id=? AND present=1 ORDER BY seen_at DESC LIMIT 1", (row["id"],)).fetchone() or [""])[0]
    poster, backdrop = _img(row["poster"], "w500", skey), _img(row["backdrop"], "w780", skey)
    facts = [(tr("سنة الإنتاج", "Year"), str(row["year"]) if row["year"] else ""),
             (tr("الدولة", "Country"), tr("، ", ", ").join(_tname(c, tr) for c in countries)),
             (tr("اللغة", "Language"), tr("، ", ", ").join(_tname(x, tr) for x in langs)),
             (tr("التصنيف", "Genre"), tr("، ", ", ").join(f'<a href="{_esc(_hub_path(hubs[0]["key"], "genres/" + g["slug"], tr.code) if hubs else tr.path)}">{_esc(_tname(g, tr))}</a>' for g in genres)),
             (tr("المدة", "Runtime"), tr(f"{row['runtime']} دقيقة", f"{row['runtime']} min") if row["runtime"] else ""),
             (tr("التقييم", "Rating"), f"{row['rating']:g}/10" if row["rating"] else ""),
             (tr("الحالة", "Status"), airing["short"] if airing else "") if typ == "series" else ("", ""),
             (tr("المواسم", "Seasons"), str(n_seasons) if seasons else ""), (tr("الحلقات", "Episodes"), (str(n_eps) if n_official else eps_label(n_eps)) if n_eps else ""),
             (tr("الحلقات الخاصة", "Specials"), str(n_specials) if n_specials else ""),
             (ROLE_NAMES[director["role"]][tr.en] if director else "", f'<a href="{_esc(_person_path(director["role"], director["slug"], tr.code))}">{_esc(_pname(director, tr))}</a>' if director else "")]
    facts = [(k, v) for k, v in facts if k and v]
    facts_html = "".join(f"<dt>{_esc(k)}</dt><dd>{v if v.startswith('<a') else _esc(v)}</dd>" for k, v in facts)
    chips = "".join(f'<a class="chip" href="{_esc(_hub_path(h["key"], "", tr.code))}">{_esc(HUB_NAMES.get(h["key"], (h["key"], h["key"]))[tr.en])}</a>' for h in hubs)
    if row["format"].startswith("anime") and row["anime_kind"]:
        chips += f'<span class="chip">{_esc({"japanese": tr("أنمي ياباني", "Japanese anime"), "chinese": tr("رسوم متحركة صينية", "Chinese animation"), "korean": tr("رسوم متحركة كورية", "Korean animation")}.get(row["anime_kind"], row["anime_kind"]))}</span>'
    alt_poster = _esc(tr(f"ملصق {kind_ar} {title}", f"{title} poster"))
    head = (f'<section class="hero">{f"<img class=bg src={chr(34)}{_esc(backdrop)}{chr(34)} alt={chr(34)}{chr(34)} aria-hidden=true>" if backdrop else ""}'
            f'<div class="wrap hd"><div class="pos">{f"<img src={chr(34)}{_esc(poster)}{chr(34)} alt={chr(34)}{alt_poster}{chr(34)} width=500 height=750 fetchpriority=high>" if poster else f"<span class=ph>{_esc(P._initials(title))}</span>"}</div>'
            f'<div class="meta"><h1 dir="auto">{_esc(title)}</h1>'
            + (f'<p class="orig" dir="auto">{_esc(row["original_title"])}</p>' if row["original_title"] and row["original_title"] != title else "")
            + f'<p class="chips">{chips}</p><dl class="facts">{facts_html}</dl></div></div></section>')
    # القصة
    story = (f'<section class="story"><h2>{_esc(tr(f"قصة {kind_ar}", "Plot Overview"))}</h2><p dir="auto">{_esc(ov)}</p></section>' if ov else "")
    air_html = (f'<aside class="airing{" live" if airing["live"] else ""}" id="airing" aria-label="{_esc(tr("حال العرض", "Airing status"))}"><b>{_esc(airing["head"])}</b>'
                f'<span>{_esc(airing["detail"])}</span><small>{_esc(airing["note"])}</small></aside>') if airing else ""
    # دليل الأهل: بعد القصة؛ بلا بياناتٍ يُكتب «لا يوجد دليل بعد» لا «آمن»
    guide_html, guide_rating = seo_guide.section(con, row["id"], slug, typ, tr)
    # المخرج والممثلون
    ppl = ""
    if director:
        ppl += f'<section><h2>{_esc(ROLE_NAMES[director["role"]][tr.en])}</h2><div class="people">{_person_chip(director, tr, title)}</div></section>'
    if cast:
        ppl += f'<section><h2>{_esc(tr("طاقم العمل والشخصيات", "Cast & Key Characters"))}</h2><div class="people">{"".join(_person_chip(p, tr, title) for p in cast[:12])}</div></section>'
    writers = [p for r in ("creator", "writer", "screenwriter") for p in people.get(r) or [] if not (director and p["id"] == director["id"])]
    if writers:
        ppl += f'<section><h2>{_esc(tr("الكتّاب", "Writers"))}</h2><div class="people">{"".join(_person_chip(p, tr, title) for p in writers[:8])}</div></section>'
    companies = _companies(con, row["id"])
    if companies:   # الشركة المنتجة كيانٌ بصفحته — ليست سيرفر الاشتراك (Casper/Smart/Falcon = توفّر)
        ppl += (f'<section><h2>{_esc(tr("الإنتاج", "Production"))}</h2><p class="chips">'
                + "".join(f'<a class="chip" href="{_esc(_company_path(c["slug"], tr.code))}">{_esc(c["name"])}</a>' for c in companies) + "</p></section>")
    # المواسم والحلقات
    seas = ""
    if seasons:
        items = []
        for s in seasons:
            eps = con.execute("SELECT * FROM episode WHERE content_id=? AND season=? ORDER BY number LIMIT 100", (row["id"], s["number"])).fetchall()
            name = s["name"] if tr.en and s["name"] else (tr("الحلقات الخاصة", "Specials") if s["number"] == 0 else tr(f"الموسم {s['number']}", f"Season {s['number']}"))
            ep_html = ""
            if eps:
                lis = []
                for e in eps:
                    et = (e["title_en"] if tr.en else e["title_ar"] or e["title_en"]) or ""
                    lis.append(f'<li><span>{e["number"]}</span> {_esc(et)}' + (f' <small>{_esc(e["air_date"])}</small>' if e["air_date"] else "") + "</li>")
                ep_html = "<ol class=eps>" + "".join(lis) + "</ol>"
            s_label = tr.count(s["episodes_official"], "episodes") if s["episodes_official"] else (tr.count(s["episode_count"], "episodes") + tr(" في القوائم", " as listed"))
            if s["number"] == 0:
                name = tr("حلقات خاصة", "Specials")
            if s["number"] > 0 and (season_ok(s, eps, tr.code, st)[0] or any(episode_ok(e, tr.code, st) for e in eps)):
                name_html = f'<a href="{_esc(_season_path(row, s["number"], tr.code))}">{_esc(name)}</a>'
            else:
                name_html = _esc(name)
            items.append(f'<details{" open" if s is seasons[0] else ""}><summary><b>{name_html}</b> <small>{_esc(s_label)}</small></summary>'
                         + (f'<p>{_esc(s["overview_en"] if tr.en else s["overview_ar"] or "")}</p>' if (s["overview_en"] if tr.en else s["overview_ar"]) else "") + ep_html + "</details>")
        seas = f'<section id="seasons"><h2>{_esc(tr("دليل المواسم والحلقات", "Season & Episode Breakdown"))}</h2>{"".join(items)}</section>'
    # التقييم: القيمة والعدد من TMDB كما هما، بلا آراء نقّاد مختلَقة
    rate_html = ""
    if row["rating"]:
        votes = f' — {row["votes"]:,} {tr("تقييم", "votes")}' if row["votes"] else ""
        rate_html = (f'<section class="rating" id="rating"><h2>{_esc(tr("تقييم وآراء النقاد", "Critical Reception & Ratings"))}</h2>'
                     f'<p>{_esc(tr(f"تقييم {kind_ar} {title} لدى المشاهدين {row['rating']:g} من 10", f"{title} is rated {row['rating']:g} out of 10 by viewers"))}{_esc(votes)}.</p></section>')
    # الصور
    pics = ""
    if poster or backdrop:
        pics = f'<section class="pics"><h2>{_esc(tr(f"صور {kind_ar} {title}", f"{title} images"))}</h2><div class="pics-row">'
        if backdrop:
            pics += f'<img src="{_esc(backdrop)}" alt="{_esc(tr(f"مشهد من {kind_ar} {title}", f"Scene from {title}"))}" width="780" height="439" loading=lazy decoding=async>'
        pics += "</div></section>"
    # المشابه
    sim = _similar(con, row, tr, st)
    sim_html = f'<section><h2>{_esc(tr("قد يعجبك أيضًا", "You may also like"))}</h2>{_grid(sim, tr)}</section>' if sim else ""
    # الأسئلة الشائعة (بإجاباتٍ معروضة فعلًا)
    faq = []
    if ov:
        faq.append((tr(f"ما قصة {kind_ar} {title}؟", f"What is {title} about?"), ov[:300]))
    if seasons:
        so_far = airing and airing["live"]
        faq.append((tr(f"كم عدد مواسم وحلقات {title}؟", f"How many seasons and episodes does {title} have?"),
                    tr(f"{tr.count(n_seasons, 'seasons')} و{eps_label(n_eps)}" + (" حتى الآن، والمسلسل ما زال يُعرض وتُضاف حلقاته تباعًا." if so_far else "."),
                       f"{tr.count(n_seasons, 'seasons')} and {eps_label(n_eps)}" + (" so far; the series is still airing and episodes are being added." if so_far else "."))))
    if airing:
        faq.append((tr(f"هل ما زال {title} يُعرض؟ وهل سيكون له جزء ثانٍ؟", f"Is {title} still airing, and will there be another season?"), airing["faq_a"]))
    if cast:
        faq.append((tr(f"من أبطال {title}؟", f"Who stars in {title}?"), tr("، ", ", ").join(_pname(p, tr) for p in cast[:6]) + "."))
    if director:
        faq.append((tr(f"من {'مخرج' if director['role'] == 'director' else 'مبتكر'} {title}؟", f"Who is the {director['role']} of {title}?"), _pname(director, tr) + "."))
    if row["year"]:
        faq.append((tr(f"ما سنة إنتاج {title}؟", f"When was {title} released?"), str(row["year"]) + "."))
    if srv_names:
        faq.append((tr(f"أين أشاهد {title}؟", f"Where can I watch {title}?"), tr(f"متوفر عبر اشتراكات {tr.join(srv_names)} من سمارت سوق.", f"Available on Smart Souq's {tr.join(srv_names)} subscriptions.")))
    faq_html = (f'<section class="faq" id="faq"><h2>{_esc(tr("أسئلة شائعة", "Frequently Asked Questions (FAQ)"))}</h2>' + "".join(f"<details><summary>{_esc(q)}</summary><p>{_esc(a)}</p></details>" for q, a in faq) + "</section>") if len(faq) >= 2 else ""
    # JSON-LD
    canonical = SITE + _path(row, tr.code)
    ld = {"@context": "https://schema.org", "@type": "Movie" if typ == "movie" else "TVSeries", "name": title, "url": canonical, "inLanguage": tr.code}
    if row["original_title"]:
        ld["alternateName"] = row["original_title"]
    if poster:
        ld["image"] = poster
    if ov:
        ld["description"] = ov
    if row["release_date"]:
        ld["datePublished"] = row["release_date"]
    if genres:
        ld["genre"] = [_tname(g, tr) for g in genres]
    if director:
        ld["director" if director["role"] == "director" else "creator"] = {"@type": "Person", "name": _pname(director, tr), "url": SITE + _person_path(director["role"], director["slug"], tr.code)}
    if cast:
        ld["actor"] = [{"@type": "Person", "name": _pname(p, tr), "url": SITE + _person_path(p["role"], p["slug"], tr.code)} for p in cast[:12]]
    if writers:
        ld["author"] = [{"@type": "Person", "name": _pname(p, tr), "url": SITE + _person_path(p["role"], p["slug"], tr.code)} for p in writers[:8]]
    if companies:
        ld["productionCompany"] = [{"@type": "Organization", "name": c["name"], "url": SITE + _company_path(c["slug"], tr.code)} for c in companies]
    if row["rating"] and row["votes"]:
        ld["aggregateRating"] = {"@type": "AggregateRating", "ratingValue": row["rating"], "bestRating": 10, "ratingCount": row["votes"]}
    if typ == "series" and n_official:            # في البيانات المهيكلة الرسمي وحده؛ المدرج لا يُقدَّم عددًا رسميًّا
        ld["numberOfSeasons"] = n_seasons
        ld["numberOfEpisodes"] = n_official
    if guide_rating:
        ld["contentRating"] = guide_rating
    if typ == "series" and row["status"] in ("Ended", "Canceled") and row["last_air_date"]:
        ld["endDate"] = row["last_air_date"]                 # المنتهي وحده: لا endDate لما ما زال يُعرض
    if countries:
        ld["countryOfOrigin"] = [{"@type": "Country", "name": _tname(c, tr)} for c in countries]
    if row["runtime"] and typ == "movie":
        ld["duration"] = f"PT{row['runtime']}M"
    if row["trailer_yt"]:
        ld["trailer"] = {"@type": "VideoObject", "name": tr(f"إعلان {title}", f"{title} trailer"), "embedUrl": f"https://www.youtube.com/embed/{row['trailer_yt']}",
                         "thumbnailUrl": f"https://i.ytimg.com/vi/{row['trailer_yt']}/hqdefault.jpg", "uploadDate": row["release_date"] or f"{row['year']}-01-01" if (row["release_date"] or row["year"]) else None}
        ld["trailer"] = {k: v for k, v in ld["trailer"].items() if v}
    lds = [crumb_ld, ld]
    if faq_html:
        lds.append({"@context": "https://schema.org", "@type": "FAQPage", "inLanguage": tr.code, "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]})
    trailer_html = (f'<section class="trailer"><h2>{_esc(tr("الإعلان", "Trailer"))}</h2><div class="yt"><iframe loading="lazy" src="https://www.youtube-nocookie.com/embed/{_esc(row["trailer_yt"])}" '
                    f'title="{_esc(tr(f"إعلان {title}", f"{title} trailer"))}" allowfullscreen></iframe></div></section>') if row["trailer_yt"] else ""
    ov_ar, ov_en = _override(con, "content", row["id"], "ar"), _override(con, "content", row["id"], "en")
    ovr = ov_en if tr.en else ov_ar
    if ovr.get("seo_title"):
        page_title = ovr["seo_title"]
    if ovr.get("meta_desc"):
        desc = ovr["meta_desc"][:160]
    if ovr.get("intro"):
        body_intro = f'<p class="intro" dir="auto">{_esc(ovr["intro"])}</p>'
    else:
        body_intro = ""
    like_bar, foryou_html, like_js = _like_widget(con, row, tr)
    ok_ar, ok_en, live = index_flags(con, row, st)     # قبل المرحلة 4: الأهلية؛ بعدها: المعتمد المستحقّ وحده (والباقي noindex بلا alternate)
    if ov_ar.get("index_flag") == 0:
        ok_ar = False                                  # المدير أخرج هذه اللغة من الفهرسة: noindex ولا alternate
    if ov_en.get("index_flag") == 0:
        ok_en = False
    alts = [("ar", SITE + _path(row, "ar")), ("en", SITE + _path(row, "en")), ("x-default", SITE + _path(row, "ar"))] if ok_ar and ok_en else []
    noindex = not (live and (ok_en if tr.en else ok_ar))
    body = (_header(tr, hubs[0]["key"] if hubs else "") + f'<main class="wrap">{crumb_html}<div class="tools">{_switch(tr, _path(row, "en" if not tr.en else "ar"))}</div>'
            + body_intro + head + air_html + like_bar + f'<div class="cols"><div class="main">{story}{guide_html}{ppl}{seas}{rate_html}{trailer_html}{pics}{faq_html}{foryou_html}{sim_html}</div><aside>{avail_html}</aside></div></main>' + _footer(tr) + like_js)
    return "page", {"html": _doc(tr, page_title, desc, canonical, alts, body, lds, og_image=backdrop or poster, og_type="video.movie" if typ == "movie" else "video.tv_show",
                                 noindex=noindex), "title": page_title, "desc": desc, "canonical": canonical, "alts": alts, "index_ar": ok_ar, "index_en": ok_en,
                   "noindex": noindex, "live": live, "why": (indexable(row, "ar", st)[1], indexable(row, "en", st)[1]), "row": row}


# ================= الشخص =================
def _paginate(rows, page, st):
    size = max(1, int(st.get("page_size", 60)))
    pages = max(1, (len(rows) + size - 1) // size)
    if page < 1 or page > pages:
        return None, pages
    return rows[(page - 1) * size: page * size], pages


def _page_links(path_of, tr, page, pages):
    """rel=prev/next في الرأس، وروابط الصفحات في الجسم."""
    head = (f'<link rel="prev" href="{_esc(SITE + path_of(tr.code, page - 1))}">' if page > 1 else "") + (f'<link rel="next" href="{_esc(SITE + path_of(tr.code, page + 1))}">' if page < pages else "")
    nav = ""
    if pages > 1:
        nav = '<nav class="pages">' + "".join(f'<a href="{_esc(path_of(tr.code, n))}"{" aria-current=page" if n == page else ""}>{n}</a>' for n in range(1, pages + 1)) + "</nav>"
    return head, nav


def render_person(con, data_dir, role_path, slug, tr, st, page=1):
    """صفحة الشخص: كل أعماله (بأدواره: تمثيلًا وإخراجًا وكتابة) من content_person — لا نصوصًا؛ مرقّمة الصفحات؛ noindex أثناء المراجعة؛
    ولا تُعدّ ذات محتوى (فهرسة) تحت person_min_works. المسار بحسب الدور المطلوب (actors · directors · writers) ويجب أن يحمله الشخص."""
    _services.data_dir = data_dir
    p = con.execute("SELECT * FROM person WHERE slug=?", (slug,)).fetchone()
    if not p or role_path not in PATH_ROLES:
        return None
    roles_here = PATH_ROLES[role_path]
    rows = con.execute("SELECT c.*, cp.role, cp.character FROM content_person cp JOIN content c ON c.id=cp.content_id WHERE cp.person_id=? AND c.merged_into IS NULL AND c.available=1 "
                       "ORDER BY COALESCE(c.year,0) DESC, c.id", (p["id"],)).fetchall()
    if not any(w["role"] in roles_here for w in rows):
        return None                                  # ليس له هذا الدور: المسار الصحيح لدوره هو الذي يُربط به
    role = next(w["role"] for w in rows if w["role"] in roles_here)
    seen, works = set(), []
    for w in rows:                                   # العمل مرةً واحدة ولو تعدّدت أدواره فيه
        if w["id"] not in seen:
            seen.add(w["id"]); works.append(w)
    roles_of = {}
    for w in rows:
        roles_of.setdefault(w["id"], []).append(w["role"])
    page_rows, pages = _paginate(works, page, st)
    if page_rows is None:
        return None
    name = _pname(p, tr)
    movies = [w for w in works if w["type"] == "movie"]
    series = [w for w in works if w["type"] == "series"]
    path_of = lambda lang, n: _person_path(role, slug, lang, n)   # noqa: E731
    page_title = f"{name} | " + tr("الأفلام والمسلسلات", "Movies & Series") + (tr(f" — صفحة {page}", f" — page {page}") if page > 1 else "")
    desc = tr(f"أعمال {name}: {tr.count(len(movies), 'movie')} و{tr.count(len(series), 'series')} متوفرة في اشتراكات سمارت سوق.",
              f"{name}: {tr.count(len(movies), 'movie')} and {tr.count(len(series), 'series')} available on Smart Souq subscriptions.")
    crumb_html, crumb_ld = _crumbs([(tr("الرئيسية", "Home"), "/"), (tr("المحتوى", "Content"), tr.path), (PATH_NAMES[role_path][tr.en], ""), (name, "")])
    photo = _img(p["photo"], "w342")
    bio = (p["bio_en"] if tr.en else p["bio_ar"]) or ""
    role_line = tr("، ", ", ").join(sorted({ROLE_NAMES[r][tr.en] for w in rows for r in [w["role"]] if r in ROLE_NAMES}))
    head_extra, nav = _page_links(path_of, tr, page, pages)
    sections = ""
    for label, typ in ((tr("الأفلام", "Movies"), "movie"), (tr("المسلسلات", "Series"), "series")):
        rs = [w for w in page_rows if w["type"] == typ]
        if rs:
            sections += f'<section><h3>{_esc(label)}</h3>{_grid(rs, tr)}</section>'
    body = (_header(tr) + f'<main class="wrap">{crumb_html}<div class="tools">{_switch(tr, path_of("en" if not tr.en else "ar", page))}</div>'
            f'<section class="hero person-hero"><div class="wrap hd"><div class="pos">{f"<img src={chr(34)}{_esc(photo)}{chr(34)} alt={chr(34)}{_esc(name)}{chr(34)} width=342 height=513>" if photo else f"<span class=ph>{_esc(P._initials(name))}</span>"}</div>'
            f'<div class="meta"><h1 dir="auto">{_esc(name)}</h1>' + (f'<p class="orig">{_esc(p["original_name"])}</p>' if p["original_name"] and p["original_name"] != name else "")
            + (f'<p class="chips"><span class="chip">{_esc(role_line)}</span></p>' if role_line else "")
            + (f'<p dir="auto">{_esc(bio)}</p>' if bio else "") + "</div></div></section>"
            + f'<h2>{_esc(tr(f"أعمال {name}", f"{name} works"))} <small>{_esc(tr.count(len(works), "work") if "work" in P.N_AR else str(len(works)))}</small></h2>' + sections + nav
            + "</main>" + _footer(tr))
    ld = {"@context": "https://schema.org", "@type": "Person", "name": name, "url": SITE + _person_path(role, slug, tr.code)}
    if photo:
        ld["image"] = photo
    if bio:
        ld["description"] = bio
    if role_line:
        ld["jobTitle"] = role_line
    canonical = SITE + path_of(tr.code, page)
    ok = len(works) >= int(st.get("person_min_works", 2)) or bool(bio and photo)
    alts = [("ar", SITE + path_of("ar", page)), ("en", SITE + path_of("en", page)), ("x-default", SITE + path_of("ar", page))] if ok else []
    return "page", {"html": _doc(tr, page_title, desc, canonical, alts, body, [crumb_ld, ld], og_image=photo, og_type="profile", noindex=True, extra_head=head_extra),
                    "title": page_title, "desc": desc, "canonical": canonical, "alts": alts, "index_ar": ok, "index_en": ok, "why": ("ok" if ok else "few works",) * 2,
                    "pages": pages, "works": len(works)}


def render_company(con, data_dir, slug, tr, st, page=1):
    """صفحة الشركة المنتجة (استوديو/شبكة) بأعمالها من content_company — Organization؛ لا تُخلط بسيرفرات الاشتراك."""
    _services.data_dir = data_dir
    co = con.execute("SELECT * FROM company WHERE slug=?", (slug,)).fetchone()
    if not co:
        return None
    works = con.execute("SELECT DISTINCT c.* FROM content_company cc JOIN content c ON c.id=cc.content_id WHERE cc.company_id=? AND c.merged_into IS NULL AND c.available=1 "
                        "ORDER BY COALESCE(c.year,0) DESC, c.id", (co["id"],)).fetchall()
    page_rows, pages = _paginate(works, page, st)
    if page_rows is None:
        return None
    name = co["name"]
    path_of = lambda lang, n: _company_path(slug, lang, n)   # noqa: E731
    kind = tr("شبكة", "Network") if co["kind"] == "network" else tr("شركة إنتاج", "Production company")
    page_title = f"{name} | " + tr("أعمال الشركة", "Productions") + (tr(f" — صفحة {page}", f" — page {page}") if page > 1 else "")
    movies, series = [w for w in works if w["type"] == "movie"], [w for w in works if w["type"] == "series"]
    desc = tr(f"أعمال {name} ({kind}): {tr.count(len(movies), 'movie')} و{tr.count(len(series), 'series')} متوفرة في اشتراكات سمارت سوق.",
              f"{name} ({kind}): {tr.count(len(movies), 'movie')} and {tr.count(len(series), 'series')} available on Smart Souq subscriptions.")
    crumb_html, crumb_ld = _crumbs([(tr("الرئيسية", "Home"), "/"), (tr("المحتوى", "Content"), tr.path), (tr("شركات الإنتاج", "Production companies"), ""), (name, "")])
    logo = _img(co["logo"], "w185")
    head_extra, nav = _page_links(path_of, tr, page, pages)
    sections = ""
    for label, typ in ((tr("الأفلام", "Movies"), "movie"), (tr("المسلسلات", "Series"), "series")):
        rs = [w for w in page_rows if w["type"] == typ]
        if rs:
            sections += f'<section><h3>{_esc(label)}</h3>{_grid(rs, tr)}</section>'
    body = (_header(tr) + f'<main class="wrap">{crumb_html}<div class="tools">{_switch(tr, path_of("en" if not tr.en else "ar", page))}</div>'
            f'<section class="hero person-hero"><div class="wrap hd"><div class="pos logo">{f"<img src={chr(34)}{_esc(logo)}{chr(34)} alt={chr(34)}{_esc(name)}{chr(34)} width=185 height=185>" if logo else f"<span class=ph>{_esc(P._initials(name))}</span>"}</div>'
            f'<div class="meta"><h1 dir="auto">{_esc(name)}</h1><p class="chips"><span class="chip">{_esc(kind)}</span>'
            + (f'<span class="chip">{_esc(co["country"])}</span>' if co["country"] else "") + "</p></div></div></section>"
            + f'<h2>{_esc(tr(f"أعمال {name}", f"{name} productions"))}</h2>' + sections + nav + "</main>" + _footer(tr))
    ld = {"@context": "https://schema.org", "@type": "Organization", "name": name, "url": SITE + _company_path(slug, tr.code)}
    if logo:
        ld["logo"] = logo
    canonical = SITE + path_of(tr.code, page)
    ok = len(works) >= int(st.get("company_min_works", 2))
    alts = [("ar", SITE + path_of("ar", page)), ("en", SITE + path_of("en", page)), ("x-default", SITE + path_of("ar", page))] if ok else []
    return "page", {"html": _doc(tr, page_title, desc, canonical, alts, body, [crumb_ld, ld], og_image=logo, noindex=True, extra_head=head_extra),
                    "title": page_title, "desc": desc, "canonical": canonical, "alts": alts, "index_ar": ok, "index_en": ok, "why": ("ok" if ok else "few works",) * 2,
                    "pages": pages, "works": len(works)}


# ================= الهب =================
def _hub_query(con, hub, section, genre=None, year=None):
    """أعمال الهب (عضوية مؤكّدة) بقسمه ← (SQL, args) بترتيبٍ ثابت: آخر إضافة ثم المعرّف."""
    sql = ("SELECT c.* FROM content c JOIN content_taxonomy ct ON ct.content_id=c.id JOIN taxonomy t ON t.id=ct.taxonomy_id "
           "WHERE t.kind='hub' AND t.key=? AND ct.source IN ('tmdb','manual') AND c.merged_into IS NULL AND c.available=1")
    args = [hub]
    if section == "series":
        sql += " AND c.type='series'"
    elif section == "movies":
        sql += " AND c.type='movie'"
    elif section == "ongoing":
        sql += " AND c.type='series' AND c.status IN ('Returning Series','In Production')"
    elif section == "completed":
        sql += " AND c.type='series' AND c.status IN ('Ended','Canceled')"
    if genre:
        sql += " AND c.id IN (SELECT ct2.content_id FROM content_taxonomy ct2 JOIN taxonomy t2 ON t2.id=ct2.taxonomy_id WHERE t2.kind='genre' AND t2.slug=? AND ct2.source IN ('tmdb','manual'))"
        args.append(genre)
    if year:
        sql += " AND c.year=?"
        args.append(int(year))
    return sql, args


def _hub_rows(con, hub, section, genre, year, page, size):
    sql, args = _hub_query(con, hub, section, genre, year)
    total = con.execute(f"SELECT COUNT(*) FROM ({sql})", args).fetchone()[0]
    rows = con.execute(sql + " ORDER BY COALESCE(c.last_seen, c.first_seen, 0) DESC, c.id DESC LIMIT ? OFFSET ?", (*args, size, (page - 1) * size)).fetchall()
    return total, rows


def render_hub(con, data_dir, hub, section, sub, page, tr, st):
    """‏/content/<hub>/[section/][genres/<g>/|year/<y>/][page/<n>/]"""
    _services.data_dir = data_dir
    if hub not in HUBS:
        return None
    t = con.execute("SELECT * FROM taxonomy WHERE kind='hub' AND key=?", (hub,)).fetchone()
    size, max_pages, min_items = int(st.get("page_size", 60)), int(st.get("list_max_pages", 50)), int(st.get("list_min_items", 12))
    genre = sub[1] if sub and sub[0] == "genres" else None
    year = sub[1] if sub and sub[0] == "year" else None
    if page < 1 or page > max_pages:
        return None
    hub_name = HUB_NAMES[hub][tr.en]
    base_path = f"/content/{hub}/" + (f"{section}/" if section else "") + (f"genres/{genre}/" if genre else f"year/{year}/" if year else "")
    me = lambda lang, pg=1: (seo_db.lang_prefix(lang) + base_path + (f"page/{pg}/" if pg > 1 else ""))   # noqa: E731
    gt = con.execute("SELECT * FROM taxonomy WHERE kind='genre' AND slug=?", (genre,)).fetchone() if genre else None
    if genre and not gt:
        return None
    listing = bool(section or genre or year or page > 1)
    total, rows = _hub_rows(con, hub, section, genre, year, page, size)
    if listing and not rows:
        return None
    sec_name = SECTION_NAMES[section][tr.en] if section else ""
    qual = (f"{_tname(gt, tr)}" if gt else f"{year}" if year else "")
    h1 = hub_name if not listing else " · ".join(x for x in (hub_name, sec_name, qual) if x)
    page_title = h1 + (tr(f" — صفحة {page}", f" — page {page}") if page > 1 else "") + " | " + tr("سمارت سوق", "Smart Souq")
    intro = ((t["intro_en"] if tr.en else t["intro_ar"]) if t else "") or HUB_INTRO[hub][tr.en]
    desc = (tr(f"{h1}: {tr.count(total, 'series' if section in ('series', 'ongoing', 'completed') else 'movie' if section == 'movies' else 'results')} متوفرة في اشتراكات سمارت سوق، بقصة كل عمل وأبطاله ومواسمه.",
               f"{h1}: {tr.count(total, 'series' if section in ('series', 'ongoing', 'completed') else 'movie' if section == 'movies' else 'results')} available on Smart Souq subscriptions, with story, cast and seasons.")
            if listing else intro[:160])
    crumbs = [(tr("الرئيسية", "Home"), "/"), (tr("المحتوى", "Content"), tr.path), (hub_name, _hub_path(hub, "", tr.code) if listing else "")]
    if section:
        crumbs.append((sec_name, _hub_path(hub, section, tr.code) if (genre or year or page > 1) else ""))
    if qual:
        crumbs.append((qual, me(tr.code) if page > 1 else ""))
    if page > 1:
        crumbs.append((tr(f"صفحة {page}", f"Page {page}"), ""))
    crumb_html, crumb_ld = _crumbs(crumbs)
    body = _header(tr, hub) + f'<main class="wrap">{crumb_html}<div class="tools">{_switch(tr, me("en" if not tr.en else "ar", page))}</div><h1>{_esc(h1)}</h1>'
    if not listing:
        body += f'<p class="intro" dir="auto">{_esc(intro)}</p>'
        for sec in HUB_SECTIONS:
            n, rs = _hub_rows(con, hub, sec, None, None, 1, 12)
            if rs:
                head = (tr("أحدث ", "Latest ") + SECTION_NAMES[sec][tr.en]) if sec in ("series", "movies") else \
                    tr("المسلسلات " + SECTION_NAMES[sec][0], SECTION_NAMES[sec][1] + " series")
                body += (f'<section><h2><a href="{_esc(_hub_path(hub, sec, tr.code))}">{_esc(head)}</a> <small>{n:,}</small></h2>{_grid(rs, tr)}'
                         + (f'<p class="more"><a href="{_esc(_hub_path(hub, sec, tr.code))}">{_esc(tr("عرض الكل", "View all"))}</a></p>' if n > 12 else "") + "</section>")
        gs = con.execute("SELECT t.*, COUNT(*) n FROM taxonomy t JOIN content_taxonomy ct ON ct.taxonomy_id=t.id JOIN content c ON c.id=ct.content_id WHERE t.kind='genre' AND ct.source IN ('tmdb','manual') "
                         "AND c.merged_into IS NULL AND c.available=1 AND c.id IN (SELECT content_id FROM content_taxonomy ct3 JOIN taxonomy t3 ON t3.id=ct3.taxonomy_id WHERE t3.kind='hub' AND t3.key=? AND ct3.source IN ('tmdb','manual')) "
                         "GROUP BY t.id HAVING n>=? ORDER BY n DESC LIMIT 20", (hub, min_items)).fetchall()
        if gs:
            body += f'<section><h2>{_esc(tr("حسب النوع", "By genre"))}</h2><p class="chips">' + "".join(f'<a class="chip" href="{_esc(_hub_path(hub, "genres/" + g["slug"], tr.code))}">{_esc(_tname(g, tr))} <small>{g["n"]:,}</small></a>' for g in gs) + "</p></section>"
        ys = con.execute("SELECT c.year, COUNT(*) n FROM content c JOIN content_taxonomy ct ON ct.content_id=c.id JOIN taxonomy t ON t.id=ct.taxonomy_id WHERE t.kind='hub' AND t.key=? AND ct.source IN ('tmdb','manual') "
                         "AND c.merged_into IS NULL AND c.available=1 AND c.year IS NOT NULL GROUP BY c.year HAVING n>=? ORDER BY c.year DESC LIMIT 30", (hub, min_items)).fetchall()
        if ys:
            body += f'<section><h2>{_esc(tr("حسب السنة", "By year"))}</h2><p class="chips">' + "".join(f'<a class="chip" href="{_esc(_hub_path(hub, "year/%d" % y["year"], tr.code))}">{y["year"]} <small>{y["n"]:,}</small></a>' for y in ys) + "</p></section>"
        for role, label in (("actor", tr("أبرز الممثلين", "Top cast")), ("director", tr("المخرجون", "Directors"))):
            ps = con.execute("SELECT p.*, cp.role, NULL character, COUNT(*) n FROM person p JOIN content_person cp ON cp.person_id=p.id JOIN content c ON c.id=cp.content_id "
                             "WHERE cp.role IN (?, ?) AND c.merged_into IS NULL AND c.available=1 AND c.id IN (SELECT content_id FROM content_taxonomy ct3 JOIN taxonomy t3 ON t3.id=ct3.taxonomy_id WHERE t3.kind='hub' AND t3.key=? AND ct3.source IN ('tmdb','manual')) "
                             "GROUP BY p.id ORDER BY n DESC, p.name LIMIT 12", (role, "voice" if role == "actor" else "creator", hub)).fetchall()
            if ps:
                body += f'<section><h2>{_esc(label)}</h2><div class="people">{"".join(_person_chip(p, tr) for p in ps)}</div></section>'
        if hub == "anime":
            sts = con.execute("SELECT t.*, COUNT(*) n FROM taxonomy t JOIN content_taxonomy ct ON ct.taxonomy_id=t.id JOIN content c ON c.id=ct.content_id WHERE t.kind='studio' AND c.merged_into IS NULL AND c.available=1 GROUP BY t.id HAVING n>=3 ORDER BY n DESC LIMIT 20").fetchall()
            if sts:
                body += f'<section><h2>{_esc(tr("الاستوديوهات", "Studios"))}</h2><p class="chips">' + "".join(f'<span class="chip">{_esc(_tname(s, tr))} <small>{s["n"]:,}</small></span>' for s in sts) + "</p></section>"
    else:
        body += _grid(rows, tr)
        pages = min(max_pages, max(1, -(-total // size)))
        if pages > 1:
            body += '<nav class="pager">' + (f'<a href="{_esc(me(tr.code, page - 1))}" rel="prev">{_esc(tr("السابق", "Previous"))}</a>' if page > 1 else "") \
                + f'<span>{page} / {pages}</span>' + (f'<a href="{_esc(me(tr.code, page + 1))}" rel="next">{_esc(tr("التالي", "Next"))}</a>' if page < pages else "") + "</nav>"
    body += "</main>" + _footer(tr)
    canonical = SITE + me(tr.code, page)
    ok = total >= min_items
    ia, ie, live = extra_flags(con, st, me("ar", page), ok, ok)
    alts = [("ar", SITE + me("ar", page)), ("en", SITE + me("en", page)), ("x-default", SITE + me("ar", page))] if ia and ie else []
    noindex = not (live and (ie if tr.en else ia))
    ld = {"@context": "https://schema.org", "@type": "CollectionPage", "name": h1, "url": canonical, "description": desc}
    if rows or not listing:
        lst = rows if listing else _hub_rows(con, hub, "", None, None, 1, 12)[1]
        ld["mainEntity"] = {"@type": "ItemList", "numberOfItems": total, "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "url": SITE + _path(r, tr.code), "name": _title(r, tr)} for i, r in enumerate(lst)]}
    return "page", {"html": _doc(tr, page_title, desc, canonical, alts, body, [crumb_ld, ld], noindex=noindex), "noindex": noindex, "title": page_title, "desc": desc,
                    "canonical": canonical, "alts": alts, "index_ar": ok, "index_en": ok, "why": ("ok" if ok else f"items < {min_items}",) * 2, "total": total}





def render_tour(con, data_dir, tr, st):
    """‏/content/for-you/ — «محتار ايش تشاهد؟»: جولة بثلاث خطوات (الاهتمامات ← ما شاهده وأعجبه ببحثٍ ذكي يقبل الأخطاء ← مقترحات بتقييمها وسببها).
    صفحةٌ أداة: noindex ولا تدخل الخريطة؛ والحالة في جهاز الزائر فقط."""
    chips = seo_reco.interests(data_dir, tr.code)
    L = {"liked": tr("أعجبني", "Like"), "seen": tr("شاهدته", "Watched"), "none": tr("لا اقتراحات مناسبة بعد — أضِف أعمالًا شاهدتها أو أعجبتك.", "No fitting picks yet — add titles you watched or liked."),
         "pick": tr("الأشهر في اهتماماتك — حدّد ما شاهدته", "Popular in your interests — mark what you watched"), "noresult": tr("لا نتائج", "No results"),
         "searching": tr("يبحث…", "Searching…")}
    ages = [{"v": 0, "n": tr("بلا قيد", "Any")}] + [{"v": a, "n": f"{a}+ · " + tr(*seo_guide.AGE_NAMES[a])} for a in (6, 10, 13, 16)]
    L["agenote"] = tr("يُعرض ما له «دليل أهل» فقط؛ وما لم يُصنَّف بعد مُستبعد.", "Only titles with a parents guide are shown; unrated titles are excluded.")
    cfg = json.dumps({"lang": tr.code, "chips": chips, "L": L, "ages": ages}, ensure_ascii=False).replace("</", "<\\/")
    title = tr("محتار ايش تشاهد؟", "Not sure what to watch?")
    body = (_header(tr) + f'<main class="wrap tour"><h1>{_esc(title)}</h1><p class="lead">{_esc(tr("جولة سريعة: اختر اهتماماتك وما شاهدته، ونقترح عليك ما يناسبك.", "A quick tour: pick your interests and what you watched, and we will suggest what fits."))}</p>'
            f'<ol class="tsteps" id="tDots"><li class="on">1 · {_esc(tr("اهتماماتك", "Interests"))}</li><li>2 · {_esc(tr("ما شاهدته", "What you watched"))}</li><li>3 · {_esc(tr("مقترحاتك", "Your picks"))}</li></ol>'
            f'<section id="s1"><div class="tbtns top"><button type="button" class="tbtn go" id="to2">{_esc(tr("التالي", "Next"))} ←</button><button type="button" class="tbtn" id="tSkip">{_esc(tr("تخطَّ وأرني الأشهر", "Skip — show popular"))}</button></div>'
            f'<h2>{_esc(tr("ماذا تحب أن تشاهد؟", "What do you like?"))}</h2><h3 class="filter-section-title">{_esc(tr("النوع", "Kind"))}</h3><div class="tchips" id="tTypes"></div>'
            f'<h3 class="filter-section-title">{_esc(tr("الأصل (اختر ما يعجبك)", "Origin (pick what you like)"))}</h3><div class="tchips" id="tOrigins"></div>'
            f'<h3 class="filter-section-title">{_esc(tr("التصنيف", "Genre"))}</h3><div class="tchips" id="tChips"></div>'
            f'<h3 class="filter-section-title">{_esc(tr("عمر المشاهد (للعائلة)", "Viewer age (family)"))}</h3><div class="tchips" id="tAges"></div><p class="tmsg" id="tAgeNote"></p></section>'
            f'<section id="s2" hidden><div class="tbtns top"><button type="button" class="tbtn" id="to1">→ {_esc(tr("السابق", "Back"))}</button><button type="button" class="tbtn go" id="to3">{_esc(tr("أظهر المقترحات", "Show my picks"))} ←</button></div>'
            f'<h2>{_esc(tr("أعمالٌ شاهدتها أو أعجبتك", "Titles you watched or liked"))}</h2>'
            f'<input class="tsearch" id="tQ" type="search" autocomplete="off" placeholder="{_esc(tr("ابحث باسم مسلسل أو فيلم (يقبل الأخطاء الإملائية)", "Search a series or movie (typos are fine)"))}">'
            f'<p class="tmsg" id="tMsg"></p><div class="grid" id="tRes"></div><h3 id="tQuickH"></h3><div class="grid" id="tQuick"></div></section>'
            f'<section id="s3" hidden><div class="tbtns top"><button type="button" class="tbtn" id="to2b">→ {_esc(tr("عدّل اختياراتي", "Edit my picks"))}</button><button type="button" class="tbtn" id="tReset">{_esc(tr("ابدأ من جديد", "Start over"))}</button></div>'
            f'<h2>{_esc(tr("قد يعجبك", "You may like"))}</h2><p class="tmsg" id="tWhy"></p><div class="grid" id="tOut"></div></section>'
            f'<p class="meta">{_esc(tr("تُحفظ اختياراتك في جهازك فقط، ولا نخزّن شيئًا عنك.", "Your choices stay on your device only; we store nothing about you."))}</p></main>' + _footer(tr))
    js = r"""(function(){var CFG=__CFG__,L=CFG.L,$=function(i){return document.getElementById(i)};
function rd(k,d){try{var v=JSON.parse(localStorage.getItem(k));return v==null?d:v}catch(e){return d}}
function wr(k,v){try{localStorage.setItem(k,JSON.stringify(v))}catch(e){}}
var st={interests:rd('ssq_interests',[]),types:rd('ssq_types',[]),likes:rd('ssq_likes',[]),seen:rd('ssq_seen',[]),age:rd('ssq_age',0)};
function save(){wr('ssq_interests',st.interests);wr('ssq_types',st.types);wr('ssq_likes',st.likes);wr('ssq_seen',st.seen);wr('ssq_age',st.age)}
function has(a,x){return a.indexOf(x)>-1}function flip(a,x){var i=a.indexOf(x);if(i>-1)a.splice(i,1);else a.unshift(x)}
function step(n){if(window.sq)sq('tour_step',String(n));['s1','s2','s3'].forEach(function(id,i){$(id).hidden=(i+1!==n)});Array.prototype.forEach.call($('tDots').children,function(li,i){li.className=(i+1===n)?'on':''});window.scrollTo(0,0)}
function el(t,c,x){var e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e}
function rate(it){return it.rating?(Math.round(it.rating*10)/10):0}
function card(it,pick){var a=el(pick?'div':'a','card'+(pick?' pick':''));if(!pick)a.href=it.path;var p=el('span','pos');
 if(it.poster){var im=el('img');im.src=it.poster;im.alt=it.title;im.width=342;im.height=513;im.loading='lazy';p.appendChild(im)}
 if(rate(it)){p.appendChild(el('i','rt-badge','\u2605 '+rate(it)))}
 a.appendChild(p);var t=el('b',null,it.title);t.dir='auto';a.appendChild(t);
 var sm=[it.year||'',rate(it)?'\u2605 '+rate(it):''].filter(Boolean).join(' \u00b7 ');if(sm)a.appendChild(el('small',null,sm));
 if(!pick&&it.why){var w=el('small',null,it.why);w.style.display='block';a.appendChild(w)}
 if(!pick)a.addEventListener('click',function(){if(window.sq)sq('reco_click',it.slug)});
 if(!pick&&it.guide){var g=el('small',null,'\ud83d\udc6a '+it.guide);g.style.display='block';a.appendChild(g)}
 if(pick){var k=el('div','pk'),lk=el('button','lk'+(has(st.likes,it.slug)?' on':''),'\ud83d\udc4d '+L.liked),sn=el('button','sn'+(has(st.seen,it.slug)?' on':''),'\u2713 '+L.seen);lk.type=sn.type='button';
  lk.onclick=function(){if(has(st.likes,it.slug)){flip(st.likes,it.slug)}else{if(window.sq)sq('tour_pick','like');st.likes.unshift(it.slug);if(!has(st.seen,it.slug))st.seen.unshift(it.slug)}save();lk.className='lk'+(has(st.likes,it.slug)?' on':'');sn.className='sn'+(has(st.seen,it.slug)?' on':'')};
  sn.onclick=function(){if(has(st.seen,it.slug)){flip(st.seen,it.slug);var i=st.likes.indexOf(it.slug);if(i>-1)st.likes.splice(i,1)}else{if(window.sq)sq('tour_pick','seen');st.seen.unshift(it.slug)}save();sn.className='sn'+(has(st.seen,it.slug)?' on':'');lk.className='lk'+(has(st.likes,it.slug)?' on':'')};
  k.appendChild(lk);k.appendChild(sn);a.appendChild(k)}return a}
function fill(box,items,pick){box.textContent='';items.forEach(function(it){box.appendChild(card(it,pick))})}
function q(extra){return '/api/content/recommend?lang='+CFG.lang+'&interests='+encodeURIComponent(st.interests.join(','))+'&types='+encodeURIComponent(st.types.join(','))+(st.age?'&age='+st.age:'')+extra}
// الخطوة 1
var TY=[['movie',CFG.lang==='en'?'Movies':'\u0623\u0641\u0644\u0627\u0645'],['series',CFG.lang==='en'?'Series':'\u0645\u0633\u0644\u0633\u0644\u0627\u062a']];
TY.forEach(function(t){var b=el('button','tchip filter-chip'+(has(st.types,t[0])?' on':''),t[1]);b.type='button';b.onclick=function(){flip(st.types,t[0]);save();b.className='tchip filter-chip'+(has(st.types,t[0])?' on':'')};$('tTypes').appendChild(b)});
function ageNote(){$('tAgeNote').textContent=st.age?L.agenote:''}
CFG.ages.forEach(function(a){var b=el('button','tchip filter-chip'+(st.age===a.v?' on':''),a.n);b.type='button';b.onclick=function(){st.age=a.v;if(window.sq)sq('tour_age',String(a.v));save();Array.prototype.forEach.call($('tAges').children,function(x,i){x.className='tchip filter-chip'+(CFG.ages[i].v===st.age?' on':'')});ageNote()};$('tAges').appendChild(b)});ageNote();
CFG.chips.forEach(function(c){var b=el('button','tchip filter-chip'+(has(st.interests,c.id)?' on':''),c.name);b.type='button';b.onclick=function(){flip(st.interests,c.id);save();b.className='tchip filter-chip'+(has(st.interests,c.id)?' on':'')};$(c.group==='origin'?'tOrigins':'tChips').appendChild(b)});
// الخطوة 2: بحثٌ ذكي + اقتراحات سريعة
var tm=0;$('tQ').oninput=function(){clearTimeout(tm);var v=this.value.trim();if(v.length<2){$('tRes').textContent='';$('tMsg').textContent='';return}
 $('tMsg').textContent=L.searching;tm=setTimeout(function(){fetch('/api/content/find?lang='+CFG.lang+'&q='+encodeURIComponent(v)).then(function(r){return r.json()}).then(function(d){
  $('tMsg').textContent=(d.items&&d.items.length)?'':L.noresult;fill($('tRes'),d.items||[],true)}).catch(function(){$('tMsg').textContent=''})},250)};
function quick(){$('tQuickH').textContent=L.pick;fetch(q('&n=12&likes=&seen=')).then(function(r){return r.json()}).then(function(d){fill($('tQuick'),d.items||[],true)}).catch(function(){})}
function results(){$('tWhy').textContent='';$('tOut').textContent='';fetch(q('&n=18&likes='+encodeURIComponent(st.likes.slice(0,30).join(','))+'&seen='+encodeURIComponent(st.seen.slice(0,60).join(',')))).then(function(r){return r.json()}).then(function(d){
 if(!d.items||!d.items.length||d.cold&&!st.interests.length&&!st.likes.length){$('tWhy').textContent=L.none;return}fill($('tOut'),d.items,false);if(window.sq)sq('tour_result',String(d.items.length));var w=d.items.filter(function(i){return i.why})[0];$('tWhy').textContent=w?w.why:''}).catch(function(){})}
$('to2').onclick=function(){step(2);quick()};$('tSkip').onclick=function(){step(3);results()};$('to1').onclick=function(){step(1)};$('to3').onclick=function(){step(3);results()};$('to2b').onclick=function(){step(2);quick()};
$('tReset').onclick=function(){st={interests:[],types:[],likes:[],seen:[],age:0};save();location.reload()};
})();""".replace("__CFG__", cfg)
    body += f"<script>{js}</script>"
    canonical = SITE + seo_db.lang_prefix(tr.code) + "/content/for-you/"
    return "page", {"html": _doc(tr, title + " | " + tr("سمارت سوق", "Smart Souq"), tr("جولة سريعة لاقتراح مسلسلات وأفلام تناسبك.", "A quick tour to suggest series and movies that fit you."), canonical, [], body, [], noindex=True),
                    "noindex": True, "title": title, "index_ar": False, "index_en": False}


# ================= المواسم والحلقات (المرحلة 7) =================
def season_ok(season, eps, lang, st):
    """صفحة الموسم: ملخصٌ باللغة + حلقاتٌ بعناوين (سياسة §6) ← (نعم؟، السبب)."""
    ov = (season["overview_en"] if lang == "en" else season["overview_ar"]) or ""
    if len(ov) < int(st.get("index_min_overview", 120)):
        return False, f"season overview_{lang} < {st.get('index_min_overview', 120)}"
    if not eps or not all((e["title_en"] if lang == "en" else (e["title_ar"] or e["title_en"])) for e in eps):
        return False, "episodes without titles"
    return True, "ok"


def episode_ok(ep, lang, st):
    """صفحة الحلقة: لا صفحة إلا بشروط ‏episode_page في الإعدادات (عنوان · ملخص ≥ الحدّ · تاريخ عرض) ← نعم؟"""
    pol = st.get("episode_page") or {}
    title = (ep["title_en"] if lang == "en" else (ep["title_ar"] or ep["title_en"])) or ""
    ov = (ep["overview_en"] if lang == "en" else ep["overview_ar"]) or ""
    if pol.get("title", True) and not title:
        return False
    if len(ov) < int(pol.get("overview_min", 80)):
        return False
    if pol.get("air_date", True) and not ep["air_date"]:
        return False
    return True


def _season_path(row, n, lang="ar", ep=None):
    return seo_db.lang_prefix(lang) + f"/content/series/{row['slug']}/season-{n}/" + (f"episode-{ep}/" if ep else "")


def render_season(con, data_dir, slug, n, ep_no, tr, st):
    """‏/content/series/<slug>/season-<n>/ و…/episode-<e>/ — 404 حين لا تتوفر شروط الصفحة (الحلقة خصوصًا)."""
    _services.data_dir = data_dir
    row = con.execute("SELECT * FROM content WHERE type='series' AND slug=? AND merged_into IS NULL AND available=1", (slug,)).fetchone()
    if not row or n < 1:
        return None
    season = con.execute("SELECT * FROM season WHERE content_id=? AND number=?", (row["id"], n)).fetchone()
    if not season:
        return None
    eps = con.execute("SELECT * FROM episode WHERE content_id=? AND season=? ORDER BY number LIMIT 300", (row["id"], n)).fetchall()
    title = _title(row, tr)
    s_name = tr(f"الموسم {n}", f"Season {n}")
    series_path = _path(row, tr.code)
    if ep_no:
        ep = next((e for e in eps if e["number"] == ep_no), None)
        if not ep or not episode_ok(ep, tr.code, st):
            return None
        et = (ep["title_en"] if tr.en else ep["title_ar"] or ep["title_en"])
        ov = (ep["overview_en"] if tr.en else ep["overview_ar"]) or ""
        h1 = tr(f"{title} — {s_name} الحلقة {ep_no}: {et}", f"{title} — {s_name} Episode {ep_no}: {et}")
        desc = ov[:160]
        me = lambda lang: _season_path(row, n, lang, ep_no)   # noqa: E731
        crumbs = [(tr("الرئيسية", "Home"), "/"), (tr("المحتوى", "Content"), tr.path), (title, series_path),
                  (s_name, _season_path(row, n, tr.code)), (tr(f"الحلقة {ep_no}", f"Episode {ep_no}"), "")]
        prev_n = next((e["number"] for e in reversed(eps) if e["number"] < ep_no and episode_ok(e, tr.code, st)), None)
        next_n = next((e["number"] for e in eps if e["number"] > ep_no and episode_ok(e, tr.code, st)), None)
        still = _img(ep["still"], "w780") if ep["still"] else ""
        crumb_html, crumb_ld = _crumbs(crumbs)
        body = (_header(tr) + f'<main class="wrap">{crumb_html}<div class="tools">{_switch(tr, me("en" if not tr.en else "ar"))}</div><h1>{_esc(h1)}</h1>'
                + (f'<img src="{_esc(still)}" alt="{_esc(tr(f"لقطة من الحلقة {ep_no} من {title}", f"Still from {title} episode {ep_no}"))}" width="780" height="439">' if still else "")
                + f'<p dir="auto">{_esc(ov)}</p><p><small>{_esc(ep["air_date"])}' + (f' · {ep["runtime"]} {_esc(tr("دقيقة", "min"))}' if ep["runtime"] else "") + "</small></p>"
                + '<p class="more">' + (f'<a href="{_esc(_season_path(row, n, tr.code, prev_n))}" rel="prev">{_esc(tr("الحلقة السابقة", "Previous episode"))}</a> ' if prev_n else "")
                + (f'<a href="{_esc(_season_path(row, n, tr.code, next_n))}" rel="next">{_esc(tr("الحلقة التالية", "Next episode"))}</a> ' if next_n else "")
                + f'<a href="{_esc(_season_path(row, n, tr.code))}">{_esc(s_name)}</a> · <a href="{_esc(series_path)}">{_esc(title)}</a></p></main>' + _footer(tr))
        ld = {"@context": "https://schema.org", "@type": "TVEpisode", "name": et, "episodeNumber": ep_no, "description": ov, "datePublished": ep["air_date"],
              "partOfSeason": {"@type": "TVSeason", "seasonNumber": n}, "partOfSeries": {"@type": "TVSeries", "name": title, "url": SITE + series_path}}
        ok_ar, ok_en = episode_ok(ep, "ar", st), episode_ok(ep, "en", st)
        lds, page_title = [crumb_ld, ld], f"{h1} | " + tr("سمارت سوق", "Smart Souq")
    else:
        ok_ar, ok_en = season_ok(season, eps, "ar", st)[0], season_ok(season, eps, "en", st)[0]
        h1 = tr(f"{title} — {s_name}", f"{title} — {s_name}")
        sov = (season["overview_en"] if tr.en else season["overview_ar"]) or ""
        desc = (sov or tr(f"حلقات {s_name} من {title}", f"Episodes of {title} {s_name}"))[:160]
        me = lambda lang: _season_path(row, n, lang)   # noqa: E731
        crumb_html, crumb_ld = _crumbs([(tr("الرئيسية", "Home"), "/"), (tr("المحتوى", "Content"), tr.path), (title, series_path), (s_name, "")])
        lis = []
        for e in eps:
            et = (e["title_en"] if tr.en else e["title_ar"] or e["title_en"]) or ""
            label = f'<span>{e["number"]}</span> {_esc(et)}' + (f' <small>{_esc(e["air_date"])}</small>' if e["air_date"] else "")
            lis.append(f'<li><a href="{_esc(_season_path(row, n, tr.code, e["number"]))}">{label}</a></li>' if episode_ok(e, tr.code, st) else f"<li>{label}</li>")
        body = (_header(tr) + f'<main class="wrap">{crumb_html}<div class="tools">{_switch(tr, me("en" if not tr.en else "ar"))}</div><h1>{_esc(h1)}</h1>'
                + (f'<p dir="auto">{_esc(sov)}</p>' if sov else "") + (f'<ol class=eps>{"".join(lis)}</ol>' if lis else "")
                + f'<p class="more"><a href="{_esc(series_path)}">{_esc(title)}</a></p></main>' + _footer(tr))
        ld = {"@context": "https://schema.org", "@type": "TVSeason", "name": h1, "seasonNumber": n, "numberOfEpisodes": len(eps),
              "partOfSeries": {"@type": "TVSeries", "name": title, "url": SITE + series_path}}
        lds, page_title = [crumb_ld, ld], f"{h1} | " + tr("المواسم والحلقات", "Seasons & Episodes") + " | " + tr("سمارت سوق", "Smart Souq")
    canonical = SITE + me(tr.code)
    ia, ie, live = extra_flags(con, st, me("ar"), ok_ar, ok_en, parent_id=row["id"])
    alts = [("ar", SITE + me("ar")), ("en", SITE + me("en")), ("x-default", SITE + me("ar"))] if ia and ie else []
    noindex = not (live and (ie if tr.en else ia))
    return "page", {"html": _doc(tr, page_title, desc, canonical, alts, body, lds, og_type="video.episode" if ep_no else "video.tv_show", noindex=noindex),
                    "noindex": noindex, "title": page_title, "desc": desc, "canonical": canonical, "alts": alts, "index_ar": ok_ar, "index_en": ok_en}


# ================= قوائم التصنيف العامة (المرحلة 6): النوع · الدولة · اللغة · السنة · الأحدث =================
TAX_KINDS = {"genres": "genre", "countries": "country", "languages": "language"}
TAX_TITLES = {"genres": ("النوع", "Genre"), "countries": ("الدولة", "Country"), "languages": ("اللغة", "Language")}
LATEST_SECTIONS = {"": ("الأحدث", "Latest"), "movies": ("أحدث الأفلام", "Latest movies"), "series": ("أحدث المسلسلات", "Latest series")}


def _tax_where(kind, key, section=""):
    """شرط القائمة العامة (بُعدٌ واحد، لا تركيبات فلاتر) ← (JOIN/WHERE، args)."""
    sql = "FROM content c WHERE c.merged_into IS NULL AND c.available=1"
    args = []
    if kind in TAX_KINDS.values():
        sql += (" AND c.id IN (SELECT ct.content_id FROM content_taxonomy ct JOIN taxonomy t ON t.id=ct.taxonomy_id "
                "WHERE t.kind=? AND t.slug=? AND ct.source IN ('tmdb','manual'))")
        args += [kind, key]
    elif kind == "year":
        sql += " AND c.year=?"
        args.append(int(key))
    if section == "movies":
        sql += " AND c.type='movie'"
    elif section == "series":
        sql += " AND c.type='series'"
    return sql, args


def render_taxonomy(con, data_dir, facet, slug, section, page, tr, st):
    """‏/content/<genres|countries|languages>/<slug>/ · /content/year/<yyyy>/ · /content/latest/[movies|series/] — [page/<n>/]
    بُعدٌ واحد فقط؛ الفهرسة بعدد العناصر (list_min_items) وحدّ الصفحات (list_max_pages) من الإعدادات."""
    _services.data_dir = data_dir
    size, max_pages, min_items = int(st.get("page_size", 60)), int(st.get("list_max_pages", 50)), int(st.get("list_min_items", 12))
    if page < 1 or page > max_pages:
        return None
    if facet in TAX_KINDS:
        kind = TAX_KINDS[facet]
        t = con.execute("SELECT * FROM taxonomy WHERE kind=? AND slug=?", (kind, slug)).fetchone()
        if not t:
            return None
        name, base = _tname(t, tr), f"/content/{facet}/{slug}/"
        h1 = {"genres": tr(f"أعمال {name}", f"{name} series & movies"),
              "countries": tr(f"أعمال {name}", f"Series & movies from {name}"),
              "languages": tr(f"أعمال بلغة {name}", f"{name}-language series & movies")}[facet]
    elif facet == "year":
        kind, name, base = "year", str(slug), f"/content/year/{slug}/"
        if not str(slug).isdigit() or not 1900 <= int(slug) <= 2100:
            return None
        h1 = tr(f"مسلسلات وأفلام {slug}", f"Series & movies of {slug}")
    else:   # latest
        kind, name, base = "latest", "", "/content/latest/" + (f"{section}/" if section else "")
        h1 = LATEST_SECTIONS[section][tr.en]
    where, args = _tax_where(kind, slug if kind != "latest" else "", section if facet in ("latest",) else "")
    total = con.execute(f"SELECT COUNT(*) {where}", args).fetchone()[0]
    if not total:
        return None
    pages = min(max_pages, max(1, -(-total // size)))
    if page > pages:
        return None
    rows = con.execute(f"SELECT c.* {where} ORDER BY COALESCE(c.last_seen, c.first_seen, 0) DESC, c.id DESC LIMIT ? OFFSET ?",
                       (*args, size, (page - 1) * size)).fetchall()
    me = lambda lang, pg=1: seo_db.lang_prefix(lang) + base + (f"page/{pg}/" if pg > 1 else "")   # noqa: E731
    page_title = h1 + (tr(f" — صفحة {page}", f" — page {page}") if page > 1 else "") + " | " + tr("سمارت سوق", "Smart Souq")
    desc = tr(f"{h1}: {total:,} عملًا متوفرًا في اشتراكات سمارت سوق، بقصة كل عمل وأبطاله ومواسمه.",
              f"{h1}: {total:,} titles available on Smart Souq subscriptions, with story, cast and seasons.")[:160]
    crumbs = [(tr("الرئيسية", "Home"), "/"), (tr("المحتوى", "Content"), tr.path)]
    if facet in TAX_KINDS:
        crumbs.append((TAX_TITLES[facet][tr.en], ""))
    crumbs.append((h1, me(tr.code) if page > 1 else ""))
    if page > 1:
        crumbs.append((tr(f"صفحة {page}", f"Page {page}"), ""))
    crumb_html, crumb_ld = _crumbs(crumbs)
    head_links, nav = _page_links(lambda lang, pg: me(lang, pg), tr, page, pages)
    body = (_header(tr) + f'<main class="wrap">{crumb_html}<div class="tools">{_switch(tr, me("en" if not tr.en else "ar", page))}</div>'
            f'<h1>{_esc(h1)}</h1><p class="intro" dir="auto">{_esc(desc)}</p>{_grid(rows, tr)}{nav}</main>' + _footer(tr))
    canonical = SITE + me(tr.code, page)
    ok = total >= min_items
    ia, ie, live = extra_flags(con, st, me("ar", page), ok, ok)
    alts = [("ar", SITE + me("ar", page)), ("en", SITE + me("en", page)), ("x-default", SITE + me("ar", page))] if ia and ie else []
    noindex = not (live and (ie if tr.en else ia))
    ld = {"@context": "https://schema.org", "@type": "CollectionPage", "name": h1, "url": canonical, "description": desc,
          "mainEntity": {"@type": "ItemList", "numberOfItems": total, "itemListElement": [
              {"@type": "ListItem", "position": (page - 1) * size + i + 1, "url": SITE + _path(r, tr.code), "name": _title(r, tr)}
              for i, r in enumerate(rows)]}}
    return "page", {"html": _doc(tr, page_title, desc, canonical, alts, body, [crumb_ld, ld], noindex=noindex, extra_head=head_links),
                    "noindex": noindex, "title": page_title, "desc": desc, "canonical": canonical, "alts": alts, "index_ar": ok, "index_en": ok,
                    "why": ("ok" if ok else f"items < {min_items}",) * 2, "total": total}



# ================= هب المحتوى /content/ (المرحلة 8) =================
def render_content_hub(con, data_dir, tr, st):
    """‏/content/ هبًّا حقيقيًّا (أحدث المحتوى · الهبّات · التصنيفات · السنوات · السيرفرات) بدل التحويل 302 — يعمل فقط حين
    يُفعَّل ‏content_hub في الإعدادات؛ وما دام معطّلًا يبقى سلوكه القديم (302 لأول سيرفر) كما هو."""
    _services.data_dir = data_dir
    min_items = int(st.get("list_min_items", 12))
    h1 = tr("المسلسلات والأفلام في اشتراكات سمارت سوق", "Series & Movies on Smart Souq subscriptions")
    desc = tr("دليل المسلسلات والأفلام المتوفرة في اشتراكات سمارت سوق: أحدث الأعمال، التركي والأنمي، حسب النوع والدولة والسنة، وأين يتوفر كل عمل.",
              "Guide to the series and movies available on Smart Souq subscriptions: latest titles, Turkish and anime, by genre, country and year, and where each one is available.")[:160]
    body = _header(tr)
    crumb_html, crumb_ld = _crumbs([(tr("الرئيسية", "Home"), "/"), (tr("المحتوى", "Content"), "")])
    body += f'<main class="wrap">{crumb_html}<div class="tools">{_switch(tr, seo_db.lang_prefix("en" if not tr.en else "ar") + "/content/")}</div><h1>{_esc(h1)}</h1><p class="intro" dir="auto">{_esc(desc)}</p>'
    for typ, sec, head in (("movie", "movies", tr("أحدث الأفلام", "Latest movies")), ("series", "series", tr("أحدث المسلسلات", "Latest series"))):
        rows = con.execute("SELECT * FROM content WHERE type=? AND merged_into IS NULL AND available=1 ORDER BY COALESCE(last_seen, first_seen, 0) DESC, id DESC LIMIT 12", (typ,)).fetchall()
        if rows:
            body += (f'<section><h2><a href="{_esc(seo_db.lang_prefix(tr.code) + "/content/latest/" + sec + "/")}">{_esc(head)}</a></h2>{_grid(rows, tr)}</section>')
    body += (f'<section><h2>{_esc(tr("أقسام مختارة", "Featured"))}</h2><p class="chips">'
             + "".join(f'<a class="chip" href="{_esc(_hub_path(h, "", tr.code))}">{_esc(HUB_NAMES[h][tr.en])}</a>' for h in HUBS) + "</p></section>")
    for kind, facet, head, limit in (("genre", "genres", tr("حسب النوع", "By genre"), 24), ("country", "countries", tr("حسب الدولة", "By country"), 24),
                                     ("language", "languages", tr("حسب اللغة", "By language"), 16)):
        ts = con.execute("SELECT t.*, COUNT(*) n FROM taxonomy t JOIN content_taxonomy ct ON ct.taxonomy_id=t.id JOIN content c ON c.id=ct.content_id "
                         "WHERE t.kind=? AND ct.source IN ('tmdb','manual') AND c.merged_into IS NULL AND c.available=1 GROUP BY t.id HAVING n>=? ORDER BY n DESC LIMIT ?",
                         (kind, min_items, limit)).fetchall()
        if kind == "country":
            ts = [t for t in ts if t["slug"] != "tr"]          # التركي هبٌّ مستقل (لا صفحتان تتنافسان)
        if ts:
            body += (f'<section><h2>{_esc(head)}</h2><p class="chips">' + "".join(
                f'<a class="chip" href="{_esc(seo_db.lang_prefix(tr.code) + f"/content/{facet}/{t["slug"]}/")}">{_esc(_tname(t, tr))} <small>{t["n"]:,}</small></a>' for t in ts) + "</p></section>")
    ys = con.execute("SELECT year, COUNT(*) n FROM content WHERE merged_into IS NULL AND available=1 AND year IS NOT NULL GROUP BY year HAVING n>=? ORDER BY year DESC LIMIT 25", (min_items,)).fetchall()
    if ys:
        body += (f'<section><h2>{_esc(tr("حسب السنة", "By year"))}</h2><p class="chips">' + "".join(
            f'<a class="chip" href="{_esc(seo_db.lang_prefix(tr.code) + "/content/year/%d/" % y["year"])}">{y["year"]} <small>{y["n"]:,}</small></a>' for y in ys) + "</p></section>")
    srv = [s_ for s_ in C.servers(data_dir)]
    if srv:   # صفحات السيرفرات القائمة تبقى كما هي، ويربط إليها الهب
        body += (f'<section><h2>{_esc(tr("السيرفرات", "Servers"))}</h2><p class="chips">' + "".join(
            f'<a class="chip" href="{_esc(tr.path + "/" + s_["key"])}">{_esc(tr.name(s_))}</a>' for s_ in srv) + "</p></section>")
    body += "</main>" + _footer(tr)
    me = lambda lang: seo_db.lang_prefix(lang) + "/content/"   # noqa: E731
    canonical = SITE + me(tr.code)
    ia, ie, live = extra_flags(con, st, "/content/", True, True)
    alts = [("ar", SITE + me("ar")), ("en", SITE + me("en")), ("x-default", SITE + me("ar"))] if ia and ie else []
    noindex = not (live and (ie if tr.en else ia))
    ld = {"@context": "https://schema.org", "@type": "CollectionPage", "name": h1, "url": canonical, "description": desc}
    return "page", {"html": _doc(tr, h1 + " | " + tr("سمارت سوق", "Smart Souq"), desc, canonical, alts, body, [crumb_ld, ld], noindex=noindex),
                    "noindex": noindex, "title": h1, "desc": desc, "canonical": canonical, "alts": alts, "index_ar": True, "index_en": True}


# ================= التوجيه =================
_RX = re.compile(r"^/content/(?:(movies|series)/([a-z0-9-]+)/|people/(actors|directors|writers)/([a-z0-9-]+)/(?:page/(\d+)/)?|companies/([a-z0-9-]+)/(?:page/(\d+)/)?|"
                 r"(turkish|anime)/(?:(series|movies|ongoing|completed)/)?(?:(genres|year)/([a-z0-9-]+)/)?(?:page/(\d+)/)?)$")


_RX_SEASON = re.compile(r"^/content/series/([a-z0-9-]+)/season-(\d{1,3})/(?:episode-(\d{1,4})/)?$")
_RX_TAX = re.compile(r"^/content/(?:(genres|countries|languages)/([a-z0-9-]+)/|year/(\d{4})/|latest/(?:(movies|series)/)?)(?:page/(\d+)/)?$")


def _served(res):
    """رأس الردّ لصفحةٍ مرسومة: noindex (وسمًا ورأسًا) أو معتمدٌ مستحقّ بلا رأس noindex."""
    if res[1].get("noindex", True):
        return 200, res[1]["html"], {"X-Robots-Tag": "noindex", "Cache-Control": "private, max-age=0"}
    return 200, res[1]["html"], {"Cache-Control": "public, max-age=600"}


def handle(data_dir, path, lang, _info=False, _con=None):
    """← (code, body, headers) أو None إن لم يكن من مسارات الطبقة. وبلا ‏preview: 404 لكل مساراتها (لا شيء عامٌّ بعد).
    ‏_info=True (لفحوص seo_release): يعيد قاموس الصفحة المرسومة (الأهلية index_ar/index_en…) بدل الردّ، أو None إن لم تُرسم.
    ‏_con: اتصالٌ قائم يُستعمل بدل فتح اتصالٍ جديد (فحص دفعة التوسيع داخل معاملةٍ غير مثبّتة يجب أن يرى الصفحات كما ستكون) — ولا يُغلق."""
    pre = seo_db.lang_prefix(lang)
    ar_path = path[len(pre):] if pre else path
    hub_root = ar_path in ("/content", "/content/")
    if not hub_root and ar_path != "/content/latest" and not ar_path.startswith(("/content/movies/", "/content/series/", "/content/people/", "/content/companies/", "/content/genres/", "/content/countries/", "/content/languages/", "/content/year/", "/content/latest/", "/content/for-you/", "/content/turkish", "/content/anime", "/content/countries/turkey")):
        return None
    con = _con or seo_db.connect(data_dir, create=False)
    if con is None:
        return 404, b"", {}
    try:
        _tl.con = con
        st = seo_db.settings(con)
        if hub_root:     # الهب: معطّلٌ ← None فيبقى 302 القديم في xm_lines كما كان
            if not (st.get("content_hub") and st.get("preview")) or lang not in (st.get("languages") or ["ar", "en"]):
                return None
            res = render_content_hub(con, data_dir, P.lang_of(lang), st)
            return res[1] if _info else _served(res)
        if not st.get("preview") or lang not in (st.get("languages") or ["ar", "en"]):
            return 404, b"", {}
        if ar_path.rstrip("/") == "/content/countries/turkey":   # صفحة الدولة لا تنافس الهب: 301 إليه (قرار المالك)
            return 301, b"", {"Location": pre + "/content/turkish/"}
        if not ar_path.endswith("/"):            # الشرطة الأخيرة إلزامية
            return 301, b"", {"Location": path + "/"}
        r = con.execute("SELECT target FROM redirect WHERE path=?", (ar_path,)).fetchone()
        if r:
            return 301, b"", {"Location": pre + r["target"]}
        tr = P.lang_of(lang)
        if ar_path == "/content/for-you/":
            res = render_tour(con, data_dir, tr, st)
            return res[1]["html"] if _info else (200, res[1]["html"], {"X-Robots-Tag": "noindex", "Cache-Control": "private, max-age=0"})
        ms = _RX_SEASON.match(ar_path)
        if ms:
            res = render_season(con, data_dir, ms.group(1), int(ms.group(2)), int(ms.group(3)) if ms.group(3) else 0, tr, st)
            if not res:
                return 404, b"", {}
            return res[1] if _info else _served(res)
        mt = _RX_TAX.match(ar_path)
        if mt:
            facet_g, slug_g, year_g, sect_g, page_g = mt.groups()
            if page_g == "1":
                return 301, b"", {"Location": path.replace("page/1/", "")}
            facet = facet_g or ("year" if year_g else "latest")
            res = render_taxonomy(con, data_dir, facet, slug_g or year_g or "", sect_g or "", int(page_g or 1), tr, st)
            if not res:
                return 404, b"", {}
            return res[1] if _info else _served(res)
        m = _RX.match(ar_path)
        if not m:
            return 404, b"", {}
        typ, slug, role_path, pslug, ppage, cslug, cpage, hub, section, subk, subv, page = m.groups()
        if (ppage or cpage or page) == "1":
            return 301, b"", {"Location": path.replace("page/1/", "")}
        if typ:
            res = render_entity(con, data_dir, "movie" if typ == "movies" else "series", slug, tr, st)
        elif role_path:
            res = render_person(con, data_dir, role_path, pslug, tr, st, int(ppage or 1))
        elif cslug:
            res = render_company(con, data_dir, cslug, tr, st, int(cpage or 1))
        else:
            res = render_hub(con, data_dir, hub, section or "", (subk, subv) if subk else None, int(page or 1), tr, st)
        if not res:
            return 404, b"", {}
        if res[0] == "redirect":
            return None if _info else (301, b"", {"Location": res[1]})
        if _info:
            return res[1]
        if res[1].get("noindex", True):
            return 200, res[1]["html"], {"X-Robots-Tag": "noindex", "Cache-Control": "private, max-age=0"}
        return 200, res[1]["html"], {"Cache-Control": "public, max-age=600"}     # معتمدٌ مستحقّ (المرحلة 4): بلا رأس noindex، والوسم index في الصفحة
    finally:
        _tl.con = None
        if _con is None:
            con.close()


# ================= فحص العيّنة =================
def audit(data_dir, n=30):
    """عيّنة (تركي · أنمي · عالمي · عربي) بصفحاتها باللغتين وهبّاها: ما يُفحص قبل الفهرسة — ومن سطر الأوامر."""
    con = seo_db.connect(data_dir, create=False)
    if con is None:
        return {"error": "لم تُبنَ القاعدة"}
    try:
        st = seo_db.settings(con)
        picks, seen = [], set()

        def take(sql, k):
            for r in con.execute(sql + " LIMIT ?", (k,)):
                if r["id"] not in seen:
                    seen.add(r["id"]); picks.append(r)
        q = "SELECT c.* FROM content c WHERE c.merged_into IS NULL AND c.available=1 AND c.match='tmdb'"
        hub = " AND c.id IN (SELECT ct.content_id FROM content_taxonomy ct JOIN taxonomy t ON t.id=ct.taxonomy_id WHERE t.kind='hub' AND t.key=? AND ct.source IN ('tmdb','manual'))"
        each = max(1, n // 4)
        for key in HUBS:
            for r in con.execute(q + hub + " ORDER BY c.popularity DESC LIMIT ?", (key, each)):
                if r["id"] not in seen:
                    seen.add(r["id"]); picks.append(r)
        take(q + " AND c.title GLOB '*[A-Za-z]*' ORDER BY c.popularity DESC", each)
        take(q + " AND c.title GLOB '*[؀-ۿ]*' ORDER BY c.popularity DESC", each)
        take("SELECT c.* FROM content c WHERE c.merged_into IS NULL AND c.available=1 ORDER BY c.id", n - len(picks)) if len(picks) < n else None
        results, canon = [], {}
        checks_total = {"pass": 0, "fail": 0}

        def check_page(label, res, lang, path):
            errs = []
            html = res["html"].decode("utf-8")
            if html.count("<h1") != 1:
                errs.append("h1 != 1")
            if not res["title"] or len(res["title"]) > 90:
                errs.append("title")
            if not res["desc"] or len(res["desc"]) > 175:
                errs.append("description")
            if res["canonical"] != SITE + path:
                errs.append(f"canonical {res['canonical']}")
            if 'name="robots" content="noindex' not in html:
                errs.append("noindex missing (preview)")
            if '"BreadcrumbList"' not in html:
                errs.append("breadcrumb")
            for s in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
                try:
                    json.loads(s.replace("<\\/", "</"))
                except ValueError:
                    errs.append("schema json")
            if ('"@type": "Movie"' not in html and '"@type": "TVSeries"' not in html and '"@type": "Person"' not in html and '"@type": "CollectionPage"' not in html):
                errs.append("schema type")
            links = re.findall(r'href="(/(?:en/)?content/[^"]+)"', html)
            if len(links) < 3:
                errs.append("few internal links")
            bad = [u for u in links if handle(data_dir, u.split("?")[0], "en" if u.startswith("/en/") else "ar")[0] not in (200, 301)]
            if bad:
                errs.append(f"broken links: {bad[:3]}")
            alts = dict(res["alts"])
            if alts and (alts.get(lang) != res["canonical"]):
                errs.append("hreflang self")
            if res["canonical"] in canon and canon[res["canonical"]] != label:
                errs.append(f"duplicate canonical with {canon[res['canonical']]}")
            canon[res["canonical"]] = label
            imgs = re.findall(r"<img [^>]*>", html)
            if any(' alt=' not in i for i in imgs):
                errs.append("img without alt")
            checks_total["pass" if not errs else "fail"] += 1
            return {"page": label, "lang": lang, "path": path, "ok": not errs, "errors": errs, "would_index": res["index_ar"] if lang == "ar" else res["index_en"],
                    "why": res["why"][0 if lang == "ar" else 1], "title": res["title"]}
        for r in picks:
            for lang in ("ar", "en"):
                res = render_entity(con, data_dir, r["type"], r["slug"], P.lang_of(lang), st)
                if res and res[0] == "page":
                    results.append(check_page(f"{r['type']}:{r['slug']}", res[1], lang, _path(r, lang)))
        for key in HUBS:
            for lang in ("ar", "en"):
                for section in ("", "series", "movies"):
                    res = render_hub(con, data_dir, key, section, None, 1, P.lang_of(lang), st)
                    if res:
                        results.append(check_page(f"hub:{key}/{section}", res[1], lang, _hub_path(key, section, lang)))
        return {"sample": len(picks), "pages": len(results), **checks_total, "would_index": sum(1 for x in results if x["would_index"]),
                "preview": bool(st.get("preview")), "results": results}
    finally:
        con.close()


CSS = """
:root{color-scheme:dark;--bg:#060b17;--card:#0e172c;--card2:#132039;--line:#1c2a4a;--ink:#eaf0ff;--mute:#8fa2c6;--acc:#2f8cff;--gold:#f6c343}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.65 "IBM Plex Sans Arabic",Tahoma,sans-serif}
a{color:inherit;text-decoration:none}img{display:block;max-width:100%;height:auto}.wrap{max-width:1200px;margin:0 auto;padding:0 16px}
.top{border-bottom:1px solid var(--line);background:rgba(6,11,23,.9)}.top .wrap{display:flex;gap:16px;align-items:center;min-height:60px}
.brand b{font-size:1.1rem}.brand small{display:block;color:var(--mute);font-size:.7rem;direction:ltr}.nav{display:flex;gap:4px;overflow-x:auto}
.nav a{padding:8px 12px;border-radius:10px;color:var(--mute);font-weight:600;white-space:nowrap}.nav a[aria-current]{color:var(--acc)}
.crumbs ol{list-style:none;display:flex;flex-wrap:wrap;gap:6px;padding:0;margin:14px 0 0;color:var(--mute);font-size:.85rem}.crumbs li+li::before{content:"›";margin-inline-end:6px}
.tools{display:flex;justify-content:flex-end;margin:6px 0}.lang{border:1px solid var(--line);border-radius:10px;padding:6px 12px;color:var(--mute);font-weight:600}
.hero{position:relative;overflow:hidden;border-radius:18px;background:var(--card);margin-top:10px}.hero .bg{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:.18;filter:blur(2px)}
.hd{position:relative;display:grid;grid-template-columns:220px 1fr;gap:22px;padding:22px 16px}.hd .pos img,.hd .pos .ph{width:220px;aspect-ratio:2/3;border-radius:14px;object-fit:cover;background:var(--card2)}
.ph{display:grid;place-items:center;font-size:2rem;color:var(--mute)}h1{margin:0 0 4px;font-size:1.7rem;line-height:1.25}.orig{color:var(--mute);margin:0 0 8px;direction:ltr;text-align:start}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}.chip{display:inline-block;background:var(--card2);border:1px solid var(--line);border-radius:999px;padding:3px 11px;font-size:.84rem}
.chip small{color:var(--mute)}.facts{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;margin:10px 0 0;font-size:.92rem}.facts dt{color:var(--mute)}.facts dd{margin:0}.facts a{color:var(--acc)}
.cols{display:grid;grid-template-columns:1fr 320px;gap:24px;margin-top:22px}h2{font-size:1.25rem;margin:26px 0 10px}h3{font-size:1.05rem;margin:18px 0 8px}
.story p{font-size:1.02rem}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:14px}.card .pos{display:block;aspect-ratio:2/3;border-radius:12px;overflow:hidden;background:var(--card2)}
.card .pos img{width:100%;height:100%;object-fit:cover}.card b{display:block;margin-top:6px;font-size:.92rem;line-height:1.3}.card small{color:var(--mute);font-size:.8rem}
.people{display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:12px}.person .pos{display:block;aspect-ratio:2/3;border-radius:12px;overflow:hidden;background:var(--card2)}
.person .pos img{width:100%;height:100%;object-fit:cover}.person b{display:block;margin-top:5px;font-size:.86rem}.person small{display:block;color:var(--mute);font-size:.78rem}
details{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin:8px 0}summary{cursor:pointer;font-weight:600}summary small{color:var(--mute);font-weight:400}
.eps{padding-inline-start:0;list-style:none;margin:8px 0 0}.eps li{padding:5px 0;border-top:1px solid var(--line);font-size:.9rem}.eps li span{display:inline-block;min-width:28px;color:var(--mute)}
.pics-row img{border-radius:12px}.yt{position:relative;aspect-ratio:16/9;border-radius:12px;overflow:hidden;background:#000}.yt iframe{position:absolute;inset:0;width:100%;height:100%;border:0}
.card .pos{position:relative}.rt-badge{position:absolute;inset-block-start:6px;inset-inline-start:6px;background:rgba(6,11,23,.82);color:var(--gold);border-radius:999px;padding:2px 8px;font:700 .74rem/1.5 inherit;font-style:normal}
.tour h1{margin:8px 0}.tour .lead{color:var(--mute);margin:0 0 14px}.tsteps{display:flex;gap:8px;margin:10px 0 18px;padding:0;list-style:none;flex-wrap:wrap}
.tsteps li{padding:5px 12px;border:1px solid var(--line);border-radius:999px;color:var(--mute);font-size:.85rem}.tsteps li.on{border-color:var(--acc);color:var(--ink);font-weight:700}
.tchips{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0 14px}.tchip{padding:9px 14px;border-radius:999px;border:1.5px solid var(--line);background:var(--card);color:var(--ink);font:inherit;cursor:pointer}
.tchip.on{border-color:var(--acc);background:rgba(47,140,255,.18);font-weight:700}.tbtns{display:flex;gap:10px;margin:16px 0;flex-wrap:wrap}.tbtns.top{position:sticky;inset-block-start:0;z-index:20;margin:0 0 12px;padding:10px 0;background:var(--bg)}.tour h3{margin:14px 0 6px;font-size:.95rem;color:var(--mute)}
.tbtn{padding:11px 20px;border-radius:12px;border:1.5px solid var(--line);background:var(--card);color:var(--ink);font:inherit;font-weight:700;cursor:pointer}.tbtn.go{background:var(--acc);border-color:var(--acc);color:#fff}
.tsearch{width:100%;padding:12px 14px;border-radius:12px;border:1.5px solid var(--line);background:var(--card);color:var(--ink);font:inherit;margin:6px 0 12px}
.card.pick .pk{display:flex;gap:6px;margin-top:6px}.card.pick .pk button{flex:1;padding:6px 4px;border-radius:9px;border:1.5px solid var(--line);background:var(--card);color:var(--ink);font:inherit;font-size:.78rem;cursor:pointer}
.card.pick .pk button.on{border-color:#ff5d7a;color:#ff5d7a;font-weight:700}.card.pick .pk button.sn.on{border-color:var(--acc);color:var(--acc)}
.tour .meta,.tmsg{color:var(--mute);font-size:.88rem}
.like-bar{margin:12px 0 0}.like-btn{display:inline-flex;align-items:center;gap:8px;padding:9px 16px;border-radius:999px;border:1.5px solid var(--line);background:var(--card);color:var(--ink);font:inherit;font-weight:700;cursor:pointer}
.like-btn .heart{font-size:1.15rem;line-height:1}.like-btn b{font-weight:700;color:var(--mute);min-width:1ch}.like-btn.on{border-color:#ff5d7a;color:#ff5d7a}.like-btn.on b{color:#ff5d7a}
.foryou[hidden]{display:none}.foryou .meta{color:var(--mute);font-size:.85rem;margin:4px 0 10px}
.avail{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px 16px;position:sticky;top:12px}.avail h2{margin:0 0 10px;font-size:1.1rem}
.srv{list-style:none;padding:0;margin:0}.srv li{display:flex;align-items:center;gap:10px;padding:9px 0;border-top:1px solid var(--line)}.srv li:first-child{border-top:0}.srv li span{flex:1}
.srv small{display:block;color:var(--mute);font-size:.8rem}.logo{width:34px;height:34px;border-radius:10px;object-fit:cover}.btn{background:var(--acc);color:#fff;border-radius:10px;padding:7px 12px;font-weight:700;font-size:.86rem;white-space:nowrap}
.airing{display:grid;gap:3px;background:var(--card);border:1px solid var(--line);border-inline-start:4px solid var(--mute);border-radius:12px;padding:11px 14px;margin:14px 0}.airing.live{border-inline-start-color:#22c58b}
.airing b{font-size:1.02rem}.airing small{color:var(--mute)}
.guide{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px 16px;margin:18px 0}.guide h2{margin:0 0 8px}.guide h3{margin:14px 0 4px;font-size:1rem}
.g-sum{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:0 0 10px}.g-age{background:var(--acc);color:#fff;border-radius:10px;padding:3px 10px}.g-sum small,.g-none{color:var(--mute)}
.g-cats{list-style:none;padding:0;margin:0}.g-cats li{display:flex;gap:10px;align-items:center;padding:6px 0;border-top:1px solid var(--line)}.g-cats li:first-child{border-top:0}.g-cats li span:first-child{flex:1}
.g-cats .dots{letter-spacing:2px;color:var(--gold);direction:ltr}.g-cats em{min-width:5.5em;font-style:normal;color:var(--mute);text-align:end}.g-text{margin:10px 0 0}
.g-scenes{padding-inline-start:18px;margin:6px 0}.g-scenes li{margin:6px 0}.g-scenes time{background:rgba(255,255,255,.08);border-radius:6px;padding:1px 6px}.g-scenes i{color:var(--gold);font-style:normal}.g-scenes small{color:var(--mute)}
.g-report{margin-top:12px}.g-report summary{cursor:pointer;color:var(--acc)}.g-report form{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}.g-report input,.g-report select,.g-report textarea{background:var(--bg);color:inherit;border:1px solid var(--line);border-radius:8px;padding:6px 8px;font:inherit}
.g-report textarea{flex:1 1 100%}.g-report button{background:var(--acc);color:#fff;border:0;border-radius:8px;padding:7px 14px;font:inherit}.g-msg{color:var(--mute);align-self:center}
.cta{color:var(--mute);font-size:.86rem;margin:10px 0 0}.intro{font-size:1.05rem;color:#dbe4ff;max-width:900px}.more{text-align:end}.more a{color:var(--acc)}
.pager{display:flex;justify-content:center;gap:16px;align-items:center;margin:24px 0}.pager a{border:1px solid var(--line);border-radius:10px;padding:8px 14px}
.foot{border-top:1px solid var(--line);margin-top:40px;padding:18px 0;color:var(--mute);font-size:.86rem}.foot a{color:var(--acc)}
@media(max-width:800px){.hd{grid-template-columns:1fr}.hd .pos img,.hd .pos .ph{width:160px}.cols{grid-template-columns:1fr}.cols>aside{order:-1}.avail{position:static;border-color:var(--acc);box-shadow:0 8px 24px -16px rgba(47,140,255,.6)}}
"""


def main(argv):
    data_dir = os.environ.get("XM_DATA") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    cmd = argv[1] if len(argv) > 1 else "audit"
    opt = {a.lstrip("-").split("=")[0]: (a.split("=", 1)[1] if "=" in a else True) for a in argv[2:] if a.startswith("--")}
    if cmd == "audit":
        rep = audit(data_dir, int(opt.get("n") or 30))
        if opt.get("json"):
            print(json.dumps(rep, ensure_ascii=False, indent=1))
        else:
            print(f"عيّنة {rep.get('sample')} عملًا · {rep.get('pages')} صفحة · ناجحة {rep.get('pass')} · فيها ملاحظات {rep.get('fail')} · تستحق الفهرسة {rep.get('would_index')}")
            for r in rep.get("results") or []:
                if r["errors"] or not r["would_index"]:
                    print(f"  {r['lang']} {r['path']}: {', '.join(r['errors']) or 'ok'}; index={r['would_index']} ({r['why']})")
    elif cmd == "render":                      # python seo_pages.py render --path=/content/series/x/ --lang=ar
        code, body, hdr = handle(data_dir, str(opt.get("path") or "/content/turkish/"), str(opt.get("lang") or "ar")) or (404, b"", {})
        print(code, hdr); sys.stdout.write(body.decode("utf-8", "replace"))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)

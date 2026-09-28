# -*- coding: utf-8 -*-
"""ترتيب الدوريات: بطاقة في الرئيسية (‏/api/league) وصفحة لكل دوري (‏/standings/…).

المصدر: واجهة الترتيب العامة في ESPN — بلا مفتاح ولا تسجيل، وتُرجع الموسم
الجاري وحده، فلا شيء يُعدَّل يدويًا مع بداية كل موسم. والأسماء فيها
بالإنجليزية فتُعرَّب هنا: الدوري من `LEAGUES`، والنادي من `AR` **بمعرّفه عند
ESPN** لا باسمه (الاسم يتغيّر إملاؤه والمعرّف ثابت)، ومناطق التأهل والهبوط من
`ZONES`. نادٍ لم يُضَف سطره بعدُ يظهر باسمه الإنجليزي حتى يُضاف.

الجدول يُرسم هنا وحده، صفحةً كاملة على السيرفر كصفحات الأجهزة (بأنماط المعالج
نفسها) فيقرؤه محرك البحث كما يراه الزائر، ومقطعًا تحقنه الرئيسية كما هو.

الكاش لكل دوري على حدة: يُجلب عند أول طلب ويُحفظ ربع ساعة (`LEAGUE_TTL`).
انتهاء المدة لا يؤخّر أحدًا: يُقدَّم المحفوظ فورًا ويُجدَّد في الخلفية، فلا يصل
ESPN أكثر من طلب لكل دوري كل ربع ساعة مهما كثر الزوار. والفشل يُبقي آخر نسخة
صالحة ويعيد المحاولة بعد دقيقتين — إلا إن تجاوز عمرها يومين فيُخفى الجدول بدل
أن يُعرض ترتيبٌ قديم على أنه الحالي.
"""
import datetime
import html as _html
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

import guide_pages

API = os.environ.get("LEAGUE_API", "https://site.api.espn.com/apis/v2/sports/soccer").rstrip("/")
TTL = int(os.environ.get("LEAGUE_TTL", "900"))
RETRY = 120                       # بعد فشلٍ: متى تُعاد المحاولة
MAX_AGE = 2 * 24 * 3600           # أقدم نسخة تُعرض إن تعذّر التجديد
TIMEOUT = 10
PREVIEW = 6                       # صفوف كل جدول في بطاقة الرئيسية (4 إن تعدّدت المجموعات)
PATH = "/standings/"
LOGO_HOST = "https://a.espncdn.com"
RIYADH = datetime.timezone(datetime.timedelta(hours=3))

# المفتاح آخر الرابط (/standings/<المفتاح>) وهو ما ترسله الرئيسية في ?l=.
# الترتيب هنا ترتيب الأزرار والروابط بين الصفحات، والأول هو الافتراضي.
LEAGUES = {
    "saudi-pro-league":     dict(code="ksa.1", name="دوري روشن السعودي", tab="السعودي"),
    "premier-league":       dict(code="eng.1", name="الدوري الإنجليزي الممتاز", tab="الإنجليزي"),
    "la-liga":              dict(code="esp.1", name="الدوري الإسباني", tab="الإسباني"),
    "serie-a":              dict(code="ita.1", name="الدوري الإيطالي", tab="الإيطالي"),
    "bundesliga":           dict(code="ger.1", name="الدوري الألماني", tab="الألماني"),
    "ligue-1":              dict(code="fra.1", name="الدوري الفرنسي", tab="الفرنسي"),
    "champions-league":     dict(code="uefa.champions", name="دوري أبطال أوروبا", tab="أبطال أوروبا"),
    "afc-champions-league": dict(code="afc.champions", name="دوري أبطال آسيا للنخبة", tab="أبطال آسيا"),
}
DEFAULT = next(iter(LEAGUES))
MENU = [{"slug": k, "tab": v["tab"]} for k, v in LEAGUES.items()]
SITEMAP = [(PATH + k, "daily", "0.7") for k in LEAGUES]

# أسماء الأندية بالعربية بمعرّفها عند ESPN: أندية الموسم الجاري ومن مرّ على
# كل دوري في الموسمين السابقين (فالهابط إن صعد ثانيةً يظهر بالعربية).
AR = {
    # السعودي
    "929": "الهلال", "2276": "الاتحاد", "817": "النصر", "8346": "الأهلي",
    "22022": "القادسية", "130899": "نيوم", "22028": "الخلود", "131746": "الدرعية",
    "8363": "الاتفاق", "21964": "الحزم", "21965": "الرياض", "21827": "الفيحاء",
    "21829": "الخليج", "793": "الشباب", "13033": "الفتح", "21446": "الفيصلي",
    "18459": "التعاون", "21833": "أبها", "21830": "العدالة", "21832": "الباطن",
    "22023": "النجمة", "21966": "الأخدود", "22029": "العروبة", "21834": "الرائد",
    "21831": "الطائي", "21835": "الوحدة", "21828": "ضمك",
    # الإنجليزي
    "382": "مانشستر سيتي", "359": "آرسنال", "331": "برايتون", "337": "برينتفورد",
    "357": "ليدز يونايتد", "364": "ليفربول", "368": "إيفرتون", "306": "هال سيتي",
    "361": "نيوكاسل يونايتد", "363": "تشيلسي", "373": "إيبسويتش تاون",
    "360": "مانشستر يونايتد", "393": "نوتنغهام فورست", "366": "سندرلاند",
    "384": "كريستال بالاس", "362": "أستون فيلا", "349": "بورنموث", "388": "كوفنتري سيتي",
    "370": "فولهام", "367": "توتنهام", "371": "وست هام يونايتد", "379": "بيرنلي",
    "380": "وولفرهامبتون", "375": "ليستر سيتي", "376": "ساوثهامبتون",
    # الإسباني
    "83": "برشلونة", "1068": "أتلتيكو مدريد", "244": "ريال بيتيس", "86": "ريال مدريد",
    "243": "إشبيلية", "96": "ألافيس", "90": "ديبورتيفو لاكورونيا", "89": "ريال سوسيداد",
    "102": "فياريال", "93": "أتلتيك بلباو", "2922": "خيتافي", "101": "رايو فاييكانو",
    "97": "أوساسونا", "85": "سيلتا فيغو", "88": "إسبانيول", "87": "راسينغ سانتاندير",
    "1538": "ليفانتي", "3751": "إلتشي", "94": "فالنسيا", "99": "ملقة", "84": "مايوركا",
    "9812": "جيرونا", "92": "ريال أوفييدو", "17534": "ليغانيس", "98": "لاس بالماس",
    "95": "بلد الوليد",
    # الإيطالي
    "104": "روما", "110": "إنتر ميلان", "112": "لاتسيو", "2925": "كالياري", "103": "ميلان",
    "4057": "فروزينوني", "111": "يوفنتوس", "2572": "كومو", "114": "نابولي", "3997": "ساسولو",
    "105": "أتالانتا", "113": "ليتشي", "118": "أودينيزي", "239": "تورينو", "115": "بارما",
    "4007": "مونزا", "109": "فيورنتينا", "107": "بولونيا", "3263": "جنوى", "17530": "فينيسيا",
    "4050": "كريمونيزي", "119": "هيلاس فيرونا", "3956": "بيزا", "2574": "إمبولي",
    # الألماني
    "124": "بوروسيا دورتموند", "132": "بايرن ميونخ", "126": "فرايبورغ", "3841": "أوغسبورغ",
    "131": "باير ليفركوزن", "2950": "ماينز", "10388": "إلفرسبيرغ", "137": "فيردر بريمن",
    "11420": "لايبزيغ", "125": "آينتراخت فرانكفورت", "133": "شالكه", "3307": "بادربورن",
    "122": "كولن", "7911": "هوفنهايم", "134": "شتوتغارت", "127": "هامبورغ",
    "598": "يونيون برلين", "268": "بوروسيا مونشنغلادباخ", "138": "فولفسبورغ",
    "6418": "هايدنهايم", "270": "سانت باولي", "7884": "هولشتاين كيل", "121": "بوخوم",
    # الفرنسي
    "174": "موناكو", "167": "ليون", "6851": "باريس إف سي", "166": "ليل", "169": "رين",
    "160": "باريس سان جيرمان", "7868": "أنجيه", "180": "ستراسبورغ", "2697": "لومان",
    "172": "أوكسير", "6997": "بريست", "273": "لوريان", "179": "تولوز", "2502": "نيس",
    "175": "لانس", "170": "تروا", "176": "مارسيليا", "3236": "لوهافر", "165": "نانت",
    "177": "ميتز", "3243": "ريمس", "178": "سانت إتيان", "274": "مونبلييه",
    # دوري أبطال أوروبا (من خارج الدوريات الخمسة)
    "2250": "سبورتينغ لشبونة", "887": "أيك أثينا", "493": "شاختار دونيتسك",
    "436": "فنربخشة", "148": "آيندهوفن", "570": "كلوب بروج", "494": "سلافيا براغ",
    "4411": "لاسك لينز", "432": "غلطة سراي", "510": "فايكنغ", "437": "بورتو",
    "142": "فينورد", "21922": "صباح الأذربيجاني", "521": "سلوفان براتيسلافا",
    "2980": "بودو غليمت", "435": "أولمبياكوس", "10414": "قره باغ", "1929": "بنفيكا",
    "22281": "بافوس", "5807": "أونيون سان جيلواز", "909": "كوبنهاغن", "139": "أياكس",
    "2528": "كايرات ألماتي", "256": "سلتيك", "597": "دينامو زغرب", "2290": "النجم الأحمر",
    "3746": "شتورم غراتس", "433": "سبارتا براغ", "2790": "سالزبورغ", "2722": "يونغ بويز",
    # دوري أبطال آسيا للنخبة (من خارج الدوري السعودي)
    "2052": "بكين غوان", "5323": "نيوكاسل جيتس", "7102": "غامبا أوساكا",
    "7115": "كاشيما أنتلرز", "7119": "جونبوك هيونداي", "7138": "بوريرام يونايتد",
    "7476": "كاشيوا ريسول", "7477": "فيسيل كوبي", "9693": "بوهانغ ستيلرز",
    "15515": "شنغهاي بورت", "17689": "جوهور دار التعظيم", "17757": "بورت التايلندي",
    "17760": "راتشابوري", "21361": "كيوتو سانغا", "131375": "كونغ آن هانوي",
    "133171": "دايجون هانا سيتيزن", "790": "شباب الأهلي", "7123": "باختاكور",
    "7128": "العين", "7129": "الغرافة", "7135": "السد", "7525": "استقلال طهران",
    "7530": "نفتشي فرغانة", "8365": "الوصل", "15107": "تراكتور", "20912": "القوة الجوية",
    "21575": "الشمال", "977": "شنغهاي شينهوا", "6972": "إف سي سيول",
    "7114": "سانفريتشي هيروشيما", "7120": "أولسان", "11143": "ملبورن سيتي",
    "21355": "تشنغدو رونغتشنغ", "22167": "ماتشيدا زيلفيا", "131373": "غانغوون",
    "7134": "الوحدة الإماراتي", "8217": "ناساف قرشي", "8371": "الشارقة", "9655": "الشرطة",
    "12008": "الدحيل", "5325": "سنترال كوست مارينرز", "7112": "كاواساكي فرونتال",
    "7116": "يوكوهاما مارينوس", "7521": "شاندونغ تايشان", "22351": "غوانغجو",
    "7527": "الريان", "18461": "برسبوليس",
}

# ملاحظة ESPN على صفّ النادي ← (المفتاح، الاسم العربي، اللون). الأدقّ أولًا:
# "Champions League qualifying" تُفحص قبل "Champions League". والألوان ألواننا
# لا ألوان ESPN، لأن فيها لونًا واحدًا لمنطقتين مختلفتين في الدوري نفسه.
ZONES = [
    ("round of 16", "r16", "التأهل المباشر إلى دور الـ16", "#16A34A"),
    ("playoffs - seeded", "kos", "ملحق دور الـ16 (مصنّف)", "#4ADE80"),
    ("playoffs - unseeded", "kou", "ملحق دور الـ16 (غير مصنّف)", "#60A5FA"),
    ("champions league qualifying", "uclq", "تصفيات دوري أبطال أوروبا", "#4ADE80"),
    ("champions league", "ucl", "دوري أبطال أوروبا", "#16A34A"),
    ("europa league qualifying", "uelq", "تصفيات الدوري الأوروبي", "#60A5FA"),
    ("europa league", "uel", "الدوري الأوروبي", "#2563EB"),
    ("conference league qualifying", "ueclq", "تصفيات دوري المؤتمر الأوروبي", "#2DD4BF"),
    ("conference league", "uecl", "دوري المؤتمر الأوروبي", "#0D9488"),
    ("relegation playoff", "rpo", "ملحق الهبوط", "#F59E0B"),
    ("relegat", "rel", "الهبوط", "#DC2626"),
    ("eliminated", "out", "الخروج من البطولة", "#DC2626"),
]

# البطولة ذات الجداول المتعددة: اسم كل جدول وترتيب عرضه — منطقة الغرب أولًا في
# دوري أبطال آسيا لأن الأندية السعودية فيها. (ESPN تسمّيها "West Region" مرةً
# و"WEST" مرة، فالمطابقة بجزء من الاسم.)
GROUPS = {"west": (0, "منطقة الغرب"), "east": (1, "منطقة الشرق")}

MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس",
          "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]

_lock = threading.Lock()
_state = {k: {"data": None, "at": 0.0, "next": 0.0, "busy": False, "error": None,
              "first": threading.Event()} for k in LEAGUES}


# ---------- القراءة من ESPN ----------
def _stat(entry, name):
    for s in entry.get("stats") or []:
        if s.get("name") == name:
            try:
                return int(round(float(s.get("value") or 0)))
            except (TypeError, ValueError):
                return 0
    return 0


def _logo(team):
    """شعار النادي مصغّرًا (48px بدل 500px) من خادم صور ESPN وحده."""
    for lg in team.get("logos") or []:
        href = str(lg.get("href") or "")
        if href.startswith(LOGO_HOST + "/i/"):
            img = urllib.parse.quote(href[len(LOGO_HOST):])
            return f"{LOGO_HOST}/combiner/i?img={img}&w=48&h=48"
    return ""


def _zone(entry):
    """(المفتاح، الاسم، اللون) لملاحظة الصف، أو None. غير المعروفة تبقى بنصّها."""
    desc = str((entry.get("note") or {}).get("description") or "").strip()
    if not desc:
        return None
    low = desc.lower()
    for needle, key, label, color in ZONES:
        if needle in low:
            return key, label, color
    return "x-" + re.sub(r"[^a-z0-9]+", "-", low).strip("-")[:30], desc, "#94A3B8"


def _group(name, i):
    """(ترتيب العرض، الاسم العربي) لجدولٍ من جداول البطولة."""
    key = str(name or "").strip().lower()
    for needle, got in GROUPS.items():
        if re.search(rf"\b{needle}\b", key):
            return got
    m = re.fullmatch(r"group ([a-z0-9]+)", key)
    return 10 + i, (f"المجموعة {m.group(1).upper()}" if m else str(name or ""))


def parse(data):
    """رد ESPN ← {season, groups, zones}. يرفع ValueError إن لم يكن فيه جدول."""
    groups, zones = [], {}
    for i, ch in enumerate(data.get("children") or []):
        rows = []
        for e in (ch.get("standings") or {}).get("entries") or []:
            t = e.get("team") or {}
            rows.append({
                "rank": _stat(e, "rank"),
                "name": AR.get(str(t.get("id") or "")) or t.get("displayName") or t.get("name") or "—",
                "logo": _logo(t),
                "p": _stat(e, "gamesPlayed"), "w": _stat(e, "wins"),
                "d": _stat(e, "ties"), "l": _stat(e, "losses"),
                "gf": _stat(e, "pointsFor"), "ga": _stat(e, "pointsAgainst"),
                "gd": _stat(e, "pointDifferential"), "pts": _stat(e, "points"),
                "zone": _zone(e),
            })
        if len(rows) < 2:
            continue
        rows.sort(key=lambda r: (r["rank"] or 999, -r["pts"]))
        for n, r in enumerate(rows):
            r["rank"] = r["rank"] or n + 1
            if r["zone"]:
                key, label, color = r["zone"]
                zones.setdefault(key, {"label": label, "color": color})
                r["zone"] = key
            else:
                r["zone"] = ""
        order, gname = _group(ch.get("name"), i)
        groups.append((order, {"name": gname, "rows": rows}))
    if not groups:
        raise ValueError("no standings in response")
    groups = [g for _, g in sorted(groups, key=lambda og: og[0])]
    # "2026-27 Saudi Pro League" ← "2026-27"
    names = [(data.get("season") or {}).get("displayName")]
    for ch in data.get("children") or []:
        names += [(ch.get("standings") or {}).get("seasonDisplayName"), ch.get("abbreviation")]
    m = re.search(r"\b(20\d\d)\s*[-–/]\s*(\d\d)", " ".join(n for n in names if isinstance(n, str)))
    return {"season": f"{m.group(1)}-{m.group(2)}" if m else "", "groups": groups, "zones": zones}


def _fetch(code):
    # بلا User-Agent خاص: بوابة ESPN (‏Akamai) تردّ 403 على أي وكيل مخصَّص أو
    # شبيهٍ بالمتصفح، وتقبل وكيل urllib الافتراضي (عكس سلة في store_sitemap).
    req = urllib.request.Request(f"{API}/{code}/standings", headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


# ---------- الكاش ----------
def refresh(slug):
    """جلبٌ واحد يحدّث كاش الدوري؛ الفشل يُبقي آخر نسخة صالحة ويؤجّل المحاولة."""
    st = _state[slug]
    data, error = None, None
    try:
        data = parse(_fetch(LEAGUES[slug]["code"]))
    except Exception as e:        # شبكة، مهلة، JSON تالف، أو شكلٌ غير متوقّع
        error = (str(e) or e.__class__.__name__)[:160]
    finally:
        now = time.time()
        with _lock:
            if data:
                st.update(data=data, at=now, next=now + TTL)
            else:
                st["next"] = now + RETRY
            st.update(busy=False, error=error)
        st["first"].set()
    return data is not None


def table(slug=None):
    """جدول الدوري من الكاش (None لمفتاح غير معروف)، ويُجدَّد في الخلفية متى
    انتهت مدته. أول زائر بعد الإقلاع وحده ينتظر الجلب الأول (بحدّ المهلة)."""
    slug = slug or DEFAULT
    lg = LEAGUES.get(slug)
    if not lg:
        return None
    st = _state[slug]
    now = time.time()
    with _lock:
        if now >= st["next"] and not st["busy"]:
            st["busy"] = True
            threading.Thread(target=refresh, args=(slug,), daemon=True).start()
    st["first"].wait(TIMEOUT + 2)
    with _lock:
        data, at, error = st["data"], st["at"], st["error"]
    head = {"slug": slug, "league": lg["name"], "page": PATH + slug, "leagues": MENU}
    if not data or time.time() - at > MAX_AGE:
        return dict(head, ok=False, error=error or "stale")
    return dict(head, ok=True, source="ESPN", updated=int(at), **data)


# ---------- الرسم ----------
def _esc(s):
    return _html.escape(str(s if s is not None else ""), quote=True)


def _count(n, one, two, few, many):
    """العدد مع معدوده كما يُكتب: نقطة واحدة، نقطتين، 7 نقاط، 18 نقطة."""
    if n == 1:
        return f"{one} واحدة"
    if n == 2:
        return two
    return f"{n} {few if 3 <= n <= 10 else many}"


def _when(ts):
    t = datetime.datetime.fromtimestamp(ts, RIYADH)
    return (f"{t.day} {MONTHS[t.month - 1]} {t.year}، "
            f"{t.hour % 12 or 12}:{t.minute:02d} {'ص' if t.hour < 12 else 'م'}")


def _season(t):
    return f' <span class="season" dir="ltr">{_esc(t["season"])}</span>' if t.get("season") else ""


def _tables_html(t, limit=0):
    """جداول الدوري (جدول لكل مجموعة) ودليل ألوانه. limit يقصّ كل جدول
    لبطاقة الرئيسية، وبدونه يخرج كاملًا بعمودَي الأهداف له وعليه."""
    full = not limit
    many = len(t["groups"]) > 1
    cut = (4 if many else limit) if limit else 0
    gcols = ('<th scope="col" class="gfga"><abbr title="الأهداف له">له</abbr></th>'
             '<th scope="col" class="gfga"><abbr title="الأهداف عليه">عليه</abbr></th>') if full else ""
    head = ('<thead><tr><th scope="col"><abbr title="المركز">#</abbr></th>'
            '<th scope="col" class="team">النادي</th>'
            '<th scope="col"><abbr title="عدد المباريات">لعب</abbr></th>'
            '<th scope="col" class="wdl"><abbr title="فوز">ف</abbr></th>'
            '<th scope="col" class="wdl"><abbr title="تعادل">ت</abbr></th>'
            '<th scope="col" class="wdl"><abbr title="خسارة">خ</abbr></th>'
            f'{gcols}<th scope="col"><abbr title="فارق الأهداف">فارق</abbr></th>'
            '<th scope="col"><abbr title="النقاط">نقاط</abbr></th></tr></thead>')
    out, seen = [], []
    for g in t["groups"]:
        rows = g["rows"][:cut] if cut else g["rows"]
        body = []
        for r in rows:
            z = t["zones"].get(r["zone"])
            if z and r["zone"] not in seen:
                seen.append(r["zone"])
            crest = (f'<img src="{_esc(r["logo"])}" alt="" width="22" height="22" loading="lazy">'
                     if r["logo"] else '<i class="crest"></i>')
            goals = f'<td class="gfga">{r["gf"]}</td><td class="gfga">{r["ga"]}</td>' if full else ""
            # اللون وحده لا يُقرأ: اسم المنطقة تلميحٌ على المركز ونصٌّ لقارئ الشاشة
            style, rank = "", r["rank"]
            if z:
                style = f' style="--z:{z["color"]}"'
                rank = f'<span title="{_esc(z["label"])}">{rank}</span><span class="sr"> — {_esc(z["label"])}</span>'
            body.append(
                f'<tr{style}><td>{rank}</td>'
                f'<th scope="row" class="team"><span>{crest}<b dir="auto">{_esc(r["name"])}</b></span></th>'
                f'<td>{r["p"]}</td><td class="wdl">{r["w"]}</td><td class="wdl">{r["d"]}</td>'
                f'<td class="wdl">{r["l"]}</td>{goals}'
                f'<td dir="ltr">{"+" if r["gd"] > 0 else ""}{r["gd"]}</td><td class="pts">{r["pts"]}</td></tr>')
        caption = t["league"] + (" — " + g["name"] if many and g["name"] else "")
        if many and g["name"]:
            out.append(f'<h3 class="lgroup">{_esc(g["name"])}</h3>')
        out.append(f'<div class="lwrap"><table class="standings"><caption class="sr">ترتيب {_esc(caption)}</caption>'
                   f'{head}<tbody>{"".join(body)}</tbody></table></div>')
    if seen:
        out.append('<ul class="zones">' + "".join(
            f'<li style="--z:{t["zones"][k]["color"]}">{_esc(t["zones"][k]["label"])}</li>' for k in seen) + "</ul>")
    return "".join(out)


def api(slug=None):
    """بطاقة الرئيسية: الجدول مختصرًا ومرسومًا، وقائمة الدوريات لأزرارها."""
    t = table(slug)
    if t is None:
        return None
    out = {k: t[k] for k in ("ok", "slug", "league", "page", "leagues")}
    if not t["ok"]:
        out["error"] = t["error"]
        return out
    out.update(season=t["season"], updated=t["updated"], html=(
        f'<p class="lname"><b>{_esc(t["league"])}</b>{_season(t)}</p>'
        + _tables_html(t, limit=PREVIEW)
        + f'<a class="lfull" href="{_esc(t["page"])}">جدول الترتيب الكامل ←</a>'))
    return out


def render(slug):
    """صفحة الدوري كاملة ← (رمز HTTP، بايتات)، أو None لمفتاح غير معروف.
    تعذّر الجلب = 503 بالصفحة نفسها ورسالة، فلا يُفهرس جدولٌ فارغ."""
    t = table(slug)
    if t is None:
        return None
    name, url, site = t["league"], guide_pages.SITE + t["page"], guide_pages.SITE
    season = f' {t["season"]}' if t.get("season") else ""
    title = f"جدول ترتيب {name}{season} | سمارت سوق"
    lead = ""
    if t["ok"] and len(t["groups"]) == 1 and t["groups"][0]["rows"][0]["p"]:
        top = t["groups"][0]["rows"][0]
        lead = (f" يتصدّر {top['name']} برصيد {_count(top['pts'], 'نقطة', 'نقطتين', 'نقاط', 'نقطة')}"
                f" بعد {_count(top['p'], 'مباراة', 'مباراتين', 'مباريات', 'مباراة')}.")
    desc = (f"جدول ترتيب {name}{season} محدَّثًا تلقائيًا: النقاط وعدد المباريات والفوز "
            f"والتعادل والخسارة والأهداف وفارقها لكل الفرق.{lead}")
    crumbs = {
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "دليل سمارت سوق", "item": site + "/"},
            {"@type": "ListItem", "position": 2, "name": f"جدول ترتيب {name}", "item": url},
        ],
    }
    tabs = "".join(
        f'<a href="{PATH}{k}"{" aria-current=page" if k == t["slug"] else ""}>{_esc(v["tab"])}</a>'
        for k, v in LEAGUES.items())
    if t["ok"]:
        body = (_tables_html(t) + f'<p class="lsrc">آخر تحديث: <time datetime="'
                f'{datetime.datetime.fromtimestamp(t["updated"], RIYADH).isoformat()}">{_when(t["updated"])}</time>'
                ' بتوقيت السعودية · يُحدَّث تلقائيًا · المصدر ESPN</p>')
    else:
        body = ('<p>تعذّر تحميل الترتيب الآن، ونعيد المحاولة تلقائيًا. حدّث الصفحة بعد دقائق، '
                'أو اختر دوريًا آخر من الأعلى.</p>')

    doc = f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
<meta name="description" content="{_esc(desc)}">
<meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1">
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
<link rel="preconnect" href="{LOGO_HOST}">
<script type="application/ld+json">{json.dumps(crumbs, ensure_ascii=False)}</script>
<style>{guide_pages._style()}
nav.crumb{{font-size:14px;opacity:.75;margin:0 0 14px}}
</style>
</head>
<body>
<main id="view">
<nav class="crumb"><a class="link" href="/">دليل سمارت سوق</a> ← جدول الترتيب</nav>
<h1>جدول ترتيب {_esc(name)}{_season(t)}</h1>
<p class="sub">ترتيب الفرق كما هو الآن: النقاط وعدد المباريات والفوز والتعادل والخسارة والأهداف.{_esc(lead)}</p>
<nav class="ltabs" aria-label="الدوريات">{tabs}</nav>
<section class="card league">
{body}
</section>
<section class="card">
<h2>اشتراكات IPTV من سمارت سوق</h2>
<p class="sub">أربع خطوات قصيرة ونرشّح لك الباقة الأنسب لك ولجهازك، ثم نشرح تفعيلها خطوة بخطوة.</p>
<div class="nav"><a class="btn go" href="/#buy">ساعدني في الاختيار</a><a class="btn ghost" href="/#plans">كل الباقات</a></div>
</section>
</main>
</body>
</html>"""
    return (200 if t["ok"] else 503), doc.encode("utf-8")

# -*- coding: utf-8 -*-
"""بلاغات المحتوى (‏/report): المشترك يبلّغ عن فيديو لا يعمل أو يقطع، ويراه الموظف في admin.ssouq.com/reports.

العميل يختار من ملفات M3U نفسها (‏content.py) خطوةً بعد خطوة، فلا يكتب اسمًا لا وجود له:
  السيرفر ← البحث باسم المسلسل أو الفيلم (وقبل الكتابة أحدث ما أضيف؛ ولكل نتيجةٍ قسمها، بلا ما أخفاه المدير)
  ← الموسم والحلقة (للمسلسل) ← المشكلة: «لا يعمل» أو «يقطع» أو «الحلقة ليست هي» (الفيلم ليس هو) أو «الترجمة غير صحيحة».
وما لم يجده يطلب إضافته (‏add): مسلسلٌ أو فيلم باسمٍ يكتبه، ويصل موظفي سيرفره كالبلاغ. (وخطوات القسم ثم عناصره باقيةٌ في الواجهة لرابط صفحة المحتوى.)
ورقم واتسابه وملاحظته اختياريان، ليُبلَّغ بعد الإصلاح.

والبلاغ يُطابَق بما في الفهرس (القسم والاسم والموسم) فلا يُحفظ إلا ما في السيرفر حقًّا. والبلاغ نفسه
(السيرفر والعنصر والموسم والحلقة والمشكلة) ما دام مفتوحًا لا يتكرّر: يزيد عدده ويُضاف رقم صاحبه، فيرى الموظف
سطرًا واحدًا لكل حلقةٍ معطّلة بعدد من بلّغ عنها. وحدّ المحاولات بالساعة لكل عنوان (مجزّأً لا مخزَّنًا).

الموظف حسابٌ في الأداة فتح له المدير «بلاغات المحتوى» من نافذة الحساب (‏reports في الحساب): يرى المفتوحة
والمنجزة، ويعلّم البلاغ «تم الإصلاح» أو يعيد فتحه، ويراسل صاحبه على واتساب. ولكل موظفٍ سيرفراته (‏reports_servers،
وبلا اختيارٍ كلها): لا يرى إلا بلاغاتها ولا يصله إلا تنبيهها، وللسيرفر الواحد موظفٌ أو أكثر. والمدير يرى الكل ويحذف.

وتنبيه واتساب بكل بلاغ (‏alert، في خيطٍ مستقل فلا ينتظره المشترك): من رقم المسابقة المربوط إلى كل موظفٍ
له رقمٌ ولم يوقفه، وإلى رقم المدير إن حفظه — بالاسم والحلقة والمشكلة والسيرفر والقسم، بلا رقم صاحبه ولا رابط.
والبلاغ المكرّر يُنبَّه به ثانيةً بعد نصف ساعة (بعدد من بلّغ) لا مع كل تكرار، وحدٌّ بالساعة لكل التنبيهات يحمي
الرقم من الحظر؛ وما لم يُرسل يبقى في الصفحة بسببه. والإرسال والمستلمون يضبطهما الخادم (‏sender · recipients).

التخزين: data/reports/reports.json — الأحدث أولًا، وبحدٍّ يُسقط أقدم المنجز ثم أقدم الكل؛ و‏settings.json برقم
المدير للتنبيه. بلا مكتبات خارجية.
"""
import hashlib
import json
import os
import re
import secrets
import threading
import time
import unicodedata

import content
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request

PATH = "/report"
DIR = "reports"
FILE = "reports.json"
PROBLEMS = {"down": "لا يعمل", "buffer": "يقطع", "wrong": "الحلقة ليست هي", "subs": "الترجمة غير صحيحة",
            "add": "طلب إضافة"}
ADD = "add"                  # طلب إضافة مسلسلٍ أو فيلمٍ ليس في السيرفر: اسمٌ يكتبه، لا عنصرٌ من الفهرس
KIND_ONE = {"series": "مسلسل", "movie": "فيلم", "live": "قناة"}
WRONG = {"series": "الحلقة ليست هي", "movie": "الفيلم ليس هو", "live": "القناة ليست هي"}
# بالإنجليزية: لصفحة البلاغ وصفحة الموظف وتنبيهه بلغته
PROBLEMS_EN = {"down": "Not working", "buffer": "Buffering", "wrong": "Wrong episode", "subs": "Wrong subtitles", "add": "Request to add"}
KIND_EN = {"series": "series", "movie": "movie", "live": "channel"}
WRONG_EN = {"series": "Wrong episode", "movie": "Wrong movie", "live": "Wrong channel"}
# لغة المسلسل أو الفيلم في طلب الإضافة (قائمةٌ في الصفحة، وتُعرف من رابطه): الرمز ← (بالعربية، بالإنجليزية)
LANGS = {"ar": ("عربي", "Arabic"), "en": ("إنجليزي", "English"), "tr": ("تركي", "Turkish"), "ko": ("كوري", "Korean"),
         "hi": ("هندي", "Hindi"), "es": ("إسباني", "Spanish"), "fr": ("فرنسي", "French"), "ja": ("ياباني", "Japanese"),
         "zh": ("صيني", "Chinese"), "fa": ("فارسي", "Persian"), "ur": ("أردو", "Urdu"), "de": ("ألماني", "German"),
         "it": ("إيطالي", "Italian"), "pt": ("برتغالي", "Portuguese"), "ru": ("روسي", "Russian"), "th": ("تايلندي", "Thai"),
         "other": ("لغة أخرى", "Other")}
LINK_MAX = 400
KINDS = ("series", "movie", "live")
KEEP = 3000                  # ما يُحفظ من البلاغات، والمنجز الأقدم يُسقط أولًا
PEOPLE_MAX = 30              # أصحاب البلاغ الواحد (بأرقامهم) — والباقي عددٌ في ‏count
NOTE_MAX = 300
EP_MAX = 9999
ITEMS_PAGE = 120             # عناصر القسم في الصفحة الواحدة وفي كل «المزيد»
SEARCH_MAX = 30
RATE = int(os.environ.get("REPORT_RATE_PER_HOUR", "10") or 10)   # بلاغاتٌ بالساعة لكل عنوان

_lock = threading.RLock()
_rate = {}                   # بصمة العنوان:الساعة ← العدد

# تنبيه واتساب — يضبطهما الخادم (xm_lines)، وبدونهما لا تنبيه:
sender = None                # (الرقم، النص) ← {ok, error}: من رقم المسابقة
recipients = None            # (البلاغ) ← [(الاسم، الرقم)] من يصله تنبيه سيرفره الآن
ALERT_AGAIN = 30 * 60        # البلاغ المكرّر يُنبَّه به ثانيةً بعدها، لا مع كل تكرار
ALERT_HOUR_MAX = int(os.environ.get("REPORT_ALERTS_PER_HOUR", "30") or 30)   # تنبيهاتٌ بالساعة، لكل المستلمين
_alerts = {}                 # الساعة ← عدد البلاغات التي نُبّه بها


def _path(data_dir):
    return os.path.join(data_dir, DIR, FILE)


def _load(data_dir):
    try:
        with open(_path(data_dir), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("items"), list) else {"items": []}
    except (OSError, ValueError):
        return {"items": []}


def _save(data_dir, d):
    p = _path(data_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = f"{p}.{secrets.token_hex(4)}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, p)


def rate_ok(ip, limit=None, now=None):
    """حدّ البلاغات بالساعة لكل عنوان — بصمته لا هو، وفي الذاكرة: ساعةٌ واحدة تكفي."""
    if not ip:
        return True
    hour = int((now or time.time()) // 3600)
    k = hashlib.sha256(str(ip).encode()).hexdigest()[:16] + ":" + str(hour)
    with _lock:
        for old in [x for x in _rate if not x.endswith(":" + str(hour))]:
            _rate.pop(old, None)
        _rate[k] = _rate.get(k, 0) + 1
        return _rate[k] <= (RATE if limit is None else limit)


# ================= ما يختار منه العميل =================
def _img(key, it):
    return content.img_src(key, it.get("p"), "w185")


def servers(data_dir):
    """السيرفرات التي لها محتوى — الخطوة الأولى."""
    en = {s["key"]: content.en_name(s) for s in content.servers(data_dir)}
    return {"ok": True, "servers": [{"key": s["key"], "name": s["name"], "en": en.get(s["key"], s["name"])}
                                    for s in content.brief(data_dir)["servers"]]}


def _view(data_dir, key):
    srv, v = content._view(data_dir, content.key_ok(key)) if content.key_ok(key) else (None, None)
    return (srv, v) if srv and v and content._has(v) else (None, None)


def groups(data_dir, key):
    """أقسام السيرفر الظاهرة لكل نوع بعدد ما فيها ← None بلا سيرفر."""
    srv, v = _view(data_dir, key)
    if not v:
        return None
    return {"ok": True, "server": {"key": srv["key"], "name": srv["name"]},
            "kinds": {k: [{"id": g["id"], "name": g["name"], "n": len(g["items"])} for g in v["kinds"][k]]
                      for k in KINDS}}


def _seasons(it):
    return [[int(s), int(n)] for s, n in it.get("s") or () if isinstance(s, int) and isinstance(n, int)]


def _item(key, kind, it, gname=""):
    d = {"n": it.get("n", ""), "y": it.get("y") or 0, "p": _img(key, it)}
    if kind == "series":
        d["s"] = _seasons(it)
    if gname:
        d["g"] = gname
    return d


def items(data_dir, key, kind, gid, q="", page=0):
    """عناصر القسم، الأحدث أولًا (كصفحة المحتوى)، و‏q يرشّحها بالاسم ← None بلا قسم."""
    srv, v = _view(data_dir, key)
    if not v or kind not in KINDS or gid not in v["byid"][kind]:
        return None
    g = v["kinds"][kind][v["byid"][kind][gid]]
    words = content._norm(q).split()
    picks = [(gi, ii) for gi, ii in content.select(v, kind, gid)
             if not words or all(w in content._norm(g["items"][ii].get("n", "")) for w in words)]
    page = _int(page, 0, 10 ** 5) or 0
    rows = picks[page * ITEMS_PAGE:(page + 1) * ITEMS_PAGE]
    return {"ok": True, "group": {"id": gid, "name": g["name"]}, "total": len(picks),
            "more": len(picks) > (page + 1) * ITEMS_PAGE,
            "items": [_item(srv["key"], kind, g["items"][ii]) for _, ii in rows]}


def _hit(srv, v, kind, gi, ii):
    g = v["kinds"][kind][gi]
    return dict(_item(srv["key"], kind, g["items"][ii], g["name"]), k=kind, gid=g["id"])


def search(data_dir, key, q):
    """البحث باسم المسلسل أو الفيلم في السيرفر كله، بلا اختيار القسم ← {total, items} أو None بلا سيرفر. ولكلّ نتيجةٍ
    قسمها، والاسم في قسمين نتيجتان (لا كبحث صفحة المحتوى): المدبلج والمترجم من المسلسل نفسه قد يعمل أحدهما ولا يعمل
    الآخر. والمطابق تمامًا أولًا ثم ما يبدأ بالكلمة ثم ما فيه، والمسلسلات قبل الأفلام في كلٍّ منها."""
    srv, v = _view(data_dir, key)
    if not v:
        return None
    words = content._words(str(q or "")[:content.QUERY_MAX])
    if not words:
        return {"ok": True, "total": 0, "items": []}
    full = " ".join(words)
    tiers, total = ([], [], []), 0
    for kind in content.SEARCH_KINDS:
        for norm, gi, ii in v["index"][kind]:
            if all(w in norm for w in words):
                total += 1
                t = tiers[0 if norm == full else 1 if norm.startswith(full) else 2]
                if len(t) < SEARCH_MAX:
                    t.append((kind, gi, ii))
    hits = (tiers[0] + tiers[1] + tiers[2])[:SEARCH_MAX]
    return {"ok": True, "total": total, "items": [_hit(srv, v, *h) for h in hits]}


_ARTICLE = re.compile(r"^(the|a|an) ")
EXISTS_MAX = 6


def _bare(norm):
    """الاسم للمطابقة: بلا «The» أوله (‏«The Batman» و«Batman» واحد)."""
    return _ARTICLE.sub("", norm)


def exists(data_dir, key, name, kind="", year=0):
    """هل ما يطلب إضافته موجودٌ في السيرفر؟ ← {total, items} (‏items كنتائج البحث) أو None بلا سيرفر. الاسم نفسه
    (بلا تشكيل ولا رموز ولا «The»)، وبنوعه إن عُرف، وبسنته إن عُرفت هي وسنة العنصر (والفرق سنةٌ واحدة يُقبل: تاريخ
    العرض يختلف بين البلدان) — فلا يقول «موجود» لفيلمٍ أعيد إنتاجه باسمه."""
    srv, v = _view(data_dir, key)
    if not v:
        return None
    want = _bare(" ".join(content._words(str(name or "")[:content.NAME_MAX])))
    year = _int(year, 1900, 2100) or 0
    if len(want.replace(" ", "")) < 2:
        return {"ok": True, "total": 0, "items": []}
    hits, total = [], 0
    for k in [kind] if kind in content.SEARCH_KINDS else content.SEARCH_KINDS:
        for norm, gi, ii in v["index"][k]:
            if want not in norm:                            # سريعٌ قبل المطابقة نفسها
                continue
            it = v["kinds"][k][gi]["items"][ii]
            y = it.get("y") or 0
            if _bare(norm[:-len(str(y)) - 1] if y else norm) != want or (year and y and abs(year - y) > 1):
                continue
            total += 1
            if len(hits) < EXISTS_MAX:
                hits.append((k, gi, ii))
    return {"ok": True, "total": total, "items": [_hit(srv, v, *h) for h in hits]}


def recent(data_dir, key, n=18):
    """أحدث ما أضيف من مسلسلاتٍ وأفلام (بتاريخ الواجهة، وإلا برقم العنصر) — تحت البحث قبل أن يكتب شيئًا."""
    srv, v = _view(data_dir, key)
    if not v:
        return None
    rank = lambda h: (lambda it: (it.get("a") or 0, it.get("i") or 0))(v["kinds"][h[0]][h[1]]["items"][h[2]])  # noqa: E731
    hits = sorted([(kind, gi, ii) for kind in content.SEARCH_KINDS for gi, ii in v["recent"][kind][:n]], key=rank, reverse=True)
    return {"ok": True, "items": [_hit(srv, v, *h) for h in hits[:n]]}


# ================= البلاغ =================
_DIG = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_CTRL = re.compile(r"[\u0000-\u0008\u000b-\u001f\u007f​-‏‪-‮⁦-⁩]")


class Invalid(ValueError):
    """بلاغٌ لا يُقبل — ورسالته للعميل كما هي، بالعربية (‏str) وبالإنجليزية (‏en) لصفحة البلاغ الإنجليزية."""

    def __init__(self, ar, en=""):
        super().__init__(ar)
        self.en = en or ar


def phone_of(v):
    """رقم واتساب بصيغته الدولية أرقامًا («0551234567» ← 966551234567) ← "" بلا رقم، وInvalid لرقمٍ لا يصلح."""
    s = re.sub(r"[\s\-().+]", "", str(v or "").translate(_DIG))
    if not s:
        return ""
    if not s.isdigit():
        raise Invalid("رقم الواتساب أرقامٌ فقط", "The WhatsApp number must be digits only")
    s = s[2:] if s.startswith("00") else s
    if len(s) == 10 and s.startswith("05"):
        s = "966" + s[1:]
    elif len(s) == 9 and s.startswith("5"):
        s = "966" + s
    if not 8 <= len(s) <= 15:
        raise Invalid("رقم الواتساب غير صحيح — اكتبه كما في واتساب: 05xxxxxxxx", "Invalid WhatsApp number — write it as in WhatsApp, with the country code")
    return s


def _text(v, limit):
    s = unicodedata.normalize("NFC", _CTRL.sub("", str(v or "")))
    return " ".join(s.split())[:limit]


def _int(v, lo, hi):
    try:
        n = int(str(v).translate(_DIG).strip())
    except (TypeError, ValueError):
        return None
    return n if lo <= n <= hi else None


def _find(v, kind, gid, name, year):
    """العنصر في قسمه باسمه (وسنته للفيلم) ← (القسم، العنصر) أو (None، None)."""
    if kind not in KINDS or gid not in v["byid"][kind]:
        return None, None
    g = v["kinds"][kind][v["byid"][kind][gid]]
    want = content._norm(name)
    hits = [it for it in g["items"] if content._norm(it.get("n", "")) == want]
    if kind == "movie" and len(hits) > 1:
        hits = [it for it in hits if (it.get("y") or 0) == year] or hits
    return (g, hits[0]) if want and hits else (g, None)


def _mark(r):
    """بصمة البلاغ: ما دام مفتوحًا لا يُكرَّر، بل يزيد عدده."""
    return "|".join(str(x) for x in (r["server"], r["kind"], content._norm(r["title"]), r["year"],
                                       r["season"], r["ep"], r["problem"]))


def problem_name(problem, kind="", lang="ar"):
    """اسم المشكلة كما يُعرض: «الحلقة ليست هي» للمسلسل و«الفيلم ليس هو» للفيلم، و«طلب إضافة مسلسل» — وبالإنجليزية."""
    en = lang == "en"
    if problem == "wrong":
        return (WRONG_EN if en else WRONG).get(kind, (PROBLEMS_EN if en else PROBLEMS)["wrong"])
    if problem == ADD:
        return f"Request to add a {KIND_EN.get(kind, '')}".strip() if en else f"طلب إضافة {KIND_ONE.get(kind, '')}".strip()
    return (PROBLEMS_EN if en else PROBLEMS).get(problem, "")


def link_of(v):
    """رابط المسلسل أو الفيلم كما لصقه ← "" بلا رابط، وInvalid لما ليس رابط http(s)."""
    s = str(v or "").strip()
    if not s:
        return ""
    u = urlsplit(s)
    if u.scheme not in ("http", "https") or not u.hostname or len(s) > LINK_MAX or re.search(r"[\s<>\"']", s):
        raise Invalid("الرابط غير صحيح — الصقه كما هو من المتصفح", "Invalid link — paste it as it is from the browser")
    return s


def _request(srv, form):
    """طلب إضافة: النوع والاسم كما كتبه، والسنة ولغته من قائمتيهما ورابطه إن وضعه — لا يُطابَق بالفهرس، فما يطلبه ليس فيه."""
    kind = str(form.get("t") or "")
    if kind not in ("series", "movie"):
        raise Invalid("اختر: مسلسل أو فيلم", "Choose: series or movie")
    name = _text(form.get("n"), content.NAME_MAX)
    if len(name.replace(" ", "")) < 2:
        raise Invalid("اكتب اسم المسلسل أو الفيلم", "Write the series or movie name")
    cl = str(form.get("cl") or "")
    return {"server": srv["key"], "sname": srv["name"], "sname_en": content.en_name(srv), "kind": kind, "gid": "", "group": "", "title": name,
            "year": _int(form.get("y"), 1900, 2100) or 0, "season": None, "ep": None, "problem": ADD, "p": "",
            "cl": cl if cl in LANGS else "", "link": link_of(form.get("link"))}


def submit(data_dir, form, now=None):
    """بلاغٌ أو طلب إضافة من الصفحة ← (البلاغ، جديد؟). وInvalid بما لا يُقبل."""
    form = form if isinstance(form, dict) else {}
    srv, v = _view(data_dir, form.get("s"))
    if not v:
        raise Invalid("اختر السيرفر من القائمة", "Choose the server from the list")
    kind = str(form.get("t") or "")
    problem = str(form.get("problem") or "")
    if problem not in PROBLEMS:
        raise Invalid("اختر المشكلة", "Choose the problem")
    if problem == ADD:
        return _store(data_dir, _request(srv, form), form, now)
    g, it = _find(v, kind, str(form.get("g") or ""), _text(form.get("n"), content.NAME_MAX),
                  _int(form.get("y"), 0, 3000) or 0)
    if g is None:
        raise Invalid("اختر القسم من القائمة", "Choose the category from the list")
    if it is None:
        raise Invalid("اختر المسلسل أو الفيلم من القائمة", "Choose the series or movie from the list")
    season = ep = None
    if kind == "series":
        seasons = [s for s, _ in _seasons(it)]
        season = _int(form.get("season"), 0, 999)
        if seasons and season not in seasons:
            raise Invalid("اختر الموسم", "Choose the season")
        ep = _int(form.get("ep"), 0, EP_MAX)           # ‏0 = الحلقات كلها
        if ep is None:
            raise Invalid("اختر الحلقة", "Choose the episode")
    rec = {"server": srv["key"], "sname": srv["name"], "sname_en": content.en_name(srv), "kind": kind, "gid": g["id"], "group": g["name"],
           "title": it.get("n", ""), "year": it.get("y") or 0, "season": season, "ep": ep, "problem": problem,
           "p": _img(srv["key"], it)}
    return _store(data_dir, rec, form, now)


def _store(data_dir, rec, form, now=None):
    """يحفظ البلاغ، أو يضمّه إلى مثله المفتوح (يزيد عدده ويُضاف رقم صاحبه) ← (البلاغ، جديد؟)."""
    phone = phone_of(form.get("phone"))
    note = _text(form.get("note"), NOTE_MAX)
    now = now or time.time()
    lang = "en" if form.get("lang") == "en" else "ar"          # لغة صفحته: بها رسالة «تم الإصلاح» إليه
    rec["lang"] = lang
    person = {"at": int(now), "phone": phone, "note": note, "lang": lang}
    with _lock:
        d = _load(data_dir)
        mark = _mark(rec)
        old = next((r for r in d["items"] if r.get("state") == "open" and _mark(r) == mark), None)
        if old:
            old["count"] = int(old.get("count") or 1) + 1
            old["last"] = int(now)
            people = old.setdefault("people", [])
            same = next((x for x in people if phone and x.get("phone") == phone), None)
            if same:                                    # صاحب الرقم نفسه: ملاحظته الأحدث
                if note:
                    same.update(at=int(now), note=note)
            elif (phone or note) and len(people) < PEOPLE_MAX \
                    and not any(not phone and not x.get("phone") and x.get("note") == note for x in people):
                people.append(person)
            d["items"].remove(old)
            d["items"].insert(0, old)                   # الأحدث بلاغًا أولًا
            _save(data_dir, d)
            return dict(old), False
        rec.update(id=secrets.token_hex(5), at=int(now), last=int(now), state="open", count=1,
                   people=[person] if (phone or note) else [])
        d["items"].insert(0, rec)
        if len(d["items"]) > KEEP:
            done = [r for r in d["items"] if r.get("state") != "open"]
            drop = {id(r) for r in done[-(len(d["items"]) - KEEP):]}
            d["items"] = [r for r in d["items"] if id(r) not in drop][:KEEP]
        _save(data_dir, d)
        return dict(rec), True


def label(r):
    """«Breaking Bad · الموسم 2 · الحلقة 5 — يقطع»، و«Shogun — طلب إضافة مسلسل» — للموظف ولرسالة واتساب."""
    bits = [r.get("title", "") + (f" ({r['year']})" if r.get("year") else "")]
    if r.get("kind") == "series" and r.get("problem") != ADD:
        if r.get("season"):
            bits.append(f"الموسم {r['season']}")
        bits.append("كل الحلقات" if not r.get("ep") else f"الحلقة {r['ep']}")
    return " · ".join(bits) + " — " + problem_name(r.get("problem"), r.get("kind"))


# ================= للموظف =================
def listing(data_dir, state="open", server="", only=None, what=""):
    """البلاغات للموظف: ‏open المفتوحة، ‏done المنجزة، ‏all الكل — بأعدادها لكل حالٍ ولكل سيرفر. و‏only سيرفرات الموظف
    (‏None = كلها): لا يرى غيرها ولا يُعدّ. و‏what: ‏issue المشاكل وحدها، ‏add طلبات الإضافة وحدها (وأعداد المفتوح منهما)."""
    with _lock:
        rows = _load(data_dir)["items"]
    if only is not None:
        rows = [r for r in rows if r.get("server") in only]
    counts = {"open": 0, "done": 0, "issue": 0, "add": 0}
    by_server = {}
    for r in rows:
        st = "open" if r.get("state") == "open" else "done"
        if st == "open":
            counts["add" if r.get("problem") == ADD else "issue"] += 1
        if what and (r.get("problem") == ADD) != (what == "add"):
            continue
        counts[st] += 1
        if st == "open":
            s = by_server.setdefault(r.get("server", ""), {"key": r.get("server", ""), "name": r.get("sname", ""), "open": 0})
            s["open"] += 1
    pick = [r for r in rows if (state == "all" or (r.get("state") == "open") == (state != "done"))
            and (not server or r.get("server") == server)]
    return {"ok": True, "counts": counts, "servers": sorted(by_server.values(), key=lambda s: -s["open"]),
            "problems": PROBLEMS, "items": [dict(r, label=label(r), ptext=problem_name(r.get("problem"), r.get("kind")))
                                            for r in pick if not what or (r.get("problem") == ADD) == (what == "add")]}


def set_state(data_dir, rid, done, by="", reply="", now=None):
    """«تم الإصلاح» (‏done) أو إعادة الفتح ← البلاغ أو None."""
    with _lock:
        d = _load(data_dir)
        r = next((x for x in d["items"] if x.get("id") == rid), None)
        if not r:
            return None
        if done:
            r.update(state="done", done_at=int(now or time.time()), done_by=str(by)[:60], reply=_text(reply, NOTE_MAX))
        else:
            r["state"] = "open"
            for k in ("done_at", "done_by", "reply"):
                r.pop(k, None)
            mark = _mark(r)                              # ومفتوحٌ مثله: يُضمّ إليه فلا يتكرّر
            twin = next((x for x in d["items"] if x is not r and x.get("state") == "open" and _mark(x) == mark), None)
            if twin:
                twin["count"] = int(twin.get("count") or 1) + int(r.get("count") or 1)
                twin["people"] = (twin.get("people") or []) + [p for p in r.get("people") or []
                                                               if not p.get("phone") or all(p["phone"] != q.get("phone")
                                                                                            for q in twin.get("people") or [])]
                twin["people"] = twin["people"][:PEOPLE_MAX]
                twin["at"] = min(int(twin.get("at") or 0), int(r.get("at") or 0)) or twin.get("at")
                d["items"].remove(r)
                r = twin
        _save(data_dir, d)
        return dict(r)


def get(data_dir, rid):
    """البلاغ برقمه ← نسخةٌ منه أو None (لمعرفة سيرفره قبل أن يمسّه موظف)."""
    with _lock:
        r = next((x for x in _load(data_dir)["items"] if x.get("id") == rid), None)
    return dict(r) if r else None


def remove(data_dir, rid):
    with _lock:
        d = _load(data_dir)
        n = len(d["items"])
        d["items"] = [x for x in d["items"] if x.get("id") != rid]
        if len(d["items"]) == n:
            return False
        _save(data_dir, d)
        return True


def open_count(data_dir):
    with _lock:
        return sum(1 for r in _load(data_dir)["items"] if r.get("state") == "open")


# ================= تنبيه واتساب =================
SETTINGS = "settings.json"


def _settings_path(data_dir):
    return os.path.join(data_dir, DIR, SETTINGS)


def settings(data_dir):
    """رقم المدير للتنبيه ← {wa, on}."""
    try:
        with open(_settings_path(data_dir), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    d = d if isinstance(d, dict) else {}
    return {"wa": str(d.get("wa") or ""), "on": d.get("on") is not False, "lang": "en" if d.get("lang") == "en" else ""}


def save_lang(data_dir, lang):
    """لغة صفحة المدير وتنبيهاته."""
    d = settings(data_dir)
    return _save_settings(data_dir, dict(d, lang="en" if lang == "en" else "ar"))


def save_settings(data_dir, wa, on=True):
    """يحفظ رقم المدير ← الإعداد، وInvalid لرقمٍ لا يصلح."""
    return _save_settings(data_dir, dict(settings(data_dir), wa=phone_of(wa), on=bool(on)))


def _save_settings(data_dir, d):
    p = _settings_path(data_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with _lock:
        tmp = f"{p}.{secrets.token_hex(4)}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, p)
    return d


def alert_text_en(r, new):
    """التنبيه بالإنجليزية لمن اختارها في صفحته."""
    w = content._wa
    n, srv = int(r.get("count") or 1), w(r.get("sname_en") or r.get("sname"))
    title = w(r.get("title")) + (f" ({r['year']})" if r.get("year") else "")
    if r.get("problem") == ADD:
        kind = KIND_EN.get(r.get("kind"), "")
        head = (f"🙋 *Request to add a {kind} on {srv}*" if new else f"🔁 *Request to add a {kind} on {srv}* — {n} subscribers asked")
        lines = [head, "", f"🎬 {title}"] + ([f"🌐 {LANGS[r['cl']][1]}"] if r.get("cl") in LANGS else []) \
            + ([f"🔗 {r['link']}"] if r.get("link") else [])
    else:
        prob = problem_name(r.get("problem"), r.get("kind"), "en")
        head = (f"🔔 *New report on {srv}: {prob}*" if new else f"🔁 *Repeated report on {srv}: {prob}* ({n} reports)")
        ep = ""
        if r.get("kind") == "series":
            ep = (f" · S{r['season']}" if r.get("season") else "") + (f" · E{r['ep']}" if r.get("ep") else " · all episodes")
        lines = [head, "", f"🎬 {title}{ep}", f"📂 {KIND_EN.get(r.get('kind'), '')} · {w(r.get('group'))}"]
    return "\n".join(lines)


def alert_text(r, new, lang="ar"):
    """نصّ التنبيه بخطّ واتساب العريض — وأول كل سطرٍ فيه اسمٌ علامة RLM فيبقى من اليمين وإن بدأ بإنجليزي.
    بلا رقم صاحبه ولا ملاحظته ولا رابط الصفحة: كلها في صفحة البلاغات."""
    if lang == "en":
        return alert_text_en(r, new)
    w, rlm = content._wa, "\u200f"
    n, srv = int(r.get("count") or 1), w(r.get("sname"))
    title = w(r.get("title")) + (f" ({r['year']})" if r.get("year") else "")
    if r.get("problem") == ADD:                        # طلب إضافة: الاسم كما كتبه، بلا قسمٍ ولا حلقة
        kind = KIND_ONE.get(r.get("kind"), "")
        head = (f"🙋 *طلب إضافة {kind} في {srv}*" if new else f"🔁 *طلب إضافة {kind} في {srv}* — طلبه {n} مشتركين")
        lines = [head, "", f"{rlm}🎬 {title}"] + ([f"{rlm}🌐 {LANGS[r['cl']][0]}"] if r.get("cl") in LANGS else []) \
            + ([f"🔗 {r['link']}"] if r.get("link") else [])
    else:
        prob = problem_name(r.get("problem"), r.get("kind"))
        head = (f"🔔 *بلاغ جديد في {srv}: {prob}*" if new else f"🔁 *بلاغٌ متكرّر في {srv}: {prob}* ({n} بلاغات)")
        ep = ""
        if r.get("kind") == "series":
            ep = (f" · الموسم {r['season']}" if r.get("season") else "") + (f" · الحلقة {r['ep']}" if r.get("ep") else " · كل الحلقات")
        lines = [head, "", f"{rlm}🎬 {title}{ep}", f"{rlm}📂 {KIND_ONE.get(r.get('kind'), '')} · {w(r.get('group'))}"]
    return "\n".join(lines)


def _record_alert(data_dir, rid, res):
    with _lock:
        d = _load(data_dir)
        r = next((x for x in d["items"] if x.get("id") == rid), None)
        if r is not None:
            r["wa"] = res
            _save(data_dir, d)


def alert(data_dir, r, new, now=None):
    """ينبّه الموظفين بالبلاغ ← ما جرى {at, to, sent, error} ويُحفظ معه، أو None إن لم يحن (المكرّر قبل نصف ساعة)
    أو لم يُضبط الإرسال."""
    if not sender or not recipients:
        return None
    now = now or time.time()
    last = (r.get("wa") or {}).get("at") or 0
    if not new and last and now - last < ALERT_AGAIN:
        return None
    try:
        rcpt, seen = [], set()
        for name, wa, *more in recipients(r) or ():       # (الاسم، الرقم[، لغته])
            if wa and wa not in seen:
                seen.add(wa)
                rcpt.append((name, wa, more[0] if more else "ar"))
    except Exception as e:  # noqa: BLE001 — لا يُسقط البلاغ
        rcpt, err = [], str(e)[:200]
    else:
        err = "" if rcpt else f"لا أحد يصله تنبيه {r.get('sname') or 'هذا السيرفر'} — أضف رقمًا لموظفه أو رقمك"
    res = {"at": int(now), "to": len(rcpt), "sent": 0, "error": err}
    if rcpt:
        hour = int(now // 3600)
        with _lock:
            for h in [h for h in _alerts if h != hour]:
                _alerts.pop(h, None)
            over = _alerts.get(hour, 0) >= ALERT_HOUR_MAX
            if not over:
                _alerts[hour] = _alerts.get(hour, 0) + 1
        if over:
            res["error"] = f"تجاوز حدّ التنبيهات بالساعة ({ALERT_HOUR_MAX}) — البلاغ محفوظ هنا"
        else:
            texts, errs = {}, []
            for name, wa, lang in rcpt:
                text = texts.get(lang) or texts.setdefault(lang, alert_text(r, new, lang))
                try:
                    out = sender(wa, text) or {}
                except Exception as e:  # noqa: BLE001
                    out = {"ok": False, "error": str(e)}
                if out.get("ok"):
                    res["sent"] += 1
                else:
                    errs.append(f"{name}: {out.get('error') or 'تعذّر الإرسال'}")
            res["error"] = " · ".join(errs)[:300]
    _record_alert(data_dir, r["id"], res)
    return res


# ================= تحديثٌ لصاحب البلاغ =================
UPDATE_MAX = 600             # نصّ التحديث
UPDATES_KEEP = 20            # ما يُحفظ من تحديثات البلاغ الواحد


def _msg(v, limit):
    """نصّ رسالةٍ بأسطره: بلا رموز تحكّم، وكل سطرٍ بمسافاتٍ مفردة، وبلا أسطرٍ فارغةٍ متتالية."""
    lines = [" ".join(_CTRL.sub("", unicodedata.normalize("NFC", ln)).split()) for ln in str(v or "").splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()[:limit]


def notify(data_dir, rid, text, by="", now=None):
    """يرسل التحديث (تم الإصلاح، أو نعمل عليه) إلى أصحاب البلاغ على واتساب، كلُّ رقمٍ مرة ← {at, by, to, sent, error, text}،
    ويُحفظ مع البلاغ (آخر ‏UPDATES_KEEP). وInvalid بلا نصٍّ أو بلا أرقام."""
    r = get(data_dir, rid)
    if not r:
        raise Invalid("لا بلاغ بهذا الرقم", "No such report")
    text = _msg(text, UPDATE_MAX)
    if not text:
        raise Invalid("اكتب نصّ الرسالة", "Write the message")
    phones = list(dict.fromkeys(p["phone"] for p in r.get("people") or [] if p.get("phone")))
    if not phones:
        raise Invalid("لا أرقام لأصحاب هذا البلاغ — لم يكتب أحدهم رقمه", "No numbers for this report — nobody left one")
    up = {"at": int(now or time.time()), "by": str(by)[:60], "to": len(phones), "sent": 0, "error": "", "text": text}
    errs = []
    for wa in phones:
        try:
            out = (sender(wa, text) if sender else {"ok": False, "error": "الإرسال غير مضبوط"}) or {}
        except Exception as e:  # noqa: BLE001
            out = {"ok": False, "error": str(e)}
        if out.get("ok"):
            up["sent"] += 1
        else:
            errs.append(f"+{wa}: {out.get('error') or 'تعذّر الإرسال'}")
    up["error"] = " · ".join(dict.fromkeys(errs))[:300]
    with _lock:
        d = _load(data_dir)
        rec = next((x for x in d["items"] if x.get("id") == rid), None)
        if rec is not None:
            rec["updates"] = ((rec.get("updates") or []) + [up])[-UPDATES_KEEP:]
            _save(data_dir, d)
    return up


# ================= رابط المسلسل أو الفيلم: يعبّئ طلب الإضافة وحده =================
# يُقرأ من الصفحة نفسها ما تعلنه للمحركات: JSON-LD (‏@type ‏Movie · TVSeries، والاسم وتاريخه ولغته)، ثم Open Graph (‏og:title
# ‏og:type)، ثم <title> — كما في IMDb و TMDB و Letterboxd وأغلب مواقع الأفلام. وطلب الرابط من خادمنا بحرص: عنوانٌ عام وحده
# (‏content._public_host، والتحويل يُفحص كذلك)، ومهلةٌ قصيرة، وأولُ 1.5 MB، وحدٌّ بالساعة لكل عنوان.
LOOKUP_MAX = 1536 * 1024
LOOKUP_TIMEOUT = 8
LOOKUP_RATE = 30                  # قراءة روابط بالساعة لكل عنوان
UA_BROWSER = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
# IMDb يحجب طلب صفحاته من الخوادم (‏202 بصفحة تحقّقٍ فارغة)، فرابطه يُقرأ من بيانات عنوانه العامة (اسمه وسنته ونوعه —
# ما يقترحه بحث IMDb نفسه)، ولغته الأصلية برقم IMDb: للمسلسل من TVmaze، ولغيره (أو إن لم يعرفه) من Wikidata ‏(P345 ← P364).
# والعناوين الثلاثة قابلةٌ للتغيير لاختبارٍ بلا شبكة.
IMDB_API = os.environ.get("REPORT_IMDB_API") or "https://v3.sg.media-imdb.com/suggestion/x/{id}.json"
TVMAZE_API = os.environ.get("REPORT_TVMAZE_API") or "https://api.tvmaze.com/lookup/shows?imdb={id}"
WIKIDATA_API = os.environ.get("REPORT_WIKIDATA_API") or "https://query.wikidata.org/sparql"
UA_BOT = "ssouq-guide/1.0 (https://guide.ssouq.com)"        # Wikidata تطلب تعريفًا بمن يسأل
JSON_MAX = 256 * 1024
_IMDB_ID = re.compile(r"/title/(tt\d{6,10})(?:[/?#]|$)")
_IMDB_KIND = {"movie": "movie", "tvMovie": "movie", "short": "movie", "tvShort": "movie", "video": "movie",
              "tvSeries": "series", "tvMiniSeries": "series", "tvSpecial": "series"}
_ISO3 = {"ara": "ar", "arb": "ar", "arz": "ar", "apc": "ar", "ajp": "ar", "afb": "ar", "acm": "ar", "ary": "ar", "aeb": "ar",
         "cmn": "zh", "yue": "zh", "pes": "fa", "prs": "fa"}
_lookups = {}
# اسم اللغة كما تكتبه المواقع ← رمزها في LANGS
_LANG_NAMES = {"arabic": "ar", "english": "en", "turkish": "tr", "korean": "ko", "hindi": "hi", "spanish": "es", "castilian": "es",
               "french": "fr", "japanese": "ja", "chinese": "zh", "mandarin": "zh", "cantonese": "zh", "persian": "fa", "farsi": "fa",
               "urdu": "ur", "german": "de", "italian": "it", "portuguese": "pt", "russian": "ru", "thai": "th"}
_SITE_TAIL = re.compile(r"\s+[-—|·:]\s+(IMDb|TMDB|The Movie Database.*|Letterboxd|Netflix|Wikipedia.*|ويكيبيديا.*|Shahid|شاهد|"
                        r"OSN\+?|Prime Video|Apple TV\+?|elCinema.*|السينما\.كوم.*)\s*$", re.I)
_TV_HINT = re.compile(r"\b(TV (Mini )?Series|TV Show|Series|Season)\b|مسلسل", re.I)
_YEAR = re.compile(r"\b(19[0-9]{2}|20[0-9]{2})\b")


def _lang_code(v):
    """«English» أو «en» أو «en-US» أو {name: …} ← رمز اللغة في LANGS، أو ""."""
    if isinstance(v, dict):
        v = v.get("name") or v.get("alternateName") or ""
    if isinstance(v, list):
        return next((c for c in (_lang_code(x) for x in v) if c), "")
    s = str(v or "").strip().lower()
    code = s.split("-")[0].split("_")[0]
    if code in LANGS and code != "other":
        return code
    return next((c for name, c in _LANG_NAMES.items() if s.startswith(name)), "")


def _ld_items(html):
    out = []
    for m in re.finditer(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            d = json.loads(m.group(1).strip())
        except ValueError:
            continue
        stack = d if isinstance(d, list) else [d]
        while stack:
            x = stack.pop(0)
            if isinstance(x, dict):
                out.append(x)
                stack.extend(x.get("@graph") or [])
    return out


def _meta(html, prop):
    for pat in (r'<meta[^>]+(?:property|name)=["\']%s["\'][^>]*content=["\']([^"\']*)["\']',
                r'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']%s["\']'):
        m = re.search(pat % re.escape(prop), html, re.I)
        if m:
            return _unescape(m.group(1))
    return ""


def _unescape(s):
    import html as _h
    return " ".join(_h.unescape(s or "").split())


def parse_page(html, url=""):
    """صفحة المسلسل أو الفيلم ← {kind, name, year, lang} (ما عُرف منها، والفارغ لما لم يُعرف)."""
    out = {"kind": "", "name": "", "year": 0, "lang": ""}
    path = urlsplit(url).path.lower()
    if re.search(r"/(tv|series|show|shows|tv-shows?)/", path + "/"):
        out["kind"] = "series"
    elif re.search(r"/(movie|movies|film|films)/", path + "/"):
        out["kind"] = "movie"
    for x in _ld_items(html):
        t = x.get("@type")
        t = " ".join(t) if isinstance(t, list) else str(t or "")
        if not re.search(r"Movie|TVSeries|TVSeason|TVEpisode|CreativeWorkSeries", t):
            continue
        out["kind"] = out["kind"] or ("movie" if "Movie" in t else "series")
        out["name"] = out["name"] or _unescape(str(x.get("name") or ""))
        m = _YEAR.search(str(x.get("datePublished") or x.get("startDate") or x.get("dateCreated") or ""))
        out["year"] = out["year"] or (int(m.group(1)) if m else 0)
        out["lang"] = out["lang"] or _lang_code(x.get("inLanguage"))
    og_type = _meta(html, "og:type").lower()
    if not out["kind"] and og_type:
        out["kind"] = "series" if ("tv" in og_type or "episode" in og_type) else "movie" if "movie" in og_type else ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    titles = [t for t in (_meta(html, "og:title"), _meta(html, "twitter:title"), _unescape(m.group(1)) if m else "") if t]
    for i, title in enumerate(titles):                  # الاسم من أولها، والسنة والنوع ممّا بين قوسين في أيٍّ منها
        title = re.sub(r"\s*[⭐|].*$", "", _SITE_TAIL.sub("", title)).strip()   # «… ⭐ 9.5 | Crime, Drama» في og:title عند IMDb
        if not out["kind"] and _TV_HINT.search(title):
            out["kind"] = "series"
        paren = re.search(r"\s*\(([^)]*)\)\s*$", title)          # «Breaking Bad (TV Series 2008–2013)» «Dune (2021)»
        if paren:
            y = _YEAR.search(paren.group(1))
            out["year"] = out["year"] or (int(y.group(1)) if y else 0)
            if _TV_HINT.search(paren.group(1)):
                out["kind"] = out["kind"] or "series"
            title = title[:paren.start()].strip()
        if i == 0 or not out["name"]:
            out["name"] = out["name"] or title
    if not out["lang"]:                                    # IMDb: ‏title-details-languages؛ TMDB: «Original Language»
        m = (re.search(r'title-details-languages.*?<a[^>]*>([^<]+)</a>', html, re.S | re.I)
             or re.search(r'Original Language\s*(?:</[^>]+>\s*)+([A-Za-z][A-Za-z ]+)', html, re.I)
             or re.search(r'"original_language"\s*:\s*"([a-z]{2})"', html))
        out["lang"] = _lang_code(m.group(1)) if m else ""
    out["name"] = _text(out["name"], content.NAME_MAX)
    if out["year"] and not 1900 <= out["year"] <= 2100:
        out["year"] = 0
    return out


def lookup_ok(ip, now=None):
    """حدّ قراءة الروابط بالساعة لكل عنوان (كحدّ البلاغات، بعدّادٍ مستقل)."""
    if not ip:
        return True
    hour = int((now or time.time()) // 3600)
    k = hashlib.sha256(str(ip).encode()).hexdigest()[:16] + ":" + str(hour)
    with _lock:
        for old in [x for x in _lookups if not x.endswith(":" + str(hour))]:
            _lookups.pop(old, None)
        _lookups[k] = _lookups.get(k, 0) + 1
        return _lookups[k] <= LOOKUP_RATE


def _json(url, headers=None, timeout=LOOKUP_TIMEOUT):
    """‏GET ← JSON، أو None لكل خطأ."""
    try:
        rq = Request(url, headers=dict({"User-Agent": UA_BROWSER, "Accept": "application/json"}, **(headers or {})))
        with content.build_opener(content._SafeRedirect).open(rq, timeout=timeout) as r:
            return json.loads(r.read(JSON_MAX).decode("utf-8", "replace"))
    except (HTTPError, URLError, OSError, ValueError):
        return None


def imdb_id(url):
    """رابط IMDb (‏www وm والمترجم كـ ‏/ar/title/…، ومشاركة التطبيق ‏?ref_=ext_shr) ← رقمه «tt0111161»، أو ""."""
    u = urlsplit(url)
    host = (u.hostname or "").lower()
    m = _IMDB_ID.search(u.path + "/")
    return m.group(1) if m and (host == "imdb.com" or host.endswith(".imdb.com")) else ""


def _imdb(tt):
    """رقم IMDb ← {kind, name, year, lang} من بياناته العامة، أو None."""
    d = _json(IMDB_API.replace("{id}", tt))
    x = next((x for x in (d or {}).get("d") or [] if isinstance(x, dict) and x.get("id") == tt), None)
    kind = _IMDB_KIND.get(str((x or {}).get("qid") or ""))
    if not x or not kind or not str(x.get("l") or "").strip():
        return None                                  # حلقةٌ وحدها أو لعبة: لا يُعرف منها المسلسل
    year = _int(x.get("y"), 1900, 2100) or 0
    lang = _lang_code((_json(TVMAZE_API.replace("{id}", tt), timeout=4) or {}).get("language")) if kind == "series" else ""
    return {"kind": kind, "name": _text(_unescape(str(x["l"])), content.NAME_MAX), "year": year, "lang": lang or _wikidata_lang(tt)}


def _wikidata_lang(tt):
    """اللغة الأصلية برقم IMDb من Wikidata ← رمزها في LANGS، أو "" (ولا تُعطّل البقية إن تأخرت)."""
    q = ('SELECT ?c2 ?c3 WHERE { ?i wdt:P345 "%s"; wdt:P364 ?l . OPTIONAL { ?l wdt:P218 ?c2 } OPTIONAL { ?l wdt:P220 ?c3 } } LIMIT 5' % tt)
    d = _json(WIKIDATA_API + "?" + urlencode({"query": q, "format": "json"}),
              {"User-Agent": UA_BOT, "Accept": "application/sparql-results+json"}, timeout=4)
    for b in ((d or {}).get("results") or {}).get("bindings") or []:
        c2 = str((b.get("c2") or {}).get("value") or "").lower()
        c3 = str((b.get("c3") or {}).get("value") or "").lower()
        code = _lang_code(c2) or _ISO3.get(c3, "")
        if code:
            return code
    return ""


_SLUG_SKIP = {"movie", "movies", "film", "films", "tv", "series", "show", "shows", "title", "titles", "watch", "season", "episode",
              "seasons", "episodes", "details", "info", "ar", "en", "www", "index", "html", "php", "مسلسل", "فيلم", "مسلسلات", "افلام", "أفلام"}


def from_slug(url):
    """حين لا تُقرأ الصفحة: الاسم ممّا في الرابط نفسه (‏/movie/278-the-shawshank-redemption ‏/film/dune-2021
    ‏/series/مسلسل-الهيبة) ← {kind, name, year, lang}. وفي رابط مسلسلٍ أو فيلمٍ وحده (‏/movie/ ‏/tv/ ‏/film/ ‏/series/، أو
    «مسلسل-…»)، فلا يصير آخرُ أي رابطٍ اسمًا؛ وNone لرابطٍ بأرقامٍ أو معرّفٍ وحده."""
    from urllib.parse import unquote
    path = urlsplit(url).path
    kind = ("series" if re.search(r"/(tv|series|show|shows|tv-shows?)/", path.lower() + "/")
            else "movie" if re.search(r"/(movie|movies|film|films)/", path.lower() + "/") else "")
    for seg in reversed([x for x in path.split("/") if x]):
        seg = re.sub(r"\.(html?|php|aspx?)$", "", unquote(seg), flags=re.I)
        words = [w for w in re.split(r"[-_+.\s]+", seg) if w]
        while words and (words[0].isdigit() or re.fullmatch(r"(tt|nm)\d+", words[0], re.I)):
            words.pop(0)                             # ‏«278-…» أرقام TMDB أولها
        year = 0
        if len(words) > 1 and _YEAR.fullmatch(words[-1]):
            year = int(words.pop())
        while words and words[-1].isdigit():
            words.pop()
        if words and words[0] in ("مسلسل", "فيلم"):
            kind = kind or ("series" if words[0] == "مسلسل" else "movie")
            words.pop(0)
        if re.fullmatch(r"[a-z]{2}([-_][a-z]{2,4})?", seg, re.I):
            continue                                 # ‏«sa-en» «ar»: البلد واللغة
        if not words or all(w.lower() in _SLUG_SKIP for w in words) or (len(words) == 1 and len(words[0]) <= 2) or not any(re.search(r"[^\W\d_]", w) for w in words) \
                or any(len(w) > 24 or re.fullmatch(r"(?=.*\d)(?=.*[a-z])[a-z0-9]{8,}", w, re.I) for w in words):
            continue                                 # كلمةٌ عامّة، أو رقمٌ أو معرّفٌ عشوائي، لا اسم
        if not kind:
            return None
        name = " ".join(w[:1].upper() + w[1:] if w.isascii() and w.islower() else w for w in words)
        return {"kind": kind, "name": _text(name, content.NAME_MAX), "year": year, "lang": ""}
    return None


def lookup(url):
    """يقرأ صفحة الرابط ← {ok, kind, name, year, lang} أو {ok: False, error, en}. لا يرمي استثناءً. ورابط IMDb من بياناته
    العامة أولًا، وما لا تُقرأ صفحته يُعرف اسمه ممّا في الرابط نفسه إن كان (و‏guess: لتُراجَع)."""
    try:
        url = link_of(url)
    except Invalid as e:
        return {"ok": False, "error": str(e), "en": e.en}
    bad = {"ok": False, "error": "تعذّر قراءة الرابط — اكتب البيانات بنفسك", "en": "Couldn’t read the link — fill in the details yourself"}
    if not url:
        return {"ok": False, "error": "الصق الرابط", "en": "Paste the link"}
    tt = imdb_id(url)
    if tt:
        d = _imdb(tt)
        if d:
            return dict(d, ok=True)
    if not content._public_host(urlsplit(url).hostname or ""):
        return bad
    d = _page(url)
    if d and d["name"]:
        return dict(d, ok=True)
    g = None if tt else from_slug(url)
    return dict(g, ok=True, guess=True) if g else bad


def _page(url):
    try:
        rq = Request(url, headers={"User-Agent": UA_BROWSER, "Accept": "text/html,application/xhtml+xml",
                                   "Accept-Language": "en-US,en;q=0.8,ar;q=0.6"})
        with content.build_opener(content._SafeRedirect).open(rq, timeout=LOOKUP_TIMEOUT) as r:
            if "html" not in (r.headers.get("Content-Type") or "text/html").lower():
                return None
            raw = r.read(LOOKUP_MAX)
            charset = r.headers.get_content_charset() or "utf-8"
    except (HTTPError, URLError, OSError, ValueError):
        return None
    try:
        html = raw.decode(charset, "replace")
    except LookupError:
        html = raw.decode("utf-8", "replace")
    return parse_page(html, url)

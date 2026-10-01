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
له رقمٌ ولم يوقفه، وإلى رقم المدير إن حفظه — بالاسم والحلقة والمشكلة والسيرفر والقسم وصاحب البلاغ ورابط الصفحة.
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
page_url = ""                # رابط صفحة البلاغات في التنبيه
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


def _request(srv, form):
    """طلب إضافة: النوع والاسم كما كتبه (والسنة إن ذكرها) — لا يُطابَق بالفهرس، فما يطلبه ليس فيه."""
    kind = str(form.get("t") or "")
    if kind not in ("series", "movie"):
        raise Invalid("اختر: مسلسل أو فيلم", "Choose: series or movie")
    name = _text(form.get("n"), content.NAME_MAX)
    if len(name.replace(" ", "")) < 2:
        raise Invalid("اكتب اسم المسلسل أو الفيلم", "Write the series or movie name")
    return {"server": srv["key"], "sname": srv["name"], "sname_en": content.en_name(srv), "kind": kind, "gid": "", "group": "", "title": name,
            "year": _int(form.get("y"), 1900, 2100) or 0, "season": None, "ep": None, "problem": ADD, "p": ""}


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
        lines = [head, "", f"🎬 {title}"]
    else:
        prob = problem_name(r.get("problem"), r.get("kind"), "en")
        head = (f"🔔 *New report on {srv}: {prob}*" if new else f"🔁 *Repeated report on {srv}: {prob}* ({n} reports)")
        ep = ""
        if r.get("kind") == "series":
            ep = (f" · S{r['season']}" if r.get("season") else "") + (f" · E{r['ep']}" if r.get("ep") else " · all episodes")
        lines = [head, "", f"🎬 {title}{ep}", f"📂 {KIND_EN.get(r.get('kind'), '')} · {w(r.get('group'))}"]
    p = next((x for x in reversed(r.get("people") or []) if x.get("phone") or x.get("note")), None)
    if p:
        lines.append("📱 " + " — ".join(b for b in (f"+{p['phone']}" if p.get("phone") else "", w(p.get("note"))) if b))
    if page_url:
        lines += ["", f"Reports: {page_url}"]
    return "\n".join(lines)


def alert_text(r, new, lang="ar"):
    """نصّ التنبيه بخطّ واتساب العريض — وأول كل سطرٍ فيه اسمٌ علامة RLM فيبقى من اليمين وإن بدأ بإنجليزي."""
    if lang == "en":
        return alert_text_en(r, new)
    w, rlm = content._wa, "\u200f"
    n, srv = int(r.get("count") or 1), w(r.get("sname"))
    title = w(r.get("title")) + (f" ({r['year']})" if r.get("year") else "")
    if r.get("problem") == ADD:                        # طلب إضافة: الاسم كما كتبه، بلا قسمٍ ولا حلقة
        kind = KIND_ONE.get(r.get("kind"), "")
        head = (f"🙋 *طلب إضافة {kind} في {srv}*" if new else f"🔁 *طلب إضافة {kind} في {srv}* — طلبه {n} مشتركين")
        lines = [head, "", f"{rlm}🎬 {title}"]
    else:
        prob = problem_name(r.get("problem"), r.get("kind"))
        head = (f"🔔 *بلاغ جديد في {srv}: {prob}*" if new else f"🔁 *بلاغٌ متكرّر في {srv}: {prob}* ({n} بلاغات)")
        ep = ""
        if r.get("kind") == "series":
            ep = (f" · الموسم {r['season']}" if r.get("season") else "") + (f" · الحلقة {r['ep']}" if r.get("ep") else " · كل الحلقات")
        lines = [head, "", f"{rlm}🎬 {title}{ep}", f"{rlm}📂 {KIND_ONE.get(r.get('kind'), '')} · {w(r.get('group'))}"]
    p = next((x for x in reversed(r.get("people") or []) if x.get("phone") or x.get("note")), None)
    if p:
        lines.append(f"{rlm}📱 " + " — ".join(b for b in (f"+{p['phone']}" if p.get("phone") else "", w(p.get("note"))) if b))
    if page_url:
        lines += ["", f"البلاغات: {page_url}"]
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

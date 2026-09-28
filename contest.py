# -*- coding: utf-8 -*-
"""مسابقة «توقّع النتيجة واربح» على مباريات البطولة (‏tournament.py).

المدير يفتحها على مباراةٍ بعينها من admin.ssouq.com/contest بجائزتها وعدد فائزيها.
والزائر يختار النتيجة في صفحة المباراة ويكتب اسمه، فيأخذ **رمزًا** (‏start)، ثم يرسل رسالة
واتساب جاهزة فيها الرمز إلى رقم المتجر؛ وخدمة واتساب (whatsapp-baileys) تمرّرها إلى
confirm، فيُسجَّل التوقّع **برقم مرسل الرسالة نفسه** — لا رقمٌ يُكتب، فلا رقمٌ وهمي ولا رقم
صاحبٍ دون علمه. وما بعد ذلك آليٌّ كله، بلا يد:

  • **الإقفال** مع موعد البداية من ESPN: لا رمز بعده، ولا تُقبل إلا رسالةٌ أرسلها صاحبها قبله
    بوقت خادم واتساب نفسه (تُستقبل حتى WA_GRACE بعد البداية إن تأخّر وصولها).
  • **توقّعٌ واحد لكل رقم** في كل مباراة، ولا يُعدَّل.
  • **بصمة التوقّعات**: SHA-256 لقائمتها كما أُقفلت، تُعرض للعموم من لحظة الإقفال.
  • **الفرز** بعد صافرة النهاية:
        رقم القرعة = SHA-256(البصمة | المباراة | النتيجة)
    المؤهّلون من أصاب النتيجة بالضبط، فإن لم يكن أحد فمن أصاب الفائز أو التعادل،
    والفائز = المؤهّل رقم (رقم القرعة mod عددهم) بترتيب التسجيل. لا يعرف أحدٌ الرقم
    قبل النهاية، ولا تتغيّر القائمة بعد الإقفال، وإعادة الفرز تعطي الفائز نفسه.
  • **التبليغ** على واتساب للرقم نفسه، والجائزة لا تُسلَّم إلا له.

التخزين ملفٌّ لكل مباراة في data/contest/<المعرّف>.json، والإعداد في settings.json بجانبها.
بلا مكتبات خارجية.
"""
import collections
import datetime
import hashlib
import json
import os
import random
import re
import secrets
import threading
import time
import unicodedata

import crypto_store
import renew

DIR = "contest"
SETTINGS = "settings.json"
# حالات ESPN: الملغاة لا فرز لها، والمعلّقة تنتظر (مؤجلة، أو أُوقفت وقد تُستكمل)
VOID = {"STATUS_CANCELED"}
HOLD = {"STATUS_POSTPONED", "STATUS_SUSPENDED", "STATUS_ABANDONED", "STATUS_FORFEIT", "STATUS_DELAYED"}
SETTLE_AFTER = 95 * 60          # لا فرز قبل هذا من موعد البداية مهما قالت ESPN (حارسٌ من بياناتٍ خاطئة)
MAX_GOALS = 15
NAME_MAX = 30
PRIZE_MAX = 80
MAX_WINNERS = 10
EXTRA_MAX = 15                   # أقصى ما يبقى فيه التوقّع مفتوحًا بعد صافرة البداية (دقائق، خيارٌ للمدير)
IP_PER_HOUR = 30                # رموز من عنوانٍ واحد في الساعة، على كل المباريات
IP_PER_MATCH = 6                # ومن عنوانٍ واحد في المباراة الواحدة (عائلةٌ على شبكة البيت)
WA_GRACE = 10 * 60              # رسالةٌ أُرسلت قبل البداية ووصلت بعدها تُقبل حتى هذا؛ وبعده تُعلن البصمة
CODE_ALPHA = "ACDEFGHJKLMNPQRTUVWXY34679"   # بلا ما يلتبس (0/O، 1/I، 5/S، 8/B، 2/Z)
CODE_LEN = 6
POOL_WINDOW = 150               # المؤهّلون المعروضون حول الفائز في تقرير الفرز العام (من كل جهة)
RIYADH = datetime.timezone(datetime.timedelta(hours=3))
PRIZE_UTM = "utm_source=guide.ssouq.com&utm_medium=referral&utm_campaign=contest"   # كروابط الدليل

DEFAULT_TEXT = ("مبروك {name} 🎉\n"
                "فزت في مسابقة سمارت سوق لتوقّع نتيجة مباراة {match}.\n"
                "النتيجة: {score}\n"
                "جائزتك: {prize}\n\n"
                "رُد على هذه الرسالة لاستلامها.\n"
                "كيف تم الفرز: {link}")
DEFAULTS = {"notify": True, "text": DEFAULT_TEXT, "admin_phone": ""}

# شروط المسابقة كما تظهر للزائر (صفحة المسابقة وبطاقة المباراة)
RULES = [
    "المشاركة مجانية ولا تشترط شراء.",
    "يُسجَّل التوقّع برسالة واتساب يرسلها المشارك من رقمه، والرقم المعتمد رقم مرسل الرسالة.",
    "توقّعٌ واحد لكل رقم واتساب في كل مباراة، ولا يُعدَّل بعد إرساله.",
    "تُقفل التوقّعات مع صافرة البداية، أو بعدها بدقائق إن ذُكر ذلك في المباراة: لا تُقبل رسالةٌ أُرسلت بعد الإقفال.",
    "النتيجة المعتمدة نتيجة المباراة النهائية كما تعلنها ESPN، بالأشواط الإضافية إن لُعبت، ولا تُحسب ركلات الترجيح.",
    "الفرز آليٌّ بعد صافرة النهاية: المؤهّلون من أصاب النتيجة بالضبط، فإن لم يُصبها أحد فمن أصاب الفائز أو التعادل.",
    "الفائز يُختار بقرعة ثابتة: رقم القرعة من بصمة التوقّعات (تُعلن عند الإقفال) والنتيجة النهائية، "
    "والفائز هو المؤهّل الذي ترتيبه باقي قسمة هذا الرقم على عدد المؤهّلين. فلا يختاره أحدٌ بيده، "
    "وإعادة الفرز تعطي الفائز نفسه.",
    "نبلّغ الفائز على واتساب بالرقم الذي سجّل به، ولا تُسلَّم الجائزة إلا لصاحب ذلك الرقم. "
    "ومن لم يردّ خلال 7 أيام سقطت جائزته.",
    "رقمك للتواصل بشأن المسابقة وحدها، ولا نرسل لك عروضًا إلا إن وافقت على ذلك.",
]

STATE_MSG = {"closed": "أُقفلت التوقّعات مع صافرة البداية.",
             "pending": "انتهت المباراة، والفرز آليٌّ خلال دقائق.",
             "done": "انتهت المسابقة وفُرزت.",
             "void": "أُلغيت المباراة فلا فرز.",
             "hold": "التوقّعات موقوفة حتى يُعلن موعد المباراة.",
             "off": "لا مسابقة على هذه المباراة."}

_lock = threading.Lock()
_hits = {}          # بصمة العنوان ← أوقات توقّعاته في الساعة الأخيرة
_index = {}         # مجلد البيانات ← {المعرّف: ملخّص} — يُبنى مرةً ويُحدَّث مع كل حفظ
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


# ---------- التخزين ----------
def _dir(data_dir):
    return os.path.join(data_dir, DIR)


def eid_of(v):
    """معرّف ESPN أرقامًا فقط، وإلا فارغ — فلا يصير اسمَ ملفٍّ خارج المجلد."""
    s = str(v or "").strip()
    return s if re.fullmatch(r"\d{1,12}", s) else ""


def _path(data_dir, eid):
    return os.path.join(_dir(data_dir), eid + ".json")


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def load(data_dir, eid):
    eid = eid_of(eid)
    return _read(_path(data_dir, eid)) if eid else None


def _blank(eid):
    return {"eid": eid, "on": False, "prize": "", "winners": 1, "match": {}, "entries": [],
            "draw": None, "void": None, "sent": [], "created": time.time()}


def _summary(rec):
    s = {"eid": rec["eid"], "on": bool(rec.get("on")), "prize": rec.get("prize") or "",
         "prize_id": rec.get("prize_id") or "", "prize_url": rec.get("prize_url") or "",
         "prize_img": rec.get("prize_img") or "",
         "winners": int(rec.get("winners") or 1), "extra": extra_of(rec), "count": len(rec.get("entries") or []),
         "draw": bool(rec.get("draw")), "void": bool(rec.get("void")), "match": rec.get("match") or {}}
    if rec.get("draw"):
        by = {e["n"]: e for e in rec["entries"]}
        s["score"] = rec["draw"]["score"]
        s["won"] = [short_name(by[p["n"]]["name"]) for p in rec["draw"]["picks"] if p["n"] in by]
    return s


def summaries(data_dir):
    """كل المسابقات ملخّصةً {المعرّف: ملخّص} — من الذاكرة بعد أول قراءة."""
    with _lock:
        idx = _index.get(data_dir)
        if idx is None:
            idx = {}
            try:
                names = os.listdir(_dir(data_dir))
            except OSError:
                names = []
            for fn in names:
                rec = _read(os.path.join(_dir(data_dir), fn)) if re.fullmatch(r"\d+\.json", fn) else None
                if rec and rec.get("eid"):
                    idx[rec["eid"]] = _summary(rec)
            _index[data_dir] = idx
        return dict(idx)


def _save(data_dir, rec):
    """يُستدعى والقفل ممسوك."""
    rec["updated"] = time.time()
    _write(_path(data_dir, rec["eid"]), rec)
    if data_dir in _index:
        _index[data_dir][rec["eid"]] = _summary(rec)


def load_settings(data_dir):
    s = _read(os.path.join(_dir(data_dir), SETTINGS)) or {}
    out = dict(DEFAULTS)
    out["notify"] = bool(s.get("notify", DEFAULTS["notify"]))
    out["text"] = str(s.get("text") or DEFAULTS["text"])[:1000]
    out["admin_phone"] = norm_phone(s.get("admin_phone", ""))
    return out


# ---------- خدمة واتساب النظام اللوجستي (whatsapp-reader في souq-saas) ----------
# الخدمة نفسها التي يربط بها النظام اللوجستي أرقامه: جلسةٌ لكل مفتاح، تُربط برمز QR من صفحة
# المدير (الرقم ← «ربط» ← امسح الرمز)، وتمرّر الرسائل الخاصة (1:1) إلى رابطنا موقَّعةً برمزٍ نولّده.
# تعمل نسختها (whatsapp-reader/) داخل الحاوية نفسها على 127.0.0.1 بسرٍّ يُولَّد ويُحفظ — فلا إعداد؛
# وإن ضُبط WHATSAPP_READER_URL/SECRET (بأسمائهما في النظام اللوجستي) فالخدمة الخارجية بدلها.
READER_TENANT = "ssouq-guide--contest"
EMBED_PORT = int(os.environ.get("CONTEST_READER_PORT", "3301") or 3301)


def _secret(data_dir, key):
    """سرٌّ عشوائيّ يُولَّد مرةً ويُحفظ مشفَّرًا في إعداد المسابقة."""
    s = _read(os.path.join(_dir(data_dir), SETTINGS)) or {}
    v = crypto_store.decrypt(s.get(key) or "", data_dir)
    if v:
        return v
    with _lock:
        s = _read(os.path.join(_dir(data_dir), SETTINGS)) or {}
        v = crypto_store.decrypt(s.get(key) or "", data_dir)
        if not v:
            v = secrets.token_urlsafe(24)
            s[key] = crypto_store.encrypt(v, data_dir)
            _write(os.path.join(_dir(data_dir), SETTINGS), s)
    return v


def reader_config(data_dir):
    """← {url, secret, token, embedded}: الخدمة المدمجة (افتراضًا) أو الخارجية من البيئة؛ وtoken رمز
    توقيع الرسائل الواردة."""
    url = os.environ.get("WHATSAPP_READER_URL", "").strip().rstrip("/")
    if url:
        secret = os.environ.get("WHATSAPP_READER_SECRET", "").strip()
    else:
        url, secret = f"http://127.0.0.1:{EMBED_PORT}", _secret(data_dir, "reader_embed_secret")
    return {"url": url, "secret": secret, "token": _secret(data_dir, "reader_token"),
            "embedded": url == f"http://127.0.0.1:{EMBED_PORT}"}


def save_settings(data_dir, new):
    s = {"notify": bool(new.get("notify")),
         "text": str(new.get("text") or "").strip()[:1000] or DEFAULT_TEXT,
         "admin_phone": norm_phone(new.get("admin_phone", ""))}
    if s["admin_phone"] and not phone_ok(s["admin_phone"]):
        raise ValueError("رقم واتساب المدير غير صحيح")
    with _lock:
        old = _read(os.path.join(_dir(data_dir), SETTINGS)) or {}
        s.update({k: v for k, v in old.items() if k.startswith("reader_")})
        _write(os.path.join(_dir(data_dir), SETTINGS), s)
    return load_settings(data_dir)


# ---------- التنظيف والإخفاء ----------
def norm_phone(p):
    """05x و5x و+9665x و009665x تصير 9665x، وما عداها رقمٌ دوليٌّ بمفتاح دولته."""
    d = renew.norm_phone(p)
    if len(d) == 9 and d.startswith("5"):
        d = "966" + d
    return d


def phone_ok(d):
    if d.startswith("966"):
        return bool(re.fullmatch(r"9665\d{8}", d))
    return bool(re.fullmatch(r"[1-9]\d{7,14}", d))


def clean_name(s):
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = re.sub(r"[\x00-\x1f\x7f<>]", "", s)
    return re.sub(r"\s+", " ", s).strip()[:NAME_MAX]


def short_name(name):
    """الاسم الأول وحده للعلن («أبو فهد» و«عبد الله» كلمتان)."""
    parts = str(name or "").split()
    if not parts:
        return ""
    if len(parts) > 1 and parts[0] in ("أبو", "ابو", "أم", "ام", "عبد", "بو"):
        return " ".join(parts[:2])[:NAME_MAX]
    return parts[0][:NAME_MAX]


def mask_phone(d):
    """9665XXXXX321 ← ‎05•••••321، والدوليّ ‎+965•••••321."""
    d = str(d or "")
    if re.fullmatch(r"9665\d{8}", d):
        return "05" + "•" * 5 + d[-3:]
    if len(d) < 7:
        return "•" * len(d)
    return "+" + d[:3] + "•" * (len(d) - 6) + d[-3:]


def _goals(v):
    try:
        n = int(str(v).strip().translate(_AR_DIGITS))
    except (TypeError, ValueError):
        return None
    return n if 0 <= n <= MAX_GOALS else None


def _ipk(ip):
    return hashlib.sha256(str(ip).encode()).hexdigest()[:12] if ip else ""


def _sign(x):
    return (x > 0) - (x < 0)


def _snap(m):
    """ما يلزم من المباراة ليبقى مع المسابقة وإن خرجت من ESPN."""
    return {"home": m["home"]["name"], "away": m["away"]["name"],
            "home_logo": m["home"].get("logo") or "", "away_logo": m["away"].get("logo") or "",
            "ts": m["ts"], "slug": m["slug"], "stage": m["stage"], "time_ok": m["time_ok"]}


def _sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ---------- الحالة ----------
def extra_of(rec):
    """دقائق يبقى فيها التوقّع مفتوحًا بعد صافرة البداية (0 = يُقفل مع الصافرة)."""
    try:
        return max(0, min(int((rec or {}).get("extra") or 0), EXTRA_MAX))
    except (TypeError, ValueError):
        return 0


def lock_at(rec, ts):
    """موعد إقفال التوقّعات: صافرة البداية ودقائق المدير بعدها."""
    return (ts or 0) + extra_of(rec) * 60


def state_of(rec, m, now=None):
    """off · open · hold · closed · pending · done · void — لسجلٍّ أو ملخّصه."""
    now = time.time() if now is None else now
    if not rec:
        return "off"
    if rec.get("draw"):
        return "done"
    if rec.get("void"):
        return "void"
    if not rec.get("on"):
        return "off"
    if not m:
        return "closed"
    if m["status"] in VOID:
        return "void"
    if m["state"] == "pre":
        if m["status"] in HOLD or not m["time_ok"]:
            return "hold"
        return "open" if now < lock_at(rec, m["ts"]) else "closed"
    if m["state"] == "post" and m["status"] not in HOLD:
        return "pending"
    if m["state"] == "in" and m["status"] not in HOLD and now < lock_at(rec, m["ts"]):
        return "open"                                  # دقائق المدير بعد الصافرة
    return "closed"


def fingerprint(entries):
    """بصمة القائمة كما أُقفلت: رقم التوقّع ونتيجته وبصمة رقمه (لا الرقم نفسه)، بترتيب التسجيل."""
    lines = [f"{e['n']}|{e['h']}-{e['a']}|{_sha(e['phone'])[:16]}" for e in sorted(entries, key=lambda e: e["n"])]
    return _sha("\n".join(lines))


def dist(entries, top=5):
    """أكثر النتائج توقّعًا، وكم توقّع فوز صاحب الأرض والتعادل والضيف (تُعرض بعد الإقفال)."""
    c = collections.Counter((e["h"], e["a"]) for e in entries)
    return {"n": len(entries),
            "top": [{"h": h, "a": a, "c": k} for (h, a), k in c.most_common(top)],
            "home": sum(1 for e in entries if e["h"] > e["a"]),
            "draw": sum(1 for e in entries if e["h"] == e["a"]),
            "away": sum(1 for e in entries if e["h"] < e["a"])}


# ---------- التوقّع: رمزٌ من الصفحة، ثم رسالة واتساب من صاحب الرقم ----------
_CODE_RE = re.compile(r"رمز\s*التوقع\s*[:：]?\s*([A-Za-z0-9]{%d})(?![A-Za-z0-9])" % CODE_LEN)
_TASHKEEL = re.compile(r"[\u064B-\u065F\u0670\u0640]")


def code_in(text):
    """الرمز من رسالة التوقّع («رمز التوقّع: K7Q4MX»)، بلا تشكيلٍ وبأرقامٍ عربيةٍ أو لاتينية."""
    m = _CODE_RE.search(_TASHKEEL.sub("", str(text or "")).translate(_AR_DIGITS))
    return m.group(1).upper() if m else ""


def _rate_ok(ipk, now):
    if not ipk:
        return True
    with _lock:
        ts = [t for t in _hits.get(ipk, ()) if now - t < 3600]
        ok = len(ts) < IP_PER_HOUR
        if ok:
            ts.append(now)
        _hits[ipk] = ts
        if len(_hits) > 5000:
            for k in [k for k, v in _hits.items() if not v or now - v[-1] >= 3600]:
                _hits.pop(k, None)
    return ok


def message_text(mt, h, a, code):
    """نصّ رسالة واتساب الجاهزة — والرمز فيه ما يُعتمد، لا النتيجة المكتوبة."""
    return (f"توقّعي في مسابقة سمارت سوق 🎁\n{mt['home']} {h} – {a} {mt['away']}\n"
            f"رمز التوقّع: {code}")


def start(data_dir, m, form, ip="", now=None):
    """الخطوة الأولى من الصفحة: النتيجة والاسم ← رمزٌ ورسالةٌ جاهزة (‏(رمز HTTP، الرد))."""
    now = time.time() if now is None else now
    if not m or m["id"] != eid_of(form.get("m")):
        return 404, {"error": "لا مسابقة على هذه المباراة"}
    name = clean_name(form.get("name"))
    h, a = _goals(form.get("h")), _goals(form.get("a"))
    if str(form.get("website") or "").strip():            # حقلٌ مخفي لا يملؤه إلا روبوت: ردٌّ لا يُحفظ
        return 200, {"ok": True, "code": "".join(CODE_ALPHA[0] for _ in range(CODE_LEN)), "h": h or 0, "a": a or 0,
                     "text": ""}
    if len(name) < 2 or not re.search(r"[^\W\d_]", name):
        return 400, {"error": "اكتب اسمك", "field": "name"}
    if h is None or a is None:
        return 400, {"error": "اختر النتيجة", "field": "score"}
    if not form.get("agree"):
        return 400, {"error": "وافق على شروط المسابقة أولًا", "field": "agree"}
    ipk = _ipk(ip)
    if not _rate_ok(ipk, now):
        return 429, {"error": "محاولات كثيرة من هذا الاتصال. حاول بعد ساعة."}
    others = [e for e in waiting(data_dir) if e != m["id"]]
    with _lock:
        rec = load(data_dir, m["id"])
        st = state_of(rec, m, now)
        if st != "open":
            return 409, {"error": STATE_MSG.get(st, "التوقّعات مقفلة."), "state": st}
        tickets = rec.setdefault("tickets", {})
        if ipk and sum(1 for t in tickets.values() if t.get("ipk") == ipk) >= IP_PER_MATCH:
            return 429, {"error": "بلغت التوقّعات من هذا الاتصال حدّها في هذه المباراة."}
        taken = set(tickets)
        for e in others:                                   # الرمز يدلّ على مباراته وحده
            taken |= set(((load(data_dir, e) or {}).get("tickets") or {}))
        rnd = random.SystemRandom()
        code = ""
        while not code or code in taken:
            code = "".join(rnd.choice(CODE_ALPHA) for _ in range(CODE_LEN))
        tickets[code] = {"name": name, "h": h, "a": a, "promo": bool(form.get("promo")), "at": round(now, 3),
                         "ipk": ipk, "st": "pending"}
        rec["match"] = _snap(m)
        _save(data_dir, rec)
    return 200, {"ok": True, "code": code, "h": h, "a": a, "text": message_text(rec["match"], h, a, code)}


def _sent_time(ts, now):
    """وقت الإرسال من خادم واتساب؛ وإن غاب أو شذّ فوقت الوصول."""
    try:
        ts = float(ts)
    except (TypeError, ValueError):
        return now
    return ts if now - 86400 < ts <= now + 120 else now


def confirm(data_dir, text, phone, sent_ts, matches, link, now=None):
    """الخطوة الثانية من واتساب: رسالةٌ فيها رمز ← يُسجَّل التوقّع برقم مرسلها.
    ← {status, reply?, eid?, n?}: done · dup (الرقم توقّع من قبل) · late (أُرسلت بعد البداية)
    · used (الرمز لرقمٍ آخر) · unknown · nophone · ignored (لا رمز: لا ردّ أبدًا —
    فرسائل العملاء الأخرى على الرقم نفسه لا يُجاب عنها)."""
    now = time.time() if now is None else now
    code = code_in(text)
    if not code:
        return {"status": "ignored"}
    phone = norm_phone(phone)
    ids = waiting(data_dir)
    with _lock:
        rec = t = None
        for eid in ids:
            r = load(data_dir, eid)
            if r and code in (r.get("tickets") or {}):
                rec, t = r, r["tickets"][code]
                break
        if not t:
            return {"status": "unknown", "reply": "لم نجد هذا الرمز، أو انتهى وقته. سجّل توقّعك من صفحة المباراة "
                                                  "ثم أرسل الرسالة كما هي."}
        eid, mt = rec["eid"], rec.get("match") or {}
        m = (matches or {}).get(eid)
        kick = (m or mt).get("ts") or 0
        page = link(rec)
        if t["st"] == "done":
            if t.get("by") == _sha(phone)[:16]:
                return {"status": "done", "eid": eid, "n": t["n"], "reply": f"توقّعك مسجّل من قبل، ورقمه {t['n']}. "
                                                                            "بالتوفيق!"}
            return {"status": "used", "eid": eid, "reply": "هذا الرمز استُخدم من رقمٍ آخر. سجّل توقّعك أنت من صفحة "
                                                           f"المباراة: {page}"}
        if not phone_ok(phone):
            return {"status": "nophone", "eid": eid, "reply": "تعذّر التعرّف على رقمك من واتساب. حدّث التطبيق "
                                                              "وأعد إرسال الرسالة."}
        sent = _sent_time(sent_ts, now)
        void = m and m["status"] in VOID
        lock = lock_at(rec, kick)
        if void or not kick or sent >= lock or now >= lock + WA_GRACE:
            t["st"] = "late"
            _save(data_dir, rec)
            return {"status": "late", "eid": eid, "reply": "وصلت رسالتك بعد إقفال التوقّعات فلم يُحتسب التوقّع. "
                                                           "نلقاك في المباراة القادمة!"}
        old = next((e for e in rec["entries"] if e["phone"] == phone), None)
        if old:
            t.update(st="dup", n=old["n"], ph=mask_phone(phone))
            _save(data_dir, rec)
            return {"status": "dup", "eid": eid, "n": old["n"],
                    "reply": f"رقمك سجّل توقّعه لهذه المباراة من قبل: {mt.get('home', '')} {old['h']} – {old['a']} "
                             f"{mt.get('away', '')} (رقم توقّعك {old['n']}). والتوقّع لا يُعدَّل."}
        n = (rec["entries"][-1]["n"] if rec["entries"] else 0) + 1
        rec["entries"].append({"n": n, "name": t["name"], "phone": phone, "h": t["h"], "a": t["a"],
                               "at": round(sent, 3), "ipk": t.get("ipk", ""), "promo": bool(t.get("promo"))})
        t.update(st="done", n=n, by=_sha(phone)[:16], ph=mask_phone(phone))
        if m:
            rec["match"] = _snap(m)
        _save(data_dir, rec)
    return {"status": "done", "eid": eid, "n": n,
            "reply": (f"تم تسجيل توقّعك ✅\n{mt.get('home', '')} {t['h']} – {t['a']} {mt.get('away', '')}\n"
                      f"رقم توقّعك: {n}\nالفرز آليٌّ بعد صافرة النهاية، ونبلّغك هنا إن فزت 🎁\n{page}")}


def ticket_status(data_dir, eid, code):
    """حال الرمز للصفحة وهي تنتظر الرسالة — لا يكشف إلا ما يعرفه صاحب الرمز."""
    rec = load(data_dir, eid)
    t = ((rec or {}).get("tickets") or {}).get(str(code or "").strip().upper())
    if not t:
        return {"ok": True, "state": "unknown"}
    out = {"ok": True, "state": t["st"], "h": t["h"], "a": t["a"]}
    for k, v in (("n", "n"), ("ph", "phone")):
        if t.get(k):
            out[v] = t[k]
    return out


# ---------- الفرز ----------
def draw_number(seed, i):
    """رقم قرعة الفائز i (يبدأ من الصفر): أول 12 خانة من SHA-256(رقم القرعة:i) عددًا عشريًّا."""
    return int(_sha(f"{seed}:{i}")[:12], 16)


def draw(rec, m, now=None):
    """الفرز نفسه — دالّةٌ ثابتة في مدخلاتها: القائمة والمباراة ونتيجتها."""
    now = time.time() if now is None else now
    h, a = int(m["home"]["score"]), int(m["away"]["score"])
    es = sorted(rec["entries"], key=lambda e: e["n"])
    fp = fingerprint(es)
    seed = _sha(f"{fp}|{rec['eid']}|{h}-{a}")
    exact = [e for e in es if e["h"] == h and e["a"] == a]
    right = [e for e in es if _sign(e["h"] - e["a"]) == _sign(h - a) and not (e["h"] == h and e["a"] == a)]
    picks, want = [], max(1, int(rec.get("winners") or 1))
    for tier, pool in (("exact", exact), ("outcome", right)):
        pool = [e["n"] for e in pool]
        while pool and len(picks) < want:
            num = draw_number(seed, len(picks))
            idx = num % len(pool)
            picks.append({"n": pool[idx], "tier": tier, "num": num, "size": len(pool), "idx": idx, "pool": list(pool)})
            pool.pop(idx)
    return {"at": now, "score": [h, a], "fp": fp, "seed": seed, "count": len(es),
            "exact": len(exact), "outcome": len(right), "picks": picks}


def due(rec, m, now=None):
    now = time.time() if now is None else now
    return (state_of(rec, m, now) == "pending" and not rec.get("draw")
            and now >= m["ts"] + SETTLE_AFTER)


def settle(data_dir, eid, m, now=None):
    """يفرز مسابقةً انتهت مباراتها، ويُلغيها إن أُلغيت ← (السجل، فُرزت الآن؟). تُعاد بلا ضرر."""
    now = time.time() if now is None else now
    with _lock:
        rec = load(data_dir, eid)
        if not rec or not rec.get("on") or rec.get("draw") or rec.get("void") or not m:
            return rec, False
        if m["status"] in VOID:
            rec["void"] = {"at": now, "status": m["status"]}
            rec["match"] = _snap(m)
            rec.pop("tickets", None)
            _save(data_dir, rec)
            return rec, False
        if not due(rec, m, now):
            return rec, False
        rec["draw"] = draw(rec, m, now)
        rec["match"] = _snap(m)
        rec.pop("tickets", None)                      # الرموز لا تلزم بعد الفرز
        _save(data_dir, rec)
        return rec, True


def waiting(data_dir):
    """مسابقاتٌ مفتوحة لم تُفرز بعد — ما تمرّ عليه الدورة."""
    return [eid for eid, s in summaries(data_dir).items() if s["on"] and not s["draw"] and not s["void"]]


# ---------- العلن ----------
def _pub_entry(e):
    return {"n": e["n"], "name": short_name(e["name"]), "phone": mask_phone(e["phone"]), "h": e["h"], "a": e["a"]}


def public_draw(rec):
    """تقرير الفرز للعلن وللفيديو: الأرقام كلها، والأسماء الأولى والأرقام مخفيّةً."""
    d = rec["draw"]
    by = {e["n"]: e for e in rec["entries"]}
    picks = [{**_pub_entry(by[p["n"]]), **{k: p[k] for k in ("tier", "num", "size", "idx")}}
             for p in d["picks"] if p["n"] in by]
    pool, start = [], 0
    if d["picks"]:
        first = d["picks"][0]
        start = max(0, first["idx"] - POOL_WINDOW)
        pool = [_pub_entry(by[n]) for n in first["pool"][start:first["idx"] + POOL_WINDOW + 1] if n in by]
    return {"at": d["at"], "score": d["score"], "fp": d["fp"], "seed": d["seed"], "count": d["count"],
            "exact": d["exact"], "outcome": d["outcome"], "picks": picks, "pool": pool, "pool_from": start}


def _match_of(rec, m):
    s = _snap(m) if m else (rec.get("match") or {})
    return {k: s.get(k) for k in ("home", "away", "home_logo", "away_logo", "ts", "slug", "stage", "time_ok")}


def public(rec, m, now=None):
    """ما تعرضه صفحة المباراة: الحالة والجائزة والعدد — ولا توقّع أحدٍ قبل الإقفال."""
    now = time.time() if now is None else now
    st = state_of(rec, m, now)
    if st == "off":
        return {"ok": True, "state": "off"}
    es = rec.get("entries") or []
    out = {"ok": True, "state": st, "eid": rec["eid"], "prize": rec.get("prize") or "",
           "prize_url": rec.get("prize_url") or "", "prize_img": rec.get("prize_img") or "",
           "winners": int(rec.get("winners") or 1), "count": len(es), "now": round(now, 3),
           "match": _match_of(rec, m), "msg": STATE_MSG.get(st, ""), "extra": extra_of(rec)}
    if st == "hold":
        out["msg"] = ("المباراة مؤجلة، والتوقّعات موقوفة حتى يُعلن موعدها الجديد."
                      if m and m["status"] in HOLD else STATE_MSG["hold"])
    lock = lock_at(rec, out["match"].get("ts") or 0)
    out["closes"] = lock
    if st == "closed" and out["extra"]:
        out["msg"] = f"أُقفلت التوقّعات بعد صافرة البداية بـ {out['extra']} دقائق."
    if st in ("pending", "done", "void") or (st == "closed" and now >= lock + WA_GRACE):
        out["fp"] = fingerprint(es)                   # بعد مهلة الرسائل المتأخرة: القائمة نهائية
        out["dist"] = dist(es)
    if st == "done":
        out["draw"] = public_draw(rec)
    return out


def listing(summ, matches, now=None):
    """مسابقات صفحة المسابقة من ملخّصاتها (summaries): المفتوحة بموعدها، ثم الجارية،
    ثم المفروزة الأحدث أولًا."""
    now = time.time() if now is None else now
    ms = {m["id"]: m for m in matches or []}
    rows = []
    for eid, s in summ.items():
        m = ms.get(eid)
        st = state_of(s, m, now)
        if st == "off":
            continue
        snap = _snap(m) if m else s["match"]
        if not snap:
            continue
        rows.append({"eid": eid, "state": st, "prize": s["prize"], "count": s["count"],
                     "won": s.get("won") or [], "score": s.get("score"), "match": snap,
                     "closes": lock_at(s, snap.get("ts"))})
    order = {"open": 0, "hold": 1, "closed": 2, "pending": 2, "done": 3, "void": 4}
    rows.sort(key=lambda r: (order.get(r["state"], 5),
                             r["match"]["ts"] if order.get(r["state"], 5) < 3 else -r["match"]["ts"]))
    return rows


# ---------- التبليغ ----------
def _fill(tpl, **kw):
    """قالب الرسالة بمتغيّراته — استبدالٌ حرفيّ، فلا يكسره قوسٌ يكتبه المدير."""
    for k, v in kw.items():
        tpl = tpl.replace("{" + k + "}", str(v))
    return tpl


def messages(rec, settings, link):
    """رسائل واتساب بعد الفرز: للفائزين (إن فُعّل التبليغ) وملخّصٌ لرقم المدير إن ضُبط."""
    d = rec.get("draw")
    if not d:
        return []
    mt = rec.get("match") or {}
    by = {e["n"]: e for e in rec["entries"]}
    h, a = d["score"]
    match = f"{mt.get('home', '')} و{mt.get('away', '')}"
    score = f"{mt.get('home', '')} {h} – {a} {mt.get('away', '')}"
    out = []
    if settings.get("notify"):
        for p in d["picks"]:
            e = by.get(p["n"])
            if e:
                out.append({"to": e["phone"], "kind": "winner", "n": e["n"],
                            "text": _fill(settings.get("text") or DEFAULT_TEXT, name=short_name(e["name"]),
                                          match=match, score=score, prize=rec.get("prize") or "", link=link,
                                          prize_link=rec.get("prize_url") or "")})
    if settings.get("admin_phone"):
        won = "، ".join(f"{by[p['n']]['name']} ({by[p['n']]['phone']}) #{p['n']}" for p in d["picks"] if p["n"] in by)
        out.append({"to": settings["admin_phone"], "kind": "admin",
                    "text": (f"فرز مسابقة {match}\nالنتيجة: {score}\n"
                             f"التوقّعات: {d['count']} · أصابوا النتيجة: {d['exact']} · أصابوا الفائز: {d['outcome']}\n"
                             f"الفائز: {won or 'لا أحد'}\nالجائزة: {rec.get('prize') or ''}\n{link}")})
    return out


def mark_sent(data_dir, eid, results):
    with _lock:
        rec = load(data_dir, eid)
        if not rec:
            return
        now = round(time.time(), 3)
        rec.setdefault("sent", []).extend(dict(r, at=now) for r in results)
        _save(data_dir, rec)


# ---------- الإدارة ----------
def saved_prize(data_dir, eid):
    """منتج الجائزة المحفوظ على المسابقة بصيغة store_sitemap.product_of — فيبقى إن غاب عن قائمة
    المتجر لحظيًّا (فشل جلبٍ أو إخفاء)، ولا يُطلب من المدير اختياره من جديد."""
    rec = load(data_dir, eid) or {}
    if not rec.get("prize_id"):
        return None
    url = rec.get("prize_url") or ""
    if url.endswith(PRIZE_UTM):
        url = url[:-len(PRIZE_UTM) - 1]
    return {"id": rec["prize_id"], "name": rec.get("prize") or "", "url": url, "img": rec.get("prize_img") or ""}


def prize_name(product):
    """اسم الجائزة من اسم المنتج في سلة بلا ذيله بعد «|»: «اشتراك فالكون IPTV لمدة 3 أشهر»."""
    name = str(product.get("name") or "")
    return (name.split("|")[0].strip() or name.strip())[:PRIZE_MAX]


def configure(data_dir, m, on, prize, winners, now=None, product=None, extra=None):
    """فتح المسابقة على مباراة أو إيقافها، بجائزتها وعدد فائزيها ← (رمز، رد). والجائزة منتجٌ من
    المتجر (`product` من store_sitemap.products، فيُحفظ رابطه وصورته) أو نصٌّ يكتبه المدير."""
    now = time.time() if now is None else now
    if product:
        prize = prize_name(product)
    prize = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(prize or ""))).strip()[:PRIZE_MAX]
    try:
        winners = max(1, min(int(winners or 1), MAX_WINNERS))
        extra = None if extra is None else max(0, min(int(extra or 0), EXTRA_MAX))
    except (TypeError, ValueError):
        return 400, {"error": "عدد الفائزين رقم"}
    with _lock:
        rec = load(data_dir, m["id"]) or _blank(m["id"])
        if rec.get("draw"):
            return 409, {"error": "فُرزت هذه المسابقة، فلا تُعدَّل."}
        old = state_of(dict(rec, on=True), m, now)
        if extra is not None and extra != extra_of(rec):
            # الإقفال يتغيّر ما لم تُعلن البصمة (قائمة التوقّعات النهائية) ولم تنتهِ المباراة
            if old not in ("open", "hold", "closed") or now >= lock_at(rec, m["ts"]) + WA_GRACE:
                return 409, {"error": "أُعلنت قائمة التوقّعات النهائية، فلا يتغيّر وقت الإقفال."}
            rec["extra"] = extra
        st = state_of(dict(rec, on=True), m, now)
        if on and not prize:
            return 400, {"error": "اكتب الجائزة"}
        if on and not rec["entries"] and st not in ("open", "hold"):
            return 409, {"error": "بدأت المباراة أو انتهت، فلا تُفتح عليها مسابقة الآن."}
        if rec["entries"] and st not in ("open", "hold") and winners != int(rec.get("winners") or 1):
            return 409, {"error": "لا يتغيّر عدد الفائزين بعد إقفال التوقّعات."}
        rec.update(on=bool(on), prize=prize or rec.get("prize") or "", winners=winners, match=_snap(m))
        if product:
            url = product["url"]
            rec.update(prize_id=product["id"], prize_url=url + ("&" if "?" in url else "?") + PRIZE_UTM,
                       prize_img=product.get("img") or "")
        elif prize:                                   # جائزةٌ مكتوبة تحلّ محلّ المنتج
            rec.update(prize_id="", prize_url="", prize_img="")
        _save(data_dir, rec)
    return 200, {"ok": True, "contest": _summary(rec)}


def _when(ts):
    return datetime.datetime.fromtimestamp(ts, RIYADH).strftime("%Y-%m-%d %H:%M") if ts else ""


def admin_rows(data_dir, matches, now=None, days=21):
    """مباريات صفحة المدير: القادمة خلال `days` يومًا والجارية، وكل مباراةٍ عليها مسابقة."""
    now = time.time() if now is None else now
    idx = summaries(data_dir)
    rows, seen = [], set()
    for m in matches or []:
        s = idx.get(m["id"])
        soon = m["state"] == "in" or (m["state"] == "pre" and m["ts"] <= now + days * 86400)
        if not (s or soon):
            continue
        seen.add(m["id"])
        rows.append({"eid": m["id"], "match": _snap(m), "mstate": m["state"], "status": m["status"],
                     "score": [m["home"]["score"], m["away"]["score"]],
                     "contest": s, "state": state_of(s, m, now) if s else "off"})
    for eid, s in idx.items():
        if eid not in seen and s["match"]:
            rows.append({"eid": eid, "match": s["match"], "mstate": "", "status": "", "score": s.get("score"),
                         "contest": s, "state": state_of(s, None, now)})
    rows.sort(key=lambda r: (r["state"] in ("done", "void"), r["match"]["ts"] if r["state"] not in ("done", "void")
                             else -r["match"]["ts"]))
    return rows


def admin_detail(data_dir, eid, m, now=None):
    now = time.time() if now is None else now
    rec = load(data_dir, eid)
    if not rec:
        return None
    by = {e["n"]: e for e in rec["entries"]}
    d = rec.get("draw")
    won = []
    if d:
        won = [{**{k: by[p["n"]][k] for k in ("n", "name", "phone", "h", "a")},
                **{k: p[k] for k in ("tier", "num", "size", "idx")}} for p in d["picks"] if p["n"] in by]
    return {"ok": True, "eid": eid, "state": state_of(rec, m, now), "on": bool(rec.get("on")),
            "prize": rec.get("prize") or "", "winners": int(rec.get("winners") or 1),
            "prize_id": rec.get("prize_id") or "", "prize_url": rec.get("prize_url") or "",
            "match": _match_of(rec, m), "fp": fingerprint(rec["entries"]),
            "entries": [{k: e.get(k) for k in ("n", "name", "phone", "h", "a", "at", "promo")} for e in rec["entries"]],
            "won": won, "draw": {k: v for k, v in d.items() if k != "picks"} if d else None,
            "tickets": dict(collections.Counter(t["st"] for t in (rec.get("tickets") or {}).values())),
            "sent": rec.get("sent") or [], "public": public(rec, m, now)}


def export_sheets(data_dir, eid=""):
    """التوقّعات ملفَّ Excel: ورقةٌ لكل مباراة، أو مباراةٌ واحدة."""
    ids = [eid_of(eid)] if eid else sorted(summaries(data_dir), key=lambda x: int(x))
    sheets = []
    head = ["رقم التوقّع", "الاسم", "واتساب", "توقّع صاحب الأرض", "توقّع الضيف", "وقت التسجيل (السعودية)",
            "يقبل العروض", "فائز"]
    for i in ids:
        rec = load(data_dir, i)
        if not rec:
            continue
        mt = rec.get("match") or {}
        won = {p["n"] for p in (rec.get("draw") or {}).get("picks", [])}
        rows = [[e["n"], e["name"], e["phone"], e["h"], e["a"], _when(e["at"]), "نعم" if e.get("promo") else "لا",
                 "فائز" if e["n"] in won else ""] for e in rec["entries"]]
        sheets.append((f"{mt.get('home', '')} - {mt.get('away', '')}"[:28] or i, head, rows))
    return sheets

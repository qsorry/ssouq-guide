#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
الاشتراكات المجزّأة — بيع خطٍّ واحدٍ بباقة ١٥ شهرًا على أجزاء (١٢ شهرًا · ٦ أشهر · ٣ أشهر · شهر،
أو أي مدةٍ أخرى بالأشهر الكاملة حتى ١٤).

الخط يُنشأ بباقة ١٥ شهرًا (أرخص للشهر الواحد)، ويُباع منه جزءٌ لعميل. فإذا انتهى
الجزء غيّر النظام **اسم المستخدم وحده** على اللوحة — كلمة المرور تبقى كما هي —
فينقطع العميل الأول ويبقى الخط بما تبقّى من مدته — «متبقي ٩ أشهر» بعد جزءٍ من
ستة — جاهزًا للبيع من جديد، ثم يتكرّر ذلك حتى تنتهي مدة الخط. يسري على بوابات
مرح وكاسبر (جلسة ويب) وفالكون.

ثلاث ضمانات تحكم هذا الملف:

1. **لا تغييرَ ضائع ولا بياناتٌ مختلفة في كل محاولة.** البيانات الجديدة تُولَّد
   وتُحفظ (`pending`) *قبل* لمس اللوحة، فانقطاعٌ في منتصف الحفظ يجدها عند الإعادة:
   إن كانت اللوحة قد أخذتها عُدّ نجاحًا، وإلا أُعيد إرسالُ القيم نفسها لا غيرها.
2. **لا نجاحَ بلا تحقّق.** يُعلَن النجاح حين تُظهر اللوحة البيانات الجديدة فعلًا.
   وما لم تسمح به اللوحة أو لم يتأكّد يصير «يحتاج تدخّلًا» — بإشعارٍ وبريد — لا صمتًا.
3. **لا يُفقد خط.** الخط يبقى مسجَّلًا بكل أجزائه وبياناته السابقة، ولا يُحذف إلا بيد
   المشغّل؛ والحذف من هنا لا يلمس اللوحة.

هذا الملف لا يعرف شيئًا عن اللوحات: يُعطى **جسرًا** من xm_lines فيه `change(gate,
rec, pend)` (يغيّر ويتحقّق، أو يرفع Transient/Unsupported) — فيبقى قابلًا للاختبار
وحده. التخزين ملفٌّ لكل حساب في `data/split/<id>.json`. stdlib فقط.
"""
import copy
import datetime
import json
import os
import re
import secrets
import threading

import renew

# الخيارات السريعة لنوع البيع من الخط الأم (بالأشهر)، والخط الأم نفسه: باقات بهذه المدة تُجزّأ.
# ١٢ شهرًا = سنةٌ للعميل من خطٍّ بباقة ١٥ شهرًا، ويبقى بعدها «متبقي ٣ أشهر» للبيع.
# وتُقبل أي مدةٍ أخرى بالأشهر الكاملة («مدة أخرى» في الصفحات — ١٠ أشهر مثلًا) من شهرٍ إلى
# MAX_SLICE: الخيارات السريعة اختصارٌ لا حدّ.
SLICES = (12, 6, 3, 1)
BASE_MONTHS = (15,)
MAX_SLICE = max(BASE_MONTHS) - 1     # أطول جزء: ١٤ شهرًا — والـ١٥ هي الخط كاملًا لا جزءٌ منه
# ما يُختار مسبقًا في «بيع» خطٍّ متاح وفي «إضافة خطٍّ قائم» — ستة أشهر كما كان قبل
# إضافة ١٢، فالنقرة المعتادة لا تبيع سنةً بدل نصفها. الـ١٢ اختيارٌ صريح.
DEFAULT_SLICE = 6
# جزءٌ ينتهي على بُعد هذه الأيام أو أقل من انتهاء الخط نفسه = «بيعُ المتبقي»: لا
# يُغيَّر شيءٌ بعده، فالخط ينتهي من تلقاء نفسه.
FINAL_GRACE_DAYS = 3
MAX_NOTES = 300
RETRY_MINUTES = 30               # إعادة المحاولة بعد عطلٍ عابر (لوحة ساقطة، كود تحقّق)
MAX_TRANSIENT = 48               # ≈ يوم كامل من المحاولات العابرة، ثم «يحتاج تدخّلًا»
MAIL_RETRY_MINUTES = 30
MAIL_MAX_FAILS = 6
MAIL_WAIT_HOURS = 24             # إشعارٌ ينتظر ضبط البريد يومًا، ثم يبقى في الأداة وحدها

# الحالات
ACTIVE = "active"        # جزءٌ مبيع يجري
DUE = "due"              # حان التغيير والتغيير التلقائي معطَّل — ينتظر المشغّل
FAILED = "failed"        # تعذّر التغيير — يحتاج تدخّلًا
AVAILABLE = "available"  # تغيّرت بياناته — متاحٌ للبيع بما تبقّى
SOLD_OUT = "sold_out"    # بيع المتبقي كاملًا — لا تغيير بعده
ENDED = "ended"          # انتهت مدة الخط الأم
STATES = (ACTIVE, DUE, FAILED, AVAILABLE, SOLD_OUT, ENDED)

# ما يُغيَّر عند انتهاء الجزء: اسم المستخدم وحده، وكلمة المرور تبقى كما هي.
CHANGED = "اسم المستخدم"


class Transient(Exception):
    """عطلٌ عابر (لوحة لا تردّ، كود تحقّق، جلسة انتهت): يُعاد تلقائيًا لاحقًا."""


class Unsupported(Exception):
    """اللوحة لا تتيح التغيير من الأداة (لا صفحة تعديل، أو حقلٌ مقفل للموزّع).
    يُرفع **قبل** أي إرسال إلى اللوحة — فلا شيء تغيّر، والتغيير يدويٌّ من اللوحة."""


_lock = threading.RLock()          # يحرس ملفات الحسابات: القراءة والكتابة معًا
_inflight = set()                   # خطوطٌ يجري تغييرها الآن — فلا يُغيَّر خطٌّ مرتين معًا
_inflight_guard = threading.Lock()


# ============================ الوقت ============================
_TZ = datetime.timezone(datetime.timedelta(hours=3))     # توقيت السعودية، كبقية الأداة


def now_dt():
    return datetime.datetime.now(_TZ).replace(tzinfo=None, second=0, microsecond=0)


def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M")


def parse_dt(v):
    """وقتٌ من نصّنا («2026-09-28 14:30») أو تاريخٍ وحده، وإلا None."""
    s = str(v or "").strip().replace("T", " ")
    for f, n in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10)):
        try:
            return datetime.datetime.strptime(s[:n], f)
        except ValueError:
            continue
    return None


def to_date(v):
    """تاريخ انتهاءٍ كما تعطيه أي لوحة: «2027-12-25 22:54» (كاسبر)، «2027-12-31»
    (مرح)، ختمُ يونكس (فالكون)، أو الصيغ المقلوبة. وإلا None."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    s = str(v).strip()
    if re.fullmatch(r"\d{9,11}", s):                      # ختم يونكس بالثواني
        try:
            return datetime.datetime.fromtimestamp(int(s), _TZ).date()
        except (OverflowError, OSError, ValueError):
            return None
    return renew.parse_date(s)


def trust_expiry(panel, reckoned, days=20):
    """تاريخ اللوحة أصدق من حسابنا — إن قاربه. فالصيغ تختلف بين اللوحات (يومٌ/شهرٌ
    مقلوبان، أو تاريخٌ لا يخصّ الخط)، وتاريخٌ بعيدٌ عن المحسوب خطأُ قراءةٍ لا حقيقة."""
    p = to_date(panel)
    if p and reckoned and abs((p - reckoned).days) <= days:
        return p
    return reckoned


def add_months_dt(dt, n):
    return datetime.datetime.combine(renew.add_months(dt.date(), int(n)), dt.time())


def months_left(expiry, today):
    """الأشهر المتبقية حتى الانتهاء، وكسر الشهر يُقرَّب لأعلى (كالتجديد): بعد جزءٍ
    من ستة في خطٍّ من خمسة عشر يبقى تسعة بالضبط، وبعد يومٍ من ذلك يبقى «تسعة» أيضًا."""
    if not expiry or expiry <= today:
        return 0
    return renew.months_between(today, expiry)


def months_ar(n):
    n = int(n or 0)
    if n <= 0:
        return "أقل من شهر"
    if n == 1:
        return "شهر"
    if n == 2:
        return "شهران"
    return ("%d أشهر" % n) if n <= 10 else ("%d شهرًا" % n)


def eligible(months):
    """هل تُجزّأ باقةٌ بهذه المدة؟ (باقات ١٥ شهرًا)"""
    try:
        return int(months or 0) in BASE_MONTHS
    except (TypeError, ValueError):
        return False


_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def parse_months(v):
    """عدد أشهرٍ صحيح من رقمٍ أو نصٍّ مكتوب («10» أو «١٠») ← int، وإلا None (كسرٌ أو كلام)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v) if v.is_integer() else None
    s = str(v if v is not None else "").strip().translate(_AR_DIGITS)
    return int(s) if re.fullmatch(r"\d{1,3}", s) else None


def slice_ok(months, base_months=None):
    """مدةُ جزءٍ صالحة: أشهرٌ كاملة من شهرٍ إلى ما دون مدة الخط الأم (حتى ١٤ من ١٥) — من
    الخيارات السريعة أو غيرها («مدة أخرى»: ١٠ أشهر مثلًا)."""
    base = int(base_months or max(BASE_MONTHS))
    return isinstance(months, int) and not isinstance(months, bool) and 1 <= months < base


def slice_range_text(base_months=None):
    """«من شهر إلى 14 شهرًا» — حدّا مدة الجزء في رسائل الرفض."""
    return "من شهر إلى %s" % months_ar(int(base_months or max(BASE_MONTHS)) - 1)


# ============================ الإعداد ============================
def default_cfg():
    return {
        "auto": True,           # يغيّر النظام اسم المستخدم بنفسه عند انتهاء الجزء
        "remind_days": 3,       # تذكيرٌ قبل انتهاء الجزء بهذه الأيام (٠ = بلا تذكير)
    }


def normalize_cfg(c):
    d = default_cfg()
    if not isinstance(c, dict):
        return d
    d["auto"] = bool(c.get("auto", d["auto"]))
    try:
        d["remind_days"] = max(0, min(30, int(c.get("remind_days", d["remind_days"]))))
    except (TypeError, ValueError):
        pass
    return d


# ============================ التخزين ============================
def _safe(x):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(x or "x"))[:64].strip(".") or "x"


def store_dir(data_dir):
    return os.path.join(data_dir, "split")


def path(data_dir, acct_id):
    return os.path.join(store_dir(data_dir), _safe(acct_id) + ".json")


def _empty():
    return {"cfg": default_cfg(), "lines": {}, "notes": [], "gates": {}, "mail": {}}


def load(data_dir, acct_id):
    try:
        with open(path(data_dir, acct_id), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return _empty()
    if not isinstance(d, dict):
        return _empty()
    for k, v in _empty().items():
        if not isinstance(d.get(k), type(v)):
            d[k] = v
    d["cfg"] = normalize_cfg(d["cfg"])
    return d


def save(data_dir, acct_id, db):
    os.makedirs(store_dir(data_dir), exist_ok=True)
    p = path(data_dir, acct_id)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def has_data(data_dir, acct_id):
    return os.path.exists(path(data_dir, acct_id))


def set_cfg(data_dir, acct_id, cfg):
    with _lock:
        db = load(data_dir, acct_id)
        db["cfg"] = normalize_cfg({**db["cfg"], **(cfg or {})})
        save(data_dir, acct_id, db)
        return db["cfg"]


# ============================ الإشعارات ============================
def _note(db, kind, rec, text, now, mail=True, read=False):
    """إشعارٌ داخل الأداة (يُعدّ في الجرس حتى يُقرأ)، ويُرسَل في بريد الملخّص إن mail.
    read=True سجلٌّ لما فعله المشغّل بيده (بيع جزء): يظهر في القائمة ولا يرفع العدّاد."""
    n = {"id": secrets.token_hex(5), "at": fmt(now), "kind": kind,
         "line": (rec or {}).get("id", ""), "username": (rec or {}).get("username", ""),
         "gate": (rec or {}).get("gate_name", ""), "text": text, "read": bool(read),
         "mail": "pending" if mail else "skip",
         "batch": (rec or {}).get("batch", "")}     # جلسة الخط: تُعرض شارةً تفتح خطوطها
    db["notes"].insert(0, n)
    del db["notes"][MAX_NOTES:]
    return n


def unread(db):
    return sum(1 for n in db.get("notes", []) if not n.get("read"))


def mark_read(data_dir, acct_id, ids=None):
    """يعلّم الإشعارات مقروءة: كلها، أو المعرّفات المعطاة وحدها."""
    with _lock:
        if not has_data(data_dir, acct_id):
            return 0
        db = load(data_dir, acct_id)
        want = set(ids or [])
        n = 0
        for x in db["notes"]:
            if not x.get("read") and (not want or x.get("id") in want):
                x["read"] = True
                n += 1
        if n:
            save(data_dir, acct_id, db)
        return n


# ============================ الخطوط ============================
def _is_final(due, expiry):
    """جزءٌ يبلغ نهاية الخط (أو يقاربها) = بيعُ المتبقي: لا تغيير بعده."""
    return due.date() >= expiry - datetime.timedelta(days=FINAL_GRACE_DAYS)


def _fits(due, expiry):
    return due.date() <= expiry + datetime.timedelta(days=FINAL_GRACE_DAYS)


def _slice(n, months, start, due, customer="", final=False):
    return {"n": int(n), "months": int(months), "start": fmt(start), "due": fmt(due),
            "customer": str(customer or "").strip()[:200], "reminded": False,
            "final": bool(final)}


def find(db, gate_id, username):
    u = str(username or "").strip()
    return next((r for r in db["lines"].values()
                 if r.get("gate_id") == str(gate_id) and r.get("username") == u
                 and r.get("state") != ENDED), None)


def new_batch_id(now=None):
    """معرّف جلسة الإنشاء (دفعةٌ واحدة من صفحة الإنشاء، أو إضافة خطٍّ قائم): «S» ثم
    سنة-شهر-يوم وساعة-دقيقة-ثانية — يُقرأ منه متى تمّت، ويُبحث به في صفحة «حسابات متبقية»
    ويرافق إشعاراتها. الدفعة طلبٌ واحد يأخذ ثوانيَ، فلا تتزاحم جلستان في الثانية نفسها."""
    now = now or now_dt()
    return "S" + now.strftime("%y%m%d-%H%M%S")


def batches(lines, now=None):
    """الجلسات من الخطوط: لكل معرّفٍ وقتُها (أول إنشاء) وعدد خطوطها وبواباتها وأجزاؤها
    وحالاتها — الأحدث أولًا. الخطوط القديمة بلا معرّف لا تُعدّ."""
    out = {}
    for r in lines:
        b = str(r.get("batch") or "")
        if not b:
            continue
        e = out.setdefault(b, {"id": b, "at": r.get("created_at", ""), "n": 0, "gates": [],
                               "months": [], "states": {}, "source": r.get("source", "")})
        e["n"] += 1
        if r.get("created_at") and (not e["at"] or r["created_at"] < e["at"]):
            e["at"] = r["created_at"]
        if r.get("gate_name") and r["gate_name"] not in e["gates"]:
            e["gates"].append(r["gate_name"])
        m = (r.get("slice") or {}).get("months")
        if m and m not in e["months"]:
            e["months"].append(m)
        st = r.get("state", "")
        e["states"][st] = e["states"].get(st, 0) + 1
    return sorted(out.values(), key=lambda e: e["at"], reverse=True)


def register(data_dir, acct_id, gate, username, password, slice_months, *, package="",
             base_months=15, start=None, expiry=None, customer="", line_id="", host="",
             source="create", now=None, batch=""):
    """يسجّل خطًّا أمًّا وأول جزءٍ مبيعٍ منه. يرجّع (السجل، أهو جديد؟).

    الخط نفسه (البوابة واليوزر) لا يُسجَّل مرتين — تُعاد نسخته القائمة. وجزءٌ انتهى
    قبل تسجيله (خطٌّ قديم بتاريخ بيعٍ مضى) لا يُغيَّر تلقائيًا: يُترك «حان التغيير»
    ليقرّر المشغّل، فخطأٌ في التاريخ لا يقطع عميلًا قائمًا."""
    now = now or now_dt()
    username = str(username or "").strip()
    password = str(password or "").strip()
    if not username:
        raise ValueError("اسم المستخدم مطلوب")
    months = parse_months(slice_months)
    if not slice_ok(months, base_months):
        raise ValueError("مدة الجزء بالأشهر الكاملة %s" % slice_range_text(base_months))
    slice_months = months
    start = start or now
    exp = to_date(expiry) or renew.add_months(start.date(), int(base_months or 15))
    due = add_months_dt(start, slice_months)
    if not _fits(due, exp):
        raise ValueError("المتبقي في الخط أقصر من جزء %s" % months_ar(slice_months))
    final = _is_final(due, exp)
    with _lock:
        db = load(data_dir, acct_id)
        old = find(db, gate.get("id"), username)
        if old:
            return old, False
        rid = secrets.token_hex(5)
        while rid in db["lines"]:
            rid = secrets.token_hex(5)
        rec = {
            "id": rid, "account_id": str(acct_id),
            "gate_id": str(gate.get("id", "")), "gate_name": str(gate.get("name", "")),
            "username": username, "password": password, "line_id": str(line_id or ""),
            "host": str(host or gate.get("host", "") or ""),
            "package": str(package or ""), "base_months": int(base_months or 15),
            "created_at": fmt(now), "start": fmt(start), "expiry": exp.isoformat(),
            "state": SOLD_OUT if final else ACTIVE,
            "slice": _slice(1, slice_months, start, due, customer, final),
            "history": [], "pending": None, "attempts": 0, "last_error": "",
            "last_try": "", "next_try": "", "delayed_noted": False, "source": source,
            "batch": str(batch or ""),          # جلسة الإنشاء التي جاء منها (new_batch_id)
        }
        if not final and due <= now:            # جزءٌ انتهى قبل تسجيله: قرار المشغّل
            rec["state"] = DUE
            _note(db, "due_manual", rec,
                  "🔔 الخط %s (%s) — جزء %s انتهى قبل تسجيله في %s؛ غيّر %s من الصفحة أو أكّد."
                  % (username, rec["gate_name"], months_ar(slice_months), rec["slice"]["due"],
                     CHANGED), now, mail=False)
        else:
            _note(db, "sold", rec, _sold_text(rec, exp), now, mail=False, read=True)
        db["lines"][rid] = rec
        save(data_dir, acct_id, db)
        return rec, True


def _key(data_dir, acct_id, rid):
    return (os.path.abspath(data_dir), str(acct_id), str(rid))


def busy(data_dir, acct_id, rid):
    """هل يجري تغيير اسم هذا الخط على اللوحة الآن؟"""
    with _inflight_guard:
        return _key(data_dir, acct_id, rid) in _inflight


def _not_busy(data_dir, acct_id, rid):
    if busy(data_dir, acct_id, rid):
        raise ValueError("جارٍ تغيير هذا الخط على اللوحة الآن — انتظر لحظة ثم أعد")


def _sold_text(rec, exp):
    """سطر السجلّ حين يُباع جزء: ما بِيع، ومتى يتغيّر الاسم، وما يبقى بعده."""
    sl = rec.get("slice") or {}
    who = (" للعميل %s" % sl["customer"]) if sl.get("customer") else ""
    sess = (" · جلسة %s" % rec["batch"]) if rec.get("batch") else ""
    if rec.get("state") == SOLD_OUT:
        return "🆕 بِيع المتبقي من الخط %s (%s)%s — ينتهي %s، ولا تغيير بعده.%s" % (
            rec["username"], rec["gate_name"], who, exp.isoformat(), sess)
    due = parse_dt(sl.get("due"))
    return "🆕 بِيع جزء %s من الخط %s (%s)%s — يتغيّر اسم المستخدم %s، ثم «متبقي %s».%s" % (
        months_ar(sl.get("months")), rec["username"], rec["gate_name"], who, sl.get("due", ""),
        months_ar(months_left(exp, due.date())) if due else "", sess)


def _get(db, rid):
    rec = db["lines"].get(str(rid or ""))
    if not rec:
        raise KeyError("لا خط بهذا المعرّف")
    return rec


def sell(data_dir, acct_id, rid, months, customer="", now=None):
    """يبيع جزءًا جديدًا من خطٍّ متاح: أي مدةٍ بالأشهر الكاملة يتّسع لها الخط (من الخيارات
    السريعة أو غيرها — ١٠ أشهر مثلًا). months=0 = المتبقي كاملًا (لا تغيير بعده)."""
    now = now or now_dt()
    m = parse_months(months if months not in (None, "") else 0)
    if m is None or not 0 <= m <= 999:          # وعددٌ هائل لا يبلغ حساب التواريخ فيُسقطه
        raise ValueError("اكتب مدة البيع بالأشهر الكاملة، أو اختر «المتبقي كاملًا»")
    months = m
    with _lock:
        db = load(data_dir, acct_id)
        rec = _get(db, rid)
        if rec.get("state") != AVAILABLE:
            raise ValueError("الخط غير متاح للبيع الآن")
        exp = to_date(rec.get("expiry"))
        if not exp or exp <= now.date():
            rec["state"] = ENDED
            save(data_dir, acct_id, db)
            raise ValueError("انتهت مدة هذا الخط")
        n = len(rec.get("history") or []) + 1
        if months == 0:
            due = datetime.datetime.combine(exp, now.time())
            rec["slice"] = _slice(n, months_left(exp, now.date()), now, due, customer, final=True)
            rec["state"] = SOLD_OUT
        else:
            due = add_months_dt(now, months)
            if not _fits(due, exp):
                raise ValueError("المتبقي (%s) أقصر من جزء %s — بِع المتبقي كاملًا"
                                 % (months_ar(months_left(exp, now.date())), months_ar(months)))
            final = _is_final(due, exp)
            rec["slice"] = _slice(n, months, now, due, customer, final)
            rec["state"] = SOLD_OUT if final else ACTIVE
        rec.update({"attempts": 0, "last_error": "", "next_try": "", "delayed_noted": False,
                    "available_since": ""})
        _note(db, "sold", rec, _sold_text(rec, exp), now, mail=False, read=True)
        save(data_dir, acct_id, db)
        return rec


def set_customer(data_dir, acct_id, rid, customer):
    with _lock:
        db = load(data_dir, acct_id)
        rec = _get(db, rid)
        if not rec.get("slice"):
            raise ValueError("لا جزء مبيعًا الآن في هذا الخط")
        rec["slice"]["customer"] = str(customer or "").strip()[:200]
        save(data_dir, acct_id, db)
        return rec


def delete(data_dir, acct_id, rid):
    """يُسقط الخط من المتابعة — لا يلمس اللوحة."""
    with _lock:
        _not_busy(data_dir, acct_id, rid)       # لا يُسقط خطٌّ يُغيَّر اسمه في هذه اللحظة
        db = load(data_dir, acct_id)
        rec = db["lines"].pop(str(rid or ""), None)
        if not rec:
            raise KeyError("لا خط بهذا المعرّف")
        save(data_dir, acct_id, db)
        return rec


def _close_slice(db, rec, username, password, now, how):
    """يُغلق الجزء المبيع: يُحفظ في السجل ببياناته القديمة، ويصير الخط متاحًا."""
    sl = rec.get("slice") or {}
    rec.setdefault("history", []).append({
        "n": sl.get("n", len(rec["history"]) + 1), "months": sl.get("months"),
        "start": sl.get("start", ""), "due": sl.get("due", ""),
        "customer": sl.get("customer", ""), "username": rec.get("username", ""),
        "password": rec.get("password", ""), "ended_at": fmt(now), "how": how})
    rec["username"], rec["password"] = username, password
    rec.update({"pending": None, "slice": None, "attempts": 0, "last_error": "",
                "next_try": "", "delayed_noted": False})
    exp = to_date(rec.get("expiry"))
    if not exp or exp <= now.date():
        rec["state"] = ENDED
    else:
        rec["state"] = AVAILABLE
        rec["available_since"] = fmt(now)
    return sl


def confirm_manual(data_dir, acct_id, rid, username="", password="", now=None):
    """المشغّل غيّر اسم المستخدم من اللوحة بيده: يُغلق الجزء بما كتبه (أو بالمقترَح).
    كلمة المرور تبقى كما هي ما لم يكتب غيرها."""
    now = now or now_dt()
    with _lock:
        _not_busy(data_dir, acct_id, rid)       # والتغيير الآلي جارٍ: اللوحة هي الحَكَم بعده
        db = load(data_dir, acct_id)
        rec = _get(db, rid)
        if rec.get("state") not in (ACTIVE, DUE, FAILED):
            raise ValueError("لا جزء مبيعًا ينتظر التغيير في هذا الخط")
        pend = rec.get("pending") or {}
        u = str(username or "").strip() or pend.get("username") or rec["username"]
        p = str(password or "").strip() or rec["password"]
        if u == rec["username"]:
            raise ValueError("اكتب اسم المستخدم الجديد كما غيّرته في اللوحة")
        sl = _close_slice(db, rec, u, p, now, "manual")
        _note(db, "rotated", rec, "✅ أُكِّد تغيير الخط %s (%s) يدويًا — انتهى جزء %s، ومتبقي %s للبيع."
              % (u, rec["gate_name"], months_ar(sl.get("months")),
                 months_ar(months_left(to_date(rec.get("expiry")), now.date()))), now, mail=False)
        save(data_dir, acct_id, db)
        return rec


# ============================ التغيير على اللوحة ============================
def _new_value(digits, avoid):
    digits = max(6, min(20, int(digits or 12)))
    v = avoid
    for _ in range(20):
        v = str(secrets.randbelow(9) + 1) + "".join(str(secrets.randbelow(10)) for _ in range(digits - 1))
        if v != avoid:
            break
    return v


def _new_username(gate, current):
    """اسمٌ جديد بصيغة القديم: أرقامٌ بطوله نفسه (كاسبر ١٠ ومرح ١٢ مثلًا)، وإلا
    بطول البوابة — فلا يبدو غريبًا على اللوحة ولا على العميل."""
    cur = str(current or "")
    if cur.isdigit() and 6 <= len(cur) <= 20:
        n = len(cur)
    else:
        try:
            n = int(gate.get("digits") or 12)
        except (TypeError, ValueError):
            n = 12
    return _new_value(n, cur)


def new_username(gate, current):
    """اسمٌ جديد بصيغة الحالي — للتجربة على خطٍّ تجريبي بالقاعدة نفسها."""
    return _new_username(gate, current)


def record_test(data_dir, acct_id, gate, ok, text, error="", now=None):
    """نتيجة «تجربة على خطٍّ تجريبي»: حالة البوابة (جُرِّبت بنجاح/لم تتح) وإشعارٌ بها.
    فشلٌ عابر (كود تحقّق، لوحة لا تردّ) لا يغيّر حالتها — لم تُجرَّب بعد."""
    now = now or now_dt()
    with _lock:
        db = load(data_dir, acct_id)
        if ok is not None:
            db["gates"][str(gate.get("id", ""))] = {"edit": "ok" if ok else "unsupported",
                                                    "at": fmt(now), "error": "" if ok else error[:300]}
        _note(db, "test", {"gate_name": gate.get("name", "")}, text, now, mail=False)
        save(data_dir, acct_id, db)


def rotate(data_dir, acct_id, rid, gate, bridge, now=None, how="auto"):
    """يغيّر اسم مستخدم الخط على اللوحة (كلمة المرور كما هي) ويُغلق الجزء المبيع.
    يرجّع (السجل، النتيجة) حيث النتيجة: ok · busy · skip · missing · transient · failed.

    ١) الاسم الجديد يُحجز في السجل قبل لمس اللوحة (ويُعاد نفسه عند الإعادة).
    ٢) الجسر يغيّر ويتحقّق؛ أو يرفع Transient (يُعاد لاحقًا) أو Unsupported (لم يُرسَل
       شيء — يدويّ). أي خطأٍ آخر بعد الإرسال = «يحتاج تدخّلًا» وتبقى القيم المحجوزة.
    how: auto (موعده) · now (زرّ «غيّر الآن» من الصفحة)."""
    now = now or now_dt()
    key = _key(data_dir, acct_id, rid)
    with _inflight_guard:
        if key in _inflight:
            return None, "busy"
        _inflight.add(key)
    try:
        with _lock:
            db = load(data_dir, acct_id)
            rec = db["lines"].get(str(rid))
            if not rec:
                return None, "missing"
            if rec.get("state") not in (ACTIVE, DUE, FAILED):
                return rec, "skip"
            prior = rec["state"]
            pend = rec.get("pending")
            if not pend:
                pend = {"username": _new_username(gate, rec["username"]),
                        "password": rec["password"], "at": fmt(now)}
                rec["pending"] = pend
                rec["last_try"] = fmt(now)
                save(data_dir, acct_id, db)
            pend = dict(pend)
            snap = copy.deepcopy(rec)
        try:
            res = bridge.change(gate, snap, pend) or {}
        except Transient as e:
            return _after_fail(data_dir, acct_id, rid, now, str(e), prior, how, transient=True)
        except Unsupported as e:
            return _after_fail(data_dir, acct_id, rid, now, str(e), prior, how, unsupported=True)
        except Exception as e:                  # بعد الإرسال أو غامض: لا إعادة تلقائية
            return _after_fail(data_dir, acct_id, rid, now, str(e) or e.__class__.__name__, prior, how)
        return _after_ok(data_dir, acct_id, rid, pend, res, now, how)
    finally:
        with _inflight_guard:
            _inflight.discard(key)


def undo(data_dir, acct_id, rid, gate, bridge, now=None):
    """«تراجع» عن آخر تغيير اسم: يعيد اسم الخط على اللوحة كما كان (كلمة المرور كما هي)
    ويعيد جزأه المبيع كما كان. يرجّع (السجل، النتيجة): ok · busy · skip · missing ·
    transient · failed. لا تراجع إلا عن خطٍّ «متاح» لم يُبَع بعد التغيير — وإلا قُطع
    عميلٌ جديد. وإن كانت اللوحة قد عادت إلى الاسم القديم (غيّره المشغّل بيده) عُدّ نجاحًا.

    جزءٌ فات موعده يعود «حان التغيير» لا «يجري» — وإلا غيّرته الدورة التالية من جديد."""
    now = now or now_dt()
    key = _key(data_dir, acct_id, rid)
    with _inflight_guard:
        if key in _inflight:
            return None, "busy"
        _inflight.add(key)
    try:
        with _lock:
            db = load(data_dir, acct_id)
            rec = db["lines"].get(str(rid))
            if not rec:
                return None, "missing"
            hist = rec.get("history") or []
            if rec.get("state") != AVAILABLE or not hist:
                return rec, "skip"
            last = hist[-1]
            snap = copy.deepcopy(rec)
            pend = {"username": last.get("username", ""), "password": rec["password"]}
        if not pend["username"] or pend["username"] == snap["username"]:
            return snap, "skip"
        try:
            bridge.change(gate, snap, pend)
        except (Transient, Unsupported, Exception) as e:
            with _lock:
                db = load(data_dir, acct_id)
                cur = db["lines"].get(str(rid))
                if cur:
                    cur["last_error"] = ("تعذّر التراجع: %s" % e)[:300]
                    save(data_dir, acct_id, db)
            kind = "transient" if isinstance(e, Transient) else "failed"
            return cur, kind
        with _lock:
            db = load(data_dir, acct_id)
            rec = db["lines"].get(str(rid))
            if not rec:
                return None, "missing"
            last = rec["history"].pop()
            renamed = rec["username"]
            rec["username"] = last.get("username") or rec["username"]
            due = parse_dt(last.get("due"))
            days = int(db["cfg"].get("remind_days") or 0)
            rec["slice"] = {"n": last.get("n", len(rec["history"]) + 1), "months": last.get("months"),
                            "start": last.get("start", ""), "due": last.get("due", ""),
                            "customer": last.get("customer", ""), "final": False,
                            "reminded": bool(due and days and now >= due - datetime.timedelta(days=days))}
            rec["state"] = ACTIVE if due and due > now else DUE
            rec.update({"pending": None, "attempts": 0, "last_error": "", "next_try": "",
                        "delayed_noted": False, "available_since": ""})
            _note(db, "undo", rec, "↩️ تراجع: عاد اسم الخط %s ← %s (%s)، وجزؤه (%s) %s."
                  % (renamed, rec["username"], rec["gate_name"], months_ar(last.get("months")),
                     ("يجري حتى %s" % last.get("due", "")) if rec["state"] == ACTIVE
                     else "انتهى موعده — ينتظر قرارك"), now, mail=False, read=True)
            save(data_dir, acct_id, db)
            return rec, "ok"
    finally:
        with _inflight_guard:
            _inflight.discard(key)


def _after_ok(data_dir, acct_id, rid, pend, res, now, how):
    with _lock:
        db = load(data_dir, acct_id)
        rec = db["lines"].get(str(rid))
        if not rec:
            return None, "missing"
        if res.get("line_id"):
            rec["line_id"] = str(res["line_id"])
        cur_exp = to_date(rec.get("expiry"))
        rec["expiry"] = trust_expiry(res.get("exp"), cur_exp).isoformat() if cur_exp else rec.get("expiry")
        old = rec["username"]
        sl = _close_slice(db, rec, pend["username"], pend["password"], now, how)
        exp = to_date(rec.get("expiry"))
        who = (" — العميل: %s" % sl.get("customer")) if sl.get("customer") else ""
        if rec["state"] == ENDED:
            text = "✅ تغيّر اسم المستخدم %s ← %s (%s) وانتهت مدة الخط." % (old, rec["username"], rec["gate_name"])
        else:
            text = ("✅ تغيّر اسم المستخدم %s ← %s (%s) — انتهى جزء %s%s، وصار «متبقي %s» جاهزًا للبيع."
                    % (old, rec["username"], rec["gate_name"], months_ar(sl.get("months")), who,
                       months_ar(months_left(exp, now.date()))))
        _note(db, "rotated", rec, text, now, mail=True)
        db["gates"][rec["gate_id"]] = {"edit": "ok", "at": fmt(now), "error": ""}
        save(data_dir, acct_id, db)
        return rec, "ok"


def _after_fail(data_dir, acct_id, rid, now, error, prior, how, transient=False, unsupported=False):
    error = (error or "خطأ غير معروف").strip()[:300]
    with _lock:
        db = load(data_dir, acct_id)
        rec = db["lines"].get(str(rid))
        if not rec:
            return None, "missing"
        rec["attempts"] = int(rec.get("attempts") or 0) + 1
        rec["last_error"] = error
        rec["last_try"] = fmt(now)
        if unsupported:
            rec["pending"] = None               # لم يُرسَل شيء — لا قيمٌ معلّقة على اللوحة
            db["gates"][rec["gate_id"]] = {"edit": "unsupported", "at": fmt(now), "error": error}
        due = parse_dt((rec.get("slice") or {}).get("due"))
        early = how == "now" and prior == ACTIVE and due and now < due
        if early:
            # «غيّر الآن» قبل موعده ولم ينجح: الجزء باقٍ يجري، ويُحاوَل في موعده.
            save(data_dir, acct_id, db)
            return rec, "transient" if transient else "failed"
        if transient and prior == ACTIVE and rec["attempts"] < MAX_TRANSIENT:
            rec["next_try"] = fmt(now + datetime.timedelta(minutes=RETRY_MINUTES))
            if not rec.get("delayed_noted"):
                rec["delayed_noted"] = True
                _note(db, "delayed", rec, "⏳ تأخّر تغيير %s للخط %s (%s): %s — يُعاد تلقائيًا كل %d دقيقة."
                      % (CHANGED, rec["username"], rec["gate_name"], error, RETRY_MINUTES),
                      now, mail=True)
            save(data_dir, acct_id, db)
            return rec, "transient"
        if transient and prior == DUE:
            save(data_dir, acct_id, db)
            return rec, "transient"
        rec["state"] = FAILED
        rec["next_try"] = ""
        if prior != FAILED or how == "auto":
            _note(db, "failed", rec, "⚠️ تعذّر تغيير %s للخط %s (%s): %s — غيّره من اللوحة ثم «أكّدتُ التغيير» في الصفحة."
                  % (CHANGED, rec["username"], rec["gate_name"], error), now, mail=True)
        save(data_dir, acct_id, db)
        return rec, "failed"


# ============================ الدورة ============================
def process(data_dir, acct_id, gates, bridge, now=None, mailer=None, page_url="", title=""):
    """دورةٌ واحدة لحسابٍ واحد: تذكيرُ ما اقترب، وتغييرُ ما حان، وإنهاءُ ما انتهى،
    ثم بريدُ ملخّصٍ واحد بما جدّ. `gates`: {gate_id: gate}."""
    now = now or now_dt()
    todo = []
    with _lock:
        if not has_data(data_dir, acct_id):
            return {"rotated": 0, "failed": 0, "reminded": 0}
        db = load(data_dir, acct_id)
        cfg = db["cfg"]
        changed = False
        reminded = 0
        for rec in db["lines"].values():
            if busy(data_dir, acct_id, rec.get("id")):
                continue                        # يُغيَّر الآن من «غيّر الآن» — نتيجته تكفي
            state = rec.get("state")
            exp = to_date(rec.get("expiry"))
            sl = rec.get("slice") or {}
            if state in (AVAILABLE, SOLD_OUT, DUE, FAILED) and exp and exp <= now.date():
                # انتهت مدة الخط نفسه: لا تغيير بعد اليوم، فالخط ينتهي من تلقاء نفسه.
                rec["state"] = ENDED
                rec["pending"] = None
                changed = True
                if state == AVAILABLE:
                    _note(db, "ended", rec, "⌛ انتهت مدة الخط %s (%s) قبل أن يُباع."
                          % (rec["username"], rec["gate_name"]), now, mail=True)
                continue
            if state != ACTIVE:
                continue
            due = parse_dt(sl.get("due"))
            if not due:
                continue
            if now >= due:
                if not cfg["auto"]:
                    rec["state"] = DUE
                    changed = True
                    _note(db, "due_manual", rec,
                          "🔔 حان تغيير %s للخط %s (%s) — انتهى جزء %s%s. التغيير التلقائي معطَّل: غيّره من الصفحة."
                          % (CHANGED, rec["username"], rec["gate_name"],
                             months_ar(sl.get("months")),
                             (" للعميل %s" % sl["customer"]) if sl.get("customer") else ""),
                          now, mail=True)
                    continue
                nt = parse_dt(rec.get("next_try"))
                if nt and now < nt:
                    continue
                todo.append(rec["id"])
                continue
            days = int(cfg.get("remind_days") or 0)
            if days and not sl.get("reminded") and now >= due - datetime.timedelta(days=days):
                sl["reminded"] = True
                changed = True
                reminded += 1
                left = max(0, (due.date() - now.date()).days)
                _note(db, "due_soon", rec,
                      "⏰ الخط %s (%s) — جزء %s%s ينتهي %s (%s)، ثم %s."
                      % (rec["username"], rec["gate_name"], months_ar(sl.get("months")),
                         (" للعميل %s" % sl["customer"]) if sl.get("customer") else "",
                         sl.get("due", ""), "اليوم" if left == 0 else "بعد %d يوم" % left,
                         ("يتغيّر %s تلقائيًا" % CHANGED) if cfg["auto"]
                         else "حان تغييره يدويًا"),
                      now, mail=True)
        if changed:
            save(data_dir, acct_id, db)
    out = {"rotated": 0, "failed": 0, "reminded": reminded}
    for rid in todo:
        gate = (gates or {}).get(_line_gate(data_dir, acct_id, rid))
        if not gate:
            _after_fail(data_dir, acct_id, rid, now, "البوابة لم تعد موجودة في الحساب", ACTIVE, "auto")
            out["failed"] += 1
            continue
        _rec, res = rotate(data_dir, acct_id, rid, gate, bridge, now=now, how="auto")
        if res == "ok":
            out["rotated"] += 1
        elif res == "failed":
            out["failed"] += 1
    if mailer:
        out["mail"] = flush_mail(data_dir, acct_id, mailer, now=now, page_url=page_url, title=title)
    return out


def _line_gate(data_dir, acct_id, rid):
    with _lock:
        return (load(data_dir, acct_id)["lines"].get(str(rid)) or {}).get("gate_id", "")


# ============================ البريد ============================
_KIND_ORDER = ("failed", "due_manual", "delayed", "rotated", "due_soon", "ended")
_KIND_HEAD = {"failed": "تحتاج تدخّلًا", "due_manual": "حان تغييرها", "delayed": "تأخّر تغييرها",
              "rotated": "تغيّرت بياناتها", "due_soon": "تنتهي قريبًا", "ended": "انتهت"}


def digest(notes, page_url="", title=""):
    """(الموضوع، النص) لبريدٍ واحدٍ يجمع ما جدّ — لا بريدٌ لكل خط. لا كلمة مرور فيه:
    البيانات كاملةً في الصفحة وحدها."""
    by = {}
    for n in notes:
        by.setdefault(n.get("kind", ""), []).append(n)
    parts = ["%s %d" % (_KIND_HEAD.get(k, k), len(by[k])) for k in _KIND_ORDER if by.get(k)]
    subject = "حسابات متبقية: " + " · ".join(parts) if parts else "حسابات متبقية"
    lines = ["حسابات متبقية" + ((" — " + title) if title else ""), ""]
    for k in _KIND_ORDER:
        for n in by.get(k, []):
            lines.append("• " + n.get("text", ""))
    lines.append("")
    if page_url:
        lines.append("افتح الصفحة لنسخ البيانات الجديدة وبيع الخطوط المتاحة:")
        lines.append(page_url)
    return subject, "\n".join(lines) + "\n"


def mail_hint(err):
    """شرحٌ بالعربية لأشهر أخطاء خادم البريد (SMTP)، ليعرف المشغّل ما يُصلح — أو ""."""
    e = str(err or "").lower()
    if not e or "غير مضبوط" in e:
        return ""
    has = lambda *ks: any(k in e for k in ks)
    if has("smtp auth extension not supported"):
        return "الخادم لا يقبل الدخول قبل التشفير — استخدم المنفذ 587 مع STARTTLS، أو 465."
    if has("535", "534", "5.7.8", "5.7.9", "username and password not accepted", "authentication",
           "invalid login", "application-specific", "bad credentials", "auth failed"):
        return ("خادم البريد رفض اسم الدخول أو كلمة المرور. في Gmail أو Google Workspace أو Zoho "
                "مع التحقّق الثنائي تلزم «كلمة مرور التطبيقات» لا كلمة المرور العادية.")
    if has("wrong_version_number", "wrong version number", "unknown protocol", "ssl", "tls"):
        return "المنفذ ونوع التشفير لا يتطابقان: 465 للاتصال المشفَّر (SSL)، و587 مع STARTTLS."
    if has("name or service not known", "nodename nor servname", "getaddrinfo",
           "no address associated", "temporary failure in name resolution"):
        return "اسم خادم SMTP غير صحيح — تأكّد منه (مثل smtp.gmail.com أو smtp.zoho.com)."
    if has("timed out", "timeout", "connection refused", "network is unreachable",
           "no route to host", "errno 111", "errno 110", "errno 113"):
        return ("لم يصل السيرفر إلى خادم البريد على هذا المنفذ — جرّب المنفذ الآخر (465 أو 587)، "
                "أو تحقّق أن مزوّد السيرفر لا يحجب منافذ البريد.")
    if has("550", "553", "554", "5.7.1", "sender", "relay", "not owned"):
        return "خادم البريد رفض المُرسِل أو المستلم — اجعل «المُرسِل» هو بريد اسم الدخول نفسه."
    return ""


def mail_verified(data_dir, acct_id):
    """نجح بريدٌ تجريبي: البريد يعمل الآن — تُمحى أخطاؤه القديمة ويُرسَل المنتظر فورًا
    بلا انتظار موعد إعادة المحاولة."""
    with _lock:
        if not has_data(data_dir, acct_id):
            return
        db = load(data_dir, acct_id)
        db["mail"].update({"last_error": "", "fails": 0, "next_try": ""})
        save(data_dir, acct_id, db)


def flush_mail(data_dir, acct_id, mailer, now=None, page_url="", title=""):
    """يرسل الإشعارات المنتظرة في بريدٍ واحد. mailer(subject, body) → (ok, error)؛
    ok=None = البريد غير مضبوط: تنتظر الإشعارات يومًا (MAIL_WAIT_HOURS) ثم تُترك."""
    now = now or now_dt()
    with _lock:
        if not has_data(data_dir, acct_id):
            return None
        db = load(data_dir, acct_id)
        pend = [n for n in db["notes"] if n.get("mail") == "pending"]
        if not pend:
            return None
        nt = parse_dt(db["mail"].get("next_try"))
        if nt and now < nt:
            return None
    subject, body = digest(list(reversed(pend)), page_url, title)
    try:
        ok, err = mailer(subject, body)
    except Exception as e:                      # البريد لا يُسقط الدورة
        ok, err = False, str(e)[:200]
    ids = {n["id"] for n in pend}
    with _lock:
        db = load(data_dir, acct_id)
        m = db["mail"]
        if ok is None:
            # البريد غير مضبوط بعد: تنتظر الإشعارات يومًا (فضبطُه بعدها بقليلٍ يُوصلها)،
            # ثم تُترك في الأداة وحدها — فلا يصل سيلُ إشعاراتٍ قديمة يوم يُضبط. ويُعاد
            # الفحص كل دورة: معرفة الضبط لا تكلّف شيئًا، والانتظار يؤخّر البريد بعد ضبطه.
            m.update({"last_error": err or "بريد التذكير غير مضبوط", "next_try": ""})
            for n in db["notes"]:
                if n.get("id") in ids:
                    at = parse_dt(n.get("at"))
                    old = not at or now - at > datetime.timedelta(hours=MAIL_WAIT_HOURS)
                    n["mail"] = "skip" if old else "pending"
            save(data_dir, acct_id, db)
            return ok
        elif ok:
            mark = "sent"
            m.update({"last_sent": fmt(now), "last_error": "", "fails": 0, "next_try": ""})
        else:
            m["fails"] = int(m.get("fails") or 0) + 1
            m["last_error"] = str(err or "تعذّر الإرسال")[:200]
            if m["fails"] >= MAIL_MAX_FAILS:
                mark, m["fails"], m["next_try"] = "failed", 0, ""
            else:
                mark = "pending"
                m["next_try"] = fmt(now + datetime.timedelta(minutes=MAIL_RETRY_MINUTES))
        for n in db["notes"]:
            if n.get("id") in ids:
                n["mail"] = mark
        save(data_dir, acct_id, db)
    return ok


# ============================ العرض ============================
def decorate(rec, now=None):
    """السجل للعرض: مع المتبقي وموعد الجزء محسوبين الآن."""
    now = now or now_dt()
    out = copy.deepcopy(rec)
    exp = to_date(rec.get("expiry"))
    out["remaining_months"] = months_left(exp, now.date())
    out["remaining_days"] = max(0, (exp - now.date()).days) if exp else 0
    sl = rec.get("slice") or {}
    due = parse_dt(sl.get("due"))
    if due:
        out["due_in_days"] = (due.date() - now.date()).days
        out["remaining_after"] = months_left(exp, due.date())
    # أنواع البيع المتاحة لهذا الخط الآن (ما يتّسع له المتبقي): الخيارات السريعة، وأطول مدةٍ
    # بالأشهر الكاملة يتّسع لها — حدّ «مدة أخرى» عند بيعه.
    if rec.get("state") == AVAILABLE and exp:
        out["can_sell"] = [m for m in SLICES if _fits(add_months_dt(now, m), exp)]
        out["max_sell"] = _max_fit(now, exp)
    return out


def _max_fit(now, exp):
    m = 0
    while m < 60 and _fits(add_months_dt(now, m + 1), exp):
        m += 1
    return m


def view(data_dir, acct_id, now=None):
    now = now or now_dt()
    db = load(data_dir, acct_id)
    lines = [decorate(r, now) for r in db["lines"].values()]
    return {"cfg": db["cfg"], "lines": lines, "notes": db["notes"][:100], "batches": batches(lines),
            "unread": unread(db), "gates": db["gates"], "mail": db["mail"],
            "slices": list(SLICES), "default_slice": DEFAULT_SLICE, "max_slice": MAX_SLICE,
            "base_months": list(BASE_MONTHS)}

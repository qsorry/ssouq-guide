#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
تجديد اشتراك قائم على سيرفر مرح — القاعدة والطابور والتنبيه.

العميل يثبت ملكيته لاشتراك سابق (برقم طلبه وجواله، أو بيوزر اشتراكه)، فنحسب
**ما تبقّى** له (تاريخ الشراء + مدة الباقة − اليوم) وننشئ له خطًّا على مرح
**بنفس اليوزر والباسورد**، ولا يتغيّر إلا الهوست.

ثلاث ضمانات تحكم هذا الملف:

1. **لا يُنشأ يوزر مرتين.** لكل طلبٍ مفتاحٌ ثابت يُحجز في القاعدة *قبل* لمس
   مرح، فانقطاعٌ في منتصف النداء يجد المفتاح محجوزًا عند إعادة المحاولة لا
   فارغًا. وقبل الإنشاء نسأل مرح نفسها: أهذا اليوزر عندك؟ فإن كان — وهي حالة
   الردّ الضائع بعد إنشاء ناجح — نعدّه نجاحًا ولا ننشئ ثانيًا.
2. **الانقطاع لا يُضيع العميل.** إن تعذّر الوصول لمرح يبقى الطلب `queued`
   ويُقال للعميل إن اشتراكه يُفعَّل خلال ١٢ ساعة (رقم قابل للضبط)، ويصلنا
   بريد بأن الوصل مقطوع.
3. **العودة تُفرِّغ الطابور.** خيطٌ دوريّ يعيد المحاولة، فما إن يعود الوصل
   حتى تُنشأ المعلّقات تباعًا بلا تدخّل.

stdlib فقط. لا يُسجَّل سرّ ولا يُرسَل في بريد.
"""
import datetime
import hashlib
import json
import os
import re
import secrets
import smtplib
import threading
import time
from email.message import EmailMessage
from email.utils import formatdate

# باقات المتجر المتاحة للإنشاء، تصاعديًا. المتبقّي يُرقّى لأصغر باقة تغطّيه.
TIERS = (1, 3, 6, 12, 15, 30)
DAYS_PER_MONTH = 30.4375
MAX_ATTEMPTS = 60                 # بعدها يُعلَّم الطلب `stuck` ولا يُنسى
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

_db_lock = threading.RLock()      # يحرس ملف القاعدة: الحجز والكتابة معًا


# ============================ الإعداد ============================
def default_config():
    return {
        "enabled": False,
        "dry_run": True,
        # اللوحة التي يُبحث فيها عن اشتراك العميل الحالي (لاستخراج الباسورد والانتهاء)
        "source": {"account_id": "", "gate_id": ""},
        # مرح: وجهة الإنشاء
        "target": {"account_id": "", "gate_id": ""},
        # مدة → باقة على مرح: {"6": {"id": "...", "name": "..."}}
        "packages": {},
        "promise_hours": 12,        # ما يُقال للعميل عند الانقطاع
        "retry_minutes": 10,        # كل كم يُعاد تفريغ الطابور
        "rate_per_hour": 12,        # محاولات التعرّف لكل عنوان، منعًا لتخمين أرقام الطلبات
        "alert": {"host": "", "port": 587, "user": "", "password": "",
                  "from": "", "to": "", "tls": True, "gap_minutes": 30},
    }


_SECRET_KEYS = ("password",)        # داخل alert: لا يُرسَل للمتصفح ولا يُمسح بالفراغ


def normalize_config(cfg):
    d = default_config()
    if not isinstance(cfg, dict):
        return d
    for k in ("enabled", "dry_run"):
        d[k] = bool(cfg.get(k, d[k]))
    for side in ("source", "target"):
        got = cfg.get(side) if isinstance(cfg.get(side), dict) else {}
        d[side] = {"account_id": str(got.get("account_id", "") or "").strip(),
                   "gate_id": str(got.get("gate_id", "") or "").strip()}
    pk = cfg.get("packages") if isinstance(cfg.get("packages"), dict) else {}
    d["packages"] = {str(m): {"id": str(v.get("id", "") or "").strip(),
                              "name": str(v.get("name", "") or "").strip()}
                     for m, v in pk.items()
                     if isinstance(v, dict) and str(m).isdigit() and v.get("id")}
    for k, lo, hi in (("promise_hours", 1, 240), ("retry_minutes", 1, 1440),
                      ("rate_per_hour", 1, 10000)):
        try:
            d[k] = max(lo, min(hi, int(cfg.get(k, d[k]))))
        except (TypeError, ValueError):
            pass
    al = cfg.get("alert") if isinstance(cfg.get("alert"), dict) else {}
    d["alert"].update({
        "host": str(al.get("host", "") or "").strip(),
        "user": str(al.get("user", "") or "").strip(),
        "password": str(al.get("password", "") or ""),
        "from": str(al.get("from", "") or "").strip(),
        "to": str(al.get("to", "") or "").strip(),
        "tls": bool(al.get("tls", True)),
    })
    try:
        d["alert"]["port"] = max(1, min(65535, int(al.get("port", 587))))
    except (TypeError, ValueError):
        pass
    return d


def clean_config(new, old):
    """يبني الإعداد ويُبقي السرّ حين يُترك الحقل فارغًا (كبقية أسرار الأداة)."""
    o, n = normalize_config(old), normalize_config(new)
    for k in _SECRET_KEYS:
        if not n["alert"][k]:
            n["alert"][k] = o["alert"][k]
    return n


def redact_config(cfg):
    """نسخة صالحة للمتصفح: بلا كلمة مرور البريد."""
    c = normalize_config(cfg)
    a = dict(c["alert"])
    a["has_password"] = bool(a.pop("password", ""))
    return {**c, "alert": a}


# ============================ أدوات ============================
def now_iso():
    tz = datetime.timezone(datetime.timedelta(hours=3))       # توقيت السعودية
    return datetime.datetime.now(tz).strftime("%Y-%m-%d %H:%M")


def _today():
    tz = datetime.timezone(datetime.timedelta(hours=3))
    return datetime.datetime.now(tz).date()


def norm_phone(p):
    """أرقام الجوال بصيغة واحدة: 05x و+9665x و009665x تصير 9665x."""
    d = re.sub(r"\D", "", str(p or "").translate(_AR_DIGITS))
    if d.startswith("00"):
        d = d[2:]
    if d.startswith("0") and len(d) == 10:
        d = "966" + d[1:]
    return d


def norm_order(o):
    return re.sub(r"\D", "", str(o or "").translate(_AR_DIGITS))


def parse_date(s):
    s = str(s or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def add_months(d, n):
    y, m = divmod((d.month - 1) + int(n), 12)
    y += d.year
    m += 1
    leap = y % 4 == 0 and (y % 100 or y % 400 == 0)
    last = (31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[m - 1]
    return datetime.date(y, m, min(d.day, last))


def months_between(start, end):
    """أشهرٌ تقويمية من `start` إلى `end`، وكسرُ الشهر يُقرَّب لأعلى.

    القسمة على ٣٠ لا تصلح هنا: من ٢٣ مارس إلى ٢٣ سبتمبر ١٨١ يومًا، فتعطي
    القسمةُ سبعةَ أشهر وهي ستة بالتقويم — وشهرٌ زائد يقفز بالعميل إلى باقة
    أغلى ويُحمّلنا فرقها في خمسة آلاف حالة."""
    n = (end.year - start.year) * 12 + (end.month - start.month)
    if add_months(start, n) > end:
        n -= 1
    return n if add_months(start, n) == end else n + 1


def tier_for(months):
    """أصغر باقة تغطّي المتبقّي. ما فوق أطول باقة يُقصّ إليها."""
    return next((t for t in TIERS if t >= months), TIERS[-1])


def plan_from_expiry(expiry, today=None):
    """من تاريخ انتهاء معروف → المتبقّي والباقة المطلوبة."""
    today = today or _today()
    if not expiry:
        return None
    days = (expiry - today).days
    if days <= 0:
        return {"expiry": expiry.isoformat(), "days": days, "months": 0,
                "tier": 0, "expired": True}
    months = max(1, months_between(today, expiry))
    return {"expiry": expiry.isoformat(), "days": days, "months": months,
            "tier": tier_for(months), "expired": False}


# ============================ فهرس الطلبات ============================
def index_path(data_dir):
    return os.path.join(data_dir, "renew_index.json")


def load_index(data_dir):
    try:
        with open(index_path(data_dir), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("orders"), dict) else {"orders": {}}
    except (OSError, ValueError):
        return {"orders": {}}


def index_stats(data_dir):
    d = load_index(data_dir)
    return {"count": len(d.get("orders", {})), "built": d.get("built", ""),
             "source_files": d.get("source_files", 0)}


def find_order(data_dir, order_no, phone):
    """طلبٌ يطابق الرقم والجوال معًا. الجوال شرطٌ لا زينة: بدونه يصير رقم الطلب
    وحده مفتاحًا يُخمَّن."""
    rec = load_index(data_dir).get("orders", {}).get(norm_order(order_no))
    if not rec:
        return None
    if norm_phone(rec.get("phone")) != norm_phone(phone):
        return None
    return rec


def plan_from_order(rec, today=None):
    """طلبٌ من الفهرس → المتبقّي والباقة المطلوبة."""
    bought = parse_date(rec.get("date"))
    months = int(rec.get("months") or 0)
    if not bought or not months:
        return None
    p = plan_from_expiry(add_months(bought, months), today)
    if p:
        p.update({"bought": bought.isoformat(), "package_months": months,
                  "devices": int(rec.get("devices") or 1)})
    return p


# ============================ قاعدة الطلبات ============================
def db_path(data_dir):
    return os.path.join(data_dir, "renewals.json")


def _empty_db():
    return {"claims": {}, "by_user": {}, "by_ticket": {}, "alert_at": "", "rate": {}}


def load_db(data_dir):
    try:
        with open(db_path(data_dir), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return _empty_db()
    if not isinstance(d, dict):
        return _empty_db()
    base = _empty_db()
    for k, v in base.items():
        if not isinstance(d.get(k), type(v)):
            d[k] = v
    return d


def save_db(data_dir, db):
    os.makedirs(data_dir, exist_ok=True)
    tmp = db_path(data_dir) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=1)
    os.replace(tmp, db_path(data_dir))


def claim_key(order_no="", username=""):
    """مفتاح ثابت للطلب الواحد: رقم الطلب إن وُجد، وإلا اليوزر. الثبات هو ما
    يمنع الإنشاء مرتين — نفس المدخلات تعطي نفس المفتاح دائمًا."""
    o = norm_order(order_no)
    if o:
        return "o:" + o
    u = str(username or "").strip().lower()
    return "u:" + u if u else ""


def public_view(rec, promise_hours=12):
    """ما يراه العميل: حالته وخطّه، بلا أي أثر داخلي."""
    if not rec:
        return None
    out = {"ticket": rec.get("ticket", ""), "state": rec.get("state", ""),
           "months": rec.get("months", 0), "tier": rec.get("tier", 0),
           "expiry": rec.get("expiry", ""), "at": rec.get("at", ""),
           "promise_hours": promise_hours}
    if rec.get("state") == "done":
        out.update({"username": rec.get("username", ""), "password": rec.get("password", ""),
                    "host": rec.get("host", ""), "line": rec.get("line", ""),
                    "new_expiry": rec.get("new_expiry", ""), "done_at": rec.get("done_at", "")})
    return out


# ============================ البريد ============================
def _smtp_send(alert, subject, body):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = alert.get("from") or alert.get("user")
    msg["To"] = alert.get("to")
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(body)
    port = int(alert.get("port") or 587)
    if port == 465:
        with smtplib.SMTP_SSL(alert["host"], port, timeout=20) as s:
            if alert.get("user"):
                s.login(alert["user"], alert.get("password") or "")
            s.send_message(msg)
        return
    with smtplib.SMTP(alert["host"], port, timeout=20) as s:
        if alert.get("tls", True):
            s.starttls()
        if alert.get("user"):
            s.login(alert["user"], alert.get("password") or "")
        s.send_message(msg)


def alert_disconnect(data_dir, cfg, reason, pending):
    """بريدٌ واحد لكل انقطاع، لا بريدٌ لكل عميل: بين رسالتين فجوة `gap_minutes`.
    يرجّع (أُرسل؟، سبب عدم الإرسال)."""
    alert = normalize_config(cfg)["alert"]
    if not (alert.get("host") and alert.get("to")):
        return False, "بريد التنبيه غير مضبوط"
    gap = int(alert.get("gap_minutes") or 30) * 60
    with _db_lock:
        db = load_db(data_dir)
        last = db.get("alert_at", "")
        if last:
            try:
                prev = datetime.datetime.strptime(last, "%Y-%m-%d %H:%M")
                tz = datetime.timezone(datetime.timedelta(hours=3))
                if (datetime.datetime.now(tz).replace(tzinfo=None) - prev).total_seconds() < gap:
                    return False, "أُرسل تنبيه قريب"
            except ValueError:
                pass
        db["alert_at"] = now_iso()
        save_db(data_dir, db)
    body = (
        "انقطع الاتصال بين سيرفر الأداة ولوحة مرح، فتوقّف إنشاء يوزرات التجديد.\n\n"
        "السبب كما ورد من اللوحة:\n  %s\n\n"
        "طلبات معلّقة الآن: %d\n"
        "الوقت: %s\n\n"
        "ما إن يعود الاتصال حتى تُنشأ المعلّقات تلقائيًا — لا حاجة لتدخّل يدوي.\n"
        "لتسريع ذلك: افتح https://admin.ssouq.com/ وسجّل الدخول لبوابة مرح\n"
        "(قد تكون الجلسة انتهت أو تطلب اللوحة كود تحقّق).\n"
    ) % (str(reason)[:400], pending, now_iso())
    try:
        _smtp_send(alert, "تنبيه: انقطاع الاتصال بلوحة مرح — %d طلب معلّق" % pending, body)
        return True, ""
    except Exception as e:                      # البريد لا يُسقط التجديد
        return False, str(e)[:200]


# ============================ التنفيذ ============================
class Provisioner:
    """الجسر إلى xm_lines: نداءان فقط، ليبقى هذا الملف قابلًا للاختبار وحده.

    exists(gate, username) → هل اليوزر موجود على اللوحة؟
    create(gate, pkg, username, password) → ينشئ ويرجّع {line, username, password, ...}
    """

    def __init__(self, exists, create, find_gate):
        self.exists = exists
        self.create = create
        self.find_gate = find_gate


def gate_allowed(gate):
    """فالكون خارج التجديد: لوحته قائمة بذاتها ولا يُنقل عملاؤها إلى مرح.
    يرجّع (مسموح؟، السبب)."""
    if not gate:
        return False, "البوابة غير موجودة"
    if str(gate.get("mode", "")).lower() == "falcon":
        return False, "اشتراكات فالكون خارج نطاق هذا التجديد"
    return True, ""


def _gate_of(prov, st, side_cfg):
    acct = next((a for a in st.get("accounts", [])
                 if str(a.get("id")) == str(side_cfg.get("account_id"))), None)
    return prov.find_gate(acct, side_cfg.get("gate_id")) if acct else None


def provision(data_dir, st, cfg, prov, rec):
    """ينفّذ طلبًا واحدًا على مرح. لا يُنشئ أبدًا ما هو منشأ:

    1. اليوزر موجود على مرح؟ → نجاح بلا إنشاء (حالة الردّ الضائع).
    2. وإلا يُنشأ بنفس اليوزر والباسورد.

    يرجّع السجل بعد تحديثه. الانقطاع يتركه `queued` ولا يرفع استثناء."""
    cfg = normalize_config(cfg)
    gate = _gate_of(prov, st, cfg["target"])
    if not gate:
        return _finish(data_dir, rec, state="queued",
                       error="بوابة مرح غير مضبوطة في إعداد التجديد")
    ok, why = gate_allowed(gate)
    if not ok:                                  # إعدادٌ خاطئ لا انقطاع: لا يُعاد تلقائيًا
        return _finish(data_dir, rec, state="rejected", error=why)
    pkg_cfg = cfg["packages"].get(str(rec.get("tier")))
    if not pkg_cfg:
        return _finish(data_dir, rec, state="queued",
                       error="لا باقة مربوطة لمدة %s شهر" % rec.get("tier"))
    if cfg.get("dry_run"):
        return _finish(data_dir, rec, state="done", host=gate.get("host", ""),
                       line="Host %s User %s Pass %s" % (gate.get("host", ""),
                                                         rec["username"], rec["password"]),
                       dry=True)
    try:
        if prov.exists(gate, rec["username"]):
            # أُنشئ في محاولة سابقة وضاع ردّها. لا نُنشئ ثانيًا.
            return _finish(data_dir, rec, state="done", host=gate.get("host", ""),
                           line="Host %s User %s Pass %s" % (gate.get("host", ""),
                                                             rec["username"], rec["password"]),
                           note="كان موجودًا على مرح")
        r = prov.create(gate, {"id": pkg_cfg["id"], "name": pkg_cfg.get("name", ""),
                               "bouquets": [], "max_connections": rec.get("devices", 1)},
                        rec["username"], rec["password"])
    except Exception as e:
        return _finish(data_dir, rec, state="queued", error=str(e)[:300])
    return _finish(data_dir, rec, state="done", host=gate.get("host", ""),
                   line=r.get("line", ""), new_expiry=r.get("expiry", ""))


def _finish(data_dir, rec, state, error="", **extra):
    with _db_lock:
        db = load_db(data_dir)
        cur = db["claims"].get(rec["key"], rec)
        if cur.get("state") == "done":          # لا نتراجع عن نجاح مسجَّل
            return cur
        cur.update(extra)
        cur["attempts"] = int(cur.get("attempts", 0)) + 1
        cur["last_error"] = error
        cur["last_try"] = now_iso()
        if state == "done":
            cur["state"] = "done"
            cur["done_at"] = now_iso()
        elif state == "rejected":
            cur["state"] = "rejected"           # خطأ إعداد، لا انقطاع
        elif cur["attempts"] >= MAX_ATTEMPTS:
            cur["state"] = "stuck"              # لا يُعاد تلقائيًا، ولا يُحذف
        else:
            cur["state"] = "queued"
        db["claims"][rec["key"]] = cur
        save_db(data_dir, db)
        return cur


def submit(data_dir, st, cfg, prov, *, order_no="", phone="", username="", password="",
           months=0, tier=0, expiry="", devices=1, source=""):
    """يسجّل طلب تجديد ثم ينفّذه. يرجّع (السجل، أهو جديد؟).

    الحجز يسبق النداء: السجل يُكتب `queued` أولًا، فلو مات الخادم في منتصف
    الإنشاء وجدت المحاولةُ التالية المفتاحَ محجوزًا لا فارغًا."""
    cfg = normalize_config(cfg)
    key = claim_key(order_no, username)
    if not key:
        return None, False
    uname = str(username or "").strip()
    with _db_lock:
        db = load_db(data_dir)
        # المفتاح نفسه — أو اليوزر نفسه من مدخلٍ آخر: كلاهما يردّ السجل القائم.
        existing = db["claims"].get(key) or db["claims"].get(db["by_user"].get(uname.lower(), ""))
        if existing:
            return existing, False
        ticket = secrets.token_urlsafe(9)
        rec = {"key": key, "ticket": ticket, "state": "queued",
               "order": norm_order(order_no), "phone": norm_phone(phone),
               "username": uname, "password": str(password or ""),
               "months": int(months), "tier": int(tier), "expiry": expiry,
               "devices": int(devices or 1), "via": source,
               "at": now_iso(), "attempts": 0, "last_error": "", "line": "", "host": ""}
        db["claims"][key] = rec
        if uname:
            db["by_user"][uname.lower()] = key
        db["by_ticket"][ticket] = key
        save_db(data_dir, db)
    return provision(data_dir, st, cfg, prov, rec), True


def by_ticket(data_dir, ticket):
    db = load_db(data_dir)
    return db["claims"].get(db["by_ticket"].get(str(ticket or ""), ""))


def pending(data_dir):
    return [r for r in load_db(data_dir)["claims"].values() if r.get("state") == "queued"]


def run_queue(data_dir, st, cfg, prov, limit=25):
    """يفرّغ الطابور. أول فشل اتصال يوقف الجولة — اللوحة ما زالت مقطوعة،
    والاستمرار يراكم محاولات فاشلة على كل الطلبات بلا فائدة."""
    cfg = normalize_config(cfg)
    if not cfg.get("enabled"):
        return {"ran": 0, "done": 0, "left": len(pending(data_dir)), "skipped": "معطّل"}
    rows = sorted(pending(data_dir), key=lambda r: r.get("at", ""))[:limit]
    done = ran = 0
    for rec in rows:
        out = provision(data_dir, st, cfg, prov, rec)
        ran += 1
        if out.get("state") == "done":
            done += 1
        elif out.get("last_error"):
            break
    left = len(pending(data_dir))
    return {"ran": ran, "done": done, "left": left}


# ============================ حدّ المحاولات ============================
def rate_ok(data_dir, ip, limit_per_hour):
    """يمنع تخمين أرقام الطلبات: عدّاد بالساعة لكل عنوان، مُجزّأ لا مخزَّنًا."""
    if not ip:
        return True
    tag = hashlib.sha256(str(ip).encode()).hexdigest()[:16]
    hour = datetime.datetime.utcnow().strftime("%Y%m%d%H")
    with _db_lock:
        db = load_db(data_dir)
        rate = db.get("rate") or {}
        rate = {k: v for k, v in rate.items() if k.endswith(hour)}   # ساعة واحدة تكفي
        k = tag + ":" + hour
        n = int(rate.get(k, 0)) + 1
        rate[k] = n
        db["rate"] = rate
        save_db(data_dir, db)
    return n <= int(limit_per_hour or 12)


# ============================ التحليل المحفوظ ============================
def analysis_path(data_dir):
    return os.path.join(data_dir, "renew_analysis.json")


def load_analysis(data_dir):
    try:
        with open(analysis_path(data_dir), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _write_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def save_analysis(data_dir, agg):
    _write_json(analysis_path(data_dir), agg)


def save_index(data_dir, index):
    _write_json(index_path(data_dir), index)

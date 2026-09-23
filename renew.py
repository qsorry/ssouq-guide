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
        # كوكيز جلسة لوحة سلة، يلصقها المشغّل من متصفّحه. لا كلمة مرور ولا
        # دخول آلي: اللوحة محميّة بتحقّق ثنائي وأتمتته عبثٌ وخطر.
        "panel_cookie": "",
    }


_SECRET_KEYS = ("password",)        # داخل alert: لا يُرسَل للمتصفح ولا يُمسح بالفراغ
_TOP_SECRETS = ("panel_cookie",)    # سرٌّ في جذر الإعداد، بالحكم نفسه


def _num(v):
    """رقمٌ أو فراغ. الفراغ «غير معروف» لا صفرًا — وصفرُ النقاط باقةٌ مجانية."""
    if v is None or str(v).strip() == "":
        return ""
    try:
        return round(float(str(v).strip()), 3)
    except (TypeError, ValueError):
        return ""


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
                              "name": str(v.get("name", "") or "").strip(),
                              "credits": _num(v.get("credits"))}
                     for m, v in pk.items()
                     if isinstance(v, dict) and str(m).isdigit() and v.get("id")}
    for k, lo, hi in (("promise_hours", 1, 240), ("retry_minutes", 1, 1440),
                      ("rate_per_hour", 1, 10000)):
        try:
            d[k] = max(lo, min(hi, int(cfg.get(k, d[k]))))
        except (TypeError, ValueError):
            pass
    d["panel_cookie"] = str(cfg.get("panel_cookie", "") or "")
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
    for k in _TOP_SECRETS:
        if not n[k]:
            n[k] = o[k]
    return n


def redact_config(cfg):
    """نسخة صالحة للمتصفح: بلا كلمة مرور البريد."""
    c = normalize_config(cfg)
    a = dict(c["alert"])
    a["has_password"] = bool(a.pop("password", ""))
    out = {**c, "alert": a}
    out["has_panel_cookie"] = bool(out.pop("panel_cookie", ""))
    return out


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


def send_alert(data_dir, cfg, subject, body, kind="disconnect"):
    """بريدٌ واحد لكل حدث، لا بريدٌ لكل عميل: لكل نوعٍ خانقُه المستقل، فانتهاءُ
    جلسة اللوحة لا يبتلع تنبيهَ انقطاع مرح ولا العكس."""
    alert = normalize_config(cfg)["alert"]
    if not (alert.get("host") and alert.get("to")):
        return False, "بريد التنبيه غير مضبوط"
    gap = int(alert.get("gap_minutes") or 30) * 60
    key = "alert_at" if kind == "disconnect" else "alert_at_" + kind
    with _db_lock:
        db = load_db(data_dir)
        last = db.get(key, "")
        if last:
            try:
                prev = datetime.datetime.strptime(last, "%Y-%m-%d %H:%M")
                tz = datetime.timezone(datetime.timedelta(hours=3))
                if (datetime.datetime.now(tz).replace(tzinfo=None) - prev).total_seconds() < gap:
                    return False, "أُرسل تنبيه قريب"
            except ValueError:
                pass
        db[key] = now_iso()
        save_db(data_dir, db)
    try:
        _smtp_send(alert, subject, body)
        return True, ""
    except Exception as e:                      # البريد لا يُسقط التجديد
        return False, str(e)[:200]


def alert_disconnect(data_dir, cfg, reason, pending):
    """انقطاع الوصل بمرح: الطلبات معلّقة حتى يعود."""
    body = (
        "انقطع الاتصال بين سيرفر الأداة ولوحة مرح، فتوقّف إنشاء يوزرات التجديد.\n\n"
        "السبب كما ورد من اللوحة:\n  %s\n\n"
        "طلبات معلّقة الآن: %d\n"
        "الوقت: %s\n\n"
        "ما إن يعود الاتصال حتى تُنشأ المعلّقات تلقائيًا — لا حاجة لتدخّل يدوي.\n"
        "لتسريع ذلك: افتح https://admin.ssouq.com/ وسجّل الدخول لبوابة مرح\n"
        "(قد تكون الجلسة انتهت أو تطلب اللوحة كود تحقّق).\n"
    ) % (str(reason)[:400], pending, now_iso())
    return send_alert(data_dir, cfg,
                      "تنبيه: انقطاع الاتصال بلوحة مرح — %d طلب معلّق" % pending,
                      body, kind="disconnect")


def alert_session_expired(data_dir, cfg):
    """انتهاء جلسة لوحة سلة: تحقّقها الثنائي إلزاميّ لا يُعطَّل، فلا دخول آليّ
    ولا تجديد تلقائي للجلسة — تُلصق كوكيز جديدة بيد المشغّل."""
    body = (
        "انتهت جلسة لوحة سلة، فتوقّفت قراءةُ بطاقات الاشتراك منها.\n\n"
        "التجديد لم يتوقّف: اللوحة ثالثُ المصادر، وقبلها سجلّ الطلب وبطاقته من\n"
        "الواجهة، وبعدها يكتب العميل يوزره بنفسه. لكن كلما طالت، كثُر من يُطلب\n"
        "منهم الكتابة.\n\n"
        "لإعادتها — ولا سبيل غيره، فالتحقّق الثنائي في سلة إلزاميّ لا يُعطَّل:\n"
        "  1. افتح https://s.salla.sa/orders في متصفّحك وسجّل الدخول.\n"
        "  2. من أدوات المطوّر ← Network، انسخ ترويسة Cookie من أي نداء.\n"
        "  3. الصقها في https://admin.ssouq.com/renew ← «جلسة لوحة سلة».\n\n"
        "الوقت: %s\n"
    ) % now_iso()
    return send_alert(data_dir, cfg, "تنبيه: انتهت جلسة لوحة سلة — الصق كوكيز جديدة",
                      body, kind="session")


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


# ============================ خطوط اللوحة ============================
# اللوحة هي المصدر الوحيد الكامل: كل خط فيها بيوزره وباسورده وانتهائه. وسلة
# تعرف ماذا اشترى العميل، لكنها لا تعرف بأيّ يوزر سُلّم — إلا حيث كُتب يدويًا.
# فمن كتب يوزره عرفناه من هنا فورًا، بلا نداء للوحة وقت الطلب.
def lines_path(data_dir):
    return os.path.join(data_dir, "renew_lines.json")


def load_lines(data_dir):
    try:
        with open(lines_path(data_dir), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("by_user"), dict) \
            else {"by_user": {}}
    except (OSError, ValueError):
        return {"by_user": {}}


def save_lines(data_dir, rows, gate_name="", host=""):
    """يحفظ تصدير اللوحة مفهرسًا باليوزر (بحروف صغيرة — اللوحات لا تتّسق)."""
    by_user = {}
    for r in rows:
        u = str(r.get("username") or "").strip()
        if not u:
            continue
        by_user[u.lower()] = {
            "username": u, "password": str(r.get("password") or ""),
            "exp": str(r.get("exp") or ""), "status": str(r.get("status") or ""),
            "connections": str(r.get("connections") or ""),
            "package": str(r.get("package") or ""), "created": str(r.get("created") or ""),
        }
    _write_json(lines_path(data_dir), {"by_user": by_user, "built": now_iso(),
                                       "gate": gate_name, "host": host,
                                       "count": len(by_user)})
    return len(by_user)


def find_line(data_dir, username):
    """خطٌّ بيوزره من التصدير المحفوظ. لا شبكة ولا انتظار."""
    u = str(username or "").strip().lower()
    return load_lines(data_dir)["by_user"].get(u) if u else None


def lines_stats(data_dir):
    d = load_lines(data_dir)
    return {"count": len(d.get("by_user", {})), "built": d.get("built", ""),
            "gate": d.get("gate", ""), "host": d.get("host", "")}


def match_candidates(data_dir, bought, months, devices=1, window=3):
    """مرشّحو الخط لعميلٍ لا يعرف يوزره: خطوطٌ أُنشئت حول يوم شرائه بنفس المدة.

    مطابقةٌ ظنّية لا قاطعة — المتجر يبيع عشرات في اليوم، فقد يتشابه المرشّحون.
    تُعرض على الموظّف ليختار، ولا يُبنى عليها إنشاءٌ تلقائي."""
    b = parse_date(bought)
    if not b:
        return []
    out = []
    for rec in load_lines(data_dir)["by_user"].values():
        c = parse_date(rec.get("created"))
        if not c or abs((c - b).days) > window:
            continue
        e = parse_date(rec.get("exp"))
        if e and months and abs(months_between(c, e) - months) > 1:
            continue
        conns = str(rec.get("connections") or "")
        if conns.isdigit() and devices and int(conns) != int(devices):
            continue
        out.append({**rec, "days_off": abs((c - b).days)})
    return sorted(out, key=lambda r: r["days_off"])[:20]


# ============================ الحصاد ============================
# جلسة لوحة سلة تنتهي خلال ساعات، فهي **نافذةُ حصادٍ لا اعتمادٌ دائم**: يُجمع
# فيها ما يُستطاع ويُخزَّن، فلا تُسأل اللوحة مرة أخرى عمّا حُصد.
#
# ولذلك ثلاث خصال: يُحفظ التقدّم على القرص لا في الذاكرة (فموتُ الخادم لا
# يُضيّع ساعةَ عمل)، ويُستأنف من حيث وقف (فالجلسة الجديدة تُكمل لا تبدأ)،
# ويعمل بخيوط متوازية (فالنافذة قصيرة والطلبات عشرات الألوف).
def harvest_path(data_dir):
    return os.path.join(data_dir, "renew_harvest.json")


def _empty_harvest():
    return {"seen": {}, "found": {}, "at": "", "rounds": 0}


def load_harvest(data_dir):
    try:
        with open(harvest_path(data_dir), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return _empty_harvest()
    if not isinstance(d, dict):
        return _empty_harvest()
    for k, v in _empty_harvest().items():
        if not isinstance(d.get(k), type(v)):
            d[k] = v
    return d


def save_harvest(data_dir, h):
    h["at"] = now_iso()
    _write_json(harvest_path(data_dir), h)


def harvest_stats(data_dir):
    h = load_harvest(data_dir)
    return {"seen": len(h["seen"]), "found": len(h["found"]),
            "at": h.get("at", ""), "rounds": h.get("rounds", 0)}


def harvest_pending(data_dir, sids):
    """ما لم يُحاوَل بعد. المحاوَلُ لا يُعاد ولو لم يُعطِ اعتمادًا — وإلا دارت
    الجلسةُ القصيرة على من لا اعتماد له وتركت من له."""
    seen = load_harvest(data_dir)["seen"]
    return [s for s in sids if s and str(s) not in seen]


def harvest_record(data_dir, rows):
    """يسجّل دفعةً: [(sid, cred)]. الكتابة دفعةً لا لكل واحد، فالقرص لا يُرهَق."""
    if not rows:
        return 0
    with _db_lock:
        h = load_harvest(data_dir)
        for sid, cred in rows:
            h["seen"][str(sid)] = 1
            if cred:
                h["found"][str(sid)] = cred
        save_harvest(data_dir, h)
        return len(h["found"])


def harvest_into_index(data_dir):
    """يدمج ما حُصد في فهرس التجديد، فيصير التعرّف لحظيًّا بلا لوحة ولا واجهة."""
    h = load_harvest(data_dir)
    if not h["found"]:
        return 0
    idx = load_index(data_dir)
    orders = idx.get("orders") or {}
    n = 0
    for rec in orders.values():
        cred = h["found"].get(str(rec.get("sid") or ""))
        if cred and not rec.get("username"):
            rec.update({k: v for k, v in cred.items() if v})
            n += 1
    if n:
        idx["orders"] = orders
        save_index(data_dir, idx)
    return n


def harvest_reset(data_dir):
    """يمسح أثر المحاولات ويُبقي ما وُجد — لإعادة الكرّة على من لم يُعطِ شيئًا."""
    with _db_lock:
        h = load_harvest(data_dir)
        h["seen"] = {k: 1 for k in h["found"]}
        h["rounds"] = int(h.get("rounds", 0)) + 1
        save_harvest(data_dir, h)
        return len(h["seen"])


def harvest_scope(data_dir, from_date="", to_date="", active_only=True, today=None):
    """يختار ما يُحصد بنطاقٍ من التاريخ بدل كنسِ المتجر كله.

    النافذة ساعات والطلبات عشرات الألوف، فالحصاد الأعمى يحرقها على ما لا
    يهمّ: طلبٌ انقضى اشتراكه لا يُجدَّد، فلا معنى لقراءة اعتماده. ومن هنا
    خياران — نطاقُ تاريخٍ يختاره المشغّل، وإسقاطُ المنتهي افتراضًا.

    يرجّع (ما يُحصد الآن، إحصاءٌ يُعرض قبل البدء)."""
    today = today or _today()
    a, b = parse_date(from_date), parse_date(to_date)
    orders = (load_index(data_dir).get("orders") or {})
    seen = load_harvest(data_dir)["seen"]

    n = {"orders": len(orders), "in_range": 0, "known": 0, "expired": 0,
         "done": 0, "pending": 0}
    todo = []
    for no, rec in orders.items():
        d = parse_date(rec.get("date"))
        if not d or (a and d < a) or (b and d > b):
            continue
        n["in_range"] += 1
        if rec.get("username") and rec.get("password"):
            n["known"] += 1                      # اعتماده معروف أصلًا
            continue
        if active_only:
            exp = add_months(d, int(rec.get("months") or 0)) if rec.get("months") else None
            if not exp or exp <= today:
                n["expired"] += 1                # انقضى، فلا يُجدَّد ولا يُقرأ
                continue
        sid = str(rec.get("sid") or "")
        if not sid:
            continue
        if sid in seen:
            n["done"] += 1                       # حوول في جولةٍ سابقة
            continue
        n["pending"] += 1
        todo.append({"sid": sid, "order": no, "date": rec.get("date", ""),
                     "admin_url": str(rec.get("admin_url") or "")})
    todo.sort(key=lambda r: r["date"], reverse=True)   # الأحدث أولًا: أطولها بقاءً
    return todo, n

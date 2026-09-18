# -*- coding: utf-8 -*-
"""تسليم الطلب على واتساب — /whatsapp

كل طلب يُنفَّذ في المتجر يصل صاحبه رسالة واتساب واحدة تحمل: رقم الطلب، الباقة،
نوع الاشتراك (مرح أو فالكون)، بيانات الدخول (السيرفر واليوزر والباسورد)، ورابط
صفحة التفعيل الخاصة بنوع اشتراكه. ومن راسلنا بعدها على الرقم نفسه تُعاد إليه
رسالته كما هي بلا أن يسأل أحدًا.

المسارات:
  الإرسال      واتساب العمليات نفسه (خدمة whatsapp-reader في souq-saas) بمفتاح
               جلسة مستقل لهذا الموقع — لا نسخة ثانية من Baileys هنا. ومعه مزوّد
               ثانٍ رسمي (Meta Cloud API) يُبدَّل إليه من الإعدادات بلا إعادة بناء.
  بيانات الطلب واجهة إدارة سلة (‏`/admin/v2/orders`) بـ SALLA_ADMIN_TOKEN.
  نص الكود     واجهة تقارير سلة (‏`merchant-reports/.../sales-per-digitalcode`) —
               وهي الوحيدة التي تُرجع نص الكود؛ واجهة الطلب تذكر رقمه فقط.

ملف الإعدادات والسجل في data/ (نفس مجلد الحسابات). بلا أي مكتبات خارجية.
"""
import datetime
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("XM_DATA", os.path.join(BASE_DIR, "data"))
WA_FILE = os.path.join(DATA_DIR, "whatsapp.json")
LOG_FILE = os.path.join(DATA_DIR, "wa_log.jsonl")

P = "/whatsapp"                       # جذر الصفحة
SESSION_TTL = 30 * 24 * 3600
TIMEOUT = 25
UA = "Mozilla/5.0 (compatible; ssouq-guide/1.0; +https://guide.ssouq.com/)"
GUIDE_BASE = os.environ.get("GUIDE_BASE", "https://guide.ssouq.com").rstrip("/")
STORE_ID = os.environ.get("SALLA_STORE_ID", "831097886")
LOG_CAP = 4000                        # أقصى عدد أسطر يبقى في ملف السجل
REPLY_COOLDOWN = 15 * 60              # لا يُرد على الرقم نفسه أكثر من مرة كل ربع ساعة

# منتجات فالكون في المتجر. وكل ما عداها مرح — وهذه قاعدة المنشأة لا استنتاج.
# المصدر: كائن CATALOG في index.html (الخمسة تحت "falcon")، ويُدعمها مطابقة
# الاسم لأن المتجر يحمل منتجات خارج الكتالوج المنسّق.
FALCON_IDS = {153695876, 1233297791, 479880741, 484498871, 2083342610}
BRANDS = {
    "falcon": {"name": "فالكون", "full": "FALCON TV PRO", "guide": GUIDE_BASE + "/#activate/falcon"},
    "marah": {"name": "مرح", "full": "MR7 TV", "guide": GUIDE_BASE + "/#activate/marah"},
}

_lock = threading.RLock()
_sessions = {}      # token -> exp


# ================= التخزين =================
def _blank():
    return {
        "password": None,
        "settings": {
            "provider": "reader",       # reader | cloud
            "session_key": "ssouq-guide",
            "number": "",
            "auto_send": True,
            "auto_reply": True,
        },
        "sent": {},                     # reference_id -> {at, to, status}
        # توكن سلة كما وصل من حدث app.store.authorize، ومعه توكن تجديده.
        # لا يُنسخ باليد ولا يُوضع في متغيّر بيئة — يصل وحده ويُجدَّد وحده.
        "salla": {"access_token": "", "refresh_token": "", "expires_at": 0,
                  "scope": "", "merchant": "", "at": 0, "refreshed_at": 0},
    }


def load():
    try:
        with open(WA_FILE, encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    base = _blank()
    base.update(st if isinstance(st, dict) else {})
    base["settings"] = dict(_blank()["settings"], **(base.get("settings") or {}))
    base["salla"] = dict(_blank()["salla"], **(base.get("salla") or {}))
    base.setdefault("sent", {})
    return base


def save(st):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = WA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    os.replace(tmp, WA_FILE)


def hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(8)
    return {"salt": salt, "hash": hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100_000).hex()}


def check_pw(pw, rec):
    return bool(rec) and hmac.compare_digest(hash_pw(pw, rec["salt"])["hash"], rec["hash"])


def new_session():
    now = time.time()
    for t, exp in list(_sessions.items()):
        if exp < now:
            _sessions.pop(t, None)
    tok = secrets.token_urlsafe(32)
    _sessions[tok] = now + SESSION_TTL
    return tok


def valid_session(tok):
    return bool(tok) and _sessions.get(tok, 0) > time.time()


def drop_session(tok):
    _sessions.pop(tok, None)


# ================= السجل =================
def log_event(kind, **fields):
    """سطر واحد لكل حدث. append فقط — لا يُعاد كتابة ما مضى."""
    row = dict(fields, kind=kind, at=int(time.time()))
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        return row
    _trim_log()
    return row


def _trim_log():
    try:
        if os.path.getsize(LOG_FILE) < 3_000_000:
            return
        with open(LOG_FILE, encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) <= LOG_CAP:
            return
        tmp = LOG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(lines[-LOG_CAP:])
        os.replace(tmp, LOG_FILE)
    except OSError:
        pass


def read_log(limit=200, q=""):
    try:
        with open(LOG_FILE, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    out = []
    for ln in reversed(lines):
        try:
            row = json.loads(ln)
        except ValueError:
            continue
        if q and q not in json.dumps(row, ensure_ascii=False):
            continue
        out.append(row)
        if len(out) >= limit:
            break
    return out


# ================= سلة =================
OAUTH_TOKEN_URL = os.environ.get("SALLA_TOKEN_URL", "https://accounts.salla.sa/oauth2/token")
REFRESH_MARGIN = 24 * 3600        # يُجدَّد قبل انتهائه بيوم، لا عند سقوطه


def store_tokens(d, how="authorize"):
    """يحفظ ما وصل من سلة: التوكن وتوكن تجديده ووقت انتهائه.

    `expires` يأتي أحيانًا ختمًا زمنيًّا وأحيانًا عددَ ثوانٍ، فيُقبل الشكلان:
    الرقم الكبير ختم، والصغير مدة. وإلا حُسب الانتهاء خطأً بسنوات.
    """
    d = d or {}
    tok = str(d.get("access_token") or "").strip()
    if not tok:
        return None
    exp = d.get("expires") or d.get("expires_in") or 0
    try:
        exp = int(exp)
    except (TypeError, ValueError):
        exp = 0
    expires_at = exp if exp > 10_000_000 else (int(time.time()) + exp if exp else 0)
    with _lock:
        st = load()
        s = st["salla"]
        s["access_token"] = tok
        s["refresh_token"] = str(d.get("refresh_token") or s.get("refresh_token") or "").strip()
        s["expires_at"] = expires_at
        s["scope"] = str(d.get("scope") or s.get("scope") or "")
        s["merchant"] = str(d.get("merchant") or d.get("store_id") or s.get("merchant") or "")
        s["at"] = s.get("at") or int(time.time())
        s["refreshed_at"] = int(time.time())
        save(st)
    log_event("salla_token", how=how, expires_at=expires_at,
              scope=(s.get("scope") or "")[:200], merchant=s.get("merchant", ""))
    return s


def refresh_salla(force=False):
    """يجدّد التوكن بتوكن التجديد. يرجع (نجح, سبب).

    توكن التجديد يُستعمل مرة واحدة عند سلة: إعادة استعماله تُلغي كل التوكنات
    وتفرض إعادة التثبيت. فالجديد يُكتب مكان القديم فورًا، ولا يُعاد النداء عند
    الفشل — يُقال ويُسجَّل.
    """
    s = load()["salla"]
    if not s.get("refresh_token"):
        return False, "لا يوجد توكن تجديد — ثبّت التطبيق مرة واحدة ليصل"
    if not force and s.get("expires_at") and s["expires_at"] - time.time() > REFRESH_MARGIN:
        return True, ""
    cid = (os.environ.get("SALLA_CLIENT_ID", "") or "").strip()
    secret = (os.environ.get("SALLA_CLIENT_SECRET", "") or "").strip()
    if not cid or not secret:
        return False, "SALLA_CLIENT_ID أو SALLA_CLIENT_SECRET غير مضبوط — لا يمكن التجديد"
    data = urllib.parse.urlencode({"grant_type": "refresh_token", "client_id": cid,
                                   "client_secret": secret, "refresh_token": s["refresh_token"]}).encode()
    req = urllib.request.Request(OAUTH_TOKEN_URL, data=data, headers={
        "User-Agent": UA, "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            out = json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        why = "سلة رفضت التجديد (%d) — قد يكون توكن التجديد استُعمل أو انتهى؛ أعد تثبيت التطبيق" % e.code
        log_event("salla_refresh_failed", error=why)
        return False, why
    except Exception as e:
        log_event("salla_refresh_failed", error=str(e)[:200])
        return False, "تعذّر الوصول لسلة: %s" % str(e)[:120]
    if not store_tokens(out, how="refresh"):
        log_event("salla_refresh_failed", error="رد سلة بلا توكن")
        return False, "رد سلة بلا توكن"
    return True, ""


def _token(kind="admin"):
    """التوكن المخزَّن أولًا (ويُجدَّد إن قارب الانتهاء) ثم متغيّر البيئة.

    ترتيبٌ مقصود: ما وصل من سلة نفسها أحدث دائمًا مما كُتب باليد.
    """
    s = load()["salla"]
    if s.get("access_token"):
        if s.get("expires_at") and s["expires_at"] - time.time() <= REFRESH_MARGIN:
            refresh_salla()
            s = load()["salla"]
        if s.get("access_token"):
            return s["access_token"]
    if kind == "reports":
        return (os.environ.get("SALLA_REPORTS_TOKEN") or os.environ.get("SALLA_ADMIN_TOKEN") or "").strip()
    return (os.environ.get("SALLA_ADMIN_TOKEN") or "").strip()


def hook_secret():
    """السرّ داخل الرابط: يُولَّد مرة، ويُغني عن سرٍّ يُضبط في لوحة سلة."""
    with _lock:
        st = load()
        sec = st.get("hook_secret")
        if not sec:
            sec = secrets.token_urlsafe(48)
            st["hook_secret"] = sec
            save(st)
        return sec


def _get_json(url, headers=None, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers=dict(headers or {}, **{"User-Agent": UA, "Accept": "application/json"}))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace") or "{}")


def _post_json(url, payload, headers=None, timeout=TIMEOUT, method="POST"):
    body = json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(url, data=body, method=method, headers=dict(
        headers or {}, **{"User-Agent": UA, "Accept": "application/json", "Content-Type": "application/json"}))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
    try:
        return json.loads(raw or "{}")
    except ValueError:
        return {"raw": raw[:400]}


def find_order(ref):
    """يقبل رقم الطلب المعروض (reference_id) أو المعرّف الداخلي."""
    tok = _token()
    if not tok:
        raise RuntimeError("SALLA_ADMIN_TOKEN غير مضبوط — لا يمكن قراءة الطلب")
    ref = str(ref).strip()
    if not ref.isdigit():
        raise ValueError("رقم الطلب أرقام فقط")
    head = {"Authorization": "Bearer " + tok}
    try:
        d = _get_json(f"https://api.salla.dev/admin/v2/orders?reference_id={ref}", head)
        rows = d.get("data") or []
        if rows:
            return rows[0]
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise RuntimeError("توكن سلة مرفوض (%d) — راجع SALLA_ADMIN_TOKEN" % e.code)
    try:                                   # ربما مرّر المعرّف الداخلي
        d = _get_json(f"https://api.salla.dev/admin/v2/orders/{ref}", head)
        if d.get("data"):
            return d["data"]
    except urllib.error.HTTPError:
        pass
    raise ValueError("لا يوجد طلب بهذا الرقم: " + ref)


def digital_codes(order_ref, when=None):
    """نص الأكواد الرقمية لطلب واحد.

    واجهة الطلب لا تحمل نص الكود (تذكر رقمه فقط)، وواجهة التقارير وحدها تحمله.
    وهي لا تُصفّي بالطلب، فنقرأ نافذة يومين حول تاريخه ونُصفّي هنا.
    """
    tok = _token("reports")
    if not tok:
        return [], "SALLA_REPORTS_TOKEN/SALLA_ADMIN_TOKEN غير مضبوط"
    day = (when or datetime.datetime.now()).date()
    frm, to = day - datetime.timedelta(days=1), day + datetime.timedelta(days=1)
    q = urllib.parse.urlencode({
        "_from_date": f"{frm} 00:00:00", "_to_date": f"{to} 23:59:59",
        "from_date_int": str(frm), "to_date_int": str(to),
        "_limit": "500", "store_id": STORE_ID, "orders_statuses": "",
    })
    url = "https://api.salla.dev/merchant-reports/v1/sales/sales-per-digitalcode?" + q
    try:
        d = _get_json(url, {"Authorization": "Bearer " + tok})
    except urllib.error.HTTPError as e:
        return [], f"واجهة التقارير ردّت {e.code} — الأكواد لا تُقرأ بهذا التوكن"
    except (urllib.error.URLError, ValueError, TimeoutError) as e:
        return [], "تعذّر الوصول لواجهة التقارير: %s" % e
    rows = [r for r in (d.get("rows") or []) if str(r.get("order_id")) == str(order_ref)]
    return rows, "" if rows else "لم يُعثر على كود رقمي لهذا الطلب في نافذة تاريخه"


# ================= قراءة الكود والعلامة =================
_AR_LABELS = [("اسم المستخدم", " Username "), ("المستخدم", " Username "), ("كلمة المرور", " Password "),
              ("كلمه المرور", " Password "), ("الخادم", " Host "), ("السيرفر", " Host ")]


def parse_code(raw):
    """يقرأ نص الكود مهما اختلفت صيغته.

    أكواد المتجر ليست على صيغة واحدة: ترتيب الحقول يختلف، وبعضها بالعربية،
    وبعضها بلا مسافات بين الحقل وقيمته. فيُطبَّع النص أولًا ثم يُقرأ بالوسم لا
    بالموضع، ويرجع ما وُجد فقط — والناقص يُقال ولا يُخمَّن.
    """
    s = " " + re.sub(r"\s+", " ", str(raw or "")).strip() + " "
    for ar, en in _AR_LABELS:
        s = s.replace(ar, en)
    # الحقل الملتصق بما قبله: "…vipUsername 12" → "…vip Username 12".
    # الفصل بحرف الوسم الكبير وحده، وإلا قُطع الهوست نفسه: "ssouqhost.vip"
    # يحمل كلمة host بحروف صغيرة فلا يُفصل، و"vipUsername" يُفصل.
    s = re.sub(r"(?<=[a-z0-9؀-ۿ])(?=(?:Host|Username|User|Password|Pass)\b)", " ", s)
    s = re.sub(r"\s+", " ", s)

    def grab(pattern):
        m = re.search(pattern, s, re.I)
        return m.group(1).strip() if m else ""

    out = {
        "host": grab(r"\bhost\b\s*[:=]?\s*(\S+)"),
        "username": grab(r"\buser(?:name)?\b\s*[:=]?\s*(\S+)"),
        "password": grab(r"\bpass(?:word)?\b\s*[:=]?\s*(\S+)"),
        "raw": str(raw or "").strip(),
    }
    out["missing"] = [k for k in ("host", "username", "password") if not out[k]]
    return out


def brand_of(product_id, name=""):
    try:
        if int(product_id) in FALCON_IDS:
            return "falcon"
    except (TypeError, ValueError):
        pass
    low = (name or "").lower()
    return "falcon" if ("فالكون" in (name or "") or "falcon" in low) else "marah"


def normalize_phone(mobile, code="+966"):
    digits = re.sub(r"\D", "", str(mobile or ""))
    cc = re.sub(r"\D", "", str(code or "")) or "966"
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith(cc):
        return digits
    return cc + digits.lstrip("0")


# ================= بناء الرسالة =================
def build_message(order, code_rows):
    ref = order.get("reference_id") or order.get("id")
    cust = order.get("customer") or {}
    name = (cust.get("first_name") or cust.get("full_name") or "").strip()
    items = order.get("items") or []

    blocks, brands, warnings = [], set(), []
    for i, row in enumerate(code_rows):
        pid = row.get("product_id")
        pname = row.get("product_name") or ""
        brand = brand_of(pid, pname)
        brands.add(brand)
        c = parse_code(row.get("digital_code"))
        if c["missing"]:
            warnings.append("الكود %s ينقصه: %s" % (row.get("digital_code_id"), "، ".join(c["missing"])))
        lines = ["📦 *%s*" % pname, "🏷️ نوع الاشتراك: *%s*" % BRANDS[brand]["name"]]
        if c["host"]:
            lines.append("🌐 السيرفر: `%s`" % c["host"])
        if c["username"]:
            lines.append("👤 اسم المستخدم: `%s`" % c["username"])
        if c["password"]:
            lines.append("🔑 كلمة المرور: `%s`" % c["password"])
        if c["missing"] and c["raw"]:
            lines.append("بيانات الاشتراك: %s" % c["raw"])
        blocks.append(("" if len(code_rows) == 1 else "*الاشتراك %d:*\n" % (i + 1)) + "\n".join(lines))

    if not blocks:                       # طلب بلا كود: لا تُرسل بيانات وهمية
        for it in items:
            blocks.append("📦 *%s*" % (it.get("name") or ""))
        warnings.append("لا يوجد كود رقمي لهذا الطلب")

    guides = [BRANDS[b]["guide"] for b in ("falcon", "marah") if b in brands] or [BRANDS["marah"]["guide"]]
    guide_line = "\n".join("▶️ طريقة التفعيل خطوة بخطوة:\n%s" % g for g in guides)

    body = "\n\n".join(filter(None, [
        ("مرحبًا %s 👋" % name) if name else "مرحبًا 👋",
        "شكرًا لطلبك من *سمارت سوق*.",
        "🧾 رقم الطلب: *%s*" % ref,
        "\n\n".join(blocks),
        guide_line,
        "احتفظ بهذه الرسالة، ففيها بيانات اشتراكك.\nوأي استفسار راسلنا هنا مباشرة وسنرد عليك.",
    ]))
    return {"body": body, "ref": str(ref), "brands": sorted(brands),
            "to": normalize_phone(cust.get("mobile"), cust.get("mobile_code")),
            "customer": name, "warnings": warnings, "codes": len(code_rows)}


# ================= المزوّدون =================
def reader_cfg():
    st = load()["settings"]
    return {
        "url": (os.environ.get("WA_READER_URL", "") or "").strip().rstrip("/"),
        "secret": (os.environ.get("WA_READER_SECRET", "") or "").strip(),
        "key": st.get("session_key") or "ssouq-guide",
    }


def _reader(path, payload=None, method="GET"):
    cfg = reader_cfg()
    if not cfg["url"] or not cfg["secret"]:
        raise RuntimeError("WA_READER_URL أو WA_READER_SECRET غير مضبوط")
    url = cfg["url"] + path
    head = {"X-Reader-Secret": cfg["secret"]}
    if method == "GET":
        return _get_json(url, head)
    return _post_json(url, payload or {}, head, method=method)


def reader_status():
    cfg = reader_cfg()
    return _reader("/sessions/" + urllib.parse.quote(cfg["key"]))


def reader_connect(number):
    cfg = reader_cfg()
    return _reader("/sessions", {
        "tenant": cfg["key"],
        "number": number,
        "callbackUrl": GUIDE_BASE + P + "/ingest",
        "ingestToken": ingest_token(),
    }, method="POST")


def reader_disconnect():
    cfg = reader_cfg()
    return _reader("/sessions/" + urllib.parse.quote(cfg["key"]), method="DELETE")


def ingest_token():
    """سر يوقّع به القارئ رسائله الواردة إلينا. يُولَّد مرة ويُحفظ."""
    with _lock:
        st = load()
        tok = st.get("ingest_token")
        if not tok:
            tok = secrets.token_urlsafe(24)
            st["ingest_token"] = tok
            save(st)
        return tok


def send_text(to, body):
    """يرسل عبر المزوّد المختار ويرجع {ok, id, provider}."""
    st = load()
    provider = st["settings"].get("provider", "reader")
    if provider == "cloud":
        token = (os.environ.get("WA_CLOUD_TOKEN", "") or "").strip()
        phone_id = (os.environ.get("WA_CLOUD_PHONE_ID", "") or "").strip()
        if not token or not phone_id:
            raise RuntimeError("WA_CLOUD_TOKEN أو WA_CLOUD_PHONE_ID غير مضبوط")
        r = _post_json(
            f"https://graph.facebook.com/v21.0/{phone_id}/messages",
            {"messaging_product": "whatsapp", "recipient_type": "individual",
             "to": to, "type": "text", "text": {"preview_url": False, "body": body}},
            {"Authorization": "Bearer " + token})
        mid = ((r.get("messages") or [{}])[0]).get("id", "")
        return {"ok": bool(mid), "id": mid, "provider": "cloud"}
    cfg = reader_cfg()
    r = _reader("/sessions/" + urllib.parse.quote(cfg["key"]) + "/send",
                {"to": to, "body": body, "dmCallbackUrl": GUIDE_BASE + P + "/ingest"}, method="POST")
    return {"ok": bool(r.get("ok")), "id": r.get("waMessageId", ""), "provider": "reader"}


# ================= التسليم =================
def preview_order(ref):
    order = find_order(ref)
    when = None
    raw_date = ((order.get("date") or {}) if isinstance(order.get("date"), dict) else {}).get("date")
    if raw_date:
        try:
            when = datetime.datetime.strptime(raw_date[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            when = None
    rows, note = digital_codes(order.get("reference_id") or order.get("id"), when)
    msg = build_message(order, rows)
    if note:
        msg["warnings"] = msg["warnings"] + [note]
    msg["status"] = ((order.get("status") or {}).get("slug") or "")
    msg["sent_before"] = load()["sent"].get(msg["ref"])
    return msg


def deliver(ref, force=False, source="manual", body=None):
    """يبني الرسالة ويرسلها. `body` يستبدل النص المبني — المراجع قد يعدّله."""
    msg = preview_order(ref)
    if body and str(body).strip():
        msg["body"] = str(body).strip()
    if not msg["to"]:
        raise RuntimeError("الطلب بلا رقم جوال")
    with _lock:
        st = load()
        prev = st["sent"].get(msg["ref"])
        if prev and prev.get("ok") and not force:
            log_event("skipped", ref=msg["ref"], to=msg["to"], reason="أُرسل من قبل", source=source)
            return dict(msg, sent=False, skipped=True, note="أُرسلت من قبل — استعمل الإرسال القسري لإعادتها")
    try:
        res = send_text(msg["to"], msg["body"])
    except Exception as e:
        log_event("send_failed", ref=msg["ref"], to=msg["to"], error=str(e), source=source)
        with _lock:
            st = load()
            st["sent"][msg["ref"]] = {"at": int(time.time()), "to": msg["to"], "ok": False, "error": str(e)}
            save(st)
        raise
    with _lock:
        st = load()
        st["sent"][msg["ref"]] = {"at": int(time.time()), "to": msg["to"], "ok": True,
                                  "id": res.get("id", ""), "source": source}
        save(st)
    log_event("sent", ref=msg["ref"], to=msg["to"], customer=msg["customer"], brands=msg["brands"],
              codes=msg["codes"], provider=res.get("provider"), source=source,
              warnings=msg["warnings"], body=msg["body"])
    return dict(msg, sent=True, skipped=False)


def order_ref_from_webhook(payload):
    """رقم الطلب من حمولة ويب هوك سلة، ومعه هل الحالة تستحق الإرسال."""
    ev = str(payload.get("event") or "")
    d = payload.get("data") or {}
    ref = d.get("reference_id") or d.get("id") or ((d.get("order") or {}).get("reference_id"))
    slug = ""
    stt = d.get("status")
    if isinstance(stt, dict):
        slug = str(stt.get("slug") or stt.get("name") or "")
    elif isinstance(stt, str):
        slug = stt
    ready = ev in ("order.created", "order.updated", "order.status.updated", "order.payment.updated")
    done = slug in ("completed", "delivered", "delivering", "in_progress") or ev == "order.created"
    return (str(ref) if ref else ""), (ready and done), ev, slug


def verify_webhook(raw, signature="", authorization=""):
    """ويب هوك سلة: توقيع HMAC أو توكن. بلا سرٍّ مضبوط لا يُقبل شيء.

    نداء غير موقَّع يعني أن أي أحد يستطيع إطلاق رسائل باسمنا، فالرفض هو
    الافتراضي والصفحة تقول ما ينقص بدل أن يعمل الباب مفتوحًا.
    """
    secret = (os.environ.get("SALLA_WEBHOOK_SECRET", "") or "").strip()
    if not secret:
        return False, "SALLA_WEBHOOK_SECRET غير مضبوط — كل نداء مرفوض"
    tok = str(authorization or "")
    if tok.lower().startswith("bearer "):
        tok = tok[7:].strip()
    if tok and hmac.compare_digest(tok, secret):
        return True, ""
    if signature:
        mine = hmac.new(secret.encode(), raw or b"", hashlib.sha256).hexdigest()
        if hmac.compare_digest(mine, str(signature).strip()):
            return True, ""
    return False, "توقيع الويب هوك غير مطابق"


def handle_webhook(payload):
    ev = str(payload.get("event") or "")
    data = payload.get("data") or {}

    # التثبيت والتصريح: التوكن يصل هنا فلا يُنسخ باليد ولا يُوضع في البيئة.
    if isinstance(data, dict) and data.get("access_token"):
        s = store_tokens(dict(data, merchant=payload.get("merchant") or data.get("merchant")), how=ev or "authorize")
        return {"ok": bool(s), "event": ev, "stored": bool(s)}
    if ev in ("app.store.uninstall", "app.uninstalled"):
        with _lock:
            st = load()
            st["salla"] = _blank()["salla"]
            save(st)
        log_event("salla_uninstalled", event=ev)
        return {"ok": True, "event": ev, "cleared": True}

    ref, ok, ev, slug = order_ref_from_webhook(payload)
    if not ref:
        log_event("webhook_ignored", event=ev, reason="بلا رقم طلب")
        return {"ok": False, "reason": "no_reference"}
    if not load()["settings"].get("auto_send", True):
        log_event("webhook_ignored", event=ev, ref=ref, reason="الإرسال الآلي مطفأ")
        return {"ok": False, "reason": "auto_off"}
    if not ok:
        log_event("webhook_ignored", event=ev, ref=ref, status=slug, reason="الحالة لا تستحق الإرسال")
        return {"ok": False, "reason": "status"}
    try:
        res = deliver(ref, source="webhook:" + ev)
        return {"ok": bool(res.get("sent")), "ref": ref}
    except Exception as e:
        log_event("webhook_failed", event=ev, ref=ref, error=str(e))
        return {"ok": False, "error": str(e)}


def last_order_for_phone(phone):
    """آخر طلب لصاحب هذا الرقم — لإعادة إرسال بياناته حين يراسلنا."""
    tok = _token()
    if not tok or not phone:
        return None
    tail = phone[-9:]
    try:
        d = _get_json("https://api.salla.dev/admin/v2/orders?" + urllib.parse.urlencode(
            {"keyword": tail, "sort_by": "created_at", "per_page": 5}),
            {"Authorization": "Bearer " + tok})
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError, TimeoutError):
        return None
    for row in (d.get("data") or []):
        cust = row.get("customer") or {}
        if normalize_phone(cust.get("mobile"), cust.get("mobile_code")).endswith(tail):
            return row.get("reference_id") or row.get("id")
    return None


def handle_ingest(payload):
    """رسالة واردة من العميل: تُسجَّل، ثم تُعاد إليه بيانات آخر طلب له."""
    msg = payload.get("message") or payload
    if msg.get("fromMe") or msg.get("from_me"):
        return {"ok": True, "skipped": "منّا لا منه"}
    jid = str(msg.get("chatId") or msg.get("chat_id") or msg.get("from") or "")
    if jid.endswith("@g.us"):
        return {"ok": True, "skipped": "قروب"}
    phone = normalize_phone(jid.split("@")[0], "")
    text = str(msg.get("body") or msg.get("text") or "")[:2000]
    log_event("received", phone=phone, body=text)

    st = load()
    if not st["settings"].get("auto_reply", True):
        return {"ok": True, "replied": False, "reason": "الرد الآلي مطفأ"}
    with _lock:
        st = load()
        last = (st.setdefault("replied", {})).get(phone, 0)
        if time.time() - last < REPLY_COOLDOWN:
            log_event("reply_skipped", phone=phone, reason="ردٌّ قريب على الرقم نفسه")
            return {"ok": True, "replied": False, "reason": "cooldown"}
        st["replied"][phone] = int(time.time())
        save(st)

    ref = last_order_for_phone(phone)
    if not ref:
        log_event("reply_skipped", phone=phone, reason="لا يوجد طلب لهذا الرقم")
        return {"ok": True, "replied": False, "reason": "no_order"}
    try:
        res = deliver(ref, force=True, source="reply")
        return {"ok": True, "replied": True, "ref": res["ref"]}
    except Exception as e:
        log_event("reply_failed", phone=phone, ref=ref, error=str(e))
        return {"ok": False, "error": str(e)}


# ================= التشخيص =================
def diagnostics():
    """ما المضبوط وما الناقص وأثر كل نقص — تُقرأ بالعين لا بالتخمين."""
    st = load()
    provider = st["settings"].get("provider", "reader")
    checks = []

    def add(key, ok, detail, effect):
        checks.append({"key": key, "ok": bool(ok), "detail": detail, "effect": effect})

    s = st["salla"]
    left = int((s.get("expires_at") or 0) - time.time())
    if s.get("access_token"):
        days = max(0, left // 86400)
        add("توكن سلة", left > 0,
            ("وصل من سلة، يبقى %d يومًا" % days) if left > 0 else "وصل من سلة لكنه انتهى",
            "" if left > 0 else "سيُجدَّد آليًّا عند أول نداء، وإن فشل فأعد تثبيت التطبيق")
        cid = os.environ.get("SALLA_CLIENT_ID") and os.environ.get("SALLA_CLIENT_SECRET")
        add("التجديد الآلي", bool(s.get("refresh_token")) and bool(cid),
            "يعمل" if (s.get("refresh_token") and cid) else
            ("ينقصه SALLA_CLIENT_ID/SECRET" if s.get("refresh_token") else "لا يوجد توكن تجديد"),
            "بدونه يتوقف كل شيء بعد أسبوعين من وصول التوكن")
    else:
        add("توكن سلة", bool(os.environ.get("SALLA_ADMIN_TOKEN")),
            "من متغيّر البيئة" if os.environ.get("SALLA_ADMIN_TOKEN") else "لم يصل بعد",
            "ثبّت التطبيق على متجرك فيصل التوكن إلى هذه الصفحة وحده — أو ضع SALLA_ADMIN_TOKEN يدويًّا")

    admin = _token()
    if admin:
        try:
            _get_json("https://api.salla.dev/admin/v2/orders?per_page=1", {"Authorization": "Bearer " + admin})
            add("salla_orders", True, "واجهة الطلبات تستجيب", "")
        except urllib.error.HTTPError as e:
            add("salla_orders", False, "واجهة الطلبات ردّت %d" % e.code, "التوكن مرفوض أو منتهي")
        except Exception as e:
            add("salla_orders", False, str(e)[:120], "تعذّر الوصول لواجهة سلة")

    rep = _token("reports")
    if rep:
        day = datetime.date.today()
        q = urllib.parse.urlencode({"_from_date": f"{day} 00:00:00", "_to_date": f"{day} 23:59:59",
                                    "from_date_int": str(day), "to_date_int": str(day),
                                    "_limit": "1", "store_id": STORE_ID, "orders_statuses": ""})
        try:
            _get_json("https://api.salla.dev/merchant-reports/v1/sales/sales-per-digitalcode?" + q,
                      {"Authorization": "Bearer " + rep})
            add("salla_reports", True, "واجهة التقارير تستجيب", "")
        except urllib.error.HTTPError as e:
            add("salla_reports", False, "واجهة التقارير ردّت %d" % e.code,
                "نص الكود لن يُقرأ — ضع SALLA_REPORTS_TOKEN لواجهة التقارير")
        except Exception as e:
            add("salla_reports", False, str(e)[:120], "نص الكود لن يُقرأ")
    else:
        add("salla_reports", False, "غير مضبوط",
            "نص الكود لن يُقرأ — الرسالة تخرج بلا بيانات دخول")

    # الرابط السرّي يغني عن سرٍّ يُضبط في لوحة سلة، وهو مولَّد دائمًا — فالباب
    # مقفل بلا أي إعداد منك. و SALLA_WEBHOOK_SECRET يبقى مقبولًا لمن ضبطه.
    add("باب الويب هوك", True, "مقفل برابط سرّي" +
        (" ومعه سرّ سلة" if (os.environ.get("SALLA_WEBHOOK_SECRET") or "").strip() else ""),
        "")

    if provider == "reader":
        cfg = reader_cfg()
        add("WA_READER_URL", cfg["url"], cfg["url"] or "غير مضبوط", "بدونه لا يُرسل واتساب")
        add("WA_READER_SECRET", cfg["secret"], "مضبوط" if cfg["secret"] else "غير مضبوط",
            "بدونه يرفض القارئ كل نداء")
    else:
        add("WA_CLOUD_TOKEN", os.environ.get("WA_CLOUD_TOKEN"),
            "مضبوط" if os.environ.get("WA_CLOUD_TOKEN") else "غير مضبوط", "بدونه لا يُرسل واتساب")
        add("WA_CLOUD_PHONE_ID", os.environ.get("WA_CLOUD_PHONE_ID"),
            "مضبوط" if os.environ.get("WA_CLOUD_PHONE_ID") else "غير مضبوط", "بدونه لا يُرسل واتساب")

    return {"provider": provider, "checks": checks,
            "webhook_url": GUIDE_BASE + P + "/hook/" + hook_secret(),
            "ingest_url": GUIDE_BASE + P + "/ingest",
            "salla": {"connected": bool(st["salla"].get("access_token")),
                      "expires_at": st["salla"].get("expires_at") or 0,
                      "merchant": st["salla"].get("merchant") or "",
                      "scope": st["salla"].get("scope") or ""},
            # "جاهز" = الإرسال اليدوي يعمل. نقص التقارير يُفقِد نص الكود، ونقص
            # سرّ الويب هوك يُطفئ الآلي وحده — وكلاهما معلن في الفحص أعلاه.
            "ready": all(c["ok"] for c in checks
                         if c["key"] not in ("salla_reports", "SALLA_WEBHOOK_SECRET"))}


def status_payload():
    """ما تعرضه شاشة الحالة: الفحص + لقطة الجلسة + الإعدادات."""
    out = diagnostics()
    out["settings"] = load()["settings"]
    out["session"], out["session_error"] = {}, ""
    if out["provider"] == "reader":
        try:
            out["session"] = reader_status() or {}
        except urllib.error.HTTPError as e:
            out["session_error"] = "القارئ ردّ %d — تأكد من WA_READER_URL والسر" % e.code
        except Exception as e:
            out["session_error"] = "تعذّر الوصول للقارئ: %s" % str(e)[:160]
    return out


def set_settings(d):
    allowed_provider = ("reader", "cloud")
    with _lock:
        st = load()
        s = st["settings"]
        if "provider" in d:
            if d["provider"] not in allowed_provider:
                raise ValueError("مزوّد غير معروف")
            s["provider"] = d["provider"]
        if "session_key" in d:
            key = re.sub(r"[^A-Za-z0-9_.-]", "", str(d["session_key"] or "")).strip() or "ssouq-guide"
            s["session_key"] = key
        for flag in ("auto_send", "auto_reply"):
            if flag in d:
                s[flag] = bool(d[flag])
        save(st)
        return s

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
التجديدات — قاعدة عملاء الاشتراكات ومحرك رسائل الواتساب
=========================================================
يقرأ تصدير طلبات سلة (CSV أو XLSX) ويبني قاعدة عملاء: لكل عميل باقته وتاريخ
انتهائها والمتبقي، ثم يقسّمهم إلى شرائح ويكتب لكل شريحة رسالة واتساب مع ترشيح
باقة من نفس كتالوج الصفحة الرئيسية (`CATALOG` في index.html — مصدر واحد للباقات).

بايثون خالص بلا أي مكتبة خارجية، على نهج xm_lines.py. التخزين في data/subs.json
و data/wa.json (يُضاف إليه ولا يُعاد كتابته).
"""
import os, re, io, csv, json, html, zipfile, datetime, hashlib
import xml.etree.ElementTree as ET
from urllib.parse import quote

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("XM_DATA", os.path.join(BASE_DIR, "data"))
SUBS_FILE = os.path.join(DATA_DIR, "subs.json")
WA_FILE   = os.path.join(DATA_DIR, "wa.json")

# ═════════ قواعد التعرّف (نفس قواعد تحليل التصدير) ═════════
IPTV_HINT = re.compile(r"iptv|smarters|falcon|فالكون|كاسبر|اشتراك سمارت|webos|ال جي|"
                       r"ترفيهي رقمي|اشتراك مسلسلات|كاس العالم", re.I)
NOT_SUB   = re.compile(r"لوحة تحكم|للموزعين|تحديث من نظام", re.I)
PAID      = {"طلبك مؤكد", "تم التنفيذ", "تم التوصيل", "طرود مؤكد",
             "جاري التوصيل", "جاهزة لشحن", "تم التوصيل طرود COD"}
DEFAULT_MONTHS = 12
WEBOS_HINT = re.compile(r"سامسونج|ال جي|\bLG\b|webos", re.I)
FALCON_HINT = re.compile(r"falcon|فالكون", re.I)
VOD_HINT = re.compile(r"ترفيهي|نتفلكس|مسلسلات|أفلام|افلام", re.I)

# استخراج الكود من الملاحظات الداخلية
_SPLIT = re.compile(r"(?i)(?=(?:password|كلمة\s*(?:السر|المرور)|pass\b|dns|host|الهوست|الخادم|https?://|📅|ينتهي))")
_USER = re.compile(r"(?:اسم\s*المستخدم|المستخدم|user\s*name|username|user)\s*[:：=/]?\s*[\"“”'«]?\s*([A-Za-z0-9_\-.@]{3,})", re.I)
_PASS = re.compile(r"(?:كلمة\s*(?:السر|المرور)|password|pass)\s*[:：=/]?\s*[\"“”'«]?\s*([A-Za-z0-9_\-.@]{3,})", re.I)
_EXP  = re.compile(r"(?:ينتهي\s*في|expires?\s*(?:on|at)?|exp)\s*[:：=/]?\s*(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", re.I)


def duration(name):
    """المدة بالأشهر من اسم المنتج، ومصدرها."""
    n = (name or "").strip()
    m = re.search(r"(\d+)\s*(?:شهرا|شهرًا|شهر|شهور|اشهر|أشهر)", n)
    if m: return int(m.group(1)), "اسم المنتج"
    if re.search(r"سنتين", n):                 return 24, "اسم المنتج"
    if re.search(r"ثلاثة\s*(?:اشهر|أشهر)", n): return 3,  "اسم المنتج"
    if re.search(r"ستة\s*(?:اشهر|أشهر)", n):   return 6,  "اسم المنتج"
    if re.search(r"سنه|سنة", n):               return 12, "اسم المنتج"
    if re.search(r"يوم", n):                   return 0,  "تجريبي"
    return DEFAULT_MONTHS, "مُفترضة"


def add_months(d, n):
    import calendar
    m = d.month - 1 + n; y = d.year + m // 12; m = m % 12 + 1
    return datetime.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def parse_date(s):
    s = (s or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        try: return datetime.date.fromisoformat(s[:10])
        except ValueError: return None
    for f in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
        try: return datetime.datetime.strptime(s, f).date()
        except ValueError: pass
    return None


def norm_phone(p):
    """يوحّد الجوال: 9665xxxxxxxx (بلا +)، ويرجّع '' لغير الصالح."""
    d = re.sub(r"\D", "", p or "")
    if d.startswith("00"): d = d[2:]
    if d.startswith("05"): d = "966" + d[1:]
    elif d.startswith("5") and len(d) == 9: d = "966" + d
    return d if 10 <= len(d) <= 15 else ""


# ═════════ قراءة الملفات ═════════
def xlsx_rows(data):
    """يقرأ أول ورقة في ملف xlsx بمكتبات بايثون القياسية فقط."""
    z = zipfile.ZipFile(io.BytesIO(data))
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")):
            shared.append("".join(t.text or "" for t in si.iter(ns + "t")))
    sheet = next((n for n in z.namelist() if re.match(r"xl/worksheets/sheet1\.xml$", n)), None)
    if not sheet: raise ValueError("ملف إكسل بلا ورقة أولى")
    rows = []
    for row in ET.fromstring(z.read(sheet)).iter(ns + "row"):
        cells = {}
        for c in row.iter(ns + "c"):
            ref = c.get("r") or ""
            col = re.sub(r"\d", "", ref)
            v = c.find(ns + "v"); t = c.get("t")
            if t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(ns + "t"))
            elif v is None:
                val = ""
            elif t == "s":
                val = shared[int(v.text)] if v.text and v.text.isdigit() else ""
            else:
                val = v.text or ""
            cells[col] = val
        rows.append(cells)
    if not rows: return []
    def key(c):
        n = 0
        for ch in c: n = n * 26 + (ord(ch) - 64)
        return n
    cols = sorted({c for r in rows for c in r}, key=key)
    headers = [rows[0].get(c, "") for c in cols]
    return [dict(zip(headers, [r.get(c, "") for c in cols])) for r in rows[1:]]


def csv_rows(text):
    if text.startswith("﻿"): text = text[1:]
    return list(csv.DictReader(io.StringIO(text)))


def read_upload(data):
    """يستقبل بايتات الملف ويرجع صفوفًا (يميّز xlsx من csv تلقائيًا)."""
    if data[:4] == b"PK\x03\x04":
        return xlsx_rows(data), "xlsx"
    for enc in ("utf-8-sig", "utf-8", "cp1256"):
        try: return csv_rows(data.decode(enc)), "csv"
        except UnicodeDecodeError: continue
    raise ValueError("تعذّرت قراءة الملف — ارفع CSV أو XLSX من تصدير سلة")


# ═════════ التخزين ═════════
def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, type(default)) else default
    except (OSError, ValueError):
        return default


def _save(path, obj):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def load_subs(): return _load(SUBS_FILE, {"updated": "", "orders": {}, "files": []})
def save_subs(d): _save(SUBS_FILE, d)
def load_wa():
    d = _load(WA_FILE, {})
    d.setdefault("sent", []); d.setdefault("optout", [])
    d.setdefault("settings", {"daily_cap": 80, "gap_min": 45, "gap_max": 120,
                              "send_url": "", "send_token": "", "enabled": False})
    return d
def save_wa(d): _save(WA_FILE, d)


# ═════════ الاستيعاب ═════════
def ingest(rows, filename=""):
    """يدمج صفوف تصدير سلة في المخزن. يرجع تقريرًا."""
    if not rows or not any("رقم الطلب" in r and "skus_json" in r for r in rows[:5]):
        raise ValueError('هذا ليس تصدير طلبات من سلة — يجب أن يحوي عمودَي "رقم الطلب" و"skus_json"')
    st = load_subs()
    orders = st["orders"]
    added = updated = skipped = codes = 0
    for r in rows:
        oid = str(r.get("رقم الطلب", "")).strip()
        if not oid: continue
        status = str(r.get("حالة الطلب", "")).strip()
        odate = parse_date(str(r.get("تاريخ الطلب", ""))[:10])
        if not odate: continue
        try: items = json.loads(r.get("skus_json") or "[]")
        except Exception: items = []
        # الكود من الملاحظات الداخلية
        code = pw = ""; real = None
        note = (r.get("الملاحظات الداخلية") or "").strip()
        if note:
            t = _SPLIT.sub("\n", html.unescape(html.unescape(note)))
            u = _USER.search(t); p = _PASS.search(t); e = _EXP.search(t)
            if u: code = u.group(1)
            if p: pw = p.group(1)
            if e: real = parse_date(e.group(1))
        subs = []
        for it in items:
            name = (it[0] or "").strip()
            if not IPTV_HINT.search(name) or NOT_SUB.search(name): continue
            months, src = duration(name)
            if months == 0: continue
            price = 0.0
            try: price = float(it[4]) if len(it) > 4 and it[4] not in (None, "") else 0.0
            except (TypeError, ValueError): price = 0.0
            subs.append({"product": name, "months": months, "src": src,
                         "qty": int(float(it[1] or 1) or 1), "price": price})
        if not subs:
            skipped += 1; continue
        phone = norm_phone(str(r.get("رقم الجوال", "")))
        rec = {"order": oid, "date": odate.isoformat(), "status": status,
               "paid": status in PAID, "phone": phone,
               "name": str(r.get("اسم العميل", "")).strip(),
               "city": str(r.get("المدينة", "")).strip(),
               "email": str(r.get("بريد العميل", "")).strip(),
               "subs": subs, "code": code, "pw": pw,
               "real_exp": real.isoformat() if real else ""}
        old = orders.get(oid)
        if old:
            # لا نفقد كودًا استُخرج من ملف سابق
            if not rec["code"] and old.get("code"): rec["code"] = old["code"]; rec["pw"] = old.get("pw", "")
            if not rec["real_exp"] and old.get("real_exp"): rec["real_exp"] = old["real_exp"]
            if rec != old: updated += 1
        else:
            added += 1
        if rec["code"]: codes += 1
        orders[oid] = rec
    st["updated"] = datetime.datetime.now().isoformat(timespec="seconds")
    if filename and filename not in st["files"]: st["files"].append(filename)
    save_subs(st)
    return {"added": added, "updated": updated, "skipped": skipped,
            "codes": codes, "total_orders": len(orders)}


# ═════════ الكتالوج (مصدره index.html) ═════════
_CATALOG = None
def catalog():
    global _CATALOG
    if _CATALOG is None:
        try:
            with open(os.path.join(BASE_DIR, "index.html"), encoding="utf-8") as f:
                txt = f.read()
            m = re.search(r"const CATALOG\s*=\s*(\{.*?\});\s*\n", txt, re.S)
            _CATALOG = json.loads(m.group(1)) if m else {}
        except Exception:
            _CATALOG = {}
    return _CATALOG


def _plan_months(p):
    m = re.search(r"(\d+)", p.get("dur", ""))
    if "ساعة" in p.get("dur", ""): return 0
    return int(m.group(1)) if m else 0


def recommend(product, months):
    """يرشّح باقة: نفس العلامة ونفس الجهاز، ويفضّل المدة الأربح لكل شهر خدمة.

    القاعدة مبنية على أرقام المتجر: الربح لكل شهر خدمة في باقة ٦ أشهر يقارب
    ضعفه في باقة ١٢ شهرًا، فمن جدّد نصف سنة أربح لك ممن جدّد سنة — ما لم يكن
    العميل من أصحاب المدد الطويلة (١٥ شهرًا فأكثر) فيُعرض عليه مثلها.
    """
    cat = catalog()
    brand = "falcon" if FALCON_HINT.search(product or "") else "smart"
    need_webos = bool(WEBOS_HINT.search(product or ""))
    want_vod = bool(VOD_HINT.search(product or ""))
    plans = [p for p in cat.get(brand, {}).get("plans", []) if _plan_months(p) > 0]
    if not plans: return None, None
    if need_webos:
        pool = [p for p in plans if p.get("webos")] or plans
    else:
        pool = [p for p in plans if not p.get("webos")]
        if want_vod:
            pool = [p for p in pool if p.get("vod")] or pool
        pool = pool or plans
    target = 6 if months <= 12 else months
    primary = min(pool, key=lambda p: (abs(_plan_months(p) - target), _plan_months(p)))
    alts = [p for p in pool if p["id"] != primary["id"]]
    alt = min(alts, key=lambda p: abs(_plan_months(p) - max(months, 12))) if alts else None
    return primary, alt


# ═════════ نقص المدة المفعَّلة (تعويض) ═════════
TOLERANCE_DAYS = 3          # فرق مقبول بين المحسوب والمفعَّل


def shortfalls():
    """الطلبات التي فُعّلت بمدة أقل مما دُفع — لتعويض أصحابها.

    تُقارَن المدة المدفوعة (تاريخ الطلب + مدة الباقة) بتاريخ الانتهاء الفعلي
    المسجَّل في ملاحظات الطلب. الفرق السالب أكبر من TOLERANCE_DAYS نقصٌ حقيقي.
    """
    st = load_subs(); out = []
    for o in st["orders"].values():
        if not o["paid"] or not o["real_exp"]: continue
        d = parse_date(o["date"]); real = parse_date(o["real_exp"])
        if not d or not real: continue
        for s_ in o["subs"]:
            calc = add_months(d, s_["months"])
            gap = (real - calc).days
            if gap >= -TOLERANCE_DAYS: continue
            out.append({"order": o["order"], "name": o["name"], "phone": o["phone"],
                        "city": o["city"], "code": o["code"], "product": s_["product"],
                        "months": s_["months"], "price": s_["price"],
                        "date": o["date"], "calc_exp": calc.isoformat(),
                        "real_exp": real.isoformat(), "missing_days": -gap,
                        "missing_months": round(-gap / 30.44, 1)})
    out.sort(key=lambda x: -x["missing_days"])
    return out


def render_compensation(sf):
    """رسالة التعويض لصف من shortfalls()."""
    first = (sf.get("name") or "").split(" ")[0] or "عميلنا"
    new_exp = (parse_date(sf["real_exp"]) + datetime.timedelta(days=sf["missing_days"])).isoformat()
    return TEMPLATES["compensation"][1].format(
        name=first, paid_months=f"{sf['months']} شهرًا", real_exp=sf["real_exp"],
        missing=_days_ar(sf["missing_days"]), new_exp=new_exp)


# ═════════ العملاء والشرائح ═════════
def _today(): return datetime.date.today()


def customers():
    """يجمع الطلبات في عملاء (مفتاحهم الجوال) مع المتبقي والترشيح."""
    st = load_subs(); wa = load_wa()
    optout = set(wa["optout"])
    last_sent = {}
    for s in wa["sent"]:
        if s["phone"] not in last_sent or s["at"] > last_sent[s["phone"]]["at"]:
            last_sent[s["phone"]] = s
    by = {}
    for o in st["orders"].values():
        if not o["paid"] or not o["phone"]: continue
        d = parse_date(o["date"])
        for s in o["subs"]:
            exp = parse_date(o["real_exp"]) or add_months(d, s["months"])
            c = by.setdefault(o["phone"], {"phone": o["phone"], "name": o["name"], "city": o["city"],
                                           "email": o["email"], "code": "", "count": 0, "spend": 0.0,
                                           "first": d, "last_exp": exp, "last_product": s["product"],
                                           "last_months": s["months"], "orders": []})
            c["count"] += s["qty"]; c["spend"] += s["price"] * s["qty"]
            c["orders"].append({"order": o["order"], "date": o["date"], "product": s["product"],
                                "months": s["months"], "exp": exp.isoformat(), "price": s["price"]})
            if o["code"]: c["code"] = o["code"]
            if o["name"] and not c["name"]: c["name"] = o["name"]
            if d < c["first"]: c["first"] = d
            if exp > c["last_exp"]:
                c["last_exp"] = exp; c["last_product"] = s["product"]; c["last_months"] = s["months"]
    out = []
    t = _today()
    for c in by.values():
        rem = (c["last_exp"] - t).days
        primary, alt = recommend(c["last_product"], c["last_months"])
        ls = last_sent.get(c["phone"])
        out.append({**c, "first": c["first"].isoformat(), "last_exp": c["last_exp"].isoformat(),
                    "rem": rem, "segment": segment_of(rem), "repeat": c["count"] > 1,
                    "spend": round(c["spend"], 2), "optout": c["phone"] in optout,
                    "last_sent": ls["at"] if ls else "", "sent_kind": ls["kind"] if ls else "",
                    "plan": primary, "plan_alt": alt, "orders": sorted(c["orders"], key=lambda x: x["date"])})
    out.sort(key=lambda c: c["rem"])
    return out


SEGMENTS = [("expired", "منتهٍ", "منتهية اشتراكاتهم"),
            ("d7", "ينتهي خلال ٧ أيام", "على وشك الانتهاء"),
            ("d30", "ينتهي خلال ٣٠ يومًا", "قرب الانتهاء"),
            ("d90", "ينتهي خلال ٩٠ يومًا", "تحت المتابعة"),
            ("active", "ساري", "بعيد عن الانتهاء")]


def segment_of(rem):
    if rem < 0:  return "expired"
    if rem <= 7: return "d7"
    if rem <= 30: return "d30"
    if rem <= 90: return "d90"
    return "active"


def stats(cs=None):
    cs = cs if cs is not None else customers()
    c = {k: 0 for k, _, _ in SEGMENTS}
    for x in cs: c[x["segment"]] += 1
    rep = sum(1 for x in cs if x["repeat"])
    sf = shortfalls()
    return {"customers": len(cs), "repeat": rep,
            "shortfalls": len(sf), "shortfall_days": sum(x["missing_days"] for x in sf),
            "spend": round(sum(x["spend"] for x in cs), 2),
            "with_code": sum(1 for x in cs if x["code"]),
            "optout": sum(1 for x in cs if x["optout"]),
            "segments": c, "updated": load_subs().get("updated", "")}


# ═════════ الرسائل ═════════
TEMPLATES = {
    "d7":      ("قبل الانتهاء بأيام",
                "مرحبًا {name} 👋\nاشتراكك في سمارت سوق ينتهي {when} — وبعدها ينقطع البث.\n\n"
                "جدّد الآن واحتفظ بنفس الإعدادات على جهازك:\n{plan_name} — {plan_price} ريال\n{plan_url}\n\n"
                "لأي استفسار راسلنا هنا مباشرة."),
    "expiry":  ("يوم الانتهاء",
                "مرحبًا {name} 👋\nاشتراكك انتهى اليوم. جدّده خلال ٢٤ ساعة ويعود البث فورًا بنفس الإعدادات:\n\n"
                "{plan_name} — {plan_price} ريال\n{plan_url}"),
    "after3":  ("بعد ٣ أيام من الانتهاء",
                "مرحبًا {name} 👋\nمرّت ثلاثة أيام على انتهاء اشتراكك. كودك محفوظ عندنا، والتجديد يعيده كما كان:\n\n"
                "{plan_name} — {plan_price} ريال\n{plan_url}\n\n"
                "إن واجهتك مشكلة في الجهاز أخبرنا ونحلّها معك."),
    "compensation": ("تعويض عن نقص في المدة",
                "مرحبًا {name} 👋\nراجعنا اشتراكك في سمارت سوق ووجدنا أنه فُعّل بمدة أقل مما دفعت:\n"
                "دفعت {paid_months} وفُعّل لك حتى {real_exp} — بفارق {missing}.\n\n"
                "الخطأ منّا، وقد أضفنا المدة الناقصة إلى اشتراكك بلا أي رسوم. "
                "تاريخ انتهائك الجديد {new_exp}.\n\nنعتذر عن الخلل، وشكرًا لثقتك بنا."),
    "after14": ("بعد أسبوعين — آخر تذكير",
                "مرحبًا {name} 👋\nآخر تذكير منّا. لو رجعت اليوم نفعّل لك الاشتراك على نفس الجهاز بلا إعادة ضبط:\n\n"
                "{plan_name} — {plan_price} ريال\n{plan_url}\n\n"
                "وإن كنت لا ترغب بالتذكير، ردّ بكلمة (إيقاف) ولن نراسلك."),
}


def _days_ar(n):
    n = abs(n)
    if n == 0:  return "اليوم"
    if n == 1:  return "يوم واحد"
    if n == 2:  return "يومين"
    if n <= 10: return f"{n} أيام"
    return f"{n} يومًا"


def _when_ar(n):
    """صياغة الزمن في الجملة: اليوم/غدًا/بعد كذا — لا "بعد اليوم"."""
    if n <= 0: return "اليوم"
    if n == 1: return "غدًا"
    return "بعد " + _days_ar(n)


def render(cust, kind):
    t = TEMPLATES.get(kind)
    if not t: return ""
    p = cust.get("plan") or {}
    first = (cust.get("name") or "").split(" ")[0] or "عميلنا"
    return t[1].format(name=first, days=_days_ar(cust.get("rem", 0)),
                       when=_when_ar(cust.get("rem", 0)),
                       product=cust.get("last_product", ""),
                       plan_name=p.get("name", "باقة سمارت سوق"),
                       plan_price=p.get("price", ""), plan_url=p.get("url", "https://ssouq.com"))


def wa_link(phone, text):
    return f"https://wa.me/{phone}?text={quote(text)}"


def log_send(phone, kind, ok=True, note=""):
    wa = load_wa()
    wa["sent"].append({"phone": phone, "kind": kind, "ok": bool(ok), "note": note,
                       "at": datetime.datetime.now().isoformat(timespec="seconds")})
    wa["sent"] = wa["sent"][-5000:]
    save_wa(wa)
    return len([s for s in wa["sent"] if s["at"][:10] == datetime.date.today().isoformat()])


def sent_today():
    wa = load_wa(); today = datetime.date.today().isoformat()
    return len([s for s in wa["sent"] if s["at"][:10] == today and s.get("ok")])


def set_optout(phone, on=True):
    wa = load_wa(); ph = norm_phone(phone)
    if on and ph not in wa["optout"]: wa["optout"].append(ph)
    if not on and ph in wa["optout"]: wa["optout"].remove(ph)
    save_wa(wa)
    return wa["optout"]

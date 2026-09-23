#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
قراءة ملفات سلة (الطلبات والمنتجات) → فهرس التجديد + تحليله.

مصدرٌ واحد للحقيقة: الأداة على السطر (`tools/build_renew_index.py`) وصفحةُ الرفع
في لوحة الإدارة كلتاهما تناديان هذا الملف، فلا يفترق رقمٌ بين طريقين.

ما يقرؤه:
  • **ملف الطلبات** — تصدير سلة المعتاد. منه رقم الطلب والجوال وتاريخ الشراء
    و`skus_json` (المنتجات وكمياتها).
  • **ملف المنتجات** — اختياري. يربط الـSKU باسم المنتج ومدته، فتُقرأ المدة من
    المنتج لا من نصّ اسمه داخل الطلب.

التكرار يُحذف مرتين: ملفات متطابقة بالبصمة، ثم أرقام طلبات تكرّرت بين الملفات.

**الوحدة هنا يوزر، لا طلب.** طلبٌ بكمية ٢ = يوزران، لأن التكلفة تُحسب بالخطوط.
stdlib فقط.
"""
import csv
import hashlib
import io
import json
import os
import re

import renew

CONFIRMED = ("طلبك مؤكد", "مكتمل", "تم التنفيذ", "جاري التنفيذ", "completed", "paid")

# فالكون خارج التجديد: لوحته قائمة بذاتها ولا يُنقل عملاؤها إلى مرح.
EXCLUDE = re.compile(r"فالكون|falcon", re.I)

# منتجات قديمة لا تحمل مدة في اسمها. سعر الوحدة ٤٠ ر.س وهو سعر شريحة السنة
# نفسها في بقية المنتجات، فتُقرأ سنةً — وتُعلَّم `inferred` ليبقى الاستنتاج ظاهرًا.
INFERRED_MONTHS = {
    "iptv smarters pro": 12,
    "iptv smarters pro | سمارت اي بي تي في": 12,
}

ORDER_COLS = {"order": "رقم الطلب", "status": "حالة الطلب", "phone": "رقم الجوال",
              "date": "تاريخ الطلب", "skus": "skus_json", "total": "إجمالي المبيعات"}

# أعمدة ملف المنتجات تختلف بين تصديرات سلة، فتُقرأ بعدّة أسماء محتملة.
PRODUCT_COLS = {
    "id":    ("معرف المنتج", "رقم المنتج", "id", "product_id"),
    "name":  ("اسم المنتج", "الاسم", "name", "product_name"),
    "sku":   ("SKU", "sku", "رمز المنتج", "الرمز"),
    "price": ("السعر", "price", "سعر المنتج"),
}


# ============================ قراءة عامة ============================
def _decode(raw):
    for enc in ("utf-8-sig", "utf-8", "cp1256", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _rows(raw):
    text = _decode(raw)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return list(csv.DictReader(io.StringIO(text), dialect=dialect))


def _pick(row, names):
    for n in names:
        if n in row and str(row[n]).strip():
            return str(row[n]).strip()
    return ""


def dedupe_files(files):
    """[(اسم، بايتات)] → (المحفوظة، أسماء المتطابقة). البصمة تكشف الملف المكرر
    مهما اختلف اسمه."""
    seen, keep, dups = {}, [], []
    for name, raw in files:
        h = hashlib.md5(raw).hexdigest()
        if h in seen:
            dups.append(name)
        else:
            seen[h] = name
            keep.append((name, raw))
    return keep, dups


# ============================ المنتجات ============================
def months_of(name):
    """مدة الباقة من اسم المنتج. يرجّع (أشهر، أمُستنتَج؟)."""
    s = str(name or "").translate(renew._AR_DIGITS)
    if s.strip().lower() in INFERRED_MONTHS:
        return INFERRED_MONTHS[s.strip().lower()], True
    if re.search(r"سنتين", s):
        return 24, False
    m = re.search(r"(\d{1,2})\s*(?:شهر|شهرا|شهراً|اشهر|أشهر|شهور|month)", s)
    if m:
        return int(m.group(1)), False
    if re.search(r"سن[ةه]|year|عام", s):
        return 12, False
    return 0, False


def devices_of(name):
    s = str(name or "").translate(renew._AR_DIGITS)
    if "جهازين" in s or re.search(r"2\s*(?:جهاز|device|connection)", s, re.I):
        return 2
    m = re.search(r"(\d)\s*(?:اجهزة|أجهزة|devices?|connections?)", s, re.I)
    return int(m.group(1)) if m else 1


def read_products(files):
    """ملف منتجات سلة → {sku: {...}} و{اسم: {...}}، مع مدة كل منتج.

    يُستعمل لسببين: قراءة المدة من المنتج بدل اسمه داخل الطلب، وعرض قائمة
    المنتجات للمدير ليربط كلًّا منها بباقة على مرح."""
    by_sku, by_name, rows = {}, {}, []
    for name, raw in files:
        for r in _rows(raw):
            pname = _pick(r, PRODUCT_COLS["name"])
            if not pname:
                continue
            mo, inferred = months_of(pname)
            rec = {"id": _pick(r, PRODUCT_COLS["id"]), "name": pname,
                   "sku": _pick(r, PRODUCT_COLS["sku"]),
                   "price": _pick(r, PRODUCT_COLS["price"]),
                   "months": mo, "devices": devices_of(pname),
                   "inferred": inferred, "falcon": bool(EXCLUDE.search(pname)),
                   "file": name}
            rows.append(rec)
            if rec["sku"]:
                by_sku[rec["sku"]] = rec
            by_name[pname.strip().lower()] = rec
    return {"by_sku": by_sku, "by_name": by_name, "rows": rows}



# ============================ الاعتمادات داخل الطلب ============================
# بيانات الاشتراك تُكتب يدويًا في ملاحظة الطلب، فتختلف صياغتها من كاتب لآخر ومن
# شهر لآخر. رأينا في ملفات سلة وحدها: «Host:» و«Host-URL:»، وبفواصل أسطر تارةً
# و«|» تارة، وبمنفذ وبغيره. ويُكتب أيضًا «host» بلا نقطتين، و«UserName» بحرف
# كبير، و«Passowrd» مصحَّفًا. فالقراءة هنا تتسامح مع الشكل وتتمسّك بالمعنى.
_C_HOST = re.compile(
    r"(?i)\bhost(?:[\w-]*)\s*[:=]?\s*['\"]?"
    r"((?:https?://)?[a-z0-9][a-z0-9.\-]*\.[a-z]{2,}(?::\d{1,5})?)")
_C_USER = re.compile(r"(?i)\buser\s*-?\s*(?:name)?\s*[:=]\s*['\"]?([A-Za-z0-9._\-]{3,64})")
_C_PASS = re.compile(r"(?i)\bpass\w*\s*[:=]\s*['\"]?([^\s|,;\"']{3,64})")
_EMAILY = re.compile(r"[A-Za-z0-9._%+-]@")


_TAGS = re.compile(r"<[^>]+>")
_ENT = {"&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'"}


def strip_html(text):
    """‏`Host: x<br />Username: y` → سطران. سلة تحفظ ملاحظات السجل بـHTML."""
    s = _TAGS.sub("\n", str(text or ""))
    for k, v in _ENT.items():
        s = s.replace(k, v)
    return s


def parse_credentials(text):
    """نصٌّ حرّ → {host, username, password} بما وُجد منها، وإلا {}.

    الهوست بلا نقطتين (`host http://x`) يُقبل فقط إذا صحبه يوزر أو باسورد في
    النصّ نفسه — وإلا صار كل ذكرٍ لكلمة «hosting» هوستًا."""
    s = strip_html(text)
    if not s.strip():
        return {}
    out = {}
    u = _C_USER.search(s)
    p = _C_PASS.search(s)
    if u:
        out["username"] = u.group(1)
    if p:
        out["password"] = p.group(1)
    for m in _C_HOST.finditer(s):
        host = m.group(1)
        if _EMAILY.search(s[max(0, m.start(1) - 1):m.start(1) + 1]):
            continue                        # ‏host_12@live.com بريدٌ لا هوست
        explicit = "=" in m.group(0) or ":" in m.group(0)[:m.group(0).find(host)]
        if explicit or out:
            out["host"] = host if host.startswith(("http://", "https://")) else "http://" + host
            break
    return out


def credentials_of(row):
    """يفتّش أعمدة الطلب كلها عن كتلة اعتماد — فالكاتب قد يضعها في الملاحظة
    الداخلية أو في العنوان أو في أي حقل حرّ."""
    best = {}
    for col, v in row.items():
        if col == ORDER_COLS["skus"] or not v:
            continue
        got = parse_credentials(v)
        if len(got) > len(best):
            best = got
        if len(best) == 3:
            break
    return best


# ============================ الطلبات ============================
def read_orders(files, products=None, keep_unconfirmed=False, include_falcon=False):
    """ملفات طلبات → (وحدات، تقرير). الوحدة يوزر واحد: كمية ٢ تعطي وحدتين."""
    keep, dup_files = dedupe_files(files)
    products = products or {"by_sku": {}, "by_name": {}}

    units, seen_orders, dup_orders = [], set(), []
    skipped = {"unconfirmed": 0, "falcon": 0, "no_months": 0, "no_date": 0, "no_items": 0}
    bad_files = []

    for fname, raw in keep:
        try:
            rows = _rows(raw)
        except Exception as e:
            bad_files.append({"file": fname, "error": str(e)[:120]})
            continue
        if not rows or ORDER_COLS["order"] not in rows[0]:
            bad_files.append({"file": fname, "error": "لا يبدو ملف طلبات سلة (لا عمود «رقم الطلب»)"})
            continue
        for r in rows:
            no = renew.norm_order(r.get(ORDER_COLS["order"]))
            if not no:
                continue
            if no in seen_orders:
                dup_orders.append(no)
                continue
            seen_orders.add(no)

            status = (r.get(ORDER_COLS["status"]) or "").strip()
            if not keep_unconfirmed and status not in CONFIRMED:
                skipped["unconfirmed"] += 1
                continue
            date = renew.parse_date(r.get(ORDER_COLS["date"]))
            if not date:
                skipped["no_date"] += 1
                continue
            try:
                items = json.loads(r.get(ORDER_COLS["skus"]) or "[]")
            except ValueError:
                items = []
            if not items:
                skipped["no_items"] += 1
                continue
            if not include_falcon and any(
                    isinstance(it, list) and it and EXCLUDE.search(str(it[0])) for it in items):
                skipped["falcon"] += 1          # فالكون لوحةٌ قائمة بذاتها، لا تُنقل لمرح
                continue

            phone = renew.norm_phone(r.get(ORDER_COLS["phone"]))
            cred = credentials_of(r)          # قد تكون مكتوبة يدويًا في الطلب
            for it in items:
                if not isinstance(it, list) or not it:
                    continue
                pname = str(it[0])
                qty = int(it[1] or 1) if len(it) > 1 else 1
                sku = str(it[2] or "") if len(it) > 2 else ""
                # المنتج يُعرَّف بالـSKU أولًا، ثم بالاسم، ثم بقراءة الاسم نفسه.
                prod = products["by_sku"].get(sku) or products["by_name"].get(pname.strip().lower())
                if prod and prod.get("months"):
                    mo, dev, inferred = prod["months"], prod["devices"], prod.get("inferred", False)
                else:
                    mo, inferred = months_of(pname)
                    dev = devices_of(pname)
                if not mo:
                    skipped["no_months"] += qty
                    continue
                expiry = renew.add_months(date, mo)
                for _ in range(max(1, min(qty, 20))):
                    units.append({"order": no, "phone": phone, "date": date.isoformat(),
                                  "product": pname, "sku": sku, "months": mo,
                                  "devices": dev, "inferred": inferred,
                                  "expiry": expiry.isoformat(), **cred})

    return units, {"files_seen": len(keep) + len(dup_files), "files_kept": len(keep),
                   "files_dup": len(dup_files), "dup_names": dup_files,
                   "orders": len(seen_orders), "orders_dup": len(dup_orders),
                   "dup_orders": sorted(set(dup_orders))[:50],
                   "skipped": skipped, "bad_files": bad_files}


# ============================ الفهرس ============================
def build_index(units, meta=None):
    """وحدات → فهرس التجديد. الطلب الواحد يُفهرس بأطول مدة فيه — هي ما يستحقّه."""
    orders = {}
    for u in units:
        cur = orders.get(u["order"])
        if not cur or u["months"] > cur["months"]:
            orders[u["order"]] = {"phone": u["phone"], "date": u["date"],
                                  "months": u["months"], "devices": u["devices"],
                                  **({"inferred": True} if u["inferred"] else {}),
                                  **{k: u[k] for k in ("host", "username", "password", "sid")
                                     if u.get(k)}}
    return {"orders": orders, "built": renew.now_iso(),
            "source_files": (meta or {}).get("files_kept", 0),
            "stats": meta or {}}


# ============================ التحليل ============================
def analyze(units, meta=None, today=None):
    """وحدات → الأرقام التي تُبنى عليها القرارات: كم يوزرًا، وكم يكلّف تجديدهم."""
    today = today or renew._today()
    meta = meta or {}

    def count(key, rows=None):
        c = {}
        for u in (rows if rows is not None else units):
            k = key(u)
            c[k] = c.get(k, 0) + 1
        return [{"k": k, "n": c[k]} for k in sorted(c)]

    live, dead = [], []
    for u in units:
        exp = renew.parse_date(u["expiry"])
        days = (exp - today).days if exp else 0
        if days > 0:
            months = max(1, renew.months_between(today, exp))
            live.append({**u, "remaining": months, "tier": renew.tier_for(months)})
        else:
            dead.append(u)

    phones = {u["phone"] for u in live if u["phone"]}
    per_phone = {}
    for u in live:
        if u["phone"]:
            per_phone[u["phone"]] = per_phone.get(u["phone"], 0) + 1
    multi = {}
    for n in per_phone.values():
        multi[n] = multi.get(n, 0) + 1

    tiers = {}
    for u in live:
        k = (u["tier"], u["devices"])
        tiers[k] = tiers.get(k, 0) + 1

    prods = {}
    for u in units:
        k = (u["product"], u["months"], u["devices"], u["inferred"])
        prods[k] = prods.get(k, 0) + 1

    hosts = {}
    with_cred = 0
    for u in units:
        if u.get("username") or u.get("password"):
            with_cred += 1
        if u.get("host"):
            h = u["host"].lower().replace("http://", "").replace("https://", "")
            hosts[h] = hosts.get(h, 0) + 1

    return {
        "today": today.isoformat(),
        "creds": {"with_credentials": with_cred,
                  "hosts": [{"k": h, "n": n} for h, n in
                            sorted(hosts.items(), key=lambda x: -x[1])]},
        "files": {"total": meta.get("files_seen", 0), "kept": meta.get("files_kept", 0),
                  "dup": meta.get("files_dup", 0), "dup_names": meta.get("dup_names", []),
                  "bad": meta.get("bad_files", [])},
        "orders": {"unique": meta.get("orders", 0), "dup": meta.get("orders_dup", 0),
                   "dup_ids": meta.get("dup_orders", []),
                   "skipped": meta.get("skipped", {})},
        "units": {"all": len(units), "active": len(live), "expired": len(dead),
                  "phones_active": len(phones)},
        "tiers": [{"months": m, "devices": d, "n": n}
                  for (m, d), n in sorted(tiers.items())],
        "remaining": count(lambda u: u["remaining"], live),
        "expiry_month": count(lambda u: u["expiry"][:7]),
        "order_month": count(lambda u: u["date"][:7]),
        "multi": [{"k": k, "n": multi[k]} for k in sorted(multi)],
        "products": sorted(
            [{"name": k[0], "months": k[1], "devices": k[2], "inferred": k[3], "n": n,
              "active": sum(1 for u in live if u["product"] == k[0])}
             for k, n in prods.items()], key=lambda x: -x["n"]),
    }


# ============================ التقرير ============================
TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "renew_report_tpl.html")
_PLACEHOLDER = "/*__DATA__*/{}"


def report_html(agg):
    """التحليل صفحةً واحدة قائمة بذاتها — لا شبكة ولا خطوط خارجية، فتُفتح وتُرسَل
    كما هي. القالب واحد للأداة وللوحة، فالصفحتان لا تختلفان."""
    with open(TEMPLATE, encoding="utf-8") as f:
        tpl = f.read()
    return tpl.replace(_PLACEHOLDER, json.dumps(agg, ensure_ascii=False, separators=(",", ":")))


# ============================ رفع الملفات ============================
MAX_UPLOAD = 48 * 1024 * 1024          # سقف الجسم الواحد


def parse_multipart(content_type, body):
    """multipart/form-data → (حقول، ملفات). محلّل صغير بدل `cgi` المحذوف من 3.13."""
    m = re.search(r'boundary=(?:"([^"]+)"|([^;]+))', content_type or "", re.I)
    if not m:
        return {}, []
    delim = b"--" + (m.group(1) or m.group(2)).strip().encode()
    fields, files = {}, []
    for part in body.split(delim):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        head, sep, data = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        dis = re.search(r"Content-Disposition:[^\r\n]*",
                        head.decode("utf-8", "replace"), re.I)
        if not dis:
            continue
        name = re.search(r'name="([^"]*)"', dis.group(0))
        fn = re.search(r'filename="([^"]*)"', dis.group(0))
        data = data[:-2] if data.endswith(b"\r\n") else data
        if fn and fn.group(1):
            files.append((name.group(1) if name else "", fn.group(1), data))
        elif name:
            fields[name.group(1)] = data.decode("utf-8", "replace")
    return fields, files


def looks_like_orders(raw):
    """أهذا ملف طلبات أم منتجات؟ يُقرأ من العناوين، فلا يحتاج المدير أن يرتّبهما."""
    head = _decode(raw[:8192]).splitlines()[:1]
    line = head[0] if head else ""
    return ORDER_COLS["order"] in line or "skus_json" in line


def ingest(files, keep_unconfirmed=False, include_falcon=False):
    """ملفات مرفوعة (طلبات ومنتجات مختلطة) → (وحدات، تقرير، منتجات، تحليل)."""
    orders_f = [(n, b) for n, b in files if looks_like_orders(b)]
    products_f = [(n, b) for n, b in files if not looks_like_orders(b)]
    products = read_products(products_f) if products_f else None
    units, meta = read_orders(orders_f, products, keep_unconfirmed, include_falcon)
    meta["products_files"] = [n for n, _ in products_f]
    meta["orders_files"] = [n for n, _ in orders_f]
    agg = analyze(units, meta)
    agg["catalog"] = (products or {}).get("rows", [])
    return units, meta, products, agg


# ============================ السحب من سلة مباشرة ============================
# تصدير سلة ناقص: لا يُخرج سجل الطلب، وبيانات الاشتراك تُكتب فيه تعليقًا. والسحب
# من الواجهة يعطي الطلبات كلها ومعها سجلّها — فلا ملفات ولا نقص.

def _salla_phone(cust):
    code = str((cust or {}).get("mobile_code") or "").strip()
    mob = str((cust or {}).get("mobile") or "").strip()
    return renew.norm_phone((code + mob) if code else mob)


def salla_order_units(order, keep_unconfirmed=False, include_falcon=False):
    """طلبٌ من واجهة سلة → وحدات (يوزر لكل نسخة). بنفس شكل قراءة الملفات."""
    status = str(((order.get("status") or {}).get("customized") or {}).get("name")
                 or (order.get("status") or {}).get("name") or "").strip()
    if not keep_unconfirmed and status not in CONFIRMED:
        return [], "unconfirmed"
    no = renew.norm_order(order.get("reference_id") or order.get("id"))
    date = renew.parse_date(((order.get("date") or {}).get("date")) or order.get("date"))
    if not no or not date:
        return [], "no_date"
    items = [it for it in (order.get("items") or []) if isinstance(it, dict)]
    if not items:
        return [], "no_items"
    if not include_falcon and any(EXCLUDE.search(str(it.get("name", ""))) for it in items):
        return [], "falcon"

    phone = _salla_phone(order.get("customer"))
    out = []
    for it in items:
        pname = str(it.get("name") or "")
        mo, inferred = months_of(pname)
        if not mo:
            continue
        dev = devices_of(pname)
        expiry = renew.add_months(date, mo)
        for _ in range(max(1, min(int(it.get("quantity") or 1), 20))):
            out.append({"order": no, "sid": str(order.get("id") or ""), "phone": phone,
                        "date": date.isoformat(), "product": pname, "sku": "",
                        "months": mo, "devices": dev, "inferred": inferred,
                        "expiry": expiry.isoformat()})
    return (out, "") if out else ([], "no_months")


def pull_from_salla(token, progress=None, with_history=True, stop=None,
                    keep_unconfirmed=False, include_falcon=False, per_page=50):
    """يسحب طلبات المتجر كلها → (وحدات، تقرير).

    على مرحلتين: الطلبات أولًا (صفحةٌ لكل خمسين)، ثم — إن طُلب — سجلُّ كل طلبٍ
    أُبقي، لاستخراج ما كُتب فيه من يوزر وباسورد. المرحلة الثانية نداءٌ لكل طلب
    فهي الأبطأ، ولذلك تُبلَّغ بالتقدّم وتقبل الإيقاف."""
    import salla_api

    units, seen = [], set()
    skipped = {"unconfirmed": 0, "falcon": 0, "no_months": 0, "no_date": 0, "no_items": 0}
    page, pages, total = 1, 1, 0

    while page <= pages:
        if stop and stop():
            break
        rows, pg = salla_api.orders_page(token, page, per_page)
        pages, total = pg["pages"], pg["total"]
        for o in rows:
            got, why = salla_order_units(o, keep_unconfirmed, include_falcon)
            if why:
                skipped[why] = skipped.get(why, 0) + 1
            for u in got:
                if u["order"] in seen and not got:
                    continue
                seen.add(u["order"])
                units.append(u)
        if progress:
            progress({"phase": "orders", "done": page, "total": pages,
                      "units": len(units), "orders_total": total})
        page += 1
        if not rows:
            break

    found = 0
    if with_history:
        by_sid = {}
        for u in units:
            if u.get("sid"):
                by_sid.setdefault(u["sid"], []).append(u)
        sids = list(by_sid)
        for i, sid in enumerate(sids, 1):
            if stop and stop():
                break
            cred = parse_credentials(salla_api.history_notes(token, sid))
            if cred:
                found += 1
                for u in by_sid[sid]:
                    u.update(cred)
            if progress and (i % 10 == 0 or i == len(sids)):
                progress({"phase": "history", "done": i, "total": len(sids),
                          "units": len(units), "found": found})

    return units, {"files_seen": 0, "files_kept": 0, "files_dup": 0, "dup_names": [],
                   "orders": len(seen), "orders_dup": 0, "dup_orders": [],
                   "skipped": skipped, "bad_files": [], "source": "salla",
                   "orders_total": total, "with_credentials": found}

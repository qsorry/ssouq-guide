#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""مطابقة يوزرات سلة بيوزرات اللوحات، والتحقّق من صلاحيتها.

الفكرة: كل لوحة (كاسبر/مرح/c4k…) دخولٌ واحد وعدّة هوستات للعملاء تتبعها.
تُسحب يوزرات كل لوحة مرّةً وتُخزَّن مفهرسةً باليوزر، وتُقرأ طلبات سلة فتُعرف
منها بيانات كل اشتراك (يوزره وهوسته ومدّته). ثم تُطابَق:

  - الطلب في سلة يُنسب للوحته عبر هوسته (renew.norm_host + خريطة الهوستات).
  - يُبحث يوزره في يوزرات تلك اللوحة المسحوبة.
      • غير موجود        → «مفقود على اللوحة».
      • موجود بمدّة أقصر  → «فرق مدّة» (سلة ١٥ شهرًا واللوحة ١٢ مثلًا).
      • موجود بنفس المدّة → «مطابق».

هذا الملف لا يعرف كيف يُسجَّل الدخول للوحة ولا كيف تُقرأ سلة — تلك في
xm_web/renew_import — بل يخزّن ما جُمع ويقارنه، فيبقى قابلًا للاختبار وحده.
"""

import json
import re
import os
import re

import renew


# ============================ مدّة الباقة ============================
_P_MONTHS = re.compile(r"(\d+)\s*(?:month|mon|mo|شهر|شهرا|شهراً|اشهر|أشهر|شهور)", re.I)
_P_YEARS = re.compile(r"(\d+)\s*(?:year|yr|سنة|سنه|سنوات|عام|أعوام)", re.I)
_P_DAYS = re.compile(r"(\d+)\s*(?:day|يوم|أيام|ايام)", re.I)


def parse_panel_months(package):
    """نصّ الباقة كما تكتبه اللوحة → عدد الأشهر. «15 Months»→15 · «1 Year»→12 ·
    «2 Years»→24 · «سنة ونصف»؟ لا تُخمَّن. الأيام (تجربة) → 0 فلا مدّة شهرية لها.

    قد يجتمع الاثنان («1 Year 3 Months») فتُجمع؛ والسنتان لفظًا («سنتين») حالةٌ
    خاصّة لأن رقمها غير مكتوب."""
    s = str(package or "").translate(renew._AR_DIGITS).strip()
    if not s:
        return 0
    months = 0
    y = _P_YEARS.search(s)
    if y:
        months += int(y.group(1)) * 12
    elif re.search(r"سنتين", s):
        months += 24
    elif re.search(r"\bسنة\b|\bسنه\b|\byear\b|\bعام\b", s, re.I):
        months += 12
    m = _P_MONTHS.search(s)
    if m:
        months += int(m.group(1))
    if months:
        return months
    # لا سنة ولا شهر مكتوبان: إن كانت أيامًا فقط فهي تجربة (بلا أشهر).
    return 0


def months_from_dates(created, exp):
    """أشهرٌ محسوبة من الإنشاء إلى الانتهاء — سندٌ حين لا تُقرأ من نصّ الباقة."""
    c, e = renew.parse_date(created), renew.parse_date(exp)
    if not c or not e or e <= c:
        return 0
    return max(0, renew.months_between(c, e))


def line_months(rec):
    """مدّة خطّ اللوحة: من نصّ الباقة أولًا (أوثق)، فإن غاب فمن التاريخين."""
    return parse_panel_months(rec.get("package")) or \
        months_from_dates(rec.get("created"), rec.get("exp"))


def expiry_status(exp, today, renewal_days):
    """حالة الانتهاء من تاريخ اللوحة: كم بقي، أمنتهٍ، أقريبٌ من الانتهاء.

    القريب: انتهاؤه بين اليوم و`renewal_days` يومًا — وقتُ رسالة التجديد."""
    d = renew.parse_date(exp)
    if not d:                                       # لوحة فالكون تكتب «Expired» مكان التاريخ
        gone = bool(re.search(r"(?i)expire|منته", str(exp or "")))
        return {"exp_date": "", "days_left": 0 if gone else None, "expired": gone, "expiring_soon": False}
    left = (d - today).days
    return {"exp_date": d.isoformat(), "days_left": left,
            "expired": left < 0, "expiring_soon": 0 <= left <= renewal_days}


# ============================ تخزين يوزرات اللوحات ============================
def panel_lines_path(data_dir):
    return os.path.join(data_dir, "renew_panel_lines.json")


def panel_data_for(pl, panel):
    """يوزرات لوحةٍ من المحفوظ: بمعرّفها، وإلا بأحدث سحبٍ يحمل اسمها (حفظٌ قديم للوحات
    كان يولّد معرّفًا جديدًا كل مرة فتنفصل اللوحة عمّا سُحب لها)."""
    d = pl.get(str(panel.get("id", "")))
    if d:
        return d
    same = [x for x in pl.values() if x.get("name") == panel.get("name") and x.get("count")]
    return max(same, key=lambda x: x.get("built", "")) if same else None


def load_panel_lines(data_dir):
    try:
        with open(panel_lines_path(data_dir), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("panels"), dict) \
            else {"panels": {}}
    except (OSError, ValueError):
        return {"panels": {}}


def save_panel_lines(data_dir, panel_id, name, rows):
    """يحفظ يوزرات لوحةٍ واحدة مفهرسةً باليوزر (بحروف صغيرة)، دون مسّ البقيّة."""
    by_user = {}
    for r in rows:
        u = str(r.get("username") or "").strip()
        if not u:
            continue
        by_user[u.lower()] = {
            "username": u, "password": str(r.get("password") or ""),
            "exp": str(r.get("exp") or ""), "package": str(r.get("package") or ""),
            "created": str(r.get("created") or ""),
            "connections": str(r.get("connections") or ""),
            "status": str(r.get("status") or ""),
            "months": line_months(r),
        }
    data = load_panel_lines(data_dir)
    data["panels"][str(panel_id)] = {"name": name, "built": renew.now_iso(),
                                     "count": len(by_user), "by_user": by_user}
    renew._write_json(panel_lines_path(data_dir), data)
    return len(by_user)


def panel_lines_stats(data_dir):
    d = load_panel_lines(data_dir)
    return {pid: {"name": p.get("name", ""), "count": p.get("count", 0),
                  "built": p.get("built", "")}
            for pid, p in d.get("panels", {}).items()}


# ============================ تخزين خطوط سلة ============================
# الوحدة = يوزرٌ واحد بيعَ في سلة، بما عُرف عنه: هوسته ومدّته وانتهاؤه. تُحفظ
# منها ما كُتب له يوزرٌ (وإلا فلا شيء نطابقه)، ومعها بلا يوزرٍ عدّتها لنُبلغ بها.
def store_lines_path(data_dir):
    return os.path.join(data_dir, "renew_store_lines.json")


def save_store_lines(data_dir, units):
    lines, no_user = [], 0
    for u in units:
        rec = {"order": u.get("order", ""), "date": u.get("date", ""),
               "phone": u.get("phone", ""), "customer": u.get("customer", ""),
               "sid": u.get("sid", ""), "admin_url": u.get("admin_url", ""),
               "price": u.get("price", ""), "status": u.get("status", ""),
               "falcon": bool(u.get("falcon")),
               "host": u.get("host", ""), "username": u.get("username", ""),
               "password": u.get("password", ""), "months": u.get("months", 0),
               "devices": u.get("devices", 1), "expiry": u.get("expiry", ""),
               "product": u.get("product", ""), "sku": u.get("sku", "")}
        if rec["username"]:
            lines.append(rec)
        else:
            no_user += 1
    renew._write_json(store_lines_path(data_dir),
                      {"built": renew.now_iso(), "count": len(lines),
                       "no_username": no_user, "lines": lines})
    return len(lines)


def known_orders(data_dir):
    """أرقام الطلبات المحفوظة في خطوط المتجر — ليُكمل السحب من حيث توقّف."""
    return {renew.norm_order(ln.get("order")) for ln in load_store_lines(data_dir).get("lines", [])
            if ln.get("order")}


def merge_store_lines(data_dir, units):
    """الخطوط المحفوظة + وحداتٌ جديدة، بلا تكرار (الطلب واليوزر): الجديد يغلب القديم."""
    old = load_store_lines(data_dir).get("lines", [])
    # الخطوط المحفوظة أقلّ حقولًا من الوحدات الحيّة (لا inferred مثلًا)، والتحليل
    # والفهرس يقرآنها بالمفتاح — فتُكمَّل بالافتراضيات قبل الدمج.
    defaults = {"inferred": False, "months": 0, "devices": 1, "phone": "", "date": "",
                "expiry": "", "product": "", "sku": "", "order": ""}
    old = [{**defaults, **u} for u in old]
    out, idx = [], {}
    for u in list(old) + list(units):
        key = (renew.norm_order(u.get("order")), str(u.get("username") or "").lower())
        if not key[1]:
            out.append(u)
            continue
        if key in idx:
            out[idx[key]] = u
        else:
            idx[key] = len(out)
            out.append(u)
    return out


def load_store_lines(data_dir):
    try:
        with open(store_lines_path(data_dir), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("lines"), list) \
            else {"lines": [], "no_username": 0}
    except (OSError, ValueError):
        return {"lines": [], "no_username": 0}


# ============================ خريطة الهوستات ============================
def host_index(panels):
    """{هوست مُوحّد: معرّف اللوحة}. آخر لوحة تعرّف هوستًا تكسبه إن تكرّر."""
    idx = {}
    for p in (panels or []):
        for h in (p.get("hosts") or []):
            nh = renew.norm_host(h)
            if nh:
                idx[nh] = p.get("id", "")
    return idx


# ============================ أكواد سلة المتاحة ============================
# الإضافة تقرأ من لوحة سلة (بجلسة المتصفّح) مخزون الأكواد غير المبيعة لكل منتجٍ
# رقمي، فيُعرف أيُّ يوزرٍ على اللوحات معروضٌ للبيع الآن — لا مبيعًا ولا منسيًّا.

def salla_codes_path(data_dir):
    return os.path.join(data_dir, "renew_salla_codes.json")


def _code_text(raw):
    """عنصر كودٍ كما تعطيه واجهة سلة (نصٌّ أو قاموس) → نصّه. الحقول بلا ثبات في
    الواجهة فتُجرَّب المعتادة، وإلا كل نصوص القاموس مجتمعة."""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        for k in ("code", "value", "text", "name", "content", "card", "serial"):
            v = raw.get(k)
            if isinstance(v, str) and v.strip():
                return v
        return " ".join(str(v) for v in raw.values() if isinstance(v, (str, int)))
    return str(raw or "")


def _code_status(raw):
    if not isinstance(raw, dict):
        return ""
    for k in ("status", "state", "is_sold", "sold", "used", "is_used"):
        v = raw.get(k)
        if v in (None, ""):
            continue
        if isinstance(v, bool):
            return "sold" if v else "available"
        return str(v).lower()
    return ""


def save_salla_codes(data_dir, products, reset=False):
    """يحفظ (أو يضيف) منتجات سلة الرقمية بأكوادها كما أرسلتها الإضافة. كل كود
    يُحلَّل إلى يوزر/باسورد/هوست ليُطابَق بيوزرات اللوحات. يرجّع ملخّصًا."""
    import renew_import
    data = {"built": renew.now_iso(), "products": []} if reset else load_salla_codes(data_dir)
    have = {str(p.get("id")): i for i, p in enumerate(data["products"])}
    for prod in (products or []):
        pid = str(prod.get("id") or "")
        codes, masked = [], 0
        raw_codes = prod.get("codes") or []
        if prod.get("html"):                   # نافذة اللوحة القديمة كما هي — نحلّلها هنا
            import salla_web
            raw_codes = salla_web.parse_product_codes(prod.get("html")) or raw_codes
        for raw in raw_codes:
            text = _code_text(raw)
            cred = renew_import.parse_credentials(text)
            if not cred.get("username"):
                masked += 1                    # مقنَّع (****) أو ليس اعتمادًا
            codes.append({"text": text[:300], "status": _code_status(raw),
                          "username": cred.get("username", ""),
                          "password": cred.get("password", ""),
                          "host": cred.get("host", "")})
        rec = {"id": pid, "name": str(prod.get("name") or ""), "sku": str(prod.get("sku") or ""),
               "type": str(prod.get("type") or ""), "total": int(prod.get("total") or len(codes)),
               "source": "legacy" if prod.get("html") else str(prod.get("source") or "api"),
               "codes": codes, "unparsed": masked, "at": renew.now_iso()}
        if pid in have:
            data["products"][have[pid]] = rec
        else:
            have[pid] = len(data["products"])
            data["products"].append(rec)
    data["built"] = renew.now_iso()
    renew._write_json(salla_codes_path(data_dir), data)
    return salla_codes_stats(data)


def load_salla_codes(data_dir):
    try:
        with open(salla_codes_path(data_dir), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("products"), list) \
            else {"built": "", "products": []}
    except (OSError, ValueError):
        return {"built": "", "products": []}


def salla_codes_stats(data):
    prods = data.get("products") or []
    return {"built": data.get("built", ""), "products": len(prods),
            "codes": sum(len(p.get("codes") or []) for p in prods),
            "with_username": sum(1 for p in prods for c in p.get("codes") or [] if c.get("username")),
            "unparsed": sum(int(p.get("unparsed") or 0) for p in prods),
            "list": [{"id": p["id"], "name": p["name"], "codes": len(p.get("codes") or []),
                      "unparsed": p.get("unparsed", 0)} for p in prods]}


def salla_codes_rows(data):
    """صفوف الأكواد المتاحة للعرض والتصدير: المنتج ثم كل كود بما قُرئ منه."""
    rows = []
    for p in data.get("products") or []:
        for c in p.get("codes") or []:
            rows.append({"product_id": p.get("id", ""), "product": p.get("name", ""), "sku": p.get("sku", ""),
                         "text": c.get("text", ""), "status": c.get("status", ""),
                         "username": c.get("username", ""), "password": c.get("password", ""),
                         "host": c.get("host", ""), "readable": bool(c.get("username"))})
    return rows


def salla_codes_by_user(data):
    out = {}
    for p in data.get("products") or []:
        for c in p.get("codes") or []:
            if c.get("username"):
                out[c["username"].lower()] = {"product": p.get("name", ""), "product_id": p.get("id", ""),
                                              "host": c.get("host", ""), "status": c.get("status", "")}
    return out


# ============================ المعلَّم يدويًا «معروض في سلة» ============================
# مخزون أكواد سلة قد يصل مقنَّعًا فلا يُعرف منه اليوزر؛ فيُعلّم المشغّل ما عرضه بنفسه
# (بعد نسخ سطر الكود ولصقه في سلة) ويبقى خارج «غير المعروض» حتى يُلغي تعليمه.

def listed_path(data_dir):
    return os.path.join(data_dir, "renew_listed.json")


def load_listed(data_dir):
    try:
        with open(listed_path(data_dir), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def mark_listed(data_dir, usernames, remove=False, note=""):
    """يعلّم يوزرات (أو يلغي تعليمها) كمعروضة في سلة يدويًا. يرجّع العدد الكلي المعلَّم."""
    d = load_listed(data_dir)
    for u in usernames or []:
        k = str(u or "").strip().lower()
        if not k:
            continue
        if remove:
            d.pop(k, None)
        else:
            d[k] = {"at": renew.now_iso(), "note": str(note or "")[:120]}
    renew._write_json(listed_path(data_dir), d)
    return len(d)


# ============================ لم تُعرض للبيع ============================

def remaining_text(exp, today=None):
    """«ينتهي بعد سنة و٢ شهر و٢٥ يومًا» بالتقويم من اليوم إلى تاريخ الانتهاء، أو
    «انتهى منذ …» لما مضى، أو "" إن لم يُفهم التاريخ."""
    end = renew.parse_date(exp)
    if not end:
        return "منتهٍ" if re.search(r"(?i)expire|منته", str(exp or "")) else ""
    today = today or renew._today()
    past = end < today
    a, b = (end, today) if past else (today, end)
    months = (b.year - a.year) * 12 + (b.month - a.month)
    if renew.add_months(a, months) > b:
        months -= 1
    days = (b - renew.add_months(a, months)).days
    y, m = divmod(months, 12)
    parts = []
    if y:
        parts.append("سنة" if y == 1 else ("سنتان" if y == 2 else "%d سنوات" % y if y <= 10 else "%d سنة" % y))
    if m:
        parts.append("شهر" if m == 1 else ("شهران" if m == 2 else "%d أشهر" % m if m <= 10 else "%d شهرًا" % m))
    if days or not parts:
        parts.append("يوم" if days == 1 else ("يومان" if days == 2 else "%d أيام" % days if days <= 10 else "%d يومًا" % days))
    text = " و".join(parts)
    return ("انتهى منذ " + text) if past else ("ينتهي بعد " + text)



GUIDE_BY_NAME = (("فالكون|falcon", "https://guide.ssouq.com/#activate/falcon"),
                 ("كاسبر|casper", "https://guide.ssouq.com/#activate/casper"),
                 ("مرح|سمارت|smart|marah", "https://guide.ssouq.com/#activate/smart"))


def panel_card(panel, gate=None):
    """(هوست البطاقة، رابط الشرح) للوحة. المصدر الأوّل **بوابة السحب نفسها** كما ضُبطت في
    admin.ssouq.com (هوست السطر ورابط شرحها الفعلي)، ثم ما كُتب في اللوحة، ثم أوّل
    هوستاتها بمنفذ 80 والشرح من اسمها (فالكون/كاسبر/مرح)."""
    gate = gate or {}
    host = panel.get("card_host") or str(gate.get("host") or "").strip()
    if not host:
        h = (panel.get("hosts") or [""])[0]
        host = ("http://%s:80" % h) if h else ""
    elif not host.startswith("http"):
        host = "http://" + host
    guide = panel.get("guide_url") or str(gate.get("guide_url") or "").strip()
    if not guide:
        for pat, url in GUIDE_BY_NAME:
            if re.search(pat, panel.get("name", ""), re.I):
                guide = url
                break
    return host, guide


def salla_card_line(host, username, password, guide=""):
    """سطر الكود بصيغة بطاقة سلة: «Host … User … Pass … Guide …» — يُلصق كما هو."""
    line = "Host %s User %s Pass %s" % (host or "-", username, password)
    return line + (" Guide " + guide if guide else "")


def unlisted(config, data_dir, include_expired=False, gates=None, split=None, replaced=None):
    """`gates`: {(account_id, gate_id): بوابةٌ بهوستها ورابط شرحها الفعلي} — لسطر الكود.
    `split`: {(account_id, gate_id): {يوزرات مسجَّلة في «حسابات متبقية»}} — ما جُزِّئ
    يبقى في القائمة بعلامة «مجزَّأ» (المشغّل ينسخه ويلصقه في سلة)، ويُعدّ فقط."""
    """يوزرات اللوحات التي لا هي مبيعة في سلة (خطوط المتجر) ولا معروضة في مخزون
    أكوادها: أُنشئت ونُسيت. لكل لوحةٍ صفوفها، وفي كل صف السطر الجاهز للنسخ
    (Host · Username · Password · Exp) ليُعرض من جديد أو يُجزَّأ."""
    cfg = renew.normalize_config(config)
    store = load_store_lines(data_dir)
    sold = {str(ln.get("username") or "").strip().lower() for ln in store.get("lines", []) if ln.get("username")}
    listed = salla_codes_by_user(load_salla_codes(data_dir))
    manual = load_listed(data_dir)                  # ما علّمه المشغّل بنفسه «معروض في سلة»
    pl = load_panel_lines(data_dir)["panels"]
    today = renew._today()
    rows, per_panel = [], {}
    for p in cfg["panels"]:
        pdata = panel_data_for(pl, p)
        if not pdata:                               # لوحةٌ لم تُسحب يوزراتها بعد: تُذكر لا تُخفى
            per_panel[p["id"]] = {"name": p["name"], "lines": 0, "sold": 0, "listed": 0,
                                  "unlisted": 0, "expired": 0, "not_pulled": True}
            continue
        host, guide = panel_card(p, (gates or {}).get((p.get("account_id", ""), p.get("gate_id", ""))))
        gk = (p.get("account_id", ""), p.get("gate_id", ""))
        in_split = (split or {}).get(gk, {})
        in_replaced = (replaced or {}).get(gk, set())   # بدائل مسلَّمة لعملاء: ليست غير معروضة
        n_sold = n_listed = n_unlisted = n_expired = n_split = n_replaced = 0
        for key, rec in pdata["by_user"].items():
            if key in sold:
                n_sold += 1
                continue
            if key in in_replaced:
                n_replaced += 1
                continue
            is_split = key in in_split              # مجزَّأ في «حسابات متبقية»: يبقى معروضًا هنا
            if is_split:                           # ليُنسخ ويُلصق في سلة، مع علامته
                n_split += 1
            if key in listed or key in manual:
                n_listed += 1
                continue
            es = expiry_status(rec.get("exp"), today, 0)
            expired = (bool(es["expired"]) or str(rec.get("status") or "").lower() in ("expired", "disabled", "banned")
                       or es["days_left"] == 0)        # ينتهي اليوم: لا يُباع
            if expired:
                n_expired += 1
                if not include_expired:
                    continue
            n_unlisted += 1
            months_left = 0
            if es["days_left"] is not None and es["days_left"] > 0:
                months_left = max(0, int(round(es["days_left"] / 30.4)))
            line = "Host %s Username %s Password %s" % (host or "-", rec["username"], rec.get("password", ""))
            if rec.get("exp"):
                line += " Exp " + rec["exp"]
            card = salla_card_line(host, rec["username"], rec.get("password", ""), guide)
            rows.append({"panel_id": p["id"], "panel_name": p["name"], "username": rec["username"],
                         "password": rec.get("password", ""), "host": host, "package": rec.get("package", ""),
                         "months": rec.get("months", 0), "created": rec.get("created", ""),
                         "exp": rec.get("exp", ""), "days_left": es["days_left"], "months_left": months_left,
                         "remaining": remaining_text(rec.get("exp"), today), "card": card,
                         "expired": expired, "status": rec.get("status", ""), "line": line,
                         "split": is_split,
                         "split_months": int((in_split.get(key) if isinstance(in_split, dict) else 0) or 0)})
        per_panel[p["id"]] = {"name": p["name"], "lines": pdata.get("count", 0), "sold": n_sold,
                              "listed": n_listed, "unlisted": n_unlisted, "expired": n_expired,
                              "split": n_split, "replaced": n_replaced, "built": pdata.get("built", "")}
    rows.sort(key=lambda r: (r["panel_name"], -(r["days_left"] or 0), r["username"]))
    return {"rows": rows, "panels": per_panel, "built": renew.now_iso(),
            "store_sold": len(sold), "salla_listed": len(listed), "manual_listed": len(manual),
            "codes_built": load_salla_codes(data_dir).get("built", "")}



def explain_user(config, data_dir, username, gates=None, split=None, replaced=None):
    """لماذا لا يظهر يوزرٌ في «غير المعروض»؟ يُفتَّش عنه في كل مصدرٍ ويُعاد كل ما
    وُجد: على أي لوحة، وفي أي طلبٍ بيع، وفي أي منتجٍ معروض، وهل جُزِّئ أو عُلِّم
    يدويًا أو انتهى. فيعرف المشغّل السبب بدل أن يخمّنه."""
    key = str(username or "").strip().lower()
    out = {"username": key, "panels": [], "sold": [], "listed": [], "split": [], "replaced": [], "manual": None,
           "expired": False, "reason": ""}
    if not key:
        return out
    cfg = renew.normalize_config(config)
    for ln in load_store_lines(data_dir).get("lines", []):
        if str(ln.get("username") or "").strip().lower() == key:
            out["sold"].append({"order": ln.get("order", ""), "product": ln.get("product", ""),
                                "date": ln.get("date", ""), "customer": ln.get("customer", "")})
    for p in load_salla_codes(data_dir).get("products") or []:
        for c in p.get("codes") or []:
            if str(c.get("username") or "").lower() == key:
                out["listed"].append({"product": p.get("name", ""), "product_id": p.get("id", "")})
    m = load_listed(data_dir).get(key)
    if m:
        out["manual"] = m
    pl = load_panel_lines(data_dir)["panels"]
    today = renew._today()
    for p in cfg["panels"]:
        pdata = panel_data_for(pl, p)
        rec = (pdata or {}).get("by_user", {}).get(key)
        if not rec:
            continue
        es = expiry_status(rec.get("exp"), today, 0)
        expired = (bool(es["expired"]) or str(rec.get("status") or "").lower() in ("expired", "disabled", "banned")
                   or es["days_left"] == 0)
        out["expired"] = out["expired"] or expired
        gk = (p.get("account_id", ""), p.get("gate_id", ""))
        if key in (split or {}).get(gk, {}):
            out["split"].append(p["name"])
        if key in (replaced or {}).get(gk, set()):
            out["replaced"].append(p["name"])
        out["panels"].append({"panel": p["name"], "exp": rec.get("exp", ""), "status": rec.get("status", ""),
                              "days_left": es["days_left"], "expired": expired})
    if not out["panels"]:
        out["reason"] = "ليس في يوزرات أي لوحة مسحوبة (اسحب اللوحات أولًا)"
    elif out["sold"]:
        out["reason"] = "مبيع في سلة: طلب %s" % "، ".join(str(x["order"]) for x in out["sold"][:5])
    elif out["replaced"]:
        out["reason"] = "بديلٌ مسلَّم لعميل عن رقمٍ قديم (الحسابات البديلة) — %s" % "، ".join(out["replaced"])
    elif out["split"]:
        out["reason"] = "مجزَّأ: مسجَّل في «حسابات متبقية» (%s)" % "، ".join(out["split"])
    elif out["listed"]:
        out["reason"] = "معروض في مخزون أكواد سلة: %s" % "، ".join(x["product"] for x in out["listed"][:3])
    elif out["manual"]:
        out["reason"] = "معلَّم يدويًا «معروض في سلة» (%s)" % out["manual"].get("at", "")
    elif out["expired"]:
        out["reason"] = "منتهٍ (أو ينتهي اليوم) فيُخفى إلا مع «إظهار المنتهي»"
    else:
        out["reason"] = "غير معروض — يجب أن يظهر في القائمة؛ أعد الحساب"
    return out


# ============================ المبيع المكرر ============================
# يوزرٌ واحدٌ بيع في أكثر من طلبٍ لعملاء مختلفين: الأول يحتفظ به، وكل طلبٍ لاحق يحتاج
# يوزرًا جديدًا بما بقي من مدته (تاريخ الطلب + مدة الباقة − اليوم). نفس الجوال = تجديدٌ
# لنفس العميل لا بيعٌ مكرر. ما أُنشئ له بديلٌ يُحفظ هنا فلا يُعرض ثانيةً.

def dupes_path(data_dir):
    return os.path.join(data_dir, "renew_dupes_done.json")


def load_dupes_done(data_dir):
    try:
        with open(dupes_path(data_dir), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def mark_dupe_done(data_dir, order, new_user, months, customer="", extra=None):
    d = load_dupes_done(data_dir)
    rec = {"new": str(new_user), "months": int(months or 0), "customer": str(customer or "")[:60],
           "at": renew.now_iso()}
    rec.update(extra or {})                       # msgs (رسائل واتساب)، renamed (تغيير القديم)
    d[str(order)] = rec
    renew._write_json(dupes_path(data_dir), d)
    return d


def update_dupe(data_dir, order, fields, add_msg=None):
    """يحدّث سجل طلبٍ منجَز (حقول جديدة، ورسالة تُضاف). يرجّع السجل أو None."""
    d = load_dupes_done(data_dir)
    rec = d.get(str(order))
    if not rec:
        return None
    rec.update(fields or {})
    if add_msg:
        rec.setdefault("msgs", []).append(add_msg)
    renew._write_json(dupes_path(data_dir), d)
    return rec


def dup_log_path(data_dir):
    return os.path.join(data_dir, "renew_dup_log.jsonl")


def log_dup_send(data_dir, msg, how, ok, error=""):
    """سجلٌّ يُضاف إليه ولا يُمحى: كل محاولة إرسال لرسالة بديل (نجحت أو فشلت) بنصّها كما أُرسلت."""
    rec = {"at": renew.now_iso(), "order": msg.get("order", ""), "kind": msg.get("kind", ""),
           "name": msg.get("name", ""), "phone": msg.get("phone", ""), "how": how, "ok": bool(ok),
           "error": str(error or "")[:200], "text": str(msg.get("text", ""))[:1500]}
    with open(dup_log_path(data_dir), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def sent_today(data_dir, day):
    """كم رسالةً أُرسلت (بالرقم المربوط، ناجحةً) في يومٍ — بقراءة السجل سطرًا سطرًا وفحص التاريخ نصًّا قبل التحليل،
    لا بتحميل السجل كله (قد يبلغ عشرات الميغابايت) مع كل طلب."""
    n, mark = 0, '"at": "%s' % day
    try:
        with open(dup_log_path(data_dir), encoding="utf-8") as f:
            for line in f:
                if mark not in line:
                    continue
                try:
                    m = json.loads(line)
                except ValueError:
                    continue
                n += bool(m.get("ok") and m.get("how") != "manual")
    except OSError:
        pass
    return n


def load_dup_log(data_dir, limit=500):
    out = []
    try:
        with open(dup_log_path(data_dir), encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out[::-1][:limit]


def set_dupe_msg(data_dir, order, idx, **fields):
    """يحدّث رسالةً من رسائل بديل مكرر (نصها، أو أنها أُرسلت وكيف). يرجّع الرسالة أو None."""
    d = load_dupes_done(data_dir)
    msgs = (d.get(str(order)) or {}).get("msgs") or []
    if not (isinstance(idx, int) and 0 <= idx < len(msgs)):
        return None
    msgs[idx].update(fields)
    renew._write_json(dupes_path(data_dir), d)
    return msgs[idx]


def dupe_messages(data_dir):
    """كل رسائل البدائل المُنشأة (الأحدث أولًا) — لتُرسل أو يُعاد إرسالها."""
    out = []
    for order, rec in load_dupes_done(data_dir).items():
        for i, m in enumerate(rec.get("msgs") or []):
            out.append(dict(m, order=order, idx=i, at=rec.get("at", "")))
    out.sort(key=lambda m: m["at"], reverse=True)
    return out


def suggest_slice(days_left):
    """أشهر الجزء المقترحة لما تبقّى: أقرب شهر كامل، من شهرٍ إلى ١٥ (١٥ = الباقة كاملة)."""
    if days_left is None or days_left <= 0:
        return 0
    return max(1, min(15, int(round(days_left / 30.4))))


def duplicates(config, data_dir, today=None):
    """الطلبات التي بيع يوزرها قبلها لعميلٍ آخر. صفٌّ لكل طلبٍ لاحق، الأقدم دومًا يحتفظ باليوزر."""
    cfg = renew.normalize_config(config)
    hidx = host_index(cfg["panels"])
    pmap = {p["id"]: p for p in cfg["panels"]}
    today = today or renew._today()
    done = load_dupes_done(data_dir)
    groups = {}
    for ln in load_store_lines(data_dir).get("lines", []):
        u = str(ln.get("username") or "").strip()
        if not u:
            continue
        nh = renew.norm_host(ln.get("host"))
        groups.setdefault((hidx.get(nh) or nh, u.lower()), []).append(ln)
    rows = []
    for (pid, _u), lns in groups.items():
        by_order = {}
        for ln in lns:
            by_order.setdefault(str(ln.get("order") or ""), ln)
        if len(by_order) < 2:
            continue
        ordered = sorted(by_order.values(), key=lambda r: (str(r.get("date") or ""), str(r.get("order") or "")))
        first = ordered[0]
        panel = pmap.get(pid) or {}
        for ln in ordered[1:]:
            if ln.get("phone") and ln.get("phone") == first.get("phone"):
                continue                                  # نفس العميل يجدّد: ليس بيعًا مكرّرًا
            start = renew.parse_date(ln.get("date"))
            exp = renew.parse_date(ln.get("expiry")) or (
                renew.add_months(start, int(ln.get("months") or 0)) if start and ln.get("months") else None)
            left = (exp - today).days if exp else None
            rec = done.get(str(ln.get("order") or ""))
            rows.append({
                "username": str(ln.get("username") or ""), "password": str(ln.get("password") or ""),
                "host": str(ln.get("host") or ""), "panel_id": pid if pid in pmap else "",
                "panel_name": panel.get("name", ""), "account_id": panel.get("account_id", ""),
                "gate_id": panel.get("gate_id", ""), "order": str(ln.get("order") or ""),
                "date": str(ln.get("date") or ""), "customer": str(ln.get("customer") or ""),
                "phone": str(ln.get("phone") or ""), "product": str(ln.get("product") or ""),
                "months": int(ln.get("months") or 0), "expiry": exp.isoformat() if exp else "",
                "days_left": left, "remaining": remaining_text(exp.isoformat(), today) if exp else "",
                "expired": left is not None and left <= 0, "suggest": suggest_slice(left),
                "first_order": str(first.get("order") or ""), "first_date": str(first.get("date") or ""),
                "first_customer": str(first.get("customer") or ""),
                "first_phone": str(first.get("phone") or ""), "done": rec})
    rows.sort(key=lambda r: (bool(r["done"]), r["expired"], -(r["days_left"] or 0), r["order"]))
    return {"rows": rows, "total": len(rows),
            "pending": sum(1 for r in rows if not r["done"] and not r["expired"]),
            "done": sum(1 for r in rows if r["done"]),
            "expired": sum(1 for r in rows if r["expired"] and not r["done"]),
            "built": renew.now_iso()}

# ============================ المقارنة ============================
# الأصناف — كلٌّ صريحٌ ليُعرَض للمدير كما هو:
OK = "ok"
DURATION_MISMATCH = "duration_mismatch"     # اليوزر موجود لكن مدّته على اللوحة ≠ سلة
MISSING = "missing_on_panel"                # مباعٌ في سلة وغير موجود على اللوحة
WRONG_PANEL = "wrong_panel"                 # موجودٌ لكن على لوحةٍ غير التي يُشير هوستُه إليها
HOST_UNMAPPED = "host_unmapped"             # هوست الطلب غير مربوطٍ بأي لوحة


def compare(config, data_dir, days_override=None):
    """يطابق خطوط سلة المحفوظة بيوزرات اللوحات المحفوظة → صفوفٌ مصنّفة + ملخّص.

    لا شبكة هنا: يعمل على ما سُحب وحُفظ. فالسحب نافذةٌ تُجمع فيها البيانات، ثم
    المقارنة عليها متى شئنا وبلا انتظار."""
    cfg = renew.normalize_config(config)
    panels = {p["id"]: p for p in cfg["panels"]}
    hidx = host_index(cfg["panels"])
    pl = load_panel_lines(data_dir)["panels"]
    store = load_store_lines(data_dir)
    today = renew._today()
    renewal_days = days_override if days_override else cfg.get("renewal_days", 45)

    rows = []
    summary = {OK: 0, DURATION_MISMATCH: 0, MISSING: 0, WRONG_PANEL: 0,
               HOST_UNMAPPED: 0, "no_username": store.get("no_username", 0),
               "store_lines": len(store.get("lines", [])),
               "expired": 0, "expiring_soon": 0}

    for ln in store.get("lines", []):
        u = str(ln.get("username") or "").strip()
        if not u:
            continue
        nh = renew.norm_host(ln.get("host"))
        pid = hidx.get(nh, "")
        panel = panels.get(pid)
        s_months = int(ln.get("months") or 0)

        # أين وُجد اليوزر فعلًا (على أي لوحة)؟
        found_pid, found_rec = "", None
        own = panel_data_for(pl, panel) if panel else None
        if own:
            found_rec = own["by_user"].get(u.lower())
            if found_rec:
                found_pid = pid
        if not found_rec:                       # ابحث في بقيّة اللوحات
            for opid, pdata in pl.items():
                rec = pdata["by_user"].get(u.lower())
                if rec:
                    found_pid, found_rec = opid, rec
                    break

        row = {"username": u, "order": ln.get("order", ""), "date": ln.get("date", ""),
               "phone": ln.get("phone", ""),
               "host": ln.get("host", ""), "host_norm": nh, "product": ln.get("product", ""),
               "sku": ln.get("sku", ""), "store_months": s_months,
               "panel_id": pid, "panel_name": panel["name"] if panel else "",
               "found_panel_id": found_pid,
               "found_panel_name": (pl.get(found_pid, {}).get("name", "") if found_pid else ""),
               "panel_months": 0, "panel_exp": "", "panel_package": "",
               "days_left": None, "expired": False, "expiring_soon": False}

        if not pid:
            row["kind"] = HOST_UNMAPPED
        elif not found_rec:
            row["kind"] = MISSING
        else:
            row["panel_months"] = int(found_rec.get("months") or 0)
            row["panel_exp"] = found_rec.get("exp", "")
            row["panel_package"] = found_rec.get("package", "")
            es = expiry_status(found_rec.get("exp"), today, renewal_days)
            row.update({"days_left": es["days_left"], "expired": es["expired"],
                        "expiring_soon": es["expiring_soon"]})
            if es["expired"]:
                summary["expired"] += 1
            elif es["expiring_soon"]:
                summary["expiring_soon"] += 1
            if found_pid and pid and found_pid != pid:
                row["kind"] = WRONG_PANEL
            elif s_months and row["panel_months"] and s_months != row["panel_months"]:
                row["kind"] = DURATION_MISMATCH
                row["months_diff"] = row["panel_months"] - s_months
            else:
                row["kind"] = OK
        summary[row["kind"]] = summary.get(row["kind"], 0) + 1
        rows.append(row)

    # الأهمّ أولًا: الفروق ثم المفقود ثم اللوحة الخاطئة ثم الهوست غير المربوط ثم المطابق.
    order = {DURATION_MISMATCH: 0, MISSING: 1, WRONG_PANEL: 2, HOST_UNMAPPED: 3, OK: 4}
    rows.sort(key=lambda r: (order.get(r["kind"], 9), r["username"]))
    return {"rows": rows, "summary": summary, "built": renew.now_iso(),
            "renewal_days": renewal_days}


def renewal_list(config, data_dir, days_override=None):
    """العملاء المستحقّون للتجديد: خطٌّ وُجد على لوحته وانتهى أو قارب الانتهاء
    (خلال renewal_days)، ومعه جوال العميل ورقم طلبه — جاهزٌ لرسالة تجديد.

    الأعجل أولًا (الأقلّ أيامًا متبقّية)، والمنتهي قبل القريب."""
    res = compare(config, data_dir, days_override)
    due = [r for r in res["rows"] if r.get("days_left") is not None
           and (r["expired"] or r["expiring_soon"])]
    due.sort(key=lambda r: r["days_left"])
    return {"rows": due, "renewal_days": res["renewal_days"],
            "expired": res["summary"]["expired"],
            "expiring_soon": res["summary"]["expiring_soon"],
            "built": res["built"]}


# ============================ البحث برقم الطلب، والمفقود ============================
# مباعٌ في سلة ولا يوجد يوزره على أي لوحة (لا لوحته ولا البديلة) ولا استُبدل: العميل له
# اشتراكٌ مدفوع وخطٌّ ضائع. يُنشأ له خطٌّ من باقة ١٥ شهرًا بجزءٍ = ما تبقّى + تعويض، والباقي
# يعود إلى «حسابات متبقية» للبيع. ويُربط الطلب بيوزره يدويًا حين لم تحمله سلة أو حملت غيره.
COMP_DEFAULT = 1            # أشهر التعويض افتراضًا
BASE_MONTHS = 15            # الباقة التي يُجزَّأ منها الخط


def line_expiry(ln):
    """انتهاء خطٍّ من المتجر: المكتوب، وإلا تاريخ الشراء + المدة، وإلا None."""
    exp = renew.parse_date(ln.get("expiry"))
    if exp:
        return exp
    start = renew.parse_date(ln.get("date"))
    m = int(ln.get("months") or 0)
    return renew.add_months(start, m) if start and m else None


def comp_months(days_left, comp=COMP_DEFAULT):
    """أشهر الخط الجديد: المتبقي (أقرب شهر كامل) + التعويض، من شهرٍ إلى ١٥ (١٥ = الباقة كاملةً)."""
    left = suggest_slice(days_left)
    if not left:
        return 0
    return max(1, min(BASE_MONTHS, left + max(0, int(comp or 0))))


def _panel_users(pl, export=None):
    """{يوزر بحروف صغيرة: (اسم مصدره، نوعه)} من يوزرات اللوحات المسحوبة («panel»)، ثم من ملفات Excel البوابات
    المحفوظة في النظام («excel» — `export["users"]`: {يوزر: اسم البوابة}) — فما عُرف في أيٍّ منهما ليس مفقودًا."""
    out = {}
    for pid, pdata in pl.items():
        name = pdata.get("name") or pid
        for u in (pdata.get("by_user") or {}):
            out.setdefault(u, (name, "panel"))
    for u, name in ((export or {}).get("users") or {}).items():
        out.setdefault(str(u).lower(), (name, "excel"))
    return out


def _covered_orders(lines, users):
    """طلباتٌ وُجد أحد يوزراتها على لوحة: اشتراكها قائم، فيوزرٌ آخر فيها (قديمٌ أو مكرّرٌ في سجلّه) ليس مفقودًا."""
    return {renew.norm_order(ln.get("order")) for ln in lines
            if str(ln.get("username") or "").strip().lower() in users and ln.get("order")}


def _line_row(ln, ctx):
    """صفّ خطٍّ من المتجر بحاله: أين وُجد، وأمفقودٌ هو، وكم بقي له. `ctx` ما بُني مرةً للفهرس كله
    (خريطة الهوستات واللوحات واليوزرات …) — لا يُعاد بناؤه لكل خط."""
    u = str(ln.get("username") or "").strip()
    pid = ctx["hidx"].get(renew.norm_host(ln.get("host")), "")
    panel = ctx["pmap"].get(pid) or {}
    own = ctx["own"].get(pid) if panel else None
    found = ctx["users"].get(u.lower())
    exp = line_expiry(ln)
    today = ctx["today"]
    left = (exp - today).days if exp else None
    order = str(ln.get("order") or "")
    rec = ctx["done"].get(order)
    mine = rec if (rec or {}).get("src") == "lost" else None      # تعويضٌ أُنشئ من هذه الصفحة
    no = renew.norm_order(order)
    if not u:
        state = "no_user"
    elif found:
        state = "found"
    elif (u.lower() in ctx["replaced"] and not mine) or (rec and not mine):
        state = "replaced"                       # استُبدل من غير هذه الصفحة (بديل المكرر أو البحث)
    elif no in ctx["covered"] and not mine:
        state = "covered"                        # للطلب يوزرٌ آخر موجود: الاشتراك قائم
    elif not panel:
        state = "host_unmapped"
    elif not ((own and own.get("count"))
              or (str(panel.get("account_id", "")), str(panel.get("gate_id", ""))) in ctx["xgates"]):
        state = "not_pulled"                     # لوحته لم تُسحب: لا يُحكم بالفقد
    else:
        state = "missing"
    return {"order": order, "order_norm": no, "date": str(ln.get("date") or ""), "customer": str(ln.get("customer") or ""),
            "phone": str(ln.get("phone") or ""), "product": str(ln.get("product") or ""),
            "username": u, "password": str(ln.get("password") or ""), "host": str(ln.get("host") or ""),
            "months": int(ln.get("months") or 0), "expiry": exp.isoformat() if exp else "",
            "days_left": left, "remaining": remaining_text(exp.isoformat(), today) if exp else "",
            "expired": left is not None and left <= 0, "suggest": suggest_slice(left),
            "panel_id": pid if panel else "", "panel_name": panel.get("name", ""),
            "account_id": panel.get("account_id", ""), "gate_id": panel.get("gate_id", ""),
            "found_panel": found[0] if found else "", "found_src": found[1] if found else "",
            "state": state, "linked": str(ln.get("linked") or ""), "done": mine}


# ---- فهرس البحث: يُبنى مرةً عند تغيّر مصادره ويُخدم من الذاكرة ----
# البحث والمفقود كانا يقرآن كل الملفات (خطوط سلة، يوزرات اللوحات، ملفات Excel البوابات، فهرس الطلبات) ويحسبان
# حال كل خط مع كل طلب — والمفقود يبني خريطة الهوستات لكل خط (١٢ مليون norm_host لـ٤٠ ألف خط: ٢٠ ثانية).
# فالفهرس يُبنى مرةً ويُحفظ في الذاكرة بتوقيع مصادره (تاريخ تعديل كل ملفٍ وحجمه، وإعداد اللوحات، واليوم)؛ أي
# تغيّرٍ في مصدرٍ يغيّر التوقيع فيُعاد البناء عند أول طلب — فلا نتيجة من بياناتٍ قديمة. والقراءة بالقاموس.
import threading as _threading
_IDX = {}                    # data_dir → (التوقيع، الفهرس)
_IDX_LOCK = _threading.Lock()
_IDX_BUILDING = {}           # data_dir → وقت بدء بناءٍ جارٍ


def _file_sig(path):
    try:
        st = os.stat(path)
        return (path, st.st_mtime_ns, st.st_size)
    except OSError:
        return (path, 0, 0)


def index_sig(config, data_dir, extra=()):
    """توقيع مصادر الفهرس: ملفاتها (تاريخ التعديل والحجم)، وإعداد اللوحات، واليوم (المتبقي يتغيّر به)، و`extra`
    (ملفات Excel البوابات وروابط الاستبدال — يحسبها المستدعي لأنها خارج مجلد الإعداد)."""
    cfg = renew.normalize_config(config)
    files = [store_lines_path(data_dir), panel_lines_path(data_dir), dupes_path(data_dir), renew.index_path(data_dir)]
    return (tuple(_file_sig(f) for f in files), json.dumps(cfg["panels"], sort_keys=True, ensure_ascii=False),
            renew._today().isoformat(), tuple(extra))


def build_index(config, data_dir, replaced=None, export=None, today=None):
    """يبني فهرس البحث: كل خطٍّ من سلة (فريدٌ بالطلب واليوزر) بحاله، ومفاتيح البحث (الطلب · اليوزر · كلمة المرور)."""
    t0 = __import__("time").perf_counter()
    cfg = renew.normalize_config(config)
    pl = load_panel_lines(data_dir)["panels"]
    store = load_store_lines(data_dir)
    lines = store.get("lines", [])
    users = _panel_users(pl, export)
    pmap = {p["id"]: p for p in cfg["panels"]}
    ctx = {"pmap": pmap, "hidx": host_index(cfg["panels"]), "own": {pid: panel_data_for(pl, p) for pid, p in pmap.items()},
           "users": users, "done": load_dupes_done(data_dir), "replaced": {str(u).lower() for u in (replaced or ())},
           "covered": _covered_orders(lines, users), "today": today or renew._today(),
           "xgates": set((export or {}).get("gates") or ())}
    rows, seen = [], set()
    by_order, by_user, by_pass = {}, {}, {}
    for ln in lines:
        key = (renew.norm_order(ln.get("order")), str(ln.get("username") or "").strip().lower())
        if not key[1] or key in seen:
            continue
        seen.add(key)
        r = _line_row(ln, ctx)
        i = len(rows)
        rows.append(r)
        if r["order_norm"]:
            by_order.setdefault(r["order_norm"], []).append(i)
        by_user.setdefault(key[1], []).append(i)
        if len(r["password"]) >= 4:
            by_pass.setdefault(r["password"], []).append(i)
    counts = {"checked": len(rows)}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    ix = renew.load_index(data_dir)
    return {"rows": rows, "by_order": by_order, "by_user": by_user, "by_pass": by_pass, "counts": counts,
            "orders_index": ix.get("orders", {}), "orders_index_built": ix.get("built", ""),
            "store_built": store.get("built", ""), "no_username": store.get("no_username", 0),
            "panels": {p.get("name") or pid: {"count": p.get("count", 0), "built": p.get("built", "")} for pid, p in pl.items()},
            "excel_users": len((export or {}).get("users") or {}), "excel_gates": len(ctx["xgates"]),
            "built": renew.now_iso(), "build_ms": int((__import__("time").perf_counter() - t0) * 1000)}


def get_index(config, data_dir, sources=None, extra_sig=()):
    """الفهرس الجاهز إن لم تتغيّر مصادره، وإلا يُبنى (مرةً واحدة ولو طلبه أكثر من مستخدمٍ معًا).
    `sources()` ← (replaced، export): يُستدعى عند البناء وحده، فلا تُقرأ ملفات Excel مع كل بحث."""
    sig = index_sig(config, data_dir, extra_sig)
    hit = _IDX.get(data_dir)
    if hit and hit[0] == sig:
        return hit[1]
    with _IDX_LOCK:
        hit = _IDX.get(data_dir)
        if hit and hit[0] == sig:              # بناه طلبٌ آخر بينما ننتظر
            return hit[1]
        _IDX_BUILDING[data_dir] = renew.now_iso()
        try:
            replaced, export = sources() if sources else (None, None)
            idx = build_index(config, data_dir, replaced, export)
            _IDX[data_dir] = (sig, idx)
            return idx
        finally:
            _IDX_BUILDING.pop(data_dir, None)


def index_ready(config, data_dir, extra_sig=()):
    """أجاهزٌ الفهرس بمصادره الحالية؟ (بلا بناء) — ومتى بُني، وأيُبنى الآن."""
    hit = _IDX.get(data_dir)
    return {"ready": bool(hit and hit[0] == index_sig(config, data_dir, extra_sig)),
            "built": hit[1]["built"] if hit else "", "building": data_dir in _IDX_BUILDING}


def index_info(idx):
    """ما يُعرض عن المزامنة: متى بُني الفهرس وكم أخذ، ومن كل مصدرٍ كم ومتى."""
    return {"built": idx["built"], "build_ms": idx["build_ms"], "lines": idx["counts"].get("checked", 0),
            "store_built": idx["store_built"], "no_username": idx["no_username"], "panels": idx["panels"],
            "excel_users": idx["excel_users"], "excel_gates": idx["excel_gates"],
            "orders_index": len(idx["orders_index"]), "orders_index_built": idx["orders_index_built"]}


def lost(config, data_dir, replaced=None, comp=COMP_DEFAULT, include_expired=False, today=None, export=None, idx=None):
    """المفقود: خطوط المتجر التي لا يوجد يوزرها على أي لوحةٍ مسحوبة ولا في ملفات Excel ولم يُستبدل — جاريةً
    (والمنتهية اختيارًا). صفٌّ لكل (طلب، يوزر)، وما أُنشئ له تعويضه يبقى ظاهرًا بسجلّه. `idx` فهرسٌ جاهز (get_index)."""
    idx = idx or build_index(config, data_dir, replaced, export, today)
    counts = {"checked": 0, "found": 0, "covered": 0, "replaced": 0, "host_unmapped": 0, "not_pulled": 0, "expired": 0}
    rows = []
    for r in idx["rows"]:
        counts["checked"] += 1
        if r["state"] != "missing":
            counts[r["state"]] = counts.get(r["state"], 0) + 1
            continue
        if r["expired"] or r["days_left"] is None:
            counts["expired"] += 1
            if not include_expired or r["days_left"] is None:
                continue
        rows.append(dict(r, new_months=comp_months(r["days_left"], comp)))
    rows.sort(key=lambda r: (bool(r["done"]), r["expired"], -(r["days_left"] or 0), r["order"]))
    return {"rows": rows, "total": len(rows), "comp": int(comp or 0), "base": BASE_MONTHS,
            "pending": sum(1 for r in rows if not r["done"] and not r["expired"]),
            "done": sum(1 for r in rows if r["done"]), "counts": counts,
            "pulled": sum(1 for p in idx["panels"].values() if p.get("count")) + idx["excel_gates"],
            "export_users": idx["excel_users"], "index": index_info(idx), "built": idx["built"]}


_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def norm_query(q):
    """نص البحث بصيغةٍ واحدة: أرقامٌ عربية أو فارسية ← إنجليزية، وبلا مسافاتٍ ولا شرطاتٍ ولا نقاطٍ ولا # —
    ولا يُحذف صفرٌ ولا يُضاف رمز دولة: «٠٥٠ ١٢٣-٤» ← «0501234»."""
    return re.sub(r"[\s\-_.#/‎‏]+", "", str(q or "").translate(_AR_DIGITS)).strip()


def order_search(config, data_dir, q, replaced=None, today=None, export=None, idx=None):
    """بحثٌ برقم الطلب (أو اليوزر أو كلمة المرور) في الفهرس: تطابقٌ تامٌّ بعد توحيد الصيغة، وكل نتيجةٍ مرةً واحدة
    ولو طابقت بأكثر من مفتاح، ومعها ما طابقت به. ثم فهرس طلبات سلة لطلبٍ لا يوزر له. ← {rows, index, order}."""
    raw = str(q or "").strip()
    qn = norm_query(raw)
    if not qn:
        return {"rows": [], "index": None, "order": "", "q": ""}
    idx = idx or build_index(config, data_dir, replaced, export, today)
    qo, ql = renew.norm_order(qn) if qn.isdigit() else "", qn.lower()
    hits, why = [], {}
    for key, table, val in (("order", idx["by_order"], qo), ("username", idx["by_user"], ql),
                            ("username", idx["by_user"], raw.lower()), ("password", idx["by_pass"], qn),
                            ("password", idx["by_pass"], raw)):
        for i in (table.get(val) or []) if val else []:
            if i not in why:
                hits.append(i)
            why.setdefault(i, key)
    rows = [dict(idx["rows"][i], match=why[i]) for i in hits]
    order = rows[0]["order"] if rows and all(r["order"] == rows[0]["order"] for r in rows) else (qo if not rows else "")
    ix = idx["orders_index"].get(qo) if qo else None
    if ix:
        exp = line_expiry(ix)
        ix = {k: ix.get(k) for k in ("phone", "date", "months", "devices", "host", "username", "sid")
              if ix.get(k) not in (None, "")} | {"expiry": exp.isoformat() if exp else ""}
    return {"rows": rows, "index": ix, "order": order or (qo if ix else ""), "q": qn}


def link_order(data_dir, order, username, password="", host="", replace="", base=None):
    """يربط طلبًا بيوزره في اشتراكات المتجر: يُضاف الخط (الطلب، اليوزر) أو تُحدَّث كلمة مروره وهوسته،
    بمعلومات الطلب من خطٍّ له أو من `base` (فهرس الطلبات). و`replace` يوزرٌ مسجَّلٌ للطلب خطأً يُحذف خطّه.
    ← الخط المحفوظ. ValueError برسالةٍ للعرض."""
    order, username = renew.norm_order(order), str(username or "").strip()
    if not order or not username:
        raise ValueError("رقم الطلب واسم المستخدم مطلوبان")
    if re.search(r"\s", username):
        raise ValueError("اسم المستخدم بلا مسافات")
    d = load_store_lines(data_dir)
    lines = d.get("lines", [])
    mine = [ln for ln in lines if renew.norm_order(ln.get("order")) == order]
    src = (mine[0] if mine else None) or dict(base or {})
    if not src:
        raise ValueError("لا طلب بهذا الرقم في الاشتراكات المسحوبة — اسحب طلبات سلة أولًا")
    rep = str(replace or "").strip().lower()
    if rep and rep != username.lower():
        lines = [ln for ln in lines if not (renew.norm_order(ln.get("order")) == order
                                            and str(ln.get("username") or "").strip().lower() == rep)]
    cur = next((ln for ln in lines if renew.norm_order(ln.get("order")) == order
                and str(ln.get("username") or "").strip().lower() == username.lower()), None)
    if cur is None:
        cur = {k: src.get(k, "") for k in ("order", "date", "phone", "customer", "sid", "admin_url", "price",
                                           "status", "host", "months", "devices", "expiry", "product", "sku")}
        cur.update(order=str(src.get("order") or order), falcon=bool(src.get("falcon")),
                   months=int(src.get("months") or 0), devices=int(src.get("devices") or 1))
        if not cur.get("expiry"):
            exp = line_expiry(src)
            cur["expiry"] = exp.isoformat() if exp else ""
        lines.append(cur)
    cur["username"] = username
    if password:
        cur["password"] = str(password).strip()
    if host:
        cur["host"] = str(host).strip()
    cur["linked"] = renew.now_iso()
    d["lines"], d["count"] = lines, len(lines)
    renew._write_json(store_lines_path(data_dir), d)
    return cur

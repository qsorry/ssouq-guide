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
    if not d:
        return {"exp_date": "", "days_left": None, "expired": False, "expiring_soon": False}
    left = (d - today).days
    return {"exp_date": d.isoformat(), "days_left": left,
            "expired": left < 0, "expiring_soon": 0 <= left <= renewal_days}


# ============================ تخزين يوزرات اللوحات ============================
def panel_lines_path(data_dir):
    return os.path.join(data_dir, "renew_panel_lines.json")


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
               "phone": u.get("phone", ""),
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
        if pid and pid in pl:
            found_rec = pl[pid]["by_user"].get(u.lower())
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

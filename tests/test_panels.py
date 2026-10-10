#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبار مقارنة اللوحات: موصّل كاسبر (مقابل لوحة وهمية، بلا إنترنت)، ومنطق
المطابقة سلة↔اللوحات، وتصدير Excel.

تشغيل:  python tests/test_panels.py
"""
import os
import sys
import zipfile
import tempfile
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import xm_web          # noqa: E402
import panels          # noqa: E402
import renew           # noqa: E402
import xlsx_write      # noqa: E402
import mock_casper     # noqa: E402

_p = _f = 0


def check(label, cond, extra=""):
    global _p, _f
    if cond:
        _p += 1
        print(f"  \033[32mPASS\033[0m  {label}" + (f"  ({extra})" if extra else ""))
    else:
        _f += 1
        print(f"  \033[31mFAIL\033[0m  {label}" + (f"  ({extra})" if extra else ""))


def test_months():
    print("== مدّة الباقة من نصّها ==")
    cases = {"15 Months": 15, "1 Year": 12, "2 Years": 24, "6 Months": 6,
             "30 Days": 0, "سنة": 12, "سنتين": 24, "1 Year 3 Months": 15, "": 0}
    for txt, want in cases.items():
        check(f"«{txt}» → {want}", panels.parse_panel_months(txt) == want,
              str(panels.parse_panel_months(txt)))


def test_host():
    print("== توحيد الهوست ==")
    check("بروتوكول ومنفذ ومسار يُقتطعون",
          renew.norm_host("https://Sub.Kasper.tv:8080/get.php") == "sub.kasper.tv")
    check("www يُقتطع", renew.norm_host("www.kasper.tv") == "kasper.tv")
    check("فارغ", renew.norm_host("") == "")


def test_normalize_panels():
    print("== تنظيف اللوحات ==")
    got = renew.normalize_panels([
        {"name": "كاسبر", "hosts": ["A.tv", "a.tv", "https://b.tv:80/x"]},
        {"name": "", "hosts": ["c.tv"]},          # بلا اسم → يُطرح
    ])
    check("لوحة بلا اسم تُطرح", len(got) == 1, str(len(got)))
    check("الهوستات تُوحّد وتُنقّى من التكرار",
          got[0]["hosts"] == ["a.tv", "b.tv"], str(got[0]["hosts"]))
    check("لكلٍّ معرّف", bool(got[0]["id"]))


def test_casper_connector():
    print("== موصّل كاسبر مقابل لوحة وهمية ==")
    srv, base, _t = mock_casper.start(user_count=120)
    d = tempfile.mkdtemp(prefix="casper_")
    try:
        s = xm_web.CasperWebSession(
            {"id": "m", "user": "x", "password": "y", "panel_base": base}, d)
        check("السياق يُشتقّ من panel_base", s.ctx == "/iptv", s.ctx)
        check("تسجيل الدخول ينجح", s.login() is True)
        check("الجلسة مُصادَقة", s.is_authenticated() is True)
        rows = s.all_users()
        check("سُحب كل اليوزرات (120)", len(rows) == 120, str(len(rows)))
        uset = {r["username"] for r in rows}
        check("اليوزرات فريدة لا اسم الموزّع", len(uset) == 120 and "reseller1" not in uset,
              str(len(uset)))
        r0 = rows[0]
        check("العمود الصحيح: username=u00000 لا reseller",
              r0["username"] == "u00000", r0["username"])
        check("كلمة المرور من عمودها", r0["password"] == "p00000", r0["password"])
        check("الباقة والانتهاء يُقرآن",
              r0["package"] == "15 Months" and r0["exp"].startswith("2027-04-01"),
              f'{r0["package"]} / {r0["exp"]}')
        # بحثٌ لا يُخطئ النفي
        found = s.search("u00007")
        check("البحث يجد يوزرًا موجودًا", len(found) == 1 and found[0]["username"] == "u00007")
        check("البحث ينفي غير الموجود", s.search("nope999") == [])
    finally:
        srv.shutdown()
        shutil.rmtree(d, ignore_errors=True)


def test_pull_flavors():
    print("== سحب اللوحات: كاسبر واكتشافه التلقائي ==")
    import xm_lines
    srv, base, _t = mock_casper.start(user_count=120)
    xm_lines.DATA_DIR = tempfile.mkdtemp(prefix="pull_")
    try:
        g_casper = {"id": "c1", "mode": "web", "web_flavor": "casper",
                    "panel_base": base, "panel_user": "x", "panel_pass": "y", "host": base}
        check("بوابة كاسبر تسحب كل اليوزرات", len(xm_lines._all_web_lines(g_casper)) == 120)
        # نفس لوحة كاسبر لكن مضبوطة Xtream خطأً → اكتشافٌ تلقائي لا صفر
        g_wrong = {**g_casper, "id": "c2", "web_flavor": "xtream"}
        rows = xm_lines._all_web_lines(g_wrong)
        check("كاسبر مضبوطة Xtream خطأً → تُكتشف تلقائيًا لا تُرجع صفرًا",
              len(rows) == 120, str(len(rows)))
        check("اليوزر من العمود الصحيح", rows[0]["username"].startswith("u"), rows[0]["username"])
    finally:
        srv.shutdown()


def test_compare():
    print("== المطابقة سلة ↔ اللوحات ==")
    d = tempfile.mkdtemp(prefix="cmp_")
    try:
        panels.save_panel_lines(d, "pk", "كاسبر", [
            {"username": "1111", "password": "a", "package": "12 Months",
             "created": "2026-01-01", "exp": "2027-01-01"},
            {"username": "2222", "password": "b", "package": "15 Months",
             "created": "2026-01-01", "exp": "2027-04-01"},
        ])
        panels.save_store_lines(d, [
            {"order": "1", "date": "2026-01-01", "host": "http://sub.kasper.tv:8080",
             "username": "1111", "months": 15, "expiry": "2027-04-01"},   # فرق: 15≠12
            {"order": "2", "date": "2026-01-01", "host": "kasper.tv",
             "username": "2222", "months": 15},                           # مطابق
            {"order": "3", "date": "2026-01-01", "host": "kasper.tv",
             "username": "9999", "months": 12},                           # مفقود
            {"order": "4", "date": "2026-01-01", "host": "other.com",
             "username": "1111", "months": 12},                           # هوست غير مربوط
            {"order": "5", "date": "2026-01-01", "host": "kasper.tv",
             "username": "", "months": 12},                               # بلا يوزر
        ])
        cfg = {"panels": [{"id": "pk", "name": "كاسبر", "account_id": "a",
                           "gate_id": "g", "hosts": ["sub.kasper.tv", "kasper.tv"]}]}
        res = panels.compare(cfg, d)
        s = res["summary"]
        check("فرق مدّة واحد (سلة 15 · اللوحة 12)", s[panels.DURATION_MISMATCH] == 1, str(s))
        check("مفقود واحد", s[panels.MISSING] == 1)
        check("مطابق واحد", s[panels.OK] == 1)
        check("هوست غير مربوط واحد", s[panels.HOST_UNMAPPED] == 1)
        check("بلا يوزر واحد", s["no_username"] == 1)
        mm = next(r for r in res["rows"] if r["kind"] == panels.DURATION_MISMATCH)
        check("صفّ الفرق يحمل الرقمين والفرق",
              mm["store_months"] == 15 and mm["panel_months"] == 12 and mm["months_diff"] == -3,
              f'{mm["store_months"]}/{mm["panel_months"]}/{mm.get("months_diff")}')
        check("الأهمّ أولًا: أول صفٍّ فرق مدّة", res["rows"][0]["kind"] == panels.DURATION_MISMATCH)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_renewal():
    print("== المنتهي والقريب من الانتهاء والتجديد ==")
    import datetime
    d = tempfile.mkdtemp(prefix="ren_")
    today = renew._today()
    def iso(days): return (today + datetime.timedelta(days=days)).isoformat()
    try:
        panels.save_panel_lines(d, "pk", "كاسبر", [
            {"username": "exp1", "package": "12 Months", "created": iso(-400), "exp": iso(-5)},   # منتهٍ
            {"username": "soon1", "package": "12 Months", "created": iso(-350), "exp": iso(20)},   # قريب (خلال 45)
            {"username": "far1", "package": "12 Months", "created": iso(-10), "exp": iso(300)},     # بعيد
        ])
        panels.save_store_lines(d, [
            {"order": "1", "phone": "966500000001", "host": "kasper.tv", "username": "exp1", "months": 12},
            {"order": "2", "phone": "966500000002", "host": "kasper.tv", "username": "soon1", "months": 12},
            {"order": "3", "phone": "966500000003", "host": "kasper.tv", "username": "far1", "months": 12},
        ])
        cfg = {"renewal_days": 45, "panels": [{"id": "pk", "name": "كاسبر",
               "account_id": "a", "gate_id": "g", "hosts": ["kasper.tv"]}]}
        res = panels.compare(cfg, d)
        check("منتهٍ واحد", res["summary"]["expired"] == 1, str(res["summary"]))
        check("قريب الانتهاء واحد", res["summary"]["expiring_soon"] == 1)
        rl = panels.renewal_list(cfg, d)
        users = [r["username"] for r in rl["rows"]]
        check("قائمة التجديد فيها المنتهي والقريب فقط",
              set(users) == {"exp1", "soon1"}, str(users))
        check("الأعجل أولًا (المنتهي قبل القريب)", users[0] == "exp1", str(users))
        check("الجوال محمول في الصف", rl["rows"][0].get("phone") == "966500000001")
        # نطاق أضيق: 10 أيام → القريب (20 يومًا) يخرج
        rl2 = panels.renewal_list(cfg, d, days_override=10)
        check("days_override يضيّق القريب", [r["username"] for r in rl2["rows"]] == ["exp1"],
              str([r["username"] for r in rl2["rows"]]))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_xlsx():
    print("== تصدير Excel ==")
    data = xlsx_write.build_xlsx([
        ("ورقة عربية", ["يوزر", "المدة", "ملاحظة"],
         [["u1", 15, "نصّ عربي"], ["u2", 12, ""], ["u3", 6, "a & b < c"]]),
        ("Sheet2", ["x"], [[1]]),
    ])
    check("بايتات غير فارغة", len(data) > 500, str(len(data)))
    p = tempfile.mktemp(suffix=".xlsx")
    try:
        open(p, "wb").write(data)
        z = zipfile.ZipFile(p)
        check("حزمة zip سليمة", z.testzip() is None)
        names = z.namelist()
        check("فيها ورقتان", "xl/worksheets/sheet1.xml" in names
              and "xl/worksheets/sheet2.xml" in names, str(len(names)))
        s1 = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
        check("النصّ العربي محفوظ", "نصّ عربي" in s1)
        check("الرمز & مُهرَّب لا خام", "a &amp; b &lt; c" in s1)
        check("الرقم خليّة رقمية", "<v>15</v>" in s1)
    finally:
        try:
            os.remove(p)
        except OSError:
            pass


def test_unlisted():
    print("== لم تُعرض للبيع: يوزرات اللوحة − المبيع في سلة − مخزون أكواد سلة ==")
    d = tempfile.mkdtemp(prefix="unl_")
    try:
        today_d = renew._today()
        today = today_d.isoformat()
        far = renew.add_months(today_d, 10).isoformat()
        panels.save_panel_lines(d, "pk", "كاسبر", [
            {"username": "111111111111", "password": "1000000001", "package": "15 Months", "exp": far},     # مبيع في سلة
            {"username": "222222222222", "password": "1000000002", "package": "15 Months", "exp": far},     # معروض في مخزون سلة
            {"username": "333333333333", "password": "1000000003", "package": "15 Months", "exp": far},     # لم يُعرض ← المطلوب
            {"username": "444444444444", "password": "1000000004", "package": "15 Months", "exp": "2020-01-01"},  # منتهٍ
        ])
        panels.save_store_lines(d, [{"order": "1", "date": today, "host": "kasper.tv", "username": "111111111111", "months": 15}])
        st = panels.save_salla_codes(d, [{"id": "p1", "name": "اشتراك كاسبر 12 شهر", "type": "codes",
                                          "codes": [{"code": "Host http://kasper.tv:80 | Username 222222222222 | Password 1000000002", "status": "available"},
                                                    {"code": "****-masked", "status": "available"}]}], reset=True)
        check("salla codes saved with parsed usernames and masked count", st["products"] == 1 and st["with_username"] == 1 and st["unparsed"] == 1, str(st))
        cfg = {"panels": [{"id": "pk", "name": "كاسبر", "account_id": "a", "gate_id": "g", "hosts": ["kasper.tv"]}]}
        res = panels.unlisted(cfg, d)
        users = [r["username"] for r in res["rows"]]
        check("only the never-listed, unexpired line is reported", users == ["333333333333"], str(users))
        r = res["rows"][0]
        check("row carries a ready-to-copy line with host/user/pass/exp",
              r["line"] == "Host http://kasper.tv Username 333333333333 Password 1000000003 Exp " + far and r["months_left"] >= 9, r["line"])
        pp = res["panels"]["pk"]
        check("per-panel counts: sold/listed/unlisted/expired", (pp["sold"], pp["listed"], pp["unlisted"], pp["expired"]) == (1, 1, 1, 1), str(pp))
        res2 = panels.unlisted(cfg, d, include_expired=True)
        check("include_expired adds the expired line", sorted(r["username"] for r in res2["rows"]) == ["333333333333", "444444444444"])
        # إضافة منتجٍ آخر دون reset تُبقي الأوّل
        st2 = panels.save_salla_codes(d, [{"id": "p2", "name": "سمارت", "codes": ["Host http://m.ink Username 555555555555 Password 1000000005"]}])
        check("append keeps earlier products", st2["products"] == 2 and st2["with_username"] == 2, str(st2))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_split_bulk():
    print("== تجزئة جماعية من سطور ملصوقة ==")
    import xm_lines as X
    import split_subs
    d = tempfile.mkdtemp(prefix="blk_")
    try:
        a = {"id": "acc1", "name": "حساب"}
        gate = {"id": "g1", "name": "مرح", "mode": "web", "host": "http://m.ink"}
        exp = renew.add_months(renew._today(), 14).isoformat()
        text = "Host http://m.ink Username 123456789012 Password 987654321 Exp %s\n\nلا شيء هنا\nUsername 222333444555 Password x" % exp
        out = X.split_register_bulk(a, gate, 6, text, d)
        check("two lines registered, one rejected", len(out["registered"]) == 2 and len(out["errors"]) == 1, str(out)[:200])
        db = split_subs.load(d, "acc1")
        rec = next(r for r in db["lines"].values() if r["username"] == "123456789012")
        check("expiry from the line, slice of 6 months, base 15", rec["expiry"] == exp and rec["slice"]["months"] == 6 and rec["base_months"] == 15, str(rec["slice"]))
        out2 = X.split_register_bulk(a, gate, 6, text, d)
        check("re-posting the same lines reports them as existing", len(out2["existing"]) == 2 and not out2["registered"], str(out2)[:120])
        check("a bad slice is refused", X.split_register_bulk(a, gate, 15, text, d)["ok"] is False)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main():
    test_months()
    test_host()
    test_normalize_panels()
    test_casper_connector()
    test_pull_flavors()
    test_compare()
    test_renewal()
    test_xlsx()
    test_unlisted()
    test_split_bulk()
    print("\n----------------------------------------")
    print(f"Result: \033[32m{_p} passed\033[0m, "
          + (f"\033[31m{_f} failed\033[0m" if _f else "0 failed"))
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

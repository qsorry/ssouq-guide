#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبار مقارنة اللوحات: موصّل كاسبر (مقابل لوحة وهمية، بلا إنترنت)، ومنطق
المطابقة سلة↔اللوحات، وتصدير Excel.

تشغيل:  python tests/test_panels.py
"""
import datetime
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
        check("row carries a Salla card line (User/Pass/Guide by panel name)",
              r["card"] == "Host http://kasper.tv:80 User 333333333333 Pass 1000000003 Guide https://guide.ssouq.com/#activate/casper", r["card"])
        hg, gg = panels.panel_card({"name": "x", "hosts": ["kasper.tv"]}, {"host": "http://ssouqhost.vip:80", "guide_url": "https://guide.ssouq.com/#activate/casper"})
        check("panel_card takes host and guide from the pull gate first", (hg, gg) == ("http://ssouqhost.vip:80", "https://guide.ssouq.com/#activate/casper"), str((hg, gg)))
        h2, g2 = panels.panel_card({"name": "مرح", "hosts": ["mrha.ink"], "card_host": "http://mrha.ink:80", "guide_url": ""})
        check("panel_card honours card_host and derives the guide from the name", (h2, g2) == ("http://mrha.ink:80", "https://guide.ssouq.com/#activate/smart"), str((h2, g2)))
        check("row carries a ready-to-copy line with host/user/pass/exp",
              r["line"] == "Host http://kasper.tv:80 Username 333333333333 Password 1000000003 Exp " + far and r["months_left"] >= 9, r["line"])
        pp = res["panels"]["pk"]
        check("per-panel counts: sold/listed/unlisted/expired", (pp["sold"], pp["listed"], pp["unlisted"], pp["expired"]) == (1, 1, 1, 1), str(pp))
        # حفظٌ قديم غيّر معرّف اللوحة: تُربط بأحدث سحبٍ يحمل اسمها
        cfg_renamed = {"panels": [{**cfg["panels"][0], "id": "new-id"}]}
        resr = panels.unlisted(cfg_renamed, d)
        check("panel lines are found by name when the id changed", resr["panels"]["new-id"]["lines"] == 4 and [r["username"] for r in resr["rows"]] == ["333333333333"], str(resr["panels"]))
        cfg2 = {"panels": cfg["panels"] + [{"id": "pm", "name": "مرح", "account_id": "a", "gate_id": "g2", "hosts": ["m.ink"]}]}
        resm = panels.unlisted(cfg2, d)
        check("a panel without pulled lines is reported as not_pulled", resm["panels"]["pm"].get("not_pulled") is True and resm["panels"]["pm"]["lines"] == 0)
        rows_c = panels.salla_codes_rows(panels.load_salla_codes(d))
        check("codes rows list every code with readability", len(rows_c) == 2 and [r["readable"] for r in rows_c] == [True, False], str(rows_c)[:120])
        n = panels.mark_listed(d, ["333333333333"], note="عُرض في سلة")
        resl = panels.unlisted(cfg, d)
        check("a manually marked user counts as listed", n == 1 and resl["rows"] == [] and resl["panels"]["pk"]["listed"] == 2 and resl["manual_listed"] == 1, str(resl["panels"]["pk"]))
        panels.mark_listed(d, ["333333333333"], remove=True)
        check("unmarking brings it back", [r["username"] for r in panels.unlisted(cfg, d)["rows"]] == ["333333333333"])
        # مبيع مكرر: الأقدم يحتفظ باليوزر، واللاحق (جوال مختلف) صفٌّ بمتبقّيه، ونفس الجوال تجديد
        dd = tempfile.mkdtemp()
        today = renew._today()
        def _ln(order, days_ago, phone, months=12):
            st = today - datetime.timedelta(days=days_ago)
            return {"order": order, "date": st.isoformat(), "phone": phone, "customer": "c" + phone,
                    "username": "999000111222", "password": "pw", "host": "http://m.ink", "months": months,
                    "expiry": renew.add_months(st, months).isoformat()}
        panels.save_store_lines(dd, [_ln("1", 40, "111"), _ln("2", 10, "222"), _ln("3", 5, "111")])
        dupr = panels.duplicates({"panels": [{"id": "pk", "name": "P", "hosts": ["http://m.ink"], "account_id": "a", "gate_id": "g"}]}, dd)
        check("duplicates: later order of another customer is a row, same phone is not",
              dupr["total"] == 1 and dupr["rows"][0]["order"] == "2" and dupr["rows"][0]["first_order"] == "1"
              and dupr["rows"][0]["account_id"] == "a" and dupr["rows"][0]["suggest"] in (11, 12), str(dupr["rows"]))
        panels.mark_dupe_done(dd, "2", "new1", 11)
        check("duplicates: done order is flagged", panels.duplicates({"panels": []}, dd)["rows"][0]["done"]["new"] == "new1")
        check("suggest_slice rounds and clamps", panels.suggest_slice(353) == 12 and panels.suggest_slice(5) == 1
              and panels.suggest_slice(900) == 15 and panels.suggest_slice(0) == 0 and panels.suggest_slice(None) == 0)
        resr = panels.unlisted(cfg, d, replaced={("a", "g"): {"333333333333"}})
        check("a replacement delivered to a customer is not unlisted", resr["rows"] == [] and resr["panels"]["pk"]["replaced"] == 1, str(resr["panels"]["pk"]))
        whyr = panels.explain_user(cfg, d, "333333333333", replaced={("a", "g"): {"333333333333"}})
        check("explain_user: replacement reason", "بديل" in whyr["reason"], whyr["reason"])
        ress = panels.unlisted(cfg, d, split={("a", "g"): {"333333333333": 6}})
        check("a line registered for splitting stays listed, flagged", len(ress["rows"]) == 1 and ress["rows"][0]["split"] is True and ress["rows"][0]["split_months"] == 6
              and ress["panels"]["pk"]["split"] == 1, str(ress["panels"]["pk"]))
        res2 = panels.unlisted(cfg, d, include_expired=True)
        check("include_expired adds the expired line", sorted(r["username"] for r in res2["rows"]) == ["333333333333", "444444444444"])
        # إضافة منتجٍ آخر دون reset تُبقي الأوّل
        st2 = panels.save_salla_codes(d, [{"id": "p2", "name": "سمارت", "codes": ["Host http://m.ink Username 555555555555 Password 1000000005"]}])
        check("append keeps earlier products", st2["products"] == 2 and st2["with_username"] == 2, str(st2))
    finally:
        shutil.rmtree(d, ignore_errors=True)
        ex = panels.expiry_status("Expired", renew._today(), 0)
        check("expiry_status: «Expired» text counts as expired", ex["expired"] and ex["days_left"] == 0, ex)
        why = panels.explain_user(cfg_u if 'cfg_u' in dir() else {}, d, "nobody_here")
        check("explain_user: unknown user has a reason", bool(why["reason"]) and not why["panels"], why)
        st_html = panels.save_salla_codes(d, [{"id": "p3", "name": "كاسبر 30", "html":
            '<div id="codes_list"><textarea name="code_content[]">Host http://mrha.ink:80 User 808808243040 Pass 370378628604 Guide g</textarea>'
            '<textarea name="code_content[]">Host http://mrha.ink:80 User 568483197191 Pass 375343915287</textarea></div>'
            '<div class="clone_code hidden"><textarea name="code_content[]"></textarea></div>'}])
        p3 = [p for p in panels.load_salla_codes(d)["products"] if p["id"] == "p3"][0]
        check("salla_codes: html من اللوحة القديمة يُحلَّل", len(p3["codes"]) == 2 and p3["source"] == "legacy"
              and p3["codes"][0]["username"] == "808808243040" and p3["unparsed"] == 0, p3)


def test_remaining_text():
    print("== «ينتهي بعد سنة و٢ شهر و٢٥ يومًا» ==")
    import datetime
    t = datetime.date(2026, 10, 11)
    check("1y 1m 24d", panels.remaining_text("2027-12-05", t) == "ينتهي بعد سنة وشهر و24 يومًا", panels.remaining_text("2027-12-05", t))
    check("1y 2m 25d", panels.remaining_text("2028-01-05", t) == "ينتهي بعد سنة وشهران و25 يومًا", panels.remaining_text("2028-01-05", t))
    check("exact months", panels.remaining_text("2027-04-11", t) == "ينتهي بعد 6 أشهر", panels.remaining_text("2027-04-11", t))
    check("days only", panels.remaining_text("2026-10-16", t) == "ينتهي بعد 5 أيام", panels.remaining_text("2026-10-16", t))
    check("past", panels.remaining_text("2026-09-01", t).startswith("انتهى منذ"), panels.remaining_text("2026-09-01", t))
    check("unknown date", panels.remaining_text("", t) == "")


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


def test_dup_create():
    print("== مبيع مكرر: بديل للاحق + تغيير القديم + رسائل ==")
    import datetime
    import xm_lines as X
    d = tempfile.mkdtemp(prefix="dup_")
    keep = {k: getattr(X, k) for k in ("DATA_DIR", "find_gate", "with_guide", "get_packages", "create_lines",
                                       "split_find_line", "split_change", "split_register_created", "rand_digits")}
    try:
        today = renew._today()
        def ln(order, days_ago, phone, name):
            st = today - datetime.timedelta(days=days_ago)
            return {"order": order, "date": st.isoformat(), "phone": phone, "customer": name, "username": "999000111222",
                    "password": "oldpw", "host": "http://m.ink", "months": 12, "expiry": renew.add_months(st, 12).isoformat()}
        panels.save_store_lines(d, [ln("1", 40, "966500000001", "الأول"), ln("2", 10, "0500000002", "الثاني")])
        cfg = {"panels": [{"id": "pk", "name": "P", "hosts": ["http://m.ink"], "account_id": "acc1", "gate_id": "g1"}]}
        gate = {"id": "g1", "name": "مرح", "mode": "web", "host": "http://m.ink"}
        acct = {"id": "acc1", "split": True, "gates": [gate]}
        calls = {}
        X.DATA_DIR = d
        X.find_gate = lambda a, gid: gate
        X.with_guide = lambda a, g: g
        X.get_packages = lambda g: [{"id": "p15", "name": "اشتراك 15 شهر"}]
        X.create_lines = lambda g, pkg, n, *a, **k: ([{"line": "Host http://m.ink User 555 Pass 666", "username": "555", "password": "666"}], None)
        X.split_find_line = lambda g, u: {"password": "oldpw", "line_id": "7"}
        X.split_change = lambda g, rec, pend: calls.setdefault("rename", (rec["username"], pend["username"]))
        X.split_register_created = lambda *a, **k: [{"username": "555"}]
        X.rand_digits = lambda n=12: "777888999000"
        code, body = X.dup_create([acct], cfg, d, {"order": "2", "username": "999000111222", "months": 11, "rename_old": True})
        check("dup_create ok with a renamed old user", code == 200 and body["ok"] and body["renamed"]["to"] == "777888999000", str(body)[:200])
        check("old user renamed on the panel", calls.get("rename") == ("999000111222", "777888999000"), str(calls))
        kinds = [m["kind"] for m in body["messages"]]
        check("two messages: new to the later buyer, old to the first buyer", kinds == ["new", "old"]
              and body["messages"][0]["phone"] == "966500000002" and body["messages"][1]["phone"] == "966500000001"
              and "User 777888999000 Pass oldpw" in body["messages"][1]["text"], str(body["messages"]))
        check("done is recorded with the messages", panels.duplicates(cfg, d)["rows"][0]["done"]["msgs"][1]["kind"] == "old")
        check("messages listed for sending", len(panels.dupe_messages(d)) == 2)
        # القناة: رقم المسابقة المتصل أولًا
        sent = {}
        keep_rs, keep_rsend = X.reader_status, X.reader_send
        X.reader_status = lambda *a, **k: {"status": "connected"}
        X.reader_send = lambda to, text: sent.setdefault("x", (to, text)) and {"ok": True}
        r_, how_ = X.dup_wa_send({"service": {}}, "966500000002", "hi")
        check("dup_wa_send prefers the connected contest number", how_ == "contest" and r_["ok"] and sent["x"] == ("966500000002", "hi") and X.dup_wa_ready({"service": {}}))
        X.reader_status = lambda *a, **k: {"status": "disconnected"}
        check("no channel when contest is down and service wa is off", not X.dup_wa_ready({"service": {"wa": {"type": "none"}}}))
        X.reader_status, X.reader_send = keep_rs, keep_rsend
        panels.log_dup_send(d, {"order": "2", "kind": "new", "name": "n", "phone": "9665", "text": "t"}, "contest", False, "boom")
        panels.log_dup_send(d, {"order": "2", "kind": "new", "name": "n", "phone": "9665", "text": "t2"}, "contest", True)
        lg = panels.load_dup_log(d)
        check("send log is append-only, newest first, failures kept", len(lg) == 2 and lg[0]["ok"] and not lg[1]["ok"] and lg[1]["error"] == "boom", str(lg))
        code2, body2 = X.dup_create([acct], cfg, d, {"order": "2", "username": "999000111222"})
        check("a second create for the same order is refused", code2 == 400, str(body2))
        check("old-owner message uses the security wording", "لوجود خطر على الحساب" in body["messages"][1]["text"])
        # قديمٌ لم يُغيَّر (فشل) ثم يُعاد بالزر
        panels.update_dupe(d, "2", {"renamed": None, "rename_error": "x"})
        panels.load_dupes_done(d)["2"]["msgs"].pop()
        calls.pop("rename", None)
        code3, body3 = X.dup_rename([acct], cfg, d, {"order": "2", "username": "999000111222"})
        check("dup_rename renames the old user and adds the message", code3 == 200 and calls.get("rename")
              and body3["renamed"]["to"] == "777888999000", str(body3))
        code4, _ = X.dup_rename([acct], cfg, d, {"order": "2", "username": "999000111222"})
        check("dup_rename twice is refused", code4 == 400)
        # القديم في لوحة أرشيف بنفس الهوست (بوابة أخرى): يُبحث فيها ويُغيَّر هناك
        g2 = {"id": "g2", "name": "مرح أرشيف", "mode": "web", "host": "http://m.ink"}
        acct2 = {"id": "acc2", "gates": [g2]}
        X.split_find_line = lambda g, u: ({"password": "oldpw", "line_id": "9"} if g["id"] == "g2" else {})
        calls2 = []
        X.split_change = lambda g, rec, pend: calls2.append((g["id"], rec["username"]))
        info, err = X._dup_rename_old(acct, gate, {"username": "999000111222", "password": "x", "host": "http://m.ink"}, [acct, acct2], cfg)
        check("old user found on the archive panel sharing the host", info and info["panel"] == "مرح أرشيف" and calls2 == [("g2", "999000111222")], str((info, err, calls2)))
        X.split_find_line = lambda g, u: {}
        info, err = X._dup_rename_old(acct, gate, {"username": "u", "password": "x", "host": "http://m.ink"}, [acct, acct2], cfg)
        check("missing everywhere = old_missing", info is None and err == X.OLD_MISSING)
        g3 = {"id": "g3", "name": "أرشيف آخر", "mode": "web", "host": "http://old.ink"}
        X.split_find_line = lambda g, u: ({"password": "pw", "line_id": "4"} if g["id"] == "g3" else {})
        calls2.clear()
        info, err = X._dup_rename_old(acct, gate, {"username": "u", "password": "x", "host": "http://m.ink"}, [acct, acct2, {"id": "acc3", "gates": [g3]}], cfg)
        check("falls back to gates on other hosts", info and info["panel"] == "أرشيف آخر" and calls2 == [("g3", "u")], str((info, err)))
        ga = {"id": "ga", "name": "مرح أرشيف", "mode": "web", "host": "http://m.ink", "archive_only": True}
        X.split_find_line = lambda g, u: {}
        arch = X._dup_archived([acct, {"id": "acc4", "gates": [ga]}], cfg, acct, gate, {"host": "http://m.ink"})
        check("archive-only gates are listed for connecting, not searched", len(arch) == 1 and arch[0]["gate_id"] == "ga" and arch[0]["web"])
        X.split_find_line = lambda g, u: (_ for _ in ()).throw(AssertionError("archive searched")) if g["id"] == "ga" else {}
        info, err = X._dup_rename_old(acct, gate, {"username": "u", "password": "x", "host": "http://m.ink"}, [acct, {"id": "acc4", "gates": [ga]}], cfg)
        check("archive gate is skipped in the search", info is None and err == X.OLD_MISSING)
        def boom(g, u): raise RuntimeError("login failed")
        X.split_find_line = boom
        info, err = X._dup_rename_old(acct, gate, {"username": "u", "password": "x", "host": "http://m.ink"}, [acct, acct2], cfg)
        check("connection errors are reported, not called missing", info is None and "login failed" in err and err != X.OLD_MISSING, err)
        panels.set_dupe_msg(d, "2", 0, sent={"ok": True, "how": "manual"})
        check("message can be marked sent", panels.dupe_messages(d)[0]["sent"] or panels.dupe_messages(d)[1]["sent"])
    finally:
        for k, v in keep.items():
            setattr(X, k, v)
        shutil.rmtree(d, ignore_errors=True)


def test_host_audience():
    print("== رسالة لمشتركي هوست ==")
    import datetime
    import xm_lines as X
    d = tempfile.mkdtemp(prefix="hs_")
    keep = X.DATA_DIR
    try:
        today = renew._today()
        fut = (today + datetime.timedelta(days=30)).isoformat()
        past = (today - datetime.timedelta(days=30)).isoformat()
        def ln(u, phone, host, exp, name="ع"):
            return {"order": u, "username": u, "password": "p", "host": host, "phone": phone, "customer": name, "expiry": exp, "date": past}
        panels.save_store_lines(d, [ln("u1", "0500000001", "http://cdn65.mitatura.store", fut), ln("u2", "966500000001", "http://cdn65.mitatura.store/", fut),
                                    ln("u3", "", "http://cdn65.mitatura.store", fut), ln("u4", "0500000002", "http://cdn65.mitatura.store", past),
                                    ln("u5", "0500000003", "http://other.host", fut)])
        X.DATA_DIR = d
        r = X.host_audience({}, d, "http://cdn65.mitatura.store")
        check("one recipient per phone, expired and no-phone excluded", len(r["recipients"]) == 1 and r["recipients"][0]["usernames"] == ["u1", "u2"]
              and len(r["no_phone"]) == 1 and r["expired_skipped"] == 1 and r["lines"] == 4, str(r))
        r2 = X.host_audience({}, d, "cdn65.mitatura.store", include_expired=True)
        check("host matches without scheme and expired can be included", len(r2["recipients"]) == 2)
        # نوع الاشتراك + المرسَل سابقًا
        lines = panels.load_store_lines(d)["lines"]
        lines[0]["falcon"] = True
        lines[3]["product"] = "اشتراك سمارت"
        lines[3]["expiry"] = fut
        panels.save_store_lines(d, lines)
        rf = X.host_audience({}, d, "http://cdn65.mitatura.store", sub="falcon")
        check("sub filter keeps only falcon lines", rf["lines"] == 1 and rf["recipients"][0]["usernames"] == ["u1"] and rf["subs"].get("falcon") == 1 and rf["subs"].get("smart") == 1, str(rf["subs"]))
        panels.log_dup_send(d, {"order": "host:cdn65.mitatura.store", "kind": "host", "name": "ع", "phone": "966500000001", "text": "t"}, "contest", True)
        rs = X.host_audience({}, d, "http://cdn65.mitatura.store")
        check("already-sent phones are skipped and counted", all(r["phone"] != "966500000001" for r in rs["recipients"]) and rs["sent_before"] == 1, str(rs["sent_before"]))
        check("skip_sent off keeps them flagged", any(r["sent"] for r in X.host_audience({}, d, "http://cdn65.mitatura.store", skip_sent=False)["recipients"]))
        check("empty host is an error", "error" in X.host_audience({}, d, ""))
        check("default template has the placeholders", all(k in X.HOST_MSG for k in ("{name}", "{host}", "{channel}", "{new_host}")))
    finally:
        X.DATA_DIR = keep
        shutil.rmtree(d, ignore_errors=True)


def main():
    test_host_audience()
    test_months()
    test_host()
    test_normalize_panels()
    test_casper_connector()
    test_pull_flavors()
    test_compare()
    test_renewal()
    test_xlsx()
    test_unlisted()
    test_remaining_text()
    test_split_bulk()
    test_dup_create()
    print("\n----------------------------------------")
    print(f"Result: \033[32m{_p} passed\033[0m, "
          + (f"\033[31m{_f} failed\033[0m" if _f else "0 failed"))
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

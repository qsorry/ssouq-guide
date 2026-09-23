#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اختبارات صفحة التجديد: القراءة والتحليل، ثم الضمانات الثلاث —
لا إنشاء مرتين، والانقطاع يُبقي الطلب في الدور، والعودة تُفرِّغه.

    python -m pytest tests/test_renew.py -q      أو      python tests/test_renew.py
"""
import datetime
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import renew                                                   # noqa: E402
import renew_import                                            # noqa: E402

TODAY = datetime.date(2026, 9, 23)


def order_csv(rows):
    """صفوف (رقم، حالة، جوال، تاريخ، منتج، كمية، sku) → ملف طلبات سلة."""
    head = ("رقم الطلب,حالة الطلب,رقم الجوال,تاريخ الطلب,skus_json\n")
    out = [head]
    for no, status, phone, date, product, qty, sku in rows:
        skus = json.dumps([[product, qty, sku, 40, 40]], ensure_ascii=False)
        out.append('%s,%s,%s,%s,"%s"\n' % (no, status, phone, date, skus.replace('"', '""')))
    return "".join(out).encode("utf-8")


def product_csv(rows):
    out = ["اسم المنتج,SKU,السعر\n"]
    for name, sku, price in rows:
        out.append('"%s",%s,%s\n' % (name, sku, price))
    return "".join(out).encode("utf-8")


# ============================ القراءة ============================
class TestReading(unittest.TestCase):
    def test_duration_from_name(self):
        for name, months in [
            ("اشتراك سمارت لمدة سنه", 12),
            ("اشتراك iptv للمسلسلات والافلام لمدة 15 شهر", 15),
            ("اشتراك سمارت لمدة 6 اشهر", 6),
            ("اشتراك IPTV لمدة 30 شهر | أطول باقة وأوفر سعر", 30),
            ("اقوى بث باقه كاس العالم للمباريات | لمدة 3 شهور", 3),
            ("اشتراك مسلسلات شهر رمضان ونتفلكس لمدة 15 شهر", 15),
        ]:
            self.assertEqual(renew_import.months_of(name)[0], months, name)

    def test_devices_not_confused_by_duration(self):
        """«١٥ شهر | جهاز واحد» جهازٌ واحد لا خمسة عشر — الرقم للمدة لا للأجهزة."""
        self.assertEqual(renew_import.devices_of("اشتراك كاسبر - 15 شهر | جهاز واحد"), 1)
        self.assertEqual(renew_import.devices_of("اشتراك سنة + 3 اشهر + جهازين"), 2)

    def test_identical_files_dropped(self):
        raw = order_csv([("111", "طلبك مؤكد", "0501234567", "2026-06-01", "اشتراك لمدة سنة", 1, "")])
        units, meta = renew_import.read_orders([("a.csv", raw), ("b.csv", raw)])
        self.assertEqual(meta["files_dup"], 1)
        self.assertEqual(len(units), 1)

    def test_repeated_order_number_dropped(self):
        a = order_csv([("222", "طلبك مؤكد", "0501111111", "2026-06-01", "اشتراك لمدة سنة", 1, "")])
        b = order_csv([("222", "طلبك مؤكد", "0501111111", "2026-06-01", "اشتراك لمدة سنة", 1, ""),
                       ("333", "طلبك مؤكد", "0502222222", "2026-06-02", "اشتراك لمدة سنة", 1, "")])
        units, meta = renew_import.read_orders([("a.csv", a), ("b.csv", b)])
        self.assertEqual(meta["orders_dup"], 1)
        self.assertEqual({u["order"] for u in units}, {"222", "333"})

    def test_quantity_is_users_not_orders(self):
        raw = order_csv([("444", "طلبك مؤكد", "0503333333", "2026-06-01", "اشتراك لمدة سنة", 3, "")])
        units, _ = renew_import.read_orders([("a.csv", raw)])
        self.assertEqual(len(units), 3)

    def test_unconfirmed_and_falcon_dropped(self):
        raw = order_csv([
            ("1", "ملغي", "0500000001", "2026-06-01", "اشتراك لمدة سنة", 1, ""),
            ("2", "طلبك مؤكد", "0500000002", "2026-06-01", "FALCON TV PRO | فالكون 15 شهر", 1, ""),
            ("3", "طلبك مؤكد", "0500000003", "2026-06-01", "اشتراك لمدة سنة", 1, ""),
        ])
        units, meta = renew_import.read_orders([("a.csv", raw)])
        self.assertEqual([u["order"] for u in units], ["3"])
        self.assertEqual(meta["skipped"]["unconfirmed"], 1)
        self.assertEqual(meta["skipped"]["falcon"], 1)
        units2, _ = renew_import.read_orders([("a.csv", raw)], include_falcon=True)
        self.assertEqual(sorted(u["order"] for u in units2), ["2", "3"])

    def test_products_file_sets_duration(self):
        """المنتج يُعرَّف بالـSKU، فتُقرأ مدته من ملف المنتجات لا من نصّ الطلب."""
        prods = renew_import.read_products([("p.csv", product_csv([("باقة الموسم لمدة 6 اشهر", "SK1", 40)]))])
        raw = order_csv([("9", "طلبك مؤكد", "0509999999", "2026-06-01", "باقة الموسم", 1, "SK1")])
        units, _ = renew_import.read_orders([("o.csv", raw)], prods)
        self.assertEqual(units[0]["months"], 6)

    def test_upload_splits_orders_from_products(self):
        o = order_csv([("5", "طلبك مؤكد", "0505555555", "2026-06-01", "اشتراك لمدة سنة", 1, "")])
        p = product_csv([("اشتراك لمدة سنة", "SK9", 40)])
        units, meta, _prods, agg = renew_import.ingest([("orders.csv", o), ("products.csv", p)])
        self.assertEqual(meta["orders_files"], ["orders.csv"])
        self.assertEqual(meta["products_files"], ["products.csv"])
        self.assertEqual(agg["units"]["all"], 1)


# ============================ الحساب ============================
class TestPlanning(unittest.TestCase):
    def test_remaining_is_what_is_left(self):
        """المثال في المواصفة: اشترى باقة سنة قبل ٦ شهور → يبقى له ٦."""
        bought = renew.add_months(TODAY, -6)
        p = renew.plan_from_order({"date": bought.isoformat(), "months": 12}, today=TODAY)
        self.assertEqual(p["months"], 6)
        self.assertEqual(p["tier"], 6)

    def test_tier_rounds_up_to_a_real_package(self):
        self.assertEqual(renew.tier_for(9), 12)     # لا توجد باقة ٩ شهور
        self.assertEqual(renew.tier_for(6), 6)
        self.assertEqual(renew.tier_for(31), 30)    # لا شيء فوق الثلاثين

    def test_expired_is_refused(self):
        bought = renew.add_months(TODAY, -13)
        p = renew.plan_from_order({"date": bought.isoformat(), "months": 12}, today=TODAY)
        self.assertTrue(p["expired"])


# ============================ الضمانات ============================
class FakePanel:
    """لوحة مرح مزيّفة: تُنشئ، وتَعرف ما أنشأته، وتستطيع أن «تنقطع»."""

    def __init__(self):
        self.lines = {}
        self.down = False
        self.creates = 0

    def exists(self, gate, username):
        if self.down:
            raise RuntimeError("connection refused")
        return username in self.lines

    def create(self, gate, pkg, username=None, password=None):
        if self.down:
            raise RuntimeError("connection refused")
        self.creates += 1
        self.lines[username] = password
        return {"line": "Host %s User %s Pass %s" % (gate["host"], username, password),
                "username": username, "password": password}

    def find_gate(self, acct, gate_id):
        return next((g for g in (acct or {}).get("gates", [])
                     if str(g.get("id")) == str(gate_id)), None)


class TestGuarantees(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.panel = FakePanel()
        self.prov = renew.Provisioner(self.panel.exists, self.panel.create, self.panel.find_gate)
        self.st = {"accounts": [{"id": "a1", "name": "أنا",
                                 "gates": [{"id": "g1", "name": "مرح", "mode": "web",
                                            "host": "http://marh.tv:80"},
                                           {"id": "g2", "name": "فالكون", "mode": "falcon",
                                            "host": "http://falcon.tv:80"}]}]}
        self.cfg = {**renew.default_config(), "enabled": True, "dry_run": False,
                    "target": {"account_id": "a1", "gate_id": "g1"},
                    "packages": {"6": {"id": "P6", "name": "6 شهور"},
                                 "12": {"id": "P12", "name": "سنة"}}}

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def submit(self, **kw):
        base = dict(order_no="1001", phone="0501234567", username="U1", password="P1",
                    months=6, tier=6, expiry="2027-03-23", devices=1, source="test")
        base.update(kw)
        return renew.submit(self.dir, self.st, self.cfg, self.prov, **base)

    # ---- ١: لا يُنشأ يوزر مرتين ----
    def test_same_request_twice_creates_once(self):
        rec1, new1 = self.submit()
        rec2, new2 = self.submit()
        self.assertTrue(new1)
        self.assertFalse(new2)
        self.assertEqual(rec1["ticket"], rec2["ticket"])
        self.assertEqual(self.panel.creates, 1)

    def test_same_username_from_another_order_creates_once(self):
        self.submit()
        _rec, new = self.submit(order_no="2002")
        self.assertFalse(new)
        self.assertEqual(self.panel.creates, 1)

    def test_line_already_on_panel_is_not_recreated(self):
        """إنشاءٌ نجح وضاع ردّه: اللوحة تعرف اليوزر، فلا يُنشأ ثانيًا."""
        self.panel.lines["U9"] = "P9"
        rec, _ = self.submit(order_no="3003", username="U9", password="P9")
        self.assertEqual(rec["state"], "done")
        self.assertEqual(self.panel.creates, 0)

    def test_crash_before_response_leaves_the_key_taken(self):
        """السجل يُحجز قبل النداء: فحتى لو انهار الخادم أثناءه، المفتاح محجوز."""
        self.panel.down = True
        rec, _ = self.submit(order_no="4004", username="U4")
        self.assertEqual(rec["state"], "queued")
        db = renew.load_db(self.dir)
        self.assertIn("o:4004", db["claims"])
        self.assertEqual(db["by_user"]["u4"], "o:4004")

    # ---- ٢: الانقطاع يُبقي الطلب في الدور ----
    def test_disconnect_queues_and_promises(self):
        self.panel.down = True
        rec, _ = self.submit()
        self.assertEqual(rec["state"], "queued")
        self.assertEqual(self.panel.creates, 0)
        view = renew.public_view(rec, self.cfg["promise_hours"])
        self.assertEqual(view["promise_hours"], 12)
        self.assertNotIn("password", view)      # لا بيانات قبل التفعيل
        self.assertEqual(len(renew.pending(self.dir)), 1)

    # ---- ٣: العودة تُفرِّغ الطابور ----
    def test_queue_drains_when_the_panel_returns(self):
        self.panel.down = True
        for i in range(3):
            self.submit(order_no="500%d" % i, username="U50%d" % i)
        self.assertEqual(len(renew.pending(self.dir)), 3)

        self.panel.down = False
        out = renew.run_queue(self.dir, self.st, self.cfg, self.prov)
        self.assertEqual(out["done"], 3)
        self.assertEqual(out["left"], 0)
        self.assertEqual(self.panel.creates, 3)

    def test_drain_stops_at_the_first_disconnect(self):
        """اللوحة ما زالت مقطوعة: لا نُراكم محاولات فاشلة على كل الطلبات."""
        self.panel.down = True
        for i in range(4):
            self.submit(order_no="600%d" % i, username="U60%d" % i)
        out = renew.run_queue(self.dir, self.st, self.cfg, self.prov)
        self.assertEqual(out["ran"], 1)
        self.assertEqual(out["done"], 0)

    def test_drained_lines_are_not_created_again(self):
        self.panel.down = True
        self.submit(order_no="7007", username="U7")
        self.panel.down = False
        renew.run_queue(self.dir, self.st, self.cfg, self.prov)
        renew.run_queue(self.dir, self.st, self.cfg, self.prov)
        self.submit(order_no="7007", username="U7")
        self.assertEqual(self.panel.creates, 1)

    # ---- فالكون ----
    def test_falcon_gate_is_refused(self):
        self.cfg["target"] = {"account_id": "a1", "gate_id": "g2"}
        rec, _ = self.submit(order_no="8008", username="U8")
        self.assertEqual(rec["state"], "rejected")
        self.assertEqual(self.panel.creates, 0)
        self.assertNotIn(rec, renew.pending(self.dir))   # لا يُعاد تلقائيًا

    # ---- التعرّف ----
    def test_order_needs_the_matching_phone(self):
        renew.save_index(self.dir, {"orders": {"9001": {
            "phone": "966501234567", "date": "2026-06-01", "months": 12, "devices": 1}}})
        self.assertIsNone(renew.find_order(self.dir, "9001", "0555555555"))
        self.assertIsNotNone(renew.find_order(self.dir, "9001", "0501234567"))
        self.assertIsNotNone(renew.find_order(self.dir, "9001", "+966501234567"))

    def test_rate_limit_blocks_guessing(self):
        for _ in range(5):
            self.assertTrue(renew.rate_ok(self.dir, "1.2.3.4", 5))
        self.assertFalse(renew.rate_ok(self.dir, "1.2.3.4", 5))
        self.assertTrue(renew.rate_ok(self.dir, "5.6.7.8", 5))   # عنوان آخر لا يُعاقَب

    def test_secrets_never_reach_the_browser(self):
        cfg = {**renew.default_config(),
               "alert": {**renew.default_config()["alert"], "password": "s3cret"}}
        red = renew.redact_config(cfg)
        self.assertNotIn("password", red["alert"])
        self.assertTrue(red["alert"]["has_password"])
        self.assertNotIn("s3cret", json.dumps(red, ensure_ascii=False))

    def test_empty_password_keeps_the_stored_one(self):
        old = {**renew.default_config(),
               "alert": {**renew.default_config()["alert"], "password": "keepme"}}
        new = renew.clean_config({**renew.default_config()}, old)
        self.assertEqual(new["alert"]["password"], "keepme")


# ============================ نقاط الباقات وسعرها ============================
class TestPricing(unittest.TestCase):
    """النقاط تُقرأ من أسماء باقات مرح، وسعر النقطة يكتبه صاحب الحساب."""

    def test_credits_read_from_the_package_name(self):
        import xm_lines
        for name, months, devices, credits in [
            ("اشتراك شهر (نقطة)", 1, 1, 1),
            ("اشتراك 3 اشهر (نقطتين)", 3, 1, 2),
            ("اشتراك 6 اشهر (3 نقاط)", 6, 1, 3),
            ("اشتراك سنة (4 نقاط)", 12, 1, 4),
            ("اشتراك سنة + 3 اشهر (4 نقاط)", 15, 1, 4),
            ("اشتراك سنة + جهازين (6 نقاط)", 12, 2, 6),
            ("اشتراك سنة + 3 اشهر + جهازين (6 نقاط)", 15, 2, 6),
            ("اشتراك 30 شهر (8 نقاط)", 30, 1, 8),
        ]:
            info = xm_lines.parse_package_name(name)
            self.assertEqual((info["months"], info["devices"], info["credits"]),
                             (months, devices, credits), name)

    def test_two_devices_is_not_double(self):
        """السنة بأربع نقاط والسنة بجهازين بستٍّ — لا بثمانٍ. الضربُ في الأجهزة خطأ."""
        import xm_lines
        one = xm_lines.parse_package_name("اشتراك سنة (4 نقاط)")["credits"]
        two = xm_lines.parse_package_name("اشتراك سنة + جهازين (6 نقاط)")["credits"]
        self.assertEqual((one, two), (4, 6))
        self.assertNotEqual(two, one * 2)

    def test_gate_keeps_the_cost_its_owner_typed(self):
        import xm_lines
        g = xm_lines.clean_gate({"name": "مرح", "mode": "web", "host": "http://m.tv:80",
                                 "panel_base": "http://p.tv", "panel_user": "u",
                                 "panel_pass": "p", "point_cost": "2.5"})
        self.assertEqual(g["point_cost"], 2.5)

    def test_blank_cost_is_unknown_not_zero(self):
        """الفراغ «غير محدَّد»، وصفرٌ تكلفةٌ — فلا يُخلط بينهما."""
        import xm_lines
        base = {"name": "مرح", "mode": "web", "host": "http://m.tv:80",
                "panel_base": "http://p.tv", "panel_user": "u", "panel_pass": "p"}
        self.assertEqual(xm_lines.clean_gate({**base, "point_cost": ""})["point_cost"], "")
        self.assertEqual(xm_lines.clean_gate({**base, "point_cost": "لا"})["point_cost"], "")
        self.assertEqual(xm_lines.clean_gate({**base, "point_cost": "0"})["point_cost"], 0)

    def test_cost_survives_an_edit_that_omits_it(self):
        import xm_lines
        old = xm_lines.clean_gate({"name": "مرح", "mode": "web", "host": "http://m.tv:80",
                                   "panel_base": "http://p.tv", "panel_user": "u",
                                   "panel_pass": "p", "point_cost": 2})
        new = xm_lines.clean_gate({"name": "مرح", "mode": "web", "host": "http://m.tv:80",
                                   "panel_base": "http://p.tv", "panel_user": "u"}, old)
        self.assertEqual(new["point_cost"], 2)

    def test_config_stores_package_credits(self):
        cfg = renew.normalize_config({"packages": {"12": {"id": "7", "name": "سنة", "credits": "4"}}})
        self.assertEqual(cfg["packages"]["12"]["credits"], 4)


# ============================ قراءة الاعتمادات ============================
class TestCredentials(unittest.TestCase):
    """الاعتماد يُكتب يدويًا في الطلب، فتختلف صياغته من كاتب لآخر ومن شهر لآخر.
    القراءة تتسامح مع الشكل وتتمسّك بالمعنى."""

    STYLES = [
        # كما وردت فعلًا في ملفات سلة
        ("Host: http://ksa4you.co:80 | Username: 293643794326 |Password: 221893957253",
         "http://ksa4you.co:80", "293643794326", "221893957253"),
        ("Host: http://ssouq.org:80\nUsername: 608147296618\nPassword: 299303692789",
         "http://ssouq.org:80", "608147296618", "299303692789"),
        ("Host-URL: http://mrha.ink", "http://mrha.ink", None, None),
        # صيغ أخرى: بلا مسافة، بفواصل، وبحرف كبير في UserName
        ("HOST:http://ssouqhost.vip|UserName:962491987906|Password:195990759930",
         "http://ssouqhost.vip", "962491987906", "195990759930"),
        # «host» بلا نقطتين، و«Passowrd» مصحَّفًا، والترتيب مقلوب
        ("username:346731410391 Passowrd:266061955108 host http://ssouqhost.vip",
         "http://ssouqhost.vip", "346731410391", "266061955108"),
    ]

    def test_every_style_reads_the_same(self):
        for text, host, user, pw in self.STYLES:
            got = renew_import.parse_credentials(text)
            self.assertEqual(got.get("host"), host, text[:40])
            if user:
                self.assertEqual(got.get("username"), user, text[:40])
                self.assertEqual(got.get("password"), pw, text[:40])

    def test_bare_host_without_a_colon_needs_company(self):
        """«host http://x» بلا نقطتين يُقبل مع يوزر أو باسورد فقط — وإلا صار كل
        ذكرٍ لكلمة hosting هوستًا."""
        self.assertEqual(renew_import.parse_credentials("نحن أفضل hosting في السوق"), {})
        self.assertEqual(renew_import.parse_credentials("host example.com"), {})
        self.assertEqual(
            renew_import.parse_credentials("user:abc pass:xyz host example.com").get("host"),
            "http://example.com")

    def test_an_email_is_not_a_host(self):
        for e in ("host_12@live.com", "host80@gmail.com", "password007@hotmail.co.uk"):
            self.assertNotIn("host", renew_import.parse_credentials(e))

    def test_credentials_travel_into_the_index(self):
        """ما كُتب في الطلب يصل إلى الفهرس، فلا يُطلب من العميل كتابته."""
        raw = ("رقم الطلب,حالة الطلب,رقم الجوال,تاريخ الطلب,الملاحظات الداخلية,skus_json\n"
               '777,طلبك مؤكد,0501234567,2026-06-01,'
               '"HOST:http://ssouqhost.vip|UserName:9624919|Password:1959907",'
               '"[[""اشتراك لمدة سنة"", 1, """", 40, 40]]"\n').encode("utf-8")
        units, meta = renew_import.read_orders([("o.csv", raw)])
        self.assertEqual(units[0]["username"], "9624919")
        idx = renew_import.build_index(units, meta)
        self.assertEqual(idx["orders"]["777"]["password"], "1959907")
        self.assertEqual(idx["orders"]["777"]["host"], "http://ssouqhost.vip")

    def test_analysis_counts_credentials_and_hosts(self):
        raw = ("رقم الطلب,حالة الطلب,رقم الجوال,تاريخ الطلب,الملاحظات الداخلية,skus_json\n"
               '778,طلبك مؤكد,0501234567,2026-06-01,'
               '"Host: http://a.co:80 | Username: 111 | Password: 222",'
               '"[[""اشتراك لمدة سنة"", 1, """", 40, 40]]"\n'
               '779,طلبك مؤكد,0501234568,2026-06-01,,'
               '"[[""اشتراك لمدة سنة"", 1, """", 40, 40]]"\n').encode("utf-8")
        units, meta = renew_import.read_orders([("o.csv", raw)])
        agg = renew_import.analyze(units, meta)
        self.assertEqual(agg["creds"]["with_credentials"], 1)
        self.assertEqual(agg["creds"]["hosts"], [{"k": "a.co:80", "n": 1}])


# ============================ البطاقات الرقمية ============================
class TestDigitalCodes(unittest.TestCase):
    """مساران لتسليم الاشتراك: تعليقٌ يكتبه موظّف، وبطاقةٌ من مخزون الأكواد.
    السجلّ لا يحمل الثانية — يحمل رقمها فقط."""

    def test_code_id_read_from_the_history_line(self):
        import salla_api
        self.assertEqual(salla_api.code_ids_from_notes("تم شراء الكود #186327502"),
                         ["186327502"])
        self.assertEqual(salla_api.code_ids_from_notes("تم إرسال رسالة التقيم"), [])

    def test_an_order_delivered_by_card_has_no_credentials_in_its_history(self):
        """الطلب 272053873 كما جاء من سلة: سبعة قيود آلية، ولا اعتماد فيها."""
        notes = "\n".join(["تم إرسال رسالة التقيم",
                            "تم إرسال فاتورة الطلب  ومحتوى المنتجات إلى بريد العميل",
                            "تم إرسال البطاقات الرقمية إلى جوال العميل",
                            "تم شراء الكود #186327502"])
        self.assertEqual(renew_import.parse_credentials(notes), {})
        import salla_api
        self.assertTrue(salla_api.code_ids_from_notes(notes))   # لكنه يدلّ على الكود

    def test_credentials_are_read_out_of_a_card_payload(self):
        """حمولة الكود مهما تعشّشت: تُجمَّع نصوصها وتُقرأ بنفس القارئ."""
        import salla_api
        payload = {"data": [{"id": 1, "codes": [
            {"code": "HOST:http://ssouqhost.vip|UserName:962491987906|Password:195990759930"}]}]}
        text = "\n".join(salla_api._walk_strings(payload["data"], []))
        self.assertEqual(renew_import.parse_credentials(text),
                         {"username": "962491987906", "password": "195990759930",
                          "host": "http://ssouqhost.vip"})


    def test_xlsx_is_read_like_csv(self):
        """سلة تصدّر xlsx أيضًا — ويُقرأ بلا تبعية، بالمكتبة القياسية."""
        import io as _io
        import zipfile
        book = _io.BytesIO()
        with zipfile.ZipFile(book, "w") as z:
            z.writestr("[Content_Types].xml", "<Types/>")
            z.writestr("xl/sharedStrings.xml",
                       "<sst><si><t>أسم المنتج</t></si><si><t>رمز المنتج sku</t></si>"
                       "<si><t>اشتراك تجريبي</t></si><si><t>MRH-06M</t></si></sst>")
            z.writestr("xl/worksheets/sheet1.xml",
                       '<sheetData>'
                       '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
                       '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2" t="s"><v>3</v></c></row>'
                       '</sheetData>')
        raw = book.getvalue()
        self.assertTrue(renew_import.is_xlsx(raw))
        rows = renew_import._rows(raw)
        self.assertEqual(rows[0]["أسم المنتج"], "اشتراك تجريبي")
        self.assertEqual(rows[0]["رمز المنتج sku"], "MRH-06M")

    def test_the_sku_column_is_found_despite_its_wording(self):
        """سلة تسمّي العمود «رمز المنتج sku» — والمطابقة الحرفية كانت تُسقطه."""
        self.assertEqual(
            renew_import._pick({"رمز المنتج sku": "MRH-06M"}, ("SKU", "sku", "رمز المنتج")),
            "MRH-06M")



# ============================ خطوط اللوحة ============================
class TestPanelLines(unittest.TestCase):
    """اللوحة هي المصدر الكامل الوحيد: كل خط فيها بيوزره وباسورده."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        renew.save_lines(self.dir, [
            {"username": "111222333", "password": "aaa", "exp": "2027-03-01",
             "created": "2026-03-01", "connections": "1", "package": "سنة"},
            {"username": "444555666", "password": "bbb", "exp": "2027-06-10",
             "created": "2026-03-02", "connections": "2", "package": "15 شهر"},
            {"username": "777888999", "password": "ccc", "exp": "2026-12-01",
             "created": "2026-06-01", "connections": "1", "package": "6 اشهر"},
        ], "مرح", "http://marh.tv:80")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_username_resolves_without_touching_the_panel(self):
        got = renew.find_line(self.dir, "111222333")
        self.assertEqual(got["password"], "aaa")

    def test_lookup_ignores_letter_case(self):
        renew.save_lines(self.dir, [{"username": "AbC123", "password": "p"}])
        self.assertIsNotNone(renew.find_line(self.dir, "abc123"))
        self.assertIsNotNone(renew.find_line(self.dir, "ABC123"))

    def test_an_unknown_username_is_not_invented(self):
        self.assertIsNone(renew.find_line(self.dir, "000000"))

    def test_candidates_match_by_date_duration_and_devices(self):
        """من لا يعرف يوزره: خطوطٌ أُنشئت حول يوم شرائه بنفس المدة والأجهزة."""
        c = renew.match_candidates(self.dir, "2026-03-01", months=12, devices=1)
        self.assertEqual([r["username"] for r in c], ["111222333"])

    def test_devices_separate_two_lines_bought_the_same_week(self):
        c = renew.match_candidates(self.dir, "2026-03-01", months=15, devices=2)
        self.assertEqual([r["username"] for r in c], ["444555666"])

    def test_a_distant_purchase_matches_nothing(self):
        self.assertEqual(renew.match_candidates(self.dir, "2026-01-01", 12, 1), [])


# ============================ رموز المنتجات والبطاقة ============================
class TestSkuAndCard(unittest.TestCase):
    """الرمز يحمل المدة صراحةً، والبطاقة تحمل الاعتماد — كلاهما من بيانات حيّة."""

    def test_sku_carries_duration_devices_and_provider(self):
        """رموز كتالوج المتجر نفسه."""
        for sku, months, devices, prov in [
            ("MRH-12M-ENT", 12, 1, "MRH"), ("MRH-06M", 6, 1, "MRH"),
            ("MRH-30M", 30, 1, "MRH"), ("MRH-06M-WEBOS", 6, 1, "MRH"),
            ("MRH-15M-2D", 15, 2, "MRH"),          # «2D» أجهزة: سبقتها مدة
            ("FAL-PRO-24M", 24, 1, "FAL"),         # الرقم ليس بعد الشرطة الأولى
            ("FAL-PRO-15M-2D", 15, 2, "FAL"),
        ]:
            got = renew_import.sku_info(sku)
            self.assertEqual((got.get("months"), got.get("devices"), got.get("provider")),
                             (months, devices, prov), sku)

    def test_a_day_trial_is_not_a_renewable_subscription(self):
        """«MRH-01D-TRIAL» يومٌ لا شهر — ولا متبقّى لتجربةٍ تُجدَّد."""
        got = renew_import.sku_info("MRH-01D-TRIAL")
        self.assertEqual((got.get("days"), got.get("months")), (1, 0))

    def test_falcon_is_known_by_its_prefix_not_its_arabic_name(self):
        """‏`FAL-PRO-15M` فالكون وإن خلا اسمه العربي من الكلمة."""
        self.assertTrue(renew_import.sku_is_falcon("FAL-PRO-15M"))
        self.assertFalse(renew_import.sku_is_falcon("MRH-15M-2D"))

    def test_a_meaningless_sku_is_not_forced(self):
        for sku in ("", "ABC", "MRH", "MRH-0M"):
            self.assertFalse(renew_import.sku_info(sku).get("months"), sku)

    def test_the_sku_beats_the_arabic_name(self):
        """الاسم تسويقيّ يتغيّر، والرمز مُصنَّف بيد صاحبه — فالرمز يُقدَّم."""
        raw = ("رقم الطلب,حالة الطلب,رقم الجوال,تاريخ الطلب,skus_json\n"
               '881,طلبك مؤكد,0501234567,2026-06-01,'
               '"[[""اشتراك ترفيهي رقمي"", 1, ""MRH-06M"", 40, 40]]"\n').encode("utf-8")
        units, _ = renew_import.read_orders([("o.csv", raw)])
        self.assertEqual(units[0]["months"], 6)      # لا مدة في الاسم أصلًا

    def test_the_real_digital_card_is_read(self):
        """نصّ البطاقة كما يظهر في لوحة سلة للطلب 272053873 — بالتصحيف وكل شيء."""
        card = ("الرقم المخزني SKU:\nMRH-12M-ENT\nالكود:\n"
                "username:346731410391\nPassowrd:266061955108 host http://ssouqhost.vip")
        self.assertEqual(renew_import.parse_credentials(card), {
            "username": "346731410391", "password": "266061955108",
            "host": "http://ssouqhost.vip"})


# ============================ جلسة لوحة سلة ============================
class TestPanelSession(unittest.TestCase):
    """بديل الواجهة حين لا تُخرج ما نحتاج — بكوكيز يلصقها المشغّل، لا بدخول آلي."""

    def test_every_shape_of_paste_is_accepted(self):
        """التنقيب عن الترويسة وحدها متعب، فيُقبل «Copy as cURL» كما هو."""
        import salla_web
        want = "salla_session=abc; XSRF-TOKEN=def"
        for raw in [
            "curl 'https://s.salla.sa/api/orders/x' -H 'accept: application/json' "
            "-H 'cookie: salla_session=abc; XSRF-TOKEN=def' --compressed",
            'curl "https://s.salla.sa/orders" -b "salla_session=abc; XSRF-TOKEN=def"',
            "Cookie: salla_session=abc; XSRF-TOKEN=def",
            "salla_session=abc; XSRF-TOKEN=def",
            "salla_session=abc\nXSRF-TOKEN=def",
        ]:
            self.assertEqual(salla_web.clean_cookie(raw), want, raw[:40])

    def test_a_pasted_cookie_header_is_cleaned(self):
        import salla_web
        for raw, want in [
            ("Cookie: a=1; b=2", "a=1; b=2"),
            ("a=1\nb=2", "a=1; b=2"),
            ("  a=1; ضجيج; b=2 ", "a=1; b=2"),
            ("a=1;", "a=1"),
        ]:
            self.assertEqual(salla_web.clean_cookie(raw), want, raw)

    def test_an_empty_cookie_is_refused_outright(self):
        import salla_web
        with self.assertRaises(salla_web.WebError):
            salla_web.Session("")

    def test_the_admin_link_gives_the_panel_token(self):
        """الواجهة تعطي `urls.admin` لكل طلب — وهو الجسر بينها وبين اللوحة."""
        import salla_web
        self.assertEqual(
            salla_web.admin_token("https://s.salla.sa/orders/order/oPpbBAN_JmK78M6q"),
            "oPpbBAN_JmK78M6q")
        self.assertEqual(salla_web.admin_token("https://s.salla.sa/customers/x"), "")

    def test_the_cookie_never_reaches_the_browser(self):
        cfg = renew.normalize_config({"panel_cookie": "salla_session=secret"})
        red = renew.redact_config(cfg)
        self.assertNotIn("panel_cookie", red)
        self.assertTrue(red["has_panel_cookie"])
        self.assertNotIn("secret", json.dumps(red, ensure_ascii=False))

    def test_an_empty_cookie_field_keeps_the_stored_one(self):
        old = renew.normalize_config({"panel_cookie": "keepme=1"})
        self.assertEqual(renew.clean_config({}, old)["panel_cookie"], "keepme=1")

    def test_each_alert_kind_has_its_own_throttle(self):
        """انقطاع مرح وانتهاء جلسة سلة حدثان مختلفان — فلا يبتلع أحدهما الآخر."""
        d = tempfile.mkdtemp()
        try:
            sent = []
            cfg = {**renew.default_config(),
                   "alert": {**renew.default_config()["alert"],
                             "host": "smtp.test", "to": "me@test", "gap_minutes": 60}}
            real = renew._smtp_send
            renew._smtp_send = lambda a, s_, b: sent.append(s_)
            try:
                renew.alert_disconnect(d, cfg, "refused", 3)
                renew.alert_session_expired(d, cfg)          # نوعٌ آخر — يمرّ
                renew.alert_disconnect(d, cfg, "refused", 4)  # مكرر — يُخنق
                renew.alert_session_expired(d, cfg)           # مكرر — يُخنق
            finally:
                renew._smtp_send = real
            self.assertEqual(len(sent), 2, sent)
            self.assertTrue(any("مرح" in x for x in sent))
            self.assertTrue(any("سلة" in x for x in sent))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_the_expiry_alert_says_how_to_fix_it(self):
        """لا دخول آلي: التحقّق الثنائي إلزاميّ، فالرسالة تشرح اللصق."""
        d = tempfile.mkdtemp()
        try:
            body = []
            cfg = {**renew.default_config(),
                   "alert": {**renew.default_config()["alert"],
                             "host": "smtp.test", "to": "me@test"}}
            real = renew._smtp_send
            renew._smtp_send = lambda a, s_, b: body.append(b)
            try:
                renew.alert_session_expired(d, cfg)
            finally:
                renew._smtp_send = real
            self.assertIn("s.salla.sa", body[0])
            self.assertIn("Cookie", body[0])
        finally:
            shutil.rmtree(d, ignore_errors=True)


# ============================ الحصاد ============================
class TestHarvest(unittest.TestCase):
    """جلسة اللوحة تنتهي خلال ساعات، فهي نافذةُ حصادٍ لا اعتمادٌ دائم."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        renew.save_index(self.dir, {"orders": {
            "101": {"sid": "s1", "phone": "966501111111", "date": "2026-03-01", "months": 12},
            "102": {"sid": "s2", "phone": "966502222222", "date": "2026-03-01", "months": 12},
            "103": {"sid": "s3", "phone": "966503333333", "date": "2026-03-01", "months": 12},
        }})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_progress_survives_a_restart(self):
        """التقدّم على القرص لا في الذاكرة — فموتُ الخادم لا يُضيّع ساعةَ عمل."""
        renew.harvest_record(self.dir, [("s1", {"username": "u1", "password": "p1"})])
        self.assertEqual(renew.harvest_pending(self.dir, ["s1", "s2", "s3"]), ["s2", "s3"])
        self.assertEqual(renew.harvest_stats(self.dir)["found"], 1)

    def test_a_fruitless_order_is_not_asked_twice(self):
        """من لا اعتماد له يُعلَّم أيضًا — وإلا دارت الجلسة القصيرة عليه وتركت غيره."""
        renew.harvest_record(self.dir, [("s2", {})])
        self.assertNotIn("s2", renew.harvest_pending(self.dir, ["s1", "s2", "s3"]))
        self.assertEqual(renew.harvest_stats(self.dir)["found"], 0)

    def test_what_was_harvested_lands_in_the_index(self):
        renew.harvest_record(self.dir, [("s1", {"username": "u1", "password": "p1",
                                                "host": "http://old.tv"})])
        self.assertEqual(renew.harvest_into_index(self.dir), 1)
        rec = renew.load_index(self.dir)["orders"]["101"]
        self.assertEqual((rec["username"], rec["password"]), ("u1", "p1"))
        self.assertEqual(renew.harvest_into_index(self.dir), 0)   # لا يُكرَّر

    def test_a_harvested_order_never_needs_the_session_again(self):
        """بعد الحصاد يُعرف العميل من القرص — ولو ماتت الجلسة واللوحة معًا."""
        renew.harvest_record(self.dir, [("s1", {"username": "u1", "password": "p1"})])
        got = renew.load_harvest(self.dir)["found"].get("s1")
        self.assertEqual(got["password"], "p1")

    def test_a_retry_round_keeps_what_was_found_and_frees_the_rest(self):
        renew.harvest_record(self.dir, [("s1", {"username": "u1"}), ("s2", {}), ("s3", {})])
        self.assertEqual(renew.harvest_pending(self.dir, ["s1", "s2", "s3"]), [])
        renew.harvest_reset(self.dir)
        self.assertEqual(renew.harvest_pending(self.dir, ["s1", "s2", "s3"]), ["s2", "s3"])
        self.assertEqual(renew.harvest_stats(self.dir)["rounds"], 1)

    def test_the_scope_is_chosen_by_date(self):
        """النافذة ساعات، فالحصاد يُوجَّه لا يُكنس."""
        renew.save_index(self.dir, {"orders": {
            "1": {"sid": "s1", "date": "2026-08-01", "months": 12, "admin_url": "u1"},
            "2": {"sid": "s2", "date": "2026-02-01", "months": 12, "admin_url": "u2"},
        }})
        rows, n = renew.harvest_scope(self.dir, from_date="2026-06-01", today=TODAY)
        self.assertEqual([r["order"] for r in rows], ["1"])
        self.assertEqual((n["in_range"], n["pending"]), (1, 1))

    def test_an_expired_order_is_not_worth_reading(self):
        """انقضى اشتراكه فلا يُجدَّد — فلا معنى لإنفاق النافذة على اعتماده."""
        renew.save_index(self.dir, {"orders": {
            "9": {"sid": "s9", "date": "2024-01-01", "months": 12, "admin_url": "u9"}}})
        rows, n = renew.harvest_scope(self.dir, today=TODAY)
        self.assertEqual((rows, n["expired"]), ([], 1))
        rows2, _ = renew.harvest_scope(self.dir, active_only=False, today=TODAY)
        self.assertEqual(len(rows2), 1)

    def test_an_order_whose_credentials_are_known_is_skipped(self):
        renew.save_index(self.dir, {"orders": {
            "7": {"sid": "s7", "date": "2026-08-01", "months": 12,
                  "username": "u", "password": "p"}}})
        rows, n = renew.harvest_scope(self.dir, today=TODAY)
        self.assertEqual((rows, n["known"]), ([], 1))

    def test_the_newest_orders_are_harvested_first(self):
        """الأحدث أطولها بقاءً، فهو أولى بنافذةٍ قد تُغلَق قبل أن تكتمل."""
        renew.save_index(self.dir, {"orders": {
            "a": {"sid": "sa", "date": "2026-04-01", "months": 12, "admin_url": "ua"},
            "b": {"sid": "sb", "date": "2026-08-01", "months": 12, "admin_url": "ub"},
            "c": {"sid": "sc", "date": "2026-06-01", "months": 12, "admin_url": "uc"},
        }})
        rows, _ = renew.harvest_scope(self.dir, today=TODAY)
        self.assertEqual([r["order"] for r in rows], ["b", "c", "a"])



if __name__ == "__main__":
    unittest.main(verbosity=2)

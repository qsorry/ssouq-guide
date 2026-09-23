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


if __name__ == "__main__":
    unittest.main(verbosity=2)

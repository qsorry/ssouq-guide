#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اختبارات الاشتراكات المجزّأة (split_subs) بلا لوحة ولا شبكة: جسرٌ وهميّ يمثّل
اللوحة، والوقت يُمرَّر صراحةً — فيُختبَر ما بعد ستة أشهر في جزءٍ من الثانية.

    python -m pytest tests/test_split.py -q      أو      python tests/test_split.py
"""
import datetime
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import split_subs as S                                          # noqa: E402

T0 = datetime.datetime(2026, 9, 28, 14, 30)
GATE = {"id": "g1", "name": "بوابة مرح", "mode": "web", "digits": 12}


class FakePanel:
    """اللوحة: {username: password}. change يغيّر الاسم ويُرجع ما تُظهره اللوحة."""

    def __init__(self, fail=None):
        self.lines = {}
        self.calls = []
        self.fail = fail            # None · Exception يُرفع

    def change(self, gate, rec, pend):
        self.calls.append((rec["username"], pend["username"], pend["password"]))
        if self.fail:
            raise self.fail
        if pend["username"] in self.lines and self.lines[pend["username"]] == pend["password"]:
            return {"already": True, "verified": True}
        pw = self.lines.pop(rec["username"])
        self.lines[pend["username"]] = pw
        return {"verified": True, "line_id": "77", "exp": ""}


class Mailer:
    def __init__(self, ok=True):
        self.sent = []
        self.ok = ok

    def __call__(self, subject, body):
        self.sent.append((subject, body))
        return (self.ok, "" if self.ok else "smtp down")


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="split_")
        self.panel = FakePanel()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def reg(self, user="111122223333", pw="999988887777", months=6, **kw):
        self.panel.lines[user] = pw
        rec, new = S.register(self.d, "a1", GATE, user, pw, months, package="اشتراك سنة + 3 اشهر",
                              now=kw.pop("now", T0), **kw)
        return rec, new

    def rec(self, rid):
        return S.load(self.d, "a1")["lines"][rid]


class TestBatch(Base):
    """جلسة الإنشاء: معرّفٌ بوقتها على كل خطٍّ من الدفعة، في إشعار بيعه، وفي ملخّص الجلسات."""
    def test_id_and_summary(self):
        bid = S.new_batch_id(T0)
        self.assertRegex(bid, r"^S\d{6}-\d{6}$")
        self.assertEqual(bid, "S" + T0.strftime("%y%m%d-%H%M%S"))
        r1, _ = self.reg("111122223333", batch=bid)
        r2, _ = self.reg("444455556666", batch=bid)
        r3, _ = self.reg("777788889999", months=3)           # بلا جلسة (خطٌّ قديم)
        self.assertEqual((r1["batch"], r2["batch"], r3["batch"]), (bid, bid, ""))
        notes = S.load(self.d, "a1")["notes"]
        n1 = next(n for n in notes if n["username"] == "111122223333")
        self.assertIn("جلسة " + bid, n1["text"])
        self.assertEqual(n1["batch"], bid)
        n3 = next(n for n in notes if n["username"] == "777788889999")
        self.assertNotIn("جلسة", n3["text"])
        self.assertEqual(n3["batch"], "")
        v = S.view(self.d, "a1", T0)
        self.assertEqual(len(v["batches"]), 1)
        b = v["batches"][0]
        self.assertEqual((b["id"], b["n"], b["at"], b["months"], b["states"]),
                         (bid, 2, S.fmt(T0), [6], {S.ACTIVE: 2}))
        self.assertEqual(b["gates"], [GATE["name"]])


class TestRegister(Base):
    def test_six_of_fifteen(self):
        rec, new = self.reg()
        self.assertTrue(new)
        self.assertEqual(rec["state"], S.ACTIVE)
        self.assertEqual(rec["slice"]["due"], "2027-03-28 14:30")
        self.assertEqual(rec["expiry"], "2027-12-28")
        v = S.decorate(rec, T0)
        self.assertEqual(v["remaining_after"], 9, "بعد ستة من خمسة عشر يبقى تسعة")

    def test_three_and_one(self):
        r3, _ = self.reg(user="100000000003", months=3)
        r1, _ = self.reg(user="100000000001", months=1)
        self.assertEqual(S.decorate(r3, T0)["remaining_after"], 12)
        self.assertEqual(S.decorate(r1, T0)["remaining_after"], 14)

    def test_twelve_of_fifteen(self):
        """سنةٌ للعميل من باقة ١٥ شهرًا (ومنها «مدة البديل»): يتغيّر الاسم بعد ١٢ شهرًا،
        ويبقى من الخط ثلاثة أشهر للبيع — لا «بيعُ المتبقي» ولا تغييرٌ قبل موعده."""
        rec, _ = self.reg(user="100000000012", months=12)
        self.assertEqual(rec["state"], S.ACTIVE)
        self.assertEqual(rec["slice"]["months"], 12)
        self.assertEqual(rec["slice"]["due"], "2027-09-28 14:30")
        self.assertFalse(rec["slice"]["final"])
        self.assertEqual(S.decorate(rec, T0)["remaining_after"], 3, "بعد اثني عشر من خمسة عشر يبقى ثلاثة")
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=T0 + datetime.timedelta(days=300))
        self.assertEqual(self.panel.calls, [], "لا تغيير قبل تمام السنة")
        due = S.parse_dt(rec["slice"]["due"])
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due)
        r = self.rec(rec["id"])
        self.assertEqual(r["state"], S.AVAILABLE)
        self.assertNotEqual(r["username"], "100000000012")
        self.assertEqual(S.decorate(r, due)["remaining_months"], 3)
        self.assertEqual(S.decorate(r, due)["can_sell"], [3, 1])

    def test_slices_and_default(self):
        """١٢ شهرًا نوعُ بيعٍ كغيره، والاختيار المسبق في «بيع» و«إضافة خطٍّ قائم» يبقى ستة."""
        self.assertEqual(S.SLICES, (12, 6, 3, 1))
        self.assertIn(S.DEFAULT_SLICE, S.SLICES)
        self.assertEqual(S.DEFAULT_SLICE, 6)
        v = S.view(self.d, "a1", T0)
        self.assertEqual((v["slices"], v["default_slice"], v["max_slice"]), ([12, 6, 3, 1], 6, 14))

    def test_same_line_not_twice(self):
        a, _ = self.reg()
        b, new = self.reg()
        self.assertFalse(new)
        self.assertEqual(a["id"], b["id"])

    def test_any_whole_months_within_the_line(self):
        """«مدة أخرى»: أي عددٍ من الأشهر الكاملة من شهرٍ إلى ١٤ (١٠ أشهر مثلًا، وبالأرقام العربية)،
        لا الخيارات السريعة وحدها — وما سواه يُرفض بسببه."""
        r10, _ = self.reg(user="100000000010", months=10)
        self.assertEqual((r10["slice"]["months"], S.decorate(r10, T0)["remaining_after"]), (10, 5))
        self.assertEqual(r10["slice"]["due"], "2027-07-28 14:30")
        r5, _ = self.reg(user="100000000005", months="٥")
        self.assertEqual(r5["slice"]["months"], 5)
        r14, _ = self.reg(user="100000000014", months=14)
        self.assertEqual((r14["state"], S.decorate(r14, T0)["remaining_after"]), (S.ACTIVE, 1))
        for bad in (0, 15, 16, -1, 2.5, "x", "", None, True):
            with self.assertRaises(ValueError, msg=repr(bad)) as cm:
                self.reg(user="100000000099", months=bad)
            self.assertIn("من شهر إلى 14 شهرًا", str(cm.exception))

    def test_parse_months(self):
        self.assertEqual([S.parse_months(v) for v in (10, "10", " ١٠ ", "۱۰", 10.0)], [10] * 5)
        self.assertEqual([S.parse_months(v) for v in ("10.5", 2.5, "عشرة", "", None, True, "-3")], [None] * 7)
        self.assertEqual((S.slice_ok(1), S.slice_ok(14), S.slice_ok(15), S.slice_ok(0)), (True, True, False, False))

    def test_past_due_waits_for_operator(self):
        """خطٌّ قديم انتهى جزؤه قبل تسجيله لا يُغيَّر تلقائيًا: خطأ تاريخ لا يقطع عميلًا."""
        rec, _ = self.reg(start=T0 - datetime.timedelta(days=200))
        self.assertEqual(rec["state"], S.DUE)
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=T0)
        self.assertEqual(self.panel.calls, [])

    def test_eligible_only_fifteen(self):
        self.assertTrue(S.eligible(15))
        self.assertFalse(S.eligible(12))
        self.assertFalse(S.eligible(30))


class TestRotation(Base):
    def test_username_changes_password_stays(self):
        rec, _ = self.reg()
        due = T0 + datetime.timedelta(days=182)
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due)
        r = self.rec(rec["id"])
        self.assertEqual(r["state"], S.AVAILABLE)
        self.assertNotEqual(r["username"], "111122223333")
        self.assertEqual(r["password"], "999988887777", "كلمة المرور لا تتغيّر")
        self.assertEqual(len(r["username"]), 12, "الاسم الجديد بطول القديم")
        self.assertTrue(r["username"].isdigit())
        self.assertEqual(self.panel.lines, {r["username"]: "999988887777"})
        self.assertEqual(r["history"][0]["username"], "111122223333")
        self.assertEqual(S.decorate(r, due)["remaining_months"], 9)
        self.assertEqual(r["line_id"], "77")

    def test_not_before_due(self):
        self.reg()
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=T0 + datetime.timedelta(days=100))
        self.assertEqual(self.panel.calls, [])

    def test_reminder_once_before_due(self):
        rec, _ = self.reg()
        due = S.parse_dt(rec["slice"]["due"])
        alerts = lambda: [n for n in S.load(self.d, "a1")["notes"] if n["kind"] != "sold"]
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due - datetime.timedelta(days=5))
        self.assertEqual(alerts(), [])
        for h in (0, 1, 2):
            S.process(self.d, "a1", {"g1": GATE}, self.panel,
                      now=due - datetime.timedelta(days=2, hours=h))
        self.assertEqual([n["kind"] for n in alerts()], ["due_soon"], "تذكيرٌ واحد لا تذكيرٌ كل دورة")

    def test_lost_response_not_changed_twice(self):
        """حُجز الاسم الجديد، ثم مات الخادم بعد أن أخذته اللوحة: الإعادة تعدّه نجاحًا
        بالاسم نفسه ولا تولّد اسمًا ثالثًا."""
        rec, _ = self.reg()
        due = T0 + datetime.timedelta(days=182)

        class Dies(FakePanel):
            def change(s, gate, r, pend):
                FakePanel.change(s, gate, r, pend)      # اللوحة تغيّرت …
                raise S.Transient("انقطع الاتصال")      # … والردّ ضاع
        dying = Dies()
        dying.lines = self.panel.lines
        S.process(self.d, "a1", {"g1": GATE}, dying, now=due)
        r = self.rec(rec["id"])
        self.assertEqual(r["state"], S.ACTIVE)
        pend = r["pending"]["username"]
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due + datetime.timedelta(minutes=45))
        r = self.rec(rec["id"])
        self.assertEqual(r["state"], S.AVAILABLE)
        self.assertEqual(r["username"], pend, "الاسم المحجوز نفسه — لا اسمٌ ثالث")
        self.assertEqual(self.panel.calls[-1][1], pend)

    def test_transient_retries_later(self):
        rec, _ = self.reg()
        due = T0 + datetime.timedelta(days=182)
        self.panel.fail = S.Transient("اللوحة تطلب كود تحقّق")
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due)
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due + datetime.timedelta(minutes=10))
        self.assertEqual(len(self.panel.calls), 1, "لا إعادة قبل موعدها")
        self.panel.fail = None
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due + datetime.timedelta(minutes=31))
        self.assertEqual(self.rec(rec["id"])["state"], S.AVAILABLE)
        kinds = [n["kind"] for n in S.load(self.d, "a1")["notes"]]
        self.assertEqual(kinds.count("delayed"), 1)

    def test_unsupported_goes_manual(self):
        rec, _ = self.reg()
        due = T0 + datetime.timedelta(days=182)
        self.panel.fail = S.Unsupported("اللوحة تقفل حقل اسم المستخدم")
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due)
        r = self.rec(rec["id"])
        self.assertEqual(r["state"], S.FAILED)
        self.assertIsNone(r["pending"], "لم يُرسَل شيء — لا قيم معلّقة")
        self.assertEqual(S.load(self.d, "a1")["gates"]["g1"]["edit"], "unsupported")
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due + datetime.timedelta(days=1))
        self.assertEqual(len(self.panel.calls), 1, "الفاشل لا يُعاد تلقائيًا")
        # المشغّل غيّره بيده ثم أكّد
        S.confirm_manual(self.d, "a1", rec["id"], username="555566667777", now=due)
        r = self.rec(rec["id"])
        self.assertEqual((r["state"], r["username"], r["password"]),
                         (S.AVAILABLE, "555566667777", "999988887777"))

    def test_failure_after_submit_keeps_pending(self):
        rec, _ = self.reg()
        due = T0 + datetime.timedelta(days=182)
        self.panel.fail = RuntimeError("لم يظهر التغيير في جدول اللوحة")
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due)
        r = self.rec(rec["id"])
        self.assertEqual(r["state"], S.FAILED)
        self.assertTrue(r["pending"]["username"], "قد تكون اللوحة أخذته — يبقى للإعادة والتأكيد")
        self.panel.fail = None
        r2, res = S.rotate(self.d, "a1", rec["id"], GATE, self.panel, now=due, how="now")
        self.assertEqual(res, "ok")
        self.assertEqual(r2["username"], r["pending"]["username"])

    def test_failed_line_ends_with_its_expiry(self):
        rec, _ = self.reg()
        due = S.parse_dt(rec["slice"]["due"])
        self.panel.fail = S.Unsupported("لا صفحة تعديل")
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due)
        self.assertEqual(self.rec(rec["id"])["state"], S.FAILED)
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due + datetime.timedelta(days=300))
        self.assertEqual(self.rec(rec["id"])["state"], S.ENDED)

    def test_manual_mode(self):
        rec, _ = self.reg()
        S.set_cfg(self.d, "a1", {"auto": False})
        due = T0 + datetime.timedelta(days=182)
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due)
        self.assertEqual(self.rec(rec["id"])["state"], S.DUE)
        self.assertEqual(self.panel.calls, [])

    def test_rotate_now_early_failure_keeps_slice(self):
        rec, _ = self.reg()
        self.panel.fail = S.Unsupported("لا صفحة تعديل")
        _r, res = S.rotate(self.d, "a1", rec["id"], GATE, self.panel,
                           now=T0 + datetime.timedelta(days=3), how="now")
        self.assertEqual(res, "failed")
        self.assertEqual(self.rec(rec["id"])["state"], S.ACTIVE, "الجزء باقٍ يجري")


class TestInFlight(Base):
    def test_manual_actions_wait_for_a_running_change(self):
        """المشغّل يؤكّد أو يُسقط خطًّا بينما الدورة تغيّر اسمه على اللوحة: يُرفض حتى
        تنتهي — وإلا كتب كلٌّ فوق الآخر (اللوحة باسمٍ والسجل بآخر)."""
        rec, _ = self.reg()
        key = S._key(self.d, "a1", rec["id"])
        S._inflight.add(key)
        try:
            with self.assertRaises(ValueError):
                S.confirm_manual(self.d, "a1", rec["id"], username="555566667777", now=T0)
            with self.assertRaises(ValueError):
                S.delete(self.d, "a1", rec["id"])
            due = S.parse_dt(rec["slice"]["due"])
            S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due)
            self.assertEqual(self.panel.calls, [], "الدورة تتخطّاه")
            _r, res = S.rotate(self.d, "a1", rec["id"], GATE, self.panel, now=due, how="now")
            self.assertEqual(res, "busy")
        finally:
            S._inflight.discard(key)
        S.delete(self.d, "a1", rec["id"])
        self.assertNotIn(rec["id"], S.load(self.d, "a1")["lines"])


class TestUndo(Base):
    """«تراجع»: يعيد الاسم القديم على اللوحة ويعيد الجزء كما كان."""

    def rotated_now(self):
        rec, _ = self.reg()
        r, res = S.rotate(self.d, "a1", rec["id"], GATE, self.panel, now=T0 + datetime.timedelta(minutes=4), how="now")
        self.assertEqual(res, "ok")
        return rec, r

    def test_undo_restores_name_and_slice(self):
        rec, r = self.rotated_now()
        self.assertNotEqual(r["username"], "111122223333")
        u, res = S.undo(self.d, "a1", rec["id"], GATE, self.panel, now=T0 + datetime.timedelta(minutes=5))
        self.assertEqual(res, "ok")
        self.assertEqual(self.panel.lines, {"111122223333": "999988887777"}, "اللوحة عادت إلى الاسم القديم")
        self.assertEqual((u["state"], u["username"], u["password"]), (S.ACTIVE, "111122223333", "999988887777"))
        self.assertEqual(u["slice"]["due"], rec["slice"]["due"], "الجزء عاد بموعده نفسه")
        self.assertEqual(u["history"], [])
        n = S.load(self.d, "a1")["notes"][0]
        self.assertEqual((n["kind"], n["read"], n["mail"]), ("undo", True, "skip"))
        # ويسير بعدها كأن شيئًا لم يكن: يتغيّر في موعده
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=S.parse_dt(rec["slice"]["due"]))
        self.assertEqual(self.rec(rec["id"])["state"], S.AVAILABLE)

    def test_panel_already_reverted_by_hand(self):
        rec, r = self.rotated_now()
        self.panel.lines = {"111122223333": "999988887777"}         # المشغّل أعاده من اللوحة بيده
        u, res = S.undo(self.d, "a1", rec["id"], GATE, self.panel, now=T0 + datetime.timedelta(minutes=5))
        self.assertEqual((res, u["username"]), ("ok", "111122223333"))

    def test_only_an_unsold_available_line(self):
        rec, r = self.rotated_now()
        S.sell(self.d, "a1", rec["id"], 3, now=T0 + datetime.timedelta(minutes=5))
        u, res = S.undo(self.d, "a1", rec["id"], GATE, self.panel, now=T0 + datetime.timedelta(minutes=6))
        self.assertEqual(res, "skip", "بِيع بعد التغيير — التراجع يقطع العميل الجديد")
        fresh, _ = self.reg(user="100000000009")
        _u, res = S.undo(self.d, "a1", fresh["id"], GATE, self.panel, now=T0)
        self.assertEqual(res, "skip", "لا تغيير يُتراجع عنه")

    def test_past_due_slice_comes_back_waiting(self):
        """التراجع عن تغييرٍ في موعده: الجزء انتهى — يعود «حان التغيير» لا «يجري»، وإلا
        غيّرته الدورة التالية فورًا."""
        rec, _ = self.reg()
        due = S.parse_dt(rec["slice"]["due"])
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due)
        u, res = S.undo(self.d, "a1", rec["id"], GATE, self.panel, now=due + datetime.timedelta(hours=1))
        self.assertEqual((res, u["state"]), ("ok", S.DUE))
        calls = len(self.panel.calls)
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due + datetime.timedelta(hours=2))
        self.assertEqual(len(self.panel.calls), calls)

    def test_failure_keeps_line_and_says_why(self):
        rec, r = self.rotated_now()
        self.panel.fail = S.Unsupported("اللوحة تقفل حقل اسم المستخدم")
        u, res = S.undo(self.d, "a1", rec["id"], GATE, self.panel, now=T0 + datetime.timedelta(minutes=5))
        self.assertEqual(res, "failed")
        cur = self.rec(rec["id"])
        self.assertEqual((cur["state"], cur["username"]), (S.AVAILABLE, r["username"]))
        self.assertIn("تعذّر التراجع", cur["last_error"])


class TestResell(Base):
    def rotated(self, months=6):
        rec, _ = self.reg(months=months)
        due = S.parse_dt(rec["slice"]["due"])
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due)
        return self.rec(rec["id"]), due

    def test_sell_again_then_rotate_again(self):
        r, due = self.rotated()
        self.assertEqual(S.decorate(r, due)["can_sell"], [6, 3, 1])
        r = S.sell(self.d, "a1", r["id"], 6, customer="أبو محمد", now=due)
        self.assertEqual(r["state"], S.ACTIVE)
        self.assertEqual(r["slice"]["n"], 2)
        due2 = S.parse_dt(r["slice"]["due"])
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due2)
        r = self.rec(r["id"])
        self.assertEqual(r["state"], S.AVAILABLE)
        self.assertEqual(S.decorate(r, due2)["remaining_months"], 3)
        self.assertEqual(S.decorate(r, due2)["can_sell"], [3, 1])
        with self.assertRaises(ValueError):
            S.sell(self.d, "a1", r["id"], 6, now=due2)
        # جزء الثلاثة الأخير يبلغ نهاية الخط: بيعُ المتبقي، لا تغيير بعده
        r = S.sell(self.d, "a1", r["id"], 3, now=due2)
        self.assertEqual(r["state"], S.SOLD_OUT)
        calls = len(self.panel.calls)
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due2 + datetime.timedelta(days=100))
        self.assertEqual(len(self.panel.calls), calls)
        self.assertEqual(self.rec(r["id"])["state"], S.ENDED)
        self.assertEqual(len(self.rec(r["id"])["history"]), 2)

    def test_sell_twelve_when_it_fits(self):
        """بعد جزء شهرٍ يبقى ١٤: تُعرض ١٢ بين أنواع البيع، وبيعها يترك شهرين بعدها."""
        r, due = self.rotated(months=1)
        self.assertEqual(S.decorate(r, due)["can_sell"], [12, 6, 3, 1])
        r = S.sell(self.d, "a1", r["id"], 12, customer="عميل السنة", now=due)
        self.assertEqual((r["state"], r["slice"]["months"]), (S.ACTIVE, 12))
        self.assertEqual(S.decorate(r, due)["remaining_after"], 2)

    def test_sell_any_months_that_fit(self):
        """«مدة أخرى» عند البيع: أي أشهرٍ كاملة يتّسع لها المتبقي (٨ من ٩)، وحدّها max_sell."""
        r, due = self.rotated()                      # بعد جزء ستة: يبقى تسعة
        self.assertEqual((S.decorate(r, due)["can_sell"], S.decorate(r, due)["max_sell"]), ([6, 3, 1], 9))
        for bad in (10, -2, "x"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                S.sell(self.d, "a1", r["id"], bad, now=due)
        r = S.sell(self.d, "a1", r["id"], "٨", customer="عميل الثمانية", now=due)
        self.assertEqual((r["state"], r["slice"]["months"]), (S.ACTIVE, 8))
        self.assertEqual(S.decorate(r, due)["remaining_after"], 1)

    def test_sell_remainder(self):
        r, due = self.rotated()
        r = S.sell(self.d, "a1", r["id"], 0, now=due)
        self.assertEqual(r["state"], S.SOLD_OUT)
        self.assertEqual(r["slice"]["months"], 9)

    def test_only_available_sells(self):
        rec, _ = self.reg()
        with self.assertRaises(ValueError):
            S.sell(self.d, "a1", rec["id"], 6, now=T0)

    def test_unsold_expires(self):
        r, due = self.rotated()
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due + datetime.timedelta(days=400))
        self.assertEqual(self.rec(r["id"])["state"], S.ENDED)


class TestMail(Base):
    def test_one_digest_no_password(self):
        a, _ = self.reg(user="111111111111")
        b, _ = self.reg(user="222222222222")
        m = Mailer()
        due = T0 + datetime.timedelta(days=182)
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due, mailer=m,
                  page_url="https://admin.ssouq.com/remaining")
        self.assertEqual(len(m.sent), 1, "بريدٌ واحد يجمع الخطين")
        subject, body = m.sent[0]
        self.assertIn("تغيّرت بياناتها 2", subject)
        self.assertIn("111111111111", body)
        self.assertIn("متبقي 9 أشهر", body)
        self.assertIn("https://admin.ssouq.com/remaining", body)
        self.assertNotIn("999988887777", body, "لا كلمة مرور في البريد")
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due + datetime.timedelta(hours=1), mailer=m)
        self.assertEqual(len(m.sent), 1, "لا يُعاد ما أُرسل")

    def test_sale_logged_quietly(self):
        """بيع جزءٍ يُسجَّل في قائمة الإشعارات (ليظهر أن الخط متابَع) — مقروءًا، فلا
        يرفع العدّاد، ولا بريد له: المشغّل هو من باع."""
        rec, _ = self.reg()
        notes = S.load(self.d, "a1")["notes"]
        self.assertEqual([(n["kind"], n["read"], n["mail"]) for n in notes], [("sold", True, "skip")])
        self.assertIn("يتغيّر اسم المستخدم 2027-03-28 14:30", notes[0]["text"])
        self.assertIn("متبقي 9 أشهر", notes[0]["text"])
        self.assertEqual(S.unread(S.load(self.d, "a1")), 0)
        m = Mailer()
        S.flush_mail(self.d, "a1", m, now=T0)
        self.assertEqual(m.sent, [])

    def test_failed_mail_retries_then_gives_up(self):
        self.reg()
        m = Mailer(ok=False)
        due = T0 + datetime.timedelta(days=182)
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due, mailer=m)
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due + datetime.timedelta(minutes=5), mailer=m)
        self.assertEqual(len(m.sent), 1, "لا إعادة قبل نصف ساعة")
        for i in range(1, 8):
            S.process(self.d, "a1", {"g1": GATE}, self.panel,
                      now=due + datetime.timedelta(minutes=31 * i), mailer=m)
        self.assertEqual(len(m.sent), S.MAIL_MAX_FAILS)
        self.assertTrue(all(n["mail"] in ("failed", "skip") for n in S.load(self.d, "a1")["notes"]))
        self.assertTrue(any(n["mail"] == "failed" for n in S.load(self.d, "a1")["notes"]))

    def test_unconfigured_mail_waits_a_day(self):
        """البريد غير مضبوط لحظة الإشعار: ينتظر الإشعار يومًا — فضبطُ البريد بعده بقليل
        يُوصله — ثم يبقى في الأداة وحدها (لا سيلَ إشعاراتٍ قديمة يوم يُضبط)."""
        rec, _ = self.reg()
        due = S.parse_dt(rec["slice"]["due"])
        none = lambda s, b: (None, "بريد التذكير غير مضبوط")
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due, mailer=none)
        db = S.load(self.d, "a1")
        self.assertEqual([n["mail"] for n in db["notes"] if n["kind"] == "rotated"], ["pending"])
        self.assertEqual(S.unread(db), 1)
        m = Mailer()                                              # ضُبط البريد بعد ساعة
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due + datetime.timedelta(hours=1), mailer=m)
        self.assertEqual(len(m.sent), 1)
        self.assertIn("تغيّرت بياناتها 1", m.sent[0][0])

    def test_mail_configured_minutes_later_goes_next_cycle(self):
        """لا انتظارَ نصف ساعة بعد ضبط البريد: فحصُ الضبط لا يكلّف شيئًا، فيُعاد كل دورة."""
        rec, _ = self.reg()
        due = S.parse_dt(rec["slice"]["due"])
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due, mailer=lambda s, b: (None, "غير مضبوط"))
        m = Mailer()
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due + datetime.timedelta(minutes=5), mailer=m)
        self.assertEqual(len(m.sent), 1)

    def test_verified_mail_clears_old_errors_and_retry_wait(self):
        rec, _ = self.reg()
        due = S.parse_dt(rec["slice"]["due"])
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due, mailer=Mailer(ok=False))
        self.assertTrue(S.load(self.d, "a1")["mail"]["next_try"])
        S.mail_verified(self.d, "a1")                          # بريدٌ تجريبي نجح
        mail = S.load(self.d, "a1")["mail"]
        self.assertEqual((mail["last_error"], mail["next_try"], mail["fails"]), ("", "", 0))
        m = Mailer()
        S.flush_mail(self.d, "a1", m, now=due + datetime.timedelta(minutes=1))
        self.assertEqual(len(m.sent), 1, "المنتظر يُرسَل فورًا لا بعد نصف ساعة")

    def test_unconfigured_for_a_day_then_dropped(self):
        rec, _ = self.reg()
        due = S.parse_dt(rec["slice"]["due"])
        none = lambda s, b: (None, "بريد التذكير غير مضبوط")
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due, mailer=none)
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due + datetime.timedelta(hours=25), mailer=none)
        m = Mailer()
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due + datetime.timedelta(hours=26), mailer=m)
        self.assertEqual(m.sent, [], "إشعار الأمس لا يُرسَل اليوم")
        self.assertTrue(all(n["mail"] == "skip" for n in S.load(self.d, "a1")["notes"]))

    def test_mail_hints(self):
        self.assertIn("كلمة مرور التطبيقات", S.mail_hint("(535, b'5.7.8 Username and Password not accepted')"))
        self.assertIn("465", S.mail_hint("[SSL: WRONG_VERSION_NUMBER] wrong version number (_ssl.c:1006)"))
        self.assertIn("اسم خادم", S.mail_hint("[Errno -2] Name or service not known"))
        self.assertIn("المنفذ الآخر", S.mail_hint("timed out"))
        self.assertEqual(S.mail_hint(""), "")
        self.assertEqual(S.mail_hint("بريد التذكير غير مضبوط"), "")


class TestNotes(Base):
    def test_unread_and_mark(self):
        rec, _ = self.reg()
        due = S.parse_dt(rec["slice"]["due"])
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due - datetime.timedelta(days=1))
        S.process(self.d, "a1", {"g1": GATE}, self.panel, now=due)
        db = S.load(self.d, "a1")
        self.assertEqual(S.unread(db), 2)
        S.mark_read(self.d, "a1", [db["notes"][0]["id"]])
        self.assertEqual(S.unread(S.load(self.d, "a1")), 1)
        S.mark_read(self.d, "a1")
        self.assertEqual(S.unread(S.load(self.d, "a1")), 0)


class TestDates(unittest.TestCase):
    def test_panel_expiry_formats(self):
        self.assertEqual(S.to_date("2027-12-25 22:54"), datetime.date(2027, 12, 25))
        self.assertEqual(S.to_date("2027-12-31"), datetime.date(2027, 12, 31))
        self.assertEqual(S.to_date("31-12-2027"), datetime.date(2027, 12, 31))
        self.assertIsNotNone(S.to_date(1830000000))
        self.assertIsNone(S.to_date("—"))

    def test_month_end(self):
        self.assertEqual(S.add_months_dt(datetime.datetime(2026, 8, 31, 10, 0), 6),
                         datetime.datetime(2027, 2, 28, 10, 0))

    def test_months_ar(self):
        self.assertEqual(S.months_ar(9), "9 أشهر")
        self.assertEqual(S.months_ar(12), "12 شهرًا")
        self.assertEqual(S.months_ar(1), "شهر")


if __name__ == "__main__":
    unittest.main(verbosity=1)

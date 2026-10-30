#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبار تصدير الحسابات البديلة للمتجر (panels.replacements_export): المفقود والمكرر وتغيير اسم القديم لصاحبه الأول
وروابط user_links، بطلب كلٍّ منها وكلمة مرور البديل وهوسته، وطلبٌ لا يُعرف لا يُصدَّر بطلب.

تشغيل:  python tests/test_replacements.py
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import panels  # noqa: E402

_p = _f = 0


def check(label, cond, extra=""):
    global _p, _f
    if cond:
        _p += 1
        print(f"  \033[32mPASS\033[0m  {label}")
    else:
        _f += 1
        print(f"  \033[31mFAIL\033[0m  {label}  {extra}")


def write(d, name, obj):
    with open(os.path.join(d, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def main():
    d = tempfile.mkdtemp()
    try:
        write(d, "renew_store_lines.json", {"lines": [
            {"order": "100", "date": "2026-01-01", "phone": "0500000001", "customer": "أ", "username": "111", "password": "p1", "host": "http://old.x"},
            {"order": "200", "date": "2026-02-01", "phone": "0500000002", "customer": "ب", "username": "222", "password": "p2", "host": "http://old.x"},
            {"order": "300", "date": "2026-03-01", "phone": "0500000003", "customer": "ج", "username": "222", "password": "p2", "host": "http://old.x"},
            {"order": "400", "date": "2026-04-01", "phone": "0500000004", "customer": "د", "username": "444", "password": "p4", "host": "http://old.x"},
            {"order": "400", "date": "2026-04-01", "phone": "0500000004", "customer": "د", "username": "4444", "password": "np4", "host": "http://new.x", "linked": "2026-05-01"},
            {"order": "500", "date": "2026-05-01", "phone": "0500000005", "username": "555", "password": "p5"},
            {"order": "600", "date": "2026-05-02", "phone": "0500000006", "username": "555", "password": "p5"},
        ]})
        write(d, "renew_panel_lines.json", {"panels": {"m": {"by_user": {"9111": {"username": "9111", "password": "pp", "exp": "2027-01-01 00:00"}}}}})
        write(d, "renew_dupes_done.json", {
            "100": {"new": "9111", "months": 6, "src": "lost", "old": "111", "host": "http://new.x", "at": "2026-06-01"},
            "300": {"new": "9222", "months": 3, "src": "dup", "old": "222", "password": "np2", "host": "http://new.x",
                    "renamed": {"from": "222", "to": "8222"}, "at": "2026-06-02"},
        })
        links = [{"old": "444", "new": "4444", "at": "2026-05-01", "host": "http://new.x"},
                 {"old": "555", "new": "5555", "at": "2026-05-03", "host": "http://new.x"},
                 {"old": "222", "new": "8222", "at": "2026-06-02", "host": "http://old.x", "package": "تغيير اسم (مكرر)"}]
        out = panels.replacements_export(d, links)
        rows = {(r["order"], r["old"]): r for r in out["rows"]}
        check("نوع الملف", out["kind"] == "ssouq-replacements" and out["count"] == len(out["rows"]))
        lost = rows.get(("100", "111")) or {}
        check("المفقود: البديل وكلمة مروره من يوزرات اللوحة وانتهاؤه", lost.get("new") == "9111" and lost.get("password") == "pp" and lost.get("expiry") == "2027-01-01" and lost.get("kind") == "lost", lost)
        dup = rows.get(("300", "222")) or {}
        check("المكرر: للطلب الثاني بكلمة مرور البديل", dup.get("new") == "9222" and dup.get("password") == "np2" and dup.get("kind") == "dup", dup)
        ren = rows.get(("200", "222")) or {}
        check("تغيير اسم القديم المكرر: لطلب صاحبه الأول بكلمة مروره نفسها", ren.get("kind") == "renamed" and ren.get("new") == "8222" and ren.get("password") == "p2" and ren.get("host") == "http://old.x", ren)
        check("رابط التغيير نفسه لا يتكرر", sum(1 for r in out["rows"] if r["new"] == "8222") == 1)
        lk = rows.get(("400", "444")) or {}
        check("بديل البحث: طلبه من خطه المربوط", lk.get("new") == "4444" and lk.get("password") == "np4" and lk.get("host") == "http://new.x", lk)
        amb = rows.get(("", "555")) or {}
        check("يوزر لعميلين: بلا طلب ومعه الطلبات المحتملة", amb.get("orders") == ["500", "600"], amb)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print(f"\n{_p} نجح، {_f} فشل")
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

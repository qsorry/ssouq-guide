#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبار users_export: السحب الكامل، الإضافة عند الإنشاء، وصحّة ملف xlsx — بلا شبكة."""
import io
import os
import sys
import shutil
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import users_export  # noqa: E402

_p = _f = 0


def check(label, cond, extra=""):
    global _p, _f
    if cond:
        _p += 1
        print("  \033[32mPASS\033[0m  " + label + (("  (%s)" % extra) if extra else ""))
    else:
        _f += 1
        print("  \033[31mFAIL\033[0m  " + label + (("  (%s)" % extra) if extra else ""))


def _sheet_text(xlsx_path):
    with zipfile.ZipFile(xlsx_path) as z:
        return z.read("xl/worksheets/sheet1.xml").decode("utf-8")


def main():
    d = tempfile.mkdtemp(prefix="uexp_")
    try:
        A, G = "acct1", "gateA"
        panel_rows = [
            {"id": "1", "username": "111111", "password": "aaa", "package": "15 Months",
             "exp": "2027-01-01", "created": "2026-01-01", "connections": "0/1"},
            {"id": "2", "username": "222222", "password": "bbb", "package": "1 Year",
             "exp": "2026-12-01", "created": "2026-01-02", "connections": "0/1"},
            {"username": "222222", "password": "dup"},   # مكرر بالاسم → يُتجاهَل في السحب
        ]
        n = users_export.replace_all(d, A, G, "كاسبر", panel_rows, host="http://h:80")
        check("replace_all dedupes by username", n == 2, "n=%d" % n)

        jsonl, xlsx = users_export.paths(d, A, G)
        check("jsonl + xlsx files written", os.path.exists(jsonl) and os.path.exists(xlsx))

        st = users_export.status(d, A, G)
        check("status: exists + count", st["exists"] and st["count"] == 2, str(st))

        rows = users_export.load(jsonl)
        check("host filled from gate when row lacks it", rows[0]["host"] == "http://h:80", rows[0]["host"])

        # ملف xlsx صالح: zip فيه ورقةٌ تحوي اليوزر والرأس العربي
        sx = _sheet_text(xlsx)
        check("xlsx is a valid zip with the username inside", "111111" in sx and "اليوزر" in sx)

        # الإضافة عند الإنشاء: يوزرٌ جديد يُضاف في آخره، ولا يُكرَّر
        created = [{"username": "333333", "password": "ccc", "package": "15 Months", "exp": "2027-06-01"}]
        n2 = users_export.merge(d, A, G, "كاسبر", created, host="http://h:80")
        check("merge appends new user", n2 == 3, "n=%d" % n2)
        rows2 = users_export.load(jsonl)
        check("new user is last (order preserved)", rows2[-1]["username"] == "333333", rows2[-1]["username"])

        # الإضافة لا تدهس قيمةً موجودةً بفراغ، وتحدّث الموجود بمكانه
        upd = [{"username": "111111", "password": "NEWPASS"}]  # بلا exp → لا يُمسح exp القديم
        users_export.merge(d, A, G, "كاسبر", upd)
        rows3 = users_export.load(jsonl)
        r1 = next(r for r in rows3 if r["username"] == "111111")
        check("merge updates in place (password) and keeps position",
              r1["password"] == "NEWPASS" and rows3[0]["username"] == "111111", str(r1)[:80])
        check("merge does not overwrite existing exp with blank", r1["exp"] == "2027-01-01", r1["exp"])
        check("merge did not add a duplicate row", len(rows3) == 3, "len=%d" % len(rows3))

        # عزل البوابات: بوابةٌ أخرى ملفٌّ مستقل
        users_export.replace_all(d, A, "gateB", "مرح", [{"username": "999", "password": "z"}])
        check("separate file per gate", users_export.status(d, A, "gateB")["count"] == 1
              and users_export.status(d, A, G)["count"] == 3)

        # لا ملف بعد لبوابةٍ لم تُسحب
        check("status false before any pull", users_export.status(d, A, "gateC")["exists"] is False)
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print("\n----------------------------------------")
    print("Result: \033[32m%d passed\033[0m, %s" % (_p, ("\033[31m%d failed\033[0m" % _f) if _f else "0 failed"))
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

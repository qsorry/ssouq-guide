#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ربط اليوزر القديم بالجديد عند الاستبدال — تتبّع الاتجاهين."""
import os
import sys
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import user_links  # noqa: E402

_p = _f = 0


def check(label, cond, extra=""):
    global _p, _f
    if cond:
        _p += 1
        print("  \033[32mPASS\033[0m  " + label + (("  (%s)" % extra) if extra else ""))
    else:
        _f += 1
        print("  \033[31mFAIL\033[0m  " + label + (("  (%s)" % extra) if extra else ""))


def main():
    d = tempfile.mkdtemp(prefix="ulinks_")
    A, G = "acc1", "gateA"
    try:
        user_links.add(d, A, G, "1111", "2222", "15 شهرًا")
        user_links.add(d, A, G, "2222", "3333", "سنة")   # سلسلة استبدال

        old = user_links.find(d, A, G, "1111")
        check("query old → replaced_by new", len(old) == 1 and old[0]["direction"] == "replaced_by"
              and old[0]["new"] == "2222", str(old))
        new = user_links.find(d, A, G, "3333")
        check("query new → replacement_of old", len(new) == 1 and new[0]["direction"] == "replacement_of"
              and new[0]["old"] == "2222", str(new))
        mid = user_links.find(d, A, G, "2222")
        check("middle of a chain shows both directions", len(mid) == 2
              and {m["direction"] for m in mid} == {"replaced_by", "replacement_of"}, str(mid))
        check("package carried on the link", old[0].get("package") == "15 شهرًا", old[0].get("package"))

        check("unknown query → no links", user_links.find(d, A, G, "9999") == [])
        check("empty query → []", user_links.find(d, A, G, "") == [])

        # حراسة: لا يُسجَّل فارغٌ أو مطابق
        check("add ignores empty old", user_links.add(d, A, G, "", "x") is None)
        check("add ignores same old==new", user_links.add(d, A, G, "5", "5") is None)

        # عزل: بوابةٌ أخرى لا ترى روابط الأولى
        check("per-gate isolation", user_links.find(d, A, "gateB", "1111") == [])
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print("\n----------------------------------------")
    print("Result: \033[32m%d passed\033[0m, %s" % (_p, ("\033[31m%d failed\033[0m" % _f) if _f else "0 failed"))
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

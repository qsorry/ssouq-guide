#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
يبني فهرس طلبات التجديد من ملفات سلة المصدَّرة، من سطر الأوامر.

    python tools/build_renew_index.py exports/                     # كل CSV في المجلد
    python tools/build_renew_index.py orders.csv --products products.csv
    python tools/build_renew_index.py exports/ --report tahlil.html # تحليل كصفحة

نفس ما تفعله صفحةُ الرفع في لوحة الإدارة — كلاهما ينادي `renew_import`، فلا
يفترق رقمٌ بين الطريقين.
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import renew                                                  # noqa: E402
import renew_import                                           # noqa: E402


def expand(paths):
    out = []
    for p in paths:
        if os.path.isdir(p):
            out += sorted(glob.glob(os.path.join(p, "**", "*.csv"), recursive=True))
        else:
            out += sorted(glob.glob(p))
    return out


def load(paths):
    files = []
    for f in expand(paths):
        try:
            files.append((os.path.basename(f), open(f, "rb").read()))
        except OSError as e:
            print("  تعذّرت قراءة %s: %s" % (f, e), file=sys.stderr)
    return files


def main():
    ap = argparse.ArgumentParser(description="فهرس وتحليل طلبات التجديد")
    ap.add_argument("paths", nargs="+", help="ملفات الطلبات (CSV) أو مجلدات تحويها")
    ap.add_argument("--products", nargs="*", default=[], help="ملف المنتجات (اختياري)")
    ap.add_argument("--out", default=None, help="مسار الفهرس (الافتراضي data/renew_index.json)")
    ap.add_argument("--report", default=None, help="يكتب التحليل صفحةَ HTML في هذا المسار")
    ap.add_argument("--keep-unconfirmed", action="store_true", help="يُبقي الملغي وغير المدفوع")
    ap.add_argument("--include-falcon", action="store_true", help="يُبقي طلبات فالكون")
    a = ap.parse_args()

    data_dir = os.environ.get("XM_DATA") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    out = a.out or renew.index_path(data_dir)

    products = renew_import.read_products(load(a.products)) if a.products else None
    units, meta = renew_import.read_orders(load(a.paths), products,
                                           a.keep_unconfirmed, a.include_falcon)
    if not units:
        print("لم يُقرأ أي طلب صالح — تأكّد أن الملفات تصدير طلبات سلة.", file=sys.stderr)
        for b in meta.get("bad_files", []):
            print("  %s: %s" % (b["file"], b["error"]), file=sys.stderr)
        return 1

    idx = renew_import.build_index(units, meta)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False)
    os.replace(tmp, out)

    agg = renew_import.analyze(units, meta)
    sk = meta["skipped"]
    print("ملفات: %d مقروءة، %d متطابقة حُذفت" % (meta["files_kept"], meta["files_dup"]))
    print("طلبات: %d فريدة، %d مكررة حُذفت" % (meta["orders"], meta["orders_dup"]))
    print("استُبعد: %d غير مؤكد · %d فالكون · %d بلا مدة · %d بلا تاريخ"
          % (sk["unconfirmed"], sk["falcon"], sk["no_months"], sk["no_date"]))
    print("يوزرات: %d إجمالًا · %d سارية · %d عميلًا فريدًا"
          % (agg["units"]["all"], agg["units"]["active"], agg["units"]["phones_active"]))
    print("\n✓ الفهرس: %s" % out)

    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            f.write(renew_import.report_html(agg))
        print("✓ التحليل: %s" % a.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

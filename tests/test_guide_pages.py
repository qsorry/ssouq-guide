#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""صفحات الدليل الثابتة: الأجهزة و/compare.

يفحص ما يسهل أن ينكسر صامتًا: صفحة جهاز تسقط، رابط منتج يشير إلى مفتاح
غير موجود في PRODUCTS، مخطط FAQ يخرج JSON غير صالح، أو صفحة تُضاف إلى
PAGES ولا تدخل خريطة الموقع.

تشغيل:  python tests/test_guide_pages.py
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import guide_pages as G  # noqa: E402

_p = _f = 0


def check(l, c, x=""):
    global _p, _f
    print((f"  \033[32mPASS\033[0m  {l}" if c else f"  \033[31mFAIL\033[0m  {l}") + (f"  ({x})" if x else ""))
    _p += 1 if c else 0
    _f += 0 if c else 1


def main():
    global _f

    print("صفحات الأجهزة")
    for path, meta in G.PAGES.items():
        if meta.get("compare"):
            continue
        raw = G.render(path)
        check(f"{path} تُصيَّر", bool(raw) and len(raw) > 2000)
        h = raw.decode("utf-8") if raw else ""
        check(f"{path} فيها h1 والعنوان", f"<h1>" in h and meta["title"] in h)
        check(f"{path} canonical صحيح", f'rel="canonical" href="{G.SITE}{path}"' in h)

    print("\nكل مفاتيح المنتجات معرَّفة")
    # مفتاح ناقص يرفع KeyError وقت الطلب لا وقت النشر — أي 500 على صفحة حيّة.
    for path, meta in G.PAGES.items():
        for pid in list(meta.get("products", [])):
            check(f"{path} → {pid}", pid in G.PRODUCTS)
    for row in G.COMPARE_ROWS:
        for pid in row[2]:
            check(f"COMPARE_ROWS → {pid}", pid in G.PRODUCTS)
    for _, prods in G.COMPARE_CONTENT:
        for pid in prods:
            check(f"COMPARE_CONTENT → {pid}", pid in G.PRODUCTS)

    print("\nصفحة المقارنة")
    raw = G.render("/compare")
    check("/compare تُصيَّر", bool(raw) and len(raw) > 5000)
    h = raw.decode("utf-8")
    blocks = re.findall(r'application/ld\+json">(.*?)</script>', h, re.S)
    check("كتلتا JSON-LD", len(blocks) == 2, f"وجدت {len(blocks)}")
    types = []
    for b in blocks:
        try:
            types.append(json.loads(b).get("@type"))
        except Exception as e:
            check("JSON-LD صالح", False, str(e)[:60])
    check("BreadcrumbList + FAQPage", set(types) == {"BreadcrumbList", "FAQPage"}, str(types))
    faq = next((json.loads(b) for b in blocks if '"FAQPage"' in b), None)
    check("عدد الأسئلة يطابق المصدر",
          faq and len(faq["mainEntity"]) == len(G.COMPARE_FAQ))
    # المصدر واحد: لو انحرف النص المرئي عن المخطط صار أحدهما يَعِد بما لا يقوله الآخر.
    check("نص كل سؤال ظاهر للزائر أيضًا",
          all(q in h for q, _ in G.COMPARE_FAQ))
    check("تحيل إلى مقال المتجر ولا تعيد نصّه", G.BLOG_COMPARE in h)
    check("تربط كل صفحات الأجهزة",
          all(f'href="{p}"' in h for p in G.PAGES if not G.PAGES[p].get("compare")))

    print("\nخريطة الموقع")
    sm = G.sitemap().decode("utf-8")
    for path in G.PAGES:
        check(f"{path} في المخطط", f"<loc>{G.SITE}{path}</loc>" in sm)
    check("المخطط XML صالح الشكل",
          sm.startswith("<?xml") and sm.rstrip().endswith("</urlset>"))

    print(f"\n{_p} نجح · {_f} فشل")
    return 1 if _f else 0


if __name__ == "__main__":
    sys.exit(main())

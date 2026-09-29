#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""صفحات الدليل الثابتة: الأجهزة و/compare.

يفحص ما يسهل أن ينكسر صامتًا: صفحة جهاز تسقط، رابط منتج يشير إلى مفتاح
غير موجود في PRODUCTS، مخطط FAQ يخرج JSON غير صالح، صفحة تُضاف إلى
PAGES ولا تدخل خريطة الموقع، صورة خطوة ليست على القرص، أو guide-data.json
نُسي بعد تعديل المعالج فبقيت الصفحات على القديم.

تشغيل:  python tests/test_guide_pages.py
"""
import json
import os
import re
import shutil
import subprocess
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

    print("\nصور الخطوات على القرص")
    # الصورة تُكتب نصًّا في index.html، فالناقصة لا يكشفها إلا من يفتح خطوتها
    data = G._data()
    srcs = set()
    for dev in data.values():
        for steps in ([dev["steps"]] if "steps" in dev else dev["variants"].values()):
            for st in steps:
                srcs.update([st["img"]] if st.get("img") else [])
                srcs.update(re.findall(r'(?:src|poster)="(/static/[^"?]+)', st.get("html", "")))   # ?v= لا يدخل في اسم الملف
        srcs.update(f"/static/img/apps/{o['icon']}.webp"
                    for o in dev.get("choose", {}).get("options", []) if o.get("icon"))
    missing = sorted(p for p in srcs if not os.path.isfile(os.path.join(ROOT, p.lstrip("/"))))
    check(f"كل الصور ({len(srcs)}) موجودة", not missing, ", ".join(missing[:4]))

    print("\nSS IPTV و VIDAA")
    v, w = data["vidaa"], data["webos"]
    check("VIDAA جهاز بخطوات SS IPTV السبع", len(v.get("steps", [])) == 7
          and v["steps"][0]["title"] == "حمّل تطبيق SS IPTV من متجر VIDAA")
    check("سامسونج و LG: اختيار 0Player أو SS IPTV",
          [o["key"] for o in w["choose"]["options"]] == ["0player", "ssiptv"])
    # التحميل وحده يختلف بين الجهازين، وما بعده خطوات واحدة
    check("خطوات SS IPTV بعد التحميل واحدة على الجهازين", w["variants"]["ssiptv"][1:] == v["steps"][1:])
    video = re.compile(r'^<div class="vid"><video src="/static/video/ssiptv-ar\.mp4\?v=(\d+)" poster="/static/video/ssiptv-ar\.webp\?v=\1"')
    check("فيديو الخطوات أول خطوة التحميل في المسارين، بإصدارٍ واحد للفيديو وغلافه",
          bool(video.match(v["steps"][0]["html"])) and bool(video.match(w["variants"]["ssiptv"][0]["html"])))

    print("\n0Player بطريقتين")
    z = w["variants"]["0player"]
    forks = [st for st in z if st.get("fork")]
    check("ست خطوات، وتفرّعٌ إلى طريقتين كلتاهما «الخطوة 5» وتنتهيان إلى الأخيرة",
          len(z) == 7 and len(forks) == 1 and [o["to"] for o in forks[0]["fork"]] == [4, 5]
          and all(z[k].get("num") == 5 and z[k].get("next") == 6 for k in (4, 5)) and z[6].get("num") == 6)
    zv = re.compile(r'<video src="/static/video/0player-92929480-ar\.mp4\?v=(\d+)" poster="/static/video/0player-92929480-ar\.webp\?v=\1"')
    check("فيديو 0Player أول خطوة التحميل، واسمه يحمل رمز سمارت", bool(zv.search(z[0]["html"])))
    check("ولفالكون فيديوه وصوره باسم رمزه (يشتقّها المعالج بتبديل الرمز)",
          all(os.path.isfile(os.path.join(ROOT, p)) for p in (
              "static/video/0player-75710072-ar.mp4", "static/video/0player-75710072-ar.webp",
              "static/img/webos-0player-portal-75710072.webp", "static/img/webos-0player-web-75710072.webp")))
    h = G.render("/vidaa").decode("utf-8")
    check("/vidaa تربط محرّر ss-iptv.com وأداة M3U",
          'href="https://ss-iptv.com/en/users/playlist"' in h and 'href="/#m3u"' in h)
    # كصفحتي منتج كاسبر في المتجر: لا يعمل على VIDAA، فلا تقول الصفحة «لكل الاشتراكات»
    check("/vidaa لسمارت وفالكون، وكاسبر لا يعمل عليها",
          "لكل الاشتراكات" not in h and "سمارت أو فالكون، أما كاسبر فلا يعمل على هذه الشاشات" in h)
    h = G.render("/samsung-lg").decode("utf-8")
    check("/samsung-lg فيها التطبيقان", "تطبيق 0Player" in h and "تطبيق SS IPTV" in h)

    print("\nguide-data.json على آخر المعالج")
    node = shutil.which("node")
    if node:
        r = subprocess.run([node, os.path.join(ROOT, "tools", "sync_guide_data.js"), "--check"],
                           capture_output=True, text=True, timeout=60)
        check("مطابق لـ index.html", r.returncode == 0, (r.stdout or r.stderr).strip()[:90])
    else:
        print("  تخطّي: لا node على هذا الجهاز")

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

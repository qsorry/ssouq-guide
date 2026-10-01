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
    vs = v["variants"]["ssiptv"]
    check("VIDAA: اختيار SS IPTV أو Duplecast", [o["key"] for o in v["choose"]["options"]] == ["ssiptv", "duplecast"])
    check("VIDAA بخطوات SS IPTV السبع", len(vs) == 7 and vs[0]["title"] == "حمّل تطبيق SS IPTV من متجر VIDAA")
    check("سامسونج و LG: اختيار 0Player أو Duplecast أو SS IPTV",
          [o["key"] for o in w["choose"]["options"]] == ["0player", "duplecast", "ssiptv"])
    # التحميل وحده يختلف بين الجهازين، وما بعده خطوات واحدة
    check("خطوات SS IPTV بعد التحميل واحدة على الجهازين", w["variants"]["ssiptv"][1:] == vs[1:])
    video = re.compile(r'^<div class="vid"><video src="/static/video/ssiptv-ar\.mp4\?v=(\d+)" poster="/static/video/ssiptv-ar\.webp\?v=\1"')
    check("فيديو الخطوات أول خطوة التحميل في المسارين، بإصدارٍ واحد للفيديو وغلافه",
          bool(video.match(vs[0]["html"])) and bool(video.match(w["variants"]["ssiptv"][0]["html"])))

    print("\nDuplecast (دبل كاست)")
    dw, dv = w["variants"]["duplecast"], v["variants"]["duplecast"]
    check("سبع خطوات على الجهازين، وما بعد التحميل واحد", len(dw) == 7 and len(dv) == 7 and dw[1:] == dv[1:])
    check("التحميل من متجر الشاشة: سامسونج و LG، و VIDAA",
          "Samsung Apps" in dw[0]["html"] and "LG Content Store" in dw[0]["html"] and "VIDAA Store" in dv[0]["html"])
    dvid = re.compile(r'^<div class="vid"><video src="/static/video/duplecast-ar\.mp4\?v=(\d+)" poster="/static/video/duplecast-ar\.webp\?v=\1"')
    check("فيديو Duplecast أول خطوة التحميل في الجهازين، بإصدارٍ واحد للفيديو وغلافه",
          bool(dvid.match(dw[0]["html"])) and bool(dvid.match(dv[0]["html"]))
          and all(os.path.isfile(os.path.join(ROOT, "static/video", f)) for f in ("duplecast-ar.mp4", "duplecast-ar.webp")))
    # السعر يُقال من أول خطوة: 15 يومًا مجانًا ثم 3 دولارات للسنة، أو كود المتجر بـ 16 ريال
    buy = "https://ssouq.com/تفعيل-duplecast-دبل-كاست-لمدة-سنة/p1575092005?"
    check("السعر في خطوة التحميل: 15 يومًا مجانًا، ثم 3 دولارات للسنة، أو كود بـ 16 ريال من المتجر",
          all(x in dw[0]["html"] for x in ("15 يومًا", "3 دولارات للسنة", "16 ريال", buy)))
    last = dw[-1]
    check("آخر خطوة التفعيل: الطريقتان، وزر شراء الكود، و Activate by code",
          "3 دولارات للسنة" in last["title"] and "Activate by Payment" in last["html"]
          and f'<a class="btn go" href="{buy}' in last["html"] and "Activate by code" in last["html"])
    check("الهوست والبورت في خانتين، مع تنبيه http", "Port" in dw[3]["html"] and 'class="note http"' in dw[3]["html"])

    print("\n0Player بطريقتين")
    z = w["variants"]["0player"]
    forks = [st for st in z if st.get("fork")]
    check("ست خطوات، وتفرّعٌ إلى طريقتين كلتاهما «الخطوة 5» وتنتهيان إلى الأخيرة",
          len(z) == 7 and len(forks) == 1 and [o["to"] for o in forks[0]["fork"]] == [4, 5]
          and all(z[k].get("num") == 5 and z[k].get("next") == 6 for k in (4, 5)) and z[6].get("num") == 6)
    zv = re.compile(r'<video src="/static/video/0player-92929480-ar\.mp4\?v=(\d+)" poster="/static/video/0player-92929480-ar\.webp\?v=\1"')
    check("فيديو 0Player أول خطوة التحميل، واسمه يحمل رمز سمارت", bool(zv.search(z[0]["html"])))
    check("ولفالكون وكاسبر فيديوهما وصورهما باسم رمزيهما (يشتقّها المعالج بتبديل الرمز)",
          all(os.path.isfile(os.path.join(ROOT, p.format(c))) for c in ("75710072", "59820658") for p in (
              "static/video/0player-{}-ar.mp4", "static/video/0player-{}-ar.webp",
              "static/img/webos-0player-portal-{}.webp", "static/img/webos-0player-web-{}.webp")))
    check("0Player مجاني: في بطاقة التطبيق وخيار التطبيق", "مجاني · من متجر الشاشة" in z[0]["html"]
          and next(o for o in w["choose"]["options"] if o["key"] == "0player")["sub"].startswith("مجاني "))
    h = G.render("/vidaa").decode("utf-8")
    check("/vidaa تربط محرّر ss-iptv.com وأداة M3U",
          'href="https://ss-iptv.com/en/users/playlist"' in h and 'href="/#m3u"' in h)
    check("/vidaa للاشتراكات الثلاثة", "والاثنان لاشتراكات سمارت وفالكون وكاسبر." in h and "أما كاسبر فلا يعمل" not in h)
    h = G.render("/samsung-lg").decode("utf-8")
    check("/samsung-lg فيها التطبيقات الثلاثة", "تطبيق 0Player" in h and "تطبيق Duplecast" in h and "تطبيق SS IPTV" in h)
    check("/samsung-lg تقول إن 0Player مجاني", "تطبيق 0Player المجاني من متجر الشاشة" in h)
    check("/vidaa فيها التطبيقان", all(x in G.render("/vidaa").decode("utf-8") for x in ("تطبيق SS IPTV", "تطبيق Duplecast")))

    print("\nشاشة أندرويد: Downloader وموافقة الشاشة عليه")
    t = data["tv"]["variants"]
    sm, mr = t["smarters"], t["mr7"]
    # خطوات Downloader (DL_*) واحدة للتطبيقين: الكود والتطبيق وحدهما يختلفان، والفيديو أول Smarters وحده
    check("عشر خطوات لـ Smarters وسبع لـ MR7", len(sm) == 10 and len(mr) == 7, f"{len(sm)} · {len(mr)}")
    check("رسالة الأمان ثم تفعيل Downloader خطوتان واحدتان في التطبيقين",
          sm[1] == mr[1] and sm[3] == mr[3] and sm[4] == mr[4]
          and sm[3]["title"] == "ظهرت رسالة الأمان؟ اضغط «الإعدادات»" and sm[4]["title"] == "فعّل Downloader ثم ارجع")
    check("نص رسالة الأمان كما في ترجمة أندرويد",
          "لأغراض الأمان، غير مسموح حاليًا لجهاز التلفزيون الذي تستخدمه بتثبيت تطبيقات غير معروفة من هذا المصدر" in sm[3]["html"]
          and "تطبيق مسموح به" in sm[4]["html"])
    check("كل تطبيقٍ بصورة كوده ونافذتي تثبيته",
          sm[2]["img"].endswith("tv-dl-code-8744201.webp") and mr[2]["img"].endswith("tv-dl-code-5574841.webp")
          and sm[5]["img"].endswith("tv-dl-install-smarters.webp") and mr[5]["img"].endswith("tv-dl-install-mr7.webp"))
    sv = re.compile(r'^<div class="vid"><video src="/static/video/smarters-tv-ar\.mp4\?v=(\d+)" poster="/static/video/smarters-tv-ar\.webp\?v=\1"')
    check("فيديو Smarters أول خطوة التحميل، ولا فيديو في خطوة MR7", bool(sv.match(sm[0]["html"])) and "<video" not in mr[0]["html"])
    check("الدخول: ADD USER لا ADD PLAYLIST، وخطوته نفسها على الجوال",
          "ADD USER" in sm[9]["html"] and "ADD PLAYLIST" not in sm[9]["html"]
          and data["android"]["variants"]["smarters"][-1] == sm[9])
    # فالكون وكاسبر خارج guide-data.json (سمارت وحده)، فصورهما هنا
    check("صور كود فالكون وكاسبر ونوافذ تثبيتهما على القرص",
          all(os.path.isfile(os.path.join(ROOT, "static/img", f)) for f in (
              "tv-dl-code-1683248.webp", "tv-dl-code-3638997.webp", "tv-dl-install-falcon.webp", "tv-dl-done-falcon.webp",
              "tv-dl-install-casper.webp", "tv-dl-done-casper.webp", "tv-dl-devmode.webp")))
    h = G.render("/android-tv").decode("utf-8")
    check("/android-tv فيها الموافقة والفيديو", "الخطوة 4 — ظهرت رسالة الأمان؟ اضغط «الإعدادات»" in h
          and "/static/video/smarters-tv-ar.mp4" in h and "مرة واحدة فقط" in h)

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

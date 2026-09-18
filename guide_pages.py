# -*- coding: utf-8 -*-
"""صفحات الأجهزة الثابتة — نسخة يقرأها محرك البحث.

المعالج في index.html يبني خطواته بالجافاسكربت، فلا يرى جوجل منها شيئًا.
هذه الوحدة تُصيّر الخطوات نفسها HTML كاملًا على السيرفر، صفحةً لكل جهاز،
من المصدر ذاته (static/guide-data.json) فلا يقع انحراف بين الاثنين.

بعد أي تعديل على خطوات المعالج في index.html شغّل:
    node tools/sync_guide_data.js
"""
import html as _html
import json
import os
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SITE = "https://guide.ssouq.com"
STORE = "https://ssouq.com"
UTM = "?utm_source=guide.ssouq.com&utm_medium=referral&utm_campaign=guide"

# روابط المتجر القانونية — مُتحقَّق منها على المتجر الحيّ (رأس canonical).
# لا تكتب رابطًا هنا دون التأكد من أنه هو الرابط القانوني للمنتج.
PRODUCTS = {
    "p1112367445": ("اشتراك IPTV لمدة 30 شهر", "اشتراك-iptv-30-شهر"),
    "p159938107":  ("اشتراك IPTV لمدة 15 شهر لجهازين", "اشتراك-iptv-smarters-15-شهر"),
    "p1859503976": ("اشتراك IPTV لسامسونج و LG لمدة 12 شهر", "اشتراك-iptv-سامسونج-ال-جي-webos-12-شهر"),
    "p2067729417": ("اشتراك IPTV لسامسونج و LG لمدة 6 أشهر", "اشتراك-iptv-لشاشات-سامسونج-و-lg-لمدة-6-أشهر"),
    "p1205321184": ("اشتراك IPTV لمدة 6 أشهر لجميع الأجهزة", "اشتراك-iptv-لمدة-6-أشهر-جميع-الأجهزة"),
    "p971439862":  ("اشتراك سمارت لمدة سنة", "اشتراك-سمارت-سنه"),
    "p153695876":  ("اشتراك فالكون IPTV لمدة 3 أشهر", "اشتراك-فالكون-iptv-لمدة-3-أشهر-falcon-tv-pro"),
}

# صفحة لكل جهاز: العنوان والوصف مكتوبان لاستعلام بحث واحد واضح.
PAGES = {
    "/samsung-lg": dict(
        device="webos",
        title="طريقة تثبيت IPTV على شاشات سامسونج و LG | سمارت سوق",
        desc="شرح تفعيل اشتراك IPTV على شاشات سامسونج و LG بنظام webOS خطوة بخطوة عبر تطبيق 0Player المجاني أو ORAplayer، بلا رسيفر ولا جهاز إضافي.",
        h1="طريقة تثبيت اشتراك IPTV على شاشات سامسونج و LG",
        intro="شاشات سامسونج و LG تعمل بنظام webOS ولا تقبل تطبيقات أندرويد، فلها تطبيقان خاصان بها. اختر التطبيق ثم اتبع الخطوات بالترتيب، ولا تحتاج رسيفر ولا أي جهاز إضافي.",
        products=["p2067729417", "p1859503976"],
    ),
    "/iphone": dict(
        device="ios",
        title="طريقة تشغيل اشتراك IPTV على الآيفون والآيباد | سمارت سوق",
        desc="شرح تفعيل اشتراك IPTV على الآيفون والآيباد خطوة بخطوة عبر تطبيق VAR Player من متجر آبل، مع إدخال بيانات الاشتراك وتشغيل القنوات.",
        h1="طريقة تشغيل اشتراك IPTV على الآيفون والآيباد",
        intro="التشغيل على أجهزة آبل لا يحتاج أكثر من تطبيق واحد من المتجر الرسمي وبيانات اشتراكك. اتبع الخطوات بالترتيب.",
        products=["p1205321184", "p1112367445"],
    ),
    "/android": dict(
        device="android",
        title="طريقة تثبيت IPTV على جوال أندرويد | NEXT+ و Smarters | سمارت سوق",
        desc="شرح تفعيل اشتراك IPTV على جوالات أندرويد خطوة بخطوة، عبر تطبيق NEXT+ من جوجل بلاي أو IPTV Smarters Pro بالتحميل المباشر.",
        h1="طريقة تثبيت اشتراك IPTV على جوال أندرويد",
        intro="أمامك طريقان على الأندرويد: تطبيق NEXT+ من جوجل بلاي وهو الأسهل، أو IPTV Smarters Pro بتحميل مباشر. اختر واحدًا واتبع خطواته.",
        products=["p1205321184", "p1112367445"],
    ),
    "/android-tv": dict(
        device="tv",
        title="طريقة تثبيت IPTV على شاشات وبوكسات أندرويد | سمارت سوق",
        desc="شرح تثبيت اشتراك IPTV على شاشات أندرويد مثل TCL و Dansat وبوكسات أندرويد، عبر تطبيق MR7 TV أو IPTV Smarters Pro بأداة Downloader.",
        h1="طريقة تثبيت اشتراك IPTV على شاشات وبوكسات أندرويد",
        intro="شاشات أندرويد مثل TCL و Dansat وأي بوكس أندرويد تقبل التطبيقين. تطبيق MR7 TV أسهل لأن دخوله مباشر، و IPTV Smarters Pro يحتاج أداة Downloader.",
        products=["p1112367445", "p159938107"],
    ),
    "/windows": dict(
        device="windows",
        title="طريقة تشغيل اشتراك IPTV على كمبيوتر ويندوز | سمارت سوق",
        desc="شرح تشغيل اشتراك IPTV على كمبيوتر ويندوز خطوة بخطوة عبر برنامج IPTV Smarters Pro، من التحميل حتى إدخال بيانات الاشتراك.",
        h1="طريقة تشغيل اشتراك IPTV على كمبيوتر ويندوز",
        intro="برنامج IPTV Smarters Pro يعمل على ويندوز بنسخة مكتبية كاملة. حمّل الملف ثم أدخل بيانات اشتراكك.",
        products=["p1112367445", "p971439862"],
    ),
    "/mac": dict(
        device="mac",
        title="طريقة تشغيل اشتراك IPTV على ماك MacBook و iMac | سمارت سوق",
        desc="شرح تشغيل اشتراك IPTV على أجهزة ماك خطوة بخطوة عبر IPTV Smarters Pro، مع تجاوز رسالة حماية macOS وإدخال بيانات الاشتراك.",
        h1="طريقة تشغيل اشتراك IPTV على أجهزة ماك",
        intro="على الماك تحتاج خطوة إضافية لتجاوز حماية macOS عند أول تشغيل. الخطوات كاملة بالترتيب.",
        products=["p1112367445", "p971439862"],
    ),
}


def _data():
    with open(os.path.join(BASE_DIR, "static", "guide-data.json"), encoding="utf-8") as f:
        return json.load(f)


def _style():
    """نأخذ أنماط المعالج نفسها فيخرج الشكل واحدًا بلا نسخ ثانٍ من الـ CSS."""
    with open(os.path.join(BASE_DIR, "index.html"), encoding="utf-8") as f:
        m = re.search(r"<style[^>]*>(.*?)</style>", f.read(), re.S)
    return m.group(1) if m else ""


def _esc(s):
    return _html.escape(s or "", quote=True)


def _product_link(pid):
    name, slug = PRODUCTS[pid]
    return f'<a class="link" href="{STORE}/{slug}/{pid}{UTM}">{_esc(name)}</a>'


def _steps_html(dev):
    """يبني الخطوات: قسم لكل تطبيق، وعنوان h2 لكل خطوة، وصورة بنصّ بديل."""
    out, n = [], 0
    groups = ([(None, dev["steps"])] if "steps" in dev
              else [(o, dev["variants"][o["key"]]) for o in dev["choose"]["options"]
                    if o["key"] in dev["variants"]])
    for opt, steps in groups:
        if opt:
            out.append(f'<h2 class="app">تطبيق {_esc(opt["label"])}'
                       f'<small> — {_esc(opt["sub"])}</small></h2>')
        for s in steps:
            n += 1
            out.append('<section class="card step">')
            out.append(f'<h3>الخطوة {n} — {_esc(s["title"])}</h3>')
            if s.get("img"):
                out.append(f'<img src="{_esc(s["img"])}" alt="{_esc(s["title"])}" loading="lazy">')
            out.append(s.get("html", ""))
            out.append("</section>")
        n = 0
    return "\n".join(out)


def render(path):
    """يُرجع صفحة الجهاز كاملة بايتات، أو None إن لم يكن المسار صفحة جهاز."""
    meta = PAGES.get(path)
    if not meta:
        return None
    dev = _data()[meta["device"]]
    url = SITE + path

    crumbs = {
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "دليل التفعيل", "item": SITE + "/"},
            {"@type": "ListItem", "position": 2, "name": meta["h1"], "item": url},
        ],
    }
    plans = " · ".join(_product_link(p) for p in meta["products"])
    others = "".join(
        f'<li><a class="link" href="{p}">{_esc(m["h1"])}</a></li>'
        for p, m in PAGES.items() if p != path)

    doc = f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(meta["title"])}</title>
<meta name="description" content="{_esc(meta["desc"])}">
<meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1">
<link rel="canonical" href="{url}">
<link rel="alternate" hreflang="ar" href="{url}">
<link rel="alternate" hreflang="x-default" href="{url}">
<meta property="og:type" content="article">
<meta property="og:locale" content="ar_SA">
<meta property="og:site_name" content="سمارت سوق">
<meta property="og:title" content="{_esc(meta["title"])}">
<meta property="og:description" content="{_esc(meta["desc"])}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{SITE}/static/og-image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<link rel="icon" href="/favicon.ico">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<script type="application/ld+json">{json.dumps(crumbs, ensure_ascii=False)}</script>
<style>{_style()}
.app{{margin:28px 0 12px;font-size:20px}}.app small{{font-weight:400;opacity:.7}}
.step h3{{margin:0 0 10px;font-size:18px}}
nav.crumb{{font-size:14px;opacity:.75;margin:0 0 14px}}
ul.more{{margin:8px 0 0;padding-inline-start:20px;line-height:2}}
</style>
</head>
<body>
<main id="view">
<nav class="crumb"><a class="link" href="/">دليل التفعيل</a> ← {_esc(dev["name"])}</nav>
<h1>{_esc(meta["h1"])}</h1>
<p class="sub">{_esc(meta["intro"])}</p>
{_steps_html(dev)}
<section class="card">
<h2>الباقة المناسبة لهذا الجهاز</h2>
<p>{plans}</p>
<p class="sub">أو تصفّح <a class="link" href="{STORE}/الاشتراكات-الرقمية/c993357185{UTM}">كل اشتراكات IPTV</a> في متجر سمارت سوق.</p>
</section>
<section class="card">
<h2>أجهزة أخرى</h2>
<ul class="more">{others}</ul>
<p class="sub"><a class="link" href="/">أو افتح المعالج التفاعلي</a> واختر جهازك خطوة بخطوة.</p>
</section>
</main>
<script>
/* أزرار النسخ في هذه الصفحات الثابتة — الوسم نفسه الذي يبنيه COPY في المعالج،
   فلو بقيت بلا سكربت لكان الزر يَعِد بنسخ لا يحدث. */
document.addEventListener("click", function (e) {{
  var b = e.target.closest("[data-copy]"); if (!b) return;
  if (navigator.clipboard) navigator.clipboard.writeText(b.dataset.copy).catch(function () {{}});
  var em = b.querySelector("em"); b.classList.add("done");
  if (em) {{ em.textContent = "تم النسخ"; setTimeout(function () {{ em.textContent = "نسخ"; b.classList.remove("done"); }}, 1800); }}
}});
</script>
</body>
</html>"""
    return doc.encode("utf-8")


def sitemap():
    """خريطة الموقع مبنيّة من PAGES نفسها، فلا تتخلّف عنها عند إضافة صفحة."""
    import datetime
    today = datetime.date.today().isoformat()
    rows = [
        '  <url>\n    <loc>%s/</loc>\n    <lastmod>%s</lastmod>'
        '\n    <changefreq>weekly</changefreq>\n    <priority>1.0</priority>'
        '\n    <image:image><image:loc>%s/static/og-image.png</image:loc>'
        '<image:title>تفعيل الاشتراك خطوة بخطوة | سمارت سوق</image:title></image:image>'
        '\n  </url>' % (SITE, today, SITE)
    ]
    for path in PAGES:
        rows.append(
            '  <url>\n    <loc>%s%s</loc>\n    <lastmod>%s</lastmod>'
            '\n    <changefreq>monthly</changefreq>\n    <priority>0.8</priority>\n  </url>'
            % (SITE, path, today))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n'
            + "\n".join(rows) + "\n</urlset>\n").encode("utf-8")

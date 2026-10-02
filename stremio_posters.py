#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ملصقات القنوات في Stremio: اسم القناة ورقمها وختم جودتها («4K» · «FULL HD» · «HD 720») — تُرسم على الخادم بخط الموقع
(IBM Plex Sans Arabic، ‏static/fonts)، فتتشابه بطاقات البث كلها وتُقرأ من بعيد على التلفزيون.

  PNG بـ Pillow (ومعه raqm لتشكيل العربية واتجاهها) — ما تعرضه تطبيقات Stremio كلها؛ وبلا Pillow (أو اسمٌ عربي بلا
  raqm) ← SVG بالتصميم نفسه (يرسمه المتصفح ونسخة الكمبيوتر).
  ‏render(الاسم، الرقم، الجودة، القسم) ← (البايتات، النوع)، محفوظةٌ في الذاكرة (الصورة نفسها لا تتغيّر لمعطياتها نفسها).

الرابط مختومٌ في stremio_addon (‏/stremio/p/<رمز>.png): لا يُرسم نصٌّ لم يصدر منّا.
"""
import hashlib
import io
import os
import re
import threading
from collections import OrderedDict
from xml.sax.saxutils import escape

import content as C

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_BOLD = os.path.join(HERE, "static", "fonts", "IBMPlexSansArabic-Bold.ttf")
FONT_SEMI = os.path.join(HERE, "static", "fonts", "IBMPlexSansArabic-SemiBold.ttf")
SIZE = 400                          # مربّعٌ كما تعرض Stremio بطاقات القنوات (‏posterShape: square)
CACHE_MAX = 600

try:
    from PIL import Image, ImageDraw, ImageFont, features
    PIL_OK = os.path.isfile(FONT_BOLD) and os.path.isfile(FONT_SEMI)
    RAQM = PIL_OK and bool(features.check("raqm"))
except Exception:                   # Pillow غير مثبّت: SVG
    PIL_OK = RAQM = False

# الختم: نصّه ولونه (حدٌّ ونص) لكل جودة — ما لا تُعرف جودته بلا ختم
STAMP = {"4K": ("4K", (247, 196, 75)), "FHD": ("FULL HD", (74, 222, 163)), "HD": ("HD 720", (110, 168, 255)),
         "SD": ("SD", (180, 188, 204))}
# خلفياتٌ داكنة متدرّجة؛ لكل قسمٍ لونه (من بصمة اسمه) فتتجاور قنوات القسم بلونٍ واحد
PALETTES = [((27, 35, 74), (10, 14, 34)), ((52, 28, 84), (16, 10, 36)), ((12, 58, 74), (6, 20, 32)),
            ((74, 30, 44), (30, 10, 18)), ((24, 62, 46), (8, 24, 18)), ((70, 52, 18), (28, 18, 6)),
            ((40, 40, 48), (14, 14, 20)), ((22, 46, 90), (8, 16, 40))]
_AR = re.compile(r"[؀-ۿ]")
_lock = threading.Lock()
_cache = OrderedDict()


def display_name(name):
    """اسم القناة على الملصق: بلا بادئة اللغة («AR:») ولا رمز الجودة (الختم يقولها)."""
    return C._dequal(C._clean(name)) or str(name or "")


def _palette(cat, name):
    h = int(hashlib.sha1((cat or name or "").encode("utf-8")).hexdigest()[:6], 16)
    return PALETTES[h % len(PALETTES)]


def _wrap(words, fits, max_lines):
    """أطول أسطرٍ تسعها المساحة (كلماتٌ كاملة)، أو None إن لم تسع."""
    lines, cur = [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if fits(t):
            cur = t
        elif cur and fits(w):
            lines.append(cur)
            cur = w
        else:
            return None
        if len(lines) >= max_lines:
            return None
    lines.append(cur)
    return lines if len(lines) <= max_lines else None


def _png(name, num, quality, cat):
    top, bottom = _palette(cat, name)
    grad = Image.new("RGB", (1, SIZE))                            # تدرّجٌ رأسي (عمود بكسلٍ يُمدّ)
    for y in range(SIZE):
        t = y / (SIZE - 1)
        grad.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    img = grad.resize((SIZE, SIZE))
    d = ImageDraw.Draw(img, "RGBA")
    d.ellipse((-120, -160, 300, 200), fill=(255, 255, 255, 14))   # لمعةٌ خفيفة
    d.rounded_rectangle((8, 8, SIZE - 9, SIZE - 9), radius=34, outline=(255, 255, 255, 34), width=2)
    lay = {"layout_engine": ImageFont.Layout.RAQM} if RAQM else {}

    if num:                                                       # الرقم: مربّعٌ في الأعلى يسارًا
        f = ImageFont.truetype(FONT_BOLD, 40, **lay)
        tx = str(num)
        w = max(64, int(f.getlength(tx)) + 32)
        d.rounded_rectangle((24, 24, 24 + w, 88), radius=18, fill=(255, 255, 255, 30), outline=(255, 255, 255, 60), width=2)
        d.text((24 + w / 2, 56), tx, font=f, fill=(255, 255, 255), anchor="mm")

    st = STAMP.get(quality)
    if st:                                                        # الختم: مائلٌ في الأعلى يمينًا بحدٍّ مزدوج
        label, col = st
        f = ImageFont.truetype(FONT_BOLD, 30 if len(label) > 3 else 40, **lay)
        tw = int(f.getlength(label))
        sw, sh = tw + 44, 70
        stamp = Image.new("RGBA", (sw + 20, sh + 20), (0, 0, 0, 0))
        sd = ImageDraw.Draw(stamp)
        sd.rounded_rectangle((10, 10, 10 + sw, 10 + sh), radius=14, fill=col + (38,), outline=col + (255,), width=4)
        sd.rounded_rectangle((17, 17, 3 + sw, 3 + sh), radius=10, outline=col + (170,), width=2)
        sd.text((10 + sw / 2, 10 + sh / 2), label, font=f, fill=col + (255,), anchor="mm")
        stamp = stamp.rotate(-10, resample=Image.BICUBIC, expand=True)
        img.paste(stamp, (SIZE - stamp.width - 14, 14), stamp)

    words = name.split() or [name]                                # الاسم: أكبر خطٍّ يسعه في ثلاثة أسطرٍ على الأكثر
    box_w, box_top, box_bot = SIZE - 56, 110, (318 if cat else 352)
    for size in (84, 74, 66, 58, 52, 46, 40, 35, 30, 26):
        f = ImageFont.truetype(FONT_BOLD, size, **lay)
        lines = _wrap(words, lambda t: f.getlength(t) <= box_w, 3)
        if lines and len(lines) * size * 1.18 <= box_bot - box_top:
            break
    else:
        lines = [name[:22] + "…"]
    lh = size * 1.18
    y0 = (box_top + box_bot) / 2 - lh * len(lines) / 2 + lh / 2
    for i, ln in enumerate(lines):
        d.text((SIZE / 2 + 2, y0 + i * lh + 3), ln, font=f, fill=(0, 0, 0, 110), anchor="mm")   # ظلٌّ للقراءة من بعيد
        d.text((SIZE / 2, y0 + i * lh), ln, font=f, fill=(255, 255, 255), anchor="mm")

    if cat:                                                       # القسم: سطرٌ خافت في الأسفل
        f = ImageFont.truetype(FONT_SEMI, 26, **lay)
        c = cat if f.getlength(cat) <= SIZE - 60 else cat[:26] + "…"
        d.line((SIZE / 2 - 40, 330, SIZE / 2 + 40, 330), fill=(255, 255, 255, 60), width=2)
        d.text((SIZE / 2, 362), c, font=f, fill=(255, 255, 255, 170), anchor="mm")
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


def _svg(name, num, quality, cat):
    top, bottom = _palette(cat, name)
    rgb = lambda c, a=1: f"rgba({c[0]},{c[1]},{c[2]},{a})"
    words, lines, cur = name.split() or [name], [], ""
    for w in words:                                               # لفٌّ تقريبي بعدد الحروف (المتصفح يرسم الخط)
        if len((cur + " " + w).strip()) <= 14 or not cur:
            cur = (cur + " " + w).strip()
        else:
            lines.append(cur)
            cur = w
    lines = (lines + [cur])[:3]
    size = 70 if max(len(x) for x in lines) <= 9 else 54 if max(len(x) for x in lines) <= 13 else 40
    lh = size * 1.2
    box_top, box_bot = 110, (318 if cat else 352)
    y0 = (box_top + box_bot) / 2 - lh * len(lines) / 2 + lh / 2
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{SIZE}" height="{SIZE}" viewBox="0 0 {SIZE} {SIZE}">',
             f'<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{rgb(top)}"/>'
             f'<stop offset="1" stop-color="{rgb(bottom)}"/></linearGradient></defs>',
             f'<rect width="{SIZE}" height="{SIZE}" fill="url(#g)"/>',
             f'<rect x="8" y="8" width="{SIZE - 17}" height="{SIZE - 17}" rx="34" fill="none" stroke="rgba(255,255,255,.14)" stroke-width="2"/>']
    font = "font-family=\"'IBM Plex Sans Arabic',Tahoma,Arial,sans-serif\" font-weight=\"700\""
    if num:
        w = max(64, 26 * len(str(num)) + 32)
        parts.append(f'<rect x="24" y="24" width="{w}" height="64" rx="18" fill="rgba(255,255,255,.12)" stroke="rgba(255,255,255,.24)" stroke-width="2"/>'
                     f'<text x="{24 + w / 2}" y="68" text-anchor="middle" font-size="40" fill="#fff" {font}>{num}</text>')
    st = STAMP.get(quality)
    if st:
        label, col = st
        fs = 30 if len(label) > 3 else 40
        sw = int(fs * 0.62 * len(label)) + 44
        x = SIZE - sw - 30
        parts.append(f'<g transform="rotate(10 {x + sw / 2} 64)"><rect x="{x}" y="29" width="{sw}" height="70" rx="14" fill="{rgb(col, .15)}" '
                     f'stroke="{rgb(col)}" stroke-width="4"/><rect x="{x + 7}" y="36" width="{sw - 14}" height="56" rx="10" fill="none" '
                     f'stroke="{rgb(col, .67)}" stroke-width="2"/><text x="{x + sw / 2}" y="{64 + fs * 0.36}" text-anchor="middle" '
                     f'font-size="{fs}" fill="{rgb(col)}" {font}>{escape(label)}</text></g>')
    for i, ln in enumerate(lines):
        parts.append(f'<text x="{SIZE / 2}" y="{y0 + i * lh + size * 0.35}" text-anchor="middle" font-size="{size}" fill="#fff" '
                     f'direction="{"rtl" if _AR.search(ln) else "ltr"}" {font}>{escape(ln)}</text>')
    if cat:
        parts.append(f'<line x1="{SIZE / 2 - 40}" y1="330" x2="{SIZE / 2 + 40}" y2="330" stroke="rgba(255,255,255,.24)" stroke-width="2"/>'
                     f'<text x="{SIZE / 2}" y="371" text-anchor="middle" font-size="26" fill="rgba(255,255,255,.67)" '
                     f"font-family=\"'IBM Plex Sans Arabic',Tahoma,Arial,sans-serif\" font-weight=\"600\">{escape(cat[:30])}</text>")
    parts.append("</svg>")
    return "".join(parts).encode("utf-8")


def render(name, num=0, quality="", cat=""):
    """ملصق القناة ← (البايتات، نوعها). PNG متى أمكن (Pillow، ومع raqm للعربية)، وإلا SVG."""
    name = display_name(name)
    key = (name, int(num or 0), quality or "", cat or "")
    with _lock:
        hit = _cache.get(key)
        if hit:
            _cache.move_to_end(key)
            return hit
    if PIL_OK and (RAQM or not (_AR.search(name) or _AR.search(cat or ""))):
        val = (_png(*key), "image/png")
    else:
        val = (_svg(*key), "image/svg+xml")
    with _lock:
        _cache[key] = val
        while len(_cache) > CACHE_MAX:
            _cache.popitem(last=False)
    return val

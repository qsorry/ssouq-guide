#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
الردّ على الشكاوى — نصّ الردّ الذي يُرسل لعميلٍ اشتكى أن اشتراكه لا يعمل.

الشكوى في أغلبها واحدة: العميل لا يعرف إلا تطبيقًا واحدًا (IPTV Smarters Pro) أو
حمّل تطبيقًا يشبهه بالاسم، أو ثبّت التطبيق القديم على اشتراكه الجديد. فالردّ لا
يعيد بيانات الاشتراك وحدها، بل يرتّب للعميل ما يحتاجه كله في رسالة واحدة:

  1. رأسٌ باسمه ورقم طلبه (فيعرف أن الردّ على طلبه هو لا ردٌّ عامّ).
  2. نصّ الشرح المعتاد (📲 طريقة التثبيت والتفعيل: رابط الشرح، وسيرفر الاشتراك،
     وHost/User/Pass، وتحذير التطبيق القديم) — هو نفسه ما تنسخه صفحة الإنشاء.
  3. **التطبيق المناسب لجهازه** — جدول اشتراكه وحده (سمارت · فالكون · كاسبر) كما
     في دليل التفعيل: لكل جهازٍ تطبيقُه الموصى به وبديله، لرفع وعي من لا يعرف
     إلا تطبيقًا واحدًا.
  4. تحذير التطبيقات المقلِّدة، ثم كيف يطلب المساعدة (نوع الجهاز وصورة الشاشة).

وفي هذا الملف أيضًا معرفةُ اشتراك الطلب (سمارت · فالكون · كاسبر) من اسم منتجه أو
رمزه (SKU) أو هوسته — فالنصّ يُبنى على اشتراك العميل لا على اشتراكٍ عامّ.

stdlib فقط. لا يعرف شيئًا عن سلة ولا عن اللوحات: يأخذ ما وُجد ويصوغ النصّ.
"""
import re

SITE = "https://guide.ssouq.com"

# أسماء الاشتراكات كما يراها العميل في الدليل (SUBS في index.html).
SUB_NAMES = {"smart": "سمارت", "falcon": "فالكون", "casper": "كاسبر"}

# كلماتٌ تدلّ على الاشتراك في اسم المنتج أو البوابة أو الهوست. «مرح» و«MR7» اسم سمارت القديم.
SUB_WORDS = {"falcon": ("falcon", "فالكون", "fal-"),
             "casper": ("casper", "كاسبر"),
             "smart": ("smart", "marah", "mr7", "سمارت", "مرح")}

# بادئات SKU في المتجر: `FAL-PRO-15M` فالكون، `MRH-15M-2D` سمارت (مرح)، `CSP-…` كاسبر.
SKU_PREFIX = {"FAL": "falcon", "MRH": "smart", "MR7": "smart", "SMT": "smart", "CSP": "casper", "CAS": "casper"}

# التطبيق الموصى به لكل جهاز، لكل اشتراك — من جدول «الاشتراكات الثلاثة في دليل التفعيل» (README).
# (الجهاز، التطبيق الأول، البديل). ما يختلف بين الاشتراكات هو الجوال والشاشات؛ والبقية واحدة.
_DEVICES = ("iphone", "android", "android_tv", "webos", "vidaa", "pc")
DEVICE_NAMES = {"iphone": "آيفون وآيباد", "android": "جوال أندرويد", "android_tv": "شاشة أو بوكس أندرويد",
                "webos": "شاشات سامسونج و LG", "vidaa": "هايسنس (VIDAA)", "pc": "ويندوز وماك"}
APPS = {
    "smart": {"iphone": ("VAR Player", ""),
              "android": ("NEXT+", "IPTV Smarters Pro"),
              "android_tv": ("MR7 TV", "IPTV Smarters Pro"),
              "webos": ("0Player برمز 92929480", "Duplecast"),
              "vidaa": ("Duplecast", ""),
              "pc": ("IPTV Smarters Pro", "")},
    "falcon": {"iphone": ("Smarters Player Lite", ""),
               "android": ("تطبيق فالكون", "IPTV Smarters Pro"),
               "android_tv": ("تطبيق فالكون", "IPTV Smarters Pro"),
               "webos": ("0Player برمز 75710072", "Duplecast"),
               "vidaa": ("Duplecast", ""),
               "pc": ("IPTV Smarters Pro", "")},
    "casper": {"iphone": ("CASPER VIP", "AroPlayer"),
               "android": ("CASPER VIP", "IPTV Smarters Pro"),
               "android_tv": ("CASPER VIP", "IPTV Smarters Pro"),
               "webos": ("0Player برمز 59820658 (بباقة سامسونج و LG)", "Duplecast"),
               "vidaa": ("Duplecast", ""),
               "pc": ("IPTV Smarters Pro", "")},
}

# صفحة الجهاز في الدليل — تُذكر مع الجدول ليفتح العميل شرح جهازه هو.
DEVICE_PAGES = {"iphone": "/iphone", "android": "/android", "android_tv": "/android-tv",
                "webos": "/samsung-lg", "vidaa": "/vidaa", "pc": "/windows"}

REPLY_HEAD = ("السلام عليكم ورحمة الله *{name}* 👋\n\n"
              "بخصوص طلبكم رقم *{order}*: هذه بيانات اشتراككم وطريقة تشغيله خطوة بخطوة 👇")

APPS_HEAD = "📱 *التطبيق المناسب لجهازك (اشتراك {server})*\n" \
            "الاشتراك ليس لتطبيق IPTV Smarters Pro وحده؛ لكل جهاز تطبيقٌ موصى به:"
APPS_HEAD_GENERIC = "📱 *التطبيق المناسب لجهازك*\n" \
                    "الاشتراك ليس لتطبيق IPTV Smarters Pro وحده؛ لكل اشتراكٍ وجهاز تطبيقٌ موصى به، تجده في الشرح:"

WARN = ("⚠️ *انتبه:* توجد تطبيقات كثيرة تحمل اسم IPTV Smarters أو تشبهه، لا تحمّل تطبيقًا عشوائيًا ولا تعتمد على الاسم وحده. "
        "التطبيقات المذكورة في الشرح مضمونة ومتوافقة مع اشتراكك وجهازك.")

EXTRA_USER = "📌 *اليوزر {n}:*\nUser: {user}\nPass: {pass}"

FOOT = "❓ إن تعذّرت عليك خطوة، أرسل لنا *نوع جهازك* و*صورة الشاشة* ونساعدك فورًا 🌹"

# حالات الشكوى التي تنتظر التاجر وحدها تُعرض في «مراجعة الشكاوى» — «بانتظار الحل من التاجر» و«بانتظار رد التاجر»
# (وتسمّيها صفحة مساعدة سلة «بانتظار استجابة التاجر»)؛ وما ينتظر العميل أو أُغلق أو ما زال عند سلة لا يُعرض.
OPEN_STATUSES = ("بانتظار الحل من التاجر", "بانتظار رد التاجر", "بانتظار استجابة التاجر")
_OPEN_RE = re.compile(r"(?:بانتظار|في انتظار|ينتظر)\s*(?:الحل من|رد|ردّ|استجابة)\s*التاجر|awaiting[_ ]merchant|pending[_ ]merchant", re.I)


def is_open(status):
    """أتنتظر الشكوى التاجر؟ — بنصّ حالتها كما تعرضه لوحة سلة (أو مفتاحها بالإنجليزية)."""
    t = re.sub(r"\s+", " ", str(status or "")).strip()
    return t in OPEN_STATUSES or bool(_OPEN_RE.search(t))


def open_only(rows):
    """الشكاوى التي تنتظر التاجر وحدها، بترتيبها."""
    return [r for r in (rows or []) if is_open(r.get("status"))]


_AR = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def norm_order(v):
    """رقم الطلب أرقامًا لاتينية بلا مسافات ولا شرطات — والعربية والفارسية تُقرأ."""
    return re.sub(r"\D", "", str(v or "").translate(_AR))


def sub_from_sku(sku):
    p = str(sku or "").strip().upper().split("-", 1)[0]
    return SKU_PREFIX.get(p, "")


def sub_from_text(text):
    """اشتراكٌ من نصٍّ حرّ (اسم منتج أو بوابة أو هوست): فالكون أولًا — «فالكون IPTV» فيه كلمة IPTV
    العامة — ثم كاسبر، ثم سمارت."""
    # «IPTV Smarters» اسم تطبيقٍ تحمله منتجات الاشتراكات كلها، لا اشتراكُ سمارت — فيُحذف قبل المطابقة.
    t = re.sub(r"smarters?\s*(player|pro|lite)?", " ", str(text or "").lower()).replace("smarters", " ")
    for key in ("falcon", "casper", "smart"):
        if any(w in t for w in SUB_WORDS[key]):
            return key
    return ""


def sub_of(product="", sku="", host="", falcon=False, gate_sub=""):
    """اشتراك الطلب: علامة فالكون، ثم رمز المنتج، ثم اسمه، ثم اشتراك بوابة هوسته، ثم الهوست نفسه، وإلا ""."""
    if falcon:
        return "falcon"
    return (sub_from_sku(sku) or sub_from_text(product) or (gate_sub if gate_sub in SUB_NAMES else "")
            or sub_from_text(host))


def guide_link(sub):
    """رابط شرح الاشتراك في الدليل (#activate/<الاشتراك>)، أو الصفحة الرئيسية لمجهول الاشتراك."""
    return SITE + ("/#activate/" + sub if sub in SUB_NAMES else "/")


def apps_lines(sub):
    """أسطر الجدول: «• الجهاز: التطبيق (أو البديل)» — لاشتراكٍ معروف وحده."""
    table = APPS.get(sub)
    if not table:
        return []
    out = []
    for dev in _DEVICES:
        first, alt = table[dev]
        out.append("• %s: %s%s" % (DEVICE_NAMES[dev], first, (" (أو %s)" % alt) if alt else ""))
    return out


def apps_block(sub):
    """كتلة «التطبيق المناسب لجهازك»: الرأس باسم الاشتراك، وجدوله، ثم تحذير المقلِّدات."""
    if sub in APPS:
        head = APPS_HEAD.format(server=SUB_NAMES[sub])
        body = "\n".join(apps_lines(sub))
        return head + "\n" + body + "\n\n" + WARN
    return APPS_HEAD_GENERIC + "\n\n" + WARN


def reply_text(name, order, line, sub="", extra=()):
    """الردّ كاملًا: الرأس، ثم نصّ الشرح (line: «📲 طريقة التثبيت والتفعيل» ببيانات اليوزر الأول)، ثم
    اليوزرات الزائدة لطلبٍ بأكثر من نسخة، ثم جدول تطبيقات اشتراكه وتحذيره، ثم طلب المساعدة."""
    parts = [REPLY_HEAD.format(name=(str(name or "").strip() or "عميلنا العزيز"), order=norm_order(order) or str(order or "")),
             str(line or "").strip()]
    for i, c in enumerate(extra or (), start=2):
        if c.get("username"):
            parts.append(EXTRA_USER.format(n=i, user=c.get("username", ""), **{"pass": c.get("password", "")}))
    parts += [apps_block(sub), FOOT]
    return "\n\n".join(p for p in parts if p)


def product_blurb(sub=""):
    """وصفٌ متكامل يُلصق في صفحة المنتج (أو يُرسل للعميل قبل الشراء): التنبيه قبل الشراء، والجدول إن عُرف
    الاشتراك — النسخة الواعية من «الاشتراك ليس لتطبيق IPTV Smarters Pro فقط»."""
    lines = ["⚠️ قبل الشراء: تأكد أن التطبيق الموصى به متوفر على جهازك",
             "",
             "🔹 لكل اشتراك تطبيق مناسب حسب نوع الاشتراك والجهاز، فاتبع تعليمات التشغيل المرفقة مع الاشتراك واستخدم التطبيق الموصى به لتعمل الخدمة بالشكل الصحيح.",
             "🔹 توجد تطبيقات كثيرة تحمل أسماء مشابهة لـ IPTV Smarters Pro أو تقلّده؛ لا تحمّل تطبيقًا عشوائيًا ولا تعتمد على الاسم فقط.",
             "🔹 نوفّر لك تطبيقات موصى بها ومضمونة ومتوافقة مع جهازك واشتراكك، مع طريقة التحميل والتشغيل."]
    if sub in APPS:
        lines += ["", "📱 تطبيقات اشتراك %s حسب الجهاز:" % SUB_NAMES[sub]] + apps_lines(sub)
    lines += ["", "✅ تأكد أولًا من إمكانية تحميل التطبيق الموصى به على جهازك، حتى لا تشتري ثم تكتشف أنه غير متوفر أو غير متوافق.",
              "📌 اعرف التطبيق المناسب لجهازك وطريقة التشغيل: " + guide_link(sub)]
    return "\n".join(lines)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
موصّل لوحة سلة بجلسة متصفّح — بديل الواجهة حين لا تعطي ما نحتاج.

لماذا هذا الملف؟ للسبب نفسه الذي وُجد لأجله `xm_web.py`: واجهة الإدارة الرسمية
لا تُخرج كل شيء. بيانات الاشتراك تُسلَّم بطاقةً رقمية، ومسار الأكواد في الواجهة
غير موثّق بثبات. أما **لوحة سلة نفسها** فتعرض البطاقة كاملةً — والمشغّل يراها
بعينيه. فما يراه المشغّل نستطيع قراءته بجلسته.

**لا كلمة مرور هنا ولا دخول آلي — ولا سبيل إليه.** كود الـSMS وحده لم يكن
ليمنع: `xm_web` يدخل لوحة مرح آليًّا ويرفع `CaptchaNeeded` فيكتب المشغّل الكود،
وكان يمكن أن نفعل مثله هنا. لكن **Cloudflare Turnstile يسبق الكود**: صفحة
`s.salla.sa/auth` قشرةُ SystemJS بلا نموذج في الـHTML، والتحدّي يُحمَّل بالـJS،
ورمزُه يُصدَر لمتصفّحٍ حقيقي بعد تحدٍّ ولا يستطيع خادمٌ توليده. ومن ورائه
مفتاحُ مرورٍ (‏`/auth/quick`) مربوطٌ بجهاز المشغّل.

فالطريق الوحيد أن يدخل المشغّل بمتصفّحه — بكلمة مروره وكود الـSMS وبصمته — ثم
يُعطينا جلسته: ينسخ «Copy as cURL» من أدوات المطوّر ويلصقه مرة. تُحفظ مشفَّرةً
كبقية الأسرار وتُستعمل حتى تنتهي، فإن انتهت طُلب لصقها ثانية — تمامًا كجلسة
`xm_web` حين تسقط.

**والصفحة تطبيق JS**، فلا يُقرأ الـHTML: تُنادى نُقط JSON نفسها التي تناديها
اللوحة. ومسارها غير موثّق، فتُجرَّب مرشّحات ويُحفظ أوّل ما نجح.

stdlib فقط. لا يُسجَّل سرّ.
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 30
BASE = "https://s.salla.sa"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")

# اللوحة تُحوّل غير الداخل إلى /auth — وهذا هو كاشفُ انتهاء الجلسة.
AUTH_REDIRECT = re.compile(r"/auth(?:\?|$)")

# مرشّحات مسار الطلب في لوحة سلة. غير موثّقة وتتغيّر بين إصدارات اللوحة،
# فتُجرَّب بالترتيب ويُحفظ أوّل ما ردّ JSON فيه ما نريد.
ORDER_PATHS = (
    "/api/orders/{token}",
    "/orders/order/{token}?format=json",
    "/api/v1/orders/{token}",
    "/api/orders/order/{token}",
)


class SessionExpired(RuntimeError):
    """الكوكيز انتهت أو لم تعد صالحة — يُطلب لصقها من جديد."""


class WebError(RuntimeError):
    pass


# من «Copy as cURL» في أدوات المطوّر: الكوكيز إمّا ترويسةٌ بـ‎-H أو ‎-b/--cookie.
_CURL_COOKIE = re.compile(
    r"""(?ix)
    -H\s+(['"])\s*cookie\s*:\s*(?P<h>.*?)\1
    | (?:-b|--cookie)\s+(['"])(?P<b>.*?)\3
    """)


def clean_cookie(raw):
    """ما يلصقه المشغّل → نصٌّ صالح للإرسال، أيًّا كان شكل اللصق.

    التنقيب عن ترويسة `Cookie` وحدها في أدوات المطوّر متعب — وعلى الجوال شبه
    متعذّر. فالأسهل «Copy as cURL» من تبويب Network، ونحن نستخرجها منه. وتُقبل
    كذلك الترويسةُ وحدها، بالبادئة أو بدونها، سطرًا أو أسطرًا."""
    s = str(raw or "").strip()
    if not s:
        return ""
    if re.search(r"(?i)\bcurl\b", s[:400]):        # لُصق أمر cURL كاملًا
        m = _CURL_COOKIE.search(s)
        if m:
            s = m.group("h") or m.group("b") or ""
    s = re.sub(r"(?im)^\s*cookie\s*:\s*", "", s)
    s = s.replace("\\\n", " ")                       # أسطر cURL الموصولة بـ ‎\
    s = re.sub(r"\s*[\r\n]+\s*", "; ", s).strip().strip(";")
    parts = [p.strip() for p in s.split(";") if "=" in p]
    return "; ".join(parts)


def cookie_names(cookie):
    return [p.split("=", 1)[0].strip() for p in str(cookie or "").split(";") if "=" in p]


class Session:
    """جلسة لوحة سلة بكوكيز ملصوقة. لا تُنشئ جلسة ولا تُجدّدها — تستعملها."""

    def __init__(self, cookie, base=BASE):
        self.cookie = clean_cookie(cookie)
        self.base = base.rstrip("/")
        self._order_path = None          # أوّل مسارٍ نجح، يُحفظ فلا يُخمَّن ثانيةً
        if not self.cookie:
            raise WebError("لم تُلصق كوكيز الجلسة")

    # ----------------------------- النقل -----------------------------
    def _get(self, path, accept="application/json"):
        url = path if path.startswith("http") else self.base + path
        req = urllib.request.Request(url, headers={
            "Cookie": self.cookie, "User-Agent": UA, "Accept": accept,
            "X-Requested-With": "XMLHttpRequest", "Referer": self.base + "/orders",
        })
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(req, timeout=TIMEOUT) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                return e.code, e.headers, b""
            if e.code in (401, 403):
                raise SessionExpired("الجلسة غير مقبولة (%d) — الصق الكوكيز من جديد" % e.code)
            return e.code, e.headers, (e.read() if e.fp else b"")
        except urllib.error.URLError as e:
            raise WebError("تعذّر الوصول للوحة سلة: %s" % (getattr(e, "reason", e)))

    def _json(self, path):
        code, headers, body = self._get(path)
        loc = headers.get("Location", "") if headers else ""
        if code in (301, 302, 303, 307, 308) and AUTH_REDIRECT.search(loc):
            raise SessionExpired("انتهت الجلسة — الصق كوكيز جديدة من لوحة سلة")
        if code != 200 or not body:
            return None
        text = body.decode("utf-8", "replace")
        if AUTH_REDIRECT.search(text[:400]) and "<!DOCTYPE" in text[:200].upper():
            raise SessionExpired("أُعيد التحويل لصفحة الدخول — الصق كوكيز جديدة")
        try:
            return json.loads(text)
        except ValueError:
            return None

    # ----------------------------- الاستعمال -----------------------------
    def alive(self):
        """أما زالت الجلسة مقبولة؟ يرجّع (نعم؟، السبب)."""
        try:
            code, headers, _ = self._get("/orders", accept="text/html")
        except SessionExpired as e:
            return False, str(e)
        except WebError as e:
            return False, str(e)
        loc = headers.get("Location", "") if headers else ""
        if code in (301, 302, 303, 307, 308) and AUTH_REDIRECT.search(loc):
            return False, "انتهت الجلسة — الصق كوكيز جديدة من لوحة سلة"
        return (True, "") if code == 200 else (False, "ردّت اللوحة %d" % code)

    def order(self, token):
        """حمولة الطلب من اللوحة بمعرّفه في رابطها (‏`urls.admin` من الواجهة)."""
        tried = []
        paths = ([self._order_path] if self._order_path else []) + list(ORDER_PATHS)
        for tpl in paths:
            path = tpl.format(token=urllib.parse.quote(str(token)))
            if path in tried:
                continue
            tried.append(path)
            d = self._json(path)
            if isinstance(d, (dict, list)) and d:
                self._order_path = tpl
                return d
        return None

    def order_text(self, token):
        """نصّ الطلب كله مسطَّحًا — يُمرَّر لقارئ الاعتمادات كما هو."""
        d = self.order(token)
        if not d:
            return ""
        chunks = []
        _walk(d, chunks)
        return "\n".join(c for c in chunks if len(c) < 800)

    # مرشّحات قائمة الطلبات في لوحة سلة (غير موثّقة كمسار الطلب المفرد) — تُجرَّب
    # بالترتيب ويُحفظ أوّل ما ردّ قائمةَ طلبات، فلا يُخمَّن ثانيةً.
    _LIST_PATHS = (
        "/api/orders?per_page={n}&page=1",
        "/api/v1/orders?per_page={n}&page=1",
        "/orders?format=json&per_page={n}",
        "/api/orders?limit={n}",
        "/dashboard/orders?format=json",
    )

    def recent_orders(self, limit=25):
        """أحدث الطلبات من لوحة سلة بالجلسة (لا توكن API) — للسحب الدوري. تُعيد
        قائمة قواميس خام كما تعطيها اللوحة (يحلّلها المتصل بـ salla_api.parse_order).
        أفضل جهد: مسار القائمة غير موثّق فتُجرّب مرشّحات ويُلتقط أوّل قائمةٍ صالحة."""
        paths = ([self._list_path] if getattr(self, "_list_path", None) else []) \
            + [p for p in self._LIST_PATHS if p != getattr(self, "_list_path", None)]
        for tpl in paths:
            d = self._json(tpl.format(n=int(limit)))
            rows = _find_orders(d)
            if rows:
                self._list_path = tpl
                return rows[:limit]
        return []


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """لا نتبع 30x: التحويل إلى /auth هو خبرُ انتهاء الجلسة، لا خطأً نُخفيه."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _looks_like_order(d):
    if not isinstance(d, dict):
        return False
    keys = set(d.keys())
    has_id = bool(keys & {"id", "order_id", "reference_id", "reference"})
    has_ord = bool(keys & {"status", "total", "amount", "payment_method", "customer", "items", "reference_id"})
    return has_id and has_ord


def _find_orders(obj, depth=0):
    """يبحث في ردّ JSON عن أوّل قائمةِ طلباتٍ فعلية (تحت data/orders/items/results
    أو قائمة عليا)، متسامحًا مع اختلاف أشكال ردود لوحة سلة."""
    if depth > 6 or obj is None:
        return []
    if isinstance(obj, list):
        rows = [x for x in obj if _looks_like_order(x)]
        if rows:
            return rows
        for x in obj:
            r = _find_orders(x, depth + 1)
            if r:
                return r
        return []
    if isinstance(obj, dict):
        for k in ("data", "orders", "items", "results", "list"):
            if k in obj:
                r = _find_orders(obj[k], depth + 1)
                if r:
                    return r
        for v in obj.values():
            r = _find_orders(v, depth + 1)
            if r:
                return r
    return []


def _walk(obj, out, depth=0):
    if depth > 8:
        return out
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk(v, out, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, out, depth + 1)
    return out


def admin_token(url):
    """‏`https://s.salla.sa/orders/order/<token>` → `<token>`. الواجهة تعطي هذا
    الرابط في `urls.admin` لكل طلب، فهو الجسر بين الواجهة واللوحة."""
    m = re.search(r"/orders/order/([A-Za-z0-9_-]{8,})", str(url or ""))
    return m.group(1) if m else ""

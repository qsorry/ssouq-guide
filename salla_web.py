#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
موصّل لوحة سلة بجلسة متصفّح — بديل الواجهة حين لا تعطي ما نحتاج.

لماذا هذا الملف؟ للسبب نفسه الذي وُجد لأجله `xm_web.py`: واجهة الإدارة الرسمية
لا تُخرج كل شيء. بيانات الاشتراك تُسلَّم بطاقةً رقمية، ومسار الأكواد في الواجهة
غير موثّق بثبات. أما **لوحة سلة نفسها** فتعرض البطاقة كاملةً — والمشغّل يراها
بعينيه. فما يراه المشغّل نستطيع قراءته بجلسته.

**لا كلمة مرور هنا ولا دخول آلي.** لوحة سلة محمية بتحقّق ثنائي، وأتمتته عبثٌ
وخطر. بدلًا منه: يفتح المشغّل اللوحة في متصفّحه، وينسخ ترويسة `Cookie` من
أدوات المطوّر، ويلصقها مرة. تُحفظ مشفَّرةً كبقية الأسرار وتُستعمل حتى تنتهي،
فإن انتهت طُلب لصقها ثانية — تمامًا كجلسة `xm_web` حين تسقط.

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


def clean_cookie(raw):
    """ترويسة `Cookie` كما تُنسخ من المتصفّح → نصٌّ صالح للإرسال.

    المشغّل قد ينسخ السطر كاملًا (`Cookie: a=1; b=2`) أو محتواه وحده، وقد يلصق
    أسطرًا متعددة. كلها تُقبل."""
    s = str(raw or "").strip()
    s = re.sub(r"(?im)^\s*cookie\s*:\s*", "", s)
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


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """لا نتبع 30x: التحويل إلى /auth هو خبرُ انتهاء الجلسة، لا خطأً نُخفيه."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


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

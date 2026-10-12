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
import datetime
import html as _html_mod
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 30
RETRIES, RETRY_WAIT = 3, 2          # محاولاتُ النداء الواحد، وثواني التراجع الأولى
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


# لوحة سلة القديمة (`legacy=1`) تُخرج الطلبات HTML — وهذا ما نقرؤه حين لا توكن:
# قائمة الطلبات صفحةً صفحة، ثم صفحة كل طلب وفيها الكود والسجل وملاحظة العميل.
LIST_PATH = "/orders?page={page}&sort_by=created_at-desc"
ORDER_PAGE = "/orders/order/{sid}"
# نافذة «بيانات المنتج» في اللوحة القديمة (تبويب الأكواد المتاحة) — HTML فيه textarea لكل كود.
PRODUCT_CODES_PATH = "/products/{pid}/details?product_type=codes"

_EN_MONTHS = {m: i for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"), 1)}


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
        """نداءٌ واحد — ومهلةُ الشبكة أو انقطاعها العابر يُعاد ثلاثًا بتراجعٍ، فلا
        يُسقط سحبُ آلاف الطلبات بمصافحة SSL واحدة انتهت مهلتها."""
        url = path if path.startswith("http") else self.base + path
        req = urllib.request.Request(url, headers={
            "Cookie": self.cookie, "User-Agent": UA, "Accept": accept,
            "X-Requested-With": "XMLHttpRequest", "Referer": self.base + "/orders",
        })
        opener = urllib.request.build_opener(_NoRedirect)
        last = None
        for attempt in range(RETRIES):
            try:
                with opener.open(req, timeout=TIMEOUT) as r:
                    return r.status, r.headers, r.read()
            except urllib.error.HTTPError as e:
                # ‏429 (حدّ المعدّل) و5xx عابرة: تُمهَل اللوحة (Retry-After إن قالته) ويُعاد.
                if e.code == 429 or e.code >= 500:
                    last = e
                    if attempt + 1 < RETRIES:
                        time.sleep(_retry_after(e.headers, RETRY_WAIT * (2 ** attempt) * (3 if e.code == 429 else 1)))
                        continue
                    return e.code, e.headers, (e.read() if e.fp else b"")
                return self._http_error(e)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                last = e
                if attempt + 1 < RETRIES:
                    time.sleep(RETRY_WAIT * (2 ** attempt))
        raise WebError("تعذّر الوصول للوحة سلة: %s" % (getattr(last, "reason", last)))

    def _http_error(self, e):
        if e.code in (301, 302, 303, 307, 308):
            return e.code, e.headers, b""
        body = e.read() if e.fp else b""
        if e.code in (401, 403):
            raise denied_error(e.code, e.headers, body)
        return e.code, e.headers, body

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

    def _html(self, path):
        """صفحة HTML من اللوحة، أو SessionExpired إن حُوّلنا للدخول."""
        code, headers, body = self._get(path, accept="text/html")
        loc = headers.get("Location", "") if headers else ""
        if code in (301, 302, 303, 307, 308) and AUTH_REDIRECT.search(loc):
            raise SessionExpired("انتهت الجلسة — الصق كوكيز جديدة من لوحة سلة")
        if code != 200 or not body:
            return ""
        text = body.decode("utf-8", "replace")
        if "/auth" in text[:600] and "<form" in text[:3000] and "login" in text[:3000].lower():
            raise SessionExpired("أُعيد التحويل لصفحة الدخول — الصق كوكيز جديدة")
        return text

    def diagnose(self):
        """أوّل نداءٍ للوحة كما هو: الرمز، ومَن ردّ (Cloudflare؟)، وعنوان الصفحة —
        ليُعرف من خادمٍ لا نراه أهي جلسةٌ منتهية أم حجبُ عنوان الخادم أم غير ذلك."""
        out = {"ok": False, "code": 0, "server": "", "cf": "", "title": "", "verdict": ""}
        try:
            code, headers, body = self._get("/orders", accept="text/html")
        except (SessionExpired, WebError) as e:
            out["verdict"] = str(e)
            return out
        out["code"] = code
        out["server"] = str(headers.get("Server", "") if headers else "")
        out["cf"] = str(headers.get("cf-mitigated", "") if headers else "")
        text = body.decode("utf-8", "replace") if body else ""
        m = re.search(r"<title>(.*?)</title>", text, re.S | re.I)
        out["title"] = _WS.sub(" ", m.group(1)).strip()[:80] if m else ""
        loc = headers.get("Location", "") if headers else ""
        if code in (301, 302, 303, 307, 308):
            out["verdict"] = ("انتهت الجلسة — حُوّلنا لصفحة الدخول" if AUTH_REDIRECT.search(loc)
                              else "تحويل إلى %s" % loc[:80])
        elif code == 200:
            out["ok"] = True
            out["verdict"] = "الجلسة صالحة"
        else:
            out["verdict"] = "ردّت اللوحة %d" % code
        return out

    # ----------------------------- الاستعمال -----------------------------
    def orders_page(self, page=1):
        """صفحةٌ من قائمة الطلبات (HTML) → (صفوف، أهناك صفحةٌ تالية؟)."""
        return parse_orders_list(self._html(LIST_PATH.format(page=int(page))))

    def order_page(self, sid):
        """صفحة الطلب كاملةً كما يراها المشغّل — بمعرّفه في الرابط."""
        return self._html(ORDER_PAGE.format(sid=urllib.parse.quote(str(sid))))

    def order_details(self, sid):
        """الطلب محلَّلًا من صفحته بشكل طلب الواجهة (يفهمه renew_import)، أو None."""
        page = self.order_page(sid)
        return parse_order_page(page, sid) if page else None

    def product_codes(self, product_id):
        """أكواد منتجٍ رقمي المتاحة من اللوحة القديمة (غير مقنَّعة). الواجهة الجديدة
        (api.salla.dev …/codes) تُعيدها XXXX، أما نافذة «الأكواد المتاحة» في اللوحة
        القديمة فتُحمَّل من مسار details بالجلسة وفيها النصّ كاملًا."""
        return parse_product_codes(self._html(PRODUCT_CODES_PATH.format(pid=urllib.parse.quote(str(product_id)))))

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


# ============================ شكاوى العملاء ============================
# سجل «شكاوى العملاء» في لوحة سلة لا واجهة له في Admin API، فيُقرأ بالجلسة نفسها كالطلبات. مساره غير
# موثّق فتُجرَّب مرشّحات (JSON أولًا ثم صفحة HTML) ويُحفظ أوّل ما ردّ شكاوى، فلا يُخمَّن ثانيةً.
COMPLAINT_PATHS = (
    "/api/complaints?per_page={n}&page={p}",
    "/api/v1/complaints?per_page={n}&page={p}",
    "/complaints?format=json&per_page={n}&page={p}",
    "/customers/complaints?format=json&per_page={n}&page={p}",
    "/orders/complaints?format=json&per_page={n}&page={p}",
)
COMPLAINT_HTML_PATHS = ("/complaints?page={p}", "/customers/complaints?page={p}", "/orders/complaints?page={p}")
_C_ORDER_KEYS = ("order_reference", "order_reference_id", "reference_id", "order_number", "order_no", "order_id", "order")
_C_STATUS_KEYS = ("status", "state", "complaint_status")


def _looks_like_complaint(d):
    if not isinstance(d, dict):
        return False
    keys = set(d.keys())
    return bool(keys & {"id", "complaint_id", "number"}) and bool(keys & set(_C_STATUS_KEYS)) \
        and bool(keys & (set(_C_ORDER_KEYS) | {"customer", "content", "description", "type", "subject"}))


def _find_complaints(obj, depth=0):
    if depth > 6 or obj is None:
        return []
    if isinstance(obj, list):
        rows = [x for x in obj if _looks_like_complaint(x)]
        if rows:
            return rows
        for x in obj:
            r = _find_complaints(x, depth + 1)
            if r:
                return r
        return []
    if isinstance(obj, dict):
        for k in ("data", "complaints", "items", "results", "list"):
            if k in obj:
                r = _find_complaints(obj[k], depth + 1)
                if r:
                    return r
        for v in obj.values():
            r = _find_complaints(v, depth + 1)
            if r:
                return r
    return []


def _c_text(v):
    """قيمةٌ قد تكون نصًّا أو كائنًا (‏{name, slug} أو {reference_id} أو {date}) → نصّها."""
    if isinstance(v, dict):
        for k in ("name", "label", "title", "date", "reference_id", "number", "id", "slug"):
            if v.get(k) not in (None, ""):
                return str(v[k])
        return ""
    return "" if v is None else str(v)


# مفاتيح حالة الشكوى في اللوحة (slug) → ما تعرضه بالعربية، للعرض حين لا يأتي الاسم.
STATUS_NAMES = {"pending_merchant": "بانتظار رد التاجر", "awaiting_merchant": "بانتظار رد التاجر",
                "pending_customer": "بانتظار رد العميل", "awaiting_customer": "بانتظار رد العميل",
                "under_review": "قيد التحقق من سلة", "pending_salla": "قيد التحقق من سلة",
                "resolved": "تم الحل", "closed": "مغلقة"}


def normalize_complaint(d):
    """شكوى كما تعطيها اللوحة (بأي شكل) → {id, order, order_sid, customer, status, type, text, date, phone, url}.

    **رقم الطلب الذي يراه العميل هو `reference_id` الطلب**، لا معرّفه الداخلي (`order_id` / `order.id`): الأول
    يُكتب في `order`، والثاني في `order_sid` ليُحوَّل إلى رقمه بالواجهة إن لم يأتِ الرقم. ورقم الشكوى الظاهر
    (`number` / `reference_id` الشكوى نفسها) يُفضَّل على معرّفها الداخلي `id`."""
    ref, sid = "", ""
    o = d.get("order")
    if isinstance(o, dict):
        ref = _c_text(o.get("reference_id") or o.get("reference") or o.get("number") or "")
        sid = _c_text(o.get("id") or "")
    elif o not in (None, "", 0, {}):
        ref = _c_text(o)
    for k in ("order_reference", "order_reference_id", "order_number", "order_no", "order_ref"):
        if not ref and d.get(k) not in (None, "", 0):
            ref = _c_text(d[k])
    if not sid and d.get("order_id") not in (None, "", 0):
        sid = _c_text(d["order_id"])
    ref, sid = re.sub(r"\D", "", ref), re.sub(r"\D", "", sid)
    cust = d.get("customer")
    cust = ((cust.get("name") or (str(cust.get("first_name") or "") + " " + str(cust.get("last_name") or "")).strip())
            if isinstance(cust, dict) else str(cust or d.get("customer_name") or ""))
    st = next((d[k] for k in _C_STATUS_KEYS if d.get(k) not in (None, "")), "")
    status = _c_text(st).strip()
    slug = (st.get("slug") if isinstance(st, dict) else status) or ""
    status = STATUS_NAMES.get(str(slug).strip().lower(), status) if not re.search(r"[\u0600-\u06FF]", status) else status
    num = next((_c_text(d[k]) for k in ("number", "complaint_number", "reference_id", "reference", "complaint_id", "id")
                if d.get(k) not in (None, "")), "")
    cid = _c_text(d.get("id") or "")
    url = _c_text(d.get("url") or ((d.get("urls") or {}).get("admin") if isinstance(d.get("urls"), dict) else ""))
    if not url and cid:                                   # رابط الشكوى في اللوحة (مسارها المعتاد) ليُفتح مباشرة
        url = BASE + "/complaints/" + cid
    return {"id": num, "cid": cid, "order": ref, "order_sid": sid if sid != ref else "", "customer": cust.strip(), "status": status,
            "type": _c_text(d.get("type") or d.get("category") or d.get("subject") or d.get("reason")),
            "text": str(d.get("content") or d.get("description") or d.get("message") or d.get("comment") or "")[:600],
            "date": _c_text(d.get("created_at") or d.get("date") or d.get("updated_at")),
            "phone": _c_text((d.get("customer") or {}).get("mobile") if isinstance(d.get("customer"), dict) else ""),
            "url": url}


_C_TR = re.compile(r"<tr[^>]*>(?P<body>.*?)</tr>", re.S | re.I)
_C_TD = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_C_HREF = re.compile(r'href="([^"]*complaint[^"]*)"', re.I)


def parse_complaints_html(page):
    """صفوف جدول سجل الشكاوى في HTML اللوحة: رقم الشكوى، والعميل، ورقم الطلب، والحالة — بالترتيب الذي
    يعرضه السجل (رقم الشكوى · اسم العميل · رقم الطلب · الحالة)، وتُؤخذ الحالة من خليةٍ فيها «بانتظار» أو
    «مغلقة» أو «قيد» أينما كانت. صفوفٌ بلا رقمين (شكوى وطلب) تُهمل."""
    out = []
    for m in _C_TR.finditer(page or ""):
        cells = [_text(c) for c in _C_TD.findall(m.group("body"))]
        if len(cells) < 3:
            continue
        nums = [re.sub(r"\D", "", c) for c in cells if re.fullmatch(r"\s*#?\d+\s*", c or "")]
        status = next((c for c in cells if re.search(r"بانتظار|مغلق|قيد|تم الحل|محلول", c)), "")
        if len(nums) < 2 or not status:
            continue
        name = next((c for c in cells if c and not re.fullmatch(r"#?\d+", c) and c != status
                     and not re.search(r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}", c)), "")
        href = _C_HREF.search(m.group("body"))
        out.append({"id": nums[0], "order": nums[1], "order_sid": "", "customer": name, "status": status, "type": "", "text": "",
                    "date": next((c for c in cells if re.search(r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}", c)), ""),
                    "phone": "", "url": (_html_mod.unescape(href.group(1)) if href else BASE + "/complaints/" + nums[0])})
    return out


def _session_complaints(self, limit=50, pages=3):
    """شكاوى العملاء من اللوحة بالجلسة (أحدثها أولًا كما يعطيها السجل): JSON بمرشّحاته، وإلا جدول HTML.
    ويُحفظ أوّل مسارٍ نجح. ← قائمة normalize_complaint، و[] إن لم يُعرف مسار."""
    rows = []
    tpl = getattr(self, "_complaints_path", None)
    cands = ([tpl] if tpl else []) + [p for p in COMPLAINT_PATHS if p != tpl]
    for tpl in cands:
        got = _find_complaints(self._json(tpl.format(n=int(limit), p=1)))
        if got:
            self._complaints_path = tpl
            rows = [normalize_complaint(x) for x in got]
            for pg in range(2, pages + 1):
                if len(rows) >= limit:
                    break
                more = _find_complaints(self._json(tpl.format(n=int(limit), p=pg)))
                if not more:
                    break
                rows += [normalize_complaint(x) for x in more]
            return rows[:limit]
    tpl = getattr(self, "_complaints_html", None)
    for tpl in ([tpl] if tpl else []) + [p for p in COMPLAINT_HTML_PATHS if p != tpl]:
        got = parse_complaints_html(self._html(tpl.format(p=1)))
        if got:
            self._complaints_html = tpl
            for pg in range(2, pages + 1):
                if len(got) >= limit:
                    break
                more = parse_complaints_html(self._html(tpl.format(p=pg)))
                if not more or more[0]["id"] == got[0]["id"]:
                    break
                got += more
            return got[:limit]
    return []


Session.complaints = _session_complaints


_CF_CHALLENGE = re.compile(r"(?i)just a moment|cf-chl|challenge-platform|attention required|cloudflare")


def _retry_after(headers, default):
    """ثواني الانتظار من Retry-After إن أعطتها اللوحة (حتى دقيقة)، وإلا الافتراضي."""
    try:
        v = float(str((headers or {}).get("Retry-After", "")).strip() or 0)
        return min(60.0, v) if v > 0 else default
    except ValueError:
        return default


def denied_error(code, headers, body):
    """‏401/403 ليس دائمًا جلسةً منتهية: Cloudflare يحجب عناوين الخوادم بتحدٍّ لا يجتازه
    خادم. التمييز بترويساته وصفحته — فلا يُرسَل تنبيه «انتهت الجلسة» ولا تُطلب كوكيز
    جديدة لن تنفع، بل يُقال الحقّ: عنوان الخادم محجوب."""
    h = headers or {}
    text = (body or b"")[:4000].decode("utf-8", "replace")
    cf = (str(h.get("cf-mitigated", "")).lower() == "challenge"
          or ("cloudflare" in str(h.get("Server", "")).lower() and _CF_CHALLENGE.search(text) is not None
              and "salla" not in text[:2000].lower()))
    if cf:
        return WebError("Cloudflare يحجب عنوان الخادم (%d) — ليست الكوكيز: الوصول للوحة سلة "
                        "من هذا الخادم ممنوع، فيُسحب من جهازٍ آخر أو بعنوان IP آخر" % code)
    return SessionExpired("الجلسة غير مقبولة (%d) — الصق الكوكيز من جديد" % code)


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

# ============================ قراءة HTML اللوحة ============================
_ROW = re.compile(r'<tr[^>]*class="[^"]*row_order[^"]*"(?P<attrs>[^>]*)>(?P<body>.*?)</tr>', re.S)
_ATTR = re.compile(r'data-([\w-]+)="([^"]*)"')
_NEXT = re.compile(r'class="[^"]*next-page-link[^"]*"')
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _text(frag):
    return _WS.sub(" ", _html_mod.unescape(_TAG.sub(" ", str(frag or "")))).strip()


def _between(html, start_pat, end_pat, flags=re.S):
    m = re.search(start_pat + r"(.*?)" + end_pat, html, flags)
    return m.group(1) if m else ""


_CODE_AREA = re.compile(r'<textarea\b([^>]*)>(.*?)</textarea>', re.S | re.I)


def parse_product_codes(page):
    """نصوص الأكواد المتاحة من نافذة المنتج في اللوحة القديمة: كل كود في
    <textarea name="code_content[]"> داخل #codes_list. القالب المخفي (clone_code)
    فارغ فيُستبعد، وكذلك مربّع الإضافة الجماعية (لا اسم code_content له)."""
    html = str(page or "")
    out = []
    for attrs, body in _CODE_AREA.findall(html):
        if "code_content" not in attrs:
            continue
        text = _html_mod.unescape(body).strip()
        if text:
            out.append(text)
    return out


def parse_orders_list(page):
    """صفحة قائمة الطلبات → ([{sid, order, customer, status, total, admin_url}], تالية؟).

    `sid` معرّف الطلب في الرابط (ما تسمّيه الواجهة `urls.admin`)، و`order` رقمه
    الظاهر للعميل (#293119145)."""
    rows = []
    for m in _ROW.finditer(page or ""):
        attrs = dict(_ATTR.findall(m.group("attrs")))
        sid = attrs.get("order_id") or attrs.get("row-order-id") or ""
        if not sid:
            continue
        body = m.group("body")
        no = _text(_between(body, r'class="order-number[^"]*"[^>]*>', r"</div>")).lstrip("#")
        if not no:
            prev = re.search(r'data-order-preview-id="(\d+)"', body)
            no = prev.group(1) if prev else ""
        rows.append({
            "sid": sid, "order": no,
            "customer": _WS.sub(" ", attrs.get("customer", "")).strip()
            or _text(_between(body, r'class="order-customer-name"[^>]*>', r"</div>")),
            "status": _text(_between(body, r'class="order-status"[^>]*>', r"</div>")).lstrip("● ").strip(),
            "total": _text(_between(body, r'class="order-total[^"]*"[^>]*>', r"</td>")),
            "admin_url": attrs.get("order-link") or (BASE + ORDER_PAGE.format(sid=sid)),
        })
    return rows, bool(_NEXT.search(page or ""))


def _parse_panel_date(s):
    """‏«Saturday 10 October 2026 | 08:20 PM» → «2026-10-10»، وإلا ""."""
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", str(s or ""))
    if m and m.group(2).lower() in _EN_MONTHS:
        try:
            return datetime.date(int(m.group(3)), _EN_MONTHS[m.group(2).lower()],
                                 int(m.group(1))).isoformat()
        except ValueError:
            return ""
    m = re.search(r"(\d{4}-\d{2}-\d{2})", str(s or ""))
    return m.group(1) if m else ""


def _initial_data(page):
    m = re.search(r"var\s+initialData\s*=\s*(\{.*?\})\s*;", page or "", re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except ValueError:
        return {}


def parse_order_page(page, sid=""):
    """صفحة الطلب → قاموس بشكل طلب الواجهة: id وreference_id وstatus وdate
    وcustomer وitems (ولكل منتج `codes` بنصوص أكواده) — ومعه `notes` من سجلّ
    الطلب و`customer_note`، فيُفتَّش عن الاشتراك في الكود ثم في الملاحظات."""
    page = page or ""
    data = _initial_data(page)
    hist = [h for h in (data.get("statusHistories") or []) if isinstance(h, dict)]

    no = _text(_between(page, r'class="rec-order-no"[^>]*>', r"(?:<div|</div>)"))
    no = re.sub(r"\D", "", no)
    status = _text(_between(page, r'id="order_status_btn"[^>]*>', r"</span>"))
    date = _parse_panel_date(_text(_between(page, r'class="rec-order-date"[^>]*>', r"</div>")))
    if not date:
        times = [str((h.get("created_at") or {}).get("time") or "") for h in hist]
        times = [t for t in times if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t)]
        date = min(times) if times else ""

    name = _text(_between(page, r'<div data-card-customer-buyer.*?<a href="[^"]*/customers/[^"]*"[^>]*>', r"</a>"))
    phone = ""
    m = re.search(r'href="tel:([+\d]+)"', page)
    if m:
        phone = m.group(1)
    else:
        m = re.search(r'href="https://wa\.me/(\d+)"', page)
        phone = m.group(1) if m else ""

    items = []
    products_tbl = _between(page, r"المنتجات\s*</h6>", r"</table>")
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", products_tbl, re.S):
        if "media-heading" not in tr and "no-margin" not in tr:
            continue
        pid = re.search(r"/products/(\d+)", tr)
        pname = _text(_between(tr, r'<h6 class="no-margin">', r"</h6>"))
        if not pname:
            continue
        codes = [_text(c) for c in re.findall(
            r"الكود\s*:?\s*</span>\s*<span[^>]*>(.*?)</span>", tr, re.S)]
        qty = _text(_between(tr, r'data-title="الكمية"[^>]*>', r"</td>"))
        qty = int(re.sub(r"\D", "", qty) or 1) if qty else 1
        price = _text(_between(tr, r'data-title="السعر"[^>]*>', r"</td>"))
        items.append({"product_id": pid.group(1) if pid else "", "name": pname, "sku": "",
                      "quantity": qty, "price": price, "codes": codes})

    notes = [str(h.get("note") or "") for h in hist if h.get("note")]
    cnote = _text(_between(page, r"ملاحظة العميل\s*</h6>.*?<div class=\"panel-body\">", r"</div>"))
    if "لا توجد ملاحظات" in cnote:
        cnote = ""
    sid = str(sid or data.get("order_id") or "")
    return {"id": sid, "reference_id": no, "status": {"name": status},
            "date": {"date": date}, "customer": {"name": name, "mobile": phone},
            "items": items, "notes": notes, "customer_note": cnote,
            "urls": {"admin": BASE + ORDER_PAGE.format(sid=sid)}}


def order_notes(order):
    """ملاحظات الطلب التي قد يُكتب فيها الاشتراك حين يخلو منه الكود: سجلّ الطلب
    (ملاحظاته بترتيبها) ثم ملاحظة العميل."""
    out = [n for n in (order.get("notes") or []) if n]
    if order.get("customer_note"):
        out.append(order["customer_note"])
    return out


def order_texts(order):
    """نصوص الطلب كلها بترتيب البحث: الأكواد، ثم الملاحظات."""
    out = []
    for it in order.get("items") or []:
        out.extend(c for c in (it.get("codes") or []) if c)
    return out + order_notes(order)


def admin_token(url):
    """‏`https://s.salla.sa/orders/order/<token>` → `<token>`. الواجهة تعطي هذا
    الرابط في `urls.admin` لكل طلب، فهو الجسر بين الواجهة واللوحة."""
    m = re.search(r"/orders/order/([A-Za-z0-9_-]{8,})", str(url or ""))
    return m.group(1) if m else ""

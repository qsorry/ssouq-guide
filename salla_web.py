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


# لوحة سلة القديمة (`legacy=1`) تُخرج الطلبات HTML — وهذا ما نقرؤه حين لا توكن:
# قائمة الطلبات صفحةً صفحة، ثم صفحة كل طلب وفيها الكود والسجل وملاحظة العميل.
LIST_PATH = "/orders?page={page}&sort_by=created_at-desc"
ORDER_PAGE = "/orders/order/{sid}"

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

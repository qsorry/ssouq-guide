#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
موصّل متجر سلة (Salla) — قراءة الطلبات آليًا لتسليم الاشتراك على واتساب.

مصدران للطلب:
  • Webhook فوري: سلة تُرسل `order.created`/`order.updated`/`order.payment.updated`
    إلى مسارنا، موقَّعة بـ HMAC-SHA256 على جسم الطلب بمفتاح الويبهوك (استراتيجية
    "Signature")، أو برمز ثابت في ترويسة Authorization (استراتيجية "Token").
  • سحب دوري: Salla Admin API v2 (`/admin/v2/orders`) بتوكن Bearer، للاحتياط.

stdlib فقط. لا يُسجَّل أي سرّ. التحليل متسامح: أشكال حمولة سلة تختلف قليلًا بين
الويبهوك وواجهة الإدارة، فنقرأ عدة مسارات محتملة للحقل الواحد.
"""
import hmac
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 20
UA = "ssouq-guide-salla/1.0"
API = "https://api.salla.dev"


class SallaError(RuntimeError):
    pass


# ----------------------------- التوقيع -----------------------------
def sign(secret: str, body: bytes) -> str:
    return hmac.new(str(secret).encode(), body or b"", hashlib.sha256).hexdigest()


def verify(secret: str, token: str, body: bytes, headers) -> bool:
    """يتحقّق من أصالة الويبهوك: توقيع HMAC (Signature) أو رمز ثابت (Token).

    headers: كائن يدعم .get(name) بلا حساسية لحالة الأحرف (مثل http.server headers).
    يُقبل الطلب إذا طابق أيّ من الاستراتيجيتين المضبوطتين."""
    def h(name):
        try:
            return headers.get(name) or headers.get(name.lower()) or ""
        except Exception:
            return ""

    if secret:
        got = str(h("x-salla-signature") or h("X-Salla-Signature")).strip()
        got = got.split("=", 1)[1] if "=" in got and got.split("=", 1)[0].lower() in ("sha256", "hmac") else got
        if got and hmac.compare_digest(got, sign(secret, body)):
            return True
    if token:
        auth = str(h("authorization") or h("Authorization")).strip()
        auth = auth.split(" ", 1)[1] if " " in auth else auth
        if auth and hmac.compare_digest(auth, str(token)):
            return True
    return False


# ----------------------------- الهاتف -----------------------------
def normalize_phone(mobile, code="", default_cc="966") -> str:
    """رقم واتساب دوليًّا بالأرقام فقط (بلا +/مسافات)، بدمج مفتاح الدولة إن لزم."""
    m = re.sub(r"\D", "", str(mobile or ""))
    cc = re.sub(r"\D", "", str(code or "")) or str(default_cc or "")
    if not m:
        return ""
    if m.startswith("00"):            # دولي صريح (00<code><num>) — لا نضيف مفتاحًا
        return m[2:]
    if m.startswith("0"):             # محلي (05..) → استبدل الصفر بمفتاح الدولة
        return cc + m[1:]
    if cc and not m.startswith(cc) and len(m) <= 10:   # محلي بلا صفر → أضِف المفتاح
        return cc + m
    return m


# ----------------------------- تحليل الطلب -----------------------------
def _first(d, *paths):
    """يرجّع أول قيمة غير فارغة من عدة مسارات مثل "data.customer.mobile"."""
    for p in paths:
        cur = d
        ok = True
        for key in p.split("."):
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                ok = False
                break
        if ok and cur not in (None, "", [], {}):
            return cur
    return None


def _status_name(order) -> str:
    st = _first(order, "status", "status.name", "status.slug")
    if isinstance(st, dict):
        st = st.get("slug") or st.get("name") or ""
    return str(st or "").strip().lower()


def parse_order(payload: dict) -> dict:
    """يحوّل حمولة سلة (ويبهوك أو API) إلى شكل موحّد نتعامل معه."""
    event = str(payload.get("event", "")).strip()
    order = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    order = order or {}

    oid = _first(order, "id", "order_id", "reference_id")
    ref = _first(order, "reference_id", "reference", "id")

    fn = _first(order, "customer.first_name", "customer.name") or ""
    ln = _first(order, "customer.last_name") or ""
    name = (str(fn) + " " + str(ln)).strip() or str(_first(order, "customer.full_name") or "").strip()
    mobile = _first(order, "customer.mobile", "customer.phone", "receiver.phone")
    code = _first(order, "customer.mobile_code", "customer.country_code", "customer.mobile_country_code") or ""

    items = []
    raw_items = _first(order, "items", "order.items", "products") or []
    if isinstance(raw_items, dict):
        raw_items = list(raw_items.values())
    for it in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(it, dict):
            continue
        pid = _first(it, "product.id", "product_id", "id")
        pname = _first(it, "product.name", "name", "product_name") or ""
        sku = _first(it, "product.sku", "sku") or ""
        qty = _first(it, "quantity", "qty") or 1
        try:
            qty = int(qty)
        except (TypeError, ValueError):
            qty = 1
        items.append({"product_id": str(pid) if pid is not None else "",
                      "name": str(pname), "sku": str(sku), "quantity": max(1, qty)})

    return {
        "event": event,
        "order_id": str(oid) if oid is not None else "",
        "reference": str(ref) if ref is not None else "",
        "status": _status_name(order),
        "customer_name": name,
        "phone": normalize_phone(mobile, code),
        "items": items,
    }


PAID_STATES = ("completed", "delivered", "paid", "in_progress", "under_review",
               "processing", "shipped", "payed")


def is_paid(order: dict) -> bool:
    """هل الطلب مدفوع/مؤكَّد؟ (نتجنّب التسليم لطلب ملغى أو بانتظار الدفع)."""
    st = order.get("status", "")
    if not st:
        return True  # بعض الحمولات لا تحمل الحالة صراحةً — لا نحجب
    if any(x in st for x in ("cancel", "refund", "declin", "fail", "pending", "restor")):
        return False
    return True


# ----------------------------- سحب من الـ API -----------------------------
def _get(url, token):
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + str(token), "Accept": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace") if e.fp else ""
        raise SallaError("سلة API %s: %s" % (e.code, raw[:200]))
    except (urllib.error.URLError, ValueError) as e:
        raise SallaError("تعذّر الوصول إلى سلة: %s" % (getattr(e, "reason", e)))


def fetch_orders(token: str, per_page: int = 25, page: int = 1) -> list:
    """أحدث الطلبات من واجهة الإدارة (للسحب الدوري)، محلَّلةً بالشكل الموحّد."""
    d = _get("%s/admin/v2/orders?per_page=%d&page=%d" % (API, per_page, page), token)
    return [parse_order({"data": o}) for o in (d.get("data") or []) if isinstance(o, dict)]


def orders_page(token: str, page: int = 1, per_page: int = 50) -> tuple:
    """صفحة طلبات خامًا + معلومات الترقيم: (الطلبات، {page, pages, total}).

    خامًا لا محلَّلةً، لأن فهرس التجديد يحتاج حقولًا لا يحملها `parse_order`
    (تاريخ الطلب، وحالته، وأسماء بنوده وكمياتها)."""
    d = _get("%s/admin/v2/orders?per_page=%d&page=%d&sort_by=created_at"
             % (API, per_page, page), token)
    rows = [o for o in (d.get("data") or []) if isinstance(o, dict)]
    p = d.get("pagination") or {}
    return rows, {"page": int(p.get("currentPage") or page),
                  "pages": int(p.get("totalPages") or 1),
                  "total": int(p.get("total") or len(rows))}


def order_histories(token: str, order_id, page: int = 1) -> list:
    """سجل الطلب: التعليقات والأنشطة. بيانات الاشتراك تُكتب هنا تعليقًا
    (‏`Host: … Username: … Password: …`) ولا يُخرجها تصدير سلة — فهذا هو
    المكان الوحيد الذي تُقرأ منه."""
    d = _get("%s/admin/v2/orders/%s/histories?page=%d" % (API, order_id, page), token)
    return [h for h in (d.get("data") or []) if isinstance(h, dict)]


def history_notes(token: str, order_id) -> str:
    """ملاحظات سجل الطلب مجموعةً في نصّ واحد، صالحًا لقارئ الاعتمادات."""
    try:
        rows = order_histories(token, order_id)
    except SallaError:
        return ""
    return "\n".join(str(h.get("note") or "") for h in rows if h.get("note"))

# -*- coding: utf-8 -*-
"""خريطة موقع المتجر (ssouq.com) مُولَّدة من منتجاته الحيّة.

خريطة سلة الخاصة بالمتجر مجمَّدة ولا تُحدَّث، ولا يمكننا رفع ملف على ssouq.com.
فتُبنى هنا على guide.ssouq.com وتُقدَّم على /store-sitemap.xml، ويُثبت ملكيتها
بسطر Sitemap في robots.txt الخاص بـ ssouq.com — وهذه طريقة الإرسال المتقاطع
التي يوثّقها جوجل.

مصدر البيانات:
  • الافتراضي: واجهة المتجر العامة (بلا أي مفتاح سري) — لكنها تُرجع 15 منتجًا
    كحدّ أقصى وتتجاهل الترقيم. فإذا تجاوز المتجر 15 منتجًا حيًّا سقط الباقي
    صامتًا، ولذلك تُعلَن الحالة في تعليق داخل الـ XML وفي /store-sitemap.json.
  • الأكمل: ضع SALLA_ADMIN_TOKEN في متغيّرات البيئة فتُستعمل واجهة الإدارة
    بترقيم كامل بلا حدّ، ويُصفّى المخفي وغير المعروض على الويب.
"""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

STORE_ID = os.environ.get("SALLA_STORE_ID", "831097886")
STORE_URL = os.environ.get("SALLA_STORE_URL", "https://ssouq.com").rstrip("/")
CATEGORY = os.environ.get("SALLA_CATEGORY_ID", "993357185")
TOKEN = os.environ.get("SALLA_ADMIN_TOKEN", "").strip()
API = os.environ.get("SALLA_API", "https://api.salla.dev").rstrip("/")   # يُغيَّر في الاختبارات وحدها
TTL = int(os.environ.get("STORE_SITEMAP_TTL", "3600"))
TIMEOUT = 12
# واجهة سلة تحجب وكيل urllib الافتراضي بـ403، فنرسل وكيلًا صريحًا.
UA = "Mozilla/5.0 (compatible; ssouq-sitemap/1.0; +https://guide.ssouq.com/)"
PUBLIC_CAP = 15          # الحد الذي تفرضه الواجهة العامة
EXTRA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "static", "store-extra-urls.json")

_lock = threading.Lock()
_cache = {"at": 0.0, "xml": None, "meta": None}


def _get(url, headers):
    req = urllib.request.Request(url, headers=dict(headers, **{"User-Agent": UA}))
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _from_public():
    """المنتجات المعروضة على الواجهة — ما تراه الواجهة هو ما يراه الزائر."""
    data = _get(f"{API}/store/v1/products?per_page=50",
                {"Store-Identifier": STORE_ID, "Accept": "application/json"})
    items = []
    for p in data.get("data", []):
        url = (p.get("url") or "").strip()
        if url.startswith(STORE_URL):
            items.append({"url": url, "lastmod": None})
    return items, ("public", len(data.get("data", [])) >= PUBLIC_CAP)


def _from_admin():
    """واجهة الإدارة: ترقيم كامل، ونصفّي المخفي وغير المعروض على الويب."""
    items, page = [], 1
    while page <= 40:
        d = _get(f"{API}/admin/v2/products?per_page=50&page={page}",
                 {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"})
        rows = d.get("data", [])
        if not rows:
            break
        for p in rows:
            if p.get("status") != "sale":
                continue
            if not (p.get("show_in") or {}).get("web", True):
                continue
            url = ((p.get("urls") or {}).get("customer") or p.get("url") or "").strip()
            if url.startswith(STORE_URL):
                items.append({"url": url, "lastmod": (p.get("updated_at") or "")[:10] or None})
        cur = (d.get("pagination") or {})
        if not cur.get("totalPages") or page >= cur["totalPages"]:
            break
        page += 1
    return items, ("admin", False)


def _extra():
    """روابط تكميلية لما تسقطه الواجهة العامة بسبب حدّ الـ15."""
    try:
        with open(EXTRA_FILE, encoding="utf-8") as f:
            return [u.strip() for u in json.load(f).get("urls", [])
                    if u.strip().startswith(STORE_URL)]
    except (OSError, ValueError):
        return []


def _esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _build():
    try:
        items, (source, capped) = (_from_admin() if TOKEN else _from_public())
        error = None
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, KeyError, TimeoutError) as e:
        items, source, capped, error = [], "error", False, str(e)[:160]

    # مع التوكن تكون النتيجة كاملة فلا حاجة للتكميلية
    extra = [] if source == "admin" else [{"url": u, "lastmod": None} for u in _extra()]

    # نزيل التكرار مع الحفاظ على الترتيب
    seen, uniq = set(), []
    for it in items + extra:
        if it["url"] not in seen:
            seen.add(it["url"])
            uniq.append(it)

    rows = [
        f"  <url>\n    <loc>{_esc(STORE_URL)}/</loc>\n"
        f"    <changefreq>daily</changefreq>\n    <priority>1.0</priority>\n  </url>",
        f"  <url>\n    <loc>{_esc(STORE_URL)}/الاشتراكات-الرقمية/c{CATEGORY}</loc>\n"
        f"    <changefreq>daily</changefreq>\n    <priority>0.9</priority>\n  </url>",
    ]
    for it in uniq:
        lm = f"\n    <lastmod>{it['lastmod']}</lastmod>" if it["lastmod"] else ""
        rows.append(f"  <url>\n    <loc>{_esc(it['url'])}</loc>{lm}\n"
                    f"    <changefreq>weekly</changefreq>\n    <priority>0.8</priority>\n  </url>")

    notes = [f"المصدر: {source} · المنتجات: {len(uniq)}"
             + (f" (منها {len(extra)} من القائمة التكميلية)" if extra else "")]
    if capped:
        notes.append("تحذير: الواجهة العامة تُرجع 15 منتجًا كحدّ أقصى وتتجاهل الترقيم، "
                     "فقد تكون هناك منتجات حيّة خارج الخريطة. ضع SALLA_ADMIN_TOKEN "
                     "لتغطية كاملة تلقائية.")
    if error:
        notes.append(f"تعذّر جلب المنتجات: {error} — الخريطة تحمل الصفحات الثابتة فقط.")

    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           + "".join(f"<!-- {_esc(n)} -->\n" for n in notes)
           + '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           + "\n".join(rows) + "\n</urlset>\n")
    meta = {"source": source, "products": len(uniq), "from_extra": len(extra),
            "capped": capped, "error": error, "urls": [i["url"] for i in uniq]}
    return xml.encode("utf-8"), meta


def _fresh():
    """يُرجع (xml, meta) من الكاش، ويعيد البناء عند انتهاء مدته.

    إن فشل البناء ولدينا نسخة سابقة صالحة نُبقيها بدل تقديم خريطة ناقصة."""
    with _lock:
        now = time.time()
        if _cache["xml"] is None or now - _cache["at"] > TTL:
            xml, meta = _build()
            if meta["source"] == "error" and _cache["xml"] is not None:
                _cache["at"] = now - TTL + 120      # أعد المحاولة بعد دقيقتين
            else:
                _cache.update(at=now, xml=xml, meta=meta)
        return _cache["xml"], _cache["meta"]


def sitemap():
    return _fresh()[0]


def status():
    meta = dict(_fresh()[1])
    meta["cached_for_seconds"] = int(max(0, TTL - (time.time() - _cache["at"])))
    return json.dumps(meta, ensure_ascii=False, indent=1).encode("utf-8")


# ---------- منتجات المتجر للاختيار منها (جائزة مسابقة التوقّعات) ----------
PRODUCTS_TTL = 600
_plock = threading.Lock()
_products = {"at": 0.0, "key": None, "data": None}


def _amount(v):
    if isinstance(v, dict):                          # الإدارية: {amount, currency}، والعامة رقم
        v = v.get("amount")
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def product_of(p):
    """منتجٌ من واجهة سلة (العامة أو الإدارية) بشكلٍ واحد، أو None لما ليس معروضًا في المتجر:
    {id, name, url, price, img, available} — والنافد (out) يبقى: الجائزة تُسلَّم بيدٍ لا من المخزون."""
    if not isinstance(p, dict):
        return None
    url = ((p.get("urls") or {}).get("customer") or p.get("url") or "").strip()
    status, pid = str(p.get("status") or ""), str(p.get("id") or "")
    if not url.startswith(STORE_URL + "/") or status not in ("sale", "out") or not pid.isdigit():
        return None
    if not (p.get("show_in") or {}).get("web", True):
        return None
    img = p.get("image") if isinstance(p.get("image"), dict) else {}
    img = str(img.get("url") or p.get("main_image") or p.get("thumbnail") or "")
    return {"id": pid, "name": re.sub(r"\s+", " ", str(p.get("name") or "")).strip(), "url": url,
            "price": _amount(p.get("sale_price")) or _amount(p.get("price")),
            "img": img if img.startswith("https://") else "",
            "available": status == "sale" and not p.get("is_out_of_stock")}


def _products_admin(token):
    out, page = [], 1
    while page <= 40:
        d = _get(f"{API}/admin/v2/products?per_page=50&page={page}",
                 {"Authorization": f"Bearer {token}", "Accept": "application/json"})
        rows = d.get("data") or []
        out += [x for x in map(product_of, rows) if x]
        cur = d.get("pagination") or {}
        if not rows or not cur.get("totalPages") or page >= cur["totalPages"]:
            break
        page += 1
    return out


def _products_public(extra_ids):
    """الواجهة العامة تعطي 15 منتجًا وتتجاهل الترقيم؛ وما سقط منها ويعرفه الدليل يُطلب بتفاصيله."""
    head = {"Store-Identifier": STORE_ID, "Accept": "application/json"}
    out = [x for x in map(product_of, _get(f"{API}/store/v1/products?per_page=50", head).get("data") or []) if x]
    have = {x["id"] for x in out}
    for pid in extra_ids:
        pid = str(pid).lstrip("p")
        if not pid.isdigit() or pid in have:
            continue
        try:
            x = product_of(_get(f"{API}/store/v1/products/{pid}/details", head).get("data"))
        except (urllib.error.URLError, ValueError, TimeoutError):
            x = None                                  # منتجٌ حُذف أو تعذّر: لا يُسقط القائمة
        if x:
            out.append(x)
            have.add(pid)
    return out


def products(token="", extra_ids=(), fresh=False):
    """منتجات المتجر الحيّة ← (القائمة، المصدر، الخطأ). بالرمز الإداري كاملةً؛ وبدونه (أو إن رُفض)
    الواجهة العامة ومعها `extra_ids`. عشر دقائق في الذاكرة، والفشل يُبقي آخر قائمةٍ صالحة."""
    token = (token or TOKEN or "").strip()
    key = (bool(token), tuple(extra_ids))
    with _plock:
        c = dict(_products)
    if not fresh and c["data"] and c["key"] == key and time.time() - c["at"] < PRODUCTS_TTL:
        return c["data"]
    items, source, error = [], "", ""
    if token:
        try:
            items, source = _products_admin(token), "admin"
        except (urllib.error.URLError, ValueError, KeyError, TimeoutError) as e:
            error = "الواجهة الإدارية: " + str(e)[:120]
    if not items:
        try:
            items, source = _products_public(extra_ids), "public"
        except (urllib.error.URLError, ValueError, KeyError, TimeoutError) as e:
            error = (error + " · " if error else "") + str(e)[:120]
    with _plock:
        if items:
            _products.update(at=time.time(), key=key, data=(items, source, ""))
            return _products["data"]
        if _products["data"]:                         # فشلٌ عابر: القائمة السابقة أصلح من لا شيء
            return (_products["data"][0], _products["data"][1], error)
    return [], "error", error

# -*- coding: utf-8 -*-
"""ربط صفحة الإحصائيات بجوجل: Google Analytics 4 (‏Data API) وSearch Console — بحساب خدمة (service account).

بلا مكتبات خارجية: المفتاح الخاص في ملف JSON يُقرأ من PEM (‏PKCS#8 كما تنزّله جوجل، أو PKCS#1)، ويُوقَّع به
JWT بـ RS256 (‏PKCS#1 v1.5 مع SHA-256) بحساب الأعداد الكبيرة في بايثون نفسها، ثم يُستبدل برمز وصولٍ صالحٍ ساعة
يُحفظ في الذاكرة حتى قبيل انتهائه. والتقارير تُحفظ دقائق فلا تُستهلك حصة جوجل مع كل فتحٍ للصفحة.

خطوات الربط (مرةً واحدة، وتُشرح في الصفحة نفسها):
  1. Google Cloud: مشروع ← فعّل «Google Analytics Data API» و«Google Search Console API» (و«Google Analytics
     Admin API» ليُعرض رقم الخاصية وحده) ← حساب خدمة ← مفتاح JSON.
  2. Google Analytics: الإدارة ← إدارة الوصول إلى الخاصية ← أضف بريد حساب الخدمة «مشاهد» (Viewer).
  3. Search Console: الإعدادات ← المستخدمون والأذونات ← أضف البريد نفسه (كامل الصلاحية لإرسال خريطة الموقع).
"""
import base64
import datetime
import hashlib
import json
import os
import re
import threading
import time
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError

TOKEN_URL = os.environ.get("XM_GOOGLE_TOKEN_URL", "https://oauth2.googleapis.com/token")
GA_API = os.environ.get("XM_GA_API", "https://analyticsdata.googleapis.com/v1beta")
GA_ADMIN = os.environ.get("XM_GA_ADMIN_API", "https://analyticsadmin.googleapis.com/v1beta")
GSC_API = os.environ.get("XM_GSC_API", "https://www.googleapis.com/webmasters/v3")
AUD = "https://oauth2.googleapis.com/token"
# الكتابة في Search Console لإرسال خريطة الموقع وحدها؛ والقراءة تكفيها صلاحية «مقيّد» لمن لا يريد ذلك
SCOPES = "https://www.googleapis.com/auth/analytics.readonly https://www.googleapis.com/auth/webmasters"
RIYADH = datetime.timezone(datetime.timedelta(hours=3))
TTL = {"ga": 900, "rt": 60, "gsc": 1800}      # ثوانٍ: GA ربع ساعة، «الآن» دقيقة، Search Console نصف ساعة


class GoogleError(Exception):
    def __init__(self, code, msg, hint="", url=""):
        super().__init__(msg)
        self.code, self.msg, self.hint, self.url = code, msg, hint, url

    def as_dict(self):
        return {"code": self.code, "error": self.msg, "hint": self.hint, "url": self.url}


# ================= RSA بلا مكتبات: قراءة المفتاح والتوقيع =================
def _der(buf, i):
    """عنصر DER واحد من buf عند i ← (الوسم، القيمة، موضع ما بعده)."""
    tag, ln = buf[i], buf[i + 1]
    i += 2
    if ln & 0x80:
        n = ln & 0x7F
        ln = int.from_bytes(buf[i:i + n], "big")
        i += n
    return tag, buf[i:i + ln], i + ln


def _items(buf):
    out, i = [], 0
    while i < len(buf):
        t, v, i = _der(buf, i)
        out.append((t, v))
    return out


def load_key(pem):
    """PEM (‏«BEGIN PRIVATE KEY» كما في ملف حساب الخدمة، أو «BEGIN RSA PRIVATE KEY») ← أعداد المفتاح."""
    pem = str(pem or "").replace("\\n", "\n")
    b64 = "".join(l.strip() for l in pem.strip().splitlines() if l.strip() and not l.startswith("-----"))
    der = base64.b64decode(b64)
    tag, body, _ = _der(der, 0)
    if tag != 0x30:
        raise ValueError("not a DER sequence")
    items = _items(body)
    if "RSA PRIVATE KEY" not in pem:             # PKCS#8: الإصدار، الخوارزمية، ثم المفتاح في OCTET STRING
        octet = next(v for t, v in items if t == 0x04)
        tag, body, _ = _der(octet, 0)
        items = _items(body)
    ints = [int.from_bytes(v, "big") for t, v in items if t == 0x02]
    if len(ints) < 9:
        raise ValueError("incomplete RSA key")
    _, n, e, d, p, q, dp, dq, qi = ints[:9]
    if n != p * q:
        raise ValueError("inconsistent RSA key")
    return {"n": n, "e": e, "d": d, "p": p, "q": q, "dp": dp, "dq": dq, "qi": qi}


_SHA256_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


def sign(key, msg):
    """توقيع RSASSA-PKCS1-v1_5 مع SHA-256 (هو RS256) — بطريقة البواقي الصينية للسرعة."""
    k = (key["n"].bit_length() + 7) // 8
    t = _SHA256_INFO + hashlib.sha256(msg).digest()
    if k < len(t) + 11:
        raise ValueError("key too short")
    m = int.from_bytes(b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t, "big")
    s1, s2 = pow(m, key["dp"], key["p"]), pow(m, key["dq"], key["q"])
    s = s2 + ((key["qi"] * (s1 - s2)) % key["p"]) * key["q"]
    return s.to_bytes(k, "big")


def _b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def jwt(sa, now=None, scope=SCOPES):
    now = int(time.time() if now is None else now)
    head = {"alg": "RS256", "typ": "JWT"}
    if sa.get("private_key_id"):
        head["kid"] = sa["private_key_id"]
    claims = {"iss": sa["client_email"], "scope": scope, "aud": AUD, "iat": now, "exp": now + 3600}
    msg = (_b64u(json.dumps(head, separators=(",", ":")).encode()) + "."
           + _b64u(json.dumps(claims, separators=(",", ":")).encode())).encode()
    return msg.decode() + "." + _b64u(sign(load_key(sa["private_key"]), msg))


# ================= الشبكة =================
def _explain(code, body):
    """ردّ جوجل ← (رسالة، تلميح بالعربية، رابط تفعيل الواجهة إن ذُكر)."""
    err = body.get("error") if isinstance(body, dict) else None
    msg = (err.get("message") if isinstance(err, dict) else None) or (body.get("error_description") if isinstance(body, dict) else "") \
        or (err if isinstance(err, str) else "") or f"HTTP {code}"
    url = ""
    m = re.search(r"https://console\.(?:developers|cloud)\.google\.com/\S+", msg)
    if m:
        url = m.group(0).rstrip(".")
    low = msg.lower()
    if "invalid_grant" in low or "invalid jwt" in low or "account not found" in low:
        hint = "جوجل رفضت المفتاح: ربما حُذف أو عُطّل حساب الخدمة، أو ساعة الخادم غير مضبوطة. أنشئ مفتاحًا جديدًا."
    elif "has not been used" in low or "is disabled" in low or "service_disabled" in low:
        hint = "فعّل هذه الواجهة في مشروع Google Cloud من الرابط، ثم انتظر دقيقتين وأعد المحاولة."
    elif "sufficient permission" in low or "permission" in low and code == 403:
        hint = "أضف بريد حساب الخدمة مستخدمًا في الخاصية/الموقع (مشاهد في Analytics، ومستخدمًا في Search Console)."
    elif code == 404:
        hint = "لم تُوجد الخاصية أو الموقع — تأكّد من الرقم أو الرابط كما يظهر في جوجل."
    elif code == 429 or "quota" in low:
        hint = "تجاوزت حصة جوجل مؤقتًا — تُعاد المحاولة بعد قليل."
    else:
        hint = ""
    return msg[:400], hint, url


def _call(url, body=None, token=None, method=None, timeout=25, form=None):
    headers = {"User-Agent": "ssouq-guide/1.0"}
    data = None
    if form is not None:
        data = form.encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    elif method == "PUT":
        data = b""
    if token:
        headers["Authorization"] = "Bearer " + token
    req = Request(url, data=data, headers=headers, method=method or ("POST" if data is not None else "GET"))
    try:
        with urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except HTTPError as e:
        try:
            err = json.loads(e.read() or b"{}")
        except ValueError:
            err = {}
        raise GoogleError(e.code, *_explain(e.code, err))
    except OSError as e:
        raise GoogleError(0, "تعذّر الاتصال بجوجل: " + str(e)[:160])
    try:
        return json.loads(raw or b"{}")
    except ValueError:
        return {}


_tok = {}                       # بريد حساب الخدمة ← (الرمز، انتهاؤه)
_tok_lock = threading.Lock()


def token(sa, fresh=False):
    email = sa.get("client_email", "")
    with _tok_lock:
        t = _tok.get(email)
        if t and not fresh and t[1] - 120 > time.time():
            return t[0]
    from urllib.parse import urlencode
    r = _call(TOKEN_URL, form=urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                         "assertion": jwt(sa)}))
    tok = r.get("access_token")
    if not tok:
        raise GoogleError(0, "لم تُرجع جوجل رمز وصول")
    with _tok_lock:
        _tok[email] = (tok, time.time() + int(r.get("expires_in") or 3600))
    return tok


# ================= الذاكرة المؤقتة للتقارير =================
_cache = {}
_cache_lock = threading.Lock()


def _cached(key, ttl, fn, fresh=False):
    with _cache_lock:
        c = _cache.get(key)
        if c and not fresh and time.time() - c[0] < ttl:
            return c[1]
    val = fn()
    with _cache_lock:
        if len(_cache) > 200:
            _cache.clear()
        _cache[key] = (time.time(), val)
    return val


def clear_cache():
    with _cache_lock:
        _cache.clear()
    with _tok_lock:
        _tok.clear()


# ================= Google Analytics 4 =================
def _m(name):
    return {"name": name}


def _desc(metric):
    return [{"metric": {"metricName": metric}, "desc": True}]


def _rows(rep, ints=True):
    out = []
    for r in rep.get("rows") or []:
        dims = [d.get("value", "") for d in r.get("dimensionValues") or []]
        vals = [float(v.get("value") or 0) for v in r.get("metricValues") or []]
        out.append((dims, [int(v) if ints else v for v in vals]))
    return out


def _total(rep, i=0):
    t = rep.get("totals") or []
    try:
        return float(t[0]["metricValues"][i]["value"])
    except (IndexError, KeyError, TypeError, ValueError):
        return 0.0


def ga_report(tok, prop, days):
    start = "today" if days <= 1 else f"{days - 1}daysAgo"
    rng = [{"startDate": start, "endDate": "today"}]
    reqs = [
        {"dateRanges": rng, "dimensions": [{"name": "date"}],
         "metrics": [_m("activeUsers"), _m("sessions"), _m("screenPageViews"), _m("engagementRate")],
         "orderBys": [{"dimension": {"dimensionName": "date"}}], "metricAggregations": ["TOTAL"], "keepEmptyRows": True},
        {"dateRanges": rng, "dimensions": [{"name": "sessionDefaultChannelGroup"}], "metrics": [_m("sessions")],
         "limit": 12, "orderBys": _desc("sessions")},
        {"dateRanges": rng, "dimensions": [{"name": "sessionSource"}], "metrics": [_m("sessions")],
         "limit": 12, "orderBys": _desc("sessions")},
        {"dateRanges": rng, "dimensions": [{"name": "countryId"}], "metrics": [_m("activeUsers")],
         "limit": 12, "orderBys": _desc("activeUsers")},
        {"dateRanges": rng, "dimensions": [{"name": "pagePath"}], "metrics": [_m("screenPageViews")],
         "limit": 15, "orderBys": _desc("screenPageViews")},
    ]
    r = _call(f"{GA_API}/properties/{prop}:batchRunReports", {"requests": reqs}, tok)
    reps = r.get("reports") or [{}] * 5
    reps += [{}] * (5 - len(reps))
    daily = []
    for dims, v in _rows(reps[0], ints=False):
        d = dims[0] if dims else ""
        daily.append({"d": f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d,
                      "users": int(v[0]), "sessions": int(v[1]), "views": int(v[2])})
    pair = lambda rep: [[dims[0] if dims else "", v[0]] for dims, v in _rows(rep)]
    return {"totals": {"users": int(_total(reps[0], 0)), "sessions": int(_total(reps[0], 1)),
                       "views": int(_total(reps[0], 2)), "engagement": round(_total(reps[0], 3), 4)},
            "daily": daily, "channels": pair(reps[1]), "sources": pair(reps[2]),
            "countries": pair(reps[3]), "pages": pair(reps[4])}


def ga_realtime(tok, prop):
    r = _call(f"{GA_API}/properties/{prop}:runRealtimeReport",
              {"dimensions": [{"name": "unifiedScreenName"}], "metrics": [_m("activeUsers")], "limit": 8,
               "metricAggregations": ["TOTAL"]}, tok)
    return {"users": int(_total(r, 0)), "pages": [[dims[0] if dims else "", v[0]] for dims, v in _rows(r)]}


def ga_properties(tok):
    r = _call(f"{GA_ADMIN}/accountSummaries?pageSize=200", token=tok)
    out = []
    for a in r.get("accountSummaries") or []:
        for p in a.get("propertySummaries") or []:
            pid = str(p.get("property", "")).replace("properties/", "")
            if pid:
                out.append({"id": pid, "name": p.get("displayName", ""), "account": a.get("displayName", "")})
    return out


# ================= Search Console =================
def _site_url(site):
    return f"{GSC_API}/sites/{quote(site, safe='')}"


def _gsc_rows(r):
    out = []
    for x in r.get("rows") or []:
        out.append([(x.get("keys") or [""])[0], int(x.get("clicks") or 0), int(x.get("impressions") or 0),
                    round(float(x.get("ctr") or 0), 4), round(float(x.get("position") or 0), 1)])
    return out


def _gsc_total(r):
    x = (r.get("rows") or [{}])[0]
    return {"clicks": int(x.get("clicks") or 0), "impressions": int(x.get("impressions") or 0),
            "ctr": round(float(x.get("ctr") or 0), 4), "position": round(float(x.get("position") or 0), 1)}


def gsc_report(tok, site, days, host, today=None):
    """أعداد البحث في جوجل لآخر `days` يومًا: المجموع ومقارنته بما قبله، ولكل يوم، والاستعلامات والصفحات،
    وخرائط الموقع المرسلة. وخاصية النطاق (‏sc-domain:) تُقصَر على صفحات الدليل."""
    today = today or datetime.datetime.now(RIYADH).date()
    end = today
    start = end - datetime.timedelta(days=max(1, days) - 1)
    p_end, p_start = start - datetime.timedelta(days=1), start - datetime.timedelta(days=max(1, days))
    base = {"dataState": "all"}
    if site.startswith("sc-domain:") and host:
        base["dimensionFilterGroups"] = [{"filters": [{"dimension": "page", "operator": "contains",
                                                       "expression": f"://{host}/"}]}]
    q = lambda extra, s=start, e=end: _call(_site_url(site) + "/searchAnalytics/query",
                                            dict(base, startDate=s.isoformat(), endDate=e.isoformat(), **extra), tok)
    out = {"site": site, "from": start.isoformat(), "to": end.isoformat(),
           "totals": _gsc_total(q({})), "prev": _gsc_total(q({}, p_start, p_end)),
           "daily": [{"d": r[0], "clicks": r[1], "impressions": r[2]}
                     for r in _gsc_rows(q({"dimensions": ["date"], "rowLimit": 500}))],
           "queries": _gsc_rows(q({"dimensions": ["query"], "rowLimit": 200})),
           "pages": _gsc_rows(q({"dimensions": ["page"], "rowLimit": 60}))}
    out["daily"].sort(key=lambda x: x["d"])
    try:
        out["sitemaps"] = sitemaps(tok, site)
    except GoogleError as e:
        out["sitemaps"], out["sitemaps_error"] = [], e.as_dict()
    return out


def sitemaps(tok, site):
    r = _call(_site_url(site) + "/sitemaps", token=tok)
    out = []
    for s in r.get("sitemap") or []:
        c = (s.get("contents") or [{}])[0]
        out.append({"path": s.get("path", ""), "downloaded": s.get("lastDownloaded", ""),
                    "submitted_at": s.get("lastSubmitted", ""), "pending": bool(s.get("isPending")),
                    "errors": int(s.get("errors") or 0), "warnings": int(s.get("warnings") or 0),
                    "urls": int(c.get("submitted") or 0)})
    return out


def submit_sitemap(tok, site, url):
    _call(_site_url(site) + "/sitemaps/" + quote(url, safe=""), token=tok, method="PUT")


def gsc_sites(tok):
    r = _call(f"{GSC_API}/sites", token=tok)
    return [{"url": s.get("siteUrl", ""), "level": s.get("permissionLevel", "")} for s in r.get("siteEntry") or []]


# ================= ما تطلبه الصفحة =================
def report(creds, days=28, host="", fresh=False):
    """تقرير جوجل للصفحة ← {ga, gsc} ولكلٍّ خطؤه وحده: فشل واحدٍ لا يُسقط الآخر. `creds` من الإعداد:
    {sa, email, ga, site}."""
    out = {"ok": True, "email": creds.get("email", ""), "ga": None, "gsc": None}
    try:
        tok = token(creds["sa"], fresh=fresh)
    except GoogleError as e:
        out.update(ok=False, **{"error": e.msg, "hint": e.hint, "url": e.url})
        return out
    prop, site, email = creds.get("ga"), creds.get("site"), creds.get("email", "")
    if prop:
        try:
            ga = _cached(("ga", email, prop, days), TTL["ga"], lambda: ga_report(tok, prop, days), fresh)
            ga = dict(ga)
            try:
                ga["realtime"] = _cached(("rt", email, prop), TTL["rt"], lambda: ga_realtime(tok, prop), fresh)
            except GoogleError as e:
                ga["realtime"], ga["realtime_error"] = None, e.as_dict()
            out["ga"] = ga
        except GoogleError as e:
            out["ga"] = {"error": e.as_dict()}
    if site:
        try:
            out["gsc"] = _cached(("gsc", email, site, days), TTL["gsc"], lambda: gsc_report(tok, site, days, host), fresh)
        except GoogleError as e:
            out["gsc"] = {"error": e.as_dict()}
    return out


def check(creds):
    """«اختبر الربط»: رمز الوصول، والخصائص والمواقع التي يراها حساب الخدمة (ليُختار منها)."""
    out = {"ok": False, "email": creds.get("email", ""), "properties": [], "sites": []}
    try:
        tok = token(creds["sa"], fresh=True)
    except GoogleError as e:
        out.update(error=e.msg, hint=e.hint, url=e.url)
        return out
    out["ok"] = True
    try:
        out["properties"] = ga_properties(tok)
    except GoogleError as e:
        out["properties_error"] = e.as_dict()
    try:
        out["sites"] = gsc_sites(tok)
    except GoogleError as e:
        out["sites_error"] = e.as_dict()
    return out


def send_sitemaps(creds, urls):
    """يرسل خرائط الموقع إلى Search Console ← [{url, ok, error}] ثم حالها كما تراها جوجل."""
    tok = token(creds["sa"])
    res = []
    for u in urls:
        try:
            submit_sitemap(tok, creds["site"], u)
            res.append({"url": u, "ok": True})
        except GoogleError as e:
            res.append({"url": u, "ok": False, **e.as_dict()})
    with _cache_lock:
        for k in [k for k in _cache if k[0] == "gsc"]:
            del _cache[k]
    return res

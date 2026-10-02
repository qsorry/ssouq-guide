"""«الإضافات الأخرى» في حسابات Stremio الجاهزة — مثل AIOMetadata.

العميل يلصق رابط manifest إضافةٍ (بعد إعدادها في صفحتها) مرةً واحدة: تُقرأ وتُحفظ له، فتُثبَّت في كل حسابٍ جديد
مع إضافتنا (وعند ربط خطٍّ أو «تحديث الإضافة»)، وبزرٍّ واحد في كل حساباته السابقة — أو تُسقط منها كلها. التثبيت في
الحسابات السابقة عمليةٌ في الخلفية بتقدّمٍ تقرؤه الصفحة.

الحفظ: ‏data/stremio_extras.json ‏{حساب الأداة: [{id, url, manifest, added}]}.
"""

import datetime
import hashlib
import re
import http.client
import ipaddress
import json
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import stremio_accounts

FILE = "stremio_extras.json"
MAX_PER_ACCT = 10
MAX_BYTES = 512 * 1024
TIMEOUT = 15
WORKERS = 3                                   # حساباتٌ معًا في التثبيت للسابقة (لطفًا بـ Stremio)
# الاختبارات تقرأ إضافةً وهميةً على هذا الجهاز؛ وفي التشغيل لا يُقرأ رابطٌ إلى شبكةٍ داخلية
ALLOW_LOCAL = os.environ.get("STREMIO_EXTRAS_ALLOW_LOCAL") == "1"
UA = "Mozilla/5.0 (compatible; ssouq-stremio/1.0)"
# دليل الإضافات للبحث بالاسم: الرسمي (ما يعرضه Stremio) ودليل المجتمع (stremio-addons.net)
CATALOGS = [u.strip() for u in os.environ.get(
    "STREMIO_ADDON_CATALOGS",
    "https://api.strem.io/addonscollection.json,https://stremio-addons.net/api/addon_catalog/all/stremio-addons.net.json",
).split(",") if u.strip()]
DIR_TTL = 6 * 3600
DIR_BYTES = 6 * 1024 * 1024

_lock = threading.Lock()


def _path(data_dir):
    return os.path.join(data_dir, FILE)


def _load(data_dir):
    try:
        with open(_path(data_dir), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data_dir, d):
    tmp = _path(data_dir) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, _path(data_dir))


# ================= قراءة الإضافة =================
def norm_url(url):
    """رابط manifest كما يُلصق (‏stremio:// أو https://، وقد ينقصه manifest.json) ← رابطه بـ https/http، أو
    ValueError."""
    u = str(url or "").strip()
    if u.startswith("stremio://"):
        u = "https://" + u[len("stremio://"):]
    p = urlsplit(u)
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        raise ValueError("الصق رابط manifest الإضافة (https://…/manifest.json)")
    path = p.path.rstrip("/")
    if not path.endswith("/manifest.json"):
        path += "/manifest.json"
    return urlunsplit((p.scheme, p.netloc, path, p.query, ""))


def _public(host):
    """لا يُقرأ رابطٌ إلى الجهاز نفسه أو شبكةٍ داخلية (فلا تصير الأداة بابًا لما خلف الخادم)."""
    if ALLOW_LOCAL:
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
    return bool(infos)


class _Checked(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        p = urlsplit(newurl)
        if p.scheme not in ("http", "https") or not p.hostname or not _public(p.hostname):
            raise ValueError("الرابط يحوّل إلى عنوانٍ لا يُقرأ")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _get(url, limit):
    """GET لرابطٍ عام (لا الجهاز ولا شبكةٌ داخلية، ولا تحويلٌ إليها) ← البايتات. ‏ValueError برسالةٍ للعرض."""
    if not _public(urlsplit(url).hostname):
        raise ValueError("رابطٌ إلى شبكةٍ داخلية لا يُقرأ")
    try:
        with build_opener(_Checked).open(Request(url, headers={"User-Agent": UA, "Accept": "application/json"}),
                                         timeout=TIMEOUT) as r:
            raw = r.read(limit + 1)
    except HTTPError as e:
        raise ValueError(f"الإضافة ردّت بخطأ {e.code} — تأكّد من الرابط") from None
    except (URLError, OSError, http.client.HTTPException):
        raise ValueError("تعذّر الوصول إلى الإضافة — تأكّد من الرابط") from None
    if len(raw) > limit:
        raise ValueError("ردّ الإضافة أكبر من المسموح")
    return raw


def _usable(m):
    """إضافةٌ تعمل كما هي: لها موارد ولا تطلب إعدادًا (AIOMetadata بلا إعدادٍ manifestها بلا موارد)."""
    return bool(m.get("resources")) and not (m.get("behaviorHints") or {}).get("configurationRequired")


def fetch(url):
    """رابط manifest ← وصف الإضافة للتثبيت ‏{transportUrl, manifest, flags}. ‏ValueError برسالةٍ للعرض: رابطٌ لا يصلح،
    أو لا يردّ، أو ليس manifest إضافة، أو إضافةٌ تحتاج إعدادًا (يُلصق رابطها بعد الإعداد)."""
    url = norm_url(url)
    raw = _get(url, MAX_BYTES)
    try:
        m = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        raise ValueError("الرابط لا يعيد manifest إضافة") from None
    if not (isinstance(m, dict) and m.get("id") and m.get("name") and isinstance(m.get("resources"), list)
            and isinstance(m.get("types"), list)):
        raise ValueError("الرابط لا يعيد manifest إضافة")
    if not _usable(m):
        raise ValueError("هذه الإضافة تحتاج إعدادًا: افتح صفحة إعدادها، وأكمله، ثم الصق رابط التثبيت (manifest) الذي تعطيه")
    if str(m["id"]).startswith(stremio_accounts.OURS):
        raise ValueError("هذه إضافتنا نفسها — تُثبَّت وحدها مع كل حساب")
    return {"transportUrl": url, "manifest": m, "flags": {"official": False, "protected": False}}


# ================= البحث بالاسم في دليل الإضافات =================
_dir = {"t": 0, "items": []}
_dir_lock = threading.Lock()


def _brief(url, m):
    bh = m.get("behaviorHints") or {}
    conf = bool(bh.get("configurable") or bh.get("configurationRequired"))
    return {"url": url, "id": str(m.get("id", "")), "name": str(m.get("name", ""))[:80], "version": str(m.get("version", ""))[:20],
            "description": " ".join(str(m.get("description") or "").split())[:240], "logo": str(m.get("logo") or ""),
            "host": urlsplit(url).hostname or "", "needs_config": not _usable(m),
            "configure": url[:-len("manifest.json")] + "configure" if conf and url.endswith("/manifest.json") else ""}


def directory():
    """دليل الإضافات (الرسمي ودليل المجتمع) — يُقرأ ويُحفظ 6 ساعات؛ ومصدرٌ لا يردّ يُتخطّى."""
    with _dir_lock:
        if _dir["items"] and time.time() - _dir["t"] < DIR_TTL:
            return _dir["items"]
        items, seen = [], set()
        for src in CATALOGS:
            try:
                d = json.loads(_get(src, DIR_BYTES).decode("utf-8", "replace"))
            except (ValueError, UnicodeError):
                continue
            for a in (d.get("addons") if isinstance(d, dict) else d) or []:
                url, m = (a.get("transportUrl"), a.get("manifest")) if isinstance(a, dict) else (None, None)
                if not (isinstance(url, str) and url.startswith(("https://", "http://")) and isinstance(m, dict)
                        and m.get("id") and m.get("name")) or url in seen:
                    continue
                seen.add(url)
                items.append(_brief(url, m))
        if items:
            _dir.update(t=time.time(), items=items)
        return _dir["items"]


def _compact(s):
    return re.sub(r"[^0-9a-z\u0600-\u06ff]", "", str(s).lower())


def search(q, limit=24):
    """إضافاتٌ بالاسم («AIOMetadata» تجد «AIO Metadata» بمضيفيها): الاسم أولًا ثم المعرّف والوصف؛ والتي تعمل كما هي
    قبل التي تحتاج إعدادًا. ‏ValueError: الدليل لا يردّ."""
    cq, words = _compact(q), str(q or "").lower().split()
    if len(cq) < 2:
        return []
    items = directory()
    if not items:
        raise ValueError("تعذّر الوصول إلى دليل الإضافات — الصق رابط manifest الإضافة مباشرةً")
    hits = []
    for it in items:
        name = _compact(it["name"])
        rank = 0 if name.startswith(cq) else 1 if cq in name else \
            2 if cq in _compact(it["id"]) or all(w in f"{it['name']} {it['id']} {it['description']}".lower() for w in words) else None
        if rank is not None:
            hits.append((rank, it["needs_config"], it["name"].lower(), it))
    hits.sort(key=lambda h: h[:3])
    return [h[3] for h in hits[:limit]]


# ================= القائمة =================
def _eid(url):
    return hashlib.sha256(url.encode()).hexdigest()[:12]


def items(data_dir, acct_id):
    """إضافات العميل الأخرى للعرض: ‏[{id, name, version, url, logo, description, added}]."""
    with _lock:
        lst = _load(data_dir).get(acct_id) or []
    return [{"id": e["id"], "name": str(e["manifest"].get("name", "")), "version": str(e["manifest"].get("version", "")),
             "url": e["url"], "logo": str(e["manifest"].get("logo") or ""), "added": e.get("added", ""),
             "description": str(e["manifest"].get("description") or "")[:200]} for e in lst if isinstance(e, dict)]


def descriptors(data_dir, acct_id, only=None):
    """أوصاف إضافات العميل للتثبيت (كلها، أو ما في only من معرّفاتها)."""
    with _lock:
        lst = _load(data_dir).get(acct_id) or []
    return [{"transportUrl": e["url"], "manifest": e["manifest"], "flags": {"official": False, "protected": False}}
            for e in lst if isinstance(e, dict) and (only is None or e["id"] in only)]


def add(data_dir, acct_id, url):
    """يقرأ الإضافة ويحفظها للعميل (أو يحدّث وصفها إن كانت عنده). ← عنصرها. ‏ValueError برسالةٍ للعرض."""
    desc = fetch(url)
    url = desc["transportUrl"]
    with _lock:
        d = _load(data_dir)
        lst = [e for e in d.get(acct_id) or [] if isinstance(e, dict)]
        cur = next((e for e in lst if e["url"] == url), None)
        if cur:
            cur["manifest"] = desc["manifest"]
        else:
            if any((e["manifest"] or {}).get("id") == desc["manifest"]["id"] for e in lst):
                raise ValueError(f"«{desc['manifest']['name']}» في القائمة برابطٍ آخر — احذفه أولًا لتضع هذا")
            if len(lst) >= MAX_PER_ACCT:
                raise ValueError(f"بلغت القائمة حدّها ({MAX_PER_ACCT})")
            cur = {"id": _eid(url), "url": url, "manifest": desc["manifest"],
                   "added": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")}
            lst.append(cur)
        d[acct_id] = lst
        _save(data_dir, d)
    return cur


def remove(data_dir, acct_id, eid):
    """يحذفها من القائمة (لا تُثبَّت في الجديدة بعده؛ وما في الحسابات يبقى ما لم تُسقط منها)."""
    with _lock:
        d = _load(data_dir)
        lst = [e for e in d.get(acct_id) or [] if isinstance(e, dict)]
        new = [e for e in lst if e["id"] != eid]
        if len(new) == len(lst):
            return False
        if new:
            d[acct_id] = new
        else:
            d.pop(acct_id, None)
        _save(data_dir, d)
    return True


# ================= في كل الحسابات السابقة (في الخلفية) =================
_jobs = {}                                     # حساب الأداة ← حال آخر عملية


def job(acct_id):
    with _lock:
        j = _jobs.get(acct_id)
        return dict(j, failed=list(j["failed"])) if j else None


def start(data_dir, acct_id, eid, remove_it=False):
    """يثبّت إضافةً من القائمة في كل حسابات Stremio للعميل (أو يُسقطها منها) في الخلفية — الحساب الواحد مرةً
    مهما كثرت خطوطه. ← حال العملية. ‏ValueError: عمليةٌ جارية، أو إضافةٌ ليست في القائمة، أو لا حسابات."""
    extras = descriptors(data_dir, acct_id, {eid})
    if not extras:
        raise ValueError("الإضافة ليست في القائمة")
    accts = {}
    for r in stremio_accounts.owned_all(data_dir, acct_id):
        if r.get("email") and r.get("password"):
            accts.setdefault(r["email"].lower(), (r["email"], r["password"]))
    if not accts:
        raise ValueError("لا حسابات Stremio بعد")
    with _lock:
        if (_jobs.get(acct_id) or {}).get("running"):
            raise ValueError("عمليةٌ جارية — انتظر انتهاءها")
        j = _jobs[acct_id] = {"id": eid, "name": str(extras[0]["manifest"].get("name", "")), "op": "remove" if remove_it else "install",
                              "total": len(accts), "done": 0, "changed": 0, "failed": [], "running": True,
                              "started": int(time.time()), "finished": 0}

    def one(cred):
        email, pw = cred
        try:
            auth = stremio_accounts.login(email, pw)
            try:
                n = stremio_accounts.set_extras(auth, extras, remove_it)
            finally:
                stremio_accounts.logout(auth)
            err = None
        except stremio_accounts.StremioError as e:
            n, err = 0, str(e)
        with _lock:
            j["done"] += 1
            j["changed"] += 1 if n else 0
            if err:
                j["failed"].append({"email": email, "error": err})

    def run():
        try:
            with ThreadPoolExecutor(max_workers=WORKERS) as ex:
                list(ex.map(one, accts.values()))
        finally:
            with _lock:
                j["running"], j["finished"] = False, int(time.time())
    threading.Thread(target=run, daemon=True, name="stremio-extras").start()
    return job(acct_id)

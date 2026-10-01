#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
موصّل لوحة فالكون (Falcon) — مزوّد مختلف عن Xtream-Masters:
مصادقة Bearer بمفتاح rk_live_...، وواجهة REST تحت /api/v1.

المكتشَف من الواجهة الحيّة:
  GET  /me         → {ok, reseller:{id, username, credits, host}}
  GET  /packages   → {ok, packages:[{id, package_name, official_credits,
                                     official_duration, official_duration_in,
                                     max_connections}]}
  GET  /lines      → {ok, total, page, per, lines:[{id, username, password,
                                     status, expires_at, max_connections,
                                     package_id}]}
  POST /lines      → إنشاء يوزر بـ {package_id, username?, password?,
                                     max_connections?} (باقة غير صالحة → 400
                                     {ok:false, error:"package_not_available"})
  PATCH /lines/<id> → تغيير اسم الخط وحده (الاشتراكات المجزّأة) — **غير مؤكَّد على
                     الواجهة الحيّة**: إن لم يوجد المسار (404/405) يُعدّ «غير متاح»
                     ولم يتغيّر شيء، ويُغيَّر الاسم من اللوحة يدويًا.

stdlib فقط. المفتاح لا يُسجَّل ولا يُطبع.
"""
import re
import json
import time
import urllib.parse
import urllib.request
import urllib.error

TIMEOUT = 30


def arabic_package_name(en):
    """اسم عربي لباقة فالكون الإنجليزية (1months, 1years 2 contact + 3 months...)."""
    s = str(en or "").lower()
    ym = re.search(r"(\d+)\s*years?", s)
    mm = re.search(r"(\d+)\s*months?", s)
    cm = re.search(r"(\d+)\s*(?:contact|connection|conn|device|screen)", s)
    parts = []
    if ym:
        y = int(ym.group(1))
        parts.append("سنة" if y == 1 else ("سنتان" if y == 2 else "%d سنوات" % y))
    if mm:
        m = int(mm.group(1))
        parts.append("شهر" if m == 1 else ("شهران" if m == 2 else ("%d أشهر" % m if m <= 10 else "%d شهرًا" % m)))
    name = " + ".join(parts) if parts else str(en)
    if cm:
        c = int(cm.group(1))
        name += " — " + ("جهاز" if c == 1 else ("جهازان" if c == 2 else "%d أجهزة" % c))
    return name or str(en)


def _line_row(r):
    return {"id": r.get("id"), "username": r.get("username"), "password": r.get("password"),
            "status": r.get("status"), "exp": r.get("expires_at"),
            "max_connections": r.get("max_connections"), "package_id": r.get("package_id")}


class FalconError(RuntimeError):
    pass


class FalconUnsupported(FalconError):
    """الواجهة لا تتيح التعديل (لا مسار PATCH للخط، أو الخط غير ظاهر) — لم يتغيّر شيء."""


class FalconOffline(FalconError):
    """تعذّر الوصول إلى فالكون — عطلٌ عابر يُعاد لاحقًا."""


def _request(base, key, path, method="GET", body=None):
    url = base.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + str(key),
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "ssouq-guide",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace") if e.fp else ""
    except urllib.error.URLError as e:
        raise FalconError("تعذّر الوصول إلى فالكون: %s" % getattr(e, "reason", e))
    try:
        return json.loads(raw)
    except ValueError:
        raise FalconError("رد غير JSON من فالكون: " + raw[:200])


def me(base, key):
    d = _request(base, key, "/me")
    if not d.get("ok"):
        raise FalconError("فالكون /me: " + str(d.get("error")))
    return d.get("reseller", {}) or {}


def host(base, key):
    try:
        return str(me(base, key).get("host", "")).strip().rstrip("/")
    except FalconError:
        return ""


def packages(base, key):
    d = _request(base, key, "/packages")
    if not d.get("ok"):
        raise FalconError("فالكون /packages: " + str(d.get("error")))
    out = []
    for p in d.get("packages", []) or []:
        if not isinstance(p, dict):
            continue
        en = p.get("package_name") or p.get("name") or ("باقة %s" % p.get("id"))
        out.append({
            "id": p.get("id"),
            "name": arabic_package_name(en),        # الاسم بالعربي
            "name_en": en,
            "credits": p.get("official_credits", p.get("credits")),
            "max_connections": p.get("max_connections", 1),
            "bouquets": [],
        })
    return out


def status(base, key):
    """حالة البوابة: النقاط، الهوست، عدد اللاينات، وآخر يوزر مُنشأ (الأحدث)."""
    r = me(base, key)
    try:
        d = _request(base, key, "/lines?per=1")
    except FalconError:
        d = {}
    lines = d.get("lines", []) or []
    newest = lines[0] if lines else {}   # /lines مرتَّبة من الأحدث
    return {
        "provider": "falcon",
        "credits": r.get("credits"),
        "host": r.get("host"),
        "username": r.get("username"),
        "total": d.get("total"),
        "last_id": newest.get("id"),
        "last_username": newest.get("username"),
    }


def search(base, key, query, max_pages=12, per=50):
    """بحث بالـ username (خادمي عبر q=) أو بالـ password (مسح الصفحات)."""
    query = str(query or "").strip()
    if not query:
        return []
    d = _request(base, key, "/lines?per=%d&q=%s" % (per, urllib.parse.quote(query)))
    if d.get("ok") is False:          # مفتاحٌ مرفوض وأشباهه: خطأٌ يُذكر، لا «لم يُعثر» كاذبة
        raise FalconError("فالكون /lines: " + str(d.get("error")))
    rows = d.get("lines", []) or []
    if rows:
        return [_line_row(r) for r in rows[:50]]
    # لا نتائج username → ابحث بالـ password عبر الصفحات
    out, total = [], None
    for page in range(1, max_pages + 1):
        try:
            d = _request(base, key, "/lines?per=%d&page=%d" % (per, page))
        except FalconError:
            break
        ls = d.get("lines", []) or []
        total = d.get("total", total)
        for r in ls:
            if query in str(r.get("username", "")) or query in str(r.get("password", "")):
                out.append(_line_row(r))
                if len(out) >= 50:
                    return out
        if len(ls) < per or (total and page * per >= total):
            break
    return out


def all_lines(base, key, progress=None, per=50, max_pages=4000):
    """كل لايناتِ البوابة (بترقيم الصفحات) — للتصدير إلى Excel. الباقةُ بالاسم
    العربي (تُحلّ من /packages)، والانتهاء والاتصالات كما تعطيها اللوحة."""
    try:
        pkgmap = {str(p["id"]): p["name"] for p in packages(base, key)}
    except Exception:
        pkgmap = {}
    out, total = [], None
    for page in range(1, max_pages + 1):
        d = _request(base, key, "/lines?per=%d&page=%d" % (per, page))
        ls = d.get("lines", []) or []
        total = d.get("total", total)
        for r in ls:
            out.append({
                "id": r.get("id"),
                "username": r.get("username"),
                "password": r.get("password"),
                "package": pkgmap.get(str(r.get("package_id")), r.get("package_name") or ""),
                "exp": r.get("expires_at") or r.get("exp") or "",
                "created": str(r.get("created_at") or "")[:10],
                "connections": r.get("max_connections"),
                # النشاط الآن إن أتاحته فالكون (online/متصلون الآن)؛ وإلا يُترك فارغًا.
                "active": ("online" if r.get("online") else "offline")
                          if r.get("online") is not None else
                          ("online" if r.get("active_connections") else "")
                          if r.get("active_connections") is not None else "",
                # آخر اتصال إن أتاحته فالكون (أسماء الحقول تختلف)؛ وإلا فارغ.
                "last_conn": str(r.get("last_connection") or r.get("last_seen")
                                 or r.get("lastseen") or r.get("last_online") or ""),
                "status": r.get("status") or "",
            })
        if progress:
            last = max(1, ((total or len(out)) + per - 1) // per)
            progress(len(out), last, page)
        if not ls or len(ls) < per or (total and page * per >= total):
            break
    return out


def _rand_digits(n=12):
    import secrets
    return str(secrets.randbelow(9) + 1) + "".join(str(secrets.randbelow(10)) for _ in range(n - 1))


def create_line(base, key, package_id, username=None, password=None, max_connections=None):
    """ينشئ يوزرًا على فالكون ويرجّع {username, password, id, exp}.
    يرسل اسم/كلمة مرور مولَّدين إن لم يُمرَّرا، ويقرأ الفعليين من الرد أو من
    قائمة /lines عبر الـ id."""
    username = str(username or _rand_digits())
    password = str(password or _rand_digits())
    body = {"package_id": int(package_id), "username": username, "password": password}
    if max_connections:
        body["max_connections"] = int(max_connections)
    d = _request(base, key, "/lines", method="POST", body=body)
    if not d.get("ok"):
        raise FalconError("فشل الإنشاء على فالكون: " + str(d.get("error")))

    line = d.get("line") if isinstance(d.get("line"), dict) else \
        (d.get("data") if isinstance(d.get("data"), dict) else d)
    u = line.get("username") or username
    p = line.get("password") or password
    lid = line.get("id", "")
    exp = line.get("expires_at", "")

    # لو لم يرجّع الرد الاسم/كلمة المرور، اقرأهما من قائمة اللاينات عبر الـ id.
    if (not line.get("username") or not line.get("password")) and lid:
        try:
            ls = _request(base, key, "/lines?per=200")
            for row in (ls.get("lines", []) or []):
                if str(row.get("id")) == str(lid):
                    u = row.get("username", u)
                    p = row.get("password", p)
                    exp = row.get("expires_at", exp)
                    break
        except FalconError:
            pass

    return {"username": str(u), "password": str(p), "id": lid, "exp": exp}


# ---------------- تغيير اسم خطٍّ قائم (الاشتراكات المجزّأة) ----------------
def _call(base, key, path, method="GET", body=None):
    """كـ _request لكن بالحالة: (رمز HTTP، JSON أو None) — ليفرّق التعديل بين «لا مسار»
    و«رُفض الطلب» و«لم يُردّ» (FalconOffline)."""
    url = base.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + str(key),
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "ssouq-guide",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            code, raw = r.getcode(), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        code, raw = e.code, (e.read().decode("utf-8", "replace") if e.fp else "")
    except (urllib.error.URLError, OSError) as e:
        raise FalconOffline("تعذّر الوصول إلى فالكون: %s" % getattr(e, "reason", e))
    try:
        return code, json.loads(raw)
    except ValueError:
        return code, None


def _exact(base, key, username):
    """صفّ الخط الذي اسمه username بالضبط (بحث الخادم بالاسم)، أو None."""
    code, d = _call(base, key, "/lines?per=50&q=%s" % urllib.parse.quote(str(username)))
    if not isinstance(d, dict) or not d.get("ok", True):
        raise FalconOffline("فالكون /lines: %s" % ((d or {}).get("error") if isinstance(d, dict) else code))
    for r in d.get("lines", []) or []:
        if str(r.get("username", "")) == str(username):
            return r
    return None


def rename_line(base, key, username, new_username, line_id=""):
    """يغيّر اسم خطٍّ على فالكون وكلمةُ مروره كما هي: PATCH /lines/<id> بالاسم وحده،
    ثم يتحقّق من /lines أن الاسم الجديد ظاهرٌ بكلمة المرور نفسها والانتهاء نفسه.
    FalconUnsupported = لا مسار تعديل (لم يتغيّر شيء)؛ FalconError بعد الإرسال = راجع."""
    username, new_username = str(username or "").strip(), str(new_username or "").strip()
    if not username or not new_username or username == new_username:
        raise ValueError("اسمٌ جديد مختلف مطلوب")
    done = _exact(base, key, new_username)
    if done:                                     # أُخذ في محاولةٍ سابقة ضاع ردّها
        return {"already": True, "verified": True, "line_id": done.get("id", ""),
                "exp": done.get("expires_at", ""), "password": done.get("password", "")}
    cur = _exact(base, key, username)
    if not cur:
        raise FalconUnsupported("الخط %s غير موجود على فالكون — لا يُعدَّل ما لا يُرى" % username)
    lid = cur.get("id") or line_id
    code, d = _call(base, key, "/lines/%s" % urllib.parse.quote(str(lid)), method="PATCH",
                    body={"username": new_username})
    if code in (404, 405, 501) or (code >= 400 and not isinstance(d, dict)):
        raise FalconUnsupported("واجهة فالكون لا تتيح تعديل اسم الخط (PATCH /lines ← %s) — "
                                "غيّره من اللوحة يدويًا" % code)
    if code >= 400 or not (isinstance(d, dict) and d.get("ok")):
        raise FalconError("رفضت فالكون تغيير الاسم: %s" % ((d or {}).get("error") or code))
    after = None
    for attempt in range(4):
        if attempt:
            time.sleep(1)
        after = _exact(base, key, new_username)
        if after:
            break
    if not after:
        raise FalconError("قبلت فالكون التعديل لكن الاسم الجديد لم يظهر — راجع اللوحة")
    if cur.get("password") and after.get("password") and str(after["password"]) != str(cur["password"]):
        raise FalconError("تغيّر الاسم لكن كلمة المرور تغيّرت أيضًا (%s) — راجع اللوحة" % after["password"])
    if cur.get("expires_at") and after.get("expires_at") and after["expires_at"] != cur["expires_at"]:
        raise FalconError("تغيّر الاسم لكن تغيّر تاريخ الانتهاء أيضًا — راجع اللوحة")
    return {"verified": True, "line_id": after.get("id") or lid, "exp": after.get("expires_at", ""),
            "password": after.get("password", "")}

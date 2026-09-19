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

stdlib فقط. المفتاح لا يُسجَّل ولا يُطبع.
"""
import re
import json
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

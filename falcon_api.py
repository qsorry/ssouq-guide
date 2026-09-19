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
import json
import urllib.request
import urllib.error

TIMEOUT = 30


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
        out.append({
            "id": p.get("id"),
            "name": p.get("package_name") or p.get("name") or ("باقة %s" % p.get("id")),
            "credits": p.get("official_credits", p.get("credits")),
            "max_connections": p.get("max_connections", 1),
            "bouquets": [],
        })
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

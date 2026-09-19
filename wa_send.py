#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مُرسِل واتساب قابل للتبديل — يرسل نص الاشتراك إلى رقم العميل.

الأنواع:
  • "cloud"  واتساب Cloud API الرسمي (Meta): token + phone_id.
             POST graph.facebook.com/<v>/<phone_id>/messages
  • "http"   بوابة عامة: POST {to, text} إلى url، مع Authorization اختياري —
             يوجّهها المستخدم إلى خدمته الخاصة (مثل قارئ واتساب Baileys عنده).
  • "none"   وضع تجريبي: لا يرسل، يسجّل فقط (dry-run افتراضي حتى الإعداد).

stdlib فقط. لا يُسجَّل أي token. كل إرسال يرجّع {ok, id?/dry?, error?}.
"""
import json
import urllib.error
import urllib.request

TIMEOUT = 25
GRAPH = "https://graph.facebook.com"
UA = "ssouq-guide-wa/1.0"


def _post(url, headers, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers=dict(headers, **{"Content-Type": "application/json",
                                                          "Accept": "application/json",
                                                          "User-Agent": UA}))
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read().decode("utf-8", "replace")
            code = r.getcode()
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace") if e.fp else ""
        code = e.code
    except urllib.error.URLError as e:
        return None, 0, str(getattr(e, "reason", e))
    try:
        return json.loads(raw) if raw else {}, code, None
    except ValueError:
        return {}, code, raw[:200]


def send(cfg: dict, to: str, text: str) -> dict:
    """يرسل رسالة نصية عبر القناة المضبوطة. لا يرمي استثناء — يرجّع النتيجة."""
    cfg = cfg or {}
    kind = str(cfg.get("type") or "none").lower()
    to = str(to or "").strip()
    if not to:
        return {"ok": False, "error": "رقم واتساب غير صالح"}

    if kind in ("none", "", "dry"):
        return {"ok": True, "dry": True}

    if kind == "cloud":
        token = str(cfg.get("token") or "").strip()
        phone_id = str(cfg.get("phone_id") or "").strip()
        ver = str(cfg.get("version") or "v21.0").strip()
        if not token or not phone_id:
            return {"ok": False, "error": "إعداد Cloud API ناقص (token/phone_id)"}
        url = "%s/%s/%s/messages" % (GRAPH, ver, phone_id)
        payload = {"messaging_product": "whatsapp", "recipient_type": "individual",
                   "to": to, "type": "text", "text": {"preview_url": False, "body": text}}
        d, code, err = _post(url, {"Authorization": "Bearer " + token}, payload)
        if err:
            return {"ok": False, "error": err}
        if 200 <= code < 300:
            mid = ""
            try:
                mid = (d.get("messages") or [{}])[0].get("id", "")
            except Exception:
                mid = ""
            return {"ok": True, "id": mid}
        emsg = ""
        try:
            emsg = (d.get("error") or {}).get("message") or ""
        except Exception:
            emsg = ""
        return {"ok": False, "error": emsg or ("HTTP %s" % code)}

    if kind == "http":
        url = str(cfg.get("url") or "").strip()
        if not url:
            return {"ok": False, "error": "رابط بوابة الواتساب غير مضبوط"}
        headers = {}
        sec = str(cfg.get("secret") or "").strip()
        if sec:
            headers["Authorization"] = "Bearer " + sec
        d, code, err = _post(url, headers, {"to": to, "text": text})
        if err:
            return {"ok": False, "error": err}
        if 200 <= code < 300:
            ok = True if not isinstance(d, dict) else d.get("ok", True) is not False
            return {"ok": bool(ok), "id": (d.get("id") if isinstance(d, dict) else "") or "",
                    **({} if ok else {"error": str(d.get("error") or "رفضت البوابة")})}
        return {"ok": False, "error": "HTTP %s" % code}

    return {"ok": False, "error": "نوع قناة واتساب غير معروف: " + kind}

"""التحكّم في الأجهزة المتزامنة لإضافة Stremio / Nuvio (نسخة «session» من الإضافة).

لكل اشتراك Xtream (خطّ: «هوست|يوزر») حدٌّ للأجهزة التي تشغّل في الوقت نفسه. يُفحص عند كل طلب تشغيل (‏/play) **قبل** تحويل
302 إلى اللوحة — الفيديو لا يمرّ بخادمنا أبدًا (لسنا وسيطًا للبث)، والتحويل كما كان تمامًا متى سُمح.

    الإضافة ← فحص الجلسة (هنا) ← سماح / رفض ← 302 إلى رابط Xtream مباشرةً ← المشغّل

النسختان: «standard» (كما كانت، لا فحص) و«session» (بهذا الفحص) — الإضافة نفسها والرابط نفسه ومعرّف الـmanifest نفسه، والنسخة
إعدادٌ للاشتراك على الخادم؛ فلا تُثبَّت نسختان على جهاز، وكل تطويرٍ في الإضافة يصل النسختين معًا.

**حدود معرفة «الجهاز» (مهم):** Stremio وNuvio لا يرسلان للإضافة أي معرّف جهازٍ ثابت. طلبات Stremio للإضافة ‏GET بلا ترويسات
(stremio-core: ‏addon_transport/http_transport)، ومشغّل Nuvio يرسل User-Agent ثابتًا واحدًا لكل الجوالات وآخر لكل أجهزة التلفاز
(‏PlayerPlaybackNetworking.DEFAULT_USER_AGENT). فلا Device ID حقيقي هنا. وUser-Agent لا يصلح للتمييز أصلًا: في الجهاز الواحد يختلف
بين طلبات التطبيق للإضافة ومشغّله وخادم البث المحلي في Stremio (فيُحسب الجهاز جهازين ويَحجب نفسه بحدٍّ 1)، ويتطابق بين الأجهزة.
فالمتاح «بصمةٌ» تقريبية (‏device_key) من **الشبكة** وحدها: عنوان IPv4 كاملًا، أو أول 64 بتًّا من IPv6 (عناوين الخصوصية تتبدّل
داخلها) — وUser-Agent يُحفظ للعرض في الأداة فقط.
  · تغيُّر المحتوى (حلقةٌ أو قناةٌ أخرى) أو مكوّن التطبيق الذي يطلب لا يغيّر البصمة: الجهاز نفسه جلسته نفسها.
  · جهازان على الشبكة نفسها (البيت نفسه) ← بصمةٌ واحدة (يُحسبان جهازًا واحدًا).
  · جهازٌ واحد ينتقل من شبكةٍ لأخرى (Wi-Fi ← بيانات الجوال) ← بصمةٌ جديدة؛ إن امتلأ الحد يُرفض حتى تنتهي جلسته القديمة
    (‏session_timeout) أو يُلغيها الموظف من الأداة.
  وكل جلسةٍ ‏session_id عشوائي (‏secrets) — هو ما يُعرض ويُلغى، لا البصمة.

لا Heartbeat من المشغّل (غير ممكن في Stremio/Nuvio دون تمرير الفيديو): ‏last_seen يتجدّد مع كل طلب تشغيلٍ جديد، والجلسة تنتهي بعد
‏session_timeout من آخر طلب (افتراضًا 3 ساعات للأفلام والمسلسلات وساعة للبث — من الأداة). والإلغاء يمنع كل ‏/play جديد للجلسة
الملغاة (ولا يُوقف ما يعمل الآن — غير ممكن بلا وسيط). و«الخروج من كل الأجهزة» يرفع ‏version الاشتراك فتسقط جلساته كلها.

لا تُحفظ هنا كلمة مرور ولا رابط بثّ: الاشتراك بهوسته ويوزره، والجهاز بعنوانه ووكيله (للعرض في الأداة) وبصمته."""
import hashlib
import ipaddress
import json
import os
import re
import secrets
import threading
import time

FILE = "stremio_sessions.json"
VARIANTS = ("standard", "session")
LIMIT_REASON = "CONCURRENT_DEVICE_LIMIT"
REVOKED_REASON = "SESSION_REVOKED"
RATE_REASON = "RATE_LIMITED"
RATE_MAX, RATE_WINDOW = 90, 60          # طلبات /play من شبكةٍ واحدة في الدقيقة (نسخة «session») — أكثر ← رفضٌ مؤقت
# ما يحدث عند امتلاء الحد: «deny» وحده الآن (الجهاز الجديد يُرفض، والقديم لا يُقطع). ‏«kick_oldest» مكانه هنا لاحقًا (يُلغي أقدم
# جلسةٍ ويقبل الجديدة) — غير مفعّل: قيمةٌ غير معروفة تعمل كـ«deny».
ON_LIMIT = ("deny",)
DEFAULTS = {"timeout_vod": 3 * 3600, "timeout_live": 3600, "default_max": 1}
TIMEOUT_MIN, TIMEOUT_MAX = 60, 7 * 86400
MAX_DEVICES_CAP = 20
KEEP_SECS = 2 * 86400                   # ما انتهى من الجلسات يبقى للعرض يومين ثم يُحذف
MSG = {LIMIT_REASON: "الحساب مستخدم حاليًا على جهاز آخر.", REVOKED_REASON: "تم تسجيل الدخول من جهاز آخر.",
       RATE_REASON: "طلبات تشغيلٍ كثيرة — انتظر دقيقة ثم أعد المحاولة."}

_lock = threading.RLock()
_state = {"dir": None, "data": None}
_hits = {}                              # شبكة ← [أوقات طلبات /play في النافذة] (في الذاكرة)


def setup(data_dir):
    """مجلد البيانات (مرةً من الخادم)."""
    with _lock:
        if data_dir and _state["dir"] != data_dir:
            _state["dir"], _state["data"] = data_dir, None


def reset():
    """للاختبارات."""
    with _lock:
        _state["dir"], _state["data"] = None, None
        _hits.clear()


def _rate_ok(ip, now):
    """حدٌّ لطلبات /play من شبكةٍ واحدة (‏RATE_MAX في ‏RATE_WINDOW ثانية) — و_lock مقفل."""
    k = ip_net(ip)
    q = [t for t in _hits.get(k, ()) if now - t < RATE_WINDOW]
    if len(q) >= RATE_MAX:
        _hits[k] = q
        return False
    q.append(now)
    _hits[k] = q
    if len(_hits) > 20000:
        for kk in [kk for kk, v in _hits.items() if not v or now - v[-1] >= RATE_WINDOW]:
            _hits.pop(kk, None)
    return True


def _path():
    return os.path.join(_state["dir"], FILE) if _state["dir"] else None


def _data():
    """المخزن (يُقرأ من القرص أول مرة) — و_lock مقفل."""
    if _state["data"] is None:
        d = {}
        p = _path()
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except (TypeError, OSError, ValueError):
            d = {}
        if not isinstance(d, dict):
            d = {}
        for k in ("accounts", "sessions", "settings"):
            if not isinstance(d.get(k), dict):
                d[k] = {}
        if not isinstance(d.get("salt"), str) or len(d["salt"]) < 16:
            d["salt"] = secrets.token_hex(16)
        _state["data"] = d
    return _state["data"]


def _save():
    """يحفظ المخزن (و_lock مقفل). تعذّر القرص ← يبقى في الذاكرة ويعمل (لا يتعطّل التشغيل)."""
    p = _path()
    if not p:
        return
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_state["data"], f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, p)
    except OSError:
        pass


# ---------------- الاشتراك والإعدادات ----------------
def account_key(host_key, user):
    """مفتاح الاشتراك: «هوست|يوزر» (كمفاتيح حسابات Nuvio)."""
    return f"{str(host_key or '').lower()}|{user}"


def _acct(d, acct):
    a = d["accounts"].get(acct)
    return a if isinstance(a, dict) else None


def account(acct):
    """إعداد الاشتراك: ‏variant · max_devices (‏None = من اللوحة) · panel_max (آخر ما عُرف) · version · owner · on_limit."""
    with _lock:
        a = _acct(_data(), acct)
        return dict(a) if a else {"variant": "standard", "max_devices": None, "version": 1, "owner": "", "on_limit": "deny"}


def variant(acct):
    with _lock:
        a = _acct(_data(), acct)
        return a.get("variant") if a and a.get("variant") in VARIANTS else "standard"


def set_account(acct, owner=None, variant=None, max_devices=False):
    """يضبط نسخة الاشتراك وحدّه (‏max_devices=None: من اللوحة؛ ‏False: لا يتغيّر). ← إعداده. ‏ValueError لقيمةٍ لا تصلح."""
    if variant is not None and variant not in VARIANTS:
        raise ValueError("نسخةٌ غير معروفة")
    if max_devices is not False and max_devices is not None:
        try:
            max_devices = int(max_devices)
        except (TypeError, ValueError):
            raise ValueError("عدد الأجهزة رقمٌ من 1 إلى %d" % MAX_DEVICES_CAP)
        if not 1 <= max_devices <= MAX_DEVICES_CAP:
            raise ValueError("عدد الأجهزة رقمٌ من 1 إلى %d" % MAX_DEVICES_CAP)
    with _lock:
        d = _data()
        a = _acct(d, acct) or {"variant": "standard", "max_devices": None, "version": 1, "owner": "", "on_limit": "deny"}
        if owner:
            a["owner"] = str(owner)
        if variant is not None:
            a["variant"] = variant
        if max_devices is not False:
            a["max_devices"] = max_devices
        d["accounts"][acct] = a
        _save()
        return dict(a)


def logout_all(acct):
    """«الخروج من كل الأجهزة»: ‏version += 1 — كل جلسةٍ قبلها تسقط عند أول ‏/play (ولا يتغيّر رابط الإضافة ولا الـmanifest)."""
    with _lock:
        d = _data()
        a = _acct(d, acct) or {"variant": "standard", "max_devices": None, "version": 1, "owner": "", "on_limit": "deny"}
        a["version"] = int(a.get("version") or 1) + 1
        d["accounts"][acct] = a
        _save()
        return a["version"]


def settings(owner=""):
    """مهلة الجلسة لحساب أداة (ثوانٍ): ‏timeout_vod (الأفلام والمسلسلات) · timeout_live · default_max (حدٌّ حين لا تُعرف اللوحة)."""
    with _lock:
        s = _data()["settings"].get(str(owner or "")) or {}
    return {k: int(s.get(k) or v) for k, v in DEFAULTS.items()}


def set_settings(owner, timeout_vod=None, timeout_live=None, default_max=None):
    """يضبط مهلتي الجلسة (ثوانٍ، من دقيقة إلى أسبوع) وحدّ «لا تُعرف اللوحة». ‏ValueError لقيمةٍ لا تصلح."""
    new = {}
    for k, v, lo, hi in (("timeout_vod", timeout_vod, TIMEOUT_MIN, TIMEOUT_MAX), ("timeout_live", timeout_live, TIMEOUT_MIN, TIMEOUT_MAX),
                         ("default_max", default_max, 1, MAX_DEVICES_CAP)):
        if v is None:
            continue
        try:
            v = int(v)
        except (TypeError, ValueError):
            raise ValueError("قيمةٌ غير صالحة")
        if not lo <= v <= hi:
            raise ValueError("قيمةٌ خارج الحدود")
        new[k] = v
    with _lock:
        d = _data()
        cur = dict(d["settings"].get(str(owner or "")) or {})
        cur.update(new)
        d["settings"][str(owner or "")] = cur
        _save()
    return settings(owner)


def _timeout(st, content_type):
    return st["timeout_live"] if content_type == "live" else st["timeout_vod"]


# ---------------- البصمة ----------------
_DIGITS = re.compile(r"[\d][\d._]*")


def ua_class(ua):
    """فئة التطبيق من User-Agent: بلا أرقام الإصدار (تحديث التطبيق لا يصنع جهازًا جديدًا)."""
    return " ".join(_DIGITS.sub("", str(ua or "")).lower().split())[:160]


def ip_net(ip):
    """شبكة العنوان: IPv4 كما هو، وIPv6 أول 64 بتًّا (عناوين الخصوصية تتبدّل داخلها)."""
    try:
        a = ipaddress.ip_address(str(ip or "").strip())
    except ValueError:
        return str(ip or "").strip()[:64]
    if a.version == 6:
        if a.ipv4_mapped:
            return str(a.ipv4_mapped)
        return str(ipaddress.ip_network(f"{a}/64", strict=False))
    return str(a)


def device_key(acct, ip, ua=None):
    """بصمة الجهاز التقريبية (انظر أعلى الملف — ليست Device ID حقيقيًا): الاشتراك + الشبكة، مختومةً بملحٍ سرّي. ‏ua لا يدخلها
    (يختلف داخل الجهاز الواحد ويتطابق بين الأجهزة)."""
    with _lock:
        salt = _data()["salt"]
    raw = f"{salt}\n{acct}\n{ip_net(ip)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


# ---------------- الجلسات ----------------
def _status(s, a, st, now):
    """حال الجلسة الآن: active · expired · revoked · logged_out."""
    if s.get("revoked"):
        return "revoked"
    if int(s.get("version") or 1) != int(a.get("version") or 1):
        return "logged_out"
    if now - float(s.get("last_seen") or 0) > _timeout(st, s.get("content_type")):
        return "expired"
    return "active"


def _prune(d, now):
    old = [sid for sid, s in d["sessions"].items()
           if not isinstance(s, dict) or now - float(s.get("revoked_at") or s.get("last_seen") or 0) > KEEP_SECS]
    for sid in old:
        d["sessions"].pop(sid, None)


def _limit(a, panel_max, st):
    """الحد: ما ضبطه الموظف، وإلا ‏max_connections من اللوحة (أو آخر ما عُرف منها)، وإلا ‏default_max."""
    if a.get("max_devices"):
        return int(a["max_devices"])
    pm = panel_max or a.get("panel_max")
    return int(pm) if pm else st["default_max"]


def check(acct, ip, ua, content_id="", content_type="movie", panel_max=None, dry=False, now=None):
    """قرار التشغيل لطلب ‏/play من نسخة «session» ← {"allowed"، "reason"، "active_devices"، "max_devices"، "session_id"، "message"}.
    ‏dry: يحسب القرار بلا إنشاء جلسةٍ ولا تجديد (لقائمة التشغيل). الجهاز نفسه (بصمته) بجلسةٍ نشطة ← تتجدّد ‏last_seen ومحتواها
    ويُسمح؛ وجلسته ملغاة (ولم تنتهِ مهلتها من الإلغاء) ← ‏SESSION_REVOKED؛ وجهازٌ جديد ← جلسةٌ جديدة إن بقي مكانٌ في الحد، وإلا
    ‏CONCURRENT_DEVICE_LIMIT (والجلسات القائمة لا تُمسّ)."""
    now = time.time() if now is None else now
    content_type = content_type if content_type in ("movie", "series", "live") else "movie"
    dk = device_key(acct, ip, ua)
    with _lock:
        d = _data()
        a = _acct(d, acct) or {"variant": "standard", "max_devices": None, "version": 1, "owner": "", "on_limit": "deny"}
        if panel_max and not dry and a.get("panel_max") != panel_max and acct in d["accounts"]:
            a["panel_max"] = int(panel_max)
        st = settings(a.get("owner"))
        mx = _limit(a, panel_max, st)
        mine = [(sid, s) for sid, s in d["sessions"].items() if isinstance(s, dict) and s.get("account") == acct]
        active = [(sid, s) for sid, s in mine if _status(s, a, st, now) == "active"]
        same = next(((sid, s) for sid, s in active if s.get("device_key") == dk), None)
        out = {"allowed": True, "reason": None, "active_devices": len(active), "max_devices": mx, "session_id": None, "message": ""}
        if not dry and not _rate_ok(ip, now):
            return {**out, "allowed": False, "reason": RATE_REASON, "message": MSG[RATE_REASON]}
        if same:
            sid, s = same
            if not dry:
                s.update(last_seen=now, content_id=str(content_id)[:120], content_type=content_type, ip=str(ip or "")[:64],
                         ua=str(ua or "")[:200])
                _save()
            out["session_id"] = sid
            return out
        blocked = next((s for _, s in mine if s.get("device_key") == dk and s.get("revoked")    # (والخروج من كل الأجهزة يمحوه)
                        and int(s.get("version") or 1) == int(a.get("version") or 1)
                        and now - float(s.get("revoked_at") or 0) <= _timeout(st, s.get("content_type"))), None)
        if blocked:
            if not dry:
                _log_denied(d, acct, ip, ua, content_id, REVOKED_REASON, [], now)
            return {**out, "allowed": False, "reason": REVOKED_REASON, "message": MSG[REVOKED_REASON]}
        if len(active) >= mx:                            # ‏on_limit: «deny» وحده الآن (‏kick_oldest لاحقًا هنا)
            if not dry:
                _log_denied(d, acct, ip, ua, content_id, LIMIT_REASON, active, now)
            return {**out, "allowed": False, "reason": LIMIT_REASON, "message": MSG[LIMIT_REASON]}
        if dry:
            return out
        sid = secrets.token_urlsafe(18)
        d["sessions"][sid] = {"account": acct, "device_key": dk, "ip": str(ip or "")[:64], "ua": str(ua or "")[:200],
                              "content_id": str(content_id)[:120], "content_type": content_type, "created_at": now, "last_seen": now,
                              "version": int(a.get("version") or 1), "revoked": False}
        _prune(d, now)
        _save()
        return {**out, "active_devices": len(active) + 1, "session_id": sid}


DENIED_MAX = 300                        # آخر محاولات التشغيل المرفوضة (للأداة: من رُفض، ومن أي شبكة، وأي جلسةٍ حجبته)


def _log_denied(d, acct, ip, ua, content_id, reason, active, now):
    """يسجّل محاولةً مرفوضة (و_lock مقفل) — مع الجلسات التي حجبتها، فيُعرف السبب: جهازٌ آخر فعلًا، أم الجهاز نفسه من شبكةٍ أخرى."""
    log = d.setdefault("denied", [])
    if not isinstance(log, list):
        log = d["denied"] = []
    last = log[-1] if log else None
    if last and last.get("account") == acct and last.get("ip") == str(ip or "")[:64] and now - float(last.get("at") or 0) < 60:
        last["at"], last["count"] = now, int(last.get("count") or 1) + 1      # تكرار المحاولة نفسها خلال دقيقة: سطرٌ واحد
    else:
        log.append({"account": acct, "ip": str(ip or "")[:64], "ua": str(ua or "")[:200], "content_id": str(content_id)[:120],
                    "reason": reason, "at": now, "count": 1,
                    "blocking": [{"session_id": sid, "ip": x.get("ip", ""), "last_seen": int(x.get("last_seen") or 0)} for sid, x in active]})
        del log[:-DENIED_MAX]
    _save()


def denied(accts=None):
    """المحاولات المرفوضة (لاشتراكاتٍ أو كلها)، الأحدث أولًا."""
    want = set(accts) if accts is not None else None
    with _lock:
        log = _data().get("denied") or []
        out = [dict(x, blocking=[dict(b) for b in x.get("blocking") or []]) for x in log
               if isinstance(x, dict) and (want is None or x.get("account") in want)]
    return sorted(out, key=lambda x: -float(x.get("at") or 0))


def revoke(session_id):
    """يلغي جلسة: لا ‏/play جديد منها (حتى تمضي مهلتها من الإلغاء) — وما يعمل الآن لا يُوقف. ← اشتراكها، أو None."""
    with _lock:
        d = _data()
        s = d["sessions"].get(str(session_id or ""))
        if not isinstance(s, dict):
            return None
        s["revoked"], s["revoked_at"] = True, time.time()
        _save()
        return s.get("account")


def session_account(session_id):
    with _lock:
        s = _data()["sessions"].get(str(session_id or ""))
        return s.get("account") if isinstance(s, dict) else None


def sessions(accts=None, now=None):
    """جلسات اشتراكاتٍ (أو كلها) للأداة، الأحدث أولًا: ‏session_id · account · device (مختصر البصمة) · ip · ua · content ·
    created_at · last_seen · status."""
    now = time.time() if now is None else now
    want = set(accts) if accts is not None else None
    out = []
    with _lock:
        d = _data()
        for sid, s in d["sessions"].items():
            if not isinstance(s, dict) or (want is not None and s.get("account") not in want):
                continue
            a = _acct(d, s.get("account")) or {"version": 1}
            st = settings(a.get("owner"))
            out.append({"session_id": sid, "account": s.get("account"), "device": str(s.get("device_key") or "")[:8],
                        "ip": s.get("ip", ""), "ua": s.get("ua", ""), "content_id": s.get("content_id", ""),
                        "content_type": s.get("content_type", ""), "created_at": int(s.get("created_at") or 0),
                        "last_seen": int(s.get("last_seen") or 0), "status": _status(s, a, st, now)})
    return sorted(out, key=lambda x: -x["last_seen"])


def accounts(owner=None):
    """الاشتراكات المضبوطة (لحساب أداة، أو كلها) ← {المفتاح: إعداده}."""
    with _lock:
        return {k: dict(v) for k, v in _data()["accounts"].items()
                if isinstance(v, dict) and (owner is None or v.get("owner") == str(owner))}

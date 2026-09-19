#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
xm_web — إنشاء يوزرات M3U عبر جلسة ويب للوحة Xtream-Masters (بديل الـ API).

لماذا هذا الملف؟ الـ Reseller API (رابط `.../reseller/index.php`) لا يستجيب على
هذا السيرفر (خلف Cloudflare، الأصل ساقط على HTTPS، والمسار يُعاد لصفحة الدخول).
البديل العملي — نفس ما يفعله سكربت السيلينيوم — هو الدخول للوحة نفسها
(اسم مستخدم + كلمة مرور + **كود تحقّق/كابتشا**)، حفظ الكوكيز، ثم إنشاء اليوزر
من نموذج اللوحة (`user_reseller.php`) بالجلسة المحفوظة.

الكابتشا: يُقرأ **آليًا** (OCR اختياري عبر pytesseract) وإن فشل يُطلب **تدخّل بشري**
(تُعرض الصورة ويكتب المشغّل الكود). لا مكتبات إلزامية — stdlib فقط؛ الـ OCR
يُستورد بتكاسل ويُتجاوز بأمان إن لم يكن متوفرًا.

التدفّق (مطابق للسكربت المثبت):
  begin() → صفحة الدخول (PHPSESSID + lkey + تخطّي التحقق البشري)
  login(captcha) → POST login.php ؛ خطأ الكود = ?error=captcha ، النجاح = تحويل للوحة
  packages() → قراءة قائمة الباقات من نموذج الإضافة
  create_line(pkg) → POST user_reseller.php (member_id + selected_bouquets + submit_user=1)
                     ثم تأكيد عبر table_search.php
"""
import json
import os
import re
import time
import secrets
import html as _html
import http.cookiejar
import urllib.request
import urllib.parse
import urllib.error

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")

# مسارات صفحة "إضافة يوزر" المحتملة (تُكتشف تلقائيًا وتُحفظ).
ADD_CANDIDATES = [
    "/user_reseller.php", "/line.php", "/user.php", "/add_line.php",
    "/lines.php?action=add", "/line.php?action=add", "/reseller/line.php",
]
HTTP_TIMEOUT = 30


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """يمنع urllib من تتبّع 30x تلقائيًا: نجاح/فشل الدخول كله في ترويسة Location."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class CaptchaNeeded(Exception):
    """الدخول يحتاج كودًا يكتبه إنسان. يحمل صورة كابتشا حديثة صالحة للجلسة."""

    def __init__(self, content_type: str, image: bytes, reason: str = "captcha"):
        super().__init__(reason)
        self.content_type = content_type
        self.image = image
        self.reason = reason


class LoginFailed(Exception):
    """فشل الدخول لسبب غير الكابتشا (بيانات خاطئة، حظر، ...)."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


# ----------------------------- OCR (اختياري) -----------------------------
_OCR_STATE = {"checked": False, "ok": False}


def ocr_available() -> bool:
    """هل يمكن قراءة الكابتشا آليًا؟ (pytesseract + tesseract + Pillow)."""
    if not _OCR_STATE["checked"]:
        _OCR_STATE["checked"] = True
        try:
            import pytesseract  # noqa: F401
            from PIL import Image  # noqa: F401
            # يتحقق أن ثنائية tesseract نفسها موجودة.
            pytesseract.get_tesseract_version()
            _OCR_STATE["ok"] = True
        except Exception:
            _OCR_STATE["ok"] = False
    return _OCR_STATE["ok"]


def solve_captcha(image: bytes) -> str:
    """
    قراءة كود الكابتشا آليًا (أرقام فقط). يرجّع النص أو "" عند الفشل/عدم التوفّر.
    لا يرمي استثناء أبدًا — الفشل يعني fallback بشري.
    """
    if not image or not ocr_available():
        return ""
    try:
        import io
        import pytesseract
        from PIL import Image, ImageOps, ImageFilter

        im = Image.open(io.BytesIO(image)).convert("L")
        im = im.resize((im.width * 3, im.height * 3))          # تكبير يحسّن التعرّف
        im = ImageOps.autocontrast(im)
        im = im.point(lambda p: 0 if p < 130 else 255)          # عتبة ثنائية
        im = im.filter(ImageFilter.MedianFilter(3))             # إزالة خطوط التشويش
        cfg = "--psm 7 -c tessedit_char_whitelist=0123456789"
        txt = pytesseract.image_to_string(im, config=cfg)
        digits = re.sub(r"\D", "", txt or "")
        return digits
    except Exception:
        return ""


# ----------------------------- جلسة اللوحة -----------------------------
class PanelWebSession:
    """
    جلسة ويب مصادَقة للوحة حساب واحد. الكوكيز تُحفظ على القرص فتبقى بين الطلبات
    وإعادة التشغيل.

    account: dict يحوي على الأقل:
        id        معرّف الحساب (لاسم ملف الكوكيز)
        user      اسم دخول اللوحة
        password  كلمة مرور اللوحة
        host      الهوست المكتوب في اللاين
      و(اختياري):
        panel_base  مثل http://panel-host:2052  — أو يُشتق من login_url/api_url
        login_url   مثل http://panel-host:2052/login.php
        add_line_url مسار صفحة الإضافة إن عُرف (يُكتشف ويُحفظ آليًا)
    """

    def __init__(self, account: dict, data_dir: str, use_ocr: bool = True):
        self.acct = account
        self.use_ocr = use_ocr
        self.base = self._resolve_base(account)
        if not self.base:
            raise ValueError("panel_base غير معروف — أضف panel_base أو login_url للحساب")

        self.sess_dir = os.path.join(data_dir, "sessions")
        os.makedirs(self.sess_dir, exist_ok=True)
        aid = str(account.get("id") or re.sub(r"\W+", "_", account.get("user", "acct")))
        self.jar_path = os.path.join(self.sess_dir, f"{aid}.cookies")
        self.meta_path = os.path.join(self.sess_dir, f"{aid}.meta.json")

        self.cj = http.cookiejar.MozillaCookieJar(self.jar_path)
        if os.path.exists(self.jar_path):
            try:
                self.cj.load(ignore_discard=True, ignore_expires=True)
            except Exception:
                pass
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj), _NoRedirect())
        self.add_url = account.get("add_line_url") or self._meta().get("add_url") or ""
        self.add_action = self._meta().get("add_action") or ""

    # ---- إعدادات / تخزين ----
    @staticmethod
    def _resolve_base(account: dict) -> str:
        for key in ("panel_base", "login_url", "api_url", "host"):
            v = str(account.get(key, "")).strip()
            if not v:
                continue
            if "/login.php" in v:
                v = v.split("/login.php")[0]
            # اقتطاع أي مسار بعد المضيف والمنفذ
            m = re.match(r"^(https?://[^/]+)", v)
            if m:
                return m.group(1)
        return ""

    def _meta(self) -> dict:
        try:
            with open(self.meta_path, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def _save_meta(self, **kw):
        d = self._meta()
        d.update(kw)
        tmp = self.meta_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, self.meta_path)

    def _save_cookies(self):
        try:
            self.cj.save(ignore_discard=True, ignore_expires=True)
        except Exception:
            pass

    # ---- HTTP ----
    def _abs(self, path: str) -> str:
        if re.match(r"^https?://", path):
            return path
        return self.base + "/" + path.lstrip("/")

    def _request(self, path, data=None, headers=None, method=None):
        url = self._abs(path)
        body = None
        if data is not None:
            body = urllib.parse.urlencode(data, doseq=True).encode()
        h = {"User-Agent": UA, "Accept": "text/html,application/json,*/*"}
        if body is not None:
            h["Content-Type"] = "application/x-www-form-urlencoded"
        if headers:
            h.update(headers)
        req = urllib.request.Request(url, data=body, headers=h, method=method)
        try:
            resp = self.opener.open(req, timeout=HTTP_TIMEOUT)
            raw = resp.read()
            status = resp.getcode()
            final = resp.geturl()
            ctype = resp.headers.get("Content-Type", "")
            self._save_cookies()
            return {"status": status, "body": raw, "final_url": final, "ctype": ctype,
                    "location": resp.headers.get("Location", "") or ""}
        except urllib.error.HTTPError as e:
            raw = e.read()
            self._save_cookies()
            return {"status": e.code, "body": raw, "final_url": url,
                    "ctype": e.headers.get("Content-Type", "") if e.headers else "",
                    "location": e.headers.get("Location", "") if e.headers else ""}

    def _text(self, r) -> str:
        return (r.get("body") or b"").decode("utf-8", "replace")

    # ---- تخطّي التحقق البشري ----
    def _handshake(self):
        r = self._request("/token.php")
        token = self._text(r).strip()
        if token and len(token) <= 512 and "<" not in token:
            host = re.sub(r":\d+$", "", urllib.parse.urlparse(self.base).netloc)
            c = http.cookiejar.Cookie(
                version=0, name="xm_simple_security_check", value=token,
                port=None, port_specified=False, domain=host, domain_specified=True,
                domain_initial_dot=False, path="/", path_specified=True,
                secure=False, expires=int(time.time()) + 7 * 86400, discard=False,
                comment=None, comment_url=None, rest={}, rfc2109=False)
            self.cj.set_cookie(c)
            self._save_cookies()

    # ---- صفحة الدخول ----
    @staticmethod
    def _scrape_input(html: str, name: str) -> str:
        m = re.search(r'<input[^>]*name=["\']' + re.escape(name) + r'["\'][^>]*>', html, re.I)
        if m:
            v = re.search(r'value=["\']([^"\']*)["\']', m.group(0), re.I)
            if v:
                return _html.unescape(v.group(1))
        return ""

    def begin(self):
        """جلسة دخول جديدة: تخطّي التحقق البشري + قراءة صفحة الدخول (PHPSESSID + lkey)."""
        self._handshake()
        r = self._request("/login")
        html = self._text(r)
        self._save_meta(
            lkey=self._scrape_input(html, "lkey"),
            referrer=self._scrape_input(html, "referrer"),
            access_code=self._scrape_input(html, "access_code"),
        )

    def fetch_captcha(self):
        """(content_type, bytes) لصورة الكابتشا الحالية (مربوطة بجلسة PHPSESSID)."""
        r = self._request("/captcha.php?a=1")
        return r.get("ctype") or "image/jpeg", r.get("body") or b""

    # ---- الدخول ----
    def login(self, captcha: str = None, auto_attempts: int = 3) -> bool:
        """
        يسجّل الدخول. سلوك الكابتشا:
          - captcha ممرّر → محاولة واحدة به (المسار البشري).
          - captcha=None → يقرأ الكود آليًا (OCR) حتى auto_attempts محاولة.
        النجاح → True (وتُحفظ الكوكيز). عند الحاجة لإنسان → CaptchaNeeded.
        بيانات خاطئة/حظر → LoginFailed.
        """
        if not self._meta().get("lkey") and captcha is None:
            self.begin()

        if captcha is not None:
            return self._attempt_login(captcha)

        # المسار الآلي
        last_img, last_ct = b"", "image/jpeg"
        for _ in range(max(1, auto_attempts)):
            self.begin()  # جلسة/كابتشا جديدة كل محاولة
            last_ct, last_img = self.fetch_captcha()
            code = solve_captcha(last_img) if self.use_ocr else ""
            if not code:
                break  # لا OCR / لم يُقرأ → أرسل الطلب للإنسان مباشرة
            try:
                if self._attempt_login(code):
                    return True
            except LoginFailed:
                raise
            except CaptchaNeeded:
                continue  # الكود الآلي خاطئ → جرّب صورة أخرى
        # فشل الآلي → إنسان، بصورة حديثة صالحة
        last_ct, last_img = self.fetch_captcha()
        raise CaptchaNeeded(last_ct, last_img, "auto_failed")

    def _attempt_login(self, captcha: str) -> bool:
        meta = self._meta()
        fields = {
            "referrer": meta.get("referrer", ""),
            "access_code": meta.get("access_code", ""),
            "username": self.acct.get("user", ""),
            "password": self.acct.get("password", ""),
            "lkey": meta.get("lkey", ""),
            "captcha": captcha,
        }
        r = self._request("/login.php", data=fields)
        loc = r.get("location", "") or r.get("final_url", "")
        m = re.search(r"[?&]error=([a-z0-9_\-]+)", loc, re.I)
        if m:
            code = m.group(1).lower()
            if code == "captcha":
                _, img = self.fetch_captcha()
                raise CaptchaNeeded("image/jpeg", img, "captcha")
            raise LoginFailed(code, self._login_error_msg(code))
        # ردّ 200 يعيد نموذج الدخول = فشل صامت
        body = self._text(r)
        if r.get("status") == 200 and 'name="password"' in body and "login_form" in body:
            _, img = self.fetch_captcha()
            raise CaptchaNeeded("image/jpeg", img, "captcha")
        if not self.is_authenticated():
            raise LoginFailed("not_authenticated", "قُبل الطلب لكن الجلسة غير مُصادَقة")
        return True

    @staticmethod
    def _login_error_msg(code: str) -> str:
        return {
            "captcha": "الكود غير صحيح",
            "credentials": "اسم المستخدم أو كلمة المرور غير صحيحة",
            "login": "اسم المستخدم أو كلمة المرور غير صحيحة",
            "password": "اسم المستخدم أو كلمة المرور غير صحيحة",
            "blocked": "الحساب أو الـ IP محظور",
            "ban": "الحساب أو الـ IP محظور",
        }.get(code, "فشل الدخول (%s)" % code)

    def is_authenticated(self) -> bool:
        r = self._request("/")
        loc = (r.get("location", "") or r.get("final_url", "")).lower()
        if "/login" in loc or "check.html" in loc:
            return False
        body = self._text(r)
        low = body.lower()
        # صفحة الدخول أو بوابة التحقّق البشري = غير مُصادَق
        if 'id="login_form"' in body or ('name="password"' in low and "captcha" in low):
            return False
        for gate in ("xm_simple_security_check", "verifying your browser",
                     "security verification", "check.html", "token.php"):
            if gate in low:
                return False
        return r.get("status", 0) < 400

    def ensure_login(self):
        """يعيد استخدام الكوكيز المحفوظة؛ ولو انتهت الجلسة يسجّل الدخول آليًا."""
        if self.is_authenticated():
            return
        self.login()  # آلي؛ قد يرمي CaptchaNeeded

    # ---- اكتشاف صفحة الإضافة ----
    _PKG_SELECT = re.compile(
        r'<select[^>]*(?:id=["\']package["\']|name=["\']package(?:_id)?["\']|'
        r'(?:id|name)=["\'][^"\']*package[^"\']*["\'])[^>]*>(.*?)</select>', re.I | re.S)

    def _has_add_form(self, html: str) -> bool:
        return bool(self._PKG_SELECT.search(html)) and 'name="password"' in html.lower() \
            and 'name="username"' in html.lower()

    def discover_add(self):
        if self.add_url:
            r = self._request(self.add_url)
            if self._has_add_form(self._text(r)):
                return
        for path in ADD_CANDIDATES:
            r = self._request(path)
            if 300 <= r.get("status", 0) < 400 or "login" in (r.get("location", "") or "").lower():
                continue  # أُعيد لصفحة الدخول = ليست صفحة الإضافة
            html = self._text(r)
            if self._has_add_form(html):
                self.add_url = path
                action = self._form_action(html) or "/user_reseller.php"
                self.add_action = action
                self._save_meta(add_url=path, add_action=action)
                return
        raise RuntimeError("لم يُعثر على صفحة إضافة اليوزر (add-line)")

    @staticmethod
    def _form_action(html: str) -> str:
        m = re.search(r'<form[^>]*id=["\']user_form["\'][^>]*>', html, re.I) \
            or re.search(r'<form[^>]*>', html, re.I)
        if m:
            a = re.search(r'action=["\']([^"\']*)["\']', m.group(0), re.I)
            if a and a.group(1):
                return _html.unescape(a.group(1)).lstrip("./")
        return ""

    # ---- قراءة الباقات ----
    def packages(self) -> list:
        self.ensure_login()
        self.discover_add()
        r = self._request(self.add_url)
        html = self._text(r)
        m = self._PKG_SELECT.search(html)
        if not m:
            raise RuntimeError("قائمة الباقات غير موجودة في صفحة الإضافة")
        opts = []
        for om in re.finditer(r'<option[^>]*value=["\']([^"\']+)["\'][^>]*>(.*?)</option>', m.group(1), re.I | re.S):
            val = om.group(1).strip()
            text = _html.unescape(re.sub(r"<[^>]+>", "", om.group(2))).strip()
            if not val or re.search(r"select|choose|اختر", text, re.I):
                continue
            opts.append({"value": val, "text": text, "id": val, "name": text})
        return opts

    # ---- إنشاء يوزر ----
    def create_line(self, package_id, username=None, password=None, host=None) -> dict:
        self.ensure_login()
        self.discover_add()

        host = (host or self.acct.get("host", "")).strip().rstrip("/")
        username = str(username or _rand_digits())
        password = str(password or _rand_digits())

        # 1) صفحة الإضافة → member_id والحقول الافتراضية
        page = self._text(self._request(self.add_url))
        member_id = self._scrape_input(page, "member_id")
        if not member_id:
            raise RuntimeError("member_id غير موجود في صفحة الإضافة")
        is_official = self._scrape_input(page, "is_official") or "1"
        custom_playlist = self._scrape_input(page, "custom_playlist_id")
        action = self.add_action or self._form_action(page) or "/user_reseller.php"

        # 2) بوكيهات الباقة (= كل Subscribed)
        bq = self._request("/user_reseller.php?action=get_package&package_id=" + urllib.parse.quote(str(package_id)),
                           headers={"X-Requested-With": "XMLHttpRequest"})
        try:
            bj = json.loads(self._text(bq))
        except ValueError:
            bj = {}
        ids = [int(b["id"]) for b in (bj.get("bouquets") or []) if str(b.get("id", "")).strip().isdigit()]
        if not ids:
            raise RuntimeError("لا توجد بوكيهات للباقة %s" % package_id)

        # 3) الإنشاء (نقطة اللاعودة)
        body = {
            "is_official": is_official,
            "username": username,
            "password": password,
            "member_id": member_id,
            "package": str(package_id),
            "mac_address_mag": "",
            "mac_address_e2": "",
            "allow_epg": "on",
            "reseller_notes": "",
            "custom_playlist_id": custom_playlist,
            "selected_bouquets": json.dumps(ids),
            "submit_user": "1",
        }
        self._request(action, data=body, headers={"X-Requested-With": "XMLHttpRequest"})

        # 4) تأكيد من جدول اللاينات
        found = None
        for _ in range(6):
            found = self._search_line(username)
            if found and found.get("id"):
                break
            time.sleep(1.2)
        if not (found and found.get("id")):
            raise RuntimeError("تعذّر تأكيد إنشاء اليوزر بعد الإرسال")

        line = "Host {h}  Password {p} Username {u}".format(h=host, p=password, u=username)
        return {
            "line": line, "username": username, "password": password, "host": host,
            "package_id": str(package_id), "line_id": found.get("id"),
            "exp": found.get("end", ""), "connections": found.get("conns", ""),
            "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

    def _search_line(self, username: str) -> dict:
        params = {
            "draw": "1", "start": "0", "length": "25",
            "search[value]": username, "_": str(int(time.time() * 1000)),
        }
        r = self._request("/table_search.php?" + urllib.parse.urlencode(params),
                          headers={"X-Requested-With": "XMLHttpRequest"})
        try:
            j = json.loads(self._text(r))
        except ValueError:
            return {}
        for row in (j.get("data") or []):
            s = " ".join(str(c) for c in row) if isinstance(row, list) else str(row)
            um = re.search(r"User:\s*([^<\s]+)", s)
            if not um or um.group(1) != username:
                continue
            pm = re.search(r"Pass:\s*([^<\s]+)", s)
            rid = re.search(r'userid=\\?"?(\d+)', s) or re.search(r'data-row-id=\\?"?(\d+)', s)
            end = re.search(r"End:\s*([0-9][0-9\-\/.]+)", s)
            conns = re.search(r"\d+\s*/\s*(\d+)\s*</a>", s)
            return {"id": rid.group(1) if rid else "", "user": um.group(1),
                    "pass": pm.group(1) if pm else "",
                    "end": end.group(1) if end else "",
                    "conns": conns.group(1) if conns else ""}
        return {}

    def logout_local(self):
        for p in (self.jar_path, self.meta_path):
            try:
                os.remove(p)
            except OSError:
                pass


def _rand_digits(n: int = 12) -> str:
    return str(secrets.randbelow(9) + 1) + "".join(str(secrets.randbelow(10)) for _ in range(n - 1))

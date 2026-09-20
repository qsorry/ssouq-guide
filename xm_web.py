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
  extend_line(user, pkg) → GET user_reseller_extend_modal.php?id=<line id> (نموذج التمديد)
                     ثم POST بنفس المسار، والتأكيد = تغيّر تاريخ الانتهاء في الجدول
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

    # صفحة الدخول تختلف من لوحة لأخرى: /login في مرح، وقد تكون /login.php أو الجذر في غيرها.
    LOGIN_CANDIDATES = ("/login", "/login.php", "/index.php", "/")
    IMAGE_MAGIC = (b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"BM", b"RIFF", b"<svg", b"<?xml")

    @staticmethod
    def _captcha_src(html: str) -> str:
        """رابط صورة الكابتشا كما تعرضه صفحة الدخول نفسها (أي <img> يذكر captcha في
        عنوانه أو معرّفه أو صنفه أو وصفه). فارغ = لم يُعثر عليه."""
        for m in re.finditer(r"<img\b[^>]*>", html, re.I):
            tag = m.group(0)
            src = re.search(r"""src=["']([^"']+)["']|src=([^\s>"']+)""", tag, re.I)
            if not src:
                continue
            url = _html.unescape(src.group(1) or src.group(2) or "").strip()
            if not url or url.startswith("data:"):
                continue
            if re.search(r"captcha|securimage|verify|vcode|kcaptcha|imagecode", tag, re.I):
                return url

        return ""

    @staticmethod
    def _looks_like_image(ctype: str, body: bytes) -> bool:
        if (ctype or "").lower().startswith("image/"):
            return True
        head = (body or b"")[:8].lstrip()
        return any(head.startswith(sig) for sig in PanelWebSession.IMAGE_MAGIC)

    def _login_page(self):
        """يجلب صفحة الدخول من أول مسار يعطي نموذجًا (ويتبع تحويلًا واحدًا)، ويحفظ مسارها."""
        tried = []
        known = self._meta().get("login_path")
        for path in ((known,) if known else ()) + self.LOGIN_CANDIDATES:
            r = self._request(path)
            if 300 <= r.get("status", 0) < 400 and r.get("location"):
                loc = r["location"]
                if "login" in loc.lower() or path == "/":
                    path = loc
                    r = self._request(loc)
            html = self._text(r)
            tried.append("%s→%s" % (path, r.get("status")))
            if r.get("status", 0) < 400 and ('name="captcha"' in html.lower() or 'name="password"' in html.lower()):
                self._save_meta(login_path=path)
                return html
        raise RuntimeError("لم أجد صفحة الدخول في اللوحة (%s) — جرّبت: %s" % (self.base, ", ".join(tried)))

    @staticmethod
    def _parse_login_form(html: str) -> dict:
        """يقرأ نموذج الدخول كما هو: مساره، وكل حقوله بقيمها، وأيّها اسم المستخدم وكلمة
        المرور والكابتشا — فلا نفترض أسماء لوحة مرح على كل لوحة. لوحة بلا حقل كابتشا
        (ككاسبر) تُعرف هنا فلا تُطلب لها صورة أصلًا."""
        form_html = html
        for m in re.finditer(r"<form\b[^>]*>(.*?)</form>", html, re.I | re.S):
            if 'type="password"' in m.group(0).lower() or "type='password'" in m.group(0).lower():
                form_html = m.group(0)
                break
        act = re.search(r"""<form\b[^>]*\baction=["']([^"']*)["']""", form_html, re.I)
        fields, user_f, pass_f, cap_f = {}, "", "", ""
        for m in re.finditer(r"<(input|select|textarea)\b[^>]*>", form_html, re.I):
            tag = m.group(0)
            name = re.search(r"""\bname=["']([^"']+)["']""", tag, re.I)
            if not name:
                continue
            n = name.group(1)
            typ = (re.search(r"""\btype=["']([^"']+)["']""", tag, re.I) or [None, "text"])[1].lower()
            if typ in ("submit", "button", "image", "reset"):
                continue
            val = re.search(r"""\bvalue=["']([^"']*)["']""", tag, re.I)
            fields[n] = _html.unescape(val.group(1)) if val else ""
            low = n.lower()
            if typ == "password" and not pass_f:
                pass_f = n
            elif re.search(r"captcha|vcode|verif|code", low) and typ != "hidden" and not cap_f:
                cap_f = n
            elif re.search(r"user|login|email|name", low) and typ in ("text", "email") and not user_f:
                user_f = n
        return {"action": _html.unescape(act.group(1)) if act else "", "fields": fields,
                "user_field": user_f or "username", "pass_field": pass_f or "password",
                "captcha_field": cap_f}

    def begin(self):
        """جلسة دخول جديدة: تخطّي التحقق البشري + قراءة صفحة الدخول (PHPSESSID + النموذج كاملًا + رابط الكابتشا)."""
        self._handshake()
        html = self._login_page()
        form = self._parse_login_form(html)
        self._save_meta(
            lkey=self._scrape_input(html, "lkey"),
            referrer=self._scrape_input(html, "referrer"),
            access_code=self._scrape_input(html, "access_code"),
            captcha_url=self._captcha_src(html),
            login_form=form,
        )

    def needs_captcha(self) -> bool:
        """هل تطلب صفحة دخول اللوحة كود تحقق؟ (حقل كابتشا في النموذج أو صورة كابتشا)."""
        meta = self._meta()
        form = meta.get("login_form") or {}
        return bool(form.get("captcha_field") or meta.get("captcha_url"))

    def fetch_captcha(self):
        """(content_type, bytes) لصورة الكابتشا الحالية (مربوطة بجلسة PHPSESSID).
        الرابط يُقرأ من صفحة الدخول نفسها؛ وإن غاب فالمسار المعتاد captcha.php. وما ليس
        صورةً (404، صفحة دخول، حاجز حماية) يُرفع خطأً مقروءًا بدل صورة مكسورة."""
        url = self._meta().get("captcha_url") or "/captcha.php?a=1"
        base_login = self._meta().get("login_path") or "/login"
        url = urllib.parse.urljoin(self._abs(base_login), url)   # نسبيّ إلى صفحة الدخول
        url += ("&" if "?" in url else "?") + "t=%d" % int(time.time() * 1000)   # لا كاش
        r = self._request(url, headers={"Accept": "image/*,*/*", "Referer": self._abs(base_login)})
        ct, body = r.get("ctype") or "", r.get("body") or b""
        if r.get("status", 0) >= 400 or not self._looks_like_image(ct, body):
            snippet = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body[:600].decode("utf-8", "replace"))).strip()[:120]
            raise RuntimeError("اللوحة لم تُرجع صورة كود التحقق من %s (HTTP %s، %s)%s" % (
                url.split("?")[0].replace(self.base, "") or "/", r.get("status"), ct.split(";")[0] or "بلا نوع",
                (": " + snippet) if snippet else ""))
        return ct.split(";")[0] or "image/jpeg", body

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

        # لوحة بلا كود تحقق (ككاسبر): دخول مباشر بلا صورة ولا OCR ولا إنسان.
        if not self._meta().get("login_form"):
            self.begin()
        if not self.needs_captcha():
            return self._attempt_login("")

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
        form = meta.get("login_form") or {}
        # الحقول كما في صفحة اللوحة (المخفية بقيمها)، ثم بياناتنا في حقلَي الاسم وكلمة المرور،
        # والكود في حقل الكابتشا إن وُجد. الافتراضي = أسماء لوحة Xtream-Masters المعتادة.
        fields = dict(form.get("fields") or {
            "referrer": meta.get("referrer", ""), "access_code": meta.get("access_code", ""),
            "lkey": meta.get("lkey", ""), "username": "", "password": "", "captcha": ""})
        fields[form.get("user_field") or "username"] = self.acct.get("user", "")
        fields[form.get("pass_field") or "password"] = self.acct.get("password", "")
        if form.get("captcha_field"):
            fields[form["captcha_field"]] = captcha
        elif "captcha" in fields or not form:
            fields["captcha"] = captcha
        login_page = self._abs(meta.get("login_path") or "/login")
        action = urllib.parse.urljoin(login_page, form.get("action") or "/login.php")
        r = self._request(action, data=fields, headers={"Referer": login_page})
        body = self._text(r)
        loc = r.get("location", "") or r.get("final_url", "")

        # (أ) تحويل 30x يحمل error=... (اللوحة تفعلها لخطأ الكابتشا)
        m = re.search(r"[?&]error=([a-z0-9_\-]+)", loc, re.I)
        if m:
            code = m.group(1).lower()
            if code in ("captcha", "code"):
                _, img = self.fetch_captcha()
                raise CaptchaNeeded("image/jpeg", img, "captcha")
            raise LoginFailed("credentials" if code in ("login", "password", "user") else code,
                              self._login_error_msg(code))

        # (ب) ردّ 200 يعيد صفحة الدخول = فشل. نميّز سببه من رسالة alert في الصفحة،
        # لأن اللوحة ترجع "Incorrect username or password" (بيانات) بردّ 200 لا بتحويل،
        # فلا يصح عدّ كل 200-فيه-نموذج خطأَ كابتشا.
        still_login = 'id="login_form"' in body or 'name="captcha"' in body or 'type="password"' in body.lower()
        if still_login:
            alert = self._extract_alert(body)
            kind = self._classify_login_error(alert)
            if kind == "captcha":
                _, img = self.fetch_captcha()
                raise CaptchaNeeded("image/jpeg", img, "captcha")
            raise LoginFailed(kind, alert or self._login_error_msg(kind))

        # (ج) لم نعد على صفحة الدخول → نجاح، ونتأكد بجلب صفحة محمية.
        if not self.is_authenticated():
            raise LoginFailed("not_authenticated", "قُبل الطلب لكن الجلسة غير مُصادَقة (أُرسل إلى %s بالحقول: %s)" % (
                action.replace(self.base, "") or "/", ", ".join(sorted(fields)) or "—"))
        return True

    @staticmethod
    def _extract_alert(html: str) -> str:
        """نص أول تنبيه خطأ في صفحة الدخول (alert-danger)، منظّفًا من الوسوم."""
        m = re.search(r'<div[^>]*class=["\'][^"\']*alert-danger[^"\']*["\'][^>]*>(.*?)</div>',
                      html, re.I | re.S)
        if not m:
            return ""
        txt = re.sub(r"<[^>]+>", " ", m.group(1))
        txt = _html.unescape(re.sub(r"\s+", " ", txt)).strip(" ××")
        return txt[:200]

    @staticmethod
    def _classify_login_error(alert: str) -> str:
        a = (alert or "").lower()
        if any(k in a for k in ("captcha", "verification code", "الكود", "رمز التحقق", "wrong code")):
            return "captcha"
        if any(k in a for k in ("username", "password", "incorrect", "invalid login",
                                "credential", "كلمة المرور", "اسم المستخدم", "بيانات")):
            return "credentials"
        if any(k in a for k in ("blocked", "banned", "محظور", "suspend")):
            return "blocked"
        # صفحة دخول بلا رسالة واضحة: الأرجح بيانات خاطئة.
        return "credentials"

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
        if 'id="login_form"' in body or ('name="password"' in low and "captcha" in low) \
                or ('type="password"' in low and "<form" in low):
            return False
        for gate in ("xm_simple_security_check", "verifying your browser",
                     "security verification", "check.html", "token.php"):
            if gate in low:
                return False
        return r.get("status", 0) < 400

    _LOGIN_LOCKS = {}
    _LOCKS_GUARD = __import__("threading").Lock()

    def _login_lock(self):
        with self._LOCKS_GUARD:
            return self._LOGIN_LOCKS.setdefault(self.jar_path, __import__("threading").Lock())

    def ensure_login(self):
        """يعيد استخدام الكوكيز المحفوظة؛ ولو انتهت الجلسة يسجّل الدخول آليًا.
        قفل لكل بوابة: صفحة الإنشاء تطلب الرصيد والباقات معًا، فلو دخل الاثنان في آن واحد
        كتب كلٌّ جلسته فوق جلسة الآخر وظهر أحدهما "بيانات غير صحيحة" بلا سبب."""
        with self._login_lock():
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
    def _field_value(html: str, name: str) -> str:
        """قيمة حقل النموذج مهما كان نوعه (input/select/textarea)، بأي ترتيب
        سمات أو نمط اقتباس — يطابق منطق val() في سكربت السيلينيوم."""
        nq = re.escape(name)
        # input: value مقتبسة أو غير مقتبسة
        m = re.search(r'<input\b[^>]*\bname=["\']?%s["\'\s/>][^>]*>' % nq, html, re.I)
        if m:
            v = re.search(r'\bvalue=["\']([^"\']*)["\']', m.group(0), re.I) \
                or re.search(r'\bvalue=([^\s"\'>]+)', m.group(0), re.I)
            if v:
                return _html.unescape(v.group(1))
        # select: الخيار المحدَّد ثم أول خيار له قيمة
        sm = re.search(r'<select\b[^>]*\bname=["\']?%s["\'\s>][^>]*>(.*?)</select>' % nq, html, re.I | re.S)
        if sm:
            opts = re.findall(r'<option\b([^>]*)>(.*?)</option>', sm.group(1), re.I | re.S)
            for want_sel in (True, False):
                for attrs, _txt in opts:
                    if want_sel and not re.search(r'\bselected\b', attrs, re.I):
                        continue
                    vv = re.search(r'\bvalue=["\']?([^"\'\s>]*)', attrs, re.I)
                    if vv and vv.group(1):
                        return _html.unescape(vv.group(1))
        # textarea
        tm = re.search(r'<textarea\b[^>]*\bname=["\']?%s["\'\s>][^>]*>(.*?)</textarea>' % nq, html, re.I | re.S)
        if tm:
            return _html.unescape(re.sub(r"<[^>]+>", "", tm.group(1))).strip()
        return ""

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

    # ---- بوكيهات الباقة ----
    @staticmethod
    def _bouquet_ids(obj) -> list:
        """كل معرّفات البوكيهات في ردّ JSON مهما كان شكله: {"bouquets":[{"id":1}]} كما في
        مرح، أو {"data":{"bouquet_ids":["1","2"]}}، أو قائمة أرقام مباشرة، أو نص JSON
        داخل نص. تُفضَّل القوائم تحت مفتاح يذكر bouquet؛ وإلا أي قائمة معرّفات."""
        def ids_of(v):
            if isinstance(v, str):
                v = v.strip()
                if v.startswith(("[", "{")):
                    try:
                        return ids_of(json.loads(v))
                    except ValueError:
                        return []
                return [int(x) for x in re.split(r"[,\s]+", v) if x.isdigit()] if re.fullmatch(r"[\d,\s]+", v) else []
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return [int(v)]
            if isinstance(v, dict):
                for k in ("id", "bouquet_id", "bid", "value"):
                    if str(v.get(k, "")).strip().lstrip("-").isdigit():
                        return [int(v[k])]
                return []
            if isinstance(v, list):
                out = []
                for it in v:
                    out += ids_of(it)
                return out
            return []

        preferred, fallback = [], []

        def walk(node, key=""):
            if isinstance(node, dict):
                for k, v in node.items():
                    walk(v, str(k))
            elif isinstance(node, list):
                got = ids_of(node)
                if got:
                    (preferred if re.search(r"bouquet|bqt|packages?_?ch|channels?", key, re.I) else fallback).extend(got)
                else:
                    for it in node:
                        walk(it, key)
            elif isinstance(node, str) and re.search(r"bouquet", key, re.I):
                preferred.extend(ids_of(node))

        if isinstance(obj, str):
            try:
                obj = json.loads(obj)
            except ValueError:
                return []
        walk(obj)
        seen, out = set(), []
        for i in (preferred or fallback):
            if i not in seen:
                seen.add(i)
                out.append(i)
        return out

    @staticmethod
    def _page_bouquets(page: str) -> list:
        """معرّفات البوكيهات من عناصر صفحة الإضافة (checkbox/select باسم يذكر bouquet)."""
        out = []
        for m in re.finditer(r"<(input|option)\b[^>]*>", page, re.I):
            tag = m.group(0)
            ctx = tag
            if m.group(1).lower() == "option":
                sel = re.search(r"<select\b[^>]*name=[\"']([^\"']*)[\"'][^>]*>(?:(?!</select>).)*?" + re.escape(tag), page, re.I | re.S)
                ctx = (sel.group(1) if sel else "") + tag
            if not re.search(r"bouquet", ctx, re.I):
                continue
            v = re.search(r"""\bvalue=["']?(\d+)""", tag, re.I)
            if v:
                out.append(int(v.group(1)))
        return sorted(set(out))

    def _package_bouquets(self, package_id, page: str):
        """(ids, why): البوكيهات من get_package (نسبيًّا إلى صفحة الإضافة، ثم المسار المعتاد)،
        وإلا من الصفحة؛ وwhy يصف ما رُئي حين لا شيء."""
        tried = []
        add_path = urllib.parse.urlparse(self._abs(self.add_url or "/user_reseller.php")).path or "/user_reseller.php"
        for path in dict.fromkeys([add_path, "/user_reseller.php"]):
            url = path + "?action=get_package&package_id=" + urllib.parse.quote(str(package_id))
            r = self._request(url, headers={"X-Requested-With": "XMLHttpRequest",
                                            "Accept": "application/json,text/javascript,*/*"})
            text = self._text(r)
            ids = self._bouquet_ids(text)
            if ids:
                return ids, ""
            snippet = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text[:400])).strip()[:100]
            tried.append("%s → HTTP %s %s%s" % (url.split("?")[0], r.get("status"), (r.get("ctype") or "").split(";")[0],
                                                 (": " + snippet) if snippet else ""))
        ids = self._page_bouquets(page)
        if ids:
            return ids, ""
        return [], "ردّ get_package بلا معرّفات (%s) ولا عناصر بوكيهات في صفحة الإضافة" % "؛ ".join(tried)

    @classmethod
    def _add_form(cls, page: str) -> dict:
        """نموذج الإضافة كما تعرّفه اللوحة: مساره، حقوله بقيمها الافتراضية (المخفية،
        والنصية بقيمها، وselect بخياره المحدَّد، وcheckbox المؤشَّر)، واسم حقل الباقة،
        واسم زر الإرسال. فيُرسَل ما تتوقعه اللوحة نفسها لا ما تتوقعه لوحة مرح."""
        form_html = page
        for m in re.finditer(r"<form\b[^>]*>(.*?)</form>", page, re.I | re.S):
            if cls._PKG_SELECT.search(m.group(0)):
                form_html = m.group(0)
                break
        act = re.search(r"""<form\b[^>]*\baction=["']([^"']*)["']""", form_html, re.I)
        fields, submit, pkg_field = {}, "", ""
        for m in re.finditer(r"<(input|select|textarea|button)\b[^>]*>", form_html, re.I):
            tag = m.group(0)
            kind = m.group(1).lower()
            name = re.search(r"""\bname=["']([^"']+)["']""", tag, re.I)
            if not name:
                continue
            n = name.group(1)
            typ = (re.search(r"""\btype=["']([^"']+)["']""", tag, re.I) or [None, "text" if kind == "input" else kind])[1].lower()
            if kind == "button" or typ in ("submit", "image"):
                if not submit and re.search(r"submit|save|add|create", n, re.I):
                    submit = n
                continue
            if typ in ("button", "reset", "file"):
                continue
            if typ in ("checkbox", "radio") and not re.search(r"\bchecked\b", tag, re.I):
                continue
            if kind == "select":
                fields[n] = cls._field_value(page, n)
                if cls._PKG_SELECT.search(tag + "</select>") or re.search(r"package", n, re.I):
                    pkg_field = pkg_field or n
                continue
            val = re.search(r"""\bvalue=["']([^"']*)["']""", tag, re.I)
            fields[n] = _html.unescape(val.group(1)) if val else ""
        return {"action": _html.unescape(act.group(1)) if act else "", "fields": fields,
                "submit": submit, "package_field": pkg_field or "package"}

    # ---- إنشاء يوزر ----
    def _prepare_add(self, package_id, host=None) -> dict:
        """كل ما يسبق الإرسال ويصلح لدفعة كاملة: الدخول مرة، اكتشاف صفحة الإضافة، جلبها
        مرة، قراءة نموذجها، وبوكيهات الباقة. الدفعة من ٥٠ يوزرًا تدفع هذا مرة واحدة
        ثم طلب إرسال واحدًا لكل يوزر — لا ثلاثة طلبات لكل يوزر."""
        t0 = time.time()
        self.ensure_login()
        t_login = time.time()
        self.discover_add()
        host = (host or self.acct.get("host", "")).strip().rstrip("/")

        # 1) صفحة الإضافة → member_id والحقول الافتراضية (input/select/textarea)
        page = self._text(self._request(self.add_url))
        t_page = time.time()
        member_id = self._field_value(page, "member_id")
        if not member_id:
            names = ", ".join(sorted(set(re.findall(
                r'name=["\']([^"\']*member[^"\']*)["\']', page, re.I)))) or "لا يوجد حقل باسم يحوي member"
            raise RuntimeError("member_id غير موجود في صفحة الإضافة (الحقول المتاحة: %s)" % names)
        is_official = self._field_value(page, "is_official") or "1"
        custom_playlist = self._field_value(page, "custom_playlist_id")
        action = self.add_action or self._form_action(page) or "/user_reseller.php"

        # 2) بوكيهات الباقة (= كل Subscribed): من نداء get_package بأي شكل JSON، وإلا من
        #    عناصر البوكيهات في صفحة الإضافة نفسها؛ وإن لم يوجد شيء نقول ما ردّت به اللوحة.
        if self._meta().get("bouquets_by_panel"):
            ids = []
        else:
            ids, _why = self._package_bouquets(package_id, page)
            if not ids:
                self._save_meta(bouquets_by_panel=True)   # لا يُعاد الاستكشاف في كل إنشاء
        # لوحة لا تعرض بوكيهات للريسيلر (Xtream Codes الأصلي: لا get_package ولا عناصر في
        # الصفحة) تحدّدها هي من الباقة — فنرسل النموذج بلا selected_bouquets.
        panel_bouquets = not ids

        # 3) جسم الإرسال: حقول نموذج اللوحة نفسه فوق افتراضيات Xtream-Masters
        form = self._add_form(page)
        body = {
            "is_official": is_official,
            "member_id": member_id,
            "mac_address_mag": "",
            "mac_address_e2": "",
            "allow_epg": "on",
            "reseller_notes": "",
            "custom_playlist_id": custom_playlist,
        }
        body.update(form.get("fields") or {})
        body[form.get("package_field") or "package"] = str(package_id)
        if not panel_bouquets:
            body["selected_bouquets"] = json.dumps(ids)
        else:
            body.pop("selected_bouquets", None)
        body[form.get("submit") or "submit_user"] = "1"
        if form.get("action"):
            action = form["action"]
        add_abs = self._abs(self.add_url or "/user_reseller.php")
        return {"package_id": str(package_id), "host": host, "body": body, "ids": ids,
                "panel_bouquets": panel_bouquets, "action": urllib.parse.urljoin(add_abs, action),
                "referer": add_abs,
                "timing": {"login_ms": int((t_login - t0) * 1000), "page_ms": int((t_page - t_login) * 1000),
                           "bouquets_ms": int((time.time() - t_page) * 1000)}}

    def _submit_add(self, prep: dict, username: str, password: str) -> dict:
        """إرسال يوزر واحد بجسم مُعدّ مسبقًا (نقطة اللاعودة) ثم تأكيد غير حاسم."""
        body = dict(prep["body"])
        body["username"] = username
        body["password"] = password
        t0 = time.time()
        cr = self._request(prep["action"], data=body,
                           headers={"X-Requested-With": "XMLHttpRequest", "Referer": prep["referer"]})
        t_post = time.time()

        # إن ردّت اللوحة بخطأ صريح على الإنشاء نفسه، أوقف (لم يُخصم/لم يُنشأ).
        alert = self._extract_alert(self._text(cr))
        if alert and self._classify_login_error(alert) != "credentials" \
                and re.search(r"error|fail|خطأ|فشل|not\s|invalid|denied|exceed|رصيد|credit", alert, re.I):
            raise RuntimeError("رفضت اللوحة الإنشاء: " + alert)

        # 4) تأكيد من جدول اللاينات (لجلب الـ id/الانتهاء) — **غير حاسم**:
        # الإنشاء نقطة لا عودة (يُخصم الرصيد)، فلا نفقد بيانات اليوزر لو تأخّر البحث.
        # عدد المحاولات يتكيّف مع اللوحة: التي أثبتت أنها تجد يوزرنا (مرح) تُمهل حتى 6
        # محاولات، والمجهولة محاولتان، والتي تردّ جدولًا لا يجد يوزرنا أبدًا (Xtream Codes:
        # table_search.php موجود لكن بأعمدة وبحث آخرين) تُوقَف بعد ثلاث إخفاقات متتالية —
        # وإلا دفع كل يوزر 6 × 1.2 ثانية انتظارًا لتأكيد لن يأتي.
        meta = self._meta()
        found = {}
        if not meta.get("no_table_search"):
            attempts = 6 if meta.get("table_search_ok") else 2
            for i in range(attempts):
                try:
                    found = self._search_line(username)
                except Exception:
                    found = {}
                if (found and found.get("id")) or self._meta().get("no_table_search"):
                    break
                if i < attempts - 1:
                    time.sleep(1.2)
            if found and found.get("id"):
                self._save_meta(table_search_ok=True, confirm_misses=0)
            elif not meta.get("table_search_ok"):
                misses = int(meta.get("confirm_misses") or 0) + 1
                self._save_meta(confirm_misses=misses, **({"no_table_search": True} if misses >= 3 else {}))

        # اسم/كلمة المرور اللذان أرسلناهما هما ما سجّلته اللوحة (تركناهما فارغين =
        # ولّدناهما نحن)، فنعرضهما دائمًا حتى لو تعذّر التأكيد.
        u_final = found.get("user") or username
        p_final = found.get("pass") or password
        host = prep["host"]
        line = "Host {h}  Password {p} Username {u}".format(h=host, p=p_final, u=u_final)
        return {
            "line": line, "username": u_final, "password": p_final, "host": host,
            "package_id": prep["package_id"], "line_id": found.get("id", ""),
            "exp": found.get("end", ""), "connections": found.get("conns", ""),
            "verified": bool(found.get("id")),
            "bouquets": "panel" if prep["panel_bouquets"] else prep["ids"],
            "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "timing": {**prep.get("timing", {}), "post_ms": int((t_post - t0) * 1000),
                       "confirm_ms": int((time.time() - t_post) * 1000)},
        }

    def create_line(self, package_id, username=None, password=None, host=None) -> dict:
        prep = self._prepare_add(package_id, host)
        return self._submit_add(prep, str(username or _rand_digits()), str(password or _rand_digits()))

    def create_many(self, package_id, pairs, host=None) -> list:
        """دفعة: (اسم، كلمة مرور) لكل يوزر — تحضير واحد ثم إرسال لكل زوج. يرجّع النتائج
        بالترتيب؛ وإن فشل يوزر في المنتصف تُعاد النتائج الناجحة قبله مع الخطأ
        (نقطة اللاعودة: ما أُنشئ قد خُصم، فلا يضيع)."""
        prep = self._prepare_add(package_id, host)
        out = []
        for u, p in pairs:
            try:
                out.append(self._submit_add(prep, str(u), str(p)))
            except Exception as e:
                out.append({"error": str(e)[:200], "username": str(u), "password": str(p)})
                break
        return out

    # ---- تمديد يوزر (ExtendUser) ----
    # نفس ما تفعله اللوحة من زر Extend (ومطابق لسكربت السيلينيوم المثبت): نموذج التمديد
    # يُجلب من user_reseller_extend_modal.php?id=<line id>، ثم يُرسل POST لنفس المسار
    # بحقوله المخفية + edit + package + selected_connections + submit_user=1.
    EXTEND_PATH = "/user_reseller_extend_modal.php"

    def supports_extend(self) -> bool:
        """هل للوحة نافذة تمديد؟ (Xtream-Masters نعم؛ Xtream Codes الأصلي لا: 404).
        يُفحص مرة واحدة ويُحفظ، فلا يكلّف كل تحميل للباقات طلبًا."""
        meta = self._meta()
        if "extend_modal" in meta:
            return bool(meta["extend_modal"])
        self.ensure_login()
        try:
            r = self._request(self.EXTEND_PATH + "?id=0", headers={"X-Requested-With": "XMLHttpRequest"})
            ok = r.get("status", 0) < 400 and "login" not in (r.get("location") or "").lower()
        except Exception:
            return False           # لا نحفظ فشل الشبكة كحقيقة عن اللوحة
        self._save_meta(extend_modal=ok)
        return ok

    @staticmethod
    def _extend_form(html: str) -> dict:
        """نموذج التمديد: حقوله المخفية بقيمها، وخيارات الباقات المسموحة
        (value، النص، data-connections)."""
        m = re.search(r"<form\b[^>]*\bid=[\"']extend_user_form[\"'][^>]*>(.*?)</form>", html, re.I | re.S)
        form_html = m.group(0) if m else html
        fields = {}
        for im in re.finditer(r"<input\b[^>]*>", form_html, re.I):
            tag = im.group(0)
            typ = (re.search(r"""\btype=["']([^"']+)["']""", tag, re.I) or [None, "text"])[1].lower()
            name = re.search(r"""\bname=["']([^"']+)["']""", tag, re.I)
            if typ != "hidden" or not name:
                continue
            val = re.search(r"""\bvalue=["']([^"']*)["']""", tag, re.I)
            fields[name.group(1)] = _html.unescape(val.group(1)) if val else ""
        sm = re.search(r"<select\b[^>]*\bname=[\"']package[\"'][^>]*>(.*?)</select>", form_html, re.I | re.S) \
            or re.search(r"<select\b[^>]*\bid=[\"']ext_package[\"'][^>]*>(.*?)</select>", html, re.I | re.S)
        options = []
        for om in re.finditer(r"<option\b([^>]*)>(.*?)</option>", sm.group(1) if sm else "", re.I | re.S):
            attrs, text = om.group(1), _html.unescape(re.sub(r"<[^>]+>", "", om.group(2))).strip()
            val = re.search(r"""\bvalue=["']([^"']*)["']""", attrs, re.I)
            if not val or not val.group(1).strip():
                continue
            conns = re.search(r"""\bdata-connections=["']([^"']*)["']""", attrs, re.I)
            options.append({"value": val.group(1).strip(), "text": text,
                            "connections": conns.group(1) if conns else ""})
        return {"found": bool(m), "fields": fields, "options": options}

    def extend_line(self, username: str, package_id, package_text: str = "") -> dict:
        """يمدّد يوزرًا قائمًا بباقة (نفس عدد الاتصالات). يرجّع {before, after, message, credits}.
        RuntimeError قبل الإرسال = لم يُخصم شيء؛ وبعده = راجع اللوحة."""
        self.ensure_login()
        before = self._search_line(username)
        if not before.get("id"):
            raise RuntimeError("اليوزر %s غير موجود في جدول اللوحة فلا يمكن تمديده" % username)
        url = self.EXTEND_PATH + "?id=" + urllib.parse.quote(str(before["id"]))
        page = self._text(self._request(url, headers={"X-Requested-With": "XMLHttpRequest"}))
        form = self._extend_form(page)
        if not form["found"]:
            alert = self._extract_alert(page)
            raise RuntimeError("نموذج التمديد غير موجود في اللوحة" + (": " + alert if alert else ""))
        norm = lambda t: re.sub(r"\s+", "", str(t or ""))
        opt = next((o for o in form["options"] if o["value"] == str(package_id)), None) \
            or (next((o for o in form["options"] if package_text and norm(o["text"]).startswith(norm(package_text))), None))
        if not opt:
            raise RuntimeError("الباقة %s غير متاحة للتمديد (تمديد بباقات نفس عدد الاتصالات فقط)" % package_id)
        body = dict(form["fields"])
        body["edit"] = before["id"]
        body["submit_user"] = "1"
        body["selected_connections"] = opt["connections"] or before.get("conns") or body.get("selected_connections") or "1"
        body.setdefault("group_change_confirmed", "0")
        body.setdefault("keep_remaining_days", "0")
        body["package"] = opt["value"]

        # نقطة اللاعودة
        r = self._request(url, data=body, headers={"X-Requested-With": "XMLHttpRequest"})
        txt = self._text(r)
        try:
            resp = json.loads(txt)
        except ValueError:
            resp = {}
        msg = str(resp.get("message", "")) if isinstance(resp, dict) else ""
        after = {}
        for i in range(6):
            try:
                after = self._search_line(username)
            except Exception:
                after = {}
            if after.get("id") and after.get("end") and after.get("end") != before.get("end"):
                break
            if i < 5:
                time.sleep(1.2)
        else:
            if isinstance(resp, dict) and str(resp.get("status", "")).lower() in ("error", "false", "0"):
                raise RuntimeError("رفضت اللوحة التمديد: " + (msg or txt[:200]))
            raise RuntimeError("لم يتغيّر تاريخ انتهاء %s بعد التمديد%s" % (username, (" (" + msg + ")") if msg else ""))
        return {"before": before.get("end", ""), "after": after.get("end", ""), "message": msg,
                "credits": (resp.get("new_credits") if isinstance(resp, dict) else None),
                "line_id": before["id"], "package": opt["text"]}

    # ---- حالة اللوحة (الرصيد + أرقام لوحة المعلومات) ----
    # الجذر "/" في لوحات كثيرة يردّ تحويلًا (30x) بجسم فارغ إلى لوحة المعلومات،
    # فنتبع التحويل ونجرّب مساراتها المعروفة حتى نصل لصفحة فيها الرصيد فعلًا.
    DASH_PATHS = ("/", "/dashboard", "/dashboard.php", "/home", "/home.php", "/index.php", "/reseller")

    def _get_follow(self, path, max_hops=4):
        r = self._request(path)
        hops = 0
        while 300 <= r.get("status", 0) < 400 and hops < max_hops:
            loc = r.get("location", "")
            if not loc or "login" in loc.lower():
                break
            r = self._request(loc)
            hops += 1
        return r

    def _dashboard_html(self) -> str:
        """أول صفحة لوحة مصادَقة غير فارغة (بعد اتّباع التحويلات)."""
        for path in self.DASH_PATHS:
            body = self._text(self._get_follow(path))
            low = body.lower()
            if body.strip() and 'id="login_form"' not in low and 'name="captcha"' not in low:
                return body
        return ""

    def status(self) -> dict:
        """يقرأ صفحة اللوحة المصادَقة ويستخرج الرصيد (Credits) وبعض أرقامها.
        الرصيد ظاهر على الصفحة نفسها ("Credits: N")، فنلتقطه كما تلتقطه فالكون."""
        self.ensure_login()
        html = self._dashboard_html()
        # آخر يوزر أُنشئ = أول صف في جدول اللاينات مرتَّبًا من الأحدث (كما في فالكون)،
        # ومعه العدد الكلي من الجدول احتياطًا إن لم تُقرأ بطاقة لوحة المعلومات.
        last, table_total = {}, None
        try:
            t = self._table_query("", 1)
            last, table_total = (t["rows"][0] if t["rows"] else {}), t["total"]
        except Exception:
            pass
        # "عدد اليوزرات" = عدد لايناته من جدول اللوحة (رقم موثوق من الخادم، وهو ما
        # يظهر 253)، ونلجأ لبطاقة لوحة المعلومات فقط إن غاب. أرقام "المتصلون
        # الآن/أُنشئ اليوم/الاشتراكات" تُحمَّل بجافاسكربت على اللوحة (تكون صفرًا في
        # HTML الخام)، فلا نعرضها كي لا تُضلِّل.
        dash_total = self._dashboard_number(html, r"active\s+(?:subscription|account)")
        return {
            "provider": "web",
            "credits": self._extract_credits(html),
            "host": self.acct.get("host", ""),
            "username": self.acct.get("user", ""),
            "total": table_total if table_total is not None else dash_total,
            "last_id": last.get("id"),
            "last_username": last.get("user"),
        }

    _KW = r"(?:(?<![a-z])(?:credits?|balance|credit\s*balance)(?![a-z])|الرصيد|رصيد\w*|النقاط|نقاط\w*|الكريد\w*|كريد\w*)"
    _CREDIT_RX = [
        re.compile(r'data-credits?\s*=\s*["\']?\s*([0-9][\d,]*(?:\.\d+)?)', re.I),
        re.compile(_KW + r'[^0-9<]{0,15}(?:<[^>]+>\s*){0,4}([0-9][\d,]*(?:\.\d+)?)', re.I | re.U),
        re.compile(r'([0-9][\d,]*(?:\.\d+)?)\s*(?:<[^>]+>\s*){0,4}[^0-9>]{0,8}' + _KW, re.I | re.U),
    ]

    _NUM = r'([0-9][\d,]*(?:\.\d+)?)'

    @staticmethod
    def _extract_credits(html: str):
        """رقم الرصيد من صفحة اللوحة. الصفحة قد تذكر "credits" في أكثر من موضع (قائمة
        جانبية ببادج 1، بطاقة 3,975.50 CREDITS…) فلا يُؤخذ أول تطابق بل **الأوثق**:
        data-credits، ثم بطاقة رقمها يليه لفظ الرصيد وحده في عنصره، ثم "Credits: N"
        بنقطتين، ثم أي تطابق عام — وعند التعادل الرقم الأكبر/ذو الكسور."""
        KW, NUM = PanelWebSession._KW, PanelWebSession._NUM
        TAGS = r'(?:<[^>]+>\s*)*'
        scored = []
        def add(rx, score, first_only=False, group=1):
            for m in re.finditer(rx, html, re.I | re.U):
                n = _to_num(m.group(group))
                if n is None:
                    continue
                sc = score
                # عدّاد تحرّكه جافاسكربت (counterup) يُطبع صفرًا في HTML: ليس الرصيد.
                around = html[max(0, m.start() - 160):m.start()] + m.group(0)
                if n == 0 and re.search(r"counterup|counter-up|data-count|data-target", around, re.I):
                    sc = 1
                scored.append((sc, ("." in m.group(group) or "," in m.group(group)), n))
                if first_only:
                    break
        add(r'data-credits?\s*=\s*["\']?\s*' + NUM, 100)
        # سجل العمليات في Xtream Codes: "Credits: 3975.5 -> 3974.5" — الرقم بعد السهم في
        # أحدث سطر (الأول في الصفحة) هو الرصيد الحالي، وهو أوثق من بطاقةٍ تملؤها جافاسكربت.
        add(r'credits?\s*:\s*' + TAGS + NUM + r'\s*' + TAGS + r'(?:-+&gt;|-+>|→|⇒)\s*' + TAGS + NUM, 95, first_only=True, group=2)
        add(NUM + r'\s*' + TAGS + KW + r'\s*(?:</|$)', 90)          # بطاقة: 3,975.50 </h3><p>CREDITS</p>
        add(KW + r'\s*:\s*' + TAGS + NUM, 80)                       # Credits: 1002
        add(KW + r'[^0-9<]{0,15}' + TAGS + NUM, 10)                   # عام: كلمة ثم رقم
        add(NUM + r'\s*' + TAGS + r'[^0-9>]{0,8}' + KW, 10)          # عام: رقم ثم كلمة
        scored = [t for t in scored if t[0] > 1]   # عدّاد صفر وحده = رصيد غير معروف، لا صفر
        if not scored:
            return None
        scored.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
        return scored[0][2]

    def diag_web(self) -> dict:
        """تشخيص مؤقّت: حالة كل مسار محتمل للوحة + مقتطفات حول كلمات الرصيد على
        الصفحة الفعلية (لا يحوي كلمات مرور — لوحة المُوزِّع)."""
        self.ensure_login()
        tries = []
        for path in self.DASH_PATHS:
            r = self._request(path)
            tries.append({"path": path, "status": r.get("status"),
                          "loc": (r.get("location") or "")[:140], "len": len(self._text(r))})
        html = self._dashboard_html()
        snips = []
        for m in re.finditer(r'.{0,160}(?:credit|balance|رصيد|نقاط|نقط|كريد|point).{0,160}', html, re.I | re.U | re.S):
            t = re.sub(r'\s+', ' ', m.group(0)).strip()
            if t and t not in snips:
                snips.append(t)
            if len(snips) >= 25:
                break
        return {"tries": tries, "dash_len": len(html), "scripts": html.lower().count("<script"),
                "credits": self._extract_credits(html), "snippets": snips}

    @staticmethod
    def _dashboard_number(html: str, label_re: str):
        """رقم بطاقةٍ يسبق تسميتها (قد تتخلّلهما وسوم فقط)، مثل "253 … ACTIVE SUBSCRIPTIONS"."""
        m = re.search(r'([0-9][\d,]*)\s*(?:<[^>]+>\s*)*' + label_re, html, re.I)
        return _to_num(m.group(1)) if m else None

    _TABLE_COLS = 12

    def _table_query(self, term: str = "", length: int = 10) -> dict:
        """استعلام جدول اللاينات (table_search.php) بنفس معاملات DataTables التي تطلبها
        اللوحة (id=users + الأعمدة كاملة) — وإلا رجّع لا شيء — مرتَّبًا من الأحدث.
        يرجّع {"rows": [صفوف مفكَّكة], "total": العدد الكلي إن أعلنته اللوحة}."""
        params = [("draw", "1")]
        for i in range(self._TABLE_COLS):
            params += [
                ("columns[%d][data]" % i, str(i)),
                ("columns[%d][name]" % i, ""),
                ("columns[%d][searchable]" % i, "true"),
                ("columns[%d][orderable]" % i, "false" if i in (3, 10, 11) else "true"),
                ("columns[%d][search][value]" % i, ""),
                ("columns[%d][search][regex]" % i, "false"),
            ]
        params += [
            ("order[0][column]", "0"), ("order[0][dir]", "desc"),
            ("start", "0"), ("length", str(int(length))),
            ("search[value]", term), ("search[regex]", "false"),
            ("id", "users"), ("filter", ""), ("reseller", ""),
            ("date_created_from", ""), ("date_created_to", ""),
            ("date_expire_from", ""), ("date_expire_to", ""),
            ("_", str(int(time.time() * 1000))),
        ]
        if self._meta().get("no_table_search"):
            return {"rows": [], "total": None}
        r = self._request("/table_search.php?" + urllib.parse.urlencode(params),
                          headers={"X-Requested-With": "XMLHttpRequest"})
        try:
            j = json.loads(self._text(r))
        except ValueError:
            # ليست JSON (404 أو صفحة HTML): اللوحة بلا جدول DataTables (Xtream Codes الأصلي).
            # نحفظ ذلك فلا نكرر النداء ولا ننتظر تأكيدًا لن يأتي بعد كل إنشاء.
            if r.get("status", 0) < 500:
                self._save_meta(no_table_search=True)
            return {"rows": [], "total": None}
        rows = []
        for row in (j.get("data") or []):
            s = " ".join(str(c) for c in row) if isinstance(row, list) else str(row)
            parsed = self._parse_row(s)
            if parsed:
                rows.append(parsed)
        total = j.get("recordsTotal")
        return {"rows": rows, "total": _to_num(total) if total is not None else None}

    @staticmethod
    def _parse_row(s: str) -> dict:
        """صف جدول اللاينات (نص HTML مسطَّح) → {id, user, pass, end, conns, status}."""
        um = re.search(r"User:\s*([^<\s]+)", s)
        if not um:
            return {}
        pm = re.search(r"Pass:\s*([^<\s]+)", s)
        rid = re.search(r'userid=\\?"?(\d+)', s) or re.search(r'data-row-id=\\?"?(\d+)', s)
        end = re.search(r"End:\s*([0-9][0-9\-\/.]+)", s)
        conns = re.search(r"\d+\s*/\s*(\d+)\s*</a>", s)
        low = s.lower()
        status = "expired" if "expired" in low else ("disabled" if re.search(r"disabled|banned", low) else "active")
        return {"id": rid.group(1) if rid else "", "user": um.group(1),
                "pass": pm.group(1) if pm else "",
                "end": end.group(1) if end else "",
                "conns": conns.group(1) if conns else "",
                "status": status}

    def _search_line(self, username: str) -> dict:
        for row in self._table_query(username, 10)["rows"]:
            if row["user"] == username:
                return row
        return {}

    def last_line(self) -> dict:
        """آخر يوزر أُنشئ على اللوحة (أول صف مرتَّبًا من الأحدث)."""
        rows = self._table_query("", 1)["rows"]
        return rows[0] if rows else {}

    def search(self, query: str, limit: int = 50) -> list:
        """بحث بالـ username أو الـ password عبر بحث الجدول نفسه (يفتّش كل الأعمدة)."""
        query = str(query or "").strip()
        if not query:
            return []
        return [{"id": r["id"], "username": r["user"], "password": r["pass"],
                 "status": r["status"], "exp": r["end"]}
                for r in self._table_query(query, limit)["rows"]]

    def logout_local(self):
        for p in (self.jar_path, self.meta_path):
            try:
                os.remove(p)
            except OSError:
                pass


def _to_num(s):
    """نص رقمي (بفواصل آلاف) → int أو float، وإلا None."""
    s = str(s).replace(",", "").strip()
    try:
        f = float(s)
        return int(f) if f.is_integer() else f
    except ValueError:
        return None


def _rand_digits(n: int = 12) -> str:
    return str(secrets.randbelow(9) + 1) + "".join(str(secrets.randbelow(10)) for _ in range(n - 1))

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
بريد حسابات Stremio: مستقبِلٌ صغير على خادمنا (SMTP على المنفذ 25) لعناوين `tv.ssouq.com` — بلا صناديق ولا إرسال.

حساب Stremio لا يحتاج صندوق بريد (Stremio لا يتحقّق من الإيميل)، والبريد يُحتاج لأمرٍ واحد: رابط «نسيت كلمة المرور».
فلا نظام بريدٍ كامل ولا حدّ لعدد العناوين: كل رسالةٍ تصل لعنوان حسابٍ من حساباتنا (‏known) تُحفظ نصًّا وروابط،
وتظهر في الأداة عند يوزرها. وما سواها يُرفض قبل أن يُرسل (‏550)، فلا يتراكم بريدٌ مزعج لعناوين عشوائية.

  لا يُرسل شيئًا ولا يمرّر (ليس open relay)        رسالة ≤ 2 ميجا · 20 مستلمًا · 40 اتصالًا معًا · مهلة دقيقة لكل سطر
  آخر 20 رسالة لكل عنوان، وما مضى عليه 60 يومًا يُحذف    data/mail/<العنوان>.json (النص مقتطعٌ والروابط)

يُشغَّل من الخادم متى ضُبط ‏XM_MAIL_PORT (‏25 في الحاوية — Dockerfile)، والدومين ‏STREMIO_EMAIL_DOMAIN.
ويحتاج على الدومين: سجلّ A ‏`tv` ← عنوان الخادم، وسجلّ MX ‏`tv` ← ‏`tv.ssouq.com`، والمنفذ 25 مفتوحًا للحاوية.
بلا مكتبات خارجية (‏smtpd أُزيل من بايثون 3.12، فالبروتوكول هنا بقدر ما يحتاجه الاستقبال).
"""
import datetime
import email
import email.policy
import email.utils
import html
import json
import os
import re
import secrets
import socketserver
import threading
import time

MAX_SIZE = 2 << 20
MAX_RCPT = 20
MAX_CONN = 40
LINE_MAX = 1000                      # سطر SMTP (‏RFC 5321: 512 للأوامر، 1000 للنص)
TIMEOUT = 60
SESSION_MAX = 300
KEEP = 20
TTL_DAYS = 60
TEXT_MAX = 4000

_lock = threading.Lock()


# ================= الحفظ =================
def _local(addr):
    return re.sub(r"[^a-z0-9._@-]", "_", str(addr or "").strip().lower())[:120]


def _path(data_dir, addr):
    return os.path.join(data_dir, "mail", _local(addr) + ".json")


def _fresh(msgs, now=None):
    cut = (now or time.time()) - TTL_DAYS * 86400
    return [m for m in msgs if isinstance(m, dict) and m.get("ts", 0) >= cut][:KEEP]


def messages(data_dir, addr):
    """رسائل عنوانٍ (الأحدث أولًا) — آخر 20، وبلا ما مضى عليه 60 يومًا."""
    try:
        with open(_path(data_dir, addr), encoding="utf-8") as f:
            return _fresh(json.load(f))
    except (OSError, ValueError):
        return []


def store(data_dir, addr, msg):
    p = _path(data_dir, addr)
    with _lock:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        msgs = _fresh([msg] + messages(data_dir, addr))
        tmp = f"{p}.{secrets.token_hex(4)}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(msgs, f, ensure_ascii=False)
        os.replace(tmp, p)


# ================= قراءة الرسالة =================
_TAGS = re.compile(r"(?is)<(script|style|head)\b.*?</\1>|<[^>]+>")
_URL = re.compile(r"https?://[^\s<>\"')\]]+")
_HREF = re.compile(r"""(?i)href\s*=\s*["'](https?://[^"']+)["']""")


def _html_text(h):
    h = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", "\n", h)
    t = html.unescape(_TAGS.sub(" ", h))
    return "\n".join(" ".join(line.split()) for line in t.splitlines() if line.strip())


def _content(part):
    try:
        return part.get_content()
    except (LookupError, ValueError, AttributeError):
        raw = part.get_payload(decode=True) or b""
        return raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)


def parse(raw):
    """الرسالة كما وصلت ← ‏{from, subject, date, text, links} — النص بلا وسوم HTML، والروابط (رابط إعادة تعيين كلمة
    المرور منها) من الوسوم ومن النص، بلا تكرار."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    links, text = [], ""
    plain = msg.get_body(preferencelist=("plain",))
    rich = msg.get_body(preferencelist=("html",))
    if rich is not None:
        h = str(_content(rich))
        links += _HREF.findall(h)
        if plain is None:
            text = _html_text(h)
    if plain is not None:
        text = str(_content(plain))
    links += _URL.findall(text)
    seen, out = set(), []
    for u in links:
        u = html.unescape(u).rstrip(".,;:!?")
        if u not in seen:
            seen.add(u)
            out.append(u)
    try:
        when = email.utils.parsedate_to_datetime(str(msg.get("date", ""))).astimezone(datetime.timezone.utc)
    except (TypeError, ValueError, IndexError):
        when = datetime.datetime.now(datetime.timezone.utc)
    return {"from": str(msg.get("from", ""))[:200], "subject": " ".join(str(msg.get("subject", "")).split())[:300],
            "date": when.strftime("%Y-%m-%d %H:%M"), "ts": int(time.time()),
            "text": text.strip()[:TEXT_MAX], "links": out[:15]}


# ================= SMTP =================
_ADDR = re.compile(r"(?i)^(?:MAIL\s+FROM|RCPT\s+TO)\s*:\s*<?([^<>\s]*)>?(.*)$")


class _Handler(socketserver.StreamRequestHandler):
    timeout = TIMEOUT

    def _say(self, line):
        self.wfile.write((line + "\r\n").encode("ascii", "replace"))

    def handle(self):
        srv = self.server
        if not srv.slots.acquire(blocking=False):
            self._say("421 4.3.2 too busy, try later")
            return
        try:
            self._session()
        except (OSError, ValueError):
            pass                          # انقطع المرسل أو انتهت مهلته
        finally:
            srv.slots.release()

    def _readline(self):
        line = self.rfile.readline(LINE_MAX + 2)
        if len(line) > LINE_MAX and not line.endswith(b"\n"):
            raise ValueError("line too long")
        return line

    def _session(self):
        srv = self.server
        self._say(f"220 {srv.hostname} ESMTP")
        sender, rcpts, start = None, [], time.time()
        while time.time() - start < SESSION_MAX:
            line = self._readline()
            if not line:
                return
            cmd = line.decode("utf-8", "replace").strip()
            verb = cmd.split(" ", 1)[0].upper()
            if verb == "EHLO":
                self._say(f"250-{srv.hostname}")
                self._say(f"250-SIZE {MAX_SIZE}")
                self._say("250 8BITMIME")
            elif verb == "HELO":
                self._say(f"250 {srv.hostname}")
            elif verb == "MAIL":
                m = _ADDR.match(cmd)
                size = re.search(r"(?i)\bSIZE=(\d+)", m.group(2)) if m else None
                if not m:
                    self._say("501 5.5.4 syntax: MAIL FROM:<address>")
                elif size and int(size.group(1)) > MAX_SIZE:
                    self._say("552 5.3.4 message too big")
                else:
                    sender, rcpts = m.group(1), []
                    self._say("250 2.1.0 OK")
            elif verb == "RCPT":
                m = _ADDR.match(cmd)
                addr = (m.group(1) if m else "").lower()
                if sender is None:
                    self._say("503 5.5.1 MAIL first")
                elif not m or "@" not in addr:
                    self._say("501 5.5.4 syntax: RCPT TO:<address>")
                elif addr.rsplit("@", 1)[1] not in srv.domains:
                    self._say("550 5.7.1 relaying denied")          # لا نمرّر لغير دومينا أبدًا
                elif not srv.known(addr):
                    self._say("550 5.1.1 no such user")
                elif len(rcpts) >= MAX_RCPT:
                    self._say("452 4.5.3 too many recipients")
                else:
                    if addr not in rcpts:
                        rcpts.append(addr)
                    self._say("250 2.1.5 OK")
            elif verb == "DATA":
                if not rcpts:
                    self._say("503 5.5.1 RCPT first")
                    continue
                self._say("354 end with <CRLF>.<CRLF>")
                raw, too_big = self._data()
                if too_big:
                    self._say("552 5.3.4 message too big")
                else:
                    try:
                        msg = parse(raw)
                        for r in rcpts:
                            store(srv.data_dir, r, msg)
                        self._say("250 2.0.0 OK")
                    except Exception:            # noqa: BLE001 — رسالةٌ لا تُقرأ لا تُسقط الخادم
                        self._say("451 4.3.0 could not store message")
                sender, rcpts = None, []
            elif verb == "RSET":
                sender, rcpts = None, []
                self._say("250 2.0.0 OK")
            elif verb == "NOOP":
                self._say("250 2.0.0 OK")
            elif verb == "VRFY":
                self._say("252 2.5.0 cannot verify")
            elif verb == "QUIT":
                self._say("221 2.0.0 bye")
                return
            else:
                self._say("502 5.5.2 command not implemented")
        self._say("421 4.4.2 session too long")

    def _data(self):
        """نص الرسالة حتى «.» وحدها في سطر، بفكّ النقطة المضاعفة؛ وما تجاوز الحدّ يُقرأ ويُهمل."""
        buf, size, too_big = [], 0, False
        while True:
            line = self.rfile.readline(LINE_MAX * 4)
            if not line:
                raise ValueError("connection closed in DATA")
            if line in (b".\r\n", b".\n"):
                return b"".join(buf), too_big
            if line.startswith(b"."):
                line = line[1:]
            size += len(line)
            if size > MAX_SIZE:
                too_big, buf = True, []
            elif not too_big:
                buf.append(line)


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def start(data_dir, port, domains, known, host="0.0.0.0", hostname=None):
    """يشغّل المستقبِل في خيطٍ مستقل ويُرجعه (‏.shutdown() لإيقافه). ‏known(العنوان) ← هل هو عنوان حسابٍ لنا."""
    srv = _Server((host, int(port)), _Handler)
    srv.data_dir, srv.known = data_dir, known
    srv.domains = {d.strip().lower() for d in domains if d and d.strip()}
    srv.hostname = hostname or next(iter(sorted(srv.domains)), "localhost")
    srv.slots = threading.BoundedSemaphore(MAX_CONN)
    threading.Thread(target=srv.serve_forever, daemon=True, name="mail-inbox").start()
    return srv

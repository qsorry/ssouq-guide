#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مستقبِل بريد حسابات Stremio (‏mail_inbox.py) بـ SMTP حقيقي (‏smtplib): يقبل عناوين حساباتنا على tv.ssouq.com وحدها،
ويرفض غيرها وأي تمرير، ويحفظ الرسالة نصًّا وروابط (HTML وbase64 وquoted-printable وعنوانٌ عربي)، بحدودها:
الحجم والمستلمون والاتصالات وآخر 20 رسالة و60 يومًا.

    python tests/test_mail_inbox.py
"""
import os
import shutil
import smtplib
import socket
import sys
import tempfile
import time
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import mail_inbox as M  # noqa: E402

_p = _f = 0
KNOWN = {"0504998661ali@tv.ssouq.com", "777@tv.ssouq.com"}


def check(label, cond, extra=""):
    global _p, _f
    if cond:
        _p += 1
        print("  \033[32mPASS\033[0m  " + label + (("  (%s)" % extra) if extra else ""))
    else:
        _f += 1
        print("  \033[31mFAIL\033[0m  " + label + (("  (%s)" % extra) if extra else ""))


def reset_mail(link):
    """رسالة «نسيت كلمة المرور» كما يرسلها موقعٌ عادة: نصٌّ وHTML، والرابط في الاثنين."""
    m = MIMEMultipart("alternative")
    m["From"] = "Stremio <no-reply@strem.io>"
    m["To"] = "0504998661ali@tv.ssouq.com"
    m["Subject"] = "Reset your Stremio password"
    m["Date"] = "Fri, 02 Oct 2026 13:00:00 +0000"
    m.attach(MIMEText(f"Hi,\nClick to reset: {link}\nThanks", "plain", "utf-8"))
    m.attach(MIMEText(f'<html><body><p>Hi,</p><a href="{link}">Reset password</a><style>.x{{}}</style></body></html>', "html", "utf-8"))
    return m.as_string()


def main():
    d = tempfile.mkdtemp(prefix="mail_")
    srv = M.start(d, 0, ["tv.ssouq.com"], lambda a: a in KNOWN, host="127.0.0.1")
    port = srv.server_address[1]
    try:
        print("== الاستقبال ==")
        link = "https://www.stremio.com/reset-password/abc123?token=XYZ&x=1"
        with smtplib.SMTP("127.0.0.1", port, timeout=10) as s:
            code, banner = s.ehlo("mta.example")
            check("EHLO يعلن الحجم الأقصى", code == 250 and s.has_extn("size") and int(s.esmtp_features["size"]) == M.MAX_SIZE)
            s.sendmail("no-reply@strem.io", ["0504998661ali@tv.ssouq.com"], reset_mail(link))
        got = M.messages(d, "0504998661ali@tv.ssouq.com")
        check("الرسالة محفوظةٌ لعنوانها", len(got) == 1 and got[0]["subject"] == "Reset your Stremio password", str(got)[:150])
        check("رابط إعادة التعيين أول روابطها، كما هو (بـ&)", got and got[0]["links"][0] == link, str(got and got[0]["links"]))
        check("النص المقروء (لا HTML)", got and "Click to reset" in got[0]["text"] and "<a" not in got[0]["text"])
        check("المرسل والتاريخ", got and "no-reply@strem.io" in got[0]["from"] and got[0]["date"] == "2026-10-02 13:00")
        check("عنوانٌ بحروفٍ كبيرة يصل للعنوان نفسه", _send(port, "0504998661ALI@TV.ssouq.com", "Subject: Upper\r\n\r\nhi\r\n")[0] == 250
              and M.messages(d, "0504998661ali@tv.ssouq.com")[0]["subject"] == "Upper")

        print("== HTML وحده وترميزات وعربية ==")
        m = MIMEText('<div>مرحبا<br>الرابط: <a href="https://example.com/r?a=1&amp;b=2">هنا</a></div>', "html", "utf-8")
        m["Subject"] = Header("إعادة تعيين كلمة المرور", "utf-8")
        _send(port, "777@tv.ssouq.com", m.as_string())
        g = M.messages(d, "777@tv.ssouq.com")[0]
        check("عنوانٌ عربي مرمَّز يُقرأ", g["subject"] == "إعادة تعيين كلمة المرور", g["subject"])
        check("HTML وحده ← نصٌّ بأسطره وبلا وسوم، و&amp; في الرابط ← &", "مرحبا" in g["text"] and "<" not in g["text"]
              and g["links"] == ["https://example.com/r?a=1&b=2"], str(g))
        _send(port, "777@tv.ssouq.com", "Subject: QP\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Transfer-Encoding: quoted-printable\r\n\r\n"
              "caf=C3=A9 https://q.example/p?x=3D1\r\n")
        g = M.messages(d, "777@tv.ssouq.com")[0]
        check("quoted-printable يُفكّ", g["text"].startswith("café") and g["links"] == ["https://q.example/p?x=1"], str(g))
        _send(port, "777@tv.ssouq.com", "Subject: dots\r\n\r\n.starts with a dot\r\nok\r\n")
        check("سطرٌ يبدأ بنقطة يبقى (فكّ النقطة المضاعفة)", M.messages(d, "777@tv.ssouq.com")[0]["text"].startswith(".starts"))

        print("== الرفض: ليس صندوقًا مفتوحًا ولا ممرًّا ==")
        code, msg = _rcpt(port, "random123@tv.ssouq.com")
        check("عنوانٌ ليس لحسابٍ عندنا ← 550", code == 550 and b"no such user" in msg, str((code, msg)))
        code, msg = _rcpt(port, "victim@gmail.com")
        check("دومينٌ آخر ← 550 (لا تمرير)", code == 550 and b"relaying denied" in msg, str((code, msg)))
        check("ولا يُحفظ لهما شيء", not os.path.exists(M._path(d, "random123@tv.ssouq.com")) and not os.path.exists(M._path(d, "victim@gmail.com")))
        with smtplib.SMTP("127.0.0.1", port, timeout=10) as s:
            s.ehlo()
            check("RCPT قبل MAIL ← 503", s.rcpt("777@tv.ssouq.com")[0] == 503)
            s.mail("a@b.c")
            check("DATA قبل RCPT ← 503", s.docmd("DATA")[0] == 503)
            check("VRFY لا يكشف العناوين ← 252", s.verify("777@tv.ssouq.com")[0] == 252)
            check("أمرٌ غير معروف ← 502", s.docmd("STARTTLS")[0] == 502)
            check("NOOP و RSET", s.noop()[0] == 250 and s.rset()[0] == 250)
            check("رسالةٌ أكبر من المسموح (بإعلان SIZE) ← 552", s.mail("a@b.c", ["SIZE=%d" % (M.MAX_SIZE + 1)])[0] == 552)
            s.mail("a@b.c")
            s.rcpt("777@tv.ssouq.com")
            n = len(M.messages(d, "777@tv.ssouq.com"))
            big = "Subject: big\r\n\r\n" + ("y" * 990 + "\r\n") * (M.MAX_SIZE // 990 + 10)
            check("وبلا إعلان: تُقرأ وتُرفض ← 552 ولا تُحفظ", s.data(big)[0] == 552 and len(M.messages(d, "777@tv.ssouq.com")) == n)
            check("والجلسة تبقى صالحة بعدها", s.noop()[0] == 250)

        print("== الحدود ==")
        for i in range(M.KEEP + 5):
            _send(port, "777@tv.ssouq.com", f"Subject: n{i}\r\n\r\nbody {i}\r\n")
        g = M.messages(d, "777@tv.ssouq.com")
        check(f"آخر {M.KEEP} رسالة، الأحدث أولًا", len(g) == M.KEEP and g[0]["subject"] == f"n{M.KEEP + 4}", str([x["subject"] for x in g[:2]]))
        old = M._fresh([{"ts": time.time() - (M.TTL_DAYS + 1) * 86400}, {"ts": time.time()}])
        check(f"ما مضى عليه {M.TTL_DAYS} يومًا يُحذف", len(old) == 1)
        srv.slots = threading.BoundedSemaphore(1)
        hold = socket.create_connection(("127.0.0.1", port), timeout=5)
        hold.recv(200)
        c2 = socket.create_connection(("127.0.0.1", port), timeout=5)
        check("الاتصالات معًا محدودة ← 421", c2.recv(200).startswith(b"421"))
        c2.close()
        hold.close()
        time.sleep(0.2)
        srv.slots = threading.BoundedSemaphore(M.MAX_CONN)
        raw = socket.create_connection(("127.0.0.1", port), timeout=5)
        raw.recv(200)
        raw.sendall(b"HELO " + b"x" * 5000 + b"\r\n")
        raw.settimeout(5)
        try:
            check("سطرٌ أطول من المسموح يقطع الاتصال", raw.recv(200) == b"")
        except OSError:
            check("سطرٌ أطول من المسموح يقطع الاتصال", True)
        raw.close()
        with smtplib.SMTP("127.0.0.1", port, timeout=10) as s:
            check("وبعدها يستقبل كالعادة", s.ehlo()[0] == 250)
        check("رسالةٌ لمستلمَين تُحفظ لكلٍّ منهما", _multi(port, d))
    finally:
        srv.shutdown()
        srv.server_close()
        shutil.rmtree(d, ignore_errors=True)
    print("\n----------------------------------------")
    print("Result: \033[32m%d passed\033[0m, %s" % (_p, ("\033[31m%d failed\033[0m" % _f) if _f else "0 failed"))
    sys.exit(1 if _f else 0)


def _send(port, to, body):
    with smtplib.SMTP("127.0.0.1", port, timeout=10) as s:
        s.ehlo()
        s.mail("sender@example.com")
        code, msg = s.rcpt(to)
        if code != 250:
            return code, msg
        return s.data(body.encode() if isinstance(body, str) else body)


def _rcpt(port, to):
    with smtplib.SMTP("127.0.0.1", port, timeout=10) as s:
        s.ehlo()
        s.mail("sender@example.com")
        return s.rcpt(to)


def _multi(port, d):
    with smtplib.SMTP("127.0.0.1", port, timeout=10) as s:
        s.sendmail("x@example.com", ["777@tv.ssouq.com", "0504998661ali@tv.ssouq.com"], "Subject: both\r\n\r\nhi\r\n")
    return all(M.messages(d, a)[0]["subject"] == "both" for a in ("777@tv.ssouq.com", "0504998661ali@tv.ssouq.com"))


if __name__ == "__main__":
    main()

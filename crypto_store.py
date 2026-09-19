#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
تشفير وحماية للبيانات الحسّاسة المخزَّنة (كلمات مرور اللوحات، مفاتيح API).

بلا أي مكتبات خارجية — بناء encrypt-then-MAC حقيقي فوق HMAC-SHA256 في وضع
العدّاد (CTR): سرّية + سلامة، ما دام المفتاح سرّيًا.

المفتاح الرئيسي:
  1) من متغيّر البيئة XM_SECRET_KEY (المفضّل — يُضبط في Coolify)، أو
  2) ملف مفتاح 0600 في data/.secret_key (يُولَّد مرة ويبقى مع الـ Volume).

القيم المشفَّرة تُوسم بالبادئة "enc:1:" فلا تُشفَّر مرتين، والقيم القديمة
(نص صريح) تُقرأ كما هي وتُشفَّر عند أول حفظ.
"""
import os
import hmac
import base64
import hashlib
import secrets

_MARK = "enc:1:"
_key_cache = {}


def _master_key(data_dir: str) -> bytes:
    env = os.environ.get("XM_SECRET_KEY", "").strip()
    if env:
        return hashlib.sha256(("env:" + env).encode()).digest()
    if data_dir in _key_cache:
        return _key_cache[data_dir]
    path = os.path.join(data_dir, ".secret_key")
    raw = b""
    try:
        with open(path, "rb") as f:
            raw = f.read().strip()
    except OSError:
        raw = b""
    if not raw:
        raw = base64.b64encode(secrets.token_bytes(32))
        try:
            os.makedirs(data_dir, exist_ok=True)
            with open(path, "wb") as f:
                f.write(raw)
            os.chmod(path, 0o600)
        except OSError:
            pass
    key = hashlib.sha256(b"file:" + raw).digest()
    _key_cache[data_dir] = key
    return key


def _subkeys(mk: bytes):
    return hashlib.sha256(b"enc" + mk).digest(), hashlib.sha256(b"mac" + mk).digest()


def _keystream(key: bytes, nonce: bytes, n: int) -> bytes:
    out = bytearray()
    ctr = 0
    while len(out) < n:
        out += hmac.new(key, nonce + ctr.to_bytes(8, "big"), hashlib.sha256).digest()
        ctr += 1
    return bytes(out[:n])


def encrypt(value, data_dir: str):
    """يشفّر نصًّا؛ يمرّر الفارغ/غير النص كما هو، ولا يشفّر المشفَّر مرتين."""
    if not isinstance(value, str) or value == "" or value.startswith(_MARK):
        return value
    mk = _master_key(data_dir)
    enc_key, mac_key = _subkeys(mk)
    nonce = secrets.token_bytes(16)
    pt = value.encode("utf-8")
    ks = _keystream(enc_key, nonce, len(pt))
    ct = bytes(a ^ b for a, b in zip(pt, ks))
    tag = hmac.new(mac_key, nonce + ct, hashlib.sha256).digest()
    return _MARK + base64.b64encode(nonce + ct + tag).decode("ascii")


def decrypt(value, data_dir: str):
    """يفكّ التشفير؛ يمرّر النص الصريح/غير المشفَّر كما هو. عند العبث/خطأ المفتاح
    يرجّع "" (لا يكسر الحساب)."""
    if not isinstance(value, str) or not value.startswith(_MARK):
        return value
    try:
        raw = base64.b64decode(value[len(_MARK):])
        nonce, ct, tag = raw[:16], raw[16:-32], raw[-32:]
        mk = _master_key(data_dir)
        enc_key, mac_key = _subkeys(mk)
        if not hmac.compare_digest(tag, hmac.new(mac_key, nonce + ct, hashlib.sha256).digest()):
            return ""
        ks = _keystream(enc_key, nonce, len(ct))
        return bytes(a ^ b for a, b in zip(ct, ks)).decode("utf-8", "replace")
    except Exception:
        return ""


def is_encrypted(value) -> bool:
    return isinstance(value, str) and value.startswith(_MARK)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ربط اليوزر القديم بالجديد عند الاستبدال — لتتبّع «هذا الرقم استُبدل بأيّ رقم؟»
و«هذا الرقم بديلٌ عن أيّ رقم؟». تخزينٌ بسيط لكل (حساب، بوابة) في jsonl.

بلا اعتمادات خارجية. لا يُسجَّل أي سرّ (اليوزرات أرقامٌ علنية على اللوحة)."""

import json
import os
import re
import time


def _key(acct_id, gate_id):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", "%s__%s" % (acct_id or "x", gate_id or "x"))[:120]


def path(data_dir, acct_id, gate_id):
    d = os.path.join(data_dir, "user_links")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, _key(acct_id, gate_id) + ".jsonl")


def load(p):
    out = []
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    if isinstance(d, dict) and d.get("old") and d.get("new"):
                        out.append(d)
                except ValueError:
                    continue
    except FileNotFoundError:
        pass
    return out


def add(data_dir, acct_id, gate_id, old, new, package=""):
    """يسجّل استبدالًا: القديم → الجديد. يتجاهل الفارغ أو المطابق."""
    old, new = str(old or "").strip(), str(new or "").strip()
    if not old or not new or old == new:
        return None
    rec = {"old": old, "new": new, "package": str(package or ""),
           "at": time.strftime("%Y-%m-%d %H:%M")}
    p = path(data_dir, acct_id, gate_id)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def find(data_dir, acct_id, gate_id, query, limit=20):
    """كل الروابط التي يظهر فيها `query` قديمًا أو جديدًا — الأحدث أولًا. لكلٍّ
    اتجاهٌ: replaced_by (query هو القديم) أو replacement_of (query هو الجديد)."""
    q = str(query or "").strip()
    if not q:
        return []
    out = []
    for r in load(path(data_dir, acct_id, gate_id)):
        if r["old"] == q:
            out.append({**r, "direction": "replaced_by"})
        elif r["new"] == q:
            out.append({**r, "direction": "replacement_of"})
    out.reverse()                      # الأحدث أولًا
    return out[:limit]

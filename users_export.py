#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تصدير يوزرات البوابة إلى ملف Excel محفوظٍ على السيرفر.

لكل (حساب، بوابة) ملفٌّ ثابت: `users_export/<مفتاح>.xlsx` يُعاد بناؤه من لقطةٍ
مخزَّنة `‎.jsonl`. عمليتان:
  • السحب الكامل (replace_all): يجلب كل اليوزرات من اللوحة ويكتب الملف كاملًا.
  • الإضافة عند الإنشاء (merge): يضيف اليوزرات المُنشأة حديثًا للقطة ويعيد بناء الملف.
الدمج بالاسم: يحدّث الموجود بمكانه، ويضيف الجديد في آخره — فلا تكرار ولا فقدان.

بلا اعتمادات خارجية: يعتمد xlsx_write (كاتب xlsx بالمكتبة القياسية)."""

import json
import os
import re
import time

import xlsx_write

# أعمدة الملف (المفتاح ↔ الرأس العربي)، بالترتيب.
KEYS = ["username", "password", "package", "exp", "created", "connections", "host"]
HEADERS = ["اليوزر", "كلمة المرور", "الباقة", "تاريخ الانتهاء",
           "تاريخ الإنشاء", "الاتصالات", "الهوست"]


def _key(acct_id, gate_id):
    raw = "%s__%s" % (acct_id or "x", gate_id or "x")
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", raw)[:120]


def _dir(data_dir):
    d = os.path.join(data_dir, "users_export")
    os.makedirs(d, exist_ok=True)
    return d


def paths(data_dir, acct_id, gate_id):
    """(مسار jsonl، مسار xlsx) لهذه البوابة."""
    base = os.path.join(_dir(data_dir), _key(acct_id, gate_id))
    return base + ".jsonl", base + ".xlsx"


def _norm(row, host=""):
    """صفٌّ واردٌ (قاموس اللوحة أو نتيجة الإنشاء) → قاموسٌ بمفاتيح ثابتة."""
    g = lambda *ks: next((str(row.get(k)) for k in ks if row.get(k) not in (None, "")), "")
    return {
        "username": g("username", "user"),
        "password": g("password", "pass"),
        "package": g("package", "package_name", "name"),
        "exp": g("exp", "exp_date", "expire"),
        "created": g("created", "created_at") or "",
        "connections": g("connections", "max_connections", "conns"),
        "host": g("host") or str(host or ""),
    }


def load(jsonl_path):
    """لقطةٌ مخزَّنة → قائمة قواميس (بلا انهيار إن كان الملف مفقودًا/تالفًا)."""
    out = []
    try:
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    if isinstance(d, dict) and d.get("username"):
                        out.append(d)
                except ValueError:
                    continue
    except FileNotFoundError:
        pass
    return out


def _save(data_dir, acct_id, gate_id, gate_name, rows):
    jsonl_path, xlsx_path = paths(data_dir, acct_id, gate_id)
    tmp = jsonl_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, jsonl_path)
    grid = [[r.get(k, "") for k in KEYS] for r in rows]
    data = xlsx_write.build_xlsx([(str(gate_name or "Users")[:31] or "Users", HEADERS, grid)])
    tmpx = xlsx_path + ".tmp"
    with open(tmpx, "wb") as f:
        f.write(data)
    os.replace(tmpx, xlsx_path)
    return len(rows)


def replace_all(data_dir, acct_id, gate_id, gate_name, rows, host=""):
    """سحبٌ كامل: يكتب الملف من الصفر (إزالة التكرار بالاسم، مع حفظ الترتيب)."""
    seen, uniq = set(), []
    for r in rows:
        n = _norm(r, host)
        u = n["username"]
        if not u or u in seen:
            continue
        seen.add(u)
        uniq.append(n)
    return _save(data_dir, acct_id, gate_id, gate_name, uniq)


def merge(data_dir, acct_id, gate_id, gate_name, new_rows, host=""):
    """إضافةُ يوزراتٍ للقطة: تحديثُ الموجود بمكانه وإضافةُ الجديد في آخره."""
    rows = load(paths(data_dir, acct_id, gate_id)[0])
    idx = {r.get("username"): i for i, r in enumerate(rows)}
    for r in new_rows:
        n = _norm(r, host)
        u = n["username"]
        if not u:
            continue
        if u in idx:
            cur = rows[idx[u]]
            for k, v in n.items():                 # لا تدهس قيمةً موجودةً بفراغ
                if v:
                    cur[k] = v
        else:
            idx[u] = len(rows)
            rows.append(n)
    return _save(data_dir, acct_id, gate_id, gate_name, rows)


def status(data_dir, acct_id, gate_id):
    """{exists, count, updated_at} — لعرض حالة الملف في الواجهة."""
    jsonl_path, xlsx_path = paths(data_dir, acct_id, gate_id)
    if not os.path.exists(xlsx_path):
        return {"exists": False, "count": 0, "updated_at": ""}
    n = len(load(jsonl_path))
    ts = os.path.getmtime(xlsx_path)
    return {"exists": True, "count": n,
            "updated_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))}

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""مسابقة التوقّعات (contest.py): التسجيل والإقفال والفرز الآلي والعلن، بلا إنترنت.

  - الجوال والاسم والإخفاء، وحالات المسابقة من حال المباراة في ESPN.
  - توقّعٌ واحد لكل رقم، والرفض بعد البداية، والحقل المخفي، وحدّ العنوان.
  - الفرز: ثابتٌ في مدخلاته، بالمعادلة المنشورة نفسها، وبالنتيجة بالضبط ثم الفائز،
    وأكثر من فائز، ولا فائز؛ ولا فرز قبل النهاية، والملغاة بلا فرز، والإعادة بلا أثر.
  - العلن لا يكشف رقمًا ولا توقّعًا قبل الإقفال، وبعد الفرز أسماءٌ أولى وأرقامٌ مخفيّة.
  - الرسائل، والإدارة (فتح وإيقاف وحدودهما)، وملف Excel.
  - على خادم حيّ مع ESPN وهمية: البطاقة والشريط والشارة وصفحة المسابقة والواجهات
    وصلاحياتها، والفرز الآلي لمباراةٍ انتهت.

تشغيل:  python tests/test_contest.py
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
import io

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import contest as C  # noqa: E402
import mock_espn  # noqa: E402
import tournament as T  # noqa: E402

_p = _f = 0


def check(l, c, x=""):
    global _p, _f
    print((f"  \033[32mPASS\033[0m  {l}" if c else f"  \033[31mFAIL\033[0m  {l}") + (f"  ({x})" if x else ""))
    _p += 1 if c else 0
    _f += 0 if c else 1


NOW = 1_800_000_000.0


def match(eid="7", state="pre", status="STATUS_SCHEDULED", ts=NOW + 3600, h=0, a=0, time_ok=True):
    return {"id": eid, "slug": f"{eid}-belgium-france", "ts": ts, "stage": "المجموعة الأولى", "time_ok": time_ok,
            "state": state, "status": status, "clock": "",
            "home": {"id": "459", "name": "بلجيكا", "logo": "", "score": h, "so": None, "win": h > a},
            "away": {"id": "478", "name": "فرنسا", "logo": "", "score": a, "so": None, "win": a > h}}


def form(**kw):
    d = {"m": "7", "name": "عبدالله محمد", "phone": "0551234567", "h": 2, "a": 1, "agree": True}
    d.update(kw)
    return d


def fresh():
    d = tempfile.mkdtemp(prefix="contest_")
    C._hits.clear()
    return d


def seed(data_dir, m, entries, prize="اشتراك شهر", winners=1):
    """مسابقةٌ مفتوحة بتوقّعاتٍ جاهزة: [(الاسم، الجوال، له، عليه)]."""
    code, res = C.configure(data_dir, m, True, prize, winners, now=m["ts"] - 7200)
    assert code == 200, res
    rec = C.load(data_dir, m["id"])
    for i, (name, phone, h, a) in enumerate(entries, 1):
        rec["entries"].append({"n": i, "name": name, "phone": phone, "h": h, "a": a, "at": m["ts"] - 3600 + i,
                               "ipk": "", "promo": i % 2 == 0})
    with C._lock:
        C._save(data_dir, rec)
    return rec


def unit():
    print("الجوال والاسم والإخفاء")
    check("05x ← 9665x", C.norm_phone("055 123 4567") == "966551234567")
    check("+966 و00966 و5x بلا صفر", C.norm_phone("+966551234567") == C.norm_phone("00966551234567")
          == C.norm_phone("551234567") == "966551234567")
    check("أرقامٌ عربية", C.norm_phone("٠٥٥١٢٣٤٥٦٧") == "966551234567")
    check("رقمٌ سعوديٌّ صحيح فقط", C.phone_ok("966551234567") and not C.phone_ok("96655123456")
          and not C.phone_ok("966112345678"))
    check("دوليٌّ بمفتاحه (الكويت)", C.phone_ok(C.norm_phone("+965 5123 4567")))
    check("قصيرٌ مرفوض", not C.phone_ok(C.norm_phone("12345")))
    check("الاسم بلا وسوم ولا مسافات زائدة", C.clean_name("  <b>سارة</b>\n  أحمد ") == "bسارة/b أحمد")
    check("الاسم الأول للعلن", C.short_name("عبدالله محمد العتيبي") == "عبدالله"
          and C.short_name("أبو فهد القحطاني") == "أبو فهد")
    check("الرقم مخفيًّا", C.mask_phone("966551234567") == "05•••••567"
          and C.mask_phone("96551234567") == "+965•••••567")

    print("الحالة")
    s = {"on": True, "draw": False, "void": False}
    check("مفتوحة قبل البداية", C.state_of(s, match(), NOW) == "open")
    check("مقفلة لحظة البداية", C.state_of(s, match(ts=NOW), NOW) == "closed")
    check("مقفلة والمباراة جارية", C.state_of(s, match(state="in", status="STATUS_FIRST_HALF", ts=NOW - 600), NOW) == "closed")
    check("تنتظر الفرز بعد النهاية", C.state_of(s, match(state="post", status="STATUS_FULL_TIME", ts=NOW - 7200), NOW) == "pending")
    check("موقوفة: مؤجلة", C.state_of(s, match(status="STATUS_POSTPONED"), NOW) == "hold")
    check("موقوفة: الساعة لم تُعتمد", C.state_of(s, match(time_ok=False), NOW) == "hold")
    check("ملغاة", C.state_of(s, match(status="STATUS_CANCELED"), NOW) == "void")
    check("مطفأة", C.state_of({"on": False}, match(), NOW) == "off" and C.state_of(None, match(), NOW) == "off")

    print("التوقّع")
    d = fresh()
    m = match()
    code, res = C.enter(d, m, form(), "1.1.1.1", NOW)
    check("لا مسابقة قبل أن يفتحها المدير", code == 409 and res.get("state") == "off", res)
    C.configure(d, m, True, "اشتراك 3 أشهر", 1, now=NOW)
    code, res = C.enter(d, m, form(), "1.1.1.1", NOW)
    check("توقّعٌ مقبول برقمه", code == 200 and res["n"] == 1 and (res["h"], res["a"]) == (2, 1), res)
    code, res = C.enter(d, m, form(phone="+966551234567", h=0, a=0), "2.2.2.2", NOW)
    check("الرقم نفسه بصيغةٍ أخرى مرفوض، ولا يُعدَّل التوقّع", code == 409 and res.get("dup")
          and C.load(d, "7")["entries"][0]["h"] == 2, res)
    check("الاسم لازم", C.enter(d, m, form(name=" 1 ", phone="0551111111"), "3.3.3.3", NOW)[1].get("field") == "name")
    check("الرقم لازم", C.enter(d, m, form(phone="0512"), "3.3.3.3", NOW)[1].get("field") == "phone")
    check("النتيجة لازمة وفي حدّها", C.enter(d, m, form(phone="0551111111", h=40), "3.3.3.3", NOW)[1].get("field") == "score"
          and C.enter(d, m, form(phone="0551111111", h="x"), "3.3.3.3", NOW)[1].get("field") == "score")
    check("الموافقة على الشروط لازمة", C.enter(d, m, form(phone="0551111111", agree=False), "3.3.3.3", NOW)[1].get("field") == "agree")
    code, res = C.enter(d, m, form(phone="0552222222", website="http://spam"), "4.4.4.4", NOW)
    check("الحقل المخفي: ردٌّ كاذب ولا حفظ", code == 200 and res["n"] == 0 and len(C.load(d, "7")["entries"]) == 1)
    code, res = C.enter(d, m, form(phone="0553333333"), "5.5.5.5", m["ts"])
    check("لحظة البداية مرفوض", code == 409 and res["state"] == "closed", res)
    code, res = C.enter(d, match(eid="8"), form(phone="0553333333"), "5.5.5.5", NOW)
    check("مباراةٌ غير التي في الطلب", code == 404)
    for i in range(C.IP_PER_MATCH - 1):
        C.enter(d, m, form(phone=f"05500000{i:02d}"), "1.1.1.1", NOW)
    code, res = C.enter(d, m, form(phone="0559999999"), "1.1.1.1", NOW)
    check(f"حدّ العنوان في المباراة ({C.IP_PER_MATCH})", code == 429, res)
    old = C.IP_PER_HOUR
    C.IP_PER_HOUR = 3
    try:
        C._hits.clear()
        got = [C.enter(d, m, form(phone=f"05600000{i:02d}"), "9.9.9.9", NOW)[0] for i in range(4)]
    finally:
        C.IP_PER_HOUR = old
    check("حدّ العنوان في الساعة", got == [200, 200, 200, 429], got)
    rec = C.load(d, "7")
    check("لا يُحفظ العنوان نفسه", all(not re.search(r"\d+\.\d+\.\d+\.\d+", json.dumps(e)) for e in rec["entries"]))
    check("لقطة المباراة مع المسابقة", rec["match"]["home"] == "بلجيكا" and rec["match"]["slug"] == "7-belgium-france")
    shutil.rmtree(d)

    print("البصمة")
    es = [{"n": 1, "h": 1, "a": 0, "phone": "966551"}, {"n": 2, "h": 2, "a": 2, "phone": "966552"}]
    check("ثابتة وبترتيب التسجيل لا بترتيب القائمة", C.fingerprint(es) == C.fingerprint(list(reversed(es))))
    check("تتغيّر بتغيّر توقّع", C.fingerprint(es) != C.fingerprint([es[0], dict(es[1], h=3)]))
    check("لا تحمل الأرقام نفسها", "966551" not in C.fingerprint(es))

    print("الفرز")
    d = fresh()
    m = match()
    people = [("سارة", "966550000001", 2, 1), ("فهد", "966550000002", 1, 0), ("نورة", "966550000003", 2, 1),
              ("خالد", "966550000004", 0, 0), ("ريم", "966550000005", 2, 1), ("تركي", "966550000006", 3, 0)]
    rec = seed(d, m, people)
    end = dict(m, state="post", status="STATUS_FULL_TIME", home=dict(m["home"], score=2), away=dict(m["away"], score=1))
    dr = C.draw(rec, end, NOW)
    fp = C.fingerprint(rec["entries"])
    sd = hashlib.sha256(f"{fp}|7|2-1".encode()).hexdigest()
    num = int(hashlib.sha256(f"{sd}:0".encode()).hexdigest()[:12], 16)
    pool = [1, 3, 5]
    p = dr["picks"][0]
    check("رقم القرعة بالمعادلة المنشورة", dr["seed"] == sd and dr["fp"] == fp)
    check("الفائز = المؤهّل (رقم الفائز mod عددهم)", p["num"] == num and p["idx"] == num % 3 and p["n"] == pool[num % 3], p)
    check("من أصاب النتيجة بالضبط وحدهم", p["tier"] == "exact" and dr["exact"] == 3 and p["pool"] == pool)
    check("من أصاب الفائز يُعدّون", dr["outcome"] == 2)
    check("ثابتٌ: الفرز نفسه مرتين", C.draw(rec, end, NOW + 99)["picks"] == dr["picks"])
    other = dict(end, home=dict(end["home"], score=3), away=dict(end["away"], score=0))
    check("النتيجة جزءٌ من القرعة", C.draw(rec, other, NOW)["seed"] != dr["seed"])
    rec2 = dict(rec, winners=2)
    two = C.draw(rec2, end, NOW)["picks"]
    check("فائزان: الثاني من الباقين وبرقمٍ آخر", len(two) == 2 and two[0]["n"] != two[1]["n"]
          and two[1]["num"] == int(hashlib.sha256(f"{sd}:1".encode()).hexdigest()[:12], 16)
          and two[1]["size"] == 2)
    fb = dict(end, home=dict(end["home"], score=4), away=dict(end["away"], score=1))
    dfb = C.draw(rec, fb, NOW)
    check("لا أحد بالضبط ← من أصاب الفائز", dfb["exact"] == 0 and dfb["picks"][0]["tier"] == "outcome"
          and dfb["picks"][0]["size"] == 5, dfb["picks"])
    rec5 = dict(rec, winners=5)
    five = C.draw(rec5, end, NOW)["picks"]
    check("أكثر من المصيبين بالضبط: تكملهم فئة الفائز", [x["tier"] for x in five] == ["exact"] * 3 + ["outcome"] * 2)
    nob = dict(end, home=dict(end["home"], score=0), away=dict(end["away"], score=2))
    check("لم يُصب أحدٌ شيئًا ← لا فائز", C.draw(rec, nob, NOW)["picks"] == [])

    print("الفرز الآلي (settle)")
    live = dict(end, state="in", status="STATUS_SECOND_HALF")
    check("لا فرز والمباراة جارية", C.settle(d, "7", live, NOW + 7200) == (C.load(d, "7"), False))
    check("لا فرز قبل مرور الحدّ من البداية", C.settle(d, "7", end, m["ts"] + C.SETTLE_AFTER - 1)[1] is False)
    rec, did = C.settle(d, "7", end, m["ts"] + C.SETTLE_AFTER)
    check("يُفرز بعد النهاية ويُحفظ", did and C.load(d, "7")["draw"]["picks"] == dr["picks"])
    rec, did = C.settle(d, "7", other, m["ts"] + C.SETTLE_AFTER + 60)
    check("الإعادة لا تغيّر شيئًا", not did and rec["draw"]["seed"] == sd)
    check("خرجت من قائمة الانتظار", "7" not in C.waiting(d) and C.summaries(d)["7"]["draw"])
    check("لا توقّع بعد الفرز", C.enter(d, m, form(phone="0557777777"), "7.7.7.7", NOW)[1].get("state") == "done")
    check("لا تعديل بعد الفرز", C.configure(d, m, True, "x", 1, now=NOW)[0] == 409)
    seed(d, match(eid="9"), people[:2])
    rec, did = C.settle(d, "9", match(eid="9", status="STATUS_CANCELED"), NOW)
    check("المباراة الملغاة: بلا فرز", not did and rec["void"] and C.state_of(rec, match(eid="9"), NOW) == "void")

    print("العلن")
    pub = C.public(C.load(d, "7"), end, NOW)
    blob = json.dumps(pub, ensure_ascii=False)
    check("لا رقمٌ كامل في العلن", not any(x[1] in blob for x in people), blob[:120])
    check("الفائز باسمه الأول ورقمه مخفيًّا", pub["draw"]["picks"][0]["phone"].startswith("05•••••")
          and pub["draw"]["picks"][0]["name"] in {"سارة", "نورة", "ريم"})
    w = pub["draw"]["picks"][0]
    check("الفائز في قائمة المؤهّلين المنشورة بموضعه", pub["draw"]["pool"][w["idx"] - pub["draw"]["pool_from"]]["n"] == w["n"])
    check("البصمة وتوزيع التوقّعات بعد الإقفال", pub["fp"] == fp and pub["dist"]["n"] == 6 and pub["dist"]["home"] == 5)
    d2 = fresh()
    seed(d2, m, people)
    pre = C.public(C.load(d2, "7"), m, NOW)
    check("قبل الإقفال: العدد فقط", pre["state"] == "open" and pre["count"] == 6 and "fp" not in pre and "dist" not in pre
          and "entries" not in pre)
    check("المطفأة لا تقول شيئًا", C.public({"on": False}, m, NOW) == {"ok": True, "state": "off"})

    print("الرسائل")
    rec = C.load(d, "7")
    msgs = C.messages(rec, {"notify": True, "text": C.DEFAULT_TEXT, "admin_phone": "966500000000"}, "https://x/y#predict")
    win = [x for x in msgs if x["kind"] == "winner"]
    check("للفائز على رقمه", len(win) == 1 and win[0]["to"] == dict((i + 1, p[1]) for i, p in enumerate(people))[w["n"]])
    check("القالب ممتلئ", "{" not in win[0]["text"] and "بلجيكا 2 – 1 فرنسا" in win[0]["text"] and "https://x/y#predict" in win[0]["text"])
    check("ملخّصٌ للمدير", [x["to"] for x in msgs if x["kind"] == "admin"] == ["966500000000"])
    check("قوسٌ في القالب لا يكسره", "{غريب}" in C.messages(rec, {"notify": True, "text": "{غريب} {name}"}, "")[0]["text"])
    check("التبليغ مطفأ: المدير وحده", [x["kind"] for x in C.messages(rec, {"notify": False, "admin_phone": "966500000000"}, "")] == ["admin"])
    C.mark_sent(d, "7", [{"to": "1", "ok": True}])
    check("نتيجة الإرسال تُحفظ", C.load(d, "7")["sent"][0]["ok"] is True)

    print("الإدارة")
    d3 = fresh()
    check("الجائزة لازمة", C.configure(d3, m, True, " ", 1, now=NOW)[0] == 400)
    check("لا تُفتح بعد البداية", C.configure(d3, match(state="in", status="STATUS_FIRST_HALF", ts=NOW - 60), True, "x", 1, now=NOW)[0] == 409)
    check("تُفتح والموعد لم يُعتمد", C.configure(d3, match(eid="11", time_ok=False), True, "x", 1, now=NOW)[0] == 200)
    seed(d3, m, people)
    check("عدد الفائزين لا يتغيّر بعد الإقفال", C.configure(d3, m, True, "x", 3, now=m["ts"] + 1)[0] == 409
          and C.configure(d3, m, True, "جائزة أخرى", 1, now=m["ts"] + 1)[0] == 200)
    check("الإيقاف يُبقي التوقّعات", C.configure(d3, m, False, "", 1, now=NOW)[0] == 200
          and len(C.load(d3, "7")["entries"]) == 6 and "7" not in C.waiting(d3))
    C.save_settings(d3, {"notify": False, "text": "", "admin_phone": "0550000000"})
    st = C.load_settings(d3)
    check("الإعداد: نصٌّ فارغ يعود للافتراضي والرقم يُوحَّد", st["text"] == C.DEFAULT_TEXT and st["admin_phone"] == "966550000000"
          and st["notify"] is False)
    try:
        C.save_settings(d3, {"admin_phone": "123"})
        bad = False
    except ValueError:
        bad = True
    check("رقم مديرٍ خاطئ مرفوض", bad)
    rows = C.admin_rows(d3, [match(eid="12", ts=NOW + 86400), m, match(eid="13", ts=NOW + 60 * 86400)], NOW)
    ids = [r["eid"] for r in rows]
    check("صفحة المدير: القادمة وما عليها مسابقة، لا البعيدة", "12" in ids and "7" in ids and "13" not in ids and "11" in ids, ids)
    sheets = C.export_sheets(d3)
    check("Excel: ورقةٌ لكل مسابقة بترتيبها، وأرقامٌ كاملة", len(sheets) == 2 and sheets[0][2][0][2] == "966550000001"
          and sheets[0][1][0] == "رقم التوقّع" and sheets[1][2] == [], [s[0] for s in sheets])
    lst = C.listing(C.summaries(d), [end])
    check("صفحة المسابقة: المفروزة بفائزها", lst and lst[0]["state"] == "done" and lst[0]["won"] and lst[0]["score"] == [2, 1])
    for x in (d, d2, d3):
        shutil.rmtree(x)


# ---------- خادمٌ حيّ ----------
def get(url, auth=False):
    req = urllib.request.Request(url)
    if auth:
        import base64
        req.add_header("Authorization", "Basic " + base64.b64encode(b"admin:envpass123").decode())
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def post(url, body, auth=False):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    if auth:
        import base64
        req.add_header("Authorization", "Basic " + base64.b64encode(b"admin:envpass123").decode())
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def live():
    print("خادمٌ حيّ")
    mport, port = 9781, 9782
    data = tempfile.mkdtemp(prefix="contest_live_")
    # مسابقةٌ على مباراةٍ انتهت (1: فرنسا 2-1 بلجيكا) بتوقّعاتٍ سُجّلت قبلها — ليفرزها الخادم
    ms = T.matches(mock_espn.scoreboard("uefa.nations", "2026")["events"])
    m1 = next(x for x in ms if x["id"] == "1")
    rec = C._blank("1")
    rec.update(on=True, prize="اشتراك 3 أشهر", winners=1, match=C._snap(m1))
    for i in range(1, 41):
        rec["entries"].append({"n": i, "name": f"مشارك {i}", "phone": f"9665500{i:05d}", "h": i % 4, "a": i % 3,
                               "at": m1["ts"] - 5000 + i, "ipk": "", "promo": False})
    os.makedirs(os.path.join(data, "contest"))
    with open(os.path.join(data, "contest", "1.json"), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False)
    procs = [subprocess.Popen([sys.executable, os.path.join(HERE, "mock_espn.py"), str(mport)])]
    try:
        env = dict(os.environ, XM_DATA=data, XM_BIND="127.0.0.1", XM_PORT=str(port), XM_ADMIN_PASSWORD="envpass123",
                   LEAGUE_API=f"http://127.0.0.1:{mport}")
        procs.append(subprocess.Popen([sys.executable, os.path.join(ROOT, "xm_lines.py"), "web"], env=env))
        base = f"http://127.0.0.1:{port}"
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/robots.txt", timeout=2)
                break
            except Exception:
                time.sleep(.2)

        code, body, _ = get(base + "/admin/api/contest/admin")
        check("واجهة المدير تطلب الدخول", code == 401)
        code, res = post(base + "/admin/api/contest/admin/set", {"m": "6", "on": True, "prize": "اشتراك 3 أشهر"})
        check("والكتابة كذلك", code == 401)
        code, res = post(base + "/admin/api/contest/admin/set", {"m": "6", "on": True, "prize": "اشتراك 3 أشهر"}, auth=True)
        check("المدير يفتح المسابقة على مباراةٍ قادمة", code == 200 and res["contest"]["on"], res)
        code, res = post(base + "/admin/api/contest/admin/set", {"m": "999", "on": True, "prize": "x"}, auth=True)
        check("مباراةٌ ليست في البطولة", code == 404)
        code, res = post(base + "/admin/api/contest/admin/set", {"m": "7", "on": True, "prize": "x"}, auth=True)
        code2, body, _ = get(base + "/api/contest?m=7")
        check("المؤجلة تُفتح موقوفة", code == 200 and json.loads(body)["state"] == "hold")

        code, body, hd = get(base + "/api/contest?m=6")
        d = json.loads(body)
        check("الحال مفتوحة بلا كاش وبموعدٍ مقروء", code == 200 and d["state"] == "open" and d["count"] == 0
              and "no-store" in hd.get("Cache-Control", "") and d["when"].endswith(("ص", "م")), d)
        code, res = post(base + "/api/contest/enter", {"m": "6", "name": "سارة", "phone": "0551230000", "h": 1, "a": 0,
                                                       "agree": True, "promo": True})
        check("توقّعٌ من الموقع", code == 200 and res["n"] == 1, res)
        code, res = post(base + "/api/contest/enter", {"m": "6", "name": "سارة", "phone": "551230000", "h": 3, "a": 0,
                                                       "agree": True})
        check("والرقم نفسه مرفوض", code == 409 and res.get("dup"))
        code, res = post(base + "/api/contest/enter", {"m": "3", "name": "سارة", "phone": "0551230001", "h": 3, "a": 0,
                                                       "agree": True})
        check("مباراةٌ بلا مسابقة", code == 409 and res.get("state") == "off")
        code, body, _ = get(base + "/api/contest?m=6")
        check("العلن: العدد ولا رقم", json.loads(body)["count"] == 1 and b"551230000" not in body)

        code, body, _ = get(base + "/nations-league/6-netherlands-serbia")
        page = body.decode()
        check("بطاقة المسابقة في صفحة المباراة", 'id="predict" data-m="6"' in page and "/static/contest.js?v=" in page
              and "توقّع النتيجة واربح اشتراك 3 أشهر" in page)
        check("ورابط الشروط", 'href="/nations-league/predict#rules"' in page)
        code, body, _ = get(base + "/nations-league/3-england-spain")
        check("ولا بطاقة لمباراةٍ بلا مسابقة", 'id="predict"' not in body.decode())
        code, body, _ = get(base + "/nations-league")
        page = body.decode()
        check("شريط المسابقة في صفحة البطولة", '<a class="pbanner" href="/nations-league/6-netherlands-serbia#predict"' in page)
        check("وشارةٌ على صفّ المباراة وحده", page.count('<small class="pz">') == 1)
        code, body, _ = get(base + "/nations-league/widget?theme=dark")
        page = body.decode()
        check("والشريط في ودجت المتجر يُفتح في نافذة", re.search(r'<a class="pbanner" href="[^"]+#predict" target="_blank"', page))
        code, body, _ = get(base + "/nations-league/predict")
        page = body.decode()
        check("صفحة المسابقة: المفتوحة والشروط", code == 200 and "مفتوحة للتوقّع" in page and 'id="rules"' in page
              and C.RULES[0] in page)
        code, body, _ = get(base + "/sitemap.xml")
        check("صفحة المسابقة في خريطة الموقع", b"/nations-league/predict</loc>" in body)

        code, body, _ = get(base + "/api/contest?m=1")
        d = json.loads(body)
        local = C.draw(rec, m1)
        check("المباراة المنتهية تُفرز آليًّا", d["state"] == "done" and d["draw"]["seed"] == local["seed"], d.get("state"))
        check("والفائز كما يحسبه أيّ أحد", d["draw"]["picks"][0]["n"] == local["picks"][0]["n"]
              and d["draw"]["picks"][0]["phone"].startswith("05•••••"))
        for _ in range(20):                              # التبليغ في خيطٍ بعد الفرز
            code, body, _ = get(base + "/admin/api/contest/admin/match?m=1", auth=True)
            det = json.loads(body)
            if det.get("sent"):
                break
            time.sleep(.1)
        check("المدير يرى الرقم كاملًا ونتيجة الإرسال", det["won"][0]["phone"].startswith("9665500")
              and det["sent"] and det["sent"][0]["dry"], det.get("sent"))
        code, res = post(base + "/admin/api/contest/admin/settle", {"m": "1"}, auth=True)
        check("«افرز الآن» بعد الفرز لا يغيّر شيئًا", code == 200 and res["drawn"] is False)
        code, res = post(base + "/admin/api/contest/admin/settle", {"m": "6"}, auth=True)
        check("ولا فرز قبل النهاية", code == 409)
        code, body, hd = get(base + "/admin/api/contest/admin/export.xlsx", auth=True)
        z = zipfile.ZipFile(io.BytesIO(body))
        xml = "".join(z.read(n).decode() for n in z.namelist() if n.startswith("xl/worksheets/"))
        check("Excel كل التوقّعات بالأرقام", code == 200 and "966551230000" in xml and "966550000001" in xml)
        code, body, _ = get(base + "/admin/api/contest/admin", auth=True)
        rows = {r["eid"]: r for r in json.loads(body)["rows"]}
        check("صفحة المدير: المفروزة والمفتوحة", rows["1"]["state"] == "done" and rows["6"]["state"] == "open")
        code, body, _ = get(base + "/admin/contest", auth=True)
        check("صفحة المدير نفسها", code == 200 and "مسابقة توقّع النتيجة" in body.decode())
        code, body, _ = get(base + "/static/contest-draw.js")
        check("سكربت الفيديو يُقدَّم", code == 200 and b"SSDraw" in body)
    finally:
        for p in procs:
            p.terminate()
        shutil.rmtree(data, ignore_errors=True)


def main():
    unit()
    live()
    print(f"\nResult: {_p} passed, {_f} failed")
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

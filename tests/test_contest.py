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
import urllib.parse
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
    d = {"m": "7", "name": "عبدالله محمد", "h": 2, "a": 1, "agree": True}
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

    print("التسجيل برسالة واتساب")
    d = fresh()
    m = match()
    ms = {"7": m}
    link = lambda rec: "https://x/" + rec["eid"]  # noqa: E731
    code, res = C.start(d, m, form(), "1.1.1.1", NOW)
    check("لا مسابقة قبل أن يفتحها المدير", code == 409 and res.get("state") == "off", res)
    C.configure(d, m, True, "اشتراك 3 أشهر", 1, now=NOW)
    code, res = C.start(d, m, form(), "1.1.1.1", NOW)
    tk = res.get("code", "")
    check("الصفحة تأخذ رمزًا ورسالةً جاهزة، ولا رقم يُكتب", code == 200 and len(tk) == C.CODE_LEN
          and set(tk) <= set(C.CODE_ALPHA) and ("رمز التوقّع: " + tk) in res["text"]
          and "بلجيكا 2 – 1 فرنسا" in res["text"], res)
    check("الرمز ينتظر ولا توقّع بعد", C.ticket_status(d, "7", tk)["state"] == "pending" and not C.load(d, "7")["entries"])
    r = C.confirm(d, res["text"], "966551234567", NOW + 5, ms, link, now=NOW + 6)
    rec = C.load(d, "7")
    check("الرسالة تسجّله برقم مرسلها", r["status"] == "done" and r["n"] == 1
          and rec["entries"][0]["phone"] == "966551234567" and rec["entries"][0]["name"] == "عبدالله محمد", r)
    check("ويُردّ عليه بالتأكيد ورابط صفحته", "تم تسجيل توقّعك" in r["reply"] and "https://x/7" in r["reply"]
          and "بلجيكا 2 – 1 فرنسا" in r["reply"])
    ts = C.ticket_status(d, "7", tk.lower())
    check("والصفحة ترى التسجيل برقمٍ مخفي", ts["state"] == "done" and ts["n"] == 1 and ts["phone"] == "05•••••567", ts)
    r = C.confirm(d, res["text"], "966551234567", NOW + 7, ms, link, now=NOW + 8)
    check("الرسالة نفسها مرةً ثانية: لا توقّعٌ ثانٍ", r["status"] == "done" and len(C.load(d, "7")["entries"]) == 1, r)
    r = C.confirm(d, res["text"], "966559999999", NOW + 9, ms, link, now=NOW + 9)
    check("الرمز من رقمٍ آخر (رسالةٌ مُعاد توجيهها) مرفوض", r["status"] == "used"
          and len(C.load(d, "7")["entries"]) == 1, r)
    code, res2 = C.start(d, m, form(h=0, a=0), "2.2.2.2", NOW)
    r = C.confirm(d, res2["text"], "+966 55 123 4567", NOW + 10, ms, link, now=NOW + 10)
    check("رقمٌ توقّع من قبل: مرفوض ولا يتغيّر توقّعه", r["status"] == "dup" and "من قبل" in r["reply"]
          and C.load(d, "7")["entries"][0]["h"] == 2 and C.ticket_status(d, "7", res2["code"])["state"] == "dup", r)
    check("رسالة عميلٍ عادية بلا رمز: لا ردّ أبدًا",
          C.confirm(d, "السلام عليكم، متى ينتهي اشتراكي؟", "966551111111", NOW, ms, link, now=NOW) == {"status": "ignored"})
    r = C.confirm(d, "رمز التوقّع: ACDEFG", "966551111111", NOW, ms, link, now=NOW)
    check("رمزٌ لا وجود له", r["status"] == "unknown" and r["reply"])
    code, res3 = C.start(d, m, form(h=1, a=1), "3.3.3.3", NOW)
    r = C.confirm(d, res3["text"], "", NOW, ms, link, now=NOW)
    check("رقم المرسل مجهول (معرّف LID بلا رقم): لا تسجيل", r["status"] == "nophone" and len(C.load(d, "7")["entries"]) == 1)
    r = C.confirm(d, res3["text"], "966552222222", m["ts"] + 1, ms, link, now=m["ts"] + 2)
    check("أُرسلت بعد صافرة البداية: لا تُحتسب", r["status"] == "late" and len(C.load(d, "7")["entries"]) == 1
          and C.ticket_status(d, "7", res3["code"])["state"] == "late", r)
    code, res4 = C.start(d, m, form(h=3, a=0), "4.4.4.4", NOW)
    r = C.confirm(d, res4["text"], "966553333333", m["ts"] - 30, ms, link, now=m["ts"] + 120)
    check("أُرسلت قبلها ووصلت بعدها: تُحتسب بوقت إرسالها", r["status"] == "done"
          and C.load(d, "7")["entries"][-1]["at"] == m["ts"] - 30, r)
    code, res5 = C.start(d, m, form(h=0, a=3), "5.5.5.5", NOW)
    r = C.confirm(d, res5["text"], "966554444444", m["ts"] - 30, ms, link, now=m["ts"] + C.WA_GRACE + 1)
    check("وبعد المهلة لا تُقبل مهما كان وقت إرسالها", r["status"] == "late")
    check("لا رمز بعد البداية", C.start(d, m, form(), "6.6.6.6", m["ts"])[1].get("state") == "closed")
    check("وقتٌ شاذّ من المرسل: وقت الوصول", C._sent_time(NOW + 99999, NOW) == NOW and C._sent_time("x", NOW) == NOW
          and C._sent_time(NOW - 60, NOW) == NOW - 60)
    check("الرمز من الرسالة وإن تغيّرت كتابتها", C.code_in("توقّعي\nرمز التوقّع: k7q4mx") == "K7Q4MX"
          and C.code_in("رمز التوقع ٣٤٦٧٩A شكرًا") == "34679A" and C.code_in("رمز التوقّع: K7Q4MXX") == ""
          and C.code_in("K7Q4MX") == "")
    C.configure(d, match(eid="8"), True, "اشتراك شهر", 1, now=NOW)
    code, r8 = C.start(d, match(eid="8"), form(m="8"), "7.7.7.7", NOW)
    r = C.confirm(d, r8["text"], "966555555555", NOW, {"7": m, "8": match(eid="8")}, link, now=NOW)
    check("الرمز يدلّ على مباراته", r["status"] == "done" and r["eid"] == "8" and len(C.load(d, "8")["entries"]) == 1)
    check("الاسم لازم", C.start(d, m, form(name=" 1 "), "8.8.8.8", NOW)[1].get("field") == "name")
    check("النتيجة لازمة وفي حدّها", C.start(d, m, form(h=40), "8.8.8.8", NOW)[1].get("field") == "score"
          and C.start(d, m, form(h="x"), "8.8.8.8", NOW)[1].get("field") == "score")
    check("الموافقة على الشروط لازمة", C.start(d, m, form(agree=False), "8.8.8.8", NOW)[1].get("field") == "agree")
    code, res = C.start(d, m, form(website="http://spam"), "8.8.8.8", NOW)
    check("الحقل المخفي: رمزٌ كاذب لا يُحفظ", code == 200 and res["code"] not in C.load(d, "7")["tickets"])
    check("مباراةٌ غير التي في الطلب", C.start(d, match(eid="8"), form(), "8.8.8.8", NOW)[0] == 404)
    got = [C.start(d, m, form(), "1.2.3.4", NOW)[0] for _ in range(C.IP_PER_MATCH + 1)]
    check(f"حدّ العنوان في المباراة ({C.IP_PER_MATCH})", got[-1] == 429 and got[:-1] == [200] * C.IP_PER_MATCH, got)
    old = C.IP_PER_HOUR
    C.IP_PER_HOUR = 3
    try:
        C._hits.clear()
        got = [C.start(d, m, form(), "9.9.9.9", NOW)[0] for i in range(4)]
    finally:
        C.IP_PER_HOUR = old
    check("حدّ العنوان في الساعة", got == [200, 200, 200, 429], got)
    rec = C.load(d, "7")
    blob = json.dumps(rec)
    check("لا يُحفظ العنوان نفسه", not re.search(r"\d+\.\d+\.\d+\.\d+", blob))
    check("لقطة المباراة مع المسابقة", rec["match"]["home"] == "بلجيكا" and rec["match"]["slug"] == "7-belgium-france")
    closed = dict(m, state="in", status="STATUS_FIRST_HALF")
    check("البصمة لا تُعلن قبل مهلة الرسائل المتأخرة", "fp" not in C.public(rec, closed, m["ts"] + 60)
          and "fp" in C.public(rec, closed, m["ts"] + C.WA_GRACE))
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
    dex = C.draw(rec, fb, NOW)
    check("الافتراض «بالضبط فقط»: لا أحد بالضبط ← لا فائز، ولو أصاب كثيرون الفائز", C.mode_of(rec) == "exact"
          and dex["mode"] == "exact" and dex["exact"] == 0 and dex["outcome"] == 5 and dex["picks"] == [], dex["picks"])
    five_x = C.draw(dict(rec, winners=5), end, NOW)["picks"]
    check("وأكثر من المصيبين بالضبط: لا تكملهم فئة الفائز", [x["tier"] for x in five_x] == ["exact"] * 3)
    orec = dict(rec, mode="outcome")
    dfb = C.draw(orec, fb, NOW)
    check("طريقة «بالضبط، وإلا من أصاب الفائز»: من أصاب الفائز", dfb["mode"] == "outcome" and dfb["exact"] == 0
          and dfb["picks"][0]["tier"] == "outcome" and dfb["picks"][0]["size"] == 5, dfb["picks"])
    five = C.draw(dict(orec, winners=5), end, NOW)["picks"]
    check("وأكثر من المصيبين بالضبط: تكملهم فئة الفائز", [x["tier"] for x in five] == ["exact"] * 3 + ["outcome"] * 2)
    check("وبالمعادلة نفسها: الفائز الأول لا يتغيّر بين الطريقتين حين يصيب أحدٌ بالضبط",
          C.draw(orec, end, NOW)["picks"][0] == dr["picks"][0])
    nob = dict(end, home=dict(end["home"], score=0), away=dict(end["away"], score=2))
    check("لم يُصب أحدٌ شيئًا ← لا فائز", C.draw(orec, nob, NOW)["picks"] == [] and C.draw(rec, nob, NOW)["picks"] == [])
    check("فرزٌ قديمٌ بلا طريقة: تُعرف من فئة فائزيه", C.draw_mode({"picks": [{"tier": "outcome"}]}) == "outcome"
          and C.draw_mode({"picks": [{"tier": "exact"}]}) == "exact" and C.draw_mode({"picks": []}) == "exact")

    print("الفرز الآلي (settle)")
    live = dict(end, state="in", status="STATUS_SECOND_HALF")
    check("لا فرز والمباراة جارية", C.settle(d, "7", live, NOW + 7200) == (C.load(d, "7"), False))
    check("لا فرز قبل مرور الحدّ من البداية", C.settle(d, "7", end, m["ts"] + C.SETTLE_AFTER - 1)[1] is False)
    rec, did = C.settle(d, "7", end, m["ts"] + C.SETTLE_AFTER)
    check("يُفرز بعد النهاية ويُحفظ", did and C.load(d, "7")["draw"]["picks"] == dr["picks"])
    rec, did = C.settle(d, "7", other, m["ts"] + C.SETTLE_AFTER + 60)
    check("الإعادة لا تغيّر شيئًا", not did and rec["draw"]["seed"] == sd)
    check("خرجت من قائمة الانتظار", "7" not in C.waiting(d) and C.summaries(d)["7"]["draw"])
    check("لا رمز بعد الفرز", C.start(d, m, form(), "7.7.7.7", NOW)[1].get("state") == "done")
    check("والرموز لا تُحفظ بعده", "tickets" not in C.load(d, "7"))
    check("لا تعديل بعد الفرز", C.configure(d, m, True, "x", 1, now=NOW)[0] == 409)
    seed(d, match(eid="9"), people[:2])
    rec, did = C.settle(d, "9", match(eid="9", status="STATUS_CANCELED"), NOW)
    check("المباراة الملغاة: بلا فرز", not did and rec["void"] and C.state_of(rec, match(eid="9"), NOW) == "void")

    print("إعادة الفرز بطريقة «بالضبط فقط»")
    d6 = fresh()
    m6 = match(eid="41")
    code, res = C.configure(d6, m6, True, "شهر", 2, now=m6["ts"] - 7200, mode="outcome")
    check("طريقة الفوز تُحفظ في المسابقة", code == 200 and res["contest"]["mode"] == "outcome", res)
    code, res = C.configure(d6, m6, True, "شهر", 2, now=m6["ts"] - 7200, mode="bogus")
    check("وقيمةٌ غير معروفة لا تغيّرها", res["contest"]["mode"] == "outcome")
    r6 = C.load(d6, "41")
    for i, (h, a) in enumerate([(0, 2), (1, 2), (2, 0), (0, 3), (1, 1), (0, 2), (2, 2)], 1):
        r6["entries"].append({"n": i, "name": f"مشارك {i}", "phone": f"96655100000{i}", "h": h, "a": a,
                              "at": m6["ts"] - 600 + i, "ipk": "", "promo": False})
    with C._lock:
        C._save(d6, r6)
    code, res = C.configure(d6, dict(m6, state="in", status="STATUS_FIRST_HALF"), True, "شهر", 2,
                            now=m6["ts"] + 600, mode="exact")
    check("ولا تتغيّر بعد إقفال التوقّعات", code == 409, res)
    end6 = dict(m6, state="post", status="STATUS_FULL_TIME", home=dict(m6["home"], score=0), away=dict(m6["away"], score=1))
    r6, did = C.settle(d6, "41", end6, m6["ts"] + C.SETTLE_AFTER)
    first = r6["draw"]
    check("فرز الطريقة القديمة: فائزان ممن أصاب الفائز", did and [p["tier"] for p in first["picks"]] == ["outcome"] * 2)
    r6["sent"] = [{"to": "966551000001", "kind": "winner", "ok": True}]
    with C._lock:
        C._save(d6, r6)
    again = C.redraw(d6, "41", "exact", now=m6["ts"] + 9000)
    check("إعادة الفرز «بالضبط فقط»: لا فائز، بالبصمة ورقم القرعة نفسيهما", again["draw"]["picks"] == []
          and again["draw"]["mode"] == "exact" and again["draw"]["seed"] == first["seed"]
          and again["draw"]["fp"] == first["fp"] and again["mode"] == "exact")
    check("والفرز السابق ورسائله محفوظان في سجلّ الإعادات", again["redraws"][0]["draw"] == first
          and again["redraws"][0]["mode"] == "outcome" and again["redraws"][0]["sent"] and again["sent"] == [])
    pub6 = C.public(C.load(d6, "41"), end6, m6["ts"] + 9100)
    check("والعلن: لا فائز، بطريقة «بالضبط»، ومرّة إعادة", pub6["state"] == "done" and pub6["draw"]["picks"] == []
          and pub6["draw"]["mode"] == "exact" and pub6["draw"]["redrawn"] == 1)
    det6 = C.admin_detail(d6, "41", end6, m6["ts"] + 9100)
    check("والمدير يرى السجلّ بأسماء من كانوا فائزين", det6["draw_mode"] == "exact" and len(det6["redraws"]) == 1
          and len(det6["redraws"][0]["won"]) == 2 and not det6["won"], det6["redraws"])
    check("وإعادةٌ لمسابقةٍ لم تُفرز: لا شيء", C.redraw(d6, "999", "exact") is None)
    try:
        C.redraw(d6, "41", "x")
        bad = False
    except ValueError:
        bad = True
    check("وطريقةٌ غير معروفة تُرفض", bad)
    shutil.rmtree(d6)

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


def unit_prize():
    """الجائزة من منتجات سلة، وإعداد خدمة واتساب النظام اللوجستي، ورسالة القناة."""
    import datetime
    import store_sitemap as S
    print("الجائزة والخدمة ورسالة القناة")
    pub = {"id": 11, "name": " اشتراك  سمارت 3 أشهر | IPTV ", "status": "sale", "url": "https://ssouq.com/a/p11",
           "price": 99, "sale_price": 79, "image": {"url": "https://cdn.salla.sa/11.png"}, "is_out_of_stock": False}
    x = S.product_of(pub)
    check("منتج الواجهة العامة بشكلٍ واحد", x == {"id": "11", "name": "اشتراك سمارت 3 أشهر | IPTV",
                                                   "url": "https://ssouq.com/a/p11", "price": 79.0,
                                                   "img": "https://cdn.salla.sa/11.png", "available": True}, x)
    adm = {"id": 12, "name": "سنة", "status": "out", "urls": {"customer": "https://ssouq.com/b/p12"},
           "price": {"amount": 249, "currency": "SAR"}, "main_image": "http://insecure/x.png", "show_in": {"web": True}}
    x = S.product_of(adm)
    check("والإدارية: السعر من {amount}، والنافد يبقى بلا توفّر، ولا صورة بلا https", x["price"] == 249.0
          and not x["available"] and x["img"] == "", x)
    check("المخفي، وغير المعروض على الويب، ورابطٌ خارج المتجر: لا", not S.product_of(dict(pub, status="hidden"))
          and not S.product_of(dict(adm, show_in={"web": False})) and not S.product_of(dict(pub, url="https://evil.com/p11"))
          and not S.product_of(dict(pub, id="p11")) and not S.product_of(None))
    check("اسم الجائزة ما قبل «|»", C.prize_name({"name": "اشتراك سمارت 3 أشهر | IPTV"}) == "اشتراك سمارت 3 أشهر")

    d = fresh()
    m = match(eid="21", ts=NOW + 7200)
    prod = S.product_of(pub)
    code, res = C.configure(d, m, True, "", 1, now=NOW, product=prod)
    c = res["contest"]
    check("اختيار منتجٍ جائزةً: الاسم والرابط بعلامة الدليل والصورة", code == 200 and c["prize"] == "اشتراك سمارت 3 أشهر"
          and c["prize_id"] == "11" and c["prize_url"] == "https://ssouq.com/a/p11?" + C.PRIZE_UTM
          and c["prize_img"] == "https://cdn.salla.sa/11.png", c)
    sp = C.saved_prize(d, "21")
    check("المحفوظ يُستعاد منتجًا برابطه الأصلي", sp == {"id": "11", "name": "اشتراك سمارت 3 أشهر",
                                                        "url": "https://ssouq.com/a/p11", "img": "https://cdn.salla.sa/11.png"}, sp)
    code, res = C.configure(d, m, True, "", 2, now=NOW, product=sp)
    check("وإعادة حفظه لا تكرّر علامة الدليل", res["contest"]["prize_url"].count("utm_source") == 1
          and res["contest"]["winners"] == 2, res)
    code, res = C.configure(d, m, False, "", 2, now=NOW)
    check("الإيقاف يُبقي الجائزة ورابطها", code == 200 and not res["contest"]["on"]
          and res["contest"]["prize_id"] == "11", res)
    code, res = C.configure(d, m, True, "بطاقة هدية", 1, now=NOW)
    check("جائزةٌ مكتوبة تحلّ محلّ المنتج", res["contest"]["prize"] == "بطاقة هدية" and not res["contest"]["prize_id"]
          and not res["contest"]["prize_url"] and C.saved_prize(d, "21") is None, res)
    pub_d = C.public(C.load(d, "21"), m, NOW)
    check("والعلن يحمل رابط الجائزة إن وُجد", "prize_url" in pub_d)
    C.configure(d, m, True, "", 1, now=NOW, product=prod)
    html = T._prize_row(C.summaries(d)["21"])
    check("سطر الجائزة في البطاقة: رابط صفحتها في نافذة", 'class="pprize"' in html and "p11?utm_source=" in html
          and 'target="_blank"' in html and "اشتراك سمارت 3 أشهر" in html, html)
    check("ولا سطر لجائزةٍ بلا رابط", T._prize_row({"prize": "x", "prize_url": ""}) == "")

    # الخدمة: مدمجةٌ داخل الحاوية بلا إعداد، أو خارجيةٌ من البيئة بأسماء النظام اللوجستي
    saved = {k: os.environ.pop(k) for k in ("WHATSAPP_READER_URL", "WHATSAPP_READER_SECRET") if k in os.environ}
    try:
        cfg = C.reader_config(d)
        check("بلا إعداد: الخدمة المدمجة على 127.0.0.1 بسرٍّ مولَّد", cfg["embedded"]
              and cfg["url"] == f"http://127.0.0.1:{C.EMBED_PORT}" and len(cfg["secret"]) >= 24, cfg["url"])
        check("ورمز الوارد غير السرّ، وكلاهما ثابتٌ بين القراءات", len(cfg["token"]) >= 24 and cfg["token"] != cfg["secret"]
              and C.reader_config(d) == cfg)
        raw = open(os.path.join(d, "contest", "settings.json"), encoding="utf-8").read()
        check("وكلاهما مشفَّرٌ على القرص", cfg["secret"] not in raw and cfg["token"] not in raw)
        C.save_settings(d, {"notify": True, "text": "مرحبا {name}", "admin_phone": "0551234567"})
        check("حفظ إعدادات التبليغ لا يمسّهما", C.reader_config(d) == cfg)
        os.environ.update(WHATSAPP_READER_URL="https://reader.internal:3000/", WHATSAPP_READER_SECRET="envsec")
        c3 = C.reader_config(d)
        check("خدمةٌ خارجية من البيئة تغلب المدمجة", c3["url"] == "https://reader.internal:3000" and c3["secret"] == "envsec"
              and not c3["embedded"] and c3["token"] == cfg["token"], c3)
    finally:
        os.environ.pop("WHATSAPP_READER_URL", None)
        os.environ.pop("WHATSAPP_READER_SECRET", None)
        os.environ.update(saved)

    # رسالة القناة (بصيغة المتجر، وبأعلام المنتخبين)
    from league import RIYADH
    k = datetime.datetime(2026, 9, 28, 21, 45, tzinfo=RIYADH).timestamp()
    now = datetime.datetime(2026, 9, 28, 20, 40, tzinfo=RIYADH).timestamp()
    G = "https://guide.ssouq.com/nations-league/"
    LOGO = "https://a.espncdn.com/combiner/i?img=/i/teamlogos/countries/500/{}.png&w=48&h=48"
    CODES = {"تركيا": "tur", "إيطاليا": "ita", "بلجيكا": "bel", "فرنسا": "fra", "إنجلترا": "eng"}

    def row(h, a, ts, prize="اشتراك سمارت 3 أشهر", w=1, st="open", extra=0):
        return {"state": st, "match": {"home": h, "away": a, "ts": ts, "slug": f"9-{h}-{a}",
                                       "home_logo": LOGO.format(CODES.get(h, "zz")), "away_logo": LOGO.format(CODES.get(a, "zz"))},
                "contest": {"prize": prize, "winners": w, "extra": extra}}

    check("الأعلام من شعار ESPN، وإنجلترا بعلمها", T.flag(LOGO.format("ksa")) == "🇸🇦" and T.flag(LOGO.format("irq")) == "🇮🇶"
          and T.flag(LOGO.format("sba")) == "🇷🇸" and T.flag(LOGO.format("eng")) == "🏴\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F"
          and T.flag(LOGO.format("zz")) == "" and T.flag("") == "")
    one = T.announcement([row("بلجيكا", "فرنسا", k)], now)
    check("مباراةٌ واحدة: الصيغة كما كتبها المتجر، بالعلمين ورابط صفحتها", one == "\n".join([
        "🎁 مسابقة سمارت سوق | توقّع واربح! ⚽🏆", "", "توقّع نتيجة مباراة الليلة بين:", "",
        "🇧🇪 بلجيكا × فرنسا 🇫🇷", "🕘 الساعة 9:45 م", "", "🎁 الجائزة:", "اشتراك سمارت 3 أشهر 🎉", "",
        "طريقة المشاركة:", "1️⃣ ادخل صفحة المباراة 👇", f"{G}9-بلجيكا-فرنسا#predict", "",
        "2️⃣ اكتب توقعك للنتيجة + اسمك.", "", "3️⃣ اضغط «أرسل توقّعي على واتساب» وأرسل الرسالة الجاهزة كما هي.", "",
        "4️⃣ انتظر رسالة التأكيد على الواتساب ✅", "", "📌 الشروط:", "• المشاركة مجانية بالكامل.",
        "• توقع واحد فقط لكل رقم في كل مباراة.", "• تُغلق التوقعات مع صافرة بداية المباراة.",
        "• بعد نهاية المباراة يتم الفرز آليًا بين أصحاب التوقع الصحيح بالنتيجة كاملة.",
        "• إذا لم يتوقع أحد النتيجة الصحيحة، لا يوجد فائز.",
        "• سيتم نشر فيديو يوضح آلية الفرز، والتواصل مع الفائز عبر الواتساب.", "",
        "🔥 جاهزين للتحدي؟ توقّع النتيجة الآن!", "", "🤞 بالتوفيق للجميع!"]), one[:300])
    txt = T.announcement([row("تركيا", "إيطاليا", k), row("بلجيكا", "فرنسا", k), row("x", "y", k, st="off"),
                          row("z", "w", k, st="hold")], now)
    check("مباريات الليلة: الساعة مرّة، ولكلٍّ علماها ورابطها", "توقّع نتيجة مباريات الليلة في دوري الأمم الأوروبية:\n\n🕘 الساعة 9:45 م\n\n"
          f"🇹🇷 تركيا × إيطاليا 🇮🇹\n{G}9-تركيا-إيطاليا#predict\n\n🇧🇪 بلجيكا × فرنسا 🇫🇷\n{G}9-بلجيكا-فرنسا#predict\n\n"
          "🎁 الجائزة لكل مباراة:\nاشتراك سمارت 3 أشهر 🎉\n\nطريقة المشاركة:\n1️⃣ افتح رابط المباراة اللي تبيها 👆\n" in txt,
          txt[:500])
    check("والشروط لكل مباراة والختام", "• تُغلق التوقعات مع صافرة بداية كل مباراة.\n" in txt
          and "• بعد نهاية كل مباراة يتم الفرز آليًا" in txt and txt.endswith("🤞 بالتوفيق للجميع!"))
    check("والموقوفة والمغلقة ليست فيها", "x × y" not in txt and "z × w" not in txt)
    one = T.announcement([row("بلجيكا", "فرنسا", k, w=2, extra=10)], now)
    check("فائزان، والإقفال بعد البداية بدقائق المدير", "اشتراك سمارت 3 أشهر — فائزان 🎉" in one
          and "• تُغلق التوقعات بعد صافرة البداية بـ 10 دقائق.\n" in one)
    orow = row("بلجيكا", "فرنسا", k)
    orow["contest"]["mode"] = "outcome"
    check("وطريقة «بالضبط، وإلا من أصاب الفائز»", "• إذا لم يتوقع أحد النتيجة الصحيحة، فالفرز بين من توقّع الفائز."
          in T.announcement([orow], now))
    mix = T.announcement([row("أ", "ب", k, extra=10), row("ج", "د", k)], now)
    check("وإقفالٌ مختلف بين المباريات يُقال عامًّا", "أو بعدها بدقائق، كما في صفحة كل مباراة" in mix)
    txt = T.announcement([row("تركيا", "إيطاليا", k, prize=""), row("بلجيكا", "فرنسا", k + 3 * 86400, w=3)], now)
    check("أيامٌ مختلفة وجوائز مختلفة: الموعد والجائزة لكلٍّ", "توقّع نتيجة المباريات المفتوحة للتوقّع في دوري الأمم الأوروبية:" in txt
          and "🇹🇷 تركيا × إيطاليا 🇮🇹\n🕘 الاثنين 28 سبتمبر 2026 · 9:45 م\n" in txt
          and "🎁 الجوائز:\n• تركيا × إيطاليا: [اكتب الجائزة هنا]\n• بلجيكا × فرنسا: اشتراك سمارت 3 أشهر — 3 فائزين" in txt,
          txt[:400])
    txt = T.announcement([row("تركيا", "إيطاليا", k + 86400 - 5 * 3600, w=2)], now)
    check("مباراة الغد وحدها", "توقّع نتيجة مباراة الغد بين:" in txt and "🕓 الساعة 4:45 م" in txt, txt[:200])
    txt = T.announcement([row("أ", "ب", k), row("ج", "د", k - 2 * 3600)], now - 6 * 3600)
    check("اليوم بموعدين: الساعة تحت كل مباراة", "توقّع نتيجة مباريات الليلة في دوري الأمم الأوروبية:" in txt
          and f"ج × د\n🕖 7:45 م\n{G}9-ج-د#predict\n\nأ × ب\n🕘 9:45 م" in txt and "الساعة" not in txt, txt[:300])
    check("ولا مسابقة مفتوحة: لا رسالة", T.announcement([row("a", "b", k, st="done")], now) == "")

    # الإقفال بعد صافرة البداية بدقائق (خيار المدير)
    d4 = fresh()
    m = match(eid="31", ts=NOW + 3600)
    code, res = C.configure(d4, m, True, "شهر", 1, now=NOW, extra=10)
    check("خيار الإقفال: يُحفظ ويظهر في الملخّص", code == 200 and res["contest"]["extra"] == 10, res)
    code, res = C.configure(d4, m, True, "شهر", 1, now=NOW, extra=99)
    check("وأقصاه 15 دقيقة", res["contest"]["extra"] == C.EXTRA_MAX == 15)
    C.configure(d4, m, True, "شهر", 1, now=NOW, extra=10)
    rec = C.load(d4, "31")
    live_m = dict(m, state="in", status="STATUS_FIRST_HALF")
    check("بعد الصافرة وضمن الدقائق: مفتوحة والمباراة جارية", C.state_of(rec, live_m, m["ts"] + 9 * 60) == "open")
    check("وبعدها مقفلة", C.state_of(rec, live_m, m["ts"] + 10 * 60) == "closed")
    check("وبلا الخيار: مقفلةٌ مع الصافرة", C.state_of(dict(rec, extra=0), live_m, m["ts"] + 60) == "closed")
    code, res = C.start(d4, live_m, form(m="31"), "1.2.3.4", now=m["ts"] + 5 * 60)
    check("وتُعطى رموزٌ خلالها", code == 200, res)
    ms4 = {"31": live_m}
    r = C.confirm(d4, res["text"], "966551112233", m["ts"] + 6 * 60, ms4, lambda x: "L", now=m["ts"] + 6 * 60)
    check("ورسالةٌ أُرسلت خلالها تُسجَّل", r["status"] == "done", r)
    code, res2 = C.start(d4, live_m, form(m="31"), "1.2.3.5", now=m["ts"] + 9 * 60)
    r = C.confirm(d4, res2["text"], "966551112244", m["ts"] + 10 * 60 + 5, ms4, lambda x: "L", now=m["ts"] + 10 * 60 + 5)
    check("وما أُرسل بعد الإقفال متأخر", r["status"] == "late" and "إقفال التوقّعات" in r["reply"], r)
    pub = C.public(C.load(d4, "31"), live_m, m["ts"] + 11 * 60)
    check("العلن: موعد الإقفال، والبصمة بعد مهلة الرسائل من الإقفال", pub["closes"] == m["ts"] + 600 and "fp" not in pub
          and "بـ 10 دقائق" in pub["msg"] and "fp" in C.public(C.load(d4, "31"), live_m, m["ts"] + 600 + C.WA_GRACE))
    code, res = C.configure(d4, m, True, "شهر", 1, now=m["ts"] + 600 + C.WA_GRACE, extra=15)
    check("ولا يتغيّر الإقفال بعد إعلان القائمة النهائية", code == 409, res)
    d5 = fresh()
    m5 = match(eid="32", ts=NOW)
    C.configure(d5, m5, True, "شهر", 1, now=NOW - 60)
    rec5 = C.load(d5, "32")
    rec5["entries"].append({"n": 1, "name": "س", "phone": "966551110000", "h": 1, "a": 0, "at": NOW - 30, "ipk": "", "promo": False})
    with C._lock:
        C._save(d5, rec5)
    code, res = C.configure(d5, dict(m5, state="in", status="STATUS_FIRST_HALF"), True, "شهر", 1, now=NOW + 120, extra=10)
    check("قبل إعلان القائمة: يُمدَّد الإقفال بعد الصافرة فتعود مفتوحة", code == 200
          and C.state_of(C.load(d5, "32"), dict(m5, state="in", status="STATUS_FIRST_HALF"), NOW + 180) == "open", res)
    lst = C.listing(C.summaries(d4), [live_m], m["ts"] + 60)
    check("صفحة المسابقة: موعد الإقفال لكل مسابقة", lst and lst[0]["closes"] == m["ts"] + 600)
    for x in (d4, d5):
        shutil.rmtree(x)
    shutil.rmtree(d)


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
    mport, port, wport = 9781, 9782, 9783
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
    # كليلة 28 سبتمبر: فُرزت قبل خيار الطريقة (لا mode)، ولم يُصب أحدٌ 0-1 فخرج فائزان ممن توقّع فوز الضيف
    m2 = next(x for x in ms if x["id"] == "2")
    old = C._blank("2")
    old.update(on=True, prize="اشتراك 3 أشهر", winners=2, match=C._snap(m2))
    for i, (h, a) in enumerate([(0, 2), (1, 2), (2, 0), (0, 3), (1, 1), (0, 2), (1, 3)], 1):
        old["entries"].append({"n": i, "name": f"لاعب {i}", "phone": f"9665520000{i:02d}", "h": h, "a": a,
                               "at": m2["ts"] - 600 + i, "ipk": "", "promo": False})
    old["draw"] = C.draw(dict(old, mode="outcome"), m2, m2["ts"] + 7000)
    del old["draw"]["mode"]
    with open(os.path.join(data, "contest", "2.json"), "w", encoding="utf-8") as f:
        json.dump(old, f, ensure_ascii=False)
    procs = [subprocess.Popen([sys.executable, os.path.join(HERE, "mock_espn.py"), str(mport)])]
    try:
        base, reader = f"http://127.0.0.1:{port}", f"http://127.0.0.1:{wport}"
        # خدمة واتساب النظام اللوجستي وهميةً (ومعها منتجات سلة)، ورابط الوارد إلى هذا الخادم
        procs.append(subprocess.Popen([sys.executable, os.path.join(HERE, "mock_reader.py"), str(wport), "rdr_live"]))
        env = {k: v for k, v in os.environ.items() if not k.startswith(("WHATSAPP_READER_", "SALLA_ADMIN_TOKEN"))}
        env.update(XM_DATA=data, XM_BIND="127.0.0.1", XM_PORT=str(port), XM_ADMIN_PASSWORD="envpass123",
                   LEAGUE_API=f"http://127.0.0.1:{mport}", SALLA_API=reader, WHATSAPP_READER_URL=reader,
                   WHATSAPP_READER_SECRET="rdr_live", CONTEST_INBOUND_URL=base + "/api/contest/wa-inbound")
        procs.append(subprocess.Popen([sys.executable, os.path.join(ROOT, "xm_lines.py"), "web"], env=env))
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
        check("بلا واتساب مضبوط: التسجيل متوقّف", d.get("reg") is False)
        code, res = post(base + "/api/contest/start", {"m": "6", "name": "سارة", "h": 1, "a": 0, "agree": True})
        check("ولا رمز", code == 503, res)

        # ربط رقم المسابقة كما في النظام اللوجستي: رابط الخدمة وسرّها ← الرقم ← QR ← مربوط
        def rd(method, path, body=None, secret="rdr_live"):
            rq = urllib.request.Request(reader + path, method=method, data=json.dumps(body).encode() if body else None,
                                        headers={"Content-Type": "application/json", "X-Reader-Secret": secret})
            with urllib.request.urlopen(rq, timeout=20) as r:
                return json.loads(r.read())

        code, body, _ = get(base + "/admin/api/contest/admin/wa", auth=True)
        w = json.loads(body)
        check("صفحة المدير: الخدمة جاهزة، والرقم غير مربوط", code == 200 and w["configured"] and not w["error"]
              and w["status"] == "disconnected" and not w["embedded"] and not w["qr"], w)
        check("ولا رابطَ ولا سرَّ في ردّها", "rdr_live" not in body.decode() and reader not in body.decode())
        code, res = post(base + "/admin/api/contest/admin/wa/config", {"url": "x", "secret": "y"}, auth=True)
        check("لا إعداد للرابط والسرّ من الصفحة", code == 404)
        code, res = post(base + "/admin/api/contest/admin/wa/connect", {"number": "12"}, auth=True)
        check("الربط يطلب رقمًا صحيحًا", code == 400)
        code, res = post(base + "/admin/api/contest/admin/wa/connect", {"number": "0500000009"}, auth=True)
        check("«ربط»: يظهر رمز QR للمسح", code == 200 and res["status"] == "qr" and res["qr"].startswith("data:image/"), res)
        sess = rd("GET", "/_test/log")["sessions"]["ssouq-guide--contest"]
        check("والجلسة في الخدمة باسمها ورقمها، ورسائلها الخاصة إلى الأداة موقّعة", sess["number"] == "966500000009"
              and sess["dmCallbackUrl"] == base + "/api/contest/wa-inbound" and len(sess["ingestToken"]) >= 24, sess)
        code, body, _ = get(base + "/api/contest?m=6")
        check("قبل المسح: التسجيل متوقّف", json.loads(body).get("reg") is False)
        rd("POST", "/_test/scan/ssouq-guide--contest", {})
        code, body, _ = get(base + "/admin/api/contest/admin", auth=True)
        w = json.loads(body)["reader"]
        check("بعد المسح: مربوطٌ برقمه، ولا QR", w["status"] == "connected" and w["number"] == "966500000009"
              and not w["qr"], w)
        code, body, _ = get(base + "/api/contest?m=6")
        check("فيُفتح التسجيل", json.loads(body).get("reg") is True)
        code, res = post(base + "/admin/api/contest/admin/wa/test", {"to": "0551112222"}, auth=True)
        log = rd("GET", "/_test/log")
        check("رسالة تجربة من رقم المسابقة", code == 200 and res["ok"] and log["sent"][-1]["to"] == "966551112222", res)
        code, res = post(base + "/admin/api/contest/admin/wa/test", {"to": "0599000000"}, auth=True)
        check("ورقمٌ ليس على واتساب يُقال بوضوح", code == 502 and res["error"] == "الرقم ليس على واتساب", res)

        code, res = post(base + "/api/contest/start", {"m": "6", "name": "سارة", "h": 1, "a": 0, "agree": True,
                                                       "promo": True})
        check("رمزٌ ورابط واتساب برسالةٍ جاهزة إلى رقم المسابقة", code == 200
              and res["url"].startswith("https://wa.me/966500000009?text=")
              and urllib.parse.quote(res["code"]) in res["url"] and "%0A" in res["url"], res)
        tk = res["code"]

        def inbound(frm, text, **extra):
            """رسالةٌ خاصة إلى رقم المسابقة كما تمرّرها الخدمة (شكل handleDirectMessage)."""
            payload = {"wa_message_id": f"W{time.time_ns()}", "sender_number": frm, "sender_name": "x",
                       "sent_at": int(time.time()), "body": text, "quoted_body": "", "forwarded": False,
                       "media_base64": None, "media_mime": None, **extra}
            return rd("POST", "/_test/dm/ssouq-guide--contest", payload)

        r = inbound("966551230000", res["text"], _token="wrong")
        check("الأداة لا تقبل رسالةً بتوقيعٍ خاطئ", r["code"] == 401 and not r["sent"], r)
        code, _ = post(base + "/api/contest/wa-inbound", {"sender_number": "966551230000", "body": res["text"]})
        check("ولا بلا توقيع", code == 401)
        r = inbound("966551230000", res["text"])
        check("رسالة التوقّع تصل الأداة ويُردّ على مرسلها من رقم المسابقة", r["code"] == 200
              and r["answer"]["status"] == "ok" and r["sent"] and r["sent"][0]["to"] == "966551230000"
              and "تم تسجيل توقّعك" in r["sent"][0]["body"], r)
        code, body, _ = get(base + f"/api/contest/ticket?m=6&c={tk}")
        t = json.loads(body)
        check("والصفحة ترى رمزها مسجّلًا برقمٍ مخفي", t["state"] == "done" and t["n"] == 1 and t["phone"] == "05•••••000", t)
        r = inbound("966551239999", res["text"])
        check("الرسالة نفسها من رقمٍ آخر: الرمز مستخدم", r["sent"] and "استُخدم" in r["sent"][0]["body"], r)
        r = inbound("966551230000", "السلام عليكم، متى ينتهي اشتراكي؟")
        check("رسائل العملاء الأخرى: ignored ولا ردّ", r["answer"].get("status") == "ignored" and not r["sent"], r)
        r = rd("POST", "/_test/dm/ssouq-guide--contest", {"type": "ack", "wa_message_id": "X", "ack_status": "read"})
        check("إيصالات التسليم تُهمل", r["code"] == 200 and r["answer"]["status"] == "ignored" and not r["sent"], r)
        r = inbound("966551230000", "", media_base64="A" * 300000, media_mime="image/jpeg")
        check("صورةٌ كبيرة تُقرأ وتُهمل (فلا تعيدها الخدمة)", r["code"] == 200 and r["answer"]["status"] == "ignored", r)
        r = rd("POST", "/_test/dm/ssouq-guide--contest", {"type": "ping"})
        check("وفحص الخدمة لرابطنا", r["code"] == 200 and r["answer"]["status"] == "ok", r)

        # الجائزة اشتراكٌ من منتجات سلة الحيّة، برابطه
        code, body, _ = get(base + "/admin/api/contest/admin/products", auth=True)
        pr = json.loads(body)
        ids = [x["id"] for x in pr["products"]]
        check("منتجات سلة للاختيار: المعروض والنافد، لا المخفي", pr["ok"] and ids[:2] == ["1001", "1002"]
              and "1003" not in ids and pr["source"] == "public", pr)
        check("بسعر العرض وتوفّره", pr["products"][0]["price"] == 79 and pr["products"][0]["available"]
              and not pr["products"][1]["available"])
        code, res = post(base + "/admin/api/contest/admin/set", {"m": "6", "on": True, "prize_id": "999", "winners": 1},
                         auth=True)
        check("منتجٌ ليس في المتجر يُرفض", code == 400, res)
        code, res = post(base + "/admin/api/contest/admin/set", {"m": "6", "on": True, "prize_id": "1001", "winners": 2},
                         auth=True)
        c6 = res.get("contest") or {}
        check("اختيار الاشتراك: اسمه جائزةً ورابطه بعلامة الدليل", code == 200 and c6["prize"] == "اشتراك سمارت 3 أشهر"
              and c6["prize_id"] == "1001" and c6["prize_url"].startswith("https://ssouq.com/smart-3m/p1001?utm_source=")
              and c6["prize_img"] == "https://cdn.salla.sa/p1001.png", c6)
        code, body, _ = get(base + "/nations-league/6-netherlands-serbia")
        page = body.decode()
        check("والبطاقة تعرض الجائزة برابط صفحتها", 'class="pprize"' in page and "p1001?utm_source=" in page
              and "توقّع النتيجة واربح اشتراك سمارت 3 أشهر" in page)
        code, body, _ = get(base + "/admin/api/contest/admin", auth=True)
        ann = json.loads(body)["announce"]
        check("رسالة القناة جاهزة: المباراة وموعدها وجائزتها ورابط المسابقة", "🎁 مسابقة سمارت سوق | توقّع واربح!" in ann
              and "هولندا × صربيا" in ann and "🎁 الجائزة:\nاشتراك سمارت 3 أشهر — فائزان 🎉" in ann
              and "https://guide.ssouq.com/nations-league/6-netherlands-serbia#predict" in ann and "الساعة" in ann, ann)
        by = json.loads(body)["announce_by"]
        check("ورسالةٌ لكل مباراةٍ مفتوحة برابطها", set(by) == {"6"} and by["6"] == ann)
        code, res = post(base + "/api/contest/start", {"m": "3", "name": "سارة", "h": 3, "a": 0, "agree": True})
        check("مباراةٌ بلا مسابقة", code == 409 and res.get("state") == "off")
        code, body, _ = get(base + "/api/contest?m=6")
        check("العلن: العدد ولا رقم", json.loads(body)["count"] == 1 and b"551230000" not in body)

        code, body, _ = get(base + "/nations-league/6-netherlands-serbia")
        page = body.decode()
        check("بطاقة المسابقة في صفحة المباراة", 'id="predict" data-m="6"' in page and "/static/contest.js?v=" in page)
        check("ورابط الشروط وكل المسابقات", 'href="/predict#rules"' in page and 'href="/predict">كل المسابقات' in page)
        code, body, _ = get(base + "/nations-league/3-england-spain")
        check("ولا بطاقة لمباراةٍ بلا مسابقة", 'id="predict"' not in body.decode())
        code, body, _ = get(base + "/nations-league")
        page = body.decode()
        check("شريط المسابقة في صفحة البطولة", '<a class="pbanner" href="/nations-league/6-netherlands-serbia#predict"' in page)
        check("وشارةٌ على صفّ المباراة وحده", page.count('<small class="pz">') == 1)
        code, body, _ = get(base + "/nations-league/widget?theme=dark")
        page = body.decode()
        check("والشريط في ودجت المتجر يُفتح في نافذة", re.search(r'<a class="pbanner" href="[^"]+#predict" target="_blank"', page))
        code, body, _ = get(base + "/predict")
        page = body.decode()
        check("صفحة المسابقة: المفتوحة والشروط", code == 200 and "مفتوحة للتوقّع" in page and 'id="rules"' in page
              and C.RULES[0] in page)
        code, body, _ = get(base + "/sitemap.xml")
        check("صفحة المسابقة في خريطة الموقع، لا صفحتا البطولتين القديمتان", b"/predict</loc>" in body
              and b"/nations-league/predict</loc>" not in body)
        req = urllib.request.Request(base + "/nations-league/predict")

        class _NoRedir(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        try:
            urllib.request.build_opener(_NoRedir).open(req, timeout=10)
            moved = (200, "")
        except urllib.error.HTTPError as e:
            moved = (e.code, e.headers.get("Location"))
        check("صفحة مسابقة البطولة القديمة ← 301 إلى /predict", moved == (301, "/predict"), moved)

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
        check("المدير يرى الرقم كاملًا، ورسالة الفائز أُرسلت له عبر الخدمة", det["won"][0]["phone"].startswith("9665500")
              and det["sent"] and det["sent"][0]["to"] == det["won"][0]["phone"] and det["sent"][0]["ok"], det.get("sent"))
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

        code, body, _ = get(base + "/admin/api/contest/admin/match?m=2", auth=True)
        det = json.loads(body)
        check("فرزٌ قديم: طريقته «بالضبط، وإلا من أصاب الفائز» وفائزاه منها", det["draw_mode"] == "outcome"
              and len(det["won"]) == 2 and all(w["tier"] == "outcome" for w in det["won"]), det.get("draw_mode"))
        code, res = post(base + "/admin/api/contest/admin/redraw", {"m": "2", "mode": "exact"})
        check("إعادة الفرز للمدير وحده", code == 401)
        code, res = post(base + "/admin/api/contest/admin/redraw", {"m": "2", "mode": "exact"}, auth=True)
        check("«أعد الفرز: النتيجة بالضبط فقط» ← لا فائز", code == 200 and res["ok"] and res["picks"] == 0, res)
        code, body, _ = get(base + "/api/contest?m=2")
        d2 = json.loads(body)
        check("والعلن يقولها: مفروزة بلا فائز بطريقة «بالضبط»", d2["state"] == "done" and d2["draw"]["picks"] == []
              and d2["draw"]["mode"] == "exact" and d2["draw"]["redrawn"] == 1 and d2["draw"]["seed"] == old["draw"]["seed"], d2.get("draw"))
        code, body, _ = get(base + "/admin/api/contest/admin/match?m=2", auth=True)
        det = json.loads(body)
        check("والمدير يرى من كانا فائزين في سجلّ الإعادات", det["draw_mode"] == "exact" and not det["won"]
              and len(det["redraws"]) == 1 and len(det["redraws"][0]["won"]) == 2, det.get("redraws"))
        code, res = post(base + "/admin/api/contest/admin/redraw", {"m": "6", "mode": "exact"}, auth=True)
        check("ولا إعادة لمسابقةٍ لم تُفرز", code == 409, res)

        # كأس الخليج: مبارياتها في صفحة المدير، والقناة الناقلة، ومسابقةٌ على مباراةٍ منها برابطها
        code, body, _ = get(base + "/admin/api/contest/admin", auth=True)
        d = json.loads(body)
        rows = {r["eid"]: r for r in d["rows"]}
        check("صفحة المدير: مباريات كأس الخليج مع دوري الأمم", "103" in rows and "6" in rows
              and rows["103"]["match"]["cup"] == "كأس الخليج العربي" and rows["103"]["match"]["path"] == "/gulf-cup"
              and rows["6"]["match"]["path"] == "/nations-league", sorted(rows))
        check("واقتراحات القنوات", "AL KASS One" in d["channels"] and "beIN SPORTS 1" in d["channels"])
        code, res = post(base + "/admin/api/contest/admin/tv", {"m": "103", "channel": " AL  KASS One "})
        check("القناة للمدير وحده", code == 401)
        code, res = post(base + "/admin/api/contest/admin/tv", {"m": "103", "channel": " AL  KASS One "}, auth=True)
        check("حفظ القناة الناقلة (بلا مسافاتٍ زائدة)", code == 200 and res["channel"] == "AL KASS One", res)
        code, res = post(base + "/admin/api/contest/admin/tv", {"m": "999999", "channel": "x"}, auth=True)
        check("ولا قناة لمباراةٍ ليست في البطولات", code == 404, res)
        code, res = post(base + "/admin/api/contest/admin/tv", {"m": "104", "channel": "AL KASS Two"}, auth=True)
        code, res = post(base + "/admin/api/contest/admin/tv", {"m": "104", "channel": ""}, auth=True)
        check("والفارغ يمسحها", code == 200 and res["channel"] == "" and "104" not in C.channels(data))
        code, body, _ = get(base + "/admin/api/contest/admin", auth=True)
        check("وتظهر في صف المباراة", {r["eid"]: r for r in json.loads(body)["rows"]}["103"]["tv"] == "AL KASS One")
        code, body, _ = get(base + "/gulf-cup/103-saudi-arabia-iraq")
        page = body.decode()
        check("وفي صفحة المباراة", code == 200 and "القناة الناقلة: <b dir=\"ltr\">AL KASS One</b>" in page)
        code, body, _ = get(base + "/gulf-cup")
        check("وفي جدول البطولة", ">AL KASS One</span>" in body.decode())

        code, res = post(base + "/admin/api/contest/admin/set", {"m": "103", "on": True, "prize": "اشتراك شهر",
                                                                 "winners": 1}, auth=True)
        check("مسابقة على مباراةٍ من كأس الخليج", code == 200 and res["contest"]["match"]["path"] == "/gulf-cup", res)
        code, body, _ = get(base + "/gulf-cup/103-saudi-arabia-iraq")
        page = body.decode()
        check("وبطاقتها في صفحة المباراة بشروط بطولتها", 'id="predict" data-m="103"' in page
              and 'data-rules="/predict#rules"' in page)
        code, body, _ = get(base + "/api/contest?m=103")
        pub = json.loads(body)
        check("والعلن يعرف بطولتها", pub["state"] == "open" and pub["match"]["path"] == "/gulf-cup"
              and pub["match"]["cup"] == "كأس الخليج العربي", pub.get("match"))
        code, body, _ = get(base + "/admin/api/contest/admin", auth=True)
        d = json.loads(body)
        ann, one = d["announce"], d["announce_by"]["103"]
        check("رسالة القناة: بطولتان فاسم كلٍّ بجانب مباراته، ورابطها تحت مسارها", "توقّع نتيجة المباريات المفتوحة للتوقّع:\n" in ann
              and "(كأس الخليج العربي)" in ann and "(دوري الأمم الأوروبية)" in ann
              and "https://guide.ssouq.com/gulf-cup/103-saudi-arabia-iraq#predict" in ann
              and "https://guide.ssouq.com/nations-league/6-netherlands-serbia#predict" in ann, ann[:400])
        check("والقناة الناقلة بجانب المباراة", "📺 AL KASS One" in ann)
        check("ورسالة المباراة وحدها: بعلمَي المنتخبين وقناتها ورابط صفحتها", "السعودية × العراق" in one
              and "📺 القناة الناقلة: AL KASS One" in one
              and "https://guide.ssouq.com/gulf-cup/103-saudi-arabia-iraq#predict" in one, one[:300])
        code, body, _ = get(base + "/predict")
        page = body.decode()
        cards = {m: st for st, m in re.findall(r'<article class="mc ([a-z]+)[^"]*" data-tab="[a-z]+" data-m="(\d+)"', page)}
        check("صفحة المسابقات: البطولتان معًا، بطاقةٌ لكل مسابقة بحالها", cards.get("103") == "open" and cards.get("6") == "open"
              and cards.get("1") == "done" and cards.get("2") == "done", cards)
        card103 = re.search(r'<article class="mc open[^"]*" data-tab="open" data-m="103">.*?</article>', page, re.S).group(0)
        check("بطاقة مباراة كأس الخليج: بطولتها وقناتها و«شارك الآن» إلى صفحتها وجائزتها", "كأس الخليج العربي" in card103
              and ">AL KASS One</span>" in card103 and 'class="cta go" href="/gulf-cup/103-saudi-arabia-iraq#predict"' in card103
              and "اشتراك شهر" in card103 and "الجائزة" in card103, card103[:300])
        card1 = re.search(r'<article class="mc done[^"]*" data-tab="done" data-m="1">.*?</article>', page, re.S).group(0)
        check("والمفروزة: النتيجة والفائز وزرّ عرض الفرز", '<span class="sc">2<i>-</i>1</span>' in card1
              and 'class="won"' in card1 and "عرض النتيجة وفيديو الفرز" in card1, card1[:300])
        card2 = re.search(r'<article class="mc done[^"]*" data-tab="done" data-m="2">.*?</article>', page, re.S).group(0)
        check("والمعاد فرزها بلا فائز", "لم يُصب أحدٌ النتيجة بالضبط، فلا فائز." in card2)
        check("وأزرار التصفية بأعدادها", re.search(r'data-k="all"[^>]*>كل المسابقات <span class="n">\((\d+)\)</span>', page)
              and re.search(r'data-k="open"[^>]*>مفتوحة للتوقّع <span class="n">\(\d+\)</span>', page))
        check("والفائزون، وكيف أشارك، والشروط", 'id="winners"' in page and 'class="wins"' in page and 'id="how"' in page
              and 'id="rules"' in page and "الفرز بالأرقام" in page)
        check("ولا رقمٌ كامل فيها", not re.search(r"9665\d{8}", page))
        code, res = post(base + "/api/contest/start", {"m": "103", "name": "فهد", "h": 2, "a": 0, "agree": True})
        check("رمزٌ لمباراة كأس الخليج", code == 200 and "السعودية 2 – 0 العراق" in res["text"], res)
        r = inbound("966551230077", res["text"])
        r2 = inbound("966551230088", res["text"])
        check("والرد برابط صفحتها تحت /gulf-cup", r["sent"] and "تم تسجيل توقّعك" in r["sent"][0]["body"]
              and r2["sent"] and "https://guide.ssouq.com/gulf-cup/103-saudi-arabia-iraq#predict" in r2["sent"][0]["body"],
              (r2.get("sent") or [{}])[0].get("body", "")[:200])
        code, body, _ = get(base + "/static/contest-draw.js")
        check("سكربت الفيديو يُقدَّم", code == 200 and b"SSDraw" in body)
    finally:
        for p in procs:
            p.terminate()
        shutil.rmtree(data, ignore_errors=True)


def live_embedded():
    """الخدمة المدمجة: بلا أيّ إعداد يشغّلها الخادم داخل الحاوية وتجيب صفحة المدير (إن ثُبّتت مكتباتها)."""
    reader_dir = os.path.join(ROOT, "whatsapp-reader")
    if not shutil.which("node") or not os.path.isdir(os.path.join(reader_dir, "node_modules")):
        print("الخدمة المدمجة: تُتخطّى (لا node أو لم تُثبَّت مكتباتها: cd whatsapp-reader && npm ci --omit=dev)")
        return
    print("الخدمة المدمجة")
    port, rport = 9785, 9786
    data = tempfile.mkdtemp(prefix="contest_emb_")
    env = {k: v for k, v in os.environ.items() if not k.startswith("WHATSAPP_READER_")}
    env.update(XM_DATA=data, XM_BIND="127.0.0.1", XM_PORT=str(port), XM_ADMIN_PASSWORD="envpass123",
               LEAGUE_API="http://127.0.0.1:9", CONTEST_READER_PORT=str(rport))
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "xm_lines.py"), "web"], env=env)
    base, w = f"http://127.0.0.1:{port}", {}
    try:
        for _ in range(100):
            try:
                code, body, _ = get(base + "/admin/api/contest/admin/wa", auth=True)
                w = json.loads(body)
                if w.get("status") == "disconnected" and not w.get("error"):
                    break
            except Exception:
                pass
            time.sleep(.2)
        check("بلا إعداد: الخادم يشغّل الخدمة المدمجة وصفحة المدير تطلب الرقم وحده", w.get("configured")
              and w.get("embedded") and w.get("status") == "disconnected" and not w.get("error"), w)
        code, res = post(base + "/admin/api/contest/admin/wa/connect", {"number": "0500000009"}, auth=True)
        check("«ربط» يبدأ جلسة المسابقة فيها برقمها", code == 200 and res["status"] in ("connecting", "qr")
              and res["number"] == "966500000009", res)
        check("وجلساتها في مجلد البيانات الدائم", os.path.isdir(os.path.join(data, "wa-reader", "sessions")))
        code, res = post(base + "/admin/api/contest/admin/wa/disconnect", {}, auth=True)
        check("و«فصل» يمسحها", code == 200 and res["status"] == "disconnected", res)
    finally:
        p.terminate()
        p.wait(timeout=10)
        for pid in os.listdir("/proc"):              # الخدمة ابنةٌ للخادم: تُعرف بمنفذها في بيئتها
            try:
                with open(f"/proc/{pid}/environ", "rb") as f:
                    if f"PORT={rport}".encode() in f.read().split(b"\0"):
                        os.kill(int(pid), 15)
            except (OSError, ValueError):
                pass
        time.sleep(.5)
        shutil.rmtree(data, ignore_errors=True)


def main():
    unit()
    unit_prize()
    live()
    live_embedded()
    print(f"\nResult: {_p} passed, {_f} failed")
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

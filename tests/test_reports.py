#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""بلاغات المحتوى (reports.py · report.html · reports_admin.html): المشترك يختار من ملف M3U السيرفر ثم القسم ثم
المسلسل أو الفيلم ثم الحلقة، ويبلّغ «لا يعمل» أو «يقطع»؛ والموظف الذي فتحها له المدير يراها ويعلّمها «تم الإصلاح».

  - الخطوات: السيرفرات التي لها محتوى، وأقسامها الظاهرة (بلا المخفي)، وعناصر القسم بالتصفية والصفحات، والبحث بالاسم.
  - البلاغ: يُطابَق بالفهرس (القسم والاسم وسنة الفيلم والموسم)، وما لا يُقبل برسالته، ورقم الواتساب بصيغته الدولية،
    والمكرّر المفتوح يزيد عدده ولا يتكرّر، والحدّ بالساعة، وحدّ الحفظ.
  - الموظف: المفتوحة والمنجزة بأعدادها ولكل سيرفر، و«تم الإصلاح» وإعادة الفتح (ويُضمّ إلى مثله)، والحذف.
  - لكل سيرفر موظفٌ أو أكثر: الموظف لا يرى إلا بلاغات سيرفراته ولا يمسّ غيرها ولا يصله إلا تنبيهها، ومن بلا سيرفراتٍ
    مختارة يتابع كلها، والمدير يرى من يتابع كل سيرفر.
  - المشاكل الأربع («الحلقة ليست هي» و«الفيلم ليس هو» بالنوع، و«الترجمة غير صحيحة»)، وطلب إضافة مسلسلٍ أو فيلمٍ ليس
    في السيرفر: اسمه كما كتبه، والمكرّر يزيد عدده، وتصفيته وحده، وتنبيهه.
  - تنبيه واتساب: نصّه، ولكل مستلمٍ مرة، والمكرّر بعد نصف ساعة لا قبلها، وحدّ الساعة، وما لم يصل بسببه ويُحفظ مع البلاغ،
    ورقم المدير؛ وعلى خادمٍ حيّ بخدمة واتساب وهمية: يصل الموظف والمدير من رقم المسابقة، والموقوف لا يصله، والتجربة.
  - على خادم حيّ: الصفحة العامة وواجهاتها والإرسال، وصلاحيات الموظف (المدير، ومن فُتحت له، ومن لم تُفتح له)،
    وتحويل الموظف بلا بوابات إلى البلاغات، والخيار في الحساب.

تشغيل:  python tests/test_reports.py
"""
import base64
import http.cookiejar
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import content as C  # noqa: E402
import reports as R  # noqa: E402


def _offline(xt, action):
    raise urllib.error.URLError("offline test")


C._api_open = _offline          # بلا إنترنت: لا إثراء من واجهة Xtream

_p = _f = 0


def check(label, cond, extra=""):
    global _p, _f
    print((f"  \033[32mPASS\033[0m  {label}" if cond else f"  \033[31mFAIL\033[0m  {label}") + (f"  ({extra})" if extra else ""))
    _p += 1 if cond else 0
    _f += 0 if cond else 1


HOST = "http://panel.example:8080"


def entry(title, group, kind="live", n=1):
    path = {"live": f"live/u/p/{n}.ts", "movie": f"movie/u/p/{n}.mkv", "series": f"series/u/p/{n}.mkv"}[kind]
    return f'#EXTINF:-1 tvg-logo="https://image.tmdb.org/t/p/w600/x{n}.jpg" group-title="{group}",{title}\n{HOST}/{path}\n'


SAMPLE = ("#EXTM3U\n"
          + entry("AR: MBC 1 HD", "AR | MBC", n=1)
          + entry("The Batman (2022)", "VOD | English Movies", "movie", 2)
          + entry("Dune (2021)", "VOD | English Movies", "movie", 3)
          + entry("Dune (1984)", "VOD | English Movies", "movie", 4)
          + entry("Breaking Bad S01 E01", "SERIES | Drama", "series", 5)
          + entry("Breaking Bad S01 E02", "SERIES | Drama", "series", 6)
          + entry("Breaking Bad S02 E01", "SERIES | Drama", "series", 7)
          + entry("المؤسس عثمان الموسم ٥ الحلقة ١٢", "مسلسلات تركية", "series", 8)
          + entry("المؤسس عثمان الموسم الخامس الحلقة 13", "مسلسلات تركية", "series", 9)
          + entry("قيامة أرطغرل الحلقة 45", "مسلسلات تركية", "series", 10)
          + entry("Hidden Show S01 E01", "Hidden Group", "series", 11))


def fresh():
    d = tempfile.mkdtemp(prefix="reports_")
    for x in (C._cache, C._sums, C._files, C._found, C._busy):
        x.clear()
    R._rate.clear()
    return d


def seed(d, key="smart", text=SAMPLE):
    return C.ingest(d, key, io.BytesIO(text.encode("utf-8")).read, "file", "sample.m3u")


def gid(d, kind, name, key="smart"):
    return next(g["id"] for g in R.groups(d, key)["kinds"][kind] if g["name"] == name)


def od(c):
    """(المفتوحة، المنجزة) من أعداد الصفحة — ومعها أعداد المشاكل والطلبات."""
    return c.get("open"), c.get("done")


def raises(fn, *a, **k):
    try:
        fn(*a, **k)
    except R.Invalid as e:
        return str(e)
    return ""


def unit_steps():
    print("الخطوات: السيرفر ← القسم ← العنصر، والبحث")
    d = fresh()
    check("بلا محتوى: لا سيرفرات", R.servers(d) == {"ok": True, "servers": []})
    seed(d)
    check("السيرفر الذي له محتوى وحده", R.servers(d)["servers"] == [{"key": "smart", "name": "سمارت", "en": "Smart"}], R.servers(d))
    check("سيرفرٌ بلا محتوى أو مفتاحٌ غريب ← None", R.groups(d, "kon") is None and R.groups(d, "../x") is None)
    hidden = next(g for g in R.groups(d, "smart")["kinds"]["series"] if g["name"] == "Hidden Group")
    C.set_hidden(d, "smart", hidden["id"], True)
    g = R.groups(d, "smart")
    names = {k: [(x["name"], x["n"]) for x in v] for k, v in g["kinds"].items()}
    check("الأقسام الظاهرة لكل نوع بعدد ما فيها، بلا ما أخفاه المدير",
          names == {"series": [("SERIES | Drama", 1), ("مسلسلات تركية", 2)], "movie": [("VOD | English Movies", 3)],
                    "live": [("AR | MBC", 1)]}, names)
    check("ولا يُبلَّغ عن قسمٍ مخفي", R.items(d, "smart", "series", hidden["id"]) is None)
    tr = gid(d, "series", "مسلسلات تركية")
    it = R.items(d, "smart", "series", tr)
    osman = next(x for x in it["items"] if x["n"] == "المؤسس عثمان")
    check("عناصر القسم بمواسمها وحلقاتها وصورتها", it["group"]["name"] == "مسلسلات تركية" and it["total"] == 2
          and osman["s"] == [[5, 2]] and osman["p"].startswith("https://image.tmdb.org/t/p/w185/"), it)
    check("والتصفية بالاسم", [x["n"] for x in R.items(d, "smart", "series", tr, "ارطغرل")["items"]] == ["قيامة أرطغرل"])
    mv = gid(d, "movie", "VOD | English Movies")
    old = R.ITEMS_PAGE
    R.ITEMS_PAGE = 2
    try:
        p0, p1 = R.items(d, "smart", "movie", mv), R.items(d, "smart", "movie", mv, page="1")
        check("وبصفحاتٍ مع «المزيد»", len(p0["items"]) == 2 and p0["more"] and len(p1["items"]) == 1 and not p1["more"]
              and p0["total"] == 3)
        check("ورقم صفحةٍ غريب ← الأولى", R.items(d, "smart", "movie", mv, page="abc")["items"] == p0["items"])
    finally:
        R.ITEMS_PAGE = old
    check("ونوعٌ أو قسمٌ غريب ← None", R.items(d, "smart", "bad", mv) is None and R.items(d, "smart", "movie", "nope") is None)
    s = R.search(d, "smart", "breaking")
    check("البحث بالاسم في السيرفر كله، ومعه نوعه وقسمه", len(s["items"]) == 1 and s["items"][0]["k"] == "series"
          and s["items"][0]["g"] == "SERIES | Drama" and s["items"][0]["gid"] == gid(d, "series", "SERIES | Drama")
          and s["items"][0]["s"] == [[1, 2], [2, 1]], s)
    check("والقنوات لا تدخل البحث", R.search(d, "smart", "MBC")["items"] == [])
    check("وكلمةٌ من حرفٍ واحد: لا شيء", R.search(d, "smart", "b") == {"ok": True, "total": 0, "items": []})
    seed(d, "casper", "#EXTM3U\n" + entry("Osman S01 E01", "تركي مترجم", "series", 1) + entry("Osman S01 E02", "تركي مترجم", "series", 2)
         + entry("Osman S01 E01", "تركي مدبلج", "series", 3) + entry("Osmanli (2020)", "أفلام تركية", "movie", 4))
    s2 = R.search(d, "casper", "osman")
    check("والاسم في قسمين نتيجتان بقسميهما (المدبلج والمترجم)، والمطابق تمامًا أولًا",
          [(x["n"], x["g"]) for x in s2["items"]] == [("Osman", "تركي مترجم"), ("Osman", "تركي مدبلج"), ("Osmanli", "أفلام تركية")]
          and s2["total"] == 3, s2)
    rec = R.recent(d, "casper")
    check("وأحدث ما أضيف قبل الكتابة (الأكبر رقمًا أولًا)", [(x["n"], x["k"]) for x in rec["items"]][:2] == [("Osmanli", "movie"), ("Osman", "series")]
          and all("gid" in x and "g" in x for x in rec["items"]), rec)
    check("وسيرفرٌ بلا محتوى ← None", R.recent(d, "kon") is None and R.search(d, "kon", "x") is None)
    ex = lambda *a: [(x["n"], x["k"], x.get("y") or 0) for x in R.exists(d, *a)["items"]]  # noqa: E731
    check("موجودٌ في السيرفر؟ الاسم نفسه بنوعه وقسمه", ex("smart", "breaking bad") == [("Breaking Bad", "series", 0)]
          and R.exists(d, "smart", "Breaking Bad")["items"][0]["gid"] == gid(d, "series", "SERIES | Drama"))
    check("وبنوعه إن عُرف (المسلسل ليس فيلمًا)", ex("smart", "Breaking Bad", "movie") == [])
    check("وبلا «The» أوله، وبسنته", ex("smart", "Batman", "movie") == [("The Batman", "movie", 2022)]
          and ex("smart", "the batman", "", "2022") == [("The Batman", "movie", 2022)])
    check("وبسنته: «Dune» 2021 لا 1984، وفرق سنةٍ يُقبل، وبلا سنةٍ كلاهما",
          ex("smart", "Dune", "movie", 2021) == [("Dune", "movie", 2021)] and ex("smart", "Dune", "", "2020") == [("Dune", "movie", 2021)]
          and ex("smart", "Dune", "movie", 1990) == [] and sorted(y for _, _, y in ex("smart", "Dune")) == [1984, 2021])
    check("وجزءٌ من الاسم ليس هو", ex("smart", "Break") == [] and ex("smart", "Breaking Bad 2") == [])
    check("وبلا همزات (قيامة ارطغرل)", ex("smart", "قيامة ارطغرل") == [("قيامة أرطغرل", "series", 0)])
    e2 = R.exists(d, "casper", "Osman")
    check("وفي قسمين: كلاهما", e2["total"] == 2 and [x["g"] for x in e2["items"]] == ["تركي مترجم", "تركي مدبلج"], e2)
    check("واسمٌ من حرفٍ وسيرفرٌ بلا محتوى", R.exists(d, "smart", "D") == {"ok": True, "total": 0, "items": []}
          and R.exists(d, "kon", "Dune") is None)
    return d


def unit_submit():
    print("البلاغ")
    d = fresh()
    seed(d)
    drama = gid(d, "series", "SERIES | Drama")
    mv = gid(d, "movie", "VOD | English Movies")
    live = gid(d, "live", "AR | MBC")
    base = {"s": "smart", "t": "series", "g": drama, "n": "Breaking Bad", "season": 2, "ep": 1, "problem": "down"}
    r, new = R.submit(d, dict(base, phone="0551234567", note="شاشة سوداء"), now=1000)
    check("بلاغٌ جديد بما في الفهرس", new and r["count"] == 1 and r["state"] == "open" and r["title"] == "Breaking Bad"
          and r["season"] == 2 and r["ep"] == 1 and r["sname"] == "سمارت" and r["group"] == "SERIES | Drama"
          and r["people"] == [{"at": 1000, "phone": "966551234567", "note": "شاشة سوداء", "lang": "ar"}] and r["lang"] == "ar"
          and r["sname_en"] == "Smart", r)
    check("ونصّه للموظف", R.label(r) == "Breaking Bad · الموسم 2 · الحلقة 1 — لا يعمل", R.label(r))
    r2, new2 = R.submit(d, dict(base, n="breaking  bad", phone="+966 55 123 4567"), now=1100)
    check("المكرّر المفتوح يزيد عدده ولا يتكرّر (والرقم نفسه مرة)", not new2 and r2["id"] == r["id"] and r2["count"] == 2
          and len(r2["people"]) == 1 and r2["last"] == 1100)
    r3, _ = R.submit(d, dict(base, phone="٠٥٠٠٠٠٠٠٠١"), now=1200)
    check("ورقمٌ آخر (بالأرقام الهندية) يُضاف", r3["count"] == 3 and r3["people"][-1]["phone"] == "966500000001")
    r4, new4 = R.submit(d, dict(base, problem="buffer"), now=1300)
    check("والمشكلة الأخرى بلاغٌ آخر، بلا رقمٍ ولا أصحاب", new4 and r4["id"] != r["id"] and r4["people"] == [])
    r5, _ = R.submit(d, dict(base, ep=0), now=1400)
    check("و«كل الحلقات» (‏0)", R.label(r5) == "Breaking Bad · الموسم 2 · كل الحلقات — لا يعمل")
    tr = gid(d, "series", "مسلسلات تركية")
    r6, _ = R.submit(d, {"s": "smart", "t": "series", "g": tr, "n": "قيامة أرطغرل", "season": 0, "ep": 45, "problem": "buffer"})
    check("ومسلسلٌ بلا رقم موسم بحلقةٍ فوق عدد حلقاته", R.label(r6) == "قيامة أرطغرل · الحلقة 45 — يقطع", R.label(r6))
    m, _ = R.submit(d, {"s": "smart", "t": "movie", "g": mv, "n": "Dune", "y": 1984, "problem": "down"})
    check("الفيلم بسنته بين المتشابهين، بلا موسمٍ ولا حلقة", m["year"] == 1984 and m["season"] is None and m["ep"] is None
          and R.label(m) == "Dune (1984) — لا يعمل")
    c, _ = R.submit(d, {"s": "smart", "t": "live", "g": live, "n": "MBC 1", "problem": "buffer"})
    check("والقناة", R.label(c) == "MBC 1 — يقطع" and c["kind"] == "live")
    bad = {
        "سيرفرٌ غريب": (dict(base, s="nope"), "اختر السيرفر"),
        "قسمٌ غريب": (dict(base, g="zzz"), "اختر القسم"),
        "نوعٌ غريب": (dict(base, t="radio"), "اختر القسم"),
        "اسمٌ ليس في القسم": (dict(base, n="The Wire"), "اختر المسلسل"),
        "موسمٌ ليس فيه": (dict(base, season=7), "اختر الموسم"),
        "بلا حلقة": (dict(base, ep=None), "اختر الحلقة"),
        "حلقةٌ غريبة": (dict(base, ep="x"), "اختر الحلقة"),
        "مشكلةٌ غريبة": (dict(base, problem="slow"), "اختر المشكلة"),
        "رقمٌ بحروف": (dict(base, phone="05abc"), "أرقامٌ فقط"),
        "رقمٌ قصير": (dict(base, phone="1234"), "غير صحيح"),
        "ليس قاموسًا": ([1, 2], "اختر السيرفر"),
    }
    for name, (form, want) in bad.items():
        msg = raises(R.submit, d, form)
        check(f"يُرفض: {name}", want in msg, msg)
    long, _ = R.submit(d, dict(base, season=1, ep=2, note="x" * 900 + "‮"))
    check("والملاحظة بحدّها بلا رموز الاتجاه", long["people"][0]["note"] == "x" * R.NOTE_MAX)
    check("<script> في الملاحظة نصٌّ كما هو (الصفحة تهرّبه)",
          R.submit(d, dict(base, season=1, ep=1, note="<b>hi</b>"))[0]["people"][0]["note"] == "<b>hi</b>")
    return d


def unit_staff():
    print("الموظف")
    d = fresh()
    seed(d)
    seed(d, "falcon", "#EXTM3U\n" + entry("Kon Show S01 E01", "Drama", "series", 1))
    drama = gid(d, "series", "SERIES | Drama")
    base = {"s": "smart", "t": "series", "g": drama, "n": "Breaking Bad", "season": 1, "ep": 1, "problem": "down"}
    a, _ = R.submit(d, dict(base, phone="0551234567"), now=100)
    b, _ = R.submit(d, dict(base, ep=2), now=200)
    f, _ = R.submit(d, {"s": "falcon", "t": "series", "g": gid(d, "series", "Drama", "falcon"), "n": "Kon Show",
                        "season": 1, "ep": 1, "problem": "buffer"}, now=300)
    ls = R.listing(d)
    check("المفتوحة الأحدث أولًا بأعدادها ولكل سيرفر", [x["id"] for x in ls["items"]] == [f["id"], b["id"], a["id"]]
          and od(ls["counts"]) == (3, 0) and ls["servers"] == [
              {"key": "smart", "name": "سمارت", "open": 2}, {"key": "falcon", "name": "فالكون", "open": 1}]
          and ls["items"][0]["label"] == "Kon Show · الموسم 1 · الحلقة 1 — يقطع", ls)
    check("وتصفيتها بالسيرفر", [x["id"] for x in R.listing(d, server="falcon")["items"]] == [f["id"]])
    done = R.set_state(d, a["id"], True, "سارة", now=500)
    check("«تم الإصلاح» بمن ومتى", done["state"] == "done" and done["done_by"] == "سارة" and done["done_at"] == 500)
    ls = R.listing(d)
    check("فتخرج من المفتوحة إلى المنجزة", od(ls["counts"]) == (2, 1)
          and [x["id"] for x in R.listing(d, "done")["items"]] == [a["id"]] and len(R.listing(d, "all")["items"]) == 3)
    again, new = R.submit(d, dict(base, phone="0500000002"), now=600)
    check("وبلاغٌ جديدٌ بمثله بعد إصلاحه بلاغٌ جديد", new and again["id"] != a["id"])
    back = R.set_state(d, a["id"], False)
    check("وإعادة فتح القديم تضمّه إلى المفتوح مثله (العدد والأرقام)", back["id"] == again["id"] and back["count"] == 2
          and sorted(p["phone"] for p in back["people"]) == ["966500000002", "966551234567"]
          and all(x["id"] != a["id"] for x in R.listing(d, "all")["items"]))
    check("وبلاغٌ لا وجود له ← None", R.set_state(d, "nope", True) is None)
    check("والحذف", R.remove(d, b["id"]) and not R.remove(d, b["id"])
          and all(x["id"] != b["id"] for x in R.listing(d, "all")["items"]))
    check("وعدد المفتوحة", R.open_count(d) == 2)
    mine = R.listing(d, "all", only={"falcon"})
    check("وموظف سيرفرٍ لا يرى غيره ولا يُعدّ له", [x["server"] for x in mine["items"]] == ["falcon"]
          and od(mine["counts"]) == (1, 0) and [x["key"] for x in mine["servers"]] == ["falcon"], mine["counts"])
    check("وبلا سيرفرات (‏only فارغة): لا شيء", R.listing(d, "all", only=set())["items"] == [])
    check("والبلاغ برقمه لمعرفة سيرفره", R.get(d, f["id"])["server"] == "falcon" and R.get(d, "nope") is None)
    old = R.KEEP
    R.KEEP = 3
    try:
        R.set_state(d, f["id"], True)
        for ep in (5, 6, 7):
            R.submit(d, dict(base, ep=ep))
        rows = R.listing(d, "all")["items"]
        check("وحدّ الحفظ يُسقط المنجز الأقدم أولًا", len(rows) == 3 and all(x["state"] == "open" for x in rows)
              and f["id"] not in {x["id"] for x in rows})
    finally:
        R.KEEP = old
    R._rate.clear()
    check("الحدّ بالساعة لكل عنوان", all(R.rate_ok("1.2.3.4", 3, now=7200) for _ in range(3))
          and not R.rate_ok("1.2.3.4", 3, now=7300) and R.rate_ok("5.6.7.8", 3, now=7300)
          and R.rate_ok("1.2.3.4", 3, now=10900) and R.rate_ok("", 0))
    check("ولا يُحفظ العنوان نفسه", not any("1.2.3.4" in k for k in R._rate))


def unit_more():
    print("«الحلقة ليست هي» و«الترجمة غير صحيحة»، وطلب الإضافة")
    d = fresh()
    seed(d)
    drama = gid(d, "series", "SERIES | Drama")
    mv = gid(d, "movie", "VOD | English Movies")
    base = {"s": "smart", "t": "series", "g": drama, "n": "Breaking Bad", "season": 2, "ep": 1}
    w, _ = R.submit(d, dict(base, problem="wrong"), now=100)
    sub, _ = R.submit(d, dict(base, problem="subs"), now=110)
    check("«الحلقة ليست هي» و«الترجمة غير صحيحة» للمسلسل", R.label(w) == "Breaking Bad · الموسم 2 · الحلقة 1 — الحلقة ليست هي"
          and R.label(sub) == "Breaking Bad · الموسم 2 · الحلقة 1 — الترجمة غير صحيحة", (R.label(w), R.label(sub)))
    m, _ = R.submit(d, {"s": "smart", "t": "movie", "g": mv, "n": "Dune", "y": 2021, "problem": "wrong"}, now=120)
    check("و«الفيلم ليس هو» للفيلم", R.label(m) == "Dune (2021) — الفيلم ليس هو" and R.problem_name("wrong", "live") == "القناة ليست هي")
    req, new = R.submit(d, {"s": "smart", "t": "series", "n": "  Shōgun   (2024) ", "problem": "add", "phone": "0551234567",
                            "note": "الموسم الجديد"}, now=130)
    check("طلب إضافة: الاسم كما كتبه، بلا قسمٍ ولا حلقةٍ ولا صورة", new and req["problem"] == "add" and req["title"] == "Shōgun (2024)"
          and req["group"] == "" and req["season"] is None and req["ep"] is None and req["p"] == ""
          and R.label(req) == "Shōgun (2024) — طلب إضافة مسلسل", req)
    again, new2 = R.submit(d, {"s": "smart", "t": "series", "n": "shōgun (2024)", "problem": "add", "phone": "0500000001"}, now=140)
    check("وطلبه مرةً أخرى يزيد عدده ورقمه", not new2 and again["id"] == req["id"] and again["count"] == 2 and len(again["people"]) == 2)
    mreq, new3 = R.submit(d, {"s": "smart", "t": "movie", "n": "Shōgun (2024)", "problem": "add"}, now=150)
    check("والفيلم بالاسم نفسه طلبٌ آخر", new3 and R.label(mreq) == "Shōgun (2024) — طلب إضافة فيلم")
    for name, (form, want) in {"نوعٌ غير مسلسلٍ أو فيلم": ({"t": "live", "n": "MBC"}, "مسلسل أو فيلم"),
                               "بلا اسم": ({"t": "series", "n": " ا "}, "اكتب اسم"),
                               "بلا سيرفر": ({"s": "nope", "t": "series", "n": "Shogun"}, "اختر السيرفر")}.items():
        msg = raises(R.submit, d, dict({"s": "smart", "problem": "add"}, **form))
        check(f"طلبٌ يُرفض: {name}", want in msg, msg)
    ls = R.listing(d)
    check("وعدد المشاكل والطلبات المفتوحة معًا", ls["counts"]["issue"] == 3 and ls["counts"]["add"] == 2 and len(ls["items"]) == 5
          and next(x for x in ls["items"] if x["id"] == m["id"])["ptext"] == "الفيلم ليس هو", ls["counts"])
    only = R.listing(d, what="add")
    check("وتصفية طلبات الإضافة وحدها", [x["problem"] for x in only["items"]] == ["add", "add"] and only["counts"]["open"] == 2
          and R.listing(d, what="issue")["counts"]["open"] == 3 and all(x["problem"] != "add" for x in R.listing(d, what="issue")["items"]))
    t = R.alert_text(R.get(d, req["id"]), True)
    check("وتنبيه الطلب: النوع والسيرفر والاسم، بلا رقم من طلبه", t == "🙋 *طلب إضافة مسلسل في سمارت*\n\n\u200f🎬 Shōgun (2024)", t)
    check("ومكرّره بعدده", R.alert_text(R.get(d, req["id"]), False).startswith("🔁 *طلب إضافة مسلسل في سمارت* — طلبه 2 مشتركين"))
    check("وتنبيه «الحلقة ليست هي»", R.alert_text(w, True).startswith("🔔 *بلاغ جديد في سمارت: الحلقة ليست هي*"))


def unit_notify_lang():
    print("رسالةٌ لأصحاب البلاغ، والإنجليزية")
    d = fresh()
    seed(d)
    drama = gid(d, "series", "SERIES | Drama")
    base = {"s": "smart", "t": "series", "g": drama, "n": "Breaking Bad", "season": 2, "ep": 1, "problem": "down"}
    r, _ = R.submit(d, dict(base, phone="0551234567", lang="en"), now=100)
    R.submit(d, dict(base, phone="0500000001"), now=110)
    R.submit(d, dict(base, phone="0551234567", note="again"), now=120)
    check("لغة صفحة المشترك مع بلاغه (وأولها للبلاغ)", r["lang"] == "en" and R.get(d, r["id"])["people"][0]["lang"] == "en"
          and R.get(d, r["id"])["people"][1]["lang"] == "ar")
    for form, en in [(dict(base, season=9), "Choose the season"), (dict(base, problem="x"), "Choose the problem"),
                     (dict(base, phone="12"), "Invalid WhatsApp number"), ({"s": "smart", "problem": "add", "t": "live", "n": "x"}, "Choose: series or movie")]:
        try:
            R.submit(d, form)
            check(f"خطأٌ بالإنجليزية: {en}", False)
        except R.Invalid as e:
            check(f"خطأٌ بالإنجليزية: {en}", e.en.startswith(en) and str(e) != e.en, e.en)
    sent = []
    R.sender = lambda to, text: sent.append((to, text)) or ({"ok": False, "error": "الرقم ليس على واتساب"} if to == "966500000001" else {"ok": True})
    try:
        up = R.notify(d, r["id"], "  تم الإصلاح ✅  \n\n\n\n جرّبه الآن\u202e  ", "سارة", now=500)
        check("الرسالة لكل رقمٍ مرة، بأسطرها بلا رموز الاتجاه", sorted(x[0] for x in sent) == ["966500000001", "966551234567"]
              and sent[0][1] == "تم الإصلاح ✅\n\nجرّبه الآن" and up["to"] == 2 and up["sent"] == 1 and up["by"] == "سارة", (up, sent))
        check("وما لم يصل بسببه ورقمه", up["error"] == "+966500000001: الرقم ليس على واتساب", up["error"])
        check("وتُحفظ مع البلاغ", R.get(d, r["id"])["updates"] == [up])
        check("وبلا نصٍّ تُرفض", "اكتب نصّ الرسالة" in raises(R.notify, d, r["id"], " \n "))
        r2, _ = R.submit(d, dict(base, ep=2), now=600)
        check("وبلاغٌ بلا أرقام: لا رسالة", "لا أرقام" in raises(R.notify, d, r2["id"], "x"))
        check("وبلاغٌ لا وجود له", "لا بلاغ" in raises(R.notify, d, "nope", "x"))
        R.sender = lambda to, text: sent.append((to, text)) or {"ok": True}
        for i in range(R.UPDATES_KEEP + 3):
            R.notify(d, r["id"], f"update {i}", now=700 + i)
        check("ويُحفظ آخرها بحدّ", len(R.get(d, r["id"])["updates"]) == R.UPDATES_KEEP
              and R.get(d, r["id"])["updates"][-1]["text"] == f"update {R.UPDATES_KEEP + 2}")
        # التنبيه بلغة كل موظف
        sent.clear()
        R.recipients = lambda rep: [("سارة", "966500000001"), ("John", "966500000002", "en"), ("Ali", "966500000003", "ar")]
        R._alerts.clear()
        R.alert(d, R.get(d, r["id"]), True, now=900)
        by = {to: text for to, text in sent}
        check("التنبيه بلغة كل موظف (والعربية افتراضًا)", by["966500000001"].startswith("🔔 *بلاغ جديد في سمارت: لا يعمل*")
              and by["966500000003"] == by["966500000001"]
              and by["966500000002"] == "🔔 *New report on Smart: Not working*\n\n🎬 Breaking Bad · S2 · E1\n📂 series · SERIES | Drama",
              by.get("966500000002"))
        q, _ = R.submit(d, {"s": "smart", "t": "movie", "n": "Oppenheimer", "problem": "add"}, now=950)
        check("وطلب الإضافة بالإنجليزية", R.alert_text(q, True, "en") == "🙋 *Request to add a movie on Smart*\n\n🎬 Oppenheimer"
              and R.problem_name("wrong", "movie", "en") == "Wrong movie")
    finally:
        R.sender = R.recipients = None
    check("ولغة المدير", R.save_lang(d, "en")["lang"] == "en" and R.settings(d)["lang"] == "en" and R.settings(d)["wa"] == "")


IMDB_PAGE = """<html><head><title>Breaking Bad (TV Series 2008–2013) - IMDb</title>
<meta property="og:title" content="Breaking Bad (TV Series 2008–2013) ⭐ 9.5 | Crime, Drama, Thriller">
<meta property="og:type" content="video.tv_show">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"TVSeries","name":"Breaking Bad","datePublished":"2008-01-20"}</script>
</head><body><li data-testid="title-details-languages"><span>Languages</span><ul><li><a href="/x">English</a></li><li><a>Spanish</a></li></ul></li></body></html>"""
TMDB_PAGE = """<html><head><title>Dune (2021) — The Movie Database (TMDB)</title><meta property="og:title" content="Dune">
<meta property="og:type" content="video.movie"></head><body><p><strong><bdi>Original Language</bdi></strong> English</p></body></html>"""


def unit_link():
    print("رابط المسلسل أو الفيلم في طلب الإضافة، والسنة واللغة")
    cases = {
        "IMDb: مسلسل بسنته ولغته (JSON-LD وصفحة اللغات)": (IMDB_PAGE, "https://www.imdb.com/title/tt0903747/",
                                                         {"kind": "series", "name": "Breaking Bad", "year": 2008, "lang": "en"}),
        "TMDB: فيلم من رابطه، وسنته من <title>، ولغته الأصلية": (TMDB_PAGE, "https://www.themoviedb.org/movie/438631-dune",
                                                              {"kind": "movie", "name": "Dune", "year": 2021, "lang": "en"}),
        "JSON-LD قائمةً بلغةٍ رمزًا": ('<meta property="og:title" content="Squid Game"><script type="application/ld+json">'
                                    '[{"@type":"WebPage"},{"@type":["TVSeries"],"name":"Squid Game","startDate":"2021-09-17","inLanguage":"ko-KR"}]</script>',
                                    "https://www.netflix.com/title/81040344", {"kind": "series", "name": "Squid Game", "year": 2021, "lang": "ko"}),
        "عنوانٌ عربي بنوعه وسنته بين قوسين": ('<title>المؤسس عثمان (مسلسل 2019) - ويكيبيديا</title>', "https://ar.wikipedia.org/wiki/x",
                                          {"kind": "series", "name": "المؤسس عثمان", "year": 2019, "lang": ""}),
        "صفحةٌ بلا شيء": ("<html><body>hi</body></html>", "https://example.com/", {"kind": "", "name": "", "year": 0, "lang": ""}),
    }
    for name, (html, url, want) in cases.items():
        got = R.parse_page(html, url)
        check(name, got == want, got)
    for bad in ("javascript:alert(1)", "ftp://x.com/a", "https://exa mple.com", "https://x.com/" + "a" * 500, "x.com/a", 'https://x.com/"><b>'):
        check(f"رابطٌ يُرفض: {bad[:30]}", "الرابط غير صحيح" in raises(R.link_of, bad))
    check("والفارغ لا رابط", R.link_of("  ") == "")
    ids = {"https://www.imdb.com/title/tt0111161/?ref_=ext_shr": "tt0111161", "https://m.imdb.com/title/tt0903747": "tt0903747",
           "https://www.imdb.com/ar/title/tt4320258/reviews/": "tt4320258", "https://imdb.com/title/tt10919420/": "tt10919420",
           "https://www.imdb.com/name/nm0000151/": "", "https://notimdb.com/title/tt0111161/": "", "https://www.themoviedb.org/movie/278": ""}
    got = {u: R.imdb_id(u) for u in ids}
    check("رقم IMDb من رابطه (‏www وm والمترجم ورابط المشاركة)، ولا غيره", got == ids, got)
    slugs = {"https://www.themoviedb.org/movie/278-the-shawshank-redemption": ("movie", "The Shawshank Redemption", 0),
             "https://letterboxd.com/film/dune-2021/": ("movie", "Dune", 2021),
             "https://www.themoviedb.org/tv/1396-breaking-bad/season/1": ("series", "Breaking Bad", 0),
             "https://shahid.mbc.net/ar/series/%D9%85%D8%B3%D9%84%D8%B3%D9%84-%D8%A7%D9%84%D9%87%D9%8A%D8%A8%D8%A9/series-49923": ("series", "الهيبة", 0),
             "https://example.com/films/Oppenheimer.html": ("movie", "Oppenheimer", 0)}
    got = {u: (lambda g: g and (g["kind"], g["name"], g["year"]))(R.from_slug(u)) for u in slugs}
    check("وما لا تُقرأ صفحته: اسمه ممّا في الرابط (‏TMDB وLetterboxd وشاهد)", got == slugs, got)
    nones = ["https://www.netflix.com/sa-en/title/80057281", "https://www.youtube.com/watch?v=abc", "https://x.com/",
             "https://x.com/movie/v/a8f3k29dk3m2", "https://example.com/watch/Oppenheimer.html", "https://x.com/news/some-page"]
    check("ولا اسم من رابطٍ بأرقامٍ أو معرّفٍ وحده، ولا من رابطٍ ليس لمسلسلٍ أو فيلم", [R.from_slug(u) for u in nones] == [None] * 6,
          [R.from_slug(u) for u in nones])
    d = fresh()
    seed(d)
    r, _ = R.submit(d, {"s": "smart", "t": "series", "n": "Breaking Bad", "y": "2008", "cl": "en", "problem": "add",
                        "link": " https://www.imdb.com/title/tt0903747/ "})
    check("طلبٌ بسنته ولغته ورابطه", r["year"] == 2008 and r["cl"] == "en" and r["link"] == "https://www.imdb.com/title/tt0903747/"
          and R.label(r) == "Breaking Bad (2008) — طلب إضافة مسلسل", r)
    r2, _ = R.submit(d, {"s": "smart", "t": "movie", "n": "Dune", "y": "abc", "cl": "xx", "problem": "add"})
    check("وسنةٌ أو لغةٌ غريبة تُترك", r2["year"] == 0 and r2["cl"] == "" and r2["link"] == "")
    check("ورابطٌ غريب يُرفض", "الرابط غير صحيح" in raises(R.submit, d, {"s": "smart", "t": "movie", "n": "Dune", "problem": "add",
                                                                        "link": "javascript:x"}))
    t = R.alert_text(R.get(d, r["id"]), True)
    check("والتنبيه بلغته ورابطه", "\u200f🌐 إنجليزي" in t and "🔗 https://www.imdb.com/title/tt0903747/" in t, t)
    check("وبالإنجليزية", "🌐 English" in R.alert_text(R.get(d, r["id"]), True, "en"))
    # قراءة الرابط من خادمٍ وهمي محلي (والعناوين الداخلية مرفوضةٌ في غير الاختبار)
    import http.server
    import threading

    class Page(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            js = "application/json"
            body, ctype, code = {"/title/tt0903747/": (IMDB_PAGE, "text/html; charset=utf-8", 200),
                                 "/img.png": ("PNG", "image/png", 200),
                                 "/imdb/tt0111161.json": (json.dumps({"d": [
                                     {"id": "tt0111161", "l": "The Shawshank Redemption", "q": "feature", "qid": "movie", "y": 1994},
                                     {"id": "tt16970392", "l": "x", "qid": "tvEpisode"}]}), js, 200),
                                 "/imdb/tt0903747.json": (json.dumps({"d": [{"id": "tt0903747", "l": "Breaking Bad", "qid": "tvSeries",
                                                                             "y": 2008}]}), js, 200),
                                 "/imdb/tt0959621.json": (json.dumps({"d": [{"id": "tt0959621", "l": "Pilot", "qid": "tvEpisode",
                                                                             "y": 2008}]}), js, 200),
                                 "/tvmaze/tt0903747": (json.dumps({"name": "Breaking Bad", "language": "English"}), js, 200),
                                 "/sparql": (json.dumps({"results": {"bindings": [{"c3": {"value": "nap"}}, {"c2": {"value": "en"}}]}}),
                                             js, 200),
                                 }.get(self.path.split("?")[0], ("nope", "text/html", 404))
            raw = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Page)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        check("عنوانٌ داخلي مرفوض (لا يُطلب من خادمنا)", not R.lookup(base + "/title/tt0903747/")["ok"])
        old, C.IMG_PRIVATE = C.IMG_PRIVATE, True
        try:
            got = R.lookup(base + "/title/tt0903747/")
            check("قراءة الرابط: النوع والاسم والسنة واللغة", got == {"ok": True, "kind": "series", "name": "Breaking Bad", "year": 2008,
                                                                    "lang": "en"}, got)
            check("وصفحةٌ لا وجود لها أو ليست HTML: تعذّر", not R.lookup(base + "/missing")["ok"] and not R.lookup(base + "/img.png")["ok"])
            check("ورابطٌ غريب برسالته بالإنجليزية", R.lookup("javascript:1")["en"].startswith("Invalid link"))
            got = R.lookup(base + "/movie/278-the-shawshank-redemption")
            check("وصفحةٌ لا تُقرأ: الاسم ممّا في الرابط (‏guess: ليُراجع)", got == {"ok": True, "guess": True, "kind": "movie",
                                                                                 "name": "The Shawshank Redemption", "year": 0, "lang": ""}, got)
            apis = (R.IMDB_API, R.TVMAZE_API, R.WIKIDATA_API)
            R.IMDB_API, R.TVMAZE_API, R.WIKIDATA_API = base + "/imdb/{id}.json", base + "/tvmaze/{id}", base + "/sparql"
            try:
                got = R.lookup("https://www.imdb.com/title/tt0111161/?ref_=ext_shr")
                check("رابط IMDb (ومشاركة تطبيقه): من بياناته العامة لا صفحته، ولغة الفيلم من Wikidata",
                      got == {"ok": True, "kind": "movie", "name": "The Shawshank Redemption", "year": 1994, "lang": "en"}, got)
                got = R.lookup("https://m.imdb.com/title/tt0903747/")
                check("والمسلسل بنوعه، ولغته من TVmaze", got == {"ok": True, "kind": "series", "name": "Breaking Bad", "year": 2008,
                                                               "lang": "en"}, got)
                check("وحلقةٌ وحدها لا يُعرف منها المسلسل", R._imdb("tt0959621") is None)
                R.TVMAZE_API = R.WIKIDATA_API = base + "/missing"
                got = R.lookup("https://www.imdb.com/title/tt0903747/")
                check("ولغةٌ لا تُعرف تُترك له", got == {"ok": True, "kind": "series", "name": "Breaking Bad", "year": 2008, "lang": ""}, got)
            finally:
                R.IMDB_API, R.TVMAZE_API, R.WIKIDATA_API = apis
        finally:
            C.IMG_PRIVATE = old
    finally:
        srv.shutdown()
    R._lookups.clear()
    check("وحدّ قراءة الروابط بالساعة", all(R.lookup_ok("1.1.1.1", now=3600) for _ in range(R.LOOKUP_RATE))
          and not R.lookup_ok("1.1.1.1", now=3700) and R.lookup_ok("2.2.2.2", now=3700))


def unit_alert():
    print("تنبيه واتساب")
    d = fresh()
    seed(d)
    drama = gid(d, "series", "SERIES | Drama")
    base = {"s": "smart", "t": "series", "g": drama, "n": "Breaking Bad", "season": 2, "ep": 1, "problem": "down"}
    r, new = R.submit(d, dict(base, phone="0551234567", note="شاشة *سوداء*"), now=1000)
    txt = R.alert_text(r, True)
    check("نصّ التنبيه: المشكلة والسيرفر، والاسم والحلقة، والقسم — بلا رقم صاحبه ولا ملاحظته ولا رابط", txt == (
        "🔔 *بلاغ جديد في سمارت: لا يعمل*\n\n\u200f🎬 Breaking Bad · الموسم 2 · الحلقة 1\n\u200f📂 مسلسل · SERIES | Drama"), txt)
    check("وكل الحلقات", R.alert_text(dict(r, ep=None), True).endswith("· الموسم 2 · كل الحلقات\n\u200f📂 مسلسل · SERIES | Drama"))
    check("والمكرّر بعدده", R.alert_text(dict(r, count=3), False).startswith("🔁 *بلاغٌ متكرّر في سمارت: لا يعمل* (3 بلاغات)"))
    check("وبلا تنبيهٍ مضبوط: لا شيء", R.alert(d, r, True) is None)
    sent = []
    R.sender = lambda to, text: sent.append((to, text)) or ({"ok": False, "error": "الرقم ليس على واتساب"}
                                                          if to == "966599000000" else {"ok": True})
    asked = []
    R.recipients = lambda rep: asked.append(rep["server"]) or [("سارة", "966500000001"), ("المدير", "966500000002"),
                                                               ("سارة مكرّر", "966500000001")]
    R._alerts.clear()
    try:
        res = R.alert(d, r, True, now=1000)
        check("يصل كل مستلمٍ مرة", res == {"at": 1000, "to": 2, "sent": 2, "error": ""}
              and [x[0] for x in sent] == ["966500000001", "966500000002"] and sent[0][1] == txt, res)
        check("ويُحفظ مع البلاغ، والمستلمون بسيرفر البلاغ", R.listing(d)["items"][0]["wa"] == res and asked == ["smart"])
        r2, new2 = R.submit(d, dict(base, phone="0500000009"), now=1100)
        check("والمكرّر قبل نصف ساعة: لا تنبيه", not new2 and R.alert(d, r2, False, now=1100) is None and len(sent) == 2)
        r3, _ = R.submit(d, base, now=1000 + R.ALERT_AGAIN)
        res3 = R.alert(d, r3, False, now=1000 + R.ALERT_AGAIN)
        check("وبعدها ينبّه ثانيةً بعدده", res3["sent"] == 2 and "(3 بلاغات)" in sent[-1][1] and "📱" not in sent[-1][1])
        R.recipients = lambda rep: [("سارة", "966500000001"), ("علي", "966599000000")]
        r4, _ = R.submit(d, dict(base, ep=2), now=5000)
        res4 = R.alert(d, r4, True, now=5000)
        check("وما لم يصل: بسببه ولمن", res4["sent"] == 1 and res4["error"] == "علي: الرقم ليس على واتساب", res4)
        R.recipients = lambda rep: []
        r5, _ = R.submit(d, dict(base, ep=3), now=5100)
        check("وبلا مستلمين: سببه باسم السيرفر", R.alert(d, r5, True, now=5100)["error"].startswith("لا أحد يصله تنبيه سمارت"))
        R.recipients = lambda rep: [("سارة", "966500000001")]
        old, R.ALERT_HOUR_MAX = R.ALERT_HOUR_MAX, 2
        R._alerts.clear()
        try:
            got = [R.alert(d, R.submit(d, dict(base, ep=10 + i), now=90000)[0], True, now=90000) for i in range(3)]
            check("وحدّ الساعة يحمي الرقم (والبلاغ محفوظ)", [g["sent"] for g in got] == [1, 1, 0]
                  and "تجاوز حدّ التنبيهات" in got[2]["error"])
            check("ويعود في الساعة التالية", R.alert(d, R.submit(d, dict(base, ep=20), now=93700)[0], True, now=93700)["sent"] == 1)
        finally:
            R.ALERT_HOUR_MAX = old
    finally:
        R.sender = R.recipients = None
    check("رقم المدير: فارغٌ افتراضًا", R.settings(d) == {"wa": "", "on": True, "lang": ""})
    check("ويُحفظ بصيغته الدولية", R.save_settings(d, "0551112222", False) == {"wa": "966551112222", "on": False, "lang": ""}
          and R.settings(d) == {"wa": "966551112222", "on": False, "lang": ""})
    check("والرقم الخطأ يُرفض", "غير صحيح" in raises(R.save_settings, d, "12"))


# ================= على خادمٍ حيّ =================
AUTH = "Basic " + base64.b64encode(b"admin:envpass123").decode()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def req(url, data=None, auth=None, headers=None, opener=None):
    r = urllib.request.Request(url, data=data, headers=dict(headers or {}))
    if auth:
        r.add_header("Authorization", auth)
    try:
        with (opener or urllib.request.build_opener(_NoRedirect)).open(r, timeout=30) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def jpost(url, body, auth=None, opener=None, headers=None):
    code, raw, _ = req(url, json.dumps(body).encode(), auth, {"Content-Type": "application/json", **(headers or {})}, opener)
    try:
        return code, json.loads(raw or b"{}")
    except ValueError:
        return code, {"raw": raw[:200]}


def jget(url, auth=None, opener=None):
    code, raw, _ = req(url, auth=auth, opener=opener)
    try:
        return code, json.loads(raw or b"{}")
    except ValueError:
        return code, {"raw": raw[:200]}


def login(adm, user, pw):
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), _NoRedirect)
    code, d = jpost(adm + "/api/login", {"user": user, "password": pw}, opener=op)
    return op if code == 200 else None


def live():
    print("خادمٌ حيّ")
    port = 9797
    data = tempfile.mkdtemp(prefix="reports_live_")
    env = {k: v for k, v in os.environ.items() if not k.startswith("SALLA_ADMIN_TOKEN")}
    env.update(XM_DATA=data, XM_BIND="127.0.0.1", XM_PORT=str(port), XM_ADMIN_PASSWORD="envpass123",
               REPORT_RATE_PER_HOUR="12")
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "xm_lines.py"), "web"], env=env)
    base, adm = f"http://127.0.0.1:{port}", f"http://127.0.0.1:{port}/admin"
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/robots.txt", timeout=2)
                break
            except Exception:
                time.sleep(.2)
        code, raw, _ = req(base + "/")
        check("مدخل البلاغ في رئيسية الدليل والقائمة (يظهر حين يكون للسيرفرات محتوى)", code == 200
              and b'id="report-entry" href="/report" hidden' in raw and b'id="menu-report" hidden' in raw)
        code, raw, hdr = req(base + "/report")
        check("صفحة البلاغ عامة ولا تُفهرس", code == 200 and b"noindex" in raw and "فيديو لا يعمل".encode() in raw
              and "/api/report/servers".encode() in raw)
        check("وبلا محتوى: لا سيرفرات", jget(base + "/api/report/servers")[1] == {"ok": True, "servers": []})
        code, raw, _ = req(adm + "/api/content/admin/upload?s=smart&name=s.m3u", SAMPLE.encode(), AUTH)
        check("(رفع ملف السيرفر)", code == 200, raw[:200])
        srv = jget(base + "/api/report/servers")[1]
        check("السيرفرات", srv["servers"] == [{"key": "smart", "name": "سمارت", "en": "Smart"}], srv)
        code, g = jget(base + "/api/report/groups?s=smart")
        drama = next(x["id"] for x in g["kinds"]["series"] if x["name"] == "SERIES | Drama")
        check("الأقسام", code == 200 and len(g["kinds"]["movie"]) == 1)
        code, it = jget(base + f"/api/report/items?s=smart&t=series&g={drama}")
        check("العناصر", code == 200 and it["items"][0]["n"] == "Breaking Bad" and it["items"][0]["s"] == [[1, 2], [2, 1]])
        check("والبحث", jget(base + "/api/report/search?s=smart&q=dune")[1]["total"] == 2)
        code, ex = jget(base + "/api/report/exists?s=smart&n=" + urllib.parse.quote("The Dune") + "&t=movie&y=2021")
        check("‏/api/report/exists: موجودٌ بقسمه", code == 200 and ex["total"] == 1 and ex["items"][0]["n"] == "Dune"
              and ex["items"][0]["y"] == 2021 and ex["items"][0]["g"] == "VOD | English Movies", ex)
        check("وما ليس فيه", jget(base + "/api/report/exists?s=smart&n=Oppenheimer")[1] == {"ok": True, "total": 0, "items": []}
              and jget(base + "/api/report/exists?s=nope&n=Dune")[0] == 404)
        check("وما لا وجود له 404", jget(base + "/api/report/groups?s=nope")[0] == 404
              and jget(base + "/api/report/items?s=smart&t=series&g=zz")[0] == 404
              and jget(base + "/api/report/other")[0] == 404)
        form = {"s": "smart", "t": "series", "g": drama, "n": "Breaking Bad", "season": 1, "ep": 2, "problem": "buffer",
                "phone": "0551234567", "note": "يقطع كل دقيقة"}
        code, d = jpost(base + "/api/report", form)
        check("الإرسال", code == 200 and d["ok"] and d["new"] and d["label"] == "Breaking Bad · الموسم 1 · الحلقة 2 — يقطع", d)
        code, d = jpost(base + "/api/report", dict(form, phone=""))
        check("والمكرّر يزيد عدده", code == 200 and not d["new"] and d["count"] == 2, d)
        code, d = jpost(base + "/api/report", dict(form, season=9))
        check("وما لا يُقبل 400 برسالته", code == 400 and d["error"] == "اختر الموسم", d)
        code, d = jpost(base + "/api/report", {"s": "smart", "t": "movie", "n": "Oppenheimer", "problem": "add"})
        check("وطلب الإضافة", code == 200 and d["label"] == "Oppenheimer — طلب إضافة فيلم", d)
        dd = jget(adm + "/api/reports?w=add", AUTH)[1]
        check("والمدير يصفّي الطلبات وحدها", [x["title"] for x in dd["items"]] == ["Oppenheimer"] and dd["counts"]["add"] == 1
              and dd["items"][0]["ptext"] == "طلب إضافة فيلم", dd.get("counts"))
        jpost(adm + "/api/reports/delete", {"id": dd["items"][0]["id"]}, AUTH)
        code, raw, _ = req(base + "/api/report", b"not json", headers={"Content-Type": "application/json"})
        check("وطلبٌ ليس JSON ‏400", code == 400)
        code, raw, _ = req(base + "/api/report", b"{" + b" " * 9000 + b"}", headers={"Content-Type": "application/json"})
        check("وطلبٌ كبير ‏413", code == 413)
        # حال الموظف: المدير، وموظفٌ فُتحت له (بلا بوابات)، وحسابٌ لم تُفتح له
        code, d = jpost(adm + "/api/accounts", {"name": "سارة", "user": "sara", "password": "sara1234", "reports": True, "gates": []}, AUTH)
        check("خيار «بلاغات المحتوى» في الحساب", code == 200 and next(a for a in d["accounts"] if a["user"] == "sara")["reports"] is True, d)
        code, d = jpost(adm + "/api/accounts", {"name": "علي", "user": "ali", "password": "ali12345", "gates": []}, AUTH)
        check("ومغلقٌ افتراضًا", code == 200 and next(a for a in d["accounts"] if a["user"] == "ali")["reports"] is False)
        code, raw, h = req(adm + "/reports")
        check("صفحة الموظف تطلب الدخول", code == 302 and h["Location"] == "/admin/login" and jget(adm + "/api/reports")[0] == 401)
        code, raw, _ = req(adm + "/reports", auth=AUTH)
        check("والمدير يفتحها", code == 200 and "بلاغات المحتوى".encode() in raw)
        code, d = jget(adm + "/api/reports", AUTH)
        rid = d["items"][0]["id"] if d.get("items") else ""
        check("ويرى البلاغ بعدده وأصحابه", code == 200 and d["role"] == "admin" and od(d["counts"]) == (1, 0)
              and d["items"][0]["count"] == 2 and d["items"][0]["people"][0]["phone"] == "966551234567"
              and d["items"][0]["people"][0]["note"] == "يقطع كل دقيقة", d)
        sara = login(adm, "sara", "sara1234")
        code, raw, h = req(adm + "/", opener=sara)
        check("الموظف بلا بوابات يدخل إلى البلاغات", code == 302 and h["Location"] == "/admin/reports", (code, h.get("Location")))
        check("و‏/api/me يقول إنها له", jget(adm + "/api/me", opener=sara)[1].get("reports") is True)
        code, d = jget(adm + "/api/reports", opener=sara)
        check("ويرى البلاغات باسمه", code == 200 and d["role"] == "account" and d["name"] == "سارة" and d["gates"] == 0
              and len(d["items"]) == 1)
        code, d = jpost(adm + "/api/reports/state", {"id": rid, "done": True}, opener=sara)
        check("ويعلّم «تم الإصلاح» باسمه", code == 200 and d["item"]["state"] == "done" and d["item"]["done_by"] == "سارة", d)
        check("فيصير في المنجزة", od(jget(adm + "/api/reports?state=done", opener=sara)[1]["counts"]) == (0, 1))
        check("ولا يحذف (للمدير وحده)", jpost(adm + "/api/reports/delete", {"id": rid}, opener=sara)[0] == 403)
        check("وبلاغٌ لا وجود له 404", jpost(adm + "/api/reports/state", {"id": "nope", "done": True}, opener=sara)[0] == 404)
        ali = login(adm, "ali", "ali12345")
        check("ومن لم تُفتح له: لا صفحة ولا بلاغات", req(adm + "/reports", opener=ali)[0] == 403
              and jget(adm + "/api/reports", opener=ali)[0] == 403
              and jpost(adm + "/api/reports/state", {"id": rid, "done": False}, opener=ali)[0] == 403
              and jget(adm + "/api/me", opener=ali)[1].get("reports") is False)
        code, raw, h = req(adm + "/", opener=ali)
        check("وصفحته الأولى صفحة الإنشاء كما كانت", code == 200)
        check("والمدير يحذف", jpost(adm + "/api/reports/delete", {"id": rid}, AUTH)[0] == 200
              and jget(adm + "/api/reports?state=all", AUTH)[1]["items"] == [])
        code, raw, _ = req(base + "/content/smart")
        check("ورابط البلاغ في صفحة المحتوى (العربية)", code == 200 and b'href="/report?s=smart"' in raw)
        code, raw, _ = req(base + "/en/content/smart")
        check("وفي الإنجليزية إلى صفحة البلاغ بالإنجليزية", code == 200 and b'href="/report?s=smart&amp;lang=en"' in raw
              and "Report it".encode() in raw)
        hits = [jpost(base + "/api/report", dict(form, ep=3), headers={"X-Forwarded-For": "9.9.9.9"})[0] for _ in range(13)]
        check("وحدّ البلاغات بالساعة لكل عنوان (429)", hits[:12] == [200] * 12 and hits[12] == 429, hits)
    finally:
        p.terminate()
        p.wait(timeout=10)


def live_alert():
    print("خادمٌ حيّ: التنبيه يصل على واتساب")
    port, wport = 9794, 9784
    data = tempfile.mkdtemp(prefix="reports_alert_")
    reader = f"http://127.0.0.1:{wport}"
    rdp = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_reader.py"), str(wport), "rdr_rep"])
    env = {k: v for k, v in os.environ.items() if not k.startswith(("WHATSAPP_READER_", "SALLA_ADMIN_TOKEN"))}
    env.update(XM_DATA=data, XM_BIND="127.0.0.1", XM_PORT=str(port), XM_ADMIN_PASSWORD="envpass123",
               WHATSAPP_READER_URL=reader, WHATSAPP_READER_SECRET="rdr_rep")
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "xm_lines.py"), "web"], env=env)
    base, adm = f"http://127.0.0.1:{port}", f"http://127.0.0.1:{port}/admin"

    def rd(method, path, body=None):
        rq = urllib.request.Request(reader + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                    headers={"Content-Type": "application/json", "X-Reader-Secret": "rdr_rep"})
        with urllib.request.urlopen(rq, timeout=20) as r:
            return json.loads(r.read())

    def sent_after(n, want, t=8.0):
        end = time.time() + t
        while time.time() < end:
            log = rd("GET", "/_test/log")["sent"]
            if len(log) >= n + want:
                return log[n:]
            time.sleep(.1)
        return rd("GET", "/_test/log")["sent"][n:]

    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/robots.txt", timeout=2)
                rd("GET", "/_test/log")
                break
            except Exception:
                time.sleep(.2)
        req(adm + "/api/content/admin/upload?s=smart&name=s.m3u", SAMPLE.encode(), AUTH)
        drama = next(x["id"] for x in jget(base + "/api/report/groups?s=smart")[1]["kinds"]["series"] if x["name"] == "SERIES | Drama")
        form = {"s": "smart", "t": "series", "g": drama, "n": "Breaking Bad", "season": 1, "ep": 2, "problem": "buffer",
                "phone": "0551234567"}
        code, d = jpost(adm + "/api/accounts", {"name": "سارة", "user": "sara", "password": "sara1234", "reports": True,
                                                "reports_wa": "0500000001", "gates": []}, AUTH)
        check("رقم الموظف في نافذة الحساب (بصيغته الدولية)", code == 200
              and next(a for a in d["accounts"] if a["user"] == "sara")["reports_wa"] == "966500000001", d)
        code, d = jpost(adm + "/api/accounts", {"name": "علي", "user": "ali", "password": "ali12345", "reports": True,
                                                "reports_wa": "05ab", "gates": []}, AUTH)
        check("والرقم الخطأ يُرفض برسالته", code == 400 and d["error"].startswith("رقم واتساب الموظف"), d)
        code, d = jget(adm + "/api/reports", AUTH)
        check("بلا رقم مسابقةٍ مربوط: الصفحة تقول ذلك", code == 200 and d["alert"]["from"] == ""
              and "رقم المسابقة غير مربوط" in d["alert"]["from_error"]
              and d["alert"]["staff"] == [{"name": "سارة", "wa": "966500000001", "on": True, "all": True, "lead": False, "of": "", "servers": []}], d.get("alert"))
        n0 = len(rd("GET", "/_test/log")["sent"])
        code, d = jpost(base + "/api/report", form)
        time.sleep(1)
        check("والبلاغ يُحفظ وإن لم يصل التنبيه، وسببه معه", code == 200
              and "رقم المسابقة غير مربوط" in (jget(adm + "/api/reports", AUTH)[1]["items"][0].get("wa") or {}).get("error", "")
              and len(rd("GET", "/_test/log")["sent"]) == n0, jget(adm + "/api/reports", AUTH)[1]["items"][0].get("wa"))
        jpost(adm + "/api/contest/admin/wa/connect", {"number": "0500000009"}, AUTH)
        rd("POST", "/_test/scan/ssouq-guide--contest", {})
        req(adm + "/api/contest/admin", auth=AUTH)              # صفحة المسابقة تجدّد حال الرقم
        code, d = jpost(adm + "/api/reports/alert", {"wa": "0551112222", "on": True}, AUTH)
        check("المدير يحفظ رقمه، ومن أين يُرسل", code == 200 and d["alert"]["mine"] == {"wa": "966551112222", "on": True, "lang": ""}
              and d["alert"]["from"] == "966500000009", d)
        n0 = len(rd("GET", "/_test/log")["sent"])
        code, d = jpost(base + "/api/report", dict(form, ep=3, note="يقطع كل دقيقة"))
        got = sent_after(n0, 2)
        check("كل بلاغٍ جديد يصل الموظف والمدير", code == 200 and sorted(x["to"] for x in got) == ["966500000001", "966551112222"]
              and all("Breaking Bad · الموسم 1 · الحلقة 3" in x["body"] and "يقطع" in x["body"]
                      and "966551234567" not in x["body"] and "كل دقيقة" not in x["body"] and "https://" not in x["body"]
                      for x in got), got)
        item = next(x for x in jget(adm + "/api/reports", AUTH)[1]["items"] if x["ep"] == 3)
        check("وما جرى معه في الصفحة", item["wa"]["sent"] == 2 and item["wa"]["error"] == "", item.get("wa"))
        n0 = len(rd("GET", "/_test/log")["sent"])
        jpost(base + "/api/report", dict(form, ep=3))
        time.sleep(1)
        check("والمكرّر فورًا لا يُعيد التنبيه", len(rd("GET", "/_test/log")["sent"]) == n0)
        sara = login(adm, "sara", "sara1234")
        code, d = jget(adm + "/api/reports", opener=sara)
        check("والموظف يرى رقمه، ولا يرى غيره", code == 200 and d["alert"]["mine"] == {"wa": "966500000001", "on": True, "lang": ""}
              and "staff" not in d["alert"])
        code, d = jpost(adm + "/api/reports/alert", {"wa": "0500000002", "on": False}, opener=sara)
        check("ويغيّر رقمه ويوقف تنبيهه", code == 200 and d["alert"]["mine"] == {"wa": "966500000002", "on": False, "lang": ""}, d)
        check("ورقمٌ خطأ ‏400", jpost(adm + "/api/reports/alert", {"wa": "123"}, opener=sara)[0] == 400)
        n0 = len(rd("GET", "/_test/log")["sent"])
        jpost(base + "/api/report", dict(form, ep=4))
        got = sent_after(n0, 1)
        time.sleep(.5)
        got = rd("GET", "/_test/log")["sent"][n0:]
        check("فلا يصله، ويصل المدير", [x["to"] for x in got] == ["966551112222"], got)
        n0 = len(rd("GET", "/_test/log")["sent"])
        code, d = jpost(adm + "/api/reports/alert-test", {}, opener=sara)
        got = rd("GET", "/_test/log")["sent"][n0:]
        check("والرسالة التجريبية إلى رقمه", code == 200 and d["ok"] and d["to"] == "966500000002"
              and len(got) == 1 and got[0]["to"] == "966500000002" and "تنبيه بلاغات المحتوى يعمل" in got[0]["body"], (d, got))
        code, d = jpost(adm + "/api/accounts", {"name": "علي", "user": "ali", "password": "ali12345", "gates": []}, AUTH)
        ali = login(adm, "ali", "ali12345")
        check("ومن لم تُفتح له البلاغات: لا تنبيه ولا تجربة", jpost(adm + "/api/reports/alert", {"wa": "0500000003"}, opener=ali)[0] == 403
              and jpost(adm + "/api/reports/alert-test", {}, opener=ali)[0] == 403)
    finally:
        p.terminate()
        p.wait(timeout=10)
        rdp.terminate()
        rdp.wait(timeout=10)


def live_team():
    print("خادمٌ حيّ: لكل سيرفر موظفٌ أو أكثر")
    port, wport = 9793, 9783
    data = tempfile.mkdtemp(prefix="reports_team_")
    reader = f"http://127.0.0.1:{wport}"
    rdp = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_reader.py"), str(wport), "rdr_team"])
    env = {k: v for k, v in os.environ.items() if not k.startswith(("WHATSAPP_READER_", "SALLA_ADMIN_TOKEN"))}
    env.update(XM_DATA=data, XM_BIND="127.0.0.1", XM_PORT=str(port), XM_ADMIN_PASSWORD="envpass123",
               WHATSAPP_READER_URL=reader, WHATSAPP_READER_SECRET="rdr_team")
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "xm_lines.py"), "web"], env=env)
    base, adm = f"http://127.0.0.1:{port}", f"http://127.0.0.1:{port}/admin"

    def rd(method, path, body=None):
        rq = urllib.request.Request(reader + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                    headers={"Content-Type": "application/json", "X-Reader-Secret": "rdr_team"})
        with urllib.request.urlopen(rq, timeout=20) as r:
            return json.loads(r.read())

    def sent_to(n0, want, t=8.0):
        """أرقام من وصلهم بعد n0 — حين يصل عددهم ‏want، ثم مهلةٌ قصيرة لما قد يزيد."""
        end = time.time() + t
        while time.time() < end and len(rd("GET", "/_test/log")["sent"]) < n0 + want:
            time.sleep(.1)
        time.sleep(.4)
        return sorted(x["to"] for x in rd("GET", "/_test/log")["sent"][n0:])

    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/robots.txt", timeout=2)
                rd("GET", "/_test/log")
                break
            except Exception:
                time.sleep(.2)
        req(adm + "/api/content/admin/upload?s=smart&name=s.m3u", SAMPLE.encode(), AUTH)
        req(adm + "/api/content/admin/upload?s=falcon&name=f.m3u",
            ("#EXTM3U\n" + entry("Kon Show S01 E01", "Drama", "series", 1)).encode(), AUTH)
        jpost(adm + "/api/contest/admin/wa/connect", {"number": "0500000009"}, AUTH)
        rd("POST", "/_test/scan/ssouq-guide--contest", {})
        req(adm + "/api/contest/admin", auth=AUTH)
        code, d = jget(adm + "/api/accounts", AUTH)
        check("نافذة الحساب تعرف السيرفرات", [x["key"] for x in d["report_servers"]] == ["kon", "casper", "smart", "falcon"],
              d.get("report_servers"))
        people = {"sara": ("سارة", "0500000001", ["smart"]), "nora": ("نورة", "0500000002", ["falcon", "../x", "falcon"]),
                  "omar": ("عمر", "0500000003", []), "huda": ("هدى", "0500000004", ["smart"])}
        for user, (name, wa, srv) in people.items():
            code, d = jpost(adm + "/api/accounts", {"name": name, "user": user, "password": user + "1234", "reports": True,
                                                    "reports_wa": wa, "reports_servers": srv, "gates": []}, AUTH)
        acc = {a["user"]: a for a in d["accounts"]}
        check("سيرفرات كل موظف (بلا تكرارٍ ولا مفتاحٍ غريب، والفارغة كلها)", acc["sara"]["reports_servers"] == ["smart"]
              and acc["nora"]["reports_servers"] == ["falcon"] and acc["omar"]["reports_servers"] == [], acc["nora"])
        code, d = jget(adm + "/api/reports", AUTH)
        team = {t["key"]: sorted(x["name"] for x in t["people"]) for t in d["alert"]["team"]}
        check("والمدير يرى من يتابع كل سيرفرٍ له محتوى (وللسيرفر أكثر من موظف)", team == {
            "smart": ["سارة", "عمر", "هدى"], "falcon": ["عمر", "نورة"]}, team)
        smart = next(x["id"] for x in jget(base + "/api/report/groups?s=smart")[1]["kinds"]["series"] if x["name"] == "SERIES | Drama")
        falcon = jget(base + "/api/report/groups?s=falcon")[1]["kinds"]["series"][0]["id"]
        n0 = len(rd("GET", "/_test/log")["sent"])
        jpost(base + "/api/report", {"s": "smart", "t": "series", "g": smart, "n": "Breaking Bad", "season": 1, "ep": 1, "problem": "down"})
        check("بلاغ سمارت يصل موظفيه ومن يتابع الكل وحدهم", sent_to(n0, 3) == ["966500000001", "966500000003", "966500000004"])
        n0 = len(rd("GET", "/_test/log")["sent"])
        jpost(base + "/api/report", {"s": "falcon", "t": "series", "g": falcon, "n": "Kon Show", "season": 1, "ep": 1, "problem": "buffer"})
        check("وبلاغ فالكون كذلك", sent_to(n0, 2) == ["966500000002", "966500000003"])
        sara, omar = login(adm, "sara", "sara1234"), login(adm, "omar", "omar1234")
        code, d = jget(adm + "/api/reports?state=all", opener=sara)
        fid = next(x["id"] for x in jget(adm + "/api/reports", AUTH)[1]["items"] if x["server"] == "falcon")
        check("موظف سمارت لا يرى إلا بلاغاتها، ولا يُعدّ له غيرها", code == 200 and [x["server"] for x in d["items"]] == ["smart"]
              and od(d["counts"]) == (1, 0) and d["alert"]["servers"] == ["سمارت"] and "team" not in d["alert"], d.get("counts"))
        check("ولا يرى بلاغ فالكون بتصفيته", jget(adm + "/api/reports?s=falcon", opener=sara)[1]["items"] == [])
        check("ولا يمسّ بلاغ فالكون برقمه", jpost(adm + "/api/reports/state", {"id": fid, "done": True}, opener=sara)[0] == 404
              and jget(adm + "/api/reports", AUTH)[1]["counts"]["open"] == 2)
        d = jget(adm + "/api/reports?state=all", opener=omar)[1]
        check("ومن يتابع الكل يرى الكل ويصلحه", sorted(x["server"] for x in d["items"]) == ["falcon", "smart"]
              and d["alert"]["servers"] == [] and jpost(adm + "/api/reports/state", {"id": fid, "done": True}, opener=omar)[0] == 200)
        code, d = jpost(adm + "/api/accounts", {"id": acc["sara"]["id"], "name": "سارة", "user": "sara",
                                                "reports": True, "reports_servers": ["smart", "falcon"], "gates": []}, AUTH)
        check("وتعديل سيرفراته يحفظ رقمه", code == 200 and next(a for a in d["accounts"] if a["user"] == "sara")["reports_wa"] == "966500000001")
        check("فيرى ما أُضيف له فورًا", sorted(x["server"] for x in jget(adm + "/api/reports?state=all", opener=sara)[1]["items"]) == ["falcon", "smart"])
    finally:
        p.terminate()
        p.wait(timeout=10)
        rdp.terminate()
        rdp.wait(timeout=10)


def live_lead():
    print("خادمٌ حيّ: المشرف وفريقه، و«صفحة البلاغات فقط»، ورسالة أصحاب البلاغ، والإنجليزية")
    port, wport = 9792, 9782
    data = tempfile.mkdtemp(prefix="reports_lead_")
    reader = f"http://127.0.0.1:{wport}"
    rdp = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_reader.py"), str(wport), "rdr_lead"])
    env = {k: v for k, v in os.environ.items() if not k.startswith(("WHATSAPP_READER_", "SALLA_ADMIN_TOKEN"))}
    env.update(XM_DATA=data, XM_BIND="127.0.0.1", XM_PORT=str(port), XM_ADMIN_PASSWORD="envpass123",
               WHATSAPP_READER_URL=reader, WHATSAPP_READER_SECRET="rdr_lead", CONTENT_IMG_PRIVATE="1")
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "xm_lines.py"), "web"], env=env)
    base, adm = f"http://127.0.0.1:{port}", f"http://127.0.0.1:{port}/admin"

    def rd(method, path, body=None):
        rq = urllib.request.Request(reader + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                    headers={"Content-Type": "application/json", "X-Reader-Secret": "rdr_lead"})
        with urllib.request.urlopen(rq, timeout=20) as r:
            return json.loads(r.read())

    def sent_since(n0, want, t=8.0):
        end = time.time() + t
        while time.time() < end and len(rd("GET", "/_test/log")["sent"]) < n0 + want:
            time.sleep(.1)
        time.sleep(.3)
        return rd("GET", "/_test/log")["sent"][n0:]

    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/robots.txt", timeout=2)
                rd("GET", "/_test/log")
                break
            except Exception:
                time.sleep(.2)
        req(adm + "/api/content/admin/upload?s=smart&name=s.m3u", SAMPLE.encode(), AUTH)
        req(adm + "/api/content/admin/upload?s=falcon&name=f.m3u", ("#EXTM3U\n" + entry("Kon Show S01 E01", "Drama", "series", 1)).encode(), AUTH)
        jpost(adm + "/api/contest/admin/wa/connect", {"number": "0500000009"}, AUTH)
        rd("POST", "/_test/scan/ssouq-guide--contest", {})
        req(adm + "/api/contest/admin", auth=AUTH)
        code, d = jpost(adm + "/api/accounts", {"name": "مشرف سمارت", "user": "lead1", "password": "lead1234", "reports": True,
                                                "reports_only": True, "reports_lead": True, "reports_servers": ["smart"],
                                                "reports_wa": "0500000010", "gates": []}, AUTH)
        lead_acc = next(a for a in d["accounts"] if a["user"] == "lead1")
        check("المدير يجعل حسابًا مشرفًا و«صفحة البلاغات فقط»", code == 200 and lead_acc["reports_lead"] and lead_acc["reports_only"])
        jpost(adm + "/api/accounts", {"name": "موظف عادي", "user": "plain", "password": "plain1234", "reports": True, "gates": []}, AUTH)
        lead = login(adm, "lead1", "lead1234")
        code, _, h = req(adm + "/", opener=lead)
        check("المشرف يدخل إلى البلاغات", code == 302 and h["Location"] == "/admin/reports")
        blocked = {"/renew": req(adm + "/renew", opener=lead), "/remaining": req(adm + "/remaining", opener=lead),
                   "/accounts": req(adm + "/accounts", opener=lead)}
        check("و«صفحة البلاغات فقط»: كل صفحةٍ غيرها تحوّل إليها", all(c == 302 and hh["Location"] == "/admin/reports"
                                                                   for c, _, hh in blocked.values()), {k: v[0] for k, v in blocked.items()})
        apis = [jget(adm + "/api/me", opener=lead), jget(adm + "/api/renew/config", opener=lead), jget(adm + "/api/split/state", opener=lead),
                jpost(adm + "/api/mygates", {"gates": []}, opener=lead), jpost(adm + "/api/myguide", {"guide_url": ""}, opener=lead),
                jpost(adm + "/api/create", {"gate": "x"}, opener=lead), jpost(adm + "/api/accounts", {"name": "x"}, opener=lead)]
        check("وكل واجهةٍ غيرها ‏403", all(c == 403 and dd.get("error") == "هذا الحساب لصفحة البلاغات فقط" for c, dd in apis),
              [c for c, _ in apis])
        code, d = jget(adm + "/api/reports", opener=lead)
        check("والبلاغات وفريقه (فارغًا) وسيرفراته", code == 200 and d["team"] == {"members": [], "servers": [
            {"key": "smart", "name": "سمارت", "en": "Smart"}]} and d["server_names"]["falcon"] == "Falcon", d.get("team"))
        code, d = jpost(adm + "/api/reports/team", {"action": "save", "name": "عضو", "user": "m1", "password": "m1pass",
                                                     "wa": "0500000011", "servers": ["smart", "falcon"]}, opener=lead)
        mem = d.get("team", {}).get("members", [{}])[0]
        check("المشرف يضيف عضوًا (وسيرفرٌ ليس له لا يُعطى)", code == 200 and mem.get("user") == "m1" and mem.get("servers") == ["smart"]
              and mem.get("wa") == "966500000011", d)
        code, d = jpost(adm + "/api/reports/team", {"action": "save", "name": "عضو٢", "user": "m2", "password": "m2pass", "servers": []},
                        opener=lead)
        check("وبلا اختيارٍ: سيرفراته كلها لا كل السيرفرات", code == 200
              and next(x for x in d["team"]["members"] if x["user"] == "m2")["servers"] == ["smart"])
        check("واسم دخولٍ مستخدم ‏400", jpost(adm + "/api/reports/team", {"action": "save", "name": "x", "user": "plain", "password": "xxxx1"},
                                                opener=lead)[0] == 400)
        check("ولا يمسّ حسابًا ليس من فريقه", jpost(adm + "/api/reports/team", {"action": "save", "id": lead_acc["id"], "name": "x",
                                                                               "user": "x", "password": "xxxx1"}, opener=lead)[0] == 404)
        accs = {a["user"]: a for a in jget(adm + "/api/accounts", AUTH)[1]["accounts"]}
        check("وعضوه «صفحة البلاغات فقط» بلا بواباتٍ ولا إشراف، ومنسوبٌ إليه", accs["m1"]["reports_only"] and not accs["m1"]["reports_lead"]
              and accs["m1"]["gates"] == [] and accs["m1"]["lead_id"] == lead_acc["id"])
        m1 = login(adm, "m1", "m1pass")
        check("والعضو يدخل إلى البلاغات ولا شيء غيرها، ولا يدير فريقًا", req(adm + "/", opener=m1)[2].get("Location") == "/admin/reports"
              and jget(adm + "/api/me", opener=m1)[0] == 403
              and jpost(adm + "/api/reports/team", {"action": "save", "name": "x", "user": "m9", "password": "xxxx1"}, opener=m1)[0] == 403)
        plain = login(adm, "plain", "plain1234")
        check("وموظفٌ غير مشرف لا يدير فريقًا، ويرى غير البلاغات", jpost(adm + "/api/reports/team", {"action": "save"}, opener=plain)[0] == 403
              and jget(adm + "/api/me", opener=plain)[0] == 200)
        team = {t["key"]: [(x["name"], x["lead"], x["of"]) for x in t["people"]] for t in jget(adm + "/api/reports", AUTH)[1]["alert"]["team"]}
        check("والمدير يرى المشرف وفريقه على السيرفر", sorted(team["smart"]) == sorted([("مشرف سمارت", True, ""), ("عضو", False, "مشرف سمارت"),
                                                                                    ("عضو٢", False, "مشرف سمارت"), ("موظف عادي", False, "")]), team)
        # بلاغٌ بالإنجليزية: خطؤه بالإنجليزية، والتنبيه بلغة كل موظف
        smart = next(x["id"] for x in jget(base + "/api/report/groups?s=smart")[1]["kinds"]["series"] if x["name"] == "SERIES | Drama")
        code, d = jpost(base + "/api/report", {"s": "smart", "t": "series", "g": smart, "n": "Breaking Bad", "season": 9, "ep": 1,
                                                "problem": "down", "lang": "en"})
        check("خطأ البلاغ بالإنجليزية", code == 400 and d["error"] == "Choose the season", d)
        check("وصفحة الموظف تحفظ لغته", jpost(adm + "/api/reports/lang", {"lang": "en"}, opener=m1)[1].get("lang") == "en"
              and jget(adm + "/api/reports", opener=m1)[1]["lang"] == "en")
        n0 = len(rd("GET", "/_test/log")["sent"])
        code, d = jpost(base + "/api/report", {"s": "smart", "t": "series", "g": smart, "n": "Breaking Bad", "season": 1, "ep": 2,
                                                "problem": "subs", "phone": "0551234567", "lang": "en"})
        got = {x["to"]: x["body"] for x in sent_since(n0, 2)}
        check("التنبيه: بالإنجليزية لمن اختارها، وبالعربية لغيره", code == 200 and got.get("966500000011", "").startswith(
            "🔔 *New report on Smart: Wrong subtitles*") and got.get("966500000010", "").startswith("🔔 *بلاغ جديد في سمارت: الترجمة غير صحيحة*"),
              got)
        rid = next(x["id"] for x in jget(adm + "/api/reports", opener=m1)[1]["items"] if x["ep"] == 2)
        check("وللبلاغ لغة صاحبه", jget(adm + "/api/reports", opener=m1)[1]["items"][0]["lang"] == "en")
        # «تم الإصلاح» ورسالةٌ لصاحبه
        check("العضو يعلّمه «تم الإصلاح»", jpost(adm + "/api/reports/state", {"id": rid, "done": True}, opener=m1)[0] == 200)
        n0 = len(rd("GET", "/_test/log")["sent"])
        code, d = jpost(adm + "/api/reports/notify", {"id": rid, "text": "Hello 👋 What you reported on Smart is fixed."}, opener=m1)
        got = rd("GET", "/_test/log")["sent"][n0:]
        check("ويرسل لصاحبه على واتساب من رقم المسابقة", code == 200 and d["ok"] and d["update"]["sent"] == 1 and d["update"]["by"] == "عضو"
              and [x["to"] for x in got] == ["966551234567"] and got[0]["body"] == "Hello 👋 What you reported on Smart is fixed.", (d, got))
        upd = next(x for x in jget(adm + "/api/reports?state=done", AUTH)[1]["items"] if x["id"] == rid)["updates"]
        check("ويظهر للمدير ما أُرسل ومن أرسله", len(upd) == 1 and upd[0]["sent"] == 1 and upd[0]["by"] == "عضو")
        check("وبلا نصٍّ ‏400", jpost(adm + "/api/reports/notify", {"id": rid, "text": " "}, opener=m1)[0] == 400)
        falcon = jget(base + "/api/report/groups?s=falcon")[1]["kinds"]["series"][0]["id"]
        jpost(base + "/api/report", {"s": "falcon", "t": "series", "g": falcon, "n": "Kon Show", "season": 1, "ep": 1, "problem": "down",
                                     "phone": "0551234567"})
        fid = next(x["id"] for x in jget(adm + "/api/reports", AUTH)[1]["items"] if x["server"] == "falcon")
        check("ولا يراسل أصحاب بلاغ سيرفرٍ ليس له", jpost(adm + "/api/reports/notify", {"id": fid, "text": "x"}, opener=m1)[0] == 404
              and jpost(adm + "/api/reports/notify", {"id": fid, "text": "x"}, opener=lead)[0] == 404)
        # رابط المسلسل أو الفيلم يعبّئ طلب الإضافة (صفحةٌ من خادمٍ وهمي محلي)
        import http.server
        import threading

        class Page(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                raw = TMDB_PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *a):
                pass
        ps = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Page)
        threading.Thread(target=ps.serve_forever, daemon=True).start()
        link = f"http://127.0.0.1:{ps.server_address[1]}/movie/438631-dune"
        code, d = jget(base + "/api/report/lookup?url=" + urllib.parse.quote(link))
        check("‏/api/report/lookup يقرأ الرابط", code == 200 and d == {"ok": True, "kind": "movie", "name": "Dune", "year": 2021, "lang": "en"}, d)
        code, d = jget(base + "/api/report/lookup?url=javascript:1")
        check("ورابطٌ غريب برسالتيه", code == 200 and not d["ok"] and d["error"].startswith("الرابط غير صحيح") and d["en"].startswith("Invalid"))
        code, d = jpost(base + "/api/report", {"s": "smart", "t": "movie", "n": "Dune", "y": 2021, "cl": "en", "link": link, "problem": "add"})
        item = next(x for x in jget(adm + "/api/reports?w=add", AUTH)[1]["items"] if x["title"] == "Dune")
        check("والطلب بسنته ولغته ورابطه", code == 200 and item["year"] == 2021 and item["cl"] == "en" and item["link"] == link, item)
        ps.shutdown()
        mid = next(x["id"] for x in jget(adm + "/api/reports", opener=lead)[1]["team"]["members"] if x["user"] == "m1")
        code, d = jpost(adm + "/api/reports/team", {"action": "delete", "id": mid}, opener=lead)
        check("والمشرف يحذف عضوه فلا يدخل بعدها", code == 200 and [x["user"] for x in d["team"]["members"]] == ["m2"]
              and jget(adm + "/api/reports", opener=m1)[0] == 401 and login(adm, "m1", "m1pass") is None)
    finally:
        p.terminate()
        p.wait(timeout=10)
        rdp.terminate()
        rdp.wait(timeout=10)


def main():
    unit_steps()
    unit_submit()
    unit_staff()
    unit_alert()
    unit_more()
    unit_notify_lang()
    unit_link()
    live()
    live_alert()
    live_team()
    live_lead()
    print(f"\nResult: {_p} passed, {_f} failed")
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

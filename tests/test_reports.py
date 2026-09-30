#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""بلاغات المحتوى (reports.py · report.html · reports_admin.html): المشترك يختار من ملف M3U السيرفر ثم القسم ثم
المسلسل أو الفيلم ثم الحلقة، ويبلّغ «لا يعمل» أو «يقطع»؛ والموظف الذي فتحها له المدير يراها ويعلّمها «تم الإصلاح».

  - الخطوات: السيرفرات التي لها محتوى، وأقسامها الظاهرة (بلا المخفي)، وعناصر القسم بالتصفية والصفحات، والبحث بالاسم.
  - البلاغ: يُطابَق بالفهرس (القسم والاسم وسنة الفيلم والموسم)، وما لا يُقبل برسالته، ورقم الواتساب بصيغته الدولية،
    والمكرّر المفتوح يزيد عدده ولا يتكرّر، والحدّ بالساعة، وحدّ الحفظ.
  - الموظف: المفتوحة والمنجزة بأعدادها ولكل سيرفر، و«تم الإصلاح» وإعادة الفتح (ويُضمّ إلى مثله)، والحذف.
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
    check("السيرفر الذي له محتوى وحده", R.servers(d)["servers"] == [{"key": "smart", "name": "سمارت"}], R.servers(d))
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
          and r["people"] == [{"at": 1000, "phone": "966551234567", "note": "شاشة سوداء"}], r)
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
          and ls["counts"] == {"open": 3, "done": 0} and ls["servers"] == [
              {"key": "smart", "name": "سمارت", "open": 2}, {"key": "falcon", "name": "فالكون", "open": 1}]
          and ls["items"][0]["label"] == "Kon Show · الموسم 1 · الحلقة 1 — يقطع", ls)
    check("وتصفيتها بالسيرفر", [x["id"] for x in R.listing(d, server="falcon")["items"]] == [f["id"]])
    done = R.set_state(d, a["id"], True, "سارة", now=500)
    check("«تم الإصلاح» بمن ومتى", done["state"] == "done" and done["done_by"] == "سارة" and done["done_at"] == 500)
    ls = R.listing(d)
    check("فتخرج من المفتوحة إلى المنجزة", ls["counts"] == {"open": 2, "done": 1}
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
        code, raw, hdr = req(base + "/report")
        check("صفحة البلاغ عامة ولا تُفهرس", code == 200 and b"noindex" in raw and "فيديو لا يعمل".encode() in raw
              and "/api/report/servers".encode() in raw)
        check("وبلا محتوى: لا سيرفرات", jget(base + "/api/report/servers")[1] == {"ok": True, "servers": []})
        code, raw, _ = req(adm + "/api/content/admin/upload?s=smart&name=s.m3u", SAMPLE.encode(), AUTH)
        check("(رفع ملف السيرفر)", code == 200, raw[:200])
        srv = jget(base + "/api/report/servers")[1]
        check("السيرفرات", srv["servers"] == [{"key": "smart", "name": "سمارت"}], srv)
        code, g = jget(base + "/api/report/groups?s=smart")
        drama = next(x["id"] for x in g["kinds"]["series"] if x["name"] == "SERIES | Drama")
        check("الأقسام", code == 200 and len(g["kinds"]["movie"]) == 1)
        code, it = jget(base + f"/api/report/items?s=smart&t=series&g={drama}")
        check("العناصر", code == 200 and it["items"][0]["n"] == "Breaking Bad" and it["items"][0]["s"] == [[1, 2], [2, 1]])
        check("والبحث", jget(base + "/api/report/search?s=smart&q=dune")[1]["total"] == 2)
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
        check("ويرى البلاغ بعدده وأصحابه", code == 200 and d["role"] == "admin" and d["counts"] == {"open": 1, "done": 0}
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
        check("فيصير في المنجزة", jget(adm + "/api/reports?state=done", opener=sara)[1]["counts"] == {"open": 0, "done": 1})
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
        check("ولا في الإنجليزية (صفحة البلاغ عربية)", code == 200 and b"/report?s=" not in raw)
        hits = [jpost(base + "/api/report", dict(form, ep=3), headers={"X-Forwarded-For": "9.9.9.9"})[0] for _ in range(13)]
        check("وحدّ البلاغات بالساعة لكل عنوان (429)", hits[:12] == [200] * 12 and hits[12] == 429, hits)
    finally:
        p.terminate()
        p.wait(timeout=10)


def main():
    unit_steps()
    unit_submit()
    unit_staff()
    live()
    print(f"\nResult: {_p} passed, {_f} failed")
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

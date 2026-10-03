#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
إضافة Stremio (‏stremio_addon.py): الرمز المختوم، والقوائم كلها بصفحات 100، والتصنيفات والبحث، والتفاصيل
بمواسمها وحلقاتها، وروابط التشغيل — مقابل سيرفر Xtream الوهمي (بلا إنترنت)، ثم المسارات عبر الخادم نفسه:
الصفحة العامة ورابط التثبيت وCORS وما يصل Stremio.

    python tests/test_stremio.py
"""
import json
import re
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import mock_xtream  # noqa: E402
import stremio_addon as S  # noqa: E402

PORT = int(os.environ.get("STREMIO_TEST_PORT", "9591"))
_p = _f = 0


def check(label, cond, extra=""):
    global _p, _f
    if cond:
        _p += 1
        print("  \033[32mPASS\033[0m  " + label + (("  (%s)" % extra) if extra else ""))
    else:
        _f += 1
        print("  \033[31mFAIL\033[0m  " + label + (("  (%s)" % extra) if extra else ""))


def walk(cfg, kind, **extra):
    """كل صفحات كتالوجٍ كما يطلبها Stremio: ‏skip = ما وصل، وتتوقّف عند صفحةٍ أقلّ من 100."""
    out, pages = [], 0
    while True:
        page = S.catalog(cfg, kind, S.CATALOG[kind], {**extra, "skip": str(len(out))})["metas"]
        pages += 1
        out += page
        if len(page) < S.PAGE or pages > 500:
            return out, pages


# ================= بلا شبكة =================
def unit():
    print("== الهوست والرمز ==")
    check("هوست بلا بروتوكول ← http", S.norm_host("mrha.ink:80") == "http://mrha.ink:80")
    check("المسار والشرطة الأخيرة تُحذف والحروف تصغر", S.norm_host("HTTP://Mrha.INK:8080/get.php?x=1") == "http://mrha.ink:8080")
    check("https يبقى", S.norm_host("https://a.b.c") == "https://a.b.c")
    check("ما ليس هوستًا يُرفض", all(S.norm_host(x) is None for x in ("", "ftp://a.b", "http://u:p@a.b", "http://a b", "http://a.b:99999")))
    check("مفتاح القائمة المسموحة: الاسم وحده", S.host_key("http://Mrha.ink:80/") == "mrha.ink" == S.host_key("mrha.ink:2095"))

    d = tempfile.mkdtemp(prefix="stremio_key_")
    try:
        t = S.make_token(d, "mrha.ink:80", "0501", "pw!/+&")
        cfg = S.read_token(d, t)
        check("الرمز يُفكّ إلى بياناته", cfg == S.Cfg("http://mrha.ink:80", "0501", "pw!/+&"), str(cfg))
        check("الرمز صالحٌ في العنوان (base64 للعناوين بلا حشو)", all(c.isalnum() or c in "-_" for c in t), t)
        check("البيانات لا تظهر في الرمز", "0501" not in t and "mrha" not in t)
        check("الاشتراك نفسه = الرمز نفسه (لا تتكرّر الإضافة في Stremio)", S.make_token(d, "http://mrha.ink:80/", "0501", "pw!/+&") == t)
        check("اشتراكٌ آخر = رمزٌ آخر", S.make_token(d, "mrha.ink:80", "0502", "pw!/+&") != t)
        bad = t[:10] + ("A" if t[10] != "A" else "B") + t[11:]
        check("حرفٌ معبوثٌ به يُرفض", S.read_token(d, bad) is None)
        check("رمزٌ قصير أو بحروفٍ غريبة يُرفض", S.read_token(d, "abc") is None and S.read_token(d, t + "!") is None)
        d2 = tempfile.mkdtemp(prefix="stremio_key2_")
        check("رمزٌ من خادمٍ آخر (مفتاحٌ آخر) يُرفض", S.read_token(d2, t) is None)
        shutil.rmtree(d2, ignore_errors=True)
        import crypto_store
        check("رمز استعمالٍ آخر لا يصلح للإضافة", S.read_token(d, crypto_store.seal_token("a.b\nu\np", d, "other")) is None)
        lk = S.make_token(d, "mrha.ink:80", "0501", "pw!/+&", key="Kx_1-abcd")
        check("رمزٌ بقفل حسابه: البيانات نفسها وقفله معها، ورمزٌ آخر", S.read_token_key(d, lk) == (cfg, "Kx_1-abcd") and lk != t
              and S.read_token(d, lk) == cfg and S.read_token_key(d, t) == (cfg, None))
        check("وقفلٌ آخر = رمزٌ آخر", S.make_token(d, "mrha.ink:80", "0501", "pw!/+&", key="Kx_1-abce") != lk)
        try:
            S.make_token(d, "mrha.ink:80", "0501", "pw", key="a b\n")
            check("قفلٌ بحروفٍ غريبة يُرفض", False)
        except ValueError:
            check("قفلٌ بحروفٍ غريبة يُرفض", True)
        check("رمزٌ بحقلٍ رابعٍ فارغ يُرفض", S.read_token(d, crypto_store.seal_token("a.b\nu\np\n", d, S.LABEL)) is None)
        rt = S.routed(cfg, "new.host:8080")
        check("تحويل الهوست: الطلبات إلى الجديد، وبادئة المعرّفات كما هي (المكتبة و«تابع المشاهدة» تبقى)",
              rt.host == "http://new.host:8080" and rt.origin == cfg.host and S.prefix(rt) == S.prefix(cfg) and rt.user == cfg.user
              and S.routed(rt, "http://third.host") .origin == cfg.host and S.routed(cfg, cfg.host) is cfg, str(rt))
        c, b = S.handle(d, f"/stremio/{lk}/manifest.json", "https://g", None, lambda c_, k: k == "newer")[:2]
        check("رمزٌ أُوقف قفله ← 404 برسالته (قبل أي طلبٍ للسيرفر)", c == 404 and "أُوقف هذا الرابط" in b.decode(), b.decode()[:80])
        for u, p in (("", "p"), ("u", ""), ("u u", "p"), ("u", "p\nx"), ("u" * 200, "p")):
            try:
                S.make_token(d, "a.b", u, p)
                ok = False
            except ValueError:
                ok = True
            check(f"بياناتٌ لا تصلح تُرفض ({u[:6]!r}، {p[:6]!r})", ok)
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print("== رسالة الاشتراك ==")
    check("السطر كما نرسله", S.parse_line("Host http://mrha.ink:80 User 111 Pass 222 Guide https://guide.ssouq.com/#activate/smart")
          == ("http://mrha.ink:80", "111", "222"))
    msg = "📲 طريقة التثبيت\n🔗 شرح التثبيت:\nhttps://guide.ssouq.com/#activate/smart\n\nHost: http://mrha.ink\nUser: 111\nPass: 222\n"
    check("نص الشرح (Host: … على أسطر)", S.parse_line(msg) == ("http://mrha.ink", "111", "222"), str(S.parse_line(msg)))
    check("رابط M3U بصيغة Xtream", S.parse_line("http://a.b:8080/get.php?username=u1&password=p1&type=m3u_plus&output=ts")
          == ("http://a.b:8080", "u1", "p1"))
    check("نصٌّ بلا بيانات ← None", S.parse_line("مرحبا") is None)

    print("== ما يرسله Stremio في المسار ==")
    g = "مسلسلات تركية & مدبلجة / 2026"
    check("التصنيف بحروفه كلها (عربي، &، /) والصفحة", S.parse_extra(f"genre={quote(g, safe='')}&skip=200") == {"genre": g, "skip": "200"})
    check("البحث بمسافاته", S.parse_extra("search=breaking%20bad") == {"search": "breaking bad"})
    check("«Disney+» (قسمٌ حقيقي في سيرفر مرح) بترميزيه: ‏%2B، و+ مسافةً في form-urlencoded",
          S.parse_extra("genre=Disney%2B&skip=100")["genre"] == "Disney+" and S.parse_extra("genre=Sci+Fi")["genre"] == "Sci Fi")

    print("== القوائم: الكبار والترتيب والتصنيفات والبحث ==")
    cats = [{"category_id": "1", "category_name": "أفلام عربية"}, {"category_id": "2", "category_name": "XXX Adults"},
            {"category_id": "3", "category_name": "Kids", "is_adult": 1}, {"category_id": "4", "category_name": "أفلام  عربية"},
            {"category_id": "5", "category_name": "Action"}]
    raw = [{"stream_id": 1, "name": "xXx (2002)", "category_id": "5", "added": "100", "container_extension": "mkv", "rating": "6.1"},
           {"stream_id": 2, "name": "Hidden", "category_id": "2", "added": "900"},
           {"stream_id": 3, "name": "Flagged", "category_id": "1", "added": "800", "is_adult": "1"},
           {"stream_id": 4, "name": "الرسالة", "category_id": "1", "added": "300"},
           {"stream_id": 5, "name": "إبراهيم الأبيض", "category_id": "4", "added": "500", "container_extension": ".MP4"},
           {"stream_id": 6, "name": "Kid film", "category_id": "3", "added": "999"},
           {"stream_id": 4, "name": "dup id", "category_id": "1", "added": "1"},
           {"stream_id": 7, "name": "  ", "category_id": "1"}, "junk",
           {"stream_id": 8, "name": "No category", "category_id": "77", "added": "200"}]
    L = S.Lists("movie", cats, raw)
    ids = [it.id for it in L.items]
    check("قسم الكبار (بالاسم وبعلامة السيرفر) وما علّمه السيرفر يسقط", ids == [1, 4, 5, 8], str(ids))
    check("«xXx» فيلمٌ في قسمٍ عادي: يبقى (لا إسقاط بالعنوان)", L.by_id.get(1) and L.by_id[1].name == "xXx (2002)")
    check("الكل: الأحدث إضافةً أولًا", [it.id for it in L.latest] == [5, 4, 8, 1])
    check("اسم القسم المكرّر قسمٌ واحد بعناصرهما", [it.id for it in L.by_genre["أفلام عربية"]] == [4, 5], str(dict(L.by_genre)))
    check("التصنيفات بترتيب السيرفر وبلا الكبار", L.genres == ["أفلام عربية", "Action"], str(L.genres))
    check("الامتداد والسنة والتقييم", L.by_id[5].ext == "mp4" and L.by_id[1].year == "2002" and L.by_id[1].rating == "6.1")
    check("البحث بلا همزات ولا حالة أحرف", [it.id for it in L.search("ابراهيم")] == [5] and [it.id for it in L.search("XXX")] == [1])
    check("البحث بكلمتين في أي ترتيب", [it.id for it in L.search("الابيض ابراهيم")] == [5])
    big = S.Lists("tv", [{"category_id": "1", "category_name": "C"}],
                  [{"stream_id": i, "name": f"Ch {i}", "category_id": "1"} for i in range(1, 251)])
    check("القنوات بترتيب السيرفر", [it.id for it in big.latest[:3]] == [1, 2, 3])
    rk = S.Lists("movie", [], [{"stream_id": 1, "name": "The Batman Returns", "added": "9"},
                               {"stream_id": 2, "name": "Batman", "added": "1"},
                               {"stream_id": 3, "name": "Batman Begins", "added": "5"}])
    check("ترتيب البحث: المطابق ثم ما يبدأ به ثم ما يحويه", [it.id for it in rk.search("batman")] == [2, 3, 1])

    print("== عناوين الحلقات وتواريخها ==")
    check("«الاسم (السنة) - S01E01» ← «الحلقة 1»", S._ep_title("احتمال حب (2026) - S01E01", "احتمال حب (2026)", 1, 1) == "الحلقة 1")
    check("عنوانٌ للحلقة يبقى", S._ep_title("Breaking Bad S02E03 - Bit by a Dead Bee", "Breaking Bad", 2, 3) == "Bit by a Dead Bee")
    check("تاريخ ISO", S._released("2026-06-18") == "2026-06-18T00:00:00.000Z")
    check("تاريخٌ لا يُفهم يُحذف (لا يُسقط صفحة المسلسل)", S._released("0000-00-00") is None and S._released("") is None)


def raises_auth(fn):
    try:
        fn()
    except S.AuthError:
        return True
    return False


# ================= مقابل السيرفر الوهمي =================
def against_mock():
    srv = mock_xtream.serve(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    host = f"http://127.0.0.1:{srv.server_address[1]}"
    d = tempfile.mkdtemp(prefix="stremio_mock_")
    S.reset()
    try:
        cfg = S.read_token(d, S.make_token(d, host, mock_xtream.USER, mock_xtream.PASS))
        _, vod, series, live = mock_xtream.build(host)
        n_vod = sum(1 for v in vod.values() if v.get("is_adult") != "1")
        n_live = sum(len(v) for v in mock_xtream.CHANNELS.values())
        pre = S.prefix(cfg)

        print("== تحميلٌ واحد مهما تزامنت الطلبات ==")
        before = sum(1 for h in mock_xtream.Handler.hits if h.endswith("action=get_series"))
        ths = [threading.Thread(target=S.lists, args=(cfg, "series")) for _ in range(8)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        n = sum(1 for h in mock_xtream.Handler.hits if h.endswith("action=get_series")) - before
        check("8 طلباتٍ معًا = طلبٌ واحد للسيرفر", n == 1, str(n))

        print("== بحثٌ أسرع: قائمةٌ واحدة لمشتركي الباقة، وتحديثٌ في الخلفية، وفهرسٌ جاهز ==")
        srv.users["u3"] = "p3"
        other = S.Cfg(cfg.host, "u3", "p3")
        hits = lambda: sum(1 for h in mock_xtream.Handler.hits if h.endswith("action=get_series"))
        before = hits()
        Ls, Lo = S.lists(cfg, "series"), S.lists(other, "series")
        check("مشتركٌ آخر بالباقة نفسها على السيرفر نفسه: القائمة نفسها بلا تحميلٍ ثانٍ", Lo is Ls and hits() == before, str(hits() - before))
        check("وفهرس البحث جاهزٌ مع التحميل (أول بحثٍ لا يبنيه)", Ls._keys is not None and len(Ls._keys) == len(Ls.items))
        check("بصمة الباقة: الأقسام نفسها ← البصمة نفسها، وأقسامٌ أخرى ← غيرها",
              S._bouquet([{"category_id": "2"}, {"category_id": "1"}]) == S._bouquet([{"category_id": 1}, {"category_id": 2}])
              != S._bouquet([{"category_id": "1"}]))
        with S._lock:
            key = S._list_keys[(cfg, "series")]
            S._lists[key] = (S._lists[key][0] - S.TTL - 1, Ls)               # قديمة
        t0 = time.time()
        again = S.lists(other, "series")
        quick = time.time() - t0
        for _ in range(50):
            if S._lists[key][1] is not Ls:
                break
            time.sleep(0.05)
        check("قديمةٌ تُعرض فورًا وتُحدَّث في الخلفية (لا ينتظر البحث السيرفر)", again is Ls and quick < 0.5
              and S._lists[key][1] is not Ls and time.time() - S._lists[key][0] < 5, f"{quick:.2f}s")
        info_hits = lambda: sum(1 for h in mock_xtream.Handler.hits if h.endswith("action=get_series_info"))
        sid = S.lists(cfg, "series").items[0].id
        S._details(cfg, "get_series_info", "series_id", sid)
        before = info_hits()
        S._details(other, "get_series_info", "series_id", sid)
        check("وتفاصيل المسلسل واحدةٌ لمشتركي السيرفر", info_hits() == before)
        check("تحميل قوائم اشتراكٍ مسبقًا (الأنواع الثلاثة)", S.warm(other) == 3 and all(S.has_lists(other, k) for k in S.TYPES))
        check("ومشتركٌ يرفضه السيرفر لا يأخذ قائمة غيره", raises_auth(lambda: S.lists(S.Cfg(cfg.host, "u3", "wrong"), "series")))

        print("== قائمةٌ كاملة يتعثّر فيها السيرفر (كاسبر يردّ 503 لأفلامه) ← قسمًا قسمًا ==")
        srv.full_fails = {"get_vod_streams"}
        S.drop_lists(cfg, "movie")
        S.drop_lists(other, "movie")                         # حمّلها التحميل المسبق أعلاه لمشترك الباقة نفسها
        before = sum(1 for h in mock_xtream.Handler.hits if h.endswith("action=get_vod_streams"))
        L = S.lists(cfg, "movie")
        n_parts = sum(1 for h in mock_xtream.Handler.hits if h.endswith("action=get_vod_streams")) - before
        check("كل الأفلام تُجمع من أقسامها (بلا الكبار ولا تكرار)", len(L.items) == n_vod and len({it.id for it in L.items}) == n_vod
              and n_parts == 1 + len(mock_xtream.MOVIES) + 1, f"{len(L.items)} / {n_vod} · {n_parts} طلبات")
        check("والبحث فيها يعمل", [m["name"] for m in S.catalog(cfg, "movie", "sq_movies", {"search": "oppenheimer"})["metas"]] == ["Oppenheimer (2023)"])
        srv.api_down = True
        S.drop_lists(cfg, "movie")
        t0 = time.time()
        try:
            S.lists(cfg, "movie")
            check("وتعثّر الأقسام أيضًا ← خطأ (لا قائمةٌ ناقصة تُحفظ)", False)
        except S.XtreamError:
            check("وتعثّر الأقسام أيضًا ← خطأ (لا قائمةٌ ناقصة تُحفظ)", not S.has_lists(cfg, "movie"), f"{time.time() - t0:.1f}s")
        srv.api_down, srv.full_fails = False, set()
        S.drop_lists(cfg, "movie")

        print("== الـmanifest ==")
        man = S.manifest(cfg, "https://guide.ssouq.com", "سمارت")
        check("الاسم بالسيرفر", man["name"] == "سمارت سوق · سمارت", man["name"])
        check("الأنواع والموارد والبادئة («الحسابات» نوعٌ خاصّ تُطلب تفاصيله وتجديده منّا)",
              man["types"] == [S.ACCOUNTS, "series", "movie", "tv"] and man["idPrefixes"] == [pre]
              and man["resources"][0] == "catalog" and {r["name"] for r in man["resources"][1:]} == {"meta", "stream"}
              and all(r["types"] == man["types"] for r in man["resources"][1:]), str(man["types"]))
        check("بترتيب تطبيقات IPTV: الحسابات ثم المسلسلات ثم الأفلام ثم البث",
              [c["type"] for c in man["catalogs"]] == [S.ACCOUNTS, "series", "movie", "tv"], str([c["type"] for c in man["catalogs"]]))
        cat = {c["type"]: c for c in man["catalogs"]}
        check("«الحسابات» في الرئيسية بلا بحثٍ ولا صفحات (لا تختلط بنتائج البحث)", cat[S.ACCOUNTS]["extra"] == []
              and cat[S.ACCOUNTS]["name"] == S.BRAND and cat[S.ACCOUNTS]["id"] == S.ACCOUNTS_ID)
        check("وخطٌّ مرتبطٌ بحساب Stremio بلاها (صفّها عند صاحب الحساب، فلا يتكرّر)",
              [c["type"] for c in S.manifest(cfg, "https://g", "سمارت", accounts=False)["catalogs"]] == ["series", "movie", "tv"]
              and S.ACCOUNTS not in S.manifest(cfg, "https://g", "", accounts=False)["types"])
        opts = cat["movie"]["extra"][0]["options"]
        n_of = lambda o: int(re.search(r"\(([\d,]+)\)$", o).group(1).replace(",", ""))
        check("أقسام الأفلام كلها تصنيفات", [S._COUNT.sub("", o) for o in opts] == list(mock_xtream.MOVIES), str(opts))
        check("وبجانب كل قسمٍ عدد أفلامه (مجموعها = كل الأفلام بلا الكبار)",
              all(re.search(r" \([\d,]+\)$", o) for o in opts) and sum(map(n_of, opts)) == n_vod, str(opts))
        sopts = cat["series"]["extra"][0]["options"]
        check("أقسام المسلسلات تصنيفاتٌ كذلك بأعدادها", [S._COUNT.sub("", o) for o in sopts] == list(mock_xtream.SERIES)
              and sum(map(n_of, sopts)) == len(series), str(sopts))
        check("اسم السيرفر وعدد المحتوى في اسم كل كتالوج — بلا كلمة النوع (Stremio يُلحقه: «سمارت (10) - المسلسلات»)",
              [c["name"] for c in man["catalogs"][1:]] == [f"سمارت ({len(series)})", f"سمارت ({n_vod})", f"سمارت ({n_live})"],
              str([c["name"] for c in man["catalogs"]]))
        check("وفي وصف الإضافة بالترتيب نفسه", man["description"].startswith(f"{len(series)} مسلسل · {n_vod} فيلم · {n_live} قناة — ")
              and "IPTV" in man["description"], man["description"][:60])
        check("الأعداد بفواصل الآلاف", S._fmt(21293) == "21,293" and S._COUNT.sub("", "أفلام عربية (1,234)") == "أفلام عربية")
        check("إضافةٌ مكتملة", S.build_manifest(cfg, "https://g", "")[1] == "ok")
        nob, st = S.build_manifest(S.Cfg(cfg.host, "nobody", "x"), "https://g", "")
        check("واشتراكٌ يرفضه السيرفر (لم يُفعَّل بعد): تُبنى بلا أقسامٍ ولا أعداد وحالها «pending» فيُعاد بناؤها",
              st == "pending" and [c["name"] for c in nob["catalogs"][1:]] == [S.BRAND] * 3
              and not any(len(c["extra"]) > 2 for c in nob["catalogs"]), st)
        down = mock_xtream.serve(0, api_down=True)
        threading.Thread(target=down.serve_forever, daemon=True).start()
        try:
            st = S.build_manifest(S.Cfg(f"http://127.0.0.1:{down.server_address[1]}", mock_xtream.USER, mock_xtream.PASS), "https://g", "")[1]
        finally:
            down.shutdown()
        check("وسيرفرٌ لا يردّ: «error» (لا فائدة من إعادته فورًا)", st == "error", st)
        empty = S.Cfg(cfg.host, "empty", "x")
        for k in ("series", "tv"):
            S.set_lists(empty, k, S.Lists(k, [], []))
        with S._lock:
            S._list_keys[(empty, "movie")] = S._list_keys[(cfg, "movie")]     # قائمة باقته محمّلةٌ بمحتواها
            S._cats[(empty, "series")] = (time.time(), [])
        e2 = S.Cfg(cfg.host, "empty2", "x")
        with S._lock:
            for k in S.TYPES:
                S._cats[(e2, k)] = (time.time(), [])          # قبلته اللوحة بلا أقسام بعد
        for k in S.TYPES:
            S.set_lists(e2, k, S.Lists(k, [], []))
        check("وقوائم فارغةٌ كلها (يوزرٌ قبلته اللوحة ولم تُسنِد له باقته بعد) كذلك «pending»",
              S.build_manifest(e2, "https://g", "")[1] == "pending")
        S.forget_empty(empty)
        with S._lock:
            kept = [k for k in S.TYPES if S._list_keys.get((empty, k)) in S._lists]
            cats_gone = (empty, "series") not in S._cats
        check("إعادة القراءة تنسى الفارغ وحده (وما حُمّل بمحتواه يبقى)", kept == ["movie"] and cats_gone, str(kept))
        topts = cat["tv"]["extra"][0].get("options") or []
        check("وأقسام القنوات تصنيفاتٌ كذلك بأعدادها (بلا قسم الكبار)، والبحث والصفحات", [e["name"] for e in cat["tv"]["extra"]] == ["genre", "search", "skip"]
              and [S._COUNT.sub("", o) for o in topts] == list(mock_xtream.CHANNELS) and sum(map(n_of, topts)) == n_live, str(topts))
        check("لا تصنيفٌ مطلوب (الكتالوجات في الرئيسية) والبحث والصفحات مدعومة في المحتوى",
              all(not e["isRequired"] for c in man["catalogs"] for e in c["extra"])
              and all({"search", "skip"} <= set(c["extraSupported"]) for c in man["catalogs"][1:]))
        check("زرّ الإعداد (Configure) ظاهرٌ في Stremio (يفتح موقع المتجر)", man["behaviorHints"]["configurable"] is True)
        uid = S.manifest(S.Cfg(cfg.host, "other", "x"), "https://g", "")["id"]
        check("معرّف الإضافة لكل اشتراك (اشتراكان في حسابٍ واحد لا يتصادمان)", uid != man["id"])

        print("== الكتالوجات: كل شيء ==")
        allm, _ = walk(cfg, "movie")
        check("كل الأفلام (بلا الكبار)", len(allm) == n_vod and len({m["id"] for m in allm}) == n_vod, f"{len(allm)} / {n_vod}")
        alls, _ = walk(cfg, "series")
        check("كل المسلسلات", len(alls) == len(series), f"{len(alls)} / {len(series)}")
        allt, _ = walk(cfg, "tv")
        check("كل القنوات (بلا الكبار) في كتالوجها الواحد", len(allt) == n_live, f"{len(allt)} / {n_live}")
        check("بترتيب السيرفر (أقسامها متجاورة)", [m["name"] for m in allt[:2]] == mock_xtream.CHANNELS["beIN SPORTS"][:2], str([m["name"] for m in allt[:2]]))
        old_mf, _ = walk(cfg, "tv", genre="MBC")
        check("وطلب تصنيفٍ من manifest قديم في Stremio ما زال يعمل", [m["name"] for m in old_mf] == mock_xtream.CHANNELS["MBC"])
        check("الأحدث أولًا", allm[0]["name"].startswith("F1 The Movie"), allm[0]["name"])
        g = "مسلسلات تركية مدبلجة"
        gs, _ = walk(cfg, "series", genre=g)
        check("قسمٌ واحد", {m["name"] for m in gs} == {"المؤسس عثمان", "قيامة أرطغرل"}, str([m["name"] for m in gs]))
        gc = next(o for o in sopts if o.startswith(g + " ("))
        check("واسم القسم بعدده كما يرسله Stremio", walk(cfg, "series", genre=gc)[0] == gs, gc)
        check("قسمٌ لا يُعرف = لا شيء", walk(cfg, "movie", genre="nope")[0] == [])
        found = S.catalog(cfg, "series", "sq_series", {"search": "breaking"})["metas"]
        check("البحث", [m["name"] for m in found] == ["Breaking Bad"], str(found))
        m0 = next(m for m in allm if m["name"].startswith("Oppenheimer"))
        check("بطاقة الفيلم: ملصقٌ وسنةٌ وتقييمٌ ومعرّفٌ ببادئة السيرفر",
              m0["id"].startswith(pre + "m:") and m0["poster"].startswith("https://image.tmdb.org") and m0["releaseInfo"] == "2023"
              and m0["imdbRating"] == "8.1", json.dumps(m0, ensure_ascii=False))
        check("كتالوجٌ لا يُعرف ← None", S.catalog(cfg, "movie", "sq_series", {}) is None)

        print("== صفحات 100 كما يعدّها Stremio ==")
        many = S.Lists("movie", [], [{"stream_id": i, "name": f"F{i}", "added": str(i)} for i in range(1, 251)])
        S.set_lists(cfg, "movie", many)
        got, pages = walk(cfg, "movie")
        check("250 فيلمًا = 100 + 100 + 50", len(got) == 250 and pages == 3 and len({m["id"] for m in got}) == 250, f"{len(got)} في {pages}")
        S.drop_lists(cfg, "movie")

        print("== التفاصيل ==")
        mm = S.meta(cfg, "movie", m0["id"])["meta"]
        check("الفيلم من get_vod_info: الممثلون والمخرج والمدة والقصة",
              mm["cast"][:1] == ["Cillian Murphy"] and mm["director"] == ["Christopher Nolan"] and mm["runtime"] == "120 min"
              and mm["description"].startswith("Plot of"), json.dumps(mm, ensure_ascii=False)[:200])
        got_id = next(m["id"] for m in alls if m["name"] == "Game of Thrones")
        sm = S.meta(cfg, "series", got_id)["meta"]
        v = sm["videos"]
        check("المسلسل بمواسمه وحلقاته", len(v) == 6 and [(x["season"], x["episode"]) for x in v][:4] == [(1, 1), (1, 2), (1, 3), (2, 1)],
              str([(x["season"], x["episode"]) for x in v]))
        check("عنوان الحلقة وتاريخها وقصتها", v[0]["title"] == "Episode title 1-1" and v[0]["released"] == "2011-01-01T00:00:00.000Z"
              and v[0]["overview"].startswith("What happens"), json.dumps(v[0], ensure_ascii=False))
        check("معرّف الحلقة يحمل امتدادها", v[0]["id"].startswith(pre + "e:") and v[0]["id"].endswith(":mp4"), v[0]["id"])
        lt = S.meta(cfg, "tv", allt[0]["id"])["meta"]
        check("القناة: اسمها وصورتها مربّعة (بلا logo يحلّ محلّ الاسم في صفحتها)", lt["name"] == allt[0]["name"]
              and lt["posterShape"] == "square" and lt["poster"].endswith(".png") and "logo" not in lt, json.dumps(lt, ensure_ascii=False))
        check("وقسمها وصفًا وتصنيفًا", lt["description"] == "beIN SPORTS" and lt["genres"] == ["beIN SPORTS"]
              and allt[0]["description"] == "beIN SPORTS", json.dumps(lt, ensure_ascii=False))
        check("معرّفٌ لسيرفرٍ آخر أو نوعٌ لا يطابق ← None",
              S.meta(cfg, "movie", "sq000000:m:1") is None and S.meta(cfg, "series", m0["id"]) is None)

        print("== روابط التصنيفات: «جريمة» ← كل ما في الاشتراك منها (لا Cinemeta) ==")
        man_url = "https://g/stremio/TOK/manifest.json"
        mm = S.meta(cfg, "movie", m0["id"], man_url)["meta"]
        gl = [l for l in mm["links"] if l["category"] == "Genres"]
        check("تصنيفات الفيلم روابطُ إلى كتالوجنا مصفًّى بها، بالعربية الموحدة («Drama» ← «دراما»)", [l["name"] for l in gl] == ["دراما", "تاريخي"]
              and gl[0]["url"] == "stremio:///discover/" + quote(man_url, safe="") + "/movie/sq_movies?genre=" + quote("دراما", safe=""),
              json.dumps(gl, ensure_ascii=False)[:200])
        check("والتقييم رابطٌ إلى بحث IMDb بالاسم (يبقى ظاهرًا في صفحته)",
              any(l["category"] == "imdb" and l["name"] == "8.1" and l["url"].startswith("https://imdb.com/find/?q=Oppenheimer") for l in mm["links"]))
        dr = walk(cfg, "movie", genre="Drama")[0]
        exp_dr = [m["name"] for m in allm if "دراما" in m.get("genres", [])]
        check("الضغط على «Drama» ← كل أفلام الدراما بالأحدث (و«دراما» بالعربية معها)", [m["name"] for m in dr] == exp_dr and len(dr) >= 3
              and any(re.search("[a-z]", n.lower()) for n in exp_dr) and any(n.startswith("فيلم عربي") for n in exp_dr), str([m["name"] for m in dr]))
        check("بلا حالة أحرفٍ ولا تشكيل («drama»)، وبالعربية («دراما») النتيجة نفسها",
              walk(cfg, "movie", genre="drama")[0] == dr and walk(cfg, "movie", genre="دراما")[0] == dr)
        ser_g = walk(cfg, "series", genre="تاريخي")[0]
        check("وللمسلسلات (تصنيفها في القائمة بفاصلةٍ عربية)", {m["name"] for m in ser_g} == {"المؤسس عثمان", "قيامة أرطغرل"}, str([m["name"] for m in ser_g]))
        smm = S.meta(cfg, "series", next(m["id"] for m in alls if m["name"] == "المؤسس عثمان"), man_url)["meta"]
        check("ورابطه في صفحة المسلسل", [l["name"] for l in smm["links"] if l["category"] == "Genres"] == ["تاريخي", "دراما"]
              and "/series/sq_series?genre=" in smm["links"][-1]["url"], json.dumps(smm.get("links"), ensure_ascii=False)[:200])
        ltm = S.meta(cfg, "tv", allt[0]["id"], man_url)["meta"]
        check("وقسم القناة رابطٌ إلى كل قنواته", ltm["links"] == [{"name": "beIN SPORTS", "category": "Genres",
              "url": "stremio:///discover/" + quote(man_url, safe="") + "/tv/sq_live?genre=beIN%20SPORTS"}]
              and len(walk(cfg, "tv", genre="beIN SPORTS")[0]) == len(mock_xtream.CHANNELS["beIN SPORTS"]), json.dumps(ltm.get("links")))
        check("وبلا رابط الـmanifest: بلا روابط (والتصنيفات كما هي)", "links" not in S.meta(cfg, "movie", m0["id"])["meta"])
        bare = S.Lists("movie", [], [{"stream_id": 1, "name": "A", "added": "1"}, {"stream_id": 2, "name": "B", "added": "2"}])
        S.note_genre(cfg, 1, "Crime, Drama")
        check("سيرفرٌ لا يذكر التصنيف في القائمة: ما عُرف تصنيفه من تفاصيله (بلغتين: «crime» = «جريمة»)",
              [it.name for it in S._tagged(cfg, "movie", bare, "crime")] == ["A"] == [it.name for it in S._tagged(cfg, "movie", bare, "جريمة")]
              and S._tagged(cfg, "movie", bare, "Horror") == [])
        S.note_genre(cfg, 1, "")

        print("== «الحسابات»: حال كل خطوط الحساب كشاشة الحساب في تطبيقات IPTV ==")
        check("المتبقّي بعدده الصحيح", [S.remaining(n * 86400, now=0) for n in (1, 2, 3, 10, 11, 100, 103, 365)] ==
              ["باقي يوم", "باقي يومان", "باقي 3 أيام", "باقي 10 أيام", "باقي 11 يومًا", "باقي 100 يوم", "باقي 103 أيام", "باقي 365 يومًا"]
              and S.remaining(10, now=20) == "منتهٍ" and S.remaining(86400 + 5, now=0) == "باقي يومان")
        other2 = S.Cfg(host, "u", "p", "http://old.example")       # خطٌّ ثانٍ (سيرفرٌ غيّر عنوانه: معرّفه من الأصلي)
        lines = [{"cfg": cfg, "label": "سمارت", "art": "/static/img/brands/smart.webp"}, {"cfg": other2, "label": "كاسبر"}]
        cards = S.accounts_catalog(lines, pre, "https://g")["metas"]
        c0 = cards[0]
        check("بطاقةٌ لكل خط بترتيبه، باسم سيرفره وكم باقي", [c["name"].split(" · ")[0] for c in cards] == ["سمارت", "كاسبر"]
              and c0["name"].startswith("سمارت · باقي 36") and c0["type"] == S.ACCOUNTS, c0["name"])
        check("شعار السيرفر مربّعًا (وإلا شعار المتجر)", c0["poster"] == "https://g/static/img/brands/smart.webp" and c0["posterShape"] == "square"
              and cards[1]["poster"] == "https://g/static/icons/icon-512.png")
        check("التفاصيل: الحالة والانتهاء والاتصالات واليوزر والمحتوى — بلا كلمة المرور",
              all(x in c0["description"] for x in ("الحالة: نشط", "ينتهي 20", "الاتصالات المسموحة: 1", "اليوزر: u",
                                                    f"المحتوى: {len(series)} مسلسل · {n_vod} فيلم · {n_live} قناة"))
              and mock_xtream.PASS + " " not in c0["description"] and "كلمة" not in c0["description"], c0["description"])
        check("وطريقة الترجمة العربية، وإظهار الأسماء تحت الصور على تلفاز أندرويد (إعدادٌ في التطبيق لا يُضبط من الإضافة)",
              c0["description"].endswith(S.SUBS_TIP + " · " + S.TITLE_TIP) and "Show title under catalog items" in S.TITLE_TIP)
        check("معرّف الخط ببادئة الإضافة ومن سيرفره الأصلي", c0["id"].startswith(pre + "a:") and cards[1]["id"] == S.line_id(pre, other2)
              and S.line_id(pre, other2) == S.line_id(pre, S.Cfg("http://old.example", "u", "p")) != c0["id"])
        am = S.accounts_meta(lines, pre, "https://g", c0["id"])["meta"]
        check("صفحة الخط: حتى تاريخ انتهائه، وتفتح التجديد مباشرة", am["releaseInfo"].startswith("حتى 20")
              and am["behaviorHints"]["defaultVideoId"] == c0["id"], json.dumps(am, ensure_ascii=False)[:200])
        rs = S.accounts_streams(lines, pre, c0["id"])["streams"]
        check("«تجديد الاشتراك» يفتح المتجر في المتصفح", len(rs) == 1 and rs[0]["externalUrl"] == S.CONFIGURE_URL and "url" not in rs[0])
        check("معرّفٌ ليس من خطوط الحساب ← None", S.accounts_meta(lines, pre, "https://g", pre + "a:0000000000") is None
              and S.accounts_streams(lines, pre, "x") is None)
        busy = S.Cfg(host, "u", "p")
        with S._lock:
            S._accounts[busy] = (time.time(), {"auth": 1, "status": "Active", "exp_date": None, "max_connections": "2", "active_cons": "1",
                                               "is_trial": "1"}, {})
        cb = S.account_card({"cfg": busy, "label": ""}, pre, "https://g")
        check("بلا تاريخ انتهاء: «غير محدود»، وتجريبي، والاتصالات المستعملة", cb["name"] == "u · غير محدود"
              and "(تجريبي)" in cb["description"] and "الاتصالات: 1 من 2" in cb["description"] and "releaseInfo" not in cb, json.dumps(cb, ensure_ascii=False))
        with S._lock:
            S._accounts.pop(busy, None)

        print("== التشغيل ==")
        num = m0["id"].rsplit(":", 1)[1]
        st = S.streams(cfg, "movie", m0["id"])["streams"]
        check("الفيلم: ‏/movie/ باليوزر والباسورد وامتداده", st[0]["url"] == f"{host}/movie/u/p/{num}.mkv"
              and st[0]["behaviorHints"]["notWebReady"] is True, st[0]["url"])
        se = S.streams(cfg, "series", v[0]["id"])["streams"]
        check("الحلقة: ‏/series/", se[0]["url"] == f"{host}/series/u/p/{v[0]['id'].split(':')[2]}.mp4", se[0]["url"])
        check("حلقات المسلسل مجموعةٌ واحدة (التشغيل التلقائي للتالية)", se[0]["behaviorHints"]["bingeGroup"] == st[0]["behaviorHints"]["bingeGroup"])
        sl = S.streams(cfg, "tv", allt[0]["id"])["streams"]
        lnum = allt[0]["id"].rsplit(":", 1)[1]
        check("القناة: HLS ثم TS", [x["url"] for x in sl] == [f"{host}/live/u/p/{lnum}.m3u8", f"{host}/live/u/p/{lnum}.ts"], str(sl))
        check("واسم القناة في عنوان التشغيل (لا يُخلط بين القنوات)", all(x["title"].startswith(allt[0]["name"] + "\n") for x in sl),
              str([x["title"] for x in sl]))
        odd = S.read_token(d, S.make_token(d, host, "u/x", "p&y"))
        with S._lock:                                        # قائمته في الذاكرة (السيرفر الوهمي لا يعرف هذا اليوزر)
            S._list_keys[(odd, "movie")] = S._list_keys[(cfg, "movie")]
        check("يوزرٌ أو باسوردٌ بحروفٍ خاصة يُرمَّز في الرابط", "/movie/u%2Fx/p%26y/" in S.streams(odd, "movie", m0["id"])["streams"][0]["url"])

        print("== الحالة والأخطاء ==")
        stt = S.status(cfg, "https://g", "TOK", "سمارت")
        check("حالة الاشتراك والأعداد", stt["ok"] and stt["active"] and stt["exp"] and stt["counts"] == {"movie": n_vod, "series": len(series), "tv": n_live},
              json.dumps(stt, ensure_ascii=False)[:200])
        check("روابط التثبيت", stt["install"] == "stremio://g/stremio/TOK/manifest.json"
              and stt["web"] == "https://web.stremio.com/#/addons?addon=" + quote("https://g/stremio/TOK/manifest.json", safe=""))
        wrong = S.Cfg(host, "u", "bad")
        try:
            S.lists(wrong, "movie")
            ok = False
        except S.AuthError:
            ok = True
        check("اشتراكٌ مرفوض ← AuthError", ok)
        check("وحالته: غير فعّال", S.status(wrong, "https://g", "T")["auth"] is False)
        man2 = S.manifest(wrong, "https://g")
        check("ويُثبَّت مع ذلك (بلا تصنيفات) فيعمل متى جُدِّد", len(man2["catalogs"]) == 4 and all(len(c["extra"]) == 2 for c in man2["catalogs"][1:]))
        card = S.accounts_catalog([{"cfg": wrong, "label": "سمارت"}], S.prefix(wrong), "https://g")["metas"][0]
        check("وبطاقته في «الحسابات»: منتهٍ أو موقوف", card["name"] == "سمارت · منتهٍ أو موقوف" and "جدّده" in card["description"], card["name"])
        S.lists(cfg, "series")                               # في الذاكرة
        srv.api_down = True
        with S._lock:
            key = S._list_keys[(cfg, "series")]
            t, val = S._lists[key]
            S._lists[key] = (t - S.TTL - 1, val)             # انتهى عمرها
        stale = S.catalog(cfg, "series", "sq_series", {})["metas"]
        check("السيرفر سقط والقائمة قديمة: تُعرض كما هي لا تختفي", len(stale) == len(series))
        try:
            S.lists(S.Cfg(host, "u2", "p"), "movie")
            ok = False
        except S.XtreamError:
            ok = True
        check("وبلا نسخةٍ في الذاكرة ← XtreamError", ok)
        srv.api_down = False
    finally:
        srv.shutdown()
        shutil.rmtree(d, ignore_errors=True)


# ================= عبر الخادم =================
def http(base, path, obj=None, method=None, headers=None):
    data = json.dumps(obj).encode() if obj is not None else None
    h = {"Content-Type": "application/json", **(headers or {})}
    r = urllib.request.Request(base + path, data=data, headers=h, method=method or ("POST" if obj is not None else "GET"))
    try:
        x = urllib.request.urlopen(r, timeout=20)
        return x.getcode(), dict(x.headers), x.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def through_server():
    srv = mock_xtream.serve(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    mock = f"127.0.0.1:{srv.server_address[1]}"
    d = tempfile.mkdtemp(prefix="stremio_web_")
    with open(os.path.join(d, "accounts.json"), "w", encoding="utf-8") as f:
        json.dump({"admin": None, "accounts": [{"id": "a1", "name": "MR7", "user": "mr7", "password": "pw123456", "stremio": True,
                                                "gates": [{"id": "g1", "name": "بوابة مرح", "mode": "web", "host": f"http://{mock}"}]},
                                               {"id": "a9", "name": "بلا Stremio", "user": "nost", "password": "pw999999",
                                                "gates": [{"id": "g9", "name": "بوابة كاسبر", "mode": "web", "host": "http://other.example:8080"}]}]},
                  f, ensure_ascii=False)
    env = dict(os.environ, XM_DATA=d, XM_BIND="127.0.0.1", XM_PORT=str(PORT), XM_ADMIN_PASSWORD="adminpw1")
    env.pop("XM_SECRET_KEY", None)
    app = subprocess.Popen([sys.executable, os.path.join(ROOT, "xm_lines.py"), "web"], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{PORT}"
    try:
        for _ in range(80):
            try:
                urllib.request.urlopen(base + "/stremio", timeout=0.3)
                break
            except Exception:
                time.sleep(0.1)

        print("== الصفحة العامة ==")
        c, h, body = http(base, "/stremio")
        check("‏/stremio صفحة", c == 200 and b"api/stremio/link" in body, str(c))
        check("لا تُفهرس ولا ترسل العنوان (فيه رمز الاشتراك)", h.get("X-Robots-Tag", "").startswith("noindex")
              and h.get("Referrer-Policy") == "no-referrer")
        check("بلا عدّاد الزيارات (لا يُسجَّل رابطٌ فيه الرمز)", b"sq.js" not in body and b"/api/hit" not in body)

        print("== رابط التثبيت من رسالة الاشتراك ==")
        c, _, b = http(base, "/api/stremio/link", {"line": f"Host http://{mock} User u Pass p Guide https://guide.ssouq.com/"})
        r = json.loads(b)
        check("رسالة الاشتراك ← رابط", c == 200 and r.get("ok") and r["page"].startswith(base + "/stremio/"), json.dumps(r, ensure_ascii=False)[:160])
        tok = r.get("token", "")
        check("الرابط يحمل روابط التثبيت", r.get("install", "").startswith("stremio://127.0.0.1:") and r.get("manifest", "").endswith("/manifest.json"))
        c, _, b2 = http(base, "/api/stremio/link", {"host": mock, "user": "u", "pass": "p"})
        check("البيانات نفسها مكتوبةً ← الرابط نفسه", c == 200 and json.loads(b2).get("token") == tok)
        c, _, b = http(base, "/api/stremio/link", {"host": "example.com", "user": "u", "pass": "p"})
        check("سيرفرٌ ليس من سيرفراتنا يُرفض (لا تُسأل عناوين الإنترنت)", c == 400 and "ليس من سيرفراتنا" in json.loads(b)["error"])
        c, _, b = http(base, "/api/stremio/link", {"host": "other.example:8080", "user": "u", "pass": "p"})
        check("وسيرفر عميلٍ لم يُفتح له Stremio لا تقبله الصفحة العامة", c == 400 and "ليس من سيرفراتنا" in json.loads(b)["error"])
        c, _, b = http(base, "/api/stremio/link", {"host": mock, "user": "u", "pass": "wrong"})
        check("بياناتٌ يرفضها السيرفر", c == 400 and "رفض" in json.loads(b)["error"], b.decode()[:120])
        c, _, b = http(base, "/api/stremio/link", {"line": "مرحبا"})
        check("نصٌّ بلا بيانات", c == 400)

        print("== ما يصل Stremio ==")
        c, h, b = http(base, f"/stremio/{tok}/manifest.json")
        man = json.loads(b)
        mains = [c_ for c_ in man["catalogs"] if not c_["id"].startswith(S.CAT_PREFIX)]
        check("الـmanifest (ورابطٌ بلا حساب Stremio: «الحسابات» فيه)", c == 200 and man["name"] == "سمارت سوق · سمارت"
              and [c_["type"] for c_ in mains] == [S.ACCOUNTS, S.TILES, "series", "movie", "tv"], man.get("name"))
        rows = [(c_["type"], c_["name"]) for c_ in man["catalogs"] if c_["id"].startswith(S.CAT_PREFIX)]
        order = [c_["type"] for c_ in man["catalogs"]]
        check("تصنيفات سمارت سوق صفوفٌ في الرئيسية بعد كتالوج نوعها («تركي - المسلسلات»)، بلا بحثٍ ولا قائمة تصنيف",
              {("series", "تركي"), ("series", "أجنبي"), ("movie", "عربي"), ("movie", "أجنبي"), ("tv", "رياضة"), ("tv", "عربية")} <= set(rows)
              and order == sorted(order, key=[S.ACCOUNTS, S.TILES, "series", "movie", "tv"].index)
              and all(c_["extraSupported"] == ["skip"] for c_ in man["catalogs"] if c_["id"].startswith(S.CAT_PREFIX)),
              json.dumps(rows, ensure_ascii=False))
        topts_u = next(e["options"] for c_ in mains if c_["id"] == "sq_live" for e in c_["extra"] if e["name"] == "genre")
        check("وقائمة التصنيف في «اكتشف» تصنيفاتنا بأعدادها (لا أقسام كل لوحة؛ والقناة باسمها أيضًا: «MBC Drama» ← «أفلام ومسلسلات»)",
              [S._COUNT.sub("", o) for o in topts_u] == ["رياضة", "عربية", "أفلام ومسلسلات"],
              json.dumps(topts_u, ensure_ascii=False))
        c, _, b = http(base, f"/stremio/{tok}/catalog/series/{S.CAT_PREFIX}s_turkish.json")
        tr_names = {m["name"] for m in json.loads(b)["metas"]}
        check("وصفّ «تركي» عبر المسار: ما في «مسلسلات تركية مدبلجة» كله", c == 200 and tr_names
              and tr_names == {x[0] for x in mock_xtream.SERIES["مسلسلات تركية مدبلجة"]}, str(tr_names))
        c, _, b = http(base, f"/stremio/{tok}/catalog/tv/sq_live/genre={quote('رياضة (1)', safe='')}.json")
        sp = {m["name"] for m in json.loads(b)["metas"]}
        check("والتصنيف من «اكتشف» (باسمه وعدده): قنوات القسمين الرياضيين وحدها", len(sp) >= 6
              and all(n.startswith(("beIN SPORTS", "SSC")) for n in sp), str(sp))
        acc_p = quote(S.ACCOUNTS, safe="")
        c, h, b = http(base, f"/stremio/{tok}/catalog/{acc_p}/{S.ACCOUNTS_ID}.json")
        cards = json.loads(b).get("metas") or []
        check("«الحسابات» عبر المسار (النوع العربي مرمَّزًا): الخط وحده باسم سيرفره، ويُحفظ دقائق",
              c == 200 and len(cards) == 1 and cards[0]["name"].startswith("سمارت · باقي") and "max-age=300" in h.get("Cache-Control", ""),
              b.decode()[:200])
        c, _, b = http(base, f"/stremio/{tok}/meta/{acc_p}/{quote(cards[0]['id'], safe='')}.json")
        c2, _, b2 = http(base, f"/stremio/{tok}/stream/{acc_p}/{quote(cards[0]['id'], safe='')}.json")
        check("وتفاصيله وتجديده", c == 200 and json.loads(b)["meta"]["id"] == cards[0]["id"] and c2 == 200
              and json.loads(b2)["streams"][0]["externalUrl"], b2.decode()[:120])
        c, _, _ = http(base, f"/stremio/{tok}/meta/{acc_p}/x.json")
        check("ومعرّفٌ لا يُعرف ← 404", c == 404)
        check("CORS لـStremio Web", h.get("Access-Control-Allow-Origin") == "*")
        check("الشعار من الموقع نفسه", man["logo"] == base + "/static/icons/icon-512.png")
        g = "مسلسلات تركية مدبلجة"
        c, h, b = http(base, f"/stremio/{tok}/catalog/series/sq_series/genre={quote(g, safe='')}&skip=0.json")
        names = [m["name"] for m in json.loads(b)["metas"]]
        check("كتالوج بتصنيفٍ عربي في المسار", c == 200 and set(names) == {"المؤسس عثمان", "قيامة أرطغرل"}, str(names))
        check("ويُحفظ في Stremio دقائق", "max-age=900" in h.get("Cache-Control", ""))
        c, _, b = http(base, f"/stremio/{tok}/catalog/movie/sq_movies.json")
        metas = json.loads(b)["metas"]
        check("كتالوج بلا إضافات", c == 200 and len(metas) == sum(1 for v in mock_xtream.build("x")[1].values() if v.get("is_adult") != "1"))
        mid = metas[0]["id"]
        c, _, b = http(base, f"/stremio/{tok}/meta/movie/{quote(mid, safe='')}.json")
        mj = json.loads(b)["meta"]
        check("التفاصيل بمعرّفٍ مرمَّز (‏%3A)", c == 200 and mj["id"] == mid)
        check("وروابط تصنيفاته إلى الإضافة نفسها كما ثُبّتت", all(quote(f"{base}/stremio/{tok}/manifest.json", safe="") in l["url"]
              for l in mj.get("links", []) if l["category"] == "Genres") and any(l["category"] == "Genres" for l in mj.get("links", [])))
        c, _, b = http(base, f"/stremio/{tok}/stream/movie/{mid}.json")
        url = json.loads(b)["streams"][0]["url"]
        check("رابط التشغيل يعمل عند السيرفر", c == 200 and url.startswith(f"http://{mock}/movie/u/p/"), url)
        c, _, b = http(base, f"/stremio/{tok}/catalog/series/sq_series/search=breaking.json")
        check("البحث عبر المسار", [m["name"] for m in json.loads(b)["metas"]] == ["Breaking Bad"])
        c, _, b = http(base, f"/stremio/{tok}/status.json")
        st = json.loads(b)
        check("حالة الاشتراك لصفحته", c == 200 and st["ok"] and st["counts"]["series"] == 10 and st["label"] == "سمارت", b.decode()[:160])
        class _Stay(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        try:
            urllib.request.build_opener(_Stay).open(base + f"/stremio/{tok}/configure", timeout=20)
            c, loc = 200, ""
        except urllib.error.HTTPError as e:
            c, loc = e.code, e.headers.get("Location", "")
        check("زرّ Configure في Stremio ← موقع سمارت سوق (لا صفحة التثبيت: لا نسخ رابطٍ ولا تثبيت في حسابٍ آخر)",
              c == 302 and loc == "https://ssouq.com/", f"{c} {loc}")
        c, _, b = http(base, f"/stremio/{tok}")
        check("وصفحة التثبيت برمزها باقيةٌ للأداة", c == 200 and b"<html" in b)
        c, _, _ = http(base, f"/stremio/{tok[:-3]}xyz/manifest.json")
        check("رمزٌ معبوثٌ به ← 404", c == 404)
        c, _, _ = http(base, f"/stremio/{tok}/meta/movie/sq000000:m:1.json")
        check("معرّفٌ ليس لهذا السيرفر ← 404", c == 404)
        c, h, _ = http(base, f"/stremio/{tok}/manifest.json", method="OPTIONS")
        check("OPTIONS (CORS)", c == 204 and h.get("Access-Control-Allow-Origin") == "*")
        c, h, b = http(base, f"/stremio/{tok}/manifest.json", headers={"X-Forwarded-Proto": "https", "Host": "guide.ssouq.com"})
        check("خلف Traefik: الروابط بـhttps ونطاق الموقع", json.loads(b)["logo"] == "https://guide.ssouq.com/static/icons/icon-512.png")

        print("== الحدّ بالساعة ==")
        codes = [http(base, "/api/stremio/link", {"host": mock, "user": "u", "pass": "p"})[0] for _ in range(S.RATE)]
        check("الصفحة العامة: محاولاتٌ كثيرة من عنوانٍ واحد ← 429", 429 in codes, str(codes[-5:]))
    finally:
        app.terminate()
        app.wait(timeout=10)
        srv.shutdown()
        shutil.rmtree(d, ignore_errors=True)


def links_in_tool():
    """الأداة تصنع لكل يوزرٍ رابط تثبيت (الإنشاء والبحث) — من الهوست في سطره."""
    d = tempfile.mkdtemp(prefix="stremio_tool_")
    os.environ["XM_DATA"] = d
    try:
        import xm_lines as X
        X.DATA_DIR = d
        rows = X.with_stremio({"host": "http://mrha.ink"}, [
            {"username": "111", "password": "222", "line": "Host http://falcon.example:8080 User 111 Pass 222"},
            {"username": "333", "password": "444"}, {"username": "555"}])
        print("== روابط الأداة ==")
        check("رابطٌ لكل يوزرٍ له باسورد", bool(rows[0].get("stremio")) and bool(rows[1].get("stremio")) and "stremio" not in rows[2])
        check("على الموقع العام", rows[0]["stremio"].startswith(f"https://{X.SITE_HOST}/stremio/"), rows[0]["stremio"])
        cfg0 = S.read_token(d, rows[0]["stremio"].rsplit("/", 1)[1])
        cfg1 = S.read_token(d, rows[1]["stremio"].rsplit("/", 1)[1])
        check("الهوست من سطر اليوزر (فالكون يعرفه لحظة الإنشاء)", cfg0 == S.Cfg("http://falcon.example:8080", "111", "222"), str(cfg0))
        check("وإلا من البوابة", cfg1 == S.Cfg("http://mrha.ink", "333", "444"), str(cfg1))
        check("بوابةٌ بلا هوست: بلا رابط ولا خطأ", "stremio" not in X.with_stremio({}, [{"username": "1", "password": "2"}])[0])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main():
    unit()
    against_mock()
    through_server()
    links_in_tool()
    print("\n----------------------------------------")
    print("Result: \033[32m%d passed\033[0m, %s" % (_p, ("\033[31m%d failed\033[0m" % _f) if _f else "0 failed"))
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
إضافة Stremio (‏stremio_addon.py): الرمز المختوم، والقوائم كلها بصفحات 100، والتصنيفات والبحث، والتفاصيل
بمواسمها وحلقاتها، وروابط التشغيل — مقابل سيرفر Xtream الوهمي (بلا إنترنت)، ثم المسارات عبر الخادم نفسه:
الصفحة العامة ورابط التثبيت وCORS وما يصل Stremio.

    python tests/test_stremio.py
"""
import json
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

        print("== الـmanifest ==")
        man = S.manifest(cfg, "https://guide.ssouq.com", "سمارت")
        check("الاسم بالسيرفر", man["name"] == "سمارت سوق · سمارت", man["name"])
        check("الأنواع والموارد والبادئة", man["types"] == ["movie", "series", "tv"] and man["idPrefixes"] == [pre]
              and man["resources"][0] == "catalog" and {r["name"] for r in man["resources"][1:]} == {"meta", "stream"})
        cat = {c["type"]: c for c in man["catalogs"]}
        opts = cat["movie"]["extra"][0]["options"]
        check("أقسام الأفلام كلها تصنيفات", opts == list(mock_xtream.MOVIES), str(opts))
        check("أقسام المسلسلات تصنيفاتٌ كذلك", cat["series"]["extra"][0]["options"] == list(mock_xtream.SERIES))
        check("والقنوات كلها تصنيفٌ واحد (بحثٌ وصفحات، بلا قائمة أقسام)", [e["name"] for e in cat["tv"]["extra"]] == ["search", "skip"]
              and cat["tv"]["extraSupported"] == ["search", "skip"], str(cat["tv"]["extra"]))
        check("لا تصنيفٌ مطلوب (الكتالوجات في الرئيسية) والبحث والصفحات مدعومة",
              all(not e["isRequired"] for c in man["catalogs"] for e in c["extra"])
              and all({"search", "skip"} <= set(c["extraSupported"]) for c in man["catalogs"]))
        check("زرّ الإعداد (Configure) يفتح صفحة الاشتراك", man["behaviorHints"]["configurable"] is True)
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
        with S._lock:
            S._lists[(cfg, "movie")] = (time.time(), many)
        got, pages = walk(cfg, "movie")
        check("250 فيلمًا = 100 + 100 + 50", len(got) == 250 and pages == 3 and len({m["id"] for m in got}) == 250, f"{len(got)} في {pages}")
        with S._lock:
            S._lists.pop((cfg, "movie"), None)

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
        check("القناة: اسمها وشعارها", lt["name"] == allt[0]["name"] and lt["posterShape"] == "square" and lt["logo"].endswith(".png"))
        check("معرّفٌ لسيرفرٍ آخر أو نوعٌ لا يطابق ← None",
              S.meta(cfg, "movie", "sq000000:m:1") is None and S.meta(cfg, "series", m0["id"]) is None)

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
        odd = S.read_token(d, S.make_token(d, host, "u/x", "p&y"))
        with S._lock:                                        # قائمته في الذاكرة (السيرفر الوهمي لا يعرف هذا اليوزر)
            S._lists[(odd, "movie")] = S._lists[(cfg, "movie")]
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
        check("ويُثبَّت مع ذلك (بلا تصنيفات) فيعمل متى جُدِّد", len(man2["catalogs"]) == 3 and all(len(c["extra"]) == 2 for c in man2["catalogs"]))
        S.lists(cfg, "series")                               # في الذاكرة
        srv.api_down = True
        with S._lock:
            t, val = S._lists[(cfg, "series")]
            S._lists[(cfg, "series")] = (t - S.TTL - 1, val)  # انتهى عمرها
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
        check("الـmanifest", c == 200 and man["name"] == "سمارت سوق · سمارت" and len(man["catalogs"]) == 3, man.get("name"))
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
        check("التفاصيل بمعرّفٍ مرمَّز (‏%3A)", c == 200 and json.loads(b)["meta"]["id"] == mid)
        c, _, b = http(base, f"/stremio/{tok}/stream/movie/{mid}.json")
        url = json.loads(b)["streams"][0]["url"]
        check("رابط التشغيل يعمل عند السيرفر", c == 200 and url.startswith(f"http://{mock}/movie/u/p/"), url)
        c, _, b = http(base, f"/stremio/{tok}/catalog/series/sq_series/search=breaking.json")
        check("البحث عبر المسار", [m["name"] for m in json.loads(b)["metas"]] == ["Breaking Bad"])
        c, _, b = http(base, f"/stremio/{tok}/status.json")
        st = json.loads(b)
        check("حالة الاشتراك لصفحته", c == 200 and st["ok"] and st["counts"]["series"] == 10 and st["label"] == "سمارت", b.decode()[:160])
        c, _, b = http(base, f"/stremio/{tok}/configure")
        check("زرّ Configure في Stremio ← صفحة الاشتراك", c == 200 and b"<html" in b)
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

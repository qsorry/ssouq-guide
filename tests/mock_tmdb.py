#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TMDB وهمي لاختبارات الإثراء (بلا إنترنت): بحثٌ وتفاصيل ومواسم لأعمالٍ معروفة، بترجماتٍ عربية وبدائل عناوين.

  /3/search/movie|tv?query=&year=&language=     يبحث في العنوان والأصل والترجمات والبدائل (بالتطبيع واحتواءً)
  /3/movie/<id> · /3/tv/<id>                     التفاصيل بـ append_to_response (credits · keywords · translations …)
  /3/tv/<id>/season/<n>                          الحلقات بعناوينها وملخصاتها
  مفتاحٌ غير «testkey»: 401. ويعدّ الطلبات في Handler.hits.

    python tests/mock_tmdb.py 9796
"""
import json
import re
import sys
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

KEY = "testkey"


def _pid(name):
    """معرّف الشخص ثابتٌ باسمه (الشخص الواحد معرّفٌ واحد في كل الأعمال — كما في TMDB)."""
    import hashlib
    return int(hashlib.md5(name.encode("utf-8")).hexdigest()[:6], 16)


def _p(name, pid, job=None, char=None):
    pid = _pid(name)
    d = {"id": pid, "name": name, "original_name": name, "profile_path": f"/p{pid}.jpg"}
    if job:
        d["job"] = job
    if char is not None:
        d["character"] = char
    return d


def _tv(tid, name, orig, year, lang, countries, genres, ar=None, ar_overview="", alts=(), status="Ended", seasons=2, eps=3,
        cast=(), creators=(), companies=(), keywords=(), popularity=50.0, type_="Scripted", writers=(("Some Writer", "Writer"),)):
    return {"id": tid, "name": name, "original_name": orig, "first_air_date": f"{year}-01-10", "last_air_date": f"{year + 1}-05-01",
            "original_language": lang, "origin_country": list(countries), "genres": [{"id": g, "name": GENRE_NAMES[g]} for g in genres],
            "overview": f"{name}: an English overview long enough to be indexed when the time comes, about {name.lower()} and its world, "
                        f"its characters and the conflicts that drive every season of the show forward.",
            "status": status, "type": type_, "vote_average": 8.4, "vote_count": 1200, "popularity": popularity,
            "poster_path": f"/tv{tid}.jpg", "backdrop_path": f"/tvb{tid}.jpg", "episode_run_time": [45],
            "number_of_seasons": seasons, "number_of_episodes": seasons * eps,
            "seasons": [{"season_number": n, "name": f"Season {n}", "episode_count": eps, "air_date": f"{year + n - 1}-01-10", "poster_path": f"/s{tid}{n}.jpg"} for n in range(1, seasons + 1)],
            "translations": {"translations": [{"iso_639_1": "ar", "data": {"name": ar or "", "overview": ar_overview}}]},
            "alternative_titles": {"results": [{"iso_3166_1": "XX", "title": a} for a in alts]},
            "aggregate_credits": {"cast": [dict(_p(n, i + tid * 10), roles=[{"character": c}]) for i, (n, c) in enumerate(cast)],
                                  "crew": [dict(_p(n, tid * 10 + 99 - i if n != "Vince Gilligan" else 1396 * 10 + 50), jobs=[{"job": j}]) for i, (n, j) in enumerate(writers)]},
            "created_by": [_p(n, tid * 10 + 50 + i) for i, n in enumerate(creators)],
            "production_companies": [{"id": tid * 100 + i, "name": c, "logo_path": None, "origin_country": countries[0] if countries else ""} for i, c in enumerate(companies)],
            "networks": [], "keywords": {"results": [{"id": k, "name": "kw"} for k in keywords]},
            "external_ids": {"imdb_id": f"tt{tid:07d}"}, "videos": {"results": [{"site": "YouTube", "type": "Trailer", "key": f"yt{tid}"}]}}


def _movie(mid, title, orig, year, lang, countries, genres, ar=None, ar_overview="", alts=(), cast=(), director="", companies=(), keywords=(), popularity=40.0):
    return {"id": mid, "title": title, "original_title": orig, "release_date": f"{year}-06-15", "original_language": lang,
            "production_countries": [{"iso_3166_1": c, "name": c} for c in countries], "origin_country": list(countries),
            "genres": [{"id": g, "name": GENRE_NAMES[g]} for g in genres],
            "overview": f"{title}: an English overview long enough to be indexed when the time comes, about {title.lower()} and what happens in it, "
                        f"who is in it, and why it matters to the people on screen.",
            "status": "Released", "runtime": 148, "vote_average": 8.0, "vote_count": 5000, "popularity": popularity,
            "poster_path": f"/m{mid}.jpg", "backdrop_path": f"/mb{mid}.jpg",
            "translations": {"translations": [{"iso_639_1": "ar", "data": {"title": ar or "", "overview": ar_overview}}]},
            "alternative_titles": {"titles": [{"iso_3166_1": "XX", "title": a} for a in alts]},
            "credits": {"cast": [_p(n, i + mid * 10, char=c) for i, (n, c) in enumerate(cast)],
                        "crew": ([_p(director, mid * 10 + 77, job="Director")] if director else [])},
            "production_companies": [{"id": mid * 100 + i, "name": c, "logo_path": None, "origin_country": ""} for i, c in enumerate(companies)],
            "keywords": {"keywords": [{"id": k, "name": "kw"} for k in keywords]},
            "external_ids": {"imdb_id": f"tt{mid:07d}"}, "imdb_id": f"tt{mid:07d}",
            "videos": {"results": [{"site": "YouTube", "type": "Trailer", "key": f"yt{mid}"}]}}


GENRE_NAMES = {28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy", 80: "Crime", 18: "Drama", 14: "Fantasy", 36: "History",
               878: "Science Fiction", 10402: "Music", 53: "Thriller", 10762: "Kids", 10759: "Action & Adventure", 10765: "Sci-Fi & Fantasy", 10768: "War & Politics", 10749: "Romance"}

TV = {
    2288: _tv(2288, "Prison Break", "Prison Break", 2005, "en", ["US"], [10759, 80, 18], ar="بريزون بريك", ar_overview="قصة بريزون بريك بالعربية، طويلة بما يكفي لتكون مفيدة للقارئ العربي وللفهرسة لاحقًا. تدور الأحداث في أجواءٍ مشوّقة تجمع بين الدراما والتشويق، وتتطوّر الشخصيات حلقةً بعد حلقة حتى النهاية.",
              alts=["Prison Break: Sequel"], cast=[("Wentworth Miller", "Michael Scofield"), ("Dominic Purcell", "Lincoln Burrows")], creators=["Paul Scheuring"], companies=["20th Century Fox Television"], popularity=90),
    1396: _tv(1396, "Breaking Bad", "Breaking Bad", 2008, "en", ["US"], [18, 80], ar="بريكنج باد", ar_overview="قصة بريكنج باد بالعربية، معلّم كيمياء يتحوّل إلى صناعة المخدرات، طويلة بما يكفي. تدور الأحداث في أجواءٍ مشوّقة تجمع بين الدراما والتشويق، وتتطوّر الشخصيات حلقةً بعد حلقة حتى النهاية.",
              cast=[("Bryan Cranston", "Walter White"), ("Aaron Paul", "Jesse Pinkman")], creators=["Vince Gilligan"], companies=["Sony Pictures Television"], popularity=95,
              writers=(("Vince Gilligan", "Writer"), ("Some Writer", "Screenplay"))),
    37854: _tv(37854, "One Piece", "ONE PIECE", 1999, "ja", ["JP"], [10759, 16, 35], ar="ون بيس", ar_overview="مغامرات لوفي وطاقم قبعة القش بحثًا عن الكنز الأسطوري ون بيس، قصة طويلة بما يكفي. تدور الأحداث في أجواءٍ مشوّقة تجمع بين الدراما والتشويق، وتتطوّر الشخصيات حلقةً بعد حلقة حتى النهاية.",
               status="Returning Series", cast=[("Mayumi Tanaka", "Monkey D. Luffy (voice)")], companies=["Toei Animation"], keywords=[210024], popularity=200, seasons=3, eps=40),
    1429: _tv(1429, "Attack on Titan", "進撃の巨人", 2013, "ja", ["JP"], [10759, 16, 10765], ar="هجوم العمالقة", ar_overview="البشر يعيشون خلف جدران عملاقة خوفًا من العمالقة، قصة طويلة بما يكفي للفهرسة. تدور الأحداث في أجواءٍ مشوّقة تجمع بين الدراما والتشويق، وتتطوّر الشخصيات حلقةً بعد حلقة حتى النهاية.",
              alts=["Shingeki no Kyojin"], cast=[("Yuki Kaji", "Eren Yeager (voice)")], companies=["Wit Studio"], keywords=[210024], popularity=150),
    89456: _tv(89456, "Kuruluş Osman", "Kuruluş Osman", 2019, "tr", ["TR"], [18, 10759, 36], ar="المؤسس عثمان", ar_overview="قصة عثمان بن أرطغرل ونشأة الدولة العثمانية، مسلسل تركي تاريخي طويل القصة بما يكفي. تدور الأحداث في أجواءٍ مشوّقة تجمع بين الدراما والتشويق، وتتطوّر الشخصيات حلقةً بعد حلقة حتى النهاية.",
               alts=["Osman the Founder", "Kurulus Osman"], status="Returning Series", cast=[("Burak Özçivit", "Osman Bey")], companies=["Bozdağ Film"], popularity=80, seasons=6, eps=5),
    120089: _tv(120089, "Love Is in the Air", "Sen Çal Kapımı", 2020, "tr", ["TR"], [35, 18, 10749], ar="أنت اطرق بابي", ar_overview="قصة إيدا وسركان، مسلسل تركي رومانسي كوميدي، طويلة بما يكفي للفهرسة لاحقًا. تدور الأحداث في أجواءٍ مشوّقة تجمع بين الدراما والتشويق، وتتطوّر الشخصيات حلقةً بعد حلقة حتى النهاية.",
                alts=["Sen Cal Kapimi", "طبيعة الحب"], cast=[("Hande Erçel", "Eda Yıldız")], companies=["MF Yapım"], popularity=70),
    2316: _tv(2316, "The Office", "The Office", 2005, "en", ["US"], [35], ar="ذا أوفيس", cast=[("Steve Carell", "Michael Scott")], popularity=120),
    2996: _tv(2996, "The Office", "The Office", 2001, "en", ["GB"], [35], ar="ذا أوفيس", cast=[("Ricky Gervais", "David Brent")], popularity=40),
    1399: _tv(1399, "Game of Thrones", "Game of Thrones", 2011, "en", ["US"], [10765, 18, 10759], ar="صراع العروش", ar_overview="صراع العائلات النبيلة على العرش الحديدي، قصة طويلة بما يكفي. تدور الأحداث في أجواءٍ مشوّقة تجمع بين الدراما والتشويق، وتتطوّر الشخصيات حلقةً بعد حلقة حتى النهاية.",
              cast=[("Emilia Clarke", "Daenerys Targaryen")], creators=["David Benioff"], companies=["HBO"], popularity=180, seasons=8, eps=10),
    99001: _tv(99001, "Super Wings", "Super Wings", 2014, "ko", ["KR", "CN"], [16, 10762], ar="سوبر وينجز", cast=[], companies=["FunnyFlux"], popularity=20),
    99002: _tv(99002, "Batman Beyond", "Batman Beyond", 1999, "en", ["US"], [16, 10759], ar="باتمان", cast=[], companies=["Warner Bros. Animation"], popularity=30),
    98001: _tv(98001, "Forbidden Fruit", "Yasak Elma", 2018, "tr", ["TR"], [18, 35], ar="التفاح الحرام", ar_overview="قصة يلدز وزينب الأختين في عالم الأثرياء، مسلسل تركي درامي كوميدي طويل القصة بما يكفي للفهرسة.",
               alts=["Yasak Elma", "Altın Kızlar"], status="Ended", cast=[("Eda Ece", "Yıldız")], companies=["Medyapım"], popularity=60, seasons=6, eps=5),
    98002: _tv(98002, "D.Gray-man Hallow", "D.Gray-man HALLOW", 2016, "ja", ["JP"], [16, 10759, 10765], ar="دي غراي مان هالو", ar_overview="أليـن ووكر والمعزوفين في مواجهة إيرل الألفية، أنمي ياباني طويل القصة بما يكفي للفهرسة لاحقًا.",
               alts=["D.Gray-man Hallow"], cast=[("Ayumu Murase", "Allen Walker (voice)")], companies=["TMS Entertainment"], keywords=[210024], popularity=25),
    # عيّنة الإنتاج الثانية: اسمٌ عربي عام لعملين (تركي وسوري/سعودي) — والأصلي اللاتيني في القائمة يفصل
    153515: _tv(153515, "Mahkum", "Mahkum", 2021, "tr", ["TR"], [80, 18], ar="السجين", ar_overview="فرات ضابطٌ تركي يُتَّهم ظلمًا ويُسجن، دراما تركية طويلة القصة بما يكفي للفهرسة لاحقًا في الصفحات.",
                alts=["The Prisoner"], cast=[("Onur Tuna", "Fırat")], popularity=40, seasons=2, eps=4),
    99006: _tv(99006, "Al Sajeen", "السجين", 2015, "ar", ["SY"], [18], ar="السجين", ar_overview="مسلسل سوري عن سجينٍ يعود إلى حيّه القديم بعد سنوات، دراما اجتماعية طويلة القصة بما يكفي للفهرسة لاحقًا.",
               cast=[("Bassem Yakhour", "Abu Saleem")], popularity=15, seasons=1, eps=30),
    99007: _tv(99007, "Söz", "Söz", 2017, "tr", ["TR"], [18, 10759], ar="العهد", ar_overview="وحدةٌ عسكرية تركية خاصة في مهمات، مسلسل أكشن ودراما طويل القصة بما يكفي للفهرسة لاحقًا في الصفحات.",
               alts=["SOZ", "The Oath"], cast=[("Tolga Sarıtaş", "Yavuz")], popularity=45, seasons=3, eps=4),
    281452: _tv(281452, "Alahed", "العهد", 2018, "ar", ["SY"], [18], ar="العهد", ar_overview="مسلسل سوري اجتماعي عن عهدٍ بين صديقين تتبدّل به الأقدار، دراما طويلة القصة بما يكفي للفهرسة لاحقًا.",
                cast=[("Mohamed Zuhair Ragab", "")], popularity=12, seasons=1, eps=32),
    # مصفوفة الأنمي: ياباني (1429 · 37854) · صيني · كوري · رسومٌ إسبانية (ليست أنمي) · رسومٌ أمريكية (99002) · رسومٌ بلا بلدٍ ولا لغة
    99004: _tv(99004, "The King's Avatar", "全职高手", 2017, "zh", ["CN"], [16, 10759], ar="الأفاتار الملك", ar_overview="يي شيو لاعبٌ محترف يبدأ من الصفر في عالم لعبة غلوري، دونغهوا صيني طويل القصة بما يكفي للفهرسة لاحقًا.",
               alts=["Quanzhi Gaoshou"], keywords=[210024], popularity=35),
    99005: _tv(99005, "Lookism", "외모지상주의", 2022, "ko", ["KR"], [16, 18], ar="لوكيزم", ar_overview="طالبٌ يستيقظ بجسدٍ ثانٍ وسيم، رسوم كورية مقتبسة من ويبتون، طويلة القصة بما يكفي للفهرسة لاحقًا.",
               popularity=28),
    87846: _tv(87846, "The Idhun Chronicles", "Memorias de Idhún", 2020, "es", ["ES"], [16, 10765, 10759], ar="ذكريات إيدون", ar_overview="ثلاثة شبان يقاومون طاغية عالم إيدون السحري، رسوم إسبانية مقتبسة من روايات لاورا غاييغو، طويلة القصة بما يكفي للفهرسة لاحقًا.",
               keywords=[210024], popularity=22),
    99008: _tv(99008, "Mystery Toon", "Mystery Toon", 2010, "", [], [16], ar="ميستري تون", keywords=[210024], popularity=5),
    # One Piece الحيّ (2023): الاسم نفسه والترجمة العربية نفسها — السنة أو مواسم القائمة أو قرينة «أنمي» تفصل
    111110: _tv(111110, "ONE PIECE", "ONE PIECE", 2023, "en", ["US", "JP"], [10759, 18], ar="ون بيس", ar_overview="اقتباسٌ حيّ لمغامرات لوفي وطاقم قبعة القش، قصة طويلة بما يكفي للفهرسة لاحقًا في الصفحات بكل تفاصيلها.",
                status="Returning Series", cast=[("Iñaki Godoy", "Monkey D. Luffy"), ("Wentworth Miller", "Cameo")], companies=["Tomorrow Studios"], popularity=150, seasons=2, eps=8),
    99009: _tv(99009, "Stub Show", "Stub Show", 2020, "ar", ["JO"], [18], ar="مسلسل ناقص", seasons=1, eps=1, popularity=3),
}
MOVIES = {
    438631: _movie(438631, "Dune", "Dune", 2021, "en", ["US"], [878, 12], ar="كثيب", ar_overview="بول أتريديس ينتقل إلى كوكب أراكيس الصحراوي، قصة طويلة بما يكفي للفهرسة. تدور الأحداث في أجواءٍ مشوّقة تجمع بين الدراما والتشويق، وتتطوّر الشخصيات حلقةً بعد حلقة حتى النهاية.",
                   alts=["Dune: Part One"], cast=[("Timothée Chalamet", "Paul Atreides"), ("Zendaya", "Chani")], director="Denis Villeneuve", companies=["Legendary Pictures"], popularity=120),
    841: _movie(841, "Dune", "Dune", 1984, "en", ["US"], [878, 12], ar="الكثيب", cast=[("Kyle MacLachlan", "Paul Atreides")], director="David Lynch", popularity=30),
    297762: _movie(297762, "Wonder Woman", "Wonder Woman", 2017, "en", ["US"], [28, 12, 14], ar="المرأة الخارقة", ar_overview="ديانا أميرة الأمازون تغادر جزيرتها لتقاتل في الحرب العالمية، قصة طويلة بما يكفي. تدور الأحداث في أجواءٍ مشوّقة تجمع بين الدراما والتشويق، وتتطوّر الشخصيات حلقةً بعد حلقة حتى النهاية.",
                   cast=[("Gal Gadot", "Diana Prince")], director="Patty Jenkins", companies=["Warner Bros. Pictures"], popularity=100),
    872585: _movie(872585, "Oppenheimer", "Oppenheimer", 2023, "en", ["US", "GB"], [18, 36], ar="أوبنهايمر", ar_overview="قصة روبرت أوبنهايمر وصنع القنبلة الذرية، طويلة بما يكفي للفهرسة لاحقًا. تدور الأحداث في أجواءٍ مشوّقة تجمع بين الدراما والتشويق، وتتطوّر الشخصيات حلقةً بعد حلقة حتى النهاية.",
                   cast=[("Cillian Murphy", "J. Robert Oppenheimer")], director="Christopher Nolan", companies=["Universal Pictures"], popularity=150),
    693134: _movie(693134, "Dune: Part Two", "Dune: Part Two", 2024, "en", ["US"], [878, 12], ar="كثيب: الجزء الثاني", cast=[("Timothée Chalamet", "Paul Atreides")], director="Denis Villeneuve", popularity=160),
    900001: _movie(900001, "One Piece Film: Red", "ONE PIECE FILM RED", 2022, "ja", ["JP"], [16, 28, 12], ar="ون بيس فيلم: ريد", cast=[("Mayumi Tanaka", "Luffy (voice)")], director="Goro Taniguchi", companies=["Toei Animation"], keywords=[210024], popularity=60),
    8870: _movie(8870, "Wayne's World", "Wayne's World", 1992, "en", ["US"], [35, 10402], ar="عالم واين", ar_overview="واين وغارث يقدّمان برنامجًا تلفزيونيًا من القبو، كوميديا موسيقية طويلة القصة بما يكفي للفهرسة لاحقًا.",
                 cast=[("Mike Myers", "Wayne Campbell")], director="Penelope Spheeris", popularity=45),
    99003: _movie(99003, "Heart of Stone", "Heart of Stone", 2023, "en", ["US"], [28, 53], ar="قلب من حجر", ar_overview="عميلة استخبارات تحاول حماية سلاح خطير، فيلم أكشن طويل القصة بما يكفي للفهرسة لاحقًا.",
                  cast=[("Gal Gadot", "Rachel Stone")], director="Tom Harper", popularity=55),
}


def norm(s):
    s = unicodedata.normalize("NFKC", s or "").casefold().replace("'", "").replace("\u2019", "")   # TMDB يبحث بتسامح مع الفاصلة العليا
    return " ".join(re.sub(r"[\W_]+", " ", s).split())


def _names(d):
    out = [d.get("title") or d.get("name"), d.get("original_title") or d.get("original_name")]
    out += [t.get("title") for t in (d.get("alternative_titles") or {}).get("titles") or (d.get("alternative_titles") or {}).get("results") or []]
    out += [(t.get("data") or {}).get("title") or (t.get("data") or {}).get("name") for t in (d.get("translations") or {}).get("translations") or []]
    return [norm(x) for x in out if x]


def search(table, q, year):
    qn = norm(q)
    res = []
    for d in table.values():
        date = d.get("release_date") or d.get("first_air_date") or ""
        y = int(date[:4]) if date[:4].isdigit() else 0
        if year and y and abs(y - int(year)) > 1:
            continue
        names = _names(d)
        if any(n == qn for n in names) or (len(qn) >= 4 and any(qn in n or n in qn for n in names)):
            r = {k: v for k, v in d.items() if k in ("id", "title", "name", "original_title", "original_name", "release_date", "first_air_date", "popularity", "poster_path")}
            res.append(r)
    res.sort(key=lambda r: -r.get("popularity", 0))
    return res


class Handler(BaseHTTPRequestHandler):
    hits = []

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlsplit(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        Handler.hits.append(u.path)
        if q.get("api_key") != KEY:
            return self._send(401, {"status_code": 7, "status_message": "Invalid API key"})
        if self.server.down:
            return self._send(503, {"status_message": "down"})
        m = re.fullmatch(r"/3/search/(movie|tv)", u.path)
        if m:
            table = MOVIES if m.group(1) == "movie" else TV
            return self._send(200, {"page": 1, "results": search(table, q.get("query", ""), q.get("year") or q.get("first_air_date_year"))})
        m = re.fullmatch(r"/3/tv/(\d+)/season/(\d+)", u.path)
        if m:
            d = TV.get(int(m.group(1)))
            if not d:
                return self._send(404, {"status_code": 34})
            n = int(m.group(2))
            eps = [{"episode_number": e, "name": f"{d['name']} — Episode {e}", "overview": f"In episode {e} of season {n}, things happen that are described here in enough words to be a real summary.",
                    "air_date": f"{2000 + n}-02-{e:02d}", "runtime": 44, "still_path": f"/st{n}{e}.jpg"} for e in range(1, (d["seasons"][0]["episode_count"] if d["seasons"] else 3) + 1)]
            return self._send(200, {"season_number": n, "overview": f"Season {n} overview", "episodes": eps,
                                    "translations": {"translations": [{"iso_639_1": "ar", "data": {"overview": f"ملخص الموسم {n}"}}]}})
        m = re.fullmatch(r"/3/(movie|tv)/(\d+)", u.path)
        if m:
            d = (MOVIES if m.group(1) == "movie" else TV).get(int(m.group(2)))
            return self._send(200, d) if d else self._send(404, {"status_code": 34, "status_message": "not found"})
        return self._send(404, {"status_code": 34})


def serve(port, down=False):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.down = down
    return srv


if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 9796).serve_forever()

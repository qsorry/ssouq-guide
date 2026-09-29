#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""سيرفر Xtream وهمي لاختبارات صفحة المحتوى: قائمة M3U (‏get.php) وواجهته (‏player_api.php) وصور القنوات.

  get.php?username=u&password=p           قائمة M3U: أفلام ومسلسلات بحلقاتها وقنوات وقسمٌ للكبار
  player_api.php?…&action=get_vod_streams  تقييم الأفلام وتاريخ إضافتها وتصنيفها، وفيلمٌ معلَّمٌ للكبار
  player_api.php?…&action=get_series       تصنيف المسلسلات وقصتها وتقييمها وتاريخ آخر حلقة
  images/<الاسم>.png                        صورةٌ مولَّدة (للمرور بخادمنا)
  وكلمة مرورٍ أخرى: 403 (اشتراكٌ منتهٍ)، وwant=api-down: الواجهة 500 والقائمة سليمة.

الملصقات على TMDB لأسماءٍ معروفة — لا تُطلب في الاختبارات (بلا إنترنت تظهر الحروف الأولى مكانها).

    python tests/mock_xtream.py 9790
"""
import json
import struct
import sys
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

USER, PASS = "u", "p"
NOW = int(time.time())
DAY = 86400
TMDB = "https://image.tmdb.org/t/p/w600_and_h900_bestv2"

# (الاسم، السنة، ملصق TMDB، التقييم، التصنيف، منذ كم يومٍ أضيف)
MOVIES = {
    "English Movies 2026 - أفلام": [
        ("F1 The Movie", 2025, "/9PXZIUsSDh4alB80jheWX4fhZmy.jpg", 7.8, "Action, Drama", 1),
        ("M3GAN 2.0", 2025, "/oekamLQrwlJjRNmfaBE4llIvkir.jpg", 6.9, "Horror, Sci-Fi", 2),
        ("The Fantastic Four: First Steps", 2025, "/nf5qaSEvyYSNeFH0YhSs5EsBLX9.jpg", 7.4, "Action, Adventure", 3),
        ("How to Train Your Dragon", 2025, "/5uiXWKH2dcWcQDP2GVFLGTmcGRp.jpg", 7.6, "Adventure, Family", 4),
        ("Mission: Impossible - The Final Reckoning", 2025, "/iKPsC9EFUafRP9SrUznI61getVP.jpg", 7.4, "Action, Thriller", 6),
        ("Dune: Part Two", 2024, "/6izwz7rsy95ARzTR3poZ8H6c5pp.jpg", 8.2, "Sci-Fi, Adventure", 40),
        ("Deadpool & Wolverine", 2024, "/8cdWjvZQUExUUTzyp4t6EDMubfO.jpg", 7.7, "Action, Comedy", 45),
        ("Oppenheimer", 2023, "/8Gxv8gSFCU0XGDykEGv7zR1n2ua.jpg", 8.1, "Drama, History", 120),
        ("Inside Out 2", 2024, "/vpnVM9B6NMmQpWeZvzLvDESb2QY.jpg", 7.6, "Animation, Family", 60),
        ("Gladiator II", 2024, "/2cxhvwyEwRlysAmRH4iodkvo0z5.jpg", 6.8, "Action, Drama", 50),
        ("Wicked", 2024, "/xDGbZ0JJ3mYaGKy4Nzd9Kph6M9L.jpg", 7.2, "Fantasy, Musical", 55),
        ("Moana 2", 2024, "/aLVkiINlIeCkcZIzb7XHzPYgO6L.jpg", 6.9, "Animation, Adventure", 58),
    ],
    "Netflix Movies - أفلام نتفلكس": [
        ("The Electric State", 2025, "/sI2NiMU8o65hmIMY0JI9CjJ0p7f.jpg", 6.0, "Action, Sci-Fi", 20),
        ("Carry-On", 2024, "/sjMN7DRi4sGiledsmllEw5HJjPy.jpg", 6.5, "Action, Thriller", 70),
        ("Rebel Ridge", 2024, "/xEt2GSz9z5rSVpIHMiGdtf0czyf.jpg", 6.8, "Action, Crime", 80),
        ("Damsel", 2024, "/AgHbB9DCE9aE57zkHjSmseszh6e.jpg", 6.1, "Action, Fantasy", 90),
        ("Atlas", 2024, "/b65qmSkIse1ja5bk6piVEZO2IFE.jpg", 5.6, "Sci-Fi, Thriller", 95),
        ("The Platform 2", 2024, "/tvIpBg12IIA5Dr9Sjn38ygS1vQp.jpg", 5.4, "Horror, Sci-Fi", 100),
    ],
    "أفلام عربية": [(f"فيلم عربي {i}", 2015 + i % 11, "", round(5 + i % 4 + .3, 1), "دراما", 200 + i) for i in range(1, 15)],
}
# (الاسم، ملصق TMDB، المواسم، حلقات الموسم، التقييم، التصنيف، سنة البداية، منذ كم يومٍ آخر حلقة)
SERIES = {
    "مسلسلات أجنبية": [
        ("Game of Thrones", "/1XS1oqL89opfnbLl8WnZY1O1uJx.jpg", 8, 10, 9.2, "Drama, Fantasy", 2011, 400),
        ("Breaking Bad", "/anFx9aTOOYqgS3v7x3R84Kz67ly.jpg", 5, 13, 9.5, "Crime, Drama", 2008, 500),
        ("Stranger Things", "/uOOtwVbSr4QDjAGIifLDwpb2Pdl.jpg", 5, 9, 8.6, "Drama, Sci-Fi", 2016, 3),
        ("The Last of Us", "/dmo6TYuuJgaYinXBPjrgG9mB5od.jpg", 2, 9, 8.7, "Drama, Adventure", 2023, 30),
        ("Wednesday", "/9PFonBhy4cQy7Jz20NpMygczOkv.jpg", 2, 8, 8.1, "Comedy, Fantasy", 2022, 8),
        ("House of the Dragon", "/7V0Ebks0GgpKvQ7QbLAIdX5dos4.jpg", 2, 10, 8.4, "Drama, Fantasy", 2022, 90),
        ("Squid Game", "/1QdXdRYfktUSONkl1oD5gc6Be0s.jpg", 3, 7, 7.9, "Drama, Thriller", 2021, 5),
        ("Money Heist", "/reEMJA1uzscCbkpeRJeTT2bjqUp.jpg", 5, 10, 8.2, "Crime, Drama", 2017, 700),
    ],
    "مسلسلات تركية مدبلجة": [
        ("المؤسس عثمان", "/tu4BWsGFHcYDWulZwHxylA91vo0.jpg", 6, 30, 8.1, "تاريخي، دراما", 2019, 1),
        ("قيامة أرطغرل", "/rOar34cNLn2sgDH5FmAa1bvMpBv.jpg", 5, 30, 8.3, "تاريخي، دراما", 2014, 900),
    ],
}
CHANNELS = {
    "beIN SPORTS": [f"beIN SPORTS {i} HD" for i in range(1, 6)] + ["beIN SPORTS 1 FHD"],
    "MBC": ["MBC 1", "MBC 2", "MBC 3", "MBC 4", "MBC Action", "MBC Drama"],
    "SSC": ["SSC 1", "SSC 2", "SSC Extra"],
}
ADULT = {"XXX | Adults": ["Hot Stuff", "Night Club"]}
PLOTS = {"Breaking Bad": "معلّم كيمياء يتحوّل إلى صانع مخدرات بعد تشخيص مرضه.",
         "المؤسس عثمان": "قصة عثمان بن أرطغرل وتأسيس الدولة العثمانية."}


def build(host):
    """← (نص M3U، {رقم الفيلم: بياناته في الواجهة}، [المسلسلات في الواجهة]) بأرقامٍ تصاعدية: الأحدث أكبر."""
    lines, vod, series, sid = ["#EXTM3U"], {}, [], 100
    for group, items in CHANNELS.items():
        for name in items:
            sid += 1
            lines += [f'#EXTINF:-1 tvg-id="" tvg-name="{name}" tvg-logo="{host}/images/{sid}.png" group-title="{group}",{name}',
                      f"{host}/{USER}/{PASS}/{sid}"]
    for group, items in ADULT.items():
        for name in items:
            sid += 1
            lines += [f'#EXTINF:-1 group-title="{group}",{name}', f"{host}/{USER}/{PASS}/{sid}"]
    flat = [(g, m) for g, items in MOVIES.items() for m in items]
    for group, (name, year, poster, rating, genre, ago) in sorted(flat, key=lambda x: -x[1][5]):   # الأقدم أولًا
        sid += 1
        logo = TMDB + poster if poster else f"{host}/images/{sid}.png"
        title = f"{name} ({year})"
        lines += [f'#EXTINF:-1 tvg-name="{title}" tvg-logo="{logo}" group-title="{group}",{title}',
                  f"{host}/movie/{USER}/{PASS}/{sid}.mkv"]
        vod[sid] = {"num": sid, "name": title, "stream_type": "movie", "stream_id": sid, "stream_icon": logo,
                    "rating": str(rating), "rating_5based": rating / 2, "added": str(NOW - ago * 86400), "genre": genre,
                    "is_adult": "0", "category_id": "1", "container_extension": "mkv"}
    sid += 1                                   # فيلمٌ في قسمٍ عادي تعلّمه الواجهة للكبار: يُسقط بالإثراء
    lines += ['#EXTINF:-1 group-title="أفلام عربية",Hidden Adult Film', f"{host}/movie/{USER}/{PASS}/{sid}.mp4"]
    vod[sid] = {"stream_id": sid, "name": "Hidden Adult Film", "is_adult": "1"}
    flat = [(g, s) for g, items in SERIES.items() for s in items]
    for group, (name, poster, seasons, eps, rating, genre, year, ago) in sorted(flat, key=lambda x: -x[1][7]):
        for s in range(1, seasons + 1):
            for e in range(1, eps + 1):
                sid += 1
                title = f"{name} S{s:02d} E{e:02d}"
                lines += [f'#EXTINF:-1 tvg-name="{title}" tvg-logo="{TMDB}{poster}" group-title="{group}",{title}',
                          f"{host}/series/{USER}/{PASS}/{sid}.mkv"]
        series.append({"num": len(series) + 1, "name": name, "series_id": len(series) + 1, "cover": TMDB + poster,
                       "plot": PLOTS.get(name, f"{name}: القصة كاملة بمواسمها."), "cast": "", "director": "",
                       "genre": genre, "releaseDate": f"{year}-01-20", "last_modified": str(NOW - ago * 86400),
                       "rating": str(rating), "rating_5based": rating / 2, "backdrop_path": [TMDB + poster],
                       "youtube_trailer": "", "episode_run_time": "50", "category_id": "2"})
    return "\n".join(lines) + "\n", vod, series


def png(seed, w=120, h=120):
    """صورة PNG متدرّجة بلا مكتبات."""
    r0, g0, b0 = (seed * 53) % 200 + 30, (seed * 97) % 200 + 30, (seed * 29) % 200 + 30
    raw = b"".join(b"\x00" + bytes((min(255, r0 + y // 2), g0, min(255, b0 + y // 3))) * w for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class Handler(BaseHTTPRequestHandler):
    hits = []

    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", ctype="text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlsplit(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        Handler.hits.append(u.path + ("?action=" + q["action"] if "action" in q else ""))
        host = f"http://{self.headers.get('Host')}"
        if u.path.startswith("/images/"):
            n = int("".join(c for c in u.path if c.isdigit()) or 1)
            return self._send(200, png(n), "image/png")
        if u.path in ("/get.php", "/player_api.php") and (q.get("username") != USER or q.get("password") != PASS):
            if u.path == "/player_api.php":
                return self._send(200, json.dumps({"user_info": {"auth": 0}}).encode(), "application/json")
            return self._send(403, b"Forbidden")
        text, vod, series = build(host)
        if u.path == "/get.php":
            return self._send(200, text.encode("utf-8"), "audio/x-mpegurl")
        if u.path == "/player_api.php":
            if self.server.api_down:
                return self._send(500, b"error")
            if q.get("action") == "get_vod_streams":
                return self._send(200, json.dumps(list(vod.values()), ensure_ascii=False).encode(), "application/json")
            if q.get("action") == "get_series":
                return self._send(200, json.dumps(series, ensure_ascii=False).encode(), "application/json")
            return self._send(200, b"[]", "application/json")
        return self._send(404, b"not found")


def serve(port, api_down=False):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.api_down = api_down
    return srv


if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 9790, api_down="api-down" in sys.argv).serve_forever()

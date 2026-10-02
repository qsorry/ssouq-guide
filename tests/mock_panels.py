#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""لوحات Xtream وهمية قابلة للتعديل أثناء الاختبار — لكلٍّ بياناتها: بوابات تكتب العمل نفسه بأسماء مختلفة
(«علي كارا» · «علي كارا (مترجم)» · «Ali Kara - Arabic Sub» · «علي كارا الموسم الأول»)، وروابط تشغيلٍ تعمل أو تتعطّل.

  Panel(name).series / .vod / .live          قوائم (قواميس كما تردّها اللوحات)
  Panel.info[series_id]                       get_series_info: {"info": …, "episodes": {"1": [...]}}
  Panel.dead                                  روابط تشغيل معطّلة (رقم العنصر أو الحلقة) ← 404
  Panel.rejected = True                       الاشتراك مرفوض (‏auth 0)
  Panel.slow[action] = ثوانٍ · Panel.down       سيرفرٌ بطيء في إجراء، أو يردّ 503 له (كاسبر وقائمة أفلامه)
  Panel.hits                                  مسارات الطلبات (لعدّ الفحص)
  vod[...]["info_genre"]                      تصنيف الفيلم في تفاصيله وحدها (لوحاتٌ لا تذكره في القائمة)

    srv = serve(Panel("smart")); host = f"http://127.0.0.1:{srv.server_address[1]}"
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

USER, PASS = "u", "p"


class Panel:
    def __init__(self, name, user=USER, pw=PASS):
        self.name, self.user, self.pw = name, user, pw
        self.series, self.vod, self.live = [], [], []
        self.cats = {"series": [], "vod": [], "live": []}
        self.info = {}
        self.dead = set()
        self.rejected = False
        self.slow, self.down = {}, set()
        self.exp = int(time.time()) + 30 * 86400
        self.hits = []
        self.lock = threading.Lock()

    def cat(self, kind, cid, name):
        self.cats[kind].append({"category_id": str(cid), "category_name": name, "parent_id": 0})
        return str(cid)

    def episodes(self, sid, seasons, height=0):
        """‏seasons: {الموسم: عدد الحلقات} ← حلقاتٌ بأرقامٍ فريدة (‏sid*1000 + …)؛ ‏height: ارتفاع صورتها في التفاصيل."""
        eps = {}
        for se, n in seasons.items():
            eps[str(se)] = [{"id": str(sid * 1000 + se * 100 + e), "episode_num": e, "season": se,
                             "title": f"Episode {se}x{e}", "container_extension": "mkv",
                             "info": {"plot": f"{self.name} {se}x{e}", "releasedate": "2024-01-01",
                                      **({"video": {"height": height}} if height else {})}} for e in range(1, n + 1)]
        self.info[sid] = {"info": {"name": next((s["name"] for s in self.series if s["series_id"] == sid), ""),
                                   "plot": f"قصة من {self.name}", "genre": "دراما", "rating": "8.1"}, "episodes": eps}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", ctype="application/json", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        p: Panel = self.server.panel
        u = urlsplit(self.path)
        with p.lock:
            p.hits.append(u.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        parts = u.path.strip("/").split("/")
        if parts and parts[0] in ("movie", "series", "live") and len(parts) == 4:     # روابط التشغيل
            ok = parts[1] == p.user and parts[2] == p.pw and not p.rejected
            num = int(parts[3].split(".")[0]) if parts[3].split(".")[0].isdigit() else -1
            if not ok:
                return self._send(401, b"")
            if num in p.dead:
                return self._send(404, b"")
            return self._send(302, b"", "text/plain", {"Location": f"http://127.0.0.1:1/media/{p.name}/{num}"})
        if u.path != "/player_api.php":
            return self._send(404, b"")
        if q.get("username") != p.user or q.get("password") != p.pw or p.rejected:
            return self._send(200, json.dumps({"user_info": {"auth": 0}}).encode())
        act = q.get("action", "")
        if act in p.slow:
            time.sleep(p.slow[act])
        if act in p.down:
            return self._send(503, b"")
        if not act:
            return self._send(200, json.dumps({"user_info": {"username": p.user, "auth": 1, "status": "Active",
                                                             "exp_date": str(p.exp), "max_connections": "1",
                                                             "allowed_output_formats": ["m3u8", "ts"]},
                                               "server_info": {}}).encode())
        data = {"get_series_categories": p.cats["series"], "get_vod_categories": p.cats["vod"],
                "get_live_categories": p.cats["live"], "get_series": p.series, "get_vod_streams": p.vod,
                "get_live_streams": p.live}.get(act)
        if act == "get_series_info":
            data = p.info.get(int(q.get("series_id", 0)), {})
        if act == "get_vod_info":
            v = next((x for x in p.vod if str(x["stream_id"]) == q.get("vod_id")), None)
            data = {"info": {"name": v["name"], "plot": "plot", "genre": v.get("info_genre", v.get("genre", "")),
                             **({"video": {"height": v["height"]}} if v.get("height") else {})},
                    "movie_data": {"stream_id": v["stream_id"], "name": v["name"],
                                   "container_extension": v.get("container_extension", "mp4")}} if v else {}
        if data is None:
            return self._send(404, b"")
        return self._send(200, json.dumps(data, ensure_ascii=False).encode())


def serve(panel, port=0, bind="127.0.0.1"):
    """‏bind: عنوانٌ آخر على الجهاز (127.0.0.2) — سيرفراتٌ بهوستاتٍ مختلفة كما في حسابٍ حقيقي متعدد البوابات."""
    srv = ThreadingHTTPServer((bind, port), Handler)
    srv.panel = panel
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv

"""إضافة Stremio وهمية لاختبار «الإضافات الأخرى» (مثل AIOMetadata):
  /aio/manifest.json     إضافةٌ مُعدّة (بيانات أفلامٍ ومسلسلات بمعرّفات tt)
  /needs/manifest.json   إضافةٌ تحتاج إعدادًا (configurationRequired)
  /html/manifest.json    صفحة HTML لا manifest
  /aiobase/manifest.json AIOMetadata بلا إعداد (لا موارد — كما على elfhosted)
  /official.json         دليلٌ كالرسمي (قائمة)، و/community.json كدليل المجتمع ({addons: [...]})
  /hop                   تحويلٌ (302) إلى ?to=
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

AIO = {"id": "community.aiometadata", "version": "1.9.0", "name": "AIOMetadata", "description": "Metadata for everything",
       "logo": "https://example.com/aio.png", "resources": ["catalog", "meta"], "types": ["movie", "series"],
       "idPrefixes": ["tt", "tmdb:"], "catalogs": [], "behaviorHints": {"configurable": True}}


BASE = {**AIO, "name": "AIO Metadata", "id": "com.aio.metadata", "resources": [], "logo": "",
        "behaviorHints": {"configurable": True, "configurationRequired": False}}


def _dir(host):
    official = [{"transportUrl": f"{host}/aio/manifest.json", "transportName": "http", "manifest": AIO},
                {"transportUrl": "https://v3-cinemeta.strem.io/manifest.json", "manifest": {"id": "com.linvo.cinemeta", "name": "Cinemeta",
                                                                                            "description": "The official metadata add-on"}}]
    community = {"addons": [{"transportUrl": f"{host}/aiobase/manifest.json", "manifest": BASE},
                            {"transportUrl": f"{host}/aio/manifest.json", "manifest": AIO},             # مكرّرة في المصدرين
                            {"transportUrl": "https://aio2.example.com/stremio/manifest.json", "manifest": BASE},   # مضيفٌ آخر لها
                            {"transportUrl": "https://subs.example.com/manifest.json",
                             "manifest": {"id": "community.arsubs", "name": "ترجمة عربية", "resources": ["subtitles"], "description": "Arabic subtitles"}},
                            {"transportUrl": "javascript:alert(1)", "manifest": {"id": "x", "name": "bad"}}]}
    return official, community


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlsplit(self.path)
        if u.path == "/aio/manifest.json":
            return self._send(200, AIO)
        if u.path == "/aiobase/manifest.json":
            return self._send(200, BASE)
        if u.path == "/manifest.json" and getattr(self.server, "root", False):   # جذر المضيف: AIOMetadata بلا إعداد
            return self._send(200, BASE)
        if u.path in ("/official.json", "/community.json"):
            official, community = _dir(f"http://{self.headers.get('Host')}")
            return self._send(200, official if u.path == "/official.json" else community)
        if u.path == "/needs/manifest.json":
            return self._send(200, {**AIO, "id": "community.needs", "name": "Needs Config",
                                    "behaviorHints": {"configurable": True, "configurationRequired": True}})
        if u.path == "/html/manifest.json":
            return self._send(200, b"<html>hi</html>", "text/html")
        if u.path == "/hop":
            self.send_response(302)
            self.send_header("Location", parse_qs(u.query).get("to", ["/"])[0])
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        return self._send(404, {"error": "not found"})


def serve(port=0):
    return ThreadingHTTPServer(("127.0.0.1", port), H)


if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 9796).serve_forever()

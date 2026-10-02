"""إضافة Stremio وهمية لاختبار «الإضافات الأخرى» (مثل AIOMetadata):
  /aio/manifest.json     إضافةٌ مُعدّة (بيانات أفلامٍ ومسلسلات بمعرّفات tt)
  /needs/manifest.json   إضافةٌ تحتاج إعدادًا (configurationRequired)
  /html/manifest.json    صفحة HTML لا manifest
  /hop                   تحويلٌ (302) إلى ?to=
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

AIO = {"id": "community.aiometadata", "version": "1.9.0", "name": "AIOMetadata", "description": "Metadata for everything",
       "logo": "https://example.com/aio.png", "resources": ["catalog", "meta"], "types": ["movie", "series"],
       "idPrefixes": ["tt", "tmdb:"], "catalogs": [], "behaviorHints": {"configurable": True}}


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

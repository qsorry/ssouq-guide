#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
جوجل وهمية للاختبار (بلا إنترنت): رمز الوصول من JWT يُتحقّق من توقيعه بالمفتاح العام كما تفعل جوجل، وGA4
(‏Data وAdmin)، وSearch Console (‏البحث وخرائط الموقع والمواقع)، وIndexNow.

ومعها make_key(): مفتاح RSA يُولَّد وقت الاختبار ويُكتب PEM (‏PKCS#8 كملف حساب الخدمة) بمُرمِّز DER مستقل عن
قارئ google_api — فلا مفتاح خاص محفوظ في المستودع.

    python tests/mock_google.py PORT PUBKEY.json
"""
import base64
import hashlib
import json
import random
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

TOKEN = "ya29.mock-access-token"


# ================= مفتاح RSA للاختبار =================
def _probable_prime(bits, rnd):
    small = [p for p in range(3, 2000, 2) if all(p % q for q in range(3, int(p ** .5) + 1, 2))]
    while True:
        n = rnd.getrandbits(bits) | (1 << bits - 1) | 1
        if any(n % p == 0 for p in small):
            continue
        d, s = n - 1, 0
        while d % 2 == 0:
            d, s = d // 2, s + 1
        for _ in range(20):
            x = pow(rnd.randrange(2, n - 2), d, n)
            if x in (1, n - 1):
                continue
            for _ in range(s - 1):
                x = pow(x, 2, n)
                if x == n - 1:
                    break
            else:
                break
        else:
            return n


def _len(n):
    if n < 128:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _tlv(tag, body):
    return bytes([tag]) + _len(len(body)) + body


def _int(v):
    b = v.to_bytes(v.bit_length() // 8 + 1, "big")        # بايتٌ زائد يمنع قراءته سالبًا
    return _tlv(0x02, b)


def make_key(bits=1024, seed=None, pkcs1=False):
    """← (PEM بصيغة PKCS#8 — أو PKCS#1 «RSA PRIVATE KEY» — ‏{n, e}) لمفتاحٍ جديد."""
    rnd = random.Random(seed)
    e = 65537
    while True:
        p, q = _probable_prime(bits // 2, rnd), _probable_prime(bits // 2, rnd)
        phi = (p - 1) * (q - 1)
        if p != q and phi % e:
            break
    n, d = p * q, pow(e, -1, phi)
    rsa = _tlv(0x30, b"".join(_int(v) for v in (0, n, e, d, p, q, d % (p - 1), d % (q - 1), pow(q, -1, p))))
    alg = _tlv(0x30, _tlv(0x06, bytes.fromhex("2a864886f70d010101")) + b"\x05\x00")
    der = rsa if pkcs1 else _tlv(0x30, _int(0) + alg + _tlv(0x04, rsa))
    b64 = base64.b64encode(der).decode()
    kind = "RSA PRIVATE KEY" if pkcs1 else "PRIVATE KEY"
    pem = (f"-----BEGIN {kind}-----\n" + "\n".join(b64[i:i + 64] for i in range(0, len(b64), 64))
           + f"\n-----END {kind}-----\n")
    return pem, {"n": n, "e": e}


def service_account(pem, email="guide-stats@demo-project.iam.gserviceaccount.com"):
    return {"type": "service_account", "project_id": "demo-project", "private_key_id": "abc123", "private_key": pem,
            "client_email": email, "client_id": "1", "token_uri": "https://oauth2.googleapis.com/token"}


# ================= الخادم =================
def _b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def verify(jwt, pub):
    """JWT ← مطالباته إن صحّ توقيعه RS256 بالمفتاح العام، وإلا None."""
    try:
        h, c, s = jwt.split(".")
        if json.loads(_b64d(h)).get("alg") != "RS256":
            return None
        n, e = pub["n"], pub["e"]
        k = (n.bit_length() + 7) // 8
        m = pow(int.from_bytes(_b64d(s), "big"), e, n).to_bytes(k, "big")
        t = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256((h + "." + c).encode()).digest()
        if m != b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t:
            return None
        return json.loads(_b64d(c))
    except Exception:
        return None


STATE = {"log": [], "sitemaps": [], "indexnow": [], "mode": {}, "gsc_queries": []}
DIM_ROWS = {
    "sessionDefaultChannelGroup": [("Organic Search", 820), ("Direct", 410), ("Organic Social", 260), ("Referral", 95)],
    "sessionSource": [("google", 800), ("(direct)", 410), ("snapchat.com", 140), ("whatsapp", 120)],
    "countryId": [("SA", 1500), ("KW", 90), ("AE", 70)],
    "pagePath": [("/", 900), ("/samsung-lg", 420), ("/content/kon", 300)],
    "unifiedScreenName": [("تفعيل الاشتراك خطوة بخطوة | سمارت سوق", 4), ("طريقة تثبيت IPTV على شاشات سامسونج", 3)],
}


def _report(req):
    dims = [d["name"] for d in req.get("dimensions") or []]
    mets = [m["name"] for m in req.get("metrics") or []]
    if dims == ["date"]:
        rows = [([f"202609{d:02d}"], [100 + d, 120 + d, 250 + d * 3, 0.61]) for d in range(1, 8)]
    else:
        rows = [([k], [v] * len(mets)) for k, v in DIM_ROWS.get(dims[0] if dims else "", [])]
    out = {"rows": [{"dimensionValues": [{"value": x} for x in dv], "metricValues": [{"value": str(v)} for v in mv[:len(mets)]]}
                    for dv, mv in rows]}
    if "TOTAL" in (req.get("metricAggregations") or []):
        tot = [sum(r[1][i] for r in rows) for i in range(len(mets))]
        if "engagementRate" in mets:
            tot[mets.index("engagementRate")] = 0.61
        out["totals"] = [{"dimensionValues": [{"value": "RESERVED_TOTAL"}], "metricValues": [{"value": str(v)} for v in tot]}]
    return out


class H(BaseHTTPRequestHandler):
    pub = None

    def log_message(self, *a):
        pass

    def _send(self, code, obj=None):
        body = b"" if obj is None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _authed(self):
        return self.headers.get("Authorization") == "Bearer " + TOKEN

    def _err(self, code, msg, status="PERMISSION_DENIED"):
        return self._send(code, {"error": {"code": code, "message": msg, "status": status}})

    def do_GET(self):
        u = urlparse(self.path)
        STATE["log"].append(("GET", u.path))
        if u.path == "/_test/state":
            return self._send(200, {k: v for k, v in STATE.items()})
        if not self._authed():
            return self._err(401, "Request had invalid authentication credentials.", "UNAUTHENTICATED")
        if u.path == "/gaadmin/v1beta/accountSummaries":
            if STATE["mode"].get("admin") == "disabled":
                return self._err(403, "Google Analytics Admin API has not been used in project 1 before or it is disabled. "
                                      "Enable it by visiting https://console.developers.google.com/apis/api/analyticsadmin.googleapis.com/overview?project=1 then retry.")
            return self._send(200, {"accountSummaries": [{"account": "accounts/9", "displayName": "سمارت سوق",
                                    "propertySummaries": [{"property": "properties/424242", "displayName": "guide.ssouq.com"}]}]})
        if u.path == "/gsc/sites":
            return self._send(200, {"siteEntry": [{"siteUrl": "https://guide.ssouq.com/", "permissionLevel": "siteFullUser"},
                                                  {"siteUrl": "sc-domain:ssouq.com", "permissionLevel": "siteRestrictedUser"}]})
        if u.path.startswith("/gsc/sites/") and u.path.endswith("/sitemaps"):
            return self._send(200, {"sitemap": [{"path": p, "lastSubmitted": "2026-09-29T08:00:00Z", "lastDownloaded": "2026-09-29T09:00:00Z",
                                                 "isPending": False, "errors": 0, "warnings": 0, "contents": [{"type": "web", "submitted": "64"}]}
                                                for p in STATE["sitemaps"]]})
        return self._send(404, {"error": {"code": 404, "message": "Not found"}})

    def do_PUT(self):
        u = urlparse(self.path)
        STATE["log"].append(("PUT", u.path))
        if not self._authed():
            return self._err(401, "unauthenticated", "UNAUTHENTICATED")
        if "/sitemaps/" in u.path:
            if STATE["mode"].get("gsc") == "restricted":
                return self._err(403, "User does not have sufficient permission for site 'https://guide.ssouq.com/'.")
            feed = unquote(u.path.split("/sitemaps/", 1)[1])
            if feed not in STATE["sitemaps"]:
                STATE["sitemaps"].append(feed)
            return self._send(204)
        return self._send(404)

    def do_POST(self):
        u = urlparse(self.path)
        raw = self._body()
        STATE["log"].append(("POST", u.path))
        if u.path == "/_test/mode":
            STATE["mode"].update(json.loads(raw or b"{}"))
            return self._send(200, {"ok": True})
        if u.path == "/token":
            f = parse_qs(raw.decode())
            claims = verify((f.get("assertion") or [""])[0], self.pub)
            if f.get("grant_type") != ["urn:ietf:params:oauth:grant-type:jwt-bearer"] or not claims:
                return self._send(400, {"error": "invalid_grant", "error_description": "Invalid JWT Signature."})
            ok = (claims.get("aud") == "https://oauth2.googleapis.com/token" and claims.get("exp", 0) - claims.get("iat", 0) == 3600
                  and "analytics.readonly" in claims.get("scope", "") and "webmasters" in claims.get("scope", "")
                  and claims.get("iss", "").endswith("gserviceaccount.com"))
            if not ok:
                return self._send(400, {"error": "invalid_grant", "error_description": "Invalid JWT claims."})
            return self._send(200, {"access_token": TOKEN, "expires_in": 3599, "token_type": "Bearer"})
        if u.path == "/indexnow":
            body = json.loads(raw or b"{}")
            STATE["indexnow"].append(body)
            code = STATE["mode"].get("indexnow", 200)
            return self._send(code) if code != 200 else self._send(200)
        if not self._authed():
            return self._err(401, "unauthenticated", "UNAUTHENTICATED")
        body = json.loads(raw or b"{}")
        if u.path.startswith("/ga/v1beta/properties/"):
            prop = u.path.split("/properties/", 1)[1].split(":", 1)[0]
            if prop == "403":
                return self._err(403, "User does not have sufficient permissions for this property.")
            if STATE["mode"].get("ga") == "disabled":
                return self._err(403, "Google Analytics Data API has not been used in project 1 before or it is disabled. "
                                      "Enable it by visiting https://console.developers.google.com/apis/api/analyticsdata.googleapis.com/overview?project=1 then retry.")
            if u.path.endswith(":batchRunReports"):
                return self._send(200, {"reports": [_report(r) for r in body.get("requests") or []]})
            if u.path.endswith(":runRealtimeReport"):
                r = _report(body)
                return self._send(200, r)
        if u.path.startswith("/gsc/sites/") and u.path.endswith("/searchAnalytics/query"):
            dims = body.get("dimensions") or []
            STATE["gsc_queries"].append(body)
            if not dims:
                clicks = 120 if len([q for q in STATE["gsc_queries"] if not q.get("dimensions")]) % 2 else 80   # الحالية ثم السابقة
                rows = [{"clicks": clicks, "impressions": 4200, "ctr": clicks / 4200, "position": 9.4}]
            elif dims == ["date"]:
                rows = [{"keys": [f"2026-09-{d:02d}"], "clicks": 3 + d % 5, "impressions": 140 + d * 3, "ctr": 0.03, "position": 9.1}
                        for d in range(1, 29)]
            elif dims == ["query"]:
                rows = [{"keys": ["اشتراك iptv"], "clicks": 40, "impressions": 900, "ctr": 0.044, "position": 6.2},
                        {"keys": ["تفعيل iptv على سامسونج"], "clicks": 25, "impressions": 300, "ctr": 0.083, "position": 3.1},
                        {"keys": ["ترتيب دوري روشن"], "clicks": 4, "impressions": 700, "ctr": 0.0057, "position": 11.8}]
            else:
                rows = [{"keys": ["https://guide.ssouq.com/samsung-lg"], "clicks": 30, "impressions": 800, "ctr": 0.0375, "position": 5.2},
                        {"keys": ["https://guide.ssouq.com/standings/saudi-pro-league"], "clicks": 3, "impressions": 900, "ctr": 0.0033, "position": 12.4}]
            return self._send(200, {"rows": rows})
        return self._send(404, {"error": {"code": 404, "message": "Not found"}})


def main():
    port, pub = int(sys.argv[1]), json.load(open(sys.argv[2]))
    H.pub = {"n": int(pub["n"]), "e": int(pub["e"])}
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()


if __name__ == "__main__":
    main()

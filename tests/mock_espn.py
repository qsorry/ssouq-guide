#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""واجهة ترتيب ESPN وهمية للاختبار.  python tests/mock_espn.py 9596

GET /<code>/standings بشكل رد ESPN نفسه (children ← standings ← entries):
  ksa.1           18 ناديًا بلا ملاحظات، مقلوبة الترتيب في الرد، وآخرها نادٍ
                  مجهول المعرّف باسم إنجليزي فيه وسوم HTML وشعار من خادم غريب
  eng.1           20 ناديًا بملاحظات التأهل والهبوط
  uefa.champions  36 فريقًا بملاحظات الأدوار، وملاحظة لا يعرفها التعريب
  afc.champions   جدولان: الشرق أولًا في الرد (والصفحة تقدّم الغرب)
  أي رمز آخر      400 كما تفعل ESPN مع دوري لا تغطيه

والدوال نفسها (payload) تستوردها الاختبارات بلا خادم.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SAUDI = [("929", "Al Hilal"), ("2276", "Al Ittihad"), ("817", "Al Nassr"), ("8346", "Al Ahli"),
         ("22022", "Al Qadsiah"), ("130899", "Neom SC"), ("22028", "Al Kholood"),
         ("131746", "Al Diriyah"), ("8363", "Al Ettifaq"), ("21964", "Al Hazem"),
         ("21965", "Al Riyadh"), ("21827", "Al Fayha"), ("21829", "Al Khaleej"),
         ("793", "Al Shabab"), ("13033", "Al Fateh"), ("21446", "Al Faisaly"),
         ("18459", "Al Taawoun"), ("999999", 'New <b>Club</b> & "Co"')]
ENGLAND = [("382", "Manchester City"), ("359", "Arsenal"), ("364", "Liverpool"), ("363", "Chelsea"),
           ("361", "Newcastle United"), ("362", "Aston Villa"), ("367", "Tottenham Hotspur"),
           ("360", "Manchester United"), ("331", "Brighton & Hove Albion"), ("370", "Fulham"),
           ("384", "Crystal Palace"), ("371", "West Ham United"), ("368", "Everton"),
           ("337", "Brentford"), ("393", "Nottingham Forest"), ("349", "AFC Bournemouth"),
           ("380", "Wolverhampton Wanderers"), ("357", "Leeds United"), ("379", "Burnley"),
           ("366", "Sunderland")]
EUROPE = ENGLAND + [("86", "Real Madrid"), ("83", "Barcelona"), ("1068", "Atlético Madrid"),
                    ("132", "Bayern Munich"), ("124", "Borussia Dortmund"), ("160", "Paris Saint-Germain"),
                    ("110", "Internazionale"), ("103", "AC Milan"), ("111", "Juventus"),
                    ("114", "Napoli"), ("1929", "Benfica"), ("437", "FC Porto"),
                    ("2250", "Sporting CP"), ("432", "Galatasaray"), ("139", "Ajax Amsterdam"),
                    ("256", "Celtic")]
WEST = [("929", "Al Hilal"), ("817", "Al Nassr"), ("2276", "Al Ittihad"), ("8346", "Al Ahli"),
        ("7128", "Al Ain"), ("7135", "Al Sadd")]
EAST = [("7115", "Kashima Antlers"), ("7477", "Vissel Kobe"), ("7120", "Ulsan HD"),
        ("977", "Shanghai Shenhua"), ("6972", "FC Seoul"), ("7112", "Kawasaki Frontale")]


def _entry(tid, name, rank, n, note=None):
    """صفّ نادٍ: المتصدّر أعلى النقاط، ونقاط كل صف أقل ممّن قبله."""
    w, d = max(0, 5 - rank // 4), rank % 2
    l = max(0, 5 - w - d)
    gf, ga = 2 * w + d, l + rank // 3
    stats = {"rank": rank, "gamesPlayed": w + d + l, "wins": w, "ties": d, "losses": l,
             "pointsFor": gf, "pointsAgainst": ga, "pointDifferential": gf - ga,
             "points": 3 * (n - rank) + 3}
    logo = ("https://evil.example/logo.png" if tid == "999999"
            else f"https://a.espncdn.com/i/teamlogos/soccer/500/{tid}.png")
    e = {"team": {"id": tid, "displayName": name,
                  "logos": [] if tid == "21446" else [{"href": logo, "rel": ["full", "default"]}]},
         "stats": [{"name": k, "value": float(v), "displayValue": str(v)} for k, v in stats.items()]}
    if note:
        e["note"] = {"description": note, "color": "#81D6AC", "rank": rank}
    return e


def _child(name, teams, note_of=lambda r, n: None, reverse=False):
    n = len(teams)
    entries = [_entry(tid, nm, i + 1, n, note_of(i + 1, n)) for i, (tid, nm) in enumerate(teams)]
    return {"name": name, "abbreviation": "2026-27",
            "standings": {"seasonDisplayName": "2026-27 Mock League",
                          "entries": entries[::-1] if reverse else entries}}


def _england_note(r, n):
    return ("Champions League" if r <= 4 else "Europa League" if r == 5
            else "Conference League qualifying" if r == 6 else "Relegation" if r > n - 3 else None)


def _europe_note(r, n):
    return ("Qualifies for round of 16" if r <= 8 else "Knockout phase playoffs - seeded" if r <= 16
            else "Knockout phase playoffs - unseeded" if r <= 24
            else "Mystery Zone" if r == 25 else "Eliminated")


def payload(code):
    """رد ESPN لرمز الدوري، أو None لما لا تغطيه."""
    kids = {
        "ksa.1": lambda: [_child("Saudi Pro League", SAUDI, reverse=True)],
        "eng.1": lambda: [_child("2026-27 English Premier League", ENGLAND, _england_note)],
        "uefa.champions": lambda: [_child("League Phase", EUROPE, _europe_note)],
        "afc.champions": lambda: [_child("East Region", EAST), _child("West Region", WEST)],
    }.get(code)
    if not kids:
        return None
    return {"name": code, "season": {"year": 2026, "displayName": "2026-27 Mock League"},
            "children": kids()}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        parts = self.path.split("?")[0].strip("/").split("/")
        data = payload(parts[0]) if len(parts) == 2 and parts[1] == "standings" else None
        body = json.dumps(data if data else {"code": 400, "message": "bad league"}).encode()
        self.send_response(200 if data else 400)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 9596), H).serve_forever()

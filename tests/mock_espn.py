#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""واجهات ESPN وهمية للاختبار.  python tests/mock_espn.py 9596   (LEAGUE_API=http://127.0.0.1:9596)

GET /v2/sports/soccer/<code>/standings بشكل رد ESPN نفسه (children ← standings ← entries):
  ksa.1           18 ناديًا بلا ملاحظات، مقلوبة الترتيب في الرد، وآخرها نادٍ
                  مجهول المعرّف باسم إنجليزي فيه وسوم HTML وشعار من خادم غريب
  eng.1           20 ناديًا بملاحظات التأهل والهبوط
  uefa.champions  36 فريقًا بملاحظات الأدوار، وملاحظة لا يعرفها التعريب
  afc.champions   جدولان: الشرق أولًا في الرد (والصفحة تقدّم الغرب)
  uefa.nations    مجموعات المستوى الأول الأربع بملاحظات ESPN المختلطة، ومجموعة من الثاني
  أي رمز آخر      400 كما تفعل ESPN مع دوري لا تغطيه

GET /site/v2/sports/soccer/uefa.nations/scoreboard?dates=2026 مباريات دوري الأمم
بمواعيد حول «الآن» (scoreboard)، وسنة أخرى بلا مباريات. والدوال نفسها (payload
وscoreboard) تستوردها الاختبارات بلا خادم.
"""
import datetime
import json
import sys
import time
from urllib.parse import parse_qs, urlparse
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


NATIONS = {
    "A1": [("478", "France"), ("459", "Belgium"), ("465", "Türkiye"), ("162", "Italy")],
    "A2": [("455", "Greece"), ("449", "Netherlands"), ("481", "Germany"), ("6757", "Serbia")],
    "A3": [("164", "Spain"), ("477", "Croatia"), ("448", "England"), ("450", "Czechia")],
    "A4": [("482", "Portugal"), ("464", "Norway"), ("479", "Denmark"), ("578", "Wales")],
    "B1": [("466", "Sweden"), ("580", "Scotland"), ("471", "Poland"), ("480", "Hungary")],
}
# ملاحظات ESPN الحقيقية في دوري الأمم تخلط المستويات الأربعة في سطر واحد
MIXED_NOTES = {1: "A: Qualifies for QFs; B-D: Promotion", 3: "A, B: Relegation playoffs",
               4: "A, B: Relegation; C: Relegation or playoffs"}


def _event(eid, mins, home, away, stage="league-phase", group=None, state="post", status="STATUS_FULL_TIME",
           clock="90'", time_valid=True):
    """مباراة scoreboard تبدأ بعد mins دقيقة من الآن (سالبة = مضت). home/away: (id، الاسم، الأهداف، الترجيح، الفائز)."""
    date = datetime.datetime.fromtimestamp(time.time() + mins * 60, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    comp = []
    for side, (tid, name, score, so, win) in (("home", home), ("away", away)):
        x = {"homeAway": side, "score": str(score), "winner": win,
             "team": {"id": tid, "displayName": name,
                      "logo": f"https://a.espncdn.com/i/teamlogos/countries/500/{tid}.png"}}
        if so is not None:
            x["shootoutScore"] = so
        comp.append(x)
    return {"id": eid, "date": date, "season": {"year": 2026, "slug": stage},
            "competitions": [{"timeValid": time_valid, "group": {"name": f"Group {group}"} if group else None,
                              "status": {"displayClock": clock, "type": {"state": state, "name": status}},
                              "competitors": comp}]}


def scoreboard(code, dates):
    """مباريات دوري الأمم حول الآن: منتهية، وجارية، واستراحة، وقادمة، ومؤجلة، وأدوار
    إقصائية (ترجيح، تمديد، وأطراف لم تُعرف بعد)، وما ليس من المستوى الأول."""
    if code != "uefa.nations":
        return None
    if dates != "2026":
        return {"events": []}
    day = 24 * 60
    return {"events": [
        _event("1", -3 * day, ("478", "France", 2, None, True), ("459", "Belgium", 1, None, False), group="A1"),
        _event("2", -2 * day, ("481", "Germany", 0, None, False), ("455", "Greece", 1, None, True), group="A2"),
        _event("3", -2 * day + 60, ("448", "England", 2, None, False), ("164", "Spain", 3, None, True), group="A3"),
        _event("4", -67, ("482", "Portugal", 1, None, False), ("578", "Wales", 0, None, False), group="A4",
               state="in", status="STATUS_IN_PROGRESS", clock="67'"),
        _event("5", -50, ("162", "Italy", 0, None, False), ("465", "Türkiye", 0, None, False), group="A1",
               state="in", status="STATUS_HALFTIME", clock="45'"),
        _event("6", 2 * day, ("449", "Netherlands", 0, None, False), ("6757", "Serbia", 0, None, False), group="A2",
               state="pre", status="STATUS_SCHEDULED", clock="0'"),
        _event("7", 3 * day, ("477", "Croatia", 0, None, False), ("450", "Czechia", 0, None, False), group="A3",
               state="pre", status="STATUS_POSTPONED", clock="0'"),
        _event("8", 4 * day, ("164", "Spain", 0, None, False), ("-9", "<b>Evil</b> & Co", 0, None, False), group="A3",
               state="pre", status="STATUS_SCHEDULED", clock="0'"),
        _event("9", -2 * day, ("466", "Sweden", 3, None, True), ("480", "Hungary", 0, None, False), group="B1"),
        _event("10", 60 * day, ("-1", "Group A1 Winner", 0, None, False), ("-2", "Group A2 2nd Place", 0, None, False),
               stage="quarterfinals", state="pre", status="STATUS_SCHEDULED", clock="0'", time_valid=False),
        _event("11", -10 * day, ("164", "Spain", 2, 5, True), ("482", "Portugal", 2, 4, False),
               stage="quarterfinals", status="STATUS_FINAL_PEN", clock="120'"),
        _event("12", -9 * day, ("479", "Denmark", 3, None, True), ("464", "Norway", 2, None, False),
               stage="semifinals", status="STATUS_FINAL_AET", clock="120'"),
        _event("13", -20 * day, ("578", "Wales", 1, None, False), ("580", "Scotland", 1, None, False),
               stage="relegation-playoffs"),
        _event("14", -20 * day, ("456", "Latvia", 2, None, True), ("16721", "Gibraltar", 0, None, False),
               stage="relegation-playoffs"),
    ]}


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
        "uefa.nations": lambda: [_child(f"Group {g}", teams, lambda r, n: MIXED_NOTES.get(r))
                                 for g, teams in NATIONS.items()],
    }.get(code)
    if not kids:
        return None
    return {"name": code, "season": {"year": 2026, "displayName": "2026-27 Mock League"},
            "children": kids()}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urlparse(self.path)
        parts = u.path.strip("/").split("/")
        data = None
        if parts[:3] == ["v2", "sports", "soccer"] and len(parts) == 5 and parts[4] == "standings":
            data = payload(parts[3])
        elif parts[:4] == ["site", "v2", "sports", "soccer"] and len(parts) == 6 and parts[5] == "scoreboard":
            data = scoreboard(parts[4], (parse_qs(u.query).get("dates") or [""])[0])
        body = json.dumps(data if data is not None else {"code": 400, "message": "bad league"}).encode()
        self.send_response(200 if data is not None else 400)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 9596), H).serve_forever()

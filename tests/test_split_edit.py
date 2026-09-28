#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
تغيير اسم اليوزر على اللوحات (الاشتراكات المجزّأة) — مقابل لوحاتٍ وهمية تُنمذِج
أخطار نموذج التعديل: باقةٌ مُرسَلة = تمديد مدفوع، بوكيهاتٌ فارغة = مسح القنوات،
كلمة مرورٍ فارغة = توليد جديدة. والحارس الأهمّ: نموذج «الإضافة» لا يُرسَل أبدًا.

    python tests/test_split_edit.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import xm_web                                                   # noqa: E402
import falcon_api                                               # noqa: E402
import mock_casper                                              # noqa: E402

_p = _f = 0


def check(label, cond, extra=""):
    global _p, _f
    if cond:
        _p += 1
        print("  PASS  " + label + (("  (%s)" % extra) if extra else ""))
    else:
        _f += 1
        print("  FAIL  " + label + (("  (%s)" % extra) if extra else ""))


def start(args, probe):
    p = subprocess.Popen([sys.executable] + args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            urllib.request.urlopen(probe, timeout=0.3)
            break
        except urllib.error.HTTPError:
            break
        except Exception:
            time.sleep(0.1)
    return p


def state(base):
    return json.loads(urllib.request.urlopen(base + "/__lines", timeout=10).read())


def xtream_session(base):
    """جلسة مرح مسجّلة الدخول: الكود يُقرأ من ترويسة اللوحة الوهمية (OCR محاكى)."""
    s = xm_web.PanelWebSession({"id": "g", "user": "demo", "password": "secret", "panel_base": base,
                                "host": "http://h"}, tempfile.mkdtemp())
    holder, orig = {}, s.fetch_captcha

    def fetch():
        ct, img = orig()
        holder["c"] = s.opener.open(base + "/captcha.php?a=1", timeout=10).headers.get("X-Captcha-Code", "")
        return ct, img
    s.fetch_captcha = fetch
    xm_web.solve_captcha = lambda img: holder.get("c", "")
    s.use_ocr = True
    s.login()
    return s


def xtream(variant, port):
    base = "http://127.0.0.1:%d" % port
    proc = start([os.path.join(HERE, "mock_panel.py"), str(port), "demo", "secret"] + ([variant] if variant else []),
                 base + "/token.php")
    try:
        s = xtream_session(base)
        s.create_line("15", "111122223333", "999988887777")
        before = next(l for l in state(base)["lines"] if l["username"] == "111122223333")
        try:
            out, err = s.edit_line("111122223333", "555566667777"), None
        except Exception as e:
            out, err = None, e
        after = state(base)
        return out, err, before, after, s
    finally:
        proc.kill()


def main():
    print("== مرح (Xtream): الاسم وحده ==")
    out, err, before, st, _s = xtream("", 9481)
    ln = next((l for l in st["lines"] if l["id"] == before["id"]), {})
    check("renamed and verified", out and out.get("verified") and ln.get("username") == "555566667777", str(err or out))
    check("password untouched", ln.get("password") == "999988887777")
    check("channels kept", ln.get("bouquets") == before["bouquets"] and before["bouquets"] not in ("", "[]"), ln.get("bouquets"))
    check("no paid extension (package left unchanged)", ln.get("end") == before["end"] and not st["extends"])
    form = st["edits"][0][1] if st["edits"] else {}
    check("the edit form went with its id marker", form.get("edit") == before["id"] and form.get("submit_user") == "1")
    check("no new line created", len(st["lines"]) == 1)

    print("\n== مرح: الاسم مقفل للموزّع ==")
    out, err, before, st, _s = xtream("lockuser", 9482)
    check("refused before sending", isinstance(err, xm_web.EditUnsupported) and not st["edits"], str(err))
    check("line untouched", st["lines"][0]["username"] == "111122223333")

    print("\n== مرح: جدول البوكيهات بالجافاسكربت (فارغ في الصفحة) ==")
    out, err, before, st, _s = xtream("jsbq", 9483)
    ln = next((l for l in st["lines"] if l["id"] == before["id"]), {})
    check("renamed", out and ln.get("username") == "555566667777", str(err or out))
    check("channels restored from the line's own package", ln.get("bouquets") == before["bouquets"], ln.get("bouquets"))

    print("\n== مرح: لوحة بلا صفحة تعديل (تعيد نموذج الإضافة) ==")
    out, err, before, st, _s = xtream("nocap", 9484)
    check("add form never submitted as an edit", isinstance(err, xm_web.EditUnsupported), str(err))
    check("…so no line was created or changed", len(st["lines"]) == 1 and st["lines"][0]["username"] == "111122223333")

    print("\n== مرح: إعادةٌ بعد ردٍّ ضائع ==")
    base = "http://127.0.0.1:9485"
    proc = start([os.path.join(HERE, "mock_panel.py"), "9485", "demo", "secret"], base + "/token.php")
    try:
        s = xtream_session(base)
        s.create_line("15", "111122223333", "999988887777")
        s.edit_line("111122223333", "555566667777")
        again = s.edit_line("111122223333", "555566667777")
        check("second call sees it done, sends nothing", again.get("already") and len(state(base)["edits"]) == 1)
    finally:
        proc.kill()

    print("\n== كاسبر ==")
    srv, cbase, _t = mock_casper.start(4)
    try:
        cs = xm_web.CasperWebSession({"id": "c", "user": "u", "password": "p", "panel_base": cbase, "host": "http://h"},
                                     tempfile.mkdtemp())
        u0 = dict(mock_casper._Handler.users[0])
        out = cs.edit_line(u0["username"], "7777777777")
        cu = next(u for u in mock_casper._Handler.users if u["id"] == u0["id"])
        check("renamed via the row's edit link", out.get("verified") and cu["username"] == "7777777777")
        check("password kept (not left empty → not regenerated)", cu["password"] == u0["password"])
        check("bouquets kept", cu.get("bq") == {"live": ["1", "2"], "vod": ["10"]}, str(cu.get("bq")))
        check("expiry kept", cu["exp"] == u0["exp"])
        fields = mock_casper._Handler.edits[-1][1]
        check("sent with usernameold = the old name", fields.get("usernameold") == [u0["username"]])
    finally:
        srv.shutdown()

    print("\n== فالكون ==")
    fp = start([os.path.join(HERE, "mock_falcon.py"), "9486", "fk"], "http://127.0.0.1:9486/api/v1/me")
    np_ = start([os.path.join(HERE, "mock_falcon.py"), "9487", "fk", "nopatch"], "http://127.0.0.1:9487/api/v1/me")
    try:
        api = "http://127.0.0.1:9486/api/v1"
        out = falcon_api.rename_line(api, "fk", "user001", "888800001111")
        rows = falcon_api.search(api, "fk", "888800001111")
        check("renamed with PATCH, password kept", out.get("verified") and rows and rows[0]["password"] == "pass001")
        check("old name gone", not [r for r in falcon_api.search(api, "fk", "user001") if r["username"] == "user001"])
        try:
            falcon_api.rename_line("http://127.0.0.1:9487/api/v1", "fk", "user001", "888800001111")
            check("no PATCH route → unsupported", False, "no exception")
        except falcon_api.FalconUnsupported as e:
            check("no PATCH route → unsupported, nothing changed", True, str(e)[:60])
        try:
            falcon_api.rename_line("http://127.0.0.1:9", "fk", "user001", "888800001111")
            check("unreachable → offline (retried later)", False, "no exception")
        except falcon_api.FalconOffline:
            check("unreachable → offline (retried later)", True)
    finally:
        fp.kill()
        np_.kill()

    print("\n== قراءة النماذج كما يرسلها المتصفح ==")
    forms = xm_web.parse_forms('<form action="/x?id=5"><input name="a" value="1" disabled>'
                               '<input name="b" class="btn disabled" value="2"><input type="checkbox" name="c">'
                               '<input type="checkbox" name="d" checked><select name="e"><option value="">-</option>'
                               '<option value="9" selected>n</option></select><select name="f[]" multiple>'
                               '<option value="1" selected>x<option value="2">y<option value="3" selected>z</select>'
                               '<textarea name="g">t &amp; u</textarea><button type="submit" name="go" value="1">s</button></form>')
    pairs = xm_web.serialize_form(forms[0]["fields"])
    check("disabled skipped, class≠disabled, unchecked skipped, selects, multi, textarea",
          pairs == [("b", "2"), ("d", "on"), ("e", "9"), ("f[]", "1"), ("f[]", "3"), ("g", "t & u")], str(pairs))
    check("submit button found", xm_web._submit_pair(forms[0]["fields"]) == ("go", "1"))
    links = xm_web._row_links('<a href="user_reseller.php?id=55">e</a> <a href="?extend=55">x</a> '
                              '<a href="delete.php?id=55">d</a> <a href="user.php?id=556">o</a>', "55")
    check("row links: edit kept, extend/delete/other ids dropped", links == ["user_reseller.php?id=55"], str(links))
    pick = xm_web.PanelWebSession._pick_edit_form
    add = ('<form id="user_form" action="./user_reseller.php"><input type="hidden" name="member_id" value="8842">'
           '<input name="username"><input name="password"><select name="package"><option value="15">x</option></select></form>')
    check("add form (empty username) never picked as an edit form", pick(add, "55", "111122223333") is None)
    add2 = add.replace('<input name="username">', '<input name="username" value="111122223333">')
    check("…nor a form with our name but without the line's id", pick(add2, "55", "111122223333") is None)
    edit = add2.replace('<input type="hidden" name="member_id" value="8842">', '<input type="hidden" name="edit" value="55">')
    check("edit form (our name + hidden id) picked", pick(edit, "55", "111122223333") is not None)
    other = edit.replace('value="55"', 'value="56"')
    check("another line's edit form refused", pick(other, "55", "111122223333") is None)

    print("\nResult: %d passed, %d failed" % (_p, _f))
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

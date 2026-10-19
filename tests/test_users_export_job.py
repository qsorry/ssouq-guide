#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبار مهمّة السحب الخلفية إلى Excel (عدّاد حيّ) مقابل لوحة كاسبر الوهمية."""
import os
import sys
import time
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

_TMP = tempfile.mkdtemp(prefix="xmjob_")
os.environ["XM_DATA"] = _TMP        # يجب أن يُضبط قبل استيراد xm_lines

import mock_casper  # noqa: E402
import xm_lines      # noqa: E402

_p = _f = 0


def check(label, cond, extra=""):
    global _p, _f
    if cond:
        _p += 1
        print("  \033[32mPASS\033[0m  " + label + (("  (%s)" % extra) if extra else ""))
    else:
        _f += 1
        print("  \033[31mFAIL\033[0m  " + label + (("  (%s)" % extra) if extra else ""))


def main():
    srv, base, _ = mock_casper.start(user_count=140)
    try:
        gate = {"id": "g1", "name": "كاسبر", "mode": "web", "web_flavor": "casper",
                "panel_base": base + "/login.php", "panel_user": "demo",
                "panel_pass": "secret", "host": "http://ssouqhost.vip:80"}
        r = xm_lines.start_users_export("acc1", "g1", gate)
        check("start returns running", r.get("ok") and r.get("running"), str(r))

        r2 = xm_lines.start_users_export("acc1", "g1", gate)
        check("second start refused while running", r2.get("ok") is False and r2.get("running"), str(r2))

        saw_running = False
        final = None
        for _ in range(100):
            p = xm_lines.export_progress("acc1", "g1")
            if p.get("running"):
                saw_running = True
            else:
                final = p
                break
            time.sleep(0.1)
        check("progress reported a running phase", saw_running)
        check("job finished with the full count", final and final.get("count") == 140, str(final))
        check("no error", final and not final.get("error"), str(final))

        st = xm_lines.users_export.status(xm_lines.DATA_DIR, "acc1", "g1")
        check("xlsx saved with all users", st["exists"] and st["count"] == 140, str(st))

        # عزل: بوابةٌ لم تُسحب لا مهمّة لها
        idle = xm_lines.export_progress("acc1", "other")
        check("idle gate has no job", idle.get("idle") is True and not idle.get("running"), str(idle))
    finally:
        srv.shutdown()

    # --- بوابة «أرشيف فقط»: البحث من اللقطة المحفوظة واللوحة مُطفأة (أُغلق الخادم) ---
    # لا panel_base/user/pass — ومع ذلك يَبحث ولا يحاول دخولًا ولا يرمي خطأً.
    acct = {"id": "acc1", "gates": []}
    arch = {"id": "g1", "name": "كاسبر قديم", "mode": "web", "web_flavor": "casper",
            "host": "http://ssouqhost.vip:80", "archive_only": True}
    found = xm_lines.search_gate(acct, arch, "u00007")
    check("archive-only: found in the saved snapshot with the panel down",
          found.get("source") == "file" and found.get("archive_only") is True
          and any(r["username"] == "u00007" for r in found.get("results", [])), str(found)[:120])
    miss = xm_lines.search_gate(acct, arch, "no-such-user-zzz")
    check("archive-only: a miss is 'not in archive', never a panel login error",
          miss.get("results") == [] and miss.get("archive_only") is True
          and "login_error" not in miss and "error" not in miss, str(miss)[:120])
    # --- يوزرٌ في الملف «غير مؤكَّد» (أُنشئ ولم يؤكّده جدول اللوحة): تُسأل اللوحة الحيّة ---
    live_gate = {"id": "gv", "name": "مرح", "mode": "web", "host": "http://h:80",
                 "panel_base": "http://127.0.0.1:9", "panel_user": "u", "panel_pass": "p"}
    xm_lines.users_export.merge(xm_lines.DATA_DIR, "acc1", "gv", "مرح", [
        {"username": "457723874144", "password": "pa", "verified": False},
        {"username": "457700000001", "password": "pb", "verified": False},
        {"username": "457700000002", "password": "pc", "verified": True},
    ])
    orig_live, calls = xm_lines._search_live, []

    def fake_live(g, q):
        calls.append(q)
        return {"results": [{"username": "457723874144", "password": "pa", "status": "active"}]}
    xm_lines._search_live = fake_live
    try:
        out = xm_lines.search_gate(acct, live_gate, "4577")
        by = {r["username"]: r for r in out.get("results", [])}
        check("unverified in file: the live panel is asked", calls == ["4577"], str(calls))
        check("found on the panel: shown from it, not flagged",
              by["457723874144"].get("status") == "active" and not by["457723874144"].get("missing_on_panel"),
              str(by.get("457723874144")))
        check("not found on the panel: flagged missing_on_panel",
              by["457700000001"].get("missing_on_panel") is True, str(by.get("457700000001")))
        check("a confirmed row in the file is not flagged", not by["457700000002"].get("missing_on_panel"))
        snap = {r["username"]: r for r in xm_lines.users_export.search(xm_lines.DATA_DIR, "acc1", "gv", "4577")}
        check("panel confirmation clears the file's flag; the missing one stays flagged",
              "unverified" not in snap["457723874144"] and snap["457700000001"].get("unverified") is True)

        xm_lines._search_live = lambda g, q: {"results": [], "need_login": True}
        out2 = xm_lines.search_gate(acct, live_gate, "457700000001")
        r2 = (out2.get("results") or [{}])[0]
        check("panel unreachable: file row still shown, unverified but not called missing",
              r2.get("unverified") is True and not r2.get("missing_on_panel") and out2.get("need_login"), str(out2)[:160])

        calls.clear()
        xm_lines._search_live = fake_live
        xm_lines.search_gate(acct, live_gate, "457700000002")
        check("only confirmed rows matched: the file answers, the panel is not asked", calls == [], str(calls))

        # «تحقّق» من جلسة إنشاء: موجود · غُيّر اسمه (كلمة مروره عند يوزرٍ آخر) · غير موجود
        panel = [{"username": "111", "password": "a1", "status": "active", "exp": "2027-01-01"},
                 {"username": "999", "password": "b2", "status": "active"}]
        xm_lines._search_live = lambda g, q: {"results": [r for r in panel if q in (r["username"], r["password"])]}
        v = xm_lines.verify_lines(acct, live_gate, [
            {"username": "111", "password": "a1"}, {"username": "222", "password": "b2"},
            {"username": "333", "password": "c3"}, {"username": ""}])
        st = {r["username"]: r for r in v.get("results", [])}
        check("verify: found / renamed (to the user holding its password) / missing",
              st["111"]["state"] == "found" and st["111"]["exp"] == "2027-01-01"
              and st["222"]["state"] == "renamed" and st["222"]["now"] == "999"
              and st["333"]["state"] == "missing" and len(st) == 3, str(v)[:200])
        snap = {r["username"]: r for r in xm_lines.users_export.load(
            xm_lines.users_export.paths(xm_lines.DATA_DIR, "acc1", "gv")[0])}
        check("verify: missing is flagged unverified in the file, found is not, renamed untouched",
              snap["333"].get("unverified") is True and "unverified" not in snap["111"] and "222" not in snap,
              str({k: snap[k].get("unverified") for k in snap if k in ("111", "222", "333")}))

        xm_lines._search_live = lambda g, q: {"results": [], "need_login": True}
        v2 = xm_lines.verify_lines(acct, live_gate, [{"username": "111", "password": "a1"}])
        check("verify: panel needs login -> stops with need_login, nothing called missing",
              v2.get("need_login") and v2.get("results") == [], str(v2))
        v3 = xm_lines.verify_lines(acct, arch, [{"username": "111"}])
        check("verify: archive-only gate is unsupported (no panel)", v3.get("unsupported") is True)
        many = [{"username": str(i)} for i in range(xm_lines.VERIFY_MAX + 20)]
        xm_lines._search_live = lambda g, q: {"results": []}
        check("verify: capped at VERIFY_MAX per request",
              len(xm_lines.verify_lines(acct, live_gate, many)["results"]) == xm_lines.VERIFY_MAX)
    finally:
        xm_lines._search_live = orig_live

    cg = xm_lines.clean_gate(arch)
    check("clean_gate: archive-only web gate needs no panel creds, flag kept",
          cg["archive_only"] is True and cg["mode"] == "web", str(cg)[:120])
    try:
        xm_lines.clean_gate({"name": "حيّة", "mode": "web", "web_flavor": "casper",
                             "host": "http://h:80"})
        check("clean_gate: a NON-archive web gate still requires panel creds", False, "no raise")
    except ValueError:
        check("clean_gate: a NON-archive web gate still requires panel creds", True)
    check("get_packages: archive-only gate offers none (no create)",
          xm_lines.get_packages(arch) == [])

    # --- فالكون: نفس السحب الخلفي إلى Excel ---
    import threading
    from http.server import ThreadingHTTPServer
    import mock_falcon
    fsrv = ThreadingHTTPServer(("127.0.0.1", 0), mock_falcon.H)
    threading.Thread(target=fsrv.serve_forever, daemon=True).start()
    fport = fsrv.server_address[1]
    try:
        fgate = {"id": "gf", "name": "فالكون", "mode": "falcon",
                 "api_url": "http://127.0.0.1:%d/api/v1" % fport,
                 "api_key": mock_falcon.KEY, "host": ""}
        rf = xm_lines.start_users_export("acc1", "gf", fgate)
        check("falcon: start returns running", rf.get("ok") and rf.get("running"), str(rf))
        finalf = None
        for _ in range(100):
            p = xm_lines.export_progress("acc1", "gf")
            if not p.get("running"):
                finalf = p
                break
            time.sleep(0.1)
        want = len(mock_falcon.LINES)
        check("falcon: job finished with all lines", finalf and finalf.get("count") == want, str(finalf))
        stf = xm_lines.users_export.status(xm_lines.DATA_DIR, "acc1", "gf")
        check("falcon: xlsx saved", stf["exists"] and stf["count"] == want, str(stf))
        rows = xm_lines.users_export.load(xm_lines.users_export.paths(xm_lines.DATA_DIR, "acc1", "gf")[0])
        check("falcon: rows carry package name + username", bool(rows) and rows[0].get("username")
              and rows[0].get("package"), str(rows[0])[:90] if rows else "no rows")
    finally:
        fsrv.shutdown()
        shutil.rmtree(_TMP, ignore_errors=True)

    print("\n----------------------------------------")
    print("Result: \033[32m%d passed\033[0m, %s" % (_p, ("\033[31m%d failed\033[0m" % _f) if _f else "0 failed"))
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

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

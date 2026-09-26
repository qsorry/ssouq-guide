#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""جلسات الدخول تبقى بعد إعادة التشغيل/النشر (تُحفَظ على القرص لا في الذاكرة)."""
import os
import sys
import json
import time
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

_TMP = tempfile.mkdtemp(prefix="xmsess_")
os.environ["XM_DATA"] = _TMP        # يجب أن يُضبط قبل الاستيراد

import xm_lines as X  # noqa: E402

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
    try:
        tok = X.new_session("admin", "admin")
        check("new_session wrote the token to disk", os.path.exists(X.SESSIONS_FILE))

        # محاكاة النشر: الذاكرة تُمسح، والحاوية تعيد التحميل من القرص
        X._sessions.clear()
        reloaded = X._load_sessions()
        check("session survives a restart (reloaded from disk)",
              tok in reloaded and reloaded[tok]["role"] == "admin", str(list(reloaded)[:1]))

        # الجلسات المنتهية تُنظَّف عند التحميل
        expired_tok = "expired123"
        d = json.load(open(X.SESSIONS_FILE, encoding="utf-8"))
        d[expired_tok] = {"role": "admin", "user": "admin", "exp": time.time() - 10}
        json.dump(d, open(X.SESSIONS_FILE, "w", encoding="utf-8"))
        after = X._load_sessions()
        check("expired sessions pruned on load", expired_tok not in after and tok in after, str(list(after)))

        # تسجيل الخروج يزيلها من القرص أيضًا
        X._sessions = X._load_sessions()
        X._sessions.pop(tok, None)
        X._save_sessions()
        check("logout removes it from disk too", tok not in X._load_sessions())
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)

    print("\n----------------------------------------")
    print("Result: \033[32m%d passed\033[0m, %s" % (_p, ("\033[31m%d failed\033[0m" % _f) if _f else "0 failed"))
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

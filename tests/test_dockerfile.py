#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
حارس النشر: الـ Dockerfile يسمّي ملفاته واحدًا واحدًا، فملفٌّ جديد يُستورد أو صفحةٌ
جديدة تُقدَّم ولم تُضَف إلى COPY تعمل هنا وتُسقط الحاوية كلها عند النشر (ImportError
عند الإقلاع). يتحقّق أن كل وحدةٍ محلية يستوردها الخادم وكل صفحةٍ يقدّمها في COPY.

    python tests/test_dockerfile.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_p = _f = 0


def check(label, cond, extra=""):
    global _p, _f
    if cond:
        _p += 1
        print("  PASS  " + label + (("  (%s)" % extra) if extra else ""))
    else:
        _f += 1
        print("  FAIL  " + label + (("  (%s)" % extra) if extra else ""))


def local_imports(path, seen):
    """الوحدات المحلية التي يستوردها الملف، ثم ما تستورده هي (مغلقًا)."""
    src = open(path, encoding="utf-8").read()
    for m in re.finditer(r"^\s*(?:import\s+([\w, ]+)|from\s+(\w+)\s+import)", src, re.M):
        for name in re.split(r"[,\s]+", (m.group(1) or m.group(2) or "").strip()):
            f = os.path.join(ROOT, name + ".py")
            if name and os.path.isfile(f) and name not in seen:
                seen.add(name)
                local_imports(f, seen)
    return seen


def main():
    docker = open(os.path.join(ROOT, "Dockerfile"), encoding="utf-8").read()
    copied = set()
    for line in docker.splitlines():
        if line.startswith("COPY ") and line.rstrip().endswith("./"):
            copied.update(line.split()[1:-1])
    mods = local_imports(os.path.join(ROOT, "xm_lines.py"), set())
    missing = sorted(m + ".py" for m in mods if m + ".py" not in copied)
    check("every local module the server imports is copied into the image", not missing, ", ".join(missing))
    src = open(os.path.join(ROOT, "xm_lines.py"), encoding="utf-8").read()
    # صفحاتٌ موجودة في المستودع يذكرها الخادم (لا أسماء ملفات تنزيلٍ كـ renew-analysis.html)
    pages = {p for p in re.findall(r"""["']([\w-]+\.html)["']""", src) if os.path.isfile(os.path.join(ROOT, p))}
    missing = sorted(p for p in pages if p not in copied)
    check("every page the server serves is copied into the image", not missing, ", ".join(missing))
    check("the split subscriptions ship", "split_subs.py" in copied and "remaining.html" in copied)
    check("the contest WhatsApp service ships (installed, non-fatal)",
          "COPY whatsapp-reader/server.js ./whatsapp-reader/" in docker and "npm ci --omit=dev" in docker
          and "whatsapp-reader/package-lock.json" in docker and "contest WhatsApp linking unavailable" in docker)
    print("\nResult: %d passed, %d failed" % (_p, _f))
    sys.exit(1 if _f else 0)


if __name__ == "__main__":
    main()

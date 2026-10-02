"""«الإضافات الأخرى» (‏stremio_extras): قراءة رابط الإضافة والتحقّق منه، والقائمة، وتثبيتها في الحسابات.
التشغيل: python3 tests/test_stremio_extras.py   (والتثبيت عبر الأداة في tests/test_stremio_accounts.py)"""
import os
import shutil
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import mock_addon  # noqa: E402
import stremio_accounts as A  # noqa: E402
import stremio_extras as X  # noqa: E402

PASS = FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  \033[32mPASS\033[0m  {label}")
    else:
        FAIL += 1
        print(f"  \033[31mFAIL\033[0m  {label}  {extra}")


def raises(fn, words=""):
    try:
        fn()
    except ValueError as e:
        return words in str(e)
    return False


def main():
    print("== الرابط ==")
    check("stremio:// ← https، والرابط بلا manifest.json يُكمَّل", X.norm_url("stremio://aio.example.com/abc/") == "https://aio.example.com/abc/manifest.json"
          and X.norm_url(" https://a.b/x/manifest.json?c=1 ") == "https://a.b/x/manifest.json?c=1")
    check("ما ليس رابطًا يُرفض", all(raises(lambda u=u: X.norm_url(u), "manifest") for u in ("", "ftp://a.b/m", "https://u:p@a.b/m", "aio")))
    X.ALLOW_LOCAL = False
    check("لا يُقرأ رابطٌ إلى الجهاز أو شبكةٍ داخلية", not X._public("127.0.0.1") and not X._public("10.1.2.3") and not X._public("169.254.169.254")
          and not X._public("localhost") and not X._public("no-such-host.invalid"))
    check("ولا تُرسل الأداة طلبه أصلًا", raises(lambda: X.fetch("http://127.0.0.1:1/aio/manifest.json"), "شبكةٍ داخلية"))

    srv = mock_addon.serve()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    X.ALLOW_LOCAL = True
    print("== قراءة الإضافة ==")
    d = X.fetch(base + "/aio/")
    check("manifest الإضافة ← وصفها للتثبيت", d["transportUrl"] == base + "/aio/manifest.json" and d["manifest"]["name"] == "AIOMetadata"
          and d["flags"] == {"official": False, "protected": False})
    check("إضافةٌ تحتاج إعدادًا تُرفض (يُلصق رابطها بعد الإعداد)", raises(lambda: X.fetch(base + "/needs/manifest.json"), "تحتاج إعدادًا"))
    check("وصفحةٌ ليست manifest", raises(lambda: X.fetch(base + "/html/manifest.json"), "لا يعيد manifest"))
    check("ورابطٌ لا يوجد", raises(lambda: X.fetch(base + "/nope/manifest.json"), "404"))
    X.ALLOW_LOCAL = False
    import urllib.request
    check("وتحويلٌ (302) إلى عنوانٍ داخلي لا يُتبع", raises(lambda: X._Checked().redirect_request(
        urllib.request.Request("https://aio.example.com/m"), None, 302, "Found", {}, "http://169.254.169.254/latest"), "لا يُقرأ"))
    X.ALLOW_LOCAL = True

    print("== القائمة ==")
    dd = tempfile.mkdtemp(prefix="extras_")
    try:
        e = X.add(dd, "a1", base + "/aio/manifest.json")
        it = X.items(dd, "a1")
        check("تُحفظ للعميل باسمها وإصدارها وشعارها", [(i["name"], i["version"], i["logo"]) for i in it] == [("AIOMetadata", "1.9.0", "https://example.com/aio.png")]
              and X.items(dd, "a2") == [])
        check("وإضافتها مرةً ثانية تحدّث وصفها لا تكرّرها", X.add(dd, "a1", base + "/aio")["id"] == e["id"] and len(X.items(dd, "a1")) == 1)
        check("وأوصافها للتثبيت", [x["manifest"]["id"] for x in X.descriptors(dd, "a1")] == ["community.aiometadata"]
              and X.descriptors(dd, "a1", {"other"}) == [])
        check("لا عملية بلا حسابات", raises(lambda: X.start(dd, "a1", e["id"]), "لا حسابات"))
        check("ولإضافةٍ ليست في القائمة", raises(lambda: X.start(dd, "a1", "nope"), "ليست في القائمة"))
        check("الحذف من القائمة", X.remove(dd, "a1", e["id"]) and X.items(dd, "a1") == [] and not X.remove(dd, "a1", e["id"]))
    finally:
        shutil.rmtree(dd, ignore_errors=True)

    print("== في قائمة الحساب: بعد إضافاتنا، بلا تكرار ==")
    ours = {"transportUrl": "https://g/stremio/T/manifest.json", "manifest": {"id": A.OURS + "x", "idPrefixes": ["sqaaaaaa:"]}}
    cine = {"transportUrl": "https://v3-cinemeta.strem.io/manifest.json", "manifest": {"id": "com.linvo.cinemeta"}}
    out = A._with_extras([ours, cine], [d])
    check("الإضافة الأخرى بعد إضافتنا وقبل Cinemeta", [a["manifest"]["id"] for a in out] == [A.OURS + "x", "community.aiometadata", "com.linvo.cinemeta"])
    check("وما فيه منها (بالرابط أو المعرّف) لا يُكرَّر", A._with_extras(out, [d]) is out
          and A._with_extras([cine, {**d, "transportUrl": "https://other/manifest.json"}], [d])[0] is cine
          and len(A._with_extras([cine, {**d, "transportUrl": "https://other/manifest.json"}], [d])) == 2)
    srv.shutdown()

    print(f"\n{'-' * 40}\nResult: \033[32m{PASS} passed\033[0m, " + (f"\033[31m{FAIL} failed\033[0m" if FAIL else "0 failed"))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()

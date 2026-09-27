#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
نص الشرح لكل عميل: خيار يفعّله المدير لحسابٍ بعينه (copy_guide) فتنسخ صفحة
الإنشاء نص الشرح كاملًا بدل السطر الواحد. هنا جهة الخادم: الحفظ والتحقّق وما
يصل صفحة الإنشاء (/api/me)، وألّا يمسح حفظُ الحساب ما لا يديره نموذجه.
تشغيل:  python tests/test_guide_text.py
"""
import os, re, sys, json, time, shutil, tempfile, subprocess, http.cookiejar, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
_UNIT_DATA = tempfile.mkdtemp(prefix="gtext_unit_")
os.environ["XM_DATA"] = _UNIT_DATA        # قبل الاستيراد (لفحص guide_sub مباشرة)
import xm_lines as X  # noqa: E402
ADMIN_PORT = int(os.environ.get("ADMIN_PORT_GT", "9731"))
ADMIN = f"http://127.0.0.1:{ADMIN_PORT}"
_p = _f = 0
def check(l, c, x=""):
    global _p, _f
    print((f"  \033[32mPASS\033[0m  {l}" if c else f"  \033[31mFAIL\033[0m  {l}") + (f"  ({x})" if x else ""))
    _p += 1 if c else 0; _f += 0 if c else 1

def session():
    cj = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    def jreq(path, obj=None):
        data = json.dumps(obj).encode() if obj is not None else None
        req = urllib.request.Request(ADMIN + path, data=data, headers={"Content-Type": "application/json"},
                                     method="POST" if obj is not None else "GET")
        try: r = op.open(req, timeout=15); return r.getcode(), json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try: return e.code, json.loads(e.read() or b"{}")
            except Exception: return e.code, {}
    return jreq

CASPER_GATE = {"name": "بوابة كاسبر", "mode": "web", "web_flavor": "casper", "host": "http://ssouqhost.vip:80",
               "panel_base": "http://127.0.0.1:1/iptv", "panel_user": "u", "panel_pass": "p", "digits": 10,
               "guide_url": "https://guide.ssouq.com/#activate/casper"}

def main():
    data_dir = tempfile.mkdtemp(prefix="gtext_")
    env = dict(os.environ, XM_DATA=data_dir, XM_BIND="127.0.0.1", XM_PORT=str(ADMIN_PORT))
    app = subprocess.Popen([sys.executable, os.path.join(ROOT, "xm_lines.py"), "web"], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try: urllib.request.urlopen(ADMIN + "/admin/login", timeout=0.3); break
        except urllib.error.HTTPError: break
        except Exception: time.sleep(0.1)
    try:
        adm = session()
        adm("/admin/api/setup", {"password": "admin123"})

        print("== 1. The default text is the requested one, with placeholders ==")
        _, d = adm("/admin/api/accounts")
        dflt = d.get("default_guide_text", "")
        check("admin gets the default text", dflt.startswith("📲 طريقة التثبيت والتفعيل"), dflt[:30])
        check("default has guide/host/user/pass placeholders",
              all(k in dflt for k in ("🔗 شرح التثبيت:\n{guide}", "Host: {host}\nUser: {user}\nPass: {pass}")))
        check("default names the subscription per gate, not «كاسبر» for all",
              "واختيار سيرفر {server} ✅" in dflt and "كاسبر" not in dflt)
        check("default keeps the warning block", "⚠️ مهم جدًا:" in dflt and dflt.endswith("خطوات التفعيل الموجودة في الدليل."))

        _, d = adm("/admin/api/accounts", {"name": "كاسبر", "user": "casper", "password": "pw_casper", "gates": [CASPER_GATE]})
        cas = next(a for a in d["accounts"] if a["user"] == "casper")
        _, d = adm("/admin/api/accounts", {"name": "آخر", "user": "other", "password": "pw_other", "gates": [CASPER_GATE]})
        oth = next(a for a in d["accounts"] if a["user"] == "other")
        check("off by default", cas.get("copy_guide") is False and cas.get("guide_text") == "")

        me_c, me_o = session(), session()
        me_c("/admin/api/login", {"user": "casper", "password": "pw_casper"})
        me_o("/admin/api/login", {"user": "other", "password": "pw_other"})
        _, m = me_c("/admin/api/me")
        check("create page gets no text while off", m.get("guide_text") == "", repr(m.get("guide_text"))[:40])

        print("\n== 2. Enabling it for one client ==")
        body = {"id": cas["id"], "name": cas["name"], "user": "casper", "password": "",
                "gates": cas["gates"], "copy_guide": True, "guide_text": dflt}
        c, d = adm("/admin/api/accounts", body)
        cas = next(a for a in d.get("accounts", []) if a["user"] == "casper")
        check("saved on", c == 200 and cas.get("copy_guide") is True, d.get("error", ""))
        check("the unedited default is stored empty (follows the default)", cas.get("guide_text") == "")
        _, m = me_c("/admin/api/me")
        check("that client's create page gets the default text", m.get("guide_text") == dflt)
        _, m = me_o("/admin/api/me")
        check("another client stays on the one-line copy", m.get("guide_text") == "")
        c, d = adm("/admin/api/accounts", {**body, "guide_text": dflt.replace("{server}", "كاسبر")})
        cas = next(a for a in d.get("accounts", []) if a["user"] == "casper")
        check("the old «كاسبر for all» default (stale page) also follows the default", c == 200 and cas.get("guide_text") == "")

        print("\n== 3. A custom text per client ==")
        custom = "مرحبًا 👋\r\nHost: {host}\r\nUser: {user}\r\nPass: {pass}\r\n{guide}\r\n"
        c, d = adm("/admin/api/accounts", {**body, "guide_text": custom})
        cas = next(a for a in d.get("accounts", []) if a["user"] == "casper")
        want = "مرحبًا 👋\nHost: {host}\nUser: {user}\nPass: {pass}\n{guide}"
        check("custom text saved with unix newlines, trimmed", c == 200 and cas.get("guide_text") == want, repr(cas.get("guide_text"))[:60])
        _, m = me_c("/admin/api/me")
        check("create page gets the custom text", m.get("guide_text") == want)

        c, d = adm("/admin/api/accounts", {**body, "guide_text": "Host: {host}\nUser: {user}"})
        check("on + text without {pass} is refused", c == 400 and "{pass}" in d.get("error", ""), d.get("error", ""))
        _, m = me_c("/admin/api/me")
        check("refused save changed nothing", m.get("guide_text") == want)
        c, d = adm("/admin/api/accounts", {**body, "guide_text": "x" * 5000})
        check("an over-long text is refused", c == 400, d.get("error", ""))

        c, d = adm("/admin/api/accounts", {**body, "copy_guide": False, "guide_text": "مسودة بلا بيانات"})
        check("off + draft text is kept (not validated while off)", c == 200 and
              next(a for a in d["accounts"] if a["user"] == "casper").get("guide_text") == "مسودة بلا بيانات")
        _, m = me_c("/admin/api/me")
        check("off again = one-line copy", m.get("guide_text") == "")
        adm("/admin/api/accounts", {**body, "guide_text": custom})

        print("\n== 4. Saves that don't carry the option keep it ==")
        c, d = adm("/admin/api/accounts", {"id": cas["id"], "name": "كاسبر ٢", "user": "casper", "password": "", "gates": cas["gates"]})
        cas = next(a for a in d.get("accounts", []) if a["user"] == "casper")
        check("admin save without the keys keeps them", c == 200 and cas.get("copy_guide") is True and cas.get("guide_text") == want)
        me_c("/admin/api/myguide", {"guide_url": "https://guide.ssouq.com/"})
        me_c("/admin/api/mygates", {**CASPER_GATE, "id": cas["gates"][0]["id"], "host": "http://ssouqhost.vip:8080"})
        _, m = me_c("/admin/api/me")
        check("client's own guide/gate edits keep it", m.get("guide_text") == want)
        c, _ = me_c("/admin/api/accounts", {**body, "copy_guide": False})
        check("a client cannot switch it themselves", c == 403, str(c))

        print("\n== 5. Saving a client from the accounts page keeps its renew settings ==")
        c, d = me_c("/admin/api/renew/panels", {"panels": [{"name": "لوحة كاسبر", "hosts": ["ssouqhost.vip"]}]})
        check("client saved a renew panel", c == 200 and len(d.get("panels", [])) == 1, d.get("error", ""))
        _, d = adm("/admin/api/accounts")
        cas = next(a for a in d["accounts"] if a["user"] == "casper")
        adm("/admin/api/accounts", {"id": cas["id"], "name": cas["name"], "user": "casper", "password": "",
                                    "gates": cas["gates"], "copy_guide": True, "guide_text": dflt})
        _, r = me_c("/admin/api/renew/config")
        names = [p.get("name") for p in (r.get("renew") or {}).get("panels", [])]
        check("renew panel survives the admin save", names == ["لوحة كاسبر"], str(names))

        print("\n== 6. {server}: the subscription name as the guide shows it ==")
        G = lambda **k: {"name": "", "mode": "api", **k}
        for label, g, url, want in [
            ("casper link wins over the gate name", G(name="بوابة مرح"), "https://guide.ssouq.com/#activate/casper", "كاسبر"),
            ("falcon link (deep path)", G(), "https://guide.ssouq.com/#activate/falcon/android/2", "فالكون"),
            ("smart link", G(), "https://guide.ssouq.com/#activate/smart", "سمارت"),
            ("old marah link = smart", G(), "https://guide.ssouq.com/#activate/marah", "سمارت"),
            ("no sub in link: by gate name مرح", G(name="بوابة مرح"), "https://guide.ssouq.com/", "سمارت"),
            ("no link: by gate name Falcon", G(name="Falcon 2"), "", "فالكون"),
            ("no link: Falcon gate type", G(name="بوابة جديدة", mode="falcon"), "", "فالكون"),
            ("no link: Casper panel type", G(name="بوابة جديدة", mode="web", web_flavor="casper"), "", "كاسبر"),
            ("unknown: gate name without «بوابة»", G(name="بوابة الريم"), "https://guide.ssouq.com/#activate/xyz", "الريم"),
        ]:
            got = X.guide_sub(g, url)
            check(label + " → " + want, got == want, got)
        src = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
        block = src[src.index("const SUBS = {"):]
        names = dict(re.findall(r'(\w+):\s*\{\s*name:\s*"([^"]+)"', block[:block.index("};")]))
        check("names match the guide's SUBS in index.html", names == X.GUIDE_SUBS, str(names))
        check("the guide still reads the old marah key as smart", 'k === "marah" ? "smart"' in src)

        _, m = me_c("/admin/api/me")
        check("create page gets the gate's subscription name", m["gates"][0].get("guide_sub") == "كاسبر", m["gates"][0].get("guide_sub"))
        adm("/admin/api/accounts", {"name": "سمارت", "user": "smart", "password": "pw_smart",
                                    "guide_url": "https://guide.ssouq.com/#activate/smart",
                                    "gates": [{**CASPER_GATE, "name": "بوابة ٣", "web_flavor": "xtream", "guide_url": ""}]})
        me_s = session(); me_s("/admin/api/login", {"user": "smart", "password": "pw_smart"})
        _, m = me_s("/admin/api/me")
        check("gate without its own link uses the client's guide link", m["gates"][0].get("guide_sub") == "سمارت", m["gates"][0].get("guide_sub"))
        print("\n== 7. Import carries the option (replaces all accounts — keep last) ==")
        c, d = adm("/admin/api/accounts/import", {"accounts": [
            {"name": "مستورد", "user": "imp", "password": "pw_imp", "gates": [], "copy_guide": True, "guide_text": ""}]})
        imp = (d.get("accounts") or [{}])[0]
        check("imported account keeps copy_guide", c == 200 and imp.get("copy_guide") is True and imp.get("guide_text") == "", d.get("error", ""))

    finally:
        app.terminate()
        try: app.wait(timeout=5)
        except Exception: app.kill()
        shutil.rmtree(data_dir, ignore_errors=True)
        shutil.rmtree(_UNIT_DATA, ignore_errors=True)
    print("\n----------------------------------------")
    print(f"Result: \033[32m{_p} passed\033[0m, " + (f"\033[31m{_f} failed\033[0m" if _f else "0 failed"))
    sys.exit(1 if _f else 0)

if __name__ == "__main__":
    main()

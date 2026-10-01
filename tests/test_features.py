#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ميزات جديدة عبر بوابة فالكون وهمية: أسماء عربية، حالة (نقاط/آخر يوزر)،
بحث بالـ user/pass، رابط شرح عام لكل البوابات، وكشف الإنشاء المباشر،
وعدّاد الإنشاء الحيّ لدفعةٍ جارية («جاري الإنشاء… ٧ من ٢٠»).
تشغيل:  python tests/test_features.py
"""
import os, sys, json, time, shutil, tempfile, threading, subprocess, http.cookiejar, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
FALCON_PORT = int(os.environ.get("FALCON_PORT", "9677")); ADMIN_PORT = int(os.environ.get("ADMIN_PORT2", "9679"))
ADMIN = f"http://127.0.0.1:{ADMIN_PORT}"; FALCON = f"http://127.0.0.1:{FALCON_PORT}/api/v1"
FALCON2_PORT = int(os.environ.get("FALCON2_PORT", "9683")); FALCON2 = f"http://127.0.0.1:{FALCON2_PORT}/api/v1"
_p = _f = 0
def check(l, c, x=""):
    global _p, _f
    print((f"  \033[32mPASS\033[0m  {l}" if c else f"  \033[31mFAIL\033[0m  {l}") + (f"  ({x})" if x else ""))
    _p += 1 if c else 0; _f += 0 if c else 1

def main():
    global _p, _f
    data_dir = tempfile.mkdtemp(prefix="feat_")
    env = dict(os.environ, XM_DATA=data_dir, XM_BIND="127.0.0.1", XM_PORT=str(ADMIN_PORT))
    # كل إنشاءٍ على الفالكون الوهمية يأخذ ٠٫٣ث، فتُرى الدفعة في منتصفها (القسم ٦)
    falcon = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_falcon.py"), str(FALCON_PORT), "testkey"],
                              env=dict(os.environ, MOCK_FALCON_CREATE_DELAY="0.3"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    falcon2 = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_falcon.py"), str(FALCON2_PORT), "key2"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    app = subprocess.Popen([sys.executable, os.path.join(ROOT, "xm_lines.py"), "web"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    def opener():
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    op = opener()
    def jreq(path, obj=None, via=None):
        data = json.dumps(obj).encode() if obj is not None else None
        req = urllib.request.Request(ADMIN + path, data=data, headers={"Content-Type": "application/json"}, method="POST" if obj is not None else "GET")
        try: r = (via or op).open(req, timeout=15); return r.getcode(), json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try: return e.code, json.loads(e.read() or b"{}")
            except Exception: return e.code, {}
    def up(u):
        for _ in range(60):
            try: urllib.request.urlopen(u, timeout=0.3); return
            except urllib.error.HTTPError: return
            except Exception: time.sleep(0.1)
    try:
        up(ADMIN + "/admin/login"); up(FALCON + "/me"); up(FALCON2 + "/me")
        jreq("/admin/api/setup", {"password": "admin123"})
        jreq("/admin/api/accounts", {"name": "Ali", "user": "ali", "password": "pw_ali", "gates": [
            {"name": "فالكون", "mode": "falcon", "api_url": FALCON, "api_key": "testkey"}]})
        jreq("/admin/api/accounts", {"name": "Sara", "user": "sara", "password": "pw_sara", "gates": []})
        # عميلٌ بخمس بوابات (القسم ٧): فالكونان حيّتان كلٌّ بلوحتها، ومتوقّفة، وبمفتاح خاطئ، وواحدةٌ بلا بحث
        jreq("/admin/api/accounts", {"name": "Multi", "user": "multi", "password": "pw_multi", "gates": [
            {"name": "فالكون ١", "mode": "falcon", "api_url": FALCON, "api_key": "testkey"},
            {"name": "فالكون ٢", "mode": "falcon", "api_url": FALCON2, "api_key": "key2"},
            {"name": "فالكون متوقّفة", "mode": "falcon", "api_url": "http://127.0.0.1:9/api/v1", "api_key": "x"},
            {"name": "فالكون بمفتاح خاطئ", "mode": "falcon", "api_url": FALCON, "api_key": "wrong"},
            {"name": "Reseller API", "mode": "api", "api_url": "http://127.0.0.1:9/reseller/index.php", "api_key": "x",
             "host": "http://api.host"}]})
        code, _ = jreq("/admin/api/create/progress?job=abc")
        admin_progress_code = code
        admin_search_all_code, _ = jreq("/admin/api/search?gate=all&q=user003")
        op.open(ADMIN + "/admin/logout")
        jreq("/admin/api/login", {"user": "ali", "password": "pw_ali"})
        _, me = jreq("/admin/api/me"); gid = me["gates"][0]["id"]

        print("== 1. Arabic package names ==")
        _, d = jreq("/admin/api/packages?gate=" + gid)
        names = [p["name"] for p in d.get("packages", [])]
        check("packages show Arabic", "شهر" in names and "3 أشهر" in names and any("جهاز" in n for n in names), " / ".join(names))

        print("\n== 2. Gate status (credits + last user) ==")
        _, s = jreq("/admin/api/gate-status?gate=" + gid)
        check("status has credits", s.get("credits") == 100.0, str(s.get("credits")))
        check("status has total + last user", s.get("total") == 5 and s.get("last_username") == "user005",
              "total=%s last=%s" % (s.get("total"), s.get("last_username")))

        print("\n== 3. Search by username and by password ==")
        _, d = jreq("/admin/api/search?gate=" + gid + "&q=user003")
        check("search by username", len(d.get("results", [])) == 1 and d["results"][0]["username"] == "user003")
        _, d = jreq("/admin/api/search?gate=" + gid + "&q=pass004")
        check("search by password (client-side scan)", len(d.get("results", [])) == 1 and d["results"][0]["username"] == "user004")

        print("\n== 4. Global guide URL for all gates ==")
        _, d = jreq("/admin/api/myguide", {"guide_url": "https://guide.ssouq.com/"})
        check("guide saved", d.get("ok") and d.get("guide_url") == "https://guide.ssouq.com/")
        _, d = jreq("/admin/api/packages?gate=" + gid)
        check("packages reflect the account guide, aimed at the gate's subscription (falcon)",
              d.get("guide_url") == "https://guide.ssouq.com/#activate/falcon", d.get("guide_url"))

        print("\n== 5. Create uses Falcon + Arabic + guide; status detects the new user ==")
        _, d = jreq("/admin/api/create", {"gate": gid, "package_id": "167", "username": "newone", "password": "np", "count": 1})
        ln = (d.get("lines") or [{}])[0].get("line", "")
        check("line new-format with host + guide", " User newone " in ln and "s.falconiptv.ink" in ln
              and ln.endswith(" Guide https://guide.ssouq.com/#activate/falcon"), ln[-60:])
        _, s2 = jreq("/admin/api/gate-status?gate=" + gid)
        check("status now shows the new last user + fewer credits", s2.get("last_username") == "newone" and s2.get("credits") == 99.5,
              "last=%s credits=%s" % (s2.get("last_username"), s2.get("credits")))

        print("\n== 6. Live create counter: the page sees how far a batch has got ==")
        job, res, snaps = "t6job", {}, []
        def run():
            res["d"] = jreq("/admin/api/create", {"gate": gid, "package_id": "167", "count": 5, "job": job})[1]
        th = threading.Thread(target=run); th.start()
        while th.is_alive():
            snaps.append(jreq("/admin/api/create/progress?job=" + job)[1])
            time.sleep(0.1)
        th.join()
        live = [x for x in snaps if x.get("running")]
        check("batch of 5 created", len((res.get("d") or {}).get("lines") or []) == 5, str(res.get("d"))[:120])
        check("counter seen mid-batch (running, 0 < done < 5, total 5)",
              any(0 < x.get("done", 0) < 5 and x.get("total") == 5 for x in live), str([x.get("done") for x in live]))
        dones = [x.get("done", 0) for x in live]
        check("counter only goes up", dones == sorted(dones), str(dones))
        _, fin = jreq("/admin/api/create/progress?job=" + job)
        check("after the batch: not running, 5 of 5", fin.get("running") is False and fin.get("done") == 5 and fin.get("total") == 5, str(fin))
        _, d = jreq("/admin/api/create/progress?job=nosuchjob")
        check("unknown job reads idle", d.get("idle") is True and d.get("running") is False, str(d))
        _, d = jreq("/admin/api/create/progress?job=" + "../" + job)
        check("a malformed job id is ignored (idle)", d.get("idle") is True, str(d))
        sara = opener()
        jreq("/admin/api/login", {"user": "sara", "password": "pw_sara"}, via=sara)
        _, d = jreq("/admin/api/create/progress?job=" + job, via=sara)
        check("another account can't read this batch's counter", d.get("idle") is True, str(d))
        check("admin (no account) gets 403", admin_progress_code == 403, str(admin_progress_code))

        print("\n== 7. Search across all of the client's gates at once ==")
        multi = opener()
        jreq("/admin/api/login", {"user": "multi", "password": "pw_multi"}, via=multi)
        _, me = jreq("/admin/api/me", via=multi)
        g = {x["name"]: x["id"] for x in me["gates"]}
        g1, g2, gx, gk, ga = g["فالكون ١"], g["فالكون ٢"], g["فالكون متوقّفة"], g["فالكون بمفتاح خاطئ"], g["Reseller API"]
        _, d = jreq("/admin/api/search?gate=all&q=user003", via=multi)
        out = {x["id"]: x for x in d.get("gates", [])}
        check("one entry per gate, in the client's order, with its name",
              d.get("all") is True and [x["id"] for x in d.get("gates", [])] == [x["id"] for x in me["gates"]]
              and out[g1]["name"] == "فالكون ١", json.dumps(d, ensure_ascii=False)[:160])
        check("found on both live gates", [r["username"] for r in out[g1]["results"]] == ["user003"]
              and [r["username"] for r in out[g2]["results"]] == ["user003"])
        check("an unreachable gate reports its error, without sinking the others",
              out[gx]["results"] == [] and "فالكون" in out[gx].get("error", ""), out[gx].get("error", ""))
        check("a rejected key is an error, not a false «not found»",
              out[gk]["results"] == [] and "unauthorized" in out[gk].get("error", ""), out[gk].get("error", ""))
        check("a gate without search says so", out[ga].get("unsupported") is True and out[ga]["results"] == [])
        jreq("/admin/api/create", {"gate": g2, "package_id": "167", "username": "onlyon2", "password": "pw2", "count": 1}, via=multi)
        _, d = jreq("/admin/api/search?gate=all&q=onlyon2", via=multi)
        hits = {x["id"]: [r["username"] for r in x["results"]] for x in d.get("gates", []) if x["results"]}
        check("a user that exists on one gate only is found there only", hits == {g2: ["onlyon2"]}, json.dumps(hits))
        _, d = jreq("/admin/api/search?gate=all&q=pw2", via=multi)
        hits = {x["id"]: [r["username"] for r in x["results"]] for x in d.get("gates", []) if x["results"]}
        check("…and by its password too", hits == {g2: ["onlyon2"]}, json.dumps(hits))
        _, d = jreq("/admin/api/create", {"gate": g1, "package_id": "167", "count": 1, "replaces": "777000111"}, via=multi)
        new_u = (d.get("lines") or [{}])[0].get("username", "")
        _, d = jreq("/admin/api/search?gate=all&q=777000111", via=multi)
        out = {x["id"]: x for x in d.get("gates", [])}
        check("a replaced number: not on any gate, its link shows under the gate it was replaced on",
              all(not x["results"] for x in d["gates"]) and [(l["direction"], l["new"]) for l in out[g1]["links"]] == [("replaced_by", new_u)]
              and all(not x["links"] for x in d["gates"] if x["id"] != g1), json.dumps(d, ensure_ascii=False)[:200])
        _, d = jreq("/admin/api/search?gate=all&q=", via=multi)
        check("empty query: nothing searched", d == {"all": True, "gates": []}, str(d))
        _, d = jreq("/admin/api/search?gate=" + g1 + "&q=user003", via=multi)
        check("one gate (as before): same shape", "all" not in d and [r["username"] for r in d.get("results", [])] == ["user003"], str(d)[:120])
        _, d = jreq("/admin/api/search?gate=" + gk + "&q=user003", via=multi)
        check("one gate with a rejected key: says why", d.get("results") == [] and "unauthorized" in d.get("error", ""), str(d)[:120])
        _, d = jreq("/admin/api/search?gate=all&q=user003")
        check("another account searches only its own gates", [x["id"] for x in d.get("gates", [])] == [gid], str(d)[:120])
        code, _ = jreq("/admin/api/search?gate=all&q=user003", via=sara)
        check("an account without gates gets 403", code == 403, str(code))
        check("admin (no account) gets 403 for all gates too", admin_search_all_code == 403, str(admin_search_all_code))
    finally:
        for pr in (app, falcon, falcon2):
            pr.terminate()
            try: pr.wait(timeout=5)
            except Exception: pr.kill()
        shutil.rmtree(data_dir, ignore_errors=True)
    print("\n----------------------------------------")
    print(f"Result: \033[32m{_p} passed\033[0m, " + (f"\033[31m{_f} failed\033[0m" if _f else "0 failed"))
    sys.exit(1 if _f else 0)

if __name__ == "__main__":
    main()

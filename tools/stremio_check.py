#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
فحص إضافة Stremio لاشتراكٍ كما يمشيها Stremio نفسه: كل صفحات كل كتالوج (‏skip حتى صفحةٍ أقلّ من 100)، وكل
تصنيف، والبحث، وتفاصيل عيّنةٍ من كل نوع، وروابط تشغيلها عند السيرفر (‏302 إلى خادم البث أو 200 = يعمل؛ 403/404 =
لا يعمل). وتُقارن الأعداد بقوائم السيرفر نفسه، فيظهر إن نقص شيء.

  python tools/stremio_check.py http://mrha.ink:80 USER PASS          مباشرةً (بلا خادم: stremio_addon نفسه)
  python tools/stremio_check.py --addon https://guide.ssouq.com/stremio/<رمز>/manifest.json
                                                                       الإضافة المنشورة عبر HTTP
  --no-genres  بلا المشي في التصنيفات (أسرع)    --samples N  عيّنات التفاصيل والتشغيل لكل نوع (الافتراضي 3)

البيانات لا تُطبع: الباسورد يُستبدل بـ *** في كل ما يظهر.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import stremio_addon as S  # noqa: E402

UA = S.UA


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def probe(url, timeout=20):
    """رابط تشغيل ← (الرمز، إلى أين يحوّل) بلا اتّباع التحويل ولا تنزيل الملف."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-1023"})
    try:
        r = urllib.request.build_opener(_NoRedirect).open(req, timeout=timeout)
        r.read(1024)
        return r.getcode(), ""
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location", "")
    except Exception as e:                      # noqa: BLE001 — فحصٌ يقول ما حدث ولا يتوقّف
        return None, type(e).__name__


class Direct:
    """الإضافة نفسها في هذه العملية (‏stremio_addon) — الأعداد تُقارن بقوائم السيرفر."""

    def __init__(self, host, user, pw):
        self.cfg = S.Cfg(S.norm_host(host), user, pw)
        self.secret = pw

    def manifest(self):
        return S.manifest(self.cfg, "https://guide.ssouq.com")

    def catalog(self, kind, cid, extra):
        return S.catalog(self.cfg, kind, cid, extra)["metas"]

    def meta(self, kind, mid):
        return (S.meta(self.cfg, kind, mid) or {}).get("meta")

    def streams(self, kind, mid):
        return (S.streams(self.cfg, kind, mid) or {}).get("streams") or []

    def expected(self, kind):
        return len(S.lists(self.cfg, kind).items)

    def accounts(self, cid):
        return S.accounts_catalog([{"cfg": self.cfg, "label": ""}], S.prefix(self.cfg), "https://guide.ssouq.com")["metas"]


class Remote:
    """الإضافة المنشورة عبر HTTP كما يطلبها Stremio — الأعداد تُقارن بحالة الاشتراك (‏status.json)."""

    def __init__(self, manifest_url):
        self.base = manifest_url.rsplit("/manifest.json", 1)[0]
        self.secret = None
        self._status = None

    def get(self, path):
        req = urllib.request.Request(self.base + path, headers={"User-Agent": "stremio-check"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())

    def manifest(self):
        return self.get("/manifest.json")

    def catalog(self, kind, cid, extra):
        ex = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in extra.items() if v not in ("", None))
        return self.get(f"/catalog/{kind}/{cid}" + (f"/{ex}" if ex else "") + ".json").get("metas") or []

    def meta(self, kind, mid):
        try:
            return self.get(f"/meta/{kind}/{quote(mid, safe='')}.json").get("meta")
        except urllib.error.HTTPError:
            return None

    def streams(self, kind, mid):
        try:
            return self.get(f"/stream/{kind}/{quote(mid, safe='')}.json").get("streams") or []
        except urllib.error.HTTPError:
            return []

    def accounts(self, cid):
        return self.get(f"/catalog/{quote(S.ACCOUNTS, safe='')}/{cid}.json").get("metas") or []

    def expected(self, kind):
        if self._status is None:
            self._status = self.get("/status.json")
        return (self._status.get("counts") or {}).get(kind)


def walk(src, kind, cid, **extra):
    got, pages = [], 0
    while True:
        page = src.catalog(kind, cid, {**extra, "skip": len(got)} if got else dict(extra))
        pages += 1
        got += page
        if len(page) < S.PAGE or pages > 2000:
            return got, pages


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("creds", nargs="*", help="HOST USER PASS")
    ap.add_argument("--addon", help="رابط manifest.json لإضافةٍ منشورة")
    ap.add_argument("--no-genres", action="store_true")
    ap.add_argument("--samples", type=int, default=3)
    a = ap.parse_args()
    if a.addon:
        src = Remote(a.addon)
    elif len(a.creds) == 3:
        src = Direct(*a.creds)
    else:
        ap.error("اكتب HOST USER PASS أو --addon <manifest>")
    hide = (lambda s: s.replace(src.secret, "***")) if src.secret else (lambda s: s)
    bad = 0

    t0 = time.time()
    man = src.manifest()
    print(f"الإضافة: {man['name']}  ({man['id']})  البادئة {man['idPrefixes']}")
    for c in man["catalogs"]:
        kind, cid = c["type"], c["id"]
        if kind == S.ACCOUNTS:                  # «الحسابات»: حال الخطوط لا محتوى
            cards = src.accounts(cid)
            bad += not cards
            print(f"\n[{kind}] {len(cards)} خط: " + " | ".join(hide(m.get("name", "")) for m in cards))
            continue
        genres = next((e.get("options") or [] for e in c["extra"] if e["name"] == "genre"), [])
        t = time.time()
        allm, pages = walk(src, kind, cid)
        exp = src.expected(kind)
        ids = {m["id"] for m in allm}
        ok = exp is None or (len(allm) == exp == len(ids))
        bad += not ok
        print(f"\n[{kind}] {c['name']}: {len(allm):,} عنصرًا في {pages} صفحة ({time.time() - t:.1f}ث)"
              f" — في السيرفر {exp if exp is not None else '؟'}{'' if ok else '  ✗ نقصٌ أو تكرار'}")
        if genres and not a.no_genres:
            t, total, empty = time.time(), 0, []
            for g in genres:
                n = len(walk(src, kind, cid, genre=g)[0])
                total += n
                if not n:
                    empty.append(g)
            ok = total == len(allm)
            bad += not ok
            print(f"  التصنيفات: {len(genres)} قسمًا، مجموعها {total:,}{' = الكل' if ok else '  ✗ لا يساوي الكل'}"
                  f" ({time.time() - t:.1f}ث)" + (f" — أقسامٌ فارغة: {len(empty)}" if empty else ""))
        if allm:
            q = allm[0]["name"].split("(")[0].strip()[:20]
            hit = src.catalog(kind, cid, {"search": q})
            ok = any(m["id"] == allm[0]["id"] for m in hit)
            bad += not ok
            print(f"  البحث «{q}»: {len(hit)} نتيجة{'' if ok else '  ✗ لم يجد العنصر نفسه'}")
        step = max(1, len(allm) // max(1, a.samples))
        for m in allm[::step][:a.samples]:
            meta = src.meta(kind, m["id"])
            if not meta:
                bad += 1
                print(f"  ✗ {m['name']}: بلا تفاصيل")
                continue
            vids = meta.get("videos") or []
            target = vids[0]["id"] if vids else m["id"]
            st = src.streams(kind, target)
            if not st:
                bad += 1
                print(f"  ✗ {m['name']}: بلا رابط تشغيل")
                continue
            code, where = probe(st[0]["url"])
            works = code in (200, 206, 301, 302, 307)
            bad += not works
            extra = f"، {len({v['season'] for v in vids})} مواسم و{len(vids)} حلقة" if vids else ""
            print(f"  {'✓' if works else '✗'} {m['name']}{extra} ← {hide(st[0]['url'])} ← {code}"
                  + (f" إلى {hide(where.split('?')[0])}" if where else ""))
    print(f"\n{'✓ كل شيء سليم' if not bad else f'✗ {bad} مشكلة'} ({time.time() - t0:.0f}ث)")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""فحص السكّان كاملًا (**قراءةٌ صرفة**): كل كيانٍ حيٍّ متاح (نحو 58 ألفًا) بصفحتيه العربية والإنجليزية (نحو 116 ألف مسار)،
على دفعاتٍ في خيطٍ خلفي، بعدّاد تقدّم ونقطة استئناف في ملف (`full-scan.json` في مجلد المراجعة) فيُكمل من حيث توقّف
إن أُوقف أو أُعيد تشغيل الخادم — ولا يكتب في القاعدة شيئًا: لا دمج ولا انقسام ولا إثراء ولا تحويلات ولا روابط.

لكل مسار: HTTP (كما تخدمه الطبقة: 200 للصفحة، 301 لمسار تحويل، 404 لغير ذلك)، canonical ذاتي ومطابق للمسار، `<html lang>`،
الأهلية (would_index) ووسم noindex (المعاينة)، قاعدة hreflang (كاملةً متبادلة مع x-default حين تستحق اللغتان؛ ولا وسم حين
تستحق واحدة)، canonical مكرّر، استعلامات/تصفّح، ومسارٌ هو تحويلٌ قديم. النتيجة تدخل qa.json تحت `full_population`.

    python seo_scan.py run      # يبدأ أو يستأنف حتى النهاية (من سطر الأوامر)
    python seo_scan.py state    # الحال والعدّادات
"""
import json
import os
import re
import sys
import threading
import time

import content_page as P
import seo_db
import seo_pages
import seo_qa
import seo_sources

BATCH = 50                       # كيانًا في الدفعة (×2 مسار) ثم نقطة استئناف — صغيرة ليتحرّك العدّاد كل نصف دقيقة تقريبًا
PAUSE = 0.05                     # ثانية بين الدفعات: لا يستأثر الخيط بالخادم
SCAN_VERSION = 1                 # يُرفع عند تغيّر منطق الفحص نفسه؛ ومعه بصمة ملفات الرسم تحدّد «هل النتائج قابلة للاستكمال»
WAIT_SLEEP = 30                  # ثانية بين نظرات الانتظار خارج وقت الهدوء
WATCHDOG_EVERY = 60              # ثانية: الحارس يستأنف فحصًا كان جاريًا حين أُعيد تشغيل الخادم (نشرٌ أو سقوط) — بلا ضغطة
_threads, _stop = {}, {}
_lock = threading.Lock()


def quiet_window(st):
    """نافذة الهدوء من الإعدادات ← (بداية، نهاية، إزاحة UTC بالساعات)؛ الافتراضي 0–12 بتوقيت السعودية."""
    q = st.get("scan_quiet_hours") if isinstance(st.get("scan_quiet_hours"), dict) else {}
    return int(q.get("start", 0)), int(q.get("end", 12)), float(q.get("utc_offset", 3))


def in_quiet_hours(st, now=None):
    """هل نحن داخل وقت الهدوء؟ (نافذةٌ قد تعبر منتصف الليل)."""
    start, end, off = quiet_window(st)
    if start == end:
        return True                             # نافذةٌ فارغة = بلا قيد
    h = (time.gmtime((now if now is not None else time.time()) + off * 3600).tm_hour)
    return start <= h < end if start < end else (h >= start or h < end)


def quiet_label(st):
    start, end, off = quiet_window(st)
    fmt = lambda h: f"{(h % 12) or 12} {'ص' if h % 24 < 12 else 'ظ' if h % 24 == 12 else 'م'}"   # noqa: E731
    return f"{fmt(start)} – {fmt(end)} (UTC{off:+g})"


def scan_key():
    """مفتاح التوافق: نسخة منطق الفحص + بصمة ملفات **الرسم** (seo_pages · content_page · seo_db). ما دام ثابتًا فالنتائج
    قابلة للاستكمال عبر النشر، ولو تغيّرت بصمة الكود الكلية (تقارير، بطاقة، إثراء…). تغيّره = نتائج غير قابلة للخلط: من الصفر."""
    import hashlib
    here = os.path.dirname(os.path.abspath(__file__))
    h = hashlib.sha1()
    for n in ("seo_pages.py", "content_page.py", "seo_db.py"):
        try:
            with open(os.path.join(here, n), "rb") as f:
                h.update(f.read())
        except OSError:
            pass
    return f"{SCAN_VERSION}:{h.hexdigest()[:12]}"


def path_(data_dir):
    return os.path.join(seo_sources.bundle_dir(data_dir), "full-scan.json")


def _empty(con, st):
    total = con.execute("SELECT COUNT(*) FROM content WHERE merged_into IS NULL AND available=1").fetchone()[0]
    return {"status": "idle", "started_at": None, "updated_at": None, "finished_at": None, "code_fingerprint": seo_sources.code_version()["code_fingerprint"],
            "entities_total": total, "routes_total": total * 2, "last_id": 0, "tested_entities": 0, "tested_routes": 0, "batches": 0, "seconds": 0.0,
            "preview": bool(st.get("preview")),
            "ar": {"routes": 0, "http_200": 0, "http_failures": 0, "canonical_failures": 0, "canonical_mismatch": 0, "language_mismatch": 0, "indexable": 0, "noindex": 0},
            "en": {"routes": 0, "http_200": 0, "http_failures": 0, "canonical_failures": 0, "canonical_mismatch": 0, "language_mismatch": 0, "indexable": 0, "noindex": 0},
            "hreflang": {"bilingual_pairs": 0, "expected": 0, "complete": 0, "incomplete": 0, "reciprocity_failures": 0, "missing_x_default": 0,
                         "single_language": 0, "single_language_ok": 0, "single_language_stray_alternates": 0, "none": 0},
            "duplicates": {"duplicate_canonical": 0, "faceted_query": 0, "old_redirect_urls": 0},
            "failures": 0, "failure_examples": [], "errors": 0, "error_examples": []}


def load(data_dir):
    try:
        with open(path_(data_dir), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _save(data_dir, s):
    p = path_(data_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _check_entity(con, data_dir, r, st, redirect_paths, canon_seen, s):
    """كيانٌ واحد بلغتيه ← يحدّث العدّادات؛ ويعيد قائمة مشكلاته (فارغة = سليم)."""
    pages, problems = {}, []
    for lang in ("ar", "en"):
        c = s[lang]
        c["routes"] += 1
        p = seo_pages._path(r, lang)
        ar_path = p[len(seo_db.EN):] if lang == "en" else p
        if ar_path in redirect_paths:
            code, page = 301, None
        else:
            res = seo_pages.render_entity(con, data_dir, r["type"], r["slug"], P.lang_of(lang), st)
            code, page = (200, res[1]) if res and res[0] == "page" else (301, None) if res and res[0] == "redirect" else (404, None)
        if code != 200:
            c["http_failures"] += 1; problems.append(f"http_{lang}={code}")
            if code == 301:
                s["duplicates"]["old_redirect_urls"] += 1
            continue
        c["http_200"] += 1
        html = page["html"].decode("utf-8")
        expected = seo_pages.SITE + p
        if page["canonical"] != expected:
            c["canonical_mismatch"] += 1; problems.append(f"canonical_mismatch_{lang}")
        if f'<link rel="canonical" href="{page["canonical"]}">' not in html:
            c["canonical_failures"] += 1; problems.append(f"canonical_self_{lang}")
        if f'<html lang="{lang}"' not in html:
            c["language_mismatch"] += 1; problems.append(f"language_{lang}")
        ok_idx = bool(page["index_ar"] if lang == "ar" else page["index_en"])
        c["indexable"] += 1 if ok_idx else 0
        c["noindex"] += 1 if 'name="robots" content="noindex' in html else 0
        if "?" in page["canonical"] or "#" in page["canonical"] or "/page/" in page["canonical"]:
            s["duplicates"]["faceted_query"] += 1; problems.append(f"faceted_{lang}")
        prev = canon_seen.get(page["canonical"])
        if prev is not None and prev != r["id"]:
            s["duplicates"]["duplicate_canonical"] += 1; problems.append(f"duplicate_canonical_{lang}")
        canon_seen[page["canonical"]] = r["id"]
        pages[lang] = {**page, "text": html, "code": 200}
    if len(pages) == 2:
        ok, det = seo_qa.hreflang_check(pages)
        h = s["hreflang"]
        if det["hreflang_mode"] == "bilingual":
            h["bilingual_pairs"] += 1; h["expected"] += 1
            if ok:
                h["complete"] += 1
            else:
                h["incomplete"] += 1; problems.append("hreflang_incomplete")
                if not det.get("reciprocal"):
                    h["reciprocity_failures"] += 1
                if any("x-default" not in t for t in det["tags"].values()):
                    h["missing_x_default"] += 1
        elif det["hreflang_mode"] == "single:none":
            h["none"] += 1
            if not det["no_alternate_tags"]:
                h["single_language_stray_alternates"] += 1; problems.append("stray_alternates")
        else:
            h["single_language"] += 1
            if ok:
                h["single_language_ok"] += 1
            else:
                h["single_language_stray_alternates"] += 1; problems.append("single_language_rule")
    return problems


def run(data_dir, stop=None, progress=None, resume=True):
    """يبدأ أو يستأنف الفحص حتى النهاية (أو حتى `stop()` تعود True) ← الحال. قراءةٌ صرفة."""
    con = seo_db.connect(data_dir, create=False)
    if con is None:
        return {"status": "error", "error": "لم تُبنَ القاعدة"}
    try:
        st = seo_db.settings(con)
        s = load(data_dir) if resume else None
        fp = seo_sources.code_version()["code_fingerprint"]
        sk = scan_key()
        compatible = bool(s) and (s.get("scan_key") in (None, sk))   # بلا مفتاح = نقطة استئنافٍ من قبل المفتاح (رسمٌ لم يتغيّر): تُكمَل مرةً وتُختم
        if not s or s.get("status") == "complete" or not compatible:
            s = _empty(con, st)                 # من البداية: فحصٌ جديد أو منطق الرسم/الفحص تغيّر (نتائج لا تُخلط)
        s["status"] = "running"
        s["started_at"] = s["started_at"] or int(time.time())
        s["scan_key"] = sk
        s["code_fingerprint"] = fp
        fps = s.setdefault("code_fingerprints", [])
        if fp not in fps:
            fps.append(fp)                      # كل بصمات الكود التي ساهمت (شفافية: الاستكمال عبر النشر)
        s["updated_at"] = int(time.time())
        _save(data_dir, s)                      # فورًا: البطاقة ترى «يفحص الآن 0 / N» قبل أول دفعة
        redirect_paths = {r["path"] for r in con.execute("SELECT path FROM redirect")}
        canon_seen = {}
        if s["last_id"]:                        # عند الاستئناف: canonical ما سبق فحصه يُعاد بناؤه من الروابط لا من الرسم (كشف التكرار)
            for r in con.execute("SELECT id, type, slug FROM content WHERE merged_into IS NULL AND available=1 AND id<=? ORDER BY id", (s["last_id"],)):
                for lang in ("ar", "en"):
                    canon_seen[seo_pages.SITE + seo_pages._path(r, lang)] = r["id"]
        seo_pages._services.data_dir = data_dir
        while True:
            if stop and stop():
                s["status"] = "paused"; s["updated_at"] = int(time.time()); _save(data_dir, s)
                return s
            if not in_quiet_hours(st):          # خارج وقت الهدوء: ينتظر بلا فقدان تقدّم (الحال «waiting» ويُستأنف وحده حين تحين النافذة)
                if s["status"] != "waiting":
                    s["status"] = "waiting"; s["quiet_hours"] = quiet_label(st); s["updated_at"] = int(time.time()); _save(data_dir, s)
                time.sleep(WAIT_SLEEP)
                continue
            if s["status"] != "running":
                s["status"] = "running"; s["updated_at"] = int(time.time()); _save(data_dir, s)
            t0 = time.time()
            rows = con.execute("SELECT * FROM content WHERE merged_into IS NULL AND available=1 AND id>? ORDER BY id LIMIT ?", (s["last_id"], BATCH)).fetchall()
            if not rows:
                break
            for r in rows:
                try:
                    problems = _check_entity(con, data_dir, r, st, redirect_paths, canon_seen, s)
                except Exception as ex:  # noqa: BLE001 — خطأ رسمٍ في كيانٍ لا يوقف الفحص: يُعدّ ويُسجَّل
                    problems = [f"error:{type(ex).__name__}: {str(ex)[:120]}"]
                    s["errors"] += 1
                    if len(s["error_examples"]) < 20:
                        s["error_examples"].append({"id": r["id"], "slug": r["slug"], "error": problems[0]})
                if problems:
                    s["failures"] += 1
                    if len(s["failure_examples"]) < 50:
                        s["failure_examples"].append({"id": r["id"], "slug": r["slug"], "problems": problems})
                s["tested_entities"] += 1
                s["tested_routes"] += 2
                s["last_id"] = r["id"]
            s["batches"] += 1
            s["seconds"] = round(s["seconds"] + (time.time() - t0), 1)
            s["updated_at"] = int(time.time())
            _save(data_dir, s)
            if progress:
                progress(s)
            time.sleep(PAUSE)
        s["status"] = "complete"
        s["finished_at"] = s["updated_at"] = int(time.time())
        s["entities_total_now"] = con.execute("SELECT COUNT(*) FROM content WHERE merged_into IS NULL AND available=1").fetchone()[0]
        _save(data_dir, s)
        return s
    finally:
        con.close()


def summary(s):
    """ملخّص الحال للبطاقة وqa.json: النسبة والمتبقّي والحكم (لا PASS إلا مكتملًا بلا فشل)."""
    if not s:
        return {"status": "never run", "verdict": "NOT PROVEN", "tested_entities": 0, "tested_routes": 0, "coverage_percent": 0.0, "remaining_entities": None}
    total = s["entities_total"] or 0
    pct = round(100.0 * s["tested_entities"] / total, 2) if total else 0.0
    remaining = max(0, total - s["tested_entities"])
    complete = s["status"] == "complete" and remaining == 0
    verdict = "PASS" if complete and s["failures"] == 0 and s["errors"] == 0 else ("FAIL" if complete else "INCOMPLETE")
    eta = round(s["seconds"] / s["tested_entities"] * remaining / 60) if s["tested_entities"] and remaining else 0
    return {"status": s["status"], "verdict": verdict, "code_fingerprint": s["code_fingerprint"], "started_at": s["started_at"], "updated_at": s["updated_at"], "finished_at": s.get("finished_at"),
            "entities_total": total, "routes_total": s["routes_total"], "tested_entities": s["tested_entities"], "tested_routes": s["tested_routes"],
            "coverage_percent": pct, "remaining_entities": remaining, "remaining_routes": remaining * 2, "eta_minutes": eta, "failures": s["failures"], "errors": s["errors"],
            "scan_key": s.get("scan_key"), "code_fingerprints": s.get("code_fingerprints", [s["code_fingerprint"]]),
            "seconds": s["seconds"], "batches": s["batches"], "ar": s["ar"], "en": s["en"], "hreflang": s["hreflang"], "duplicates": s["duplicates"],
            "failure_examples": s["failure_examples"][:20], "error_examples": s["error_examples"][:10], "entities_total_now": s.get("entities_total_now"),
            "read_only": "render only; no entity, source row, merge, split, enrichment, redirect or slug is written"}


# ================= الخيط الخلفي من بطاقة الإدارة =================
def start(data_dir, resume=True):
    """يبدأ (أو يستأنف) في خيطٍ خلفي؛ واحدٌ في وقته ← هل بدأ؟"""
    k = os.path.abspath(data_dir)
    t = _threads.get(k)
    if t and t.is_alive():
        return False
    _stop[k] = False

    def run_():
        try:
            run(data_dir, stop=lambda: _stop.get(k, False), resume=resume)
        except Exception as ex:  # noqa: BLE001
            s = load(data_dir) or {}
            s["status"] = "error"; s["error"] = f"{type(ex).__name__}: {str(ex)[:300]}"; s["updated_at"] = int(time.time())
            _save(data_dir, s)
    t = _threads[k] = threading.Thread(target=run_, daemon=True)
    t.start()
    return True


def pause(data_dir):
    _stop[os.path.abspath(data_dir)] = True


def watchdog_tick(data_dir):
    """الحارس: فحصٌ حاله في الملف «جارٍ» بلا خيطٍ حيّ (أُعيد تشغيل الخادم أثناءه) يُستأنف وحده ← هل استُؤنف؟
    الموقوف مؤقتًا بيد المدير (paused) والمكتمل والخاطئ لا يُمسّان."""
    k = os.path.abspath(data_dir)
    t = _threads.get(k)
    if t and t.is_alive():
        return False
    s = load(data_dir)
    if not s or s.get("status") not in ("running", "waiting"):
        return False
    return start(data_dir, resume=True)


def start_watchdog(data_dir):
    """خيط الحارس (من الخادم عند الإقلاع): يستأنف الفحص الجاري بعد أي إعادة تشغيل، نشرًا كان أو سقوطًا — ولو كان المدير بعيدًا."""
    def loop():
        time.sleep(15)                          # بعد إقلاع الخادم بقليل
        while True:
            try:
                watchdog_tick(data_dir)
            except Exception:  # noqa: BLE001 — الحارس لا يسقط
                pass
            time.sleep(WATCHDOG_EVERY)
    threading.Thread(target=loop, daemon=True, name="seo-scan-watchdog").start()


def state(data_dir):
    k = os.path.abspath(data_dir)
    s = load(data_dir)
    con = seo_db.connect(data_dir, create=False)
    try:
        st = seo_db.settings(con) if con else {}
    finally:
        if con:
            con.close()
    return {"running": bool(_threads.get(k) and _threads[k].is_alive()), "auto_resume": True, "watchdog_every": WATCHDOG_EVERY,
            "quiet_hours": quiet_label(st), "in_quiet_hours": in_quiet_hours(st), **summary(s)}


def main(argv):
    data_dir = os.environ.get("XM_DATA") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    cmd = argv[1] if len(argv) > 1 else "state"
    if cmd == "run":
        s = run(data_dir, progress=lambda s: print(f"{s['tested_entities']}/{s['entities_total']} · failures {s['failures']}", file=sys.stderr))
        print(json.dumps(summary(s), ensure_ascii=False, indent=1))
    elif cmd == "reset":
        try:
            os.remove(path_(data_dir)); print("reset")
        except OSError:
            print("nothing to reset")
    else:
        print(json.dumps(state(data_dir), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv)

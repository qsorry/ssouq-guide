# -*- coding: utf-8 -*-
"""«دليل الأهل»: ما في العمل مما لا يناسب الصغار — شدّة كل فئةٍ (عنف · مشاهد جنسية · ألفاظ · مخدرات · مخيف) ومشاهد بأوقاتها.

معلوماتيٌّ يُقرأ في صفحة العمل قبل المشاهدة؛ لا مشغّل ولا تخطٍّ آلي. تُحفظ في جدولين من القاعدة (لا يمسّهما البناء):
  content_guide      — صفٌّ لكل عمل: شدّة الفئات (0 لا شيء · 1 خفيف · 2 متوسط · 3 شديد · NULL غير مُقيَّم)، وعمرٌ يدوي اختياري، وخلاصة نصية.
  content_scene_flag — مشهدٌ يُنصح بتجنّبه: موسم/حلقة، بداية ونهاية بالثواني (اختياريان)، فئة، شدّة، وصف، ونسخة العمل التي تنطبق عليها الأوقات.

قواعد النشر (لا استثناء):
  · **المشهد بوقته لا يظهر إلا بعد مراجعةٍ بشرية** (status='approved')؛ وبلاغ الزائر يدخل pending ويراجعه المدير.
  · **الخلاصة العمرية** تُشتقّ من أعلى شدّة، وتُعرض مع مصدرها («مستورد من IMDb — لم يُراجَع» / «راجعه الفريق»)، وللمدير أن يفرض عمرًا يدويًا.
  · **عملٌ بلا بيانات** يُكتب «لا يوجد دليل بعد» — لا «آمن» أبدًا. وفلتر العائلة في «ويش ودك تشاهد» يستبعد غير المُصنَّف افتراضًا.
  · الأوقات تقديرية وتختلف بين نسخ العمل (مدبلج/مترجم/كامل)، وتُكتب كذلك."""
import html
import re
import threading
import time

import seo_db

CATS = ("violence", "sex", "profanity", "drugs", "frightening")
CAT_NAMES = {"violence": ("عنف ودم", "Violence & gore"), "sex": ("مشاهد جنسية وعري", "Sex & nudity"), "profanity": ("ألفاظ نابية", "Profanity"),
             "drugs": ("كحول ومخدرات", "Alcohol & drugs"), "frightening": ("مشاهد مخيفة", "Frightening scenes")}
SEV_NAMES = {0: ("لا يوجد", "None"), 1: ("خفيف", "Mild"), 2: ("متوسط", "Moderate"), 3: ("شديد", "Severe")}
AGES = (6, 10, 13, 16, 18)
AGE_NAMES = {6: ("للأطفال", "Kids"), 10: ("عائلي", "Family"), 13: ("بإشراف عائلي", "Parental guidance"), 16: ("للكبار فقط", "Teens & adults"), 18: ("للبالغين فقط", "Adults only")}
SOURCES = {"imdb": ("IMDb", "IMDb"), "manual": ("الفريق", "our team"), "import": ("مستورد", "imported")}
STATUS = ("pending", "approved", "rejected")
MAX_PENDING_PER_TITLE, MAX_PENDING_TOTAL, NOTE_MAX, SCENE_MAX_S = 20, 3000, 300, 86400
REPORT_PER_HOUR = 6
_rate = {}
_lock = threading.Lock()


# ================= المنطق =================
def derive_age(sev):
    """شدّة الفئات {cat: 0..3|None} ← (العمر|None، جزئي؟). أعلى شدّة تحكم؛ وللجنس سقفٌ أعلى (متوسط ← 16، شديد ← 18). بلا أي فئةٍ مُقيَّمة ← None."""
    known = {c: v for c, v in sev.items() if c in CATS and v is not None}
    if not known:
        return None, False
    base = {0: 6, 1: 10, 2: 13, 3: 16}
    age = max(base[min(3, max(0, int(v)))] for v in known.values())
    sx = known.get("sex")
    if sx is not None:
        age = max(age, 18 if sx >= 3 else 16 if sx == 2 else 0)
    return age, len(known) < len(CATS)


def fmt_time(s):
    s = max(0, int(s))
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def parse_time(v):
    """‏«12:34» · «1:02:03» · 754 ← ثوانٍ، أو None إن كان فارغًا؛ ‏ValueError لغير الصالح."""
    if v is None or str(v).strip() == "":
        return None
    t = str(v).strip()
    if t.isdigit():
        n = int(t)
    else:
        m = re.fullmatch(r"(?:(\d{1,2}):)?(\d{1,3}):([0-5]?\d)", t)
        if not m:
            raise ValueError("وقتٌ غير صالح (اكتبه mm:ss)")
        n = int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    if not 0 <= n <= SCENE_MAX_S:
        raise ValueError("وقتٌ خارج المدى")
    return n


def _sev(v):
    if v is None or v == "":
        return None
    n = int(v)
    if not 0 <= n <= 3:
        raise ValueError("الشدّة بين 0 و3")
    return n


def guide_row(con, cid):
    r = con.execute("SELECT * FROM content_guide WHERE content_id=?", (int(cid),)).fetchone()
    if not r:
        return None
    sev = {c: r[c] for c in CATS}
    d_age, partial = derive_age(sev)
    return {"sev": sev, "age": r["age"] or d_age, "age_manual": bool(r["age"]), "partial": partial and not r["age"], "summary_ar": r["summary_ar"] or "", "summary_en": r["summary_en"] or "",
            "source": r["source"], "reviewed": bool(r["reviewed"]), "updated_at": r["updated_at"]}


def scenes(con, cid, status="approved"):
    return [dict(r) for r in con.execute("SELECT * FROM content_scene_flag WHERE content_id=? AND status=? ORDER BY COALESCE(season,0), COALESCE(episode,0), COALESCE(start_s,0), id", (int(cid), status))]


def allowed(con, ids, age, unrated=False):
    """أي الأعمال يناسب عمر المشاهد (age ∈ AGES)؟ ← مجموعة المعرّفات. غير المُصنَّف مستبعدٌ ما لم يُطلب (unrated)."""
    ids = list(ids)
    if not ids or age not in AGES:
        return set(ids)
    ok = set()
    seen = set()
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        for r in con.execute(f"SELECT * FROM content_guide WHERE content_id IN ({','.join('?' * len(part))})", part):
            seen.add(r["content_id"])
            a = r["age"] or derive_age({c: r[c] for c in CATS})[0]
            if a is None:
                if unrated:
                    ok.add(r["content_id"])
            elif a <= age:
                ok.add(r["content_id"])
    if unrated:
        ok |= set(ids) - seen
    return ok


def ages_of(con, ids):
    out = {}
    ids = list(ids)
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        for r in con.execute(f"SELECT * FROM content_guide WHERE content_id IN ({','.join('?' * len(part))})", part):
            out[r["content_id"]] = r["age"] or derive_age({c: r[c] for c in CATS})[0]
    return out


def label(age, tr):
    return f"{age}+ · {tr(*AGE_NAMES[age])}" if age in AGE_NAMES else ""


# ================= الكتابة (المدير) =================
def set_guide(con, cid, fields, now=None):
    """يحفظ دليل عمل. الحقول: violence/sex/profanity/drugs/frightening (0..3 أو فارغ) · age (من AGES أو فارغ) · summary_ar/en · source · reviewed."""
    now = int(now or time.time())
    if not con.execute("SELECT 1 FROM content WHERE id=?", (int(cid),)).fetchone():
        raise ValueError("لا كيان بهذا المعرّف")
    cur = con.execute("SELECT * FROM content_guide WHERE content_id=?", (int(cid),)).fetchone()
    v = {c: (cur[c] if cur else None) for c in CATS}
    v.update({"age": cur["age"] if cur else None, "summary_ar": cur["summary_ar"] if cur else None, "summary_en": cur["summary_en"] if cur else None,
              "source": cur["source"] if cur else "manual", "reviewed": cur["reviewed"] if cur else 0})
    for c in CATS:
        if c in fields:
            v[c] = _sev(fields[c])
    if "age" in fields:
        a = fields["age"]
        v["age"] = None if a in (None, "", 0) else int(a)
        if v["age"] is not None and v["age"] not in AGES:
            raise ValueError("عمرٌ غير مسموح")
    for k in ("summary_ar", "summary_en"):
        if k in fields:
            v[k] = str(fields[k] or "").strip()[:1200] or None
    if "source" in fields:
        if fields["source"] not in SOURCES:
            raise ValueError("مصدرٌ غير معروف")
        v["source"] = fields["source"]
    if "reviewed" in fields:
        v["reviewed"] = 1 if fields["reviewed"] else 0
    con.execute("INSERT INTO content_guide(content_id, violence, sex, profanity, drugs, frightening, age, summary_ar, summary_en, source, reviewed, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(content_id) DO UPDATE SET violence=excluded.violence, sex=excluded.sex, profanity=excluded.profanity, drugs=excluded.drugs, frightening=excluded.frightening, "
                "age=excluded.age, summary_ar=excluded.summary_ar, summary_en=excluded.summary_en, source=excluded.source, reviewed=excluded.reviewed, updated_at=excluded.updated_at",
                (int(cid), v["violence"], v["sex"], v["profanity"], v["drugs"], v["frightening"], v["age"], v["summary_ar"], v["summary_en"], v["source"], v["reviewed"], now))


def _scene_fields(f):
    cat = str(f.get("category") or "")
    if cat not in CATS:
        raise ValueError("فئةٌ غير معروفة")
    sev = int(f.get("severity") or 2)
    if not 1 <= sev <= 3:
        raise ValueError("شدّة المشهد 1 إلى 3")
    st, en = parse_time(f.get("start")), parse_time(f.get("end"))
    if (st is None) != (en is None):
        raise ValueError("اكتب البداية والنهاية معًا")
    if st is not None and en is not None and en <= st:
        raise ValueError("النهاية بعد البداية")
    season = int(f["season"]) if str(f.get("season") or "").strip() else None
    episode = int(f["episode"]) if str(f.get("episode") or "").strip() else None
    for n in (season, episode):
        if n is not None and not 0 <= n <= 5000:
            raise ValueError("رقمٌ غير صالح")
    return {"category": cat, "severity": sev, "start_s": st, "end_s": en, "season": season, "episode": episode,
            "note_ar": (str(f.get("note_ar") or "").strip()[:NOTE_MAX] or None), "note_en": (str(f.get("note_en") or "").strip()[:NOTE_MAX] or None),
            "version": (str(f.get("version") or "").strip()[:60] or None)}


def add_scene(con, cid, f, source="manual", status="approved", now=None):
    now = int(now or time.time())
    if not con.execute("SELECT 1 FROM content WHERE id=?", (int(cid),)).fetchone():
        raise ValueError("لا كيان بهذا المعرّف")
    s = _scene_fields(f)
    if status not in STATUS or source not in ("manual", "report"):
        raise ValueError("حالة غير صالحة")
    cur = con.execute("INSERT INTO content_scene_flag(content_id, season, episode, start_s, end_s, category, severity, note_ar, note_en, version, source, status, created_at, updated_at) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (int(cid), s["season"], s["episode"], s["start_s"], s["end_s"], s["category"], s["severity"], s["note_ar"], s["note_en"],
                                                                s["version"], source, status, now, now))
    return cur.lastrowid


def edit_scene(con, sid, f, now=None):
    r = con.execute("SELECT 1 FROM content_scene_flag WHERE id=?", (int(sid),)).fetchone()
    if not r:
        raise ValueError("لا مشهد بهذا المعرّف")
    s = _scene_fields(f)
    con.execute("UPDATE content_scene_flag SET season=?, episode=?, start_s=?, end_s=?, category=?, severity=?, note_ar=?, note_en=?, version=?, updated_at=? WHERE id=?",
                (s["season"], s["episode"], s["start_s"], s["end_s"], s["category"], s["severity"], s["note_ar"], s["note_en"], s["version"], int(now or time.time()), int(sid)))


def set_status(con, sid, status, now=None):
    if status not in STATUS:
        raise ValueError("حالة غير صالحة")
    if con.execute("UPDATE content_scene_flag SET status=?, updated_at=? WHERE id=?", (status, int(now or time.time()), int(sid))).rowcount != 1:
        raise ValueError("لا مشهد بهذا المعرّف")


def delete_scene(con, sid):
    con.execute("DELETE FROM content_scene_flag WHERE id=?", (int(sid),))


def pending(con, limit=100):
    rows = con.execute("SELECT f.*, c.slug, c.type, COALESCE(c.title_ar, c.title) title FROM content_scene_flag f JOIN content c ON c.id=f.content_id "
                       "WHERE f.status='pending' ORDER BY f.created_at LIMIT ?", (int(limit),)).fetchall()
    return [dict(r) for r in rows]


def import_rows(con, rows, now=None):
    """استيراد دليلٍ جماعي (مثلًا من ترخيص IMDb): [{tmdb_id | slug, violence, sex, profanity, drugs, frightening, summary_ar, summary_en, source}] ← (استُورد، تُخطّي).
    لا يكتب فوق دليلٍ راجعه الفريق (reviewed=1)."""
    done = skipped = 0
    for it in rows or []:
        if not isinstance(it, dict):
            skipped += 1
            continue
        r = None
        if it.get("slug"):
            r = con.execute("SELECT id FROM content WHERE slug=? AND merged_into IS NULL", (str(it["slug"]),)).fetchone()
        elif it.get("tmdb_id"):
            r = con.execute("SELECT id FROM content WHERE tmdb_id=? AND merged_into IS NULL", (int(it["tmdb_id"]),)).fetchone()
        if not r:
            skipped += 1
            continue
        cur = con.execute("SELECT reviewed FROM content_guide WHERE content_id=?", (r["id"],)).fetchone()
        if cur and cur["reviewed"]:
            skipped += 1
            continue
        f = {k: it[k] for k in (*CATS, "summary_ar", "summary_en") if k in it}
        f["source"] = it.get("source") if it.get("source") in SOURCES else "import"
        f["reviewed"] = 0
        try:
            set_guide(con, r["id"], f, now)
            done += 1
        except (ValueError, TypeError):
            skipped += 1
    return done, skipped


# ================= البلاغ العام =================
def rate_ok(ip, limit=REPORT_PER_HOUR):
    now = time.time()
    with _lock:
        hits = [t for t in _rate.get(ip, []) if now - t < 3600]
        if len(hits) >= limit:
            _rate[ip] = hits
            return False
        hits.append(now)
        _rate[ip] = hits
        if len(_rate) > 5000:
            for k in [k for k, v in _rate.items() if not v or now - v[-1] > 3600]:
                _rate.pop(k, None)
        return True


def report(data_dir, slug, f, now=None):
    """بلاغ زائرٍ عن مشهد ← 'ok' | 'not_found' | 'invalid:…' | 'full'. يدخل pending ولا يظهر قبل مراجعة المدير."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,100}", slug or ""):
        return "not_found"
    con = seo_db.connect(data_dir, create=False)
    if con is None:
        return "not_found"
    try:
        row = con.execute("SELECT id FROM content WHERE slug=? AND merged_into IS NULL", (slug,)).fetchone()
        if not row:
            return "not_found"
        try:
            _scene_fields(f)
        except (ValueError, TypeError) as e:
            return f"invalid:{e}"
        if con.execute("SELECT COUNT(*) FROM content_scene_flag WHERE status='pending'").fetchone()[0] >= MAX_PENDING_TOTAL or \
                con.execute("SELECT COUNT(*) FROM content_scene_flag WHERE status='pending' AND content_id=?", (row["id"],)).fetchone()[0] >= MAX_PENDING_PER_TITLE:
            return "full"
        with con:
            add_scene(con, row["id"], {**f, "note_en": None}, source="report", status="pending", now=now)
        return "ok"
    finally:
        con.close()


# ================= العرض =================
def _dots(n):
    return "●" * n + "○" * (4 - n) if n else "○○○○"


def section(con, cid, slug, typ, tr):
    """قسم «دليل الأهل» في صفحة العمل ← (html، contentRating|None). بلا دليلٍ يُكتب «لا يوجد دليل بعد»، وبلا ادّعاء أمان."""
    e = html.escape
    g = guide_row(con, cid)
    out = [f'<section class="guide" id="parents-guide"><h2>{e(tr("دليل الأهل", "Parents guide"))}</h2>']
    rating = None
    if not g or all(v is None for v in g["sev"].values()) and not g["age"]:
        out.append(f'<p class="g-none">{e(tr("لا يوجد دليل لهذا العمل بعد. غيابه لا يعني خلوّ العمل من مشاهد لا تناسب الصغار.", "No guide for this title yet. Its absence does not mean the title has no scenes unsuitable for children."))}</p>')
    else:
        age = g["age"]
        if age:
            rating = f"{age}+"
            src = tr(*SOURCES.get(g["source"], SOURCES["import"]))
            note = tr(f"راجعه الفريق · المصدر: {src}", f"Reviewed by our team · source: {src}") if g["reviewed"] else tr(f"المصدر: {src} — لم يُراجَع بعد", f"Source: {src} — not reviewed yet")
            out.append(f'<p class="g-sum"><b class="g-age">{age}+</b> {e(tr(*AGE_NAMES[age]))}'
                       f'{e(" · " + tr("مبنيٌّ على بعض الفئات فقط", "based on some categories only")) if g["partial"] else ""} <small>{e(note)}</small></p>')
        out.append('<ul class="g-cats">')
        for c in CATS:
            v = g["sev"][c]
            nm = tr(*CAT_NAMES[c])
            if v is None:
                out.append(f'<li><span>{e(nm)}</span><span class="dots" aria-hidden="true">····</span><em>{e(tr("غير مُقيَّم", "Not rated"))}</em></li>')
            else:
                out.append(f'<li><span>{e(nm)}</span><span class="dots" aria-hidden="true">{_dots(v)}</span><em>{e(tr(*SEV_NAMES[v]))}</em></li>')
        out.append("</ul>")
        txt = g["summary_en"] if tr.en else g["summary_ar"]
        if txt:
            out.append(f'<p class="g-text" dir="auto">{e(txt)}</p>')
    sc = scenes(con, cid)
    if sc:
        out.append(f'<h3>{e(tr("مشاهد يُنصح بتجنبها", "Scenes to skip"))}</h3><p class="meta">{e(tr("الأوقات تقريبية وتختلف بين نسخ العمل (مدبلج · مترجم · كامل).", "Times are approximate and differ between versions (dubbed · subtitled · full)."))}</p><ul class="g-scenes">')
        for s in sc:
            where = []
            if typ == "series" and s["season"]:
                where.append(tr(f"الموسم {s['season']}", f"Season {s['season']}"))
            if s["episode"]:
                where.append(tr(f"الحلقة {s['episode']}", f"Episode {s['episode']}"))
            when = f'{fmt_time(s["start_s"])} – {fmt_time(s["end_s"])}' if s["start_s"] is not None and s["end_s"] is not None else ""
            note = (s["note_en"] if tr.en else s["note_ar"]) or ""
            bits = [f'<b>{e(" · ".join(where))}</b>' if where else "", f'<time dir="ltr">{e(when)}</time>' if when else "",
                    f'<i>{e(tr(*CAT_NAMES[s["category"]]))} · {e(tr(*SEV_NAMES[s["severity"]]))}</i>', e(note), f'<small>{e(s["version"])}</small>' if s["version"] else ""]
            out.append("<li>" + " ".join(b for b in bits if b) + "</li>")
        out.append("</ul>")
    opts = "".join(f'<option value="{c}">{e(tr(*CAT_NAMES[c]))}</option>' for c in CATS)
    out.append(
        f'<details class="g-report"><summary>{e(tr("أبلغ عن مشهد غير مذكور", "Report a scene"))}</summary>'
        f'<form id="gForm" data-slug="{e(slug)}"><select name="category" aria-label="{e(tr("الفئة", "Category"))}">{opts}</select>'
        f'<select name="severity" aria-label="{e(tr("الشدّة", "Severity"))}"><option value="1">{e(tr(*SEV_NAMES[1]))}</option><option value="2" selected>{e(tr(*SEV_NAMES[2]))}</option><option value="3">{e(tr(*SEV_NAMES[3]))}</option></select>'
        + (f'<input name="season" inputmode="numeric" placeholder="{e(tr("الموسم", "Season"))}"><input name="episode" inputmode="numeric" placeholder="{e(tr("الحلقة", "Episode"))}">' if typ == "series" else "")
        + f'<input name="start" dir="ltr" placeholder="{e(tr("من 12:34", "From 12:34"))}"><input name="end" dir="ltr" placeholder="{e(tr("إلى 12:50", "To 12:50"))}">'
        f'<input name="version" placeholder="{e(tr("النسخة (مدبلج/مترجم)", "Version (dubbed/subtitled)"))}"><textarea name="note_ar" maxlength="{NOTE_MAX}" rows="2" placeholder="{e(tr("وصف مختصر بلا حرق للأحداث", "Short description, no spoilers"))}"></textarea>'
        f'<button type="submit">{e(tr("إرسال", "Send"))}</button><span class="g-msg" role="status"></span></form></details>'
        '<script>(function(){var f=document.getElementById("gForm");if(!f)return;f.addEventListener("submit",function(ev){ev.preventDefault();var m=f.querySelector(".g-msg"),b={slug:f.dataset.slug};'
        'Array.prototype.forEach.call(f.elements,function(x){if(x.name)b[x.name]=x.value});'
        'fetch("/api/content/guide-report",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b)}).then(function(r){return r.json()}).then(function(d){'
        f'm.textContent=d.ok?{_js(tr("شكرًا، سيُراجَع بلاغك قبل النشر.", "Thanks — your report will be reviewed before publishing."))}:(d.error||{_js(tr("تعذّر الإرسال", "Could not send"))});if(d.ok)f.reset()'
        f'}}).catch(function(){{m.textContent={_js(tr("تعذّر الإرسال", "Could not send"))}}})}})}})()</script></section>')
    return "".join(out), rating


def _js(s):
    import json
    return json.dumps(s, ensure_ascii=False).replace("</", "<\\/")


# ================= واجهة الإدارة =================
def admin(data_dir, body):
    """إجراءات لوحة الإدارة (‏/api/content/admin/seo-guide). كل كتابةٍ معاملةٌ تُرجَع عند الخطأ.
    get {id} · set {id, fields} · scene_add {id, scene} · scene_edit {scene_id, scene} · scene_status {scene_id, status} · scene_delete {scene_id} · pending {} · import {rows}"""
    act = str(body.get("action") or "")
    con = seo_db.connect(data_dir)
    try:
        def one(cid):
            r = con.execute("SELECT id, slug, type, COALESCE(title_ar, title) title, year FROM content WHERE id=?", (int(cid),)).fetchone()
            if not r:
                raise ValueError("لا كيان بهذا المعرّف")
            return {"entity": {"id": r["id"], "slug": r["slug"], "type": r["type"], "title": r["title"], "year": r["year"]}, "guide": guide_row(con, cid),
                    "scenes": [dict(x) for x in con.execute("SELECT * FROM content_scene_flag WHERE content_id=? AND status!='rejected' ORDER BY COALESCE(season,0), COALESCE(episode,0), COALESCE(start_s,0), id", (int(cid),))]}
        if act == "get":
            return {"ok": True, **one(body.get("id"))}
        if act == "pending":
            return {"ok": True, "pending": pending(con), "total": con.execute("SELECT COUNT(*) FROM content_scene_flag WHERE status='pending'").fetchone()[0]}
        with con:
            if act == "set":
                set_guide(con, body.get("id"), body.get("fields") or {})
                cid = body.get("id")
            elif act == "scene_add":
                add_scene(con, body.get("id"), body.get("scene") or {}, "manual", "approved")
                cid = body.get("id")
            elif act in ("scene_edit", "scene_status", "scene_delete"):
                r = con.execute("SELECT content_id FROM content_scene_flag WHERE id=?", (int(body.get("scene_id") or 0),)).fetchone()
                if not r:
                    raise ValueError("لا مشهد بهذا المعرّف")
                cid = r["content_id"]
                if act == "scene_edit":
                    edit_scene(con, body.get("scene_id"), body.get("scene") or {})
                elif act == "scene_status":
                    set_status(con, body.get("scene_id"), str(body.get("status") or ""))
                else:
                    delete_scene(con, body.get("scene_id"))
            elif act == "import":
                done, skipped = import_rows(con, body.get("rows") or [])
                return {"ok": True, "imported": done, "skipped": skipped}
            else:
                raise ValueError("إجراء غير معروف")
        return {"ok": True, **one(cid)}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

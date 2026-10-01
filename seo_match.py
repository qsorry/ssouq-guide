# -*- coding: utf-8 -*-
"""مطابقة المحتوى بين السيرفرات — محافظةً: الاسم وحده لا يدمج.

العنصر نفسه (فيلمٌ أو مسلسل) في كاسبر وفالكون وسمارت يصير كيانًا واحدًا إذا اجتمعت قرائن كافية
(‏pair_score): نفس السنة، أو نفس ملف ملصق TMDB، أو قصّةٌ واحدة، أو تصنيفٌ مشترك — بعتباتٍ من ‏seo_settings.
ومَن اتفق اسمه وحده بلا قرينة يُترك عنصرين وبندَ مراجعة (‏name_only)، ومَن تعارضت سنته أو قصّته كذلك (‏conflict).
ترتيب المطابقة في المراحل كلها: ‏tmdb_id ← معرّفٌ موثوق ← الاسم الأصلي + السنة + النوع ← النص آخرًا.

بلا مكتبات خارجية.
"""
import re
import unicodedata

import content as C

_TMDB_FILE = re.compile(r"^https?://image\.tmdb\.org/t/p/[^/]+/([^/?#]+)$")
_WORD = re.compile(r"\w+", re.U)
_SLUG_BAD = re.compile(r"[^\w]+", re.U)
_LATIN = re.compile(r"[A-Za-z]")
SLUG_MAX = 80

norm = C._norm


# ================= slug =================
# الرابط لاتينيٌّ دائمًا (‏/content/series/breaking-bad/)، صغير الحروف، بلا رموز، ولا يتغيّر مع تحديث البيانات:
# يُولَّد مرةً عند إنشاء الكيان من (1) الاسم الإنجليزي (2) الاسم الأصلي (3) نقحرةٍ للعربي عند الحاجة — ومصدره في
# ‏content.slug_source؛ فإذا جاء لاحقًا مصدرٌ أعلى (اسمٌ إنجليزي من TMDB لكيانٍ نُقحر اسمه) بُدِّل عبر ‏seo_db.change_slug
# الذي يسجّل الرابط القديم في ‏redirect (301). والأسماء العربية كلها ‏aliases وبيانات عرض، لا روابط.
_AR_MAP = {"ا": "a", "أ": "a", "إ": "i", "آ": "a", "ٱ": "a", "ب": "b", "ت": "t", "ث": "th", "ج": "j", "ح": "h", "خ": "kh",
           "د": "d", "ذ": "dh", "ر": "r", "ز": "z", "س": "s", "ش": "sh", "ص": "s", "ض": "d", "ط": "t", "ظ": "z", "ع": "a",
           "غ": "gh", "ف": "f", "ق": "q", "ك": "k", "ل": "l", "م": "m", "ن": "n", "ه": "h", "و": "w", "ي": "y", "ى": "a",
           "ة": "a", "ء": "", "ؤ": "w", "ئ": "y", "ﻻ": "la", "پ": "p", "چ": "ch", "ڤ": "v", "گ": "g", "ک": "k", "ی": "y"}
_AR_WORD = re.compile(r"[\u0600-\u06ff]+")


def translit(s):
    """نقحرة عربية بسيطة وثابتة (بلا حركات، فتقريبية): «المؤسس عثمان» ← almwss athman — للرابط حين لا اسم لاتيني."""
    s = C._TASHKEEL.sub("", unicodedata.normalize("NFKC", s or ""))

    def word(m):
        w = m.group(0)
        out = "al" + "".join(_AR_MAP.get(ch, "") for ch in w[2:]) if w.startswith("ال") and len(w) > 3 \
            else "".join(_AR_MAP.get(ch, "") for ch in w)
        return out
    return _AR_WORD.sub(word, s)


def slugify(title, year=0):
    """‏«Wonder Woman (2017)» ← wonder-woman؛ «Amélie» ← amelie؛ وما ليس لاتينيًّا يُنقحر. ‏year يُلحق عند التعارض وحده."""
    s = unicodedata.normalize("NFKC", title or "").translate(C._DIG)
    s = translit(s)
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    s = s.encode("ascii", "ignore").decode().casefold()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    s = re.sub(r"-{2,}", "-", s)[:SLUG_MAX].strip("-")
    if year:
        s = f"{s}-{year}" if s else str(year)
    return s or "item"


def slug_source(fields):
    """أيّ اسمٍ يصنع الرابط ← (الاسم، المصدر): الإنجليزي، فالأصلي، فالاسم المعروض إن كان لاتينيًّا، وإلا نقحرته."""
    for f, src in (("title_en", "en"), ("original_title", "original")):
        if fields.get(f) and _LATIN.search(fields[f]):
            return fields[f], src
    t = fields.get("title") or ""
    return (t, "original") if _LATIN.search(t) else (t, "translit")


def unique_slug(exists, title, year=0):
    """أول صيغةٍ غير مستعملة: الاسم، ثم الاسم-السنة، ثم الاسم-السنة-2…"""
    base = slugify(title)
    for cand in (base, slugify(title, year) if year else ""):
        if cand and not exists(cand):
            return cand
    stem = slugify(title, year) if year else base
    n = 2
    while exists(f"{stem}-{n}"):
        n += 1
    return f"{stem}-{n}"


# ================= القرائن =================
def poster_file(url):
    """ملف ملصق TMDB من رابطه (هويةٌ تكاد تكون قاطعة)، أو ‏"" لصورةٍ من لوحة السيرفر (لا تُقارن بين السيرفرات)."""
    m = _TMDB_FILE.match(url or "")
    return m.group(1) if m else ""


def plot_words(s):
    return {w for w in _WORD.findall(norm(s)) if len(w) >= 3}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


DISTINCT = -1 << 20       # عنصران مختلفان يقينًا (سنتان مختلفتان: «Dune 1984» و«Dune 2021») — لا دمج ولا مراجعة


def pair_score(a, b, st, same_server=False):
    """قرائن أن العنصرين (بنفس النوع) واحد ← (المجموع، [الأسباب]): ‏None عند تعارضٍ يُراجَع، و‏DISTINCT لمختلفين يقينًا.
    ‏same_server: عنصران في سيرفرٍ واحد (قسمان) — صورة اللوحة نفسها تُقارن، والقصة والتصنيف لا (الواجهة تعطيهما بالاسم)."""
    score, why = 0, []
    if a.get("type") != b.get("type"):
        return DISTINCT, ["type_differs"]
    ta, tb = a.get("tmdb_id") or 0, b.get("tmdb_id") or 0
    if ta and tb:
        if ta != tb:
            return DISTINCT, ["tmdb_differs"]
        score += st["score_tmdb"]
        why.append("tmdb")
    ya, yb = a.get("year") or 0, b.get("year") or 0
    pa, pb = poster_file(a.get("poster")), poster_file(b.get("poster"))
    if same_server and not (pa and pb):            # في السيرفر نفسه رابط صورة اللوحة يُقارن حرفيًّا
        pa = pb = ""
        if a.get("poster") and a.get("poster") == b.get("poster"):
            pa = pb = a["poster"]
    same_poster = bool(pa and pb and pa == pb)
    if ya and yb:
        if ya != yb:
            return (None, ["year_differs", "poster"]) if same_poster and not same_server else (DISTINCT, ["year_differs"])
        score += st["score_year"]
        why.append("year")
    if same_poster:
        score += st["score_poster"]
        why.append("poster")
    if same_server:
        sa, sb = a.get("seasons") or {}, b.get("seasons") or {}
        if sa and sb and any(sa.get(k) == v for k, v in sb.items()):   # موسمٌ بعدد حلقاته نفسه في القسمين
            score += st["score_seasons"]
            why.append("seasons")
        return score, why
    da, db = a.get("plot") or "", b.get("plot") or ""
    if len(da) >= st["plot_min"] and len(db) >= st["plot_min"]:
        j = jaccard(plot_words(da), plot_words(db))
        if j >= st["plot_same"]:
            score += st["score_plot"]
            why.append("plot")
        elif j <= st["plot_diff"]:
            why.append("plot_differs")
            if not pa or pa != pb:           # قصّتان مختلفتان بلا ملصقٍ واحد: تعارض
                return None, why
    ga, gb = {norm(x) for x in a.get("genres") or ()}, {norm(x) for x in b.get("genres") or ()}
    if ga and gb and ga & gb:
        score += st["score_genre"]
        why.append("genre")
    return score, why


def bucket_key(item):
    return item["type"], norm(item["name"])


def cluster_in_server(entries, st):
    """مداخل سيرفرٍ واحد بنفس النوع والاسم المطبَّع (من أقسامٍ شتّى) ← (عناقيد الفهارس، أغامض؟). الصورة نفسها أو السنة
    نفسها أو موسمٌ بعدد حلقاته تجمع؛ وسنتان مختلفتان تفرّقان يقينًا؛ وبلا قرينة: عنصران ومراجعة."""
    uf, ambiguous = _UF(len(entries)), False
    for x in range(len(entries)):
        for y in range(x + 1, len(entries)):
            score, _ = pair_score(entries[x], entries[y], st, same_server=True)
            if score is not None and score != DISTINCT and score >= st["merge_min"]:
                uf.union(x, y)
    groups = {}
    for i in range(len(entries)):
        groups.setdefault(uf.find(i), []).append(i)
    out = list(groups.values())
    if len(out) > 1:
        for g1 in range(len(out)):
            for g2 in range(g1 + 1, len(out)):
                score, _ = pair_score(entries[out[g1][0]], entries[out[g2][0]], st, same_server=True)
                if score != DISTINCT:
                    ambiguous = True
    return out, ambiguous


def verify_tmdb(cand, entity, st):
    """هل سجلّ TMDB (‏type · title · original_title · year · aliases) هو هذا الكيان؟ معرّفٌ من لوحةٍ خارجية لا يُعتمد
    وحده: النوع واحد، والسنة ضمن ‏tmdb_year_tolerance، واسمٌ من أسماء الكيان يطابق عنوان TMDB أو أصله أو بدائله."""
    v = st.get("tmdb_verify") or {}
    if v.get("type", True) and cand.get("type") != entity.get("type"):
        return False, "type"
    cy, ey = cand.get("year") or 0, entity.get("year") or 0
    if v.get("year", True) and cy and ey and abs(cy - ey) > int(v.get("year_tolerance", 1)):
        return False, "year"
    mine = {norm(x) for x in [entity.get("title"), entity.get("title_en"), entity.get("original_title")] + list(entity.get("aliases") or []) if x}
    theirs = {norm(x) for x in [cand.get("title"), cand.get("original_title")] + list(cand.get("aliases") or []) if x}
    if v.get("title", True) and not (mine & theirs):
        return False, "title"
    return True, "ok"


# ================= التجميع =================
class _UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, i):
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def union(self, i, j):
        self.p[self.find(i)] = self.find(j)


def cluster(items, st):
    """العناصر (قاموسٌ لكلٍّ: type · name · year · poster · plot · genres · service · local_key …) ← (العناقيد، المراجعات).
    العنقود قائمة فهارس عناصرٍ هي كيانٌ واحد؛ والمراجعة {kind, key, items:[فهارس], why}."""
    uf, reviews = _UF(len(items)), {}
    buckets, posters = {}, {}
    for i, it in enumerate(items):
        buckets.setdefault(bucket_key(it), []).append(i)
        pf = poster_file(it.get("poster"))
        if pf:                                # المعرّف الموثوق المتاح الآن: ملف ملصق TMDB — يجمع «Breaking Bad» و«بريكنغ باد»
            posters.setdefault((it["type"], pf), []).append(i)
        if it.get("tmdb_id"):                 # وtmdb_id حين يُعرف (بعد تحقّق ‏verify_tmdb)
            posters.setdefault((it["type"], "tmdb", it["tmdb_id"]), []).append(i)
    pairs_why = []
    for (typ, nm), idx in list(buckets.items()) + [(k, v) for k, v in posters.items() if len(v) > 1]:
        if len(idx) < 2:
            continue
        for x in range(len(idx)):
            for y in range(x + 1, len(idx)):
                i, j = idx[x], idx[y]
                if items[i]["service"] == items[j]["service"]:   # نفس السيرفر: فيلمان بسنتين — عنصران أصلًا
                    continue
                score, why = pair_score(items[i], items[j], st)
                if score is not None and score >= st["merge_min"]:
                    uf.union(i, j)
                elif score != DISTINCT:
                    pairs_why.append((typ, nm, i, j, score, why))
    # ما بقي منفصلًا بعد الدمج الاتّحادي يُراجَع: الاسم وحده، أو تعارض
    for typ, nm, i, j, score, why in pairs_why:
        if uf.find(i) == uf.find(j):
            continue                     # اتّصلا عبر ثالثٍ: لا مراجعة
        kind = "conflict" if score is None else "name_only"
        key = f"{kind}:{typ}:{nm}"
        r = reviews.setdefault(key, {"kind": kind, "key": key, "type": typ, "name": items[i]["name"],
                                     "items": [], "why": []})
        for k in (i, j):
            if k not in r["items"]:
                r["items"].append(k)
        for w in why:
            if w not in r["why"]:
                r["why"].append(w)
    groups = {}
    for i in range(len(items)):
        groups.setdefault(uf.find(i), []).append(i)
    return list(groups.values()), list(reviews.values())


# ================= اختيار قيم الكيان من أعضائه =================
def pick_title(members):
    """الاسم الأكثر تكرارًا بين السيرفرات، وعند التساوي الأطول (الأكمل)."""
    freq = {}
    for m in members:
        freq[m["name"]] = freq.get(m["name"], 0) + 1
    return sorted(freq.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))[0][0]


def pick(members, field, prefer=None):
    """أول قيمةٍ غير فارغة بترتيب ‏prefer (دالة ترتيب) أو ترتيب الأعضاء ← (القيمة، العضو)."""
    for m in sorted(members, key=prefer) if prefer else members:
        if m.get(field):
            return m[field], m
    return None, None

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
def slugify(title, year=0):
    """‏«Wonder Woman (2017)» ← wonder-woman؛ والعربي يبقى بحروفه (‏«المؤسس عثمان» ← المؤسس-عثمان). ‏year يُلحق
    عند التعارض وحده (‏unique_slug)."""
    s = unicodedata.normalize("NFKC", title or "")
    if _LATIN.search(s):                      # اللاتيني بلا علامات التشكيل الأوروبية: «Amélie» ← amelie
        s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    s = C._TASHKEEL.sub("", s.translate(C._DIG)).casefold()
    s = _SLUG_BAD.sub("-", s).strip("-_").replace("_", "-")
    s = re.sub(r"-{2,}", "-", s)[:SLUG_MAX].strip("-")
    if year:
        s = f"{s}-{year}" if s else str(year)
    return s or "item"


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


def pair_score(a, b, st):
    """قرائن أن العنصرين (بنفس النوع) واحد ← (المجموع، [الأسباب]): ‏None عند تعارضٍ يُراجَع، و‏DISTINCT لمختلفين يقينًا."""
    score, why = 0, []
    ya, yb = a.get("year") or 0, b.get("year") or 0
    pa, pb = poster_file(a.get("poster")), poster_file(b.get("poster"))
    same_poster = bool(pa and pb and pa == pb)
    if ya and yb:
        if ya != yb:
            return (None, ["year_differs", "poster"]) if same_poster else (DISTINCT, ["year_differs"])
        score += st["score_year"]
        why.append("year")
    if same_poster:
        score += st["score_poster"]
        why.append("poster")
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

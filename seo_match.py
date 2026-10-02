# -*- coding: utf-8 -*-
"""مطابقة المحتوى بين السيرفرات — محافظةً: الاسم وحده لا يدمج.

العنصر نفسه (فيلمٌ أو مسلسل) في كاسبر وفالكون وسمارت يصير كيانًا واحدًا إذا اجتمعت قرائن كافية
(‏pair_score): نفس السنة، أو نفس ملف ملصق TMDB، أو قصّةٌ واحدة، أو تصنيفٌ مشترك — بعتباتٍ من ‏seo_settings.
ومَن اتفق اسمه وحده بلا قرينة يُترك عنصرين وبندَ مراجعة (‏name_only)، ومَن تعارضت سنته أو قصّته كذلك (‏conflict).
ترتيب المطابقة في المراحل كلها: ‏tmdb_id ← معرّفٌ موثوق ← الاسم الأصلي + السنة + النوع ← النص آخرًا.

بلا مكتبات خارجية.
"""
import json
import re
import unicodedata

import content as C
from seo_search import norm, phonetic  # noqa: F401 — التطبيع (بلا فاصلة عليا) والمفتاح الصوتي

_TMDB_FILE = re.compile(r"^https?://image\.tmdb\.org/t/p/[^/]+/([^/?#]+)$")
_WORD = re.compile(r"\w+", re.U)
_SLUG_BAD = re.compile(r"[^\w]+", re.U)
_LATIN = re.compile(r"[A-Za-z]")
SLUG_MAX = 80


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


def sections_agree(a, b):
    """هل المدخلان من القسم نفسه في السيرفر، أو يحملان الاسم الأصلي اللاتيني نفسه؟ (العمل نفسه بمواسمه المفرّقة يبقى في قسمه؛
    «السجين S01» في «سورية» و«السجين S02 Mahkum» في «تركية» عملان)."""
    ga, gb = {norm(g) for g in a.get("groups") or ()}, {norm(g) for g in b.get("groups") or ()}
    if ga & gb:
        return True
    return bool(_originals(a) & _originals(b))


def person_key(name):
    """مفتاح توحيد الشخص بالاسم: التطبيع (بلا تشكيلٍ ولا فاصلة عليا ولا علامات) وكلماتٌ مرتّبة (ترتيب الاسم لا يفرّق).
    الاسم العربي والإنجليزي للشخص نفسه لا يجمعهما إلا معرّف TMDB (ترجماته) — لا تخمين."""
    return " ".join(sorted(norm(name).split()))


def _originals(e):
    return {norm(o) for o in (e.get("originals") or ([e["original"]] if e.get("original") else [])) if o}


def originals_conflict(a, b):
    """كلاهما يحمل اسمًا أصليًّا لاتينيًّا من القائمة ولا يشتركان في واحد."""
    oa, ob = _originals(a), _originals(b)
    return bool(oa and ob and not (oa & ob))


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
        if originals_conflict(a, b):                 # اسمان أصليان لاتينيان مختلفان («SOZ» و«Al-Ahd»): عملان بالاسم العربي نفسه
            why.append("original_differs")
            return (score if score >= st["merge_min"] else None), why   # لا نسخة ولا موسم يجمعانهما؛ بلا دليلٍ أقوى: مراجعة
        va, vb = a.get("versions") or [], b.get("versions") or []
        if (va or vb) and va != vb and norm(a.get("raw_name") or "") != norm(b.get("raw_name") or ""):
            score += st["score_version"]      # لا يختلفان إلا بلاحقة النسخة: العمل نفسه مدبلجًا ومترجمًا
            why.append("version")
        ta, tb = a.get("season_token") or 0, b.get("season_token") or 0
        if ta and tb and ta != tb:
            if sections_agree(a, b) or same_poster:   # مدخلان للعمل نفسه برمزَي موسمين: قوائم تفرّق المواسم — في القسم نفسه
                score += st.get("score_season_split", 2)   # (أو بالاسم الأصلي نفسه)؛ قسمان مختلفان («تركية» و«سورية») لا يجمعهما رمز الموسم
                why.append("season_split")
            else:
                why.append("season_split_sections_differ")
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


# ================= النسخ (مدبلج · مترجم · سوفت) =================
_version_cache = {}


def _version_table(st):
    """لواحق النسخ من الإعدادات ← (لاحقة مطبَّعة ← نسخة، أطول لاحقة بالكلمات)."""
    tags = st.get("version_tags") or {}
    key = json.dumps(tags, sort_keys=True, ensure_ascii=False)
    if key not in _version_cache:
        table = {norm(t): v for v, ts in tags.items() for t in ts if norm(t)}
        _version_cache[key] = (table, max((len(t.split()) for t in table), default=0))
    return _version_cache[key]


def split_version(name, st):
    """‏«طبيعة الحب مدبلج» ← («طبيعة الحب», ["dubbed"])؛ «السعادة العائلية مترجم سوفت» ← (…, ["subbed_soft"]).
    اللاحقة صفةٌ للنسخة لا جزءٌ من هوية العمل؛ تُحذف من آخر الاسم أو أوله (ويبقى منه كلمة على الأقل)."""
    table, maxlen = _version_table(st)
    words = name.split()
    nw = [norm(w) for w in words]
    found = []

    def strip(at_end):
        for n in range(min(maxlen, len(words) - 1), 0, -1):
            seg = " ".join(nw[-n:] if at_end else nw[:n])
            if seg in table and (at_end or _AR_WORD.search(seg)):   # اللاتينية في الآخر وحده («Sub Zero» فيلم)
                found.append(table[seg])
                if at_end:
                    del words[-n:], nw[-n:]
                else:
                    del words[:n], nw[:n]
                return True
        return False
    while len(words) > 1 and (strip(True) or strip(False)):
        pass
    if not found:
        return name, []
    out = []
    for v in found:
        if v not in out:
            out.append(v)
    if "subbed_soft" in out and "subbed" in out:
        out.remove("subbed")
    return " ".join(words), out


# ================= تنظيف اسم السيرفر: العمل ← الموسم ← النسخة ← الاسم الأصلي =================
_SEASON_TOKEN = re.compile(r"(?<![\w])S(\d{1,2})(?![\w])", re.I)
_SEP_TAIL = re.compile(r"[\s\-–—|·:,]+$")
_SEP_HEAD = re.compile(r"^[\s\-–—|·:,]+")
_YEAR_TOKEN = re.compile(r"^(?:19|20)\d\d$")


def _strip_tail(s, st):
    """يحذف من آخر الاسم (وأوّله) لاحقات النسخة ورموز الجودة والفواصل حتى يثبت ← (الاسم، النسخ)."""
    versions = []
    for _ in range(6):
        before = s
        s, v = split_version(s, st)
        versions += [x for x in v if x not in versions]
        s = C._dequal(s)
        s = _SEP_HEAD.sub("", _SEP_TAIL.sub("", s)).strip()
        if s == before:
            break
    return s, versions


def clean_title(name, st):
    """اسم القائمة كما تكتبه اللوحات ← مكوّناته: «التفاح الحرام مدبلج S06 YASAK ELMA Ar» ←
    base «التفاح الحرام» · season 6 · versions [dubbed] · original «YASAK ELMA»؛ «Heart of Stone - FHD - متعدد الترجمات» ←
    base «Heart of Stone» · versions [multi]. رمز الموسم والنسخة والجودة ليست من هوية العمل؛ والاسم الخام يبقى alias."""
    raw = " ".join((name or "").split())
    base, remainder, season = raw, "", 0
    m = _SEASON_TOKEN.search(raw)
    if m and raw[:m.start()].strip():
        base, remainder, season = raw[:m.start()], raw[m.end():], int(m.group(1))
    base, versions = _strip_tail(base, st)
    original = ""
    if remainder:
        rem = remainder.replace(".", " ").replace("_", " ")
        rem, v2 = _strip_tail(rem, st)
        versions += [x for x in v2 if x not in versions]
        tails = {t.casefold() for t in (st.get("name_tail_tokens") or [])}
        words = rem.split()
        while words and (words[-1].casefold() in tails or _YEAR_TOKEN.match(words[-1])):
            words.pop()
        rem = " ".join(words).strip()
        if len(norm(rem)) >= 3 and norm(rem) != norm(base):
            original = rem
    base = base or raw
    base2, year = C._split_year(base)
    if year and base2:
        base = base2
    if original and norm(base).startswith(norm(original)):
        original = ""
    return {"raw": raw, "base": base, "season": season, "versions": versions, "original": original, "year": year,
            "cleaned": norm(base) != norm(raw)}


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


def cluster_in_server(entries, st):
    """مداخل سيرفرٍ واحد بنفس النوع والاسم المطبَّع (من أقسامٍ شتّى) ← (عناقيد الفهارس، أغامض؟). الصورة نفسها أو السنة
    نفسها أو موسمٌ بعدد حلقاته أو اختلاف اللاحقة وحده (مدبلج/مترجم) تجمع؛ وسنتان مختلفتان تفرّقان يقينًا؛ وبلا قرينة:
    عنصران ومراجعة."""
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
    وحده: النوع واحد، والسنة ضمن ‏tmdb_year_tolerance، واسمٌ من أسماء الكيان يطابق عنوان TMDB أو أصله أو بدائله
    (بالتطبيع، أو بالمفتاح الصوتي للأسماء العربية المنقحرة)."""
    v = st.get("tmdb_verify") or {}
    if v.get("type", True) and cand.get("type") != entity.get("type"):
        return False, "type"
    cy, ey = cand.get("year") or 0, entity.get("year") or 0
    if v.get("year", True) and cy and ey and abs(cy - ey) > int(v.get("year_tolerance", 1)):
        return False, "year"
    mine = [x for x in [entity.get("title"), entity.get("title_en"), entity.get("original_title")] + list(entity.get("aliases") or []) if x]
    theirs = [x for x in [cand.get("title"), cand.get("original_title")] + list(cand.get("aliases") or []) if x]
    theirs_n = {norm(x) for x in theirs}
    if v.get("title", True):
        if not ({norm(x) for x in mine} & theirs_n) and \
           not ({phonetic(x) for x in mine} & {phonetic(x) for x in theirs}):
            return False, "title"
    # اسمٌ أصلي لاتيني من القائمة («SOZ» · «Mahkum») لا يطابق المرشّح، وبلدُ المرشّح يناقض قرينة القسم: ليس هو
    # (اسمٌ عربي عام «العهد» يطابق مسلسلًا سوريًّا وآخر تركيًّا — الأصلي والقرينة يفصلان)
    originals = {norm(x) for x in entity.get("originals") or [] if x}
    hint_c, cand_c = set(entity.get("hint_countries") or []), set(cand.get("countries") or [])
    if v.get("origin", True) and originals and not (originals & theirs_n) and hint_c and cand_c and not (hint_c & cand_c):
        return False, "origin"
    return True, "ok"


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

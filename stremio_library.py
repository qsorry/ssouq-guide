#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
المكتبة الموحدة لحساب Stremio فيه خطوط من عدة بوابات (مرح · كاسبر · فالكون…): العمل الواحد عملٌ واحد مهما اختلف اسمه
بين البوابات، ومصادره كلها معه.

  «علي كارا» في سمارت · «علي كارا (مترجم)» في كاسبر · «Ali Kara - Arabic Sub» و«علي كارا الموسم الأول» في فالكون
  ← عملٌ واحد بأربعة مصادر، والاسم الأصلي لكل مصدرٍ محفوظٌ فيه (يُعرض في قائمة المصادر ويُبحث به).

المطابقة محافظة — لا تدمج إلا عند التأكد، بهذا الترتيب:
  1. معرّف TMDB (أو IMDb) من قائمة السيرفر: واحدٌ ← عملٌ واحد؛ ومختلفان ← عملان مهما تشابه الاسم.
  2. الاسم المطبَّع + النوع + السنة (+ الموسم): بلا تشكيلٍ ولا همزاتٍ ولا حالة أحرف، وبلا ما ليس من هوية العمل —
     «مترجم» «مدبلج» «Arabic Sub» ورموز الجودة و«الموسم الأول» و«S02» (تُحذف من مفتاح المطابقة وحده، وتصير صفةً للمصدر).
     سنتان مختلفتان ← عملان («Dune 1984» و«Dune 2021»)، إلا مواسمَ مفرّقة لمسلسل (لكل موسمٍ سنته).
  3. الاسم بخطٍّ آخر (العربي واللاتيني: «علي كارا» = «Ali Kara») بالمفتاح الصوتي — ومعه قرينةٌ لا بدّ منها: السنة نفسها
     في الطرفين، أو ملف ملصق TMDB نفسه. بلا قرينة لا دمج (اسمٌ قصير يتشابه صوتيًّا ليس دليلًا).
  وما جمعه طريقان متعارضان (معرّفا TMDB أو سنتان) يُفصل بعد الدمج.

القنوات: الاسم المطبَّع بلا رمز الجودة («beIN SPORTS 1 HD» = «beIN SPORTS 1 FHD») — فالقناة الواحدة بمصادرها وجوداتها.

بلا شبكة ولا حالة: ‏build(kind, parts) يأخذ قوائم الخطوط (‏stremio_addon.Lists) ويعيد المكتبة؛ وstremio_addon يحفظها
ويعيد بناءها متى تغيّرت قائمة خطٍّ (إضافةٌ أو حذفٌ أو تعديلٌ في السيرفر).
"""
import copy
import re
import threading
from collections import OrderedDict, namedtuple

import content as C
import seo_match as M
from seo_db import DEFAULTS
from seo_search import norm, phonetic

# لواحق النسخ كما في طبقة المحتوى، وما تكتبه البوابات بالإنجليزية بعدُ («Ali Kara - Arabic Sub»)
ST = copy.deepcopy(DEFAULTS)
ST["version_tags"]["subbed"] += ["arabic sub", "arabic subs", "arabic subbed", "arabic subtitle", "arabic subtitles",
                                 "subtitles", "eng sub", "مترجم عربي", "مترجم للعربية", "ترجمة عربية"]
ST["version_tags"]["dubbed"] += ["arabic dubbed", "مدبلج عربي", "دبلجة عربية"]

VERSION_AR = {"dubbed": "مدبلج", "subbed": "مترجم", "subbed_soft": "مترجم", "multi": "متعدد الترجمات"}
_QUALITY = [("4K", re.compile(r"(?i)(?<![a-z0-9])(?:4k|8k|uhd|2160p?)(?![a-z0-9])")),
            ("FHD", re.compile(r"(?i)(?<![a-z0-9])(?:fhd|full\s*hd|1080[pi]?)(?![a-z0-9])")),
            ("HD", re.compile(r"(?i)(?<![a-z0-9])(?:hd|720p?|hq)(?![a-z0-9])")),
            ("SD", re.compile(r"(?i)(?<![a-z0-9])(?:sd|480p?|360p?)(?![a-z0-9])"))]
QUALITY_RANK = {"4K": 4, "FHD": 3, "HD": 2, "": 1, "SD": 0}

# «الموسم الأول» · «الموسم 2» · «الجزء الثالث» · «Season 3» — الموسم صفةٌ للمصدر لا من هوية العمل
_ORD = {"الاول": 1, "الثاني": 2, "الثالث": 3, "الرابع": 4, "الخامس": 5, "السادس": 6, "السابع": 7, "الثامن": 8,
        "التاسع": 9, "العاشر": 10, "الحادي عشر": 11, "الثاني عشر": 12, "الثالث عشر": 13, "الرابع عشر": 14,
        "الخامس عشر": 15}
_AR_SEASON = re.compile(r"[\s\-–—|:(\[]*(?:ال)?(?:موسم|جزء)\s+(?:رقم\s+)?(\d{1,2}|ال\S+(?:\s+عشر)?)[\s)\]]*")
_EN_SEASON = re.compile(r"(?i)[\s\-–—|:(\[]*\b(?:season|saison|sezon)\s*(\d{1,2})\b[\s)\]]*")
_ADULT_CAT = C._ADULT_GROUP


def season_of(name):
    """‏«علي كارا الموسم الأول» ← («علي كارا»، 1)؛ «Ali Kara Season 2» ← («Ali Kara»، 2)؛ وغيره كما هو بـ0."""
    s = str(name or "")
    m = _EN_SEASON.search(s)
    if m and s[:m.start()].strip():
        return (s[:m.start()] + " " + s[m.end():]).strip(), int(m.group(1))
    m = _AR_SEASON.search(s)
    if m and s[:m.start()].strip():
        word = C._norm(m.group(1))
        n = int(word) if word.isdigit() else _ORD.get(word, 0)
        if n:
            return (s[:m.start()] + " " + s[m.end():]).strip(), n
    return s, 0


def quality_of(*texts):
    """أعلى جودةٍ مذكورة في اسم المصدر أو قسمه («FHD» · «4K»…)، أو ""."""
    t = " ".join(str(x or "") for x in texts)
    for q, rx in _QUALITY:
        if rx.search(t):
            return q
    return ""


def _versions_of_cat(cat):
    """نسخة القسم («مسلسلات تركية مدبلجة» ← dubbed) — قسمٌ كلّه مدبلج أو مترجم."""
    n = norm(cat)
    out = []
    if "مدبلج" in n or "dubbed" in n:
        out.append("dubbed")
    if "مترجم" in n or re.search(r"\bsub(?:bed|s|titled)?\b", n):
        out.append("subbed")
    return out


Key = namedtuple("Key", "base nkey pkey okey year season versions quality tmdb pfile imdb")


def _int(v):
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return 0


def item_key(it, cat=""):
    """عنصر القائمة ← مفتاح مطابقته (الاسم الخام يبقى في العنصر نفسه)."""
    raw, season = season_of(it.name)
    ct = M.clean_title(raw, ST)
    season = season or ct["season"]
    base = ct["base"] or it.name
    versions = list(ct["versions"])
    for v in _versions_of_cat(cat):
        if v not in versions and not (v == "subbed" and "subbed_soft" in versions):
            versions.append(v)
    pk = phonetic(base)
    return Key(base, norm(base), pk if len(pk.replace(" ", "")) >= 3 else "", norm(ct["original"]) if ct["original"] else "",
               _int(it.year) or ct["year"], season, tuple(versions), quality_of(it.name, cat),
               _int(getattr(it, "tmdb", 0)), M.poster_file(it.poster), str(getattr(it, "imdb", "") or ""))


Src = namedtuple("Src", "line hk item key cat label")


class Work:
    """عملٌ واحد ومصادره (بترتيب الخطوط ثم الجودة)."""

    __slots__ = ("kind", "sources", "anchor", "name", "poster", "year", "rating", "plot", "genre", "added",
                 "cats", "tags", "labels", "_names", "_pkeys")

    def __init__(self, kind, sources):
        self.kind = kind
        self.sources = sorted(sources, key=lambda s: (s.line, -QUALITY_RANK.get(s.key.quality, 1), s.item.id))
        a = min(sources, key=lambda s: (s.line, s.item.id))       # المرساة: منها معرّف العمل (ثابتٌ ما بقي مصدرها)
        self.anchor = a
        if len(sources) == 1:
            self.name = a.item.name                                # مصدرٌ واحد: اسمه كما في السيرفر
        elif kind == "tv":
            self.name = C._dequal(a.item.name)                     # «beIN SPORTS 1 HD/FHD» ← «beIN SPORTS 1»
        else:
            self.name = a.key.base + (f" ({a.key.year})" if kind == "movie" and a.key.year and re.search(r"\(\d{4}\)", a.item.name) else "")
        first = lambda f: next((getattr(s.item, f) for s in [a] + self.sources if getattr(s.item, f)), None)
        tmdb_poster = next((s.item.poster for s in [a] + self.sources if s.key.pfile), None)
        self.poster = a.item.poster or tmdb_poster or first("poster") or ""
        self.year = next((str(s.key.year) for s in [a] + self.sources if s.key.year), None) if kind != "tv" else None
        self.rating = first("rating")
        self.plot = first("plot") or ""
        self.genre = first("genre") or ""
        self.added = max(s.item.added for s in sources)
        self.cats = {norm(s.cat) for s in sources if s.cat}
        self.tags = {norm(t) for s in sources for t in re.split(r"[,،/|]", s.item.genre or "") if t.strip()}
        self.labels = list(dict.fromkeys(s.label for s in self.sources if s.label))
        self._names = None
        self._pkeys = None

    def names(self):
        if self._names is None:
            self._names = list(dict.fromkeys([norm(s.item.name) for s in self.sources] + [s.key.nkey for s in self.sources]))
            self._pkeys = {s.key.pkey for s in self.sources if s.key.pkey}
        return self._names


class _UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, i):
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def union(self, i, j):
        a, b = self.find(i), self.find(j)
        if a != b:
            self.p[max(a, b)] = min(a, b)


def _years_ok(kind, a, b, tol=0):
    """سنتان لا تتعارضان: إحداهما غير معروفة، أو متساويتان (±tol)، أو موسمان مختلفان لمسلسل (لكل موسمٍ سنته)."""
    if not a.year or not b.year:
        return True
    if kind == "series" and (a.season or b.season) and a.season != b.season:
        return True
    return abs(a.year - b.year) <= tol


_AR_CHARS = re.compile(r"[\u0600-\u06ff]")


def _arabic(s):
    return bool(_AR_CHARS.search(s or ""))


def _tmdb_ok(a, b):
    """معرّفان مختلفان (TMDB أو IMDb) ← عملان يقينًا."""
    return not (a.tmdb and b.tmdb and a.tmdb != b.tmdb) and not (a.imdb and b.imdb and a.imdb != b.imdb)


def _name_bucket(kind, idx, keys, uf):
    """عناصر بالاسم المطبَّع نفسه: تُجمع ما لم تتعارض سنتها أو معرّفها. ما لا سنة له (أو موسمٌ مفرّق لمسلسل: سنته سنة
    موسمه) يلحق بالمجموعة الوحيدة ذات السنة، ويجتمع وحده إن لم تكن سنة؛ ومع سنتين معروفتين مختلفتين يبقى وحده (لا يُخمَّن
    لأيّهما)."""
    years, loose = OrderedDict(), []
    for i in idx:
        k = keys[i]
        if k.year and not (kind == "series" and k.season):
            years.setdefault(k.year, []).append(i)
        else:
            loose.append(i)
    groups = list(years.values())
    if len(groups) <= 1:
        groups = [(groups[0] if groups else []) + loose]
    elif loose:
        groups.append(loose)
    for g in groups:
        for x in range(1, len(g)):
            if _tmdb_ok(keys[g[0]], keys[g[x]]):
                uf.union(g[0], g[x])


def _split_conflicts(kind, members, keys):
    """عنقودٌ جمعه طريقان متعارضان (معرّفا TMDB مختلفان، أو سنتان) ← أجزاءٌ لا تعارض فيها."""
    tm = {keys[i].tmdb for i in members if keys[i].tmdb}
    if len(tm) > 1:
        parts = OrderedDict((t, [i for i in members if keys[i].tmdb == t]) for t in tm)
        rest = [i for i in members if not keys[i].tmdb]
        for i in rest:
            home = next((p for p in parts.values() if all(_years_ok(kind, keys[i], keys[j], 1) for j in p)), None)
            (home if home is not None else max(parts.values(), key=len)).append(i)
        return [p for p in parts.values()]
    if kind == "series" or any(keys[i].tmdb for i in members):
        return [members]
    years = OrderedDict()
    for i in members:
        if keys[i].year:
            years.setdefault(keys[i].year, []).append(i)
    if len(years) <= 1:
        return [members]
    parts = list(years.values())
    biggest = max(parts, key=len)
    biggest += [i for i in members if not keys[i].year]
    return parts


def merge(kind, entries):
    """‏entries: [(Src)] ← عناقيد الفهارس (كل عنقودٍ عملٌ واحد)."""
    keys = [e.key for e in entries]
    uf = _UF(len(entries))
    by_tmdb, by_name, by_phon, by_poster = {}, {}, {}, {}
    for i, k in enumerate(keys):
        if k.tmdb:
            by_tmdb.setdefault(("t", k.tmdb), []).append(i)
        if k.imdb:
            by_tmdb.setdefault(("i", k.imdb), []).append(i)
        by_name.setdefault(k.nkey, []).append(i)
        if k.okey and k.okey != k.nkey:
            by_name.setdefault(k.okey, []).append(i)              # الاسم الأصلي اللاتيني بعد رمز الموسم
        if k.pkey:
            by_phon.setdefault(k.pkey, []).append(i)
        if k.pfile:
            by_poster.setdefault(k.pfile, []).append(i)
    for idx in by_tmdb.values():                                  # 1. معرّف TMDB
        for x in range(1, len(idx)):
            if _years_ok(kind, keys[idx[0]], keys[idx[x]], 1) and _tmdb_ok(keys[idx[0]], keys[idx[x]]):
                uf.union(idx[0], idx[x])
    for nk, idx in by_name.items():                               # 2. الاسم المطبَّع + السنة
        if nk and len(idx) > 1:
            _name_bucket(kind, idx, keys, uf)
    for idx in list(by_phon.values()) + list(by_poster.values()):   # 3. بخطٍّ آخر: بقرينة سنةٍ أو ملصق
        if len(idx) < 2 or len(idx) > 200:
            continue
        for x in range(len(idx)):
            for y in range(x + 1, len(idx)):
                a, b = keys[idx[x]], keys[idx[y]]
                if not _tmdb_ok(a, b):
                    continue
                same_year = bool(a.year and b.year and a.year == b.year)
                same_poster = bool(a.pfile and a.pfile == b.pfile)
                # الصوتي بين خطّين مختلفين وحدهما («علي كارا» و«Ali Kara») — وفي الخط الواحد يكفي الاسم المطبَّع
                cross = a.pkey == b.pkey and _arabic(a.base) != _arabic(b.base)
                if (same_poster or (cross and same_year)) and _years_ok(kind, a, b, 1 if same_poster else 0):
                    uf.union(idx[x], idx[y])
    groups = OrderedDict()
    for i in range(len(entries)):
        groups.setdefault(uf.find(i), []).append(i)
    out = []
    for members in groups.values():
        out += _split_conflicts(kind, members, keys) if len(members) > 1 else [members]
    return out


def _live_key(name):
    return C._norm(C._dequal(" ".join(str(name or "").split())))


class Library:
    """أعمال نوعٍ واحد لخطوط حساب: الأحدث أولًا (والقنوات بترتيب السيرفر)، وفهرسٌ من مصدرٍ إلى عمله، والبحث."""

    def __init__(self, kind, works, genres):
        self.kind = kind
        self.works = works
        self.latest = works if kind == "tv" else sorted(works, key=lambda w: -w.added)
        self.by_src = {(s.hk, s.item.id): w for w in works for s in w.sources}
        self.genres = genres                                      # [(اسم القسم، عدد الأعمال)] بترتيب الخطوط
        self.labels = list(dict.fromkeys(lb for w in works for lb in w.labels))
        self._num = {id(w): n for n, w in enumerate(self.latest, 1)} if kind == "tv" else {}
        self._lock = threading.Lock()

    def number(self, w):
        """رقم القناة: مكانها في القائمة الموحدة (بترتيب السيرفر) — كأرقام القنوات في تطبيقات IPTV."""
        return self._num.get(id(w), 0)

    def find(self, hk, iid):
        return self.by_src.get((hk, iid))

    def in_category(self, g):
        n = norm(g)
        return [w for w in self.latest if n in w.cats]

    def from_source(self, label):
        return [w for w in self.latest if label in w.labels]

    def tagged(self, g):
        n = norm(g)
        return [w for w in self.latest if n in w.tags]

    def search(self, q):
        """كل الكلمات في اسمٍ من أسماء العمل (أسماء مصادره الأصلية ومفتاحه): المطابق ثم ما يبدأ بها ثم ما يحويها؛ ثم بالمفتاح
        الصوتي («Ali Kara» يجد «علي كارا»). عملٌ واحد مرةً واحدة مهما كثرت مصادره."""
        words = norm(q).split()
        if not words:
            return []
        phrase = " ".join(words)
        pq = phonetic(q)
        pq = pq if len(pq.replace(" ", "")) >= 3 else ""
        hits = []
        for w in self.latest:
            best = None
            for k in w.names():
                if all(x in k for x in words):
                    r = 0 if k == phrase else 1 if k.startswith(phrase) else 2 if (" " + phrase) in (" " + k) else 3
                    best = r if best is None else min(best, r)
            if best is None and pq:
                if pq in w._pkeys:
                    best = 4
                elif any(p.startswith(pq + " ") for p in w._pkeys):
                    best = 5
            if best is not None:
                hits.append((best, -w.added, w))
        hits.sort(key=lambda h: (h[0], h[1]))
        return [h[2] for h in hits]


def build(kind, parts):
    """‏parts: [(رقم الخط، بصمة سيرفره، اسمه، Lists أو None)] بترتيب الخطوط (صاحب الحساب أولًا) ← Library."""
    entries = []
    for line, hk, label, L in parts:
        if L is None:
            continue
        keys = L.match_keys(item_key) if kind != "tv" else None
        for n, it in enumerate(L.items):
            cat = L.cat_of(it)
            entries.append(Src(line, hk, it, keys[n] if keys else None, cat, label))
    if kind == "tv":
        works, at = [], {}
        for s in entries:
            k = _live_key(s.item.name)
            if k in at:
                at[k].append(s)
            else:
                at[k] = [s]
                works.append(at[k])
        works = [_live_work(ss) for ss in works]
    else:
        works = [Work(kind, [entries[i] for i in g]) for g in merge(kind, entries)]
    for w in works:                                               # فهرس البحث مع البناء (في الخلفية غالبًا)
        w.names()
    counts, names = OrderedDict(), {}
    for w in works:
        for c in w.cats:
            counts[c] = counts.get(c, 0) + 1
    for line, hk, label, L in parts:
        for g in (L.genres if L is not None else []):
            names.setdefault(norm(g), g)
    genres = [(names[c], counts[c]) for c in names if counts.get(c)]
    return Library(kind, works, genres)


def _live_work(sources):
    k = Key("", "", "", "", 0, 0, (), "", 0, "", "")
    srcs = [Src(s.line, s.hk, s.item, k._replace(quality=quality_of(s.item.name)), s.cat, s.label) for s in sources]
    return Work("tv", srcs)

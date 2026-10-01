# -*- coding: utf-8 -*-
"""تصحيح البحث: «person break» و«Prison Brek» و«بريزن بريك» كلها تصل إلى Prison Break — اقتراحًا، لا دمجًا.

المفتاح الصوتي (‏phonetic): الاسم بأي خطّ يُختزل إلى هيكل صوامت موحَّد (‏p/b ← b، s/z/ص/ز ← s، c/k/q/ك/ق ← k،
والصوائت والتضعيف تُحذف…) فيلتقي «Prison Break» (‏brsn brk) مع «بريزن بريك» (‏brsn brk) مع «person break» (‏brsn brk).
والأخطاء الإملائية الأبعد بمسافة تحريرٍ ≤ 2 على المفتاح. والنتيجة اقتراح («هل تقصد…؟») بثقةٍ، لا كيانٌ جديد ولا دمج —
المطابقة بين الكيانات تبقى كما في ‏seo_match. وبلا مكتبات خارجية.
"""
import re
import unicodedata

import content as C

_APOS = re.compile(r"[\'\u2019\u02bc`]")


def norm(s):
    """تطبيع الطبقة: كتطبيع المحتوى لكن الفاصلة العليا تُحذف لا تُفصل («Wayne's World» = «Waynes World»)."""
    return C._norm(_APOS.sub("", s or ""))

# لاتيني ← صامت موحَّد (بعد NFKD وحذف العلامات)
_LAT = {"b": "b", "p": "b", "v": "f", "f": "f", "w": "w", "m": "m", "n": "n", "l": "l", "r": "r",
        "t": "t", "d": "d", "s": "s", "z": "s", "c": "k", "k": "k", "q": "k", "g": "j", "j": "j", "h": "h", "x": "ks", "y": "y"}
_LAT_DIGRAPH = {"ph": "f", "th": "t", "sh": "sh", "ch": "ch", "kh": "kh", "gh": "j", "ck": "k", "ts": "s", "dh": "t", "zh": "j"}
_ARTICLES = {"al", "el", "the", "ال", "ذا"}
# عربي ← الصامت نفسه (الحروف الصائتة ا و ي والهمزات تُحذف)
_AR = {"ب": "b", "پ": "b", "ت": "t", "ة": "", "ث": "t", "ج": "j", "چ": "ch", "ح": "h", "خ": "kh", "د": "d", "ذ": "t",
       "ر": "r", "ز": "s", "س": "s", "ش": "sh", "ص": "s", "ض": "d", "ط": "t", "ظ": "s", "ع": "", "غ": "j", "ف": "f",
       "ڤ": "f", "ق": "k", "ك": "k", "گ": "g", "ل": "l", "م": "m", "ن": "n", "ه": "h", "و": "w", "ي": "y", "ى": "", "ء": "",
       "أ": "", "إ": "", "آ": "", "ا": "", "ؤ": "w", "ئ": "y"}
_VOWELS = set("aeiou")
_WORD = re.compile(r"[^\W_]+", re.U)


def _lat_word(w):
    w = "".join(ch for ch in unicodedata.normalize("NFKD", w) if not unicodedata.combining(ch)).lower()
    out, i = [], 0
    while i < len(w):
        two = w[i:i + 2]
        if two in _LAT_DIGRAPH:
            out.append(_LAT_DIGRAPH[two]); i += 2; continue
        ch = w[i]
        if ch == "o" and i == 0 and len(w) > 1:       # «One» «Office» «Oppenheimer»: الواو في النقحرة العربية («ون» «أوفيس»)
            out.append("w")
        elif ch in _VOWELS or ch == "'":
            pass
        elif ch == "c" and i + 1 < len(w) and w[i + 1] in "eiy":   # «piece» «office»: c ناعمة
            out.append("s")
        elif ch == "y" and 0 < i < len(w) - 1:      # «y» وسط الكلمة صائتة («Styles»)
            pass
        elif ch == "w" and i > 0 and w[i - 1] in _VOWELS:   # «ow» «aw»: صائتة
            pass
        elif ch == "h" and i > 0 and i == len(w) - 1:       # هاء في الآخر صامتة
            pass
        elif ch.isdigit():
            out.append(ch)
        else:
            out.append(_LAT.get(ch, ch))
        i += 1
    return "".join(out)


def _ar_word(w):
    out = []
    if len(w) > 3 and w.startswith("ال"):          # أداة التعريف تُحذف كما تُحذف «al/the» اللاتينية
        w = w[2:]
    if len(w) > 2 and w[0] in "اأإآ" and w[1] == "و":   # «أوفيس» «أوبنهايمر»: همزةٌ فواو = «o» اللاتينية في الأول
        w = "و" + w[2:]
    for i, ch in enumerate(w):
        if ch in ("و", "ي") and 0 < i < len(w) - 1:   # واو وياء وسط الكلمة غالبًا مدّ («بريزن» «سوق»)
            continue
        if ch == "ي" and i == len(w) - 1 and len(w) > 2:   # ياء الآخر مدّ أو نسبة
            continue
        if ch == "و" and i == 0:
            out.append("w"); continue
        out.append(_AR.get(ch, ch if ch.isdigit() else ""))
    return "".join(out)


def phonetic(s):
    """المفتاح الصوتي للاسم بأي خطّ ← كلماتٌ من صوامت بينها فراغ (بلا تكرار متتالٍ)."""
    s = unicodedata.normalize("NFKC", s or "").translate(C._DIG)
    s = C._TASHKEEL.sub("", s)
    words = []
    for w in _WORD.findall(s):
        if w.lower() in _ARTICLES:
            continue
        k = _ar_word(w) if re.search(r"[؀-ۿ]", w) else _lat_word(w)
        k = re.sub(r"(.)\1+", r"\1", k)
        if k:
            words.append(k)
    return " ".join(words)


def _lev(a, b, cap=3):
    """مسافة التحرير بحدٍّ — سطرٌ واحد من الذاكرة."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


class Index:
    """فهرس الأسماء في الذاكرة من ‏content_alias: بالتطبيع، وبالمفتاح الصوتي، وبالكلمات — يُبنى من القاعدة بعد كل بناء."""

    def __init__(self, rows, years=None):
        self.by_norm, self.by_phon, self.names, self.years = {}, {}, {}, years or {}
        for cid, alias, an, ph, kind in rows:
            self.by_norm.setdefault(an, set()).add(cid)
            if ph:
                self.by_phon.setdefault(ph, set()).add(cid)
            self.names.setdefault(cid, []).append((alias, kind))
        self.phon_keys = list(self.by_phon)

    def title(self, cid):
        for a, k in self.names.get(cid, ()):
            if k == "title":
                return a
        return self.names.get(cid, [("", "")])[0][0]

    def search(self, q, max_suggest=5, min_conf=0.5):
        """‏← {"exact": [cid…], "suggest": [(cid, الاسم, الثقة, السبب)…]}: الدقيق بالتطبيع، وإلا الصوتي (1.0)،
        وإلا الأقرب تحريريًّا على المفتاح الصوتي ثم على التطبيع (ثقةٌ تنقص بالمسافة)."""
        qn, qp = norm(q), phonetic(q)
        if not qn:
            return {"exact": [], "suggest": []}
        m = re.fullmatch(r"(.+?)\s+((?:19|20)\d\d)", qn)     # «Dune 1984»: الاسم ثم السنة تميّز
        if m and qn not in self.by_norm:
            r = self.search(m.group(1), max_suggest, min_conf)
            y = int(m.group(2))
            ex = [c for c in r["exact"] if self.years.get(c) == y]
            sg = [x for x in r["suggest"] if self.years.get(x[0]) == y]
            if ex:
                return {"exact": ex, "suggest": []}
            if sg or r["exact"] or r["suggest"]:
                return {"exact": [], "suggest": sg or [(c, self.title(c), 0.7, "name, other year") for c in r["exact"]][:max_suggest] or r["suggest"]}
        if qn in self.by_norm:
            return {"exact": sorted(self.by_norm[qn]), "suggest": []}
        found = {}
        for cid in self.by_phon.get(qp, ()):
            found[cid] = (0.95, "phonetic")
        if not found and len(qp) >= 4:
            cands = []
            for k in self.phon_keys:
                d = _lev(qp, k, cap=2)
                if d <= 2:
                    cands.append((d, k))
            for d, k in sorted(cands)[:20]:
                conf = 0.9 - 0.2 * d
                for cid in self.by_phon[k]:
                    if conf >= min_conf and (cid not in found or found[cid][0] < conf):
                        found[cid] = (conf, f"phonetic~{d}")
        if not found:
            # بادئة أو احتواء بالتطبيع («breaking» ← Breaking Bad)
            for an, cids in self.by_norm.items():
                if an.startswith(qn) or (len(qn) >= 4 and qn in an):
                    conf = 0.8 if an.startswith(qn) else 0.6
                    for cid in cids:
                        if cid not in found or found[cid][0] < conf:
                            found[cid] = (conf, "prefix" if an.startswith(qn) else "contains")
        out = sorted(((cid, self.title(cid), c, why) for cid, (c, why) in found.items()), key=lambda x: (-x[2], x[1]))
        return {"exact": [], "suggest": out[:max_suggest]}


def load(con):
    rows = con.execute("SELECT a.content_id, a.alias, a.alias_norm, a.phonetic, a.kind FROM content_alias a "
                       "JOIN content c ON c.id=a.content_id WHERE c.merged_into IS NULL").fetchall()
    years = {r[0]: r[1] for r in con.execute("SELECT id, year FROM content WHERE merged_into IS NULL AND year IS NOT NULL")}
    return Index([tuple(r) for r in rows], years)


def explain(con, idx, q, st):
    """لتقرير جودة البحث: ما يصير إليه الاسم — كيان (slug) · alias · نسخة · اقتراح · أو لا شيء. لاحقة النسخة في الاستعلام
    («طبيعة الحب مترجم») تُحذف قبل البحث، والاقتراح لا يُعرض تحت عتبة الثقة (‏search_min_conf)."""
    import seo_match
    q = seo_match.split_version(q, st)[0] or q
    r = idx.search(q, st.get("search_max_suggest", 5), st.get("search_min_conf", 0.75))

    def ent(cid):
        row = con.execute("SELECT id, slug, title FROM content WHERE id=?", (cid,)).fetchone()
        vers = [(x["service_key"], x["versions_json"]) for x in con.execute(
            "SELECT service_key, versions_json FROM content_service WHERE content_id=? AND present=1", (cid,))]
        return {"id": row["id"], "slug": row["slug"], "title": row["title"], "versions": vers}
    def grouped(ents):
        """كياناتٌ بالاسم نفسه (العمل نفسه على سيرفرين بلا دليل دمج بعد، أو عملان متشابهان): تُجمع للعرض مرةً واحدة —
        عرضٌ لا دمج؛ ويُذكر لماذا هما كيانان (name_only · split …) من بنود المراجعة المفتوحة."""
        groups = {}
        for e in ents:
            groups.setdefault(norm(e["title"]), []).append(e["id"])
        out = []
        for t, ids in groups.items():
            g = {"title": t, "ids": ids}
            if len(ids) > 1:
                kinds = [r[0] for r in con.execute("SELECT DISTINCT kind FROM review WHERE status='open' AND kind IN ('name_only','conflict','split_entity','same_server_ambiguous') "
                                                   "AND payload_json LIKE ?", (f'%"name": "{ents[0]["title"]}"%',))]
                g["why_separate"] = kinds or ["no merge evidence yet (tmdb pending)"]
            out.append(g)
        return out
    if r["exact"]:
        ents = [ent(c) for c in r["exact"]]
        return {"q": q, "norm": norm(q), "phonetic": phonetic(q), "result": "entity", "entities": ents, "grouped": grouped(ents)}
    if r["suggest"]:
        sg = [dict(ent(c), confidence=conf, why=why) for c, _, conf, why in r["suggest"]]
        return {"q": q, "norm": norm(q), "phonetic": phonetic(q), "result": "suggest", "suggest": sg, "grouped": grouped(sg)}
    return {"q": q, "norm": norm(q), "phonetic": phonetic(q), "result": "none"}

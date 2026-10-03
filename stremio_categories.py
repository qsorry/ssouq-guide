# -*- coding: utf-8 -*-
"""تصنيفات سمارت سوق في Stremio: تصنيفٌ واحد لكل البوابات بدل أقسام كل لوحةٍ بأسمائها («مسلسلات تركية» في سمارت و
«TR | Turkish» في فالكون = «تركي»).

كل تصنيفٍ نوعه (مسلسلات · أفلام · قنوات) واسمه وكلمات ربطه: قسم اللوحة الذي يحوي كلمةً منها يدخل فيه، والقناة باسمها
أيضًا (كلمةٌ بـ«-» قبلها تُخرجه: «عرب، -مدبلج»)، وللأفلام والمسلسلات تصنيفات العمل نفسه أيضًا (‏genres: «أكشن» من حقل genre بلغتيه). وما لم يدخل
تصنيفًا في «أخرى». ‏home: صفٌّ في رئيسية Stremio («تركي - المسلسلات»)، وإلا ففي قائمة «اكتشف» وحدها؛ ‏on=False: مخفي.

يُحرَّر من صفحة «التصنيفات» في الأداة لكل حساب أداة (وبلا تحرير: الافتراضي هنا). تغيير الصفوف يصل حسابات Stremio بـ«تحديث
الإضافة لكل الحسابات» (الـmanifest)، ومحتوى كل تصنيفٍ يُقرأ من الخادم فيتغيّر فورًا.

الحفظ: ‏data/stremio_categories.json ‏{حساب الأداة: {"cats": [...]، "at": وقت}}.
"""
import copy
import hashlib
import json
import os
import re
import threading
import time

from seo_search import norm

FILE = "stremio_categories.json"
KINDS = ("series", "movie", "tv")
KIND_AR = {"series": "المسلسلات", "movie": "الأفلام", "tv": "القنوات"}
OTHERS = "أخرى"                     # ما لم يدخل تصنيفًا (في «اكتشف» وحدها)
OTHERS_ID = "others"
MAX_PER_KIND = 30
NAME_MAX = 40
KEYS_MAX = 600

_C = lambda cid, kind, name, keys, home=True, genres="": {"id": cid, "kind": kind, "name": name, "keys": keys,
                                                          "genres": genres, "home": home, "on": True}
DEFAULTS = [
    _C("s_ramadan", "series", "رمضان", "رمضان, ramadan"),
    _C("s_turkish", "series", "تركي", "ترك, turk, turkish, tr"),
    _C("s_arabic", "series", "عربي", "عرب, arab, مصر, خليج, سوري, شامي, لبنان, عراق, سعودي, كويت, gulf, egypt, khaliji, "
                                     "-ترك, -هند, -كور, -مدبلج, -انمي"),
    _C("s_foreign", "series", "أجنبي", "اجنب, english, foreign, netflix, hbo, apple, amazon, disney, en, us, uk, usa, -مدبلج"),
    _C("s_asian", "series", "آسيوي", "كور, korea, kdrama, k drama, صين, china, chinese, يابان, japan, تايلند, thai, اسيو, asian"),
    _C("s_anime", "series", "أنمي", "انمي, انيمي, anime", genres="أنمي"),
    _C("s_kids", "series", "أطفال وكرتون", "اطفال, كرتون, kids, cartoon, children, رسوم متحركة, animation, spacetoon",
       genres="رسوم متحركة, أطفال"),
    _C("s_indian", "series", "هندي", "هند, india, hindi, bollywood", home=False),
    _C("s_docs", "series", "وثائقي", "وثائق, documentar", home=False, genres="وثائقي"),
    _C("s_dubbed", "series", "مدبلج", "مدبلج, dubbed, dub", home=False),
    _C("m_arabic", "movie", "عربي", "عرب, arab, مصر, خليج, سعودي, egypt, gulf, -مدبلج, -هند, -ترك"),
    _C("m_foreign", "movie", "أجنبي", "اجنب, english, foreign, hollywood, هوليود, netflix, نتفلكس, en, us, uk, usa, -هند, -مدبلج"),
    _C("m_action", "movie", "أكشن", "اكشن, action", genres="أكشن"),
    _C("m_horror", "movie", "رعب", "رعب, horror", genres="رعب"),
    _C("m_comedy", "movie", "كوميديا", "كوميد, comedy", genres="كوميديا"),
    _C("m_kids", "movie", "أطفال وكرتون", "اطفال, كرتون, kids, cartoon, animation, انيميشن, رسوم متحركة, disney, pixar",
       genres="رسوم متحركة"),
    _C("m_indian", "movie", "هندي", "هند, india, hindi, bollywood"),
    _C("m_thriller", "movie", "إثارة وجريمة", "اثارة, thriller, جريمة, crime, غموض, mystery", home=False, genres="إثارة, جريمة, غموض"),
    _C("m_drama", "movie", "دراما", "دراما, drama", home=False, genres="دراما"),
    _C("m_scifi", "movie", "خيال علمي", "خيال علمي, sci fi, science fiction, فانتازيا, fantasy", home=False, genres="خيال علمي, فانتازيا"),
    _C("m_turkish", "movie", "تركي", "ترك, turk, tr", home=False),
    _C("m_asian", "movie", "آسيوي", "كور, korea, صين, china, يابان, japan, اسيو, asian, thai", home=False),
    _C("m_anime", "movie", "أنمي", "انمي, anime", home=False, genres="أنمي"),
    _C("m_docs", "movie", "وثائقي", "وثائق, documentar", home=False, genres="وثائقي"),
    _C("m_4k", "movie", "4K", "4k, uhd, 2160", home=False),
    _C("t_sports", "tv", "رياضة", "رياض, sport, bein, ssc, kass, الكاس, ad sport, nba, football, كرة, dazn, espn"),
    _C("t_news", "tv", "أخبار", "اخبار, news"),
    _C("t_arabic", "tv", "عربية", "عرب, arab, mbc, روتانا, rotana, مصر, سعودي, خليج, ksa, uae, امارات, قطر, كويت, عراق, سوري, لبنان, "
                                  "-رياض, -sport, -اخبار, -news, -اطفال, -kids"),
    _C("t_movies", "tv", "أفلام ومسلسلات", "افلام, مسلسلات, movies, cinema, سينما, drama, دراما, osn, box office"),
    _C("t_kids", "tv", "أطفال", "اطفال, kids, cartoon, كرتون, spacetoon, سبيستون, children"),
    _C("t_docs", "tv", "وثائقي", "وثائق, documentar, nat geo, national geographic, discovery", home=False),
    _C("t_religious", "tv", "دينية", "ديني, دين, قران, quran, islam, اسلام", home=False),
    _C("t_foreign", "tv", "أجنبية", "english, uk, usa, us, en, foreign, اجنب", home=False),
    _C("t_4k", "tv", "4K", "4k, uhd", home=False),
]

_lock = threading.Lock()
_cache = {}                          # المسار ← (وقت التعديل، المحتوى)


def defaults():
    return copy.deepcopy(DEFAULTS)


def _path(data_dir):
    return os.path.join(data_dir, FILE)


def _load(data_dir):
    path = _path(data_dir)
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return {}
    with _lock:
        hit = _cache.get(path)
        if hit and hit[0] == mt:
            return hit[1]
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    d = d if isinstance(d, dict) else {}
    with _lock:
        _cache[path] = (mt, d)
    return d


def _write(data_dir, d):
    path = _path(data_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    with _lock:
        _cache.pop(path, None)


def get(data_dir, acct_id):
    """تصنيفات حساب الأداة (المحفوظة، وإلا الافتراضية)."""
    if not data_dir or not acct_id:
        return defaults()
    rec = _load(data_dir).get(str(acct_id))
    cats = rec.get("cats") if isinstance(rec, dict) else None
    return copy.deepcopy(cats) if isinstance(cats, list) else defaults()


def edited(data_dir, acct_id):
    rec = _load(data_dir).get(str(acct_id)) if data_dir and acct_id else None
    return bool(isinstance(rec, dict) and isinstance(rec.get("cats"), list))


def _clean_text(v, limit):
    return " ".join(str(v or "").split())[:limit]


def clean(cats):
    """تحقّقٌ وتنظيف لما يُحفظ ← القائمة. ‏ValueError برسالةٍ للعرض."""
    if not isinstance(cats, list):
        raise ValueError("قائمة تصنيفاتٍ غير صالحة")
    out, ids, per = [], set(), {k: 0 for k in KINDS}
    for c in cats:
        if not isinstance(c, dict) or c.get("kind") not in KINDS:
            raise ValueError("تصنيفٌ بلا نوعٍ صالح")
        name = _clean_text(c.get("name"), NAME_MAX)
        if not name:
            raise ValueError("تصنيفٌ بلا اسم")
        if norm(name) == norm(OTHERS):
            raise ValueError(f"«{OTHERS}» يُضاف وحده (ما لم يدخل تصنيفًا)")
        kind = c["kind"]
        per[kind] += 1
        if per[kind] > MAX_PER_KIND:
            raise ValueError(f"الحدّ {MAX_PER_KIND} تصنيفًا لكل نوع")
        cid = re.sub(r"[^a-z0-9_]", "", str(c.get("id") or "").lower())[:24]
        if not cid or cid in ids or cid == OTHERS_ID:
            cid = kind[0] + "_" + hashlib.sha1(f"{kind}\n{name}\n{len(out)}".encode()).hexdigest()[:8]
        ids.add(cid)
        out.append({"id": cid, "kind": kind, "name": name, "keys": _clean_text(c.get("keys"), KEYS_MAX),
                    "genres": _clean_text(c.get("genres"), KEYS_MAX) if kind != "tv" else "",
                    "home": bool(c.get("home")), "on": c.get("on", True) is not False})
    names = [(c["kind"], norm(c["name"])) for c in out]
    dup = next((c["name"] for c, k in zip(out, names) if names.count(k) > 1), None)
    if dup:
        raise ValueError(f"اسمٌ مكرّر في النوع نفسه: «{dup}»")
    return out


def save(data_dir, acct_id, cats):
    cats = clean(cats)
    d = dict(_load(data_dir))
    d[str(acct_id)] = {**(d.get(str(acct_id)) or {}), "cats": cats, "at": int(time.time())}
    _write(data_dir, d)
    return cats


def reset(data_dir, acct_id):
    """يعيد الافتراضي (يحذف تحرير الحساب)."""
    d = dict(_load(data_dir))
    if d.pop(str(acct_id), None) is not None:
        _write(data_dir, d)
    return defaults()


# ---- المطابقة ----
def _terms(keys):
    """«عرب، arab، -مدبلج» ← ([مطابِقات]، [مستثنيات]) مطبَّعةً."""
    inc, exc = [], []
    for t in re.split(r"[,،\n|]", keys or ""):
        t = t.strip()
        neg = t[:1] in "-!"
        t = norm(t[1:] if neg else t)
        if t:
            (exc if neg else inc).append(t)
    return inc, exc


def _hit(term, name):
    """كلمةٌ قصيرة لاتينية (tr · en · us) كلمةٌ كاملة؛ وغيرها جزءٌ من الاسم («ترك» في «التركية»)."""
    if len(term) <= 3 and term.isascii():
        return f" {term} " in f" {name} "
    return term in name


def matcher(cat):
    inc, exc = _terms(cat.get("keys"))

    def match(name):
        return bool(inc) and any(_hit(t, name) for t in inc) and not any(_hit(t, name) for t in exc)
    return match


def of_kind(cats, kind, home=None):
    """تصنيفات نوعٍ الظاهرة بترتيبها (و‏home: صفوف الرئيسية وحدها)."""
    return [c for c in cats if c.get("kind") == kind and c.get("on", True) and (home is None or bool(c.get("home")) == home)]


def sig(cats):
    return tuple((c["id"], c.get("keys", ""), c.get("genres", "")) for c in cats)

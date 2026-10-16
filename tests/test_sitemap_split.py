"""خريطة الموقع: ≤ الحدّ خريطةٌ واحدة كما كانت، وفوقه فهرسٌ بخرائط فرعية بالقسم واللغة وبلا رابطٍ مفقود أو مكرَّر."""
import os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import guide_pages as G

ok = fail = 0


def check(name, cond, info=""):
    global ok, fail
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  ({info})" if not cond and info else ""))
    ok, fail = ok + bool(cond), fail + (not cond)


extra = [(f"/content/series/s{i}/", "weekly", "0.7") for i in range(30)] + [(f"/en/content/series/s{i}/", "weekly", "0.7") for i in range(30)] \
    + [(f"/content/movies/m{i}/", "weekly", "0.7") for i in range(10)] + [("/watch/", "daily", "0.5")]
LOC = re.compile(r"<loc>([^<]+)</loc>")
check("عدّ صغير: خريطةٌ واحدة (urlset) كما كانت، وبلا أجزاء", G.sitemap_parts(extra) is None and b"<urlset" in G.sitemap_public(extra) and b"<sitemapindex" not in G.sitemap_public(extra))
G.SITEMAP_SINGLE_MAX, G.SITEMAP_PART_MAX = 20, 25
parts = G.sitemap_parts(extra)
idx = G.sitemap_public(extra).decode()
check("فوق الحدّ: /sitemap.xml فهرس يسرد كل خريطة فرعية", b"<sitemapindex" in idx.encode() and all(f"{G.SITE}/{n}" in idx for n in parts), idx[:200])
check("الأقسام: static + series-ar (مقسَّمة بالحدّ 25) + series-en + movies-ar", {"sitemap-static.xml", "sitemap-series-ar.xml", "sitemap-series-ar-2.xml", "sitemap-series-en.xml", "sitemap-movies-ar.xml"} <= set(parts), sorted(parts))
check("لا خريطة فرعية فوق الحدّ", all(len(LOC.findall(x.decode())) <= 25 for x in parts.values()))
all_locs = [u for x in parts.values() for u in LOC.findall(x.decode())]
whole = LOC.findall(G.sitemap(extra).decode())
check("مجموع الأجزاء = الخريطة الكاملة بلا فقد ولا تكرار", sorted(all_locs) == sorted(whole) and len(set(all_locs)) == len(all_locs), f"{len(all_locs)} vs {len(whole)}")
check("خريطةٌ فرعية مجهولة: None (404)", G.sitemap_public(extra, "sitemap-nope.xml") is None and G.sitemap_public(extra, "sitemap-static.xml"))
xml = G.sitemap(extra).decode()
ent = [b for b in xml.split("<url>") if "/content/series/s0/" in b][0]
stat = [b for b in xml.split("<url>") if "/watch/</loc>" in b][0]
check("روابط المحتوى بلا lastmod (تاريخٌ غير حقيقي) وتحتفظ بـ changefreq/priority، وغيرها يحتفظ به", "<lastmod>" not in ent and "<priority>0.7" in ent and "<changefreq>weekly" in ent and "<lastmod>" in stat)
print(f"\nResult: {ok} passed, {fail} failed")
sys.exit(1 if fail else 0)

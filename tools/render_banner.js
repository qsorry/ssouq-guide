// يصوّر بنرًا من tools/banners/ إلى صورة WebP بمقاسه (العرض والارتفاع في html,body{…}).
//     node tools/render_banner.js tools/banners/install-guide.html static/img/store/install-guide.webp
// يحتاج Playwright وChromium كاختبارات الواجهة (tests/ui_*.js)، والشبكة لخط Noto Sans Arabic من Google Fonts.
// خلف وسيط: HTTPS_PROXY يُمرَّر إلى Chromium، وCHROMIUM_ARGS لأي خيارٍ آخر تحتاجه بيئتك.
const fs = require("fs"), path = require("path"), { execSync } = require("child_process");
let chromium;
try { ({ chromium } = require("playwright-core")); } catch (e) { ({ chromium } = require("playwright")); }

const [src, out, quality = "0.92"] = process.argv.slice(2);
if (!src || !out) throw new Error("الاستعمال: node tools/render_banner.js <بنر.html> <صورة.webp> [الجودة 0-1]");

const size = fs.readFileSync(src, "utf8").match(/html,\s*body\s*\{[^}]*?width:\s*(\d+)px;\s*height:\s*(\d+)px/);
if (!size) throw new Error("لم أجد مقاس البنر في html,body{width:…px;height:…px}");
const [width, height] = [+size[1], +size[2]];

const exe = process.env.CHROMIUM ||
  execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim() || undefined;
const proxy = process.env.HTTPS_PROXY || process.env.https_proxy;

(async () => {
  const browser = await chromium.launch({
    executablePath: exe,
    args: ["--no-sandbox", ...(process.env.CHROMIUM_ARGS || "").split(/\s+/).filter(Boolean)],
    ...(proxy ? { proxy: { server: proxy } } : {}),
  });
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
  await page.goto("file://" + path.resolve(src), { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts.ready);

  // لا تُلتقط الصورة بخطٍّ بديل أو بشعارٍ ناقص
  const bad = await page.evaluate(async () => {
    const fonts = [...document.fonts].filter((f) => f.status === "loaded").map((f) => f.family.replace(/"/g, "") + " " + f.weight);
    const out = ["Noto Sans Arabic 400", "Noto Sans Arabic 700"].filter((f) => !fonts.includes(f));
    const srcs = [...document.querySelectorAll("img, image")].map((i) => i.src || i.href.baseVal);
    for (const s of srcs) { try { const i = new Image(); i.src = s; await i.decode(); } catch (e) { out.push(s); } }
    return out;
  });
  if (bad.length) throw new Error("لم يُحمَّل: " + bad.join(" · "));
  const png = await page.screenshot({ clip: { x: 0, y: 0, width, height } });

  // التحويل إلى WebP في المتصفح نفسه، فلا تلزم مكتبة صور
  const webp = await page.evaluate(async ([b64, q]) => {
    const img = new Image();
    img.src = "data:image/png;base64," + b64;
    await img.decode();
    const c = document.createElement("canvas");
    c.width = img.naturalWidth; c.height = img.naturalHeight;
    c.getContext("2d").drawImage(img, 0, 0);
    return c.toDataURL("image/webp", +q).split(",")[1];
  }, [png.toString("base64"), quality]);
  await browser.close();

  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, Buffer.from(webp, "base64"));
  console.log(`✓ ${out}  ${width}×${height}  ${Math.round(fs.statSync(out).size / 1024)} KB`);
})().catch((e) => { console.error(e.message || e); process.exit(1); });

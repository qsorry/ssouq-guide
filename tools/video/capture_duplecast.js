// صور فيديو Duplecast وشرحه (assets/dc_*) وصورة منتج «تفعيل Duplecast» في المتجر: يعيد رسمها من
// tv_duplecast.html ويطبع مواضع ما عليه [data-k] (بكسل الصورة) لتُطابَق بمستطيلات SCENES في duplecast.html
// وبـ shots_duplecast.js.
//
//     node tools/video/capture_duplecast.js
//
//   dc_start.webp  dc_home.webp          التلفاز 1920×1080: أول فتح (الباركود ورقم الجهاز)، والرئيسية وزر التحديث
//   dc_manage.webp dc_form.webp dc_saved.webp dc_code.webp dc_active.webp
//                                        صفحة الجهاز في duplecast.com على الجوال، بعرض 1170 (390 × 3)
//   dc_price.webp                        لا يُعاد رسمه: قسم Activation من الصفحة الرئيسية في duplecast.com كما
//                                        صُوِّر في 30 سبتمبر 2026 — مجاني 15 يومًا، و3$ للسنة، و7.5$ لثلاث سنوات
//   static/img/products/duplecast-1y.jpg صورة المنتج 1000×1000 (تُرفع إلى سلة)
const { chromium } = require('playwright-core');
const { execSync, execFileSync } = require('child_process');
const fs = require('fs'); const path = require('path'); const os = require('os');

const A = path.join(__dirname, 'assets'), ROOT = path.join(__dirname, '..', '..');
const EXE = fs.existsSync('/opt/pw-browsers/chromium/chrome-linux/chrome')
  ? '/opt/pw-browsers/chromium/chrome-linux/chrome'
  : execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim() || undefined;
const FFMPEG = process.env.FFMPEG || (() => {
  try { return execSync('python3 -c "import imageio_ffmpeg as f; print(f.get_ffmpeg_exe())"', { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim(); }
  catch (e) { return 'ffmpeg'; }
})();
// الشاشة، ومقاس نافذتها، ومضاعف البكسل
const SHOTS = [['start', 1920, 1080, 1], ['home', 1920, 1080, 1],
  ['manage', 390, 800, 3], ['form', 390, 800, 3], ['saved', 390, 800, 3], ['code', 390, 800, 3], ['active', 390, 800, 3],
  ['cover', 1000, 1000, 1]];

(async () => {
  const browser = await chromium.launch({ executablePath: EXE, args: ['--no-sandbox', '--force-color-profile=srgb'] });
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'dc-'));
  for (const [name, w, h, k] of SHOTS) {
    const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: k });
    await page.goto('file://' + path.join(__dirname, 'tv_duplecast.html') + '?screen=' + name, { waitUntil: 'load' });
    await page.evaluate(() => document.fonts.ready);
    const el = page.locator('#' + name);
    const png = path.join(tmp, name + '.png');
    await el.screenshot({ path: png });
    if (name !== 'cover') execFileSync(FFMPEG, ['-hide_banner', '-loglevel', 'error', '-y', '-i', png, '-c:v', 'libwebp', '-quality', '92', path.join(A, `dc_${name}.webp`)]);
    const box = await el.boundingBox();
    const ks = await page.$$eval('[data-k]', (els, id) => els.filter(e => e.closest('#' + id)).map(e => {
      const r = e.getBoundingClientRect(); return [e.dataset.k, r.x, r.y, r.width, r.height]; }), name);
    console.log(`${name} (${Math.round(box.width * k)}×${Math.round(box.height * k)})`);
    for (const [key, x, y, bw, bh] of ks)
      console.log(`  ${key}: [${[x - box.x, y - box.y, bw, bh].map(v => Math.round(v * k)).join(', ')}]`);
    await page.close();
  }
  execFileSync(FFMPEG, ['-hide_banner', '-loglevel', 'error', '-y', '-i', path.join(tmp, 'cover.png'), '-q:v', '2',
    path.join(ROOT, 'static', 'img', 'products', 'duplecast-1y.jpg')]);
  await browser.close();
  fs.rmSync(tmp, { recursive: true, force: true });
})();

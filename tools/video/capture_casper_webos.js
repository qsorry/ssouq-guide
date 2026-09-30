// صورتا منتجَي «اشتراك كاسبر لشاشات سامسونج و LG» في المتجر، من casper_webos_cover.html (1000×1000، تُرفعان إلى سلة):
//
//     node tools/video/capture_casper_webos.js
//
//   static/img/products/casper-12m-webos.jpg   لمدة 12 شهر (p1152389812)
//   static/img/products/casper-6m-webos.jpg    لمدة 6 أشهر (p138230620)
const { chromium } = require('playwright-core');
const { execSync, execFileSync } = require('child_process');
const fs = require('fs'); const path = require('path'); const os = require('os');

const ROOT = path.join(__dirname, '..', '..');
const EXE = fs.existsSync('/opt/pw-browsers/chromium/chrome-linux/chrome')
  ? '/opt/pw-browsers/chromium/chrome-linux/chrome'
  : execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim() || undefined;
const FFMPEG = process.env.FFMPEG || (() => {
  try { return execSync('python3 -c "import imageio_ffmpeg as f; print(f.get_ffmpeg_exe())"', { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim(); }
  catch (e) { return 'ffmpeg'; }
})();

(async () => {
  // خطوط Google (Cairo و Inter) عبر وكيل HTTPS إن وُجد. يجلبها جانب Node من Playwright (route.fetch) لا المتصفح،
  // لأن Node يثق بشهادة الوكيل (NODE_EXTRA_CA_CERTS) والمتصفح قد لا يثق بها
  const proxy = process.env.HTTPS_PROXY || process.env.https_proxy;
  const browser = await chromium.launch({ executablePath: EXE, args: ['--no-sandbox', '--force-color-profile=srgb'],
    ...(proxy ? { proxy: { server: proxy } } : {}) });
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'cw-'));
  for (const m of ['12', '6']) {
    const page = await browser.newPage({ viewport: { width: 1000, height: 1000 }, deviceScaleFactor: 1 });
    await page.route(/^https:\/\/fonts\.(googleapis|gstatic)\.com\//, async route => route.fulfill({ response: await route.fetch() }));
    await page.goto('file://' + path.join(__dirname, 'casper_webos_cover.html') + '?m=' + m, { waitUntil: 'load' });
    await page.evaluate(() => document.fonts.ready);
    const loaded = await page.evaluate(() => [...document.fonts].filter(f => f.status === 'loaded').map(f => f.family));
    if (!loaded.includes('Cairo') || !loaded.includes('Inter')) throw new Error('لم تُحمَّل خطوط Cairo و Inter');
    const png = path.join(tmp, m + '.png');
    await page.locator('#cover').screenshot({ path: png });
    const out = path.join(ROOT, 'static', 'img', 'products', `casper-${m}m-webos.jpg`);
    execFileSync(FFMPEG, ['-hide_banner', '-loglevel', 'error', '-y', '-i', png, '-q:v', '2', out]);
    console.log(path.relative(ROOT, out));
    await page.close();
  }
  await browser.close();
  fs.rmSync(tmp, { recursive: true, force: true });
})();

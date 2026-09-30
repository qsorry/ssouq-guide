// صور فيديو 0Player وشرحه (assets/0p_*): يعيد جمعها كلها إن تغيّر التطبيق أو موقعه، ويطبع مواضع
// الأزرار (بكسل الصورة) لتُطابَق بمستطيلات SCENES في 0player.html.
//
//     node tools/video/capture_0player.js
//
//   0p_home.png    الشاشة الرئيسية — الصورة الرسمية في 0player.com (مؤرّخة 2026)، مقصوصة على الشاشة
//   0p_lists.png   Choose Your Playlist — لقطة المطوّر في متجر LG (مارس 2026)، مقصوصة على الشاشة
//   0p_notice.png  أول فتح بلا قائمة، و 0p_dialog*.png شاشة Add a new playlist — من tv_0player.html
//   0p_web-<الرمز>.png و 0p_done.png و 0p_terms.png — من 0player.com نفسه على الجوال
//
// في 0player.com يُجاب كل طلب إلى واجهته (/frontend/…) محليًّا داخل المتصفح: تُرسم الصفحات بكود
// الموقع نفسه، ولا يُسجَّل جهاز ولا يُرسل شيء لخوادمهم. والكابتشا صورة من عندنا.
const { chromium } = require('playwright-core');
const { execSync, execFileSync } = require('child_process');
const fs = require('fs'); const path = require('path'); const os = require('os');

const A = path.join(__dirname, 'assets'), K = 3;
const CODES = ['92929480', '75710072', '59820658'];     // رمز بوابة سمارت، ثم فالكون، ثم كاسبر
const LG_LISTS = 'http://ngfts.lge.com/fts/gftsDownload.lge?biz_code=APP_STORE&func_code=APP_PREVIEW&file_path=/appstore/app/preview/20260312/38815515.jpg';
const EXE = fs.existsSync('/opt/pw-browsers/chromium/chrome-linux/chrome')
  ? '/opt/pw-browsers/chromium/chrome-linux/chrome'
  : execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim() || undefined;
const FFMPEG = process.env.FFMPEG || (() => {
  try { return execSync('python3 -c "import imageio_ffmpeg as f; print(f.get_ffmpeg_exe())"', { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim(); }
  catch (e) { return 'ffmpeg'; }
})();
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), '0p-'));
const get = (url, file) => { execFileSync('curl', ['-sSfL', '-m', '60', '-o', file, url]); return file; };
const crop = (src, [w, h, x, y], out) => execFileSync(FFMPEG, ['-hide_banner', '-loglevel', 'error', '-y', '-i', src, '-vf', `crop=${w}:${h}:${x}:${y}`, out]);
const CAPTCHA = '<svg xmlns="http://www.w3.org/2000/svg" width="150" height="50" viewBox="0,0,150,50"><rect width="100%" height="100%" fill="#e9ecf2"/>'
  + '<text x="18" y="35" font-family="Verdana" font-size="28" fill="#222" letter-spacing="6">K7PX4</text></svg>';

(async () => {
  // ١) الصور الرسمية: أسماء ملفات 0player.com تتغيّر مع كل نشرٍ لموقعهم، فتُقرأ من حزمته
  const site = fs.readFileSync(get('https://0player.com/', path.join(tmp, 'index.html')), 'utf8');
  const bundle = fs.readFileSync(get('https://0player.com' + site.match(/\/assets\/index-[\w-]+\.js/)[0], path.join(tmp, 'bundle.js')), 'utf8');
  const asset = re => 'https://0player.com' + bundle.match(re)[0];
  crop(get(asset(/\/assets\/simpleUi-[\w-]+\.webp/), path.join(tmp, 'home.webp')), [1674, 934, 105, 111], path.join(A, '0p_home.png'));
  crop(get(LG_LISTS, path.join(tmp, 'lists.jpg')), [1046, 592, 406, 258], path.join(A, '0p_lists.png'));
  get(asset(/\/assets\/Zero-Player-[\w-]+\.png/), path.join(A, '0p_logo.png'));

  const browser = await chromium.launch({ executablePath: EXE, args: ['--no-sandbox', '--force-color-profile=srgb'] });
  const box = async (page, sel, o = [0, 0], k = 1) => {
    const b = await page.locator(sel).first().boundingBox(), sy = await page.evaluate(() => scrollY);
    return [b.x * k - o[0], (b.y + sy) * k - o[1], b.width * k, b.height * k].map(Math.round);
  };

  { // ٢) شاشتا التلفاز المرسومتان
    const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
    const shot = async (qs, name, sels) => {
      await page.goto('file://' + path.join(__dirname, 'tv_0player.html') + qs, { waitUntil: 'networkidle' });
      await page.evaluate(() => document.fonts.ready);
      await page.screenshot({ path: path.join(A, name) });
      const out = {}; for (const [k, s] of Object.entries(sels)) out[k] = await box(page, s);
      console.log(name, JSON.stringify(out));
    };
    await shot('?screen=notice', '0p_notice.png', { reload: '#bReload', go: '#bGo', box: '#notice .box' });
    const f = { portal: '#tPortal', name: '#fName', code: '#fCode', user: '#fUser', pass: '#fPass', save: '#save', qr: '#qr', scan: '#scan' };
    await shot('?screen=dialog', '0p_dialog.png', f);
    for (const c of CODES) await shot(`?screen=dialog&fill=1&code=${c}`, `0p_dialog-${c}.png`, {});
    await page.close();
  }

  { // ٣) 0player.com على الجوال، وكل طلبٍ لواجهتهم يُجاب هنا
    const ctx = await browser.newContext({ viewport: { width: 390, height: 1200 }, deviceScaleFactor: K, isMobile: true, hasTouch: true,
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1' });
    await ctx.route('**/frontend/**', r => r.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify(/captcha/.test(r.request().url()) ? { svg: CAPTCHA, token: 'local' } : { status: 'success', msg: 'ok' }) }));
    await ctx.route(/cloudflareinsights|cdn-cgi\/rum/, r => r.abort());
    const page = await ctx.newPage();
    // ما يفتحه الباركود: رقم الجهاز في الرابط، ونوع القائمة
    await page.goto('https://0player.com/qr-playlist?mac_address=00:00:00:00:00:00&type=portal_code', { waitUntil: 'networkidle', timeout: 60000 });
    await page.waitForTimeout(1200);
    // نافذة الشروط: أقرب أبٍ أبيض لزرّ القبول
    const modal = (await page.evaluate(() => {
      let el = [...document.querySelectorAll('button')].find(b => /Accept legal terms/.test(b.textContent));
      while (el && getComputedStyle(el).backgroundColor !== 'rgb(255, 255, 255)') el = el.parentElement;
      const r = el.getBoundingClientRect(); return [r.x, r.y, r.width, r.height];
    })).map(v => Math.round(v * K));
    await page.screenshot({ path: path.join(tmp, 'terms.png') });
    // هامشٌ حول النافذة، داخل حدود لقطة الشاشة (390×1200 بدقة 3×)
    const fit = ([x, y, w, h]) => { const X = Math.max(0, x), Y = Math.max(0, y); return [X, Y, Math.min(w, 390 * K - X), Math.min(h, 1200 * K - Y)]; };
    const mo = fit([modal[0] - 12, modal[1] - 12, modal[2] + 24, modal[3] + 24]);
    crop(path.join(tmp, 'terms.png'), [mo[2], mo[3], mo[0], mo[1]], path.join(A, '0p_terms.png'));
    console.log('0p_terms.png', JSON.stringify({ accept: (await box(page, 'button:has-text("Accept legal terms")', [mo[0], mo[1]], K)) }));
    await page.click('button:has-text("Accept legal terms")'); await page.waitForTimeout(900);
    for (const c of CODES) {
      await page.fill('#portal-code-name', 'ssouq'); await page.fill('#portal-code-code', c);
      await page.fill('#portal-code-username', 'USERNAME'); await page.fill('#portal-code-password', 'PASSWORD');
      await page.fill('input[placeholder="Enter captcha"]', 'K7PX4');
      await page.evaluate(() => { document.activeElement.blur(); getSelection().removeAllRanges(); scrollTo(0, 0); });
      await page.waitForTimeout(400);
      const top = await box(page, 'h2:has-text("Add Your Playlist")', [0, 0], K), add = await box(page, 'button:has-text("ADD PLAYLIST")', [0, 0], K);
      const o = [60, top[1] - 70], size = [1170 - 120, add[1] + add[3] + 70 - o[1]];
      await page.screenshot({ path: path.join(tmp, 'form.png'), fullPage: true });
      crop(path.join(tmp, 'form.png'), [size[0], size[1], o[0], o[1]], path.join(A, `0p_web-${c}.png`));
      const out = {};
      for (const [k, s] of Object.entries({ tab: 'button:has-text("Portal Code")', name: '#portal-code-name', code: '#portal-code-code', user: '#portal-code-username',
        pass: '#portal-code-password', captcha: 'input[placeholder="Enter captcha"]', add: 'button:has-text("ADD PLAYLIST")' })) out[k] = await box(page, s, o, K);
      console.log(`0p_web-${c}.png`, JSON.stringify(out));
    }
    await page.click('button:has-text("ADD PLAYLIST")'); await page.waitForTimeout(2500);
    const pop = await box(page, '.swal2-popup', [0, 0], K);
    await page.screenshot({ path: path.join(tmp, 'done.png') });
    const po = fit([pop[0] - 12, pop[1] - 12, pop[2] + 24, pop[3] + 24]);
    crop(path.join(tmp, 'done.png'), [po[2], po[3], po[0], po[1]], path.join(A, '0p_done.png'));
    // العنوان نصًّا لا سطرًا كاملًا: حلقةٌ على «Playlist Added!» وحدها
    const title = (await page.evaluate(() => { const r = document.createRange(); r.selectNodeContents(document.querySelector('.swal2-title'));
      const b = r.getBoundingClientRect(); return [b.x, b.y + scrollY, b.width, b.height]; })).map(v => Math.round(v * K));
    console.log('0p_done.png', JSON.stringify({ title: [title[0] - po[0], title[1] - po[1], title[2], title[3]] }));
    await ctx.close();
  }
  await browser.close();
  // المخزَّن WebP لا PNG (أصغر بكثير، والفيديو مضغوطٌ بعده أصلًا) — إلا الشعار: تقرؤه tv_0player.html
  for (const f of fs.readdirSync(A).filter(f => /^0p_.*\.png$/.test(f) && f !== '0p_logo.png')) {
    execFileSync(FFMPEG, ['-hide_banner', '-loglevel', 'error', '-y', '-i', path.join(A, f), '-c:v', 'libwebp', '-quality', '90', path.join(A, f.replace(/\.png$/, '.webp'))]);
    fs.unlinkSync(path.join(A, f));
  }
  fs.rmSync(tmp, { recursive: true, force: true });
})();

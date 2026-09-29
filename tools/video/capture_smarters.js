// صور فيديو IPTV Smarters Pro على شاشة أندرويد وشرحه (assets/dl_* و assets/sm_*): يعيد جمعها كلها، ويطبع مواضع
// الأزرار (بكسل الصورة) لتُطابَق بمستطيلات B في smarters.html وفي shots_smarters.js.
//
//     node tools/video/capture_smarters.js
//
//   الرسمية كما هي:
//     dl_icon.png     أيقونة Downloader من صفحته في Google Play
//     dl_welcome      أول فتح لـ Downloader 2.0 على التلفاز (Welcome… وزر OK) — من لقطات صفحته في Google Play
//     dl_home         الشاشة الرئيسية وزر # بجانب خانة العنوان — من اللقطات نفسها
//     dl_numpad       لوحة أرقام # للأكواد — من مقال AFTVnews عن Downloader 2.0 (مارس 2026)، أصلٌ لـ dl_code-*
//   ورسوم IPTV Smarters Pro 3.1.5 من ملف التطبيق نفسه (الذي يحمّله كود 8744201) — sm_*.png:
//     أسماء الملفات داخله مختصرة مموّهة (res/UGG.png…)، والمقابل في SM_RES كما قرأته androguard من resources.arsc
//   والمرسومة في tv_smarters.html (شاشات النظام بالعربية، وشاشات التطبيق بتخطيطاته):
//     dl_play، dl_code-<الكود>، dl_blocked، dl_allow و dl_allow-off، dl_install-<التطبيق> و dl_done-<التطبيق>،
//     dl_devmode، sm_device، sm_terms، sm_route، sm_login و sm_login-fill
const { chromium } = require('playwright-core');
const { execSync, execFileSync } = require('child_process');
const fs = require('fs'); const path = require('path'); const os = require('os');

const A = path.join(__dirname, 'assets');
const APK = 'https://ssouq.net/iptvsmarters/IPTV-Smarters-Pro3.1.apk';
const PLAY = 'https://play-lh.googleusercontent.com/';
const OFFICIAL = {
  'dl_icon.png': PLAY + '_zuxP30plNbEBOOre6Q4rVwGQslOX6NCsefA8tPxJFsFt2XLO35yK2YVaPqmFl0oGVnO9FZCJ6b2lhrSk3a0KA=s512',
  'dl_welcome.png': PLAY + 'BPu6QRx774Xv6Eszo64eXjXcmX-4kM05ADeeIun32Pblj5LOZN2Tu1d5q7_m_3tjFO6fYYmVHjMRz0R7o1Sp-Q=w1920',
  'dl_home.png': PLAY + 'p2IghtppCBhk4ACwTsk_a0S05YCU1DMZsLHMcDvG8UDdvVrg4xc5YSMSEe81t6pTwU5u6YoddJEbc_AVIFLN=w1920',
  'dl_numpad.png': 'https://www.aftvnews.com/wp-content/uploads/2026/03/Number-Pad-option-in-Downloader-v2-for-Short-Codes.png'
};
const SM_RES = {
  'sm_icon.png': 'res/CGK.png',          // mipmap/ic_launcher (xxxhdpi)
  'sm_logo.png': 'res/WdN.png',          // drawable/logo (xxhdpi)
  'sm_logo_long.png': 'res/bjI.png',     // drawable/logo_white_long
  'sm_box.png': 'res/UGG.png',           // drawable/box_unfocused
  'sm_box_on.png': 'res/G8u.png',        // drawable/box_focused
  'sm_btn.png': 'res/G-3.png',           // drawable/login_btn_unfocused
  'sm_btn_on.png': 'res/prt.png',        // drawable/login_btn_focused
  'sm_btn_dark.png': 'res/M8E.png',      // drawable/black_button_dark
  'sm_ic_m3u.png': 'res/61c.png',        // drawable/icon1_unfocused
  'sm_ic_xtream_on.png': 'res/8JG.png',  // drawable/icon3_focused
  'sm_arrow.png': 'res/JpY.png',         // drawable/black_arrow_right
  'sm_arrow_on.png': 'res/Egm.png',      // drawable/white_arrow_right
  'sm_ic_vpn.png': 'res/KIf.png',        // drawable/login_icon1_unfocused
  'sm_ic_users.png': 'res/7jC.png',      // drawable/login_icon2_unfocused
  'sm_check.png': 'res/sg3.png',         // drawable/white_check
  'sm_cross.png': 'res/Dku.png'          // drawable/white_cross
};
// أكواد Downloader في الدليل، والتطبيقات التي تُثبَّت بها (أسماؤها في tv_smarters.html)
const CODES = ['8744201', '5574841', '1683248', '3638997'];
const APPS = ['smarters', 'mr7', 'falcon', 'casper'];
// زر # في رأس Downloader (dl_home و dl_numpad)، و OK في dl_welcome — بكسل اللقطات الرسمية
const FIXED = { dl_home: { hash: [1642, 4, 112, 112] }, dl_welcome: { ok: [512, 784, 896, 76], dialog: [464, 180, 991, 719] } };

const EXE = fs.existsSync('/opt/pw-browsers/chromium/chrome-linux/chrome')
  ? '/opt/pw-browsers/chromium/chrome-linux/chrome'
  : execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim() || undefined;
const FFMPEG = process.env.FFMPEG || (() => {
  try { return execSync('python3 -c "import imageio_ffmpeg as f; print(f.get_ffmpeg_exe())"', { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim(); }
  catch (e) { return 'ffmpeg'; }
})();
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'sm-'));
const get = (url, file) => { execFileSync('curl', ['-sSfL', '-m', '300', '-o', file, url]); return file; };
const webp = (src, out, q = 90) => execFileSync(FFMPEG, ['-hide_banner', '-loglevel', 'error', '-y', '-i', src, '-c:v', 'libwebp', '-quality', String(q), out]);

(async () => {
  // ١) الرسمية: الأيقونة كما هي، واللقطات WebP
  for (const [f, url] of Object.entries(OFFICIAL)) {
    if (f === 'dl_icon.png') { get(url, path.join(A, f)); continue; }
    webp(get(url, path.join(tmp, f)), path.join(A, f.replace(/\.png$/, '.webp')));
  }
  console.log('dl_home.webp', JSON.stringify(FIXED.dl_home), '\ndl_welcome.webp', JSON.stringify(FIXED.dl_welcome));

  // ٢) رسوم التطبيق من ملفه (unzip)
  const apk = get(APK, path.join(tmp, 'smarters.apk'));
  for (const [f, entry] of Object.entries(SM_RES)) fs.writeFileSync(path.join(A, f), execFileSync('unzip', ['-p', apk, entry], { maxBuffer: 1 << 26 }));

  // ٣) الشاشات المرسومة
  const browser = await chromium.launch({ executablePath: EXE, args: ['--no-sandbox', '--force-color-profile=srgb'] });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  page.on('pageerror', e => { console.error('pageerror', e.message); process.exitCode = 1; });
  const shot = async (qs, name, sels) => {
    await page.goto('file://' + path.join(__dirname, 'tv_smarters.html') + '?' + qs, { waitUntil: 'networkidle' });
    await page.evaluate(() => document.fonts.ready); await page.waitForTimeout(150);
    const png = path.join(tmp, name + '.png'); await page.screenshot({ path: png });
    webp(png, path.join(A, name + '.webp'));
    const out = {}; for (const [k, s] of Object.entries(sels)) out[k] = await page.evaluate(s => box(s), s);
    console.log(name + '.webp', JSON.stringify(out));
  };
  await shot('screen=play', 'dl_play', { install: '#pInstall', title: '#play h1', banner: '#pBanner' });
  for (const c of CODES) await shot(`screen=code&code=${c}`, `dl_code-${c}`, c === CODES[0] ? { code: '#codeTxt', load: '#load' } : {});
  await shot('screen=blocked', 'dl_blocked', { dialog: '#bDlg', settings: '#bSettings', cancel: '#bCancel' });
  await shot('screen=allow&on=0', 'dl_allow-off', { row: '#aRow', sw: '#aSw' });
  await shot('screen=allow', 'dl_allow', { row: '#aRow', sw: '#aSw', title: '#allow h1' });
  for (const a of APPS) await shot(`screen=install&app=${a}`, `dl_install-${a}`, a === APPS[0] ? { dialog: '#iDlg', install: '#iInstall' } : {});
  for (const a of APPS) await shot(`screen=done&app=${a}`, `dl_done-${a}`, a === APPS[0] ? { dialog: '#dDlg', open: '#dOpen' } : {});
  await shot('screen=devmode', 'dl_devmode', { build: '#vBuild', toast: '#toast' });
  await shot('screen=device', 'sm_device', { card: '#device .shade', tv: '#rTV', save: '#save' });
  await shot('screen=terms', 'sm_terms', { accept: '#tAccept', bar: '#terms .bar' });
  await shot('screen=route', 'sm_route', { m3u: '#rM3u', xtream: '#rXtream' });
  await shot('screen=login', 'sm_login', {});
  await shot('screen=login&fill=1', 'sm_login-fill', { title: '#login h2', name: '#fName', user: '#fUser', pass: '#fPass', eye: '#eye', url: '#fUrl', add: '#addUser', users: '#lUsers' });
  await browser.close();
  fs.rmSync(tmp, { recursive: true, force: true });
})();

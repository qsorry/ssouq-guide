// يعيد التقاط صور الجوال التي يبني منها video.html مشاهده (assets/a_*.png) بدقة 3× — إن تغيّر
// محرّر القوائم في ss-iptv.com أو أداة M3U في الدليل. ويطبع مواضع الأزرار (بكسل الصورة بعد القصّ)
// لتُقارن بمستطيلات SCENES في video.html وتُصحَّح إن تحرّكت.
//
//     python3 xm_lines.py web                        # الدليل محليًّا لأداة M3U (المنفذ 8080)
//     node tools/video_ssiptv/capture.js [http://127.0.0.1:8080]
//
// في ss-iptv.com يُستبدل جسر الجهاز (ssiptv.bridge) بردود محلية داخل الصفحة: تُرسم حالات الربط
// والإضافة والحفظ بكود الموقع نفسه، فلا جهاز يُسجَّل ولا يُرسل شيء لخوادمهم. ولقطتا التلفاز
// (a_tvhome.jpg و a_tvset.jpg) من صفحة التطبيق في متجر VIDAA كما رفعها فريق SS IPTV.
const { chromium } = require('playwright-core');
const { execSync } = require('child_process');
const fs = require('fs'); const path = require('path');

const GUIDE = process.argv[2] || 'http://127.0.0.1:8080';
const A = path.join(__dirname, 'assets'), K = 3;
const EXE = fs.existsSync('/opt/pw-browsers/chromium/chrome-linux/chrome')
  ? '/opt/pw-browsers/chromium/chrome-linux/chrome'
  : execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim() || undefined;

(async () => {
  const browser = await chromium.launch({ executablePath: EXE, args: ['--no-sandbox'] });
  const phone = () => browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: K, isMobile: true, hasTouch: true,
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1' });
  // لقطة قصّ من الصفحة كاملة: y و h ببكسل الصورة (3×)، والمواضع المطبوعة نسبةً إلى أعلى القصّ
  const grab = async (page, name, y, h, sels) => {
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: path.join(A, name), fullPage: true, clip: { x: 0, y: y / K, width: 390, height: h / K } });
    const out = {};
    for (const [k, s] of Object.entries(sels)) {
      const b = await page.locator(s).first().boundingBox(), sy = await page.evaluate(() => window.scrollY);
      out[k] = b && [b.x * K, (b.y + sy) * K - y, b.width * K, b.height * K].map(Math.round);
    }
    console.log(name, JSON.stringify(out));
  };

  { // أداة M3U في الدليل
    const page = await (await phone()).newPage();
    await page.goto(GUIDE + '/#m3u', { waitUntil: 'networkidle' });
    await page.addStyleTag({ content: 'header,.top,#top{position:static!important} #m3u-count{display:none!important}' });
    await page.fill('#m3u-host', 'http://host.com:8080'); await page.fill('#m3u-user', 'USER'); await page.fill('#m3u-pass', 'PASS');
    await page.click('#m3u-form button[type=submit]'); await page.waitForTimeout(500);
    await page.evaluate(() => { document.activeElement.blur(); getSelection().removeAllRanges();
      const l = document.querySelector('#m3u-link'); l.setSelectionRange(0, 0); l.scrollLeft = 0; });
    await grab(page, 'a_m3u.png', 200, 2660, { host: '#m3u-host', user: '#m3u-user', pass: '#m3u-pass',
      gen: '#m3u-form button[type=submit]', link: '#m3u-link', copy: '#m3u-copy' });
  }
  { // محرّر القوائم في ss-iptv.com
    const page = await (await phone()).newPage();
    await page.goto('https://ss-iptv.com/en/users/playlist', { waitUntil: 'networkidle', timeout: 60000 });
    const agree = page.locator('text=Agree').first(); if (await agree.count()) await agree.click().catch(() => {});
    await page.evaluate(() => { const B = ssiptv.bridge;
      B.getDevices = cb => cb({ list: [{ id: 1, name: 'TV', group: '', model: '' }] }); B.getCurrent = cb => cb({ id: 1 });
      B.getContent = (id, t, cb) => cb({ list: [{ list: [] }] }); B.setContent = (id, t, c, cb) => setTimeout(() => cb({}), 150);
      B.getAccess = (code, cb) => cb({ present: false, deviceId: 1 }); });
    await grab(page, 'a_code.png', 0, 1330, { input: '#inptConnectionCodeInput', add: '#btnAddDevice' });
    await page.click('#btnAddDevice'); await page.waitForTimeout(900); await page.click('#playlistsTab'); await page.waitForTimeout(900);
    // من تحت خانة الرمز: اسم الجهاز فوقها اسمٌ وهميّ من الردود المحلية فلا يظهر
    await grab(page, 'a_tab.png', 1075, 700, { tab: '#playlistsTab', addItem: '#btnAddPlaylistItem', save: '#btnSave' });
    await page.click('#btnAddPlaylistItem'); await page.waitForTimeout(900);
    await page.fill('#inputStreamTitle', 'ssouq');
    await page.fill('#inputStreamURL', 'http://host.com:8080/get.php?username=USER&password=PASS&type=m3u_plus&output=ts');
    await page.evaluate(() => { const el = document.querySelector('#inputStreamURL'); el.setSelectionRange(0, 0); el.scrollLeft = 0; el.blur(); });
    await grab(page, 'a_item.png', 0, 2340, { name: '#inputStreamTitle', src: '#inputStreamURL', ok: '#btnApplyChanges' });
    await page.click('#btnApplyChanges'); await page.waitForTimeout(700); await page.click('#btnSave'); await page.waitForTimeout(900);
    await grab(page, 'a_saved.png', 1075, 1110, { save: '#btnSave', row: '#listRenderer tr' });
  }
  await browser.close();
})();

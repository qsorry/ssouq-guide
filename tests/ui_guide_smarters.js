// Browser test: IPTV Smarters Pro on an Android TV/box, and the Downloader approval every TV app shares.
// Smarters: ten steps — Downloader from Google Play (with the video), OK on first open, # and code 8744201, the
// security message → «الإعدادات», allow Downloader, «تثبيت» then «فتح», then Smarters' own first run: TV + «حفظ»,
// «قبول», XTREAM CODES API, and the login (Any Name / Username / Password / URL → «إضافة مستخدم» / ADD USER).
// MR7, Falcon and CASPER VIP use the same Downloader steps with their own code and app name. Every image loads.
const { chromium } = require('playwright-core');
const { spawn, execSync } = require('child_process');
const path = require('path'); const fs = require('fs'); const os = require('os');
const ROOT = path.dirname(__dirname);
const APP_PORT = 9836;
const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'guide_smarters_'));
const EXE = fs.existsSync('/opt/pw-browsers/chromium/chrome-linux/chrome')
  ? '/opt/pw-browsers/chromium/chrome-linux/chrome'
  : execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim();
let pass = 0, fail = 0;
const check = (l, c, x='') => { c ? (pass++, console.log(`  PASS  ${l}${x?'  ('+x+')':''}`)) : (fail++, console.log(`  FAIL  ${l}${x?'  ('+x+')':''}`)); };
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function up(u){ for (let i=0;i<80;i++){ try { execSync(`curl -s -o /dev/null ${u}`); return; } catch(e){} await sleep(150); } }

(async () => {
  const app = spawn('python3', [path.join(ROOT,'xm_lines.py'), 'web'],
    {stdio:'ignore', env:{...process.env, XM_DATA:dataDir, XM_BIND:'127.0.0.1', XM_PORT:String(APP_PORT)}});
  const APP = `http://127.0.0.1:${APP_PORT}`;
  await up(APP + '/');
  const browser = await chromium.launch({executablePath: EXE, args:['--no-sandbox']});
  const page = await (await browser.newContext({viewport:{width:390, height:844}})).newPage();
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  const open = async hash => { await page.goto(APP + '/' + hash); await page.waitForSelector('#view .card'); };
  const h2 = () => page.$eval('#view h2', e => e.textContent.trim());
  const sub = () => page.$eval('#view .card.step > .sub', e => e.textContent);
  const img = () => page.$eval('#view .card.step > img', i => i.getAttribute('src')).catch(() => null);
  const text = () => page.textContent('#view');
  const next = async () => { await page.click('#view [data-next]'); await page.waitForSelector('#view .card'); };
  const brokenImgs = () => page.evaluate(async () => {
    const im = [...document.querySelectorAll('#view img')];
    im.forEach(i => { i.loading = 'eager'; });
    await Promise.race([Promise.all(im.map(i => i.complete ? 0 : new Promise(r => { i.onload = i.onerror = r; }))),
                        new Promise(r => setTimeout(r, 8000))]);
    return im.filter(i => !i.naturalWidth).map(i => i.getAttribute('src'));
  });
  try {
    console.log('== Smart: IPTV Smarters Pro on the TV ==');
    await open('#activate/smart/tv');
    await page.click('[data-variant="smarters"]'); await page.waitForSelector('#view .card');
    const broken = [];
    const STEPS = [
      ['حمّل تطبيق Downloader من Google Play', '/static/img/tv-dl-play.webp', ['Downloader by AFTVnews', 'AFTVnews', 'تثبيت']],
      ['افتح Downloader واضغط OK', '/static/img/tv-dl-welcome.webp', ['Welcome to Downloader', 'سماح']],
      ['اضغط # واكتب الكود 8744201', '/static/img/tv-dl-code-8744201.webp', ['Load', 'Go', '84 ميغابايت']],
      ['ظهرت رسالة الأمان؟ اضغط «الإعدادات»', '/static/img/tv-dl-blocked.webp',
        ['لأغراض الأمان، غير مسموح حاليًا لجهاز التلفزيون الذي تستخدمه بتثبيت تطبيقات غير معروفة من هذا المصدر', 'مرة واحدة فقط', 'Settings',
         'Google TV', 'إصدار نظام تشغيل Android TV', 'لقد أصبحت الآن مطور برامج!']],
      ['فعّل Downloader ثم ارجع', '/static/img/tv-dl-allow.webp', ['تثبيت التطبيقات غير المعروفة', 'Install unknown apps', 'تطبيق مسموح به', 'الرجوع', 'مصادر غير معروفة']],
      ['اضغط «تثبيت» ثم «فتح»', '/static/img/tv-dl-install-smarters.webp', ['هل تريد تثبيت هذا التطبيق؟', 'تم تثبيت التطبيق.', 'Play Protect', 'IPTV Smarters Pro']],
      ['اختر TV ثم «حفظ»', '/static/img/tv-smarters-device.webp', ['Device Option', 'SAVE']],
      ['اضغط «قبول» أسفل الشروط', '/static/img/tv-smarters-terms.webp', ['LICENSE AGREEMENT', 'ACCEPT']],
      ['اختر XTREAM CODES API', '/static/img/tv-smarters-route.webp', ['LOGIN WITH XTREAM CODES API', 'M3U']],
      ['أدخل بيانات الاشتراك ثم «إضافة مستخدم»', '/static/img/smarters-pro-login.webp',
        ['Any Name', 'Username', 'Password', 'http://url_here.com:port', 'ADD USER', 'إضافة مستخدم', 'https']]
    ];
    for (const [k, [title, src, words]] of STEPS.entries()) {
      const t = await text();
      const missing = words.filter(w => !t.includes(w));
      check(`step ${k + 1}: ${title}`, (await h2()) === title && (await sub()).includes(`الخطوة ${k + 1} من 10`) && (await img()) === src && !missing.length,
        missing.join(', ') || (await h2()));
      broken.push(...await brokenImgs());
      if (k === 0) {
        const vid = await page.$eval('#view .vid video', v => ({ src: v.getAttribute('src'), poster: v.getAttribute('poster'), pre: v.getAttribute('preload') }));
        check('… the video heads the first step', vid.src === '/static/video/smarters-tv-ar.mp4?v=1' && vid.poster === '/static/video/smarters-tv-ar.webp?v=1' && vid.pre === 'none', JSON.stringify(vid));
        const served = await page.evaluate(async v => { const r = await fetch(v.src, { headers: { Range: 'bytes=0-1' } }); const p = await fetch(v.poster);
          return [r.status, r.headers.get('content-type'), p.status]; }, vid);
        check('… served in byte ranges, poster too', served[0] === 206 && served[1] === 'video/mp4' && served[2] === 200, served.join(' '));
      }
      if (k === 2) check('… the code is copyable', (await page.getAttribute('#view [data-copy]', 'data-copy')) === '8744201');
      if (k === 5) check('… and «فتح» shown inline for this app', (await page.$$eval('#view .card.step img', a => a.map(i => i.getAttribute('src')))).includes('/static/img/tv-dl-done-smarters.webp'));
      await next();
    }
    check('then the done screen', (await h2()) === 'استمتع بالمشاهدة!');
    check('every image on the way loads', !broken.length, broken.join(', '));
    const all = await page.evaluate(() => JSON.stringify(DEVICES.tv.variants.smarters));
    check('no old approval photos or banner left', !/smarters-tv-install|tv-downloader|ADD PLAYLIST|Playlist Name/.test(all));

    console.log('== the same Downloader approval for MR7, Falcon and CASPER VIP ==');
    for (const [sub_, v, code, key, name, last] of [['smart', 'mr7', '5574841', 'mr7', 'MR7 TV', 'سجّل الدخول'],
        ['falcon', 'falconapp', '1683248', 'falcon', 'FALCON IPTV PRO', null], ['casper', 'caspervip', '3638997', 'casper', 'Casper VIP', null]]) {
      await open(`#activate/${sub_}/tv/${v}/3`);
      check(`${sub_}/${v}: step 3 is its own code, 3 of 7`, (await h2()) === `اضغط # واكتب الكود ${code}` && (await sub()).includes('الخطوة 3 من 7')
        && (await img()) === `/static/img/tv-dl-code-${code}.webp` && (await page.getAttribute('#view [data-copy]', 'data-copy')) === code);
      await open(`#activate/${sub_}/tv/${v}/4`);
      check('… then the security message → «الإعدادات»', (await h2()) === 'ظهرت رسالة الأمان؟ اضغط «الإعدادات»' && (await img()) === '/static/img/tv-dl-blocked.webp');
      await open(`#activate/${sub_}/tv/${v}/5`);
      check('… allow Downloader', (await h2()) === 'فعّل Downloader ثم ارجع');
      await open(`#activate/${sub_}/tv/${v}/6`);
      const t = await text();
      check(`… «تثبيت» and «فتح» with the app's own name (${name})`, (await img()) === `/static/img/tv-dl-install-${key}.webp` && t.includes(name)
        && (await page.$$eval('#view .card.step img', a => a.map(i => i.getAttribute('src')))).includes(`/static/img/tv-dl-done-${key}.webp`));
      const b2 = await brokenImgs();
      check('… its images load', !b2.length, b2.join(', '));
      await open(`#activate/${sub_}/tv/${v}/7`);
      check('… and its own login last', last ? (await h2()) === last : (await sub()).includes('الخطوة 7 من 7'), await h2());
    }
    const shared = await page.evaluate(() => [FALCON.tv.variants.smarters === DEVICES.tv.variants.smarters, CASPER.tv.variants.smarters === DEVICES.tv.variants.smarters]);
    check("Falcon's and Casper's TVs share Smart's Smarters steps", shared.every(Boolean), shared.join());

    console.log('== the phone shares the corrected login ==');
    await open('#activate/smart/android/smarters/3');
    check('Android phone: same login step and image (ADD USER, not ADD PLAYLIST)', (await h2()) === 'أدخل بيانات الاشتراك ثم «إضافة مستخدم»'
      && (await img()) === '/static/img/smarters-pro-login.webp' && !(await text()).includes('ADD PLAYLIST'));

    await page.goto(APP + '/android-tv');
    const html = await page.content();
    check('static /android-tv: the approval steps and the video', html.includes('الخطوة 4 — ظهرت رسالة الأمان؟ اضغط «الإعدادات»')
      && html.includes('الخطوة 5 — فعّل Downloader ثم ارجع') && html.includes('/static/video/smarters-tv-ar.mp4') && html.includes('tv-dl-install-smarters.webp'));
    check('no page errors', !errors.length, errors.join(' | ').slice(0, 160));
  } catch (e) { fail++; console.log('  FAIL  exception:', e.message); }
  finally {
    await browser.close(); app.kill();
    fs.rmSync(dataDir, {recursive: true, force: true});
  }
  console.log(`\nResult: ${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();

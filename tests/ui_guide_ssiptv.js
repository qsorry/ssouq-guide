// Browser test: SS IPTV in the activation guide, for every subscription. The new VIDAA device
// walks all seven steps to the done screen with every image loaded; Samsung/LG asks for the app
// (0Player or Duplecast, and SS IPTV); Falcon keeps its own 0Player portal code; old links still open.
const { chromium } = require('playwright-core');
const { spawn, execSync } = require('child_process');
const path = require('path'); const fs = require('fs'); const os = require('os');
const ROOT = path.dirname(__dirname);
const APP_PORT = 9762;
const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'guide_ssiptv_'));
const SHOTS = process.env.SHOTS_DIR || '';
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
  // الصور كسولة التحميل: نطلبها كلها ثم نتحقّق أن كل واحدة وصلت
  const brokenImgs = () => page.evaluate(async () => {
    const im = [...document.querySelectorAll('#view img')];
    im.forEach(i => { i.loading = 'eager'; });
    await Promise.race([Promise.all(im.map(i => i.complete ? 0 : new Promise(r => { i.onload = i.onerror = r; }))),
                        new Promise(r => setTimeout(r, 8000))]);
    return im.filter(i => !i.naturalWidth).map(i => i.getAttribute('src'));
  });
  try {
    for (const sub of ['smart', 'falcon', 'casper']) {
      console.log(`== ${sub} ==`);
      await open(`#activate/${sub}`);
      const devs = await page.$$eval('#view .dev b', b => b.map(x => x.textContent));
      check('VIDAA in the device grid, right after Samsung/LG',
        devs.indexOf('هايسنس و VIDAA OS') === devs.indexOf('سامسونج و LG و WebOS') + 1, devs.join(' | '));

      await open(`#activate/${sub}/vidaa`);
      const titles = [], broken = [];
      for (let i = 0; i < 7; i++) {
        titles.push(await h2());
        broken.push(...await brokenImgs());
        if (SHOTS && sub === 'smart') await page.screenshot({path: path.join(SHOTS, `ssiptv-vidaa-${i + 1}.png`), fullPage: true});
        await page.click('[data-next]');
        await page.waitForSelector('#view .card');
      }
      check('VIDAA: seven SS IPTV steps', titles[0] === 'حمّل تطبيق SS IPTV من متجر VIDAA' && titles[6] === 'افتح قائمتك على الشاشة', titles.join(' → '));
      check('VIDAA: every step image loads', !broken.length, broken.join(', '));
      check('VIDAA: ends on the done screen', (await h2()) === 'استمتع بالمشاهدة!' && new URL(page.url()).hash === `#activate/${sub}/vidaa/8`);

      await open(`#activate/${sub}/webos`);
      const apps = await page.$$eval('#view .pick b', b => b.map(x => x.textContent));
      check('Samsung/LG asks for the app', apps.join('|') === (sub === 'casper' ? 'Duplecast|SS IPTV' : '0Player|SS IPTV'), apps.join('|'));
      await page.click('[data-variant="ssiptv"]');
      await page.waitForSelector('#view .card.step');
      check('Samsung/LG → SS IPTV: its install step (LG store, Samsung USB)',
        (await h2()) === 'حمّل تطبيق SS IPTV' && (await page.textContent('#view')).includes('userwidget'));
      check('… with the same steps after it', (await page.textContent('#view .card.step .sub')).includes('الخطوة 1 من 7'));
    }

    console.log('== links and codes ==');
    await open('#activate/smart/vidaa/2');
    check('M3U step opens the M3U tool in a new tab',
      (await page.$eval('#view a.btn.go', a => a.getAttribute('href') + ' ' + a.target)) === '/#m3u _blank');
    await open('#activate/smart/vidaa/4');
    check('connect step opens the SS IPTV playlist editor',
      (await page.$eval('#view a.btn.go', a => a.href)) === 'https://ss-iptv.com/en/users/playlist');
    await open('#activate/falcon/webos/0player/2');
    const fal = await page.textContent('#view');
    check("Falcon's 0Player keeps its own portal code", fal.includes('75710072') && !fal.includes('92929480'));
    check('… and its own portal image', (await page.$$eval('#view img', im => im.map(i => i.getAttribute('src')))).includes('/static/img/webos-0player-portal-75710072.webp'));
    await open('#activate/smart/webos/0player/2');
    check("Smart's 0Player code unchanged", (await page.textContent('#view')).includes('92929480'));
    await open('#activate/casper/webos/duplecast/3');
    check("Casper's Duplecast steps unchanged", (await h2()) === 'عبّئ بياناتك في تبويب Xtream Info');
    await open('#webos');
    check('old #webos link opens the app choice', new URL(page.url()).hash === '#activate/smart/webos' && (await h2()) === 'اختر التطبيق');

    await open('#activate/casper/webos/ssiptv/7');
    await page.click('[data-next]');
    await page.waitForSelector('#view a.btn.wa');
    const wa = decodeURIComponent((await page.getAttribute('#view a.btn.wa', 'href')).split('text=')[1]);
    check('support message names the device and the app', wa.includes('نوع الجهاز: سامسونج و LG و WebOS') && wa.includes('التطبيق: SS IPTV'), wa.split('\n').slice(1, 4).join(' / '));

    for (const p of ['/vidaa', '/samsung-lg']) {
      await page.goto(APP + p);
      const n = (await page.$$('section.step')).length;
      check(`static ${p} renders the SS IPTV steps`, (await page.content()).includes('Get code') && n >= 7, `${n} steps`);
    }
    check('no page errors', !errors.length, errors.join(' | ').slice(0, 120));
  } catch (e) { fail++; console.log('  FAIL  exception:', e.message); }
  finally {
    await browser.close(); app.kill();
    fs.rmSync(dataDir, {recursive: true, force: true});
  }
  console.log(`\nResult: ${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();

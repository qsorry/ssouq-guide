// Browser test: SS IPTV in the activation guide, for Smart and Falcon. The VIDAA device walks all
// seven steps to the done screen with every image loaded; Samsung/LG asks for the app (0Player or
// SS IPTV); Falcon keeps its own 0Player portal code; old links still open. Casper does not run on
// Samsung/LG or VIDAA, as its product pages in the store say, so those two say just that and open
// Smart's plans for that TV. And the buy path: VIDAA gets the Samsung/LG plans and Smart first.
const { chromium } = require('playwright-core');
const { spawn, execSync } = require('child_process');
const path = require('path'); const fs = require('fs'); const os = require('os');
const ROOT = path.dirname(__dirname);
const APP_PORT = 9831;             // 9762 هو خادم جوجل الوهمي في test_analytics.py
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
    for (const sub of ['smart', 'falcon']) {
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
      check('Samsung/LG asks for the app', apps.join('|') === '0Player|SS IPTV', apps.join('|'));
      await page.click('[data-variant="ssiptv"]');
      await page.waitForSelector('#view .card.step');
      check('Samsung/LG → SS IPTV: its install step (LG store, Samsung USB)',
        (await h2()) === 'حمّل تطبيق SS IPTV' && (await page.textContent('#view')).includes('userwidget'));
      check('… with the same steps after it', (await page.textContent('#view .card.step .sub')).includes('الخطوة 1 من 7'));
    }

    console.log('== buy path ==');
    await open('#buy/live');
    const bdevs = await page.$$eval('#view [data-bdev]', b => b.map(x => x.dataset.bdev));
    check('VIDAA in the buy device list, right after Samsung/LG', bdevs.indexOf('vidaa') === bdevs.indexOf('webos') + 1, bdevs.join(' | '));
    await page.click('[data-bdev="vidaa"]');
    await page.waitForSelector('#view .brandcard');
    check('VIDAA: Smart first even for live sports, with the SS IPTV note',
      (await page.$eval('#view .brandcard.badged', b => b.dataset.brand)) === 'smart'
      && (await page.textContent('#view .note.warn')).includes('SS IPTV'));
    await open('#buy/live/vidaa/smart');
    const vPlans = await page.$$eval('#view [data-plan]', b => b.map(x => x.dataset.plan));
    const vText = await page.textContent('#view');
    await open('#buy/live/webos/smart');
    const wPlans = await page.$$eval('#view [data-plan]', b => b.map(x => x.dataset.plan));
    check('VIDAA gets the Samsung/LG plans', vPlans.length === 4 && vPlans.join() === wPlans.join(), vPlans.join(' '));
    check('… with a note that they run on VIDAA via SS IPTV', vText.includes('وهي نفسها لشاشات VIDAA'));
    check('… and Samsung/LG has no such note', !(await page.textContent('#view')).includes('لشاشات VIDAA'));
    await open('#buy/live/vidaa/falcon');
    const fPlans = await page.$$eval('#view [data-plan]', b => b.map(x => x.dataset.plan));
    const fWarn = await page.textContent('#view .note.warn');
    check('VIDAA + Falcon: Falcon plans with the ask-support caution',
      fPlans.length > 0 && fWarn.includes('اخترت شاشة هايسنس (VIDAA) مع فالكون') && fWarn.includes('للشاشات الذكية'));
    await open('#buy/live/webos/falcon');
    check('Samsung/LG + Falcon caution unchanged',
      (await page.textContent('#view .note.warn')).includes('اخترت شاشة سامسونج أو LG مع فالكون') && (await page.textContent('#view .note.warn')).includes('لـ webOS'));
    await open(`#buy/vod/vidaa/smart/${vPlans[vPlans.length - 1]}`);
    await page.click('[data-activate]');
    await page.waitForSelector('#view .card.step');
    check('result page opens the VIDAA activation steps',
      new URL(page.url()).hash === '#activate/smart/vidaa' && (await h2()) === 'حمّل تطبيق SS IPTV من متجر VIDAA');

    console.log('== casper: not on Samsung/LG or VIDAA, as its product pages say ==');
    await open('#activate');
    check('Casper no longer lists Duplecast among its apps',
      (await page.textContent('#view [data-sub="casper"] small')) === 'CASPER VIP أو AroPlayer أو Smarters Pro');
    await open('#activate/casper');
    const cdev = await page.$$eval('#view .dev', b => b.map(x => ({ name: x.querySelector('b').textContent,
      muted: x.classList.contains('muted'), sub: x.querySelector('small').textContent })));
    const off = cdev.slice(-2), on = cdev.slice(0, -2);
    check('Casper lists Samsung/LG and VIDAA last, dimmed, "not with Casper"',
      off.map(d => d.name).join('|') === 'سامسونج و LG و WebOS|هايسنس و VIDAA OS'
      && off.every(d => d.muted && d.sub === 'لا يعمل مع كاسبر') && on.length > 0 && on.every(d => !d.muted),
      cdev.map(d => d.name).join(' | '));
    for (const [dev, name] of [['webos', 'سامسونج و LG و WebOS'], ['vidaa', 'هايسنس و VIDAA OS']]) {
      await open('#activate/casper');
      await page.click(`#view [data-dev="${dev}"]`);
      await page.waitForSelector('#view .card.result');
      const txt = await page.textContent('#view');
      check(`casper → ${dev}: what the product page says, and no steps`,
        (await h2()) === `كاسبر لا يعمل على ${name}` && new URL(page.url()).hash === `#activate/casper/${dev}`
        && txt.includes('اشتراك كاسبر لا يعمل على شاشات سامسونج و LG، ولا على الشاشات بنظام VIDAA أو WebOS')
        && txt.includes('ويعمل على الكمبيوتر والماك وجوال أندرويد والآيفون والشاشات بنظام أندرويد')
        && !(await page.$('#view [data-next], #view [data-variant]')));
      check('… with its own tab title', (await page.title()).startsWith(`كاسبر لا يعمل على ${name}`), await page.title());
      await page.click('#view [data-buy]');
      await page.waitForSelector('#view [data-plan]');
      const plans = await page.$$eval('#view [data-plan]', b => b.map(x => x.dataset.plan));
      check("… its button opens Smart's plans for that TV",
        new URL(page.url()).hash === `#buy/vod/${dev}/smart` && plans.join() === wPlans.join(), plans.join(' '));
      await page.click('#view [data-back]');
      await page.waitForSelector('#view .card.result');
      check('… and back returns to it', new URL(page.url()).hash === `#activate/casper/${dev}` && (await h2()) === `كاسبر لا يعمل على ${name}`);
    }

    console.log('== video ==');
    await open('#activate/smart/vidaa');
    const vid = await page.$eval('#view .vid video', v => ({ src: v.getAttribute('src'), poster: v.getAttribute('poster'),
      playsinline: v.hasAttribute('playsinline'), controls: v.controls, preload: v.getAttribute('preload') }));
    check('the SS IPTV video heads the install step', /^\/static\/video\/ssiptv-ar\.mp4\?v=\d+$/.test(vid.src)
      && /^\/static\/video\/ssiptv-ar\.webp\?v=\d+$/.test(vid.poster) && vid.playsinline && vid.controls && vid.preload === 'none', JSON.stringify(vid));
    const vr = await page.evaluate(async src => { const r = await fetch(src, { headers: { Range: 'bytes=0-1' } }); return r.status; }, vid.src);
    check('… and its versioned address is served (the ?v= is ignored)', vr === 206, String(vr));
    const range = await page.evaluate(async () => { const r = await fetch('/static/video/ssiptv-ar.mp4', { headers: { Range: 'bytes=0-1' } });
      return [r.status, r.headers.get('content-type'), r.headers.get('content-range'), (await r.arrayBuffer()).byteLength]; });
    check('… served in byte ranges, as iPhone Safari needs', range[0] === 206 && range[1] === 'video/mp4' && /^bytes 0-1\/\d+$/.test(range[2]) && range[3] === 2, range.join(' '));
    check('… and its poster loads', (await page.$eval('#view .vid video', v => fetch(v.poster).then(r => r.ok))));

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
    check("Casper's old Duplecast link opens its not-on-this-TV screen",
      new URL(page.url()).hash === '#activate/casper/webos' && (await h2()) === 'كاسبر لا يعمل على سامسونج و LG و WebOS');
    await open('#activate/casper/vidaa/4');
    check('… and so does an old Casper VIDAA step link',
      new URL(page.url()).hash === '#activate/casper/vidaa' && (await h2()) === 'كاسبر لا يعمل على هايسنس و VIDAA OS');
    await open('#webos');
    check('old #webos link opens the app choice', new URL(page.url()).hash === '#activate/smart/webos' && (await h2()) === 'اختر التطبيق');

    await open('#activate/falcon/webos/ssiptv/7');
    await page.click('[data-next]');
    await page.waitForSelector('#view a.btn.wa');
    const wa = decodeURIComponent((await page.getAttribute('#view a.btn.wa', 'href')).split('text=')[1]);
    check('support message names the device and the app', wa.includes('نوع الجهاز: سامسونج و LG و WebOS') && wa.includes('التطبيق: SS IPTV'), wa.split('\n').slice(1, 4).join(' / '));

    for (const p of ['/vidaa', '/samsung-lg']) {
      await page.goto(APP + p);
      const n = (await page.$$('section.step')).length;
      check(`static ${p} renders the SS IPTV steps`, (await page.content()).includes('Get code') && n >= 7, `${n} steps`);
    }
    check('static /vidaa no longer says it is for every subscription', !(await page.goto(APP + '/vidaa').then(() => page.content())).includes('لكل الاشتراكات'));
    check('no page errors', !errors.length, errors.join(' | ').slice(0, 120));
  } catch (e) { fail++; console.log('  FAIL  exception:', e.message); }
  finally {
    await browser.close(); app.kill();
    fs.rmSync(dataDir, {recursive: true, force: true});
  }
  console.log(`\nResult: ${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();

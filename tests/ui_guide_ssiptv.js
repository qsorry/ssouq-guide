// Browser test: SS IPTV in the activation guide, for Smart, Falcon and Casper. VIDAA asks for the app (SS IPTV
// or Duplecast) and SS IPTV walks all seven steps to the done screen with every image loaded; Samsung/LG
// asks for the app (0Player, Duplecast or SS IPTV); Falcon and Casper keep their own 0Player portal codes; old
// links still open. (Duplecast's own steps: ui_guide_duplecast.js.) Casper runs on every TV: on Samsung/LG with
// its own plans for those TVs — the same three apps as Falcon, each opening with a note linking its plans —
// and on VIDAA with its regular plan, so no device of its is dimmed. And the buy path: VIDAA gets the
// Samsung/LG plans and Smart first.
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
    for (const sub of ['smart', 'falcon', 'casper']) {
      console.log(`== ${sub} ==`);
      await open(`#activate/${sub}`);
      const devs = await page.$$eval('#view .dev b', b => b.map(x => x.textContent));
      check('VIDAA in the device grid, right after Samsung/LG',
        devs.indexOf('هايسنس و VIDAA OS') === devs.indexOf('سامسونج و LG و WebOS') + 1, devs.join(' | '));

      await open(`#activate/${sub}/vidaa`);
      const vapps = await page.$$eval('#view .pick b', b => b.map(x => x.textContent));
      check('VIDAA asks for the app', (await h2()) === 'اختر التطبيق' && vapps.join('|') === 'SS IPTV|Duplecast', vapps.join('|'));
      await page.click('[data-variant="ssiptv"]');
      await page.waitForSelector('#view .card.step');
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
      check('VIDAA: ends on the done screen', (await h2()) === 'استمتع بالمشاهدة!' && new URL(page.url()).hash === `#activate/${sub}/vidaa/ssiptv/8`);

      await open(`#activate/${sub}/webos`);
      const apps = await page.$$eval('#view .pick b', b => b.map(x => x.textContent));
      check('Samsung/LG asks for the app', apps.join('|') === '0Player|Duplecast|SS IPTV', apps.join('|'));
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
    await page.waitForSelector('#view .pick');
    check('result page opens the VIDAA app choice',
      new URL(page.url()).hash === '#activate/smart/vidaa' && (await h2()) === 'اختر التطبيق');

    console.log('== casper: every TV — Samsung/LG with its own plans, VIDAA with its regular plan ==');
    await open('#activate');
    check('Casper no longer lists Duplecast among its apps',
      (await page.textContent('#view [data-sub="casper"] small')) === 'CASPER VIP أو AroPlayer أو Smarters Pro');
    await open('#activate/casper');
    const cdev = await page.$$eval('#view .dev', b => b.map(x => ({ name: x.querySelector('b').textContent,
      muted: x.classList.contains('muted'), sub: x.querySelector('small').textContent })));
    check('Casper lists every device, none dimmed or "not with Casper"',
      cdev.length === 8 && cdev.every(d => !d.muted && !d.sub.includes('لا يعمل')), cdev.map(d => d.name + ': ' + d.sub).join(' | '));
    for (const [v, title, app] of [['0player', 'حمّل تطبيق 0Player (زيرو بلاير)', 'من متجر التطبيقات في الشاشة'],
        ['duplecast', 'حمّل تطبيق Duplecast (دبل كاست)', 'من متجر التطبيقات في الشاشة'], ['ssiptv', 'حمّل تطبيق SS IPTV', 'شاشات LG:']]) {
      await open(`#activate/casper/webos/${v}`);
      const t = await page.textContent('#view');
      const links = await page.$$eval('#view .note a.link', a => a.map(x => x.getAttribute('href')));
      check(`… ${v} on Samsung/LG opens with the note on its Samsung/LG plans, before the app`,
        (await h2()) === title && t.includes('باقة كاسبر الخاصة بشاشات سامسونج و LG')
        && t.includes('أما باقة كاسبر العادية فلا تعمل على هذه الشاشات')
        && t.indexOf('باقة كاسبر الخاصة') < t.indexOf(app), await h2());
      check('… its three links are the three Casper Samsung/LG plans in the store (3 and 6 months, a year)',
        links.filter(u => /\/p(143101956|138230620|1152389812)\?utm_source=guide\.ssouq\.com&utm_medium=referral&utm_campaign=guide$/.test(u)).length === 3, links.join(' '));
    }
    await open('#activate/casper/vidaa/ssiptv');
    check('… but not on VIDAA: the regular plan works there', !(await page.textContent('#view')).includes('باقة كاسبر الخاصة'));
    for (const [dev, apps] of [['webos', '0player,duplecast,ssiptv'], ['vidaa', 'ssiptv,duplecast']]) {
      await open('#activate/casper');
      await page.click(`#view [data-dev="${dev}"]`);
      await page.waitForSelector('#view .pick');
      const got = await page.$$eval('#view [data-variant]', b => b.map(x => x.dataset.variant));
      check(`casper → ${dev}: the app choice, as for Smart and Falcon`, (await h2()) === 'اختر التطبيق'
        && new URL(page.url()).hash === `#activate/casper/${dev}` && got.join() === apps, got.join());
    }
    await open('#activate/casper/vidaa/ssiptv');
    const stepSub = () => page.$eval('#view .card.step > .sub', e => e.textContent);
    check('… and SS IPTV on VIDAA opens its steps', (await stepSub()).includes('كاسبر · هايسنس و VIDAA OS · SS IPTV · الخطوة 1 من 7'), await stepSub());

    console.log('== video ==');
    await open('#activate/smart/vidaa/ssiptv');
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
    await open('#activate/smart/vidaa/ssiptv/2');
    check('M3U step opens the M3U tool in a new tab',
      (await page.$eval('#view a.btn.go', a => a.getAttribute('href') + ' ' + a.target)) === '/#m3u _blank');
    await open('#activate/smart/vidaa/ssiptv/4');
    check('connect step opens the SS IPTV playlist editor',
      (await page.$eval('#view a.btn.go', a => a.href)) === 'https://ss-iptv.com/en/users/playlist');
    await open('#activate/falcon/webos/0player/6');          // طريقة «من التطبيق نفسه»: فيها الرمز وصورته
    const fal = await page.textContent('#view');
    check("Falcon's 0Player keeps its own portal code", fal.includes('75710072') && !fal.includes('92929480'));
    check('… and its own portal image', (await page.$$eval('#view img', im => im.map(i => i.getAttribute('src')))).includes('/static/img/webos-0player-portal-75710072.webp'));
    await open('#activate/smart/webos/0player/6');
    check("Smart's 0Player code unchanged", (await page.textContent('#view')).includes('92929480'));
    await open('#activate/casper/webos/duplecast/3');
    check("Casper's old Duplecast link opens that Samsung/LG step",
      new URL(page.url()).hash === '#activate/casper/webos/duplecast/3' && (await h2()) === 'اضغط Add Playlist', await h2());
    await open('#activate/casper/webos/0player/6');
    const cas = await page.textContent('#view');
    check("Casper's 0Player has its own portal code", cas.includes('59820658') && !cas.includes('92929480') && !cas.includes('75710072'));
    await open('#activate/casper/vidaa/4');
    check('an old Casper VIDAA step link (before the app choice) opens the app choice',
      new URL(page.url()).hash === '#activate/casper/vidaa' && (await h2()) === 'اختر التطبيق');
    await open('#activate/smart/vidaa/3');
    check('an old VIDAA step link (before the app choice) opens the app choice',
      new URL(page.url()).hash === '#activate/smart/vidaa' && (await h2()) === 'اختر التطبيق');
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

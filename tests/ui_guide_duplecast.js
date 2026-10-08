// Browser test: Duplecast (دبل كاست) in the activation guide, for Smart, Falcon and Casper, on Samsung/LG and on VIDAA.
// Seven steps each — the install step (with the video, the price: 15 days free then $3 a year, or a 16-riyal
// code from the store), scan the TV's barcode, Add Playlist, Xtream Info with host and port apart, saved,
// refresh on the TV, and the activation (Activate by Payment, or Activate by code with the store's code) —
// every image loads, the store button opens the code product, and the done screen's support message names
// the app. Casper offers Duplecast on Samsung/LG with its own plans for those TVs (the same steps, after a note
// linking them), and on VIDAA with its regular plan. The static pages carry the steps too.
const { chromium } = require('playwright-core');
const { spawn, execSync } = require('child_process');
const path = require('path'); const fs = require('fs'); const os = require('os');
const ROOT = path.dirname(__dirname);
const APP_PORT = 9838;
const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'guide_duplecast_'));
const EXE = fs.existsSync('/opt/pw-browsers/chromium/chrome-linux/chrome')
  ? '/opt/pw-browsers/chromium/chrome-linux/chrome'
  : execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim();
const BUY = 'https://ssouq.com/%D8%AA%D9%81%D8%B9%D9%8A%D9%84-duplecast-%D8%AF%D8%A8%D9%84-%D9%83%D8%A7%D8%B3%D8%AA-%D9%84%D9%85%D8%AF%D8%A9-%D8%B3%D9%86%D8%A9/p1575092005';
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
  const text = () => page.textContent('#view');
  const brokenImgs = () => page.evaluate(async () => {
    const im = [...document.querySelectorAll('#view img')];
    im.forEach(i => { i.loading = 'eager'; });
    await Promise.race([Promise.all(im.map(i => i.complete ? 0 : new Promise(r => { i.onload = i.onerror = r; }))),
                        new Promise(r => setTimeout(r, 8000))]);
    return im.filter(i => !i.naturalWidth).map(i => i.getAttribute('src'));
  });
  const TITLES = ['امسح الباركود على الشاشة بجوالك', 'اضغط Add Playlist', 'عبّئ بياناتك في تبويب Xtream Info',
    'تأكّد أن القائمة حُفظت', 'حدّث التطبيق على الشاشة وشاهد', 'بعد 15 يومًا فعّل التطبيق: 3 دولارات للسنة'];
  try {
    for (const sub of ['smart', 'falcon', 'casper']) for (const [dev, first, store] of [
        ['webos', 'حمّل تطبيق Duplecast (دبل كاست)', 'Samsung Apps'], ['vidaa', 'حمّل تطبيق Duplecast من متجر VIDAA', 'VIDAA Store']]) {
      console.log(`== ${sub} · ${dev} ==`);
      await open(`#activate/${sub}/${dev}`);
      if (dev === 'webos') {
        const opt = await page.$eval('#view [data-variant="duplecast"]', b => ({ label: b.querySelector('b').textContent,
          sub: b.querySelector('small').textContent, icon: b.querySelector('img').getAttribute('src') }));
        check('the app choice offers Duplecast, with its price', opt.label === 'Duplecast' && opt.sub.includes('مجاني 15 يومًا ثم 3$ للسنة')
          && opt.icon === '/static/img/apps/duplecast.webp', JSON.stringify(opt));
        await page.click('[data-variant="duplecast"]');
      }
      await page.waitForSelector('#view .card.step');
      // VIDAA بلا اختيار تطبيق: Duplecast وحده، فيُفتح على خطواته مباشرة
      const hash = dev === 'webos' ? `#activate/${sub}/${dev}/duplecast` : `#activate/${sub}/${dev}`;
      check('→ its install step', (await h2()) === first && new URL(page.url()).hash === hash);
      const t0 = await text();
      check('… from the TV\'s own store, with the price: 15 days free, then $3 a year, or a 16-riyal code',
        t0.includes(store) && t0.includes('15 يومًا') && t0.includes('3 دولارات للسنة') && t0.includes('16 ريال'));
      check('… and the price note links the store\'s code product',
        (await page.$$eval('#view .note a.link', a => a.map(x => x.href))).some(h => h.startsWith(BUY)));
      const titles = [first], broken = [...await brokenImgs()];
      for (let i = 1; i < 7; i++) {
        await page.click('[data-next]'); await page.waitForSelector('#view .card.step');
        titles.push(await h2()); broken.push(...await brokenImgs());
        if (i === 3) check('Xtream Info: host and port apart, with the http warning',
          (await text()).includes('http://host.com') && (await text()).includes('8080') && !!(await page.$('#view .note.http')));
      }
      check('seven steps in order', titles.slice(1).join('|') === TITLES.join('|'), titles.join(' → '));
      check('every image loads', !broken.length, broken.join(', '));
      const last = await text();
      check('the last step: pay $3 on its site, or activate by code', last.includes('Activate by Payment') && last.includes('Activate by code')
        && last.includes('Status : active') && last.includes('7.5 دولار'));
      const btn = await page.$eval('#view a.btn.go', a => ({ href: a.href, target: a.target, t: a.textContent }));
      check('… with a button to buy the code for 16 riyals', btn.href.startsWith(BUY) && btn.href.includes('utm_source=guide.ssouq.com')
        && btn.target === '_blank' && btn.t.includes('16 ريال'), btn.t);
      await page.click('[data-next]'); await page.waitForSelector('#view a.btn.wa');
      const wa = decodeURIComponent((await page.getAttribute('#view a.btn.wa', 'href')).split('text=')[1]);
      check('done screen, and the support message names the app', (await h2()) === 'استمتع بالمشاهدة!' && wa.includes('التطبيق: Duplecast'),
        wa.split('\n').slice(1, 4).join(' / '));
    }

    console.log('== video ==');
    await open('#activate/smart/webos/duplecast');
    const vid = await page.$eval('#view .vid video', v => ({ src: v.getAttribute('src'), poster: v.getAttribute('poster'),
      playsinline: v.hasAttribute('playsinline'), controls: v.controls, preload: v.getAttribute('preload') }));
    check('the Duplecast video heads the install step', /^\/static\/video\/duplecast-ar\.mp4\?v=\d+$/.test(vid.src)
      && /^\/static\/video\/duplecast-ar\.webp\?v=\d+$/.test(vid.poster) && vid.playsinline && vid.controls && vid.preload === 'none', JSON.stringify(vid));
    const range = await page.evaluate(async src => { const r = await fetch(src, { headers: { Range: 'bytes=0-1' } });
      return [r.status, r.headers.get('content-type')]; }, vid.src);
    check('… served in byte ranges, as iPhone Safari needs', range[0] === 206 && range[1] === 'video/mp4', range.join(' '));
    check('… and its poster loads', (await page.$eval('#view .vid video', v => fetch(v.poster).then(r => r.ok))));

    console.log('== links ==');
    await open('#activate/smart/webos/duplecast/7');
    check('a link to the activation step opens it', (await h2()) === TITLES[5]);
    await open('#activate/casper/webos/duplecast/3');
    check("Casper's old Samsung/LG Duplecast link opens that step", new URL(page.url()).hash === '#activate/casper/webos/duplecast/3'
      && (await h2()) === TITLES[1], await h2());
    await open('#activate/casper/webos');
    check('… Casper on Samsung/LG offers 0Player and Duplecast', (await h2()) === 'اختر التطبيق'
      && (await page.$$eval('#view [data-variant]', b => b.map(x => x.dataset.variant))).join() === '0player,duplecast');
    await open('#activate/casper/webos/duplecast');
    check("… its Duplecast opens with the note on Casper's own Samsung/LG plans",
      (await h2()) === 'حمّل تطبيق Duplecast (دبل كاست)' && (await text()).includes('باقة كاسبر الخاصة بشاشات سامسونج و LG'));
    const casperTitles = [];
    for (let i = 2; i <= 7; i++) { await open(`#activate/casper/webos/duplecast/${i}`); casperTitles.push(await h2()); }
    check('… the same seven steps as Smart, activation last', casperTitles.join('|') === TITLES.join('|'), casperTitles.join(' | '));
    await open('#activate/casper/webos/duplecast/7');
    check('… whose activation step still sells the code', (await page.$$eval('#view a.btn.go', a => a.map(x => x.href))).some(h => h.startsWith(BUY)));
    await open('#activate/casper/vidaa/3');
    check('… and Casper has Duplecast on VIDAA too', new URL(page.url()).hash === '#activate/casper/vidaa/3'
      && (await h2()) === TITLES[1], await h2());
    await open('#activate/casper/vidaa/duplecast/3');
    check('… and the old VIDAA link with the app in it still opens that step', new URL(page.url()).hash === '#activate/casper/vidaa/3'
      && (await h2()) === TITLES[1], await h2());
    await open('#activate/casper/vidaa');
    check('… with its regular plan: no Samsung/LG plans note there', !(await text()).includes('باقة كاسبر الخاصة'));

    for (const p of ['/samsung-lg', '/vidaa']) {
      await page.goto(APP + p);
      const html = await page.content();
      check(`static ${p} carries the Duplecast steps and the code product`, html.includes('تطبيق Duplecast')
        && html.includes('Activate by code') && html.includes('p1575092005') && html.includes('/static/video/duplecast-ar.mp4'));
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

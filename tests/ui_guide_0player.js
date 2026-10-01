// Browser test: 0Player on Samsung/LG, for Smart, Falcon and Casper (Casper: its install step opening with a note on its own
// Samsung/LG plans). Six steps: install (with the video), «متابعة»
// on the first-open message, PlayList, Add Playlist + Portal Code — which forks into two methods, the QR code
// from the phone or the app itself, both numbered «الخطوة 5 من 6» and both leading to the last step. Every image
// and the video load; each subscription's steps carry its own code everywhere (text, images, video) and no other's.
// The app is free: its box, its option and the install note say so.
const { chromium } = require('playwright-core');
const { spawn, execSync } = require('child_process');
const path = require('path'); const fs = require('fs'); const os = require('os');
const ROOT = path.dirname(__dirname);
const APP_PORT = 9834;
const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'guide_0player_'));
const EXE = fs.existsSync('/opt/pw-browsers/chromium/chrome-linux/chrome')
  ? '/opt/pw-browsers/chromium/chrome-linux/chrome'
  : execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim();
let pass = 0, fail = 0;
const check = (l, c, x='') => { c ? (pass++, console.log(`  PASS  ${l}${x?'  ('+x+')':''}`)) : (fail++, console.log(`  FAIL  ${l}${x?'  ('+x+')':''}`)); };
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function up(u){ for (let i=0;i<80;i++){ try { execSync(`curl -s -o /dev/null ${u}`); return; } catch(e){} await sleep(150); } }
const CODE = { smart: '92929480', falcon: '75710072', casper: '59820658' };

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
  const hash = () => new URL(page.url()).hash;
  const click = async sel => { await page.click(sel); await page.waitForSelector('#view .card'); };
  const brokenImgs = () => page.evaluate(async () => {
    const im = [...document.querySelectorAll('#view img')];
    im.forEach(i => { i.loading = 'eager'; });
    await Promise.race([Promise.all(im.map(i => i.complete ? 0 : new Promise(r => { i.onload = i.onerror = r; }))),
                        new Promise(r => setTimeout(r, 8000))]);
    return im.filter(i => !i.naturalWidth).map(i => i.getAttribute('src'));
  });
  try {
    for (const s of Object.keys(CODE)) {
      const code = CODE[s], others = Object.values(CODE).filter(c => c !== code);
      console.log(`== ${s} (${code}) ==`);
      await open(`#activate/${s}/webos`);
      check('the app choice offers 0Player, free, by QR code or remote',
        (await page.textContent('#view [data-variant="0player"] small')) === 'مجاني من متجر الشاشة: بالباركود من جوالك أو بالريموت');
      const apps = await page.$$eval('#view [data-variant]', b => b.map(x => x.dataset.variant));
      check('… beside Duplecast and SS IPTV', apps.join() === '0player,duplecast,ssiptv', apps.join());
      await click('[data-variant="0player"]');
      const broken = [];

      // ١ التحميل والفيديو
      check('step 1: install, 1 of 6', (await h2()) === 'حمّل تطبيق 0Player (زيرو بلاير)' && (await sub()).includes('الخطوة 1 من 6'), await sub());
      check(s === 'casper' ? "… opening with the note on Casper's own Samsung/LG plans" : '… with no Casper note',
        (await page.textContent('#view')).includes('باقة كاسبر الخاصة بشاشات سامسونج و LG') === (s === 'casper'));
      const vid = await page.$eval('#view .vid video', v => ({ src: v.getAttribute('src'), poster: v.getAttribute('poster'), pre: v.getAttribute('preload') }));
      check("… with this subscription's video", vid.src === `/static/video/0player-${code}-ar.mp4?v=2` && vid.poster === `/static/video/0player-${code}-ar.webp?v=2`
        && vid.pre === 'none', JSON.stringify(vid));
      const served = await page.evaluate(async v => { const r = await fetch(v.src, { headers: { Range: 'bytes=0-1' } }); const p = await fetch(v.poster);
        return [r.status, r.headers.get('content-type'), p.status]; }, vid);
      check('… served in byte ranges, poster too', served[0] === 206 && served[1] === 'video/mp4' && served[2] === 200, served.join(' '));
      check('… and the app is free', (await page.textContent('#view .appbox small')) === 'مجاني · من متجر الشاشة'
        && (await page.textContent('#view')).includes('التطبيق مجاني، وموجود في متجر سامسونج'));
      broken.push(...await brokenImgs());

      // ٢ رسالة أول فتح ← «متابعة»
      await click('[data-next]');
      check('step 2: the first-open message, press «متابعة»', (await h2()) === 'افتح التطبيق واضغط «متابعة»' && (await sub()).includes('الخطوة 2 من 6'));
      broken.push(...await brokenImgs());
      // ٣ PlayList
      await click('[data-next]');
      check('step 3: PlayList (قائمة التشغيل)', (await h2()) === 'اضغط PlayList (قائمة التشغيل)' && (await sub()).includes('الخطوة 3 من 6'));
      broken.push(...await brokenImgs());
      // ٤ Add Playlist + Portal Code، ثم التفرّع
      await click('[data-next]');
      const forks = await page.$$eval('#view [data-goto]', b => b.map(x => [x.dataset.goto, x.querySelector('b').textContent]));
      check('step 4: Add Playlist + Portal Code, then two methods instead of «التالي»',
        (await h2()) === 'اضغط Add Playlist واختر Portal Code' && (await sub()).includes('الخطوة 4 من 6') && !(await page.$('#view [data-next]'))
        && JSON.stringify(forks) === JSON.stringify([['4', 'بالباركود من جوالك'], ['5', 'من التطبيق نفسه']]), JSON.stringify(forks));
      broken.push(...await brokenImgs());

      // ٥ أ: بالباركود
      await click('[data-goto="4"]');
      let t = await page.textContent('#view');
      check('QR method: step 5 of 6, with the phone form for this code', (await h2()) === 'الطريقة الأولى: بالباركود من جوالك'
        && (await sub()).includes('الخطوة 5 من 6') && hash() === `#activate/${s}/webos/0player/5`
        && (await page.$eval('#view .card.step > img', i => i.getAttribute('src'))) === `/static/img/webos-0player-web-${code}.webp`);
      check('… the code, copyable, and Accept legal terms / ADD PLAYLIST / Playlist Added!',
        (await page.getAttribute('#view [data-copy]', 'data-copy')) === code && t.includes('Accept legal terms') && t.includes('ADD PLAYLIST') && t.includes('Playlist Added!'));
      broken.push(...await brokenImgs());
      await click('[data-next]');
      check('… then the last step, 6 of 6', (await h2()) === 'اختر قائمتك وشاهد' && (await sub()).includes('الخطوة 6 من 6')
        && (await page.textContent('#view [data-next]')) === 'أنهيت الخطوات');
      broken.push(...await brokenImgs());
      await page.goBack(); await page.waitForSelector('#view .card');
      check('… back returns to the QR method', (await h2()) === 'الطريقة الأولى: بالباركود من جوالك');
      await page.goBack(); await page.waitForSelector('#view .card');
      check('… and back again to the choice', (await h2()) === 'اضغط Add Playlist واختر Portal Code');

      // ٥ ب: من التطبيق نفسه
      await click('[data-goto="5"]');
      t = await page.textContent('#view');
      check('app method: step 5 of 6, the annotated screen for this code', (await h2()) === 'الطريقة الثانية: من التطبيق نفسه'
        && (await sub()).includes('الخطوة 5 من 6') && t.includes(code) && t.includes('SAVE')
        && (await page.$eval('#view .card.step > img', i => i.getAttribute('src'))) === `/static/img/webos-0player-portal-${code}.webp`);
      broken.push(...await brokenImgs());
      await click('[data-next]');
      check('… then the same last step', (await h2()) === 'اختر قائمتك وشاهد' && (await page.textContent('#view')).includes(code));
      await click('[data-next]');
      check('… and the done screen', (await h2()) === 'استمتع بالمشاهدة!' && hash() === `#activate/${s}/webos/0player/8`);
      check('every image on the way loads', !broken.length, broken.join(', '));

      // لكل اشتراكٍ رمزه في كل شيء، ولا رمز غيره
      const all = await page.evaluate(k => JSON.stringify(({ smart: DEVICES, falcon: FALCON, casper: CASPER })[k].webos.variants['0player']), s);
      check(`${s}'s steps carry only its own code (text, images, video)`, all.includes(code) && !others.some(c => all.includes(c))
        && all.includes(`0player-${code}-ar.mp4`) && all.includes(`webos-0player-web-${code}.webp`));
    }

    console.log('== links, titles, back without history ==');
    await open('#activate/smart/webos/0player/2');
    check('an old step link still opens (now the first-open message)', (await h2()) === 'افتح التطبيق واضغط «متابعة»');
    await open('#activate/falcon/webos/0player/5');
    check('the QR method has its own link, and its tab title counts 5 of 6',
      (await h2()) === 'الطريقة الأولى: بالباركود من جوالك' && (await page.title()).startsWith('الخطوة 5 من 6 · 0Player على'), await page.title());
    // صفحةٌ جديدة فعلًا (لا تغيير # في الصفحة نفسها) حتى لا يبقى للمعالج سجلٌّ يرجع فيه
    const fresh = async h => { await page.goto(`${APP}/?fresh=${Date.now()}${h}`); await page.waitForSelector('#view .card'); };
    await fresh('#activate/smart/webos/0player/7');
    await click('[data-back]');
    check('back from the last step without history goes to the choice', hash() === '#activate/smart/webos/0player/4');
    await fresh('#activate/smart/webos/0player/6');
    await click('[data-back]');
    check('… and so does back from the app method', hash() === '#activate/smart/webos/0player/4');
    await open('#activate/smart/webos/ssiptv/3');
    check('SS IPTV keeps its plain numbering', (await sub()).includes('الخطوة 3 من 7'));

    await page.goto(APP + '/samsung-lg');
    const html = await page.content();
    check('static /samsung-lg: both methods, numbered 5, and the video',
      html.includes('الخطوة 5 — الطريقة الأولى: بالباركود من جوالك') && html.includes('الخطوة 5 — الطريقة الثانية: من التطبيق نفسه')
      && html.includes('الخطوة 6 — اختر قائمتك وشاهد') && html.includes('/static/video/0player-92929480-ar.mp4'));
    check('no page errors', !errors.length, errors.join(' | ').slice(0, 160));
  } catch (e) { fail++; console.log('  FAIL  exception:', e.message); }
  finally {
    await browser.close(); app.kill();
    fs.rmSync(dataDir, {recursive: true, force: true});
  }
  console.log(`\nResult: ${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();

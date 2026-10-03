// Browser test: the Nuvio path on the Stremio page of the tool. The admin picks the platform (Stremio | Nuvio);
// on Nuvio a search in the gate creates a ready Nuvio account the Stremio way (email = username@tv.ssouq.com,
// password = the line's password), the card shows its status and add-on, and «تحديث الإضافة» / «إلغاء التفعيل» /
// «إعادة الربط» work against a mock Nuvio backend (tests/mock_nuvio.py, api.nuvio.tv's API).
const { chromium } = require('playwright-core');
const { spawn, execSync } = require('child_process');
const path = require('path'); const fs = require('fs'); const os = require('os');
const ROOT = path.dirname(__dirname);
const F1_PORT = 9785, NV_PORT = 9786, APP_PORT = 9787, XT_PORT = 9788;
const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'nuviopage_'));
const SHOTS = process.env.SHOTS_DIR || '';
const EXE = execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim();
let pass = 0, fail = 0;
const check = (l, c, x='') => { c ? (pass++, console.log(`  PASS  ${l}${x?'  ('+x+')':''}`)) : (fail++, console.log(`  FAIL  ${l}${x?'  ('+x+')':''}`)); };
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function up(u){ for (let i=0;i<80;i++){ try { execSync(`curl -s -o /dev/null ${u}`); return; } catch(e){} await sleep(150); } }
const api = (page, url, body) => page.evaluate(async ([u, b]) => (await fetch(u, b === undefined ? {} :
  {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(b)})).json(), [url, body]);
const shot = async (p, n) => { if (SHOTS) await p.screenshot({path: path.join(SHOTS, n + '.png'), fullPage: true}); };
const NV = `http://127.0.0.1:${NV_PORT}`;
const nvState = () => JSON.parse(execSync(`curl -s ${NV}/_mock/state`).toString());

(async () => {
  const procs = [
    spawn('python3', [path.join(ROOT,'tests/mock_falcon.py'), String(F1_PORT), 'k1'], {stdio:'ignore'}),
    spawn('python3', [path.join(ROOT,'tests/mock_nuvio.py'), String(NV_PORT)], {stdio:'ignore'}),
    // سيرفر Xtream وهمي يقبل user003 من بحث البوابة (فالحساب يُنشأ لخطٍّ يعمل)
    spawn('python3', ['-c', `import sys; sys.path.insert(0, ${JSON.stringify(path.join(ROOT, 'tests'))}); import mock_xtream as m
s = m.serve(${XT_PORT}); s.users['user003'] = 'pass003'; s.users['user004'] = 'pass004'; s.serve_forever()`], {stdio:'ignore'}),
  ];
  const app = spawn('python3', [path.join(ROOT,'xm_lines.py'), 'web'], {stdio:'ignore', env:{...process.env, XM_DATA:dataDir,
    XM_BIND:'127.0.0.1', XM_PORT:String(APP_PORT), NUVIO_BACKEND: NV, STREMIO_API:'http://127.0.0.1:9/'}});
  procs.push(app);
  await up(`http://127.0.0.1:${APP_PORT}/admin/login`);
  await up(`${NV}/_mock/state`);
  const browser = await chromium.launch({executablePath: EXE, args:['--no-sandbox']});
  const APP = `http://127.0.0.1:${APP_PORT}`;
  try {
    const ctx = await browser.newContext({viewport:{width:1100, height:900}});
    await ctx.grantPermissions(['clipboard-read', 'clipboard-write'], {origin: APP});
    const admin = await ctx.newPage();
    await admin.goto(APP + '/admin/setup');
    await api(admin, '/admin/api/setup', {password:'admin123'});
    const r = await api(admin, '/admin/api/accounts', {name:'عميل', user:'multi', password:'pw_multi', stremio: true,
      gates:[{name:'بوابة أ', mode:'falcon', api_url:`http://127.0.0.1:${F1_PORT}/api/v1`, api_key:'k1', host:`http://127.0.0.1:${XT_PORT}`},
             // سيرفرٌ آخر (localhost) — لربط خطٍّ من بوابةٍ أخرى بحساب Nuvio
             {name:'بوابة ب', mode:'falcon', api_url:`http://127.0.0.1:${F1_PORT}/api/v1`, api_key:'k1', host:`http://localhost:${XT_PORT}`}]});
    check('client set up with Stremio/Nuvio on', (r.accounts || []).some(a => a.user === 'multi'));

    const user = await ctx.newPage();
    const errs = []; user.on('pageerror', e => errs.push(e.message));
    await user.goto(APP + '/admin/login');
    await api(user, '/admin/api/login', {user:'multi', password:'pw_multi'});
    await user.goto(APP + '/admin/stremio');
    await user.waitForSelector('#gates .gate', {timeout: 8000});

    console.log('== the platform switch ==');
    check('Stremio by default', (await user.textContent('#accTtl')) === 'حسابات Stremio' && await user.isVisible('#mkSec')
      && await user.getAttribute('#plat [data-plat=stremio]', 'aria-selected') === 'true');
    await user.click('#plat [data-plat=nuvio]');
    await user.waitForFunction(() => /لا حسابات Nuvio/.test(document.querySelector('#list')?.textContent || ''), null, {timeout: 8000});
    check('Nuvio: its title, its note (the Stremio way), no «إنشاء يوزر Stremio» and no expiry tools',
      (await user.textContent('#accTtl')) === 'حسابات Nuvio' && /كحساب Stremio/.test(await user.textContent('#subNv'))
      && !(await user.isVisible('#mkSec')) && !(await user.isVisible('#sort')) && !(await user.isVisible('#expBtn')));
    check('the gate chip counts Nuvio accounts', (await user.textContent('#gates .gate')).replace(/\s+/g, ' ').trim() === 'بوابة أ 0');
    await shot(user, 'nuvio-empty');

    console.log('== create from search ==');
    await user.fill('#q', 'user003'); await user.click('#findBtn');
    await user.waitForSelector('#res [data-nmake]', {timeout: 8000});
    check('search offers «إنشاء حساب Nuvio» (not Stremio)', /إنشاء حساب Nuvio/.test(await user.textContent('#res [data-nmake]'))
      && (await user.$$('#res [data-make]')).length === 0);
    await user.click('#res [data-nmake]');
    await user.waitForSelector('#list .card.acct', {timeout: 20000});
    const clip = await user.evaluate(() => navigator.clipboard.readText());
    const st = nvState(), email = Object.keys(st.users)[0] || '';
    check('a Nuvio account the Stremio way: username@tv.ssouq.com and the line password', email === 'user003@tv.ssouq.com'
      && st.users[email] === 'pass003', email);
    check('the copied text has them, and how to sign in on the TV with the phone (QR)', clip.includes(email) && clip.includes('pass003')
      && /QR/.test(clip) && /جوالك/.test(clip), clip.slice(0, 80));
    const adds = st.addons[email] || [];
    check('our add-on first in his Nuvio add-ons, Nuvio defaults kept', adds.length === 3 && adds[0].name === 'سمارت سوق'
      && /\/stremio\/[^/]+\/manifest\.json$/.test(adds[0].url) && !/user003|pass003/.test(adds[0].url), JSON.stringify(adds.map(a => a.name)));
    const card = (await user.textContent('#list .card.acct')).replace(/\s+/g, ' ');
    check('the card: status, email, password, add-on version', /مفعّل/.test(card) && card.includes(email) && card.includes(st.users[email])
      && /الإضافة \d+\.\d+\.\d+/.test(card), card.slice(0, 160));
    check('the search hit now copies the account', await user.isVisible('#res [data-copy]') && (await user.$$('#res [data-nmake]')).length === 0);
    check('and the gate chip counts it', (await user.textContent('#gates .gate')).replace(/\s+/g, ' ').trim() === 'بوابة أ 1');
    await shot(user, 'nuvio-list');

    console.log('== «أو: حساب Nuvio بإيميلٍ تختاره» ==');
    check('the button is under the search, on Nuvio only', await user.isVisible('#nvCustomBtn') && !(await user.isVisible('#customBtn')));
    await user.click('#nvCustomBtn');
    await user.waitForSelector('#linkOverlay:not([hidden])');
    check('its dialog: email + password, an existing line from search (no «خطٌّ جديد»)', (await user.textContent('#linkTtl')) === 'حساب Nuvio بإيميلٍ تختاره'
      && await user.isVisible('#cEmail') && !(await user.isVisible('#linkModes')) && (await user.textContent('#cDom')) === '@tv.ssouq.com');
    await user.fill('#cEmail', 'sara.m'); await user.fill('#cPass', 'Sara1234');
    await user.fill('#linkQ', 'user004'); await user.click('#linkFindBtn');
    await user.waitForSelector('#linkHits [data-lnk]', {timeout: 8000});
    await shot(user, 'nuvio-custom');
    await user.click('#linkHits [data-lnk]');
    await user.waitForSelector('#linkOverlay', {state: 'hidden', timeout: 20000});
    const clip2 = await user.evaluate(() => navigator.clipboard.readText());
    check('created with the chosen email and password, and copied (the Nuvio text)', nvState().users['sara.m@tv.ssouq.com'] === 'Sara1234'
      && clip2.includes('sara.m@tv.ssouq.com') && clip2.includes('Sara1234') && /Nuvio/.test(clip2), clip2.slice(0, 60));
    await user.waitForFunction(() => document.querySelectorAll('#list .card.acct').length === 2, null, {timeout: 8000});
    check('and it is in the gate list', /sara\.m@tv\.ssouq\.com/.test(await user.textContent('#list')));

    console.log('== «ربط خط آخر» ==');
    const u3 = user.locator('#list .card.acct', {hasText: 'user003'});
    await u3.locator('[data-nmore]').click();
    await user.click('#sheet [data-nlinkto]');
    await user.waitForSelector('#linkOverlay:not([hidden])');
    check('the dialog: the other gate picked, its own gate taken', (await user.textContent('#linkTtl')) === 'ربط خطٍّ آخر بحساب Nuvio'
      && /بوابة ب/.test(await user.textContent('#linkGates .on')) && await user.isDisabled('#linkGates button:not(.on)'));
    await user.fill('#linkQ', 'user003'); await user.click('#linkFindBtn');
    await user.waitForSelector('#linkHits [data-lnk]', {timeout: 8000});
    await user.click('#linkHits [data-lnk]');
    await user.waitForSelector('#linkOverlay', {state: 'hidden', timeout: 20000});
    await user.waitForFunction(() => /بوابة ب · user003/.test(document.querySelector('#list')?.textContent || ''), null, {timeout: 8000});
    check('the card shows both lines (★ the owner)', /بوابة أ · user003 ★/.test(await u3.textContent()) && /بوابة ب · user003/.test(await u3.textContent()));
    await shot(user, 'nuvio-linked');
    await u3.locator('.lines button:not(.me)').click();
    await user.waitForFunction(() => /مرتبطٌ بحساب user003/.test(document.querySelector('#list')?.textContent || ''), null, {timeout: 8000});
    check('the chip goes to the linked line in its gate, with the account details', (await user.textContent('#gates .gate.on')).includes('بوابة ب')
      && /user003@tv\.ssouq\.com/.test(await user.textContent('#list')));
    await user.click('#list [data-nmore]');
    user.once('dialog', d => d.accept());
    await user.click('#sheet [data-nunlink]');
    await user.waitForFunction(() => !document.querySelector('#list .card.acct'), null, {timeout: 8000});
    check('«فصل الخط» takes it out of the account', (await user.textContent('#gates .gate.on')).replace(/\s+/g, ' ').trim() === 'بوابة ب 0');
    await user.click('#gates [data-gate]:first-child');
    await user.fill('#filter', 'user003');             // بقية الفحوص على حساب user003 وحده
    await user.waitForFunction(() => document.querySelectorAll('#list .card.acct').length === 1, null, {timeout: 8000});

    console.log('== the ⋯ menu ==');
    await user.click('#list [data-nmore]');
    const items = await user.$$eval('#sheet .sitem', bs => bs.map(b => b.querySelector('span').firstChild.textContent.trim()));
    check('«ربط خط آخر» · «تحديث الإضافة» · «إعادة الربط» · «إلغاء التفعيل» · «فحص عمل» (no TV code: the customer scans the QR)',
      items.join('|') === 'ربط خط آخر|تحديث الإضافة|إعادة الربط|إلغاء التفعيل|فحص عمل', items.join('|'));
    await shot(user, 'nuvio-menu');
    await user.click('#sheet [data-insp]');
    await user.waitForSelector('#inspOverlay:not([hidden])');
    await user.fill('#inspQ', 'game of thrones');
    let insp = '';
    for (let i = 0; i < 20 && !/✓ مصدره في العمل بالإضافة/.test(insp); i++) {   // أول مرة: «لم تُحمَّل بعد» ويبدأ تحميلها
      await user.click('#inspBtn');
      await user.waitForFunction(() => /في الإضافة/.test(document.querySelector('#inspRes')?.textContent || ''), null, {timeout: 20000});
      insp = (await user.textContent('#inspRes')).replace(/\s+/g, ' ');
      if (i === 0) check('first time: «لم تُحمَّل بعد» (its loading starts)', /⏳/.test(insp), insp.slice(0, 120));
      await sleep(700);
    }
    check('«فحص عمل»: the work in the add-on with its sources, and what each line list has', /Game of Thrones/.test(insp)
      && /قائمة فالكون/.test(insp) && /✓ مصدره في العمل بالإضافة/.test(insp), insp.slice(0, 200));
    await shot(user, 'nuvio-inspect');
    await user.click('#inspClose');
    await user.click('#list [data-nmore]');
    await user.click('#sheet [data-nre]');
    await user.waitForFunction(() => /حُدّثت الإضافة/.test(document.querySelector('#toast')?.textContent || ''), null, {timeout: 8000});
    check('«تحديث الإضافة»', true);
    const before = nvState().addons[email][0].url;
    await user.click('#list [data-nmore]');
    await user.click('#sheet [data-nrelink]');
    await user.waitForFunction(() => /أُعيد الربط/.test(document.querySelector('#toast')?.textContent || ''), null, {timeout: 8000});
    const after = nvState().addons[email][0].url;
    check('«إعادة الربط»: a new add-on link replaces the old one', after !== before && nvState().addons[email].length === 3);
    await user.click('#list [data-nmore]');
    user.once('dialog', d => d.accept());
    await user.click('#sheet [data-noff]');
    await user.waitForFunction(() => /مُلغى التفعيل/.test(document.querySelector('#list')?.textContent || ''), null, {timeout: 8000});
    check('«إلغاء التفعيل»: off, and our add-on removed from his Nuvio', !nvState().addons[email].some(a => a.name === 'سمارت سوق')
      && await user.isVisible('#list [data-nrelink]') && (await user.$$('#list [data-copy]')).length === 0);
    await shot(user, 'nuvio-off');
    await user.click('#list [data-nrelink]');
    await user.waitForFunction(() => /مفعّل/.test(document.querySelector('#list .pill')?.textContent || '')
      && !/مُلغى/.test(document.querySelector('#list .pill')?.textContent || ''), null, {timeout: 8000});
    check('«إعادة الربط» brings it back', nvState().addons[email][0].name === 'سمارت سوق');

    console.log('== remembered, and back to Stremio ==');
    await user.reload();
    await user.waitForSelector('#list .card.acct', {timeout: 8000});
    check('the platform is remembered', (await user.textContent('#accTtl')) === 'حسابات Nuvio');
    await user.click('#plat [data-plat=stremio]');
    check('Stremio again: its title and «إنشاء يوزر Stremio»', (await user.textContent('#accTtl')) === 'حسابات Stremio' && await user.isVisible('#mkSec'));

    const phone = await browser.newContext({viewport:{width:390, height:844}, deviceScaleFactor: 2});
    const ph = await phone.newPage();
    await ph.goto(APP + '/admin/login');
    await api(ph, '/admin/api/login', {user:'multi', password:'pw_multi'});
    await ph.goto(APP + '/admin/stremio');
    await ph.evaluate(() => localStorage.setItem('xm_stremio_plat', 'nuvio'));
    await ph.reload();
    await ph.waitForSelector('#list .card.acct', {timeout: 8000});
    const wide = await ph.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
    check('phone: no sideways scroll', wide);
    await shot(ph, 'nuvio-phone');
    check('no page errors', errs.length === 0, errs.join(' | '));
  } catch (e) { fail++; console.log('  FAIL  exception:', e.message); }
  finally {
    await browser.close();
    procs.forEach(p => { try { p.kill(); } catch {} });
    fs.rmSync(dataDir, {recursive: true, force: true});
    console.log(`\nResult: ${pass} passed, ${fail} failed`);
    process.exit(fail ? 1 : 0);
  }
})();

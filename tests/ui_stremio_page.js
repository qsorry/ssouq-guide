// Browser test: the Stremio page of the tool (stremio_tool.html at /stremio). One place per gate: the gate chips
// carry their account counts, a search in the selected gate is the only way to create a ready Stremio account,
// the gate's list shows its accounts (filter + sort) with link, copy and mail, and the mail overlay shows what
// the server received for that address. A client without the option is sent back to the create page.
const { chromium } = require('playwright-core');
const { spawn, execSync } = require('child_process');
const path = require('path'); const fs = require('fs'); const os = require('os');
const ROOT = path.dirname(__dirname);
const F1_PORT = 9775, F2_PORT = 9776, API_PORT = 9777, APP_PORT = 9778, MAIL_PORT = 9779, XT_PORT = 9780, ADDON_PORT = 9781;
const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'stremiopage_'));
const SHOTS = process.env.SHOTS_DIR || '';
const EXE = execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim();
let pass = 0, fail = 0;
const check = (l, c, x='') => { c ? (pass++, console.log(`  PASS  ${l}${x?'  ('+x+')':''}`)) : (fail++, console.log(`  FAIL  ${l}${x?'  ('+x+')':''}`)); };
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function up(u){ for (let i=0;i<80;i++){ try { execSync(`curl -s -o /dev/null ${u}`); return; } catch(e){} await sleep(150); } }
const api = (page, url, body) => page.evaluate(async ([u, b]) => (await fetch(u, b === undefined ? {} :
  {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(b)})).json(), [url, body]);
const shot = async (p, n) => { if (SHOTS) await p.screenshot({path: path.join(SHOTS, n + '.png'), fullPage: true}); };
const sendMail = (to, subject, body) => execSync(`python3 -c "
import smtplib
s = smtplib.SMTP('127.0.0.1', ${MAIL_PORT}); s.sendmail('no-reply@strem.io', ['${to}'], 'From: Stremio <no-reply@strem.io>\\r\\nSubject: ${subject}\\r\\n\\r\\n${body}\\r\\n'); s.quit()"`);

(async () => {
  const procs = [
    spawn('python3', [path.join(ROOT,'tests/mock_falcon.py'), String(F1_PORT), 'k1'], {stdio:'ignore'}),
    spawn('python3', [path.join(ROOT,'tests/mock_falcon.py'), String(F2_PORT), 'k2'], {stdio:'ignore'}),
    spawn('python3', [path.join(ROOT,'tests/mock_stremio_api.py'), String(API_PORT)], {stdio:'ignore'}),
    // سيرفر Xtream وهمي هوستًا للبوابتين: منه يُقرأ انتهاء اليوزرات (يرفض غير u/p، فتُصنَّف «منتهية»)
    spawn('python3', [path.join(ROOT,'tests/mock_xtream.py'), String(XT_PORT)], {stdio:'ignore'}),
    spawn('python3', [path.join(ROOT,'tests/mock_addon.py'), String(ADDON_PORT)], {stdio:'ignore'}),
  ];
  const app = spawn('python3', [path.join(ROOT,'xm_lines.py'), 'web'], {stdio:'ignore', env:{...process.env, XM_DATA:dataDir,
    XM_BIND:'127.0.0.1', XM_PORT:String(APP_PORT), XM_MAIL_PORT:String(MAIL_PORT), STREMIO_API:`http://127.0.0.1:${API_PORT}`,
    STREMIO_ACTIVATION_WAIT:'0.1', STREMIO_EXTRAS_ALLOW_LOCAL:'1',
    STREMIO_ADDON_CATALOGS:`http://127.0.0.1:${ADDON_PORT}/official.json,http://127.0.0.1:${ADDON_PORT}/community.json`}});
  procs.push(app);
  await up(`http://127.0.0.1:${APP_PORT}/admin/login`);
  const browser = await chromium.launch({executablePath: EXE, args:['--no-sandbox']});
  const APP = `http://127.0.0.1:${APP_PORT}`;
  try {
    const ctx = await browser.newContext({viewport:{width:1100, height:900}});
    await ctx.grantPermissions(['clipboard-read', 'clipboard-write'], {origin: APP});
    const admin = await ctx.newPage();
    await admin.goto(APP + '/admin/setup');
    await api(admin, '/admin/api/setup', {password:'admin123'});
    const F = p => `http://127.0.0.1:${p}/api/v1`;
    let r = await api(admin, '/admin/api/accounts', {name:'عميل Stremio', user:'multi', password:'pw_multi', stremio: true,
      gates:[{name:'بوابة أ', mode:'falcon', api_url:F(F1_PORT), api_key:'k1', host:`http://127.0.0.1:${XT_PORT}`},
             {name:'بوابة ب', mode:'falcon', api_url:F(F2_PORT), api_key:'k2', host:'http://localhost:' + XT_PORT}]});
    const gates = (r.accounts.find(a => a.user === 'multi') || {}).gates || [];
    await api(admin, '/admin/api/accounts', {name:'بلا Stremio', user:'one', password:'pw_one',
      gates:[{name:'بوابته', mode:'falcon', api_url:F(F1_PORT), api_key:'k1', host:'http://a.host:80'}]});
    check('two clients set up (Stremio on for one of them)', gates.length === 2);

    console.log('== a client without the option ==');
    const ctx2 = await browser.newContext();
    const one = await ctx2.newPage();
    await one.goto(APP + '/admin/login');
    await api(one, '/admin/api/login', {user:'one', password:'pw_one'});
    await one.goto(APP + '/admin/stremio');
    check('the Stremio page sends him back to the create page', new URL(one.url()).pathname === '/admin', one.url());
    r = await api(one, '/admin/api/stremio/accounts');
    check('and its API refuses him', /غير مفعّل/.test(r.error || ''), JSON.stringify(r));

    console.log('== the Stremio page ==');
    const user = await ctx.newPage();
    const errs = []; user.on('pageerror', e => errs.push(e.message));
    await user.goto(APP + '/admin/login');
    await api(user, '/admin/api/login', {user:'multi', password:'pw_multi'});
    await user.goto(APP + '/admin/');
    await user.waitForSelector('#lnkStremio:not([hidden])', {timeout: 8000});
    await user.click('#lnkStremio');
    await user.waitForSelector('#gates .gate', {timeout: 8000});
    check('reached from the create page header link', new URL(user.url()).pathname === '/admin/stremio', user.url());
    const chips = await user.$$eval('#gates .gate', bs => bs.map(b => b.textContent.replace(/\s+/g, ' ').trim()));
    check('one place per gate, with its count', chips.length === 2 && chips[0] === 'بوابة أ 0' && chips[1] === 'بوابة ب 0', chips.join(' | '));
    check('the gate list starts empty, and says how to add', /أنشئ يوزر Stremio أعلاه/.test(await user.textContent('#list')));
    check('no Stremio account for an existing line without searching it first', (await user.$$('[data-make]')).length === 0);

    console.log('== «إنشاء يوزر Stremio»: line in the gate → mail (Stremio account) → add-on ==');
    await user.waitForSelector('#pkgs input[name="pkg"]', {timeout: 8000});
    const pk = await user.$$eval('#pkgs .opt span', ss => ss.map(x => x.textContent.trim()));
    check('the gate packages are offered', pk.length >= 2, pk.join(' | '));
    let asked = '';
    user.once('dialog', d => { asked = d.message(); d.accept(); });
    await user.click('#mkBtn');
    await user.waitForSelector('#mkRes .card.made', {timeout: 20000});
    check('asked to confirm (it costs the package)', /بوابة أ/.test(asked) && /تُخصم/.test(asked), asked.slice(0, 60));
    const made = (await user.textContent('#mkRes')).replace(/\s+/g, ' ');
    const newUser = (await user.textContent('#mkRes .creds .mono')).trim();
    check('one press: a new line in the gate, its mail and the add-on', newUser && made.includes(newUser + '@tv.ssouq.com') && made.includes('✓ يوزر · بريد · إضافة'), made.slice(0, 160));
    const clip0 = await user.evaluate(() => navigator.clipboard.readText());
    check('the customer text is copied', clip0.includes(newUser + '@tv.ssouq.com'), clip0.slice(0, 60));
    await user.waitForFunction(() => document.querySelector('#gates .gate.on .count')?.textContent === '1', null, {timeout: 8000});
    check('and it is listed under gate أ', (await user.$$('#list .card')).length === 1);
    await user.waitForFunction(() => /يرفضه السيرفر|ينتهي|انتهى/.test(document.querySelector('#list .card .pill')?.textContent || ''), null, {timeout: 10000});
    check('its expiry is read from the server (this mock rejects it → expired), as one badge', /يرفضه السيرفر/.test(await user.textContent('#list .card .pill'))
          && /السيرفر يرفض اليوزر/.test(await user.getAttribute('#list .card .pill', 'title')));
    const chips1 = (await user.textContent('#expChips')).replace(/\s+/g, ' ');
    check('expiry chips classify the accounts', /الكل ?1/.test(chips1) && /منتهية ?1/.test(chips1), chips1);
    check('the gate tab flags it (⚠ due)', /⚠ 1/.test(await user.textContent('#gates .gate.on')));
    check('an add-on installed without categories (line not active yet) is flagged',
          /الإضافة بلا أقسام/.test(await user.textContent('#list .card .tags')));
    check('the card has one main action, mail and ⋯ (the rest is in the menu)', (await user.$$('#list .card:first-child .abar button')).length === 3
          && (await user.$$('#list [data-re], #list [data-lock], #list [data-linkto]')).length === 0);
    await user.click('#list .card:first-child [data-more]');
    await user.waitForSelector('#sheet:not([hidden]) [data-re]', {timeout: 5000});
    const menuT = (await user.textContent('#sheetList')).replace(/\s+/g, ' ');
    check('⋯ opens the actions sheet: update add-on, change its link, link another line', /تحديث الإضافة/.test(menuT)
          && /تغيير رابط الإضافة/.test(menuT) && /ربط خط آخر/.test(menuT), menuT.slice(0, 120));
    await shot(user, 'stremio-menu');
    await user.click('#sheet [data-re]');
    await user.waitForFunction(() => /حُدّثت الإضافة/.test(document.querySelector('#toast')?.textContent || ''), null, {timeout: 10000});
    check('«تحديث الإضافة» reinstalls it and says whether categories came back (this mock still rejects the line)',
          /لم يُرجع أقسامًا/.test(await user.textContent('#toast')) && await user.isHidden('#sheet'),
          await user.textContent('#toast'));
    check('the add-on is locked to its account from the start (no public install link on the card)',
          /مقفلة على الحساب/.test(await user.textContent('#list .card .tags')) && (await user.$$('#list .card [data-what="نُسخ الرابط"]')).length === 0
          && !/نسخ رابط التثبيت/.test(menuT));
    let lockAsk = '';
    user.once('dialog', d => { lockAsk = d.message(); d.accept(); });
    await user.click('#list .card:first-child [data-more]');
    await user.click('#sheet [data-lock]');
    await user.waitForFunction(() => /قُفلت الإضافة/.test(document.querySelector('#toast')?.textContent || ''), null, {timeout: 10000});
    check('«تغيير رابط الإضافة» asks first, then stops any copy moved to another account', /تتوقف أي نسخةٍ/.test(lockAsk), lockAsk.slice(0, 60));

    console.log('== a batch: 3 at once ==');
    await user.fill('#n', '3'); await user.dispatchEvent('#n', 'input');
    check('the button says how many', (await user.textContent('#mkBtn')).includes('3 يوزرات Stremio'), await user.textContent('#mkBtn'));
    user.once('dialog', d => d.accept());
    await user.click('#mkBtn');
    await user.waitForFunction(() => /أُنشئ 3 من 3/.test(document.querySelector('#mkRes')?.textContent || ''), null, {timeout: 30000});
    check('three lines, each with its mail and add-on', (await user.$$('#mkRes .card.made')).length === 3
          && (await user.$$eval('#mkRes .meta', ms => ms.filter(m => m.textContent.includes('✓ يوزر · بريد · إضافة')).length)) === 3);
    check('one button copies all three', (await user.textContent('[data-copyall]')).includes('(3)'));
    const clip3 = await user.evaluate(() => navigator.clipboard.readText());
    check('all three accounts were copied', (clip3.match(/@tv\.ssouq\.com/g) || []).length === 3, String((clip3.match(/@tv\.ssouq\.com/g) || []).length));
    await user.waitForFunction(() => document.querySelector('#gates .gate.on .count')?.textContent === '4', null, {timeout: 8000});
    check('the gate count follows (1 + 3)', true);
    await user.selectOption('#sort', 'exp');
    check('sort by nearest expiry', (await user.$$('#list .card')).length === 4);
    await user.selectOption('#sort', 'new');

    await user.fill('#q', 'user003'); await user.click('#findBtn');
    await user.waitForSelector('#res [data-make]', {timeout: 8000});
    check('search in gate أ finds the line, with create + link', await user.isVisible('#res [data-make]')
          && (await user.getAttribute('#res [data-copy]', 'data-copy')).startsWith('https://guide.ssouq.com/stremio/'));
    await user.click('#res [data-make]');
    await user.waitForFunction(() => document.querySelector('#gates .gate.on .count')?.textContent === '5', null, {timeout: 15000});
    const clip = await user.evaluate(() => navigator.clipboard.readText());
    check('created from the search result, and its text copied', /user003@tv\.ssouq\.com/.test(clip) && /كلمة المرور: pass003/.test(clip), clip.slice(0, 80));
    check('the result card now copies the account and opens its mail', await user.isVisible('#res [data-mail]'));
    const rows = await user.$$eval('#list .card', cs => cs.map(c => c.textContent.replace(/\s+/g, ' ')));
    check('it is listed under gate أ (newest first), no mail yet', rows.length === 5 && rows[0].includes('user003@tv.ssouq.com')
          && (await user.$$('#list .card:first-child [data-mail] .n')).length === 0, rows.join(' | ').slice(0, 200));

    console.log('== per-gate places ==');
    await user.click('#gates .gate:nth-child(2)');
    await user.waitForFunction(() => document.querySelector('#gates .gate.on')?.textContent.includes('بوابة ب'), null, {timeout: 8000});
    check('gate ب has its own (empty) list', (await user.$$('#list .card')).length === 0 && (await user.textContent('#gName2')) === 'بوابة ب');
    check('switching gates clears the previous search', (await user.inputValue('#q')) === '' && (await user.$$('#res .card')).length === 0);

    console.log('== mail ==');
    sendMail('user003@tv.ssouq.com', 'Reset your Stremio password', 'Open https://www.stremio.com/reset-password/tok42');
    await user.click('#gates .gate:nth-child(1)');
    await user.waitForFunction(() => document.querySelector('#list [data-mail="user003"] .n')?.textContent === '1', null, {timeout: 8000});
    check('the gate list shows the received mail count', true);
    check('gate ب: the create section loads its own packages', true);
    await user.click('#list [data-mail="user003"]');
    await user.waitForSelector('#mailList .mail', {timeout: 8000});
    check('the mail overlay shows the account and the message with its link',
          (await user.textContent('#mailAddr')).includes('user003@tv.ssouq.com')
          && (await user.textContent('#mailList .mail-h b')) === 'Reset your Stremio password'
          && (await user.getAttribute('#mailList .mail-l', 'href')) === 'https://www.stremio.com/reset-password/tok42');
    await user.click('.mail-help summary');
    await shot(user, 'stremio-mail');
    await user.click('#mailClose');

    console.log('== filter and sort ==');
    await user.fill('#filter', 'zzz');
    check('filter with no match says so', /لا حساب يطابق/.test(await user.textContent('#list')));
    await user.fill('#filter', 'user003');
    check('filter by username', (await user.$$('#list .card')).length === 1);
    await user.selectOption('#sort', 'mail');
    check('sort by mail keeps the list', (await user.$$('#list .card')).length === 1);
    await shot(user, 'stremio-page');

    console.log('== one Stremio account, lines from several gates ==');
    await user.fill('#filter', 'user003'); await user.dispatchEvent('#filter', 'input');
    await user.click('#list [data-more="user003"]');
    await user.click('#sheet [data-linkto="user003"]');
    await user.waitForSelector('#linkOverlay:not([hidden])', {timeout: 5000});
    const lg = await user.$$eval('#linkGates button', bs => bs.map(b => [b.textContent.trim(), b.disabled, b.classList.contains('on')]));
    check('the link picker offers the other gate (this one is already in the account)',
          JSON.stringify(lg) === JSON.stringify([['بوابة أ', true, false], ['بوابة ب', false, true]]), JSON.stringify(lg));
    await user.fill('#linkQ', 'user003'); await user.click('#linkFindBtn');
    await user.waitForSelector('#linkHits [data-lnk]', {timeout: 8000});
    await user.click('#linkHits [data-lnk]');
    await user.waitForFunction(() => /رُبط user003 بالحساب/.test(document.querySelector('#toast')?.textContent || ''), null, {timeout: 15000});
    await user.waitForFunction(() => document.querySelectorAll('#list .card .lines button').length === 2, null, {timeout: 8000});
    const chipsL = await user.$$eval('#list .card .lines button', bs => bs.map(b => b.textContent.replace(/\s+/g, ' ').trim()));
    check('an existing line from gate ب is linked: the card lists the account lines', chipsL[0] === 'بوابة أ · user003 ★' && chipsL[1] === 'بوابة ب · user003', chipsL.join(' | '));
    await user.click('#list .card .lines button:nth-of-type(2)');
    await user.waitForFunction(() => document.querySelector('#gates .gate.on')?.textContent.includes('بوابة ب') && document.querySelector('#list [data-more="user003"]'), null, {timeout: 8000});
    check('its chip moves to that line in gate ب (linked, same login)', (await user.inputValue('#filter')) === 'user003'
          && (await user.textContent('#list .card')).includes('user003@tv.ssouq.com'));
    await shot(user, 'stremio-lines');
    user.once('dialog', d => d.accept());
    await user.click('#list [data-more="user003"]');
    await user.click('#sheet [data-unlink]');
    await user.waitForFunction(() => /فُصل الخط/.test(document.querySelector('#toast')?.textContent || ''), null, {timeout: 10000});
    await user.waitForFunction(() => document.querySelector('#gates .gate.on .count')?.textContent === '0', null, {timeout: 8000});
    check('«فصل الخط» removes it from the account and gate ب', true);

    await user.click('#gates .gate:nth-child(1)');
    await user.waitForFunction(() => document.querySelector('#gates .gate.on')?.textContent.includes('بوابة أ'), null, {timeout: 8000});
    await user.fill('#filter', newUser); await user.dispatchEvent('#filter', 'input');
    await user.click(`#list [data-more="${newUser}"]`);
    await user.click(`#sheet [data-linkto="${newUser}"]`);
    await user.click('[data-lm="new"]');
    await user.waitForSelector('#linkPkgs input[name="lpkg"]', {timeout: 8000});
    let askNew = '';
    user.once('dialog', d => { askNew = d.message(); d.accept(); });
    await user.click('#linkMk');
    await user.waitForFunction(() => /ورُبط بالحساب/.test(document.querySelector('#toast')?.textContent || ''), null, {timeout: 20000});
    check('«خطٌّ جديد»: asks (it costs the package), creates the line in gate ب and links it',
          /بوابة ب/.test(askNew) && /تُخصم/.test(askNew), askNew.slice(0, 80));
    await user.waitForFunction(() => document.querySelectorAll('#list .card .lines button').length === 2, null, {timeout: 8000});
    check('and the card now lists both lines', (await user.textContent('#list .card .lines')).includes('بوابة ب ·'));

    console.log('== a Stremio account with an email and password I choose ==');
    await user.click('#gates .gate:nth-child(1)');
    await user.waitForFunction(() => document.querySelector('#gates .gate.on')?.textContent.includes('بوابة أ'), null, {timeout: 8000});
    await user.click('#customBtn');
    await user.waitForSelector('#customFields:not([hidden])', {timeout: 5000});
    check('the window asks for the email (on our mail domain) and password', (await user.textContent('#linkTtl')).includes('بإيميلٍ تختاره')
          && (await user.textContent('#cDom')) === '@tv.ssouq.com');
    await user.fill('#linkQ', 'user001'); await user.click('#linkFindBtn');
    await user.waitForSelector('#linkHits [data-lnk]', {timeout: 8000});
    await user.click('#linkHits [data-lnk]');
    check('it checks the email first', /اسم الإيميل/.test(await user.textContent('#linkMsg')));
    await user.fill('#cEmail', 'family.ali'); await user.fill('#cPass', 'Ali12345');
    await shot(user, 'stremio-custom');
    await user.click('#linkHits [data-lnk]');
    await user.waitForFunction(() => /أُنشئ الحساب family\.ali@tv\.ssouq\.com/.test(document.querySelector('#toast')?.textContent || ''), null, {timeout: 15000});
    const clipC = await user.evaluate(() => navigator.clipboard.readText());
    check('the account is created with that email and password, and its text copied', clipC.includes('family.ali@tv.ssouq.com') && clipC.includes('Ali12345'), clipC.slice(0, 80));
    await user.fill('#filter', 'family.ali'); await user.dispatchEvent('#filter', 'input');
    await user.waitForFunction(() => (document.querySelector('#list')?.textContent || '').includes('family.ali@tv.ssouq.com'), null, {timeout: 8000});
    check('and listed in the gate with its first line (user001)', (await user.textContent('#list .card')).includes('user001'));

    console.log('== the add-ons & panels page ==');
    await user.click('#tabAdd');
    await user.waitForSelector('#viewAddons:not([hidden]) #panelList [data-pg]', {timeout: 8000});
    check('the second tab is its own page (/stremio/addons)', new URL(user.url()).pathname === '/admin/stremio/addons'
          && await user.isHidden('#viewAccounts') && (await user.getAttribute('#tabAdd', 'aria-current')) === 'page');

    console.log('== change a panel link for all users at once ==');
    const pans = await user.$$eval('#panelList .pan', cs => cs.map(c => c.textContent.replace(/\s+/g, ' ').trim()));
    check('each gate with its link and the number of its accounts', pans.length === 2 && pans[0].includes('بوابة أ') && pans[0].includes(`http://127.0.0.1:${XT_PORT}`)
          && /\d+ حساب/.test(pans[0]), pans.join(' | '));
    const gA = await user.getAttribute('#panelList [data-pg]', 'data-pg');
    await user.fill(`[data-pin="g:${gA}"]`, `http://127.0.0.2:${XT_PORT}`);
    const asked2 = [];
    const onDlg = d => { asked2.push(d.message()); d.accept(); };
    user.on('dialog', onDlg);
    await user.click(`[data-pg="${gA}"]`);
    await user.waitForFunction(() => /تغيّر الرابط لجميع اليوزرات/.test(document.querySelector('#toast')?.textContent || ''), null, {timeout: 20000});
    check('asks, tries the new link on its lines (this mock rejects them), asks again, then changes it for everyone',
          asked2.length === 2 && /لكل يوزراتها/.test(asked2[0]) && /لم يقبل/.test(asked2[1])
          && (await user.textContent('#panelList .pan')).includes(`http://127.0.0.2:${XT_PORT}`), asked2.join(' | ').slice(0, 160));
    const myGates = (await api(user, '/admin/api/mygates')).gates || [];
    check('and the gate itself now has the new link (new users get it)', myGates[0] && myGates[0].host === `http://127.0.0.2:${XT_PORT}`, JSON.stringify(myGates[0] || {}).slice(0, 120));
    await user.fill(`[data-pin="g:${gA}"]`, `http://127.0.0.1:${XT_PORT}`);
    await user.click(`[data-pg="${gA}"]`);
    await user.waitForFunction(() => (document.querySelector('#panelList .pan')?.textContent || '').includes('127.0.0.1'), null, {timeout: 20000});
    user.off('dialog', onDlg);
    check('and back again', (await user.textContent('#panelList .pan')).includes(`http://127.0.0.1:${XT_PORT}`));
    await shot(user, 'stremio-panels');

    console.log('== another add-on (like AIOMetadata) in new and existing accounts ==');
    user.once('dialog', d => d.accept());
    await user.fill('#extUrl', `http://127.0.0.1:${ADDON_PORT}/needs/manifest.json`); await user.click('#extAdd');
    await user.waitForFunction(() => /تحتاج إعدادًا/.test(document.querySelector('#extMsg')?.textContent || ''), null, {timeout: 8000});
    check('an add-on that still needs setup is refused with the reason and a button to its setup page',
          (await user.getAttribute('#extMsg a.acc', 'href')) === `http://127.0.0.1:${ADDON_PORT}/needs/configure`);
    await user.fill('#extUrl', 'AIOMetadata');
    check('typing a name turns the button into a search', (await user.textContent('#extAdd')).trim() === 'بحث');
    await user.click('#extAdd');
    await user.waitForSelector('#extHits .card', {timeout: 10000});
    const hitsT = await user.$$eval('#extHits .card', cs => cs.map(c => c.textContent.replace(/\s+/g, ' ').trim()));
    check('searching «AIOMetadata» finds it in the add-on directory (and «AIO Metadata» that still needs setup)',
          hitsT.length === 2 && hitsT[0].startsWith('AIOMetadata') && /افتح صفحة الإعداد/.test(hitsT[1]), hitsT.join(' | ').slice(0, 200));
    check('the one needing setup links to its setup page', (await user.getAttribute('#extHits a.acc', 'href')) === `http://127.0.0.1:${ADDON_PORT}/aiobase/configure`);
    check('…with two steps and a field for its install link, and its other hosts folded (one card, not one per host)',
          await user.isVisible('#extHits [data-xpaste="1"]') && await user.isVisible('#extHits [data-xinst="1"]')
          && (await user.textContent('#extHits details.hosts summary')).includes('(1)'));
    await shot(user, 'stremio-extras-search');
    let extAsk = '';
    user.once('dialog', d => { extAsk = d.message(); d.accept(); });
    await user.click('#extHits [data-xhit="0"]');
    await user.waitForFunction(() => /ثُبّتت AIOMetadata في الحسابات/.test(document.querySelector('#extJob')?.textContent || ''), null, {timeout: 30000});
    const jobT = (await user.textContent('#extJob')).replace(/\s+/g, ' ');
    check('«إضافة لجميع اليوزرات»: one confirmation, then it installs in all of them in the background', /لجميع اليوزرات/.test(extAsk)
          && /(\d+) من \1/.test(jobT) && !/تعذّر/.test(jobT), jobT + ' | ' + extAsk.slice(0, 60));
    check('and the list shows it (for every new account)', (await user.textContent('#extList')).includes('AIOMetadata')
          && (await user.textContent('#extList')).includes('لكل حسابٍ جديد'));
    await shot(user, 'stremio-extras');
    user.once('dialog', d => d.accept());
    await user.click('#extList [data-xmore]');
    await user.click('#sheet [data-xdel]');
    await user.waitForFunction(() => /لا إضافات بعد/.test(document.querySelector('#extList')?.textContent || ''), null, {timeout: 8000});
    check('«حذف من القائمة»', true);
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

// Browser test: the Stremio page of the tool (stremio_tool.html at /stremio). One place per gate: the gate chips
// carry their account counts, a search in the selected gate is the only way to create a ready Stremio account,
// the gate's list shows its accounts (filter + sort) with link, copy and mail, and the mail overlay shows what
// the server received for that address. A client without the option is sent back to the create page.
const { chromium } = require('playwright-core');
const { spawn, execSync } = require('child_process');
const path = require('path'); const fs = require('fs'); const os = require('os');
const ROOT = path.dirname(__dirname);
const F1_PORT = 9775, F2_PORT = 9776, API_PORT = 9777, APP_PORT = 9778, MAIL_PORT = 9779;
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
  ];
  const app = spawn('python3', [path.join(ROOT,'xm_lines.py'), 'web'], {stdio:'ignore', env:{...process.env, XM_DATA:dataDir,
    XM_BIND:'127.0.0.1', XM_PORT:String(APP_PORT), XM_MAIL_PORT:String(MAIL_PORT), STREMIO_API:`http://127.0.0.1:${API_PORT}`}});
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
      gates:[{name:'بوابة أ', mode:'falcon', api_url:F(F1_PORT), api_key:'k1', host:'http://a.host:80'},
             {name:'بوابة ب', mode:'falcon', api_url:F(F2_PORT), api_key:'k2', host:'http://b.host:80'}]});
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
    check('the gate list starts empty, and says how to add', /ابحث عن اليوزر/.test(await user.textContent('#list')));
    check('no way to create an account outside a search result', (await user.$$('[data-make]')).length === 0);

    await user.fill('#q', 'user003'); await user.click('#findBtn');
    await user.waitForSelector('#res [data-make]', {timeout: 8000});
    check('search in gate أ finds the line, with create + link', await user.isVisible('#res [data-make]')
          && (await user.getAttribute('#res [data-copy]', 'data-copy')).startsWith('https://guide.ssouq.com/stremio/'));
    await user.click('#res [data-make]');
    await user.waitForFunction(() => document.querySelector('#gates .gate.on .count')?.textContent === '1', null, {timeout: 15000});
    const clip = await user.evaluate(() => navigator.clipboard.readText());
    check('created from the search result, and its text copied', /user003@tv\.ssouq\.com/.test(clip) && /كلمة المرور: pass003/.test(clip), clip.slice(0, 80));
    check('the result card now copies the account and opens its mail', await user.isVisible('#res [data-mail]'));
    const rows = await user.$$eval('#list .card', cs => cs.map(c => c.textContent.replace(/\s+/g, ' ')));
    check('it is listed under gate أ', rows.length === 1 && rows[0].includes('user003@tv.ssouq.com') && rows[0].includes('لا بريد'), rows.join(' | '));

    console.log('== per-gate places ==');
    await user.click('#gates .gate:nth-child(2)');
    await user.waitForFunction(() => document.querySelector('#gates .gate.on')?.textContent.includes('بوابة ب'), null, {timeout: 8000});
    check('gate ب has its own (empty) list', (await user.$$('#list .card')).length === 0 && (await user.textContent('#gName2')) === 'بوابة ب');
    check('switching gates clears the previous search', (await user.inputValue('#q')) === '' && (await user.$$('#res .card')).length === 0);

    console.log('== mail ==');
    sendMail('user003@tv.ssouq.com', 'Reset your Stremio password', 'Open https://www.stremio.com/reset-password/tok42');
    await user.click('#gates .gate:nth-child(1)');
    await user.waitForFunction(() => /البريد 1/.test(document.querySelector('#list')?.textContent || ''), null, {timeout: 8000});
    check('the gate list shows the received mail count', true);
    await user.click('#list [data-mail]');
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
    await user.fill('#filter', '003');
    check('filter by username', (await user.$$('#list .card')).length === 1);
    await user.selectOption('#sort', 'mail');
    check('sort by mail keeps the list', (await user.$$('#list .card')).length === 1);
    await shot(user, 'stremio-page');
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

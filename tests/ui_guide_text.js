// Browser test: the admin enables "نسخ نص الشرح" for one client. That client's search
// (result copy + replacement) copies the full guide text; creating users keeps the line.
const { chromium } = require('playwright-core');
const { spawn, execSync } = require('child_process');
const path = require('path'); const fs = require('fs'); const os = require('os');
const ROOT = path.dirname(__dirname);
const FALCON_PORT = 9741, APP_PORT = 9742;
const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'guidetext_'));
const SHOTS = process.env.SHOTS_DIR || '';
const EXE = execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim();
let pass = 0, fail = 0;
const check = (l, c, x='') => { c ? (pass++, console.log(`  PASS  ${l}${x?'  ('+x+')':''}`)) : (fail++, console.log(`  FAIL  ${l}${x?'  ('+x+')':''}`)); };
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function up(u){ for (let i=0;i<80;i++){ try { execSync(`curl -s -o /dev/null ${u}`); return; } catch(e){} await sleep(150); } }
const api = (page, url, body) => page.evaluate(async ([u, b]) => (await fetch(u, b === undefined ? {} :
  {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(b)})).json(), [url, body]);

const HOST = 'http://ssouqhost.vip:80', GUIDE = 'https://guide.ssouq.com/#activate/casper';
const HOST2 = 'http://falcon.host:80', GUIDE2 = 'https://guide.ssouq.com/#activate/falcon';
const HOST3 = 'http://smart.host:80', GUIDE3 = 'https://guide.ssouq.com/#activate/smart';

(async () => {
  const falcon = spawn('python3', [path.join(ROOT,'tests/mock_falcon.py'), String(FALCON_PORT), 'testkey'], {stdio:'ignore'});
  const app = spawn('python3', [path.join(ROOT,'xm_lines.py'), 'web'],
    {stdio:'ignore', env:{...process.env, XM_DATA:dataDir, XM_BIND:'127.0.0.1', XM_PORT:String(APP_PORT)}});
  await up(`http://127.0.0.1:${APP_PORT}/admin/login`);
  const browser = await chromium.launch({executablePath: EXE, args:['--no-sandbox']});
  const APP = `http://127.0.0.1:${APP_PORT}`, FALCON = `http://127.0.0.1:${FALCON_PORT}/api/v1`;
  const adminCtx = await browser.newContext();
  const userCtx = await browser.newContext({permissions:['clipboard-read','clipboard-write']});
  const admin = await adminCtx.newPage(), user = await userCtx.newPage();
  const clip = () => user.evaluate(() => navigator.clipboard.readText());
  try {
    await admin.goto(APP + '/admin/setup');
    await api(admin, '/admin/api/setup', {password:'admin123'});
    let r = await api(admin, '/admin/api/accounts', {name:'عميل كاسبر', user:'casper', password:'pw_casper',
      gates:[{name:'بوابة كاسبر', mode:'falcon', api_url:FALCON, api_key:'testkey', host:HOST, guide_url:GUIDE},
             {name:'بوابة فالكون', mode:'falcon', api_url:FALCON, api_key:'testkey', host:HOST2, guide_url:GUIDE2},
             // نوعها فالكون ورابطها سمارت: الاسم يتبع الرابط المضاف لا نوع البوابة
             {name:'بوابة سمارت', mode:'falcon', api_url:FALCON, api_key:'testkey', host:HOST3, guide_url:GUIDE3}]});
    check('client with three gates created', r.ok === true, r.error || '');

    // ---- صفحة الحسابات: تفعيل الخيار من المربع ----
    await admin.evaluate(() => localStorage.setItem('xm_admin_tab', 'accounts'));
    await admin.goto(APP + '/admin/accounts');
    await admin.waitForSelector('[data-toggle]');
    await admin.click('[data-toggle]');
    await admin.click('[data-edit]');
    await admin.waitForSelector('#acctModal:not([hidden])');
    check('box hidden until the option is ticked', await admin.isHidden('#acc_guide_box'));
    await admin.check('#acc_copy_guide');
    check('ticking shows the text box', await admin.isVisible('#acc_guide_text'));
    const dflt = await admin.inputValue('#acc_guide_text');
    check('text box prefilled with the default text', dflt.startsWith('📲 طريقة التثبيت والتفعيل') && dflt.includes('Pass: {pass}'), dflt.slice(0, 26));
    if (SHOTS) await admin.screenshot({path: path.join(SHOTS, 'admin-guide-text.png'), fullPage: false});
    await admin.click('#save');
    await admin.waitForSelector('#acctModal', {state:'hidden'});
    check('client row shows the option', (await admin.textContent('#list')).includes('نسخ نص الشرح'));

    // ---- صفحة الإنشاء للعميل: الإنشاء يبقى سطرًا حتى مع الخيار ----
    await user.goto(APP + '/admin/login');
    r = await api(user, '/admin/api/login', {user:'casper', password:'pw_casper'});
    check('client login', r.role === 'account');
    await user.goto(APP + '/admin');
    await user.waitForSelector('input[name="pkg"]', {timeout: 8000});
    const LINE = (h, g) => new RegExp('^Host ' + h + ' User \\d{12} Pass \\d{12} Guide ' + g.replace(/[.#/]/g, '\\$&') + '$');
    check('create: copy button unchanged (نسخ الكل)', (await user.textContent('#copyRes')).trim() === 'نسخ الكل');
    await user.click('#create');
    await user.waitForSelector('#resBox:not([hidden])', {timeout: 8000});
    const res = await user.textContent('#res');
    check('create: result is the one-line format, not the guide text', LINE(HOST, GUIDE).test(res), res);
    check('create: clipboard holds the line', (await clip()) === res);
    check('history row copies the line', (await user.$eval('#hist button.cb', b => b.dataset.line)) === res);

    // ---- البحث: نص الشرح ----
    await user.fill('#searchQ', 'user003');
    await user.click('#searchBtn');
    await user.waitForSelector('#searchRes button.cb', {timeout: 8000});
    const sc = await user.$eval('#searchRes button.cb', b => b.dataset.copy);
    check('search: copy is the guide text for that user', sc.startsWith('📲 طريقة التثبيت والتفعيل') && sc.includes('🔗 شرح التثبيت:\n' + GUIDE) && sc.includes('Host: ' + HOST + '\nUser: user003\nPass: pass003'), sc.slice(-40));
    check('search: subscription name from the gate guide (كاسبر)', sc.includes('واختيار سيرفر كاسبر ✅'));
    check('search: no placeholder left', !/\{(host|user|pass|guide|server)\}/.test(sc));
    await user.click('#searchRes button.cb');
    await sleep(150);
    check('search: clipboard holds it', (await clip()) === sc);

    // ---- بديل عن رقمٍ لم يُعثر عليه (من البحث): نص الشرح ----
    await user.fill('#searchQ', '999000111');
    await user.click('#searchBtn');
    await user.waitForSelector('#mkRepl', {timeout: 8000});
    await user.click('#mkRepl');
    await user.waitForSelector('#mkGo', {timeout: 8000});
    await user.click('#mkGo');
    await user.waitForFunction(() => (document.querySelector('#mkBox .msg.ok') || {}).textContent, null, {timeout: 8000});
    check('replacement: says the guide text was copied', (await user.textContent('#mkBox .msg.ok')).includes('نُسخ نص الشرح'));
    const rc = await clip();
    check('replacement: clipboard holds the guide text', rc.startsWith('📲') && /User: \d{12}\nPass: \d{12}/.test(rc), rc.slice(-40));

    // ---- بوابة برابط فالكون: اسم الاشتراك في البحث يتبع رابطها، والإنشاء سطر ----
    await user.click('.gate-tab:has-text("بوابة فالكون")');
    await user.waitForSelector('input[name="pkg"]', {timeout: 8000});
    await user.fill('#searchQ', 'user002');
    await user.click('#searchBtn');
    await user.waitForSelector('#searchRes button.cb', {timeout: 8000});
    const sc2 = await user.$eval('#searchRes button.cb', b => b.dataset.copy);
    check('Falcon link: search names فالكون', sc2.includes('واختيار سيرفر فالكون ✅') && !sc2.includes('كاسبر'), (sc2.match(/واختيار سيرفر [^\n]*/) || [''])[0]);
    check('Falcon link: its own guide link and host', sc2.includes('🔗 شرح التثبيت:\n' + GUIDE2) && sc2.includes('Host: ' + HOST2 + '\n'));
    await user.click('#create');
    await user.waitForFunction(() => document.querySelector('#res').textContent.includes('falcon.host'), null, {timeout: 8000});
    check('Falcon gate: create still copies the line', LINE(HOST2, GUIDE2).test(await user.textContent('#res')));

    // ---- بوابة برابط سمارت (ونوعها فالكون): الاسم يتبع الرابط ----
    await user.click('.gate-tab:has-text("بوابة سمارت")');
    await user.waitForSelector('input[name="pkg"]', {timeout: 8000});
    await user.fill('#searchQ', 'user001');
    await user.click('#searchBtn');
    await user.waitForSelector('#searchRes button.cb', {timeout: 8000});
    const sc3 = await user.$eval('#searchRes button.cb', b => b.dataset.copy);
    check('Smart link: search names سمارت (link wins over the Falcon gate type)', sc3.includes('واختيار سيرفر سمارت ✅') && sc3.includes('🔗 شرح التثبيت:\n' + GUIDE3), (sc3.match(/واختيار سيرفر [^\n]*/) || [''])[0]);
    await user.click('.gate-tab:has-text("بوابة كاسبر")');
    await user.waitForSelector('input[name="pkg"]', {timeout: 8000});

    // ---- إيقاف الخيار: البحث يعود سطرًا ----
    const acc = (await api(admin, '/admin/api/accounts')).accounts[0];
    r = await api(admin, '/admin/api/accounts', {...acc, password:'', copy_guide:false});
    check('admin switches it off', r.ok === true, r.error || '');
    await user.reload();
    await user.waitForSelector('input[name="pkg"]', {timeout: 8000});
    await user.fill('#searchQ', 'user004');
    await user.click('#searchBtn');
    await user.waitForSelector('#searchRes button.cb', {timeout: 8000});
    check('off: search copies the line', (await user.$eval('#searchRes button.cb', b => b.dataset.copy)) === `Host ${HOST} User user004 Pass pass004 Guide ${GUIDE}`);
    await user.click('#create');
    await user.waitForFunction(() => /^Host /.test(document.querySelector('#res').textContent), null, {timeout: 8000});
    const line = await user.textContent('#res');
    check('off: create copies the line', LINE(HOST, GUIDE).test(line) && (await clip()) === line, line);
  } catch (e) { fail++; console.log('  FAIL  exception:', e.message); }
  finally {
    await browser.close(); falcon.kill(); app.kill();
    fs.rmSync(dataDir, {recursive: true, force: true});
  }
  console.log(`\nResult: ${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();

// Browser smoke test of the gate UI (admin.html add-gate + xm_lines.html gate flow).
const { chromium } = require('playwright-core');
const { spawn, execSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');

const ROOT = '/home/user/ssouq-guide';
const PANEL_PORT = 9188, APP_PORT = 9189;
const PUSER = 'demo', PPASS = 'secret';
const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'uismoke_'));
const EXE = fs.existsSync('/opt/pw-browsers/chromium/chrome-linux/chrome')
  ? '/opt/pw-browsers/chromium/chrome-linux/chrome'
  : execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim();

let pass = 0, fail = 0;
const check = (l, c, x='') => { c ? (pass++, console.log(`  PASS  ${l}${x?'  ('+x+')':''}`)) : (fail++, console.log(`  FAIL  ${l}${x?'  ('+x+')':''}`)); };
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function waitUp(url) { for (let i=0;i<80;i++){ try{ execSync(`curl -s -o /dev/null ${url}`); return; }catch(e){} await sleep(150); } }

(async () => {
  const panel = spawn(process.execPath === 'node' ? 'python3' : 'python3',
    [path.join(ROOT,'tests/mock_panel.py'), String(PANEL_PORT), PUSER, PPASS], {stdio:'ignore'});
  const app = spawn('python3', [path.join(ROOT,'xm_lines.py'),'web'],
    {stdio:'ignore', env:{...process.env, XM_DATA:dataDir, XM_BIND:'127.0.0.1', XM_PORT:String(APP_PORT)}});
  await waitUp(`http://127.0.0.1:${PANEL_PORT}/token.php`);
  await waitUp(`http://127.0.0.1:${APP_PORT}/admin/login`);

  const browser = await chromium.launch({ executablePath: EXE, args:['--no-sandbox'] });
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const APP = `http://127.0.0.1:${APP_PORT}`;
  const PANEL = `http://127.0.0.1:${PANEL_PORT}`;
  try {
    // admin setup + add account+gate via API (using the page's fetch so cookies stick)
    await page.goto(APP + '/admin/setup');
    let r = await page.evaluate(async () => (await fetch('/admin/api/setup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:'admin123'})})).json());
    check('admin setup', r.ok === true);
    r = await page.evaluate(async (P) => (await fetch('/admin/api/accounts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
      name:'MR7', user:'demo', password:'secret',
      gates:[{name:'بوابة مرح',mode:'web',host:'http://mrha.ink',panel_base:P,panel_user:'demo',panel_pass:'secret',guide_url:'https://guide.ssouq.com/'},
             {name:'بوابة فالكون',mode:'web',host:'http://falcon.host',panel_base:P,panel_user:'demo',panel_pass:'secret',guide_url:''}]
    })})).json(), PANEL);
    check('account with 2 gates added', r.ok === true, r.error||'');
    const gid = r.accounts[0].gates[0].id;

    // admin.html renders the account with its gates
    await page.goto(APP + '/admin/accounts');
    await page.waitForTimeout(400);
    const listTxt = await page.textContent('#list');
    check('admin list shows both gate names', listTxt.includes('بوابة مرح') && listTxt.includes('بوابة فالكون'));
    // the dashboard home: welcome banner, stat cards, shortcuts, latest accounts and admin links
    await page.evaluate(() => nav('home'));
    await page.waitForFunction(() => document.getElementById('statPrize').textContent !== '—', null, {timeout: 8000});
    check('dashboard: banner, 4 stat cards (visitors too), 7 shortcuts (content reports too), admin links',
      (await page.textContent('.hero h1')).includes('مرحباً بك في لوحة الإدارة') && (await page.$$('.kpis .kpi')).length === 4
      && (await page.$$('.qgrid .qt')).length === 7 && (await page.$$('#links .lt')).length >= 4);
    check('dashboard: accounts and gates counted, prizes from the contest summary',
      (await page.textContent('#statAcc')) === '1' && (await page.textContent('#statGates')) === '2'
      && (await page.textContent('#statPrize')) === '0');
    check('dashboard: latest accounts with an avatar, login name isolated', (await page.$$('#recent .ra')).length === 1
      && (await page.$eval('#recent .ra bdi', e => e.textContent)) === 'demo');
    await page.click('#recent .ra');
    check('a latest account opens it in the accounts tab', await page.$eval('.view[data-view="accounts"]', v => v.classList.contains('on'))
      && await page.$eval('.acct', a => a.classList.contains('open')));
    check('the open tab is kept in the address (a reload stays on it)', new URL(page.url()).hash === '#accounts');
    await page.evaluate(() => localStorage.setItem('xm_admin_tab', 'accounts'));   // ما كانت الأداة تتذكّره
    await page.goto(APP + '/admin/accounts');
    check('a fresh visit opens the dashboard home, not the last tab', await page.$eval('.view[data-view="home"]', v => v.classList.contains('on'))
      && new URL(page.url()).hash === '');
    await page.goto(APP + '/admin/accounts#settings');
    check('#settings in the address opens its tab', await page.$eval('.view[data-view="settings"]', v => v.classList.contains('on')));
    check('the bottom bar links the contest page', (await page.getAttribute('.bnav #navContest', 'href')) === '/admin/contest'
      && (await page.$$('.bnav > *')).length === 5);
    await page.setViewportSize({width: 390, height: 844});
    await page.evaluate(() => nav('home'));
    check('dashboard fits a phone (no horizontal scroll)', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    if (process.env.SHOTS_DIR) { await page.waitForTimeout(400); await page.screenshot({path: path.join(process.env.SHOTS_DIR, 'dashboard-phone.png')}); }
    await page.goto(APP + '/admin/contest');
    await page.waitForSelector('.kpis .kpi');
    check('the contest page in the dashboard design: header, banner, 4 stat cards, shortcuts, bottom bar',
      (await page.textContent('.top .brand b')) === 'سمارت سوق' && (await page.textContent('.hero h1')) === 'مسابقة التوقّعات'
      && (await page.$$('.kpis .kpi')).length === 4 && (await page.$$('.qgrid .qt')).length === 6
      && (await page.textContent('.bnav a.on')).includes('المسابقة')
      && (await page.getAttribute('.bnav a[data-tab="accounts"]', 'href')) === '/admin/accounts#accounts'
      && (await page.getAttribute('.bnav #lnkHome', 'href')) === '/admin/accounts'
      && await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    if (process.env.SHOTS_DIR) {                 // ما تراه على الجوال أولًا: الرأس والترحيب والأرقام والشريط السفلي
      await page.screenshot({path: path.join(process.env.SHOTS_DIR, 'contest-admin-phone.png')});
      await page.evaluate(() => { document.getElementById('matches').scrollIntoView(); });
      await page.screenshot({path: path.join(process.env.SHOTS_DIR, 'contest-admin-phone-rows.png')});
    }
    await page.click('.bnav a[data-tab="accounts"]');
    await page.waitForSelector('.view[data-view="accounts"].on', {timeout: 5000});
    check('and its bar opens the dashboard tabs', new URL(page.url()).pathname === '/admin/accounts');

    // login as the person
    await page.evaluate(async () => { await fetch('/admin/logout'); });
    r = await page.evaluate(async () => (await fetch('/admin/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user:'demo',password:'secret'})})).json());
    check('account login', r.role === 'account');

    // account page: gate tabs render
    await page.goto(APP + '/admin');
    await page.waitForSelector('.gate-tab', {timeout:5000});
    const tabs = await page.$$eval('.gate-tab', els => els.map(e => e.textContent.trim()));
    check('two gate tabs rendered', tabs.length === 2 && tabs.includes('بوابة مرح'), tabs.join('|'));
    check('first gate active', await page.$eval('.gate-tab', e => e.classList.contains('on')));

    // packages need captcha (OCR off) -> modal shows
    await page.waitForSelector('#capOverlay.show', {timeout:6000});
    check('captcha modal shown on load', await page.isVisible('#capOverlay'));

    // Cancel closes it (the bug we fixed)
    await page.click('#capCancel');
    await page.waitForTimeout(200);
    check('Cancel closes the captcha modal', !(await page.isVisible('#capOverlay')));

    // read the panel captcha via the gate session jar, submit it
    const jar = path.join(dataDir,'sessions','gate_'+gid+'.cookies');
    // re-open the modal via تحديث (reload packages -> need_captcha)
    await page.click('#reload');
    await page.waitForSelector('#capOverlay.show', {timeout:6000});
    // now read code from mock using the gate jar
    let code = '';
    for (let i=0;i<20 && !code;i++){ try{
      code = execSync(`python3 - <<'PY'
import http.cookiejar,urllib.request
cj=http.cookiejar.MozillaCookieJar("${jar}"); cj.load(ignore_discard=True,ignore_expires=True)
op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
r=op.open("${PANEL}/captcha.php?a=1",timeout=10); r.read()
print(r.headers.get("X-Captcha-Code",""))
PY`).toString().trim();
    }catch(e){ await sleep(200); } }
    check('read panel captcha for the gate', !!code, code);
    await page.fill('#capInput', code);
    await page.click('#capSubmit');
    // after login, packages should load; pick first and create
    await page.waitForSelector('input[name="pkg"]', {timeout:8000});
    check('packages loaded after captcha', (await page.$$('input[name="pkg"]')).length >= 1);
    await page.click('#create');
    await page.waitForSelector('#resBox:not([hidden]) .lines', {timeout:8000}).catch(()=>{});
    const res = await page.textContent('#res').catch(()=>'');
    check('created line in new format with Guide', res.includes(' User ') && res.includes(' Pass ') && res.includes('Guide https://guide.ssouq.com/'), res.slice(0,70));
  } catch (e) {
    fail++; console.log('  FAIL  exception:', e.message);
  } finally {
    await browser.close();
    panel.kill(); app.kill();
    fs.rmSync(dataDir, {recursive:true, force:true});
  }
  console.log(`\nResult: ${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();

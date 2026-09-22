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

    // date-range audit: a line seeded straight into the panel must show as "من اللوحة"
    execSync(`curl -s -o /dev/null "${PANEL}/_seed?username=910000000001&password=p1"`);
    await page.click('#rangeBox button[data-days="7"]');
    await page.waitForSelector('#rangeRes .tbl', {timeout:15000});
    const sum = (await page.textContent('#rangeRes .sum')).replace(/\s+/g,' ').trim();
    check('audit summary counts both origins', /من الأداة 1/.test(sum) && /من اللوحة مباشرة 1/.test(sum), sum);
    const seeded = await page.$eval('#rangeRes .tbl tbody', b => {
      const tr = [...b.querySelectorAll('tr')].find(r => r.textContent.includes('910000000001'));
      return tr ? tr.className + '|' + tr.textContent.replace(/\s+/g,' ').trim() : '';
    });
    check('panel-made line is flagged and highlighted', seeded.startsWith('off|') && seeded.includes('من اللوحة'), seeded.slice(0,80));
    const mine = await page.$eval('#rangeRes .tbl tbody', b => {
      const tr = [...b.querySelectorAll('tr')].find(r => !r.textContent.includes('910000000001'));
      return tr ? tr.textContent.replace(/\s+/g,' ').trim() : '';
    });
    check('tool-made line is flagged "من الأداة"', mine.includes('من الأداة'), mine.slice(0,80));
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

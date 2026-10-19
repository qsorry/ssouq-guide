// Browser test: «تحقّق» on a creation session (a day under a package in «اليوزرات المنشأة») asks the
// live panel about each user — found / renamed (its password is on another user) / missing — and
// offers to add the missing ones with the same user, password and package.
const { chromium } = require('playwright-core');
const { spawn, execSync } = require('child_process');
const path = require('path'); const fs = require('fs'); const os = require('os');
const ROOT = path.dirname(__dirname);
const F_PORT = 9781, APP_PORT = 9783;
const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'verifysess_'));
const EXE = execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim();
let pass = 0, fail = 0;
const check = (l, c, x='') => { c ? (pass++, console.log(`  PASS  ${l}${x?'  ('+x+')':''}`)) : (fail++, console.log(`  FAIL  ${l}${x?'  ('+x+')':''}`)); };
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function up(u){ for (let i=0;i<80;i++){ try { execSync(`curl -s -o /dev/null ${u}`); return; } catch(e){} await sleep(150); } }
const api = (page, url, body) => page.evaluate(async ([u, b]) => (await fetch(u, b === undefined ? {} :
  {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(b)})).json(), [url, body]);

(async () => {
  const f = spawn('python3', [path.join(ROOT,'tests/mock_falcon.py'), String(F_PORT), 'k1'], {stdio:'ignore'});
  const app = spawn('python3', [path.join(ROOT,'xm_lines.py'), 'web'],
    {stdio:'ignore', env:{...process.env, XM_DATA:dataDir, XM_BIND:'127.0.0.1', XM_PORT:String(APP_PORT)}});
  await up(`http://127.0.0.1:${APP_PORT}/admin/login`);
  const browser = await chromium.launch({executablePath: EXE, args:['--no-sandbox']});
  const APP = `http://127.0.0.1:${APP_PORT}`;
  const page = await (await browser.newContext({permissions:['clipboard-read','clipboard-write']})).newPage();
  const dialogs = [];
  page.on('dialog', d => { dialogs.push(d.message()); d.accept(); });
  try {
    await page.goto(APP + '/admin/setup');
    await api(page, '/admin/api/setup', {password:'admin123'});
    await api(page, '/admin/api/accounts', {name:'عميل', user:'u1', password:'pw_u1',
      gates:[{name:'مرح', mode:'falcon', api_url:`http://127.0.0.1:${F_PORT}/api/v1`, api_key:'k1', host:'http://h:80'}]});
    await page.goto(APP + '/admin/login');
    await api(page, '/admin/api/login', {user:'u1', password:'pw_u1'});
    await page.goto(APP + '/admin');
    await page.waitForSelector('input[name="pkg"]', {timeout: 8000});
    const me = await api(page, '/admin/api/me');
    const gid = me.gates[0].id;

    // سجلّ جلسةٍ واحدة (يومٌ تحت باقة): موجود · كلمة مروره عند يوزرٍ آخر · مفقود
    const t = new Date().toISOString();
    const mk = (u, p) => ({line: `Host http://h:80 User ${u} Pass ${p}`, username: u, password: p,
      package: '1months', package_id: '167', time: t});
    await page.evaluate(([k, h]) => localStorage.setItem(k, JSON.stringify(h)),
      ['xm_lines_history_' + me.account + '_' + gid, [mk('user003', 'pass003'), mk('oldname5', 'pass005'), mk('lost77', 'lostpw77')]]);
    await page.reload();
    await page.waitForSelector('#hist button[data-vday]', {timeout: 8000});
    check('a «تحقّق» button on the session', (await page.textContent('#hist button[data-vday]')).trim() === 'تحقّق');

    await page.click('#hist button[data-vday]');
    await page.waitForFunction(() => /موجود في اللوحة/.test(document.querySelector('#hist').textContent), null, {timeout: 15000});
    await sleep(800);
    const ask = dialogs.find(m => m.includes('هل تريد إضافتها')) || '';
    check('asks to add the missing one, naming it, with the summary',
          ask.includes('lost77') && ask.includes('موجود 1 · غيّر اسمه 1 · غير موجود 1') && !ask.includes('oldname5'), ask.slice(0, 160));
    const rows = await page.$$eval('#hist tbody tr', trs => trs.map(tr => tr.textContent.replace(/\s+/g, ' ').trim()));
    const row = u => rows.find(r => r.includes(u)) || '';
    check('found on the panel', row('user003').includes('موجود في اللوحة'), row('user003'));
    check('renamed: shows the user that now holds its password, no add button',
          row('oldname5').includes('تغيّر اسمه') && row('oldname5').includes('user005') && !row('oldname5').includes('إضافة'), row('oldname5'));
    check('the missing one was added (accepted) and is now on the panel',
          row('lost77').includes('موجود في اللوحة') && !row('lost77').includes('غير موجود'), row('lost77'));
    const s = await api(page, '/admin/api/search?gate=' + gid + '&q=lost77');
    check('it really exists on the panel now, with its password',
          (s.results || []).some(r => r.username === 'lost77' && r.password === 'lostpw77'), JSON.stringify(s).slice(0, 160));
    const h = await page.evaluate(k => JSON.parse(localStorage.getItem(k)), 'xm_lines_history_' + me.account + '_' + gid);
    check('history keeps one row for it (updated in place, not duplicated)',
          h.filter(x => x.username === 'lost77').length === 1 && h.length === 3 && h.find(x => x.username === 'lost77').re_added);

    // رفض الإضافة: يبقى «غير موجود» بزرّ «إضافة» لكلٍّ منه
    await page.evaluate(([k, h]) => localStorage.setItem(k, JSON.stringify(h)),
      ['xm_lines_history_' + me.account + '_' + gid, [mk('gone88', 'gonepw88')]]);
    await page.reload();
    await page.waitForSelector('#hist button[data-vday]', {timeout: 8000});
    page.removeAllListeners('dialog');
    page.on('dialog', d => d.dismiss());
    await page.click('#hist button[data-vday]');
    await page.waitForSelector('#hist button[data-add="gone88"]', {timeout: 15000});
    check('declined: marked missing with a per-row «إضافة» button',
          (await page.textContent('#hist')).includes('غير موجود في اللوحة'));
  } catch (e) { check('no exception', false, e.message); }
  finally { await browser.close(); app.kill(); f.kill(); fs.rmSync(dataDir, {recursive: true, force: true}); }
  console.log(`\nResult: ${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();

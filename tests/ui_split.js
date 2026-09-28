// Browser test of the split subscriptions (الاشتراكات المجزّأة) UI:
//  admin opens the feature for one client → that client picks "6 أشهر" on a 15-month
//  package, sees the bell, rotates, re-sells on «حسابات متبقية»; the other client sees nothing new.
//   NODE_PATH=<dir with playwright-core> node tests/ui_split.js     (SHOTS_DIR=… for screenshots)
const { chromium } = require('playwright-core');
const { spawn, execSync } = require('child_process');
const path = require('path'); const fs = require('fs'); const os = require('os');
const ROOT = path.dirname(__dirname);
const FALCON_PORT = 9751, APP_PORT = 9752;
const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'uisplit_'));
const SHOTS = process.env.SHOTS_DIR || '';
const EXE = execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim();
let pass = 0, fail = 0;
const check = (l, c, x='') => { c ? (pass++, console.log(`  PASS  ${l}${x?'  ('+x+')':''}`)) : (fail++, console.log(`  FAIL  ${l}${x?'  ('+x+')':''}`)); };
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function up(u){ for (let i=0;i<80;i++){ try { execSync(`curl -s -o /dev/null ${u}`); return; } catch(e){} await sleep(150); } }
const api = (page, url, body) => page.evaluate(async ([u, b]) => (await fetch(u, b === undefined ? {} :
  {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(b)})).json(), [url, body]);
const shot = async (page, name) => { if (SHOTS) await page.screenshot({path: path.join(SHOTS, name + '.png'), fullPage: true}); };

(async () => {
  const falcon = spawn('python3', [path.join(ROOT,'tests/mock_falcon.py'), String(FALCON_PORT), 'fk'], {stdio:'ignore'});
  const app = spawn('python3', [path.join(ROOT,'xm_lines.py'), 'web'],
    {stdio:'ignore', env:{...process.env, XM_DATA:dataDir, XM_BIND:'127.0.0.1', XM_PORT:String(APP_PORT)}});
  await up(`http://127.0.0.1:${APP_PORT}/admin/login`);
  const browser = await chromium.launch({executablePath: EXE, args:['--no-sandbox']});
  const APP = `http://127.0.0.1:${APP_PORT}`, FALCON = `http://127.0.0.1:${FALCON_PORT}/api/v1`;
  const adminCtx = await browser.newContext();
  const userCtx = await browser.newContext({permissions:['clipboard-read','clipboard-write']});
  const plainCtx = await browser.newContext();
  const admin = await adminCtx.newPage(), user = await userCtx.newPage(), plain = await plainCtx.newPage();
  user.on('dialog', d => d.accept());
  const gate = {name:'بوابة فالكون', mode:'falcon', api_url:FALCON, api_key:'fk', host:'http://falcon.host',
                guide_url:'https://guide.ssouq.com/#activate/falcon'};
  try {
    await admin.goto(APP + '/admin/setup');
    await api(admin, '/admin/api/setup', {password:'admin123'});
    let r = await api(admin, '/admin/api/accounts', {name:'عميل التجزئة', user:'split', password:'pw_split', gates:[gate]});
    check('client created (feature off)', r.ok === true && !r.accounts[0].split, r.error || '');
    await api(admin, '/admin/api/accounts', {name:'عميل عادي', user:'plain', password:'pw_plain', gates:[gate]});

    // ---- المدير يفتح الميزة من نافذة الحساب ----
    await admin.evaluate(() => localStorage.setItem('xm_admin_tab', 'accounts'));
    await admin.goto(APP + '/admin/accounts');
    await admin.waitForSelector('[data-toggle]');
    await admin.click('.acct:first-child [data-toggle]');
    await admin.click('.acct:first-child [data-edit]');
    await admin.waitForSelector('#acctModal:not([hidden])');
    check('switch in the account window, off by default', await admin.isVisible('#acc_split') && !(await admin.isChecked('#acc_split')));
    await admin.check('#acc_split');
    await shot(admin, 'split-admin-modal');
    await admin.click('#save');
    await admin.waitForSelector('#acctModal', {state:'hidden'});
    check('list tags the client', (await admin.textContent('#list')).includes('اشتراكات مجزّأة'));
    r = await api(admin, '/admin/api/accounts');
    check('saved on the account', r.accounts.find(a => a.user === 'split').split === true);

    // ---- العميل: الإنشاء بنوع البيع ----
    await user.goto(APP + '/admin/login');
    await api(user, '/admin/api/login', {user:'split', password:'pw_split'});
    await user.goto(APP + '/admin');
    await user.waitForSelector('input[name="pkg"]');
    check('bell and «حسابات متبقية» link shown', await user.isVisible('#bellBtn') && await user.isVisible('#lnkRemain'));
    check('picker hidden for the first (1-month) package', await user.isHidden('#sliceBox'));
    await user.check('input[name="pkg"][value="190"]');
    await user.waitForSelector('#sliceBox:not([hidden])');
    const opts = await user.$$eval('#slices span', els => els.map(e => e.textContent));
    check('picker offers كامل / 6 / 3 / شهر', opts.join('|') === 'كامل ١٥ شهرًا|6 أشهر|3 أشهر|شهر', opts.join('|'));
    await user.click('#slices label:nth-child(2)');
    check('button names the slice', (await user.textContent('#createTxt')).includes('جزء 6 أشهر'));
    check('hint explains the username change', (await user.textContent('#sliceHint')).includes('متبقي 9 أشهر'));
    await shot(user, 'split-create-picker');
    await user.click('#create');
    await user.waitForSelector('#splitMsg:not([hidden])', {timeout:15000});
    const sm = await user.textContent('#splitMsg');
    check('created: tells when the name changes', sm.includes('يتغيّر اسم المستخدم تلقائيًا') && sm.includes('متبقي 9 أشهر'), sm);
    check('timing line is grey info, not a red error', await user.isVisible('#timing')
          && (await user.textContent('#msg')).trim() === ''
          && await user.$eval('#timing', e => getComputedStyle(e).color) !== await user.$eval('#msg', e => getComputedStyle(e).color));
    check('message links to «حسابات متبقية»', await user.$$eval('#splitMsg a', els => els.some(e => e.getAttribute('href').endsWith('/remaining'))));
    check('message warns the email is not set up (no SMTP here)', sm.includes('بريد التنبيه غير مضبوط'), sm);
    await user.click('#bellBtn');
    await user.waitForFunction(() => document.getElementById('notesItems').textContent.includes('بِيع'), null, {timeout: 5000}).catch(() => {});
    check('bell shows the sale in the log right away', (await user.textContent('#notesItems')).includes('بِيع جزء 6 أشهر'));
    check('…without a badge (it is his own action)', await user.isHidden('#bellN'));
    await user.click('#bellBtn');
    const made = (await user.textContent('#res')).trim();
    const u1 = (made.match(/User (\S+)/) || [])[1];
    check('line still copied as usual', /^Host http:\/\/falcon\.host User \d+ Pass \d+ Guide /.test(made), made);
    await user.check('input[name="pkg"][value="167"]');
    check('picker hides for a non-15 package', await user.isHidden('#sliceBox'));
    check('button back to plain text', !(await user.textContent('#createTxt')).includes('جزء'));

    // ---- صفحة حسابات متبقية ----
    await user.goto(APP + '/admin/remaining');
    await user.waitForSelector('#activeList .card');
    check('running slice listed', (await user.textContent('#activeList')).includes(u1), u1);
    check('shows what remains after it', (await user.textContent('#activeList')).includes('بعده متبقي 9 أشهر'));
    await shot(user, 'split-remaining-active');
    await user.click(`#activeList [data-rot]`);                     // «غيّر الآن» (يقبل التأكيد)
    await user.waitForSelector('#availList .card', {timeout:15000});
    const avail = await user.textContent('#availList');
    const u2first = (await user.$eval('#availList .creds .mono', e => e.textContent)).trim();
    check('renamed and moved to «متبقية للبيع»', u2first && u2first !== u1 && avail.includes('متبقي'), `${u1} → ${u2first}`);
    check('grouped by what remains', /متبقي\s*1[45] شهرًا/.test(avail), avail.slice(0, 80));
    // «تراجع»: يعود الاسم القديم ويعود الجزء، ثم يُغيَّر من جديد لبقية الاختبار
    check('undo button names the old username', (await user.getAttribute('#availList [data-undo]', 'title')).includes(u1));
    await user.click('#availList [data-undo]');                    // يقبل التأكيد
    await user.waitForSelector('#activeList .card', {timeout:15000});
    check('undo: back to the old name, slice running again', (await user.textContent('#activeList')).includes(u1)
          && (await user.textContent('#availList')).includes('لا خطوط متاحة'));
    await user.click(`#activeList [data-rot]`);
    await user.waitForSelector('#availList .card', {timeout:15000});
    const u2 = (await user.$eval('#availList .creds .mono', e => e.textContent)).trim();
    check('bell badge counts the notification', await user.isVisible('#bellN'));
    await user.click('#availList [data-sell]');
    await user.waitForSelector('.sellbox');
    await shot(user, 'split-remaining-sell');
    await user.fill('.sellbox input.t', 'أبو محمد');
    await user.click('[data-dosell]');
    await user.waitForSelector('#activeList .card', {timeout:10000});
    const clip = await user.evaluate(() => navigator.clipboard.readText());
    check('sold: line copied for the new customer', clip.includes(`User ${u2} `), clip);
    check('slice #2 running with the customer', (await user.textContent('#activeList')).includes('الجزء 2') &&
          (await user.textContent('#activeList')).includes('أبو محمد'));
    await user.click('#readAll');
    await sleep(500);
    check('mark all read clears the badge', await user.isHidden('#bellN'));

    // ---- تجربة على خطٍّ تجريبي من الصفحة ----
    const meU = await api(user, '/admin/api/me');
    const made2 = await api(user, '/admin/api/create', {gate: meU.gates[0].id, package_id: 167, count: 1});
    const trialU = made2.lines[0].username, trialP = made2.lines[0].password;
    await user.goto(APP + '/admin/remaining');
    await user.waitForSelector('#tGo');
    check('trial-test block shown in settings', (await user.textContent('#testBox')).includes('تجربة على خطٍّ تجريبي'));
    await user.fill('#tUser', trialU);
    await user.click('#tGo');                                        // يقبل التأكيد
    await user.waitForSelector('#tRes .ok-t, #tRes .err', {timeout: 15000});
    const tres = await user.textContent('#tRes');
    check('trial test renames it and keeps the password', tres.includes('نجحت التجربة') && tres.includes(trialU)
          && tres.includes('كما هي') && tres.includes(trialP), tres);
    check('gate now shows «جُرِّب … بنجاح»', (await user.textContent('.gates')).includes('جُرِّب التغيير التلقائي بنجاح'));
    await shot(user, 'split-trial-test');
    await user.setViewportSize({width: 390, height: 844});
    await shot(user, 'split-remaining-mobile');
    const overflow = await user.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    check('no horizontal scroll on a phone', !overflow);
    await user.goto(APP + '/admin');                              // الجوال: الرابط في القائمة الجانبية
    await user.waitForSelector('#menuBtn');
    await user.click('#menuBtn');
    await sleep(300);
    check('phone: «حسابات متبقية» in the side menu', await user.isVisible('#sideRemain'));
    await shot(user, 'split-create-mobile-menu');
    await user.setViewportSize({width: 1280, height: 800});
    await user.goto(APP + '/admin');
    await user.waitForSelector('#bellBtn:not([hidden])');
    await user.click('#bellBtn');
    check('bell opens the notifications dropdown', await user.isVisible('#notesPanel') &&
          (await user.textContent('#notesItems')).includes('تغيّر اسم المستخدم'));
    await shot(user, 'split-create-bell');

    // ---- العميل الذي لم تُفتح له ----
    await plain.goto(APP + '/admin/login');
    await api(plain, '/admin/api/login', {user:'plain', password:'pw_plain'});
    await plain.goto(APP + '/admin');
    await plain.waitForSelector('input[name="pkg"]');
    await plain.check('input[name="pkg"][value="190"]');
    await sleep(200);
    check('other client: no bell, no link, no picker', await plain.isHidden('#bellBtn') && await plain.isHidden('#lnkRemain')
          && await plain.isHidden('#sliceBox'));
    await plain.goto(APP + '/admin/remaining');
    check('other client: the page sends him back', new URL(plain.url()).pathname === '/admin', plain.url());
  } catch (e) {
    fail++; console.log('  FAIL  exception: ' + (e && e.stack || e));
  } finally {
    await browser.close(); falcon.kill(); app.kill();
  }
  console.log(`\nResult: ${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();

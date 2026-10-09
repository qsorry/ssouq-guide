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
    await admin.goto(APP + '/admin/accounts#accounts');   // تبويب الحسابات من عنوانه
    await admin.reload();                                  // وبياناتٌ جديدة إن كانت الصفحة نفسها
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
    check('picker offers كامل / 12 / 6 / 3 / شهر / مدة أخرى', opts.join('|') === 'كامل ١٥ شهرًا|12 شهرًا|6 أشهر|3 أشهر|شهر|مدة أخرى', opts.join('|'));
    // «مدة أخرى»: مربعٌ لعدد الأشهر — ١٥ ليست جزءًا فتُرفض قبل أي إرسال، و١٠ (بالأرقام العربية) تُقبل
    check('months box hidden until «مدة أخرى»', await user.isHidden('#sliceBox .slice-n'));
    await user.click('#slices label:nth-child(6)');
    await user.waitForSelector('#sliceBox .slice-n:not([hidden])');
    check('«مدة أخرى» opens the months box, focused', await user.evaluate(() => (document.activeElement || {}).name === 'slice_n'));
    await user.fill('input[name="slice_n"]', '15');
    check('15 months is not a part: the hint says the range', (await user.textContent('#sliceHint')).includes('من 1 إلى 14'));
    await user.click('#create');
    check('…and create refuses it before sending anything', (await user.textContent('#msg')).includes('من 1 إلى 14') && await user.isHidden('#resBox'),
          await user.textContent('#msg'));
    await user.fill('input[name="slice_n"]', '١٠');
    check('10 months typed (Arabic digits): the button and the hint follow', (await user.textContent('#createTxt')).includes('جزء 10 أشهر')
          && (await user.textContent('#sliceHint')).includes('متبقي 5 أشهر'), await user.textContent('#createTxt'));
    await shot(user, 'split-create-custom');
    await user.click('#slices label:nth-child(3)');
    check('a quick choice hides the months box again', await user.isHidden('#sliceBox .slice-n'));
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
    const sid = ((await user.textContent('#splitBatch')) || '').trim();
    check('message names the creation session (S + date-time)', /^S\d{6}-\d{6}$/.test(sid), sid);
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
    // ---- جلسات الإنشاء: المعرّف على البطاقة وفي الإشعار وفي قسم الجلسات، «عرض» يرشّح و«نسخ» ينسخ ----
    check('sessions section lists the creation session with its id and count', await user.isVisible('#sess')
          && (await user.$eval('#sessList .srow .sid', e => e.textContent.trim())) === sid
          && (await user.textContent('#sessList .srow b')).trim() === '1 يوزر', await user.textContent('#sessList'));
    check('card carries the session chip', (await user.$eval('#activeList .card [data-q]', e => e.dataset.q)) === sid);
    check('notification carries the session chip', (await user.$$eval('#notesList [data-q]', (els, id) => els.some(e => e.dataset.q === id), sid)));
    await user.click('#sessList .srow [data-q]');
    check('«عرض» filters by the session id (search box filled, row highlighted)', (await user.inputValue('#q')) === sid
          && !!(await user.$('#sessList .srow.on')) && (await user.textContent('#activeList')).includes(u1));
    await user.evaluate(() => navigator.clipboard.writeText(''));
    await user.click('#sessList .srow [data-scopy]');
    await sleep(150);
    check('session «نسخ» copies its lines', (await user.evaluate(() => navigator.clipboard.readText())) === made);
    await user.click('#sessList .srow [data-q]');
    check('pressing again clears the filter', (await user.inputValue('#q')) === '' && !(await user.$('#sessList .srow.on')));
    await user.goto(APP + '/admin/remaining?s=' + sid);
    await user.waitForSelector('#sessList .srow.on');
    check('?s=<id> in the link (from the create message) opens the session', (await user.inputValue('#q')) === sid);
    await user.goto(APP + '/admin/remaining');
    await user.waitForSelector('#activeList .card');
    // ---- نسخ دفعةً واحدة: «نسخ آخر N المنشأة» في رأس القسم، و«نسخ الكل» في عنوان كل مجموعة (لا يطويها) ----
    check('«نسخ آخر N» shown with 10 as the default', await user.isVisible('#copyLast') && (await user.inputValue('#lastN')) === '10');
    await user.evaluate(() => navigator.clipboard.writeText(''));
    await user.click('#copyLast');
    await sleep(150);
    const lastClip = await user.evaluate(() => navigator.clipboard.readText());
    check('copies the newest created line(s) as full lines', lastClip === made, lastClip);
    const wasOpen = await user.$eval('#activeList details.gp', d => d.open);
    await user.evaluate(() => navigator.clipboard.writeText(''));
    await user.click('#activeList details.gp > summary button[data-gcopy]');
    await sleep(150);
    check('group «نسخ الكل» copies the group and leaves the fold as it was',
          (await user.evaluate(() => navigator.clipboard.readText())) === made
          && (await user.$eval('#activeList details.gp', d => d.open)) === wasOpen);
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
    const sellOpts = await user.$$eval('.sellbox .opts span', els => els.map(e => e.textContent));
    check('sell offers 12 months on a line that has them', sellOpts[0] === '12 شهرًا', sellOpts.join('|'));
    check('…but 6 months stays preselected (12 is chosen on purpose)',
          await user.$eval('.sellbox input:checked', e => e.value) === '6');
    // «مدة أخرى» في البيع: حدّها ما بقي في الخط، وما زاد يُرفض قبل أي بيع
    check('sell offers «مدة أخرى» too', sellOpts.includes('مدة أخرى'), sellOpts.join('|'));
    await user.click('.sellbox .opt:has-text("مدة أخرى")');
    await user.waitForSelector('.sellbox .opt-n:not([hidden])');
    const most = +(((await user.textContent('.sellbox .opt-n')).match(/من 1 إلى (\d+)/) || [])[1] || 0);
    check('sell: the months box names the line\'s limit', most >= 14, await user.textContent('.sellbox .opt-n'));
    await user.fill('.sellbox .opt-n input', String(most + 5));
    await user.click('[data-dosell]');
    await user.waitForSelector('#toast.bad', {timeout: 3000}).catch(() => {});
    check('sell: more months than the line has is refused before selling', (await user.textContent('#toast')).includes('من 1 إلى ' + most)
          && await user.isVisible('.sellbox'), await user.textContent('#toast'));
    await user.click('.sellbox .opt:has-text("6 أشهر")');
    check('sell: back to 6 months hides the box', await user.isHidden('.sellbox .opt-n'));
    await user.fill('.sellbox input[id^="cu_"]', 'أبو محمد');
    await user.click('[data-dosell]');
    await user.waitForSelector('#activeList .card', {timeout:10000});
    const clip = await user.evaluate(() => navigator.clipboard.readText());
    check('sold: line copied for the new customer', clip.includes(`User ${u2} `), clip);
    check('slice #2 running with the customer', (await user.textContent('#activeList')).includes('الجزء 2') &&
          (await user.textContent('#activeList')).includes('أبو محمد'));
    await user.click('#readAll');
    await sleep(500);
    check('mark all read clears the badge', await user.isHidden('#bellN'));

    // ---- التنظيم: مجموعاتٌ بنوع الجزء وما يبقى بعده، بعددها ----
    const gid = (await api(user, '/admin/api/me')).gates[0].id;
    const m3 = await api(user, '/admin/api/create', {gate: gid, package_id: 190, count: 3, slice_months: 3});
    const m1 = await api(user, '/admin/api/create', {gate: gid, package_id: 190, count: 2, slice_months: 1});
    check('created 3 × 3 months and 2 × 1 month', m3.lines.length === 3 && m1.lines.length === 2, m3.error || m1.error || '');
    await user.goto(APP + '/admin/remaining');
    await user.waitForSelector('#activeList .gp');
    const heads = await user.$$eval('#activeList .gp > summary', els => els.map(e => e.textContent.replace(/\s+/g, ' ').trim()));
    check('three groups, longest slice first', heads.length === 3 && heads[0].includes('جزء 6 أشهر')
          && heads[1].includes('جزء 3 أشهر') && heads[2].includes('جزء شهر'), heads.join(' | '));
    check('group title: count, slice and what remains after', /^3 يوزرات جزء 3 أشهر/.test(heads[1]) && heads[1].includes('بعده متبقي 12 شهرًا')
          && /^2 يوزر جزء شهر/.test(heads[2]) && heads[2].includes('بعده متبقي 14 شهرًا'), heads[1] + ' | ' + heads[2]);
    check('group shows its nearest change', heads[1].includes('أقرب تغيير') && heads[1].includes('بعد'), heads[1]);
    check('several groups: all folded at first', await user.$$eval('#activeList .gp', els => els.every(e => !e.open)));
    await user.click('#activeList .gp:nth-child(2) > summary');
    check('tap opens the group with its lines', await user.$$eval('#activeList .gp:nth-child(2) .card', els => els.length) === 3
          && await user.isVisible('#activeList .gp:nth-child(2) [data-copy]'));
    await user.reload();
    await user.waitForSelector('#activeList .gp');
    check('opened group stays open after reload, others folded', await user.$$eval('#activeList .gp', els => els.map(e => e.open).join()) === 'false,true,false');
    const needle = m1.lines[1].username;
    const arabic = needle.replace(/\d/g, d => '٠١٢٣٤٥٦٧٨٩'[d]);                  // يُكتب بالأرقام العربية
    await user.fill('#q', arabic);
    await user.waitForFunction(() => document.querySelectorAll('#activeList .card').length === 1, null, {timeout: 5000}).catch(() => {});
    check('search (Arabic digits) finds the one line and opens its group', await user.$$eval('#activeList .card', els => els.length) === 1
          && (await user.textContent('#activeList')).includes(needle) && await user.isVisible(`#activeList [data-rot]`));
    check('search: other lists say no result', (await user.textContent('#availList')).includes('لا نتيجة'));
    check('tiles keep the totals while searching', await user.$eval('#tiles [data-go="active"] b', e => e.textContent) === '6');
    await user.fill('#q', '');
    await user.waitForFunction(() => document.querySelectorAll('#activeList .gp').length === 3, null, {timeout: 5000}).catch(() => {});
    check('clearing the search restores the groups as they were', await user.$$eval('#activeList .gp', els => els.map(e => e.open).join()) === 'false,true,false');
    // مع نص الشرح تصير الأزرار ثلاثة («نسخ السطر» · «نسخ الشرح» · «غيّر الآن»)
    const sa = (await api(admin, '/admin/api/accounts')).accounts.find(a => a.user === 'split');
    r = await api(admin, '/admin/api/accounts', {...sa, copy_guide: true});
    check('admin turns on the guide text for him', r.ok === true && r.accounts.find(a => a.user === 'split').copy_guide === true, r.error || '');
    await user.reload();
    await user.waitForSelector('#activeList .gp[open] [data-kind="msg"]');
    await user.setViewportSize({width: 360, height: 780});
    await sleep(200);
    const actsH = await user.$$eval('#activeList .gp[open] .card .acts', els => Math.max(...els.map(e => e.getBoundingClientRect().height)));
    check('phone (360px): card buttons stay on one row', actsH > 0 && actsH < 50, String(actsH));
    await shot(user, 'split-remaining-groups-mobile');
    await user.setViewportSize({width: 1280, height: 800});

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
    await user.click('#bellBtn');                                    // يُغلق القائمة

    // ---- بديلٌ عن رقمٍ لم يُعثر عليه: «مدة البديل» — ١٢ شهرًا من باقة ١٥ ----
    const OLD = '555000111222';
    await user.fill('#searchQ', OLD);
    await user.click('#searchBtn');
    await user.waitForSelector('#mkRepl', {timeout: 8000});
    await user.click('#mkRepl');
    await user.waitForSelector('#mkGo', {timeout: 8000});
    check('replacement: no duration choice on the first (1-month) package', await user.isHidden('#rSliceBox'));
    await user.check('input[name="rpkg"][value="190"]');
    await user.waitForSelector('#rSliceBox:not([hidden])');
    const ropts = await user.$$eval('#rSlices span', els => els.map(e => e.textContent));
    check('replacement: the 15-month package offers كامل / 12 / 6 / 3 / شهر / مدة أخرى',
          ropts.join('|') === 'كامل ١٥ شهرًا|12 شهرًا|6 أشهر|3 أشهر|شهر|مدة أخرى', ropts.join('|'));
    check('replacement: the full 15 months by default', await user.$eval('input[name="rslice"]:checked', e => e.value) === '0'
          && (await user.textContent('#mkGo')).trim() === 'إنشاء البديل وربطه بـ ' + OLD);
    await user.click('#rSlices label:nth-child(2)');
    check('replacement: the 12-month choice names itself on the button', (await user.textContent('#mkGo')).includes('إنشاء البديل (12 شهرًا) وربطه بـ ' + OLD),
          await user.textContent('#mkGo'));
    // «مدة أخرى»: ١٠ أشهر للبديل، تُكتب بالأرقام العربية
    await user.click('#rSlices label:nth-child(6)');
    await user.waitForSelector('#rSliceBox .slice-n:not([hidden])');
    await user.fill('input[name="rslice_n"]', '١٠');
    check('replacement: the button names the 10 months', (await user.textContent('#mkGo')).includes('إنشاء البديل (10 أشهر) وربطه بـ ' + OLD),
          await user.textContent('#mkGo'));
    check('replacement: the hint says 5 months remain after it', (await user.textContent('#rSliceHint')).includes('متبقي 5 أشهر'));
    await shot(user, 'split-replacement-duration');
    await user.click('#mkGo');
    await user.waitForSelector('#mkSplit', {timeout: 15000});
    const rok = await user.textContent('#mkBox .msg.ok');
    check('replacement: created and linked with its duration', rok.includes('أُنشئ البديل (10 أشهر) وارتبط بـ ' + OLD), rok);
    const rsp = await user.textContent('#mkSplit');
    check('replacement: tracked — the username changes, then 5 months remain',
          rsp.includes('يتغيّر اسم المستخدم تلقائيًا') && rsp.includes('متبقي 5 أشهر'), rsp);
    check('replacement: its row names the 10 months', (await user.textContent('#mkBox table')).includes('جزء 10 أشهر'));
    const rclip = await user.evaluate(() => navigator.clipboard.readText());
    const rUser = (await user.textContent('#mkBox table td.m')).trim();
    check('replacement: copied as usual — the guide text (on for him above) with the new user',
          rclip.startsWith('📲') && rclip.includes('User: ' + rUser + '\n'), rclip.slice(-60));
    await shot(user, 'split-replacement-done');
    await user.click('#searchBtn');                                  // البحث عن الرقم القديم من جديد
    await user.waitForSelector('#searchRes .lnk', {timeout: 8000});
    const lnk = await user.textContent('#searchRes .lnk');
    check('searching the old number: replaced, and by how many months', lnk.includes('استُبدل بـ') && lnk.includes('جزء 10 أشهر'), lnk);

    // ---- العميل الذي لم تُفتح له ----
    await plain.goto(APP + '/admin/login');
    await api(plain, '/admin/api/login', {user:'plain', password:'pw_plain'});
    await plain.goto(APP + '/admin');
    await plain.waitForSelector('input[name="pkg"]');
    await plain.check('input[name="pkg"][value="190"]');
    await sleep(200);
    check('other client: no bell, no link, no picker', await plain.isHidden('#bellBtn') && await plain.isHidden('#lnkRemain')
          && await plain.isHidden('#sliceBox'));
    await plain.fill('#searchQ', '555000999888');
    await plain.click('#searchBtn');
    await plain.waitForSelector('#mkRepl', {timeout: 8000});
    await plain.click('#mkRepl');
    await plain.waitForSelector('#mkGo', {timeout: 8000});
    await plain.check('input[name="rpkg"][value="190"]');
    await sleep(200);
    check('other client: no duration on his replacement either', await plain.isHidden('#rSliceBox')
          && (await plain.textContent('#mkGo')).trim() === 'إنشاء البديل وربطه بـ 555000999888');
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

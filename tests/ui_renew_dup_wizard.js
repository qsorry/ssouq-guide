// اختبار متصفح لمعالج المكرر في «البحث والمفقود»: إنشاء البديل ← تغيير القديم ← إرسال للبديل ← إرسال ما عُدّل،
// بخلفيةٍ وهمية للإنشاء والتغيير والإرسال (لا لوحة ولا واتساب): الخطوات بترتيبها، والنص المعدَّل يُرسَل، والتخطّي يُبقي المكرر معلّقًا.
//   NODE_PATH=<dir with playwright-core> node tests/ui_renew_dup_wizard.js
const { chromium } = require('playwright-core');
const { spawn, execSync } = require('child_process');
const path = require('path'); const fs = require('fs'); const os = require('os');
const ROOT = path.dirname(__dirname), PORT = 9795;
const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'uirwizard_'));
const SHOTS = process.env.SHOTS_DIR || '';
const EXE = execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim();
let pass = 0, fail = 0;
const check = (l, c, x = '') => { c ? (pass++, console.log(`  PASS  ${l}${x ? '  (' + x + ')' : ''}`)) : (fail++, console.log(`  FAIL  ${l}${x ? '  (' + x + ')' : ''}`)); };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const api = (page, url, body) => page.evaluate(async ([u, b]) => (await fetch(u, b === undefined ? {} :
  {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(b)})).json(), [url, body]);
const shot = async (page, name) => { if (SHOTS) await page.screenshot({path: path.join(SHOTS, name + '.png')}); };

const d0 = new Date(Date.now() - 60 * 864e5).toISOString().slice(0, 10), exp = new Date(Date.now() + 300 * 864e5).toISOString().slice(0, 10);
const d1 = new Date(Date.now() - 90 * 864e5).toISOString().slice(0, 10);
const ln = (o, u, n) => ({order: o, date: d0, phone: '0500000001', customer: n, username: u, password: 'pw' + u, host: 'http://m.ink', months: 12, expiry: exp, product: 'اشتراك 12 شهر'});
fs.writeFileSync(path.join(dataDir, 'renew_store_lines.json'), JSON.stringify({lines: [
  Object.assign(ln('100', '363816609180', 'الأول'), {date: d1, phone: '0500000001'}), Object.assign(ln('200', '363816609180', 'الثاني'), {phone: '0500000002'}),]}));


(async () => {
  const app = spawn('python3', [path.join(ROOT, 'xm_lines.py'), 'web'], {stdio: 'ignore', env: {...process.env, XM_DATA: dataDir, XM_BIND: '127.0.0.1', XM_PORT: String(PORT)}});
  for (let i = 0; i < 80; i++) { try { execSync(`curl -s -o /dev/null http://127.0.0.1:${PORT}/admin/login`); break; } catch (e) {} await sleep(150); }
  const browser = await chromium.launch({executablePath: EXE, args: ['--no-sandbox']});
  const APP = `http://127.0.0.1:${PORT}`;
  try {
    const ctx = await browser.newContext({viewport: {width: 390, height: 844}});
    const page = await ctx.newPage(); const errs = []; page.on('pageerror', e => errs.push(e.message));
    await page.goto(APP + '/admin/setup'); await api(page, '/admin/api/setup', {password: 'admin123'});
    await api(page, '/admin/api/renew/config', {renew: {panels: [{name: 'مرح', hosts: ['http://m.ink'], account_id: '', gate_id: ''}]}});
    // خلفيةٌ وهمية للمعالجة: حالٌ يتقدّم مع كل خطوة
    const S = {done: null, msgs: [], posts: [], failRename: true};
    const item = () => ({order: '200', username: '363816609180', customer: 'الثاني', phone: '0500000002', date: d0, remaining: '10 أشهر', suggest: 10,
      first_order: '100', first_customer: 'الأول', first_phone: '0500000001', can_create: true,
      need: !S.done ? ['create'] : [...(!S.done.renamed ? ['rename'] : []), ...S.msgs.filter(m => !(m.sent && m.sent.ok)).map(m => m.kind === 'new' ? 'send_new' : 'send_old')],
      done: S.done, msgs: S.msgs.map((m, idx) => ({idx, ...m}))});
    await page.route('**/api/renew/order?q=*', async rt => { const r = await rt.fetch(); const j = await r.json();
      (j.rows || []).forEach(x => { x.dup_todo = item().need.length ? [item()] : []; x.dup_chain = [
        {role: 'first', order: '100', date: d1, customer: 'الأول', phone: '0500000001'},
        {role: 'later', order: '200', date: d0, customer: 'الثاني', phone: '0500000002', replacement: S.done ? S.done.new : '', months: 10, renamed: S.done && S.done.renamed ? S.done.renamed.to : '', old_missing: false, rename_error: '', msg_new: S.msgs[0] ? (S.msgs[0].sent ? 'sent' : 'unsent') : '', msg_old: ''}]; }); await rt.fulfill({response: r, json: j}); });
    await page.route('**/api/renew/dup-state*', rt => rt.fulfill({json: {item: item(), wa_linked: true}}));
    await page.route('**/api/renew/dup-create', async rt => { S.posts.push(['create', rt.request().postDataJSON()]);
      S.done = {new: 'newuser1', months: 10, renamed: null, old_missing: false, rename_error: ''};
      S.msgs = [{kind: 'new', name: 'الثاني', phone: '966500000002', text: 'بيانات البديل', sent: null}];
      await rt.fulfill({json: {ok: true, username: 'newuser1', months: 10, replaces: '363816609180'}}); });
    await page.route('**/api/renew/dup-rename', async rt => { S.posts.push(['rename', rt.request().postDataJSON()]);
      if (S.capRename) { S.capRename = false; return rt.fulfill({json: {need_captcha: true, error: 'اللوحة تطلب كود التحقّق', need_connect: [{account_id: 'a', gate_id: 'g', name: 'مرح الأرشيف', archive: true, has_creds: true, panel_base: 'http://p', panel_user: 'u'}]}}); }
      if (S.failRename) { S.failRename = false; return rt.fulfill({status: 502, json: {error: 'تعذّر قراءة بوكيهات الخط من صفحة التعديل — غيّر اسم المستخدم يدويًا'}}); }
      S.done.renamed = {from: '363816609180', to: 'old_x', line: 'l'}; S.msgs.push({kind: 'old', name: 'الأول', phone: '966500000001', text: 'ما عُدّل', sent: null});
      await rt.fulfill({json: {ok: true, renamed: S.done.renamed}}); });
    await page.route('**/api/renew/dup-send', async rt => { const b = rt.request().postDataJSON(); S.posts.push(['send', b]);
      S.msgs[b.idx].sent = {ok: true}; await rt.fulfill({json: {ok: true}}); });
    page.on('dialog', d => d.accept());

    await page.goto(APP + '/admin/renew#secLost'); await page.waitForSelector('#loQ'); await sleep(500);
    await page.fill('#loQ', '200'); await page.click('#loFind');
    await page.waitForSelector('#loBody .lcDupWz');
    check('unprocessed duplicate shows the warning and the wizard button', (await page.textContent('#loBody')).includes('ولم تتم معالجته') && await page.isVisible('.lcDupWz'));
    const bt = await page.textContent('#loBody');
    check('the chain names both owners and says the first account was not changed yet', bt.includes('مَن لديه هذا المكرر') && bt.includes('الأول') && bt.includes('الثاني') && bt.includes('لا شيء بعد'));
    await page.evaluate(() => document.querySelector('.dch').scrollIntoView()); await shot(page, 'chain'); await page.click('.lcDupWz'); await page.waitForSelector('#wzModal:not(.hidden) #wzGo');
    const cur = () => page.textContent('.wzst li.cur');
    check('wizard opens on step 1 (create)', (await cur()).includes('إنشاء'), await cur());
    await page.fill('#wzM', '10'); await page.click('#wzGo');
    await page.waitForSelector('#wzLater');
    check('create posts without renaming, then renames the first at once', S.posts[0][0] === 'create' && S.posts[0][1].rename_old === false && S.posts[0][1].months === 10 && S.posts[1][0] === 'rename', JSON.stringify(S.posts.slice(0, 2)));
    check('rename failed: the step is mandatory (no skip), says so, and shows the missing link in the chain', !(await page.$('#wzSkip')) && (await page.textContent('#wzFoot')).includes('حلقة مفقودة') && /تعذّر|اربط/.test(await page.textContent('#wzFoot')));
    await page.click('#wzGo');
    await page.waitForFunction(() => /إرسال للبديل/.test(document.querySelector('.wzst li.cur')?.textContent || ''));
    check('step 3 shows the replacement message', (await page.inputValue('#wzT')) === 'بيانات البديل');
    await page.fill('#wzT', 'بيانات البديل معدّلة'); await page.click('#wzGo');
    await page.waitForFunction(() => /إرسال ما عُدّل/.test(document.querySelector('.wzst li.cur')?.textContent || ''));
    check('send uses the edited text on message 0 via wa', S.posts[3][0] === 'send' && S.posts[3][1].idx === 0 && S.posts[3][1].text === 'بيانات البديل معدّلة' && S.posts[3][1].mode === 'wa', JSON.stringify(S.posts[3]));
    check('step 4 shows the old owner message', (await page.inputValue('#wzT')) === 'ما عُدّل');
    await page.click('#wzSkip');
    check('skipping the last step finishes the wizard', (await page.textContent('#wzBody')).includes('اكتملت المعالجة'));
    await shot(page, 'wizard-done');
    await page.click('#wzEnd'); await sleep(600);
    check('after closing the chain shows the replacement and the renamed first account', /newuser1/.test(await page.textContent('#loBody')) && /old_x/.test(await page.textContent('#loBody')));
    check('a skipped (unsent) message keeps the duplicate pending, listing only that step', /المتبقي من المعالجة: إرسال ما عُدّل/.test(await page.textContent('#loBody')));
    // صفحة «المكرر والبدائل»: «أنشئ بديلًا» يفتح المعالج نفسه (بلا confirm منفصل) ويمرّر بوابة الإنشاء المختارة
    S.done = null; S.msgs = []; S.posts = []; S.failRename = false;
    await page.route('**/api/renew/duplicates', rt => rt.fulfill({json: {rows: [{order: '200', username: '363816609180', host: 'http://m.ink', panel_name: 'مرح', customer: 'الثاني', phone: '0500000002',
      date: d0, remaining: '10 أشهر', suggest: 10, first_order: '100', first_customer: 'الأول', first_phone: '0500000001', done: null, expired: false, can_create: true, sub: ''}],
      pending: 1, done: 0, expired: 0, gates: [], messages: [], wa_linked: true}}));
    await page.evaluate(() => loadDup()); await page.waitForSelector('#dupBody .dupMk', {state: 'attached'});
    await page.evaluate(() => document.querySelector('#dupBody .dupMk').click());
    await page.waitForSelector('#wzModal:not(.hidden) #wzGo');
    check('the duplicates page opens the same wizard on step 1', (await page.textContent('.wzst li.cur')).includes('إنشاء'));
    await page.click('#wzGo'); await page.waitForFunction(() => /إرسال للبديل/.test(document.querySelector('.wzst li.cur')?.textContent || ''));
    check('create + rename ran from the duplicates page', S.posts[0][0] === 'create' && S.posts[1][0] === 'rename', JSON.stringify(S.posts.map(x => x[0])));
    // اللوحة (أرشيف) تطلب كودًا: يظهر الدخول فيدخل آليًا ثم يطلب الكود، وبعد كتابته يُكمل تغيير الأول تلقائيًا
    S.done = null; S.msgs = []; S.posts = []; S.capRename = true; S.connects = [];
    await page.route('**/api/renew/dup-captcha*', rt => rt.fulfill({contentType: 'image/png', body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==', 'base64')}));
    await page.route('**/api/renew/dup-connect', async rt => { const b = rt.request().postDataJSON(); S.connects.push(b);
      await rt.fulfill({json: b.captcha === '123' ? {ok: true} : {ok: false, need_captcha: true, error: b.captcha ? 'الكود غير صحيح' : ''}}); });
    await page.evaluate(() => document.querySelector('#dupBody .dupMk').click());
    await page.waitForSelector('#wzGo'); await page.click('#wzGo');
    await page.waitForSelector('#wzCnC');
    check('archive gate asks for a code: auto login first (saved creds), then shows the code box', S.connects.length === 1 && S.connects[0].captcha === '' && S.connects[0].gate_id === 'g' && await page.isVisible('#wzCnImg'), JSON.stringify(S.connects));
    await page.fill('#wzCnC', '123'); await page.click('#wzCnGo');
    await page.waitForFunction(() => /إرسال للبديل/.test(document.querySelector('.wzst li.cur')?.textContent || ''));
    check('the typed code is sent and the rename is retried automatically', S.connects[1].captcha === '123' && S.posts.filter(x => x[0] === 'rename').length === 2 && S.done.renamed, JSON.stringify(S.connects));
    check('no page errors', errs.length === 0, errs.join(' | '));
  } finally { await browser.close(); app.kill(); fs.rmSync(dataDir, {recursive: true, force: true}); }
  console.log(`\nResult: ${pass} passed, ${fail} failed`); process.exit(fail ? 1 : 0);
})();

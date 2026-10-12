// اختبار متصفح لتبويب «الردّ على الشكاوى» في صفحة التجديد: الحالات (جاهز · جارٍ · الردّ جاهز · بلا يوزر · لا طلب · خطأ)،
// ونصّ الردّ بجدول تطبيقات اشتراك العميل، وربط يوزرٍ أُنشئ له بلصق سطره، والنسخ والإرسال اليدوي وتسجيله.
//   NODE_PATH=<dir with playwright-core> node tests/ui_reply.js     (SHOTS_DIR=… للقطات)
const { chromium } = require('playwright-core');
const { spawn, execSync } = require('child_process');
const path = require('path'); const fs = require('fs'); const os = require('os');
const ROOT = path.dirname(__dirname), PORT = 9796;
const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'uireply_'));
const SHOTS = process.env.SHOTS_DIR || '';
const EXE = execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim();
let pass = 0, fail = 0;
const check = (l, c, x = '') => { c ? (pass++, console.log(`  PASS  ${l}${x ? '  (' + x + ')' : ''}`)) : (fail++, console.log(`  FAIL  ${l}${x ? '  (' + x + ')' : ''}`)); };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const api = (page, url, body) => page.evaluate(async ([u, b]) => (await fetch(u, b === undefined ? {} :
  {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(b)})).json(), [url, body]);
const shot = async (page, name) => { if (SHOTS) await page.screenshot({path: path.join(SHOTS, name + '.png'), fullPage: true}); };

const d0 = new Date(Date.now() - 30 * 864e5).toISOString().slice(0, 10), exp = new Date(Date.now() + 60 * 864e5).toISOString().slice(0, 10);
fs.writeFileSync(path.join(dataDir, 'renew_store_lines.json'), JSON.stringify({lines: [
  {order: '138', date: d0, phone: '0500000001', customer: 'ali', username: '333426852552', password: '4784316512', host: 'http://ssouqhost.vip:80',
   months: 3, expiry: exp, product: 'اشتراك كاسبر IPTV لمدة 3 أشهر'}]}));
// طلبٌ في فهرس الطلبات بلا يوزر (لا رمز سلة في الاختبار، فلا سجلّ يُسأل) ⇒ «أنشئ له»
fs.writeFileSync(path.join(dataDir, 'renew_index.json'), JSON.stringify({orders: {'400': {phone: '0500000004', date: d0, months: 12}}}));

(async () => {
  const app = spawn('python3', [path.join(ROOT, 'xm_lines.py'), 'web'], {stdio: 'ignore', env: {...process.env, XM_DATA: dataDir, XM_BIND: '127.0.0.1', XM_PORT: String(PORT)}});
  for (let i = 0; i < 80; i++) { try { execSync(`curl -s -o /dev/null http://127.0.0.1:${PORT}/admin/login`); break; } catch (e) {} await sleep(150); }
  const browser = await chromium.launch({executablePath: EXE, args: ['--no-sandbox']});
  const APP = `http://127.0.0.1:${PORT}`;
  try {
    const ctx = await browser.newContext({viewport: {width: 390, height: 844}});
    await ctx.grantPermissions(['clipboard-read', 'clipboard-write']);
    const page = await ctx.newPage(); const errs = []; page.on('pageerror', e => errs.push(e.message));
    await page.goto(APP + '/admin/setup'); await api(page, '/admin/api/setup', {password: 'admin123'});
    // بوابة كاسبر بهوست الاشتراك: منها رابط الشرح واسم السيرفر
    await api(page, '/admin/api/accounts', {name: 'عميل', user: 'u1', password: 'pw_u1_long',
      gates: [{name: 'بوابة كاسبر', host: 'http://ssouqhost.vip:80', mode: 'web', web_flavor: 'casper', panel_base: 'http://panel.x', panel_user: 'pu', panel_pass: 'pp'}]});
    await page.goto(APP + '/admin/renew#secReply'); await page.waitForSelector('#rpQ'); await sleep(400);
    const st = () => page.getAttribute('#rpBox', 'data-state'), msg = () => page.textContent('#rpMsg');
    check('the tab opens from its hash and is ready', await page.isVisible('#secReply') && await st() === 'ready' && (await msg()).includes('اكتب'));
    check('nav has the new tab', (await page.textContent('.jump a[data-tab="reply"]')).includes('الردّ على الشكاوى'));

    // الردّ جاهز لطلبٍ مسحوب بيوزره
    await page.fill('#rpQ', '١٣٨'); await page.click('#rpFind');
    await page.waitForFunction(() => document.querySelector('#rpBox').dataset.state !== 'loading');
    const text = await page.inputValue('#rpText');
    check('found state: reply ready for the customer', await st() === 'found' && (await msg()).includes('الردّ جاهز لـali'), await msg());
    check('card: customer, phone and the credentials', (await page.textContent('#rpBody')).includes('ali') && (await page.textContent('#rpBody')).includes('333426852552'));
    check('text: head with the order, guide text, host/user/pass', text.includes('*ali*') && text.includes('طلبكم رقم *138*')
      && text.includes('📲 طريقة التثبيت والتفعيل') && text.includes('Host: http://ssouqhost.vip:80\nUser: 333426852552\nPass: 4784316512'), text.slice(0, 200));
    check('text: casper apps table and the look-alike warning', text.includes('اشتراك كاسبر') && text.includes('CASPER VIP') && text.includes('تطبيقًا عشوائيًا'));
    check('no-user block hidden, reply block shown', await page.isHidden('#rpNoUser') && await page.isVisible('#rpReply'));
    check('wa link present for a customer with a phone', await page.isVisible('#rpWa'));
    await page.click('#rpCopy'); await sleep(200);
    check('copy button confirms', (await page.textContent('#rpCopy')).includes('نُسخ'));
    await shot(page, 'reply-ready');
    // الإرسال اليدوي يُسجَّل في سجل الرسائل بنوع reply
    await page.evaluate(() => { document.querySelector('#rpWa').addEventListener('click', e => e.preventDefault()); });
    await page.click('#rpWa'); await sleep(400);
    const log = await api(page, '/admin/api/renew/dup-log');
    const rows = log.log || [];
    check('manual send logged as reply', rows.some(r => r.kind === 'reply' && r.order === '138' && r.how === 'manual'), JSON.stringify(rows).slice(0, 200));
    check('manual whatsapp shows «تم الإرسال» like the linked number', (await page.textContent('#rpSent')).includes('تم الإرسال ✓'), await page.textContent('#rpSent'));
    // مراجعة الشكاوى بلا جلسة لوحة: تلميحٌ لا عطل
    await page.click('#cqLoad'); await page.waitForFunction(() => !document.querySelector('#cqLoad').disabled);
    check('complaints pull without a panel session explains itself', (await page.textContent('#cqMsg')).includes('سحب الشكاوى من جهازي'), await page.textContent('#cqMsg'));

    // الردّ من صفّ الشكوى نفسه: شكاوى محفوظة (كما تحفظها الإضافة) ← «جهّز الردّ» يفتح الردّ تحت الصفّ، ورقم الشكوى رابط
    fs.writeFileSync(path.join(dataDir, 'renew_complaints.json'), JSON.stringify({at: '2026-10-12 01:00', rows: [
      {id: '1455683', cid: '2078174950', order: '138', order_sid: '', customer: 'ali', status: 'بانتظار رد التاجر', type: 'المنتج لا يعمل', text: '', date: '', phone: '', url: 'https://complaint.salla.sa/2078174950'},
      {id: '2', cid: '2', order: '999000', order_sid: '', customer: 'x', status: 'بانتظار الحل من التاجر', type: '', text: '', date: '', phone: '', url: ''},
      {id: '3', cid: '3', order: '5', order_sid: '', customer: 'y', status: 'مغلقة', type: '', text: '', date: '', phone: '', url: ''}]}));
    await page.click('#cqLoad'); await page.waitForFunction(() => !document.querySelector('#cqLoad').disabled);
    check('complaints list shows only the merchant-waiting ones', (await page.$$('#cqBody tr')).length === 2 && (await page.textContent('#cqSum')).includes('٢'));
    // تبويب «مفقودٌ وعليه شكوى»: الطلب 138 يوزره لا على لوحة (هوست غير مربوط لا يُعدّ مفقودًا)، والطلب 999000 بلا سجل → لا شيء مفقود هنا
    check('filter chips: lost-with-complaint and all', (await page.$$('#cqChips .fchip')).length === 2 && (await page.textContent('#cqChips')).includes('مفقودٌ وعليه شكوى'));
    await page.click('#cqChips .fchip[data-f="lost"]'); await sleep(200);
    check('lost filter: empty here with a clear note', (await page.$$('#cqBody tr')).length === 0 && (await page.textContent('#cqMsg')).includes('لا شكوى على طلبٍ مفقود'));
    await page.click('#cqChips .fchip[data-f="all"]'); await sleep(200);
    check('back to all', (await page.$$('#cqBody tr')).length === 2);
    check('complaint number links to the panel', (await page.getAttribute('#cqBody tr:first-child td:first-child a', 'href')) === 'https://complaint.salla.sa/2078174950');
    await page.click('#cqBody .cqGo'); await page.waitForSelector('#cqSheetBody .cqT');
    const inl = await page.inputValue('#cqSheetBody .cqT');
    check('reply opens in a sheet with the credentials and a sticky action bar', inl.includes('طلبكم رقم *138*') && inl.includes('User: 333426852552') && await page.isVisible('#cqSheetFoot .cqCopy') && await page.isVisible('#cqSalla'));
    check('the search box was not touched (still the earlier query)', (await page.inputValue('#rpQ')) === '١٣٨');
    await page.evaluate(() => { document.querySelector('#cqSheetFoot .cqWa').addEventListener('click', e => e.preventDefault()); });
    await page.click('#cqSheetFoot .cqWa'); await page.waitForFunction(() => ((document.querySelector('#cqSheetFoot [data-sent]') || {}).textContent || '').includes('تم الإرسال'));
    check('manual whatsapp from the row says sent and marks the row', (await page.textContent('#cqBody tr[data-o="138"] .cqS')).includes('تم الردّ'));
    check('panel state shown in the sheet', /لم يُتحقّق|غير مربوط بلوحة|مفقود من اللوحة/.test(await page.textContent('#cqSheetBody')));
    // «نسخ الردّ وفتح الشكوى في سلة»: ينسخ ويفتح رابط الشكوى ويُعلَّم مردودًا عليها (كيف: salla)
    await page.evaluate(() => { window.__opened = []; window.open = (u) => { const w = {set location(v) { window.__opened.push(String(v)); }}; window.__opened.push(String(u)); return w; }; });
    await page.click('#cqSheetFoot .cqSallaGo'); await sleep(500);
    const opened = await page.evaluate(() => window.__opened);
    check('copy+open: the complaint url opened and the status says pasted-in-salla', opened.includes('https://complaint.salla.sa/2078174950') && (await page.textContent('#cqSheetFoot [data-sent]')).includes('فُتحت الشكوى في سلة'), JSON.stringify(opened));
    const log2 = (await api(page, '/admin/api/renew/dup-log')).log || [];
    check('logged as sent via salla', log2.some(x => x.kind === 'reply' && x.how === 'salla' && x.order === '138'));
    check('header has a prominent salla link', (await page.getAttribute('#cqSalla', 'href')) === 'https://complaint.salla.sa/2078174950');
    await page.click('#cqClose'); check('close hides the sheet', await page.isHidden('#cqModal'));
    await page.click('#cqBody tr[data-o="999000"] .cqGo'); await page.waitForSelector('#cqSheetBody .rp-note');
    check('unknown order: note in the sheet with a jump to the box', (await page.textContent('#cqSheetBody')).includes('لا طلب برقم') && await page.isVisible('#cqSheetFoot .cqToBox'));
    await page.keyboard.press('Escape'); check('escape closes', await page.isHidden('#cqModal'));
    // «تم الردّ»: الصفّ عُلّم بالإرسال اليدوي، ويُلغى ويُعاد بالزرّ، ويبقى بعد إعادة التحميل
    await page.waitForSelector('#cqBody tr[data-o="138"].cq-done');
    check('manual send marked the complaint as replied (dimmed, with time)', (await page.textContent('#cqBody tr[data-o="138"] .cqS')).includes('تم الردّ ✓'));
    await page.click('#cqBody tr[data-o="138"] .cqDone'); await page.waitForFunction(() => !document.querySelector('#cqBody tr[data-o="138"].cq-done'));
    check('unmark via the button', !(await page.textContent('#cqBody tr[data-o="138"] .cqS')).includes('تم'));
    await page.click('#cqBody tr[data-o="138"] .cqDone'); await page.waitForSelector('#cqBody tr[data-o="138"].cq-done');
    check('mark via the button, replied rows sort last', (await page.$$eval('#cqBody tr[data-o]', t => t.filter(x => !x.classList.contains('cq-r')).map(x => x.dataset.o))).join() === '999000,138');
    fs.unlinkSync(path.join(dataDir, 'renew_complaints.json'));

    // بلا يوزر: الطلب معروف من الفهرس ⇒ «أنشئ له» ولصق السطر يربطه ويجهّز الردّ
    await page.fill('#rpQ', '400'); await page.click('#rpFind');
    await page.waitForFunction(() => document.querySelector('#rpBox').dataset.state !== 'loading');
    check('no_user: found state with the create hint, reply hidden', await st() === 'found' && (await msg()).includes('بلا يوزر')
      && await page.isVisible('#rpNoUser') && await page.isHidden('#rpReply') && (await page.textContent('#rpHint')).includes('أنشئ له يوزرًا'), await msg());
    await shot(page, 'reply-nouser');
    await page.fill('#rpLine', 'Host http://ssouqhost.vip:80 User 4001 Pass 4002 Guide https://guide.ssouq.com/#activate/casper');
    await page.click('#rpLinkGo');
    await page.waitForFunction(() => !document.querySelector('#rpReply').classList.contains('hidden'), null, {timeout: 15000});
    const t2 = await page.inputValue('#rpText');
    check('pasted line links the order and the reply is ready with it', t2.includes('User: 4001\nPass: 4002') && t2.includes('طلبكم رقم *400*') && t2.includes('سيرفر كاسبر'), t2.replace(/\n/g, ' ¶ ').slice(0, 700));
    check('after linking, a new search finds it in the store lines', (await api(page, '/admin/api/renew/reply?q=400')).src === 'store');

    // لا طلب
    await page.fill('#rpQ', '999000'); await page.click('#rpFind');
    await page.waitForFunction(() => document.querySelector('#rpBox').dataset.state !== 'loading');
    check('empty state for an unknown order, with retry', await st() === 'empty' && (await msg()).includes('لا طلب برقم') && await page.isVisible('#rpRetry') && await page.isHidden('#rpReply'));

    // خطأ من الخادم ثم إعادة المحاولة
    await page.route('**/api/renew/reply?q=138*', rt => rt.fulfill({status: 500, body: '{}'}), {times: 1});
    await page.fill('#rpQ', '138'); await page.click('#rpFind');
    await page.waitForFunction(() => document.querySelector('#rpBox').dataset.state !== 'loading');
    check('server error → error state with retry', await st() === 'error' && await page.isVisible('#rpRetry'));
    await page.click('#rpRetry'); await page.waitForFunction(() => document.querySelector('#rpBox').dataset.state === 'found');
    check('retry recovers', await st() === 'found');
    // المسح
    await page.click('#rpClear');
    check('clear resets to ready and hides the result', await st() === 'ready' && await page.isHidden('#rpReply') && (await page.inputValue('#rpQ')) === '');
    // الإضافة بلا صلاحية الأصل: التمهيد (OPTIONS) والنداء نفسه يحملان ترويسات CORS لأصل chrome-extension:// على /api/renew/ وحدها
    const pre = execSync(`curl -s -i -X OPTIONS -H "Origin: chrome-extension://abc" -H "Access-Control-Request-Method: POST" -H "Access-Control-Request-Headers: authorization,content-type" ${APP}/admin/api/renew/panel-cookie`).toString();
    check('extension preflight answered with CORS headers', /HTTP\/1\.[01] 204/.test(pre) && /Access-Control-Allow-Origin: chrome-extension:\/\/abc/i.test(pre) && /Allow-Headers: Authorization, Content-Type/i.test(pre), pre.split('\n').slice(0, 8).join(' | '));
    const real = execSync(`curl -s -i -H "Origin: chrome-extension://abc" ${APP}/admin/api/renew/extension-version`).toString();
    check('the actual call carries the CORS origin too (401 without auth, header still there)', /Access-Control-Allow-Origin: chrome-extension:\/\/abc/i.test(real), real.split('\n').slice(0, 6).join(' | '));
    const other = execSync(`curl -s -i -H "Origin: https://evil.example" ${APP}/admin/api/renew/extension-version`).toString();
    check('a web origin gets no CORS header', !/Access-Control-Allow-Origin/i.test(other));
    const nonrenew = execSync(`curl -s -i -X OPTIONS -H "Origin: chrome-extension://abc" ${APP}/admin/api/accounts`).toString();
    check('paths outside /api/renew/ are not opened', /HTTP\/1\.[01] 404/.test(nonrenew) && !/Access-Control-Allow-Origin/i.test(nonrenew));
    check('no page errors', errs.length === 0, errs.join(' | '));
  } finally {
    await browser.close(); app.kill(); fs.rmSync(dataDir, {recursive: true, force: true});
  }
  console.log(`\nResult: ${pass} passed, ${fail} failed`); process.exit(fail ? 1 : 0);
})();

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
    check('no page errors', errs.length === 0, errs.join(' | '));
  } finally {
    await browser.close(); app.kill(); fs.rmSync(dataDir, {recursive: true, force: true});
  }
  console.log(`\nResult: ${pass} passed, ${fail} failed`); process.exit(fail ? 1 : 0);
})();

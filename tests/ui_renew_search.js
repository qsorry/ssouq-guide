// اختبار متصفح لبحث «البحث والمفقود» في صفحة التجديد: الحالات (جاهز · جارٍ · وُجد · لا نتيجة · خطأ)، ومنع الطلب
// المكرّر، وإهمال ردٍّ قديم بعد بحثٍ أحدث، والانقطاع والمهلة وإعادة المحاولة، والمسح، وألّا يُفحص المفقود عند فتح
// التبويب، ومستخدمَين يبحثان معًا.
//   NODE_PATH=<dir with playwright-core> node tests/ui_renew_search.js     (SHOTS_DIR=… للقطات)
const { chromium } = require('playwright-core');
const { spawn, execSync } = require('child_process');
const path = require('path'); const fs = require('fs'); const os = require('os');
const ROOT = path.dirname(__dirname), PORT = 9794;
const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'uirsearch_'));
const SHOTS = process.env.SHOTS_DIR || '';
const EXE = execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim();
let pass = 0, fail = 0;
const check = (l, c, x = '') => { c ? (pass++, console.log(`  PASS  ${l}${x ? '  (' + x + ')' : ''}`)) : (fail++, console.log(`  FAIL  ${l}${x ? '  (' + x + ')' : ''}`)); };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const api = (page, url, body) => page.evaluate(async ([u, b]) => (await fetch(u, b === undefined ? {} :
  {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(b)})).json(), [url, body]);
const shot = async (page, name) => { if (SHOTS) await page.screenshot({path: path.join(SHOTS, name + '.png')}); };

const d0 = new Date(Date.now() - 60 * 864e5).toISOString().slice(0, 10), exp = new Date(Date.now() + 300 * 864e5).toISOString().slice(0, 10);
const ln = (o, u, n) => ({order: o, date: d0, phone: '0500000001', customer: n, username: u, password: 'pw' + u, host: 'http://m.ink', months: 12, expiry: exp, product: 'اشتراك 12 شهر'});
fs.writeFileSync(path.join(dataDir, 'renew_store_lines.json'), JSON.stringify({lines: [
  ln('287314660', '363816609180', 'عبدالله'), ln('287314660', '691869829206', 'عبدالله'), ln('111222333', '555000111', 'سارة')]}));

(async () => {
  const app = spawn('python3', [path.join(ROOT, 'xm_lines.py'), 'web'], {stdio: 'ignore', env: {...process.env, XM_DATA: dataDir, XM_BIND: '127.0.0.1', XM_PORT: String(PORT)}});
  for (let i = 0; i < 80; i++) { try { execSync(`curl -s -o /dev/null http://127.0.0.1:${PORT}/admin/login`); break; } catch (e) {} await sleep(150); }
  const browser = await chromium.launch({executablePath: EXE, args: ['--no-sandbox']});
  const APP = `http://127.0.0.1:${PORT}`;
  try {
    const ctx = await browser.newContext({viewport: {width: 390, height: 844}});
    const page = await ctx.newPage(); const errs = []; page.on('pageerror', e => errs.push(e.message));
    await page.goto(APP + '/admin/setup'); await api(page, '/admin/api/setup', {password: 'admin123'});
    const r = await api(page, '/admin/api/renew/config', {renew: {panels: [{name: 'مرح', hosts: ['http://m.ink'], account_id: '', gate_id: ''}]}});
    fs.writeFileSync(path.join(dataDir, 'renew_panel_lines.json'), JSON.stringify({panels: {[r.renew.panels[0].id]: {name: 'مرح', count: 1, by_user: {'363816609180': {username: '363816609180'}}}}}));
    const reqs = []; page.on('request', q => { const u = q.url(); if (u.includes('/api/renew/')) reqs.push(u.replace(APP, '')); });
    await page.goto(APP + '/admin/renew#secLost'); await page.waitForSelector('#loQ'); await sleep(600);
    check('opening the tab does not start a lost scan', !reqs.some(u => u.includes('/api/renew/lost')), reqs.filter(u => u.includes('lost')).join());
    check('opening the tab asks the index status (background build)', reqs.some(u => u.includes('/api/renew/index-status')));
    const st = () => page.getAttribute('#loBox', 'data-state'), msg = () => page.textContent('#loMsg');
    check('ready state with a hint', await st() === 'ready' && (await msg()).includes('اكتب'));

    // وُجد: بالأرقام العربية وبمسافات
    await page.fill('#loQ', '٢٨٧ ٣١٤ ٦٦٠'); await page.click('#loFind');
    await page.waitForFunction(() => document.querySelector('#loBox').dataset.state !== 'loading');
    check('found state for arabic digits with spaces', await st() === 'found' && (await page.$$('#loBody .lc')).length === 2, await msg());
    check('button back to «بحث» after the result', (await page.textContent('#loFind')) === 'بحث' && !(await page.isDisabled('#loFind')));
    check('the extra user of a covered order is not called missing', (await page.textContent('#loBody')).includes('يوزر زائد'));
    await shot(page, 'search-found');

    // لا نتيجة + إعادة المحاولة ظاهرة
    await page.fill('#loQ', '999000999'); await page.click('#loFind');
    await page.waitForFunction(() => document.querySelector('#loBox').dataset.state !== 'loading');
    check('empty state says not found, with retry', await st() === 'empty' && (await msg()).includes('لم يُعثر') && await page.isVisible('#loRetry'));
    check('no cards left from the previous search', await page.isHidden('#loWrap'));
    await shot(page, 'search-empty');

    // الضغط المتكرر: طلبٌ واحد، و«جارٍ» يظهر أثناء الطلب فقط
    await page.route('**/api/renew/order?q=111222333*', async rt => { await sleep(700); await rt.continue(); });
    reqs.length = 0;
    await page.fill('#loQ', '111222333');
    await page.click('#loFind'); await page.click('#loFind', {force: true}); await page.press('#loQ', 'Enter');
    await sleep(150);
    check('loading state while the request is in flight', await st() === 'loading' && (await page.textContent('#loFind')).includes('جارٍ'));
    await shot(page, 'search-loading');
    await page.waitForFunction(() => document.querySelector('#loBox').dataset.state !== 'loading');
    check('repeated clicks send one request', reqs.filter(u => u.includes('/api/renew/order?q=111222333')).length === 1, String(reqs.length));
    check('and the result shows', await st() === 'found' && (await page.textContent('#loBody')).includes('555000111'));
    await page.unroute('**/api/renew/order?q=111222333*');

    // ردٌّ قديم بعد بحثٍ أحدث يُهمل
    await page.route('**/api/renew/order?q=111222333*', async rt => { await sleep(1200); await rt.continue().catch(() => {}); });
    await page.fill('#loQ', '111222333'); await page.click('#loFind'); await sleep(100);
    await page.fill('#loQ', '287314660'); await page.click('#loFind');
    await page.waitForFunction(() => document.querySelector('#loBox').dataset.state !== 'loading'); await sleep(1400);
    check('a newer search wins over a slower older one', (await page.textContent('#loBody')).includes('363816609180')
      && !(await page.textContent('#loBody')).includes('555000111') && await st() === 'found');
    await page.unroute('**/api/renew/order?q=111222333*');

    // انقطاع الاتصال ثم إعادة المحاولة
    await page.route('**/api/renew/order?**', rt => rt.abort('internetdisconnected'));
    await page.fill('#loQ', '111222333'); await page.click('#loFind');
    await page.waitForFunction(() => document.querySelector('#loBox').dataset.state !== 'loading');
    check('the previous result is not left under the error', await page.isHidden('#loWrap'));
    check('network failure = error state, retry visible, button usable', await st() === 'error' && (await msg()).includes('الاتصال')
      && await page.isVisible('#loRetry') && !(await page.isDisabled('#loFind')), await msg());
    await shot(page, 'search-error');
    await page.unroute('**/api/renew/order?**');
    await page.click('#loRetry');
    await page.waitForFunction(() => document.querySelector('#loBox').dataset.state !== 'loading');
    check('retry after the network is back finds it', await st() === 'found');

    // خطأ الخادم لا يُظهر تفاصيل تقنية
    await page.route('**/api/renew/order?**', rt => rt.fulfill({status: 500, contentType: 'application/json', body: '{"error":"Traceback KeyError x"}'}));
    await page.click('#loFind', {force: true}); await page.fill('#loQ', '287314660'); await page.click('#loFind');
    await page.waitForFunction(() => document.querySelector('#loBox').dataset.state !== 'loading');
    check('server error shown in plain words, no technical detail', await st() === 'error' && !(await msg()).includes('Traceback'), await msg());
    await page.unroute('**/api/renew/order?**');

    // المهلة
    await page.evaluate(() => { window.__searchMs = 400; });
    await page.route('**/api/renew/order?**', async rt => { await sleep(1500); await rt.continue().catch(() => {}); });
    await page.fill('#loQ', '111222333'); await page.click('#loFind');
    await page.waitForFunction(() => document.querySelector('#loBox').dataset.state !== 'loading', null, {timeout: 5000});
    check('timeout ends loading with a retry', await st() === 'error' && (await msg()).includes('أطول') && await page.isVisible('#loRetry'), await msg());
    await page.unroute('**/api/renew/order?**'); await page.evaluate(() => { window.__searchMs = 0; });

    // المسح
    await page.click('#loClear');
    check('clear empties the field and results, back to ready', (await page.inputValue('#loQ')) === '' && await page.isHidden('#loWrap') && await st() === 'ready');

    // المفقود بزرّه وحده، ولا طلب مكرّر
    reqs.length = 0;
    await page.route('**/api/renew/lost?**', async rt => { await sleep(600); await rt.continue(); });
    await page.click('#lsLoad'); await sleep(100); await page.click('#lsLoad', {force: true});
    await sleep(100); await page.waitForFunction(() => !document.querySelector('#lsLoad').disabled);
    await page.unroute('**/api/renew/lost?**');
    check('lost scan runs on its button, once', reqs.filter(u => u.includes('/api/renew/lost')).length === 1);
    check('lost scan shows a summary', (await page.textContent('#lsMsg')).includes('فُحص'));

    // مستخدمان معًا
    const p2 = await ctx.newPage(); await p2.goto(APP + '/admin/renew#secLost'); await p2.waitForSelector('#loQ');
    await Promise.all([(async () => { await page.fill('#loQ', '287314660'); await page.click('#loFind'); })(),
                       (async () => { await p2.fill('#loQ', '111222333'); await p2.click('#loFind'); })()]);
    await page.waitForFunction(() => document.querySelector('#loBox').dataset.state === 'found');
    await p2.waitForFunction(() => document.querySelector('#loBox').dataset.state === 'found');
    check('two users searching at once each get their own result', (await page.textContent('#loBody')).includes('363816609180')
      && (await p2.textContent('#loBody')).includes('555000111'));
    check('no horizontal scroll on a phone', await page.evaluate(() => document.documentElement.scrollWidth) <= 390);
    check('no page errors', !errs.length, errs.join(' | '));
  } catch (e) { fail++; console.log('  FAIL  exception', e.message); }
  finally { await browser.close(); app.kill(); fs.rmSync(dataDir, {recursive: true, force: true}); }
  console.log(`\nResult: ${pass} passed, ${fail} failed`); process.exit(fail ? 1 : 0);
})();

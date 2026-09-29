// Browser test of the store card on the content admin page ("أعداد المحتوى في منتجات المتجر"): an M3U is uploaded for
// Casper, the Salla app is saved (client id, secrets) and its token arrives by a signed app.store.authorize webhook; the
// suggested products come from the (mock) store, one is linked to Casper and saved; the preview shows old → new without
// writing; "حدّث الآن" writes the counts into the product in Salla and marks it approved; nothing overflows a 360px
// screen and no script error. No internet: Salla is tests/mock_salla_api.py.
//   NODE_PATH=<dir with playwright-core> node tests/ui_store.js     (SHOTS_DIR=… for screenshots)
const { chromium } = require('playwright-core');
const { spawn, execSync } = require('child_process');
const crypto = require('crypto');
const path = require('path'); const fs = require('fs'); const os = require('os');
const ROOT = path.dirname(__dirname);
const APP_PORT = 9813, MOCK_PORT = 9814;
const SHOTS = process.env.SHOTS_DIR || '';
const EXE = execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim();
let pass = 0, fail = 0;
const check = (l, c, x='') => { c ? (pass++, console.log(`  PASS  ${l}${x?'  ('+x+')':''}`)) : (fail++, console.log(`  FAIL  ${l}${x?'  ('+x+')':''}`)); };
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function up(u){ for (let i=0;i<80;i++){ try { execSync(`curl -s -o /dev/null ${u}`); return; } catch(e){} await sleep(150); } }
const AUTH = 'Basic ' + Buffer.from('admin:envpass123').toString('base64');

function playlist(movies) {
  const H = 'http://panel.example:8080', C = 'u/p';
  let s = '#EXTM3U\n', n = 1;
  for (let i = 0; i < movies; i++) s += `#EXTINF:-1 group-title="VOD",Film ${String(i).padStart(4, '0')} (2020)\n${H}/movie/${C}/${n++}.mkv\n`;
  for (let i = 0; i < 30; i++) for (const e of [1, 2]) s += `#EXTINF:-1 group-title="Series",Show ${i} S01 E0${e}\n${H}/series/${C}/${n++}.mkv\n`;
  for (let i = 0; i < 45; i++) s += `#EXTINF:-1 group-title="Live",Channel ${i}\n${H}/live/${C}/${n++}.ts\n`;
  return s;
}

(async () => {
  const DATA = fs.mkdtempSync(path.join(os.tmpdir(), 'uistore_'));
  const MOCK = `http://127.0.0.1:${MOCK_PORT}`;
  const app = spawn('python3', [path.join(ROOT, 'xm_lines.py'), 'web'], {stdio: 'ignore', env: {...process.env,
    XM_DATA: DATA, XM_BIND: '127.0.0.1', XM_PORT: String(APP_PORT), XM_ADMIN_PASSWORD: 'envpass123',
    SALLA_API: MOCK, SALLA_ACCOUNTS: MOCK, SALLA_ADMIN_TOKEN: ''}});
  const mock = spawn('python3', [path.join(ROOT, 'tests', 'mock_salla_api.py'), String(MOCK_PORT)], {stdio: 'ignore'});
  await up(`http://127.0.0.1:${APP_PORT}/robots.txt`);
  await up(`${MOCK}/__state`);
  const browser = await chromium.launch({executablePath: EXE, args: ['--no-sandbox']});
  const APP = `http://127.0.0.1:${APP_PORT}`;
  const errors = [];
  try {
    const up1 = await fetch(`${APP}/admin/api/content/admin/upload?s=casper&name=c.m3u`, {method: 'POST',
      headers: {Authorization: AUTH, 'Content-Type': 'application/octet-stream'}, body: playlist(650)});
    check('رفع ملف كاسبر (650 فيلمًا و30 مسلسلًا)', up1.status === 200);

    const ctx = await browser.newContext({viewport: {width: 360, height: 780}, extraHTTPHeaders: {Authorization: AUTH}});
    const ap = await ctx.newPage();
    ap.on('pageerror', e => errors.push(e.message));
    await ap.goto(APP + '/admin/content');
    await ap.waitForSelector('#store:not([hidden])');
    check('البطاقة ظاهرة: غير مربوط، والربط مفتوح', (await ap.textContent('#sChip')) === 'غير مربوط'
          && await ap.$eval('#sConn', e => e.open) && (await ap.textContent('#sHookUrl')).endsWith('/salla/webhook'));
    check('ولا منتجات مربوطة', (await ap.textContent('#sLinks')).includes('لا منتجات مربوطة'));

    await ap.fill('#sCid', 'cid-1'); await ap.fill('#sSecret', 'csecret-1'); await ap.fill('#sHook', 'hooksecret');
    await ap.click('#sAuthSave');
    await ap.waitForFunction(() => document.querySelector('#sMsg').textContent.startsWith('حُفظ'));
    check('حفظ التطبيق: ينتظر تثبيته', (await ap.textContent('#sAuth')).includes('ثبّته في متجرك')
          && await ap.$eval('#sSecret', e => e.value === '' && e.placeholder.includes('محفوظ')));

    const payload = JSON.stringify({event: 'app.store.authorize', merchant: 831097886,
      data: {access_token: 'tok-1', refresh_token: 'ref-1', expires: Math.floor(Date.now() / 1000) + 14 * 86400,
             scope: 'products.read_write offline_access', token_type: 'bearer'}});
    const sig = crypto.createHmac('sha256', 'hooksecret').update(payload).digest('hex');
    const wh = await fetch(`${APP}/salla/webhook`, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Salla-Signature': sig}, body: payload});
    check('الويبهوك الموقَّع يوصل الرمز', wh.status === 200);
    await ap.reload();
    await ap.waitForSelector('#store:not([hidden])');
    const auth = await ap.textContent('#sAuth');
    check('مربوطٌ بتطبيق سلة ويتجدّد وحده', auth.includes('مربوط بتطبيق سلة ✓') && auth.includes('يتجدّد وحده'), auth);

    await ap.click('#sSuggest');
    await ap.waitForSelector('#sFound .prow');
    const found = await ap.$$eval('#sFound .prow', rs => rs.map(r => [r.dataset.pid, r.querySelector('select').value]));
    check('المقترحة من المتجر بسيرفراتها', JSON.stringify(found.sort()) === JSON.stringify(
      [['153695876', 'falcon'], ['1557813796', 'casper'], ['889146346', 'smart']].sort()), JSON.stringify(found));
    await ap.click('#sFound [data-pid="1557813796"] [data-add]');
    check('«اربط»: في المربوطة ولم يُحفظ بعد', (await ap.textContent('#sLinks')).includes('لم يُحفظ بعد')
          && await ap.$eval('#sFound [data-pid="1557813796"] [data-add]', b => b.disabled));
    await ap.check('#sOn');
    await ap.click('#sSave');
    await ap.waitForFunction(() => document.querySelector('#sMsg').textContent === 'حُفظ');
    check('حُفظ: ينتظر أول تحديثٍ بيدك، والتحديث التلقائي مفعّل', (await ap.textContent('#sLinks')).includes('ينتظر أول تحديثٍ بيدك')
          && (await ap.textContent('#sChip')) === 'يُحدَّث وحده');

    await ap.click('#sPrev');
    await ap.waitForSelector('#sDiff .diff li');
    const diff = await ap.$$eval('#sDiff .diff li', ls => ls.map(l => l.textContent.replace(/\s+/g, ' ').trim()));
    check('المعاينة: القديم ← الجديد', diff.some(t => t.includes('600+ فيلم') && t.includes('650+ فيلم'))
          && diff.some(t => t.includes('28 مسلسلًا') && t.includes('30 مسلسلًا')) && diff.some(t => t.includes('وصف محركات البحث')), diff.join(' | '));
    let st = await (await fetch(`${MOCK}/__state`)).json();
    check('ولم يُكتب شيء', st.puts.length === 0);
    check('بلا تمرير أفقي والمعاينة ظاهرة', await ap.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    if (SHOTS) await ap.locator('#store').screenshot({path: path.join(SHOTS, 'store-preview.png')});

    ap.once('dialog', d => d.accept());
    await ap.click('#sRun');
    await ap.waitForFunction(() => document.querySelector('#sMsg').textContent.startsWith('كُتب في'), null, {timeout: 15000});
    st = await (await fetch(`${MOCK}/__state`)).json();
    const desc = st.products['1557813796'].description;
    check('«حدّث الآن» يكتب في سلة', st.puts.length === 1 && desc.includes('<strong>650+</strong>')
          && desc.includes('650 فيلمًا</strong> و<strong>30 مسلسلًا') && desc.includes('<strong>40 فيلمًا</strong>'), desc.slice(0, 200));
    const links = await ap.textContent('#sLinks');
    check('والمنتج معتمَد ومطابقٌ لآخر سحب', links.includes('آخر كتابة') && links.includes('مطابقٌ لآخر سحب'), links);
    check('وآخر تحديث', (await ap.textContent('#sLast')).includes('كُتب في منتج واحد من منتج واحد'));
    check('بلا تمرير أفقي', await ap.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    if (SHOTS) await ap.locator('#store').screenshot({path: path.join(SHOTS, 'store-done.png')});
    check('بلا أخطاء سكربت', errors.length === 0, errors.join(' | '));
  } catch (e) {
    check('بلا استثناء', false, e.message);
  } finally {
    await browser.close();
    app.kill();
    mock.kill();
    fs.rmSync(DATA, {recursive: true, force: true});
    console.log(`\nResult: ${pass} passed, ${fail} failed`);
    process.exit(fail ? 1 : 0);
  }
})();

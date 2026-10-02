// Browser test of the guide's statistics (analytics.py · static/sq.js · stats_admin.html · google_api.py):
//  - a visitor on the public guide (a phone, not headless) arriving from a Snapchat campaign link is counted with its
//    source, device and campaign; the wizard steps («أريد اشتراكًا جديدًا»، أداة M3U)، توليد الرابط، a store click and the
//    reading time reach the report; ?sq=off excludes the browser (kept) and ?sq=on brings it back;
//  - the admin page: KPIs, the trend chart (two lines, crosshair tooltip), «اليوم» = hourly bars, the ranked lists and
//    their tabs, the events drill-down, the funnels;
//  - connecting: GA4 pasted as the full gtag snippet (lands in the guide's pages), the service-account JSON (an RSA key
//    made by Node here, parsed by our pure-Python reader) → «اختبر الربط» → pick the property and site → GA4 and Search
//    Console with quick wins and sitemaps → «أرسل خريطتي الموقع»; IndexNow «أرسل الآن»; the campaign-link builder;
//  - the setup sections are folded, and those needing attention (GA4 missing, Google not connected, IndexNow never sent)
//    open by themselves; Google Analytics' lists are tabs;
//  - the admin dashboard's 4th card counts today's visitors; nothing overflows a 390px or 360px screen, and the controls
//    are ≥ 40px tall on a phone; no script error.
// No internet: Google and IndexNow are tests/mock_google.py.
//   NODE_PATH=<dir with playwright-core> node tests/ui_stats.js     (SHOTS_DIR=… for screenshots)
const { chromium } = require('playwright-core');
const { spawn, execSync } = require('child_process');
const crypto = require('crypto');
const path = require('path'); const fs = require('fs'); const os = require('os');
const ROOT = path.dirname(__dirname);
const APP_PORT = 9815, MOCK_PORT = 9816;
const SHOTS = process.env.SHOTS_DIR || '';
const EXE = execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim();
let pass = 0, fail = 0;
const check = (l, c, x='') => { c ? (pass++, console.log(`  PASS  ${l}${x?'  ('+x+')':''}`)) : (fail++, console.log(`  FAIL  ${l}${x?'  ('+x+')':''}`)); };
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function up(u){ for (let i=0;i<80;i++){ try { execSync(`curl -s -o /dev/null ${u}`); return; } catch(e){} await sleep(150); } }
const AUTH = 'Basic ' + Buffer.from('admin:envpass123').toString('base64');
const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1';
const GA_SNIP = `<!-- Google tag (gtag.js) -->\n<script async src="https://www.googletagmanager.com/gtag/js?id=G-UITEST1234"></script>\n<script>gtag('config', 'G-UITEST1234');</script>`;

// أيامٌ مضت بأرقامها، فيكون للرسم خطّ
function seed(dir) {
  const d = path.join(dir, 'analytics', 'days'); fs.mkdirSync(d, {recursive: true});
  for (let i = 1; i <= 9; i++) {
    const day = new Date(Date.now() + 3 * 3600e3 - i * 86400e3).toISOString().slice(0, 10);
    const uv = 40 + i * 3, pv = uv * 2;
    fs.writeFileSync(path.join(d, day + '.json'), JSON.stringify({v: 1, pv, uv, in: uv, pages: {'/': pv - 10, '/iphone': 10}, land: {'/': uv},
      src: {google: uv - 5, whatsapp: 5}, ref: {'www.google.com': uv - 5}, utm: {}, dev: {mobile: uv}, os: {ios: uv}, cc: {SA: uv},
      hr: Array.from({length: 24}, (_, h) => h === 21 ? pv : 0), ev: {store_click: 3}, evl: {store_click: {p479880741: 3}},
      dur: [pv * 40, pv], pdur: {'/': [400, 10]}, bot: {Google: 12}, shp: {}}));
  }
}

async function report(days = 1) {
  return (await fetch(`http://127.0.0.1:${APP_PORT}/admin/api/analytics/report?days=${days}`, {headers: {Authorization: AUTH}})).json();
}
async function until(fn, ms = 8000) {
  const t = Date.now();
  while (Date.now() - t < ms) { const r = await fn(); if (r) return r; await sleep(200); }
  return null;
}
const evc = (r, n) => ((r.events || []).find(e => e.n === n) || {c: 0}).c;

(async () => {
  const DATA = fs.mkdtempSync(path.join(os.tmpdir(), 'uistats_'));
  seed(DATA);
  // مفتاح حساب الخدمة: يولّده Node (OpenSSL) فيُقرأ بقارئنا — وعامّه للجوجل الوهمية
  const {privateKey, publicKey} = crypto.generateKeyPairSync('rsa', {modulusLength: 1024,
    privateKeyEncoding: {type: 'pkcs8', format: 'pem'}, publicKeyEncoding: {type: 'spki', format: 'pem'}});
  const jwk = crypto.createPublicKey(publicKey).export({format: 'jwk'});
  const n = BigInt('0x' + Buffer.from(jwk.n, 'base64url').toString('hex')).toString();
  const e = BigInt('0x' + Buffer.from(jwk.e, 'base64url').toString('hex')).toString();
  fs.writeFileSync(path.join(DATA, 'pub.json'), `{"n": ${n}, "e": ${e}}`);
  const SA = {type: 'service_account', project_id: 'demo', private_key_id: 'k1', private_key: privateKey,
              client_email: 'stats@demo.iam.gserviceaccount.com', token_uri: 'https://oauth2.googleapis.com/token'};
  const MOCK = `http://127.0.0.1:${MOCK_PORT}`;
  const mock = spawn('python3', [path.join(ROOT, 'tests', 'mock_google.py'), String(MOCK_PORT), path.join(DATA, 'pub.json')], {stdio: 'ignore'});
  const app = spawn('python3', [path.join(ROOT, 'xm_lines.py'), 'web'], {stdio: 'ignore', env: {...process.env,
    XM_DATA: DATA, XM_BIND: '127.0.0.1', XM_PORT: String(APP_PORT), XM_ADMIN_PASSWORD: 'envpass123',
    XM_GOOGLE_TOKEN_URL: MOCK + '/token', XM_GA_API: MOCK + '/ga/v1beta', XM_GA_ADMIN_API: MOCK + '/gaadmin/v1beta',
    XM_GSC_API: MOCK + '/gsc', XM_INDEXNOW_URL: MOCK + '/indexnow'}});
  await up(`http://127.0.0.1:${APP_PORT}/robots.txt`);
  await up(`${MOCK}/_test/state`);
  const browser = await chromium.launch({executablePath: EXE, args: ['--no-sandbox']});
  const APP = `http://127.0.0.1:${APP_PORT}`;
  const errors = [];
  try {
    // ---------- الزائر ----------
    const vc = await browser.newContext({viewport: {width: 390, height: 844}, userAgent: IPHONE, hasTouch: true, isMobile: true});
    await vc.route(/https:\/\/(www\.)?(ssouq\.com|fonts\.googleapis\.com|fonts\.gstatic\.com|cdn\.salla\.network)\//, r => r.fulfill({status: 200, body: ''}));
    const vp = await vc.newPage();
    vp.on('pageerror', e => errors.push('guide: ' + e.message));
    await vp.goto(APP + '/?utm_source=snap&utm_medium=social&utm_campaign=ui-test');
    let r = await until(async () => { const x = await report(); return x.totals.pv >= 1 && x; });
    check('الزيارة تُعدّ بمصدرها وحملتها وجهازها', r && r.sources.some(s => s[0] === 'snapchat') && r.utm.some(u => u[0] === 'snap / social / ui-test')
          && r.devices.some(d => d[0] === 'mobile') && r.os.some(o => o[0] === 'ios'), r && JSON.stringify([r.sources, r.utm]));
    await vp.click('#view [data-nav="buy"]');
    await vp.waitForFunction(() => location.hash.startsWith('#buy'));
    await vp.evaluate(() => nav('m3u'));
    await vp.waitForSelector('#m3u-form');
    await vp.fill('#m3u-host', 'http://host.example:8080'); await vp.fill('#m3u-user', 'u1'); await vp.fill('#m3u-pass', 'p1');
    await vp.click('#m3u-form [type="submit"]');
    r = await until(async () => { const x = await report(); return evc(x, 'buy_start') && evc(x, 'm3u_open') && evc(x, 'm3u_generate') && x; });
    check('خطوات المعالج: بدء «اشتراك جديد»، وفتح أداة M3U وتوليد رابط', !!r, r && JSON.stringify(r.events.map(e => [e.n, e.c])));
    await vp.evaluate(() => nav('plans'));
    const link = await vp.waitForSelector('#view a[href*="ssouq.com/"]');
    const href = await link.getAttribute('href');
    const pid = (href.match(/\/(p\d{5,})/) || [])[1];
    await vp.evaluate(() => document.querySelectorAll('#view a[href*="ssouq.com/"]').forEach(a => a.removeAttribute('target')));
    await Promise.all([vp.waitForURL(/ssouq\.com/), link.click()]);   // يغادر إلى المتجر: نقرةٌ ومدة قراءة
    r = await until(async () => { const x = await report(); return evc(x, 'store_click') && x.totals.dur > 0 && x; });
    const sc = r && r.events.find(e => e.n === 'store_click');
    check('نقرة الشراء برقم المنتج، ومدة القراءة حين غادر', sc && sc.top.some(t => t[0] === pid), sc && JSON.stringify(sc.top));
    const pv0 = (await report()).totals.pv;
    await vp.goto(APP + '/iphone?sq=off'); await vp.goto(APP + '/android'); await sleep(700);
    const pv1 = (await report()).totals.pv;
    await vp.goto(APP + '/mac?sq=on');
    const pv2 = await until(async () => { const x = await report(); return x.totals.pv > pv1 && x.totals.pv; });
    check('?sq=off يستثني المتصفح (ويبقى)، و?sq=on يعيده', pv1 === pv0 && pv2 === pv0 + 1, `${pv0} → ${pv1} → ${pv2}`);
    await vc.close();

    // ---------- صفحة الإحصائيات ----------
    const ctx = await browser.newContext({viewport: {width: 1280, height: 900}, extraHTTPHeaders: {Authorization: AUTH}});
    const ap = await ctx.newPage();
    ap.on('pageerror', e => errors.push('stats: ' + e.message));
    await ap.goto(APP + '/admin/stats');
    await ap.waitForFunction(() => document.querySelector('#kUv').textContent !== '—');
    await ap.click('.range [data-days="30"]');
    await ap.waitForFunction(() => document.querySelectorAll('#trend .ln').length === 2);
    const kpi = await ap.evaluate(() => ['#kUv', '#kIn', '#kPv', '#kSt'].map(s => document.querySelector(s).textContent));
    check('البطاقات الأربع بأرقام الشهر', kpi.every(v => /^[\d,]+$/.test(v)) && +kpi[0].replace(/,/g, '') > 400, kpi.join(' · '));
    check('ومقارنتها بما قبلها، ونسبة الشراء من الزوار', (await ap.textContent('#dSt')).includes('% من الزوار'));
    const box = await (await ap.$('#trend svg')).boundingBox();
    await ap.mouse.move(box.x + box.width - 40, box.y + box.height / 2);
    const tip = await ap.evaluate(() => { const t = document.querySelector('#trend .tip'); return !t.hidden && t.textContent; });
    check('الرسم: خطّان ومؤشّرٌ يعرض اليوم وقيمتيه', tip && tip.includes('زائر') && tip.includes('مشاهدة'), tip);
    check('ودليلٌ للخطّين، وجدولٌ بديل', (await ap.$$('#trendLegend span')).length === 2 && (await ap.$$('#trendTbl tr')).length === 31);
    await ap.click('.range [data-days="1"]');
    await ap.waitForFunction(() => document.querySelector('#trendTitle').textContent.includes('بالساعة'));
    check('«اليوم»: المشاهدات بالساعة أعمدة', (await ap.$$('#trend .bar')).length >= 1 && (await ap.textContent('#dUv')).startsWith('أمس'));
    await ap.click('.range [data-days="30"]');
    await ap.waitForFunction(() => document.querySelectorAll('#trend .ln').length === 2);
    check('المصادر بأسمائها العربية', (await ap.textContent('#lSrc')).includes('سناب شات') && (await ap.textContent('#lSrc')).includes('جوجل'));
    await ap.click('.seg[data-list="src"] [data-k="utm"]');
    check('وتبويب «الحملات»', (await ap.textContent('#lSrc')).includes('snap / social / ui-test'));
    await ap.click('.seg[data-list="pages"] [data-k="landing"]');
    check('والصفحات: صفحات الدخول بأسمائها', (await ap.textContent('#lPages')).includes('الرئيسية'));
    await ap.click('#lEvents [data-ev="store_click"]');
    const evt = await ap.textContent('#lEvents');
    check('النقرات: «نقرات الشراء» تنفتح على الباقات بأسمائها', evt.includes('اشتراك فالكون IPTV لمدة 15 شهر'), evt.slice(0, 200));
    check('رحلة الزائر: المسارات الثلاثة', (await ap.textContent('#funnels')).includes('اشتراك جديد') && (await ap.textContent('#funnels')).includes('أداة M3U'));
    check('الأرشفة: زحف جوجل', (await ap.textContent('#lBots')).includes('Google'));
    if (SHOTS) await ap.screenshot({path: path.join(SHOTS, 'stats-top.png')});

    // ---------- الإعداد: مطويّ، ويُفتح وحده ما يحتاج انتباهًا ----------
    await ap.waitForFunction(() => document.querySelector('#gConn').open && document.querySelector('#connSec').open);
    const folds = await ap.evaluate(() => Object.fromEntries(['connSec', 'gConn', 'ixSec', 'growSec', 'utmSec'].map(id => [id, document.getElementById(id).open])));
    check('الإعداد الناقص مفتوحٌ وحده (GA4 وربط جوجل وIndexNow)، والباقي مطويّ',
          folds.connSec && folds.gConn && folds.ixSec && !folds.growSec && !folds.utmSec, JSON.stringify(folds));

    // ---------- الربط ----------
    await ap.fill('#t_ga', GA_SNIP);
    await ap.click('#tagSave');
    await ap.waitForFunction(() => document.querySelector('#tagMsg').classList.contains('ok'));
    check('GA4: الكود الملصوق كاملًا يُحفظ معرّفًا', (await ap.inputValue('#t_ga')) === 'G-UITEST1234');
    const home = await (await fetch(APP + '/')).text();
    check('ويظهر في صفحات الدليل', home.includes('gtag/js?id=G-UITEST1234'));
    await ap.fill('#t_bing', 'nonsense');
    await ap.click('#tagSave');
    await ap.waitForFunction(() => document.querySelector('#tagMsg').classList.contains('err'));
    check('وقيمةٌ خاطئة تُرفض باسمها', (await ap.textContent('#tagMsg')).includes('Bing'));
    await ap.fill('#t_bing', '');

    await ap.fill('#gKey', JSON.stringify(SA));
    await ap.click('#gSave');
    await ap.waitForFunction(() => document.querySelector('#gState').textContent.includes('stats@demo'));
    check('مفتاح حساب الخدمة (من Node/OpenSSL) يُقبل ويُحفظ', (await ap.inputValue('#gKey')) === '' && !(await ap.isHidden('#gRemove')));
    await ap.click('#gCheck');
    await ap.waitForSelector('#gPick [data-ga="424242"]');
    await ap.click('#gPick [data-ga="424242"]');
    await ap.click('#gPick [data-site="https://guide.ssouq.com/"]');
    check('«اختبر الربط» يعرض الخاصية والموقع للاختيار', (await ap.inputValue('#gGa')) === '424242' && (await ap.inputValue('#gSite')) === 'https://guide.ssouq.com/');
    await ap.click('#gSave');
    await ap.waitForFunction(() => document.querySelector('#gaChip').textContent === 'مربوط' && document.querySelector('#gscChip').textContent === 'مربوط', null, {timeout: 15000});
    const ga = await ap.textContent('#gaBody');
    check('Google Analytics: المستخدمون والقنوات والدول و«الآن»', ga.includes('728') && ga.includes('بحث مجاني') && ga.includes('السعودية') && ga.includes('آخر 30 دقيقة'), ga.slice(0, 160));
    await ap.click('#gaBody .seg[data-pane="ga"] [data-k="cc"]');
    check('وقوائمه تبويبات: «الدول» تظهر وحدها', await ap.isVisible('#gaBody .pane[data-k="cc"]') && await ap.isHidden('#gaBody .pane[data-k="ch"]')
          && (await ap.textContent('#gaBody .pane[data-k="cc"]')).includes('السعودية'));
    const gsc = await ap.textContent('#gscBody');
    check('Search Console: البحث وفرصٌ سريعة', gsc.includes('اشتراك iptv') && gsc.includes('فرصٌ سريعة') && gsc.includes('ترتيب دوري روشن'), gsc.slice(0, 160));
    await ap.click('#smSend');
    await ap.waitForFunction(() => document.querySelector('#smMsg') && document.querySelector('#smMsg').classList.contains('ok') || document.querySelectorAll('#gscBody .chip.ok').length >= 2, null, {timeout: 15000});
    const st = await (await fetch(MOCK + '/_test/state')).json();
    check('«أرسل خريطتي الموقع» يصل جوجل', st.sitemaps.length === 2, JSON.stringify(st.sitemaps));
    await ap.click('#ixSend');
    await ap.waitForFunction(() => !document.querySelector('#ixSend').disabled && document.querySelector('#ixMsg').textContent.includes('يدوي'), null, {timeout: 15000});
    check('IndexNow: «أرسل كل الصفحات الآن»', (await ap.textContent('#ixMsg')).includes('استُلمت')
          && (await ap.textContent('#ixChip')) === 'آخر إرسال ناجح', await ap.textContent('#ixMsg'));
    await ap.click('#utmSec > summary');                  // أداةٌ لا إعداد: مطويّةٌ حتى تُفتح
    await ap.selectOption('#uSrc', 'snapchat');
    await ap.fill('#uCamp', 'Eid Sale');
    await ap.selectOption('#uPaid', 'paid');
    const utm = await ap.inputValue('#uOut');
    check('رابط الحملة', utm.includes('utm_source=snapchat') && utm.includes('utm_medium=paid_social') && utm.includes('utm_campaign=eid-sale'), utm);
    const done = await ap.$$eval('#checks .ic.ok', els => els.length);
    check('خطوات زيادة الزوار بحالها', done >= 4, done);
    await ap.click('#connSec > summary');                 // يطويه المدير بيده، فلا يُفتح وحده بعدها
    await ap.click('#growSec > summary');
    await ap.click('#checks a[href="#t_snap"]');
    await ap.waitForFunction(() => document.activeElement && document.activeElement.id === 't_snap');
    check('«ابدأ» يفتح القسم المطويّ ويضع المؤشر في خانته', await ap.evaluate(() => document.querySelector('#connSec').open));
    if (SHOTS) await ap.locator('#gscSec').screenshot({path: path.join(SHOTS, 'stats-gsc.png')});

    await ap.setViewportSize({width: 390, height: 844});
    await sleep(300);
    check('بلا تمرير أفقي على 390px', await ap.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    const small = await ap.evaluate(() => [...document.querySelectorAll('#main :is(button, a.rw, a.go, a.ghost, .jump a, summary), .top .icon-btn, .bnav a')]
      .filter(e => e.offsetParent !== null && !e.closest('.menu')).map(e => [e, e.getBoundingClientRect().height]).filter(([, h]) => h < 40)
      .map(([e, h]) => (e.id || e.className || e.tagName) + ':' + Math.round(h)));
    check('على الجوال: الأزرار والتبويبات وسطور القوائم ≥ 40px', small.length === 0, small.join(' '));
    await ap.setViewportSize({width: 360, height: 780});
    await sleep(300);
    check('بلا تمرير أفقي على 360px', await ap.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    if (SHOTS) await ap.screenshot({path: path.join(SHOTS, 'stats-mobile.png'), fullPage: true});

    // ---------- رئيسية لوحة الإدارة ----------
    await ap.setViewportSize({width: 1280, height: 900});
    await ap.goto(APP + '/admin/accounts');
    await ap.evaluate(() => nav('home'));
    await ap.waitForFunction(() => document.querySelector('#statVisits').textContent !== '—');
    check('رئيسية اللوحة: بطاقة «زوار الدليل اليوم» وإلى الإحصائيات', /^\d+$/.test(await ap.textContent('#statVisits'))
          && (await ap.getAttribute('#kpiVisits', 'href')) === '/admin/stats' && (await ap.$$('.kpis .kpi')).length === 4);
    check('بلا أخطاء سكربت', errors.length === 0, errors.join(' | '));
  } catch (e) {
    check('بلا استثناء', false, e.message);
  } finally {
    await browser.close();
    const gone = new Promise(r => app.once('exit', r));
    app.kill();                                          // SIGTERM: يكتب أعداد اليوم قبل أن يخرج — فننتظره
    await Promise.race([gone, sleep(5000)]);
    mock.kill();
    fs.rmSync(DATA, {recursive: true, force: true});
    console.log(`\nResult: ${pass} passed, ${fail} failed`);
    process.exit(fail ? 1 : 0);
  }
})();

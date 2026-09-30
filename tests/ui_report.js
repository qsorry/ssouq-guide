// Browser test of content reports: a subscriber on /report (360px) picks the server, the category, the series and
// its season and episode (or a movie from the name search), says "لا يعمل" or "يقطع" and sends it; the browser's back
// button and the trail go back a step; a link from the content page opens the server, and one with the category and
// name opens the episode step. The employee (an account the admin gave «بلاغات المحتوى», no gates) lands on
// /reports after login, sees the report with its count and WhatsApp numbers, marks it fixed and finds it under
// «تم إصلاحها» with a ready "fixed" WhatsApp message; the admin sees the option ticked on the account. Nothing
// overflows a 360px screen. No internet: the playlist is written by the test.
//   NODE_PATH=<dir with playwright-core> node tests/ui_report.js     (SHOTS_DIR=… for screenshots)
const { chromium } = require('playwright-core');
const { spawn, execSync } = require('child_process');
const path = require('path'); const fs = require('fs'); const os = require('os');
const ROOT = path.dirname(__dirname);
const APP_PORT = 9796;
const SHOTS = process.env.SHOTS_DIR || '';
const EXE = execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim();
const AUTH = 'Basic ' + Buffer.from('admin:envpass123').toString('base64');
let pass = 0, fail = 0;
const check = (l, c, x='') => { c ? (pass++, console.log(`  PASS  ${l}${x?'  ('+x+')':''}`)) : (fail++, console.log(`  FAIL  ${l}${x?'  ('+x+')':''}`)); };
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function up(u){ for (let i=0;i<80;i++){ try { execSync(`curl -s -o /dev/null ${u}`); return; } catch(e){} await sleep(150); } }
const shot = async (page, name) => { if (SHOTS) await page.screenshot({path: path.join(SHOTS, name + '.png'), fullPage: true}); };
const wide = page => page.evaluate(() => document.documentElement.scrollWidth);

function playlist(extra) {
  const H = 'http://panel.example:8080';
  const e = (title, group, kind, n) => `#EXTINF:-1 group-title="${group}",${title}\n${H}/${kind}/u/p/${n}.${kind === 'live' ? 'ts' : 'mkv'}\n`;
  let s = '#EXTM3U\n', n = 1;
  for (let se = 1; se <= 3; se++) for (let ep = 1; ep <= 8; ep++) s += e(`Breaking Bad S0${se} E0${ep}`, 'SERIES | Drama', 'series', n++);
  for (let ep = 1; ep <= 30; ep++) s += e(`المؤسس عثمان الموسم الخامس الحلقة ${ep}`, 'مسلسلات تركية', 'series', n++);
  s += e('Dune (2021)', 'VOD | English Movies', 'movie', n++) + e('The Batman (2022)', 'VOD | English Movies', 'movie', n++);
  s += e('AR: MBC 1 HD', 'AR | MBC', 'live', n++);
  return s + (extra || '');
}

(async () => {
  const DATA = fs.mkdtempSync(path.join(os.tmpdir(), 'uireport_'));
  const app = spawn('python3', [path.join(ROOT, 'xm_lines.py'), 'web'], {stdio: 'ignore', env: {...process.env,
    XM_DATA: DATA, XM_BIND: '127.0.0.1', XM_PORT: String(APP_PORT), XM_ADMIN_PASSWORD: 'envpass123'}});
  const APP = `http://127.0.0.1:${APP_PORT}`;
  await up(APP + '/robots.txt');
  const up1 = async (key, body) => (await fetch(`${APP}/admin/api/content/admin/upload?s=${key}&name=${key}.m3u`,
    {method: 'POST', headers: {Authorization: AUTH}, body})).status;
  const browser = await chromium.launch({executablePath: EXE, args: ['--no-sandbox']});
  const errors = [];
  try {
    check('(رفع ملفَّي السيرفرين)', await up1('smart', playlist()) === 200
          && await up1('falcon', '#EXTM3U\n#EXTINF:-1 group-title="Drama",Kon Show S01 E01\nhttp://x.example/series/u/p/1.mkv\n') === 200);
    const r = await (await fetch(`${APP}/admin/api/accounts`, {method: 'POST', headers: {Authorization: AUTH, 'Content-Type': 'application/json'},
      body: JSON.stringify({name: 'سارة', user: 'sara', password: 'sara1234', reports: true, gates: []})})).json();
    check('(حساب الموظف)', !!(r.accounts || []).find(a => a.user === 'sara' && a.reports));

    console.log('العميل: مسلسل ← موسم ← حلقة ← يقطع');
    const ctx = await browser.newContext({viewport: {width: 360, height: 780}});
    const page = await ctx.newPage();
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(APP + '/report');
    await page.waitForSelector('.srv');
    check('الخطوة الأولى: السيرفرات التي لها محتوى', (await page.$$eval('.srv b', b => b.map(x => x.textContent))).join('|') === 'فالكون|سمارت'
          || (await page.$$eval('.srv b', b => b.map(x => x.textContent))).sort().join('|') === 'سمارت|فالكون');
    check('بلا عرضٍ زائد على 360px (السيرفرات)', await wide(page) <= 360, await wide(page));
    await shot(page, 'report-1-servers');
    await page.click('.srv[data-s="smart"]');
    await page.waitForSelector('#glist .row');
    check('ثم أقسام السيرفر بأنواعها وأعدادها', (await page.$$eval('.tabs button', b => b.map(x => x.textContent))).join('|') === 'مسلسلات2|أفلام1|قنوات1'
          && (await page.$$eval('#glist .row .t', b => b.map(x => x.textContent))).join('|') === 'SERIES | Drama|مسلسلات تركية');
    check('وما اخترته في الأعلى', (await page.textContent('#trail')).includes('سمارت'));
    await shot(page, 'report-2-groups');
    await page.click('#glist .row[data-name="SERIES | Drama"]');
    await page.waitForSelector('.card[data-i]');
    check('ثم مسلسلات القسم', (await page.$$eval('.card[data-i] b', b => b.map(x => x.textContent))).join('|') === 'Breaking Bad'
          && (await page.textContent('.card[data-i] small')).includes('3 مواسم'));
    await shot(page, 'report-3-items');
    await page.goBack();
    await page.waitForSelector('#glist .row');
    check('زرّ الرجوع في المتصفح يرجع خطوة (لا يخرج)', page.url().endsWith('/report') && !!(await page.$('#glist')));
    await page.click('#glist .row[data-name="SERIES | Drama"]');
    await page.waitForSelector('.card[data-i]');
    await page.click('.card[data-i="0"]');
    await page.waitForSelector('.eps button');
    check('ثم المواسم، والأحدث مختار، وحلقاته', (await page.$$eval('.chips button[data-season]', b => b.map(x => x.textContent))).join('|') === '1|2|3'
          && await page.$eval('.chips button[data-season="3"]', b => b.getAttribute('aria-pressed')) === 'true'
          && (await page.$$('.eps button')).length === 8);
    await page.click('.chips button[data-season="1"]');
    check('واختيار موسمٍ آخر', await page.$eval('.chips button[data-season="1"]', b => b.getAttribute('aria-pressed')) === 'true');
    await shot(page, 'report-4-episode');
    await page.click('.eps button[data-ep="5"]');
    await page.waitForSelector('.prob');
    check('ثم المشكلة وما اختاره', (await page.textContent('.pick')).includes('الموسم 1 · الحلقة 5')
          && await page.$eval('#send', b => b.disabled));
    check('بلا عرضٍ زائد على 360px (المشكلة)', await wide(page) <= 360, await wide(page));
    await page.click('.prob.buffer');
    await page.fill('#ph', '0551234567');
    await page.fill('#nt', 'يقطع بعد دقيقتين');
    await shot(page, 'report-5-problem');
    await page.click('#send');
    await page.waitForSelector('.done');
    check('وصل البلاغ', (await page.textContent('.done .what')) === 'Breaking Bad · الموسم 1 · الحلقة 5 — يقطع');
    await shot(page, 'report-6-done');

    console.log('العميل: فيلمٌ من البحث بالاسم، ورقمه محفوظ');
    await page.click('#again');
    await page.waitForSelector('#sq');
    await page.fill('#sq', 'dune');
    await page.waitForSelector('#sres .card');
    check('البحث بالاسم في السيرفر كله', (await page.textContent('#sres .card')).includes('Dune'));
    await page.click('#sres .card');
    await page.waitForSelector('.prob');
    check('والفيلم إلى المشكلة مباشرةً، ورقمه كما كتبه', (await page.textContent('.pick')).includes('Dune (2021)')
          && await page.inputValue('#ph') === '0551234567');
    await page.click('.prob.down');
    await page.click('#send');
    await page.waitForSelector('.done');
    check('وصل', (await page.textContent('.done .what')) === 'Dune (2021) — لا يعمل');

    console.log('العميل: من صفحة المحتوى، ورابطٌ بالمسلسل نفسه');
    await page.goto(APP + '/content/smart');
    await page.click('a[href="/report?s=smart"]');
    await page.waitForSelector('#glist .row');
    check('رابط صفحة المحتوى يختار سيرفرها', (await page.textContent('#trail')).includes('سمارت'));
    const gid = (await (await fetch(`${APP}/api/report/groups?s=smart`)).json()).kinds.series.find(g => g.name === 'مسلسلات تركية').id;
    await page.goto(`${APP}/report?s=smart&t=series&g=${gid}&n=${encodeURIComponent('المؤسس عثمان')}`);
    await page.waitForSelector('.eps button');
    check('ورابطٌ بالقسم والاسم يفتح الحلقات', (await page.$$('.eps button')).length === 30
          && (await page.textContent('#trail')).includes('المؤسس عثمان'));
    await page.fill('#epn', '٣١');
    await page.click('#epgo');
    await page.waitForSelector('.prob');
    check('ورقم حلقةٍ آخر (بالأرقام الهندية)', (await page.textContent('.pick')).includes('الحلقة 31'));
    await page.click('[data-back]');
    await page.waitForSelector('.eps button');
    await page.click('[data-back]');
    await page.waitForSelector('.card[data-i]');
    check('و«رجوع» في الصفحة إلى القسم', (await page.$$eval('.card[data-i] b', b => b.map(x => x.textContent))).includes('المؤسس عثمان'));
    await page.click('#trail [data-to="server"]');
    await page.waitForSelector('.srv');
    check('وما اخترته في الأعلى يرجع إليه', (await page.$$('.srv')).length === 2 && (await page.textContent('#trail')) === '');

    console.log('الموظف');
    const emp = await browser.newContext({viewport: {width: 390, height: 844}});
    const ep = await emp.newPage();
    ep.on('pageerror', e => errors.push(e.message));
    await ep.goto(APP + '/admin/login');
    await ep.fill('#u', 'sara'); await ep.fill('#p', 'sara1234');
    await ep.click('#go');
    await ep.waitForSelector('.rep');
    check('الموظف بلا بوابات يدخل إلى البلاغات', ep.url().endsWith('/admin/reports'));
    check('المفتوحة بأعدادها', await ep.textContent('#nOpen') === '2' && await ep.textContent('#nDone') === '0'
          && (await ep.title()).startsWith('(2)'));
    const first = await ep.$eval('.rep', el => el.textContent);
    check('البلاغ: الاسم والسيرفر والقسم والمشكلة والرقم والملاحظة', first.includes('Dune (2021)') || first.includes('Breaking Bad'));
    const bb = await ep.$('.rep:has-text("Breaking Bad")');
    const txt = await bb.textContent();
    check('وتفاصيله', txt.includes('Breaking Bad · الموسم 1 · الحلقة 5') && txt.includes('سمارت · SERIES | Drama')
          && txt.includes('يقطع') && txt.includes('+966551234567') && txt.includes('يقطع بعد دقيقتين'), txt.slice(0, 200));
    check('ورقمه رابط واتساب', await bb.$eval('.people a', a => a.href) === 'https://wa.me/966551234567');
    check('وما جرى لتنبيهه (بلا أرقامٍ بعد)', (await bb.$eval('.wline', e => e.textContent)).includes('لا أرقام للتنبيه'));
    check('بطاقة تنبيه واتساب مفتوحة بلا رقم', await ep.$eval('#abox', e => e.open)
          && (await ep.textContent('#aSum')).includes('أضف رقمك'));
    await ep.fill('#aWa', '0500000001');
    await ep.click('#aSave');
    await ep.waitForFunction(() => document.getElementById('aMsg').textContent.includes('حُفظ'));
    check('ويحفظ رقمه، ويقول إن رقم المسابقة غير مربوط', (await ep.textContent('#aSum')).includes('+966500000001')
          && !(await ep.$eval('#aFrom', e => e.hidden)) && await ep.inputValue('#aWa') === '+966500000001');
    await ep.fill('#aWa', '12');
    await ep.click('#aSave');
    await ep.waitForFunction(() => document.getElementById('aMsg').classList.contains('bad'));
    check('والرقم الخطأ برسالته', (await ep.textContent('#aMsg')).includes('غير صحيح'));
    await ep.fill('#aWa', '0500000001');
    await ep.click('#aSave');
    await ep.waitForFunction(() => document.getElementById('aMsg').textContent.includes('حُفظ'));
    await shot(ep, 'reports-0-alert');
    check('بلا عرضٍ زائد على 390px', await wide(ep) <= 390, await wide(ep));
    await shot(ep, 'reports-1-open');
    await bb.$eval('[data-act="done"]', b => b.click());
    await ep.waitForFunction(() => document.getElementById('nDone').textContent === '1');
    check('«تم الإصلاح» ينقله إلى المنجزة', await ep.textContent('#nOpen') === '1' && (await ep.$$('.rep')).length === 1);
    await ep.click('[data-state="done"]');
    await ep.waitForSelector('.rep.done');
    const dn = await ep.$eval('.rep.done', el => el.textContent);
    check('وفيها من أصلحه', dn.includes('أُصلح') && dn.includes('سارة'));
    const wa = await ep.$eval('.rep.done .people a', a => a.href);
    check('ورابط واتساب برسالة «تم الإصلاح» جاهزة', wa.startsWith('https://wa.me/966551234567?text=')
          && decodeURIComponent(wa).includes('تم إصلاح ما بلّغت عنه في سمارت'), wa.slice(0, 80));
    check('ولا حذف للموظف', !(await ep.$('[data-act="del"]')));
    await shot(ep, 'reports-2-done');

    console.log('المدير');
    const ad = await browser.newContext({viewport: {width: 390, height: 844}, extraHTTPHeaders: {Authorization: AUTH}});
    const ap = await ad.newPage();
    ap.on('pageerror', e => errors.push(e.message));
    await ap.goto(APP + '/admin/accounts');
    await ap.waitForSelector('#lkReportsN');
    await ap.waitForFunction(() => document.getElementById('lkReportsN').textContent.includes('مفتوحة'));
    check('رابط البلاغات في الرئيسية بعدد المفتوحة', (await ap.textContent('#lkReportsN')).startsWith('1 مفتوحة'));
    await ap.goto(APP + '/admin/accounts#accounts');
    await ap.waitForSelector('[data-toggle]');
    check('وسم الحساب', (await ap.textContent('.acct')).includes('بلاغات المحتوى'));
    await ap.$eval('[data-edit]', b => b.click());
    check('والخيار مفعّل في نافذته، ورقم الموظف معه', await ap.$eval('#acc_reports', c => c.checked)
          && await ap.inputValue('#acc_reports_wa') === '+966500000001' && !(await ap.$eval('#acc_reports_box', e => e.hidden)));
    await ap.goto(APP + '/admin/reports?state=all');
    await ap.waitForSelector('.rep');
    check('والمدير يرى الكل ويحذف', (await ap.$$('.rep')).length === 2 && !!(await ap.$('[data-act="del"]')));
    check('ومن يصله التنبيه', (await ap.textContent('#aStaff')).includes('سارة') && (await ap.textContent('#aStaff')).includes('+966500000001'));
    check('بلا أخطاء سكربت', errors.length === 0, errors.join(' | '));
  } catch (e) {
    check('بلا استثناء', false, e.stack);
  } finally {
    await browser.close();
    app.kill();
    console.log(`\nResult: ${pass} passed, ${fail} failed`);
    process.exit(fail ? 1 : 0);
  }
})();

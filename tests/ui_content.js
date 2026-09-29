// Browser test of the content page (/content): the admin page uploads an M3U (gzip-compressed in the
// browser) and hides a group; the homepage, menu, buy flow and plans screen link the page only once a
// server has content; a group opens in place with "عرض المزيد"; search runs as you type and says where
// else a name exists; nothing overflows a 360px screen. No internet: the playlist is written by the test.
//   NODE_PATH=<dir with playwright-core> node tests/ui_content.js     (SHOTS_DIR=… for screenshots)
const { chromium } = require('playwright-core');
const { spawn, execSync } = require('child_process');
const path = require('path'); const fs = require('fs'); const os = require('os');
const ROOT = path.dirname(__dirname);
const APP_PORT = 9797;
const SHOTS = process.env.SHOTS_DIR || '';
const EXE = execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim();
let pass = 0, fail = 0;
const check = (l, c, x='') => { c ? (pass++, console.log(`  PASS  ${l}${x?'  ('+x+')':''}`)) : (fail++, console.log(`  FAIL  ${l}${x?'  ('+x+')':''}`)); };
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function up(u){ for (let i=0;i<80;i++){ try { execSync(`curl -s -o /dev/null ${u}`); return; } catch(e){} await sleep(150); } }
const shot = async (page, name) => { if (SHOTS) await page.screenshot({path: path.join(SHOTS, name + '.png'), fullPage: true}); };

function playlist(movies) {
  const H = 'http://panel.example:8080', C = 'user123/pass456';
  const e = (title, group, kind, n) => `#EXTINF:-1 tvg-name="${title}" tvg-logo="${H}/i/${n}.png" group-title="${group}",${title}\n`
    + `${H}/${kind}/${C}/${n}.${kind === 'live' ? 'ts' : 'mkv'}\n`;
  let s = '#EXTM3U\n', n = 1;
  for (let se = 1; se <= 3; se++) for (let ep = 1; ep <= 8; ep++) s += e(`Breaking Bad S0${se} E0${ep}`, 'SERIES | Drama', 'series', n++);
  for (let ep = 1; ep <= 30; ep++) s += e(`المؤسس عثمان الموسم الخامس الحلقة ${ep}`, 'مسلسلات رمضان 2026', 'series', n++);
  s += e('Sex Education S01 E01', 'Netflix', 'series', n++);
  s += e('Hot Stuff', 'XXX | Adults', 'live', n++);
  for (let i = 0; i < movies; i++) s += e(`Film ${String(i).padStart(4, '0')} (2020)`, 'VOD | Big', 'movie', n++);
  s += e('AR: MBC 1 HD', 'AR | MBC', 'live', n++) + e('beIN SPORTS 1', 'beIN', 'live', n++);
  return s;
}

(async () => {
  const DATA = fs.mkdtempSync(path.join(os.tmpdir(), 'uicontent_'));
  const app = spawn('python3', [path.join(ROOT, 'xm_lines.py'), 'web'], {stdio: 'ignore', env: {...process.env,
    XM_DATA: DATA, XM_BIND: '127.0.0.1', XM_PORT: String(APP_PORT), XM_ADMIN_PASSWORD: 'envpass123'}});
  await up(`http://127.0.0.1:${APP_PORT}/robots.txt`);
  const browser = await chromium.launch({executablePath: EXE, args: ['--no-sandbox']});
  const APP = `http://127.0.0.1:${APP_PORT}`;
  const errors = [];
  try {
    const ctx = await browser.newContext({viewport: {width: 360, height: 780}});
    const page = await ctx.newPage();
    page.on('pageerror', e => errors.push(e.message));

    console.log('الرئيسية قبل أي ملف');
    await page.goto(APP + '/');
    await page.waitForSelector('.entries');
    await page.waitForResponse(r => r.url().endsWith('/api/content')).catch(() => {});
    await sleep(300);
    check('لا مدخل ولا رابط في القائمة بلا محتوى', await page.$eval('#content-entry', e => e.hidden)
          && await page.$eval('#menu-content', e => e.hidden));

    console.log('صفحة المدير');
    const adm = await browser.newContext({viewport: {width: 390, height: 844},
      extraHTTPHeaders: {Authorization: 'Basic ' + Buffer.from('admin:envpass123').toString('base64')}});
    await adm.addInitScript(() => {            // ما يرسله الرفع فعلًا: حجمه وأول بايتين
      const send = XMLHttpRequest.prototype.send;
      XMLHttpRequest.prototype.send = function (b) {
        if (b instanceof Blob) b.slice(0, 2).arrayBuffer().then(a => { window.__sent = {size: b.size, head: [...new Uint8Array(a)]}; });
        return send.call(this, b);
      };
    });
    const ap = await adm.newPage();
    ap.on('pageerror', e => errors.push('admin: ' + e.message));
    await ap.goto(APP + '/admin/content');
    await ap.waitForSelector('[data-k="smart"] [data-file]');
    check('السيرفرات الأربعة بترتيبها', (await ap.$$eval('#list > section h2 b', h => h.map(x => x.textContent.trim())))
          .join('|') === 'كون|كاسبر|سمارت|فالكون');
    const file = path.join(DATA, 'smart-list.m3u');
    fs.writeFileSync(file, playlist(2500));
    const size = fs.statSync(file).size;
    await ap.setInputFiles('[data-k="smart"] [data-file]', file);
    await ap.click('[data-k="smart"] [data-act="upload"]');
    await ap.waitForFunction(() => /^تم:/.test(document.querySelector('[data-k="smart"] [data-msg]').textContent), null, {timeout: 20000});
    const sent = await ap.evaluate(() => window.__sent);
    check('يُضغط في المتصفح قبل الرفع', sent && sent.head[0] === 0x1f && sent.head[1] === 0x8b && sent.size < size / 5,
          `${size} → ${sent && sent.size}`);
    const msg = await ap.textContent('[data-k="smart"] [data-msg]');
    check('ملخّص الرفع بالعربية', msg.includes('تم: 2,557 عنصرًا — 55 حلقة من المسلسلات و2,500 فيلم وقناتان.')
          && msg.includes('أُسقط 1 من أقسام الكبار'), msg);
    check('منشور بأعداده', (await ap.textContent('[data-k="smart"] .chip')).includes('منشور')
          && (await ap.textContent('[data-k="smart"] .stats')).includes('2,500'));
    check('وبلا بيانات الدخول', !(await ap.content()).includes('pass456'));
    await ap.click('[data-k="smart"] details.groups summary');
    await ap.click('[data-k="smart"] [data-gk="series"]');
    const nf = ap.locator('[data-k="smart"] .grow', {hasText: 'Netflix'});
    const hideReq = ap.waitForResponse(r => r.url().includes('/api/content/admin/hide'));
    await nf.locator('input').uncheck();
    await hideReq;
    await ap.waitForFunction(() => document.querySelector('[data-k="smart"] details.groups summary').textContent.includes('المخفي منها 1'));
    check('إخفاء قسم: القائمة تبقى مفتوحة وهو معلَّم', await ap.$eval('[data-k="smart"] details.groups', d => d.open)
          && await ap.$eval('[data-k="smart"] .grow.off', r => r.textContent.includes('Netflix') && !r.querySelector('input').checked));
    check('بلا تمرير أفقي في صفحة المدير', await ap.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await shot(ap, 'content-admin');

    console.log('الرئيسية بعد الرفع');
    await page.goto(APP + '/');
    await page.waitForSelector('#content-entry:not([hidden])', {timeout: 8000});
    check('مدخل المحتوى باسم السيرفر', (await page.textContent('#content-entry small')).includes('سيرفر سمارت'));
    check('ورابطٌ في القائمة', !(await page.$eval('#menu-content', e => e.hidden)));
    check('بلا تمرير أفقي على 360px', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.goto(APP + '/#buy/vod/mobile');
    await page.waitForSelector('[data-content-list]:not([hidden]) a', {timeout: 8000});
    check('اختيار النوع: محتوى سمارت وحده (لا ملف لفالكون)', (await page.$$eval('[data-content-list] a', a => a.map(x => x.textContent + '@' + x.getAttribute('href'))))
          .join('|') === 'محتوى سمارت@/content/smart');
    await page.goto(APP + '/#plans');
    await page.waitForSelector('.clink[data-content="smart"]:not([hidden])', {timeout: 8000});
    check('كل الباقات: الرابط بجانب سمارت لا فالكون', await page.$eval('.clink[data-content="falcon"]', e => e.hidden));

    console.log('صفحة المحتوى');
    await page.goto(APP + '/content');
    check('‏/content ← صفحة سمارت', page.url() === APP + '/content/smart');
    check('الأعداد', (await page.textContent('.cstats')).replace(/\s/g, '').includes('2مسلسلان'));
    check('القسم المخفي ليس فيها', !(await page.content()).includes('Netflix'));
    await page.click('details.cg >> nth=0 >> summary');
    await page.waitForSelector('details.cg[open] ul.ci li', {timeout: 8000});
    const bb = await page.textContent('details.cg[open] ul.ci li');
    check('القسم يُفتح في مكانه: المسلسل بمواسمه', bb.includes('Breaking Bad') && bb.includes('3 مواسم')
          && bb.includes('الموسم 3 (8 حلقات)'), bb);
    await page.click('.ckinds a[href$="t=movie"]');
    await page.waitForURL(/t=movie/);
    await page.click('details.cg >> nth=0 >> summary');
    await page.waitForSelector('details.cg[open] .cmore', {timeout: 8000});
    check('300 أولًا وزرّ المزيد', await page.$$eval('details.cg[open] li', l => l.length) === 300
          && (await page.textContent('details.cg[open] .cmore')).includes('بقي 2,200 فيلم'));
    await page.click('details.cg[open] .cmore');
    await page.waitForFunction(() => document.querySelectorAll('details.cg[open] li').length === 600, null, {timeout: 8000});
    check('والمزيد يُلحق بها', (await page.textContent('details.cg[open] li:nth-child(301)')).includes('Film 0300'));
    check('بلا تمرير أفقي في صفحة المحتوى', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));

    console.log('البحث بالاسم');
    await page.fill('.csearch input', 'عثم');
    await page.waitForSelector('#cres .cres', {timeout: 8000});
    const r1 = await page.textContent('#cres');
    check('مع الكتابة', r1.includes('المؤسس عثمان') && r1.includes('الموسم 5 (30 حلقة)'), r1.slice(0, 120));
    check('والعنوان يحمل البحث', page.url().endsWith('?q=' + encodeURIComponent('عثم')));
    await page.fill('.csearch input', 'Sex Education');
    await page.waitForFunction(() => document.querySelector('#cres').textContent.includes('لا يوجد'), null, {timeout: 8000});
    check('القسم المخفي لا يُبحث فيه', true);
    await page.fill('.csearch input', '');
    await page.waitForFunction(() => !document.querySelector('#cres').textContent.trim(), null, {timeout: 8000});
    check('مسح البحث يمسح النتائج', true);
    await page.fill('.csearch input', 'mbc');
    await page.press('.csearch input', 'Enter');
    await page.waitForFunction(() => document.querySelector('#cres').textContent.includes('MBC 1 HD'), null, {timeout: 8000});
    check('Enter يبحث بلا انتقال', page.url().includes('/content/smart?q=mbc'));
    await shot(page, 'content-page');

    check('بلا أخطاء سكربت', errors.length === 0, errors.join(' | '));
  } catch (e) {
    check('بلا استثناء', false, e.message);
  } finally {
    await browser.close();
    app.kill();
    fs.rmSync(DATA, {recursive: true, force: true});
    console.log(`\nResult: ${pass} passed, ${fail} failed`);
    process.exit(fail ? 1 : 0);
  }
})();

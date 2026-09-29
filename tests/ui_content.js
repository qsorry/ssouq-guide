// Browser test of the content page (/content): the admin page uploads an M3U (gzip-compressed in the
// browser), hides a group, and saves an Xtream link whose panel API adds ratings, genres and dates; the
// homepage, menu, buy flow and plans screen link the page only once a server has content; the hero
// carousel, the details window with each season's episodes, "أضيف مؤخرًا", row arrows, a category grid
// with pages, the filters, search as you type (and where else a name exists), panel images through our
// server; nothing overflows a 360px screen. No internet: the playlist is written by the test and the
// Xtream panel is tests/mock_xtream.py (TMDB posters fail offline and fall back to initials).
//   NODE_PATH=<dir with playwright-core> node tests/ui_content.js     (SHOTS_DIR=… for screenshots)
const { chromium } = require('playwright-core');
const { spawn, execSync } = require('child_process');
const path = require('path'); const fs = require('fs'); const os = require('os');
const ROOT = path.dirname(__dirname);
const APP_PORT = 9797, MOCK_PORT = 9798;
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
    XM_DATA: DATA, XM_BIND: '127.0.0.1', XM_PORT: String(APP_PORT), XM_ADMIN_PASSWORD: 'envpass123', CONTENT_IMG_PRIVATE: '1'}});
  const mock = spawn('python3', [path.join(ROOT, 'tests', 'mock_xtream.py'), String(MOCK_PORT)], {stdio: 'ignore'});
  await up(`http://127.0.0.1:${APP_PORT}/robots.txt`);
  await up(`http://127.0.0.1:${MOCK_PORT}/images/1.png`);
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
    // محتوى قرأته النسخة الأولى (قبل الصور والتقييمات): المدير يُطلب منه إعادة رفع الملف
    fs.writeFileSync(path.join(DATA, 'content', 'kon.json'), JSON.stringify({entries: 1, n: {series: 0, movie: 1, live: 0},
      skipped: {}, series: [], live: [], movie: [{id: 'm0', name: 'M', items: ['Old Film (2019)']}], at: Date.now() / 1000}));
    await ap.reload();
    await ap.waitForSelector('[data-k="kon"] .warnline', {timeout: 8000});
    check('المحتوى القديم: «أعد رفع الملف»', (await ap.textContent('[data-k="kon"] .warnline')).includes('أعد رفع الملف'));
    ap.once('dialog', dlg => dlg.accept());       // «مسح محتوى هذا السيرفر؟»
    await ap.click('[data-k="kon"] [data-act="clear"]');
    await ap.waitForFunction(() => !document.querySelector('[data-k="kon"] .warnline'), null, {timeout: 8000});
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

    console.log('سيرفرٌ برابط Xtream: الإثراء من واجهته');
    await ap.fill('[data-k="falcon"] [data-url]', `http://127.0.0.1:${MOCK_PORT}/get.php?username=u&password=p&type=m3u_plus`);
    await ap.click('[data-k="falcon"] [data-act="url"]');
    await ap.waitForFunction(() => /واجهة السيرفر/.test(document.querySelector('[data-k="falcon"]').textContent), null, {timeout: 20000});
    const fmeta = await ap.textContent('[data-k="falcon"]');
    check('يُسحب ويُثرى، والحال للمدير', fmeta.includes('منشور') && fmeta.includes('من واجهة السيرفر: 32 فيلمًا و10 مسلسلات'),
          fmeta.slice(0, 200));
    check('والرابط مخفيّ', !fmeta.includes('password=p') && fmeta.includes('/•••'));

    console.log('صفحة المحتوى على الحاسوب');
    const desk = await browser.newContext({viewport: {width: 1280, height: 900}});
    const dp = await desk.newPage();
    dp.on('pageerror', e => errors.push('desktop: ' + e.message));
    await dp.goto(APP + '/content');
    check('‏/content ← صفحة سمارت', dp.url() === APP + '/content/smart');
    check('الأعداد', (await dp.textContent('.stats')).replace(/\s/g, '').includes('2,500فيلم')
          && (await dp.textContent('.stats')).replace(/\s/g, '').includes('2مسلسلان'));
    check('القسم المخفي ليس فيها', !(await dp.content()).includes('Netflix'));
    await dp.waitForLoadState('networkidle').catch(() => {});
    await dp.reload({waitUntil: 'networkidle'}).catch(() => {});     // والثانية: 404 الصور من ذاكرة الخادم فورًا
    check('ولا صورة معطوبة: الحرفان الأولان مكانها', await dp.evaluate(() => [...document.querySelectorAll('.pos img,.chip img,.slide img')]
      .every(i => !i.complete || i.naturalWidth > 0)));
    const slides = await dp.$$eval('.hero .slide', s => s.map(x => x.querySelector('h2').textContent));
    check('الواجهة: أحدث الأفلام والمسلسلات', slides.length === 5 && slides[0] === 'Film 2499'
          && slides.includes('المؤسس عثمان'), slides.join('|'));
    await dp.click('.hero .harrow.next');
    check('وتتحرّك بالأسهم', await dp.$eval('.hero .slide.on h2', h => h.textContent) === slides[1]
          && await dp.$eval('.hero .dots [aria-current]', b => b.dataset.go) === '1');
    await dp.click('.hlist button[data-go="3"]');
    check('وبالقائمة بجانبها', await dp.$eval('.hero .slide.on h2', h => h.textContent) === slides[3]);
    await dp.click('.hero .slide.on .btn');
    await dp.waitForSelector('#cx-modal:not([hidden])');
    check('«عرض التفاصيل» يفتح النافذة', await dp.textContent('#cx-title') === slides[3]);
    await dp.keyboard.press('Escape');
    check('وEsc يغلقها', await dp.$eval('#cx-modal', m => m.hidden));

    const bbCard = dp.locator('.row .card', {hasText: 'Breaking Bad'}).first();
    await bbCard.click();
    await dp.waitForSelector('#cx-modal:not([hidden])');
    const seasons = await dp.$$eval('#cx-modal .seasons span', s => s.map(x => x.textContent));
    check('المسلسل: مواسمه وحلقات كل موسم', seasons.join('|') === 'الموسم 1 (8 حلقات)|الموسم 2 (8 حلقات)|الموسم 3 (8 حلقات)'
          && (await dp.textContent('#cx-modal')).includes('3 مواسم · 24 حلقة'), seasons.join('|'));
    check('وزرّ الاشتراك في السيرفر', (await dp.getAttribute('#cx-modal .btn', 'href')).includes('utm_campaign=content')
          && (await dp.textContent('#cx-modal .btn')).includes('اشترك في سمارت'));
    await dp.click('#cx-modal .x');
    check('والإغلاق يعيد التركيز', await dp.$eval('#cx-modal', m => m.hidden)
          && await dp.evaluate(() => document.activeElement && document.activeElement.classList.contains('card')));
    await shot(dp, 'content-desktop');

    await dp.click('.kinds a[href$="t=new"]');
    await dp.waitForURL(/t=new/);
    check('«أضيف مؤخرًا»: الأحدث أولًا', (await dp.textContent('h1')).includes('أضيف مؤخرًا في سمارت')
          && await dp.$eval('.grid .card h3', h => h.textContent) === 'المؤسس عثمان');
    await dp.click('.kinds a[href$="t=movie"]');
    await dp.waitForURL(/t=movie$/);
    const box = dp.locator('.row .cards').first();
    const x0 = await box.evaluate(b => b.scrollLeft);
    await dp.locator('.row .arrow.next').first().click();
    await dp.waitForFunction(x => document.querySelector('.row .cards').scrollLeft !== x, x0, {timeout: 4000}).catch(() => {});
    check('أسهم الصفّ تمرّره', await box.evaluate(b => b.scrollLeft) !== x0);
    await dp.click('.row .more');
    await dp.waitForURL(/g=/);
    check('«عرض الكل»: القسم شبكةً بصفحاتها', await dp.$$eval('.col .grid .card', c => c.length) === 60
          && (await dp.textContent('.pager')).includes('صفحة 1 من 42'));
    await dp.click('.pager a:has-text("التالي")');
    await dp.waitForURL(/p=2/);
    check('والتالي', await dp.$eval('.col .grid .card h3', h => h.textContent) === 'Film 2439');
    await dp.selectOption('.filter select[name="y"]', '2020');
    await dp.selectOption('.filter select[name="g"]', '');
    await dp.click('.filter .btn');
    await dp.waitForURL(/view=grid/);
    check('التصفية بالسنة', (await dp.textContent('.gh')).includes('2,500 فيلم · 2020'), await dp.textContent('.gh'));
    await shot(dp, 'content-grid');

    console.log('البحث بالاسم');
    await dp.goto(APP + '/content/smart');
    await dp.fill('.search input', 'عثم');
    await dp.waitForSelector('#cres .results', {timeout: 8000});
    check('مع الكتابة', (await dp.textContent('#cres')).includes('المؤسس عثمان'));
    check('والعنوان يحمل البحث', dp.url().endsWith('?q=' + encodeURIComponent('عثم')));
    await dp.click('#cres .card');
    await dp.waitForSelector('#cx-modal:not([hidden])');
    check('والنتيجة تفتح تفاصيلها', (await dp.textContent('#cx-modal .seasons')).includes('الموسم 5 (30 حلقة)'));
    await dp.keyboard.press('Escape');
    await dp.fill('.search input', 'Sex Education');
    await dp.waitForFunction(() => document.querySelector('#cres').textContent.includes('لا يوجد'), null, {timeout: 8000});
    check('القسم المخفي لا يُبحث فيه', true);
    await dp.fill('.search input', '');
    await dp.waitForFunction(() => !document.querySelector('#cres').textContent.trim(), null, {timeout: 8000});
    check('مسح البحث يمسح النتائج', await dp.$eval('#cres', b => getComputedStyle(b).display === 'none'));
    await dp.fill('.search input', 'mbc');
    await dp.press('.search input', 'Enter');
    await dp.waitForFunction(() => document.querySelector('#cres').textContent.includes('MBC 1'), null, {timeout: 8000});
    check('Enter يبحث بلا انتقال', dp.url().includes('/content/smart?q=mbc'));
    await dp.fill('.search input', 'breaking');
    await dp.waitForFunction(() => document.querySelector('#cres').textContent.includes('ويوجد أيضًا في'), null, {timeout: 8000});
    check('وأين يوجد في السيرفرات الأخرى', (await dp.textContent('#cres .other')).includes('فالكون'));

    console.log('سيرفرٌ مُثرًى');
    await dp.goto(APP + '/content/falcon');
    check('أحدث فيلم في الواجهة بتقييمه وتصنيفه', await dp.$eval('.hero .slide.on h2', h => h.textContent) === 'F1 The Movie'
          && (await dp.textContent('.hero .slide.on')).includes('7.8') && (await dp.textContent('.hero .slide.on')).includes('Action • Drama'));
    check('وشارة «جديد»', await dp.$$eval('.badge', b => b.length) > 0);
    await dp.locator('.card', {hasText: 'F1 The Movie'}).first().click();
    await dp.waitForSelector('#cx-modal:not([hidden])');
    const fm = await dp.textContent('#cx-modal');
    check('والنافذة: التقييم والتصنيف وتاريخ الإضافة', fm.includes('★ 7.8') && fm.includes('Action • Drama') && fm.includes('أضيف أمس'), fm);
    check('وحرفا الملصق كما في الخادم', await dp.textContent('#cx-modal .ph') === 'FT');
    await dp.keyboard.press('Escape');
    await dp.goto(APP + '/content/falcon?t=live');
    const logo = dp.locator('img[src^="/content/falcon/img/"]').first();
    await logo.scrollIntoViewIfNeeded();
    await dp.waitForFunction(() => [...document.querySelectorAll('img[src^="/content/falcon/img/"]')]
      .some(i => i.complete && i.naturalWidth > 0), null, {timeout: 8000}).catch(() => {});
    check('صور اللوحة تمرّ بخادمنا', await dp.evaluate(() => [...document.querySelectorAll('img[src^="/content/falcon/img/"]')]
      .some(i => i.complete && i.naturalWidth > 0)));
    check('ولا يظهر فيها سيرفر اللوحة', !(await dp.content()).includes(`127.0.0.1:${MOCK_PORT}`));

    console.log('على الجوال (360px)');
    for (const u of ['/content/smart', '/content/smart?t=movie', '/content/smart?t=new', '/content/falcon?t=series',
                     '/content/smart?t=movie&view=grid&y=2020']) {
      await page.goto(APP + u);
      check(`بلا تمرير أفقي: ${u}`, await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    }
    await page.goto(APP + '/content/falcon');
    const st = await page.evaluate(() => {
      const box = document.querySelector('.stats').getBoundingClientRect();
      const tiles = [...document.querySelectorAll('.stat')].map(t => t.getBoundingClientRect());
      return {n: tiles.length, rows: new Set(tiles.map(t => Math.round(t.top))).size,
              left: Math.round(tiles[tiles.length - 1].left - box.left)};
    });
    check('خانات الأعداد تملأ صفوفها (3 ثم 2)', st.n === 5 && st.rows === 2 && st.left <= 1, JSON.stringify(st));
    await page.locator('.row .card').first().click();
    await page.waitForSelector('#cx-modal:not([hidden])');
    check('والنافذة كذلك', await page.evaluate(() => {
      const s = document.querySelector('#cx-modal .sheet').getBoundingClientRect();
      return s.left >= 0 && s.right <= innerWidth && document.documentElement.scrollWidth <= innerWidth;
    }));
    await shot(page, 'content-mobile-modal');
    await page.keyboard.press('Escape');
    const tl = await page.evaluate(() => {
      const h = document.querySelector('.hero'); const x = h.getBoundingClientRect();
      return {w: x.width, top: document.querySelector('.stats').getBoundingClientRect().top > x.bottom};
    });
    check('الواجهة بعرض الشاشة وتحتها الأعداد', tl.w <= 360 && tl.top, JSON.stringify(tl));
    await shot(page, 'content-mobile');

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

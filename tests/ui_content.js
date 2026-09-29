// Browser test of the content page (/content): the admin page uploads an M3U (gzip-compressed in the
// browser), lists what it dropped as adult, saves and tests who gets the adult alert, hides a group,
// saves an Xtream link whose panel API adds ratings, genres and dates, and links a WhatsApp channel whose
// daily "أضيف مؤخرًا" post it previews as a WhatsApp bubble and posts (mock WhatsApp service); the
// homepage, menu, buy flow and plans screen link the page only once a server has content; the hero
// carousel, the details window with each season's episodes, "أضيف مؤخرًا", row arrows, a category grid
// with pages, the filters, search as you type (and where else a name exists), panel images through our
// server; nothing overflows a 360px screen. And the same page in English (/en/content): left to right, the language
// switch keeping the section and search, the details window, row arrows and swipes the other way round, search in
// English, a compact ad on 360px; the admin saves a server's English name. No internet: the playlist is written by
// the test and the Xtream panel is tests/mock_xtream.py (TMDB posters fail offline and fall back to initials).
//   NODE_PATH=<dir with playwright-core> node tests/ui_content.js     (SHOTS_DIR=… for screenshots)
const { chromium } = require('playwright-core');
const { spawn, execSync } = require('child_process');
const path = require('path'); const fs = require('fs'); const os = require('os');
const ROOT = path.dirname(__dirname);
const APP_PORT = 9797, MOCK_PORT = 9798, READER_PORT = 9789;
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

// سيرفر كون لمنشور القناة: ملفٌ أول، ثم هو وما جدّ فيه (فيلمان ومسلسلٌ جديد وحلقةٌ جديدة)
function konList(more) {
  const H = 'http://panel.example:8080', C = 'user123/pass456';
  const e = (title, group, kind, n) => `#EXTINF:-1 tvg-logo="${H}/i/${n}.png" group-title="${group}",${title}\n${H}/${kind}/${C}/${n}.mkv\n`;
  let s = '#EXTM3U\n' + e('The Batman (2022)', 'VOD | EN', 'movie', 1) + e('The Boys S04 E01', 'Series', 'series', 2);
  if (more) s += e('Dune: Part Two (2024)', 'VOD | EN', 'movie', 3) + e('ولاد رزق 3 (2024)', 'أفلام عربية', 'movie', 4)
    + e('The Boys S04 E02', 'Series', 'series', 5) + e('Shogun S01 E01', 'Series', 'series', 6);
  return s;
}

(async () => {
  const DATA = fs.mkdtempSync(path.join(os.tmpdir(), 'uicontent_'));
  const app = spawn('python3', [path.join(ROOT, 'xm_lines.py'), 'web'], {stdio: 'ignore', env: {...process.env,
    XM_DATA: DATA, XM_BIND: '127.0.0.1', XM_PORT: String(APP_PORT), XM_ADMIN_PASSWORD: 'envpass123', CONTENT_IMG_PRIVATE: '1',
    WHATSAPP_READER_URL: `http://127.0.0.1:${READER_PORT}`, WHATSAPP_READER_SECRET: 'rdr_ui'}});
  const mock = spawn('python3', [path.join(ROOT, 'tests', 'mock_xtream.py'), String(MOCK_PORT)], {stdio: 'ignore'});
  const reader = spawn('python3', [path.join(ROOT, 'tests', 'mock_reader.py'), String(READER_PORT), 'rdr_ui'], {stdio: 'ignore'});
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
          && msg.includes('وأُسقط عنصر واحد للكبار.'), msg);
    check('منشور بأعداده', (await ap.textContent('[data-k="smart"] .chip')).includes('منشور')
          && (await ap.textContent('[data-k="smart"] .stats')).includes('2,500'));
    check('وبلا بيانات الدخول', !(await ap.content()).includes('pass456'));
    check('أُسقط بعدده ومعدوده', (await ap.textContent('[data-k="smart"] .meta')).includes('أُسقط: عنصر واحد للكبار'));
    await ap.click('[data-k="smart"] details.adult summary');
    const ad = await ap.textContent('[data-k="smart"] details.adult');
    check('وما هو: القسم بعدده، ولا يُنشر', ad.includes('ما أُسقط للكبار (عنصر واحد) — لا يُنشر')
          && ad.includes('أقسامٌ حُذفت كلها') && ad.includes('XXX | Adults'), ad.replace(/\s+/g, ' ').slice(0, 160));
    await ap.click('[data-k="smart"] details.groups summary');
    await ap.click('[data-k="smart"] [data-gk="series"]');
    const nf = ap.locator('[data-k="smart"] .grow', {hasText: 'Netflix'});
    const hideReq = ap.waitForResponse(r => r.url().includes('/api/content/admin/hide'));
    await nf.locator('input').uncheck();
    await hideReq;
    await ap.waitForFunction(() => document.querySelector('[data-k="smart"] details.groups summary').textContent.includes('المخفي منها 1'));
    check('إخفاء قسم: القائمة تبقى مفتوحة وهو معلَّم', await ap.$eval('[data-k="smart"] details.groups', d => d.open)
          && await ap.$eval('[data-k="smart"] .grow.off', r => r.textContent.includes('Netflix') && !r.querySelector('input').checked));
    check('وما أُسقط يبقى مفتوحًا بعد إعادة الرسم', await ap.$eval('[data-k="smart"] details.adult', d => d.open));
    // محتوى قرأته النسخة الأولى (قبل الصور والتقييمات): المدير يُطلب منه إعادة رفع الملف
    fs.writeFileSync(path.join(DATA, 'content', 'kon.json'), JSON.stringify({entries: 1, n: {series: 0, movie: 1, live: 0},
      skipped: {}, series: [], live: [], movie: [{id: 'm0', name: 'M', items: ['Old Film (2019)']}], at: Date.now() / 1000}));
    await ap.reload();
    await ap.waitForSelector('[data-k="kon"] .warnline', {timeout: 8000});
    check('المحتوى القديم: «أعد رفع الملف»', (await ap.textContent('[data-k="kon"] .warnline')).includes('أعد رفع الملف'));
    ap.once('dialog', dlg => dlg.accept());       // «مسح محتوى هذا السيرفر؟»
    await ap.click('[data-k="kon"] [data-act="clear"]');
    await ap.waitForFunction(() => !document.querySelector('[data-k="kon"] .warnline'), null, {timeout: 8000});
    await ap.click('[data-k="kon"] [data-act="edit"]');
    check('«تعديل»: الاسم بالإنجليزية ورابط الصفحة الإنجليزية', await ap.getAttribute('[data-k="kon"] [data-e="en"]', 'value') === 'Kon'
          && await ap.$$eval('[data-k="kon"] [data-editbox] input[readonly]', i => i.map(x => x.value).join('|'))
             === 'https://guide.ssouq.com/content/kon|https://guide.ssouq.com/en/content/kon');
    await ap.fill('[data-k="kon"] [data-e="en"]', 'Kon TV');
    await ap.click('[data-k="kon"] [data-act="save"]');
    await ap.waitForFunction(() => document.querySelector('[data-k="kon"] [data-msg]').textContent.trim(), null, {timeout: 8000});
    const konEn = await ap.evaluate(async () => (await (await fetch(location.pathname.replace(/\/content$/, '/api/content/admin')))
      .json()).servers.find(s => s.key === 'kon').en);
    check('و«حفظ» يحفظه (كان يُرفض «سيرفر غير معروف»)', (await ap.textContent('[data-k="kon"] [data-msg]')) === 'حُفظ'
          && konEn === 'Kon TV' && await ap.$eval('[data-k="kon"] [data-editbox]', e => e.hidden),
          await ap.textContent('[data-k="kon"] [data-msg]'));

    console.log('تنبيه الكبار');
    check('بلا بريدٍ ولا رقم، ويقول ما ينقص', await ap.$eval('#alert', e => !e.hidden) && await ap.inputValue('#aMail') === ''
          && (await ap.textContent('#aMailHint')).includes('خادم البريد غير مضبوط')
          && (await ap.textContent('#aWaHint')).includes('غير مربوط') && await ap.$eval('#aFrom', e => !e.hidden));
    await ap.fill('#aMail', 'not-an-email');
    await ap.click('#aSave');
    await ap.waitForFunction(() => document.querySelector('#aMsg').textContent.includes('بريدًا صحيحًا'), null, {timeout: 8000});
    check('بريدٌ غير صحيح يُرفض', (await ap.getAttribute('#aMsg', 'class')).includes('err'));
    await ap.fill('#aMail', 'me@example.com');
    await ap.fill('#aWa', '0551234567');
    await ap.click('#aTest');
    await ap.waitForFunction(() => document.querySelector('#aMsg').textContent.includes('واتساب:'), null, {timeout: 30000});
    const tm = await ap.textContent('#aMsg');
    check('التجربة تحفظ الخانتين ثم ترسل، وتقول ما جرى لكلٍّ منهما', tm.includes('البريد: لم يُرسل — خادم البريد غير مضبوط')
          && tm.includes('واتساب: لم يُرسل — ') && !tm.includes('Errno') && await ap.inputValue('#aWa') === '966551234567'
          && await ap.$eval('#aFrom', e => e.hidden), tm);
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
    const logos = await dp.$$eval('.servers a', a => a.map(x => [x.querySelector('b').textContent,
      x.querySelector('img') ? x.querySelector('img').getAttribute('src') : '', !!x.getAttribute('aria-current')]));
    check('السيرفرات بشعاراتها، والحالي معلَّم', JSON.stringify(logos) === JSON.stringify([
      ['سمارت', '/static/img/brands/smart.webp', true], ['فالكون', '/static/img/brands/falcon.webp', false]]), JSON.stringify(logos));
    check('والشعارات تُحمَّل', await dp.$$eval('.servers img', i => i.length === 2 && i.every(x => x.complete && x.naturalWidth > 0)));
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
    await dp.waitForFunction(() => document.querySelector('#cres').textContent.includes('لا يوجد'), null, {timeout: 8000});
    check('Enter يبحث بلا انتقال، والبحث باسم المسلسل أو الفيلم وحده (لا القنوات)', dp.url().includes('/content/smart?q=mbc')
          && (await dp.textContent('#cres')).includes('والقنوات في'));
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
    const adPos = await page.evaluate(() => {
      const a = document.querySelector('main > .ad'), hero = document.querySelector('.hero');
      const r = a.getBoundingClientRect();
      return {plans: a.querySelectorAll('.adplan').length, top: Math.round(r.top), h: Math.round(r.height),
              above: r.bottom <= hero.getBoundingClientRect().top, fits: r.left >= 0 && r.right <= innerWidth,
              tagged: [...a.querySelectorAll('a[target]')].every(x => x.href.includes('utm_campaign=content-ad'))};
    });
    check('الإعلان في أعلى الصفحة على الجوال، مختصرًا: باقات فالكون بحملتها', adPos.plans === 3 && adPos.above
          && adPos.top < 300 && adPos.h < 420 && adPos.fits && adPos.tagged, JSON.stringify(adPos));
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

    console.log('الصفحة الإنجليزية (/en/content)');
    await dp.goto(APP + '/content/smart?t=movie');
    await dp.click('.top .lang');
    await dp.waitForURL(u => u.pathname === '/en/content/smart' && u.search === '?t=movie', {waitUntil: 'domcontentloaded'});
    check('زرّ English يفتح الصفحة نفسها بالإنجليزية ومن اليسار', await dp.evaluate(() =>
      document.documentElement.lang === 'en' && document.documentElement.dir === 'ltr')
      && (await dp.textContent('.kinds a[aria-current]')).includes('Movies'));
    const ebox = dp.locator('.row .cards').first();
    await dp.locator('.row .arrow.next').first().click();
    await dp.waitForFunction(() => document.querySelector('.row .cards').scrollLeft > 0, null, {timeout: 4000}).catch(() => {});
    check('وسهم «التالي» يمرّر الصفّ إلى اليمين', await ebox.evaluate(b => b.scrollLeft) > 0);
    await dp.goto(APP + '/en/content/smart');
    check('الأعداد بالإنجليزية', (await dp.textContent('.stats')).replace(/\s/g, '').includes('2,500movies')
          && (await dp.textContent('.stats')).replace(/\s/g, '').includes('2series'));
    const ha = await dp.evaluate(() => {
      const h = document.querySelector('.hero').getBoundingClientRect(), n = document.querySelector('.hero .harrow.next').getBoundingClientRect();
      return {right: n.left > h.left + h.width / 2, first: document.querySelector('.hero .slide.on h2').textContent};
    });
    await dp.click('.hero .harrow.next');
    check('الواجهة: «التالي» على اليمين ويتقدّم', ha.right && await dp.$eval('.hero .dots [aria-current]', b => b.dataset.go) === '1',
          JSON.stringify(ha));
    await dp.locator('.row .card', {hasText: 'Breaking Bad'}).first().click();
    await dp.waitForSelector('#cx-modal:not([hidden])');
    const eseasons = await dp.$$eval('#cx-modal .seasons span', s => s.map(x => x.textContent));
    check('النافذة بالإنجليزية: المواسم وحلقاتها وزرّ الاشتراك', eseasons.join('|') === 'Season 1 (8 episodes)|Season 2 (8 episodes)|Season 3 (8 episodes)'
          && (await dp.textContent('#cx-modal')).includes('3 seasons · 24 episodes') && (await dp.textContent('#cx-modal .kick')).startsWith('Series')
          && (await dp.textContent('#cx-modal .btn')) === 'Subscribe to Smart' && await dp.getAttribute('#cx-modal .x', 'aria-label') === 'Close',
          eseasons.join('|'));
    await dp.keyboard.press('Escape');
    await dp.fill('.search input', 'عثم');
    await dp.waitForSelector('#cres .results', {timeout: 8000});
    check('البحث مع الكتابة بالإنجليزية', (await dp.textContent('#cres h2')).startsWith('Results for “عثم” in Smart')
          && (await dp.textContent('#cres')).includes('المؤسس عثمان') && dp.url().endsWith('/en/content/smart?q=' + encodeURIComponent('عثم')),
          await dp.textContent('#cres h2'));
    check('وزرّ العربية على البحث نفسه', (await dp.getAttribute('.top .lang', 'href')) === '/content/smart?q=' + encodeURIComponent('عثم'),
          await dp.getAttribute('.top .lang', 'href'));
    await dp.fill('.search input', 'breaking');
    await dp.waitForFunction(() => document.querySelector('#cres h2').textContent.includes('“breaking”')
      && document.querySelector('#cres').textContent.includes('Also on') && location.search === '?q=breaking', null, {timeout: 8000});
    check('وأين يوجد في السيرفرات الأخرى', (await dp.getAttribute('#cres .other a', 'href')) === '/en/content/falcon?q=breaking'
          && (await dp.textContent('#cres .other')).includes('Falcon'));
    await dp.click('.top .lang');
    await dp.waitForURL(u => u.pathname === '/content/smart' && u.search === '?q=breaking', {waitUntil: 'domcontentloaded'});
    check('والعودة إلى العربية بالبحث نفسه', await dp.evaluate(() => document.documentElement.dir === 'rtl')
          && (await dp.textContent('#cres')).includes('نتائج «breaking»'));
    await dp.goto(APP + '/en/content/falcon');
    await dp.locator('.card', {hasText: 'F1 The Movie'}).first().click();
    await dp.waitForSelector('#cx-modal:not([hidden])');
    const efm = await dp.textContent('#cx-modal');
    check('سيرفرٌ مُثرًى: تاريخ الإضافة والتقييم بالإنجليزية', efm.includes('Added yesterday') && efm.includes('★ 7.8')
          && efm.includes('Subscribe to Falcon'), efm);
    await dp.keyboard.press('Escape');
    await dp.goto(APP + '/en/content/smart?t=movie');
    await dp.click('.row .more');
    await dp.waitForURL(/g=/);
    check('«View all»: القسم شبكةً بصفحاتها', await dp.$$eval('.col .grid .card', c => c.length) === 60
          && (await dp.textContent('.pager')).includes('Page 1 of 42'));
    await dp.click('.pager a:has-text("Next")');
    await dp.waitForURL(/p=2/);
    check('وNext', dp.url().includes('/en/content/smart?') && await dp.$eval('.col .grid .card h3', h => h.textContent) === 'Film 2439');
    await shot(dp, 'content-en-desktop');

    for (const u of ['/en/content/smart', '/en/content/smart?t=movie', '/en/content/smart?t=new', '/en/content/falcon?t=series',
                     '/en/content/smart?t=movie&view=grid&y=2020', '/en/content/falcon']) {
      await page.goto(APP + u);
      check(`بالإنجليزية بلا تمرير أفقي على 360px: ${u}`, await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    }
    const em = await page.evaluate(() => {
      const nav = document.querySelector('.top .nav'), a = document.querySelector('main > .ad'), hero = document.querySelector('.hero');
      const btns = [...a.querySelectorAll('.adbtns .btn')].map(b => b.getBoundingClientRect());
      const r = a.getBoundingClientRect();
      return {nav: nav.scrollWidth <= nav.clientWidth, row: btns.length === 2 && Math.round(btns[0].top) === Math.round(btns[1].top),
              h: Math.round(r.height), above: r.bottom <= hero.getBoundingClientRect().top, sub: a.querySelector('.adbtns .btn').innerText};
    });
    check('على الجوال: الرأس يتّسع لأقسامه، والإعلان مختصرٌ بزرّيه في سطر', em.nav && em.row && em.h < 420 && em.above
          && em.sub === 'Subscribe', JSON.stringify(em));
    const swipe = dx => page.evaluate(dx => {
      const h = document.querySelector('.hero');
      const touch = (type, x) => {
        const t = new Touch({identifier: 1, target: h, clientX: x, clientY: 120});
        h.dispatchEvent(new TouchEvent(type, {touches: type === 'touchend' ? [] : [t], changedTouches: [t], bubbles: true}));
      };
      touch('touchstart', 200); touch('touchend', 200 + dx); delete h.dataset.swiped;
      return +document.querySelector('.hero .dots [aria-current]').dataset.go;
    }, dx);
    check('السحب إلى اليسار يتقدّم بالإنجليزية', await swipe(-120) === 1 && await swipe(120) === 0);
    await page.goto(APP + '/content/falcon');
    check('وبالعربية السحب إلى اليمين يتقدّم', await swipe(120) === 1 && await swipe(-120) === 0);
    await page.goto(APP + '/en/content/falcon');
    await shot(page, 'content-en-mobile');

    console.log('قناة واتساب: «أضيف مؤخرًا» كل يوم');
    const auth = {Authorization: 'Basic ' + Buffer.from('admin:envpass123').toString('base64')};
    const rh = {'X-Reader-Secret': 'rdr_ui', 'Content-Type': 'application/json'};
    const post = (p, body) => fetch(APP + '/admin' + p, {method: 'POST', headers: {...auth, 'Content-Type': 'application/json'},
      body: JSON.stringify(body)}).then(r => r.json());
    const upload = text => fetch(APP + '/admin/api/content/admin/upload?s=kon&name=kon.m3u', {method: 'POST',
      headers: {...auth, 'Content-Type': 'application/octet-stream'}, body: text}).then(r => r.json());
    const rlog = () => fetch(`http://127.0.0.1:${READER_PORT}/_test/log`, {headers: rh}).then(r => r.json());
    await post('/api/contest/admin/wa/connect', {number: '0500000009'});
    await fetch(`http://127.0.0.1:${READER_PORT}/_test/scan/ssouq-guide--contest`, {method: 'POST', headers: rh, body: '{}'});
    await fetch(APP + '/admin/api/contest/admin', {headers: auth});      // صفحة المسابقة تجدّد حال الرقم
    await upload(konList(false));
    const up = await upload(konList(true));
    check('الرفع الثاني بما جدّ فيه', up.result && up.result.news.movie === 2 && up.result.news.eps === 2, JSON.stringify(up.result && up.result.news));
    await ap.goto(APP + '/admin/content');
    await ap.waitForSelector('#chan:not([hidden]) #cSrv input');
    check('وما جدّ في آخر سحبٍ على بطاقة السيرفر', (await ap.textContent('[data-k="kon"] .meta')).includes('الجديد فيه: فيلمان · مسلسلان · حلقتان'),
          await ap.textContent('[data-k="kon"] .meta'));
    check('قبل الربط: غير مربوطة، والسيرفرات كلها، والساعة 9 مساءً', (await ap.textContent('#cChip')) === 'غير مربوطة'
          && (await ap.$$eval('#cSrv input', i => i.filter(x => x.checked).length)) === 4 && await ap.inputValue('#cHour') === '21'
          && (await ap.textContent('#cLinkHint')).includes('نسخ الرابط'));
    await ap.fill('#cLink', 'https://whatsapp.com/channel/0029VaSsouqNews000000000');
    for (const k of ['casper', 'smart', 'falcon']) await ap.uncheck(`#cSrv input[value="${k}"]`);
    await ap.check('#cOn');
    await ap.click('#cSave');
    await ap.waitForFunction(() => document.querySelector('#cLinkHint').textContent.includes('مشرفٌ فيها'), null, {timeout: 15000});
    const hint = await ap.textContent('#cLinkHint');
    check('الحفظ: القناة باسمها ومتابعيها، ورقم المسابقة مشرفٌ فيها', hint.includes('«سمارت سوق | الجديد»') && hint.includes('1,520 متابع')
          && (await ap.textContent('#cChip')) === 'كل يوم 9 مساءً', hint);
    const last0 = await ap.textContent('#cLast');
    check('وما جدّ منذ ربطها وموعد المنشور', last0.includes('الجديد منذ آخر منشور: فيلمان · مسلسلان · حلقتان')
          && last0.includes('المنشور القادم:'), last0);
    await ap.click('#cPrev');
    await ap.waitForSelector('#cBox:not([hidden])');
    const bub = await ap.$eval('#cText', e => ({html: e.innerHTML, text: e.textContent, href: (e.querySelector('a') || {}).href}));
    check('المعاينة فقاعة واتساب: العريض عريض، والرابط رابط', bub.html.includes('<b>أضيف مؤخرًا في كون</b>')
          && bub.html.includes('<b>أفلام جديدة</b>') && bub.text.includes('Dune: Part Two (2024)') && bub.text.includes('Shogun · حلقة واحدة')
          && bub.href === 'https://guide.ssouq.com/content/kon?t=new&ref=wa', bub.text.slice(0, 160));
    check('وحجمها', (await ap.textContent('#cSize')).includes('فيلمان · مسلسلان · حلقتان'));
    check('بلا تمرير أفقي والمعاينة ظاهرة', await ap.evaluate(() => document.documentElement.scrollWidth <= innerWidth
          && document.querySelector('#cText').getBoundingClientRect().right <= innerWidth));
    if (SHOTS) await ap.locator('#chan').screenshot({path: path.join(SHOTS, 'content-channel.png')});
    ap.once('dialog', d => d.accept());
    await ap.click('#cPost');
    await ap.waitForFunction(() => document.querySelector('#cMsg').textContent.includes('نُشر في القناة'), null, {timeout: 15000});
    const sentCh = (await rlog()).sent.filter(x => x.to.endsWith('@newsletter'));
    check('«انشر الآن» يصل القناة بما في المعاينة', sentCh.length === 1 && sentCh[0].to === '120363000000000001@newsletter'
          && sentCh[0].body.startsWith('🆕 *أضيف مؤخرًا في كون*') && sentCh[0].body.includes('Dune: Part Two (2024)'), JSON.stringify(sentCh).slice(0, 200));
    const last1 = await ap.textContent('#cLast');
    check('وآخر منشورٍ يدويًّا، ولا جديد بعده', last1.includes('آخر منشور:') && last1.includes('(يدويًّا)')
          && last1.includes('لا جديد منذ آخر منشور'), last1);
    // سيرفرٌ مُثرًى من واجهة Xtream: ما في «أضيف مؤخرًا» في صفحته يدخل المنشور من تاريخ إضافته، بلا انتظار سحبٍ ثانٍ
    await ap.check('#cSrv input[value="falcon"]');
    await ap.click('#cPrev');
    await ap.waitForFunction(() => document.querySelector('#cText').textContent.includes('فالكون'), null, {timeout: 15000});
    const bub2 = await ap.textContent('#cText');
    check('و«أضيف مؤخرًا» في صفحة سيرفرٍ مُثرًى يدخل المعاينة من تاريخ إضافته في واجهته', bub2.includes('F1 The Movie (2025) ⭐ 7.8')
          && bub2.includes('Stranger Things · الموسم 5 (9 حلقات)') && !bub2.includes('Oppenheimer')
          && (await ap.textContent('#cMsg')).includes('آخر 7 أيام'), bub2.slice(0, 240));

    check('بلا أخطاء سكربت', errors.length === 0, errors.join(' | '));
  } catch (e) {
    check('بلا استثناء', false, e.message);
  } finally {
    await browser.close();
    app.kill();
    mock.kill();
    reader.kill();
    fs.rmSync(DATA, {recursive: true, force: true});
    console.log(`\nResult: ${pass} passed, ${fail} failed`);
    process.exit(fail ? 1 : 0);
  }
})();

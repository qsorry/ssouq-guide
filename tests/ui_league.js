// Browser test of the league standings (ترتيب الدوريات): the home card and its tabs, the
// per-league pages, the Nations League page (/nations-league) and its subscriptions ad, the
// watch pages (/watch and /watch/<league>) from the home entry, and that a dead ESPN leaves the
// home page untouched. ESPN is mocked.
//   NODE_PATH=<dir with playwright-core> node tests/ui_league.js     (SHOTS_DIR=… for screenshots)
const { chromium } = require('playwright-core');
const { spawn, execSync } = require('child_process');
const path = require('path'); const fs = require('fs'); const os = require('os');
const ROOT = path.dirname(__dirname);
const ESPN_PORT = 9761, APP_PORT = 9762, DEAD_PORT = 9763;
const SHOTS = process.env.SHOTS_DIR || '';
const EXE = execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim();
let pass = 0, fail = 0;
const check = (l, c, x='') => { c ? (pass++, console.log(`  PASS  ${l}${x?'  ('+x+')':''}`)) : (fail++, console.log(`  FAIL  ${l}${x?'  ('+x+')':''}`)); };
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function up(u){ for (let i=0;i<80;i++){ try { execSync(`curl -s -o /dev/null ${u}`); return; } catch(e){} await sleep(150); } }
const shot = async (page, name) => { if (SHOTS) await page.screenshot({path: path.join(SHOTS, name + '.png'), fullPage: true}); };
const app = (port, api) => spawn('python3', [path.join(ROOT,'xm_lines.py'), 'web'], {stdio:'ignore', env:{...process.env,
  XM_DATA: fs.mkdtempSync(path.join(os.tmpdir(), 'uileague_')), XM_BIND:'127.0.0.1', XM_PORT:String(port), LEAGUE_API: api}});

(async () => {
  const procs = [spawn('python3', [path.join(ROOT,'tests/mock_espn.py'), String(ESPN_PORT)], {stdio:'ignore'}),
                 app(APP_PORT, `http://127.0.0.1:${ESPN_PORT}`), app(DEAD_PORT, 'http://127.0.0.1:9')];
  await up(`http://127.0.0.1:${ESPN_PORT}/v2/sports/soccer/ksa.1/standings`);
  await up(`http://127.0.0.1:${APP_PORT}/robots.txt`); await up(`http://127.0.0.1:${DEAD_PORT}/robots.txt`);
  const browser = await chromium.launch({executablePath: EXE, args:['--no-sandbox']});
  const APP = `http://127.0.0.1:${APP_PORT}`, DEAD = `http://127.0.0.1:${DEAD_PORT}`;
  const errors = [];
  try {
    const ctx = await browser.newContext({viewport:{width:360, height:780}});
    const page = await ctx.newPage();
    page.on('pageerror', e => errors.push(e.message));
    const calls = [];
    page.on('request', r => { if (r.url().includes('/api/league')) calls.push(r.url().replace(APP, '')); });

    console.log('الرئيسية');
    await page.goto(APP + '/');
    await page.waitForSelector('#league:not([hidden]) table.standings', {timeout:8000});
    const tabs = await page.$$eval('#league [data-league]', b => b.map(x => [x.textContent, x.getAttribute('aria-pressed')]));
    check('ثمانية أزرار والسعودي مختار', tabs.length === 8 && tabs[0][0] === 'السعودي' && tabs[0][1] === 'true'
          && tabs.slice(1).every(t => t[1] === 'false'), tabs.map(t => t[0]).join('|'));
    check('ستة صفوف والهلال أولها', await page.$$eval('#league tbody tr', r => r.length) === 6
          && (await page.textContent('#league tbody tr th')).includes('الهلال'));
    check('رابط الجدول الكامل', await page.getAttribute('#league .lfull', 'href') === '/standings/saudi-pro-league');
    check('البطاقة بعد مداخل الرئيسية الثلاثة', await page.evaluate(() =>
      !!(document.querySelector('.entries').compareDocumentPosition(document.getElementById('league')) & Node.DOCUMENT_POSITION_FOLLOWING)));
    check('بلا تمرير أفقي على 360px', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await shot(page, 'league-home');

    await page.click('[data-league="premier-league"]');
    await page.waitForFunction(() => document.querySelector('#league .lname b')?.textContent === 'الدوري الإنجليزي الممتاز', null, {timeout:8000});
    check('الزر يبدّل الدوري في مكانه', await page.getAttribute('[data-league="premier-league"]', 'aria-pressed') === 'true'
          && await page.getAttribute('[data-league="saudi-pro-league"]', 'aria-pressed') === 'false' && page.url() === APP + '/');
    check('دليل ألوان التأهل', (await page.textContent('#league .zones')).includes('دوري أبطال أوروبا'));
    await page.click('[data-league="afc-champions-league"]');
    await page.waitForFunction(() => document.querySelectorAll('#league .lgroup').length === 2, null, {timeout:8000});
    check('أبطال آسيا: جدولان، الغرب أولًا', (await page.$$eval('#league .lgroup', h => h.map(x => x.textContent))).join('|') === 'منطقة الغرب|منطقة الشرق');
    await page.click('[data-league="premier-league"]');
    await page.waitForFunction(() => document.querySelector('#league .lname b')?.textContent === 'الدوري الإنجليزي الممتاز');
    await shot(page, 'league-home-epl');

    await page.click('.entry[data-nav="buy"]');
    await page.waitForSelector('[data-taste]');
    check('الشاشات الأخرى بلا بطاقة', !(await page.$('#league')));
    await page.goBack();
    await page.waitForSelector('#league:not([hidden]) table.standings', {timeout:8000});
    check('الرجوع يعيد آخر دوري اختاره', (await page.textContent('#league .lname b')) === 'الدوري الإنجليزي الممتاز');
    check('كل دوري يُجلب مرة واحدة في الجلسة', calls.length === 3 && new Set(calls).size === 3, calls.join(' '));

    // الوهمية لا تعرف الإسباني (400) — كما لو تعذّر دوري واحد والبقية تعمل
    await page.click('[data-league="la-liga"]');
    await page.waitForFunction(() => document.querySelector('#league-body')?.textContent.includes('تعذّر تحميل هذا الترتيب'), null, {timeout:8000});
    check('دوري تعذّر: رسالة في البطاقة ورابط صفحته', await page.getAttribute('#league-body a', 'href') === '/standings/la-liga'
          && await page.getAttribute('[data-league="la-liga"]', 'aria-pressed') === 'true');
    await page.click('.entry[data-nav="buy"]');
    await page.waitForSelector('[data-taste]');
    await page.goBack();
    await page.waitForFunction(() => document.querySelector('#league .lname b')?.textContent === 'دوري روشن السعودي', null, {timeout:8000});
    check('والرجوع للرئيسية يعرض الافتراضي لا بطاقة مخفية', await page.getAttribute('[data-league="saudi-pro-league"]', 'aria-pressed') === 'true');

    console.log('\nصفحة الدوري');
    await page.goto(APP + '/standings/premier-league');
    check('الجدول كاملًا ومعه عمودا الأهداف', await page.$$eval('table.standings tbody tr', r => r.length) === 20
          && await page.$$eval('th.gfga', t => t.length) === 2);
    check('عمودا الأهداف يُخفيان على الجوال', !(await page.isVisible('th.gfga')));
    check('الدوري الحالي معلَّم', await page.getAttribute('.ltabs [aria-current="page"]', 'href') === '/standings/premier-league');
    await page.click('.ltabs a[href="/standings/champions-league"]');
    await page.waitForURL(APP + '/standings/champions-league');
    check('الأزرار روابط بين الصفحات', await page.$$eval('table.standings tbody tr', r => r.length) === 36);
    check('بلا تمرير أفقي', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await shot(page, 'league-page-ucl');

    console.log('\nدوري الأمم الأوروبية');
    await page.goto(APP + '/');
    check('الرئيسية: كأس الخليج أولًا ثم دوري الأمم', (await page.$$eval('a.entry.cup', a => a.map(x => x.getAttribute('href'))))
          .join(' ') === '/gulf-cup /nations-league');
    await page.click('a.entry.cup[href="/nations-league"]');
    await page.waitForURL(APP + '/nations-league');
    check('الرئيسية تفتح صفحة دوري الأمم', (await page.textContent('h1')).includes('دوري الأمم الأوروبية'));
    check('على الجوال: بلا تمرير أفقي', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    check('على الجوال: الإعلان بطاقة بين الأقسام لا عمود', await page.isVisible('.cup-ad-inline') && !(await page.isVisible('.cup-ad-side')));
    check('الجارية مُعلَّمة مباشرة', await page.$$eval('#today .match.live', l => l.length) === 2);
    const geo = await page.$eval('#results .match.done', li => {
      const [h, a] = li.querySelectorAll('.score b'), [th] = li.querySelectorAll('.side b');
      return { hx: h.getBoundingClientRect().x, ax: a.getBoundingClientRect().x, tx: th.getBoundingClientRect().x };
    });
    check('نتيجة صاحب الأرض بجانب اسمه (يمينًا)', geo.hx > geo.ax && geo.tx > geo.hx, JSON.stringify(geo));
    await shot(page, 'nations-league-mobile');
    await page.click('#results a.match[href$="-france-belgium"]');
    await page.waitForURL(APP + '/nations-league/1-france-belgium');
    check('المباراة تفتح صفحتها', (await page.textContent('h1')) === 'مباراة فرنسا وبلجيكا'
          && await page.$$eval('.goals li', l => l.length) === 3);
    check('صفحة المباراة: بلا تمرير أفقي، والإعلان فيها', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)
          && await page.isVisible('.cup-ad-inline'));
    const bar = await page.$eval('.stat .bar i', i => i.getBoundingClientRect().right);
    check('شريط صاحب الأرض يبدأ من اليمين', Math.abs(bar - await page.$eval('.stat .bar', b => b.getBoundingClientRect().right)) < 1);
    await shot(page, 'match-mobile');
    const wide = await browser.newContext({viewport:{width:1280, height:900}});
    const desk = await wide.newPage();
    await desk.goto(APP + '/nations-league');
    check('على الكمبيوتر: الاشتراكات عمودٌ بجانب النتائج', await desk.isVisible('.cup-ad-side') && !(await desk.isVisible('.cup-ad-inline'))
          && await desk.evaluate(() => document.querySelector('.cup-ad-side').getBoundingClientRect().right
                                     <= document.querySelector('.cupmain').getBoundingClientRect().left + 1));
    await desk.evaluate(() => scrollTo({top: 1500, behavior: 'instant'}));
    await desk.waitForTimeout(200);
    check('والعمود يبقى ظاهرًا مع التمرير', await desk.evaluate(() => { const r = document.querySelector('.cup-ad-side').getBoundingClientRect(); return r.top >= 0 && r.top < 40; }));
    await shot(desk, 'nations-league-desktop');
    await wide.close();

    console.log('\nصفحات المشاهدة');
    await page.goto(APP + '/');
    await page.click('a.entry.watch');
    await page.waitForURL(APP + '/watch');
    check('الرئيسية تفتح مدخل المشاهدة: بطاقةٌ لكل مسابقة', (await page.textContent('h1')) === 'مشاهدة مباريات اليوم'
          && await page.$$eval('.wcomp', s => s.length) === 10);
    check('المدخل على الجوال: بلا تمرير أفقي', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await shot(page, 'watch-hub-mobile');
    await page.click('.wcomp h2 a[href="/watch/saudi-pro-league"]');
    await page.waitForURL(APP + '/watch/saudi-pro-league');
    check('صفحة دوري روشن: الجارية مُعلَّمة، والناقل تحت القادمة', await page.$$eval('#today .match.live', l => l.length) === 1
          && await page.$$eval('#upcoming .tv', l => l.length) === 2 && (await page.textContent('#upcoming .tv')).includes('ثمانية'));
    check('على الجوال: بلا تمرير أفقي، والإعلان بطاقة بين الأقسام', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)
          && await page.isVisible('.cup-ad-inline') && !(await page.isVisible('.cup-ad-side')));
    await shot(page, 'watch-spl-mobile');

    console.log('\nوضع التضمين وتعطّل ESPN');
    await page.goto(APP + '/?embed=1');
    await page.waitForSelector('.entries');
    await sleep(600);
    check('المعالج المضمَّن في المدونة بلا بطاقة', await page.$eval('#league', s => s.hidden));
    await page.goto(DEAD + '/');
    await page.waitForSelector('.entries');
    await sleep(1200);
    check('ESPN لا تردّ: البطاقة مخفية', await page.$eval('#league', s => s.hidden && !s.innerHTML));
    check('والمداخل تعمل', await page.isVisible('.entry[data-nav="activate"]'));
    check('بلا أخطاء جافاسكربت', errors.length === 0, errors.join(' | '));
    await ctx.close();
  } catch (e) {
    check('exception', false, e.message);
  } finally {
    await browser.close();
    procs.forEach(p => p.kill());
    console.log(`\nResult: ${pass} passed, ${fail} failed`);
    process.exit(fail ? 1 : 0);
  }
})();

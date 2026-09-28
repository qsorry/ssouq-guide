// Browser test of the prediction contest (مسابقة التوقّعات): the card on a match page (form, one
// prediction per number, the remembered prediction), a finished match (winner, the draw video player,
// every scene renders, recording to a video file) and the admin page. ESPN is mocked.
//   NODE_PATH=<dir with playwright-core> node tests/ui_contest.js     (SHOTS_DIR=… for screenshots)
const { chromium } = require('playwright-core');
const { spawn, execSync } = require('child_process');
const path = require('path'); const fs = require('fs'); const os = require('os');
const ROOT = path.dirname(__dirname);
const ESPN_PORT = 9771, APP_PORT = 9772;
const SHOTS = process.env.SHOTS_DIR || '';
const EXE = execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim();
let pass = 0, fail = 0;
const check = (l, c, x='') => { c ? (pass++, console.log(`  PASS  ${l}${x?'  ('+x+')':''}`)) : (fail++, console.log(`  FAIL  ${l}${x?'  ('+x+')':''}`)); };
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function up(u){ for (let i=0;i<80;i++){ try { execSync(`curl -s -o /dev/null ${u}`); return; } catch(e){} await sleep(150); } }
const shot = async (page, name) => { if (SHOTS) await page.screenshot({path: path.join(SHOTS, name + '.png'), fullPage: true}); };
const AUTH = 'Basic ' + Buffer.from('admin:envpass123').toString('base64');

// مسابقةٌ على مباراةٍ انتهت (1: فرنسا 2-1 بلجيكا) بتوقّعاتٍ قبلها — يفرزها الخادم عند أول طلب
function seedFinished(dir) {
  const out = execSync(`python3 -c "
import json, sys; sys.path[:0] = ['${ROOT}', '${ROOT}/tests']
import mock_espn, tournament as T, contest as C
m = next(x for x in T.matches(mock_espn.scoreboard('uefa.nations', '2026')['events']) if x['id'] == '1')
rec = C._blank('1'); rec.update(on=True, prize='اشتراك 3 أشهر', winners=1, match=C._snap(m))
names = ['سارة', 'فهد', 'نورة', 'خالد', 'ريم', 'تركي', 'هيا', 'ماجد']
for i in range(1, 121):
    rec['entries'].append({'n': i, 'name': names[i % 8], 'phone': '9665501%05d' % i, 'h': i % 4, 'a': i % 3,
                           'at': m['ts'] - 9000 + i, 'ipk': '', 'promo': False})
print(json.dumps(rec, ensure_ascii=False))
"`).toString();
  fs.mkdirSync(path.join(dir, 'contest'), {recursive: true});
  fs.writeFileSync(path.join(dir, 'contest', '1.json'), out);
}

(async () => {
  const data = fs.mkdtempSync(path.join(os.tmpdir(), 'uicontest_'));
  seedFinished(data);
  const procs = [spawn('python3', [path.join(ROOT,'tests/mock_espn.py'), String(ESPN_PORT)], {stdio:'ignore'}),
                 spawn('python3', [path.join(ROOT,'xm_lines.py'), 'web'], {stdio:'ignore', env:{...process.env,
                   XM_DATA: data, XM_BIND:'127.0.0.1', XM_PORT:String(APP_PORT), XM_ADMIN_PASSWORD:'envpass123',
                   LEAGUE_API:`http://127.0.0.1:${ESPN_PORT}`}})];
  await up(`http://127.0.0.1:${ESPN_PORT}/v2/sports/soccer/ksa.1/standings`);
  await up(`http://127.0.0.1:${APP_PORT}/robots.txt`);
  const APP = `http://127.0.0.1:${APP_PORT}`;
  const browser = await chromium.launch({executablePath: EXE, args:['--no-sandbox']});
  const errors = [];
  try {
    const r = await fetch(APP + '/admin/api/contest/admin/set', {method: 'POST', headers: {'Content-Type': 'application/json', Authorization: AUTH},
      body: JSON.stringify({m: '6', on: true, prize: 'اشتراك 3 أشهر', winners: 1})});
    check('المدير يفتح المسابقة على هولندا وصربيا', r.status === 200);

    console.log('بطاقة المباراة المفتوحة');
    const ctx = await browser.newContext({viewport:{width:360, height:780}});
    const page = await ctx.newPage();
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(APP + '/nations-league/6-netherlands-serbia');
    await page.waitForSelector('#predict form', {timeout:8000});
    check('النموذج: الفريقان وأسماؤهما', (await page.textContent('#predict .pteams')).includes('هولندا')
          && (await page.textContent('#predict .pteams')).includes('صربيا'));
    check('العدّاد يعدّ حتى الإقفال', /^(يوم|يومين) و\d{2}:\d{2}:\d{2}$/.test(await page.textContent('#predict .cd')),
          await page.textContent('#predict .cd'));
    check('بلا تمرير أفقي على 360px', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.click('#predict [data-side="h"] [data-d="1"]'); await page.click('#predict [data-side="h"] [data-d="1"]');
    await page.click('#predict [data-side="a"] [data-d="1"]');
    await page.click('#predict [data-side="a"] [data-d="1"]'); await page.click('#predict [data-side="a"] [data-d="-1"]');
    check('أزرار الأهداف', (await page.$$eval('#predict output', o => o.map(x => x.textContent))).join('-') === '2-1');
    await page.click('#predict button[type=submit]');
    check('الاسم قبل الإرسال', (await page.textContent('#predict .pmsg')).includes('اسمك'));
    await page.fill('#p-name', 'سارة'); await page.fill('#p-phone', '0551234567');
    await page.click('#predict button[type=submit]');
    check('الموافقة على الشروط', (await page.textContent('#predict .pmsg')).includes('شروط المسابقة'));
    await page.check('#predict input[name=agree]');
    await shot(page, 'contest-form');
    await page.click('#predict button[type=submit]');
    await page.waitForSelector('#predict .pmine', {timeout:8000});
    const mine = await page.textContent('#predict .pmine');
    check('سُجّل التوقّع برقمه', mine.includes('سجّلت توقّعك') && mine.includes('1'), mine.slice(0, 60));
    check('وزرّ المشاركة على واتساب', (await page.getAttribute('#predict .pmine a.wa', 'href')).startsWith('https://wa.me/?text='));
    await page.reload();
    await page.waitForSelector('#predict .pmine', {timeout:8000});
    check('يبقى بعد التحديث', (await page.textContent('#predict .pcount')).includes('1'));
    await shot(page, 'contest-done-entry');

    const other = await (await browser.newContext({viewport:{width:360, height:780}})).newPage();
    other.on('pageerror', e => errors.push(e.message));
    await other.goto(APP + '/nations-league/6-netherlands-serbia');
    await other.waitForSelector('#predict form', {timeout:8000});
    await other.fill('#p-name', 'غيرها'); await other.fill('#p-phone', '+966 55 123 4567');
    await other.check('#predict input[name=agree]');
    await other.click('#predict button[type=submit]');
    await other.waitForFunction(() => document.querySelector('#predict .pmsg.err'), null, {timeout:8000});
    check('الرقم نفسه من جهازٍ آخر مرفوض', (await other.textContent('#predict .pmsg')).includes('من قبل'));

    console.log('المباراة المنتهية والفيديو');
    await page.goto(APP + '/nations-league/1-france-belgium');
    await page.waitForSelector('#predict .pwin', {timeout:8000});
    const win = await page.textContent('#predict .pwin');
    check('الفائز باسمه الأول ورقمه مخفيًّا', /05•••••\d{3}/.test(win) && !/9665501/.test(await page.content()), win.slice(0, 60));
    check('الفرز بالأرقام منشور', (await page.textContent('#predict .pfp')).includes('SHA-256'));
    await shot(page, 'contest-winner');
    await page.click('#predict .pplay');
    await page.waitForFunction(() => window.SSDraw && document.querySelector('.pvid canvas'), null, {timeout:8000});
    await sleep(1200);
    const lit = await page.evaluate(() => {
      const c = document.querySelector('.pvid canvas'), d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
      let bright = 0; for (let i = 0; i < d.length; i += 4 * 97) if (d[i] + d[i+1] + d[i+2] > 600) bright++;
      return bright;
    });
    check('الفيديو يُرسم (نصٌّ أبيض على الخلفية)', lit > 50, lit);
    const scenes = await page.evaluate(async () => {
      const r = await (await fetch('/api/contest?m=1')).json();
      const c = document.createElement('canvas');
      const api = await window.SSDraw.prepare(c, {match: r.match, when: r.when, prize: r.prize, eid: '1', draw: r.draw});
      const sums = [];
      for (let t = 0; t <= api.total + 1; t += 1.5) { api.frame(t); sums.push(c.toDataURL('image/jpeg', .5).length); }
      return {total: api.total, sums, rec: window.SSDraw.canRecord()};
    });
    check('كل المشاهد تُرسم بلا خطأ', scenes.sums.length > 10 && new Set(scenes.sums).size > 8, `${scenes.total}s`);
    check('الفيديو قصير (≤ 25 ثانية)', scenes.total <= 25, scenes.total);
    check('المتصفح يسجّله ملفًّا', scenes.rec);
    const recd = await page.evaluate(async () => {
      const r = await (await fetch('/api/contest?m=1')).json();
      const out = await window.SSDraw.record({match: r.match, when: r.when, prize: r.prize, eid: '1', draw: r.draw});
      return {size: out.blob.size, type: out.type, ext: out.ext};
    });
    check('التسجيل: ملف فيديو', recd.size > 20000 && /^video\/(webm|mp4)$/.test(recd.type), JSON.stringify(recd));
    await page.keyboard.press('Escape');
    check('Esc يغلق الفيديو', !(await page.$('.pvid')));

    console.log('صفحة المدير');
    const adm = await (await browser.newContext({viewport:{width:430, height:900}})).newPage();
    adm.on('pageerror', e => errors.push(e.message));
    await adm.goto(APP + '/admin/login');
    await adm.evaluate(async () => { await fetch('/admin/api/login', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({user: 'admin', password: 'envpass123'})}); });
    await adm.goto(APP + '/admin/contest');
    await adm.waitForSelector('.mrow[data-eid="6"]', {timeout:8000});
    check('المباراة المفتوحة وعدد توقّعاتها', (await adm.textContent('.mrow[data-eid="6"] .chip')).includes('1 توقّعًا'));
    check('الجارية بلا مسابقة: لا أزرار فتح', !(await adm.$('.mrow[data-eid="4"] [data-a="on"]')));
    await adm.click('.mrow[data-eid="1"] [data-a="view"]');
    await adm.waitForSelector('#dBody .win', {timeout:8000});
    check('التفاصيل: الفائز برقمه كاملًا', /\+9665501\d{5}/.test(await adm.textContent('#dBody .win')));
    check('ورسالته لم تُرسل (القناة غير مضبوطة)', (await adm.textContent('#dBody .sent')).includes('غير مضبوطة'));
    check('وفيديو الفرز', !!(await adm.$('#dBody canvas')) && !(await adm.$eval('#vSave', b => b.hidden)));
    await shot(adm, 'contest-admin');
    check('بلا أخطاء في الصفحات', errors.length === 0, errors.join(' | '));
  } finally {
    await browser.close();
    procs.forEach(p => p.kill());
    fs.rmSync(data, {recursive: true, force: true});
  }
  console.log(`\n${pass} نجح · ${fail} فشل`);
  process.exit(fail ? 1 : 0);
})();

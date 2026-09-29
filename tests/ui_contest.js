// Browser test of the prediction contest (مسابقة التوقّعات): the admin page first (linking the contest number
// through the logistics WhatsApp service like the logistics system: number, QR, connected; the prize picked from the
// store's products with its link; the channel message ready to copy), then the card on a match page (form
// without a phone, the ready WhatsApp message, the message arriving through the service and registering the
// sender's number, one prediction per number, the remembered prediction), a finished match (winner, the draw
// video player, every scene renders, recording to a video file) and the draw details in the admin page.
// ESPN is mocked; the WhatsApp service (whatsapp-reader) and Salla's product API are tests/mock_reader.py.
//   NODE_PATH=<dir with playwright-core> node tests/ui_contest.js     (SHOTS_DIR=… for screenshots)
const { chromium } = require('playwright-core');
const { spawn, execSync } = require('child_process');
const path = require('path'); const fs = require('fs'); const os = require('os');
const ROOT = path.dirname(__dirname);
const ESPN_PORT = 9771, APP_PORT = 9772, WA_PORT = 9773, WA_SECRET = 'ui_wa_secret', TENANT = 'ssouq-guide--contest';
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
  // كليلة 28 سبتمبر: فُرزت قبل خيار الطريقة، ولم يُصب أحدٌ 0-1 فخرج فائزان ممن توقّع فوز الضيف
  const old = execSync(`python3 -c "
import json, sys; sys.path[:0] = ['${ROOT}', '${ROOT}/tests']
import mock_espn, tournament as T, contest as C
m = next(x for x in T.matches(mock_espn.scoreboard('uefa.nations', '2026')['events']) if x['id'] == '2')
rec = C._blank('2'); rec.update(on=True, prize='اشتراك 3 أشهر', winners=2, match=C._snap(m))
for i, (h, a) in enumerate([(0, 2), (1, 2), (2, 0), (0, 3), (1, 1), (0, 2), (1, 3)], 1):
    rec['entries'].append({'n': i, 'name': ['عبدالله', 'عمر', 'سارة', 'فهد', 'نورة', 'خالد', 'ريم'][i - 1],
                           'phone': '96655200%04d' % i, 'h': h, 'a': a, 'at': m['ts'] - 600 + i, 'ipk': '', 'promo': False})
rec['draw'] = C.draw(dict(rec, mode='outcome'), m, m['ts'] + 7000); del rec['draw']['mode']
print(json.dumps(rec, ensure_ascii=False))
"`).toString();
  fs.writeFileSync(path.join(dir, 'contest', '2.json'), old);
}

(async () => {
  const data = fs.mkdtempSync(path.join(os.tmpdir(), 'uicontest_'));
  seedFinished(data);
  const APP = `http://127.0.0.1:${APP_PORT}`, WA = `http://127.0.0.1:${WA_PORT}`;
  const env = Object.fromEntries(Object.entries(process.env).filter(([k]) => !k.startsWith('WHATSAPP_READER_') && k !== 'SALLA_ADMIN_TOKEN'));
  const procs = [spawn('python3', [path.join(ROOT,'tests/mock_espn.py'), String(ESPN_PORT)], {stdio:'ignore'}),
                 spawn('python3', [path.join(ROOT,'tests/mock_reader.py'), String(WA_PORT), WA_SECRET], {stdio:'ignore'}),
                 spawn('python3', [path.join(ROOT,'xm_lines.py'), 'web'], {stdio:'ignore', env:{...env,
                   XM_DATA: data, XM_BIND:'127.0.0.1', XM_PORT:String(APP_PORT), XM_ADMIN_PASSWORD:'envpass123',
                   LEAGUE_API:`http://127.0.0.1:${ESPN_PORT}`, SALLA_API: WA, WHATSAPP_READER_URL: WA,
                   WHATSAPP_READER_SECRET: WA_SECRET, CONTEST_INBOUND_URL: APP + '/api/contest/wa-inbound'}})];
  await up(`http://127.0.0.1:${ESPN_PORT}/v2/sports/soccer/ksa.1/standings`);
  await up(`http://127.0.0.1:${APP_PORT}/robots.txt`);
  await up(`${WA}/store/v1/products`);
  // الخدمة (وهمية): «مسح الرمز»، ورسالةٌ خاصة من رقم المرسل تمرّرها للأداة كما تفعل الحقيقية
  const reader = async (p, body) => (await fetch(WA + p, {method: 'POST', headers: {'Content-Type': 'application/json',
    'X-Reader-Secret': WA_SECRET}, body: JSON.stringify(body || {})})).json();
  const whatsapp = (from, text) => reader('/_test/dm/' + TENANT, {wa_message_id: 'W' + Date.now() + Math.random(),
    sender_number: from, sender_name: '', sent_at: Math.floor(Date.now() / 1000), body: text, quoted_body: '',
    forwarded: false, media_base64: null, media_mime: null});
  const waText = href => decodeURIComponent(new URL(href).searchParams.get('text'));
  const browser = await chromium.launch({executablePath: EXE, args:['--no-sandbox']});
  const errors = [];
  try {
    console.log('صفحة المدير: ربط الرقم والجائزة ورسالة القناة');
    const actx = await browser.newContext({viewport:{width:430, height:900}});
    await actx.grantPermissions(['clipboard-read', 'clipboard-write'], {origin: APP});
    const adm = await actx.newPage();
    adm.on('pageerror', e => errors.push(e.message));
    await adm.goto(APP + '/admin/login');
    await adm.evaluate(async () => { await fetch('/admin/api/login', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({user: 'admin', password: 'envpass123'})}); });
    await adm.goto(APP + '/admin/contest');
    await adm.waitForSelector('.mrow[data-eid="6"]', {timeout:8000});
    await adm.waitForSelector('#waConnect:not([hidden])', {timeout:8000});
    check('كالنظام اللوجستي: رقم الجوال و«ربط» وحدهما، بلا رابطٍ ولا سرّ', (await adm.textContent('#waState')).includes('أدخل الرقم')
          && (await adm.textContent('#waChip')).includes('غير مربوط') && (await adm.$$('#waSec input')).length === 2
          && !(await adm.$('#rUrl')) && !(await adm.$('#rSecret')));
    check('والتسجيل غير جاهز', (await adm.textContent('#stWa')).includes('غير جاهز'));
    await adm.fill('#wNum', '0500000009');
    await adm.click('#wGo');
    await adm.waitForSelector('#waQr:not([hidden])', {timeout:8000});
    check('يظهر رمز QR للمسح وشرحه', (await adm.getAttribute('#wQrImg', 'src')).startsWith('data:image/png;base64,')
          && (await adm.textContent('#waQr')).includes('الأجهزة المرتبطة') && (await adm.textContent('#waChip')).includes('بانتظار'));
    await shot(adm, 'contest-admin-qr');
    await reader('/_test/scan/' + TENANT);
    await adm.waitForFunction(() => document.getElementById('waChip').textContent.includes('مربوط ✓'), null, {timeout:10000});
    check('بعد المسح: مربوطٌ برقمه، والرمز يختفي وحده', (await adm.textContent('#waState')).includes('+966500000009')
          && await adm.$eval('#waQr', e => e.hidden) && await adm.$eval('#waConnect', e => e.hidden) && await adm.isVisible('#waOn'));
    check('واستقبال التوقّعات جاهز', (await adm.textContent('#stWa')).includes('جاهز ✓'));
    await adm.fill('#wTest', '0551112222'); await adm.click('#wTestGo');
    await adm.waitForFunction(() => document.getElementById('waMsg').textContent.includes('✓'), null, {timeout:8000});
    check('رسالة تجربة من رقم المسابقة', true);

    const opts = await adm.$$eval('.mrow[data-eid="6"] select[data-f="prize_id"] option', o => o.map(x => [x.value, x.textContent]));
    check('الجائزة: اشتراكات المتجر بأسعارها، والنافد معلَّم، وجائزةٌ أخرى', opts.some(([v, t]) => v === '1001'
          && t.includes('اشتراك سمارت 3 أشهر') && t.includes('79 ر.س')) && opts.some(([v, t]) => v === '1002' && t.includes('نافد'))
          && !opts.some(([v]) => v === '1003') && opts.some(([v]) => v === '__text'), JSON.stringify(opts).slice(0, 120));
    await adm.selectOption('.mrow[data-eid="6"] select[data-f="prize_id"]', '1001');
    check('اختياره يُظهر رابطه', (await adm.getAttribute('.mrow[data-eid="6"] [data-f="plink"]', 'href')) === 'https://ssouq.com/smart-3m/p1001'
          && await adm.isVisible('.mrow[data-eid="6"] [data-f="plink"]'));
    await adm.selectOption('.mrow[data-eid="6"] select[data-f="prize_id"]', '__text');
    check('«جائزة أخرى» تفتح خانة الكتابة', await adm.isVisible('.mrow[data-eid="6"] input[data-f="prize"]')
          && !(await adm.isVisible('.mrow[data-eid="6"] [data-f="plink"]')));
    await adm.selectOption('.mrow[data-eid="6"] select[data-f="prize_id"]', '1001');
    await adm.click('.mrow[data-eid="6"] [data-a="on"]');
    await adm.waitForFunction(() => (document.querySelector('.mrow[data-eid="6"] .chip') || {}).textContent.includes('مفتوحة'), null, {timeout:8000});
    check('فُتحت المسابقة بالاشتراك المختار ورابطه', (await adm.$eval('.mrow[data-eid="6"] select[data-f="prize_id"]', s => s.value)) === '1001'
          && (await adm.getAttribute('.mrow[data-eid="6"] [data-f="plink"]', 'href')).startsWith('https://ssouq.com/smart-3m/p1001?utm_source='));
    const ann = await adm.inputValue('#annText');
    check('رسالة القناة كُتبت وحدها: المباراة والجائزة والرابط', ann.startsWith('⚽🎉 تحدّي التوقعات مع سمارت سوق')
          && ann.includes('هولندا × صربيا') && ann.includes('ويحصل على:\n⭐ اشتراك سمارت 3 أشهر')
          && ann.includes('https://guide.ssouq.com/nations-league/6-netherlands-serbia#predict'), ann.slice(0, 90));
    await adm.click('.mrow[data-eid="6"] [data-a="copy"]');
    await adm.waitForFunction(() => document.querySelector('.mrow[data-eid="6"] .msg').textContent.includes('نُسخت'), null, {timeout:5000});
    check('«نسخ رسالتها للقناة»: رسالة المباراة برابطها الخاص', (await adm.evaluate(() => navigator.clipboard.readText())) === ann);
    await adm.selectOption('.mrow[data-eid="6"] select[data-f="extra"]', '10');
    await adm.click('.mrow[data-eid="6"] [data-a="save"]');
    await adm.waitForFunction(() => DATA.rows.find(r => r.eid === '6').contest.extra === 10, null, {timeout:8000});
    check('خيار الإقفال بعد البداية بـ 10 دقائق يُحفظ', (await adm.$eval('.mrow[data-eid="6"] select[data-f="extra"]', s => s.value)) === '10');
    await adm.selectOption('.mrow[data-eid="6"] select[data-f="extra"]', '0');
    await adm.click('.mrow[data-eid="6"] [data-a="save"]');
    await adm.waitForFunction(() => DATA.rows.find(r => r.eid === '6').contest.extra === 0, null, {timeout:8000});
    await adm.click('#annCopy');
    await adm.waitForFunction(() => document.getElementById('annMsg').textContent.includes('نُسخت'), null, {timeout:5000});
    check('«نسخ الرسالة» ينسخها كما هي', (await adm.evaluate(() => navigator.clipboard.readText())) === ann);
    await adm.fill('#annText', ann + '\nسطرٌ من المدير');
    await adm.evaluate(() => load());
    check('تعديل المدير لا يمسحه التحديث الدوري', (await adm.inputValue('#annText')).endsWith('سطرٌ من المدير'));
    await adm.click('#annReset');
    check('و«إعادة إنشاء» يعيدها', (await adm.inputValue('#annText')) === ann);
    check('بلا تمرير أفقي في صفحة المدير (430px)', await adm.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    check('مباريات كأس الخليج مع دوري الأمم، واسم البطولة في كل صف',
          (await adm.textContent('.mrow[data-eid="103"] .cupname')) === 'كأس الخليج العربي'
          && (await adm.textContent('.mrow[data-eid="6"] .cupname')) === 'دوري الأمم الأوروبية'
          && (await adm.getAttribute('.mrow[data-eid="103"] a[href*="#predict"]', 'href')).includes('/gulf-cup/103-saudi-arabia-iraq'));
    await adm.fill('.mrow[data-eid="103"] [data-f="tv"]', 'AL KASS One');
    await adm.press('.mrow[data-eid="103"] [data-f="tv"]', 'Tab');
    await adm.waitForFunction(() => document.querySelector('.mrow[data-eid="103"] .msg').textContent.includes('حُفظت القناة'), null, {timeout:8000});
    check('القناة الناقلة تُحفظ فور كتابتها، ومعها اقتراحات', (await adm.$$eval('#tvlist option', o => o.map(x => x.value))).includes('AL KASS Two'));
    await adm.evaluate(() => load());
    check('وتبقى بعد التحديث', (await adm.inputValue('.mrow[data-eid="103"] [data-f="tv"]')) === 'AL KASS One');
    const gpage = await (await browser.newContext({viewport:{width:360, height:780}})).newPage();
    gpage.on('pageerror', e => errors.push(e.message));
    await gpage.goto(APP + '/gulf-cup/103-saudi-arabia-iraq');
    check('وتظهر في صفحة المباراة', (await gpage.textContent('.mhero')).includes('القناة الناقلة: AL KASS One'));
    await gpage.goto(APP + '/gulf-cup');
    check('وفي جدول كأس الخليج', (await gpage.textContent('#upcoming')).includes('AL KASS One')
          && await gpage.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await shot(gpage, 'gulf-cup');
    check('قناة كل بطولة جاهزة في رأس المباريات', (await adm.inputValue('#cupTv [data-cup="/gulf-cup"]')) === 'AL KASS'
          && (await adm.inputValue('#cupTv [data-cup="/nations-league"]')) === 'beIN SPORTS'
          && (await adm.getAttribute('.mrow[data-eid="6"] [data-f="tv"]', 'placeholder')) === 'beIN SPORTS (قناة البطولة)');
    await adm.fill('#cupTv [data-cup="/nations-league"]', 'beIN SPORTS 1');
    await adm.press('#cupTv [data-cup="/nations-league"]', 'Enter');
    await adm.waitForFunction(() => document.querySelector('#cupTvMsg').textContent.includes('حُفظت: beIN SPORTS 1'), null, {timeout:8000});
    await adm.waitForFunction(() => document.querySelector('.mrow[data-eid="6"] [data-f="tv"]').placeholder.includes('beIN SPORTS 1'), null, {timeout:8000});
    check('وتُحفظ فور كتابتها، وصفوف مبارياتها تعرضها', (await adm.inputValue('#cupTv [data-cup="/nations-league"]')) === 'beIN SPORTS 1');
    await gpage.goto(APP + '/nations-league/6-netherlands-serbia');
    check('فتظهر في صفحة مباراة دوري الأمم بلا كتابتها لها', (await gpage.textContent('.mhero')).includes('القناة الناقلة: beIN SPORTS 1'));
    await gpage.goto(APP + '/nations-league/widget');
    const wtv = await gpage.$$eval('a.match', rs => rs.map(r => r.textContent.replace(/\s+/g, ' ')));
    check('وفي ودجت المتجر: قناةٌ تحت كل مباراة من البطولتين', wtv.some(t => t.includes('beIN SPORTS 1'))
          && wtv.some(t => t.includes('AL KASS One')) && wtv.some(t => /AL KASS(?! One)/.test(t))
          && await gpage.evaluate(() => document.documentElement.scrollWidth <= innerWidth), wtv.length);
    await gpage.evaluate(() => document.querySelector('#more') && (document.querySelector('#more').open = true));
    await shot(gpage, 'widget-channels');
    await adm.fill('#cupTv [data-cup="/nations-league"]', 'beIN SPORTS');
    await adm.press('#cupTv [data-cup="/nations-league"]', 'Enter');
    await adm.waitForFunction(() => document.querySelector('#cupTvMsg').textContent.includes('حُفظت: beIN SPORTS '), null, {timeout:8000});
    await shot(adm, 'contest-admin');

    console.log('بطاقة المباراة المفتوحة');
    const ctx = await browser.newContext({viewport:{width:360, height:780}});
    await ctx.route(/^https:\/\/wa\.me\//, r => r.fulfill({status: 200, contentType: 'text/html', body: 'wa'}));
    const page = await ctx.newPage();
    page.on('popup', p => p.close().catch(() => {}));      // واتساب يُفتح في نافذة: لا يلزم هنا
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(APP + '/nations-league/6-netherlands-serbia');
    await page.waitForSelector('#predict form', {timeout:8000});
    check('النموذج: الفريقان وأسماؤهما', (await page.textContent('#predict .pteams')).includes('هولندا')
          && (await page.textContent('#predict .pteams')).includes('صربيا'));
    check('العدّاد يعدّ حتى الإقفال', /^(يوم|يومين) و\d{2}:\d{2}:\d{2}$/.test(await page.textContent('#predict .cd')),
          await page.textContent('#predict .cd'));
    check('بلا تمرير أفقي على 360px', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    const cshare = await page.getAttribute('#predict form ~ a.pshare', 'href');
    check('زرّ «شارك المسابقة» تحت النموذج قبل التوقّع: رابط المباراة نفسها', cshare && cshare.startsWith('https://wa.me/?text=')
          && waText(cshare).includes('/nations-league/6-netherlands-serbia#predict'), cshare && waText(cshare).slice(0, 90));
    await page.click('#predict [data-side="h"] [data-d="1"]'); await page.click('#predict [data-side="h"] [data-d="1"]');
    await page.click('#predict [data-side="a"] [data-d="1"]');
    await page.click('#predict [data-side="a"] [data-d="1"]'); await page.click('#predict [data-side="a"] [data-d="-1"]');
    check('أزرار الأهداف', (await page.$$eval('#predict output', o => o.map(x => x.textContent))).join('-') === '2-1');
    check('لا خانة رقم: الرقم من واتساب', !(await page.$('#p-phone')));
    check('والبطاقة تقول من يفوز: النتيجة بالضبط فقط', (await page.textContent('#predict')).includes('يفوز من يصيب النتيجة بالضبط فقط'));
    await page.click('#predict button[type=submit]');
    check('الاسم قبل الإرسال', (await page.textContent('#predict .pmsg')).includes('اسمك'));
    await page.fill('#p-name', 'سارة');
    await page.click('#predict button[type=submit]');
    check('الموافقة على الشروط', (await page.textContent('#predict .pmsg')).includes('شروط المسابقة'));
    await page.check('#predict input[name=agree]');
    await shot(page, 'contest-form');
    await page.click('#predict button[type=submit]');
    await page.waitForSelector('#predict .pwait', {timeout:8000});
    const code = await page.textContent('#predict .pwait code');
    const href = await page.getAttribute('#predict .pwait a.wa', 'href');
    check('سطر الجائزة: الاشتراك برابط صفحته', (await page.getAttribute('#predict .pprize', 'href') || '').includes('p1001?utm_source=')
          && (await page.textContent('#predict .pprize')).includes('اشتراك سمارت 3 أشهر'));
    check('الخطوة الأخيرة: رمزٌ وزرّ واتساب برسالةٍ جاهزة إلى رقم المسابقة', /^[A-Z0-9]{6}$/.test(code)
          && href.startsWith('https://wa.me/966500000009?text=') && waText(href).includes('رمز التوقّع: ' + code)
          && waText(href).includes('هولندا 2 – 1 صربيا'), code);
    await shot(page, 'contest-wait');
    const sent = await whatsapp('966551234567', waText(href));
    check('رسالة الواتساب تُسجّله ويُردّ عليه من رقم المسابقة', sent.code === 200 && sent.answer.status === 'ok'
          && sent.sent.length && sent.sent[0].to === '966551234567' && sent.sent[0].body.includes('تم تسجيل توقّعك'),
          JSON.stringify(sent).slice(0, 80));
    await page.waitForSelector('#predict .pmine', {timeout:10000});
    const mine = await page.textContent('#predict .pmine');
    check('والصفحة تؤكّد برقم المرسل مخفيًّا', mine.includes('سجّلت توقّعك') && mine.includes('05•••••567'), mine.slice(0, 70));
    check('وزرّ مشاركة المسابقة', (await page.getAttribute('#predict a.pshare', 'href')).startsWith('https://wa.me/?text='));
    await page.reload();
    await page.waitForSelector('#predict .pmine', {timeout:8000});
    check('يبقى بعد التحديث', (await page.textContent('#predict .pcount')).includes('توقّعٌ واحد'));
    await shot(page, 'contest-done-entry');

    const octx = await browser.newContext({viewport:{width:360, height:780}});
    await octx.route(/^https:\/\/wa\.me\//, r => r.fulfill({status: 200, contentType: 'text/html', body: 'wa'}));
    const other = await octx.newPage();
    other.on('popup', p => p.close().catch(() => {}));
    other.on('pageerror', e => errors.push(e.message));
    await other.goto(APP + '/nations-league/6-netherlands-serbia');
    await other.waitForSelector('#predict form', {timeout:8000});
    await other.fill('#p-name', 'غيرها');
    await other.click('#predict [data-side="a"] [data-d="1"]');
    await other.check('#predict input[name=agree]');
    await other.click('#predict button[type=submit]');
    await other.waitForSelector('#predict .pwait', {timeout:8000});
    await whatsapp('966551234567', waText(await other.getAttribute('#predict .pwait a.wa', 'href')));
    await other.waitForSelector('#predict .pmine', {timeout:10000});
    check('الرقم نفسه من جهازٍ آخر: مسجّلٌ من قبل ولا يتغيّر', (await other.textContent('#predict .pmine')).includes('من قبل')
          && (await page.evaluate(async () => (await (await fetch('/api/contest?m=6')).json()).count)) === 1);
    console.log('صفحة المسابقات /predict');
    await page.goto(APP + '/predict');
    await page.waitForSelector('.mc[data-m="6"]', {timeout:8000});
    check('ليليةٌ افتراضًا، وبلا تمرير أفقي على 360px', (await page.getAttribute('html', 'data-theme')) === 'dark'
          && await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    const hs = await page.getAttribute('.hbtn a.pshare', 'href'), cs6 = await page.getAttribute('.mc[data-m="6"] a.pshare', 'href');
    check('«شارك المسابقة» في رأس الصفحة برابطها', hs.startsWith('https://wa.me/?text=') && waText(hs).includes('/predict'), waText(hs).slice(0, 90));
    check('و«مشاركة» في كل بطاقةٍ مفتوحة برابط مباراتها', await page.$$eval('.mc.open', cs => cs.every(c => c.querySelector('a.pshare')))
          && waText(cs6).includes('هولندا') && waText(cs6).includes('/nations-league/6-netherlands-serbia#predict')
          && !(await page.$('.mc.done a.pshare')), waText(cs6).slice(0, 90));
    check('والقناة في البطاقة: قناة البطولة وإن لم تُكتب للمباراة', (await page.textContent('.mc[data-m="6"] .meta')).includes('beIN SPORTS'));
    const sctx = await browser.newContext({viewport:{width:360, height:780}});
    await sctx.addInitScript(() => { navigator.share = d => { window.__shared = d; return Promise.resolve(); }; });
    const sp = await sctx.newPage();
    sp.on('pageerror', e => errors.push(e.message));
    await sp.goto(APP + '/predict');
    await sp.click('.hbtn a.pshare');
    await sp.click('.mc[data-m="6"] a.pshare');
    const shared = await sp.evaluate(() => window.__shared);
    check('وفي الجوال تفتح المشاركة الأصلية (واتساب وغيره) بلا مغادرة الصفحة', shared && shared.url.endsWith('/nations-league/6-netherlands-serbia#predict')
          && shared.text.includes('هولندا') && sp.url().endsWith('/predict'), JSON.stringify(shared || {}).slice(0, 90));
    await sp.goto(APP + '/nations-league/6-netherlands-serbia');
    await sp.waitForSelector('#predict form ~ a.pshare', {timeout:8000});
    await sp.click('#predict form ~ a.pshare');
    check('ومن بطاقة المباراة كذلك', (await sp.evaluate(() => window.__shared.url)).endsWith('/nations-league/6-netherlands-serbia#predict')
          && sp.url().endsWith('/nations-league/6-netherlands-serbia'));
    await sctx.close();
    check('بطاقة المباراة تعرف توقّع الزائر من متصفحه', (await page.textContent('.mc[data-m="6"] .mine')).includes('توقّعك مسجّل: 2-1')
          && !(await page.$eval('.mc[data-m="6"] .mine', e => e.hidden)));
    await page.click('.tabs button[data-k="done"]');
    const vis = await page.$$eval('.mc', cs => cs.filter(c => !c.hidden).map(c => c.dataset.tab));
    check('التصفية: «منتهية» تُظهر المفروزة وحدها', vis.length > 0 && vis.every(t => t === 'done'), vis.join(','));
    await page.click('.tabs button[data-k="all"]');
    check('و«كل المسابقات» تعيدها كلها', (await page.$$eval('.mc', cs => cs.filter(c => c.hidden).length)) === 0);
    await page.click('#tbtn');
    await page.reload();
    check('زرّ الوضع النهاري يُحفظ', (await page.getAttribute('html', 'data-theme')) === 'light');
    await page.click('#tbtn');
    await shot(page, 'predict-page');
    await page.goto(APP + '/nations-league/6-netherlands-serbia');
    await page.waitForSelector('#predict .pmine', {timeout:8000});
    const plain = await whatsapp('966551234567', 'السلام عليكم، متى ينتهي اشتراكي؟');
    check('رسائل العملاء الأخرى: ignored ولا ردّ', plain.answer.status === 'ignored' && plain.sent.length === 0);

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

    console.log('صفحة المدير: التفاصيل والفرز');
    await adm.goto(APP + '/admin/contest');
    await adm.waitForSelector('.mrow[data-eid="6"]', {timeout:8000});
    check('المباراة المفتوحة وعدد توقّعاتها', (await adm.textContent('.mrow[data-eid="6"] .chip')).includes('1 توقّعًا'));
    check('الجارية بلا مسابقة: لا أزرار فتح', !(await adm.$('.mrow[data-eid="4"] [data-a="on"]')));
    await adm.click('.mrow[data-eid="1"] [data-a="view"]');
    await adm.waitForSelector('#dBody .win', {timeout:8000});
    check('التفاصيل: الفائز برقمه كاملًا', /\+9665501\d{5}/.test(await adm.textContent('#dBody .win')));
    check('ورسالة التهنئة أُرسلت له', (await adm.textContent('#dBody .sent')).includes('أُرسلت ✓'));
    check('وفيديو الفرز', !!(await adm.$('#dBody canvas')) && !(await adm.$eval('#vSave', b => b.hidden)));
    await shot(adm, 'contest-admin-draw');

    console.log('إعادة فرزٍ قديم على «النتيجة بالضبط فقط»');
    await adm.click('#dClose');
    await adm.click('.mrow[data-eid="2"] [data-a="view"]');
    await adm.waitForSelector('#dRedraw', {timeout:8000});
    check('فرزٌ قديم بفائزَين ممن أصاب الفائز، وزرّ «أعد الفرز: النتيجة بالضبط فقط»', (await adm.$$('#dBody .win')).length === 2
          && (await adm.textContent('#dBody')).includes('من أصاب النتيجة بالضبط، وإلا من أصاب الفائز'));
    adm.once('dialog', dlg => dlg.accept());
    await adm.click('#dRedraw');
    await adm.waitForFunction(() => document.getElementById('dBody').textContent.includes('أُعيد الفرز'), null, {timeout:8000});
    const after = await adm.textContent('#dBody');
    check('بعد الإعادة: لا فائز، والطريقة «بالضبط فقط»، ومن كانا فائزين في السجلّ', !(await adm.$('#dBody .win'))
          && after.includes('لم يُصب أحدٌ النتيجة بالضبط، فلا فائز') && after.includes('من أصاب النتيجة بالضبط فقط')
          && after.includes('عبدالله') && !(await adm.$('#dRedraw')), after.slice(0, 80));
    await adm.click('#dClose');
    const pub2 = await (await browser.newContext({viewport:{width:360, height:780}})).newPage();
    pub2.on('pageerror', e => errors.push(e.message));
    await pub2.goto(APP + '/nations-league/2-germany-greece');
    await pub2.waitForSelector('#predict .pcount', {timeout:8000});
    const card2 = await pub2.textContent('#predict');
    check('وبطاقة المباراة للعموم: لم يُصب أحدٌ النتيجة بالضبط، فلا فائز', card2.includes('لم يُصب أحدٌ النتيجة بالضبط، فلا فائز')
          && !(await pub2.$('#predict .pwin')), card2.slice(0, 80));
    await pub2.click('#predict .pplay');                  // سكربت الفيديو يُحمَّل عند الطلب
    await pub2.waitForFunction(() => window.SSDraw && document.querySelector('.pvid canvas'), null, {timeout:8000});
    const vid2 = await pub2.evaluate(async () => {
      const r = await (await fetch('/api/contest?m=2')).json();
      const c = document.createElement('canvas');
      const api = await window.SSDraw.prepare(c, {match: r.match, when: r.when, prize: r.prize, eid: '2', draw: r.draw});
      for (let t = 0; t <= api.total + 1; t += 1.5) api.frame(t);
      return api.total;
    });
    check('وفيديو فرزها يُرسم بلا خطأ', vid2 > 5, vid2);
    check('بلا أخطاء في الصفحات', errors.length === 0, errors.join(' | '));
  } finally {
    await browser.close();
    procs.forEach(p => p.kill());
    fs.rmSync(data, {recursive: true, force: true});
  }
  console.log(`\n${pass} نجح · ${fail} فشل`);
  process.exit(fail ? 1 : 0);
})();

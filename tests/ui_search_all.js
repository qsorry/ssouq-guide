// Browser test: a client with several gates searches all of them at once — results grouped under
// each gate's name (the selected gate first), copy uses that gate's host, gates that couldn't be
// searched are named, and a replacement for a number found nowhere can go to any gate.
const { chromium } = require('playwright-core');
const { spawn, execSync } = require('child_process');
const path = require('path'); const fs = require('fs'); const os = require('os');
const ROOT = path.dirname(__dirname);
const F1_PORT = 9771, F2_PORT = 9772, APP_PORT = 9773;
const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'searchall_'));
const SHOTS = process.env.SHOTS_DIR || '';
const EXE = execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim();
let pass = 0, fail = 0;
const check = (l, c, x='') => { c ? (pass++, console.log(`  PASS  ${l}${x?'  ('+x+')':''}`)) : (fail++, console.log(`  FAIL  ${l}${x?'  ('+x+')':''}`)); };
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function up(u){ for (let i=0;i<80;i++){ try { execSync(`curl -s -o /dev/null ${u}`); return; } catch(e){} await sleep(150); } }
const api = (page, url, body) => page.evaluate(async ([u, b]) => (await fetch(u, b === undefined ? {} :
  {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(b)})).json(), [url, body]);
const shot = async (p, n) => { if (SHOTS) await p.screenshot({path: path.join(SHOTS, n + '.png'), fullPage: true}); };

const HA = 'http://a.host:80', HB = 'http://b.host:80', GUIDE = 'https://guide.ssouq.com/';
const GUIDE_F = GUIDE + '#activate/falcon';      // البوابات فالكون: الرابط العام موجّهًا لصفحة اشتراكها

(async () => {
  const f1 = spawn('python3', [path.join(ROOT,'tests/mock_falcon.py'), String(F1_PORT), 'k1'], {stdio:'ignore'});
  const f2 = spawn('python3', [path.join(ROOT,'tests/mock_falcon.py'), String(F2_PORT), 'k2'], {stdio:'ignore'});
  const app = spawn('python3', [path.join(ROOT,'xm_lines.py'), 'web'],
    {stdio:'ignore', env:{...process.env, XM_DATA:dataDir, XM_BIND:'127.0.0.1', XM_PORT:String(APP_PORT)}});
  await up(`http://127.0.0.1:${APP_PORT}/admin/login`);
  const browser = await chromium.launch({executablePath: EXE, args:['--no-sandbox']});
  const APP = `http://127.0.0.1:${APP_PORT}`;
  const F1 = `http://127.0.0.1:${F1_PORT}/api/v1`, F2 = `http://127.0.0.1:${F2_PORT}/api/v1`;
  const admin = await (await browser.newContext()).newPage();
  const user = await (await browser.newContext({permissions:['clipboard-read','clipboard-write']})).newPage();
  const one = await (await browser.newContext()).newPage();
  const search = async (p, q) => {
    await p.fill('#searchQ', q);
    await p.click('#searchBtn');
    await p.waitForFunction(() => !/جاري البحث/.test(document.querySelector('#searchRes').textContent), null, {timeout: 10000});
  };
  try {
    await admin.goto(APP + '/admin/setup');
    await api(admin, '/admin/api/setup', {password:'admin123'});
    let r = await api(admin, '/admin/api/accounts', {name:'عميل البوابات', user:'multi', password:'pw_multi', guide_url: GUIDE,
      gates:[{name:'بوابة أ', mode:'falcon', api_url:F1, api_key:'k1', host:HA},
             {name:'بوابة ب', mode:'falcon', api_url:F2, api_key:'k2', host:HB},
             {name:'بوابة متوقّفة', mode:'falcon', api_url:'http://127.0.0.1:9/api/v1', api_key:'x', host:'http://c.host:80'}]});
    check('client with three gates created', r.ok === true, r.error || '');
    await api(admin, '/admin/api/accounts', {name:'عميل بوابة', user:'one', password:'pw_one',
      gates:[{name:'بوابته', mode:'falcon', api_url:F1, api_key:'k1', host:HA}]});

    await user.goto(APP + '/admin/login');
    await api(user, '/admin/api/login', {user:'multi', password:'pw_multi'});
    await user.goto(APP + '/admin');
    await user.waitForSelector('input[name="pkg"]', {timeout: 8000});
    const me = await api(user, '/admin/api/me');
    const gid = Object.fromEntries(me.gates.map(g => [g.name, g.id]));

    // ---- الافتراضي: كل البوابات ----
    check('scope switch shown for a client with several gates', await user.isVisible('#searchScope'));
    check('all gates by default', (await user.textContent('#searchScope button.on')).trim() === 'كل البوابات'
          && (await user.textContent('#searchTtl')).trim() === 'بحث في كل البوابات', await user.textContent('#searchTtl'));

    // يوزرٌ على بوابة ب وحدها — والمختارة أ
    r = await api(user, '/admin/api/create', {gate: gid['بوابة ب'], package_id: '167', username: 'onlyonb', password: 'pwb', count: 1});
    check('a user created on gate ب only', (r.lines || []).length === 1, r.error || '');
    await search(user, 'onlyonb');
    const groups = await user.$$eval('#searchRes .sg-h', els => els.map(e => e.textContent.replace(/\s+/g, ' ').trim()));
    check('found under gate ب only, though أ is selected', groups.length === 1 && groups[0].startsWith('بوابة ب'), groups.join(' | '));
    check('the summary counts the gates', (await user.textContent('#searchRes .sg-sum')).includes('وُجد في بوابة واحدة من 3'));
    const cp = await user.$eval('#searchRes button.cb', b => b.dataset.copy);
    check('copy uses that gate\'s host, not the selected one', cp === `Host ${HB} User onlyonb Pass pwb Guide ${GUIDE_F}`, cp);
    const notes = await user.textContent('#searchRes .sg-notes');
    check('the unreachable gate is named with why', notes.includes('بوابة متوقّفة') && notes.includes('تعذّر البحث فيها'), notes);
    check('no «not found» card when found somewhere', !(await user.$('#mkRepl')));

    await search(user, 'user003');
    const g2 = await user.$$eval('#searchRes .sg-h', els => els.map(e => e.textContent.replace(/\s+/g, ' ').trim()));
    check('found on both live gates, the selected gate first', g2.length === 2 && g2[0].startsWith('بوابة أ') && g2[0].includes('المختارة')
          && g2[1].startsWith('بوابة ب'), g2.join(' | '));
    const cps = await user.$$eval('#searchRes button.cb', bs => bs.map(b => b.dataset.copy));
    check('each row copies its own gate\'s line', cps[0].startsWith('Host ' + HA + ' User user003') && cps[1].startsWith('Host ' + HB + ' User user003'), cps.join(' / '));
    await user.click('#searchRes button.cb >> nth=1');
    await sleep(150);
    check('clipboard holds gate ب\'s line', (await user.evaluate(() => navigator.clipboard.readText())) === cps[1]);
    await shot(user, 'search-all');

    // ---- نطاق «البوابة المختارة» يعيد البحث فيها وحدها، ويُتذكَّر ----
    await user.click('#searchScope button[data-scope="one"]');
    await user.waitForFunction(() => !/جاري البحث/.test(document.querySelector('#searchRes').textContent) && document.querySelector('#searchRes table'), null, {timeout: 8000});
    check('selected gate only: title, no groups, its row', (await user.textContent('#searchTtl')).trim() === 'بحث في البوابة'
          && !(await user.$('#searchRes .sg')) && (await user.$$('#searchRes button.cb')).length === 1);
    await search(user, 'onlyonb');
    check('…a user on another gate is not found there', (await user.textContent('#searchRes .miss-h')).trim() === 'لم يُعثر على «onlyonb»');
    await user.reload();
    await user.waitForSelector('input[name="pkg"]', {timeout: 8000});
    check('the choice survives a reload', (await user.textContent('#searchScope button.on')).trim() === 'البوابة المختارة');
    await user.click('#searchScope button[data-scope="all"]');

    // ---- لم يُعثر عليه في أي بوابة: البديل في البوابة التي تُختار ----
    const OLD = '555000123456';
    await search(user, OLD);
    check('«not found in any gate»', (await user.textContent('#searchRes .miss-h')).includes('لم يُعثر على «' + OLD + '» في أي بوابة'));
    check('…and the gate that could not be searched is named above it', (await user.textContent('#searchRes .sg-notes')).includes('بوابة متوقّفة'));
    await user.click('#mkRepl');
    await user.waitForSelector('#mkGo', {timeout: 8000});
    const rg = await user.$$eval('#rGates span', els => els.map(e => e.textContent));
    check('replacement: a gate choice, the selected gate ticked', rg.join('|') === 'بوابة أ|بوابة ب|بوابة متوقّفة'
          && await user.$eval('input[name="rgate"]:checked', e => e.value) === gid['بوابة أ'], rg.join('|'));
    await user.click('#rGates label:nth-child(2)');
    await user.waitForFunction(id => { const c = document.querySelector('input[name="rgate"]:checked'); return c && c.value === id && document.querySelector('#mkGo'); },
                               gid['بوابة ب'], {timeout: 8000});
    check('picking gate ب selects it on the page', (await user.textContent('#heroName')).trim() === 'بوابة ب'
          && (await user.textContent('.gate-tab.on')).trim() === 'بوابة ب');
    check('…and the search results stay', (await user.textContent('#searchRes .miss-h')).includes(OLD));
    check('…the button text is unchanged', (await user.textContent('#mkGo')).trim() === 'إنشاء البديل وربطه بـ ' + OLD);
    await shot(user, 'search-all-replacement');
    await user.click('#mkGo');
    await user.waitForSelector('#mkBox .msg.ok', {timeout: 8000});
    const rl = await user.evaluate(() => navigator.clipboard.readText());
    check('replacement created on gate ب (its host)', /^Host http:\/\/b\.host:80 User \d{12} Pass \d{12} /.test(rl), rl);
    await search(user, OLD);
    const lg = await user.$$eval('#searchRes .sg', els => els.map(e => [e.querySelector('.sg-h').textContent.trim(), !!e.querySelector('.lnk')]));
    check('searching the old number again: its link under gate ب', lg.length === 1 && lg[0][0].startsWith('بوابة ب') && lg[0][1], JSON.stringify(lg));

    // ---- رابط الشرح العام يُحفظ من الصفحة: يُوجَّه لصفحة اشتراك كل بوابة، بلا إعادة تحميل ----
    await user.fill('#myGuide', 'https://guide.ssouq.com/?ref=x');
    await Promise.all([user.waitForResponse(r => r.url().includes('/api/me')), user.click('#saveGuide')]);
    await search(user, 'onlyonb');
    const cp2 = await user.$eval('#searchRes button.cb', b => b.dataset.copy);
    check('a new general link is used at once, aimed at the gate\'s subscription page',
          cp2 === `Host ${HB} User onlyonb Pass pwb Guide https://guide.ssouq.com/?ref=x#activate/falcon`, cp2);

    // ---- الجوال ----
    await search(user, 'user003');
    await user.setViewportSize({width: 390, height: 844});
    await sleep(200);
    check('phone: no horizontal scroll', !(await user.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)));
    await user.$eval('#searchBox', e => e.scrollIntoView());
    if (SHOTS) await user.screenshot({path: path.join(SHOTS, 'search-all-mobile.png')});

    // ---- عميلٌ ببوابة واحدة: كما كان ----
    await one.goto(APP + '/admin/login');
    await api(one, '/admin/api/login', {user:'one', password:'pw_one'});
    await one.goto(APP + '/admin');
    await one.waitForSelector('input[name="pkg"]', {timeout: 8000});
    check('one gate: no scope switch, the old title', await one.isHidden('#searchScope') && (await one.textContent('#searchTtl')).trim() === 'بحث في البوابة');
    await search(one, 'user002');
    check('one gate: plain results table', !(await one.$('#searchRes .sg')) && (await one.$$('#searchRes button.cb')).length === 1);
  } catch (e) { fail++; console.log('  FAIL  exception:', e.message); }
  finally {
    await browser.close(); f1.kill(); f2.kill(); app.kill();
    fs.rmSync(dataDir, {recursive: true, force: true});
  }
  console.log(`\nResult: ${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();

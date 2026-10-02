// يصوّر قالبًا من tools/store بمقاسه: node tools/store/render.js <القالب.html> <الناتج.jpg|.png> <عرض> <ارتفاع> [استعلام]
// مثال: node tools/store/render.js tools/store/casper-update.html static/img/store/casper-movies.jpg 1000 1000 "kind=movies&n=7,338&…"
let chromium; try { ({ chromium } = require('playwright-core')); } catch (e) { ({ chromium } = require('playwright')); }
const { execSync, execFileSync } = require('child_process');
const path = require('path'); const fs = require('fs');
const EXE = execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim();
const [tpl, out, w, h, query = ''] = process.argv.slice(2);
(async () => {
  const browser = await chromium.launch({executablePath: EXE || undefined, args: ['--no-sandbox', '--allow-file-access-from-files']});
  const page = await browser.newPage({viewport: {width: +w, height: +h}});
  // ما على الشبكة (خطوط jsDelivr) يجلبه curl: يأخذ وكيل البيئة وشهاداتها، والمتصفح لا يأخذهما
  await page.route(/^https:/, route => {
    try { route.fulfill({body: execFileSync('curl', ['-sSfL', route.request().url()])}); }
    catch (e) { route.abort(); }
  });
  await page.goto('file://' + path.resolve(tpl) + (query ? '?' + query : ''));
  await page.evaluate(() => document.fonts.ready);
  const fonts = await page.evaluate(() => [...document.fonts].filter(f => f.status === 'loaded').length);
  if (!fonts) console.warn('تنبيه: لم يُحمَّل خطّ القالب، والصورة بخطٍّ بديل');
  await page.waitForFunction(() => [...document.images].every(i => i.complete));
  const ext = path.extname(out).slice(1).toLowerCase();
  const buf = await page.screenshot({type: ext === 'png' ? 'png' : 'jpeg', quality: ext === 'png' ? undefined : 90});
  fs.mkdirSync(path.dirname(out), {recursive: true});
  fs.writeFileSync(out, buf);
  await browser.close();
  console.log(out, buf.length);
})().catch(e => { console.error(e); process.exit(1); });

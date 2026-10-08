// يصوّر صفحة فيديو من هذا المجلد (0player.html أو duplecast.html) إطارًا إطارًا (30 إطارًا في الثانية)
// ويرمّزه H.264 عموديًّا 720×1280 — يعمل على الآيفون والأندرويد — ثم يلتقط الغلاف (poster).
// الناتج في static/video/ باسمٍ تعرّفه الصفحة (VIDEO.out).
//
//     pip install imageio-ffmpeg        # ffmpeg فيه libx264 و libwebp (أو اضبط FFMPEG)
//     node tools/video/render.js 0player
//     node tools/video/render.js 0player code=75710072      # معاملات للصفحة (?code=…)
//     node tools/video/render.js 0player stills 3 15.5 40   # لقطات ثابتة للمراجعة في مجلد مؤقت
const { chromium } = require('playwright-core');
const { spawn, execSync } = require('child_process');
const fs = require('fs'); const path = require('path'); const os = require('os');

const HERE = __dirname, ROOT = path.resolve(HERE, '..', '..');
const OUT = path.join(ROOT, 'static', 'video');
const FPS = 30;
const EXE = fs.existsSync('/opt/pw-browsers/chromium/chrome-linux/chrome')
  ? '/opt/pw-browsers/chromium/chrome-linux/chrome'
  : execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim() || undefined;
const FFMPEG = process.env.FFMPEG || (() => {
  try { return execSync('python3 -c "import imageio_ffmpeg as f; print(f.get_ffmpeg_exe())"').toString().trim(); }
  catch (e) { return 'ffmpeg'; }
})();
const run = (args, input) => new Promise((ok, no) => {
  const p = spawn(FFMPEG, ['-hide_banner', '-loglevel', 'error', '-y', ...args], { stdio: [input ? 'pipe' : 'ignore', 'inherit', 'inherit'] });
  p.on('close', c => c ? no(new Error('ffmpeg ' + c)) : ok()); if (input) input(p.stdin);
});

(async () => {
  const [name, ...rest] = process.argv.slice(2);
  const page_ = path.join(HERE, (name || '') + '.html');
  if (!name || !fs.existsSync(page_)) { console.error('usage: node tools/video/render.js <0player|duplecast|smarters> [key=value…] [stills t…]'); process.exit(2); }
  const si = rest.indexOf('stills');
  const params = new URLSearchParams(rest.slice(0, si < 0 ? rest.length : si).map(kv => kv.split('=')));
  const times = si < 0 ? null : rest.slice(si + 1);
  const browser = await chromium.launch({ executablePath: EXE, args: ['--no-sandbox', '--force-color-profile=srgb'] });
  const page = await browser.newPage({ viewport: { width: 720, height: 1280 }, deviceScaleFactor: 1 });
  page.on('pageerror', e => { console.error('pageerror', e.message); process.exitCode = 1; });
  await page.goto('file://' + page_ + (params.size ? '?' + params : ''), { waitUntil: 'networkidle' });   // الخط من Google Fonts
  const total = await page.evaluate(() => init());
  const { out, poster } = await page.evaluate(() => ({ out: VIDEO.out, poster: VIDEO.poster ?? 2.6 }));
  const frame = async (t, type) => { await page.evaluate(t => renderAt(t), t); return page.screenshot({ type, quality: type === 'jpeg' ? 93 : undefined }); };

  if (times) {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), out + '-'));
    for (const t of times) fs.writeFileSync(path.join(dir, `still-${t}.png`), await frame(+t, 'png'));
    console.log(`stills in ${dir}`);
  } else {
    fs.mkdirSync(OUT, { recursive: true });
    const N = Math.ceil(total * FPS), mp4 = path.join(OUT, out + '.mp4');
    let feed;
    const done = run(['-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'mjpeg', '-i', '-', '-c:v', 'libx264', '-preset', 'slow',
      '-crf', '26', '-pix_fmt', 'yuv420p', '-profile:v', 'high', '-level', '4.0', '-movflags', '+faststart', mp4], s => { feed = s; });
    for (let f = 0; f < N; f++) {
      const buf = await frame(f / FPS, 'jpeg');
      if (!feed.write(buf)) await new Promise(r => feed.once('drain', r));
      if (f % 300 === 0) console.log(`frame ${f}/${N}`);
    }
    feed.end(); await done;
    // الغلاف: المقدّمة بعد ظهورها كاملة
    const png = path.join(OUT, `.${out}-poster.png`);
    fs.writeFileSync(png, await frame(poster, 'png'));
    await run(['-i', png, '-vf', 'scale=540:960:flags=lanczos', '-c:v', 'libwebp', '-quality', '82', path.join(OUT, out + '.webp')]);
    fs.unlinkSync(png);
    console.log(`✓ ${mp4} (${(fs.statSync(mp4).size / 1e6).toFixed(1)} MB, ${total.toFixed(1)}s) + ${out}.webp`);
  }
  await browser.close();
})();

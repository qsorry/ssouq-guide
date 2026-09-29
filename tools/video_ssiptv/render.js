// يصوّر video.html إطارًا إطارًا (30 إطارًا في الثانية) ويرمّزه H.264 عموديًّا 720×1280
// — يعمل على الآيفون والأندرويد — ثم يلتقط الغلاف (poster). الناتج في static/video/.
//
//     pip install imageio-ffmpeg        # ffmpeg فيه libx264 و libwebp (أو اضبط FFMPEG)
//     node tools/video_ssiptv/render.js
//     node tools/video_ssiptv/render.js stills 3 15.5 40    # لقطات ثابتة للمراجعة في /tmp
const { chromium } = require('playwright-core');
const { spawn, execSync } = require('child_process');
const fs = require('fs'); const path = require('path');

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
  const [mode, ...times] = process.argv.slice(2);
  const browser = await chromium.launch({ executablePath: EXE, args: ['--no-sandbox', '--force-color-profile=srgb'] });
  const page = await browser.newPage({ viewport: { width: 720, height: 1280 }, deviceScaleFactor: 1 });
  page.on('pageerror', e => { console.error('pageerror', e.message); process.exitCode = 1; });
  await page.goto('file://' + path.join(HERE, 'video.html'), { waitUntil: 'networkidle' });   // الخط من Google Fonts
  const total = await page.evaluate(() => init());
  const frame = async (t, type) => { await page.evaluate(t => renderAt(t), t); return page.screenshot({ type, quality: type === 'jpeg' ? 93 : undefined }); };

  if (mode === 'stills') {
    for (const t of times) fs.writeFileSync(`/tmp/ssiptv-still-${t}.png`, await frame(+t, 'png'));
    console.log('stills in /tmp/ssiptv-still-*.png');
  } else {
    fs.mkdirSync(OUT, { recursive: true });
    const N = Math.ceil(total * FPS), mp4 = path.join(OUT, 'ssiptv-ar.mp4');
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
    const png = path.join(OUT, '.poster.png');
    fs.writeFileSync(png, await frame(2.6, 'png'));
    await run(['-i', png, '-vf', 'scale=540:960:flags=lanczos', '-c:v', 'libwebp', '-quality', '82', path.join(OUT, 'ssiptv-ar.webp')]);
    fs.unlinkSync(png);
    console.log(`✓ ${mp4} (${(fs.statSync(mp4).size / 1e6).toFixed(1)} MB, ${total.toFixed(1)}s) + ssiptv-ar.webp`);
  }
  await browser.close();
})();

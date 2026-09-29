// صور الشرح في الدليل (static/img) من صور assets/ نفسها التي يُبنى منها الفيديو: إطار ذهبي (#F0A12B) حول ما
// يُضغط كبقية لقطات الدليل، وبطاقات عربية مرقّمة حيث تفيد. تستعمله shots_0player.js و shots_smarters.js.
//
// كل صورة في SPECS: out (الاسم في static/img)، وsrc (في assets)، وcrop [x,y,w,h] إن لزم، وw (عرض الناتج)،
// وfs (حجم خط البطاقات، بكسل المصدر)، وmarks: r المستطيل، وn الرقم، وt النص، وhot (بطاقة أفتح)، وat مكان البطاقة:
// left | right | top | bottom | below (تحته محاذيًا يمينه) | in (داخله يمينًا) | none (إطار بلا بطاقة)
const { chromium } = require('playwright-core');
const { execSync, execFileSync } = require('child_process');
const fs = require('fs'); const path = require('path'); const os = require('os');

const A = path.join(__dirname, 'assets'), OUT = path.join(__dirname, '..', '..', 'static', 'img');
const EXE = fs.existsSync('/opt/pw-browsers/chromium/chrome-linux/chrome')
  ? '/opt/pw-browsers/chromium/chrome-linux/chrome'
  : execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim() || undefined;
const FFMPEG = process.env.FFMPEG || (() => {
  try { return execSync('python3 -c "import imageio_ffmpeg as f; print(f.get_ffmpeg_exe())"', { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim(); }
  catch (e) { return 'ffmpeg'; }
})();

const page_ = s => {
  const [cx, cy, cw, ch] = s.crop || [0, 0, s.W, s.H], b = Math.max(4, Math.round(cw / 230)), g = Math.round(s.fs * 0.5);
  const marks = s.marks.map(m => {
    const [x, y, w, h] = [m.r[0] - cx, m.r[1] - cy, m.r[2], m.r[3]], pad = Math.round(b * 1.6);
    const frame = `<div class="f" style="left:${x - pad}px;top:${y - pad}px;width:${w + 2 * pad}px;height:${h + 2 * pad}px;border-width:${b}px;border-radius:${b * 3}px"></div>`;
    if (!m.t || m.at === 'none') return frame;
    const pos = { right: `left:${x + w + pad + g}px;top:${y + h / 2}px;transform:translateY(-50%)`,
      left: `right:${cw - x + pad + g}px;top:${y + h / 2}px;transform:translateY(-50%)`,
      top: `left:${x + w / 2}px;top:${y - pad - g}px;transform:translate(-50%,-100%)`,
      bottom: `left:${x + w / 2}px;top:${y + h + pad + g}px;transform:translateX(-50%)`,
      below: `right:${cw - (x + w) - pad}px;top:${y + h + pad + g}px`,
      in: `right:${cw - (x + w) + g}px;top:${y + h / 2}px;transform:translateY(-50%)` }[m.at];
    return frame + `<div class="c${m.hot ? ' hot' : ''}" style="${pos}">${m.n ? `<i>${m.n}</i>` : ''}<span>${m.t}</span></div>`;
  }).join('');
  return `<!doctype html><html dir="rtl"><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@600;700&display=block" rel="stylesheet">
<style>*{margin:0;padding:0;box-sizing:border-box}body{background:#000}
#s{position:relative;width:${cw}px;height:${ch}px;overflow:hidden}
#s img{position:absolute;left:${-cx}px;top:${-cy}px}
.f{position:absolute;border:solid #F0A12B;box-shadow:0 0 ${b * 3}px ${b}px rgba(240,161,43,.45)}
.c{position:absolute;display:flex;align-items:center;gap:${Math.round(s.fs * .35)}px;white-space:nowrap;background:#F0A12B;color:#1b1300;
  font:700 ${s.fs}px/1.25 "IBM Plex Sans Arabic";padding:${Math.round(s.fs * .22)}px ${Math.round(s.fs * .55)}px;border-radius:${s.fs}px;
  box-shadow:0 ${Math.round(s.fs * .12)}px ${Math.round(s.fs * .5)}px rgba(0,0,0,.45)}
.c.hot{background:#FFD24A}
.c i{font-style:normal;display:inline-flex;align-items:center;justify-content:center;width:${Math.round(s.fs * 1.25)}px;height:${Math.round(s.fs * 1.25)}px;
  border-radius:50%;background:#1b1300;color:#F0A12B;font-size:${Math.round(s.fs * .8)}px}
</style></head><body><div id="s"><img src="file://${path.join(A, s.src)}">${marks}</div></body></html>`;
};

async function renderShots(SPECS){
  const browser = await chromium.launch({ executablePath: EXE, args: ['--no-sandbox', '--force-color-profile=srgb'] });
  const page = await browser.newPage();
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'shots-'));
  for (const s of SPECS) {
    const type = s.src.endsWith('.png') ? 'png' : 'webp';
    const [W, H] = await page.evaluate(async src => { const im = new Image(); im.src = src; await im.decode(); return [im.naturalWidth, im.naturalHeight]; },
      `data:image/${type};base64,` + fs.readFileSync(path.join(A, s.src)).toString('base64'));
    Object.assign(s, { W, H });
    const html = path.join(tmp, 'p.html'); fs.writeFileSync(html, page_(s));
    const [cw, ch] = (s.crop || [0, 0, W, H]).slice(2);
    await page.setViewportSize({ width: cw, height: ch });
    await page.goto('file://' + html, { waitUntil: 'networkidle' });
    await page.evaluate(() => document.fonts.ready);
    const png = path.join(tmp, 's.png'); await page.locator('#s').screenshot({ path: png });
    execFileSync(FFMPEG, ['-hide_banner', '-loglevel', 'error', '-y', '-i', png, '-vf', `scale=${s.w}:-2:flags=lanczos`, '-c:v', 'libwebp', '-quality', '80', path.join(OUT, s.out)]);
    console.log(`✓ ${s.out} (${(fs.statSync(path.join(OUT, s.out)).size / 1024).toFixed(0)} KB)`);
  }
  await browser.close();
  fs.rmSync(tmp, { recursive: true, force: true });
}

module.exports = { renderShots };

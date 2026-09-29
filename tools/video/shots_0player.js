// صور شرح 0Player في الدليل (static/img/webos-0player-*.webp) من صور assets/0p_* نفسها التي يُبنى
// منها الفيديو: إطار ذهبي (#F0A12B) حول ما يُضغط كبقية لقطات الدليل، وبطاقات عربية مرقّمة حيث تفيد.
// وما فيه رمز البوابة صورتان باسمه (…-92929480 و …-75710072) فيتبدّل مع اشتراك فالكون تلقائيًّا.
//
//     node tools/video/capture_0player.js    # أولًا، إن تغيّرت الصور
//     node tools/video/shots_0player.js
const { chromium } = require('playwright-core');
const { execSync, execFileSync } = require('child_process');
const fs = require('fs'); const path = require('path'); const os = require('os');

const A = path.join(__dirname, 'assets'), OUT = path.join(__dirname, '..', '..', 'static', 'img');
const CODES = ['92929480', '75710072'];
const EXE = fs.existsSync('/opt/pw-browsers/chromium/chrome-linux/chrome')
  ? '/opt/pw-browsers/chromium/chrome-linux/chrome'
  : execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim() || undefined;
const FFMPEG = process.env.FFMPEG || (() => {
  try { return execSync('python3 -c "import imageio_ffmpeg as f; print(f.get_ffmpeg_exe())"', { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim(); }
  catch (e) { return 'ffmpeg'; }
})();

// مواضع الأزرار (بكسل الصورة) — كما يطبعها capture_0player.js، ومثلها في B بصفحة 0player.html
const TV = { go: [971, 728, 390, 92], playlist: [614, 377, 444, 136], add: [805, 404, 226, 42], reload: [805, 455, 226, 42], first: [49, 80, 300, 78],
  portal: [600, 168, 310, 98], name: [60, 300, 1380, 106], code: [60, 430, 1380, 106], user: [60, 560, 1380, 106], pass: [60, 690, 1380, 106],
  save: [60, 822, 1380, 112], qr: [1545, 470, 330, 330], scan: [1515, 340, 390, 89] };
const WEB = { tab: [378, 274, 294, 114], name: [84, 487, 882, 138], code: [84, 721, 882, 138], user: [84, 955, 882, 138], pass: [84, 1189, 882, 138],
  captcha: [84, 1729, 882, 138], add: [84, 2071, 882, 120], accept: [503, 1729, 535, 144], title: [283, 509, 569, 111] };

// خانات الموقع عنوانها الأزرق فوقها (Name * …): الإطار يضمّه معها
const withLabel = ([x, y, w, h]) => [x, y - 66, w, h + 66];
// صورة: المصدر، وقصّها [x,y,w,h]، وعرض الناتج، وحجم خط البطاقات (بكسل المصدر)، والعلامات:
// r المستطيل، وn الرقم، وt النص، وat مكان البطاقة: left | right | top | bottom | below (تحته محاذيًا يمينه)
// | in (داخله يمينًا) | none (إطار بلا بطاقة)
const SPECS = [
  { out: 'webos-0player-notice.webp', src: '0p_notice.webp', crop: [0, 250, 1920, 700], w: 1280, fs: 46,
    marks: [{ r: TV.go, n: 1, t: 'اضغط «متابعة»', at: 'right' }] },
  { out: 'webos-0player-home.webp', src: '0p_home.webp', w: 1280, fs: 32,
    marks: [{ r: TV.playlist, n: 2, t: 'قائمة التشغيل', at: 'in' }] },
  { out: 'webos-0player-lists.webp', src: '0p_lists.webp', w: 1046, fs: 26,
    marks: [{ r: TV.add, n: 3, t: 'اضغط Add Playlist', at: 'left' }] },
  { out: 'webos-0player-dialog.webp', src: '0p_dialog.webp', w: 1280, fs: 44,
    marks: [{ r: TV.portal, n: 4, t: 'اختر تبويب Portal Code', at: 'right' },
            { r: [60, 300, 1380, 634], t: 'الطريقة الثانية: تكتب هنا بالريموت', at: 'in' },
            { r: [1515, 340, 390, 460], t: 'الطريقة الأولى: امسح بجوالك', at: 'below' }] },
  ...CODES.map(c => ({ out: `webos-0player-portal-${c}.webp`, src: `0p_dialog-${c}.webp`, w: 1280, fs: 44,
    marks: [{ r: TV.portal, n: 1, t: 'اختر تبويب Portal Code', at: 'right' }, { r: TV.name, n: 2, t: 'أي اسم، مثلًا ssouq', at: 'in' },
            { r: TV.code, n: 3, t: `اكتب الكود ${c}`, at: 'in', hot: 1 }, { r: TV.user, n: 4, t: 'اسم المستخدم من رسالة اشتراكك', at: 'in' },
            { r: TV.pass, n: 5, t: 'كلمة المرور من رسالة اشتراكك', at: 'in' }, { r: TV.save, n: 6, t: 'اضغط SAVE للحفظ', at: 'in' }] })),
  ...CODES.map(c => ({ out: `webos-0player-web-${c}.webp`, src: `0p_web-${c}.webp`, w: 740, fs: 46,
    marks: [{ r: WEB.tab, n: 1, t: 'تبويب Portal Code', at: 'top' }, { r: withLabel(WEB.name), n: 2, t: 'أي اسم', at: 'in' },
            { r: withLabel(WEB.code), n: 3, t: `الكود ${c}`, at: 'in', hot: 1 }, { r: withLabel(WEB.user), n: 4, t: 'اسم المستخدم', at: 'in' },
            { r: withLabel(WEB.pass), n: 5, t: 'كلمة المرور', at: 'in' }, { r: WEB.captcha, n: 6, t: 'حروف الصورة', at: 'in' },
            { r: WEB.add, n: 7, t: 'اضغط', at: 'in' }] })),
  { out: 'webos-0player-web-done.webp', src: '0p_done.webp', w: 620, fs: 50,
    marks: [{ r: WEB.title, at: 'none' }] },
  { out: 'webos-0player-reload.webp', src: '0p_lists.webp', w: 1046, fs: 26,
    marks: [{ r: TV.reload, n: 1, t: 'بالباركود؟ اضغط Reload', at: 'left' }, { r: TV.first, n: 2, t: 'ثم اختر قائمتك', at: 'right' }] }
];

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

(async () => {
  const browser = await chromium.launch({ executablePath: EXE, args: ['--no-sandbox', '--force-color-profile=srgb'] });
  const page = await browser.newPage();
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), '0p-shots-'));
  for (const s of SPECS) {
    const [W, H] = await page.evaluate(async src => { const im = new Image(); im.src = src; await im.decode(); return [im.naturalWidth, im.naturalHeight]; },
      'data:image/webp;base64,' + fs.readFileSync(path.join(A, s.src)).toString('base64'));
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
})();

// صور شرح IPTV Smarters Pro على شاشة أندرويد في الدليل (static/img/tv-dl-*.webp و tv-smarters-*.webp، و
// smarters-pro-login.webp لشاشة الدخول وهي نفسها على الجوال) من صور assets/dl_* و assets/sm_* التي يُبنى منها
// الفيديو. وخطوات الموافقة على Downloader واحدة لكل تطبيق يُثبَّت به في الدليل، فصور الكود ونافذتي التثبيت
// بأسماء الأكواد والتطبيقات (…-8744201، …-smarters، …-falcon).
//
//     node tools/video/capture_smarters.js    # أولًا، إن تغيّرت الصور
//     node tools/video/shots_smarters.js
const { renderShots } = require('./shots_lib');

const CODES = ['8744201', '5574841', '1683248', '3638997'];
const APPS = ['smarters', 'mr7', 'falcon', 'casper'];
// مواضع الأزرار (بكسل الصورة) — كما يطبعها capture_smarters.js، ومثلها في B بصفحة smarters.html
const DL = { hash: [1642, 4, 112, 112], ok: [512, 784, 896, 76], title: [1090, 132, 718, 241], install: [1616, 736, 197, 88],
  code: [420, 171, 1080, 119], load: [1352, 348, 159, 80], settings: [1199, 572, 209, 96], row: [1003, 515, 714, 127],
  inst: [1240, 583, 168, 96], open: [1270, 583, 138, 96], build: [1003, 750, 714, 154] };
const SM = { tv: [1260, 649, 300, 80], save: [810, 749, 300, 100], accept: [960, 970, 960, 110], xtream: [550, 600, 820, 100],
  name: [100, 200, 952, 160], user: [100, 380, 952, 160], pass: [100, 560, 952, 160], url: [100, 740, 952, 160], add: [100, 900, 952, 160] };
// نوافذ النظام الصغيرة: النافذة وحدها بهامشٍ يتّسع لبطاقة تحت الزر
const DLG = [424, 278, 1072, 560];
// حقول كل صورة ومواضع البطاقات (at) موصوفة في shots_lib.js
const SPECS = [
  { out: 'tv-dl-play.webp', src: 'dl_play.webp', w: 1280, fs: 44,
    marks: [{ r: DL.title, n: 1, t: 'هذا هو التطبيق', at: 'left' }, { r: DL.install, n: 2, t: 'اضغط «تثبيت»', at: 'left' }] },
  { out: 'tv-dl-welcome.webp', src: 'dl_welcome.webp', w: 1280, fs: 44,
    marks: [{ r: DL.ok, n: 1, t: 'اضغط OK', at: 'bottom' }] },
  ...CODES.map(c => ({ out: `tv-dl-code-${c}.webp`, src: `dl_code-${c}.webp`, w: 1280, fs: 44,
    marks: [{ r: DL.hash, n: 1, t: 'زر #', at: 'left' }, { r: DL.code, n: 2, t: `اكتب ${c}`, at: 'top', hot: 1 },
            { r: DL.load, n: 3, t: 'ثم Load', at: 'bottom' }] })),
  { out: 'tv-dl-blocked.webp', src: 'dl_blocked.webp', crop: DLG, w: 1072, fs: 36,
    marks: [{ r: DL.settings, n: 1, t: 'اضغط «الإعدادات»', at: 'below' }] },
  { out: 'tv-dl-allow.webp', src: 'dl_allow.webp', crop: [940, 80, 900, 700], w: 900, fs: 34,
    marks: [{ r: DL.row, n: 1, t: 'اضغط Downloader فيصير «تطبيق مسموح به»', at: 'below' }] },
  ...APPS.map(a => ({ out: `tv-dl-install-${a}.webp`, src: `dl_install-${a}.webp`, crop: DLG, w: 1072, fs: 36,
    marks: [{ r: DL.inst, n: 1, t: 'اضغط «تثبيت»', at: 'below' }] })),
  ...APPS.map(a => ({ out: `tv-dl-done-${a}.webp`, src: `dl_done-${a}.webp`, crop: DLG, w: 1072, fs: 36,
    marks: [{ r: DL.open, n: 2, t: 'ثم «فتح»', at: 'below' }] })),
  { out: 'tv-dl-devmode.webp', src: 'dl_devmode.webp', crop: [600, 90, 1200, 990], w: 1000, fs: 40,
    marks: [{ r: DL.build, n: 1, t: 'اضغطه 7 مرات', at: 'left' }] },
  { out: 'tv-smarters-device.webp', src: 'sm_device.webp', w: 1280, fs: 44,
    marks: [{ r: SM.tv, n: 1, t: 'اختر TV', at: 'left' }, { r: SM.save, n: 2, t: 'ثم «حفظ»', at: 'left' }] },
  { out: 'tv-smarters-terms.webp', src: 'sm_terms.webp', w: 1280, fs: 44,
    marks: [{ r: SM.accept, n: 1, t: 'اضغط «قبول»', at: 'in' }] },
  { out: 'tv-smarters-route.webp', src: 'sm_route.webp', crop: [460, 150, 1000, 700], w: 1000, fs: 36,
    marks: [{ r: SM.xtream, n: 1, t: 'اختر هذا', at: 'bottom' }] },
  { out: 'smarters-pro-login.webp', src: 'sm_login-fill.webp', w: 1280, fs: 40,
    marks: [{ r: SM.name, n: 1, t: 'أي اسم', at: 'in' }, { r: SM.user, n: 2, t: 'اسم المستخدم', at: 'in' },
            { r: SM.pass, n: 3, t: 'كلمة المرور', at: 'in' }, { r: SM.url, n: 4, t: 'رابط الهوست', at: 'in', hot: 1 },
            { r: SM.add, n: 5, t: 'اضغط', at: 'in' }] }
];

renderShots(SPECS);

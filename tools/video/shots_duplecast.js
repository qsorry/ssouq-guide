// صور شرح Duplecast في الدليل (static/img/webos-duplecast-*.webp) من صور assets/dc_* نفسها التي يُبنى منها
// الفيديو: إطار ذهبي (#F0A12B) حول ما يُضغط كبقية لقطات الدليل، وبطاقات عربية مرقّمة حيث تفيد.
//
//     node tools/video/capture_duplecast.js    # أولًا، إن تغيّرت الصور
//     node tools/video/shots_duplecast.js
const { renderShots } = require('./shots_lib');

// مواضع الأزرار (بكسل الصورة) — كما يطبعها capture_duplecast.js، ومثلها في B بصفحة duplecast.html
const TV = { qr: [1230, 200, 520, 520], mac: [80, 836, 543, 154], refresh: [1596, 70, 104, 104], live: [80, 320, 560, 300] };
const WEB = { add: [697, 981, 398, 111], code: [786, 648, 348, 132], tab: [755, 375, 340, 120],
  name: [75, 885, 1020, 189], host: [75, 1110, 1020, 189], port: [75, 1335, 1020, 189], user: [75, 1560, 1020, 189],
  pass: [75, 1785, 1020, 189], save: [75, 2184, 1020, 138], row: [75, 1061, 1020, 104], ok: [75, 1200, 1020, 123],
  field: [87, 1010, 996, 189], go: [87, 1241, 996, 138], st: [66, 447, 1038, 123] };
// بطاقات الأسعار في قسم Activation من duplecast.com (dc_price)
const PRICE = { free: [15, 119, 357, 313], year: [393, 119, 354, 313] };

// حقول كل صورة ومواضع البطاقات (at) موصوفة في shots_lib.js
const SPECS = [
  { out: 'webos-duplecast-start.webp', src: 'dc_start.webp', w: 1280, fs: 42,
    marks: [{ r: TV.qr, n: 1, t: 'امسح الباركود بكاميرا جوالك', at: 'top' },
            { r: TV.mac, n: 2, t: 'أو رقم جهازك في الموقع', at: 'top' }] },
  { out: 'webos-duplecast-manage.webp', src: 'dc_manage.webp', w: 740, fs: 48,
    marks: [{ r: WEB.add, n: 1, t: 'اضغط Add Playlist', at: 'left' }] },
  { out: 'webos-duplecast-form.webp', src: 'dc_form.webp', w: 740, fs: 46,
    marks: [{ r: WEB.tab, n: 1, t: 'تبويب Xtream Info', at: 'below' }, { r: WEB.name, n: 2, t: 'أي اسم', at: 'in' },
            { r: WEB.host, n: 3, t: 'الهوست بلا البورت', at: 'in', hot: 1 }, { r: WEB.port, n: 4, t: 'رقم البورت وحده', at: 'in', hot: 1 },
            { r: WEB.user, n: 5, t: 'اسم المستخدم', at: 'in' }, { r: WEB.pass, n: 6, t: 'كلمة المرور', at: 'in' },
            { r: WEB.save, n: 7, t: 'اضغط Save', at: 'in' }] },
  { out: 'webos-duplecast-saved.webp', src: 'dc_saved.webp', crop: [0, 630, 1170, 786], w: 740, fs: 46,
    marks: [{ r: WEB.row, t: 'قائمتك باسمها', at: 'top' }, { r: WEB.ok, at: 'none' }] },
  { out: 'webos-duplecast-home.webp', src: 'dc_home.webp', w: 1280, fs: 60,
    marks: [{ r: TV.refresh, n: 1, t: 'اضغط التحديث ↻', at: 'left' }, { r: TV.live, n: 2, t: 'ثم افتح LIVE TV', at: 'bottom' }] },
  { out: 'webos-duplecast-price.webp', src: 'dc_price.webp', w: 900, fs: 30,
    marks: [{ r: PRICE.free, t: '15 يومًا مجانًا', at: 'top' }, { r: PRICE.year, t: 'ثم 3 دولارات للسنة', at: 'top', hot: 1 }] },
  { out: 'webos-duplecast-codebtn.webp', src: 'dc_manage.webp', crop: [0, 0, 1170, 960], w: 740, fs: 46,
    marks: [{ r: WEB.code, n: 1, t: 'اضغط Activate by code', at: 'below' }] },
  { out: 'webos-duplecast-code.webp', src: 'dc_code.webp', crop: [0, 620, 1170, 870], w: 740, fs: 46,
    marks: [{ r: WEB.field, n: 2, t: 'الصق كود التفعيل', at: 'in', hot: 1 }, { r: WEB.go, n: 3, t: 'اضغط Activate', at: 'bottom' }] },
  { out: 'webos-duplecast-active.webp', src: 'dc_active.webp', crop: [0, 180, 1170, 460], w: 740, fs: 46,
    marks: [{ r: WEB.st, at: 'none' }] }
];

renderShots(SPECS);

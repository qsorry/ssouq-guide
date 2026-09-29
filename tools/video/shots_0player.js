// صور شرح 0Player في الدليل (static/img/webos-0player-*.webp) من صور assets/0p_* نفسها التي يُبنى
// منها الفيديو: إطار ذهبي (#F0A12B) حول ما يُضغط كبقية لقطات الدليل، وبطاقات عربية مرقّمة حيث تفيد.
// وما فيه رمز البوابة صورتان باسمه (…-92929480 و …-75710072) فيتبدّل مع اشتراك فالكون تلقائيًّا.
//
//     node tools/video/capture_0player.js    # أولًا، إن تغيّرت الصور
//     node tools/video/shots_0player.js
const { renderShots } = require('./shots_lib');

const CODES = ['92929480', '75710072'];
// مواضع الأزرار (بكسل الصورة) — كما يطبعها capture_0player.js، ومثلها في B بصفحة 0player.html
const TV = { go: [971, 728, 390, 92], playlist: [614, 377, 444, 136], add: [805, 404, 226, 42], reload: [805, 455, 226, 42], first: [49, 80, 300, 78],
  portal: [600, 168, 310, 98], name: [60, 300, 1380, 106], code: [60, 430, 1380, 106], user: [60, 560, 1380, 106], pass: [60, 690, 1380, 106],
  save: [60, 822, 1380, 112], qr: [1545, 470, 330, 330], scan: [1515, 340, 390, 89] };
const WEB = { tab: [378, 274, 294, 114], name: [84, 487, 882, 138], code: [84, 721, 882, 138], user: [84, 955, 882, 138], pass: [84, 1189, 882, 138],
  captcha: [84, 1729, 882, 138], add: [84, 2071, 882, 120], accept: [503, 1729, 535, 144], title: [283, 509, 569, 111] };

// خانات الموقع عنوانها الأزرق فوقها (Name * …): الإطار يضمّه معها
const withLabel = ([x, y, w, h]) => [x, y - 66, w, h + 66];
// حقول كل صورة ومواضع البطاقات (at) موصوفة في shots_lib.js
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

renderShots(SPECS);

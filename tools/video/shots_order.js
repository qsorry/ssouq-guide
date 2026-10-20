// صورة «بيانات اشتراكك في طلبك» (static/img/order-digital.webp) التي يُحال إليها من كل خطوة تُكتب فيها البيانات:
// بطاقة «بيانات الدخول» في صفحة الطلب بالمتجر الجديد (ssouq.com، مستودع ssouq-store:
// CredentialsCard و CredentialRows) بثيمه الحيّ «سمارت سوق V1» الداكن، والبيانات مثال (http://mrha.ink و user123
// و pass456)، مع إطار ذهبي على صف الهوست. المصدر assets/order_store.webp: البطاقة بأصنافها وCSS الموقع الحيّ
// مصوّرة بعرض 390 × 3.
//
//     node tools/video/shots_order.js
const { renderShots } = require('./shots_lib');

const ROW = { host: [99, 339, 972, 174] };

renderShots([
  { out: 'order-digital.webp', src: 'order_store.webp', w: 740, fs: 46,
    marks: [{ r: ROW.host, n: 1, t: 'هنا رابط الهوست الذي وصلك', at: 'top', hot: 1 }] },
]);

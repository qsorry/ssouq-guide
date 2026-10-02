/* كود «JS مخصص» لثيم المتجر (رائد): عرض كود الخصم NEW30.
   يُلصق كاملًا مكان القديم في: لوحة سلة ← التصميم ← تخصيص الثيم «ترقية إلى ثيم رائد» ← JS مخصص.
   - في كل الصفحات: زرّ عائم صغير يفتح نافذة الكود، والنافذة تظهر وحدها للزائر نفسه مرة كل 3 أيام.
   - في السلة: لا زرّ عائم ولا نافذة. كانا يغطّيان شريط الإجمالي أسفل شاشة الجوال (المبلغ و«وفرت»
     وزرّ «إتمام الطلب»)؛ بدلهما سطرٌ ثابت فوق «لديك كوبون خصم؟» زرّه يكتب الكود ويطبّقه،
     ويختفي متى طُبّق كوبون. */
(function () {
  var CODE = 'NEW30';                  // اسم الكود كما أنشأته في سلة
  var TITLE = 'خصم 30% على باقات اشتراك سمارت';
  var NOTE = 'لأول طلب: انسخ الكود واكتبه في «لديك كوبون خصم؟» داخل سلة المشتريات';
  var LINK = '/smart-iptv/brand-194365739'; // صفحة باقات سمارت فقط
  var LINK_TEXT = 'تصفّح باقات سمارت ←';
  var DAYS = 3;                        // النافذة تظهر للزائر نفسه مرة كل 3 أيام
  var KEY = 'ssq_promo_seen';

  function seen() { try { return Date.now() - (+localStorage.getItem(KEY) || 0) < DAYS * 864e5; } catch (e) { return false; } }
  function mark() { try { localStorage.setItem(KEY, String(Date.now())); } catch (e) {} }
  // السلة (والدفع إن حمل الكود): أسفل الشاشة فيها شريط الإجمالي و«إتمام الطلب»
  function inCart() { return /(^|\s)cart(\s|$)/.test(document.body.className) || /\/(cart|checkout)(\/|$)/.test(location.pathname); }

  function copy(btn) {
    function done() { btn.textContent = 'تم النسخ ✓'; setTimeout(function () { btn.textContent = 'نسخ الكود'; }, 2000); }
    function fallback() {
      var t = document.createElement('textarea');
      t.value = CODE; t.setAttribute('readonly', ''); t.style.position = 'fixed'; t.style.opacity = '0';
      document.body.appendChild(t); t.select();
      try { document.execCommand('copy'); done(); } catch (e) {}
      document.body.removeChild(t);
    }
    if (navigator.clipboard && window.isSecureContext) { navigator.clipboard.writeText(CODE).then(done, fallback); } else { fallback(); }
  }

  var CSS =
    '#ssq-promo{position:fixed;inset:0;background:rgba(0,0,0,.55);display:none;align-items:center;justify-content:center;z-index:99999;padding:16px}' +
    '#ssq-promo.ssq-open{display:flex}' +
    '#ssq-promo .ssq-box{position:relative;background:#fff;color:#1f2937;border-radius:16px;padding:28px 22px 22px;width:100%;max-width:360px;text-align:center;direction:rtl;font-family:inherit;box-shadow:0 20px 50px rgba(0,0,0,.3)}' +
    '#ssq-promo .ssq-x{position:absolute;top:8px;left:10px;background:none;border:0;font-size:26px;line-height:1;color:#6b7280;cursor:pointer}' +
    '#ssq-promo h3{margin:0 0 6px;font-size:22px;font-weight:800;color:#111827!important}' +
    '#ssq-promo p{margin:0 0 16px;font-size:14px;color:#4b5563}' +
    '#ssq-promo .ssq-code{border:2px dashed #21636d;border-radius:10px;padding:12px;font-size:26px;font-weight:800;letter-spacing:3px;direction:ltr;margin-bottom:14px;user-select:all;color:#111827}' +
    '#ssq-promo .ssq-copy{width:100%;border:0;border-radius:10px;padding:13px;font-size:16px;font-weight:700;color:#fff;background:#21636d;cursor:pointer;font-family:inherit}' +
    '#ssq-promo .ssq-link{display:block;margin-top:10px;border:2px solid #21636d;border-radius:10px;padding:11px;font-size:15px;font-weight:700;color:#21636d;text-decoration:none;font-family:inherit}' +
    // الزرّ العائم: داكنٌ بحدٍّ سماوي ونصٍّ ذهبي كبقية المتجر (كان نصًّا فاتحًا على خلفيةٍ فاتحة)
    '#ssq-badge{position:fixed;bottom:90px;left:12px;z-index:9999;display:flex;align-items:center;gap:6px;border:1px solid rgba(127,220,248,.42);border-radius:999px;padding:7px 12px;font-size:13px;line-height:1.4;font-weight:700;color:#F1F8FB;background:#0A2735;box-shadow:0 6px 18px rgba(0,0,0,.35);cursor:pointer;font-family:inherit;direction:rtl}' +
    '#ssq-badge b{color:#E9B44C!important}' +
    // سطر الكود في السلة، فوق «لديك كوبون خصم؟» وفي بطاقتها
    '#ssq-cart-code{display:flex;align-items:center;gap:12px;margin:20px 0 4px;padding:12px 14px;border:1.5px dashed #E9B44C;border-radius:12px;background:rgba(233,180,76,.08);direction:rtl;font-family:inherit}' +
    '#ssq-cart-code .ssq-t{flex:1;min-width:0;font-size:14px;line-height:1.6;font-weight:700;color:#F1F8FB}' +
    '#ssq-cart-code .ssq-t small{display:block;font-size:12.5px;font-weight:500;color:#A9C7D6}' +
    '#ssq-cart-code .ssq-t bdi{color:#E9B44C;letter-spacing:1px}' +
    '#ssq-cart-code button{flex:none;border:0;border-radius:10px;padding:10px 14px;font-size:14px;font-weight:700;color:#10202b;background:#E9B44C;cursor:pointer;font-family:inherit;white-space:nowrap}' +
    '#ssq-cart-code[hidden]{display:none}';

  function popup() {
    var o = document.createElement('div');
    o.id = 'ssq-promo';
    o.innerHTML =
      '<div class="ssq-box" role="dialog" aria-modal="true" aria-label="' + TITLE + '">' +
      '<button type="button" class="ssq-x" aria-label="إغلاق">&times;</button>' +
      '<h3>🎁 ' + TITLE + '</h3><p>' + NOTE + '</p>' +
      '<div class="ssq-code">' + CODE + '</div>' +
      '<button type="button" class="ssq-copy">نسخ الكود</button>' +
      '<a class="ssq-link" href="' + LINK + '">' + LINK_TEXT + '</a></div>';
    document.body.appendChild(o);

    var b = document.createElement('button');
    b.id = 'ssq-badge'; b.type = 'button'; b.setAttribute('aria-label', TITLE);
    b.innerHTML = '🎁 خصم <b>30%</b> على سمارت';
    document.body.appendChild(b);

    function open() { o.classList.add('ssq-open'); mark(); }
    function close() { o.classList.remove('ssq-open'); }
    o.addEventListener('click', function (e) { if (e.target === o) close(); });
    o.querySelector('.ssq-x').addEventListener('click', close);
    o.querySelector('.ssq-copy').addEventListener('click', function () { copy(this); });
    b.addEventListener('click', open);
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });

    if (!seen()) setTimeout(open, 4000);
  }

  // salla-cart-coupons يُرسم بعد تحميل الصفحة، فننتظر حقله ثم نضع السطر فوقه
  function cartCode(tries) {
    var box = document.querySelector('salla-cart-coupons');
    var input = box && box.querySelector('input[name="coupon"]');
    if (!input) { if (tries < 40) setTimeout(function () { cartCode(tries + 1); }, 500); return; }
    if (document.getElementById('ssq-cart-code')) return;

    var row = document.createElement('div');
    row.id = 'ssq-cart-code';
    row.innerHTML =
      '<span class="ssq-t">🎁 خصم 30% على باقات سمارت<small>لأول طلب بالكود <bdi dir="ltr">' + CODE + '</bdi></small></span>' +
      '<button type="button">استخدم الكود</button>';
    box.parentNode.insertBefore(row, box);

    row.querySelector('button').addEventListener('click', function () {
      var i = box.querySelector('input[name="coupon"]');
      var apply = box.querySelector('.s-cart-coupons-coupon-button-apply button, button.s-cart-coupons-coupon-button-apply');
      if (!i) return;
      i.value = CODE;
      i.dispatchEvent(new Event('input', { bubbles: true }));
      i.dispatchEvent(new Event('change', { bubbles: true }));
      if (apply) apply.click(); else i.focus();
    });

    // كوبونٌ مطبّق (الحقل مقفل أو ظهر زرّ الإزالة): لا حاجة للسطر
    function sync() {
      var i = box.querySelector('input[name="coupon"]');
      row.hidden = !i || i.disabled || i.readOnly || !!box.querySelector('[class*="coupon-button-remove"]');
    }
    sync();
    if (window.MutationObserver) new MutationObserver(sync).observe(box, { subtree: true, childList: true, attributes: true });
  }

  function init() {
    if (document.getElementById('ssq-promo') || document.getElementById('ssq-cart-code')) return;
    var s = document.createElement('style');
    s.textContent = CSS;
    document.head.appendChild(s);
    if (inCart()) cartCode(0); else popup();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();

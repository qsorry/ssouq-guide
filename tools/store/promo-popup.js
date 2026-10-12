(function () {
  var CODE = 'NEW30';                  // اسم الكود كما أنشأته في سلة
  var TITLE = 'خصم 30% على باقات اشتراك سمارت';
  var NOTE = 'لأول طلب: انسخ الكود واكتبه في "عندك كوبون خصم؟" بصفحة الدفع';
  var LINK = '/smart-iptv/brand-194365739'; // صفحة باقات سمارت فقط
  var LINK_TEXT = 'تصفّح باقات سمارت ←';
  var DAYS = 3;                        // النافذة تظهر للزائر نفسه مرة كل 3 أيام، والزر العائم يبقى في كل الصفحات
  var KEY = 'ssq_promo_seen';

  function seen() { try { return Date.now() - (+localStorage.getItem(KEY) || 0) < DAYS * 864e5; } catch (e) { return false; } }
  function mark() { try { localStorage.setItem(KEY, String(Date.now())); } catch (e) {} }

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

  function init() {
    if (document.getElementById('ssq-promo')) return;
    /* ألوان الثيم (متغيّرات --ssq-* من CSS المتجر) وبدائلها إن غابت */
    var T = {
      surface: 'var(--ssq-surface,#103546)', surface2: 'var(--ssq-surface-2,#143E50)',
      border: 'var(--ssq-border,rgba(127,220,248,.16))', borderHover: 'var(--ssq-border-hover,rgba(127,220,248,.42))',
      text: 'var(--ssq-text,#F1F8FB)', muted: 'var(--ssq-muted,#A9C7D6)',
      cyan: 'var(--ssq-cyan,#4FC3E8)', cyanLight: 'var(--ssq-cyan-light,#7FDCF8)', gold: 'var(--ssq-gold,#E9B44C)',
      btn: 'linear-gradient(135deg,#0A6E9E,#087EA9)'
    };
    var s = document.createElement('style');
    s.textContent =
      '#ssq-promo{position:fixed;inset:0;background:rgba(4,18,26,.72);-webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px);display:none;align-items:center;justify-content:center;z-index:99999;padding:16px}' +
      '#ssq-promo.ssq-open{display:flex;animation:ssqPromoFade .25s ease both}' +
      '#ssq-promo .ssq-box{position:relative;overflow:hidden;background:linear-gradient(145deg,' + T.surface2 + ',' + T.surface + ');color:' + T.text + ';border:1px solid ' + T.border + ';border-radius:22px;padding:30px 22px 22px;width:100%;max-width:380px;text-align:center;direction:rtl;font-family:inherit;box-shadow:0 22px 60px rgba(0,0,0,.45);animation:ssqPromoRise .3s ease both}' +
      '#ssq-promo .ssq-box::before{content:"";position:absolute;top:0;right:0;left:0;height:3px;background:linear-gradient(90deg,' + T.cyan + ',' + T.gold + ')}' +
      '#ssq-promo .ssq-x{position:absolute;top:10px;left:10px;width:32px;height:32px;display:grid;place-items:center;background:' + T.surface + ';border:1px solid ' + T.border + ';border-radius:50%;font-size:20px;line-height:1;color:' + T.muted + ';cursor:pointer;padding:0;transition:border-color .2s ease,color .2s ease}' +
      '#ssq-promo .ssq-x:hover{border-color:' + T.borderHover + ';color:' + T.text + '}' +
      '#ssq-promo h3{margin:0 0 8px;font-size:21px;font-weight:900;line-height:1.5;letter-spacing:-.3px;color:' + T.text + '!important}' +
      '#ssq-promo p{margin:0 0 18px;font-size:14px;line-height:1.8;color:' + T.muted + '!important}' +
      '#ssq-promo .ssq-code{background:rgba(8,31,42,.55);border:1.5px dashed ' + T.gold + ';border-radius:14px;padding:12px;font-size:26px;font-weight:900;letter-spacing:4px;direction:ltr;margin-bottom:14px;color:' + T.cyanLight + ';user-select:all}' +
      '#ssq-promo .ssq-copy{width:100%;min-height:46px;border:1px solid rgba(127,220,248,.18);border-radius:12px;padding:0 14px;font-size:15px;font-weight:800;color:#fff;background:' + T.btn + ';box-shadow:0 7px 18px rgba(0,0,0,.18);cursor:pointer;font-family:inherit;transition:transform .22s ease,box-shadow .22s ease,filter .22s ease}' +
      '#ssq-promo .ssq-copy:hover{transform:translateY(-2px);box-shadow:0 12px 25px rgba(0,0,0,.28);filter:brightness(1.07)}' +
      '#ssq-promo .ssq-link{display:flex;align-items:center;justify-content:center;min-height:46px;margin-top:10px;background:' + T.surface + ';border:1px solid ' + T.cyan + ';border-radius:12px;padding:0 14px;font-size:14px;font-weight:800;color:' + T.cyanLight + '!important;text-decoration:none;font-family:inherit;transition:transform .22s ease,background .22s ease}' +
      '#ssq-promo .ssq-link:hover{transform:translateY(-2px);background:' + T.surface2 + '}' +
      '#ssq-badge{position:fixed;bottom:90px;left:16px;z-index:9999;min-height:42px;border:1px solid rgba(127,220,248,.18);border-radius:999px;padding:0 16px;font-size:14px;font-weight:800;color:#fff;background:' + T.btn + ';box-shadow:0 8px 22px rgba(0,0,0,.3);cursor:pointer;font-family:inherit;direction:rtl;transition:transform .22s ease,box-shadow .22s ease}' +
      '#ssq-badge:hover{transform:translateY(-2px);box-shadow:0 12px 28px rgba(0,0,0,.4)}' +
      '@keyframes ssqPromoFade{from{opacity:0}to{opacity:1}}' +
      '@keyframes ssqPromoRise{from{opacity:0;transform:translateY(18px)}to{opacity:1;transform:none}}' +
      '@media(prefers-reduced-motion:reduce){#ssq-promo.ssq-open,#ssq-promo .ssq-box{animation:none}}';
    document.head.appendChild(s);

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
    b.id = 'ssq-badge'; b.type = 'button'; b.textContent = '🎁 خصم 30% على سمارت';
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

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();

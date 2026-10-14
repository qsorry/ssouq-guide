/* زرّ «محتار ايش تشاهد؟» العائم على صفحات الموقع العامة → جولة الاقتراح (/content/for-you/). لا يظهر في الإطارات ولا في صفحة الجولة نفسها ولا في الإدارة.
   أنماطه في static/ux.css (‏.floating-choice-btn). يُستدعى ‏fyEnsure من التنقّل السلس (softnav.js) بعد كل تبديلٍ فيُنشأ الزرّ أو يُخفى أو تُحدَّث لغته. */
(function () {
  try { if (window.top !== window) return; } catch (e) { return; }
  function off(p) { return /\/content\/for-you\//.test(p) || /^\/(admin|api|static)\b/.test(p); }
  function ensure() {
    var p = location.pathname, hide = off(p), en = (document.documentElement.lang || "ar") === "en", a = document.getElementById("fyFab");
    document.documentElement.classList.toggle("has-fab", !hide);       // فراغٌ أسفل الصفحة فلا يغطّي الزرّ آخر المحتوى
    if (!a) {
      if (hide || !document.body) return;
      a = document.createElement("a");
      a.id = "fyFab"; a.className = "floating-choice-btn";
      a.addEventListener("click", function () { if (window.sq) window.sq("fy_click", location.pathname.slice(0, 60)); });
      document.body.appendChild(a);
    }
    a.hidden = hide;
    a.href = (en ? "/en" : "") + "/content/for-you/";
    a.textContent = en ? "Not sure what to watch?" : "محتار ايش تشاهد؟";
  }
  window.fyEnsure = ensure;
  if (document.body) ensure(); else document.addEventListener("DOMContentLoaded", ensure);
})();

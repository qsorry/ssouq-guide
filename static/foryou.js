/* زرّ «محتار ايش تشاهد؟» العائم على صفحات الموقع العامة → جولة الاقتراح (/content/for-you/). لا يظهر في الإطارات ولا في صفحة الجولة نفسها. */
(function () {
  try { if (window.top !== window) return; } catch (e) { return; }
  var p = location.pathname;
  if (/\/content\/for-you\//.test(p) || /^\/(admin|api|static)\b/.test(p)) return;
  var en = (document.documentElement.lang || "ar") === "en";
  function add() {
    if (document.getElementById("fyFab")) return;
    var a = document.createElement("a");
    a.id = "fyFab"; a.href = (en ? "/en" : "") + "/content/for-you/";
    a.textContent = en ? "Not sure what to watch?" : "محتار ايش تشاهد؟";
    a.setAttribute("style", "position:fixed;inset-block-end:16px;inset-inline-start:16px;z-index:60;padding:11px 18px;border-radius:999px;background:linear-gradient(135deg,#2f8cff,#8b7cf6);color:#fff;font:700 .92rem/1.2 system-ui,Tahoma,sans-serif;text-decoration:none;box-shadow:0 10px 28px -10px rgba(47,140,255,.8)");
    document.body.appendChild(a);
  }
  if (document.body) add(); else document.addEventListener("DOMContentLoaded", add);
})();

/* sq.js — عدّاد دليل سمارت سوق (analytics.py): بلا كوكيز ولا بياناتٍ شخصية، يرسل إلى /api/hit.
   - المشاهدة ومُحيلها وحملتها ومنطقة الجهاز الزمنية (للدولة) حين تظهر الصفحة فعلًا (لا في التحميل المسبق).
   - مدة القراءة: ما ظهرت فيه الصفحة، على دفعات كلما اختفت (أولها يُعدّ للمشاهدة).
   - النقرات: المتجر (برقم المنتج) · واتساب (قناة/محادثة/مشاركة) · الروابط الخارجية · الاتصال · المشاركة.
   - sq("اسم", "وصف") لما تريده الصفحة نفسها (خطوات المعالج، توليد M3U، البحث)، ويُرسل مثله إلى GA4/GTM إن رُبطا.
   - ?sq=off يستثني هذا المتصفح (يُحفظ)، و?sq=on يعيده. ES5 عمدًا: متصفحات الشاشات قديمة. */
(function () {
  var w = window, d = document, n = navigator, L = location;
  if (w.sqReady) return;
  w.sqReady = true;
  var queued = (w.sq && w.sq.q) || [];
  var off = !!w.sqOff;
  try {
    var m = /[?&]sq=(off|on)\b/.exec(L.search);
    if (m) {
      if (m[1] === "off") localStorage.setItem("sq_off", "1"); else localStorage.removeItem("sq_off");
      off = m[1] === "off";
    }
  } catch (e) {}

  function send(o) {
    if (off) return;
    o.p = o.p || L.pathname;
    var b = JSON.stringify(o);
    try { if (n.sendBeacon && n.sendBeacon("/api/hit", b)) return; } catch (e) {}
    try {
      if (w.fetch) { w.fetch("/api/hit", {method: "POST", body: b, keepalive: true})["catch"](function () {}); return; }
      var x = new XMLHttpRequest(); x.open("POST", "/api/hit", true); x.send(b);
    } catch (e) {}
  }

  function track(name, label) {
    name = String(name || "");
    if (!/^[a-z][a-z0-9_]{1,31}$/.test(name)) return;
    var l = label == null ? "" : String(label).slice(0, 80);
    send({t: "ev", n: name, l: l});
    if (off) return;
    try { if (typeof w.gtag === "function") w.gtag("event", name, l ? {label: l} : {}); } catch (e) {}
    try { if (w.SQ_GTM && w.dataLayer) w.dataLayer.push({event: name, event_label: l}); } catch (e) {}
  }

  function tz() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch (e) { return ""; }
  }

  // ----- المشاهدة: حين تظهر الصفحة للزائر (Chrome يحمّل بعض الصفحات مسبقًا قبل أن تُفتح) -----
  function pageview() {
    send({t: "pv", r: d.referrer || "", q: L.search || "", tz: tz(), tp: n.maxTouchPoints || 0});
  }
  if (d.prerendering) d.addEventListener("prerenderingchange", pageview, {once: true});
  else pageview();

  // ----- مدة القراءة: وقت ظهور الصفحة، يُرسل ما تجمّع كلما اختفت أو غادرها الزائر إلى موقعٍ آخر (فمغادرة
  //       موقعٍ إلى موقع قد لا يُطلق فيها المتصفح pagehide) — وما دامت ظاهرةً يستمرّ العدّ -----
  var shown = d.visibilityState === "visible" ? +new Date() : 0, acc = 0, first = 1;
  function flush() {
    var now = +new Date();
    if (shown) { acc += now - shown; shown = d.visibilityState === "visible" ? now : 0; }
    var s = Math.round(acc / 1000);
    if (s >= 1) { send({t: "end", d: Math.min(s, 1800), f: first}); first = 0; acc = 0; }
  }
  d.addEventListener("visibilitychange", function () {
    if (d.visibilityState === "hidden") flush();
    else if (!shown) shown = +new Date();
  });
  w.addEventListener("pagehide", flush);

  // ----- النقرات: تُلتقط من المستند كله، فلا تحتاج الصفحات سطرًا لكل رابط -----
  function closestLink(el) {
    while (el && el !== d) {
      if (el.tagName === "A" && el.getAttribute("href")) return el;
      el = el.parentNode;
    }
    return null;
  }
  d.addEventListener("click", function (e) {
    var a = closestLink(e.target);
    if (!a) return;
    var href = a.href || "", proto = (/^([a-z][a-z0-9+.\-]*):/i.exec(href) || [])[1] || "";
    proto = proto.toLowerCase();
    if (proto === "tel") return track("call_click", href.slice(4, 24));
    if (proto !== "http" && proto !== "https") return;
    var h = (/^https?:\/\/([^\/?#:]+)/i.exec(href) || [])[1] || "";
    h = h.toLowerCase();
    var path = (/^https?:\/\/[^\/?#]+([^?#]*)/i.exec(href) || [])[1] || "/";
    if (h === L.hostname.toLowerCase()) return;
    if (/(^|\.)wa\.me$|(^|\.)whatsapp\.com$/.test(h)) {
      var kind = /\/channel\//.test(path) ? "channel"
        : /\d{6,}/.test(path) || /[?&]phone=\d/.test(href) || !/[?&]text=/.test(href) ? "chat" : "share";
      track("whatsapp_click", kind);
    } else if (/(^|\.)ssouq\.com$/.test(h) && !/^admin\./.test(h)) {
      var pm = /\/(p\d{5,})(?:\/|$)/.exec(path);
      var lbl = pm ? pm[1] : path;
      try { if (!pm) lbl = decodeURIComponent(path); } catch (er) {}
      track("store_click", lbl.slice(0, 60));
    } else track("outbound", h);
    flush();
  }, true);

  // ----- المشاركة الأصلية في الجوال (واتساب وسناب…) -----
  try {
    if (n.share) {
      var share0 = n.share;
      n.share = function (data) {
        var u = (data && data.url) || L.href, p = (/^https?:\/\/[^\/?#]+([^?#]*)/i.exec(u) || [])[1] || L.pathname;
        track("share", p);
        return share0.apply(n, arguments);
      };
    }
  } catch (e) {}

  w.sq = track;
  for (var i = 0; i < queued.length; i++) {
    try { track.apply(null, queued[i]); } catch (e) {}
  }
})();

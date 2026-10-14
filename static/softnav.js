/* softnav.js — تنقّلٌ بلا إعادة تحميل الصفحة داخل /content و/en/content (تحسينٌ تدريجي فوق صفحات الخادم الحقيقية).
   - الروابط تبقى روابطَ حقيقية (للزواحف وللنقر بالزر الأوسط وللمتصفحات القديمة)؛ هنا تُلتقط النقرة فقط فتُجلب الصفحة وتُبدَّل محتوياتها.
   - يُجلب مسبقًا ما يوشك الزائر على فتحه (مرور المؤشر/لمسةٌ أولى) فيبدو التنقّل فوريًا.
   - قالب الصفحة الهدف قد يختلف (الدليل والكيانات): تُبدَّل أنماطه مع المحتوى. وإن فشل الجلب أو لم يكن HTML ← تنقّلٌ عاديٌّ كاملًا، فلا يظهر شيءٌ مكسور.
   - الإحصائيات: تُرسَل مشاهدةٌ جديدة لكل تنقّل (sqNav من sq.js) بمُحيلٍ داخلي، فلا تُعدّ دخولًا من الخارج.
   - ES5 عمدًا (متصفحات الشاشات قديمة) وبكشفٍ للميزات: بلا fetch/history/DOMParser لا يفعل شيئًا. */
(function () {
  var w = window, d = document, L = location;
  if (w.sqSoft || !w.fetch || !w.history || !history.pushState || !w.DOMParser || !w.Promise || !w.URL) return;
  try { if (w.top !== w) return; } catch (e) { return; }
  var SCOPE = /^\/(en\/)?content(\/|$)/;
  if (!SCOPE.test(L.pathname)) return;
  var cache = {}, order = [], MAX = 24, TTL = 60000, busy = 0, bar = null, tm = 0;
  w.sqSoft = {cleanups: (w.__snClean = w.__snClean || [])};
  try { if ("scrollRestoration" in history) history.scrollRestoration = "manual"; } catch (e) {}
  history.replaceState({sn: 1, y: w.pageYOffset || 0}, "", L.href);

  var here = L.pathname + L.search;
  function styleSig(doc) {     // بصمة الأنماط: صفحات المحتوى من قالبين (الدليل والكيانات) فتُبدَّل الأنماط حين تختلف
    var s = "", n = doc.querySelectorAll("style,link[rel=stylesheet]"), i;
    for (i = 0; i < n.length; i++) s += n[i].tagName === "STYLE" ? n[i].textContent.length + ":" + n[i].textContent.slice(0, 80) + "|" : n[i].getAttribute("href") + "|";
    return s;
  }
  var mySig = styleSig(d);
  function swapStyles(doc) {
    var i, old = d.head.querySelectorAll("style"), nw = doc.head.querySelectorAll("style"), links = d.head.querySelectorAll("link[rel=stylesheet]"), have = {}, want = {};
    for (i = 0; i < old.length; i++) old[i].parentNode.removeChild(old[i]);
    for (i = 0; i < nw.length; i++) d.head.appendChild(d.importNode(nw[i], true));
    for (i = 0; i < links.length; i++) have[links[i].getAttribute("href")] = links[i];
    nw = doc.head.querySelectorAll("link[rel=stylesheet]");
    for (i = 0; i < nw.length; i++) { want[nw[i].getAttribute("href")] = 1; if (!have[nw[i].getAttribute("href")]) d.head.appendChild(d.importNode(nw[i], true)); }
    for (i in have) if (!want[i] && have[i].parentNode) have[i].parentNode.removeChild(have[i]);
  }

  function eligible(a) {
    if (!a || !a.href || a.target && a.target !== "_self" || a.hasAttribute("download") || a.hasAttribute("data-hard")) return false;
    if (a.origin !== L.origin || !SCOPE.test(a.pathname)) return false;
    if (a.pathname === L.pathname && a.search === L.search) return false;       // نفس الصفحة (أو مرساة): للمتصفح
    return true;
  }
  function plain(e) { return e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey && !e.defaultPrevented; }

  function get(url) {
    var c = cache[url], now = +new Date();
    if (c && now - c.t < TTL) return c.p;
    var p = fetch(url, {credentials: "same-origin", headers: {"Accept": "text/html"}}).then(function (r) {
      var ct = r.headers.get("Content-Type") || "";
      if (!r.ok || ct.indexOf("text/html") < 0) throw new Error("no");
      return r.text().then(function (t) { return {url: r.url, html: t}; });
    });
    cache[url] = {t: now, p: p};
    order.push(url);
    if (order.length > MAX) delete cache[order.shift()];
    p["catch"](function () { delete cache[url]; });
    return p;
  }

  function progress(on) {
    if (on) {
      if (!bar) {
        bar = d.createElement("div");
        bar.setAttribute("aria-hidden", "true");
        bar.style.cssText = "position:fixed;inset-block-start:0;inset-inline-start:0;height:3px;width:0;z-index:99;background:linear-gradient(90deg,#2f8cff,#8b7cf6);transition:width .4s ease,opacity .25s;pointer-events:none";
        d.body.appendChild(bar);
      }
      bar.style.opacity = "1"; bar.style.width = "35%";
      clearTimeout(tm); tm = setTimeout(function () { if (bar) bar.style.width = "70%"; }, 400);
    } else if (bar) {
      clearTimeout(tm); bar.style.width = "100%";
      var b = bar; bar = null;
      setTimeout(function () { b.style.opacity = "0"; }, 120);
      setTimeout(function () { if (b.parentNode) b.parentNode.removeChild(b); }, 450);
    }
  }

  var HEAD_SEL = 'title,meta[name=description],meta[name=robots],meta[property^="og:"],meta[name^="twitter:"],link[rel=canonical],link[rel=alternate],link[rel=prev],link[rel=next],script[type="application/ld+json"]';
  function swapHead(doc) {
    var old = d.head.querySelectorAll(HEAD_SEL), i;
    for (i = 0; i < old.length; i++) old[i].parentNode.removeChild(old[i]);
    var nw = doc.head.querySelectorAll(HEAD_SEL);
    for (i = 0; i < nw.length; i++) d.head.appendChild(d.importNode(nw[i], true));
  }
  function runScripts(root) {      // السكربتات المضمّنة في الجسم الجديد (innerHTML/importNode لا تشغّلها)
    var s = root.querySelectorAll("script"), i, x, n;
    for (i = 0; i < s.length; i++) {
      var t = s[i].getAttribute("type");
      if (t && t !== "text/javascript") continue;
      x = d.createElement("script");
      if (s[i].src) x.src = s[i].src; else x.text = s[i].textContent;
      n = s[i];
      n.parentNode.replaceChild(x, n);
    }
  }
  function cleanup() {
    var c = w.__snClean || [], i;
    w.__snClean = w.sqSoft.cleanups = [];
    for (i = 0; i < c.length; i++) { try { c[i](); } catch (e) {} }
    d.body.style.overflow = "";
  }

  function apply(res, url, push, y) {
    var doc = new DOMParser().parseFromString(res.html, "text/html");
    if (!doc.body || !doc.head) return false;
    var finalUrl = res.url || url;
    var prev = L.href;
    try { if (w.sqNav) w.sqNav.before(); } catch (e) {}
    var go = function () {
      cleanup();
      if (push) { history.replaceState({sn: 1, y: w.pageYOffset || 0}, "", prev); history.pushState({sn: 1, y: 0}, "", finalUrl); }
      here = L.pathname + L.search;
      d.documentElement.lang = doc.documentElement.lang || d.documentElement.lang;
      d.documentElement.dir = doc.documentElement.dir || d.documentElement.dir;
      var ns = styleSig(doc);
      if (ns !== mySig) { swapStyles(doc); mySig = ns; }
      swapHead(doc);
      // خصائص الجسم (data-server… يقرؤها سكربت الصفحة) ثم محتواه، مع إبقاء العناصر الدائمة (زرّ «محتار ايش تشاهد؟»)
      var i, a;
      for (i = d.body.attributes.length - 1; i >= 0; i--) d.body.removeAttribute(d.body.attributes[i].name);
      for (i = 0; i < doc.body.attributes.length; i++) { a = doc.body.attributes[i]; d.body.setAttribute(a.name, a.value); }
      var keep = d.getElementById("fyFab");
      while (d.body.firstChild) d.body.removeChild(d.body.firstChild);
      var nodes = doc.body.childNodes;
      for (i = 0; i < nodes.length; i++) d.body.appendChild(d.importNode(nodes[i], true));
      if (keep) { d.body.appendChild(keep); keep.hidden = /\/content\/for-you\//.test(L.pathname); }
      runScripts(d.body);
      var h = L.hash && d.getElementById(decodeURIComponent(L.hash.slice(1)));
      if (h) h.scrollIntoView(); else w.scrollTo(0, push ? 0 : (y || 0));
      try { if (w.sqNav) w.sqNav.after(prev); } catch (e) {}
      try { var f = d.querySelector("h1"); if (f) { f.setAttribute("tabindex", "-1"); f.focus({preventScroll: true}); } } catch (e) {}
    };
    var reduce = w.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (d.startViewTransition && !reduce) d.startViewTransition(go); else go();
    return true;
  }

  function nav(url, push, y) {
    var id = ++busy;
    progress(true);
    get(url).then(function (res) {
      if (id !== busy) return;           // نقرةٌ أحدث سبقتها
      progress(false);
      var u = new URL(res.url || url, L.href);
      if (u.origin !== L.origin || !SCOPE.test(u.pathname) || !apply(res, url, push, y)) L.href = url;
    })["catch"](function () { if (id === busy) { progress(false); L.href = url; } });
  }

  d.addEventListener("click", function (e) {
    if (!plain(e)) return;
    var a = e.target.closest ? e.target.closest("a") : null;
    if (!eligible(a)) return;
    e.preventDefault();
    nav(a.href, true);
  });
  d.addEventListener("submit", function (e) {       // نماذج GET (الفلاتر والبحث) داخل النطاق
    var f = e.target;
    if (!f || (f.method || "get").toLowerCase() !== "get" || e.defaultPrevented || f.hasAttribute("data-hard")) return;
    var u = new URL(f.getAttribute("action") || L.pathname, L.href);
    if (u.origin !== L.origin || !SCOPE.test(u.pathname)) return;
    var q = [], i, el;
    for (i = 0; i < f.elements.length; i++) {
      el = f.elements[i];
      if (!el.name || el.disabled || ((el.type === "checkbox" || el.type === "radio") && !el.checked)) continue;
      q.push(encodeURIComponent(el.name) + "=" + encodeURIComponent(el.value));
    }
    u.search = q.length ? "?" + q.join("&") : "";
    e.preventDefault();
    nav(u.href, true);
  });
  function pre(e) {
    var a = e.target.closest ? e.target.closest("a") : null;
    if (eligible(a)) { try { get(a.href); } catch (x) {} }
  }
  d.addEventListener("mouseover", pre, {passive: true});
  d.addEventListener("touchstart", pre, {passive: true});
  w.addEventListener("popstate", function (e) {
    if (L.pathname + L.search === here) return;        // تغيّرت المرساة فقط
    if (!SCOPE.test(L.pathname)) { L.reload(); return; }
    nav(L.href, false, e.state && e.state.y);
  });
})();

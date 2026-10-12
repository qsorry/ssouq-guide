// ==UserScript==
// @name         سمارت سوق ← سحب الطلبات والشكاوى من لوحة سلة
// @namespace    https://__TOOL_HOST__/
// @version      __VERSION__
// @description  زرّان على لوحة سلة: سحب الطلبات، وسحب سجل الشكاوى — إلى أداة التجديد (للجوال: Tampermonkey في Edge، حيث لا تُثبَّت الإضافة)
// @match        https://s.salla.sa/*
// @grant        GM_xmlhttpRequest
// @grant        GM_setValue
// @grant        GM_getValue
// @connect      __TOOL_HOST__
// @connect      api.salla.dev
// @run-at       document-idle
// ==/UserScript==
//
// النسخة الخفيفة من إضافة المتصفّح: تعمل داخل صفحة s.salla.sa نفسها (فجلسة اللوحة جلسةُ الصفحة، بلا كوكيز تُلتقط)،
// وتنادي الأداة بـ GM_xmlhttpRequest (يتجاوز CORS) بمصادقة Basic. المسارات والمحلّلات هي نفسها التي في
// background.js: مرشّحات JSON في اللوحة ← api.salla.dev برمز الجلسة (من localStorage) ← صفحة HTML، ثم تحويل
// معرّفات الطلبات إلى أرقامها. تُقدَّم من الأداة على GET /api/renew/userscript (تُعبَّأ TOOL وVERSION).
(function () {
  "use strict";
  const TOOL = "https://__TOOL_HOST__" + "__TOOL_PATH__";
  const KEY = "ssouq_tool_login";
  const API = "https://api.salla.dev/admin/v2";
  const COMPLAINT_JSON = [
    "/api/complaints?per_page=50&page={p}", "/api/v1/complaints?per_page=50&page={p}",
    "/complaints?format=json&per_page=50&page={p}", "/customers/complaints?format=json&per_page=50&page={p}",
    "/orders/complaints?format=json&per_page=50&page={p}",
  ];
  const COMPLAINT_API = ["/complaints?per_page=50&page={p}", "/customers/complaints?per_page=50&page={p}", "/orders/complaints?per_page=50&page={p}"];
  const COMPLAINT_HTML = ["/complaints?page={p}", "/customers/complaints?page={p}", "/orders/complaints?page={p}"];
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // ---- الواجهة: زرٌّ عائم وسطرُ حالة ----
  const box = document.createElement("div");
  box.style.cssText = "position:fixed;inset-inline-start:12px;bottom:12px;z-index:2147483647;font:14px/1.5 Tahoma,sans-serif;direction:rtl;display:grid;gap:6px;max-width:min(92vw,360px)";
  const BTN = "border:0;border-radius:14px;padding:12px 16px;background:#0f9c6e;color:#fff;font:inherit;font-weight:700;box-shadow:0 8px 24px rgba(0,0,0,.25);cursor:pointer";
  const btn = document.createElement("button");
  btn.textContent = "📥 سحب الشكاوى → سمارت سوق";
  btn.style.cssText = BTN;
  const btnO = document.createElement("button");
  btnO.textContent = "📦 سحب الطلبات → سمارت سوق";
  btnO.style.cssText = BTN + ";background:#2563eb";
  const line = document.createElement("div");
  line.style.cssText = "display:none;background:#12213a;color:#fff;border-radius:12px;padding:8px 12px;font-size:13px;white-space:pre-wrap";
  box.append(btnO, btn, line);
  document.documentElement.appendChild(box);
  const set = (t, ok) => { line.style.display = t ? "block" : "none"; line.textContent = t || ""; line.style.background = ok === true ? "#0b7f5a" : ok === false ? "#c2412d" : "#12213a"; };

  // ---- الأداة: Basic + GM_xmlhttpRequest ----
  function login() {
    let s = GM_getValue(KEY, null);
    if (s && s.user && s.pass) return s;
    const user = prompt("اسم الدخول للأداة (سمارت سوق):", (s && s.user) || "admin");
    if (!user) return null;
    const pass = prompt("كلمة المرور للأداة:");
    if (!pass) return null;
    s = { user, pass };
    GM_setValue(KEY, s);
    return s;
  }
  function toolPost(s, path, body) {
    return new Promise((resolve, reject) => {
      GM_xmlhttpRequest({
        method: "POST", url: TOOL + path, data: JSON.stringify(body), timeout: 60000,
        headers: { "Content-Type": "application/json", Authorization: "Basic " + btoa(unescape(encodeURIComponent(s.user + ":" + s.pass))) },
        onload: (r) => {
          let d = {}; try { d = JSON.parse(r.responseText || "{}"); } catch (e) { /* ردّ غير JSON */ }
          if (r.status === 401) { GM_setValue(KEY, null); return reject(new Error("اسم الدخول أو كلمة المرور غير صحيحة (401) — أعد الضغط وأدخلهما")); }
          if (r.status < 200 || r.status >= 300) return reject(new Error(d.error || "خطأ " + r.status));
          if (d.ok === false) return reject(new Error(d.error || "رفض الخادم"));
          resolve(d);
        },
        onerror: () => reject(new Error("تعذّر الوصول للأداة")), ontimeout: () => reject(new Error("انتهت مهلة الأداة")),
      });
    });
  }

  // ---- لوحة سلة: نفس الأصل، فجلسة الصفحة تكفي ----
  async function sallaJson(path) {
    const r = await fetch(path, { credentials: "include", headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" } });
    if (!r.ok) return "";
    const t = await r.text(); const s = t.trim();
    return s.startsWith("{") || s.startsWith("[") ? t : "";
  }
  async function sallaHtml(path) {
    const r = await fetch(path, { credentials: "include", headers: { Accept: "text/html" } });
    return r.ok ? await r.text() : "";
  }
  function userToken() {
    try { const u = JSON.parse(localStorage.getItem("user") || "null"); return u && u.token ? u.token : ""; } catch (e) { return ""; }
  }
  async function apiGet(token, path) {
    const r = await fetch(API + path, { headers: { Authorization: "Bearer " + token, Accept: "application/json" } });
    if (!r.ok) throw new Error("واجهة سلة " + r.status);
    return await r.json();
  }

  let running = false;
  async function run() {
    if (running) return;
    const s = login(); if (!s) return;
    running = true; btn.disabled = true;
    try {
      set("بدء سحب الشكاوى…");
      await toolPost(s, "/api/renew/complaints-feed", { op: "start" });
      const token = userToken();
      const sources = [
        ["json", (p) => sallaJson(p), COMPLAINT_JSON],
        ["api", async (p) => { if (!token) return ""; try { return JSON.stringify(await apiGet(token, p)); } catch (e) { return ""; } }, COMPLAINT_API],
        ["html", (p) => sallaHtml(p), COMPLAINT_HTML],
      ];
      let total = 0;
      outer: for (const [kind, read, paths] of sources) {
        for (const tpl of paths) {
          let body = ""; try { body = await read(tpl.replace("{p}", "1")); } catch (e) { body = ""; }
          if (!body) continue;
          const r = await toolPost(s, "/api/renew/complaints-feed", { op: "page", path: tpl, body });
          if (!r.found) continue;
          total = r.total; set(`وُجد سجل الشكاوى (${kind}) · ${total} شكوى…`);
          for (let page = 2; page <= 20; page++) {
            await sleep(400);
            let more = ""; try { more = await read(tpl.replace("{p}", String(page))); } catch (e) { more = ""; }
            if (!more) break;
            const rr = await toolPost(s, "/api/renew/complaints-feed", { op: "page", path: tpl, body: more });
            if (!rr.found || !rr.new) break;
            total = rr.total; set(`صفحة ${page} · ${total} شكوى…`);
          }
          break outer;
        }
      }
      const fin = await toolPost(s, "/api/renew/complaints-feed", { op: "finish", force: true });
      if (!total) { set("لم أجد سجل الشكاوى بالمسارات المعروفة. افتح صفحة الشكاوى هنا وأرسل رابطها كما يظهر في المتصفّح.", false); return; }
      // معرّفات الطلبات الداخلية → أرقامها التي يراها العميل (برمز الجلسة)
      const sids = fin.unresolved || [];
      let resolved = 0, left = sids.length;
      if (sids.length && token) {
        const map = {};
        for (const [i, sid] of sids.entries()) {
          try { const j = await apiGet(token, `/orders/${sid}`); const ref = j && j.data && (j.data.reference_id || j.data.reference); if (ref) map[sid] = String(ref); } catch (e) { /* يبقى بلا رقم */ }
          set(`تحويل أرقام الطلبات… ${i + 1} من ${sids.length}`); await sleep(250);
        }
        const rr = await toolPost(s, "/api/renew/complaints-feed", { op: "resolve", map });
        resolved = rr.resolved || 0; left = rr.left || 0;
      }
      set(`اكتمل ✓ ${fin.total} شكوى، منها ${fin.open} تنتظر التاجر${sids.length ? ` · أرقام الطلبات: حُوّل ${resolved}${left ? `، بقي ${left} بلا رقم` : ""}` : ""}.\nافتح «الردّ على الشكاوى» في الأداة.`, true);
    } catch (e) {
      set("توقّف: " + (e && e.message ? e.message : e), false);
    } finally {
      running = false; btn.disabled = false;
    }
  }
  btn.onclick = run;

  // ---- سحب الطلبات: كحلقة الإضافة سواءً بسواء (/api/renew/panel-feed) — قائمة الطلبات صفحةً صفحة ثم صفحة كل طلب ----
  let runningO = false, cancelO = false;
  async function runOrders() {
    if (runningO) { cancelO = true; btnO.textContent = "⏳ جارٍ الإيقاف…"; return; }
    const s = login(); if (!s) return;
    const months = Math.max(0, Number(prompt("الطلبات الأحدث من (أشهر) — ٠ = الكل:", String(GM_getValue("ssouq_months", 15))) || 0));
    GM_setValue("ssouq_months", months);
    runningO = true; cancelO = false; btn.disabled = true; btnO.textContent = "⏹ إيقاف سحب الطلبات";
    try {
      set("بدء سحب الطلبات…");
      const st = await toolPost(s, "/api/renew/panel-feed", { op: "start", max_months: months, apply: true, resume: true, fresh: false });
      let page = st.resume_page || 1, more = true, units = st.units || 0, found = st.found || 0, opened = st.done || 0, listed = st.total || 0;
      if (st.resume_page) set(`استئناف من صفحة ${page} (${units} يوزرًا محفوظة)`);
      while (more && !cancelO) {
        const html = await sallaHtml(`/orders?page=${page}&sort_by=created_at-desc`);
        if (!html) throw new Error("لم تُقرأ صفحة الطلبات — سجّل دخولك للوحة سلة");
        const lst = await toolPost(s, "/api/renew/panel-feed", { op: "list", page, html });
        more = !!lst.more; listed += lst.rows || 0;
        const sids = lst.sids || [];
        let tooOld = false;
        for (let i = 0; i < sids.length && !cancelO; i += 2) {
          const batch = sids.slice(i, i + 2);
          const pages = await Promise.all(batch.map((sid) => sallaHtml(`/orders/order/${sid}`)));
          const orders = {}; batch.forEach((sid, k) => { orders[sid] = pages[k]; });
          const res = await toolPost(s, "/api/renew/panel-feed", { op: "orders", orders });
          opened = res.done || opened + batch.length; units = res.units || units; found = res.found || found; tooOld = tooOld || !!res.too_old;
          set(`صفحة ${page} · ${opened} من ${listed} طلبًا · ${units} يوزرًا (${found} باعتماد)`);
          await sleep(400);
        }
        if (tooOld) break;
        if (page % 10 === 0) await toolPost(s, "/api/renew/panel-feed", { op: "save" });
        page += 1;
      }
      const fin = await toolPost(s, "/api/renew/panel-feed", { op: "finish" });
      if (!fin.units && !cancelO) { set("لا طلبات جديدة منذ آخر سحب — المحفوظ كما هو ✓", true); return; }
      set(cancelO ? `أُوقف. حُفظ ما سُحب: ${fin.units} يوزرًا (${fin.found} باعتماد)` : `اكتمل ✓ ${fin.units} يوزرًا، ${fin.found} باعتماد، ${fin.pages} صفحة. افتح صفحة التجديد في الأداة.`, true);
    } catch (e) {
      set("توقّف: " + (e && e.message ? e.message : e), false);
    } finally {
      runningO = false; cancelO = false; btn.disabled = false; btnO.textContent = "📦 سحب الطلبات → سمارت سوق";
    }
  }
  btnO.onclick = runOrders;
})();

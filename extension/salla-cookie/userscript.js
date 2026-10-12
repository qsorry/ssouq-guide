// ==UserScript==
// @name         سمارت سوق ← أداة التجديد على لوحة سلة
// @namespace    https://__TOOL_HOST__/
// @version      __VERSION__
// @description  لوحةٌ صغيرة على لوحة سلة بمواصفات الإضافة: سحب الطلبات (بحدّ الأشهر ومن الصفر/استئناف)، وسحب الشكاوى، وسحب الأكواد المتاحة — إلى أداة التجديد (للجوال: Tampermonkey في Edge)
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

  // ---- الواجهة: لوحةٌ عائمة قابلة للطيّ، بمواصفات نافذة الإضافة ----
  const box = document.createElement("div");
  box.style.cssText = "position:fixed;inset-inline-start:12px;bottom:12px;z-index:2147483647;font:14px/1.5 Tahoma,sans-serif;direction:rtl;max-width:min(92vw,380px)";
  const fab = document.createElement("button");
  fab.textContent = "🛍 سمارت سوق";
  fab.style.cssText = "border:0;border-radius:999px;padding:12px 18px;background:#0f9c6e;color:#fff;font:inherit;font-weight:700;box-shadow:0 8px 24px rgba(0,0,0,.25);cursor:pointer";
  const panel = document.createElement("div");
  panel.style.cssText = "display:none;background:#fff;color:#12213a;border:1px solid #d6dfeb;border-radius:18px;padding:12px;box-shadow:0 14px 40px rgba(20,40,80,.2);margin-bottom:8px;display:none;gap:10px";
  const BTN = "border:0;border-radius:12px;padding:11px 14px;color:#fff;font:inherit;font-weight:700;cursor:pointer;width:100%";
  panel.innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between;gap:8px"><b>سمارت سوق · أداة التجديد</b><button data-x style="border:0;background:#eef2f8;border-radius:10px;width:34px;height:34px;font-size:18px;cursor:pointer">×</button></div>
    <div style="border:1px solid #d6dfeb;border-radius:14px;padding:10px;display:grid;gap:8px">
      <b style="font-size:13px">📦 سحب الطلبات</b>
      <label style="font-size:12px;color:#5f7290;display:flex;align-items:center;gap:6px">الأحدث من <input data-months type="number" min="0" max="120" style="width:64px;padding:6px;border:1px solid #d6dfeb;border-radius:8px"> شهرًا (٠ = الكل)</label>
      <label style="font-size:12px;color:#5f7290;display:flex;align-items:center;gap:6px"><input data-fresh type="checkbox"> من الصفر (بدل الإكمال من حيث توقّف)</label>
      <button data-orders style="${BTN};background:#2563eb">ابدأ سحب الطلبات</button>
    </div>
    <button data-complaints style="${BTN};background:#0f9c6e">📥 سحب الشكاوى</button>
    <button data-codes style="${BTN};background:#6d5ce7">🎟 سحب الأكواد المتاحة (المنتجات الرقمية)</button>
    <div data-line style="display:none;background:#12213a;color:#fff;border-radius:12px;padding:8px 12px;font-size:13px;white-space:pre-wrap"></div>
    <button data-login style="border:0;background:transparent;color:#5f7290;font-size:12px;text-decoration:underline;cursor:pointer;justify-self:start">تغيير بيانات الدخول للأداة</button>`;
  box.append(panel, fab);
  document.documentElement.appendChild(box);
  const q = (k) => panel.querySelector("[data-" + k + "]");
  const line = q("line"), btn = q("complaints"), btnO = q("orders"), btnC = q("codes");
  q("months").value = GM_getValue("ssouq_months", 15);
  fab.onclick = () => { const open = panel.style.display === "grid"; panel.style.display = open ? "none" : "grid"; };
  q("x").onclick = () => { panel.style.display = "none"; };
  q("login").onclick = () => { GM_setValue(KEY, null); login(); };
  const set = (t, ok) => { line.style.display = t ? "block" : "none"; line.textContent = t || ""; line.style.background = ok === true ? "#0b7f5a" : ok === false ? "#c2412d" : "#12213a"; if (t && panel.style.display !== "grid") { panel.style.display = "grid"; } };

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
    running = true; btn.disabled = true; btnO.disabled = true; btnC.disabled = true;
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
      running = false; btn.disabled = false; btnO.disabled = false; btnC.disabled = false;
    }
  }
  btn.onclick = run;

  // ---- سحب الطلبات: كحلقة الإضافة سواءً بسواء (/api/renew/panel-feed) — قائمة الطلبات صفحةً صفحة ثم صفحة كل طلب ----
  let runningO = false, cancelO = false;
  async function runOrders() {
    if (runningO) { cancelO = true; btnO.textContent = "⏳ جارٍ الإيقاف…"; return; }
    const s = login(); if (!s) return;
    const months = Math.max(0, Number(q("months").value) || 0), fresh = !!q("fresh").checked;
    GM_setValue("ssouq_months", months);
    runningO = true; cancelO = false; btn.disabled = true; btnC.disabled = true; btnO.textContent = "⏹ إيقاف سحب الطلبات";
    try {
      set("بدء سحب الطلبات…");
      const st = await toolPost(s, "/api/renew/panel-feed", { op: "start", max_months: months, apply: true, resume: !fresh, fresh });
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
      runningO = false; cancelO = false; btn.disabled = false; btnC.disabled = false; btnO.textContent = "ابدأ سحب الطلبات";
    }
  }
  btnO.onclick = runOrders;

  // ---- الأكواد المتاحة (المنتجات الرقمية): كـ runCodes في الإضافة — المنتجات من api.salla.dev برمز الجلسة، وأكواد كل
  // منتجٍ من نافذة اللوحة القديمة (/products/{id}/details) وإلا من الواجهة، ثم تُرسل إلى /api/renew/salla-codes ----
  const items = (j) => { const d = j && j.data; if (Array.isArray(d)) return d; if (d && Array.isArray(d.items)) return d.items; if (d && Array.isArray(d.data)) return d.data; return Array.isArray(j) ? j : []; };
  const lastPage = (j) => { const p = (j && (j.pagination || (j.meta && j.meta.pagination) || j.meta)) || {}; return Number(p.totalPages || p.total_pages || p.last_page || p.pages || 0) || 0; };
  const isCodesProduct = (p) => { const t = String((p && (p.type || p.product_type || (p.product && p.product.type))) || "").toLowerCase(); return t === "codes" || t === "digital" || t === "code"; };
  function legacyCodeCount(html) { let n = 0; const re = /<textarea\b([^>]*)>([\s\S]*?)<\/textarea>/gi; let m; while ((m = re.exec(html || "")) !== null) { if (/code_content/.test(m[1]) && m[2].trim()) n++; } return n; }
  let runningC = false;
  async function runCodes() {
    if (runningC) return;
    const s = login(); if (!s) return;
    runningC = true; btnC.disabled = true; btnO.disabled = true;
    try {
      const token = userToken();
      if (!token) throw new Error("لا رمز جلسة في لوحة سلة — سجّل دخولك ثم أعد المحاولة");
      set("جلب المنتجات…");
      const digital = [];
      for (let page = 1, last = 1; page <= last && page < 200; page++) {
        const j = await apiGet(token, `/products?page=${page}&per_page=50`);
        const list = items(j); if (!list.length) break;
        last = lastPage(j) || (list.length === 50 ? page + 1 : page);
        for (const p of list) if (isCodesProduct(p)) digital.push({ id: p.id, name: p.name || "", sku: p.sku || "", type: p.type || p.product_type || "" });
        set(`المنتجات: صفحة ${page} · ${digital.length} منتجًا رقميًا`); await sleep(400);
      }
      if (!digital.length) throw new Error("لم أجد منتجات رقمية (نوع codes) في المتجر");
      let total = 0, reset = true, summary = null;
      for (const [i, p] of digital.entries()) {
        let html = "", codes = [];
        try { html = await sallaHtml(`/products/${p.id}/details?product_type=codes`); } catch (e) { html = ""; }
        const n = legacyCodeCount(html);
        if (!n) {
          html = "";
          for (let page = 1, last = 1; page <= last && page < 500; page++) {
            const j = await apiGet(token, `/products/${p.id}/codes?page=${page}&per_page=100`);
            const list = items(j); if (!list.length) break;
            codes.push(...list); last = lastPage(j) || (list.length === 100 ? page + 1 : page); await sleep(400);
          }
        }
        const count = n || codes.length; total += count; await sleep(400);
        summary = await toolPost(s, "/api/renew/salla-codes", { reset, products: [{ ...p, total: count, codes, html, source: n ? "legacy" : "api" }] });
        reset = false;
        set(`${i + 1} من ${digital.length} منتجًا · ${total} كودًا${summary && summary.unparsed ? ` · غير مقروء ${summary.unparsed}` : ""}`);
      }
      set(`اكتمل ✓ ${digital.length} منتجًا رقميًا، ${total} كودًا، منها ${summary ? summary.with_username : 0} بيوزر مقروء. احسب «غير المعروض» في صفحة التجديد.`, true);
    } catch (e) {
      set("توقّف: " + (e && e.message ? e.message : e), false);
    } finally {
      runningC = false; btnC.disabled = false; btnO.disabled = false;
    }
  }
  btnC.onclick = runCodes;
})();

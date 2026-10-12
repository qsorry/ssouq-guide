// خدمة الخلفية: تقرأ كوكيز لوحة سلة من المتصفّح، وترسلها إلى أداة التجديد.
//
// لماذا إضافة؟ ترويسة `Cookie` في لوحة سلة تحوي كوكيزًا HttpOnly لا يراها
// `document.cookie`، ولذلك كان الطريق الوحيد سابقًا هو «Copy as cURL» يدويًّا.
// لكن chrome.cookies يقرأ حتى HttpOnly، فتُلتقط الجلسة بنقرة واحدة.
//
// المصادقة على الأداة بترويسة Basic (يدعمها `_who` في xm_lines.py)، فلا حاجة
// لكوكيز جلسة الأداة ولا لإعداد CORS.

const SALLA_URL = "https://s.salla.sa/";

// كوكيز الجلسة الأساسية في لوحة سلة — للتحذير إن لم يكن المشغّل داخلًا.
const SESSION_HINTS = ["salla_session", "XSRF-TOKEN", "salla", "s_session"];

async function readSallaCookie() {
  // url يجمع كوكيز s.salla.sa وكوكيز النطاق الأب (.salla.sa) التي تُرسَل إليه.
  const cookies = await chrome.cookies.getAll({ url: SALLA_URL });
  if (!cookies || !cookies.length) {
    return { cookie: "", count: 0, hasSession: false };
  }
  // ترتيب ثابت (بالاسم) كي لا تختلف الترويسة بين النقرات.
  cookies.sort((a, b) => a.name.localeCompare(b.name));
  const header = cookies
    .filter((c) => c.name && c.value !== undefined)
    .map((c) => `${c.name}=${c.value}`)
    .join("; ");
  const names = cookies.map((c) => c.name.toLowerCase());
  const hasSession = SESSION_HINTS.some((h) => names.includes(h.toLowerCase())) ||
    names.some((n) => n.includes("session"));
  return { cookie: header, count: cookies.length, hasSession };
}

function toolOrigin(base) {
  try {
    return new URL(base).origin + "/*";
  } catch (e) {
    return "";
  }
}

async function sendToTool({ base, user, pass, cookie, test }) {
  const url = base.replace(/\/+$/, "") + "/api/renew/panel-cookie";
  const auth = "Basic " + btoa(unescape(encodeURIComponent(`${user}:${pass}`)));
  let r;
  try {
    r = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: auth,
      },
      body: JSON.stringify({ cookie, test: !!test }),
    });
  } catch (e) {
    return { ok: false, error: "تعذّر الوصول للأداة: " + (e && e.message ? e.message : e) };
  }
  let d = {};
  try {
    d = await r.json();
  } catch (e) {
    /* ردّ غير JSON */
  }
  if (r.status === 401) {
    return { ok: false, error: "اسم الدخول أو كلمة المرور غير صحيحة (401)" };
  }
  if (!r.ok) {
    return { ok: false, error: d.error || "خطأ " + r.status };
  }
  return { ok: true, ...d };
}

// ---- السحب من جهاز المشغّل ----
// Cloudflare يحجب عنوان خادم الأداة عن لوحة سلة، أما متصفّح المشغّل فمسموح.
// فالإضافة تقرأ صفحات اللوحة من هنا (بجلسته) وترسلها خامًا إلى
// /api/renew/panel-feed، والخادم يحلّلها بمحلّلاته نفسها.
const PULL_WORKERS = 2;            // أكثر من هذا ولوحة سلة تردّ 429 (حدّ المعدّل)
const PULL_PAUSE_MS = 400;         // مهلة بين الدفعات، لتبقى تحت الحدّ
const pullState = { running: false, cancel: false, line: "", ok: null };

async function toolPost(settings, path, body) {
  const url = settings.base.replace(/\/+$/, "") + path;
  const auth = "Basic " + btoa(unescape(encodeURIComponent(`${settings.user}:${settings.pass}`)));
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: auth },
    body: JSON.stringify(body),
  });
  let d = {};
  try { d = await r.json(); } catch (e) { /* ردّ غير JSON */ }
  if (r.status === 401) throw new Error("اسم الدخول أو كلمة المرور غير صحيحة (401)");
  if (!r.ok) throw new Error(d.error || "خطأ " + r.status);
  if (d.ok === false) throw new Error(d.error || "رفض الخادم");
  return d;
}

const sleep = (ms) => new Promise((res) => setTimeout(res, ms));

// صفحة من لوحة سلة بجلسة المتصفّح. ‏429 (حدّ المعدّل) و5xx تُعاد بانتظارٍ متدرّج
// (Retry-After إن قالته اللوحة)، حتى خمس مرات، قبل أن يُعدّ فشلًا.
async function sallaPage(path) {
  let last = "";
  for (let attempt = 0; attempt < 5; attempt++) {
    const r = await fetch(SALLA_URL.replace(/\/$/, "") + path, {
      credentials: "include",
      headers: { Accept: "text/html" },
      redirect: "manual",
    });
    if (r.type === "opaqueredirect" || r.status === 0) throw new Error("حُوّلنا لصفحة الدخول — سجّل دخولك للوحة سلة أولًا");
    if (r.ok) return await r.text();
    last = "ردّت لوحة سلة " + r.status;
    if (r.status !== 429 && r.status < 500) throw new Error(last);
    const ra = Number(r.headers.get("Retry-After")) || 0;
    const wait = ra > 0 ? Math.min(60, ra) * 1000 : (r.status === 429 ? 5000 : 2000) * 2 ** attempt;
    setLine(`${last} — انتظار ${Math.round(wait / 1000)} ث ثم إعادة…`, null);
    await sleep(wait);
  }
  throw new Error(last + " بعد خمس محاولات");
}

// الحالة تُحفظ في التخزين أيضًا: كروم يُطفئ خلفية الإضافة بعد ثوانٍ من الخمول فتضيع
// الذاكرة، والنافذة تقرأ من التخزين عند فتحها لتعرف أين وصل السحب أو كيف انتهى.
function persist(key, st) {
  chrome.storage.local.set({ [key]: { ...st, at: Date.now() } }).catch(() => {});
}
function setLine(line, ok) {
  pullState.line = line;
  pullState.ok = ok;
  persist("pull_state", pullState);
}

async function runPull(settings, maxMonths, fresh) {
  if (pullState.running) return;
  pullState.running = true;
  pullState.cancel = false;
  try {
    setLine("بدء السحب…", null);
    // إكمالٌ من حيث توقّف (الافتراضي): الخادم يعرف الطلبات المحفوظة فلا تُفتح، ويقف عند أوّل صفحة كلها محفوظة.
    const st = await toolPost(settings, "/api/renew/panel-feed", { op: "start", max_months: maxMonths, apply: true, resume: true, fresh: !!fresh });
    // انقطع سحبٌ سابق (أُغلق المتصفّح)؟ الخادم يعيد الصفحة التالية وما جُمع، فيُستأنف لا يُعاد.
    let page = st.resume_page || 1, more = true, units = st.units || 0, found = st.found || 0, opened = st.done || 0, listed = st.total || 0;
    if (st.resume_page) setLine(`استئناف من صفحة ${page} (${units} يوزرًا محفوظة)`, null);
    while (more && !pullState.cancel) {
      const html = await sallaPage(`/orders?page=${page}&sort_by=created_at-desc`);
      const lst = await toolPost(settings, "/api/renew/panel-feed", { op: "list", page, html });
      more = !!lst.more;
      listed += lst.rows || 0;
      const sids = lst.sids || [];
      let tooOld = false;
      // أربعة طلبات في آنٍ واحد — كخيوط الخادم في السحب المباشر.
      for (let i = 0; i < sids.length && !pullState.cancel; i += PULL_WORKERS) {
        const batch = sids.slice(i, i + PULL_WORKERS);
        const pages = await Promise.all(batch.map((sid) => sallaPage(`/orders/order/${sid}`)));
        const orders = {};
        batch.forEach((sid, k) => { orders[sid] = pages[k]; });
        const res = await toolPost(settings, "/api/renew/panel-feed", { op: "orders", orders });
        opened = res.done || opened + batch.length;
        units = res.units || units;
        found = res.found || found;
        tooOld = tooOld || !!res.too_old;
        setLine(`صفحة ${page} · ${opened} من ${listed} طلبًا · ${units} يوزرًا (${found} باعتماد)`, null);
        await sleep(PULL_PAUSE_MS);
      }
      if (tooOld) break;               // صفحةٌ كلها أقدم من الحدّ: ما بعدها أقدم
      // كل عشر صفحات يُحفظ ما جُمع على الخادم، فإن أُغلق المتصفّح لم يضع شيء.
      if (page % 10 === 0) await toolPost(settings, "/api/renew/panel-feed", { op: "save" });
      page += 1;
    }
    const fin = await toolPost(settings, "/api/renew/panel-feed", { op: "finish" });
    if (!fin.units && !pullState.cancel) { setLine("لا طلبات جديدة منذ آخر سحب — المحفوظ كما هو ✓", true); return; }
    setLine(pullState.cancel
      ? `أُوقف. حُفظ ما سُحب: ${fin.units} يوزرًا (${fin.found} باعتماد)`
      : `اكتمل ✓ ${fin.units} يوزرًا، ${fin.found} باعتماد، ${fin.pages} صفحة. نزّل Excel من صفحة التجديد.`, true);
  } catch (e) {
    setLine("توقّف: " + (e && e.message ? e.message : e), false);
  } finally {
    pullState.running = false;
    persist("pull_state", pullState);
  }
}

// ---- سجل شكاوى العملاء من جهاز المشغّل ----
// سلة لا تفتح سجل الشكاوى في Admin API، ولوحتها محجوبة عن الخادم بـ Cloudflare — فتُقرأ صفحاته من هنا
// (بجلسة المتصفّح) وتُرسَل خامًا إلى /api/renew/complaints-feed، والخادم يحلّلها (JSON أو جدول HTML) ويحفظها.
// مساره غير موثّق فتُجرَّب مرشّحات: نُقط JSON في اللوحة، ثم api.salla.dev برمز الجلسة، ثم صفحة HTML.
const COMPLAINT_JSON = [
  "/api/complaints?per_page=50&page={p}", "/api/v1/complaints?per_page=50&page={p}",
  "/complaints?format=json&per_page=50&page={p}", "/customers/complaints?format=json&per_page=50&page={p}",
  "/orders/complaints?format=json&per_page=50&page={p}",
];
const COMPLAINT_API = ["/complaints?per_page=50&page={p}", "/customers/complaints?per_page=50&page={p}", "/orders/complaints?per_page=50&page={p}"];
const COMPLAINT_HTML = ["/complaints?page={p}", "/customers/complaints?page={p}", "/orders/complaints?page={p}"];
const cqState = { running: false, line: "", ok: null };

async function sallaJson(path) {
  const r = await fetch(SALLA_URL.replace(/\/$/, "") + path, {
    credentials: "include", redirect: "manual",
    headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
  });
  if (r.type === "opaqueredirect" || r.status === 0) throw new Error("حُوّلنا لصفحة الدخول — سجّل دخولك للوحة سلة أولًا");
  if (!r.ok) return "";
  const t = await r.text();
  return t.trim().startsWith("{") || t.trim().startsWith("[") ? t : "";
}

async function runComplaints(settings) {
  if (cqState.running) return;
  cqState.running = true;
  const set = (line, ok) => { cqState.line = line; cqState.ok = ok; persist("cq_state", cqState); };
  try {
    set("بدء سحب الشكاوى…", null);
    await toolPost(settings, "/api/renew/complaints-feed", { op: "start" });
    // المصادر بالترتيب: (كيف تُقرأ الصفحة، المسارات). أوّل مصدرٍ يعطي صفوفًا يُتابَع صفحاته حتى تفرغ.
    let token = "";
    const sources = [
      ["json", (p) => sallaJson(p), COMPLAINT_JSON],
      ["api", async (p) => { if (!token) token = await readUserToken(); try { return JSON.stringify(await apiGet(token, p)); } catch (e) { return ""; } }, COMPLAINT_API],
      ["html", (p) => sallaPage(p), COMPLAINT_HTML],
    ];
    let total = 0, where = "";
    outer: for (const [kind, read, paths] of sources) {
      for (const tpl of paths) {
        let body = "";
        try { body = await read(tpl.replace("{p}", "1")); } catch (e) { if (/الدخول/.test(String(e && e.message))) throw e; body = ""; }
        if (!body) continue;
        const r = await toolPost(settings, "/api/renew/complaints-feed", { op: "page", path: tpl, body });
        if (!r.found) continue;
        where = kind + " " + tpl; total = r.total;
        set(`وُجد سجل الشكاوى (${kind}) · ${total} شكوى…`, null);
        for (let page = 2; page <= 20; page++) {
          await sleep(PULL_PAUSE_MS);
          let more = "";
          try { more = await read(tpl.replace("{p}", String(page))); } catch (e) { more = ""; }
          if (!more) break;
          const rr = await toolPost(settings, "/api/renew/complaints-feed", { op: "page", path: tpl, body: more });
          if (!rr.found || !rr.new) break;
          total = rr.total;
          set(`صفحة ${page} · ${total} شكوى…`, null);
        }
        break outer;
      }
    }
    const fin = await toolPost(settings, "/api/renew/complaints-feed", { op: "finish", force: true });
    if (!total) { set("لم أجد سجل الشكاوى بالمسارات المعروفة. افتح صفحة الشكاوى في لوحة سلة وأرسل رابطها كما يظهر في المتصفّح ليُضاف مسارًا.", false); return; }
    // السجل يعطي معرّف الطلب الداخلي لا رقمه الذي يراه العميل: يُحوَّل هنا برمز الجلسة (api.salla.dev) لأن الخادم محجوب
    const sids = fin.unresolved || [];
    let resolved = 0, left = sids.length;
    if (sids.length) {
      if (!token) token = await readUserToken();
      const map = {};
      for (const [i, sid] of sids.entries()) {
        try {
          const j = await apiGet(token, `/orders/${sid}`);
          const ref = j && j.data && (j.data.reference_id || j.data.reference);
          if (ref) map[sid] = String(ref);
        } catch (e) { /* طلبٌ لا يُقرأ: يبقى بلا رقم */ }
        set(`تحويل أرقام الطلبات… ${i + 1} من ${sids.length}`, null);
        await sleep(250);
      }
      const rr = await toolPost(settings, "/api/renew/complaints-feed", { op: "resolve", map });
      resolved = rr.resolved || 0; left = rr.left || 0;
    }
    set(`اكتمل ✓ ${fin.total} شكوى، منها ${fin.open} تنتظر التاجر${sids.length ? ` · أرقام الطلبات: حُوّل ${resolved}${left ? `، بقي ${left} بلا رقم` : ""}` : ""}. افتح «الردّ على الشكاوى» في صفحة التجديد.`, true);
  } catch (e) {
    set("توقّف: " + (e && e.message ? e.message : e), false);
  } finally {
    cqState.running = false;
    persist("cq_state", cqState);
  }
}

// ---- أكواد سلة المتاحة (المنتجات الرقمية) ----
// لوحة سلة الجديدة تنادي api.salla.dev برمزٍ محفوظ في localStorage الخاص بـ s.salla.sa
// (لا في الكوكيز)، فلا يصل إليه الخادم. الإضافة تقرؤه من تبويب اللوحة (scripting)،
// تجدّده إن انتهى، ثم تجلب المنتجات الرقمية وأكوادها وترسلها للأداة لتُحلَّل وتُحفظ.
const API = "https://api.salla.dev/admin/v2";
const codesState = { running: false, line: "", ok: null };

async function sallaTab() {
  const tabs = await chrome.tabs.query({ url: "https://s.salla.sa/*" });
  if (tabs.length) return { tab: tabs[0], created: false };
  const tab = await chrome.tabs.create({ url: "https://s.salla.sa/products", active: false });
  await new Promise((res) => {
    const done = (id, info) => { if (id === tab.id && info.status === "complete") { chrome.tabs.onUpdated.removeListener(done); res(); } };
    chrome.tabs.onUpdated.addListener(done);
    setTimeout(res, 15000);
  });
  return { tab, created: true };
}

async function readUserToken() {
  const { tab, created } = await sallaTab();
  try {
    const [r] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: () => localStorage.getItem("user") });
    const user = r && r.result ? JSON.parse(r.result) : null;
    if (!user || !user.token) throw new Error("لا رمز جلسة في لوحة سلة — افتح s.salla.sa وسجّل دخولك");
    if (user.expire_at && new Date() > new Date(user.expire_at) && user.refresh_token) {
      const rr = await fetch(API + "/auth/refresh", { method: "POST", headers: { Authorization: "Bearer " + user.refresh_token } });
      const j = await rr.json();
      if (!j.data || !j.data.token) throw new Error("تعذّر تجديد رمز الجلسة — أعد فتح لوحة سلة");
      return j.data.token;
    }
    return user.token;
  } finally {
    if (created) chrome.tabs.remove(tab.id).catch(() => {});
  }
}

async function apiGet(token, path) {
  for (let attempt = 0; attempt < 5; attempt++) {
    const r = await fetch(API + path, { headers: { Authorization: "Bearer " + token, Accept: "application/json" } });
    if (r.ok) return await r.json();
    if (r.status === 429 || r.status >= 500) { await sleep((r.status === 429 ? 5000 : 2000) * 2 ** attempt); continue; }
    const t = await r.text();
    throw new Error(`واجهة سلة ${r.status} على ${path}: ${t.slice(0, 120)}`);
  }
  throw new Error("واجهة سلة لا تستجيب على " + path);
}

// قائمة العناصر وعدد الصفحات من ردٍّ أيًّا كان شكله (data[] أو data.items[]، pagination…).
function items(j) {
  const d = j && j.data;
  if (Array.isArray(d)) return d;
  if (d && Array.isArray(d.items)) return d.items;
  if (d && Array.isArray(d.data)) return d.data;
  if (Array.isArray(j)) return j;
  return [];
}
function lastPage(j) {
  const p = (j && (j.pagination || (j.meta && j.meta.pagination) || j.meta)) || {};
  return Number(p.totalPages || p.total_pages || p.last_page || p.pages || 0) || 0;
}
const isCodesProduct = (p) => {
  const t = String((p && (p.type || p.product_type || (p.product && p.product.type))) || "").toLowerCase();
  return t === "codes" || t === "digital" || t === "code";
};

// عدد الأكواد في نافذة اللوحة القديمة (textarea باسم code_content[] غير فارغة؛ القالب المخفي فارغ).
function legacyCodeCount(html) {
  let n = 0;
  const re = /<textarea\b([^>]*)>([\s\S]*?)<\/textarea>/gi;
  let m;
  while ((m = re.exec(html || "")) !== null) {
    if (/code_content/.test(m[1]) && m[2].trim()) n++;
  }
  return n;
}

async function runCodes(settings) {
  if (codesState.running) return;
  codesState.running = true;
  const set = (line, ok) => { codesState.line = line; codesState.ok = ok; persist("codes_state", codesState); };
  try {
    set("قراءة رمز الجلسة…", null);
    const token = await readUserToken();
    set("جلب المنتجات…", null);
    const digital = [];
    for (let page = 1, last = 1; page <= last && page < 200; page++) {
      const j = await apiGet(token, `/products?page=${page}&per_page=50`);
      const list = items(j);
      if (!list.length) break;
      last = lastPage(j) || (list.length === 50 ? page + 1 : page);
      for (const p of list) if (isCodesProduct(p)) digital.push({ id: p.id, name: p.name || "", sku: p.sku || "", type: p.type || p.product_type || "" });
      set(`المنتجات: صفحة ${page} · ${digital.length} منتجًا رقميًا`, null);
      await sleep(PULL_PAUSE_MS);
    }
    if (!digital.length) throw new Error("لم أجد منتجات رقمية (نوع codes) في المتجر");
    let total = 0, reset = true, summary = null;
    for (const [i, p] of digital.entries()) {
      // الأكواد من اللوحة القديمة: نافذة «بيانات المنتج ← الأكواد المتاحة» تُحمَّل من
      // /products/{id}/details وفيها الأكواد كاملةً. الواجهة الجديدة تُعيدها مقنَّعة (XXXX)
      // فلا تُستعمل إلا احتياطًا إن لم تُعطِ الصفحة القديمة شيئًا.
      let html = "", codes = [];
      try {
        html = await sallaPage(`/products/${p.id}/details?product_type=codes`);
      } catch (e) {
        html = "";
      }
      const n = legacyCodeCount(html);
      if (!n) {
        html = "";
        for (let page = 1, last = 1; page <= last && page < 500; page++) {
          const j = await apiGet(token, `/products/${p.id}/codes?page=${page}&per_page=100`);
          const list = items(j);
          if (!list.length) break;
          codes.push(...list);
          last = lastPage(j) || (list.length === 100 ? page + 1 : page);
          await sleep(PULL_PAUSE_MS);
        }
      }
      const count = n || codes.length;
      total += count;
      await sleep(PULL_PAUSE_MS);
      summary = await toolPost(settings, "/api/renew/salla-codes",
        { reset, products: [{ ...p, total: count, codes, html, source: n ? "legacy" : "api" }] });
      reset = false;
      set(`${i + 1} من ${digital.length} منتجًا · ${total} كودًا${summary && summary.unparsed ? ` · غير مقروء ${summary.unparsed}` : ""}`, null);
    }
    set(`اكتمل ✓ ${digital.length} منتجًا رقميًا، ${total} كودًا من اللوحة القديمة، منها ${summary ? summary.with_username : 0} بيوزر مقروء. احسب «غير المعروض» في صفحة التجديد.`, true);
  } catch (e) {
    set("توقّف: " + (e && e.message ? e.message : e), false);
  } finally {
    codesState.running = false;
    persist("codes_state", codesState);
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    try {
      if (msg.type === "grab") {
        sendResponse(await readSallaCookie());
        return;
      }
      if (msg.type === "send") {
        const got = await readSallaCookie();
        if (!got.cookie) {
          sendResponse({ ok: false, error: "لا كوكيز لـ s.salla.sa — سجّل دخولك للوحة سلة أولًا" });
          return;
        }
        const res = await sendToTool({ ...msg.settings, cookie: got.cookie, test: msg.test });
        sendResponse({ ...res, count: got.count, hasSession: got.hasSession });
        return;
      }
      if (msg.type === "pull") {
        runPull(msg.settings, msg.maxMonths, msg.fresh);   // يعمل في الخلفية؛ النافذة تسأل عن حاله
        sendResponse({ ok: true });
        return;
      }
      if (msg.type === "codes") {
        runCodes(msg.settings);
        sendResponse({ ok: true });
        return;
      }
      if (msg.type === "complaints") {
        runComplaints(msg.settings);
        sendResponse({ ok: true });
        return;
      }
      if (msg.type === "codes-status" || msg.type === "pull-status" || msg.type === "complaints-status") {
        const key = msg.type === "codes-status" ? "codes_state" : msg.type === "complaints-status" ? "cq_state" : "pull_state";
        const mem = msg.type === "codes-status" ? codesState : msg.type === "complaints-status" ? cqState : pullState;
        if (mem.line) { sendResponse({ ok: true, ...mem }); return; }
        const saved = (await chrome.storage.local.get(key))[key];
        if (!saved) { sendResponse({ ok: true, ...mem }); return; }
        // الخلفية أُعيد تشغيلها: المحفوظ «جارٍ» لكن لا أحد يعمل الآن → انقطع.
        if (saved.running) {
          saved.running = false;
          saved.ok = false;
          saved.line = "انقطع السحب (أُغلق المتصفح أو أُطفئت الإضافة) عند: " + saved.line + " — اضغط السحب ليُستأنف من حيث توقف";
        }
        sendResponse({ ok: true, ...saved });
        return;
      }
      if (msg.type === "pull-cancel") {
        pullState.cancel = true;
        sendResponse({ ok: true });
        return;
      }
      if (msg.type === "grant") {
        const pat = toolOrigin(msg.base);
        if (!pat) {
          sendResponse({ ok: false, error: "عنوان الأداة غير صالح" });
          return;
        }
        // ممنوحة من قبل؟ لا نافذة إذن (هي تُغلق النافذة المنبثقة)؛ وإلا تُطلب مرةً واحدة وتبقى مع المعرّف الثابت.
        const has = await chrome.permissions.contains({ origins: [pat] }).catch(() => false);
        const granted = has || (await chrome.permissions.request({ origins: [pat] }));
        sendResponse({ ok: granted });
        return;
      }
      sendResponse({ ok: false, error: "طلب غير معروف" });
    } catch (e) {
      sendResponse({ ok: false, error: String(e && e.message ? e.message : e) });
    }
  })();
  return true; // ردّ غير متزامن
});

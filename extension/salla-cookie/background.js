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
const PULL_WORKERS = 4;
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

async function sallaPage(path) {
  const r = await fetch(SALLA_URL.replace(/\/$/, "") + path, {
    credentials: "include",
    headers: { Accept: "text/html" },
    redirect: "manual",
  });
  if (r.type === "opaqueredirect" || r.status === 0) throw new Error("حُوّلنا لصفحة الدخول — سجّل دخولك للوحة سلة أولًا");
  if (!r.ok) throw new Error("ردّت لوحة سلة " + r.status);
  return await r.text();
}

function setLine(line, ok) {
  pullState.line = line;
  pullState.ok = ok;
}

async function runPull(settings, maxMonths) {
  if (pullState.running) return;
  pullState.running = true;
  pullState.cancel = false;
  try {
    setLine("بدء السحب…", null);
    await toolPost(settings, "/api/renew/panel-feed", { op: "start", max_months: maxMonths, apply: true });
    let page = 1, more = true, units = 0, found = 0, opened = 0, listed = 0;
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
      }
      if (tooOld) break;               // صفحةٌ كلها أقدم من الحدّ: ما بعدها أقدم
      page += 1;
    }
    const fin = await toolPost(settings, "/api/renew/panel-feed", { op: "finish" });
    setLine(pullState.cancel
      ? `أُوقف. حُفظ ما سُحب: ${fin.units} يوزرًا (${fin.found} باعتماد)`
      : `اكتمل ✓ ${fin.units} يوزرًا، ${fin.found} باعتماد، ${fin.pages} صفحة. نزّل Excel من صفحة التجديد.`, true);
  } catch (e) {
    setLine("توقّف: " + (e && e.message ? e.message : e), false);
  } finally {
    pullState.running = false;
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
        runPull(msg.settings, msg.maxMonths);   // يعمل في الخلفية؛ النافذة تسأل عن حاله
        sendResponse({ ok: true });
        return;
      }
      if (msg.type === "pull-status") {
        sendResponse({ ok: true, ...pullState });
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
        const granted = await chrome.permissions.request({ origins: [pat] });
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

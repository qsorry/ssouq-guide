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

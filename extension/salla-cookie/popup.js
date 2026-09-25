"use strict";

const $ = (id) => document.getElementById(id);
const KEY = "ssouq_tool";

function setMsg(text, kind) {
  const m = $("msg");
  m.textContent = text || "";
  m.className = "msg" + (kind ? " " + kind : "");
}

async function loadSettings() {
  const d = await chrome.storage.local.get(KEY);
  const s = d[KEY] || {};
  $("base").value = s.base || "";
  $("user").value = s.user || "admin";
  $("pass").value = s.pass || "";
  return s;
}

function readSettings() {
  return {
    base: $("base").value.trim(),
    user: $("user").value.trim(),
    pass: $("pass").value,
  };
}

function validSettings(s) {
  if (!s.base) return "اكتب عنوان الأداة في الإعدادات";
  if (!/^https?:\/\//i.test(s.base)) return "العنوان يجب أن يبدأ بـ http:// أو https://";
  if (!s.user || !s.pass) return "اكتب اسم الدخول وكلمة المرور في الإعدادات";
  return "";
}

const ask = (m) => new Promise((res) => chrome.runtime.sendMessage(m, res));

$("save").onclick = async () => {
  const s = readSettings();
  const bad = validSettings(s);
  if (bad) { setMsg(bad, "err"); $("cfg").open = true; return; }
  // نطلب صلاحية الوصول لعنوان الأداة (host permission) كي يعمل الإرسال.
  const g = await ask({ type: "grant", base: s.base });
  if (!g || !g.ok) {
    setMsg("لم تُمنح صلاحية الوصول لعنوان الأداة" + (g && g.error ? " — " + g.error : ""), "err");
    return;
  }
  await chrome.storage.local.set({ [KEY]: s });
  setMsg("حُفظت الإعدادات ✓", "ok");
};

$("grab").onclick = async () => {
  setMsg("جارٍ القراءة…");
  const g = await ask({ type: "grab" });
  if (!g || !g.cookie) {
    setMsg("لا كوكيز لـ s.salla.sa — سجّل دخولك للوحة سلة أولًا", "err");
    return;
  }
  const out = $("out");
  out.style.display = "block";
  out.value = g.cookie;
  out.select();
  try { await navigator.clipboard.writeText(g.cookie); } catch (e) { /* المستخدم ينسخ يدويًّا */ }
  setMsg(`نُسخت الترويسة ✓ (${g.count} كوكي)${g.hasSession ? "" : " — تحذير: لا يبدو أنك داخل"}`,
         g.hasSession ? "ok" : "err");
};

async function grabAndSend(test) {
  const s = readSettings();
  const bad = validSettings(s);
  if (bad) { setMsg(bad, "err"); $("cfg").open = true; return; }
  await chrome.storage.local.set({ [KEY]: s });
  setMsg(test ? "جارٍ الالتقاط والاختبار…" : "جارٍ الالتقاط والإرسال…");
  const res = await ask({ type: "send", settings: s, test });
  if (!res || !res.ok) {
    setMsg((res && res.error) || "فشل الإرسال", "err");
    return;
  }
  let line = `أُرسلت الجلسة ✓ (${res.cookies} كوكي)`;
  if (!res.hasSession) line += " — تحذير: لا يبدو أنك داخل";
  if (res.alive === true) line += "\nالجلسة صالحة عند سلة ✓";
  if (res.alive === false) line += "\nالجلسة غير مقبولة: " + (res.alive_error || "");
  setMsg(line, res.alive === false ? "err" : "ok");
}

$("send").onclick = () => grabAndSend(false);
$("test").onclick = () => grabAndSend(true);

loadSettings().then((s) => {
  if (!s.base || !s.user || !s.pass) $("cfg").open = true;
});

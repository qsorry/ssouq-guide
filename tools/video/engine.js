/* محرّك فيديوهات الدليل: صفحة الفيديو (ssiptv.html أو 0player.html) تعرّف بعده
     VIDEO  — out (اسم الملف في static/video)، وsteps (عدد الخطوات)، وicon (أيقونة التطبيق)
     IMG    — الصور: src، وmax (أقصى تكبير؛ 1.25 إن لم يُذكر). والمقاسات تُقرأ من الصور نفسها
     SCENES — المشاهد: مدة، ثم صورة وكاميرا (أهداف بزمنها) وحلقات وتعليقات — أو بطاقة
   و render.js يستدعي init() مرة ثم renderAt(ثانية) لكل إطار: الرسم حتميّ، فالإطار نفسه يخرج كل مرة. */
const SW = 680, SH = 760;
const K = s => `<b class="k" dir="ltr">${s}</b>`;
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const ease = x => x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
function fade(t, at){ return clamp((t - at) / 0.35, 0, 1).toFixed(3); }
let starts = [], TOTAL = 0;

function camFor(img, r){
  const I = IMG[img];
  let x, y, w, h;
  if (r === "full") { x = 0; y = 0; w = I.w; h = I.h; } else [x, y, w, h] = r;
  const pad = r === "full" ? 1 : 1.12;
  let s = Math.min(SW / (w * pad), SH / (h * pad), I.max ?? 1.25);
  let cx = x + w / 2, cy = y + h / 2;
  // لا تُظهر ما وراء حدود الصورة إن كانت تملأ الشاشة
  cx = I.w * s >= SW ? clamp(cx, SW / (2 * s), I.w - SW / (2 * s)) : I.w / 2;
  cy = I.h * s >= SH ? clamp(cy, SH / (2 * s), I.h - SH / (2 * s)) : I.h / 2;
  return { cx, cy, s };
}
function camAt(sc, t){
  const keys = sc.cam;
  let cur = camFor(sc.img, keys[0].r);
  for (let i = 1; i < keys.length; i++) {
    const k = keys[i];
    if (t < k.t) break;
    const to = camFor(sc.img, k.r), p = ease(clamp((t - k.t) / (k.d ?? 1.0), 0, 1));
    // تكبير لوغاريتمي: الانتقال بين مقياسين متباعدين يبدو أنعم
    cur = { cx: cur.cx + (to.cx - cur.cx) * p, cy: cur.cy + (to.cy - cur.cy) * p, s: Math.exp(Math.log(cur.s) + (Math.log(to.s) - Math.log(cur.s)) * p) };
  }
  return cur;
}

let lastScene = -1, lastCard = "", lastCap = null;
const $ = id => document.getElementById(id);
function renderAt(T){
  let i = SCENES.length - 1;
  while (i > 0 && T < starts[i]) i--;
  const sc = SCENES[i], t = T - starts[i];
  const a = clamp(Math.min(t / 0.3, (sc.dur - t) / 0.3), 0, 1);      // دخول المشهد وخروجه
  $("screen").style.opacity = i === 0 && t < 0.3 ? 1 : a;
  $("cap").style.opacity = i === 0 && t < 0.3 ? 1 : a;
  // الخطوة وشريط التقدّم
  $("pill").style.visibility = sc.step ? "visible" : "hidden";
  if (sc.step) $("pill").textContent = `الخطوة ${sc.step} من ${VIDEO.steps}`;
  document.querySelectorAll("#prog i").forEach((el, k) => el.classList.toggle("on", !!sc.step && k < sc.step || (!sc.step && i > 0)));
  // بطاقة أو صورة
  if (sc.card) {
    $("card").style.display = "flex"; $("cam").style.display = "none"; $("bgImg").style.display = "none";
    const html = sc.card(t); if (html !== lastCard) { $("card").innerHTML = html; lastCard = html; }
  } else {
    $("card").style.display = "none"; $("cam").style.display = "block"; $("bgImg").style.display = "block";
    if (i !== lastScene) {
      const I = IMG[sc.img]; const im = $("camImg");
      im.src = I.src; im.width = I.w; im.height = I.h; $("bgImg").src = I.src;
      $("cam").querySelectorAll(".ring").forEach(r => r.remove());
      sc.rings.forEach((r, k) => { const d = document.createElement("div"); d.className = "ring"; d.dataset.k = k; $("cam").appendChild(d); });
    }
    const c = camAt(sc, t);
    $("cam").style.transform = `translate(${SW / 2 - c.cx * c.s}px, ${SH / 2 - c.cy * c.s}px) scale(${c.s})`;
    $("cam").querySelectorAll(".ring").forEach(el => {
      const R = sc.rings[+el.dataset.k], on = t >= R.from && (R.to === undefined || t < R.to);
      if (!on) { el.style.opacity = 0; return; }
      const p = ease(clamp((t - R.from) / 0.4, 0, 1)), g = 0.5 + 0.5 * Math.sin((t - R.from) * Math.PI * 2 * 1.1);
      const pad = 10 / c.s, bw = 7 / c.s;
      const [x, y, w, h] = R.r, grow = (1 - p) * 0.25;
      el.style.left = `${x - pad - w * grow / 2}px`; el.style.top = `${y - pad - h * grow / 2}px`;
      el.style.width = `${w + 2 * pad + w * grow}px`; el.style.height = `${h + 2 * pad + h * grow}px`;
      el.style.borderWidth = `${bw}px`; el.style.borderRadius = `${22 / c.s}px`; el.style.opacity = p;
      el.style.boxShadow = `0 0 ${(14 + 18 * g) / c.s}px ${(3 + 5 * g) / c.s}px rgba(240,161,43,${0.35 + 0.35 * g}), inset 0 0 0 ${2 / c.s}px rgba(255,255,255,.25)`;
    });
  }
  // التعليق
  let cap = sc.caps[0]; for (const c of sc.caps) if (t >= c.t) cap = c;
  if (cap !== lastCap) {
    $("capT").innerHTML = (sc.step ? `<span class="n">${sc.step}</span>` : "") + cap.title;
    $("capB").innerHTML = cap.body; lastCap = cap;
  }
  const since = t - cap.t;
  $("capB").style.opacity = cap.t > 0 ? clamp(since / 0.3, 0, 1) : 1;
  lastScene = i;
}

async function init(){
  // الهيكل واحد في كل الفيديوهات: الرأس، وشريط الخطوات، والشاشة، والتعليق
  document.body.innerHTML = `<div id="stage">
  <div id="hdr"><img src="../../static/icons/icon-192.png" alt=""><div class="who"><b>سمارت سوق</b><small>دليل التفعيل · guide.ssouq.com</small></div><span id="pill"></span></div>
  <div id="prog">${"<i></i>".repeat(VIDEO.steps)}</div>
  <div id="screen"><img id="bgImg" alt=""><div id="cam"><img id="camImg" alt=""></div><div id="card"></div></div>
  <div id="cap"><h2 id="capT"></h2><p id="capB"></p></div>
</div>`;
  starts = []; TOTAL = 0;
  for (const s of SCENES) { starts.push(TOTAL); TOTAL += s.dur; }
  // المقاسات من الصور نفسها: لقطةٌ أُعيد التقاطها قد تختلف ببكسل أو اثنين
  await Promise.all(Object.values(IMG).map(async I => { const im = new Image(); im.src = I.src; await im.decode(); I.w = im.naturalWidth; I.h = im.naturalHeight; }));
  const ic = new Image(); ic.src = VIDEO.icon; await ic.decode();
  await Promise.all([...document.images].map(im => im.src ? im.decode().catch(() => {}) : 0));
  await document.fonts.load('700 44px "IBM Plex Sans Arabic"'); await document.fonts.load('400 33px "IBM Plex Sans Arabic"');
  await document.fonts.ready;
  return TOTAL;
}

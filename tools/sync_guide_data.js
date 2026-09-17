// يستخرج كائن DEVICES من index.html إلى static/guide-data.json
// وهو المصدر الذي تبني منه صفحات الأجهزة الثابتة (guide_pages.py).
// شغّله بعد أي تعديل على خطوات المعالج في index.html:
//     node tools/sync_guide_data.js
const fs = require("fs"), path = require("path");

const root = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");

const starts = ["ICONS", "WA", "CREDS", "DEVICES"]
  .map((n) => html.indexOf(`const ${n}`))
  .filter((i) => i >= 0);
if (!starts.length) throw new Error("لم أجد تعريفات الثوابت في index.html");

const end = html.indexOf("const state");
if (end < 0) throw new Error("لم أجد نهاية الكتلة (const state) في index.html");

const block = html.slice(Math.min(...starts), end);
const DEVICES = new Function(`${block}; return DEVICES;`)();

const out = path.join(root, "static", "guide-data.json");
fs.writeFileSync(out, JSON.stringify(DEVICES, null, 1) + "\n", "utf8");

const steps = Object.values(DEVICES).reduce(
  (n, d) => n + (d.steps ? d.steps.length : Object.values(d.variants).reduce((m, v) => m + v.length, 0)), 0);
console.log(`✓ ${out}\n  ${Object.keys(DEVICES).length} أجهزة · ${steps} خطوة`);

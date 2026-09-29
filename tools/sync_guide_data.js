// يستخرج كائن DEVICES من index.html إلى static/guide-data.json
// وهو المصدر الذي تبني منه صفحات الأجهزة الثابتة (guide_pages.py).
// شغّله بعد أي تعديل على خطوات المعالج في index.html:
//     node tools/sync_guide_data.js
// و --check يقول هل الملف على آخر المعالج بلا كتابة (للاختبارات):
//     node tools/sync_guide_data.js --check
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
const text = JSON.stringify(DEVICES, null, 1) + "\n";
if (process.argv.includes("--check")) {
  const same = fs.existsSync(out) && fs.readFileSync(out, "utf8") === text;
  console.log(same ? "✓ guide-data.json على آخر المعالج"
                   : "✗ guide-data.json أقدم من index.html — شغّل: node tools/sync_guide_data.js");
  process.exit(same ? 0 : 1);
}
fs.writeFileSync(out, text, "utf8");

const steps = Object.values(DEVICES).reduce(
  (n, d) => n + (d.steps ? d.steps.length : Object.values(d.variants).reduce((m, v) => m + v.length, 0)), 0);
console.log(`✓ ${out}\n  ${Object.keys(DEVICES).length} أجهزة · ${steps} خطوة`);

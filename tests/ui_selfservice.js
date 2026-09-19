// Browser test: a login-only person adds their OWN gate via "إدارة بواباتي".
const { chromium } = require('playwright-core');
const { spawn, execSync } = require('child_process');
const path = require('path'); const fs = require('fs'); const os = require('os');
const ROOT = '/home/user/ssouq-guide';
const PANEL_PORT = 9388, APP_PORT = 9389;
const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'selfsvc_'));
const EXE = execSync("ls -d /opt/pw-browsers/chromium*/chrome-linux/chrome 2>/dev/null | head -1").toString().trim();
let pass=0, fail=0;
const check=(l,c,x='')=>{ c?(pass++,console.log(`  PASS  ${l}${x?'  ('+x+')':''}`)):(fail++,console.log(`  FAIL  ${l}${x?'  ('+x+')':''}`)); };
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function up(u){ for(let i=0;i<80;i++){ try{execSync(`curl -s -o /dev/null ${u}`);return;}catch(e){} await sleep(150);} }
(async()=>{
  const panel=spawn('python3',[path.join(ROOT,'tests/mock_panel.py'),String(PANEL_PORT),'demo','secret'],{stdio:'ignore'});
  const app=spawn('python3',[path.join(ROOT,'xm_lines.py'),'web'],{stdio:'ignore',env:{...process.env,XM_DATA:dataDir,XM_BIND:'127.0.0.1',XM_PORT:String(APP_PORT)}});
  await up(`http://127.0.0.1:${PANEL_PORT}/token.php`); await up(`http://127.0.0.1:${APP_PORT}/admin/login`);
  const browser=await chromium.launch({executablePath:EXE,args:['--no-sandbox']});
  const page=await (await browser.newContext()).newPage();
  const APP=`http://127.0.0.1:${APP_PORT}`, PANEL=`http://127.0.0.1:${PANEL_PORT}`;
  try{
    await page.goto(APP+'/admin/setup');
    await page.evaluate(async()=>fetch('/admin/api/setup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:'admin123'})}));
    // admin creates a LOGIN-ONLY person (no gates)
    let r=await page.evaluate(async()=>(await fetch('/admin/api/accounts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'Ok',user:'Ok',password:'998661',gates:[]})})).json());
    check('login-only person created', r.ok===true && r.accounts.find(a=>a.user==='Ok').gates.length===0);
    await page.evaluate(async()=>fetch('/admin/logout'));
    r=await page.evaluate(async()=>(await fetch('/admin/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user:'Ok',password:'998661'})})).json());
    check('person login', r.role==='account');

    await page.goto(APP+'/admin');
    await page.waitForSelector('#gateTabs', {timeout:5000});
    check('empty-gates prompt shown', (await page.textContent('#gateTabs')).includes('إدارة بواباتي'));

    // open manage, add a gate
    await page.click('#manageGates');
    await page.waitForSelector('#gatesManage:not([hidden])');
    await page.click('#addMyGate');
    await page.waitForSelector('#gateEditor:not([hidden])');
    await page.fill('#g_name','بوابة مرح');
    await page.selectOption('#g_mode','web');
    await page.fill('#g_panel_base', PANEL);
    await page.fill('#g_panel_user','demo');
    await page.fill('#g_panel_pass','secret');
    await page.fill('#g_host','http://mrha.ink');
    await page.fill('#g_guide','https://guide.ssouq.com/');
    await page.click('#saveGate');
    await page.waitForFunction(()=>document.querySelectorAll('#myGatesList .item').length>=1,{timeout:6000});
    check('gate appears in my-gates list', (await page.textContent('#myGatesList')).includes('بوابة مرح'));
    // a gate tab now exists
    await page.waitForSelector('.gate-tab',{timeout:6000});
    check('new gate shows as a tab', (await page.$$eval('.gate-tab',e=>e.map(x=>x.textContent))).includes('بوبة مرح') || (await page.textContent('#gateTabs')).includes('بوابة مرح'));

    // data encrypted at rest
    const raw=fs.readFileSync(path.join(dataDir,'accounts.json'),'utf8');
    check('panel pass + tool pass encrypted on disk', !raw.includes('secret') && !raw.includes('998661') && raw.includes('enc:1:'));
  }catch(e){ fail++; console.log('  FAIL exception:',e.message); }
  finally{ await browser.close(); panel.kill(); app.kill(); fs.rmSync(dataDir,{recursive:true,force:true}); }
  console.log(`\nResult: ${pass} passed, ${fail} failed`); process.exit(fail?1:0);
})();

// خدمة إرسال واتساب عبر Baileys لأداة Guide (تسليم اشتراكات سلة على واتساب).
//
// تربط رقم واتساب واحدًا بمسح رمز QR (تُحفظ الجلسة على القرص فتبقى بين النشرات)،
// ثم تعرض واجهة HTTP بسيطة تستدعيها أداة Guide عبر قناة "بوابة HTTP خاصة":
//   GET  /health              → صحّة الخدمة (بلا مصادقة)
//   GET  /            (?key=) → صفحة مسح رمز QR للربط
//   GET  /status      (?key=) → {connected, me, hasQR, inbound}
//   GET  /qr          (?key=) → {connected, qr}   (qr = صورة data-URL)
//   POST /send    (Bearer)    → {to, text} → يرسل، ويرجّع {ok, id}
//   POST /logout  (Bearer)    → يفصل الجلسة لإعادة الربط
//
// والرسائل الواردة: رسالة توقّعٍ من مسابقة التوقّعات («رمز التوقّع: XXXXXX») تُمرَّر إلى
// WA_INBOUND_URL (‏/api/contest/wa-inbound في أداة Guide) برقم مرسلها ووقتها من خادم واتساب،
// ويُرسل ردّها للمرسل. وما عداها من رسائل العملاء لا يُمرَّر ولا يُردّ عليه.
//
// المصادقة بمتغيّر البيئة WA_SECRET (Bearer للـ POST، أو ?key= لصفحات GET)، وبه نفسه تُوقَّع
// الرسائل الممرَّرة. WA_FAKE=1 يشغّل الخدمة بمُرسِل وهمي (بلا واتساب) لاختبار الواجهة والتكامل،
// ومعه POST /fake-inbound {from, text, name, ts} يحاكي رسالةً واردة.
//
// تنويه: Baileys غير رسمي وقد يُعرّض الرقم للحظر — استعمله برقم عمليات مخصّص.

import http from 'http';
import { URL } from 'url';

const PORT = parseInt(process.env.WA_PORT || '80', 10);
const HOST = process.env.WA_BIND || '0.0.0.0';
const SECRET = (process.env.WA_SECRET || '').trim();
const AUTH_DIR = process.env.WA_AUTH_DIR || './auth';
const FAKE = !!process.env.WA_FAKE;
const INBOUND = (process.env.WA_INBOUND_URL || '').trim();   // أين تُمرَّر رسائل التوقّعات

const state = { connected: false, me: '', qr: null };   // qr = صورة data-URL
let sendImpl = async () => { throw new Error('واتساب غير متصل'); };
export const __sent = [];                                // لأغراض الاختبار (WA_FAKE)


// ---------- الرسائل الواردة: مسابقة التوقّعات ----------
// العلامة بلا تشكيل: «رمز التوقّع» مكتوبة في الرسالة الجاهزة، ولا يُمرَّر غيرها
const MARK = /رمز\s*التوقع/;
const plain = (t) => String(t || '').replace(/[\u064B-\u065F\u0670\u0640]/g, '');
const seen = new Set();                                  // معرّفات ما مُرِّر (رسالةٌ تصل مرتين تُمرَّر مرة)

function textOf(m) {
  const x = (m && m.message) || {};
  const inner = (x.ephemeralMessage && x.ephemeralMessage.message) ||
    (x.viewOnceMessage && x.viewOnceMessage.message) || (x.viewOnceMessageV2 && x.viewOnceMessageV2.message) || x;
  return inner.conversation || (inner.extendedTextMessage && inner.extendedTextMessage.text) || '';
}

// رقم المرسل: من remoteJid إن كان رقمًا، أو من senderPn حين يصل المرسل بمعرّف LID
function phoneOf(key) {
  for (const j of [key.senderPn, key.remoteJid]) {
    if (j && /@s\.whatsapp\.net$/.test(j)) return j.split('@')[0].split(':')[0];
  }
  return '';
}

function secondsOf(t) {
  if (typeof t === 'number') return t;
  if (t && typeof t.toNumber === 'function') return t.toNumber();
  return Number(t) || 0;
}

export async function handleInbound(msg, reply) {
  if (!INBOUND || !MARK.test(plain(msg.text))) return { forwarded: false };
  if (msg.id) {
    if (seen.has(msg.id)) return { forwarded: false, repeat: true };
    seen.add(msg.id);
    if (seen.size > 5000) seen.delete(seen.values().next().value);
  }
  let d = {};
  try {
    const r = await fetch(INBOUND, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + SECRET },
      body: JSON.stringify({ from: msg.from, text: msg.text, name: msg.name, id: msg.id, ts: msg.ts }),
      signal: AbortSignal.timeout(15000),
    });
    d = await r.json().catch(() => ({}));
    if (!r.ok) return { forwarded: true, status: r.status, error: d.error || '' };
  } catch (e) {
    console.error('inbound error', (e && e.message) || e);
    if (msg.id) seen.delete(msg.id);                     // تُعاد إن وصلت ثانيةً
    return { forwarded: false, error: String((e && e.message) || e) };
  }
  if (d.reply) {
    try { await reply(String(d.reply)); } catch (e) { console.error('reply error', (e && e.message) || e); }
  }
  return { forwarded: true, status: 200, reply: d.reply || '' };
}


async function startBaileys() {
  const baileys = await import('@whiskeysockets/baileys');
  const makeWASocket = baileys.default || baileys.makeWASocket;
  const { useMultiFileAuthState, fetchLatestBaileysVersion, DisconnectReason } = baileys;
  const pino = (await import('pino')).default;
  const QR = (await import('qrcode')).default;

  const { state: auth, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const { version } = await fetchLatestBaileysVersion();
  const logger = pino({ level: 'silent' });

  const start = () => {
    const sock = makeWASocket({
      version, auth, logger, printQRInTerminal: false,
      browser: ['ssouq-guide', 'Chrome', '1.0'],
    });
    sock.ev.on('creds.update', saveCreds);
    sock.ev.on('connection.update', async (u) => {
      const { connection, lastDisconnect, qr } = u;
      if (qr) { try { state.qr = await QR.toDataURL(qr); } catch { state.qr = null; } state.connected = false; }
      if (connection === 'open') {
        state.connected = true; state.qr = null;
        state.me = ((sock.user && sock.user.id) || '').split(':')[0];
      }
      if (connection === 'close') {
        state.connected = false;
        const code = lastDisconnect && lastDisconnect.error &&
          lastDisconnect.error.output && lastDisconnect.error.output.statusCode;
        if (code !== DisconnectReason.loggedOut) setTimeout(start, 2500);
        else { state.me = ''; state.qr = null; }
      }
    });
    sendImpl = async (to, text) => {
      const jid = String(to).replace(/\D/g, '') + '@s.whatsapp.net';
      const r = await sock.sendMessage(jid, { text: String(text) });
      return (r && r.key && r.key.id) || '';
    };
    sock.ev.on('messages.upsert', async ({ messages }) => {
      for (const m of messages || []) {
        const k = m.key || {}, jid = k.remoteJid || '';
        if (k.fromMe || !jid || /@(g\.us|broadcast|newsletter)$/.test(jid)) continue;
        const text = textOf(m);
        if (!text) continue;
        await handleInbound({ from: phoneOf(k), text, name: m.pushName || '', id: k.id || '', ts: secondsOf(m.messageTimestamp) },
                            (t) => sock.sendMessage(jid, { text: t }));
      }
    });
  };
  start();
}

function startFake() {
  state.connected = true; state.me = (process.env.WA_FAKE_ME || '').trim() || 'FAKE';
  sendImpl = async (to, text) => { __sent.push({ to, text }); return 'FAKE-' + __sent.length; };
}


function authed(req, url) {
  if (!SECRET) return true;   // بلا سرّ = مفتوح (غير مستحسن للإنتاج)
  const h = req.headers['authorization'] || '';
  const bearer = h.startsWith('Bearer ') ? h.slice(7) : '';
  const key = url.searchParams.get('key') || '';
  return bearer === SECRET || key === SECRET;
}

function json(res, code, obj) {
  const b = Buffer.from(JSON.stringify(obj));
  res.writeHead(code, { 'Content-Type': 'application/json', 'Content-Length': b.length });
  res.end(b);
}

const LINK_PAGE = (key) => `<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>ربط واتساب</title></head>
<body style="font-family:system-ui,Tahoma;background:#0e1a26;color:#e3ecf5;text-align:center;padding:24px;margin:0">
<h2>ربط رقم واتساب</h2>
<div id="s" style="font-size:1.1rem;margin:12px 0">…</div>
<img id="q" alt="QR" style="width:280px;max-width:80vw;background:#fff;border-radius:14px;padding:10px;display:none">
<p style="color:#8fa3b8;max-width:340px;margin:14px auto">في واتساب: <b>الإعدادات ← الأجهزة المرتبطة ← ربط جهاز</b>، ثم امسح الرمز.</p>
<script>
const key=${JSON.stringify(key)};
async function tick(){try{
  const r=await fetch('/qr?key='+encodeURIComponent(key)); const d=await r.json();
  const s=document.getElementById('s'), q=document.getElementById('q');
  if(d.connected){s.textContent='متصل ✅'; q.style.display='none';}
  else if(d.qr){s.textContent='امسح الرمز بهاتفك'; q.src=d.qr; q.style.display='inline-block';}
  else{s.textContent='بانتظار الرمز…';}
}catch(e){}}
tick(); setInterval(tick,3000);
</script></body></html>`;

const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://x');
  const p = url.pathname;

  if (p === '/health') return json(res, 200, { ok: true, connected: state.connected });
  if (!authed(req, url)) return json(res, 401, { ok: false, error: 'unauthorized' });

  if (req.method === 'GET' && p === '/status')
    return json(res, 200, { connected: state.connected, me: state.me, hasQR: !!state.qr, inbound: !!INBOUND });
  if (req.method === 'GET' && p === '/qr')
    return json(res, 200, { connected: state.connected, qr: state.qr });
  if (req.method === 'GET' && (p === '/' || p === '/link')) {
    const body = LINK_PAGE(url.searchParams.get('key') || '');
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    return res.end(body);
  }
  if (req.method === 'POST' && p === '/send') {
    let raw = '';
    req.on('data', (c) => { raw += c; if (raw.length > 1e6) req.destroy(); });
    req.on('end', async () => {
      let o = {};
      try { o = JSON.parse(raw || '{}'); } catch { return json(res, 400, { ok: false, error: 'bad json' }); }
      const to = String(o.to || '').replace(/\D/g, '');
      const text = String(o.text || '');
      if (!to || !text) return json(res, 400, { ok: false, error: 'to/text required' });
      if (!state.connected) return json(res, 503, { ok: false, error: 'واتساب غير متصل — امسح الرمز أولًا' });
      try { const id = await sendImpl(to, text); json(res, 200, { ok: true, id }); }
      catch (e) { json(res, 502, { ok: false, error: String((e && e.message) || e) }); }
    });
    return;
  }
  if (req.method === 'POST' && p === '/fake-inbound' && FAKE) {   // يحاكي رسالةً واردة (اختبار فقط)
    let raw = '';
    req.on('data', (c) => { raw += c; if (raw.length > 1e5) req.destroy(); });
    req.on('end', async () => {
      let o = {};
      try { o = JSON.parse(raw || '{}'); } catch { return json(res, 400, { ok: false, error: 'bad json' }); }
      const from = String(o.from || '').replace(/\D/g, ''), before = __sent.length;
      const out = await handleInbound({ from, text: String(o.text || ''), name: String(o.name || ''),
                                        id: String(o.id || ''), ts: Number(o.ts) || Math.floor(Date.now() / 1000) },
                                      (t) => sendImpl(from, t));
      json(res, 200, { ok: true, ...out, sent: __sent.slice(before) });
    });
    return;
  }
  if (req.method === 'POST' && p === '/logout') {
    (async () => {
      try { const fs = await import('fs'); fs.rmSync(AUTH_DIR, { recursive: true, force: true }); } catch {}
      state.connected = false; state.me = ''; state.qr = null;
      if (!FAKE) startBaileys().catch((e) => console.error('relink error', e));
      json(res, 200, { ok: true });
    })();
    return;
  }
  return json(res, 404, { ok: false, error: 'not found' });
});

if (FAKE) startFake();
else startBaileys().catch((e) => console.error('baileys start error', e));

server.listen(PORT, HOST, () => console.log('wa-baileys on ' + HOST + ':' + PORT + (FAKE ? ' (FAKE)' : '')));

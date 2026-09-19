/**
 * مرسل واتساب — صفحة التجديدات في guide.ssouq.com
 * ================================================
 * جلسة واحدة تُربط بمسح QR، وطابور يرسل رسالة كل ٤٥–١٢٠ ثانية عشوائيًا بسقف
 * يومي. هذا ليس تزيينًا: الإرسال المتلاحق من رقم عادي هو ما يُحظر عليه.
 *
 * المسارات:
 *   GET  /?k=<WA_TOKEN>   صفحة الحالة والربط (QR) — المفتاح إلزامي: من يفتحها
 *                        لحظة الربط يستطيع مسح الرمز وسرقة الجلسة.
 *   GET  /status?k=...    JSON: متصل؟ رقمه؟ طول الطابور؟ المُرسل اليوم؟
 *   GET  /health          نبضة للمراقبة — بلا أي بيانات
 *   POST /send        { phone, text }        ← تناديه صفحة التجديدات
 *   POST /test        { phone }              ← رسالة تجريبية إليك
 *   GET  /optout      قائمة من ردّ بكلمة إيقاف
 *   POST /logout      فصل الجلسة (يتطلب مسح QR من جديد)
 * والباقي يتطلب: Authorization: Bearer <WA_TOKEN>
 */
import express from 'express';
import pino from 'pino';
import QR from 'qrcode';
import fs from 'node:fs';
import path from 'node:path';
import { Boom } from '@hapi/boom';
import makeWASocket, {
    DisconnectReason, fetchLatestBaileysVersion, useMultiFileAuthState,
} from 'baileys';

const PORT      = Number(process.env.PORT || 8081);
const DATA_DIR  = process.env.DATA_DIR || './data';
const TOKEN     = process.env.WA_TOKEN || '';
const CAP       = Number(process.env.DAILY_CAP || 80);      // سقف الرسائل اليومي
const GAP_MIN   = Number(process.env.GAP_MIN || 45);        // أقل فاصل بالثواني
const GAP_MAX   = Number(process.env.GAP_MAX || 120);       // أعلى فاصل
const WARMUP    = Number(process.env.WARMUP_DAYS || 0);     // تحضين: يوم ١ = ١٠٪ من السقف
const STOP_WORDS = ['ايقاف', 'إيقاف', 'الغاء', 'إلغاء', 'stop', 'unsubscribe', 'لا تراسلني'];

const log = pino({ level: process.env.LOG_LEVEL || 'info' });
const AUTH_DIR = path.join(DATA_DIR, 'auth');
const STATE_FILE = path.join(DATA_DIR, 'sender.json');
fs.mkdirSync(AUTH_DIR, { recursive: true });

// ───────── الحالة على القرص ─────────
const today = () => new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Riyadh' });
function loadState() {
    try { return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8')); }
    catch { return { day: today(), sentToday: 0, optout: [], log: [], firstDay: today() }; }
}
function saveState(s) {
    fs.mkdirSync(DATA_DIR, { recursive: true });
    fs.writeFileSync(STATE_FILE + '.tmp', JSON.stringify(s, null, 1));
    fs.renameSync(STATE_FILE + '.tmp', STATE_FILE);
}
let S = loadState();
function rollDay() {
    if (S.day !== today()) { S.day = today(); S.sentToday = 0; saveState(S); }
}
/** السقف الفعلي اليوم — يرتفع تدريجيًا في أيام التحضين. */
function capToday() {
    rollDay();
    if (!WARMUP) return CAP;
    const days = Math.floor((Date.parse(S.day) - Date.parse(S.firstDay || S.day)) / 86400000) + 1;
    if (days >= WARMUP) return CAP;
    return Math.max(5, Math.round(CAP * (days / WARMUP)));
}

// ───────── الجلسة ─────────
const session = { sock: null, status: 'starting', qr: null, qrPng: null, me: null, stop: false };

async function connect() {
    const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
    const { version } = await fetchLatestBaileysVersion();
    const sock = makeWASocket({
        version, auth: state, printQRInTerminal: false,
        logger: pino({ level: 'silent' }),
        browser: ['Ssouq Renewals', 'Chrome', '1.0.0'],
        syncFullHistory: false,
        markOnlineOnConnect: false,      // لا تُظهر الرقم "متصل" دائمًا
    });
    session.sock = sock;
    session.status = 'connecting';

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', async (u) => {
        if (u.qr) {
            session.qr = u.qr;
            session.qrPng = await QR.toDataURL(u.qr, { margin: 1, width: 300 }).catch(() => null);
            session.status = 'qr';
            log.info('امسح رمز QR من الصفحة لربط الرقم');
        }
        if (u.connection === 'open') {
            session.status = 'open';
            session.qr = session.qrPng = null;
            session.me = (sock.user?.id || '').split(':')[0].split('@')[0];
            log.info({ me: session.me }, 'الرقم مرتبط');
        }
        if (u.connection === 'close') {
            const code = new Boom(u.lastDisconnect?.error)?.output?.statusCode;
            const loggedOut = code === DisconnectReason.loggedOut;
            session.status = loggedOut ? 'logged_out' : 'closed';
            log.warn({ code, loggedOut }, 'انقطع الاتصال');
            if (loggedOut) { fs.rmSync(AUTH_DIR, { recursive: true, force: true }); fs.mkdirSync(AUTH_DIR, { recursive: true }); }
            if (!session.stop) setTimeout(connect, loggedOut ? 2000 : 5000);
        }
    });

    // ردّ العميل بكلمة إيقاف ← لا نراسله بعدها أبدًا
    sock.ev.on('messages.upsert', ({ messages, type }) => {
        if (type !== 'notify') return;
        for (const m of messages) {
            if (m.key.fromMe) continue;
            const jid = m.key.remoteJid || '';
            if (!jid.endsWith('@s.whatsapp.net')) continue;
            const t = (m.message?.conversation || m.message?.extendedTextMessage?.text || '')
                .trim().toLowerCase();
            if (!t) continue;
            if (STOP_WORDS.some((w) => t === w || t.startsWith(w))) {
                const phone = jid.split('@')[0];
                if (!S.optout.includes(phone)) {
                    S.optout.push(phone); saveState(S);
                    log.info({ phone }, 'أُضيف إلى قائمة الإيقاف بناءً على رده');
                    sock.sendMessage(jid, { text: 'تم. لن تصلك رسائل تجديد بعد الآن. شكرًا لك 🌿' })
                        .catch(() => {});
                }
            }
        }
    });
}

// ───────── الطابور ─────────
const queue = [];
let draining = false;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const gap = () => (GAP_MIN + Math.random() * Math.max(0, GAP_MAX - GAP_MIN)) * 1000;

function normalize(p) {
    let d = String(p || '').replace(/\D/g, '');
    if (d.startsWith('00')) d = d.slice(2);
    if (d.startsWith('05')) d = '966' + d.slice(1);
    else if (d.length === 9 && d.startsWith('5')) d = '966' + d;
    return d;
}

async function drain() {
    if (draining) return;
    draining = true;
    while (queue.length) {
        if (session.status !== 'open') { await sleep(5000); continue; }
        rollDay();
        if (S.sentToday >= capToday()) {
            log.warn({ cap: capToday() }, 'بلغ السقف اليومي — يتوقف حتى الغد');
            await sleep(60000); continue;
        }
        const job = queue.shift();
        try {
            let jid = `${job.phone}@s.whatsapp.net`;
            const [found] = await session.sock.onWhatsApp(job.phone).catch(() => []);
            if (found?.exists && found.jid) jid = found.jid;
            else if (found && !found.exists) throw new Error('الرقم ليس على واتساب');
            await session.sock.sendMessage(jid, { text: job.text });
            S.sentToday += 1;
            S.log.unshift({ phone: job.phone, at: new Date().toISOString(), ok: true });
            job.resolve?.({ ok: true });
            log.info({ phone: job.phone, sentToday: S.sentToday }, 'أُرسلت');
        } catch (e) {
            S.log.unshift({ phone: job.phone, at: new Date().toISOString(), ok: false, err: String(e?.message || e) });
            job.resolve?.({ ok: false, error: String(e?.message || e) });
            log.error({ phone: job.phone, err: String(e) }, 'فشل الإرسال');
        }
        S.log = S.log.slice(0, 500);
        saveState(S);
        if (queue.length) await sleep(gap());
    }
    draining = false;
}

// ───────── الواجهة ─────────
const app = express();
app.use(express.json({ limit: '256kb' }));

const auth = (req, res, next) => {
    if (!TOKEN) return res.status(500).json({ error: 'WA_TOKEN غير مضبوط في الخدمة' });
    const h = req.headers.authorization || '';
    if (h !== `Bearer ${TOKEN}`) return res.status(401).json({ error: 'مفتاح غير صحيح' });
    next();
};

/** المفتاح من الترويسة أو من ?k= — الصفحة تُفتح من المتصفح فلا ترويسة فيها. */
const keyed = (req, res, next) => {
    if (!TOKEN) return res.status(500).type('text/plain').send('WA_TOKEN غير مضبوط في الخدمة');
    const k = req.query.k || (req.headers.authorization || '').replace(/^Bearer /, '');
    if (k !== TOKEN) return res.status(401).type('text/plain').send('مفتاح غير صحيح');
    next();
};

app.get('/health', (req, res) => res.json({ up: true }));

app.get('/status', keyed, (req, res) => {
    rollDay();
    res.json({ status: session.status, me: session.me, queue: queue.length,
               sentToday: S.sentToday, cap: capToday(), optout: S.optout.length });
});

app.get('/', keyed, (req, res) => {
    rollDay();
    const st = { starting: 'يبدأ…', connecting: 'يتصل…', qr: 'بانتظار مسح الرمز',
                 open: 'مرتبط ويعمل', closed: 'منقطع — يعيد المحاولة',
                 logged_out: 'فُصل — امسح الرمز من جديد' }[session.status] || session.status;
    const body = session.qrPng
        ? `<p class=lead>افتح واتساب في جوالك ← الإعدادات ← الأجهزة المرتبطة ← ربط جهاز، وامسح:</p>
           <img class=qr src="${session.qrPng}" alt="QR"><p class=note>يتجدد الرمز تلقائيًا — حدّث الصفحة إن انتهى.</p>`
        : session.status === 'open'
            ? `<p class=ok>الرقم <b dir=ltr>${session.me || '—'}</b> مرتبط.</p>
               <p class=note>المُرسل اليوم ${S.sentToday} من ${capToday()} · في الطابور ${queue.length} · أوقفوا الرسائل ${S.optout.length}</p>`
            : `<p class=note>الحالة: ${st}</p>`;
    res.type('html').send(`<!doctype html><html lang=ar dir=rtl><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>مرسل واتساب — سمارت سوق</title>
<meta name=robots content="noindex,nofollow"><meta http-equiv=refresh content=20>
<style>body{margin:0;background:#EFF5FA;color:#14283A;font:16px/1.7 system-ui,Tahoma,sans-serif}
@media(prefers-color-scheme:dark){body{background:#0B1826;color:#E3ECF5}.card{background:#132433!important;border-color:#25405A!important}}
main{max-width:460px;margin:0 auto;padding:30px 16px}.card{background:#fff;border:1px solid #DCE6EF;border-radius:16px;padding:24px;text-align:center}
h1{font-size:1.25rem;margin:0 0 4px}.lead{color:#5C7288;font-size:.92rem}.note{color:#5C7288;font-size:.85rem}
.ok{color:#1DA851;font-weight:700}.qr{width:260px;height:260px;border-radius:12px;background:#fff;padding:8px}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-inline-end:6px;background:${session.status === 'open' ? '#1DA851' : '#F0A12B'}}
</style></head><body><main><div class=card><h1><span class=dot></span>مرسل واتساب</h1>
<p class=lead>${st}</p>${body}</div></main></body></html>`);
});

app.post('/send', auth, async (req, res) => {
    const phone = normalize(req.body?.phone);
    const text = String(req.body?.text || '').trim();
    if (!phone || phone.length < 10) return res.status(400).json({ error: 'رقم غير صالح' });
    if (!text) return res.status(400).json({ error: 'نص فارغ' });
    if (S.optout.includes(phone)) return res.status(409).json({ error: 'هذا الرقم طلب الإيقاف' });
    rollDay();
    if (S.sentToday + queue.length >= capToday())
        return res.status(429).json({ error: `بلغت السقف اليومي (${capToday()})`, sentToday: S.sentToday });
    queue.push({ phone, text });
    drain();
    res.json({ queued: true, position: queue.length, sentToday: S.sentToday, cap: capToday() });
});

app.post('/test', auth, async (req, res) => {
    const phone = normalize(req.body?.phone);
    if (!phone) return res.status(400).json({ error: 'اكتب رقمًا' });
    if (session.status !== 'open') return res.status(503).json({ error: 'الرقم غير مرتبط بعد — امسح QR أولًا' });
    const text = 'رسالة تجريبية من سمارت سوق ✅\nمرسل التجديدات يعمل، والربط سليم.';
    const done = await new Promise((resolve) => { queue.unshift({ phone, text, resolve }); drain(); });
    res.status(done.ok ? 200 : 502).json(done);
});

app.get('/optout', auth, (req, res) => res.json({ optout: S.optout }));
app.get('/log', auth, (req, res) => res.json({ log: S.log.slice(0, 100) }));
app.post('/logout', auth, async (req, res) => {
    try { await session.sock?.logout(); } catch { /* الجلسة قد تكون منقطعة أصلًا */ }
    res.json({ ok: true });
});

app.listen(PORT, () => log.info({ port: PORT }, 'مرسل واتساب يعمل'));
connect().catch((e) => log.error({ err: String(e) }, 'تعذّر بدء الجلسة'));

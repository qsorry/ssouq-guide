// Souq WhatsApp reader — the always-on service behind فواتير واتساب.
//
// It holds one WhatsApp (Baileys) session PER SESSION KEY, links each to a
// dedicated number via QR or an 8-char pairing code, reads the chosen
// "Invoice" group, and forwards every new message to that business's ingest
// endpoint. It runs as its OWN container next to the Laravel app, so the main
// image is never touched.
//
// The `tenant` key is an OPAQUE string chosen by Laravel: a business's Invoice
// session is keyed by its tenant id, and its OPERATIONS channel (the delay
// chases and escalations on a second number) by `{tenant}--ops` — nothing in
// this service treats the two differently; an ops session simply has no
// chatId, so only its direct (1:1) traffic flows.
//
// Laravel → reader (this service), authenticated with the shared reader secret:
//   POST   /sessions            {tenant, number, callbackUrl, ingestToken, chatId?,
//          historySince?} — historySince (unix seconds, 0 = from the beginning,
//          null/absent = off) turns on the pairing history backfill (تاريخ السحب)
//   GET    /sessions/:tenant     → live status snapshot
//   PATCH  /sessions/:tenant     {chatId?, historySince?, callbackUrl?, chatRoutes?} — point
//          at the ingested group / update the backfill boundary / re-point the
//          group-ingest callback (the ops session's متابعة البدء group).
//          chatId must be a GROUP jid (or '' to clear) — a private chat is
//          refused with 422 not_a_group (v29)
//   POST   /sessions/:tenant/backfill {since} — سحب العمليات: pull the group's
//          past messages from `since` (unix seconds) without re-linking the
//          number; operations already pulled are skipped
//   POST   /sessions/:tenant/forget {ids} — drop message ids from the pulled-ids
//          memory (deleted operations become re-pullable)
//   GET    /sessions/:tenant/forwarded — the pulled-ids memory itself, so
//          Laravel can sweep ids it no longer knows before a pull
//   POST   /sessions/:tenant/send {to, body, dmCallbackUrl?, mentions?} — send a text
//          message from the business's own number (the delay-chase messages);
//          dmCallbackUrl, when given, is persisted so direct replies forward.
//   DELETE /sessions/:tenant     — log out + wipe credentials
//
// reader → Laravel (per business), authenticated with that business's ingest
// token in X-Reader-Token:
//   POST {callbackUrl}  {wa_message_id, chat_id, chat_name, sender_number,
//                        sender_name, sent_at, body, media_base64?, media_mime?}
//   POST {dmCallbackUrl} {wa_message_id, sender_number, sender_name, sent_at,
//                         body} — a DIRECT (1:1) message someone sent to the
//                         business's number, e.g. a rider replying to a chase.
//
// Credentials + a small meta.json are persisted per tenant under DATA_DIR (a
// mounted volume), so a restart reconnects every session and resumes forwarding
// with no re-scan.

import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statfsSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join } from 'node:path';

// `baileys` is the maintained successor of `@whiskeysockets/baileys` — the
// abandoned 6.7.9 build predates WhatsApp's LID addressing, and its sends were
// silently DROPPED by the server (a message id came back, nothing arrived
// anywhere, not even the sender's own phone). The current 6.7.x line carries
// the LID-era fixes with the same API.
import { Boom } from '@hapi/boom';
import {
    default as makeWASocket,
    DisconnectReason,
    downloadMediaMessage,
    fetchLatestBaileysVersion,
    useMultiFileAuthState,
} from 'baileys';
import express from 'express';
import pino from 'pino';
import qrcode from 'qrcode';

// Reported in every snapshot so the app can tell a stale container from a
// current one (verified sends + delivery receipts need this version or later).
// Bump when the reader's capabilities change. 3 = the baileys upgrade (LID
// addressing — sends before it were silently dropped by WhatsApp's server);
// 4 = baileys 7.0.0-rc13 (the full LID rewrite — 6.7.23 still had its sends
// dropped on this account even after a fresh pairing);
// 5 = re-entrant sessions (a stuck 'connecting' can be restarted safely),
// history backfill (تاريخ السحب), the lastForwardedAt heartbeat, and the
// receipt/reply plumbing rebuilt against the actual rc13 API (LID→phone
// resolution for replies, receipt listeners on both events, ack/reply logging);
// 6 = QR-only pairing (rc13's requestPairingCode poisons creds mid-QR) and the
// unregistered-creds sweep so a fresh QR always appears;
// 7 = the sweep spares a fresh QR pairing (account set, registered not yet) —
// v6 deleted it during WhatsApp's forced post-scan restart, so linking hung;
// 8 = reply-liveness diagnostics (lastDmSeenAt/lastDmDrop in the snapshot —
// the settings popup names the exact stage where a rider's reply died);
// 9 = /send accepts full jids (…@g.us) for the escalation group posts;
// 15 = POST /sessions accepts dmCallbackUrl (connect-time reply seeding — the
// operations `--ops` sessions have no group-save knob to re-seed it later);
// 16 = an explicit empty dmCallbackUrl CLEARS the stored one (the Invoice
// session forwards no direct replies after the invoice/operations hard split);
// 17 = تاريخ السحب on demand: POST /sessions/:tenant/backfill asks WhatsApp for
// the group's older messages without re-linking the number, and every group
// message id already forwarded is remembered so a replay SKIPS it before its
// media is downloaded (مضاف من قبل = لا يُسحب مرة أخرى);
// 18 = /send accepts `mentions` (bare phone digits) — the rider-points group
// alerts @-tag chosen members so the message pings them, not just the group;
// 19 = POST /sessions/:tenant/forget drops given ids from that pulled-ids
// memory — Laravel calls it when operations are DELETED, so the next pull
// re-forwards them (deletion frees a re-pull; Laravel's ingest stays the
// authority and still answers "duplicate" for money already posted);
// 20 = متابعة البدء: PATCH /sessions/:tenant accepts callbackUrl (the ops
// session gains a group + its own ingest URL after connect), the ingest
// answer's `react` emoji is sent as a reaction to the forwarded message (the
// "Start" 👍🏽), and a group sender's PHONE is resolved through the LID
// mapping like direct chats (LID-era groups hide it from the participant jid);
// 21 = GET /sessions/:tenant/forwarded exposes that memory, so the pull can
// SELF-HEAL past deletions: Laravel diffs the remembered ids against its own
// records and forgets the ones it no longer knows — operations deleted before
// the forget hook existed become re-pullable with one press of the pull.
// Plus the LOCAL ARCHIVE: forwarded operations are persisted (bounded) and a
// pull re-sends deleted ones from disk FIRST — deterministic, instant, no
// dependency on WhatsApp answering a history request or the phone being on;
// 22 = the group sender's REAL PHONE resolves through the group METADATA too
// (each participant's phoneNumber rides beside its hidden LID, cached) plus
// the stanza's senderPn — الرقم هو المرجع في نسبة المرسل، لا اسم واتساب;
// 23 = history-synced messages read the sender from the envelope's own
// 29 = متابعة البدء: a session can read SEVERAL groups — chatIds (a list,
// one group per platform) beside the primary chatId; every gate that asked
// "is this THE group?" now asks "is this ONE OF them?";
// 28 = متابعة البدء: a session flagged groupCatchUp forwards its group's
// OFFLINE-delivered messages ('append') from ANYONE too, so a rider's "Start"
// queued while the reader restarted arrives late instead of never;
// participant field too, and the GROUP's jid is never forwarded as the
// sender — an unknown sender arrives empty, not as the group id;
// 24 = the payload carries sender_jid (the sender's raw identity — phone jid
// or LID) so Laravel's contact book (سجل جهات الاتصال) can learn each sender
// once and attribute every later message, however hidden its phone is;
// 29 = علامة على الرسالة تتغيّر مع حالتها: POST /sessions/:tenant/react puts
// (or REPLACES) a reaction on an already-forwarded message, so the financial
// group's message is marked 👍🏽 when it is pulled into العمليات المالية, ❗ while
// data it needs is missing, and ✅ the moment it is approved into the expenses. The message key is
// archived with the payload, so the reaction lands on the exact message even
// days later; a key that fell off the archive is rebuilt from the chat id,
// the sender and the fromMe flag the caller kept;
// 30 = قروب أم خاص بلا استنتاج: "is this a group?" is one predicate
// (isGroupJid, `@g.us`) instead of elimination, and it gates the live path,
// the history replay AND the archive replay — a PRIVATE chat saved as chatId
// used to walk straight into the money/tasks ingest through the last two.
// chatId itself is now group-or-nothing: POST blanks a private one, PATCH
// answers 422 not_a_group. الرقم المربوط للربط لا لأخذ المعلومات منه;
// 31 = متابعة البدء بقروب لكل منصة: a session reads SEVERAL groups — chatIds
// (a list beside the primary chatId, each entry group-or-dropped) — so one
// number can watch every platform's "Start" group at once;
// 32 = السحب يمشي على كل قروب: history anchors are kept PER CHAT and the pull
// walks the tracked groups one after another — anchored on a single shared
// key it could only ever cover whichever group owned it, so a second group's
// "اسحب" brought nothing back;
// 33 = اسم الملف المرفق: /send honors media_filename for document sends (the
// warning PDF arrives under the letter's real name instead of "attachment");
// 34 = قرصٌ ممتلئ لا يقتل الخدمة: every disk write degrades instead of
// throwing, a global handler keeps the process alive through an unexpected
// error, the archive is capped in BYTES (not just message count) and stops
// keeping media while the volume is tight — and the snapshot reports
// diskFree + the last write error so the app can SAY "القرص ممتلئ" instead
// of going silent. Before this, one ENOSPC inside a save timer took the whole
// container down for every business, and a container that is down stops
// resolving by name — "Could not resolve host: whatsapp-reader";
// 35 = رقم واحد يقرأ عدة قروبات: chatRoutes — a per-chat {callbackUrl,
// historySince} map beside the session-wide pair. Every tracked group
// forwards to ITS OWN ingest with ITS OWN history boundary, so one number
// can read the start group, the tasks group, the financial group and the
// maintenance group at once, each landing where it belongs. The session-wide
// callbackUrl/historySince stay as the fallback for a chat with no route
// (older apps keep working untouched). /backfill takes an optional chatId
// to pull ONE group with its own since, so a full-history pull on the
// maintenance group never replays the money group;
// 36 = المحادثة الخاصة للصيانة: the dm callback's answer may carry `react`
// (a listed technician's private photo claimed as maintenance gets its 👍🏽),
// exactly like the group ingest answer;
// 41 = backfillMediaFailed + lastMediaError in the snapshot: the pull says
// how many photos it could not download (expired media the phone could not
// re-upload), so a text-only history is explained, not mysterious;
// 40 = dmAliases: once a private chat's LID has been resolved to its phone
// from a LIVE message, the pair is remembered (and persisted), so HISTORY
// messages of that chat — which carry the LID alone, no phone beside it —
// are still attributed to the tracked number; a walk that fetched them used
// to end "done, 0 pulled" because every batch was dropped as untracked;
// 39 = المحادثة الشخصية بمعرّف مخفي: a private chat may arrive as a LID
// (`…@lid`), not the phone jid the app tracks — anchors, cursors and the
// history boundary are now keyed by the CANONICAL phone jid (resolved the
// way the dm forwarder resolves the sender), so a technician's chat on a
// LID-era account gets its starting point and its pull walks;
// 42 = تسليم النسخة الاحتياطية: an OUTBOUND document may be far larger than an
// inbound one (a gzipped database dump), so /send has its own ceiling —
// READER_MAX_SEND_MEDIA_BYTES — and the JSON body limit is sized to carry it
// base64-encoded instead of refusing it with a bare 413;
// 38 = dmHistory accepts a null boundary: the private chat is TRACKED (anchor
// kept, on-demand pull answered) without replaying its past on pairing;
// 37 = سحب المحادثة الشخصية: dmHistory — {privateJid: since} — reads the
// history of listed PRIVATE chats (the maintenance technicians) through the
// dm callback: on pairing sync and on a scoped /backfill walk, anchored per
// chat like the groups. Our own messages in those chats are never replayed.
const READER_VERSION = '42';

// The WhatsApp library ACTUALLY installed in this container — reported in the
// snapshot so "which build is really running?" is answerable from the UI.
const BAILEYS_VERSION = (() => {
    try {
        return String(createRequire(import.meta.url)('baileys/package.json').version || '');
    } catch {
        return '';
    }
})();

const PORT = Number(process.env.PORT || 3000);
const SECRET = String(process.env.WHATSAPP_READER_SECRET || '');
const DATA_DIR = String(process.env.READER_DATA_DIR || '/data/sessions');
// The biggest attachment we forward inline (base64). Larger media is skipped —
// the message text still arrives for review.
const MAX_MEDIA_BYTES = Number(process.env.READER_MAX_MEDIA_BYTES || 5 * 1024 * 1024);

// What we may SEND is a different question from what we may forward: the
// backup delivery hands us a gzipped database dump, which is legitimately
// bigger than any photo a rider takes. Kept separate so raising it never
// widens the ingest path, and bounded so one send can still not exhaust the
// container's memory.
const MAX_SEND_MEDIA_BYTES = Number(process.env.READER_MAX_SEND_MEDIA_BYTES || 32 * 1024 * 1024);

// How many forwarded group-message ids a session remembers (persisted with its
// meta). A replay skips them without downloading their media — Laravel is
// still the authority on duplicates, this only saves the round trip.
const MAX_FORWARDED_IDS = Number(process.env.READER_MAX_FORWARDED_IDS || 5000);
// On-demand pull (سحب العمليات): messages per request to WhatsApp, and the
// hard cap on how many requests one pull chains — the walk stops earlier when
// the history reaches the since-date or WhatsApp stops handing anything older.
const BACKFILL_BATCH = 50;
const BACKFILL_MAX_ROUNDS = 20;
// A pull whose requested history never arrives (WhatsApp simply has nothing
// older for this device) must not stay "running" forever on the page.
const BACKFILL_TIMEOUT_MS = 90000;
// How often the message path is allowed to rewrite a session's meta file.
const META_SAVE_INTERVAL_MS = 5000;
// الأرشيف المحلي (v21): the last N group messages this session forwarded,
// persisted beside the meta — so "سحب العمليات الآن" re-sends a DELETED
// operation from disk instantly and deterministically: no WhatsApp history
// request, no phone-online dependency ("أحيانًا يسحب وأحيانًا لا" was exactly
// that dependency). Media is archived up to a cap; bigger attachments replay
// text-only.
const ARCHIVE_MAX_MESSAGES = Number(process.env.READER_ARCHIVE_MAX_MESSAGES || 500);
const ARCHIVE_MAX_MEDIA_BYTES = Number(process.env.READER_ARCHIVE_MEDIA_BYTES || 1024 * 1024);
// ...and a cap on what the whole archive may WEIGH (v34). The message count
// alone bounded nothing useful: 500 messages each carrying up to 1 MB of
// inline base64 media is ~670 MB per business in a single file that is
// rewritten whole on every forward. The oldest entries' media is dropped
// (text stays replayable) until the file fits.
const ARCHIVE_MAX_BYTES = Number(process.env.READER_ARCHIVE_MAX_BYTES || 64 * 1024 * 1024);
// Below this much free space on the data volume the reader stops keeping
// media at all — archived media is a convenience (a deleted operation
// replays instantly), never the operation itself, so it is the first thing
// to give up when the disk is tight.
const DISK_FLOOR_BYTES = Number(process.env.READER_DISK_FLOOR_BYTES || 512 * 1024 * 1024);

const log = pino({ level: process.env.LOG_LEVEL || 'info' });

// ---- القرص الممتلئ لا يُسقط الخدمة (v34) ----
//
// The reader is infrastructure for every business at once, so the worst
// outcome is not a failed write — it is a DEAD CONTAINER. A container that
// exits stops resolving by name, and the app can then say nothing more useful
// than "could not resolve host": the actual cause (a full volume) never
// reaches a screen. So: writes degrade, the process survives, and the problem
// is REPORTED through the snapshot instead of taking the service with it.

/** The last disk write that failed, surfaced in /health and every snapshot. */
let lastWriteError = '';
let lastWriteErrorAt = 0;

/** Free bytes on the data volume, or -1 when the platform will not say. */
function diskFreeBytes() {
    try {
        const stat = statfsSync(DATA_DIR);

        return Number(stat.bavail) * Number(stat.bsize);
    } catch {
        return -1;
    }
}

/** Is the volume too tight to spend on optional (media) storage? */
function diskIsTight() {
    const free = diskFreeBytes();

    return free >= 0 && free < DISK_FLOOR_BYTES;
}

/**
 * Persist a file, or record why it could not be persisted and carry on. A lost
 * meta write costs a few remembered ids (Laravel dedups authoritatively
 * anyway); an ENOSPC thrown out of a save timer used to cost the container.
 */
function safeWriteFile(path, data, what) {
    try {
        writeFileSync(path, data);
        return true;
    } catch (err) {
        lastWriteError = `${what}: ${String(err && err.message ? err.message : err)}`.slice(0, 300);
        lastWriteErrorAt = Math.floor(Date.now() / 1000);
        log.error({ err: String(err), what }, 'disk write failed — degrading, not exiting');

        return false;
    }
}

// A thrown error anywhere else must not end the process either. Every business
// loses WhatsApp when this container dies, and it dies silently — these two
// handlers turn "the whole service disappeared" into "one operation failed and
// the log says why".
process.on('uncaughtException', (err) => {
    log.error({ err: String(err && err.stack ? err.stack : err) }, 'uncaught exception — staying up');
});

process.on('unhandledRejection', (reason) => {
    log.error({ err: String(reason) }, 'unhandled rejection — staying up');
});

// The data volume may be missing or unwritable (a fresh mount, a full disk).
// That is a reason to REPORT, never a reason to refuse to boot: a reader that
// still answers can tell the app what is wrong.
try {
    if (!existsSync(DATA_DIR)) mkdirSync(DATA_DIR, { recursive: true });
} catch (err) {
    lastWriteError = `data dir: ${String(err && err.message ? err.message : err)}`.slice(0, 300);
    lastWriteErrorAt = Math.floor(Date.now() / 1000);
    log.error({ err: String(err), dir: DATA_DIR }, 'data dir unavailable — sessions cannot persist');
}

/** @type {Map<string, Session>} tenant id → live session */
const sessions = new Map();

// A live session's in-memory view. `meta` is the persisted part.
class Session {
    constructor(tenant) {
        this.tenant = tenant;
        this.sock = null;
        this.status = 'connecting'; // connecting | qr | connected | disconnected
        this.qr = null; // data-URL
        this.pairingCode = null; // 8-char code
        this.number = '';
        this.chatId = '';
        // متابعة البدء (v29): the OTHER groups this session reads beside the
        // primary chatId — one per platform, all forwarding to the same
        // ingest. The Invoice session keeps a single group (its list stays
        // empty), so nothing about the financial intake changes.
        this.chatIds = [];
        // رقم واحد يقرأ عدة قروبات (v35): per-chat routes — jid → {callbackUrl,
        // historySince}. A chat listed here forwards to its OWN ingest with its
        // OWN history boundary; a tracked chat without a route falls back to
        // the session-wide callbackUrl/historySince below.
        this.chatRoutes = {};
        // سحب المحادثة الشخصية (v37): private jids whose HISTORY is read too
        // — jid → since (unix seconds, 0 = from the beginning). Live private
        // messages already flow through the dm callback; this adds the past.
        this.dmHistory = {};
        // v40: real jid (a LID) → the canonical phone jid it resolved to.
        this.dmAliases = {};
        // متابعة البدء (v25): forward the group's OFFLINE-delivered messages
        // too ('append' upserts — what WhatsApp queued while this reader was
        // down). The Invoice group stays live-only; a start message missed
        // during a restart is a rider nobody follows up, so it must arrive
        // late rather than never. Dedup (forwardedIds + wa_message_id) makes
        // the late delivery a no-op when it was already taken.
        this.groupCatchUp = false;
        this.callbackUrl = '';
        this.dmCallbackUrl = ''; // where direct (1:1) replies forward — set by the send API
        this.ingestToken = '';
        this.groups = []; // [{id, name}]
        this.pairingRequested = false;
        this.groupPoll = null; // slow backstop timer that refreshes groups
        this.reconnectTimer = null; // pending auto-reconnect (cleared on restart/wipe)
        // History backfill: unix seconds — forward group messages sent at/after
        // this instant from WhatsApp's pairing history sync. 0 = everything the
        // server hands over; null = backfill disabled.
        this.historySince = null;
        // ---- تاريخ السحب on demand (سحب العمليات) ----
        // The last pull's live state, reported in the snapshot so the settings
        // page can say what it produced without reading container logs.
        this.backfillStatus = ''; // '' | running | done | unsupported | no_anchor | failed
        this.backfillSince = null; // the boundary that pull asked for
        this.backfillAt = 0; // unix — when it was asked for
        this.backfillPulled = 0; // operations forwarded since then
        this.backfillSkipped = 0; // ones already pulled before (مكرر) — never re-sent
        this.backfillRounds = 0; // history requests spent (capped)
        this.backfillTimer = null; // watchdog closing a pull nothing answers
        // Group message ids already forwarded (or answered "duplicate" by
        // Laravel). A replay skips them BEFORE downloading their media, so a
        // message added before is never pulled twice.
        this.forwardedIds = [];
        this.forwardedIdSet = new Set();
        // الأرشيف المحلي (v21): the payloads of the last forwarded operations,
        // oldest first — loaded from disk at session start, replayed on a pull
        // for any id the app no longer knows (a deleted operation).
        this.archive = [];
        this.archiveSaveTimer = null;
        // LID → phone from the GROUP METADATA (v22): each participant's real
        // number rides the metadata beside its hidden LID — the most reliable
        // resolver when the stanza alt attrs and the LID store both miss.
        this.groupParticipants = new Map();
        this.groupParticipantsAt = 0;
        // The history anchors, PER CHAT (v32): jid → {oldestKey,
        // oldestTimestamp, newestKey, newestTimestamp}. WhatsApp's history
        // request is anchored on a MESSAGE, and a message belongs to one chat
        // — so one shared anchor could only ever pull the group that happened
        // to own it. With a group per platform, each chat keeps its own.
        //
        // The OLDEST is what a pull could reach further back from; the NEWEST
        // (v27) is where a pull STARTS, so a gap near the present is the first
        // thing it covers instead of being invisible to the walk.
        this.anchors = {};
        // The pull walks the tracked chats one after another: the queue of
        // chats still to visit, the one being walked, and where its walk
        // stands (the cursor moves back batch by batch).
        this.backfillQueue = [];
        this.backfillChats = []; // the chats THIS pull covers (v35: one, or all tracked)
        // v41: photos the pull could NOT download (expired on WhatsApp's
        // servers and the phone could not re-upload them) — said out loud in
        // the snapshot, so "0 photos" reads as "unreachable", not "none sent".
        this.backfillMediaFailed = 0;
        this.lastMediaError = '';
        this.backfillChat = '';
        this.backfillCursorKey = null;
        this.backfillCursorTimestamp = 0;
        // Why a chat's walk could not start ('' entries dropped) — reported
        // only when the WHOLE pull produced nothing, so one silent group
        // never hides another's refusal.
        this.backfillRefusals = [];
        this.metaSavedAt = 0; // unix ms of the last meta write (coalescing)
        this.metaSaveTimer = null;
        // Unix seconds of the last group message successfully forwarded to the
        // ingest endpoint — the settings page's "آخر رسالة وصلت من القروب".
        this.lastForwardedAt = null;
        this.lastAckAt = 0; // unix — last delivery/read receipt forwarded to Laravel
        this.lastReplyAt = 0; // unix — last direct (1:1) reply forwarded AND recorded
        this.lastDmSeenAt = 0; // unix — last direct message SEEN, whatever became of it
        this.lastDmDrop = ''; // why the last seen dm was not recorded ('' = it was)
        this.lastDmDropDetail = ''; // the app's actual answer on callback_failed (HTTP status + snippet)
        // The same three diagnostics for the GROUP pipe (v25). lastForwardedAt
        // only ever proves a SUCCESS, so a group message that arrived and was
        // then dropped left no trace anywhere the owner can see — the exact
        // silence behind "لم يتم سحب البيانات من القروب". Now every group
        // message stamps "seen", and whatever kills it stamps why.
        this.lastGroupSeenAt = 0; // unix — last group message SEEN, whatever became of it
        this.lastGroupDrop = ''; // why the last seen group message was not recorded ('' = it was)
        this.lastGroupDropDetail = ''; // the app's actual answer on callback_failed (HTTP status + snippet)
        // Failed reply/ack callbacks waiting for another try — a message that
        // arrives while the app container is mid-deploy (it answers 404 for a
        // minute or two) must be DELAYED, never lost. Laravel dedups by
        // wa_message_id and receipts are idempotent, so retries are safe.
        this.pendingCallbacks = [];
    }

    snapshot() {
        return {
            version: READER_VERSION,
            library: BAILEYS_VERSION,
            status: this.status,
            qr: this.qr,
            pairingCode: this.pairingCode,
            number: this.number,
            chatId: this.chatId,
            chatIds: this.chatIds,
            chatRoutes: this.chatRoutes,
            dmHistory: this.dmHistory,
            dmAliases: this.dmAliases,
            groupCatchUp: this.groupCatchUp,
            groups: this.groups,
            historySince: this.historySince,
            lastForwardedAt: this.lastForwardedAt,
            lastAckAt: this.lastAckAt,
            lastReplyAt: this.lastReplyAt,
            lastDmSeenAt: this.lastDmSeenAt,
            lastDmDrop: this.lastDmDrop,
            lastDmDropDetail: this.lastDmDropDetail,
            lastGroupSeenAt: this.lastGroupSeenAt,
            lastGroupDrop: this.lastGroupDrop,
            lastGroupDropDetail: this.lastGroupDropDetail,
            backfillStatus: this.backfillStatus,
            backfillChat: this.backfillChat,
            backfillSince: this.backfillSince,
            backfillAt: this.backfillAt,
            backfillPulled: this.backfillPulled,
            backfillSkipped: this.backfillSkipped,
            backfillMediaFailed: this.backfillMediaFailed,
            lastMediaError: this.lastMediaError,
            // حالة التخزين (v34): the silent killer, said out loud. A volume
            // that cannot be written no longer takes the container down, so
            // the app has to be the one that notices — it reads these.
            diskFree: diskFreeBytes(),
            lastWriteError,
            lastWriteErrorAt: lastWriteErrorAt || null,
        };
    }

    /**
     * Remember a group message id as pulled. The list is capped (oldest ids
     * fall off first): Laravel dedups authoritatively by wa_message_id, this
     * memory only spares the reader from re-downloading known media.
     */
    markForwarded(id) {
        if (!id || this.forwardedIdSet.has(id)) return;
        this.forwardedIdSet.add(id);
        this.forwardedIds.push(id);
        if (this.forwardedIds.length > MAX_FORWARDED_IDS) {
            for (const dropped of this.forwardedIds.splice(0, this.forwardedIds.length - MAX_FORWARDED_IDS)) {
                this.forwardedIdSet.delete(dropped);
            }
        }
    }

    alreadyForwarded(id) {
        return Boolean(id) && this.forwardedIdSet.has(id);
    }

    /**
     * الأرشيف المحلي — remember a forwarded operation's payload (v21) so a
     * pull can re-send it after the app deletes it. Bounded: oldest entries
     * fall off past ARCHIVE_MAX_MESSAGES, and media beyond the byte cap is
     * dropped from the copy (the text still replays).
     *
     * The message KEY rides along (v29): reacting to a message later — the
     * ✅ an approval stamps on it — needs the exact key WhatsApp indexed it
     * by, not just its id.
     */
    archivePut(payload, msgKey = null) {
        const id = String(payload.wa_message_id || '');
        if (!id) return;
        this.archive = this.archive.filter((p) => p.wa_message_id !== id);
        // A tight volume gives up media first (v34) — the operation itself is
        // already staged in Laravel; only the instant replay is lost.
        const keepMedia = typeof payload.media_base64 === 'string'
            && payload.media_base64.length <= Math.ceil((ARCHIVE_MAX_MEDIA_BYTES * 4) / 3)
            && !diskIsTight();
        this.archive.push({
            ...payload,
            msg_key: msgKey ? { ...msgKey } : (payload.msg_key || null),
            media_base64: keepMedia ? payload.media_base64 : null,
            media_mime: keepMedia ? payload.media_mime : null,
        });
        if (this.archive.length > ARCHIVE_MAX_MESSAGES) {
            this.archive.splice(0, this.archive.length - ARCHIVE_MAX_MESSAGES);
        }
    }

    /**
     * Drop ids from the pulled-ids memory (v19) — a deleted operation must be
     * re-forwardable by the next pull. Returns how many were actually known.
     * Laravel remains the duplicate authority: an id whose money is already
     * posted is answered "duplicate" on re-forward and re-remembered here.
     */
    forget(ids) {
        let forgotten = 0;
        for (const id of ids) {
            if (!id || !this.forwardedIdSet.has(id)) continue;
            this.forwardedIdSet.delete(id);
            forgotten++;
        }
        if (forgotten > 0) {
            this.forwardedIds = this.forwardedIds.filter((id) => this.forwardedIdSet.has(id));
        }
        return forgotten;
    }
}

function metaPath(tenant) {
    return join(DATA_DIR, tenant, 'meta.json');
}

function saveMeta(session) {
    const dir = join(DATA_DIR, session.tenant);
    if (!ensureDir(dir, 'meta dir')) return;
    session.metaSavedAt = Date.now();
    safeWriteFile(
        metaPath(session.tenant),
        JSON.stringify({
            number: session.number,
            chatId: session.chatId,
            chatIds: session.chatIds,
            chatRoutes: session.chatRoutes,
            dmHistory: session.dmHistory,
            dmAliases: session.dmAliases,
            groupCatchUp: session.groupCatchUp,
            callbackUrl: session.callbackUrl,
            dmCallbackUrl: session.dmCallbackUrl,
            ingestToken: session.ingestToken,
            historySince: session.historySince,
            lastForwardedAt: session.lastForwardedAt,
            // Survive a restart: the pulled-ids memory and the history anchor
            // are what keep a later pull from re-sending old operations.
            forwardedIds: session.forwardedIds,
            anchors: session.anchors,
        }),
        'meta',
    );
}

/** mkdir that reports instead of throwing (a full or unmounted volume). */
function ensureDir(dir, what) {
    try {
        if (!existsSync(dir)) mkdirSync(dir, { recursive: true });

        return true;
    } catch (err) {
        lastWriteError = `${what}: ${String(err && err.message ? err.message : err)}`.slice(0, 300);
        lastWriteErrorAt = Math.floor(Date.now() / 1000);
        log.error({ err: String(err), dir }, 'could not create directory — degrading');

        return false;
    }
}

// The message path touches meta constantly (the pulled-ids memory, the anchor,
// the heartbeat) and a pull can walk a thousand messages in a burst — so those
// writes are coalesced. A crash inside the window costs at most a few ids,
// which Laravel's own dedup covers anyway.
function saveMetaSoon(session) {
    if (session.metaSaveTimer) return;

    const elapsed = Date.now() - (session.metaSavedAt || 0);
    if (elapsed >= META_SAVE_INTERVAL_MS) {
        saveMeta(session);

        return;
    }

    session.metaSaveTimer = setTimeout(() => {
        session.metaSaveTimer = null;
        saveMeta(session);
    }, META_SAVE_INTERVAL_MS - elapsed);
}

function loadMeta(tenant) {
    try {
        return JSON.parse(readFileSync(metaPath(tenant), 'utf8'));
    } catch {
        return null;
    }
}

// ---- الأرشيف المحلي (v21): its own file beside the meta — the meta is
// rewritten constantly and stays small; the archive is bigger and only
// changes when a message is forwarded.

function archivePath(tenant) {
    return join(DATA_DIR, tenant, 'archive.json');
}

function saveArchive(session) {
    const dir = join(DATA_DIR, session.tenant);
    if (!ensureDir(dir, 'archive dir')) return;

    // Weigh it before writing (v34): drop the OLDEST entries' media until the
    // file fits ARCHIVE_MAX_BYTES. Losing an old attachment costs an instant
    // replay of a deleted operation; losing the volume costs everything.
    let body = JSON.stringify(session.archive);

    if (body.length > ARCHIVE_MAX_BYTES) {
        for (const entry of session.archive) {
            if (body.length <= ARCHIVE_MAX_BYTES) break;
            if (entry.media_base64 === null) continue;
            entry.media_base64 = null;
            entry.media_mime = null;
            body = JSON.stringify(session.archive);
        }

        log.warn({ tenant: session.tenant, bytes: body.length }, 'archive over its byte cap — oldest media dropped');
    }

    safeWriteFile(archivePath(session.tenant), body, 'archive');
}

// Same coalescing idea as the meta: a history burst forwards many messages in
// seconds — one write at the end covers them all, and a crash inside the
// window only costs replayability of the last few (never the operations
// themselves — Laravel already staged them).
function saveArchiveSoon(session) {
    if (session.archiveSaveTimer) return;
    session.archiveSaveTimer = setTimeout(() => {
        session.archiveSaveTimer = null;
        saveArchive(session);
    }, META_SAVE_INTERVAL_MS);
}

function loadArchive(tenant) {
    try {
        const rows = JSON.parse(readFileSync(archivePath(tenant), 'utf8'));

        return Array.isArray(rows) ? rows : [];
    } catch {
        return [];
    }
}

// Coerce a historySince input (unix seconds, 0 = from the beginning) into the
// متابعة البدء (v29): the extra tracked groups as a clean list of jids —
// duplicates and blanks dropped, so a gate can just ask "does it include?".
function normalizeChatIds(value) {
    if (!Array.isArray(value)) return [];

    return [...new Set(value.map((id) => String(id || '')).filter((id) => isGroupJid(id)))];
}

// Every chat this session reads: the primary group plus the extras (v29).
function trackedChats(session) {
    return [...new Set([session.chatId, ...session.chatIds, ...Object.keys(session.chatRoutes || {})].filter(Boolean))];
}

// The per-chat routes as the session keeps them (v35): only group jids, each
// with a callback URL (may be '' = use the session-wide one) and a history
// boundary (unix seconds, 0 = from the beginning, null = live only).
function normalizeChatRoutes(value) {
    const routes = {};
    if (!value || typeof value !== 'object' || Array.isArray(value)) return routes;

    for (const [jid, route] of Object.entries(value)) {
        const id = String(jid || '');
        if (!isGroupJid(id)) continue;
        const spec = route && typeof route === 'object' ? route : {};
        routes[id] = {
            callbackUrl: String(spec.callbackUrl || ''),
            historySince: normalizeHistorySince(spec.historySince),
        };
    }

    return routes;
}

// Where ONE chat's messages go and how far back its history is read: its own
// route, else the session-wide pair — so a reader fed by an older app (no
// routes) behaves exactly as before.
function routeFor(session, jid) {
    const route = session.chatRoutes?.[jid];

    return {
        callbackUrl: (route && route.callbackUrl) || session.callbackUrl || '',
        historySince: route ? route.historySince : session.historySince,
    };
}

// Does this session read ANY group somewhere? The gate every group path asks.
function hasGroupReader(session) {
    return trackedChats(session).some((jid) => routeFor(session, jid).callbackUrl !== '');
}

// Is history wanted for ANY tracked chat (turns on syncFullHistory)?
function historyWanted(session) {
    return trackedChats(session).some((jid) => routeFor(session, jid).historySince !== null)
        || (Boolean(session.dmCallbackUrl) && Object.values(session.dmHistory || {}).some((since) => since !== null));
}

// The private chats whose history may be read (v37): only private jids.
// A null boundary (v38) means "tracked, but nothing replayed on pairing" —
// the chat keeps its anchor and answers an on-demand scoped pull, without
// its past flooding in on every re-link.
function normalizeDmHistory(value) {
    const out = {};
    if (!value || typeof value !== 'object' || Array.isArray(value)) return out;

    for (const [jid, since] of Object.entries(value)) {
        const id = String(jid || '');
        if (!isPrivateJid(id)) continue;
        out[id] = normalizeHistorySince(since);
    }

    return out;
}

function readsDmHistory(session, jid) {
    return Boolean(jid) && Object.prototype.hasOwnProperty.call(session.dmHistory || {}, jid);
}

// The phone jid the app tracks for a private chat (v39): a LID-era chat
// arrives as `…@lid`, so the phone is resolved exactly as the dm forwarder
// resolves the sender, and everything history-related is keyed by it.
async function dmCanonicalJid(session, m, jid) {
    if (!isPrivateJid(jid)) return jid;
    if (jid.endsWith('@s.whatsapp.net')) return jid;

    // Learned earlier from a live message (v40) — history messages carry the
    // LID alone, so this is the only way they find their number.
    if (session.dmAliases?.[jid]) return session.dmAliases[jid];

    // A walk in progress on a chat whose anchor key IS this LID: that chat.
    if (session.backfillStatus === 'running' && session.backfillChat && session.backfillCursorKey?.remoteJid === jid) {
        return session.backfillChat;
    }

    const phone = await directChatPhone(session, m, jid);
    if (!phone) return jid;

    const canonical = `${phone}@s.whatsapp.net`;
    if (readsDmHistory(session, canonical)) {
        session.dmAliases[jid] = canonical;
        saveMetaSoon(session);
    }

    return canonical;
}

// Does this session read that chat? The primary group plus every extra one
// (v29) — one question, asked by every group gate.
function readsChat(session, jid) {
    if (!jid) return false;

    return trackedChats(session).includes(jid);
}

// session's canonical form: a non-negative number, or null = backfill disabled.
function normalizeHistorySince(value) {
    if (value === null || value === undefined || value === '') return null;
    const n = Number(value);
    return Number.isFinite(n) && n >= 0 ? Math.floor(n) : null;
}

// Bring a session up: (re)connect the socket, wire its events, and — when the
// number isn't registered yet — request a pairing code so the page can show it
// beside the QR.
//
// RE-ENTRANT by design: calling it again for a tenant that already has a
// session (even one stuck in 'connecting') tears the old socket down first and
// starts fresh — sockets never pile up, and a dead socket can always be
// escaped by pressing "connect" again.
async function startSession(tenant, opts = {}) {
    let session = sessions.get(tenant);
    if (!session) {
        session = new Session(tenant);
        session.archive = loadArchive(tenant);
        sessions.set(tenant, session);
    }

    if (opts.number) session.number = String(opts.number).replace(/\D+/g, '');
    if (opts.callbackUrl) session.callbackUrl = String(opts.callbackUrl);
    // An EXPLICIT empty string clears the dm callback (v16) — the Invoice
    // session must stop forwarding direct replies after the invoice/operations
    // hard split; absent keeps whatever is stored (resume path).
    if (opts.dmCallbackUrl !== undefined && opts.dmCallbackUrl !== null) {
        session.dmCallbackUrl = String(opts.dmCallbackUrl || '');
    }
    if (opts.ingestToken) session.ingestToken = String(opts.ingestToken);
    // قروب فقط: a group jid or nothing. A private chat can never become the
    // chat a session READS — the linked number carries the connection, it is
    // not a source of information (see isGroupJid).
    if (opts.chatId !== undefined) {
        const wanted = String(opts.chatId || '');
        session.chatId = isGroupJid(wanted) ? wanted : '';
    }
    // متابعة البدء (v31): the OTHER groups this session reads — same rule,
    // private chats dropped rather than read.
    if (opts.chatIds !== undefined) session.chatIds = normalizeChatIds(opts.chatIds);
    // رقم واحد يقرأ عدة قروبات (v35): the per-chat routes, replaced wholesale.
    if (opts.chatRoutes !== undefined) session.chatRoutes = normalizeChatRoutes(opts.chatRoutes);
    // سحب المحادثة الشخصية (v37): the private chats whose past is read too.
    if (opts.dmHistory !== undefined) session.dmHistory = normalizeDmHistory(opts.dmHistory);
    // Resume path (v40): the LID → phone pairs learned before the restart.
    if (opts.dmAliases && typeof opts.dmAliases === 'object' && !Array.isArray(opts.dmAliases) && Object.keys(session.dmAliases).length === 0) {
        for (const [jid, canonical] of Object.entries(opts.dmAliases)) {
            if (isPrivateJid(String(jid)) && isPrivateJid(String(canonical))) session.dmAliases[String(jid)] = String(canonical);
        }
    }
    if (opts.groupCatchUp !== undefined) session.groupCatchUp = Boolean(opts.groupCatchUp);
    if (opts.historySince !== undefined) session.historySince = normalizeHistorySince(opts.historySince);
    if (opts.lastForwardedAt !== undefined && session.lastForwardedAt === null) {
        session.lastForwardedAt = normalizeHistorySince(opts.lastForwardedAt);
    }
    // Resume path (meta): restore the pulled-ids memory and the history anchor
    // so a reconnect never re-pulls operations this session already sent.
    if (Array.isArray(opts.forwardedIds) && session.forwardedIds.length === 0) {
        for (const id of opts.forwardedIds) session.markForwarded(String(id));
    }
    if (opts.anchors && typeof opts.anchors === 'object' && Object.keys(session.anchors).length === 0) {
        for (const [jid, anchor] of Object.entries(opts.anchors)) {
            if (jid && anchor && typeof anchor === 'object') session.anchors[jid] = anchor;
        }
    }
    // Resume from a PRE-v32 meta: the single shared anchor belonged to the
    // session's primary chat, so that is where it is filed.
    if ((opts.oldestKey || opts.newestKey) && session.chatId && !session.anchors[session.chatId]) {
        session.anchors[session.chatId] = {
            oldestKey: opts.oldestKey ?? null,
            oldestTimestamp: normalizeHistorySince(opts.oldestTimestamp) ?? 0,
            newestKey: opts.newestKey ?? null,
            newestTimestamp: normalizeHistorySince(opts.newestTimestamp) ?? 0,
        };
    }
    saveMeta(session);

    // Tear down whatever socket exists (stuck, half-open, or healthy) before
    // opening a new one — a re-connect must never leave two sockets fighting
    // over the same creds (WhatsApp answers that with stream-conflict loops).
    if (session.reconnectTimer) {
        clearTimeout(session.reconnectTimer);
        session.reconnectTimer = null;
    }
    if (session.sock) {
        const old = session.sock;
        session.sock = null; // stale-socket guards make old events no-ops
        try {
            old.end(undefined);
        } catch { /* ignore */ }
    }

    // Un-poison half-registrations: rc13's requestPairingCode MUTATES creds
    // (sets creds.me + pairingCode and persists them) even when the pairing
    // never completes — a socket that then boots from those creds never emits
    // a QR again. The poisoned signature is me/pairingCode WITHOUT an account.
    // CAREFUL with the flags: a successful QR scan sets creds.account
    // (configureSuccessfulPairing, lib/Utils/validate-connection.js:121-69)
    // but `registered` only flips true LATER (lib/Socket/messages-recv.js:940)
    // — and WhatsApp forces a restart right after the scan, so sweeping on
    // `!registered` alone would delete the FRESH pairing at that exact moment
    // (the phone then hangs on "logging in" and errors out). Only creds with
    // neither `registered` nor `account` are junk worth clearing.
    const authDir = join(DATA_DIR, tenant, 'auth');
    try {
        const creds = JSON.parse(readFileSync(join(authDir, 'creds.json'), 'utf8'));
        if (!creds?.registered && !creds?.account) {
            log.info({ tenant }, 'unpaired leftover creds found — clearing for a fresh QR');
            rmSync(authDir, { recursive: true, force: true });
        }
    } catch { /* no creds yet — nothing to clean */ }

    const { state, saveCreds } = await useMultiFileAuthState(authDir);
    const { version } = await fetchLatestBaileysVersion();

    const sock = makeWASocket({
        version,
        auth: state,
        printQRInTerminal: false,
        logger: pino({ level: 'silent' }),
        browser: ['Souq Invoice', 'Chrome', '1.0.0'],
        // History backfill (تاريخ السحب): ask WhatsApp for the full history on
        // pairing when the tenant configured a since-date. How much actually
        // arrives is WhatsApp's call (roughly recent months, device-dependent).
        syncFullHistory: historyWanted(session),
    });

    session.sock = sock;
    session.status = 'connecting';
    session.qr = null;
    session.pairingRequested = false;

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', async (update) => {
        if (session.sock !== sock) return; // superseded by a newer socket
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
            session.status = 'qr';
            session.qr = await qrcode.toDataURL(qr).catch(() => null);

            // NOTE: the old "also request a pairing code" convenience is GONE
            // on purpose. In baileys v7, requestPairingCode() rewrites and
            // persists creds (me + pairingCode) mid-QR — the two flows can no
            // longer be mixed: the QR dies and the stored creds are poisoned
            // (see the un-poison sweep in startSession). QR is the one flow.
        }

        if (connection === 'open') {
            session.status = 'connected';
            session.qr = null;
            session.pairingCode = null;
            await refreshGroups(session);
        }

        if (connection === 'close') {
            const code = new Boom(lastDisconnect?.error)?.output?.statusCode;
            const loggedOut = code === DisconnectReason.loggedOut;
            session.status = loggedOut ? 'disconnected' : 'connecting';

            if (loggedOut) {
                log.info({ tenant }, 'logged out — wiping session');
                wipe(tenant);
            } else {
                log.info({ tenant, code }, 'connection closed — reconnecting');
                session.reconnectTimer = setTimeout(() => {
                    session.reconnectTimer = null;
                    // A wiped (DELETE) or replaced session must stay gone — the
                    // timer must never resurrect it from an empty meta.
                    if (sessions.get(tenant) !== session) return;
                    startSession(tenant).catch((e) => log.error({ tenant, e: String(e) }));
                }, 3000);
            }
        }
    });

    // 'notify' = live messages; 'append' = messages the server queued while
    // this reader was offline (rc13 upserts offline-delivered nodes as
    // 'append': baileys/lib/Socket/messages-recv.js:1432). A rider's reply
    // sent during a container restart must still reach the log, so both types
    // flow through — handleMessage keeps the group-ingest path 'notify'-only.
    sock.ev.on('messages.upsert', async ({ messages, type }) => {
        if (session.sock !== sock) return;
        if (type !== 'notify' && type !== 'append') return;
        for (const m of messages) {
            try {
                await handleMessage(session, m, type);
            } catch (err) {
                log.error({ tenant, err: String(err) }, 'message handling failed');
            }
        }
    });

    // History backfill (تاريخ السحب): on pairing, WhatsApp syncs a slice of the
    // account's past chats to the new linked device. When the tenant configured
    // a since-date we replay the Invoice group's part of that slice through the
    // normal ingest path — Laravel dedups by wa_message_id, so overlap with
    // live messages is harmless. WhatsApp decides how far back the sync goes
    // (roughly recent months, device-dependent); nothing older ever arrives.
    sock.ev.on('messaging-history.set', async ({ messages }) => {
        if (session.sock !== sock) return;
        if (!historyWanted(session) && session.backfillStatus !== 'running') return;
        const anchorBefore = session.backfillCursorTimestamp;
        for (const m of messages || []) {
            try {
                await handleHistoryMessage(session, m);
            } catch (err) {
                log.error({ tenant, err: String(err) }, 'history message handling failed');
            }
        }
        // An on-demand pull (سحب العمليات) walks backwards one batch at a
        // time: keep asking while the history is still newer than the
        // requested date AND the anchor actually moved — an unmoved anchor
        // means WhatsApp has nothing older for this device, so the pull ends.
        if (session.backfillStatus === 'running') {
            await continueBackfill(session, anchorBefore);
        }
    });

    // Delivery/read receipts for messages WE sent (the delay chases): forward
    // them so the log can prove a message actually reached the rider's phone —
    // "accepted by the server" and "delivered" are different claims. rc13
    // routes 1:1 receipts through 'messages.update' (numeric status — see
    // handleAck's source refs).
    sock.ev.on('messages.update', async (updates) => {
        if (session.sock !== sock) return;
        for (const u of updates) {
            try {
                await handleAck(session, u);
            } catch (err) {
                log.error({ tenant, err: String(err) }, 'ack handling failed');
            }
        }
    });

    // Defensive net: rc13 emits 'message-receipt.update' for GROUP/status
    // chats only (baileys/lib/Socket/messages-recv.js:1186-1197), but its
    // payload (proto.IUserReceipt — receiptTimestamp/readTimestamp,
    // baileys/WAProto/index.d.ts:13396-13403) carries everything an ack
    // needs, so if a future build routes a direct-chat receipt here it still
    // stamps the log. Laravel keeps the first stamp (??=), so a receipt that
    // arrives on both events is a no-op the second time.
    sock.ev.on('message-receipt.update', async (updates) => {
        if (session.sock !== sock) return;
        for (const u of updates) {
            try {
                await handleReceiptAck(session, u.key, u.receipt);
            } catch (err) {
                log.error({ tenant, err: String(err) }, 'receipt handling failed');
            }
        }
    });

    // Refresh the joined-groups list when the account is ADDED to (or removed
    // from) a group — debounced. Deliberately NOT on groups.update or a timer:
    // fetching all groups is heavy and WhatsApp rate-limits it hard on accounts
    // in many groups. Anything else uses the manual "Refresh groups" button.
    let groupDebounce = null;
    sock.ev.on('groups.upsert', () => {
        if (session.sock !== sock) return;
        if (groupDebounce) clearTimeout(groupDebounce);
        groupDebounce = setTimeout(() => refreshGroups(session), 10000);
    });

    return session;
}

// The joined groups, for the page's "which group is Invoice?" picker.
async function refreshGroups(session) {
    try {
        const all = await session.sock.groupFetchAllParticipating();
        session.groups = Object.values(all).map((g) => ({ id: g.id, name: g.subject || g.id }));
    } catch (err) {
        log.warn({ tenant: session.tenant, err: String(err) }, 'group fetch failed');
    }
}

// قروب أم خاص — the ONE place the shape of a chat id is judged. A group jid
// ends with @g.us; everything else that carries messages is a 1:1 chat (a
// phone jid, WhatsApp Web's legacy form, or a LID-era hidden id).
//
// The linked number is a CONNECTION, not a source: it exists to read the group
// it was pointed at. So the group pipeline — money operations, tasks, "Start"
// — must only ever be fed by a real group. This used to be decided by
// elimination ("not a private suffix ⇒ treat it as a group"), which meant a
// private chat saved as `chatId` walked straight into the group ingest, both
// on the history replay and on the archive replay. Ask isGroupJid instead.
function isGroupJid(jid) {
    return typeof jid === 'string' && jid.endsWith('@g.us');
}

function isPrivateJid(jid) {
    return typeof jid === 'string'
        && (jid.endsWith('@s.whatsapp.net') || jid.endsWith('@c.us') || jid.endsWith('@lid'));
}

// Route one incoming message: the configured Invoice group forwards to the
// business's ingest endpoint; a DIRECT (1:1) message — someone replying to the
// business's number, e.g. a rider answering a delay chase — forwards text-only
// to the dm callback when one is set. Everything else, and our own messages,
// is ignored.
async function handleMessage(session, m, upsertType = 'notify') {
    const jid = m.key?.remoteJid;
    const fromMe = Boolean(m.key?.fromMe);

    if (isPrivateJid(jid)) {
        // A private chat whose past is read (v37) keeps its anchor like a
        // group, so a later pull has a message to start from — keyed by the
        // phone jid the app knows, whatever jid WhatsApp delivered it as.
        const canonical = await dmCanonicalJid(session, m, jid);
        if (readsDmHistory(session, canonical)) noteGroupMessage(session, m, canonical);

        // A DIRECT message we sent is never a rider's reply — reading our own
        // delay chases back would feed the pipeline its own output. This is
        // the one place `fromMe` must still stop everything.
        if (fromMe) return;

        const result = await handleDirectMessage(session, m, jid);
        if (readsDmHistory(session, canonical) && result?.ok && m.key?.id) session.markForwarded(String(m.key.id));

        return;
    }

    // ...but in a GROUP it must not. The linked number is often the very
    // number that posts the operations ("المرسل هو نفس المتصل بواتساب"), and
    // a blanket fromMe skip dropped every one of those messages before any
    // other check — connected, right group, and nothing ever arrived.
    // Its natural delivery type on a linked device is 'append' (the phone
    // sent it, this device is catching up), so both types are taken for it.
    // Someone ELSE's 'append' is the offline catch-up: ignored for the
    // Invoice group, TAKEN by a session flagged groupCatchUp (متابعة البدء,
    // v28) — a rider's "Start" queued while this reader restarted must arrive
    // late, not never, and dedup makes it a no-op if it was already taken.
    if (upsertType !== 'notify' && !fromMe && !session.groupCatchUp) return;

    if (!hasGroupReader(session)) {
        log.debug({ tenant: session.tenant, jid }, 'group message ignored — no group configured');
        return;
    }
    // Only a REAL group feeds the group ingest. Belt and braces with the
    // match below: if a tracked chat were ever a private one, matching it
    // would otherwise post a 1:1 conversation to the money/tasks endpoint.
    if (!isGroupJid(jid)) return;
    if (!readsChat(session, jid)) return;

    noteGroupMessage(session, m);
    await forwardGroupMessage(session, m, jid);
}

// Keep the anchor WhatsApp needs for an on-demand history request: the OLDEST
// group message this session has seen. Every group message counts — including
// ones we skip as duplicates — because the anchor is about reach, not content.
function noteGroupMessage(session, m, canonicalJid = null) {
    const timestamp = Number(m.messageTimestamp || 0);
    const jid = m.key?.remoteJid;
    if (!timestamp || !m.key?.id || !jid) return;
    // The KEY keeps the jid WhatsApp delivered (a history request needs the
    // real one); the anchor RECORD sits under the canonical jid (v39).
    const key = { id: m.key.id, remoteJid: jid, fromMe: Boolean(m.key.fromMe) };
    const anchor = anchorFor(session, canonicalJid || jid);
    let moved = false;

    if (anchor.oldestTimestamp === 0 || timestamp < anchor.oldestTimestamp) {
        anchor.oldestTimestamp = timestamp;
        anchor.oldestKey = key;
        moved = true;
    }

    // The NEWEST anchor is what a pull starts from (v27) — without it the walk
    // could only go deeper into the past and never over a recent gap.
    if (timestamp > anchor.newestTimestamp) {
        anchor.newestTimestamp = timestamp;
        anchor.newestKey = key;
        moved = true;
    }

    if (moved) saveMetaSoon(session);
}

// This chat's anchor record, created on first sight (v32) — every tracked
// group keeps its own, because a history request is anchored on a message and
// a message belongs to exactly one chat.
function anchorFor(session, jid) {
    session.anchors[jid] ??= { oldestKey: null, oldestTimestamp: 0, newestKey: null, newestTimestamp: 0 };

    return session.anchors[jid];
}

/**
 * Move the running pull's cursor to the OLDEST message it has been handed so
 * far — that is where the next batch request starts. Tracked separately from
 * the session's own oldest anchor: a pull that begins at the newest message
 * must be able to walk down THROUGH messages the session already knows.
 */
function noteBackfillCursor(session, m, canonicalJid = null) {
    const timestamp = Number(m.messageTimestamp || 0);
    if (!timestamp || !m.key?.id) return;
    // Only the chat currently being walked moves the cursor: a message from
    // ANOTHER tracked group arriving in the same batch would otherwise hijack
    // the walk into the wrong history (v32). Compared by the canonical jid
    // (v39) so a LID-delivered private message still moves its own walk.
    if (session.backfillChat && (canonicalJid || m.key.remoteJid) !== session.backfillChat) return;
    if (session.backfillCursorTimestamp !== 0 && timestamp >= session.backfillCursorTimestamp) return;

    session.backfillCursorTimestamp = timestamp;
    session.backfillCursorKey = { id: m.key.id, remoteJid: m.key.remoteJid, fromMe: Boolean(m.key.fromMe) };
}

// A message from WhatsApp's pairing history sync (تاريخ السحب): replay it into
// the same ingest path when it belongs to the Invoice group and was sent at or
// after the configured since-instant. Laravel dedups by wa_message_id.
async function handleHistoryMessage(session, m) {
    const jid = m.key?.remoteJid;

    // سحب المحادثة الشخصية (v37): a listed private chat's past goes through
    // the dm callback exactly like its live messages — never our own side
    // of the chat, never a message this session already handed over.
    if (isPrivateJid(jid)) {
        const canonical = await dmCanonicalJid(session, m, jid);
        if (!readsDmHistory(session, canonical)) return;

        noteGroupMessage(session, m, canonical);
        noteBackfillCursor(session, m, canonical);

        if (m.key?.fromMe) return;

        const since = historySinceFor(session, canonical);
        if (since === null || Number(m.messageTimestamp || 0) < since) return;

        const id = String(m.key?.id || '');
        if (id && session.alreadyForwarded(id)) {
            session.backfillSkipped++;
            return;
        }

        const result = await handleDirectMessage(session, m, jid);
        if (!result?.ok) return;

        if (id) session.markForwarded(id);
        if (result.body?.duplicate || result.body?.status === 'ignored') {
            session.backfillSkipped++;
        } else {
            session.backfillPulled++;
            session.lastForwardedAt = Math.floor(Date.now() / 1000);
        }
        saveMetaSoon(session);

        return;
    }

    if (!readsChat(session, jid)) return;
    // The live path checks the shape; the history replay must too, or a
    // private chat stored as a tracked chat would be pulled into the group
    // ingest wholesale on the next pairing sync.
    if (!isGroupJid(jid)) return;

    noteGroupMessage(session, m);
    noteBackfillCursor(session, m);

    // Our own messages are operations too (v26): when the business posts its
    // invoices from the linked number itself, skipping fromMe here made the
    // pull as blind as the live path — "سحبت ولم تأتِ آخر عملية".
    const since = historySinceFor(session, jid);
    if (since === null) return;
    if (Number(m.messageTimestamp || 0) < since) return;

    await forwardGroupMessage(session, m, jid);
}

// The boundary a history message of THIS chat is judged by: the running
// pull's own since while the pull walks this chat (v35: a one-group pull
// carries its own boundary), else the chat's route (null = live only).
function historySinceFor(session, jid) {
    if (session.backfillStatus === 'running' && Array.isArray(session.backfillChats) && session.backfillChats.includes(jid)) {
        return session.backfillSince ?? 0;
    }

    if (isPrivateJid(jid)) return readsDmHistory(session, jid) ? session.dmHistory[jid] : null;

    return routeFor(session, jid).historySince;
}

// ---- سحب العمليات: the on-demand pull ----
//
// WhatsApp only pushes history to a linked device when it is paired, so a
// business that wants OLDER operations used to have to re-link its number.
// The on-demand path asks for them instead: anchored on the oldest group
// message this session has seen, `fetchMessageHistory` requests the batch
// before it, WhatsApp answers on 'messaging-history.set', and the walk repeats
// backwards until it reaches the requested date, runs out of history, or hits
// the round cap. Messages already pulled are skipped on the way (مكرر).

// Ask WhatsApp for the batch of messages older than the current anchor.
// Returns false (with the reason parked on backfillStatus) when the request
// cannot be made at all.
async function requestOlderHistory(session) {
    if (typeof session.sock?.fetchMessageHistory !== 'function') {
        session.backfillStatus = 'unsupported';

        return false;
    }
    if (!session.backfillCursorKey || !session.backfillCursorTimestamp) {
        // Nothing to anchor on: this session has never seen a message from
        // THIS group, so only a (re-)link can bring its history over. Recorded
        // as this chat's refusal — the other tracked groups still get walked.
        noteRefusal(session, 'no_anchor');

        return false;
    }
    // نقطة الانطلاق أقدم من الفترة المطلوبة (v27): the newest group message
    // this session ever SAW predates the date we are asked to cover, so
    // "everything before it" cannot possibly contain the missing operations —
    // WhatsApp is never even asked. Reported as its own state, because the
    // alternative is the lie the owner already met: "اكتمل السحب — 0 عملية"
    // for a window the pull could never have looked at. The cure is one
    // message in the group: it becomes the anchor, and the next pull covers
    // everything before it.
    if (session.backfillRounds === 0
        && (session.backfillSince ?? 0) > 0
        && session.backfillCursorTimestamp <= session.backfillSince
    ) {
        noteRefusal(session, 'stale_anchor');

        return false;
    }

    if (session.backfillRounds >= BACKFILL_MAX_ROUNDS) {
        return false;
    }

    session.backfillRounds++;

    try {
        await session.sock.fetchMessageHistory(BACKFILL_BATCH, session.backfillCursorKey, session.backfillCursorTimestamp);
        armBackfillWatchdog(session);

        return true;
    } catch (err) {
        log.warn({ tenant: session.tenant, err: String(err) }, 'history request failed');
        noteRefusal(session, 'failed');

        return false;
    }
}

// Why one chat's walk could not start. Kept as a list: the pull only reports a
// refusal when NOTHING came back at all, so a group with no anchor never hides
// what the others actually pulled (v32).
function noteRefusal(session, reason) {
    if (!session.backfillRefusals.includes(reason)) session.backfillRefusals.push(reason);
}

// Start walking ONE chat: its own newest message is where the walk begins
// (v27), and it works back from there to the requested date.
async function startChatWalk(session, jid) {
    const anchor = anchorFor(session, jid);

    session.backfillChat = jid;
    session.backfillRounds = 0;
    session.backfillCursorKey = anchor.newestKey || anchor.oldestKey;
    session.backfillCursorTimestamp = anchor.newestTimestamp || anchor.oldestTimestamp;

    return requestOlderHistory(session);
}

// Move to the next tracked chat, or close the pull when the queue is empty.
// Returns true while a walk is running.
async function advanceBackfill(session) {
    while (session.backfillQueue.length > 0) {
        const jid = session.backfillQueue.shift();

        if (await startChatWalk(session, jid)) return true;
    }

    session.backfillChat = '';
    finishBackfill(session, backfillOutcome(session));

    return false;
}

// What the pull ends as: anything actually pulled (or skipped as already
// known) means it DID look — "done". Only a pull that produced nothing at all
// reports the refusal that stopped it, so "اكتمل السحب — 0" never covers for
// a group WhatsApp was never even asked about.
function backfillOutcome(session) {
    if (session.backfillPulled > 0 || session.backfillSkipped > 0) return 'done';

    return session.backfillRefusals[0] ?? 'done';
}

// One batch answered: keep walking back while the history is still newer than
// the requested date and the anchor is actually moving. An unmoved anchor means
// WhatsApp handed over nothing older — the pull is done, not stuck.
async function continueBackfill(session, anchorBefore) {
    const reachedDate = session.backfillCursorTimestamp !== 0 && session.backfillCursorTimestamp <= (session.backfillSince ?? 0);
    const anchorMoved = session.backfillCursorTimestamp !== anchorBefore;

    // This chat is done (covered the date, or WhatsApp handed over nothing
    // older) — move on to the NEXT tracked group instead of ending the pull:
    // with a group per platform, the first chat finishing is not the answer
    // for the others (v32).
    if (reachedDate || !anchorMoved) {
        await advanceBackfill(session);
        saveMeta(session);

        return;
    }

    if (!await requestOlderHistory(session)) await advanceBackfill(session);
    saveMeta(session);
}

// إعادة المحذوف من الأرشيف — re-send archived operations the app no longer
// knows: their ids were swept from the pulled-ids memory (deleted in the app),
// so alreadyForwarded() is false for exactly them. Local and deterministic —
// runs before WhatsApp is asked for anything, so a deleted operation returns
// even when the phone is offline or hands over no history.
async function replayArchived(session) {
    const since = session.backfillSince ?? 0;

    for (const payload of [...session.archive]) {
        const id = String(payload.wa_message_id || '');
        if (!id || session.alreadyForwarded(id)) continue;
        // Archived payloads predate the group-shape rule, so re-check it here
        // rather than trusting what was written to disk.
        if (!isGroupJid(payload.chat_id)) continue;
        // A one-group pull (v35) replays that group only.
        if (Array.isArray(session.backfillChats) && session.backfillChats.length && !session.backfillChats.includes(payload.chat_id)) continue;
        if (since > 0 && Number(payload.sent_at || 0) < since) continue;

        const url = routeFor(session, payload.chat_id).callbackUrl;
        if (!url) continue;

        const answer = await postCallback(session, url, payload, 'archive replay');
        if (!answer.ok) continue;

        session.markForwarded(id);
        if (answer.body?.duplicate) {
            session.backfillSkipped++;
        } else {
            session.backfillPulled++;
            session.lastForwardedAt = Math.floor(Date.now() / 1000);
        }
    }

    saveMetaSoon(session);
}

// How many archived operations the app no longer knows — what replayArchived
// WOULD re-send. Answered synchronously so the pull endpoint can say "ok"
// before the replay finishes.
function replayableCount(session, since, chats = []) {
    return session.archive.filter((p) => {
        const id = String(p.wa_message_id || '');

        return id !== '' && !session.alreadyForwarded(id)
            && !(chats.length && !chats.includes(String(p.chat_id || '')))
            && !(since > 0 && Number(p.sent_at || 0) < since);
    }).length;
}

// Close the pull: a page polling the snapshot must never see "running" for a
// request WhatsApp silently stopped answering.
function finishBackfill(session, status) {
    if (session.backfillTimer) {
        clearTimeout(session.backfillTimer);
        session.backfillTimer = null;
    }
    if (session.backfillStatus === 'running') session.backfillStatus = status;
    log.info(
        { tenant: session.tenant, status: session.backfillStatus, pulled: session.backfillPulled, skipped: session.backfillSkipped },
        'backfill finished',
    );
}

function armBackfillWatchdog(session) {
    if (session.backfillTimer) clearTimeout(session.backfillTimer);
    session.backfillTimer = setTimeout(() => finishBackfill(session, 'done'), BACKFILL_TIMEOUT_MS);
}

// Forward one Invoice-group message (live or history) to the business's ingest
// endpoint, and stamp lastForwardedAt on success — the settings page's proof
// the pipe is alive.
async function forwardGroupMessage(session, m, jid) {
    // Liveness diagnostics (v25), mirroring the DM ones: the message was SEEN
    // here — whatever happens next, the settings page can now say so, and name
    // the reason it never reached the review inbox.
    session.lastGroupSeenAt = Math.floor(Date.now() / 1000);
    const drop = (reason, detail = '') => {
        session.lastGroupDrop = reason;
        session.lastGroupDropDetail = detail;
        saveMetaSoon(session);
    };

    // مضاف من قبل — an operation this session already pulled is NOT pulled
    // again: the skip happens here, before the media download and the ingest
    // round trip, and is counted so the settings page can report it.
    const waMessageId = m.key?.id || '';
    if (session.alreadyForwarded(waMessageId)) {
        session.backfillSkipped++;
        drop('already_pulled');
        log.debug({ tenant: session.tenant, id: waMessageId }, 'group message skipped — already pulled');
        return;
    }

    // Peel WhatsApp's envelopes (ephemeral / view-once / document-with-caption)
    // to reach the real content, then work off a normalised message so a PDF
    // sent WITH a caption is captured (its media lives inside the envelope).
    const content = contentMessage(m.message);
    const normalized = { key: m.key, message: content };

    const body = extractText(content);
    const { mediaBase64, mediaMime } = await extractMedia(session, normalized);
    if (!body && !mediaBase64) {
        drop('empty');
        log.info({ tenant: session.tenant, id: m.key?.id || '' }, 'group message skipped — no extractable text or media');
        return;
    }

    // Who sent it. A message WE sent carries no participant — the sender is
    // the linked number itself, so name it explicitly instead of letting the
    // app fall back to an empty push name.
    const fromMe = Boolean(m.key?.fromMe);
    const ownNumber = String(session.number || '');
    const senderJid = fromMe
        ? (ownNumber ? `${ownNumber}@s.whatsapp.net` : '')
        : String(m.key?.participant || m.participant || '');

    const payload = {
        wa_message_id: waMessageId,
        chat_id: jid,
        chat_name: session.groups.find((g) => g.id === jid)?.name || '',
        // The raw identity beside the resolved phone (v24) — the group's own
        // jid is never a sender.
        sender_jid: senderJid && senderJid !== jid ? senderJid : '',
        sender_number: fromMe ? ownNumber : await groupSenderPhone(session, m, jid),
        // Whose message this is (v26). The reader forwards it either way; each
        // ingest endpoint decides what a self-sent message means — an invoice
        // posted from the linked number IS an operation, while the "Start"
        // group must not read the alerts we post there as rider starts.
        from_me: fromMe,
        sender_name: m.pushName || '',
        sent_at: Number(m.messageTimestamp || 0),
        body,
        media_base64: mediaBase64,
        media_mime: mediaMime,
    };

    // رقم واحد يقرأ عدة قروبات (v35): this chat's own ingest.
    const callbackUrl = routeFor(session, jid).callbackUrl;
    if (!callbackUrl) {
        drop('no_route');
        log.warn({ tenant: session.tenant, jid }, 'group message skipped — no ingest route for this chat');
        return;
    }

    const answer = await postCallback(session, callbackUrl, payload, 'ingest');

    // The app refused or errored (403 wrong token, 404 gate/domain, 500, or the
    // request never landed): the operation is LOST until the next pull, and
    // that used to happen in total silence. Keep the app's own answer — the
    // settings page renders it verbatim beside the reason.
    if (!answer.ok) {
        drop('callback_failed', answer.detail || '');

        // ...but it must NOT be lost (v25). Two safety nets, because the pull
        // button cannot save this message: "سحب العمليات الآن" walks history
        // BACKWARDS from the oldest message the session knows, so a message
        // newer than that anchor is never fetched again.
        //   1. ARCHIVE it — the pull replays archived operations the app does
        //      not know, from disk, before asking WhatsApp for anything; the
        //      id was never marked forwarded, so exactly this message returns.
        //   2. RETRY it — the same queue the replies use (30s × 20 ≈ 10
        //      minutes), which is what carries a message across a deploy
        //      window. It covered receipts but not the MONEY messages.
        session.archivePut(payload, m.key);
        saveArchiveSoon(session);
        enqueueCallbackRetry(session, callbackUrl, payload, 'ingest');

        return;
    }

    // الأرشيف المحلي — keep the operation replayable even after the app
    // deletes it: a later pull re-sends it from here, no WhatsApp involved.
    session.archivePut(payload, m.key);
    saveArchiveSoon(session);

    // متابعة البدء: the app's answer may ask for a reaction on the message it
    // just took (a rider's "Start" gets the 👍🏽). Best-effort — a failed
    // reaction never blocks the pipeline, and a duplicate never re-reacts
    // (the app answers `react` only for a freshly recorded message).
    const react = String(answer.body?.react || '');
    if (react && !answer.body?.duplicate) {
        try {
            await session.sock.sendMessage(jid, { react: { text: react, key: m.key } });
        } catch (err) {
            log.warn({ tenant: session.tenant, id: waMessageId, err: String(err) }, 'reaction failed');
        }
    }

    // The app answers `duplicate` for an operation already staged (one pulled
    // before this session's memory existed, or before a restart): remember it
    // exactly like a fresh one so the next replay skips it, and count it as
    // skipped rather than pulled — nothing new reached the review inbox.
    const duplicate = Boolean(answer.body?.duplicate);
    session.markForwarded(waMessageId);
    if (duplicate) {
        session.backfillSkipped++;
        // Not a failure, but not a new operation either — "the app already has
        // it" is exactly what the owner needs to read when a message they just
        // sent shows nowhere new.
        drop('duplicate');
    } else {
        session.backfillPulled++;
        session.lastForwardedAt = Math.floor(Date.now() / 1000);
        drop('');
    }
    saveMetaSoon(session);
}

// Forward a direct (1:1) text message to the business's dm callback — the log
// of rider replies to the delay-chase messages. Text only: replies are read by
// a human in the log screen, media adds nothing there. A reply whose phone
// cannot be resolved is LOGGED, never silently dropped — that silence was
// exactly the production bug this line of logging exists to catch.
async function handleDirectMessage(session, m, jid) {
    // Liveness diagnostics: every DM stamps lastDmSeenAt, and whatever kills
    // it stamps lastDmDrop — the app's settings popup renders both, so "where
    // do replies die?" is answerable from the UI instead of container logs.
    session.lastDmSeenAt = Math.floor(Date.now() / 1000);

    if (!session.dmCallbackUrl) {
        // The classic post-re-link gap: meta was wiped, no send has re-seeded
        // the callback yet — every reply would vanish invisibly without this.
        session.lastDmDrop = 'no_callback';
        log.warn({ tenant: session.tenant, jid }, 'dm reply dropped — no dmCallbackUrl configured');
        return;
    }

    // Text AND media both count: a rider often answers with a PHOTO of the
    // order (it carries the order number) — captioned or not. Only messages
    // with neither (stickers, audio, reactions) are dropped.
    const content = contentMessage(m.message);
    const body = extractText(content);
    const { mediaBase64, mediaMime } = await extractMedia(session, { key: m.key, message: content });
    if (!body && !mediaBase64) {
        session.lastDmDrop = 'no_text';
        return;
    }

    const waMessageId = m.key?.id || '';
    const phone = await directChatPhone(session, m, jid);
    if (!phone) {
        session.lastDmDrop = 'phone_unresolvable';
        log.warn({ tenant: session.tenant, jid, wa_message_id: waMessageId }, 'dm reply dropped — sender phone unresolvable');
        return;
    }

    log.info({ tenant: session.tenant, jid, wa_message_id: waMessageId, phone, hasMedia: Boolean(mediaBase64) }, 'forwarding dm reply');

    // Built once and reused for the retry — the two copies used to drift.
    const payload = {
        wa_message_id: waMessageId,
        sender_number: phone,
        sender_name: m.pushName || '',
        sent_at: Number(m.messageTimestamp || 0),
        body,
        // contextInfo: what this message replies to, and whether the rider
        // forwarded it. A thumbs-up answering "حطيته؟" is unreadable without
        // the quote, and a forwarded chat is the rider handing over evidence
        // rather than speaking for themselves.
        quoted_body: quotedText(m.message),
        forwarded: forwardedMessage(m.message),
        media_base64: mediaBase64,
        media_mime: mediaMime,
    };

    const result = await postCallback(session, session.dmCallbackUrl, payload, 'dm');

    if (!result.ok) {
        session.lastDmDrop = 'callback_failed';
        session.lastDmDropDetail = result.detail || '';
        enqueueCallbackRetry(session, session.dmCallbackUrl, payload, 'dm');
        return result;
    } else if (result.body?.status === 'ignored') {
        // Laravel accepted the POST but refused the record: the number
        // matched no chased rider and no registered rider.
        session.lastDmDrop = 'ignored_by_app';
        session.lastDmDropDetail = '';
        log.warn({ tenant: session.tenant, phone }, 'dm reply ignored by app — number matches no rider');
    } else {
        session.lastDmDrop = '';
        session.lastDmDropDetail = '';
        session.lastReplyAt = Math.floor(Date.now() / 1000);

        // المحادثة الخاصة للصيانة (v36): the app may claim a private message
        // as a maintenance photo and ask for the same 👍🏽 the group gets.
        // Best-effort, never on a duplicate.
        const react = String(result.body?.react || '');
        if (react && !result.body?.duplicate) {
            try {
                await session.sock.sendMessage(jid, { react: { text: react, key: m.key } });
            } catch (err) {
                log.warn({ tenant: session.tenant, id: waMessageId, err: String(err) }, 'dm reaction failed');
            }
        }
    }

    return result;
}

// The sender's PHONE from a direct chat. A PN chat carries it in the jid. A
// LID-era chat ("…@lid") hides it: rc13 puts the phone jid on the key as
// `remoteJidAlt` for 1:1 chats — built from the stanza's sender_pn /
// participant_pn / peer_recipient_pn attrs (baileys/lib/Utils/
// decode-wa-message.js:69-95 + 178-181). The rc13 key type has NO `senderPn`,
// and `participantAlt` is set for GROUP keys only (lib/Types/Message.d.ts:
// 18-26; decode-wa-message.js:187) — both stay here only as legacy fallbacks.
// When the stanza carried no alt attr, the socket's LID store still knows the
// mapping: signalRepository.lidMapping.getPNForLID() (lib/Signal/
// lid-mapping.d.ts:15) answers from cached envelope mappings or a USync
// lookup, returning a device-suffixed jid ("<user>:<device>@s.whatsapp.net",
// lib/Signal/lid-mapping.js:229) — so the device part is stripped too.
async function directChatPhone(session, m, jid) {
    const phoneFromJid = (value) =>
        typeof value === 'string' && value.endsWith('@s.whatsapp.net')
            ? (value.split('@')[0] || '').split(':')[0] || ''
            : '';

    if (jid.endsWith('@s.whatsapp.net')) return phoneFromJid(jid);

    for (const alt of [m.key?.remoteJidAlt, m.key?.senderPn, m.key?.participantAlt]) {
        const phone = phoneFromJid(alt);
        if (phone) return phone;
    }

    try {
        const pn = await session.sock?.signalRepository?.lidMapping?.getPNForLID(jid);
        const phone = phoneFromJid(pn || '');
        if (phone) return phone;
    } catch (err) {
        log.warn({ tenant: session.tenant, jid, err: String(err) }, 'lid → phone lookup failed');
    }

    return '';
}

// How long the group-metadata participant map is trusted before a refetch is
// allowed. Stamped even on failure so an unresolvable sender can never turn
// every message into a metadata request.
const GROUP_PARTICIPANTS_TTL_MS = 10 * 60 * 1000;

// LID → phone through the group's own METADATA (v22): Baileys 7 lists every
// participant with its phoneNumber beside the hidden LID. Cached per session.
async function lidPhoneFromGroupMetadata(session, groupJid, lid) {
    const now = Date.now();

    if (now - (session.groupParticipantsAt || 0) > GROUP_PARTICIPANTS_TTL_MS
        && typeof session.sock?.groupMetadata === 'function') {
        session.groupParticipantsAt = now;

        try {
            const meta = await session.sock.groupMetadata(groupJid);
            session.groupParticipants = new Map();
            for (const p of meta?.participants || []) {
                const id = String(p?.id || '');
                const phone = String(p?.phoneNumber || p?.jid || '');
                if (id.endsWith('@lid') && phone.endsWith('@s.whatsapp.net')) {
                    session.groupParticipants.set(id, (phone.split('@')[0] || '').split(':')[0]);
                }
            }
        } catch (err) {
            log.warn({ tenant: session.tenant, groupJid, err: String(err) }, 'group metadata fetch failed');
        }
    }

    return session.groupParticipants.get(lid) || '';
}

// The sender's PHONE for a GROUP message. A PN participant carries it in the
// jid; a LID-era participant ("…@lid") hides it — resolved in order of
// reliability: the stanza's alt attrs (participantAlt / senderPn), the
// socket's LID store, then the group METADATA's participant list (v22), which
// carries every member's real number. Falls back to the raw participant
// digits so an unresolvable sender still arrives labelled rather than empty.
//
// v23: the sender rides key.participant on LIVE messages, but a HISTORY-synced
// message often carries it only on the envelope's own participant field — and
// sometimes not at all. The GROUP's jid is NEVER the sender: the old `|| jid`
// fallback forwarded the group id as a phone-looking sender_number
// ("1203633…") that could match nobody — an unknown sender now arrives EMPTY,
// so the app's push-name fallback (or the reviewer) takes over honestly.
async function groupSenderPhone(session, m, jid) {
    const participant = String(m.key?.participant || m.participant || '');
    const phoneFromJid = (value) =>
        typeof value === 'string' && value.endsWith('@s.whatsapp.net')
            ? (value.split('@')[0] || '').split(':')[0] || ''
            : '';

    if (participant === '' || participant === jid) return '';

    if (participant.endsWith('@s.whatsapp.net')) return phoneFromJid(participant);

    if (participant.endsWith('@lid')) {
        for (const alt of [m.key?.participantAlt, m.key?.senderPn]) {
            const phone = phoneFromJid(alt);
            if (phone) return phone;
        }

        try {
            const pn = await session.sock?.signalRepository?.lidMapping?.getPNForLID(participant);
            const phone = phoneFromJid(pn || '');
            if (phone) return phone;
        } catch (err) {
            log.warn({ tenant: session.tenant, participant, err: String(err) }, 'group lid → phone lookup failed');
        }

        const fromMeta = await lidPhoneFromGroupMetadata(session, jid, participant);
        if (fromMeta) return fromMeta;
    }

    return participant.split('@')[0] || '';
}

// A proto timestamp as unix seconds: plain number, numeric string, or a Long
// (protobufjs) — anything else, or a non-positive value, is 0.
function unixOf(value) {
    const n = Number(value?.toNumber ? value.toNumber() : value);
    return Number.isFinite(n) && n > 0 ? Math.floor(n) : 0;
}

// WebMessageInfo.Status → our ack label. rc13 stamps NUMERIC statuses
// (verified at runtime: proto.WebMessageInfo.Status = {ERROR:0, PENDING:1,
// SERVER_ACK:2, DELIVERY_ACK:3, READ:4, PLAYED:5}); the names are accepted
// too as cheap insurance against a build that serialises the enum.
function ackStatusOf(status) {
    const names = { SERVER_ACK: 2, DELIVERY_ACK: 3, READ: 4, PLAYED: 5 };
    const numeric = typeof status === 'number' ? status : (names[String(status)] ?? Number(status));
    if (!Number.isFinite(numeric)) return null;
    return numeric >= 4 ? 'read' : numeric >= 3 ? 'delivered' : null;
}

// Forward a delivery (✓✓) or read receipt for a message WE sent in a direct
// chat. rc13 emits 1:1 receipts on 'messages.update' with a numeric
// proto.WebMessageInfo.Status — 3 = delivered, 4 = read — and the receipt's
// own unix time in update.messageTimestamp (emission: baileys/lib/Socket/
// messages-recv.js:1198-1203; receipt-type → status map: lib/Utils/
// generics.js:265-281). The receipt's key keeps fromMe=true and the chat jid
// (PN or LID) in remoteJid (messages-recv.js:1161-1172).
async function handleAck(session, u) {
    if (!session.dmCallbackUrl) return;
    if (!u.key?.fromMe) return;

    const jid = String(u.key?.remoteJid || '');
    if (!jid.endsWith('@s.whatsapp.net') && !jid.endsWith('@lid')) return;

    const ackStatus = ackStatusOf(u.update?.status);
    if (!ackStatus) return;

    await forwardAck(session, jid, u.key?.id || '', ackStatus, unixOf(u.update?.messageTimestamp));
}

// The 'message-receipt.update' twin of handleAck (see the listener's comment):
// proto.IUserReceipt marks reads with readTimestamp/playedTimestamp and plain
// delivery with receiptTimestamp (baileys/WAProto/index.d.ts:13396-13403).
async function handleReceiptAck(session, key, receipt) {
    if (!session.dmCallbackUrl) return;
    if (!key?.fromMe) return;

    const jid = String(key?.remoteJid || '');
    if (!jid.endsWith('@s.whatsapp.net') && !jid.endsWith('@lid')) return;

    const readAt = unixOf(receipt?.readTimestamp) || unixOf(receipt?.playedTimestamp);
    const deliveredAt = unixOf(receipt?.receiptTimestamp);
    const ackStatus = readAt > 0 ? 'read' : deliveredAt > 0 ? 'delivered' : null;
    if (!ackStatus) return;

    await forwardAck(session, jid, key?.id || '', ackStatus, readAt > 0 ? readAt : deliveredAt);
}

// One ack POST to Laravel, logged — the log line is the production evidence
// that a receipt made it out of the reader (there was zero visibility here).
async function forwardAck(session, jid, waMessageId, ackStatus, ackAt) {
    if (!waMessageId) return;

    log.info({ tenant: session.tenant, jid, wa_message_id: waMessageId, ack_status: ackStatus }, 'forwarding ack');
    session.lastAckAt = Math.floor(Date.now() / 1000);

    const payload = {
        type: 'ack',
        wa_message_id: waMessageId,
        ack_status: ackStatus,
        ack_at: ackAt > 0 ? ackAt : Math.floor(Date.now() / 1000),
    };
    const result = await postCallback(session, session.dmCallbackUrl, payload, 'ack');
    if (!result.ok) enqueueCallbackRetry(session, session.dmCallbackUrl, payload, 'ack');
}

// ---- Callback retry queue: deploys must delay messages, never eat them ----

const CALLBACK_RETRY_MS = 30 * 1000; // flush cadence
const CALLBACK_RETRY_MAX = 20; // × 30s ≈ 10 minutes of coverage
const CALLBACK_RETRY_CAP = 200; // per-session queue bound

function enqueueCallbackRetry(session, url, payload, label) {
    if (!url) return;
    if (session.pendingCallbacks.length >= CALLBACK_RETRY_CAP) session.pendingCallbacks.shift();
    session.pendingCallbacks.push({ url, payload, label, attempts: 1 });
    log.info({ tenant: session.tenant, label, queued: session.pendingCallbacks.length }, 'callback queued for retry');
}

async function flushPendingCallbacks() {
    for (const session of sessions.values()) {
        if (!session.pendingCallbacks.length) continue;

        const queue = session.pendingCallbacks;
        session.pendingCallbacks = [];

        for (const item of queue) {
            const result = await postCallback(session, item.url, item.payload, `${item.label} retry`);

            if (result.ok) {
                if (item.label === 'dm') {
                    session.lastReplyAt = Math.floor(Date.now() / 1000);
                    if (session.lastDmDrop === 'callback_failed') {
                        session.lastDmDrop = '';
                        session.lastDmDropDetail = '';
                    }
                }

                // A group operation that only landed on the retry is a NORMAL
                // arrival: remember its id (so no pull re-sends it), count it,
                // move the heartbeat, and clear the failure the settings page
                // is showing — the pipe recovered on its own.
                if (item.label === 'ingest') {
                    const id = String(item.payload?.wa_message_id || '');
                    if (id) session.markForwarded(id);

                    if (result.body?.duplicate) {
                        session.backfillSkipped++;
                    } else {
                        session.backfillPulled++;
                        session.lastForwardedAt = Math.floor(Date.now() / 1000);
                    }

                    if (session.lastGroupDrop === 'callback_failed') {
                        session.lastGroupDrop = '';
                        session.lastGroupDropDetail = '';
                    }

                    saveMetaSoon(session);
                }

                continue;
            }

            item.attempts += 1;
            if (item.attempts <= CALLBACK_RETRY_MAX) {
                session.pendingCallbacks.push(item);
            } else {
                log.warn({ tenant: session.tenant, label: item.label, detail: result.detail }, 'callback retry gave up');
            }
        }
    }
}

setInterval(() => { flushPendingCallbacks().catch((err) => log.error({ err: String(err) }, 'retry flush crashed')); }, CALLBACK_RETRY_MS);

// One authenticated POST back to Laravel (ingest or dm), with a hard timeout.
// Returns {ok, body}: ok = HTTP accepted; body = Laravel's parsed JSON answer
// (the dm endpoint replies {"status":"ok"|"ignored"} — the difference matters
// for the reply-liveness diagnostics).
async function postCallback(session, url, payload, label) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    try {
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Reader-Token': session.ingestToken },
            body: JSON.stringify(payload),
            signal: controller.signal,
        });
        const text = await res.text().catch(() => '');
        let body = null;
        try { body = JSON.parse(text); } catch { /* non-json response */ }
        if (!res.ok) log.warn({ tenant: session.tenant, status: res.status, body: text.slice(0, 300) }, `${label} rejected`);
        // detail: what the app actually answered — the settings popup shows it,
        // so a failing callback is diagnosable without container logs.
        return { ok: res.ok, body, detail: res.ok ? '' : `HTTP ${res.status}: ${text.slice(0, 180)}` };
    } catch (err) {
        log.error({ tenant: session.tenant, err: String(err) }, `${label} post failed`);
        return { ok: false, body: null, detail: String(err).slice(0, 180) };
    } finally {
        clearTimeout(timer);
    }
}

// Peel the common WhatsApp wrappers to reach the actual content message: a
// disappearing message (ephemeralMessage), a view-once photo, and — the one that
// bit us — a document sent WITH a caption (documentWithCaptionMessage), whose
// documentMessage lives one level down.
function contentMessage(message) {
    let m = message || {};
    for (let i = 0; i < 4; i++) {
        const inner =
            m.ephemeralMessage?.message ||
            m.viewOnceMessage?.message ||
            m.viewOnceMessageV2?.message ||
            m.viewOnceMessageV2Extension?.message ||
            m.documentWithCaptionMessage?.message;
        if (!inner) break;
        m = inner;
    }
    return m;
}

function extractText(message) {
    if (!message) return '';
    return (
        message.conversation ||
        message.extendedTextMessage?.text ||
        message.imageMessage?.caption ||
        message.documentMessage?.caption ||
        message.videoMessage?.caption ||
        ''
    );
}

// WhatsApp hangs contextInfo off whichever node carries the message, so find
// the first node that has one rather than guessing the message type.
function messageContext(message) {
    const inner = contentMessage(message);
    if (!inner || typeof inner !== 'object') return null;
    for (const node of Object.values(inner)) {
        if (node && typeof node === 'object' && node.contextInfo) return node.contextInfo;
    }
    return null;
}

// The text of the message this one replies to ('' when it replies to nothing,
// or to something with no text of its own — a photo, a sticker).
function quotedText(message) {
    const quoted = messageContext(message)?.quotedMessage;
    return quoted ? extractText(contentMessage(quoted)) : '';
}

// Forwarded at all — WhatsApp reports "forwarded" as a flag on the first hop
// and as a hop count after that, so accept either.
function forwardedMessage(message) {
    const context = messageContext(message);
    return Boolean(context?.isForwarded) || Number(context?.forwardingScore || 0) > 0;
}

async function extractMedia(session, m) {
    const image = m.message?.imageMessage;
    const doc = m.message?.documentMessage;
    const node = image || (doc && /image\/|pdf/.test(doc.mimetype || '') ? doc : null);
    if (!node) return { mediaBase64: null, mediaMime: null };
    if (Number(node.fileLength || 0) > MAX_MEDIA_BYTES) return { mediaBase64: null, mediaMime: null };

    try {
        const buffer = await downloadMediaMessage(m, 'buffer', {}, { logger: pino({ level: 'silent' }), reuploadRequest: session.sock.updateMediaMessage });
        if (buffer.length > MAX_MEDIA_BYTES) return { mediaBase64: null, mediaMime: null };
        return { mediaBase64: buffer.toString('base64'), mediaMime: node.mimetype || 'image/jpeg' };
    } catch (err) {
        // Counted during a pull (v41): an old photo WhatsApp no longer serves
        // and the phone cannot re-upload is the usual reason a history walk
        // brings text and no pictures.
        if (session.backfillStatus === 'running') session.backfillMediaFailed++;
        session.lastMediaError = String(err).slice(0, 180);
        log.warn({ tenant: session.tenant, err: String(err) }, 'media download failed');
        return { mediaBase64: null, mediaMime: null };
    }
}

function wipe(tenant) {
    const session = sessions.get(tenant);
    if (session?.groupPoll) clearInterval(session.groupPoll);
    if (session?.reconnectTimer) clearTimeout(session.reconnectTimer);
    if (session?.sock) {
        try {
            session.sock.end(undefined);
        } catch { /* ignore */ }
    }
    sessions.delete(tenant);
    try {
        rmSync(join(DATA_DIR, tenant), { recursive: true, force: true });
    } catch { /* ignore */ }
}

// Re-open every persisted session on boot, so a restart needs no re-scan.
async function resumeAll() {
    for (const tenant of readdirSync(DATA_DIR, { withFileTypes: true }).filter((d) => d.isDirectory()).map((d) => d.name)) {
        const meta = loadMeta(tenant);
        if (!meta) continue;
        try {
            await startSession(tenant, meta);
            log.info({ tenant }, 'resumed session');
        } catch (err) {
            log.error({ tenant, err: String(err) }, 'resume failed');
        }
    }
}

// ---- HTTP API ----

const app = express();
// Sized off the SEND ceiling: base64 inflates bytes by 4/3, plus room for the
// rest of the payload. A 2 MB cap silently refused every attachment bigger
// than a photo with a 413 that never reached a screen.
app.use(express.json({ limit: `${Math.ceil((MAX_SEND_MEDIA_BYTES * 4) / 3 / (1024 * 1024)) + 2}mb` }));

// Every route is authenticated with the shared reader secret.
app.use((req, res, next) => {
    if (SECRET === '' || req.get('X-Reader-Secret') !== SECRET) {
        return res.status(403).json({ error: 'forbidden' });
    }
    next();
});

app.get('/health', (_req, res) => res.json({
    ok: true,
    version: READER_VERSION,
    library: BAILEYS_VERSION,
    sessions: sessions.size,
    // Answers "the container is up — so why is nothing working?" (v34).
    diskFree: diskFreeBytes(),
    lastWriteError,
    lastWriteErrorAt: lastWriteErrorAt || null,
}));

app.post('/sessions', async (req, res) => {
    // dmCallbackUrl is accepted at CONNECT time too (v15) — the operations
    // sessions have no "save group" knob to re-seed it later, so a reply
    // arriving before the first send must already know where to forward.
    const { tenant, number, callbackUrl, ingestToken, chatId, chatIds, chatRoutes, dmHistory, groupCatchUp, historySince, dmCallbackUrl } = req.body || {};
    if (!tenant) return res.status(422).json({ error: 'tenant required' });
    try {
        const session = await startSession(String(tenant), { number, callbackUrl, ingestToken, chatId, chatIds, chatRoutes, dmHistory, groupCatchUp, historySince, dmCallbackUrl });
        res.json(session.snapshot());
    } catch (err) {
        log.error({ err: String(err) }, 'start session failed');
        res.status(500).json({ error: 'start_failed' });
    }
});

app.get('/sessions/:tenant', (req, res) => {
    const session = sessions.get(req.params.tenant);
    res.json(session ? session.snapshot() : { version: READER_VERSION, library: BAILEYS_VERSION, status: 'disconnected', groups: [] });
});

app.patch('/sessions/:tenant', (req, res) => {
    const session = sessions.get(req.params.tenant);
    if (!session) return res.status(404).json({ error: 'no_session' });
    // A group, or nothing. Refused rather than silently blanked, so the app
    // is told its choice did not take instead of quietly reading no group.
    if (req.body?.chatId !== undefined) {
        const next = String(req.body.chatId || '');
        if (next !== '' && !isGroupJid(next)) return res.status(422).json({ error: 'not_a_group' });
        session.chatId = next;
    }
    // v31: the extra tracked groups (متابعة البدء reads one per platform) —
    // same rule as the primary chat, a private jid is refused outright.
    if (req.body?.chatIds !== undefined) {
        const wanted = normalizeChatIds(req.body.chatIds);
        if (wanted.some((id) => !isGroupJid(id))) return res.status(422).json({ error: 'not_a_group' });
        session.chatIds = wanted;
    }
    // v35: the per-chat routes — replaced wholesale; a private jid is refused.
    if (req.body?.chatRoutes !== undefined && req.body?.chatRoutes !== null) {
        const wanted = req.body.chatRoutes;
        if (wanted && typeof wanted === 'object' && !Array.isArray(wanted)
            && Object.keys(wanted).some((id) => !isGroupJid(String(id)))) {
            return res.status(422).json({ error: 'not_a_group' });
        }
        session.chatRoutes = normalizeChatRoutes(wanted);
    }
    // v37: the private chats whose history is read — replaced wholesale.
    if (req.body?.dmHistory !== undefined && req.body?.dmHistory !== null) {
        session.dmHistory = normalizeDmHistory(req.body.dmHistory);
    }
    // v25: whether this session's group takes offline-delivered messages too.
    if (req.body?.groupCatchUp !== undefined) session.groupCatchUp = Boolean(req.body.groupCatchUp);
    if (req.body?.historySince !== undefined) session.historySince = normalizeHistorySince(req.body.historySince);
    // v19: the group-ingest callback can be (re)pointed on a LIVE session —
    // the operations session gains its group AFTER connect (متابعة البدء), so
    // the group save must carry the ingest URL too; absent leaves it untouched.
    if (req.body?.callbackUrl !== undefined && req.body?.callbackUrl !== null) {
        session.callbackUrl = String(req.body.callbackUrl || '');
    }
    // Set OR clear the reply callback from "حفظ القروب" too (v16: an explicit
    // empty string clears it — the Invoice session forwards no direct replies
    // after the invoice/operations hard split); absent leaves it untouched.
    if (req.body?.dmCallbackUrl !== undefined && req.body?.dmCallbackUrl !== null) {
        session.dmCallbackUrl = String(req.body.dmCallbackUrl || '');
    }
    saveMeta(session);
    res.json(session.snapshot());
});

// Send a text message from the business's own connected number — the automatic
// delay-chase messages (رسائل التأخير). `to` is a bare phone (digits, intl
// format); dmCallbackUrl, when given, is persisted so the recipient's direct
// replies forward back to Laravel.
app.post('/sessions/:tenant/send', async (req, res) => {
    const session = sessions.get(req.params.tenant);
    if (!session) return res.status(404).json({ error: 'no_session' });
    if (session.status !== 'connected' || !session.sock) {
        return res.status(409).json({ error: 'not_connected' });
    }

    // `to` is a bare phone (digits) — or a full jid (e.g. "...@g.us" for the
    // escalation GROUP posts), which is used as-is and skips the onWhatsApp
    // registration check (that lookup is for user numbers only).
    const rawTo = String(req.body?.to || '');
    const isJid = rawTo.includes('@');
    const to = isJid ? rawTo : rawTo.replace(/\D+/g, '');
    const body = String(req.body?.body || '');
    if (!to || !body) return res.status(422).json({ error: 'to_and_body_required' });

    if (req.body?.dmCallbackUrl && session.dmCallbackUrl !== String(req.body.dmCallbackUrl)) {
        session.dmCallbackUrl = String(req.body.dmCallbackUrl);
        saveMeta(session);
    }

    // Baileys "sends" to a non-WhatsApp number without complaining — the
    // message just evaporates while the caller logs a success. Verify the
    // number is registered first (bare-number form, the documented usage) and
    // send to its CANONICAL jid, so a wrong rider phone comes back as a
    // readable failure instead of a lie. A lookup that itself ERRORS is not
    // proof the number is missing — log it and fall through to a plain send
    // rather than false-blocking a valid number.
    let jid = isJid ? to : `${to}@s.whatsapp.net`;
    if (!isJid) {
        try {
            const [lookup] = await session.sock.onWhatsApp(to);
            if (!lookup?.exists) {
                return res.status(409).json({ error: 'not_on_whatsapp' });
            }
            jid = lookup.jid || jid;
        } catch (err) {
            log.warn({ tenant: session.tenant, to, err: String(err) }, 'onWhatsApp lookup failed — sending unverified');
        }
    }

    // An attached image (media_base64 + media_mime) goes out as a photo with
    // the text as its caption — the escalation path forwarding a rider's
    // order photo to the group/supervisors. Size-capped like the ingest side.
    let payload = { text: body };
    const mediaBase64 = String(req.body?.media_base64 || '');
    if (mediaBase64) {
        const buffer = Buffer.from(mediaBase64, 'base64');
        if (buffer.length === 0 || buffer.length > MAX_SEND_MEDIA_BYTES) {
            return res.status(422).json({ error: 'media_invalid' });
        }
        payload = /^image\//.test(String(req.body?.media_mime || 'image/jpeg'))
            ? { image: buffer, caption: body }
            : { document: buffer, mimetype: String(req.body.media_mime), fileName: String(req.body?.media_filename || 'attachment'), caption: body };
    }

    // `mentions` (bare phone digits) @-tags group members: WhatsApp only pings
    // them when the mentioned jid is listed here AND the body carries the
    // matching "@<digits>" text — the caller composes the body, we supply the
    // jids. Ignored for 1:1 sends where mentioning is meaningless.
    const mentionDigits = Array.isArray(req.body?.mentions) ? req.body.mentions : [];
    if (mentionDigits.length && jid.endsWith('@g.us')) {
        payload.mentions = mentionDigits
            .map((n) => String(n).replace(/\D+/g, ''))
            .filter(Boolean)
            .map((n) => `${n}@s.whatsapp.net`);
    }

    try {
        const sent = await session.sock.sendMessage(jid, payload);
        log.info({ tenant: session.tenant, jid, id: sent?.key?.id || '', hasMedia: Boolean(mediaBase64) }, 'message sent');
        res.json({ ok: true, waMessageId: sent?.key?.id || '' });
    } catch (err) {
        log.warn({ tenant: session.tenant, jid, err: String(err) }, 'send failed');
        res.status(502).json({ error: 'send_failed', detail: String(err).slice(0, 300) });
    }
});

// قنوات واتساب — إضافة ssouq-guide على نسخة souq-saas (أعِدها إن نسختَ server.js من هناك):
// GET /sessions/:tenant/newsletter?invite=<رمز رابط القناة> أو ?jid=<…@newsletter> ← {ok, id, name,
// subscribers, role, invite}. الرابط whatsapp.com/channel/<الرمز> لا يحمل معرّف القناة، والنشر فيها يحتاجه:
// POST /sessions/:tenant/send {to: '<المعرّف>@newsletter', body} كأي محادثة. و`role` دور الرقم المربوط
// فيها (OWNER · ADMIN · SUBSCRIBER · GUEST) — والنشر للمالك والمشرفين وحدهم.
app.get('/sessions/:tenant/newsletter', async (req, res) => {
    const session = sessions.get(req.params.tenant);
    if (!session) return res.status(404).json({ error: 'no_session' });
    if (session.status !== 'connected' || !session.sock) {
        return res.status(409).json({ error: 'not_connected' });
    }
    const jid = String(req.query.jid || '').trim();
    const invite = String(req.query.invite || '').trim();
    if (jid ? !/^\d{5,30}@newsletter$/.test(jid) : !/^[A-Za-z0-9]{10,40}$/.test(invite)) {
        return res.status(422).json({ error: 'invalid' });
    }
    try {
        const meta = await session.sock.newsletterMetadata(jid ? 'jid' : 'invite', jid || invite);
        if (!meta?.id) return res.status(404).json({ error: 'channel_not_found' });
        // rc13 يعيد ردّ الخادم كما هو (thread_metadata.name.text …)، والأنواع تصفه مسطّحًا — يُقرأ الشكلان
        const thread = meta.thread_metadata || {};
        const text = (v) => (v && typeof v === 'object' ? v.text : v) || '';
        res.json({
            ok: true,
            id: String(meta.id),
            name: String(text(thread.name) || text(meta.name)),
            subscribers: Number(thread.subscribers_count ?? meta.subscribers ?? 0) || 0,
            role: String(meta.viewer_metadata?.role || ''),
            invite: String(thread.invite || meta.invite || ''),
        });
    } catch (err) {
        log.warn({ tenant: session.tenant, jid, invite, err: String(err) }, 'newsletter lookup failed');
        const code = Number(err?.output?.statusCode || 0);
        res.status(code === 404 ? 404 : 502).json({
            error: code === 404 ? 'channel_not_found' : 'lookup_failed',
            detail: String(err).slice(0, 300),
        });
    }
});

// One-click reverse-channel test (فحص استقبال الردود): POST a `type:"ping"`
// to the stored dmCallbackUrl exactly like a real reply/receipt would go, and
// return what the app ACTUALLY answered — so "why do replies die?" is settled
// from the settings popup in one tap instead of waiting for a rider message.
app.post('/sessions/:tenant/test-callback', async (req, res) => {
    const session = sessions.get(req.params.tenant);
    if (!session) return res.status(404).json({ error: 'no_session' });
    if (!session.dmCallbackUrl) {
        return res.json({ ok: false, error: 'no_callback', detail: '', url: '' });
    }

    const result = await postCallback(session, session.dmCallbackUrl, { type: 'ping' }, 'ping');
    const ok = result.ok && result.body?.status === 'ok';

    // A successful live check supersedes any stale failure from an earlier
    // message (e.g. one that arrived mid-deploy) — clear the drop line so the
    // popup reflects the channel's CURRENT truth.
    if (ok && session.lastDmDrop === 'callback_failed') {
        session.lastDmDrop = '';
        session.lastDmDropDetail = '';
    }

    res.json({
        ok,
        error: result.ok ? (result.body?.status === 'ok' ? '' : 'unexpected_answer') : 'callback_failed',
        detail: result.detail || (result.ok && result.body?.status !== 'ok' ? JSON.stringify(result.body).slice(0, 180) : ''),
        url: session.dmCallbackUrl,
    });
});

// سحب العمليات — pull the Invoice group's past messages from a date WITHOUT
// re-linking the number: set the boundary, then walk WhatsApp's history
// backwards from the oldest message this session knows. Answers immediately
// (the walk continues on 'messaging-history.set'); the settings page polls the
// snapshot for what it produced. Operations already pulled are skipped, so a
// repeated pull is safe and cheap.
app.post('/sessions/:tenant/backfill', async (req, res) => {
    const session = sessions.get(req.params.tenant);
    if (!session) return res.status(404).json({ error: 'no_session' });
    if (session.status !== 'connected' || !session.sock) {
        return res.status(409).json({ error: 'not_connected' });
    }
    // قروب واحد (v35) أو قائمة (v37): a pull scoped to chosen chats — tracked
    // groups and/or listed private chats — carries its own since and never
    // touches the session-wide boundary, so reading the maintenance group
    // (and the technicians' chats) from the first message never replays
    // the money group.
    const scopedChats = [...new Set([String(req.body?.chatId || ''), ...(Array.isArray(req.body?.chatIds) ? req.body.chatIds.map(String) : [])].filter(Boolean))];
    const scopedChat = scopedChats.length ? scopedChats[0] : '';

    if (!hasGroupReader(session) && !scopedChats.some((jid) => readsDmHistory(session, jid))) {
        return res.status(409).json({ error: 'no_group' });
    }
    if (scopedChats.some((jid) => !readsChat(session, jid) && !readsDmHistory(session, jid))) {
        return res.status(422).json({ error: 'not_tracked' });
    }

    let since;
    if (scopedChat !== '') {
        since = normalizeHistorySince(req.body?.since);
    } else {
        if (req.body?.since !== undefined) session.historySince = normalizeHistorySince(req.body.since);
        since = session.historySince;
    }
    if (since === null) return res.status(422).json({ error: 'since_required' });

    if (session.backfillTimer) {
        clearTimeout(session.backfillTimer);
        session.backfillTimer = null;
    }
    session.backfillStatus = 'running';
    session.backfillSince = since;
    session.backfillAt = Math.floor(Date.now() / 1000);
    session.backfillPulled = 0;
    session.backfillSkipped = 0;
    session.backfillMediaFailed = 0;
    session.lastMediaError = '';
    session.backfillRounds = 0;
    session.backfillRefusals = [];

    // كل قروب على حدة (v32): the walk visits every tracked chat in turn, each
    // anchored on ITS OWN newest message. A history request is anchored on a
    // message, and a message belongs to one chat — so a single shared anchor
    // pulled whichever group owned it and left the others untouched ("ضغطت
    // سحب في القروب الثاني ولم يأتِ شيء").
    //
    // ابدأ من الأحدث لا من الأقدم (v27): starting each chat at its newest
    // message makes the first batch the most recent one, and the walk then
    // works back to the requested date. Messages we already have are skipped
    // before their media is downloaded, so re-walking them is cheap.
    session.backfillQueue = scopedChats.length ? scopedChats : trackedChats(session);
    session.backfillChats = [...session.backfillQueue];
    session.backfillChat = '';

    // إعادة المحذوف من الأرشيف أولًا (v21) — deterministic and local: deleted
    // operations return from disk whatever WhatsApp does next. Counted before
    // the replay starts so the answer can already say the pull produces work.
    const replayable = replayableCount(session, since, session.backfillChats);
    const replay = replayArchived(session);

    const started = await advanceBackfill(session);

    // The WhatsApp walk closes its own lifecycle when it started; otherwise
    // the pull ends when the replay does — as "done" when the replay had
    // anything to re-send, else with the walk's honest refusal (no_anchor /
    // unsupported), so "nothing older will come" is never masked.
    replay.then(() => {
        if (!started) {
            // Every chat refused: the pull is already closed with the honest
            // reason — a productive replay overwrites it, because the pull DID
            // produce even though WhatsApp handed nothing over.
            if (replayable > 0) session.backfillStatus = 'done';
        }
        saveMeta(session);
    });

    res.json({ ok: started || replayable > 0, ...session.snapshot() });
});

// The pulled-ids memory itself (v20) — Laravel reads it before a pull to
// sweep ids it no longer recognizes (operations deleted before the forget
// hook existed), so the pull self-heals past deletions.
app.get('/sessions/:tenant/forwarded', (req, res) => {
    const session = sessions.get(req.params.tenant);
    if (!session) return res.status(404).json({ error: 'no_session' });
    res.json({ ids: session.forwardedIds });
});

// The pulled-ids memory itself (v20) — Laravel reads it before a pull to
// sweep ids it no longer recognizes (operations deleted before the forget
// hook existed), so the pull self-heals past deletions.
app.get('/sessions/:tenant/forwarded', (req, res) => {
    const session = sessions.get(req.params.tenant);
    if (!session) return res.status(404).json({ error: 'no_session' });
    res.json({ ids: session.forwardedIds });
});

// Forget forwarded ids (v19) — Laravel calls this when operations are deleted
// from the review inbox, so the NEXT pull re-forwards them instead of skipping
// "already pulled". Persisted immediately: a restart must not resurrect the
// memory of a deleted operation.
app.post('/sessions/:tenant/forget', (req, res) => {
    const session = sessions.get(req.params.tenant);
    if (!session) return res.status(404).json({ error: 'no_session' });
    const ids = Array.isArray(req.body?.ids) ? req.body.ids.map(String) : [];
    if (ids.length === 0) return res.status(422).json({ error: 'ids_required' });
    const forgotten = session.forget(ids);
    if (forgotten > 0) saveMeta(session);
    res.json({ ok: true, forgotten });
});

// علامة على الرسالة (v29) — put a reaction on a message the session already
// forwarded, at any time after the fact. WhatsApp treats a second reaction
// from the same account on the same message as a REPLACEMENT, which is what
// makes the operation's mark tell its state: 👍🏽 when it was pulled into
// العمليات المالية, ❗ while it is missing data, then ✅ once it is approved.
//
// The key is taken from the local archive whenever the message is still in it
// (exact, including the LID-era participant). Older than that, it is rebuilt
// from what the caller kept beside the operation — chat id, sender jid and
// whether the linked number wrote it itself.
app.post('/sessions/:tenant/react', async (req, res) => {
    const session = sessions.get(req.params.tenant);
    if (!session) return res.status(404).json({ error: 'no_session' });
    if (session.status !== 'connected' || !session.sock) {
        return res.status(409).json({ error: 'not_connected' });
    }

    const messageId = String(req.body?.message_id || '');
    const chatId = String(req.body?.chat_id || '');
    // An empty emoji is the documented way to REMOVE a reaction — allowed.
    const emoji = String(req.body?.emoji ?? '');
    if (!messageId || !chatId) return res.status(422).json({ error: 'message_and_chat_required' });

    const archived = session.archive.find((p) => p.wa_message_id === messageId);
    const participant = String(req.body?.participant || '');
    const fromMe = Boolean(req.body?.from_me);
    const key = archived?.msg_key || {
        remoteJid: chatId,
        id: messageId,
        fromMe,
        ...(participant && !fromMe ? { participant } : {}),
    };

    try {
        await session.sock.sendMessage(key.remoteJid || chatId, { react: { text: emoji, key } });
        log.info({ tenant: session.tenant, id: messageId, emoji, keyed: Boolean(archived?.msg_key) }, 'reaction sent');
        res.json({ ok: true });
    } catch (err) {
        log.warn({ tenant: session.tenant, id: messageId, err: String(err) }, 'reaction failed');
        res.status(502).json({ error: 'react_failed', detail: String(err).slice(0, 300) });
    }
});

// Force an immediate re-fetch of the joined groups (the "Refresh groups" button).
app.post('/sessions/:tenant/refresh-groups', async (req, res) => {
    const session = sessions.get(req.params.tenant);
    if (!session) return res.status(404).json({ error: 'no_session' });
    await refreshGroups(session);
    res.json(session.snapshot());
});

app.delete('/sessions/:tenant', async (req, res) => {
    const tenant = req.params.tenant;
    const session = sessions.get(tenant);
    if (session?.sock) {
        try {
            await session.sock.logout();
        } catch { /* ignore */ }
    }
    wipe(tenant);
    res.json({ status: 'disconnected', groups: [] });
});

app.listen(PORT, async () => {
    log.info({ port: PORT }, 'whatsapp reader up');
    await resumeAll();
});

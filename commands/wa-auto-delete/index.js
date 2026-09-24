#!/usr/bin/env node
'use strict';

/*
 * WhatsApp auto-delete-on-reply
 *
 *   npm run setup     link WhatsApp (QR) and pick the chat – interactive
 *   npm run dry-run   watch the chat but only LOG what would be deleted
 *   npm start         run in the foreground
 *   npm run service   run 24/7 under pm2 (recommended)
 *   npm run status    show health of the running service
 */

if (parseInt(process.versions.node, 10) < 18) {
  console.error(`Node.js 18 or newer is required (you have ${process.versions.node}).`);
  process.exit(78);
}

const fs = require('fs');
const path = require('path');
const readline = require('readline');
const L = require('./lib');
const { WaDirect } = require('./wa');
const { Engine, planSweep, normalizeMessages, validateSettings, isTrigger, parseCommand, DEFAULT_SETTINGS } = require('./engine');

process.chdir(__dirname);

const log = L.logger;
const DATA = path.join(__dirname, 'data');
const P = {
  config: path.join(__dirname, 'config.json'),
  state: path.join(DATA, 'state.json'),
  status: path.join(DATA, 'status.json'),
  lock: path.join(DATA, 'run.lock'),
  qr: path.join(DATA, 'qr.png'),
  auth: path.join(DATA, 'session'),
  webCache: path.join(DATA, 'web-cache'),
};
const CLIENT_ID = 'autodelete';
const PROFILE_DIR = path.join(P.auth, `session-${CLIENT_ID}`);
const EXIT = { OK: 0, RESTART: 1, NEEDS_USER: 78 }; // pm2 is configured not to restart on 78

const args = process.argv.slice(2);
const MODE = args.includes('--setup') ? 'setup' : args.includes('--status') ? 'status' : 'service';
const FORCE_DRY_RUN = args.includes('--dry-run');
const INTERACTIVE = Boolean(process.stdin.isTTY && process.stdout.isTTY);
const SUPERVISED = process.env.pm_id !== undefined || process.env.WA_SUPERVISED === '1';
const ON_PHONE = process.env.WA_ON_PHONE === '1'; // set by the Termux "wa" command

if (ON_PHONE) {
  for (const k of ['log', 'error']) {
    const orig = console[k].bind(console);
    console[k] = (...a) => orig(...a.map((x) => (typeof x === 'string' ? L.phoneText(x) : x)));
  }
}

// ------------------------------------------------------------------ runtime state

let client = null;
let clientClosed = false;
let engine = null;
let config = null;
let settings = { ...DEFAULT_SETTINGS };
let state = null;
let phase = 'starting';
let isReady = false;
let readyCount = 0;
let serviceStarted = false;
let awaitingQr = false;
let shuttingDown = false;
let lastWaState = null;
let lastError = null;
let pageFailures = 0;
let notConnectedMinutes = 0;
let lastWatchdogTick = Date.now();
let initProgressAt = Date.now(); // last sign of login progress (QR shown, authenticated, loading)
let rejectionTimes = [];
const startedAt = Date.now();
const abort = new AbortController();
const timers = new Set();
const targetIds = new Set();
const wa = new WaDirect(() => (clientClosed ? null : client));
let authLogged = false;
let connectedSince = 0; // when the page first reported CONNECTED (for the direct-ready fallback)
let lastPageError = null;
let readyVia = null;

// ------------------------------------------------------------------ small helpers

async function safe(fn) {
  try { await fn(); } catch (e) {
    if (!shuttingDown) log.error('Unexpected error in background task:', L.errText(e), (e && e.stack ? `\n${e.stack.split('\n').slice(0, 4).join('\n')}` : ''));
  }
}
function later(ms, fn) {
  const t = setTimeout(() => { timers.delete(t); safe(fn); }, ms);
  timers.add(t);
  return t;
}
function every(ms, fn) {
  const t = setInterval(() => safe(fn), ms);
  timers.add(t);
  return t;
}
const sleep = (ms) => L.sleep(ms, abort.signal);
const randMs = ([a, b], unit) => L.randInt(a * unit, b * unit);

function setPhase(p) {
  phase = p;
  writeStatus();
}

// ------------------------------------------------------------------ state / status / config

function freshState() {
  return {
    version: 1, skip: {}, attempts: {}, rateEvents: [], pausedUntil: 0, totals: { deleted: 0 }, startupFailures: 0, browserPid: null,
    control: freshControl(),
  };
}

function freshControl() {
  // Your pause/resume switch (set from your phone). Survives restarts and reboots.
  return { paused: false, resumeAt: 0, activeSince: 0, lastCommandAt: 0, handled: [], pauseMsgId: null };
}

function loadState() {
  const { value, error } = L.readJson(P.state, null, { quarantine: true });
  if (error) log.warn(`State file problem: ${error}. Starting with fresh state.`);
  const base = freshState();
  if (!value || typeof value !== 'object') return base;
  const obj = (x) => (x && typeof x === 'object' && !Array.isArray(x) ? x : {});
  return {
    ...base,
    ...value,
    skip: obj(value.skip),
    attempts: obj(value.attempts),
    totals: { ...base.totals, ...obj(value.totals) },
    rateEvents: Array.isArray(value.rateEvents) ? value.rateEvents.filter(Number.isFinite) : [],
    pausedUntil: Number.isFinite(value.pausedUntil) ? value.pausedUntil : 0,
    startupFailures: Number.isInteger(value.startupFailures) ? value.startupFailures : 0,
    control: { ...freshControl(), ...obj(value.control), handled: Array.isArray((value.control || {}).handled) ? value.control.handled : [] },
  };
}

function saveState() {
  if (!state) return;
  try { L.writeJsonAtomic(P.state, state); } catch (e) { log.error('Could not save state:', L.errText(e)); }
}

function writeStatus() {
  const st = {
    updatedAt: new Date().toISOString(),
    pid: process.pid,
    phase,
    whatsappState: lastWaState,
    targetChat: config && config.targetChat ? { name: config.targetChat.name, id: config.targetChat.id } : null,
    dryRun: Boolean(settings.dryRun),
    lastCheckAt: engine ? L.fmtMs(engine.lastSweepAt) : null,
    lastDeletionAt: engine ? L.fmtMs(engine.lastDeletionAt) : null,
    totalDeleted: state ? state.totals.deleted : 0,
    pausedUntil: state && state.pausedUntil > Date.now() ? L.fmtMs(state.pausedUntil) : null,
    pausedByYou: state && state.control && state.control.paused
      ? (state.control.resumeAt ? `until ${L.fmtMs(state.control.resumeAt)}` : 'until you send "resume"')
      : null,
    lastError: (engine && engine.lastError) || lastError,
    startedAt: L.fmtMs(startedAt),
  };
  try { L.writeJsonAtomic(P.status, st); } catch { /* status is best-effort */ }
}

/** Returns { config } or { error } – never silently "fixes" a user-edited config. */
function loadConfig() {
  const { value, error, missing } = L.readJson(P.config, null);
  if (missing) return { missing: true };
  if (error) return { error: `${error}. Fix the file or delete it and run "npm run setup".` };
  if (!value || !value.targetChat || typeof value.targetChat.id !== 'string' || !value.targetChat.id.includes('@')) {
    return { error: 'config.json has no valid targetChat. Run "npm run setup".' };
  }
  return { config: value };
}

// ------------------------------------------------------------------ WhatsApp client

/**
 * Picks the browser: CHROME_PATH if set, else Puppeteer's own Chrome if it was downloaded,
 * else an installed Chrome / Edge / Chromium. Returns null to let Puppeteer decide.
 */
function findBrowser() {
  const exists = (p) => { try { return Boolean(p) && fs.statSync(p).isFile(); } catch { return false; } };
  if (process.env.CHROME_PATH) {
    if (exists(process.env.CHROME_PATH)) return process.env.CHROME_PATH;
    log.warn(`CHROME_PATH points to "${process.env.CHROME_PATH}" but nothing is there; looking for another browser.`);
  }
  try {
    if (exists(require('puppeteer').executablePath())) return null;
  } catch { /* not downloaded or unsupported platform */ }
  const pf = process.env.PROGRAMFILES || 'C:\\Program Files';
  const pf86 = process.env['PROGRAMFILES(X86)'] || 'C:\\Program Files (x86)';
  const local = process.env.LOCALAPPDATA || '';
  const candidates = {
    win32: [
      `${pf}\\Google\\Chrome\\Application\\chrome.exe`,
      `${pf86}\\Google\\Chrome\\Application\\chrome.exe`,
      `${local}\\Google\\Chrome\\Application\\chrome.exe`,
      `${pf86}\\Microsoft\\Edge\\Application\\msedge.exe`,
      `${pf}\\Microsoft\\Edge\\Application\\msedge.exe`,
    ],
    darwin: [
      '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
      '/Applications/Chromium.app/Contents/MacOS/Chromium',
      '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    ],
  }[process.platform] || [
    '/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/lib/chromium/chromium',
    '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/microsoft-edge',
  ];
  const found = candidates.find(exists);
  if (found) log.info(`Using browser: ${found}`);
  return found || null;
}

function makeClient() {
  const { Client, LocalAuth } = require('whatsapp-web.js');
  const chromeArgs = [
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-extensions',
    // keep WhatsApp's timers running at full speed in a hidden browser
    '--disable-background-timer-throttling',
    '--disable-backgrounding-occluded-windows',
    '--disable-renderer-backgrounding',
  ];
  if (process.platform === 'linux' || process.platform === 'android') {
    chromeArgs.push('--disable-dev-shm-usage', '--disable-gpu');
    if (typeof process.getuid === 'function' && process.getuid() === 0) {
      chromeArgs.push('--no-sandbox', '--disable-setuid-sandbox'); // Chrome refuses to run as root otherwise
    }
  }
  const puppeteer = {
    headless: true,
    args: chromeArgs,
    // we close the browser ourselves so the WhatsApp session is saved cleanly
    handleSIGINT: false,
    handleSIGTERM: false,
    handleSIGHUP: false,
  };
  if (process.env.CHROME_EXTRA_ARGS) chromeArgs.push(...process.env.CHROME_EXTRA_ARGS.split(/\s+/).filter(Boolean));
  const browserPath = findBrowser();
  if (browserPath) puppeteer.executablePath = browserPath;

  const options = {
    authStrategy: new LocalAuth({ clientId: CLIENT_ID, dataPath: P.auth }),
    puppeteer,
    webVersionCache: { type: 'local', path: P.webCache },
    authTimeoutMs: 240000, // phones under proot load WhatsApp Web slowly
    qrMaxRetries: 0,
    takeoverOnConflict: true,
    takeoverTimeoutMs: 15000,
  };
  if (pairPhone) {
    options.pairWithPhoneNumber = { phoneNumber: pairPhone, showNotification: true, intervalMs: 180000 };
  }
  return new Client(options);
}

let pairPhone = null; // set in setup when linking by code instead of QR

/** Asks how to link when there's no saved login yet. Returns digits for code-linking, or null for QR. */
async function askLinkMethod() {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  const ask = (q) => new Promise((resolve) => rl.question(q, (a) => resolve((a || '').trim())));
  try {
    console.log('\nThis device is not linked to WhatsApp yet. How do you want to link it?');
    console.log('  1) Scan a QR code          (QR shown here; scan it with your phone)');
    console.log('  2) Type a code on the phone (use this when running ON your phone)');
    const def = ON_PHONE ? '2' : '1';
    const choice = (await ask(`Choose 1 or 2 [${def}]: `)) || def;
    if (choice !== '2') return null;
    for (;;) {
      const raw = await ask('Your WhatsApp number with country code (e.g. +919876543210): ');
      const digits = raw.replace(/\D/g, '');
      if (digits.length >= 8 && digits.length <= 15) return digits;
      console.log('That doesn\'t look like a full number with country code. Try again.');
    }
  } finally {
    rl.close();
  }
}

async function presenceOff() {
  if (!client || clientClosed) return;
  await L.withTimeout(client.sendPresenceUnavailable(), 20000, 'presence update');
}

let lastScanNote = '';

/** Logs how far back a scan got; repeats of the same outcome go to debug so the log stays quiet. */
function reportScan(r) {
  const n = r.messages.length;
  const back = r.oldest ? L.fmtUnix(r.oldest) : 'n/a';
  const win = `${settings.maxMessageAgeHours}h`;
  let level;
  let msg;
  switch (r.stop) {
    case 'window':
      level = 'info';
      msg = `Scanned ${n} message(s) back to ${back}: covers the whole ${win} window in which WhatsApp allows "delete for everyone".`;
      break;
    case 'start':
      level = 'info';
      msg = `Scanned all ${n} message(s) this computer has for the chat (back to ${back}). ` +
        'If the chat goes back further, WhatsApp may still be syncing older history from your phone; later checks will pick it up.';
      break;
    case 'cap':
      level = 'warn';
      msg = `Stopped after ${n} message(s) (back to ${back}) because of the scanDepth limit (${settings.scanDepth}). ` +
        `Older messages still inside the ${win} window were not checked; raise "scanDepth" in config.json to go further.`;
      break;
    default:
      level = 'warn';
      msg = `Could not load older messages (${r.error || 'unknown reason'}); only the ${n} most recent message(s), back to ${back}, were checked.`;
  }
  const key = `${r.stop}:${r.error || ''}`;
  if (key !== lastScanNote) { lastScanNote = key; log[level](msg); } else log.debug(msg);
}

function makeAdapter(chatId) {
  // All message access goes through wa.js (tolerant of WhatsApp's internal renames).
  return {
    fetchMessages: async () => {
      // Scroll back through everything that can still be deleted for everyone (and no further).
      const sinceSec = Math.floor(Date.now() / 1000) - settings.maxMessageAgeHours * 3600;
      const r = await wa.fetchMessages(chatId, { sinceSec, maxMsgs: settings.scanDepth });
      reportScan(r);
      return normalizeMessages(r.messages);
    },
    checkRevoke: (id) => wa.checkRevoke(id),
    revoke: (id) => wa.revoke(id), // checks permission and deletes in one atomic step
    getType: (id, m) => wa.verifyRevoked(chatId, id, m && m.timestamp),
    presenceOff,
  };
}

function chatIdsOf(msg) {
  const ids = [];
  const remote = msg.id && msg.id.remote;
  if (remote) ids.push(typeof remote === 'object' ? remote._serialized : remote);
  if (msg.from) ids.push(msg.from);
  return ids;
}

/** A 1:1 chat can be addressed by phone-number id or by WhatsApp's newer "LID" id. Track both. */
async function refreshTargetIds() {
  const t = config.targetChat;
  targetIds.clear();
  targetIds.add(t.id);
  (Array.isArray(t.aliases) ? t.aliases : []).forEach((a) => targetIds.add(a));
  if (t.isGroup) return;
  try {
    const res = await L.withTimeout(client.getContactLidAndPhone([t.id]), 30000, 'id lookup');
    for (const r of res || []) {
      if (r.lid) targetIds.add(r.lid);
      if (r.pn) targetIds.add(r.pn);
    }
  } catch (e) {
    log.debug('Alias lookup failed (not critical):', L.errText(e));
  }
}

// ------------------------------------------------------------------ client events

function wireClientEvents() {
  client.on('qr', async (qr) => {
    awaitingQr = true;
    initProgressAt = Date.now();
    setPhase('needs_qr_scan');
    if (INTERACTIVE) {
      console.log('\nOn your phone: WhatsApp → Settings → Linked devices → Link a device, then scan:\n');
      require('qrcode-terminal').generate(qr, { small: true });
    } else {
      log.warn(`Not logged in. Open ${P.qr} and scan it (WhatsApp → Linked devices → Link a device), ` +
        'or stop the service and run "npm run setup".');
    }
    try { await require('qrcode').toFile(P.qr, qr, { width: 420, margin: 2 }); } catch (e) { log.debug('QR image not written:', L.errText(e)); }
  });

  client.on('code', (code) => {
    awaitingQr = true;
    initProgressAt = Date.now();
    setPhase('needs_pairing_code');
    const pretty = String(code).replace(/^(.{4})(.{4})$/, '$1-$2');
    console.log(`\n   Your linking code:   ${pretty}\n`);
    console.log('On your phone: WhatsApp → Linked devices → Link a device → "Link with phone number instead" → type the code.');
    console.log('(WhatsApp may also show a notification asking for it. A new code appears every 3 minutes if unused.)');
  });

  client.on('authenticated', () => {
    awaitingQr = false;
    initProgressAt = Date.now();
    L.rmQuiet(P.qr);
    if (!authLogged) log.info('Authenticated with WhatsApp.');
    authLogged = true;
  });

  client.on('auth_failure', (m) => {
    lastError = `authentication failed: ${m}`;
    log.error(`Authentication failed (${m}). If this keeps happening, stop the service and run "npm run setup".`);
    shutdown(EXIT.RESTART, 'auth failure', { delayMs: backoffDelay() });
  });

  client.on('loading_screen', (pct) => {
    initProgressAt = Date.now();
    log.debug(`Loading WhatsApp… ${pct}%`);
  });

  client.on('change_state', (s) => {
    lastWaState = s;
    log.info(`WhatsApp connection state: ${s}`);
  });

  client.on('disconnected', (reason) => {
    lastWaState = 'DISCONNECTED';
    if (shuttingDown) return;
    if (reason === 'LOGOUT') {
      lastError = 'logged out';
      log.error('WhatsApp logged this linked device out. A new QR scan is needed (see data/qr.png or run "npm run setup").');
    } else {
      log.warn(`Disconnected from WhatsApp (${reason}).`);
    }
    shutdown(EXIT.RESTART, `disconnected: ${reason}`, { delayMs: L.randInt(5e3, 20e3) });
  });

  client.on('ready', () => safe(() => onReady('library')));
  client.on('message', (msg) => onIncoming(msg, 'message'));
  client.on('message_ciphertext', (msg) => onIncoming(msg, 'ciphertext'));
}

function recordBrowser() {
  const c = client;
  const browser = c && c.pupBrowser;
  if (!browser || c._wadWired) return Boolean(browser);
  c._wadWired = true;
  try {
    const proc = browser.process && browser.process();
    if (proc && proc.pid) {
      state.browserPid = proc.pid;
      saveState();
    }
  } catch { /* ignore */ }
  browser.on('disconnected', () => {
    if (shuttingDown || clientClosed) return;
    lastError = 'browser closed unexpectedly';
    log.error('The background browser closed unexpectedly; restarting.');
    shutdown(EXIT.RESTART, 'browser disconnected', { delayMs: L.randInt(3e3, 10e3) });
  });
  if (c.pupPage) {
    c.pupPage.on('pageerror', (e) => {
      lastPageError = L.errText(e).slice(0, 200);
      log.debug('WhatsApp page error:', lastPageError);
    });
    c.pupPage.on('error', (e) => {
      if (shuttingDown) return;
      lastError = 'page crashed';
      log.error('The WhatsApp page crashed:', L.errText(e));
      shutdown(EXIT.RESTART, 'page crashed', { delayMs: L.randInt(3e3, 10e3) });
    });
  }
  return true;
}

async function watchBrowserLaunch() {
  for (let i = 0; i < 600 && !shuttingDown; i++) {
    if (recordBrowser()) return;
    await sleep(200);
  }
}

async function onReady(source) {
  if (source === 'direct' && isReady) return;
  readyCount++;
  if (readyCount === 1) readyVia = source;
  isReady = true;
  awaitingQr = false;
  lastWaState = 'CONNECTED';
  L.rmQuiet(P.qr);
  recordBrowser();
  if (state.startupFailures) {
    state.startupFailures = 0;
    saveState();
  }

  if (readyCount > 1) {
    if (source === 'library' && readyVia === 'direct' && readyCount === 2) log.info('The library caught up; all good.');
    else log.info('WhatsApp Web reloaded itself; re-syncing.');
    if (serviceStarted) {
      await refreshTargetIds();
      await startListening();
      engine.deferSweep(L.randInt(10e3, 30e3), 'after reload');
      presenceOff().catch(() => {});
    }
    return;
  }

  const me = client.info && (client.info.pushname || (client.info.wid && client.info.wid.user));
  log.info(`Connected${me ? ` as ${me}` : ''}${source === 'direct' ? ' (direct mode)' : ''}.`);
  if (MODE === 'setup') return runSetup();
  return startService();
}

/** From the library's event (may break if WhatsApp renames fields – that's why we also listen ourselves). */
function onIncoming(msg, via) {
  try {
    if (!msg || msg.fromMe) return;
    handleIncoming(chatIdsOf(msg), msg.type, via);
  } catch (e) {
    log.error('Error handling incoming message:', L.errText(e));
  }
}

function handleIncoming(ids, type, via) {
  if (!serviceStarted || shuttingDown) return;
  if (!ids.some((id) => targetIds.has(id))) return;
  if (!isTrigger({ fromMe: false, type })) {
    log.debug(`Ignoring non-message event (${type}) in target chat.`);
    return;
  }
  const now = Date.now();
  if (now - (handleIncoming.lastLog || 0) > 3000) {
    if (isPausedNow()) log.info('They replied, but you have paused it – nothing will be deleted.');
    else log.info(`They replied (${type === 'ciphertext' ? 'message still decrypting' : type}); cleanup scheduled.`);
  }
  handleIncoming.lastLog = now;
  log.debug(`Reply seen via ${via}.`);
  engine.onReply();
}

async function startListening() {
  try {
    await wa.listen((ids, type) => handleIncoming(ids, type, 'direct listener'), onSelfNote);
  } catch (e) {
    log.warn(`Direct reply listener unavailable (${L.errText(e)}); relying on periodic checks and library events.`);
  }
}

// ------------------------------------------------------------------ phone remote control

function isPausedNow() {
  const c = state && state.control;
  if (!c || !c.paused) return false;
  if (c.resumeAt && Date.now() >= c.resumeAt) {
    doResume('timer');
    return false;
  }
  return true;
}

async function reactTo(msgId, emoji) {
  try { await wa.react(msgId, emoji); } catch (e) { log.debug('Reaction failed:', L.errText(e)); }
}

function doResume(how) {
  const c = state.control;
  const wasPaused = c.paused;
  c.paused = false;
  c.resumeAt = 0;
  if (how === 'all') c.activeSince = 0;
  else if (wasPaused) c.activeSince = Math.floor(Date.now() / 1000); // keep what was sent while paused
  if (how === 'timer' && c.pauseMsgId) reactTo(c.pauseMsgId, '▶️');
  c.pauseMsgId = null;
  saveState();
  writeStatus();
  if (wasPaused || how === 'all') {
    log.info(how === 'timer' ? 'Pause time is over – running again.'
      : how === 'all' ? 'Resumed from your phone (also cleaning up what piled up while paused).'
        : 'Resumed from your phone. Messages sent while paused are kept.');
  }
  if (engine && !shuttingDown) engine.deferSweep(L.randInt(5e3, 20e3), 'resumed');
}

async function applyCommand(cmd, msgId) {
  const c = state.control;
  if (cmd.cmd === 'pause') {
    c.paused = true;
    c.resumeAt = cmd.ms ? Date.now() + cmd.ms : 0;
    c.pauseMsgId = msgId;
    saveState();
    writeStatus();
    log.info(`Paused from your phone${c.resumeAt ? ` until ${L.fmtMs(c.resumeAt)}` : ' until you send "resume"'}.`);
    await reactTo(msgId, '⏸️');
  } else if (cmd.cmd === 'resume') {
    doResume(cmd.all ? 'all' : 'phone');
    await reactTo(msgId, '▶️');
  } else if (cmd.cmd === 'status') {
    const problem = (state.pausedUntil > Date.now()) || (engine && engine.lastError);
    log.info('Status requested from your phone.');
    await reactTo(msgId, isPausedNow() ? '⏸️' : problem ? '⚠️' : '✅');
  }
}

let commandsRunning = false;
let commandsAgain = false;

/** Reads your recent notes-to-self and applies any new pause/resume/status commands. */
async function checkCommands() {
  if (!serviceStarted || shuttingDown) return;
  if (commandsRunning) { commandsAgain = true; return; }
  commandsRunning = true;
  try {
    do {
      commandsAgain = false;
      const notes = await wa.ownNotes(20);
      const c = state.control;
      let changed = false;
      for (const n of notes) {
        if (!n.id || n.t < c.lastCommandAt || c.handled.includes(n.id)) continue;
        c.handled = [...c.handled, n.id].slice(-50);
        c.lastCommandAt = Math.max(c.lastCommandAt, n.t);
        changed = true;
        const cmd = parseCommand(n.body);
        if (cmd) await applyCommand(cmd, n.id);
      }
      if (changed) saveState();
    } while (commandsAgain && !shuttingDown);
  } catch (e) {
    log.debug('Checking phone commands failed:', L.errText(e));
  } finally {
    commandsRunning = false;
  }
}

function onSelfNote() {
  later(800, checkCommands);
}

// ------------------------------------------------------------------ service mode

async function startService() {
  const t = config.targetChat;
  let chat = null;
  for (let i = 1; i <= 10 && !shuttingDown; i++) {
    try {
      chat = await wa.chatInfo(t.id);
    } catch (e) {
      log.warn(`Looking up the chat failed: ${L.errText(e)}`);
    }
    if (chat) break;
    log.warn(`Chat "${t.name}" not found yet (try ${i}/10) – WhatsApp may still be syncing. Retrying in 60s.`);
    await sleep(60000);
  }
  if (shuttingDown) return;
  if (!chat) {
    lastError = 'configured chat not found';
    log.error(`Could not find the chat "${t.name}". Run "npm run setup" to choose it again.`);
    return shutdown(EXIT.NEEDS_USER, 'chat not found');
  }

  await refreshTargetIds();
  if (chat.id) targetIds.add(chat.id);
  engine = new Engine({
    adapter: makeAdapter(t.id),
    settings,
    state,
    persist: saveState,
    logger: log,
    activeSinceSec: () => Math.max(Number(t.activeSince) || 0, state.control.activeSince || 0),
    isPaused: isPausedNow,
    sleep,
    timers: { set: (fn, ms) => later(ms, fn), clear: (h) => { clearTimeout(h); timers.delete(h); } },
  });
  serviceStarted = true;
  if (!state.control.lastCommandAt) {
    state.control.lastCommandAt = Math.floor(Date.now() / 1000); // never replay old notes
    saveState();
  }
  setPhase(settings.dryRun ? 'running (dry-run)' : 'running');
  log.info(`Watching "${t.name}"${t.isGroup ? ' (group: ANY other member\'s message counts as a reply)' : ''}.`);
  log.info(settings.dryRun
    ? 'DRY-RUN mode: nothing will be deleted, only logged.'
    : 'When they reply, your earlier messages there will be deleted for everyone.');

  await startListening();
  log.info('Phone control: message yourself "pause", "pause 2h", "resume" or "status".');
  if (isPausedNow()) {
    log.info(`Currently PAUSED by you${state.control.resumeAt ? ` until ${L.fmtMs(state.control.resumeAt)}` : ''}.`);
  }
  later(L.randInt(3e3, 8e3), checkCommands);
  presenceOff().catch((e) => log.debug('Presence update failed:', L.errText(e)));
  schedulePresence();
  schedulePeriodicSweep();
  scheduleRecycle();
  engine.deferSweep(L.randInt(15e3, 45e3), 'startup catch-up');
}

function schedulePeriodicSweep() {
  later(randMs(settings.periodicSweepMin, 60e3), () => {
    if (shuttingDown) return;
    engine.requestSweep('periodic check');
    schedulePeriodicSweep();
  });
}

function schedulePresence() {
  later(randMs(settings.presenceRefreshMin, 60e3), async () => {
    if (shuttingDown) return;
    await presenceOff().catch(() => {});
    schedulePresence();
  });
}

function scheduleRecycle() {
  if (!SUPERVISED) {
    log.info(ON_PHONE
      ? 'Tip: use "wa start" to run it in the background.'
      : 'Tip: for 24/7 use run "npm run service" (pm2) – it adds auto-restart, daily refresh and start-on-boot.');
    return;
  }
  const tryRecycle = () => {
    if (shuttingDown) return;
    if (engine && engine.isBusy()) { later(120e3, tryRecycle); return; }
    shutdown(EXIT.OK, 'planned daily refresh');
  };
  later(randMs(settings.recycleAfterHours, 3600e3), tryRecycle);
}

// ------------------------------------------------------------------ direct-ready fallback

/*
 * The library announces "ready" only after a chain of steps that touch WhatsApp internals.
 * When WhatsApp Web changes, one of those steps can fail silently inside the page and
 * "ready" never comes. This script doesn't need anything from that chain, so if the page
 * is logged in and CONNECTED but "ready" is late, we continue on our own.
 */
function startDirectReadyProbe() {
  every(5000, async () => {
    if (isReady || shuttingDown || clientClosed || !client || !client.pupPage) return;
    let h;
    try { h = await wa.health(); } catch { connectedSince = 0; return; }
    if (h.state !== 'CONNECTED') { connectedSince = 0; return; }
    if (!connectedSince) { connectedSince = Date.now(); initProgressAt = Date.now(); }
    if (Date.now() - connectedSince < 45000) return; // give the library a fair chance first
    log.warn('The library never signalled "ready" (WhatsApp Web changed again' +
      `${lastPageError ? `; page error: ${lastPageError}` : ''}). Continuing without it – this script doesn't need it.`);
    initProgressAt = Date.now();
    await onReady('direct');
  });
}

// ------------------------------------------------------------------ watchdog

function startWatchdog() {
  every(60e3, async () => {
    if (shuttingDown) return;
    const now = Date.now();
    const gap = now - lastWatchdogTick;
    lastWatchdogTick = now;
    if (gap > 5 * 60e3) {
      log.info(`Resumed after a ~${Math.round(gap / 60e3)} min pause (computer asleep?); re-checking the chat.`);
      if (serviceStarted) engine.deferSweep(L.randInt(20e3, 60e3), 'after wake');
    }

    if (!isReady) {
      if (!awaitingQr && now - initProgressAt > 8 * 60e3) {
        lastError = 'startup did not finish';
        log.error('Startup made no progress for 8 minutes.');
        return shutdown(EXIT.RESTART, 'startup timeout', { delayMs: backoffDelay() });
      }
      return writeStatus();
    }

    let st;
    try {
      const h = await wa.health();
      st = h.state || 'UNKNOWN'; // page answered; state module may simply have been renamed
      pageFailures = 0;
    } catch (e) {
      pageFailures++;
      log.warn(`Health check failed (${pageFailures}/3): ${L.errText(e)}`);
      if (pageFailures >= 3) {
        lastError = 'browser unresponsive';
        return shutdown(EXIT.RESTART, 'browser unresponsive', { delayMs: L.randInt(5e3, 15e3) });
      }
      return writeStatus();
    }

    lastWaState = st;
    if (st === 'CONNECTED' || st === 'UNKNOWN') {
      if (notConnectedMinutes) log.info('WhatsApp connection is back.');
      notConnectedMinutes = 0;
    } else {
      notConnectedMinutes++;
      if (notConnectedMinutes === 1 || notConnectedMinutes % 5 === 0) {
        log.warn(`WhatsApp not connected (${st}) for ~${notConnectedMinutes} min; waiting for it to reconnect.`);
      }
      if (notConnectedMinutes >= 20) {
        lastError = `not connected for 20 min (${st})`;
        return shutdown(EXIT.RESTART, 'stuck disconnected', { delayMs: L.randInt(30e3, 90e3) });
      }
    }

    if (serviceStarted && (st === 'CONNECTED' || st === 'UNKNOWN')) {
      isPausedNow(); // handles timed auto-resume
      checkCommands(); // backup in case a command message event was missed
      try {
        const reattached = await wa.listen((ids, type) => handleIncoming(ids, type, 'direct listener'), onSelfNote);
        if (reattached) {
          log.info('Re-attached the reply listener (WhatsApp reloaded its page); re-checking the chat.');
          engine.deferSweep(L.randInt(10e3, 30e3), 'after page reload');
        }
      } catch (e) {
        log.debug('Listener check failed:', L.errText(e));
      }
    }

    if (engine && engine.isBusy() && engine.sweepStartedAt && now - engine.sweepStartedAt > 30 * 60e3) {
      lastError = 'a cleanup got stuck';
      return shutdown(EXIT.RESTART, 'cleanup stuck', { delayMs: L.randInt(5e3, 15e3) });
    }
    writeStatus();
  });
}

/** Exponential backoff for repeated startup failures (15s → 15min) – gentle on WhatsApp's servers. */
function backoffDelay() {
  state.startupFailures = (state.startupFailures || 0) + 1;
  saveState();
  const n = state.startupFailures;
  const ms = Math.min(15e3 * 2 ** (n - 1), 15 * 60e3) + L.randInt(0, 10e3);
  if (SUPERVISED) log.warn(`Consecutive startup problem #${n}; waiting ${Math.round(ms / 1000)}s before retrying.`);
  return ms;
}

// ------------------------------------------------------------------ shutdown

function killBrowserHard() {
  try {
    const proc = client && client.pupBrowser && client.pupBrowser.process && client.pupBrowser.process();
    if (proc && proc.pid && L.isPidAlive(proc.pid)) L.killTree(proc.pid);
  } catch { /* ignore */ }
}

async function teardownClient() {
  if (!client || clientClosed) return;
  clientClosed = true;
  try {
    await L.withTimeout(client.destroy(), 15000, 'closing browser');
  } catch (e) {
    log.warn(`Browser did not close cleanly (${L.errText(e)}); force-closing.`);
    killBrowserHard();
  }
}

function finalExit(code) {
  try {
    if (state) {
      state.browserPid = null;
      saveState();
    }
    phase = code === EXIT.OK ? 'stopped' : code === EXIT.NEEDS_USER ? 'stopped (needs you)' : 'restarting';
    writeStatus();
  } catch { /* ignore */ }
  L.releaseLock(P.lock);
  process.exit(code);
}

async function shutdown(code, reason, { delayMs = 0 } = {}) {
  if (shuttingDown) return;
  shuttingDown = true;
  log.info(`Stopping (${reason})…`);
  phase = 'stopping';
  writeStatus();
  abort.abort();
  for (const t of timers) { clearTimeout(t); clearInterval(t); }
  timers.clear();
  if (engine) engine.stop();

  const force = setTimeout(() => {
    log.warn('Shutdown is taking too long; forcing exit.');
    killBrowserHard();
    finalExit(code);
  }, 30000 + delayMs);

  const t0 = Date.now();
  while (engine && engine.isBusy() && Date.now() - t0 < 12000) await L.sleep(250);
  await teardownClient();

  if (delayMs > 0 && SUPERVISED) {
    phase = `restarting in ${Math.round(delayMs / 1000)}s`;
    writeStatus();
    await L.sleep(delayMs); // keeps pm2 from counting this as a crash loop
  }
  clearTimeout(force);
  if (!SUPERVISED && code === EXIT.RESTART) {
    log.warn('Exited because of the problem above. Under pm2 ("npm run service") this restarts automatically.');
  }
  finalExit(code);
}

function onStopSignal(sig) {
  if (shuttingDown) {
    log.warn('Second stop request – exiting immediately.');
    killBrowserHard();
    finalExit(EXIT.OK);
    return;
  }
  shutdown(EXIT.OK, sig);
}

// ------------------------------------------------------------------ setup mode (interactive)

async function loadChatList() {
  let lastErr = null;
  for (let i = 1; i <= 3 && !shuttingDown; i++) {
    try {
      const chats = await wa.listChats();
      return chats
        .map((c) => ({ ...c, name: c.name || (c.phone ? `+${c.phone}` : c.id) }))
        .sort((a, b) => b.ts - a.ts);
    } catch (e) {
      lastErr = e;
      log.warn(`Loading chats failed (try ${i}/3): ${L.errText(e)}`);
      if (i < 3) await sleep(5000);
    }
  }
  console.log(`\nCouldn't load the chat list (${L.errText(lastErr)}).`);
  console.log('You can still pick a person directly by typing their number, e.g. +919876543210');
  return [];
}

function describeChat(c) {
  const who = c.isGroup ? 'group' : c.phone ? `+${c.phone}` : 'contact';
  const when = c.ts ? L.fmtUnix(c.ts).slice(0, 16) : '';
  return `${c.name}  ·  ${who}${c.archived ? '  ·  archived' : ''}${when ? `  ·  ${when}` : ''}`;
}

async function runSetup() {
  setPhase('setup');
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  rl.on('SIGINT', () => onStopSignal('SIGINT'));
  const ask = (q) => new Promise((resolve) => rl.question(q, (a) => resolve((a || '').trim())));

  try {
    console.log('\nLoading your chats… (right after linking, WhatsApp may take a minute to sync – use [r] to reload)');
    let all = await loadChatList();
    let list = all;
    let page = 0;
    const PAGE = 15;
    let chosen = null;

    while (!chosen && !shuttingDown) {
      const pages = Math.max(1, Math.ceil(list.length / PAGE));
      page = Math.min(Math.max(page, 0), pages - 1);
      console.log(`\n── Chats (page ${page + 1}/${pages}, ${list.length} shown of ${all.length}) ──`);
      if (!list.length) console.log('  (no chats match)');
      list.slice(page * PAGE, page * PAGE + PAGE).forEach((c, i) => {
        console.log(`${String(page * PAGE + i + 1).padStart(4)}. ${describeChat(c)}`);
      });
      const a = await ask('\nList number to pick · text to search · +phone number · [n]ext · [p]rev · [a]ll · [r]eload · [q]uit: ');
      if (shuttingDown) return;
      const lower = a.toLowerCase();
      if (lower === 'q') return shutdown(EXIT.OK, 'setup cancelled');
      if (lower === 'n') { page++; continue; }
      if (lower === 'p') { page--; continue; }
      if (lower === 'a' || a === '') { list = all; page = 0; continue; }
      if (lower === 'r') { all = await loadChatList(); list = all; page = 0; continue; }
      const compact = a.replace(/[\s()-]/g, '');
      if (/^\+\d{6,15}$/.test(compact)) {
        const digits = compact.slice(1);
        let c = null;
        try { c = await wa.findChatByPhone(digits); } catch (e) { console.log(`Lookup failed: ${L.errText(e)}`); continue; }
        if (!c) {
          console.log(`No existing chat with +${digits}. Make sure you've chatted with them before (check the country code), then try again.`);
          continue;
        }
        const ok = (await ask(`\nUse "${c.name}" (+${digits})? [y/N]: `)).toLowerCase();
        if (ok === 'y' || ok === 'yes') chosen = { ...c, phone: digits };
        continue;
      }
      if (/^\d+$/.test(a)) {
        const c = list[parseInt(a, 10) - 1];
        if (!c) { console.log('No chat with that number.'); continue; }
        const ok = (await ask(`\nUse "${c.name}"${c.isGroup ? ' (GROUP)' : ''}? [y/N]: `)).toLowerCase();
        if (ok === 'y' || ok === 'yes') chosen = c;
        continue;
      }
      const digits = a.replace(/\D/g, '');
      list = all.filter((c) => c.name.toLowerCase().includes(lower) ||
        (digits.length >= 4 && ((c.phone && c.phone.includes(digits)) || c.id.includes(digits))));
      page = 0;
    }
    if (!chosen) return;

    if (chosen.isGroup) {
      console.log('\nNote: this is a group. A message from ANY other member will trigger deletion of your earlier messages.');
    }
    console.log('\nShould your messages that are ALREADY in this chat be included?');
    console.log('  y = yes, also clean up existing ones (only those WhatsApp still allows, roughly the last 2.5 days)');
    console.log('  n = no, only messages you send from now on (safer default)');
    const inc = (await ask('Include existing messages? [y/N]: ')).toLowerCase();
    const includeOld = inc === 'y' || inc === 'yes';

    const aliases = [];
    if (chosen.phone && `${chosen.phone}@c.us` !== chosen.id) aliases.push(`${chosen.phone}@c.us`);
    if (!chosen.isGroup) {
      try {
        const res = await L.withTimeout(client.getContactLidAndPhone([chosen.id]), 30000, 'id lookup');
        for (const r of res || []) [r.lid, r.pn].forEach((x) => { if (x && x !== chosen.id) aliases.push(x); });
      } catch { /* optional */ }
    }

    const prev = loadConfig().config;
    const nowSec = Math.floor(Date.now() / 1000);
    const newConfig = {
      _readme: 'Edit "settings" to tune behaviour (see README.md). Re-run "npm run setup" to change the chat.',
      targetChat: {
        id: chosen.id,
        name: chosen.name,
        isGroup: chosen.isGroup,
        aliases,
        activeSince: includeOld ? 0 : nowSec,
        configuredAt: new Date().toISOString(),
      },
      settings: { ...DEFAULT_SETTINGS, ...((prev && prev.settings) || {}) },
    };
    L.writeJsonAtomic(P.config, newConfig);
    config = newConfig;
    console.log(`\n✔ Saved. Target chat: "${chosen.name}"`);

    // Preview so you can see exactly what the rule would do right now.
    try {
      settings = validateSettings(newConfig.settings, (w) => log.warn(w));
      const msgs = await makeAdapter(chosen.id).fetchMessages();
      const plan = planSweep(msgs, {
        nowSec,
        maxAgeSec: settings.maxMessageAgeHours * 3600,
        activeSinceSec: newConfig.targetChat.activeSince,
      });
      console.log('\nPreview:');
      if (!plan.trigger) {
        console.log('  They have not written in this chat yet – nothing happens until they do.');
      } else if (!plan.toDelete.length) {
        console.log('  Nothing would be deleted right now. Your next messages will be deleted after their next reply.');
      } else {
        console.log(`  ${plan.toDelete.length} of your message(s) would be deleted when the service starts:`);
        plan.toDelete.slice(-10).forEach((m) => console.log(`   • ${m.type} from ${L.fmtUnix(m.timestamp)}`));
      }
      if (plan.tooOld.length) console.log(`  ${plan.tooOld.length} older message(s) are past WhatsApp's window and will be left alone.`);
    } catch (e) {
      console.log(`  (Preview unavailable: ${L.errText(e)} – that's fine.)`);
    }

    console.log('\nNext steps:');
    console.log('  1) Optional trial run that deletes nothing:  npm run dry-run   (Ctrl+C to stop)');
    console.log('  2) Run it 24/7:                              npm run service');
    console.log('  3) Check on it any time:                     npm run status');
  } catch (e) {
    if (shuttingDown) return;
    console.log(`\nSetup hit an error: ${L.errText(e)}`);
    console.log('Nothing was changed. Run "npm run setup" again; if it repeats, send a screenshot.');
    rl.close();
    return shutdown(EXIT.RESTART, 'setup failed');
  } finally {
    rl.close();
  }
  return shutdown(EXIT.OK, 'setup complete');
}

// ------------------------------------------------------------------ status mode

function printStatus() {
  const lockPid = parseInt(L.safeRead(P.lock), 10);
  const running = Boolean(lockPid) && L.isPidAlive(lockPid);
  const { value: st } = L.readJson(P.status, null);
  console.log(running ? `● Running (pid ${lockPid})` : '○ Not running');
  if (!st) { console.log('No status recorded yet.'); return; }
  const ageMin = Math.round((Date.now() - Date.parse(st.updatedAt)) / 60e3);
  const rows = [
    ['Phase', st.phase],
    ['WhatsApp', st.whatsappState],
    ['Chat', st.targetChat ? st.targetChat.name : '(not configured)'],
    ['Mode', st.dryRun ? 'DRY-RUN (nothing is deleted)' : 'live'],
    ['Last check', st.lastCheckAt],
    ['Last deletion', st.lastDeletionAt],
    ['Total deleted', st.totalDeleted],
    ['Paused by you', st.pausedByYou],
    ['Safety pause', st.pausedUntil],
    ['Last problem', st.lastError],
    ['Status written', `${L.fmtMs(Date.parse(st.updatedAt))} (${ageMin} min ago)`],
  ];
  rows.filter(([, v]) => v !== null && v !== undefined && v !== '')
    .forEach(([k, v]) => console.log(`  ${k.padEnd(15)} ${v}`));
  if (running && ageMin > 3) console.log('\n⚠ Status is stale – the process may be hung. Try: pm2 restart wa-autodelete');
  if (st.phase === 'needs_qr_scan') console.log(`\n⚠ Needs a QR scan: open ${P.qr} or run "npm run setup".`);
}

// ------------------------------------------------------------------ main

async function main() {
  if (MODE === 'status') { printStatus(); return; }

  fs.mkdirSync(DATA, { recursive: true });

  if (MODE === 'setup' && !INTERACTIVE) {
    console.error('Setup needs an interactive terminal. Run "npm run setup" directly in a terminal window.');
    process.exit(EXIT.NEEDS_USER);
  }

  const lock = L.acquireLock(P.lock);
  if (!lock.ok) {
    console.error(`Another copy is already running${lock.pid ? ` (pid ${lock.pid})` : ''}. Only one copy may run at a time.`);
    console.error('  • If it is in another terminal window, press Ctrl+C there (or close that terminal).');
    console.error('  • If it runs under pm2: pm2 stop wa-autodelete');
    if (lock.pid) {
      console.error(`  • If it is stuck: ${process.platform === 'win32' ? `taskkill /PID ${lock.pid} /T /F` : `kill ${lock.pid}`}`);
    }
    process.exit(EXIT.NEEDS_USER);
  }

  for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
    try { process.on(sig, () => onStopSignal(sig)); } catch { /* not supported on this OS */ }
  }
  process.on('message', (m) => { if (m === 'shutdown') onStopSignal('pm2 shutdown'); }); // pm2 on Windows
  process.on('uncaughtException', (e) => {
    lastError = L.errText(e);
    log.error('Uncaught exception:', (e && e.stack) || e);
    if (!shuttingDown) shutdown(EXIT.RESTART, 'uncaught exception', { delayMs: L.randInt(5e3, 15e3) });
  });
  process.on('unhandledRejection', (e) => {
    if (shuttingDown) return;
    const now = Date.now();
    rejectionTimes = rejectionTimes.filter((t) => now - t < 10 * 60e3);
    rejectionTimes.push(now);
    log.warn('Internal async error (continuing):', L.errText(e));
    if (rejectionTimes.length >= 20) shutdown(EXIT.RESTART, 'too many internal errors', { delayMs: L.randInt(10e3, 30e3) });
  });

  state = loadState();

  if (MODE === 'service') {
    const res = loadConfig();
    if (res.error || res.missing) {
      if (res.missing && INTERACTIVE) {
        log.info('No chat configured yet – run "npm run setup" first.');
      } else {
        log.error(res.error || 'No config.json found. Run "npm run setup" in a terminal first.');
      }
      L.releaseLock(P.lock);
      process.exit(EXIT.NEEDS_USER);
    }
    config = res.config;
    settings = validateSettings(config.settings, (w) => log.warn(w));
    if (FORCE_DRY_RUN) settings.dryRun = true;
  }

  // Clean up after a crash of a previous run.
  if (state.browserPid) {
    L.killStaleBrowser(state.browserPid, log);
    state.browserPid = null;
    saveState();
  }
  L.removeChromeSingletons(PROFILE_DIR);

  log.info(`Starting (${MODE}${settings.dryRun ? ', dry-run' : ''}${SUPERVISED ? ', supervised' : ''})…`);
  setPhase('starting');
  startWatchdog();
  startDirectReadyProbe();

  if (MODE === 'setup' && !fs.existsSync(PROFILE_DIR)) {
    pairPhone = await askLinkMethod();
  }

  try {
    client = makeClient();
  } catch (e) {
    log.error('Could not load whatsapp-web.js – did you run "npm install"?', L.errText(e));
    L.releaseLock(P.lock);
    process.exit(EXIT.NEEDS_USER);
  }
  wireClientEvents();
  const init = client.initialize();
  watchBrowserLaunch();
  try {
    await init;
  } catch (e) {
    if (shuttingDown) return;
    lastError = `could not open WhatsApp Web: ${L.errText(e)}`;
    log.error(lastError);
    if (/Could not find (Chrome|Chromium|browser)|Failed to launch the browser process|ENOENT/i.test(L.errText(e))) {
      log.error(ON_PHONE
        ? 'The browser could not start. Re-run the installer (bash ~/wa-autodelete/termux/install.sh).'
        : 'No usable browser found. Install Google Chrome (or use Edge) or set CHROME_PATH – see README.');
      return shutdown(EXIT.NEEDS_USER, 'no browser');
    }
    shutdown(EXIT.RESTART, 'startup failed', { delayMs: backoffDelay() });
  }
}

main().catch((e) => {
  log.error('Fatal error:', (e && e.stack) || e);
  if (!shuttingDown) shutdown(EXIT.RESTART, 'fatal error', { delayMs: 10e3 });
});

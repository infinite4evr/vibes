'use strict';

/**
 * Small, dependency-free helpers used by the service.
 * Everything here is defensive: nothing in this file should ever throw
 * unexpectedly except writeJsonAtomic (callers catch it).
 */

const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

// ---------------------------------------------------------------- time/format

const pad = (n, w = 2) => String(n).padStart(w, '0');

function fmtDate(d) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}
const nowStamp = () => fmtDate(new Date());
const fmtUnix = (sec) => (sec ? fmtDate(new Date(sec * 1000)) : 'unknown time');
const fmtMs = (ms) => (ms ? fmtDate(new Date(ms)) : null);

function errText(e) {
  if (e === null || e === undefined) return String(e);
  if (typeof e === 'string') return e;
  if (e.message) return e.message;
  try { return JSON.stringify(e); } catch { return String(e); }
}

const shortId = (id) => (id ? `…${String(id).slice(-6)}` : '…?');

// ---------------------------------------------------------------- logging

const LEVELS = { debug: 10, info: 20, warn: 30, error: 40 };
const threshold = LEVELS[String(process.env.LOG_LEVEL || 'info').toLowerCase()] || LEVELS.info;

function emit(level, args) {
  if (LEVELS[level] < threshold) return;
  const prefix = `${nowStamp()} [${level.toUpperCase()}]`;
  const out = level === 'error' || level === 'warn' ? console.error : console.log;
  try { out(prefix, ...args); } catch { /* stdout closed – nothing we can do */ }
}

const logger = {
  debug: (...a) => emit('debug', a),
  info: (...a) => emit('info', a),
  warn: (...a) => emit('warn', a),
  error: (...a) => emit('error', a),
};

// ---------------------------------------------------------------- async helpers

/** Sleep that resolves early (with false) when the AbortSignal fires. Never rejects. */
function sleep(ms, signal) {
  return new Promise((resolve) => {
    if (signal && signal.aborted) return resolve(false);
    const onAbort = () => { clearTimeout(t); resolve(false); };
    const t = setTimeout(() => {
      if (signal) signal.removeEventListener('abort', onAbort);
      resolve(true);
    }, Math.max(0, ms));
    if (signal) signal.addEventListener('abort', onAbort, { once: true });
  });
}

/** Rejects with code TIMEOUT if the promise does not settle in time. */
function withTimeout(promise, ms, label = 'operation') {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => {
      const e = new Error(`${label} timed out after ${Math.round(ms / 1000)}s`);
      e.code = 'TIMEOUT';
      reject(e);
    }, ms);
  });
  return Promise.race([Promise.resolve(promise), timeout]).finally(() => clearTimeout(timer));
}

function randInt(min, max) {
  const lo = Math.min(min, max);
  const hi = Math.max(min, max);
  return Math.round(lo + Math.random() * (hi - lo));
}

function sleepSync(ms) {
  try { Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms); } catch { /* ignore */ }
}

// ---------------------------------------------------------------- files

function safeRead(file) {
  try { return fs.readFileSync(file, 'utf8'); } catch { return ''; }
}

function rmQuiet(file) {
  try { fs.rmSync(file, { force: true }); } catch { /* ignore */ }
}

/**
 * Reads JSON. Missing file -> fallback.
 * Corrupt file -> fallback, and (if quarantine) the bad file is moved aside so it can be inspected.
 * Returns { value, error } so callers can decide how to react.
 */
function readJson(file, fallback, { quarantine = false } = {}) {
  let raw;
  try {
    raw = fs.readFileSync(file, 'utf8');
  } catch (e) {
    if (e.code === 'ENOENT') return { value: fallback, error: null, missing: true };
    return { value: fallback, error: `could not read ${path.basename(file)}: ${errText(e)}` };
  }
  try {
    return { value: JSON.parse(raw.replace(/^\uFEFF/, '')), error: null };
  } catch (e) {
    let note = '';
    if (quarantine) {
      const bak = `${file}.corrupt-${Date.now()}`;
      try { fs.renameSync(file, bak); note = ` (moved to ${path.basename(bak)})`; } catch { /* ignore */ }
    }
    return { value: fallback, error: `${path.basename(file)} is not valid JSON: ${errText(e)}${note}` };
  }
}

/** Crash-safe write: temp file + fsync + rename. Retries briefly on Windows file locks. */
function writeJsonAtomic(file, obj) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.tmp`;
  const data = `${JSON.stringify(obj, null, 2)}\n`;
  const fd = fs.openSync(tmp, 'w');
  try {
    fs.writeSync(fd, data);
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
  for (let i = 0; ; i++) {
    try {
      fs.renameSync(tmp, file);
      return;
    } catch (e) {
      if (i >= 5 || !['EPERM', 'EBUSY', 'EACCES'].includes(e.code)) {
        rmQuiet(tmp);
        throw e;
      }
      sleepSync(60 * (i + 1));
    }
  }
}

// ---------------------------------------------------------------- processes

function isPidAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    return e.code === 'EPERM';
  }
}

/** Best-effort process name lookup (null if unknown). */
function getProcessName(pid) {
  if (process.platform === 'linux' || process.platform === 'android') {
    try { return fs.readFileSync(`/proc/${pid}/comm`, 'utf8').trim() || null; } catch { /* fall through */ }
  }
  try {
    if (process.platform === 'win32') {
      const out = execFileSync('tasklist', ['/FI', `PID eq ${pid}`, '/FO', 'CSV', '/NH'],
        { encoding: 'utf8', timeout: 8000, windowsHide: true });
      const m = out.match(/^"([^"]+)"/m);
      return m ? m[1] : null;
    }
    const out = execFileSync('ps', ['-p', String(pid), '-o', 'comm='], { encoding: 'utf8', timeout: 8000 });
    return out.trim() || null;
  } catch {
    return null;
  }
}

function killTree(pid) {
  try {
    if (process.platform === 'win32') {
      execFileSync('taskkill', ['/PID', String(pid), '/T', '/F'],
        { stdio: 'ignore', timeout: 10000, windowsHide: true });
    } else {
      process.kill(pid, 'SIGKILL');
    }
  } catch { /* already gone */ }
}

/** Kills a browser left over from a crashed run – only if the PID really is a browser. */
function killStaleBrowser(pid, log) {
  if (!isPidAlive(pid)) return false;
  const name = getProcessName(pid);
  if (!name || !/chrom|msedge|brave/i.test(name)) {
    log.debug(`Recorded browser pid ${pid} is now "${name}" – not touching it.`);
    return false;
  }
  log.warn(`Closing a browser left over from a previous run (pid ${pid}).`);
  killTree(pid);
  return true;
}

/** Chrome refuses to start if these lock files survive a crash. */
function removeChromeSingletons(profileDir) {
  for (const n of ['SingletonLock', 'SingletonSocket', 'SingletonCookie']) {
    rmQuiet(path.join(profileDir, n));
  }
}

// ---------------------------------------------------------------- single-instance lock

function acquireLock(file) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      fs.writeFileSync(file, String(process.pid), { flag: 'wx' });
      return { ok: true };
    } catch (e) {
      if (e.code !== 'EEXIST') throw e;
      const pid = parseInt(safeRead(file), 10);
      const alive = pid && pid !== process.pid && isPidAlive(pid);
      if (alive) {
        const name = getProcessName(pid);
        // PID reuse protection: a live PID that is not node is a stale lock.
        if (!name || /node/i.test(name)) return { ok: false, pid };
      }
      rmQuiet(file);
    }
  }
  return { ok: false, pid: null };
}

function releaseLock(file) {
  try {
    if (parseInt(fs.readFileSync(file, 'utf8'), 10) === process.pid) fs.unlinkSync(file);
  } catch { /* ignore */ }
}

// ---------------------------------------------------------------- rate budget

const HOUR = 3600 * 1000;
const DAY = 24 * HOUR;

/**
 * Sliding-window limiter (per hour + per day). History is persisted by the caller,
 * so restarts or crash loops cannot bypass the limits.
 */
class RateBudget {
  constructor({ perHour, perDay }, history = []) {
    this.perHour = perHour;
    this.perDay = perDay;
    this.events = (Array.isArray(history) ? history : [])
      .filter((t) => Number.isFinite(t))
      .sort((a, b) => a - b);
  }

  prune(now) {
    while (this.events.length && now - this.events[0] >= DAY) this.events.shift();
  }

  /** 0 if an action is allowed now, otherwise ms until one is. */
  msUntilAvailable(now = Date.now()) {
    this.prune(now);
    let wait = 0;
    const hourEvents = this.events.filter((t) => now - t < HOUR);
    if (hourEvents.length >= this.perHour) {
      wait = Math.max(wait, hourEvents[hourEvents.length - this.perHour] + HOUR - now);
    }
    if (this.events.length >= this.perDay) {
      wait = Math.max(wait, this.events[this.events.length - this.perDay] + DAY - now);
    }
    return Math.max(0, wait);
  }

  record(now = Date.now()) {
    this.events.push(now);
  }

  toJSON() {
    return this.events.slice();
  }
}

/** On the phone, the commands are "wa …" instead of "npm run …" / pm2. */
function phoneText(s) {
  return String(s)
    .replace(/pm2 stop wa-autodelete/g, 'wa stop')
    .replace(/pm2 restart wa-autodelete/g, 'wa restart')
    .replace(/npm run service/g, 'wa start')
    .replace(/npm run update-lib/g, 'wa update')
    .replace(/npm run (setup|dry-run|status|stop|restart|logs)/g, 'wa $1');
}

module.exports = {
  phoneText,
  logger, errText, shortId, fmtUnix, fmtMs, nowStamp,
  sleep, withTimeout, randInt,
  safeRead, rmQuiet, readJson, writeJsonAtomic,
  isPidAlive, getProcessName, killTree, killStaleBrowser, removeChromeSingletons,
  acquireLock, releaseLock,
  RateBudget, HOUR, DAY,
};

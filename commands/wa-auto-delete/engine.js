'use strict';

/**
 * The deletion engine. It knows nothing about Puppeteer or WhatsApp internals;
 * it talks to an "adapter" so it can be tested against a simulated chat.
 *
 * Rule implemented:
 *   Find the most recent message in the chat that was sent by someone else
 *   (a real message, not a system notice). Every message YOU sent before it
 *   that is not already deleted gets "deleted for everyone".
 *   Messages you send after their reply are left alone until they reply again.
 */

const { RateBudget, randInt, errText, shortId, fmtUnix, fmtMs } = require('./lib');

// Message types that are not real chat messages.
const SYSTEM_TYPES = new Set([
  'e2e_notification', 'notification', 'notification_template', 'gp2',
  'group_notification', 'call_log', 'protocol', 'broadcast_notification', 'debug', 'reaction',
]);

const isTrigger = (m) => !m.fromMe && !SYSTEM_TYPES.has(m.type);
const isOwnDeletable = (m) =>
  m.fromMe && m.type !== 'revoked' && m.type !== 'ciphertext' && !SYSTEM_TYPES.has(m.type);

const DEFAULT_SETTINGS = Object.freeze({
  dryRun: false,
  settleDelaySec: [4, 12], // random wait after their reply before acting (lets bursts arrive, looks human)
  settleMaxSec: 45, // never wait longer than this after the first message of a burst
  deleteDelaySec: [2.5, 7], // random gap between individual deletions
  maxDeletesPerHour: 60, // hard safety caps (persisted across restarts)
  maxDeletesPerDay: 400,
  maxMessageAgeHours: 58, // WhatsApp's own window is ~60h; stay safely inside it
  scanDepth: 3000, // upper limit when scrolling back; normally stops sooner, once maxMessageAgeHours is covered
  periodicSweepMin: [8, 16], // self-healing re-check interval (catches anything an event missed)
  presenceRefreshMin: [20, 40], // re-assert "offline" so you don't look online 24/7
  recycleAfterHours: [20, 28], // planned browser refresh (only under pm2)
  maxAttemptsPerMessage: 3,
  circuitBreakerFailures: 4, // this many failures in a row -> pause everything
  circuitBreakerPauseMin: 30,
  incompatiblePauseMin: 60,
});

const BOUNDS = {
  settleDelaySec: [0, 300], settleMaxSec: [0, 600], deleteDelaySec: [1, 120],
  maxDeletesPerHour: [1, 500], maxDeletesPerDay: [1, 5000], maxMessageAgeHours: [1, 720],
  scanDepth: [20, 20000], periodicSweepMin: [1, 240], presenceRefreshMin: [5, 240],
  recycleAfterHours: [1, 168], maxAttemptsPerMessage: [1, 10], circuitBreakerFailures: [1, 50],
  circuitBreakerPauseMin: [1, 1440], incompatiblePauseMin: [5, 1440],
};

/** Merges user settings over defaults; invalid values are reported and replaced by defaults. */
function validateSettings(user, warn = () => {}) {
  const out = { ...DEFAULT_SETTINGS };
  if (!user || typeof user !== 'object') return out;
  for (const key of Object.keys(user)) {
    if (!key.startsWith('_') && !(key in DEFAULT_SETTINGS)) warn(`Unknown setting "${key}" ignored.`);
  }
  for (const [key, def] of Object.entries(DEFAULT_SETTINGS)) {
    if (!(key in user)) continue;
    const v = user[key];
    const bad = () => warn(`Setting "${key}" has an invalid value (${JSON.stringify(v)}); using default ${JSON.stringify(def)}.`);
    if (typeof def === 'boolean') {
      if (typeof v === 'boolean') out[key] = v; else bad();
      continue;
    }
    const [lo, hi] = BOUNDS[key];
    if (Array.isArray(def)) {
      const ok = Array.isArray(v) && v.length === 2 && v.every(Number.isFinite) && v[0] <= v[1] && v[0] >= lo && v[1] <= hi;
      if (ok) out[key] = [v[0], v[1]]; else bad();
    } else if (Number.isFinite(v) && v >= lo && v <= hi) {
      out[key] = v;
    } else {
      bad();
    }
  }
  return out;
}

/** Converts library Message objects into plain records, oldest first. */
function normalizeMessages(raw) {
  const out = [];
  (raw || []).forEach((m, i) => {
    if (!m || !m.id) return;
    const id = typeof m.id === 'string' ? m.id : m.id._serialized;
    if (!id) return;
    out.push({
      id,
      fromMe: Boolean(m.fromMe !== undefined ? m.fromMe : m.id.fromMe),
      type: String(m.type || 'unknown'),
      timestamp: Number(m.timestamp) || 0,
      ack: typeof m.ack === 'number' ? m.ack : undefined,
      order: i,
    });
  });
  out.sort((a, b) => a.timestamp - b.timestamp || a.order - b.order);
  return out;
}

/** Pure planning function – decides what should be deleted right now. */
function planSweep(messages, { nowSec, maxAgeSec, activeSinceSec = 0, skipIds = new Set() }) {
  let lastTrigger = -1;
  for (let i = messages.length - 1; i >= 0; i--) {
    if (isTrigger(messages[i])) { lastTrigger = i; break; }
  }
  const plan = { trigger: null, toDelete: [], tooOld: [], pending: [] };
  if (lastTrigger === -1) return plan;
  plan.trigger = messages[lastTrigger];
  for (let i = 0; i < lastTrigger; i++) {
    const m = messages[i];
    if (!isOwnDeletable(m) || skipIds.has(m.id)) continue;
    if (activeSinceSec && m.timestamp < activeSinceSec) continue;
    if (nowSec - m.timestamp > maxAgeSec) { plan.tooOld.push(m); continue; }
    if (typeof m.ack === 'number' && m.ack < 1) { plan.pending.push(m); continue; }
    plan.toDelete.push(m);
  }
  return plan;
}

const SKIP_TTL = 30 * 24 * 3600 * 1000;
const ATTEMPT_TTL = 7 * 24 * 3600 * 1000;
const MAX_SKIP_ENTRIES = 5000;

class Engine {
  /**
   * deps: { adapter, settings, state, persist, logger, activeSinceSec,
   *         now?, sleep?, timers? }
   * adapter: { fetchMessages(), checkRevoke(id), revoke(id), getType(id), presenceOff() }
   */
  constructor(deps) {
    this.adapter = deps.adapter;
    this.settings = deps.settings;
    this.state = deps.state;
    this.persist = deps.persist;
    this.log = deps.logger;
    this.activeSinceSec = deps.activeSinceSec || 0; // number, or a function returning one
    this.isPaused = deps.isPaused || (() => false);
    this.now = deps.now || Date.now;
    this.sleep = deps.sleep || ((ms) => new Promise((r) => setTimeout(r, ms)));
    this.timers = deps.timers || { set: setTimeout, clear: clearTimeout };

    this.state.skip = this.state.skip || {};
    this.state.attempts = this.state.attempts || {};
    this.state.totals = this.state.totals || { deleted: 0 };
    this.budget = new RateBudget(
      { perHour: this.settings.maxDeletesPerHour, perDay: this.settings.maxDeletesPerDay },
      this.state.rateEvents,
    );

    this.running = false;
    this.again = false;
    this.stopped = false;
    this.settleTimer = null;
    this.settleFirstAt = 0;
    this.deferredTimer = null;
    this.deferredAt = 0;
    this.sweepStartedAt = 0;
    this.lastSweepAt = 0;
    this.lastDeletionAt = 0;
    this.lastError = null;
    this.dryRunSeen = new Set();
  }

  isBusy() { return this.running; }

  stop() {
    this.stopped = true;
    if (this.settleTimer) this.timers.clear(this.settleTimer);
    if (this.deferredTimer) this.timers.clear(this.deferredTimer);
    this.settleTimer = null;
    this.deferredTimer = null;
  }

  /** Called for every incoming message in the target chat. Debounces bursts. */
  onReply() {
    if (this.stopped) return;
    const s = this.settings;
    const now = this.now();
    if (!this.settleTimer) this.settleFirstAt = now;
    const delay = randInt(s.settleDelaySec[0] * 1000, s.settleDelaySec[1] * 1000);
    const fireAt = Math.min(now + delay, this.settleFirstAt + s.settleMaxSec * 1000);
    if (this.settleTimer) this.timers.clear(this.settleTimer);
    this.settleTimer = this.timers.set(() => {
      this.settleTimer = null;
      this.requestSweep('reply');
    }, Math.max(0, fireAt - now));
  }

  /** Schedules a sweep later; keeps whichever scheduled sweep is earliest. */
  deferSweep(ms, reason) {
    if (this.stopped) return;
    const at = this.now() + Math.max(0, ms);
    if (this.deferredTimer && this.deferredAt <= at) return;
    if (this.deferredTimer) this.timers.clear(this.deferredTimer);
    this.deferredAt = at;
    this.deferredTimer = this.timers.set(() => {
      this.deferredTimer = null;
      this.deferredAt = 0;
      this.requestSweep(reason);
    }, Math.max(0, ms));
  }

  /** Single-flight: concurrent requests collapse into one follow-up run. Never rejects. */
  async requestSweep(reason) {
    if (this.stopped) return;
    if (this.running) { this.again = true; return; }
    this.running = true;
    try {
      let why = reason;
      do {
        this.again = false;
        this.sweepStartedAt = this.now();
        try {
          await this.sweep(why);
          this.lastError = null;
        } catch (e) {
          if (this.stopped) break;
          this.lastError = errText(e);
          this.log.warn(`Check of the chat failed (${why}): ${errText(e)} – retrying in a few minutes.`);
          this.deferSweep(randInt(60e3, 180e3), 'retry after error');
        }
        why = 'follow-up';
      } while (this.again && !this.stopped);
    } finally {
      this.running = false;
      this.sweepStartedAt = 0;
    }
  }

  async sweep(reason) {
    const s = this.settings;
    const now = this.now();

    if (this.isPaused()) {
      this.log.debug(`Sweep (${reason}) skipped: paused by you.`);
      return { deleted: 0, userPaused: true };
    }
    if (this.state.pausedUntil && this.state.pausedUntil > now) {
      this.log.warn(`Deletions are paused until ${fmtMs(this.state.pausedUntil)}; will resume automatically.`);
      this.deferSweep(this.state.pausedUntil - now + randInt(5e3, 30e3), 'resume after pause');
      return { deleted: 0, paused: true };
    }

    const messages = await this.adapter.fetchMessages();
    this.lastSweepAt = this.now();
    const plan = planSweep(messages, {
      nowSec: Math.floor(now / 1000),
      maxAgeSec: s.maxMessageAgeHours * 3600,
      activeSinceSec: typeof this.activeSinceSec === 'function' ? this.activeSinceSec() : this.activeSinceSec,
      skipIds: new Set(Object.keys(this.state.skip)),
    });

    if (plan.tooOld.length) {
      for (const m of plan.tooOld) this.state.skip[m.id] = { reason: 'too-old', at: now };
      this.log.warn(`${plan.tooOld.length} of your message(s) are older than ${s.maxMessageAgeHours}h – ` +
        'past WhatsApp\'s "delete for everyone" window, so they are left alone.');
      this._save();
    }
    if (plan.pending.length) {
      this.log.info(`${plan.pending.length} message(s) still sending; will check again shortly.`);
      this.deferSweep(randInt(45e3, 90e3), 'waiting for send');
    }
    if (!plan.toDelete.length) {
      this.log.debug(`Sweep (${reason}): nothing to delete.`);
      return { deleted: 0 };
    }

    if (s.dryRun) {
      const fresh = plan.toDelete.filter((m) => !this.dryRunSeen.has(m.id));
      fresh.forEach((m) => this.dryRunSeen.add(m.id));
      if (fresh.length) {
        this.log.info(`[DRY-RUN] Their reply at ${fmtUnix(plan.trigger.timestamp)} would delete ${fresh.length} message(s):`);
        fresh.forEach((m) => this.log.info(`[DRY-RUN]   your ${m.type} from ${fmtUnix(m.timestamp)} (${shortId(m.id)})`));
      }
      return { deleted: 0, dryRun: plan.toDelete.length };
    }

    this.log.info(`Reply at ${fmtUnix(plan.trigger.timestamp)} → deleting ${plan.toDelete.length} earlier message(s) of yours.`);
    let deleted = 0;
    let failuresInRow = 0;

    for (let i = 0; i < plan.toDelete.length; i++) {
      if (this.stopped) break;
      if (this.isPaused()) {
        this.log.info('Paused by you – stopping this cleanup.');
        break;
      }
      const m = plan.toDelete[i];

      const wait = this.budget.msUntilAvailable(this.now());
      if (wait > 0) {
        const left = plan.toDelete.length - i;
        this.log.warn(`Safety limit reached (${s.maxDeletesPerHour}/hour, ${s.maxDeletesPerDay}/day). ` +
          `${left} remaining message(s) will be handled in ~${Math.ceil(wait / 60e3)} min.`);
        this.deferSweep(wait + randInt(15e3, 60e3), 'rate limit');
        break;
      }

      const r = await this.deleteOne(m);
      switch (r.kind) {
        case 'ok':
          deleted++;
          failuresInRow = 0;
          delete this.state.attempts[m.id];
          this.state.totals.deleted = (this.state.totals.deleted || 0) + 1;
          this.lastDeletionAt = this.now();
          this.log.info(`Deleted for everyone: your ${m.type} from ${fmtUnix(m.timestamp)} (${shortId(m.id)}).`);
          break;
        case 'already':
        case 'gone':
          failuresInRow = 0;
          delete this.state.attempts[m.id];
          break;
        case 'vanished':
          failuresInRow = 0;
          delete this.state.attempts[m.id];
          this.state.skip[m.id] = { reason: 'vanished', at: this.now() };
          this.log.warn(`Deleted ${shortId(m.id)}, but couldn't find the "deleted" placeholder to confirm it. ` +
            'If the other person still sees that message, tell the developer.');
          break;
        case 'cannot':
          failuresInRow = 0;
          delete this.state.attempts[m.id];
          this.state.skip[m.id] = { reason: r.reason, at: this.now() };
          this.log.warn(`WhatsApp won't delete your ${m.type} from ${fmtUnix(m.timestamp)} for everyone (${r.reason}); skipping it.`);
          break;
        case 'incompatible':
          this._pause(s.incompatiblePauseMin,
            'WhatsApp Web changed and the safety check is unavailable. Nothing will be deleted until this works again. ' +
            'Fix: stop the service, run "npm run update-lib", start it again.');
          this._save();
          return { deleted, paused: true };
        case 'unverified':
          failuresInRow = 0;
          this.log.warn(`Could not confirm deletion of ${shortId(m.id)} yet; the next check will verify it.`);
          break;
        case 'error':
        default: {
          failuresInRow++;
          const n = (this.state.attempts[m.id] && this.state.attempts[m.id].n) || 0;
          this.log.warn(`Delete failed for ${shortId(m.id)} (attempt ${n}/${s.maxAttemptsPerMessage}): ${errText(r.error)}`);
          if (n >= s.maxAttemptsPerMessage) {
            delete this.state.attempts[m.id];
            this.state.skip[m.id] = { reason: 'gave-up', at: this.now() };
            this.log.error(`Giving up on ${shortId(m.id)} after ${n} attempts. Delete it manually if needed.`);
          }
          if (failuresInRow >= s.circuitBreakerFailures) {
            this._pause(s.circuitBreakerPauseMin, `${failuresInRow} failures in a row – backing off instead of hammering WhatsApp`);
            this._save();
            return { deleted, paused: true };
          }
        }
      }
      this._save();
      if (i < plan.toDelete.length - 1 && !this.stopped) {
        await this.sleep(randInt(s.deleteDelaySec[0] * 1000, s.deleteDelaySec[1] * 1000));
      }
    }

    if (deleted) {
      this.log.info(`Cleanup done: ${deleted} deleted (total so far: ${this.state.totals.deleted}).`);
      try { await this.adapter.presenceOff(); } catch { /* cosmetic */ }
    }
    return { deleted };
  }

  async deleteOne(m) {
    let chk;
    try {
      chk = await this.adapter.checkRevoke(m.id);
    } catch (e) {
      if (e && e.code === 'INCOMPATIBLE') return { kind: 'incompatible' };
      return { kind: 'error', error: e };
    }
    if (!chk || !chk.found) return { kind: 'gone' };
    if (!chk.fromMe) return { kind: 'cannot', reason: 'not your message' }; // should be impossible; hard guard
    if (chk.type === 'revoked') return { kind: 'already' };
    if (!chk.canRevoke) return { kind: 'cannot', reason: 'outside WhatsApp\'s allowed window or not deletable' };

    const prev = (this.state.attempts[m.id] && this.state.attempts[m.id].n) || 0;
    this.state.attempts[m.id] = { n: prev + 1, at: this.now() };
    this.budget.record(this.now()); // count every real attempt against the safety budget
    this._save();

    try {
      await this.adapter.revoke(m.id);
    } catch (e) {
      return { kind: 'error', error: e };
    }

    // Confirm it now shows as deleted. Keep looking for a few seconds: WhatsApp may
    // briefly have no record while it re-files the message as "deleted".
    let lastSeen;
    let everMissing = false;
    for (let k = 0; k < 4; k++) {
      await this.sleep(1500 + k * 1000);
      try {
        lastSeen = await this.adapter.getType(m.id, m);
      } catch {
        lastSeen = undefined;
      }
      if (lastSeen === 'revoked') return { kind: 'ok' };
      if (lastSeen === null) everMissing = true;
    }
    if (lastSeen === null) return { kind: 'vanished' };
    if (lastSeen === undefined) return { kind: everMissing ? 'vanished' : 'unverified' };
    return { kind: 'error', error: new Error(`still shows as "${lastSeen}" after delete`) };
  }

  _pause(minutes, why) {
    this.state.pausedUntil = this.now() + minutes * 60e3;
    this.log.error(`Pausing deletions for ${minutes} min: ${why}`);
    this.deferSweep(minutes * 60e3 + randInt(10e3, 60e3), 'resume after pause');
  }

  _save() {
    const now = this.now();
    for (const [k, v] of Object.entries(this.state.skip)) {
      if (!v || now - (v.at || 0) > SKIP_TTL) delete this.state.skip[k];
    }
    const keys = Object.keys(this.state.skip);
    if (keys.length > MAX_SKIP_ENTRIES) {
      keys.sort((a, b) => this.state.skip[a].at - this.state.skip[b].at)
        .slice(0, keys.length - MAX_SKIP_ENTRIES)
        .forEach((k) => delete this.state.skip[k]);
    }
    for (const [k, v] of Object.entries(this.state.attempts)) {
      if (!v || now - (v.at || 0) > ATTEMPT_TTL) delete this.state.attempts[k];
    }
    this.state.rateEvents = this.budget.toJSON();
    this.persist();
  }
}

/**
 * Phone commands, sent as a message to yourself ("Message yourself" chat).
 * The whole message must be the command, so ordinary notes never trigger anything.
 *   pause | stop | off              pause until you resume
 *   pause 30m | pause 2h | pause 1d  pause for a while, then resume automatically
 *   resume | start | on             resume; messages you sent while paused are deleted too
 *   ("resume all" is accepted as the same command)
 *   status                          the script reacts ✅ running, ⏸️ paused, ⚠️ problem
 * An optional leading ! / # . is allowed (e.g. "!pause").
 */
function parseCommand(body) {
  const t = String(body || '').trim().toLowerCase().replace(/^[!/#.]\s*/, '').replace(/\s+/g, ' ');
  const p = t.match(/^(?:pause|stop|off)(?: (?:for )?(\d{1,4}) ?(m|min|mins|minutes?|h|hr|hrs|hours?|d|days?))?$/);
  if (p) {
    let ms = 0;
    if (p[1]) {
      const unit = p[2][0] === 'm' ? 60e3 : p[2][0] === 'h' ? 3600e3 : 86400e3;
      ms = Math.min(Number(p[1]) * unit, 30 * 86400e3);
    }
    return ms > 0 || !p[1] ? { cmd: 'pause', ms } : null;
  }
  if (/^(?:resume|start|on|unpause)(?: all)?$/.test(t)) return { cmd: 'resume' };
  if (/^(?:status|\?)$/.test(t)) return { cmd: 'status' };
  return null;
}

module.exports = {
  Engine, parseCommand, planSweep, normalizeMessages, validateSettings, isTrigger, isOwnDeletable,
  DEFAULT_SETTINGS, SYSTEM_TYPES,
};

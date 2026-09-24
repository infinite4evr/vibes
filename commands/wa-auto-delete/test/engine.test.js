'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { Engine, planSweep, normalizeMessages, validateSettings, DEFAULT_SETTINGS } = require('../engine');
const L = require('../lib');

const NOW = 1_800_000_000_000; // fixed clock (ms)
const NOW_S = NOW / 1000;
const quietLog = { debug() {}, info() {}, warn() {}, error() {} };

function msg(id, fromMe, secondsAgo, type = 'chat', ack = 2) {
  return { id, fromMe, type, timestamp: NOW_S - secondsAgo, ack };
}

/** A fake WhatsApp chat that behaves like the real adapter. */
function fakeChat(messages, opts = {}) {
  const store = new Map(messages.map((m) => [m.id, { ...m }]));
  const calls = { revoke: [], check: [] };
  const adapter = {
    async fetchMessages() {
      return [...store.values()].map((m) => ({ ...m })).sort((a, b) => a.timestamp - b.timestamp);
    },
    async checkRevoke(id) {
      calls.check.push(id);
      if (opts.incompatible) { const e = new Error('x'); e.code = 'INCOMPATIBLE'; throw e; }
      const m = store.get(id);
      if (!m) return { found: false };
      const can = opts.canRevoke ? opts.canRevoke(m) : NOW_S - m.timestamp < 60 * 3600;
      return { found: true, fromMe: m.fromMe, type: m.type, canRevoke: can };
    },
    async revoke(id) {
      calls.revoke.push(id);
      if (opts.failRevoke && opts.failRevoke(id)) throw new Error('network glitch');
      if (!opts.noopRevoke) store.get(id).type = 'revoked';
    },
    async getType(id) { const m = store.get(id); return m ? m.type : null; },
    async presenceOff() {},
  };
  return { adapter, store, calls };
}

function makeEngine(chat, overrides = {}, state = {}) {
  const st = { skip: {}, attempts: {}, rateEvents: [], pausedUntil: 0, totals: { deleted: 0 }, ...state };
  const scheduled = [];
  const engine = new Engine({
    adapter: chat.adapter,
    settings: { ...DEFAULT_SETTINGS, ...overrides },
    state: st,
    persist: () => {},
    logger: quietLog,
    now: () => NOW,
    sleep: async () => {},
    timers: { set: (fn, ms) => { scheduled.push({ fn, ms }); return scheduled.length; }, clear: () => {} },
    activeSinceSec: overrides.activeSinceSec || 0,
  });
  return { engine, state: st, scheduled };
}

// ---------------------------------------------------------------- planning rule

test('deletes only MY messages sent BEFORE their latest reply', () => {
  const msgs = [
    msg('me1', true, 500), msg('me2', true, 400),
    msg('them1', false, 300),
    msg('me3', true, 200),
    msg('them2', false, 100),
    msg('me4', true, 50), // sent after their latest reply -> must survive
  ];
  const plan = planSweep(msgs, { nowSec: NOW_S, maxAgeSec: 58 * 3600 });
  assert.deepEqual(plan.toDelete.map((m) => m.id), ['me1', 'me2', 'me3']);
  assert.equal(plan.trigger.id, 'them2');
});

test('nothing happens until they reply at all', () => {
  const plan = planSweep([msg('me1', true, 100), msg('me2', true, 50)], { nowSec: NOW_S, maxAgeSec: 1e9 });
  assert.equal(plan.trigger, null);
  assert.equal(plan.toDelete.length, 0);
});

test('system notices and reactions are not treated as replies', () => {
  const msgs = [
    msg('me1', true, 300),
    msg('sys', false, 200, 'e2e_notification'),
    msg('call', false, 150, 'call_log'),
    msg('grp', false, 100, 'gp2'),
  ];
  assert.equal(planSweep(msgs, { nowSec: NOW_S, maxAgeSec: 1e9 }).toDelete.length, 0);
});

test('media and other real messages from them DO count as replies', () => {
  const msgs = [msg('me1', true, 300), msg('img', false, 100, 'image')];
  assert.deepEqual(planSweep(msgs, { nowSec: NOW_S, maxAgeSec: 1e9 }).toDelete.map((m) => m.id), ['me1']);
});

test('already-deleted and too-old messages are skipped; unsent ones wait', () => {
  const msgs = [
    msg('old', true, 70 * 3600),
    msg('gone', true, 400, 'revoked'),
    msg('sending', true, 300, 'chat', 0),
    msg('ok', true, 200),
    msg('them', false, 100),
  ];
  const plan = planSweep(msgs, { nowSec: NOW_S, maxAgeSec: 58 * 3600 });
  assert.deepEqual(plan.toDelete.map((m) => m.id), ['ok']);
  assert.deepEqual(plan.tooOld.map((m) => m.id), ['old']);
  assert.deepEqual(plan.pending.map((m) => m.id), ['sending']);
});

test('"only from now on" setting protects messages sent before setup', () => {
  const msgs = [msg('before', true, 1000), msg('after', true, 200), msg('them', false, 100)];
  const plan = planSweep(msgs, { nowSec: NOW_S, maxAgeSec: 1e9, activeSinceSec: NOW_S - 500 });
  assert.deepEqual(plan.toDelete.map((m) => m.id), ['after']);
});

test('normalizeMessages handles library objects and sorts oldest first', () => {
  const raw = [
    { id: { _serialized: 'b', fromMe: true }, fromMe: true, type: 'chat', timestamp: 20, ack: 1 },
    { id: { _serialized: 'a', fromMe: false }, fromMe: false, type: 'chat', timestamp: 10 },
    { id: null }, null,
  ];
  assert.deepEqual(normalizeMessages(raw).map((m) => m.id), ['a', 'b']);
});

// ---------------------------------------------------------------- engine behaviour

test('engine deletes the right messages, verifies, and counts them', async () => {
  const chat = fakeChat([msg('me1', true, 300), msg('me2', true, 250), msg('them', false, 100), msg('me3', true, 50)]);
  const { engine, state } = makeEngine(chat);
  const r = await engine.sweep('test');
  assert.equal(r.deleted, 2);
  assert.deepEqual(chat.calls.revoke, ['me1', 'me2']);
  assert.equal(chat.store.get('me3').type, 'chat');
  assert.equal(state.totals.deleted, 2);
  // running again is a no-op (idempotent)
  const again = await engine.sweep('test');
  assert.equal(again.deleted, 0);
  assert.equal(chat.calls.revoke.length, 2);
});

test('dry-run never deletes', async () => {
  const chat = fakeChat([msg('me1', true, 300), msg('them', false, 100)]);
  const { engine } = makeEngine(chat, { dryRun: true });
  const r = await engine.sweep('test');
  assert.equal(r.dryRun, 1);
  assert.equal(chat.calls.revoke.length, 0);
});

test('never calls delete when WhatsApp says "for everyone" is not allowed (no silent delete-for-me)', async () => {
  const chat = fakeChat([msg('me1', true, 300), msg('them', false, 100)], { canRevoke: () => false });
  const { engine, state } = makeEngine(chat);
  await engine.sweep('test');
  assert.equal(chat.calls.revoke.length, 0);
  assert.ok(state.skip.me1, 'message is remembered as not deletable');
  await engine.sweep('test');
  assert.equal(chat.calls.check.length, 1, 'not re-checked forever');
});

test('WhatsApp internals changed -> fail closed and pause', async () => {
  const chat = fakeChat([msg('me1', true, 300), msg('them', false, 100)], { incompatible: true });
  const { engine, state } = makeEngine(chat);
  const r = await engine.sweep('test');
  assert.equal(r.paused, true);
  assert.equal(chat.calls.revoke.length, 0);
  assert.ok(state.pausedUntil > NOW);
  const r2 = await engine.sweep('test');
  assert.equal(r2.paused, true, 'stays paused');
});

test('transient failure: retries up to the limit, then gives up on that message', async () => {
  const chat = fakeChat([msg('me1', true, 300), msg('them', false, 100)], { failRevoke: () => true });
  const { engine, state } = makeEngine(chat, { maxAttemptsPerMessage: 3, circuitBreakerFailures: 99 });
  for (let i = 0; i < 5; i++) await engine.sweep('test');
  assert.equal(chat.calls.revoke.length, 3);
  assert.equal(state.skip.me1.reason, 'gave-up');
});

test('circuit breaker pauses after several failures in a row', async () => {
  const msgs = [];
  for (let i = 0; i < 10; i++) msgs.push(msg(`me${i}`, true, 1000 - i));
  msgs.push(msg('them', false, 10));
  const chat = fakeChat(msgs, { failRevoke: () => true });
  const { engine, state } = makeEngine(chat, { circuitBreakerFailures: 4 });
  const r = await engine.sweep('test');
  assert.equal(r.paused, true);
  assert.equal(chat.calls.revoke.length, 4);
  assert.ok(state.pausedUntil > NOW);
});

test('delete that does not take effect is reported as a failure', async () => {
  const chat = fakeChat([msg('me1', true, 300), msg('them', false, 100)], { noopRevoke: true });
  const { engine, state } = makeEngine(chat);
  await engine.sweep('test');
  assert.equal(state.totals.deleted, 0);
  assert.equal(state.attempts.me1.n, 1);
});

test('hourly safety limit stops early and schedules the rest', async () => {
  const msgs = [];
  for (let i = 0; i < 8; i++) msgs.push(msg(`me${i}`, true, 1000 - i));
  msgs.push(msg('them', false, 10));
  const chat = fakeChat(msgs);
  const { engine, scheduled } = makeEngine(chat, { maxDeletesPerHour: 5 });
  const r = await engine.sweep('test');
  assert.equal(r.deleted, 5);
  assert.ok(scheduled.some((s) => s.ms > 0), 'follow-up scheduled');
});

test('rate limit survives restarts via persisted history', async () => {
  const history = Array.from({ length: 5 }, (_, i) => NOW - 60e3 * (i + 1));
  const chat = fakeChat([msg('me1', true, 300), msg('them', false, 100)]);
  const { engine } = makeEngine(chat, { maxDeletesPerHour: 5 }, { rateEvents: history });
  const r = await engine.sweep('test');
  assert.equal(r.deleted, 0);
  assert.equal(chat.calls.revoke.length, 0);
});

test('burst of replies triggers a single sweep (debounce)', async () => {
  const chat = fakeChat([msg('me1', true, 300), msg('them', false, 100)]);
  const { engine, scheduled } = makeEngine(chat);
  engine.onReply(); engine.onReply(); engine.onReply();
  assert.ok(scheduled.length >= 1);
  assert.ok(scheduled.every((s) => s.ms <= DEFAULT_SETTINGS.settleMaxSec * 1000));
});

test('concurrent sweep requests collapse into one follow-up (no double deletes)', async () => {
  const chat = fakeChat([msg('me1', true, 300), msg('them', false, 100)]);
  const { engine } = makeEngine(chat);
  await Promise.all([engine.requestSweep('a'), engine.requestSweep('b'), engine.requestSweep('c')]);
  assert.equal(chat.calls.revoke.length, 1);
});

test('fetch errors never crash the engine', async () => {
  const chat = fakeChat([]);
  chat.adapter.fetchMessages = async () => { throw new Error('page reloaded'); };
  const { engine, scheduled } = makeEngine(chat);
  await engine.requestSweep('test'); // must not throw
  assert.ok(engine.lastError.includes('page reloaded'));
  assert.ok(scheduled.length > 0, 'retry scheduled');
});

// ---------------------------------------------------------------- utilities

test('RateBudget math', () => {
  const b = new L.RateBudget({ perHour: 2, perDay: 3 }, []);
  assert.equal(b.msUntilAvailable(NOW), 0);
  b.record(NOW - 30 * 60e3);
  b.record(NOW - 10 * 60e3);
  assert.equal(b.msUntilAvailable(NOW), 30 * 60e3);
  assert.equal(b.msUntilAvailable(NOW + 31 * 60e3), 0);
});

test('settings validation rejects bad values safely', () => {
  const warnings = [];
  const s = validateSettings({ maxDeletesPerHour: -5, deleteDelaySec: [9, 1], dryRun: 'yes', typo: 1, scanDepth: 300 }, (w) => warnings.push(w));
  assert.equal(s.maxDeletesPerHour, DEFAULT_SETTINGS.maxDeletesPerHour);
  assert.deepEqual(s.deleteDelaySec, DEFAULT_SETTINGS.deleteDelaySec);
  assert.equal(s.dryRun, false);
  assert.equal(s.scanDepth, 300);
  assert.equal(warnings.length, 4);
});

test('atomic JSON write + corrupt file quarantine', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'wad-'));
  const f = path.join(dir, 's.json');
  L.writeJsonAtomic(f, { a: 1 });
  assert.deepEqual(L.readJson(f, null).value, { a: 1 });
  fs.writeFileSync(f, '{broken');
  const r = L.readJson(f, { fresh: true }, { quarantine: true });
  assert.deepEqual(r.value, { fresh: true });
  assert.ok(r.error);
  assert.ok(fs.readdirSync(dir).some((n) => n.includes('.corrupt-')));
});

test('single-instance lock', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'wad-'));
  const f = path.join(dir, 'run.lock');
  assert.equal(L.acquireLock(f).ok, true);
  fs.writeFileSync(f, '999999'); // stale pid from a crashed run
  assert.equal(L.acquireLock(f).ok, true, 'stale lock is taken over');
  L.releaseLock(f);
  assert.equal(fs.existsSync(f), false);
});

test('withTimeout rejects hung calls', async () => {
  await assert.rejects(L.withTimeout(new Promise(() => {}), 50, 'x'), /timed out/);
});

test('message briefly missing during re-filing, then shows deleted -> counted as success', async () => {
  const chat = fakeChat([msg('me1', true, 300), msg('them', false, 100)]);
  let calls = 0;
  chat.adapter.getType = async () => (++calls < 3 ? null : 'revoked');
  const { engine, state } = makeEngine(chat);
  await engine.sweep('test');
  assert.equal(state.totals.deleted, 1);
});

test('message that never reappears is reported as vanished (not retried)', async () => {
  const chat = fakeChat([msg('me1', true, 300), msg('them', false, 100)]);
  chat.adapter.getType = async () => null;
  const { engine, state } = makeEngine(chat);
  await engine.sweep('test');
  assert.equal(state.skip.me1.reason, 'vanished');
  await engine.sweep('test');
  assert.equal(chat.calls.revoke.length, 1);
});

// ---------------------------------------------------------------- phone commands / pause

const { parseCommand } = require('../engine');

test('phone commands are recognised only when the whole note is the command', () => {
  assert.deepEqual(parseCommand('pause'), { cmd: 'pause', ms: 0 });
  assert.deepEqual(parseCommand('  !Pause  '), { cmd: 'pause', ms: 0 });
  assert.deepEqual(parseCommand('pause 2h'), { cmd: 'pause', ms: 2 * 3600e3 });
  assert.deepEqual(parseCommand('pause for 30 min'), { cmd: 'pause', ms: 30 * 60e3 });
  assert.deepEqual(parseCommand('off 1d'), { cmd: 'pause', ms: 86400e3 });
  assert.deepEqual(parseCommand('resume'), { cmd: 'resume', all: false });
  assert.deepEqual(parseCommand('#ON'), { cmd: 'resume', all: false });
  assert.deepEqual(parseCommand('resume all'), { cmd: 'resume', all: true });
  assert.deepEqual(parseCommand('status'), { cmd: 'status' });
  assert.equal(parseCommand('stop by the shop later'), null);
  assert.equal(parseCommand('remember to pause the movie'), null);
  assert.equal(parseCommand('pause 0h'), null);
  assert.equal(parseCommand(''), null);
  assert.equal(parseCommand('pause 99999d'), null, 'absurd numbers rejected');
  assert.equal(parseCommand('pause 9999d').ms, 30 * 86400e3, 'long pauses capped at 30 days');
});

test('paused by you: nothing is deleted, and pausing mid-cleanup stops it', async () => {
  const chat = fakeChat([msg('me1', true, 300), msg('me2', true, 250), msg('them', false, 100)]);
  let paused = true;
  const { engine } = makeEngine(chat);
  engine.isPaused = () => paused;
  let r = await engine.sweep('test');
  assert.equal(r.userPaused, true);
  assert.equal(chat.calls.revoke.length, 0);
  paused = false;
  const origRevoke = chat.adapter.revoke;
  chat.adapter.revoke = async (id) => { await origRevoke(id); paused = true; }; // pause arrives during cleanup
  r = await engine.sweep('test');
  assert.equal(chat.calls.revoke.length, 1, 'stopped after the in-flight deletion');
});

test('resume "fresh": messages sent before the resume time are kept', async () => {
  const chat = fakeChat([msg('old', true, 300), msg('them', false, 100)]);
  const { engine } = makeEngine(chat);
  engine.activeSinceSec = () => NOW_S - 200; // resumed 200s ago
  await engine.sweep('test');
  assert.equal(chat.calls.revoke.length, 0);
});

'use strict';

// Runs the in-page code against a simulated WhatsApp Web store that uses the NEW
// id format ("$1" instead of "_serialized" on message keys) that broke whatsapp-web.js 1.34.7.
const test = require('node:test');
const assert = require('node:assert/strict');
const { _page: P } = require('../wa');

const CHAT = '919876543210@c.us';
const NOW = 1_800_000_000;

function makeWorld({ canRevoke = () => true, oldIdFormat = false } = {}) {
  const key = (id, fromMe) => (oldIdFormat
    ? { _serialized: id, fromMe, remote: { _serialized: CHAT } }
    : { $1: id, fromMe, remote: { _serialized: CHAT } }); // new format: no _serialized
  const msgs = [
    { id: key('m1', true), t: NOW - 300, type: 'chat', ack: 3 },
    { id: key('sys', false), t: NOW - 290, type: 'e2e_notification', isNotification: true },
    { id: key('m2', true), t: NOW - 200, type: 'image', ack: 3 },
    { id: key('t1', false), t: NOW - 100, type: 'chat', ack: 3 },
    { id: key('m3', true), t: NOW - 50, type: 'chat', ack: 2 },
  ];
  const kid = (k) => (k && (k._serialized || k.$1)) || k;
  const listeners = [];
  const Msg = {
    get: (id) => msgs.find((m) => kid(m.id) === id),
    getMessagesById: async (ids) => ({ messages: msgs.filter((m) => ids.includes(kid(m.id))) }),
    on: (ev, fn) => { if (ev === 'add') listeners.push(fn); },
  };
  const chat = {
    id: { _serialized: CHAT }, name: 'Test Person', t: NOW - 50,
    contact: { phoneNumber: { _serialized: CHAT } },
    msgs: { getModelsArray: () => msgs.slice(2) }, // only some loaded, rest via loadEarlierMsgs
  };
  const group = { id: { _serialized: '123@g.us' }, formattedTitle: 'Family', t: NOW - 999, contact: {} };
  const broken = { get id() { throw new Error('r'); } }; // a chat that explodes on access
  const Chat = {
    get: (w) => [chat, group].find((c) => c.id._serialized === (w && w._serialized ? w._serialized : w)),
    getModelsArray: () => [chat, group, broken],
  };
  const revoked = [];
  const modules = {
    WAWebCollections: { Chat, Msg },
    WAWebWidFactory: { createWid: (id) => ({ _serialized: id }) },
    WAWebChatLoadMessages: { loadEarlierMsgs: async () => (chat.loadedAll ? [] : ((chat.loadedAll = true), msgs.slice(0, 2))) },
    WAWebMsgActionCapability: { canSenderRevokeMsg: (m) => canRevoke(m) },
    WAWebCmd: { Cmd: { sendRevokeMsgs: async (c, arg, opts) => { revoked.push({ c, arg, opts }); arg.list[0].type = 'revoked'; } } },
    WAWebSocketModel: { Socket: { state: 'CONNECTED' } },
  };
  global.window = {
    require: (n) => { if (!(n in modules)) throw new Error(`no module ${n}`); return modules[n]; },
    Debug: { VERSION: '2.3000.1043270046' },
    WWebJS: { compareWwebVersions: () => true },
  };
  P.installHelpers(3);
  return { msgs, revoked, listeners, modules };
}

test('lists chats even when one chat is broken, detects groups by id', () => {
  makeWorld();
  const chats = P.pageListChats();
  assert.equal(chats.length, 2);
  assert.deepEqual(chats.map((c) => [c.name, c.isGroup, c.phone]), [['Test Person', false, '919876543210'], ['Family', true, null]]);
});

test('finds a chat by phone number', () => {
  makeWorld();
  assert.equal(P.pageFindChatByPhone('919876543210').id, CHAT);
  assert.equal(P.pageFindChatByPhone('111111'), null);
});

test('reads messages with the NEW "$1" id format, oldest first, skipping notices', async () => {
  makeWorld();
  const { messages: out } = await P.pageFetchMessages(CHAT, 150);
  assert.deepEqual(out.map((m) => m.id), ['m1', 'm2', 't1', 'm3']);
  assert.deepEqual(out.map((m) => m.fromMe), [true, true, false, true]);
});

test('still works with the OLD "_serialized" format', async () => {
  makeWorld({ oldIdFormat: true });
  const { messages: out } = await P.pageFetchMessages(CHAT, 150);
  assert.deepEqual(out.map((m) => m.id), ['m1', 'm2', 't1', 'm3']);
});

// ---------------------------------------------------------------- scrolling back through history

/**
 * A long chat: one message every `stepSec`, newest at NOW. Only the newest `inMemory`
 * are loaded at first; each loadEarlierMsgs() call loads the next `page` older ones.
 */
function makeLongChat({ total, stepSec, inMemory = 40, page = 50, loader } = {}) {
  const w = makeWorld();
  const all = [];
  for (let i = 0; i < total; i++) {
    const fromMe = i % 3 !== 0;
    all.push({ id: { $1: `h${i}`, fromMe, remote: { _serialized: CHAT } }, t: NOW - (total - 1 - i) * stepSec, type: 'chat', ack: 3 });
  }
  let loadedFrom = total - inMemory;
  const chat = w.modules.WAWebCollections.Chat.get(CHAT);
  chat.msgs = { getModelsArray: () => all.slice(loadedFrom) };
  let calls = 0;
  const defaultLoader = async () => {
    calls++;
    if (loadedFrom === 0) return [];
    const next = Math.max(0, loadedFrom - page);
    const chunk = all.slice(next, loadedFrom);
    loadedFrom = next;
    return chunk;
  };
  w.modules.WAWebChatLoadMessages = { loadEarlierMsgs: loader ? loader(defaultLoader) : defaultLoader };
  return { all, calls: () => calls };
}

test('scrolls back until the whole delete window is covered, then stops', async () => {
  // 1000 messages, one every 10 min (~7 days). The 58h window needs ~348 of them.
  const { calls } = makeLongChat({ total: 1000, stepSec: 600 });
  const sinceSec = NOW - 58 * 3600;
  const r = await P.pageFetchMessages(CHAT, { sinceSec, maxMsgs: 3000 });
  assert.equal(r.stop, 'window');
  assert.ok(r.oldest <= sinceSec, 'reached past the start of the window');
  assert.ok(r.messages.some((m) => m.timestamp <= sinceSec), 'includes the oldest deletable messages');
  assert.ok(r.messages.length < 450, `did not load far past the window (${r.messages.length})`);
  assert.equal(calls(), 7, '40 in memory + 7 pages of 50 = 390 messages ≈ 65h');
});

test('does not load anything more when memory already covers the window', async () => {
  const { calls } = makeLongChat({ total: 100, stepSec: 3 * 3600, inMemory: 30 });
  const r = await P.pageFetchMessages(CHAT, { sinceSec: NOW - 58 * 3600, maxMsgs: 3000 });
  assert.equal(r.stop, 'window');
  assert.equal(calls(), 0);
});

test('reports reaching the start of the chat', async () => {
  makeLongChat({ total: 120, stepSec: 60 }); // whole chat is 2h old
  const r = await P.pageFetchMessages(CHAT, { sinceSec: NOW - 58 * 3600, maxMsgs: 3000 });
  assert.equal(r.stop, 'start');
  assert.equal(r.messages.length, 120, 'every message was read');
});

test('stops at the scanDepth cap and says so', async () => {
  makeLongChat({ total: 5000, stepSec: 10 }); // very busy chat: 58h ≈ 20,000 messages
  const r = await P.pageFetchMessages(CHAT, { sinceSec: NOW - 58 * 3600, maxMsgs: 500 });
  assert.equal(r.stop, 'cap');
  assert.equal(r.messages.length, 500);
  assert.equal(r.messages[r.messages.length - 1].id, 'h4999', 'kept the newest ones');
});

test('a failing loader is reported instead of silently checking only recent messages', async () => {
  makeLongChat({ total: 1000, stepSec: 600, loader: () => async () => { throw new Error('boom'); } });
  const r = await P.pageFetchMessages(CHAT, { sinceSec: NOW - 58 * 3600, maxMsgs: 3000 });
  assert.equal(r.stop, 'loader');
  assert.match(r.error, /boom/);
  assert.equal(r.messages.length, 40, 'still returns what was already loaded');
});

test('falls back to the other loadEarlierMsgs call form', async () => {
  // This loader only accepts the chat itself, not { chat }.
  makeLongChat({
    total: 1000,
    stepSec: 600,
    loader: (real) => async (arg) => {
      if (!arg || arg.chat) throw new TypeError('bad argument');
      return real();
    },
  });
  delete global.window.__wadLoadForm;
  const r = await P.pageFetchMessages(CHAT, { sinceSec: NOW - 58 * 3600, maxMsgs: 3000 });
  assert.equal(r.stop, 'window');
  assert.equal(global.window.__wadLoadForm, 1, 'remembers the form that worked');
});

test('revoke: checks permission and deletes for everyone in one step', async () => {
  const w = makeWorld();
  const r = await P.pageRevoke('m1');
  assert.equal(r.ok, true);
  assert.equal(w.revoked.length, 1);
  assert.equal(w.revoked[0].arg.type, 'message');
  assert.equal(w.revoked[0].c.id._serialized, CHAT);
  assert.equal(await P.pageGetType('m1'), 'revoked');
});

test('revoke refuses when WhatsApp disallows it (never falls back to delete-for-me)', async () => {
  const w = makeWorld({ canRevoke: () => false });
  const r = await P.pageRevoke('m1');
  assert.equal(r.ok, false);
  assert.equal(w.revoked.length, 0);
});

test('revoke refuses other people\'s messages', async () => {
  const w = makeWorld();
  const r = await P.pageRevoke('t1');
  assert.equal(r.ok, false);
  assert.equal(w.revoked.length, 0);
});

test('missing internal module -> clear INCOMPATIBLE error, nothing deleted', async () => {
  const w = makeWorld();
  delete w.modules.WAWebMsgActionCapability;
  await assert.rejects(P.pageRevoke('m1'), /WAD_INCOMPATIBLE/);
  await assert.rejects(P.pageCheckRevoke('m1'), /WAD_INCOMPATIBLE/);
  assert.equal(w.revoked.length, 0);
});

test('own listener reports new incoming messages only', () => {
  const w = makeWorld();
  const seen = [];
  global.window.__wadIncoming = (ids, type) => seen.push([ids, type]);
  assert.equal(P.pageListen(), true);
  assert.equal(P.pageListen(), false, 'not registered twice');
  const fire = (m) => w.listeners.forEach((fn) => fn(m));
  fire({ isNewMsg: true, type: 'chat', id: { $1: 'x', fromMe: false, remote: { _serialized: CHAT } } });
  fire({ isNewMsg: true, type: 'chat', id: { $1: 'y', fromMe: true, remote: { _serialized: CHAT } } });
  fire({ isNewMsg: false, type: 'chat', id: { $1: 'z', fromMe: false, remote: { _serialized: CHAT } } });
  assert.equal(seen.length, 1);
  assert.ok(seen[0][0].includes(CHAT));
});

test('helpers missing after a page reload are detected', () => {
  makeWorld();
  delete global.window.__wad;
  assert.throws(() => P.pageListChats(), /WAD_NO_HELPERS/);
});

test('health check reads connection state', () => {
  makeWorld();
  assert.equal(P.pageHealth().state, 'CONNECTED');
});

test('wrapper reinstalls helpers after a page reload and flags incompatibility', async () => {
  const { WaDirect } = require('../wa');
  const w = makeWorld();
  const page = { evaluate: async (fn, ...args) => fn(...args), exposeFunction: async () => {} };
  const wa = new WaDirect(() => ({ pupPage: page }));
  delete global.window.__wad; // simulate WhatsApp reloading its page
  const chats = await wa.listChats();
  assert.equal(chats.length, 2, 'recovered transparently');
  delete w.modules.WAWebMsgActionCapability;
  await assert.rejects(wa.checkRevoke('m1'), (e) => e.code === 'INCOMPATIBLE');
  await assert.rejects(wa.revoke('m1'), (e) => e.code === 'INCOMPATIBLE');
});

test('verify finds a deleted message that WhatsApp re-filed under a new record (by permanent id)', async () => {
  const w = makeWorld();
  const i = w.msgs.findIndex((m) => m.id.$1 === 'm3');
  const orig = w.msgs.splice(i, 1)[0]; // old key no longer resolves
  w.msgs.push({ id: { $1: 'new-internal-key', id: 'm3', fromMe: true, remote: orig.id.remote }, t: orig.t, type: 'revoked' });
  assert.equal(await P.pageGetType('m3'), null, 'old lookup fails, like on your PC');
  assert.equal((await P.pageVerifyRevoked(CHAT, 'm3', orig.t)).type, 'revoked');
});

test('verify falls back to matching the send time', async () => {
  const w = makeWorld();
  const i = w.msgs.findIndex((m) => m.id.$1 === 'm3');
  const orig = w.msgs.splice(i, 1)[0];
  w.msgs.push({ id: { $1: 'x', id: 'something-else', fromMe: true, remote: orig.id.remote }, t: orig.t, type: 'revoked' });
  assert.equal((await P.pageVerifyRevoked(CHAT, 'm3', orig.t)).type, 'revoked');
});

test('verify reports a truly missing message as missing', async () => {
  const w = makeWorld();
  const i = w.msgs.findIndex((m) => m.id.$1 === 'm3');
  w.msgs.splice(i, 1);
  assert.equal((await P.pageVerifyRevoked(CHAT, 'm3', 12345)).type, null);
});

// ---------------------------------------------------------------- notes to self (phone commands)

const SELF = '910000000000@c.us';
function addSelfChat(w, notes) {
  const kid = (k) => (k && (k._serialized || k.$1)) || k;
  const selfMsgs = notes.map((n, i) => ({ id: { $1: `note${i}`, fromMe: true, remote: { _serialized: SELF } }, t: n.t, type: 'chat', body: n.body }));
  const selfChat = { id: { _serialized: SELF }, name: 'You', t: 1, msgs: { getModelsArray: () => selfMsgs } };
  const C = w.modules.WAWebCollections;
  const origGet = C.Chat.get;
  C.Chat.get = (x) => ((x && x._serialized ? x._serialized : x) === SELF ? selfChat : origGet(x));
  const origAll = C.Chat.getModelsArray;
  C.Chat.getModelsArray = () => [...origAll(), selfChat];
  const origMsgGet = C.Msg.get;
  C.Msg.get = (id) => selfMsgs.find((m) => kid(m.id) === id) || origMsgGet(id);
  w.modules.WAWebUserPrefsMeUser = { getMaybeMePnUser: () => ({ _serialized: SELF }), getMaybeMeLidUser: () => null };
  const reactions = [];
  w.modules.WAWebSendReactionMsgAction = { sendReactionToMsg: async (m, e) => { reactions.push([kid(m.id), e]); } };
  return { selfMsgs, reactions };
}

test('reads your notes-to-self and reacts to them', async () => {
  const w = makeWorld();
  const { reactions } = addSelfChat(w, [{ t: 10, body: 'buy milk' }, { t: 20, body: 'pause 2h' }]);
  const notes = P.pageOwnNotes(20);
  assert.deepEqual(notes.map((n) => n.body), ['buy milk', 'pause 2h']);
  assert.equal(await P.pageReact('note1', '⏸️'), true);
  assert.deepEqual(reactions, [['note1', '⏸️']]);
});

test('listener pings for your own notes-to-self but not for your messages in other chats', () => {
  const w = makeWorld();
  addSelfChat(w, []);
  let selfPings = 0;
  const incoming = [];
  global.window.__wadSelf = () => { selfPings++; };
  global.window.__wadIncoming = (ids, type) => incoming.push(type);
  P.pageListen();
  const fire = (m) => w.listeners.forEach((fn) => fn(m));
  fire({ isNewMsg: true, type: 'chat', body: 'pause', id: { $1: 'a', fromMe: true, remote: { _serialized: SELF } } });
  fire({ isNewMsg: true, type: 'chat', body: 'hi', id: { $1: 'b', fromMe: true, remote: { _serialized: CHAT } } });
  assert.equal(selfPings, 1);
  assert.equal(incoming.length, 0, 'your own messages never count as their reply');
});

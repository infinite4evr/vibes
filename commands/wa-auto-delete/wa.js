'use strict';

/**
 * Direct access to WhatsApp Web's internals, used instead of whatsapp-web.js helpers
 * that break whenever WhatsApp renames an internal field.
 *
 * Why: in mid-2026 WhatsApp renamed message-key "_serialized" to "$1". whatsapp-web.js
 * 1.34.7 still reads "_serialized", so its getChats / getChatById / message.delete fail
 * with the cryptic error "r". Everything here reads ids defensively (_serialized, $1,
 * toString) and only ever touches the few internal modules it truly needs.
 * The library is still used for launching the browser, login/session and connection events.
 *
 * Every in-page function below is plain JS executed inside the WhatsApp Web page.
 */

const L = require('./lib');

const HELPERS_VERSION = 3;

// ---------------------------------------------------------------- in-page code

/* eslint-disable no-undef */
function installHelpers(version) {
  const req = (name) => {
    try { return window.require(name); } catch (e) { return null; }
  };
  const keyStr = (k) => {
    if (!k) return null;
    if (typeof k === 'string') return k;
    if (typeof k._serialized === 'string' && k._serialized) return k._serialized;
    if (typeof k.$1 === 'string' && k.$1) return k.$1;
    try {
      const s = k.toString();
      return s && s !== '[object Object]' ? s : null;
    } catch (e) { return null; }
  };
  const coll = () => {
    const c = req('WAWebCollections');
    if (!c || !c.Chat || !c.Msg) throw new Error('WAD_INCOMPATIBLE: message store not found');
    return c;
  };
  const allChats = () => {
    try { return coll().Chat.getModelsArray() || []; } catch (e) { return []; }
  };
  // Read-only lookup: never creates a chat.
  const findChat = (chatId) => {
    const C = coll();
    let chat = null;
    try {
      const f = req('WAWebWidFactory');
      if (f && f.createWid) chat = C.Chat.get(f.createWid(chatId)) || null;
    } catch (e) { /* ignore */ }
    if (!chat) { try { chat = C.Chat.get(chatId) || null; } catch (e) { /* ignore */ } }
    if (!chat) chat = allChats().find((c) => keyStr(c.id) === chatId) || null;
    return chat;
  };
  const findMsg = async (msgId) => {
    const C = coll();
    let m = null;
    try { m = C.Msg.get(msgId) || null; } catch (e) { /* ignore */ }
    if (!m) {
      try {
        const r = await C.Msg.getMessagesById([msgId]);
        m = (r && r.messages && r.messages[0]) || null;
      } catch (e) { /* ignore */ }
    }
    return m;
  };
  const slim = (m) => ({
    id: keyStr(m.id),
    fromMe: Boolean(m.id && m.id.fromMe),
    type: String(m.type || 'unknown'),
    timestamp: Number(m.t) || 0,
    ack: typeof m.ack === 'number' ? m.ack : undefined,
  });
  const selfIds = () => {
    const M = req('WAWebUserPrefsMeUser');
    if (!M) return [];
    const ids = [];
    try { ids.push(keyStr(M.getMaybeMePnUser && M.getMaybeMePnUser())); } catch (e) { /* ignore */ }
    try { ids.push(keyStr(M.getMaybeMeLidUser && M.getMaybeMeLidUser())); } catch (e) { /* ignore */ }
    return ids.filter(Boolean);
  };
  window.__wad = { v: version, req, keyStr, coll, allChats, findChat, findMsg, slim, selfIds };
  return true;
}

function pageHealth() {
  const W = window.__wad;
  if (!W || W.v !== 3) throw new Error('WAD_NO_HELPERS');
  const sock = W.req('WAWebSocketModel');
  const state = sock && sock.Socket ? sock.Socket.state : null;
  return { state: state || null, version: (window.Debug && window.Debug.VERSION) || null };
}

function pageListChats() {
  const W = window.__wad;
  if (!W || W.v !== 3) throw new Error('WAD_NO_HELPERS');
  const out = [];
  for (const c of W.allChats()) {
    try {
      const id = W.keyStr(c.id);
      if (!id || /@(newsletter|broadcast)$/.test(id)) continue;
      const contact = c.contact || {};
      const phone = W.keyStr(contact.phoneNumber) || (id.endsWith('@c.us') ? id : null);
      out.push({
        id,
        name: c.name || c.formattedTitle || contact.name || contact.pushname || contact.verifiedName || '',
        isGroup: id.endsWith('@g.us'),
        phone: phone ? phone.split('@')[0] : null,
        ts: Number(c.t) || 0,
        archived: Boolean(c.archive),
      });
    } catch (e) { /* one odd chat must not break the list */ }
  }
  return out;
}

function pageFindChatByPhone(digits) {
  const W = window.__wad;
  if (!W || W.v !== 3) throw new Error('WAD_NO_HELPERS');
  const want = `${digits}@c.us`;
  for (const c of W.allChats()) {
    try {
      const id = W.keyStr(c.id);
      const phone = W.keyStr(c.contact && c.contact.phoneNumber);
      if (id === want || phone === want) {
        return { id, name: c.name || c.formattedTitle || digits, isGroup: false };
      }
    } catch (e) { /* ignore */ }
  }
  return null;
}

function pageChatInfo(chatId) {
  const W = window.__wad;
  if (!W || W.v !== 3) throw new Error('WAD_NO_HELPERS');
  const chat = W.findChat(chatId);
  if (!chat) return null;
  return { id: W.keyStr(chat.id), name: chat.name || chat.formattedTitle || '' };
}

/**
 * Reads the chat, scrolling back (loading earlier messages, like scrolling up in the app)
 * until it has covered everything since `sinceSec` – the whole "delete for everyone"
 * window – or reaches the start of the history on this computer, or hits `maxMsgs`.
 *
 * Returns { messages (oldest first), oldest, pages, stop, error }, where stop is:
 *   'window'  everything since sinceSec was covered
 *   'start'   no earlier messages exist on this computer
 *   'cap'     hit maxMsgs / maxPages before reaching sinceSec
 *   'loader'  loading earlier messages failed (see error)
 */
async function pageFetchMessages(chatId, opts) {
  const W = window.__wad;
  if (!W || W.v !== 3) throw new Error('WAD_NO_HELPERS');
  const o = typeof opts === 'number' ? { maxMsgs: opts } : (opts || {});
  const sinceSec = Number(o.sinceSec) || 0;
  const maxMsgs = Number(o.maxMsgs) || 3000;
  const maxPages = Number(o.maxPages) || 300;
  const chat = W.findChat(chatId);
  if (!chat) throw new Error('the configured chat was not found');

  const keep = (m) => m && !m.isNotification && W.keyStr(m.id);
  const byId = new Map();
  let oldest = Infinity; // how far back we have got (any message, notices included)
  const add = (arr) => {
    for (const m of Array.isArray(arr) ? arr : []) {
      if (!m) continue;
      const t = Number(m.t) || 0;
      if (t && t < oldest) oldest = t;
      if (keep(m)) byId.set(W.keyStr(m.id), m);
    }
  };
  const inMemory = () => (chat.msgs && chat.msgs.getModelsArray ? chat.msgs.getModelsArray() : []);
  add(inMemory());

  const loader = W.req('WAWebChatLoadMessages');
  // WhatsApp has changed this call's signature before; try both known forms and remember which works.
  const loadEarlier = async () => {
    const forms = [() => loader.loadEarlierMsgs({ chat }), () => loader.loadEarlierMsgs(chat)];
    const first = window.__wadLoadForm || 0;
    let err = null;
    for (let k = 0; k < forms.length; k++) {
      const idx = (first + k) % forms.length;
      try {
        const r = await forms[idx]();
        window.__wadLoadForm = idx;
        return r;
      } catch (e) { err = e; }
    }
    throw err;
  };

  let pages = 0;
  let stop = null;
  let error = null;
  while (!stop) {
    if (oldest <= sinceSec) { stop = 'window'; break; }
    if (byId.size >= maxMsgs || pages >= maxPages) { stop = 'cap'; break; }
    if (!loader || typeof loader.loadEarlierMsgs !== 'function') {
      stop = 'loader';
      error = 'WhatsApp Web\'s "load earlier messages" function was not found';
      break;
    }
    let more;
    try {
      more = await loadEarlier();
    } catch (e) {
      stop = 'loader';
      error = String((e && e.message) || e || 'unknown error').slice(0, 120);
      break;
    }
    pages++;
    const before = byId.size;
    const reachedBefore = oldest;
    add(Array.isArray(more) ? more : (more && more.messages));
    add(inMemory()); // loaded messages normally land in the chat's own list too
    if (byId.size === before && oldest === reachedBefore) stop = 'start';
  }

  const messages = [...byId.values()]
    .sort((a, b) => (Number(a.t) || 0) - (Number(b.t) || 0))
    .slice(-maxMsgs)
    .map(W.slim);
  return { messages, oldest: Number.isFinite(oldest) ? oldest : 0, pages, stop, error };
}

async function pageCheckRevoke(msgId) {
  const W = window.__wad;
  if (!W || W.v !== 3) throw new Error('WAD_NO_HELPERS');
  const Cap = W.req('WAWebMsgActionCapability');
  if (!Cap || typeof Cap.canSenderRevokeMsg !== 'function') throw new Error('WAD_INCOMPATIBLE: revoke check not found');
  const m = await W.findMsg(msgId);
  if (!m) return { found: false };
  return {
    found: true,
    fromMe: Boolean(m.id && m.id.fromMe),
    type: m.type,
    canRevoke: Boolean(Cap.canSenderRevokeMsg(m)),
  };
}

/** Check + revoke in ONE step: there is no gap in which WhatsApp's answer could change. */
async function pageRevoke(msgId) {
  const W = window.__wad;
  if (!W || W.v !== 3) throw new Error('WAD_NO_HELPERS');
  const m = await W.findMsg(msgId);
  if (!m) return { ok: false, reason: 'message not found' };
  if (!(m.id && m.id.fromMe)) return { ok: false, reason: 'refusing: not your message' };
  if (m.type === 'revoked') return { ok: true, already: true };
  const Cap = W.req('WAWebMsgActionCapability');
  if (!Cap || typeof Cap.canSenderRevokeMsg !== 'function') throw new Error('WAD_INCOMPATIBLE: revoke check not found');
  if (!Cap.canSenderRevokeMsg(m)) return { ok: false, reason: 'WhatsApp no longer allows deleting this for everyone' };
  const CmdMod = W.req('WAWebCmd');
  const Cmd = CmdMod && CmdMod.Cmd;
  if (!Cmd || typeof Cmd.sendRevokeMsgs !== 'function') throw new Error('WAD_INCOMPATIBLE: revoke command not found');

  const C = W.coll();
  let chat = null;
  try { chat = C.Chat.get(m.id.remote) || null; } catch (e) { /* ignore */ }
  if (!chat) chat = W.findChat(W.keyStr(m.id.remote));
  if (!chat) return { ok: false, reason: 'chat for message not found' };

  const cmp = window.WWebJS && window.WWebJS.compareWwebVersions;
  const version = (window.Debug && window.Debug.VERSION) || '2.3000.0';
  const newApi = typeof cmp === 'function' ? cmp(version, '>=', '2.3000.0') : true;
  if (newApi) {
    await Cmd.sendRevokeMsgs(chat, { list: [m], type: 'message' }, { clearMedia: true });
  } else {
    await Cmd.sendRevokeMsgs(chat, [m], { clearMedia: true, type: 'Sender' });
  }
  return { ok: true };
}

async function pageGetType(msgId) {
  const W = window.__wad;
  if (!W || W.v !== 3) throw new Error('WAD_NO_HELPERS');
  const m = await W.findMsg(msgId);
  return m ? String(m.type) : null;
}

/**
 * After "delete for everyone", current WhatsApp Web re-files the message under a new
 * internal record, so a lookup by the old key finds nothing. Search the chat instead:
 * by the message's permanent id (the last part of the key), then by send time.
 */
async function pageVerifyRevoked(chatId, msgId, sentAt) {
  const W = window.__wad;
  if (!W || W.v !== 3) throw new Error('WAD_NO_HELPERS');
  const direct = await W.findMsg(msgId);
  if (direct && direct.type === 'revoked') return { type: 'revoked', via: 'key' };

  const raw = String(msgId).split('_').pop();
  const chat = W.findChat(chatId);
  const list = chat && chat.msgs && chat.msgs.getModelsArray ? chat.msgs.getModelsArray() : [];
  for (const m of list) {
    try {
      if (m && m.id && (m.id.id === raw || W.keyStr(m.id) === msgId)) return { type: String(m.type), via: 'id' };
    } catch (e) { /* ignore */ }
  }
  if (sentAt) {
    for (const m of list) {
      try {
        if (m && m.id && m.id.fromMe && m.type === 'revoked' && Number(m.t) === Number(sentAt)) return { type: 'revoked', via: 'time' };
      } catch (e) { /* ignore */ }
    }
  }
  if (direct) return { type: String(direct.type), via: 'key' };
  return { type: null, via: 'none' };
}

/** Recent text notes you sent in your "Message yourself" chat (used for pause/resume commands). */
function pageOwnNotes(limit) {
  const W = window.__wad;
  if (!W || W.v !== 3) throw new Error('WAD_NO_HELPERS');
  const out = [];
  const seen = new Set();
  for (const id of W.selfIds()) {
    const chat = W.findChat(id);
    if (!chat || seen.has(chat)) continue;
    seen.add(chat);
    const arr = chat.msgs && chat.msgs.getModelsArray ? chat.msgs.getModelsArray() : [];
    for (const m of arr.slice(-limit)) {
      try {
        if (m && m.id && m.id.fromMe && m.type === 'chat' && typeof m.body === 'string') {
          out.push({ id: W.keyStr(m.id), body: m.body.slice(0, 60), t: Number(m.t) || 0 });
        }
      } catch (e) { /* ignore */ }
    }
  }
  return out.sort((a, b) => a.t - b.t);
}

/** Reacts to one of your own notes with an emoji (the script's way of answering you). */
async function pageReact(msgId, emoji) {
  const W = window.__wad;
  if (!W || W.v !== 3) throw new Error('WAD_NO_HELPERS');
  const m = await W.findMsg(msgId);
  const A = W.req('WAWebSendReactionMsgAction');
  if (!m || !A || typeof A.sendReactionToMsg !== 'function') return false;
  await A.sendReactionToMsg(m, emoji);
  return true;
}

/** Our own "new incoming message" listener, independent of the library's event pipeline. */
function pageListen() {
  const W = window.__wad;
  if (!W || W.v !== 3) throw new Error('WAD_NO_HELPERS');
  if (window.__wadListening) return false;
  const C = W.coll();
  C.Msg.on('add', (m) => {
    try {
      if (!m || !m.isNewMsg || !m.id) return;
      if (m.id.fromMe) {
        // A note in your "Message yourself" chat might be a pause/resume command.
        const mine = W.selfIds();
        let chatId = null;
        try { const c = C.Chat.get(m.id.remote); chatId = c && W.keyStr(c.id); } catch (e) { /* ignore */ }
        if ((mine.includes(W.keyStr(m.id.remote)) || mine.includes(chatId)) && typeof window.__wadSelf === 'function') {
          window.__wadSelf();
        }
        return;
      }
      const ids = [W.keyStr(m.id.remote)];
      try {
        const chat = C.Chat.get(m.id.remote);
        if (chat) ids.push(W.keyStr(chat.id));
      } catch (e) { /* ignore */ }
      window.__wadIncoming(ids.filter(Boolean), String(m.type || 'unknown'));
    } catch (e) { /* never break WhatsApp's own event loop */ }
  });
  window.__wadListening = true;
  return true;
}
/* eslint-enable no-undef */

// ---------------------------------------------------------------- node side

function incompatible(e) {
  const t = L.errText(e);
  if (!t.includes('WAD_INCOMPATIBLE')) return e;
  const err = new Error(`WhatsApp Web changed: ${t.replace(/^.*WAD_INCOMPATIBLE:\s*/, '')}`);
  err.code = 'INCOMPATIBLE';
  return err;
}

class WaDirect {
  constructor(getClient) {
    this.getClient = getClient;
    this.exposedOn = null;
  }

  page() {
    const c = this.getClient();
    if (!c || !c.pupPage) throw new Error('WhatsApp page is not available');
    return c.pupPage;
  }

  /** Runs an in-page function, (re)installing helpers after page reloads. */
  async run(fn, ms, label, ...args) {
    const page = this.page();
    const once = () => L.withTimeout(page.evaluate(fn, ...args), ms, label);
    try {
      return await once();
    } catch (e) {
      if (!L.errText(e).includes('WAD_NO_HELPERS')) throw incompatible(e);
      await L.withTimeout(page.evaluate(installHelpers, HELPERS_VERSION), 15000, 'install helpers');
      try { return await once(); } catch (e2) { throw incompatible(e2); }
    }
  }

  health() { return this.run(pageHealth, 20000, 'health check'); }
  listChats() { return this.run(pageListChats, 120000, 'list chats'); }
  findChatByPhone(digits) { return this.run(pageFindChatByPhone, 30000, 'find chat', digits); }
  chatInfo(chatId) { return this.run(pageChatInfo, 30000, 'find chat', chatId); }
  /** opts: { sinceSec, maxMsgs }. Resolves to { messages, oldest, pages, stop, error }. */
  fetchMessages(chatId, opts) { return this.run(pageFetchMessages, 300000, 'read messages', chatId, opts); }
  checkRevoke(msgId) { return this.run(pageCheckRevoke, 30000, 'revoke check', msgId); }
  getType(msgId) { return this.run(pageGetType, 20000, 'verify delete', msgId); }
  ownNotes(limit = 20) { return this.run(pageOwnNotes, 20000, 'read notes to self', limit); }
  react(msgId, emoji) { return this.run(pageReact, 20000, 'react', msgId, emoji); }
  async verifyRevoked(chatId, msgId, sentAt) {
    const r = await this.run(pageVerifyRevoked, 20000, 'verify delete', chatId, msgId, sentAt || 0);
    return r ? r.type : null;
  }

  async revoke(msgId) {
    const r = await this.run(pageRevoke, 45000, 'delete for everyone', msgId);
    if (!r || !r.ok) throw new Error((r && r.reason) || 'delete failed');
    return r;
  }

  /** Registers our own incoming-message listener. Safe to call again after every page reload. */
  async listen(onIncoming, onSelfNote = () => {}) {
    const page = this.page();
    if (this.exposedOn !== page) {
      const expose = async (name, fn) => {
        try { await page.exposeFunction(name, fn); } catch (e) {
          if (!/already exists/i.test(L.errText(e))) throw e;
        }
      };
      await expose('__wadIncoming', (ids, type) => {
        try { onIncoming(Array.isArray(ids) ? ids : [], String(type)); } catch { /* ignore */ }
      });
      await expose('__wadSelf', () => { try { onSelfNote(); } catch { /* ignore */ } });
      this.exposedOn = page;
    }
    return this.run(pageListen, 20000, 'listen for replies');
  }
}

module.exports = {
  WaDirect,
  // exported for tests only
  _page: { installHelpers, pageHealth, pageListChats, pageFindChatByPhone, pageChatInfo, pageFetchMessages, pageCheckRevoke, pageRevoke, pageGetType, pageVerifyRevoked, pageListen, pageOwnNotes, pageReact },
};

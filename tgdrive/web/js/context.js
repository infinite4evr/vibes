// "Show in chat": the messages around a file in its chat — who sent it, what was said before and after,
// replies and neighbouring files — read live from Telegram, in the side panel.
import { $, S, A, api, esc, icon, fmtDate, fmtSize, key, inlineSrc, thumbUrl, bus, extColor } from './core.js';
import { fail } from './ui.js';

let C = null;

export async function showContext(f) {
  bus.emit('flush-note');   // a note still being typed in the details panel is saved first
  C = { f, messages: [], hasOlder: false, hasNewer: false, chat: null };
  S.drawer = 'context';
  const d = $('#drawer');
  d.hidden = false;
  $('#app').classList.add('with-drawer');
  d.innerHTML = `<div class="drawer-head"><h2>In chat</h2><button class="icon-btn" data-ctx="close" aria-label="Close">${icon('close')}</button></div>
    <div class="drawer-body ctx-body"><div class="page-loading"><span class="spin"></span> Reading messages around this file…</div></div>`;
  await load(15, 15, 'center');
}

async function load(before, after, mode, anchor) {
  const f = C.f;
  try {
    const r = await api(A(`/context/${f.chat_id}/${anchor || f.msg_id}?before=${before}&after=${after}`));
    if (!C || C.f !== f) return;
    C.chat = r.chat;
    if (mode === 'center') { C.messages = r.messages; C.hasOlder = r.has_older; C.hasNewer = r.has_newer; }
    else if (mode === 'older') {
      const have = new Set(C.messages.map((m) => m.id));
      C.messages = [...r.messages.filter((m) => !have.has(m.id) && m.id < C.messages[0].id), ...C.messages];
      C.hasOlder = r.has_older;
    } else {
      const have = new Set(C.messages.map((m) => m.id));
      C.messages = [...C.messages, ...r.messages.filter((m) => !have.has(m.id) && m.id > C.messages[C.messages.length - 1].id)];
      C.hasNewer = r.has_newer;
    }
    render(mode);
  } catch (e) {
    if (!C || C.f !== f) return;
    // Earlier or later messages: keep what is already shown and say what went wrong.
    if (mode !== 'center') { fail(e); return; }
    const body = $('.ctx-body');
    if (body) {
      body.innerHTML = `<div class="empty page-error">${icon('info')}<h2>Couldn't read this chat</h2><p>${esc(e.message)}</p>
        <p class="help">Telegram needs to be connected to read the messages around a file.</p><button class="btn" data-ctx="retry">${icon('refresh')}Try again</button></div>`;
    }
  }
}

function fileBubble(file) {
  const img = file.has_thumb || file.inline;
  return `<button class="ctx-file ${img ? 'pic' : ''}" data-ctx-file="${file.chat_id}:${file.msg_id}">
    ${img ? `<span class="ctx-thumb">${file.inline ? `<img class="lqip" src="${inlineSrc(file.inline)}" alt="">` : ''}${file.has_thumb ? `<img class="real" data-src="${thumbUrl(file, 's')}" alt="">` : ''}</span>`
      : `<span class="mini doc" style="--ec:${extColor(file.ext)}">${esc((file.ext || file.kind).slice(0, 4).toUpperCase())}</span>`}
    <span class="ctx-fname"><strong>${esc(file.name)}</strong><small>${fmtSize(file.size)}</small></span></button>`;
}

function render(mode) {
  const body = $('.ctx-body');
  if (!body || !C) return;
  const byId = new Map(C.messages.map((m) => [m.id, m]));
  const chatLink = C.chat?.username ? `https://t.me/${C.chat.username}/${C.f.msg_id}` : null;
  let lastDay = '';
  let lastSender = null;
  const rows = C.messages.map((m) => {
    const day = m.date ? new Date(m.date * 1000).toDateString() : '';
    const sep = day && day !== lastDay ? `<div class="ctx-day">${esc(fmtDate(m.date))}</div>` : '';
    if (sep) lastSender = null;
    lastDay = day;
    const reply = m.reply_to ? byId.get(m.reply_to) : null;
    const showName = !m.out && m.sender && m.sender !== lastSender;
    lastSender = m.sender;
    const time = m.date ? new Date(m.date * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
    return `${sep}<div class="ctx-msg ${m.out ? 'out' : ''} ${m.target ? 'target' : ''}" data-mid="${m.id}">
      ${showName ? `<div class="ctx-from">${esc(m.sender)}</div>` : ''}
      ${m.fwd ? `<div class="ctx-fwd">${icon('send')}Forwarded${m.fwd !== 'Forwarded' ? ` from ${esc(m.fwd)}` : ''}</div>` : ''}
      ${m.reply_to ? `<button class="ctx-reply" data-ctx-jump="${m.reply_to}">${reply ? esc((reply.text || reply.file?.name || reply.media || '').slice(0, 90)) : 'Reply to an earlier message'}</button>` : ''}
      ${m.file ? fileBubble(m.file) : m.media ? `<div class="ctx-media">${icon('info')}${esc(m.media)}</div>` : ''}
      ${m.text ? `<div class="ctx-text">${linkify(m.text)}</div>` : ''}
      <div class="ctx-time">${time}</div></div>`;
  }).join('');
  body.innerHTML = `<div class="ctx-chat">${esc(C.chat?.title || '')}${chatLink ? ` <a class="subtle-link" href="${esc(chatLink)}" target="_blank" rel="noopener">Open in Telegram</a>` : ''}</div>
    ${C.hasOlder ? `<button class="btn sm ghost ctx-more" data-ctx="older">${icon('up')}Earlier messages</button>` : ''}
    <div class="ctx-list">${rows}</div>
    ${C.hasNewer ? `<button class="btn sm ghost ctx-more" data-ctx="newer">${icon('down')}Later messages</button>` : ''}`;
  import('./core.js').then((m) => m.thumbs.observe(body));
  if (mode === 'center') body.querySelector('.ctx-msg.target')?.scrollIntoView({ block: 'center' });
  else if (mode === 'older') body.scrollTop = 0;
  else if (mode === 'newer') body.scrollTop = body.scrollHeight;
}

function linkify(text) {
  return esc(text).replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>').replace(/\n/g, '<br>');
}

document.addEventListener('click', async (e) => {
  if (!C || S.drawer !== 'context') return;
  const b = e.target.closest('[data-ctx]');
  if (b) {
    const a = b.dataset.ctx;
    if (a === 'close') { C = null; S.drawer = null; (await import('./details.js')).renderDrawer(); return; }
    if (a === 'retry') {
      $('.ctx-body').innerHTML = '<div class="page-loading"><span class="spin"></span> Reading messages around this file…</div>';
      load(15, 15, 'center');
    }
    if (a === 'older') load(25, 0, 'older', C.messages[0].id);
    if (a === 'newer') load(0, 25, 'newer', C.messages[C.messages.length - 1].id);
    return;
  }
  const j = e.target.closest('[data-ctx-jump]');
  if (j) {
    const el = $(`.ctx-msg[data-mid="${j.dataset.ctxJump}"]`);
    if (el) { el.scrollIntoView({ block: 'center', behavior: 'smooth' }); el.classList.add('flash'); setTimeout(() => el.classList.remove('flash'), 1400); }
    return;
  }
  const fb = e.target.closest('[data-ctx-file]');
  if (fb) {
    const [c, m] = fb.dataset.ctxFile.split(':').map(Number);
    const files = C.messages.map((x) => x.file).filter(Boolean);
    const f = files.find((x) => x.chat_id === c && x.msg_id === m);
    if (f) { files.forEach((x) => S.byKey.set(key(x), S.byKey.get(key(x)) || x)); (await import('./viewer.js')).openViewer(f, files); }
  }
});
bus.on('route', () => {});
export { fail };

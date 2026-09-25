// Details drawer (single file or a multi-selection).
import { $, S, A, api, esc, icon, key, fmtSize, fmtDate, fmtDur, plural, KIND_NAME, CHAT_KIND_NAME, STREAMABLE, bus, callBridge, bridge, debounce, thumbs, friendlyName, displayName, copiesParam } from './core.js';
import { toast, fail, chatAvatar } from './ui.js';
import {
  selectedFiles, selectedItems, setSelected, thumbHtml, refreshCard, openFile, doDownload, doMove, placeInto, doCopy, doSend,
  doLinks, doDelete, toggleStar, editTags, bulkRename, doOpenLocal, openInTelegram, viewTitle, undoLast,
} from './files.js';
import { mountPreview, stopPreview } from './preview.js';

// The panel slides in and out; its content cross-fades when it switches between details and transfers.
let closeTimer = 0;
let shownKind = null;
export function renderDrawer() {
  const d = $('#drawer');
  clearTimeout(closeTimer);
  $('#transfersBtn').setAttribute('aria-expanded', String(S.drawer === 'transfers'));
  if (!S.drawer) {
    stopPreview();
    shownKind = null;
    if (d.hidden) return undefined;
    d.classList.remove('opening');
    d.classList.add('closing');
    closeTimer = setTimeout(() => {
      d.classList.remove('closing');
      d.hidden = true;
      $('#app').classList.remove('with-drawer');
      d.innerHTML = '';
    }, 190);
    return undefined;
  }
  if (d.hidden || d.classList.contains('closing')) {
    d.classList.remove('closing');
    d.hidden = false;
    d.classList.remove('opening');
    void d.offsetWidth;
    d.classList.add('opening');
    setTimeout(() => d.classList.remove('opening'), 360);
  } else if (shownKind && shownKind !== S.drawer) {
    d.classList.remove('swap');
    void d.offsetWidth;
    d.classList.add('swap');
  }
  $('#app').classList.add('with-drawer');
  if (S.drawer !== 'details') stopPreview();
  shownKind = S.drawer;
  if (S.drawer === 'transfers') return import('./transfers.js').then((m) => m.renderTransfers());
  if (S.drawer === 'details') return renderDetails();
  if (S.drawer === 'context') return undefined;   // context.js owns the panel
  d.innerHTML = '';
  return undefined;
}
export function closeDrawer() { S.drawer = null; renderDrawer(); }

// Clicking a file always shows its details and preview (also when the transfers list was open).
bus.on('open-details', () => { S.drawer = 'details'; renderDrawer(); });
bus.on('selection', () => {
  if (S.drawer === 'details') { if (!S.selected.size) closeDrawer(); else renderDetails(); }
});

const skel = (w) => `<i class="sk-line" style="width:${w}%"></i>`;
function factsSkeleton() {
  return `<div class="d-skel" aria-hidden="true">${skel(70)}${skel(40)}<div class="sk-row">${'<i class="sk-btn"></i>'.repeat(3)}</div>
    ${[60, 45, 70, 50, 65, 40].map((w) => `<div class="sk-fact"><i></i>${skel(w)}</div>`).join('')}</div>`;
}

let detailsReq = 0;
async function renderDetails() {
  const d = $('#drawer');
  const files = selectedFiles();
  if (files.length > 1) {
    stopPreview();
    const bytes = files.reduce((a, f) => a + (f.size || 0), 0);
    const kinds = {};
    files.forEach((f) => { kinds[f.kind] = (kinds[f.kind] || 0) + 1; });
    d.innerHTML = `<div class="drawer-head"><h2>${plural(files.length, 'file')} selected</h2><button class="icon-btn" data-close aria-label="Close">${icon('close')}</button></div>
      <div class="drawer-body"><div class="multi-stack">${files.slice(0, 4).map((f) => `<div class="ms-item">${thumbHtml(f)}</div>`).join('')}</div>
      <p class="multi-note">${fmtSize(bytes)} in total, from ${plural(new Set(files.map((f) => f.chat_id)).size, 'chat')}.<br>${Object.entries(kinds).map(([k, n]) => `${n} ${esc((KIND_NAME[k] || k).toLowerCase())}${n > 1 ? 's' : ''}`).join(', ')}</p>
      <div class="actions">
        <button class="btn primary" data-bulk-d="download">${icon('download')}Download all</button>
        <button class="btn" data-bulk-d="zip">${icon('download')}Download as .zip</button>
        <button class="btn" data-bulk-d="move">${icon('move')}Move to folder</button>
        <button class="btn" data-bulk-d="star">${icon('star')}${files.every((f) => f.starred) ? 'Remove stars' : 'Star all'}</button>
        <button class="btn" data-bulk-d="tags">${icon('tag')}Tags</button>
        <button class="btn" data-bulk-d="rename">${icon('edit')}Rename with a pattern</button>
        <button class="btn" data-bulk-d="copy">${icon('copy')}Save copies to Drive</button>
        <button class="btn" data-bulk-d="send">${icon('send')}Send to chat</button>
        <button class="btn" data-bulk-d="links">${icon('link')}Copy links</button>
        <button class="btn danger" data-bulk-d="delete">${icon('trash')}Delete from Telegram</button></div></div>`;
    thumbs.observe(d);
    shownDetail = null;
    return;
  }
  const f = files[0];
  if (!f) { closeDrawer(); return; }
  const k = key(f);
  S.detail = k;
  const req = ++detailsReq;
  // Same file again (after a star, tag or rename): keep the preview playing, refresh only the facts.
  if (shownDetail !== k || !d.querySelector('.d-info')) {
    d.innerHTML = `<div class="drawer-head"><h2>Details</h2><button class="icon-btn" data-close aria-label="Close">${icon('close')}</button></div>
      <div class="drawer-body"><div class="preview"></div><div class="d-info"><div class="d-title-row"><div class="d-title"><span class="d-name">${esc(displayName(f))}</span></div></div>
      <p class="d-sub">${esc([KIND_NAME[f.kind] || f.kind, fmtSize(f.size), f.duration ? fmtDur(f.duration) : '', fmtDate(f.date)].filter(Boolean).join(' · '))}</p>${factsSkeleton()}</div></div>`;
    shownDetail = k;
    mountPreview($('.preview', d), f, { onOpen: (x) => openFile(x) });
    d.querySelector('.drawer-body').classList.add('fade-in');
  }
  let det;
  try { det = await api(A(`/files/${f.chat_id}/${f.msg_id}`)); } catch (e) {
    if (req === detailsReq) $('.d-info', d).innerHTML = `<p class="orig err">${esc(e.message)}</p><button class="btn" data-one="retry-details">${icon('refresh')}Try again</button>`;
    return;
  }
  if (S.detail !== k || S.drawer !== 'details' || req !== detailsReq) return;
  Object.assign(f, { starred: det.starred, tags: det.tags, name: det.name });
  const chat = S.chatById.get(det.chat_id);
  const facts = [
    ['Type', `${KIND_NAME[det.kind] || det.kind}${det.ext ? ` · .${esc(det.ext)}` : ''}`],
    ['Size', `${fmtSize(det.size)}${det.size > 1024 ? ` <span class="subtle">(${det.size.toLocaleString()} bytes)</span>` : ''}`],
    det.width && det.height ? ['Dimensions', `${det.width} × ${det.height}`] : null,
    det.duration ? ['Duration', fmtDur(det.duration)] : null,
    det.performer || det.audio_title ? ['Track', esc([det.performer, det.audio_title].filter(Boolean).join(' · '))] : null,
    ['Sent', esc(fmtDate(det.date, true))],
    ['Chat', `<button data-go="#chat/${det.chat_id}">${esc(det.chat_title)}</button>${chat ? ` · ${esc(CHAT_KIND_NAME[chat.kind] || '')}` : ''}`],
    det.topic ? ['Topic', esc(det.topic)] : null,
    det.sender_name ? ['From', esc(det.sender_name)] : null,
    det.fwd_from ? ['Forwarded from', esc(det.fwd_from)] : null,
    ['Folder', det.folder_path.length ? `<button data-go="#drive/${esc(det.folder_id)}">${det.folder_path.map((p) => esc(p.name)).join(' / ')}</button>` : 'Not in a folder'],
    det.album > 1 ? ['Album', `<button data-go="#album/${det.chat_id}/${det.grouped_id}">${det.album} files sent together</button>`] : null,
    det.local_path ? ['On this computer', `<button data-local="open">Open</button> · <button data-local="reveal">Show in folder</button>`] : null,
    ['Mime type', esc(det.mime || '')],
  ].filter(Boolean);
  const canPlay = STREAMABLE.has(det.kind);
  const info = $('.d-info', d);
  info.classList.remove('fade-in');
  void info.offsetWidth;
  info.classList.add('fade-in');
  const friendly = friendlyName(det);
  const subjName = det.subject && det.subject !== '_none' ? (S.subjects || []).find((x) => x.id === det.subject)?.name || det.subject : '';
  const tool = (act, ic, label, extra = '') => `<button class="icon-btn" data-one="${act}" title="${esc(label)}" aria-label="${esc(label)}" ${extra}>${icon(ic)}</button>`;
  info.innerHTML = `<div class="d-title-row" id="dTitleRow">
      <button class="d-title" data-rename title="Rename (F2)"><span class="d-name">${esc(friendly || det.name)}</span>${friendly ? `<small class="d-real">${esc(det.name)}</small>` : ''}</button>
      <button class="icon-btn star-btn ${det.starred ? 'on' : ''}" id="starBtn" aria-pressed="${det.starred}" title="${det.starred ? 'Remove star (S)' : 'Star (S)'}">${icon('star')}</button>
      <button class="icon-btn" data-rename title="Rename (F2)" aria-label="Rename">${icon('edit')}</button></div>
    <form class="rename" id="renameForm" hidden><label class="sr-only" for="renameInput">File name</label>
      <input id="renameInput" type="text" value="${esc(det.name)}" maxlength="120">
      <small>Changes the name in TG Drive only · Enter to save · Esc to cancel</small></form>
    ${det.renamed ? `<p class="orig">Original name: ${esc(det.original_name)} · <button type="button" id="resetName">Use original</button></p>` : ''}
    <p class="d-sub">${esc([KIND_NAME[det.kind] || det.kind, fmtSize(det.size), det.duration ? fmtDur(det.duration) : '', fmtDate(det.date)].filter(Boolean).join(' · '))}</p>
    <div class="tag-row">${(det.tags || []).map((t) => `<button class="chip" data-go="#tag/${encodeURIComponent(t)}">${esc(t)}</button>`).join('')}<button class="chip ghost" id="tagsBtn">${icon('tag')}${det.tags?.length ? 'Edit' : 'Add tags'}</button>${subjName ? `<button class="chip subj" data-one="subject" title="Subject (click to change)">${icon('book')}${esc(subjName)}</button>` : ''}</div>
    <div class="quick-acts">
      <button class="btn primary" data-one="${canPlay ? 'play' : 'view'}">${icon(canPlay ? 'play' : 'eye')}${canPlay ? 'Play' : 'Preview'}</button>
      <button class="btn" data-one="download">${icon('download')}Download</button>
      <button class="btn" data-one="open" title="Download if needed and open with the default app">${icon('external')}Open</button></div>
    <div class="d-tools" role="toolbar" aria-label="More actions">
      ${det.tg_link || det.link ? tool('telegram', 'telegram', 'Open in Telegram') : ''}
      ${tool('context', 'chat', 'Show in chat')}
      ${tool('move', 'move', det.folder_id ? 'Move to another folder' : 'Move to folder')}
      ${det.folder_id ? tool('unfile', 'folder', 'Take out of folder') : ''}
      ${det.can_copy ? tool('copy', 'copy', 'Save a copy to Drive') : ''}
      ${det.can_forward ? tool('send', 'send', 'Send to chat') : ''}
      ${det.link ? tool('link', 'link', 'Copy link') : ''}
      ${tool('subject', 'book', subjName ? `Subject: ${subjName}` : 'Set subject')}
      ${tool('related', 'sparkle', 'Find related files')}
      <span class="spacer"></span>
      ${det.can_delete ? tool('delete', 'trash', 'Delete from Telegram', 'data-danger') : ''}</div>
    <dl class="facts">${facts.map(([t, v]) => `<dt>${t}</dt><dd>${v}</dd>`).join('')}</dl>
    ${copiesHtml(det)}
    ${det.caption ? `<div class="caption">${linkify(det.caption)}</div>` : ''}
    <label class="field note-field"><span>${icon('note')}Note <small>synced, searchable with has:note</small></span><textarea id="noteInput" rows="2" maxlength="2000" placeholder="Add a note…">${esc(det.note || '')}</textarea></label>
    ${det.link ? `<div class="link-row"><input type="text" readonly value="${esc(det.link)}" aria-label="Telegram link"><button class="icon-btn" id="copyLink" title="Copy link" aria-label="Copy link">${icon('copy')}</button></div>` : ''}`;
  const rf = $('#renameForm');
  const ri = $('#renameInput');
  const startRename = () => {
    $('#dTitleRow').hidden = true;
    rf.hidden = false;
    ri.focus();
    const dot = ri.value.lastIndexOf('.');
    ri.setSelectionRange(0, dot > 0 ? dot : ri.value.length);
  };
  const stopRename = () => { rf.hidden = true; $('#dTitleRow').hidden = false; ri.value = det.name; };
  info.querySelectorAll('[data-rename]').forEach((b) => b.addEventListener('click', startRename));
  rf.addEventListener('submit', async (e) => { e.preventDefault(); rf.dataset.saving = '1'; try { await renameFile(det, ri.value); } finally { delete rf.dataset.saving; } });
  ri.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); stopRename(); } });
  ri.addEventListener('blur', () => {
    if (rf.dataset.saving) return;
    if (ri.value.trim() && ri.value.trim() !== det.name) renameFile(det, ri.value); else stopRename();
  });
  $('#resetName')?.addEventListener('click', () => renameFile(det, ''));
  $('#copyLink')?.addEventListener('click', () => navigator.clipboard.writeText(det.link).then(() => toast('Link copied'), () => fail(new Error("Couldn't copy to the clipboard."))));
  $('#starBtn').addEventListener('click', async () => { await toggleStar([f]); renderDetails(); });
  $('#tagsBtn').addEventListener('click', async () => { await editTags([f]); renderDetails(); });
  watchTitle(d, friendly || det.name);
  const saveNote = debounce(async () => {
    try {
      await api(A('/files/meta'), { method: 'POST', body: { items: [[f.chat_id, f.msg_id]], note: $('#noteInput')?.value ?? '' } });
      $('#noteInput')?.classList.add('saved');
      setTimeout(() => $('#noteInput')?.classList.remove('saved'), 1200);
    } catch (e) { fail(e); }
  }, 900);
  $('#noteInput').addEventListener('input', saveNote);
  d.querySelector('[data-dupes]')?.addEventListener('click', () => bus.emit('go', '#duplicates'));
  d.querySelectorAll('[data-local]').forEach((b) => b.addEventListener('click', () => api('/api/open', { method: 'POST', body: { path: det.local_path, reveal: b.dataset.local === 'reveal' } }).catch(fail)));
}
let shownDetail = null;

// Every copy of the file (forwarded into other chats, or uploaded again), best first.
function copiesHtml(det) {
  const list = det.copy_list || [];
  if (list.length < 2) return '';
  const hiding = copiesParam() === 'hide';
  return `<section class="d-copies"><div class="d-sec-h">${icon('dupes')}<span>${list.length} copies of this file</span>
      <small>${hiding ? 'Lists show only the first one' : 'Lists show all of them'}</small></div>
    ${list.map((c, i) => `<div class="copy-row ${c.this ? 'this' : ''}">${chatAvatar({ title: c.chat_title || '?' }, 'xs')}
      <span class="grow"><button class="linkish" data-go="#chat/${c.chat_id}" title="Go to this chat">${esc(c.chat_title || 'Chat')}</button>
        <small>${esc(fmtDate(c.date))}${c.starred ? ' · starred' : ''}${c.folder_id ? ' · in a folder' : ''}${i === 0 ? ' · shown in lists' : ''}</small></span>
      ${c.this ? '<span class="pill blue">This one</span>' : `<button class="btn sm ghost" data-copy-open="${c.chat_id}:${c.msg_id}" title="Open this copy">${icon('eye')}</button>`}</div>`).join('')}
    <button class="linkish d-copies-all" data-go="#duplicates">Manage all duplicates…</button></section>`;
}

// The panel header shows the file's name once its title has scrolled out of view.
let titleIO = null;
function watchTitle(d, name) {
  titleIO?.disconnect();
  const h = d.querySelector('.drawer-head h2');
  const row = d.querySelector('#dTitleRow');
  if (!h || !row) return;
  h.dataset.name = name;
  titleIO = new IntersectionObserver(([en]) => {
    const show = !en.isIntersecting && en.boundingClientRect.top < en.rootBounds.top + 10;
    h.classList.toggle('as-name', show);
    h.textContent = show ? h.dataset.name : 'Details';
  }, { root: d.querySelector('.drawer-body'), threshold: 0 });
  titleIO.observe(row);
}
export function startRenameInPanel() {
  const b = document.querySelector('#drawer .d-title[data-rename]');
  if (!b || S.drawer !== 'details') return false;
  b.click();
  return true;
}

function linkify(text) {
  return esc(text).replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>')
    .replace(/(^|\s)@([A-Za-z0-9_]{4,32})/g, '$1<a href="https://t.me/$2" target="_blank" rel="noopener">@$2</a>')
    .replace(/(^|\s)#([\p{L}\p{N}_]{2,40})/gu, '$1<button class="hashtag" data-hashtag="$2">#$2</button>');
}

async function renameFile(det, name) {
  name = name.trim();
  if (name === det.name) return;
  try {
    await api(A(`/files/${det.chat_id}/${det.msg_id}/rename`), { method: 'POST', body: { name } });
    const f = S.byKey.get(key(det));
    if (f) { f.name = name || det.original_name; f.renamed = !!name; refreshCard(f); }
    toast(name ? 'Renamed' : 'Name reset', { action: 'Undo', onAction: undoLast });
    renderDetails();
  } catch (e) { fail(e); }
}

$('#drawer').addEventListener('click', (e) => {
  if (e.target.closest('[data-close]')) {
    if (S.drawer === 'details') setSelected([]);
    closeDrawer();
    return;
  }
  const ht = e.target.closest('[data-hashtag]');
  if (ht) { bus.emit('go', `#search/${encodeURIComponent('#' + ht.dataset.hashtag)}`); return; }
  const one = e.target.closest('[data-one]');
  if (one) {
    const f = selectedFiles()[0];
    if (!f) return;
    const items = [[f.chat_id, f.msg_id]];
    ({
      'retry-details': () => { shownDetail = null; renderDetails(); },
      link: () => (f.link ? navigator.clipboard.writeText(f.link).then(() => toast('Link copied'), () => fail(new Error("Couldn't copy to the clipboard."))) : doLinks([f])),
      play: () => openFile(f), view: () => openFile(f),
      download: () => doDownload(items), open: () => doOpenLocal(f),
      move: () => doMove(items, f.folder_id), unfile: () => placeInto(items, null),
      copy: () => doCopy(items), send: () => doSend(items), delete: () => doDelete(items),
      telegram: () => openInTelegram(f),
      context: () => import('./context.js').then((m) => m.showContext(f)),
      subject: () => import('./actions.js').then((m) => m.setSubject([f]).then(renderDetails)),
      related: () => bus.emit('go', `#search/${encodeURIComponent(f.name.replace(/\.[^.]+$/, '').replace(/[_\-.()]+/g, ' ').trim())}`),
    })[one.dataset.one]?.();
    return;
  }
  const co = e.target.closest('[data-copy-open]');
  if (co) { const [c, m] = co.dataset.copyOpen.split(':').map(Number); bus.emit('open-file-ref', { chat_id: c, msg_id: m }); return; }
  const bulk = e.target.closest('[data-bulk-d]');
  if (bulk) {
    const items = selectedItems();
    const files = selectedFiles();
    ({
      download: () => doDownload(items), zip: () => doDownload(items, { zip: true, name: viewTitle() }),
      move: () => doMove(items), copy: () => doCopy(items), send: () => doSend(items),
      links: () => doLinks(files), delete: () => doDelete(items), star: () => toggleStar(files).then(renderDetails),
      tags: () => editTags(files), rename: () => bulkRename(files),
    })[bulk.dataset.bulkD]?.();
  }
});
export { callBridge, bridge };

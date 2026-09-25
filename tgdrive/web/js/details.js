// Details drawer (single file or a multi-selection).
import { $, S, A, api, esc, icon, key, fmtSize, fmtDate, fmtDur, plural, KIND_NAME, CHAT_KIND_NAME, STREAMABLE, bus, callBridge, bridge, streamUrl, debounce } from './core.js';
import { toast, fail } from './ui.js';
import {
  selectedFiles, selectedItems, setSelected, thumbHtml, refreshCard, openFile, doDownload, doMove, placeInto, doCopy, doSend,
  doLinks, doDelete, toggleStar, editTags, bulkRename, doOpenLocal, openInTelegram, viewTitle, undoLast,
} from './files.js';
import { canPlayInline } from './viewer.js';

export function renderDrawer() {
  const d = $('#drawer');
  d.hidden = !S.drawer;
  $('#app').classList.toggle('with-drawer', !!S.drawer);
  $('#transfersBtn').setAttribute('aria-expanded', String(S.drawer === 'transfers'));
  if (S.drawer === 'transfers') return import('./transfers.js').then((m) => m.renderTransfers());
  if (S.drawer === 'details') return renderDetails();
  d.innerHTML = '';
}
export function closeDrawer() { S.drawer = null; renderDrawer(); }

bus.on('open-details', () => { if (S.drawer !== 'transfers' || S.pinDetails) { S.drawer = 'details'; renderDrawer(); } else renderDrawer(); });
bus.on('selection', () => {
  if (S.drawer === 'details') { if (!S.selected.size) closeDrawer(); else renderDetails(); }
});

async function renderDetails() {
  const d = $('#drawer');
  const files = selectedFiles();
  if (files.length > 1) {
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
    return;
  }
  const f = files[0];
  if (!f) { closeDrawer(); return; }
  const k = key(f);
  S.detail = k;
  d.innerHTML = `<div class="drawer-head"><h2>Details</h2><button class="icon-btn" data-close aria-label="Close">${icon('close')}</button></div>
    <div class="drawer-body"><div class="preview">${previewHtml(f)}</div><p class="orig">Loading…</p></div>`;
  let det;
  try { det = await api(A(`/files/${f.chat_id}/${f.msg_id}`)); } catch (e) { $('.orig', d).textContent = e.message; return; }
  if (S.detail !== k || S.drawer !== 'details') return;
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
    det.duplicates > 0 ? ['Copies', `<button data-dupes="1">${plural(det.duplicates, 'other copy', 'other copies')} in your chats</button>`] : null,
    det.local_path ? ['On this computer', `<button data-local="open">Open</button> · <button data-local="reveal">Show in folder</button>`] : null,
    ['Mime type', esc(det.mime || '')],
  ].filter(Boolean);
  const canPlay = STREAMABLE.has(det.kind);
  $('.drawer-body', d).innerHTML = `<div class="preview">${previewHtml(det, true)}</div>
    <div class="name-row"><form class="rename" id="renameForm"><label class="sr-only" for="renameInput">File name</label>
      <input id="renameInput" type="text" value="${esc(det.name)}" maxlength="120"></form>
      <button class="icon-btn star-btn ${det.starred ? 'on' : ''}" id="starBtn" aria-pressed="${det.starred}" title="${det.starred ? 'Remove star (S)' : 'Star (S)'}">${icon('star')}</button></div>
    <p class="orig">${det.renamed ? `Original name: ${esc(det.original_name)}. <button type="button" id="resetName">Use original</button>` : 'Renaming only changes the name in TG Drive. Press Enter to save.'}</p>
    <div class="tag-row">${(det.tags || []).map((t) => `<button class="chip" data-go="#tag/${encodeURIComponent(t)}">${esc(t)}</button>`).join('')}<button class="chip ghost" id="tagsBtn">${icon('tag')}${det.tags?.length ? 'Edit' : 'Add tags'}</button></div>
    <div class="quick-acts">
      <button class="btn primary" data-one="${canPlay ? 'play' : 'view'}">${icon(canPlay ? 'play' : 'eye')}${canPlay ? 'Play' : 'Preview'}</button>
      <button class="btn" data-one="download">${icon('download')}Download</button>
      <button class="btn" data-one="open" title="Download if needed and open with the default app">${icon('external')}Open</button></div>
    <dl class="facts">${facts.map(([t, v]) => `<dt>${t}</dt><dd>${v}</dd>`).join('')}</dl>
    ${det.caption ? `<div class="caption">${linkify(det.caption)}</div>` : ''}
    <label class="field note-field"><span>${icon('note')}Note <small>synced, searchable with has:note</small></span><textarea id="noteInput" rows="2" maxlength="2000" placeholder="Add a note…">${esc(det.note || '')}</textarea></label>
    ${det.link ? `<div class="link-row"><input type="text" readonly value="${esc(det.link)}" aria-label="Telegram link"><button class="icon-btn" id="copyLink" title="Copy link" aria-label="Copy link">${icon('copy')}</button></div>`
    : '<p class="orig">Messages in private chats and basic groups have no t.me link.</p>'}
    <div class="actions">
      ${det.tg_link || det.link ? `<button class="btn" data-one="telegram">${icon('telegram')}Open in Telegram</button>` : ''}
      <button class="btn" data-one="move">${icon('move')}${det.folder_id ? 'Move to another folder' : 'Move to folder'}</button>
      ${det.folder_id ? `<button class="btn" data-one="unfile">${icon('folder')}Take out of folder</button>` : ''}
      ${det.can_copy ? `<button class="btn" data-one="copy">${icon('copy')}Save a copy to Drive</button>` : ''}
      ${det.can_forward ? `<button class="btn" data-one="send">${icon('send')}Send to chat</button>` : ''}
      <button class="btn" data-one="related">${icon('sparkle')}Find related files</button>
      ${det.can_delete ? `<button class="btn danger" data-one="delete">${icon('trash')}Delete from Telegram</button>` : ''}
    </div>`;
  const rf = $('#renameForm');
  rf.addEventListener('submit', async (e) => { e.preventDefault(); await renameFile(det, $('#renameInput').value); });
  $('#renameInput').addEventListener('blur', () => { if ($('#renameInput').value.trim() && $('#renameInput').value.trim() !== det.name) renameFile(det, $('#renameInput').value); });
  $('#resetName')?.addEventListener('click', () => renameFile(det, ''));
  $('#copyLink')?.addEventListener('click', () => navigator.clipboard.writeText(det.link).then(() => toast('Link copied'), () => fail(new Error("Couldn't copy to the clipboard."))));
  $('#starBtn').addEventListener('click', async () => { await toggleStar([f]); renderDetails(); });
  $('#tagsBtn').addEventListener('click', async () => { await editTags([f]); renderDetails(); });
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
  d.querySelector('.preview [data-lightbox]')?.addEventListener('click', () => openFile(f));
}

function previewHtml(f, live = false) {
  if (live && (f.kind === 'audio' || f.kind === 'voice') && (!bridge.ready || canPlayInline(f))) {
    return `<div class="audio-prev">${thumbHtml(f, 'b')}<audio controls preload="none" src="${streamUrl(f)}"></audio></div>`;
  }
  if (live && ['video', 'round', 'gif'].includes(f.kind)) {
    return `<button data-lightbox aria-label="Play">${thumbHtml(f, 'b')}</button>`;
  }
  return `<button data-lightbox aria-label="Open preview">${thumbHtml(f, 'b')}</button>`;
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
    if (f) { f.name = name || det.original_name; refreshCard(f); }
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
      play: () => openFile(f), view: () => openFile(f),
      download: () => doDownload(items), open: () => doOpenLocal(f),
      move: () => doMove(items, f.folder_id), unfile: () => placeInto(items, null),
      copy: () => doCopy(items), send: () => doSend(items), delete: () => doDelete(items),
      telegram: () => openInTelegram(f),
      related: () => bus.emit('go', `#search/${encodeURIComponent(f.name.replace(/\.[^.]+$/, '').replace(/[_\-.()]+/g, ' ').trim())}`),
    })[one.dataset.one]?.();
    return;
  }
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

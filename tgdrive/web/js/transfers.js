// Transfers panel and uploads.
import { $, S, A, api, esc, icon, fmtSize, fmtEta, plural, bus, bridge, callBridge, qs } from './core.js';
import { toast, fail, confirmDialog, chatPicker, promptDialog, dialog, folderPicker } from './ui.js';

const openWhenDone = new Set();
bus.on('open-when-done', (id) => openWhenDone.add(id));

export function openTransfers() {
  S.drawer = 'transfers';
  import('./details.js').then((m) => m.renderDrawer());
  loadTransfers();
}
bus.on('open-transfers', openTransfers);
bus.on('transfers-changed', () => loadTransfers());

export async function loadTransfers() {
  try {
    const r = await api(A('/transfers'));
    const prev = new Map(S.transfers.map((t) => [t.id, t.status]));
    S.transfers = r.transfers;
    S.tsummary = r.summary;
    for (const t of r.transfers) {
      if (t.status === 'done' && prev.get(t.id) && prev.get(t.id) !== 'done' && openWhenDone.has(t.id)) {
        openWhenDone.delete(t.id);
        api(A(`/transfers/${t.id}/open`), { method: 'POST' }).catch(fail);
      }
    }
    if (S.drawer === 'transfers') renderTransfers();
    updateBadge();
  } catch { /* polling retries */ }
}

export function updateBadge() {
  const active = (S.tsummary?.active || 0) + S.localUploads.length;
  $('#tBadge').hidden = !active;
  $('#tBadge').textContent = active;
  const sp = S.tsummary?.speed;
  $('#transfersBtn').title = active ? `Transfers: ${active} active${sp ? `, ${fmtSize(sp)}/s` : ''}` : 'Transfers';
}

function transferRow(t) {
  const pct = t.size ? Math.min(100, Math.round((t.done / t.size) * 100)) : 0;
  const up = t.direction === 'up';
  const eta = t.speed ? fmtEta((t.size - t.done) / t.speed) : '';
  const words = {
    sending: `Reading into TG Drive, ${pct}%`,
    queued: 'Waiting to start',
    running: `${up ? 'Uploading' : 'Downloading'} ${pct}% · ${fmtSize(t.done)} of ${fmtSize(t.size)}${t.speed ? ` · ${fmtSize(t.speed)}/s` : ''}${eta ? ` · ${eta}` : ''}`,
    paused: `Paused at ${pct}% · ${fmtSize(t.done)} of ${fmtSize(t.size)}`,
    done: up ? `Uploaded · ${fmtSize(t.size)}` : `Downloaded · ${fmtSize(t.size)}`,
    error: `Failed: ${t.error || 'unknown error'}`,
    cancelled: 'Cancelled',
  }[t.status] || t.status;
  const b = (act, ic, label) => `<button class="icon-btn" data-t="${act}" data-id="${t.id}" title="${label}" aria-label="${label}">${icon(ic)}</button>`;
  let acts = '';
  if (t.status === 'running' || t.status === 'queued') acts = b('pause', 'pause', 'Pause') + b('cancel', 'close', 'Cancel');
  else if (t.status === 'paused' || t.status === 'error') acts = b('resume', 'play', t.status === 'error' ? 'Retry' : 'Resume') + b('cancel', 'close', 'Cancel');
  else if (t.status === 'done' && !up) {
    acts = (S.desktop || S.localHost ? b('open', 'external', 'Open') + b('reveal', 'folder', 'Show in folder')
      : `<a class="icon-btn" href="${A(`/transfers/${t.id}/file`)}" download title="Save to this device">${icon('download')}</a>`) + b('remove', 'trash', 'Remove from list');
  } else if (t.status !== 'sending') acts = b('remove', 'trash', 'Remove from list');
  const where = t.status === 'done' && t.path && !up ? `<div class="t-path" title="${esc(t.path)}">${esc(t.path)}</div>` : '';
  return `<div class="t-row ${t.status}"><div class="t-top">${icon(up ? 'upload' : 'download')}<span class="t-name" title="${esc(t.name)}">${esc(t.name)}</span><span class="t-acts">${acts}</span></div>
    ${['running', 'paused', 'sending', 'queued', 'error'].includes(t.status) ? `<div class="bar"><i style="width:${pct}%"></i></div>` : ''}
    <div class="t-sub ${t.status === 'error' ? 'err' : ''}">${esc(words)}</div>${where}</div>`;
}

export function renderTransfers() {
  const d = $('#drawer');
  const rows = [...S.localUploads, ...S.transfers];
  const s = S.tsummary || {};
  const running = S.transfers.some((t) => t.status === 'running' || t.status === 'queued');
  const paused = S.transfers.some((t) => t.status === 'paused');
  const failed = S.transfers.some((t) => t.status === 'error');
  const finished = S.transfers.some((t) => t.status === 'done' || t.status === 'cancelled');
  const eta = s.speed ? fmtEta((s.size - s.done) / s.speed) : '';
  d.innerHTML = `<div class="drawer-head"><h2>Transfers</h2><button class="icon-btn" data-close aria-label="Close">${icon('close')}</button></div>
    ${s.active ? `<div class="t-summary"><div class="bar"><i style="width:${s.size ? Math.round((s.done / s.size) * 100) : 0}%"></i></div>
      <span>${plural(s.active, 'transfer')} · ${fmtSize(s.done)} of ${fmtSize(s.size)}${s.speed ? ` · ${fmtSize(s.speed)}/s` : ''}${eta ? ` · ${eta}` : ''}</span></div>` : ''}
    <div class="t-bulk">${running ? `<button class="btn sm" data-tb="pause">${icon('pause')}Pause all</button>` : ''}${paused ? `<button class="btn sm" data-tb="resume">${icon('play')}Resume all</button>` : ''}
      ${failed ? `<button class="btn sm" data-tb="retry">${icon('refresh')}Retry failed</button>` : ''}${finished ? `<button class="btn sm ghost" data-tb="clear">Clear finished</button>` : ''}
      ${running || paused ? `<button class="btn sm ghost danger" data-tb="cancel">Cancel all</button>` : ''}</div>
    <div class="drawer-body">${rows.length ? rows.map(transferRow).join('') : `<div class="t-empty">${icon('transfers')}<p>Downloads and uploads show up here.</p><p class="subtle">Downloads are saved to <b>${esc(S.status?.download_dir || S.downloadDir || 'your Downloads folder')}</b>. Change it in Settings → Downloads.</p></div>`}</div>`;
}

$('#drawer').addEventListener('click', async (e) => {
  const tb = e.target.closest('[data-tb]');
  if (tb) {
    if (tb.dataset.tb === 'cancel' && !await confirmDialog('Cancel all transfers?', 'Partly downloaded files are deleted.', 'Cancel all', true)) return;
    try { await api(A(`/transfers/bulk/${tb.dataset.tb}`), { method: 'POST' }); loadTransfers(); } catch (err) { fail(err); }
    return;
  }
  const t = e.target.closest('[data-t]');
  if (!t) return;
  const { t: act, id } = t.dataset;
  try {
    if (act === 'remove') await api(A(`/transfers/${id}`), { method: 'DELETE' });
    else await api(A(`/transfers/${id}/${act}`), { method: 'POST' });
    loadTransfers();
  } catch (err) { fail(err); }
});

/* ---------------------------------------------------------------- uploads */
let uploadSeq = 0;
let renderQueued = false;
export function uploadFiles(files, folderId, relPaths = null, dest = {}) {
  const list = [...files].map((file, i) => ({ file, rel: relPaths ? relPaths[i] : (file.webkitRelativePath || '') })).filter((x) => x.file.size > 0);
  if (!list.length) return toast('Empty files can’t be uploaded.', { err: true });
  const where = dest.chatId ? `“${S.chatById.get(dest.chatId)?.title || 'the chat'}”` : folderId ? `“${S.folderById.get(folderId)?.name}”` : 'My Drive';
  toast(list.length === 1 ? `Uploading “${list[0].file.name}” to ${where}` : `Uploading ${list.length} files to ${where}`);
  let running = 0;
  const queue = [...list];
  const pump = () => {
    while (running < 3 && queue.length) {
      const { file, rel } = queue.shift();
      running++;
      sendOne(file, rel, folderId, dest).finally(() => { running--; pump(); });
    }
  };
  pump();
  openTransfers();
}
function sendOne(file, rel, folderId, dest = {}) {
  return new Promise((resolve) => {
    const local = { id: `l${++uploadSeq}`, name: rel || file.name, size: file.size, done: 0, status: 'sending', direction: 'up' };
    S.localUploads.unshift(local);
    const xhr = new XMLHttpRequest();
    xhr.open('PUT', A(`/upload?${qs({ name: file.name, folder_id: folderId, rel, chat_id: dest.chatId, caption: dest.caption })}`));
    xhr.setRequestHeader('X-TGDrive', '1');
    xhr.upload.onprogress = (e) => {
      local.done = e.loaded;
      if (!renderQueued && S.drawer === 'transfers') {
        renderQueued = true;
        requestAnimationFrame(() => { renderQueued = false; if (S.drawer === 'transfers') renderTransfers(); });
      }
    };
    const finish = (err) => {
      S.localUploads = S.localUploads.filter((x) => x !== local);
      if (err) toast(`“${file.name}”: ${err}`, { err: true });
      loadTransfers();
      if (rel.includes('/')) bus.emit('drive-changed');
      resolve();
    };
    xhr.onload = () => {
      let data = null;
      try { data = JSON.parse(xhr.responseText); } catch { /* ignore */ }
      finish(xhr.status >= 400 ? (data?.error || `TG Drive answered ${xhr.status}`) : null);
    };
    xhr.onerror = () => finish("couldn't reach TG Drive");
    xhr.send(file);
  });
}

export async function uploadPaths(paths, folderId, dest = {}) {
  if (!paths?.length) return;
  try {
    const r = await api(A('/upload/paths'), { method: 'POST', body: { paths, folder_id: folderId, chat_id: dest.chatId || null, caption: dest.caption || '' } });
    toast(`Uploading ${plural(r.ids.length, 'file')}${r.skipped.length ? ` (${r.skipped.length} skipped)` : ''}`);
    if (r.skipped.length) toast(r.skipped.slice(0, 3).join('; '), { err: true });
    bus.emit('drive-changed');
    openTransfers();
  } catch (e) { fail(e); }
}

export async function uploadDropped(dt, folderId) {
  // Folders dropped from the file manager: walk them so the structure is kept.
  const entries = [...(dt.items || [])].map((i) => i.webkitGetAsEntry?.()).filter(Boolean);
  if (!entries.some((en) => en.isDirectory)) return uploadFiles(dt.files, folderId);
  const files = [], rels = [];
  const walk = (entry, prefix) => new Promise((resolve) => {
    if (entry.isFile) entry.file((f) => { files.push(f); rels.push(prefix + f.name); resolve(); }, resolve);
    else {
      const reader = entry.createReader();
      const all = [];
      const readMore = () => reader.readEntries(async (batch) => {
        if (!batch.length) { for (const en of all) await walk(en, `${prefix}${entry.name}/`); resolve(); }
        else { all.push(...batch); readMore(); }
      }, resolve);
      readMore();
    }
  });
  for (const en of entries) await walk(en, '');
  uploadFiles(files, folderId, rels);
}

export async function pickUpload(folderId = S.view.type === 'drive' ? S.view.folderId : null) {
  if (bridge.ready) {
    const paths = await callBridge('pickFiles');
    if (paths && paths.length) uploadPaths(paths, folderId);
    return;
  }
  const input = document.createElement('input');
  input.type = 'file';
  input.multiple = true;
  input.onchange = () => uploadFiles(input.files, folderId);
  input.click();
}
export async function pickUploadFolder(folderId = S.view.type === 'drive' ? S.view.folderId : null) {
  if (bridge.ready) {
    const path = await callBridge('pickFolder');
    if (path) uploadPaths([path], folderId);
    return;
  }
  const input = document.createElement('input');
  input.type = 'file';
  input.webkitdirectory = true;
  input.onchange = () => uploadFiles(input.files, folderId);
  input.click();
}

/* Upload into any chat or channel you can post in (not the TG Drive channel), with an optional caption. */
export async function uploadToChat(preset = null) {
  const pick = preset ? { chatId: preset } : await chatPicker({
    title: 'Upload to a chat', okLabel: 'Next',
    filterFn: (c) => c.can_post !== false && c.id !== S.driveChannel,
  });
  if (!pick) return;
  const caption = await promptDialog('Caption', 'Caption sent with each file (optional)', '', 'Choose files…',
    { multiline: true, max: 1024, allowEmpty: true });
  if (caption === null || caption === undefined) return;
  const dest = { chatId: pick.chatId, caption };
  if (bridge.ready) {
    const paths = await callBridge('pickFiles');
    if (paths && paths.length) uploadPaths(paths, null, dest);
    return;
  }
  const input = document.createElement('input');
  input.type = 'file';
  input.multiple = true;
  input.onchange = () => uploadFiles(input.files, null, null, dest);
  input.click();
}

/* --------------------------------------------------------- paste to upload */
// Ctrl+V: files copied in the file manager, or an image (screenshot) on the clipboard, upload into the
// folder you're looking at, after one confirmation.
function destFolder() { return S.view.type === 'drive' && S.folderById.get(S.view.folderId)?.kind !== 'smart' ? S.view.folderId : null; }
function destLabel(fid) { return fid ? `“${S.folderById.get(fid)?.name}”` : 'My Drive'; }

async function confirmPaste(n, what) {
  const fid = destFolder();
  return dialog({
    title: `Upload ${what}?`,
    body: `<p>${esc(n)} from the clipboard will be uploaded to <b>${esc(destLabel(fid))}</b>.</p>`,
    actions: [{ label: 'Cancel' }, { label: 'Choose folder…', onClick: async () => { const r = await folderPicker({ title: 'Upload to', okLabel: 'Upload here', current: fid }); return r ? { fid: r.folderId } : false; } },
      { label: 'Upload', cls: 'primary', submit: true, onClick: () => ({ fid }) }],
  });
}

document.addEventListener('paste', async (e) => {
  const t = e.target;
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
  if (!S.aid || $('#layer').children.length) return;
  const files = [...(e.clipboardData?.files || [])];
  const uris = (e.clipboardData?.getData('text/uri-list') || '').split(/\r?\n/).filter((u) => u.startsWith('file://'));
  if (!files.length && !uris.length) {
    if (bridge.ready) { e.preventDefault(); pasteFromBridge(true); }
    return;
  }
  e.preventDefault();
  if (bridge.ready && uris.length) {
    const paths = uris.map((u) => decodeURIComponent(u.slice(7)));
    const r = await confirmPaste(paths.length === 1 ? `“${paths[0].split('/').pop()}”` : `${paths.length} items`, paths.length === 1 ? 'this file' : `${paths.length} items`);
    if (r) uploadPaths(paths, r.fid);
    return;
  }
  const named = files.map((f) => (f.name && f.name !== 'image.png' ? f : new File([f], `Pasted ${new Date().toISOString().slice(0, 19).replace('T', ' ').replace(/:/g, '.')}.${(f.type.split('/')[1] || 'png').replace('jpeg', 'jpg')}`, { type: f.type })));
  const r = await confirmPaste(named.length === 1 ? `“${named[0].name}”` : `${named.length} files`, named.length === 1 ? 'this file' : `${named.length} files`);
  if (r) uploadFiles(named, r.fid);
});

// The desktop app can read files copied in the file manager (the web page alone can't).
export async function pasteFromBridge(quiet = false) {
  if (!bridge.ready) {
    if (!quiet) toast('Press Ctrl+V in the file list to paste copied files or a screenshot.');
    return;
  }
  const paths = await callBridge('clipboardPaths');
  if (!paths?.length) { if (!quiet) toast('Nothing to paste. Copy files in your file manager first (Ctrl+C).'); return; }
  const r = await confirmPaste(paths.length === 1 ? `“${paths[0].split('/').pop()}”` : `${paths.length} items`, paths.length === 1 ? 'this file' : `${paths.length} items`);
  if (r) uploadPaths(paths, r.fid);
}

/* ------------------------------------------------- "Send to TG Drive" menu */
export async function sendToDialog(paths) {
  if (!paths?.length) return;
  let info = { items: paths.map((p) => ({ path: p, name: p.split('/').pop(), files: 1, bytes: 0 })) };
  try { info = await api(`/api/paths/check?${qs({ paths: JSON.stringify(paths) })}`); } catch { /* sizes are optional */ }
  const items = info.items;
  const files = items.reduce((a, x) => a + x.files, 0);
  const bytes = items.reduce((a, x) => a + x.bytes, 0);
  let fid = destFolder();
  let chat = null;
  const where = () => (chat ? `chat “${S.chatById.get(chat)?.title || 'chat'}”` : destLabel(fid));
  const r = await dialog({
    title: items.length === 1 ? `Upload “${items[0].name}”` : `Upload ${items.length} items`,
    body: `<ul class="send-list">${items.slice(0, 8).map((x) => `<li>${icon(x.dir ? 'folder' : 'document')}<span>${esc(x.name)}</span><small>${x.dir ? `${plural(x.files, 'file')} · ` : ''}${fmtSize(x.bytes)}</small></li>`).join('')}${items.length > 8 ? `<li class="subtle">and ${items.length - 8} more</li>` : ''}</ul>
      <p>${plural(files, 'file')}, ${fmtSize(bytes)}. Folders keep their structure.</p>
      <div class="send-dest"><span>Upload to</span><strong id="sendWhere">${esc(where())}</strong><button class="btn sm" id="sendPickFolder">${icon('folder')}Folder…</button><button class="btn sm" id="sendPickChat">${icon('send')}Chat…</button></div>`,
    actions: [{ label: 'Cancel' }, { label: 'Upload', cls: 'primary', submit: true, onClick: () => ({ fid, chat }) }],
    onOpen: (bd) => {
      bd.querySelector('#sendPickFolder').addEventListener('click', async () => { const p = await folderPicker({ title: 'Upload to', okLabel: 'Choose', current: fid }); if (p) { fid = p.folderId; chat = null; bd.querySelector('#sendWhere').textContent = where(); } });
      bd.querySelector('#sendPickChat').addEventListener('click', async () => { const p = await chatPicker({ title: 'Upload to a chat', okLabel: 'Choose', filterFn: (c) => c.can_post !== false && c.id !== S.driveChannel }); if (p) { chat = p.chatId; bd.querySelector('#sendWhere').textContent = where(); } });
    },
  });
  if (!r) return;
  uploadPaths(paths, r.chat ? null : r.fid, r.chat ? { chatId: r.chat } : {});
}

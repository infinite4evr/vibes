// Transfers panel and uploads.
import { $, S, A, api, esc, icon, fmtSize, fmtEta, plural, bus, bridge, callBridge, qs, debounce } from './core.js';
import { toast, dismissToast, fail, confirmDialog, chatPicker, promptDialog, dialog, folderPicker } from './ui.js';
import { reportOnce } from './report.js';

const openWhenDone = new Set();
bus.on('open-when-done', (id) => openWhenDone.add(id));

export function openTransfers() {
  S.drawer = 'transfers';
  import('./details.js').then((m) => m.renderDrawer());
  loadTransfers();
}
bus.on('open-transfers', openTransfers);
bus.on('transfers-changed', () => loadTransfers());

// Uploads already finished when this window last looked; one that finishes after that refreshes the list, so
// the new file shows up in the folder you're looking at.
let doneUploads = null;
let doneFor = null;   // the account those belong to
const uploadsLanded = debounce(() => bus.emit('drive-changed'), 600);
export async function loadTransfers() {
  try {
    const r = await api(A('/transfers'));
    const prev = new Map(S.transfers.map((t) => [t.id, t.status]));
    S.transfers = r.transfers;
    S.tsummary = r.summary;
    for (const t of r.transfers) {
      if (t.status === 'error' && prev.get(t.id) !== 'error') {
        reportOnce(`${t.kind === 'upload' ? 'Upload' : 'Download'} of “${t.name || ''}” failed: ${t.error || 'unknown error'}`,
          { detail: `Transfer ${t.id}: ${t.kind || ''} ${t.size || ''} bytes`, action: 'Retry', onAction: () => api(A(`/transfers/${t.id}/resume`), { method: 'POST' }).then(loadTransfers).catch(fail) });
      }
      if (t.status === 'done' && prev.get(t.id) && prev.get(t.id) !== 'done' && openWhenDone.has(t.id)) {
        openWhenDone.delete(t.id);
        api(A(`/transfers/${t.id}/open`), { method: 'POST' }).catch(fail);
      }
    }
    if (doneFor !== S.aid) { doneUploads = null; doneFor = S.aid; }
    const done = r.transfers.filter((t) => t.direction === 'up' && t.status === 'done').map((t) => t.id);
    if (doneUploads && done.some((id) => !doneUploads.has(id))) uploadsLanded();
    doneUploads = new Set([...(doneUploads || []), ...done]);
    if (S.drawer === 'transfers') renderTransfers();
    updateBadge();
  } catch { /* polling retries */ }
}

export function updateBadge() {
  const active = (S.tsummary?.active || 0) + S.localUploads.filter((x) => x.status === 'sending').length;
  $('#tBadge').hidden = !active;
  $('#tBadge').textContent = active;
  // A ring around the button fills up as the active transfers progress.
  const btn = $('#transfersBtn');
  let ring = btn.querySelector('.t-ring');
  if (!ring) {
    btn.insertAdjacentHTML('beforeend', '<svg class="t-ring" viewBox="0 0 40 40" aria-hidden="true"><circle cx="20" cy="20" r="17"/><circle class="p" cx="20" cy="20" r="17"/></svg>');
    ring = btn.querySelector('.t-ring');
  }
  const size = S.tsummary?.size || 0;
  const pct = size ? Math.min(1, (S.tsummary.done || 0) / size) : 0;
  btn.classList.toggle('t-active', !!active);
  ring.querySelector('.p').style.strokeDashoffset = String(106.8 * (1 - pct));
  const sp = S.tsummary?.speed;
  $('#transfersBtn').title = active ? `Transfers: ${active} active${sp ? `, ${fmtSize(sp)}/s` : ''}` : 'Transfers';
}

const pctOf = (t) => (t.size ? Math.min(100, Math.round((t.done / t.size) * 100)) : 0);
function rowWords(t) {
  const pct = pctOf(t);
  const up = t.direction === 'up';
  const eta = t.speed ? fmtEta((t.size - t.done) / t.speed) : '';
  return {
    sending: `Sending to TG Drive · ${pct}% · ${fmtSize(t.done)} of ${fmtSize(t.size)}`,
    queued: 'Waiting to start',
    running: `${up ? 'Uploading' : 'Downloading'} ${pct}% · ${fmtSize(t.done)} of ${fmtSize(t.size)}${t.speed ? ` · ${fmtSize(t.speed)}/s` : ''}${eta ? ` · ${eta}` : ''}`,
    paused: `Paused at ${pct}% · ${fmtSize(t.done)} of ${fmtSize(t.size)}`,
    done: up ? `Uploaded · ${fmtSize(t.size)}` : `Downloaded · ${fmtSize(t.size)}`,
    error: `Failed: ${t.error || 'unknown error'}`,
    cancelled: 'Cancelled',
  }[t.status] || t.status;
}

function transferRow(t) {
  const up = t.direction === 'up';
  const local = String(t.id).startsWith('l');   // an upload still being sent from this window
  const b = (act, ic, label) => `<button class="icon-btn" data-t="${act}" data-id="${t.id}" title="${label}" aria-label="${label}">${icon(ic)}</button>`;
  let acts = '';
  if (local) {
    if (t.status === 'sending') acts = b('cancel', 'close', 'Cancel');
    else acts = (t.status === 'error' ? b('resume', 'refresh', 'Retry') : '') + b('remove', 'trash', 'Remove from list');
  } else if (t.status === 'running' || t.status === 'queued') acts = b('pause', 'pause', 'Pause') + b('cancel', 'close', 'Cancel');
  else if (t.status === 'paused' || t.status === 'error') acts = b('resume', t.status === 'error' ? 'refresh' : 'play', t.status === 'error' ? 'Retry' : 'Resume') + b('cancel', 'close', 'Cancel');
  else if (t.status === 'done' && !up) {
    acts = (S.desktop || S.localHost ? b('open', 'external', 'Open') + b('reveal', 'folder', 'Show in folder')
      : `<a class="icon-btn" href="${A(`/transfers/${t.id}/file`)}" download title="Save to this device" aria-label="Save to this device">${icon('download')}</a>`) + b('remove', 'trash', 'Remove from list');
  } else acts = b('remove', 'trash', 'Remove from list');
  const where = t.status === 'done' && t.path && !up ? `<div class="t-path" title="${esc(t.path)}">&lrm;${esc(t.path)}&lrm;</div>` : '';
  return `<div class="t-row ${t.status}" data-tid="${t.id}" data-tstatus="${t.status}"><div class="t-top">${icon(up ? 'upload' : 'download')}<span class="t-name" title="${esc(t.name)}">${esc(t.name)}</span><span class="t-acts">${acts}</span></div>
    ${['running', 'paused', 'sending', 'queued', 'error'].includes(t.status) ? `<div class="bar"><i style="width:${pctOf(t)}%"></i></div>` : ''}
    <div class="t-sub ${t.status === 'error' ? 'err' : ''}">${esc(rowWords(t))}</div>${where}</div>`;
}

function summaryHtml(s) {
  const eta = s.speed ? fmtEta((s.size - s.done) / s.speed) : '';
  return `<div class="bar"><i style="width:${s.size ? Math.round((s.done / s.size) * 100) : 0}%"></i></div>
      <span>${plural(s.active, 'transfer')} · ${fmtSize(s.done)} of ${fmtSize(s.size)}${s.speed ? ` · ${fmtSize(s.speed)}/s` : ''}${eta ? ` · ${eta}` : ''}</span>`;
}

// When only the numbers moved (progress, speed), the rows are updated in place, so the buttons stay put under
// the pointer; the panel is rebuilt only when a transfer starts, ends or changes state.
let shape = '';
export function renderTransfers() {
  const d = $('#drawer');
  const rows = [...S.localUploads, ...S.transfers];
  const s = S.tsummary || {};
  const all = [...S.localUploads, ...S.transfers];
  const running = S.transfers.some((t) => t.status === 'running' || t.status === 'queued');
  const paused = S.transfers.some((t) => t.status === 'paused');
  const failed = S.transfers.some((t) => t.status === 'error');
  const finished = all.some((t) => ['done', 'cancelled'].includes(t.status) || (String(t.id).startsWith('l') && t.status === 'error'));
  const nextShape = JSON.stringify([rows.map((t) => [t.id, t.status, t.path || '']), !!s.active, running, paused, failed, finished]);
  const body = d.querySelector('.t-list');
  if (body && nextShape === shape) {
    for (const t of rows) {
      const el = body.querySelector(`[data-tid="${CSS.escape(String(t.id))}"]`);
      if (!el) continue;
      const bar = el.querySelector('.bar i');
      if (bar) bar.style.width = `${pctOf(t)}%`;
      el.querySelector('.t-sub').textContent = rowWords(t);
    }
    const sum = d.querySelector('.t-summary');
    if (sum && s.active) sum.innerHTML = summaryHtml(s);
    return;
  }
  shape = nextShape;
  const scroll = d.querySelector('.drawer-body')?.scrollTop || 0;
  d.innerHTML = `<div class="drawer-head"><h2>Transfers</h2><button class="icon-btn" data-close aria-label="Close">${icon('close')}</button></div>
    ${s.active ? `<div class="t-summary">${summaryHtml(s)}</div>` : ''}
    <div class="t-bulk">${running ? `<button class="btn sm" data-tb="pause">${icon('pause')}Pause all</button>` : ''}${paused ? `<button class="btn sm" data-tb="resume">${icon('play')}Resume all</button>` : ''}
      ${failed ? `<button class="btn sm" data-tb="retry">${icon('refresh')}Retry failed</button>` : ''}${finished ? `<button class="btn sm ghost" data-tb="clear">Clear finished</button>` : ''}
      ${running || paused ? `<button class="btn sm ghost danger" data-tb="cancel">Cancel all</button>` : ''}</div>
    <div class="drawer-body t-list">${rows.length ? rows.map(transferRow).join('') : `<div class="t-empty">${icon('transfers')}<p>Downloads and uploads show up here.</p><p class="subtle">Downloads are saved to <b>${esc(S.status?.download_dir || S.downloadDir || 'your Downloads folder')}</b>. Change it in Settings → Downloads.</p></div>`}</div>`;
  const b = d.querySelector('.drawer-body');
  if (b) b.scrollTop = scroll;
}

$('#drawer').addEventListener('click', async (e) => {
  const tb = e.target.closest('[data-tb]');
  if (tb) {
    if (tb.dataset.tb === 'cancel' && !await confirmDialog('Cancel all transfers?', 'Partly downloaded files are deleted.', 'Cancel all', true)) return;
    if (tb.dataset.tb === 'clear') S.localUploads = S.localUploads.filter((x) => x.status === 'sending');
    try { await api(A(`/transfers/bulk/${tb.dataset.tb}`), { method: 'POST' }); loadTransfers(); } catch (err) { fail(err); }
    return;
  }
  const t = e.target.closest('[data-t]');
  if (!t) return;
  const { t: act, id } = t.dataset;
  if (id.startsWith('l')) { localAction(act, id); return; }
  try {
    if (act === 'remove') await api(A(`/transfers/${id}`), { method: 'DELETE' });
    else await api(A(`/transfers/${id}/${act}`), { method: 'POST' });
    loadTransfers();
  } catch (err) { fail(err); }
});

/* ---------------------------------------------------------------- uploads */
// Files picked or dropped in this window are sent to TG Drive's service first (a row "Sending to TG Drive"),
// which then uploads them to Telegram (a normal transfer row). Sending can be cancelled; one that failed
// stays in the list with Retry.
let uploadSeq = 0;
let renderQueued = false;
const sendQueue = [];
let sending = 0;
function paint() {
  if (renderQueued || S.drawer !== 'transfers') { updateBadge(); return; }
  renderQueued = true;
  requestAnimationFrame(() => { renderQueued = false; if (S.drawer === 'transfers') renderTransfers(); updateBadge(); });
}
export function uploadFiles(files, folderId, relPaths = null, dest = {}) {
  const all = [...files].map((file, i) => ({ file, rel: relPaths ? relPaths[i] : (file.webkitRelativePath || '') }));
  const list = all.filter((x) => x.file.size > 0);
  const empty = all.length - list.length;
  if (!list.length) return toast(all.length === 1 ? 'That file is empty; Telegram can\u2019t store empty files.' : 'Those files are empty; Telegram can\u2019t store empty files.', { err: true });
  const where = dest.chatId ? `“${S.chatById.get(dest.chatId)?.title || 'the chat'}”` : folderId ? `“${S.folderById.get(folderId)?.name}”` : 'My Drive';
  toast(`${list.length === 1 ? `Uploading “${list[0].file.name}”` : `Uploading ${list.length} files`} to ${where}${empty ? ` (${plural(empty, 'empty file')} skipped)` : ''}`);
  for (const { file, rel } of list) {
    const local = { id: `l${++uploadSeq}`, name: rel || file.name, size: file.size, done: 0, status: 'sending', direction: 'up', file, rel, folderId, dest, xhr: null };
    S.localUploads.push(local);
    sendQueue.push(local);
  }
  pump();
  openTransfers();
}
function pump() {
  while (sending < 3 && sendQueue.length) {
    const local = sendQueue.shift();
    if (local.status !== 'sending') continue;   // cancelled while waiting
    sending++;
    sendOne(local).finally(() => { sending--; pump(); });
  }
  paint();
}
function sendOne(local) {
  return new Promise((resolve) => {
    const { file, rel, folderId, dest } = local;
    const xhr = new XMLHttpRequest();
    local.xhr = xhr;
    xhr.open('PUT', A(`/upload?${qs({ name: file.name, folder_id: folderId, rel, chat_id: dest.chatId, caption: dest.caption })}`));
    xhr.setRequestHeader('X-TGDrive', '1');
    xhr.upload.onprogress = (e) => { local.done = e.loaded; paint(); };
    const finish = (err) => {
      local.xhr = null;
      if (local.status === 'cancelled') { S.localUploads = S.localUploads.filter((x) => x !== local); paint(); resolve(); return; }
      if (err) {
        local.status = 'error';
        local.error = err;
        toast(`“${file.name}” couldn't be uploaded: ${err}`, { err: true });
      } else S.localUploads = S.localUploads.filter((x) => x !== local);
      loadTransfers();
      if (!err && rel.includes('/')) bus.emit('drive-changed');
      paint();
      resolve();
    };
    xhr.onload = () => {
      let data = null;
      try { data = JSON.parse(xhr.responseText); } catch { /* ignore */ }
      finish(xhr.status >= 400 ? (data?.error || `TG Drive answered ${xhr.status}`) : null);
    };
    xhr.onerror = () => finish("couldn't reach TG Drive");
    xhr.onabort = () => finish('cancelled');
    xhr.send(file);
  });
}
function localAction(act, id) {
  const local = S.localUploads.find((x) => x.id === id);
  if (!local) return;
  if (act === 'cancel') {
    local.status = 'cancelled';
    if (local.xhr) local.xhr.abort();
    else { S.localUploads = S.localUploads.filter((x) => x !== local); paint(); }
    toast(`Upload of “${local.file.name}” cancelled`);
  } else if (act === 'resume') {
    Object.assign(local, { status: 'sending', done: 0, error: null });
    sendQueue.push(local);
    pump();
  } else if (act === 'remove') {
    S.localUploads = S.localUploads.filter((x) => x !== local);
    paint();
  }
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
  let unreadable = 0;
  // Reading a big folder takes a moment: say so, and count up, until the uploads start.
  const first = entries.find((en) => en.isDirectory);
  const note = toast(`Reading “${first.name}”…`, { ms: 600000 });
  const noteText = note.querySelector('span:not(.toast-ic)');
  let lastPaint = 0;
  const found = () => {
    if (Date.now() - lastPaint < 150) return;
    lastPaint = Date.now();
    if (noteText) noteText.textContent = `Reading “${first.name}”… ${plural(files.length, 'file')} found`;
  };
  const walk = (entry, prefix) => new Promise((resolve) => {
    if (entry.isFile) entry.file((f) => { files.push(f); rels.push(prefix + f.name); found(); resolve(); }, () => { unreadable++; resolve(); });
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
  dismissToast(note);
  if (unreadable) toast(`${plural(unreadable, 'file')} couldn't be read and won't be uploaded.`, { err: true });
  if (!files.length) { toast('Nothing to upload: the folder is empty.', { err: true }); return; }
  uploadFiles(files, folderId, rels);
}

export async function pickUpload(folderId = destFolder()) {
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
export async function pickUploadFolder(folderId = destFolder()) {
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
    actions: [{ label: 'Cancel' }, { label: 'Choose folder…', onClick: async () => { const r = await folderPicker({ title: 'Upload to', okLabel: 'Upload here', current: fid, forFiles: true }); return r ? { fid: r.folderId } : false; } },
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
      bd.querySelector('#sendPickFolder').addEventListener('click', async () => { const p = await folderPicker({ title: 'Upload to', okLabel: 'Choose', current: fid, forFiles: true }); if (p) { fid = p.folderId; chat = null; bd.querySelector('#sendWhere').textContent = where(); } });
      bd.querySelector('#sendPickChat').addEventListener('click', async () => { const p = await chatPicker({ title: 'Upload to a chat', okLabel: 'Choose', filterFn: (c) => c.can_post !== false && c.id !== S.driveChannel }); if (p) { chat = p.chatId; bd.querySelector('#sendWhere').textContent = where(); } });
    },
  });
  if (!r) return;
  uploadPaths(paths, r.chat ? null : r.fid, r.chat ? { chatId: r.chat } : {});
}

// Folder sync: keep a folder on this computer and a TG Drive folder the same, both ways.
import { $, S, A, api, esc, icon, fmtSize, fmtNum, relTime, plural, bridge, callBridge, bus } from './core.js';
import { toast, fail, confirmDialog, dialog, folderPicker, promptDialog } from './ui.js';

const STATE = {
  'needs approval': ['blue', 'Check and approve'], preview: ['blue', 'Preview'], waiting: ['grey', 'Waiting'],
  syncing: ['blue', 'Syncing'], 'up to date': ['ok', 'Up to date'], stopped: ['red', 'Stopped'], error: ['red', 'Problem'],
};

function planHtml(p) {
  if (!p) return '';
  const row = (n, ic, label, extra = '') => (n ? `<li>${icon(ic)}<span>${label}</span><strong>${fmtNum(n)}</strong>${extra}</li>` : '');
  const list = [
    row(p.upload, 'upload', 'to upload', p.upload_bytes ? `<small>${fmtSize(p.upload_bytes)}</small>` : ''),
    row(p.download, 'download', 'to download', p.download_bytes ? `<small>${fmtSize(p.download_bytes)}</small>` : ''),
    row(p.conflict, 'dupes', 'changed on both sides (both versions kept)'),
    row(p.unfile, 'folder', 'deleted on this computer → taken out of the TG Drive folder'),
    row(p.trash, 'trash', 'removed in TG Drive → moved to .tgdrive-trash here'),
    row(p.mkdir_local + p.mkdir_remote, 'folderPlus', 'folders to create'),
    row(p.same, 'check', 'already the same'),
    row(p.busy, 'transfers', 'waiting: still transferring, or still being written on this computer'),
  ].join('');
  return list ? `<ul class="plan">${list}</ul>` : '<p class="help">Nothing to do: both sides are the same.</p>';
}

export async function renderSyncPage() {
  const page = $('#pageView');
  page.innerHTML = `<div class="page-head"><div><h1>Folder sync</h1><p>Keep folders on this computer and TG Drive folders the same, both ways. New and changed files upload and download automatically; nothing is ever deleted outright.</p></div>
    <div class="page-right"><button class="btn primary" data-sync-add>${icon('plus')}Sync a folder</button></div></div><div id="syncList"><div class="page-loading">Loading…</div></div>`;
  await refresh();
  clearTimeout(timer);
  timer = setTimeout(tick, 30000);
}

async function refresh() {
  const el = $('#syncList');
  if (!el) return;
  let r;
  try { r = await api(A('/sync')); } catch (e) { fail(e); return; }
  if (!r.pairs.length) {
    el.innerHTML = `<div class="empty sync-empty">${icon('sync')}<h2>No synced folders yet</h2><p>Pick a folder on this computer and a TG Drive folder. TG Drive shows what it will do and waits for your OK before the first sync.</p>
      <button class="btn primary" data-sync-add>${icon('plus')}Sync a folder</button>
      <p class="help">Good to know: syncing needs TG Drive running. Deleting a file on this computer only takes it out of the TG Drive folder (the message stays in Telegram unless you change that in Settings → Folder sync). Files removed in TG Drive go to <code>.tgdrive-trash</code> inside the synced folder.</p></div>`;
    return;
  }
  el.innerHTML = r.pairs.map((p) => {
    const [cls, label] = STATE[p.state] || ['grey', p.state || 'Waiting'];
    const path = p.folder_path.map((x) => x.name).join(' / ') || 'My Drive';
    return `<section class="panel sync-pair" data-pid="${p.id}">
      <div class="sp-top"><div class="sp-ends"><span class="sp-end">${icon('disk')}<code title="${esc(p.local_path)}">&lrm;${esc(p.local_path)}&lrm;</code></span><span class="sp-arrow">${icon('sync')}</span>
        <span class="sp-end">${icon('folder')}<button class="linkish" data-go="#drive/${esc(p.folder_id)}">${esc(path)}</button></span></div>
        <span class="pill ${cls}">${esc(label)}</span></div>
      <div class="sp-meta">${plural(p.files, 'file')} in sync${p.pending ? ` · ${plural(p.pending, 'transfer')} in progress` : ''}${p.last_run ? ` · checked ${relTime(p.last_run)}` : ''}${p.enabled ? '' : ' · paused'}</div>
      ${p.error ? `<p class="warn">${esc(p.error)}</p>` : ''}
      ${!p.approved ? `<div class="sp-plan"><strong>The first sync will do this:</strong>${planHtml(p.plan || p.stats)}</div>` : ''}
      <div class="btn-row">
        ${!p.approved ? `<button class="btn primary" data-sync="approve">${icon('check')}Approve and start</button><button class="btn" data-sync="preview">${icon('refresh')}Check again</button>`
          : `<button class="btn" data-sync="run">${icon('refresh')}Sync now</button><button class="btn" data-sync="enable" data-on="${p.enabled ? 0 : 1}">${icon(p.enabled ? 'pause' : 'play')}${p.enabled ? 'Pause' : 'Resume'}</button><button class="btn ghost" data-sync="preview">${icon('eye')}What would change?</button>`}
        <button class="btn ghost" data-sync="open">${icon('external')}Open folder</button>
        <span class="spacer"></span><button class="btn ghost danger" data-sync="remove">${icon('trash')}Stop syncing</button></div>
      <div class="sp-preview"></div></section>`;
  }).join('');
}

export async function addPairDialog(folderId = null) {
  let local = '';
  let fid = folderId;
  const fname = () => (fid ? S.folderById.get(fid)?.name || 'folder' : 'Choose a TG Drive folder');
  const r = await dialog({
    title: 'Sync a folder',
    body: `<p>Everything in the folder on this computer and the TG Drive folder (including subfolders) is kept the same, in both directions.</p>
      <label class="field"><span>Folder on this computer</span><div class="path-pick"><input id="syncLocal" placeholder="/home/you/Documents/Notes">${bridge.ready ? `<button class="btn" id="syncPickLocal">${icon('folder')}Choose…</button>` : ''}</div></label>
      <div class="field"><span>TG Drive folder</span><div class="pair1"><button class="btn" id="syncPickDrive">${icon('folder')}<span>${esc(fname())}</span></button><button class="btn ghost" id="syncNewDrive">${icon('folderPlus')}New folder</button></div></div>
      <p class="help">Nothing happens until you've seen what the first sync will do and approved it.</p>`,
    actions: [{ label: 'Cancel' }, { label: 'Next', cls: 'primary', submit: true, onClick: (bd) => { local = bd.querySelector('#syncLocal').value.trim(); if (!local || !fid) { toast('Choose both folders.', { err: true }); return false; } return { local, fid }; } }],
    onOpen: (bd) => {
      bd.querySelector('#syncPickLocal')?.addEventListener('click', async (e) => { e.preventDefault(); const p = await callBridge('pickFolder'); if (p) bd.querySelector('#syncLocal').value = p; });
      bd.querySelector('#syncPickDrive').addEventListener('click', async (e) => {
        e.preventDefault();
        const p = await folderPicker({ title: 'TG Drive folder to sync', okLabel: 'Choose', current: fid, allowNone: false });
        if (p?.folderId) { fid = p.folderId; bd.querySelector('#syncPickDrive span').textContent = fname(); }
      });
      bd.querySelector('#syncNewDrive').addEventListener('click', async (e) => {
        e.preventDefault();
        const guess = (bd.querySelector('#syncLocal').value.trim().split('/').filter(Boolean).pop()) || '';
        const name = await promptDialog('New TG Drive folder', 'Name', guess, 'Create');
        if (!name) return;
        try {
          const f = await api(A('/folders'), { method: 'POST', body: { name } });
          const { loadFolders } = await import('./sidebar.js');
          await loadFolders();
          fid = f.id;
          bd.querySelector('#syncPickDrive span').textContent = fname();
        } catch (err) { fail(err); }
      });
    },
  });
  if (!r) return;
  try {
    toast('Comparing both folders…');
    await api(A('/sync'), { method: 'POST', body: { local_path: r.local, folder_id: r.fid } });
    bus.emit('go', '#sync');
    setTimeout(refresh, 300);
  } catch (e) { fail(e); }
}

document.addEventListener('click', async (e) => {
  if (e.target.closest('[data-sync-add]')) { addPairDialog(); return; }
  const b = e.target.closest('[data-sync]');
  if (!b) return;
  const pid = b.closest('[data-pid]')?.dataset.pid;
  if (!pid) return;
  const act = b.dataset.sync;
  try {
    if (act === 'remove') {
      if (!await confirmDialog('Stop syncing this folder?', 'Both folders stay as they are; they just stop being kept the same.', 'Stop syncing', true)) return;
      await api(A(`/sync/${pid}`), { method: 'DELETE' });
    } else if (act === 'preview') {
      b.disabled = true;
      const plan = await api(A(`/sync/${pid}/preview`), { method: 'POST' });
      const box = b.closest('.sync-pair').querySelector('.sp-preview');
      box.innerHTML = plan.error ? `<p class="warn">${esc(plan.error)}</p>` : `<strong>If it synced now:</strong>${planHtml(plan)}`;
      b.disabled = false;
      return;
    } else if (act === 'enable') await api(A(`/sync/${pid}/enable`), { method: 'POST', body: { on: b.dataset.on === '1' } });
    else if (act === 'run') {
      b.disabled = true;
      const res = await api(A(`/sync/${pid}/run`), { method: 'POST' });
      toast(res.error ? res.error : `Synced: ${res.upload || 0} up, ${res.download || 0} down`, { err: !!res.error });
      bus.emit('transfers-changed');
    } else await api(A(`/sync/${pid}/${act}`), { method: 'POST' });
    if (act === 'approve') toast('Syncing started. Transfers show in the Transfers panel.');
  } catch (err) { fail(err); }
  refresh();
});
let timer = 0;
// The page follows the pairs' state as the server pushes it (see app.js, 'sync-changed'); a slow timer is
// only a safety net.
function tick() {
  clearTimeout(timer);
  if (S.view.type !== 'sync' || !$('#syncList')) return;
  if (!document.querySelector('.sp-preview:not(:empty)')) refresh();
  timer = setTimeout(tick, 30000);
}
bus.on('sync-changed', () => { if (S.view.type === 'sync' && $('#syncList') && !document.querySelector('.sp-preview:not(:empty)')) refresh(); });

// Folder actions.
import { S, A, api, esc, icon, plural, bus, M, qs } from './core.js';
import { menu, toast, fail, confirmDialog, promptDialog, folderPicker, descendantIds, dialog } from './ui.js';
import { undoLast } from './files.js';

export const COLORS = ['', 'red', 'orange', 'yellow', 'green', 'teal', 'blue', 'purple', 'pink', 'grey'];

export async function newFolder(parent = S.view.type === 'drive' ? S.view.folderId : null) {
  const name = await promptDialog(parent ? `New folder in “${S.folderById.get(parent)?.name}”` : 'New folder', 'Folder name', '', 'Create');
  if (!name) return null;
  try {
    const f = await api(A('/folders'), { method: 'POST', body: { name, parent_id: parent } });
    if (parent) S.openFolders.add(parent);
    toast(`Created “${name}”`, { action: 'Undo', onAction: undoLast });
    bus.emit('drive-changed');
    return f;
  } catch (e) { fail(e); return null; }
}

async function pickColor(f) {
  const c = await dialog({
    title: `Colour for “${f.name}”`,
    body: `<div class="swatches">${COLORS.map((c) => `<button class="swatch ${f.color === c || (!f.color && !c) ? 'on' : ''}" data-c="${c}" style="--sw:${c ? `var(--fc-${c})` : 'var(--folder)'}" aria-label="${c || 'Default'}"></button>`).join('')}</div>`,
    actions: [{ label: 'Cancel' }],
    onOpen: (bd, done) => bd.addEventListener('click', (e) => { const b = e.target.closest('[data-c]'); if (b) done({ color: b.dataset.c }); }),
  });
  if (!c) return;
  await api(A(`/folders/${f.id}`), { method: 'PATCH', body: { color: c.color } }).catch(fail);
  bus.emit('drive-changed');
}

export function folderMenu(anchor, id) {
  const f = S.folderById.get(id);
  if (!f) return;
  menu(anchor, [
    { label: 'Open', icon: 'folder', onClick: () => bus.emit('go', `#drive/${id}`) },
    { label: 'New subfolder', icon: 'folderPlus', onClick: () => newFolder(id) },
    { label: 'Search in this folder', icon: 'search', onClick: () => bus.emit('scope-search', { label: f.name, params: { folder_id: id, folder_tree: 1 } }) },
    '-',
    {
      label: 'Rename', icon: 'edit', onClick: async () => {
        const name = await promptDialog('Rename folder', 'Folder name', f.name, 'Rename');
        if (!name) return;
        try { await api(A(`/folders/${id}`), { method: 'PATCH', body: { name } }); toast('Renamed', { action: 'Undo', onAction: undoLast }); bus.emit('drive-changed'); } catch (e) { fail(e); }
      },
    },
    { label: 'Colour…', icon: 'sparkle', onClick: () => pickColor(f) },
    {
      label: 'Description…', icon: 'note', onClick: async () => {
        const d = await promptDialog('Folder description', 'Shown in the folder header', f.description || '', 'Save', { multiline: true, allowEmpty: true, max: 500 });
        if (d === null || d === undefined) return;
        await api(A(`/folders/${id}`), { method: 'PATCH', body: { description: d } }).catch(fail);
        bus.emit('drive-changed');
      },
    },
    {
      label: 'Move to…', icon: 'move', onClick: async () => {
        const r = await folderPicker({ title: `Move “${f.name}”`, okLabel: 'Move here', exclude: new Set([id, ...descendantIds(id)]), current: f.parent_id });
        if (!r) return;
        try { await api(A(`/folders/${id}`), { method: 'PATCH', body: { parent_id: r.folderId } }); toast('Folder moved', { action: 'Undo', onAction: undoLast }); bus.emit('drive-changed'); } catch (e) { fail(e); }
      },
    },
    '-',
    { label: 'Download folder', icon: 'download', onClick: () => downloadFolder(f, false) },
    { label: 'Download as .zip', icon: 'download', onClick: () => downloadFolder(f, true) },
    { label: 'Playlist for VLC / mpv', icon: 'play', onClick: () => { window.location.href = M(`/playlist.m3u?${qs({ folder_id: id, folder_tree: 1 })}`); } },
    '-',
    {
      label: 'Delete folder', icon: 'trash', danger: true, onClick: async () => {
        const subs = descendantIds(id).size;
        const ok = await confirmDialog(`Delete “${f.name}”?`,
          `${subs ? `Its ${plural(subs, 'subfolder')} go too. ` : ''}Files inside stay in Telegram and simply leave the folder. You can undo this.`, 'Delete folder', true);
        if (!ok) return;
        try {
          await api(A(`/folders/${id}`), { method: 'DELETE' });
          toast('Folder deleted', { action: 'Undo', onAction: undoLast });
          if (S.view.type === 'drive' && (S.view.folderId === id || descendantIds(id).has(S.view.folderId))) bus.emit('go', f.parent_id ? `#drive/${f.parent_id}` : '#drive');
          bus.emit('drive-changed');
        } catch (e) { fail(e); }
      },
    },
  ]);
}

export async function downloadFolder(f, zip) {
  try {
    const r = await api(A(`/folders/${f.id}/download`), { method: 'POST', body: { zip } });
    toast(`${zip ? 'Zipping' : 'Downloading'} “${f.name}” (${plural(r.ids.length, 'file')})`, { action: 'Show', onAction: () => bus.emit('open-transfers') });
    bus.emit('transfers-changed');
  } catch (e) { fail(e); }
}
export { icon, esc };

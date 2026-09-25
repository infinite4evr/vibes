// File actions (download, move, star, tags, rename, send, delete …) and the file context menu.
import { S, A, api, bus, bridge, callBridge, plural, STREAMABLE } from './core.js';
import { toast, fail, confirmDialog, promptDialog, folderPicker, chatPicker, tagsDialog, dialog, menu } from './ui.js';
import { refreshCard, setSelected, reload, removeFromList, viewTitle, selectedFiles } from './files.js';

export async function openFile(f) {
  const m = await import('./viewer.js');
  m.openViewer(f);
}

export async function doDownload(items, opts = {}) {
  if (!items.length) return;
  try {
    const r = await api(A('/transfers/download'), { method: 'POST', body: { items, ...opts } });
    const n = r.ids.length;
    toast(opts.zip ? `Downloading ${plural(n, 'file')} into a .zip` : n === 1 ? 'Download started' : `${n} downloads started`, {
      action: 'Show', onAction: () => bus.emit('open-transfers'),
    });
    bus.emit('transfers-changed');
  } catch (e) { fail(e); }
}
export async function doOpenLocal(f) {
  // Download (if needed) and open with the default app.
  try {
    const det = await api(A(`/files/${f.chat_id}/${f.msg_id}`));
    if (det.local_path) { await api('/api/open', { method: 'POST', body: { path: det.local_path } }); return; }
    const r = await api(A('/transfers/download'), { method: 'POST', body: { items: [[f.chat_id, f.msg_id]] } });
    toast(`Downloading “${f.name}” — it opens when ready`);
    bus.emit('open-when-done', r.ids[0]);
    bus.emit('transfers-changed');
  } catch (e) { fail(e); }
}
export async function doMove(items, current) {
  const r = await folderPicker({ title: items.length === 1 ? 'Move to folder' : `Move ${items.length} files to folder`, okLabel: 'Move here', current });
  if (!r) return;
  await placeInto(items, r.folderId);
}
export async function undoLast() {
  try {
    const r = await api(A('/drive/undo'), { method: 'POST' });
    toast(`Undone: ${r.undone}`);
    bus.emit('drive-changed');
  } catch (e) { fail(e); }
}
export async function placeInto(items, folderId) {
  try {
    await api(A('/files/place'), { method: 'POST', body: { items, folder_id: folderId } });
    const where = folderId ? `“${S.folderById.get(folderId)?.name || 'folder'}”` : 'My Drive';
    toast(items.length === 1 ? `Moved to ${where}` : `Moved ${items.length} files to ${where}`, { action: 'Undo', onAction: undoLast });
    bus.emit('drive-changed');
  } catch (e) { fail(e); }
}
export async function doCopy(items) {
  const r = await folderPicker({ title: 'Save a copy to Drive', okLabel: 'Save copy', current: S.view.type === 'drive' ? S.view.folderId : null });
  if (!r) return;
  try {
    toast('Saving copies…');
    const res = await api(A('/files/copy'), { method: 'POST', body: { items, folder_id: r.folderId } });
    if (res.copied.length) toast(res.copied.length === 1 ? 'Saved a copy to Drive' : `Saved ${res.copied.length} copies to Drive`);
    if (res.failed.length) toast(`${res.failed.length} couldn't be copied: ${res.failed[0]}`, { err: true });
    bus.emit('drive-changed');
  } catch (e) { fail(e); }
}
export async function doSend(items) {
  const r = await chatPicker({ title: items.length === 1 ? 'Send to chat' : `Send ${items.length} files to chat`, okLabel: 'Send' });
  if (!r) return;
  const mode = await dialog({
    title: 'How should they be sent?',
    body: '<p>A copy looks like you sent it. Forwarding shows where it came from.</p>',
    actions: [{ label: 'Cancel' }, { label: 'Forward', onClick: () => 'forward' }, { label: 'Send as copy', cls: 'primary', submit: true, onClick: () => 'copy' }],
  });
  if (!mode) return;
  try {
    const res = await api(A('/files/send'), { method: 'POST', body: { items, chat_id: r.chatId, mode } });
    if (res.sent) toast(`Sent ${plural(res.sent, 'file')} to ${S.chatById.get(r.chatId)?.title || 'the chat'}`);
    if (res.failed.length) toast(res.failed[0], { err: true });
  } catch (e) { fail(e); }
}
export async function doLinks(files) {
  const links = files.map((f) => f.link).filter(Boolean);
  if (!links.length) return toast('Private chats and basic groups have no t.me links.', { err: true });
  try {
    await navigator.clipboard.writeText(links.join('\n'));
    const missing = files.length - links.length;
    toast(`Copied ${plural(links.length, 'link')}${missing ? `. ${missing} in private chats have none.` : ''}`);
  } catch { toast("Couldn't copy to the clipboard. Open the details panel to copy links.", { err: true }); }
}
export async function doDelete(items) {
  const ok = !S.settings.confirm_delete || await confirmDialog(items.length === 1 ? 'Delete this file from Telegram?' : `Delete ${items.length} files from Telegram?`,
    'This deletes the messages in their chats, for everyone where Telegram allows it. It can’t be undone.', 'Delete from Telegram', true);
  if (!ok) return;
  try {
    const r = await api(A('/files/delete'), { method: 'POST', body: { items } });
    if (r.deleted) toast(r.deleted === 1 ? 'Deleted' : `Deleted ${r.deleted} files`);
    if (r.failed.length) toast(`Telegram didn't allow deleting in: ${r.failed.join(', ')}`, { err: true });
    removeFromList(items);
    bus.emit('chats-changed');
  } catch (e) { fail(e); }
}
export async function doForget(items) {
  const ok = await confirmDialog(`Hide ${plural(items.length, 'file')} from TG Drive?`,
    'They are removed from the index only. Nothing changes in Telegram. “Index again from scratch” on the chat brings them back.', 'Remove from index');
  if (!ok) return;
  try {
    const r = await api(A('/files/forget'), { method: 'POST', body: { items } });
    toast(`Removed ${plural(r.removed, 'file')} from the index`);
    removeFromList(items);
  } catch (e) { fail(e); }
}
export async function toggleStar(files) {
  if (!files.length) return;
  const star = !files.every((f) => f.starred);
  try {
    await api(A('/files/meta'), { method: 'POST', body: { items: files.map((f) => [f.chat_id, f.msg_id]), starred: star } });
    files.forEach((f) => { f.starred = star; refreshCard(f); });
    S.starredCount += star ? files.length : -files.length;
    toast(star ? (files.length === 1 ? 'Starred' : `Starred ${files.length} files`) : 'Removed star', { action: 'Undo', onAction: undoLast });
    bus.emit('meta-changed');
  } catch (e) { fail(e); }
}
export async function editTags(files) {
  if (!files.length) return;
  const common = files.length === 1 ? files[0].tags || [] : (files[0].tags || []).filter((t) => files.every((f) => (f.tags || []).includes(t)));
  const r = await tagsDialog(common, files.length === 1 ? `Tags for “${files[0].name}”` : `Tags for ${files.length} files`);
  if (!r) return;
  const removed = common.filter((t) => !r.tags.includes(t));
  try {
    await api(A('/files/meta'), {
      method: 'POST',
      body: files.length === 1 ? { items: [[files[0].chat_id, files[0].msg_id]], tags: r.tags }
        : { items: files.map((f) => [f.chat_id, f.msg_id]), tags_add: r.tags, tags_remove: removed },
    });
    files.forEach((f) => { f.tags = files.length === 1 ? r.tags : [...new Set([...(f.tags || []).filter((t) => !removed.includes(t)), ...r.tags])]; refreshCard(f); });
    toast('Tags saved');
    bus.emit('meta-changed');
  } catch (e) { fail(e); }
}
export async function renameOne(f) {
  const name = await promptDialog('Rename', 'Name in TG Drive (the message in Telegram is unchanged)', f.name, 'Rename', { selectStem: true, max: 120 });
  if (name === null || name === undefined) return;
  try {
    await api(A(`/files/${f.chat_id}/${f.msg_id}/rename`), { method: 'POST', body: { name } });
    f.name = name || f.original_name;
    f.renamed = !!name && name !== f.original_name;
    refreshCard(f);
    toast('Renamed', { action: 'Undo', onAction: undoLast });
    bus.emit('meta-changed');
  } catch (e) { fail(e); }
}
export async function bulkRename(files) {
  const pattern = await promptDialog(`Rename ${files.length} files`, 'Pattern', '{name}', 'Rename', {
    help: 'Use <code>{n}</code> for a number (<code>{n:02}</code> pads to 2 digits), <code>{name}</code> for the current name, <code>{date}</code>, <code>{chat}</code>. The extension is kept. Files are numbered in the order shown.',
  });
  if (!pattern) return;
  try {
    const ordered = S.items.filter((f) => files.includes(f));
    const r = await api(A('/files/rename'), { method: 'POST', body: { items: ordered.map((f) => [f.chat_id, f.msg_id]), pattern } });
    toast(`Renamed ${plural(r.renamed, 'file')}`, { action: 'Undo', onAction: undoLast });
    reload(true);
  } catch (e) { fail(e); }
}
export async function editNote(f) {
  const det = await api(A(`/files/${f.chat_id}/${f.msg_id}`));
  const note = await promptDialog('Note', 'Your note (synced, searchable with has:note)', det.note || '', 'Save', { multiline: true, allowEmpty: true, max: 2000 });
  if (note === null || note === undefined) return;
  try {
    await api(A('/files/meta'), { method: 'POST', body: { items: [[f.chat_id, f.msg_id]], note } });
    f.note = !!note;
    toast(note ? 'Note saved' : 'Note removed');
    bus.emit('meta-changed');
  } catch (e) { fail(e); }
}
export async function openInTelegram(f) {
  try {
    const det = await api(A(`/files/${f.chat_id}/${f.msg_id}`));
    const url = det.tg_link || det.link;
    if (!url) return toast("Telegram has no link for messages in basic groups.", { err: true });
    if (bridge.ready) callBridge('openExternal', url);
    else window.open(url, '_blank', 'noopener');
  } catch (e) { fail(e); }
}

/* Subjects: choose one by hand (the automatic tagger never changes it again), or none. */
export async function setSubject(files) {
  if (!files.length) return;
  let list = S.subjects;
  if (!list?.length) { try { list = (await api(A('/subjects'))).subjects; S.subjects = list; } catch (e) { return fail(e); } }
  const cur = files.length === 1 ? files[0].subject : null;
  const r = await dialog({
    title: files.length === 1 ? 'Subject' : `Subject for ${plural(files.length, 'file')}`,
    body: `<p>Subjects are set automatically from names and captions. Pick one to correct it; TG Drive won't change it again.</p>
      <div class="subject-pick">${list.map((s) => `<button class="chip ${cur === s.id ? 'on' : ''}" data-sid="${s.id}">${s.emoji ? `<span>${s.emoji}</span>` : ''}${s.name}</button>`).join('')}
      <button class="chip ghost" data-sid="">No subject</button></div>`,
    actions: [{ label: 'Cancel' }],
    onOpen: (bd, done) => bd.addEventListener('click', (e) => { const b = e.target.closest('[data-sid]'); if (b) done({ sid: b.dataset.sid }); }),
  });
  if (!r) return;
  try {
    await api(A('/subjects/set'), { method: 'POST', body: { items: files.map((f) => [f.chat_id, f.msg_id]), subject: r.sid || null } });
    files.forEach((f) => { f.subject = r.sid || null; refreshCard(f); });
    toast(r.sid ? `Subject set to ${list.find((s) => s.id === r.sid)?.name || r.sid}` : 'Subject removed');
    bus.emit('subjects-changed');
  } catch (e) { fail(e); }
}

export function fileMenuItems(files) {
  if (!files.length) return [];
  const one = files.length === 1 ? files[0] : null;
  const items = files.map((f) => [f.chat_id, f.msg_id]);
  const allStarred = files.every((f) => f.starred);
  const pics = files.filter((f) => f.kind === 'photo' || (f.mime || '').startsWith('image/'));
  return [
    one ? { label: STREAMABLE.has(one.kind) ? 'Play' : 'Preview', icon: STREAMABLE.has(one.kind) ? 'play' : 'eye', kbd: 'Enter', onClick: () => openFile(one) } : null,
    one ? { label: 'Open with default app', icon: 'external', onClick: () => doOpenLocal(one) } : null,
    pics.length > 1 ? { label: `Slideshow (${pics.length} pictures)`, icon: 'slides', onClick: () => import('./viewer.js').then((m) => m.slideshow(pics)) } : null,
    { label: files.length > 1 ? `Download ${files.length} files` : 'Download', icon: 'download', kbd: 'D', onClick: () => doDownload(items) },
    files.length > 1 ? { label: 'Download as .zip', icon: 'download', onClick: () => doDownload(items, { zip: true, name: viewTitle() }) } : null,
    '-',
    { label: 'Move to folder…', icon: 'move', kbd: 'M', onClick: () => doMove(items, one?.folder_id) },
    { label: allStarred ? 'Remove star' : 'Star', icon: 'star', kbd: 'S', onClick: () => toggleStar(files) },
    { label: 'Tags…', icon: 'tag', kbd: 'T', onClick: () => editTags(files) },
    { label: 'Subject…', icon: 'book', onClick: () => setSubject(files) },
    one ? { label: 'Note…', icon: 'note', onClick: () => editNote(one) } : null,
    files.some((f) => STREAMABLE.has(f.kind) && f.kind !== 'gif')
      ? (files.every((f) => f.watched)
        ? { label: 'Mark as not watched', icon: 'eye', onClick: () => import('./viewer.js').then((m) => m.setWatched(files, false)) }
        : { label: 'Mark as watched', icon: 'check', onClick: () => import('./viewer.js').then((m) => m.setWatched(files, true)) })
      : null,
    one ? { label: 'Rename…', icon: 'edit', kbd: 'F2', onClick: () => renameOne(one) } : { label: 'Rename with a pattern…', icon: 'edit', onClick: () => bulkRename(files) },
    '-',
    { label: 'Save a copy to Drive…', icon: 'copy', onClick: () => doCopy(items) },
    { label: 'Send to chat…', icon: 'send', onClick: () => doSend(items) },
    { label: files.length > 1 ? 'Copy links' : 'Copy link', icon: 'link', kbd: 'L', onClick: () => doLinks(files) },
    one ? { label: 'Open in Telegram', icon: 'telegram', onClick: () => openInTelegram(one) } : null,
    one ? { label: 'Show in chat', icon: 'chat', kbd: 'C', onClick: () => import('./context.js').then((m) => m.showContext(one)) } : null,
    one && S.view.type !== 'chat' ? { label: 'Go to chat', icon: 'chevron', onClick: () => bus.emit('go', `#chat/${one.chat_id}`) } : null,
    one?.grouped_id ? { label: 'Show album', icon: 'photo', onClick: () => bus.emit('go', `#album/${one.chat_id}/${one.grouped_id}`) } : null,
    one ? { label: 'Find related files', icon: 'sparkle', onClick: () => bus.emit('go', `#search/${encodeURIComponent(one.name.replace(/\.[^.]+$/, '').replace(/[_\-.]+/g, ' '))}`) } : null,
    '-',
    { label: 'Hide from TG Drive (keep in Telegram)', icon: 'close', onClick: () => doForget(items) },
    { label: 'Delete from Telegram', icon: 'trash', danger: true, kbd: 'Del', onClick: () => doDelete(items) },
  ].filter(Boolean);
}

export function bulkAction(act, anchor) {
  const files = selectedFiles();
  const items = files.map((f) => [f.chat_id, f.msg_id]);
  ({
    download: () => doDownload(items),
    move: () => doMove(items),
    copy: () => doCopy(items),
    send: () => doSend(items),
    star: () => toggleStar(files),
    tags: () => editTags(files),
    clear: () => setSelected([]),
    more: () => menu(anchor, fileMenuItems(files), { alignRight: true }),
  })[act]?.();
}

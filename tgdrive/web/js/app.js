// Boot, routing, polling, global shortcuts.
import { $, $$, S, A, api, esc, icon, initials, bus, pref, initBridge, bridge, callBridge, plural, fmtSize, key, qs } from './core.js';
import { toast, fail, menu, closeMenu, menuOpen, confirmDialog, shortcutsDialog, folderPath } from './ui.js';
import {
  reload, renderHeader, renderFolderArea, setSelected, selectedFiles, selectedItems, toggleView, setDensity, listParams,
  doDownload, doMove, doDelete, toggleStar, editTags, renameOne, doLinks, undoLast, openFile, rerenderItems,
} from './files.js';
import { loadFolders, loadChats, renderNav, renderTree, renderChats, renderIndexStatus } from './sidebar.js';
import { renderDrawer, closeDrawer, startRenameInPanel } from './details.js';
import { loadTransfers, openTransfers, pickUpload, pickUploadFolder, uploadToChat, updateBadge } from './transfers.js';
import { renderChips, focusSearch, toggleAdv } from './search.js';
import { renderPage } from './pages.js';
import { showOnboarding, showLock } from './login.js';
import { newFolder } from './folders.js';
import { applyDebug, setDebug, debugOn, viewLog } from './debuglog.js';

const PAGES = new Set(['storage', 'duplicates', 'index', 'activity', 'settings', 'photos', 'map', 'sync', 'marks']);
const EMBED = new URLSearchParams(location.search).has('embed');
document.documentElement.classList.toggle('embed', EMBED);
// Other windows and the split-view pane: tell each other when folders or files changed.
const channel = 'BroadcastChannel' in window ? new BroadcastChannel('tgdrive') : null;
let fromOtherWindow = false;
channel?.addEventListener('message', (e) => {
  if (e.data?.aid !== S.aid) return;
  fromOtherWindow = true;
  try { bus.emit(e.data.evt); } finally { fromOtherWindow = false; }
});
function broadcast(evt) { if (!fromOtherWindow) channel?.postMessage({ evt, aid: S.aid }); }

/* ------------------------------------------------------------------- boot */
async function boot() {
  $('#menuBtn').innerHTML = icon('menu');
  $('#advBtn').innerHTML = icon('sliders');
  $('#searchClear').innerHTML = icon('close');
  $('#transfersBtn').insertAdjacentHTML('afterbegin', icon('transfers'));
  $('#refreshBtn').innerHTML = icon('refresh');
  $('#moreBtn').innerHTML = icon('more');
  $('#newBtn').innerHTML = `${icon('plus')}<span>New</span>`;
  $('#chatSortBtn').innerHTML = icon('sliders');
  S.desktop = await initBridge();
  if (S.desktop && !EMBED) import('./wintitle.js').then((m) => m.initWindowChrome()).catch(() => {});
  S.localHost = ['127.0.0.1', 'localhost', '[::1]'].includes(location.hostname);
  document.documentElement.classList.toggle('desktop', S.desktop);
  let st;
  try { st = await api('/api/status'); } catch (e) {
    $('#login').hidden = false;
    $('#login').innerHTML = `<div class="login-wrap"><div class="login"><h1>TG Drive isn't responding</h1><p>${esc(e.message)}</p></div></div>`;
    return;
  }
  applyStatus(st);
  if (st.locked) return showLock();
  if (!S.accounts.length) return showOnboarding(false);
  const saved = Number(pref('account'));
  S.aid = S.accounts.some((a) => a.id === saved) ? saved : S.accounts[0].id;
  showApp();
}

function applyStatus(st) {
  S.version = st.version;
  S.apiConfigured = st.api_configured;
  S.accounts = st.accounts || S.accounts;
  S.settings = st.settings || S.settings;
  S.downloadDir = st.download_dir;
  const mp = st.media_port;
  S.mediaToken = st.media_token || '';
  S.mediaBase = mp && S.localHost ? `${location.protocol}//${location.hostname}:${mp}` : '';
  applyTheme();
  applyDebug(!!S.settings.debug_logging);
}
function luminance(hex) {
  const n = parseInt(hex.slice(1), 16);
  const c = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}
export function applyTheme() {
  const s = S.settings;
  const root = document.documentElement;
  const t = s.theme;
  if (t === 'light' || t === 'dark') root.dataset.theme = t;
  else delete root.dataset.theme;
  root.dataset.density = s.density || 'comfortable';
  if (s.contrast === 'high') root.dataset.contrast = 'high'; else delete root.dataset.contrast;
  root.dataset.motion = ['on', 'system', 'off'].includes(s.motion) ? s.motion : 'on';
  if (/^#[0-9a-f]{6}$/i.test(s.accent || '')) {
    root.style.setProperty('--accent-base', s.accent);
    root.style.setProperty('--accent-ink-l', luminance(s.accent) > 0.45 ? '#10151d' : '#ffffff');
  } else { root.style.removeProperty('--accent-base'); root.style.removeProperty('--accent-ink-l'); }
  root.style.setProperty('--fs', String(Math.max(0.8, Math.min(1.5, Number(s.font_scale) || 1))));
  import('./columns.js').then((m) => m.applyTemplate());
  if (S.desktop) callBridge('setTheme', t || 'system');
}

function showApp() {
  $('#login').hidden = true;
  $('#app').hidden = false;
  switchAccount(S.aid);
}

async function switchAccount(aid) {
  S.aid = aid;
  pref('account', aid);
  S.selected.clear();
  S.drawer = null;
  S.transfers = [];
  S.adv = {};
  S.searchScope = null;
  renderDrawer();
  renderAccountButton();
  await Promise.all([loadFolders(), loadChats()]).catch(fail);
  loadSubjects();
  if (!location.hash || location.hash === '#') history.replaceState(null, '', '#drive');
  route();
  poll();
  pollEvents();
  loadTransfers();
  window.tgdrive.ready = true;
  if (!EMBED) checkCrashes();
}

export async function loadSubjects() {
  try {
    const r = await api(A('/subjects'));
    S.subjects = r.subjects;
    S.subjectsEnabled = r.enabled;
    renderNav();
    bus.emit('subjects-loaded');
  } catch { /* optional */ }
}
bus.on('subjects-changed', () => setTimeout(loadSubjects, 400));

/* ------------------------------------------------------------- accounts */
function renderAccountButton() {
  const a = S.accounts.find((x) => x.id === S.aid) || {};
  $('#accountBtn').innerHTML = `<span class="avatar">${esc(initials(a.name))}</span><span class="who">${esc(a.name || '')}</span>
    <span class="dot ${esc(a.status || '')}" title="${esc(a.status === 'online' ? 'Connected to Telegram' : a.error || 'Not connected')}"></span>`;
  $('#accountBtn').setAttribute('aria-label', `Account: ${a.name || ''}`);
}
$('#accountBtn').addEventListener('click', (e) => {
  const items = S.accounts.map((a) => ({
    html: `<span class="acct"><span class="avatar">${esc(initials(a.name))}</span><span>${esc(a.name)}<small>${esc(a.username ? '@' + a.username : a.phone || '')}${a.premium ? ' · Premium' : ''}</small></span></span>`,
    cls: a.id === S.aid ? 'acct current' : 'acct',
    onClick: () => { if (a.id !== S.aid) switchAccount(a.id); },
  }));
  items.push('-', { label: 'Add account', icon: 'plus', onClick: () => showOnboarding(true) },
    { label: 'Settings', icon: 'settings', kbd: 'Ctrl ,', onClick: () => go('#settings') },
    { label: 'Keyboard shortcuts', icon: 'keyboard', kbd: '?', onClick: shortcutsDialog },
    '-',
    { label: 'Detailed debug logging', icon: 'bug', checked: debugOn(), onClick: () => setDebug(!debugOn()) },
    debugOn() ? { label: 'View debug log', icon: 'document', onClick: viewLog } : null,
    S.settings.lock_set ? { label: 'Lock TG Drive', icon: 'lock', onClick: () => api('/api/lock/now', { method: 'POST' }).then(showLock) } : null,
    '-', { label: 'Sign out of this account…', icon: 'signout', danger: true, onClick: () => removeAccount(S.aid) });
  menu(e.currentTarget, items.filter(Boolean), { alignRight: true });
});
async function removeAccount(aid) {
  const a = S.accounts.find((x) => x.id === aid);
  const ok = await confirmDialog('Sign out of this account?', `TG Drive signs out of <b>${esc(a.name)}</b> and deletes its local index, previews and caches on this computer. Downloaded files, your Telegram data, folders and the Drive channel stay.`, 'Sign out', true);
  if (!ok) return;
  try {
    await api(`/api/accounts/${aid}`, { method: 'DELETE' });
    const st = await api('/api/status');
    S.accounts = st.accounts;
    if (!S.accounts.length) return showOnboarding(false);
    switchAccount(S.accounts[0].id);
  } catch (err) { fail(err); }
}
bus.on('switch-account', switchAccount);
bus.on('remove-account', removeAccount);
bus.on('add-account', () => showOnboarding(true));
bus.on('signed-in', async (account) => {
  const st = await api('/api/status');
  applyStatus(st);
  S.aid = account.id;
  showApp();
});
bus.on('locked', () => showLock());
bus.on('unlocked', () => boot());

/* ---------------------------------------------------------------- routing */
export function go(hash) {
  if (location.hash === hash) route();
  else location.hash = hash;
}
bus.on('go', go);
bus.on('route', () => route());
bus.on('reload', () => { renderChips(); reload(); });

function parseHash() {
  const raw = decodeURIComponent(location.hash.slice(1));
  const [path, query] = raw.split('?');
  const [type, ...rest] = path.split('/');
  return { type: type || 'drive', rest, params: new URLSearchParams(query || '') };
}

function route() {
  if (!S.aid) return;
  const { type, rest, params } = parseHash();
  const prev = S.view;
  let v;
  if (type === 'all') v = { type: 'all' };
  else if (type === 'starred') v = { type: 'starred' };
  else if (type === 'recent') v = { type: 'recent' };
  else if (type === 'continue') v = { type: 'continue' };
  else if (type === 'chat' && rest[0]) v = { type: 'chat', chatId: Number(rest[0]), topicId: rest[1] === 'topic' ? Number(rest[2]) : null };
  else if (type === 'tg' && rest[0]) v = { type: 'tg', filterId: Number(rest[0]) };
  else if (type === 'saved' && rest[0]) v = { type: 'saved', savedId: rest[0] };
  else if (type === 'tag' && rest[0]) v = { type: 'tag', tag: rest.join('/') };
  else if (type === 'album' && rest[1]) v = { type: 'album', chatId: Number(rest[0]), groupedId: rest[1] };
  else if (type === 'search') v = { type: 'search', q: rest.join('/') };
  else if (type === 'subject' && rest[0]) v = { type: 'subject', subject: rest[0] };
  else if (PAGES.has(type)) v = { type, arg: rest[0] };
  else v = { type: 'drive', folderId: rest[0] || null };
  const sameKind = prev && prev.type === v.type;
  S.view = v;
  if (v.type !== 'search') {
    if (!PAGES.has(v.type)) S.lastBrowse = location.hash || '#drive';
    $('#q').value = '';
    $('#searchClear').hidden = true;
    if (!sameKind || v.type !== prev.type) { S.adv = {}; S.searchScope = null; }
    if (S.sort === 'relevance') { S.sort = 'date'; S.order = 'desc'; }
  } else {
    if ($('#q').value.trim() !== v.q && document.activeElement !== $('#q')) { $('#q').value = v.q; }
    $('#searchClear').hidden = !$('#q').value;
    if (prev?.type !== 'search' && !S.userSorted) { S.sort = 'relevance'; S.order = 'desc'; }
  }
  if (!sameKind || params.get('kind')) S.kind = params.get('kind') || '';
  if (prev?.type !== v.type) S.userSorted = false;
  S.selected.clear();
  if (S.drawer === 'details') closeDrawer();
  $('#sidebar').classList.remove('open');
  closeMenu();
  const isPage = PAGES.has(v.type);
  $('#listView').hidden = isPage;
  $('#pageView').hidden = !isPage;
  renderNav();
  renderChats();
  if (isPage) {
    const pv = $('#pageView');
    pv.className = 'page-view';
    if (!sameKind) { void pv.offsetWidth; pv.classList.add('page-enter'); }
    if (v.type === 'photos') import('./photos.js').then((m) => m.renderPhotos(v.arg));
    else if (v.type === 'map') import('./map.js').then((m) => m.renderMap());
    else if (v.type === 'sync') import('./sync.js').then((m) => m.renderSyncPage());
    else if (v.type === 'marks') import('./pdfview.js').then((m) => m.renderMarksPage());
    else renderPage(v.type, v.arg);
    return;
  }
  S.lastListParams = listParams();
  renderChips();
  reload();
}
window.addEventListener('hashchange', route);
window.addEventListener('popstate', () => { if (location.hash !== `#${S.view.type}`) route(); });

bus.on('drive-changed', async () => {
  broadcast('drive-changed');
  await loadFolders().catch(fail);
  if (!$('#listView').hidden) { renderFolderArea(); reload(true); }
});
bus.on('meta-changed', () => { broadcast('meta-changed'); loadFolders().catch(() => {}); api(A('/tags')).then((r) => { S.tags = r.tags; renderNav(); }).catch(() => {}); });
bus.on('chats-changed', () => loadChats().catch(() => {}));
bus.on('open-file-ref', async (f) => {
  try {
    const det = await api(A(`/files/${f.chat_id}/${f.msg_id}`));
    openFile(det);
  } catch (e) { fail(e); }
});
bus.on('settings-changed', (k) => {
  applyTheme();
  if (k === 'debug_logging') applyDebug(!!S.settings.debug_logging, true);
  if (k === 'hide_duplicates') broadcast('settings-refresh');
  if (['view', 'grid_size', 'group_by_date'].includes(k)) { /* next list render picks it up */ }
});

/* ----------------------------------------------------------- navigation */
document.addEventListener('click', (e) => {
  const tw = e.target.closest('[data-twisty]');
  if (tw) {
    e.preventDefault();
    e.stopPropagation();
    const id = tw.dataset.twisty;
    S.openFolders.has(id) ? S.openFolders.delete(id) : S.openFolders.add(id);
    renderTree();
    return;
  }
  const g = e.target.closest('[data-go]');
  if (g && !e.target.closest('[data-folder-menu], [data-chat-menu], [data-saved-menu]')) {
    e.preventDefault();
    const m = g.dataset.go.match(/^#drive\/(.+)$/);
    if (m) folderPath(m[1]).forEach((f) => S.openFolders.add(f.parent_id || ''));
    go(g.dataset.go);
    return;
  }
  const fm = e.target.closest('[data-folder-menu]');
  if (fm) { e.stopPropagation(); import('./folders.js').then((mod) => mod.folderMenu(fm, fm.dataset.folderMenu)); return; }
  const folder = e.target.closest('.fitem[data-folder]');
  if (folder && !folder.classList.contains('fhead')) { S.openFolders.add(S.folderById.get(folder.dataset.folder)?.parent_id || ''); go(`#drive/${folder.dataset.folder}`); return; }
  const act = e.target.closest('[data-act]');
  if (act) { ({ 'new-folder': () => newFolder(), upload: () => pickUpload(), retry: () => reload() })[act.dataset.act]?.(); return; }
  const tab = e.target.closest('.tab[data-kind]');
  if (tab) { S.kind = tab.dataset.kind; reload(); }
});
document.addEventListener('contextmenu', (e) => {
  const folder = e.target.closest('.fitem[data-folder], #tree [data-go^="#drive/"]');
  if (!folder) return;
  e.preventDefault();
  const id = folder.dataset.folder || folder.dataset.go.split('/')[1];
  import('./folders.js').then((mod) => mod.folderMenu({ getBoundingClientRect: () => ({ left: e.clientX, right: e.clientX, top: e.clientY, bottom: e.clientY }), setAttribute() {} }, id));
});
document.addEventListener('keydown', (e) => {
  const folder = e.target.closest?.('.fitem[data-folder]');
  if (folder && e.key === 'Enter' && e.target === folder) go(`#drive/${folder.dataset.folder}`);
});

$('#newBtn').addEventListener('click', (e) => menu(e.currentTarget, [
  { label: 'New folder', icon: 'folderPlus', onClick: () => newFolder() },
  { label: 'New smart folder…', icon: 'sparkle', onClick: () => import('./folders.js').then((m) => m.newSmartFolder()) },
  '-',
  { label: 'Upload files', icon: 'upload', onClick: () => pickUpload() },
  { label: 'Upload a folder', icon: 'uploadFolder', onClick: () => pickUploadFolder() },
  { label: 'Upload to a chat…', icon: 'send', onClick: () => uploadToChat() },
  { label: 'Paste files', icon: 'paste', kbd: 'Ctrl V', onClick: () => import('./transfers.js').then((m) => m.pasteFromBridge()) },
  '-',
  { label: 'Sync a folder on this computer…', icon: 'sync', onClick: () => import('./sync.js').then((m) => m.addPairDialog()) },
]));
$('#sort').addEventListener('change', () => {
  [S.sort, S.order] = $('#sort').value.split(':');
  S.userSorted = true;
  reload();
});
$('#refreshBtn').addEventListener('click', async (e) => {
  const b = e.currentTarget;
  if (b.classList.contains('spinning')) return;
  b.classList.add('spinning');
  const t0 = Date.now();
  try {
    await Promise.all([loadFolders(), loadChats()]).catch(fail);
    if (!$('#listView').hidden) reload(true); else route();
  } finally {
    setTimeout(() => b.classList.remove('spinning'), Math.max(0, 600 - (Date.now() - t0)));
  }
});
$('#viewBtn').addEventListener('click', toggleView);
$('#copiesBtn').addEventListener('click', () => setHideDuplicates(S.settings.hide_duplicates === false));
async function setHideDuplicates(hide) {
  S.settings.hide_duplicates = hide;
  try {
    const r = await api('/api/settings', { method: 'PATCH', body: { hide_duplicates: hide } });
    S.settings = r.settings;
  } catch (e) { fail(e); }
  const extra = S.status?.dupes?.extra || 0;
  toast(hide ? `Duplicates hidden: one card per file${extra ? ` (${plural(extra, 'extra copy', 'extra copies')} folded away)` : ''}` : 'Showing every copy of every file');
  broadcast('settings-refresh');
  renderNav();
  if (!$('#listView').hidden) reload(true); else route();
}
bus.on('set-hide-duplicates', setHideDuplicates);
// Another window changed a setting that changes lists: pick it up and show the list again.
bus.on('settings-refresh', async () => {
  try { S.settings = await api('/api/settings'); } catch { return; }
  applyTheme();
  if (!$('#listView').hidden) reload(true);
});
$('#moreBtn').addEventListener('click', (e) => {
  const p = listParams() || {};
  menu(e.currentTarget, [
    { label: 'Open in split view', icon: 'split', onClick: () => import('./split.js').then((m) => m.openSplit(location.hash)) },
    S.desktop ? { label: 'Open in new window', icon: 'window', kbd: 'Ctrl Shift N', onClick: () => callBridge('newWindow', location.hash) } : { label: 'Open in new tab', icon: 'window', onClick: () => window.open(location.href, '_blank', 'noopener') },
    '-',
    { header: 'Card size' },
    ...[['s', 'Small'], ['m', 'Medium'], ['l', 'Large']].map(([k, l]) => ({ label: l, checked: (S.settings.grid_size || 'm') === k, onClick: () => setDensity(k) })),
    { label: 'Group by date', checked: !!S.settings.group_by_date, onClick: () => { S.settings.group_by_date = !S.settings.group_by_date; api('/api/settings', { method: 'PATCH', body: { group_by_date: S.settings.group_by_date } }).catch(() => {}); rerenderItems(); } },
    { label: 'Albums as stacks', checked: S.settings.stack_albums !== false, onClick: () => { S.settings.stack_albums = S.settings.stack_albums === false; api('/api/settings', { method: 'PATCH', body: { stack_albums: S.settings.stack_albums } }).catch(() => {}); rerenderItems(); } },
    { label: 'List columns…', icon: 'columns', onClick: () => import('./columns.js').then((m) => m.columnsDialog()) },
    '-',
    { label: 'Select all loaded', icon: 'check', kbd: 'Ctrl A', onClick: () => setSelected(S.items.map(key)) },
    { label: 'Download everything here', icon: 'download', onClick: () => downloadAll(false) },
    { label: 'Download everything as .zip', icon: 'download', onClick: () => downloadAll(true) },
    { label: 'Playlist for VLC / mpv', icon: 'play', onClick: () => { window.location.href = `${S.mediaBase}${A(`/playlist.m3u?${qs(p)}`)}`; } },
    { label: 'Export list as CSV', icon: 'download', onClick: () => { window.location.href = A(`/export.csv?${qs(p)}`); } },
    S.view.type === 'search' ? { label: 'Save this search', icon: 'star', onClick: () => import('./search.js').then((m) => m.saveSearch()) } : null,
  ].filter(Boolean), { alignRight: true });
});
async function downloadAll(zip) {
  const total = S.stats?.total ?? S.items.length;
  if (total > S.items.length) {
    const ok = await confirmDialog(`Download ${plural(total, 'file')}?`, `That's ${fmtSize(S.stats?.total_bytes || 0)}. Only the ${plural(S.items.length, 'file')} loaded so far will be queued; scroll further to include more.`, 'Download loaded files');
    if (!ok) return;
  }
  doDownload(S.items.map((f) => [f.chat_id, f.msg_id]), zip ? { zip: true, name: document.title } : { keep_structure: true });
}
$('#transfersBtn').addEventListener('click', () => {
  if (S.drawer === 'transfers') { S.drawer = S.selected.size ? 'details' : null; renderDrawer(); } else openTransfers();
});
$('#menuBtn').addEventListener('click', () => $('#sidebar').classList.toggle('open'));

/* -------------------------------------------------------------- keyboard */
let gPending = 0;
document.addEventListener('keydown', (e) => {
  const tag = document.activeElement?.tagName || '';
  const inField = /INPUT|TEXTAREA|SELECT/.test(tag) || document.activeElement?.isContentEditable;
  const layer = $('#layer').children.length > 0;
  if (e.key === 'Escape') {
    if (menuOpen()) return closeMenu();
    if (!$('#adv').hidden) return toggleAdv(false);
    if (layer) return;
    if (inField) { document.activeElement.blur(); return; }
    if (S.selected.size) return setSelected([]);
    if (S.drawer) { closeDrawer(); return; }
    if ($('#sidebar').classList.contains('open')) $('#sidebar').classList.remove('open');
    return;
  }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); focusSearch(); return; }
  if ((e.ctrlKey || e.metaKey) && e.key === ',') { e.preventDefault(); go('#settings'); return; }
  if (inField || layer) return;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); undoLast(); return; }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a' && S.items.length && !$('#listView').hidden) { e.preventDefault(); setSelected(S.items.map(key)); return; }
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === '/') { e.preventDefault(); focusSearch(); return; }
  if (e.key === '?') { e.preventDefault(); shortcutsDialog(); return; }
  if (gPending && Date.now() - gPending < 1200) {
    gPending = 0;
    const dest = { d: '#drive', a: '#all', s: '#starred', r: '#recent', c: '#continue', i: '#index', t: '#storage', p: '#photos', m: '#map' }[e.key.toLowerCase()];
    if (dest) { e.preventDefault(); go(dest); }
    return;
  }
  if (e.key.toLowerCase() === 'g') { gPending = Date.now(); return; }
  if (e.key.toLowerCase() === 'v' && !$('#listView').hidden) { toggleView(); return; }
  if (e.key.toLowerCase() === 'f' && !$('#listView').hidden) { import('./search.js').then((m) => m.toggleFilters()); return; }
  const files = selectedFiles();
  if (!files.length) return;
  const items = selectedItems();
  const k = e.key;
  if (k === 'Delete') { e.preventDefault(); doDelete(items); }
  else if (k === 'F2') { e.preventDefault(); if (files.length > 1 || !startRenameInPanel()) renameOne(files[0]); }
  else if (k.toLowerCase() === 's') toggleStar(files);
  else if (k.toLowerCase() === 't') editTags(files);
  else if (k.toLowerCase() === 'm') doMove(items, files[0]?.folder_id);
  else if (k.toLowerCase() === 'd') doDownload(items);
  else if (k.toLowerCase() === 'l') doLinks(files);
  else if (k.toLowerCase() === 'c' && files.length === 1) import('./context.js').then((m) => m.showContext(files[0]));
});

/* ---------------------------------------------------------------- polling */
let pollTimer = null;
async function poll() {
  clearTimeout(pollTimer);
  const aid = S.aid;
  try {
    const st = await api(A('/status'));
    if (aid !== S.aid) return;
    const before = S.status;
    S.status = { ...st, download_dir: S.downloadDir, data_dir: S.status?.data_dir };
    const idx = S.accounts.findIndex((a) => a.id === aid);
    if (idx >= 0 && S.accounts[idx].status !== st.account.status) { S.accounts[idx] = st.account; renderAccountButton(); }
    renderIndexStatus();
    if (before?.dupes?.extra !== st.dupes?.extra) renderNav();
    S.tsummary = st.transfers;
    updateBadge();
    if (S.drawer === 'transfers' || (before && before.transfers_active !== st.transfers_active)) loadTransfers();
    const indexing = !['idle', 'paused'].includes(st.index.phase);
    if (indexing && Date.now() - (S.chatsTimer || 0) > 20000) { S.chatsTimer = Date.now(); loadChats().catch(() => {}); }
    if (before && !['idle', 'paused'].includes(before.index.phase) && !indexing) loadChats().catch(() => {});
    if (before && before.drive.channel_id !== st.drive.channel_id) loadFolders().catch(() => {});
    if (before && before.search?.state !== 'ready' && st.search?.state === 'ready') { toast('Search upgrade finished: smart matching is on.'); if (!$('#listView').hidden) reload(true); }
    document.title = st.index.phase === 'indexing' ? `TG Drive · indexing ${st.index.chats_done}/${st.index.chats_total}` : 'TG Drive';
  } catch (e) { /* server restarting; try again */ }
  pollTimer = setTimeout(poll, document.hidden ? 10000 : 2500);
}
bus.on('poll', () => poll());

let evTimer = null;
async function pollEvents() {
  clearTimeout(evTimer);
  try {
    const r = await api(`/api/events?after=${S.lastEvent}`);
    const first = S.lastEvent === 0;
    S.lastEvent = r.last;
    if (!first) {
      for (const ev of r.events) {
        if (ev.kind === 'crash' && !EMBED) checkCrashes();
        if (ev.kind === 'notify' && ev.account === S.aid) {
          if (!S.desktop) {
            toast(`${ev.title}: ${ev.body}`, ev.path && S.localHost ? { action: 'Open', onAction: () => api('/api/open', { method: 'POST', body: { path: ev.path } }).catch(fail) } : {});
            if (document.hidden && 'Notification' in window && Notification.permission === 'granted') new Notification(ev.title, { body: ev.body });
          } else toast(`${ev.title}: ${ev.body}`);
          if (ev.title.startsWith('Download') || ev.title.startsWith('Zip')) loadTransfers();
        }
      }
    }
  } catch { /* ignore */ }
  evTimer = setTimeout(pollEvents, document.hidden ? 8000 : 3000);
}
document.addEventListener('visibilitychange', () => { if (!document.hidden) { poll(); pollEvents(); } });

bus.on('header', () => { document.title = S.view.type === 'search' && S.view.q ? `${S.view.q} · TG Drive` : 'TG Drive'; });
/* ------------------------------------------------------ crash reporting */
// Errors in this page are saved as crash reports (only on this computer; see Settings → About).
let sentErrors = 0;
function reportError(message, stack, source) {
  console.error(message, stack);
  if (sentErrors++ > 8 || !S.settings || S.settings.crash_reports === false) return;
  api('/api/crash', { method: 'POST', body: { message: String(message).slice(0, 2000), stack: String(stack || '').slice(0, 20000), source, view: location.hash, agent: navigator.userAgent } }).catch(() => {});
}
window.addEventListener('error', (e) => {
  if (!e.error && /ResizeObserver loop/.test(e.message || '')) return;
  reportError(e.message, e.error?.stack, `${e.filename}:${e.lineno}`);
});
window.addEventListener('unhandledrejection', (e) => {
  const r = e.reason;
  if (!r || r.name === 'AbortError' || r instanceof Error === false || r.status !== undefined) return;
  reportError(r.message || String(r), r.stack, 'promise');
});
async function checkCrashes() {
  try {
    const r = await api('/api/crashes');
    const newest = r.reports.find((x) => x.new);
    const el = $('#crashNotice');
    if (!r.unseen || !newest) { if (el) el.remove(); return; }
    const box = el || Object.assign(document.createElement('div'), { id: 'crashNotice', className: 'crash-notice' });
    box.innerHTML = `${icon('bug')}<div class="grow"><strong>TG Drive ran into a problem${r.unseen > 1 ? ` (${r.unseen} times)` : ''}</strong><small>${esc(newest.summary || newest.kind)}</small></div>
      <button class="btn sm" data-crash="view">View report</button><button class="btn sm" data-crash="bundle">Create diagnostics file</button><button class="icon-btn tiny" data-crash="dismiss" aria-label="Dismiss">${icon('close')}</button>`;
    box.dataset.id = newest.id;
    if (!el) $('#main').prepend(box);
  } catch { /* ignore */ }
}
document.addEventListener('click', async (e) => {
  const b = e.target.closest('[data-crash]');
  if (!b) return;
  const act = b.dataset.crash;
  if (act === 'dismiss') { await api('/api/crashes/seen', { method: 'POST' }).catch(() => {}); $('#crashNotice')?.remove(); }
  if (act === 'view') { await api('/api/crashes/seen', { method: 'POST' }).catch(() => {}); $('#crashNotice')?.remove(); go('#settings/about'); }
  if (act === 'bundle') { const m = await import('./pages.js'); m.diagnosticsDialog(); }
});

/* ---------------------------------------------- tasks from the desktop */
// "Send to TG Drive" in a file manager, and launcher actions (search, upload).
async function receivePaths(paths) {
  const m = await import('./transfers.js');
  m.sendToDialog(paths);
}
function openTask(what) {
  if (what === 'search') { import('./search.js').then((m) => m.focusSearch()); }
  else if (what === 'upload') pickUpload();
}

window.tgdrive = { ...(window.tgdrive || {}), S, go, reload, receivePaths, openTask, ready: false };

boot();

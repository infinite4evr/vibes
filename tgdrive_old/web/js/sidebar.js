// Sidebar: Drive tree, quick views, saved searches, tags, Telegram folders, sources, tools, index status.
import { $, $$, S, A, api, esc, icon, fmtNum, fmtSize, fmtCompact, plural, pref, SOURCES, CHAT_KIND_NAME, bus, relTime } from './core.js';

// Counts are short (49.7k); the exact number is in the tooltip.
const cnt = (n, extra = '') => `<span class="count" title="${fmtNum(n)}${extra}">${fmtCompact(n)}</span>`;
// A section header that folds its section away (remembered). `closedKey` sections are open by default.
const isOpen = (id, openByDefault = false) => (openByDefault ? !S.openGroups.has(`${id}-closed`) : S.openGroups.has(id));
const sectionH = (id, label, openByDefault = false) => `<div class="side-h collapsible" data-toggle="${openByDefault ? `${id}-closed` : id}" role="button" tabindex="0" aria-expanded="${isOpen(id, openByDefault)}"><span>${label}</span><span class="sh-chev ${isOpen(id, openByDefault) ? 'open' : ''}">${icon('chevron')}</span></div>`;
import { childrenOf, folderPath, folderColor, chatAvatar, menu, toast, fail, confirmDialog, promptDialog } from './ui.js';

export async function loadFolders() {
  const r = await api(A('/folders'));
  S.folders = r.folders;
  S.folderById = new Map(r.folders.map((f) => [f.id, f]));
  S.driveChannel = r.drive.channel_id;
  S.driveInfo = r.drive;
  S.driveTitle = r.drive_title;
  S.saved = r.saved || [];
  S.starredCount = r.starred;
  S.continueCount = r.continue || 0;
  S.recentCount = r.recent;
  renderNav();
}

export async function loadChats() {
  const [r, df, tags] = await Promise.all([api(A('/chats')), api(A('/dialog_filters')).catch(() => ({ filters: [] })),
    api(A('/tags')).catch(() => ({ tags: [] }))]);
  S.chats = r.chats;
  S.chatById = new Map(r.chats.map((c) => [c.id, c]));
  S.dialogFilters = df.filters;
  S.tags = tags.tags;
  renderNav();
  renderChats();
}

const active = (type, test = () => true) => S.view.type === type && test();

export function renderNav() {
  const total = S.status?.index?.files ?? S.chats.reduce((a, c) => a + (c.file_count || 0), 0);
  const item = (go, ic, label, count, isActive, extra = '') => `<button class="nav-item ${isActive ? 'active' : ''}" data-go="${go}" ${extra}>
      ${icon(ic)}<span class="label">${esc(label)}</span>${count ? cnt(count) : ''}</button>`;
  $('#navTop').innerHTML = `
    ${item('#drive', 'folder', 'My Drive', 0, active('drive', () => !S.view.folderId), 'data-drop-folder=""')}
    <div class="tree" id="tree" role="tree" aria-label="Folders"></div>
    ${item('#all', 'grid', 'All files', total, active('all'))}
    ${item('#starred', 'star', 'Starred', S.starredCount, active('starred'))}
    ${item('#recent', 'clock', 'Recent', 0, active('recent'))}
    ${S.continueCount ? item('#continue', 'play', 'Continue watching', S.continueCount, active('continue')) : ''}
    ${item('#photos', 'image', 'Photos', 0, active('photos'))}
    ${item('#map', 'map', 'Places', 0, active('map'))}`;
  renderTree();
  const saved = S.saved.length ? `${sectionH('saved', 'Saved searches', true)}${!isOpen('saved', true) ? '' : S.saved.map((s) => `<div class="chat-row"><button class="nav-item ${active('saved', () => S.view.savedId === s.id) ? 'active' : ''}" data-go="#saved/${esc(s.id)}" title="${esc(s.q || '')}">
      ${icon('search')}<span class="label">${esc(s.name)}</span></button><button class="icon-btn more" data-saved-menu="${esc(s.id)}" aria-label="Saved search actions">${icon('more')}</button></div>`).join('')}` : '';
  const tags = S.tags.length ? `${sectionH('tags', 'Tags')}${S.openGroups.has('tags') ? `<div class="tag-cloud">${S.tags.slice(0, 40).map((t) => `<button class="chip ${active('tag', () => S.view.tag === t.tag) ? 'on' : ''}" data-go="#tag/${encodeURIComponent(t.tag)}">${esc(t.tag)}<small>${t.n}</small></button>`).join('')}</div>` : ''}` : '';
  const tg = S.dialogFilters.length ? `${sectionH('tg', 'Telegram folders')}${S.openGroups.has('tg') ? S.dialogFilters.map((d) => `<button class="nav-item ${active('tg', () => S.view.filterId === d.id) ? 'active' : ''}" data-go="#tg/${d.id}">
      <span class="emo">${esc(d.emoticon || '📁')}</span><span class="label" title="${esc(d.title)}">${esc(d.title)}</span>${cnt(d.chat_ids.length, ' chats')}</button>`).join('') : ''}` : '';
  const subj = (S.subjects || []).filter((x) => x.n > 0 && !x.id.startsWith('_')).sort((a, b) => b.n - a.n);
  const subjects = subj.length ? `${sectionH('subjects', 'Subjects')}${S.openGroups.has('subjects') ? subj.map((x) => `<button class="nav-item ${active('subject', () => S.view.subject === x.id) ? 'active' : ''}" data-go="#subject/${esc(x.id)}">
      <span class="emo">${x.emoji ? esc(x.emoji) : icon('book')}</span><span class="label">${esc(x.name)}</span>${cnt(x.n)}</button>`).join('') : ''}` : '';
  $('#navMid').innerHTML = saved + subjects + tg + tags;
  const toolsOpen = isOpen('tools', true);
  $('#navTools').innerHTML = `${sectionH('tools', 'Tools', true)}${!toolsOpen ? '' : `
    ${item('#storage', 'chart', 'Storage', 0, active('storage'))}
    ${item('#duplicates', 'dupes', 'Duplicates', 0, active('duplicates'))}
    ${item('#index', 'database', 'Index manager', 0, active('index'))}
    ${item('#sync', 'sync', 'Folder sync', 0, active('sync'))}
    ${item('#marks', 'highlight', 'PDF highlights', 0, active('marks'))}
    ${item('#activity', 'activity', 'Activity', 0, active('activity'))}
    ${item('#settings', 'settings', 'Settings', 0, active('settings'))}`}`;
  const srcOpen = isOpen('sources', true);
  $('#sourcesBody').hidden = !srcOpen;
  const sh = $('.sources-h');
  sh.setAttribute('aria-expanded', String(srcOpen));
  sh.querySelector('.sh-chev').innerHTML = icon('chevron');
  sh.querySelector('.sh-chev').classList.toggle('open', srcOpen);
}

export function renderTree() {
  const tree = $('#tree');
  if (!tree) return;
  const row = (f, depth) => {
    const kids = childrenOf(f.id);
    const open = S.openFolders.has(f.id);
    const act = S.view.type === 'drive' && S.view.folderId === f.id;
    return `<div role="treeitem" aria-expanded="${kids.length ? open : ''}">
      <button class="nav-item ${act ? 'active' : ''}" data-go="#drive/${esc(f.id)}" data-drop-folder="${esc(f.id)}" style="padding-left:${10 + depth * 14}px">
        <span class="twisty ${kids.length ? (open ? 'open' : '') : 'none'}" data-twisty="${esc(f.id)}" aria-hidden="true">${icon('chevron')}</span>
        ${f.emoji ? `<span class="fold-ic emo">${esc(f.emoji)}</span>` : `<span class="fold-ic" style="color:${folderColor(f)}">${icon(f.kind === 'smart' ? 'folderSmart' : 'folder')}</span>`}<span class="label" title="${esc(f.name)}">${esc(f.name)}</span>
        ${f.kind === 'smart' ? `<span class="count">${icon('sparkle')}</span>` : f.file_count ? cnt(f.file_count) : ''}</button>
      ${open ? `<div role="group">${kids.map((k) => row(k, depth + 1)).join('')}</div>` : ''}</div>`;
  };
  tree.innerHTML = childrenOf(null).map((f) => row(f, 1)).join('');
}

function sortChats(list) {
  const by = S.chatSort;
  return list.sort((a, b) => (b.pinned - a.pinned) || (by === 'name' ? a.title.localeCompare(b.title)
    : by === 'size' ? (b.total_bytes || 0) - (a.total_bytes || 0)
      : by === 'recent' ? (b.latest_msg_id || 0) - (a.latest_msg_id || 0) : (b.file_count || 0) - (a.file_count || 0)));
}

export function renderChats() {
  const q = S.chatFilter.trim().toLowerCase();
  const cap = q ? 400 : 250;
  $('#chatList').innerHTML = SOURCES.map(([gid, label, kinds]) => {
    const chats = sortChats(S.chats.filter((c) => kinds.includes(c.kind) && (!q || c.title.toLowerCase().includes(q) || (c.username || '').toLowerCase().includes(q))));
    if (!chats.length) return '';
    const withFiles = chats.filter((c) => c.file_count || c.excluded || c.index_state !== 'done' || c.pinned);
    const open = q || S.openGroups.has(gid);
    const n = chats.reduce((a, c) => a + (c.file_count || 0), 0);
    const shown = withFiles.slice(0, cap);
    return `<button class="group-h ${open ? 'open' : ''}" data-group="${gid}" aria-expanded="${!!open}">${icon('chevron')}${label}${cnt(n)}</button>
      ${open ? shown.map((c) => {
        const act = S.view.type === 'chat' && S.view.chatId === c.id;
        const cls = c.excluded ? 'excluded' : c.index_state === 'gone' ? 'gone' : '';
        const note = c.index_state === 'error' ? `<span class="warn" title="${esc(c.index_error || '')}">!</span>`
          : c.index_state === 'running' ? `<span class="spin" title="Indexing now"></span>` : c.pinned ? `<span class="pin-mark">${icon('pin')}</span>` : '';
        return `<div class="chat-row ${cls}"><button class="nav-item ${act ? 'active' : ''}" data-go="#chat/${c.id}" title="${esc(c.title)}${c.excluded ? ' (excluded from index)' : c.index_state === 'gone' ? ' (you left this chat)' : ''}">
          ${chatAvatar(c, 'xs')}<span class="label">${esc(c.title)}</span>${note}${c.file_count ? cnt(c.file_count) : '<span class="count"></span>'}</button>
          <button class="icon-btn more" data-chat-menu="${c.id}" aria-label="Actions for ${esc(c.title)}" aria-haspopup="menu">${icon('more')}</button></div>`;
      }).join('') + (withFiles.length > cap ? `<p class="more-note">${fmtNum(withFiles.length - cap)} more — type in the filter above</p>` : '') : ''}`;
  }).join('') || `<p class="more-note">${S.chats.length ? 'No chats match.' : 'Chats appear once indexing starts.'}</p>`;
}

export function renderIndexStatus() {
  const st = S.status;
  if (!st) return;
  const i = st.index;
  const up = st.search;
  const pct = i.chats_total ? Math.round((i.chats_done / i.chats_total) * 100) : 0;
  const paused = i.phase === 'paused';
  const idle = i.phase === 'idle';
  const title = paused ? 'Indexing paused' : idle ? 'Index up to date' : i.phase === 'syncing chats' ? 'Checking your chats'
    : i.phase.startsWith('rate') ? 'Waiting for Telegram' : i.phase === 'error' ? 'Indexing hit a problem' : 'Indexing files';
  let upgrade = '';
  if (up && up.state !== 'ready') {
    const p = up.total ? Math.round((up.done / up.total) * 100) : 0;
    upgrade = `<div class="idx-up"><div class="idx-line"><span>Upgrading search</span><span class="pct">${p}%</span></div><div class="bar"><i style="width:${p}%"></i></div>
      <div class="idx-sub">One-time, about a minute per 400k files. Search keeps working meanwhile.</div></div>`;
  }
  const sem = st.semantic;
  const speed = !idle && !paused && i.files_per_min ? ` · ${fmtNum(i.files_per_min)}/min` : '';
  const state = i.error || i.phase === 'error' ? 'err' : paused ? 'paused' : idle ? 'ok' : 'busy';
  const sub = idle ? `${fmtCompact(i.files)} files · ${fmtSize(i.bytes)}${i.last_sync ? ` · checked ${relTime(i.last_sync)}` : ''}`
    : `${fmtNum(i.chats_done)}/${fmtNum(i.chats_total)} chats · ${fmtCompact(i.files)} files${speed}`;
  const extra = [i.current && !idle ? `Now: ${i.current}` : '', i.phase.startsWith('rate') ? i.phase : '',
    sem && sem.enabled && sem.state === 'building' ? `Learning file meanings · ${fmtCompact(sem.count)}` : ''].filter(Boolean);
  $('#indexStatus').className = `idx${paused ? ' paused' : ''}`;
  $('#indexStatus').innerHTML = `${upgrade}<div class="idx-row"><span class="idx-dot ${state}" aria-hidden="true"></span>
      <div class="idx-text"><strong>${title}</strong><small title="${esc(sub)}">${esc(sub)}</small></div>
      ${idle ? `<button class="icon-btn tiny" data-idx="resync" title="Check all chats for new files now" aria-label="Check now">${icon('refresh')}</button>`
        : `<button class="icon-btn tiny" data-idx="${paused ? 'resume' : 'pause'}" title="${paused ? 'Resume indexing' : 'Pause indexing'}" aria-label="${paused ? 'Resume' : 'Pause'}">${icon(paused ? 'play' : 'pause')}</button>`}</div>
    ${idle ? '' : `<div class="bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"><i style="width:${pct}%"></i></div>`}
    ${extra.length ? `<div class="idx-cur" title="${esc(extra.join(' · '))}">${esc(extra.join(' · '))}</div>` : ''}
    ${i.error ? `<div class="warn idx-cur" title="${esc(i.error)}">${esc(i.error)}</div>` : ''}`;
  const acct = st.account;
  let banner = acct.status !== 'online'
    ? `<div class="banner">${esc(acct.error || 'Not connected to Telegram. Browsing and searching still work; previews and transfers wait until it reconnects.')}</div>` : '';
  if (st.drive.error && acct.status === 'online') banner += `<div class="banner">${esc(st.drive.error)}</div>`;
  if (st.thumbs_backoff > 20) banner += `<div class="banner info">Telegram asked TG Drive to slow down previews for ${st.thumbs_backoff}s. Everything else works normally.</div>`;
  $('#banner').innerHTML = banner;
}

/* ------------------------------------------------------------- menus */
export function chatMenu(anchor, cid) {
  const c = S.chatById.get(cid);
  if (!c) return;
  const post = (path, body, msg) => api(A(path), { method: 'POST', body }).then(() => { if (msg) toast(msg); return loadChats(); }).catch(fail);
  menu(anchor, [
    { label: 'Show files', icon: 'folder', onClick: () => bus.emit('go', `#chat/${cid}`) },
    { label: c.pinned ? 'Unpin' : 'Pin to top', icon: 'pin', onClick: () => post(`/chats/${cid}/pin`, { pinned: !c.pinned }) },
    { label: 'Search in this chat', icon: 'search', onClick: () => bus.emit('scope-search', { label: c.title, params: { chat_ids: String(cid) } }) },
    c.kind !== 'bot' ? { label: 'Upload files here…', icon: 'upload', onClick: () => import('./transfers.js').then((m) => m.uploadToChat(cid)) } : null,
    '-',
    { label: 'Index again from scratch', icon: 'refresh', onClick: () => post(`/chats/${cid}/rescan`, undefined, `Re-indexing “${c.title}”`) },
    {
      label: c.excluded ? 'Include in index' : 'Exclude from index', icon: c.excluded ? 'plus' : 'close', danger: !c.excluded,
      onClick: async () => {
        if (!c.excluded && !await confirmDialog(`Exclude “${c.title}”?`, 'Its files are removed from TG Drive’s index and it won’t be indexed again until you include it. Nothing changes in Telegram.', 'Exclude')) return;
        await post(`/chats/${cid}/exclude`, { excluded: !c.excluded });
        bus.emit('reload');
      },
    },
    c.username ? { label: 'Open in Telegram', icon: 'external', href: `https://t.me/${c.username}` } : null,
  ].filter(Boolean));
}

export function savedMenu(anchor, sid) {
  const s = S.saved.find((x) => x.id === sid);
  if (!s) return;
  menu(anchor, [
    { label: 'Open', icon: 'search', onClick: () => bus.emit('go', `#saved/${sid}`) },
    {
      label: 'Rename', icon: 'edit', onClick: async () => {
        const name = await promptDialog('Rename saved search', 'Name', s.name, 'Rename');
        if (!name) return;
        await api(A('/saved'), { method: 'POST', body: { ...s, name } }).catch(fail);
        loadFolders();
      },
    },
    '-',
    { label: 'Delete', icon: 'trash', danger: true, onClick: async () => { await api(A(`/saved/${sid}`), { method: 'DELETE' }).catch(fail); loadFolders(); toast('Saved search deleted'); } },
  ]);
}

export function folderMenu(anchor, id) {
  const f = S.folderById.get(id);
  if (!f) return;
  import('./folders.js').then((m) => m.folderMenu(anchor, id));
}

/* -------------------------------------------------------- interactions */
$('#chatFilter').addEventListener('input', (e) => { S.chatFilter = e.target.value; renderChats(); });
$('#chatSortBtn').addEventListener('click', (e) => {
  const set = (v) => { S.chatSort = v; pref('chatSort', v); renderChats(); };
  menu(e.currentTarget, [
    { header: 'Sort sources by' },
    { label: 'Most files', checked: S.chatSort === 'files', onClick: () => set('files') },
    { label: 'Most space', checked: S.chatSort === 'size', onClick: () => set('size') },
    { label: 'Recent activity', checked: S.chatSort === 'recent', onClick: () => set('recent') },
    { label: 'Name', checked: S.chatSort === 'name', onClick: () => set('name') },
  ], { alignRight: true });
});
S.chatSort = pref('chatSort') || 'files';

document.addEventListener('click', (e) => {
  const grp = e.target.closest('[data-group]');
  if (grp) {
    const id = grp.dataset.group;
    S.openGroups.has(id) ? S.openGroups.delete(id) : S.openGroups.add(id);
    pref('openGroups', JSON.stringify([...S.openGroups]));
    renderChats();
    return;
  }
  const tg = e.target.closest('[data-toggle]');
  if (tg) {
    const id = tg.dataset.toggle;
    if (e.target.closest('#chatSortBtn')) return;
    S.openGroups.has(id) ? S.openGroups.delete(id) : S.openGroups.add(id);
    pref('openGroups', JSON.stringify([...S.openGroups]));
    renderNav();
    return;
  }
  const cm = e.target.closest('[data-chat-menu]');
  if (cm) { e.stopPropagation(); chatMenu(cm, Number(cm.dataset.chatMenu)); return; }
  const sm = e.target.closest('[data-saved-menu]');
  if (sm) { e.stopPropagation(); savedMenu(sm, sm.dataset.savedMenu); return; }
  const idx = e.target.closest('[data-idx]');
  if (idx) api(A(`/index/${idx.dataset.idx}`), { method: 'POST' }).then(() => bus.emit('poll')).catch(fail);
});

export { folderPath };
export const kindLabel = (k) => CHAT_KIND_NAME[k] || k;
document.addEventListener('keydown', (e) => {
  const t = e.target.closest?.('.side-h[data-toggle]');
  if (t && (e.key === 'Enter' || e.key === ' ') && e.target === t) { e.preventDefault(); t.click(); }
});

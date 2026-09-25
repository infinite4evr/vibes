// File listing (grid + list), selection, keyboard, context menu, drag & drop, and file actions.
import {
  $, $$, S, A, M, api, esc, key, unkey, icon, qs, fmtSize, fmtDate, fmtDur, fmtNum, plural, KINDS, KIND_NAME,
  STREAMABLE, extColor, dateGroup, highlight, inlineSrc, thumbs, thumbUrl, bus, pref, callBridge, bridge, streamUrl,
} from './core.js';
import {
  toast, fail, menu, contextMenu, closeMenu, confirmDialog, promptDialog, folderPicker, chatPicker, tagsDialog,
  childrenOf, folderPath, descendantIds, folderColor, dialog,
} from './ui.js';

/* --------------------------------------------------------------- params */
export function viewParams(v = S.view) {
  const p = {};
  if (v.type === 'drive') {
    if (v.folderId) p.folder_id = v.folderId;
    else if (S.driveChannel) { p.chat_ids = S.driveChannel; p.filed = 0; } else return null;
  } else if (v.type === 'chat') { p.chat_ids = v.chatId; if (v.topicId) p.topic_id = v.topicId; }
  else if (v.type === 'starred') p.starred = 1;
  else if (v.type === 'recent') p.recent = 1;
  else if (v.type === 'continue') p.in_progress = 1;
  else if (v.type === 'tg') p.dialog_filter = v.filterId;
  else if (v.type === 'tag') p.tag = v.tag;
  else if (v.type === 'album') { p.chat_ids = v.chatId; p.grouped_id = v.groupedId; }
  else if (v.type === 'saved') {
    const s = S.saved.find((x) => x.id === v.savedId);
    if (!s) return null;
    Object.assign(p, s.params || {});
    if (s.q) p.q = s.q;
  } else if (v.type === 'search') {
    if (v.q) p.q = v.q;
    const sc = S.searchScope;
    if (sc) Object.assign(p, sc.params);
  }
  return p;
}
export function listParams(extra = {}) {
  const base = viewParams();
  if (!base) return null;
  const p = { ...base, ...S.adv, sort: S.sort, order: S.order, ...extra };
  if (S.kind) p.kinds = S.kind;
  if (S.view.type === 'recent' && S.sort === 'date' && !S.userSorted) p.sort = 'recent';
  if (S.view.type === 'continue' && S.sort === 'date' && !S.userSorted) p.sort = 'played';
  return p;
}
const isTextSearch = () => !!(listParams() || {}).q;

/* ---------------------------------------------------------------- loading */
let listAbort = null;
let statsAbort = null;
export function reload(keepScroll = false) {
  listAbort?.abort();
  S.items = [];
  S.byKey = new Map();
  S.next = null;
  S.done = false;
  S.loading = false;
  S.lastGroup = null;
  S.stats = null;
  S.took = null;
  S.corrected = null;
  thumbs.reset();
  $('#grid').innerHTML = '';
  $('#empty').innerHTML = '';
  if (!keepScroll) $('#content').scrollTop = 0;
  renderHeader();
  renderFolderArea();
  showSkeleton(true);
  loadMore();
  loadStats();
}

function showSkeleton(on) {
  const g = $('#grid');
  if (on && !g.children.length) {
    g.insertAdjacentHTML('beforeend', Array.from({ length: listMode() ? 10 : 18 }, () => (listMode()
      ? '<div class="row skel" aria-hidden="true"><span></span><span></span><span></span></div>'
      : '<div class="card skel" aria-hidden="true"><div class="thumb"></div><div class="card-body"><i></i><i></i></div></div>')).join(''));
  } else if (!on) $$('.skel', g).forEach((x) => x.remove());
}

export async function loadMore() {
  if (S.loading || S.done) return;
  const p = listParams(S.next ? { cursor: S.next } : {});
  const id = ++S.reqId;
  if (!p) { S.done = true; showSkeleton(false); renderEmpty(); return; }
  S.loading = true;
  $('#loadingMore').hidden = !S.items.length;
  listAbort = new AbortController();
  const isSearch = !!p.q;
  if (isSearch && !S.next) $('#searchForm').classList.add('busy');
  try {
    const r = await api(A(`/files?${qs({ ...p, limit: listMode() ? 150 : 120, slot: 'main', record: isSearch && !S.next ? 1 : '' })}`), { signal: listAbort.signal });
    if (id !== S.reqId) return;
    showSkeleton(false);
    if (!S.next) { S.took = r.took_ms; S.corrected = r.corrected || null; S.words = r.words || []; S.effectiveSort = r.sort; }
    const fresh = r.items.filter((f) => !S.byKey.has(key(f)));
    fresh.forEach((f) => { S.items.push(f); S.byKey.set(key(f), f); });
    S.next = r.next;
    S.done = !r.next;
    appendItems(fresh);
    S.loading = false;
    renderHeader();
    renderEmpty();
  } catch (e) {
    if (e.name === 'AbortError' || e.data?.superseded) return;
    if (id === S.reqId) { showSkeleton(false); S.done = true; S.loading = false; fail(e); renderEmpty(e.message); }
  } finally {
    if (id === S.reqId) { S.loading = false; $('#loadingMore').hidden = true; $('#searchForm').classList.remove('busy'); }
  }
  if (!S.done && id === S.reqId) {
    const c = $('#content');
    if (c.scrollHeight <= c.clientHeight + 400) loadMore();
  }
}

async function loadStats() {
  statsAbort?.abort();
  const p = listParams();
  const id = ++S.statsReq;
  if (!p) return;
  statsAbort = new AbortController();
  try {
    const r = await api(A(`/files/stats?${qs({ ...p, slot: 'main' })}`), { signal: statsAbort.signal });
    if (id !== S.statsReq) return;
    S.stats = r;
    renderHeader();
  } catch (e) { /* counts are optional; the list still works */ }
}

new IntersectionObserver((entries) => { if (entries[0].isIntersecting) loadMore(); },
  { root: $('#content'), rootMargin: '900px' }).observe($('#sentinel'));

/* -------------------------------------------------------------- rendering */
export const listMode = () => (S.settings.view || 'grid') === 'list';
const docIcon = (f) => {
  const ext = (f.ext || (f.kind === 'document' ? 'file' : f.kind)).slice(0, 5).toUpperCase();
  return `<span class="docicon" style="--ec:${extColor(f.ext)}"><span class="ext">${esc(ext)}</span></span>`;
};
const KIND_ICON = { audio: 'audio', voice: 'voice', video: 'video', round: 'round', gif: 'gif', photo: 'photo' };

export function thumbHtml(f, variant = 's') {
  const k = `k-${f.kind}`;
  const dur = f.duration && STREAMABLE.has(f.kind) ? `<span class="tag">${fmtDur(f.duration)}</span>` : '';
  const play = STREAMABLE.has(f.kind) ? `<span class="play-badge">${icon('play')}</span>` : '';
  const lq = f.inline ? `<img class="lqip" src="${inlineSrc(f.inline)}" alt="" aria-hidden="true">` : '';
  let fallback;
  if (f.kind === 'document' || (f.kind === 'photo' && f.ext && !['jpg', 'jpeg'].includes(f.ext) && !f.has_thumb)) fallback = docIcon(f);
  else if (f.kind === 'audio' || f.kind === 'voice') fallback = `<span class="glyph icon">${icon(KIND_ICON[f.kind])}</span>`;
  else fallback = `<span class="glyph icon">${icon(KIND_ICON[f.kind] || 'document')}</span>`;
  const img = f.has_thumb ? `<img class="real" data-src="${thumbUrl(f, variant)}" alt="" decoding="async">` : '';
  return `<div class="thumb ${k} ${f.inline ? 'has-lq' : ''}">${fallback}${lq}${img}${play}${dur}${progressHtml(f)}</div>`;
}
// How far you got (videos/audio): a bar along the bottom, or a tick when watched.
export function progressHtml(f) {
  if (!STREAMABLE.has(f.kind)) return '';
  if (f.watched) return `<span class="watched" title="Watched">${icon('check')}</span>`;
  const d = f.play_dur || f.duration;
  if (!f.play_pos || !d) return '';
  const pct = Math.max(2, Math.min(100, (f.play_pos / d) * 100));
  return `<span class="progress" title="Stopped at ${fmtDur(f.play_pos)}"><i style="width:${pct.toFixed(1)}%"></i></span>`;
}

function matchBadge(f) {
  if (!f.match || f.match === 'exact') return '';
  const label = { variant: 'Similar form', similar: 'Close spelling', related: 'Related' }[f.match];
  const tip = { variant: 'Matched a joined, split, abbreviated, transliterated or synonym form of your words',
    similar: 'Matched after correcting a likely typo, or matched all but one word', related: 'Similar in meaning (offline AI model)' }[f.match];
  return `<span class="mbadge m-${f.match}" title="${esc(tip)}">${label}</span>`;
}

function srcLine(f) {
  const folder = f.folder_id && S.folderById.get(f.folder_id);
  if (f.kind === 'audio' && (f.performer || f.audio_title)) return esc([f.performer, f.audio_title].filter(Boolean).join(' · '));
  if (S.view.type === 'drive' && folder) return '';
  return folder ? `<span class="in-folder">${icon('folder')}${esc(folder.name)}</span> ${esc(f.chat_title || '')}` : esc(f.chat_title || '');
}

export function cardHtml(f) {
  const k = key(f);
  const sel = S.selected.has(k);
  const src = srcLine(f);
  return `<div class="card ${sel ? 'sel' : ''} ${f.match && f.match !== 'exact' ? 'm-soft' : ''}" role="option" tabindex="-1" draggable="true" data-key="${k}" aria-selected="${sel}">
    ${thumbHtml(f)}
    ${f.starred ? `<span class="star-mark" title="Starred">${icon('star')}</span>` : ''}
    <button class="c-more" data-card-menu tabindex="-1" aria-label="Actions">${icon('more')}</button>
    <div class="card-body"><div class="name" title="${esc(f.name)}">${highlight(f.name, S.words)}</div>
      <div class="meta"><span>${fmtSize(f.size)}</span><span>${fmtDate(f.date)}</span>${f.tags?.length ? `<span class="tags-mini">${icon('tag')}${f.tags.length}</span>` : ''}</div>
      ${src ? `<div class="src">${src}</div>` : ''}${matchBadge(f)}</div></div>`;
}

export function rowHtml(f) {
  const k = key(f);
  const sel = S.selected.has(k);
  const ic = f.inline ? `<img class="mini lq" src="${inlineSrc(f.inline)}" alt="">` : f.kind === 'document' || !KIND_ICON[f.kind]
    ? `<span class="mini doc" style="--ec:${extColor(f.ext)}">${esc((f.ext || '').slice(0, 4).toUpperCase() || 'FILE')}</span>`
    : `<span class="mini k-${f.kind}">${icon(KIND_ICON[f.kind])}</span>`;
  return `<div class="row ${sel ? 'sel' : ''}" role="option" tabindex="-1" draggable="true" data-key="${k}" aria-selected="${sel}">
    <span class="c-name">${ic}<span class="nm" title="${esc(f.name)}">${highlight(f.name, S.words)}</span>${f.starred ? `<span class="star-mark in">${icon('star')}</span>` : ''}${matchBadge(f)}</span>
    <span class="c-src">${srcLine(f)}</span>
    <span class="c-date">${fmtDate(f.date)}</span>
    <span class="c-size">${fmtSize(f.size)}</span>
    <span class="c-kind">${f.duration && STREAMABLE.has(f.kind) ? `${f.watched ? `<span class="watched-in" title="Watched">${icon('check')}</span>` : f.play_pos ? `<small class="subtle">${fmtDur(f.play_pos)} / </small>` : ''}${fmtDur(f.duration)}` : esc(KIND_NAME[f.kind] || '')}</span>
    <button class="c-more" data-card-menu tabindex="-1" aria-label="Actions">${icon('more')}</button></div>`;
}

function groupHeader(label) { return `<div class="group-sep" role="presentation"><span>${esc(label)}</span></div>`; }

function appendItems(list) {
  const grid = $('#grid');
  grid.classList.toggle('list', listMode());
  grid.classList.toggle('grid', !listMode());
  grid.dataset.size = S.settings.grid_size || 'm';
  const grouping = S.settings.group_by_date && (S.effectiveSort || S.sort) === 'date';
  const parts = [];
  if (listMode() && !$('.list-head', grid) && list.length) parts.push(listHead());
  for (const f of list) {
    if (grouping) {
      const g = dateGroup(f.date);
      if (g !== S.lastGroup) { parts.push(groupHeader(g)); S.lastGroup = g; }
    }
    if (f.match === 'related' && S.lastMatch !== 'related' && (S.effectiveSort === 'relevance')) parts.push(groupHeader('Related by meaning'));
    S.lastMatch = f.match;
    parts.push(listMode() ? rowHtml(f) : cardHtml(f));
  }
  grid.insertAdjacentHTML('beforeend', parts.join(''));
  thumbs.observe(grid);
  if (!grid.querySelector('[tabindex="0"]')) grid.querySelector('.card, .row')?.setAttribute('tabindex', '0');
}

function listHead() {
  const col = (k, label) => `<button class="lh ${S.sort === k ? `on ${S.order}` : ''}" data-sortcol="${k}">${label}${S.sort === k ? icon('down') : ''}</button>`;
  return `<div class="list-head" role="presentation">${col('name', 'Name')}${col('chat', 'Source')}${col('date', 'Date')}${col('size', 'Size')}${col('type', 'Type')}<span></span></div>`;
}

export function rerenderItems() {
  const grid = $('#grid');
  const st = $('#content').scrollTop;
  grid.innerHTML = '';
  S.lastGroup = null;
  S.lastMatch = null;
  appendItems(S.items);
  $('#content').scrollTop = st;
}
export function refreshCard(f) {
  const el = $(`#grid [data-key="${key(f)}"]`);
  if (el) { el.outerHTML = listMode() ? rowHtml(f) : cardHtml(f); thumbs.observe($('#grid')); }
}

/* ---------------------------------------------------------------- header */
export function viewTitle() {
  const v = S.view;
  switch (v.type) {
    case 'all': return 'All files';
    case 'starred': return 'Starred';
    case 'recent': return 'Recent';
    case 'continue': return 'Continue watching';
    case 'chat': { const c = S.chatById.get(v.chatId); return c ? c.title : 'Chat'; }
    case 'tg': { const t = S.dialogFilters.find((x) => x.id === v.filterId); return t ? t.title : 'Telegram folder'; }
    case 'saved': { const s = S.saved.find((x) => x.id === v.savedId); return s ? s.name : 'Saved search'; }
    case 'tag': return `Tag: ${v.tag}`;
    case 'album': return 'Album';
    case 'search': return v.q ? `Results for “${v.q}”` : 'Filtered files';
    default: return 'My Drive';
  }
}

export function renderHeader() {
  const v = S.view;
  let crumbs;
  if (v.type === 'drive') {
    const path = folderPath(v.folderId);
    crumbs = `<button class="crumb" data-go="#drive" data-drop-folder="">My Drive</button>` + path.map((f) =>
      `<span class="sep">${icon('chevron')}</span><button class="crumb" data-go="#drive/${esc(f.id)}" data-drop-folder="${esc(f.id)}">${esc(f.name)}</button>`).join('');
  } else if (v.type === 'chat') {
    const c = S.chatById.get(v.chatId);
    crumbs = `<h1>${esc(c ? c.title : 'Chat')}</h1>${c?.username ? `<a class="subtle-link" href="https://t.me/${esc(c.username)}" target="_blank" rel="noopener">@${esc(c.username)}</a>` : ''}`;
  } else crumbs = `<h1>${esc(viewTitle())}</h1>`;
  $('#crumbs').innerHTML = crumbs;
  const st = S.stats;
  const parts = [];
  if (st) parts.push(`${plural(st.total, 'file')}, ${fmtSize(st.total_bytes)}`);
  else if (S.items.length && !S.done) parts.push(`${fmtNum(S.items.length)}+ files`);
  if (S.took != null && isTextSearch()) parts.push(`${(S.took / 1000).toFixed(2)} s`);
  $('#summary').textContent = parts.join(' · ');
  renderSearchInfo();
  // Kind tabs
  const kc = st ? st.kind_counts || {} : {};
  const all = Object.values(kc).reduce((a, b) => a + b, 0);
  $('#tabs').innerHTML = KINDS.map(([k, label]) => {
    const n = k ? (kc[k] || 0) : all;
    if (k && st && !n && S.kind !== k) return '';
    return `<button class="tab" role="tab" data-kind="${k}" aria-selected="${S.kind === k}">
      ${k ? `<span class="sw k-${k}"></span>` : ''}${label}<span class="count">${st && n ? fmtNum(n) : ''}</span></button>`;
  }).join('');
  $('#viewBtn').innerHTML = icon(listMode() ? 'grid' : 'list');
  $('#viewBtn').title = listMode() ? 'Grid view (V)' : 'List view (V)';
  const sortSel = $('#sort');
  const rel = sortSel.querySelector('[value="relevance:desc"]');
  rel.hidden = !isTextSearch();
  sortSel.value = `${S.effectiveSort === 'relevance' && isTextSearch() ? 'relevance' : S.sort}:${S.effectiveSort === 'relevance' && isTextSearch() ? 'desc' : S.order}`;
  renderSelbar();
  bus.emit('header');
}

function renderSearchInfo() {
  const el = $('#searchInfo');
  if (!isTextSearch()) { el.innerHTML = ''; el.hidden = true; return; }
  const t = S.stats?.tiers || {};
  const bits = [];
  if (t.exact) bits.push(`<span class="ti m-exact">${fmtNum(t.exact)} exact</span>`);
  if (t.variant) bits.push(`<span class="ti m-variant" title="Joined or split words, text inside words, abbreviations, other scripts and synonyms">${fmtNum(t.variant)} similar forms</span>`);
  if (t.similar) bits.push(`<span class="ti m-similar" title="Likely typos corrected, or all but one word">${fmtNum(t.similar)} close spellings</span>`);
  if (t.related) bits.push(`<span class="ti m-related" title="Similar in meaning">${fmtNum(t.related)} related</span>`);
  const dym = S.corrected ? `<span class="dym">Also showing results for <button data-dym="${esc(S.corrected)}">${esc(S.corrected)}</button></span>` : '';
  const sc = S.searchScope ? `<span class="scope-chip">${icon('filter')}In ${esc(S.searchScope.label)}<button data-scope-clear aria-label="Search everywhere">${icon('close')}</button></span>` : '';
  const exact = (S.adv.match === 'exact') ? '<span class="ti">Exact words only</span>' : '';
  el.innerHTML = `${sc}${bits.join('')}${exact}${dym}`;
  el.hidden = !el.innerHTML;
}

function folderSummary(f) {
  const subs = childrenOf(f.id).length;
  const parts = [];
  if (subs) parts.push(plural(subs, 'folder'));
  if (f.file_count) parts.push(plural(f.file_count, 'file'));
  return parts.join(', ') || 'Empty';
}

export function renderFolderArea() {
  const v = S.view;
  if (v.type !== 'drive' || S.kind || Object.keys(S.adv).length) { $('#folderArea').innerHTML = ''; return; }
  const kids = childrenOf(v.folderId);
  $('#folderArea').innerHTML = kids.length ? `<div class="section-h">Folders</div><div class="folder-grid">${kids.map((f) => `
    <div class="folder" role="button" tabindex="0" draggable="true" data-folder="${esc(f.id)}" data-drop-folder="${esc(f.id)}" aria-label="Folder ${esc(f.name)}" style="--fcol:${folderColor(f)}">
      <span class="fcount">${folderSummary(f)}${f.bytes ? ` · ${fmtSize(f.bytes)}` : ''}</span>
      <span class="fname">${esc(f.name)}</span>
      <button class="icon-btn more" data-folder-menu="${esc(f.id)}" aria-label="Folder actions" aria-haspopup="menu">${icon('more')}</button>
    </div>`).join('')}</div><div class="section-h" id="filesH">Files</div>` : '';
}

export function renderEmpty(error) {
  const el = $('#empty');
  if (S.items.length) { el.innerHTML = ''; $('#filesH')?.removeAttribute('hidden'); return; }
  if (!S.done) return;
  const v = S.view;
  const art = `<svg class="art" viewBox="0 0 30 24" aria-hidden="true" style="stroke:none"><path d="M1 4a3 3 0 0 1 3-3h7l3 3h12a3 3 0 0 1 3 3v13a3 3 0 0 1-3 3H4a3 3 0 0 1-3-3z" fill="var(--folder-soft)"/></svg>`;
  let html;
  const indexing = S.status && !['idle', 'paused'].includes(S.status.index.phase);
  if (error) html = `<h2>Couldn't load files</h2><p>${esc(error)}</p><button class="btn" data-act="retry">${icon('refresh')}Try again</button>`;
  else if (v.type === 'drive' && !v.folderId && !childrenOf(null).length) {
    html = `<h2>Your Drive is empty</h2><p>Create folders and put any file from any chat into them, or upload files. TG Drive keeps them in a private channel called “${esc(S.driveTitle)}”.</p>
      <button class="btn primary" data-act="new-folder">${icon('folderPlus')}New folder</button> <button class="btn" data-act="upload">${icon('upload')}Upload files</button>`;
  } else if (v.type === 'drive') {
    if (childrenOf(v.folderId).length && !S.kind) { el.innerHTML = ''; $('#filesH')?.setAttribute('hidden', ''); return; }
    html = '<h2>Nothing in here yet</h2><p>Drag files onto this folder, use “Move to folder” on any file, or drop files from your computer here to upload them.</p>';
  } else if (v.type === 'search' || v.type === 'saved') {
    html = `<h2>No files match</h2><p>Try fewer words, check the filters, or switch search to smart matching in Settings → Search.</p>${Object.keys(S.adv).length ? `<button class="btn" data-act="clear-filters">${icon('close')}Clear filters</button>` : ''}`;
  } else if (v.type === 'starred') html = `<h2>No starred files</h2><p>Star files you use often (press S or use the ☆ in the details panel). Stars sync to your other devices.</p>`;
  else if (v.type === 'recent') html = '<h2>Nothing recent</h2><p>Files you open, play or download show up here.</p>';
  else if (v.type === 'continue') html = '<h2>Nothing to continue</h2><p>Videos and audio you stop part-way through show up here, and play from where you left off.</p>';
  else if (indexing) html = '<h2>Still indexing</h2><p>Files appear here as TG Drive works through your chats. Large chats can take a while the first time.</p>';
  else html = `<h2>No files here</h2><p>${S.kind ? 'Nothing of this type. Try the All tab.' : 'No files match this view.'}</p>`;
  $('#filesH')?.setAttribute('hidden', '');
  el.innerHTML = `<div class="empty">${art}${html}</div>`;
}

/* -------------------------------------------------------------- selection */
export function setSelected(keys, anchor) {
  S.selected = new Set(keys);
  if (anchor !== undefined) S.anchor = anchor;
  $$('#grid .card, #grid .row').forEach((c) => {
    const on = S.selected.has(c.dataset.key);
    c.setAttribute('aria-selected', on);
    c.classList.toggle('sel', on);
  });
  renderSelbar();
  bus.emit('selection');
}
export const selectedFiles = () => [...S.selected].map((k) => S.byKey.get(k)).filter(Boolean);
export const selectedItems = () => [...S.selected].map(unkey);

export function renderSelbar() {
  const n = S.selected.size;
  const bar = $('#selbar');
  bar.hidden = !n;
  if (!n) return;
  const files = selectedFiles();
  const bytes = files.reduce((a, f) => a + (f.size || 0), 0);
  const allStarred = files.length && files.every((f) => f.starred);
  const b = (act, ic, label, cls = '') => `<button class="btn ${cls}" data-bulk="${act}" title="${label}" aria-label="${label}">${icon(ic)}<span>${label}</span></button>`;
  bar.innerHTML = `<button class="icon-btn" data-bulk="clear" aria-label="Clear selection">${icon('close')}</button>
    <span class="n">${plural(n, 'selected', 'selected')}<small>${fmtSize(bytes)}</small></span>
    ${b('download', 'download', 'Download')}${b('move', 'move', 'Move')}${b('star', 'star', allStarred ? 'Unstar' : 'Star')}
    ${b('tags', 'tag', 'Tags')}${b('copy', 'copy', 'Save copy')}${b('send', 'send', 'Send')}
    <button class="icon-btn" data-bulk="more" aria-label="More actions" aria-haspopup="menu">${icon('more')}</button>`;
}

const grid = $('#grid');
function cardFromEvent(e) { return e.target.closest('.card[data-key], .row[data-key]'); }

grid.addEventListener('click', (e) => {
  const sc = e.target.closest('[data-sortcol]');
  if (sc) {
    const k = sc.dataset.sortcol;
    if (S.sort === k) S.order = S.order === 'asc' ? 'desc' : 'asc';
    else { S.sort = k; S.order = k === 'name' || k === 'chat' || k === 'type' ? 'asc' : 'desc'; }
    S.userSorted = true;
    reload();
    return;
  }
  const card = cardFromEvent(e);
  if (!card) return;
  if (e.target.closest('[data-card-menu]')) {
    e.stopPropagation();
    if (!S.selected.has(card.dataset.key)) setSelected([card.dataset.key], card.dataset.key);
    const r = e.target.closest('[data-card-menu]').getBoundingClientRect();
    contextMenu(r.left, r.bottom + 4, fileMenuItems(selectedFiles()));
    return;
  }
  const k = card.dataset.key;
  focusCard(card);
  if (e.metaKey || e.ctrlKey) {
    const next = new Set(S.selected);
    next.has(k) ? next.delete(k) : next.add(k);
    setSelected(next, k);
  } else if (e.shiftKey && S.anchor && S.byKey.has(S.anchor)) {
    const idx = S.items.map(key);
    const [a, b] = [idx.indexOf(S.anchor), idx.indexOf(k)].sort((x, y) => x - y);
    setSelected(new Set([...S.selected, ...idx.slice(a, b + 1)]));
  } else {
    setSelected([k], k);
    bus.emit('open-details');
  }
});
grid.addEventListener('dblclick', (e) => {
  const card = cardFromEvent(e);
  if (!card) return;
  const f = S.byKey.get(card.dataset.key);
  if (f) openFile(f);
});
grid.addEventListener('contextmenu', (e) => {
  const card = cardFromEvent(e);
  if (!card) return;
  e.preventDefault();
  if (!S.selected.has(card.dataset.key)) setSelected([card.dataset.key], card.dataset.key);
  contextMenu(e.clientX, e.clientY, fileMenuItems(selectedFiles()));
});
function focusCard(card) {
  $$('#grid [tabindex="0"]').forEach((x) => x.setAttribute('tabindex', '-1'));
  card.setAttribute('tabindex', '0');
  card.focus({ preventScroll: false });
}
grid.addEventListener('keydown', (e) => {
  const card = cardFromEvent(e);
  if (!card) return;
  const k = card.dataset.key;
  if (e.key === 'Enter') { e.preventDefault(); const f = S.byKey.get(k); if (f) openFile(f); return; }
  if (e.key === ' ') {
    e.preventDefault();
    if (!S.selected.has(k)) setSelected([k], k);
    const f = S.byKey.get(k);
    if (f) import('./viewer.js').then((m) => m.openViewer(f));
    return;
  }
  const cards = $$('.card[data-key], .row[data-key]', grid);
  const i = cards.indexOf(card);
  const cols = listMode() ? 1 : Math.max(1, Math.round(grid.clientWidth / (card.offsetWidth + 12)));
  const move = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: cols, ArrowUp: -cols, Home: -1e9, End: 1e9, PageDown: cols * 4, PageUp: -cols * 4 }[e.key];
  if (move !== undefined) {
    e.preventDefault();
    const target = cards[Math.min(cards.length - 1, Math.max(0, i + move))];
    if (!target) return;
    focusCard(target);
    if (e.shiftKey) {
      const idx = S.items.map(key);
      const anchor = S.anchor || k;
      const [a, b] = [idx.indexOf(anchor), idx.indexOf(target.dataset.key)].sort((x, y) => x - y);
      setSelected(idx.slice(a, b + 1));
    } else if (!e.ctrlKey) setSelected([target.dataset.key], target.dataset.key);
  }
});

/* ---------------------------------------------------------------- actions */
export async function openFile(f) {
  if (STREAMABLE.has(f.kind) || f.kind === 'photo' || ['pdf', 'txt', 'md', 'json', 'csv', 'srt', 'log', 'png', 'jpg', 'jpeg', 'webp', 'gif'].includes((f.ext || '').toLowerCase())) {
    const m = await import('./viewer.js');
    m.openViewer(f);
  } else {
    const m = await import('./viewer.js');
    m.openViewer(f);
  }
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
function removeFromList(items) {
  const ks = new Set(items.map(([c, m]) => `${c}:${m}`));
  S.items = S.items.filter((f) => !ks.has(key(f)));
  ks.forEach((k) => { S.byKey.delete(k); $(`#grid [data-key="${k}"]`)?.remove(); });
  setSelected([]);
  renderEmpty();
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

export function fileMenuItems(files) {
  if (!files.length) return [];
  const one = files.length === 1 ? files[0] : null;
  const items = files.map((f) => [f.chat_id, f.msg_id]);
  const allStarred = files.every((f) => f.starred);
  return [
    one ? { label: STREAMABLE.has(one.kind) ? 'Play' : 'Preview', icon: STREAMABLE.has(one.kind) ? 'play' : 'eye', kbd: 'Enter', onClick: () => openFile(one) } : null,
    one ? { label: 'Open with default app', icon: 'external', onClick: () => doOpenLocal(one) } : null,
    { label: files.length > 1 ? `Download ${files.length} files` : 'Download', icon: 'download', kbd: 'D', onClick: () => doDownload(items) },
    files.length > 1 ? { label: 'Download as .zip', icon: 'download', onClick: () => doDownload(items, { zip: true, name: viewTitle() }) } : null,
    '-',
    { label: 'Move to folder…', icon: 'move', kbd: 'M', onClick: () => doMove(items, one?.folder_id) },
    { label: allStarred ? 'Remove star' : 'Star', icon: 'star', kbd: 'S', onClick: () => toggleStar(files) },
    { label: 'Tags…', icon: 'tag', kbd: 'T', onClick: () => editTags(files) },
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
    one && S.view.type !== 'chat' ? { label: 'Show chat', icon: 'chevron', onClick: () => bus.emit('go', `#chat/${one.chat_id}`) } : null,
    one?.grouped_id ? { label: 'Show album', icon: 'photo', onClick: () => bus.emit('go', `#album/${one.chat_id}/${one.grouped_id}`) } : null,
    one ? { label: 'Find related files', icon: 'sparkle', onClick: () => bus.emit('go', `#search/${encodeURIComponent(one.name.replace(/\.[^.]+$/, '').replace(/[_\-.]+/g, ' '))}`) } : null,
    '-',
    { label: 'Hide from TG Drive (keep in Telegram)', icon: 'close', onClick: () => doForget(items) },
    { label: 'Delete from Telegram', icon: 'trash', danger: true, kbd: 'Del', onClick: () => doDelete(items) },
  ].filter(Boolean);
}

$('#selbar').addEventListener('click', (e) => {
  const b = e.target.closest('[data-bulk]');
  if (!b) return;
  const items = selectedItems();
  const files = selectedFiles();
  ({
    download: () => doDownload(items),
    move: () => doMove(items),
    copy: () => doCopy(items),
    send: () => doSend(items),
    star: () => toggleStar(files),
    tags: () => editTags(files),
    clear: () => setSelected([]),
    more: () => menu(b, fileMenuItems(files), { alignRight: true }),
  })[b.dataset.bulk]?.();
});

/* ---------------------------------------------------------- drag and drop */
let dragKeys = null;
let draggingFolder = null;
grid.addEventListener('dragstart', (e) => {
  const card = cardFromEvent(e);
  if (!card) return;
  if (!S.selected.has(card.dataset.key)) setSelected([card.dataset.key], card.dataset.key);
  dragKeys = [...S.selected];
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', `${dragKeys.length} file(s)`);
  const ghost = document.createElement('div');
  ghost.className = 'drag-ghost';
  ghost.textContent = dragKeys.length === 1 ? (S.byKey.get(dragKeys[0])?.name || '1 file') : `${dragKeys.length} files`;
  document.body.append(ghost);
  e.dataTransfer.setDragImage(ghost, 10, 10);
  setTimeout(() => ghost.remove(), 0);
});
grid.addEventListener('dragend', () => { dragKeys = null; $$('.drop-hover').forEach((x) => x.classList.remove('drop-hover')); });
document.addEventListener('dragstart', (e) => {
  const f = e.target.closest?.('.folder[data-folder]');
  if (f) { draggingFolder = f.dataset.folder; e.dataTransfer.setData('text/plain', 'folder'); }
});
document.addEventListener('dragend', () => { draggingFolder = null; });
document.addEventListener('dragover', (e) => {
  const target = e.target.closest?.('[data-drop-folder]');
  $$('.drop-hover').forEach((x) => { if (x !== target) x.classList.remove('drop-hover'); });
  if (target && (dragKeys || draggingFolder)) {
    if (draggingFolder && (target.dataset.dropFolder === draggingFolder || descendantIds(draggingFolder).has(target.dataset.dropFolder))) return;
    e.preventDefault();
    target.classList.add('drop-hover');
    return;
  }
  const isFiles = e.dataTransfer?.types?.includes('Files');
  if (isFiles && !dragKeys && e.target.closest?.('#main')) {
    e.preventDefault();
    const folderId = S.view.type === 'drive' ? S.view.folderId : null;
    const ov = $('#dropOverlay');
    ov.textContent = `Drop to upload to ${folderId ? `“${S.folderById.get(folderId)?.name}”` : 'My Drive'}`;
    ov.hidden = false;
  }
});
document.addEventListener('dragleave', (e) => {
  if (!e.relatedTarget || !$('#main').contains(e.relatedTarget)) $('#dropOverlay').hidden = true;
});
document.addEventListener('drop', async (e) => {
  $('#dropOverlay').hidden = true;
  const target = e.target.closest?.('[data-drop-folder]');
  $$('.drop-hover').forEach((x) => x.classList.remove('drop-hover'));
  if (target && dragKeys) {
    e.preventDefault();
    const items = dragKeys.map(unkey);
    dragKeys = null;
    return placeInto(items, target.dataset.dropFolder || null);
  }
  if (target && draggingFolder) {
    e.preventDefault();
    const id = draggingFolder;
    draggingFolder = null;
    try {
      await api(A(`/folders/${id}`), { method: 'PATCH', body: { parent_id: target.dataset.dropFolder || null } });
      toast('Folder moved', { action: 'Undo', onAction: undoLast });
      bus.emit('drive-changed');
    } catch (err) { fail(err); }
    return;
  }
  if (e.dataTransfer?.files?.length && e.target.closest?.('#main')) {
    e.preventDefault();
    const folderId = S.view.type === 'drive' ? S.view.folderId : null;
    const uris = (e.dataTransfer.getData('text/uri-list') || '').split(/\r?\n/).filter((u) => u.startsWith('file://'));
    const m = await import('./transfers.js');
    if (bridge.ready && uris.length) m.uploadPaths(uris.map((u) => decodeURIComponent(u.slice(7))), folderId);
    else m.uploadDropped(e.dataTransfer, folderId);
  }
});

export function toggleView() {
  const view = listMode() ? 'grid' : 'list';
  S.settings.view = view;
  api('/api/settings', { method: 'PATCH', body: { view } }).catch(() => {});
  rerenderItems();
  renderHeader();
}
export function setDensity(size) {
  S.settings.grid_size = size;
  api('/api/settings', { method: 'PATCH', body: { grid_size: size } }).catch(() => {});
  $('#grid').dataset.size = size;
}
export { pref, streamUrl, M };

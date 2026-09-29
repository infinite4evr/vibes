// File listing (virtual grid + list), album stacks, selection, keyboard, drag & drop.
// File actions live in actions.js (re-exported here for older imports).
import {
  $, $$, S, A, api, esc, key, unkey, icon, qs, fmtSize, fmtDate, fmtDur, fmtNum, plural, KINDS,
  STREAMABLE, extColor, dateGroup, highlight, inlineSrc, thumbs, thumbUrl, bus, pref, streamUrl, M, friendlyName, waveHtml, copiesParam, fmtCompact,
} from './core.js';
import { contextMenu, childrenOf, folderPath, descendantIds, toast, fail } from './ui.js';
import { VGrid } from './vgrid.js';
import { activeColumns, cellHtml, headHtml, applyTemplate, columnsDialog } from './columns.js';
import * as actions from './actions.js';

export * from './actions.js';
export { waveHtml };

/* --------------------------------------------------------------- params */
export function folderRules(folder) {
  if (!folder?.rules) return null;
  try { return typeof folder.rules === 'string' ? JSON.parse(folder.rules) : folder.rules; } catch { return null; }
}

export function viewParams(v = S.view) {
  const p = {};
  if (v.type === 'drive') {
    const fo = v.folderId && S.folderById.get(v.folderId);
    const rules = fo && fo.kind === 'smart' ? folderRules(fo) : null;
    if (rules) { Object.assign(p, rules.params || {}); if (rules.q) p.q = rules.q; }
    else if (v.folderId) p.folder_id = v.folderId;
    else if (S.driveChannel) { p.chat_ids = S.driveChannel; p.filed = 0; } else return null;
  } else if (v.type === 'chat') { p.chat_ids = v.chatId; if (v.topicId) p.topic_id = v.topicId; }
  else if (v.type === 'starred') p.starred = 1;
  else if (v.type === 'recent') p.recent = 1;
  else if (v.type === 'continue') p.in_progress = 1;
  else if (v.type === 'tg') p.dialog_filter = v.filterId;
  else if (v.type === 'tag') p.tag = v.tag;
  else if (v.type === 'subject') p.subject = v.subject;
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
  if (S.view.type !== 'album') p.copies = copiesParam();
  if (S.view.type === 'recent' && S.sort === 'date' && !S.userSorted) p.sort = 'recent';
  if (S.view.type === 'continue' && S.sort === 'date' && !S.userSorted) p.sort = 'played';
  return p;
}
const isTextSearch = () => !!(listParams() || {}).q;
const isSmartFolder = () => S.view.type === 'drive' && S.folderById.get(S.view.folderId)?.kind === 'smart';

/* -------------------------------------------------------------- entries */
// An entry is one card or row: a file, or an album (files sent together) shown as one stack.
export const listMode = () => (S.settings.view || 'grid') === 'list';
const stacking = () => S.settings.stack_albums !== false && !listMode() && S.view.type !== 'album';
S.entries = [];
S.entryOf = new Map();   // file key -> entry index

function addEntries(list) {
  const from = S.entries.length ? S.entries.length - 1 : 0;
  const stack = stacking();
  for (const f of list) {
    const last = S.entries[S.entries.length - 1];
    if (stack && f.grouped_id && last && last.f.grouped_id === f.grouped_id && last.f.chat_id === f.chat_id) {
      (last.stack ||= [last.f]).push(f);
      S.entryOf.set(key(f), S.entries.length - 1);
    } else {
      S.entries.push({ f });
      S.entryOf.set(key(f), S.entries.length - 1);
    }
  }
  return from;
}
function rebuildEntries() {
  S.entries = [];
  S.entryOf = new Map();
  addEntries(S.items);
}
export const entryKeys = (e) => (e.stack || [e.f]).map(key);

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
  S.stats = null;
  S.took = null;
  S.corrected = null;
  thumbs.reset();
  rebuildEntries();
  showLoadError(null);
  $('#stickyHead').classList.remove('on');
  $('#empty').innerHTML = '';
  if (!keepScroll) $('#content').scrollTop = 0;
  renderHeader();
  renderFolderArea();
  setupGrid();
  showSkeleton(true);
  loadMore();
  loadStats();
}

// A fresh list fades in row by row instead of popping in all at once.
let appearTimer = 0;
function appear() {
  const g = $('#grid');
  clearTimeout(appearTimer);
  g.classList.remove('appear');
  void g.offsetWidth;
  g.classList.add('appear');
  appearTimer = setTimeout(() => g.classList.remove('appear'), 1100);
}

function showSkeleton(on) {
  const sk = $('#skeleton');
  if (on && !S.items.length) {
    sk.className = listMode() ? 'skeleton list' : 'skeleton grid';
    sk.dataset.size = S.settings.grid_size || 'm';
    sk.innerHTML = Array.from({ length: listMode() ? 10 : 12 }, () => (listMode()
      ? '<div class="row skel" aria-hidden="true"><span></span><span></span><span></span></div>'
      : '<div class="card skel" aria-hidden="true"><div class="thumb"></div><div class="card-body"><i></i><i></i></div></div>')).join('');
    sk.hidden = false;
  } else if (!on) { sk.hidden = true; sk.innerHTML = ''; }
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
    const r = await api(A(`/files?${qs({ ...p, limit: listMode() ? 200 : 160, slot: 'main', record: isSearch && !S.next && S.view.type === 'search' ? 1 : '' })}`), { signal: listAbort.signal });
    if (id !== S.reqId) return;
    showSkeleton(false);
    if (!S.next) { S.took = r.took_ms; S.corrected = r.corrected || null; S.words = r.words || []; S.effectiveSort = r.sort; }
    const fresh = r.items.filter((f) => !S.byKey.has(key(f)));
    fresh.forEach((f) => { S.items.push(f); S.byKey.set(key(f), f); });
    S.next = r.next;
    S.done = !r.next;
    const firstPage = !S.entries.length;
    const from = addEntries(fresh);
    if (firstPage && fresh.length) appear();
    vg.update(S.entries, from);
    S.loading = false;
    renderHeader();
    renderEmpty();
  } catch (e) {
    if (e.name === 'AbortError' || e.data?.superseded) return;
    if (id === S.reqId) {
      showSkeleton(false); S.done = true; S.loading = false;
      // A search the server can't read (400) is explained in place, not as a failure to retry.
      if (e.status === 400 && S.view.type === 'search') renderEmpty(e.message, 'query');
      else if (S.items.length) showLoadError(e);   // a later page: the list stays, with "Try again" at its end
      else renderEmpty(e.message);
    }
  } finally {
    if (id === S.reqId) { S.loading = false; $('#loadingMore').hidden = true; $('#searchForm').classList.remove('busy'); }
  }
  if (!S.done && id === S.reqId) {
    const c = $('#content');
    if (c.scrollHeight <= c.clientHeight + 600) loadMore();
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

// A later page that couldn't load: say so at the end of the list, with "Try again" (loading stops until then).
function showLoadError(e) {
  let el = $('#loadMoreError');
  if (!e) { el?.remove(); return; }
  if (!el) {
    el = document.createElement('div');
    el.id = 'loadMoreError';
    el.className = 'load-error';
    el.setAttribute('role', 'alert');
    $('#loadingMore').after(el);
  }
  el.innerHTML = `<span>${icon('info')}Couldn't load more files: ${esc(e.message || String(e))}</span><button class="btn sm" data-act="load-more">${icon('refresh')}Try again</button>`;
}
export function retryLoadMore() {
  showLoadError(null);
  S.done = false;
  loadMore();
}

new IntersectionObserver((entries) => { if (entries[0].isIntersecting) loadMore(); },
  { root: $('#content'), rootMargin: '1400px' }).observe($('#sentinel'));

/* -------------------------------------------------------------- rendering */
const docIcon = (f) => {
  const ext = (f.ext || (f.kind === 'document' ? 'file' : f.kind)).slice(0, 5).toUpperCase();
  return `<span class="docicon" style="--ec:${extColor(f.ext)}"><span class="ext">${esc(ext)}</span></span>`;
};
const KIND_ICON = { audio: 'audio', voice: 'voice', video: 'video', round: 'round', gif: 'gif', photo: 'photo' };

export function thumbHtml(f, variant = 's') {
  const k = `k-${f.kind}`;
  if ((f.kind === 'voice' || (f.kind === 'audio' && !f.has_thumb))) {
    return `<div class="thumb ${k} wave-thumb">${waveHtml(f)}<span class="play-badge">${icon('play')}</span>${f.duration ? `<span class="tag">${fmtDur(f.duration)}</span>` : ''}${progressHtml(f)}</div>`;
  }
  const dur = f.duration && STREAMABLE.has(f.kind) ? `<span class="tag">${fmtDur(f.duration)}</span>` : '';
  const play = STREAMABLE.has(f.kind) ? `<span class="play-badge">${icon('play')}</span>` : '';
  const lq = f.inline ? `<img class="lqip" src="${inlineSrc(f.inline)}" alt="" aria-hidden="true">` : '';
  let fallback;
  if (f.kind === 'document' || (f.kind === 'photo' && f.ext && !['jpg', 'jpeg'].includes(f.ext) && !f.has_thumb)) fallback = docIcon(f);
  else fallback = `<span class="glyph icon">${icon(KIND_ICON[f.kind] || 'document')}</span>`;
  const pdfPage = !f.has_thumb && variant === 's' && (f.ext || '').toLowerCase() === 'pdf' && S.settings.pdf_card_previews !== false;
  const img = f.has_thumb ? `<img class="real" data-src="${thumbUrl(f, variant)}" alt="" decoding="async">`
    : pdfPage ? `<img class="real pdfp" data-src="${M(`/docthumb/${f.chat_id}/${f.msg_id}`)}" data-pdf="${f.chat_id}:${f.msg_id}" alt="" decoding="async">` : '';
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

export function subjectInfo(id) {
  if (!id) return null;
  return (S.subjects || []).find((s) => s.id === id) || { id, name: id.replace(/_/g, ' '), emoji: '' };
}

// Where a file is from, when that tells you something: not inside a chat's own view, not "Deleted account".
const NO_SOURCE = new Set(['', 'Deleted account', 'Deleted Account']);
function srcLine(f) {
  const folder = f.folder_id && S.folderById.get(f.folder_id);
  if (f.kind === 'audio' && (f.performer || f.audio_title)) return esc([f.performer, f.audio_title].filter(Boolean).join(' · '));
  const chat = S.view.type === 'chat' || S.view.type === 'album' || NO_SOURCE.has(f.chat_title || '') ? '' : esc(f.chat_title || '');
  if (S.view.type === 'drive' && folder && !isSmartFolder()) return chat;
  return folder ? `<span class="in-folder">${icon('folder')}${esc(folder.name)}</span>${chat ? ` ${chat}` : ''}` : chat;
}
const stackNoun = (members) => (members.every((x) => x.kind === 'photo') ? 'photos' : members.every((x) => x.kind === 'video') ? 'videos' : 'files');

const SAMPLE = { chat_id: 0, msg_id: 0, kind: 'document', name: 'Sample name that is long enough to wrap onto two lines.pdf', ext: 'pdf', size: 1, date: 0, chat_title: 'Chat' };

export function cardHtml(f, entry = null, i = 0) {
  f ||= SAMPLE;
  const k = key(f);
  const members = entry?.stack;
  const keys = members ? members.map(key) : [k];
  const sel = keys.every((x) => S.selected.has(x)) && S.selected.size > 0;
  const subj = subjectInfo(f.subject);
  const stackBadge = members ? `<span class="stack-n" title="${members.length} files sent together">${icon('stack')}${members.length}</span>` : '';
  const friendly = friendlyName(f);
  const name = members ? esc(friendly || f.name) : friendly ? `<span class="nm-auto">${esc(friendly)}</span>` : highlight(f.name, S.words);
  const src = srcLine(f);
  return `<div class="card ${sel ? 'sel' : ''} ${members ? 'stack' : ''} ${f.match && f.match !== 'exact' ? 'm-soft' : ''}" role="option" tabindex="-1" draggable="true" data-key="${k}" data-i="${i}" aria-selected="${sel}">
    ${thumbHtml(f)}${matchBadge(f)}${stackBadge}
    ${f.starred ? `<span class="star-mark" title="Starred">${icon('star')}</span>` : ''}
    <div class="c-acts"><button class="c-q ${f.starred ? 'on' : ''}" data-quick="star" tabindex="-1" title="${f.starred ? 'Remove star' : 'Star'}" aria-label="${f.starred ? 'Remove star' : 'Star'}">${icon('star')}</button><button class="c-q" data-quick="download" tabindex="-1" title="Download" aria-label="Download">${icon('download')}</button><button class="c-more" data-card-menu tabindex="-1" aria-label="Actions" title="More">${icon('more')}</button></div>
    ${f.copies > 1 ? `<span class="copies-mini on-thumb" title="${f.copies} copies of this file${copiesParam() === 'hide' ? ' (the others are hidden)' : ''}">${icon('dupes')}${f.copies}</span>` : ''}
    <div class="card-body"><div class="name" title="${esc(f.name)}">${members ? `<span class="stack-label">${members.length} ${stackNoun(members)} · </span>` : ''}${name}</div>
      <div class="src-line" title="${esc(f.chat_title || '')}">${src || ''}</div>
      <div class="meta"><span>${fmtSize(members ? members.reduce((a, x) => a + (x.size || 0), 0) : f.size)}</span>${friendly && !members ? '' : `<span>${fmtDate(f.date)}</span>`}${f.tags?.length ? `<span class="tags-mini" title="${esc(f.tags.join(', '))}">${icon('tag')}${f.tags.length}</span>` : ''}${subj ? `<span class="subj-mini" title="${esc(subj.name)}">${subj.emoji || icon('book')}</span>` : ''}</div></div></div>`;
}

export function rowHtml(f, entry = null, i = 0) {
  f ||= SAMPLE;
  const k = key(f);
  const sel = S.selected.has(k);
  const ic = f.inline ? `<img class="mini lq" src="${inlineSrc(f.inline)}" alt="">` : f.kind === 'document' || !KIND_ICON[f.kind]
    ? `<span class="mini doc" style="--ec:${extColor(f.ext)}">${esc((f.ext || '').slice(0, 4).toUpperCase() || 'FILE')}</span>`
    : `<span class="mini k-${f.kind}">${icon(KIND_ICON[f.kind])}</span>`;
  const subj = subjectInfo(f.subject);
  const cells = activeColumns().map((c) => (c === 'name'
    ? `<span class="c-name">${ic}<span class="nm" title="${esc(f.name)}">${friendlyName(f) ? `<span class="nm-auto">${esc(friendlyName(f))}</span>` : highlight(f.name, S.words)}</span>${f.starred ? `<span class="star-mark in">${icon('star')}</span>` : ''}${f.copies > 1 ? `<span class="copies-mini" title="${f.copies} copies of this file">${icon('dupes')}${f.copies}</span>` : ''}${matchBadge(f)}</span>`
    : cellHtml(c, f, subj ? `${subj.emoji ? `${subj.emoji} ` : ''}${esc(subj.name)}` : ''))).join('');
  return `<div class="row ${sel ? 'sel' : ''}" role="option" tabindex="-1" draggable="true" data-key="${k}" data-i="${i}" aria-selected="${sel}">
    ${cells}<button class="c-more" data-card-menu tabindex="-1" aria-label="Actions">${icon('more')}</button></div>`;
}

function headOf(e, prev) {
  const sortKey = S.effectiveSort || S.sort;
  if (S.settings.group_by_date && sortKey === 'date' && !isTextSearch()) {
    const g = dateGroup(e.f.date);
    if (!prev || dateGroup(prev.f.date) !== g) return g;
  }
  if (e.f.match === 'related' && sortKey === 'relevance' && (!prev || prev.f.match !== 'related')) return 'Related by meaning';
  return null;
}

const grid = $('#grid');
const vg = new VGrid($('#content'), grid, {
  renderEntry: (e, i, probe) => (listMode() ? rowHtml(e?.f, e, i) : cardHtml(e?.f, e, i)),
  renderHead: (label) => `<div class="group-sep" role="presentation"><span>${esc(label)}</span></div>`,
  headOf,
  onRender: () => {
    thumbs.observe(grid);
    const focusKey = S.focusKey;
    if (focusKey) {
      const el = grid.querySelector(`[data-key="${CSS.escape(focusKey)}"]`);
      if (el && el.getAttribute('tabindex') !== '0') { $$('#grid [tabindex="0"]').forEach((x) => x.setAttribute('tabindex', '-1')); el.setAttribute('tabindex', '0'); }
    } else if (!grid.querySelector('[tabindex="0"]')) grid.querySelector('.card, .row')?.setAttribute('tabindex', '0');
  },
});

function setupGrid() {
  const size = S.settings.grid_size || 'm';
  grid.dataset.size = size;
  vg.setMode(listMode() ? 'list' : 'grid', `${size}:${activeColumns().join(',')}`);
  const lh = $('#listHead');
  lh.hidden = !listMode();
  if (listMode()) { applyTemplate(); lh.innerHTML = headHtml(); }
  vg.reset(S.entries);
}

export function rerenderItems() {
  const st = $('#content').scrollTop;
  rebuildEntries();
  setupGrid();
  $('#content').scrollTop = st;
  vg.render();
}
export function refreshCard(f) {
  const i = S.entryOf.get(key(f));
  if (i !== undefined) vg.refreshEntry(i);
}
bus.on('columns-changed', () => { if (listMode()) rerenderItems(); });

/* -------------------------------------------- scrolling: compact header, pinned date header */
const content = $('#content');
let scrollTick = 0;
content.addEventListener('scroll', () => {
  if (!scrollTick) scrollTick = requestAnimationFrame(() => { scrollTick = 0; onListScroll(); });
}, { passive: true });
export function onListScroll() {
  $('#listView').classList.toggle('scrolled', content.scrollTop > 24);
  const sh = $('#stickyHead');
  const offset = listMode() ? 38 : 0;
  const y = content.getBoundingClientRect().top - grid.getBoundingClientRect().top + offset;
  let label = null;
  if (vg.rows.length && y > 0) {
    for (let k = vg.rowAt(y); k >= 0; k--) {
      const r = vg.rows[k];
      if (r.type === 'head') { if (r.top < y - 2) label = r.label; break; }
    }
  }
  sh.classList.toggle('on', !!label);
  sh.classList.toggle('in-list', listMode());
  if (label) sh.firstElementChild.textContent = label;
}
bus.on('subjects-loaded', () => vg.refreshAll());

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
    case 'subject': { const s = subjectInfo(v.subject); return s ? s.name : 'Subject'; }
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
    const cur = path[path.length - 1];
    crumbs = `<button class="crumb" data-go="#drive" data-drop-folder="">My Drive</button>` + path.map((f) =>
      `<span class="sep">${icon('chevron')}</span><button class="crumb" data-go="#drive/${esc(f.id)}" data-drop-folder="${esc(f.id)}">${f.emoji ? `<span class="crumb-emo">${esc(f.emoji)}</span>` : ''}${esc(f.name)}</button>`).join('');
    if (cur?.kind) crumbs += `<span class="rule-chip ${cur.kind}" title="${cur.kind === 'smart' ? 'Smart folder: shows every file that matches its rule' : 'Files matching the rule are filed here automatically'}" data-folder-rules="${esc(cur.id)}">${icon(cur.kind === 'smart' ? 'sparkle' : 'wand')}${cur.kind === 'smart' ? 'Smart' : 'Auto-filing'}</span>`;
  } else if (v.type === 'chat') {
    const c = S.chatById.get(v.chatId);
    crumbs = `<h1>${esc(c ? c.title : 'Chat')}</h1>${c?.username ? `<a class="subtle-link" href="https://t.me/${esc(c.username)}" target="_blank" rel="noopener">@${esc(c.username)}</a>` : ''}`;
  } else if (v.type === 'subject') {
    const s = subjectInfo(v.subject);
    crumbs = `<h1>${s?.emoji ? `<span class="crumb-emo">${s.emoji}</span>` : ''}${esc(viewTitle())}</h1><span class="rule-chip smart" title="Subjects are set automatically from names and captions">${icon('sparkle')}Subject</span>`;
  } else crumbs = `<h1>${esc(viewTitle())}</h1>`;
  $('#crumbs').innerHTML = crumbs;
  const st = S.stats;
  const parts = [];
  if (st) parts.push(`${plural(st.total, 'file')}, ${fmtSize(st.total_bytes)}`);
  else if (S.items.length && !S.done) parts.push(`${fmtNum(S.items.length)}+ files`);
  if (S.took != null && isTextSearch() && !isSmartFolder()) parts.push(`${(S.took / 1000).toFixed(2)} s`);
  $('#summary').textContent = parts.join(' · ');
  renderSearchInfo();
  const kc = st ? st.kind_counts || {} : {};
  const all = Object.values(kc).reduce((a, b) => a + b, 0);
  $('#tabs').innerHTML = KINDS.map(([k, label]) => {
    const n = k ? (kc[k] || 0) : all;
    if (k && st && !n && S.kind !== k) return '';
    return `<button class="tab" role="tab" data-kind="${k}" aria-selected="${S.kind === k}">
      ${k ? `<span class="sw k-${k}"></span>` : ''}${label}<span class="count">${st && n ? fmtNum(n) : ''}</span></button>`;
  }).join('');
  $('#viewBtn').innerHTML = `${icon(listMode() ? 'list' : 'grid')}<span class="vb-label">View</span>${icon('chevronDown')}`;
  const cb = $('#copiesBtn');
  if (cb) {
    const hiding = copiesParam() === 'hide';
    const extra = S.status?.dupes?.extra || 0;
    cb.innerHTML = icon('dupes');
    cb.classList.toggle('on', hiding);
    cb.setAttribute('aria-pressed', String(hiding));
    cb.hidden = S.view.type === 'album';
    cb.title = hiding ? `Duplicates hidden: one card per file${extra ? ` (${fmtCompact(extra)} extra copies folded away)` : ''}. Click to show every copy.`
      : 'Showing every copy. Click to hide duplicates (one card per file).';
    cb.setAttribute('aria-label', hiding ? 'Show duplicates' : 'Hide duplicates');
  }
  $('#viewBtn').title = 'View options: grid or list, card size, folders, sidebar';
  $('#viewBtn').setAttribute('aria-haspopup', 'menu');
  const sortSel = $('#sort');
  const rel = sortSel.querySelector('[value="relevance:desc"]');
  rel.hidden = !isTextSearch();
  sortSel.value = `${S.effectiveSort === 'relevance' && isTextSearch() ? 'relevance' : S.sort}:${S.effectiveSort === 'relevance' && isTextSearch() ? 'desc' : S.order}`;
  if (listMode() && $('#listHead').innerHTML) $('#listHead').innerHTML = headHtml();
  renderSelbar();
  bus.emit('header');
}

function renderSearchInfo() {
  const el = $('#searchInfo');
  if (!isTextSearch() || isSmartFolder()) { el.innerHTML = ''; el.hidden = true; return; }
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

export function renderFolderArea() {
  import('./folders.js').then((m) => m.renderFolderArea());
}

export function renderEmpty(error, why) {
  const el = $('#empty');
  if (S.items.length) { el.innerHTML = ''; $('#filesH')?.removeAttribute('hidden'); $('#listHead').hidden = !listMode(); return; }
  if (!S.done) return;
  $('#listHead').hidden = true;   // column headings over an empty list are just noise
  const v = S.view;
  const art = `<svg class="art" viewBox="0 0 30 24" aria-hidden="true" style="stroke:none"><path d="M1 4a3 3 0 0 1 3-3h7l3 3h12a3 3 0 0 1 3 3v13a3 3 0 0 1-3 3H4a3 3 0 0 1-3-3z" fill="var(--folder-soft)"/></svg>`;
  let html;
  const indexing = S.status && !['idle', 'paused'].includes(S.status.index.phase);
  const fo = v.type === 'drive' && v.folderId ? S.folderById.get(v.folderId) : null;
  if (error && why === 'query') html = `<h2>Check the search</h2><p>${esc(error)}</p>`;
  else if (error) html = `<h2>Couldn't load files</h2><p>${esc(error)}</p><button class="btn" data-act="retry">${icon('refresh')}Try again</button>`;
  else if (v.type === 'drive' && !v.folderId && !childrenOf(null).length) {
    html = `<h2>Your Drive is empty</h2><p>Create folders and put any file from any chat into them, or upload files. TG Drive keeps them in a private channel called “${esc(S.driveTitle)}”.</p>
      <button class="btn primary" data-act="new-folder">${icon('folderPlus')}New folder</button> <button class="btn" data-act="upload">${icon('upload')}Upload files</button>`;
  } else if (fo?.kind === 'smart') {
    html = `<h2>No files match this smart folder</h2><p>Its rule doesn't match anything yet. Files appear here as soon as they do.</p><button class="btn" data-folder-rules="${esc(fo.id)}">${icon('sparkle')}Edit the rule</button>`;
  } else if (v.type === 'drive') {
    if (childrenOf(v.folderId).length && !S.kind) { el.innerHTML = ''; $('#filesH')?.setAttribute('hidden', ''); return; }
    html = fo?.kind === 'auto'
      ? `<h2>Nothing filed here yet</h2><p>Files that match this folder's rule and aren't in another folder are moved here automatically.</p><button class="btn" data-folder-rules="${esc(fo.id)}">${icon('wand')}Rule and “File now”</button>`
      : '<h2>Nothing in here yet</h2><p>Drag files onto this folder, use “Move to folder” on any file, paste files with Ctrl+V, or drop files from your computer here to upload them.</p>';
  } else if (v.type === 'search' || v.type === 'saved') {
    html = `<h2>No files match</h2><p>${(S.settings.search_mode || 'smart') === 'smart' && S.adv.match !== 'exact' ? 'Try fewer or different words, or check the filters.' : 'Try fewer words, check the filters, or switch search to smart matching in Settings → Search.'}</p>${Object.keys(S.adv).length ? `<button class="btn" data-act="clear-filters">${icon('close')}Clear filters</button>` : ''}`;
  } else if (v.type === 'starred') html = `<h2>No starred files</h2><p>Star files you use often (press S or use the ☆ in the details panel). Stars sync to your other devices.</p>`;
  else if (v.type === 'recent') html = '<h2>Nothing recent</h2><p>Files you open, play or download show up here.</p>';
  else if (v.type === 'continue') html = '<h2>Nothing to continue</h2><p>Videos and audio you stop part-way through show up here, and play from where you left off.</p>';
  else if (v.type === 'subject') html = '<h2>No files with this subject</h2><p>Subjects are found from file names, captions and chat names while TG Drive indexes. Add your own keywords in Settings → Subjects.</p>';
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
    const e = S.entries[+c.dataset.i];
    const ks = e ? entryKeys(e) : [c.dataset.key];
    const on = ks.every((k) => S.selected.has(k));
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
  document.body.classList.toggle('has-selbar', n > 0);
  if (!n) {
    if (!bar.hidden && !bar.classList.contains('leaving')) {
      bar.classList.add('leaving');
      setTimeout(() => { if (!S.selected.size) { bar.hidden = true; bar.classList.remove('leaving'); } }, 170);
    }
    return;
  }
  bar.classList.remove('leaving');
  bar.hidden = false;
  const files = selectedFiles();
  const bytes = files.reduce((a, f) => a + (f.size || 0), 0);
  const allStarred = files.length && files.every((f) => f.starred);
  const b = (act, ic, label) => `<button class="btn" data-bulk="${act}" title="${label}" aria-label="${label}">${icon(ic)}<span>${label}</span></button>`;
  bar.innerHTML = `<button class="icon-btn" data-bulk="clear" aria-label="Clear selection">${icon('close')}</button>
    <span class="n">${plural(n, 'selected', 'selected')}<small>${fmtSize(bytes)}</small></span>
    ${b('download', 'download', 'Download')}${b('move', 'move', 'Move')}${b('star', 'star', allStarred ? 'Unstar' : 'Star')}
    ${b('tags', 'tag', 'Tags')}${b('copy', 'copy', 'Save copy')}${b('send', 'send', 'Send')}
    <button class="icon-btn" data-bulk="more" aria-label="More actions" aria-haspopup="menu">${icon('more')}</button>`;
}

function cardFromEvent(e) { return e.target.closest('.card[data-key], .row[data-key]'); }
const entryAt = (el) => S.entries[+el.dataset.i];
function keysBetween(a, b) {
  const [x, y] = [Math.min(a, b), Math.max(a, b)];
  return S.entries.slice(x, y + 1).flatMap(entryKeys);
}

// Double clicks are recognised by time and place, not by element: the first click opens the details panel,
// the grid reflows to make room, and the second click lands on a freshly drawn card (or between cards).
let lastClick = { key: null, t: 0, x: 0, y: 0 };
function openEntryKey(k) {
  const i = S.entryOf.get(k);
  const ent = i === undefined ? null : S.entries[i];
  if (ent?.stack) { bus.emit('go', `#album/${ent.f.chat_id}/${ent.f.grouped_id}`); return; }
  const f = S.byKey.get(k);
  if (f) actions.openFile(f);
}
// (The selection bar can appear too, moving everything down: the second click may even land on the tabs.)
$('#listView').addEventListener('click', (e) => {
  const now = performance.now();
  if (lastClick.key && now - lastClick.t < 500 && Math.abs(e.clientX - lastClick.x) < 10
      && Math.abs(e.clientY - lastClick.y) < 10 && !e.shiftKey && !e.ctrlKey && !e.metaKey
      && !e.target.closest('[data-card-menu]')) {
    e.stopPropagation();
    e.preventDefault();
    const k = lastClick.key;
    lastClick = { key: null, t: 0, x: 0, y: 0 };
    openEntryKey(k);
  }
}, true);
grid.addEventListener('click', (e) => {
  const card = cardFromEvent(e);
  if (!card) return;
  lastClick = { key: card.dataset.key, t: performance.now(), x: e.clientX, y: e.clientY };
  const ent = entryAt(card);
  const ks = ent ? entryKeys(ent) : [card.dataset.key];
  const quick = e.target.closest('[data-quick]');
  if (quick) {
    e.stopPropagation();
    lastClick = { key: null, t: 0, x: 0, y: 0 };
    const files = ks.map((x) => S.byKey.get(x)).filter(Boolean);
    if (quick.dataset.quick === 'star') actions.toggleStar(files).then(() => files.forEach(refreshCard));
    else actions.doDownload(files.map((x) => [x.chat_id, x.msg_id]));
    return;
  }
  if (e.target.closest('[data-card-menu]')) {
    e.stopPropagation();
    if (!ks.every((k) => S.selected.has(k))) setSelected(ks, card.dataset.key);
    const r = e.target.closest('[data-card-menu]').getBoundingClientRect();
    contextMenu(r.left, r.bottom + 4, fileMenuItemsFor(selectedFiles()));
    return;
  }
  const k = card.dataset.key;
  focusEntry(+card.dataset.i, false);
  if (e.metaKey || e.ctrlKey) {
    const next = new Set(S.selected);
    const on = ks.every((x) => next.has(x));
    ks.forEach((x) => (on ? next.delete(x) : next.add(x)));
    setSelected(next, k);
  } else if (e.shiftKey && S.anchor && S.entryOf.has(S.anchor)) {
    setSelected(new Set([...S.selected, ...keysBetween(S.entryOf.get(S.anchor), +card.dataset.i)]));
  } else {
    setSelected(ks, k);
    bus.emit('open-details');
  }
});
function fileMenuItemsFor(files) { return actions.fileMenuItems(files); }

grid.addEventListener('contextmenu', (e) => {
  const card = cardFromEvent(e);
  if (!card) return;
  e.preventDefault();
  const ent = entryAt(card);
  const ks = ent ? entryKeys(ent) : [card.dataset.key];
  if (!ks.every((k) => S.selected.has(k))) setSelected(ks, card.dataset.key);
  contextMenu(e.clientX, e.clientY, fileMenuItemsFor(selectedFiles()));
});
document.addEventListener('click', (e) => {
  const sc = e.target.closest('#listHead [data-sortcol]');
  if (sc) {
    const k = sc.dataset.sortcol;
    if (S.sort === k) S.order = S.order === 'asc' ? 'desc' : 'asc';
    else { S.sort = k; S.order = k === 'name' || k === 'chat' || k === 'type' || k === 'ext' ? 'asc' : 'desc'; }
    S.userSorted = true;
    reload();
    return;
  }
  if (e.target.closest('#listHead [data-columns]')) columnsDialog();
});
document.addEventListener('contextmenu', (e) => {
  if (!e.target.closest('#listHead')) return;
  e.preventDefault();
  columnsDialog();
});

function focusEntry(i, scroll = true) {
  const ent = S.entries[i];
  if (!ent) return;
  S.focusKey = key(ent.f);
  if (scroll) vg.scrollToEntry(i);
  const el = grid.querySelector(`[data-i="${i}"]`);
  $$('#grid [tabindex="0"]').forEach((x) => x.setAttribute('tabindex', '-1'));
  if (el) { el.setAttribute('tabindex', '0'); el.focus({ preventScroll: true }); }
}
grid.addEventListener('keydown', (e) => {
  const card = cardFromEvent(e);
  if (!card) return;
  const i = +card.dataset.i;
  const ent = S.entries[i];
  if (e.key === 'Enter') {
    e.preventDefault();
    if (ent?.stack) bus.emit('go', `#album/${ent.f.chat_id}/${ent.f.grouped_id}`);
    else { const f = S.byKey.get(card.dataset.key); if (f) actions.openFile(f); }
    return;
  }
  if (e.key === ' ') {
    e.preventDefault();
    if (!S.selected.has(card.dataset.key)) setSelected(entryKeys(ent), card.dataset.key);
    const f = S.byKey.get(card.dataset.key);
    if (f) import('./viewer.js').then((m) => m.openViewer(f));
    return;
  }
  let target = null;
  const cols = vg.columns();
  if (e.key === 'ArrowRight') target = i + 1;
  else if (e.key === 'ArrowLeft') target = i - 1;
  else if (e.key === 'ArrowDown') target = vg.vertical(i, 1);
  else if (e.key === 'ArrowUp') target = vg.vertical(i, -1);
  else if (e.key === 'Home') target = 0;
  else if (e.key === 'End') target = S.entries.length - 1;
  else if (e.key === 'PageDown') target = i + cols * 4;
  else if (e.key === 'PageUp') target = i - cols * 4;
  if (target === null) return;
  e.preventDefault();
  target = Math.max(0, Math.min(S.entries.length - 1, target));
  focusEntry(target);
  const tEnt = S.entries[target];
  if (e.shiftKey) {
    const anchorI = S.entryOf.get(S.anchor) ?? i;
    setSelected(keysBetween(anchorI, target));
  } else if (!e.ctrlKey) setSelected(entryKeys(tEnt), key(tEnt.f));
  if (target >= S.entries.length - cols * 3) loadMore();
});

export function removeFromList(items) {
  const ks = new Set(items.map(([c, m]) => `${c}:${m}`));
  S.items = S.items.filter((f) => !ks.has(key(f)));
  ks.forEach((k) => S.byKey.delete(k));
  rebuildEntries();
  vg.reset(S.entries);
  setSelected([]);
  renderEmpty();
}

$('#selbar').addEventListener('click', (e) => {
  const b = e.target.closest('[data-bulk]');
  if (b) actions.bulkAction(b.dataset.bulk, b);
});

/* ---------------------------------------------------------- drag and drop */
// Files dragged between panes of the split view (separate pages) travel as application/x-tgdrive-items.
const ITEMS_MIME = 'application/x-tgdrive-items';
let dragKeys = null;
let draggingFolder = null;
grid.addEventListener('dragstart', (e) => {
  const card = cardFromEvent(e);
  if (!card) return;
  const ks = entryKeys(entryAt(card) || { f: S.byKey.get(card.dataset.key) });
  if (!ks.every((k) => S.selected.has(k))) setSelected(ks, card.dataset.key);
  dragKeys = [...S.selected];
  e.dataTransfer.effectAllowed = 'copyMove';
  e.dataTransfer.setData('text/plain', `${dragKeys.length} file(s)`);
  e.dataTransfer.setData(ITEMS_MIME, JSON.stringify({ account: S.aid, items: dragKeys.map(unkey) }));
  const ghost = document.createElement('div');
  ghost.className = 'drag-ghost';
  ghost.textContent = dragKeys.length === 1 ? (S.byKey.get(dragKeys[0])?.name || '1 file') : `${dragKeys.length} files`;
  document.body.append(ghost);
  e.dataTransfer.setDragImage(ghost, 10, 10);
  setTimeout(() => ghost.remove(), 0);
});
grid.addEventListener('dragend', () => { dragKeys = null; $$('.drop-hover').forEach((x) => x.classList.remove('drop-hover')); });
document.addEventListener('dragstart', (e) => {
  const f = e.target.closest?.('.fitem[data-folder]');
  if (f) { draggingFolder = f.dataset.folder; e.dataTransfer.setData('text/plain', 'folder'); }
});
document.addEventListener('dragend', () => { draggingFolder = null; });
const hasItems = (e) => e.dataTransfer?.types?.includes(ITEMS_MIME);
// Smart folders show the files that match their rule: files can't be dropped into one (a folder can).
const isSmartId = (id) => !!id && S.folderById.get(id)?.kind === 'smart';
// Where files dropped on the list go: the folder shown, or My Drive when that is a smart folder (or not a folder).
export const dropFolder = () => (S.view.type === 'drive' && !isSmartId(S.view.folderId) ? S.view.folderId : null);
const dropLabel = (id) => (id ? `“${S.folderById.get(id)?.name}”` : 'My Drive');
document.addEventListener('dragover', (e) => {
  const target = e.target.closest?.('[data-drop-folder]');
  $$('.drop-hover').forEach((x) => { if (x !== target) x.classList.remove('drop-hover'); });
  if (target && (dragKeys || draggingFolder || hasItems(e))) {
    if (draggingFolder && (target.dataset.dropFolder === draggingFolder || descendantIds(draggingFolder).has(target.dataset.dropFolder))) return;
    if (!draggingFolder && isSmartId(target.dataset.dropFolder)) return;
    e.preventDefault();
    target.classList.add('drop-hover');
    return;
  }
  if (hasItems(e) && !dragKeys && e.target.closest?.('#main') && S.view.type === 'drive' && !isSmartId(S.view.folderId)) {
    e.preventDefault();   // from the other pane: drop anywhere to move into this folder
    const ov = $('#dropOverlay');
    ov.textContent = `Move here: ${dropLabel(S.view.folderId)}`;
    ov.hidden = false;
    return;
  }
  const isFiles = e.dataTransfer?.types?.includes('Files');
  if (isFiles && !dragKeys && e.target.closest?.('#main')) {
    e.preventDefault();
    const ov = $('#dropOverlay');
    ov.textContent = `Drop to upload to ${dropLabel(dropFolder())}`;
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
    if (isSmartId(target.dataset.dropFolder)) return undefined;
    e.preventDefault();
    const items = dragKeys.map(unkey);
    dragKeys = null;
    return actions.placeInto(items, target.dataset.dropFolder || null);
  }
  if (!dragKeys && hasItems(e)) {
    e.preventDefault();
    try {
      const data = JSON.parse(e.dataTransfer.getData(ITEMS_MIME));
      if (data.account !== S.aid) return toast('Files can only move within the same account.', { err: true });
      const dest = target ? (target.dataset.dropFolder || null) : dropFolder();
      if (isSmartId(dest)) return undefined;
      return actions.placeInto(data.items, dest);
    } catch { return undefined; }
  }
  if (target && draggingFolder) {
    e.preventDefault();
    const id = draggingFolder;
    draggingFolder = null;
    try {
      await api(A(`/folders/${id}`), { method: 'PATCH', body: { parent_id: target.dataset.dropFolder || null } });
      toast('Folder moved', { action: 'Undo', onAction: actions.undoLast });
      bus.emit('drive-changed');
    } catch (err) { fail(err); }
    return;
  }
  if (e.dataTransfer?.files?.length && e.target.closest?.('#main')) {
    e.preventDefault();
    const folderId = dropFolder();
    const uris = (e.dataTransfer.getData('text/uri-list') || '').split(/\r?\n/).filter((u) => u.startsWith('file://'));
    const m = await import('./transfers.js');
    const { bridge } = await import('./core.js');
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
  grid.dataset.size = size;
  rerenderItems();
}
export function scrollToTop() { $('#content').scrollTop = 0; }
export { pref, streamUrl, M, unkey, qs };

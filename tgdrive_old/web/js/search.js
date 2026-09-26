// Search box: live results, suggestions, filter chips, advanced filters, saved searches.
import { $, $$, S, A, api, esc, icon, qs, debounce, fmtNum, SOURCES, CHAT_KIND_NAME, bus, pref } from './core.js';
import { toast, fail, menu, promptDialog, chatAvatar, folderPicker, chatPicker } from './ui.js';

const input = $('#q');
const box = $('#suggest');
let sugAbort = null;
let sugIndex = -1;
let sugItems = [];
let sugOff = false;   // set after a search is submitted, until the user types again

/* ------------------------------------------------------------ live search */
function goSearch(q, { replace = false } = {}) {
  const h = `#search/${encodeURIComponent(q)}`;
  if (location.hash === h) return bus.emit('reload');
  if (replace && S.view.type === 'search') history.replaceState(null, '', h);
  else history.pushState(null, '', h);
  bus.emit('route');
}
const live = debounce(() => {
  const q = input.value.trim();
  if (S.settings.search_live === false) return;
  if (!q && !Object.keys(S.adv).length) {
    if (S.view.type === 'search') { history.replaceState(null, '', S.lastBrowse || '#drive'); bus.emit('route'); }
    return;
  }
  if (q.length < 2 && !/[ऀ-ॿ]/.test(q) && !Object.keys(S.adv).length) return;
  goSearch(q, { replace: true });
}, 260);

input.addEventListener('input', () => {
  sugOff = false;
  $('#searchClear').hidden = !input.value;
  live();
  suggest();
});
input.addEventListener('focus', () => { sugOff = false; suggest(); });
input.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowDown' && !box.hidden) { e.preventDefault(); moveSug(1); return; }
  if (e.key === 'ArrowUp' && !box.hidden) { e.preventDefault(); moveSug(-1); return; }
  if (e.key === 'Escape') {
    if (!box.hidden) { hideSug(); e.stopPropagation(); return; }
    if (input.value) {
      input.value = '';
      $('#searchClear').hidden = true;
      live.cancel();
      if (S.view.type === 'search' && !Object.keys(S.adv).length) { history.replaceState(null, '', S.lastBrowse || '#drive'); bus.emit('route'); }
      e.stopPropagation();
      return;
    }
    input.blur();
  }
  if (e.key === 'Enter' && sugIndex >= 0 && !box.hidden) { e.preventDefault(); pickSug(sugItems[sugIndex]); }
});
$('#searchForm').addEventListener('submit', (e) => {
  e.preventDefault();
  live.cancel();
  sugFetch.cancel();
  sugAbort?.abort();
  sugOff = true;
  hideSug();
  toggleAdv(false);
  const q = input.value.trim();
  if (!q && !Object.keys(S.adv).length) return bus.emit('go', S.lastBrowse || '#drive');
  goSearch(q);
});
$('#searchClear').addEventListener('click', () => {
  input.value = '';
  $('#searchClear').hidden = true;
  input.focus();
  live();
});

/* ------------------------------------------------------------ suggestions */
const sugFetch = debounce(async (q) => {
  sugAbort?.abort();
  sugAbort = new AbortController();
  try {
    const r = await api(A(`/suggest?${qs({ q })}`), { signal: sugAbort.signal });
    if (sugOff || document.activeElement !== input || input.value.trim() !== q) return;
    renderSug(q, r);
  } catch { /* ignore */ }
}, 120);
function suggest() {
  if (!S.aid) return;
  sugFetch(input.value.trim());
}
function hideSug() { box.hidden = true; sugIndex = -1; input.setAttribute('aria-expanded', 'false'); }
export function closeSuggestions() { sugOff = true; sugFetch.cancel(); sugAbort?.abort(); hideSug(); }
function moveSug(d) {
  if (!sugItems.length) return;
  sugIndex = (sugIndex + d + sugItems.length) % sugItems.length;
  $$('.sg-item', box).forEach((el, i) => el.classList.toggle('on', i === sugIndex));
  $$('.sg-item', box)[sugIndex]?.scrollIntoView({ block: 'nearest' });
}
function lastWordReplaced(insert) {
  const v = input.value.trimEnd();
  const i = v.lastIndexOf(' ');
  return `${i >= 0 ? v.slice(0, i + 1) : ''}${insert} `;
}
function renderSug(q, r) {
  sugItems = [];
  const sec = (title, rows) => (rows.length ? `<div class="sg-h">${esc(title)}</div>${rows.join('')}` : '');
  const item = (html, data) => { sugItems.push(data); return `<button type="button" class="sg-item" data-si="${sugItems.length - 1}">${html}</button>`; };
  const parts = [];
  if (r.did_you_mean && q) parts.push(sec('Did you mean', [item(`${icon('wand')}<span>${esc(r.did_you_mean)}</span>`, { type: 'q', q: r.did_you_mean })]));
  if (r.operators?.length) parts.push(sec('Filter', r.operators.map((o) => item(`${icon('filter')}<span>${esc(o.label)}</span><code>${esc(o.insert)}</code>`, { type: 'op', insert: o.insert }))));
  if (r.files?.length) parts.push(sec('Files', r.files.map((f) => item(`<span class="sg-kind k-${f.kind}">${icon(f.kind === 'document' ? 'document' : f.kind === 'photo' ? 'photo' : f.kind === 'audio' ? 'audio' : 'video')}</span><span class="grow">${esc(f.name)}</span><small>${esc(f.chat_title || '')}</small>`, { type: 'file', f }))));
  if (r.chats?.length) parts.push(sec('Search inside a chat', r.chats.map((c) => item(`${chatAvatar(c, 'xs')}<span class="grow">${esc(c.title)}</span><small>${fmtNum(c.file_count)} files</small>`, { type: 'chat', c }))));
  if (r.folders?.length) parts.push(sec('Folders', r.folders.map((f) => item(`<span class="fold-ic">${icon('folder')}</span><span class="grow">${esc(f.name)}</span>`, { type: 'folder', f }))));
  if (r.saved?.length) parts.push(sec('Saved searches', r.saved.map((s) => item(`${icon('star')}<span class="grow">${esc(s.name)}</span><small>${esc(s.q || '')}</small>`, { type: 'saved', s }))));
  if (r.history?.length) parts.push(sec(q ? 'Earlier searches' : 'Recent searches', r.history.map((h) => item(`${icon('history')}<span class="grow">${esc(h.q)}</span><span class="sg-x" data-forget="${esc(h.q)}" title="Remove">${icon('close')}</span>`, { type: 'q', q: h.q }))));
  if (!q) parts.push(`<div class="sg-tip">Tip: search understands joined and split words (test series = testseries), typos, abbreviations like PYQ, Hindi ↔ Latin script, and related meanings. Add filters like <code>type:video</code>, <code>ext:pdf</code>, <code>size&gt;50mb</code>, <code>in:"chat"</code>, <code>after:2024</code>. <button type="button" class="linkish" data-open-adv>All filters</button></div>`);
  box.innerHTML = parts.join('');
  sugIndex = -1;
  box.hidden = !parts.length;
  input.setAttribute('aria-expanded', String(!box.hidden));
}
function pickSug(s) {
  if (!s) return;
  hideSug();
  if (s.type !== 'op') { sugOff = true; sugFetch.cancel(); sugAbort?.abort(); }
  if (s.type === 'q') { input.value = s.q; $('#searchClear').hidden = false; goSearch(s.q); }
  else if (s.type === 'op') { input.value = lastWordReplaced(s.insert); input.focus(); live(); }
  else if (s.type === 'file') {
    bus.emit('open-file-ref', s.f);
  } else if (s.type === 'chat') {
    const words = input.value.trim().split(/\s+/).filter((w) => !s.c.title.toLowerCase().includes(w.toLowerCase())).join(' ');
    setScope({ label: s.c.title, params: { chat_ids: String(s.c.id) } }, words);
  } else if (s.type === 'folder') { input.value = ''; bus.emit('go', `#drive/${s.f.id}`); }
  else if (s.type === 'saved') { input.value = ''; bus.emit('go', `#saved/${s.s.id}`); }
}
box.addEventListener('mousedown', (e) => e.preventDefault());
box.addEventListener('click', async (e) => {
  const fg = e.target.closest('[data-forget]');
  if (fg) {
    e.stopPropagation();
    await api(A(`/history?${qs({ q: fg.dataset.forget })}`), { method: 'DELETE' }).catch(() => {});
    suggest();
    return;
  }
  if (e.target.closest('[data-open-adv]')) { hideSug(); toggleAdv(true); return; }
  const b = e.target.closest('[data-si]');
  if (b) pickSug(sugItems[+b.dataset.si]);
});
input.addEventListener('blur', () => setTimeout(hideSug, 120));

/* ------------------------------------------------------------------ scope */
export function setScope(scope, q = input.value.trim()) {
  S.searchScope = scope;
  input.value = q;
  $('#searchClear').hidden = !q;
  goSearch(q);
  if (!q) input.focus();
}
bus.on('scope-search', (sc) => setScope(sc, ''));
document.addEventListener('click', (e) => {
  if (e.target.closest('[data-scope-clear]')) { S.searchScope = null; bus.emit('reload'); }
  const d = e.target.closest('[data-dym]');
  if (d) { input.value = d.dataset.dym; goSearch(d.dataset.dym); }
});

/* ----------------------------------------------------------- filter chips */
const DATE_PRESETS = [['', 'Any time'], ['today', 'Today'], ['7d', 'Last 7 days'], ['30d', 'Last 30 days'], ['3m', 'Last 3 months'], ['1y', 'Last year']];
const SIZE_PRESETS = [['', 'Any size'], ['0:1mb', 'Under 1 MB'], ['1mb:10mb', '1–10 MB'], ['10mb:100mb', '10–100 MB'], ['100mb:1g', '100 MB – 1 GB'], ['1g:', 'Over 1 GB']];
export function renderChips() {
  const a = S.adv;
  const dateLabel = a.date_from ? (DATE_PRESETS.find(([k]) => k && a._date === k)?.[1] || `${a.date_from}${a.date_to ? ` → ${a.date_to}` : ''}`) : 'Any time';
  const sizeLabel = a.size_min || a.size_max ? (SIZE_PRESETS.find(([k]) => k === `${a.size_min || '0'}:${a.size_max || ''}`)?.[1] || `${a.size_min || '0'}–${a.size_max || '∞'}`) : 'Any size';
  const src = a.chat_kinds ? SOURCES.find(([k]) => k === a.chat_kinds)?.[1] : 'Any source';
  const chat = a.chat_ids ? (S.chatById.get(Number(a.chat_ids))?.title || 'Chat') : 'Any chat';
  const chip = (id, label, on) => `<button class="fchip ${on ? 'on' : ''}" data-chip="${id}">${esc(label)}${icon('down')}</button>`;
  const toggle = (id, label, on) => `<button class="fchip toggle ${on ? 'on' : ''}" data-tchip="${id}">${on ? icon('check') : ''}${esc(label)}</button>`;
  const any = Object.keys(a).filter((k) => !k.startsWith('_')).length;
  $('#chips').innerHTML = `${chip('date', dateLabel, !!a.date_from)}${chip('size', sizeLabel, !!(a.size_min || a.size_max))}
    ${S.view.type !== 'chat' ? chip('source', src, !!a.chat_kinds) + chip('chat', chat, !!a.chat_ids) : ''}
    ${toggle('starred', 'Starred', a.starred === '1')}${toggle('has_caption', 'Has caption', a.has_caption === '1')}${toggle('forwarded', 'Forwarded', a.forwarded === '1')}
    ${S.view.type === 'search' ? toggle('match', 'Exact words', a.match === 'exact') : ''}
    <button class="fchip ghost" data-open-adv>${icon('sliders')}More filters</button>
    ${any ? `<button class="fchip ghost" data-clear-filters>${icon('close')}Clear</button>` : ''}
    ${S.view.type === 'search' ? `<button class="fchip ghost" data-save-search>${icon('star')}Save search</button>` : ''}`;
  $('#filtersOn').hidden = !any;
  // The chips live behind one "Filters" button; they stay open while any filter is on.
  const open = S.showFilters || !!any;
  $('#chips').hidden = !open;
  const fb = $('#filtersBtn');
  if (fb) {
    fb.innerHTML = `${icon('filter')}<span>Filters</span>${any ? `<span class="fcount">${any}</span>` : ''}`;
    fb.setAttribute('aria-expanded', String(open));
    fb.classList.toggle('on', open);
  }
}
S.showFilters = pref('showFilters') === '1';
export function toggleFilters() {
  S.showFilters = !($('#filtersBtn')?.getAttribute('aria-expanded') === 'true');
  if (!S.showFilters && Object.keys(S.adv).some((k) => !k.startsWith('_'))) S.showFilters = true;   // can't hide active filters
  pref('showFilters', S.showFilters ? '1' : '0');
  renderChips();
}
document.addEventListener('click', (e) => { if (e.target.closest('#filtersBtn')) toggleFilters(); });
function setAdv(changes) {
  for (const [k, v] of Object.entries(changes)) { if (v === '' || v == null) delete S.adv[k]; else S.adv[k] = v; }
  bus.emit('reload');
}
document.addEventListener('click', async (e) => {
  const c = e.target.closest('[data-chip]');
  if (c) {
    const id = c.dataset.chip;
    if (id === 'date') {
      menu(c, [...DATE_PRESETS.map(([k, l]) => ({ label: l, checked: (S.adv._date || '') === k && (k || !S.adv.date_from), onClick: () => setAdv({ date_from: k || '', date_to: '', _date: k }) })), '-',
        { label: 'Custom range…', icon: 'calendar', onClick: () => toggleAdv(true) }]);
    } else if (id === 'size') {
      menu(c, SIZE_PRESETS.map(([k, l]) => ({ label: l, checked: `${S.adv.size_min || '0'}:${S.adv.size_max || ''}` === k || (!k && !S.adv.size_min && !S.adv.size_max), onClick: () => { const [lo, hi] = k.split(':'); setAdv({ size_min: lo && lo !== '0' ? lo : '', size_max: hi || '' }); } })));
    } else if (id === 'source') {
      menu(c, [{ label: 'Any source', checked: !S.adv.chat_kinds, onClick: () => setAdv({ chat_kinds: '' }) },
        ...SOURCES.map(([k, l]) => ({ label: l, checked: S.adv.chat_kinds === k, onClick: () => setAdv({ chat_kinds: k }) }))]);
    } else if (id === 'chat') {
      const r = await chatPicker({ title: 'Only files from', okLabel: 'Filter' });
      if (r) setAdv({ chat_ids: String(r.chatId) });
    }
    return;
  }
  const t = e.target.closest('[data-tchip]');
  if (t) {
    const id = t.dataset.tchip;
    if (id === 'match') setAdv({ match: S.adv.match === 'exact' ? '' : 'exact' });
    else setAdv({ [id]: S.adv[id] === '1' ? '' : '1' });
    return;
  }
  if (e.target.closest('[data-clear-filters]') || e.target.closest('[data-act="clear-filters"]')) { S.adv = {}; bus.emit('reload'); return; }
  if (e.target.closest('[data-open-adv]')) { toggleAdv(true); return; }
  if (e.target.closest('[data-save-search]')) saveSearch();
});

export async function saveSearch() {
  const q = input.value.trim();
  const name = await promptDialog('Save this search', 'Name', q || 'My search', 'Save', { help: 'Saved searches appear in the sidebar and sync to your other devices. They always show current results.' });
  if (!name) return;
  const params = { ...S.adv };
  delete params._date;
  if (S.searchScope) Object.assign(params, S.searchScope.params);
  if (S.kind) params.kinds = S.kind;
  try {
    const s = await api(A('/saved'), { method: 'POST', body: { name, q, params } });
    toast(`Saved “${name}”`);
    bus.emit('drive-changed');
    bus.emit('go', `#saved/${s.id}`);
  } catch (e) { fail(e); }
}

/* -------------------------------------------------------- advanced panel */
function renderAdv() {
  const a = S.adv;
  const chatName = a.chat_ids ? (S.chatById.get(Number(a.chat_ids))?.title || '') : '';
  const sel = (name, opts) => `<select name="${name}">${opts.map(([v, l]) => `<option value="${v}" ${String(a[name] || '') === v ? 'selected' : ''}>${l}</option>`).join('')}</select>`;
  $('#adv').innerHTML = `<div class="adv-grid">
    <label class="field"><span>File extensions</span><input type="text" name="exts" placeholder="pdf, zip, mp4" value="${esc(a.exts || '')}"></label>
    <label class="field"><span>Kind of chat</span>${sel('chat_kinds', [['', 'Any chat'], ...SOURCES.map(([id, l]) => [id, l])])}</label>
    <label class="field"><span>In chat</span><input type="text" name="chat" list="chatNames" placeholder="Any chat" value="${esc(chatName)}"></label>
    <label class="field"><span>Sent by</span><input type="text" name="sender" placeholder="Name of the sender" value="${esc(a.sender || '')}"></label>
    <div class="field"><span>Size</span><div class="pair"><input type="text" name="size_min" placeholder="At least, e.g. 10mb" aria-label="Minimum size" value="${esc(a.size_min || '')}"><input type="text" name="size_max" placeholder="At most, e.g. 1g" aria-label="Maximum size" value="${esc(a.size_max || '')}"></div></div>
    <div class="field"><span>Date sent</span><div class="pair"><input type="date" name="date_from" aria-label="From date" value="${esc(/^\d{4}-\d\d-\d\d$/.test(a.date_from || '') ? a.date_from : '')}"><input type="date" name="date_to" aria-label="To date" value="${esc(a.date_to || '')}"></div></div>
    <div class="field"><span>Duration</span><div class="pair"><input type="text" name="dur_min" placeholder="At least, e.g. 5m" aria-label="Minimum duration" value="${esc(a.dur_min || '')}"><input type="text" name="dur_max" placeholder="At most, e.g. 1h" aria-label="Maximum duration" value="${esc(a.dur_max || '')}"></div></div>
    <label class="field"><span>Tag</span><input type="text" name="tag" list="tagNames" placeholder="Any tag" value="${esc(a.tag || '')}"></label>
    <label class="field"><span>Folder</span>${sel('filed', [['', 'Anywhere'], ['1', 'In a folder'], ['0', 'Not in a folder']])}</label>
    <label class="field"><span>Forwarded</span>${sel('forwarded', [['', 'Either'], ['1', 'Only forwarded'], ['0', 'Not forwarded']])}</label>
    <label class="field"><span>Sent by me</span>${sel('mine', [['', 'Anyone'], ['1', 'Only mine'], ['0', 'Others']])}</label>
    <label class="field"><span>Caption</span>${sel('has_caption', [['', 'Either'], ['1', 'Has a caption'], ['0', 'No caption']])}</label>
    <label class="field"><span>Preview</span>${sel('has_thumb', [['', 'Either'], ['1', 'Has a preview'], ['0', 'No preview']])}</label>
    <label class="field"><span>Matching</span>${sel('match', [['', 'Smart (similar forms, typos, related)'], ['exact', 'Exact words only']])}</label>
  </div>
  <datalist id="chatNames">${S.chats.slice(0, 3000).map((c) => `<option value="${esc(c.title)}">`).join('')}</datalist>
  <datalist id="tagNames">${S.tags.map((t) => `<option value="${esc(t.tag)}">`).join('')}</datalist>
  <details><summary>Search operators you can type</summary><div class="ops">
    <code>type:video,gif</code><span>photo, video, document, audio, voice, round, gif</span>
    <code>ext:pdf</code><span>file extension, comma-separated for several</span>
    <code>in:"Chat name"</code><span>chat title or @username contains the text</span>
    <code>from:priya</code><span>sender or forwarded-from name</span>
    <code>source:channel</code><span>channel, group, private, bot or saved</span>
    <code>size&gt;50mb</code><span>also size&lt;1g, size&gt;=500k; a bare number means MB</span>
    <code>dur&gt;10m</code><span>duration for audio and video; also 1:30 or 90</span>
    <code>w&gt;=1920 h&gt;=1080</code><span>minimum width and height</span>
    <code>after:2024-06</code><span>also before:, date:2023, date:today, or relative after:7d, 2w, 3m, 1y</span>
    <code>folder:tax</code><span>files in a folder whose name contains the text</span>
    <code>tag:exam</code><span>files with a tag; also has:tags, has:note</span>
    <code>topic:"Doubts"</code><span>forum topic title (groups with topics)</span>
    <code>is:starred</code><span>also is:forwarded, is:mine, is:filed, is:unfiled, is:album</span>
    <code>has:caption</code><span>also has:thumb</span>
    <code>name:"exact"</code><span>only in the file name; caption:"…" only in captions</span>
    <code>"exact words"</code><span>phrase match</span>
    <code>-word</code><span>leave out matches; works with operators too, e.g. -type:gif</span>
    <code>match:exact</code><span>turn off smart matching for this search</span>
  </div></details>
  <div class="adv-foot"><button type="button" class="btn ghost" id="advReset">Clear filters</button><span class="spacer"></span>
    <button type="button" class="btn" id="advCancel">Cancel</button><button type="button" class="btn primary" id="advApply">Search</button></div>`;
  $('#advApply').addEventListener('click', applyAdv);
  $('#advCancel').addEventListener('click', () => toggleAdv(false));
  $('#advReset').addEventListener('click', () => { S.adv = {}; renderAdv(); renderChips(); });
}
function applyAdv() {
  const next = {};
  $$('#adv input[name], #adv select[name]').forEach((el) => { if (el.value.trim()) next[el.name] = el.value.trim(); });
  if (next.chat) {
    const match = S.chats.find((c) => c.title.toLowerCase() === next.chat.toLowerCase());
    if (match) next.chat_ids = String(match.id);
    else input.value = `${input.value.replace(/\s*in:"[^"]*"/g, '').trim()} in:"${next.chat}"`.trim();
    delete next.chat;
  }
  S.adv = next;
  toggleAdv(false);
  const q = input.value.trim();
  if (!q && !Object.keys(S.adv).length) return bus.emit('go', S.lastBrowse || '#drive');
  goSearch(q);
}
export function toggleAdv(show) {
  $('#adv').hidden = !show;
  $('#advBtn').setAttribute('aria-expanded', String(show));
  if (show) { hideSug(); renderAdv(); $('#adv input')?.focus(); }
}
$('#advBtn').addEventListener('click', () => toggleAdv($('#adv').hidden));
document.addEventListener('mousedown', (e) => {
  if (!$('#adv').hidden && !e.target.closest('#searchForm') && !e.target.closest('.menu')) toggleAdv(false);
});
export function focusSearch() { input.focus(); input.select(); }
export { pref, folderPicker, CHAT_KIND_NAME };

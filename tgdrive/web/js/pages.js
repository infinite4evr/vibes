// Full-page tools: Storage, Duplicates, Index manager, Activity, Settings.
import { $, $$, S, A, api, esc, icon, fmtSize, fmtNum, fmtDate, plural, relTime, CHAT_KIND_NAME, KIND_NAME, SOURCES, bus, key, bridge, callBridge, qs, extColor, M } from './core.js';
import { toast, fail, confirmDialog, dialog, promptDialog, chatAvatar } from './ui.js';

const page = () => $('#pageView');
const head = (title, sub = '', right = '') => `<div class="page-head"><div><h1>${esc(title)}</h1>${sub ? `<p>${sub}</p>` : ''}</div><div class="page-right">${right}</div></div>`;

export function renderPage(type, arg) {
  // Settings sections switch in place; other pages show a loader until their data is in.
  const pv = page();
  if (type !== 'settings' || !pv.querySelector('.settings')) pv.innerHTML = '<div class="page-loading big">Loading…</div>';
  ({ storage, duplicates, index: indexManager, activity, settings: settingsPage })[type]?.(arg);
}

/* ---------------------------------------------------------------- storage */
async function storage() {
  page().innerHTML = head('Storage', 'What your indexed files are made of. Everything stays in Telegram; this is what TG Drive can see.') + '<div class="page-loading">Adding it all up…</div>';
  let r;
  try { r = await api(A('/storage')); } catch (e) { page().innerHTML += `<p class="warn">${esc(e.message)}</p>`; return; }
  const max = (rows, k = 'bytes') => Math.max(1, ...rows.map((x) => x[k] || 0));
  const bars = (rows, label, color, go) => {
    const m = max(rows);
    return rows.map((x) => `<div class="hbar" ${go ? `data-go="${go(x)}"` : ''}><span class="hb-l">${label(x)}</span><span class="hb-track"><i style="width:${Math.max(1, (x.bytes || 0) / m * 100)}%;background:${color(x)}"></i></span><span class="hb-v">${fmtSize(x.bytes)}<small>${fmtNum(x.n)}</small></span></div>`).join('');
  };
  const kindColor = (x) => `var(--k-${x.kind})`;
  const local = r.local;
  const years = r.by_year.filter((y) => y.year);
  const ym = max(years);
  page().innerHTML = head('Storage', 'What your indexed files are made of. Everything stays in Telegram; this is what TG Drive can see.', `<button class="btn" data-refresh-page>${icon('refresh')}Refresh</button>`) + `
    <div class="kpis">
      <div class="kpi"><span>Files</span><strong>${fmtNum(r.total.n)}</strong></div>
      <div class="kpi"><span>Total size</span><strong>${fmtSize(r.total.bytes)}</strong></div>
      <div class="kpi" data-go="#duplicates"><span>Duplicate copies</span><strong>${fmtSize(r.duplicates.bytes)}</strong><small>${plural(r.duplicates.groups, 'file')} appear more than once</small></div>
      <div class="kpi"><span>On this computer</span><strong>${fmtSize(local.index_db + local.thumbs + local.stream_cache + local.semantic)}</strong><small>index ${fmtSize(local.index_db)} · previews ${fmtSize(local.thumbs)} · stream cache ${fmtSize(local.stream_cache)}</small></div>
    </div>
    <div class="cols">
      <section class="panel"><h2>By type</h2>${bars(r.by_kind, (x) => esc(KIND_NAME[x.kind] || x.kind), kindColor, (x) => `#all?kind=${x.kind}`)}</section>
      <section class="panel"><h2>By source</h2>${bars(r.by_source, (x) => esc(CHAT_KIND_NAME[x.kind] || x.kind), () => 'var(--accent)')}</section>
    </div>
    <section class="panel"><h2>By year sent</h2><div class="vbars">${years.map((y) => `<div class="vb" title="${y.year}: ${fmtSize(y.bytes)}, ${fmtNum(y.n)} files"><i style="height:${Math.max(2, y.bytes / ym * 100)}%"></i><span>${y.year}</span></div>`).join('')}</div></section>
    <div class="cols">
      <section class="panel"><h2>Biggest sources</h2>${bars(r.by_chat.slice(0, 15), (x) => `${chatAvatar({ title: x.title || '?' }, 'xs')}${esc(x.title || x.chat_id)}`, () => 'var(--folder)', (x) => `#chat/${x.chat_id}`)}</section>
      <section class="panel"><h2>By extension</h2>${bars(r.by_ext.slice(0, 15), (x) => `<span class="ext-dot" style="background:${extColor(x.ext)}"></span>${esc(x.ext ? `.${x.ext}` : '(none)')}`, (x) => extColor(x.ext))}</section>
    </div>
    <section class="panel"><h2>Largest files</h2><div class="simple-list">${r.largest.map((f) => `<button class="sl-row" data-open-ref="${f.chat_id}:${f.msg_id}">
      <span class="mini doc" style="--ec:${extColor(f.ext)}">${esc((f.ext || f.kind).slice(0, 4).toUpperCase())}</span><span class="grow">${esc(f.name)}</span><small>${esc(f.chat_title || '')}</small><strong>${fmtSize(f.size)}</strong></button>`).join('')}</div></section>`;
}

/* ------------------------------------------------------------- duplicates */
let dupMode = 'exact';
async function duplicates() {
  page().innerHTML = head('Duplicates', 'Files that appear more than once. “Same file” means Telegram stores one copy that was forwarded into several chats; “Same name and size” catches re-uploads.',
    `<div class="seg"><button class="${dupMode === 'exact' ? 'on' : ''}" data-dup="exact">Same file</button><button class="${dupMode === 'similar' ? 'on' : ''}" data-dup="similar">Same name and size</button></div>`) + '<div class="page-loading">Looking for duplicates…</div>';
  let r;
  try { r = await api(A(`/duplicates?${qs({ mode: dupMode })}`)); } catch (e) { fail(e); return; }
  const groups = r.groups;
  S.items = groups.flatMap((g) => g.files.map((f) => ({ ...f, name: f.name })));
  S.byKey = new Map(S.items.map((f) => [key(f), f]));
  $('.page-loading', page())?.remove();
  page().insertAdjacentHTML('beforeend', groups.length ? `<div class="dup-tools"><button class="btn" data-dup-select>${icon('check')}Select all but the oldest copy</button><span class="subtle">Then use the selection bar to move, tag, remove from the index or delete.</span></div>` + groups.map((g) => `
    <section class="panel dup"><h2>${esc(g.files[0]?.name || '')}<small>${plural(g.n, 'copy', 'copies')} · ${fmtSize(g.size)} each · ${fmtSize(g.waste)} extra</small></h2>
      ${g.files.map((f, i) => `<label class="dup-row"><input type="checkbox" data-dk="${f.chat_id}:${f.msg_id}" ${S.selected.has(`${f.chat_id}:${f.msg_id}`) ? 'checked' : ''}>
        <span class="grow">${esc(f.chat_title || '')}${f.folder_id ? ` <span class="in-folder">${icon('folder')}${esc(S.folderById.get(f.folder_id)?.name || '')}</span>` : ''}</span>
        <small>${fmtDate(f.date)}${i === 0 ? ' · oldest' : ''}</small><button class="btn ghost sm" data-open-ref="${f.chat_id}:${f.msg_id}">${icon('eye')}</button></label>`).join('')}</section>`).join('') + (r.more ? `<button class="btn" data-dup-more>Show more</button>` : '')
    : '<div class="empty"><h2>No duplicates</h2><p>Every file you have is unique.</p></div>');
  page().dataset.groups = JSON.stringify(groups.map((g) => g.files.map((f) => `${f.chat_id}:${f.msg_id}`)));
}

/* ---------------------------------------------------------- index manager */
let idxFilter = { q: '', kind: '', state: '' };
async function indexManager() {
  const st = S.status?.index;
  const pending = st ? st.chats_pending : 0;
  const right = `<button class="btn" data-idx="${st?.phase === 'paused' ? 'resume' : 'pause'}">${icon(st?.phase === 'paused' ? 'play' : 'pause')}${st?.phase === 'paused' ? 'Resume indexing' : 'Pause indexing'}</button>
    <button class="btn" data-idx="resync">${icon('refresh')}Check all chats now</button>`;
  const v = st?.verify || {};
  page().innerHTML = head('Index manager', `TG Drive indexes every file in every chat, then keeps up with new ones live. ${st ? `${fmtNum(st.chats_done)} of ${plural(st.chats_total, 'chat')} done${pending ? `, ${fmtNum(pending)} waiting` : ''}${st.files_per_min ? `, ${fmtNum(st.files_per_min)} files/min` : ''}.` : ''}
    ${v.checked ? ` Deleted-file check: ${fmtNum(v.checked)} checked, ${fmtNum(v.removed)} removed.` : ''}`, right) + `
    <div class="idx-filters"><input type="search" id="idxQ" placeholder="Filter chats" value="${esc(idxFilter.q)}">
      <select id="idxKind"><option value="">All kinds</option>${SOURCES.map(([k, l]) => `<option value="${k}" ${idxFilter.kind === k ? 'selected' : ''}>${l}</option>`).join('')}</select>
      <select id="idxState"><option value="">Any state</option>${[['done', 'Up to date'], ['pending', 'Waiting'], ['running', 'Indexing'], ['error', 'Problem'], ['excluded', 'Excluded'], ['gone', 'Left']].map(([k, l]) => `<option value="${k}" ${idxFilter.state === k ? 'selected' : ''}>${l}</option>`).join('')}</select>
      <span class="spacer"></span>
      <button class="btn sm" data-bulk-idx="exclude">Exclude shown</button><button class="btn sm" data-bulk-idx="include">Include shown</button><button class="btn sm" data-bulk-idx="rescan">Re-index shown</button></div>
    <div class="table idx-table" id="idxTable"></div>`;
  renderIdxTable();
}
function idxRows() {
  const q = idxFilter.q.toLowerCase();
  return S.chats.filter((c) => (!q || c.title.toLowerCase().includes(q))
    && (!idxFilter.kind || SOURCES.find(([k]) => k === idxFilter.kind)[2].includes(c.kind))
    && (!idxFilter.state || (idxFilter.state === 'excluded' ? c.excluded : !c.excluded && c.index_state === idxFilter.state)))
    .sort((a, b) => (b.file_count || 0) - (a.file_count || 0));
}
function renderIdxTable() {
  const rows = idxRows();
  const stateLabel = (c) => c.excluded ? '<span class="pill grey">Excluded</span>' : ({ done: '<span class="pill ok">Up to date</span>', pending: '<span class="pill">Waiting</span>', running: '<span class="pill blue">Indexing</span>', error: `<span class="pill red" title="${esc(c.index_error || '')}">Problem</span>`, gone: '<span class="pill grey">Left</span>' })[c.index_state] || esc(c.index_state);
  $('#idxTable').innerHTML = `<div class="tr th"><span>Chat</span><span>Kind</span><span>Files</span><span>Size</span><span>State</span><span>Last indexed</span><span></span></div>` + rows.slice(0, 1500).map((c) => `
    <div class="tr"><span class="td-name">${chatAvatar(c, 'xs')}<button class="linkish" data-go="#chat/${c.id}">${esc(c.title)}</button>${c.pinned ? icon('pin', 'class="pin-mark"') : ''}</span>
      <span>${esc(CHAT_KIND_NAME[c.kind] || c.kind)}</span><span>${fmtNum(c.file_count)}</span><span>${fmtSize(c.total_bytes)}</span>
      <span>${stateLabel(c)}</span><span>${c.last_indexed ? relTime(c.last_indexed) : '—'}</span>
      <span class="td-acts"><button class="btn ghost sm" data-chat-act="${c.excluded ? 'include' : 'exclude'}" data-cid="${c.id}">${c.excluded ? 'Include' : 'Exclude'}</button><button class="btn ghost sm" data-chat-act="rescan" data-cid="${c.id}">Re-index</button></span></div>`).join('')
    + (rows.length > 1500 ? `<p class="subtle">${fmtNum(rows.length - 1500)} more; narrow the filter.</p>` : '');
}

/* --------------------------------------------------------------- activity */
async function activity() {
  const r = await api(A('/activity')).catch((e) => { fail(e); return { activity: [] }; });
  page().innerHTML = head('Activity', 'What TG Drive did on your behalf: folder changes, copies, sends, deletions and clean-ups.') +
    `<div class="simple-list">${r.activity.map((a) => `<div class="sl-row static"><span class="pill">${esc(a.action)}</span><span class="grow">${esc(a.detail)}</span><small>${fmtDate(a.at, true)}</small></div>`).join('') || '<p class="subtle">Nothing yet.</p>'}</div>`;
}

/* --------------------------------------------------------------- settings */
const SECTIONS = [
  ['general', 'General', 'settings'], ['appearance', 'Appearance', 'palette'], ['search', 'Search', 'search'],
  ['subjects', 'Subjects', 'book'], ['photos', 'Photos & places', 'image'], ['downloads', 'Downloads & uploads', 'download'],
  ['streaming', 'Streaming', 'play'], ['indexing', 'Indexing', 'database'], ['drive', 'Drive on this computer', 'mount'],
  ['sync', 'Folder sync', 'sync'], ['network', 'Network & proxy', 'external'], ['telegram', 'Telegram API', 'telegram'],
  ['accounts', 'Accounts', 'user'], ['security', 'Security', 'lock'], ['desktop', 'Desktop', 'maximize'],
  ['data', 'Data & maintenance', 'database'], ['about', 'About & diagnostics', 'info'],
];
const ACCENTS = ['', '#2a7fc9', '#4f63d8', '#7a4fd0', '#c2418f', '#d2463b', '#e07a1f', '#b88a00', '#2f8f4e', '#128b86', '#4b5563'];
async function settingsPage(section = 'general') {
  if (!SECTIONS.some(([k]) => k === section)) section = 'general';
  const same = $('#setBody', page())?.dataset.section === section;
  if (!page().querySelector('.settings')) {
    page().innerHTML = `<div class="settings"><nav class="set-nav">${SECTIONS.map(([k, l, ic]) => `<button class="nav-item" data-go="#settings/${k}" data-sec="${k}">${icon(ic)}<span class="label">${l}</span></button>`).join('')}</nav>
      <div class="set-body" id="setBody"></div></div>`;
  }
  $$('.set-nav [data-sec]', page()).forEach((b) => b.classList.toggle('active', b.dataset.sec === section));
  const body = $('#setBody');
  if (!same) body.innerHTML = '<div class="page-loading">Loading…</div>';
  const s = await api('/api/settings').catch(() => S.settings);
  S.settings = s;
  const html = await SECTION_HTML[section](s);
  if (!$('#setBody') || location.hash.split('/')[0] !== '#settings') return;
  const keep = same ? body.scrollTop : 0;
  body.innerHTML = html;
  body.dataset.section = section;
  if (!same) { body.classList.remove('sec-enter'); void body.offsetWidth; body.classList.add('sec-enter'); }
  page().scrollTop = same ? page().scrollTop : 0;
  body.scrollTop = keep;
  SECTION_AFTER[section]?.(body, s);
}

const row = (label, help, control) => `<div class="set-row"><div class="set-l"><strong>${label}</strong>${help ? `<p>${help}</p>` : ''}</div><div class="set-c">${control}</div></div>`;
const sw = (k, s) => `<label class="switch"><input type="checkbox" data-set="${k}" ${s[k] ? 'checked' : ''}><span></span></label>`;
const sel = (k, s, opts) => `<select data-set="${k}">${opts.map(([v, l]) => `<option value="${v}" ${String(s[k]) === String(v) ? 'selected' : ''}>${l}</option>`).join('')}</select>`;
const num = (k, s, min, max, step = 1, unit = '') => `<span class="num"><input type="number" data-set="${k}" data-num value="${esc(s[k])}" min="${min}" max="${max}" step="${step}">${unit ? `<small>${unit}</small>` : ''}</span>`;
const txt = (k, s, ph = '', type = 'text') => `<input type="${type}" data-set="${k}" value="${esc(s[k] ?? '')}" placeholder="${esc(ph)}">`;

const SECTION_HTML = {
  general: (s) => `<h2>General</h2>
    ${row('Default view', 'Press V to switch any time.', sel('view', s, [['grid', 'Grid'], ['list', 'List']]))}
    ${row('Group by date', 'Section headers such as Today, Yesterday and months when sorted by date.', sw('group_by_date', s))}
    ${row('Hide duplicates', `One card per file: copies forwarded into other chats, and files uploaded again with the same name and size, fold into the best copy (one in your folders, starred, downloaded, in your own channel, or else the oldest). A chat still shows its own files. Type <code>copies:show</code> in a search to see them all once.${S.status?.dupes?.extra ? ` Right now ${fmtNum(S.status.dupes.extra)} extra copies (${fmtSize(S.status.dupes.extra_bytes || 0)}) are folded away.` : ''}`, sw('hide_duplicates', s))}
    ${row('Albums as stacks', 'Files sent together (an album) show as one stacked card in the grid. Open it to see them all.', sw('stack_albums', s))}
    ${row('Ask before deleting from Telegram', '', sw('confirm_delete', s))}
    ${row('Notifications', 'When downloads and uploads finish or fail.', sw('notifications', s))}`,
  appearance: (s) => `<h2>Appearance</h2>
    ${row('Theme', '', sel('theme', s, [['system', 'Match the system'], ['light', 'Light'], ['dark', 'Dark']]))}
    <div class="set-row"><div class="set-l"><strong>Accent colour</strong><p>Buttons, selection and highlights.</p></div><div class="set-c"><div class="accent-pick">
      ${ACCENTS.map((c) => `<button class="accent-sw ${(s.accent || '') === c ? 'on' : ''}" data-accent="${c}" style="--sw:${c || '#2a7fc9'}" title="${c || 'Default blue'}" aria-label="${c || 'Default'}"></button>`).join('')}
      <label class="accent-custom" title="Any colour"><input type="color" data-accent-custom value="${esc(s.accent || '#2a7fc9')}"></label></div></div></div>
    ${row('Contrast', 'High contrast makes text, borders and focus rings stronger.', sel('contrast', s, [['normal', 'Normal'], ['high', 'High contrast']]))}
    <div class="set-row"><div class="set-l"><strong>Text size</strong><p>Scales text and rows everywhere in TG Drive. (Ctrl + / Ctrl − zoom the whole window in the desktop app.)</p></div>
      <div class="set-c"><div class="fs-pick"><span class="fs-a small">A</span><input type="range" min="0.85" max="1.4" step="0.05" data-fontscale value="${esc(s.font_scale || 1)}"><span class="fs-a big">A</span><output>${Math.round((s.font_scale || 1) * 100)}%</output></div></div></div>
    ${row('Animations', 'Panels sliding, lists fading in, menus and dialogs popping. “Follow the system” turns them off when your desktop is set to reduce motion (many Linux desktops are by default).', sel('motion', s, [['on', 'On'], ['system', 'Follow the system'], ['off', 'Off']]))}
    ${row('Density', 'Compact fits more rows in lists and the sidebar.', sel('density', s, [['comfortable', 'Comfortable'], ['compact', 'Compact']]))}
    ${row('Card size', '', sel('grid_size', s, [['s', 'Small'], ['m', 'Medium'], ['l', 'Large']]))}
    ${row('Folders', 'How folders show above the files. You can also switch with the buttons next to “Folders”.', sel('folder_style', s, [['tiles', 'Tiles'], ['cards', 'Cards with covers'], ['list', 'List']]))}
    <div class="set-block"><strong>List columns</strong><p>Choose, reorder and resize the columns of the list view.</p><button class="btn" data-columns-dlg>${icon('columns')}Choose columns…</button></div>`,
  subjects: async (s) => {
    const r = await api(A('/subjects')).catch(() => ({ subjects: [], status: {} }));
    const counts = r.subjects.filter((x) => x.n).sort((a, b) => b.n - a.n);
    return `<h2>Subjects</h2>
    <p class="set-intro">TG Drive tags every file with a subject (Polity, Economy, History …) from its name, caption and chat, in English and Hindi, and uses the offline meaning model when the words alone don't decide. Subjects appear in the sidebar, in search (<code>subject:polity</code>) and in folder rules. Set a file's subject by hand from its menu; TG Drive then leaves it alone.</p>
    ${row('Tag files with subjects', `${r.status?.state === 'building' ? 'Working through your files now.' : ''}`, sw('subjects_enabled', s))}
    ${row('Built-in study subjects', 'UPSC and general study subjects with English, Hindi and abbreviated keywords.', sw('subjects_builtin', s))}
    <div class="set-block"><strong>Your subjects and keywords</strong><p>One subject per line: a name, a colon, then keywords separated by commas. Use an existing name to add keywords to it. An emoji before the name becomes its icon.</p>
      <textarea data-set="subjects_custom" rows="6" spellcheck="false" placeholder="📑 Tax Law: income tax, gst, itr&#10;History: harappa, mauryan, gupta period">${esc(s.subjects_custom || '')}</textarea></div>
    <div class="set-block"><strong>Now</strong><div class="subject-counts">${counts.map((x) => `<button class="chip" data-go="#subject/${esc(x.id)}">${x.emoji ? `<span>${x.emoji}</span>` : ''}${esc(x.name)}<small>${fmtNum(x.n)}</small></button>`).join('') || '<span class="subtle">No subjects found yet.</span>'}</div>
      <div class="btn-row"><button class="btn" data-subjects-rebuild>${icon('refresh')}Tag everything again</button><button class="btn" data-subjects-tags>${icon('tag')}Turn subjects into tags…</button></div></div>`;
  },
  photos: (s) => `<h2>Photos & places</h2>
    ${row('Find where photos were taken', 'Pictures sent as files keep their GPS location. TG Drive reads only the first 128 KB of each image file to find it, slowly, in the background. They then show on the Places map.', sw('places_scan', s))}
    ${row('Detailed map tiles', 'Shows streets and places from OpenStreetMap on the Places map. This is the one feature that loads data from outside Telegram (tile images). Takes effect after reloading the window.', sw('map_online_tiles', s))}
    ${row('Slideshow speed', 'Seconds per picture.', num('slideshow_seconds', s, 1, 60, 1, 's'))}`,
  drive: async (s) => {
    const d = await api('/api/dav').catch(() => ({}));
    return `<h2>Drive on this computer</h2>
    <p class="set-intro">Open TG Drive in your file manager like a disk, so any app can open, play or save files: videos stream, PDFs open in your PDF reader, and files copied into <b>My Drive</b> upload. It only answers on this computer, while TG Drive is running.</p>
    ${row('Make TG Drive available as a drive', '', sw('dav_enabled', s))}
    ${row('Allow changes', 'Copy files in to upload, create folders, rename and move. Deleting only takes a file out of its folder; it stays in Telegram.', sw('dav_write', s))}
    ${s.dav_enabled ? `<div class="set-block"><strong>Open it</strong>
      <div class="btn-row"><button class="btn primary" data-dav="mount">${icon('mount')}Open in file manager</button>${d.gio ? `<button class="btn" data-dav="unmount">Disconnect</button>` : ''}</div>
      <p>Or use this address in any WebDAV client:</p>
      <div class="link-row"><input type="text" readonly value="${esc(d.url || '')}" aria-label="Drive address"><button class="icon-btn" data-copy-val="${esc(d.url || '')}" title="Copy">${icon('copy')}</button></div>
      <details><summary>Other file managers and a real mount point</summary><div class="help">
        <p><b>GNOME Files, Nemo, Caja:</b> “Open in file manager” above, or <i>Other Locations → Connect to Server</i> with the address.</p>
        <p><b>Dolphin (KDE):</b> type <code>${esc((d.url || '').replace('dav://', 'webdav://'))}</code> in the location bar.</p>
        <p><b>A folder any program can use (davfs2):</b> <code>sudo mount -t davfs ${esc(d.http || '')} /mnt/tgdrive</code></p>
        <p><b>rclone:</b> <code>rclone mount :webdav: ~/TGDrive --webdav-url=${esc(d.http || '')} --vfs-cache-mode full</code></p>
        <p>The address contains a secret. <button class="linkish" data-dav="reset">Make a new one</button> if you shared it by mistake.</p></div></details></div>` : ''}`;
  },
  sync: (s) => `<h2>Folder sync</h2>
    <p class="set-intro">Synced folders are listed on the <button class="linkish" data-go="#sync">Folder sync</button> page (Tools in the sidebar).</p>
    ${row('Sync folders', 'Turn off to pause every synced folder.', sw('sync_enabled', s))}
    ${row('Check for changes every', '', num('sync_interval', s, 15, 3600, 15, 's'))}
    ${row('Deleting on this computer also deletes from Telegram', 'Off: a file you delete on this computer is only taken out of the TG Drive folder and stays in Telegram. On: files that live in your TG Drive channel are deleted there too.', sw('sync_delete_remote', s))}`,
  search: (s) => `<h2>Search</h2>
    ${row('Matching', 'Smart finds the same words written differently: joined or split (test series ↔ testseries ↔ TestSeries), text inside words, word endings, typos, abbreviations (pyq ↔ previous year questions), Hindi ↔ Latin script, and synonyms. Exact looks for your words only.', sel('search_mode', s, [['smart', 'Smart'], ['exact', 'Exact words']]))}
    ${row('Related by meaning', `Adds files with a similar meaning at the end of “Best match” results, using a small AI model that runs offline on this computer. <span id="semStatus" class="subtle"></span>`, sw('search_semantic', s))}
    ${row('Search as you type', 'Results update while you type. Turn off to search only when you press Enter.', sw('search_live', s))}
    ${row('Built-in synonyms', 'Common study and file words: PYQ, current affairs, GS, polity ↔ संविधान, and more.', sw('search_builtin_synonyms', s))}
    <div class="set-block"><strong>Your synonyms</strong><p>One group per line, separated by commas. Any word or phrase in a group finds the others. Example: <code>ts, test series, mock test</code></p>
      <textarea data-set="search_synonyms" rows="7" spellcheck="false" placeholder="lax, laxmikanth, indian polity&#10;ncert, class 11, class 12">${esc(s.search_synonyms || '')}</textarea></div>
    <div class="set-block"><strong>Search history</strong><p>TG Drive remembers recent searches on this computer to suggest them.</p><button class="btn" data-clear-history>${icon('trash')}Clear search history</button></div>`,
  downloads: (s) => `<h2>Downloads & uploads</h2>
    ${row('Download folder', `Files go here. Default: ${esc(S.status?.download_dir || '~/Downloads/TG Drive')}.`, `<span class="path-pick">${txt('download_dir', s, 'Default folder')}${bridge.ready ? `<button class="btn" data-pick-dir>${icon('folder')}Choose…</button>` : ''}</span>`)}
    ${row('Open files after downloading', 'Single files open in their default app when done.', sw('open_after_download', s))}
    ${row('Keep folder structure', 'Downloading a folder recreates its subfolders; uploading a folder recreates it in TG Drive.', sw('keep_structure', s))}
    ${row('Transfers at the same time', '', num('parallel_transfers', s, 1, 10))}
    ${row('Parallel parts per download', 'More parts download faster, up to what Telegram allows.', num('download_workers', s, 1, 8))}
    ${row('Parallel parts per upload', '', num('upload_workers', s, 1, 8))}
    ${row('Upload photos and videos as media', 'Off: files are sent as documents (original quality, any type). On: photos are compressed by Telegram and videos get a streaming preview.', sw('upload_as_media', s))}`,
  streaming: (s) => `<h2>Streaming</h2>
    <p class="set-intro">Videos, audio, voice notes, GIFs, photos and PDFs play straight from Telegram. TG Drive fetches the parts you watch, a few parts ahead, and keeps recent parts on disk so seeking back is instant.</p>
    ${row('Stream cache size', 'Oldest parts are removed when the cache is full.', num('stream_cache_mb', s, 0, 200000, 256, 'MB'))}
    ${row('Parts fetched ahead', 'Each part is 512 KB. More makes playback smoother on slow connections.', num('stream_prefetch', s, 0, 16))}
    ${bridge.ready ? row('Use the TG Drive player when needed', 'Most Telegram videos use H.264/H.265 and AAC, which the app window can\'t decode. They open in TG Drive\'s own player instead (it streams too, with seeking and speed control).', sw('native_player_auto', s)) : ''}
    ${row('Play the next file automatically', 'When a video or song ends in the viewer, the next one starts.', sw('autoplay_next', s))}
    ${row('External player', 'Used by “Open in VLC / mpv”. Leave empty to use the first of VLC, mpv, Celluloid, Totem, SMPlayer or Haruna that is installed.', txt('external_player', s, 'vlc'))}
    <div class="set-block"><strong>Cache</strong><p id="streamUsage">…</p><button class="btn" data-maint="clear_stream_cache">${icon('trash')}Clear stream cache</button></div>
    <div class="set-block"><strong>Other players</strong><p>Any video or audio can be opened in VLC or mpv: in the viewer, copy the stream link; for a whole folder, use the folder menu → Playlist for VLC / mpv.</p></div>`,
  indexing: (s) => `<h2>Indexing</h2>
    <div class="set-block"><strong>File types to index</strong><p>Turning a type off stops indexing it; files already indexed stay until you re-index the chat.</p>
      <div class="checks">${['photo', 'video', 'document', 'audio', 'voice', 'round', 'gif'].map((k) => `<label><input type="checkbox" data-kind-toggle="${k}" ${(s.index_kinds || []).includes(k) ? 'checked' : ''}>${esc(KIND_NAME[k])}</label>`).join('')}</div></div>
    <div class="set-block"><strong>Skip these kinds of chats</strong><p>Useful if private chats or bots are full of files you don't need in TG Drive.</p>
      <div class="checks">${[['user', 'Private chats'], ['bot', 'Bots'], ['group', 'Basic groups'], ['supergroup', 'Groups'], ['channel', 'Channels']].map(([k, l]) => `<label><input type="checkbox" data-skip-toggle="${k}" ${(s.index_skip_kinds_of_chat || []).includes(k) ? 'checked' : ''}>${l}</label>`).join('')}</div></div>
    ${row('Pause indexing', 'Stops fetching history. Live updates keep coming in.', sw('index_paused', s))}
    ${row('Wait between pages', 'Seconds between history pages. Raise this if Telegram keeps asking to slow down.', num('index_wait', s, 0, 10, 0.1, 's'))}
    ${row('Full check for new files', 'How often every chat is compared with Telegram (live updates catch most things sooner).', num('resync_minutes', s, 5, 1440, 5, 'min'))}
    ${row('Find files deleted while TG Drive was closed', 'Slowly re-checks indexed messages in the background and drops ones that no longer exist.', sw('verify_deleted', s))}
    ${row('Checks per hour', '100 files per request.', num('verify_per_hour', s, 0, 200000, 1000))}
    ${row('Save instant previews', 'Keeps Telegram’s tiny blurred preview in the index, so pictures appear immediately (about 200 bytes each).', sw('save_inline_previews', s))}`,
  network: (s) => `<h2>Network & proxy</h2>
    <p class="set-intro">Use a proxy if Telegram is blocked or slow on your network. Changes reconnect right away.</p>
    ${row('Use a proxy', '', sw('proxy_enabled', s))}
    ${row('Type', '', sel('proxy_type', s, [['socks5', 'SOCKS5'], ['socks4', 'SOCKS4'], ['http', 'HTTP'], ['mtproto', 'MTProto (Telegram proxy)']]))}
    ${row('Server', '', txt('proxy_host', s, 'proxy.example.com'))}
    ${row('Port', '', num('proxy_port', s, 1, 65535))}
    ${row('Username', 'SOCKS / HTTP only.', txt('proxy_user', s))}
    ${row('Password', s.proxy_pass_set ? 'Saved. Type a new one to change it.' : '', `<input type="password" data-set="proxy_pass" placeholder="${s.proxy_pass_set ? '••••••••' : ''}">`)}
    ${row('Secret', 'MTProto proxies only.', txt('proxy_secret', s))}`,
  telegram: (s) => `<h2>Telegram API</h2>
    <p class="set-intro">TG Drive signs in as your own Telegram account through Telegram's official API. It needs an API ID and hash, which you create once at my.telegram.org → API development tools.</p>
    ${S.status?.env_api ? '<p class="warn">The API ID is set by the TG_API_ID / TG_API_HASH environment variables, which override this page.</p>' : ''}
    ${row('API ID', '', `<input type="text" id="apiId" value="${esc(s.api_id || '')}" inputmode="numeric">`)}
    ${row('API hash', s.api_hash_set ? 'Saved. Enter a new one to replace it.' : '', `<input type="password" id="apiHash" placeholder="${s.api_hash_set ? '•••••••••••••••••••••••••••••••' : '32 characters'}">`)}
    <div class="set-block"><button class="btn primary" data-save-api>Save</button> <button class="btn ghost" data-ext="https://my.telegram.org/apps">${icon('external')}Open my.telegram.org</button></div>
    ${row('Name of the storage channel', 'Only used when TG Drive creates its private channel for the first time.', txt('drive_channel_title', s))}`,
  accounts: () => `<h2>Accounts</h2><div class="simple-list">${S.accounts.map((a) => `<div class="sl-row static"><span class="avatar">${esc((a.name || '?')[0])}</span><span class="grow"><strong>${esc(a.name)}</strong><small>${esc(a.username ? '@' + a.username : a.phone || '')}${a.premium ? ' · Premium' : ''} · ${esc(a.status)}</small></span>
      ${a.id === S.aid ? '<span class="pill ok">In use</span>' : `<button class="btn sm" data-switch="${a.id}">Switch</button>`}<button class="btn sm danger" data-remove-acct="${a.id}">Sign out…</button></div>`).join('')}</div>
    <div class="set-block"><button class="btn primary" data-add-account>${icon('plus')}Add another account</button></div>`,
  security: (s) => `<h2>Security</h2>
    <p class="set-intro">TG Drive only listens on this computer (127.0.0.1), rejects requests from other websites, and in the desktop app every request carries a secret that changes each launch.</p>
    ${row('App passcode', s.lock_set ? 'On. TG Drive asks for it when it starts or after being idle.' : 'Off. Anyone using this computer can open TG Drive.', `<button class="btn" data-lock-set>${s.lock_set ? 'Change or remove' : 'Set a passcode'}</button>`)}
    ${row('Lock after being idle', '0 = only when TG Drive starts.', num('lock_after_minutes', s, 0, 1440, 5, 'min'))}
    ${s.lock_set ? row('Lock now', '', '<button class="btn" data-lock-now>Lock</button>') : ''}
    <div class="set-block"><strong>Your session</strong><p>The Telegram session is stored at <code>${esc(S.status?.data_dir || '')}/accounts/…/session.session</code> with owner-only permissions. Anyone with that file can use your account; keep backups private. To end it everywhere, remove the account here or terminate “TG Drive Desktop” in Telegram → Settings → Devices.</p></div>`,
  desktop: async (s) => {
    const ig = await api('/api/integration').catch(() => ({ file_managers: [] }));
    const fms = ig.file_managers.filter((x) => x.present || x.installed);
    return `<h2>Desktop</h2>
    ${S.desktop ? `${row('Use TG Drive’s own title bar', 'One bar at the top instead of two: drag the top bar to move the window, double-click it to maximize. Turn off if your desktop handles it badly. Applies after restarting TG Drive.', sw('own_titlebar', s))}
    ${row('Keep running in the tray when the window is closed', 'Indexing and transfers continue; quit from the tray icon.', sw('close_to_tray', s))}
    ${row('Start minimized', '', sw('start_minimized', s))}
    ${row('Start when I log in', '', sw('autostart', s))}` : ''}
    <div class="set-block"><strong>Applications menu</strong><p>${ig.menu ? 'TG Drive is in your applications menu, with its icon.' : 'Add TG Drive to your applications menu (with its icon) so you can start it like any other app.'}</p>
      <div class="btn-row">${ig.menu ? `<button class="btn" data-integ="install-menu">${icon('refresh')}Update the menu entry</button><button class="btn ghost" data-integ="uninstall-menu">Remove from menu</button>` : `<button class="btn primary" data-integ="install-menu">${icon('plus')}Add to applications menu</button>`}</div>
      <p class="help">Starts with: <code>${esc(ig.launcher || '')}</code></p></div>
    <div class="set-block"><strong>“Send to TG Drive” in file managers</strong><p>Right-click files or folders in your file manager and choose “Send to TG Drive” to upload them.</p>
      ${fms.length ? `<div class="fm-list">${fms.map((x) => `<span class="pill ${x.installed ? 'ok' : 'grey'}">${esc(x.label)}${x.installed ? ' ✓' : ''}</span>`).join('')}</div>` : '<p class="subtle">No supported file manager found (GNOME Files, Nemo, Caja, Dolphin, Thunar).</p>'}
      <div class="btn-row"><button class="btn ${fms.some((x) => !x.installed) ? 'primary' : ''}" data-integ="install-file-managers">${icon('plus')}${fms.some((x) => x.installed) ? 'Update' : 'Add'} “Send to TG Drive”</button>${fms.some((x) => x.installed) ? '<button class="btn ghost" data-integ="uninstall-file-managers">Remove</button>' : ''}</div>
      <p class="help">GNOME Files lists it under <i>Scripts</i>. Restart the file manager if the item doesn't show up at once.</p></div>
    <div class="set-block"><strong>Windows</strong><p>Open another TG Drive window with <kbd>Ctrl</kbd> <kbd>Shift</kbd> <kbd>N</kbd> (or from the tray icon), or split the window in two with “Open in split view” in the ⋮ menu. Drag files between them to move them.</p></div>`;
  },
  data: async () => {
    const about = await api('/api/about').catch(() => ({ data: {} }));
    const backups = await api(A('/drive/backups')).catch(() => ({ backups: [] }));
    const legacy = await api('/api/legacy').catch(() => ({ candidates: [] }));
    return `<h2>Data & maintenance</h2>
    ${row('Data folder', `${fmtSize(about.data?.bytes || 0)} in total.`, `<code class="path">${esc(about.data?.path || '')}</code>`)}
    <div class="set-block"><strong>Index</strong><p>Tidy up or check the index. Nothing here touches Telegram.</p>
      <div class="btn-row"><button class="btn" data-maint="optimize">Optimize</button><button class="btn" data-maint="integrity">Check integrity</button>
      <button class="btn" data-maint="vacuum">Compact (VACUUM)</button><button class="btn" data-maint="stats">Recount statistics</button>
      <button class="btn" data-maint="rebuild_search">Rebuild search index</button><button class="btn" data-maint="rebuild_semantic">Rebuild meaning index</button><button class="btn" data-maint="clear_thumbs">Clear preview cache</button></div></div>
    <div class="set-block"><strong>Folders, stars, tags and notes</strong><p>They live in a pinned file in your “${esc(S.driveTitle)}” channel and sync to every device. TG Drive keeps the last 30 versions here.</p>
      <div class="btn-row"><a class="btn" href="${A('/drive/manifest')}" download>${icon('download')}Export</a><button class="btn" data-import-manifest>${icon('upload')}Import…</button><button class="btn" data-drive-sync>${icon('refresh')}Sync now</button></div>
      ${backups.backups.length ? `<div class="simple-list">${backups.backups.slice(0, 12).map((b) => `<div class="sl-row static"><span class="grow">${esc(b.reason)}<small>${fmtDate(b.at, true)} · ${fmtSize(b.bytes)}</small></span><button class="btn sm" data-restore="${b.id}">Restore</button></div>`).join('')}</div>` : ''}</div>
    <div class="set-block"><strong>Export search results</strong><p>Every file matching the current search or view as a spreadsheet (CSV).</p><button class="btn" data-export-csv>${icon('download')}Export CSV</button></div>
    <div class="set-block"><strong>Import from an earlier TG Drive</strong><p>Bring in an index and sign-in from the TG Drive zip version, so nothing needs re-indexing.</p>
      ${legacy.candidates.map((c) => `<div class="sl-row static"><code class="grow">${esc(c.path)}</code><small>${plural(c.accounts.length, 'account')}</small><button class="btn sm" data-legacy="${esc(c.path)}">Import</button></div>`).join('')}
      <button class="btn" data-legacy-pick>${icon('folder')}Choose a data folder…</button></div>`;
  },
  about: async (s) => {
    const about = await api('/api/about').catch(() => ({}));
    const logs = await api('/api/logs?lines=300').catch(() => '');
    const cr = await api('/api/crashes').catch(() => ({ reports: [] }));
    const logBytes = (about.log_files || []).reduce((a, x) => a + x.bytes, 0);
    return `<h2>About & diagnostics</h2>
    <p class="set-intro">Version ${esc(about.version || S.version)} · meaning-based search ${about.semantic_available ? 'available' : 'not installed'} · log file <code>${esc(about.log || '')}</code></p>
    <div class="btn-row"><button class="btn" data-shortcuts>${icon('keyboard')}Keyboard shortcuts</button><button class="btn" data-copy-logs>${icon('copy')}Copy log</button></div>
    <div class="set-block debug-block ${s.debug_logging ? 'is-on' : ''}"><strong>${icon('bug')}Detailed debug logging</strong>
      <p>Records everything in detail while it's on: every request and how long it took, what you clicked and where you went, transfers, streaming, indexing, search, errors and crashes with full tracebacks. It goes to <code>${esc(about.debug_log || 'tgdrive-debug.log')}</code> on this computer only. Turn it on to catch a problem, reproduce it, then send the log (or a diagnostics file) and turn it off again. A large banner shows while it's on.</p>
      ${row(`Debug logging ${s.debug_logging ? '<span class="pill red">ON</span>' : '<span class="pill grey">Off</span>'}`, 'Takes effect at once, no restart. Makes the log grow quickly (kept to about 100 MB).', sw('debug_logging', s))}
      <div class="btn-row"><button class="btn" data-debug="view">${icon('document')}View log</button><a class="btn" href="/api/logs/download?which=debug" download>${icon('download')}Download debug log</a>
        <button class="btn danger" data-debug="clear">${icon('trash')}Clear all logs</button><span class="subtle">${fmtSize(logBytes)} of logs on disk</span></div></div>
    <div class="set-block"><strong>Crash reports</strong><p>When something goes wrong, TG Drive saves a short report on this computer. Nothing is sent anywhere.</p>
      ${row('Save crash reports', '', sw('crash_reports', s))}
      ${cr.reports.length ? `<div class="simple-list crash-list">${cr.reports.slice(0, 20).map((x) => `<div class="sl-row static"><span class="pill ${x.new ? 'red' : 'grey'}">${esc(x.kind)}</span><span class="grow"><strong>${esc(x.summary || 'Error')}</strong><small>${fmtDate(x.at, true)}</small></span><button class="btn sm" data-crash-view="${esc(x.id)}">View</button></div>`).join('')}</div>
        <div class="btn-row"><button class="btn ghost" data-crash-clear>${icon('trash')}Delete all reports</button></div>` : '<p class="subtle">No crashes recorded. 🎉</p>'}</div>
    <div class="set-block"><strong>Diagnostics file</strong><p>A .zip with logs, crash reports, versions and settings to attach to a bug report. Phone numbers, keys, tokens and e-mail addresses are removed; chat and file names too unless you include them.</p>
      <button class="btn" data-diag>${icon('bug')}Create diagnostics file…</button></div>
    <div class="set-block"><strong>Back up settings</strong><p>Save all your settings (appearance, search, synonyms, subjects, transfers…) to a file, and load them on another computer or after reinstalling. Folders, stars and tags already sync through Telegram.</p>
      <div class="btn-row"><button class="btn" data-settings-export>${icon('download')}Export settings</button><button class="btn" data-settings-import>${icon('upload')}Import settings…</button></div></div>
    <div class="set-block"><strong>Log</strong><pre class="logs">${esc(logs || 'No log yet.')}</pre></div>`;
  },
};

const SECTION_AFTER = {
  appearance: (body) => {
    const r = $('[data-fontscale]', body);
    r?.addEventListener('input', () => {
      document.documentElement.style.setProperty('--fs', r.value);
      r.parentElement.querySelector('output').textContent = `${Math.round(r.value * 100)}%`;
    });
  },
  search: (body) => {
    const sem = S.status?.semantic;
    const el = $('#semStatus', body);
    if (el && sem) el.textContent = sem.error ? `(${sem.error})` : sem.state === 'building' ? `(learning: ${fmtNum(sem.count)} files so far)` : `(${fmtNum(sem.count)} files understood)`;
  },
  streaming: async (body) => {
    const r = await api(A('/storage')).catch(() => null);
    const el = $('#streamUsage', body);
    if (el && r) el.textContent = `Using ${fmtSize(r.local.stream_cache)} now.`;
  },
};

async function saveSetting(k, v) {
  try {
    const r = await api('/api/settings', { method: 'PATCH', body: { [k]: v } });
    S.settings = r.settings;
    bus.emit('settings-changed', k);
    flashSaved();
  } catch (e) { fail(e); }
}
function flashSaved() {
  let el = $('#savedFlash');
  if (!el) { el = document.createElement('div'); el.id = 'savedFlash'; el.className = 'saved-flash'; el.textContent = 'Saved'; document.body.append(el); }
  el.classList.remove('show');
  void el.offsetWidth;
  el.classList.add('show');
}

page().addEventListener('change', async (e) => {
  const t = e.target;
  if (t.dataset.fontscale !== undefined) { saveSetting('font_scale', Number(t.value)); return; }
  if (t.dataset.accentCustom !== undefined) { saveSetting('accent', t.value); $$('.accent-sw', page()).forEach((b) => b.classList.remove('on')); return; }
  if (t.dataset.set) {
    let v = t.type === 'checkbox' ? t.checked : t.value;
    if (t.dataset.num !== undefined) v = Number(v);
    if (t.dataset.set === 'proxy_pass' && !v) return;
    await saveSetting(t.dataset.set, v);
    if (['dav_enabled', 'subjects_builtin', 'debug_logging'].includes(t.dataset.set)) settingsPage(page().querySelector('#setBody')?.dataset.section);
    if (t.dataset.set === 'map_online_tiles') toast('Reload the window (Ctrl+Shift+R) to use map tiles.');
  }
  if (t.dataset.kindToggle) {
    const kinds = $$('[data-kind-toggle]', page()).filter((x) => x.checked).map((x) => x.dataset.kindToggle);
    saveSetting('index_kinds', kinds);
  }
  if (t.dataset.skipToggle) {
    const kinds = $$('[data-skip-toggle]', page()).filter((x) => x.checked).map((x) => x.dataset.skipToggle);
    saveSetting('index_skip_kinds_of_chat', kinds);
  }
  if (t.dataset.dk) {
    const next = new Set(S.selected);
    t.checked ? next.add(t.dataset.dk) : next.delete(t.dataset.dk);
    import('./files.js').then((m) => m.setSelected(next));
  }
  if (t.id === 'idxKind') { idxFilter.kind = t.value; renderIdxTable(); }
  if (t.id === 'idxState') { idxFilter.state = t.value; renderIdxTable(); }
});
page().addEventListener('input', (e) => { if (e.target.id === 'idxQ') { idxFilter.q = e.target.value; renderIdxTable(); } });

page().addEventListener('click', async (e) => {
  const t = e.target.closest('button, a');
  if (!t) return;
  const d = t.dataset;
  if (d.refreshPage !== undefined) return bus.emit('route');
  if (d.dup) { dupMode = d.dup; return duplicates(); }
  if (d.dupSelect !== undefined) {
    const groups = JSON.parse(page().dataset.groups || '[]');
    const keys = groups.flatMap((g) => g.slice(1));
    const m = await import('./files.js');
    m.setSelected(keys);
    $$('[data-dk]', page()).forEach((c) => { c.checked = S.selected.has(c.dataset.dk); });
    toast(`Selected ${plural(keys.length, 'extra copy', 'extra copies')}`);
    return;
  }
  if (d.openRef) {
    const [c, m] = d.openRef.split(':').map(Number);
    const f = S.byKey.get(d.openRef) || await api(A(`/files/${c}/${m}`)).catch(fail);
    if (f) (await import('./viewer.js')).openViewer(f, [f]);
    return;
  }
  if (d.chatAct) {
    const cid = Number(d.cid);
    try {
      if (d.chatAct === 'rescan') await api(A(`/chats/${cid}/rescan`), { method: 'POST' });
      else await api(A(`/chats/${cid}/exclude`), { method: 'POST', body: { excluded: d.chatAct === 'exclude' } });
      const sb = await import('./sidebar.js');
      await sb.loadChats();
      renderIdxTable();
      toast('Done');
    } catch (err) { fail(err); }
    return;
  }
  if (d.bulkIdx) {
    const rows = idxRows();
    if (!await confirmDialog(`${d.bulkIdx === 'exclude' ? 'Exclude' : d.bulkIdx === 'include' ? 'Include' : 'Re-index'} ${plural(rows.length, 'chat')}?`, d.bulkIdx === 'exclude' ? 'Their files leave the index. Nothing changes in Telegram.' : 'They go back into the indexing queue.', 'Go ahead', d.bulkIdx === 'exclude')) return;
    try {
      await api(A('/chats/bulk'), { method: 'POST', body: { chat_ids: rows.map((c) => c.id), action: d.bulkIdx } });
      const sb = await import('./sidebar.js');
      await sb.loadChats();
      renderIdxTable();
    } catch (err) { fail(err); }
    return;
  }
  if (d.maint) {
    const label = t.textContent.trim();
    if (['rebuild_search', 'vacuum', 'rebuild_semantic'].includes(d.maint) && !await confirmDialog(`${label}?`, d.maint === 'vacuum' ? 'This can take a few minutes on a big index. TG Drive stays usable but may be slower.' : 'Search keeps working with the old index while the new one is built.', label)) return;
    t.disabled = true;
    try {
      const r = await api(A(`/maintenance/${d.maint}`), { method: 'POST' });
      toast(r.details ? (r.ok ? 'Everything checks out' : `Problems found: ${r.details.join('; ')}`) : r.removed !== undefined ? `Removed ${fmtNum(r.removed)} files` : `${label}: done${r.seconds ? ` in ${r.seconds}s` : ''}`, { err: r.ok === false });
    } catch (err) { fail(err); } finally { t.disabled = false; }
    return;
  }
  if (d.clearHistory !== undefined) { await api(A('/history'), { method: 'DELETE' }).catch(fail); toast('Search history cleared'); return; }
  if (d.pickDir !== undefined) {
    const p = await callBridge('pickFolder');
    if (p) { $('[data-set="download_dir"]', page()).value = p; saveSetting('download_dir', p); }
    return;
  }
  if (d.saveApi !== undefined) {
    try {
      await api('/api/setup', { method: 'POST', body: { api_id: $('#apiId').value, api_hash: $('#apiHash').value } });
      toast('Saved. Reconnecting…');
    } catch (err) { fail(err); }
    return;
  }
  if (d.ext) { if (bridge.ready) callBridge('openExternal', d.ext); else window.open(d.ext, '_blank', 'noopener'); return; }
  if (d.switch) { bus.emit('switch-account', Number(d.switch)); return; }
  if (d.removeAcct) { bus.emit('remove-account', Number(d.removeAcct)); return; }
  if (d.addAccount !== undefined) { bus.emit('add-account'); return; }
  if (d.lockSet !== undefined) { lockDialog(); return; }
  if (d.lockNow !== undefined) { await api('/api/lock/now', { method: 'POST' }); bus.emit('locked'); return; }
  if (d.restore) {
    if (!await confirmDialog('Restore this version?', 'Your folders, stars, tags, notes and saved searches go back to how they were then. You can undo this.', 'Restore')) return;
    try { await api(A(`/drive/backups/${d.restore}/restore`), { method: 'POST' }); toast('Restored'); bus.emit('drive-changed'); } catch (err) { fail(err); }
    return;
  }
  if (d.importManifest !== undefined) return importManifest();
  if (d.driveSync !== undefined) { await api(A('/drive/sync'), { method: 'POST' }).then(() => toast('Synced')).catch(fail); return; }
  if (d.exportCsv !== undefined) { window.location.href = A(`/export.csv?${qs(S.lastListParams || {})}`); return; }
  if (d.legacy) { return importLegacy(d.legacy); }
  if (d.legacyPick !== undefined) {
    const p = bridge.ready ? await callBridge('pickFolder') : await promptDialog('Import data', 'Path to the old data folder (contains accounts/)', '', 'Import');
    if (p) importLegacy(p);
    return;
  }
  if (d.shortcuts !== undefined) { (await import('./ui.js')).shortcutsDialog(); return; }
  if (d.accent !== undefined) { await saveSetting('accent', d.accent); $$('.accent-sw', page()).forEach((b) => b.classList.toggle('on', b === t)); return; }
  if (d.columnsDlg !== undefined) { (await import('./columns.js')).columnsDialog(); return; }
  if (d.subjectsRebuild !== undefined) { await api(A('/subjects/rebuild'), { method: 'POST' }).catch(fail); toast('Tagging every file again in the background.'); return; }
  if (d.subjectsTags !== undefined) { subjectsToTags(); return; }
  if (d.dav) { davAction(d.dav); return; }
  if (d.copyVal) { navigator.clipboard.writeText(d.copyVal).then(() => toast('Copied')); return; }
  if (d.integ) {
    t.disabled = true;
    try { await api(`/api/integration/${d.integ}`, { method: 'POST' }); toast('Done'); settingsPage('desktop'); } catch (err) { fail(err); } finally { t.disabled = false; }
    return;
  }
  if (d.crashView) { crashView(d.crashView); return; }
  if (d.crashClear !== undefined) { await api('/api/crashes', { method: 'DELETE' }).catch(fail); settingsPage('about'); return; }
  if (d.diag !== undefined) { diagnosticsDialog(); return; }
  if (d.settingsExport !== undefined) { exportSettings(); return; }
  if (d.settingsImport !== undefined) { importSettings(); return; }
  if (d.copyLogs !== undefined) { navigator.clipboard.writeText($('.logs', page()).textContent).then(() => toast('Log copied')); }
  if (d.idx) { api(A(`/index/${d.idx}`), { method: 'POST' }).then(() => { bus.emit('poll'); setTimeout(indexManager, 500); }).catch(fail); }
});

async function subjectsToTags() {
  const r = await dialog({
    title: 'Turn subjects into tags',
    body: '<p>Adds each file\'s subject as a tag (e.g. “polity”). Tags sync to your other devices and work everywhere tags do. Choose which files:</p>',
    actions: [{ label: 'Cancel' }, { label: 'Files in My Drive folders', onClick: () => ({ filed: '1' }) }, { label: 'Starred files', onClick: () => ({ starred: '1' }) }, { label: 'All files', cls: 'primary', onClick: () => ({}) }],
  });
  if (!r) return;
  toast('Adding tags…');
  try {
    const res = await api(A('/subjects/tags'), { method: 'POST', body: { params: r } });
    toast(`Tagged ${plural(res.tagged, 'file')}${res.tags.length ? ` (${res.tags.join(', ')})` : ''}`);
    bus.emit('meta-changed');
  } catch (e) { fail(e); }
}

async function davAction(a) {
  try {
    if (a === 'mount') {
      const r = await api('/api/dav/mount', { method: 'POST', body: { open: true } });
      if (r.mounted) toast('TG Drive is open in your file manager.');
      else {
        await navigator.clipboard.writeText(r.url).catch(() => {});
        toast(`${r.message || 'Couldn\'t open it automatically.'} The address is copied.`, { err: true, ms: 9000 });
      }
    } else if (a === 'unmount') { await api('/api/dav/unmount', { method: 'POST' }); toast('Disconnected'); }
    else if (a === 'reset') {
      if (!await confirmDialog('Make a new address?', 'The old address stops working; open TG Drive in your file manager again afterwards.', 'Make a new one')) return;
      await api('/api/dav', { method: 'POST', body: { reset_secret: true } });
      settingsPage('drive');
    }
  } catch (e) { fail(e); }
}

async function crashView(id) {
  const text = await api(`/api/crashes/${encodeURIComponent(id)}`).catch((e) => e.message);
  await api('/api/crashes/seen', { method: 'POST' }).catch(() => {});
  dialog({
    title: 'Crash report', wide: true,
    body: `<pre class="logs crash-text">${esc(text)}</pre>`,
    actions: [{ label: 'Copy', onClick: () => { navigator.clipboard.writeText(text).then(() => toast('Copied')); return false; } }, { label: 'Create diagnostics file…', onClick: () => { setTimeout(diagnosticsDialog, 50); } }, { label: 'Close', cls: 'primary' }],
  });
}

export async function diagnosticsDialog() {
  const r = await dialog({
    title: 'Create a diagnostics file',
    body: `<p>A .zip with TG Drive's logs, crash reports, versions, settings (without passwords or keys) and index statistics, saved to your download folder. It is not sent anywhere; attach it to a bug report yourself.</p>
      <label class="check-line"><input type="checkbox" id="diagNames"> Include chat and file names (off: they are replaced with [name])</label>`,
    actions: [{ label: 'Cancel' }, { label: 'Create', cls: 'primary', submit: true, onClick: (bd) => ({ include_names: bd.querySelector('#diagNames').checked }) }],
  });
  if (!r) return;
  try {
    toast('Collecting…');
    const res = await api('/api/diagnostics', { method: 'POST', body: r });
    await api('/api/crashes/seen', { method: 'POST' }).catch(() => {});
    $('#crashNotice')?.remove();
    toast(`Saved ${res.path.split('/').pop()} (${fmtSize(res.bytes)})`, { action: S.localHost ? 'Show' : undefined, onAction: () => api('/api/open', { method: 'POST', body: { path: res.path, reveal: true } }).catch(fail), ms: 10000 });
  } catch (e) { fail(e); }
}

async function exportSettings() {
  const r = await dialog({
    title: 'Export settings',
    body: `<p>Saves every setting to a file you can import later or on another computer.</p>
      <label class="check-line"><input type="checkbox" id="expApi"> Include the Telegram API key and proxy password (keep that file private)</label>`,
    actions: [{ label: 'Cancel' }, { label: 'Export', cls: 'primary', submit: true, onClick: (bd) => ({ api: bd.querySelector('#expApi').checked }) }],
  });
  if (!r) return;
  window.location.href = `/api/settings/export?include_api=${r.api ? 1 : 0}`;
}

async function importSettings() {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.json,application/json';
  input.onchange = async () => {
    try {
      const doc = JSON.parse(await input.files[0].text());
      const n = Object.keys(doc.settings || {}).length;
      if (!await confirmDialog('Import settings?', `${n} settings from ${esc(input.files[0].name)} replace the current ones. Your passcode and accounts are not changed.`, 'Import')) return;
      const res = await api('/api/settings/import', { method: 'POST', body: doc });
      S.settings = res.settings;
      bus.emit('settings-changed', 'theme');
      toast(`Imported ${plural(res.applied.length, 'setting')}${res.skipped.length ? ` (${res.skipped.length} skipped)` : ''}`);
      settingsPage('about');
    } catch (e) { fail(e.message ? e : new Error("That file couldn't be read.")); }
  };
  input.click();
}

async function importLegacy(path) {
  try {
    const r = await api('/api/legacy/import', { method: 'POST', body: { path } });
    toast(r.imported.length ? `Imported ${plural(r.imported.length, 'account')}. Starting…` : 'Nothing new to import (already here).');
    setTimeout(() => location.reload(), 1200);
  } catch (err) { fail(err); }
}

async function importManifest() {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.json,application/json';
  input.onchange = async () => {
    try {
      const data = JSON.parse(await input.files[0].text());
      const mode = await dialog({ title: 'Import folders', body: '<p>Merge keeps what you have and adds what\'s in the file (newer changes win). Replace makes the file the only truth.</p>',
        actions: [{ label: 'Cancel' }, { label: 'Replace', onClick: () => 'replace' }, { label: 'Merge', cls: 'primary', submit: true, onClick: () => 'merge' }] });
      if (!mode) return;
      await api(A(`/drive/manifest?mode=${mode}`), { method: 'POST', body: data });
      toast('Imported');
      bus.emit('drive-changed');
    } catch (err) { fail(err); }
  };
  input.click();
}

async function lockDialog() {
  const has = S.settings.lock_set;
  const r = await dialog({
    title: has ? 'Change passcode' : 'Set a passcode',
    body: `${has ? '<label class="field"><span>Current passcode</span><input type="password" id="lkOld"></label>' : ''}
      <label class="field"><span>New passcode ${has ? '(leave empty to turn the lock off)' : ''}</span><input type="password" id="lkNew" minlength="4"></label>
      <label class="field"><span>Repeat it</span><input type="password" id="lkNew2"></label>`,
    actions: [{ label: 'Cancel' }, {
      label: 'Save', cls: 'primary', submit: true, onClick: async (bd) => {
        const n = $('#lkNew', bd).value;
        if (n !== $('#lkNew2', bd).value) { toast("The passcodes don't match.", { err: true }); return false; }
        await api('/api/lock/set', { method: 'POST', body: { passcode: n, old: $('#lkOld', bd)?.value || '' } });
        return true;
      },
    }],
  });
  if (r) { toast('Passcode saved'); settingsPage('security'); }
}
export { settingsPage, M };

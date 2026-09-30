// Folders: the folder area (tiles, cards with covers, or a list), folder menu, icon/colour/cover
// picker, and rules for smart and auto-filing folders.
import { $, S, A, api, esc, icon, plural, bus, M, qs, fmtSize, fmtNum, fmtDate, pref, thumbUrl, inlineSrc, debounce, key } from './core.js';
import { menu, toast, fail, confirmDialog, promptDialog, folderPicker, descendantIds, dialog, childrenOf, folderColor, chatPicker, saveDownload } from './ui.js';
import { undoLast, folderRules } from './files.js';

export const COLORS = ['', 'red', 'orange', 'yellow', 'green', 'teal', 'blue', 'purple', 'pink', 'grey'];
const EMOJI = [
  ['Study', '📚 📖 📝 ✍️ 📓 📔 📒 📕 📗 📘 📙 🗒️ 📑 🎓 🧠 💡 🔖 📐 📏 🧮 🔬 🧪 🧬 🔭 ⚖️ 🏛️ 🌍 🗺️ 🌿 📈 📰 🧭 🛡️ 🤝 🎨 🔤'],
  ['Things', '📁 📂 🗂️ 🗃️ 🗄️ 📦 💼 🧾 💳 💰 🏦 🏠 🚗 ✈️ 🧳 🏖️ 🎁 🛒 🧰 🔧 💻 🖥️ 📱 🎧 🎮 📷 🎥 🎬 🎵 🎤 🖼️ 📺 📻 ⌚'],
  ['Symbols', '⭐ ❤️ 🔥 ✅ ❗ ❓ 💬 🔒 🔑 🚀 🎯 🏆 🥇 🌟 ✨ ⚡ 💎 🌈 ☀️ 🌙 🍀 🌸 🌻 🐾 🎉 🏁 📌 📍 🔔 ♻️ 🆕 🆓 💯 🔴 🟢 🔵'],
];

/* ------------------------------------------------------------ folder area */
const style = () => S.settings.folder_style || 'tiles';
const sortBy = () => pref('folderSort') || 'name';

function sorted(list) {
  const by = sortBy();
  const arr = [...list];
  if (by === 'newest') arr.sort((a, b) => (b.mtime || b.created || 0) - (a.mtime || a.created || 0));
  else if (by === 'size') arr.sort((a, b) => (b.bytes || 0) - (a.bytes || 0));
  else if (by === 'files') arr.sort((a, b) => (b.file_count || 0) - (a.file_count || 0));
  return arr;   // childrenOf() already sorts by name
}

function folderSummary(f) {
  if (f.kind === 'smart') return 'Smart folder';
  const subs = childrenOf(f.id).length;
  const parts = [];
  if (subs) parts.push(plural(subs, 'folder'));
  if (f.file_count) parts.push(plural(f.file_count, 'file'));
  if (f.bytes) parts.push(fmtSize(f.bytes));
  return parts.join(' · ') || 'Empty';
}

export function folderGlyph(f, big = false) {
  const badge = f.kind ? `<span class="f-badge ${f.kind}" title="${f.kind === 'smart' ? 'Smart folder' : 'Auto-filing folder'}">${icon(f.kind === 'smart' ? 'sparkle' : 'wand')}</span>` : '';
  const inner = f.emoji ? `<span class="f-emo">${esc(f.emoji)}</span>` : icon(f.kind === 'smart' ? 'folderSmart' : 'folderFill');
  return `<span class="f-ic ${big ? 'big' : ''} ${f.emoji ? 'has-emo' : ''}" style="--fcol:${folderColor(f)}">${inner}${badge}</span>`;
}

function coverHtml(f) {
  const covers = S.folderCovers?.[f.id] || [];
  if (f.cover && f.cover !== 'none') {
    const [c, m] = f.cover.split(':').map(Number);
    return `<div class="fc-cover single"><img class="real" data-src="${thumbUrl({ chat_id: c, msg_id: m }, 'b')}" alt="" decoding="async"></div>`;
  }
  if (f.cover !== 'none' && covers.length && f.kind !== 'smart') {
    const n = Math.min(4, covers.length);
    return `<div class="fc-cover mosaic n${n}">${covers.slice(0, n).map((x) => `<span>${x.inline ? `<img class="lqip" src="${inlineSrc(x.inline)}" alt="">` : ''}<img class="real" data-src="${thumbUrl(x, 's')}" alt="" decoding="async"></span>`).join('')}</div>`;
  }
  return `<div class="fc-cover empty" style="--fcol:${folderColor(f)}">${f.emoji ? `<span class="f-emo huge">${esc(f.emoji)}</span>` : icon(f.kind === 'smart' ? 'folderSmart' : 'folderFill')}</div>`;
}

function itemAttrs(f, extra = '') {
  return `class="fitem ${extra}" role="button" tabindex="0" draggable="true" data-folder="${esc(f.id)}" ${f.kind === 'smart' ? '' : `data-drop-folder="${esc(f.id)}"`} aria-label="Folder ${esc(f.name)}" style="--fcol:${folderColor(f)}" title="${esc(f.description || f.name)}"`;
}

function tileHtml(f) {
  return `<div ${itemAttrs(f, 'ftile')}>${folderGlyph(f)}
    <span class="ft-text"><span class="ft-name">${esc(f.name)}</span><span class="ft-meta">${folderSummary(f)}</span></span>
    <button class="icon-btn more" data-folder-menu="${esc(f.id)}" aria-label="Folder actions" aria-haspopup="menu">${icon('more')}</button></div>`;
}
function cardHtml(f) {
  return `<div ${itemAttrs(f, 'fcard')}>${coverHtml(f)}
    <div class="fc-body">${folderGlyph(f)}<span class="ft-text"><span class="ft-name">${esc(f.name)}</span><span class="ft-meta">${folderSummary(f)}</span></span>
    <button class="icon-btn more" data-folder-menu="${esc(f.id)}" aria-label="Folder actions" aria-haspopup="menu">${icon('more')}</button></div></div>`;
}
function rowHtml(f) {
  return `<div ${itemAttrs(f, 'frow')}>${folderGlyph(f)}<span class="ft-name">${esc(f.name)}</span>
    <span class="fr-desc">${esc(f.description || '')}</span><span class="fr-n">${f.kind === 'smart' ? 'Smart' : fmtNum(f.file_count || 0)}</span>
    <span class="fr-size">${f.bytes ? fmtSize(f.bytes) : ''}</span><span class="fr-date">${f.mtime ? fmtDate(Math.round(f.mtime / 1000)) : ''}</span>
    <button class="icon-btn more" data-folder-menu="${esc(f.id)}" aria-label="Folder actions" aria-haspopup="menu">${icon('more')}</button></div>`;
}

export async function renderFolderArea() {
  const v = S.view;
  const area = $('#folderArea');
  if (v.type !== 'drive' || S.kind || Object.keys(S.adv).length) { area.innerHTML = ''; return; }
  const cur = v.folderId ? S.folderById.get(v.folderId) : null;
  const kids = sorted(childrenOf(v.folderId));
  const desc = cur?.description ? `<p class="folder-desc">${esc(cur.description)}</p>` : '';
  if (!kids.length) { area.innerHTML = desc; return; }
  const hidden = pref('foldersHidden') === '1';
  const st = style();
  if (st === 'cards' && !S.folderCovers) loadCovers();
  area.innerHTML = `${desc}<div class="folder-bar">
      <button class="section-h collapse ${hidden ? '' : 'open'}" data-folders-toggle aria-expanded="${!hidden}">${icon('chevron')}Folders<small>${fmtNum(kids.length)}</small></button>
      <span class="spacer"></span>
    </div>
    ${hidden ? '' : `<div class="folder-${st}">${st === 'list' ? `<div class="frow fhead"><span></span><span>Name</span><span>Description</span><span class="fr-n">Files</span><span class="fr-size">Size</span><span class="fr-date">Changed</span><span></span></div>` : ''}${kids.map(st === 'cards' ? cardHtml : st === 'list' ? rowHtml : tileHtml).join('')}</div>`}
    <div class="section-h files-h" id="filesH">Files</div>`;
  import('./core.js').then((m) => m.thumbs.observe(area));
}

async function loadCovers() {
  try {
    const r = await api(A('/folders/covers'));
    S.folderCovers = r.covers;
    if (style() === 'cards') renderFolderArea();
  } catch { S.folderCovers = {}; }
}
bus.on('drive-changed', () => { S.folderCovers = null; });

document.addEventListener('click', async (e) => {
  const st = e.target.closest('[data-fstyle]');
  if (st) {
    S.settings.folder_style = st.dataset.fstyle;
    api('/api/settings', { method: 'PATCH', body: { folder_style: st.dataset.fstyle } }).catch(() => {});
    renderFolderArea();
    return;
  }
  if (e.target.closest('[data-folders-toggle]')) {
    pref('foldersHidden', pref('foldersHidden') === '1' ? '0' : '1');
    renderFolderArea();
    return;
  }
  const r = e.target.closest('[data-folder-rules]');
  if (r) { rulesDialog(r.dataset.folderRules); }
});
document.addEventListener('change', (e) => {
  if (e.target.matches?.('[data-fsort]')) { pref('folderSort', e.target.value); renderFolderArea(); }
});

/* ---------------------------------------------------------- create folders */
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

export async function newSmartFolder(parent = S.view.type === 'drive' ? S.view.folderId : null, preset = null) {
  return rulesDialog(null, { parent, preset });
}

/* ------------------------------------------------------ icon, colour, cover */
export async function appearanceDialog(f) {
  let color = f.color || '';
  let emoji = f.emoji || '';
  let cover = f.cover || '';
  const pics = await api(A(`/files?${qs({ folder_id: f.id, folder_tree: 1, kinds: 'photo,video,gif', limit: 48, sort: 'date' })}`)).then((r) => r.items).catch(() => []);
  const render = (bd) => {
    bd.querySelector('.ap-preview').innerHTML = folderGlyph({ ...f, color, emoji }, true) + `<strong>${esc(f.name)}</strong>`;
    bd.querySelectorAll('.swatch').forEach((b) => b.classList.toggle('on', b.dataset.c === color));
    bd.querySelectorAll('[data-emo]').forEach((b) => b.classList.toggle('on', b.dataset.emo === emoji));
    bd.querySelectorAll('[data-cover]').forEach((b) => b.classList.toggle('on', b.dataset.cover === cover));
    bd.querySelector('#emoInput').value = emoji;
  };
  const r = await dialog({
    title: `Look of “${f.name}”`,
    wide: true,
    cls: 'appearance',
    body: `<div class="ap-preview"></div>
      <div class="ap-sec"><h3>Colour</h3><div class="swatches">${COLORS.map((c) => `<button class="swatch" data-c="${c}" style="--sw:${c ? `var(--fc-${c})` : 'var(--folder)'}" aria-label="${c || 'Default'}"></button>`).join('')}</div></div>
      <div class="ap-sec"><h3>Icon</h3><div class="emo-row"><input id="emoInput" maxlength="8" placeholder="Type or paste any emoji" aria-label="Emoji"><button class="btn sm ghost" data-emo="">${icon('folder')}No emoji</button></div>
        ${EMOJI.map(([title, list]) => `<div class="emo-h">${title}</div><div class="emo-grid">${list.split(' ').map((x) => `<button data-emo="${x}" aria-label="${x}">${x}</button>`).join('')}</div>`).join('')}</div>
      <div class="ap-sec"><h3>Cover <small>shown in the “Cards” folder view</small></h3><div class="cover-grid">
        <button class="cover-opt" data-cover="">${icon('tiles')}<span>Latest pictures</span></button>
        <button class="cover-opt" data-cover="none">${icon('close')}<span>No picture</span></button>
        ${pics.filter((p) => p.has_thumb).map((p) => `<button class="cover-opt pic" data-cover="${p.chat_id}:${p.msg_id}" title="${esc(p.name)}">${p.inline ? `<img class="lqip" src="${inlineSrc(p.inline)}" alt="">` : ''}<img class="real" data-src="${thumbUrl(p, 's')}" alt=""></button>`).join('')}
      </div>${pics.length ? '' : '<p class="help">Put photos or videos in this folder to choose one as its cover.</p>'}</div>`,
    actions: [{ label: 'Cancel' }, { label: 'Save', cls: 'primary', submit: true, onClick: () => ({ color, emoji, cover }) }],
    onOpen: (bd) => {
      render(bd);
      import('./core.js').then((m) => m.thumbs.observe(bd));
      bd.addEventListener('click', (e) => {
        const sw = e.target.closest('.swatch');
        if (sw) { color = sw.dataset.c; render(bd); }
        const em = e.target.closest('[data-emo]');
        if (em) { emoji = em.dataset.emo; render(bd); }
        const cv = e.target.closest('[data-cover]');
        if (cv) { cover = cv.dataset.cover; render(bd); }
      });
      bd.querySelector('#emoInput').addEventListener('input', (e) => { emoji = e.target.value.trim(); const p = bd.querySelector('.ap-preview'); p.innerHTML = folderGlyph({ ...f, color, emoji }, true) + `<strong>${esc(f.name)}</strong>`; });
    },
  });
  if (!r) return;
  try {
    await api(A(`/folders/${f.id}`), { method: 'PATCH', body: { color: r.color, emoji: r.emoji, cover: r.cover } });
    toast('Folder updated', { action: 'Undo', onAction: undoLast });
    bus.emit('drive-changed');
  } catch (e) { fail(e); }
}

/* ------------------------------------------------------------------ rules */
const TYPE_OPTS = [['', 'Any type'], ['document', 'Documents'], ['video', 'Videos'], ['photo', 'Photos'], ['audio', 'Audio'], ['voice', 'Voice'], ['photo,video', 'Photos and videos']];
export async function rulesDialog(folderId, opts = {}) {
  const f = folderId ? S.folderById.get(folderId) : null;
  const cur = f ? folderRules(f) : opts.preset;
  let mode = cur?.mode || (f ? 'auto' : 'smart');
  const p = { ...(cur?.params || {}) };
  let q = cur?.q || '';
  let subjects = S.subjects;
  if (!subjects) { try { subjects = (await api(A('/subjects'))).subjects; S.subjects = subjects; } catch { subjects = []; } }
  const chatName = () => (p.chat_ids ? (S.chatById.get(Number(p.chat_ids))?.title || 'a chat') : 'Any chat');
  const preview = debounce(async (bd) => {
    const out = bd.querySelector('.rule-preview');
    if (!q.trim() && !Object.values(p).some(Boolean)) { out.innerHTML = '<p class="help">Add words or a filter to see what matches.</p>'; return; }
    out.innerHTML = '<p class="help"><span class="spin"></span> Counting…</p>';
    try {
      const r = await api(A('/rules/preview'), { method: 'POST', body: { q, params: p } });
      out.innerHTML = `<p><strong>${plural(r.total, 'file')}</strong> match${mode === 'auto' ? `, <strong>${fmtNum(r.unfiled)}</strong> of them not in a folder yet (those would move here)` : ''}.</p>
        <ul class="rule-sample">${r.sample.map((x) => `<li>${icon(x.kind === 'document' ? 'document' : x.kind)}<span>${esc(x.name)}</span><small>${esc(x.chat_title || '')}</small></li>`).join('')}</ul>`;
    } catch (e) { out.innerHTML = `<p class="warn">${esc(e.message)}</p>`; }
  }, 350);
  const r = await dialog({
    title: f ? `Rule for “${f.name}”` : 'New smart folder',
    wide: true,
    cls: 'rules',
    body: `${f ? '' : `<label class="field"><span>Folder name</span><input id="ruleName" value="${esc(opts.name || '')}" placeholder="e.g. Polity PDFs"></label>`}
      <div class="mode-pick">
        <label class="mode ${mode === 'smart' ? 'on' : ''}"><input type="radio" name="rmode" value="smart" ${mode === 'smart' ? 'checked' : ''}>${icon('sparkle')}<span><strong>Smart folder</strong><small>Shows every file that matches. Nothing is moved, so a file can be in many smart folders.</small></span></label>
        <label class="mode ${mode === 'auto' ? 'on' : ''}"><input type="radio" name="rmode" value="auto" ${mode === 'auto' ? 'checked' : ''}>${icon('wand')}<span><strong>Auto-file</strong><small>Moves matching files that aren't in any folder yet into this folder, now and as new files arrive.</small></span></label>
      </div>
      <div class="adv-grid">
        <label class="field wide"><span>Words <small>same as the search box: polity ext:pdf in:"Vision IAS" -draft</small></span><input id="ruleQ" value="${esc(q)}" placeholder="Words in the name or caption"></label>
        <label class="field"><span>Type</span><select id="ruleKind">${TYPE_OPTS.map(([v, l]) => `<option value="${v}" ${(p.kinds || '') === v ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
        <label class="field"><span>Subject</span><select id="ruleSubj"><option value="">Any subject</option>${subjects.map((s) => `<option value="${esc(s.id)}" ${p.subject === s.id ? 'selected' : ''}>${s.emoji ? `${s.emoji} ` : ''}${esc(s.name)}</option>`).join('')}</select></label>
        <div class="field"><span>From chat</span><div class="pair1"><button class="btn" id="ruleChat">${icon('chat')}<span>${esc(chatName())}</span></button>${p.chat_ids ? `<button class="icon-btn" id="ruleChatClear" aria-label="Any chat">${icon('close')}</button>` : ''}</div></div>
        <label class="field"><span>Extensions</span><input id="ruleExt" value="${esc(p.exts || '')}" placeholder="pdf, epub"></label>
      </div>
      <div class="rule-preview"></div>`,
    actions: [
      f && cur ? { label: 'Remove rule', cls: 'ghost danger', onClick: () => ({ remove: true }) } : null,
      '-',
      { label: 'Cancel' },
      { label: f ? 'Save rule' : 'Create', cls: 'primary', submit: true, onClick: (bd) => ({ save: true, name: bd.querySelector('#ruleName')?.value.trim() }) },
    ].filter(Boolean),
    onOpen: (bd) => {
      const sync = () => {
        q = bd.querySelector('#ruleQ').value;
        const kind = bd.querySelector('#ruleKind').value;
        const subj = bd.querySelector('#ruleSubj').value;
        const ext = bd.querySelector('#ruleExt').value.trim();
        if (kind) p.kinds = kind; else delete p.kinds;
        if (subj) p.subject = subj; else delete p.subject;
        if (ext) p.exts = ext; else delete p.exts;
        preview(bd);
      };
      bd.addEventListener('input', sync);
      bd.addEventListener('change', (e) => {
        if (e.target.name === 'rmode') {
          mode = e.target.value;
          bd.querySelectorAll('.mode').forEach((m) => m.classList.toggle('on', m.querySelector('input').checked));
        }
        sync();
      });
      bd.addEventListener('click', async (e) => {
        if (e.target.closest('#ruleChat')) {
          e.preventDefault();
          const c = await chatPicker({ title: 'Only files from', okLabel: 'Choose' });
          if (c) { p.chat_ids = String(c.chatId); bd.querySelector('#ruleChat span').textContent = chatName(); preview(bd); }
        }
        if (e.target.closest('#ruleChatClear')) { e.preventDefault(); delete p.chat_ids; bd.querySelector('#ruleChat span').textContent = chatName(); preview(bd); }
      });
      preview(bd);
    },
  });
  if (!r) return null;
  const rules = { mode, q: q.trim(), params: p };
  try {
    if (r.remove) {
      await api(A(`/folders/${f.id}`), { method: 'PATCH', body: { rules: null } });
      toast('Rule removed. The folder is an ordinary folder again.');
    } else if (f) {
      await api(A(`/folders/${f.id}`), { method: 'PATCH', body: { rules } });
      if (mode === 'auto') {
        const res = await api(A(`/folders/${f.id}/apply-rules`), { method: 'POST' });
        toast(res.filed ? `Rule saved. Filed ${plural(res.filed, 'file')} into “${f.name}”.` : 'Rule saved. New matching files will be filed here.', { action: 'Undo', onAction: undoLast });
      } else toast('Smart folder updated');
    } else {
      if (!r.name) { toast('Give the folder a name.', { err: true }); return null; }
      const nf = await api(A('/folders'), { method: 'POST', body: { name: r.name, parent_id: opts.parent || null, rules } });
      toast(mode === 'smart' ? `Created smart folder “${r.name}”` : `Created “${r.name}”; matching files are being filed`, { action: 'Undo', onAction: undoLast });
      bus.emit('drive-changed');
      bus.emit('go', `#drive/${nf.id}`);
      return nf;
    }
    bus.emit('drive-changed');
  } catch (e) { fail(e); }
  return null;
}

/* ------------------------------------------------------------ folder menu */
export function folderMenu(anchor, id) {
  const f = S.folderById.get(id);
  if (!f) return;
  const rules = folderRules(f);
  menu(anchor, [
    { label: 'Open', icon: 'folder', onClick: () => bus.emit('go', `#drive/${id}`) },
    { label: 'Open in split view', icon: 'split', onClick: () => import('./split.js').then((m) => m.openSplit(`#drive/${id}`)) },
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
    { label: 'Icon, colour and cover…', icon: 'palette', onClick: () => appearanceDialog(f) },
    {
      label: 'Description…', icon: 'note', onClick: async () => {
        const d = await promptDialog('Folder description', 'Shown in the folder header', f.description || '', 'Save', { multiline: true, allowEmpty: true, max: 500 });
        if (d === null || d === undefined) return;
        try {
          await api(A(`/folders/${id}`), { method: 'PATCH', body: { description: d } });
          toast(d ? 'Description saved' : 'Description removed');
          bus.emit('drive-changed');
        } catch (e) { fail(e); }
      },
    },
    { label: rules ? (f.kind === 'smart' ? 'Edit smart rule…' : 'Edit auto-filing rule…') : 'Auto-file matching files…', icon: rules && f.kind === 'smart' ? 'sparkle' : 'wand', onClick: () => rulesDialog(id) },
    f.kind === 'auto' ? {
      label: 'File matching files now', icon: 'wand', onClick: async () => {
        try { const r = await api(A(`/folders/${id}/apply-rules`), { method: 'POST' }); toast(r.filed ? `Filed ${plural(r.filed, 'file')}` : 'Nothing new to file'); bus.emit('drive-changed'); } catch (e) { fail(e); }
      },
    } : null,
    {
      label: 'Move to…', icon: 'move', onClick: async () => {
        const r = await folderPicker({ title: `Move “${f.name}”`, okLabel: 'Move here', exclude: new Set([id, ...descendantIds(id)]), current: f.parent_id });
        if (!r) return;
        try { await api(A(`/folders/${id}`), { method: 'PATCH', body: { parent_id: r.folderId } }); toast('Folder moved', { action: 'Undo', onAction: undoLast }); bus.emit('drive-changed'); } catch (e) { fail(e); }
      },
    },
    { label: 'Sync with a folder on this computer…', icon: 'sync', onClick: () => import('./sync.js').then((m) => m.addPairDialog(id)) },
    '-',
    f.kind !== 'smart' ? { label: 'Download folder', icon: 'download', onClick: () => downloadFolder(f, false) } : null,
    f.kind !== 'smart' ? { label: 'Download as .zip', icon: 'download', onClick: () => downloadFolder(f, true) } : null,
    { label: 'Playlist for VLC / mpv', icon: 'play', onClick: () => saveDownload(A(`/playlist.m3u?${qs(f.kind === 'smart' && rules ? { ...rules.params, q: rules.q } : { folder_id: id, folder_tree: 1 })}`), `${f.name}.m3u`) },
    '-',
    {
      label: 'Delete folder', icon: 'trash', danger: true, onClick: async () => {
        const subs = descendantIds(id).size;
        const ok = await confirmDialog(`Delete “${f.name}”?`,
          `${subs ? `Its ${plural(subs, 'subfolder')} go too. ` : ''}${f.kind === 'smart' ? 'Nothing happens to the files it shows.' : 'Files inside stay in Telegram and simply leave the folder.'} You can undo this.`, 'Delete folder', true);
        if (!ok) return;
        try {
          await api(A(`/folders/${id}`), { method: 'DELETE' });
          toast('Folder deleted', { action: 'Undo', onAction: undoLast });
          if (S.view.type === 'drive' && (S.view.folderId === id || descendantIds(id).has(S.view.folderId))) bus.emit('go', f.parent_id ? `#drive/${f.parent_id}` : '#drive');
          bus.emit('drive-changed');
        } catch (e) { fail(e); }
      },
    },
  ].filter(Boolean));
}

export async function downloadFolder(f, zip) {
  try {
    const r = await api(A(`/folders/${f.id}/download`), { method: 'POST', body: { zip } });
    toast(`${zip ? 'Zipping' : 'Downloading'} “${f.name}” (${plural(r.ids.length, 'file')})`, { action: 'Show', onAction: () => bus.emit('open-transfers') });
    bus.emit('transfers-changed');
  } catch (e) { fail(e); }
}
export { icon, esc, key };

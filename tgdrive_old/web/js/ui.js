// UI building blocks: toasts (with actions), menus, context menus, dialogs, pickers.
import { $, $$, S, A, api, esc, icon, plural, fmtNum, CHAT_KIND_NAME, hue, initials, busy } from './core.js';

/* ----------------------------------------------------------------- toasts */
export function toast(msg, opts = {}) {
  const { err = false, action, onAction, ms } = typeof opts === 'boolean' ? { err: opts } : opts;
  const el = document.createElement('div');
  el.className = `toast${err ? ' err' : ''}`;
  el.setAttribute('role', err ? 'alert' : 'status');
  el.innerHTML = `<span class="toast-ic">${icon(err ? 'info' : 'check')}</span><span>${esc(msg)}</span>${action ? `<button class="toast-act">${esc(action)}</button>` : ''}`;
  el.querySelector('.toast-act')?.addEventListener('click', () => { dismissToast(el); onAction?.(); });
  $('#toasts').append(el);
  while ($('#toasts').children.length > 4) $('#toasts').firstChild.remove();
  setTimeout(() => dismissToast(el), ms || (action ? 8000 : err ? 6500 : 3500));
  return el;
}
export function dismissToast(el) {
  if (!el?.isConnected || el.classList.contains('leaving')) return;
  el.classList.add('leaving');
  setTimeout(() => el.remove(), 200);
}
export const fail = (e) => { if (e?.name !== 'AbortError' && e?.status !== 423) toast(e?.message || String(e), { err: true }); };

/* ------------------------------------------------------------------ menus */
let openMenu = null;
export function closeMenu() {
  if (!openMenu) return;
  openMenu.anchor?.setAttribute?.('aria-expanded', 'false');
  openMenu.el.remove();
  openMenu = null;
}
export function menuOpen() { return !!openMenu; }

function buildMenu(items) {
  const el = document.createElement('div');
  el.className = 'menu';
  el.setAttribute('role', 'menu');
  el.innerHTML = items.map((it, i) => {
    if (!it) return '';
    if (it === '-') return '<hr>';
    if (it.header) return `<div class="menu-h">${esc(it.header)}</div>`;
    const cls = [it.danger ? 'danger' : '', it.cls || '', it.checked ? 'checked' : ''].join(' ');
    const kbd = it.kbd ? `<kbd>${esc(it.kbd)}</kbd>` : '';
    const inner = it.html || `${it.icon ? icon(it.icon) : '<span class="ic-sp"></span>'}<span class="ml">${esc(it.label)}</span>${it.checked ? icon('check', 'class="chk"') : ''}${kbd}`;
    if (it.href) return `<a role="menuitem" href="${esc(it.href)}" target="_blank" rel="noopener" data-i="${i}" class="${cls}">${inner}</a>`;
    return `<button role="menuitem" data-i="${i}" class="${cls}" ${it.disabled ? 'disabled' : ''}>${inner}</button>`;
  }).join('');
  el.addEventListener('click', (e) => {
    const b = e.target.closest('[data-i]');
    if (!b) return;
    const it = items[+b.dataset.i];
    if (!it.href) e.preventDefault();
    closeMenu();
    it.onClick?.();
  });
  el.addEventListener('keydown', (e) => {
    const btns = $$('button:not([disabled]), a', el);
    const i = btns.indexOf(document.activeElement);
    if (e.key === 'ArrowDown') { e.preventDefault(); btns[(i + 1) % btns.length]?.focus(); }
    if (e.key === 'ArrowUp') { e.preventDefault(); btns[(i - 1 + btns.length) % btns.length]?.focus(); }
    if (e.key === 'Escape') { e.stopPropagation(); const a = openMenu?.anchor; closeMenu(); a?.focus?.(); }
    if (e.key === 'Tab') closeMenu();
  });
  return el;
}

export function menu(anchor, items, opts = {}) {
  closeMenu();
  const el = buildMenu(items);
  document.body.append(el);
  const r = anchor.getBoundingClientRect();
  const w = el.offsetWidth, h = el.offsetHeight;
  const left = opts.alignRight ? r.right - w : r.left;
  el.style.left = `${Math.max(8, Math.min(left, innerWidth - w - 8))}px`;
  el.style.top = `${r.bottom + 4 + h > innerHeight ? Math.max(8, r.top - h - 4) : r.bottom + 4}px`;
  anchor.setAttribute?.('aria-expanded', 'true');
  openMenu = { el, anchor };
  if (!opts.noFocus) el.querySelector('button:not([disabled]), a')?.focus();
}

export function contextMenu(x, y, items) {
  closeMenu();
  const el = buildMenu(items);
  document.body.append(el);
  const w = el.offsetWidth, h = el.offsetHeight;
  el.style.left = `${Math.max(8, Math.min(x, innerWidth - w - 8))}px`;
  el.style.top = `${Math.max(8, Math.min(y, innerHeight - h - 8))}px`;
  openMenu = { el, anchor: null };
  el.querySelector('button:not([disabled]), a')?.focus();
}
document.addEventListener('mousedown', (e) => {
  if (openMenu && !openMenu.el.contains(e.target) && !(openMenu.anchor && openMenu.anchor.contains?.(e.target))) closeMenu();
});
window.addEventListener('blur', closeMenu);
window.addEventListener('resize', closeMenu);

/* ---------------------------------------------------------------- dialogs */
export function dialog({ title, body = '', actions = [], onOpen, wide = false, cls = '' }) {
  return new Promise((resolve) => {
    const bd = document.createElement('div');
    bd.className = 'backdrop';
    bd.innerHTML = `<div class="dialog ${wide ? 'wide' : ''} ${cls}" role="dialog" aria-modal="true" aria-labelledby="dlgTitle">
      <div class="d-head"><h2 id="dlgTitle">${esc(title)}</h2><button class="icon-btn" data-x aria-label="Close">${icon('close')}</button></div>
      <div class="d-body">${body}</div>
      ${actions.length ? `<div class="d-foot">${actions.map((a, i) => a === '-' ? '<span class="spacer"></span>' : `<button class="btn ${a.cls || ''}" data-a="${i}" ${a.submit ? 'data-submit' : ''}>${a.icon ? icon(a.icon) : ''}${esc(a.label)}</button>`).join('')}</div>` : ''}</div>`;
    const prev = document.activeElement;
    let closed = false;
    const done = (v) => {
      if (closed) return;
      closed = true;
      bd.classList.add('leaving');
      setTimeout(() => bd.remove(), 160);
      prev?.focus?.();
      resolve(v);
    };
    bd.addEventListener('mousedown', (e) => { if (e.target === bd) bd.dataset.down = '1'; });
    bd.addEventListener('click', async (e) => {
      if (e.target === bd && bd.dataset.down) return done(null);
      bd.dataset.down = '';
      if (e.target.closest('[data-x]')) return done(null);
      const b = e.target.closest('[data-a]');
      if (!b) return;
      const a = actions[+b.dataset.a];
      if (!a.onClick) return done(null);
      b.disabled = true;
      const tok = busy.start(120, b);
      try {
        const v = await a.onClick(bd);
        if (v !== false) done(v === undefined ? true : v);
      } catch (err) { fail(err); } finally { busy.end(tok); b.disabled = false; }
    });
    bd.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { e.stopPropagation(); done(null); }
      if (e.key === 'Enter' && e.target.tagName === 'INPUT' && !['radio', 'checkbox'].includes(e.target.type)) {
        e.preventDefault();
        bd.querySelector('[data-submit]')?.click();
      }
    });
    bd.close = done;
    $('#layer').append(bd);
    onOpen?.(bd, done);
    (bd.querySelector('input[type=text], input[type=password], input:not([type]), textarea') || bd.querySelector('[data-submit]') || bd.querySelector('button'))?.focus();
  });
}

export function confirmDialog(title, text, label, danger = false) {
  return dialog({
    title, body: `<p>${text}</p>`,
    actions: [{ label: 'Cancel' }, { label, cls: danger ? 'danger solid' : 'primary', submit: true, onClick: () => true }],
  });
}

export function promptDialog(title, label, value = '', okLabel = 'Save', opts = {}) {
  return dialog({
    title,
    body: `<label class="field"><span>${esc(label)}</span>${opts.multiline
      ? `<textarea id="dlgInput" rows="5" maxlength="${opts.max || 2000}">${esc(value)}</textarea>`
      : `<input type="${opts.type || 'text'}" id="dlgInput" value="${esc(value)}" maxlength="${opts.max || 120}" placeholder="${esc(opts.placeholder || '')}">`}</label>
      ${opts.help ? `<p class="help">${opts.help}</p>` : ''}`,
    actions: [{ label: 'Cancel' }, {
      label: okLabel, cls: 'primary', submit: true,
      onClick: (bd) => { const v = $('#dlgInput', bd).value.trim(); return v || opts.allowEmpty ? v : false; },
    }],
    onOpen: (bd) => { const i = $('#dlgInput', bd); if (opts.selectStem && i.value.includes('.')) i.setSelectionRange(0, i.value.lastIndexOf('.')); else i.select?.(); },
  });
}

/* --------------------------------------------------------- folder helpers */
export function childrenOf(parentId) {
  return S.folders.filter((f) => (f.parent_id || null) === (parentId || null))
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base', numeric: true }));
}
export function folderPath(id) {
  const out = [];
  const seen = new Set();
  while (id && S.folderById.has(id) && !seen.has(id)) {
    seen.add(id);
    const f = S.folderById.get(id);
    out.unshift(f);
    id = f.parent_id;
  }
  return out;
}
export function descendantIds(id) {
  const out = new Set();
  const stack = [id];
  while (stack.length) {
    const cur = stack.pop();
    for (const c of childrenOf(cur)) if (!out.has(c.id)) { out.add(c.id); stack.push(c.id); }
  }
  return out;
}
export const folderColor = (f) => (f && f.color ? `var(--fc-${f.color})` : 'var(--folder)');

export function folderPicker({ title, okLabel, exclude = new Set(), current = null, allowNone = true, noneLabel = 'My Drive (not in a folder)' }) {
  let chosen = current || '';
  let filter = '';
  const matches = (f) => !filter || f.name.toLowerCase().includes(filter);
  const anyMatch = (f) => matches(f) || childrenOf(f.id).some(anyMatch);
  const rows = (parent, depth) => childrenOf(parent).filter((f) => !exclude.has(f.id) && anyMatch(f)).map((f) => `
      <label style="padding-left:${8 + depth * 20}px"><input type="radio" name="fp" value="${esc(f.id)}" ${chosen === f.id ? 'checked' : ''}>
      <span class="fold-ic" style="color:${folderColor(f)}">${icon('folder')}</span><span>${esc(f.name)}</span></label>${rows(f.id, depth + 1)}`).join('');
  const render = (bd) => {
    $('.picker', bd).innerHTML = (allowNone && !filter ? `<label><input type="radio" name="fp" value="" ${!chosen ? 'checked' : ''}>
      <span class="fold-ic">${icon('folder')}</span><span>${esc(noneLabel)}</span></label>` : '') + (rows(null, allowNone && !filter ? 1 : 0) || '<p class="help" style="padding:8px">No folders match.</p>');
  };
  return dialog({
    title,
    body: `<input type="search" class="picker-filter" placeholder="Find a folder" aria-label="Find a folder"><div class="picker" role="radiogroup" aria-label="Folders"></div>`,
    actions: [
      {
        label: 'New folder', cls: 'ghost', icon: 'folderPlus', onClick: async (bd) => {
          const name = await promptDialog('New folder', 'Folder name', '', 'Create');
          if (!name) return false;
          const f = await api(A('/folders'), { method: 'POST', body: { name, parent_id: chosen || null } });
          const { loadFolders } = await import('./sidebar.js');
          await loadFolders();
          chosen = f.id;
          render(bd);
          return false;
        },
      },
      '-',
      { label: 'Cancel' },
      { label: okLabel, cls: 'primary', submit: true, onClick: () => ({ folderId: chosen || null }) },
    ],
    onOpen: (bd) => {
      render(bd);
      bd.addEventListener('change', (e) => { if (e.target.name === 'fp') chosen = e.target.value; });
      $('.picker-filter', bd).addEventListener('input', (e) => { filter = e.target.value.trim().toLowerCase(); render(bd); });
    },
  });
}

export function chatAvatar(c, size = '') {
  const name = c ? c.title : '?';
  return `<span class="c-av ${size}" style="--h:${hue(name)}">${esc(initials(name))}</span>`;
}

export function chatPicker({ title, okLabel, filterFn = () => true }) {
  let chosen = null;
  let q = '';
  const render = (bd) => {
    const list = S.chats.filter((c) => c.index_state !== 'gone' && filterFn(c) && (!q || c.title.toLowerCase().includes(q)))
      .sort((a, b) => (a.kind === 'saved' ? -1 : b.kind === 'saved' ? 1 : 0) || (b.file_count - a.file_count)).slice(0, 200);
    $('.picker', bd).innerHTML = list.map((c) => `<label><input type="radio" name="cp" value="${c.id}" ${chosen === c.id ? 'checked' : ''}>
      ${chatAvatar(c, 'sm')}<span class="grow">${esc(c.title)}</span><small>${esc(CHAT_KIND_NAME[c.kind] || '')}</small></label>`).join('') || '<p class="help" style="padding:8px">No chats match.</p>';
  };
  return dialog({
    title,
    body: `<input type="search" class="picker-filter" placeholder="Find a chat" aria-label="Find a chat"><div class="picker" role="radiogroup"></div>`,
    actions: [{ label: 'Cancel' }, { label: okLabel, cls: 'primary', submit: true, onClick: () => (chosen ? { chatId: chosen } : false) }],
    onOpen: (bd) => {
      render(bd);
      bd.addEventListener('change', (e) => { if (e.target.name === 'cp') chosen = Number(e.target.value); });
      $('.picker-filter', bd).addEventListener('input', (e) => { q = e.target.value.trim().toLowerCase(); render(bd); });
      $('.picker-filter', bd).focus();
    },
  });
}

export function tagsDialog(current = [], title = 'Tags') {
  let tags = [...current];
  const known = S.tags.map((t) => t.tag);
  const render = (bd) => {
    $('.tag-edit', bd).innerHTML = tags.map((t, i) => `<span class="chip">${esc(t)}<button data-rm="${i}" aria-label="Remove ${esc(t)}">${icon('close')}</button></span>`).join('')
      + '<input id="tagInput" placeholder="Add a tag and press Enter" list="knownTags" aria-label="New tag">';
    $('#tagInput', bd).focus();
  };
  return dialog({
    title,
    body: `<div class="tag-edit"></div><datalist id="knownTags">${known.map((t) => `<option value="${esc(t)}">`).join('')}</datalist>
      <p class="help">Tags sync to your other devices through the TG Drive channel. A file can have many tags but lives in one folder.</p>
      ${known.length ? `<div class="tag-suggest">${known.slice(0, 16).map((t) => `<button class="chip ghost" data-add="${esc(t)}">${esc(t)}</button>`).join('')}</div>` : ''}`,
    actions: [{ label: 'Cancel' }, {
      label: 'Save', cls: 'primary', submit: true, onClick: (bd) => {
        const v = $('#tagInput', bd).value.trim();
        if (v && !tags.includes(v.toLowerCase())) tags.push(v.toLowerCase());
        return { tags };
      },
    }],
    onOpen: (bd) => {
      render(bd);
      bd.addEventListener('click', (e) => {
        const rm = e.target.closest('[data-rm]');
        if (rm) { tags.splice(+rm.dataset.rm, 1); render(bd); }
        const add = e.target.closest('[data-add]');
        if (add && !tags.includes(add.dataset.add)) { tags.push(add.dataset.add); render(bd); }
      });
      bd.addEventListener('keydown', (e) => {
        if (e.target.id === 'tagInput' && (e.key === 'Enter' || e.key === ',') && e.target.value.trim()) {
          e.preventDefault();
          e.stopPropagation();
          const v = e.target.value.trim().replace(/,$/, '').toLowerCase();
          if (!tags.includes(v)) tags.push(v);
          render(bd);
        } else if (e.target.id === 'tagInput' && e.key === 'Backspace' && !e.target.value && tags.length) {
          tags.pop();
          render(bd);
        }
      }, true);
    },
  });
}

export function shortcutsDialog() {
  const rows = [
    ['/ or Ctrl K', 'Search'], ['Esc', 'Clear selection, close panels'], ['↑ ↓ ← →', 'Move between files'],
    ['Enter', 'Open / preview'], ['Space', 'Quick look'], ['Shift click', 'Select a range'], ['Ctrl A', 'Select all'],
    ['S', 'Star or unstar'], ['T', 'Tags'], ['M', 'Move to folder'], ['D', 'Download'], ['F2', 'Rename'],
    ['L', 'Copy link'], ['Delete', 'Delete from Telegram'], ['Ctrl Z', 'Undo folder change'], ['V', 'Grid or list view'],
    ['G then D / A / S / R / C', 'Go to Drive, All files, Starred, Recent, Continue watching'], ['Ctrl ,', 'Settings'], ['?', 'This list'],
  ];
  return dialog({ title: 'Keyboard shortcuts', body: `<dl class="kbd-list">${rows.map(([k, v]) => `<dt>${k.split(' ').map((x) => (x === 'or' || x === 'then' ? ` ${x} ` : `<kbd>${esc(x)}</kbd>`)).join('')}</dt><dd>${esc(v)}</dd>`).join('')}</dl>`, actions: [{ label: 'Close', cls: 'primary' }] });
}

export function countLabel(n, exactTotal = true) {
  return `${exactTotal ? '' : 'about '}${plural(n, 'file')}`;
}
export { fmtNum };

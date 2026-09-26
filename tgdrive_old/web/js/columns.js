// List view columns: choose which ones show, drag to reorder, drag the edges to resize. Saved in Settings.
import { S, api, esc, icon, fmtSize, fmtDate, fmtDur, KIND_NAME, STREAMABLE, bus } from './core.js';
import { dialog } from './ui.js';

export const COLUMNS = {
  name: { label: 'Name', sort: 'name', w: 'minmax(220px, 3fr)', fixed: true },
  chat: { label: 'Source', sort: 'chat', w: 'minmax(120px, 1.5fr)' },
  folder: { label: 'Folder', w: 'minmax(110px, 1.2fr)' },
  date: { label: 'Date', sort: 'date', w: '112px' },
  size: { label: 'Size', sort: 'size', w: '88px', right: true },
  kind: { label: 'Type', sort: 'type', w: '104px' },
  ext: { label: 'Extension', sort: 'ext', w: '84px' },
  duration: { label: 'Length', sort: 'duration', w: '84px', right: true },
  dims: { label: 'Dimensions', w: '104px' },
  subject: { label: 'Subject', w: '140px' },
  tags: { label: 'Tags', w: 'minmax(100px, 1fr)' },
  sender: { label: 'From', w: 'minmax(100px, 1fr)' },
  caption: { label: 'Caption', w: 'minmax(140px, 2fr)' },
};
const DEFAULT = ['name', 'chat', 'date', 'size', 'kind'];

export function activeColumns() {
  const cols = (S.settings.list_columns || DEFAULT).filter((c) => COLUMNS[c]);
  return cols.includes('name') ? cols : ['name', ...cols];
}

export function template(cols = activeColumns()) {
  const widths = S.settings.list_widths || {};
  return `${cols.map((c) => (widths[c] ? `${widths[c]}px` : COLUMNS[c].w)).join(' ')} 36px`;
}

export function applyTemplate() {
  document.documentElement.style.setProperty('--list-cols', template());
}

export function headHtml() {
  const cols = activeColumns();
  const cell = (k) => {
    const c = COLUMNS[k];
    const on = c.sort && S.sort === c.sort;
    const label = `${esc(c.label)}${on ? icon('down') : ''}`;
    return `<div class="lh-cell ${c.right ? 'right' : ''}" data-col="${k}">${c.sort
      ? `<button class="lh ${on ? `on ${S.order}` : ''}" data-sortcol="${c.sort}">${label}</button>`
      : `<span class="lh">${label}</span>`}<span class="col-resize" data-resize="${k}" aria-hidden="true"></span></div>`;
  };
  return `${cols.map(cell).join('')}<div class="lh-cell"><button class="icon-btn tiny" data-columns title="Choose columns" aria-label="Choose columns">${icon('columns')}</button></div>`;
}

export function cellHtml(k, f, subjectName) {
  switch (k) {
    case 'chat': return `<span class="c-src">${srcCell(f)}</span>`;
    case 'folder': { const fo = f.folder_id && S.folderById.get(f.folder_id); return `<span class="c-folder">${fo ? `${icon('folder')}${esc(fo.name)}` : ''}</span>`; }
    case 'date': return `<span class="c-date">${fmtDate(f.date)}</span>`;
    case 'size': return `<span class="c-size right">${fmtSize(f.size)}</span>`;
    case 'kind': return `<span class="c-kind">${esc(KIND_NAME[f.kind] || '')}</span>`;
    case 'ext': return `<span class="c-ext">${f.ext ? `.${esc(f.ext)}` : ''}</span>`;
    case 'duration': return `<span class="c-dur right">${f.duration && STREAMABLE.has(f.kind) ? `${f.watched ? `<span class="watched-in" title="Watched">${icon('check')}</span>` : f.play_pos ? `<small class="subtle">${fmtDur(f.play_pos)} / </small>` : ''}${fmtDur(f.duration)}` : ''}</span>`;
    case 'dims': return `<span class="c-dims">${f.width && f.height ? `${f.width} × ${f.height}` : ''}</span>`;
    case 'subject': return `<span class="c-subj">${subjectName || ''}</span>`;
    case 'tags': return `<span class="c-tags">${(f.tags || []).map((t) => `<span class="mini-tag">${esc(t)}</span>`).join('')}</span>`;
    case 'sender': return `<span class="c-sender">${esc(f.sender_name || f.fwd_from || '')}</span>`;
    case 'caption': return `<span class="c-cap" title="${esc(f.caption || '')}">${esc((f.caption || '').replace(/\s+/g, ' '))}</span>`;
    default: return '<span></span>';
  }
}

function srcCell(f) {
  return esc(f.chat_title || '');
}

export async function columnsDialog() {
  let cols = activeColumns();
  const render = (bd) => {
    const off = Object.keys(COLUMNS).filter((k) => !cols.includes(k));
    bd.querySelector('.col-list').innerHTML = [...cols, ...off].map((k) => {
      const on = cols.includes(k);
      const i = cols.indexOf(k);
      return `<div class="col-item ${on ? 'on' : ''}" draggable="${on && k !== 'name'}" data-k="${k}">
        <span class="grip" aria-hidden="true">${on && k !== 'name' ? icon('grip') : ''}</span>
        <label><input type="checkbox" ${on ? 'checked' : ''} ${COLUMNS[k].fixed ? 'disabled' : ''} data-toggle="${k}">${esc(COLUMNS[k].label)}</label>
        ${on && k !== 'name' ? `<button class="icon-btn tiny" data-up="${k}" ${i <= 1 ? 'disabled' : ''} aria-label="Move up">${icon('up')}</button>
          <button class="icon-btn tiny" data-downk="${k}" ${i === cols.length - 1 ? 'disabled' : ''} aria-label="Move down">${icon('down')}</button>` : ''}</div>`;
    }).join('');
  };
  const r = await dialog({
    title: 'List columns',
    body: '<p>Tick the columns to show and drag them into order. Drag a column\'s edge in the list header to resize it.</p><div class="col-list"></div>',
    actions: [{ label: 'Reset', cls: 'ghost', onClick: (bd) => { cols = [...DEFAULT]; render(bd); return false; } }, '-', { label: 'Cancel' }, { label: 'Save', cls: 'primary', submit: true, onClick: () => ({ cols }) }],
    onOpen: (bd) => {
      render(bd);
      bd.addEventListener('change', (e) => {
        const k = e.target.dataset.toggle;
        if (!k) return;
        cols = e.target.checked ? [...cols, k] : cols.filter((c) => c !== k);
        render(bd);
      });
      bd.addEventListener('click', (e) => {
        const up = e.target.closest('[data-up]');
        const dn = e.target.closest('[data-downk]');
        const k = up?.dataset.up || dn?.dataset.downk;
        if (!k) return;
        const i = cols.indexOf(k);
        const j = up ? i - 1 : i + 1;
        if (j < 1 || j >= cols.length) return;
        [cols[i], cols[j]] = [cols[j], cols[i]];
        render(bd);
      });
      let dragK = null;
      bd.addEventListener('dragstart', (e) => { dragK = e.target.closest('[data-k]')?.dataset.k; e.dataTransfer.effectAllowed = 'move'; });
      bd.addEventListener('dragover', (e) => { if (dragK && e.target.closest('.col-item.on')) e.preventDefault(); });
      bd.addEventListener('drop', (e) => {
        const t = e.target.closest('.col-item.on')?.dataset.k;
        if (!dragK || !t || t === dragK || t === 'name') return;
        e.preventDefault();
        cols = cols.filter((c) => c !== dragK);
        cols.splice(cols.indexOf(t), 0, dragK);
        dragK = null;
        render(bd);
      });
    },
  });
  if (!r) return;
  await saveColumns(r.cols);
}

export async function saveColumns(cols, widths) {
  const body = {};
  if (cols) body.list_columns = cols;
  if (widths) body.list_widths = widths;
  try {
    const r = await api('/api/settings', { method: 'PATCH', body });
    S.settings = r.settings;
  } catch { if (cols) S.settings.list_columns = cols; if (widths) S.settings.list_widths = widths; }
  applyTemplate();
  bus.emit('columns-changed');
}

// Drag a header edge to resize a column.
document.addEventListener('pointerdown', (e) => {
  const h = e.target.closest('[data-resize]');
  if (!h) return;
  e.preventDefault();
  const k = h.dataset.resize;
  const cell = h.parentElement;
  const startX = e.clientX;
  const startW = cell.getBoundingClientRect().width;
  const widths = { ...(S.settings.list_widths || {}) };
  const move = (ev) => {
    widths[k] = Math.max(60, Math.min(900, Math.round(startW + ev.clientX - startX)));
    S.settings.list_widths = widths;
    applyTemplate();
  };
  const up = () => {
    document.removeEventListener('pointermove', move);
    document.removeEventListener('pointerup', up);
    document.body.classList.remove('resizing');
    saveColumns(null, widths);
  };
  document.body.classList.add('resizing');
  document.addEventListener('pointermove', move);
  document.addEventListener('pointerup', up);
});
document.addEventListener('dblclick', (e) => {
  const h = e.target.closest('[data-resize]');
  if (!h) return;
  const widths = { ...(S.settings.list_widths || {}) };
  delete widths[h.dataset.resize];
  saveColumns(null, widths);
});

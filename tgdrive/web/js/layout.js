// The sidebar: drag its right edge to make it wider or narrower (or Settings → Appearance), and hide it
// with the ☰ button in the top bar, Ctrl+B, or the small « that appears on its edge. On narrow windows it
// slides in over the page instead.
import { $, S, api, icon } from './core.js';

const MIN = 180;
const MAX = 560;
const DEFAULT = 272;
const SNAP = 140;   // dragging narrower than this hides it
const narrow = () => window.matchMedia('(max-width: 900px)').matches;
const clampW = (w) => Math.max(MIN, Math.min(MAX, Math.round(w)));

let saveTimer = 0;
function save(changes) {
  Object.assign(S.settings, changes);
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => api('/api/settings', { method: 'PATCH', body: changes, background: true }).catch(() => {}), 250);
}

export function applySidebar() {
  const root = document.documentElement;
  const w = clampW(Number(S.settings?.sidebar_width) || DEFAULT);
  root.style.setProperty('--sidebar', `${w}px`);
  root.classList.toggle('side-hidden', !!S.settings?.sidebar_hidden);
  const btn = $('#menuBtn');
  if (btn) {
    const hidden = narrow() ? !$('#sidebar').classList.contains('open') : !!S.settings?.sidebar_hidden;
    btn.setAttribute('aria-expanded', String(!hidden));
    btn.title = `${hidden ? 'Show' : 'Hide'} the sidebar (Ctrl B)`;
  }
  const r = $('#sideResizer');
  if (r) r.setAttribute('aria-valuenow', String(w));
  window.dispatchEvent(new Event('resize'));   // lists re-measure their columns
}

export function toggleSidebar(force) {
  if (narrow()) {
    const sb = $('#sidebar');
    sb.classList.toggle('open', force === undefined ? !sb.classList.contains('open') : force);
    applySidebar();
    return;
  }
  const hidden = force === undefined ? !S.settings.sidebar_hidden : !force;
  save({ sidebar_hidden: hidden });
  applySidebar();
}

export function setSidebarWidth(w, persist = true) {
  const v = clampW(w);
  document.documentElement.style.setProperty('--sidebar', `${v}px`);
  if (persist) save({ sidebar_width: v, sidebar_hidden: false });
  return v;
}

export function initSidebar() {
  const sb = $('#sidebar');
  const r = document.createElement('div');
  r.className = 'side-resizer';
  r.id = 'sideResizer';
  r.tabIndex = 0;
  r.setAttribute('role', 'separator');
  r.setAttribute('aria-orientation', 'vertical');
  r.setAttribute('aria-label', 'Sidebar width. Drag, or use the arrow keys. Double-click for the default width.');
  r.setAttribute('aria-valuemin', String(MIN));
  r.setAttribute('aria-valuemax', String(MAX));
  r.innerHTML = `<button class="side-collapse" type="button" tabindex="-1" title="Hide the sidebar (Ctrl B)" aria-label="Hide the sidebar">${icon('chevLeft')}</button>`;
  sb.append(r);
  // A thin strip on the window's left edge brings a hidden sidebar back on hover-click.
  const peek = document.createElement('button');
  peek.className = 'side-peek';
  peek.type = 'button';
  peek.title = 'Show the sidebar (Ctrl B)';
  peek.setAttribute('aria-label', 'Show the sidebar');
  peek.innerHTML = icon('chevron');
  $('#app').append(peek);
  peek.addEventListener('click', () => toggleSidebar(true));

  r.querySelector('.side-collapse').addEventListener('click', (e) => { e.stopPropagation(); toggleSidebar(false); });
  r.addEventListener('dblclick', (e) => { if (!e.target.closest('.side-collapse')) setSidebarWidth(DEFAULT); applySidebar(); });
  r.addEventListener('keydown', (e) => {
    const cur = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--sidebar'), 10) || DEFAULT;
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault();
      setSidebarWidth(cur + (e.key === 'ArrowRight' ? 16 : -16));
      applySidebar();
    } else if (e.key === 'Home' || e.key === 'End') {
      e.preventDefault();
      setSidebarWidth(e.key === 'Home' ? MIN : MAX);
      applySidebar();
    }
  });
  r.addEventListener('pointerdown', (e) => {
    if (e.button !== 0 || e.target.closest('.side-collapse') || narrow()) return;
    e.preventDefault();
    r.setPointerCapture(e.pointerId);
    const left = sb.getBoundingClientRect().left;
    document.documentElement.classList.add('side-resizing');
    let last = null;
    const move = (ev) => {
      const w = ev.clientX - left;
      document.documentElement.classList.toggle('side-will-hide', w < SNAP);
      last = w;
      if (w >= SNAP) setSidebarWidth(w, false);
    };
    const up = () => {
      r.removeEventListener('pointermove', move);
      r.removeEventListener('pointerup', up);
      r.removeEventListener('pointercancel', up);
      document.documentElement.classList.remove('side-resizing', 'side-will-hide');
      if (last === null) return;
      if (last < SNAP) { save({ sidebar_hidden: true }); applySidebar(); return; }
      setSidebarWidth(last);
      applySidebar();
    };
    r.addEventListener('pointermove', move);
    r.addEventListener('pointerup', up);
    r.addEventListener('pointercancel', up);
  });
  $('#menuBtn').addEventListener('click', () => toggleSidebar());
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === 'b') {
      e.preventDefault();
      toggleSidebar();
    }
  });
  window.matchMedia('(max-width: 900px)').addEventListener('change', applySidebar);
  applySidebar();
}

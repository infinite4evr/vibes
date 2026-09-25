// The desktop window's own title bar: the app's top bar doubles as it. Drag it to move the window,
// double-click it to maximize, window buttons at its right end, edges to resize.
// (Settings → Desktop → "Use TG Drive's own title bar" switches back to the system's.)
import { $, callBridge, bridge } from './core.js';

const WIN_ICONS = {
  min: '<path d="M6 12h12"/>',
  max: '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
  restore: '<rect x="8" y="8" width="10" height="10" rx="1.5"/><path d="M6 15V7.5A1.5 1.5 0 0 1 7.5 6H15"/>',
  close: '<path d="M7 7l10 10M17 7 7 17"/>',
};
const svg = (k) => `<svg viewBox="0 0 24 24" aria-hidden="true">${WIN_ICONS[k]}</svg>`;

function setState(state) {
  const maxed = state === 'max' || state === 'full';
  document.documentElement.classList.toggle('maximized', maxed);
  const b = $('.win-ctl [data-win="max"]');
  if (b) { b.innerHTML = svg(maxed ? 'restore' : 'max'); b.title = maxed ? 'Restore' : 'Maximize'; b.setAttribute('aria-label', b.title); }
}

export async function initWindowChrome() {
  if (!bridge.ready) return;
  const mode = await callBridge('windowChrome');
  if (mode !== 'frameless') return;
  document.documentElement.classList.add('frameless');
  const ctl = document.createElement('div');
  ctl.className = 'win-ctl';
  ctl.innerHTML = `<button data-win="min" title="Minimize" aria-label="Minimize">${svg('min')}</button>
    <button data-win="max" title="Maximize" aria-label="Maximize">${svg('max')}</button>
    <button data-win="close" class="close" title="Close" aria-label="Close">${svg('close')}</button>`;
  $('.topbar').append(ctl);
  ctl.addEventListener('click', async (e) => {
    const b = e.target.closest('[data-win]');
    if (!b) return;
    if (b.dataset.win === 'min') callBridge('windowMinimize');
    else if (b.dataset.win === 'max') setState(await callBridge('windowToggleMaximize'));
    else callBridge('windowClose');
  });
  for (const e of ['top', 'bottom', 'left', 'right', 'top-left', 'top-right', 'bottom-left', 'bottom-right']) {
    const d = document.createElement('div');
    d.className = 'win-edge';
    d.dataset.e = e;
    d.addEventListener('pointerdown', (ev) => { if (ev.button === 0) { ev.preventDefault(); callBridge('windowResize', e); } });
    document.body.append(d);
  }
  // Drag the empty parts of the top bar to move the window (starts after a few pixels, so double-click still works).
  const bar = $('.topbar');
  const isEmpty = (t) => !t.closest('button, a, input, select, textarea, [role="menu"], .search, .suggest, .adv, .win-ctl');
  let down = null;
  bar.addEventListener('pointerdown', (e) => { down = e.button === 0 && isEmpty(e.target) ? { x: e.clientX, y: e.clientY } : null; });
  bar.addEventListener('pointermove', (e) => {
    if (!down || !(e.buttons & 1)) { down = null; return; }
    if (Math.abs(e.clientX - down.x) + Math.abs(e.clientY - down.y) > 3) { down = null; callBridge('windowMove'); }
  });
  bar.addEventListener('pointerup', () => { down = null; });
  bar.addEventListener('dblclick', async (e) => { if (isEmpty(e.target)) setState(await callBridge('windowToggleMaximize')); });
  window.tgdrive = window.tgdrive || {};
  window.tgdrive.winState = setState;
  setState(await callBridge('windowState'));
}

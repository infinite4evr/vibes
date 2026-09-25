// Split view: a second, independent TG Drive pane next to the main one. Drag files from one pane onto
// the other (or onto a folder in it) to move them. Each pane has its own location, search and selection.
import { $, S, esc, icon, pref, clamp } from './core.js';

export function openSplit(hash = location.hash) {
  let pane = $('#splitPane');
  if (S.drawer) { S.drawer = null; import('./details.js').then((m) => m.renderDrawer()); }
  const src = `/?embed=1${hash && hash.startsWith('#') ? hash : '#drive'}`;
  if (!pane) {
    pane = document.createElement('section');
    pane.id = 'splitPane';
    pane.className = 'split-pane';
    pane.innerHTML = `<div class="split-bar"><span class="split-grip" title="Drag to resize" aria-hidden="true"></span>${icon('split')}<span class="grow" id="splitTitle">Second pane</span>
        <button class="icon-btn tiny" data-split="swap" title="Show this location in the main pane">${icon('prev')}</button>
        <button class="icon-btn tiny" data-split="close" title="Close split view">${icon('close')}</button></div>
      <iframe id="splitFrame" title="Second pane" src="${esc(src)}"></iframe>`;
    $('#app').append(pane);
    $('#app').classList.add('split');
    const w = Number(pref('splitWidth')) || 0;
    if (w) document.documentElement.style.setProperty('--split-w', `${w}px`);
    const frame = $('#splitFrame');
    frame.addEventListener('load', () => {
      try {
        const upd = () => { $('#splitTitle').textContent = (frame.contentDocument?.title || 'TG Drive').replace(/ · TG Drive$/, '').replace(/^TG Drive · indexing.*$/, 'TG Drive'); };
        upd();
        frame.contentWindow.addEventListener('hashchange', () => setTimeout(upd, 400));
        new MutationObserver(upd).observe(frame.contentDocument.querySelector('title'), { childList: true });
      } catch { /* cross-origin never happens here */ }
    });
  } else {
    $('#splitFrame').src = src;
  }
}

export function closeSplit() {
  $('#splitPane')?.remove();
  $('#app').classList.remove('split');
}

document.addEventListener('click', (e) => {
  const b = e.target.closest('[data-split]');
  if (!b) return;
  if (b.dataset.split === 'close') closeSplit();
  if (b.dataset.split === 'swap') {
    try {
      const h = $('#splitFrame').contentWindow.location.hash;
      $('#splitFrame').contentWindow.location.hash = location.hash;
      location.hash = h;
    } catch { /* ignore */ }
  }
});

// Drag the pane's left edge to resize it.
document.addEventListener('pointerdown', (e) => {
  if (!e.target.closest('.split-grip')) return;
  e.preventDefault();
  const frame = $('#splitFrame');
  frame.style.pointerEvents = 'none';
  const move = (ev) => {
    const w = clamp(window.innerWidth - ev.clientX, 320, window.innerWidth - 480);
    document.documentElement.style.setProperty('--split-w', `${w}px`);
    pref('splitWidth', Math.round(w));
  };
  const up = () => { frame.style.pointerEvents = ''; document.removeEventListener('pointermove', move); document.removeEventListener('pointerup', up); };
  document.addEventListener('pointermove', move);
  document.addEventListener('pointerup', up);
});
export { S };

// Photos: every photo and video on one timeline, grouped by month, with a date scrubber on the right.
// Only the months on screen are loaded, so it stays fast with 100,000+ pictures.
import { $, $$, S, A, api, esc, icon, qs, fmtDur, fmtNum, key, thumbs, thumbUrl, inlineSrc, bus, pref, clamp, plural, copiesParam } from './core.js';
import { fail, contextMenu, chatPicker } from './ui.js';

const SIZES = { s: 112, m: 164, l: 236 };
let P = null;

function filters() {
  const p = { kinds: P.kind || 'photo,video', copies: copiesParam() };
  if (P.chat) p.chat_ids = P.chat;
  if (P.starred) p.starred = 1;
  return p;
}

export async function renderPhotos() {
  const page = $('#pageView');
  P?.destroy?.();
  P = { kind: pref('photosKind') || '', chat: '', starred: false, size: pref('photosSize') || 'm', months: [], cache: new Map(), loading: new Set(), nodes: new Map() };
  page.classList.add('photos-page');
  page.innerHTML = `<div class="ph-head">
      <div class="ph-title"><h1>Photos</h1><span class="subtle" id="phCount"></span></div>
      <div class="ph-filters">
        <div class="seg">${[['', 'All'], ['photo', 'Photos'], ['video', 'Videos']].map(([k, l]) => `<button data-phkind="${k}" class="${P.kind === k ? 'on' : ''}">${l}</button>`).join('')}</div>
        <button class="fchip" data-phchat>${icon('chat')}<span>Any chat</span></button>
        <button class="fchip toggle" data-phstar>${icon('star')}Starred</button>
        <span class="spacer"></span>
        <button class="btn sm" data-phshow>${icon('slides')}Slideshow</button>
        <div class="seg small">${Object.keys(SIZES).map((k) => `<button data-phsize="${k}" class="${P.size === k ? 'on' : ''}" title="${{ s: 'Small', m: 'Medium', l: 'Large' }[k]}">${icon(k === 's' ? 'photos' : k === 'm' ? 'grid' : 'image')}</button>`).join('')}</div>
      </div></div>
    <div class="ph-body"><div class="ph-scroll" id="phScroll"><div class="ph-canvas" id="phCanvas"></div></div>
      <div class="scrubber" id="phScrub" aria-label="Jump to a date"><div class="scrub-marks"></div><div class="scrub-thumb"><span></span></div></div></div>`;
  const scroll = $('#phScroll');
  scroll.addEventListener('scroll', () => schedule(), { passive: true });
  const ro = new ResizeObserver(() => {
    if (!scroll.isConnected) { ro.disconnect(); return; }
    layout(); render();
  });
  ro.observe(scroll);
  P.destroy = () => { ro.disconnect(); page.classList.remove('photos-page'); };
  await loadMonths();
}

async function loadMonths() {
  try {
    const r = await api(A(`/timeline?${qs(filters())}`));
    P.months = r.months;
    P.total = r.total;
    P.cache.clear();
    $('#phCount').textContent = r.total ? plural(r.total, P.kind === 'video' ? 'video' : P.kind === 'photo' ? 'photo' : 'item') : '';
    if (!r.total) {
      $('#phCanvas').innerHTML = `<div class="empty"><h2>No photos or videos here yet</h2><p>They show up as TG Drive indexes your chats.</p></div>`;
      $('#phCanvas').style.height = 'auto';
      $('#phScrub').hidden = true;
      return;
    }
    $('#phScrub').hidden = false;
    layout();
    render();
  } catch (e) { fail(e); }
}

function monthLabel(ym) {
  const [y, m] = ym.split('-').map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
}

function layout() {
  const scroll = $('#phScroll');
  if (!scroll || !P.months.length) return;
  const cs = getComputedStyle(scroll);   // clientWidth includes the padding (room for the date rail)
  const w = scroll.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
  const target = SIZES[P.size];
  const gap = 4;
  P.cols = Math.max(2, Math.floor((w + gap) / (target + gap)));
  P.cell = (w - gap * (P.cols - 1)) / P.cols;
  P.gap = gap;
  const headH = 46;
  let top = 0;
  P.sections = P.months.map((m) => {
    const rows = Math.ceil(m.n / P.cols);
    const s = { ...m, top, headH, rows, h: headH + rows * (P.cell + gap) + 18 };
    top += s.h;
    return s;
  });
  P.height = top;
  $('#phCanvas').style.height = `${top}px`;
  for (const el of P.nodes.values()) el.remove();
  P.nodes.clear();
  drawScrubber();
}

let frame = 0;
function schedule() { if (!frame) frame = requestAnimationFrame(() => { frame = 0; if (!$('#phScroll')) return; render(); updateThumb(); }); }

function visibleSections() {
  const scroll = $('#phScroll');
  const y0 = scroll.scrollTop - scroll.clientHeight;
  const y1 = scroll.scrollTop + scroll.clientHeight * 2;
  return P.sections.filter((s) => s.top + s.h > y0 && s.top < y1);
}

function render() {
  if (!P?.sections || !$('#phScroll')) return;
  const vis = visibleSections();
  const keep = new Set(vis.map((s) => s.ym));
  for (const [ym, el] of P.nodes) if (!keep.has(ym)) { el.remove(); P.nodes.delete(ym); }
  for (const s of vis) {
    if (!P.cache.has(s.ym)) loadMonth(s);
    if (P.nodes.has(s.ym) && P.nodes.get(s.ym).dataset.filled === String(P.cache.get(s.ym)?.length || 0)) continue;
    const el = P.nodes.get(s.ym) || document.createElement('section');
    el.className = 'ph-month';
    el.style.transform = `translateY(${s.top}px)`;
    el.style.height = `${s.h}px`;
    const items = P.cache.get(s.ym) || [];
    el.dataset.filled = String(items.length);
    el.innerHTML = `<h2 class="ph-mh"><span>${esc(monthLabel(s.ym))}</span><small>${fmtNum(s.n)}</small><button class="icon-btn tiny" data-phmonth-show="${s.ym}" title="Slideshow of this month">${icon('slides')}</button></h2>
      <div class="ph-grid" style="grid-template-columns:repeat(${P.cols}, ${P.cell}px);gap:${P.gap}px">${Array.from({ length: s.n }, (_, i) => cellHtml(items[i], s.ym, i)).join('')}</div>`;
    if (!P.nodes.has(s.ym)) { $('#phCanvas').append(el); P.nodes.set(s.ym, el); }
  }
  thumbs.observe($('#phCanvas'));
}

function cellHtml(f, ym, i) {
  if (!f) return `<div class="ph-cell skel" style="height:${P.cell}px"></div>`;
  const video = f.kind === 'video' || f.kind === 'gif' || f.kind === 'round';
  return `<button class="ph-cell" style="height:${P.cell}px" data-ph="${ym}:${i}" title="${esc(f.name)}">
    ${f.inline ? `<img class="lqip" src="${inlineSrc(f.inline)}" alt="">` : ''}${f.has_thumb ? `<img class="real" data-src="${thumbUrl(f, P.size === 'l' ? 'b' : 's')}" alt="" decoding="async">` : `<span class="ph-none">${icon(video ? 'video' : 'photo')}</span>`}
    ${video && f.duration ? `<span class="ph-dur">${icon('play')}${fmtDur(f.duration)}</span>` : ''}${f.starred ? `<span class="ph-star">${icon('star')}</span>` : ''}</button>`;
}

async function loadMonth(s) {
  if (P.loading.has(s.ym)) return;
  P.loading.add(s.ym);
  const out = [];
  const cache = P.cache;
  try {
    let cursor = null;
    do {
      const r = await api(A(`/files?${qs({ ...filters(), date_from: s.ym, date_to: s.ym, sort: 'date', order: 'desc', limit: 500, cursor })}`));
      out.push(...r.items);
      cursor = r.next;
      if (!P || P.cache !== cache) return;
    } while (cursor && out.length < 20000);
    out.forEach((f) => { S.byKey.set(key(f), f); });
    P.cache.set(s.ym, out);
    const el = P.nodes.get(s.ym);
    if (el) el.dataset.filled = '';
    render();
  } catch (e) { if (e.name !== 'AbortError') fail(e); } finally { P?.loading.delete(s.ym); }
}

/* -------------------------------------------------------------- scrubber */
function drawScrubber() {
  const sc = $('#phScrub');
  if (!sc || !P.height) return;
  const h = sc.clientHeight || 1;
  let lastYear = '';
  const marks = [];
  for (const s of P.sections) {
    const y = s.ym.slice(0, 4);
    if (y !== lastYear) {
      marks.push(`<span class="scrub-year" style="top:${(s.top / P.height) * 100}%">${y}</span>`);
      lastYear = y;
    } else marks.push(`<span class="scrub-dot" style="top:${(s.top / P.height) * 100}%"></span>`);
  }
  sc.querySelector('.scrub-marks').innerHTML = marks.join('');
  // Keep year labels from overlapping: hide ones too close to the previous.
  let lastTop = -99;
  for (const el of sc.querySelectorAll('.scrub-year')) {
    const top = parseFloat(el.style.top) / 100 * h;
    el.hidden = top - lastTop < 18;
    if (!el.hidden) lastTop = top;
  }
  updateThumb();
}
function sectionAt(y) {
  let lo = 0, hi = P.sections.length - 1;
  while (lo < hi) { const m = (lo + hi + 1) >> 1; if (P.sections[m].top <= y) lo = m; else hi = m - 1; }
  return P.sections[lo];
}
function updateThumb() {
  const sc = $('#phScrub');
  const scroll = $('#phScroll');
  if (!sc || !P?.sections?.length) return;
  const frac = scroll.scrollTop / Math.max(1, P.height - scroll.clientHeight);
  const th = sc.querySelector('.scrub-thumb');
  th.style.top = `${clamp(frac, 0, 1) * 100}%`;
  th.querySelector('span').textContent = monthLabel(sectionAt(scroll.scrollTop + 60).ym);
}
function scrubTo(clientY) {
  const sc = $('#phScrub');
  const r = sc.getBoundingClientRect();
  const frac = clamp((clientY - r.top) / r.height, 0, 1);
  const s = sectionAt(frac * P.height);
  $('#phScroll').scrollTop = s.top;
  sc.classList.add('dragging');
}
document.addEventListener('pointerdown', (e) => {
  const sc = e.target.closest('#phScrub');
  if (!sc) return;
  e.preventDefault();
  scrubTo(e.clientY);
  const move = (ev) => scrubTo(ev.clientY);
  const up = () => { document.removeEventListener('pointermove', move); document.removeEventListener('pointerup', up); sc.classList.remove('dragging'); };
  document.addEventListener('pointermove', move);
  document.addEventListener('pointerup', up);
});
document.addEventListener('mousemove', (e) => {
  const sc = e.target.closest?.('#phScrub');
  if (!sc || !P?.sections) return;
  const r = sc.getBoundingClientRect();
  const s = sectionAt(clamp((e.clientY - r.top) / r.height, 0, 1) * P.height);
  sc.dataset.hover = monthLabel(s.ym);
  sc.style.setProperty('--hy', `${e.clientY - r.top}px`);
});

/* ---------------------------------------------------------------- events */
function allLoaded() {
  return P.sections.flatMap((s) => P.cache.get(s.ym) || []);
}
document.addEventListener('click', async (e) => {
  if (!P || !$('#phCanvas')) return;
  const k = e.target.closest('[data-phkind]');
  if (k) { P.kind = k.dataset.phkind; pref('photosKind', P.kind); $$('[data-phkind]').forEach((b) => b.classList.toggle('on', b === k)); P.nodes.forEach((n) => n.remove()); P.nodes.clear(); loadMonths(); return; }
  const sz = e.target.closest('[data-phsize]');
  if (sz) { P.size = sz.dataset.phsize; pref('photosSize', P.size); $$('[data-phsize]').forEach((b) => b.classList.toggle('on', b === sz)); layout(); render(); return; }
  if (e.target.closest('[data-phstar]')) { P.starred = !P.starred; e.target.closest('[data-phstar]').classList.toggle('on', P.starred); P.nodes.forEach((n) => n.remove()); P.nodes.clear(); loadMonths(); return; }
  if (e.target.closest('[data-phchat]')) {
    const b = e.target.closest('[data-phchat]');
    if (P.chat) { P.chat = ''; b.classList.remove('on'); b.querySelector('span').textContent = 'Any chat'; }
    else {
      const r = await chatPicker({ title: 'Photos from', okLabel: 'Show' });
      if (!r) return;
      P.chat = String(r.chatId);
      b.classList.add('on');
      b.querySelector('span').textContent = S.chatById.get(r.chatId)?.title || 'Chat';
    }
    P.nodes.forEach((n) => n.remove()); P.nodes.clear();
    loadMonths();
    return;
  }
  if (e.target.closest('[data-phshow]')) {
    const list = allLoaded().filter((f) => f.kind === 'photo');
    if (!list.length) return;
    (await import('./viewer.js')).slideshow(list);
    return;
  }
  const ms = e.target.closest('[data-phmonth-show]');
  if (ms) {
    const list = (P.cache.get(ms.dataset.phmonthShow) || []).filter((f) => f.kind === 'photo');
    if (list.length) (await import('./viewer.js')).slideshow(list);
    return;
  }
  const c = e.target.closest('[data-ph]');
  if (c) {
    const [ym, i] = c.dataset.ph.split(':');
    const f = P.cache.get(ym)?.[+i];
    if (f) (await import('./viewer.js')).openViewer(f, allLoaded());
  }
});
document.addEventListener('contextmenu', async (e) => {
  const c = e.target.closest?.('[data-ph]');
  if (!c || !P) return;
  e.preventDefault();
  const [ym, i] = c.dataset.ph.split(':');
  const f = P.cache.get(ym)?.[+i];
  if (!f) return;
  const { fileMenuItems } = await import('./actions.js');
  contextMenu(e.clientX, e.clientY, fileMenuItems([f]));
});
bus.on('route', () => {});
export { icon };

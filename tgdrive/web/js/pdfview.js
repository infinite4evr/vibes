// PDF reader: pages stream from Telegram as you scroll (pdf.js range requests), with bookmarks,
// highlights with notes, reading position (opens where you stopped) and a side panel. Marks sync
// to your other devices through the TG Drive channel.
import { $, $$, S, A, api, esc, icon, fmtDate, bus, debounce, clamp, plural } from './core.js';
import { toast, fail, confirmDialog, promptDialog } from './ui.js';

const VENDOR = '/static/vendor/pdfjs/';
let lib = null;
async function pdfjs() {
  if (!lib) {
    lib = await import(`${VENDOR}pdf.min.mjs`);
    lib.GlobalWorkerOptions.workerSrc = `${VENDOR}pdf.worker.min.mjs`;
  }
  return lib;
}

export const COLORS = { yellow: '#ffd43b', green: '#8ce99a', blue: '#74c0fc', pink: '#faa2c1', orange: '#ffa94d' };

let R = null;   // the open reader

export async function openPdf(f, stage, bar) {
  closePdf();
  const el = document.createElement('div');
  el.className = 'pdfv';
  el.innerHTML = `<aside class="pdf-side" ${sidePref() ? '' : 'hidden'}>
      <div class="seg pdf-tabs"><button data-ptab="marks" class="on">${icon('bookmark')}Marks</button><button data-ptab="pages">${icon('pages')}Pages</button></div>
      <div class="pdf-side-body"></div></aside>
    <div class="pdf-scroll" tabindex="0"><div class="pdf-pages"></div></div>
    <div class="hl-pop" hidden></div>`;
  stage.replaceChildren(el);
  stage.classList.add('pdf-stage');
  bar.innerHTML = `<button class="icon-btn" data-pdf="side" title="Marks and pages">${icon('menu')}</button>
    <span class="pdf-page"><input type="text" inputmode="numeric" data-pdf-page value="1" aria-label="Page"> / <span data-pdf-total>…</span></span>
    <button class="icon-btn" data-pdf="zoomout" title="Zoom out (−)">${icon('zoomOut')}</button>
    <span class="pdf-zoom" data-pdf-zoomlabel>100%</span>
    <button class="icon-btn" data-pdf="zoomin" title="Zoom in (+)">${icon('zoomIn')}</button>
    <button class="icon-btn" data-pdf="fit" title="Fit width">${icon('maximize')}</button>
    <span class="pdf-sep"></span>
    <button class="icon-btn" data-pdf="bookmark" title="Bookmark this page (B)">${icon('bookmark')}</button>
    <span class="hl-colors" title="Select text, then pick a colour to highlight it">${Object.entries(COLORS).map(([k, c]) => `<button class="hl-dot ${k === hlColor() ? 'on' : ''}" data-hlc="${k}" style="--c:${c}" aria-label="Highlight ${k}"></button>`).join('')}</span>`;
  bar.hidden = false;
  R = { f, el, stage, bar, scale: 0, fit: true, pages: [], marks: [], page: 1, doc: null, destroyed: false };
  el.addEventListener('click', onClick);
  bar.addEventListener('click', onClick);
  bar.addEventListener('change', onChange);
  el.querySelector('.pdf-scroll').addEventListener('scroll', onScroll, { passive: true });
  el.addEventListener('mouseup', onMouseUp);
  document.addEventListener('keydown', onKey, true);
  const ro = new ResizeObserver(debounce(() => { if (R?.fit) setScale('fit'); }, 150));
  ro.observe(el.querySelector('.pdf-scroll'));
  R.ro = ro;
  try {
    const pdf = await pdfjs();
    const url = A(`/stream/${f.chat_id}/${f.msg_id}/${encodeURIComponent(f.name || 'file.pdf')}`);
    const task = pdf.getDocument({
      url, withCredentials: true, rangeChunkSize: 512 * 1024, disableAutoFetch: true, disableStream: false,
      isEvalSupported: false, cMapUrl: `${VENDOR}cmaps/`, cMapPacked: true, standardFontDataUrl: `${VENDOR}standard_fonts/`,
      httpHeaders: { 'X-TGDrive': '1' },
    });
    R.task = task;
    const doc = await task.promise;
    if (!R || R.f !== f) { doc.destroy(); return; }
    R.doc = doc;
    bar.querySelector('[data-pdf-total]').textContent = doc.numPages;
    const first = await doc.getPage(1);
    const vp = first.getViewport({ scale: 1 });
    R.base = { w: vp.width, h: vp.height };
    buildPages(doc.numPages);
    const data = await api(A(`/marks/${f.chat_id}/${f.msg_id}`)).catch(() => ({ marks: [], reading: null }));
    R.marks = data.marks || [];
    setScale('fit');
    renderSide();
    const resume = data.reading?.page;
    if (resume && resume > 1 && resume <= doc.numPages) {
      goPage(resume, false);
      toast(`Continuing at page ${resume}`, { action: 'Start over', onAction: () => goPage(1) });
    }
  } catch (e) {
    if (!R || R.f !== f) return;
    el.querySelector('.pdf-pages').innerHTML = `<div class="v-fallback"><p>This PDF couldn't be opened here (${esc(e.message || e)}).</p>
      <button class="btn" data-v="open">${icon('external')}Open with default app</button><button class="btn" data-v="download">${icon('download')}Download</button></div>`;
  }
}

export function closePdf() {
  if (!R) return;
  R.destroyed = true;
  saveReading.flush?.();
  R.ro?.disconnect();
  R.io?.disconnect();
  try { R.task?.destroy(); } catch { /* ignore */ }
  document.removeEventListener('keydown', onKey, true);
  R.stage?.classList.remove('pdf-stage');
  if (R.bar) { R.bar.innerHTML = ''; R.bar.hidden = true; }
  R = null;
}
export const pdfOpen = () => !!R;

const sidePref = () => { try { return localStorage.getItem('tgdrive.pdfSide') !== '0'; } catch { return true; } };
const hlColor = () => { try { return localStorage.getItem('tgdrive.hlColor') || 'yellow'; } catch { return 'yellow'; } };

function buildPages(n) {
  const host = R.el.querySelector('.pdf-pages');
  host.innerHTML = Array.from({ length: n }, (_, i) => `<div class="pdf-page-box" data-p="${i + 1}"><div class="pdf-hl"></div><span class="pdf-pno">${i + 1}</span></div>`).join('');
  R.pages = $$('.pdf-page-box', host).map((el) => ({ el, rendered: 0, task: null, text: null, w: R.base.w, h: R.base.h }));
  R.io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      const p = +e.target.dataset.p;
      if (e.isIntersecting) renderPage(p);
      else unrenderPage(p);
    }
  }, { root: R.el.querySelector('.pdf-scroll'), rootMargin: '1200px 0px' });
  R.pages.forEach((p) => R.io.observe(p.el));
}

function sizePages() {
  for (const p of R.pages) {
    p.el.style.width = `${Math.floor(p.w * R.scale)}px`;
    p.el.style.height = `${Math.floor(p.h * R.scale)}px`;
    p.el.style.setProperty('--scale-factor', R.scale);
  }
  $('[data-pdf-zoomlabel]', R.bar).textContent = `${Math.round(R.scale * 100)}%`;
}

function setScale(v) {
  if (!R?.doc) return;
  const scroller = R.el.querySelector('.pdf-scroll');
  const keep = R.page;
  if (v === 'fit') {
    R.fit = true;
    R.scale = clamp((scroller.clientWidth - 48) / R.base.w, 0.3, 4);
  } else {
    R.fit = false;
    R.scale = clamp(v, 0.3, 5);
  }
  sizePages();
  for (const p of R.pages) { if (p.rendered) { p.rendered = 0; p.el.querySelector('canvas')?.classList.add('stale'); } }
  goPage(keep, false);
  requestAnimationFrame(renderVisible);
}

// Render the pages on (or near) the screen. Called after zooming and jumping; scrolling uses the observer.
function renderVisible() {
  if (!R?.doc) return;
  const scroller = R.el.querySelector('.pdf-scroll');
  const top = scroller.scrollTop - scroller.clientHeight;
  const bottom = scroller.scrollTop + scroller.clientHeight * 2;
  R.pages.forEach((p, i) => {
    const y = p.el.offsetTop;
    if (y + p.el.offsetHeight >= top && y <= bottom) renderPage(i + 1);
  });
}

async function renderPage(n) {
  const p = R?.pages[n - 1];
  if (!p || !R.doc || !R.scale || p.rendered === R.scale || p.busy) return;
  p.busy = true;
  const scale = R.scale;
  try {
    const page = await R.doc.getPage(n);
    if (!R || R.destroyed) return;
    const vp1 = page.getViewport({ scale: 1 });
    if (Math.abs(vp1.width - p.w) > 0.5 || Math.abs(vp1.height - p.h) > 0.5) {
      p.w = vp1.width; p.h = vp1.height;
      p.el.style.width = `${Math.floor(p.w * R.scale)}px`;
      p.el.style.height = `${Math.floor(p.h * R.scale)}px`;
    }
    const vp = page.getViewport({ scale });
    const dpr = window.devicePixelRatio || 1;
    const canvas = document.createElement('canvas');
    canvas.width = Math.floor(vp.width * dpr);
    canvas.height = Math.floor(vp.height * dpr);
    canvas.style.width = `${Math.floor(vp.width)}px`;
    canvas.style.height = `${Math.floor(vp.height)}px`;
    const ctx = canvas.getContext('2d');
    p.task?.cancel?.();
    p.task = page.render({ canvasContext: ctx, viewport: vp, transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null });
    await p.task.promise;
    if (!R || R.destroyed || scale !== R.scale) return;
    p.el.querySelectorAll('canvas').forEach((c) => c.remove());
    p.el.prepend(canvas);
    p.el.querySelector('.textLayer')?.remove();
    const tl = document.createElement('div');
    tl.className = 'textLayer';
    p.el.append(tl);
    const pdf = await pdfjs();
    const layer = new pdf.TextLayer({ textContentSource: page.streamTextContent(), container: tl, viewport: vp });
    await layer.render();
    p.rendered = scale;
    drawMarks(n);
  } catch (e) {
    if (e?.name !== 'RenderingCancelledException') console.warn('pdf page', n, e);
  } finally {
    p.busy = false;
    if (R && !R.destroyed && p.rendered !== R.scale && R.scale !== scale) renderPage(n);   // zoomed meanwhile
  }
}

function unrenderPage(n) {
  const p = R?.pages[n - 1];
  if (!p || !p.rendered) return;
  p.task?.cancel?.();
  p.el.querySelector('canvas')?.remove();
  p.el.querySelector('.textLayer')?.remove();
  p.rendered = 0;
}

function currentPage() {
  const scroller = R.el.querySelector('.pdf-scroll');
  const mid = scroller.scrollTop + scroller.clientHeight * 0.35;
  let lo = 0, hi = R.pages.length - 1;
  while (lo < hi) {
    const m = (lo + hi + 1) >> 1;
    if (R.pages[m].el.offsetTop <= mid) lo = m; else hi = m - 1;
  }
  return lo + 1;
}

const saveReading = debounce(() => {
  if (!R?.doc) return;
  api(A(`/reading/${R.f.chat_id}/${R.f.msg_id}`), { method: 'PUT', body: { page: R.page, pages: R.doc.numPages } }).catch(() => {});
}, 1500);

function onScroll() {
  if (!R?.doc) return;
  const p = currentPage();
  if (p !== R.page) {
    R.page = p;
    const inp = R.bar.querySelector('[data-pdf-page]');
    if (document.activeElement !== inp) inp.value = p;
    R.bar.querySelector('[data-pdf="bookmark"]').classList.toggle('on', R.marks.some((m) => m.kind === 'bookmark' && m.page === p));
    saveReading();
    $$('.pthumb.on', R.el).forEach((x) => x.classList.remove('on'));
    R.el.querySelector(`.pthumb[data-goto="${p}"]`)?.classList.add('on');
  }
  hidePop();
}

function goPage(n, smooth = true) {
  if (!R?.pages.length) return;
  n = clamp(n, 1, R.pages.length);
  const scroller = R.el.querySelector('.pdf-scroll');
  scroller.scrollTo({ top: R.pages[n - 1].el.offsetTop - 12, behavior: smooth ? 'smooth' : 'auto' });
  R.page = n;
  R.bar.querySelector('[data-pdf-page]').value = n;
  if (!smooth) requestAnimationFrame(renderVisible);
}

/* ------------------------------------------------------------------ marks */
function drawMarks(n) {
  const p = R?.pages[n - 1];
  if (!p) return;
  const layer = p.el.querySelector('.pdf-hl');
  layer.innerHTML = R.marks.filter((m) => m.kind === 'highlight' && m.page === n).map((m) => (m.data?.rects || []).map((r) =>
    `<div class="hl ${m.note ? 'has-note' : ''}" data-mark="${esc(m.id)}" style="left:${r[0] * 100}%;top:${r[1] * 100}%;width:${r[2] * 100}%;height:${r[3] * 100}%;--c:${COLORS[m.color] || COLORS.yellow}"></div>`).join('')).join('');
  p.el.classList.toggle('bookmarked', R.marks.some((m) => m.kind === 'bookmark' && m.page === n));
}

function onMouseUp(e) {
  if (e.target.closest('.hl-pop')) return;
  setTimeout(() => {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return;
    const range = sel.getRangeAt(0);
    const box = range.commonAncestorContainer.nodeType === 1 ? range.commonAncestorContainer : range.commonAncestorContainer.parentElement;
    const pageEl = box?.closest?.('.pdf-page-box') || range.startContainer.parentElement?.closest('.pdf-page-box');
    if (!pageEl || !R) return;
    const text = sel.toString().trim();
    if (!text) return;
    showPop(range.getBoundingClientRect(), `<span class="hl-pop-t">Highlight</span>${Object.entries(COLORS).map(([k, c]) => `<button class="hl-dot ${k === hlColor() ? 'on' : ''}" data-add-hl="${k}" style="--c:${c}" aria-label="${k}"></button>`).join('')}
      <button class="btn sm ghost" data-add-hl-note>${icon('note')}Note</button><button class="btn sm ghost" data-copy-sel>${icon('copy')}</button>`);
    R.pendingSel = { range: range.cloneRange(), pageEl, text };
  }, 10);
}

function rectsFor(range, pageEl) {
  const pr = pageEl.getBoundingClientRect();
  const out = [];
  for (const r of range.getClientRects()) {
    if (r.width < 1 || r.height < 1) continue;
    const x = (Math.max(r.left, pr.left) - pr.left) / pr.width;
    const y = (Math.max(r.top, pr.top) - pr.top) / pr.height;
    const w = (Math.min(r.right, pr.right) - Math.max(r.left, pr.left)) / pr.width;
    const h = (Math.min(r.bottom, pr.bottom) - Math.max(r.top, pr.top)) / pr.height;
    if (w <= 0 || h <= 0) continue;
    // merge with the previous rect when they're on the same line
    const last = out[out.length - 1];
    if (last && Math.abs(last[1] - y) < h * 0.5 && x <= last[0] + last[2] + 0.01) {
      const right = Math.max(last[0] + last[2], x + w);
      last[0] = Math.min(last[0], x); last[2] = right - last[0]; last[3] = Math.max(last[3], h);
    } else out.push([x, y, w, h]);
  }
  return out.map((r) => r.map((v) => Math.round(v * 10000) / 10000));
}

async function addHighlight(color, withNote = false) {
  const ps = R?.pendingSel;
  if (!ps) return;
  const page = +ps.pageEl.dataset.p;
  const rects = rectsFor(ps.range, ps.pageEl);
  window.getSelection()?.removeAllRanges();
  hidePop();
  if (!rects.length) return;
  let note = '';
  if (withNote) {
    note = await promptDialog('Note on highlight', `“${ps.text.slice(0, 120)}${ps.text.length > 120 ? '…' : ''}”`, '', 'Save', { multiline: true, allowEmpty: true, max: 4000 });
    if (note === null || note === undefined) return;
  }
  try { localStorage.setItem('tgdrive.hlColor', color); } catch { /* ignore */ }
  try {
    const m = await api(A(`/marks/${R.f.chat_id}/${R.f.msg_id}`), { method: 'POST', body: { kind: 'highlight', page, color, note, data: { rects, text: ps.text.slice(0, 5000) } } });
    R.marks.push(m);
    drawMarks(page);
    renderSide();
    bus.emit('marks-changed');
  } catch (e) { fail(e); }
}

async function toggleBookmark() {
  const page = R.page;
  const ex = R.marks.find((m) => m.kind === 'bookmark' && m.page === page);
  try {
    if (ex) {
      await api(A(`/marks/${encodeURIComponent(ex.id)}`), { method: 'DELETE' });
      R.marks = R.marks.filter((m) => m !== ex);
      toast(`Bookmark on page ${page} removed`);
    } else {
      const label = await promptDialog('Bookmark', `Name for page ${page}`, `Page ${page}`, 'Add bookmark', { max: 120 });
      if (label === null || label === undefined) return;
      const m = await api(A(`/marks/${R.f.chat_id}/${R.f.msg_id}`), { method: 'POST', body: { kind: 'bookmark', page, data: { title: label || `Page ${page}` } } });
      R.marks.push(m);
      toast(`Bookmarked page ${page}`);
    }
    drawMarks(page);
    renderSide();
    R.bar.querySelector('[data-pdf="bookmark"]').classList.toggle('on', !ex);
    bus.emit('marks-changed');
  } catch (e) { fail(e); }
}

function showPop(rect, html) {
  const pop = R.el.querySelector('.hl-pop');
  pop.innerHTML = html;
  pop.hidden = false;
  const host = R.el.getBoundingClientRect();
  const w = pop.offsetWidth;
  pop.style.left = `${clamp(rect.left + rect.width / 2 - w / 2 - host.left, 8, host.width - w - 8)}px`;
  pop.style.top = `${Math.max(8, rect.top - host.top - pop.offsetHeight - 8)}px`;
}
function hidePop() { const p = R?.el.querySelector('.hl-pop'); if (p) p.hidden = true; }

function markPop(id, anchor) {
  const m = R.marks.find((x) => x.id === id);
  if (!m) return;
  showPop(anchor.getBoundingClientRect(), `${Object.entries(COLORS).map(([k, c]) => `<button class="hl-dot ${m.color === k ? 'on' : ''}" data-recolor="${k}" style="--c:${c}" aria-label="${k}"></button>`).join('')}
    <button class="btn sm ghost" data-edit-note="${esc(id)}">${icon('note')}${m.note ? 'Edit note' : 'Note'}</button>
    <button class="btn sm ghost" data-copy-mark="${esc(id)}">${icon('copy')}</button>
    <button class="btn sm ghost danger" data-del-mark="${esc(id)}">${icon('trash')}</button>
    ${m.note ? `<div class="hl-note">${esc(m.note)}</div>` : ''}`);
  R.popMark = id;
}

async function saveMark(m, changes) {
  try {
    const saved = await api(A(`/marks/${R.f.chat_id}/${R.f.msg_id}`), { method: 'POST', body: { ...m, ...changes } });
    Object.assign(m, saved);
    drawMarks(m.page);
    renderSide();
    bus.emit('marks-changed');
  } catch (e) { fail(e); }
}

/* ------------------------------------------------------------ side panel */
function renderSide() {
  if (!R) return;
  const body = R.el.querySelector('.pdf-side-body');
  const tab = R.el.querySelector('.pdf-tabs .on')?.dataset.ptab || 'marks';
  if (tab === 'pages') {
    body.innerHTML = `<div class="pthumbs">${R.pages.map((p, i) => `<button class="pthumb ${R.page === i + 1 ? 'on' : ''}" data-goto="${i + 1}"><span>${i + 1}</span>${R.marks.some((m) => m.kind === 'bookmark' && m.page === i + 1) ? icon('bookmark') : ''}</button>`).join('')}</div>`;
    return;
  }
  const bms = R.marks.filter((m) => m.kind === 'bookmark').sort((a, b) => a.page - b.page);
  const hls = R.marks.filter((m) => m.kind !== 'bookmark').sort((a, b) => a.page - b.page || (a.data?.rects?.[0]?.[1] || 0) - (b.data?.rects?.[0]?.[1] || 0));
  body.innerHTML = `<div class="side-sec"><div class="side-sec-h">${icon('bookmark')}Bookmarks <small>${bms.length}</small></div>
      ${bms.map((m) => `<div class="mk-row"><button class="mk" data-goto="${m.page}"><span class="mk-p">p. ${m.page}</span><span class="grow">${esc(m.data?.title || `Page ${m.page}`)}</span></button><button class="icon-btn tiny" data-del-mark="${esc(m.id)}" aria-label="Remove">${icon('close')}</button></div>`).join('') || '<p class="help">Press B or the bookmark button to mark a page.</p>'}</div>
    <div class="side-sec"><div class="side-sec-h">${icon('highlight')}Highlights <small>${hls.length}</small>${hls.length ? `<button class="linkish" data-export-marks>Copy all</button>` : ''}</div>
      ${hls.map((m) => `<button class="mk hl-item" data-goto="${m.page}" data-flash="${esc(m.id)}" style="--c:${COLORS[m.color] || COLORS.yellow}"><span class="mk-p">p. ${m.page}</span><span class="hl-text">${esc((m.data?.text || '').slice(0, 220))}</span>${m.note ? `<span class="hl-n">${icon('note')}${esc(m.note.slice(0, 160))}</span>` : ''}</button>`).join('') || '<p class="help">Select text on a page and pick a colour to highlight it. Add a note to any highlight.</p>'}</div>`;
}

function exportText() {
  const hls = R.marks.filter((m) => m.kind !== 'bookmark').sort((a, b) => a.page - b.page);
  return `${R.f.name}\n\n${hls.map((m) => `p. ${m.page}: “${m.data?.text || ''}”${m.note ? `\n   Note: ${m.note}` : ''}`).join('\n\n')}\n`;
}

/* --------------------------------------------------------------- events */
async function onClick(e) {
  if (!R) return;
  const t = e.target.closest('button, .hl, [data-goto]');
  if (!t) { if (!e.target.closest('.hl-pop')) hidePop(); return; }
  const d = t.dataset;
  if (d.pdf === 'side') {
    const side = R.el.querySelector('.pdf-side');
    side.hidden = !side.hidden;
    try { localStorage.setItem('tgdrive.pdfSide', side.hidden ? '0' : '1'); } catch { /* ignore */ }
    if (R.fit) setScale('fit');
    return;
  }
  if (d.pdf === 'zoomin') return setScale(R.scale * 1.2);
  if (d.pdf === 'zoomout') return setScale(R.scale / 1.2);
  if (d.pdf === 'fit') return setScale('fit');
  if (d.pdf === 'bookmark') return toggleBookmark();
  if (d.hlc) {
    try { localStorage.setItem('tgdrive.hlColor', d.hlc); } catch { /* ignore */ }
    $$('[data-hlc]', R.bar).forEach((b) => b.classList.toggle('on', b === t));
    if (R.pendingSel && !window.getSelection()?.isCollapsed) addHighlight(d.hlc);
    else toast('Select text on a page, then pick a colour.');
    return;
  }
  if (d.addHl) return addHighlight(d.addHl);
  if (d.addHlNote !== undefined) return addHighlight(hlColor(), true);
  if (d.copySel !== undefined) { navigator.clipboard.writeText(R.pendingSel?.text || '').then(() => toast('Copied')); hidePop(); return; }
  if (t.classList.contains('hl')) { e.stopPropagation(); markPop(d.mark, t); return; }
  if (d.recolor) { const m = R.marks.find((x) => x.id === R.popMark); if (m) saveMark(m, { color: d.recolor }); hidePop(); return; }
  if (d.editNote) {
    const m = R.marks.find((x) => x.id === d.editNote);
    hidePop();
    if (!m) return;
    const note = await promptDialog('Note on highlight', `“${(m.data?.text || '').slice(0, 120)}”`, m.note || '', 'Save', { multiline: true, allowEmpty: true, max: 4000 });
    if (note !== null && note !== undefined) saveMark(m, { note });
    return;
  }
  if (d.copyMark) { const m = R.marks.find((x) => x.id === d.copyMark); navigator.clipboard.writeText(m?.data?.text || '').then(() => toast('Copied')); hidePop(); return; }
  if (d.delMark) {
    hidePop();
    const m = R.marks.find((x) => x.id === d.delMark);
    try {
      await api(A(`/marks/${encodeURIComponent(d.delMark)}`), { method: 'DELETE' });
      R.marks = R.marks.filter((x) => x.id !== d.delMark);
      if (m) drawMarks(m.page);
      renderSide();
      bus.emit('marks-changed');
    } catch (err) { fail(err); }
    return;
  }
  if (d.ptab) { $$('[data-ptab]', R.el).forEach((b) => b.classList.toggle('on', b === t)); renderSide(); return; }
  if (d.exportMarks !== undefined) { navigator.clipboard.writeText(exportText()).then(() => toast('Highlights copied as text')); return; }
  if (d.goto) {
    goPage(+d.goto);
    if (d.flash) setTimeout(() => $$(`.hl[data-mark="${CSS.escape(d.flash)}"]`, R.el).forEach((h) => { h.classList.add('flash'); setTimeout(() => h.classList.remove('flash'), 1400); }), 500);
  }
}

function onChange(e) {
  if (e.target.matches('[data-pdf-page]')) goPage(parseInt(e.target.value, 10) || 1);
}

function onKey(e) {
  if (!R || e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  if (e.key === '+' || e.key === '=') { e.preventDefault(); e.stopPropagation(); setScale(R.scale * 1.2); }
  else if (e.key === '-') { e.preventDefault(); e.stopPropagation(); setScale(R.scale / 1.2); }
  else if (e.key.toLowerCase() === 'b' && !e.ctrlKey) { e.preventDefault(); e.stopPropagation(); toggleBookmark(); }
  else if (e.key === 'PageDown' || (e.key === 'ArrowRight' && !e.ctrlKey)) { e.preventDefault(); e.stopPropagation(); goPage(R.page + 1); }
  else if (e.key === 'PageUp' || (e.key === 'ArrowLeft' && !e.ctrlKey)) { e.preventDefault(); e.stopPropagation(); goPage(R.page - 1); }
  else if (e.key === 'Home' && e.ctrlKey) { e.preventDefault(); goPage(1); }
  else if (e.key === 'End' && e.ctrlKey) { e.preventDefault(); goPage(R.pages.length); }
}

/* --------------------------------------------- all highlights (a page) */
let marksReq = 0;
export async function renderMarksPage() {
  const page = $('#pageView');
  const req = ++marksReq;
  page.innerHTML = `<div class="page-head"><div><h1>PDF highlights</h1><p>Bookmarks and highlights from every PDF you've read in TG Drive. They sync to your other devices.</p></div>
    <div class="page-right"><button class="btn" data-copy-allmarks>${icon('copy')}Copy all as text</button></div></div><div class="page-loading">Loading…</div>`;
  let r;
  try { r = await api(A('/marks?limit=2000')); } catch (e) { fail(e); return; }
  if (req !== marksReq) return;
  const byFile = new Map();
  for (const m of r.marks) {
    const k = `${m.chat_id}:${m.msg_id}`;
    if (!byFile.has(k)) byFile.set(k, { name: m.name || 'PDF', chat_id: m.chat_id, msg_id: m.msg_id, marks: [], at: m.mtime });
    byFile.get(k).marks.push(m);
  }
  page.querySelector('.page-loading')?.remove();
  const groups = [...byFile.values()];
  page.dataset.text = groups.map((g) => `${g.name}\n${g.marks.sort((a, b) => a.page - b.page).map((m) => (m.kind === 'bookmark' ? `  p. ${m.page} [bookmark] ${m.data?.title || ''}` : `  p. ${m.page}: “${m.data?.text || ''}”${m.note ? ` (note: ${m.note})` : ''}`)).join('\n')}`).join('\n\n');
  page.insertAdjacentHTML('beforeend', groups.length ? groups.map((g) => `<section class="panel marks-file">
      <h2><button class="linkish" data-open-pdf="${g.chat_id}:${g.msg_id}">${icon('document')}${esc(g.name)}</button><small>${plural(g.marks.filter((m) => m.kind !== 'bookmark').length, 'highlight')}, ${plural(g.marks.filter((m) => m.kind === 'bookmark').length, 'bookmark')} · ${fmtDate(Math.round((g.at || 0) / 1000))}</small></h2>
      ${g.marks.sort((a, b) => a.page - b.page).map((m) => (m.kind === 'bookmark'
        ? `<div class="mk-line">${icon('bookmark')}<span class="mk-p">p. ${m.page}</span><span>${esc(m.data?.title || '')}</span></div>`
        : `<div class="mk-line hl-line" style="--c:${COLORS[m.color] || COLORS.yellow}"><span class="mk-p">p. ${m.page}</span><span class="hl-text">${esc(m.data?.text || '')}</span>${m.note ? `<span class="hl-n">${icon('note')}${esc(m.note)}</span>` : ''}</div>`)).join('')}</section>`).join('')
    : `<div class="empty"><h2>No highlights yet</h2><p>Open any PDF, select text and pick a colour to highlight it, or press B to bookmark a page.</p></div>`);
}
document.addEventListener('click', async (e) => {
  const o = e.target.closest('[data-open-pdf]');
  if (o) {
    const [c, m] = o.dataset.openPdf.split(':').map(Number);
    try { const f = await api(A(`/files/${c}/${m}`)); (await import('./viewer.js')).openViewer(f, [f]); } catch (err) { fail(err); }
  }
  if (e.target.closest('[data-copy-allmarks]')) navigator.clipboard.writeText($('#pageView').dataset.text || '').then(() => toast('Copied'));
});
export { confirmDialog };

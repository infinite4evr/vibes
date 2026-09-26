// PDF preview: pages stream from Telegram as you scroll (pdf.js range requests). Zoom, fit to width,
// jump to a page. Text can be selected and copied. Nothing is stored about the file.
import { $, $$, A, esc, icon, debounce, clamp } from './core.js';

const VENDOR = '/static/vendor/pdfjs/';
let lib = null;
async function pdfjs() {
  if (!lib) {
    lib = await import(`${VENDOR}pdf.min.mjs`);
    lib.GlobalWorkerOptions.workerSrc = `${VENDOR}pdf.worker.min.mjs`;
  }
  return lib;
}

// First page only, for the details panel: only the bytes page 1 needs are fetched (range requests).
export async function renderFirstPage(f, canvas, cssWidth, signal) {
  const pdf = await pdfjs();
  const url = A(`/stream/${f.chat_id}/${f.msg_id}/${encodeURIComponent(f.name || 'file.pdf')}`);
  const task = pdf.getDocument({
    url, withCredentials: true, rangeChunkSize: 256 * 1024, disableAutoFetch: true, disableStream: true,
    isEvalSupported: false, cMapUrl: `${VENDOR}cmaps/`, cMapPacked: true, standardFontDataUrl: `${VENDOR}standard_fonts/`,
    httpHeaders: { 'X-TGDrive': '1' },
  });
  const onAbort = () => task.destroy();
  signal?.addEventListener('abort', onAbort, { once: true });
  try {
    const doc = await task.promise;
    const page = await doc.getPage(1);
    const base = page.getViewport({ scale: 1 });
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const vp = page.getViewport({ scale: (cssWidth / base.width) * dpr });
    canvas.width = Math.round(vp.width);
    canvas.height = Math.round(vp.height);
    canvas.style.aspectRatio = `${vp.width} / ${vp.height}`;
    await page.render({ canvasContext: canvas.getContext('2d'), viewport: vp }).promise;
    const pages = doc.numPages;
    doc.destroy();
    return { pages };
  } finally {
    signal?.removeEventListener('abort', onAbort);
  }
}

let R = null;   // the open preview

export async function openPdf(f, stage, bar) {
  closePdf();
  const el = document.createElement('div');
  el.className = 'pdfv';
  el.innerHTML = `<div class="pdf-scroll" tabindex="0"><div class="pdf-pages"></div></div>`;
  stage.replaceChildren(el);
  stage.classList.add('pdf-stage');
  bar.innerHTML = `<span class="pdf-page"><input type="text" inputmode="numeric" data-pdf-page value="1" aria-label="Page"> / <span data-pdf-total>…</span></span>
    <button class="icon-btn" data-pdf="zoomout" title="Zoom out (−)">${icon('zoomOut')}</button>
    <span class="pdf-zoom" data-pdf-zoomlabel>100%</span>
    <button class="icon-btn" data-pdf="zoomin" title="Zoom in (+)">${icon('zoomIn')}</button>
    <button class="icon-btn" data-pdf="fit" title="Fit width">${icon('maximize')}</button>`;
  bar.hidden = false;
  R = { f, el, stage, bar, scale: 0, fit: true, pages: [], page: 1, doc: null, destroyed: false };
  bar.addEventListener('click', onClick);
  bar.addEventListener('change', onChange);
  el.querySelector('.pdf-scroll').addEventListener('scroll', onScroll, { passive: true });
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
    setScale('fit');
  } catch (e) {
    if (!R || R.f !== f) return;
    el.querySelector('.pdf-pages').innerHTML = `<div class="v-fallback"><p>This PDF couldn't be opened here (${esc(e.message || e)}).</p>
      <button class="btn" data-v="open">${icon('external')}Open with default app</button><button class="btn" data-v="download">${icon('download')}Download</button></div>`;
  }
}

export function closePdf() {
  if (!R) return;
  R.destroyed = true;
  R.ro?.disconnect();
  R.io?.disconnect();
  try { R.task?.destroy(); } catch { /* ignore */ }
  document.removeEventListener('keydown', onKey, true);
  R.stage?.classList.remove('pdf-stage');
  if (R.bar) { R.bar.innerHTML = ''; R.bar.hidden = true; }
  R = null;
}
export const pdfOpen = () => !!R;

function buildPages(n) {
  const host = R.el.querySelector('.pdf-pages');
  host.innerHTML = Array.from({ length: n }, (_, i) => `<div class="pdf-page-box" data-p="${i + 1}"><span class="pdf-pno">${i + 1}</span></div>`).join('');
  R.pages = $$('.pdf-page-box', host).map((el) => ({ el, rendered: 0, task: null, w: R.base.w, h: R.base.h }));
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
  if (!R?.doc || !R.base) return;   // the window can resize while the first page is still being read
  const scroller = R.el.querySelector('.pdf-scroll');
  const keep = R.page;
  if (v === 'fit') {
    R.fit = true;
    // Fit the width, but no wider than a comfortable reading column (a page at 230% on a wide screen is hard to read).
    R.scale = clamp(Math.min(scroller.clientWidth - 48, 1000) / R.base.w, 0.3, 4);
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
    p.task?.cancel?.();
    p.task = page.render({ canvasContext: canvas.getContext('2d'), viewport: vp, transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null });
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

function onScroll() {
  if (!R?.doc) return;
  const p = currentPage();
  if (p !== R.page) {
    R.page = p;
    const inp = R.bar.querySelector('[data-pdf-page]');
    if (document.activeElement !== inp) inp.value = p;
  }
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

function onClick(e) {
  if (!R) return;
  const t = e.target.closest('button');
  if (!t) return;
  const d = t.dataset;
  if (d.pdf === 'zoomin') setScale(R.scale * 1.2);
  else if (d.pdf === 'zoomout') setScale(R.scale / 1.2);
  else if (d.pdf === 'fit') setScale('fit');
}

function onChange(e) {
  if (e.target.matches('[data-pdf-page]')) goPage(parseInt(e.target.value, 10) || 1);
}

function onKey(e) {
  if (!R || e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  if (e.key === '+' || e.key === '=') { e.preventDefault(); e.stopPropagation(); setScale(R.scale * 1.2); }
  else if (e.key === '-') { e.preventDefault(); e.stopPropagation(); setScale(R.scale / 1.2); }
  else if (e.key === 'PageDown' || (e.key === 'ArrowRight' && !e.ctrlKey)) { e.preventDefault(); e.stopPropagation(); goPage(R.page + 1); }
  else if (e.key === 'PageUp' || (e.key === 'ArrowLeft' && !e.ctrlKey)) { e.preventDefault(); e.stopPropagation(); goPage(R.page - 1); }
  else if (e.key === 'Home' && e.ctrlKey) { e.preventDefault(); goPage(1); }
  else if (e.key === 'End' && e.ctrlKey) { e.preventDefault(); goPage(R.pages.length); }
}

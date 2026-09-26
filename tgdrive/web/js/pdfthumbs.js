// First pages of PDFs as card pictures. Most PDFs on Telegram have no preview, so the grid would show
// only a generic icon. The first time a PDF card is on screen, its first page is drawn here with pdf.js
// (only the bytes page 1 needs are fetched) and the picture is kept by the server, so later it loads
// like any other thumbnail. Two at a time, only for cards still on screen.
import { A, S } from './core.js';

const queue = [];
let active = 0;
const MAX = 2;
const WIDTH = 360;

// Cards are only drawn while they're on (or near) the screen: a card scrolled past waits until it's back.
const io = new IntersectionObserver((entries) => {
  for (const e of entries) {
    const img = e.target;
    if (!img.isConnected || ['rendering', 'done', 'failed'].includes(img.dataset.pdfState)) { io.unobserve(img); continue; }
    const i = queue.indexOf(img);
    if (e.isIntersecting && i < 0) queue.push(img);
    else if (!e.isIntersecting && i >= 0) queue.splice(i, 1);
  }
  pump();
}, { rootMargin: '300px 0px' });

export function enqueue(img) {
  if (S.settings?.pdf_card_previews === false || img.dataset.pdfState) return;
  img.dataset.pdfState = 'waiting';
  io.observe(img);
}

function pump() {
  while (active < MAX && queue.length) {
    const img = queue.shift();
    if (!img.isConnected) continue;
    io.unobserve(img);
    active++;
    render(img).finally(() => { active--; pump(); });
  }
}

async function render(img) {
  const [cid, mid] = img.dataset.pdf.split(':').map(Number);
  img.dataset.pdfState = 'rendering';
  img.closest('.thumb')?.classList.add('pdf-rendering');
  const canvas = document.createElement('canvas');
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 45000);
  try {
    const { renderFirstPage } = await import('./pdfview.js');
    await renderFirstPage({ chat_id: cid, msg_id: mid, name: 'file.pdf' }, canvas, WIDTH / Math.min(2, window.devicePixelRatio || 1), ctl.signal);
    const blob = await new Promise((res) => canvas.toBlob(res, 'image/webp', 0.78));
    if (!blob) throw new Error('no picture');
    if (img.isConnected) {
      img.src = URL.createObjectURL(blob);
      img.onload = () => { img.classList.add('loaded'); img.closest('.thumb')?.classList.add('has-img', 'pdf-page'); };
    }
    img.dataset.pdfState = 'done';
    await fetch(A(`/docthumb/${cid}/${mid}`), { method: 'PUT', body: blob, credentials: 'same-origin', headers: { 'X-TGDrive': '1', 'X-TGDrive-Bg': '1' } });
  } catch (e) {
    img.dataset.pdfState = 'failed';
    // A broken or password-protected PDF: remember, so it isn't fetched again. A cut connection is not
    // the file's fault: it can be tried again later.
    if (!ctl.signal.aborted && !/network|fetch|abort|stream/i.test(String(e?.message || e))) {
      fetch(A(`/docthumb/${cid}/${mid}/failed`), { method: 'POST', credentials: 'same-origin', headers: { 'X-TGDrive': '1', 'X-TGDrive-Bg': '1' } }).catch(() => {});
    }
  } finally {
    clearTimeout(timer);
    img.closest('.thumb')?.classList.remove('pdf-rendering');
  }
}

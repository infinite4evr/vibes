// Live previews for the details panel: the real picture, a playable video or song, the first page of a
// PDF, the start of a text file. Starts the moment a file is clicked; switching files stops the old one.
import { S, esc, icon, fmtSize, fmtDur, TEXT_EXT, STREAMABLE, streamUrl, thumbUrl, inlineSrc, extColor, bridge, key, waveHtml, displayName } from './core.js';
import { canPlayInline, savePosition } from './viewer.js';

export const isPdf = (f) => (f.ext || '').toLowerCase() === 'pdf' || f.mime === 'application/pdf';
export const isText = (f) => TEXT_EXT.has((f.ext || '').toLowerCase()) && f.size < 3 * 1024 * 1024;
export const isImageDoc = (f) => f.kind !== 'photo' && (f.mime || '').startsWith('image/') && f.size < 40 * 1024 * 1024;

export function previewKind(f) {
  if (f.kind === 'photo' || isImageDoc(f)) return 'image';
  if (f.kind === 'video' || f.kind === 'round' || f.kind === 'gif') return 'video';
  if (f.kind === 'audio' || f.kind === 'voice') return 'audio';
  if (isPdf(f)) return 'pdf';
  if (isText(f)) return 'text';
  return 'none';
}

let cur = null;   // { key, ctl, media, timer }

export function stopPreview() {
  if (!cur) return;
  clearTimeout(cur.timer);
  cur.ctl.abort();
  if (cur.media) {
    savePosition(cur.f, cur.media);
    cur.media.pause();
    cur.media.removeAttribute('src');
    cur.media.load?.();
  }
  cur = null;
}

const spinner = '<span class="pv-spin" aria-hidden="true"><span class="spin big"></span></span>';

function docIconHtml(f) {
  const ext = (f.ext || (f.kind === 'document' ? 'file' : f.kind) || 'file').slice(0, 5).toUpperCase();
  return `<span class="docicon big" style="--ec:${extColor(f.ext)}"><span class="ext">${esc(ext)}</span></span>`;
}

// Shows `f` in `host`. Heavy media wait a moment, so arrowing through files doesn't start ten streams.
export function mountPreview(host, f, { onOpen } = {}) {
  const k = key(f);
  if (cur && cur.key === k && host.contains(cur.el)) return;   // same file, already showing
  stopPreview();
  const ctl = new AbortController();
  const kind = previewKind(f);
  const el = document.createElement('div');
  el.className = `pv pv--${kind} is-loading`;
  el.dataset.kind = kind;
  cur = { key: k, f, ctl, el, media: null, timer: 0 };
  const lq = f.inline ? `<img class="pv-lq" src="${inlineSrc(f.inline)}" alt="" aria-hidden="true">` : '';
  const done = () => el.classList.remove('is-loading');
  const failed = (msg) => {
    el.classList.remove('is-loading');
    el.classList.add('is-failed');
    const note = el.querySelector('.pv-note');
    if (note) note.textContent = msg;
  };

  if (kind === 'image') {
    const src = f.kind === 'photo' ? (f.has_thumb ? thumbUrl(f, 'b') : thumbUrl(f, 'full')) : (f.size < 15 * 1024 * 1024 ? streamUrl(f) : thumbUrl(f, 'b'));
    el.innerHTML = `<button class="pv-open" data-pv-open aria-label="Open ${esc(f.name)}">${lq}<img class="pv-img" alt="" decoding="async">${spinner}
      <span class="pv-hint">${icon('zoomIn')}Open</span></button><p class="pv-note" hidden></p>`;
    const img = el.querySelector('.pv-img');
    img.addEventListener('load', () => { img.classList.add('loaded'); done(); }, { once: true });
    img.addEventListener('error', () => {
      if (f.has_thumb && !img.dataset.fb && src !== thumbUrl(f, 's')) { img.dataset.fb = 1; img.src = thumbUrl(f, 's'); return; }
      el.querySelector('.pv-note').hidden = false;
      failed("Couldn't load the picture. Telegram may be slow; click to try in the viewer.");
    });
    img.src = src;
  } else if (kind === 'video') {
    const poster = f.has_thumb ? thumbUrl(f, 'b') : '';
    const inline = !bridge.ready || canPlayInline(f);
    if (!inline) {
      el.innerHTML = `<button class="pv-open" data-pv-open aria-label="Play ${esc(f.name)}">${lq}${poster ? `<img class="pv-img" src="${poster}" alt="">` : `<span class="pv-glyph">${icon('video')}</span>`}
        <span class="pv-play">${icon('play')}</span>${f.duration ? `<span class="pv-dur">${fmtDur(f.duration)}</span>` : ''}</button>`;
      const img = el.querySelector('.pv-img');
      if (img) { img.addEventListener('load', () => { img.classList.add('loaded'); done(); }, { once: true }); img.addEventListener('error', done, { once: true }); } else done();
    } else {
      const gif = f.kind === 'gif';
      el.innerHTML = `<div class="pv-media ${f.kind === 'round' ? 'round' : ''}">${lq}<video class="pv-video" playsinline ${gif ? 'muted loop autoplay' : 'controls'} preload="metadata" ${poster ? `poster="${poster}"` : ''}></video>${spinner}</div>
        <p class="pv-note" hidden></p>`;
      const v = el.querySelector('video');
      cur.media = v;
      v.addEventListener('loadeddata', done, { once: true });
      v.addEventListener('canplay', done, { once: true });
      v.addEventListener('waiting', () => el.classList.add('is-buffering'));
      v.addEventListener('playing', () => el.classList.remove('is-buffering', 'is-loading'));
      v.addEventListener('pause', () => savePosition(f, v));
      v.addEventListener('ended', () => savePosition(f, v, true));
      v.addEventListener('error', () => {
        el.querySelector('.pv-note').hidden = false;
        failed(v.error?.code === 4 ? "This video's format can't play here. Use Play to open it." : "Couldn't load the video. Telegram may be slow.");
      });
      if (poster) { const im = new Image(); im.onload = done; im.src = poster; }
      cur.timer = setTimeout(() => {
        if (ctl.signal.aborted) return;
        v.src = streamUrl(f);
        const from = f.watched ? 0 : (f.play_pos || 0);
        if (from > 5) v.addEventListener('loadedmetadata', () => { if (from < v.duration - 5) v.currentTime = from; }, { once: true });
      }, 220);
    }
  } else if (kind === 'audio') {
    const voice = f.kind === 'voice' || !f.has_thumb;
    const art = f.has_thumb ? `<img class="pv-img" src="${thumbUrl(f, 'b')}" alt="">` : `<span class="pv-glyph">${icon(f.kind === 'voice' ? 'voice' : 'audio')}</span>`;
    const inline = !bridge.ready || canPlayInline(f);
    el.innerHTML = `<div class="pv-audiobox ${voice ? 'is-voice' : ''}">${voice ? `<div class="pv-wave">${waveHtml(f, 48)}</div>` : ''}<div class="pv-art">${art}</div>
      <div class="pv-atext"><strong>${esc(f.audio_title || displayName(f))}</strong><small>${esc(f.performer || f.chat_title || '')}${f.duration ? ` · ${fmtDur(f.duration)}` : ''}</small></div>
      ${inline ? '<audio controls preload="none"></audio>' : `<button class="btn primary" data-pv-open>${icon('play')}Play</button>`}</div>`;
    const a = el.querySelector('audio');
    if (a) {
      cur.media = a;
      a.addEventListener('pause', () => savePosition(f, a));
      a.addEventListener('ended', () => savePosition(f, a, true));
      cur.timer = setTimeout(() => { if (!ctl.signal.aborted) { a.src = streamUrl(f); a.preload = 'metadata'; } }, 220);
    }
    done();
  } else if (kind === 'pdf') {
    el.innerHTML = `<button class="pv-open" data-pv-open aria-label="Open ${esc(f.name)}"><canvas class="pv-canvas"></canvas>${spinner}
      <span class="pv-hint">${icon('book')}Open</span><span class="pv-badge">PDF</span></button><p class="pv-note" hidden></p>`;
    cur.timer = setTimeout(async () => {
      if (ctl.signal.aborted) return;
      try {
        const m = await import('./pdfview.js');
        const canvas = el.querySelector('canvas');
        const w = Math.max(200, el.clientWidth || 330);
        const r = await m.renderFirstPage(f, canvas, w, ctl.signal);
        if (ctl.signal.aborted) return;
        el.querySelector('.pv-badge').textContent = `PDF · ${r.pages} page${r.pages === 1 ? '' : 's'}`;
        canvas.classList.add('loaded');
        done();
      } catch (e) {
        if (ctl.signal.aborted) return;
        el.querySelector('.pv-open').insertAdjacentHTML('afterbegin', docIconHtml(f));
        el.querySelector('.pv-note').hidden = false;
        failed("Couldn't render a preview of this PDF. Click to open it.");
      }
    }, 180);
  } else if (kind === 'text') {
    el.innerHTML = `<button class="pv-open" data-pv-open aria-label="Open ${esc(f.name)}"><pre class="pv-text"></pre>${spinner}<span class="pv-hint">${icon('eye')}Open</span></button>`;
    cur.timer = setTimeout(async () => {
      try {
        const r = await fetch(streamUrl(f), { credentials: 'include', headers: { Range: 'bytes=0-24575' }, signal: ctl.signal });
        const buf = await r.arrayBuffer();
        let t = new TextDecoder('utf-8', { fatal: false }).decode(buf);
        if (buf.byteLength >= 24576) t = t.replace(/[^\n]*$/, '') + '\n…';
        el.querySelector('.pv-text').textContent = t.slice(0, 6000) || '(empty file)';
        done();
      } catch (e) {
        if (ctl.signal.aborted) return;
        el.querySelector('.pv-text').textContent = "Couldn't load the text.";
        done();
      }
    }, 120);
  } else {
    el.innerHTML = `<div class="pv-none">${docIconHtml(f)}<p>No preview for ${f.ext ? `.${esc(f.ext)}` : 'this kind of'} files</p><small>${fmtSize(f.size)}</small></div>`;
    done();
  }
  el.addEventListener('click', (e) => { if (e.target.closest('[data-pv-open]')) { e.preventDefault(); onOpen?.(f); } });
  host.replaceChildren(el);
  return el;
}

export { STREAMABLE };

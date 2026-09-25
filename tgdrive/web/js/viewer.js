// Viewer: photos, video, audio, voice, round videos, GIFs, PDFs and text, streamed from Telegram.
import { $, S, A, api, esc, icon, fmtSize, fmtDur, fmtDate, STREAMABLE, TEXT_EXT, streamUrl, externalStreamUrl, thumbUrl, inlineSrc, bridge, callBridge, key, bus, extColor } from './core.js';
import { toast, fail } from './ui.js';
import { doDownload, openInTelegram, doOpenLocal, setSelected, refreshCard } from './files.js';

let cur = null;   // { list, i, el }

const viewable = (f) => STREAMABLE.has(f.kind) || f.kind === 'photo' || isPdf(f) || isText(f) || isImageDoc(f);
const isPdf = (f) => (f.ext || '').toLowerCase() === 'pdf' || f.mime === 'application/pdf';
const isText = (f) => TEXT_EXT.has((f.ext || '').toLowerCase()) && f.size < 3 * 1024 * 1024;
const isImageDoc = (f) => (f.mime || '').startsWith('image/') && f.size < 40 * 1024 * 1024;

export function openViewer(f, list) {
  document.querySelectorAll('#drawer video, #drawer audio').forEach((m) => m.pause());
  const items = (list || S.items).filter(viewable);
  let i = items.findIndex((x) => key(x) === key(f));
  if (i < 0) { items.unshift(f); i = 0; }
  if (!cur) {
    const el = document.createElement('div');
    el.className = 'viewer';
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-modal', 'true');
    $('#layer').append(el);
    cur = { el, list: items, i, zoom: false };
    document.addEventListener('keydown', onKey, true);
    el.addEventListener('click', onClick);
  } else Object.assign(cur, { list: items, i });
  render();
}

export function closeViewer() {
  if (!cur) return;
  stopShow();
  if (cur.pdf) import('./pdfview.js').then((m) => m.closePdf());
  const media = cur.el.querySelector('video, audio');
  savePosition(cur.list[cur.i], media);
  if (media && !media.paused && (media.tagName === 'AUDIO')) {
    const f = cur.list[cur.i];
    miniPlayer.play(f, media.currentTime, cur.list.filter((x) => x.kind === 'audio' || x.kind === 'voice'));
  }
  media?.pause();
  const el = cur.el;
  el.classList.add('leaving');
  el.style.pointerEvents = 'none';
  setTimeout(() => el.remove(), 170);
  document.removeEventListener('keydown', onKey, true);
  cur = null;
}

function onKey(e) {
  if (!cur) return;
  const tag = e.target.tagName;
  if (e.key === 'Escape') {
    e.stopPropagation(); e.preventDefault();
    if (cur.show && document.fullscreenElement) { document.exitFullscreen?.(); return; }
    closeViewer(); return;
  }
  if (tag === 'INPUT' || tag === 'TEXTAREA') return;
  if ($('#layer .backdrop')) return;
  if (cur.pdf) return;   // the PDF reader handles its own keys
  if (cur.show && e.key === ' ') { e.preventDefault(); e.stopPropagation(); toggleShow(); return; }
  if (e.key === 'ArrowRight' && !isMediaFocused(e)) { e.preventDefault(); e.stopPropagation(); step(1); }
  if (e.key === 'ArrowLeft' && !isMediaFocused(e)) { e.preventDefault(); e.stopPropagation(); step(-1); }
  if (e.key === ' ' && !isMediaFocused(e)) {
    const m = cur.el.querySelector('video, audio');
    if (m) { e.preventDefault(); e.stopPropagation(); m.paused ? m.play() : m.pause(); }
    else { e.preventDefault(); e.stopPropagation(); closeViewer(); }
  }
  if (e.key.toLowerCase() === 'd' && !e.ctrlKey) { e.stopPropagation(); const f = cur.list[cur.i]; doDownload([[f.chat_id, f.msg_id]]); }
  if (e.key.toLowerCase() === 'f' && !e.ctrlKey) {
    e.stopPropagation();
    const m = cur.el.querySelector('video');
    if (m) m.requestFullscreen?.(); else if (document.fullscreenElement) document.exitFullscreen?.(); else cur.el.requestFullscreen?.();
  }
}
const isMediaFocused = (e) => e.target.tagName === 'VIDEO' || e.target.tagName === 'AUDIO';

function step(d) {
  if (!cur) return;
  const n = cur.list.length;
  if (n < 2) return;
  savePosition(cur.list[cur.i], cur.el.querySelector('video, audio'));
  if (cur.pdf) { import('./pdfview.js').then((m) => m.closePdf()); cur.pdf = false; }
  cur.i = cur.show?.shuffle ? Math.floor(Math.random() * n) : (cur.i + d + n) % n;
  cur.zoom = false;
  render();
  if (cur.show?.playing) scheduleShow();
}

function onClick(e) {
  const a = e.target.closest('[data-v]');
  if (!a) { if (e.target === cur.el || e.target.classList.contains('v-stage')) closeViewer(); return; }
  const f = cur.list[cur.i];
  ({
    close: closeViewer, prev: () => step(-1), next: () => step(1),
    download: () => doDownload([[f.chat_id, f.msg_id]]),
    open: () => doOpenLocal(f),
    telegram: () => openInTelegram(f),
    details: () => { closeViewer(); setSelected([key(f)], key(f)); bus.emit('open-details'); },
    native: () => playNative(f),
    external: () => copyStream(f),
    player: () => api(A(`/play_external/${f.chat_id}/${f.msg_id}`), { method: 'POST' })
      .then((r) => { cur?.el.querySelector('video, audio')?.pause(); toast(`Opened in ${r.player}.`); }).catch(fail),
    zoom: () => { cur.zoom = !cur.zoom; cur.el.querySelector('.v-img')?.classList.toggle('zoomed', cur.zoom); },
    slideshow: () => startShow(),
    showtoggle: () => toggleShow(),
    showshuffle: () => { cur.show.shuffle = !cur.show.shuffle; renderShowBar(); },
    showexit: () => stopShow(true),
    fullscreen: () => { if (document.fullscreenElement) document.exitFullscreen?.(); else cur.el.requestFullscreen?.(); },
    background: () => {
      const m = cur.el.querySelector('audio');
      miniPlayer.play(f, m ? m.currentTime : 0, cur.list.filter((x) => x.kind === 'audio' || x.kind === 'voice'));
      m?.pause();
      closeViewer();
    },
  })[a.dataset.v]?.();
}

// What the embedded view can decode. The desktop app's web engine ships without the patented
// codecs (H.264, HEVC, AAC), which most Telegram videos use; those go to the native player instead.
const PROBE = {
  'video/mp4': 'video/mp4; codecs="avc1.42E01E"', 'video/quicktime': 'video/mp4; codecs="avc1.42E01E"',
  'video/x-matroska': 'video/x-matroska', 'video/3gpp': 'video/3gpp', 'video/x-msvideo': 'video/x-msvideo',
  'audio/mp4': 'audio/mp4; codecs="mp4a.40.2"', 'audio/x-m4a': 'audio/mp4; codecs="mp4a.40.2"',
  'audio/m4a': 'audio/mp4; codecs="mp4a.40.2"', 'audio/aac': 'audio/aac', 'audio/x-wav': 'audio/wav',
};
const probeCache = new Map();
export function canPlayInline(f) {
  const isAudio = f.kind === 'audio' || f.kind === 'voice';
  const mime = (f.mime || (isAudio ? 'audio/mpeg' : 'video/mp4')).toLowerCase().split(';')[0];
  const probe = PROBE[mime] || mime;
  if (!probeCache.has(probe)) probeCache.set(probe, document.createElement(isAudio ? 'audio' : 'video').canPlayType(probe) !== '');
  return probeCache.get(probe);
}
const useNative = (f) => bridge.ready && S.settings.native_player_auto !== false && STREAMABLE.has(f.kind) && !canPlayInline(f);

async function playNative(f) {
  const url = externalStreamUrl(f);
  const ok = await callBridge('playNative', url, f.name);
  if (!ok) copyStream(f);
  else cur?.el.querySelector('video')?.pause();
}
async function copyStream(f) {
  const url = externalStreamUrl(f);
  try { await navigator.clipboard.writeText(url); toast('Stream link copied. In VLC: Media → Open Network Stream, then paste.'); }
  catch { toast(url); }
}

function stageHtml(f) {
  const src = streamUrl(f);
  if (f.kind === 'photo' || isImageDoc(f)) {
    const lq = f.inline ? `<img class="v-lq" src="${inlineSrc(f.inline)}" alt="">` : '';
    const mid = f.has_thumb ? `<img class="v-mid" src="${thumbUrl(f, 'b')}" alt="">` : '';
    return `<div class="v-imgwrap">${lq}${mid}<img class="v-img" data-v="zoom" src="${f.kind === 'photo' && !isImageDoc(f) ? thumbUrl(f, 'full') : src}" alt="${esc(f.name)}"></div>`;
  }
  if ((f.kind === 'video' || f.kind === 'round' || f.kind === 'gif') && useNative(f)) {
    const poster = f.has_thumb ? `<img class="v-poster" src="${thumbUrl(f, 'b')}" alt="">` : (f.inline ? `<img class="v-poster" src="${inlineSrc(f.inline)}" alt="">` : '');
    return `<div class="v-native">${poster}<div class="v-fallback">
        <p>${f.kind === 'gif' ? 'This animation' : 'This video'} plays in the TG Drive player window, streamed as it downloads.</p>
        <button class="btn primary" data-v="native">${icon('play')}Play${f.kind === 'gif' ? '' : ' again'}</button>
        <button class="btn" data-v="external">${icon('link')}Copy stream link for VLC / mpv</button>
        <button class="btn" data-v="download">${icon('download')}Download</button></div></div>`;
  }
  if (f.kind === 'video' || f.kind === 'round' || f.kind === 'gif') {
    const gif = f.kind === 'gif';
    return `<video class="v-video ${f.kind === 'round' ? 'round' : ''}" src="${src}" ${gif ? 'autoplay loop muted playsinline' : 'controls autoplay playsinline'} preload="auto" ${f.has_thumb ? `poster="${thumbUrl(f, 'b')}"` : ''}></video>
      <div class="v-fallback" hidden><p>This video's format can't play inside the window.</p>
        ${bridge.ready ? `<button class="btn primary" data-v="native">${icon('play')}Play in TG Drive player</button>` : ''}
        <button class="btn" data-v="external">${icon('link')}Copy stream link for VLC / mpv</button>
        <button class="btn" data-v="download">${icon('download')}Download</button></div>`;
  }
  if (f.kind === 'audio' || f.kind === 'voice') {
    const art = f.has_thumb ? `<img src="${thumbUrl(f, 'b')}" alt="">` : `<span class="v-audio-ic">${icon(f.kind === 'voice' ? 'voice' : 'audio')}</span>`;
    const player = useNative(f)
      ? `<p class="v-asub">Playing in the TG Drive player window.</p><button class="btn primary" data-v="native">${icon('play')}Play again</button>`
      : `<audio controls autoplay preload="auto" src="${src}"></audio>
      <button class="btn ghost" data-v="background">${icon('audio')}Keep playing in the background</button>`;
    return `<div class="v-audio"><div class="v-art">${art}</div>
      <div class="v-atitle">${esc(f.audio_title || f.name)}</div><div class="v-asub">${esc(f.performer || f.chat_title || '')}</div>
      ${player}</div>`;
  }
  if (isPdf(f)) return '<div class="v-pdfhost"><div class="page-loading"><span class="spin"></span> Opening PDF…</div></div>';
  if (isText(f)) return '<pre class="v-text">Loading…</pre>';
  return `<div class="v-none"><span class="docicon big" style="--ec:${extColor(f.ext)}"><span class="ext">${esc((f.ext || 'file').toUpperCase().slice(0, 5))}</span></span>
    <p>No preview for this kind of file.</p><div class="v-none-acts"><button class="btn primary" data-v="open">${icon('external')}Open with default app</button><button class="btn" data-v="download">${icon('download')}Download</button></div></div>`;
}

function render() {
  const f = cur.list[cur.i];
  const n = cur.list.length;
  cur.el.setAttribute('aria-label', f.name);
  cur.el.innerHTML = `<div class="v-top"><div class="v-title"><strong title="${esc(f.name)}">${esc(f.name)}</strong>
      <small>${fmtSize(f.size)}${f.duration ? ` · ${fmtDur(f.duration)}` : ''} · ${esc(f.chat_title || '')} · ${fmtDate(f.date)}${n > 1 ? ` · ${cur.i + 1} of ${n}` : ''}</small></div>
    <div class="v-tools" hidden></div>
    <div class="v-acts">
      ${isPhotoLike(f) && photoCount() > 1 ? `<button class="icon-btn ${cur.show ? 'on' : ''}" data-v="slideshow" title="Slideshow">${icon('slides')}</button>` : ''}
      <button class="icon-btn" data-v="download" title="Download (D)">${icon('download')}</button>
      <button class="icon-btn" data-v="open" title="Open with default app">${icon('external')}</button>
      <button class="icon-btn" data-v="telegram" title="Open in Telegram">${icon('telegram')}</button>
      ${STREAMABLE.has(f.kind) && bridge.ready ? `<button class="icon-btn" data-v="native" title="Play in TG Drive player">${icon('maximize')}</button>` : ''}
      ${STREAMABLE.has(f.kind) ? `<button class="icon-btn" data-v="player" title="Open in VLC / mpv">${icon('play')}</button>` : ''}
      <button class="icon-btn" data-v="details" title="Details">${icon('info')}</button>
      <button class="icon-btn" data-v="close" title="Close (Esc)">${icon('close')}</button></div></div>
    <div class="v-stage">${stageHtml(f)}</div>
    ${n > 1 ? `<button class="v-nav prev" data-v="prev" aria-label="Previous">${icon('prev')}</button><button class="v-nav next" data-v="next" aria-label="Next">${icon('next')}</button>` : ''}
    ${f.caption ? `<div class="v-caption">${esc(f.caption)}</div>` : ''}`;
  if (isPdf(f)) {
    cur.pdf = true;
    import('./pdfview.js').then((m) => { if (cur && cur.list[cur.i] === f) m.openPdf(f, cur.el.querySelector('.v-pdfhost'), cur.el.querySelector('.v-tools')); });
  } else cur.pdf = false;
  if (cur.show) renderShowBar();
  if (useNative(f) && f.kind !== 'gif') playNative(f);
  wireResume(f, cur.el.querySelector('video, audio'));
  const audio = cur.el.querySelector('audio');
  audio?.addEventListener('error', () => {
    const code = audio.error?.code;
    if ((code === 4 || code === 3) && bridge.ready) playNative(f);
    else if (code) toast(`Playback stopped: ${audio.error?.message || 'network error'}. Telegram may be slow; try again.`, { err: true });
  });
  const video = cur.el.querySelector('video');
  if (video) {
    video.addEventListener('error', () => {
      const code = video.error?.code;
      if (code === 4 || code === 3) {
        video.hidden = true;
        cur.el.querySelector('.v-fallback').hidden = false;
        if (bridge.ready && S.settings.native_player_auto !== false) playNative(f);
      } else if (code) toast(`Playback stopped: ${video.error?.message || 'network error'}. Telegram may be slow; try again.`, { err: true });
    });
    video.addEventListener('ended', () => { if (f.kind !== 'gif' && cur?.list.length > 1 && S.settings.autoplay_next) step(1); });
  }
  const img = cur.el.querySelector('.v-img');
  if (img) {
    img.addEventListener('load', () => img.classList.add('loaded'));
    img.addEventListener('error', () => { if (f.has_thumb && !img.dataset.fb) { img.dataset.fb = 1; img.src = thumbUrl(f, 'b'); } });
  }
  const pre = cur.el.querySelector('.v-text');
  if (pre) {
    fetch(A(`/stream/${f.chat_id}/${f.msg_id}/${encodeURIComponent(f.name)}`), { credentials: 'same-origin' })
      .then((r) => r.text()).then((t) => { pre.textContent = t.slice(0, 1_000_000); }).catch((e) => { pre.textContent = e.message; });
  }
  // Prefetch neighbours' previews.
  for (const d of [1, -1]) {
    const nf = cur.list[(cur.i + d + n) % n];
    if (nf && nf.kind === 'photo' && nf.has_thumb) { const im = new Image(); im.src = thumbUrl(nf, 'b'); }
  }
  api(A(`/files/${f.chat_id}/${f.msg_id}`)).catch(() => {}); // records it under Recent
}

/* ------------------------------------------------------------ slideshow */
const isPhotoLike = (f) => f.kind === 'photo' || isImageDoc(f);
const photoCount = () => (cur ? cur.list.filter(isPhotoLike).length : 0);

export function slideshow(list, start = 0) {
  const pics = list.filter(isPhotoLike);
  if (!pics.length) return;
  openViewer(pics[Math.min(start, pics.length - 1)], pics);
  startShow();
}
function startShow() {
  if (!cur) return;
  cur.list = cur.list.filter(isPhotoLike);
  cur.i = Math.max(0, cur.list.findIndex((x) => x === cur.list[cur.i]));
  cur.show = { playing: true, shuffle: false, timer: 0 };
  cur.el.classList.add('show-mode');
  cur.el.requestFullscreen?.().catch(() => {});
  render();
  scheduleShow();
}
function scheduleShow() {
  clearTimeout(cur?.show?.timer);
  if (!cur?.show?.playing) return;
  const secs = Math.max(1, Number(S.settings.slideshow_seconds) || 4);
  cur.show.timer = setTimeout(() => step(1), secs * 1000);
  const bar = cur.el.querySelector('.show-progress i');
  if (bar) { bar.style.transition = 'none'; bar.style.width = '0%'; void bar.offsetWidth; bar.style.transition = `width ${secs}s linear`; bar.style.width = '100%'; }
}
function toggleShow() {
  if (!cur?.show) return;
  cur.show.playing = !cur.show.playing;
  if (cur.show.playing) scheduleShow(); else clearTimeout(cur.show.timer);
  renderShowBar();
}
function stopShow(keepViewer = false) {
  if (!cur?.show) return;
  clearTimeout(cur.show.timer);
  cur.show = null;
  cur.el.classList.remove('show-mode');
  cur.el.querySelector('.show-bar')?.remove();
  if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {});
  if (keepViewer) render();
}
function renderShowBar() {
  if (!cur?.show) return;
  let bar = cur.el.querySelector('.show-bar');
  if (!bar) { bar = document.createElement('div'); bar.className = 'show-bar'; cur.el.append(bar); }
  const secs = Number(S.settings.slideshow_seconds) || 4;
  bar.innerHTML = `<div class="show-progress"><i></i></div><div class="show-ctl">
    <button class="icon-btn" data-v="prev" aria-label="Previous">${icon('prev')}</button>
    <button class="icon-btn big" data-v="showtoggle" aria-label="${cur.show.playing ? 'Pause' : 'Play'}">${icon(cur.show.playing ? 'pause' : 'play')}</button>
    <button class="icon-btn" data-v="next" aria-label="Next">${icon('next')}</button>
    <select data-show-secs aria-label="Seconds per picture">${[2, 3, 4, 6, 8, 12, 20].map((n) => `<option value="${n}" ${n === secs ? 'selected' : ''}>${n} s</option>`).join('')}</select>
    <button class="icon-btn ${cur.show.shuffle ? 'on' : ''}" data-v="showshuffle" title="Shuffle">${icon('shuffle')}</button>
    <button class="icon-btn" data-v="fullscreen" title="Full screen (F)">${icon('maximize')}</button>
    <button class="icon-btn" data-v="showexit" title="Stop slideshow">${icon('close')}</button></div>`;
  if (cur.show.playing) scheduleShow();
}
document.addEventListener('change', (e) => {
  if (!e.target.matches?.('[data-show-secs]')) return;
  S.settings.slideshow_seconds = Number(e.target.value);
  api('/api/settings', { method: 'PATCH', body: { slideshow_seconds: S.settings.slideshow_seconds } }).catch(() => {});
  scheduleShow();
});

/* ------------------------------------------------------- resume playback */
// Positions are kept per file on this computer (the index), so lectures continue where you stopped,
// in the viewer, the background player and the native player alike.
export function savePosition(f, m, done = false) {
  if (!f || !m || !STREAMABLE.has(f.kind) || f.kind === 'gif') return;
  const dur = Number.isFinite(m.duration) ? m.duration : (f.duration || 0);
  if (!dur || (!done && (dur < 30 || m.currentTime < 3))) return;
  const pos = done ? dur : m.currentTime;
  if (!done && Math.abs(pos - (f.play_pos || 0)) < 1 && !f.watched) return;
  api(A(`/playback/${f.chat_id}/${f.msg_id}`), { method: 'PUT', body: { pos, dur, ...(done ? { done: true } : {}) } })
    .then((r) => { f.play_pos = r.pos; f.play_dur = r.dur; f.watched = r.done; refreshCard(f); })
    .catch(() => {});
}
export async function setWatched(files, done) {
  for (const f of files) {
    await (done ? api(A(`/playback/${f.chat_id}/${f.msg_id}`), { method: 'PUT', body: { pos: 0, dur: f.duration || null, done: true } })
      : api(A(`/playback/${f.chat_id}/${f.msg_id}`), { method: 'DELETE' })).catch(() => {});
    f.watched = done; f.play_pos = 0;
    refreshCard(f);
  }
  toast(done ? 'Marked as watched' : 'Marked as not watched');
}
function wireResume(f, m) {
  if (!m || f.kind === 'gif') return;
  let last = 0;
  m.addEventListener('timeupdate', () => {
    if (m.currentTime - last > 10 || last - m.currentTime > 10) { last = m.currentTime; savePosition(f, m); }
  });
  m.addEventListener('pause', () => { if (!m.ended) savePosition(f, m); });
  m.addEventListener('ended', () => savePosition(f, m, true));
  const from = f.watched ? 0 : (f.play_pos || 0);
  if (from > 5) {
    m.addEventListener('loadedmetadata', () => {
      if (Number.isFinite(m.duration) && from < m.duration - 5) m.currentTime = from;
    }, { once: true });
    const bar = document.createElement('div');
    bar.className = 'v-resume';
    bar.innerHTML = `<span>Continuing from ${fmtDur(from)}</span><button class="btn" data-restart>${icon('prev')}Start over</button>`;
    bar.querySelector('[data-restart]').addEventListener('click', (e) => { e.stopPropagation(); m.currentTime = 0; m.play?.(); bar.remove(); });
    cur.el.querySelector('.v-stage')?.append(bar);
    setTimeout(() => bar.remove(), 7000);
  }
}

/* ------------------------------------------------------------ mini player */
export const miniPlayer = (() => {
  let queue = [];
  let idx = 0;
  let audio = null;
  const el = () => $('#miniPlayer');
  function render() {
    const f = queue[idx];
    const m = el();
    if (!f) { m.hidden = true; return; }
    m.hidden = false;
    m.innerHTML = `<button class="icon-btn" data-mp="prev" aria-label="Previous">${icon('prev')}</button>
      <button class="icon-btn mp-play" data-mp="toggle" aria-label="Play or pause">${icon(audio && !audio.paused ? 'pause' : 'play')}</button>
      <button class="icon-btn" data-mp="next" aria-label="Next">${icon('next')}</button>
      <div class="mp-info"><strong>${esc(f.audio_title || f.name)}</strong><small>${esc(f.performer || f.chat_title || '')}</small>
        <input type="range" min="0" max="1000" value="0" class="mp-seek" aria-label="Position"></div>
      <span class="mp-time">0:00</span>
      <button class="icon-btn" data-mp="close" aria-label="Stop">${icon('close')}</button>`;
  }
  function load(start = 0) {
    const f = queue[idx];
    if (!f) return;
    if (audio) { savePosition(queue[idx], audio); audio.pause(); }
    audio = new Audio(streamUrl(f));
    audio.currentTime = start || (!f.watched && f.play_pos > 5 ? f.play_pos : 0);
    audio.play().catch(() => {});
    audio.addEventListener('timeupdate', () => {
      const m = el();
      const seek = m.querySelector('.mp-seek');
      if (seek && !seek.matches(':active') && audio.duration) seek.value = String(Math.round((audio.currentTime / audio.duration) * 1000));
      const t = m.querySelector('.mp-time');
      if (t) t.textContent = `${fmtDur(audio.currentTime)} / ${fmtDur(audio.duration || f.duration || 0)}`;
    });
    let last = 0;
    const cf = f;
    audio.addEventListener('timeupdate', () => { if (Math.abs(audio.currentTime - last) > 10) { last = audio.currentTime; savePosition(cf, audio); } });
    audio.addEventListener('ended', () => { savePosition(cf, audio, true); if (idx < queue.length - 1) { idx++; load(); render(); } else render(); });
    audio.addEventListener('error', () => { toast(`Couldn't play “${f.name}”. Telegram may be slow, or the format isn't supported here.`, { err: true }); render(); });
    audio.addEventListener('play', render);
    audio.addEventListener('pause', render);
    if ('mediaSession' in navigator) {
      navigator.mediaSession.metadata = new window.MediaMetadata({ title: f.audio_title || f.name, artist: f.performer || f.chat_title || '' });
      navigator.mediaSession.setActionHandler('nexttrack', () => ctl('next'));
      navigator.mediaSession.setActionHandler('previoustrack', () => ctl('prev'));
    }
    render();
  }
  function ctl(a) {
    if (a === 'toggle' && audio) audio.paused ? audio.play() : audio.pause();
    if (a === 'next' && idx < queue.length - 1) { idx++; load(); }
    if (a === 'prev') { if (audio && audio.currentTime > 5) audio.currentTime = 0; else if (idx > 0) { idx--; load(); } }
    if (a === 'close') { if (audio) savePosition(queue[idx], audio); audio?.pause(); audio = null; queue = []; render(); }
  }
  document.addEventListener('click', (e) => { const b = e.target.closest('[data-mp]'); if (b) ctl(b.dataset.mp); });
  document.addEventListener('input', (e) => {
    if (e.target.classList?.contains('mp-seek') && audio?.duration) audio.currentTime = (Number(e.target.value) / 1000) * audio.duration;
  });
  return {
    play(f, start = 0, list = [f]) {
      // Tracks the page can't decode (desktop app: AAC/M4A) play in the native player instead.
      queue = (list.length ? list : [f]).filter((x) => key(x) === key(f) || !useNative(x));
      idx = Math.max(0, queue.findIndex((x) => key(x) === key(f)));
      load(start);
    },
  };
})();
export { fail };

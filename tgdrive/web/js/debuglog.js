// Detailed debug logging (Settings → About & diagnostics, or the account menu).
// While it's on, the page records what it does — navigation, clicks, keyboard shortcuts, every request with
// its timing and result, errors with stack traces, console warnings, slow frames, media errors — and sends
// it in batches to the app, which writes it to tgdrive-debug.log next to the server's own detailed log.
// A large banner stays at the top of the window the whole time, so it's never left on by accident.
import { $, S, api, esc, icon, bus, fmtSize } from './core.js';

let on = false;
let installed = false;
const queue = [];
let flushTimer = 0;
const MAX_QUEUE = 2000;

function send(entries) {
  return fetch('/api/clientlog', {
    method: 'POST', credentials: 'same-origin', keepalive: entries.length < 200,
    headers: { 'X-TGDrive': '1', 'Content-Type': 'application/json' }, body: JSON.stringify({ entries }),
  }).catch(() => {});
}
function flush() {
  clearTimeout(flushTimer);
  flushTimer = 0;
  if (!queue.length) return;
  send(queue.splice(0, 400));
  if (queue.length) flushTimer = setTimeout(flush, 300);
}
export function dlog(level, cat, msg, data) {
  if (!on) return;
  if (queue.length >= MAX_QUEUE) queue.shift();
  queue.push({ t: Date.now() / 1000, level, cat, msg: String(msg).slice(0, 4000), data });
  if (level === 'error' || queue.length >= 150) flush();
  else if (!flushTimer) flushTimer = setTimeout(flush, 1500);
}

const describe = (el) => {
  if (!el) return '?';
  const label = el.getAttribute('aria-label') || el.getAttribute('title') || el.textContent || el.value || '';
  const data = Object.entries(el.dataset || {}).filter(([k]) => k !== 'i' && k !== 'state').map(([k, v]) => `${k}=${String(v).slice(0, 60)}`).join(' ');
  return `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ''} “${label.replace(/\s+/g, ' ').trim().slice(0, 70)}”${data ? ` [${data}]` : ''}`;
};

function install() {
  if (installed) return;
  installed = true;
  bus.on('api', (r) => {
    if (!on) return;
    const path = r.path.replace(/([?&](t|token)=)[^&]+/g, '$1…');
    if (r.aborted) { dlog('debug', 'api', `${r.method} ${path} aborted after ${Math.round(r.ms)} ms`); return; }
    const quietPoll = /\/(status|events)(\?|$)/.test(path) && r.status === 200 && r.ms < 1000;
    if (quietPoll) return;
    const lvl = r.status === 0 || r.status >= 500 ? 'error' : r.status >= 400 ? 'warn' : 'debug';
    let body;
    if (r.body !== undefined) { try { body = JSON.stringify(r.body).slice(0, 1500); } catch { body = '(unserializable)'; } }
    dlog(lvl, 'api', `${r.method} ${path} → ${r.status} in ${Math.round(r.ms)} ms`, r.error || body ? { error: r.error, body } : undefined);
  });
  const origEmit = bus.emit;
  bus.emit = (evt, data) => {
    if (on && evt !== 'api' && evt !== 'header') dlog('debug', 'event', evt, typeof data === 'string' || typeof data === 'number' ? { data } : undefined);
    return origEmit.call(bus, evt, data);
  };
  window.addEventListener('hashchange', () => dlog('info', 'nav', `→ ${decodeURIComponent(location.hash)}`));
  document.addEventListener('click', (e) => {
    const el = e.target.closest?.('button, a, [role="menuitem"], [role="option"], .card, .row, .fitem, .nav-item, [data-go], input[type=checkbox]');
    if (el) dlog('debug', 'ui', `click ${describe(el)}${e.shiftKey ? ' +shift' : ''}${e.ctrlKey || e.metaKey ? ' +ctrl' : ''}`);
  }, true);
  document.addEventListener('dblclick', (e) => { const el = e.target.closest?.('.card, .row'); if (el) dlog('debug', 'ui', `double-click ${describe(el)}`); }, true);
  document.addEventListener('contextmenu', (e) => { const el = e.target.closest?.('.card, .row, .fitem, .nav-item'); if (el) dlog('debug', 'ui', `right-click ${describe(el)}`); }, true);
  document.addEventListener('keydown', (e) => {
    const t = e.target;
    const inField = /INPUT|TEXTAREA|SELECT/.test(t?.tagName || '') || t?.isContentEditable;
    if (inField && !(e.ctrlKey || e.metaKey) && !['Enter', 'Escape', 'Tab'].includes(e.key)) return;   // typing isn't logged
    const k = [e.ctrlKey && 'Ctrl', e.metaKey && 'Meta', e.altKey && 'Alt', e.shiftKey && e.key.length > 1 && 'Shift', e.key].filter(Boolean).join('+');
    dlog('debug', 'key', `${k}${inField ? ` in ${t.id || t.tagName.toLowerCase()}` : ''}`);
  }, true);
  document.addEventListener('change', (e) => {
    const t = e.target;
    if (t?.dataset?.set) dlog('info', 'setting', `${t.dataset.set} = ${t.type === 'checkbox' ? t.checked : t.type === 'password' ? '(hidden)' : String(t.value).slice(0, 200)}`);
  }, true);
  window.addEventListener('error', (e) => {
    if (e.target && e.target !== window && (e.target.tagName === 'IMG' || e.target.tagName === 'VIDEO' || e.target.tagName === 'AUDIO' || e.target.tagName === 'SCRIPT' || e.target.tagName === 'LINK')) {
      const t = e.target;
      dlog('warn', 'resource', `${t.tagName.toLowerCase()} failed to load: ${(t.currentSrc || t.src || t.href || '').replace(/([?&]t=)[^&]+/, '$1…').slice(0, 300)}`,
        t.error ? { code: t.error.code, message: t.error.message } : undefined);
      return;
    }
    dlog('error', 'error', e.message || 'error', { source: `${e.filename}:${e.lineno}:${e.colno}`, stack: e.error?.stack?.slice(0, 6000) });
  }, true);
  window.addEventListener('unhandledrejection', (e) => {
    const r = e.reason;
    if (r?.name === 'AbortError') return;
    dlog('error', 'promise', r?.message || String(r), { stack: r?.stack?.slice(0, 6000), status: r?.status });
  });
  for (const lvl of ['error', 'warn']) {
    const orig = console[lvl].bind(console);
    console[lvl] = (...args) => {
      dlog(lvl, 'console', args.map((a) => (a instanceof Error ? `${a.message}\n${a.stack}` : typeof a === 'object' ? (() => { try { return JSON.stringify(a); } catch { return String(a); } })() : String(a))).join(' ').slice(0, 4000));
      orig(...args);
    };
  }
  document.addEventListener('visibilitychange', () => dlog('debug', 'window', document.hidden ? 'hidden' : 'visible'));
  window.addEventListener('online', () => dlog('info', 'window', 'online'));
  window.addEventListener('offline', () => dlog('warn', 'window', 'offline'));
  window.addEventListener('pagehide', flush);
  try {
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) if (e.duration > 200) dlog('warn', 'perf', `page busy for ${Math.round(e.duration)} ms (long task)`, { view: location.hash });
    }).observe({ type: 'longtask', buffered: false });
  } catch { /* not supported */ }
}

function environment() {
  return {
    version: S.version, agent: navigator.userAgent, desktop: S.desktop, view: location.hash,
    screen: `${screen.width}x${screen.height}@${devicePixelRatio}`, window: `${innerWidth}x${innerHeight}`,
    language: navigator.language, online: navigator.onLine, memory: navigator.deviceMemory, cores: navigator.hardwareConcurrency,
    theme: S.settings?.theme, account: S.aid,
  };
}

/* ---------------------------------------------------------------- banner */
function banner() {
  let el = $('#debugBanner');
  if (on && !el && !document.documentElement.classList.contains('embed')) {
    el = document.createElement('div');
    el.id = 'debugBanner';
    el.className = 'debug-banner';
    el.setAttribute('role', 'status');
    el.innerHTML = `<span class="db-ic">${icon('bug')}</span>
      <div class="db-text"><strong>DEBUG LOGGING IS ON</strong><span>Everything TG Drive and this window do is being written to <code>tgdrive-debug.log</code><span class="db-size"></span>. Turn it off when you're done.</span></div>
      <button class="btn sm" data-debug="view">${icon('document')}View log</button>
      <button class="btn sm" data-debug="clear">${icon('trash')}Clear logs</button>
      <button class="btn sm solid" data-debug="off">${icon('close')}Turn off</button>`;
    document.body.prepend(el);
  } else if (!on && el) el.remove();
  document.documentElement.classList.toggle('debug-on', on && !document.documentElement.classList.contains('embed'));
  const t = document.title.replace(/^\[DEBUG\] /, '');
  document.title = on ? `[DEBUG] ${t}` : t;
  if (!titleWatch && document.querySelector('title')) {
    // The app retitles the window as you navigate; keep the marker in front while logging is on.
    titleWatch = new MutationObserver(() => { if (on && !document.title.startsWith('[DEBUG] ')) document.title = `[DEBUG] ${document.title}`; });
    titleWatch.observe(document.querySelector('title'), { childList: true, characterData: true, subtree: true });
  }
}
let titleWatch = null;
async function refreshSize() {
  if (!on) return;
  try {
    const r = await api('/api/debuglog?lines=1');
    const f = (r.files || []).filter((x) => x.name.startsWith('tgdrive-debug')).reduce((a, x) => a + x.bytes, 0);
    const s = $('#debugBanner .db-size');
    if (s) s.textContent = ` (${fmtSize(f)} so far)`;
  } catch { /* ignore */ }
}
let sizeTimer = 0;

function bigNotice(title, text, tone) {
  const el = document.createElement('div');
  el.className = `big-notice ${tone}`;
  el.setAttribute('role', 'alert');
  el.innerHTML = `<span class="bn-ic">${icon('bug')}</span><strong>${esc(title)}</strong><p>${esc(text)}</p>`;
  document.body.append(el);
  setTimeout(() => el.classList.add('leaving'), 3200);
  setTimeout(() => el.remove(), 3600);
  el.addEventListener('click', () => el.remove());
}

// Called at start (quietly) and whenever the setting changes (with the large notice).
export function applyDebug(value, announce = false) {
  const was = on;
  on = !!value;
  if (on) install();
  banner();
  clearInterval(sizeTimer);
  if (on) { refreshSize(); sizeTimer = setInterval(refreshSize, 15000); }
  if (on && !was) dlog('info', 'debug', 'debug logging on in this window', environment());
  if (!on && was) flush();
  if (announce && on !== was) {
    bigNotice(on ? 'Debug logging is ON' : 'Debug logging is off',
      on ? 'Everything is now being recorded in detail to tgdrive-debug.log. A banner stays at the top until you turn it off.'
        : 'Detailed recording has stopped. The log stays on disk until you clear it.', on ? 'on' : 'off');
  }
}
export const debugOn = () => on;

export async function setDebug(value) {
  try {
    const r = await api('/api/settings', { method: 'PATCH', body: { debug_logging: !!value } });
    S.settings = r.settings;
    applyDebug(!!value, true);
    bus.emit('settings-changed', 'debug_logging');
  } catch (e) { (await import('./ui.js')).fail(e); }
}

export async function clearLogs(confirmFirst = true) {
  const ui = await import('./ui.js');
  if (confirmFirst) {
    const r = await ui.dialog({
      title: 'Clear all logs?',
      body: '<p>Empties <code>tgdrive.log</code> and <code>tgdrive-debug.log</code> and deletes their older copies. This can\'t be undone.</p><label class="check-line"><input type="checkbox" id="clrCrashes"> Also delete crash reports</label>',
      actions: [{ label: 'Cancel' }, { label: 'Clear logs', cls: 'danger solid', submit: true, onClick: (bd) => ({ crashes: bd.querySelector('#clrCrashes').checked }) }],
    });
    if (!r) return false;
    confirmFirst = r;
  }
  try {
    const res = await api(`/api/logs?crashes=${confirmFirst?.crashes ? 1 : 0}`, { method: 'DELETE' });
    ui.toast(`Logs cleared (${fmtSize(res.freed || 0)} freed${res.crashes ? `, ${res.crashes} crash reports deleted` : ''})`);
    refreshSize();
    if (res.crashes) $('#crashNotice')?.remove();
    return true;
  } catch (e) { ui.fail(e); return false; }
}

export async function viewLog() {
  const ui = await import('./ui.js');
  const load = async (bd) => {
    const pre = bd.querySelector('.logs');
    pre.classList.add('is-loading');
    try {
      const r = await api(`/api/debuglog?lines=1500&which=${bd.dataset.which || 'debug'}`);
      pre.textContent = r.text || (bd.dataset.which === 'main' ? 'The log is empty.' : 'The debug log is empty. Turn debug logging on and use TG Drive; everything shows up here.');
      bd.querySelector('.log-path').textContent = r.path;
      pre.scrollTop = pre.scrollHeight;
    } catch (e) { pre.textContent = e.message; } finally { pre.classList.remove('is-loading'); }
  };
  ui.dialog({
    title: 'Log', wide: true, cls: 'log-dialog',
    body: `<div class="seg small log-tabs"><button class="on" data-which="debug">Debug log</button><button data-which="main">Main log</button></div>
      <p class="help">Newest at the bottom. <code class="log-path"></code></p><pre class="logs log-view">Loading…</pre>`,
    actions: [
      { label: 'Refresh', icon: 'refresh', onClick: async (bd) => { await load(bd); return false; } },
      { label: 'Copy', icon: 'copy', onClick: (bd) => { ui.copyText(bd.querySelector('.logs').textContent, 'Log copied'); return false; } },
      { label: 'Download', icon: 'download', onClick: async (bd) => { await ui.saveDownload(`/api/logs/download?which=${bd.dataset.which || 'debug'}`, `tgdrive-${bd.dataset.which || 'debug'}.log`); return false; } },
      { label: 'Clear logs', icon: 'trash', cls: 'danger', onClick: async (bd) => { if (await clearLogs(true)) await load(bd); return false; } },
      '-', { label: 'Close', cls: 'primary' },
    ],
    onOpen: (bd) => {
      bd.dataset.which = 'debug';
      bd.querySelector('.log-tabs').addEventListener('click', (e) => {
        const b = e.target.closest('[data-which]');
        if (!b) return;
        bd.dataset.which = b.dataset.which;
        bd.querySelectorAll('.log-tabs button').forEach((x) => x.classList.toggle('on', x === b));
        load(bd);
      });
      load(bd);
    },
  });
}

document.addEventListener('click', (e) => {
  const b = e.target.closest('[data-debug]');
  if (!b) return;
  const a = b.dataset.debug;
  if (a === 'off') setDebug(false);
  else if (a === 'on') setDebug(true);
  else if (a === 'view') viewLog();
  else if (a === 'clear') clearLogs(true);
});

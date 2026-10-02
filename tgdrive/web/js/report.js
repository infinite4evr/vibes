// "What went wrong" dialog: every error in the window, however small (a failed action, a page or picture that
// didn't load, an error in the page itself, a crash report from the service), opens this dialog with the
// error, its details and "Create GitHub issue": a new issue on TG Drive's GitHub, already filled in with the
// error, the end of the log and the system, with secrets, numbers and chat/file names removed by the app.
// You see the issue before sending it and can edit it. Errors arriving while it is open wait their turn;
// a repeat of the one shown (or of one waiting) is counted instead of queued again.
import { S, api, esc } from './core.js';

export const REPO = 'infinite4evr/vibes';
const MAX_URL = 7600;   // browsers and GitHub accept links up to about 8 000 characters

const queue = [];       // { title, message, detail, action, onAction, count }
let showing = null;

/** Show an error. message: what went wrong (one line or a few); detail: the technical story (stack …). */
export function reportError(message, { detail = '', title = 'Something went wrong', action, onAction } = {}) {
  message = String(message || 'Unknown error').trim();
  detail = String(detail || '').trim();
  const same = (e) => e.message === message && e.detail === detail;
  if (showing && same(showing)) { showing.count++; countLabel(); return; }
  const waiting = queue.find(same);
  if (waiting) { waiting.count++; return; }
  if (queue.length >= 20) return;   // a burst of errors: the first twenty are plenty to report
  queue.push({ title, message, detail, action, onAction, count: 1 });
  if (!showing) next();
}

/** For errors shown on a page that can draw itself again (a list, a viewer): the dialog opens once per
 *  distinct error in this window, not again on every redraw. */
const reportedOnce = new Set();
export function reportOnce(message, opts = {}) {
  const k = `${message}\n${opts.detail || ''}`;
  if (reportedOnce.has(k)) return;
  if (reportedOnce.size > 500) reportedOnce.clear();
  reportedOnce.add(k);
  reportError(message, opts);
}
export function reportExceptionOnce(e, opts = {}) {
  if (!e || e.name === 'AbortError' || e.status === 423) return;
  const p = errorParts(e);
  reportOnce(opts.message ? `${opts.message}: ${p.message}` : p.message, { ...opts, detail: [opts.detail, p.detail].filter(Boolean).join('\n\n') });
}

/** An Error / ApiError / anything thrown, as message + detail. */
export function errorParts(e) {
  if (!e) return { message: 'Unknown error', detail: '' };
  if (typeof e === 'string') return { message: e, detail: '' };
  const lines = [];
  if (e.status !== undefined) lines.push(`HTTP status: ${e.status}`);
  if (e.path) lines.push(`Request: ${e.path}`);
  if (e.stack) lines.push(String(e.stack));
  return { message: e.message || String(e), detail: lines.join('\n') };
}

/** reportError for a caught exception. */
export function reportException(e, opts = {}) {
  if (!e || e.name === 'AbortError' || e.status === 423) return;
  const p = errorParts(e);
  reportError(opts.message ? `${opts.message}: ${p.message}` : p.message, { ...opts, detail: [opts.detail, p.detail].filter(Boolean).join('\n\n') });
}

function countLabel() {
  const el = document.querySelector('#errDialog .err-count');
  if (el && showing) el.textContent = showing.count > 1 ? `Happened ${showing.count} times.` : '';
}

async function next() {
  showing = queue.shift() || null;
  if (!showing) return;
  const e = showing;
  const { dialog, copyText } = await import('./ui.js');
  const full = () => `${e.message}${e.detail ? `\n\n${e.detail}` : ''}`;
  const actions = [
    { label: 'Create GitHub issue', icon: 'external', cls: 'primary', onClick: async () => { await openIssue(e); return false; } },
    { label: 'Copy', icon: 'copy', onClick: () => { copyText(full(), 'Error copied'); return false; } },
  ];
  if (e.action && e.onAction) actions.push({ label: e.action, onClick: () => { setTimeout(() => e.onAction(), 0); } });
  actions.push('-', { label: 'Close' });
  await dialog({
    title: e.title, cls: 'error-dialog',
    body: `<div id="errDialog"><p class="err-msg"><strong>${esc(e.message)}</strong></p><p class="help err-count"></p>
      <p class="help">“Create GitHub issue” opens a new issue on TG Drive's GitHub with this error, the end of the log and your
      system; you see it before sending. Passwords, keys, numbers and chat or file names are removed.</p>
      ${e.detail ? `<details><summary>Details</summary><pre class="logs err-detail">${esc(e.detail)}</pre></details>` : ''}</div>`,
    actions,
    onOpen: countLabel,
  });
  showing = null;
  next();
}

/** Opens the new issue in the browser (the desktop app hands the link to the browser). */
export async function openIssue(e) {
  let ctx = { texts: [e.message, e.detail], log: '', env: {} };
  try {
    ctx = await api('/api/issue-context', { method: 'POST', body: { texts: [e.message, e.detail] } });
  } catch { /* the service isn't answering: the link still has the error, unredacted names aside */ }
  const [message, detail] = ctx.texts;
  const title = `TG Drive: ${String(message || e.message).split('\n').find((l) => l.trim()) || e.title}`.slice(0, 110);
  const url = issueLink(title, issueBody({ ...e, message, detail }, ctx));
  const w = window.open(url, '_blank', 'noopener');
  if (w === null && !S.desktop) {
    // A blocked pop-up (noopener also returns null, so only outside the desktop app): copy the link instead.
    const { copyText } = await import('./ui.js');
    copyText(url, 'If no browser tab opened, the issue link was copied: paste it into your browser.');
  }
}

function issueBody(e, ctx) {
  const env = ctx.env || {};
  const fence = (t) => `\`\`\`text\n${String(t).replace(/```/g, "'''").trim()}\n\`\`\``;
  const parts = [
    `**Where:** ${location.hash || '#'} (TG Drive window${S.desktop ? ', desktop app' : ', browser'})`,
    '', '### What happened', '', e.message || '_Describe what you were doing when it went wrong._', '',
  ];
  if (e.detail) parts.push('### Details', '', fence(e.detail), '');
  if (e.count > 1) parts.push(`It happened ${e.count} times.`, '');
  if (ctx.log) parts.push('### Log (end)', '', fence(ctx.log), '');
  parts.push('### System', '', '| | |', '|---|---|',
    `| TG Drive | ${env.tgdrive || S.version || '?'} |`, `| Python | ${String(env.python || '?').split(' ')[0]} |`,
    `| Platform | ${env.platform || '?'} |`, `| Desktop | ${env.desktop || '?'} (${env.session || '?'}) |`,
    `| Packaged | ${env.appimage ? 'AppImage' : env.packaged ? 'yes' : 'from source'} |`,
    `| Window | ${navigator.userAgent.replace(/\|/g, '/')} |`, '',
    "<sub>Created from TG Drive's error dialog. Secrets, numbers, e-mail addresses and chat/file names were removed before this text was shown to you.</sub>");
  return parts.join('\n');
}

/** The issue link; the body is shortened (oldest log lines first, then the details' deepest lines) until it fits. */
export function issueLink(title, body) {
  const base = `https://github.com/${REPO}/issues/new?labels=bug&title=${encodeURIComponent(title)}&body=`;
  let text = body;
  for (;;) {
    const url = base + encodeURIComponent(text);
    if (url.length <= MAX_URL || text.length < 200) return url;
    text = shorten(text);
  }
}

function shorten(text) {
  const lines = text.split('\n');
  const blocks = [];
  let heading = '';
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].startsWith('### ')) heading = lines[i];
    if (lines[i].startsWith('```text')) {
      let end = i + 1;
      while (end < lines.length && !lines[end].startsWith('```')) end++;
      blocks.push({ heading, start: i + 1, end });
      i = end;
    }
  }
  const size = (b) => b.end - b.start;
  const log = blocks.find((b) => /log/i.test(b.heading) && size(b) > 3);
  if (log) { lines.splice(log.start, 1); return lines.join('\n'); }
  const other = blocks.filter((b) => size(b) > 6).sort((a, b) => size(b) - size(a))[0];
  if (other) { lines.splice(other.end - 1, 1); return lines.join('\n'); }
  return `${text.slice(0, Math.floor(text.length * 0.85))}\n…`;
}

/* Errors in this page itself (a bug in the window): reported as well. */
window.addEventListener('error', (e) => {
  if (!e.error && /ResizeObserver loop/.test(e.message || '')) return;
  if (e.target && e.target !== window) return;   // a picture/video that didn't load: reported where it is shown
  reportError(`Error in the window: ${e.message || 'unknown'}`, { detail: `${e.filename}:${e.lineno}:${e.colno}\n${e.error?.stack || ''}` });
});
window.addEventListener('unhandledrejection', (e) => {
  const r = e.reason;
  if (!r || r.name === 'AbortError' || r.status === 423) return;
  reportException(r);
});

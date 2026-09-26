// First run (API setup, data import), sign-in (QR or phone), and the lock screen.
import { $, S, api, esc, icon, MARK, bridge, callBridge, plural, bus } from './core.js';
import { toast, fail } from './ui.js';

const root = () => $('#login');
function frame(html, opts = {}) {
  $('#app').hidden = true;
  const r = root();
  r.hidden = false;
  r.innerHTML = `<div class="login-wrap"><div class="login ${opts.wide ? 'wide' : ''}">${MARK}${html}
    ${opts.back ? '<p class="back"><button class="btn ghost" id="cancelLogin">Back to my files</button></p>' : ''}</div></div>`;
  $('#cancelLogin')?.addEventListener('click', () => { r.hidden = true; $('#app').hidden = false; });
  r.querySelector('input')?.focus();
}
const openExt = (url) => (bridge.ready ? callBridge('openExternal', url) : window.open(url, '_blank', 'noopener'));

export async function showOnboarding(adding = false) {
  let st;
  try { st = await api('/api/status'); } catch (e) { return frame(`<h1>TG Drive isn't responding</h1><p>${esc(e.message)}</p>`); }
  if (st.locked) return showLock();
  if (!adding && st.legacy?.length && !st.accounts.length) return legacyStep(st.legacy);
  if (!st.api_configured) return apiStep(adding);
  return signIn(adding);
}

function legacyStep(cands) {
  frame(`<h1>Welcome back</h1><p>TG Drive found data from the earlier version on this computer. Import it to keep your sign-in, folders and your full index — no re-indexing.</p>
    <div class="legacy">${cands.map((c) => `<button class="legacy-row" data-path="${esc(c.path)}"><span>${icon('database')}</span><span class="grow"><strong>${esc(c.path)}</strong><small>${plural(c.accounts.length, 'account')}${c.env ? ' · API keys found' : ''}</small></span>${icon('chevron')}</button>`).join('')}</div>
    <p class="err" role="alert"></p>
    <p><button class="btn ghost" id="skipLegacy">Start fresh instead</button></p>`, { wide: true });
  root().addEventListener('click', async (e) => {
    const b = e.target.closest('[data-path]');
    if (b) {
      b.disabled = true;
      try {
        await api('/api/legacy/import', { method: 'POST', body: { path: b.dataset.path } });
        toast('Imported. Starting TG Drive…');
        setTimeout(() => location.reload(), 800);
      } catch (err) { $('.err', root()).textContent = err.message; b.disabled = false; }
    }
    if (e.target.id === 'skipLegacy') api('/api/status').then((st) => (st.api_configured ? signIn(false) : apiStep(false)));
  });
}

function apiStep(adding) {
  frame(`<h1>Connect TG Drive to Telegram</h1>
    <p>TG Drive signs in as your own account, so Telegram asks for an app key first. It takes a minute and you only do it once.</p>
    <ol class="steps"><li>Open <button class="linkish" data-ext="https://my.telegram.org/apps">my.telegram.org/apps</button> and sign in with your phone number.</li>
      <li>Fill in <b>App title</b> (e.g. “TG Drive”) and <b>Short name</b>, pick <b>Desktop</b>, and create it.</li>
      <li>Copy the <b>App api_id</b> and <b>App api_hash</b> here.</li></ol>
    <form id="apiForm"><label class="field"><span>API ID</span><input name="api_id" inputmode="numeric" autocomplete="off" placeholder="1234567" required></label>
      <label class="field"><span>API hash</span><input name="api_hash" autocomplete="off" spellcheck="false" placeholder="32 letters and digits" required></label>
      <p class="err" role="alert"></p><button class="btn primary" type="submit">Continue</button></form>
    <p class="fine">The key and your session stay on this computer. TG Drive talks only to Telegram.</p>`, { back: adding, wide: true });
  root().querySelector('[data-ext]').addEventListener('click', (e) => openExt(e.currentTarget.dataset.ext));
  $('#apiForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      await api('/api/setup', { method: 'POST', body: { api_id: fd.get('api_id'), api_hash: fd.get('api_hash') } });
      signIn(adding);
    } catch (err) { $('.err', e.target).textContent = err.message; }
  });
}

let qrTimer = null;
function signIn(adding, mode = 'qr') {
  clearTimeout(qrTimer);
  let loginId = null;
  const tabs = `<div class="seg login-seg"><button class="${mode === 'qr' ? 'on' : ''}" data-mode="qr">QR code</button><button class="${mode === 'phone' ? 'on' : ''}" data-mode="phone">Phone number</button></div>`;
  const step = (html) => {
    frame(`${tabs}${html}`, { back: adding });
    root().querySelectorAll('[data-mode]').forEach((b) => b.addEventListener('click', () => signIn(adding, b.dataset.mode)));
  };
  const bind = (handler) => {
    const form = root().querySelector('form');
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn = form.querySelector('button[type=submit]');
      btn.disabled = true;
      $('.err', form).textContent = '';
      try { await handler(new FormData(form)); } catch (err) { $('.err', form).textContent = err.message; } finally { btn.disabled = false; }
    });
  };
  const passwordStep = (hint) => {
    clearTimeout(qrTimer);
    step(`<h1>Two-step verification</h1><p>This account has a cloud password.${hint ? ` Hint: ${esc(hint)}` : ''}</p>
      <form><label class="field"><span>Password</span><input type="password" name="password" autocomplete="current-password" required></label>
      <p class="err" role="alert"></p><button class="btn primary" type="submit">Sign in</button></form>`);
    bind(async (fd) => {
      const r = await api('/api/login/password', { method: 'POST', body: { login_id: loginId, password: fd.get('password') } });
      finish(r.account);
    });
  };
  const finish = async (account) => {
    clearTimeout(qrTimer);
    toast(`Signed in as ${account.name}. Indexing starts now.`);
    bus.emit('signed-in', account);
  };
  if (mode === 'qr') {
    step(`<h1>${adding ? 'Add another account' : 'Sign in to Telegram'}</h1>
      <div class="qr-box"><div class="qr" id="qr"><span class="spin big"></span></div>
      <ol class="steps"><li>Open Telegram on your phone.</li><li>Go to <b>Settings → Devices → Link Desktop Device</b>.</li><li>Point your phone at this code.</li></ol></div>
      <p class="err" role="alert"></p>`);
    const poll = async () => {
      try {
        const r = await api(`/api/login/qr/${loginId}`);
        if (r.state === 'done') return finish(r.account);
        if (r.state === 'password') return passwordStep(r.hint);
        if (r.state === 'error' || r.state === 'expired') { $('.err', root()).textContent = r.error || 'The code expired.'; return; }
        if (r.svg && $('#qr')) $('#qr').innerHTML = r.svg;
      } catch (e) { if ($('.err', root())) $('.err', root()).textContent = e.message; return; }
      qrTimer = setTimeout(poll, 1500);
    };
    api('/api/login/qr', { method: 'POST' }).then((r) => {
      loginId = r.login_id;
      $('#qr').innerHTML = r.svg;
      qrTimer = setTimeout(poll, 1500);
    }).catch((e) => { $('.err', root()).textContent = e.message; });
    return;
  }
  const codeStep = (via) => {
    const where = via === 'app' ? 'in your Telegram app' : via === 'sms' ? 'by SMS' : 'to you';
    step(`<h1>Enter the code</h1><p>Telegram sent a login code ${where}.</p>
      <form><label class="field"><span>Code</span><input name="code" inputmode="numeric" autocomplete="one-time-code" required></label>
      <p class="err" role="alert"></p><button class="btn primary" type="submit">Sign in</button></form>`);
    bind(async (fd) => {
      const r = await api('/api/login/code', { method: 'POST', body: { login_id: loginId, code: fd.get('code') } });
      if (r.need_password) return passwordStep(r.hint);
      finish(r.account);
    });
  };
  step(`<h1>${adding ? 'Add another account' : 'Sign in to Telegram'}</h1>
    <p>Telegram sends you a code, like signing in on a new device. Your session stays on this computer.</p>
    <form><label class="field"><span>Phone number with country code</span><input type="tel" name="phone" placeholder="+91 98765 43210" autocomplete="tel" required></label>
    <p class="err" role="alert"></p><button class="btn primary" type="submit">Send code</button></form>`);
  bind(async (fd) => {
    const r = await api('/api/login/start', { method: 'POST', body: { phone: fd.get('phone') } });
    loginId = r.login_id;
    codeStep(r.sent_via);
  });
}

export function showLock() {
  frame(`<h1>TG Drive is locked</h1><p>Enter your passcode to continue.</p>
    <form id="lockForm"><label class="field"><span>Passcode</span><input type="password" name="passcode" autocomplete="current-password" required></label>
    <p class="err" role="alert"></p><button class="btn primary" type="submit">${icon('lock')}Unlock</button></form>`);
  $('#lockForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      await api('/api/lock/unlock', { method: 'POST', body: { passcode: new FormData(e.target).get('passcode') } });
      root().hidden = true;
      bus.emit('unlocked');
    } catch (err) { $('.err', e.target).textContent = err.message; e.target.querySelector('input').select(); }
  });
}
export { fail };

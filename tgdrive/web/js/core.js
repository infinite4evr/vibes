// Core: state, API client, icons, formatters, desktop bridge, thumbnail loader.

export const $ = (s, el = document) => el.querySelector(s);
export const $$ = (s, el = document) => [...el.querySelectorAll(s)];
export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const key = (f) => `${f.chat_id}:${f.msg_id}`;
export const unkey = (k) => k.split(':').map(Number);
export const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
export function debounce(fn, ms) {
  let t;
  const d = (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
  d.cancel = () => clearTimeout(t);
  return d;
}

/* ------------------------------------------------------------------ icons */
export const ICON = {
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  sliders: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  transfers: '<path d="M4 14.5V18a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3.5"/><path d="M8.5 4v9.5M5.5 10.5l3 3 3-3M15.5 13.5V4M12.5 7l3-3 3 3"/>',
  chevron: '<path d="m9 6 6 6-6 6"/>',
  chevronDown: '<path d="m6 9 6 6 6-6"/>',
  chevLeft: '<path d="m15 6-6 6 6 6"/>',
  sidebar: '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><path d="M9.5 4.5v15"/>',
  down: '<path d="m6 9 6 6 6-6"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  folderPlus: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M12 11v5M9.5 13.5h5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  upload: '<path d="M12 16V4M7 9l5-5 5 5M5 20h14"/>',
  uploadFolder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M12 16v-5M9.5 13.5 12 11l2.5 2.5"/>',
  download: '<path d="M12 4v12M7 11l5 5 5-5M5 20h14"/>',
  move: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M10 13h6M13 10l3 3-3 3"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  more: '<circle cx="12" cy="5" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="12" cy="19" r="1.2"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6"/>',
  pause: '<path d="M9 5v14M15 5v14"/>',
  play: '<path d="M7 5l12 7-12 7z"/>',
  next: '<path d="M6 5l10 7-10 7zM18 5v14"/>',
  prev: '<path d="M18 5 8 12l10 7zM6 5v14"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  external: '<path d="M14 4h6v6M20 4l-9 9M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/>',
  audio: '<path d="M9 18V6l10-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/>',
  voice: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  video: '<rect x="3" y="6" width="13" height="12" rx="2"/><path d="m16 10 5-3v10l-5-3z"/>',
  round: '<circle cx="12" cy="12" r="8"/><path d="m10 9 5 3-5 3z"/>',
  gif: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M10 10H8v4h2v-1.5M13 10v4M16.5 10H15v4M15 12h1.3"/>',
  photo: '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="m21 16-5-5-8 8"/>',
  document: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>',
  signout: '<path d="M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4M9 16l-4-4 4-4M5 12h11"/>',
  star: '<path d="m12 3.5 2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  grid: '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
  list: '<path d="M8 6h12M8 12h12M8 18h12"/><circle cx="4" cy="6" r="1"/><circle cx="4" cy="12" r="1"/><circle cx="4" cy="18" r="1"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  dupes: '<rect x="3" y="7" width="12" height="14" rx="2"/><path d="M9 3h10a2 2 0 0 1 2 2v12"/>',
  database: '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
  activity: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
  tag: '<path d="M3 12V4a1 1 0 0 1 1-1h8l9 9-9 9z"/><circle cx="7.5" cy="7.5" r="1.3"/>',
  note: '<path d="M5 4h14v11l-5 5H5z"/><path d="M14 20v-5h5M8 9h8M8 13h5"/>',
  send: '<path d="M21 3 3 10.5l7 2.5 2.5 7z"/><path d="m10 13 4-4"/>',
  telegram: '<path d="M21 4 3 11l6 2 2 6 3-4 5 4z"/><path d="m9 13 8-6"/>',
  lock: '<rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
  sparkle: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M18 6l-2.5 2.5M8.5 15.5 6 18"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
  check: '<path d="m5 12 5 5 9-10"/>',
  undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>',
  zoomIn: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5M11 8v6M8 11h6"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  filter: '<path d="M3 5h18l-7 8v6l-4-2v-4z"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  pin: '<path d="M9 4h6l-1 6 4 3v2H6v-2l4-3z"/><path d="M12 15v6"/>',
  keyboard: '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>',
  volume: '<path d="M4 9h4l5-4v14l-5-4H4z"/><path d="M16 9a4 4 0 0 1 0 6M18.5 6.5a8 8 0 0 1 0 11"/>',
  maximize: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
  history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/>',
  wand: '<path d="m4 20 11-11M14 4l1 2 2 1-2 1-1 2-1-2-2-1 2-1zM19 11l.7 1.3L21 13l-1.3.7L19 15l-.7-1.3L17 13l1.3-.7z"/>',
  folderFill: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" fill="currentColor" fill-opacity=".22"/>',
  folderSmart: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" fill="currentColor" fill-opacity=".14"/><path d="M12 10.5v5M9.5 13h5"/>',
  tiles: '<rect x="3.5" y="4" width="8" height="5" rx="1.5"/><rect x="12.5" y="4" width="8" height="5" rx="1.5"/><rect x="3.5" y="11" width="8" height="5" rx="1.5"/><rect x="12.5" y="11" width="8" height="5" rx="1.5"/><path d="M4 20h16"/>',
  cards: '<rect x="3.5" y="4" width="7.5" height="9" rx="1.5"/><rect x="13" y="4" width="7.5" height="9" rx="1.5"/><path d="M4 16.5h6.5M13.5 16.5H20M4 19.5h4.5M13.5 19.5H18"/>',
  columns: '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M9 4.5v15M15 4.5v15"/>',
  grip: '<circle cx="9" cy="7" r="1"/><circle cx="15" cy="7" r="1"/><circle cx="9" cy="12" r="1"/><circle cx="15" cy="12" r="1"/><circle cx="9" cy="17" r="1"/><circle cx="15" cy="17" r="1"/>',
  up: '<path d="m6 15 6-6 6 6"/>',
  stack: '<rect x="4" y="8" width="13" height="12" rx="2"/><path d="M7 5h11a2 2 0 0 1 2 2v10"/>',
  book: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5z"/><path d="M4 20.5A2.5 2.5 0 0 0 6.5 23H20v-5"/>',
  slides: '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="m10 8 4.5 2.5L10 13z"/><path d="M8 21h8M12 17v4"/>',
  chat: '<path d="M4 5h16v11H9l-5 4z"/><path d="M8 9h8M8 12.5h5"/>',
  split: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M12 4v16"/>',
  window: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 9h18M6.5 7h.01M9 7h.01"/>',
  palette: '<path d="M12 3a9 9 0 1 0 0 18c1.2 0 2-.8 2-1.8 0-.5-.2-.9-.5-1.2-.3-.3-.5-.7-.5-1.2 0-1 .8-1.8 1.8-1.8H17a4 4 0 0 0 4-4c0-4.4-4-8-9-8z"/><circle cx="7.5" cy="11" r="1.2"/><circle cx="10.5" cy="7" r="1.2"/><circle cx="15" cy="7.5" r="1.2"/>',
  sync: '<path d="M20 12a8 8 0 0 1-14 5.3M4 12A8 8 0 0 1 18 6.7"/><path d="M18 3v4h-4M6 21v-4h4"/>',
  disk: '<rect x="3" y="13" width="18" height="7" rx="2"/><path d="M5 13 7.5 5h9L19 13"/><path d="M16.5 16.5h.01"/>',
  bug: '<rect x="7" y="8" width="10" height="12" rx="5"/><path d="M12 8v12M9 5l1.5 3M15 5l-1.5 3M3 13h4M17 13h4M4 19l3-2M20 19l-3-2M4 8l3 2M20 8l-3 2"/>',
  photos: '<rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="3" width="8" height="8" rx="1.5"/><rect x="3" y="13" width="8" height="8" rx="1.5"/><rect x="13" y="13" width="8" height="8" rx="1.5"/>',
  bookmark: '<path d="M6 3h12v18l-6-4-6 4z"/>',
  paste: '<rect x="6" y="4" width="12" height="17" rx="2"/><path d="M9 4V3h6v1M9 11h6M9 15h4"/>',
  contrast: '<circle cx="12" cy="12" r="9"/><path d="M12 3v18a9 9 0 0 0 0-18z" fill="currentColor"/>',
  text: '<path d="M4 7V5h11v2M9.5 5v14M7 19h5M14 12v-1.5h7V12M17.5 10.5V19M16 19h3"/>',
  shuffle: '<path d="M3 7h3l9 10h6M3 17h3l3-3.5M15 7h6M18 4l3 3-3 3M18 14l3 3-3 3"/>',
  mount: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4M8 10l4-3 4 3M12 7v6"/>',
  shield: '<path d="M12 3 5 6v6c0 4 3 7.5 7 9 4-1.5 7-5 7-9V6z"/>',
  zoomOut: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5M8 11h6"/>',
  pages: '<rect x="6" y="3" width="12" height="16" rx="1.5"/><path d="M4 6v14a2 2 0 0 0 2 2h10"/>',
  locate: '<circle cx="12" cy="12" r="3"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/>',
};
export const icon = (name, attrs = '') => `<svg viewBox="0 0 24 24" aria-hidden="true" ${attrs}>${ICON[name] || ICON.document}</svg>`;
ICON.image = ICON.photo;
export const MARK = '<svg class="mark" viewBox="0 0 30 24" aria-hidden="true" style="stroke:none"><path d="M1 4a3 3 0 0 1 3-3h7l3 3h12a3 3 0 0 1 3 3v13a3 3 0 0 1-3 3H4a3 3 0 0 1-3-3z" fill="var(--folder)"/><path d="M8 15l12-5-3 10-3-4z" fill="var(--accent)"/></svg>';

/* ------------------------------------------------------------------ names */
export const KINDS = [
  ['', 'All'], ['photo', 'Photos'], ['video', 'Videos'], ['document', 'Documents'],
  ['audio', 'Audio'], ['voice', 'Voice'], ['round', 'Round videos'], ['gif', 'GIFs'],
];
export const KIND_NAME = { photo: 'Photo', video: 'Video', document: 'Document', audio: 'Audio', voice: 'Voice message', round: 'Round video', gif: 'GIF' };
export const SOURCES = [
  ['channel', 'Channels', ['channel']], ['group', 'Groups', ['group', 'supergroup']],
  ['user', 'Private chats', ['user']], ['bot', 'Bots', ['bot']], ['saved', 'Saved Messages', ['saved']],
];
export const CHAT_KIND_NAME = { channel: 'Channel', supergroup: 'Group', group: 'Group', user: 'Private chat', bot: 'Bot', saved: 'Saved Messages' };
export const STREAMABLE = new Set(['video', 'audio', 'voice', 'round', 'gif']);
const EXT_GROUPS = [
  ['#d0453c', 'pdf'], ['#2b62b8', 'doc docx odt rtf pages'], ['#1f7a44', 'xls xlsx csv ods numbers tsv'],
  ['#d0592a', 'ppt pptx odp key'], ['#a8751b', 'zip rar 7z tar gz bz2 xz tgz zst iso dmg'],
  ['#7b4bb3', 'epub mobi azw azw3 fb2 djvu cbz cbr'], ['#3c8f3a', 'apk xapk aab exe msi deb rpm appimage'],
  ['#57616f', 'txt md log json xml yml yaml ini srt vtt sub html htm js py c cpp java sh sql'],
  ['#b0417a', 'mp3 m4a flac wav ogg opus aac wma'], ['#6b51c7', 'mp4 mkv avi mov webm m4v 3gp ts flv wmv'],
  ['#258f84', 'jpg jpeg png webp heic gif bmp tif tiff svg raw psd ai'],
];
const EXT_COLOR = {};
for (const [c, list] of EXT_GROUPS) for (const e of list.split(' ')) EXT_COLOR[e] = c;
export const extColor = (ext) => EXT_COLOR[(ext || '').toLowerCase()] || '#5b6b82';
export const TEXT_EXT = new Set('txt md log json xml yml yaml ini srt vtt csv tsv html htm js ts css py c h cpp java kt go rs rb php sh sql toml cfg conf env'.split(' '));

/* ------------------------------------------------------------- formatting */
export function fmtSize(b) {
  if (!b) return '0 B';
  const u = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return `${i === 0 ? b : b.toFixed(b < 10 ? 1 : 0)} ${u[i]}`;
}
export const fmtNum = (n) => (n || 0).toLocaleString();
// Short counts for tight places: 8,424 → 8.4k, 438,046 → 438k, 1,250,000 → 1.3M.
export function fmtCompact(n) {
  n = n || 0;
  if (n < 1000) return String(n);
  const [d, s] = n < 1e6 ? [1e3, 'k'] : [1e6, 'M'];
  const v = n / d;
  return `${v < 100 ? (Math.floor(v * 10) / 10).toLocaleString() : Math.floor(v).toLocaleString()}${s}`;
}

// Names cameras and Telegram make up ("photo_2026-05-07_01-50-00.jpg", "IMG_20240101_123456.jpg",
// "voice_2026-07-15_10-10-01.ogg") become "Photo · 7 May, 1:50 AM". The real name stays in the tooltip,
// the details panel, search and downloads.
const GENERIC_NAME = [
  [/^(photo|video|voice|round|audio|animation|file|document|sticker)[_\- ](\d{4})-(\d{2})-(\d{2})[_ ](\d{2})-(\d{2})-(\d{2})/i, 'tg'],
  [/^(?:IMG|VID|PXL|MVIMG|PANO|DSC|Screenshot|Screen[_ ]?Recording|WhatsApp (?:Image|Video|Audio))?[_\- ]?(\d{4})-?(\d{2})-?(\d{2})[_\- T]?(?:at )?(\d{2})[.\-_]?(\d{2})[.\-_]?(\d{2})?/i, 'cam'],
];
const KIND_WORD = { photo: 'Photo', video: 'Video', voice: 'Voice message', round: 'Round video', audio: 'Audio', gif: 'GIF', document: 'File' };
export function friendlyName(f) {
  const raw = f?.name || '';
  if (!raw || f.renamed) return null;
  const base = raw.replace(/\.[a-z0-9]{2,5}$/i, '');
  let m = base.match(GENERIC_NAME[0][0]);
  let y, mo, d, h, mi;
  if (m) [, , y, mo, d, h, mi] = m;
  else {
    m = base.match(GENERIC_NAME[1][0]);
    if (!m || m.index !== 0 || base.length - m[0].length > 6) return null;   // must be (almost) the whole name
    [, y, mo, d, h, mi] = m;
  }
  const dt = new Date(+y, +mo - 1, +d, +h || 0, +mi || 0);
  if (Number.isNaN(dt.getTime()) || +y < 1995 || +y > 2100 || +mo > 12 || +d > 31) return null;
  const now = new Date();
  const day = dt.toLocaleDateString(undefined, { day: 'numeric', month: 'short', ...(dt.getFullYear() !== now.getFullYear() ? { year: 'numeric' } : {}) });
  const time = dt.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  const kind = /^screenshot/i.test(base) ? 'Screenshot' : /^screen[_ ]?rec/i.test(base) ? 'Screen recording' : KIND_WORD[f.kind] || 'File';
  return `${kind} · ${day}, ${time}`;
}
export const displayName = (f) => friendlyName(f) || f?.name || '';
// "Hide duplicates" (toolbar switch, Settings → General): lists show one card per file.
export const copiesParam = () => (S.settings?.hide_duplicates === false ? 'show' : 'hide');

// Voice notes and songs without cover art: a waveform (drawn from the file's id, so it's stable) instead of an
// empty tile with an icon.
export function waveHtml(f, bars = 34) {
  let h = hue(`${f.chat_id}:${f.msg_id}`) + 7;
  const hs = [];
  for (let i = 0; i < bars; i++) {
    h = (h * 1103515245 + 12345) % 2147483648;
    const env = Math.sin((i / (bars - 1)) * Math.PI) * 0.55 + 0.45;
    hs.push(Math.max(0.12, env * (0.35 + (h % 1000) / 1540)));
  }
  const w = 100 / bars;
  return `<svg class="wave" viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden="true">${hs.map((v, i) =>
    `<rect x="${(i * w + w * 0.18).toFixed(2)}" y="${(20 - v * 18).toFixed(2)}" width="${(w * 0.64).toFixed(2)}" height="${(v * 36).toFixed(2)}" rx="${(w * 0.32).toFixed(2)}"/>`).join('')}</svg>`;
}

export const plural = (n, one, many) => `${fmtNum(n)} ${n === 1 ? one : (many || one + 's')}`;
export function fmtDate(ts, long = false) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const now = new Date();
  if (long) return d.toLocaleString(undefined, { day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  if (d.toDateString() === now.toDateString()) return `Today ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
  const y = new Date(now); y.setDate(now.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return 'Yesterday';
  const o = { day: 'numeric', month: 'short' };
  if (d.getFullYear() !== now.getFullYear()) o.year = 'numeric';
  return d.toLocaleDateString(undefined, o);
}
export function relTime(ts) {
  if (!ts) return 'never';
  const s = Math.round(Date.now() / 1000 - ts);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)} d ago`;
  return fmtDate(ts);
}
export function fmtDur(s) {
  s = Math.round(s || 0);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return `${h ? `${h}:${String(m).padStart(2, '0')}` : m}:${String(sec).padStart(2, '0')}`;
}
export function fmtEta(sec) {
  if (!isFinite(sec) || sec <= 0) return '';
  if (sec < 60) return `${Math.ceil(sec)} s left`;
  if (sec < 3600) return `${Math.ceil(sec / 60)} min left`;
  return `${Math.floor(sec / 3600)} h ${Math.ceil((sec % 3600) / 60)} min left`;
}
export function initials(name) {
  return (name || '?').replace(/[^\p{L}\p{N}\s]/gu, ' ').split(/\s+/).filter(Boolean).slice(0, 2).map((w) => [...w][0].toUpperCase()).join('') || '?';
}
export function hue(str) {
  let h = 0;
  for (const ch of String(str)) h = (h * 31 + ch.codePointAt(0)) >>> 0;
  return h % 360;
}
export function dateGroup(ts) {
  if (!ts) return 'Undated';
  const d = new Date(ts * 1000), now = new Date();
  const day = 86400000;
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  if (d.getTime() >= start) return 'Today';
  if (d.getTime() >= start - day) return 'Yesterday';
  if (d.getTime() >= start - 6 * day) return 'Earlier this week';
  if (d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth()) return 'Earlier this month';
  return d.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
}
export function highlight(text, words) {
  // Escape piece by piece (never regex over escaped HTML) and allow line breaks after _ . - so long
  // file names wrap at their separators instead of mid-word.
  const s = String(text ?? '');
  const brk = (x) => esc(x).replace(/([_.\-])/g, '$1<wbr>');
  const parts = (words || []).filter((w) => w && w.length > 1).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  // …but never between a name and its extension ("notes." / "docx" on its own line).
  const keepExt = (h) => h.replace(/\.<wbr>((?:<\/?mark>)?[A-Za-z0-9]{1,5}(?:<\/?mark>)?)$/, '.$1');
  if (!parts.length) return keepExt(brk(s));
  let re;
  try { re = new RegExp(`(${parts.join('|')})`, 'giu'); } catch { return keepExt(brk(s)); }
  return keepExt(s.split(re).map((seg, i) => (i % 2 ? `<mark>${brk(seg)}</mark>` : brk(seg))).join('')
    .replaceAll('</mark><mark>', ''));
}

/* ------------------------------------------------------------------ state */
export const S = {
  version: '', apiConfigured: true, accounts: [], aid: null, status: null, settings: {}, desktop: false,
  mediaBase: '', view: { type: 'drive', folderId: null }, kind: '', sort: 'date', order: 'desc', adv: {},
  items: [], byKey: new Map(), next: null, done: false, loading: false, reqId: 0, lastGroup: null,
  stats: null, statsReq: 0, took: null, corrected: null, words: [],
  folders: [], folderById: new Map(), saved: [], starredCount: 0, recentCount: 0, driveChannel: null,
  driveTitle: 'TG Drive', driveInfo: {}, tags: [],
  chats: [], chatById: new Map(), dialogFilters: [], chatFilter: '', chatSort: 'files',
  openGroups: new Set(JSON.parse(pref('openGroups') || '["channel","group","user","bot","saved","subjects"]')),
  openFolders: new Set(), selected: new Set(), anchor: null, drawer: null, detail: null,
  transfers: [], tsummary: null, localUploads: [], lastEvent: 0, searchScope: null, lastBrowse: '#drive',
};

export function pref(k, v) {
  try {
    if (v === undefined) return localStorage.getItem(`tgdrive.${k}`);
    if (v === null) localStorage.removeItem(`tgdrive.${k}`);
    else localStorage.setItem(`tgdrive.${k}`, String(v));
  } catch { /* storage unavailable */ }
  return null;
}

/* -------------------------------------------------------------------- api */
export class ApiError extends Error {
  constructor(message, status, data) { super(message); this.status = status; this.data = data; }
}
// Requests the app makes by itself (polling, progress saves, logs) never show a loader.
const QUIET = /\/(status|events|suggest|playback\/|crash$|clientlog|debuglog)/;
// Requests the app makes on its own; they must not keep auto-lock from locking.
const BACKGROUND = /\/(status|events|crash|clientlog|debuglog)$/;
// Someone using the window (keys, clicks, scrolling) counts as activity for auto-lock: tell the server,
// at most once a minute.
let lastActivity = 0;
function reportActivity() {
  const now = Date.now();
  if (now - lastActivity < 60000) return;
  lastActivity = now;
  fetch('/api/activity', { method: 'POST', headers: { 'X-TGDrive': '1' }, credentials: 'same-origin' }).catch(() => {});
}
for (const ev of ['pointerdown', 'keydown', 'wheel']) document.addEventListener(ev, reportActivity, { capture: true, passive: true });
export async function api(path, opts = {}) {
  const init = { method: opts.method || 'GET', headers: { 'X-TGDrive': '1' }, signal: opts.signal, credentials: 'same-origin' };
  if (opts.body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(opts.body);
  }
  const t0 = performance.now();
  const bare = path.split('?')[0];
  if (opts.background || BACKGROUND.test(bare)) init.headers['X-TGDrive-Bg'] = '1';   // doesn't count as activity
  const token = opts.quiet || QUIET.test(bare) ? null : busy.request(init.method !== 'GET');
  let res;
  try {
    res = await fetch(path, init);
  } catch (e) {
    busy.end(token);
    if (e.name === 'AbortError') { bus.emit('api', { method: init.method, path, aborted: true, ms: performance.now() - t0 }); throw e; }
    bus.emit('api', { method: init.method, path, status: 0, ms: performance.now() - t0, error: String(e) });
    throw new ApiError("Can't reach TG Drive. If you closed the app, open it again.", 0);
  }
  if (opts.raw) { busy.end(token); bus.emit('api', { method: init.method, path, status: res.status, ms: performance.now() - t0 }); return res; }
  let data = null;
  const ct = res.headers.get('content-type') || '';
  try { data = ct.includes('json') ? await res.json() : await res.text(); } catch { /* empty */ } finally { busy.end(token); }
  bus.emit('api', { method: init.method, path, status: res.status, ms: performance.now() - t0, body: opts.body,
    error: res.ok ? undefined : (data && data.error) || `HTTP ${res.status}` });
  if (res.status === 423) { bus.emit('locked'); throw new ApiError('TG Drive is locked.', 423, data); }
  if (!res.ok) throw new ApiError((data && data.error) || `TG Drive answered ${res.status}.`, res.status, data);
  return data;
}

/* ------------------------------------------------------------ busy state */
// Every request the user started shows progress: a thin bar along the top of the window, and a spinner
// on the button that started it. Nothing flashes for fast answers (the bar waits a moment before showing).
export const busy = (() => {
  let seq = 0;
  let visible = 0;
  const pending = new Map();        // token -> { timer, shown, btn }
  const btnCount = new WeakMap();
  let lastInput = { el: null, t: 0 };
  let bar = null;
  let hideTimer = 0;
  const TRIGGER = 'button, .btn, [role="menuitem"], [role="tab"], .nav-item, .crumb, .fitem, .tab, a[href^="#"]';
  const note = (e) => { lastInput = { el: e.target?.closest?.(TRIGGER) || null, t: Date.now() }; };
  document.addEventListener('pointerdown', note, true);
  document.addEventListener('keydown', note, true);
  window.addEventListener('hashchange', () => { lastInput = { el: Date.now() - lastInput.t < 700 ? lastInput.el : null, t: Date.now() }; });

  function barEl() {
    if (!bar) {
      bar = document.createElement('div');
      bar.id = 'topProgress';
      bar.setAttribute('role', 'progressbar');
      bar.setAttribute('aria-label', 'Working');
      bar.innerHTML = '<i></i>';
      document.body.append(bar);
    }
    return bar;
  }
  function paint() {
    const b = barEl();
    clearTimeout(hideTimer);
    if (visible > 0) { b.classList.remove('done'); b.classList.add('on'); }
    else if (b.classList.contains('on')) {
      b.classList.add('done');
      hideTimer = setTimeout(() => b.classList.remove('on', 'done'), 420);
    }
    document.documentElement.classList.toggle('is-busy', visible > 0);
  }
  function markBtn(btn, on) {
    if (!btn) return;
    const n = (btnCount.get(btn) || 0) + (on ? 1 : -1);
    btnCount.set(btn, Math.max(0, n));
    btn.classList.toggle('is-busy', n > 0);
    if (n > 0) btn.setAttribute('aria-busy', 'true'); else btn.removeAttribute('aria-busy');
  }
  function show(tok) {
    const p = pending.get(tok);
    if (!p || p.shown) return;
    p.shown = true;
    visible++;
    paint();
    if (p.btn?.isConnected) markBtn(p.btn, true); else p.btn = null;
  }
  return {
    // A request: shows at once when the user just clicked something, after a short wait otherwise.
    // Background reads (nobody touched anything lately) stay silent.
    request(mutating) {
      const recent = Date.now() - lastInput.t < 1500;
      if (!mutating && !recent) return null;
      const btn = recent && Date.now() - lastInput.t < 700 && lastInput.el?.isConnected ? lastInput.el : null;
      return this.start(btn ? 60 : 220, btn);
    },
    start(delay = 0, btn = null) {
      const tok = ++seq;
      pending.set(tok, { btn, shown: false, timer: 0 });
      if (delay <= 0) show(tok); else pending.get(tok).timer = setTimeout(() => show(tok), delay);
      return tok;
    },
    end(tok) {
      if (tok == null) return;
      const p = pending.get(tok);
      if (!p) return;
      pending.delete(tok);
      clearTimeout(p.timer);
      if (p.shown) { visible--; paint(); markBtn(p.btn, false); }
    },
    // Wrap any async job (a promise, or a function returning one) in the same feedback.
    async run(job, btn = null, delay = 0) {
      const tok = this.start(delay, btn);
      try { return await (typeof job === 'function' ? job() : job); } finally { this.end(tok); }
    },
  };
})();
export const A = (p) => `/api/a/${S.aid}${p}`;
export const M = (p) => `${S.mediaBase}/api/a/${S.aid}${p}`;
export const qs = (o) => new URLSearchParams(Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== '')).toString();
export const streamUrl = (f, dl = false) => M(`/stream/${f.chat_id}/${f.msg_id}/${encodeURIComponent(f.name || 'file')}${dl ? '?dl=1' : ''}`);
// A stream link for other programs (VLC, mpv, the native player): absolute, with the stream-only token.
export function externalStreamUrl(f) {
  const u = new URL(streamUrl(f), location.href);
  if (S.mediaToken) u.searchParams.set('t', S.mediaToken);
  return u.href;
}
export const thumbUrl = (f, v = 's') => M(`/thumb/${f.chat_id}/${f.msg_id}?v=${v}`);

/* -------------------------------------------------------------------- bus */
const handlers = {};
export const bus = {
  on(evt, fn) { (handlers[evt] ||= []).push(fn); },
  emit(evt, data) { (handlers[evt] || []).forEach((fn) => { try { fn(data); } catch (e) { console.error(e); } }); },
};

/* -------------------------------------------------------- inline previews */
const JPG_HEAD = '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDACgcHiMeGSgjISMtKygwPGRBPDc3PHtYXUlkkYCZlo+AjIqgtObDoKrarYqMyP/L2u71////m8H////6/+b9//j/2wBDASstLTw1PHZBQXb4pYyl+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj/wAARCAAoACgDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwA=';
let headBytes = null;
const inlineCache = new Map();
export function inlineSrc(b64) {
  if (!b64) return '';
  const hit = inlineCache.get(b64);
  if (hit) return hit;
  try {
    headBytes ||= Uint8Array.from(atob(JPG_HEAD), (c) => c.charCodeAt(0));
    const s = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    if (s.length < 3 || s[0] !== 1) return '';
    const out = new Uint8Array(headBytes.length + s.length - 3 + 2);
    out.set(headBytes);
    out[164] = s[1];
    out[166] = s[2];
    out.set(s.subarray(3), headBytes.length);
    out[out.length - 2] = 0xff;
    out[out.length - 1] = 0xd9;
    let bin = '';
    for (let i = 0; i < out.length; i++) bin += String.fromCharCode(out[i]);
    const url = `data:image/jpeg;base64,${btoa(bin)}`;
    if (inlineCache.size > 4000) inlineCache.clear();
    inlineCache.set(b64, url);
    return url;
  } catch { return ''; }
}

/* ------------------------------------------------------ thumbnail loading */
// Visible-first, limited concurrency, retry after "busy" answers. Media come from their own port,
// so even a page full of loading thumbnails can't hold up searches.
export const thumbs = (() => {
  const queue = [];
  let active = 0;
  const MAX = 6;
  let pausedUntil = 0;
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      const img = e.target;
      if (e.isIntersecting) { if (!img.dataset.state) { img.dataset.state = 'queued'; queue.push(img); } }
      else if (img.dataset.state === 'queued') { img.dataset.state = ''; const i = queue.indexOf(img); if (i >= 0) queue.splice(i, 1); }
    }
    pump();
  }, { rootMargin: '400px 0px' });
  function pump() {
    if (Date.now() < pausedUntil) { setTimeout(pump, pausedUntil - Date.now() + 50); return; }
    while (active < MAX && queue.length) {
      const img = queue.shift();
      if (!img.isConnected) continue;
      active++;
      img.dataset.state = 'loading';
      const done = (ok) => {
        active--;
        img.dataset.state = ok ? 'done' : 'failed';
        io.unobserve(img);
        pump();
      };
      fetch(img.dataset.src, { credentials: 'include' }).then(async (r) => {
        if (r.status === 503) {
          const wait = Number(r.headers.get('Retry-After') || 10);
          pausedUntil = Date.now() + wait * 1000;
          active--;
          img.dataset.state = '';
          setTimeout(() => { if (img.isConnected) { img.dataset.state = 'queued'; queue.push(img); pump(); } }, wait * 1000 + 100);
          return;
        }
        if (!r.ok || r.status === 204) {
          // A PDF without a picture yet: draw its first page (pdfthumbs.js), then keep it on the server.
          if (img.dataset.pdf && r.headers.get('X-Doc-Thumb') === 'missing') import('./pdfthumbs.js').then((m) => m.enqueue(img));
          else img.closest('.thumb')?.classList.add('no-thumb');
          done(false);
          return;
        }
        const blob = await r.blob();
        img.src = URL.createObjectURL(blob);
        img.onload = () => { img.classList.add('loaded'); img.closest('.thumb')?.classList.add('has-img'); };
        done(true);
      }).catch(() => done(false));
    }
  }
  return {
    observe(root) { for (const img of root.querySelectorAll('img[data-src]:not([data-state])')) io.observe(img); },
    reset() { queue.length = 0; },
  };
})();

/* ------------------------------------------------------- desktop bridge */
// In the desktop app, Qt exposes a small native bridge (file dialogs, native player, notifications).
export const bridge = { ready: false, obj: null };
export function initBridge() {
  return new Promise((resolve) => {
    if (!window.qt || !window.qt.webChannelTransport) return resolve(false);
    if (window.QWebChannel) {  // injected by the desktop app
      new window.QWebChannel(window.qt.webChannelTransport, (ch) => {
        bridge.obj = ch.objects.tgd;
        bridge.ready = !!bridge.obj;
        resolve(bridge.ready);
      });
      setTimeout(() => resolve(bridge.ready), 3000);
      return;
    }
    const s = document.createElement('script');
    s.src = 'qrc:///qtwebchannel/qwebchannel.js';
    s.onload = () => {
      // eslint-disable-next-line no-undef
      new QWebChannel(window.qt.webChannelTransport, (ch) => {
        bridge.obj = ch.objects.tgd;
        bridge.ready = !!bridge.obj;
        resolve(bridge.ready);
      });
    };
    s.onerror = () => resolve(false);
    document.head.append(s);
  });
}
export function callBridge(method, ...args) {
  return new Promise((resolve) => {
    if (!bridge.ready || typeof bridge.obj[method] !== 'function') return resolve(null);
    bridge.obj[method](...args, (res) => resolve(res));
  });
}

// Places: a map of photos that carry GPS coordinates (EXIF). The world map is drawn from data bundled
// with TG Drive, so it works offline; detailed OpenStreetMap tiles are optional (Settings → Photos & places).
import { $, S, A, api, esc, icon, fmtDate, fmtNum, plural, thumbUrl, inlineSrc, key, clamp, bus, copiesParam } from './core.js';
import { fail, toast, contextMenu } from './ui.js';

const TILE = 256;
let M = null;
let world = null;

async function loadWorld() {
  if (world) return world;
  const r = await fetch('/static/geo/world.json', { credentials: 'same-origin' });
  const d = await r.json();
  const dec = (arr) => {
    // Keep rings continuous across the date line (a jump of more than 180° means it wrapped).
    const pts = new Float32Array(arr.length);
    let x = 0, y = 0, shift = 0, prev = null;
    for (let i = 0; i < arr.length; i += 2) {
      x += arr[i]; y += arr[i + 1];
      const lon = x / d.q;
      if (prev !== null) { if (lon - prev > 180) shift -= 360; else if (prev - lon > 180) shift += 360; }
      prev = lon;
      pts[i] = lon + shift; pts[i + 1] = y / d.q;
    }
    return pts;
  };
  world = { land: d.land.map(dec), borders: d.borders.map(dec) };
  return world;
}

// Web Mercator in "world pixels" at zoom z: the whole world is 256·2^z wide.
const project = (lon, lat, z) => {
  const s = TILE * 2 ** z;
  const x = (lon + 180) / 360 * s;
  const sin = Math.sin(clamp(lat, -85.05, 85.05) * Math.PI / 180);
  const y = (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * s;
  return [x, y];
};
const unproject = (x, y, z) => {
  const s = TILE * 2 ** z;
  const lon = x / s * 360 - 180;
  const n = Math.PI - 2 * Math.PI * y / s;
  return [lon, 180 / Math.PI * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)))];
};

export async function renderMap() {
  const page = $('#pageView');
  page.classList.add('map-page');
  page.innerHTML = `<div class="map-wrap"><canvas class="map-canvas" id="mapCanvas"></canvas>
      <div class="map-ctl"><button class="icon-btn" data-map="in" aria-label="Zoom in">${icon('plus')}</button><button class="icon-btn" data-map="out" aria-label="Zoom out">${icon('zoomOut')}</button><button class="icon-btn" data-map="fit" aria-label="Show all" title="Show all photos">${icon('locate')}</button></div>
      <div class="map-card" id="mapCard"></div>
      <aside class="map-side" id="mapSide" hidden></aside>
      ${S.settings.map_online_tiles ? '<div class="map-attrib">© OpenStreetMap contributors</div>' : ''}</div>`;
  const canvas = $('#mapCanvas');
  M = { canvas, ctx: canvas.getContext('2d'), z: 1.4, cx: 0, cy: 0, points: [], clusters: [], imgs: new Map(), tiles: new Map(), hover: null, status: null };
  const ro = new ResizeObserver(() => { if (!canvas.isConnected) { ro.disconnect(); return; } resize(); });
  ro.observe(canvas.parentElement);
  M.ro = ro;
  wire(canvas);
  await loadWorld().catch(() => null);
  const [x, y] = project(40, 22, M.z);
  M.cx = x; M.cy = y;
  resize();
  await loadPoints();
  pollStatus();
}

async function loadPoints() {
  try {
    const r = await api(A(`/places?copies=${copiesParam()}`));
    M.points = r.points;
    M.status = r.status;
    renderCard();
    if (M.points.length) fit();
    else draw();
  } catch (e) { fail(e); }
}

function resize() {
  if (!M) return;
  const c = M.canvas;
  const r = c.parentElement.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  c.width = Math.round(r.width * dpr);
  c.height = Math.round(r.height * dpr);
  c.style.width = `${r.width}px`;
  c.style.height = `${r.height}px`;
  M.w = r.width; M.h = r.height; M.dpr = dpr;
  draw();
}

function fit() {
  if (!M.points.length) return;
  let minLon = 180, maxLon = -180, minLat = 90, maxLat = -90;
  for (const p of M.points) { minLon = Math.min(minLon, p.lon); maxLon = Math.max(maxLon, p.lon); minLat = Math.min(minLat, p.lat); maxLat = Math.max(maxLat, p.lat); }
  let z = 1;
  for (z = 17; z > 0.5; z -= 0.25) {
    const [x0, y0] = project(minLon, maxLat, z);
    const [x1, y1] = project(maxLon, minLat, z);
    if (x1 - x0 < M.w * 0.8 && y1 - y0 < M.h * 0.8) break;
  }
  M.z = clamp(z, 1, 16);
  const [x0, y0] = project(minLon, maxLat, M.z);
  const [x1, y1] = project(maxLon, minLat, M.z);
  M.cx = (x0 + x1) / 2; M.cy = (y0 + y1) / 2;
  draw();
}

function zoomAt(factor, sx = M.w / 2, sy = M.h / 2) {
  const nz = clamp(M.z + Math.log2(factor), 1, 18);
  const f = 2 ** (nz - M.z);
  const wx = M.cx + (sx - M.w / 2);
  const wy = M.cy + (sy - M.h / 2);
  M.cx = wx * f - (sx - M.w / 2);
  M.cy = wy * f - (sy - M.h / 2);
  M.z = nz;
  draw();
}

function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

function draw() {
  if (!M?.ctx || !M.w) return;
  const { ctx } = M;
  const dpr = M.dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const dark = matchMedia('(prefers-color-scheme: dark)').matches && document.documentElement.dataset.theme !== 'light' || document.documentElement.dataset.theme === 'dark';
  const sea = dark ? '#0f1b2a' : '#dbe8f3';
  const land = dark ? '#243041' : '#f6f4ee';
  const border = dark ? '#3a4a60' : '#c9c2b3';
  ctx.fillStyle = sea;
  ctx.fillRect(0, 0, M.w, M.h);
  const ox = M.cx - M.w / 2, oy = M.cy - M.h / 2;
  const worldW = TILE * 2 ** M.z;
  if (S.settings.map_online_tiles) drawTiles(ox, oy);
  else if (world) {
    // Draw the world once or twice across the date line so panning wraps.
    for (const shift of [-worldW, 0, worldW]) {
      if (ox + M.w < shift || ox > shift + worldW) continue;
      ctx.beginPath();
      for (const ring of world.land) {
        for (let i = 0; i < ring.length; i += 2) {
          const [x, y] = project(ring[i], ring[i + 1], M.z);
          const px = x - ox + shift, py = y - oy;
          if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
        }
        ctx.closePath();
      }
      ctx.fillStyle = land;
      ctx.fill('evenodd');
      if (M.z > 1.8) {
        ctx.beginPath();
        for (const line of world.borders) {
          for (let i = 0; i < line.length; i += 2) {
            const [x, y] = project(line[i], line[i + 1], M.z);
            const px = x - ox + shift, py = y - oy;
            if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
          }
        }
        ctx.strokeStyle = border;
        ctx.lineWidth = 0.8;
        ctx.stroke();
      }
    }
  }
  clusterPoints(ox, oy, worldW);
  drawClusters(dark);
}

function drawTiles(ox, oy) {
  const z = Math.round(M.z);
  const scale = 2 ** (M.z - z);
  const size = TILE * scale;
  const n = 2 ** z;
  const x0 = Math.floor(ox / size), x1 = Math.floor((ox + M.w) / size);
  const y0 = Math.max(0, Math.floor(oy / size)), y1 = Math.min(n - 1, Math.floor((oy + M.h) / size));
  for (let ty = y0; ty <= y1; ty++) {
    for (let tx = x0; tx <= x1; tx++) {
      const wx = ((tx % n) + n) % n;
      const k = `${z}/${wx}/${ty}`;
      let img = M.tiles.get(k);
      if (!img) {
        img = new Image();
        img.referrerPolicy = 'no-referrer';
        img.onload = () => draw();
        img.src = `https://tile.openstreetmap.org/${k}.png`;
        M.tiles.set(k, img);
        if (M.tiles.size > 600) M.tiles.delete(M.tiles.keys().next().value);
      }
      if (img.complete && img.naturalWidth) M.ctx.drawImage(img, tx * size - ox, ty * size - oy, size, size);
    }
  }
}

function clusterPoints(ox, oy, worldW) {
  const cell = 64;
  const buckets = new Map();
  for (const p of M.points) {
    let [x, y] = project(p.lon, p.lat, M.z);
    x -= ox; y -= oy;
    while (x < -cell) x += worldW;
    while (x > M.w + cell) x -= worldW;
    if (x < -cell || y < -cell || x > M.w + cell || y > M.h + cell) continue;
    const k = `${Math.floor(x / cell)}:${Math.floor(y / cell)}`;
    let b = buckets.get(k);
    if (!b) { b = { x: 0, y: 0, items: [] }; buckets.set(k, b); }
    b.items.push(p);
    b.x += x; b.y += y;
  }
  M.clusters = [...buckets.values()].map((b) => ({ x: b.x / b.items.length, y: b.y / b.items.length, items: b.items }));
}

function thumbImg(p) {
  const k = key(p);
  let img = M.imgs.get(k);
  if (!img && p.has_thumb) {
    img = new Image();
    img.onload = () => draw();
    img.src = thumbUrl(p, 's');
    M.imgs.set(k, img);
  }
  return img;
}

function drawClusters(dark) {
  const { ctx } = M;
  for (const c of M.clusters) {
    const r = c.items.length > 1 ? 26 : 22;
    const p = c.items[0];
    const img = thumbImg(p);
    ctx.save();
    ctx.shadowColor = 'rgba(0,0,0,.35)';
    ctx.shadowBlur = 8;
    ctx.beginPath();
    ctx.roundRect(c.x - r, c.y - r, r * 2, r * 2, 10);
    ctx.fillStyle = '#fff';
    ctx.fill();
    ctx.restore();
    ctx.save();
    ctx.beginPath();
    ctx.roundRect(c.x - r + 3, c.y - r + 3, r * 2 - 6, r * 2 - 6, 7);
    ctx.clip();
    if (img?.complete && img.naturalWidth) {
      const s = Math.max((r * 2 - 6) / img.naturalWidth, (r * 2 - 6) / img.naturalHeight);
      ctx.drawImage(img, c.x - img.naturalWidth * s / 2, c.y - img.naturalHeight * s / 2, img.naturalWidth * s, img.naturalHeight * s);
    } else {
      ctx.fillStyle = css('--accent') || '#2a7fc9';
      ctx.fillRect(c.x - r, c.y - r, r * 2, r * 2);
    }
    ctx.restore();
    if (c.items.length > 1) {
      const label = c.items.length > 999 ? `${Math.round(c.items.length / 100) / 10}k` : String(c.items.length);
      ctx.font = `700 ${Math.round(11 * (Number(S.settings.font_scale) || 1))}px ${css('--font') || 'sans-serif'}`;
      const w = Math.max(20, ctx.measureText(label).width + 10);
      ctx.beginPath();
      ctx.roundRect(c.x + r - w + 6, c.y - r - 8, w, 18, 9);
      ctx.fillStyle = css('--accent') || '#2a7fc9';
      ctx.fill();
      ctx.fillStyle = '#fff';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(label, c.x + r - w / 2 + 6, c.y - r + 1);
    }
    if (M.hover === c) {
      ctx.strokeStyle = css('--accent') || '#2a7fc9';
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.roundRect(c.x - r - 2, c.y - r - 2, r * 2 + 4, r * 2 + 4, 12);
      ctx.stroke();
    }
  }
}

function clusterAt(x, y) {
  let best = null, bd = 30 * 30;
  for (const c of M.clusters) { const d = (c.x - x) ** 2 + (c.y - y) ** 2; if (d < bd) { bd = d; best = c; } }
  return best;
}

function wire(canvas) {
  let drag = null;
  canvas.addEventListener('pointerdown', (e) => { drag = { x: e.clientX, y: e.clientY, cx: M.cx, cy: M.cy, moved: false }; canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener('pointermove', (e) => {
    const r = canvas.getBoundingClientRect();
    if (drag) {
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
      M.cx = drag.cx - dx; M.cy = drag.cy - dy;
      draw();
      return;
    }
    const c = clusterAt(e.clientX - r.left, e.clientY - r.top);
    if (c !== M.hover) { M.hover = c; canvas.style.cursor = c ? 'pointer' : 'grab'; draw(); }
  });
  canvas.addEventListener('pointerup', (e) => {
    const r = canvas.getBoundingClientRect();
    if (drag && !drag.moved) {
      const c = clusterAt(e.clientX - r.left, e.clientY - r.top);
      if (c) showCluster(c);
    }
    drag = null;
  });
  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    const r = canvas.getBoundingClientRect();
    zoomAt(e.deltaY < 0 ? 1.25 : 0.8, e.clientX - r.left, e.clientY - r.top);
  }, { passive: false });
  canvas.addEventListener('dblclick', (e) => { const r = canvas.getBoundingClientRect(); zoomAt(2, e.clientX - r.left, e.clientY - r.top); });
}

function showCluster(c) {
  const side = $('#mapSide');
  const items = c.items;
  const [lon, lat] = unproject(M.cx + c.x - M.w / 2, M.cy + c.y - M.h / 2, M.z);
  const dates = items.map((p) => p.taken || p.date).filter(Boolean).sort();
  side.hidden = false;
  side.innerHTML = `<div class="ms-head"><div><strong>${plural(items.length, 'photo')}</strong><small>${lat.toFixed(3)}, ${lon.toFixed(3)}${dates.length ? ` · ${fmtDate(dates[0])}${dates.length > 1 && dates[0] !== dates[dates.length - 1] ? ` – ${fmtDate(dates[dates.length - 1])}` : ''}` : ''}</small></div>
    <button class="icon-btn" data-map="closeside" aria-label="Close">${icon('close')}</button></div>
    <div class="ms-acts"><button class="btn sm" data-map="show">${icon('slides')}Slideshow</button>${items.length > 1 ? `<button class="btn sm ghost" data-map="zoomhere">${icon('zoomIn')}Zoom in</button>` : ''}</div>
    <div class="ms-grid">${items.slice(0, 400).map((p, i) => `<button class="ms-cell" data-mapi="${i}" title="${esc(p.name)}">${p.inline ? `<img class="lqip" src="${inlineSrc(p.inline)}" alt="">` : ''}${p.has_thumb ? `<img class="real" data-src="${thumbUrl(p, 's')}" alt="">` : icon('photo')}</button>`).join('')}</div>`;
  M.sel = c;
  import('./core.js').then((m) => m.thumbs.observe(side));
}

function renderCard() {
  const card = $('#mapCard');
  if (!card || !M) return;
  const st = M.status || {};
  const n = M.points.length;
  card.innerHTML = `<div class="mc-top">${icon('map')}<div><strong>${n ? `${plural(n, 'photo')} on the map` : 'Where your photos were taken'}</strong>
      <small>${st.enabled ? (st.state === 'scanning' ? `Reading photo locations… ${fmtNum(st.checked)} checked, ${fmtNum(st.left)} to go` : st.state === 'done' ? `All ${fmtNum(st.checked)} image files checked` : `Location search is on (${esc(st.state || 'waiting')})`)
        : 'Photos sent as files keep their GPS location. TG Drive can read it (only the first 128 KB of each image file).'}</small></div></div>
    <div class="mc-acts"><label class="switch"><input type="checkbox" data-map-scan ${st.enabled ? 'checked' : ''}><span></span></label><span>Find photo locations</span></div>
    ${st.enabled && st.left ? `<div class="bar"><i style="width:${Math.round((st.checked / Math.max(1, st.checked + st.left)) * 100)}%"></i></div>` : ''}`;
}

async function pollStatus() {
  if (!M || !$('#mapCard')) return;
  try {
    const st = await api(A('/places/status'));
    const grew = M.status && st.found > (M.status.found || 0);
    M.status = st;
    renderCard();
    if (grew) loadPoints();
  } catch { /* ignore */ }
  setTimeout(pollStatus, M?.status?.state === 'scanning' ? 4000 : 15000);
}

document.addEventListener('click', async (e) => {
  if (!M || !$('#mapCanvas')) return;
  const b = e.target.closest('[data-map]');
  if (b) {
    const a = b.dataset.map;
    if (a === 'in') zoomAt(2);
    if (a === 'out') zoomAt(0.5);
    if (a === 'fit') fit();
    if (a === 'closeside') { $('#mapSide').hidden = true; M.sel = null; }
    if (a === 'show' && M.sel) (await import('./viewer.js')).slideshow(M.sel.items);
    if (a === 'zoomhere' && M.sel) zoomAt(4, M.sel.x, M.sel.y);
    return;
  }
  const c = e.target.closest('[data-mapi]');
  if (c && M.sel) {
    const f = M.sel.items[+c.dataset.mapi];
    (await import('./viewer.js')).openViewer(f, M.sel.items);
  }
});
document.addEventListener('change', async (e) => {
  if (!e.target.matches?.('[data-map-scan]')) return;
  try {
    M.status = await api(A('/places/scan'), { method: 'POST', body: { on: e.target.checked } });
    S.settings.places_scan = e.target.checked;
    renderCard();
    if (e.target.checked) toast('Looking for photo locations in the background. Photos appear on the map as they are found.');
  } catch (err) { fail(err); }
});
document.addEventListener('contextmenu', async (e) => {
  const c = e.target.closest?.('[data-mapi]');
  if (!c || !M?.sel) return;
  e.preventDefault();
  const { fileMenuItems } = await import('./actions.js');
  contextMenu(e.clientX, e.clientY, fileMenuItems([M.sel.items[+c.dataset.mapi]]));
});
bus.on('settings-changed', (k) => { if (k === 'theme' && M) draw(); });

// Virtual scrolling for the file grid and list: only the rows on screen (plus a margin) exist in the page,
// so 100,000+ results scroll as smoothly as 100. Rows are positioned absolutely inside a tall spacer.
//
// The layout is a list of rows: headers (date groups, "Related by meaning") and item rows (one entry per
// row in list mode, `cols` entries per row in grid mode). Entries are files, or album stacks.

export class VGrid {
  constructor(scroller, host, opts) {
    this.scroller = scroller;           // the element that scrolls (#content)
    this.host = host;                   // positioned container inside it (#grid)
    this.o = opts;                      // { renderEntry(e, i), renderHead(label), headOf(e, prev), onRender() }
    this.entries = [];
    this.rows = [];                     // { type: 'head'|'items', label?, from, to, top, h }
    this.mode = 'grid';
    this.cols = 1;
    this.cardH = 230;
    this.rowGap = 14;
    this.headH = 38;
    this.listH = 44;
    this.nodes = new Map();             // row index -> element
    this.frame = 0;
    this.measured = '';
    scroller.addEventListener('scroll', () => this.schedule(), { passive: true });
    this.ro = new ResizeObserver(() => { if (this.remeasure()) this.relayout(); else this.schedule(); });
    this.ro.observe(scroller);
  }

  schedule() {
    if (this.frame) return;
    this.frame = requestAnimationFrame(() => { this.frame = 0; this.render(); });
  }

  setMode(mode, sizeKey) {
    const key = `${mode}:${sizeKey}`;
    if (this.mode !== mode || this.sizeKey !== sizeKey) {
      this.mode = mode;
      this.sizeKey = sizeKey;
      this.measured = '';
    }
    this.host.classList.toggle('vlist', mode === 'list');
    this.host.classList.toggle('vgrid', mode !== 'list');
    return key;
  }

  // Card width and height come from CSS (card size setting, font size): measure one real card.
  remeasure() {
    const w = this.host.clientWidth || this.scroller.clientWidth;
    const cs = getComputedStyle(this.host);
    const min = parseFloat(cs.getPropertyValue('--card-min')) || 180;
    const gap = parseFloat(cs.getPropertyValue('--card-gap')) || 14;
    const cols = this.mode === 'list' ? 1 : Math.max(1, Math.floor((w + gap) / (min + gap)));
    const sig = `${this.mode}:${w}:${cols}:${this.sizeKey}:${document.documentElement.style.getPropertyValue('--fs')}`;
    if (sig === this.measured) return false;
    this.measured = sig;
    this.cols = cols;
    this.gap = gap;
    this.colW = (w - gap * (cols - 1)) / cols;
    const probe = document.createElement('div');
    probe.className = 'vrow';
    probe.style.cssText = `position:absolute;visibility:hidden;left:0;right:0;top:0;${this.mode === 'list' ? '' : `grid-template-columns:repeat(${cols}, minmax(0,1fr));`}`;
    const sample = this.entries[0];
    probe.innerHTML = sample ? this.o.renderEntry(sample, 0, true) : this.o.renderEntry(null, 0, true);
    this.host.append(probe);
    const h = probe.firstElementChild ? probe.firstElementChild.getBoundingClientRect().height : 0;
    probe.innerHTML = this.o.renderHead('Probe');
    const hh = probe.firstElementChild ? probe.firstElementChild.getBoundingClientRect().height : 0;
    probe.remove();
    if (this.mode === 'list') this.listH = Math.max(28, Math.round(h) || 44);
    else this.cardH = Math.max(80, Math.round(h) || 230);
    this.headH = Math.max(24, Math.round(hh) || 38);
    this.rowGap = this.mode === 'list' ? 0 : gap;
    return true;
  }

  // Replace everything.
  reset(entries) {
    this.entries = entries;
    this.clearNodes();
    this.remeasure();
    this.build(0);
    this.render();
  }

  // Entries from index `from` changed or were added (appending more results).
  update(entries, from) {
    this.entries = entries;
    if (this.remeasure()) { this.clearNodes(); this.build(0); } else this.build(from);
    this.render();
  }

  relayout() {
    this.clearNodes();
    this.build(0);
    this.render();
  }

  clearNodes() {
    for (const el of this.nodes.values()) el.remove();
    this.nodes.clear();
  }

  // (Re)build rows starting at the row that holds entry `from`.
  build(from) {
    let r = 0;
    if (from > 0 && this.rows.length) {
      r = this.rows.findIndex((row) => row.type === 'items' && row.to > from);
      if (r < 0) r = this.rows.length;
      while (r > 0 && this.rows[r - 1].type === 'head') r--;   // keep a header with its first row
      for (let k = r; k < this.rows.length; k++) { const el = this.nodes.get(k); if (el) { el.remove(); this.nodes.delete(k); } }
      this.rows.length = r;
    } else {
      this.rows = [];
      this.clearNodes();
    }
    let top = this.rows.length ? this.rows[this.rows.length - 1].top + this.rows[this.rows.length - 1].h : 0;
    let i = this.rows.length ? this.rows[this.rows.length - 1].to : 0;
    const perRow = this.mode === 'list' ? 1 : this.cols;
    const itemH = this.mode === 'list' ? this.listH : this.cardH + this.rowGap;
    while (i < this.entries.length) {
      const head = this.o.headOf(this.entries[i], i ? this.entries[i - 1] : null, i);
      if (head) { this.rows.push({ type: 'head', label: head, from: i, to: i, top, h: this.headH }); top += this.headH; }
      let j = i + 1;
      while (j < this.entries.length && j - i < perRow && !this.o.headOf(this.entries[j], this.entries[j - 1], j)) j++;
      this.rows.push({ type: 'items', from: i, to: j, top, h: itemH });
      top += itemH;
      i = j;
    }
    this.total = top;
    this.host.style.height = `${Math.max(0, top)}px`;
  }

  visibleRange() {
    const offset = this.host.offsetTop;
    const y0 = this.scroller.scrollTop - offset;
    const vh = this.scroller.clientHeight;
    const pad = vh * 1.2;
    return [y0 - pad, y0 + vh + pad];
  }

  rowAt(y) {
    let lo = 0, hi = this.rows.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (this.rows[mid].top <= y) lo = mid; else hi = mid - 1;
    }
    return lo;
  }

  render() {
    if (!this.rows.length) { this.clearNodes(); this.o.onRender?.(); return; }
    const [a, b] = this.visibleRange();
    const first = this.rowAt(Math.max(0, a));
    let last = first;
    while (last < this.rows.length - 1 && this.rows[last + 1].top < b) last++;
    for (const [k, el] of this.nodes) if (k < first || k > last) { el.remove(); this.nodes.delete(k); }
    const frag = document.createDocumentFragment();
    for (let k = first; k <= last; k++) {
      if (this.nodes.has(k)) continue;
      const el = this.makeRow(k);
      this.nodes.set(k, el);
      frag.append(el);
    }
    if (frag.childNodes.length) this.host.append(frag);
    this.o.onRender?.();
  }

  makeRow(k) {
    const row = this.rows[k];
    const el = document.createElement('div');
    el.className = row.type === 'head' ? 'vrow vhead' : 'vrow';
    el.style.transform = `translateY(${row.top}px)`;
    el.dataset.row = k;
    if (row.type === 'head') el.innerHTML = this.o.renderHead(row.label);
    else {
      if (this.mode !== 'list') el.style.gridTemplateColumns = `repeat(${this.cols}, minmax(0, 1fr))`;
      let html = '';
      for (let i = row.from; i < row.to; i++) html += this.o.renderEntry(this.entries[i], i);
      el.innerHTML = html;
    }
    return el;
  }

  // Re-render the row holding entry i (after a change to that file).
  refreshEntry(i) {
    const k = this.rows.findIndex((r) => r.type === 'items' && i >= r.from && i < r.to);
    if (k < 0) return;
    const el = this.nodes.get(k);
    if (!el) return;
    const fresh = this.makeRow(k);
    el.replaceWith(fresh);
    this.nodes.set(k, fresh);
    this.o.onRender?.();
  }

  refreshAll() {
    for (const [k, el] of this.nodes) { const fresh = this.makeRow(k); el.replaceWith(fresh); this.nodes.set(k, fresh); }
    this.o.onRender?.();
  }

  // Scroll so entry i is visible; returns after the row is rendered.
  scrollToEntry(i, block = 'nearest') {
    const row = this.rows.find((r) => r.type === 'items' && i >= r.from && i < r.to);
    if (!row) return;
    const offset = this.host.offsetTop;
    const top = row.top + offset;
    const bottom = top + row.h;
    const st = this.scroller.scrollTop;
    const vh = this.scroller.clientHeight;
    if (block === 'start') this.scroller.scrollTop = top - 8;
    else if (top < st + 8) this.scroller.scrollTop = top - 8;
    else if (bottom > st + vh - 8) this.scroller.scrollTop = bottom - vh + 8;
    this.render();
  }

  columns() { return this.mode === 'list' ? 1 : this.cols; }

  // Entry index directly above / below i (for arrow keys), respecting header rows.
  vertical(i, dir) {
    const k = this.rows.findIndex((r) => r.type === 'items' && i >= r.from && i < r.to);
    if (k < 0) return i;
    const col = i - this.rows[k].from;
    let m = k + dir;
    while (m >= 0 && m < this.rows.length && this.rows[m].type !== 'items') m += dir;
    if (m < 0 || m >= this.rows.length) return i;
    const r = this.rows[m];
    return Math.min(r.to - 1, r.from + col);
  }

  destroy() { this.ro.disconnect(); this.clearNodes(); }
}

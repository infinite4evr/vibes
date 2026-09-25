"""Custom widgets: live graphs (Cairo), ring gauge, bars, and a sortable/searchable table."""

from __future__ import annotations

import math
from collections import deque
from typing import Any, Callable, Sequence

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GLib, GObject, Gtk, Pango, PangoCairo  # noqa: E402

from ..core.fmt import human  # noqa: E402
from . import theme  # noqa: E402
from .util import label  # noqa: E402


def rgb(name: str, a: float = 1.0) -> tuple[float, float, float, float]:
    """A palette colour (by Catppuccin name, for the current light/dark style) or a #hex value as cairo RGBA."""
    h = theme.hex(name).lstrip("#")
    return int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, a


def level_color(pct: float, warn: float = 75, crit: float = 90) -> str:
    return "red" if pct >= crit else ("peach" if pct >= warn else "green")


# ---------------------------------------------------------------- graphs

class LineGraph(Gtk.DrawingArea):
    """Scrolling line graph with a soft fill. Supports several series."""

    def __init__(self, series: Sequence[str] = ("mauve",), points: int = 60, height: int = 70, maximum: float | None = 100.0):
        super().__init__()
        self.colors = list(series)
        self.data = [deque([0.0] * points, maxlen=points) for _ in series]
        self.maximum = maximum
        self.set_content_height(height)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)

    def push(self, *values: float) -> None:
        for d, v in zip(self.data, values):
            d.append(max(0.0, float(v or 0)))
        self.queue_draw()

    def _draw(self, _area, cr, w: int, h: int) -> None:
        top = self.maximum or max((max(d) for d in self.data), default=1) or 1
        if not self.maximum:
            top *= 1.15
        cr.set_line_width(1)
        cr.set_source_rgba(*rgb("surface1", 0.5))
        for frac in (0.25, 0.5, 0.75):
            y = round(h * frac) + 0.5
            cr.move_to(0, y)
            cr.line_to(w, y)
        cr.stroke()
        for color, d in zip(self.colors, self.data):
            n = len(d)
            if n < 2:
                continue
            step = w / (n - 1)
            pts = [(i * step, h - 2 - (v / top) * (h - 4)) for i, v in enumerate(d)]
            cr.move_to(*pts[0])
            for i in range(1, n):
                x0, y0 = pts[i - 1]
                x1, y1 = pts[i]
                cx = (x0 + x1) / 2
                cr.curve_to(cx, y0, cx, y1, x1, y1)
            cr.set_source_rgba(*rgb(color, 1))
            cr.set_line_width(2)
            cr.stroke_preserve()
            cr.line_to(w, h)
            cr.line_to(0, h)
            cr.close_path()
            cr.set_source_rgba(*rgb(color, 0.14))
            cr.fill()


class RingGauge(Gtk.DrawingArea):
    """Circular progress with a big number in the middle."""

    def __init__(self, size: int = 120, width: float = 11):
        super().__init__()
        self.value = 0.0
        self.text = "--"
        self.sub = ""
        self.color = "mauve"
        self.w = width
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_draw_func(self._draw)

    def set(self, value: float, text: str | None = None, sub: str = "", color: str | None = None) -> None:
        self.value = max(0.0, min(100.0, value))
        self.text = text if text is not None else f"{value:.0f}"
        self.sub = sub
        self.color = color or level_color(100 - value, 40, 60)
        self.queue_draw()

    def _draw(self, _a, cr, w: int, h: int) -> None:
        r = min(w, h) / 2 - self.w / 2 - 1
        cx, cy = w / 2, h / 2
        cr.set_line_width(self.w)
        cr.set_line_cap(1)  # round
        cr.set_source_rgba(*rgb("surface0", 1))
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.stroke()
        if self.value > 0:
            cr.set_source_rgba(*rgb(self.color, 1))
            start = -math.pi / 2
            cr.arc(cx, cy, r, start, start + 2 * math.pi * self.value / 100)
            cr.stroke()
        cr.set_source_rgba(*rgb("text", 1))
        cr.select_font_face("Sans", 0, 1)
        cr.set_font_size(r * 0.62)
        ext = cr.text_extents(self.text)
        cr.move_to(cx - ext.width / 2 - ext.x_bearing, cy + (ext.height / 2 if not self.sub else ext.height * 0.35))
        cr.show_text(self.text)
        if self.sub:
            cr.set_source_rgba(*rgb("overlay1", 1))
            cr.select_font_face("Sans", 0, 0)
            cr.set_font_size(r * 0.2)
            ext2 = cr.text_extents(self.sub)
            cr.move_to(cx - ext2.width / 2 - ext2.x_bearing, cy + ext.height * 0.35 + r * 0.32)
            cr.show_text(self.sub)


class MiniBar(Gtk.DrawingArea):
    """Thin rounded progress bar with threshold colours."""

    def __init__(self, width: int = -1, height: int = 8, warn: float = 75, crit: float = 90, color: str | None = None,
                 vertical: bool = False):
        super().__init__()
        self.frac = 0.0
        self.vertical = vertical
        self.warn, self.crit, self.fixed = warn, crit, color
        if width > 0:
            self.set_content_width(width)
        else:
            self.set_hexpand(True)
        self.set_content_height(height)
        self.set_valign(Gtk.Align.CENTER)
        self.set_draw_func(self._draw)

    def set(self, frac: float) -> None:
        self.frac = max(0.0, min(1.0, frac))
        self.queue_draw()

    def _draw(self, _a, cr, w: int, h: int) -> None:
        if self.vertical:
            rad = min(3.0, w / 2)
            cr.set_source_rgba(*rgb("surface0", 1))
            _round_rect(cr, 0, 0, w, h, rad)
            cr.fill()
            if self.frac > 0.001:
                cr.set_source_rgba(*rgb(self.fixed or level_color(self.frac * 100, self.warn, self.crit), 1))
                fh = max(2.0, h * self.frac)
                _round_rect(cr, 0, h - fh, w, fh, rad)
                cr.fill()
            return
        r = h / 2

        def rounded(x: float, width: float) -> None:
            if width < h:
                width = h
            cr.new_sub_path()
            cr.arc(x + width - r, r, r, -math.pi / 2, math.pi / 2)
            cr.arc(x + r, r, r, math.pi / 2, 3 * math.pi / 2)
            cr.close_path()
        cr.set_source_rgba(*rgb("surface0", 1))
        rounded(0, w)
        cr.fill()
        if self.frac > 0.001:
            color = self.fixed or level_color(self.frac * 100, self.warn, self.crit)
            cr.set_source_rgba(*rgb(color, 1))
            rounded(0, max(h, w * self.frac))
            cr.fill()


class HBars(Gtk.DrawingArea):
    """Horizontal bar chart: [(label, value, value_text)]."""

    def __init__(self, color: str = "mauve", row: int = 24, label_width: int = 230):
        super().__init__()
        self.items: list[tuple[str, float, str]] = []
        self.color, self.row, self.lw = color, row, label_width
        self.set_hexpand(True)
        self.set_draw_func(self._draw)

    def set_items(self, items: list[tuple[str, float, str]]) -> None:
        self.items = items
        self.set_content_height(max(self.row, len(items) * self.row))
        self.queue_draw()

    def _draw(self, _a, cr, w: int, h: int) -> None:
        if not self.items:
            return
        top = max(v for _, v, _ in self.items) or 1
        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(12.5)
        vw = 90
        bw = max(40, w - self.lw - vw - 12)
        for i, (name, v, vt) in enumerate(self.items):
            y = i * self.row
            cr.set_source_rgba(*rgb("subtext1", 1))
            txt = name if len(name) < 34 else name[:32] + "…"
            cr.move_to(0, y + self.row * 0.68)
            cr.show_text(txt)
            cr.set_source_rgba(*rgb("surface0", 1))
            _round_rect(cr, self.lw, y + 6, bw, self.row - 12, 4)
            cr.fill()
            cr.set_source_rgba(*rgb(self.color, 0.9))
            _round_rect(cr, self.lw, y + 6, max(4, bw * v / top), self.row - 12, 4)
            cr.fill()
            cr.set_source_rgba(*rgb("overlay2", 1))
            cr.move_to(self.lw + bw + 10, y + self.row * 0.68)
            cr.show_text(vt)


def squarify(values: list[float], x: float, y: float, w: float, h: float) -> list[tuple[float, float, float, float]]:
    """Squarified treemap layout (Bruls et al.). values must be sorted descending; returns one rect per value."""
    total = sum(values)
    if total <= 0 or w <= 0 or h <= 0:
        return [(x, y, 0, 0) for _ in values]
    scaled = [v * w * h / total for v in values]
    rects: list[tuple[float, float, float, float]] = []

    def worst(row: list[float], side: float) -> float:
        s = sum(row)
        if s <= 0:
            return float("inf")
        mx, mn = max(row), min(row)
        return max(side * side * mx / (s * s), (s * s) / (side * side * mn)) if mn > 0 else float("inf")

    def layout(row: list[float], x: float, y: float, w: float, h: float) -> tuple[float, float, float, float]:
        s = sum(row)
        if w >= h:  # lay the row out as a column on the left
            cw = s / h if h else 0
            yy = y
            for v in row:
                rh = v / cw if cw else 0
                rects.append((x, yy, cw, rh))
                yy += rh
            return x + cw, y, w - cw, h
        rh = s / w if w else 0
        xx = x
        for v in row:
            cw = v / rh if rh else 0
            rects.append((xx, y, cw, rh))
            xx += cw
        return x, y + rh, w, h - rh

    row: list[float] = []
    i = 0
    while i < len(scaled):
        side = min(w, h)
        v = scaled[i]
        if not row or worst(row + [v], side) <= worst(row, side):
            row.append(v)
            i += 1
        else:
            x, y, w, h = layout(row, x, y, w, h)
            row = []
    if row:
        layout(row, x, y, w, h)
    return rects


TREEMAP_COLORS = ["mauve", "blue", "teal", "green", "peach", "pink", "sapphire", "yellow", "lavender", "flamingo", "sky", "maroon"]


class Treemap(Gtk.DrawingArea):
    """Rectangles sized by how much space each item takes. Click to open a folder; hover for details."""

    def __init__(self, height: int = 360, on_click: Callable[[str], None] | None = None):
        super().__init__()
        self.items: list[tuple[str, float, str, str]] = []  # label, size, key, detail
        self.rects: list[tuple[float, float, float, float]] = []
        self.on_click = on_click
        self.set_content_height(height)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)
        self.set_has_tooltip(True)
        self.connect("query-tooltip", self._tooltip)
        click = Gtk.GestureClick()
        click.connect("released", self._clicked)
        self.add_controller(click)
        self.set_cursor(Gdk.Cursor.new_from_name("pointer"))

    def set_items(self, items: list[tuple[str, float, str, str]]) -> None:
        self.items = [it for it in sorted(items, key=lambda i: -i[1]) if it[1] > 0][:60]
        self.queue_draw()

    def _hit(self, x: float, y: float) -> int | None:
        for i, (rx, ry, rw, rh) in enumerate(self.rects):
            if rx <= x < rx + rw and ry <= y < ry + rh:
                return i
        return None

    def _tooltip(self, _w, x, y, _kb, tip) -> bool:
        i = self._hit(x, y)
        if i is None or i >= len(self.items):
            return False
        lab, size, _k, detail = self.items[i]
        tip.set_text(f"{lab}\n{human(size)}" + (f"\n{detail}" if detail else ""))
        return True

    def _clicked(self, _g, _n, x, y) -> None:
        i = self._hit(x, y)
        if i is not None and i < len(self.items) and self.on_click:
            self.on_click(self.items[i][2])

    def _draw(self, _a, cr, w: int, h: int) -> None:
        self.rects = squarify([it[1] for it in self.items], 0, 0, w, h)
        for i, ((rx, ry, rw, rh), it) in enumerate(zip(self.rects, self.items)):
            color = TREEMAP_COLORS[i % len(TREEMAP_COLORS)]
            cr.set_source_rgba(*rgb(color, 0.88 if i < 12 else 0.55))
            _round_rect(cr, rx + 1.5, ry + 1.5, max(0, rw - 3), max(0, rh - 3), 6)
            cr.fill()
            if rw > 70 and rh > 34:
                cr.set_source_rgba(*rgb("on_color", 1))
                layout = self.create_pango_layout(f"{it[0]}\n{human(it[1])}")
                layout.set_width(int((rw - 14) * Pango.SCALE))
                layout.set_ellipsize(Pango.EllipsizeMode.END)
                layout.set_height(int((rh - 10) * Pango.SCALE))
                cr.move_to(rx + 8, ry + 6)
                PangoCairo.show_layout(cr, layout)


def _round_rect(cr, x: float, y: float, w: float, h: float, r: float) -> None:
    r = min(r, h / 2, w / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


# ---------------------------------------------------------------- cards

def card(*children: Gtk.Widget, title: str | None = None, pad: bool = True, spacing: int = 8) -> Gtk.Box:
    b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    b.add_css_class("card")
    if pad:
        b.add_css_class("card-pad")
    if title:
        b.append(label(title.upper(), "tile-title"))
    for c in children:
        if c is not None:
            b.append(c)
    return b


# ---------------------------------------------------------------- table

class Row(GObject.Object):
    __gtype_name__ = "PcRow"

    def __init__(self, data: dict):
        super().__init__()
        self.data = data


class Column:
    """kind: text | bold | muted | mono | size | pct | num | markup | pill | bar"""

    def __init__(self, key: str, title: str, kind: str = "text", expand: bool = False, width: int = -1, sort: str | None = None,
                 fmt: Callable[[Any, dict], str] | None = None):
        self.key, self.title, self.kind, self.expand, self.width = key, title, kind, expand, width
        self.sort = sort or key
        self.fmt = fmt


def _sort_value(v: Any) -> tuple:
    if v is None:
        return (0, 0)
    if isinstance(v, (int, float)):
        return (1, v)
    if isinstance(v, (list, tuple)) and v:
        return _sort_value(v[0])
    return (2, str(v).lower())


class DataTable(Gtk.Box):
    """Sortable, filterable table. Rows are dicts that must include a unique 'key'."""

    def __init__(self, columns: list[Column], on_activate: Callable[[dict], None] | None = None,
                 on_select: Callable[[dict | None], None] | None = None, search: Callable[[dict, str], bool] | None = None,
                 empty: str = "Nothing here", sort: str | None = None, descending: bool = True):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.columns = columns
        self.on_activate_cb = on_activate
        self.on_select_cb = on_select
        self.search_fn = search or (lambda d, q: any(q in str(v).lower() for k, v in d.items() if isinstance(v, (str, int))))
        self.query = ""
        self.store = Gio_ListStore()
        self.filter = Gtk.CustomFilter.new(self._filter_func, None)
        self.filtered = Gtk.FilterListModel(model=self.store, filter=self.filter)
        self.view = Gtk.ColumnView()
        self.view.add_css_class("data-table")
        self.view.set_reorderable(False)
        self.view.set_show_row_separators(False)
        self.sorted = Gtk.SortListModel(model=self.filtered, sorter=self.view.get_sorter())
        self.selection = Gtk.SingleSelection(model=self.sorted, autoselect=True, can_unselect=True)
        self.view.set_model(self.selection)
        self.view.connect("activate", self._activate)
        self.selection.connect("notify::selected-item", self._selected)
        self.context_fn: Callable[[dict], list[tuple[str, Callable[[dict], None]]]] | None = None
        self.export_name = "table"
        rc = Gtk.GestureClick(button=3)
        rc.connect("pressed", self._right_click)
        self.view.add_controller(rc)
        lp = Gtk.GestureLongPress()
        lp.connect("pressed", lambda g, x, y: self._right_click(g, 1, x, y))
        self.view.add_controller(lp)
        self._cols: dict[str, Gtk.ColumnViewColumn] = {}
        for col in columns:
            factory = Gtk.SignalListItemFactory()
            factory.connect("setup", self._setup, col)
            factory.connect("bind", self._bind, col)
            c = Gtk.ColumnViewColumn(title=col.title.upper(), factory=factory)
            c.set_expand(col.expand)
            c.set_resizable(True)
            if col.width > 0:
                c.set_fixed_width(col.width)
            c.set_sorter(Gtk.CustomSorter.new(self._make_cmp(col.sort), None))
            self.view.append_column(c)
            self._cols[col.key] = c
        sw = Gtk.ScrolledWindow()
        sw.set_vexpand(True)
        sw.set_child(self.view)
        sw.add_css_class("table-frame")
        self.stack = Gtk.Stack()
        self.stack.add_named(sw, "table")
        self.empty_label = label(empty, "dim", xalign=0.5)
        self.empty_label.set_vexpand(True)
        self.stack.add_named(self.empty_label, "empty")
        self.append(self.stack)
        if sort and sort in self._cols:
            self.view.sort_by_column(self._cols[sort], Gtk.SortType.DESCENDING if descending else Gtk.SortType.ASCENDING)

    # -- factories
    def _setup(self, _f, item: Gtk.ListItem, col: Column) -> None:
        if col.kind == "bar":
            box = Gtk.Box(spacing=8)
            bar = MiniBar(width=70, height=7, warn=101, crit=101, color="mauve")
            lb = label("", "dim")
            lb.set_width_chars(6)
            box.append(bar)
            box.append(lb)
            item.set_child(box)
        elif col.kind == "pill":
            item.set_child(label("", "pill"))
        else:
            lb = Gtk.Label(xalign=1.0 if col.kind in ("size", "pct", "num") else 0.0)
            lb.set_ellipsize(Pango.EllipsizeMode.END)
            lb.set_single_line_mode(True)
            if col.kind == "bold":
                lb.add_css_class("heading")
            elif col.kind in ("muted",):
                lb.add_css_class("dim")
            elif col.kind == "mono":
                lb.add_css_class("mono")
                lb.add_css_class("dim")
            item.set_child(lb)

    def _bind(self, _f, item: Gtk.ListItem, col: Column) -> None:
        row: Row = item.get_item()
        d = row.data
        v = d.get(col.key)
        w = item.get_child()
        w._pos = item.get_position()
        if col.kind == "bar":
            bar, lb = w.get_first_child(), w.get_last_child()
            frac = float(v or 0)
            bar.set(frac)
            lb.set_text(col.fmt(v, d) if col.fmt else f"{frac * 100:.0f}%")
            return
        if col.kind == "pill":
            text, kind = (v if isinstance(v, (tuple, list)) else (str(v or ""), "neutral"))
            for k in ("neutral", "ok", "warn", "bad", "info", "accent"):
                w.remove_css_class(f"pill-{k}")
            w.add_css_class(f"pill-{kind}")
            w.set_text(text)
            w.set_visible(bool(text))
            return
        if col.fmt:
            text = col.fmt(v, d)
        elif col.kind == "size":
            text = human(v) if v else ""
        elif col.kind == "pct":
            text = f"{v:.1f}%" if isinstance(v, (int, float)) else ""
        else:
            text = "" if v is None else str(v)
        if col.kind == "markup":
            w.set_markup(text)
        else:
            text = text.replace("\n", " ")
            w.set_text(text)
        w.set_tooltip_text(text if len(text) > 40 and col.kind != "markup" else None)

    def _make_cmp(self, key: str):
        def cmp(a: Row, b: Row, _data=None) -> int:
            va, vb = _sort_value(a.data.get(key)), _sort_value(b.data.get(key))
            return (va > vb) - (va < vb)
        return cmp

    def _filter_func(self, row: Row, _data=None) -> bool:
        return not self.query or self.search_fn(row.data, self.query)

    # -- API
    def set_filter(self, text: str) -> None:
        self.query = text.strip().lower()
        self.filter.changed(Gtk.FilterChange.DIFFERENT)
        self._update_empty()

    def refilter(self) -> None:
        self.filter.changed(Gtk.FilterChange.DIFFERENT)
        self._update_empty()

    def set_rows(self, rows: list[dict]) -> None:
        sel = self.selected()
        key = sel.get("key") if sel else None
        self.store.splice(0, self.store.get_n_items(), [Row(r) for r in rows])
        if key is not None:
            for i in range(self.selection.get_n_items()):
                if self.selection.get_item(i).data.get("key") == key:
                    self.selection.set_selected(i)
                    break
        self._update_empty()

    def _update_empty(self) -> None:
        self.stack.set_visible_child_name("table" if self.selection.get_n_items() else "empty")

    def selected(self) -> dict | None:
        item = self.selection.get_selected_item()
        return item.data if item is not None else None

    def rows(self) -> list[dict]:
        return [self.store.get_item(i).data for i in range(self.store.get_n_items())]

    def set_empty(self, text: str) -> None:
        self.empty_label.set_text(text)

    # -- right-click menu + CSV export
    def set_context(self, fn: Callable[[dict], list[tuple[str, Callable[[dict], None]]]], export_name: str = "table") -> None:
        """fn(row) -> [(label, callback(row))] shown on right-click, above Copy / Export."""
        self.context_fn = fn
        self.export_name = export_name

    def _right_click(self, _g, _n, x: float, y: float) -> None:
        w = self.view.pick(x, y, Gtk.PickFlags.DEFAULT)
        pos = None
        while w is not None and w is not self.view:
            if hasattr(w, "_pos"):
                pos = w._pos
                break
            if w.get_first_child() is not None and hasattr(w.get_first_child(), "_pos"):
                pos = w.get_first_child()._pos
                break
            w = w.get_parent()
        if pos is None or pos >= self.selection.get_n_items():
            return
        self.selection.set_selected(pos)
        row = self.selection.get_item(pos).data
        entries = list(self.context_fn(row)) if self.context_fn else []
        entries += [None, ("Copy row", self._copy_row, "edit-copy-symbolic"),
                    ("Export table as CSV…", lambda _r: self.export_csv(), "document-save-symbolic")]
        self._ctx_pop = context_menu(self.view, x, y, entries, row)

    def _cell_text(self, col: Column, d: dict) -> str:
        v = d.get(col.key)
        if col.fmt:
            try:
                return col.fmt(v, d)
            except Exception:  # noqa: BLE001
                return str(v)
        if col.kind == "size":
            return human(v) if v else ""
        if col.kind == "pill":
            return v[0] if isinstance(v, (tuple, list)) else str(v or "")
        if col.kind == "markup":
            return Pango.parse_markup(str(v or ""), -1, "\0")[2] if v else ""
        return "" if v is None else str(v)

    def _copy_row(self, d: dict) -> None:
        text = "\t".join(self._cell_text(c, d) for c in self.columns)
        self.get_clipboard().set(text)

    def visible_rows(self) -> list[dict]:
        return [self.sorted.get_item(i).data for i in range(self.sorted.get_n_items())]

    def export_csv(self) -> None:
        import csv
        import io
        buf = io.StringIO()
        wr = csv.writer(buf)
        wr.writerow([c.title or c.key for c in self.columns])
        for d in self.visible_rows():
            wr.writerow([self._cell_text(c, d) for c in self.columns])
        data = buf.getvalue()
        dlg = Gtk.FileDialog(title="Export as CSV", initial_name=f"{self.export_name}.csv")

        def done(d, res) -> None:
            try:
                f = d.save_finish(res)
            except GLib.Error:
                return
            if f is not None:
                with open(f.get_path(), "w", encoding="utf-8", newline="") as fh:
                    fh.write(data)
        dlg.save(self.get_root(), None, done)

    def _activate(self, _view, pos: int) -> None:
        item = self.selection.get_item(pos)
        if item is not None and self.on_activate_cb:
            self.on_activate_cb(item.data)

    def _selected(self, *_a) -> None:
        if self.on_select_cb:
            self.on_select_cb(self.selected())


# ---------------------------------------------------------------- right-click menu

_ICON_WORDS = [  # first matching word decides the icon of a menu item that doesn't bring its own
    (("copy",), "edit-copy-symbolic"), (("export", "save"), "document-save-symbolic"), (("open", "show in", "reveal"), "document-open-symbolic"),
    (("folder",), "folder-open-symbolic"), (("details", "info", "properties", "what"), "dialog-information-symbolic"),
    (("log",), "text-x-generic-symbolic"), (("restart", "reload", "refresh", "again"), "view-refresh-symbolic"),
    (("look up", "browser", "website", "github"), "web-browser-symbolic"), (("terminal",), "utilities-terminal-symbolic"),
    (("edit", "rename", "change"), "document-edit-symbolic"), (("start", "run", "resume", "play"), "media-playback-start-symbolic"),
    (("pause", "suspend"), "media-playback-pause-symbolic"), (("stop", "end", "kill", "force", "quit"), "process-stop-symbolic"),
    (("never clean", "exclude", "hide", "ignore", "skip"), "view-conceal-symbolic"), (("allow", "firewall"), "security-medium-symbolic"),
    (("uninstall", "remove", "delete", "trash", "forget", "clear"), "user-trash-symbolic"), (("block", "mask", "disable", "off"), "action-unavailable-symbolic"),
    (("enable", "turn on", "on at"), "emblem-ok-symbolic"), (("permission",), "security-high-symbolic"), (("go to", "processes", "page"), "go-next-symbolic"),
    (("priority", "efficiency"), "power-profile-power-saver-symbolic"), (("update", "upgrade", "install"), "software-update-available-symbolic"),
]
_DANGER_WORDS = ("delete", "remove", "uninstall", "force", "kill", "trash", "forget", "block", "wipe", "erase")


def _has_word(text: str, words) -> bool:
    import re
    t = text.lower()
    return any(re.search(rf"(?<![a-z]){re.escape(w.strip())}(?![a-z])", t) for w in words)


def _auto_icon(text: str) -> str:
    for words, icon in _ICON_WORDS:
        if _has_word(text, words):
            return icon
    return "go-next-symbolic"


def context_menu(parent: Gtk.Widget, x: float, y: float, entries: list, arg=None) -> Gtk.Popover:
    """A right-click menu: entries are (label, callback(arg)[, icon[, "danger"]]) or None for a separator.

    Items get an icon from their wording when they don't bring one, and destructive ones (delete, force quit,
    uninstall…) are shown in red at the end, after a separator, so they're hard to hit by accident."""
    items = []
    for e in entries:
        if e is None:
            items.append(None)
            continue
        text, fn = e[0], e[1]
        icon = e[2] if len(e) > 2 and e[2] else _auto_icon(text)
        danger = (len(e) > 3 and e[3] == "danger") or _has_word(text, _DANGER_WORDS)
        items.append((text, fn, icon, danger))
    normal = [i for i in items if i is None or not i[3]]
    danger = [i for i in items if i is not None and i[3]]
    ordered = normal + ([None] + danger if danger else [])
    while ordered and ordered[0] is None:
        ordered.pop(0)
    while ordered and ordered[-1] is None:
        ordered.pop()
    ordered = [i for n, i in enumerate(ordered) if not (i is None and n and ordered[n - 1] is None)]

    pop = Gtk.Popover()
    pop.add_css_class("ctx")
    pop.set_parent(parent)
    rect = Gdk.Rectangle()
    rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
    pop.set_pointing_to(rect)
    pop.set_has_arrow(False)
    pop.set_position(Gtk.PositionType.BOTTOM)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
    for it in ordered:
        if it is None:
            sep = Gtk.Box()
            sep.add_css_class("ctx-sep")
            box.append(sep)
            continue
        text, fn, icon, is_danger = it
        img = Gtk.Image.new_from_icon_name(icon)
        lb = Gtk.Label(label=text, xalign=0)
        lb.set_hexpand(True)
        inner = Gtk.Box(spacing=12)
        inner.append(img)
        inner.append(lb)
        b = Gtk.Button()
        b.set_child(inner)
        b.add_css_class("flat")
        b.add_css_class("ctx-item")
        if is_danger:
            b.add_css_class("danger")
        b.connect("clicked", lambda _b, f=fn: (pop.popdown(), f(arg)))
        box.append(b)
    box.set_size_request(220, -1)
    pop.set_child(box)
    pop.connect("closed", lambda p: GLib.idle_add(lambda: (p.unparent(), False)[1]))
    pop.popup()
    return pop


def Gio_ListStore():  # noqa: N802 - tiny factory so imports stay local
    from gi.repository import Gio
    return Gio.ListStore(item_type=Row)

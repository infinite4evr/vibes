"""Page structure, part 2: table state, rows and columns.

Part of stack-highlights; code moved here unchanged from the original single file.
"""
import re
from .constants import CAPTION_RE, TABLE_CONTINUATION_GAP_FRACTION, TABLE_MAX_ROW_GAP
from .model import Item, Para
from .paragraphs import tokens_to_para


class TableState:
    def __init__(self):
        self.columns = []   # list of [x0, x1, name]
        self.header = False
        self.fill = {}      # column index -> last Para seen (fill-down)
        self.header_paras = []
        self.caption = None
        self.id = 0
        self.last_bottom = None
        self.last_page = None


def items_ended_with_row(items):
    return bool(items) and items[-1].type == "row"


def wraps_into_last_row(row, b):
    """A lone line directly under a cell of the previous row (no row gap) is
    that cell's text wrapping onto a new PDF block -- append it there."""
    st = row.table
    col = st.columns[column_for_x(st.columns, b["x0"])]
    bottom = getattr(row, "bottoms", {}).get(id(col))
    if bottom is None:
        return False
    line_h = b["_lines"][0][1].height or 10
    if 0 <= b["top"] - bottom <= line_h * TABLE_CONTINUATION_GAP_FRACTION:
        for c, p, filled in row.cells:
            if c is col and not filled:
                toks = [t for toks, _ in b["_lines"] for t in toks]
                extra = tokens_to_para(toks, p.page, st.cfg, kind="cell")
                p.extend(extra)
                p.finalize()
                row.bottoms[id(col)] = b["y1"]
                return True
    return False


def continues_table(st, b, pw, pno=None):
    """A lone block inside an active table is a row if it starts at a
    column edge and every piece of it starts at a column edge
    ("Chapter I – The Executive", "Chapter III – ... Suits 294 to 300")."""
    cols = st.columns
    if len(cols) < 2:
        return False
    # A table must remain spatially contiguous.  Previously a table detected
    # near the top of a page could stay "active" and swallow an ordinary prose
    # paragraph much farther down, scrambling its word order.
    if st.last_bottom is not None and pno is not None:
        if st.last_page == pno:
            if b["top"] - st.last_bottom > TABLE_MAX_ROW_GAP:
                return False
        elif st.last_page is not None and pno != st.last_page + 1:
            return False
    toks = [t for toks, _ in b["_lines"] for t in toks]
    first_line = " ".join(t.text for t in b["_lines"][0][0])
    if CAPTION_RE.match(first_line):
        return False  # "Table 6.5 ..." starts something new
    k = column_for_x(cols, b["x0"])
    if abs(cols[k][0] - b["x0"]) > 8:
        return False
    groups = {}
    for t in toks:
        groups.setdefault(column_for_x(cols, t.x0), []).append(t)
    for ci, g in groups.items():
        if abs(min(t.x0 for t in g) - cols[ci][0]) > 12:
            return False
    return k > 0 or len(groups) >= 2


def column_for_x(cols, x):
    k = 0
    for i, c in enumerate(cols):
        if x >= c[0] - 6:
            k = i
    return k


def relabel_columns(st):
    """Split the header cells' characters at the column positions -- the
    header may be stored as fewer, wider pieces than the data columns."""
    if not st.header_paras:
        return
    names = [[] for _ in st.columns]
    for hp in st.header_paras:
        for c, box in zip(hp.chars, hp.boxes):
            if box is None:
                for n in names:
                    if n and n[-1] != " ":
                        n.append(" ")
                continue
            names[column_for_x(st.columns, box.x0)].append(c)
        for n in names:
            if n and n[-1] != " ":
                n.append(" ")
    for col, n in zip(st.columns, names):
        col[2] = re.sub(r"\s+", " ", "".join(n)).strip() or None


def make_row(ctx, blocks, pno):
    cfg = ctx.cfg
    st = ctx.table
    if st is None:
        st = ctx.table = TableState()
        st.cfg = cfg
    # cells, split further at known column positions ("XIV-A Tribunals")
    specs = []
    for b in blocks:
        toks = [t for toks, _ in b["_lines"] for t in toks]
        if len(st.columns) >= 2:
            groups = {}
            for t in toks:
                groups.setdefault(column_for_x(st.columns, t.x0), []).append(t)
            if len(groups) > 1:
                for ci in sorted(groups):
                    g = groups[ci]
                    g[0].glue = False
                    specs.append((min(t.x0 for t in g), max(t.x1 for t in g), g))
                continue
        specs.append((b["x0"], b["x1"], toks))
    cells = []
    all_bold = True
    for x0, x1, toks in specs:
        para = tokens_to_para(toks, pno, cfg, kind="cell")
        para.x0 = x0
        cells.append((x0, x1, para))
        words = [t for t in toks if any(ch[0].isalpha() for ch in t.chars)]
        if not words or not all(t.bold for t in words):
            all_bold = False
    marked = any(p.has_marks() for _, _, p in cells)
    if all_bold and len(cells) >= 2 and (not marked or not st.header_paras):
        # a header row. If it lines up with the columns already known (the
        # same table continuing on a new page), keep them and just relabel.
        same = len(st.columns) >= len(cells) and all(
            any(abs(col[0] - x0) <= 8 for col in st.columns) for x0, _, _ in cells)
        if not same:
            st.columns = [[x0, x1, p.text] for x0, x1, p in cells]
            st.fill = {}
        st.header_paras = [p for _, _, p in cells]
        relabel_columns(st)
        if marked:  # you marked the header itself: keep it visible
            hp = Para(pno)
            for _, _, p in cells:
                hp.extend(p)
                hp.append_space()
                hp.chars[-1:] = [" "]
            hp.finalize()
            return [Item("para", pno, para=hp)]
        return []
    placed = []
    for x0, x1, p in cells:
        best, bestd = None, None
        for col in st.columns:
            d = abs(col[0] - x0)
            if bestd is None or d < bestd:
                best, bestd = col, d
        if best is None or bestd > cfg.column_tolerance:
            best = [x0, x1, None]
            st.columns.append(best)
            st.columns.sort(key=lambda c: c[0])
            relabel_columns(st)
        placed.append((best, p))
    first = st.columns[0]
    row = []
    for col in st.columns:
        hit = [p for c, p in placed if c is col]
        if hit:
            row.append((col, hit[0], False))
            if col is first:
                st.fill[0] = hit[0]
        elif col is first and 0 in st.fill and cfg.fill_down:
            row.append((col, st.fill[0], True))
    return [Item("row", pno, cells=row, table=st)]

"""Page structure, part 3: blocks, bands, side-by-side text and page items.

Part of stack-highlights; code moved here unchanged from the original single file.
"""
import re
from .backend import pymupdf
from .constants import (
    BOILERPLATE_RE, FOOTNOTE_START_RE, LIST_INDENT_SLOP, LIST_LINE_SHORT_FRACTION, LIST_RE,
    ROW_OVERLAP_FRACTION, SIDE_BY_SIDE_GAP_FRACTION, TABLE_ALIGN_SLOP, TABLE_MAX_ROW_GAP,
)
from .helpers import word_count
from .model import Item
from .tokens import line_tokens, RAW_FLAGS, snap_token_marks
from .paragraphs import tokens_to_para
from .headings import line_is_heading, split_runin
from .tables import continues_table, make_row, wraps_into_last_row


# ---------------------------------------------------------------------------
# Page structure: headings, paragraphs, list items, table rows
# ---------------------------------------------------------------------------
def _block_text(b):
    return " ".join(" ".join(t.text for t in toks) for toks, _ in b.get("_lines", []))


def _attach_subscript_blocks(blocks):
    """Attach small digit-only *subscript* lines to the neighbouring text line.

    Some PDFs store M₁ as a normal-size ``M`` on one text line and the small
    ``1`` as a completely separate line.  The old code classified every small
    digit as a footnote marker, so M₁..M₄ became just M.  Only lower-positioned
    digit lines are joined here; upper-positioned superscripts remain footnote
    candidates.  Plain digits are used in the reconstructed text (M1), which is
    semantically unambiguous and portable across Markdown/PDF fonts.
    """
    remove = set()
    for i, sb in enumerate(blocks):
        if len(sb.get("_lines", [])) != 1:
            continue
        stoks, sr = sb["_lines"][0]
        if not stoks or not all(t.sup for t in stoks):
            continue
        raw = "".join(t.text for t in stoks).strip()
        if not re.fullmatch(r"[0-9]{1,3}", raw):
            continue
        scy = (sr.y0 + sr.y1) / 2
        best = None
        best_score = None
        for j, hb in enumerate(blocks):
            if j == i:
                continue
            for li, (htoks, hr) in enumerate(hb.get("_lines", [])):
                if not htoks:
                    continue
                hcy = (hr.y0 + hr.y1) / 2
                # Subscripts sit lower than the host line centre but still
                # overlap it vertically.  Superscript footnote markers sit up.
                if scy <= hcy + 1.0 or sr.y0 >= hr.y1 + 3 or sr.y1 <= hr.y0:
                    continue
                prevs = [t for t in htoks if t.x1 <= sr.x0 + 2.5]
                if not prevs:
                    continue
                prev = max(prevs, key=lambda t: t.x1)
                gap = sr.x0 - prev.x1
                if gap > 3.5 or gap < -4.0 or not prev.text[-1:].isalnum():
                    continue
                score = abs(gap) + abs(scy - hcy) * 0.15
                if best_score is None or score < best_score:
                    best_score = score
                    best = (hb, li, htoks, prev)
        if best is None:
            continue
        hb, li, htoks, prev = best
        for t in stoks:
            t.sup = False
            t.line_start = False
            t.glue = True
        # Insert immediately after the host token rather than globally sorting
        # by x: a small glyph can overlap the right edge of the host character.
        k = max(k for k, t in enumerate(htoks) if t is prev) + 1
        htoks[k:k] = stoks
        remove.add(i)
    if remove:
        blocks[:] = [b for i, b in enumerate(blocks) if i not in remove]


def _looks_like_split_heading(real):
    """Two PDF blocks that are really ``7.5`` + ``LIQUIDITY RATIOS``.

    Treating this common section-title layout as a table row can keep a table
    state alive into the following prose and scramble the paragraph.
    """
    if len(real) != 2:
        return False
    left, right = sorted(real, key=lambda b: b["x0"])
    a = re.sub(r"\s+", " ", _block_text(left)).strip()
    b = re.sub(r"\s+", " ", _block_text(right)).strip()
    if not re.fullmatch(r"(?:\d+|[IVXLC]+)(?:\.[0-9A-ZIVXLC]+)*\.?", a, re.I):
        return False
    letters = [c for c in b if c.isalpha()]
    mostly_caps = bool(letters) and sum(c.isupper() for c in letters) / len(letters) >= 0.75
    return word_count(b) <= 14 and (mostly_caps or len(b) <= 80)


def _bands_align(a, b):
    """High-confidence evidence that two multi-block bands are table rows."""
    ra = [x for x in a if x.get("alnum")]
    rb = [x for x in b if x.get("alnum")]
    if len(ra) < 2 or len(rb) < 2:
        return False
    ax = [x["x0"] for x in ra]
    bx = [x["x0"] for x in rb]
    # One-to-one column matching: two nearby blocks in one band must not both
    # "match" the same x-position in the other band (that exact pattern occurs
    # when a section number + title follows a two-column prose block).
    used = set()
    matches = 0
    for x in ax:
        choices = [(abs(x - y), j) for j, y in enumerate(bx)
                   if j not in used and abs(x - y) <= TABLE_ALIGN_SLOP]
        if choices:
            _d, j = min(choices)
            used.add(j)
            matches += 1
    if matches < 2:
        return False
    # Rows of one table are near each other.  This prevents an outline near the
    # top of a page from turning an unrelated section heading below into a row.
    atop, abot = min(x["y0"] for x in ra), max(x["y1"] for x in ra)
    btop, bbot = min(x["y0"] for x in rb), max(x["y1"] for x in rb)
    gap = max(0.0, max(atop, btop) - min(abot, bbot))
    return gap <= TABLE_MAX_ROW_GAP


def page_items(ctx, page, pno, marks):
    cfg = ctx.cfg
    rd = page.get_text("rawdict", flags=RAW_FLAGS)
    pw = page.rect.width
    blocks = []
    edge_top = edge_bottom = False   # a page-numbered running head was dropped
    for b in rd["blocks"]:
        if b["type"] != 0:
            continue
        lines = []
        for l in b["lines"]:
            toks = line_tokens(l, marks, ctx)
            if not toks:
                continue
            txt = " ".join(t.text for t in toks)
            lr = pymupdf.Rect(l["bbox"])
            has_raw_mark = any(ch[1] >= 0 for t in toks for ch in t.chars)
            if BOILERPLATE_RE.match(txt.strip()) and not has_raw_mark:
                continue
            if ctx.is_running(page, lr, txt):
                # the head used to be an ordinary block that ended any table
                # running across the page break; keep that boundary
                if ctx.edge_hit == "top":
                    edge_top = True
                elif ctx.edge_hit == "bottom":
                    edge_bottom = True
                for t in toks:
                    for ch in t.chars:
                        if ch[1] >= 0:
                            ctx.stats["marks_in_running"] += 1
                continue
            for t in toks:
                for ch in t.chars:
                    if ch[1] >= 0:
                        ctx.marks[ch[1]].raw = True
                snap_token_marks(t, cfg.snap)
                for ch in t.chars:
                    if ch[1] >= 0:
                        pm = ctx.marks[ch[1]]
                        pm.text.append(ch[0])
                        for o in pm.co:
                            ctx.marks[o].text.append(ch[0])
            lines.append((toks, lr))
        for sub in split_side_by_side(lines):
            lines = sub
            x0 = min(r.x0 for _, r in lines)
            x1 = max(r.x1 for _, r in lines)
            y0 = min(r.y0 for _, r in lines)
            y1 = max(r.y1 for _, r in lines)
            has_alnum = any(ch[0].isalnum() for toks, _ in lines for t in toks for ch in t.chars)
            blocks.append({"_lines": lines, "x0": x0, "x1": x1, "y0": y0, "y1": y1,
                           "top": lines[0][1].y0, "alnum": has_alnum})

    # Repair detached small subscript digits before layout classification.
    _attach_subscript_blocks(blocks)

    # --- group blocks sharing a top edge into bands (table rows) ---------
    blocks.sort(key=lambda b: (round(b["top"]), b["x0"]))
    bands = []
    for b in blocks:
        placed = False
        for band in bands[-3:]:
            h = min(b["y1"] - b["y0"], band[0]["y1"] - band[0]["y0"]) or 1
            ov = min(b["y1"], band[0]["y1"]) - max(b["y0"], band[0]["y0"])
            if (abs(band[0]["top"] - b["top"]) <= cfg.row_tolerance or ov >= ROW_OVERLAP_FRACTION * h) and all(
                    b["x0"] >= o["x1"] - 1 or b["x1"] <= o["x0"] + 1 for o in band):
                band.append(b)
                placed = True
                break
        if not placed:
            bands.append([b])
    for band in bands:
        band.sort(key=lambda b: b["x0"])

    items = []
    if edge_top:
        ctx.table = None

    # A band is a table row only when another nearby band repeats at least two
    # column starts.  The previous "two blocks + one narrow block" rule was
    # intentionally permissive, but it could interpret ordinary prose / a
    # section number plus title as a table and then reorder the sentence.
    confident = set()
    if cfg.tables:
        for i in range(len(bands)):
            if i > 0 and _bands_align(bands[i - 1], bands[i]):
                confident.update((i - 1, i))
            if i + 1 < len(bands) and _bands_align(bands[i], bands[i + 1]):
                confident.update((i, i + 1))

    for bi, band in enumerate(bands):
        real = [b for b in band if b["alnum"]]
        split_heading = _looks_like_split_heading(real)
        is_row = cfg.tables and len(real) >= 2 and bi in confident and not split_heading
        if split_heading:
            ctx.table = None
        if cfg.tables and len(real) == 1 and ctx.table is not None:
            b = real[0]
            is_row = continues_table(ctx.table, b, pw, pno)
        if is_row:
            if len(real) == 1 and items and items[-1].type == "row" and wraps_into_last_row(items[-1], real[0]):
                if ctx.table is not None:
                    ctx.table.last_bottom = max(ctx.table.last_bottom or 0, real[0]["y1"])
                    ctx.table.last_page = pno
                continue
            new = make_row(ctx, real, pno)
            if ctx.table is not None:
                ctx.table.last_bottom = max(b["y1"] for b in real)
                ctx.table.last_page = pno
            for it in new:
                if it.type != "row":
                    continue
                it.bottoms = {id(col): max((bx.y1 for bx in p.boxes if bx is not None), default=None)
                              for col, p, filled in it.cells if not filled}
            items.extend(new)
            continue
        if not real:
            continue
        # Any ordinary block is a hard boundary for the conservative table
        # state.  Losing fancy row reconstruction is preferable to scrambling
        # a sentence and presenting it as authoritative study material.
        ctx.table = None
        for b in band:
            items.extend(text_block_items(ctx, b, pno))
    if edge_bottom:
        ctx.table = None
    return items


def split_side_by_side(lines):
    """PyMuPDF sometimes returns a whole table row (cells side by side) as
    one block. Re-split it into one group of lines per cell. A line that
    sits below existing text continues it; when several groups are above it
    (cells side by side), it goes to the one it overlaps most -- and if it
    overlaps several, they were one paragraph line PyMuPDF had split."""
    groups = []
    for toks, r in lines:
        # same line, ordinary word gap -> PyMuPDF split one line in two
        same = [g for g in groups if abs(g[-1][1].y0 - r.y0) < 2 and 0 <= r.x0 - g[-1][1].x1 < r.height * SIDE_BY_SIDE_GAP_FRACTION]
        if same:
            same[0].append((toks, r))
            continue
        above = [g for g in groups if r.y0 >= g[-1][1].y1 - 3]
        if not above:
            groups.append([(toks, r)])
            continue

        def overlap(g):
            gx0 = min(x.x0 for _, x in g)
            gx1 = max(x.x1 for _, x in g)
            return min(r.x1, gx1) - max(r.x0, gx0)

        if len(above) == 1:
            target = above[0]
        else:
            ov = [(overlap(g), g) for g in above]
            hits = [g for o, g in ov if o > 2]
            if len(hits) > 1:
                target = hits[0]
                for g in hits[1:]:
                    target.extend(g)
                    groups.remove(g)
                target.sort(key=lambda lr: (round(lr[1].y0 / 3), lr[1].x0))
            else:
                target = max(ov, key=lambda t: t[0])[1]
        target.append((toks, r))
    return groups


def text_block_items(ctx, b, pno):
    cfg = ctx.cfg
    items = []
    cur = []
    cur_x0 = None
    cont_x0 = None
    prev_lr = None
    block_x0 = min(r.x0 for _, r in b["_lines"])
    block_x1 = max(r.x1 for _, r in b["_lines"])

    def flush():
        nonlocal cur, cur_x0
        if cur:
            p = tokens_to_para(cur, pno, cfg)
            p.x0 = cur_x0 if cur_x0 is not None else p.x0
            classify_para(p, ctx)
            if p.chars:
                items.append(Item("para", pno, para=p))
        cur = []
        cur_x0 = None

    first = True
    lines = list(b["_lines"])
    li = 0
    while li < len(lines):
        toks, lr = lines[li]
        li += 1
        level = line_is_heading(toks, ctx) if cfg.headings else 0
        # a bold title that wraps and then runs into the text:
        # "3. Power to apply Act ... with another" / "establishment.—Where ..."
        if level == 3 and cfg.runin and li < len(lines):
            head2, body2 = split_runin(lines[li][0])
            if head2:
                toks = toks + head2
                lines[li] = (body2, lines[li][1])
                hp = tokens_to_para(toks, pno, cfg, kind="heading")
                htxt = hp.text.rstrip(" .—:")
                for a in (hp.chars, hp.marks, hp.boxes):
                    del a[len(htxt):]
                flush()
                items.append(Item("heading", pno, para=hp, level=4))
                continue
        if level:
            flush()
            hp = tokens_to_para(toks, pno, cfg, kind="heading")
            if items and items[-1].type == "heading" and items[-1].level == level and items[-1].page == pno \
                    and not items[-1].para.text.endswith((".", ":")):
                items[-1].para.extend(hp)   # heading wrapped onto a second line
                items[-1].para.finalize()
            elif hp.chars:
                items.append(Item("heading", pno, para=hp, level=level))
            first = False
            continue
        text = " ".join(t.text for t in toks)
        if cur and LIST_RE.match(text) and not toks[0].glue:
            flush()
        elif cur and prev_lr is not None and text[:1].isupper() and \
                prev_lr.x1 < block_x1 - (block_x1 - block_x0) * LIST_LINE_SHORT_FRACTION and \
                LIST_RE.match(" ".join(t.text for t in cur[:3])):
            # a list item whose line stops well short of the margin has ended
            # ("(iii) Lower growth but higher development" / "The above-given ...")
            flush()
        elif cur and cur_x0 is not None and cont_x0 is not None and lr.x0 < cur_x0 - LIST_INDENT_SLOP \
                and lr.x0 < cont_x0 - LIST_INDENT_SLOP and LIST_RE.match(" ".join(t.text for t in cur[:3])):
            # a line starting left of a list item's first line is not part of
            # that item ("2. This time ..." / "The major changes ... below:")
            flush()
        if not cur and cfg.headings and cfg.runin:
            head, body = split_runin(toks)
            if head:
                hp = tokens_to_para(head, pno, cfg, kind="heading")
                htxt = hp.text.rstrip(" .—:")
                cut = len(hp.text) - len(htxt)
                if cut:
                    for a in (hp.chars, hp.marks, hp.boxes):
                        del a[len(htxt):]
                items.append(Item("heading", pno, para=hp, level=4))
                toks = body
        if not cur:
            cur_x0 = lr.x0
            cont_x0 = None
        elif cont_x0 is None:
            cont_x0 = lr.x0
        toks[0].line_start = True
        cur.extend(toks)
        prev_lr = lr
        first = False
    flush()
    return items


def classify_para(p, ctx):
    text = p.text
    if p.fn is not None:
        p.kind = "footnote"
    elif p.size and p.size <= ctx.body_size * ctx.cfg.footnote_ratio and FOOTNOTE_START_RE.match(text):
        p.kind = "footnote"
        p.fn = FOOTNOTE_START_RE.match(text).group(1)
    elif LIST_RE.match(text):
        p.kind = "list"

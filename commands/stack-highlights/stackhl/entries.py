"""Build entries (snippets, grouped lists, headings) and final coverage.

Part of stack-highlights; code moved here unchanged from the original single file.
"""
import re
from .backend import pymupdf
from .constants import SECTION_RUNIN_RE, STATE_AMEND_RE
from .helpers import rect_dist, word_count
from .model import Entry
from .segmentation import snippet_ranges
from .rendering import leadin_text, md_escape, render_range


# ---------------------------------------------------------------------------
# Build entries
# ---------------------------------------------------------------------------
def build_entries(ctx, items):
    cfg = ctx.cfg
    fmt = cfg.fmt_render
    entries = []
    stack = []  # [(level, Para)]
    consumed_fn = set()

    def crumbs():
        out = []
        for lvl, hp in stack:
            if cfg.heading_depth and lvl > cfg.heading_depth:
                continue
            out.append((lvl, render_range(hp, 0, len(hp.chars), fmt, ctx), id(hp)))
        return out

    def find_footnote(start, n):
        for j in range(start + 1, min(len(items), start + 4000)):
            it = items[j]
            if it.type == "para" and it.para.kind == "footnote" and it.para.fn == n:
                return j
        return None

    last_group = None
    for idx, it in enumerate(items):
        if it.type == "heading":
            # State-amendment material is interleaved with the central Act.
            # A following unquoted numbered run-in ("12. Duties ...") is the
            # central section resuming, not a child of the state amendment.
            # Quoted amended section text does not become a run-in heading in
            # split_runin(), so this reset remains conservative.
            if SECTION_RUNIN_RE.match(it.para.text):
                cut = next((i for i, (_l, hp) in enumerate(stack)
                            if STATE_AMEND_RE.match(hp.text.strip())), None)
                if cut is not None:
                    stack = stack[:cut]
            stack = [(l, hp) for l, hp in stack if l < it.level]
            stack.append((it.level, it.para))
            last_group = None
            if it.para.has_marks():
                if cfg.heading_depth and it.level > cfg.heading_depth:
                    # Too deep to render as a heading: keep its highlighted
                    # text as an ordinary snippet so the highlight isn't lost.
                    e = Entry("snippet", crumbs(), it.page)
                    for (s, en, h, t) in snippet_ranges(it.para, cfg):
                        e.lines.append(render_range(it.para, s, en, fmt, ctx, h, t))
                        bb = mark_bbox(it.para, s, en)
                        e.bbox = bb if e.bbox is None else (e.bbox | bb if bb else e.bbox)
                    if not e.lines:
                        e.lines.append(render_range(it.para, 0, len(it.para.chars), fmt, ctx))
                    e.mark_ids = {m for m in it.para.marks if m >= 0}
                    for m in e.mark_ids:
                        ctx.marks[m].used = True
                    entries.append(e)
                else:
                    e = Entry("heading", crumbs(), it.page)
                    e.mark_ids = {m for m in it.para.marks if m >= 0}
                    for m in e.mark_ids:
                        ctx.marks[m].used = True
                    e.bbox = mark_bbox(it.para, 0, len(it.para.chars))
                    entries.append(e)
            continue
        if it.type == "row":
            if not any(p.has_marks() for _, p, filled in it.cells if not filled):
                continue
            e = Entry("row", crumbs(), it.page)
            parts = []
            for col, p, filled in it.cells:
                name = col[2]
                if filled:
                    val = render_range(p, 0, len(p.chars), fmt, ctx) if not p.has_marks() else \
                        md_escape(p.text) if fmt == "md" else p.text
                elif p.has_marks() and word_count(p.text) > cfg.cell_words:
                    rngs = snippet_ranges(p, cfg)
                    val = " ".join(render_range(p, s, en, fmt, ctx, h, t) for s, en, h, t in rngs)
                    e.mark_ids |= {m for m in p.marks if m >= 0}
                elif word_count(p.text) > cfg.cell_words:
                    words = p.text.split()
                    val = (md_escape(" ".join(words[:cfg.cell_words])) if fmt == "md" else " ".join(words[:cfg.cell_words])) + " …"
                else:
                    val = render_range(p, 0, len(p.chars), fmt, ctx)
                    e.mark_ids |= {m for m in p.marks if m >= 0}
                name_s = re.sub(r"\s+", " ", name).strip() if (name and cfg.table_style == "kv") else ""
                parts.append(f"{md_escape(name_s) if fmt == 'md' else name_s}: {val}" if name_s else val)
                bb = mark_bbox(p, 0, len(p.chars))
                if bb is not None:
                    e.bbox = bb if e.bbox is None else e.bbox | bb
            e.lines.append(" · ".join(x for x in parts if x))
            entries.append(e)
            last_group = None
            continue
        p = it.para
        if p.kind == "footnote":
            if idx in consumed_fn or not p.has_marks():
                continue
            chap = [(l, hp) for l, hp in stack if l <= 1]
            saved = stack
            stack = chap
            base = crumbs()
            stack = saved
            fn_crumbs = [] if cfg.plain_titles else base + [(2, "Footnotes", "fn")]
            e = Entry("snippet", fn_crumbs, it.page)
            for k, (s, en, h, t) in enumerate(snippet_ranges(p, cfg)):
                e.lines.append((f"fn {p.fn}: " if p.fn and k == 0 else "") + render_range(p, s, en, fmt, ctx, h, t))
                bb = mark_bbox(p, s, en)
                e.bbox = bb if e.bbox is None else (e.bbox | bb if bb else e.bbox)
            e.mark_ids = {m for m in p.marks if m >= 0}
            entries.append(e)
            continue
        if not p.has_marks():
            continue
        rngs = snippet_ranges(p, cfg)
        if len(rngs) > 1 and cfg.context != "highlight":
            s0, en0 = rngs[0][0], rngs[-1][1]
            pieces = [render_range(p, a, b, fmt, ctx, h if k == 0 else False, t if k == len(rngs) - 1 else False)
                      for k, (a, b, h, t) in enumerate(rngs)]
            joined = pieces[0]
            for (a, b, h, t), (pa, pb, ph, pt), piece in zip(rngs[1:], rngs[:-1], pieces[1:]):
                gap = p.text[pb:a].strip()
                joined += (" … " if gap else " ") + piece
            rngs = [(s0, en0, rngs[0][2], rngs[-1][3], joined)]
        for rg in rngs:
            s, en, h, t = rg[:4]
            body = rg[4] if len(rg) > 4 else render_range(p, s, en, fmt, ctx, h, t)
            ids = {m for m in p.marks[s:en] if m >= 0}
            bb = mark_bbox(p, s, en)
            if p.kind == "list" and p.leadin is not None:
                key = id(p.leadin)
                if last_group is not None and cfg.group_lists and (
                        key in last_group.keys or getattr(last_group, "last_src", None) is p.leadin):
                    last_group.keys.add(key)
                    last_group.lines.append(body)
                    last_group.last_src = p
                    last_group.mark_ids |= ids
                    if bb is not None:
                        last_group.bbox = bb if last_group.bbox is None else last_group.bbox | bb
                    e = last_group
                else:
                    ls, le, lh = leadin_text(p.leadin, cfg)
                    all_leadin_ids = {m for m in p.leadin.marks if m >= 0}
                    shown_leadin_ids = {m for m in p.leadin.marks[ls:le] if m >= 0}
                    # Only replace the lead-in's standalone highlighted snippet
                    # when every one of its marks is present in the lead-in text
                    # we are about to emit.  Otherwise keep the standalone
                    # snippet too: a little duplication is far safer than a
                    # silently missing highlighted sentence.
                    if entries and getattr(entries[-1], "src", None) is p.leadin and not entries[-1].subs \
                            and all_leadin_ids <= shown_leadin_ids:
                        entries.pop()
                    e = Entry("snippet", crumbs(), it.page)
                    e.lines.append(render_range(p.leadin, ls, le, fmt, ctx, lh, False))
                    e.lines.append(body)
                    e.leadin_key = key
                    e.keys = {key}
                    e.last_src = p
                    e.mark_ids |= ids | shown_leadin_ids
                    e.bbox = bb
                    entries.append(e)
                    last_group = e
            else:
                e = Entry("snippet", crumbs(), it.page)
                e.lines.append(body)
                e.mark_ids = ids
                e.bbox = bb
                e.src = p
                entries.append(e)
                last_group = None
            # footnotes cited inside this snippet
            if cfg.footnotes == "inline":
                for pos, n in p.refs:
                    if s <= pos <= en:
                        j = find_footnote(idx, n)
                        if j is not None and j not in consumed_fn and items[j].para.has_marks():
                            fp = items[j].para
                            consumed_fn.add(j)
                            for fs, fe, fh, ft in snippet_ranges(fp, cfg):
                                e.subs.append((f"fn {n}", render_range(fp, fs, fe, fmt, ctx, fh, ft)))
                            e.mark_ids |= {m for m in fp.marks if m >= 0}
            e.page_label = ctx.label(it.page)
    # highlight comments and free-text notes -> nearest entry
    if cfg.notes:
        for m in ctx.marks:
            if m.comment:
                target = next((e for e in entries if m.id in e.mark_ids), None)
                if target:
                    target.subs.append(("Note", md_escape(m.comment) if fmt == "md" else m.comment))
        for pno, rect, content in ctx.notes:
            cands = [e for e in entries if e.page == pno and e.bbox is not None]
            txt = md_escape(content) if fmt == "md" else content
            if cands:
                best = min(cands, key=lambda e: rect_dist(rect, e.bbox))
                best.subs.append(("Note", txt))
            else:
                e = Entry("note", [], pno)
                e.lines.append(f"Note (p. {ctx.label(pno)}): {txt}")
                entries.append(e)
    for e in entries:
        if not hasattr(e, "page_label"):
            e.page_label = ctx.label(e.page)
    return entries


def finalize_coverage(entries, ctx):
    """Recompute coverage from entries that actually survived build_entries.

    render_range() is also used while constructing temporary entries.  An
    earlier version therefore counted a mark as placed even when that entry was
    later removed (notably list lead-ins), yielding a misleading 100% report.
    Entry.mark_ids is now the source of truth for final-output coverage.
    """
    for m in ctx.marks:
        m.used = False
    for e in entries:
        for mid in e.mark_ids:
            if 0 <= mid < len(ctx.marks):
                ctx.marks[mid].used = True


def mark_bbox(p, s, e):
    bb = None
    for k in range(s, e):
        if p.marks[k] >= 0 and p.boxes[k] is not None:
            bb = pymupdf.Rect(p.boxes[k]) if bb is None else bb | p.boxes[k]
    return bb

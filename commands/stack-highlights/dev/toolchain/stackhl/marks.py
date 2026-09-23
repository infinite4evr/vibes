"""Annotations -> marks.

Part of stack-highlights; code moved here unchanged from the original single file.
"""
from .backend import pymupdf
from .constants import (
    ANNOT_KINDS, HILITE_MAX_HEIGHT, HILITE_MIN_BRIGHTNESS, HILITE_MIN_HEIGHT,
    HILITE_MIN_SATURATION, NOTE_TYPES,
)
from .helpers import color_name
from .model import Mark


# ---------------------------------------------------------------------------
# Annotations -> marks
# ---------------------------------------------------------------------------
def collect_marks(ctx, page, pno, use_fills):
    cfg = ctx.cfg
    marks = []
    if not use_fills:
        for a in page.annots() or []:
            t = a.type[0]
            if t in NOTE_TYPES:
                content = (a.info.get("content") or "").strip()
                if content and cfg.notes:
                    ctx.notes.append((pno, a.rect, content))
                continue
            kind = ANNOT_KINDS.get(t)
            if kind is None or kind not in cfg.kinds:
                continue
            col = a.colors.get("stroke") or a.colors.get("fill")
            cname = color_name(col)
            if cfg.colors and cname not in cfg.colors:
                continue
            v = a.vertices
            if v:
                rects = [pymupdf.Quad(v[i:i + 4]).rect for i in range(0, len(v) - 3, 4)]
            else:
                rects = [a.rect]
            comment = (a.info.get("content") or "").strip() if cfg.notes else ""
            m = Mark(len(ctx.marks), pno, kind, cname, rects, comment)
            ctx.marks.append(m)
            marks.append(m)
    else:
        for d in page.get_drawings():
            if d.get("type") != "f" or not d.get("fill"):
                continue
            fill = d["fill"]
            for it in d.get("items") or []:
                if it[0] != "re":
                    continue
                r = pymupdf.Rect(it[1])
                if looks_like_highlighter(fill, r):
                    cname = color_name(fill)
                    if cfg.colors and cname not in cfg.colors:
                        continue
                    m = Mark(len(ctx.marks), pno, "highlight", cname, [r], "")
                    ctx.marks.append(m)
                    marks.append(m)
    return marks


def looks_like_highlighter(fill, r):
    if not fill or len(fill) != 3:
        return False
    mx, mn = max(fill), min(fill)
    sat = 0 if mx == 0 else (mx - mn) / mx
    return (mx >= HILITE_MIN_BRIGHTNESS and sat >= HILITE_MIN_SATURATION
            and HILITE_MIN_HEIGHT <= r.height <= HILITE_MAX_HEIGHT)


def doc_has_annotation_marks(doc, pages):
    for p in pages:
        for a in doc[p].annots() or []:
            if a.type[0] in ANNOT_KINDS:
                return True
    return False

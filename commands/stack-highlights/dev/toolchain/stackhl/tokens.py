"""Page -> lines of tokens (character level, with marks).

Part of stack-highlights; code moved here unchanged from the original single file.
"""
from collections import Counter
from .backend import pymupdf
from .constants import DASHES, MARK_HIT_SLOP
from .model import Token


# ---------------------------------------------------------------------------
# Page -> lines of tokens (character level, with marks)
# ---------------------------------------------------------------------------
RAW_FLAGS = pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_PRESERVE_LIGATURES


def char_mark(cx, cy, marks):
    """Primary mark covering the point, plus any others that also cover it
    (the same words underlined twice, a highlight inside an underlined
    row ...). Only the primary one is shown; all of them count as placed."""
    hit = []
    for m in marks:
        for r in m.rects:
            if r.x0 - MARK_HIT_SLOP <= cx <= r.x1 + MARK_HIT_SLOP and r.y0 <= cy <= r.y1:
                hit.append(m)
                break
    if not hit:
        return -1
    for other in hit[1:]:
        hit[0].co.add(other.id)
    return hit[0].id


def line_tokens(line, marks, ctx):
    body = ctx.body_size
    toks = []
    cur = None
    space_pending = True
    for s in line["spans"]:
        size = s["size"]
        bold = bool(s["flags"] & 16) or "bold" in s["font"].lower()
        sup = bool(s["flags"] & 1) or size <= body * ctx.cfg.sup_ratio
        for ch in s["chars"]:
            c = ch["c"]
            if not c or c.isspace():
                cur = None
                space_pending = True
                continue
            if c in "\ufb01\ufb02\ufb00\ufb03\ufb04":
                c = {"\ufb01": "fi", "\ufb02": "fl", "\ufb00": "ff", "\ufb03": "ffi", "\ufb04": "ffl"}[c]
            box = pymupdf.Rect(ch["bbox"])
            if cur is None or cur.sup != sup:
                cur = Token()
                cur.size, cur.sup, cur.bold = size, sup, True
                cur.glue = bool(toks) and not space_pending
                cur.x0, cur.y0, cur.x1, cur.y1 = box.x0, box.y0, box.x1, box.y1
                toks.append(cur)
            space_pending = False
            mid = char_mark((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2, marks) if marks else -1
            cur.chars.append((c, mid, box, bold))
            cur.x1, cur.y1 = max(cur.x1, box.x1), max(cur.y1, box.y1)
            cur.y0 = min(cur.y0, box.y0)
            if c in DASHES and len(cur.chars) > 1:
                cur = None  # "operation].—A" -> split after the dash
    for t in toks:
        t.bold = all(ch[3] for ch in t.chars if ch[0].isalnum()) and any(ch[0].isalnum() for ch in t.chars)
    if toks:
        toks[0].line_start = True
    return toks


def snap_token_marks(tok, mode):
    """--snap word: a word counts as marked when more than half of its
    letters/digits are covered (so a highlight that clips one letter of the
    next word doesn't drag it in, and one that misses the last letter doesn't
    lose the word). --snap char keeps the exact characters."""
    if mode == "char":
        return
    alnum = [ch for ch in tok.chars if ch[0].isalnum()] or tok.chars
    marked = [ch[1] for ch in alnum if ch[1] >= 0]
    digits = [ch for ch in alnum if ch[0].isdigit()]
    all_digits = bool(digits) and all(ch[1] >= 0 for ch in digits)   # "42" of "42nd"
    if len(marked) * 2 > len(alnum) or (all_digits and marked):
        mid = Counter(marked).most_common(1)[0][0]
        tok.chars = [(c, mid, b, bo) for c, _, b, bo in tok.chars]
    else:
        tok.chars = [(c, -1, b, bo) for c, _, b, bo in tok.chars]

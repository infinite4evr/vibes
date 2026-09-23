"""Tokens -> Para (footnote markers, amendment brackets, hyphenation).

Part of stack-highlights; code moved here unchanged from the original single file.
"""
from .constants import FN_MARK_RE
from .model import Para


# ---------------------------------------------------------------------------
# Tokens -> Para (footnote markers, amendment brackets, hyphenation)
# ---------------------------------------------------------------------------
def tokens_to_para(tokens, pno, cfg, kind="para"):
    p = Para(pno)
    p.kind = kind
    amend_open = []  # char positions of "[" that belong to an amendment marker
    drop_bracket = False
    sizes = []
    first_content = True
    for i, t in enumerate(tokens):
        txt = t.text
        if t.sup and FN_MARK_RE.match(txt):
            nxt = tokens[i + 1] if i + 1 < len(tokens) else None
            if nxt is not None and nxt.glue and nxt.text.startswith("["):
                drop_bracket = not cfg.keep_markers  # "4[(1) ..." amendment marker
                if not cfg.keep_markers:
                    if not t.glue and nxt.glue:
                        nxt.glue = False
                    continue
            elif first_content and p.fn is None and nxt is not None and \
                    (nxt.text[:1].isalpha() or nxt.text[:1] in "“‘\"'"):
                p.fn = txt              # "7Westminster is a place ..." footnote body
                if not cfg.keep_markers:
                    if nxt is not None:
                        nxt.glue = False
                    continue
            else:
                p.refs.append((len(p.chars), txt))
                if not cfg.keep_markers:
                    if nxt is not None and not t.glue and nxt.glue:
                        nxt.glue = False
                    continue
        if p.chars:
            prev_last = p.chars[-1]
            hyphen_join = (t.line_start and prev_last == "-" and len(p.chars) > 1
                           and p.chars[-2].isalpha() and txt[:1].isalpha())
            if hyphen_join:
                # word broken at a line-end hyphen: always glue ("Travancore-Cochin");
                # --dehyphenate drops the hyphen only before a lowercase letter
                # ("co-operation" -> "cooperation"), never in a Capital-Capital compound
                if cfg.dehyphenate and txt[:1].islower():
                    for a in (p.chars, p.marks, p.boxes):
                        a.pop()
            elif not t.glue:
                p.append_space()
        first_content = False
        for j, (c, mid, box, _) in enumerate(t.chars):
            if j == 0 and drop_bracket and c == "[":
                amend_open.append(len(p.chars))
            p.chars.append(c)
            p.marks.append(mid)
            p.boxes.append(box)
        drop_bracket = False
        sizes.append(t.size)
        if t.sup and not FN_MARK_RE.match(txt):
            pass
    p.amend = set(amend_open)
    p.size = sorted(sizes)[len(sizes) // 2] if sizes else 0
    p.x0 = tokens[0].x0 if tokens else 0
    p.finalize()
    return p


def strip_amendments(items, cfg):
    """Remove the brackets of amendment markers ("⁴[(1) This Act ... ]"),
    pairing them across paragraphs: an amendment often opens in a section
    title and closes several paragraphs later."""
    if cfg.keep_markers:
        return
    carry = 0
    for it in items:
        if it.type == "heading" and it.level <= 2:
            carry = 0
        paras = [it.para] if it.para is not None else [p for _, p, filled in (it.cells or []) if not filled]
        for p in paras:
            carry = _strip_para(p, carry)
        carry = min(carry, 6)


def _strip_para(p, carry):
    keep = [True] * len(p.chars)
    near = [False] * len(p.chars)
    stack = ["A"] * carry
    for i, c in enumerate(p.chars):
        if c == "[":
            if i in p.amend:
                stack.append("A")
                keep[i] = False
            else:
                stack.append("N")
        elif c == "]" and stack:
            if stack.pop() == "A":
                keep[i] = False
        if not keep[i]:
            for k in (i - 1, i + 1):
                if 0 <= k < len(near):
                    near[k] = True
    carry = stack.count("A")
    if all(keep):
        return carry
    chars, marks, boxes, nr = [], [], [], []
    remap = {}
    for i, k in enumerate(keep):
        if not k:
            continue
        # " ," left behind by "funds [,pension" -> "funds,"
        if p.chars[i] in ",;" and chars and chars[-1] == " " and (near[i] or (nr and nr[-1])):
            chars.pop(); marks.pop(); boxes.pop(); nr.pop()
        remap[i] = len(chars)
        chars.append(p.chars[i]); marks.append(p.marks[i]); boxes.append(p.boxes[i]); nr.append(near[i])
        # ",pension" -> ", pension"
        if p.chars[i] in ",;" and i + 1 < len(p.chars) and near[i]:
            j = i + 1
            while j < len(p.chars) and not keep[j]:
                j += 1
            if j < len(p.chars) and p.chars[j].isalpha():
                chars.append(" "); marks.append(-1); boxes.append(None); nr.append(False)
    p.chars, p.marks, p.boxes = chars, marks, boxes
    p.refs = [(remap.get(pos, len(chars)), n) for pos, n in p.refs]
    p.amend = set()
    p.finalize()
    return carry

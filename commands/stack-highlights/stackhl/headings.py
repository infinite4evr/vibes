"""Page structure, part 1: heading lines and run-in headings.

Part of stack-highlights; code moved here unchanged from the original single file.
"""
import re
from .constants import (
    ALLCAPS_HEADING_FRACTION, ALLCAPS_MIN_LETTERS, CAPTION_RE, FN_MARK_RE,
    STRUCTURAL_HEADING_RE,
)


def line_is_heading(toks, ctx):
    words = [t for t in toks if any(ch[0].isalnum() for ch in t.chars) and not (t.sup and FN_MARK_RE.match(t.text))]
    if not words:
        return 0
    text = " ".join(t.text for t in words)
    size = max(t.size for t in words)
    body = ctx.body_size
    all_bold = all(t.bold for t in words)
    # Legal / reference PDFs frequently typeset CHAPTER II or PART IVA in the
    # same font as body text.  Treat the explicit structural label as a real
    # heading even without bold/large-font evidence so it resets stale state
    # (for example a preceding STATE AMENDMENT block).
    if STRUCTURAL_HEADING_RE.match(text) and len(words) <= 8:
        return 1
    if text.rstrip().endswith(":") or text.rstrip().endswith(":—"):
        return 0  # a bold lead-in line ("The features ... are:") is not a heading
    if size >= body * 1.6:
        return 1
    if size >= body * 1.2 and len(words) <= 20:
        return 2
    if CAPTION_RE.match(text) and len(words) <= 25:
        return 3
    if all_bold and len(words) <= ctx.cfg.heading_max_words:
        letters = [c for c in text if c.isalpha()]
        if letters and sum(c.isupper() for c in letters) / len(letters) > ALLCAPS_HEADING_FRACTION and len(letters) > ALLCAPS_MIN_LETTERS:
            return 2
        return 3
    return 0


def split_runin(toks):
    """Bold words at the very start of a paragraph followed by normal text
    ("Maharashtra and Gujarat In 1960, ...", "1. Short title, extent and
    application.—(1) This Act ...") -> (heading tokens, body tokens)."""
    n = 0
    for t in toks:
        if t.sup and FN_MARK_RE.match(t.text):
            if all(x.sup for x in toks[:n]):
                n += 1       # "¹[5A. Central Board.—" : marker before the title
                continue
            break
        if t.bold:
            n += 1
        elif not any(ch[0].isalnum() for ch in t.chars) and n:
            n += 1  # punctuation between bold words
        else:
            break
    while n and not toks[n - 1].bold:
        n -= 1
    if n and all(t.sup for t in toks[:n]):
        return None, toks
    if n == 0 or n >= len(toks):
        return None, toks
    head = toks[:n]
    htxt = " ".join(t.text for t in head).strip()
    # A bold possessive opening word is commonly an attribution inside a
    # sentence ("Kohler’s dictionary ..."), not a run-in heading.  Promoting
    # it to the heading stack can attach a later highlight to the wrong label.
    if len(head) == 1 and re.search(r"(?:['’]s|s['’])$", htxt, re.I):
        return None, toks
    if htxt.endswith(":") or len(head) > 14 or sum(ch[0].isalpha() for t in head for ch in t.chars) < 3:
        return None, toks
    rest = toks[n:]
    # drop the ".—" / ":—" / "—" joining heading and text
    while rest and all(not ch[0].isalnum() and ch[0] not in "([“‘\"'" for ch in rest[0].chars):
        rest = rest[1:]
    if not rest:
        return None, toks
    rest[0].glue = False
    return head, rest

"""Document-level passes (page joins, footnotes, table headers, lead-ins).

Part of stack-highlights; code moved here unchanged from the original single file.
"""
import re
from .constants import CAPTION_RE, HEADING_STACK_X_SLOP, LIST_RE, SMALL_STYLE_SIZE_DELTA
from .tables import column_for_x, relabel_columns


# ---------------------------------------------------------------------------
# Document-level passes
# ---------------------------------------------------------------------------
TERMINAL = ".!?:;"
DANGLING = {"the", "a", "an", "of", "to", "with", "and", "or", "in", "for", "by", "on", "at",
            "from", "as", "that", "which", "is", "are", "was", "were", "its", "their", "into",
            "under", "between", "than", "whose", "who", "has", "have", "been", "be", "this", "these"}


def join_continuations(items, cfg):
    """A paragraph cut by a page break ("... not a sovereign body" |
    "like the British Parliament.") is joined back into one."""
    if not cfg.join_pages:
        return items
    out = []
    for it in items:
        first = it.para.text.lstrip("‘“\"'([") if it.type == "para" else ""
        prev_open = False
        if out and out[-1].type == "para" and out[-1].para.kind in ("para", "list"):
            # previous text stops on a word no sentence ends with ("... in
            # consultation with the" | "RBI, decided ...") -> it continues
            last_word = (out[-1].para.text.split() or [""])[-1].lower()
            prev_open = last_word in DANGLING
        if it.type == "para" and it.para.kind in ("para", "list") and (first[:1].islower() or
                (prev_open and first[:1].isalnum() and not LIST_RE.match(it.para.text))):
            j = len(out) - 1
            while j >= 0 and out[j].type == "para" and out[j].para.kind == "footnote":
                j -= 1
            if j >= 0 and out[j].type == "para" and out[j].para.kind in ("para", "list") \
                    and out[j].para.text.rstrip()[-1:] not in TERMINAL \
                    and (out[j].page != it.page or it.para.kind == "para"):
                out[j].para.extend(it.para)
                out[j].para.finalize()
                continue
        out.append(it)
    return out


def merge_footnote_continuations(items):
    """A footnote can run over several paragraphs or contain a list
    (footnote 12: Referendum / Initiative / Recall / Plebiscite). Paragraphs
    after a footnote that don't start a new footnote belong to it -- until
    the next heading, or, for small-print page-bottom footnotes, until the
    text is no longer small."""
    out = []
    cur = None
    for it in items:
        if it.type == "heading" or it.type == "row":
            cur = None
            out.append(it)
            continue
        p = it.para
        if p.kind == "footnote":
            cur = p
            out.append(it)
            continue
        if cur is not None:
            small_style = cur.size and cur.size < p.size - SMALL_STYLE_SIZE_DELTA
            same_run = it.page in (cur.page, cur.page + 1) and not small_style
            if same_run:
                cur.chars.append(" ")
                cur.marks.append(-1)
                cur.boxes.append(None)
                cur.extend(p)
                cur.finalize()
                continue
            cur = None
        out.append(it)
    return out


def attach_table_headers(items):
    """A bold line right above a table's rows ("Parts Subject Matter
    Articles Covered") is its header row even when the PDF stores it as one
    line: split it at the rows' column positions and use it for the names."""
    out = []
    for i, it in enumerate(items):
        nxt = items[i + 1] if i + 1 < len(items) else None
        if it.type == "heading" and it.level in (2, 3) and nxt is not None and nxt.type == "row" \
                and nxt.page == it.page and len(nxt.table.columns) >= 2 and not it.para.has_marks() \
                and not CAPTION_RE.match(it.para.text):
            st = nxt.table
            xs = {column_for_x(st.columns, b.x0) for b in it.para.boxes if b is not None}
            if len(xs) >= 2:
                st.header_paras = [it.para]
                relabel_columns(st)
                continue
        out.append(it)
    return out


def demote_titles(items):
    """--plain-titles: stop treating headings specially. Every heading becomes
    an ordinary paragraph, so a highlighted heading turns into a normal snippet
    and an un-highlighted one is dropped (no big-font clutter, no breadcrumbs)."""
    for it in items:
        if it.type == "heading":
            it.type = "para"
            it.para.kind = "para"


def assign_leadins(items, cfg):
    stack = []  # (x0, para) of paragraphs ending in ':' / '—'
    for it in items:
        if it.type == "heading":
            stack = []
            continue
        if it.type != "para":
            continue
        p = it.para
        if not any(c.isalnum() for c in p.chars):
            continue  # "* * * * *" (omitted text) doesn't end a list
        tail = p.text.rstrip().lower()
        ends_intro = tail.endswith((":", "—", ":—", ":-")) or bool(re.search(r"\b(viz|namely|as follows|following)[,.:]?$", tail))
        if p.kind == "list":
            while stack and stack[-1][0] >= p.x0 - HEADING_STACK_X_SLOP:
                stack.pop()
            if stack and cfg.leadins:
                p.leadin = stack[-1][1]
            if ends_intro:
                stack.append((p.x0, p))
        elif p.kind == "para":
            stack = [(p.x0, p)] if ends_intro else []

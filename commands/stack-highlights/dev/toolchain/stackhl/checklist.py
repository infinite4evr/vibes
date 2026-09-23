"""'Check in book' list: highlights that could not be placed in the notes.

The list uses exactly the same rules as the coverage line printed at the end
of every run (see coverage_report() in driver.py), so the two always agree:

    placed = all marks - no-text marks - part-word marks - unplaced marks

It is appended to the end of the notes (Markdown and text) and added to JSON
as "check_in_book". When every highlight was placed, nothing is added and the
output is byte-for-byte what it was before this list existed.

The list is deliberately plain text (no bold): in the notes, bold means
"you highlighted this", and nothing here is a highlight.
"""
from .rendering import md_escape

MESSAGES = {
    "part_word": ("covers less than half of a word, so it was left out by the default --snap word. "
                  "Rerun with --snap char to keep it."),
    "no_text": "has no text under it (an image, figure or scanned area). Read it in the book.",
    "not_placed": "could not be placed in the notes.",
}
SNIPPET_CHARS = 80


def unplaced_marks(ctx):
    """[(mark, reason)] in page order, for every mark the coverage line does not count as placed.

    Must run after process_pdf(): coverage_report() there finalises mark.used."""
    out = []
    for m in ctx.marks:
        text = "".join(m.text).strip()
        if m.raw and not text:
            out.append((m, "part_word"))
        elif not m.raw and not text:
            out.append((m, "no_text"))
        elif not m.used:
            out.append((m, "not_placed"))
    return out


def _where(ctx, m):
    printed = ctx.label(m.page)
    where = f"p. {m.page + 1}"
    if printed != str(m.page + 1):
        where += f" (printed page {printed})"
    return where


def _snippet(m):
    text = " ".join("".join(m.text).split())
    return text if len(text) <= SNIPPET_CHARS else text[:SNIPPET_CHARS - 1].rstrip() + "…"


def _line(ctx, m, reason, fmt):
    what = ("An " if m.kind[:1] in "aeiou" else "A ") + m.kind
    text = _snippet(m)
    if text:
        what += " on “" + (md_escape(text) if fmt == "md" else text) + "”"
    line = f"{_where(ctx, m)}: {what} {MESSAGES[reason]}"
    comment = " ".join((m.comment or "").split())
    if comment:
        line += " Your note there: “" + (md_escape(comment) if fmt == "md" else comment) + "”."
    return line


INTRO = "These highlights are not in the notes above. Look them up in the PDF:"


def check_in_book_md(ctx, level_shift=0):
    """Markdown section to append to the notes, or "" when every mark was placed."""
    items = unplaced_marks(ctx)
    if not items:
        return ""
    n = min(6, max(1, 1 + level_shift))
    out = ["", "#" * n + " Check in book", "", INTRO, ""]
    out += ["- " + _line(ctx, m, r, "md") for m, r in items]
    return "\n".join(out) + "\n"


def check_in_book_text(ctx):
    """Plain-text section to append to the notes, or "" when every mark was placed."""
    items = unplaced_marks(ctx)
    if not items:
        return ""
    out = ["", "=== Check in book ===", "", INTRO]
    out += [_line(ctx, m, r, "txt") for m, r in items]
    return "\n".join(out) + "\n"


def check_in_book_json(ctx):
    """List for the JSON output (empty when every mark was placed)."""
    return [
        {
            "page": m.page + 1,
            "page_label": ctx.label(m.page),
            "reason": reason,
            "kind": m.kind,
            "color": m.color,
            "text": "".join(m.text).strip(),
            "comment": m.comment or "",
            "message": _line(ctx, m, reason, "txt"),
        }
        for m, reason in unplaced_marks(ctx)
    ]

"""Driver: process one PDF, coverage report, folder scanning.

Part of stack-highlights; code moved here unchanged from the original single file.
"""
import sys
from .backend import pymupdf
from .helpers import parse_pages
from .context import DocContext
from .marks import collect_marks, doc_has_annotation_marks
from .paragraphs import strip_amendments
from .layout import page_items
from .passes import (
    assign_leadins, attach_table_headers, demote_titles, join_continuations,
    merge_footnote_continuations,
)
from .entries import build_entries, finalize_coverage
from .writers import write_json, write_markdown, write_text
from .checklist import check_in_book_md, check_in_book_text


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def process_pdf(path, cfg, log=True):
    doc = pymupdf.open(path)
    try:
        pages = parse_pages(cfg.pages, doc.page_count)
        ctx = DocContext(doc, pages, cfg)
        use_fills = not doc_has_annotation_marks(doc, pages)
        items = []
        skipped_pages = []
        for n, pno in enumerate(pages):
            try:
                page = doc[pno]
                marks = collect_marks(ctx, page, pno, use_fills)
                items.extend(page_items(ctx, page, pno, marks))
            except Exception as ex:  # one malformed page must not sink the book
                skipped_pages.append(pno + 1)
                if log:
                    sys.stderr.write("\r\033[K")
                    print(f"  warning  {path.name}: skipped page {pno + 1} ({type(ex).__name__}: {ex})",
                          file=sys.stderr)
            if log and cfg.progress:
                sys.stderr.write(f"\r  scanning {path.name}: page {n + 1}/{len(pages)}")
                sys.stderr.flush()
        if log and cfg.progress:
            sys.stderr.write("\r\033[K")
        ctx.stats["skipped_pages"] = skipped_pages
        def _stage(fn, label, *a):
            # An optional transform that must never sink the run: on failure
            # warn and carry the items through unchanged.
            nonlocal items
            try:
                out = fn(items, *a)
                if out is not None:
                    items = out
            except Exception as ex:
                if log:
                    print(f"  warning  {path.name}: {label} step skipped ({type(ex).__name__}: {ex})",
                          file=sys.stderr)

        _stage(attach_table_headers, "table-header")
        _stage(merge_footnote_continuations, "footnote-merge")
        _stage(join_continuations, "paragraph-join", cfg)
        _stage(strip_amendments, "marker-strip", cfg)
        _stage(assign_leadins, "list-leadin", cfg)
        if cfg.plain_titles:
            _stage(demote_titles, "plain-titles")
        try:
            entries = build_entries(ctx, items)
        except Exception as ex:            # last resort: no traceback, empty result
            if log:
                print(f"  warning  {path.name}: could not build entries ({type(ex).__name__}: {ex})",
                      file=sys.stderr)
            entries = []
        finalize_coverage(entries, ctx)
        report = coverage_report(ctx, path, use_fills)
        return entries, ctx, report
    finally:
        doc.close()


def coverage_report(ctx, path, use_fills):
    for m in ctx.marks:
        if m.used:
            for o in m.co:
                ctx.marks[o].used = True
    total = len(ctx.marks)
    clipped = [m for m in ctx.marks if m.raw and not "".join(m.text).strip()]
    empty = [m for m in ctx.marks if not m.raw and not "".join(m.text).strip()]
    missing = [m for m in ctx.marks if "".join(m.text).strip() and not m.used]
    dropped = [m for m in ctx.marks if getattr(m, "skipped", False)]
    lines = [f"  {path.name}: {total} mark(s)"
             + (" (from coloured fills -- no annotations found)" if use_fills else "")
             + f", {total - len(empty) - len(missing) - len(clipped)} placed in notes"]
    if dropped:
        lines.append(f"    {len(dropped)} mark(s) shown as plain text by --color-map skip")
    if clipped:
        lines.append(f"    {len(clipped)} mark(s) cover less than half of a word and were dropped by --snap word "
                     f"(use --snap char to keep exact characters): pages "
                     + ", ".join(sorted({str(m.page + 1) for m in clipped}, key=int)))
    if empty:
        lines.append(f"    {len(empty)} mark(s) cover no extractable text (image/scan?): pages "
                     + ", ".join(sorted({str(m.page + 1) for m in empty}, key=int)))
    if missing:
        lines.append(f"    {len(missing)} mark(s) could not be placed:")
        for m in missing[:15]:
            lines.append(f"      p.{m.page + 1} {m.kind}: {''.join(m.text)[:60]!r}")
    if ctx.stats["marks_in_running"]:
        lines.append(f"    note: {ctx.stats['marks_in_running']} marked character(s) were in running "
                     f"headers/footers and dropped (use --keep-running to keep them)")
    skipped = ctx.stats.get("skipped_pages") if hasattr(ctx.stats, "get") else None
    if skipped:
        lines.append(f"    warning: {len(skipped)} page(s) could not be parsed and were skipped: "
                     + ", ".join(str(p) for p in skipped))
    return "\n".join(lines)


def render(entries, ctx, cfg, level_shift=0):
    if cfg.format == "json":
        return write_json(entries, ctx)
    if cfg.format == "txt":
        return write_text(entries, cfg) + check_in_book_text(ctx)
    return write_markdown(entries, cfg, level_shift) + check_in_book_md(ctx, level_shift)


def find_pdfs(folder, recursive):
    walker = folder.rglob("*") if recursive else folder.glob("*")
    return sorted(p for p in walker if p.is_file() and p.suffix.lower() == ".pdf")

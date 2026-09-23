"""Command-line entry point: main().

Part of stack-highlights; code moved here unchanged from the original single file.
"""
import re
import sys
from pathlib import Path
from .rendering import md_escape
from .driver import find_pdfs, process_pdf, render
from .cli import config_from_args
from .config import explain, resolve_args


_SURROGATE = re.compile(r"[\ud800-\udfff]")


def write_output(path, text):
    """Write the notes as UTF-8. A lone surrogate (which a PDF with a broken
    font map can produce) cannot be written and would otherwise lose the
    whole run at the very last step: replace it with U+FFFD and warn."""
    try:
        path.write_text(text, encoding="utf-8")
    except UnicodeEncodeError:
        n = len(_SURROGATE.findall(text))
        path.write_text(_SURROGATE.sub("\ufffd", text), encoding="utf-8")
        print(f"  warning  {path.name}: {n} unreadable character(s) from the PDF were written as \ufffd",
              file=sys.stderr)


def main():
    args = resolve_args()
    if args.dry_run:
        explain(args)
        return
    cfg = config_from_args(args)
    src = Path(cfg.input).expanduser()
    if not src.exists():
        sys.exit(f"error: {src} does not exist")
    ext = {"md": ".md", "txt": ".txt", "json": ".json"}[cfg.format]

    if src.is_dir():
        pdfs = find_pdfs(src, not cfg.no_recursive)
        if not pdfs:
            sys.exit(f"No PDFs found under {src}")
        combine = cfg.combine or cfg.combine_out
        combined = []
        for pdf in pdfs:
            try:
                entries, ctx, report = process_pdf(pdf, cfg)
            except Exception as ex:  # keep going through a folder
                print(f"  error    {pdf.name}: {ex}", file=sys.stderr)
                continue
            print(report, file=sys.stderr)
            if not entries:
                continue
            if combine:
                label = str(pdf.relative_to(src))
                combined.append(("# " + (md_escape(label) if cfg.format == "md" else label) + "\n\n"
                                 + render(entries, ctx, cfg, level_shift=1)) if cfg.format != "json"
                                else render(entries, ctx, cfg))
            else:
                out = pdf.with_suffix(ext)
                write_output(out, render(entries, ctx, cfg))
                print(f"  wrote    {out}", file=sys.stderr)
        if combine and combined:
            out = Path(cfg.combine_out) if cfg.combine_out else src / ("combined_highlights" + ext)
            write_output(out, "\n".join(combined))
            print(f"  wrote    {out}", file=sys.stderr)
        return

    if src.suffix.lower() != ".pdf":
        sys.exit("error: input must be a PDF or a folder")
    try:
        entries, ctx, report = process_pdf(src, cfg)
    except Exception as ex:
        sys.exit(f"error: could not process {src.name}: {type(ex).__name__}: {ex}")
    print(report, file=sys.stderr)
    if not entries:
        print("  no highlights found", file=sys.stderr)
        return
    out = Path(cfg.out).expanduser() if cfg.out else src.with_suffix(ext)
    write_output(out, render(entries, ctx, cfg))
    print(f"  wrote    {out}", file=sys.stderr)

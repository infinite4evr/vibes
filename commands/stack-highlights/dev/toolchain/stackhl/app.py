"""Command-line entry point: main().

Part of stack-highlights; code moved here unchanged from the original single file.
"""
import sys
from pathlib import Path
from .rendering import md_escape
from .driver import find_pdfs, process_pdf, render
from .cli import config_from_args
from .config import explain, resolve_args


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
                out.write_text(render(entries, ctx, cfg), encoding="utf-8")
                print(f"  wrote    {out}", file=sys.stderr)
        if combine and combined:
            out = Path(cfg.combine_out) if cfg.combine_out else src / ("combined_highlights" + ext)
            out.write_text("\n".join(combined), encoding="utf-8")
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
    out.write_text(render(entries, ctx, cfg), encoding="utf-8")
    print(f"  wrote    {out}", file=sys.stderr)

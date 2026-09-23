"""
stack-highlights -- turn the highlights in a PDF into structured notes.

Only what you marked (highlights, and underlines by default) ends up in bold;
everything else in the output is context the tool adds around your marks so
they make sense on their own: the rest of the sentence, the heading path they
sit under, the lead-in line of a list, the row and column of a table cell.
It never adds content from outside the book.

HOW IT WORKS
    Every character on a page is tagged with the annotation covering it (if
    any). Paragraphs, headings, list items and table rows are rebuilt from
    those characters, so a highlight is carried through exactly -- no text
    searching, so ligatures, footnote markers, hyphenation and line breaks
    can't make a highlight silently disappear. At the end a coverage check
    reports any mark that did not make it into the output.

WHAT YOU GET (Markdown by default, next to each PDF)
    # / ## / ### headings   only the headings that have marked content under
                            them (chapter > section > subsection > run-in)
    snippets                the sentence around each mark, marks in **bold**;
                            long sentences are trimmed to the clauses around
                            the marks, with "…" where text was cut
    list items              prefixed with the sentence that introduces the
                            list ("The features ... are:"), consecutive items
                            under one lead-in grouped into one entry
    table rows              "Column: value · Column: value", with the row
                            label filled down for sub-rows (Chapter I under
                            Part V, etc.) and the table caption as heading
    > fn 7: ...             a highlighted footnote, placed under the snippet
                            that cites it
    > Note: ...             your own typed notes / annotation comments,
                            placed under the nearest snippet

USAGE
    stack-highlights book.pdf                   # -> book.md next to it
    stack-highlights book.pdf --out notes.md
    stack-highlights folder/                    # every PDF, recursively
    stack-highlights folder/ --combine          # one combined_highlights.md
    stack-highlights book.pdf --context clause  # tighter snippets
    stack-highlights book.pdf --max-words 30    # trim long sentences sooner
    stack-highlights book.pdf --kinds highlight # ignore underlines
    stack-highlights book.pdf --colors red      # only the red highlights
    stack-highlights book.pdf --page-refs       # "(p. 64)" after each entry
    stack-highlights book.pdf --format json     # structured output
    stack-highlights book.pdf --pages 10-40     # only part of the PDF

Run with --help for every option.
"""
import argparse
import re
import sys
from .rendering import MARK_STYLES


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="A PDF, or a folder of PDFs")
    g = ap.add_argument_group("config & presets")
    g.add_argument("--config", metavar="FILE",
                   help="TOML config file (default: ~/.config/stack-highlights.toml plus notes.toml next to the book)")
    g.add_argument("--preset", metavar="NAME",
                   help="Apply a named bundle of flags (built-in: print, revise, dense, act; add your own in config)")
    g.add_argument("--profile", metavar="NAME",
                   help="Apply a named publisher layout profile from your config (e.g. laxmikanth)")
    g.add_argument("--dry-run", "--explain", dest="dry_run", action="store_true",
                   help="Print the settings actually in effect (after config, profile, preset and flags) "
                        "plus a small sample, then exit -- check a setup before a long run")
    # Groups are ordered the way you decide about a run: what to include ->
    # how much context -> structure -> looks -> where it goes -> fine tuning.
    g = ap.add_argument_group("1. which marks count")
    g.add_argument("--kinds", default="highlight,underline",
                   help="Annotation kinds to use: highlight,underline,squiggly,strikeout (default: highlight,underline)")
    g.add_argument("--colors", help="Only marks of these colours: yellow,orange,red,pink,green,blue,purple,gray")
    g.add_argument("--snap", choices=["word", "char"], default="word",
                   help="word (default): a word is marked if >50%% of its letters are covered; char: exact characters")
    g.add_argument("--no-notes", action="store_true", help="Ignore typed notes and annotation comments")
    g = ap.add_argument_group("2. context around each mark")
    g.add_argument("--context", choices=["sentence", "clause", "comma", "paragraph", "highlight"], default="sentence",
                   help="sentence (default), clause, comma (commas only), paragraph, or highlight (marked text only)")
    g.add_argument("--word-window", type=int, default=0, metavar="N",
                   help="Instead of sentence/clause context, keep N context words around each highlight "
                        "(e.g. 6 = 3 before + 3 after). 0 = off (default)")
    g.add_argument("--word-side", choices=["both", "left", "right"], default="both",
                   help="With --word-window: take the words on both sides (default), only the left, or only the right")
    g.add_argument("--max-words", type=int, default=40,
                   help="Sentences longer than this are trimmed to the clauses around the marks (default: 40)")
    g.add_argument("--min-words", type=int, default=8,
                   help="Trimmed snippets are widened clause by clause to at least this many words (default: 8)")
    g.add_argument("--no-leadins", action="store_true", help="Don't prefix list items with the sentence introducing the list")
    g.add_argument("--no-group-lists", action="store_true", help="One entry per list item instead of grouping items under one lead-in")
    g.add_argument("--footnotes", choices=["inline", "section"], default="inline",
                   help="inline (default): a marked footnote goes under the snippet citing it; section: under a Footnotes heading")
    g.add_argument("--no-join-pages", action="store_true", help="Don't rejoin paragraphs split by a page break")
    g = ap.add_argument_group("3. structure")
    g.add_argument("--no-headings", action="store_true", help="Flat list, no heading structure")
    g.add_argument("--heading-depth", type=int, default=0, help="Only keep heading levels up to N (1=chapter ... 4=run-in/caption)")
    g.add_argument("--no-runin", action="store_true", help="Don't treat bold words opening a paragraph as a heading")
    g.add_argument("--heading-max-words", type=int, default=16, help="Longest all-bold line still treated as a heading (default: 16)")
    g.add_argument("--no-tables", action="store_true", help="Treat table cells as ordinary paragraphs")
    g.add_argument("--table-style", choices=["kv", "plain"], default="kv",
                   help="kv (default): 'Column: value · ...'; plain: values only")
    g.add_argument("--cell-words", type=int, default=30, help="Longer unmarked table cells are shortened to this many words (default: 30)")
    g.add_argument("--no-fill-down", action="store_true", help="Don't repeat the row label for sub-rows with an empty first cell")
    g = ap.add_argument_group("4. looks")
    g.add_argument("--page-refs", action="store_true", help="Add (p. N) after each entry, using the book's printed page number when found")
    g.add_argument("--color-tags", action="store_true", help="Tag non-yellow marks, e.g. **K.C. Wheare**{red}")
    g.add_argument("--italic-colors", action="store_true",
                   help="Render non-yellow highlights as bold+italic (***...***) so they stand out from ordinary yellow ones")
    g.add_argument("--color-map", metavar="MAP",
                   help="Per-colour emphasis, e.g. 'red=italic,blue=underline,green=skip'. "
                        "Styles: bold, italic, underline, skip. Use '*' for a catch-all. Overrides --italic-colors")
    g.add_argument("--plain-titles", action="store_true",
                   help="Don't treat headings specially: a highlighted heading becomes an ordinary snippet, "
                        "an un-highlighted one is dropped (uncluttered notes, no big-font headings)")
    g.add_argument("--space-every", metavar="N:M",
                   help="Notes PDF only: after every N entries insert M blank lines of writing space (e.g. 5:10)")
    g.add_argument("--space-style", choices=["blank", "ruled", "dotted"], default="blank",
                   help="With --space-every: leave the gap blank (default), or fill it with faint ruled or dotted lines")
    g = ap.add_argument_group("5. output")
    g.add_argument("--out", help="Output file (single PDF only). Default: <pdf name>.<ext> next to the PDF")
    g.add_argument("--format", choices=["md", "txt", "json"], default="md", help="Default: md")
    g.add_argument("--combine", action="store_true", help="Folder mode: one combined file instead of one per PDF")
    g.add_argument("--combine-out", help="Path of the combined file (implies --combine)")
    g.add_argument("--no-recursive", action="store_true", help="Folder mode: top level only")
    g.add_argument("--pages", help="Only these pages, e.g. 1-20,35")
    g = ap.add_argument_group("6. clean-up")
    g.add_argument("--keep-running", action="store_true", help="Keep running headers/footers (book title, page numbers)")
    g.add_argument("--keep-markers", action="store_true", help="Keep footnote numbers and amendment brackets like 4[ ... ]")
    g.add_argument("--dehyphenate", action="store_true", help="Join 'co-' + 'operation' as 'cooperation' (default keeps the hyphen)")
    g = ap.add_argument_group("7. advanced tuning (per-publisher; see --profile)")
    g.add_argument("--margin", type=float, default=0.09, help="Top/bottom page fraction searched for running headers/footers (default: 0.09)")
    g.add_argument("--sup-ratio", type=float, default=0.75, help="Text at or below this fraction of body size counts as superscript (default: 0.75)")
    g.add_argument("--footnote-ratio", type=float, default=0.9, help="Paragraphs at or below this fraction of body size starting with a number are footnotes (default: 0.9)")
    g.add_argument("--row-tolerance", type=float, default=3.0, help="Max top-edge difference (pt) for blocks to form one table row (default: 3)")
    g.add_argument("--column-tolerance", type=float, default=20.0, help="Max x difference (pt) to match a cell to a column (default: 20)")
    g.add_argument("--no-progress", action="store_true", help="No progress line")
    return ap


def config_from_args(a):
    a.kinds = {k.strip() for k in a.kinds.split(",") if k.strip()}
    a.colors = {c.strip() for c in a.colors.split(",")} if a.colors else None
    raw_cmap = a.color_map        # the --color-map string, or None
    a.color_map = None
    if raw_cmap:
        cmap = {}
        for pair in raw_cmap.split(","):
            pair = pair.strip()
            if not pair:
                continue
            if "=" not in pair:
                sys.exit(f"error: --color-map entry must be colour=style, got {pair!r}")
            col, style = (x.strip() for x in pair.split("=", 1))
            if style not in MARK_STYLES:
                sys.exit(f"error: --color-map style must be one of {list(MARK_STYLES)}, got {style!r}")
            cmap[col] = style
        a.color_map = cmap or None
    a.notes = not a.no_notes
    a.leadins = not a.no_leadins
    a.group_lists = not a.no_group_lists
    a.join_pages = not a.no_join_pages
    a.headings = not a.no_headings
    a.runin = not a.no_runin
    a.tables = not a.no_tables
    a.fill_down = not a.no_fill_down
    a.strip_running = not a.keep_running
    a.progress = not a.no_progress and sys.stderr.isatty()
    a.fmt_render = "txt" if a.format == "txt" else "md"  # json tokenises the md runs
    a.space_n = a.space_m = 0
    if a.space_every:
        m = re.match(r"^\s*(\d+)\s*[:, ]\s*(\d+)\s*$", a.space_every)
        if not m:
            sys.exit("error: --space-every must look like N:M, e.g. 5:10")
        a.space_n, a.space_m = int(m.group(1)), int(m.group(2))
    if a.word_window < 0:
        sys.exit("error: --word-window can't be negative")
    return a

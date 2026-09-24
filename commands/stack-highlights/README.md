# stack-highlights

Turn the highlights in a PDF into structured notes (Markdown, plain text or
JSON). Only what you marked ends up in **bold**; everything else is the
surrounding context added so the marks make sense. `recall-sheet` uses it.

This is the rebuilt, modular version (from `highlight-notes-FINAL`). It
replaces both the previous `stack-highlights` and `stack-highlights-legacy`.
It accepts every flag the previous `stack-highlights` had; the legacy-only
options (`--jobs`, `--markdown`, `--with-labels`, `--out-suffix` ...) are gone.

```
stack-highlights book.pdf                        # -> book.md
stack-highlights book.pdf --format json          # -> book.json
stack-highlights book.pdf --preset revise        # print | revise | dense | act
stack-highlights book.pdf --pages 100-150 --dry-run   # show the settings in effect + a sample
stack-highlights folder/ --combine               # every PDF in a folder, one file
```

Run `stack-highlights --help` for every option.

## Layout

| Path | What |
|---|---|
| `stack-highlights` | the command (a small launcher) |
| `stackhl/` | the code, one module per stage; see `REFACTORING.md` for the map |
| `tests/` | unit tests, golden files, fixture PDFs, real-book coverage check (`merged_books.py` splits the test PDF into its books) |
| `Makefile` | runs the tests |
| `requirements.txt` | the pinned PyMuPDF version |
| `stack-highlights.toml.example` | example config, presets and profiles |
| `dev/` | the full development archive (not tracked by git; see below) |

Keep `stack-highlights` and `stackhl/` together. `env.sh` puts this folder on
your PATH, so nothing needs linking or copying.

## Requirements

- Python 3.11 or newer (3.11+ is needed to read config files).
- PyMuPDF **1.28.2**, pinned in `requirements.txt`. Notes can shift slightly
  between PyMuPDF versions, so after any upgrade run `make test`.

```
python3 -m pip install -r requirements.txt
```

## Configuration

Personal defaults go in `~/.config/stack-highlights.toml`, per-book settings in
a `notes.toml` next to the book. Precedence, lowest to highest: built-in
defaults < config `[defaults]` < `--profile` < `--preset` < command-line flags.
Copy `stack-highlights.toml.example` to start.

## "Check in book"

Every run ends with a coverage line, e.g. `648 mark(s), 647 placed in notes`.
When a highlight could not be placed, the notes end with a **Check in book**
section naming each one with its page and the reason:

- it covers less than half a word (rerun with `--snap char` to keep it),
- there is no text under it (an image, figure or scanned area), or
- its text could not be placed in the notes.

In JSON the same list is the top-level `"check_in_book"` key. `recall-sheet`
leaves this section out of recall sheets.

## Everyday checklist

1. Run whole books or continuous page ranges (`--pages 100-150`). For scattered
   pages (`--pages 50,90`) add `--no-join-pages`.
2. Read the coverage line; if the numbers differ, see "Check in book".
3. `--page-refs` page numbers are approximate; the "Check in book" pages are exact.
4. Tables and complicated footnotes may come out with imperfect layout, but the
   highlighted words are still there.

## Tests

`make test` must stay green after any code change or PyMuPDF upgrade.

```
make quick            # unit tests + golden files (seconds, no books needed)
make test             # + real-book coverage + PDF safety (about 5 minutes)
make coverage         # real-book coverage only: 14 books, 18,567 of 18,647 highlights placed
make visual           # the 500-page visual test (dev/visual-tests-500, 3-4 minutes)
make visual-pytest    # the same as 500 pytest cases
make pdf-safety       # the PDF step: bad characters must never stop a run (about a minute)
make update           # regenerate goldens DELIBERATELY, then review the diff
make update-coverage  # record new real-book results, only after checking they are better
make clean            # remove scratch output (and the split books) and Python caches
```

The real-book checks use one test PDF, `Test-Merged-All.pdf` (9,916 pages, 16
documents), from `$HIGHLIGHT_PDFS`, else `dev/source-pdfs`. They split it back
into its 14 highlighted books and run each on its own, the way the tool is used
(run as one 9,916-page file, the page statistics of the other books distort the
notes). The first run splits the PDF (about 1.5 minutes) into `tests/.tmp`;
later runs reuse the split. Without the PDF they print `SKIP` and the rest still
runs.

`make visual` checks the 500 pages whose every highlight was judged by eye
(88.0% fully correct, 99.2% correct or minor; see
`dev/visual-tests-500/REPORT.md`): it fails if a highlight judged correct stops
being placed, and lists any page whose notes changed so its verdicts can be
looked at again. It needs `dev/`.
The PDF-step check uses `md-to-pdf` (with its `md-to-pdf-safety.py`),
`recall-sheet` and `notes-recall` from the commands folder this one sits in (or
`$COMMANDS_DIR`); without them, or without pandoc/LaTeX, it also prints `SKIP`.
`tests/golden/README.md` explains each golden case.

## `dev/` — the development archive

Kept for testing and provenance: the 500-page visual test (`visual-tests-500/`,
with its report), the place for the test PDF (`source-pdfs/`), the original
upload, fix reports and development artifacts. Its own `README.md` explains it.

- `dev/toolchain/` and `dev/original-toolchain/` are frozen snapshots of earlier
  versions; no test runs them and they have drifted from `stackhl/` (no
  surrogate-safe `write_output`, older tests). Make code changes in `stackhl/`
  here, not there.
- It is tracked in this private repository (about 200 MB, mostly reference
  images); only the test PDF in `dev/source-pdfs/` is git-ignored. The images
  contain copyrighted books: do not make the repository public.

# Highlight-to-notes toolset

Turn the highlights in a PDF into study notes and active-recall sheets.

**Setting it up, or checking how to run it day to day: see [`SETUP.md`](SETUP.md).**

## The tools

- **`stack-highlights`** — reads a highlighted PDF and writes structured notes
  (Markdown, plain text, or JSON). Only what you marked ends up in **bold**;
  everything else is the surrounding context it adds so the marks make sense.
  Its code lives in the `stackhl/` folder next to it — keep the two together
  (see [`REFACTORING.md`](REFACTORING.md) for what is in each module).
- **`recall-sheet`** — turns those notes into a two-column active-recall sheet
  (cue words left, answer right; optional cloze blanks).
- **`md-to-pdf`** — renders a notes Markdown file to PDF (also used by
  `recall-sheet`). Ships with `fallback.tex`, `italic.tex`, `hr-fullwidth.lua`;
  keep all four together.
- **`notes`** — one wrapper that runs the tools above for you and produces every
  output you ask for: `notes book.pdf --to notes,recall,md,json`. (When you ask
  for both Markdown and JSON-based outputs it extracts twice, once per format.)

## Quick start

```
stack-highlights book.pdf                 # -> book.md
notes book.pdf                            # -> book_notes.pdf + book_recall.pdf
notes book.pdf --to notes --preset revise
recall-sheet book.pdf --right cloze --grey-context
```

Run any tool with `--help`. `stack-highlights ... --dry-run` prints the settings
actually in effect (after config, profile, preset and flags) plus a small
sample, so you can check a setup before an 800-page run.

## Configuration

Personal defaults live in `~/.config/stack-highlights.toml`; per-book settings
in a `notes.toml` next to the book. Presets (`--preset print|revise|dense|act`)
and publisher profiles (`--profile ...`) are named flag bundles you can edit or
extend. See `stack-highlights.toml.example`.

## Highlights that could not be placed: "Check in book"

Every run ends with a coverage line, e.g.
`book.pdf: 648 mark(s), 647 placed in notes`. When a highlight could not be
placed, the notes also end with a **Check in book** section naming each one,
with its PDF page (and printed page number when the book has them) and why:

- it covers less than half of a word (left out by the default `--snap word`;
  rerun with `--snap char` to keep it),
- there is no text under it (an image, figure or scanned area), or
- its text could not be placed in the notes.

Any note you typed on that highlight is shown too. The list follows exactly the
same rules as the coverage line, so the two always agree. In JSON the same list
is the top-level `"check_in_book"` key. When every highlight was placed nothing
is added, and the notes are exactly what they were before this feature. The
list is plain text, never bold, because in the notes bold means "you
highlighted this". Recall sheets are not affected.

## Data model

`stack-highlights --format json` emits a structured model: each line is a list
of runs `{text, mark, italic}`. `recall-sheet` reads this JSON directly, so it
never re-parses Markdown or undoes escaping — the source of a whole class of
past bugs. A single tokenizer (`runs_from_md`) is the one place Markdown is
turned into runs.

## Tests

The safety net. `make test` must stay green.

```
make test             # everything below (about 1.5 minutes with the six books)
make quick            # unit tests + golden files only (seconds, no books needed)
make units            # unit tests only
make golden           # golden-file checks only
make coverage         # real-book coverage only
make update           # regenerate goldens DELIBERATELY, then review the diff of tests/golden
make update-coverage  # record new real-book results, only after checking they are better
make fixtures         # rebuild the fixture PDFs
```

- **Unit tests** (`tests/test_units.py`, 12 tests) cover the pieces where bugs
  have lived: sentence boundaries, list-marker escaping, amendment-bracket
  stripping, the hyphen-join rule, the `runs_from_md` tokenizer, and the
  "Check in book" list.
- **Golden files** (`tests/golden/`, 25 cases on 7 small fixture PDFs) pin the
  byte-for-byte output across the fragile paths: page breaks and page gaps,
  running headers and printed page numbers, line-break hyphens, a table and a
  footnote, real legal typesetting (bold run-in titles ending ".—", a STATE
  AMENDMENT block), and highlights that cannot be placed. Every case also
  checks its coverage numbers and that its "Check in book" list names exactly
  the missing highlights — so a lost highlight fails even after `make update`.
  Goldens ending in `_KNOWN_ISSUE` record today's behaviour for a known
  problem; see `tests/golden/README.md`.
- **Real-book coverage** (`tests/run_coverage.py`) runs the six books and fails
  if any highlight that used to be placed is no longer placed, even when a
  different one was fixed at the same time. The baseline
  (`tests/coverage_baseline.json`) is 8,535 of 8,539 highlights placed; the 4
  exceptions are listed in it. The books are looked for in `$HIGHLIGHT_PDFS`,
  else `../source-pdfs`; without them this check is skipped with a message.
- The fixture PDFs are built by `tests/build_fixtures.py` from PyMuPDF's
  built-in fonts, so they can be rebuilt anywhere.

## Notes on styling

- `--grey-context` (recall-sheet and md-to-pdf via `notes`): context in grey,
  marks and headings in black, so the eye lands on what you marked.
- `--space-every N:M` with `--space-style ruled|dotted`: usable hand-writing
  space instead of a blank gap.
- `--color-map "red=italic,green=skip"`: per-colour emphasis. Styles are
  `bold`, `italic`, `skip`. (`underline` is not yet supported — it needs raw
  LaTeX that the current shared format can't carry portably.)

## Safety-first extraction behaviour

This version uses conservative layout reconstruction: when table/column structure is not strongly supported by repeated geometry, ordinary reading order wins. Coverage is calculated from the final surviving note entries, so a mark dropped during grouping cannot be silently counted as covered. For ambiguous list lead-ins, the extractor prefers a duplicate snippet over losing highlighted text.

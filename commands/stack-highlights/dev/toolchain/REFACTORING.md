# Module layout (refactor)

`stack-highlights` used to be one 2,635-line file. It is now split into the
`stackhl/` package. **No code was changed**: every statement was moved
verbatim; the only new lines are `import` lines and a one-paragraph
description at the top of each module.

`stack-highlights` itself is now a small launcher. Run it exactly as before.
**Keep the `stackhl/` folder next to `stack-highlights`** -- copying the
single file somewhere else on its own will no longer work. A symlink to it
(e.g. in `~/bin`) works fine.

| Module | What's in it |
|---|---|
| `backend.py` | PyMuPDF import (falls back to the old `fitz` name) |
| `constants.py` | all constants, layout thresholds, running-header settings |
| `helpers.py` | colour names, word count, rectangle distance, `parse_pages` |
| `model.py` | `Mark`, `Token`, `Para`, `Item`, `Entry` |
| `context.py` | `DocContext`: body size, running headers/footers, page labels |
| `marks.py` | annotations -> marks |
| `tokens.py` | page -> lines of tokens (character level, with marks) |
| `paragraphs.py` | tokens -> `Para` (footnote markers, amendment brackets, hyphenation) |
| `headings.py` | heading lines and run-in headings |
| `tables.py` | table state, rows and columns |
| `layout.py` | blocks, bands, side-by-side text, `page_items` |
| `passes.py` | document-level passes (page joins, footnotes, table headers, lead-ins) |
| `segmentation.py` | sentence / clause segmentation |
| `rendering.py` | rendering marked text |
| `entries.py` | building entries, final coverage |
| `checklist.py` | the "Check in book" list (added after the refactor; see below) |
| `writers.py` | Markdown, plain text, JSON |
| `driver.py` | processing one PDF, coverage report, folder scan |
| `cli.py` | command-line options (its docstring is the `--help` text) |
| `config.py` | config files, presets, publisher profiles |
| `app.py` | `main()` |
| `__init__.py` | re-exports every original name, so the tests and anything that loads `stack-highlights` see the same namespace |

Modules only import from modules listed above them (no circular imports).

## How it was verified

Original single file vs this version, same machine (Python 3.12, PyMuPDF 1.28.2):

- All 128 top-level statements identical character-for-character; all 247
  comments kept; same 134 names exposed.
- All 156 functions and methods compile to the same instructions and every
  constant has the same value. (Only difference: a flag Python 3.12 sets on
  calls to names that arrive via `import`. It does not change behaviour.)
- `make test`: 9/9 unit tests, 7/7 golden files.
- `--help`, `--dry-run` and five error messages/exit codes: byte-identical.
- All six books, Markdown + JSON + text: byte-identical, coverage lines included
  (8,535 of 8,539 highlights placed, as before).
- 39 option combinations x 5 books = 195 runs: byte-identical.
- All 5 visual-benchmark profiles x 6 books (30 runs): byte-identical, same scores.
- Folder mode, `--no-recursive`, `--combine`, `--combine-out`, `--config` with a
  preset and profile, per-book `notes.toml`, progress output: byte-identical.
- `notes` (notes + recall + md + json) and `recall-sheet` (cloze with grey
  context, bold, PDF input and JSON input): identical Markdown/JSON, identical
  PDF text and page counts.
- Running through a symlink on PATH from another folder: identical output.

Left untouched on purpose: an unused variable in the original code
(`first`, now in `layout.py`), because removing it would be a code change.

Note: `verify_package.py` in the full package checks the SHA-256 of
`toolchain/stack-highlights` against the benchmark's recorded one, so it will
report a mismatch after this refactor even though behaviour is identical.

## Changes after the refactor

The refactor above moved code without changing it. Afterwards, one feature was
added, keeping the extraction code untouched:

- `checklist.py` (new): builds the "Check in book" list from the same rules as
  the coverage line.
- `driver.py`, `render()`: 2 lines changed, to append the list to Markdown and
  text notes.
- `writers.py`, `write_json()`: 3 lines added, to add `"check_in_book"` to
  JSON when something was not placed.
- `__init__.py`: exports the four new functions.

Checked on the same machine: for all six books, the Markdown, text and JSON
output is byte-identical to before, plus the new list only in the three books
that have unplaced highlights (4 highlights in total). All 30
visual-benchmark runs are byte-identical, because none of the benchmark pages
has an unplaced highlight.

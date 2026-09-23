# Changes

## Round 4 — one test PDF, a 500-page visual test, coverage on the merged PDF

Extraction logic unchanged: no file in `stackhl/`, `stack-highlights`, `notes`,
`recall-sheet`, `md-to-pdf` or `notes-recall` was touched. Tests and docs only.

- **Test PDF:** `Test-Merged-All.pdf` (9,916 pages, 16 documents, 19,208 annotations)
  replaces the six single-book PDFs, which are inside it with identical highlights.
- **500-page visual test** (`visual-tests-500/`): every highlight on 500 random,
  spread-out pages (3,725) judged by eye against the notes, each book run on its own:
  88.0% fully correct, 99.2% correct or minor, 28 failures on 10 pages
  (`visual-tests-500/REPORT.md`). Automated as `run_visual_tests.py` + `gold_cases.json`
  (`make visual`) and `test_visual_500.py` (500 pytest cases).
- **Real-book coverage** (`tests/run_coverage.py`): now splits the merged PDF into its
  14 highlighted books (`tests/merged_books.py`) and runs each; baseline
  18,567 of 18,647 highlights placed, pages given as merged-PDF pages.
- **Retired:** the 180-page visual suite and its benchmark outputs; the six old PDFs;
  the old `MANIFEST.json`, `FILE_LIST.tsv`, `PACKAGE_TREE.txt`. `verify_package.py`
  rewritten for the new layout; `SHA256SUMS.txt` now covers the frozen review material.
- **Makefiles and READMEs** updated: `make visual`, `make visual-pytest`; `dev/Makefile`
  now runs the live toolchain's tests instead of the frozen `dev/toolchain/` copy.

## Round 3 — "Check in book", stronger tests, setup guide, housekeeping

Extraction logic unchanged. For all six books, notes are byte-identical to
round 2 except for the new list in the three books with unplaced highlights;
all 30 visual-benchmark outputs are byte-identical.

- **"Check in book" list** at the end of the notes (Markdown and text) and as
  `"check_in_book"` in JSON, naming every highlight that could not be placed,
  with its page, the reason and any note typed on it. New module
  `stackhl/checklist.py`; 2 lines in `driver.render()`, 3 in `writers.write_json()`.
- **Real-book coverage check** — `tests/run_coverage.py` with
  `tests/coverage_baseline.json`; part of `make test`.
- **Stronger fixtures** — 5 new fixture PDFs (page break and page gap, line-break
  hyphens, table and footnote, real legal typesetting, unplaceable highlights)
  and 18 new golden cases; every golden case now checks coverage numbers and the
  "Check in book" list. The misleading comment about the "co-" highlight in the
  original fixture was corrected (the fixture itself is unchanged).
  `build_fixtures.py` uses `import pymupdf` (the `fitz` name is deprecated).
- **Setup guide** — `toolchain/SETUP.md`, plus `toolchain/requirements.txt`.
- **Housekeeping**
  - Makefiles: `make quick`, `make coverage`, `make update-coverage`, `make fixtures`;
    `make clean` also removes `stackhl/__pycache__`.
  - Fixed `make visual-benchmark`: it passed a relative output folder, which the
    benchmark runner rejects.
  - `verify_package.py`: checks the modules, every golden and fixture, the coverage
    baseline and every file in `SHA256SUMS.txt`; the old single-file hash check
    now checks only the benchmark's own record of the script it was run with.
  - READMEs corrected: tests, layout, the `notes` wrapper's "runs once" claim,
    and caveats on the old benchmark numbers. A "do not publish" note for the
    copyrighted books.
  - `MANIFEST.json`, `FILE_LIST.tsv`, `PACKAGE_TREE.txt`, `SHA256SUMS.txt` regenerated.

Not changed on purpose: `visual-gold-tests/ISSUES_FINAL_SCRIPT.md`, the gold
cases, the benchmark runner and its packaged results (pending a decision on
revising the benchmark method).

## Round 2 — modules

`stack-highlights` split into the `stackhl/` package without changing the code;
see `toolchain/REFACTORING.md`.

## Round 1 — complete package

Restored test harness (9 unit tests, 7 goldens), fresh benchmark outputs,
package metadata.

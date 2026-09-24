# dev/ — development archive of stack-highlights

Kept next to the toolchain for testing and provenance. Tracked in the private repository
except the test PDF (`source-pdfs/` is git-ignored); not for publishing: the test PDF and
the reference images contain copyrighted books.

## What is here

| Path | What |
|---|---|
| `source-pdfs/` | put **Test-Merged-All.pdf** here (not in the zip, 266 MB; see its README). All real-book tests use it. |
| `visual-tests-500/` | **the 500-page visual test**: every highlight on 500 pages judged by eye, the automated regression test built from it, and the report — start with `visual-tests-500/REPORT.md` |
| `original-upload/files.zip` | the exact original code ZIP |
| `original-toolchain/files/` | that ZIP extracted, unmodified |
| `toolchain/` | a frozen snapshot of an earlier fixed version (with `FIX_REPORT.md`); not used by any test now — make code changes in `../stackhl/` |
| `development-artifacts/` | scripts and outputs from the earlier fix and benchmark rounds |
| `docs/` | provenance notes; `docs/CHANGES.md` lists what changed in each round |
| `verify_package.py` | checks this archive: required files, suite counts, checksums (`SHA256SUMS.txt`) |
| `Makefile` | shortcuts to the toolchain's tests (below) |

The earlier 180-page visual suite and the six single-book PDFs were retired: the six books are
inside the merged PDF with identical highlights, and the 500-page suite replaces the 180 pages.

## Tests

From here (or `make …` in the stack-highlights folder one level up):

```bash
make quick          # unit tests + golden files (seconds)
make test           # + real-book coverage on the merged PDF + PDF safety (about 5 minutes)
make coverage       # real-book coverage only (3-4 minutes; the first run also splits the PDF)
make visual         # the 500-page visual test (3-4 minutes)
make visual-pytest  # the same as 500 pytest cases
make verify         # this archive's files and checksums (python3 verify_package.py --pdf checks the PDF too)
```

All are green on the final package with PyMuPDF 1.28.2:
13 unit tests, 25 golden files, coverage 18,567 of 18,647 highlights placed in the 14 books
(every miss listed under "Check in book"), visual test 500 of 500 pages the same as judged.

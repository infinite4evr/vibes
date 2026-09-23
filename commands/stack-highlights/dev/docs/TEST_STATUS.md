# Test status

All with Python 3.12, PyMuPDF 1.28.2, on the final round-4 package.

| Test | Command | Result |
|---|---|---|
| Unit tests | `make units` | 13 pass |
| Golden files (7 fixture PDFs; each also checks coverage and "Check in book") | `make golden` | 25 pass |
| Real-book coverage: the 14 highlighted books of Test-Merged-All.pdf | `make coverage` | 18,567 of 18,647 placed, matches `tests/coverage_baseline.json` |
| PDF safety (md-to-pdf, recall-sheet, notes-recall) | `make pdf-safety` | 7 pass (needs pandoc and a TeX Live with `lmodern`) |
| 500-page visual test | `make visual` | 500 of 500 pages the same as judged, 0 regressions |

The visual verdicts themselves (88.0% fully correct, 99.2% correct or minor, 28 failures)
are in `../visual-tests-500/REPORT.md`.

History: round 3 used six single-book PDFs (8,535 of 8,539 placed) and a 180-page visual
benchmark; both were retired in round 4 (see `CHANGES.md`).

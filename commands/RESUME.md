# Handoff — testing of stack-highlights on Test-Merged-All.pdf: COMPLETE

All four parts of the agreed plan are done. The tool itself was not changed (owner's choice);
only tests and docs.

1. **Visual review of 500 pages** — every highlight on each page (3,725) judged by eye.
   **88.0% fully correct, 99.2% correct or minor, 28 failures on 10 pages** (0.75%).
   Read `stack-highlights/dev/visual-tests-500/REPORT.md`.
2. **Automated visual test** — `make visual` (or `make visual-pytest`, 500 cases): fails if a
   highlight judged correct stops being placed; lists pages whose notes changed.
3. **Real-book coverage on the merged PDF** — `make coverage` (part of `make test`): the 14
   highlighted books, 18,567 of 18,647 highlights placed.
4. **Wrap-up** — report, READMEs, Makefiles, change log (`dev/docs/CHANGES.md`, round 4);
   the 180-page legacy suite and the six old PDFs retired.

## To run the tests

```bash
cd Final-Upload/stack-highlights
python3 -m pip install -r requirements.txt pillow     # PyMuPDF 1.28.2 is pinned
# put Test-Merged-All.pdf (not in the zip, 266 MB) into dev/source-pdfs/
make quick      # seconds
make test       # about 5 minutes: + coverage on the merged PDF + PDF safety
make visual     # 3-4 minutes
python3 dev/verify_package.py --pdf   # archive files, checksums, and the PDF's SHA-256
```

`make pdf-safety` needs pandoc and a TeX Live with the `lmodern` package.

## Where things are

| Path | What |
|---|---|
| `stack-highlights/dev/visual-tests-500/REPORT.md` | the answer, per book, the failures with images, minor-issue kinds, findings |
| `stack-highlights/dev/visual-tests-500/README.md` | the suite, how to re-record verdicts after a tool change, the verdict rules |
| `stack-highlights/dev/visual-tests-500/gold_cases.json` | the 500 pages' highlights, verdicts and judged notes |
| `stack-highlights/tests/run_coverage.py`, `merged_books.py`, `coverage_baseline.json` | the coverage test on the merged PDF |
| `stack-highlights/dev/source-pdfs/README.md` | where the PDF goes, and its verified size and SHA-256 |

## Worth knowing

- The merged PDF holds 11 acts twice (about 390 pages); 23 of the 500 sampled pages repeat
  another sampled page. Figures without them: 87.9% / 99.2%.
- All tests run the merged PDF book by book: as one 9,916-page file, the page statistics of the
  other books distort the notes (REPORT.md, finding 3).
- Settings that may reduce some minor issues, not tested: `--dehyphenate`, `--max-words`,
  `--context paragraph`, `--no-tables`.
- The README mentions an `env.sh` that puts the tools on the PATH; it is not in this package.

# visual-tests-500 — the 500-page visual test of stack-highlights

500 pages of `../source-pdfs/Test-Merged-All.pdf`, chosen at random but spread over every book
that has highlights, and **every highlight on each page (3,725) checked by eye** against the notes
the tool produces (default settings, each book run on its own). Result: 88.0% fully correct,
99.2% correct or minor, 28 failures on 10 pages — **read `REPORT.md`**.

It replaces the earlier 180-page suite (`visual-gold-tests-legacy-180`, removed).

## Running it

From the stack-highlights folder:

```bash
make visual          # run the tool on the 14 books, check the 500 pages (3-4 minutes)
make visual-pytest   # the same as 500 pytest cases (needs pytest)
```

or here: `python3 run_visual_tests.py [--strict] [--pages P300-P320] [--output SAVED.json]`.
It needs `../source-pdfs/Test-Merged-All.pdf` (or `$HIGHLIGHT_PDFS`); without it, it prints SKIP.

What it reports, page by page:

- **REGRESSION** (fails): a highlight judged correct (P) or minor (M) is no longer placed.
- **CHANGED**: the notes around the page differ from what was judged, so its verdicts may not
  hold any more. Open `images/<page>.png`, compare with the printed diff, and re-record the
  verdicts (see "Recording new verdicts"). `--strict` makes these fail too.
- **IMPROVED**: a highlight that was missing or partly placed is now placed.

While every page is "same as judged", the recorded verdicts (and so the percentages in
`REPORT.md`) hold for the current tool.

## Files

| File | What |
|---|---|
| `REPORT.md` | the result: overall and per-book figures, the failures with images, kinds of minor issues, findings |
| `FINDINGS.md` | detailed notes kept during the review, book by book |
| `STATUS.md` | the verdict totals and every failure (`python3 status.py > STATUS.md`) |
| `gold_cases.json` | **the test cases**: for each page its highlights (number on the image, position, verified text, verdict and reason, where it was placed) and the notes as judged |
| `images/Pnnn_pXXXX.png` | the 500 reference images: suite page nnn = merged-PDF page XXXX, 100 dpi, every highlight boxed in red and numbered (#1, #2 … = the mark numbers everywhere) |
| `report_images/` | crops of the 10 pages with failures (made by `report_assets.py`) |
| `review_log.jsonl` | the verdicts as recorded, one line per page (last line per page wins) |
| `marks_raw.json` | every highlight on the 500 pages: quads, kind, colour, text-layer transcription (`words` = words at least half covered, `chars` = exact characters) |
| `gold_fixes.jsonl` | transcriptions corrected after looking at the image |
| `selection.json` | the 500 pages and how they were picked (seed 20260923, rule in `select_pages.py`) |
| `page_features.json` | every annotated page of the merged PDF (mark counts, kinds, ink/notes) |
| `duplicates.json` | sampled pages that are exact repeats (the merged PDF holds 11 acts twice) |
| `sources.py` | page ranges of the 16 documents in the merged PDF (and of the 19 labour acts) |
| `outputs/default_books.json` | the notes that were judged (book by book, merged-PDF page numbers) |
| `outputs/default_merged_page_ranges.json` | the same pages run as ranges of the merged file (shows finding 3 of the report) |
| `outputs/logs/` | the per-book run logs of the judged notes |

## Scripts

| Script | Use |
|---|---|
| `run_visual_tests.py` | the regression runner (above) |
| `test_visual_500.py` | pytest wrapper, one case per page |
| `build_gold_cases.py` | re-creates `gold_cases.json` from the files above |
| `report_assets.py` | makes `report_images/` and the minor-issue table |
| `status.py` | prints `STATUS.md` |
| `select_pages.py`, `build_gold_marks.py`, `render_images.py` | re-create `selection.json`, `marks_raw.json`, `images/` |
| `run_books.py`, `run_sources.py`, `compare_runs.py` | the book-by-book / page-range runs used during the review |
| `rv`, `review_print.py`, `automatch.py`, `sheet.py`, `ent.py`, `dupcmp.py` | review aids: print the notes next to each numbered highlight, stack page crops into sheets, print whole entries, compare a repeated page with its twin |
| `record.py`, `goldfix.py` | record verdicts (lines on stdin, see its docstring; do not put ";" inside a reason) and transcription fixes |

The shared code that splits the merged PDF into its books is `../../tests/merged_books.py`
(also used by the coverage test).

## Recording new verdicts

When a change to the tool makes pages CHANGED and they are better (or worse):

1. `python3 run_visual_tests.py --save outputs/new.json` (keeps the fresh notes);
2. `python3 render_images.py ../source-pdfs/Test-Merged-All.pdf images/` once, to get the
   review crops, then for the changed pages `python3 sheet.py 0.85 P123-P130` and look at them
   next to `python3 review_print.py outputs/new.json P123-P130`;
3. record the new verdicts with `record.py`;
4. `python3 build_gold_cases.py --output outputs/new.json`, `python3 status.py > STATUS.md`,
   and update `REPORT.md`.

### Verdict rules (keep them consistent with the 3,725 verdicts recorded)

- **P** — every marked word is in the notes, bold, with correct surrounding context. Still P:
  context shortened with "…" that keeps the meaning; context trimmed but the section heading
  supplies who or when; a paragraph continued from an earlier page (the entry carries that page's
  number); footnotes moved under the sentence that cites them; marked headings output as
  headings; table rows as "col: value"; a leading bullet symbol alone.
- **M** — marked information correct but something a reader notices is off: line-break hyphen
  kept; words split after the "fi" ligature; stray footnote number, symbol, bullet read as a letter,
  or margin-note text inside the sentence; words glued ("aemployee"); context trimmed so who, what
  or the condition is lost (and the heading does not supply it); a sentence, title or item split
  into two entries or headings; list or bullet items run together (M for every mark in the run);
  items or quiz answers without their lead-in or question; an unrelated lead-in prefixed; a stray
  fragment appended (M on the adjacent mark only); table row split, pair cell dropped, fraction
  flattened; row label right but paired with the wrong row's content; filed under a clearly wrong
  heading; a half-covered word left unbold; marked words intact inside a scrambled entry.
- **F** — marked words missing, cut, altered or scrambled; context from the wrong place that
  changes the meaning (a table row's content filed under another row, a quiz answer under another
  question); marked text not placed at all, only listed under "Check in book".
- **X** — cannot be judged: a highlight over no text, or a stray one-letter mark, that the tool
  lists under "Check in book" (correct behaviour).
- Page notes (not counted): `S` structure/heading problems, `N` typed-note placement,
  `T` text-layer oddity; mention repeats (`repeat of Pxxx`).

`rv`'s FOUND/PARTIAL/MISSING is only a hint: it matches on the tool's mark list, so short marks
like "(a)" can be matched to the wrong entry, and noisy text layers say MISSING. Always decide
from the image plus the printed entries.

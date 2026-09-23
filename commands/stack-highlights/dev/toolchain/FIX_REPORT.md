> **Historical report** from the fix pass. Since then the test suite has been added
> (see the Tests section of `README.md`), the code has been split into modules
> (`REFACTORING.md`), and missed highlights are listed in the notes ("Check in book").

# Highlight Notes Extractor — Safety-First Fix Report

## Goal

The fixes in this package prioritise **faithful study text over perfect layout reconstruction**. When the PDF layout is ambiguous, the extractor now prefers ordinary reading order instead of guessing a table/side-by-side structure that could change the meaning.

## Fixed issues

### 1. Honest coverage and missing list lead-ins

Coverage is now recomputed from the entries that actually survive into final output. Temporary entries removed during list grouping can no longer make a missing highlight appear "covered".

When a highlighted list lead-in is shortened for grouped output, the standalone lead-in entry is removed only if **all** of its highlighted marks are represented in the emitted lead-in. Otherwise the standalone snippet is retained. This intentionally prefers harmless duplication over silent loss.

### 2. Scrambled body prose / false table detection

Table detection is now conservative. Multiple nearby rows must repeat at least two column starts before they are treated as a table. Normal prose is a hard boundary for table state, and a table cannot continue across a large vertical gap.

A common split section-heading layout such as `7.5` + `LIQUIDITY RATIOS` is explicitly recognised so it cannot turn the following prose into a false table.

### 3. Economy M1–M4 subscripts

Small lower-positioned digit glyphs detached by the PDF text layer are reattached to their host token before layout classification. They are rendered portably as `M1`, `M2`, `M3`, `M4`. Upper-positioned superscripts remain available for footnote handling.

### 4. Running chapter headers in Accounting

Repeated text in the physical page margin can now be recognised as a running header after a small number of exact repeats, even if that chapter header does not occur on 30% of the entire book. Structural legal labels such as `CHAPTER`, `PART`, and `STATE AMENDMENT` are excluded from this shortcut.

### 5. `This page is intentionally left blank.`

Unmarked blank-page boilerplate is ignored before heading classification. If a user deliberately highlights the line, it is not silently discarded.

### 6. Industrial Disputes Act hierarchy

Explicit `CHAPTER` / `PART` labels are recognised as structure even when the publisher typesets them like body text. When a central numbered section resumes after a `STATE AMENDMENT` block, stale state-amendment hierarchy is cleared so central sections are not nested beneath the amendment heading.

### 7. `Kohler's` run-in attribution

A single bold possessive opening word is no longer treated as a run-in heading. This prevents attribution text such as `Kohler's dictionary...` from becoming unrelated structural context.

## Regression results

The final extractor was run across all six supplied PDFs:

| PDF | Marks detected | Placed in final notes | Explicitly reported exceptions |
|---|---:|---:|---|
| Constitution of India | 567 | 567 | 0 |
| Fundamentals of Accounting and Financial Analysis | 453 | 453 | 0 |
| Indian Economy | 773 | 773 | 0 |
| Indian Polity (Laxmikanth) | 5,648 | 5,646 | 2 marks cover less than half a word under default `--snap word` (pages 115, 350) |
| Industrial Disputes Act, 1947 | 450 | 449 | 1 mark covers less than half a word under default `--snap word` (page 11) |
| A Brief History of Modern India | 648 | 647 | 1 mark covers no extractable text / image-scan case (page 102) |

The important change is that these exceptions are **not reported as 100% coverage**. They are surfaced explicitly.

Targeted checks also confirmed:

- Accounting blank-page boilerplate: absent from generated notes.
- Accounting running heading `How Accounting Evolved`: only the legitimate chapter heading remains.
- `Kohler's`: no longer promoted to a heading.
- Accounting liquidity paragraph: emitted in normal sentence order.
- Economy: `M1` through `M4` survive in the relevant money-supply text.
- Industrial Disputes Act: no numeric central section is left under a `STATE AMENDMENT` heading in the generated JSON hierarchy.
- Constitution: the known false side-by-side/table prose scrambling pattern is absent.

## Validation performed

- `python -m py_compile stack-highlights recall-sheet notes` — passed.
- `bash -n md-to-pdf` — passed.
- Full `stack-highlights` regression runs — completed on all six PDFs.

The repository's `Makefile` references `tests/test_units.py` and `tests/run_golden.py`, but those test files were not included in the supplied ZIP, so that pre-existing test target cannot be executed from this package.

A full notes/recall PDF rendering smoke test reached the PDF-rendering stage, but this runtime does not have the configured `Latin Modern Roman` font. Extraction and JSON/Markdown generation succeeded; the font dependency is unrelated to the extractor changes and was not changed here.

## Files changed

The functional changes are in `stack-highlights`. A unified diff against the supplied version is included at:

`regression-results/stack-highlights.diff`

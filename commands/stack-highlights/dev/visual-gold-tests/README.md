> **Read with caveats:** the scores below were recorded with the original single-file script on a
> machine whose PyMuPDF version was not recorded, and the Modern India failures come from the
> benchmark method rather than lost highlights. See "Quick verification" in the package `README.md`.
> A revision of the method and of `ISSUES_FINAL_SCRIPT.md` is pending.

# Independent Visual-Gold Test Suite — 180 Pages

This suite is intentionally independent from `stack-highlights`' own tests. The source of truth is the **rendered PDF page and its visible highlight**, not extractor output.

## Corpus

- 6 PDFs
- **180 unique highlighted pages** total
- 30 pages per PDF
- Original suite: 60 pages (10/PDF)
- Added in this expansion: **120 new pages (20/PDF)**
- Old/new overlap: **0 pages**
- Highlight-density mix: **107 medium + 73 high**

`images/` contains all **180 full-page PNGs**. `focus_annotated/` contains the corresponding close-up visual references.

## Gold authoring

All 180 cases have `visually_verified: true`. The expected highlighted text and semantic target were reviewed against the rendered page/focus images. The PDF text layer was used only to transcribe the visually identified text accurately; extractor output was not used to create or revise gold answers.

The 120 added cases are also available separately in `gold_additional_120.json` and `selection_additional_120.json`.

## Profiles

The same five black-box profiles are retained:

1. `default_structured`
2. `highlight_exact_flat`
3. `safe_sentence_flat`
4. `clause_structured`
5. `window12_flat`

Total final comparisons: **180 × 5 = 900**.

## Final benchmark against the current fixed script

Overall: **91.06%** across **900** comparisons.

- Default structured: **91.01%**
- Exact highlight flat: **97.2%**
- Safe sentence flat: **91.39%**
- Clause structured: **87.04%**
- 12-word window flat: **88.68%**

Exact-highlight preservation passes **175/180** visual cases. The remaining five source pages are documented in `ISSUES_FINAL_SCRIPT.md`.

## Running

```bash
python run_visual_gold_tests.py \
  --script /path/to/stack-highlights \
  --pdf-root /path/to/folder-containing-the-6-pdfs \
  --out-dir results
```

The pytest wrapper contains **900 parametrized cases**:

```bash
STACK_HIGHLIGHTS_BIN=/path/to/stack-highlights \
VISUAL_GOLD_PDF_ROOT=/path/to/pdfs \
pytest -q test_visual_gold.py
```

The default pytest threshold is 85. This is intentionally strict: a benchmark run is expected to fail tests while known extraction issues remain.

## Important files

- `gold_cases.json` — final 180-case visual ground truth
- `gold_additional_120.json` — only the new 120 cases
- `selection.json` — final 180-page selection metadata
- `selection_additional_120.json` — new 120-page selection metadata
- `images/` — 180 full-page PNGs
- `focus_annotated/` — 180 annotated focus crops
- `run_visual_gold_tests.py` — tolerant black-box scorer
- `test_visual_gold.py` — 900-case pytest wrapper
- `benchmark_final_180/` — final current-script results
- `ISSUES_FINAL_SCRIPT.md` — issue triage from the final run
- `SUITE_INTEGRITY.json` — uniqueness/count checks

## Principle

Minor Markdown/layout differences are acceptable. Missing highlighted information, wrong annotation attachment, reordered meaning, and unrelated text attachment are not.

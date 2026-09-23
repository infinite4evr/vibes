# Complete Highlight Notes Package

This package combines the current fixed extraction toolchain and the independent 180-page visual-gold test suite.

## fixed-toolchain/
Current fixed application code:
- `stack-highlights` — fixed highlight/context extractor
- `notes` — pipeline wrapper
- `recall-sheet` — recall-sheet generator
- `md-to-pdf` — Markdown-to-PDF wrapper
- `Makefile`, templates/config examples, README
- `FIX_REPORT.md`, `fixes.patch`, regression logs and diff

## visual-gold-tests/
Independent visual-first regression suite:
- 180 unique highlighted pages (30 per PDF)
- full-page PNGs and annotated focus images
- `gold_cases.json` — visually authored ground truth
- `gold_additional_120.json` — the second 120 cases
- `run_visual_gold_tests.py` — black-box benchmark runner
- `test_visual_gold.py` — pytest suite (900 parameterized comparisons)
- five parameter profiles
- final benchmark raw outputs and reports
- `ISSUES_FINAL_SCRIPT.md`, `SUITE_INTEGRITY.json`, manifests and contact sheets
- `tested_stack-highlights` — exact extractor copy used by the final benchmark

## original-code/
- `files.zip` — the original code archive supplied before the fixes, retained for comparison/reference.

## test-build-tools/
Helper scripts used while constructing/extending the independent visual test corpus.

## stack-highlights-fixed
Convenience standalone copy of the current fixed extractor.

The six source PDFs are not duplicated into this package; the test suite references the original filenames. This keeps the package focused on code, tests, visual fixtures, and benchmark artifacts.

# Restored built-in tests

The original `files.zip` Makefile and README refer to a `tests/` directory, but that directory was not
present in the uploaded archive. The final package restores that safety net under `toolchain/tests/`.

It contains:

- 9 unit tests for sentence segmentation, Markdown list-marker protection, amendment-bracket stripping,
  line-break hyphen handling, and Markdown run tokenization.
- 2 tiny deterministic highlighted PDF fixtures generated with PyMuPDF.
- 7 byte-for-byte golden outputs spanning default extraction, exact-highlight flat mode,
  dehyphenation, JSON output, and legal/clause extraction.
- `run_golden.py --update` for deliberate golden refreshes.

`make -C toolchain test` is green in the packaged environment.

Update: the harness has since been extended (12 unit tests, 25 golden cases on 7
fixtures, and a real-book coverage check). See `docs/TEST_STATUS.md` and `docs/CHANGES.md`.

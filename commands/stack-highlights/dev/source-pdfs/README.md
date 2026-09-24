# source-pdfs/

Put **Test-Merged-All.pdf** here. It is not in git (266 MB, and it contains
copyrighted books); every other file in this folder is ignored too.

| | |
|---|---|
| File | `Test-Merged-All.pdf` (9,916 pages, 16 documents, 14 highlighted books) |
| Size | 266,319,940 bytes |
| SHA-256 | `a478af926ef4b96de0c2840a3a2afad27fedc2e6dbecfa4946c841ebbe4feba9` |

Check a copy with `python3 dev/verify_package.py --pdf` (from `stack-highlights/`).

Instead of copying it here you can set `HIGHLIGHT_PDFS=/folder/with/it`, or pass
`--pdf FILE_OR_DIR` to `tests/run_coverage.py`. Without the PDF, `make coverage`
and `make visual` print `SKIP` and pass.

#!/usr/bin/env python3
"""Real-book coverage check: no highlight in your books may go missing.

Uses the test PDF Test-Merged-All.pdf (9,916 pages, 16 documents). It is split
back into its 14 highlighted books (see merged_books.py) and stack-highlights
(default settings) is run on each book on its own, then compared with the
recorded baseline, coverage_baseline.json:

  FAIL  if a book now has a different number of highlights detected
        (the detection itself changed -- review, then --update);
  FAIL  if fewer highlights are placed in the notes than before;
  FAIL  if a highlight is missing that was not missing before, even when the
        total is unchanged (one miss fixed, a different one introduced);
  FAIL  if the "Check in book" list does not name exactly the missing ones.
  PASS  otherwise. If more highlights are placed than before, it says so --
        run with --update to record the improvement.

Page numbers in the baseline and in the messages are pages of the merged PDF.

Where the PDF is: --pdf FILE_OR_DIR, else $HIGHLIGHT_PDFS/Test-Merged-All.pdf,
else dev/source-pdfs/Test-Merged-All.pdf. Without it the check is skipped
(exit 0) so `make test` still works on a machine without the books. The split
books are kept in tests/.tmp/merged-books (reused while the PDF is unchanged;
`make clean` removes them). About 3-4 minutes with 4 books at a time.

Output depends a little on the PyMuPDF version; the baseline records the
version it was made with and a different version is reported (not failed).

    python3 tests/run_coverage.py              # check
    python3 tests/run_coverage.py --update     # record the current results
    python3 tests/run_coverage.py --books act_tu,constitution   # just some books
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
sys.path.insert(0, str(TESTS))
import merged_books as mb  # noqa: E402

BASELINE = TESTS / 'coverage_baseline.json'
WORK = TESTS / '.tmp' / 'merged-books'


def unplaced(data):
    return [[int(c['page']), c.get('reason', '')] for c in data.get('check_in_book', []) or []
            if isinstance(c, dict)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--pdf', help='the merged PDF, or the folder holding it '
                                  '(default: $HIGHLIGHT_PDFS or dev/source-pdfs)')
    ap.add_argument('--update', action='store_true', help='record the current results as the new baseline')
    ap.add_argument('--books', help='comma-separated book keys to check (default: all 14)')
    ap.add_argument('--jobs', type=int, help='books run at the same time (default: up to 4)')
    ns = ap.parse_args()

    base = json.loads(BASELINE.read_text(encoding='utf-8'))
    pdf = mb.find_pdf(ns.pdf)
    if not pdf:
        print(f'SKIP real-book coverage: {mb.PDF_NAME} not found\n'
              f'     (put it in dev/source-pdfs, set HIGHLIGHT_PDFS=/folder/with/it, or pass --pdf)')
        return 0
    keys = [k.strip() for k in ns.books.split(',')] if ns.books else [b[0] for b in mb.BOOKS]
    unknown = [k for k in keys if k not in {b[0] for b in mb.BOOKS}]
    if unknown:
        print(f'unknown book key(s): {", ".join(unknown)}; known: {", ".join(b[0] for b in mb.BOOKS)}'); return 2
    if ns.update and ns.books:
        print('--update needs every book: leave out --books'); return 2
    have = mb.pymupdf_version()
    if have != base.get('pymupdf'):
        print(f'note: baseline was recorded with PyMuPDF {base.get("pymupdf")}, this machine has {have}; '
              f'small differences in the notes are possible')

    print(f'real-book coverage on {pdf} ({len(keys)} book(s))', flush=True)
    res = mb.run_books(pdf, WORK, keys, ns.jobs)
    failed, results = 0, {}
    for key, title, a, b in mb.BOOKS:
        if key not in res:
            continue
        r = res[key]; want = base['books'].get(key) or {}
        if r['error']:
            print(f'FAIL {key}: {r["error"]}'); failed += 1; continue
        got = {'title': title, 'pages': [a, b], 'found': r['found'], 'placed': r['placed'],
               'unplaced': unplaced(r['data'])}
        results[key] = got
        problems = []
        if not want.get('found'):
            print(f'NEW  {key}: {got["placed"]}/{got["found"]} placed (pp. {a}-{b}) -- not in the baseline yet')
            continue
        if got['found'] != want['found']:
            problems.append(f'{got["found"]} highlights detected, baseline {want["found"]} '
                            f'(detection changed -- review, then --update)')
        if got['placed'] < want['placed']:
            problems.append(f'only {got["placed"]} placed, baseline {want["placed"]}')
        new_misses = [u for u in got['unplaced'] if u not in want['unplaced']]
        if new_misses:
            problems.append('newly missing: ' + ', '.join(f'p. {p} ({why})' for p, why in new_misses[:10])
                            + (' ...' if len(new_misses) > 10 else ''))
        if len(got['unplaced']) != got['found'] - got['placed']:
            problems.append(f'"Check in book" names {len(got["unplaced"])} highlight(s), '
                            f'coverage line says {got["found"] - got["placed"]}')
        line = f'{got["placed"]}/{got["found"]} placed (pp. {a}-{b}, {r["seconds"]:.0f}s)'
        if problems:
            failed += 1
            print(f'FAIL {key}: {line}')
            for p in problems:
                print(f'       {p}')
        else:
            better = got['placed'] > want['placed']
            print(f'PASS {key}: {line}' + ('  -- more than the baseline; run with --update to record it' if better else ''))

    total_f = sum(r['found'] for r in results.values())
    total_p = sum(r['placed'] for r in results.values())
    print(f'real-book coverage: {total_p} of {total_f} highlights placed across {len(results)} book(s); '
          f'{"FAILED" if failed else "OK"}')

    if ns.update:
        if failed or len(results) != len(mb.BOOKS):
            print('not updating: every book must run without an extractor error'); return 1
        new = {'pymupdf': have, 'settings': 'default', 'pdf': mb.PDF_NAME, 'pdf_pages': mb.PDF_PAGES,
               'pages': 'merged-PDF page numbers', 'books': results}
        BASELINE.write_text(json.dumps(new, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        print(f'updated {BASELINE.relative_to(ROOT)}')
        return 0
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())

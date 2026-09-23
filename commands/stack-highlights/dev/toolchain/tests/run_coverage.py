#!/usr/bin/env python3
"""Real-book coverage check: no highlight in your books may go missing.

Runs stack-highlights (default settings) on each book listed in
coverage_baseline.json and compares with the recorded baseline:

  FAIL  if a book now has a different number of highlights detected
        (the detection itself changed -- review, then --update);
  FAIL  if fewer highlights are placed in the notes than before;
  FAIL  if a highlight is missing that was not missing before, even when the
        total is unchanged (one miss fixed, a different one introduced);
  FAIL  if the "Check in book" list does not name exactly the missing ones.
  PASS  otherwise. If more highlights are placed than before, it says so --
        run with --update to record the improvement.

Where the PDFs are: --pdf-root DIR, else $HIGHLIGHT_PDFS, else ../source-pdfs
next to the toolchain folder (the layout of the full package). Books that are
not found are skipped and reported; if none are found the check is skipped
(exit 0) so `make test` still works on a machine without the books.

Output depends a little on the PyMuPDF version; the baseline records the
version it was made with and a different version is reported (not failed).

    python3 tests/run_coverage.py              # check
    python3 tests/run_coverage.py --update     # record the current results
"""
from __future__ import annotations
import argparse, json, os, re, subprocess, tempfile, time
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
SCRIPT = ROOT / 'stack-highlights'
BASELINE = TESTS / 'coverage_baseline.json'
COVERAGE_RE = re.compile(r'(\d+) mark\(s\)[^\n]*?, (\d+) placed in notes')


def pymupdf_version():
    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf
        except ImportError:
            return 'not installed'
    return getattr(pymupdf, 'VersionBind', '?')


def pdf_root(arg):
    if arg:
        return Path(arg).expanduser()
    if os.environ.get('HIGHLIGHT_PDFS'):
        return Path(os.environ['HIGHLIGHT_PDFS']).expanduser()
    return ROOT.parent / 'source-pdfs'


def run_book(pdf, tmp):
    out = Path(tmp) / (pdf.stem + '.json')
    cmd = [str(SCRIPT), str(pdf), '--format', 'json', '--out', str(out), '--no-progress']
    t0 = time.time()
    cp = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    secs = time.time() - t0
    m = COVERAGE_RE.search(cp.stderr)
    if cp.returncode or not m:
        return None, f'extractor failed (exit {cp.returncode}):\n{cp.stderr.strip()}', secs
    found, placed = int(m.group(1)), int(m.group(2))
    listed = []
    if out.exists():
        data = json.loads(out.read_text(encoding='utf-8'))
        listed = [[c['page'], c['reason']] for c in data.get('check_in_book', [])]
    elif placed:
        return None, 'extractor wrote no output file', secs
    return {'found': found, 'placed': placed, 'unplaced': listed}, None, secs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--pdf-root', help='folder with the books (default: $HIGHLIGHT_PDFS or ../source-pdfs)')
    ap.add_argument('--update', action='store_true', help='record the current results as the new baseline')
    ns = ap.parse_args()

    base = json.loads(BASELINE.read_text(encoding='utf-8'))
    root = pdf_root(ns.pdf_root)
    books = [b for b in base['books'] if (root / b).exists()]
    if not books:
        print(f'SKIP real-book coverage: none of the {len(base["books"])} books found in {root}\n'
              f'     (set HIGHLIGHT_PDFS=/folder/with/the/books or pass --pdf-root)')
        return 0
    have = pymupdf_version()
    if have != base.get('pymupdf'):
        print(f'note: baseline was recorded with PyMuPDF {base.get("pymupdf")}, this machine has {have}; '
              f'small differences in the notes are possible')

    failed, improved, results = 0, 0, {}
    with tempfile.TemporaryDirectory() as tmp:
        for name in base['books']:
            if name not in books:
                print(f'SKIP {name}: not found in {root}')
                continue
            want = base['books'][name]
            got, err, secs = run_book(root / name, tmp)
            if err:
                print(f'FAIL {name}: {err}'); failed += 1; continue
            results[name] = got
            problems = []
            if got['found'] != want['found']:
                problems.append(f'{got["found"]} highlights detected, baseline {want["found"]} '
                                f'(detection changed -- review, then --update)')
            if got['placed'] < want['placed']:
                problems.append(f'only {got["placed"]} placed, baseline {want["placed"]}')
            new_misses = [u for u in got['unplaced'] if u not in want['unplaced']]
            if new_misses:
                problems.append('newly missing: ' + ', '.join(f'p. {p} ({r})' for p, r in new_misses[:10])
                                + (' ...' if len(new_misses) > 10 else ''))
            if len(got['unplaced']) != got['found'] - got['placed']:
                problems.append(f'"Check in book" names {len(got["unplaced"])} highlight(s), '
                                f'coverage line says {got["found"] - got["placed"]}')
            line = f'{got["placed"]}/{got["found"]} placed ({secs:.0f}s)'
            if problems:
                failed += 1
                print(f'FAIL {name}: {line}')
                for p in problems:
                    print(f'       {p}')
            else:
                better = got['placed'] > want['placed']
                improved += better
                print(f'PASS {name}: {line}' + ('  -- more than the baseline; run with --update to record it' if better else ''))

    total_f = sum(r['found'] for r in results.values())
    total_p = sum(r['placed'] for r in results.values())
    print(f'real-book coverage: {total_p} of {total_f} highlights placed across {len(results)} book(s); '
          f'{"FAILED" if failed else "OK"}')

    if ns.update:
        if len(results) != len(base['books']):
            print('not updating: every book in the baseline must be present for --update'); return 1
        new = {'pymupdf': have, 'settings': 'default', 'books': results}
        BASELINE.write_text(json.dumps(new, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(f'updated {BASELINE.relative_to(ROOT)}')
        return 0
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())

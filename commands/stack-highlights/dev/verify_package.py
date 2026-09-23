#!/usr/bin/env python3
"""Check the development archive: required files, test-suite counts, checksums.

    python3 verify_package.py            # check (exit 1 on any problem)
    python3 verify_package.py --pdf      # also check source-pdfs/Test-Merged-All.pdf, if present
    python3 verify_package.py --write    # re-record SHA256SUMS.txt after a deliberate change

SHA256SUMS.txt covers the frozen, reviewed material of the 500-page visual test (images, gold
cases, verdicts, transcriptions, judged outputs, report). A change there means the recorded
review no longer matches its files.
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path

sys.dont_write_bytecode = True
DEV = Path(__file__).resolve().parent
TOOL = DEV.parent
SUITE = DEV / 'visual-tests-500'
SUMS = DEV / 'SHA256SUMS.txt'
PDF_SHA = 'a478af926ef4b96de0c2840a3a2afad27fedc2e6dbecfa4946c841ebbe4feba9'
PDF_SIZE = 266319940
FROZEN = ['gold_cases.json', 'review_log.jsonl', 'marks_raw.json', 'gold_fixes.jsonl', 'selection.json',
          'page_features.json', 'duplicates.json', 'image_names.json', 'outputs/default_books.json',
          'outputs/default_merged_page_ranges.json', 'REPORT.md', 'STATUS.md']


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def frozen_files():
    files = [SUITE / f for f in FROZEN]
    files += sorted((SUITE / 'images').glob('*.png')) + sorted((SUITE / 'report_images').glob('*.png'))
    return files


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--pdf', action='store_true', help='also check the merged PDF if it is present')
    ap.add_argument('--write', action='store_true', help='re-record SHA256SUMS.txt')
    ns = ap.parse_args()
    errors = []

    def need(p):
        if not p.exists():
            errors.append(f'missing: {p.relative_to(TOOL.parent)}')
        return p

    for rel in ['stack-highlights', 'Makefile', 'README.md', 'requirements.txt',
                'tests/test_units.py', 'tests/run_golden.py', 'tests/run_coverage.py',
                'tests/merged_books.py', 'tests/coverage_baseline.json', 'tests/test_pdf_safety.py']:
        need(TOOL / rel)
    for rel in ['README.md', 'REPORT.md', 'FINDINGS.md', 'STATUS.md', 'run_visual_tests.py',
                'test_visual_500.py', 'build_gold_cases.py', 'report_assets.py', 'automatch.py',
                'sources.py', 'status.py', 'record.py'] + FROZEN:
        need(SUITE / rel)
    need(DEV / 'source-pdfs' / 'README.md')

    # the visual suite: 500 pages, 3,725 highlights, one image per page, every mark judged
    gp = SUITE / 'gold_cases.json'
    if gp.exists():
        g = json.loads(gp.read_text(encoding='utf-8'))
        pages = g.get('pages', {})
        marks = [m for p in pages.values() for m in p['marks']]
        if len(pages) != 500: errors.append(f'gold cases: expected 500 pages, got {len(pages)}')
        if len(marks) != 3725: errors.append(f'gold cases: expected 3725 highlights, got {len(marks)}')
        if any(m.get('verdict') not in ('P', 'M', 'F', 'X') for m in marks):
            errors.append('gold cases: a highlight without a verdict')
        for pid, p in pages.items():
            if not (SUITE / 'images' / p['image']).exists():
                errors.append(f'gold cases: image missing for {pid}: {p["image"]}')
    n_img = len(list((SUITE / 'images').glob('P*.png')))
    if n_img != 500: errors.append(f'reference images: expected 500, got {n_img}')
    n_rep = len(list((SUITE / 'report_images').glob('F*.png')))
    if n_rep != 10: errors.append(f'report images: expected 10, got {n_rep}')

    # coverage baseline: the 14 books of the merged PDF
    cb = TOOL / 'tests' / 'coverage_baseline.json'
    if cb.exists():
        b = json.loads(cb.read_text(encoding='utf-8'))
        if b.get('pdf') != 'Test-Merged-All.pdf' or len(b.get('books', {})) != 14:
            errors.append('coverage baseline: expected the 14 books of Test-Merged-All.pdf')

    # checksums of the frozen review material
    if ns.write:
        lines = [f'{sha(p)}  {p.relative_to(DEV)}' for p in frozen_files() if p.exists()]
        SUMS.write_text('\n'.join(lines) + '\n')
        print(f'wrote {SUMS.name}: {len(lines)} files')
    elif SUMS.exists():
        bad = 0
        for line in SUMS.read_text().splitlines():
            h, rel = line.split('  ', 1)
            p = DEV / rel
            if not p.exists():
                errors.append(f'checksum: missing {rel}'); bad += 1
            elif sha(p) != h:
                errors.append(f'checksum: changed {rel}'); bad += 1
        print(f'checksums: {len(SUMS.read_text().splitlines()) - bad} files unchanged')
    else:
        errors.append('SHA256SUMS.txt missing (run with --write once)')

    if ns.pdf:
        pdf = DEV / 'source-pdfs' / 'Test-Merged-All.pdf'
        if not pdf.exists():
            print('merged PDF: not present (skipped)')
        elif pdf.stat().st_size != PDF_SIZE or sha(pdf) != PDF_SHA:
            errors.append('merged PDF: not the verified Test-Merged-All.pdf (size or SHA-256 differs)')
        else:
            print('merged PDF: verified copy')

    for e in errors:
        print('ERROR', e)
    print('package: ' + ('FAILED' if errors else 'OK'))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())

#!/usr/bin/env python3
"""Split Test-Merged-All.pdf back into its source books (annotations kept) and run
stack-highlights on each book as a standalone PDF, the way it is used day to day.
Page numbers in the outputs are shifted back to merged-PDF page numbers, and the
per-book outputs are merged into one JSON (same shape as a normal run).

Why: stack-highlights measures body text size and running headers over the whole
file. In the 9,916-page merge those statistics are dominated by other books, so
some books come out with paragraphs as headings and running headers kept. Run
book by book, the same pages come out right (see REPORT, finding 3).

usage: run_books.py SCRIPT MERGED_PDF WORKDIR NAME [extra stack-highlights args...]
"""
import json, subprocess, sys, time
from pathlib import Path
import pymupdf
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from sources import SOURCES

def main():
    script, merged, work, name = sys.argv[1:5]; extra = sys.argv[5:]
    work = Path(work); (work / 'books').mkdir(parents=True, exist_ok=True)
    feat = json.load(open(HERE / 'page_features.json'))
    marked = {f['source'] for f in feat if f['n_marks']}
    src = None
    out_all = {'highlights': 0, 'entries': [], 'check_in_book': [], 'runs': []}
    for key, title, a, b in SOURCES:
        if key not in marked: continue
        book = work / 'books' / f'{key}.pdf'
        if not book.exists():
            src = src or pymupdf.open(merged)
            d = pymupdf.open(); d.insert_pdf(src, from_page=a - 1, to_page=b - 1, annots=True)
            d.save(book, garbage=3, deflate=True); d.close()
        out = work / f'{name}__{key}.json'
        if not out.exists():
            t = time.time()
            cp = subprocess.run([script, str(book), '--format', 'json', '--out', str(out), '--no-progress'] + extra,
                                capture_output=True, text=True)
            (work / f'{name}__{key}.log').write_text(cp.stdout + cp.stderr + f'\nexit={cp.returncode} seconds={time.time()-t:.0f}\n')
            if cp.returncode != 0:
                print('FAILED', key, flush=True); continue
        d = json.load(open(out)); off = a - 1
        for e in d.get('entries', []):
            e['page'] = int(e.get('page', 0)) + off; e['source'] = key
        for c in d.get('check_in_book', []) or []:
            if isinstance(c, dict) and 'page' in c: c['page'] = int(c['page']) + off
        out_all['highlights'] += d.get('highlights', 0)
        out_all['entries'] += d.get('entries', [])
        out_all['check_in_book'] += d.get('check_in_book', []) or []
        out_all['runs'].append({'source': key, 'merged_pages': f'{a}-{b}'})
        print('done', key, flush=True)
    json.dump(out_all, open(work / f'{name}.json', 'w'), ensure_ascii=False)
    print('merged', len(out_all['entries']), 'entries', flush=True)

if __name__ == '__main__': main()

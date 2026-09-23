#!/usr/bin/env python3
"""Run stack-highlights on each source of the merged PDF (its page range), one
process per source, and merge the JSON outputs into one file.

Why per source: on a 4 GB machine a single run over all 9,916 pages is killed
for lack of memory (see REPORT). Per-source runs also match everyday use (one
book at a time). Joins across pages still work inside each source.

usage: run_sources.py SCRIPT PDF OUTDIR PROFILE_NAME [extra stack-highlights args...]
"""
import json, subprocess, sys, time, resource, os
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from sources import SOURCES

def main():
    script, pdf, outdir, name = sys.argv[1:5]; extra = sys.argv[5:]
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    feat = json.load(open(HERE / 'page_features.json'))
    marked = {f['source'] for f in feat if f['n_marks']}
    merged = {'highlights': 0, 'entries': [], 'check_in_book': [], 'runs': []}
    for key, title, a, b in SOURCES:
        if key not in marked: continue
        out = outdir / f'{name}__{key}.json'
        if not out.exists():
            t = time.time()
            cp = subprocess.run([script, pdf, '--pages', f'{a}-{b}', '--format', 'json', '--out', str(out),
                                 '--no-progress'] + extra, capture_output=True, text=True)
            rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
            (outdir / f'{name}__{key}.log').write_text(cp.stdout + cp.stderr +
                f'\nexit={cp.returncode} seconds={time.time()-t:.0f} peak_rss_so_far_kb={rss}\n')
            if cp.returncode != 0:
                print('FAILED', key, cp.returncode, flush=True); continue
        d = json.load(open(out))
        merged['highlights'] += d.get('highlights', 0)
        merged['entries'] += d.get('entries', [])
        merged['check_in_book'] += d.get('check_in_book', []) or []
        merged['runs'].append({'source': key, 'pages': f'{a}-{b}', 'log': (outdir / f'{name}__{key}.log').read_text().strip().splitlines()[-1]})
        print('done', key, flush=True)
    json.dump(merged, open(outdir / f'{name}.json', 'w'), ensure_ascii=False)
    print('merged', len(merged['entries']), 'entries', flush=True)

if __name__ == '__main__': main()

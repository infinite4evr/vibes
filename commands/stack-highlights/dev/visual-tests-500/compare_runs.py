#!/usr/bin/env python3
"""For the given case ids, show which marks come out differently in two outputs
(entry kind, text or heading path of the entry that holds the mark).
usage: compare_runs.py A.json B.json P001-P082"""
import json, sys, re
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import automatch as am
from review_print import ids_from
A = json.load(open(sys.argv[1])); B = json.load(open(sys.argv[2]))
marks = json.load(open(HERE / 'marks_raw.json'))
ia, ib = am.index_entries(A), am.index_entries(B); ca, cb = am.check_list(A), am.check_list(B)
def sig(d, r):
    if r.get('entry') is None: return (r['status'],)
    e = d['entries'][r['entry']]
    return (r['status'], e.get('kind'), am.entry_text(e), tuple(h.get('text', '') for h in e.get('headings', []) or []))
diff_pages = []
for pid in ids_from(sys.argv[3:]):
    rec = marks[pid]; nd = []
    for m in rec['marks']:
        ra = am.match_mark(m, rec['page'], ia, ca); rb = am.match_mark(m, rec['page'], ib, cb)
        sa, sb = sig(A, ra), sig(B, rb)
        if sa[:3] != sb[:3]: nd.append((m['n'], 'text'))
        elif sa != sb: nd.append((m['n'], 'heads'))
    if nd: diff_pages.append((pid, nd))
for pid, nd in diff_pages:
    print(pid, ' '.join(f'{n}:{k}' for n, k in nd))
print('pages with differences:', len(diff_pages))

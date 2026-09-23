#!/usr/bin/env python3
"""Pick the 500 visual-test pages from Test-Merged-All.pdf (reproducible).

Only pages carrying at least one highlight/underline are eligible (a page with
no marks has nothing to test). Pages are allocated to the 14 sources that have
marks in proportion to (marked pages)^0.8, with a floor of min(12, marked pages)
so small sources are still represented. Inside a source the marked pages are
put in page order, cut into k equal-size bins, and one page is drawn at random
from each bin: random, but spread over the whole book.
"""
import json, random, collections, math, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from sources import SOURCES, act_of

SEED = 20260923
TOTAL = 500
feat = json.load(open(HERE / 'page_features.json'))
by = collections.defaultdict(list)
for f in feat:
    if f['n_marks']:
        by[f['source']].append(f)
keys = [k for k, *_ in SOURCES if by.get(k)]
n = {k: len(by[k]) for k in keys}
floor = {k: min(12, n[k]) for k in keys}
w = {k: n[k] ** 0.8 for k in keys}
alloc = {k: max(floor[k], round(TOTAL * w[k] / sum(w.values()))) for k in keys}
# adjust to exactly TOTAL, taking from / giving to the largest sources
while sum(alloc.values()) != TOTAL:
    diff = TOTAL - sum(alloc.values())
    k = max((k for k in keys if (diff > 0 and alloc[k] < n[k]) or (diff < 0 and alloc[k] > floor[k])),
            key=lambda k: n[k] / alloc[k] if diff > 0 else alloc[k] / n[k])
    alloc[k] += 1 if diff > 0 else -1
rng = random.Random(SEED)
chosen = []
for k in keys:
    pages = sorted(by[k], key=lambda f: f['page'])
    kk = alloc[k]
    for b in range(kk):
        lo = math.floor(b * len(pages) / kk); hi = math.floor((b + 1) * len(pages) / kk)
        f = rng.choice(pages[lo:hi])
        chosen.append(dict(f, act=act_of(f['page'])))
chosen.sort(key=lambda f: f['page'])
for i, f in enumerate(chosen, 1):
    f['id'] = f'P{i:03d}'
out = {'seed': SEED, 'total_pages': TOTAL, 'rule': __doc__.strip(),
       'allocation': alloc, 'eligible_pages': n, 'pages': chosen}
json.dump(out, open(HERE / 'selection.json', 'w'), indent=1)
print(json.dumps(alloc), sum(alloc.values()))
print('marks on selected pages:', sum(f['n_marks'] for f in chosen))
print('density:', collections.Counter('low(1-2)' if f['n_marks'] <= 2 else 'medium(3-7)' if f['n_marks'] <= 7 else 'high(8+)' for f in chosen))
print('with underline:', sum(1 for f in chosen if 'Underline' in f['kinds']), ' non-yellow colours:', sum(1 for f in chosen if any('1.0, 1.0, 0.0' not in c for c in f['colors'])))
print('with ink/notes:', sum(1 for f in chosen if f['other']))
print('acts:', collections.Counter(f['act'] for f in chosen if f['act']))

#!/usr/bin/env python3
"""Summarise the visual review so far (review_log.jsonl) -> prints Markdown; `status.py > STATUS.md`."""
import json, collections, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from sources import SOURCES
sel = json.load(open(HERE / 'selection.json'))
last = {}
for l in open(HERE / 'review_log.jsonl'):
    r = json.loads(l); last[r['id']] = r
by = collections.defaultdict(collections.Counter); pages = collections.Counter(); planned = collections.Counter()
for p in sel['pages']: planned[p['source']] += 1
src_of = {p['id']: p['source'] for p in sel['pages']}
fails, minors, notes = [], collections.Counter(), []
for pid, r in sorted(last.items()):
    s = src_of[pid]; pages[s] += 1
    for n, v in r['verdicts'].items():
        by[s][v['v']] += 1
        if v['v'] == 'F': fails.append((pid, r['page'], n, v['why']))
        if v['v'] == 'M': minors[v['why'].split('(')[0].strip()[:70]] += 1
    if r.get('note'): notes.append((pid, r['page'], r['note']))
tot = collections.Counter()
for c in by.values(): tot.update(c)
def pct(c):
    n = sum(c.values()) - c['X']
    return (100 * c['P'] / n if n else 0, 100 * (c['P'] + c['M']) / n if n else 0)
print('# Visual review status\n')
print(f"Pages reviewed: **{len(last)} / {len(sel['pages'])}**; marks judged: **{sum(tot.values())}** "
      f"(P {tot['P']}, M {tot['M']}, F {tot['F']}, X {tot['X']}).\n")
a, b = pct(tot)
print(f"Strict (P only): **{a:.1f}%** · Usable (P + M): **{b:.1f}%**\n")
print('| Source | Pages reviewed / planned | Marks | P | M | F | Strict | Usable |\n|---|---|---|---|---|---|---|---|')
for k, title, a_, b_ in SOURCES:
    if not planned[k]: continue
    c = by[k]; x, y = pct(c)
    print(f"| {title} | {pages[k]} / {planned[k]} | {sum(c.values())} | {c['P']} | {c['M']} | {c['F']} | "
          + (f"{x:.1f}% | {y:.1f}% |" if sum(c.values()) else "– | – |"))
print('\n## Failures (F)\n')
for f in fails: print(f"- {f[0]} (merged p.{f[1]}) mark #{f[2]}: {f[3]}")
print('\n## Minor issues (M), grouped by reason\n')
for k, v in minors.most_common(): print(f"- {v} × {k}")
print('\n## Page notes (S = structure/heading, N = typed note, T = text-layer)\n')
for n in notes:
    if n[2].replace('[verdict unchanged in book run]', '').strip():
        print(f"- {n[0]} (p.{n[1]}): {n[2].replace('[verdict unchanged in book run]', '').strip()}")

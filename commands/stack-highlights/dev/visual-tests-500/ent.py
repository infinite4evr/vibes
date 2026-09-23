#!/usr/bin/env python3
"""Temporary review aid: print full entries (all headings, lines with **marks**). usage: ent.py 3782 3783-3790"""
import json, sys, re
d = json.load(open(__file__.rsplit('/', 1)[0] + '/outputs/default_books.json')); E = d['entries']
ids = []
for a in sys.argv[1:]:
    m = re.fullmatch(r'(\d+)-(\d+)', a); ids += list(range(int(m.group(1)), int(m.group(2)) + 1)) if m else [int(a)]
for i in ids:
    e = E[i]; hs = ' > '.join(h['text'] for h in e.get('headings') or [])
    print(f"E{i} p{e.get('page')} {e.get('kind')} | {hs}")
    for ln in e.get('lines') or []:
        print('   ' + ''.join(('**%s**' % r['text']) if r.get('mark') else r['text'] for r in ln.get('runs', [])))
    for k in e:
        if k not in ('kind', 'headings', 'page', 'page_label', 'lines'): print('   [%s] %s' % (k, json.dumps(e[k], ensure_ascii=False)[:300]))

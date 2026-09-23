#!/usr/bin/env python3
"""Record visual-review verdicts (appends to review_log.jsonl; last entry per page wins).

Input lines (stdin), one per page:
    P001 ok
    P002 ok; 3 M heading level wrong; 5-6 F highlight cut short
    P003 ok; 2 F context from other column | note: two-column page
Marks not named are P. Verdicts:
    P  correct: every marked word is in the notes, in bold, with correct context
    M  minor:   the marked information is right, but layout/structure/context is
                imperfect (heading level, list lead-in, table layout, spacing,
                context a little short or long)
    F  failure: marked words missing, cut or altered; context from the wrong
                place; text order scrambled; garbled characters
    X  cannot be judged (e.g. the mark covers no readable text)
"""
import json, sys, re, datetime, os
from pathlib import Path
HERE = Path(__file__).resolve().parent
marks = json.load(open(HERE / 'marks_raw.json'))
log = HERE / 'review_log.jsonl'
n = 0
for line in sys.stdin:
    line = line.strip()
    if not line or line.startswith('#'): continue
    note = ''
    if '| note:' in line:
        line, note = line.split('| note:', 1); note = note.strip()
    parts = [p.strip() for p in line.split(';')]
    pid, first = parts[0].split(None, 1) if ' ' in parts[0] else (parts[0], 'ok')
    if pid not in marks: raise SystemExit(f'unknown id {pid}')
    nm = len(marks[pid]['marks'])
    v = {str(i): {'v': 'P', 'why': ''} for i in range(1, nm + 1)}
    if first.strip() not in ('ok', ''):
        parts.insert(1, first)
    for p in parts[1:]:
        m = re.match(r'(\d+)(?:-(\d+))?\s+([PMFX])\b\s*(.*)', p)
        if not m:
            m2 = re.match(r'all\s+([PMFX])\b\s*(.*)', p)
            if m2:
                for k in v: v[k] = {'v': m2.group(1), 'why': m2.group(2)}
                continue
            raise SystemExit(f'bad verdict {p!r} in {pid}')
        a = int(m.group(1)); b = int(m.group(2) or a)
        for i in range(a, b + 1):
            if str(i) not in v: raise SystemExit(f'{pid} has no mark {i}')
            v[str(i)] = {'v': m.group(3), 'why': m.group(4)}
    rec = {'id': pid, 'page': marks[pid]['page'], 'verdicts': v, 'note': note, 'run': os.environ.get('VT_RUN', 'books'),
           'reviewed': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')}
    with open(log, 'a') as f: f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    n += 1
done = {}
for l in open(log): r = json.loads(l); done[r['id']] = r
tot = {'P': 0, 'M': 0, 'F': 0, 'X': 0}
for r in done.values():
    for x in r['verdicts'].values(): tot[x['v']] += 1
allm = sum(tot.values())
print(f'recorded {n}; reviewed pages {len(done)}/500; marks {allm}: {tot}; '
      f'strict {100*tot["P"]/max(1,allm-tot["X"]):.1f}%  usable(P+M) {100*(tot["P"]+tot["M"])/max(1,allm-tot["X"]):.1f}%')

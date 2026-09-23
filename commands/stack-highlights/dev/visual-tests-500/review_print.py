#!/usr/bin/env python3
"""Print, for the given case ids, the tool's output next to each mark (review aid).
usage: review_print.py OUTPUT.json P001 P002 ...   (or a range P001-P010)
"""
import json, sys, re
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import automatch as am

def ids_from(args):
    out = []
    for a in args:
        m = re.fullmatch(r'P(\d+)-P?(\d+)', a)
        if m:
            out += [f'P{i:03d}' for i in range(int(m.group(1)), int(m.group(2)) + 1)]
        else:
            out.append(a)
    return out

def short_heads(e, n=2):
    hs = [re.sub(r'\s+', ' ', h.get('text', ''))[:50] for h in e.get('headings', []) or []]
    return ' > '.join(hs[-n:])

def main():
    data = json.load(open(sys.argv[1]))
    marks = json.load(open(HERE / 'marks_raw.json'))
    byp = am.index_entries(data); chk = am.check_list(data)
    entries = data['entries']
    for pid in ids_from(sys.argv[2:]):
        rec = marks[pid]; p = rec['page']
        other = rec['other_annots']
        oth = ', '.join(f"{o['type']}" + (f":{o['content'][:40]!r}" if o['content'] else '') for o in other)
        print(f"=== {pid} p.{p} {rec['source']} {len(rec['marks'])} marks" + (f" | other: {oth}" if oth else ''))
        res = [am.match_mark(m, p, byp, chk) for m in rec['marks']]
        shown = []
        for m, r in zip(rec['marks'], res):
            if r.get('entry') is not None and r['entry'] not in shown: shown.append(r['entry'])
        # entries on this page that carry marks but matched nothing (possible stray bold)
        extra = [e['_i'] for e in byp.get(p, []) if e.get('marks') and e['_i'] not in shown]
        for i in shown + extra:
            e = entries[i]
            tag = 'E%d%s %s' % (i, '' if e.get('page') == p else f"(p{e.get('page')})", e.get('kind'))
            h = short_heads(e)
            txt = am.entry_text(e)
            if e.get('kind') == 'heading' and not txt: txt = '(heading) ' + h; h = ''
            print(f" {tag}{' | ' + h if h else ''}{'  <-- unmatched' if i in extra else ''}")
            print('   ' + txt[:700])
        for m, r in zip(rec['marks'], res):
            k = 'u' if m['kind'] == 'underline' else ('h' if m['kind'] == 'highlight' else m['kind'][:2])
            st = r['status']
            loc = f"E{r['entry']}" if r.get('entry') is not None else ','.join(r.get('check', []) or [])
            col = '' if m['color'] == 'yellow' else ' ' + m['color']
            w = m['words'] if m['words'] else '[chars] ' + m['chars']
            print(f" #{m['n']} {k}{col} {st} {loc}: {w[:160]}")
        pc = [c for c in chk if int(c.get('page', -1)) == p]
        if pc: print(' check-in-book:', '; '.join(f"{c.get('reason')} {c.get('text','')[:40]!r}" for c in pc))

if __name__ == '__main__': main()

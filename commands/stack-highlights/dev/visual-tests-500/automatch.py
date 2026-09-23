#!/usr/bin/env python3
"""Match every transcribed mark (marks_raw.json) to stack-highlights JSON output.

Used twice: during the visual review (to print each page's output next to its
marks) and by the regression runner. A mark is FOUND when its words appear, in
order, inside the bold (marked) runs of one output entry on the same page (or
the page before: a paragraph continued from the previous page keeps the
previous page's number, a known issue).
"""
import json, re, unicodedata, collections, difflib

def norm(s):
    s = unicodedata.normalize('NFKC', s or '').replace('\u00ad', '')
    s = s.replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"')
    return s

def compact(s):
    return re.sub(r'[^0-9a-z]+', '', norm(s).lower())

def toks(s):
    return re.findall(r'[0-9a-z]+', norm(s).lower())

def runs_of(e):
    """(text, is_marked) runs of an entry: its lines, then its subs (list items,
    footnotes, notes), each sub prefixed by its label."""
    out = []
    def add_runs(runs):
        for r in runs or []:
            out.append((r.get('text', ''), bool(r.get('mark'))))
    def add_lines(lines):
        for ln in lines or []:
            if isinstance(ln, dict):
                add_runs(ln.get('runs'))
            out.append(('\n', False))
    def add_subs(subs):
        for sb in subs or []:
            if not isinstance(sb, dict): continue
            if sb.get('label'): out.append(('[' + str(sb['label']) + '] ', False))
            add_runs(sb.get('runs')); add_lines(sb.get('lines'))
            out.append(('\n', False))
            add_subs(sb.get('subs'))
    add_lines(e.get('lines')); add_subs(e.get('subs'))
    return out

def entry_text(e, md=True):
    parts = []
    for t, m in runs_of(e):
        if t == '\n': parts.append(' / '); continue
        parts.append(f'**{t}**' if (m and md and t.strip()) else t)
    s = ''.join(parts).strip(' /')
    s = re.sub(r'\*\*(\s*)\*\*', r'\1', s)
    return re.sub(r'\s+', ' ', s)

def bold_segments(e):
    segs, cur = [], []
    for t, m in runs_of(e):
        if m: cur.append(t)
        elif t.strip() or t == '\n':
            if cur: segs.append(''.join(cur)); cur = []
    if cur: segs.append(''.join(cur))
    return segs

def heading_marks(e):
    # marked headings appear as entries of kind 'heading' whose text is the heading
    return []

def index_entries(data):
    byp = collections.defaultdict(list)
    for i, e in enumerate(data.get('entries', [])):
        e['_i'] = i
        byp[int(e.get('page', -1))].append(e)
    return byp

def entry_all_text(e):
    t = ' '.join(t for t, _ in runs_of(e))
    if not t.strip():
        t = ' '.join(h.get('text', '') for h in e.get('headings', []) or [])
    return t

def entry_mark_texts(e):
    return [compact(m.get('text', '')) for m in e.get('marks', []) or []]

def match_mark(mark, page, byp, check):
    """FOUND: an output mark on this page (or the one before) has the same words.
    PARTIAL: the output mark holds at least half of the words (truncated/merged).
    CHECK_IN_BOOK: listed by the tool as not placed. MISSING: nowhere."""
    g = compact(mark['words']) or compact(mark['chars'])
    if not g:
        return {'status': 'NO_TEXT', 'entry': None}
    cands = byp.get(page, []) + byp.get(page - 1, [])
    found = None; partial = None
    for e in cands:
        for m in entry_mark_texts(e):
            if not m: continue
            if m == g or g in m:
                found = e; break
            if m in g and len(m) >= 0.5 * len(g):
                if partial is None or len(m) > partial[1]: partial = (e, len(m))
            else:
                sm = difflib.SequenceMatcher(None, g, m)
                if sm.ratio() >= 0.8 and (partial is None or sm.ratio() * len(g) > partial[1]):
                    partial = (e, sm.ratio() * len(g))
        if found: break
    if found:
        return {'status': 'FOUND', 'entry': found['_i'], 'entry_page': found.get('page')}
    if partial:
        return {'status': 'PARTIAL', 'entry': partial[0]['_i'], 'entry_page': partial[0].get('page')}
    chk = [c for c in check if int(c.get('page', -1)) == page]
    return {'status': 'CHECK_IN_BOOK' if chk else 'MISSING', 'entry': None,
            'check': [c.get('reason') for c in chk]}

def check_list(data):
    c = data.get('check_in_book') or []
    out = []
    for x in c:
        if isinstance(x, dict): out.append(x)
        elif isinstance(x, (list, tuple)): out.append({'page': x[0], 'reason': x[1] if len(x) > 1 else ''})
    return out

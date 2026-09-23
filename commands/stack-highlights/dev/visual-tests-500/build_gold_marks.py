#!/usr/bin/env python3
"""Transcribe every highlight/underline on the selected pages, independently of
stack-highlights: the characters whose centres fall inside the annotation's
quads, read from the PDF text layer. This is only a transcription aid; the
visual review decides whether it matches what is actually marked on the page.

Writes marks_raw.json: {page: [ {n, kind, color, quads, chars, words, ...} ]}.
"""
import json, re, sys
from pathlib import Path
import pymupdf
HERE = Path(__file__).resolve().parent
PDF = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / 'source-pdfs' / 'Test-Merged-All.pdf'
MARK_TYPES = {8: 'highlight', 9: 'underline', 10: 'squiggly', 11: 'strikeout'}

def color_name(c):
    if not c: return 'none'
    r, g, b = c
    if r > .8 and g > .8 and b < .5: return 'yellow'
    if r > .8 and .4 < g <= .8 and b < .4: return 'orange'
    if r > .8 and g < .4 and b < .4: return 'red'
    if r > .8 and g < .6 and b > .5: return 'pink'
    if g > .6 and r < .6 and b < .6: return 'green'
    if b > .6 and r < .5: return 'blue'
    if r > .4 and b > .5 and g < .4: return 'purple'
    if abs(r-g) < .1 and abs(g-b) < .1: return 'gray'
    return 'other(%.2f,%.2f,%.2f)' % (r, g, b)

def quads_of(a):
    v = a.vertices or []
    qs = []
    for i in range(0, len(v) - 3, 4):
        q = pymupdf.Quad(v[i:i+4]); qs.append(q.rect)
    if not qs: qs = [a.rect]
    return qs

def transcribe(page, rects, kind):
    raw = page.get_text('rawdict', flags=pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_PRESERVE_LIGATURES)
    out_chars = []   # exact characters under the mark
    words = []       # words with at least half of their letters under the mark
    for r in rects:
        rr = pymupdf.Rect(r)
        if kind == 'underline' and rr.height < 5:  # a thin underline sits under the text; grow upward
            rr = pymupdf.Rect(rr.x0, rr.y0 - 8, rr.x1, rr.y1)
        seg_chars = []; seg_words = []
        for b in raw['blocks']:
            for ln in b.get('lines', []):
                lb = pymupdf.Rect(ln['bbox'])
                if not lb.intersects(rr): continue
                cur = []  # (char, inside)
                def flush():
                    if cur:
                        w = ''.join(c for c, _ in cur); ins = sum(1 for _, i in cur if i)
                        if ins and ins * 2 >= len(cur): seg_words.append(w)
                        cur.clear()
                for sp in ln['spans']:
                    for ch in sp['chars']:
                        cb = pymupdf.Rect(ch['bbox']); c = ch['c']
                        cx, cy = (cb.x0 + cb.x1) / 2, (cb.y0 + cb.y1) / 2
                        inside = rr.x0 <= cx <= rr.x1 and rr.y0 - 1 <= cy <= rr.y1 + 1
                        if inside: seg_chars.append(c)
                        if c.isspace(): flush()
                        else: cur.append((c, inside))
                flush()
                seg_chars.append(' ')
        out_chars.append(''.join(seg_chars)); words.extend(seg_words)
    txt = re.sub(r'\s+', ' ', ' '.join(out_chars)).strip()
    return txt, ' '.join(words)

def main():
    sel = json.load(open(HERE / 'selection.json'))
    doc = pymupdf.open(PDF)
    res = {}
    for p in sel['pages']:
        page = doc[p['page'] - 1]
        marks = []
        annots = [a for a in page.annots() if a.type[0] in MARK_TYPES]
        others = [{'type': a.type[1], 'rect': [round(x, 1) for x in a.rect],
                   'content': (a.info.get('content') or '')[:200]} for a in page.annots() if a.type[0] not in MARK_TYPES]
        for a in annots:
            rects = quads_of(a); kind = MARK_TYPES[a.type[0]]
            c = a.colors.get('stroke') or a.colors.get('fill')
            chars, words = transcribe(page, rects, kind)
            marks.append({'kind': kind, 'color': color_name(c),
                          'quads': [[round(x, 1) for x in r] for r in rects],
                          'chars': chars, 'words': words})
        # reading order: top-to-bottom by first quad, columns roughly respected
        W = page.rect.width
        def key(m):
            x0, y0 = m['quads'][0][0], m['quads'][0][1]
            col = 0 if x0 < W * 0.45 else 1
            return (y0 // 4, x0)
        marks.sort(key=key)
        for i, m in enumerate(marks, 1): m['n'] = i
        res[p['id']] = {'page': p['page'], 'source': p['source'], 'marks': marks, 'other_annots': others,
                        'size': [round(page.rect.width), round(page.rect.height)], 'rotation': page.rotation}
    json.dump(res, open(HERE / 'marks_raw.json', 'w'), ensure_ascii=False, indent=0)
    print('pages', len(res), 'marks', sum(len(v['marks']) for v in res.values()),
          'empty transcriptions', sum(1 for v in res.values() for m in v['marks'] if not m['chars']))

if __name__ == '__main__': main()

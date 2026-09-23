#!/usr/bin/env python3
"""Build gold_cases.json from the visual review.

Inputs (all in this folder):
  marks_raw.json          every highlight on the 500 pages: number, kind, colour, position,
                          text-layer transcription
  gold_fixes.jsonl        transcriptions corrected after looking at the image
  review_log.jsonl        the verdicts given by eye (last line per page wins)
  duplicates.json         pages of the merged PDF that are exact repeats of other pages
  outputs/default_books.json   the notes that were judged (stack-highlights, default
                          settings, book by book, page numbers of the merged PDF)

For every page it records the verdict of each highlight, where the highlight was placed
in the judged notes, and the judged notes themselves (the entries around the page), so
run_visual_tests.py can tell whether fresh notes still match what was judged.

Re-run it only after re-checking by eye: when a change to the tool is confirmed as an
improvement, record the new verdicts (record.py), run the tool (run_visual_tests.py
--save NEW.json), then  build_gold_cases.py --output NEW.json.

    python3 build_gold_cases.py [--output JUDGED_OUTPUT.json]
"""
from __future__ import annotations
import argparse, datetime, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_visual_tests as rvt   # noqa: E402
from sources import SOURCES      # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--output', default=str(HERE / 'outputs' / 'default_books.json'),
                    help='the notes that were judged (merged JSON)')
    ap.add_argument('--pymupdf', default='1.28.2', help='PyMuPDF version the judged notes were made with')
    ns = ap.parse_args()

    raw = json.loads((HERE / 'marks_raw.json').read_text(encoding='utf-8'))
    fixes = {}
    for line in (HERE / 'gold_fixes.jsonl').read_text(encoding='utf-8').splitlines():
        if line.strip():
            f = json.loads(line); fixes[(f['id'], int(f['n']))] = f['text']
    review = {}
    for line in (HERE / 'review_log.jsonl').read_text(encoding='utf-8').splitlines():
        if line.strip():
            r = json.loads(line); review[r['id']] = r
    images = json.loads((HERE / 'image_names.json').read_text(encoding='utf-8'))
    dup = json.loads((HERE / 'duplicates.json').read_text(encoding='utf-8'))
    repeat_of = {a: b for a, b in dup['redundant_pairs']}
    repeat_page = {a: p for a, p in dup['repeat_twin_unsampled']}
    first = {k: a for k, t, a, b in SOURCES}
    data = json.loads(Path(ns.output).read_text(encoding='utf-8'))
    byp, check = rvt.index(data)

    missing = [pid for pid in raw if pid not in review]
    if missing:
        raise SystemExit(f'{len(missing)} page(s) have no verdicts yet, e.g. {missing[:5]}')
    pages, counts = {}, {'P': 0, 'M': 0, 'F': 0, 'X': 0}
    for pid in sorted(raw):
        rec, rv = raw[pid], review[pid]
        marks = []
        for m in rec['marks']:
            v = rv['verdicts'].get(str(m['n']))
            if not v:
                raise SystemExit(f'{pid} mark #{m["n"]} has no verdict')
            text = fixes.get((pid, m['n'])) or m['words'] or m['chars']
            marks.append({'n': m['n'], 'kind': m['kind'], 'color': m['color'], 'quads': m['quads'],
                          'text': text, 'verdict': v['v'], 'why': v['why']})
            counts[v['v']] += 1
        res, lines = rvt.page_window(rec['page'], [{'words': m['text'], 'chars': m['text']} for m in marks],
                                     byp, check)
        allent = {e['_i']: e for es in byp.values() for e in es}
        for m, r in zip(marks, res):
            m['placement'] = r['status']
            m['entry_page'] = r.get('entry_page')
            m['entry_line'] = rvt.entry_line(allent[r['entry']]) if r.get('entry') is not None else None
        page = {'id': pid, 'page': rec['page'], 'source': rec['source'],
                'book_page': rec['page'] - first[rec['source']] + 1, 'image': images[pid],
                'size': rec['size'], 'rotation': rec['rotation'],
                'other_annots': [o['type'] + (f": {o['content']}" if o.get('content') else '')
                                 for o in rec['other_annots']],
                'note': rv.get('note', ''), 'marks': marks, 'notes_as_judged': lines}
        if pid in repeat_of:
            page['repeat_of'] = repeat_of[pid]
        elif pid in repeat_page:
            page['repeat_of_page'] = repeat_page[pid]
        pages[pid] = page

    judged = sum(counts.values()) - counts['X']
    gold = {
        'about': 'Visual gold cases for stack-highlights on Test-Merged-All.pdf: every highlight on 500 '
                 'pages judged by eye against the notes (default settings, each book run on its own). '
                 'Verdicts: P correct, M minor (all marked words there, something cosmetic off), '
                 'F failure, X cannot be judged. See README.md and REPORT.md.',
        'pdf': 'Test-Merged-All.pdf', 'pdf_pages': 9916, 'settings': 'default, book by book',
        'pymupdf': ns.pymupdf, 'built': datetime.date.today().isoformat(),
        'judged_output': Path(ns.output).name,
        'totals': {**counts, 'pages': len(pages), 'highlights': sum(counts.values()),
                   'fully_correct_pct': round(100 * counts['P'] / judged, 1),
                   'correct_or_minor_pct': round(100 * (counts['P'] + counts['M']) / judged, 1)},
        'pages': pages,
    }
    (HERE / 'gold_cases.json').write_text(json.dumps(gold, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    placed = sum(1 for p in pages.values() for m in p['marks'] if m['placement'] in rvt.PLACED)
    print(f'gold_cases.json: {len(pages)} pages, {sum(counts.values())} highlights {counts}; '
          f'{placed} matched to an entry of the judged notes')


if __name__ == '__main__':
    main()

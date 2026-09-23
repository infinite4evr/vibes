#!/usr/bin/env python3
"""Automated visual regression test: 500 pages, 3,725 highlights, every one judged by eye.

gold_cases.json holds, for each of the 500 reference pages (images/Pnnn_pXXXX.png):
every highlight on the page (its number on the image, position, verified text), the
verdict it got when the notes were checked by eye (P correct, M minor, F failure,
X cannot be judged) with the reason, whether it was placed in the notes and in
which entry, and the exact text of the notes around that page as they were judged.

This runner makes fresh notes (Test-Merged-All.pdf split into its books, each run
with default settings, like tests/run_coverage.py) and checks every page:

  REGRESSION  a highlight judged P or M is no longer placed in the notes
              (or is now only partly placed)                        -> exit 1
  CHANGED     the notes around the page differ from what was judged: the
              recorded verdicts may no longer hold; look at the page image
              and the diff, then re-record (build_gold_cases.py)    -> exit 0 (1 with --strict)
  IMPROVED    a highlight that was missing (or partly placed) is now placed
  same        notes identical to what was judged: the verdicts stand

It then prints the recorded verdict totals, which are the answer to "how often
is the tool right": they are exact while every page is "same".

    python3 run_visual_tests.py                   # run the tool, then check (about 4 minutes)
    python3 run_visual_tests.py --output FILE     # check an existing output (merged JSON)
    python3 run_visual_tests.py --save FILE       # also keep the fresh merged output
    python3 run_visual_tests.py --strict          # CHANGED pages fail too
    python3 run_visual_tests.py --pages P300-P320 # only some pages

The PDF is found like the coverage test does: --pdf, $HIGHLIGHT_PDFS, dev/source-pdfs.
"""
from __future__ import annotations
import argparse, collections, difflib, json, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL_ROOT = HERE.parent.parent                     # the stack-highlights folder
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(TOOL_ROOT / 'tests'))
import automatch as am                             # noqa: E402
import merged_books as mb                          # noqa: E402

GOLD = HERE / 'gold_cases.json'
WORK = TOOL_ROOT / 'tests' / '.tmp' / 'merged-books'
PLACED = ('FOUND', 'PARTIAL')
RANK = {'FOUND': 3, 'PARTIAL': 2, 'CHECK_IN_BOOK': 1, 'MISSING': 0, 'NO_TEXT': -1}
LOOKBACK = 5   # a paragraph continued from earlier pages keeps its first page's number


# ---------------------------------------------------------------- matching
def index(data):
    byp = am.index_entries(data)
    return byp, am.check_list(data)


def match(mark, page, byp, check):
    """Where did this highlight end up? Like automatch.match_mark, but looks up to
    LOOKBACK pages back for the entry (long paragraphs and definition lists)."""
    r = am.match_mark(mark, page, byp, check)
    if r['status'] in PLACED or r['status'] == 'NO_TEXT':
        return r
    older = {p: byp.get(p, []) for p in range(page - LOOKBACK, page - 1)}
    r2 = am.match_mark(mark, page, older, check) if any(older.values()) else None
    if r2 and r2['status'] in PLACED:
        return r2
    return r


def heads(e):
    return ' > '.join(re.sub(r'\s+', ' ', h.get('text', '')) for h in e.get('headings', []) or [])


def entry_line(e):
    return f"[{e.get('kind', '')} p{e.get('page')}] {heads(e)} | {am.entry_text(e)}"


def page_window(page, marks, byp, check):
    """The notes a reviewer looked at for this page: every entry numbered this page or
    the page before, and every entry a highlight of this page was matched to."""
    ids, lines = set(), []
    res = [match(m, page, byp, check) for m in marks]
    for e in byp.get(page - 1, []) + byp.get(page, []):
        ids.add(e['_i'])
    for r in res:
        if r.get('entry') is not None:
            ids.add(r['entry'])
    allent = {e['_i']: e for es in byp.values() for e in es}
    for i in sorted(ids):
        lines.append(entry_line(allent[i]))
    for c in check:
        if int(c.get('page', -1)) == page:
            lines.append(f"[check in book p{page}] {c.get('reason', '')}")
    return res, lines


# ---------------------------------------------------------------- output
def fresh_output(pdf, jobs=None, log=print):
    res = mb.run_books(pdf, WORK, None, jobs, log)
    out = {'highlights': 0, 'entries': [], 'check_in_book': [], 'runs': []}
    for key, title, a, b in mb.BOOKS:
        r = res[key]
        if r['error']:
            raise SystemExit(f'stack-highlights failed on {key}: {r["error"]}')
        d = r['data']
        out['highlights'] += d.get('highlights', 0) or 0
        out['entries'] += d.get('entries', [])
        out['check_in_book'] += d.get('check_in_book', []) or []
        out['runs'].append({'source': key, 'merged_pages': f'{a}-{b}', 'found': r['found'], 'placed': r['placed']})
    return out


def page_ids(spec, all_ids):
    if not spec:
        return list(all_ids)
    out = []
    for part in spec.split(','):
        m = re.fullmatch(r'P?(\d+)-P?(\d+)', part.strip())
        if m:
            out += [f'P{i:03d}' for i in range(int(m.group(1)), int(m.group(2)) + 1)]
        else:
            out.append(part.strip())
    return [i for i in out if i in all_ids]


# ---------------------------------------------------------------- check
def check_pages(gold, data, ids):
    """Compare an output with the recorded review. Returns one result per page."""
    byp, check = index(data)
    results = []
    for pid in ids:
        pg = gold['pages'][pid]
        marks = [{'words': m['text'], 'chars': m['text']} for m in pg['marks']]
        res, lines = page_window(pg['page'], marks, byp, check)
        page_res = {'id': pid, 'page': pg['page'], 'image': pg['image'], 'regressions': [], 'improved': [],
                    'moved': [], 'changed': lines != pg['notes_as_judged'], 'diff': None}
        allent = {e['_i']: e for es in byp.values() for e in es}
        if page_res['changed']:
            page_res['diff'] = '\n'.join(difflib.unified_diff(pg['notes_as_judged'], lines,
                                                              'as judged', 'now', lineterm='', n=0))
        for m, r in zip(pg['marks'], res):
            was, now = m['placement'], r['status']
            now_line = entry_line(allent[r['entry']]) if r.get('entry') is not None else None
            if now_line != m.get('entry_line'):
                page_res['moved'].append(m['n'])
            if m['verdict'] in ('P', 'M') and RANK.get(now, 0) < RANK.get(was, 0) and was in PLACED:
                page_res['regressions'].append((m['n'], m['verdict'], was, now, m['text'][:70]))
            elif RANK.get(now, 0) > RANK.get(was, 0) and now in PLACED:
                page_res['improved'].append((m['n'], m['verdict'], was, now, m['text'][:70]))
        results.append(page_res)
    return results


def verdict_totals(gold, ids):
    c = collections.Counter(m['verdict'] for pid in ids for m in gold['pages'][pid]['marks'])
    judged = sum(c.values()) - c['X']
    return c, judged


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--pdf', help='the merged PDF or its folder (default: $HIGHLIGHT_PDFS or dev/source-pdfs)')
    ap.add_argument('--output', help='check this merged JSON output instead of running the tool')
    ap.add_argument('--save', help='write the fresh merged output here')
    ap.add_argument('--pages', help='only these pages, e.g. P001-P050,P300')
    ap.add_argument('--strict', action='store_true', help='CHANGED pages fail too')
    ap.add_argument('--jobs', type=int, help='books run at the same time (default: up to 4)')
    ap.add_argument('--show', type=int, default=10, help='how many changed pages to show in full (default 10)')
    ns = ap.parse_args(argv)

    gold = json.loads(GOLD.read_text(encoding='utf-8'))
    ids = page_ids(ns.pages, gold['pages'])
    if ns.output:
        data = json.loads(Path(ns.output).read_text(encoding='utf-8'))
        print(f'checking {ns.output}')
    else:
        pdf = mb.find_pdf(ns.pdf)
        if not pdf:
            print(f'SKIP visual test: {mb.PDF_NAME} not found '
                  f'(put it in dev/source-pdfs, set HIGHLIGHT_PDFS, or pass --pdf)')
            return 0
        have = mb.pymupdf_version()
        if have != gold['pymupdf']:
            print(f'note: the review was done with PyMuPDF {gold["pymupdf"]}, this machine has {have}; '
                  f'expect CHANGED pages')
        print(f'running stack-highlights on the 14 books of {pdf} ...', flush=True)
        data = fresh_output(pdf, ns.jobs)
        if ns.save:
            Path(ns.save).write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            print(f'saved {ns.save}')

    results = check_pages(gold, data, ids)
    reg = [r for r in results if r['regressions']]
    chg = [r for r in results if r['changed']]
    imp = [r for r in results if r['improved']]
    for r in reg:
        for n, v, was, now, t in r['regressions']:
            print(f'REGRESSION {r["id"]} (merged p.{r["page"]}) mark #{n} [{v}]: {was} -> {now}: {t!r}  '
                  f'-- see images/{r["image"]}')
    for r in imp:
        for n, v, was, now, t in r['improved']:
            print(f'IMPROVED   {r["id"]} mark #{n} [{v}]: {was} -> {now}: {t!r}')
    for k, r in enumerate(chg):
        f_marks = [m['n'] for m in gold['pages'][r['id']]['marks'] if m['verdict'] == 'F']
        print(f'CHANGED    {r["id"]} (merged p.{r["page"]}): notes differ from what was judged'
              + (f' (had failures #{", #".join(map(str, f_marks))} -- maybe fixed)' if f_marks else '')
              + (f'; notes for mark(s) #{", #".join(map(str, r["moved"]))} differ' if r['moved'] else '')
              + f' -- re-check images/{r["image"]}')
        if k < ns.show and r['diff']:
            print('\n'.join('    ' + ln for ln in r['diff'].splitlines()[2:40]))

    c, judged = verdict_totals(gold, ids)
    same = len(results) - len(chg)
    print(f'\nvisual test: {len(results)} page(s), {sum(c.values())} highlight(s): '
          f'{same} page(s) same as judged, {len(chg)} changed, {len(reg)} with regressions, {len(imp)} improved')
    print(f'recorded verdicts: P {c["P"]}, M {c["M"]}, F {c["F"]}, X {c["X"]} -- '
          f'fully correct {100 * c["P"] / judged:.1f}%, correct or minor {100 * (c["P"] + c["M"]) / judged:.1f}%'
          + ('' if not chg else ' (verdicts on CHANGED pages need re-checking)'))
    failed = bool(reg) or (ns.strict and bool(chg))
    print('visual test: ' + ('FAILED' if failed else 'OK'))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())

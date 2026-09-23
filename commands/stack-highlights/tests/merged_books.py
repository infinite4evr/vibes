"""The test PDF, Test-Merged-All.pdf, and the books inside it.

The real-book tests (run_coverage.py here, and dev/visual-tests-500/run_visual_tests.py)
use one file: Test-Merged-All.pdf, 9,916 pages, 16 documents, 19,208 annotations. They do
not run stack-highlights on the whole merge. They split it back into its books (highlights
kept) and run each book on its own, the way the tool is used day to day: the tool measures
body-text size and running headers over the whole file, and in a 9,916-page merge those
figures are dominated by other books (see dev/visual-tests-500/REPORT.md, finding 3).

Only the 14 documents that carry highlights are listed; the ICSI Executive Programme book
(pp. 7636-8138) and the ILO Chronicle (pp. 8139-8258) have none.

Where the PDF is looked for: an explicit path, else $HIGHLIGHT_PDFS/Test-Merged-All.pdf,
else dev/source-pdfs/Test-Merged-All.pdf next to this toolchain.
"""
from __future__ import annotations
import concurrent.futures, json, os, re, subprocess, time
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
SCRIPT = ROOT / 'stack-highlights'
PDF_NAME = 'Test-Merged-All.pdf'
PDF_PAGES = 9916
COVERAGE_RE = re.compile(r'(\d+) mark\(s\)[^\n]*?, (\d+) placed in notes')

#  key               title                                                          first  last (merged-PDF pages)
BOOKS = [
    ('modern_india',   'A Brief History of Modern India (Spectrum, Rajiv Ahir)',         1,  920),
    ('constitution',   'The Constitution of India (2024 diglot)',                      921, 1322),
    ('acc_chowdhry',   'Fundamentals of Accounting & Financial Analysis (Chowdhry)',  1323, 1730),
    ('econ_ramesh',    'Indian Economy (Ramesh Singh)',                               1731, 2530),
    ('polity_laxmi',   'Indian Polity (M. Laxmikanth, 8th ed.)',                      2531, 3716),
    ('act_empcomp',    "Employee's Compensation Act, 1923",                           3717, 3798),
    ('acc_jain_panda', 'Fundamentals of Accounting for CA-CPT (Jain & Panda)',        3799, 4567),
    ('act_tu',         'Trade Unions Act, 1926',                                      4568, 4591),
    ('acc_tmh_cpt',    'Accountancy for CA-CPT (Tata McGraw Hill)',                   4592, 5710),
    ('econ_vivek',     'Indian Economy (Vivek Singh, 7th ed.)',                       5711, 6185),
    ('labour_acts',    'Labour Acts: Payment of Wages 1936 ... Unorganised Workers 2008', 6186, 7035),
    ('icsi_pp_llp',    'ICSI Professional Programme: Labour Laws & Practice',         7036, 7635),
    ('ir_pearson',     'Industrial Relations, Trade Unions & Labour Legislation (Pearson, 3e)', 8259, 9083),
    ('ir_ghosh',       'Industrial Relations and Labour Laws (Ghosh & Nanda)',        9084, 9916),
]


def find_pdf(explicit=None):
    """The merged PDF, or None when it is not on this machine."""
    cands = []
    if explicit:
        p = Path(explicit).expanduser()
        cands.append(p / PDF_NAME if p.is_dir() else p)
    if os.environ.get('HIGHLIGHT_PDFS'):
        cands.append(Path(os.environ['HIGHLIGHT_PDFS']).expanduser() / PDF_NAME)
    cands.append(ROOT / 'dev' / 'source-pdfs' / PDF_NAME)
    for c in cands:
        if c.is_file():
            return c
    return None


def pymupdf():
    try:
        import pymupdf as m
    except ImportError:
        import fitz as m
    return m


def pymupdf_version():
    try:
        return getattr(pymupdf(), 'VersionBind', '?')
    except ImportError:
        return 'not installed'


def split_books(pdf, cache_dir, keys=None, log=print):
    """Write each book as its own PDF (highlights kept) into cache_dir; reuse earlier
    splits of the same file (same size and modification time). Returns {key: path}."""
    cache = Path(cache_dir); cache.mkdir(parents=True, exist_ok=True)
    st = Path(pdf).stat()
    stamp = {'pdf': str(Path(pdf).resolve()), 'size': st.st_size, 'mtime': int(st.st_mtime)}
    stamp_file = cache / 'split.json'
    try:
        old = json.loads(stamp_file.read_text())
    except (OSError, ValueError):
        old = None
    if old != stamp:
        for f in cache.glob('*.pdf'):
            f.unlink()
    want = [b for b in BOOKS if keys is None or b[0] in keys]
    todo = [b for b in want if not (cache / f'{b[0]}.pdf').exists()]
    if todo:
        m = pymupdf()
        src = m.open(str(pdf))
        if src.page_count != PDF_PAGES:
            raise SystemExit(f'{pdf} has {src.page_count} pages, expected {PDF_PAGES}: '
                             f'not the {PDF_NAME} these tests were recorded on')
        t0 = time.time()
        for key, title, a, b in todo:
            d = m.open(); d.insert_pdf(src, from_page=a - 1, to_page=b - 1, annots=True)
            d.save(str(cache / f'{key}.pdf'), garbage=3, deflate=True); d.close()
        src.close()
        log(f'split {len(todo)} book(s) out of {Path(pdf).name} ({time.time() - t0:.0f}s)')
    stamp_file.write_text(json.dumps(stamp))
    return {b[0]: cache / f'{b[0]}.pdf' for b in want}


def run_book(book_pdf, out_json, extra=()):
    """Run stack-highlights (JSON) on one book. Returns (found, placed, data, seconds, error)."""
    cmd = [str(SCRIPT), str(book_pdf), '--format', 'json', '--out', str(out_json), '--no-progress', *extra]
    t0 = time.time()
    cp = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    secs = time.time() - t0
    m = COVERAGE_RE.search(cp.stderr)
    if cp.returncode or not m:
        return None, None, None, secs, f'extractor failed (exit {cp.returncode}):\n{cp.stderr.strip()}'
    data = json.loads(Path(out_json).read_text(encoding='utf-8')) if Path(out_json).exists() else None
    if data is None and int(m.group(2)):
        return None, None, None, secs, 'extractor wrote no output file'
    return int(m.group(1)), int(m.group(2)), data or {}, secs, None


def run_books(pdf, work_dir, keys=None, jobs=None, log=print):
    """Split and run every book. Returns {key: result dict} in BOOKS order, where the
    result has found, placed, seconds, error, and data (the tool's JSON with page numbers
    shifted back to merged-PDF pages)."""
    work = Path(work_dir); work.mkdir(parents=True, exist_ok=True)
    books = split_books(pdf, work / 'books', keys, log)
    first = {b[0]: b[2] for b in BOOKS}
    jobs = jobs or min(4, os.cpu_count() or 1)

    def one(key):
        found, placed, data, secs, err = run_book(books[key], work / f'{key}.json')
        if data:
            off = first[key] - 1
            for e in data.get('entries', []):
                e['page'] = int(e.get('page', 0)) + off
                e['source'] = key
            for c in data.get('check_in_book', []) or []:
                if isinstance(c, dict) and 'page' in c:
                    c['page'] = int(c['page']) + off
        return key, {'found': found, 'placed': placed, 'seconds': secs, 'error': err, 'data': data}

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as ex:
        for key, res in ex.map(one, list(books)):
            results[key] = res
    return {k: results[k] for k in books}

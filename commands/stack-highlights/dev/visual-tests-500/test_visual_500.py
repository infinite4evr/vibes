"""Pytest wrapper around run_visual_tests.py: one test per reference page (500).

The tool runs once for the whole session (the merged PDF split into its books);
each page test then fails if a highlight judged correct (P) or minor (M) on that page
is no longer placed in the notes. A page whose notes merely differ from what was
judged passes with a warning (set VISUAL_STRICT=1 to make it fail): its verdicts
need looking at again against images/<page>.png.

    pytest -q dev/visual-tests-500/test_visual_500.py
    VISUAL_OUTPUT=outputs/default_books.json pytest -q ...   # check a saved output, no run

Skipped when Test-Merged-All.pdf is not found ($HIGHLIGHT_PDFS or dev/source-pdfs).
"""
from __future__ import annotations
import json, os, sys, warnings
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_visual_tests as rvt   # noqa: E402

GOLD = json.loads(rvt.GOLD.read_text(encoding='utf-8'))
IDS = sorted(GOLD['pages'])


@pytest.fixture(scope='session')
def results():
    if os.environ.get('VISUAL_OUTPUT'):
        data = json.loads(Path(os.environ['VISUAL_OUTPUT']).read_text(encoding='utf-8'))
    else:
        pdf = rvt.mb.find_pdf(None)
        if not pdf:
            pytest.skip(f'{rvt.mb.PDF_NAME} not found (dev/source-pdfs or $HIGHLIGHT_PDFS)')
        data = rvt.fresh_output(pdf)
    return {r['id']: r for r in rvt.check_pages(GOLD, data, IDS)}


@pytest.mark.parametrize('pid', IDS)
def test_page(results, pid):
    r = results[pid]
    assert not r['regressions'], (
        f'{pid} (merged p.{r["page"]}): highlight(s) judged P/M no longer placed: '
        + '; '.join(f'#{n} [{v}] {was}->{now} {t!r}' for n, v, was, now, t in r['regressions'])
        + f'\nreference image: {HERE / "images" / r["image"]}')
    if r['changed']:
        msg = f'{pid}: notes differ from what was judged; re-check {HERE / "images" / r["image"]}\n{r["diff"]}'
        if os.environ.get('VISUAL_STRICT') == '1':
            pytest.fail(msg)
        warnings.warn(msg)

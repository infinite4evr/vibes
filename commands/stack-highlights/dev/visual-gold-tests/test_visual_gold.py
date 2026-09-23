"""Pytest wrapper around the independent visual-gold benchmark.

Environment variables:
  STACK_HIGHLIGHTS_BIN=/path/to/stack-highlights
  VISUAL_GOLD_PDF_ROOT=/path/to/folder/with/the/6/pdfs
  VISUAL_GOLD_MIN_SCORE=85

The session fixture runs each PDF/profile combination once; the 900 parametrized
tests then score individual visual-gold cases without rerunning the extractor.
"""
from __future__ import annotations
import importlib.util, json, os, re, subprocess
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('visual_gold_runner',ROOT/'run_visual_gold_tests.py')
runner=importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)
GOLD=json.load(open(ROOT/'gold_cases.json',encoding='utf-8'))
SCRIPT=os.environ.get('STACK_HIGHLIGHTS_BIN','stack-highlights')
PDF_ROOT=Path(os.environ.get('VISUAL_GOLD_PDF_ROOT','.'))
MIN_SCORE=float(os.environ.get('VISUAL_GOLD_MIN_SCORE','85'))

PARAMS=[(p,c) for p in GOLD['profiles'] for c in GOLD['cases']]
IDS=[f"{p}-{c['id']}" for p,c in PARAMS]

@pytest.fixture(scope='session')
def extracted(tmp_path_factory):
    out=tmp_path_factory.mktemp('visual-gold')
    bypdf={}
    for c in GOLD['cases']: bypdf.setdefault(c['pdf'],[]).append(c)
    result={}
    for pn,prof in GOLD['profiles'].items():
        for pdf,cases in bypdf.items():
            pdfpath=PDF_ROOT/pdf
            if not pdfpath.exists():
                pytest.skip(f'Missing PDF: {pdfpath}')
            pages=sorted({int(c['page']) for c in cases})
            safe=re.sub(r'[^A-Za-z0-9]+','_',Path(pdf).stem).strip('_')[:80]
            outf=out/f'{pn}__{safe}.json'
            cmd=[SCRIPT,str(pdfpath),'--pages',','.join(map(str,pages)),'--format','json','--out',str(outf),'--no-progress']+prof['args']
            cp=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            assert cp.returncode==0, f"Extractor failed: {cmd}\n{cp.stdout}\n{cp.stderr}"
            result[(pn,pdf)]=json.load(open(outf,encoding='utf-8')).get('entries',[])
    return result

@pytest.mark.parametrize('profile_name,case',PARAMS,ids=IDS)
def test_visual_gold_case(extracted,profile_name,case):
    entries=extracted[(profile_name,case['pdf'])]
    entry,selection_score=runner.choose_entry(entries,case)
    scored=runner.score_case(profile_name,case,entry,selection_score)
    assert scored['score'] >= MIN_SCORE, (
        f"{case['id']} {profile_name} scored {scored['score']}% ({scored['status']}). "
        f"Reason: {scored['reason']}\nExpected: {scored['expected']}\n"
        f"Actual: {scored['actual']}\nActual marks: {scored['actual_marks']}\n"
        f"Visual reference: {case['focus_image']}"
    )

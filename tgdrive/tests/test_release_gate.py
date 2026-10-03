"""CI policy checks complement the browser and instrumentation journeys."""
import itertools
import re
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def test_publish_gate_for_success_failure_cancel_and_skip():
    workflow=(ROOT/'.github/workflows/tgdrive-android.yml').read_text();publish=workflow.split('\n  publish:\n')[1]
    gate=publish.split('    if: >-\n')[1].split('    runs-on:')[0].strip()
    assert 'needs: [build, service-android-mode, emulator]' in publish
    for results,flags in itertools.product(itertools.product(('success','failure','cancelled','skipped'),repeat=3),itertools.product((False,True),repeat=2)):
        b,s,e=results;full,requested=flags;expr=gate.replace('always()','True')
        for k,v in {'needs.build.result':b,'needs.service-android-mode.result':s,'needs.emulator.result':e,'inputs.full':full,'inputs.emulator':requested}.items():expr=expr.replace(k,repr(v))
        expr=' '.join(expr.replace('&&',' and ').replace('||',' or ').replace('!',' not ').split())
        assert re.fullmatch(r"[a-zA-Z'()\s=]+",expr)
        assert eval(expr,{'__builtins__':{}},{})==(b=='success' and s=='success' and(e=='success' or(e=='skipped' and not full and not requested)))
    assert 'files: verified-apk/${{ needs.build.outputs.apk }}' in publish
    assert 'action-gh-release' not in workflow.split('\n  publish:\n')[0]

def test_emulator_requires_positive_completed_tests():
    s=(ROOT/'.github/scripts/tgdrive-android-emulator.sh').read_text();pattern=re.search(r"grep -Eq '([^']+)' out/reliability.txt",s)[1]
    for value,passes in [('OK (11 tests)\n',True),('OK (1 test)\n',True),('OK (0 tests)\n',False),('',False),('INSTRUMENTATION_FAILED: crash',False)]:
        assert(subprocess.run(['grep','-Eq',pattern],input=value,text=True).returncode==0)==passes
    luma=(ROOT/'.github/workflows/lumaclean-apk.yml').read_text();assert luma.index('File safety and cleanup preview journeys')<luma.index('Publish GitHub release')

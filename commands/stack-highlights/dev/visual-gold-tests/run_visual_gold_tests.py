#!/usr/bin/env python3
"""Independent visual-gold regression runner for stack-highlights.

The gold expectations in gold_cases.json were authored from rendered page images,
not from stack-highlights output. This runner treats the extractor as a black box.
"""
from __future__ import annotations
import argparse, collections, difflib, json, os, re, subprocess, sys, tempfile, unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent

STOP=set('a an the and or of to in on for by with as at from is are was were be been being it this that these those its their his her he she they them any all not only may shall should would can could into over under than then there such which who whom when where while if so per'.split())

def dehyphenate_text(s:str)->str:
    s=s.replace('\u00ad','')
    # common PDF line-break residue; don't merge numeric ranges.
    s=re.sub(r'(?<=[A-Za-z])-\s+(?=[a-z])','',s)
    return s

def norm_text(s:str)->str:
    s=unicodedata.normalize('NFKC',dehyphenate_text(s or ''))
    s=s.replace('’',"'").replace('“','"').replace('”','"').replace('–','-').replace('—','-')
    s=re.sub(r'\s+',' ',s).strip().lower()
    return s

def tokens(s:str):
    s=norm_text(s)
    out=[]
    for t in re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?",s):
        # tolerant to harmless hyphenation differences because hyphens are punctuation here.
        out.append(t)
    return out

def content_tokens(s:str):
    return [t for t in tokens(s) if t not in STOP and len(t)>1]

def multiset_recall(exp, act):
    if not exp: return 1.0
    ce,ca=collections.Counter(exp),collections.Counter(act)
    got=sum(min(n,ca[k]) for k,n in ce.items())
    return got/sum(ce.values())

def multiset_precision(exp, act):
    if not act:return 1.0 if not exp else 0.0
    ce,ca=collections.Counter(exp),collections.Counter(act)
    got=sum(min(n,ce[k]) for k,n in ca.items())
    return got/sum(ca.values())

def lcs_ratio(exp, act):
    if not exp:return 1.0
    # linear-memory LCS; strings are short enough.
    prev=[0]*(len(act)+1)
    for x in exp:
        cur=[0]
        for j,y in enumerate(act,1):
            cur.append(prev[j-1]+1 if x==y else max(prev[j],cur[-1]))
        prev=cur
    return prev[-1]/len(exp)

def flatten_runs(lines):
    chunks=[]
    for ln in lines or []:
        if isinstance(ln,dict):
            for r in ln.get('runs',[]) or []:
                chunks.append(r.get('text',''))
        elif isinstance(ln,str): chunks.append(ln)
    return ''.join(chunks)

def flatten_subs(subs):
    chunks=[]
    for s in subs or []:
        if isinstance(s,str): chunks.append(s)
        elif isinstance(s,dict):
            chunks.append(flatten_runs(s.get('lines',[])))
            chunks.append(flatten_subs(s.get('subs',[])))
    return ' '.join(x for x in chunks if x)

def entry_parts(e):
    body=' '.join(x for x in [flatten_runs(e.get('lines',[])),flatten_subs(e.get('subs',[]))] if x).strip()
    heads=' > '.join(h.get('text','') for h in e.get('headings',[]) or [])
    marks='\n'.join(m.get('text','') for m in e.get('marks',[]) or [])
    # Some highlighted headings have no body; their semantic content is the deepest heading.
    comparable=body if body else (e.get('headings') or [{}])[-1].get('text','')
    return body,heads,marks,comparable

def compact_mark(s):
    return re.sub(r'[^a-z0-9]+','',norm_text(s))

def mark_match_score(gold_mark, entry_mark):
    ge=compact_mark(gold_mark)
    if not ge:return 1.0
    candidates=[compact_mark(x) for x in (entry_mark or '').split('\n') if compact_mark(x)]
    if not candidates:return 0.0
    best=0.0
    for ae in candidates:
        if ge in ae or ae in ge:
            # containment: penalise only proportional truncation, not unrelated sibling marks.
            sc=min(len(ge),len(ae))/max(len(ge),len(ae))
            if ge in ae: sc=1.0
        else:
            sc=difflib.SequenceMatcher(None,ge,ae).ratio()
        best=max(best,sc)
    return best

def choose_entry(entries, case):
    candidates=[e for e in entries if int(e.get('page',-1))==int(case['page'])]
    if not candidates:return None,0.0
    scored=[]
    for e in candidates:
        _,_,marks,comp=entry_parts(e)
        mm=mark_match_score(case['gold']['marked_text'],marks)
        # tie-break with semantic content
        sr=multiset_recall(content_tokens(case['gold']['semantic_target']),content_tokens(comp))
        scored.append((mm+0.15*sr,e,mm))
    scored.sort(key=lambda z:z[0],reverse=True)
    return scored[0][1],scored[0][2]

def expected_for(profile_name,case):
    p=profile_name
    if p=='highlight_exact_flat': return case['gold']['marked_text']
    if p=='window12_flat': return case['gold']['window12_target']
    if p=='clause_structured': return case['gold']['clause_target']
    return case['gold']['semantic_target']

def score_case(profile_name,case,e,selector_mark_score):
    if e is None:
        return {'score':0.0,'status':'DANGEROUS','reason':'no matching entry on page','mark_score':0.0,'semantic_score':0.0,'order_score':0.0,'source_safety':0.0,'structure_score':0.0,'actual':''}
    body,heads,marks,comp=entry_parts(e)
    exp=expected_for(profile_name,case)
    goldmark=case['gold']['marked_text']
    mark_score=mark_match_score(goldmark,marks)
    mark_recall=mark_score
    mark_order=mark_score

    et=content_tokens(exp); at=content_tokens(comp)
    sem_recall=multiset_recall(et,at)
    order=lcs_ratio(et,at)
    sem_score=0.65*sem_recall+0.35*order

    # Source safety: body content words should come from the visually verified local source span.
    allowed=set(content_tokens(case['gold']['allowed_source']))
    actual_content=content_tokens(body if body else comp)
    if actual_content:
        source_safety=sum(1 for t in actual_content if t in allowed)/len(actual_content)
    else:
        source_safety=1.0 if case['content_kind']=='heading' else 0.0

    structure=1.0
    if profile_name in ('default_structured','clause_structured'):
        k=case['content_kind']
        if k=='heading': structure=1.0 if e.get('kind')=='heading' else 0.4
        elif k=='footnote': structure=1.0 if ('fn' in norm_text(body) or 'amendment' in norm_text(comp)) else 0.6
        elif k=='table_cell': structure=1.0 if comp else 0.0

    if profile_name=='highlight_exact_flat':
        # Exact-focus profile intentionally has almost no context. Highlight fidelity is the test.
        sem_score=mark_score; sem_recall=mark_score; order=mark_score; source_safety=1.0
        raw=100*mark_score
    else:
        raw=100*(0.45*mark_score+0.35*sem_score+0.15*source_safety+0.05*structure)

    reasons=[]; cap=100.0
    if mark_recall < 0.75:
        cap=min(cap,49.0); reasons.append('highlight missing/altered')
    if profile_name!='highlight_exact_flat':
        if sem_recall < 0.60:
            cap=min(cap,64.0); reasons.append('insufficient correct context')
        if order < 0.55 and len(et)>=4:
            cap=min(cap,59.0); reasons.append('context order scrambled')
        if source_safety < 0.55 and len(actual_content)>=5:
            cap=min(cap,69.0); reasons.append('substantial unrelated/unsafe text')
    score=min(raw,cap)
    status='PASS' if score>=85 else ('REVIEW' if score>=70 else ('FAIL' if score>=50 else 'DANGEROUS'))
    return {
      'score':round(score,2),'status':status,'reason':'; '.join(reasons),
      'mark_score':round(mark_score*100,2),'mark_recall':round(mark_recall*100,2),
      'semantic_score':round(sem_score*100,2),'semantic_recall':round(sem_recall*100,2),
      'order_score':round(order*100,2),'source_safety':round(source_safety*100,2),
      'structure_score':round(structure*100,2),'entry_kind':e.get('kind'),
      'actual':comp,'actual_marks':marks,'headings':heads,'expected':exp
    }

def run_cmd(script,pdf,pages,args,out):
    cmd=[str(script),str(pdf),'--pages',','.join(map(str,pages)),'--format','json','--out',str(out),'--no-progress']+list(args)
    cp=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if cp.returncode!=0:
        raise RuntimeError('command failed: '+repr(cmd)+'\nSTDOUT:\n'+cp.stdout+'\nSTDERR:\n'+cp.stderr)
    return cmd,cp.stderr.strip()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--script',default='stack-highlights')
    ap.add_argument('--pdf-root',default='.')
    ap.add_argument('--gold',default=str(ROOT/'gold_cases.json'))
    ap.add_argument('--out-dir',default=str(ROOT/'results'))
    ap.add_argument('--profiles',default='',help='comma-separated subset')
    args=ap.parse_args()
    script=Path(args.script); pdfroot=Path(args.pdf_root); outdir=Path(args.out_dir); outdir.mkdir(parents=True,exist_ok=True)
    gold=json.load(open(args.gold))
    prof_names=list(gold['profiles'])
    if args.profiles:
        keep=set(x.strip() for x in args.profiles.split(',') if x.strip()); prof_names=[p for p in prof_names if p in keep]
    bypdf=collections.defaultdict(list)
    for c in gold['cases']: bypdf[c['pdf']].append(c)
    allres=[]; runs=[]
    for pn in prof_names:
        prof=gold['profiles'][pn]
        for pdfname,cases in bypdf.items():
            pages=sorted({int(c['page']) for c in cases})
            safe=re.sub(r'[^A-Za-z0-9]+','_',Path(pdfname).stem).strip('_')[:80]
            outf=outdir/f'{pn}__{safe}.json'
            cmd,stderr=run_cmd(script,pdfroot/pdfname,pages,prof['args'],outf)
            data=json.load(open(outf)); entries=data.get('entries',[])
            runs.append({'profile':pn,'pdf':pdfname,'pages':pages,'command':cmd,'stderr':stderr,'raw_output':str(outf.relative_to(ROOT))})
            for c in cases:
                e,sel=choose_entry(entries,c)
                r=score_case(pn,c,e,sel); r.update({'case_id':c['id'],'profile':pn,'pdf':pdfname,'page':c['page'],'density':c['density'],'content_kind':c['content_kind'],'page_image':c['page_image'],'focus_image':c['focus_image']})
                allres.append(r)
    # summaries
    def avg(xs): return round(sum(xs)/len(xs),2) if xs else 0.0
    summary={'overall_score':avg([r['score'] for r in allres]),'comparisons':len(allres),'status_counts':dict(collections.Counter(r['status'] for r in allres))}
    summary['by_profile']={p:{'score':avg([r['score'] for r in allres if r['profile']==p]),'status_counts':dict(collections.Counter(r['status'] for r in allres if r['profile']==p))} for p in prof_names}
    summary['by_pdf']={pdf:{'score':avg([r['score'] for r in allres if r['pdf']==pdf]),'status_counts':dict(collections.Counter(r['status'] for r in allres if r['pdf']==pdf))} for pdf in bypdf}
    summary['by_kind']={k:{'score':avg([r['score'] for r in allres if r['content_kind']==k]),'n':len([r for r in allres if r['content_kind']==k])} for k in sorted({r['content_kind'] for r in allres})}
    summary['dangerous']=[{'case_id':r['case_id'],'profile':r['profile'],'pdf':r['pdf'],'page':r['page'],'score':r['score'],'reason':r['reason']} for r in allres if r['status']=='DANGEROUS']
    report={'summary':summary,'runs':runs,'results':allres}
    json.dump(report,open(outdir/'report.json','w'),ensure_ascii=False,indent=2)
    # human-readable markdown
    lines=['# Visual-gold regression report','',f"Overall semantic correctness score: **{summary['overall_score']}%** across **{summary['comparisons']}** comparisons.",'',
           'Scoring deliberately ignores Markdown, whitespace, line wrapping, punctuation spacing and harmless dehyphenation. Missing highlighted content, wrong context, scrambled order and unrelated text are penalised heavily.','',
           '## By profile','']
    for p,v in summary['by_profile'].items(): lines.append(f"- **{p}**: {v['score']}% - {v['status_counts']}")
    lines += ['','## By PDF','']
    for p,v in summary['by_pdf'].items(): lines.append(f"- **{p}**: {v['score']}% - {v['status_counts']}")
    lines += ['','## Dangerous failures','']
    if summary['dangerous']:
        for d in summary['dangerous']: lines.append(f"- {d['case_id']} / {d['profile']} / p.{d['page']}: **{d['score']}%** - {d['reason']}")
    else: lines.append('- None.')
    lines += ['','## Lowest-scoring comparisons','']
    for r in sorted(allres,key=lambda z:z['score'])[:20]:
        lines.append(f"- {r['case_id']} / {r['profile']} / {Path(r['pdf']).name} p.{r['page']}: **{r['score']}%** ({r['status']}) {r['reason']}")
    (outdir/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__': main()

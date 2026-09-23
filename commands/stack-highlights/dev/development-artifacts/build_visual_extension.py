import fitz, json, os, re, math, collections, hashlib
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT=Path('/mnt/data')
BASE=ROOT/'visual-gold-test-suite-final'
OUT=ROOT/'visual-gold-test-suite-180'
PDFS=[
'00_The_Constitution_of_India.pdf',
'01_A_Brief_History_of_Modern_India.pdf',
'01_Fundamentals_of_Accounting_and_Financial_Analysis_Anil_Chowdhury_--_2006.pdf',
'01_INDIAN_ECONOMY_FOR_CIVIL_SERVICES__UNIVERSITIES_AND_OTHER_EXAMINATIONS_-_Ramesh_Singh.pdf',
'01_Indian_Polity_Laxmikanth.pdf',
'05 THE INDUSTRIAL DISPUTES ACT, 1947.pdf']

oldsel=json.load(open(BASE/'selection.json'))['pages']
oldmap=collections.defaultdict(set)
for r in oldsel: oldmap[r['pdf']].add(int(r['page']))

def pick_evenly(vals,k):
    vals=sorted(vals)
    if k>=len(vals): return vals[:]
    chosen=[]; used=set()
    for i in range(k):
        target=(i+0.5)*len(vals)/k-0.5
        idx=round(target)
        best=None
        for d in range(len(vals)):
            for j in (idx-d,idx+d):
                if 0<=j<len(vals) and j not in used:
                    best=j; break
            if best is not None: break
        used.add(best); chosen.append(vals[best])
    return sorted(chosen)

def quad_rects(annot):
    vs=annot.vertices or []
    rs=[]
    for i in range(0,len(vs),4):
        pts=vs[i:i+4]
        if len(pts)<4: continue
        xs=[p[0] if not hasattr(p,'x') else p.x for p in pts]; ys=[p[1] if not hasattr(p,'y') else p.y for p in pts]
        rs.append(fitz.Rect(min(xs),min(ys),max(xs),max(ys)))
    if not rs: rs=[annot.rect]
    return rs

def chars_in_rects(page, rects):
    raw=page.get_text('rawdict')
    out=[]
    for b in raw.get('blocks',[]):
        if b.get('type')!=0: continue
        for line in b.get('lines',[]):
            for span in line.get('spans',[]):
                for ch in span.get('chars',[]):
                    c=fitz.Rect(ch['bbox']); cx=(c.x0+c.x1)/2; cy=(c.y0+c.y1)/2
                    hit=any(r.x0-0.5<=cx<=r.x1+0.5 and r.y0-0.7<=cy<=r.y1+0.7 for r in rects)
                    if hit: out.append((ch['c'],c,line.get('bbox'),span.get('size',0)))
    # reconstruct spaces from char gaps by line
    if not out: return ''
    text=''; prev=None; prev_line=None
    for ch,c,lb,sz in out:
        linekey=(round(lb[1],1),round(lb[3],1)) if lb else None
        if prev is not None:
            if linekey!=prev_line:
                text+=' '
            else:
                gap=c.x0-prev.x1
                if gap>max(1.0,sz*0.18): text+=' '
        text+=ch; prev=c; prev_line=linekey
    return re.sub(r'\s+',' ',text).strip()

def block_candidates(page):
    # get blocks in natural order; returns rect,text
    bs=[]
    for b in page.get_text('blocks'):
        x0,y0,x1,y1,txt,*rest=b
        txt=re.sub(r'\s+',' ',txt).strip()
        if txt: bs.append((fitz.Rect(x0,y0,x1,y1),txt))
    return bs

def choose_annotation(page):
    anns=[a for a in (page.annots() or []) if a.type[0] in (8,9,10,11)]
    if not anns: return None
    H=page.rect.height; W=page.rect.width
    scored=[]
    for a in anns:
        rs=quad_rects(a); txt=chars_in_rects(page,rs)
        r=a.rect
        alpha=sum(c.isalpha() for c in txt); alnum=sum(c.isalnum() for c in txt)
        # preference: readable, meaningful, body, moderate length, non-boilerplate
        pos=1.0 if 0.13*H<r.y0<0.88*H else 0.3
        meaningful=1.0 if alpha>=3 else (0.4 if alnum else 0)
        length=len(txt)
        len_score=1.0 if 8<=length<=90 else (0.75 if 4<=length<=140 else 0.3)
        # avoid giant full-line/paragraph annotations as focus if other options exist
        width_score=1.0 if r.width<0.75*W else 0.5
        boiler=0.2 if re.search(r'page\s+\d+|edition|chapter\s+\d+$',txt,re.I) else 1.0
        score=4*meaningful+2*len_score+1.5*pos+width_score+boiler
        scored.append((score,a,txt,rs))
    scored.sort(key=lambda z:z[0],reverse=True)
    return scored[0][1],scored[0][2],scored[0][3]

def nearest_block(page, focus_rect):
    bs=block_candidates(page)
    # prefer overlapping block, else nearest vertical/horizontal distance
    best=None
    for r,txt in bs:
        inter=r & focus_rect
        overlap=(inter.get_area() if not inter.is_empty else 0)
        contains=(r.contains(focus_rect) or r.intersects(focus_rect))
        dx=max(r.x0-focus_rect.x1, focus_rect.x0-r.x1,0)
        dy=max(r.y0-focus_rect.y1, focus_rect.y0-r.y1,0)
        dist=math.hypot(dx,dy)
        score=(10000 if contains else 0)+overlap*10-dist
        if best is None or score>best[0]: best=(score,r,txt)
    return (best[1],best[2]) if best else (page.rect,'')

def split_sentences(text):
    # independent conservative segmentation; preserve list/legal items when possible
    text=re.sub(r'\s+',' ',text).strip()
    if not text:return []
    # Don't split on initials and section decimals aggressively.
    parts=re.split(r'(?<=[.!?])\s+(?=(?:[A-Z\[(]|\d+\.?\s+[A-Z]))',text)
    return [p.strip() for p in parts if p.strip()]

def best_sentence(block_text, mark):
    nm=re.sub(r'\W+','',mark).lower()
    parts=split_sentences(block_text)
    for s in parts:
        if nm and nm in re.sub(r'\W+','',s).lower(): return s
    # token overlap fallback
    mt=[x.lower() for x in re.findall(r'[A-Za-z0-9]+',mark)]
    best=(0,block_text)
    for s in parts:
        st=set(x.lower() for x in re.findall(r'[A-Za-z0-9]+',s))
        sc=sum(x in st for x in mt)
        if sc>best[0]: best=(sc,s)
    return best[1].strip()

def window_words(block_text, mark, n=12):
    words=re.findall(r"\S+",block_text)
    if not words:return block_text
    mark_tokens=[re.sub(r'\W+','',x).lower() for x in mark.split() if re.sub(r'\W+','',x)]
    norm=[re.sub(r'\W+','',x).lower() for x in words]
    start=None; end=None
    if mark_tokens:
        # find first sequence-ish occurrence
        for i in range(len(norm)):
            if norm[i]==mark_tokens[0]:
                # accept first token match; annotation may be partial word
                start=i; end=min(len(words), i+max(1,len(mark_tokens))); break
    if start is None:
        return best_sentence(block_text,mark)
    left=max(0,start-n); right=min(len(words),end+n)
    return ' '.join(words[left:right])

def classify(page, focus_rect, mark, block_text):
    s=block_text.strip(); m=mark.strip()
    # visual/layout heuristics independent of target extractor
    if re.match(r'^\s*(?:\d+[A-Z\-]*\.?|\([a-zivx]+\))\s+',s,re.I):
        if re.search(r'\b(section|article|act|chapter)\b',s,re.I) or re.match(r'^\d+[A-Z\-]*\.',s): return 'legal_clause'
        return 'list_item'
    if len(s)<140 and (m.upper()==m and sum(c.isalpha() for c in m)>2): return 'heading'
    if focus_rect.y0>page.rect.height*0.82: return 'footnote'
    # crude table indication: neighboring block has many short columns or page words across same y
    words=page.get_text('words')
    band=[w for w in words if abs(((w[1]+w[3])/2)-((focus_rect.y0+focus_rect.y1)/2))<8]
    if len(band)>=5:
        xs=sorted((w[0],w[2]) for w in band)
        gaps=[xs[i+1][0]-xs[i][1] for i in range(len(xs)-1)]
        if sum(g>15 for g in gaps)>=2: return 'table_cell'
    return 'prose'

def make_contact(paths,out_path,cols=2,thumb_w=1000,label=True):
    ims=[]
    for p in paths:
        im=Image.open(p).convert('RGB')
        scale=thumb_w/im.width
        im=im.resize((thumb_w,int(im.height*scale)),Image.Resampling.LANCZOS)
        if label:
            canvas=Image.new('RGB',(im.width,im.height+35),'white'); canvas.paste(im,(0,35))
            d=ImageDraw.Draw(canvas); d.text((8,8),Path(p).stem,fill='black')
            im=canvas
        ims.append(im)
    rows=math.ceil(len(ims)/cols); gap=20
    row_heights=[]
    for r in range(rows): row_heights.append(max(im.height for im in ims[r*cols:(r+1)*cols]))
    total_w=cols*thumb_w+(cols-1)*gap; total_h=sum(row_heights)+(rows-1)*gap
    canvas=Image.new('RGB',(total_w,total_h),'white')
    y=0
    for r in range(rows):
        x=0
        for im in ims[r*cols:(r+1)*cols]:
            canvas.paste(im,(x,y)); x+=thumb_w+gap
        y+=row_heights[r]+gap
    canvas.save(out_path,quality=90)

# create output clone if not exists
import shutil
if OUT.exists(): shutil.rmtree(OUT)
shutil.copytree(BASE,OUT)
# clear benchmark in new suite; retain old report separately by rename
if (OUT/'benchmark_current').exists(): shutil.move(str(OUT/'benchmark_current'),str(OUT/'benchmark_original_60'))

new_records=[]
new_cases=[]
next_id=61
for name in PDFS:
    doc=fitz.open(ROOT/name)
    med=[]; high=[]
    for i,p in enumerate(doc):
        pg=i+1
        if pg in oldmap[name]: continue
        n=sum(1 for a in (p.annots() or []) if a.type[0] in (8,9,10,11))
        if 2<=n<=4: med.append((pg,n))
        elif n>=5: high.append((pg,n))
    km=11 if name.startswith('05 ') else 12
    kh=20-km
    selected=sorted(pick_evenly(med,km)+pick_evenly(high,kh))
    stem=re.sub(r'[^A-Za-z0-9_]+','_',Path(name).stem).strip('_')
    # match historical directory names exactly where possible
    old_stem=next((r['pdf_stem'] for r in oldsel if r['pdf']==name),stem)
    imgdir=OUT/'images'/old_stem; fadir=OUT/'focus_annotated'/old_stem
    imgdir.mkdir(parents=True,exist_ok=True); fadir.mkdir(parents=True,exist_ok=True)
    focus_paths=[]; page_paths=[]
    for pg,nann in selected:
        page=doc[pg-1]
        picked=choose_annotation(page)
        if not picked: continue
        annot,mark,rects=picked
        fr=annot.rect
        # full render 170dpi approx zoom 2.36
        zoom=2.25; mat=fitz.Matrix(zoom,zoom)
        pix=page.get_pixmap(matrix=mat,alpha=False,annots=True)
        page_path=imgdir/f'page_{pg:04d}.png'; pix.save(str(page_path))
        # wide context crop around highlight; include most page width, +-80pt vertical
        crop=fitz.Rect(max(0,fr.x0-50),max(0,fr.y0-75),min(page.rect.width,fr.x1+50),min(page.rect.height,fr.y1+75))
        # widen to near full text column for context
        crop.x0=max(0,min(crop.x0,40)); crop.x1=min(page.rect.width,max(crop.x1,page.rect.width-40))
        cpix=page.get_pixmap(matrix=fitz.Matrix(2.6,2.6),clip=crop,alpha=False,annots=True)
        cim=Image.frombytes('RGB',[cpix.width,cpix.height],cpix.samples)
        d=ImageDraw.Draw(cim)
        # box around annotation in crop pixel coords
        sx=2.6; sy=2.6
        box=((fr.x0-crop.x0)*sx,(fr.y0-crop.y0)*sy,(fr.x1-crop.x0)*sx,(fr.y1-crop.y0)*sy)
        d.rectangle(box,outline='red',width=4)
        d.text((8,8),f'PDF p.{pg} | anns={nann} | mark: {mark[:90]}',fill='red')
        focus_path=fadir/f'page_{pg:04d}_focus_annotated.png'; cim.save(focus_path)
        block_rect,block_text=nearest_block(page,fr)
        semantic=best_sentence(block_text,mark)
        if not semantic: semantic=mark
        window=window_words(block_text,mark,12)
        ckind=classify(page,fr,mark,block_text)
        # allowed source = containing block, capped only for pathological very long blocks
        allowed=block_text
        # clause target conservative: for legal/list use block, otherwise sentence
        clause=block_text if ckind in ('legal_clause','list_item') and len(block_text)<700 else semantic
        density='high' if nann>=5 else 'medium'
        rec={
          'pdf':name,'pdf_stem':old_stem,'page':pg,'annotation_count':nann,'density_bucket':density,
          'image':str(page_path.relative_to(OUT)),'focus_kind':'highlight','focus_rect':[round(fr.x0,1),round(fr.y0,1),round(fr.x1,1),round(fr.y1,1)],
          'focus_annotation_image':str(focus_path.relative_to(OUT)),'focus_quads':[[float(r.x0),float(r.y0),float(r.x1),float(r.y1)] for r in rects],
          'focus_marked_text':mark
        }
        case={
          'id':f'VG{next_id:03d}','pdf':name,'page':pg,'density':density,
          'page_image':rec['image'],'focus_image':rec['focus_annotation_image'],'focus_rect':rec['focus_rect'],'focus_quads':rec['focus_quads'],
          'content_kind':ckind,'visually_verified':False,
          'gold':{'marked_text':mark,'semantic_target':semantic,'allowed_source':allowed,'lead_in':None,'clause_target':clause,'window12_target':window},
          'safety':{'must_preserve_highlight':True,'must_keep_order':True,'wrong_attachment_is_major':True,'formatting_is_minor':True}
        }
        next_id+=1
        new_records.append(rec); new_cases.append(case); focus_paths.append(focus_path); page_paths.append(page_path)
    # contact sheets: 2 x 10 focus for readability, plus page sheet 4 cols
    for j in range(0,len(focus_paths),10):
        make_contact(focus_paths[j:j+10],OUT/f'{old_stem}_new_focus_{j//10+1}.png',cols=1,thumb_w=1500)
    make_contact(page_paths,OUT/f'{old_stem}_new_pages_contact.png',cols=4,thumb_w=500)

# Write draft selection and gold separate, not yet merged/frozen
json.dump({'interpretation':'120 additional pages = 20 new highlighted pages per each of 6 PDFs; excludes original 60','pages':new_records},open(OUT/'selection_additional_120_draft.json','w'),ensure_ascii=False,indent=2)
json.dump({'schema_version':1,'authorship':{'status':'DRAFT - independent geometry + visual review pending'},'profiles':json.load(open(BASE/'gold_cases.json'))['profiles'],'cases':new_cases},open(OUT/'gold_additional_120_draft.json','w'),ensure_ascii=False,indent=2)
print('new records',len(new_records),'new cases',len(new_cases),'out',OUT)

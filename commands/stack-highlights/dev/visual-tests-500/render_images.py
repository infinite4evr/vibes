#!/usr/bin/env python3
"""Render the visual reference image for every selected page: the full page as
it looks in a PDF viewer (highlights included), with a thin red box and a
number beside every mark, so gold case P123#4 can be found on the image.
Also writes review crops (the vertical band holding the marks) used during review.
"""
import json, sys
from pathlib import Path
import pymupdf
from PIL import Image, ImageDraw, ImageFont
HERE = Path(__file__).resolve().parent
PDF = Path(sys.argv[1])
OUT = Path(sys.argv[2])            # images/ folder for the reference images
REV = HERE / 'review_crops'
DPI = 100
try:
    FONT = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 13)
except Exception:
    FONT = ImageFont.load_default()

def render(doc, rec, pid):
    page = doc[rec['page'] - 1]
    pix = page.get_pixmap(dpi=DPI, annots=True)
    img = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    s = DPI / 72.0
    # page.rotation: quads are in unrotated space; map through rotation matrix
    M = page.rotation_matrix * pymupdf.Matrix(s, s)
    d = ImageDraw.Draw(img)
    ys = []
    for m in rec['marks']:
        first = None
        for q in m['quads']:
            r = pymupdf.Rect(q) * M; r.normalize()
            d.rectangle([r.x0 - 1, r.y0 - 1, r.x1 + 1, r.y1 + 1], outline=(220, 0, 0), width=1)
            ys += [r.y0, r.y1]
            if first is None: first = r
        lab = str(m['n'])
        tw = d.textlength(lab, font=FONT)
        x = max(0, first.x0 - tw - 5); y = max(0, first.y0 - 3)
        d.rectangle([x - 1, y, x + tw + 1, y + 14], fill=(220, 0, 0))
        d.text((x, y), lab, fill=(255, 255, 255), font=FONT)
    name = f"{pid}_p{rec['page']:04d}.png"
    q = img.quantize(colors=96, method=Image.Quantize.MEDIANCUT)
    q.save(OUT / name, optimize=True)
    if ys:
        top = max(0, int(min(ys) - 45 * s)); bot = min(img.height, int(max(ys) + 45 * s))
        img.crop((0, top, img.width, bot)).save(REV / f'{pid}.png')
    return name

def main():
    OUT.mkdir(parents=True, exist_ok=True); REV.mkdir(exist_ok=True)
    marks = json.load(open(HERE / 'marks_raw.json'))
    doc = pymupdf.open(PDF)
    names = {}
    for pid, rec in marks.items():
        names[pid] = render(doc, rec, pid)
    json.dump(names, open(HERE / 'image_names.json', 'w'), indent=0)
    print('rendered', len(names))

if __name__ == '__main__': main()

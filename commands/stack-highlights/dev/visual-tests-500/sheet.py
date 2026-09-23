#!/usr/bin/env python3
"""Stack review crops of several pages into sheets (review aid). usage: sheet.py SCALE P001-P005"""
import sys, re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
HERE = Path(__file__).resolve().parent
scale = float(sys.argv[1]); ids = []
for a in sys.argv[2:]:
    m = re.fullmatch(r'P(\d+)-P?(\d+)', a)
    ids += [f'P{i:03d}' for i in range(int(m.group(1)), int(m.group(2)) + 1)] if m else [a]
F = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 14)
MAXH = 1500; sheets = []; cur = []; h = 0
for pid in ids:
    im = Image.open(HERE / 'review_crops' / f'{pid}.png')
    im = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
    if cur and h + im.height + 18 > MAXH:
        sheets.append(cur); cur = []; h = 0
    cur.append((pid, im)); h += im.height + 18
if cur: sheets.append(cur)
out = []
for k, grp in enumerate(sheets):
    W = max(i.width for _, i in grp); H = sum(i.height + 18 for _, i in grp)
    S = Image.new('RGB', (W, H), 'white'); d = ImageDraw.Draw(S); y = 0
    for pid, im in grp:
        d.rectangle([0, y, W, y + 17], fill=(30, 30, 120)); d.text((4, y + 1), pid, fill='white', font=F)
        S.paste(im, (0, y + 18)); y += im.height + 18
    p = HERE / 'sheets' / f'{grp[0][0]}_{grp[-1][0]}.png'; p.parent.mkdir(exist_ok=True); S.save(p); out.append(str(p))
print('\n'.join(out))

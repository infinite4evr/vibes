#!/usr/bin/env python3
"""Make the material for REPORT.md from gold_cases.json:
  report_images/Fnn_Pnnn.png  a crop of each page with failures (from images/, marks boxed)
  printed: minor issues (M) grouped into categories, with counts.

    python3 report_assets.py
"""
import collections, json, re
from pathlib import Path
from PIL import Image

HERE = Path(__file__).resolve().parent
OUT = HERE / 'report_images'
SCALE = 100 / 72          # images/ are rendered at 100 dpi

CATEGORIES = [   # (name, pattern on the recorded reason); first match wins
    ('Marked words intact, but inside a scrambled entry', r'scrambled'),
    ('Context trimmed or cut: who does it, the condition, or the rest of the sentence is lost',
     r'context trimmed|context cut|cut at the page|mid-way|attribution|trimmed to|prefixed|case name'),
    ('Words glued where amendment markers were removed ("aemployee")', r'glued where|glued in|glue in|glued inside'),
    ('Filed under a wrong heading', r'wrong case heading|wrong heading'),
    ('Line-break hyphen kept ("legisla-tion")', r'hyphen'),
    ('Word split after the "fi" ligature ("fi gures")', r'ligature'),
    ('List or bullet items run together', r'run together|packed'),
    ('Item or answer without its lead-in / question', r'lead-in|without (its|their) (question|statements)|without their'),
    ('Stray symbol, letter, number or text inserted', r'stray|glyph|backtick|footnote number|inserted|injected|glued to the end'),
    ('Sentence, title or item split across entries or headings', r'split|turned into a heading|torn from'),
    ('Table cell paired wrongly or flattened', r'table|row|fraction|flowchart|cell'),
    ('Half-covered word left unbold', r'unbold'),
]


def main():
    gold = json.loads((HERE / 'gold_cases.json').read_text(encoding='utf-8'))
    OUT.mkdir(exist_ok=True)
    k = 0
    for pid, pg in sorted(gold['pages'].items()):
        fs = [m for m in pg['marks'] if m['verdict'] == 'F']
        if not fs:
            continue
        k += 1
        im = Image.open(HERE / 'images' / pg['image'])
        ys = [q[1] for m in fs for q in m['quads']] + [q[3] for m in fs for q in m['quads']]
        top = max(0, int(min(ys) * SCALE) - 60); bottom = min(im.height, int(max(ys) * SCALE) + 60)
        name = f'F{k:02d}_{pid}.png'
        im.crop((0, top, im.width, bottom)).save(OUT / name, optimize=True)
        print(f'{name}: {pid} merged p.{pg["page"]}, marks #' + ', #'.join(str(m['n']) for m in fs))

    cat = collections.Counter(); other = []
    for pid, pg in gold['pages'].items():
        for m in pg['marks']:
            if m['verdict'] != 'M':
                continue
            for name, pat in CATEGORIES:
                if re.search(pat, m['why'], re.I):
                    cat[name] += 1; break
            else:
                cat['Other'] += 1; other.append(f'{pid}#{m["n"]}: {m["why"][:90]}')
    total = sum(cat.values())
    print(f'\nminor issues: {total}')
    for name, n in cat.most_common():
        print(f'{n:4d}  {100 * n / total:4.1f}%  {name}')
    for o in other:
        print('   other:', o)


if __name__ == '__main__':
    main()

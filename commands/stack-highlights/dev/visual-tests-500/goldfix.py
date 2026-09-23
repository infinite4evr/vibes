#!/usr/bin/env python3
"""Correct a transcription after visual review. usage: goldfix.py P075 1 'visually confirmed text'
(Appends to gold_fixes.jsonl; used when the PDF text layer disagrees with what is visibly marked.)"""
import json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
pid, n, text = sys.argv[1], int(sys.argv[2]), sys.argv[3]
with open(HERE / 'gold_fixes.jsonl', 'a') as f:
    f.write(json.dumps({'id': pid, 'n': n, 'text': text}, ensure_ascii=False) + '\n')
print('fixed', pid, n)

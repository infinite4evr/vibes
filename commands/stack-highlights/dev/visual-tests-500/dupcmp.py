#!/usr/bin/env python3
"""Temporary review aid: compare the tool output for a repeated page with its sampled twin
(entry texts and headings, ignoring entry numbers and page labels). usage: dupcmp.py P336 P328"""
import json, re, subprocess, sys
def norm(pid):
    out = subprocess.run(['./rv', pid], capture_output=True, text=True).stdout
    out = re.sub(r'E\d+(\(p\d+\))?', 'E', out); out = re.sub(r'=== P\d+ p\.\d+', '===', out)
    return out
a, b = norm(sys.argv[1]), norm(sys.argv[2])
print('IDENTICAL output' if a == b else 'DIFFERENT output')
if a != b:
    import difflib; print('\n'.join(difflib.unified_diff(b.splitlines(), a.splitlines(), sys.argv[2], sys.argv[1], lineterm='', n=0)))

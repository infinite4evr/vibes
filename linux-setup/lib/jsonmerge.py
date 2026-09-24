#!/usr/bin/env python3
"""Merge settings from one JSON file into an editor settings file (JSON with comments allowed).

usage: jsonmerge.py TARGET SOURCE
Keys from SOURCE win; everything else in TARGET is kept. Exit code 2 = TARGET couldn't be parsed (left untouched).
"""
import json
import os
import sys


def strip_jsonc(text: str) -> str:
    """Remove // and /* */ comments (outside strings) and trailing commas."""
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 2; continue
            if c == '"':
                in_str = False
            i += 1; continue
        if c == '"':
            in_str = True; out.append(c); i += 1; continue
        if text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        out.append(c); i += 1
    s = "".join(out)
    # drop trailing commas before } or ] (outside strings)
    res, in_str, i = [], False, 0
    while i < len(s):
        c = s[i]
        if in_str:
            res.append(c)
            if c == "\\" and i + 1 < len(s):
                res.append(s[i + 1]); i += 2; continue
            if c == '"':
                in_str = False
            i += 1; continue
        if c == '"':
            in_str = True
        elif c == ",":
            j = i + 1
            while j < len(s) and s[j] in " \t\r\n":
                j += 1
            if j < len(s) and s[j] in "}]":
                i += 1; continue
        res.append(c); i += 1
    return "".join(res)


def deep_merge(base: dict, new: dict) -> dict:
    for k, v in new.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def main() -> int:
    target, source = sys.argv[1], sys.argv[2]
    with open(source, encoding="utf-8") as f:
        new = json.load(f)
    current = {}
    if os.path.exists(target) and os.path.getsize(target) > 0:
        with open(target, encoding="utf-8") as f:
            raw = f.read()
        try:
            current = json.loads(strip_jsonc(raw)) if raw.strip() else {}
        except json.JSONDecodeError:
            return 2
        if not isinstance(current, dict):
            return 2
    merged = deep_merge(current, new)
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, target)
    return 0


if __name__ == "__main__":
    sys.exit(main())

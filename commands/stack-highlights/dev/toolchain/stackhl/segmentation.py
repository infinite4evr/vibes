"""Sentence / clause segmentation on a paragraph string.

Part of stack-highlights; code moved here unchanged from the original single file.
"""
import re
from .constants import ABBREVIATIONS, CLOSERS, DASHES, LIST_RE, OPENERS, SENT_PUNCT
from .helpers import word_count


# ---------------------------------------------------------------------------
# Sentence / clause segmentation on a paragraph string
# ---------------------------------------------------------------------------
def is_abbrev(text, i):
    j = i - 1
    while j >= 0 and (text[j].isalnum() or text[j] in "'/"):
        j -= 1
    word = text[j + 1:i]
    if not word:
        return False
    if len(word) == 1 and word.isalpha():
        return True          # initials, "s.", "e.g", "i.e"
    return word.lower() in ABBREVIATIONS


def sentence_bounds(text):
    """Return the end positions (exclusive) of sentences in text."""
    ends = []
    n = len(text)
    for i, ch in enumerate(text):
        if ch not in SENT_PUNCT:
            continue
        j = i + 1
        while j < n and text[j] in CLOSERS:
            j += 1
        if j < n and text[j] in DASHES:          # "operation].—A woman ..."
            ends.append(j + 1)
            continue
        if j < n and not text[j].isspace():
            continue                              # 3.5, U.S.A, w.e.f.
        if ch == "." and is_abbrev(text, i):
            continue
        k = j
        while k < n and text[k].isspace():
            k += 1
        if k >= n:
            ends.append(j)
            continue
        nx = text[k]
        if nx.isupper() or nx.isdigit() or nx in OPENERS or nx in "•":
            ends.append(j)
    if not ends or ends[-1] < n:
        ends.append(n)
    return sorted(set(ends))


def clause_bounds(text, s, e):
    ends = []
    for i in range(s, e):
        ch = text[i]
        if ch in ",;:" and i + 1 < e and text[i + 1].isspace():
            ends.append(i + 1)
        elif ch in DASHES and i > s:
            ends.append(i + 1)
        elif ch == "(" and i > s and text[i - 1] == " ":
            pass
    ends.append(e)
    return sorted(set(x for x in ends if s < x <= e))


def comma_bounds(text, s, e):
    """Like clause_bounds but only commas (not ; : or dashes) cut a unit --
    the tightest 'context' setting short of the highlight itself."""
    ends = [i + 1 for i in range(s, e) if text[i] == "," and i + 1 < e and text[i + 1].isspace()]
    ends.append(e)
    return sorted(set(x for x in ends if s < x <= e))


def units_from_ends(s, ends):
    out, prev = [], s
    for e in ends:
        if e > prev:
            out.append((prev, e))
        prev = e
    return out


def trim_ws(text, s, e):
    while s < e and text[s].isspace():
        s += 1
    while e > s and text[e - 1].isspace():
        e -= 1
    return s, e


def mark_runs(marks):
    runs, i, n = [], 0, len(marks)
    while i < n:
        if marks[i] >= 0:
            j = i
            while j < n and marks[j] >= 0:
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    return runs


_WORD_RE = re.compile(r"\S+")


def _word_window_ranges(p, runs, cfg):
    """Keep a fixed number of context words around each highlight instead of
    a sentence/clause. --word-window 6 --word-side both -> 3 words before +
    the highlight + 3 after; --word-side left -> 6 words before, highlight at
    the end; right -> highlight then 6 words after."""
    text = p.text
    words = [(m.start(), m.end()) for m in _WORD_RE.finditer(text)]
    if not words:
        return [(s, e, s > 0, e < len(text)) for s, e in runs]
    n = cfg.word_window
    if cfg.word_side == "left":
        left_n, right_n = n, 0
    elif cfg.word_side == "right":
        left_n, right_n = 0, n
    else:
        left_n, right_n = n // 2, n - n // 2
    out = []
    for rs, re_ in runs:
        idx = [i for i, (a, b) in enumerate(words) if a < re_ and b > rs]
        if not idx:
            idx = [min(range(len(words)), key=lambda i: abs(words[i][0] - rs))]
        lo = max(0, idx[0] - left_n)
        hi = min(len(words) - 1, idx[-1] + right_n)
        s, e = words[lo][0], words[hi][1]
        out.append([s, e, s > 0, e < len(text)])
    out.sort()
    merged = []
    for c in out:
        if merged and c[0] <= merged[-1][1] + 1:
            m = merged[-1]
            if c[1] > m[1]:
                m[1], m[3] = c[1], c[3]
        else:
            merged.append(c)
    return [tuple(m) for m in merged]


def snippet_ranges(p, cfg):
    """Ranges of p.text to show, each with a flag for 'starts mid-sentence'
    / 'ends mid-sentence'. Based only on where the marks are."""
    text = p.text
    runs = mark_runs(p.marks)
    if not runs:
        return []
    if cfg.word_window > 0:
        return _word_window_ranges(p, runs, cfg)
    if cfg.context == "paragraph" or p.kind == "footnote" and cfg.context != "highlight":
        return [(0, len(text), False, False)] if p.kind != "footnote" or word_count(text) <= cfg.max_words * 2 \
            else _sentence_ranges(p, runs, cfg)
    if cfg.context == "highlight":
        return [(s, e, s > 0, e < len(text)) for s, e in runs]
    return _sentence_ranges(p, runs, cfg)


def _sentence_ranges(p, runs, cfg):
    text = p.text
    ends = sentence_bounds(text)
    lm = LIST_RE.match(text)
    if lm:
        ends = [x for x in ends if x > lm.end()]
    sents = units_from_ends(0, ends)
    chosen = []
    for rs, re_ in runs:
        # a run may span several sentences
        covering = [(s, e) for s, e in sents if s < re_ and e > rs]
        if not covering:
            continue
        ss, se = covering[0][0], covering[-1][1]
        ss, se = trim_ws(text, ss, se)
        if cfg.context in ("clause", "comma") or word_count(text[ss:se]) > cfg.max_words:
            seg = comma_bounds(text, ss, se) if cfg.context == "comma" else clause_bounds(text, ss, se)
            cls = [trim_ws(text, a, b) for a, b in units_from_ends(ss, seg)]
            cls = [c for c in cls if c[1] > c[0]]
            idx = [i for i, (a, b) in enumerate(cls) if a < re_ and b > rs]
            if idx:
                lo, hi = idx[0], idx[-1]
                while word_count(text[cls[lo][0]:cls[hi][1]]) < cfg.min_words and (lo > 0 or hi < len(cls) - 1):
                    if hi < len(cls) - 1:
                        hi += 1
                    if word_count(text[cls[lo][0]:cls[hi][1]]) < cfg.min_words and lo > 0:
                        lo -= 1
                cs, ce = cls[lo][0], cls[hi][1]
                chosen.append([cs, ce, cs > ss, ce < se])
                continue
        chosen.append([ss, se, False, False])
    chosen.sort()
    merged = []
    for c in chosen:
        if merged and c[0] <= merged[-1][1] + 1:
            m = merged[-1]
            if c[1] > m[1]:
                m[1], m[3] = c[1], c[3]
            m[2] = m[2] and c[2] if c[0] == m[0] else m[2]
        else:
            merged.append(c)
    return [tuple(m) for m in merged]

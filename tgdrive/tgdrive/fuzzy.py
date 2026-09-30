"""Words within a small edit distance of a query word, for typo correction ("did you mean").

TG Drive uses rapidfuzz for this where it's installed. rapidfuzz is compiled C++ with no Android
build, so the Android app uses this module instead: the same answer (terms within `max_dist`
Damerau-Levenshtein edits, closest first, ties in vocabulary order), computed with numpy over
every candidate at once. It uses the optimal-string-alignment form of the distance (one
transposition of neighbours counts as one edit), which equals true Damerau-Levenshtein for every
pair within two edits except contrived ones such as "ca" → "abc".

Only ASCII terms take part, as in search.Vocab.corrections.
"""
from __future__ import annotations

from typing import Optional, Sequence

try:
    import numpy as np
except Exception:   # pragma: no cover  (numpy can fail to load on some Android devices)
    np = None


class Matcher:
    def __init__(self, terms: Sequence[str], max_len: int = 32):
        self.terms = [t for t in terms if t.isascii() and 0 < len(t) <= max_len]
        self.max_len = max_len
        self._codes = self._lens = None
        if np is not None and self.terms:
            lens = np.fromiter((len(t) for t in self.terms), dtype=np.int16, count=len(self.terms))
            codes = np.zeros((len(self.terms), max_len), dtype=np.uint8)
            flat = "".join(t.ljust(max_len, "\0") for t in self.terms).encode("ascii")
            codes[:] = np.frombuffer(flat, dtype=np.uint8).reshape(len(self.terms), max_len)
            self._codes, self._lens = codes, lens

    def within(self, word: str, max_dist: int, limit: int = 40) -> list[tuple[str, int]]:
        """(term, distance) for every term at most max_dist edits from word, closest first."""
        if not word.isascii() or not self.terms:
            return []
        if self._codes is not None:
            hits = self._numpy(word, max_dist)
        else:
            hits = [(i, d) for i, t in enumerate(self.terms)
                    if abs(len(t) - len(word)) <= max_dist
                    for d in (osa(word, t, max_dist),) if d is not None]
        hits.sort(key=lambda h: (h[1], h[0]))
        return [(self.terms[i], d) for i, d in hits[:limit]]

    def _numpy(self, word: str, k: int) -> list[tuple[int, int]]:
        n_word = len(word)
        rows = np.nonzero(np.abs(self._lens - n_word) <= k)[0]
        if not len(rows):
            return []
        width = min(self.max_len, n_word + k)
        codes = self._codes[rows, :width].astype(np.int16)
        lens = self._lens[rows].astype(np.intp)
        q = np.frombuffer(word.encode("ascii"), dtype=np.uint8).astype(np.int16)
        n = len(rows)
        cols = np.arange(width + 1, dtype=np.int16)
        prev2 = None
        prev = np.broadcast_to(cols, (n, width + 1)).copy()
        for i in range(1, n_word + 1):
            cur = np.empty_like(prev)
            cur[:, 0] = i
            qc = q[i - 1]
            for j in range(1, width + 1):
                cost = (codes[:, j - 1] != qc).astype(np.int16)
                best = np.minimum(np.minimum(prev[:, j] + 1, cur[:, j - 1] + 1), prev[:, j - 1] + cost)
                if prev2 is not None and j > 1:
                    swap = (codes[:, j - 1] == q[i - 2]) & (codes[:, j - 2] == qc)
                    best = np.where(swap, np.minimum(best, prev2[:, j - 2] + 1), best)
                cur[:, j] = best
            prev2, prev = prev, cur
        dist = prev[np.arange(n), lens]
        ok = np.nonzero(dist <= k)[0]
        return [(int(rows[i]), int(dist[i])) for i in ok]


def osa(a: str, b: str, max_dist: Optional[int] = None) -> Optional[int]:
    """Optimal-string-alignment distance, or None once it is certainly over max_dist."""
    if max_dist is not None and abs(len(a) - len(b)) > max_dist:
        return None
    prev2: Optional[list[int]] = None
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if prev2 is not None and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                v = min(v, prev2[j - 2] + 1)
            cur[j] = v
        if max_dist is not None and min(cur) > max_dist:
            return None
        prev2, prev = prev, cur
    d = prev[len(b)]
    return d if max_dist is None or d <= max_dist else None

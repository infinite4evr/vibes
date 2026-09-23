"""Small helpers: colour names, word counts, rectangle distance, page-range parsing.

Part of stack-highlights; code moved here unchanged from the original single file.
"""
from .constants import NAMED_COLORS


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def color_name(rgb):
    if not rgb or len(rgb) < 3:
        return "yellow"
    return min(NAMED_COLORS, key=lambda n: sum((a - b) ** 2 for a, b in zip(rgb, NAMED_COLORS[n])))


def word_count(s):
    return len(s.split())


def rect_dist(a, b):
    dx = max(0.0, max(a.x0 - b.x1, b.x0 - a.x1))
    dy = max(0.0, max(a.y0 - b.y1, b.y0 - a.y1))
    return (dx * dx + dy * dy) ** 0.5


def parse_pages(spec, n):
    if not spec:
        return list(range(n))
    out = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            a = int(a) if a else 1
            b = int(b) if b else n
            out.extend(range(a - 1, min(b, n)))
        elif part:
            out.append(int(part) - 1)
    return [p for p in out if 0 <= p < n]

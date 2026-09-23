"""Data model: marks, tokens, paragraphs, items and entries.

Part of stack-highlights; code moved here unchanged from the original single file.
"""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
class Mark:
    __slots__ = ("id", "page", "kind", "color", "rects", "comment", "text", "used", "co", "raw", "skipped")

    def __init__(self, mid, page, kind, color, rects, comment):
        self.id, self.page, self.kind, self.color = mid, page, kind, color
        self.rects, self.comment = rects, comment
        self.text, self.used, self.co, self.raw = [], False, set(), False
        self.skipped = False


class Token:
    __slots__ = ("chars", "size", "bold", "sup", "glue", "line_start", "x0", "y0", "x1", "y1")

    def __init__(self):
        self.chars = []  # (c, mark_id, rect, bold)
        self.glue = False
        self.line_start = False

    @property
    def text(self):
        return "".join(c[0] for c in self.chars)


class Para:
    """A run of text as parallel arrays: characters, the mark on each
    character (-1 = unmarked) and the character's box (None for inserted
    spaces). Everything downstream works on these arrays."""

    def __init__(self, page):
        self.page = page
        self.chars, self.marks, self.boxes = [], [], []
        self.kind = "para"      # para | list | footnote | heading | cell
        self.x0 = 0.0
        self.size = 0.0
        self.fn = None          # footnote number, for footnote paragraphs
        self.refs = []          # (char position, marker) footnote references
        self.leadin = None      # Para introducing a list item
        self.amend = set()      # positions of "[" opened by an amendment marker
        self.item_index = None

    @property
    def text(self):
        return "".join(self.chars)

    def has_marks(self):
        return any(m >= 0 for m in self.marks)

    def append_space(self):
        if self.chars and self.chars[-1] != " ":
            self.chars.append(" ")
            self.marks.append(-1)
            self.boxes.append(None)

    def extend(self, other):
        base = len(self.chars)
        if base and other.chars:
            self.append_space()
            base = len(self.chars)
        self.chars += other.chars
        self.marks += other.marks
        self.boxes += other.boxes
        self.refs += [(p + base, n) for p, n in other.refs]
        self.amend |= {p + base for p in other.amend}

    def finalize(self):
        # strip, then let spaces between two chars of the same mark join it,
        # so one highlight spanning several words renders as one bold run
        while self.chars and self.chars[0] == " ":
            for a in (self.chars, self.marks, self.boxes):
                a.pop(0)
            self.refs = [(p - 1, n) for p, n in self.refs]
        while self.chars and self.chars[-1] == " ":
            for a in (self.chars, self.marks, self.boxes):
                a.pop()
        i = 1
        while i < len(self.chars):   # collapse double spaces
            if self.chars[i] == " " and self.chars[i - 1] == " ":
                for a in (self.chars, self.marks, self.boxes):
                    del a[i]
                self.refs = [(q - 1 if q > i else q, n) for q, n in self.refs]
                self.amend = {q - 1 if q > i else q for q in self.amend}
            else:
                i += 1
        for i, c in enumerate(self.chars):
            if c == " " and 0 < i < len(self.chars) - 1:
                l, r = self.marks[i - 1], self.marks[i + 1]
                if l >= 0 and l == r:
                    self.marks[i] = l


class Item:
    __slots__ = ("type", "level", "para", "cells", "page", "table", "bottoms")

    def __init__(self, type_, page, para=None, level=0, cells=None, table=None):
        self.type, self.page, self.para, self.level = type_, page, para, level
        self.cells, self.table = cells, table


class Entry:
    def __init__(self, kind, crumbs, page):
        self.kind = kind          # snippet | row | heading | note | group
        self.crumbs = crumbs      # list of (level, rendered heading)
        self.page = page
        self.lines = []           # list of rendered pieces (list of (text, mark or -1))
        self.subs = []            # (label, pieces)  footnotes / notes
        self.bbox = None
        self.mark_ids = set()
        self.leadin_key = None

"""Document context: body size, running headers/footers, page labels.

Part of stack-highlights; code moved here unchanged from the original single file.
"""
import re
from collections import Counter
from .constants import (
    EDGE_BAND_FRACTION, EDGE_MIN_REPEAT, PAGENUM_BOTTOM_FRACTION, RUNNING_LOCAL_MIN_REPEAT,
    RUNNING_MIN_PAGE_FRACTION,
)


# ---------------------------------------------------------------------------
# Document context: body size, running headers/footers, page labels
# ---------------------------------------------------------------------------
class DocContext:
    def __init__(self, doc, pages, cfg):
        self.doc, self.cfg = doc, cfg
        self.pages = pages
        self.marks = []
        self.notes = []  # (page, rect, text)
        self.running = set()
        self.edge_running = {}  # pno -> keys of page-numbered running heads
        self.edge_hit = None    # "top"/"bottom" when is_running matched one
        self.page_labels = {}
        self.body_size = 11.0
        self.table = None     # active table state across rows/pages
        self.stats = Counter()
        self._survey()

    def _survey(self):
        sizes = Counter()
        margin_keys = Counter()
        edge_cands = []           # (pno, key, offset of its page number)
        allp = list(range(self.doc.page_count))
        sample = set(allp if len(allp) <= 60 else allp[:: max(1, len(allp) // 60)])
        for pno in range(self.doc.page_count):
            page = self.doc[pno]
            h = page.rect.height
            d = page.get_text("dict", flags=0)
            edge_lines = []
            for b in d["blocks"]:
                for l in b.get("lines", []):
                    txt = "".join(s["text"] for s in l["spans"]).strip()
                    if pno in sample:
                        for s in l["spans"]:
                            sizes[round(s["size"], 1)] += len(s["text"].strip())
                    if not txt:
                        continue
                    y0, y1 = l["bbox"][1], l["bbox"][3]
                    edge_lines.append((y0, y1, txt))
                    if y1 < h * self.cfg.margin or y0 > h * (1 - self.cfg.margin):
                        margin_keys[self._key(txt)] += 1
                        if re.fullmatch(r"\d{1,4}", txt) and y0 > h * PAGENUM_BOTTOM_FRACTION:
                            self.page_labels.setdefault(pno, txt)
                        elif re.fullmatch(r"\d{1,4}", txt):
                            self.page_labels.setdefault(pno, txt)
            if edge_lines:
                top = min(edge_lines, key=lambda x: x[0])
                bot = max(edge_lines, key=lambda x: x[1])
                for y0, y1, txt in {top, bot}:
                    if not (y1 < h * EDGE_BAND_FRACTION or y0 > h * (1 - EDGE_BAND_FRACTION)):
                        continue
                    m = re.match(r"^(\d{1,4})\s", txt) or re.search(r"\s(\d{1,4})$", txt)
                    if m:
                        edge_cands.append((pno, self._key(txt), int(m.group(1)) - pno))
        if sizes:
            self.body_size = sizes.most_common(1)[0][0]
        need = max(3, int(self.doc.page_count * RUNNING_MIN_PAGE_FRACTION))
        # A fixed book title often repeats on half the pages, while a chapter
        # title may repeat only on the odd (or even) pages of that chapter.
        # Requiring 30% of the *whole book* therefore misses chapter-name
        # running heads.  Text physically inside the margin is safe to strip
        # after a few exact repeats; structural labels such as STATE AMENDMENT
        # are excluded because, in legislation, they can legitimately start at
        # the very top of a page.
        self.running = {
            k for k, v in margin_keys.items()
            if k == "#" or v >= need or (
                v >= RUNNING_LOCAL_MIN_REPEAT
                and re.search(r"[a-z]", k)
                and not k.startswith(("stateamendment", "chapter", "part"))
            )
        }
        # page-numbered running heads: the page number must follow the book's
        # dominant page offset (so a stray number in body text never qualifies)
        offsets = Counter(off for _p, _k, off in edge_cands)
        if offsets:
            best, n_best = offsets.most_common(1)[0]
            if n_best >= need:
                hits = [(p, k) for p, k, off in edge_cands if off == best]
                reps = Counter(k for _p, k in hits)
                for p, k in hits:
                    if reps[k] >= EDGE_MIN_REPEAT:
                        self.edge_running.setdefault(p, set()).add(k)

    @staticmethod
    def _key(txt):
        return re.sub(r"\d+", "#", re.sub(r"\s+", "", txt)).strip().lower()

    def is_running(self, page, rect, txt):
        self.edge_hit = None
        if not self.cfg.strip_running:
            return False
        h = page.rect.height
        if rect.y1 < h * self.cfg.margin or rect.y0 > h * (1 - self.cfg.margin):
            if self._key(txt) in self.running:
                return True
        edge = self.edge_running.get(page.number)
        if edge and (rect.y1 < h * EDGE_BAND_FRACTION or rect.y0 > h * (1 - EDGE_BAND_FRACTION)):
            if self._key(txt) in edge:
                self.edge_hit = "top" if rect.y1 < h * EDGE_BAND_FRACTION else "bottom"
                return True
        return False

    def label(self, pno):
        return self.page_labels.get(pno, str(pno + 1))

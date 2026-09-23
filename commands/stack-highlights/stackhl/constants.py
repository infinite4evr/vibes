"""Constants, layout thresholds and running-header settings.

Part of stack-highlights; code moved here unchanged from the original single file.
"""
import re


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ANNOT_KINDS = {8: "highlight", 9: "underline", 10: "squiggly", 11: "strikeout"}
NOTE_TYPES = {0, 2}  # Text (sticky note), FreeText

NAMED_COLORS = {
    "yellow": (1.0, 0.9, 0.0), "orange": (1.0, 0.6, 0.0), "red": (1.0, 0.35, 0.35),
    "pink": (1.0, 0.5, 0.8), "green": (0.3, 0.85, 0.3), "blue": (0.2, 0.6, 1.0),
    "purple": (0.6, 0.4, 0.9), "gray": (0.6, 0.6, 0.6),
}

ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "viz", "no", "nos",
    "art", "arts", "sec", "secs", "cl", "cls", "sub", "govt", "rs", "co", "ltd",
    "inc", "vol", "vols", "ch", "fig", "para", "paras", "approx", "cf", "al", "hon",
    "regn", "ord", "pp", "ss", "ibid", "sch", "cr", "lt", "gen", "col", "capt",
    "sri", "smt", "shri", "hon'ble", "u/s", "wef", "resp", "min", "max",
}

SENT_PUNCT = ".!?"
CLOSERS = "\"'”’)]"
OPENERS = "\"'“‘(["
DASHES = "—–"

LIST_RE = re.compile(r"^\s*\[*(\(?\d{1,3}(?:[a-z]|-?[A-Z]{1,3})?[.)]|\((?:[a-zA-Z]{1,4}|[ivxlc]{1,6}|\d{1,3}[A-Za-z]{0,2})\)\]?|[ivxlc]{1,6}[.)]|[a-hA-H][.)]|[•●▪■◦▸►\-–])\s")
FN_MARK_RE = re.compile(r"^\d{1,3}[a-z]?$")
FOOTNOTE_START_RE = re.compile(r"^\s*(\d{1,3}[a-z]?)[.)]?\s")
CAPTION_RE = re.compile(r"^\s*(Table|Figure|Fig\.|Chart|Box)\s+[\dIVX]+([.\-]\d+)*\b", re.I)
# ---------------------------------------------------------------------------
# Layout thresholds
#
# Heuristics for turning geometry back into structure. Values are in points
# unless the name ends in _FRACTION (a fraction of page width/height, line
# height, or body font size). They are collected here -- rather than scattered
# as bare numbers -- so a publisher whose layout differs can be tuned in one
# place. Several are also exposed as CLI flags (see build_parser); those
# defaults live on the argument, not here. Numbers that happen to share a
# value below are DIFFERENT knobs -- do not merge them.
# ---------------------------------------------------------------------------

# Running headers / footers and page numbers
PAGENUM_BOTTOM_FRACTION = 0.5        # a page number sits below this fraction of page height
RUNNING_MIN_PAGE_FRACTION = 0.3      # a header/footer must repeat on >= this fraction of pages
RUNNING_LOCAL_MIN_REPEAT = 3            # repeated text in the physical margin is also a running head
# Page-numbered running heads that change per chapter ("Advent of the Europeans
# in India * 23" on odd pages) never repeat on 30% of pages, and may sit below
# the --margin band. They are caught by their page number instead: the topmost
# or bottommost line of a page, within this band, that starts or ends with a
# number tracking the PDF page index at the book's usual offset.
EDGE_BAND_FRACTION = 0.2             # top/bottom page fraction searched for such heads
EDGE_MIN_REPEAT = 3                  # ... and the same head must occur on >= this many pages

# Highlighter-colour detection (a coloured fill counts as a highlight)
HILITE_MIN_BRIGHTNESS = 0.75         # brightest RGB channel at least this
HILITE_MIN_SATURATION = 0.3          # (max-min)/max at least this (excludes grey boxes)
HILITE_MIN_HEIGHT = 5                # fill height in points: floor ...
HILITE_MAX_HEIGHT = 40               # ... and ceiling (excludes full-page tints)
MARK_HIT_SLOP = 0.5                  # pt of slack when testing a glyph centre against a mark rect

# Headings
ALLCAPS_HEADING_FRACTION = 0.85      # >= this share of letters upper-case -> an all-caps heading
ALLCAPS_MIN_LETTERS = 3              # ... but only if it has more than this many letters
HEADING_STACK_X_SLOP = 2            # pt of indent slack when popping the heading stack
SMALL_STYLE_SIZE_DELTA = 0.5         # a run this many pt smaller than its paragraph is a style shift

# Tables and columns
ROW_OVERLAP_FRACTION = 0.5           # vertical overlap (of line height) for two blocks to share a row
NARROW_COLUMN_FRACTION = 0.3         # a block narrower than this fraction of page width may be a column
SIDE_BY_SIDE_GAP_FRACTION = 0.5      # horizontal gap (of line height) that splits side-by-side lines
TABLE_CONTINUATION_GAP_FRACTION = 0.6  # vertical gap (of line height) a table row may span to continue
TABLE_ALIGN_SLOP = 12                  # column starts must repeat this closely across rows
TABLE_MAX_ROW_GAP = 28                 # pt: a new row much farther away ends the table

# Common publisher boilerplate that must never become structural context.  It
# is intentionally tiny and conservative: these lines carry no study content,
# but if they are promoted to headings they can incorrectly own many pages.
BOILERPLATE_RE = re.compile(r"^this page is intentionally (?:left )?blank[.!]?$", re.I)
STRUCTURAL_HEADING_RE = re.compile(r"^(?:CHAPTER|PART)\s+[A-Z0-9IVXLC]+(?:[-–—][A-Z0-9IVXLC]+)?\b", re.I)
STATE_AMEND_RE = re.compile(r"^STATE\s+AMENDMENTS?$", re.I)
SECTION_RUNIN_RE = re.compile(r"^[\[\(\"'“‘]*\d+[A-Z]*(?:-[A-Z])?\.\s*", re.I)

# List items
LIST_LINE_SHORT_FRACTION = 0.2       # a line ending this fraction of the block short ends the item
LIST_INDENT_SLOP = 6                 # pt a continuation line may sit left of the item's text

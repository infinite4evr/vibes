"""stack-highlights, split into modules.

Importing this package gives the same names the original single-file script
defined, so `stack-highlights` (the launcher next to this folder) and the
unit tests see exactly the same namespace as before.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from .backend import pymupdf
from .constants import (
    ABBREVIATIONS, ALLCAPS_HEADING_FRACTION, ALLCAPS_MIN_LETTERS, ANNOT_KINDS, BOILERPLATE_RE,
    CAPTION_RE, CLOSERS, DASHES, EDGE_BAND_FRACTION, EDGE_MIN_REPEAT, FN_MARK_RE,
    FOOTNOTE_START_RE, HEADING_STACK_X_SLOP, HILITE_MAX_HEIGHT, HILITE_MIN_BRIGHTNESS,
    HILITE_MIN_HEIGHT, HILITE_MIN_SATURATION, LIST_INDENT_SLOP, LIST_LINE_SHORT_FRACTION,
    LIST_RE, MARK_HIT_SLOP, NAMED_COLORS, NARROW_COLUMN_FRACTION, NOTE_TYPES, OPENERS,
    PAGENUM_BOTTOM_FRACTION, ROW_OVERLAP_FRACTION, RUNNING_LOCAL_MIN_REPEAT,
    RUNNING_MIN_PAGE_FRACTION, SECTION_RUNIN_RE, SENT_PUNCT, SIDE_BY_SIDE_GAP_FRACTION,
    SMALL_STYLE_SIZE_DELTA, STATE_AMEND_RE, STRUCTURAL_HEADING_RE, TABLE_ALIGN_SLOP,
    TABLE_CONTINUATION_GAP_FRACTION, TABLE_MAX_ROW_GAP,
)
from .helpers import color_name, parse_pages, rect_dist, word_count
from .model import Entry, Item, Mark, Para, Token
from .context import DocContext
from .marks import collect_marks, doc_has_annotation_marks, looks_like_highlighter
from .tokens import char_mark, line_tokens, RAW_FLAGS, snap_token_marks
from .paragraphs import strip_amendments, _strip_para, tokens_to_para
from .headings import line_is_heading, split_runin
from .tables import (
    column_for_x, continues_table, items_ended_with_row, make_row, relabel_columns, TableState,
    wraps_into_last_row,
)
from .layout import (
    _attach_subscript_blocks, _bands_align, _block_text, classify_para,
    _looks_like_split_heading, page_items, split_side_by_side, text_block_items,
)
from .passes import (
    assign_leadins, attach_table_headers, DANGLING, demote_titles, join_continuations,
    merge_footnote_continuations, TERMINAL,
)
from .segmentation import (
    clause_bounds, comma_bounds, is_abbrev, mark_runs, sentence_bounds, _sentence_ranges,
    snippet_ranges, trim_ws, units_from_ends, _WORD_RE, _word_window_ranges,
)
from .rendering import (
    leadin_text, mark_style, MARK_STYLES, md_escape, md_guard, _ORDERED_RE, _PAREN_RE,
    render_range,
)
from .checklist import check_in_book_json, check_in_book_md, check_in_book_text, unplaced_marks
from .entries import build_entries, finalize_coverage, mark_bbox
from .writers import runs_from_md, write_json, write_markdown, write_text
from .driver import coverage_report, find_pdfs, process_pdf, render
from .cli import build_parser, config_from_args
from .config import (
    _apply_table, BUILTIN_PRESETS, BUILTIN_PROFILES, _coerce, _config_files, explain,
    _load_toml, _norm_key, resolve_args, tomllib, _valid_dests,
)
from .app import main

__all__ = [
    'argparse',
    'json',
    'os',
    're',
    'sys',
    'Counter',
    'Path',
    'pymupdf',
    'ABBREVIATIONS',
    'ALLCAPS_HEADING_FRACTION',
    'ALLCAPS_MIN_LETTERS',
    'ANNOT_KINDS',
    'BOILERPLATE_RE',
    'CAPTION_RE',
    'CLOSERS',
    'DASHES',
    'EDGE_BAND_FRACTION',
    'EDGE_MIN_REPEAT',
    'FN_MARK_RE',
    'FOOTNOTE_START_RE',
    'HEADING_STACK_X_SLOP',
    'HILITE_MAX_HEIGHT',
    'HILITE_MIN_BRIGHTNESS',
    'HILITE_MIN_HEIGHT',
    'HILITE_MIN_SATURATION',
    'LIST_INDENT_SLOP',
    'LIST_LINE_SHORT_FRACTION',
    'LIST_RE',
    'MARK_HIT_SLOP',
    'NAMED_COLORS',
    'NARROW_COLUMN_FRACTION',
    'NOTE_TYPES',
    'OPENERS',
    'PAGENUM_BOTTOM_FRACTION',
    'ROW_OVERLAP_FRACTION',
    'RUNNING_LOCAL_MIN_REPEAT',
    'RUNNING_MIN_PAGE_FRACTION',
    'SECTION_RUNIN_RE',
    'SENT_PUNCT',
    'SIDE_BY_SIDE_GAP_FRACTION',
    'SMALL_STYLE_SIZE_DELTA',
    'STATE_AMEND_RE',
    'STRUCTURAL_HEADING_RE',
    'TABLE_ALIGN_SLOP',
    'TABLE_CONTINUATION_GAP_FRACTION',
    'TABLE_MAX_ROW_GAP',
    'color_name',
    'parse_pages',
    'rect_dist',
    'word_count',
    'Entry',
    'Item',
    'Mark',
    'Para',
    'Token',
    'DocContext',
    'collect_marks',
    'doc_has_annotation_marks',
    'looks_like_highlighter',
    'RAW_FLAGS',
    'char_mark',
    'line_tokens',
    'snap_token_marks',
    '_strip_para',
    'strip_amendments',
    'tokens_to_para',
    'line_is_heading',
    'split_runin',
    'TableState',
    'column_for_x',
    'continues_table',
    'items_ended_with_row',
    'make_row',
    'relabel_columns',
    'wraps_into_last_row',
    '_attach_subscript_blocks',
    '_bands_align',
    '_block_text',
    '_looks_like_split_heading',
    'classify_para',
    'page_items',
    'split_side_by_side',
    'text_block_items',
    'DANGLING',
    'TERMINAL',
    'assign_leadins',
    'attach_table_headers',
    'demote_titles',
    'join_continuations',
    'merge_footnote_continuations',
    '_WORD_RE',
    '_sentence_ranges',
    '_word_window_ranges',
    'clause_bounds',
    'comma_bounds',
    'is_abbrev',
    'mark_runs',
    'sentence_bounds',
    'snippet_ranges',
    'trim_ws',
    'units_from_ends',
    'MARK_STYLES',
    '_ORDERED_RE',
    '_PAREN_RE',
    'leadin_text',
    'mark_style',
    'md_escape',
    'md_guard',
    'render_range',
    'build_entries',
    'finalize_coverage',
    'mark_bbox',
    'runs_from_md',
    'write_json',
    'write_markdown',
    'write_text',
    'coverage_report',
    'find_pdfs',
    'process_pdf',
    'render',
    'build_parser',
    'config_from_args',
    'BUILTIN_PRESETS',
    'BUILTIN_PROFILES',
    '_apply_table',
    '_coerce',
    '_config_files',
    '_load_toml',
    '_norm_key',
    '_valid_dests',
    'explain',
    'resolve_args',
    'tomllib',
    'main',
    'unplaced_marks',
    'check_in_book_md',
    'check_in_book_text',
    'check_in_book_json',
]

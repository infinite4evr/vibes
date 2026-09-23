#!/usr/bin/env python3
"""Fast unit tests for stack-highlights internals.

Uses stdlib unittest so `make units` has no pytest dependency.
"""
from __future__ import annotations
import importlib.machinery
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SH = importlib.machinery.SourceFileLoader("stack_highlights", str(ROOT / "stack-highlights")).load_module()

class UnitTests(unittest.TestCase):
    def test_sentence_bounds_do_not_split_abbreviations(self):
        s = "Dr. Rao met the board. It approved the plan."
        ends = SH.sentence_bounds(s)
        chunks=[]; start=0
        for e in ends:
            chunks.append(s[start:e].strip()); start=e
        self.assertEqual(chunks, ["Dr. Rao met the board.", "It approved the plan."])

    def test_sentence_bounds_do_not_split_decimal(self):
        s = "Growth was 3.5 per cent. It later improved."
        ends = SH.sentence_bounds(s)
        chunks=[]; start=0
        for e in ends:
            chunks.append(s[start:e].strip()); start=e
        self.assertEqual(chunks, ["Growth was 3.5 per cent.", "It later improved."])

    def test_markdown_ordered_marker_is_escaped_without_changing_number(self):
        self.assertEqual(SH.md_guard("3. Actual text"), "3\\. Actual text")
        self.assertEqual(SH.md_guard("(ii) Actual text"), "\\(ii) Actual text")

    def test_amendment_brackets_removed_but_content_kept(self):
        p = SH.Para(1)
        txt = "[(1) This Act applies]"
        p.chars = list(txt)
        p.marks = [-1] * len(txt)
        p.boxes = [None] * len(txt)
        p.amend = {0}
        p.refs = []
        carry = SH._strip_para(p, 0)
        self.assertEqual(carry, 0)
        self.assertEqual(p.text, "(1) This Act applies")

    def _tok(self, text, *, line_start=False, glue=False, size=10.0):
        t = SH.Token(); t.size=size; t.bold=False; t.sup=False; t.glue=glue; t.line_start=line_start; t.x0=t.y0=t.x1=t.y1=0.0
        t.chars=[(c,-1,None,False) for c in text]
        return t

    def test_hyphen_join_default_preserves_hyphen(self):
        cfg = types.SimpleNamespace(keep_markers=False, dehyphenate=False)
        p = SH.tokens_to_para([self._tok("co-"), self._tok("operation", line_start=True)], 1, cfg)
        self.assertEqual(p.text, "co-operation")

    def test_hyphen_join_dehyphenate_drops_lowercase_linebreak_hyphen(self):
        cfg = types.SimpleNamespace(keep_markers=False, dehyphenate=True)
        p = SH.tokens_to_para([self._tok("co-"), self._tok("operation", line_start=True)], 1, cfg)
        self.assertEqual(p.text, "cooperation")

    def test_hyphen_join_does_not_destroy_capital_compound(self):
        cfg = types.SimpleNamespace(keep_markers=False, dehyphenate=True)
        p = SH.tokens_to_para([self._tok("Anglo-"), self._tok("Indian", line_start=True)], 1, cfg)
        self.assertEqual(p.text, "Anglo-Indian")

    def test_runs_from_md_roundtrip_and_escaping(self):
        runs = SH.runs_from_md(r"Context **marked words** and \(1\) literal.")
        self.assertEqual(runs, [
            {"text":"Context ","mark":False,"italic":False},
            {"text":"marked words","mark":True,"italic":False},
            {"text":" and (1) literal.","mark":False,"italic":False},
        ])

    def test_runs_from_md_bold_italic_mark(self):
        runs = SH.runs_from_md("A ***red mark*** here")
        self.assertTrue(runs[1]["mark"])
        self.assertTrue(runs[1]["italic"])
        self.assertEqual(runs[1]["text"], "red mark")

    # --- "Check in book" list -------------------------------------------------
    def _ctx(self, marks, labels=None):
        labels = labels or {}
        return types.SimpleNamespace(marks=marks, label=lambda pno: labels.get(pno, str(pno + 1)))

    def _mark(self, page, text="", raw=False, used=False, kind="highlight", comment=""):
        m = SH.Mark(0, page, kind, "yellow", [], comment)
        m.text, m.raw, m.used = list(text), raw, used
        return m

    def test_check_list_uses_the_same_three_reasons_as_the_coverage_line(self):
        marks = [self._mark(0, "placed", raw=True, used=True),
                 self._mark(1, "", raw=True),                   # part of a word
                 self._mark(2, "", raw=False),                  # no text (image)
                 self._mark(3, "lost text", raw=True)]          # text but not placed
        got = [(m.page, r) for m, r in SH.unplaced_marks(self._ctx(marks))]
        self.assertEqual(got, [(1, "part_word"), (2, "no_text"), (3, "not_placed")])

    def test_check_list_absent_when_everything_placed(self):
        ctx = self._ctx([self._mark(0, "ok", raw=True, used=True)])
        self.assertEqual(SH.check_in_book_md(ctx), "")
        self.assertEqual(SH.check_in_book_text(ctx), "")
        self.assertEqual(SH.check_in_book_json(ctx), [])

    def test_check_list_markdown_heading_level_page_labels_and_no_bold(self):
        ctx = self._ctx([self._mark(4, "a *starred* phrase", raw=True, kind="underline", comment="revise")],
                        labels={4: "17"})
        md = SH.check_in_book_md(ctx, level_shift=1)
        self.assertIn("\n## Check in book\n", md)
        self.assertIn("- p. 5 (printed page 17): An underline on “a \\*starred\\* phrase” could not be placed", md)
        self.assertIn("Your note there: “revise”.", md)
        self.assertNotIn("**", md)   # bold means "you highlighted this" in the notes

    def test_unwritable_character_does_not_lose_the_output(self):
        # A lone surrogate (possible from a PDF with a broken font map) cannot
        # be encoded as UTF-8; the notes must still be written, with a warning.
        import contextlib, io, sys, tempfile
        sys.path.insert(0, str(ROOT))
        from stackhl.app import write_output
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "notes.md"
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                write_output(out, "**kept** a\ud800b and the rest\n")
            self.assertEqual(out.read_text(encoding="utf-8"), "**kept** a\ufffdb and the rest\n")
            self.assertIn("1 unreadable character", err.getvalue())
            write_output(out, "plain text\n")          # normal text: written as is, no warning
            self.assertEqual(out.read_text(encoding="utf-8"), "plain text\n")

if __name__ == "__main__":
    unittest.main(verbosity=2)

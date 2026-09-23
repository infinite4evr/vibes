#!/usr/bin/env python3
"""PDF-step safety: characters LaTeX cannot handle never stop a run.

Checks md-to-pdf (with its md-to-pdf-safety.py), recall-sheet and notes-recall
end to end, making real PDFs. The tools are found in the commands folder this
project lives in (../<tool>/<tool> next to the stack-highlights folder), or
in $COMMANDS_DIR. Without pandoc, xelatex, md-to-pdf or its safety helper it
prints SKIP and passes, like the real-book coverage check. About a minute.

What it protects:
  * clean text gives exactly the PDF that pandoc gave directly, no warnings;
  * an invisible control character (the ^^G that stopped the merged-PDF run)
    is removed with a warning naming its line;
  * a 3,000-letter run without spaces (a text layer that lost its spaces)
    is split into lines up front -- LaTeX can hang on it otherwise;
  * a note LaTeX cannot print ($#$ read as maths) is printed as plain text,
    a raw row LaTeX cannot print is left out -- each with a warning -- and
    everything else is still in the PDF; the input file is not changed;
  * characters the fonts cannot draw are listed instead of vanishing silently;
  * a broken pandoc/LaTeX setup is reported as such (no endless search);
  * a hung LaTeX run is stopped by the time limit instead of blocking;
  * recall-sheet survives the same characters and labels its rows;
  * notes-recall still makes the notes PDF when the recall sheet fails.
"""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
COMMANDS = Path(os.environ.get("COMMANDS_DIR") or ROOT.parent)


def tool(name):
    for cand in (COMMANDS / name / name, COMMANDS / name):
        if cand.is_file():
            return str(cand)
    return shutil.which(name)


MD2PDF = tool("md-to-pdf")
HELPER = MD2PDF and Path(MD2PDF).resolve().parent / "md-to-pdf-safety.py"
RECALL, NOTES_RECALL = tool("recall-sheet"), tool("notes-recall")
MISSING = [n for n, ok in (("pandoc", shutil.which("pandoc")), ("xelatex", shutil.which("xelatex")),
                           ("md-to-pdf", MD2PDF), ("md-to-pdf-safety.py", HELPER and HELPER.is_file()))
           if not ok]


def pdf_text(path):
    try:
        import pymupdf
    except ImportError:
        import fitz as pymupdf
    with pymupdf.open(path) as doc:
        return [" ".join(page.get_text().split()) for page in doc]


def run(cmd, env=None, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                          env={**os.environ, **(env or {})}, **kw)


MIXED = (
    "# mixed.pdf\n\n"                                                        # 1
    "## Chapter 1\n\n"                                                       # 3
    "**First normal note** stays exactly as it is.\n\n"                      # 5
    "**b)** \x07Intangible real account includes accounts.\n\n"              # 7  control char
    "Price rule: **$#$ marker** in an accounting table.\n\n"                 # 9  read as maths
    "Run-together text: " + "Summarizingtheclassifiedtransactions" * 90 + "\n\n"   # 11 huge word
    "```{=latex}\n% note: a broken raw row\n\\undefinedcommandhere{x}\n```\n\n"    # 13 raw row
    "Note (p. 1): symbols [\u16a0\u16a1\u16a2]\n\n"                          # 18 no glyphs (runes)
    "**Last normal note** is printed too.\n"                                 # 20
)


@unittest.skipIf(MISSING, "needs " + ", ".join(MISSING))
class PdfSafety(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp(prefix="pdfsafety-"))

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def write(self, name, text):
        p = self.td / name
        p.write_text(text, encoding="utf-8")
        return p

    def fake_pandoc(self, script):
        """A folder with a fake `pandoc`, to put first on PATH."""
        d = self.td / "fakebin"
        d.mkdir()
        (d / "pandoc").write_text("#!/bin/sh\n" + script + "\n")
        (d / "pandoc").chmod(0o755)
        return {"PATH": f"{d}{os.pathsep}{os.environ['PATH']}"}

    def test_clean_notes_give_exactly_the_pdf_pandoc_gave_directly(self):
        md = self.write("clean.md", "# book.pdf\n\n## Part\n\n**Marked** words and context.\n\n"
                                    "- a list item with **a mark**\n\n> Note: a comment\n")
        a, b = self.td / "direct.pdf", self.td / "safe.pdf"
        self.assertEqual(run([MD2PDF, "-s", "12", str(md), str(a)], env={"MD2PDF_SAFETY": "off"}).returncode, 0)
        r = run([MD2PDF, "-s", "12", str(md), str(b)])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(pdf_text(a), pdf_text(b))
        self.assertNotIn("warning", r.stderr)
        self.assertIn("Wrote", r.stdout)

    def test_bad_notes_are_named_and_everything_else_is_printed(self):
        md = self.write("mixed.md", MIXED)
        before = md.read_bytes()
        out = self.td / "mixed.pdf"
        r = run([MD2PDF, "-s", "12", str(md), str(out)])
        err = r.stderr
        self.assertEqual(r.returncode, 0, err)
        self.assertTrue(out.is_file())
        self.assertIn("mixed.md line 7: removed invisible character(s) U+0007", err)
        self.assertIn("mixed.md line 11: split a 3,240-character run without spaces into lines", err)
        self.assertRegex(err, r"mixed\.md line 9: .*\$#\$.*\(You can't use `macro parameter character #' "
                              r"in math mode\.\); printed it as plain text")
        self.assertRegex(err, r"“a broken raw row” -- LaTeX could not print this .*left it out")
        self.assertRegex(err, r"\u16a0.*U\+16A0.*mixed\.md line 18")
        self.assertIn("1 note(s) printed as plain text and 1 left out", err)
        text = " ".join(pdf_text(out))
        for kept in ("First normal note", "Intangible real account", "$#$ marker",
                     "Summarizingtheclassified", "Last normal note"):
            self.assertIn(kept, text)
        self.assertNotIn("undefinedcommandhere", text)
        self.assertEqual(md.read_bytes(), before, "the input Markdown must not be changed")

    def test_a_broken_setup_is_reported_not_searched(self):
        env = self.fake_pandoc('echo "! LaTeX Error: File lmodern.sty not found." >&2\nexit 43')
        md = self.write("n.md", "one\n\ntwo\n\nthree\n")
        r = run([MD2PDF, str(md), str(self.td / "n.pdf")], env=env)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("setup", r.stderr)
        self.assertIn("lmodern.sty", r.stderr)
        self.assertNotIn("finding the note", r.stderr)

    def test_a_hung_latex_is_stopped_by_the_time_limit(self):
        env = self.fake_pandoc("sleep 600")
        env["MD2PDF_TIMEOUT"] = "2"
        md = self.write("h.md", "one\n\ntwo\n")
        r = run([MD2PDF, str(md), str(self.td / "h.pdf")], env=env, timeout=60)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("did not finish within 2 seconds", r.stderr)

    @unittest.skipUnless(RECALL, "needs recall-sheet")
    def test_recall_sheet_survives_invisible_characters_and_labels_rows(self):
        md = self.write("book.md", "# book.pdf\n\n## Accounts\n\n"
                                   "**b)** \x07Intangible real account includes **goodwill** and patents.\n\n"
                                   "Nominal accounts relate to **expenses and losses**.\n\n"
                                   "**Garbled:** " + "Summarizingtheclassified" * 25 + "\n")
        out = self.td / "book_recall.pdf"
        r = run([sys.executable, RECALL, str(md), "-o", str(out), "-s", "12", "--right", "bold",
                 "--keep-md", "--md2pdf-cmd", MD2PDF])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("removed invisible character(s) U+0007", r.stderr)
        self.assertIn("split a 600-character run without spaces", r.stderr)
        self.assertIn("Intangible real account", " ".join(pdf_text(out)))
        self.assertIn("% note: ", (self.td / "book_recall.md").read_text(encoding="utf-8"))

    def _commands_tree(self, failing_recall=False):
        """A throw-away commands folder: the real tools, optionally with a
        recall-sheet that always fails."""
        root = self.td / "commands"
        for name in ("stack-highlights", "md-to-pdf", "recall-sheet"):
            (root / name).mkdir(parents=True)
            real = Path(tool(name) if name != "stack-highlights" else ROOT / "stack-highlights")
            if name == "recall-sheet" and failing_recall:
                stub = root / name / name
                stub.write_text("#!/bin/sh\necho 'recall-sheet: simulated failure' >&2\nexit 1\n")
                stub.chmod(0o755)
            else:
                (root / name / name).symlink_to(real.resolve())
        (root / "notes-recall").mkdir()
        shutil.copy(NOTES_RECALL, root / "notes-recall" / "notes-recall")
        books = self.td / "books"
        books.mkdir()
        shutil.copy(TESTS / "fixtures" / "prose_list.pdf", books / "prose_list.pdf")
        return root / "notes-recall" / "notes-recall", books

    @unittest.skipUnless(RECALL and NOTES_RECALL, "needs recall-sheet and notes-recall")
    def test_notes_recall_makes_everything(self):
        nr, books = self._commands_tree()
        out = self.td / "out"
        r = run(["bash", str(nr), str(books), "Dump", "12", "-o", str(out)])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for f in ("Dump.md", "Dump.pdf", "Dump_recall.pdf"):
            self.assertTrue((out / f).is_file(), f)

    @unittest.skipUnless(RECALL and NOTES_RECALL, "needs recall-sheet and notes-recall")
    def test_notes_recall_still_makes_the_notes_pdf_when_the_recall_sheet_fails(self):
        nr, books = self._commands_tree(failing_recall=True)
        out = self.td / "out"
        r = run(["bash", str(nr), str(books), "Dump", "12", "-o", str(out)])
        self.assertEqual(r.returncode, 1)
        self.assertTrue((out / "Dump.pdf").is_file(), "the notes PDF must still be made")
        self.assertIn("Not made:", r.stdout)
        self.assertIn("recall sheet", r.stdout)


if __name__ == "__main__":
    if MISSING:
        print("SKIP pdf-safety checks (needs " + ", ".join(MISSING) + ")")
        sys.exit(0)
    unittest.main(verbosity=2)

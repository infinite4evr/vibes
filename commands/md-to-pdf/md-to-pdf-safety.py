#!/usr/bin/env python3
"""
md-to-pdf-safety.py -- how md-to-pdf runs pandoc, so that characters LaTeX
cannot handle never stop the whole PDF.

md-to-pdf calls it as:

    python3 md-to-pdf-safety.py INPUT OUTPUT -- <pandoc options>

and it runs `pandoc INPUT -o OUTPUT <pandoc options>`. When the text is fine
that is all it does: pandoc runs once, on your file, exactly as before. It
only steps in for characters LaTeX cannot handle:

  * Invisible control characters (e.g. U+0007, which some PDFs use for
    bullets) make LaTeX stop with "Text line contains an invalid character".
    They print nothing anyway, so they are removed, with a warning naming
    the line.
  * A run of 500+ characters without a space (a PDF whose text layer lost
    its spaces) is split into lines, with a warning: LaTeX cannot print one
    "word" that long, and may even hang on it.
  * If LaTeX still stops, the note that causes it is found and printed as
    plain text instead (for example "$#$" that pandoc read as maths). If
    even that fails, the note is left out of the PDF. Either way there is a
    warning naming the line, and the PDF is made from everything else.
  * Characters the fonts cannot draw come out blank. LaTeX does not stop
    for them; they are listed with the line they are on, instead of
    vanishing silently.
  * Every pandoc run has a time limit (MD2PDF_TIMEOUT seconds; by default
    5 minutes plus 2 minutes per MB of text), so a hang is reported like
    any other failure instead of blocking forever.

Your file is never changed: cleaning and repairs happen on a temporary copy.
"""
import os
import re
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

# C0 controls except tab/newline/carriage return, DEL, and C1 controls.
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
LONG_RUN = 500        # this many characters without a space cannot be a real word
PIECE = 80            # ... so it is split into pieces of about this many characters
MISSING_RE = re.compile(r"Missing character: There is no (.+?) \(U\+([0-9A-Fa-f]+)\)")
NOTE_RE = re.compile(r"^%\s*note:\s*(.*)$")        # recall-sheet labels its rows this way
FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
MAX_LISTED = 20                                   # warnings listed before "... and N more"
MAX_RUNS = 400                                    # safety cap while searching for bad notes


def warn(msg):
    print(f"  warning  {msg}", file=sys.stderr)


def note(msg):
    print(f"  note     {msg}", file=sys.stderr)


def snippet(text, n=70):
    text = " ".join(CONTROL.sub("", text).split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# reading and cleaning
# ---------------------------------------------------------------------------
def read_text(path):
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        # pandoc reads a non-UTF-8 file as Latin-1; do the same.
        return data.decode("latin-1"), "latin-1"


def split_long_runs(line):
    """Split every run of LONG_RUN+ non-space characters into PIECE-sized
    pieces, cutting only between two letters/digits (never inside a
    Markdown marker or escape). Returns (new line, lengths of the runs)."""
    lengths = []

    def cut(m):
        w = m.group(0)
        lengths.append(len(w))
        pieces, last, k = [], 0, PIECE
        while k < len(w):
            if w[k - 1].isalnum() and w[k].isalnum():
                pieces.append(w[last:k])
                last, k = k, k + PIECE
            else:
                k += 1
        pieces.append(w[last:])
        return " ".join(pieces)

    return re.sub(r"\S{%d,}" % LONG_RUN, cut, line), lengths


def clean_text(text, name):
    """Remove control characters and split impossibly long runs; one warning
    per line changed. Returns (clean text, number of lines changed)."""
    lines = text.split("\n")
    hits, fence = [], None
    for i, ln in enumerate(lines):
        reasons = []
        found = CONTROL.findall(ln)
        if found:
            codes = ", ".join(sorted({f"U+{ord(c):04X}" for c in found}))
            reasons.append(f"removed invisible character(s) {codes} (LaTeX cannot print them)")
            ln = CONTROL.sub("", ln)
        m = FENCE_RE.match(ln)
        if fence:                          # inside ``` ... ```: raw LaTeX, leave it alone
            st = ln.strip()
            if st and set(st) == {fence[0]} and len(st) >= len(fence):
                fence = None
        elif m:
            fence = m.group(1)
        else:
            ln, lengths = split_long_runs(ln)
            if lengths:
                reasons.append("split " + ", ".join(f"a {n:,}-character" for n in lengths)
                               + " run without spaces into lines (LaTeX cannot print one word that long)")
        if reasons:
            hits.append((i + 1, "; ".join(reasons), lines[i]))
            lines[i] = ln
    for n, why, ln in hits[:MAX_LISTED]:
        warn(f"{name} line {n}: {why}: “{snippet(ln)}”")
    if len(hits) > MAX_LISTED:
        warn(f"{name}: ... and {len(hits) - MAX_LISTED} more line(s) cleaned the same way")
    return "\n".join(lines), len(hits)


# ---------------------------------------------------------------------------
# Markdown blocks (what gets isolated when LaTeX stops)
# ---------------------------------------------------------------------------
def split_blocks(lines):
    """Blank-line separated blocks as (first line, end line) index ranges;
    fenced blocks (``` ... ```) are kept whole. A YAML header at the top is
    returned separately, because every test document needs it."""
    i, n = 0, len(lines)
    header = None
    if n and lines[0].strip() == "---":
        for j in range(1, n):
            if lines[j].strip() in ("---", "..."):
                header = (0, j + 1)
                i = j + 1
                break
    blocks, start, fence = [], None, None
    while i < n:
        ln = lines[i]
        if fence:
            s = ln.strip()
            if s and set(s) == {fence[0]} and len(s) >= len(fence):
                fence = None
            i += 1
            continue
        m = FENCE_RE.match(ln)
        if m:
            if start is None:
                start = i
            fence = m.group(1)
        elif ln.strip() == "":
            if start is not None:
                blocks.append((start, i))
                start = None
        elif start is None:
            start = i
        i += 1
    if start is not None:
        blocks.append((start, n))
    return header, blocks


def describe(lines, block, name):
    """How a warning names a note: recall-sheet rows carry a "% note:" label
    (their temporary file's line numbers mean nothing to you); anything else
    is named by its line in your file."""
    s, e = block
    for ln in lines[s:e]:
        m = NOTE_RE.match(ln.strip())
        if m:
            return f"“{snippet(m.group(1))}”"
    body = " ".join(ln for ln in lines[s:e] if not FENCE_RE.match(ln))
    return f"{name} line {s + 1}: “{snippet(body)}”"


def assemble(lines, header, blocks, replace=None):
    parts = []
    if header:
        parts.append("\n".join(lines[header[0]:header[1]]))
    for b in blocks:
        if replace and b in replace:
            if replace[b] is not None:
                parts.append(replace[b])
            continue
        parts.append("\n".join(lines[b[0]:b[1]]))
    return "\n\n".join(parts) + "\n"


def rescue(text):
    """A plain-text version of one note: the Markdown characters pandoc can
    turn into maths, sub- or superscript are escaped, so they print as they
    are. None for fenced (raw LaTeX) blocks, which cannot be rescued."""
    if FENCE_RE.match(text):
        return None
    return re.sub(r"(?<!\\)([$^~@|&])", r"\\\1", text)


# ---------------------------------------------------------------------------
# running pandoc
# ---------------------------------------------------------------------------
def time_limit(nbytes):
    """Seconds one pandoc run may take before it counts as hung."""
    env = os.environ.get("MD2PDF_TIMEOUT")
    if env:
        try:
            return max(1.0, float(env))
        except ValueError:
            pass
    return 300 + 120 * nbytes / 1e6


class Pandoc:
    def __init__(self, options, name, encoding, workdir):
        self.options, self.name, self.encoding = options, name, encoding
        self.workdir = Path(workdir)
        self.runs = 0

    def run_file(self, src, out_pdf, nbytes):
        """(ok, output) of pandoc on the file src, written to out_pdf."""
        self.runs += 1
        cmd = ["pandoc", str(src), "-o", str(out_pdf)] + self.options
        limit = time_limit(nbytes)
        try:
            # own process group, so a hung xelatex under pandoc can be stopped too
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, errors="replace", start_new_session=True)
        except OSError as ex:
            return False, f"md-to-pdf: could not run pandoc: {ex}\n"
        try:
            log, _ = p.communicate(timeout=limit)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
            log, _ = p.communicate()
            return False, (log or "") + f"\n! pandoc did not finish within {limit:.0f} seconds (LaTeX hung)\n"
        return p.returncode == 0 and Path(out_pdf).is_file(), log

    def run_text(self, text, out_pdf):
        # same file name (the .md/.txt extension matters to md-to-pdf's options)
        src = self.workdir / f"run{self.runs + 1}" / self.name
        src.parent.mkdir()
        src.write_text(text, encoding=self.encoding, errors="replace")
        return self.run_file(src, out_pdf, len(text.encode("utf-8", "replace")))

    def ok(self, text):
        out = self.workdir / f"test{self.runs + 1}.pdf"
        good, log = self.run_text(text, out)
        if out.exists():
            out.unlink()
        return good, log


def latex_error(log):
    """LaTeX's own error message from pandoc's output. Font-lookup noise
    (TeX trying to build a font that is not installed, e.g. when
    fallback.tex probes for a Hindi font) also prints "!" lines, so the
    message after pandoc's "Error producing PDF." is preferred."""
    lines = log.splitlines()
    for ln in lines:
        if "did not finish within" in ln:          # our own time-limit message
            return ln.lstrip("! ").strip()
    start = next((i for i, ln in enumerate(lines) if "Error producing PDF" in ln), None)
    noise = ("Emergency stop", "I can't find file")
    for ln in (lines[start + 1:] if start is not None else []):
        if ln.startswith("!") and not any(n in ln for n in noise):
            return ln.lstrip("! ").strip()
    real = [ln for ln in lines if ln.startswith("!") and not any(n in ln for n in noise)]
    return real[-1].lstrip("! ").strip() if real else "LaTeX error"


def passthrough(log):
    """Show pandoc's own messages, minus the per-character font warnings
    (those are summarised by report_missing_glyphs)."""
    for ln in log.splitlines():
        if "Missing character:" not in ln:
            print(ln, file=sys.stderr)


def report_missing_glyphs(log, lines, name):
    """One warning line per note that has characters the fonts cannot draw."""
    chars = []
    for ch, code in MISSING_RE.findall(log):
        if (ch, code.upper()) not in chars:
            chars.append((ch, code.upper()))
    if not chars:
        return
    _header, blocks = split_blocks(lines)
    by_note = {}                 # note description -> [(char, code)]
    for ch, code in chars:
        where = next((i for i, ln in enumerate(lines) if ch in ln), None)
        if where is None:
            label = "(not found in the text)"
        else:
            block = next((b for b in blocks if b[0] <= where < b[1]), (where, where + 1))
            label = describe(lines, block, name)
        by_note.setdefault(label, []).append((ch, code))
    warn(f"{len(chars)} character(s) are not in the PDF's fonts and print as blanks "
         f"(the rest of the note prints normally):")
    for label, cs in list(by_note.items())[:MAX_LISTED]:
        shown = " ".join(ch for ch, _ in cs)
        codes = ", ".join(f"U+{c}" for _, c in cs[:6]) + (", ..." if len(cs) > 6 else "")
        print(f"             {shown} ({codes}) in {label}", file=sys.stderr)
    if len(by_note) > MAX_LISTED:
        print(f"             ... and {len(by_note) - MAX_LISTED} more note(s)", file=sys.stderr)


# ---------------------------------------------------------------------------
# isolating the note(s) that stop LaTeX
# ---------------------------------------------------------------------------
def find_bad(pandoc, lines, header, blocks, idx):
    """Indices (into blocks) of the notes that make LaTeX stop on their own."""
    if pandoc.runs > MAX_RUNS:
        raise RuntimeError("too many test runs")
    if pandoc.ok(assemble(lines, header, [blocks[i] for i in idx]))[0]:
        return []
    if len(idx) == 1:
        return idx
    mid = len(idx) // 2
    return find_bad(pandoc, lines, header, blocks, idx[:mid]) + \
        find_bad(pandoc, lines, header, blocks, idx[mid:])


def repair(pandoc, text, name):
    """(text pandoc can typeset, rescued, left out) with a warning for each
    bad note; text is None if the problem cannot be pinned on a note."""
    lines = text.split("\n")
    header, blocks = split_blocks(lines)
    if not blocks:
        return None, 0, 0
    bad = find_bad(pandoc, lines, header, blocks, list(range(len(blocks))))
    if not bad:
        return None, 0, 0
    replace, rescued, dropped = {}, 0, 0
    for i in bad:
        b = blocks[i]
        raw = "\n".join(lines[b[0]:b[1]])
        why = latex_error(pandoc.ok(assemble(lines, header, [b]))[1])
        fixed = rescue(raw)
        if fixed is not None and fixed != raw and pandoc.ok(assemble(lines, header, [b], {b: fixed}))[0]:
            replace[b] = fixed
            rescued += 1
            warn(f"{describe(lines, b, name)} -- LaTeX could not print this as written "
                 f"({why}); printed it as plain text instead")
        else:
            replace[b] = None
            dropped += 1
            warn(f"{describe(lines, b, name)} -- LaTeX could not print this ({why}); "
                 f"left it out of the PDF")
    return assemble(lines, header, blocks, replace), rescued, dropped


# ---------------------------------------------------------------------------
def main():
    args = sys.argv[1:]
    if len(args) < 3 or args[2] != "--":
        sys.exit("usage: md-to-pdf-safety.py INPUT OUTPUT -- <pandoc options>")
    inp, out, options = Path(args[0]), Path(args[1]), args[3:]
    name = inp.name
    original, enc = read_text(inp)
    text, changed = clean_text(original, name)

    with tempfile.TemporaryDirectory() as td:
        pandoc = Pandoc(options, name, enc, td)
        if changed:
            good, log = pandoc.run_text(text, out)
        else:                      # nothing to clean: pandoc runs on your file, as always
            good, log = pandoc.run_file(inp, out, len(original.encode("utf-8", "replace")))
        if good:
            passthrough(log)
            report_missing_glyphs(log, text.split("\n"), name)
            return 0

        # Is pandoc/LaTeX itself working? If not, this is a setup problem.
        if not pandoc.ok("Test\n")[0]:
            passthrough(log)
            print(f"  error    pandoc fails even on a one-line test document, so the problem is the "
                  f"pandoc/LaTeX setup, not the text of {name}.", file=sys.stderr)
            return 1

        note(f"LaTeX stopped on something in {name} ({latex_error(log)}); finding the note(s) "
             f"that cause it, the rest will still be printed ...")
        rescued = dropped = 0
        current = text
        for _round in range(3):
            try:
                fixed, r, d = repair(pandoc, current, name)
            except RuntimeError:
                fixed = None
            if fixed is None:
                break
            rescued, dropped = rescued + r, dropped + d
            current = fixed
            good, log = pandoc.run_text(current, out)
            if good:
                passthrough(log)
                report_missing_glyphs(log, text.split("\n"), name)   # line numbers of your file
                note(f"{out.name}: {rescued} note(s) printed as plain text and {dropped} left out "
                     f"because LaTeX could not print them (see the warnings above; {name} is unchanged)")
                return 0
        passthrough(log)
        print(f"  error    could not find which part of {name} stops LaTeX, so no PDF was made. "
              f"LaTeX said: {latex_error(log)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

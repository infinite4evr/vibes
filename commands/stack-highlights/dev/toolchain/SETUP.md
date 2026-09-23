# Setup and everyday use

Everything needed to install the toolset and run it reliably, in one place.

## 1. What you need

| Needed for | What | Tested with |
|---|---|---|
| everything | Python 3.11 or newer (3.11+ is needed for config files) | 3.12.3 |
| everything | PyMuPDF (the PDF library) | **1.28.2** |
| notes / recall-sheet PDFs | pandoc | 3.1.3 |
| notes / recall-sheet PDFs | XeLaTeX (TeX Live) | TeX Live 2023 |
| notes / recall-sheet PDFs | Latin Modern fonts: the `lmodern` LaTeX package *and* the "Latin Modern Roman" system font | Debian packages `lmodern`, `fonts-lmodern` |
| visual benchmark only | pytest (optional) | — |

`stack-highlights` on its own (Markdown, text or JSON notes) needs only Python
and PyMuPDF. pandoc, XeLaTeX and the fonts are only for turning notes into PDFs.

**Keep the PyMuPDF version fixed.** The notes can shift slightly between
installations: the same script gave different output in 19 of 30 benchmark
runs on two machines (one with PyMuPDF 1.28.2; the other's version wasn't
recorded), although the number of highlights placed in the six books was the
same on both. `requirements.txt` pins the tested version. If
you ever upgrade, run `make coverage` (section 4) before trusting the new
notes.

## 2. Install

### Linux (Debian / Ubuntu) — and Windows through WSL

`md-to-pdf` is a bash script, so on Windows use WSL (Ubuntu) and follow these
steps inside it.

```bash
sudo apt install python3 python3-venv pandoc texlive-xetex texlive-latex-recommended lmodern fonts-lmodern

cd /path/to/toolchain
python3 -m venv ~/.venvs/notes              # a private Python for these tools
. ~/.venvs/notes/bin/activate               # do this in each new terminal (or add it to ~/.bashrc)
python3 -m pip install -r requirements.txt
```

### macOS

Install Python 3.11+ (python.org or Homebrew), then `brew install pandoc` and
a TeX distribution with XeLaTeX (MacTeX). Then create the venv and
`pip install -r requirements.txt` as above. Font lookup differs between TeX
setups on macOS, so run the smoke test in section 3; if it reports that
"Latin Modern Roman" cannot be found, install the Latin Modern OpenType fonts
into your user fonts.

### Put the tools on your PATH

`recall-sheet` finds `stack-highlights` and `md-to-pdf` through your PATH, so
link all four there (links, not copies — `stack-highlights` needs its
`stackhl/` folder, and `md-to-pdf` its `.tex`/`.lua` files, next to the real
files):

```bash
mkdir -p ~/bin
for t in stack-highlights notes recall-sheet md-to-pdf; do ln -sf "$PWD/$t" ~/bin/$t; done
# make sure ~/bin is on your PATH (e.g. add: export PATH="$HOME/bin:$PATH" to ~/.bashrc)
```

## 3. Check the setup

```bash
make quick                                   # a few seconds; should end "25/25 golden cases passed"
stack-highlights book.pdf --pages 1-5        # writes book.md; read the coverage line it prints
notes book.pdf --pages 1-5 --to notes,recall # writes book_notes.pdf and book_recall.pdf
```

If all three work, you are set up.

## 4. Everyday checklist

1. **Run whole books, or continuous page ranges** such as `--pages 100-150`.
   If you really need scattered pages (`--pages 50,90`), add `--no-join-pages`:
   without it, text from the end of one page can be glued onto a page that
   doesn't follow it.
2. **Read the coverage line** at the end of every run, e.g.
   `648 mark(s), 647 placed in notes`. If the two numbers differ, the notes end
   with a **Check in book** list saying which pages to look at and why.
3. **Tiny highlights** covering less than half a word are left out by default
   and listed under Check in book; rerun with `--snap char` to keep them.
4. **Highlights on images or scanned pages** have no text to extract; they are
   listed under Check in book, with any note you typed on them.
5. **Page numbers from `--page-refs` are approximate**: a highlight just after a
   page break can be cited one page early. The Check in book list always gives
   the exact page.
6. **New highlighting app, or a scanned/flattened PDF?** Check one page's notes
   against the book first. The tool has been tested on highlights saved as
   normal PDF annotations.
7. **Tables and complicated footnotes** may come out with imperfect layout.
   Your highlighted words are still there; check the book if a table's pairing
   matters.
8. **After changing any code, or upgrading PyMuPDF:** run `make test`
   (about 1.5 minutes with the six books). It fails if any highlight in the
   books stops being placed.

## 5. The tests, and where the books go

`make test` runs unit tests, golden files and the real-book coverage check.
The coverage check looks for the six books in `$HIGHLIGHT_PDFS`, else in
`../source-pdfs` next to the toolchain folder (the layout of the full package):

```bash
HIGHLIGHT_PDFS=/path/to/books make test
```

Without the books, it prints `SKIP real-book coverage ...` and the rest still
runs. See the "Tests" section of `README.md` for what each part checks.

## 6. Troubleshooting

| Message | Fix |
|---|---|
| `No module named 'pymupdf'` | Activate the venv (`. ~/.venvs/notes/bin/activate`) or `pip install -r requirements.txt` |
| `LaTeX Error: File 'lmodern.sty' not found` | Install the `lmodern` package |
| `The font "Latin Modern Roman" cannot be found` | Install `fonts-lmodern` (Linux) or the Latin Modern OpenType fonts (macOS) |
| `can't find 'md-to-pdf'` / `can't find 'stack-highlights'` (from recall-sheet) | Put the tools on your PATH (section 2), or pass `--md2pdf-cmd` / `--stack-cmd` |
| `ModuleNotFoundError: No module named 'stackhl'` | `stack-highlights` was copied without its `stackhl/` folder; link it instead of copying |
| `note: baseline was recorded with PyMuPDF ...` (from `make coverage`) | A different PyMuPDF version; see section 1 |

# commands

One folder per command. The folder name, the entry file inside it, and the
global command are all the same kebab-case name. Anything a command needs
(templates, package.json, data) lives in its own folder.

| Command | What it does |
|---|---|
| `md-to-pdf` | Markdown/text to PDF via pandoc + xelatex: `--compact`, `--par-skip`, `-p` page-number position, `--grey-context` (context grey, marks black), curly-quote typography; `fallback.tex` covers unicode/PUA + Devanagari |
| `normalize-names` | Bulk-rename files/folders to PascalCase words; dry-run by default, revertable |
| `split-pdf` | Split a PDF into parts of N pages (default 50): `split-pdf book.pdf 100` |
| `merge-pdf` | Merge every PDF in a folder into one, in natural filename order (qpdf, else pdfunite): `merge-pdf folder -o all.pdf` |
| `stack-highlights` | Extract PDF highlights into structured notes (rebuilt modular version with tests, config presets and a "Check in book" list of unplaced highlights; see `stack-highlights/README.md`) |
| `recall-sheet` | PDF highlights -> two-column active-recall PDF (calls `stack-highlights` + `md-to-pdf`; also takes a `.md` or `.json` made by `stack-highlights`). Options include `--grey-context`, `--space-every N:M --space-style ruled\|dotted`, `--color-map`, `--italic-colors`, `-p` |
| `notes` | One command for a highlighted PDF: notes PDF + recall sheet by default, `--to notes,recall,md,json` for any mix; runs `stack-highlights`, `md-to-pdf` and `recall-sheet` |
| `notes-recall` | Folder of highlighted PDFs -> one combined notes `.md`, notes PDF and recall sheet, with fixed settings (all mark kinds, comma context, italic non-yellow marks, plain titles): `notes-recall [BOOKS] [NAME] [FONT]`, defaults `~/Documents/Dump`, `Dump`, `14`. BOOKS can also be one PDF; `-P 1-200` reads only those PDF pages, `-F` picks the body font, `-p` adds page numbers, `-o` the output folder (default: next to the books folder) |
| `yt-subs-export` | Export YouTube subscriptions to CSV |
| `yt-subs-sync` | Diff two accounts' subscriptions and subscribe the missing ones |
| `yt-subs-subscribe` | Bulk-subscribe from a CSV (quota-aware, resumable) |
| `wa-auto-delete` | WhatsApp linked device that deletes your earlier messages in one chosen chat (for everyone) once the other person replies; runs under pm2, controlled from your "Message yourself" chat. Entry point is `npm run setup` / `npm run service`, not a global command; see [`wa-auto-delete/README.md`](wa-auto-delete/README.md) |

Setup (once):

1. `./install.sh` - makes the commands executable and installs Node deps.
   The Python commands need PyMuPDF: `python3 -m pip install -r stack-highlights/requirements.txt`.
2. Add to `~/.bashrc` (or `~/.zshrc`): `source ~/Documents/Vibes/commands/env.sh`
3. Open a new terminal.

`env.sh` puts every command subfolder on your PATH, so adding a command is just
creating `<name>/<name>` (executable, with a shebang) - no re-install needed,
though `install.sh` handles `chmod` and `npm install` for it.

A command's folder can hold more than its entry file: `stack-highlights/` also
has its `stackhl/` code package, `tests/` (`make -C stack-highlights test`) and
`dev/`, the full development archive it was rebuilt in (tracked, except the
266 MB test PDF; see `stack-highlights/dev/source-pdfs/README.md`).

The three `yt-subs-*` commands each keep their own `package.json` and
`package-lock.json` with the same dependencies. That is on purpose: every
command folder stands alone, and `install.sh` installs each one separately.

CI (`.github/workflows/ci.yml`) runs on every push and pull request: syntax
checks of every command, `make quick` and `make pdf-safety` for
`stack-highlights`, and `verify_package.py` on the test archive. The tests that
need the 266 MB PDF (`make coverage`, `make visual`) run only locally.

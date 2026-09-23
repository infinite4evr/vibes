# Highlight-to-notes toolset

Turn the highlights in a PDF into study notes and active-recall sheets.

## The tools

- **`stack-highlights`** — reads a highlighted PDF and writes structured notes
  (Markdown, plain text, or JSON). Only what you marked ends up in **bold**;
  everything else is the surrounding context it adds so the marks make sense.
- **`recall-sheet`** — turns those notes into a two-column active-recall sheet
  (cue words left, answer right; optional cloze blanks).
- **`md-to-pdf`** — renders a notes Markdown file to PDF (also used by
  `recall-sheet`). Ships with `fallback.tex`, `italic.tex`, `hr-fullwidth.lua`;
  keep all four together.
- **`notes`** — one wrapper that runs the above once and produces every output
  you ask for: `notes book.pdf --to notes,recall,md,json`.

## Quick start

```
stack-highlights book.pdf                 # -> book.md
notes book.pdf                            # -> book_notes.pdf + book_recall.pdf
notes book.pdf --to notes --preset revise
recall-sheet book.pdf --right cloze --grey-context
```

Run any tool with `--help`. `stack-highlights ... --dry-run` prints the settings
actually in effect (after config, profile, preset and flags) plus a small
sample, so you can check a setup before an 800-page run.

## Configuration

Personal defaults live in `~/.config/stack-highlights.toml`; per-book settings
in a `notes.toml` next to the book. Presets (`--preset print|revise|dense|act`)
and publisher profiles (`--profile ...`) are named flag bundles you can edit or
extend. See `stack-highlights.toml.example`.

## Data model

`stack-highlights --format json` emits a structured model: each line is a list
of runs `{text, mark, italic}`. `recall-sheet` reads this JSON directly, so it
never re-parses Markdown or undoes escaping — the source of a whole class of
past bugs. A single tokenizer (`runs_from_md`) is the one place Markdown is
turned into runs.

## Tests

The safety net. `make test` must stay green.

```
make test      # unit tests + golden-file checks
make units     # unit tests only
make golden    # golden-file checks only
make update    # regenerate goldens DELIBERATELY, then review `git diff tests/golden`
```

- **Golden files** (`tests/golden/`) pin the byte-for-byte output of
  `stack-highlights` on small checked-in fixture PDFs across the fragile flag
  paths. Any change that alters output fails loudly; if intended, `make update`
  and review the diff.
- **Unit tests** (`tests/test_units.py`) cover the pieces where bugs have lived:
  sentence boundaries, list-marker escaping, amendment-bracket stripping, the
  hyphen-join rule, and the `runs_from_md` tokenizer.

## Notes on styling

- `--grey-context` (recall-sheet and md-to-pdf via `notes`): context in grey,
  marks and headings in black, so the eye lands on what you marked.
- `--space-every N:M` with `--space-style ruled|dotted`: usable hand-writing
  space instead of a blank gap.
- `--color-map "red=italic,green=skip"`: per-colour emphasis. Styles are
  `bold`, `italic`, `skip`. (`underline` is not yet supported — it needs raw
  LaTeX that the current shared format can't carry portably.)

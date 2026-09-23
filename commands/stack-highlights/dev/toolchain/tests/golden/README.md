# Golden files

Each file is the exact output of one case in `../run_golden.py` (same name).
Besides comparing bytes, every case checks its coverage line and that its
"Check in book" list names exactly the highlights that were not placed.

| Cases | Fixture | What they protect |
|---|---|---|
| `prose_*` | `prose_list.pdf` | list lead-ins, exact-highlight mode, dehyphenation, JSON |
| `legal_default`, `legal_clause`, `legal_json` | `legal_clause.pdf` | a simple legal clause (plain hyphen) |
| `pagebreak_default`, `pagebreak_gap_nojoin` | `page_break.pdf` | a paragraph continuing across a page break; running headers stripped; `--no-join-pages` as the safe way to run a page list with gaps |
| `hyphen_*` | `hyphen_break.pdf` | highlights across a line-break hyphen (`co-`/`operation`, and the capitalised `inter-`/`State`) |
| `table_*` | `table_footnote.pdf` | table rows with highlighted cells, `--no-tables`, a footnote marker and a highlighted footnote, `--footnotes section` |
| `legal_emdash_*` | `legal_emdash.pdf` | bold run-in section titles ending ".—", a STATE AMENDMENT block, and a central section resuming after it (it must not be filed under the amendment) |
| `misses_*` | `misses.pdf` | highlights that cannot be placed — part of a word, and one over an image with a note — appearing in "Check in book" (Markdown, text, JSON) and `--snap char` keeping the part-word one |

## Known issues recorded on purpose

These goldens pin today's behaviour for problems that are known and not yet
fixed. When one is fixed, its golden will change; update it deliberately.

- **`pagebreak_json_KNOWN_ISSUE`** — the highlights "twenty years." and "most
  important term." are on PDF page 2 (printed 13), but their entry is
  labelled page 1 (printed 12): a paragraph joined across a page break keeps
  the page it started on. This is why `--page-refs` can cite one page early.
- **`pagebreak_gap_KNOWN_ISSUE`** — with `--pages 1,3`, page 3's text is glued
  onto page 1's unfinished sentence ("…stay at peace for They voted in…"),
  because paragraphs are joined across pages that are not next to each other.
  Compare `pagebreak_gap_nojoin`, the workaround.

## Minor formatting quirks visible here (accepted, not highlight losses)

- The footnote is shown as `fn 1: 1 The Muslim League…` (its number twice).
- With `--no-tables`, the table's bold header row turns into a heading
  ("Portfolios Held") and the other header cells are not shown.
- In `legal_emdash_default`, "Maharashtra." is treated as the end of a
  sentence, so the amendment's context starts at "In section 25C…".

# stack-highlights on Test-Merged-All.pdf — visual test report

**Question:** is the toolchain correct at least 90% of the time?

**Answer:** every highlight on 500 pages (3,725 highlights) was checked by eye against the notes
stack-highlights made (default settings, each book run on its own).

| | All 500 pages | Without the 23 repeated pages¹ |
|---|---|---|
| Highlights judged | 3,718 (+7 that cannot be judged) | 3,510 (+7) |
| **Fully correct (P)** | **3,270 = 88.0%** | 3,086 = 87.9% |
| Minor issue only (M) | 420 = 11.3% | 396 = 11.3% |
| **Correct or minor (P + M)** | **3,690 = 99.2%** | 3,482 = 99.2% |
| Failure (F) | 28 = 0.75% (on 10 pages) | 28 |

- **Fully correct** means every marked word is in the notes, in bold, with sensible context.
- **Minor** means every marked word is there and right, but something a reader would notice is
  off: a kept line-break hyphen, a trimmed sentence that loses who or when, list items run
  together, a stray symbol.
- **Failure** means marked words are missing, cut, scrambled, or put in a context that changes
  their meaning.

So the notes contain the marked information correctly 99.2% of the time (well above 90%); they are
flawless 88.0% of the time (just under 90%). About 1 highlight in 130 is actually wrong or missing.

¹ The merged PDF contains 11 labour acts twice (see finding 5); 23 sampled pages repeat another
sampled page and gave identical notes and verdicts.

## By book

| Book (merged-PDF pages) | Pages | Highlights | Fully correct | Correct or minor | Failures |
|---|---|---|---|---|---|
| Indian Polity, Laxmikanth (2531–3716) | 108 | 927 | 97.6% | 99.8% | 2 |
| A Brief History of Modern India (1–920) | 27 | 123 | 95.9% | 100% | 0 |
| Employee's Compensation Act (3717–3798) | 12 | 121 | 94.2% | 100% | 0 |
| Indian Economy, Ramesh Singh (1731–2530) | 38 | 175 | 93.1% | 100% | 0 |
| ICSI Labour Laws & Practice (7036–7635) | 47 | 697 | 90.3% | 98.8% | 8 |
| 19 labour acts (6186–7035) | 90 | 767 | 88.7% | 100% | 0 |
| Trade Unions Act (4568–4591) | 12 | 107 | 87.9% | 100% | 0 |
| The Constitution of India (921–1322) | 34 | 128 | 87.5% | 100% | 0 |
| Accounting & Financial Analysis, Chowdhry (1323–1730) | 21 | 107 | 78.5% | 99.1% | 1 |
| Industrial Relations, Pearson (8259–9083) | 12 | 32 | 71.9% | 93.8% | 2 |
| Industrial Relations, Ghosh & Nanda (9084–9916) | 31 | 99 | 68.7% | 99.0% | 1 |
| Indian Economy, Vivek Singh (5711–6185) | 46 | 364 | 66.8% | 96.4% | 13 |
| Accounting for CA-CPT, Jain & Panda (3799–4567) | 12 | 51 | 64.7% | 98.0% | 1 |
| Accountancy for CA-CPT, Tata McGraw Hill (4592–5710) | 10 | 27 | 37.0% | 100% | 0 |

The weak books are weak for reasons in their PDFs rather than their content: Tata McGraw Hill's
text layer puts a space after every "ﬁ" ("fi gures"); Vivek Singh's bullets are a private-use
symbol that makes list items run together; Ghosh & Nanda's text keeps its line-break hyphens.

## The failures (28 highlights on 10 pages)

Images: `report_images/` (a crop of the reference image, marks boxed and numbered as in `images/`).

All failures are of three kinds.

**1. Prose or a boxed passage read as a table (6 pages).** Words from different lines are
interleaved, or torn out of the marked phrase and printed elsewhere in the entry.

| Image | Page | What happened |
|---|---|---|
| `F02_P224.png` | Laxmikanth p.3402, case-summary box | two layout columns mixed; "basic structure" comes out reversed |
| `F05_P310.png` | Vivek Singh p.5978, poverty estimation | the whole page is word salad; "Socio-Economic Caste Census (SECC 2011)" scattered (7 F) |
| `F07_P420.png` | ICSI p.7123, manufacturing process | "done for" torn out of the marked phrase |
| `F08_P443.png` | ICSI p.7435, set on and set off | "twenty per total salary" ("cent of the" displaced) (2 F) |
| `F09_P466.png` | Pearson p.8374, early trade unions | two marked sentences torn in two and printed apart (2 F) |
| `F10_P475.png` | Ghosh & Nanda p.9136, migration | "or town to another" torn out of the definition |

**2. Real tables paired wrongly (3 pages).**

| Image | Page | What happened |
|---|---|---|
| `F01_P067.png` | Chowdhry p.1374, accounting standards table | table collapsed column by column; "of accounting policies" lost |
| `F04_P306.png` | Vivek Singh p.5946, Five Year Plans table | rows shifted by one: each plan gets the previous plan's text (6 F) — **false facts** |
| `F03_P243.png` | Jain & Panda p.3832, two-column quiz | Q6's answer printed under Q1's question |

**3. Marked text not in the notes at all (1 page).**

| Image | Page | What happened |
|---|---|---|
| `F06_P416.png` | ICSI p.7095, ILO conference tasks | five marked bullets not placed; the tool lists them under "Check in book" (5 F) |

The P306 row shift is the most harmful: the notes read smoothly and are wrong.

## Minor issues (420 highlights)

| Kind | Highlights | Share |
|---|---|---|
| Context trimmed or cut: who does it, the condition, or the rest of the sentence is lost (mostly Acts and ICSI, where the ~40-word context stops before the subject) | 135 | 32% |
| List or bullet items run together into one entry | 98 | 23% |
| Sentence, title or item split across entries or turned into a heading | 37 | 9% |
| Stray symbol, letter, number or text (bullets read as "l", "r", "ßß"; footnote numbers; "`100" for ₹100; a margin note inside a sentence) | 32 | 8% |
| Line-break hyphen kept ("legisla-tion", "em-ployment") | 30 | 7% |
| Item or quiz answer without its lead-in or question | 27 | 6% |
| Table cell paired wrongly or flattened (fractions lose their line) | 26 | 6% |
| Marked words intact, but inside a scrambled entry | 12 | 3% |
| Filed under a wrong heading (Berubari under "Shankari Prasad Case") | 7 | 2% |
| Words glued where amendment markers were removed ("aemployee") — Employee's Compensation Act only | 7 | 2% |
| Word split after the "fi" ligature (Tata McGraw Hill; more are counted under hyphens) | 6 | 1% |
| Half-covered word left unbold ("no employer shall pay") | 3 | 1% |

(`report_assets.py` makes this table from the recorded reasons; each highlight is counted once,
under the first kind that fits.)

Settings that may reduce some of these, untested here: `--dehyphenate` (line-break hyphens),
`--max-words` / `--context paragraph` (trimmed context), `--no-tables` (pages misread as tables).

Structure notes, not counted: headings are often imperfect (sentence fragments, box titles,
"Spotlight", note boxes and run-in bold terms used as headings; Act titles filed under the
previous Act's last heading). Handwritten ink (468 annotations, mostly ICSI) is ignored by the
tool by design and was out of scope; typed notes were mostly placed well (two misplaced, counted
as minor).

## Findings about the test file and running the tool

1. **The whole 9,916-page merge in one run needs a lot of memory** (killed at ≈3.9 GB on a 4 GB
   test machine). Every run surveys the whole file, even with `--pages`. The owner's machine
   has 32 GB.
2. **Pages with no highlights give fake marks:** on an unmarked page range the tool treats
   coloured drawings as highlights (pages 1–5 gave 163 text-less "marks"). Does not happen on a
   book with real highlights.
3. **The merged PDF distorts the notes.** Body-text size and running headers are measured over
   the whole file, so in the merge some books come out wrong (Ramesh Singh's paragraphs as
   headings, Modern India's running header kept, a Constitution section number dropped). Run
   book by book the same pages are right. **All tests therefore split the merged PDF back into
   its 14 highlighted books and run each on its own** — the way the tool is used.
4. **Placement: 18,567 of 18,647 highlights placed (99.6%)** across the 14 books. Every one not
   placed is listed by the tool under "Check in book" (mostly ICSI: tiny marks over part of a
   word, marks with no text, and the P416 bullets).
5. **The merged PDF contains 11 labour acts twice** (Employee's Compensation, Trade Unions,
   Industrial Disputes, Minimum Wages, ESI, Factories, Plantations, EPF, Mines, Employment
   Exchanges, Maternity Benefit; about 390 pages, text and highlights identical — list in
   `FINDINGS.md`). If the merge is rebuilt, the second copies can go.
6. The Employee's Compensation Act is the only book where removing amendment markers glues
   words together; the Trade Unions Act and the 19 acts in the labour-acts file come out clean.

Detailed notes per book and every page's verdicts: `FINDINGS.md`, `STATUS.md`, `gold_cases.json`.

## The automated tests this review left behind

| Test | What it guards | Command | Time |
|---|---|---|---|
| Real-book coverage (`tests/run_coverage.py`) | every highlight of the 14 books still placed; "Check in book" names exactly the misses | `make coverage` (part of `make test`) | 3–4 min (+1.5 min the first time, to split the PDF) |
| Visual test (`run_visual_tests.py`, `gold_cases.json`) | on the 500 judged pages, no highlight judged correct or minor stops being placed; any page whose notes change is listed for a fresh look | `make visual`, or `make visual-pytest` (500 cases) | 3–4 min |

Both were run on the final package: coverage matched its baseline and the visual test found all
500 pages identical to what was judged (PyMuPDF 1.28.2). The tool itself was not changed.

How the review was done: pages chosen at random but spread over every highlighted book and over
light, medium and dense pages (`selection.json`, seed 20260923); each page rendered with its
highlights boxed and numbered (`images/`); the text under every highlight transcribed from the PDF
and checked against the image; the notes read next to each numbered highlight and given a
verdict with a reason (`review_log.jsonl`).

# Findings (all 500 pages reviewed)

Detailed notes kept during the review, book by book. The summary is `REPORT.md`; the numbers
are in `STATUS.md` (regenerate with `python3 status.py > STATUS.md`).
Headline: 3,718 judgeable marks (+7 X) on 500 pages — 88.0% fully correct, 99.2% correct or
only cosmetically imperfect, 28 real failures on 10 pages. Without the 23 repeated pages:
87.9% / 99.2%.

## About running the tool

1. **Whole merged PDF in one run: killed for lack of memory on a 4 GB machine** (≈3.9 GB after
   ~5.5 min). Every run surveys every page of the file, even with `--pages`. Owner's machine
   has 32 GB, so this is informational only.
2. **Unmarked page ranges produce fake marks.** When the selected pages contain no annotations,
   the tool falls back to treating coloured drawings as highlights: pages 1–5 of the merged
   PDF gave 163 "marks" with no text. Does not happen for a book that has real highlights.
3. **The merged PDF distorts results.** Body text size and running headers are measured over the
   whole file, so in the 9,916-page merge some books come out wrong: Ramesh Singh's paragraphs
   became headings; Modern India's running header ("24 ✫ A Brief History of Modern India")
   became a heading; one Constitution section number ("s. 3") was dropped. Run book by book,
   the same pages are correct. **The review therefore judges the book-by-book output**
   (`run_books.py`: the merged PDF is split back into its 14 books, each run standalone;
   no tool code changed). The merged-range output is kept in
   `outputs/default_merged_page_ranges.json` for comparison (`compare_runs.py`).
4. **Placement (book-by-book, default settings): 18,567 of 18,647 marks placed (99.6%).**
   Misses: ICSI Labour Laws 66 (50 part-word, 5 no text, 11 not placed), Vivek Singh 6
   (part-word), Jain & Panda 3, labour acts 2, Laxmikanth 2, Modern India 1. All are listed by
   the tool in "Check in book", as designed. (19,208 annotations minus 561 ink/typed notes.)
5. **The merged PDF contains the Employee's Compensation Act twice** (merged pp. 3717–3757 and
   3758–3798, identical highlights). 6 of its 12 sampled pages are exact repeats.
6. Handwritten ink (468 annotations, mostly ICSI) is ignored by the tool by design — out of scope.

## Failures (F)

- **P067, p.1374 (Chowdhry, Table 3.2 of accounting standards):** the table is collapsed column
  by column; only "AS-1" and "Disclosure" are bold, "of accounting policies" is lost.
- **P224, p.3402 (Laxmikanth, case-summary box):** two layout columns mixed into one row; the
  marked phrase comes out reversed ("structure' … 'basic") inside a jumbled sentence.

- **P243, p.3832 (Jain & Panda, two-column MCQ page):** Q6's marked answer "(a) Understatement of
  assets" is printed under Q1's question ("Accounting principles are generally based on:").
  Borderline call: the marked words are intact, but the attached question gives it a wrong meaning.

- **P306, p.5946 (Vivek Singh, Five Year Plans table, 6 F):** rows shifted by one: each plan's
  label is paired with the previous plan's cell text (the Second Plan's heavy-industry focus is filed
  under the Third Plan, the Third Plan's agriculture priority under the Annual Plans, …). Produces
  false facts.
- **P310, p.5978 (Vivek Singh, poverty estimation, 7 F):** an ordinary prose page is detected as a
  table; the output interleaves words from different lines into word salad. p.5979 is the same.

- **P416, p.7095 (ICSI, ILO conference tasks, 5 F):** five marked bullet texts are not placed in the
  notes at all; the tool only lists them under "Check in book" (not_placed).
- **P420, p.7123 (ICSI, manufacturing process, 1 F):** a prose paragraph is read as a table row;
  'done for' is torn out of the marked phrase and moved to the entry start with stray words.

- **P443, p.7435 (ICSI, set on and set off of allocable surplus, 2 F):** a sub-section is read as a
  table row; words torn out of two marked phrases and moved to the entry start ('twenty per total
  salary', 'fourth year' without 'accounting').

- **P466, p.8374 (Pearson, early trade union movement, 2 F):** a prose page read as a table row;
  two marked sentences torn in two and printed apart.
- **P475, p.9136 (Ghosh & Nanda, migration, 1 F):** a prose paragraph read as a table row; 'or town
  to another' torn out of the marked definition.

## Recurring minor issues (M)

- Line-break hyphens kept by default ("issu-ing", "quo war-rento"); `--dehyphenate` exists.
- Context trimmed by the 40-word limit so the subject is lost ("… shall prevail").
- Stray footnote numbers inside sentences ("the rate16 of interest", "Cabinet of the50 country").
- Labour acts: words glued where amendment markers like ²[employee] are removed
  ("aemployee", "theemployee", "thewilful disobedience", "deathor") — sometimes inside the mark.
- Tables: Constitution contents rows merged (numbers apart from titles); first row of Laxmikanth
  "Article No. / Subject" tables output as a bare number ("243." without "Definitions").
- Lists run together into one paragraph, or list items without their lead-in; sometimes an
  unrelated lead-in from the previous page is prefixed.
- One sentence split into two entries at a line break.
- Typed margin notes: one pasted into the middle of a sentence ("trade bill", p.2067), one
  attached to the wrong paragraph ("cabinet", p.2547).
- A ruling filed under the wrong case heading (Berubari under "Shankari Prasad Case", p.3400).

## Structure notes (S, not counted in the percentages)

Quote attributions ("—Lord Cornwallis"), bold bullet sentences, sentence fragments ("part is put
to vote."), table column headers ("Consists of") and "(iii)" used as headings; the Constitution
keeps its running header "THE CONSTITUTION OF INDIA" as a heading; Act titles filed under
"CHAPTER IV" from the arrangement-of-sections pages.

## Jain & Panda (P241–P252)

- **Two-column MCQ pages are the weak spot** (P243: 10 of 11 marks imperfect). Only the option
  letter is highlighted, and the tool often loses the question: answers without their question,
  question starts garbled with a stray "(d) All of these" from the other column, or (1 F) an
  answer under the wrong question.
- Grey "Note" boxes become headings (full sentence as heading); the entries after them are filed
  under that sentence. A stale top heading "Objectives" runs through the whole book.
- Run-in bold terms ("Clerical errors could", "Errors of omission") become headings and split the
  marked sentence. List-bullet glyphs sometimes come out as "ßß".

## Trade Unions Act, Tata McGraw Hill, Vivek Singh (P253–P320)

- **The Trade Unions Act is also in the merged PDF twice** (pp. 4568–4579 and 4580–4591, identical
  highlights); 6 of its 12 sampled pages are repeats. Output is clean apart from a stray lead-in
  from the previous clause and one over-trimmed context.
- **Tata McGraw Hill:** the text layer has a space after every "ﬁ" ligature, so nearly every mark
  reads "fi gures", "Profi t", "identifi ed" (37% strict, 100% usable). MCQ and True/False
  answers come out without their questions; a page's True/False answers get packed into one entry.
- **Vivek Singh:** bullets use a private-use glyph (U+F0B7), and the tool runs the bullet items
  together into one entry separated by that glyph — the largest source of M. Fractions are flattened
  ("Capital Output Ratio = Capital Output"). Two failure pages (P306 table row shift, P310 prose
  read as a table). The subsection title "MCLR" stays the top heading for the rest of chapter 2.

## Labour acts and the start of ICSI (P321–P422)

- **Most of the merged PDF's labour acts are in it twice.** Exact repeats (text and highlights):
  3717–3757 → 3758–3798 (Employee's Compensation), 4568–4579 → 4580–4591 (Trade Unions),
  6230–6302 → 6303–6375 (Industrial Disputes), 6376–6394 → 6395–6413 (Minimum Wages),
  6414–6474 → 6475–6535 (ESI), 6536–6595 → 6596–6655 (Factories), 6656–6679 → 6680–6703
  (Plantations), 6704–6745 → 6746–6787 (EPF), 6788–6827 → 6828–6867 (Mines), 6868–6872 →
  6873–6877 (Employment Exchanges), 6878–6888 → 6889–6899 (Maternity Benefit). 49 of the 500
  sampled pages are repeats; 23 of those repeat another sampled page (`duplicates.json`).
- **Labour acts (P321–P410): 0 failures.** Amendment markers like ²[employee] were removed cleanly
  everywhere (no glued words, unlike the Employee's Compensation Act). The main M is the ~40-word
  context window cutting off the actor or condition ("… set up a Safety Committee …" without "the
  occupier shall, in every factory where a hazardous process takes place"). One stray amendment
  number ("shall be 4 twenty-six weeks"), a few split titles/headings. Act titles are usually filed
  under the previous Act's last heading or a state-amendment heading (S).
- **ICSI Labour Laws (from P411):** dense, overlapping highlights and handwriting. Lists often come
  out as table rows ("(a) ·"); a marked bullet list got an unrelated lead-in from the previous page;
  Wingdings bullets appear as a stray letter "l". Two failure pages so far (P416, P420).
- **ICSI (P411–P457, complete):** 3 failure pages (P416 not placed, P420 and P443 prose read as a
  table). Most M: the context window cuts off who does something or the condition (Acts quoted in
  study-text prose); half-covered words left unbold ('no employer shall pay', 'Rs.10,000'); a case
  box's key line turned into a heading; list items without their lead-in. Tiny stray marks over one
  letter or a colon are listed by the tool under Check in book (7 X, correct behaviour).

## Pearson and Ghosh & Nanda (P458–P500)

- **Pearson (12 pages, 32 marks):** light marking; one scrambled prose page (P466); chapter titles
  split across nested headings.
- **Ghosh & Nanda (31 pages, 99 marks, 68.7% strict / 99.0% usable):** the typeset text keeps its
  line-break hyphens ("Com-mittee", "legisla-tion", "em-ployment") and the tool does not join them
  — the main M. Bullet glyphs come out as letters ('r', 'd'); the rupee sign comes out as a
  backtick ('`100'), which Markdown may read as inline code; two definitions split and printed in
  reverse order (P482); one prose paragraph read as a table (P475, F).

## Failure pattern across the whole review

All 28 failures fall into three kinds: (1) prose or boxed text wrongly read as a table row, so
words are interleaved or torn out of the marked phrase (P224, P310, P420, P443, P466, P475);
(2) real tables mis-paired (P067 collapsed, P306 rows shifted by one, P243 MCQ answer under the
wrong question); (3) marked text not placed at all, only listed under Check in book (P416).

# Final Script Issues from the 180-Page Visual-Gold Benchmark

## Benchmark result

- **180 unique visually reviewed pages**: 30 per PDF.
- **120 newly added pages**: 20 per PDF, with **zero overlap** with the original 60.
- **5 parameter profiles**, giving **900 black-box comparisons**.
- Overall score: **91.06%**.
- Exact-highlight profile: **97.2%** — 175/180 pass.
- Default structured: **91.01%**.
- Safe sentence flat: **91.39%**.
- Clause structured: **87.04%**.
- 12-word window flat: **88.68%**.

The test intentionally penalises missing/wrong highlighted content much more heavily than formatting or Markdown differences.

## High-severity issues

### 1. Modern India p.157 — wrong highlight chosen instead of `(1848–56)`

The visible focus highlight is **`(1848–56)`** in the sentence about Lord Dalhousie. The current script does not emit that highlight. It instead selects the unrelated highlighted phrase **`political blunder`** from a later passage on the same page. This fails all five profiles and is genuinely misleading because the output is attached to the wrong highlighted fact.

### 2. Modern India p.214 — `Rani` is replaced by `—Hugh Rose`

The visible focus highlight is **`Rani`** in the sentence about Rani Laxmibai. The extractor instead associates the page with the highlighted attribution **`—Hugh Rose`**. All five profiles fail. This is another wrong-annotation / wrong-local-region association rather than a formatting problem.

### 3. Modern India p.240 — `Sarojini Naidu` silently disappears

The visible highlighted **`Sarojini Naidu`** sentence produces **no matching output at all** under any of the five profiles. This is a true silent omission.

### 4. Modern India p.124 and p.136 — valid prose highlights disappear only with flatter parameter combinations

- p.124: **`combined`** is correctly extracted in structured/default and clause modes, but disappears in `highlight_exact_flat`, `safe_sentence_flat`, and `window12_flat`.
- p.136: **`twenty years.`** behaves the same way.

This indicates a parameter-interaction bug: disabling headings/tables/run-ins/lead-ins can cause ordinary valid prose annotations to vanish, even though the same annotation is recoverable in structured mode.

## Moderate issues

### 5. Laxmikanth p.754 — unrelated lead-in is attached

For the highlighted passage about **co-operative societies**, several profiles prefix the result with **`The functions of the CVC are:`**, which belongs to unrelated material. The highlighted sentence itself is present, so this is not a silent loss, but the attachment is misleading and should be removed.

### 6. Sentence/clause context is sometimes truncated to a heading or highlighted fragment

This is especially visible in the Constitution and the Industrial Disputes Act. Examples include Article/section highlights where the highlight survives but the surrounding legal sentence does not. Representative cases include Constitution Article 148 / Article 262 and Act sections 25C, 25N and 30. These are incomplete rather than factually wrong, but they reduce the usefulness of `sentence`/`clause` modes.

### 7. Some run-in/list context remains too short

Accounting's **`Cost accounting`** case can collapse to the run-in label without its explanatory sentence. Similar short-context cases occur in legal provisions and TOC-style entries. Again, the highlighted text is normally preserved; the problem is insufficient context.

### 8. One Economy list continuation begins mid-name

The RBI-subsidiaries case around BRBNMPL/ReBIT/IFTAS can begin at **`Limited (BRBNMPL)`** rather than the complete institution name. This is not a wrong association, but it is a line-boundary truncation that can make the note awkward or ambiguous.

## What is working well

- **175/180 exact-highlight cases pass** the visual test.
- Laxmikanth exact-highlight preservation: **30/30**.
- Industrial Disputes Act exact-highlight preservation: **30/30**.
- Accounting exact-highlight preservation: **30/30** under the tolerant visual scorer.
- Economy exact-highlight preservation: **30/30** under the tolerant visual scorer, including the earlier `Preamble` regression case.
- The previous Economy `Preamble` wrong-association case now passes all five profiles in this run.
- Table-cell extraction in the selected corpus passed all five profile comparisons.

## Priority for the next code pass

The highest-value fixes are: **(1)** repair Modern India annotation-to-text matching on the three all-profile failures, **(2)** prevent flat/no-structure parameters from deleting recoverable prose annotations, and **(3)** reject unrelated lead-ins such as the CVC/co-operative-societies attachment. The remaining context-length issues can be treated as secondary because they generally preserve the highlighted fact.

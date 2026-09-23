# Verified visual-gold regression report

Overall semantic correctness score: **91.06%** across **900** comparisons.

This report was reconstructed from fresh raw outputs for all five profiles packaged in this directory.

## By profile

- **default_structured**: 91.01% — {'PASS': 148, 'FAIL': 26, 'REVIEW': 3, 'DANGEROUS': 3}
- **highlight_exact_flat**: 97.2% — {'PASS': 175, 'DANGEROUS': 5}
- **safe_sentence_flat**: 91.39% — {'PASS': 151, 'FAIL': 21, 'REVIEW': 3, 'DANGEROUS': 5}
- **clause_structured**: 87.04% — {'PASS': 133, 'FAIL': 40, 'REVIEW': 4, 'DANGEROUS': 3}
- **window12_flat**: 88.68% — {'PASS': 148, 'FAIL': 27, 'DANGEROUS': 5}

## By PDF

- **00_The_Constitution_of_India.pdf**: 88.4% — {'PASS': 113, 'FAIL': 34, 'REVIEW': 3}
- **01_A_Brief_History_of_Modern_India.pdf**: 80.74% — {'PASS': 110, 'DANGEROUS': 21, 'FAIL': 16, 'REVIEW': 3}
- **01_Fundamentals_of_Accounting_and_Financial_Analysis_Anil_Chowdhury_--_2006.pdf**: 96.75% — {'FAIL': 7, 'PASS': 140, 'REVIEW': 3}
- **01_INDIAN_ECONOMY_FOR_CIVIL_SERVICES__UNIVERSITIES_AND_OTHER_EXAMINATIONS_-_Ramesh_Singh.pdf**: 95.23% — {'PASS': 135, 'FAIL': 15}
- **01_Indian_Polity_Laxmikanth.pdf**: 95.89% — {'PASS': 141, 'FAIL': 9}
- **05 THE INDUSTRIAL DISPUTES ACT, 1947.pdf**: 89.38% — {'PASS': 116, 'FAIL': 33, 'REVIEW': 1}

## Dangerous failures

- VG017 / default_structured / p.157: **8.0%** — highlight missing/altered; insufficient correct context; context order scrambled; substantial unrelated/unsafe text
- VG018 / default_structured / p.214: **12.5%** — highlight missing/altered; insufficient correct context; context order scrambled
- VG100 / default_structured / p.240: **0.0%** — no matching entry on page
- VG015 / highlight_exact_flat / p.124: **0.0%** — no matching entry on page
- VG017 / highlight_exact_flat / p.157: **0.0%** — highlight missing/altered
- VG018 / highlight_exact_flat / p.214: **16.67%** — highlight missing/altered
- VG090 / highlight_exact_flat / p.136: **0.0%** — no matching entry on page
- VG100 / highlight_exact_flat / p.240: **0.0%** — no matching entry on page
- VG015 / safe_sentence_flat / p.124: **0.0%** — no matching entry on page
- VG017 / safe_sentence_flat / p.157: **8.0%** — highlight missing/altered; insufficient correct context; context order scrambled; substantial unrelated/unsafe text
- VG018 / safe_sentence_flat / p.214: **23.25%** — highlight missing/altered; insufficient correct context; context order scrambled; substantial unrelated/unsafe text
- VG090 / safe_sentence_flat / p.136: **0.0%** — no matching entry on page
- VG100 / safe_sentence_flat / p.240: **0.0%** — no matching entry on page
- VG017 / clause_structured / p.157: **8.0%** — highlight missing/altered; insufficient correct context; context order scrambled; substantial unrelated/unsafe text
- VG018 / clause_structured / p.214: **12.5%** — highlight missing/altered; insufficient correct context; context order scrambled
- VG100 / clause_structured / p.240: **0.0%** — no matching entry on page
- VG015 / window12_flat / p.124: **0.0%** — no matching entry on page
- VG017 / window12_flat / p.157: **7.5%** — highlight missing/altered; insufficient correct context; context order scrambled; substantial unrelated/unsafe text
- VG018 / window12_flat / p.214: **21.79%** — highlight missing/altered; insufficient correct context; context order scrambled; substantial unrelated/unsafe text
- VG090 / window12_flat / p.136: **0.0%** — no matching entry on page
- VG100 / window12_flat / p.240: **0.0%** — no matching entry on page

## Lowest-scoring comparisons

- VG100 / default_structured / 01_A_Brief_History_of_Modern_India.pdf p.240: **0.0%** (DANGEROUS) no matching entry on page
- VG015 / highlight_exact_flat / 01_A_Brief_History_of_Modern_India.pdf p.124: **0.0%** (DANGEROUS) no matching entry on page
- VG017 / highlight_exact_flat / 01_A_Brief_History_of_Modern_India.pdf p.157: **0.0%** (DANGEROUS) highlight missing/altered
- VG090 / highlight_exact_flat / 01_A_Brief_History_of_Modern_India.pdf p.136: **0.0%** (DANGEROUS) no matching entry on page
- VG100 / highlight_exact_flat / 01_A_Brief_History_of_Modern_India.pdf p.240: **0.0%** (DANGEROUS) no matching entry on page
- VG015 / safe_sentence_flat / 01_A_Brief_History_of_Modern_India.pdf p.124: **0.0%** (DANGEROUS) no matching entry on page
- VG090 / safe_sentence_flat / 01_A_Brief_History_of_Modern_India.pdf p.136: **0.0%** (DANGEROUS) no matching entry on page
- VG100 / safe_sentence_flat / 01_A_Brief_History_of_Modern_India.pdf p.240: **0.0%** (DANGEROUS) no matching entry on page
- VG100 / clause_structured / 01_A_Brief_History_of_Modern_India.pdf p.240: **0.0%** (DANGEROUS) no matching entry on page
- VG015 / window12_flat / 01_A_Brief_History_of_Modern_India.pdf p.124: **0.0%** (DANGEROUS) no matching entry on page
- VG090 / window12_flat / 01_A_Brief_History_of_Modern_India.pdf p.136: **0.0%** (DANGEROUS) no matching entry on page
- VG100 / window12_flat / 01_A_Brief_History_of_Modern_India.pdf p.240: **0.0%** (DANGEROUS) no matching entry on page
- VG017 / window12_flat / 01_A_Brief_History_of_Modern_India.pdf p.157: **7.5%** (DANGEROUS) highlight missing/altered; insufficient correct context; context order scrambled; substantial unrelated/unsafe text
- VG017 / default_structured / 01_A_Brief_History_of_Modern_India.pdf p.157: **8.0%** (DANGEROUS) highlight missing/altered; insufficient correct context; context order scrambled; substantial unrelated/unsafe text
- VG017 / safe_sentence_flat / 01_A_Brief_History_of_Modern_India.pdf p.157: **8.0%** (DANGEROUS) highlight missing/altered; insufficient correct context; context order scrambled; substantial unrelated/unsafe text
- VG017 / clause_structured / 01_A_Brief_History_of_Modern_India.pdf p.157: **8.0%** (DANGEROUS) highlight missing/altered; insufficient correct context; context order scrambled; substantial unrelated/unsafe text
- VG018 / default_structured / 01_A_Brief_History_of_Modern_India.pdf p.214: **12.5%** (DANGEROUS) highlight missing/altered; insufficient correct context; context order scrambled
- VG018 / clause_structured / 01_A_Brief_History_of_Modern_India.pdf p.214: **12.5%** (DANGEROUS) highlight missing/altered; insufficient correct context; context order scrambled
- VG018 / highlight_exact_flat / 01_A_Brief_History_of_Modern_India.pdf p.214: **16.67%** (DANGEROUS) highlight missing/altered
- VG018 / window12_flat / 01_A_Brief_History_of_Modern_India.pdf p.214: **21.79%** (DANGEROUS) highlight missing/altered; insufficient correct context; context order scrambled; substantial unrelated/unsafe text
- VG018 / safe_sentence_flat / 01_A_Brief_History_of_Modern_India.pdf p.214: **23.25%** (DANGEROUS) highlight missing/altered; insufficient correct context; context order scrambled; substantial unrelated/unsafe text
- VG002 / default_structured / 00_The_Constitution_of_India.pdf p.9: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG009 / default_structured / 00_The_Constitution_of_India.pdf p.198: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG063 / default_structured / 00_The_Constitution_of_India.pdf p.23: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG067 / default_structured / 00_The_Constitution_of_India.pdf p.54: **59.0%** (FAIL) insufficient correct context; context order scrambled

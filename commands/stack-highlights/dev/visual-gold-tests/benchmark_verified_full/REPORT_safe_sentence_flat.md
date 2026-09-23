# Visual-gold regression report

Overall semantic correctness score: **91.39%** across **180** comparisons.

Scoring deliberately ignores Markdown, whitespace, line wrapping, punctuation spacing and harmless dehyphenation. Missing highlighted content, wrong context, scrambled order and unrelated text are penalised heavily.

## By profile

- **safe_sentence_flat**: 91.39% - {'PASS': 151, 'FAIL': 21, 'REVIEW': 3, 'DANGEROUS': 5}

## By PDF

- **00_The_Constitution_of_India.pdf**: 87.87% - {'PASS': 22, 'FAIL': 7, 'REVIEW': 1}
- **01_A_Brief_History_of_Modern_India.pdf**: 80.68% - {'PASS': 22, 'DANGEROUS': 5, 'FAIL': 2, 'REVIEW': 1}
- **01_Fundamentals_of_Accounting_and_Financial_Analysis_Anil_Chowdhury_--_2006.pdf**: 97.34% - {'FAIL': 1, 'PASS': 28, 'REVIEW': 1}
- **01_INDIAN_ECONOMY_FOR_CIVIL_SERVICES__UNIVERSITIES_AND_OTHER_EXAMINATIONS_-_Ramesh_Singh.pdf**: 98.41% - {'PASS': 29, 'FAIL': 1}
- **01_Indian_Polity_Laxmikanth.pdf**: 97.53% - {'PASS': 29, 'FAIL': 1}
- **05 THE INDUSTRIAL DISPUTES ACT, 1947.pdf**: 86.49% - {'PASS': 21, 'FAIL': 9}

## Dangerous failures

- VG015 / safe_sentence_flat / p.124: **0.0%** - no matching entry on page
- VG017 / safe_sentence_flat / p.157: **8.0%** - highlight missing/altered; insufficient correct context; context order scrambled; substantial unrelated/unsafe text
- VG018 / safe_sentence_flat / p.214: **23.25%** - highlight missing/altered; insufficient correct context; context order scrambled; substantial unrelated/unsafe text
- VG090 / safe_sentence_flat / p.136: **0.0%** - no matching entry on page
- VG100 / safe_sentence_flat / p.240: **0.0%** - no matching entry on page

## Lowest-scoring comparisons

- VG015 / safe_sentence_flat / 01_A_Brief_History_of_Modern_India.pdf p.124: **0.0%** (DANGEROUS) no matching entry on page
- VG090 / safe_sentence_flat / 01_A_Brief_History_of_Modern_India.pdf p.136: **0.0%** (DANGEROUS) no matching entry on page
- VG100 / safe_sentence_flat / 01_A_Brief_History_of_Modern_India.pdf p.240: **0.0%** (DANGEROUS) no matching entry on page
- VG017 / safe_sentence_flat / 01_A_Brief_History_of_Modern_India.pdf p.157: **8.0%** (DANGEROUS) highlight missing/altered; insufficient correct context; context order scrambled; substantial unrelated/unsafe text
- VG018 / safe_sentence_flat / 01_A_Brief_History_of_Modern_India.pdf p.214: **23.25%** (DANGEROUS) highlight missing/altered; insufficient correct context; context order scrambled; substantial unrelated/unsafe text
- VG002 / safe_sentence_flat / 00_The_Constitution_of_India.pdf p.9: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG009 / safe_sentence_flat / 00_The_Constitution_of_India.pdf p.198: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG063 / safe_sentence_flat / 00_The_Constitution_of_India.pdf p.23: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG067 / safe_sentence_flat / 00_The_Constitution_of_India.pdf p.54: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG073 / safe_sentence_flat / 00_The_Constitution_of_India.pdf p.99: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG076 / safe_sentence_flat / 00_The_Constitution_of_India.pdf p.182: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG080 / safe_sentence_flat / 00_The_Constitution_of_India.pdf p.345: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG086 / safe_sentence_flat / 01_A_Brief_History_of_Modern_India.pdf p.99: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG095 / safe_sentence_flat / 01_A_Brief_History_of_Modern_India.pdf p.202: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG021 / safe_sentence_flat / 01_Fundamentals_of_Accounting_and_Financial_Analysis_Anil_Chowdhury_--_2006.pdf p.18: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG037 / safe_sentence_flat / 01_INDIAN_ECONOMY_FOR_CIVIL_SERVICES__UNIVERSITIES_AND_OTHER_EXAMINATIONS_-_Ramesh_Singh.pdf p.352: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG157 / safe_sentence_flat / 01_Indian_Polity_Laxmikanth.pdf p.754: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG163 / safe_sentence_flat / 05 THE INDUSTRIAL DISPUTES ACT, 1947.pdf p.12: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG166 / safe_sentence_flat / 05 THE INDUSTRIAL DISPUTES ACT, 1947.pdf p.25: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG167 / safe_sentence_flat / 05 THE INDUSTRIAL DISPUTES ACT, 1947.pdf p.26: **59.0%** (FAIL) insufficient correct context; context order scrambled

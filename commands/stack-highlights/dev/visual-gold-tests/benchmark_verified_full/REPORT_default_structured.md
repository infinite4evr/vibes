# Visual-gold regression report

Overall semantic correctness score: **91.01%** across **180** comparisons.

Scoring deliberately ignores Markdown, whitespace, line wrapping, punctuation spacing and harmless dehyphenation. Missing highlighted content, wrong context, scrambled order and unrelated text are penalised heavily.

## By profile

- **default_structured**: 91.01% - {'PASS': 148, 'FAIL': 26, 'REVIEW': 3, 'DANGEROUS': 3}

## By PDF

- **00_The_Constitution_of_India.pdf**: 84.26% - {'PASS': 19, 'FAIL': 10, 'REVIEW': 1}
- **01_A_Brief_History_of_Modern_India.pdf**: 86.38% - {'PASS': 24, 'DANGEROUS': 3, 'FAIL': 2, 'REVIEW': 1}
- **01_Fundamentals_of_Accounting_and_Financial_Analysis_Anil_Chowdhury_--_2006.pdf**: 96.41% - {'FAIL': 1, 'PASS': 28, 'REVIEW': 1}
- **01_INDIAN_ECONOMY_FOR_CIVIL_SERVICES__UNIVERSITIES_AND_OTHER_EXAMINATIONS_-_Ramesh_Singh.pdf**: 98.27% - {'PASS': 29, 'FAIL': 1}
- **01_Indian_Polity_Laxmikanth.pdf**: 97.4% - {'PASS': 29, 'FAIL': 1}
- **05 THE INDUSTRIAL DISPUTES ACT, 1947.pdf**: 83.33% - {'PASS': 19, 'FAIL': 11}

## Dangerous failures

- VG017 / default_structured / p.157: **8.0%** - highlight missing/altered; insufficient correct context; context order scrambled; substantial unrelated/unsafe text
- VG018 / default_structured / p.214: **12.5%** - highlight missing/altered; insufficient correct context; context order scrambled
- VG100 / default_structured / p.240: **0.0%** - no matching entry on page

## Lowest-scoring comparisons

- VG100 / default_structured / 01_A_Brief_History_of_Modern_India.pdf p.240: **0.0%** (DANGEROUS) no matching entry on page
- VG017 / default_structured / 01_A_Brief_History_of_Modern_India.pdf p.157: **8.0%** (DANGEROUS) highlight missing/altered; insufficient correct context; context order scrambled; substantial unrelated/unsafe text
- VG018 / default_structured / 01_A_Brief_History_of_Modern_India.pdf p.214: **12.5%** (DANGEROUS) highlight missing/altered; insufficient correct context; context order scrambled
- VG002 / default_structured / 00_The_Constitution_of_India.pdf p.9: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG009 / default_structured / 00_The_Constitution_of_India.pdf p.198: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG063 / default_structured / 00_The_Constitution_of_India.pdf p.23: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG067 / default_structured / 00_The_Constitution_of_India.pdf p.54: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG069 / default_structured / 00_The_Constitution_of_India.pdf p.66: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG073 / default_structured / 00_The_Constitution_of_India.pdf p.99: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG076 / default_structured / 00_The_Constitution_of_India.pdf p.182: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG078 / default_structured / 00_The_Constitution_of_India.pdf p.234: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG080 / default_structured / 00_The_Constitution_of_India.pdf p.345: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG086 / default_structured / 01_A_Brief_History_of_Modern_India.pdf p.99: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG095 / default_structured / 01_A_Brief_History_of_Modern_India.pdf p.202: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG021 / default_structured / 01_Fundamentals_of_Accounting_and_Financial_Analysis_Anil_Chowdhury_--_2006.pdf p.18: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG037 / default_structured / 01_INDIAN_ECONOMY_FOR_CIVIL_SERVICES__UNIVERSITIES_AND_OTHER_EXAMINATIONS_-_Ramesh_Singh.pdf p.352: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG157 / default_structured / 01_Indian_Polity_Laxmikanth.pdf p.754: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG163 / default_structured / 05 THE INDUSTRIAL DISPUTES ACT, 1947.pdf p.12: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG164 / default_structured / 05 THE INDUSTRIAL DISPUTES ACT, 1947.pdf p.21: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG166 / default_structured / 05 THE INDUSTRIAL DISPUTES ACT, 1947.pdf p.25: **59.0%** (FAIL) insufficient correct context; context order scrambled

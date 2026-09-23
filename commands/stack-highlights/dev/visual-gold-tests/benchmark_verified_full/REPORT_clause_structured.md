# Visual-gold regression report

Overall semantic correctness score: **87.04%** across **180** comparisons.

Scoring deliberately ignores Markdown, whitespace, line wrapping, punctuation spacing and harmless dehyphenation. Missing highlighted content, wrong context, scrambled order and unrelated text are penalised heavily.

## By profile

- **clause_structured**: 87.04% - {'PASS': 133, 'FAIL': 40, 'REVIEW': 4, 'DANGEROUS': 3}

## By PDF

- **00_The_Constitution_of_India.pdf**: 82.95% - {'PASS': 19, 'FAIL': 10, 'REVIEW': 1}
- **01_A_Brief_History_of_Modern_India.pdf**: 78.61% - {'PASS': 19, 'DANGEROUS': 3, 'FAIL': 7, 'REVIEW': 1}
- **01_Fundamentals_of_Accounting_and_Financial_Analysis_Anil_Chowdhury_--_2006.pdf**: 95.39% - {'FAIL': 2, 'PASS': 27, 'REVIEW': 1}
- **01_INDIAN_ECONOMY_FOR_CIVIL_SERVICES__UNIVERSITIES_AND_OTHER_EXAMINATIONS_-_Ramesh_Singh.pdf**: 90.46% - {'PASS': 24, 'FAIL': 6}
- **01_Indian_Polity_Laxmikanth.pdf**: 91.34% - {'PASS': 25, 'FAIL': 5}
- **05 THE INDUSTRIAL DISPUTES ACT, 1947.pdf**: 83.51% - {'PASS': 19, 'FAIL': 10, 'REVIEW': 1}

## Dangerous failures

- VG017 / clause_structured / p.157: **8.0%** - highlight missing/altered; insufficient correct context; context order scrambled; substantial unrelated/unsafe text
- VG018 / clause_structured / p.214: **12.5%** - highlight missing/altered; insufficient correct context; context order scrambled
- VG100 / clause_structured / p.240: **0.0%** - no matching entry on page

## Lowest-scoring comparisons

- VG100 / clause_structured / 01_A_Brief_History_of_Modern_India.pdf p.240: **0.0%** (DANGEROUS) no matching entry on page
- VG017 / clause_structured / 01_A_Brief_History_of_Modern_India.pdf p.157: **8.0%** (DANGEROUS) highlight missing/altered; insufficient correct context; context order scrambled; substantial unrelated/unsafe text
- VG018 / clause_structured / 01_A_Brief_History_of_Modern_India.pdf p.214: **12.5%** (DANGEROUS) highlight missing/altered; insufficient correct context; context order scrambled
- VG002 / clause_structured / 00_The_Constitution_of_India.pdf p.9: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG009 / clause_structured / 00_The_Constitution_of_India.pdf p.198: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG010 / clause_structured / 00_The_Constitution_of_India.pdf p.349: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG061 / clause_structured / 00_The_Constitution_of_India.pdf p.7: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG067 / clause_structured / 00_The_Constitution_of_India.pdf p.54: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG073 / clause_structured / 00_The_Constitution_of_India.pdf p.99: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG076 / clause_structured / 00_The_Constitution_of_India.pdf p.182: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG078 / clause_structured / 00_The_Constitution_of_India.pdf p.234: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG080 / clause_structured / 00_The_Constitution_of_India.pdf p.345: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG086 / clause_structured / 01_A_Brief_History_of_Modern_India.pdf p.99: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG088 / clause_structured / 01_A_Brief_History_of_Modern_India.pdf p.119: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG089 / clause_structured / 01_A_Brief_History_of_Modern_India.pdf p.131: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG095 / clause_structured / 01_A_Brief_History_of_Modern_India.pdf p.202: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG098 / clause_structured / 01_A_Brief_History_of_Modern_India.pdf p.224: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG021 / clause_structured / 01_Fundamentals_of_Accounting_and_Financial_Analysis_Anil_Chowdhury_--_2006.pdf p.18: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG033 / clause_structured / 01_INDIAN_ECONOMY_FOR_CIVIL_SERVICES__UNIVERSITIES_AND_OTHER_EXAMINATIONS_-_Ramesh_Singh.pdf p.79: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG037 / clause_structured / 01_INDIAN_ECONOMY_FOR_CIVIL_SERVICES__UNIVERSITIES_AND_OTHER_EXAMINATIONS_-_Ramesh_Singh.pdf p.352: **59.0%** (FAIL) insufficient correct context; context order scrambled

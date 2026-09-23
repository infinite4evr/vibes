# Visual-gold regression report

Overall semantic correctness score: **88.68%** across **180** comparisons.

Scoring deliberately ignores Markdown, whitespace, line wrapping, punctuation spacing and harmless dehyphenation. Missing highlighted content, wrong context, scrambled order and unrelated text are penalised heavily.

## By profile

- **window12_flat**: 88.68% - {'PASS': 148, 'FAIL': 27, 'DANGEROUS': 5}

## By PDF

- **00_The_Constitution_of_India.pdf**: 87.21% - {'PASS': 23, 'FAIL': 7}
- **01_A_Brief_History_of_Modern_India.pdf**: 74.14% - {'PASS': 20, 'DANGEROUS': 5, 'FAIL': 5}
- **01_Fundamentals_of_Accounting_and_Financial_Analysis_Anil_Chowdhury_--_2006.pdf**: 94.83% - {'FAIL': 3, 'PASS': 27}
- **01_INDIAN_ECONOMY_FOR_CIVIL_SERVICES__UNIVERSITIES_AND_OTHER_EXAMINATIONS_-_Ramesh_Singh.pdf**: 89.14% - {'PASS': 23, 'FAIL': 7}
- **01_Indian_Polity_Laxmikanth.pdf**: 93.18% - {'PASS': 28, 'FAIL': 2}
- **05 THE INDUSTRIAL DISPUTES ACT, 1947.pdf**: 93.58% - {'PASS': 27, 'FAIL': 3}

## Dangerous failures

- VG015 / window12_flat / p.124: **0.0%** - no matching entry on page
- VG017 / window12_flat / p.157: **7.5%** - highlight missing/altered; insufficient correct context; context order scrambled; substantial unrelated/unsafe text
- VG018 / window12_flat / p.214: **21.79%** - highlight missing/altered; insufficient correct context; context order scrambled; substantial unrelated/unsafe text
- VG090 / window12_flat / p.136: **0.0%** - no matching entry on page
- VG100 / window12_flat / p.240: **0.0%** - no matching entry on page

## Lowest-scoring comparisons

- VG015 / window12_flat / 01_A_Brief_History_of_Modern_India.pdf p.124: **0.0%** (DANGEROUS) no matching entry on page
- VG090 / window12_flat / 01_A_Brief_History_of_Modern_India.pdf p.136: **0.0%** (DANGEROUS) no matching entry on page
- VG100 / window12_flat / 01_A_Brief_History_of_Modern_India.pdf p.240: **0.0%** (DANGEROUS) no matching entry on page
- VG017 / window12_flat / 01_A_Brief_History_of_Modern_India.pdf p.157: **7.5%** (DANGEROUS) highlight missing/altered; insufficient correct context; context order scrambled; substantial unrelated/unsafe text
- VG018 / window12_flat / 01_A_Brief_History_of_Modern_India.pdf p.214: **21.79%** (DANGEROUS) highlight missing/altered; insufficient correct context; context order scrambled; substantial unrelated/unsafe text
- VG002 / window12_flat / 00_The_Constitution_of_India.pdf p.9: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG063 / window12_flat / 00_The_Constitution_of_India.pdf p.23: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG073 / window12_flat / 00_The_Constitution_of_India.pdf p.99: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG074 / window12_flat / 00_The_Constitution_of_India.pdf p.144: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG076 / window12_flat / 00_The_Constitution_of_India.pdf p.182: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG082 / window12_flat / 01_A_Brief_History_of_Modern_India.pdf p.64: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG086 / window12_flat / 01_A_Brief_History_of_Modern_India.pdf p.99: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG088 / window12_flat / 01_A_Brief_History_of_Modern_India.pdf p.119: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG098 / window12_flat / 01_A_Brief_History_of_Modern_India.pdf p.224: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG021 / window12_flat / 01_Fundamentals_of_Accounting_and_Financial_Analysis_Anil_Chowdhury_--_2006.pdf p.18: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG101 / window12_flat / 01_Fundamentals_of_Accounting_and_Financial_Analysis_Anil_Chowdhury_--_2006.pdf p.24: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG109 / window12_flat / 01_Fundamentals_of_Accounting_and_Financial_Analysis_Anil_Chowdhury_--_2006.pdf p.85: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG125 / window12_flat / 01_INDIAN_ECONOMY_FOR_CIVIL_SERVICES__UNIVERSITIES_AND_OTHER_EXAMINATIONS_-_Ramesh_Singh.pdf p.85: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG132 / window12_flat / 01_INDIAN_ECONOMY_FOR_CIVIL_SERVICES__UNIVERSITIES_AND_OTHER_EXAMINATIONS_-_Ramesh_Singh.pdf p.341: **59.0%** (FAIL) insufficient correct context; context order scrambled
- VG133 / window12_flat / 01_INDIAN_ECONOMY_FOR_CIVIL_SERVICES__UNIVERSITIES_AND_OTHER_EXAMINATIONS_-_Ramesh_Singh.pdf p.353: **59.0%** (FAIL) insufficient correct context; context order scrambled

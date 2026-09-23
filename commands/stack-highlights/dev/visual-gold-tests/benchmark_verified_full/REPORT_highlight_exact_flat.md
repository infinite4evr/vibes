# Visual-gold regression report

Overall semantic correctness score: **97.2%** across **180** comparisons.

Scoring deliberately ignores Markdown, whitespace, line wrapping, punctuation spacing and harmless dehyphenation. Missing highlighted content, wrong context, scrambled order and unrelated text are penalised heavily.

## By profile

- **highlight_exact_flat**: 97.2% - {'PASS': 175, 'DANGEROUS': 5}

## By PDF

- **00_The_Constitution_of_India.pdf**: 99.71% - {'PASS': 30}
- **01_A_Brief_History_of_Modern_India.pdf**: 83.89% - {'PASS': 25, 'DANGEROUS': 5}
- **01_Fundamentals_of_Accounting_and_Financial_Analysis_Anil_Chowdhury_--_2006.pdf**: 99.78% - {'PASS': 30}
- **01_INDIAN_ECONOMY_FOR_CIVIL_SERVICES__UNIVERSITIES_AND_OTHER_EXAMINATIONS_-_Ramesh_Singh.pdf**: 99.84% - {'PASS': 30}
- **01_Indian_Polity_Laxmikanth.pdf**: 100.0% - {'PASS': 30}
- **05 THE INDUSTRIAL DISPUTES ACT, 1947.pdf**: 100.0% - {'PASS': 30}

## Dangerous failures

- VG015 / highlight_exact_flat / p.124: **0.0%** - no matching entry on page
- VG017 / highlight_exact_flat / p.157: **0.0%** - highlight missing/altered
- VG018 / highlight_exact_flat / p.214: **16.67%** - highlight missing/altered
- VG090 / highlight_exact_flat / p.136: **0.0%** - no matching entry on page
- VG100 / highlight_exact_flat / p.240: **0.0%** - no matching entry on page

## Lowest-scoring comparisons

- VG015 / highlight_exact_flat / 01_A_Brief_History_of_Modern_India.pdf p.124: **0.0%** (DANGEROUS) no matching entry on page
- VG017 / highlight_exact_flat / 01_A_Brief_History_of_Modern_India.pdf p.157: **0.0%** (DANGEROUS) highlight missing/altered
- VG090 / highlight_exact_flat / 01_A_Brief_History_of_Modern_India.pdf p.136: **0.0%** (DANGEROUS) no matching entry on page
- VG100 / highlight_exact_flat / 01_A_Brief_History_of_Modern_India.pdf p.240: **0.0%** (DANGEROUS) no matching entry on page
- VG018 / highlight_exact_flat / 01_A_Brief_History_of_Modern_India.pdf p.214: **16.67%** (DANGEROUS) highlight missing/altered
- VG009 / highlight_exact_flat / 00_The_Constitution_of_India.pdf p.198: **91.18%** (PASS) 
- VG030 / highlight_exact_flat / 01_Fundamentals_of_Accounting_and_Financial_Analysis_Anil_Chowdhury_--_2006.pdf p.278: **93.33%** (PASS) 
- VG137 / highlight_exact_flat / 01_INDIAN_ECONOMY_FOR_CIVIL_SERVICES__UNIVERSITIES_AND_OTHER_EXAMINATIONS_-_Ramesh_Singh.pdf p.382: **95.24%** (PASS) 
- VG001 / highlight_exact_flat / 00_The_Constitution_of_India.pdf p.4: **100.0%** (PASS) 
- VG002 / highlight_exact_flat / 00_The_Constitution_of_India.pdf p.9: **100.0%** (PASS) 
- VG003 / highlight_exact_flat / 00_The_Constitution_of_India.pdf p.37: **100.0%** (PASS) 
- VG004 / highlight_exact_flat / 00_The_Constitution_of_India.pdf p.49: **100.0%** (PASS) 
- VG005 / highlight_exact_flat / 00_The_Constitution_of_India.pdf p.65: **100.0%** (PASS) 
- VG006 / highlight_exact_flat / 00_The_Constitution_of_India.pdf p.73: **100.0%** (PASS) 
- VG007 / highlight_exact_flat / 00_The_Constitution_of_India.pdf p.109: **100.0%** (PASS) 
- VG008 / highlight_exact_flat / 00_The_Constitution_of_India.pdf p.177: **100.0%** (PASS) 
- VG010 / highlight_exact_flat / 00_The_Constitution_of_India.pdf p.349: **100.0%** (PASS) 
- VG061 / highlight_exact_flat / 00_The_Constitution_of_India.pdf p.7: **100.0%** (PASS) 
- VG062 / highlight_exact_flat / 00_The_Constitution_of_India.pdf p.17: **100.0%** (PASS) 
- VG063 / highlight_exact_flat / 00_The_Constitution_of_India.pdf p.23: **100.0%** (PASS) 

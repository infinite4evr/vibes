# Page ranges (1-based, inclusive) of each source inside Test-Merged-All.pdf (9,916 pages).
SOURCES = [
    ("modern_india",   "A Brief History of Modern India (Spectrum, Rajiv Ahir)",        1,  920),
    ("constitution",   "The Constitution of India (2024 diglot)",                      921, 1322),
    ("acc_chowdhry",   "Fundamentals of Accounting & Financial Analysis (Chowdhry)",  1323, 1730),
    ("econ_ramesh",    "Indian Economy (Ramesh Singh)",                               1731, 2530),
    ("polity_laxmi",   "Indian Polity (M. Laxmikanth, 8th ed.)",                      2531, 3716),
    ("act_empcomp",    "Employee's Compensation Act, 1923",                           3717, 3798),
    ("acc_jain_panda", "Fundamentals of Accounting for CA-CPT (Jain & Panda)",        3799, 4567),
    ("act_tu",         "Trade Unions Act, 1926",                                      4568, 4591),
    ("acc_tmh_cpt",    "Accountancy for CA-CPT (Tata McGraw Hill)",                   4592, 5710),
    ("econ_vivek",     "Indian Economy (Vivek Singh, 7th ed.)",                       5711, 6185),
    ("labour_acts",    "Labour Acts: Payment of Wages 1936 ... Unorganised Workers 2008", 6186, 7035),
    ("icsi_pp_llp",    "ICSI Professional Programme: Labour Laws & Practice",         7036, 7635),
    ("icsi_ep_ilgl",   "ICSI Executive Programme: Industrial, Labour & General Laws", 7636, 8138),
    ("ilo_chronicle",  "India and the ILO: Chronicle of a Shared Journey",            8139, 8258),
    ("ir_pearson",     "Industrial Relations, Trade Unions & Labour Legislation (Pearson, 3e)", 8259, 9083),
    ("ir_ghosh",       "Industrial Relations and Labour Laws (Ghosh & Nanda)",        9084, 9916),
]
LABOUR_ACTS = [  # first page of each act inside labour_acts
    (6186, "Payment of Wages Act, 1936"), (6230, "Industrial Disputes Act, 1947"),
    (6376, "Minimum Wages Act, 1948"), (6414, "Employees' State Insurance Act, 1948"),
    (6536, "Factories Act, 1948"), (6656, "Plantations Labour Act, 1951"),
    (6704, "EPF & Misc. Provisions Act, 1952"), (6788, "Mines Act, 1952"),
    (6868, "Employment Exchanges (CNV) Act, 1959"), (6878, "Maternity Benefit Act, 1961"),
    (6900, "Payment of Bonus Act, 1965"), (6931, "Contract Labour (R&A) Act, 1970"),
    (6947, "Payment of Gratuity Act, 1972"), (6958, "Bonded Labour System (Abolition) Act, 1976"),
    (6966, "Equal Remuneration Act, 1976"), (6974, "Inter-State Migrant Workmen Act, 1979"),
    (6989, "Child & Adolescent Labour Act, 1986"), (7000, "BOCW Act, 1996"),
    (7023, "Unorganised Workers' Social Security Act, 2008"),
]
def source_of(page):
    for key, title, a, b in SOURCES:
        if a <= page <= b:
            return key
    return None
def act_of(page):
    name = None
    for p, n in LABOUR_ACTS:
        if page >= p: name = n
    return name if 6186 <= page <= 7035 else None

"""Python port of sqlite/ext/fts5/tool/mkfts5c.tcl (SQLite 3.50.4): builds the fts5.c composite."""
import re, sys
from pathlib import Path
S = Path(sys.argv[1]); d = S / "ext/fts5"
src = [d/"fts5.h", d/"fts5Int.h", Path("fts5parse.h"), Path("fts5parse.c")] + [d/f for f in (
    "fts5_aux.c fts5_buffer.c fts5_config.c fts5_expr.c fts5_hash.c fts5_index.c fts5_main.c "
    "fts5_storage.c fts5_tokenize.c fts5_unicode2.c fts5_varint.c fts5_vocab.c").split()]
hdr = open(d/"tool/mkfts5c.tcl").read().split("set G(hdr) {",1)[1].split("\n}\n",1)[0] + "\n"
footer = "\n/* Here ends the fts5.c composite file. */\n#endif /* !defined(SQLITE_CORE) || defined(SQLITE_ENABLE_FTS5) */\n"
uuid = (S/"manifest.uuid").read_text().strip()
L = (S/"manifest").read_text().split()
date = L[L.index("D")+1]; date = date[:date.rfind(".")].replace("T", " ")
source_id = f"fts5: {date} {uuid}"
out = [hdr]
for f in src:
    out.append(f'#line 1 "{f.name}"\n')
    subs = [("--FTS5-SOURCE-ID--", source_id)]
    lines = f.read_text().split("\n")
    res = []
    for line in lines:
        if re.search(r"^#include.*fts5", line):
            line = f"/* {line} */"
        elif not re.search(r" sqlite3Fts5Init\(", line) and re.search(r"^(const )?[a-zA-Z][a-zA-Z0-9]* [*]?sqlite3Fts5", line):
            line = "static " + line
        for a, b in subs:
            line = line.replace(a, b)
        if f.name == "fts5parse.c":   # Tcl's string map: longest match first at each position, left to right
            line = re.sub(r"yy|YY|TOKEN", lambda m: {"yy": "fts5yy", "YY": "fts5YY", "TOKEN": "FTS5TOKEN"}[m.group(0)], line)
        res.append(line)
    out.append("\n".join(res) + "\n")
out.append(footer)
Path("fts5.c").write_text("".join(out)[:-1] if False else "".join(out))
print(len("".join(out)), source_id)

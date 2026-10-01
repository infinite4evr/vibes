"""Python port of sqlite/tool/mksqlite3h.tcl (SQLite 3.50.4, without --useapicall): builds sqlite3.h."""
import re, sys
from pathlib import Path
S = Path(sys.argv[1])
ver = (S/"VERSION").read_text().strip()
nver = "%d%03d%03d" % tuple(int(x) for x in ver.split("."))
L = (S/"manifest").read_text().split(); date = L[L.index("D")+1]; date = date[:date.rfind(".")].replace("T", " ")
source_id = f"{date} {(S/'manifest.uuid').read_text().strip()}"
varpat = re.compile(r"^[a-zA-Z][a-zA-Z_0-9 *]+sqlite3_[_a-zA-Z0-9]+(\[|;| =)")
decls = [re.compile(r"^ *([a-zA-Z][a-zA-Z_0-9 ]+ \**)(%s_[_a-zA-Z0-9]+)(\(.*)$" % p)
         for p in ("sqlite3", "sqlite3session", "sqlite3changeset", "sqlite3changegroup", "sqlite3rebaser")]
out = []
for f in [S/"src/sqlite.h.in", S/"ext/rtree/sqlite3rtree.h", S/"ext/session/sqlite3session.h", S/"ext/fts5/fts5.h"]:
    first = f.name == "sqlite.h.in"
    if not first: out.append(f"/******** Begin file {f.name} *********/")
    for line in f.read_bytes().decode("latin-1").split("\n")[:-1] if f.read_bytes().endswith(b"\n") else f.read_bytes().decode("latin-1").split("\n"):
        line = line.rstrip()
        if re.search(r'#include.*[<"]sqlite3\.h[>"]', line): continue
        line = line.replace("--VERS--", ver, 1).replace("--VERSION-NUMBER--", nver, 1).replace("--SOURCE-ID--", source_id, 1)
        if varpat.search(line) and not re.search(r"^ *typedef", line):
            line = "SQLITE_API " + line
        else:
            for d in decls:
                m = d.search(line)
                if m:
                    rettype, fn, rest = m.groups()
                    line = "SQLITE_API " + rettype.strip() + ("" if rettype.endswith("*") else " ") + fn + rest
                    break
        out.append(line)
    if not first: out.append(f"/******** End of {f.name} *********/")
out.append("#endif /* SQLITE3_H */")
Path("sqlite3.h").write_bytes(("\n".join(out) + "\n").encode("latin-1"))

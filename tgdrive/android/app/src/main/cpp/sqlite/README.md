# SQLite FTS5, as a loadable extension

Python's `sqlite3` module in the Android runtime (Chaquopy) is built without full-text search.
TG Drive's search needs FTS5 (including the `trigram` tokenizer and `fts5vocab`), so the app
builds SQLite's own FTS5 module into `libtgfts5.so` and registers it with
`sqlite3_auto_extension` at startup (`tgdrive/mobile.py`), before any database opens.

The files here are generated from SQLite **3.50.4** (the version in Chaquopy's Python 3.13.9
runtime), check-in `4d8adfb30e03f9cf27f800a2c1ba3c48fb4ca1b08b0f5ed59a4d5ecbf45e20a3`:

| File | From |
|---|---|
| `fts5.c` | `ext/fts5/*` and Lemon's `fts5parse.c`, composed by `tools/mkfts5c.py` (a port of `ext/fts5/tool/mkfts5c.tcl`) |
| `sqlite3.h` | `src/sqlite.h.in` and the extension headers, by `tools/mksqlite3h.py` (a port of `tool/mksqlite3h.tcl`) |
| `sqlite3ext.h` | `src/sqlite3ext.h` |

To regenerate for another version:

```bash
git clone --depth 1 --branch version-3.50.4 https://github.com/sqlite/sqlite.git
cc -o lemon sqlite/tool/lemon.c
cp sqlite/ext/fts5/fts5parse.y sqlite/tool/lempar.c . && ./lemon -S fts5parse.y
python3 tools/mkfts5c.py sqlite && python3 tools/mksqlite3h.py sqlite
cp sqlite/src/sqlite3ext.h .
```

SQLite is in the public domain.

# vibes

Personal command-line tools, mostly for turning highlighted PDFs into study notes
and active-recall sheets.

| Path | What |
|---|---|
| `commands/` | one folder per command; see [`commands/README.md`](commands/README.md) for the list and setup |
| `commands/stack-highlights/` | the main tool: PDF highlights to notes, with its tests ([README](commands/stack-highlights/README.md)) |
| `commands/RESUME.md` | where the work stands and how to run every test |
| `todo.txt` | the feature requests the tools were built against |

Quick start:

```bash
cd commands
./install.sh                                            # chmod + npm install
python3 -m pip install -r stack-highlights/requirements.txt
echo "source $PWD/env.sh" >> ~/.bashrc                  # puts every command on PATH
make -C stack-highlights quick                          # sanity check, a few seconds
```

The PDF steps (`md-to-pdf`, `recall-sheet`, `notes`, `notes-recall`) also need
`pandoc` and a TeX Live with XeLaTeX and `lmodern`.

CI: [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

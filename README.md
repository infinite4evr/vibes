# vibes

Personal tools, in three independent projects:

| Path | What |
|---|---|
| [`commands/`](commands/README.md) | command-line tools, mostly for turning highlighted PDFs into study notes and active-recall sheets, plus YouTube-subscription and WhatsApp helpers |
| [`commands/stack-highlights/`](commands/stack-highlights/README.md) | the main study tool: PDF highlights to structured notes, with its tests |
| [`linux-setup/`](linux-setup/README.md) | Ubuntu cleanup and dev-environment setup, plus **PC Command Center** (GTK app) and **pc** (terminal app) for managing the whole computer (v2.2.4) |
| [`tgdrive/`](tgdrive/README.md) | **TG Drive**: every file in your Telegram, browsed, searched, streamed and organised like Google Drive (desktop app, AppImage) |

`commands/RESUME.md` says where the study tools stand and how to run every test.
`todo.txt`, the feature requests the study tools were built against, is kept
locally and is not in git.

## Quick start

**Study tools**

```bash
cd commands
./install.sh                                            # chmod + npm install
python3 -m pip install -r stack-highlights/requirements.txt
echo "source $PWD/env.sh" >> ~/.bashrc                  # puts every command on PATH
make -C stack-highlights quick                          # sanity check, a few seconds
```

The PDF steps (`md-to-pdf`, `recall-sheet`, `notes`, `notes-recall`) also need
`pandoc` and a TeX Live with XeLaTeX and `lmodern`.

**Linux setup and PC Command Center:** `bash linux-setup/setup.sh`, then pick
**4** the first time (details in its README).

**TG Drive:** `bash tgdrive/start.sh` (or `--install` to add it to the
applications menu).

## Tests

| Project | Command |
|---|---|
| study tools | `make -C commands/stack-highlights quick` (and `pdf-safety`); `npm test` in `commands/wa-auto-delete` |
| linux-setup | `cd linux-setup/pc && pip install -e '.[dev]' && pytest` |
| tgdrive | `cd tgdrive && pip install -r requirements.txt pytest httpx && python -m pytest tests` |

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) currently runs the
study-tool checks only. `linux-setup/.github/workflows/ci.yml` is not picked up
by GitHub, because workflows only run from the repository root, and tgdrive
has no CI job yet.

# vibes

Personal tools, in independent projects:

| Path | What |
|---|---|
| [`commands/`](commands/README.md) | command-line tools, mostly for turning highlighted PDFs into study notes and active-recall sheets, plus YouTube-subscription and WhatsApp helpers |
| [`commands/stack-highlights/`](commands/stack-highlights/README.md) | the main study tool: PDF highlights to structured notes, with its tests |
| [`lumaclean/`](lumaclean/README.md) | **LumaClean**: Android phone manager (cleaning, storage, apps, battery), built and released as an APK by CI |
| [`pc-command-center/`](pc-command-center/README.md) | **PC Command Center** (GTK app) and **pc** (terminal app) for managing a whole Ubuntu computer (v2.2.4) |
| [`ubuntu-setup/`](ubuntu-setup/README.md) | Ubuntu cleanup and Catppuccin dev-environment setup; also installs PC Command Center |
| [`tgdrive/`](tgdrive/README.md) | **TG Drive**: every file in your Telegram, browsed, searched, streamed and organised like Google Drive (desktop app, AppImage) |
| [`tgdrive/android/`](tgdrive/android/README.md) | **TG Drive for Android**: the same service running on the phone (Python via Chaquopy) with a native Compose interface, built and released as an APK by CI |

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

**Ubuntu setup and PC Command Center:** `bash ubuntu-setup/setup.sh`, then pick
**4** the first time (details in its README).

**LumaClean:** download the APK from the latest `lumaclean-v…` release.

**TG Drive:** `bash tgdrive/start.sh` (or `--install` to add it to the
applications menu). On Android, download the APK from the latest `tgdrive-android-v…` release.

## Tests

| Project | Command |
|---|---|
| study tools | `make -C commands/stack-highlights quick` (and `pdf-safety`); `npm test` in `commands/wa-auto-delete` |
| pc-command-center | `cd pc-command-center && pip install -e '.[dev]' && pytest` |
| lumaclean | built by CI only (`gradle :app:assembleRelease` with Android SDK 37) |
| tgdrive | `cd tgdrive && pip install -r requirements.txt pytest httpx && python -m pytest tests` (the browser test `tests/test_e2e.py` also needs `playwright`) |
| tgdrive/android | built and tested by CI (APK, service tests with the Android package set, emulator tests and screenshots) |

CI: [`ci.yml`](.github/workflows/ci.yml) runs the study-tool checks,
[`pc-command-center.yml`](.github/workflows/pc-command-center.yml) the PC Command
Center tests, shell syntax and a GTK smoke test, and
[`lumaclean-apk.yml`](.github/workflows/lumaclean-apk.yml) builds and releases the
LumaClean APK, and [`tgdrive.yml`](.github/workflows/tgdrive.yml) runs the TG Drive tests and an end-to-end
test of its interface in Chromium, and [`tgdrive-android.yml`](.github/workflows/tgdrive-android.yml) builds,
tests and releases the TG Drive Android APK.

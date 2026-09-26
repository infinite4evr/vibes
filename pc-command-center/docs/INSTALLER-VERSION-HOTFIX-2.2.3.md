# PC Command Center 2.2.3 — installer/version hotfix

## Symptom
After installing a newer source tree, About can still show an older version such as 2.2.0.

## Root cause
PC Command Center is a single-instance GTK application. Replacing its files while its Python process is still running does not reload modules already held in memory. Clicking the dock icon can therefore reactivate the old process even though the files on disk are newer.

A second possible cause is running `setup.sh` from an older extracted copy of the repository.

## Fixes
- `install_pc_app` prints the version from the source tree.
- The installer detects a running GUI and explains that it must be fully quit/reopened.
- The installer verifies the copied GUI version after installation and fails if it differs.
- Successful installation now prints the verified version.
- `pc-gui --version` reports the runtime GUI version.

## Quick verification

```bash
grep __version__ pc/src/pcctl/__init__.py
grep __version__ ~/.local/share/pc-command-center/pcctl/__init__.py
~/.local/bin/pc-gui --version
```

The source and installed file should match. If an old GUI process was running during installation, quit it with Ctrl+Q and reopen the application.

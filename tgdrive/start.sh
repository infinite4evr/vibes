#!/usr/bin/env bash
# TG Drive launcher. First run sets up a private Python environment in .venv
# (a few minutes, ~300 MB); later runs start straight away.
#
#   bash start.sh             desktop window
#   bash start.sh --browser   open in your web browser instead
#   bash start.sh --demo      try the UI on a fake account (no Telegram sign-in)
#   bash start.sh --reinstall rebuild the environment
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

if [ "${1:-}" = "--reinstall" ]; then rm -rf .venv; shift; fi

PY="${PYTHON:-python3}"
if [ ! -x .venv/bin/python ]; then
  command -v "$PY" >/dev/null || die "python3 is not installed"
  "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' || die "TG Drive needs Python 3.10 or newer"
  "$PY" -c 'import venv, ensurepip' 2>/dev/null \
    || die "Python venv support is missing. Install it with: sudo apt install python3-venv"
  say "First run: creating the environment in .venv"
  "$PY" -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip wheel
  say "Installing dependencies (about 300 MB, a few minutes)"
  .venv/bin/pip install --quiet -r requirements.txt || { rm -rf .venv; die "Dependency install failed (see above)."; }
  say "Setup done"
fi

if [ "${1:-}" = "--demo" ]; then
  say "Demo mode on fake data → http://127.0.0.1:8766"
  exec .venv/bin/python -m tests.demo_server
fi

if ! .venv/bin/python -c 'import PyQt6.QtWebEngineWidgets' 2>/dev/null && [[ " $* " != *" --browser "* ]]; then
  say "Desktop window unavailable on this system; opening in your browser instead"
  set -- --browser "$@"
fi
exec .venv/bin/python -m desktop "$@"

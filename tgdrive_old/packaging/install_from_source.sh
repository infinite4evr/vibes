#!/usr/bin/env bash
# Install TG Drive from this source folder (for systems the AppImage doesn't cover:
# ARM computers, glibc older than 2.28, or if you prefer a normal Python install).
#
#   packaging/install_from_source.sh            install for this user, add to the app menu
#   packaging/install_from_source.sh --no-gui   server + browser only (no Qt download)
#   packaging/install_from_source.sh --uninstall
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
VENV="${TGDRIVE_VENV:-$DATA_HOME/tgdrive/venv}"
BIN="$HOME/.local/bin/tgdrive"
GUI=1

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

for a in "$@"; do
  case "$a" in
    --no-gui) GUI=0 ;;
    --uninstall)
      [ -x "$VENV/bin/python" ] && PYTHONPATH="$SRC" "$VENV/bin/python" -m desktop --uninstall-desktop-entry || true
      rm -rf "$VENV" "$BIN"
      say "Removed the program. Your data is still in $DATA_HOME/tgdrive (delete it to remove everything)."
      exit 0 ;;
    *) die "unknown option $a" ;;
  esac
done

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null || die "python3 is not installed"
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' || die "TG Drive needs Python 3.10 or newer"
"$PY" -c 'import venv, ensurepip' 2>/dev/null || die "python venv support is missing (Debian/Ubuntu: sudo apt install python3-venv)"

say "Creating the environment in $VENV"
"$PY" -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip wheel
say "Installing dependencies (this downloads about $([ $GUI = 1 ] && echo 300 || echo 60) MB)"
if [ $GUI = 1 ]; then
  "$VENV/bin/pip" install --quiet -r "$SRC/requirements.txt"
else
  grep -v -i '^pyqt6' "$SRC/requirements.txt" | "$VENV/bin/pip" install --quiet -r /dev/stdin
fi

say "Adding the tgdrive command"
mkdir -p "$(dirname "$BIN")"
cat > "$BIN" <<EOF
#!/bin/sh
# TG Drive launcher (installed from $SRC)
PYTHONPATH="$SRC\${PYTHONPATH:+:\$PYTHONPATH}" exec "$VENV/bin/python" -m desktop $([ $GUI = 1 ] || echo "--browser ")"\$@"
EOF
chmod +x "$BIN"
TGDRIVE_LAUNCHER="$BIN" PYTHONPATH="$SRC" "$VENV/bin/python" -m desktop --install-desktop-entry

say "Done. Start TG Drive from your applications menu, or run: tgdrive"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "   (add ~/.local/bin to your PATH to use the tgdrive command)";; esac

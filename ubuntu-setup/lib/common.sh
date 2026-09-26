# shellcheck shell=bash
# Shared helpers used by every part of ubuntu-setup.

# Setup state can contain command output, backup paths and configuration details.
# Keep newly-created state private by default. Individual public files are installed
# with explicit modes where needed.
umask 077

C_RESET=$'\e[0m'; C_BOLD=$'\e[1m'; C_DIM=$'\e[2m'
C_MAUVE=$'\e[38;2;203;166;247m'; C_GREEN=$'\e[38;2;166;227;161m'
C_RED=$'\e[38;2;243;139;168m'; C_YELLOW=$'\e[38;2;249;226;175m'
C_BLUE=$'\e[38;2;137;180;250m'; C_PEACH=$'\e[38;2;250;179;135m'

STATE_DIR="$HOME/.local/state/linux-setup"
RUN_ID="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$STATE_DIR/backup-$RUN_ID"
LOG_FILE="$STATE_DIR/log-$RUN_ID.txt"
mkdir -p -m 700 "$STATE_DIR"
chmod 700 "$STATE_DIR" 2>/dev/null || true

title() { printf '\n%s%s━━ %s ━━%s\n' "$C_BOLD" "$C_MAUVE" "$*" "$C_RESET"; }
info()  { printf '  %s•%s %s\n' "$C_BLUE" "$C_RESET" "$*"; }
ok()    { printf '  %s✓%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn()  { printf '  %s!%s %s\n' "$C_YELLOW" "$C_RESET" "$*"; }
err()   { printf '  %s✗%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; }
dim()   { printf '    %s%s%s\n' "$C_DIM" "$*" "$C_RESET"; }

# ask "Question" y|n  -> exit status 0 means yes. Default answer is used on Enter.
ask() {
  local q=$1 def=${2:-n} hint reply
  if [[ $def == y ]]; then hint="[Y/n]"; else hint="[y/N]"; fi
  if [[ ${ASSUME_YES:-0} == 1 ]]; then [[ $def == y ]]; return; fi
  read -r -p "  ${C_PEACH}?${C_RESET} $q $hint " reply </dev/tty || reply=""
  reply=${reply:-$def}
  [[ $reply =~ ^[Yy] ]]
}

have() { command -v "$1" >/dev/null 2>&1; }

human() {
  local b=${1:-0}
  if (( b < 1024 )); then echo "${b} B"; return; fi
  numfmt --to=iec --suffix=B --format='%.1f' "$b" 2>/dev/null | sed 's/\([0-9]\)\([KMGT]\)/\1 \2/' || echo "$b B"
}

# Total bytes used by the given paths (uses sudo silently when it already has rights).
size_of() {
  local total=0 s p
  for p in "$@"; do
    [[ -e $p || -L $p ]] || continue
    if [[ -r $p ]] && s=$(du -sB1 -- "$p" 2>/dev/null | tail -1 | cut -f1) && [[ -n $s ]]; then :
    else s=$(sudo -n du -sB1 -- "$p" 2>/dev/null | tail -1 | cut -f1); fi
    total=$(( total + ${s:-0} ))
  done
  echo "$total"
}

SUDO_READY=0
need_sudo() {
  [[ $SUDO_READY == 1 ]] && return 0
  info "The next steps need your password (the one you use to log in)."
  if ! sudo -v; then err "Couldn't get admin rights. Stopping."; exit 1; fi
  # Keep sudo alive until this script ends.
  ( while kill -0 "$$" 2>/dev/null; do sudo -n true 2>/dev/null; sleep 45; done ) &
  SUDO_READY=1
}

# Copy a file/dir into this run's backup folder (path kept relative to $HOME).
backup() {
  local f=$1 rel
  [[ -e $f || -L $f ]] || return 0
  rel=${f#"$HOME"/}
  mkdir -p "$BACKUP_DIR/$(dirname "$rel")"
  cp -a -- "$f" "$BACKUP_DIR/$rel"
  echo "$rel" >> "$BACKUP_DIR/.files"
}

# Is an apt package available in the configured repositories?
apt_has() { [[ -n $(apt-cache policy "$1" 2>/dev/null | awk '/Candidate:/ && $2 != "(none)" {print $2}') ]]; }
# Is an apt package installed?
pkg_installed() { dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q "install ok installed"; }

# Run a step, keep going if it fails, remember failures for the summary.
FAILED_STEPS=()
step() {
  local name=$1; shift
  if "$@"; then return 0; fi
  FAILED_STEPS+=("$name")
  err "\"$name\" hit a problem - skipped it and moved on (details in $LOG_FILE)."
  return 0
}

gnome_session() { [[ -n ${DBUS_SESSION_BUS_ADDRESS:-} ]] && have gsettings; }

# gset schema key value  -> only sets keys that exist on this system.
gset() {
  local schema=$1 key=$2 val=$3
  if gsettings writable "$schema" "$key" >/dev/null 2>&1; then
    gsettings set "$schema" "$key" "$val" 2>/dev/null || warn "Couldn't set $schema $key"
  fi
}

. /etc/os-release 2>/dev/null || true
UBUNTU_VERSION=${VERSION_ID:-0}

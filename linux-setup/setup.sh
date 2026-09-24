#!/usr/bin/env bash
# linux-setup - clean up Ubuntu and set up a good-looking dev environment (Catppuccin Mocha).
#
#   bash setup.sh          menu
#   bash setup.sh scan     see what's using space (changes nothing)
#   bash setup.sh clean    remove junk (asks before every step)
#   bash setup.sh setup    install tools + theme everything
#   bash setup.sh all      scan, clean, then setup
#   bash setup.sh tips     cheat sheet
#   bash setup.sh undo     put your old look/settings back

if [[ $EUID -eq 0 ]]; then
  echo "Please run this as your normal user (without sudo). It will ask for your password when needed."
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for f in common scan clean install undo tips; do
  # shellcheck source=/dev/null
  . "$SCRIPT_DIR/lib/$f.sh"
done

banner() {
  printf '\n  %s%slinux-setup%s  %s·  Ubuntu %s  ·  Catppuccin Mocha%s\n' "$C_BOLD" "$C_MAUVE" "$C_RESET" "$C_DIM" "$UBUNTU_VERSION" "$C_RESET"
}

menu() {
  banner
  cat <<EOF

    ${C_MAUVE}1${C_RESET}  Scan       see what's taking space (changes nothing)
    ${C_MAUVE}2${C_RESET}  Clean up   remove junk - asks before each step
    ${C_MAUVE}3${C_RESET}  Set up     install dev tools + make it beautiful
    ${C_MAUVE}4${C_RESET}  Do all 3   ${C_DIM}recommended the first time${C_RESET}
    ${C_MAUVE}5${C_RESET}  Tips       cheat sheet of your new commands
    ${C_MAUVE}6${C_RESET}  Undo       put your old look and settings back
    ${C_MAUVE}q${C_RESET}  Quit

EOF
  local choice
  read -r -p "  Pick a number: " choice </dev/tty
  case $choice in
    1) run scan ;; 2) run clean ;; 3) run setup ;; 4) run all ;;
    5) run tips ;; 6) run undo ;; *) exit 0 ;;
  esac
}

run() {
  case $1 in
    scan)  scan_main ;;
    clean) clean_main ;;
    setup) setup_main ;;
    all)   scan_main; ask "Continue to cleanup?" y && clean_main; ask "Continue to setup?" y && setup_main ;;
    tips)  tips_main; return ;;
    undo)  undo_main ;;
    *)     sed -n '3,10p' "$0"; return ;;
  esac
  printf '\n  %sLog saved to %s%s\n\n' "$C_DIM" "$LOG_FILE" "$C_RESET"
}

if [[ ${1:-} == tips ]]; then tips_main; exit 0; fi

# Keep a log of everything (prompts still work normally).
exec > >(tee -a "$LOG_FILE") 2>&1

if [[ -n ${1:-} ]]; then run "$1"; else menu; fi

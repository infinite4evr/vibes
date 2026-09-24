# shellcheck shell=bash
# Read-only report: shows what is using space and what could be cleaned. Changes nothing.

# Caches that are always safe to delete (apps rebuild them when needed).
SAFE_CACHES=(
  "$HOME/.cache/thumbnails"
  "$HOME/.cache/pip"
  "$HOME/.cache/pypoetry"
  "$HOME/.cache/uv"
  "$HOME/.cache/yarn"
  "$HOME/.cache/node-gyp"
  "$HOME/.cache/typescript"
  "$HOME/.cache/go-build"
  "$HOME/.cache/gnome-software"
  "$HOME/.npm/_cacache"
  "$HOME/.npm/_logs"
)

# .desktop launchers in ~/.local/share/applications whose program no longer exists.
broken_launchers() {
  local f exec_line cmd
  for f in "$HOME"/.local/share/applications/*.desktop; do
    [[ -f $f ]] || continue
    exec_line=$(grep -m1 '^Exec=' "$f" | cut -d= -f2-)
    [[ -z $exec_line ]] && continue
    # drop "env VAR=x" prefixes and quotes, keep the program
    read -r -a parts <<< "$exec_line"
    local i=0
    if [[ ${parts[0]} == env || ${parts[0]} == */env ]]; then
      i=1; while [[ ${parts[$i]:-} == *=* ]]; do i=$((i+1)); done
    fi
    cmd=${parts[$i]:-}; cmd=${cmd//\"/}; cmd=${cmd//\'/}
    [[ -z $cmd ]] && continue
    if [[ $cmd == /* ]]; then [[ -e $cmd ]] || echo "$f"
    else have "$cmd" || echo "$f"; fi
  done
}

row() { printf '  %-44s %10s   %s\n' "$1" "$2" "${C_DIM}$3${C_RESET}"; }

scan_main() {
  title "Disk space"
  df -h --output=target,size,used,avail,pcent / /home 2>/dev/null | awk 'NR==1 || !seen[$1]++' | sed 's/^/  /'

  title "Biggest folders in your home"
  info "Measuring… (can take a minute the first time)"
  du -xsB1 "$HOME"/* "$HOME"/.[!.]* 2>/dev/null | sort -rn | head -15 | while read -r b p; do
    printf '  %10s   %s\n' "$(human "$b")" "${p/#$HOME/\~}"
  done

  title "Junk that can be cleaned safely"
  local n

  n=$(apt-get -s autoremove 2>/dev/null | grep -c '^Remv')
  row "Unused packages + old kernels" "$n pkgs" "apt autoremove"
  row "Downloaded package files" "$(human "$(size_of /var/cache/apt/archives)")" "apt clean"
  n=$(dpkg -l 2>/dev/null | awk '/^rc/{c++} END{print c+0}')
  row "Leftover settings of removed apps" "$n pkgs" "dpkg purge"

  if have snap; then
    local snap_bytes=0 name rev
    while read -r name rev; do
      snap_bytes=$(( snap_bytes + $(size_of "/var/lib/snapd/snaps/${name}_${rev}.snap") ))
    done < <(LANG=C snap list --all 2>/dev/null | awk '/disabled/{print $1, $3}')
    row "Old snap versions" "$(human "$snap_bytes")" "snap remove --revision"
  fi
  if have flatpak; then
    row "Flatpak apps installed" "$(flatpak list --app 2>/dev/null | wc -l) apps" "unused runtimes removed in cleanup"
  fi

  local j
  j=$(journalctl --disk-usage 2>/dev/null | grep -oE '[0-9.]+[KMGT]' | head -1)
  row "System logs (journal)" "${j:-?}" "shrink to 200M"
  row "Trash" "$(human "$(size_of "$HOME/.local/share/Trash")")" "empty trash"

  local cache_total=0
  for p in "${SAFE_CACHES[@]}"; do cache_total=$(( cache_total + $(size_of "$p") )); done
  row "Developer + app caches" "$(human "$cache_total")" "pip/npm/poetry/thumbnail caches"
  [[ -d $HOME/.pm2/logs ]] && row "pm2 log files" "$(human "$(size_of "$HOME/.pm2/logs")")" "emptied, your bot keeps running"

  local bl
  bl=$(broken_launchers | wc -l)
  row "Broken app shortcuts" "$bl" "launchers for apps that are gone"

  title "Things you chose to remove"
  if have waydroid || [[ -d /var/lib/waydroid || -d $HOME/.local/share/waydroid ]]; then
    row "Waydroid (Android container)" "$(human "$(size_of /var/lib/waydroid "$HOME/.local/share/waydroid")")" "package + images"
  else row "Waydroid (Android container)" "-" "not installed"; fi
  if [[ -d $HOME/.android ]]; then row "~/.android (adb keys, emulator data)" "$(human "$(size_of "$HOME/.android")")" ""
  else row "~/.android" "-" "already gone"; fi

  if [[ -d $HOME/.nvm/versions/node || -d $HOME/.pyenv/versions ]]; then
    title "Old language versions (you can pick which to keep)"
    local v
    for v in "$HOME"/.nvm/versions/node/*/ "$HOME"/.pyenv/versions/*/; do
      [[ -d $v ]] || continue
      row "${v/#$HOME/\~}" "$(human "$(size_of "$v")")" ""
    done
  fi

  title "Big files (over 1 GB) - just so you know, not deleted"
  find "$HOME" -xdev -type f -size +1G -not -path '*/.local/share/Trash/*' -printf '%s\t%p\n' 2>/dev/null \
    | sort -rn | head -10 | while IFS=$'\t' read -r b p; do printf '  %10s   %s\n' "$(human "$b")" "${p/#$HOME/\~}"; done

  title "Apps that start automatically when you log in"
  local a found=0
  for a in "$HOME"/.config/autostart/*.desktop; do
    [[ -f $a ]] || continue; found=1
    if grep -qi '^Hidden=true\|X-GNOME-Autostart-enabled=false' "$a"; then
      printf '  %s(off)%s %s\n' "$C_DIM" "$C_RESET" "$(grep -m1 '^Name=' "$a" | cut -d= -f2-)"
    else
      printf '  %s(on)%s  %s\n' "$C_GREEN" "$C_RESET" "$(grep -m1 '^Name=' "$a" | cut -d= -f2-)"
    fi
  done
  (( found )) || info "None"
  dim "Change these any time in the 'Startup Applications' or GNOME Tweaks app."

  local failed
  failed=$(systemctl --failed --no-legend 2>/dev/null | wc -l)
  if (( failed > 0 )); then
    title "Services that are failing"
    systemctl --failed --no-legend 2>/dev/null | sed 's/^/  /'
  fi

  printf '\n  %sNothing was changed. Run option 2 (Clean up) to remove the junk above.%s\n' "$C_GREEN" "$C_RESET"
}

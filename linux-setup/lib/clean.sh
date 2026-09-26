# shellcheck shell=bash
# Cleanup. Every step says what it will delete and asks first.
# Nothing in Documents, Downloads, Pictures, Music, Videos or your projects is touched.

free_bytes() { df --output=avail -B1 "$HOME" | tail -1 | tr -d ' '; }

clean_apt() {
  title "System packages"
  info "Removes packages nothing needs anymore (incl. old kernels) and the installer files apt keeps."
  ask "Clean up system packages?" y || return 0
  need_sudo
  sudo apt-get autoremove --purge -y
  sudo apt-get clean
  local rc
  rc=$(dpkg -l | awk '/^rc/{print $2}')
  if [[ -n $rc ]]; then
    # shellcheck disable=SC2086
    sudo dpkg --purge $rc >/dev/null && ok "Removed leftover settings of $(wc -w <<<"$rc") uninstalled apps"
  fi
  ok "Packages cleaned"
}

clean_snap() {
  have snap || return 0
  local list
  list=$(LANG=C snap list --all 2>/dev/null | awk '/disabled/{print $1, $3}')
  title "Old snap versions"
  if [[ -z $list ]]; then ok "Nothing to clean"; return 0; fi
  info "Snap keeps old copies of every app after updates. These are safe to remove:"
  sed 's/^/      /' <<<"$list"
  ask "Remove old snap versions and keep only 2 from now on?" y || return 0
  need_sudo
  local name rev
  while read -r name rev; do
    sudo snap remove "$name" --revision="$rev" >/dev/null && ok "Removed $name (old version $rev)"
  done <<<"$list"
  sudo snap set system refresh.retain=2
}

clean_flatpak() {
  have flatpak || return 0
  title "Flatpak"
  info "Removes shared runtimes that no installed Flatpak app uses anymore."
  ask "Remove unused Flatpak runtimes?" y || return 0
  flatpak uninstall --unused -y --noninteractive 2>/dev/null || true
  need_sudo
  sudo flatpak uninstall --unused -y --noninteractive 2>/dev/null || true
  ok "Flatpak cleaned"
}

clean_journal() {
  title "System logs"
  info "Linux keeps logs of everything; they can grow to several GB. This keeps the last 200 MB."
  ask "Shrink logs and cap them at 300 MB from now on?" y || return 0
  need_sudo
  sudo journalctl --vacuum-size=200M >/dev/null 2>&1
  sudo mkdir -p /etc/systemd/journald.conf.d
  printf '[Journal]\nSystemMaxUse=300M\n' | sudo tee /etc/systemd/journald.conf.d/99-linux-setup.conf >/dev/null
  sudo systemctl restart systemd-journald 2>/dev/null || true
  ok "Logs trimmed"
}

clean_caches() {
  title "Caches"
  local total=0 p
  for p in "${SAFE_CACHES[@]}"; do total=$(( total + $(size_of "$p") )); done
  info "Download caches from pip, npm, poetry, uv, yarn, plus thumbnail previews: $(human "$total")."
  dim "Apps rebuild these automatically; your projects and settings are not affected."
  if (( total > 0 )) && ask "Delete these caches?" y; then
    for p in "${SAFE_CACHES[@]}"; do [[ -e $p ]] && rm -rf -- "$p"; done
    ok "Caches cleared"
  fi
  if [[ -d $HOME/.pm2/logs ]]; then
    local pm2size; pm2size=$(size_of "$HOME/.pm2/logs")
    if (( pm2size > 5*1024*1024 )) && ask "Empty pm2 log files ($(human "$pm2size"))? Your running bots are not stopped." y; then
      find "$HOME/.pm2/logs" -type f -name '*.log' -exec truncate -s 0 {} +
      ok "pm2 logs emptied"
    fi
  fi
}

clean_trash() {
  local t; t=$(size_of "$HOME/.local/share/Trash")
  (( t > 0 )) || return 0
  title "Trash"
  info "Your Trash holds $(human "$t")."
  ask "Empty the Trash? (can't be undone)" n || return 0
  if have gio; then gio trash --empty 2>/dev/null; fi
  rm -rf -- "$HOME/.local/share/Trash/files/"* "$HOME/.local/share/Trash/info/"* "$HOME/.local/share/Trash/expunged/"* 2>/dev/null
  ok "Trash emptied"
}

clean_launchers() {
  local list; list=$(broken_launchers)
  [[ -z $list ]] && return 0
  title "Broken app shortcuts"
  info "These icons in your app grid point to programs that no longer exist:"
  while read -r f; do dim "$(grep -m1 '^Name=' "$f" | cut -d= -f2-)  ($(basename "$f"))"; done <<<"$list"
  ask "Remove them from the app grid? (a copy is kept in the backup folder)" y || return 0
  mkdir -p "$BACKUP_DIR/removed-launchers"
  while read -r f; do mv -- "$f" "$BACKUP_DIR/removed-launchers/"; done <<<"$list"
  update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
  ok "Shortcuts removed"
}

clean_waydroid() {
  local present=0
  { have waydroid || pkg_installed waydroid || [[ -d /var/lib/waydroid || -d $HOME/.local/share/waydroid ]]; } && present=1
  if (( present )); then
    title "Waydroid (Android on Linux)"
    info "Size: $(human "$(size_of /var/lib/waydroid "$HOME/.local/share/waydroid")") - removes the app, its Android image and its app icons."
    if ask "Remove Waydroid completely?" y; then
      need_sudo
      waydroid session stop >/dev/null 2>&1 || true
      sudo waydroid container stop >/dev/null 2>&1 || true
      sudo systemctl disable --now waydroid-container.service >/dev/null 2>&1 || true
      pkg_installed waydroid && sudo apt-get purge -y waydroid
      sudo rm -rf /var/lib/waydroid /home/.waydroid "$HOME/waydroid" "$HOME/.share/waydroid" "$HOME/.local/share/waydroid"
      rm -f "$HOME"/.local/share/applications/*aydroid*.desktop
      local src
      for src in /etc/apt/sources.list.d/waydroid.list /etc/apt/sources.list.d/waydroid.sources /usr/share/keyrings/waydroid.gpg; do
        [[ -e $src ]] && sudo rm -f "$src"
      done
      update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
      sudo apt-get autoremove --purge -y >/dev/null 2>&1 || true
      ok "Waydroid removed"
    fi
  fi
  if [[ -d $HOME/.android ]]; then
    title "~/.android folder"
    info "Android tools data (adb keys, emulator images): $(human "$(size_of "$HOME/.android")")."
    dim "If you ever use adb again it simply asks your phone to trust the PC once more."
    ask "Delete ~/.android?" y && rm -rf -- "$HOME/.android" && ok "Deleted ~/.android"
  fi
}

clean_old_runtimes() {
  local keep=() v name
  if [[ -d $HOME/.nvm/versions/node ]]; then
    local def pm2svc
    def=$(bash -c '. "$HOME/.nvm/nvm.sh" >/dev/null 2>&1 && nvm version default' 2>/dev/null)
    [[ -n $def && $def != N/A ]] && keep+=("$def")
    # the Node version your pm2 background service runs on
    for pm2svc in /etc/systemd/system/pm2-*.service; do
      [[ -f $pm2svc ]] && keep+=( $(grep -oE '\.nvm/versions/node/v[0-9.]+' "$pm2svc" | sed 's#.*/##' | sort -u) )
    done
    # If we can't tell which one you use, keep the newest to be safe.
    if (( ${#keep[@]} == 0 )); then
      keep+=( "$(find "$HOME/.nvm/versions/node" -mindepth 1 -maxdepth 1 -name 'v*' -printf '%f\n' | sort -V | tail -1)" )
    fi
    local others=()
    for v in "$HOME"/.nvm/versions/node/v*/; do
      [[ -d $v ]] || continue
      name=$(basename "$v")
      [[ " ${keep[*]} " == *" $name "* ]] || others+=("$name")
    done
    if (( ${#others[@]} )); then
      title "Old Node.js versions (nvm)"
      info "Keeping ${keep[*]} (your default / used by pm2). Other installed versions:"
      for name in "${others[@]}"; do
        if ask "Remove Node $name ($(human "$(size_of "$HOME/.nvm/versions/node/$name")"))?" n; then
          rm -rf -- "$HOME/.nvm/versions/node/$name" && ok "Removed Node $name"
        fi
      done
    fi
  fi
  if [[ -d $HOME/.pyenv/versions ]]; then
    local global=""
    [[ -f $HOME/.pyenv/version ]] && global=$(head -1 "$HOME/.pyenv/version")
    local pv=()
    for v in "$HOME"/.pyenv/versions/*/; do
      [[ -d $v ]] || continue
      name=$(basename "$v"); [[ $name == "$global" ]] || pv+=("$name")
    done
    if (( ${#pv[@]} )); then
      title "Old Python versions (pyenv)"
      info "Keeping ${global:-system Python} (your global). Others:"
      for name in "${pv[@]}"; do
        if ask "Remove Python $name ($(human "$(size_of "$HOME/.pyenv/versions/$name")"))?" n; then
          rm -rf -- "$HOME/.pyenv/versions/$name" && ok "Removed Python $name"
        fi
      done
    fi
  fi
}

clean_extras() {
  if pkg_installed warp-terminal; then
    title "Warp terminal"
    info "The new setup uses Ghostty as your terminal, so Warp becomes a duplicate."
    if ask "Uninstall Warp terminal?" n; then need_sudo; sudo apt-get purge -y warp-terminal && ok "Warp removed"; fi
  fi
  if have podman && [[ -n $(podman ps -aq 2>/dev/null)$(podman images -qf dangling=true 2>/dev/null) ]]; then
    title "Podman containers"
    podman system df 2>/dev/null | sed 's/^/  /'
    ask "Remove stopped containers and unused image layers?" n && podman system prune -f >/dev/null && ok "Podman pruned"
  fi
}

clean_main() {
  local before after
  before=$(free_bytes)
  title "Cleanup"
  info "Each step explains itself and asks first. Press Enter to accept the suggested answer."
  clean_apt
  clean_snap
  clean_flatpak
  clean_journal
  clean_caches
  clean_trash
  clean_launchers
  clean_waydroid
  clean_old_runtimes
  clean_extras
  after=$(free_bytes)
  title "Done"
  if (( after > before )); then ok "Freed $(human $(( after - before ))) of disk space."
  else ok "Cleanup finished."; fi
}

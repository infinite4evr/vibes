# shellcheck shell=bash
# Put the old look, shell and config files back. Installed apps stay (remove them with apt if you like).

undo_main() {
  title "Undo: restore your previous look and settings"
  local orig="$STATE_DIR/originals" created="$STATE_DIR/created-files.txt" gs="$STATE_DIR/gsettings-original.tsv"
  if [[ ! -d $orig && ! -f $created && ! -f $gs ]]; then ok "Nothing to undo - setup hasn't changed anything yet."; return 0; fi
  info "This restores GNOME settings, your old config files and bash as your shell."
  ask "Go ahead?" n || return 0

  if [[ -f $gs ]] && have gsettings; then
    local schema key val
    while IFS=$'\t' read -r schema key val; do
      gsettings set "$schema" "$key" "$val" 2>/dev/null || true
    done < "$gs"
    ok "GNOME settings restored"
  fi

  if [[ -f $created ]]; then
    local rel
    while read -r rel; do [[ -n $rel ]] && rm -f -- "${HOME:?}/$rel"; done < "$created"
  fi
  if [[ -d $orig ]]; then
    ( cd "$orig" && find . -mindepth 1 \( -type f -o -type l \) -print0 ) | while IFS= read -r -d '' f; do
      mkdir -p "$HOME/$(dirname "${f#./}")"
      cp -a -- "$orig/${f#./}" "$HOME/${f#./}"
    done
    ok "Config files restored"
  fi

  if [[ $(getent passwd "$USER" | cut -d: -f7) == */zsh ]] && ask "Switch your shell back to bash?" y; then
    need_sudo; sudo chsh -s /bin/bash "$USER" && ok "bash is your shell again (after logging out and in)"
  fi

  if have gext || [[ -x $HOME/.local/bin/gext ]]; then
    local g=${HOME}/.local/bin/gext
    "$g" -F disable blur-my-shell@aunetx clipboard-indicator@tudmotu.com caffeine@patapon.info >/dev/null 2>&1 || true
  fi
  rm -f "$gs" "$created"; rm -rf "$orig"
  ok "Done. Log out and back in to see everything restored."
}

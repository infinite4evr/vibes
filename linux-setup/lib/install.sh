# shellcheck shell=bash
# Dev tools + Catppuccin Mocha look for Ubuntu GNOME.

RAW_CAT="https://raw.githubusercontent.com/catppuccin"
TMPD=""
tmpdir() { [[ -n $TMPD ]] || TMPD=$(mktemp -d); echo "$TMPD"; }

fetch() { curl -fsSL --retry 3 --connect-timeout 15 "$1" -o "$2"; }

# Download an installer script first, then run it (so a failed download never "succeeds").
run_installer() {
  local url=$1; shift
  local f; f="$(tmpdir)/installer-$RANDOM.sh"
  fetch "$url" "$f" && [[ -s $f ]] && sh "$f" "$@"
}

# Remember the original value of each GNOME setting we touch, so "undo" can restore it.
GSET_ORIG="$STATE_DIR/gsettings-original.tsv"
gset_keep() {
  local schema=$1 key=$2 val=$3 old
  gsettings writable "$schema" "$key" >/dev/null 2>&1 || return 0
  if ! grep -qF "$schema"$'\t'"$key"$'\t' "$GSET_ORIG" 2>/dev/null; then
    old=$(gsettings get "$schema" "$key" 2>/dev/null) && printf '%s\t%s\t%s\n' "$schema" "$key" "$old" >> "$GSET_ORIG"
  fi
  gsettings set "$schema" "$key" "$val" 2>/dev/null || warn "Couldn't set $key"
}

# Save the very first version of a file we change (for undo), plus a per-run copy.
ORIG_DIR="$STATE_DIR/originals"
CREATED_LIST="$STATE_DIR/created-files.txt"
keep_original() {
  local f=$1 rel=${1#"$HOME"/}
  if [[ -e $f || -L $f ]]; then
    if [[ ! -e $ORIG_DIR/$rel ]] && ! grep -qxF "$rel" "$CREATED_LIST" 2>/dev/null; then
      mkdir -p "$ORIG_DIR/$(dirname "$rel")"; cp -a -- "$f" "$ORIG_DIR/$rel"
    fi
    backup "$f"
  else
    [[ -e $ORIG_DIR/$rel ]] || grep -qxF "$rel" "$CREATED_LIST" 2>/dev/null || echo "$rel" >> "$CREATED_LIST"
  fi
}

# ---------------------------------------------------------------- packages
APT_PKGS=(
  git curl wget unzip build-essential python3-venv fontconfig
  zsh zsh-autosuggestions zsh-syntax-highlighting
  eza bat fd-find ripgrep fzf zoxide btop fastfetch git-delta lazygit starship
  tealdeer gdu duf jq pipx
  ghostty fonts-inter papirus-icon-theme gnome-shell-extension-manager gnome-tweaks
)

install_packages() {
  title "Installing tools"
  need_sudo
  sudo apt-get update -qq || warn "apt update reported problems (continuing)"
  local have_pkgs=() missing=() p
  for p in "${APT_PKGS[@]}"; do
    if apt_has "$p"; then have_pkgs+=("$p"); else missing+=("$p"); fi
  done
  info "Installing ${#have_pkgs[@]} packages from Ubuntu…"
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${have_pkgs[@]}" || return 1

  mkdir -p "$HOME/.local/bin"
  # Ubuntu renames two tools; give them their normal names.
  have batcat && [[ ! -e $HOME/.local/bin/bat ]] && ln -s "$(command -v batcat)" "$HOME/.local/bin/bat"
  have fdfind && [[ ! -e $HOME/.local/bin/fd ]] && ln -s "$(command -v fdfind)" "$HOME/.local/bin/fd"
  export PATH="$HOME/.local/bin:$PATH"

  for p in "${missing[@]}"; do
    have "$p" && continue
    case $p in
      starship) info "Installing starship (official installer)…"
        run_installer https://starship.rs/install.sh -y -b "$HOME/.local/bin" >/dev/null ;;
      ghostty)  info "Installing Ghostty (snap)…"; have snap && sudo snap install ghostty --classic ;;
      lazygit)  install_lazygit_release ;;
      fastfetch) info "Installing fastfetch (GitHub release)…"
        local d; d=$(tmpdir)
        fetch "https://github.com/fastfetch-cli/fastfetch/releases/latest/download/fastfetch-linux-$(dpkg --print-architecture).deb" "$d/ff.deb" \
          && sudo apt-get install -y -qq "$d/ff.deb" ;;
    esac
  done
  have tldr && (tldr --update >/dev/null 2>&1 &)
  local notfound=()
  for p in starship ghostty lazygit fastfetch eza zoxide btop delta fzf rg; do have "$p" || notfound+=("$p"); done
  if (( ${#notfound[@]} )); then
    warn "Couldn't install: ${notfound[*]} (check your internet and run option 3 again)"
    return 1
  fi
  ok "Command-line tools installed"
}

install_lazygit_release() {
  info "Installing lazygit (GitHub release)…"
  local v arch d
  v=$(curl -fsSL https://api.github.com/repos/jesseduffield/lazygit/releases/latest | grep -Po '"tag_name": *"v\K[^"]*') || return 1
  arch=$(uname -m); [[ $arch == aarch64 ]] && arch=arm64
  d=$(tmpdir)
  fetch "https://github.com/jesseduffield/lazygit/releases/download/v${v}/lazygit_${v}_Linux_${arch}.tar.gz" "$d/lg.tgz" \
    && tar -xzf "$d/lg.tgz" -C "$d" lazygit && install -m 755 "$d/lazygit" "$HOME/.local/bin/lazygit"
}

install_gh() {
  title "GitHub CLI"
  if [[ -f /etc/apt/sources.list.d/github-cli.list ]] && have gh; then ok "Already set up"; return 0; fi
  need_sudo
  local key; key="$(tmpdir)/gh.gpg"
  fetch https://cli.github.com/packages/githubcli-archive-keyring.gpg "$key" && [[ -s $key ]] || return 1
  sudo mkdir -p -m 755 /etc/apt/keyrings
  sudo install -m 644 "$key" /etc/apt/keyrings/githubcli-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | sudo tee /etc/apt/sources.list.d/github-cli.list >/dev/null
  if ! { sudo apt-get update -qq && sudo apt-get install -y -qq gh; }; then
    sudo rm -f /etc/apt/sources.list.d/github-cli.list   # don't leave a broken source behind
    return 1
  fi
  ok "gh installed - run 'gh auth login' once to connect your GitHub account"
}

install_uv() {
  title "Python tooling (uv)"
  if have uv || [[ -x $HOME/.local/bin/uv ]]; then ok "uv already installed"; return 0; fi
  export UV_NO_MODIFY_PATH=1
  run_installer https://astral.sh/uv/install.sh >/dev/null && [[ -x $HOME/.local/bin/uv ]] || return 1
  ok "uv installed (fast replacement for pip, venv, poetry and pyenv)"
}

install_fonts() {
  title "Fonts"
  if fc-list 2>/dev/null | grep -qi "JetBrainsMono Nerd Font"; then ok "JetBrainsMono Nerd Font already installed"; return 0; fi
  local d; d=$(tmpdir)
  info "Downloading JetBrainsMono Nerd Font (coding font with icons)…"
  fetch "https://github.com/ryanoasis/nerd-fonts/releases/latest/download/JetBrainsMono.tar.xz" "$d/jbm.tar.xz" || return 1
  mkdir -p "$HOME/.local/share/fonts/JetBrainsMonoNerdFont"
  tar -xJf "$d/jbm.tar.xz" -C "$HOME/.local/share/fonts/JetBrainsMonoNerdFont" --wildcards '*.ttf'
  fc-cache -f >/dev/null
  ok "Font installed"
}

# ---------------------------------------------------------------- shell
make_from_bashrc() {
  local out="$HOME/.config/zsh/from-bashrc.zsh" src="$HOME/.bashrc" added
  keep_original "$out"
  {
    echo "# Lines carried over from your ~/.bashrc by linux-setup (nvm, pyenv, PATH changes…)."
    echo "# Edit freely. Bash-only lines were left out."
  } > "$out"
  [[ -f $src ]] || return 0
  if [[ -f /etc/skel/.bashrc ]]; then
    added=$(diff --changed-group-format='%>' --unchanged-group-format='' /etc/skel/.bashrc "$src")
  else
    added=$(cat "$src")
  fi
  printf '%s\n' "$added" \
    | sed '/# >>> linux-setup >>>/,/# <<< linux-setup <<</d' \
    | grep -vE '^[[:space:]]*(shopt|complete|bind|PS1=|PROMPT_COMMAND=|HISTCONTROL=|HISTSIZE=|HISTFILESIZE=)' \
    | grep -vE 'bash_completion|\.fzf\.bash|init bash|--bash' \
    | sed "s/'shell\.bash'/'shell.zsh'/g; s/shell\.bash hook/shell.zsh hook/g; s/init - bash/init - zsh/g; s/virtualenv-init - bash/virtualenv-init - zsh/g" >> "$out"
  if ! zsh -n "$out" 2>/dev/null; then
    sed -i 's/^/# /' "$out"
    sed -i '1i # NOTE: these lines had a syntax problem in zsh, so they are switched off. Fix and uncomment what you need.' "$out"
    warn "Some of your old .bashrc lines didn't work in zsh - saved (switched off) in ~/.config/zsh/from-bashrc.zsh"
  fi
  local n; n=$(grep -cvE '^[[:space:]]*(#|$)' "$out")
  ok "Carried over $n lines from your .bashrc (nvm, pyenv, PATH…)"
}

BASHRC_BLOCK='# >>> linux-setup >>>
[ -f ~/.config/shell/common.sh ] && . ~/.config/shell/common.sh
if [[ $- == *i* ]]; then
  command -v starship >/dev/null && eval "$(starship init bash)"
  if command -v fzf >/dev/null && fzf --bash >/dev/null 2>&1; then eval "$(fzf --bash)"; fi
  command -v zoxide >/dev/null && eval "$(zoxide init bash --cmd cd)"
fi
# <<< linux-setup <<<'

setup_shell() {
  title "Shell: zsh + starship prompt"
  mkdir -p "$HOME/.config/shell" "$HOME/.config/zsh"

  keep_original "$HOME/.config/shell/common.sh"
  sed "s#__LINUX_SETUP_DIR__#$SCRIPT_DIR#" "$SCRIPT_DIR/dotfiles/common.sh" > "$HOME/.config/shell/common.sh"

  make_from_bashrc

  keep_original "$HOME/.zshrc"
  if [[ -f $HOME/.zshrc ]] && ! grep -q "made by linux-setup" "$HOME/.zshrc"; then
    warn "You already had a ~/.zshrc - it's saved in $BACKUP_DIR"
  fi
  cp "$SCRIPT_DIR/dotfiles/zshrc" "$HOME/.zshrc"
  fetch "$RAW_CAT/zsh-syntax-highlighting/main/themes/catppuccin_mocha-zsh-syntax-highlighting.zsh" \
    "$HOME/.config/zsh/catppuccin_mocha-zsh-syntax-highlighting.zsh" || true

  keep_original "$HOME/.config/starship.toml"
  cp "$SCRIPT_DIR/dotfiles/starship.toml" "$HOME/.config/starship.toml"

  keep_original "$HOME/.bashrc"
  if [[ -f $HOME/.bashrc ]]; then
    sed -i '/# >>> linux-setup >>>/,/# <<< linux-setup <<</d' "$HOME/.bashrc"
  fi
  printf '\n%s\n' "$BASHRC_BLOCK" >> "$HOME/.bashrc"

  local zsh_path; zsh_path=$(command -v zsh)
  if [[ -n $zsh_path && $(getent passwd "$USER" | cut -d: -f7) != "$zsh_path" ]]; then
    need_sudo
    sudo chsh -s "$zsh_path" "$USER" && ok "zsh is now your default shell (takes effect after you log out and back in)"
  else
    ok "zsh is your default shell"
  fi
}

# ---------------------------------------------------------------- terminal
ghostty_desktop_id() {
  if [[ -f /usr/share/applications/com.mitchellh.ghostty.desktop ]]; then echo com.mitchellh.ghostty.desktop
  elif [[ -f /var/lib/snapd/desktop/applications/ghostty_ghostty.desktop ]]; then echo ghostty_ghostty.desktop
  fi
}

setup_terminal() {
  title "Terminal: Ghostty"
  if ! have ghostty; then warn "Ghostty isn't installed - skipped"; return 1; fi
  mkdir -p "$HOME/.config/ghostty"
  keep_original "$HOME/.config/ghostty/config"
  cp "$SCRIPT_DIR/dotfiles/ghostty.config" "$HOME/.config/ghostty/config"

  local id f; id=$(ghostty_desktop_id)
  if [[ -n $id ]]; then
    for f in "$HOME/.config/ubuntu-xdg-terminals.list" "$HOME/.config/xdg-terminals.list"; do
      keep_original "$f"
      { echo "$id"; [[ -f $f ]] && grep -vxF "$id" "$f"; } > "$f.new"; mv "$f.new" "$f"
    done
  fi
  # Older Ubuntu (24.04) uses the x-terminal-emulator setting for Ctrl+Alt+T
  if dpkg --compare-versions "$UBUNTU_VERSION" lt 25.04 2>/dev/null; then
    need_sudo
    sudo update-alternatives --install /usr/bin/x-terminal-emulator x-terminal-emulator "$(command -v ghostty)" 60 >/dev/null
    sudo update-alternatives --set x-terminal-emulator "$(command -v ghostty)" >/dev/null
  fi
  ok "Ghostty is your default terminal (Ctrl+Alt+T)"
}

# ---------------------------------------------------------------- CLI tool themes + git
setup_cli_themes() {
  title "Catppuccin for command-line tools"
  if have bat; then
    local bdir; bdir="$(bat --config-dir)/themes"; mkdir -p "$bdir"
    fetch "$RAW_CAT/bat/main/themes/Catppuccin%20Mocha.tmTheme" "$bdir/Catppuccin Mocha.tmTheme" && bat cache --build >/dev/null && ok "bat"
  fi
  if have btop; then
    mkdir -p "$HOME/.config/btop/themes"
    fetch "$RAW_CAT/btop/main/themes/catppuccin_mocha.theme" "$HOME/.config/btop/themes/catppuccin_mocha.theme"
    local conf="$HOME/.config/btop/btop.conf"; keep_original "$conf"
    if [[ -f $conf ]] && grep -q '^color_theme' "$conf"; then
      sed -i 's|^color_theme.*|color_theme = "catppuccin_mocha"|' "$conf"
    else
      echo 'color_theme = "catppuccin_mocha"' >> "$conf"
    fi
    ok "btop"
  fi
  if have lazygit; then
    mkdir -p "$HOME/.config/lazygit"
    if [[ ! -s $HOME/.config/lazygit/config.yml ]]; then
      keep_original "$HOME/.config/lazygit/config.yml"
      fetch "$RAW_CAT/lazygit/main/themes-mergable/mocha/mauve.yml" "$HOME/.config/lazygit/config.yml" && ok "lazygit"
    else info "lazygit already has your own config - left as is"; fi
  fi
  if have eza && [[ ! -e $HOME/.config/eza/theme.yml ]]; then
    mkdir -p "$HOME/.config/eza"; keep_original "$HOME/.config/eza/theme.yml"
    fetch "$RAW_CAT/eza/main/themes/mocha/catppuccin-mocha-mauve.yml" "$HOME/.config/eza/theme.yml" && ok "eza"
  fi

  # git: prettier diffs with delta + a few sensible defaults (your name/email are untouched)
  keep_original "$HOME/.gitconfig"
  if have delta; then
    mkdir -p "$HOME/.config/delta"
    fetch "$RAW_CAT/delta/main/catppuccin.gitconfig" "$HOME/.config/delta/catppuccin.gitconfig"
    git config --global --get-all include.path 2>/dev/null | grep -qF "delta/catppuccin.gitconfig" \
      || git config --global --add include.path "~/.config/delta/catppuccin.gitconfig"
    git config --global core.pager delta
    git config --global interactive.diffFilter "delta --color-only"
    git config --global delta.features catppuccin-mocha
    git config --global delta.navigate true
    git config --global delta.line-numbers true
  fi
  git config --global --get init.defaultBranch >/dev/null || git config --global init.defaultBranch main
  git config --global merge.conflictStyle zdiff3
  git config --global push.autoSetupRemote true
  git config --global fetch.prune true
  git config --global diff.colorMoved default
  ok "git (delta diffs, sensible defaults)"
  if [[ -z $(git config --global user.name) ]]; then
    warn "git doesn't know your name yet. Run:  git config --global user.name \"Your Name\"  and  git config --global user.email you@example.com"
  fi
}

# ---------------------------------------------------------------- editors
setup_vscode() {
  title "VS Code"
  if ! have code; then warn "VS Code not found - skipped"; return 0; fi
  local ext
  for ext in Catppuccin.catppuccin-vsc Catppuccin.catppuccin-vsc-icons usernamehw.errorlens esbenp.prettier-vscode; do
    code --install-extension "$ext" >/dev/null 2>&1 && dim "extension: $ext"
  done
  local s="$HOME/.config/Code/User/settings.json"
  keep_original "$s"
  python3 "$SCRIPT_DIR/lib/jsonmerge.py" "$s" "$SCRIPT_DIR/dotfiles/vscode-settings.json"
  case $? in
    0) ok "Theme, icons, font and nicer defaults applied (your other settings kept)" ;;
    2) warn "Couldn't read your VS Code settings.json - left it untouched. Pick 'Catppuccin Mocha' in Ctrl+K Ctrl+T." ;;
    *) return 1 ;;
  esac
}

setup_zed() {
  title "Zed"
  if ! have zed && [[ ! -x $HOME/.local/bin/zed ]]; then
    info "Installing Zed…"
    run_installer https://zed.dev/install.sh >/dev/null && [[ -x $HOME/.local/bin/zed ]] || return 1
  fi
  local s="$HOME/.config/zed/settings.json"
  keep_original "$s"
  python3 "$SCRIPT_DIR/lib/jsonmerge.py" "$s" "$SCRIPT_DIR/dotfiles/zed-settings.json"
  case $? in
    0) ok "Zed ready - it downloads the Catppuccin theme on first launch" ;;
    2) warn "Couldn't read your Zed settings.json - left it untouched" ;;
    *) return 1 ;;
  esac
}

# ---------------------------------------------------------------- GNOME look
setup_gnome() {
  title "Desktop look: Catppuccin Mocha"
  if ! gnome_session; then warn "Run this from your desktop session (not over SSH) to change the look - skipped"; return 1; fi
  local d; d=$(tmpdir)
  dconf dump / > "$STATE_DIR/gnome-settings-$RUN_ID.dconf" 2>/dev/null || true

  local I=org.gnome.desktop.interface
  gset_keep $I color-scheme "'prefer-dark'"
  gset_keep $I accent-color "'purple'"
  [[ -d /usr/share/themes/Yaru-purple-dark ]] && gset_keep $I gtk-theme "'Yaru-purple-dark'"
  gset_keep $I monospace-font-name "'JetBrainsMono Nerd Font 11'"
  gset_keep $I clock-show-weekday true
  gset_keep $I show-battery-percentage true
  gset_keep org.gnome.mutter center-new-windows true
  ok "Dark mode + purple accent"

  # Icons: Papirus with Catppuccin mauve folders
  if [[ -d /usr/share/icons/Papirus-Dark ]]; then
    need_sudo
    if git clone -q --depth 1 https://github.com/catppuccin/papirus-folders.git "$d/pf" \
       && fetch https://raw.githubusercontent.com/PapirusDevelopmentTeam/papirus-folders/master/papirus-folders "$d/papirus-folders"; then
      sudo cp -r "$d/pf/src/"* /usr/share/icons/Papirus/
      chmod +x "$d/papirus-folders"
      "$d/papirus-folders" -C cat-mocha-mauve --theme Papirus-Dark >/dev/null 2>&1 || warn "Folder colors not applied"
    fi
    gset_keep $I icon-theme "'Papirus-Dark'"
    ok "Papirus icons with Catppuccin folders"
  fi

  # Cursor
  if fetch https://github.com/catppuccin/cursors/releases/latest/download/catppuccin-mocha-dark-cursors.zip "$d/cur.zip"; then
    mkdir -p "$HOME/.local/share/icons"
    unzip -qo "$d/cur.zip" -d "$HOME/.local/share/icons"
    gset_keep $I cursor-theme "'catppuccin-mocha-dark-cursors'"
    ok "Catppuccin cursor"
  fi

  # Wallpaper
  local wp="$HOME/.local/share/backgrounds/catppuccin-mocha.png"
  mkdir -p "$(dirname "$wp")"; cp "$SCRIPT_DIR/assets/wallpaper-catppuccin-mocha.png" "$wp"
  gset_keep org.gnome.desktop.background picture-uri "'file://$wp'"
  gset_keep org.gnome.desktop.background picture-uri-dark "'file://$wp'"
  gset_keep org.gnome.desktop.background picture-options "'zoom'"
  gset_keep org.gnome.desktop.screensaver picture-uri "'file://$wp'"
  ok "Wallpaper"

  # Ubuntu Dock: floating, bottom, auto-hide, cleaner
  local K=org.gnome.shell.extensions.dash-to-dock
  gset_keep $K dock-position "'BOTTOM'"
  gset_keep $K extend-height false
  gset_keep $K dock-fixed false
  gset_keep $K autohide true
  gset_keep $K intellihide true
  gset_keep $K dash-max-icon-size 44
  gset_keep $K show-mounts false
  gset_keep $K show-trash false
  gset_keep $K transparency-mode "'FIXED'"
  gset_keep $K background-opacity 0.6
  gset_keep $K running-indicator-style "'DOTS'"
  gset_keep $K click-action "'minimize-or-previews'"
  ok "Dock: bottom, floating, hides when a window touches it"

  # Extensions: blur, clipboard history, keep-awake
  if have pipx; then
    pipx install --system-site-packages gnome-extensions-cli >/dev/null 2>&1 || pipx upgrade gnome-extensions-cli >/dev/null 2>&1
    local gext="$HOME/.local/bin/gext" e
    if [[ -x $gext ]]; then
      gset_keep org.gnome.shell disable-user-extensions false
      local got=0
      for e in blur-my-shell@aunetx clipboard-indicator@tudmotu.com caffeine@patapon.info; do
        if "$gext" -F install "$e" >/dev/null 2>&1; then "$gext" -F enable "$e" >/dev/null 2>&1; dim "extension: $e"; got=1
        else warn "Couldn't install $e - you can add it later from the Extension Manager app"; fi
      done
      (( got )) && ok "Extensions installed (they switch on after you log out and back in)"
    fi
  fi
}

setup_main() {
  title "Set up: dev tools + Catppuccin Mocha look"
  cat <<EOF
  This will:
    • install modern tools: Ghostty, zsh, starship, eza, bat, fzf, ripgrep, zoxide,
      lazygit, btop, fastfetch, delta, gh (GitHub), uv (Python)
    • install JetBrainsMono Nerd Font and theme everything Catppuccin Mocha
    • set up VS Code and Zed with the theme, font and good defaults
    • give GNOME dark mode, purple accent, Papirus icons, new cursor, wallpaper,
      a floating dock, and 3 extensions (blur, clipboard history, keep-awake)
  Your old files are backed up and "Undo" can put your old look back.
EOF
  ask "Start?" y || return 0
  need_sudo
  step "Install tools" install_packages
  step "GitHub CLI" install_gh
  step "uv" install_uv
  step "Fonts" install_fonts
  step "Shell" setup_shell
  step "Terminal" setup_terminal
  step "CLI themes" setup_cli_themes
  step "VS Code" setup_vscode
  step "Zed" setup_zed
  step "Desktop look" setup_gnome
  [[ -n $TMPD ]] && rm -rf "$TMPD"

  title "All done"
  if (( ${#FAILED_STEPS[@]} )); then warn "Steps that need another look: ${FAILED_STEPS[*]} (run option 3 again later - it's safe to repeat)"; fi
  cat <<EOF
  ${C_BOLD}Last step: log out and log back in${C_RESET} (top-right menu → Power → Log Out).
  That switches on zsh, the extensions and the cursor everywhere.

  Then press ${C_MAUVE}Ctrl+Alt+T${C_RESET} for your new terminal and type ${C_MAUVE}tips${C_RESET} to see what's new.
  Backups of anything changed: $BACKUP_DIR
EOF
}

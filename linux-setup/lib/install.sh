# shellcheck shell=bash
# Dev tools + Catppuccin Mocha look for Ubuntu GNOME.

RAW_CAT="https://raw.githubusercontent.com/catppuccin"
TMPD=""
tmpdir() { [[ -n $TMPD ]] || { TMPD=$(mktemp -d); chmod 700 "$TMPD"; }; echo "$TMPD"; }

fetch() {
  local url=$1 out=$2
  case $url in
    https://*) ;;
    *) err "Refusing a non-HTTPS download: $url"; return 2 ;;
  esac
  curl --proto '=https' --tlsv1.2 -fsSL --retry 3 --retry-all-errors --connect-timeout 15 --max-time 180 "$url" -o "$out"
  chmod 600 "$out" 2>/dev/null || true
}

# Download an installer script first, then run it (so a failed download never "succeeds").
run_installer() {
  local url=$1; shift
  local f; f="$(tmpdir)/installer-$RANDOM.sh"
  fetch "$url" "$f" && [[ -s $f ]] && bash -n "$f" && /bin/bash "$f" "$@"
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
  # Prefer a normal Python-package installation over executing a downloaded installer.
  if have pipx; then
    PIPX_HOME="${PIPX_HOME:-$HOME/.local/share/pipx}" PIPX_BIN_DIR="$HOME/.local/bin" pipx install uv >/dev/null || return 1
  else
    python3 -m pip install --user uv >/dev/null || return 1
  fi
  [[ -x $HOME/.local/bin/uv ]] || have uv || return 1
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

# ---------------------------------------------------------------- pc control center
install_pc() {
  title "pc - your computer's control center"
  local src="$SCRIPT_DIR/pc"
  if [[ ! -f $src/pyproject.toml ]]; then warn "The pc folder is missing next to setup.sh - skipped"; return 1; fi
  export PATH="$HOME/.local/bin:$PATH"
  if have uv; then
    info "Installing pc (with its own private Python, so it never clashes with your projects)…"
    uv tool install --force --reinstall --python-preference managed "$src" >/dev/null 2>&1 \
      || uv tool install --force "$src" >/dev/null || return 1
  else
    info "Installing pc into ~/.local/share/pc…"
    python3 -m venv "$HOME/.local/share/pc/venv" \
      && "$HOME/.local/share/pc/venv/bin/pip" install -q --upgrade "$src" \
      && ln -sf "$HOME/.local/share/pc/venv/bin/pc" "$HOME/.local/bin/pc" || return 1
  fi
  local pcbin; pcbin=$(command -v pc || echo "$HOME/.local/bin/pc")
  [[ -x $pcbin ]] || return 1

  # Remember where these scripts live (pc's Maintenance tab can re-run them)
  mkdir -p "$HOME/.config/pc"
  python3 - "$SCRIPT_DIR" <<'PY'
import json, os, sys
p = os.path.expanduser("~/.config/pc/config.json")
try:
    d = json.load(open(p))
except Exception:
    d = {}
d["setup_dir"] = sys.argv[1]
json.dump(d, open(p, "w"), indent=2)
PY

  ok "pc installed - type ${C_MAUVE}pc${C_RESET} in a terminal for the terminal version"

  # Tab completion for pc (zsh + bash); regenerated from pc itself so it always matches the installed version
  mkdir -p "$HOME/.local/share/zsh/site-functions" "$HOME/.local/share/bash-completion/completions"
  if "$pcbin" completions zsh > "$HOME/.local/share/zsh/site-functions/_pc" 2>/dev/null \
     && "$pcbin" completions bash > "$HOME/.local/share/bash-completion/completions/pc" 2>/dev/null; then
    rm -f "$HOME/.cache/zcompdump"
    # an existing ~/.zshrc (e.g. from an earlier run) needs the user completion folder before compinit
    if [[ -f $HOME/.zshrc ]] && ! grep -q "zsh/site-functions" "$HOME/.zshrc"; then
      if grep -q "compinit" "$HOME/.zshrc"; then
        backup "$HOME/.zshrc"
        python3 - "$HOME/.zshrc" <<'PY' || true
import sys
p = sys.argv[1]
lines = open(p).read().split("\n")
i = next(n for n, l in enumerate(lines) if "compinit" in l)
lines.insert(i, "fpath=(~/.local/share/zsh/site-functions $fpath)   # pc and other user-installed completions")
open(p, "w").write("\n".join(lines))
PY
      fi
    fi
    dim "Tab completion for pc installed (zsh and bash)"
  fi

  install_pc_app || warn "The desktop app didn't install - try again with: bash setup.sh app"

  if ask "Turn on the weekly automatic checkup? (safe cleanup + a notification if something needs you)" y; then
    if "$pcbin" maintain --on >/dev/null 2>&1; then ok "Weekly checkup on (Sundays 11:00)"
    else warn "Couldn't turn on the weekly checkup - try it later in pc → Maintenance"; fi
  fi
  if ask "Turn on background alerts? (a notification when a disk is almost full, security updates wait, a service keeps crashing…)" y; then
    if "$pcbin" watch --on >/dev/null 2>&1; then ok "Background alerts on (checks every 30 minutes, each alert at most once a day)"
    else warn "Couldn't turn on alerts - try it later in the app: Preferences → Alerts"; fi
  fi
}

# ---------------------------------------------------------------- desktop app
APP_ID="io.github.infinite4evr.PcCommandCenter"
APP_DIR="$HOME/.local/share/pc-command-center"
APP_DEPS=(python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 python3-psutil)

install_pc_app() {
  title "PC Command Center - the desktop app"
  local src="$SCRIPT_DIR/pc/src/pcctl"
  if [[ ! -d $src/gui ]]; then warn "The pc/src/pcctl folder is missing next to setup.sh - skipped"; return 1; fi

  # Read and show the version we are about to install.  This also protects against
  # accidentally running setup.sh from an older extracted folder.
  local source_version
  source_version=$(python3 - "$src/__init__.py" <<'PYVER'
import re, sys
try:
    text = open(sys.argv[1], encoding="utf-8").read()
except OSError:
    raise SystemExit(1)
m = re.search(r'__version__\s*=\s*["\']([^"\']+)', text)
if m:
    print(m.group(1))
PYVER
  ) || return 1
  if [[ -z $source_version ]]; then warn "Couldn't determine the PC Command Center source version"; return 1; fi
  info "Source version: $source_version"

  # Replacing files underneath a running Python process does not replace the code
  # already loaded in memory.  A subsequent dock click can reactivate that old
  # single-instance process, making About appear to show an unsuccessful update.
  local gui_was_running=0
  if ps -u "$(id -u)" -o args= 2>/dev/null \
      | grep -E '[p]ython3(\s+[^ ]+)*\s+-m\s+pcctl\.gui([[:space:]]|$)' \
      | grep -vq -- '--search-provider'; then
    gui_was_running=1
    warn "PC Command Center is currently running. The new files will install, but that window keeps its old in-memory version until you fully quit it (Ctrl+Q) and reopen it."
  fi

  # GTK 4 + libadwaita for Ubuntu's own Python (native look and the normal password popup)
  local missing=() p
  for p in "${APP_DEPS[@]}"; do dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p"); done
  if (( ${#missing[@]} )); then
    info "Installing ${missing[*]}…"
    need_sudo
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${missing[@]}" || return 1
  fi
  if ! /usr/bin/python3 -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1"); from gi.repository import Gtk, Adw; import psutil' 2>/dev/null; then
    warn "GTK 4 / libadwaita for Python isn't working on this system"; return 1
  fi

  # A private copy of the code, so the app keeps working even if you move the linux-setup folder
  info "Copying the app to ${APP_DIR/#$HOME/\~}…"
  rm -rf "$APP_DIR.new" && mkdir -p "$APP_DIR.new" || return 1
  cp -r "$src" "$APP_DIR.new/pcctl" || return 1
  find "$APP_DIR.new" -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null
  rm -rf "$APP_DIR" && mv "$APP_DIR.new" "$APP_DIR" || return 1

  mkdir -p "$HOME/.local/bin"
  cat > "$HOME/.local/bin/pc-gui" <<EOF
#!/bin/sh
# PC Command Center (desktop app). Runs on Ubuntu's Python so GTK 4 / libadwaita come from apt.
export PYTHONPATH="$APP_DIR\${PYTHONPATH:+:\$PYTHONPATH}"
exec /usr/bin/python3 -m pcctl.gui "\$@"
EOF
  chmod +x "$HOME/.local/bin/pc-gui"

  # Icon + app-grid entry (right-click the icon for shortcuts straight to a page)
  mkdir -p "$HOME/.local/share/icons/hicolor/scalable/apps" "$HOME/.local/share/applications"
  cp "$src/gui/data/$APP_ID.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/$APP_ID.svg"
  keep_original "$HOME/.local/share/applications/$APP_ID.desktop"
  cat > "$HOME/.local/share/applications/$APP_ID.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=PC Command Center
GenericName=System Manager
Comment=Monitor, clean, update, secure and tune your computer
Exec=$HOME/.local/bin/pc-gui
Icon=$APP_ID
Terminal=false
StartupNotify=true
Categories=System;Monitor;Utility;GTK;
Keywords=cleanup;junk;updates;processes;task manager;storage;disk;network;services;startup;security;privacy;tweaks;troubleshoot;fix;report;battery;
Actions=cleanup;updates;processes;storage;fix;slow;

[Desktop Action cleanup]
Name=Clean up
Exec=$HOME/.local/bin/pc-gui --page cleanup

[Desktop Action updates]
Name=Updates
Exec=$HOME/.local/bin/pc-gui --page updates

[Desktop Action processes]
Name=Processes
Exec=$HOME/.local/bin/pc-gui --page processes

[Desktop Action storage]
Name=Storage
Exec=$HOME/.local/bin/pc-gui --page storage

[Desktop Action fix]
Name=Fix a problem
Exec=$HOME/.local/bin/pc-gui --page maintenance

[Desktop Action slow]
Name=Why is my PC slow?
Exec=$HOME/.local/bin/pc-gui --action maintenance:fix-slow
EOF
  # The old "PC Control Center" terminal launcher is replaced by this app (pc still works in any terminal)
  if [[ -f $HOME/.local/share/applications/pc-control-center.desktop ]]; then
    keep_original "$HOME/.local/share/applications/pc-control-center.desktop"
    rm -f "$HOME/.local/share/applications/pc-control-center.desktop"
  fi
  update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
  gtk-update-icon-cache -q -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

  # Friendlier password popup ("PC Command Center needs…", remembered for a few minutes) + GNOME Activities search
  local data="$SCRIPT_DIR/pc/data"
  mkdir -p "$HOME/.local/share/dbus-1/services" "$HOME/.cache/pc"
  printf '[D-BUS Service]\nName=%s.SearchProvider\nExec=%s --search-provider\n' "$APP_ID" "$HOME/.local/bin/pc-gui" \
    > "$HOME/.local/share/dbus-1/services/$APP_ID.SearchProvider.service"
  printf '[Shell Search Provider]\nDesktopId=%s.desktop\nBusName=%s.SearchProvider\nObjectPath=/io/github/infinite4evr/PcCommandCenter/SearchProvider\nVersion=2\n' \
    "$APP_ID" "$APP_ID" > "$HOME/.cache/pc/search-provider.ini"
  if [[ -f $data/pc-admin && -f $data/$APP_ID.policy ]] && need_sudo; then
    sudo install -D -m 755 "$data/pc-admin" /usr/local/libexec/pc-command-center/pc-admin \
      && sudo install -D -m 644 "$data/$APP_ID.policy" "/usr/share/polkit-1/actions/$APP_ID.policy" \
      && dim "Password popup set up (names the app, remembers the password for a few minutes)"
    sudo install -D -m 644 "$HOME/.cache/pc/search-provider.ini" "/usr/local/share/gnome-shell/search-providers/$APP_ID.search-provider.ini" \
      && dim "GNOME search: type “clean”, “battery” or “fix sound” in Activities (after you log out and back in)"
  fi

  # Remember where these scripts live (the app's Maintenance page can re-run them)
  mkdir -p "$HOME/.config/pc"
  python3 - "$SCRIPT_DIR" <<'PY'
import json, os, sys
p = os.path.expanduser("~/.config/pc/config.json")
try:
    d = json.load(open(p))
except Exception:
    d = {}
d["setup_dir"] = sys.argv[1]
json.dump(d, open(p, "w"), indent=2)
PY

  # Verify the private GUI copy really is the same version as this source tree.
  local installed_version
  installed_version=$(python3 - "$APP_DIR/pcctl/__init__.py" <<'PYVER'
import re, sys
try:
    text = open(sys.argv[1], encoding="utf-8").read()
except OSError:
    raise SystemExit(1)
m = re.search(r'__version__\s*=\s*["\']([^"\']+)', text)
if m:
    print(m.group(1))
PYVER
  ) || return 1
  if [[ $installed_version != "$source_version" ]]; then
    warn "Version verification failed: source is $source_version but installed GUI files report ${installed_version:-unknown}."
    return 1
  fi
  dim "Verified installed GUI files: v$installed_version"

  # Pin it to the dock (keeps whatever is already there)
  local favs; favs=$(gsettings get org.gnome.shell favorite-apps 2>/dev/null || echo "")
  if [[ $favs == "["*"]" && $favs != *"$APP_ID"* ]]; then
    if [[ $favs == "@as []" || $favs == "[]" ]]; then gset_keep org.gnome.shell favorite-apps "['$APP_ID.desktop']"
    else gset_keep org.gnome.shell favorite-apps "${favs%]}, '$APP_ID.desktop']"; fi
  fi
  ok "PC Command Center v$installed_version installed - it's in your dock and app grid (or run ${C_MAUVE}pc-gui${C_RESET})"
  if (( gui_was_running )); then
    warn "Important: quit the old PC Command Center process with Ctrl+Q, then reopen it. Until then About can still show the previous version because the old Python process is still in memory."
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
    • install ${C_MAUVE}pc${C_RESET}, a control center for your whole computer that runs in the terminal
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
  step "pc control center" install_pc
  [[ -n $TMPD ]] && rm -rf "$TMPD"

  title "All done"
  if (( ${#FAILED_STEPS[@]} )); then warn "Steps that need another look: ${FAILED_STEPS[*]} (run option 3 again later - it's safe to repeat)"; fi
  cat <<EOF
  ${C_BOLD}Last step: log out and log back in${C_RESET} (top-right menu → Power → Log Out).
  That switches on zsh, the extensions and the cursor everywhere.

  Then press ${C_MAUVE}Ctrl+Alt+T${C_RESET} for your new terminal and type ${C_MAUVE}pc${C_RESET} to open your control center
  (or ${C_MAUVE}tips${C_RESET} for a cheat sheet of the new commands).
  Backups of anything changed: $BACKUP_DIR
EOF
}

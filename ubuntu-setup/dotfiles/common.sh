# ~/.config/shell/common.sh - shared by zsh and bash (made by linux-setup).
# Safe to edit. Your own extras are better placed in ~/.zshrc.local so updates never touch them.

LINUX_SETUP_DIR="__LINUX_SETUP_DIR__"

case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$HOME/.local/bin:$PATH" ;; esac

export EDITOR="${EDITOR:-nano}"
export BAT_THEME="Catppuccin Mocha"

# fzf (fuzzy finder): Catppuccin colors, rounded border, preview files with bat
export FZF_DEFAULT_OPTS=" \
--height=60% --layout=reverse --border=rounded --info=inline-right \
--color=bg+:#313244,bg:-1,spinner:#f5e0dc,hl:#f38ba8 \
--color=fg:#cdd6f4,header:#f38ba8,info:#cba6f7,pointer:#f5e0dc \
--color=marker:#b4befe,fg+:#cdd6f4,prompt:#cba6f7,hl+:#f38ba8 \
--color=selected-bg:#45475a,border:#6c7086,label:#cdd6f4"
if command -v fd >/dev/null 2>&1; then
  export FZF_DEFAULT_COMMAND='fd --type f --hidden --exclude .git --exclude node_modules'
  export FZF_CTRL_T_COMMAND="$FZF_DEFAULT_COMMAND"
fi
command -v bat >/dev/null 2>&1 && export FZF_CTRL_T_OPTS="--preview 'bat --color=always --style=numbers --line-range=:300 {}'"

# Colorful man pages
if command -v bat >/dev/null 2>&1; then
  export MANPAGER="sh -c 'col -bx | bat -l man -p'"
  export MANROFFOPT="-c"
fi

# ---------- Friendly shortcuts ----------
if command -v eza >/dev/null 2>&1; then
  alias ls='eza --icons=auto --group-directories-first'
  alias ll='eza -lh --icons=auto --group-directories-first --git --time-style=relative'
  alias la='eza -lah --icons=auto --group-directories-first --git --time-style=relative'
  alias lt='eza --tree --level=2 --icons=auto --git-ignore'
fi
command -v bat >/dev/null 2>&1 && alias cat='bat --paging=never --style=plain'
command -v lazygit >/dev/null 2>&1 && alias lg='lazygit'
alias ..='cd ..'
alias ...='cd ../..'
alias ports='ss -tulpn'
alias myip='curl -s https://ifconfig.me; echo'
alias cleanup='bash "$LINUX_SETUP_DIR/setup.sh" clean'
alias scan='bash "$LINUX_SETUP_DIR/setup.sh" scan'
alias tips='bash "$LINUX_SETUP_DIR/setup.sh" tips'
if command -v pc >/dev/null 2>&1; then
  alias cleanup='pc clean'
  alias scan='pc doctor'
fi

# make a folder and jump into it
mkcd() { mkdir -p -- "$1" && cd -- "$1" || return; }

# update everything: apt, snap, flatpak
update() {
  sudo apt update && sudo apt full-upgrade -y && sudo apt autoremove --purge -y
  command -v snap >/dev/null 2>&1 && sudo snap refresh
  command -v flatpak >/dev/null 2>&1 && flatpak update -y
  return 0
}

# extract any archive: x file.zip / x file.tar.gz
x() {
  case "$1" in
    *.tar.gz|*.tgz) tar xzf "$1" ;;
    *.tar.xz)       tar xJf "$1" ;;
    *.tar.bz2)      tar xjf "$1" ;;
    *.tar)          tar xf "$1" ;;
    *.zip)          unzip -q "$1" ;;
    *.gz)           gunzip "$1" ;;
    *.7z)           7z x "$1" ;;
    *) echo "Don't know how to extract $1" ;;
  esac
}

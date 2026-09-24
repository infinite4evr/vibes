# shellcheck shell=bash
# Cheat sheet printed by the `tips` command.

tips_main() {
  local M=$C_MAUVE R=$C_RESET D=$C_DIM
  cat <<EOF

${C_BOLD}${M}Your new setup - cheat sheet${R}

${C_BOLD}Your control center${R}
  ${M}PC Command Center${R} the desktop app (dock / app grid, or ${M}pc-gui${R}): dashboard, cleanup,
                   updates, apps, startup, processes, storage, network, power, logs,
                   services, security, privacy, tweaks, developer, maintenance
  ${M}pc${R}               the same in your terminal (${M}pc gui${R} opens the desktop app)
  ${M}pc status${R}        quick summary          ${M}pc doctor${R}      health check with fixes
  ${M}pc clean${R}         safe cleanup           ${M}pc update${R}      update everything
  ${M}pc ports${R}         what's on which port   ${M}pc kill-port 3000${R}
  ${M}pc repos${R}         all your git projects  ${M}pc big ~/${R}      biggest folders
  ${M}pc --help${R}        everything else

${C_BOLD}Moving around${R}
  ${M}cd proj${R}          jumps to any folder you've visited that matches "proj"
  ${M}cdi${R}              pick a recent folder from a list
  ${M}..  ...${R}          up one / two folders
  ${M}mkcd name${R}        make a folder and go into it

${C_BOLD}Looking at files${R}
  ${M}ls  ll  la${R}       list files with icons (ll = details, la = incl. hidden)
  ${M}lt${R}               folder tree
  ${M}cat file${R}         shows files with colors (bat)
  ${M}rg "text"${R}        search inside all files, super fast (ripgrep)
  ${M}fd name${R}          find files by name

${C_BOLD}Keyboard magic in the terminal${R}
  ${M}Ctrl+R${R}           search everything you've typed before
  ${M}Ctrl+T${R}           fuzzy-pick a file and paste its path
  ${M}→ (right arrow)${R}  accept the grey suggestion
  ${M}Tab${R}              menu of completions (arrow keys to pick)
  ${M}Up arrow${R}         previous commands starting with what you typed

${C_BOLD}Coding${R}
  ${M}lg${R}               lazygit - see changes, stage, commit, push with single keys
  ${M}gh auth login${R}    connect GitHub once; then ${M}gh repo clone${R}, ${M}gh pr create${R}
  ${M}uv init / uv add${R} start a Python project / add a package (replaces pip + venv)
  ${M}code .${R} / ${M}zed .${R}  open this folder in VS Code / Zed
  ${M}git diff${R}         shows colorful diffs with line numbers (delta)

${C_BOLD}System${R}
  ${M}update${R}           update everything (apt + snap + flatpak)
  ${M}btop${R}             what's using CPU/RAM (q to quit)
  ${M}gdu ~${R}            what's using disk space, browse with arrows
  ${M}duf${R}              disks at a glance
  ${M}fastfetch${R}        system info with the Ubuntu logo
  ${M}tldr cmd${R}         short examples for any command (e.g. tldr tar)
  ${M}ports${R}            which apps are listening on which ports
  ${M}scan / cleanup${R}   check for junk / clean it (asks before deleting)

${C_BOLD}Ghostty terminal${R}
  ${M}Ctrl+Shift+T${R} new tab   ${M}Ctrl+Shift+O${R} split right   ${M}Ctrl+Shift+E${R} split down
  ${M}Ctrl+Alt+Arrows${R} move between splits   ${M}Ctrl+ / Ctrl-${R} bigger/smaller text

${C_BOLD}Desktop${R}
  ${M}Super${R} (Windows key)  search apps       ${M}Super+V${R} notifications
  ${M}Clipboard icon${R} (top bar)  history of everything you copied
  ${M}Coffee cup${R} (top bar)      keep screen awake
  ${M}Extension Manager${R} app     browse more GNOME extensions

${D}Config files: ~/.zshrc  ~/.config/starship.toml  ~/.config/ghostty/config
Your own additions go in ~/.zshrc.local${R}

EOF
}

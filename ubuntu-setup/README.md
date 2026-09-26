# ubuntu-setup

Cleans junk off Ubuntu and sets up a dev environment themed in Catppuccin Mocha. It also installs [PC Command Center](../pc-command-center/README.md), the desktop and terminal app for managing the whole computer, from the `pc-command-center/` folder next to this one.

## Run it

Open a terminal (Ctrl+Alt+T) and paste:

```bash
bash ~/Documents/Vibes/ubuntu-setup/setup.sh
```

Then pick **4** (Do all 3) the first time. It asks before deleting anything, and it asks for your login password when it needs admin rights.

When it's finished, **log out and log back in**, then type `tips` in the terminal.

| Option | What it does |
|---|---|
| 1 Scan | Shows what's taking space. Changes nothing. |
| 2 Clean up | apt/snap/flatpak leftovers, logs, caches, broken shortcuts, Waydroid, ~/.android, old Node/Python versions (you choose which) |
| 3 Set up | Ghostty, zsh + starship, modern CLI tools, gh, uv, Nerd Font, VS Code + Zed theming, GNOME dark + purple accent, Papirus icons, cursor, wallpaper, dock, 3 extensions |
| 4 Do all 3 | Scan, clean up and set up in one go |
| 5 Tips | Shows the cheat sheet of the new tools (the same as typing `tips`) |
| 6 Undo | Puts back your old GNOME settings, config files and bash |
| 7 pc | Installs/updates **pc** (terminal) and **PC Command Center** (desktop app) |
| 8 App | Installs/updates just the desktop app |

Everything is safe to re-run. Backups go to `~/.local/state/linux-setup/` (the folder keeps its old name so Undo still finds backups made before the rename).

## Coming from `linux-setup`

This folder used to be `linux-setup/`, with the app inside it as `linux-setup/pc/`. After pulling, run this once:

```bash
bash ~/Documents/Vibes/ubuntu-setup/setup.sh pc
```

It reinstalls PC Command Center from its new folder, tells the app where the setup scripts live now, and points the `cleanup`, `scan` and `tips` aliases here.

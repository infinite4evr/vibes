# linux-setup

Cleans junk off Ubuntu and sets up a dev environment themed in Catppuccin Mocha.

## Run it

Open a terminal (Ctrl+Alt+T) and paste:

```bash
bash ~/Documents/Vibes/linux-setup/setup.sh
```

Then pick **4** (Do all 3) the first time. It asks before deleting anything, and it asks for your login password when it needs admin rights.

When it's finished, **log out and log back in**, then type `tips` in the terminal.

| Option | What it does |
|---|---|
| 1 Scan | Shows what's taking space. Changes nothing. |
| 2 Clean up | apt/snap/flatpak leftovers, logs, caches, broken shortcuts, Waydroid, ~/.android, old Node/Python versions (you choose which) |
| 3 Set up | Ghostty, zsh + starship, modern CLI tools, gh, uv, Nerd Font, VS Code + Zed theming, GNOME dark + purple accent, Papirus icons, cursor, wallpaper, dock, 3 extensions |
| 6 Undo | Puts back your old GNOME settings, config files and bash |

Everything is safe to re-run. Backups go to `~/.local/state/linux-setup/`.

## What never gets touched

Documents, Downloads, Pictures, Music, Videos, your projects, TeX Live, VirtualBox, browsers, and the Node version your pm2 bot runs on.

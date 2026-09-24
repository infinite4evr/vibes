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
| 7 pc | Installs/updates **pc** (terminal) and **PC Command Center** (desktop app) |
| 8 App | Installs/updates just the desktop app |

## PC Command Center - the desktop app

After setup, open **PC Command Center** from the dock or app grid (or run `pc-gui`). It's a native GNOME app (GTK 4 + libadwaita, Catppuccin Mocha) for the whole computer:

- **Dashboard**: health score, live CPU / memory / network / disk / temperature / battery, what needs attention (with Fix buttons), busiest apps
- **Cleanup**: ~40 kinds of junk in 5 groups (system, developer caches, apps & browsers, your files, privacy), tick exactly what goes, deep scan for old node_modules / build folders / venvs / old runtimes / old downloads / duplicates
- **Updates**: apt + Snap + Flatpak in one list (security first), update one or all, history, firmware, auto-updates, Ubuntu Pro, leftover packages, repair
- **Apps**: everything installed from every source, uninstall, search & install (with recommended apps), default apps
- **Startup**: login apps on/off, boot time and slowest services, optional boot services (Docker, databases, printing, Bluetooth…)
- **Processes**: grouped by app, end / force quit / pause / priority / details
- **Storage**: disks and drive health, folder explorer by size, big files, duplicate finder
- **Network**: live traffic, Wi-Fi, open ports (stop / allow in firewall), diagnostics, speed test
- **Power & hardware**: battery health and charge limit, power modes, temperatures, specs, restart into BIOS
- **Logs**, **Services** (and timers), **Security** (score, one-click fixes, firewall rules, SSH keys), **Privacy** (camera/mic in use, telemetry, history), **Tweaks** (dev-laptop tuning with undo, desktop switches, Caps Lock → Escape…), **Developer** (git projects, dev servers, pm2, containers, Node/Python versions, CLI toolbox), **Maintenance** (one-click tune-up, weekly checkup, settings backups, Timeshift, these setup scripts)

Every action shows the exact commands first; anything that needs admin rights asks for your password once with Ubuntu's normal popup.

## pc - the terminal version

Type `pc` in a terminal. It's a full-screen app for the whole computer: live overview + health check, processes, storage explorer, cleanup, updates, apps, startup apps, services, network & ports, dev projects / pm2 / containers, power & hardware, security checklist, logs, and maintenance (weekly auto-checkup, settings backups, snapshots). Quick commands: `pc status`, `pc doctor`, `pc clean`, `pc update`, `pc kill-port 3000`, `pc repos`, `pc --help`. Details in `pc/README.md`.

Everything is safe to re-run. Backups go to `~/.local/state/linux-setup/`.

## What never gets touched

Documents, Downloads, Pictures, Music, Videos, your projects, TeX Live, VirtualBox, browsers, and the Node version your pm2 bot runs on.

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

After setup, open **PC Command Center** from the dock or app grid (or run `pc-gui`). It's a native GNOME app (GTK 4 + libadwaita) for the whole computer, with a clean modern look that uses GNOME's accent colour (Catppuccin is one click away in Preferences) and switches with GNOME's light/dark setting:

- **Dashboard**: health score, live CPU / memory / GPU / network / disks / temperature / battery, and a one-click **Why is my PC slow?**
- **Cleanup**: ~45 kinds of junk, a never-clean list, the real space freed, a deep scan (old node_modules, build folders, venvs, duplicates, similar photos, empty folders)
- **Updates**: apt + Snap + Flatpak together, **undo an apt change**, PPAs and sources, old kernels, drivers, snapshots before updating
- **Apps**: install from a downloaded file, AppImages in the app grid, uninstall several at once, app permissions, unused apps
- **Startup**: login apps (with a delay), boot speed and boot chart, **boot menu (GRUB) settings**
- **Processes** (tree, disk use, efficiency mode), **Storage** (drives, health, treemap, file types, Trash, swap, speed test), **Network** (which app talks to whom, DNS switcher, VPN, saved Wi-Fi passwords, hotspot, devices nearby)
- **Power & hardware**: battery history graph, keep awake, shutdown/sleep timer, CPU speed and throttling, every device
- **Logs** (kernel messages, live follow, journal size), **Services** (memory per service, block, **keep a script running or on a schedule**, cron explained)
- **Security** (checklist, **secrets check** for leaked API keys, Docker-vs-firewall, SSH, virus scan, accounts), **Privacy** (dev-tool telemetry off in one switch, file indexing)
- **Tweaks** (extensions manager, Dock settings, Ctrl+Shift+Esc → Processes, Files and clock options, computer name, time zone), **Developer** (PATH doctor, Docker disk cleanup, GitHub connection, git identity, global packages, Python versions via uv)
- **Maintenance**: troubleshooters (Wi-Fi, sound, Bluetooth, apt, printer…), weekly checkup with a health graph, a **system report** to share, backups, Timeshift snapshots

Every action shows the exact commands first; anything that needs admin rights asks for your password once. The search bar at the top (**Ctrl+K**) finds any page, action or setting. Background alerts (disk full, security updates, failing services…) arrive as notifications even when the app is closed. See `pc/README.md` for the full list and `docs/FEATURE-AUDIT.md` for how it compares with other tools.

## pc - the terminal version

Type `pc` in a terminal. It's a full-screen app for the whole computer: live overview + health check, processes, storage explorer, cleanup, updates, apps, startup apps, services, network & ports, dev projects / pm2 / containers, power & hardware, security checklist, logs, and maintenance (weekly auto-checkup, settings backups, snapshots). Quick commands: `pc status`, `pc doctor`, `pc slow`, `pc fix`, `pc secrets`, `pc report`, `pc clean`, `pc update`, `pc kill-port 3000`, `pc awake 2h`, `pc --help` (Tab completes them). Details in `pc/README.md`.

Everything is safe to re-run. Backups go to `~/.local/state/linux-setup/`.

## What never gets touched

Documents, Downloads, Pictures, Music, Videos, your projects, TeX Live, VirtualBox, browsers, and the Node version your pm2 bot runs on.

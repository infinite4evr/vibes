# PC Command Center

A control center for your whole Ubuntu computer, in two forms that share one engine:

- **PC Command Center**, a native desktop app (GTK 4 + libadwaita, Catppuccin Mocha). Open it from the dock or app grid, or run `pc-gui`.
- **pc**, the same thing in the terminal. Type `pc`.

## The desktop app

| Page | What you can do |
|---|---|
| Dashboard | Health score, live CPU (per core) / memory / network / disks / temperature / battery, what needs attention with Fix buttons, busiest apps |
| Cleanup | ~40 kinds of junk in 5 groups: System (apt cache, unused packages, config leftovers, old snaps, journal, rotated logs, crash reports, temp files), Developer (pip/uv/npm/pnpm/yarn/bun, cargo/go, Gradle/Maven, Playwright/Puppeteer browsers, AI models, old VS Code extensions, editor caches, Docker/Podman), Apps & browsers (browser caches, Chrome's AI model, Slack/Discord/Spotify caches, thumbnails, snap/flatpak leftovers, TeX cache), Your files (Trash, old installers, broken shortcuts and symlinks, Waydroid leftovers) and Privacy (recent files, clipboard history). Tick whole groups or single items, see exactly what runs. **Deep scan** adds old `node_modules`, build folders, Rust `target`, virtualenvs, `__pycache__`, `git gc`, unused Node/Python versions, old downloads and duplicate files |
| Updates | apt + Snap + Flatpak in one list (security fixes first), update one or everything, apt history, firmware (fwupd), automatic security updates, Ubuntu Pro, leftover packages, extra software sources, repair broken packages, release upgrade |
| Apps | Everything installed from every source (apt, Snap, Flatpak, AppImage), open / details / files / uninstall, search & install from all stores, recommended apps, default apps (browser, editor, PDF, images, video…) |
| Startup | Login apps on/off, boot time breakdown and slowest services, optional services that start at boot (Docker, databases, web servers, printing, Bluetooth…) |
| Processes | Live list grouped by app, CPU/memory stats, end / force quit / pause / resume / priority, details (folder, ports, disk I/O, open files) |
| Storage | Disks and drive health (SMART), TRIM, folder explorer by size, big files, duplicate finder (byte-for-byte), move to Trash |
| Network | Live traffic graph, adapters, Wi-Fi (scan / connect / on-off), open ports (stop app, allow in firewall, open in browser), step-by-step internet diagnosis, speed test, DNS flush, restart networking |
| Power & hardware | Battery health, cycles and draw, charge limit (80/90/100%), power modes, temperatures and fans, full specs (copyable), lock / suspend / restart / restart into BIOS / power off |
| Logs | Problems grouped by app with explanations, all messages with search, crash reports, past boots |
| Services | System and user services with plain-language descriptions, start/stop/restart, on/off at boot, logs, details; scheduled timers |
| Security | Score and checklist with one-click fixes (firewall, auto-updates, SSH, open ports, screen lock, auto-login, remote desktop, Secure Boot, encryption), firewall rules (add / delete), SSH keys (create, copy, permissions), admins, failed logins |
| Privacy | Camera / microphone / screen sharing / location in use right now, GNOME privacy switches, what Ubuntu sends home (all off in one click), clear recent files / clipboard / thumbnails / shell history, app permissions (Flatseal) |
| Tweaks | Dev-laptop tuning with apply/undo (file watchers, open files, swappiness, zram, OOM protection, TRIM, boot/shutdown speed, log cap, snap versions, Pro ads), look (dark, accent, text size, pointer size), keyboard (Caps Lock → Escape/Ctrl, key repeat), desktop / touchpad / workspace switches |
| Developer | Git projects (status, pull, open in VS Code / Zed / terminal / lazygit / GitHub), running dev servers (open, stop, test on your phone), pm2, Docker/Podman containers, Node (nvm) and Python versions, CLI toolbox |
| Maintenance | One-click tune-up, weekly automatic checkup, settings backups and restore, Timeshift snapshots, the linux-setup scripts, project folders |

Every action shows the exact commands first. Anything that needs admin rights asks once, with Ubuntu's normal password popup (`pkexec`), and runs with a live log.

Shortcuts: **Ctrl+K** go to a page or run an action by typing · **Ctrl+1…9** pages · **F5** refresh · **Ctrl+F** search · **Ctrl+Q** quit. Right-click the dock icon for Clean up / Updates / Processes / Storage.

## Terminal commands

```
pc                 open the full-screen terminal app (pc storage, pc dev … opens a section)
pc gui [page]      open the desktop app
pc status          one-screen summary
pc doctor          health check, offers fixes
pc clean           safe cleanup (--dry-run, --deep, --all, -y)
pc update          update apt, snap, flatpak (--firmware)
pc ports           what's listening      pc kill-port 3000
pc big ~/          biggest folders       pc repos      git projects
pc info            hardware              pc logs       recent errors
pc services --failed                     pc backup     settings → ~/Backups
pc maintain --on | --off | --auto        weekly checkup
```

Settings: `~/.config/pc/config.json` (`theme`, `icons`: auto/nerd/plain, `projects`: folders scanned for git repos). The desktop app remembers its window size and last page in `~/.config/pc/gui.json`.

## Install / update

`bash ../setup.sh pc` installs both (the terminal app with `uv tool install`, the desktop app into `~/.local/share/pc-command-center` running on Ubuntu's Python with `python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-adw-1`, `python3-psutil`). `bash ../setup.sh app` updates just the desktop app.

Run from source: `PYTHONPATH=src /usr/bin/python3 -m pcctl.gui`. Tests: `PYTHONPATH=src python3 -m pytest tests`.

# PC Command Center

A control center for your whole Ubuntu computer, in two forms that share one engine:

- **PC Command Center**, a native desktop app (GTK 4 + libadwaita). It has a clean, neutral look with GNOME's accent colour, or Catppuccin if you prefer (Preferences → Colours). Light and dark follow GNOME's switch. Open it from the dock or app grid, or run `pc-gui`.
- **pc**, the same thing in the terminal. Type `pc`.

Version 2.2 (currently 2.2.4; see `../CHANGELOG.md`) builds on the original feature audit and adds safety hardening, diagnostics, background-task control and desktop-shell polish while retaining the broad feature set that filled about 110 gaps found in a feature audit against Stacer, BleachBit, Czkawka, Mission Center, Resources, Cockpit, Warehouse, Flatseal, Timeshift, GRUB Customizer, Windows Task Manager, Microsoft PC Manager, CleanMyMac and others. The full list is in `../docs/FEATURE-AUDIT.md`.

## The desktop app

| Page | What you can do |
|---|---|
| Dashboard | Health score, live CPU / memory (with cache, swap, zram) / GPU / network / disks / temperature / battery, how hard the PC is struggling right now (pressure), **Why is my PC slow?** (measures for two seconds and explains, with fixes), what needs attention |
| Cleanup | ~45 kinds of junk in 5 groups, plus unknown big caches, VS Code / Cursor storage of deleted projects and more developer caches. A never-clean list, the real space freed (measured before and after), cleanup history, and an extra warning above 10 GB. The deep scan also finds old `node_modules`, build folders, venvs, old runtimes and downloads, duplicate files, similar photos, and empty folders and files |
| Updates | apt + Snap + Flatpak in one list. **Undo an apt change** (APT 3 history), software sources and PPAs, kernels (remove old ones safely), drivers (NVIDIA, Wi-Fi, firmware), hold a package, "what's new" changelogs, a Timeshift snapshot before updating, pause snap updates |
| Apps | Everything installed from every source. **Install from a file** (.deb shows what it pulls in first, .flatpakref, .snap, AppImage), AppImages added to the app grid, uninstall several apps at once, Snap/Flatpak permissions, apps installed twice, apps you haven't opened in months, default terminal/browser/editor |
| Startup | Login apps (on/off, delay by N seconds), your login services, boot speed (breakdown, the chain that held the boot up, a boot chart picture, recent boot times), **boot menu (GRUB) settings** with a preview of the changes and a backup |
| Processes | Grouped by app or as a tree, disk read/write per process, **efficiency mode** (lowest CPU and disk priority), end several at once, details |
| Storage | Drives and partitions (mount / unmount / safely remove), readable drive health (wear, temperature, hours), a folder treemap, space by file type, Trash viewer (restore single items), swap size, disk speed test, big files, duplicates |
| Network | Live traffic, **which app talks to which address**, DNS switcher (Cloudflare, Google, Quad9, AdGuard), VPN on/off, saved Wi-Fi (show password, forget), hotspot, devices on your network, open ports, diagnosis, speed test |
| Power & hardware | **Battery history graph**, **keep awake** for N hours, **shutdown / restart / sleep timer**, CPU speed, governor, turbo and throttling, every device (USB, PCI, audio, Bluetooth, screens, memory), power modes, temperatures |
| Logs | Problems grouped with explanations, kernel messages (hardware, drivers, USB) with "harmless / worth a look" notes, **live follow**, crash reports, journal size with "keep only N MB" |
| Services | Services with memory and CPU per service, block/unblock (mask), **My scripts** (keep a script running or run it on a schedule, like pm2: creates a user service and timer), timers, cron jobs explained in plain English |
| Security | Checklist with one-click fixes, a **Secrets check** (API keys in shell history, `.env` files git would upload, private keys in projects, readable credential files, SSH keys without a passphrase, all masked), a warning when Docker ports bypass the firewall, SSH server hardening, AppArmor, a virus scan with ClamAV, user accounts |
| Privacy | Camera / mic / screen sharing / location in use, **developer tool telemetry off in one switch** (Next.js, .NET, Nuxt, Gatsby, Astro, Turborepo, Homebrew, VS Code…), file search indexing on/off and reset, history cleanup |
| Tweaks | Dev-laptop tuning with undo, a **GNOME extensions manager**, **Dock settings**, **Ctrl+Shift+Esc opens Processes** plus your own keyboard shortcuts, Files options, window buttons and clock, computer name, time zone and automatic time |
| Developer | Git projects (fetch all, what isn't pushed yet), dev servers (stop all), pm2, containers with **Docker disk usage and cleanup by type**, a **PATH doctor** (which `node`/`python` wins), language versions (install Python with uv), **Git identity and defaults**, **GitHub connection** (gh login, SSH test, create and upload a key), global packages (npm -g, pipx, uv tools, cargo) |
| Maintenance | One-click tune-up, **troubleshooters** (internet, sound, Bluetooth, slow PC, broken installs, desktop glitches, clock, printer, screen sharing), weekly checkup with a **health history graph**, a **system report** (one HTML file; the shared copy hides names and addresses), settings backups, Timeshift snapshots (list and delete), app update and uninstall |

Every action shows the exact commands first. Anything that needs admin rights asks once. With the app's polkit policy installed, the password popup names PC Command Center and remembers your password for a few minutes. A live log shows while it runs, and Activity history (**Ctrl+H**) keeps a redacted record of what the app did. **Background Tasks (Ctrl+Shift+T)** shows work still running, recent output and the app's own scheduled jobs; safe command tasks can be stopped there while critical package/boot/filesystem steps finish their current operation before stopping.

**Around the app**

- **Preferences** (Ctrl+,): light / dark / follow the system, Modern or Catppuccin colours, start page, graph speed, **Full/Reduced/Off interface motion**, pause graphs when the window is hidden, skip confirmations for harmless actions, background alerts, never-clean list, what the weekly auto-clean may clean, and **Diagnostics → opt-in redacted debug logs + support bundle export**. The sidebar can be hidden (**Ctrl+Shift+S**) and resized by dragging its divider.
- **Background alerts** work even with the app closed: disk almost full, security updates waiting, a service keeps crashing, restart pending, Trash huge, hot CPU, worn battery. Each notification opens the right page.
- The **search bar at the top** (or **Ctrl+K**) finds any page, action or single setting as you type. With GNOME search turned on, typing "clean", "battery" or "fix sound" in the Activities overview works too.
- **Quick actions** (top of the sidebar) has the everyday jobs one click away: scan for junk, update everything, why is it slow, tune-up, fix a problem, big files, speed test, system report. The card at the bottom of the sidebar shows disk space, memory and the health score.
- Right-click any table row to copy it, export the table to CSV, or run actions. Right-click the dock icon for Clean up, Updates, Processes, Storage, Fix a problem and Why is my PC slow?
- The first run opens a welcome screen that turns on the weekly checkup, alerts and the Ctrl+Shift+Esc shortcut in one place.

Shortcuts: **Ctrl+K** (or **Ctrl+P**) go to / do anything · **Ctrl+1…9** pages · **F5** or **Ctrl+R** refresh · **Ctrl+F** search · **Ctrl+,** preferences · **Ctrl+H** activity · **Ctrl+Shift+T** background tasks · **Ctrl+Shift+S** show/hide sidebar · **Ctrl+?** all shortcuts · **Ctrl+Q** quit.

## Terminal commands

```
pc                 open the full-screen terminal app (pc storage, pc dev … opens a section)
pc gui [page]      open the desktop app
pc status          one-screen summary
pc doctor          health check, offers fixes
pc slow            why is my PC slow right now? (offers fixes)
pc fix [what]      troubleshooters: internet, sound, bluetooth, apt, desktop, clock, printer, sharing, slow
pc secrets         leaked API keys / tokens / passwords (masked; --json)
pc support         redacted troubleshooting ZIP
pc report          save a system report (--share hides names, --quick, --text, --open, -o FILE)
pc clean           safe cleanup (--dry-run, --deep, --all, -y)
pc update          update apt, snap, flatpak (--firmware)
pc ports           what's listening      pc kill-port 3000
pc big ~/          biggest folders       pc repos      git projects
pc info            hardware              pc logs       recent errors
pc awake 2h        keep the PC awake (90m, forever, off, status)
pc telemetry off   switch off developer tool telemetry (on, status)
pc watch           background alerts: --on | --off | --list | --force
pc services --failed                     pc backup     settings → ~/Backups
pc maintain --on | --off | --auto        weekly checkup
pc completions zsh|bash                  Tab completion (installed automatically)
```

Settings: `~/.config/pc/config.json` (`theme`, `icons`: auto/nerd/plain, `projects`: folders scanned for git repos) and `~/.config/pc/gui.json` (the desktop app's preferences). History and state: `~/.local/state/pc/`.

## Install / update

`bash ../setup.sh pc` installs both:

- the terminal app, with `uv tool install`;
- the desktop app, into `~/.local/share/pc-command-center`, running on Ubuntu's Python with `python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-adw-1` and `python3-psutil`;
- Tab completion, the password-popup policy (`/usr/share/polkit-1/actions/`) and its helper (`/usr/local/libexec/pc-command-center/pc-admin`), and the GNOME search provider.

It also offers the weekly checkup and background alerts. `bash ../setup.sh app` updates just the desktop app. The app can also update itself from this folder: Maintenance → Setup → This app.

Run from source: `PYTHONPATH=src /usr/bin/python3 -m pcctl.gui`. Tests: `python3 -m pip install -e '.[dev]' && python3 -m pytest` (the project config adds `src` automatically). The CI workflow for them is in `../.github/workflows/ci.yml`, but GitHub only runs workflows from the repository root, so it does not run in the `vibes` repository until it is moved there. The GUI smoke test opens every page in light and dark; it needs a display and runs only when one is available.

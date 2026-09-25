# Handover: linux-setup + PC Command Center

**As of:** 25 September 2026 · **App version:** 2.1.0 · **Owner:** Ashu (`infinite4evr` on `ashu-pc`)
**Project folder on the PC:** `~/Documents/Vibes/linux-setup`
**Handbook (private web page):** https://claude.ai/artifact/XqkwAJkc7dhyKDzxYjrHLp

This document is everything needed to pick the project up cold: what it is, how it's built, how it was built, how to test and ship it, and what's still open.

---

## 1. In one minute

- **linux-setup** is a set of Bash scripts that clean junk off Ubuntu and set up a good-looking developer environment (Catppuccin Mocha, Ghostty, zsh + starship, modern CLI tools, VS Code + Zed, GNOME tweaks). You run it with `bash setup.sh`.
- **pc** is a Python package inside it (`pc/`) with three front ends that share one engine (`pcctl.core`):
  - **PC Command Center**, a native GTK 4 + libadwaita desktop app (`pc-gui`) with 16 pages. It's the main product.
  - **`pc`**, a full-screen terminal app (Textual) plus quick subcommands (`pc status`, `pc clean`, `pc fix sound`…).
  - Background jobs: a weekly checkup timer, 30-minute background alerts, and a GNOME Activities search provider.
- Every action that changes the system is shown to the user as exact commands first. Admin actions ask for the password once, via polkit/pkexec.
- **Status:** 2.1 is complete and delivered to the PC's project folder. It is not yet installed on the PC: the user has to run `bash ~/Documents/Vibes/linux-setup/setup.sh pc` and then log out and back in.
- **Tests:** 199 automated tests pass (unit tests plus a GUI smoke test in light and dark). Everything was tested in an Ubuntu 24.04 cloud sandbox, not on the real PC.

---

## 2. The target machine

| | |
|---|---|
| Computer | `ashu-pc`, user `infinite4evr` |
| OS | Ubuntu **26.04** LTS, GNOME 50 (Wayland only) |
| Toolkit | GTK 4.22, libadwaita ~1.8, Python 3.14 (system `/usr/bin/python3` with `python3-gi`) |
| 26.04 specifics | APT 3 (history/undo), **sudo-rs**, Rust coreutils (`du` is uutils; GNU `du` is `gnudu`), Chrony (not timesyncd), Dracut initramfs, Resources is the default system monitor, LocalSearch (was Tracker) |
| User profile | A "vibe coder": not a Linux expert. Every label must be plain English. Runs a pm2 WhatsApp bot on a specific Node version, which must never be touched. Keeps TeX Live, VirtualBox, Packet Tracer and Wireshark. Uses VS Code and Zed. |
| Look chosen by the user | Polished GNOME, Catppuccin Mocha, purple accent, Papirus icons, Inter font installed (`fonts-inter`) |

---

## 3. History: what was asked and what was built

| # | User request | What was done |
|---|---|---|
| 1 | "Free of junk, best tooling setup for a normal vibe coder dev, good aesthetics, best Linux setup on Ubuntu" | Researched current tools and Catppuccin ports; wrote the `scan` / `clean` / `setup` / `undo` / `tips` scripts |
| 2 | "Explain the options with examples" → picked Polished GNOME, Catppuccin Mocha, VS Code + Zed, remove Waydroid + Android | Setup and cleanup tailored to those choices |
| 3 | "Go very deep and make it a full computer management tool from the terminal" | Built `pc` (Textual TUI with 14 panels + CLI subcommands + weekly maintenance timer) |
| 4 | "Make a desktop app instead, very deep, full command centre, all cleanup" | Built PC Command Center 2.0 (GTK4/libadwaita, 16 pages, ~40 junk categories); published the handbook artifact (v3) |
| 5 | "Find all the missing features from all points of view, nearly exhaustive" + "audit and then build, don't wait, add light mode that follows the system" + "take inspiration from famous tools" | Wrote `docs/FEATURE-AUDIT.md` (~130 gaps, each tagged with the tool it's "Like"); built ~110 of them as **2.1**, including light/dark following GNOME |
| 6 | "The UI looks outdated" + a screenshot of a modern file manager as inspiration | Redesigned the look: neutral "Modern" palette following GNOME's accent, header search bar, Quick actions, sidebar status card, underlined tabs, pill filters, crisp tables, right-click menus with icons and red danger items. Catppuccin kept as an option. |
| 7 | "Do a handover" | This document |

---

## 4. Repository map

```
linux-setup/
├── setup.sh                 menu + entry point (scan | clean | setup | all | pc | app | tips | undo)
├── lib/
│   ├── common.sh            colours, ask(), need_sudo(), backup(), gset(), logging (~/.local/state/linux-setup/)
│   ├── scan.sh              "what's using space" report (changes nothing)
│   ├── clean.sh             apt/snap/flatpak/journal/caches/trash/launchers/Waydroid/old runtimes (asks each step)
│   ├── install.sh           tools, fonts, shell, Ghostty, CLI themes, VS Code/Zed, GNOME look, install_pc, install_pc_app
│   ├── undo.sh              restores originals saved by keep_original()
│   ├── tips.sh              the `tips` cheat sheet
│   └── jsonmerge.py         merges editor settings JSON (keeps user keys)
├── dotfiles/                zshrc, starship.toml, ghostty.config, VS Code/Zed settings, common.sh (aliases)
├── assets/                  wallpaper
├── docs/
│   ├── FEATURE-AUDIT.md     the gap audit: ✅ built in 2.1 · ⏳ later · ✗ won't do (with reasons)
│   └── HANDOVER.md          this file
└── pc/
    ├── pyproject.toml       package "pc-control" 2.1.0, console script `pc = pcctl.cli:main`
    ├── README.md            feature reference for users
    ├── data/                pc-admin (root helper) + polkit policy
    ├── tests/               unit tests (+ fixtures/) and the GUI smoke test
    └── src/pcctl/
        ├── __init__.py      __version__ = "2.1.0"
        ├── cli.py           `pc` subcommands + completion generator
        ├── core/            engine, no GTK (shared by GUI, TUI, CLI)
        ├── gui/             PC Command Center (GTK4/libadwaita)
        └── ui/              terminal UI (Textual)
```

### `pcctl.core`: the engine (no GTK imports allowed)

| Module | What it does |
|---|---|
| `run.py` | `sh()`/`out()`/`read()`/`has()` for reading state; **`Step`** and **`py_step`** for actions; `du_bin()` (GNU du or fallback), `py_size()`; `run_steps_blocking()` for the CLI |
| `fmt.py` | `human()`, `rate()`, `duration()`, `ago()`, `plural()`, Catppuccin colours for the terminal |
| `system.py` | CPU/memory/disks/network sampling, mounts, battery (UPower), temperatures, hardware, boot times, processes (`ProcessWatcher` with I/O deltas), app grouping |
| `junk.py` | Cleanup engine: ~45 categories in 5 groups, deep scan, exclusions ("never clean"), `AUTO_SAFE` categories for the weekly auto-clean |
| `dupes.py` | Exact duplicates (size → partial hash → full hash) |
| `drives.py` | lsblk drives, mount/unmount/eject, SMART JSON, swap resize, speed test, Trash viewer, file types, empty files/folders, similar photos (dHash) |
| `storage.py` | Folder sizes / big files with hints |
| `packages.py` | apt/snap/flatpak/AppImage apps and updates, APT 3 history + undo/rollback, kernels, drivers (`ubuntu-drivers`), deb822 sources/PPAs, holds, changelogs, snap refresh hold |
| `appmgr.py` | Install from file (.deb dry-run preview, flatpakref, snap, AppImage), AppImage integration, uninstall several, snap/flatpak permissions, apps installed twice, unused apps (GNOME `application_state`), default terminal |
| `boot.py` | GRUB settings (safe edit + diff + backup + `update-grub`), systemd-boot detection, boot analysis/critical chain/chart/history, login-app delay, user services |
| `services.py` | systemd services (+ plain-English explanations), startup apps, masks, memory/CPU per service, **pm2-like "My scripts"** (user .service/.timer), cron jobs explained |
| `logs.py` | Journal errors grouped, crashes, boots, kernel messages with explanations, live-follow command, journal size/vacuum/limit |
| `power.py` / `devices.py` | Battery history (UPower .dat files), keep awake (detached `systemd-inhibit`), shutdown/restart/sleep timers, CPU speeds/governor/turbo/throttling; all devices (USB, PCI, audio, Bluetooth, screens via EDID, cameras, memory) |
| `network.py` | Interfaces, Wi-Fi, listening ports, connections per app, DNS presets, VPNs, saved Wi-Fi passwords, hotspot, LAN devices, speed test |
| `gpu.py` / `diagnose.py` | GPU usage (NVIDIA/AMD/Intel); "Why is my PC slow?" (PSI pressure, CPU hogs, swap, disk wait, throttling, background jobs…) with efficiency-mode fixes |
| `security.py` | Checklist (`Check` dataclass: id, title, level, detail, fix_label, steps, goto), firewall, Docker ports bypassing UFW, SSH hardening, AppArmor |
| `secrets.py` | Leaked keys in shell history, `.env` files git would upload, private keys in projects, readable credential files, unprotected SSH keys (all masked); `pc secrets` |
| `accounts.py` / `antivirus.py` | User accounts; ClamAV scan |
| `privacy.py` / `devtelemetry.py` / `indexing.py` | GNOME privacy settings; dev-tool telemetry off (environment.d + shell block + VS Code-family settings); LocalSearch on/off/reset |
| `tweaks.py` / `desktop.py` / `extensions.py` / `shortcuts.py` | Dev-laptop tuning with undo; Dock/Files/window/clock/hostname/time zone; GNOME extensions manager; custom keybindings (Ctrl+Shift+Esc → Processes) |
| `dev.py` / `devsetup.py` | Git repos, dev servers, pm2, containers, Docker disk usage/prune; PATH doctor, GitHub (`gh`, SSH test, keys), git identity/defaults, global packages, uv Python |
| `health.py` | Health checks + score (dashboard, `pc doctor`, report) |
| `maint.py` | Weekly checkup timer, settings backups/restore, Timeshift create/list/delete, project folders config |
| `watch.py` | Background alerts (user timer every 30 min), health history (`record_health`), click-to-open notifications |
| `troubleshoot.py` | 9 troubleshooters: internet, sound, bluetooth, slow, apt, desktop, clock, printer, sharing |
| `report.py` | System report: HTML (self-contained, light/dark) and text, with redaction for sharing |
| `selfupdate.py` | Update the installed app from the linux-setup folder, install polkit helper, GNOME search registration, uninstall |

### `pcctl.gui`: the desktop app

| File | Role |
|---|---|
| `__main__.py` | Entry; `--search-provider` runs the D-Bus search service without GTK |
| `main.py` | `Adw.Application` (single instance, `HANDLES_COMMAND_LINE`); `--page`, `--action`, `--screenshots DIR --pages a,b --wait N` (test mode); crash guard; welcome on first run |
| `window.py` | Main window: sidebar (Quick actions, sections, badges, status card), header search with results popover, page stack, toasts, actions/shortcuts, palette (`PALETTE_ACTIONS`, `all_actions()`, `setting_rows()`, `run_action()`), pause when hidden |
| `pages/base.py` | `Page` base class, `tabs()` (underline tab bar with auto-compact labels and a GTK 4.14 re-measure fix), `group`, `action_row`, `switch_row`, `banner`, `stat`… |
| `pages/*.py` | The 16 pages (table in §6) |
| `widgets.py` | `LineGraph`, `RingGauge`, `MiniBar`, `HBars`, `Treemap`/`squarify`, `card`, **`DataTable`** (sortable, filterable, CSV export) and **`context_menu()`** (icons picked from wording, danger items in red at the bottom) |
| `dialogs.py` | `confirm` (shows commands), `TaskDialog` (live log, records to Activity), `run_steps`, `ChecksDialog`, `ChoiceDialog`, `PickDialog`, `ActivityDialog`, `ask_text`, `show_text` |
| `runner.py` | Runs Steps in a thread; consecutive root steps go into one batch script run by `pkexec pc-admin` (one password prompt) |
| `theme.py` + `style.css` | Colour looks (Modern/Catppuccin × light/dark), system accent, CSS template with `$tokens` |
| `prefs.py` / `preferences.py` | `~/.config/pc/gui.json`; the Preferences dialog (General / Alerts / Cleanup) |
| `activity.py` | Activity history (`~/.local/state/pc/activity.jsonl`) and GUI error log |
| `welcome.py` | First-run welcome (weekly checkup, alerts, Ctrl+Shift+Esc) |
| `search_provider.py` | `org.gnome.Shell.SearchProvider2` over D-Bus |
| `util.py` | `bg()` (thread + main-loop callback), `label/button/hbox/vbox/flow/pill/esc/launch/open_in_terminal`… |

### `pcctl.ui`: the terminal app
A Textual app (`ui/app.py`, `ui/panels/*.py`, `app.tcss`) with overview, processes, storage, cleanup, updates, apps, startup, services, network, dev, power, security, logs and maintenance panels. It uses the same `core`. It wasn't extended in 2.1 beyond keeping it working (verified with a Textual pilot run).

---

## 5. Architecture and key design decisions

### 5.1 Actions are Steps, never hidden commands
- Pages never call `subprocess` to change the system. They build a list of `core.run.Step(title, cmd, root=False, env={}, cwd=None, ok_codes=(0,), optional=False)`, or `py_step(title, func, shown)` for Python work, and call `Page.run(title, steps, explain, danger, ok_label, reload, done, ask)`.
- `run_steps` shows a confirm dialog with the exact commands. Admin and danger actions always confirm; harmless ones can skip confirmation via the `confirm_safe` preference. A `TaskDialog` then streams the output and records the action in Activity history (Ctrl+H).
- **Root:** consecutive `root=True` steps are written to a batch script `/tmp/pc-admin-*.sh` (0600, owned by the user). It is run by `pkexec /usr/local/libexec/pc-command-center/pc-admin <script>`, which refuses anything that isn't such a script, is a symlink, belongs to someone else, or is writable by others. The polkit policy uses `auth_admin_keep`, so the password is remembered for a few minutes. Without the helper installed, it falls back to `pkexec /bin/bash`. `PC_ROOT_RUNNER=sudo` switches to `sudo -n` for tests.
- `core.run.sh()` uses the C locale so parsers are stable. It never raises; it returns `Result(code, out, err)`.

### 5.2 Pages
- The `Page` lifecycle: `build()` runs once and creates widgets; `load()` runs on first show and on refresh (F5); `tick()` runs every `AUTO_REFRESH` seconds while visible (scaled by the refresh preference and paused while the window is hidden).
- Slow work goes through `self.bg(fn, done)`; never block the UI thread.
- Tabs use `sw, self.stack = tabs(("id", "Title", "icon", box), …)`. Tabs load lazily on `notify::visible-child-name`.
- **Command palette/search hook:** a page class can declare `PALETTE = [("key", "Do the thing")]` and implement `palette_action(key)`. The window adds these to the header search and to GNOME search, and `run_action("page:key")` navigates to the page and calls the hook. Built-in cross-page actions live in `window.PALETTE_ACTIONS`. Individual settings (`tweaks.DESKTOP`, `privacy.SETTINGS`) are searchable as `setting:<page>:<title>`.

### 5.3 The window (2.1 redesign)
- **Header:** a search field (Ctrl+K focuses it) with a results popover (↑↓ + Enter). It covers pages, actions and single settings. The popover is non-focusable so typing stays in the field.
- **Sidebar:**
  - A **Quick actions** button: scan for junk, update everything, why slow, tune-up, fix a problem, big files, speed test, report.
  - Sections: Clean & update · Monitor · System · Develop · Care.
  - Badges: red for security updates and failing services.
  - A **status card** at the bottom showing main disk, memory, the health score and a "Free up space →" link. It refreshes every 20 s, and the dashboard pushes the health score to it.
- The sidebar collapses under 820 sp. Minimum window size is 760×520, and pages are kept usable at ~750 px of content width.

### 5.4 Theme
- `style.css` is a template. `$name` tokens are filled from the active palette, and the stylesheet is reloaded when GNOME switches light/dark or changes the accent. Both the old `@define-color` and the new CSS-variable libadwaita names are set.
- On GTK < 4.16, the `:root { … }` block is stripped (it would produce parser warnings).
- **Looks:** `modern` is the default (neutral greys, white cards with hairline borders, GNOME's accent colour). `catppuccin` is the Latte/Mocha option. The user picks it in Preferences → Colours (pref `look`), or via `PC_LOOK` for tests.
- Palettes keep Catppuccin token names (`mauve` = accent text, `accent_bg` = accent fill, `surface0` = tracks, `overlay1` = dim text, plus `line`, `line_soft`, `hover`, `field`, `shadow`). Every widget therefore works with every look.
- **Accent:** read from libadwaita ≥1.6 (`Adw.StyleManager.get_accent_color` + `accent_color_to_rgba` / `to_standalone_rgba`). The fallback is GNOME's `org.gnome.desktop.interface accent-color` mapped to Adwaita hex values, then blue.
- Cairo widgets use `widgets.rgb("token")`. `theme.redraw_tree(window)` repaints them after a switch.
- The font stack is Inter → Adwaita Sans → Ubuntu Sans → Cantarell. Numbers use tabular figures.

### 5.5 Background pieces (all per-user, no root)
- **Weekly checkup:** `~/.config/systemd/user/pc-maintain.{service,timer}` (Sundays 11:00) runs `pc maintain --auto`.
- **Background alerts:** `pc-watch.{service,timer}`, every 30 min, runs `pc watch`. `KillMode=process` keeps the "click to open" notification helpers alive. The alerts are:
  - disk almost full;
  - security updates waiting (every 3 days);
  - failing services;
  - restart pending;
  - Trash too big;
  - CPU too hot;
  - worn battery.

  Each alert fires at most once a day (state in `~/.local/state/pc/alerts.json`). Clicking a notification opens `pc-gui --page <page>`. Settings live in Preferences → Alerts.
- **Health history:** one score per day (the worst of the day) in `~/.local/state/pc/health-history.json`. It is recorded by the dashboard and by the alerts timer, and graphed in Maintenance → Checkups.
- **GNOME search:** `~/.local/share/dbus-1/services/io.github.infinite4evr.PcCommandCenter.SearchProvider.service` (Exec `pc-gui --search-provider`) plus the root-installed `/usr/local/share/gnome-shell/search-providers/io.github.infinite4evr.PcCommandCenter.search-provider.ini`. The provider quits after 60 s idle. Picking a result runs `pc-gui --page X` or `--action key`. It needs a logout/login after installing.

### 5.6 Self-update and uninstall
- The installer copies `pc/src/pcctl` to `~/.local/share/pc-command-center/pcctl` so the app survives the folder moving.
- Maintenance → Setup → "This app" compares versions and file contents with the linux-setup folder and offers **Update**: it copies the code, reinstalls the CLI with uv, refreshes completions and reinstalls the polkit helper if it changed, then offers a restart.
- It can also set up the password prompt or GNOME search if missing, show the welcome screen again, or **Uninstall** (keep or delete settings). "My scripts" units made by the user are left alone.

---

## 6. Pages reference

| Page | Tabs | Highlights |
|---|---|---|
| Dashboard | — | Health ring + fix buttons, **Why is my PC slow?**, live CPU (per core) / memory (cache, swap, zram) / GPU / network / disks / temperature / battery, pressure (PSI) |
| Cleanup | groups | ~45 categories in 5 groups, deep scan, never-clean list (right-click/⋯), real space freed (measured), history, >10 GB warning, similar photos, empty folders |
| Updates | Waiting · History & undo · Drivers · Sources · Settings | apt+snap+flatpak, security first, APT 3 undo/rollback, kernels, drivers, PPAs, holds, changelogs, Timeshift snapshot before updating, pause snaps |
| Apps | Installed · Get apps · AppImages · Tidy up · Defaults | Install from file, AppImage integration + libfuse2 check, uninstall several, permissions, installed twice, unused apps, default terminal/browser/editor |
| Startup | Login apps · Services · Boot speed · Boot menu | Login-app delay, user services, critical chain, boot chart SVG, boot history, GRUB settings with diff/backup/restore |
| Processes | — | Grouped/tree, CPU/memory/disk per app, efficiency mode, end several, details |
| Storage | Disks · Explore · Big files · Duplicates · File types · Trash | Drives & partitions (mount/eject), SMART health, treemap, swap resize, speed test |
| Network | Wi-Fi & DNS · Talking to · Open ports · Devices nearby · Fix & speed | DNS switcher, VPN, saved Wi-Fi password/forget, hotspot, connections per app (grouped), LAN scan, diagnosis, speed test |
| Power & hardware | Power · Battery · CPU & heat · Devices · What's inside | Battery history graph, keep awake, shutdown/restart/sleep timer, CPU speeds/turbo/throttling, all devices |
| Logs | Problems · Messages · Kernel · Crashes · Restarts · Log size | Explanations, live follow, journal vacuum/limit |
| Services | Services · My scripts · Timers · Cron jobs | Memory/CPU per service, block (mask), pm2-like scripts, cron in plain English |
| Security | Checklist · Secrets · Firewall · Viruses · Accounts | Secrets check, Docker vs UFW, SSH hardening (drop-in `00-pc-hardening.conf`), AppArmor, ClamAV, accounts |
| Privacy | Settings · Tracking · File search · History | Camera/mic/screen/location in use, dev telemetry off, LocalSearch on/off/reset, history cleanup |
| Tweaks | System · Desktop · Dock · Files · Extensions · Shortcuts | Tuning with undo, Dock settings, extensions manager, Ctrl+Shift+Esc and custom shortcuts, hostname/time zone/NTP |
| Developer | Projects · Servers · Containers · Languages · Git · Tools | Fetch all/unpushed, stop all servers, pm2, Docker disk cleanup, PATH doctor, uv Python, git identity/defaults, GitHub connection, global packages |
| Maintenance | Fix problems · Checkups · Report · Backups · Setup | Tune-up, 9 troubleshooters, health history graph, system report (share copy redacted), settings backups, Timeshift list/delete, app update/uninstall |

---

## 7. Terminal commands (`pc`)

```
pc                      full-screen terminal app (pc storage, pc dev … opens a section)
pc gui [page]           open the desktop app
pc status | doctor      summary | health check with fixes
pc slow                 why is my PC slow right now (offers fixes)
pc fix [what]           troubleshooters: internet sound bluetooth slow apt desktop clock printer sharing (--no-fix)
pc secrets [--json]     leaked keys/tokens/passwords (masked; exit 1 if something serious)
pc report               HTML report (--share hides names, --quick, --text [--full], -o FILE, --open)
pc clean                safe cleanup (--dry-run, --deep, --all, -y)
pc update [--firmware]  apt + snap + flatpak
pc ports [--all] · pc kill-port N · pc big [path] · pc repos · pc info · pc logs [--since] · pc services [--failed]
pc awake 2h|90m|forever|off|status
pc telemetry off|on|status
pc watch [--on|--off|--list|--force]     background alerts (the timer runs plain `pc watch`)
pc maintain [--on|--off|--auto]          weekly checkup
pc backup                                settings → ~/Backups
pc completions bash|zsh                  generated from argparse, so they never go stale
```

---

## 8. What gets installed where (on the PC)

| Path | What |
|---|---|
| `~/.local/share/pc-command-center/pcctl` | Desktop app code (copied from the repo) |
| `~/.local/bin/pc-gui` | Launcher: `PYTHONPATH=… exec /usr/bin/python3 -m pcctl.gui` |
| `~/.local/bin/pc` | Terminal app (uv tool `pc-control`, or venv `~/.local/share/pc/venv`) |
| `~/.local/share/applications/io.github.infinite4evr.PcCommandCenter.desktop` | App entry; dock actions: Clean up, Updates, Processes, Storage, Fix a problem, Why is my PC slow? |
| `~/.local/share/icons/hicolor/scalable/apps/io.github….svg` | Icon |
| `~/.local/share/zsh/site-functions/_pc`, `~/.local/share/bash-completion/completions/pc` | Tab completion (installer adds the `fpath` line to an existing `~/.zshrc`) |
| `~/.local/share/dbus-1/services/…SearchProvider.service` | GNOME search helper |
| `~/.config/systemd/user/pc-maintain.*`, `pc-watch.*`, `pc-<name>.service/.timer` | Weekly checkup, alerts, "My scripts" |
| `~/.config/pc/config.json` | CLI/TUI settings (`projects`, `setup_dir`, `auto_clean`, …) |
| `~/.config/pc/gui.json` | App preferences: `appearance`, `look`, `start_page`, `refresh`, `pause_hidden`, `confirm_safe`, `big_delete_gb`, `welcomed`, window size/page |
| `~/.config/environment.d/90-pc-no-telemetry.conf` (+ marked blocks in `~/.bashrc`/`~/.zshenv`) | Telemetry off |
| `~/.local/state/pc/` | `activity.jsonl`, `gui-errors.log`, `alerts.json`, `health-history.json`, `cleanup-history.json`, `maintain.log`, keep-awake state |
| `~/.cache/pc/` | Caches (memory module info, staged search .ini) |
| `/usr/local/libexec/pc-command-center/pc-admin` (root, 755) | Admin helper |
| `/usr/share/polkit-1/actions/io.github.infinite4evr.PcCommandCenter.policy` | Password popup names the app, `auth_admin_keep` |
| `/usr/local/share/gnome-shell/search-providers/…search-provider.ini` | GNOME search registration |
| `~/.local/state/linux-setup/` | Setup script logs, backups (`backup-<run>`), `originals/` for undo |

---

## 9. Install and update flow

- `bash setup.sh` shows a menu: 1 Scan · 2 Clean · 3 Set up · 4 all three · 5 Tips · 6 Undo · 7 pc · 8 App.
- **`bash setup.sh pc`** (`install_pc` in `lib/install.sh`):
  1. uv tool install of the package, remembering `setup_dir`.
  2. Tab completion files, and the `fpath` line inserted into an existing `~/.zshrc` (after a backup).
  3. `install_pc_app`: apt deps `python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 python3-psutil`; copy the code; launcher, desktop entry and icon; D-Bus search service; `sudo install` of pc-admin, the polkit policy and the search .ini; pin to the dock.
  4. It then asks whether to turn on the weekly checkup (`pc maintain --on`) and background alerts (`pc watch --on`).
- **`bash setup.sh app`** updates only the desktop app. The app can also update itself (§5.6).
- **Run from source:** `cd pc && PYTHONPATH=src /usr/bin/python3 -m pcctl.gui`.

---

## 10. Environment variables

| Variable | Effect |
|---|---|
| `PC_STYLE=light\|dark\|system` | Force light/dark (tests, screenshots) |
| `PC_LOOK=modern\|catppuccin` | Force the colour look |
| `PC_NO_WELCOME=1` | Don't show the first-run welcome (tests) |
| `PC_ROOT_RUNNER=sudo` | Use `sudo -n` instead of pkexec (tests as a non-root user) |
| `GSK_RENDERER=cairo` | Needed for headless Xvfb rendering |

---

## 11. Testing

**Unit tests** (`cd pc && PYTHONPATH=src python3 -m pytest -q tests`; no GTK needed): 199 tests.

| File | Tests (functions) | Covers |
|---|---|---|
| `test_parsers.py` | 20 | ss, apt, snap, flatpak, journal, junk, dev parsers |
| `test_apps_boot.py` | 33 | apt simulate, AppImage, snap/flatpak permissions, duplicates, GNOME app state, GRUB edit/diff, boot chain |
| `test_power_logs_services.py` | 37 | UPower history, inhibitors, timers, devices, kernel log, journald, cron→English, systemd quoting for scripts |
| `test_security_privacy.py` | 35 | Secret patterns and masking, history scrubbing, .env/git, SSH config (first value wins), Docker ports, accounts, telemetry blocks, JSONC editing, indexing |
| `test_tweaks_dev.py` | 32 | Extensions, keybindings, dock/files settings, PATH doctor, gh status, git config, docker df, npm/pipx/uv/cargo, time zones |
| `test_maintenance.py` | 10 | wpctl, rfkill, timedatectl, dpkg states, Timeshift list, report redaction/rendering |
| `test_gui_smoke.py` | 1 (×2 styles) | Opens every page in light and dark, asserts no traceback and a non-empty screenshot per page. Skips without a display or GTK Python. |

Test data lives in `tests/fixtures/<area>/`; the secret-like strings in them are fake.

**Headless GUI checks (how every screen was verified):**
- **Setup:** Xvfb on `:99` (`Xvfb :99 -screen 0 1920x1200x24 &`), `DISPLAY=:99 GSK_RENDERER=cairo`, and a Python that has `gi` (in the sandbox that's `/usr/bin/python3.12`; unit tests ran on 3.11).
- **Quick sweep:** `PC_STYLE=dark PC_NO_WELCOME=1 python3 -m pcctl.gui --screenshots /tmp/out --pages dashboard,updates --wait 3` saves one PNG per page.
- **Scenario harness:** a small script outside the repo, which drove the app step by step:
  - `goto`, `wait`, `call lambda win, page: …`, `accept`/`close` dialogs, `shot`, and `shotw` for popovers, which are separate surfaces and aren't in window screenshots.
  - Every page and dialog was photographed in light and dark and looked at.
  - Worth re-creating: ~60 lines around `pcctl.gui.main.App` and `screenshot()`.
- **Minimum width:** a script walked the widget tree with `measure(HORIZONTAL)` to find anything forcing the content wider than ~750 px.
- **Terminal UI:** checked with Textual's `run_test()` pilot (switching panels 1–9).
- **Other checks:** the GNOME search provider was tested inside `dbus-run-session` with `gdbus call …GetInitialResultSet`, and the HTML report with headless Chromium screenshots.

**Sandbox ≠ the real PC.** The sandbox has GTK 4.14 / libadwaita 1.5, no GNOME Shell, no user systemd session, no battery, Wi-Fi or GRUB, and runs as root. Code must degrade gracefully; the pages show friendly empty states. System-changing actions were never run for real; tests assert on the generated `Step.cmd` lists instead.

---

## 12. How the work was done

1. **Research first.** Checked what changed in Ubuntu 26.04 and what the well-known tools do (Stacer, BleachBit, Czkawka, Mission Center, Resources, GNOME System Monitor, Cockpit, Warehouse, Flatseal, Timeshift, GRUB Customizer, Mainline, hardinfo2, TLP/auto-cpufreq, glances/btop, Windows Task Manager, Microsoft PC Manager, CCleaner, CleanMyMac).
2. **Audit before building.** `docs/FEATURE-AUDIT.md` lists every gap with the tool it's "Like", a priority and a status, so the scope was explicit and trackable.
3. **Foundations myself:**
   - light/dark theme, preferences, activity history, the polkit helper, crash guard, pause-when-hidden;
   - the Updates, Storage, Processes, Network and Cleanup extensions;
   - the Maintenance page, CLI, search provider, welcome, self-update, installer and docs.
4. **Parallel helpers for the rest.** Four sub-agents each built one area with **strict file ownership** so they couldn't clash: Apps + Startup; Power + Logs + Services; Security + Privacy; Tweaks + Developer. They each worked from a shared brief with the rules in §13. Each had to lint, add tests, screenshot light and dark, and report back. I then fixed the shared issues they reported:
   - the tab re-measure fix and auto-compact tab labels;
   - a proper info banner style;
   - `bg()` no longer logging expected errors;
   - a plain-text combo row helper.

   Two things interrupted the work:
   - Usage limits cut the agents off mid-way. They were resumed with their context, and the one that failed again was finished by me after verifying its work.
   - The Maintenance agent never started, so I wrote that page myself.
5. **Test everything, look at everything.** pyflakes clean, unit tests, the GUI smoke test, and full screenshot sweeps in light and dark after each change, fixing what looked wrong (missing icons, truncated tabs, escaping, overflow).
6. **UI redesign on feedback.** The user found the Catppuccin UI dated. I reworked the palette, header, sidebar, tabs, tables and menus, kept Catppuccin as an option, and re-swept every page.
7. **Delivery.**
   - A mirror is kept at `/mnt/user-data/outputs/linux-setup` (+ `linux-setup.zip`).
   - Files reach the PC through the desktop bridge: `SendUserFile` (gives file UUIDs), then `device_commit_files` into `~/Documents/Vibes/linux-setup` (max 50 files per call). This session had no shell on the PC, so the user runs the installer themselves.
   - The handbook artifact is republished from `/home/claude/guide/ashu-pc-handbook.html` (updating needs `url=` and a fresh read of the live version first).

---

## 13. Rules to keep following

- **Plain English everywhere.** Say what something does and why you'd want it. No jargon without a one-line explanation. The user is not a Linux expert.
- **Show before doing.** Changes are Steps shown in a confirm dialog, with danger styling for anything destructive, and are logged in Activity history.
- **Never touch:**
  - Documents, Downloads, Pictures, Music and Videos;
  - projects, TeX Live, VirtualBox and browsers;
  - the Node version the pm2 bot runs on.
- **`core` has no GTK.** The CLI and TUI import it. Don't change the signatures of existing public functions; add new ones.
- **libadwaita 1.5 API floor.** Guard newer calls with `hasattr`. Use `esc()` for any text put into row titles and subtitles. Combo rows use `set_use_markup(False)` with raw text, because markup defaults differ by version.
- **No hard-coded colours.** Use CSS classes (`dim`, `accent-text`, `pill-*`, `banner-*`, `card`, …) or `theme.hex()` / `widgets.rgb()` tokens. It must look right in light and dark, in both looks.
- **Width:** usable at ~750 px of content. Use `flow()` and wrapping labels; avoid fixed widths.
- **Icons:** prefer non-legacy Adwaita names (Papirus covers the rest on the user's PC).
- **Tests:** new parsers get fixture-based unit tests in `tests/test_<area>.py`.

---

## 14. Known issues, caveats and gotchas

- **Nothing has run on the real PC yet.** Expect small surprises on GNOME 50 / libadwaita 1.8 (it was built against 1.5 in the sandbox). The first thing to do is run it on `ashu-pc` and walk every page.
- **Login-app delay (F2):** GNOME now starts login apps through systemd and may ignore `X-GNOME-Autostart-Delay`. A small systemd delay was added as a backup. Unconfirmed on 26.04.
- **GNOME search** only appears after log out / log in. **Zsh completion** needs a new terminal (the installer deletes the zcompdump).
- **Background-alert clicks** open the right page only after `pc watch --on` rewrites the unit with `KillMode=process`; the installer does this.
- **Popovers** (search results, right-click menus, Quick actions) are separate surfaces: window screenshots don't include them, so use the widget's own paintable (`shotw`).
- **Tab labels:** `Adw.ViewSwitcher` makes all tabs equal width. Pages with 6 tabs switch to compact labels (icon above text) when narrow.
- **GTK 4.14:** a box filled while its tab is hidden can keep a stale height. `base.tabs()` re-measures on switch; Security and Privacy also do it themselves.
- **Screenshot mode** occasionally caught an empty frame. It now retries up to 4 times.
- **The Terminal UI (`ui/`)** didn't get the 2.1 features; it's the 2.0 feature set on the new core.
- **SSH hardening** writes `00-pc-hardening.conf` (sshd uses the first value it reads, so a `99-` file would lose to cloud-init's `50-…`). It only disables password login when `authorized_keys` has a key.
- **Docker "Only this PC"** edits `/etc/docker/daemon.json` (`"ip": "127.0.0.1"`) and restarts Docker. It's excluded from "Fix all".
- **Test fixtures** contain fake token-shaped strings. If the repo is pushed to GitHub and push protection complains, they're fake; allow them or move them to string concatenation like the test files do.

---

## 15. Deferred (⏳) and rejected (✗) items from the audit

**Later (P3):**
- **App-wide:** multi-language UI; customisable dashboard / "My Tools"; a top-bar GNOME Shell extension; a mini always-on-top monitor; 1 h / 24 h metric history; NPU usage.
- **Cleanup:** browser history/cookies per browser; vacuuming browser databases.
- **Updates and apps:** Flatpak pin/downgrade; fastest mirror; leftover `~/.config` folders of removed apps; AppImage updater.
- **Startup, processes, storage, network:** per-login-app startup impact; network usage per process (needs root/eBPF); CPU limit via cgroups; folder growth over time; SMB/NFS shares; bandwidth history; traceroute/mtr.
- **Power, logs, security, privacy:** lid/power-button behaviour; benchmarks; reporting a crash to Ubuntu; `pro security-status` CVEs; EXIF removal; webcam off at driver level.
- **Tweaks and developer:** font manager; Catppuccin flavour switcher; mkcert.
- **Other:** copying home to USB (Déjà Dup/Pika already do it); `--json` for all CLI commands; packaging as a .deb.

**Won't do:**
- shredding / wiping free space on SSDs (TRIM already erases freed blocks; overwriting only wears the SSD);
- localepurge (breaks apt's view of packages, saves little);
- editing service overrides (expert-only, easy to break boot);
- USBGuard (can lock you out of your keyboard).

---

## 16. Suggested next steps

1. On the PC: `bash ~/Documents/Vibes/linux-setup/setup.sh pc` → log out/in → open the app, go through every page in light and dark, try Quick actions, the search bar, one troubleshooter and one report. Note anything off.
2. Watch `~/.local/state/pc/gui-errors.log` for the first few days; that's where unexpected errors land.
3. If the user wants more: the P3 list above, and bringing the 2.1 features to the terminal UI.
4. If `linux-setup` isn't in Git yet, put it there, so changes can be reviewed and rolled back.

---

## 17. Where to look

- **User-facing feature list:** `pc/README.md`, the root `README.md` and the handbook artifact.
- **Scope and decisions:** `docs/FEATURE-AUDIT.md`.
- **Entry points:** `pc/src/pcctl/gui/main.py`, `gui/window.py`, `gui/pages/base.py`, `core/run.py`, `lib/install.sh` (`install_pc`, `install_pc_app`).

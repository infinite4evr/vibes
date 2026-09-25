# PC Command Center: feature audit

September 2026 · app version 2.0 → 2.1 · **status: built** (every ✅ row ships in 2.1)

This is a sweep for everything the app (desktop **PC Command Center** and terminal **pc**) is missing, looked at from every angle: a normal user who wants a fast, clean PC; a vibe-coder developer; a laptop owner; someone who cares about privacy and security; and the app itself (look, safety, reliability, packaging).

**How it was done**

1. Compared against the well-known tools people use for the same jobs: Stacer, BleachBit, Czkawka/Krokiet, Mission Center, Resources (Ubuntu 26.04's new default monitor), GNOME System Monitor, Cockpit, Warehouse, Flatseal, Timeshift, GRUB Customizer, Mainline, hardinfo2, TLP / auto-cpufreq / power-profiles-daemon, glances/btop, Windows Task Manager, Microsoft PC Manager, CCleaner and CleanMyMac.
2. Walked through each page's code looking for dead ends ("I can see it but can't act on it"), missing states (empty, error, offline), and actions a user would reasonably expect next.
3. Checked what changed in **Ubuntu 26.04** (the version on ashu-pc): APT 3 history with undo/rollback, sudo-rs, Rust coreutils (`du` is now uutils), Chrony, Dracut, GNOME 50 Wayland-only, Resources as the default monitor, crash dumps enabled by default.

**Legend**

- Priority: **P1** high value, **P2** worth having, **P3** nice idea / later.
- Status: ✅ built in 2.1 · ⏳ later · ✗ won't do (reason given).
- "Like" names the tool the idea comes from.

---

## A. Whole app: look, comfort, platform

| ID | Missing feature | Like | Pri | Status |
|---|---|---|---|---|
| A1 | **Light mode that follows the system** (Catppuccin Latte ↔ Mocha, switches live when GNOME's style changes), plus a manual Light / Dark / System choice | every GNOME app | P1 || ✅ |
| A2 | Preferences window: appearance, start page, refresh speed, background alerts and thresholds, cleanup exclusions, weekly auto-clean contents | Mission Center, CleanMyMac | P1 || ✅ |
| A3 | Activity history: every action the app ran (when, what, exact commands, result, output) with re-open and re-run | Cockpit, CleanMyMac | P1 || ✅ |
| A4 | Friendlier password prompt: a proper polkit policy so the popup says "PC Command Center needs admin rights" instead of `/bin/bash /tmp/pc-admin-…`, and remembers the password for 5 minutes so several fixes in a row don't ask again | GNOME Software, Cockpit | P1 || ✅ |
| A5 | Pause live graphs and polling when the window is minimised or hidden (saves battery) | Mission Center | P1 || ✅ |
| A6 | Crash guard: any unexpected error is logged to a file and shown as a toast with details, instead of a silent failure | | P1 || ✅ |
| A7 | Background alerts (no window needed): disk almost full, failing services, security updates waiting for days, restart pending, Trash huge, battery worn. Desktop notifications that open the right page | CleanMyMac menu app, PC Manager | P1 || ✅ |
| A8 | GNOME Activities search: type "clean", "ports", "battery" in the overview to jump straight to that page | GNOME Settings | P2 || ✅ |
| A9 | Right-click menu on every table row (copy, export, page-specific actions) | Windows Task Manager | P2 || ✅ |
| A10 | Export any table to CSV | Cockpit | P2 || ✅ |
| A11 | Accessibility: every icon-only button gets a readable label for screen readers | | P2 || ✅ |
| A12 | First-run welcome: what the app does, turn on weekly checkup and alerts in one place | CleanMyMac | P2 || ✅ |
| A13 | Ctrl+K search also finds individual settings (e.g. "hot corner", "tap to click") | GNOME Settings search | P2 || ✅ |
| A14 | Update check for the app itself (newer version in the linux-setup folder) and a clean uninstall | | P2 || ✅ |
| A15 | Multi-language UI | BleachBit (61 languages) | P3 | ⏳ |
| A16 | Customisable dashboard tiles / "My Tools" pinned actions | CleanMyMac My Tools | P3 | ⏳ |
| A17 | Top-bar indicator (GNOME Shell extension) with CPU/RAM and quick actions | Vitals, CleanMyMac menu | P3 | ⏳ (needs a separate Shell extension) |
| A18 | Compact / always-on-top mini monitor window | Windows Task Manager | P3 | ⏳ |

## B. Dashboard and live monitoring

| ID | Missing feature | Like | Pri | Status |
|---|---|---|---|---|
| B1 | **GPU tile**: usage, video memory, temperature, power (NVIDIA via nvidia-smi, AMD via sysfs, Intel frequency) | Mission Center, Resources | P1 || ✅ |
| B2 | **"Why is my PC slow?"** one-click diagnosis: CPU hogs, memory pressure, swapping, disk waiting, thermal throttling, low disk, indexing, snap refresh, too many startup apps, each with a fix | PC Manager Boost, CleanMyMac | P1 || ✅ |
| B3 | Memory breakdown: in use / cache / available / swap / zram compression | Mission Center 1.2 | P2 || ✅ |
| B4 | System pressure (PSI) for CPU, memory and disk: is the PC actually struggling right now | glances | P2 || ✅ |
| B5 | Uptime nudge: restart recommended after two weeks up | | P2 || ✅ |
| B6 | Longer history (1 h / 24 h) kept by the background service | Cockpit metrics, netdata | P3 | ⏳ |
| B7 | NPU usage | Resources 1.7 | P3 | ⏳ (no NPU on ashu-pc) |

## C. Cleanup

| ID | Missing feature | Like | Pri | Status |
|---|---|---|---|---|
| C1 | **Never-clean list**: exclude any item or category permanently | BleachBit whitelist, CCleaner | P1 || ✅ |
| C2 | Measure what was really freed (disk free before/after), not just the estimate | PC Manager report | P1 || ✅ |
| C3 | Cleanup history list on the page | CleanMyMac | P2 || ✅ |
| C4 | **Unknown big caches**: anything large in `~/.cache` the other categories don't recognise | BleachBit | P1 || ✅ |
| C5 | **VS Code / Cursor workspace storage for folders that no longer exist** (often GBs) | | P1 || ✅ |
| C6 | More developer caches: Flutter/Dart pub, Composer, Ruby gems/bundler, Homebrew, Gradle wrapper old versions, Android emulator images, Unity/Godot caches, Maven | | P2 || ✅ |
| C7 | Weekly auto-clean: choose which safe categories it includes | CleanMyMac maintenance | P2 || ✅ |
| C8 | Similar (not identical) photos | Czkawka, CleanMyMac My Clutter | P2 || ✅ |
| C9 | Empty folders and empty files | Czkawka | P2 || ✅ |
| C10 | Browser history and cookies per browser (off by default, with clear warnings) | BleachBit, CCleaner | P3 | ⏳ (risk of logging you out of everything; caches already covered) |
| C11 | Shred files / wipe free space | BleachBit | P3 | ✗ on SSDs (TRIM already erases freed blocks; overwriting only wears the SSD) |
| C12 | Remove unused language files (localepurge) | BleachBit | P3 | ✗ (breaks apt's view of packages; saves little) |
| C13 | Vacuum browser databases | BleachBit | P3 | ⏳ |

## D. Updates and software sources

| ID | Missing feature | Like | Pri | Status |
|---|---|---|---|---|
| D1 | **Undo an apt change** using APT 3's history (Ubuntu 26.04): undo the last install/upgrade/removal, or roll back to a point | APT 3.2 history | P1 || ✅ |
| D2 | **Software sources manager**: list repositories and PPAs, turn on/off, remove, add a PPA | Stacer, Software & Updates | P1 || ✅ |
| D3 | **Kernels**: list installed kernels, which one is running, remove old ones safely | Mainline, Ubuntu Cleaner | P1 || ✅ |
| D4 | **Drivers**: detect proprietary drivers (NVIDIA, Wi-Fi, firmware) and install the recommended one | Additional Drivers | P1 || ✅ |
| D5 | Hold / unhold a package (keep it at its version) | Synaptic | P2 || ✅ |
| D6 | Changelog of an update ("what does this update change?") | Software Updater | P2 || ✅ |
| D7 | Take a Timeshift snapshot before a big update | Timeshift + apt hook | P2 || ✅ |
| D8 | Snap: pause automatic updates, see recent snap changes | | P2 || ✅ |
| D9 | Flatpak remotes and downgrade/pin versions | Warehouse | P3 | ⏳ |
| D10 | Pick the fastest download mirror | Software & Updates | P3 | ⏳ |

## E. Apps

| ID | Missing feature | Like | Pri | Status |
|---|---|---|---|---|
| E1 | **Install from a file** (.deb, .flatpakref, AppImage) with a file picker | App Center | P1 || ✅ |
| E2 | AppImage integration: make it executable and add it to the app grid | Gear Lever | P2 || ✅ |
| E3 | Uninstall several apps at once | Stacer, Warehouse | P2 || ✅ |
| E4 | App permissions: snap connections and Flatpak permissions in the app's details | Flatseal | P2 || ✅ |
| E5 | Same app installed twice (e.g. snap and deb) | | P2 || ✅ |
| E6 | Last used / unused apps | CleanMyMac Applications | P2 || ✅ |
| E7 | Default terminal choice (Ghostty / Ptyxis) | | P2 || ✅ |
| E8 | Leftover settings folders of uninstalled apps in `~/.config` | CleanMyMac uninstaller | P3 | ⏳ (hard to match folders to apps reliably) |
| E9 | App updater for non-store apps (AppImages) | CleanMyMac updater | P3 | ⏳ |

## F. Startup and boot

| ID | Missing feature | Like | Pri | Status |
|---|---|---|---|---|
| F1 | **Boot menu (GRUB) settings**: show menu, timeout, default entry, remember last choice, quiet splash | GRUB Customizer | P1 || ✅ |
| F2 | Delay a login app by N seconds | Startup Applications | P2 || ✅ |
| F3 | Boot chart picture and the critical chain | systemd-analyze | P2 || ✅ |
| F4 | Your user services that start at login | Cockpit | P2 || ✅ |
| F5 | Startup impact (how long each login app takes) | Windows Task Manager | P3 | ⏳ |

## G. Processes

| ID | Missing feature | Like | Pri | Status |
|---|---|---|---|---|
| G1 | **Efficiency mode**: lowest CPU and disk priority for a hog in one click | Windows Task Manager | P1 || ✅ |
| G2 | Tree view (parent → children) | GNOME System Monitor, htop | P2 || ✅ |
| G3 | Disk read/write per process | Mission Center | P2 || ✅ |
| G4 | End several processes at once | | P2 || ✅ |
| G5 | Network usage per process | Mission Center 1.2, nethogs | P3 | ⏳ (needs root/eBPF helper) |
| G6 | CPU limit for an app (cgroup quota) | | P3 | ⏳ |

## H. Storage and files

| ID | Missing feature | Like | Pri | Status |
|---|---|---|---|---|
| H1 | **Drives and partitions**, mount / unmount / safely remove USB drives | GNOME Disks, Cockpit | P1 || ✅ |
| H2 | **Readable drive health** (SMART JSON: passed/failed, temperature, power-on hours, SSD wear %) instead of raw output | GNOME Disks, CrystalDiskInfo | P1 || ✅ |
| H3 | Trash viewer: what's in it, restore or delete single items | | P2 || ✅ |
| H4 | Treemap of a folder ("Space Lens") | CleanMyMac Space Lens, Baobab | P2 || ✅ |
| H5 | Breakdown by file type (videos, photos, music, documents, archives, code) | Windows Storage settings | P2 || ✅ |
| H6 | Swap: see and resize the swap file | | P2 || ✅ |
| H7 | Quick disk speed test | GNOME Disks benchmark, hardinfo2 | P2 || ✅ |
| H8 | Folder growth over time | | P3 | ⏳ |
| H9 | Network shares (SMB/NFS) | Cockpit | P3 | ⏳ (Files does this) |

## I. Network

| ID | Missing feature | Like | Pri | Status |
|---|---|---|---|---|
| I1 | **Active connections**: which app talks to which address right now | Resource Monitor, Little Snitch | P1 || ✅ |
| I2 | **DNS switcher**: Automatic, Cloudflare, Google, Quad9, AdGuard (blocks ads) | | P1 || ✅ |
| I3 | VPN connections: connect / disconnect; Tailscale/WireGuard status | | P2 || ✅ |
| I4 | Saved Wi-Fi: forget, show password | | P2 || ✅ |
| I5 | Wi-Fi hotspot on/off | GNOME Settings | P2 || ✅ |
| I6 | Devices on your network ("who's on my Wi-Fi") | Fing | P2 || ✅ |
| I7 | Per-app bandwidth, data usage history | nethogs, vnStat | P3 | ⏳ |
| I8 | Traceroute / mtr tools | | P3 | ⏳ |

## J. Power and hardware

| ID | Missing feature | Like | Pri | Status |
|---|---|---|---|---|
| J1 | **Battery history graph** (charge over time) | Mission Center 1.2, GNOME Power Statistics | P1 || ✅ |
| J2 | **Keep awake** for N hours (stop sleep/screen blank) | Caffeine | P1 || ✅ |
| J3 | **Shutdown / restart / suspend timer** with cancel | | P1 || ✅ |
| J4 | CPU speed, governor, turbo and thermal throttling status | auto-cpufreq, TLP | P2 || ✅ |
| J5 | Devices: USB, PCI, audio, Bluetooth, displays, memory modules | hardinfo2, lshw | P2 || ✅ |
| J6 | Lid close / power button behaviour | | P3 | ⏳ |
| J7 | CPU/GPU benchmark | hardinfo2 | P3 | ⏳ |

## K. Logs and crashes

| ID | Missing feature | Like | Pri | Status |
|---|---|---|---|---|
| K1 | Kernel messages tab (hardware, drivers, USB) | dmesg, Cockpit | P2 || ✅ |
| K2 | Live follow (new messages appear as they happen) | Cockpit, journalctl -f | P2 || ✅ |
| K3 | Journal size and "keep only N MB" control | | P2 || ✅ |
| K4 | Report a crash to Ubuntu | ubuntu-bug | P3 | ⏳ |

## L. Services and scheduled tasks

| ID | Missing feature | Like | Pri | Status |
|---|---|---|---|---|
| L1 | **Keep a script running / run it on a schedule** (creates a user service or timer: "start my bot at login and restart it if it crashes") | pm2, Cockpit | P1 || ✅ |
| L2 | Cron jobs viewer | | P2 || ✅ |
| L3 | Block / unblock (mask) a service | Cockpit | P2 || ✅ |
| L4 | Memory used by each service | Mission Center, Cockpit | P2 || ✅ |
| L5 | Edit service overrides | Cockpit | P3 | ✗ (expert-only, easy to break boot) |

## M. Security

| ID | Missing feature | Like | Pri | Status |
|---|---|---|---|---|
| M1 | **Secrets check**: API keys/tokens in shell history, `.env` files not ignored by git, private keys inside projects, plaintext `~/.git-credentials`, readable credential files (`~/.aws`, `~/.npmrc`, `~/.docker/config.json`, `~/.netrc`) | gitleaks, trufflehog | P1 || ✅ |
| M2 | **Docker ports bypass the firewall** warning (a very common dev surprise) | | P1 || ✅ |
| M3 | SSH server hardening check (password login, root login) | Lynis | P2 || ✅ |
| M4 | AppArmor status | Lynis | P2 || ✅ |
| M5 | Virus scan of Downloads (ClamAV) | CleanMyMac Protection | P2 || ✅ |
| M6 | User accounts: who can log in, who is admin, last login | Cockpit Accounts | P2 || ✅ |
| M7 | Ubuntu security status / CVEs (`pro security-status`) | | P3 | ⏳ |
| M8 | USB device allow-listing | USBGuard | P3 | ✗ (can lock you out of your keyboard) |

## N. Privacy

| ID | Missing feature | Like | Pri | Status |
|---|---|---|---|---|
| N1 | **Developer tool telemetry off**: Next.js, .NET, VS Code, Nuxt, Gatsby, Astro, Angular, Turborepo, Homebrew, Azure CLI, Netlify, Storybook… in one switch | | P1 || ✅ |
| N2 | File search indexing: on/off, reset index | GNOME Settings | P2 || ✅ |
| N3 | Remove photo location/EXIF data | Czkawka Exif remover, mat2 | P3 | ⏳ |
| N4 | Turn the webcam off at driver level | | P3 | ⏳ |

## O. Tweaks and desktop

| ID | Missing feature | Like | Pri | Status |
|---|---|---|---|---|
| O1 | **GNOME extensions manager**: list, on/off, settings, remove | Extension Manager | P1 || ✅ |
| O2 | **Ctrl+Shift+Esc opens Processes** (like Windows) and other custom shortcuts | Windows | P1 || ✅ |
| O3 | **Dock settings**: position, icon size, auto-hide, click to minimise, show Trash/drives | Dash to Dock settings | P1 || ✅ |
| O4 | Files app options: hidden files, folders first, permanent delete key, thumbnails | Tweaks | P2 || ✅ |
| O5 | Window buttons (minimise/maximise), clock 24h | GNOME Tweaks | P2 || ✅ |
| O6 | Computer name (hostname), time zone, automatic time | Cockpit overview | P2 || ✅ |
| O7 | Font install/list | GNOME Tweaks | P3 | ⏳ |
| O8 | Catppuccin flavour switcher for terminal/editors | | P3 | ⏳ |

## P. Developer

| ID | Missing feature | Like | Pri | Status |
|---|---|---|---|---|
| P1 | **PATH doctor**: missing folders, duplicates, which `node`/`python` wins | | P1 || ✅ |
| P2 | **Docker disk usage**: images, volumes, build cache with per-type cleanup | Docker Desktop | P1 || ✅ |
| P3 | **GitHub connection**: `gh` login status, SSH test to GitHub, upload your SSH key | GitHub Desktop | P1 || ✅ |
| P4 | **Git identity & defaults**: name, email, default branch `main`, pull strategy, editor | GitHub Desktop | P1 || ✅ |
| P5 | Global packages: npm -g, pipx/uv tools, cargo installs, with uninstall | | P2 || ✅ |
| P6 | Fetch all projects / list repos with unpushed work | | P2 || ✅ |
| P7 | Stop all dev servers | | P2 || ✅ |
| P8 | Install a Python version with uv | | P2 || ✅ |
| P9 | Local HTTPS certificates (mkcert) | | P3 | ⏳ |

## Q. Maintenance, backup and recovery

| ID | Missing feature | Like | Pri | Status |
|---|---|---|---|---|
| Q1 | **System report** (one HTML file with specs, health, disks, updates, errors) to keep or send when asking for help | Cockpit diagnostic reports, hardinfo2 | P1 || ✅ |
| Q2 | **Troubleshooters**: fix sound, Wi-Fi, Bluetooth, clock, broken apt, stuck desktop settings, icon/font caches | Windows troubleshooters | P1 || ✅ |
| Q3 | Health score history (graph over weeks) | | P2 || ✅ |
| Q4 | Timeshift snapshot list and delete | Timeshift | P2 || ✅ |
| Q5 | Copy your home folder to a USB drive | Déjà Dup, Pika | P3 | ⏳ (Déjà Dup/Pika already do it well; linked) |

## R. Terminal `pc`

| ID | Missing feature | Pri | Status |
|---|---|---|---|
| R1 | Tab completion for zsh and bash | P1 || ✅ |
| R2 | `pc slow`, `pc secrets`, `pc report`, `pc watch` (same engines as the app) | P2 || ✅ |
| R3 | `--json` output for scripting | P3 | ⏳ |

## S. Safety, reliability, testing

| ID | Missing feature | Pri | Status |
|---|---|---|---|
| S1 | **Ubuntu 26.04 Rust coreutils**: use GNU `du` when present (`gnudu`) and fall back to a Python walk, so sizes never come back empty | P1 || ✅ |
| S2 | Extra confirmation for very large deletions (over 10 GB) | P2 || ✅ |
| S3 | Automated GUI smoke test in the repo (every page opens, both themes) | P2 || ✅ |
| S4 | Packaging as a .deb | P3 | ⏳ |

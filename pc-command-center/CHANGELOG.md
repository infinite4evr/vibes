# Changelog

## Unreleased

- The project moved in the `vibes` repository: the app is now `pc-command-center/` (formerly `linux-setup/pc/`) and the setup scripts are `ubuntu-setup/` (formerly `linux-setup/`). The installer finds the app next to it; the app's self-update and Maintenance page look for `ubuntu-setup` and still accept the old layout. Running `bash ubuntu-setup/setup.sh pc` once also points the `cleanup`, `scan` and `tips` aliases at the new folder.
- Debug logging now writes its file even when another log handler (e.g. a test runner's) is attached first, and turning it off releases the file.
- CI runs for the first time: the workflow moved to the repository root as `.github/workflows/pc-command-center.yml`.
- Fixed an out-of-date test for the uv install fallback. Tests: 219 passed, 2 GTK screenshot tests skipped without a display.

## 2.2.6 — every admin action was reported as failed

- **Actions that need your password always "failed" on their last step** (GitHub issues 12, 13, 14: *Update everything*, *Check for updates*, *Clean up*). The commands themselves ran and succeeded. The private admin batch ends each step with a Stop check written as `[ "$(cat flag)" = 1 ] && exit 130`. When Stop was not pressed, that test is false and was the script's last command, so the batch exited 1. The runner then marked the final step failed and showed the error dialog. The check is now an `if … fi`, and the script ends with `exit 0`. New tests run a batch with the Stop flag both clear and set.
- **Every error opens the error dialog with "Create GitHub issue"**, however small. Desktop app: toasts that report a failure ("Couldn't change it: …", "Error: …", "… failed") and background-task errors now open the error dialog instead of a passing toast (`core/bugreport.is_error_text`). The button was "Report on GitHub" and is now "Create GitHub issue" everywhere. Terminal app: new `ErrorScreen` (error, **Create GitHub issue** opening the pre-filled redacted issue in the browser, or showing and copying the link without one, and **Copy details**). It opens for every error notification and every failed action, and repeats are counted in the open dialog. Tests: `tests/test_tui_errors.py`.

## 2.2.5 — production pass (verified on real Ubuntu 26.04 + GTK 4/libadwaita 1.9)

Earlier releases could only be checked on a build host without GTK. This pass ran the desktop app, every one of its 55 tabs, the terminal UI and every CLI command on real hardware, and fixed what that exposed.

- **New: report any error on GitHub.** Every unexpected error now opens a small "Something went wrong" dialog instead of a toast or a silent log line. This covers crashes in UI callbacks, background-task failures, live-refresh failures, pages that fail to load and failures in other threads. The dialog has **Report on GitHub** (a pre-filled issue on `infinite4evr/vibes` with the redacted error, last day's error log, debug log tail and app/OS/GTK versions), **Copy details** and **Save full log** (private 0600 file in Downloads). Repeats of the same error fold into the open dialog instead of stacking. Failed actions (not user-cancelled) get a **Report on GitHub** button. `pc` and the terminal app print the same link if they crash. The link trims the log to fit GitHub's URL limit while always keeping the end of the traceback (`core/bugreport.py`, `gui/errors.py`).
- **Share-mode redaction no longer erased timestamps.** The report's IPv6 pattern matched any `08:37:12` clock time (and only half-masked real IPv6 addresses). It now matches only full or `::`-compressed IPv6.
- **Network page crashed on open.** `NetworkPage.connect()` (the Wi-Fi "Connect" handler) shadowed `GObject.connect`, so building the page raised `TypeError` and the sidebar showed the "could not be loaded" fallback. Renamed to `connect_wifi`; a test now rejects any GUI class that overrides GObject's signal API.
- **The responsive layout never ran.** Window/sidebar clamping, compact header search and page margins were wired to `notify::width`, a property GTK 4 widgets don't have. They now react to real size allocations (deferred to idle so they never re-enter layout).
- **Wi-Fi passwords were visible to other users.** Joining a network ran `nmcli dev wifi connect … password <psk>`, exposing the password in `/proc/<pid>/cmdline` (and, in the terminal UI, in run/audit output). New `network.wifi_connect()` creates the profile without a secret and supplies it through a private 0600 `passwd-file` that is deleted afterwards; a failed join removes the half-made profile. WPA3-only networks use SAE; enterprise/WEP networks point to Ubuntu Settings.
- **`pc network-check` always said the router doesn't answer.** It pinged the display string `"192.168.1.1 (wlp0s20f3)"`. Sub-millisecond replies are no longer treated as "no reply" either.
- **"Why is my PC slow?" always claimed updates were installing.** The idle `unattended-upgrade-shutdown --wait-for-signal` helper was counted as an upgrade in progress.
- **Two sets of window controls.** Both header bars drew minimise/maximise/close; the sidebar header no longer does (the content header shows start-side controls only while the sidebar is hidden), which also stops the app name being truncated.
- **Cut-off tab labels** ("History & …", "Wi-Fi & D…") — tabs now switch to icon-over-label based on the real label lengths.
- Missing `lightbulb-symbolic` icon (Advisor) replaced with a stock icon; a test checks every symbolic icon exists in Ubuntu's themes.
- Screenshot/test runs no longer read or overwrite the user's saved window state (they opened maximised and ignored `--width/--height`).
- Doctor's junk line no longer says "Only X" for what is a quick partial probe; unknown battery cycle counts say "Not reported" instead of "?".
- GUI smoke test now covers the Configuration page; Ruff is clean (`B905` intentionally ignored).
- Validation on Ubuntu 26.04.1 (Python 3.14, GTK 4 / libadwaita 1.9): `pytest` 265 passed, 0 skipped (GTK screenshot tests included); `ruff check` clean. All 17 pages and every tab were driven at 1320×860 and 780×540 with no errors, the terminal app ran through all 14 panels at 140×45 and 90×30, and every read-only `pc` subcommand was run on real hardware.

## 2.2.4 — compact-window shell/layout hotfix

- Fixed the remaining compact/fractional-scale shell problem visible on 1366x768-class laptops: the sidebar could still consume too much usable width and page/header controls could be crowded out.
- Sidebar default/max reduced to 235/300 px and dynamically capped to ~28% of the real window while reserving at least 650 px for content when possible.
- Navigation and brand labels now ellipsize instead of increasing the sidebar's minimum width.
- Added a compact top-header mode: when the content pane is narrow, the wide search entry becomes an explicit search button instead of disappearing inside `Adw.HeaderBar`; Ctrl+K remains available.
- Page title/action headers now wrap instead of forcing one rigid horizontal line.
- Page margins tighten at compact widths and scrolled pages no longer propagate an oversized natural width into the shell.
- Added three non-GTK regression contracts for content-aware sidebar sizing, compact search reachability, and wrapping page headers.
- Validation: 216 tests passed, 2 GTK screenshot tests skipped on this packaging host because PyGObject/libadwaita are unavailable.

## 2.2.3 — installer/version reliability hotfix

- Installer now prints the source version before installing the GTK app.
- Installer verifies the private GUI copy reports the same version after installation.
- Detects an already-running PC Command Center and clearly warns that the old process must be fully quit/reopened before About can reflect newly installed code.
- `pc-gui --version` now reports the GUI build version.
- Prevents a stale running single-instance process from being mistaken for a failed update.

## 2.2.2 — sidebar/page-loading hotfix

- Fixed the v2.2.1 responsive-layout regression that made several GTK pages fail during construction and disappear from the sidebar.
- Extended the shared `flow()` helper to support independent `column_spacing` / `row_spacing` overrides used by the responsive UI pass.
- Restored the missing Storage, Network, Power, Logs, Developer and Maintenance navigation/pages; also prevents lazy controls on Services, Security, Tweaks and Updates from hitting the same argument mismatch.
- Page construction failures no longer silently hide navigation rows. A visible fallback page now shows diagnostic details while keeping the rest of the app usable.
- Page import failures are also represented in navigation instead of leaving empty section headers.
- Tightened persisted/resized sidebar width to a 210–330 px range while reserving at least 560 px for page content when possible.
- Added non-GTK regression tests for sidebar route/module consistency, responsive helper keyword compatibility, and no-silent-hide behavior.
- Validation: 211 tests passed, 2 GTK screenshot tests skipped on this build host because PyGObject/libadwaita are unavailable.

## 2.2.1 — full UI responsiveness and interaction bug-fix pass

- Reworked rigid action/filter rows across all high-density GTK pages into responsive wrapping layouts.
- Fixed duplicate entries in the Ctrl+K command palette.
- Replaced slide-style shell motion with gentle crossfades; Full/Reduced/Off now use 180/90/0 ms.
- Made the resizable sidebar content-safe: it stays within a useful range and preserves room for the active page.
- Fixed narrow-window clipping in dashboard cards, cleanup charts, storage tools, network port controls, services, PM2, logs, power controls, update history and more.
- Made horizontal bar charts allocate their label/value gutters from the real available width instead of a fixed label gutter.
- Reduced oversized welcome/task/script dialogs so they fit common laptop displays more comfortably.
- Extended GTK screenshot smoke coverage to exercise all 16 pages at compact (920×620) and full (1320×860) sizes.

## 2.2.0 — safety, diagnostics and interface polish

- Added a live Background Tasks centre with stop controls and scheduled-job controls.
- Added an opt-in rotating debug logger and redacted support-bundle export.
- Added collapsible/resizable sidebar state and Full/Reduced/Off interface motion.
- Hardened privileged batches: exact accepted exit codes, private 0600 scripts, process-group cancellation, and critical-step cancellation guards.
- Added secret-aware command rendering/redaction, including hotspot credentials.
- Hardened settings restore against traversal, links, devices/FIFOs and archive bombs; added pre-restore backup.
- Made swap-file resizing transactional with rollback of the old swap on activation failure.
- Added atomic/private application-state writes in security-sensitive paths.
- Hardened bootstrap downloads to HTTPS/TLS and syntax-check downloaded scripts before execution.
- Strengthened the polkit helper's script ownership/link/mode checks.
- Added direct pytest source-path configuration and execution-safety regression tests.

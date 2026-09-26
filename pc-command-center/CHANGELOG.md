# Changelog

## Unreleased

- The project moved in the `vibes` repository: the app is now `pc-command-center/` (formerly `linux-setup/pc/`) and the setup scripts are `ubuntu-setup/` (formerly `linux-setup/`). The installer finds the app next to it; the app's self-update and Maintenance page look for `ubuntu-setup` and still accept the old layout. Running `bash ubuntu-setup/setup.sh pc` once also points the `cleanup`, `scan` and `tips` aliases at the new folder.
- Debug logging now writes its file even when another log handler (e.g. a test runner's) is attached first, and turning it off releases the file.
- CI runs for the first time: the workflow moved to the repository root as `.github/workflows/pc-command-center.yml`.
- Fixed an out-of-date test for the uv install fallback. Tests: 219 passed, 2 GTK screenshot tests skipped without a display.

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

# Changelog

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

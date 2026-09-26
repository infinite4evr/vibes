# Changelog

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

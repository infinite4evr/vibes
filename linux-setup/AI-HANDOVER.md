# PC Command Center / linux-setup — Complete AI Handover

**Authoritative handover for the current repository**  
**Release:** `2.2.4`  
**Handover date:** 26 September 2026  
**Primary product:** PC Command Center (GTK 4 + libadwaita desktop application)  
**Also included:** Textual terminal UI, `pc` CLI, Ubuntu setup/cleanup shell scripts  
**Current automated verification:** **216 passed, 2 skipped** (`pytest -q -rs`)  
**Important:** This file supersedes the older `docs/HANDOVER.md`. Start here before modifying the project.

---

## 0. Read this first

This repository began as an Ubuntu cleanup/setup script and grew into a full local PC-management suite. It now contains:

1. **PC Command Center** — the main GTK 4/libadwaita application.
2. **`pc` terminal UI** — a Textual full-screen application.
3. **`pc` CLI** — quick diagnostic/maintenance subcommands.
4. **Background jobs** — weekly maintenance, periodic alerts, live-log following, Keep Awake, and other jobs launched by the app.
5. **`linux-setup` shell tooling** — the older/bootstrap setup/cleanup layer used to prepare an Ubuntu machine and install PC Command Center.

The current `2.2.0` work was primarily a **security, execution-safety, diagnostics, background-task-control, reliability, and UI-shell upgrade**. It did **not** attempt to blindly implement every idea from the large feature audit. Some future ideas require real hardware, distribution-specific integration, or a redesigned privileged service and are deliberately left for later.

If another AI takes over, do **not** assume that “everything in the audit is implemented.” Use these files as the truth:

- `AI-HANDOVER.md` — current architectural/status handover.
- `CHANGELOG.md` — release-level change log.
- `docs/V2.2-AUDIT-IMPLEMENTATION.md` — concise list of v2.2 changes.
- `docs/FEATURE-AUDIT.md` — feature inventory and historical backlog.
- source code and tests — final authority if documentation differs.

---

## 0.0.3 2.2.4 compact-window shell/layout hotfix (2026-09-26)

A second real-machine screenshot showed that restored navigation was not the end of the UI problem: at compact logical widths/fractional scaling, the resizable sidebar still consumed too much content space, page title/action rows could enforce excess width, and the wide header search could be crowded out. 2.2.4 makes the shell content-aware: sidebar width is capped both absolutely and proportionally, page headers wrap, page margins tighten, navigation text ellipsizes, and a compact search button replaces the wide search field when the content pane is narrow. See `docs/COMPACT-LAYOUT-HOTFIX-2.2.4.md`.

Packaging-host validation: **216 passed, 2 skipped** (GTK screenshot tests require a GTK/libadwaita runtime not present here).

## 0.2 2.2.2 sidebar/page-loading hotfix (2026-09-26)

The first 2.2.1 UI package had a serious GTK runtime regression that was not caught on the build host because GTK/PyGObject was unavailable there and the renderer smoke tests were skipped. The responsive `flow()` helper only accepted a single `spacing=` keyword, while several newly converted page layouts passed `column_spacing=` and `row_spacing=`. Those pages raised `TypeError` during construction; the shell then hid their navigation rows, which produced empty **Develop**/**Care** sections and removed several **Monitor** pages.

2.2.2 fixes the root cause and hardens the shell against recurrence:

- `flow()` now explicitly supports independent horizontal and vertical spacing overrides;
- Storage, Network, Power, Logs, Developer and Maintenance construct again, and lazy responsive controls elsewhere use the same corrected helper contract;
- page construction failures no longer call `row.set_visible(False)`; a visible diagnostic fallback page is inserted instead;
- page import failures also keep a navigation entry rather than leaving an empty section;
- sidebar width is clamped to 210–330 px and old persisted oversized widths are normalized;
- three non-GTK source-contract tests were added so this class of regression is caught even when renderer tests cannot run.

Validation on the packaging host: **211 passed, 2 skipped**. The two skips remain the real GTK screenshot tests because this environment does not provide PyGObject GTK 4/libadwaita. Run those tests on Ubuntu/CI with Xvfb before treating visual rendering as fully validated.

## 0.0.2 2.2.3 installer/version reliability hotfix (2026-09-26)

The installer now prints and verifies the GUI source/installed version and warns when an already-running single-instance GUI is still holding an older build in memory. `pc-gui --version` is available for verification. See `docs/INSTALLER-VERSION-HOTFIX-2.2.3.md`.

## 0.1 2.2.1 UI bug-fix pass (2026-09-26)

A complete GTK UI responsiveness pass was performed after 2.2.0. The detailed page-by-page record is in `docs/UI-AUDIT-2026-09-26.md`. Key points:

- rigid multi-control rows were converted to wrapping layouts across the high-density pages;
- the Ctrl+K palette duplicate-action bug was fixed;
- slide motion was replaced with gentle crossfades (180/90/0 ms for Full/Reduced/Off);
- the resizable sidebar is now content-safe and capped around 210–380 px while preserving page width;
- HBars charts now size their gutters from real allocation;
- welcome/task/script dialogs were made friendlier to laptop-height screens;
- GTK screenshot smoke coverage now includes compact 920×620 and full 1320×860 layouts.

Local non-GTK test result for this patch: **208 passed, 2 skipped**. The two skips are the GTK renderer tests because the build container lacks PyGObject GTK/libadwaita; CI/Ubuntu+Xvfb remains the renderer validation path.

# 1. Executive summary

## What the project was before this audit

Before the v2.2 hardening pass, the application was already feature-rich. Version 2.1 had roughly sixteen GTK pages and covered:

- system dashboard and resource monitoring,
- cleanup,
- package/firmware updates,
- installed applications,
- startup/boot,
- processes,
- storage and disks,
- networking,
- power/hardware,
- logs,
- services and scheduled scripts,
- security,
- privacy,
- GNOME tweaks,
- developer tooling,
- maintenance/backups/troubleshooting.

The project also already had a Textual TUI and CLI, plus shell setup/cleanup scripts.

The **main weakness was not lack of features**. It was that a tool with this much system-management power needed stronger execution boundaries, safer persistence, better cancellation semantics, first-class diagnostic logging, and a unified view of work running in the background.

## What was found in the audit

The highest-impact findings were:

1. **Privileged batch return-code bug.** A root batch step that allowed one non-zero return code could accidentally permit any non-zero code to continue the privileged batch.
2. **Admin batch permissions mismatch.** Temporary privileged scripts were changed to `0644` even though the intended model/documentation said `0600`.
3. **Credential leakage path.** Sensitive values such as hotspot passwords could appear in command display/history because values were passed in argv and command rendering was not secret-aware.
4. **Unsafe cancellation semantics.** Killing package/boot/filesystem commands in the middle can leave a system inconsistent.
5. **No unified background-process/task UI.** Users could not see/control all work launched by PC Command Center from one place.
6. **No purpose-built detailed debug mode/support bundle.** Troubleshooting required scattered logs rather than an opt-in, privacy-redacted diagnostic log.
7. **Restore extraction needed stronger hardening.** Archive path checks alone were not enough; symlink/hardlink/special-file and pre-existing-symlink cases needed explicit defense.
8. **Swap resize needed transactional behavior.** A partial failure around `swapoff`, replacement, activation, or `/etc/fstab` could be risky.
9. **Local state writes were inconsistent.** Several state/log files needed private permissions and atomic replacement.
10. **Cleanup path safety needed symlink-boundary protection.** A path lexically under HOME is not necessarily physically under HOME.
11. **Installer/download paths needed stronger handling.** Pipe-to-shell/download validation patterns should be minimized and downloads should be validated before execution.
12. **UI shell was not as flexible/polished as requested.** Sidebar was effectively fixed; motion/transition behavior was not user-configurable.
13. **Test ergonomics were weaker than they should be.** Plain `pytest` required manual `PYTHONPATH=src` in some contexts.
14. **Coverage was uneven in high-risk modules.** The suite was healthy but some operational modules had much lower direct coverage than parser-heavy modules.

## Where it stands now

Version `2.2.0` now has:

- exact privileged return-code enforcement,
- private `0600` admin batches,
- stricter `pc-admin` validation,
- first-class secret-aware command rendering/redaction,
- opt-in rotating debug logs,
- redacted support-bundle generation,
- an in-app Background Tasks centre,
- process-group cancellation,
- safe “stop after current critical step” behavior,
- tracked Python worker tasks,
- tracked live-log task,
- scheduled-alert/checkup controls in the task UI,
- Keep Awake control in the task UI,
- collapsible and resizable sidebar,
- Full / Reduced / Off motion modes,
- stronger restore extraction,
- pre-restore backups,
- safer swap-file resizing,
- atomic/private local state helpers,
- cleanup symlink-boundary protection,
- safer bootstrap download handling,
- better CI/test setup,
- additional execution-safety regression tests,
- release/security/contribution documentation.

Automated validation at handover time:

```text
211 passed, 2 skipped
```

The two skipped tests are the local GTK smoke tests when a display + GTK/libadwaita Python runtime are unavailable. CI includes an Ubuntu/Xvfb GTK smoke job for that reason.

---

# 2. User requirements that drove v2.2

These were explicit requirements from the latest work and must be preserved:

## Debugging

The user wants an easy way to turn debugging on so the app records enough detail to reproduce problems and share logs for future fixes.

Current implementation:

- GUI preference: **Record detailed debug logs**.
- CLI: `pc --debug ...`.
- GUI launcher: `pc-gui --debug`.
- Environment override: `PC_DEBUG=1`.
- Rotating logs live under `~/.local/state/pc/logs/`.
- Support bundle can be exported from Preferences or with `pc support`.
- Logs/support bundles are private and aggressively redact known passwords/tokens/secrets.

**Do not weaken redaction to satisfy “log everything.”** The intended meaning is “log everything useful for diagnosis while refusing to turn logs into a credential archive.”

## Background process control

The user wants a UI to control background processes started by PC Command Center itself.

Current implementation:

- Header button opens **Background tasks**.
- Active task count appears as a badge.
- Command tasks expose status, PID, detail, recent output, and Stop when safe.
- Python worker threads are visible but are not force-killed because Python thread termination is unsafe.
- Persistent/scheduled jobs are represented separately:
  - background alerts,
  - weekly checkup,
  - Keep Awake.
- live `journalctl` follow is tracked as a cancellable monitor task.

This is an important invariant: **only work started/managed by PC Command Center should appear in this task centre.** It is not a generic OS process manager; the separate Processes page handles system processes.

## Sidebar

The user wants the sidebar closable and resizable.

Current behavior:

- hide/show button in the header,
- `Ctrl+Shift+S` toggles it,
- sidebar uses a paned layout and can be resized by dragging,
- last visibility and width are persisted,
- width is clamped to a practical range when restoring/showing.

## UI polish and animation

The user is UI-sensitive and wants the application to feel polished/professional rather than purely functional.

Current implementation:

- animated page transitions,
- animated sidebar reveal/hide,
- active background-task badge,
- updated CSS/card/button/hover treatment,
- persistent professional header controls,
- motion preference:
  - **Full** — normal smooth transitions,
  - **Reduced** — shorter transitions,
  - **Off** — no interface motion.

Future UI changes should respect reduced-motion/accessibility expectations.

---

# 3. Repository layout

```text
linux-setup/
├── AI-HANDOVER.md                  <-- START HERE
├── README.md
├── CHANGELOG.md
├── SECURITY.md
├── CONTRIBUTING.md
├── setup.sh                        bootstrap/menu entry point
├── .github/workflows/ci.yml
├── assets/
├── dotfiles/
├── lib/                            shell setup/clean/scan/undo helpers
├── docs/
│   ├── HANDOVER.md                 pointer to this document
│   ├── FEATURE-AUDIT.md            historical feature audit/backlog
│   └── V2.2-AUDIT-IMPLEMENTATION.md
└── pc/
    ├── pyproject.toml
    ├── README.md
    ├── data/
    │   ├── pc-admin                privileged batch helper
    │   └── io.github.infinite4evr.PcCommandCenter.policy
    ├── tests/
    │   ├── test_apps_boot.py
    │   ├── test_execution_safety.py
    │   ├── test_gui_smoke.py
    │   ├── test_maintenance.py
    │   ├── test_parsers.py
    │   ├── test_power_logs_services.py
    │   ├── test_security_privacy.py
    │   └── test_tweaks_dev.py
    └── src/pcctl/
        ├── __init__.py
        ├── cli.py
        ├── core/
        ├── gui/
        └── ui/
```

Approximate current scale at handover:

- ~35k lines of Python including tests,
- ~1.3k lines of shell,
- 93 Python source files under `pc/src/pcctl`,
- 8 test modules.

---

# 4. Product architecture

## 4.1 Core design

`pcctl.core` is intended to contain the reusable engine and **must not import GTK**.

The three front ends should reuse the same core logic:

```text
                   pcctl.core
              /        |        \
           GTK        TUI       CLI
```

In practice, UI/action orchestration is not yet perfectly centralized. The long-term architecture should continue moving toward a single action registry/executor so GUI/TUI/CLI behavior cannot drift.

## 4.2 Major core modules

| Module | Purpose |
|---|---|
| `run.py` | command probes, `Step`, Python steps, redaction hooks, CLI execution |
| `debug.py` | opt-in rotating diagnostic logging, redaction, support ZIP |
| `tasks.py` | in-process registry for PC Command Center-owned background work |
| `state.py` | private directories, atomic writes, private append |
| `system.py` | CPU/memory/disks/network/battery/process sampling |
| `junk.py` | cleanup categories and deletion behavior |
| `dupes.py` | duplicate-file analysis |
| `drives.py` | drive/SMART/mount/swap/storage actions |
| `storage.py` | folder and large-file analysis |
| `packages.py` | apt/snap/flatpak/firmware/repositories/kernels/drivers |
| `appmgr.py` | application install/uninstall/integration/permissions |
| `boot.py` | GRUB/boot analysis/startup-related behavior |
| `services.py` | systemd services, user scripts/timers, cron |
| `logs.py` | journal/crash/kernel/live-log support |
| `power.py` | battery, Keep Awake, timers, CPU/power state |
| `devices.py` | USB/PCI/audio/Bluetooth/display/memory info |
| `network.py` | Wi-Fi/DNS/VPN/ports/connections/hotspot/LAN/speed |
| `gpu.py` | GPU information/usage |
| `diagnose.py` | “Why is my PC slow?” style diagnosis |
| `security.py` | security checklist/firewall/SSH/AppArmor |
| `secrets.py` | credential leak checks |
| `privacy.py` | GNOME privacy controls |
| `devtelemetry.py` | developer-tool telemetry controls |
| `indexing.py` | GNOME search/indexing controls |
| `tweaks.py` / `desktop.py` | desktop tuning/settings |
| `extensions.py` | GNOME extension management |
| `shortcuts.py` | custom keyboard shortcuts |
| `dev.py` / `devsetup.py` | developer environment/project tooling |
| `health.py` | health checks/score |
| `maint.py` | weekly checkups, backups/restore, Timeshift integration |
| `watch.py` | periodic background alerts |
| `troubleshoot.py` | guided troubleshooters |
| `report.py` | system report generation/redaction |
| `selfupdate.py` | app self-update/uninstall/setup support |

## 4.3 GUI structure

`pcctl.gui` is the primary product UI.

Important files:

| File | Responsibility |
|---|---|
| `main.py` | application entry point, debug startup, crash guard, screenshot mode |
| `window.py` | main shell, sidebar, header, page stack, shortcuts, task button |
| `runner.py` | GTK command/action executor and privileged batching |
| `taskcenter.py` | Background Tasks dialog |
| `preferences.py` | UI preferences including motion/debug/support bundle |
| `prefs.py` | persistent GUI preferences |
| `activity.py` | action/error history |
| `dialogs.py` | confirmation/result dialogs |
| `style.css` | GTK styling |
| `theme.py` | appearance/theme setup |
| `util.py` | GTK helpers including tracked worker threads via `bg()` |
| `pages/*.py` | feature pages |

## 4.4 Terminal UI

`pcctl.ui` is the Textual application. It has panels for most major areas but can still drift behind the GTK app.

Long-term recommendation: make both front ends render the same declarative Action objects rather than manually wiring actions twice.

## 4.5 CLI

Main entry point:

```bash
pc
```

Useful commands currently include:

```text
pc status
pc doctor
pc slow
pc clean [--dry-run] [--deep] [--all]
pc update [--firmware]
pc ports [--all]
pc kill-port PORT
pc big [PATH]
pc repos
pc info
pc logs
pc services
pc maintain --on|--off|--auto
pc backup
pc fix ...
pc secrets [--json]
pc report ...
pc watch ...
pc awake ...
pc telemetry ...
pc completions bash|zsh
pc support
pc gui [page]
```

Global diagnostic option:

```bash
pc --debug status
```

GUI diagnostic option:

```bash
pc-gui --debug
```

---

# 5. Detailed “before → change → now” record

This section is specifically written for a future AI that needs to understand **why** v2.2 code looks the way it does.

## 5.1 Privileged return-code handling

### Before

Root commands were grouped into a temporary shell script. The batching logic used a shortcut that effectively treated “this step accepts at least one non-zero exit code” as “non-zero exit is optional.”

That is wrong for steps with `ok_codes=(0, 10)` because exit `5` must fail, not continue.

### Change

`pc/src/pcctl/gui/runner.py`

- `build_root_batch()` now serializes the exact allowed return-code set.
- The helper shell function checks whether the actual return code belongs to that set.
- An undeclared return code aborts the root batch with status `100` unless the step itself is explicitly `optional=True`.

### Now

The behavior is covered by regression tests in:

```text
pc/tests/test_execution_safety.py
```

Tests include:

- declared non-zero code accepted,
- undeclared non-zero code rejected,
- optional failure allowed to continue.

**Invariant:** never reintroduce a generic “non-zero allowed” shortcut. Exact membership in `Step.ok_codes` matters.

---

## 5.2 Privileged batch files

### Before

Temporary admin scripts were created privately but then changed to `0644`, creating a mismatch with the intended security model and exposing command contents unnecessarily.

### Change

- privileged batch script is kept `0600`,
- cancellation flag is also `0600`,
- helper validates:
  - expected `/tmp/pc-admin-*.sh` path,
  - regular file,
  - not a symlink,
  - canonical path,
  - link count = 1,
  - ownership by `PKEXEC_UID`,
  - exact mode `0600`.

Files:

```text
pc/src/pcctl/gui/runner.py
pc/data/pc-admin
```

### Now

The helper boundary is materially safer, but **it is still a generic script-execution helper**. A future redesign should replace it with a narrowly-scoped privileged D-Bus/helper service with structured operations.

That redesign is intentionally deferred because it is architectural and must be tested on real Ubuntu/polkit systems.

---

## 5.3 Secret-aware command rendering

### Before

Some commands contained passwords in argv. For example, Wi-Fi hotspot setup passes a password to `nmcli`. Command display/history could render raw argv.

### Change

`Step` gained secret metadata:

```python
sensitive_args: tuple[int, ...]
sensitive_env: tuple[str, ...]
```

Relevant methods:

```python
Step.sensitive_values()
Step.safe_cmd()
Step.display()
Step.redact()
```

Global helpers in `core/debug.py` also redact common password/token/credential forms.

### Now

Execution still receives the real values; user-facing/logging paths receive redacted values.

Example concept:

```text
nmcli ... password <redacted>
```

instead of the real password.

**Invariant:** never log `raw_argv(step)` or raw sensitive environment values.

---

## 5.4 Debug logging and support bundle

### Before

The app had scattered state/errors/activity logs but no unified opt-in “record what happened so we can debug it later” mode.

### Change

New module:

```text
pc/src/pcctl/core/debug.py
```

Features:

- opt-in only,
- `logging.handlers.RotatingFileHandler`,
- base log forced to `0600`,
- log directory private,
- size limit: 2,000,000 bytes per log,
- 4 rotated backups,
- event logging,
- exception logging,
- argv redaction,
- environment redaction,
- support ZIP export,
- support ZIP forced to `0600`.

Default log location:

```text
~/.local/state/pc/logs/debug.log
```

Support bundle default location:

```text
~/Downloads/pc-command-center-support-YYYYMMDD-HHMMSS.zip
```

The support ZIP may contain:

```text
metadata.json
logs/debug.log*
logs/gui-errors.log
logs/activity.jsonl
```

with an additional redaction pass during export.

### User controls

GUI:

```text
Preferences → Diagnostics / Debug
```

CLI:

```bash
pc --debug status
pc support
```

GUI launcher:

```bash
pc-gui --debug
```

Environment:

```bash
PC_DEBUG=1 pc-gui
```

### Important limitations

- Redaction is **best effort**, not a mathematical guarantee that arbitrary secret formats can never appear.
- Future code that introduces new secret-bearing commands must mark sensitive args/env explicitly.
- Do not put raw SSH private keys, access tokens, Wi-Fi passwords, API keys, or authentication headers into debug messages.

---

## 5.5 Background Tasks centre

### Before

Background work was fragmented across pages/threads/subprocesses. There was no single control surface for work initiated by PC Command Center.

### Change

New registry:

```text
pc/src/pcctl/core/tasks.py
```

New UI:

```text
pc/src/pcctl/gui/taskcenter.py
```

Integration points include:

- `gui/runner.py` for command actions,
- `gui/util.py:bg()` for generic Python worker threads,
- `gui/pages/logs.py` for live log following,
- scheduled jobs exposed via `watch.py` / `maint.py`,
- Keep Awake exposed via `power.py`.

Task model contains:

```text
id
title
kind
status
detail
started
finished
cancellable
pid
recent output lines
cancel callback
```

Task statuses:

```text
running
cancelling
done
failed
cancelled
```

In-memory history is capped; finished tasks can be cleared.

### Now

The header shows a background-task button with an active-count badge. The Task Centre shows:

1. running in-session tasks,
2. scheduled/persistent PC Command Center jobs,
3. recent completed tasks.

### Important limitations

1. **Python worker threads are visible but non-cancellable.** Python does not provide a safe generic way to kill an arbitrary thread. If a worker needs cancellation, redesign that worker to periodically check a cancellation token or use a subprocess.
2. The registry is **in-process**. If the GUI exits, in-memory task history disappears.
3. Persistent systemd jobs are represented as scheduled controls, not as fully streamed task instances.
4. If future code starts detached processes outside the tracked helpers, they will not automatically appear. Integrate new background work with `tasks.start()/finish()` or the shared runner.

---

## 5.6 Cancellation safety

### Before

Stopping work could terminate the immediate process without enough awareness of whether that operation was safe to interrupt.

### Change

`gui/runner.py` now:

- launches command subprocesses in a new session,
- stops the entire process group for ordinary cancellable commands,
- maintains a list of commands that should **not** be hard-killed mid-operation,
- marks unsafe operations as “stop after current system-critical step.”

Current protected command names include package, boot, swap, filesystem, and related tools such as:

```text
apt
apt-get
dpkg
fwupdmgr
update-grub
grub-mkconfig
mkfs
mkswap
swapoff
swapon
resize2fs
xfs_growfs
fsck
```

For privileged multi-step batches, a private cancellation flag stops the batch **between** critical root commands rather than killing the current one.

### Important future improvement

This is better than unconditional termination, but the ideal model is explicit per-action phases:

```text
preflight → prepare → commit → verify → rollback
```

with cancellation policy tied to phase rather than executable-name heuristics.

---

## 5.7 Restore hardening

### Before

Settings restore used TAR extraction with path checks but needed stronger defense against archive links/special files and pre-existing symlinked destination parents.

### Change

`pc/src/pcctl/core/maint.py`

Restore now:

- limits archive member count,
- limits total extracted regular-file size,
- rejects absolute paths,
- rejects `..` traversal,
- accepts only directories + regular files,
- rejects archive symlinks/hardlinks/devices/FIFOs/sockets,
- manually extracts regular files,
- rejects pre-existing symlinked destination parents,
- prevents destination escape from HOME,
- writes via temporary file + `fsync` + atomic replacement,
- strips setuid/setgid/sticky bits,
- creates a pre-restore backup of replaced top-level data where applicable.

Regression tests include:

- archive symlink rejection,
- pre-existing symlink-parent rejection.

### Future improvement

Add a formal backup manifest, per-file SHA-256, schema version, preview/conflict UI, and selective restore.

---

## 5.8 Cleanup symlink safety

### Before

A target path that looked lexically inside HOME could be reached through a symlinked parent and physically resolve outside HOME.

### Change

Cleanup path guards were hardened so deletion does not traverse symlinked parents out of the intended boundary.

Regression behavior:

- deleting `~/cache-link/keep.txt` where `cache-link -> /outside` is rejected,
- deleting the symlink object `~/link` itself remains allowed without deleting its target.

Tests are in `test_execution_safety.py`.

---

## 5.9 Local state privacy/atomicity

### Before

Different modules wrote JSON/log/state files in different ways. Some writes could be partially written on crash/power loss and permissions were not consistently enforced.

### Change

New helper:

```text
pc/src/pcctl/core/state.py
```

Provides:

```python
private_dir()
atomic_write_text()
append_private()
```

Design goals:

- state directory mode `0700` where applicable,
- state/log file mode `0600` where sensitive,
- temp-write + `fsync` + atomic `os.replace`,
- best-effort directory `fsync` after replacement.

v2.2 moved important local state paths to these helpers.

### Future improvement

Move activity/metrics/history to SQLite with WAL and migrations if concurrency/history grows significantly.

---

## 5.10 Swap resize safety

### Before

Swap resizing was too linear for a boot/storage-sensitive operation. A failure during swapoff/replacement/reactivation/persistent config could leave the system in an undesirable state.

### Change

v2.2 reworked the flow toward a staged/validated replacement with rollback behavior.

When touching this code later, preserve these goals:

- validate target path,
- validate available disk/RAM assumptions,
- do not ignore a failed `swapoff`,
- build/validate replacement before committing persistent state,
- verify new swap activation,
- keep recovery path for previous swap,
- update `/etc/fstab` safely.

### Future improvement

Treat it as a first-class transaction with explicit preconditions/postconditions/rollback object and add VM integration tests around failure injection.

---

## 5.11 Sidebar behavior

### Before

The sidebar was effectively a fixed navigation surface.

### Change

`pc/src/pcctl/gui/window.py`

- resizable paned shell,
- sidebar wrapped in a revealer,
- persistent visibility,
- persistent width,
- header toggle button,
- `Ctrl+Shift+S`,
- animation follows motion preference.

GUI preference keys:

```json
{
  "sidebar_visible": true,
  "sidebar_width": 252
}
```

When showing, stored width is clamped to roughly `210..380` px and dynamically preserves about 480 px for page content.

---

## 5.12 Motion / animations

### Before

The UI was already styled but did not expose a motion policy and did not consistently animate the shell.

### Change

Preference:

```json
"motion": "full"
```

Allowed values:

```text
full
reduced
off
```

Current durations:

```text
Full:     ~180 ms
Reduced:  ~90 ms
Off:      0 ms
```

Used for:

- page stack crossfades,
- sidebar crossfade reveal/hide.

### Future improvement

Add restrained micro-interactions where GTK/libadwaita supports them cleanly, but avoid gratuitous motion. Respect system reduced-motion signals if available and keep the user override.

---

## 5.13 Installer/download hardening

### Before

Some bootstrap flows used convenience installer patterns that are difficult to audit, including pipe-to-shell style behavior.

### Change

v2.2 moved toward:

- HTTPS/TLS-only fetches,
- downloaded-script syntax checking before execution,
- safer `uv` fallback installation without directly piping network content into a shell.

### Future improvement

Move from “download + syntax check” to proper release trust:

```text
pinned version
SHA-256/signature verification
release manifest
SBOM
reproducible dependency lock
```

---

## 5.14 Test ergonomics and CI

### Before

Tests could require `PYTHONPATH=src` depending on invocation environment.

### Change

`pc/pyproject.toml` now includes:

```toml
[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

CI matrix:

```text
Python 3.10
Python 3.11
Python 3.12
Python 3.13
```

CI performs:

- editable dev install,
- Python compileall,
- pytest,
- shell syntax validation.

A separate GTK smoke job installs:

```text
python3-gi
python3-psutil
gir1.2-gtk-4.0
gir1.2-adw-1
xvfb
```

and renders the Dashboard to a PNG under Xvfb.

---

# 6. Current security model and invariants

Future contributors/AIs should treat these as non-negotiable unless deliberately redesigning the security model.

## 6.1 Commands shown before mutation

System-changing operations should be representable as `Step` objects so the application can show what it intends to do before execution.

## 6.2 Secrets are execution data, not display data

Sensitive args/env should be marked on the `Step` and redacted in:

- confirmation UI,
- Activity history,
- Background Task output,
- debug logs,
- support bundles,
- exceptions where possible.

## 6.3 Root scripts are private

Generated admin batch/cancel files must remain `0600`.

## 6.4 Exact return codes

`ok_codes` is an exact allowlist, not “non-zero may be okay.”

## 6.5 Critical operations are not hard-killed

Package-manager, bootloader, filesystem, swap, and firmware changes should not be interrupted blindly.

## 6.6 Cleanup must not cross path boundaries

Never assume string-prefix containment means physical-filesystem containment. Symlinks/mounts matter.

## 6.7 Restore accepts only safe archive entry types

Do not re-enable generic `tar.extractall()` over untrusted archives without equivalent filtering and path-parent validation.

## 6.8 Private diagnostic/state files

Command history, logs, support bundles, backup metadata, and similar files should default to private permissions.

## 6.9 Prefer no shell

Use argv-based subprocess execution where possible. If shell semantics are needed, make that explicit and sanitize/quote carefully.

## 6.10 Privilege boundary is still technical debt

The current pkexec helper executes a validated generated script. It is safer now, but the desired end state is a structured, allowlisted root service.

---

# 7. Debugging / support workflow for future fixes

This section matters because the user explicitly wants future AI-assisted debugging.

## Recommended user flow

1. Open **Preferences**.
2. Turn on **Record detailed debug logs**.
3. Reproduce the problem.
4. Return to Preferences.
5. Click **Create support bundle**.
6. Upload that ZIP in the next debugging conversation.
7. Turn debug logging off again if continuous detailed logging is not needed.

Alternative CLI:

```bash
pc --debug status
pc support
```

Alternative GUI launch:

```bash
pc-gui --debug
```

## Diagnostic locations

```text
~/.local/state/pc/logs/debug.log
~/.local/state/pc/logs/debug.log.1 ...
~/.local/state/pc/gui-errors.log
~/.local/state/pc/activity.jsonl
```

## What debug mode captures

The intent is to capture enough to reproduce a bug:

- app startup/lifecycle events,
- navigation/action events,
- task lifecycle,
- command names,
- redacted argv,
- exit codes,
- timing/durations,
- bounded/redacted probe output,
- redacted live action output,
- exceptions.

## What debug mode deliberately avoids

- raw known password/token/credential values,
- raw sensitive `Step` arguments,
- raw sensitive environment values,
- unbounded output.

## If logs are not enough

When adding new diagnostics:

1. add structured `debug.event()` data,
2. do not print secrets,
3. prefer identifiers/state over full file contents,
4. include timing/exit codes,
5. add a regression test if the issue is reproducible without real hardware.

---

# 8. Background-task model in detail

## In-process command tasks

Created by `gui.runner.Runner`.

Characteristics:

- cancellable where safe,
- PID visible,
- child process group used,
- recent redacted output retained,
- current step exposed in detail,
- completion status retained for recent history.

## In-process worker tasks

Created by `gui.util.bg()`.

Characteristics:

- visible in Task Centre,
- daemon Python thread,
- marked non-cancellable,
- success/failure tracked.

## Monitor tasks

Example:

- live journal follow in Logs page.

These can provide their own cancellation callback.

## Persistent scheduled jobs

The Task Centre also exposes controls for jobs created by PC Command Center itself even though they are not ordinary in-process tasks:

- background alerts (`watch`),
- weekly maintenance/checkup (`maint`),
- Keep Awake (`power`).

## Future architecture improvement

Introduce a shared `TaskController` interface for:

```text
subprocess task
cooperative Python task
systemd user service/timer
long-lived monitor
```

so all background jobs expose a consistent lifecycle:

```text
start
pause (if supported)
cancel
progress
status
logs
retry
```

Do not attempt unsafe forced thread termination.

---

# 9. GUI preferences/state

GUI preference file:

```text
~/.config/pc/gui.json
```

Current defaults from `gui/prefs.py`:

```json
{
  "appearance": "system",
  "start_page": "last",
  "refresh": "normal",
  "pause_hidden": true,
  "confirm_safe": true,
  "big_delete_gb": 10,
  "welcomed": false,
  "look": "modern",
  "debug_logging": false,
  "motion": "full",
  "sidebar_visible": true,
  "sidebar_width": 252
}
```

Meaning:

| Key | Values / purpose |
|---|---|
| `appearance` | `system`, `light`, `dark` |
| `start_page` | `last`, `dashboard`, or page id |
| `refresh` | `fast`, `normal`, `slow` |
| `pause_hidden` | pause expensive live refresh when hidden |
| `confirm_safe` | show confirmation for normal safe actions; admin/dangerous actions remain protected |
| `big_delete_gb` | extra warning threshold |
| `look` | `modern` or Catppuccin styling |
| `debug_logging` | persistent opt-in debug logger |
| `motion` | `full`, `reduced`, `off` |
| `sidebar_visible` | shell state |
| `sidebar_width` | shell width state |

Writes use private atomic state handling.

---

# 10. Keyboard / shell UX added or relevant

Important shortcuts include:

```text
Ctrl+Shift+T   Background tasks
Ctrl+Shift+S   Show/hide sidebar
Ctrl+H         Activity history
Ctrl+?         Keyboard shortcuts
Ctrl+Q         Quit
```

The app also supports direct page/action launches for GNOME search/dock integration.

Examples:

```bash
pc-gui --page cleanup
pc-gui --action maintenance:fix-sound
```

---

# 11. Current pages and capabilities

The exact UI evolves, but the current conceptual pages are:

| Page | Major capabilities |
|---|---|
| Dashboard | health, live CPU/memory/GPU/network/disk/temp/battery, PSI, slowdown diagnosis |
| Cleanup | many cleanup categories, deep scan, exclusions, history, duplicates/similar-photo-related cleanup helpers |
| Updates | apt/snap/flatpak, history/undo, drivers, sources, kernels, holds, changelogs |
| Apps | installed apps, install from file, AppImages, cleanup/defaults/permissions |
| Startup | login apps, services, boot analysis, boot menu/GRUB |
| Processes | process grouping/tree, CPU/memory/disk, efficiency/end actions |
| Storage | drives/partitions, SMART, folder analysis, big files, duplicates, file types, Trash, swap |
| Network | Wi-Fi/DNS/VPN, connections, ports, LAN devices, diagnosis, speed test, hotspot |
| Power & hardware | battery, Keep Awake, timers, CPU/thermal, attached/internal devices |
| Logs | journal problems/messages/kernel/crashes/restarts/log size/live follow |
| Services | services, custom user scripts, timers, cron |
| Security | checklist, secrets, firewall, antivirus, accounts, SSH/AppArmor-related checks |
| Privacy | GNOME privacy, telemetry, indexing/history controls |
| Tweaks | system/desktop/dock/files/extensions/shortcuts |
| Developer | projects, servers, containers, languages, Git/GitHub/tools |
| Maintenance | troubleshooters, checkups, report, backups, Timeshift/setup/update/uninstall |

Historical detailed feature inventory remains in `docs/FEATURE-AUDIT.md`.

---

# 12. Persistent files / install locations

Common locations:

| Path | Purpose |
|---|---|
| `~/.config/pc/config.json` | CLI/TUI settings |
| `~/.config/pc/gui.json` | GUI preferences |
| `~/.local/state/pc/` | app state/history/logs |
| `~/.local/state/pc/logs/` | detailed debug logs |
| `~/.cache/pc/` | caches |
| `~/Backups/pc-settings-*.tar.gz` | settings backups |
| `~/.local/share/pc-command-center/pcctl` | copied installed app code |
| `~/.local/bin/pc-gui` | GUI launcher |
| `~/.local/bin/pc` | CLI/TUI entry point |
| `~/.local/share/applications/io.github.infinite4evr.PcCommandCenter.desktop` | desktop entry |
| `~/.config/systemd/user/pc-maintain.*` | weekly maintenance |
| `~/.config/systemd/user/pc-watch.*` | background alerts |
| `/usr/local/libexec/pc-command-center/pc-admin` | root helper |
| `/usr/share/polkit-1/actions/io.github.infinite4evr.PcCommandCenter.policy` | polkit policy |

The older setup layer also uses:

```text
~/.local/state/linux-setup/
```

Long-term improvement: consolidate/migrate the two state namespaces where practical.

---

# 13. Installation / development commands

## Bootstrap/install

From repository root:

```bash
bash setup.sh
```

The setup script exposes project-specific options; inspect it before changing installation semantics.

## Python development

```bash
cd pc
python3 -m pip install -e '.[dev]'
python3 -m pytest -q
```

Plain pytest source discovery is configured in `pyproject.toml`; manually setting `PYTHONPATH=src` should no longer be necessary for the normal test command.

## Syntax checks

```bash
python3 -m compileall -q pc/src pc/tests
bash -n setup.sh lib/*.sh pc/data/pc-admin
```

## GTK smoke test locally

Requires GTK 4, libadwaita GI bindings, and a display/Xvfb. CI demonstrates the canonical package set.

Example conceptual command:

```bash
cd pc
PYTHONPATH=src PC_NO_WELCOME=1 PC_DEBUG=1 \
  xvfb-run -a /usr/bin/python3 -m pcctl.gui.main \
  --screenshots /tmp/pc-shots --pages dashboard --wait 0.8
```

---

# 14. Test status at this handover

Command run:

```bash
cd pc
python3 -m pytest -q -rs
```

Result:

```text
211 passed, 2 skipped
```

Skip reason:

```text
needs a display and Python with GTK 4 + libadwaita
```

The two skips are local GUI smoke variants when the host environment does not provide the GTK stack/display. The CI GTK smoke job is intended to cover real widget initialization/rendering under Ubuntu/Xvfb.

## Important execution-safety tests

`test_execution_safety.py` specifically protects v2.2 regressions around:

- sensitive argument redaction,
- exact root batch return codes,
- optional root steps,
- task cancellation callback behavior,
- password flag redaction,
- cleanup symlink traversal,
- safe symlink unlinking,
- archive symlink rejection,
- pre-existing symlink-parent rejection,
- private debug log/support bundle permissions.

Future safety fixes should normally come with a regression test in this module or another focused test module.

---

# 15. Coverage / testing reality

The suite is healthy but risk-based coverage still needs improvement.

During the audit, parser-heavy modules were generally better covered than several operational modules. Areas that historically had little/directly measured coverage included things like:

- drive operations,
- health/diagnostics,
- self-update,
- watch/background alert logic,
- some cleanup/network/package paths,
- CLI edge cases.

Do not optimize for a vanity global coverage number. Prioritize behavior that can:

- alter disks,
- alter boot config,
- alter package state,
- alter networking,
- delete files,
- run privileged commands,
- persist scheduled jobs,
- expose secrets.

Target strong direct behavioral coverage for those paths.

---

# 16. Known limitations / technical debt

This is the most important section after the safety invariants.

## 16.1 Privileged helper architecture

Current state:

```text
GUI → generated private shell batch → pkexec → pc-admin → bash script
```

It is hardened relative to the old implementation, but still grants a fairly generic privileged execution shape.

Desired future state:

```text
GUI/core
  ↓ structured request
small root service/helper
  ↓ operation allowlist + parameter validation
specific system action
```

Potential implementation technologies:

- D-Bus service,
- narrowly scoped helper binary/script commands,
- separate polkit actions per risk family.

Do this only with integration tests and careful permission design.

## 16.2 Action duplication across front ends

GTK, TUI, and CLI still contain orchestration duplication.

Recommended architecture:

```python
@dataclass
class Action:
    id: str
    title: str
    description: str
    risk: RiskLevel
    privilege: PrivilegeLevel
    capability: Capability
    build_plan: Callable[..., list[Step]]
    reversible: bool
    cancellation_policy: ...
    postconditions: ...
```

Then all front ends render the same actions.

## 16.3 No general transaction/undo engine

Activity history exists and several individual features have backups, but there is no universal transaction object that guarantees:

```text
preflight → snapshot → apply → verify → commit → undo
```

This is the next major architectural improvement for a system-management app.

## 16.4 Background tasks are not persisted

The in-memory task registry disappears with the GUI process.

For long-running jobs, future work could persist task metadata to SQLite or map persistent jobs directly to systemd units with structured status.

## 16.5 Python worker cancellation

Generic workers are intentionally non-cancellable.

Future long scans should be written cooperatively with cancellation tokens/progress callbacks.

## 16.6 Debug redaction is best effort

Explicit `Step.sensitive_args/sensitive_env` is the strongest mechanism. Pattern-based redaction is defense-in-depth, not perfect secret detection.

## 16.7 Real-machine validation is still required

Container/unit tests cannot fully validate:

- polkit behavior,
- apt/dpkg interruptions,
- GRUB behavior,
- swap changes,
- real NetworkManager state,
- hotspot behavior,
- firmware,
- SMART/NVMe devices,
- suspend/resume,
- GNOME extension compatibility,
- hardware-specific GPU/thermal behavior.

Use VM snapshots first, then dedicated real Ubuntu hardware.

## 16.8 Release trust/signing

Self-update/bootstrap paths still need a signed release/checksum architecture.

## 16.9 Native package

A `.deb` package remains a strong future target because this is a host-management application and naturally needs native host integration.

---

# 17. Prioritized future roadmap

This consolidates the audit into a practical order rather than a flat wish list.

## P0 — next safety/architecture work

1. Replace generic privileged batch execution with a structured privileged service/helper.
2. Create an explicit action/transaction model with preconditions, postconditions, rollback, and risk levels.
3. Make long Python scans cooperatively cancellable.
4. Add VM integration tests for apt, NetworkManager, GRUB, swap/fstab, systemd, and restore flows.
5. Add release manifest + SHA-256/signature verification for self-update/bootstrap.
6. Add explicit per-command timeout policies and structured errors.
7. Audit every new secret-bearing action for `sensitive_args`/`sensitive_env`.
8. Expand redaction tests with more credential formats.

## P1 — reliability / maintainability

1. Central Action registry shared by GTK/TUI/CLI.
2. Central configuration mutation framework:
   - backup,
   - parse,
   - atomic write,
   - validate,
   - apply,
   - rollback.
3. SQLite/WAL store for Activity, metrics, task history, scan history if persistence grows.
4. Better process/task progress reporting.
5. Better “recovery after interrupted package operation” UI.
6. Installer lock/resume semantics.
7. Ownership manifest + precise uninstall/revert support.
8. Idempotency tests: apply twice, apply/rollback back to original state.

## P1 — UI/UX polish

1. Continue restrained micro-interactions.
2. Respect system reduced-motion preference automatically in addition to app preference.
3. Make task rows richer: progress, elapsed time, ETA where meaningful.
4. Add responsive sidebar behavior for very narrow windows.
5. Add custom dashboard/My Tools pinned actions.
6. Improve accessibility testing: keyboard-only, screen reader labels, large text, high contrast.
7. Add more visual regression/screenshot testing.
8. Add empty/error/loading state consistency across pages.

## P2 — monitoring/history

1. 1h/24h/7d metric history.
2. CPU pressure, memory pressure, disk latency/IOPS trends.
3. GPU VRAM/utilization history.
4. network history by interface.
5. battery discharge/wear trends.
6. boot-time history and regression detection.
7. “What changed on my PC?” daily snapshots.
8. anomaly detection with explanations, not opaque scores.

## P2 — updates/security

1. Ubuntu security/CVE/USN integration.
2. Ubuntu Pro/ESM/Livepatch status when available.
3. update severity and reboot/service restart requirements.
4. source signing/key health.
5. kernel lifecycle/default/next-boot view.
6. stronger Flatpak remote/version/pinning management.
7. stronger Snap channel/revision/permission management.
8. central encryption/Secure Boot/TPM protection page.

## P2 — storage

1. inode usage.
2. SMART self-tests and NVMe error/wear trend history.
3. TRIM status/schedule.
4. encryption/LUKS/LVM/RAID/Btrfs/ZFS status when detected.
5. `/etc/fstab` validator.
6. folder growth history.
7. shared filesystem index for large-files/duplicates/old-files/type analysis.

## P2 — networking

1. traceroute / `mtr`.
2. IPv6 diagnosis.
3. DNS latency/route/DoT state.
4. packet loss/gateway/MTU/captive portal checks.
5. local `iperf3` option.
6. VPN route/DNS leak analysis.
7. per-process bandwidth history if a safe capability is implemented.
8. clearer network-scan privacy/scope controls.

## P2 — processes/services

1. process cgroup/systemd-unit mapping.
2. per-process historical CPU/memory/IO.
3. open files/listening sockets in process detail.
4. resource controls via systemd/cgroups.
5. service dependency/reverse dependency graph.
6. service restart/failure history.
7. unit security analysis.

## P2 — backup/recovery

1. manifest + SHA-256 in settings backup.
2. backup schema version.
3. restore preview.
4. selective restore.
5. encrypted backups.
6. retention policy.
7. explicit PC Command Center “Restore Point” concept for configuration changes.

## P3 — deferred feature-audit ideas

Historical deferred ideas include:

- internationalization,
- customizable dashboard / My Tools,
- GNOME top-bar monitor,
- compact always-on-top monitor,
- longer metrics history,
- NPU monitoring,
- browser history/cookie cleanup,
- browser DB vacuum,
- Flatpak remote management/downgrade/pinning,
- fastest-mirror benchmarking,
- removed-app leftover config,
- AppImage updater,
- startup impact measurement,
- per-process network use,
- cgroup CPU limits,
- folder growth history,
- SMB/NFS integration,
- bandwidth history,
- lid/power-button behavior,
- optional safe benchmark tools,
- crash-report tooling,
- Ubuntu Pro/security status,
- CVE view,
- EXIF removal,
- advanced webcam controls,
- font manager,
- Catppuccin flavor profiles,
- `mkcert`,
- consistent CLI `--json` mode,
- native `.deb` packaging.

See `docs/FEATURE-AUDIT.md` for the historical table and rationale.

---

# 18. Features that should NOT be casually added

Several “system utility” ideas are deceptively dangerous.

Avoid or heavily gate:

- raw disk wiping/shredding presented as guaranteed secure erase on SSDs,
- arbitrary systemd system-unit override editor in beginner UI,
- generic root shell/terminal features,
- automatic deletion of visually similar photos,
- automatic removal of unknown configuration directories,
- aggressive “optimization” tweaks without evidence,
- background network scanning without explicit user intent,
- automatically modifying SSH/network/boot settings without recovery paths.

The app should prefer **explainable, reversible, evidence-based actions** over “optimizer magic.”

---

# 19. Design direction

The desired visual/product character is:

- native GNOME/libadwaita rather than a custom web-looking shell,
- polished and modern,
- soft/clean rather than flashy,
- useful motion rather than excessive motion,
- clear hierarchy,
- plain-English labels,
- visible system state,
- explicit consequences,
- friendly to non-Linux-experts while still deep enough for developers.

Keep the current “Modern” look as the default and Catppuccin as an optional flavor.

For new visuals:

- favor consistent spacing and cards,
- use meaningful icons,
- use hover/focus states,
- never communicate severity by color alone,
- respect light/dark modes,
- respect reduced motion,
- keep destructive actions visually distinct.

---

# 20. Future Action architecture recommendation

This is the strongest structural recommendation from the audit.

Today the project has `Step`, shared core functions, and front-end-specific orchestration. Evolve toward a declarative action registry.

Concept:

```python
@dataclass
class Action:
    id: str
    title: str
    description: str
    category: str
    keywords: tuple[str, ...]
    risk: RiskLevel
    privilege: PrivilegeLevel
    reversible: bool
    capabilities: tuple[str, ...]
    sensitive_fields: tuple[str, ...]
    build_plan: Callable[..., list[Step]]
    validate_preconditions: Callable[..., list[CheckResult]]
    validate_postconditions: Callable[..., list[CheckResult]]
    rollback: Callable[..., list[Step]] | None
```

Then:

```text
                 Action registry
                /      |       \
              GTK      TUI      CLI
```

Benefits:

- no feature drift,
- consistent confirmations,
- consistent risk labels,
- consistent privilege handling,
- automatic command-palette/search integration,
- easier testing,
- generated CLI completion/help,
- easier background-task integration,
- easier dry-run/preview/undo.

---

# 21. Future transaction/undo architecture recommendation

Ideal mutation lifecycle:

```text
1. capability/preflight
2. collect current state
3. show exact plan
4. create restore snapshot
5. execute prepare steps
6. execute commit step(s)
7. verify postconditions
8. record activity
9. expose Undo / recovery
```

Activity should eventually store structured data instead of just human-readable command/output history:

```json
{
  "action_id": "network.set_dns",
  "started": "...",
  "before": {...},
  "requested": {...},
  "result": {...},
  "verification": {...},
  "rollback_available": true
}
```

This would make “Undo” and “What changed?” reliable rather than heuristic.

---

# 22. Compatibility assumptions

The historical primary target has been modern Ubuntu GNOME, especially Ubuntu 26.04-era behavior, while code generally tries to degrade gracefully.

Important compatibility concepts already present in the project:

- Python package requires `>=3.10`.
- GTK GUI relies on Ubuntu/system Python with PyGObject + GTK 4 + libadwaita.
- Ubuntu 26.04 has differences such as newer APT behavior and Rust/uutils core tools; the code includes fallback handling such as preferring `gnudu` when appropriate.
- Wayland/GNOME behavior should be capability-detected where possible.
- external tools such as SMART/NVIDIA/ClamAV/Timeshift/etc. may be absent.

Do not hardcode “all Ubuntu systems have X.” Prefer `has()`/capability checks and meaningful unavailable states.

---

# 23. Rules for future AI contributors

If you are another AI continuing this project, follow these rules:

1. **Read this handover before coding.**
2. **Read the specific core module + GUI page + tests for the feature you touch.**
3. **Do not bypass `Step` for mutating commands without a strong reason.**
4. **Mark secret arguments/environment values explicitly.**
5. **Never log raw credentials.**
6. **Do not hard-kill package/boot/filesystem operations.**
7. **Do not weaken root-helper validation.**
8. **Do not use generic TAR extraction for settings restore.**
9. **Do not follow symlinked parents during cleanup/deletion.**
10. **Use atomic/private state helpers for sensitive app state.**
11. **Register background work with the task system.**
12. **Use cooperative cancellation for new Python long-running tasks.**
13. **Keep GTK imports out of `pcctl.core`.**
14. **Add regression tests for every safety bug.**
15. **Run the full suite before packaging.**
16. **Run `bash -n` on changed shell/admin scripts.**
17. **Respect motion/light/dark/accessibility behavior.**
18. **Prefer explainable/reversible actions to aggressive automation.**
19. **Do not claim a hardware-dependent feature is tested unless it actually was.**
20. **Update this handover when architecture/status materially changes.**

---

# 24. Where to start for common future tasks

## “A command/action is failing”

Start with:

```text
pc/src/pcctl/core/run.py
pc/src/pcctl/gui/runner.py
pc/src/pcctl/core/debug.py
pc/src/pcctl/gui/dialogs.py
```

Then inspect the feature’s core module/page.

## “A background task is not visible/stoppable”

Start with:

```text
pc/src/pcctl/core/tasks.py
pc/src/pcctl/gui/taskcenter.py
pc/src/pcctl/gui/util.py
pc/src/pcctl/gui/runner.py
```

## “Logs/support bundle are missing useful data”

Start with:

```text
pc/src/pcctl/core/debug.py
pc/src/pcctl/gui/preferences.py
pc/src/pcctl/gui/main.py
pc/src/pcctl/cli.py
```

## “Sidebar/layout/motion needs changing”

Start with:

```text
pc/src/pcctl/gui/window.py
pc/src/pcctl/gui/prefs.py
pc/src/pcctl/gui/preferences.py
pc/src/pcctl/gui/style.css
```

## “A cleanup path is unsafe”

Start with:

```text
pc/src/pcctl/core/junk.py
pc/tests/test_execution_safety.py
```

## “Settings backup/restore bug”

Start with:

```text
pc/src/pcctl/core/maint.py
pc/tests/test_maintenance.py
pc/tests/test_execution_safety.py
```

## “Privilege/polkit problem”

Start with:

```text
pc/src/pcctl/gui/runner.py
pc/data/pc-admin
pc/data/io.github.infinite4evr.PcCommandCenter.policy
lib/install.sh
```

Test on a real Ubuntu/polkit environment before declaring it fixed.

---

# 25. Release checklist for future versions

Before producing a new ZIP/release:

## Code

- [ ] version updated consistently,
- [ ] changelog updated,
- [ ] new preferences have defaults/migration behavior,
- [ ] new state files use appropriate privacy/atomicity,
- [ ] new secrets are marked/redacted,
- [ ] new background work is tracked,
- [ ] new destructive behavior has preview/confirmation/recovery.

## Tests

Run:

```bash
cd pc
python3 -m pytest -q -rs
python3 -m compileall -q src tests
cd ..
bash -n setup.sh lib/*.sh pc/data/pc-admin
```

- [ ] add regression test for fixed bugs,
- [ ] run GTK smoke test in GTK-capable environment,
- [ ] run VM integration tests for system-changing work where applicable.

## Documentation

- [ ] `CHANGELOG.md`,
- [ ] `AI-HANDOVER.md`,
- [ ] feature docs/readme if user-facing behavior changed,
- [ ] `SECURITY.md` if security model changed.

## Packaging

- [ ] remove `__pycache__`, `.pyc`, test temp files,
- [ ] preserve executable bits on shell/admin launchers,
- [ ] ZIP integrity test,
- [ ] compute SHA-256,
- [ ] do not include real user logs/secrets/backups.

---

# 26. Current validation result captured for handover

Latest command:

```bash
cd pc
python3 -m pytest -q -rs
```

Latest result:

```text
211 passed, 2 skipped in ~4 seconds
```

Skipped tests:

```text
tests/test_gui_smoke.py
Reason: needs a display and Python with GTK 4 + libadwaita
```

The repository CI contains a GTK/Xvfb smoke job to exercise GUI startup/rendering in an Ubuntu runner.

---

# 27. What “done” means for v2.2

v2.2 should be considered a **hardening + diagnostics + task-control + UI-shell release**, not the final endpoint of the project.

The important outcome is that the application now has safer foundations for future expansion:

```text
Before:
feature-rich system tool
+ fragmented execution/logging/background behavior

Now:
feature-rich system tool
+ safer Step model
+ secret redaction
+ hardened privileged batching
+ task registry/UI
+ opt-in support logging
+ safer cancellation
+ private atomic state
+ stronger restore/delete guards
+ better shell UX/animations
+ stronger regression tests
```

The next transformational milestone should be:

```text
Action registry
+ structured privileged service
+ transaction/undo model
+ VM integration testing
```

That is more valuable than simply adding another large batch of buttons.

---

# 28. Quick pickup checklist for another AI

If you only have five minutes before continuing work:

1. Read sections **1, 5, 6, 16, 23** of this file.
2. Run:
   ```bash
   cd pc && python3 -m pytest -q
   ```
3. Inspect `core/run.py`, `gui/runner.py`, `core/debug.py`, `core/tasks.py`, and `gui/window.py`.
4. Never log raw command argv if it may contain credentials.
5. Never weaken exact `ok_codes` handling.
6. Register long-running app work in the task system.
7. Preserve sidebar/motion preferences.
8. Use safe cancellation rules.
9. For real system changes, test in an Ubuntu VM/snapshot before claiming production readiness.
10. Update this handover when you finish your changes.

---

# 29. Final status

**Version:** `2.2.4`  
**Automated tests:** `216 passed, 2 skipped`  
**Primary UI:** GTK 4/libadwaita  
**Debug logging:** implemented, opt-in, rotating, redacted  
**Support bundle:** implemented  
**Background Task Centre:** implemented  
**Command task cancellation:** implemented with critical-operation safeguards  
**Sidebar collapse/resize:** implemented and persisted  
**Motion modes:** Full / Reduced / Off  
**Privileged return-code bug:** fixed and regression-tested  
**Private admin batches:** implemented  
**Secret-aware command display:** implemented  
**Restore/archive hardening:** implemented  
**Cleanup symlink guard:** implemented  
**Atomic/private state:** implemented in security-sensitive paths  
**GTK smoke CI:** implemented  
**Structured privileged D-Bus/helper service:** not yet implemented  
**Universal Action registry/transaction Undo engine:** not yet implemented  
**Native `.deb`:** not yet implemented  
**Comprehensive real-hardware validation:** still required for hardware/system-changing paths

This is the current handoff point.

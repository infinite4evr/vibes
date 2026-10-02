# Security

PC Command Center changes operating-system settings and therefore treats privileged execution as a security boundary.

## Reporting a problem

Every unexpected error in the desktop app opens a small **Something went wrong** dialog. **Report on GitHub** opens a pre-filled issue in your browser (nothing is sent until you submit it there); **Copy details** and **Save full log** give the untrimmed text. Before you see it, the report has secrets, your home folder path, user and computer names, and IP/MAC addresses removed. It includes the error, the last day's entries from `~/.local/state/pc/gui-errors.log`, the debug log tail when debug logging is on, and app/OS/GTK versions. Failed actions get the same **Report on GitHub** button, and a crash in `pc` or the terminal app prints the same link. Read the issue before submitting: redaction is best effort.

Do not post passwords, tokens, private keys, Wi‑Fi PSKs or unredacted diagnostic data in a public issue. In the desktop app, enable **Preferences → Diagnostics → Record detailed debug logs**, reproduce the problem, then use **Create support bundle**. The bundle applies best-effort redaction to known secret formats and explicitly secret-marked command arguments; review it before sharing. The CLI equivalent is `pc support`.

## Privileged actions

The desktop app shows planned commands before risky actions. Its installed `pc-admin` helper accepts only a private, user-owned, single-link `/tmp/pc-admin-*.sh` batch with mode `0600`. Root batches enforce each step's exact accepted exit codes.

## Limitations

Redaction is defense in depth, not a mathematical guarantee. Review diagnostic bundles before sharing. Hardware-changing and boot-critical features should be validated on a disposable VM or backed-up machine before deployment to a new distribution release.

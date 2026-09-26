# Security

PC Command Center changes operating-system settings and therefore treats privileged execution as a security boundary.

## Reporting a problem

Do not post passwords, tokens, private keys, Wi‑Fi PSKs or unredacted diagnostic data in a public issue. In the desktop app, enable **Preferences → Diagnostics → Record detailed debug logs**, reproduce the problem, then use **Create support bundle**. The bundle applies best-effort redaction to known secret formats and explicitly secret-marked command arguments; review it before sharing. The CLI equivalent is `pc support`.

## Privileged actions

The desktop app shows planned commands before risky actions. Its installed `pc-admin` helper accepts only a private, user-owned, single-link `/tmp/pc-admin-*.sh` batch with mode `0600`. Root batches enforce each step's exact accepted exit codes.

## Limitations

Redaction is defense in depth, not a mathematical guarantee. Review diagnostic bundles before sharing. Hardware-changing and boot-critical features should be validated on a disposable VM or backed-up machine before deployment to a new distribution release.

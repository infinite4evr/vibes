# PC Command Center 2.2.4 — compact-window shell/layout hotfix

## What the user screenshot exposed

2.2.2 restored the missing sidebar routes and 2.2.3 made installation/version verification reliable, but the shell was still not genuinely adaptive at compact logical widths (for example 1366x768 displays with fractional scaling). The resizable sidebar could still claim too much of the application, page title/action rows remained rigid, and `Adw.HeaderBar` could crowd the wide search field out of view.

## Changes

- Sidebar: 205 px minimum, 235 px default, 300 px hard maximum.
- Runtime width cap: sidebar is also limited to about 28% of the actual window and content reservation is raised to 650 px where possible.
- Long sidebar/brand text ellipsizes instead of widening navigation.
- Header search has a compact fallback button that opens the command palette.
- Page headers wrap title and action regions at narrow widths.
- Page margins reduce from 24 px to 18/12 px as the page gets narrower.
- Shared scrollers do not propagate large natural widths into the shell.

## Validation

`216 passed, 2 skipped` on the packaging host. The two skipped tests are the real GTK screenshot/render tests because PyGObject GTK4/libadwaita are not installed in this container. Therefore this release fixes the source/layout contracts exposed by the user's real-machine screenshot, but it must not be described as visually rendered on this build host.

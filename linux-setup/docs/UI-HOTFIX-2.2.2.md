# PC Command Center 2.2.2 UI hotfix

## Symptom seen on a real machine

- **Develop** and **Care** section headers appeared with no navigation item below them.
- Storage/Network/Power/Logs could disappear from **Monitor**.
- Other responsive controls could fail when the affected code path was opened.
- The sidebar could restore an overly wide value from a previous session.

## Root cause

The 2.2.1 responsive pass introduced calls such as:

```python
flow(..., column_spacing=8, row_spacing=6)
```

while the helper still declared only:

```python
flow(..., spacing=12, ...)
```

GTK page constructors therefore raised `TypeError`. The main window caught those exceptions and hid each failed row, so the app looked like pages had been removed rather than showing an error. The normal 208-test suite did not import/render GTK pages on the packaging host; its two GTK smoke tests were skipped because PyGObject/libadwaita were unavailable.

## Fix

1. `flow()` now accepts `column_spacing` and `row_spacing` while retaining `spacing` as the default for both.
2. Page-construction failures remain visible in the sidebar and open a diagnostic fallback page.
3. Page-import failures also get a visible fallback route.
4. Sidebar width is normalized to 210–330 px and keeps a 560 px content budget where window size allows.
5. Added three source-level tests that run without GTK:
   - all `flow()` keyword arguments must exist in the helper signature;
   - every sidebar route must have a page module with a matching ID;
   - page-construction failures must not be hidden from navigation.

## Validation

```text
211 passed, 2 skipped
```

The skipped tests are the actual GTK screenshot smoke tests and still require an Ubuntu/GTK-capable runtime.

# Contributing

## Local checks

From `pc-command-center/`:

```bash
python -m pip install -e '.[dev]'     # once: pytest, pytest-cov, ruff
python -m pytest -q
python -m compileall -q src tests
ruff check src tests                  # configured in pyproject.toml; 52 findings today, add no new ones
bash -n ../ubuntu-setup/setup.sh ../ubuntu-setup/lib/*.sh data/pc-admin
```

These are the same checks as `.github/workflows/pc-command-center.yml` at the root of the `vibes` repository (plus ruff), which runs on every push that touches `pc-command-center/` or `ubuntu-setup/`.

## Safety rules

- Keep read-only probes separate from mutating actions.
- Represent mutations as `Step` objects so confirmation, redaction, debug logging and task control stay consistent.
- Mark secret argv positions/environment names instead of embedding secrets in display strings.
- Use exact `ok_codes`; use `optional=True` only when any failure is genuinely safe to ignore.
- Use atomic/private state helpers for local history and diagnostics.
- Add a regression test for privileged/cancellation/restore behavior before changing those boundaries.

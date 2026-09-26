# Contributing

## Local checks

From `pc/`:

```bash
python -m pip install -e '.[dev]'     # once: pytest, pytest-cov, ruff
python -m pytest -q
python -m compileall -q src tests
ruff check src tests                  # configured in pyproject.toml; 52 findings today, add no new ones
bash -n ../setup.sh ../lib/*.sh data/pc-admin
```

These are the same checks as `.github/workflows/ci.yml` (plus ruff). That workflow does not run yet: GitHub only runs workflows from the root of the `vibes` repository, so run the checks locally before pushing.

## Safety rules

- Keep read-only probes separate from mutating actions.
- Represent mutations as `Step` objects so confirmation, redaction, debug logging and task control stay consistent.
- Mark secret argv positions/environment names instead of embedding secrets in display strings.
- Use exact `ok_codes`; use `optional=True` only when any failure is genuinely safe to ignore.
- Use atomic/private state helpers for local history and diagnostics.
- Add a regression test for privileged/cancellation/restore behavior before changing those boundaries.

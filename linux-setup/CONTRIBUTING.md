# Contributing

## Local checks

From `pc/`:

```bash
python -m pytest -q
python -m compileall -q src tests
bash -n ../setup.sh ../lib/*.sh
```

Install developer extras with `python -m pip install -e '.[dev]'` when desired.

## Safety rules

- Keep read-only probes separate from mutating actions.
- Represent mutations as `Step` objects so confirmation, redaction, debug logging and task control stay consistent.
- Mark secret argv positions/environment names instead of embedding secrets in display strings.
- Use exact `ok_codes`; use `optional=True` only when any failure is genuinely safe to ignore.
- Use atomic/private state helpers for local history and diagnostics.
- Add a regression test for privileged/cancellation/restore behavior before changing those boundaries.

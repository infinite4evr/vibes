"""Desktop-app preferences and window state, stored in ~/.config/pc/gui.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FILE = Path.home() / ".config/pc/gui.json"

DEFAULTS: dict[str, Any] = {
    "appearance": "system",      # system | light | dark
    "start_page": "last",        # last | dashboard | any page id
    "refresh": "normal",         # fast | normal | slow
    "pause_hidden": True,        # stop live graphs while the window is minimised or hidden
    "confirm_safe": True,        # show the commands before running (always true for admin/dangerous actions)
    "big_delete_gb": 10,         # extra warning above this size
    "welcomed": False,
    "look": "modern",            # modern (neutral, follows GNOME's accent) | catppuccin
}

_cache: dict[str, Any] | None = None


def _load() -> dict[str, Any]:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(FILE.read_text())
        except (OSError, ValueError):
            _cache = {}
    return _cache


def get(key: str, default: Any = None) -> Any:
    d = _load()
    if key in d:
        return d[key]
    return DEFAULTS.get(key, default)


def set(key: str, value: Any) -> None:  # noqa: A001 - short name reads well at call sites
    d = _load()
    d[key] = value
    save()


def update(**kw: Any) -> None:
    _load().update(kw)
    save()


def save() -> None:
    try:
        FILE.parent.mkdir(parents=True, exist_ok=True)
        FILE.write_text(json.dumps(_load(), indent=2))
    except OSError:
        pass


def refresh_factor() -> float:
    """Multiplier for every page's auto-refresh interval."""
    return {"fast": 0.6, "normal": 1.0, "slow": 2.5}.get(get("refresh"), 1.0)

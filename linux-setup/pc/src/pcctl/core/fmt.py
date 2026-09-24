"""Small formatting helpers shared by the CLI and the TUI."""

from __future__ import annotations

import time

# Catppuccin Mocha
C = {
    "rosewater": "#f5e0dc", "flamingo": "#f2cdcd", "pink": "#f5c2e7", "mauve": "#cba6f7",
    "red": "#f38ba8", "maroon": "#eba0ac", "peach": "#fab387", "yellow": "#f9e2af",
    "green": "#a6e3a1", "teal": "#94e2d5", "sky": "#89dceb", "sapphire": "#74c7ec",
    "blue": "#89b4fa", "lavender": "#b4befe", "text": "#cdd6f4", "subtext1": "#bac2de",
    "subtext0": "#a6adc8", "overlay2": "#9399b2", "overlay1": "#7f849c", "overlay0": "#6c7086",
    "surface2": "#585b70", "surface1": "#45475a", "surface0": "#313244", "base": "#1e1e2e",
    "mantle": "#181825", "crust": "#11111b",
}


def human(n: float | int | None, suffix: str = "B") -> str:
    if n is None:
        return "?"
    n = float(n)
    for unit in ("", "K", "M", "G", "T", "P"):
        if abs(n) < 1024 or unit == "P":
            if unit == "":
                return f"{int(n)} {suffix}"
            return f"{n:.1f} {unit}{suffix}"
        n /= 1024
    return f"{n:.1f} P{suffix}"


def rate(n: float) -> str:
    return human(n) + "/s"


def duration(seconds: float) -> str:
    s = int(seconds)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m"
    return f"{s}s"


def ago(ts: float) -> str:
    diff = time.time() - ts
    if diff < 60:
        return "just now"
    return duration(diff) + " ago"


def level_color(pct: float, warn: float = 75, crit: float = 90) -> str:
    if pct >= crit:
        return C["red"]
    if pct >= warn:
        return C["peach"]
    return C["green"]


def bar(pct: float, width: int = 20, warn: float = 75, crit: float = 90) -> str:
    """Rich-markup progress bar."""
    pct = max(0.0, min(100.0, pct))
    filled = round(pct / 100 * width)
    color = level_color(pct, warn, crit)
    return f"[{color}]{'━' * filled}[/][{C['surface1']}]{'━' * (width - filled)}[/]"


def plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else (many or word + 's')}"

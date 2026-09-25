"""App-wide settings, stored as JSON in the data directory and edited from the UI."""
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("tgdrive.settings")

DEFAULTS: dict[str, Any] = {
    # Telegram
    "api_id": 0,
    "api_hash": "",
    "drive_channel_title": "TG Drive",
    # Appearance
    "theme": "system",            # system | light | dark
    "density": "comfortable",     # comfortable | compact
    "view": "grid",               # grid | list
    "grid_size": "m",             # s | m | l
    "group_by_date": False,
    "show_related": True,
    # Search
    "search_mode": "smart",       # smart | exact
    "search_semantic": True,
    "search_builtin_synonyms": True,
    "search_synonyms": "",
    "search_live": True,
    "search_scope_default": "everywhere",  # everywhere | here
    # Transfers
    "download_dir": "",
    "open_after_download": False,
    "parallel_transfers": 3,
    "upload_workers": 4,
    "download_workers": 4,
    "upload_as_media": False,
    "keep_structure": True,
    # Streaming
    "stream_cache_mb": 2048,
    "stream_prefetch": 4,
    "external_player": "",         # command, e.g. "vlc" or "mpv --force-window"; empty = first one found
    "native_player_auto": True,    # desktop app: formats the window can't decode open in the built-in player
    "autoplay_next": True,
    # Indexing
    "index_paused": False,
    "index_wait": 0.5,
    "index_kinds": ["photo", "video", "document", "audio", "voice", "round", "gif"],
    "index_skip_kinds_of_chat": [],  # e.g. ["bot", "user"]
    "resync_minutes": 30,
    "verify_deleted": True,
    "verify_per_hour": 20000,
    "save_inline_previews": True,
    # Network
    "proxy_enabled": False,
    "proxy_type": "socks5",       # socks5 | socks4 | http | mtproto
    "proxy_host": "",
    "proxy_port": 1080,
    "proxy_user": "",
    "proxy_pass": "",
    "proxy_secret": "",
    # Desktop
    "notifications": True,
    "close_to_tray": True,
    "start_minimized": False,
    "autostart": False,
    # Security
    "lock_enabled": False,
    "lock_hash": "",
    "lock_salt": "",
    "lock_after_minutes": 0,
    "confirm_delete": True,
}

CHOICES = {
    "theme": {"system", "light", "dark"},
    "density": {"comfortable", "compact"},
    "view": {"grid", "list"},
    "grid_size": {"s", "m", "l"},
    "search_mode": {"smart", "exact"},
    "search_scope_default": {"everywhere", "here"},
    "proxy_type": {"socks5", "socks4", "http", "mtproto"},
}
RANGES = {
    "parallel_transfers": (1, 10), "upload_workers": (1, 8), "download_workers": (1, 8),
    "stream_cache_mb": (0, 200_000), "stream_prefetch": (0, 16), "index_wait": (0.0, 10.0),
    "resync_minutes": (5, 1440), "verify_per_hour": (0, 200_000), "proxy_port": (1, 65535),
    "lock_after_minutes": (0, 1440), "api_id": (0, 2**31),
}
SECRET = {"api_hash", "proxy_pass", "proxy_secret", "lock_hash", "lock_salt"}


class SettingsError(ValueError):
    pass


class Settings:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self.data: dict[str, Any] = dict(DEFAULTS)
        self.listeners: list[Callable[[set[str]], None]] = []
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if k in DEFAULTS:
                        self.data[k] = v
        except FileNotFoundError:
            pass
        except Exception as exc:
            log.warning("settings file unreadable (%s); using defaults", exc)

    def save(self) -> None:
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.chmod(tmp, 0o600)
            tmp.replace(self.path)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, DEFAULTS.get(key, default))

    def public(self) -> dict:
        out = {k: v for k, v in self.data.items() if k not in SECRET}
        out["api_hash_set"] = bool(self.data.get("api_hash"))
        out["proxy_pass_set"] = bool(self.data.get("proxy_pass"))
        out["lock_set"] = bool(self.data.get("lock_hash"))
        return out

    def _clean(self, key: str, value: Any) -> Any:
        if key not in DEFAULTS:
            raise SettingsError(f"Unknown setting '{key}'.")
        default = DEFAULTS[key]
        if key in CHOICES and value not in CHOICES[key]:
            raise SettingsError(f"'{value}' isn't a valid choice for {key}.")
        if isinstance(default, bool):
            return bool(value)
        if isinstance(default, int) and not isinstance(default, bool):
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise SettingsError(f"{key} must be a whole number.")
        elif isinstance(default, float):
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise SettingsError(f"{key} must be a number.")
        elif isinstance(default, list):
            if not isinstance(value, list):
                raise SettingsError(f"{key} must be a list.")
        elif isinstance(default, str):
            value = "" if value is None else str(value)
        if key in RANGES:
            lo, hi = RANGES[key]
            if not lo <= value <= hi:
                raise SettingsError(f"{key} must be between {lo} and {hi}.")
        if key == "download_dir" and value:
            p = Path(value).expanduser()
            try:
                p.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise SettingsError(f"Can't use that folder: {exc}")
            if not os.access(p, os.W_OK):
                raise SettingsError("TG Drive can't write to that folder.")
            value = str(p)
        return value

    def update(self, changes: dict[str, Any]) -> set[str]:
        with self.lock:
            cleaned = {k: self._clean(k, v) for k, v in changes.items()}
            changed = {k for k, v in cleaned.items() if self.data.get(k) != v}
            self.data.update(cleaned)
            if changed:
                self.save()
        for fn in list(self.listeners):
            try:
                fn(changed)
            except Exception:
                log.exception("settings listener failed")
        return changed

    def on_change(self, fn: Callable[[set[str]], None]) -> None:
        self.listeners.append(fn)


def _path() -> Path:
    from . import config
    return config.DATA_DIR / "settings.json"


settings = Settings(_path())


def reload_for_tests(path: Path) -> None:
    """Point the global settings at another file (tests)."""
    settings.path = path
    settings.data = dict(DEFAULTS)
    settings.load()

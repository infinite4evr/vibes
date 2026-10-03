"""Paths and startup configuration.

Data lives in the XDG data directory (~/.local/share/tgdrive) unless TGDRIVE_DATA
is set, or a `data/` folder already exists next to the source (installs from
the 0.1 zip keep working). Telegram API credentials come from Settings (entered
in the app on first run); TG_API_ID / TG_API_HASH in the environment or a .env
file still override them.
"""
import os
import secrets
import sys
from pathlib import Path

APP_NAME = "TG Drive"
APP_ID = "tgdrive"
VERSION = "2.4.0"

if getattr(sys, "frozen", False):  # PyInstaller bundle
    ROOT = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
else:
    ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


PACKAGED = bool(getattr(sys, "frozen", False) or os.environ.get("APPIMAGE") or os.environ.get("TGDRIVE_PACKAGED"))
_load_dotenv(ROOT / ".env")
if not PACKAGED:  # a packaged app must not pick up whatever .env is in the folder it was started from
    _load_dotenv(Path.cwd() / ".env")


def _xdg(var: str, fallback: str) -> Path:
    v = os.environ.get(var)
    return Path(v) if v else Path.home() / fallback


def _default_data_dir() -> Path:
    if os.environ.get("TGDRIVE_DATA"):
        return Path(os.environ["TGDRIVE_DATA"]).expanduser()
    legacy = ROOT / "data"
    if not PACKAGED and (legacy / "accounts").exists():
        return legacy
    from .data_location import selected
    return selected()


DATA_DIR = _default_data_dir().resolve()
LOG_DIR = DATA_DIR / "logs"
ENV_API_ID = int(os.environ.get("TG_API_ID", "0") or 0)
ENV_API_HASH = os.environ.get("TG_API_HASH", "")
HOST = os.environ.get("TGDRIVE_HOST", "127.0.0.1")
PORT = int(os.environ.get("TGDRIVE_PORT", "8765"))
# Optional HTTP basic-auth password. Strongly recommended if HOST is not 127.0.0.1.
PASSWORD = os.environ.get("TGDRIVE_PASSWORD", "")
# Set by the desktop shell: every API request must carry this token.
ACCESS_TOKEN = os.environ.get("TGDRIVE_TOKEN", "")
# Grants only GET/HEAD on stream URLs: goes into playlists, copied VLC/mpv links and the native
# player, so a leaked link can play that file while TG Drive runs but can't reach the rest of the API.
MEDIA_TOKEN = os.environ.get("TGDRIVE_MEDIA_TOKEN") or secrets.token_urlsafe(18)   # the desktop app passes its own
RESYNC_INTERVAL = int(os.environ.get("TGDRIVE_RESYNC", "1800"))


def default_download_dir() -> Path:
    if os.environ.get("TGDRIVE_DOWNLOADS"):   # the Android app passes the phone's Download folder
        return Path(os.environ["TGDRIVE_DOWNLOADS"])
    # Downloads are the person's files, not app data: they stay in the usual Downloads folder
    # (where earlier versions put them) whichever data folder is selected.
    d = None
    user_dirs = _xdg("XDG_CONFIG_HOME", ".config") / "user-dirs.dirs"
    try:
        for line in user_dirs.read_text().splitlines():
            if line.startswith("XDG_DOWNLOAD_DIR="):
                d = Path(os.path.expandvars(line.split("=", 1)[1].strip().strip('"')))
    except OSError:
        pass
    return (d or Path.home() / "Downloads") / APP_NAME


def api_credentials() -> tuple[int, str]:
    from .settings import settings
    if ENV_API_ID and ENV_API_HASH:
        return ENV_API_ID, ENV_API_HASH
    return int(settings.get("api_id") or 0), str(settings.get("api_hash") or "")


def api_configured() -> bool:
    api_id, api_hash = api_credentials()
    return bool(api_id and api_hash)


# Kept for modules that read these names directly.
def __getattr__(name):
    from .settings import settings
    if name == "API_ID":
        return api_credentials()[0]
    if name == "API_HASH":
        return api_credentials()[1]
    if name == "DRIVE_CHANNEL_TITLE":
        return settings.get("drive_channel_title") or "TG Drive"
    if name == "MAX_PARALLEL_TRANSFERS":
        return int(settings.get("parallel_transfers") or 3)
    if name == "UPLOAD_WORKERS":
        return int(settings.get("upload_workers") or 4)
    raise AttributeError(name)

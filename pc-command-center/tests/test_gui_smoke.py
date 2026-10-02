"""GUI smoke test: every page opens and draws in both light and dark style, with no Python errors.

Needs a display (a desktop session, or `Xvfb :99` + DISPLAY=:99) and a Python with GTK 4 + libadwaita (Ubuntu's own python3).
Skipped automatically when either is missing, so `pytest` stays green on a plain server.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
PAGES = ["dashboard", "cleanup", "updates", "apps", "startup", "processes", "storage", "network", "power", "logs", "services",
         "security", "privacy", "tweaks", "dev", "maintenance", "configuration"]
CHECK = "import gi; gi.require_version('Gtk', '4.0'); gi.require_version('Adw', '1'); from gi.repository import Gtk, Adw"


def gtk_python() -> str | None:
    for exe in (sys.executable, "/usr/bin/python3", shutil.which("python3.12") or "", shutil.which("python3.14") or ""):
        if exe and os.path.exists(exe) and subprocess.run([exe, "-c", CHECK], capture_output=True).returncode == 0:
            return exe
    return None


PY = gtk_python()
HAS_DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


@pytest.mark.skipif(PY is None or not HAS_DISPLAY, reason="needs a display and Python with GTK 4 + libadwaita")
@pytest.mark.parametrize("style,width,height", [("light", 920, 620), ("dark", 1320, 860)])
def test_every_page_opens(style, width, height):
    with tempfile.TemporaryDirectory() as out:
        env = {**os.environ, "PYTHONPATH": str(SRC), "PC_STYLE": style, "PC_NO_WELCOME": "1", "GSK_RENDERER": os.environ.get("GSK_RENDERER", "cairo")}
        r = subprocess.run([PY, "-m", "pcctl.gui", "--screenshots", out, "--pages", ",".join(PAGES), "--wait", "2.5",
                            "--width", str(width), "--height", str(height)],
                           capture_output=True, text=True, env=env, timeout=240)
        errors = r.stderr + r.stdout
        assert r.returncode == 0, errors[-3000:]
        assert "Traceback" not in errors, errors[-3000:]
        made = sorted(p.stem for p in Path(out).glob("*.png"))
        assert made == sorted(PAGES), f"missing pages: {set(PAGES) - set(made)}"
        assert all(p.stat().st_size > 20_000 for p in Path(out).glob("*.png")), "a page rendered empty"

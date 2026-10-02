"""File search indexing (GNOME LocalSearch, called Tracker before GNOME 47): on/off, reset, how big the index is.

The indexer reads your files in the background so searching in Files and the Activities overview is instant.
Turning it off saves some battery/disk activity and keeps an index of your file names and contents off the disk;
search still works in Files, just slower.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import run as _run
from .run import Step, has, out, py_step, sh

SCHEMA = "org.freedesktop.Tracker3.Miner.Files"
BACKENDS = [("localsearch", "localsearch-3.service", "LocalSearch"), ("tracker3", "tracker-miner-fs-3.service", "Tracker")]
SAVE_REL = ".config/pc/indexing-backup.json"
CACHE_RELS = [".cache/localsearch", ".cache/tracker3"]
SPECIAL = {"&DESKTOP": "Desktop", "&DOCUMENTS": "Documents", "&DOWNLOAD": "Downloads", "&MUSIC": "Music", "&PICTURES": "Pictures",
           "&VIDEOS": "Videos", "&PUBLIC_SHARE": "Public", "&TEMPLATES": "Templates", "$HOME": "Home folder (top level only)"}


def parse_strv(text: str) -> list[str]:
    """gsettings array output ("['&DESKTOP', '$HOME']" or "@as []") -> list."""
    t = text.strip()
    if t.startswith("@as"):
        t = t[3:].strip()
    return [re.sub(r"\\(.)", r"\1", m) for m in re.findall(r"'((?:[^'\\]|\\.)*)'", t)]


def strv(values: list[str]) -> str:
    return "[" + ", ".join("'" + v.replace("\\", "\\\\").replace("'", "\\'") + "'" for v in values) + "]"


def pretty_dirs(values: list[str], home: Path | None = None) -> list[str]:
    h = str(home or _run.HOME)
    res = []
    for v in values:
        if v in SPECIAL:
            res.append(SPECIAL[v])
        elif v.startswith(h + "/"):
            res.append("~" + v[len(h):])
        else:
            res.append(v)
    return res


def backend() -> dict:
    """Which indexer this Ubuntu has: {cmd, unit, name} (empty strings if none)."""
    for cmd, unit, name in BACKENDS:
        if has(cmd):
            return {"cmd": cmd, "unit": unit, "name": name}
    listed = out(["systemctl", "--user", "list-unit-files", "--no-legend", *[u for _c, u, _n in BACKENDS]], timeout=5)
    for _cmd, unit, name in BACKENDS:
        if unit in listed:
            return {"cmd": "", "unit": unit, "name": name}
    return {"cmd": "", "unit": "", "name": ""}


def index_size(home: Path | None = None) -> int:
    h = home or _run.HOME
    return sum(_run.py_size(h / rel, limit_s=5) for rel in CACHE_RELS if (h / rel).exists())


def saved(home: Path | None = None) -> dict | None:
    try:
        d = json.loads(_run.read((home or _run.HOME) / SAVE_REL) or "null")
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def status() -> dict:
    b = backend()
    schema = has("gsettings") and sh(["gsettings", "list-keys", SCHEMA], timeout=4).ok
    st = {"available": bool(schema or b["unit"]), "schema": schema, **b, "recursive": [], "single": [], "masked": False, "running": False,
          "size": index_size()}
    if schema:
        st["recursive"] = parse_strv(out(["gsettings", "get", SCHEMA, "index-recursive-directories"], timeout=4))
        st["single"] = parse_strv(out(["gsettings", "get", SCHEMA, "index-single-directories"], timeout=4))
    if b["unit"]:
        st["masked"] = out(["systemctl", "--user", "is-enabled", b["unit"]], timeout=4).startswith("masked")
        st["running"] = out(["systemctl", "--user", "is-active", b["unit"]], timeout=4) == "active"
    st["enabled"] = bool(st["recursive"] or st["single"]) and not st["masked"]
    return st


def off_steps(st: dict, home: Path | None = None) -> list[Step]:
    h = home or _run.HOME
    save = h / SAVE_REL
    steps: list[Step] = []
    if st.get("recursive") or st.get("single"):
        def remember() -> str:
            save.parent.mkdir(parents=True, exist_ok=True)
            save.write_text(json.dumps({"recursive": st.get("recursive", []), "single": st.get("single", [])}, indent=2))
            return f"Saved your search folders to {save}"
        steps.append(py_step("Remember your current search folders", remember, f"save them to ~/{SAVE_REL} so turning search back on restores them"))
    steps += [Step("Stop indexing folders inside your home", ["gsettings", "set", SCHEMA, "index-recursive-directories", "[]"]),
              Step("Stop indexing the top of your home folder", ["gsettings", "set", SCHEMA, "index-single-directories", "[]"])]
    if st.get("unit"):
        steps.append(Step("Stop the indexer for now", ["systemctl", "--user", "stop", st["unit"]], optional=True))
    return steps


def on_steps(st: dict, home: Path | None = None) -> list[Step]:
    prev = saved(home)
    steps: list[Step] = []
    if st.get("masked") and st.get("unit"):
        steps.append(Step("Allow the indexer to run again", ["systemctl", "--user", "unmask", st["unit"]]))
    if prev and (prev.get("recursive") or prev.get("single")):
        steps += [Step("Index your folders again", ["gsettings", "set", SCHEMA, "index-recursive-directories", strv(prev.get("recursive", []))]),
                  Step("Index the top of your home folder again", ["gsettings", "set", SCHEMA, "index-single-directories", strv(prev.get("single", []))])]
    else:
        steps += [Step("Index the usual folders again (Documents, Pictures…)", ["gsettings", "reset", SCHEMA, "index-recursive-directories"]),
                  Step("Index the top of your home folder again", ["gsettings", "reset", SCHEMA, "index-single-directories"])]
    if st.get("unit"):
        steps.append(Step("Start the indexer", ["systemctl", "--user", "start", st["unit"]], optional=True))
    return steps


def reset_steps(st: dict) -> list[Step]:
    """Delete the index. It's rebuilt automatically while indexing is on."""
    if st.get("cmd"):
        # The reset command asks "Are you sure? [y|N]" - answer it.
        steps = [Step("Delete the search index", ["bash", "-c", f"echo y | {st['cmd']} reset -s"])]
    else:
        h = _run.HOME
        dirs = [str(h / rel) for rel in CACHE_RELS if (h / rel).exists()]
        if not dirs:
            return []
        steps = [Step("Stop the indexer", ["systemctl", "--user", "stop", st.get("unit") or BACKENDS[0][1]], optional=True),
                 Step("Delete the search index", ["rm", "-rf", "--", *dirs])]
    if st.get("enabled") and st.get("unit"):
        steps.append(Step("Start the indexer again (it rebuilds the index quietly)", ["systemctl", "--user", "start", st["unit"]], optional=True))
    return steps


def block_steps(st: dict, block: bool = True) -> list[Step]:
    unit = st.get("unit")
    if not unit:
        return []
    if block:
        return [Step("Stop the indexer and never start it", ["systemctl", "--user", "mask", "--now", unit])]
    return [Step("Allow the indexer to run again", ["systemctl", "--user", "unmask", unit]),
            Step("Start it", ["systemctl", "--user", "start", unit], optional=True)]


def gnome_search_settings() -> list[str]:
    return ["gnome-control-center", "search"] if has("gnome-control-center") else []


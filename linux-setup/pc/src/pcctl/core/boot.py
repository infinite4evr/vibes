"""Boot and login: the GRUB boot menu, boot speed (critical chain, chart, history), delaying login apps, and your own
services that start when you log in. No GTK here (used by the desktop page, the terminal UI and the CLI).
"""

from __future__ import annotations

import difflib
import glob
import grp
import os
import pwd
import re
import shlex
import shutil
from pathlib import Path

from .run import HOME, Step, has, out, py_step, read, sh

# ---------------------------------------------------------------- F1: GRUB boot menu

GRUB_FILE = Path("/etc/default/grub")
GRUB_DROPINS = Path("/etc/default/grub.d")
GRUB_BACKUP = Path("/etc/default/grub.pc-backup")
GRUB_CFG = Path("/boot/grub/grub.cfg")
GRUBENV = Path("/boot/grub/grubenv")
CACHE = HOME / ".cache/pc-command-center"
CFG_COPY = CACHE / "grub.cfg"
STAGED = CACHE / "grub.new"
LOADER_INFO = Path("/sys/firmware/efi/efivars/LoaderInfo-4a67b082-0a4c-41cf-b6c7-440b29bb8c4f")

KEYS = ("GRUB_DEFAULT", "GRUB_SAVEDEFAULT", "GRUB_TIMEOUT_STYLE", "GRUB_TIMEOUT", "GRUB_CMDLINE_LINUX_DEFAULT", "GRUB_DISABLE_OS_PROBER")
STYLES = [("menu", "Always show the menu", "You see the list of systems every time and pick one (or wait for the countdown)."),
          ("countdown", "Show only a countdown", "A short countdown; press Esc during it to see the menu."),
          ("hidden", "Hide the menu", "Starts straight away. Hold Shift (or tap Esc) while the PC starts to see the menu.")]

_ASSIGN = re.compile(r"^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)=(.*)$")


def _unquote(raw: str) -> str:
    raw = raw.strip()
    try:
        return " ".join(shlex.split(raw, comments=True))
    except ValueError:
        return raw.strip("'\"")


def parse_grub_default(text: str) -> dict[str, str]:
    """KEY=value lines of /etc/default/grub (a shell file). The last assignment wins, like in the shell."""
    vals: dict[str, str] = {}
    for line in text.splitlines():
        m = _ASSIGN.match(line)
        if m:
            vals[m.group(1)] = _unquote(m.group(2))
    return vals


def grub_settings(vals: dict[str, str]) -> dict:
    """The settings in plain terms: timeout (s, -1 = wait for me), style, default entry, remember, quiet, splash, os_prober."""
    try:
        timeout = int(float(vals.get("GRUB_TIMEOUT", "5") or 5))
    except ValueError:
        timeout = 5
    default = vals.get("GRUB_DEFAULT", "0") or "0"
    cmd = vals.get("GRUB_CMDLINE_LINUX_DEFAULT", "")
    toks = cmd.split()
    osp = vals.get("GRUB_DISABLE_OS_PROBER")
    return {"timeout": timeout, "style": (vals.get("GRUB_TIMEOUT_STYLE") or "menu").lower(), "default": default,
            "remember": default == "saved" and vals.get("GRUB_SAVEDEFAULT", "").lower() == "true",
            "quiet": "quiet" in toks, "splash": "splash" in toks, "cmdline": cmd,
            "os_prober": None if osp is None else osp.lower() == "false"}


def cmdline_set(cmdline: str, flag: str, on: bool) -> str:
    toks = [t for t in cmdline.split() if t != flag]
    if on:
        # keep the usual order: quiet before splash
        if flag == "quiet" and "splash" in toks:
            toks.insert(toks.index("splash"), flag)
        else:
            toks.append(flag)
    return " ".join(toks)


def settings_changes(vals: dict[str, str], want: dict) -> dict[str, str | None]:
    """Turn friendly choices into /etc/default/grub key changes (None = comment the line out). Only real changes are returned."""
    cur = grub_settings(vals)
    new: dict[str, str | None] = {}
    if "timeout" in want:
        new["GRUB_TIMEOUT"] = str(int(want["timeout"]))
    if "style" in want:
        new["GRUB_TIMEOUT_STYLE"] = want["style"]
    if want.get("remember"):
        new["GRUB_DEFAULT"] = "saved"
        new["GRUB_SAVEDEFAULT"] = "true"
    elif "default" in want or "remember" in want:
        d = want.get("default", cur["default"])
        new["GRUB_DEFAULT"] = "0" if d == "saved" else d
        if vals.get("GRUB_SAVEDEFAULT") is not None:
            new["GRUB_SAVEDEFAULT"] = None
    cmd = cur["cmdline"]
    for flag in ("quiet", "splash"):
        if flag in want:
            cmd = cmdline_set(cmd, flag, bool(want[flag]))
    if cmd != cur["cmdline"]:
        new["GRUB_CMDLINE_LINUX_DEFAULT"] = cmd
    if "os_prober" in want and want["os_prober"] is not None:
        new["GRUB_DISABLE_OS_PROBER"] = "false" if want["os_prober"] else "true"
    return {k: v for k, v in new.items() if vals.get(k) != v}


def _grub_quote(key: str, v: str) -> str:
    if key != "GRUB_CMDLINE_LINUX_DEFAULT" and re.fullmatch(r"[A-Za-z0-9_.,:/+@-]+", v):
        return v
    return '"' + re.sub(r'(["\\$`])', r"\\\1", v) + '"'


def grub_edit(text: str, changes: dict[str, str | None]) -> str:
    """Apply key changes to the file text, keeping comments and everything else as it was."""
    lines = text.splitlines()
    done: set[str] = set()
    res = []
    for line in lines:
        m = _ASSIGN.match(line)
        if m and m.group(1) in changes:
            key, v = m.group(1), changes[m.group(1)]
            if key in done or v is None:
                res.append("#" + line)          # switched off, or a later duplicate that would override our value
            else:
                res.append(f"{key}={_grub_quote(key, v)}")
            done.add(key)
            continue
        res.append(line)
    for key, v in changes.items():
        if key in done or v is None:
            continue
        new = f"{key}={_grub_quote(key, v)}"
        tmpl = next((i for i, ln in enumerate(res) if re.match(rf"^\s*#\s*{key}=", ln)), None)
        if tmpl is not None:
            res.insert(tmpl + 1, new)
        else:
            while res and not res[-1].strip():
                res.pop()
            res.append(new)
    return "\n".join(res) + "\n"


def grub_diff(old: str, new: str) -> str:
    """Just the changed lines, for the confirmation dialog."""
    d = difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0)
    return "\n".join(ln for ln in d if ln[:1] in "+-" and not ln.startswith(("+++", "---")))


def describe_changes(changes: dict[str, str | None]) -> list[str]:
    """The key changes in plain words, one line each."""
    res = []
    styles = {k: t for k, t, _ in STYLES}
    if "GRUB_TIMEOUT_STYLE" in changes and changes["GRUB_TIMEOUT_STYLE"]:
        res.append(f"Menu: {styles.get(changes['GRUB_TIMEOUT_STYLE'], changes['GRUB_TIMEOUT_STYLE']).lower()}.")
    if changes.get("GRUB_TIMEOUT"):
        t = int(float(changes["GRUB_TIMEOUT"]))
        res.append("Wait until you choose (no countdown)." if t < 0 else f"Wait {t} second{'s' if t != 1 else ''} before starting the default.")
    if "GRUB_DEFAULT" in changes and changes["GRUB_DEFAULT"] is not None:
        d = changes["GRUB_DEFAULT"]
        res.append("Start the one you picked last time." if d == "saved" else "Start the first entry (normally Ubuntu)." if d == "0"
                   else f"Start “{d.split('>')[-1]}” by default.")
    if "GRUB_CMDLINE_LINUX_DEFAULT" in changes:
        toks = (changes["GRUB_CMDLINE_LINUX_DEFAULT"] or "").split()
        res.append("Quiet start with the Ubuntu logo." if "quiet" in toks and "splash" in toks else
                   "Show the text messages while starting." if "quiet" not in toks and "splash" not in toks else
                   "Start options: " + (" ".join(toks) or "none") + ".")
    if changes.get("GRUB_DISABLE_OS_PROBER"):
        res.append("Look for other systems like Windows." if changes["GRUB_DISABLE_OS_PROBER"] == "false" else "Don't look for other systems.")
    return res


def dropin_overrides(files: list[str] | None = None) -> dict[str, str]:
    """Settings that files in /etc/default/grub.d/ set again (they are read after /etc/default/grub and win)."""
    res = {}
    for f in files if files is not None else sorted(glob.glob(str(GRUB_DROPINS / "*.cfg"))):
        for k in parse_grub_default(read(f)):
            if k in KEYS:
                res[k] = f
    return res


def parse_grub_cfg(text: str) -> list[dict]:
    """Menu entries of /boot/grub/grub.cfg: title, id, depth, path ('Advanced options for Ubuntu>Ubuntu, with Linux …'),
    index ('1>2'), kind (menuentry | submenu), parent."""
    entries: list[dict] = []
    stack: list[dict] = []
    counters = [0]
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(menuentry|submenu)\s+(.*)$", line)
        if m:
            kind, rest = m.group(1), m.group(2)
            try:
                toks = shlex.split(rest)
            except ValueError:
                toks = [x[0] or x[1] for x in re.findall(r"'([^']*)'|\"([^\"]*)\"", rest)] or rest.split()
            title = toks[0] if toks else "?"
            eid = toks[toks.index("$menuentry_id_option") + 1] if "$menuentry_id_option" in toks[:-1] else ""
            parents = [s for s in stack if s["kind"] == "submenu"]
            idx = counters[-1]
            counters[-1] += 1
            entries.append({"title": title, "id": eid, "kind": kind, "depth": len(parents),
                            "path": ">".join([p["title"] for p in parents] + [title]),
                            "index": ">".join([str(p["idx"]) for p in parents] + [str(idx)]),
                            "parent": parents[-1]["title"] if parents else ""})
            if line.endswith("{"):
                stack.append({"kind": kind, "title": title, "idx": idx})
                if kind == "submenu":
                    counters.append(0)
            continue
        if line.endswith("{"):
            stack.append({"kind": "block"})
        elif line.startswith("}") and stack:
            top = stack.pop()
            if top["kind"] == "submenu":
                counters.pop()
    return entries


def parse_grubenv(text: str) -> dict[str, str]:
    res = {}
    for line in text.splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        res[k.strip()] = v.strip()
    return res


def find_entry(value: str, entries: list[dict]) -> dict | None:
    """Which menu entry a GRUB_DEFAULT / saved_entry value points to (number, '1>2', title path or id path)."""
    value = value.strip()
    if not value:
        return None
    for e in entries:
        if e["kind"] != "menuentry":
            continue
        ids = ">".join(filter(None, [p["id"] for p in entries if p["kind"] == "submenu" and p["title"] == e["parent"]] + [e["id"]]))
        if value in (e["index"], e["path"], e["id"], ids) or (e["depth"] == 0 and value == e["title"]):
            return e
    return None


def bootloader(loader_info: Path | None = None, grub_file: Path | None = None) -> dict:
    """Which boot loader started this PC: 'grub', 'systemd-boot' or 'unknown', plus whether it's a UEFI PC."""
    loader_info = loader_info or LOADER_INFO
    grub_file = grub_file or GRUB_FILE
    detail = ""
    try:
        detail = loader_info.read_bytes()[4:].decode("utf-16-le", "ignore").rstrip("\x00").strip()
    except OSError:
        pass
    if "systemd-boot" in detail.lower():
        name = "systemd-boot"
    elif grub_file.exists() or "grub" in detail.lower():
        name = "grub"
    elif detail:
        name = detail.split()[0].lower()
    else:
        name = "unknown"
    return {"name": name, "detail": detail, "efi": os.path.isdir("/sys/firmware/efi"), "grub_file": grub_file.exists()}


def read_grub_cfg() -> tuple[str | None, str]:
    """(text, where it came from: 'live' | 'copy' | 'stale-copy' | 'denied' | 'missing')."""
    try:
        return GRUB_CFG.read_text(errors="replace"), "live"
    except PermissionError:
        text = read(CFG_COPY)
        if not text:
            return None, "denied"
        try:
            stale = CFG_COPY.stat().st_mtime < GRUB_CFG.stat().st_mtime
        except OSError:
            stale = False
        return text, "stale-copy" if stale else "copy"
    except OSError:
        return None, "missing"


def _me() -> tuple[str, str]:
    try:
        user = pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        user = os.environ.get("USER", "root")
    try:
        group = grp.getgrgid(os.getgid()).gr_name
    except KeyError:
        group = user
    return user, group


def copy_grub_cfg_steps() -> list[Step]:
    """grub.cfg is sometimes readable by admins only: make a private copy this app can read."""
    user, group = _me()
    return [Step("Make a private copy of the boot menu list for this app to read",
                 ["install", "-D", "-m", "600", "-o", user, "-g", group, str(GRUB_CFG), str(CFG_COPY)], root=True)]


def update_grub_cmd() -> list[str]:
    if has("update-grub") or not has("grub-mkconfig"):
        return ["update-grub"]
    return ["grub-mkconfig", "-o", str(GRUB_CFG)]


def grub_apply_steps(new_text: str, refresh_copy: bool = False, diff: str = "") -> list[Step]:
    """Save a new /etc/default/grub (keeping a backup of the old one) and rebuild the boot menu.
    `diff` (from grub_diff) is shown with the first step so the exact line changes are visible before confirming."""
    def stage() -> str:
        CACHE.mkdir(parents=True, exist_ok=True)
        STAGED.write_text(new_text)
        os.chmod(STAGED, 0o600)
        return f"wrote {STAGED}"
    shown = f"write the new settings to {STAGED}" + (f"; the changed lines (- old, + new):\n{diff}" if diff else "")
    steps = [py_step("Prepare the new settings", stage, shown),
             Step("Keep a backup of the current settings", ["cp", "-a", str(GRUB_FILE), str(GRUB_BACKUP)], root=True),
             Step("Save the new boot menu settings", ["install", "-m", "644", str(STAGED), str(GRUB_FILE)], root=True),
             Step("Rebuild the boot menu", update_grub_cmd(), root=True)]
    if refresh_copy:
        steps += [Step(s.title, s.cmd, root=True, optional=True) for s in copy_grub_cfg_steps()]
    return steps


def grub_restore_steps() -> list[Step]:
    return [Step("Put back the settings from before the last change", ["install", "-m", "644", str(GRUB_BACKUP), str(GRUB_FILE)], root=True),
            Step("Rebuild the boot menu", update_grub_cmd(), root=True)]


def grub_info() -> dict:
    """Everything the Boot menu tab shows."""
    text = read(GRUB_FILE)
    vals = parse_grub_default(text)
    cfg, cfg_from = read_grub_cfg()
    entries = parse_grub_cfg(cfg) if cfg else []
    env = parse_grubenv(read(GRUBENV))
    return {"loader": bootloader(), "text": text, "vals": vals, "settings": grub_settings(vals), "dropins": dropin_overrides(),
            "entries": entries, "cfg_from": cfg_from, "env": env, "backup": GRUB_BACKUP.exists(),
            "saved": find_entry(env.get("saved_entry", ""), entries)}


# ---------------------------------------------------------------- F2: delay a login app

USER_AUTOSTART = HOME / ".config/autostart"
USER_UNITS = HOME / ".config/systemd/user"
DELAY_KEY = "X-GNOME-Autostart-Delay"


def autostart_delay(text: str) -> int:
    in_entry = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("["):
            in_entry = s == "[Desktop Entry]"
        elif in_entry and s.startswith(DELAY_KEY + "="):
            try:
                return max(0, int(float(s.split("=", 1)[1])))
            except ValueError:
                return 0
    return 0


def set_delay_in_text(text: str, seconds: int) -> str:
    res, in_entry, added = [], False, False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("["):
            in_entry = s == "[Desktop Entry]"
            res.append(line)
            if in_entry and seconds > 0 and not added:
                res.append(f"{DELAY_KEY}={int(seconds)}")
                added = True
            continue
        if in_entry and s.startswith(DELAY_KEY + "="):
            continue
        res.append(line)
    return "\n".join(res) + "\n"


def systemd_escape(s: str) -> str:
    """Like `systemd-escape`: keep letters, digits, ':', '_' and '.', turn '/' into '-', hex-escape the rest."""
    res = []
    for i, ch in enumerate(s):
        if ch == "/":
            res.append("-")
        elif (ch.isascii() and ch.isalnum()) or ch in ":_" or (ch == "." and i > 0):
            res.append(ch)
        else:
            res.append("".join(f"\\x{b:02x}" for b in ch.encode()))
    return "".join(res)


def autostart_unit(desktop_id: str) -> str:
    """The service systemd makes for a login app (GNOME starts login apps through systemd)."""
    return f"app-{systemd_escape(desktop_id.removesuffix('.desktop'))}@autostart.service"


def set_autostart_delay(desktop_id: str, source_file: str, seconds: int, autostart_dir: Path | None = None,
                        unit_dir: Path | None = None) -> str:
    """Open a login app N seconds after you log in (0 = right away).

    Writes X-GNOME-Autostart-Delay into your copy in ~/.config/autostart (copying Ubuntu's file there first), and a
    small systemd drop-in that waits too, because GNOME now starts login apps through systemd, which ignores that key."""
    autostart_dir = autostart_dir or USER_AUTOSTART
    unit_dir = unit_dir or USER_UNITS
    seconds = max(0, min(int(seconds), 80))
    autostart_dir.mkdir(parents=True, exist_ok=True)
    target = autostart_dir / desktop_id
    if not target.exists() and source_file and os.path.abspath(source_file) != str(target):
        shutil.copy(source_file, target)
    target.write_text(set_delay_in_text(read(target), seconds))
    dropdir = unit_dir / (autostart_unit(desktop_id) + ".d")
    conf = dropdir / "pc-delay.conf"
    if seconds > 0:
        dropdir.mkdir(parents=True, exist_ok=True)
        sleep = shutil.which("sleep") or "/usr/bin/sleep"
        conf.write_text(f"# Written by PC Command Center: wait before opening this login app\n[Service]\nExecStartPre={sleep} {seconds}\n")
        return f"it will open {seconds} s after you log in"
    try:
        conf.unlink()
        dropdir.rmdir()
    except OSError:
        pass
    return "it will open right away when you log in"


# ---------------------------------------------------------------- F3: boot speed

def parse_span(text: str) -> float:
    """systemd time spans: '1min 2.345s', '296ms', '12.303s', '1h 2min 3s' → seconds."""
    total = 0.0
    for num, unit in re.findall(r"([\d.]+)\s*(h|min|ms|us|µs|s)\b", text):
        v = float(num)
        total += {"h": 3600, "min": 60, "s": 1, "ms": 0.001, "us": 1e-6, "µs": 1e-6}[unit] * v
    return total


def parse_time(text: str) -> dict:
    """`systemd-analyze time` → {firmware, loader, kernel, initrd, userspace, total, target, target_at}."""
    res: dict = {}
    first = text.strip().splitlines()[0] if text.strip() else ""
    for part in ("firmware", "loader", "kernel", "initrd", "userspace"):
        m = re.search(r"((?:[\d.]+\s*(?:h|min|ms|us|s)\s*)+)\(" + part + r"\)", first)
        if m:
            res[part] = parse_span(m.group(1))
    m = re.search(r"=\s*((?:[\d.]+\s*(?:h|min|ms|us|s)\s*)+)", first)
    if m:
        res["total"] = parse_span(m.group(1))
    m = re.search(r"^(\S+) reached after (.+?) in userspace", text, re.M)
    if m:
        res["target"], res["target_at"] = m.group(1), parse_span(m.group(2))
    return res


def parse_blame(text: str, limit: int = 15) -> list[tuple[float, str]]:
    res = []
    for line in text.splitlines():
        m = re.match(r"^\s*((?:[\d.]+\s*(?:h|min|ms|us|s)\s*)+)\s(\S+)\s*$", line)
        if m:
            res.append((parse_span(m.group(1)), m.group(2)))
            if len(res) >= limit:
                break
    return res


def parse_critical_chain(text: str) -> list[dict]:
    """`systemd-analyze critical-chain` → [{unit, at (s after start), took (s), depth}], top-level target first."""
    res = []
    for line in text.splitlines():
        m = re.match(r"^([\s│├└─|`-]*)(\S+\.(?:target|service|socket|mount|device|swap|timer|path|slice|scope))\s*(.*)$", line)
        if not m:
            continue
        prefix, unit, rest = m.groups()
        at = re.search(r"@((?:[\d.]+\s*(?:h|min|ms|us|s)\s*)+)", rest)
        took = re.search(r"\+((?:[\d.]+\s*(?:h|min|ms|us|s)\s*)+)", rest)
        res.append({"unit": unit, "at": parse_span(at.group(1)) if at else 0.0, "took": parse_span(took.group(1)) if took else 0.0,
                    "depth": len(prefix) // 2})
    return res


# plain words for units that often show up in the slow list
UNIT_WORDS = {
    "NetworkManager-wait-online.service": "Waits until the network is connected. Safe to switch off on most desktops and laptops.",
    "systemd-networkd-wait-online.service": "Waits until the network is connected.",
    "plymouth-quit-wait.service": "The boot splash screen waiting for the login screen. Usually just waiting on something else.",
    "snapd.seeded.service": "Snap getting ready. Slow right after snaps are installed or updated.",
    "snapd.service": "Snap apps service.",
    "docker.service": "Docker engine.",
    "containerd.service": "Container runtime used by Docker.",
    "apt-daily.service": "Checks for updates in the background.",
    "apt-daily-upgrade.service": "Installs security updates in the background.",
    "fwupd.service": "Firmware update checker.",
    "cloud-init.service": "Cloud setup. Not needed on a normal PC.",
    "dev-loop": "Snap app images being attached.",
    "systemd-udev-settle.service": "Waits for all hardware to be detected (old-style; slows boot).",
    "gdm.service": "The login screen.",
    "gdm3.service": "The login screen.",
    "graphical.target": "Everything needed for the desktop is ready.",
    "multi-user.target": "The basic system is ready.",
    "network-online.target": "The network is up.",
    "plymouth-start.service": "The boot splash screen.",
    "systemd-journal-flush.service": "Saving the startup log to disk. Slow when the log is very large.",
    "e2scrub_reap.service": "Cleans up after disk checks.",
    "ModemManager.service": "Mobile broadband modems.",
    "accounts-daemon.service": "User accounts.",
    "udisks2.service": "Disks and USB drives.",
    "power-profiles-daemon.service": "Power modes.",
    "systemd-fsck": "Disk check before mounting.",
}


def explain_unit(unit: str) -> str:
    if unit in UNIT_WORDS:
        return UNIT_WORDS[unit]
    for k, v in UNIT_WORDS.items():
        if unit.startswith(k):
            return v
    if unit.startswith("snap-") and unit.endswith(".mount"):
        return "A snap app being attached."
    if unit.endswith(".mount"):
        return "A drive or folder being attached."
    if unit.endswith(".device"):
        return "Hardware being detected."
    return ""


def analyze() -> dict:
    """Boot times, the slowest units, and the critical chain."""
    if not has("systemd-analyze"):
        return {"available": False}
    t = sh(["systemd-analyze", "time"], timeout=15)
    info = parse_time(t.out)
    info["available"] = bool(info.get("total"))
    info["error"] = "" if t.ok else (t.err.strip() or "systemd-analyze did not answer")
    info["blame"] = parse_blame(out(["systemd-analyze", "blame", "--no-pager"], timeout=15))
    info["chain"] = parse_critical_chain(out(["systemd-analyze", "critical-chain", "--no-pager"], timeout=15))
    return info


FINISHED_ID = "b07a249cd024414a82dd00cd181378ff"  # systemd's "Startup finished" journal message


def parse_boot_history(text: str) -> list[dict]:
    """`journalctl -o short-unix MESSAGE_ID=… _PID=1` lines → [{when, total, firmware, loader, kernel, initrd, userspace}]."""
    res = []
    for line in text.splitlines():
        m = re.match(r"^(\d+(?:\.\d+)?)\s+\S+\s+\S+:\s+(Startup finished in .*)$", line)
        if not m:
            continue
        info = parse_time(m.group(2))
        if info.get("total"):
            info["when"] = float(m.group(1))
            res.append(info)
    return res


def boot_history(limit: int = 12) -> list[dict]:
    if not has("journalctl"):
        return []
    text = out(["journalctl", "--no-pager", "-q", "-o", "short-unix", f"MESSAGE_ID={FINISHED_ID}", "_PID=1"], timeout=20)
    return parse_boot_history(text)[-limit:]


def pictures_dir() -> Path:
    d = out(["xdg-user-dir", "PICTURES"], timeout=5) if has("xdg-user-dir") else ""
    return Path(d) if d and d != str(HOME) else HOME / "Pictures"


def plot_steps(dest: Path | None = None) -> tuple[list[Step], Path]:
    dest = dest or pictures_dir() / "boot-chart.svg"
    tmp = dest.parent / f".{dest.name}.part"
    q, t, d = shlex.quote(str(dest)), shlex.quote(str(tmp)), shlex.quote(str(dest.parent))
    cmd = f"mkdir -p {d} && systemd-analyze plot > {t} && mv -f {t} {q} || {{ rm -f {t}; false; }}"
    return [Step("Draw a chart of the last boot", ["bash", "-c", cmd])], dest


# ---------------------------------------------------------------- F4: your services that start at login

# base name → (what it does, keep it on?)
USER_WORDS = {
    "pipewire": ("Sound, microphones and screen sharing.", True),
    "pipewire-pulse": ("Lets apps made for the older sound system (PulseAudio) play sound.", True),
    "wireplumber": ("Picks your speakers, headphones and microphone.", True),
    "filter-chain": ("Sound effects and filters for PipeWire.", False),
    "gnome-keyring-daemon": ("Keeps your saved passwords and keys unlocked while you're logged in.", True),
    "gcr-ssh-agent": ("Remembers your SSH key passwords while you're logged in.", True),
    "ssh-agent": ("Remembers your SSH key passwords while you're logged in.", True),
    "gpg-agent": ("Remembers your GPG key password for a while.", False),
    "dirmngr": ("Fetches GPG keys from the internet when needed.", False),
    "localsearch-3": ("Indexes your files so searching in Files and Activities finds them. Uses some CPU after big changes.", False),
    "localsearch-control-3": ("Controls the file indexer.", False),
    "tracker-miner-fs-3": ("Indexes your files so searching in Files and Activities finds them. Uses some CPU after big changes.", False),
    "tracker-extract-3": ("Reads inside files (text, photos) for search.", False),
    "xdg-user-dirs": ("Keeps folders like Documents and Downloads set up.", False),
    "xdg-desktop-portal": ("Lets sandboxed apps open files and share the screen.", True),
    "xdg-desktop-portal-gnome": ("GNOME's file picker and screen sharing for sandboxed apps.", True),
    "xdg-desktop-portal-gtk": ("File pickers for sandboxed apps.", True),
    "xdg-document-portal": ("Gives sandboxed apps access to files you pick.", True),
    "xdg-permission-store": ("Remembers what sandboxed apps may do.", True),
    "dbus": ("Lets apps talk to each other. Needed.", True),
    "gvfs-daemon": ("Shows USB drives, phones and network folders in Files.", True),
    "gvfs-udisks2-volume-monitor": ("Notices USB drives you plug in.", True),
    "gvfs-mtp-volume-monitor": ("Notices phones you plug in.", False),
    "gvfs-gphoto2-volume-monitor": ("Notices cameras you plug in.", False),
    "gvfs-afc-volume-monitor": ("Notices iPhones you plug in.", False),
    "gvfs-goa-volume-monitor": ("Online accounts in Files (Google Drive…).", False),
    "evolution-source-registry": ("Calendar and contacts for GNOME apps.", False),
    "evolution-calendar-factory": ("Calendar for GNOME apps.", False),
    "evolution-addressbook-factory": ("Contacts for GNOME apps.", False),
    "obex": ("Sends and receives files over Bluetooth.", False),
    "at-spi-dbus-bus": ("Accessibility (screen readers).", False),
    "update-notifier": ("Tells you when updates are ready.", False),
    "gnome-remote-desktop": ("Lets you control this PC from another computer (Remote Desktop).", False),
    "gnome-remote-desktop-headless": ("Remote login without a screen.", False),
    "syncthing": ("Syncs folders between your devices.", False),
    "podman": ("Podman containers (rootless).", False),
    "docker": ("Docker for your user (rootless).", False),
    "snapd.session-agent": ("Lets snaps ask you things (permissions, updates).", False),
    "pulseaudio": ("The older sound system.", True),
    "pc-maintain": ("PC Command Center's weekly check-up.", False),
    "pc-watch": ("PC Command Center's background alerts (disk full, overheating, failed services).", False),
    "ubuntu-report": ("Asks once whether to send hardware info to Ubuntu.", False),
    "ubuntu-insights": ("Ubuntu usage reports (only if you agreed).", False),
    "orca": ("Screen reader.", False),
    "emacs": ("Emacs server for fast opening.", False),
    "onedrive": ("OneDrive sync.", False),
    "rclone": ("Cloud drive mount.", False),
    "ollama": ("Local AI models (Ollama).", False),
}


def unit_base(unit: str) -> str:
    return re.sub(r"\.(service|timer|socket|path|target|mount)$", "", unit).split("@")[0]


def user_unit_title(unit: str) -> str:
    """A readable name: 'snap.snapd-desktop-integration.snapd-desktop-integration.service' → 'snapd-desktop-integration (snap)'."""
    m = re.match(r"^snap\.([^.]+)\.([^.]+)\.", unit)
    if m:
        return f"{m.group(1)} (snap)" if m.group(1) == m.group(2) else f"{m.group(1)}: {m.group(2)} (snap)"
    kind = unit.rsplit(".", 1)[-1]
    return unit_base(unit) + ({"socket": " (on demand)", "timer": " (schedule)", "path": " (file watcher)"}.get(kind, ""))


def explain_user_unit(unit: str) -> tuple[str, bool]:
    base = unit_base(unit)
    if base in USER_WORDS:
        return USER_WORDS[base]
    m = re.match(r"^snap\.([^.]+)\.", unit)
    if m:
        return (f"Background part of the “{m.group(1)}” snap.", False)
    return ("", False)


def parse_unit_list(text: str) -> dict[str, dict]:
    """`systemctl list-units --all --plain --no-legend` → {unit: {load, active, sub, description}}."""
    res = {}
    for line in text.splitlines():
        parts = line.lstrip("● ").split(None, 4)
        if len(parts) >= 4 and "." in parts[0]:
            res[parts[0]] = {"load": parts[1], "active": parts[2], "sub": parts[3], "description": parts[4] if len(parts) > 4 else ""}
    return res


def parse_unit_file_list(text: str) -> dict[str, str]:
    """`systemctl list-unit-files --plain --no-legend` → {unit: state}."""
    res = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and "." in parts[0] and not parts[0].endswith(("listed.", "files")):
            res[parts[0]] = parts[1]
    return res


def user_services(files_text: str | None = None, units_text: str | None = None, own_dir: Path | None = None) -> dict:
    """Your own services (systemd --user) that start at login: {available, error, units: [...]}."""
    own_dir = own_dir or USER_UNITS
    if files_text is None:
        r = sh(["systemctl", "--user", "list-unit-files", "--no-legend", "--plain", "--no-pager"], timeout=15)
        if not r.ok and not r.out.strip():
            return {"available": False, "error": (r.err.strip() or "systemctl --user did not answer").splitlines()[0], "units": []}
        files_text = r.out
    if units_text is None:
        units_text = out(["systemctl", "--user", "list-units", "--all", "--no-legend", "--plain", "--no-pager"], timeout=15)
    files = parse_unit_file_list(files_text)
    live = parse_unit_list(units_text)
    mine = {os.path.basename(f) for f in glob.glob(str(own_dir / "*"))}
    res = []
    for unit, state in files.items():
        if not unit.endswith((".service", ".timer", ".socket", ".path")) or unit.endswith("@.service"):
            continue
        interesting = state == "enabled" or (unit in mine and state in ("disabled", "linked"))
        if not interesting:
            continue
        info = live.get(unit, {})
        what, keep = explain_user_unit(unit)
        res.append({"unit": unit, "name": unit_base(unit), "title": user_unit_title(unit), "kind": unit.rsplit(".", 1)[-1], "state": state,
                    "active": info.get("active", "inactive"), "sub": info.get("sub", "dead"), "description": info.get("description", ""),
                    "what": what, "keep": keep, "mine": unit in mine})
    res.sort(key=lambda u: (not u["mine"], u["keep"], u["name"].lower()))
    return {"available": True, "error": "", "units": res}


USER_ACTIONS = {"start": "Start", "stop": "Stop", "restart": "Restart", "enable": "Start at login", "disable": "Don't start at login",
                "enable --now": "Turn on (now and at every login)", "disable --now": "Turn off (now and at every login)"}


def user_unit_steps(unit: str, action: str) -> list[Step]:
    return [Step(f"{USER_ACTIONS.get(action, action)}: {unit_base(unit)}", ["systemctl", "--user", *action.split(), unit])]


def user_unit_logs(unit: str, lines: int = 200) -> str:
    target = unit
    if unit.endswith(".timer"):
        target = unit.removesuffix(".timer") + ".service"   # a timer's work shows up in its service's log
    r = sh(["journalctl", "--user-unit", target, "-n", str(lines), "--no-pager", "-o", "short-iso"], timeout=15)
    return r.out.strip() or r.err.strip() or "No log lines yet."

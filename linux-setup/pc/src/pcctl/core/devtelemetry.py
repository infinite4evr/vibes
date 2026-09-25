"""Developer tool telemetry off in one switch.

Many developer tools (Next.js, .NET, VS Code, Homebrew…) send anonymous usage data unless you opt out, each with
its own setting. This writes all the opt-outs in one go:
- ~/.config/environment.d/90-pc-no-telemetry.conf  → apps started from the desktop (after you log in again),
- a marked block in ~/.bashrc / ~/.zshenv and a fish conf.d file → every new terminal, right away,
- "telemetry.telemetryLevel": "off" in VS Code-style editors' settings.json (comments in the file are kept).
Turning it back on removes exactly what was added.
"""

from __future__ import annotations

import json
import os
import pwd
import re
from dataclasses import dataclass
from pathlib import Path

from . import run as _run
from .run import Step, has, py_step

BEGIN = "# >>> pc no-telemetry >>>"
END = "# <<< pc no-telemetry <<<"
ENV_REL = ".config/environment.d/90-pc-no-telemetry.conf"
FISH_REL = ".config/fish/conf.d/pc-no-telemetry.fish"
VSCODE_KEY = "telemetry.telemetryLevel"


@dataclass
class Var:
    name: str
    value: str
    tools: str                    # who reads it, in plain words
    cmds: tuple[str, ...] = ()    # commands that mean the tool is installed
    in_projects: bool = False     # a framework that lives inside projects (no global command)


VARS: list[Var] = [
    Var("NEXT_TELEMETRY_DISABLED", "1", "Next.js", in_projects=True),
    Var("NUXT_TELEMETRY_DISABLED", "1", "Nuxt", in_projects=True),
    Var("GATSBY_TELEMETRY_DISABLED", "1", "Gatsby", ("gatsby",), True),
    Var("ASTRO_TELEMETRY_DISABLED", "1", "Astro", in_projects=True),
    Var("NG_CLI_ANALYTICS", "false", "Angular CLI", ("ng",), True),
    Var("STORYBOOK_DISABLE_TELEMETRY", "1", "Storybook", in_projects=True),
    Var("TURBO_TELEMETRY_DISABLED", "1", "Turborepo", ("turbo",), True),
    Var("VERCEL_TELEMETRY_DISABLED", "1", "Vercel CLI", ("vercel",)),
    Var("NETLIFY_TELEMETRY_DISABLED", "1", "Netlify CLI", ("netlify",)),
    Var("EXPO_NO_TELEMETRY", "1", "Expo (React Native)", ("expo",), True),
    Var("WRANGLER_SEND_METRICS", "false", "Cloudflare Wrangler", ("wrangler",), True),
    Var("YARN_ENABLE_TELEMETRY", "0", "Yarn", ("yarn",)),
    Var("CHECKPOINT_DISABLE", "1", "Prisma, Terraform and other HashiCorp tools", ("terraform", "vagrant", "packer", "prisma"), True),
    Var("DOTNET_CLI_TELEMETRY_OPTOUT", "1", ".NET", ("dotnet",)),
    Var("POWERSHELL_TELEMETRY_OPTOUT", "1", "PowerShell", ("pwsh",)),
    Var("HOMEBREW_NO_ANALYTICS", "1", "Homebrew", ("brew",)),
    Var("AZURE_CORE_COLLECT_TELEMETRY", "0", "Azure CLI", ("az",)),
    Var("SAM_CLI_TELEMETRY", "0", "AWS SAM CLI", ("sam",)),
    Var("CLOUDSDK_CORE_DISABLE_USAGE_REPORTING", "true", "Google Cloud CLI", ("gcloud",)),
    Var("HF_HUB_DISABLE_TELEMETRY", "1", "Hugging Face libraries", ("huggingface-cli", "hf")),
    Var("GRADIO_ANALYTICS_ENABLED", "False", "Gradio", ("gradio",), True),
    Var("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false", "Streamlit", ("streamlit",), True),
    Var("DISABLE_TELEMETRY", "1", "Claude Code", ("claude",)),
    Var("DO_NOT_TRACK", "1", "Everything that follows the \"Do Not Track\" convention (Bun and others)", ("bun",)),
]

EDITORS = [("VS Code", ".config/Code/User/settings.json", "code"), ("VS Code Insiders", ".config/Code - Insiders/User/settings.json", "code-insiders"),
           ("VSCodium", ".config/VSCodium/User/settings.json", "codium"), ("Cursor", ".config/Cursor/User/settings.json", "cursor"),
           ("Windsurf", ".config/Windsurf/User/settings.json", "windsurf")]


def _home(home: Path | None) -> Path:
    return Path(home) if home else _run.HOME


def _short(p: Path, home: Path) -> str:
    s, h = str(p), str(home)
    return "~" + s[len(h):] if s.startswith(h + "/") else s


# ---------------------------------------------------------------- file contents

def env_file_text() -> str:
    lines = ["# Added by PC Command Center: tells developer tools not to send usage data.",
             "# Delete this file (or use the switch on the Privacy page) to undo. Takes effect after you log in again."]
    lines += [f"{v.name}={v.value}" for v in VARS]
    return "\n".join(lines) + "\n"


def shell_block() -> str:
    lines = [BEGIN, "# Added by PC Command Center: tells developer tools not to send usage data. Remove this block to undo."]
    lines += [f"export {v.name}={v.value}" for v in VARS]
    return "\n".join(lines + [END]) + "\n"


def fish_text() -> str:
    lines = ["# Added by PC Command Center: tells developer tools not to send usage data. Delete this file to undo."]
    lines += [f"set -gx {v.name} {v.value}" for v in VARS]
    return "\n".join(lines) + "\n"


def remove_block(text: str) -> str:
    """text without the marked block (and the blank line we put before it)."""
    return re.sub(r"\n?" + re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", "\n", text, flags=re.S).rstrip("\n") + ("\n" if text.strip() else "")


def add_block(text: str) -> str:
    base = remove_block(text) if BEGIN in text else text
    if base and not base.endswith("\n"):
        base += "\n"
    return base + ("\n" if base.strip() else "") + shell_block()


def login_shell() -> str:
    try:
        return os.path.basename(pwd.getpwuid(os.getuid()).pw_shell)
    except (KeyError, OSError):
        return os.path.basename(os.environ.get("SHELL", "bash"))


def shell_targets(home: Path | None = None, shell: str | None = None) -> list[tuple[Path, str]]:
    """Where terminal settings go: (path, 'block' | 'file')."""
    h = _home(home)
    shell = shell if shell is not None else (login_shell() if h == _run.HOME else "bash")
    res: list[tuple[Path, str]] = []
    if (h / ".bashrc").exists() or shell == "bash":
        res.append((h / ".bashrc", "block"))
    if shell == "zsh" or (h / ".zshrc").exists() or (h / ".zshenv").exists():
        res.append((h / ".zshenv", "block"))
    if shell == "fish" or (h / ".config/fish").is_dir():
        res.append((h / FISH_REL, "file"))
    return res


# ---------------------------------------------------------------- VS Code settings.json (JSON with comments)

def _comment_spans(text: str) -> list[tuple[int, int]]:
    """Where the // and /* */ comments are (outside strings)."""
    spans, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
        elif text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            spans.append((i, j))
            i = j
            continue
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            spans.append((i, j))
            i = j
            continue
        i += 1
    return spans


def strip_jsonc(text: str) -> str:
    """Comments and trailing commas removed, so json.loads can read VS Code's settings.json."""
    out, pos = [], 0
    for s, e in _comment_spans(text):
        out.append(text[pos:s])
        pos = e
    out.append(text[pos:])
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def load_jsonc(text: str) -> dict | None:
    if not text.strip():
        return {}
    try:
        d = json.loads(strip_jsonc(text))
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def _find_key(text: str, key: str) -> re.Match | None:
    spans = _comment_spans(text)
    for m in re.finditer(r'"' + re.escape(key) + r'"\s*:\s*("(?:[^"\\]|\\.)*"|[^,}\s]+)', text):
        if not any(s <= m.start() < e for s, e in spans):
            return m
    return None


def jsonc_set(text: str, key: str, value) -> str | None:
    """Set a top-level key, keeping comments and formatting. None if the file can't be understood."""
    d = load_jsonc(text)
    if d is None:
        return None
    try:
        strict = json.loads(text) if text.strip() else {}
    except ValueError:
        strict = None
    if isinstance(strict, dict):
        strict[key] = value
        return json.dumps(strict, indent=4) + "\n"
    m = _find_key(text, key)
    val = json.dumps(value)
    if m:
        return text[:m.start(1)] + val + text[m.end(1):]
    spans = _comment_spans(text)
    brace = next((i for i, c in enumerate(text) if c == "{" and not any(s <= i < e for s, e in spans)), -1)
    if brace < 0:
        return None
    entry = f'\n    "{key}": {val}' + ("," if d else "")
    return text[:brace + 1] + entry + text[brace + 1:]


def jsonc_remove(text: str, key: str) -> str:
    try:
        strict = json.loads(text)
    except ValueError:
        strict = None
    if isinstance(strict, dict):
        if key not in strict:
            return text
        strict.pop(key)
        return json.dumps(strict, indent=4) + "\n"
    m = _find_key(text, key)
    if not m:
        return text
    end = m.end()
    tail = re.match(r"\s*,", text[end:])
    if tail:
        end += tail.end()
    start = m.start()
    while start > 0 and text[start - 1] in " \t":
        start -= 1
    if start > 0 and text[start - 1] == "\n":
        start -= 1
    return text[:start] + text[end:]


def editors(home: Path | None = None) -> list[dict]:
    """VS Code-style editors that are installed: {name, path, level ('all' when not set), readable}."""
    h = _home(home)
    res = []
    for name, rel, cmd in EDITORS:
        p = h / rel
        if not p.exists() and not (home is None and has(cmd)):
            continue
        text = _run.read(p)
        d = load_jsonc(text)
        level = (d or {}).get(VSCODE_KEY, "all") if d is not None else "?"
        res.append({"name": name, "path": str(p), "level": level, "readable": d is not None, "exists": p.exists()})
    return res


def _set_editor(path: str, off: bool) -> str:
    p = Path(path)
    text = _run.read(p)
    if off:
        new = jsonc_set(text, VSCODE_KEY, "off")
        if new is None:
            return f"Skipped {p}: it isn't valid settings JSON, so it was left alone. Set Telemetry: Telemetry Level to off in the editor."
    else:
        d = load_jsonc(text)
        if d is None or d.get(VSCODE_KEY) != "off":
            return f"Left {p} as it is."
        new = jsonc_remove(text, VSCODE_KEY)
    if new == text:
        return f"{p} already set."
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        backup = p.with_name(p.name + ".pc-backup")
        backup.write_text(text)
    p.write_text(new)
    return f"Updated {p}" + (" (old version saved as settings.json.pc-backup)" if text else "")


# ---------------------------------------------------------------- status + actions

def status(home: Path | None = None, env: dict | None = None) -> dict:
    h = _home(home)
    env = os.environ if env is None else env
    env_text = _run.read(h / ENV_REL)
    targets = shell_targets(h if home else None)
    in_shell = any((BEGIN in _run.read(p)) if kind == "block" else p.exists() for p, kind in targets)
    rows = []
    for v in VARS:
        configured = re.search(rf"^{re.escape(v.name)}=", env_text, re.M) is not None
        now = env.get(v.name, "")
        off = configured or (now != "" and now.lower() == v.value.lower())
        installed = any(has(c) for c in v.cmds) if home is None else False
        rows.append({"var": v.name, "value": v.value, "tools": v.tools, "off": off, "installed": installed, "in_projects": v.in_projects,
                     "active_now": now.lower() == v.value.lower()})
    eds = editors(home)
    return {"configured": bool(env_text), "env_file": bool(env_text), "shell": in_shell, "vars": rows,
            "editors": eds, "off_count": sum(r["off"] for r in rows) + sum(e["level"] == "off" for e in eds),
            "total": len(rows) + len(eds), "flutter": has("flutter") if home is None else False, "dart": has("dart") if home is None else False}


def off_steps(home: Path | None = None, with_commands: bool = True) -> list[Step]:
    h = _home(home)
    envf = h / ENV_REL

    def write_env() -> str:
        envf.parent.mkdir(parents=True, exist_ok=True)
        envf.write_text(env_file_text())
        return f"Wrote {envf} ({len(VARS)} settings). Apps you start from the desktop pick it up after you log in again."
    steps = [py_step("For apps you open from the desktop", write_env, f"write {_short(envf, h)} with {len(VARS)} opt-out settings")]
    for p, kind in shell_targets(h if home else None):
        if kind == "block":
            def add(pp=p) -> str:
                pp.write_text(add_block(_run.read(pp)))
                return f"Added the no-telemetry block to {pp}"
            steps.append(py_step(f"For new terminals ({p.name})", add, f"add a marked block ({BEGIN}) to {_short(p, h)}"))
        else:
            def write_fish(pp=p) -> str:
                pp.parent.mkdir(parents=True, exist_ok=True)
                pp.write_text(fish_text())
                return f"Wrote {pp}"
            steps.append(py_step("For new fish terminals", write_fish, f"write {_short(p, h)}"))
    for e in editors(home):
        if e["level"] != "off":
            steps.append(py_step(f"Turn off {e['name']} telemetry", lambda pth=e["path"]: _set_editor(pth, True),
                                 f'set "{VSCODE_KEY}": "off" in {_short(Path(e["path"]), h)} (comments are kept)'))
    if with_commands and home is None:
        if has("flutter"):
            steps.append(Step("Turn off Flutter analytics", ["flutter", "--no-version-check", "config", "--no-analytics"], optional=True))
        if has("dart"):
            steps.append(Step("Turn off Dart analytics", ["dart", "--disable-analytics"], optional=True))
    return steps


def on_steps(home: Path | None = None, with_commands: bool = True) -> list[Step]:
    h = _home(home)
    envf = h / ENV_REL

    def rm_env() -> str:
        if envf.exists():
            envf.unlink()
            return f"Removed {envf}"
        return "Nothing to remove."
    steps = [py_step("Remove the desktop setting file", rm_env, f"delete {_short(envf, h)}")]
    for p, kind in shell_targets(h if home else None):
        if kind == "block":
            def rm_block(pp=p) -> str:
                text = _run.read(pp)
                if BEGIN not in text:
                    return f"{pp}: nothing to remove"
                pp.write_text(remove_block(text))
                return f"Removed the no-telemetry block from {pp}"
            steps.append(py_step(f"Remove the block from {p.name}", rm_block, f"remove the {BEGIN} block from {_short(p, h)}"))
        elif p.exists():
            steps.append(py_step("Remove the fish setting file", lambda pp=p: (pp.unlink(), f"Removed {pp}")[1], f"delete {_short(p, h)}"))
    for e in editors(home):
        if e["level"] == "off":
            steps.append(py_step(f"Let {e['name']} decide again", lambda pth=e["path"]: _set_editor(pth, False),
                                 f'remove "{VSCODE_KEY}" from {_short(Path(e["path"]), h)}'))
    if with_commands and home is None:
        if has("flutter"):
            steps.append(Step("Turn Flutter analytics back on", ["flutter", "--no-version-check", "config", "--analytics"], optional=True))
        if has("dart"):
            steps.append(Step("Turn Dart analytics back on", ["dart", "--enable-analytics"], optional=True))
    return steps

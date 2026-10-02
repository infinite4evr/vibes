"""`pc` command: no arguments opens the control center; subcommands print quick answers."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

from . import __version__
from .core.fmt import C, duration, human

R = "\033[0m"
B = "\033[1m"
DIM = "\033[2m"


def rgb(name: str) -> str:
    h = C[name].lstrip("#")
    return f"\033[38;2;{int(h[0:2], 16)};{int(h[2:4], 16)};{int(h[4:6], 16)}m"


LV = {"ok": (rgb("green"), "●"), "info": (rgb("blue"), "●"), "warn": (rgb("peach"), "▲"), "bad": (rgb("red"), "■")}


def cbar(pct: float, width: int = 24, warn: float = 75, crit: float = 90) -> str:
    pct = max(0.0, min(100.0, pct))
    n = round(pct / 100 * width)
    col = rgb("red") if pct >= crit else rgb("peach") if pct >= warn else rgb("green")
    return f"{col}{'━' * n}{rgb('surface1')}{'━' * (width - n)}{R}"


def title(t: str) -> None:
    print(f"\n{B}{rgb('mauve')}{t}{R}")


def prime_sudo() -> bool:
    if os.geteuid() == 0:
        return True
    if subprocess.call(["sudo", "-n", "true"], stderr=subprocess.DEVNULL) == 0:
        return True
    print(f"{rgb('mauve')}pc needs admin rights for this.{R} Enter your password:")
    return subprocess.call(["sudo", "-v"]) == 0


def confirm(q: str, default: bool = True) -> bool:
    try:
        a = input(f"{rgb('peach')}?{R} {q} {'[Y/n]' if default else '[y/N]'} ").strip().lower()
    except EOFError:
        return default
    return default if not a else a.startswith("y")


# ---------------------------------------------------------------- commands

def cmd_status(_a) -> int:
    from .core import system
    i = system.identity()
    s = system.Sampler()
    time.sleep(0.4)
    snap = s.sample()
    print(f"{B}{i['host']}{R}  {DIM}{i['os']} · kernel {i['kernel']} · up {duration(system.uptime_seconds())}{R}")
    print(f"  CPU   {cbar(snap.cpu)} {snap.cpu:4.0f}%" + (f"   {system.cpu_temp():.0f}°C" if system.cpu_temp() else ""))
    print(f"  RAM   {cbar(snap.mem_pct, 24, 80, 92)} {snap.mem_pct:4.0f}%   {human(snap.mem_used)} / {human(snap.mem_total)}")
    for m in system.mounts()[:4]:
        print(f"  {m.mountpoint[:5]:<5} {cbar(m.pct, 24, 80, 90)} {m.pct:4.0f}%   {human(m.free)} free")
    b = system.battery()
    if b:
        print(f"  Batt  {cbar(b['percent'], 24, 101, 101)} {b['percent']:4.0f}%   {'charging' if b.get('plugged') else 'on battery'}"
              + (f", health {b['health']:.0f}%" if b.get("health") else ""))
    procs = system.ProcessWatcher()
    procs.list()
    time.sleep(0.5)
    top = sorted(system.app_groups(procs.list()), key=lambda g: -g["cpu"])[:5]
    print(f"  {DIM}busiest: " + ", ".join(f"{g['name']} {g['cpu']:.0f}%" for g in top) + R)
    print(f"{DIM}Run `pc` for the full control center, `pc doctor` for a health check.{R}")
    return 0


def cmd_doctor(_a) -> int:
    from .core import health
    print(f"{DIM}Checking your PC…{R}")
    checks = health.run_all()
    score = health.score(checks)
    col = rgb("green") if score >= 85 else rgb("peach") if score >= 60 else rgb("red")
    print(f"\n{B}Health score: {col}{score}/100{R}\n")
    for c in checks:
        color, sym = LV[c.level]
        print(f"  {color}{sym}{R} {B}{c.title}{R}  {DIM}{c.detail}{R}")
        if c.level in ("bad", "warn") and (c.steps or c.goto):
            hint = f"pc → {c.goto}" if c.goto else f"fix: {c.fix_label} (in pc)"
            print(f"      {rgb('overlay1')}{hint}{R}")
    fixable = [c for c in checks if c.level in ("bad", "warn") and c.steps]
    if fixable and sys.stdin.isatty():
        print()
        for c in fixable:
            if confirm(f"{c.fix_label or 'Fix'}: {c.title}?", default=False):
                from .core.run import needs_root, run_steps_blocking
                if needs_root(c.steps) and not prime_sudo():
                    continue
                run_steps_blocking(c.steps)
    return 0


def cmd_clean(a) -> int:
    from .core import junk
    from .core.run import needs_root, run_steps_blocking
    print(f"{DIM}Looking for junk{' (deep scan)' if a.deep else ''}…{R}")
    found = junk.scan(deep=a.deep)
    if not found:
        print("Nothing to clean ✓")
        return 0
    total = 0
    chosen = []
    for j in found:
        size = "?" if j.size is None else human(j.size)
        default = j.default and not j.pick
        mark = f"{rgb('green')}✓{R}" if default else f"{DIM}-{R}"
        print(f"  {mark} {j.title:<46} {size:>10}  {DIM}{j.desc[:70]}{R}")
        if a.all and not j.pick or default:
            chosen.append(j)
            total += j.size or 0
    if a.dry_run:
        print(f"\nWould free about {human(total)} (✓ items). Nothing was changed.")
        return 0
    if not a.yes:
        print(f"\n{DIM}Items marked - (browser caches, Trash, old projects…) are only cleaned from the pc app, where you pick them.{R}")
        if not confirm(f"Clean the ✓ items (about {human(total)})?"):
            return 0
    steps = [s for j in chosen for s in j.steps_for()]
    if needs_root(steps) and not prime_sudo():
        steps = [s for s in steps if not s.root]
        print(f"{rgb('peach')}Skipping steps that need admin rights.{R}")
    import shutil
    before = shutil.disk_usage(os.path.expanduser("~")).free
    ok = run_steps_blocking(steps)
    freed = max(shutil.disk_usage(os.path.expanduser("~")).free - before, 0)
    print(f"\n{rgb('green') if ok else rgb('peach')}{'Done' if ok else 'Finished with some problems'} - freed {human(freed)}.{R}")
    return 0 if ok else 1


def cmd_update(a) -> int:
    from .core import packages
    from .core.run import run_steps_blocking
    if not prime_sudo():
        return 1
    ok = run_steps_blocking(packages.update_all_steps(include_firmware=a.firmware))
    from .core import system
    if system.reboot_required() is not None:
        print(f"{rgb('peach')}Restart when convenient to finish the updates.{R}")
    return 0 if ok else 1


def cmd_ports(a) -> int:
    from .core import network
    items = network.ports()
    print(f"{B}{'PORT':>6}  {'TYPE':<4} {'APP':<18} {'REACHABLE FROM':<15} {'PID':>7}  COMMAND{R}")
    for p in items:
        if a.all is False and p.proto == "udp":
            continue
        reach = f"{rgb('peach')}your network{R}   " if p.exposed else f"{DIM}this PC only{R}   "
        print(f"{p.port:>6}  {p.proto:<4} {(p.process or '?')[:18]:<18} {reach} {str(p.pid or ''):>7}  {DIM}{p.cmd[:60]}{R}")
    return 0


def cmd_kill_port(a) -> int:
    from .core import network
    from .core.run import needs_root, run_steps_blocking
    steps = network.kill_port_steps(a.port)
    if not steps:
        print(f"Nothing is using port {a.port}.")
        return 1
    who = {p.process for p in network.ports() if p.port == a.port}
    if not a.yes and not confirm(f"Stop {', '.join(who) or 'process'} on port {a.port}?"):
        return 0
    if needs_root(steps) and not prime_sudo():
        return 1
    return 0 if run_steps_blocking(steps) else 1


def cmd_big(a) -> int:
    from .core import storage
    path = os.path.abspath(os.path.expanduser(a.path))
    print(f"{DIM}Measuring {path}…{R}")
    total, items = storage.children(path)
    print(f"{B}{human(total)}{R} in {path}")
    for e in items[: a.n]:
        pct = e.size / total * 100 if total else 0
        hint = storage.hint_for(e.path)
        print(f"  {human(e.size):>10}  {cbar(pct, 16, 101, 101)} {pct:4.1f}%  {rgb('blue') if e.is_dir else ''}{e.name}{'/' if e.is_dir else ''}{R}  {DIM}{hint}{R}")
    return 0


def cmd_repos(_a) -> int:
    from .core import dev, maint
    from .core.fmt import ago
    repos = dev.repos(maint.project_roots())
    if not repos:
        print("No git projects found. Set folders in ~/.config/pc/config.json (\"projects\").")
        return 0
    for r in repos:
        changes = r["changed"] + r["untracked"]
        state = f"{rgb('peach')}{changes} changed{R}" if changes else f"{rgb('green')}clean{R}"
        sync = " ".join(x for x in (f"↑{r['ahead']}" if r["ahead"] else "", f"↓{r['behind']}" if r["behind"] else "") if x)
        print(f"  {B}{r['name']:<24}{R} {rgb('mauve')}{r['branch'][:18]:<18}{R} {state:<22} {rgb('peach')}{sync:<8}{R} {DIM}{ago(r['last_commit']) if r['last_commit'] else '-':<12} {r['path'].replace(os.path.expanduser('~'), '~')}{R}")
    return 0


def cmd_info(_a) -> int:
    from .core import system
    hw, i = system.hardware(), system.identity()
    rows = [("Computer", i["model"]), ("System", i["os"]), ("Kernel", i["kernel"])]
    if i["desktop"]:
        rows.append(("Desktop", f"{i['desktop']} ({i['session']})" if i["session"] else i["desktop"]))
    rows += [
            ("CPU", f"{hw['cpu']} · {hw['cores']}c/{hw['threads']}t"), ("Memory", human(hw["ram"]))]
    rows += [("GPU", g) for g in hw["gpus"]]
    rows += [("Disk", f"{d['name']} {d['model']} {human(d['size'])} {d['kind']}") for d in hw["disks"]]
    if hw["bios"]:
        rows.append(("BIOS", hw["bios"]))
    b = system.battery()
    if b and b.get("health"):
        rows.append(("Battery", f"health {b['health']:.0f}%" + (f", {b['cycles']} cycles" if b.get('cycles') else "")))
    for k, v in rows:
        print(f"  {rgb('overlay1')}{k:<10}{R} {v}")
    return 0


def cmd_logs(a) -> int:
    from .core import logs
    groups = logs.grouped(logs.entries(since=a.since, max_priority=3))
    if not groups:
        print("No errors ✓")
    for g in groups[:25]:
        print(f"  {rgb('red') if g['worst'] <= 2 else rgb('peach')}{g['count']:>4}×{R} {B}{g['source'][:22]:<22}{R} {DIM}{logs.fmt_time(g['last']):>12}{R}  {g['message'][:90]}")
    return 0


def cmd_services(a) -> int:
    from .core import services
    items = services.failed() if a.failed else [s for s in services.services() if s.active in ("active", "failed")]
    for s in items:
        col = rgb("red") if s.active == "failed" else rgb("green")
        print(f"  {col}●{R} {s.name:<40} {DIM}{services.explain(s.unit) or s.description}{R}")
    if a.failed and not items:
        print("No failing services ✓")
    return 0


def cmd_maintain(a) -> int:
    from .core import maint
    if a.auto:
        print(maint.maintain_auto())
        return 0
    from .core.run import run_steps_blocking
    if a.on:
        return 0 if run_steps_blocking(maint.enable_timer_steps()) else 1
    if a.off:
        return 0 if run_steps_blocking(maint.disable_timer_steps()) else 1
    st = maint.timer_status()
    print(f"Weekly checkup: {'on' if st['enabled'] else 'off'}" + (f" · next {st['next']}" if st["next"] else "") + (f" · last {st['last']}" if st["last"] else ""))
    print(f"{DIM}pc maintain --on | --off | --auto (run now){R}")
    return 0


def cmd_backup(_a) -> int:
    from .core import maint
    from .core.run import run_steps_blocking
    return 0 if run_steps_blocking(maint.backup_settings_steps()) else 1


def _print_checks(checks, fix: bool = True) -> None:
    """Shared by doctor / slow / fix: coloured list, then offer each fix (interactive terminals only)."""
    for c in checks:
        color, sym = LV[c.level]
        print(f"  {color}{sym}{R} {B}{c.title}{R}  {DIM}{c.detail}{R}")
        if c.level in ("bad", "warn") and c.goto and not c.steps:
            where = c.goto.split(":", 1)[1] + " settings" if c.goto.startswith("settings:") else f"pc gui {c.goto}"
            print(f"      {rgb('overlay1')}→ {where}{R}")
    fixable = [c for c in checks if c.level in ("bad", "warn") and c.steps]
    if fix and fixable and sys.stdin.isatty():
        print()
        from .core.run import needs_root, run_steps_blocking
        for c in fixable:
            print(f"{DIM}" + "\n".join(f"  $ {s.display()}" for s in c.steps) + R)
            if confirm(f"{c.fix_label or 'Fix'}: {c.title}?", default=False):
                if needs_root(c.steps) and not prime_sudo():
                    continue
                run_steps_blocking(c.steps)


def cmd_optimize(_a) -> int:
    from .core import advisor
    items = advisor.recommendations()
    print(f"{B}Optimization advisor{R}\n")
    for a in items:
        risk = a.risk.upper()
        print(f"  {B}{a.title}{R}  {DIM}[{risk} risk]{R}\n    {a.detail}\n    {DIM}Benefit: {a.benefit}{R}")
        if a.goto:
            print(f"    {rgb('overlay1')}→ pc gui {a.goto}{R}")
    return 0


def cmd_network_check(_a) -> int:
    from .core import network
    bad = False
    for title_, ok, detail in network.diagnose_connectivity():
        bad |= not ok
        color = rgb("green") if ok else rgb("red")
        print(f"  {color}{'✓' if ok else '✗'}{R} {B}{title_}{R}  {DIM}{detail}{R}")
    return 1 if bad else 0


def cmd_slow(_a) -> int:
    from .core import diagnose
    print(f"{DIM}Measuring for a couple of seconds…{R}\n")
    _print_checks(diagnose.run())
    return 0


def cmd_fix(a) -> int:
    from .core import troubleshoot
    if not a.what or a.what not in troubleshoot.BY_ID:
        print("What needs fixing?\n")
        for t in troubleshoot.TROUBLESHOOTERS:
            print(f"  {B}pc fix {t.id:<10}{R} {t.title} {DIM}- {t.description}{R}")
        return 0 if not a.what else 2
    t = troubleshoot.BY_ID[a.what]
    title(t.title)
    print(f"{DIM}Checking…{R}")
    _print_checks(t.checks(), fix=not a.no_fix)
    return 0


def cmd_secrets(a) -> int:
    from .core import secrets
    return secrets.main(["--json"] if a.json else [])


def cmd_report(a) -> int:
    from .core import report
    if a.text:
        print(report.text(redacted=not a.full, quick=a.quick))
        return 0
    print(f"{DIM}Collecting{' (quick)' if a.quick else ' (updates and the last day of errors take ~20 s)'}…{R}")
    data = report.collect(quick=a.quick)
    path = report.save(a.output, redacted=a.share, data=data)
    print(f"{rgb('green')}✓{R} {report.summary_line(data)}\n  {B}{path}{R}" + (f"\n  {DIM}names and addresses are hidden in this copy{R}" if a.share else ""))
    if a.open:
        subprocess.Popen(report.open_cmd(path), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return 0


def cmd_watch(a) -> int:
    """What the background-alerts timer runs every 30 minutes."""
    from .core import watch
    if a.on or a.off:
        from .core.run import run_steps_blocking
        return 0 if run_steps_blocking(watch.enable_steps() if a.on else watch.disable_steps()) else 1
    if a.list:
        found = watch.checks()
        for f in found:
            print(f"  {rgb('peach')}▲{R} {B}{f['title']}{R}  {DIM}{f['body']}{R}")
        if not found:
            print("Nothing needs attention ✓")
        return 0
    sent = watch.run(force=a.force)
    if sys.stdout.isatty():
        print(f"{len(sent)} alert(s) sent" if sent else "Nothing new to tell you ✓")
    return 0


def _parse_duration(text: str) -> int | None:
    """'90m', '2h', '1h30m', '45' (minutes) -> seconds; 'forever'/'on' -> None (until stopped)."""
    import re
    t = text.strip().lower()
    if t in ("forever", "on", "always", "until"):
        return None
    if t.isdigit():
        return int(t) * 60
    # Do not silently accept a valid-looking fragment embedded in garbage
    # (for example ``abc2hxyz`` or ``2hours``).
    if not re.fullmatch(r"(?:\d+\s*[hms]\s*)+", t):
        raise ValueError(text)
    total = 0
    for n, unit in re.findall(r"(\d+)\s*([hms])", t):
        total += int(n) * {"h": 3600, "m": 60, "s": 1}[unit]
    if not total:
        raise ValueError(text)
    return total


def cmd_awake(a) -> int:
    from .core import power
    arg = (a.duration or "").lower()
    if arg in ("off", "stop"):
        print("Keep awake stopped." if power.stop_keep_awake() else "Keep awake wasn't on.")
        return 0
    if not arg or arg == "status":
        st = power.keep_awake_status()
        if not st:
            print(f"Keep awake is off. {DIM}pc awake 2h | 90m | forever | off{R}")
        else:
            print("Keeping the PC awake " + (f"for another {duration(st['left'])}" if st.get("left") else "until you run: pc awake off"))
        return 0
    try:
        secs = _parse_duration(arg)
    except ValueError:
        print("Say how long, e.g. pc awake 2h, pc awake 45m, pc awake forever, or pc awake off")
        return 2
    try:
        power.start_keep_awake(secs)
    except Exception as e:  # noqa: BLE001
        print(f"Couldn't keep the PC awake: {e}")
        return 1
    print(f"{rgb('green')}✓{R} The PC won't sleep or blank the screen " + (f"for {duration(secs)}" if secs else "until you run: pc awake off"))
    return 0


def cmd_telemetry(a) -> int:
    from .core import devtelemetry
    from .core.run import run_steps_blocking
    if a.state == "off":
        return 0 if run_steps_blocking(devtelemetry.off_steps()) else 1
    if a.state == "on":
        return 0 if run_steps_blocking(devtelemetry.on_steps()) else 1
    st = devtelemetry.status()
    print(f"Developer tool telemetry: {st['off_count']} of {st['total']} switched off")
    for r in st["vars"]:
        if r["installed"] or r["off"]:
            mark = f"{rgb('green')}off{R}" if r["off"] else f"{rgb('peach')}on {R}"
            print(f"  {mark}  {r['tools']}  {DIM}{r['var']}={r['value']}{R}")
    print(f"{DIM}pc telemetry off | on{R}")
    return 0


PAGES = ["dashboard", "cleanup", "updates", "apps", "startup", "processes", "storage", "network", "power", "logs", "services", "security",
         "privacy", "tweaks", "dev", "maintenance"]


def _parser_tree(p: argparse.ArgumentParser) -> dict[str, list[str]]:
    """{subcommand: [options…]} straight from argparse, so completions never go stale."""
    tree: dict[str, list[str]] = {}
    for action in p._actions:  # noqa: SLF001 - argparse has no public API for this
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            for name, sp in action.choices.items():
                opts = [o for a in sp._actions for o in a.option_strings if o.startswith("--")]  # noqa: SLF001
                tree[name] = opts
    return tree


def completion_script(shell: str, p: argparse.ArgumentParser) -> str:
    from .core import troubleshoot
    tree = _parser_tree(p)
    cmds = " ".join(sorted(tree))
    values = {"gui": " ".join(PAGES), "fix": " ".join(t.id for t in troubleshoot.TROUBLESHOOTERS), "awake": "30m 1h 2h 4h forever off status",
              "telemetry": "off on", "completions": "bash zsh", "logs": ""}
    if shell == "bash":
        cases = "\n".join(f'        {c}) opts="{" ".join(o)} {values.get(c, "")}";;' for c, o in sorted(tree.items()))
        return f"""# bash completion for pc (generated by `pc completions bash`)
_pc() {{
    local cur cmd opts
    cur="${{COMP_WORDS[COMP_CWORD]}}"
    if [ "$COMP_CWORD" -eq 1 ]; then
        COMPREPLY=( $(compgen -W "{cmds} --help --version" -- "$cur") )
        return
    fi
    cmd="${{COMP_WORDS[1]}}"
    case "$cmd" in
{cases}
        *) opts="";;
    esac
    case "$cmd" in
        big) COMPREPLY=( $(compgen -d -- "$cur") $(compgen -W "$opts" -- "$cur") ); return;;
        report) if [ "${{COMP_WORDS[COMP_CWORD-1]}}" = "-o" ] || [ "${{COMP_WORDS[COMP_CWORD-1]}}" = "--output" ]; then
                    COMPREPLY=( $(compgen -f -- "$cur") ); return; fi;;
    esac
    COMPREPLY=( $(compgen -W "$opts" -- "$cur") )
}}
complete -F _pc pc
"""
    if shell == "zsh":
        helps = {}
        for action in p._actions:  # noqa: SLF001
            if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
                for ca in action._choices_actions:  # noqa: SLF001
                    helps[ca.dest] = (ca.help or "").replace("'", "").replace(":", " -")
        described = "\n".join(f"        '{c}:{helps.get(c, '')}'" for c in sorted(tree))
        cases = "\n".join(f"        {c}) _values '{c}' {' '.join(repr(x) for x in (values.get(c, '').split() + o)) or repr('')} ;;"
                          for c, o in sorted(tree.items()) if o or values.get(c))
        return f"""#compdef pc
# zsh completion for pc (generated by `pc completions zsh`)
_pc() {{
    local -a cmds
    cmds=(
{described}
    )
    if (( CURRENT == 2 )); then
        _describe 'command' cmds
        return
    fi
    case "$words[2]" in
        big) _files -/ ;;
{cases}
    esac
}}
if [[ $zsh_eval_context[-1] == loadautofunc ]]; then _pc "$@"; else compdef _pc pc; fi
"""
    raise SystemExit("pc completions bash | zsh")


def cmd_completions(a) -> int:
    print(completion_script(a.shell, a._parser))
    return 0



def cmd_support(_a) -> int:
    """Create the same redacted troubleshooting bundle offered by the GUI."""
    from .core import debug
    try:
        path = debug.export_bundle()
    except Exception as exc:  # noqa: BLE001
        print(f"Could not create support bundle: {exc}", file=sys.stderr)
        return 1
    print(path)
    return 0

def cmd_gui(a) -> int:
    """Open the desktop app. It runs on Ubuntu's own Python (for GTK), so hand over to the pc-gui launcher."""
    import os
    import shutil
    exe = shutil.which("pc-gui") or os.path.expanduser("~/.local/bin/pc-gui")
    if not os.path.exists(exe):
        print("The desktop app isn't installed yet. Run: bash setup.sh app   (in your ubuntu-setup folder)")
        return 1
    args = [exe] + (["--page", a.page] if a.page else [])
    os.execv(exe, args)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pc", description="Your computer's control center. Run without arguments for the full-screen app.")
    p.add_argument("--version", action="version", version=f"pc {__version__}")
    p.add_argument("--debug", action="store_true", help="record detailed redacted troubleshooting logs for this run")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("status", help="one-screen summary").set_defaults(fn=cmd_status)
    sub.add_parser("support", help="create a redacted troubleshooting ZIP in Downloads").set_defaults(fn=cmd_support)
    sub.add_parser("doctor", help="health check with fixes").set_defaults(fn=cmd_doctor)
    c = sub.add_parser("clean", help="remove junk safely")
    c.add_argument("--dry-run", action="store_true", help="only show what would be cleaned")
    c.add_argument("-y", "--yes", action="store_true", help="don't ask")
    c.add_argument("--deep", action="store_true", help="also look for old node_modules, language versions, old downloads")
    c.add_argument("--all", action="store_true", help="include optional items like browser caches and Trash")
    c.set_defaults(fn=cmd_clean)
    u = sub.add_parser("update", help="update apt, snap and flatpak")
    u.add_argument("--firmware", action="store_true", help="also install firmware updates")
    u.set_defaults(fn=cmd_update)
    po = sub.add_parser("ports", help="what's listening on which port")
    po.add_argument("--all", action="store_true", help="include UDP")
    po.set_defaults(fn=cmd_ports)
    k = sub.add_parser("kill-port", help="stop whatever is using a port")
    k.add_argument("port", type=int)
    k.add_argument("-y", "--yes", action="store_true")
    k.set_defaults(fn=cmd_kill_port)
    b = sub.add_parser("big", help="biggest things in a folder")
    b.add_argument("path", nargs="?", default="~")
    b.add_argument("-n", type=int, default=20)
    b.set_defaults(fn=cmd_big)
    sub.add_parser("repos", help="status of all your git projects").set_defaults(fn=cmd_repos)
    sub.add_parser("info", help="hardware and system details").set_defaults(fn=cmd_info)
    lg = sub.add_parser("logs", help="recent errors, grouped")
    lg.add_argument("--since", default="boot", help="boot, previous, -1h, today…")
    lg.set_defaults(fn=cmd_logs)
    sv = sub.add_parser("services", help="running services")
    sv.add_argument("--failed", action="store_true")
    sv.set_defaults(fn=cmd_services)
    m = sub.add_parser("maintain", help="weekly automatic checkup")
    m.add_argument("--auto", action="store_true", help="run the checkup now (what the schedule runs)")
    m.add_argument("--on", action="store_true")
    m.add_argument("--off", action="store_true")
    m.set_defaults(fn=cmd_maintain)
    sub.add_parser("backup", help="back up your settings to ~/Backups").set_defaults(fn=cmd_backup)
    sub.add_parser("slow", help="why is my PC slow right now? (with fixes)").set_defaults(fn=cmd_slow)
    sub.add_parser("optimize", help="evidence-based optimization recommendations").set_defaults(fn=cmd_optimize)
    sub.add_parser("network-check", help="layered router, internet, DNS and HTTPS diagnosis").set_defaults(fn=cmd_network_check)
    fx = sub.add_parser("fix", help="troubleshooters: internet, sound, bluetooth, apt, desktop, clock, printer…")
    fx.add_argument("what", nargs="?", default="", help="which one (leave empty to list them)")
    fx.add_argument("--no-fix", action="store_true", help="only report, don't offer fixes")
    fx.set_defaults(fn=cmd_fix)
    se = sub.add_parser("secrets", help="find leaked API keys, tokens and passwords")
    se.add_argument("--json", action="store_true", help="machine-readable output (secrets stay masked)")
    se.set_defaults(fn=cmd_secrets)
    rp = sub.add_parser("report", help="save a system report (HTML) to keep or share")
    rp.add_argument("--share", action="store_true", help="hide names, IP and MAC addresses")
    rp.add_argument("--quick", action="store_true", help="skip the update check and error log")
    rp.add_argument("--text", action="store_true", help="print plain text instead (names hidden unless --full)")
    rp.add_argument("--full", action="store_true", help="with --text: don't hide names")
    rp.add_argument("-o", "--output", default=None, help="where to save (default ~/Documents/PC-report-….html)")
    rp.add_argument("--open", action="store_true", help="open it in the browser afterwards")
    rp.set_defaults(fn=cmd_report)
    w = sub.add_parser("watch", help="check once and send desktop alerts (what the background timer runs)")
    w.add_argument("--force", action="store_true", help="run even if alerts are turned off")
    w.add_argument("--list", action="store_true", help="just print what needs attention")
    w.add_argument("--on", action="store_true", help="turn background alerts on (every 30 minutes)")
    w.add_argument("--off", action="store_true", help="turn background alerts off")
    w.set_defaults(fn=cmd_watch)
    aw = sub.add_parser("awake", help="keep the PC awake: pc awake 2h | forever | off")
    aw.add_argument("duration", nargs="?", default="", help="2h, 90m, forever, off or status")
    aw.set_defaults(fn=cmd_awake)
    te = sub.add_parser("telemetry", help="developer tool telemetry: pc telemetry off | on")
    te.add_argument("state", nargs="?", choices=["off", "on", "status"], default="status")
    te.set_defaults(fn=cmd_telemetry)
    co = sub.add_parser("completions", help="print tab-completion script: pc completions bash | zsh")
    co.add_argument("shell", choices=["bash", "zsh"])
    co.set_defaults(fn=cmd_completions, _parser=p)
    g = sub.add_parser("gui", help="open the desktop app (PC Command Center)")
    g.add_argument("page", nargs="?", default="", help="page to open, e.g. cleanup")
    g.set_defaults(fn=cmd_gui)
    for name in ("processes", "storage", "cleanup", "updates", "apps", "startup", "network", "dev", "power", "security"):
        sub.add_parser(name, help=f"open pc on the {name} section").set_defaults(fn=None, start=name)
    a = p.parse_args(argv)
    if a.debug:
        from .core import debug
        debug.configure(True)
        debug.event("cli.start", argv=" ".join(argv or sys.argv[1:]))
    if not a.cmd or getattr(a, "fn", None) is None:
        from .ui.app import run
        run(getattr(a, "start", "overview"))
        return 0
    try:
        return a.fn(a)
    except KeyboardInterrupt:
        print()
        return 130
    except Exception as exc:  # noqa: BLE001 - last resort: explain, log and offer a report instead of a bare traceback
        import traceback
        traceback.print_exc()
        offer_bug_report(exc, f"pc {a.cmd}")
        return 1


def offer_bug_report(exc: BaseException, where: str) -> None:
    """After a crash: save it to the error log and print a pre-filled GitHub issue link."""
    try:
        from .core import bugreport
        from .core.state import append_private
        import time
        rep = bugreport.from_exception(exc, where)
        append_private(bugreport.ERRORS_LOG, time.strftime("== %Y-%m-%d %H:%M:%S ==\n") + rep.error + "\n")
        print(f"\n{rgb('red')}pc hit an unexpected error.{R} It was saved to ~/.local/state/pc/gui-errors.log.\n"
              f"Report it on GitHub (opens a pre-filled issue; names, paths and addresses are removed):\n  {rep.url()}",
              file=sys.stderr)
    except Exception:  # noqa: BLE001 - never crash while reporting a crash
        pass


if __name__ == "__main__":
    sys.exit(main())

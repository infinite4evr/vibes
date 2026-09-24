"""Cleanup engine: ~40 kinds of junk, grouped, each with sizes, the exact commands, and per-item choice.

Every category returns a Junk. Items can be ticked individually in the app; `steps_for(keys)` builds the commands
for just the chosen items. Nothing here deletes anything by itself - it only describes what could be removed.
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import storage
from .run import HOME, Step, has, out, py_step, read, sh, which

STATE = HOME / ".local/state/pc"

GROUPS = ["System", "Developer", "Apps & browsers", "Your files", "Privacy"]


@dataclass
class Item:
    key: str
    label: str
    size: int = 0
    note: str = ""
    default: bool = True


@dataclass
class Junk:
    id: str
    title: str
    desc: str
    size: int | None = 0
    steps: list[Step] = field(default_factory=list)
    default: bool = True
    root: bool = False
    items: list[Item] = field(default_factory=list)
    make_steps: Callable[[list[str]], list[Step]] | None = None
    pick: bool = False          # user should choose items (nothing pre-ticked unless item.default)
    group: str = "System"
    warn: str = ""              # shown before cleaning, e.g. "close your browsers first"
    deep: bool = False          # only found by the deep scan

    def steps_for(self, chosen: list[str] | None = None) -> list[Step]:
        if self.make_steps is not None:
            keys = chosen if chosen is not None else [i.key for i in self.items if i.default or not self.pick]
            return self.make_steps(keys) if keys else []
        return self.steps

    def size_for(self, chosen: list[str] | None) -> int:
        if chosen is None or not self.items:
            return self.size or 0
        keys = set(chosen)
        return sum(i.size for i in self.items if i.key in keys)


# ---------------------------------------------------------------- helpers

def size_of(*paths: str | Path) -> int:
    existing = [str(p) for p in paths if os.path.lexists(p)]
    if not existing:
        return 0
    r = sh(["du", "-scB1", *existing], timeout=180)
    if not r.out.strip() and os.geteuid() != 0:
        r = sh(["du", "-scB1", *existing], timeout=180, root=True)
    last = r.out.strip().splitlines()[-1:] if r.out else []
    try:
        return int(last[0].split("\t")[0]) if last else 0
    except ValueError:
        return 0


SAFE_ROOTS = (str(HOME) + "/", "/tmp/", "/var/tmp/")


def _rm_paths(paths: list[str]) -> Callable[[], str]:
    """Delete files/folders - only ever inside your home folder or temp folders."""
    def run() -> str:
        done, skipped = [], []
        for p in paths:
            ap = os.path.abspath(p)
            if not ap.startswith(SAFE_ROOTS) or ap.rstrip("/") in (str(HOME), "/tmp", "/var/tmp"):
                skipped.append(p)
                continue
            try:
                if os.path.islink(ap) or os.path.isfile(ap):
                    os.unlink(ap)
                elif os.path.isdir(ap):
                    shutil.rmtree(ap, ignore_errors=True)
                else:
                    continue
                done.append(p)
            except OSError as e:
                skipped.append(f"{p} ({e.strerror})")
        msg = "\n".join(f"removed {_short(d)}" for d in done[:200])
        if len(done) > 200:
            msg += f"\n… and {len(done) - 200} more"
        if skipped:
            msg += "\nskipped: " + ", ".join(_short(s) for s in skipped[:20])
        return msg or "nothing to remove"
    return run


def _empty_dirs(paths: list[str]) -> Callable[[], str]:
    """Empty folders but keep the folders themselves (apps sometimes expect them)."""
    def run() -> str:
        n = 0
        for p in paths:
            if not os.path.abspath(p).startswith(str(HOME) + "/") or not os.path.isdir(p):
                continue
            for child in os.listdir(p):
                c = os.path.join(p, child)
                try:
                    if os.path.isdir(c) and not os.path.islink(c):
                        shutil.rmtree(c, ignore_errors=True)
                    else:
                        os.unlink(c)
                    n += 1
                except OSError:
                    pass
        return f"emptied {len(paths)} folders ({n} entries)"
    return run


def _short(p: str) -> str:
    return str(p).replace(str(HOME), "~", 1)


def _rm_step(title: str, keys: list[str]) -> Step:
    shown = "rm -rf " + " ".join(_short(k) for k in keys[:6]) + (f" … (+{len(keys) - 6} more)" if len(keys) > 6 else "")
    return py_step(title, _rm_paths(keys), shown)


def _trash_step(title: str, keys: list[str]) -> Step:
    return Step(title, ["gio", "trash", *keys])


def _path_items(rels: list[str], base: Path = HOME, note: str = "") -> list[Item]:
    items = []
    for rel in rels:
        p = base / rel
        if p.exists():
            s = size_of(p)
            if s > 0:
                items.append(Item(str(p), _short(str(p)), s, note))
    return items


def _paths_junk(id_: str, title: str, desc: str, rels: list[str], group: str, default: bool = True, warn: str = "",
                item_default: bool = True) -> Junk:
    items = _path_items(rels)
    for i in items:
        i.default = item_default
    return Junk(id_, title, desc, sum(i.size for i in items), items=items, group=group, default=default, warn=warn,
                make_steps=lambda keys: [_rm_step(f"Delete {title.lower()}", keys)])


# ================================================================ SYSTEM (needs your password)

def apt_cache() -> Junk:
    debs = glob.glob("/var/cache/apt/archives/*.deb") + glob.glob("/var/cache/apt/archives/partial/*")
    size = sum(os.path.getsize(p) for p in debs if os.path.isfile(p))
    return Junk("apt-cache", "Downloaded package files", "Installer files apt keeps after installing updates.",
                size, [Step("Delete downloaded .deb files", ["apt-get", "clean"], root=True)], root=True,
                items=[Item(d, os.path.basename(d), os.path.getsize(d)) for d in debs if os.path.isfile(d)][:200])


def parse_autoremove(text: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r"^Remv (\S+)", text, re.M)]


def pkg_sizes(pkgs: list[str]) -> dict[str, int]:
    if not pkgs:
        return {}
    r = sh(["dpkg-query", "-W", "-f=${Package}\t${Installed-Size}\n", *pkgs])
    sizes = {}
    for line in r.out.splitlines():
        name, _, kb = line.partition("\t")
        if kb.strip().isdigit():
            sizes[name.split(":")[0]] = int(kb) * 1024
    return sizes


def apt_autoremove() -> Junk:
    pkgs = parse_autoremove(out(["apt-get", "-s", "autoremove", "--purge"], timeout=60))
    sizes = pkg_sizes(pkgs)
    kernels = [p for p in pkgs if p.startswith("linux-")]
    desc = "Packages that were pulled in by something you removed, and nothing needs now."
    if kernels:
        desc += f" Includes {len(kernels)} old kernel package(s) - your current kernel is always kept."
    return Junk("apt-autoremove", "Unused packages + old kernels", desc, sum(sizes.values()),
                [Step("Remove unused packages", ["apt-get", "autoremove", "--purge", "-y"], root=True, env={"DEBIAN_FRONTEND": "noninteractive"})],
                root=True, items=[Item(p, p, sizes.get(p.split(":")[0], 0), "old kernel" if p.startswith("linux-") else "") for p in pkgs])


def dpkg_residual() -> Junk:
    pkgs = [ln.split()[1] for ln in out(["dpkg", "-l"]).splitlines() if ln.startswith("rc ")]
    return Junk("dpkg-rc", "Leftover settings of removed apps", "System-wide config files left behind by apps you uninstalled.",
                None if pkgs else 0, root=True, items=[Item(p, p) for p in pkgs],
                make_steps=lambda keys: [Step("Purge leftover configs", ["dpkg", "--purge", *keys], root=True)])


def parse_snap_disabled(text: str) -> list[tuple[str, str]]:
    res = []
    for line in text.splitlines()[1:]:
        cols = line.split()
        if len(cols) >= 6 and "disabled" in cols[-1]:
            res.append((cols[0], cols[2]))
    return res


def snap_old() -> Junk:
    if not has("snap"):
        return Junk("snap-old", "Old snap versions", "", 0)
    olds = parse_snap_disabled(out(["snap", "list", "--all"]))
    items = []
    for name, rev in olds:
        f = f"/var/lib/snapd/snaps/{name}_{rev}.snap"
        items.append(Item(f"{name}:{rev}", f"{name} (revision {rev})", os.path.getsize(f) if os.path.exists(f) else 0))

    def make(keys: list[str]) -> list[Step]:
        steps = [Step(f"Remove old {k.split(':')[0]} r{k.split(':')[1]}", ["snap", "remove", k.split(":")[0], f"--revision={k.split(':')[1]}"], root=True)
                 for k in keys]
        if steps:
            steps.append(Step("Keep only 2 versions from now on", ["snap", "set", "system", "refresh.retain=2"], root=True, optional=True))
        return steps
    return Junk("snap-old", "Old snap versions", "Snap keeps previous copies of every app after it updates.",
                sum(i.size for i in items), root=True, items=items, make_steps=make)


def snap_cache() -> Junk:
    if not os.path.isdir("/var/lib/snapd/cache"):
        return Junk("snap-cache", "Snap download cache", "", 0)
    r = sh(["find", "/var/lib/snapd/cache", "-type", "f", "-links", "1", "-printf", "%s\n"], root=True, timeout=30)
    if not r.ok:
        r = sh(["find", "/var/lib/snapd/cache", "-type", "f", "-links", "1", "-printf", "%s\n"], timeout=30)
    size = sum(int(x) for x in r.out.split() if x.isdigit())
    return Junk("snap-cache", "Snap download cache", "Copies of snap downloads that no installed snap uses anymore.", size,
                [Step("Delete unused snap downloads", ["find", "/var/lib/snapd/cache", "-type", "f", "-links", "1", "-delete"], root=True)], root=True)


def flatpak_unused() -> Junk:
    if not has("flatpak"):
        return Junk("flatpak-unused", "Unused Flatpak runtimes", "", 0)
    return Junk("flatpak-unused", "Unused Flatpak runtimes", "Shared libraries left over after Flatpak apps were removed. The size shows up after cleaning.",
                None, [Step("Remove unused runtimes (yours)", ["flatpak", "uninstall", "--unused", "-y", "--noninteractive", "--user"], optional=True),
                       Step("Remove unused runtimes (system)", ["flatpak", "uninstall", "--unused", "-y", "--noninteractive", "--system"], root=True, optional=True)])


def parse_journal_usage(text: str) -> int:
    m = re.search(r"take up ([\d.]+)([KMGT]?)", text)
    if not m:
        return 0
    mult = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}[m.group(2)]
    return int(float(m.group(1)) * mult)


def journal() -> Junk:
    r = sh(["journalctl", "--disk-usage"], root=True)
    used = parse_journal_usage(r.out if r.ok else sh(["journalctl", "--disk-usage"]).out)
    keep = 200 * 1024**2
    return Junk("journal", "System logs (journal)", "Linux logs everything; this keeps the newest 200 MB and caps logs at 300 MB from now on.",
                max(used - keep, 0),
                [Step("Shrink logs to 200 MB", ["journalctl", "--vacuum-size=200M"], root=True),
                 Step("Cap logs at 300 MB", ["bash", "-c", "mkdir -p /etc/systemd/journald.conf.d && printf '[Journal]\\nSystemMaxUse=300M\\n' > /etc/systemd/journald.conf.d/99-pc.conf && systemctl restart systemd-journald"], root=True, optional=True)],
                root=True)


ROTATED = r".*\.([0-9]+|gz|xz|bz2|zst|old)$"


def rotated_logs() -> Junk:
    r = sh(["find", "/var/log", "-type", "f", "-regextype", "posix-extended", "-regex", ROTATED, "-printf", "%s\t%p\n"], timeout=30)
    r2 = sh(["find", "/var/log", "-type", "f", "-regextype", "posix-extended", "-regex", ROTATED, "-printf", "%s\t%p\n"], root=True, timeout=30)
    text = r2.out if r2.ok and r2.out else r.out
    files = [(int(s), p) for s, _, p in (ln.partition("\t") for ln in text.splitlines()) if s.isdigit()]
    return Junk("rotated-logs", "Old rotated log files", "Compressed and numbered copies of logs in /var/log (e.g. syslog.2.gz). The current logs are kept.",
                sum(s for s, _ in files),
                [Step("Delete old rotated logs", ["find", "/var/log", "-type", "f", "-regextype", "posix-extended", "-regex", ROTATED, "-delete"], root=True)],
                root=True, items=[Item(p, p, s) for s, p in sorted(files, reverse=True)[:100]])


def crash_reports() -> Junk:
    files = glob.glob("/var/crash/*") + glob.glob("/var/lib/systemd/coredump/*")
    size = 0
    for f in files:
        try:
            size += os.path.getsize(f)
        except OSError:
            pass
    return Junk("crash", "Crash reports and core dumps", "Reports saved when apps crashed. Only useful if you file a bug report.", size,
                [Step("Delete crash reports", ["bash", "-c", "rm -rf /var/crash/* /var/lib/systemd/coredump/*"], root=True)] if files else [],
                root=True, items=[Item(f, os.path.basename(f), os.path.getsize(f) if os.path.exists(f) else 0) for f in files])


def temp_files() -> Junk:
    """Old files in /tmp and /var/tmp (yours: no password; others' need one)."""
    me = os.getuid()
    items: list[Item] = []
    cutoff = time.time() - 7 * 86400
    for base in ("/tmp", "/var/tmp"):
        try:
            entries = list(os.scandir(base))
        except OSError:
            continue
        for e in entries:
            try:
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            if st.st_uid != me or max(st.st_mtime, st.st_atime) > cutoff or e.name.startswith((".X", ".ICE", "systemd-", "snap-private")):
                continue
            size = size_of(e.path) if e.is_dir(follow_symlinks=False) else st.st_size
            items.append(Item(e.path, e.path, size, f"untouched {int((time.time() - st.st_mtime) / 86400)} days"))
    root_old = sh(["find", "/var/tmp", "-mindepth", "1", "-maxdepth", "1", "-mtime", "+30", "-not", "-user", str(me), "-printf", "%s\n"], root=True, timeout=20)
    root_size = sum(int(x) for x in root_old.out.split() if x.isdigit()) if root_old.ok else 0

    def make(keys: list[str]) -> list[Step]:
        steps = [_rm_step("Delete your old temp files", [k for k in keys if k != "__root__"])] if [k for k in keys if k != "__root__"] else []
        if "__root__" in keys:
            steps.append(Step("Delete system temp files older than 30 days", ["find", "/var/tmp", "-mindepth", "1", "-mtime", "+30", "-delete"], root=True, optional=True))
        return steps
    if root_size:
        items.append(Item("__root__", "System files in /var/tmp older than 30 days", root_size, "needs password", default=False))
    return Junk("temp-files", "Old temporary files", "Leftovers in /tmp and /var/tmp that nothing has touched for a week.",
                sum(i.size for i in items), items=items, make_steps=make)


def packagekit_cache() -> Junk:
    d = "/var/cache/PackageKit"
    if not os.path.isdir(d):
        return Junk("packagekit", "App Center download cache", "", 0)
    return Junk("packagekit", "App Center download cache", "Downloads kept by the App Center / GNOME Software updater.", size_of(d),
                [Step("Delete App Center cache", ["bash", "-c", "rm -rf /var/cache/PackageKit/*/*"], root=True)], root=True)


def containers() -> Junk:
    tool = "podman" if has("podman") else ("docker" if has("docker") else None)
    if not tool:
        return Junk("containers", "Container leftovers", "", 0)
    text = out([tool, "system", "df"], timeout=30)
    total = 0
    items = []
    for line in text.splitlines()[1:]:
        m = re.search(r"([\d.]+)\s*([kKMGT]?B)\s*\(\d+%\)\s*$", line)
        if m:
            mult = {"B": 1, "kB": 1000, "KB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4}.get(m.group(2), 1)
            s = int(float(m.group(1)) * mult)
            total += s
            items.append(Item(line.split()[0], line.split()[0] + " (reclaimable)", s))
    return Junk("containers", f"{tool.title()} leftovers", "Stopped containers, unused images and build cache. Running containers and named volumes are kept.",
                total, [Step(f"Prune {tool} (stopped containers, unused images, networks)", [tool, "system", "prune", "-af"]),
                        Step(f"Prune {tool} build cache", [tool, "builder", "prune", "-af"] if tool == "docker" else [tool, "image", "prune", "-f"], optional=True)],
                default=False, group="Developer", items=items)


def waydroid_left() -> Junk:
    paths = [p for p in ("/var/lib/waydroid", str(HOME / ".local/share/waydroid"), str(HOME / ".android")) if os.path.exists(p)]
    if not paths and not has("waydroid"):
        return Junk("waydroid", "Waydroid leftovers", "", 0)
    steps = []
    if has("waydroid"):
        steps.append(Step("Stop Waydroid", ["waydroid", "session", "stop"], optional=True))
        steps.append(Step("Uninstall Waydroid", ["apt-get", "purge", "-y", "waydroid"], root=True, optional=True))
    steps.append(Step("Delete Waydroid data", ["rm", "-rf", "/var/lib/waydroid", "/home/.waydroid", str(HOME / ".local/share/waydroid"), str(HOME / ".android")], root=True))
    return Junk("waydroid", "Waydroid (Android) leftovers", "Android container data and ~/.android.", size_of(*paths), steps, root=True, default=False,
                group="Apps & browsers")


# ================================================================ DEVELOPER

def python_caches() -> Junk:
    rels = [".cache/pip", ".cache/pypoetry/cache", ".cache/pypoetry/artifacts", ".local/pipx/.cache", ".cache/pipx", ".pyenv/cache",
            ".cache/pre-commit", ".cache/pdm", ".cache/hatch", ".cache/virtualenv", ".cache/matplotlib", ".conda/pkgs", "miniconda3/pkgs", "anaconda3/pkgs"]
    j = _paths_junk("py-caches", "Python caches", "pip, poetry, pipx, pyenv downloads, pre-commit, conda packages. Re-downloaded when needed.", rels, "Developer")
    uv = HOME / ".cache/uv"
    if uv.exists() and which("uv"):
        s = size_of(uv)
        if s:
            j.items.append(Item("uv", "~/.cache/uv (uv cache prune)", s))
            j.size = (j.size or 0) + s
    base = j.make_steps

    def make(keys: list[str]) -> list[Step]:
        steps = base([k for k in keys if k != "uv"]) if [k for k in keys if k != "uv"] else []
        if "uv" in keys:
            steps.append(Step("Clean uv cache", [which("uv") or "uv", "cache", "clean"], optional=True))
        return steps
    j.make_steps = make
    return j


def js_caches() -> Junk:
    rels = [".npm/_cacache", ".npm/_logs", ".npm/_npx", ".cache/yarn", ".yarn/berry/cache", ".cache/node-gyp", ".cache/typescript",
            ".cache/bun", ".bun/install/cache", ".cache/deno", ".cache/electron", ".cache/electron-builder", ".cache/prisma",
            ".cache/turbo", ".cache/next-swc", ".cache/nx", ".cache/vite", ".cache/esbuild", ".cache/node", ".cache/corepack"]
    j = _paths_junk("js-caches", "JavaScript caches", "npm, yarn, bun, deno, electron and build tool caches. Your projects are untouched.", rels, "Developer")
    pnpm = which("pnpm") or (glob.glob(str(HOME / ".nvm/versions/node/*/bin/pnpm")) or [None])[0]
    store = HOME / ".local/share/pnpm/store"
    if pnpm and store.exists():
        s = size_of(store)
        j.items.append(Item("pnpm", "~/.local/share/pnpm/store (pnpm store prune - keeps what projects use)", s, default=True))
        j.size = (j.size or 0) + s // 3  # prune usually frees a fraction
    base = j.make_steps

    def make(keys: list[str]) -> list[Step]:
        rest = [k for k in keys if k != "pnpm"]
        steps = base(rest) if rest else []
        if "pnpm" in keys:
            steps.append(Step("Prune pnpm store", [pnpm, "store", "prune"], optional=True))
        return steps
    j.make_steps = make
    return j


def go_rust_caches() -> Junk:
    items: list[Item] = []
    if which("go"):
        gocache = out(["go", "env", "GOCACHE"]) or str(HOME / ".cache/go-build")
        s = size_of(gocache)
        if s:
            items.append(Item("go-cache", f"{_short(gocache)} (go clean -cache)", s))
        modcache = out(["go", "env", "GOMODCACHE"]) or str(HOME / "go/pkg/mod")
        s = size_of(modcache)
        if s:
            items.append(Item("go-mod", f"{_short(modcache)} (go clean -modcache) - re-downloaded on next build", s, default=False))
    for rel in (".cargo/registry/cache", ".cargo/registry/src", ".cargo/git/checkouts"):
        p = HOME / rel
        if p.exists():
            s = size_of(p)
            if s:
                items.append(Item(str(p), _short(str(p)), s))
    rustup = HOME / ".rustup/toolchains"
    if rustup.is_dir() and len(list(rustup.iterdir())) > 1 and which("rustup"):
        active = out(["rustup", "show", "active-toolchain"]).split(" ")[0]
        for tc in rustup.iterdir():
            if tc.name != active:
                items.append(Item(f"rustup:{tc.name}", f"Rust toolchain {tc.name} (not active)", size_of(tc), default=False))

    def make(keys: list[str]) -> list[Step]:
        steps = []
        if "go-cache" in keys:
            steps.append(Step("Clean Go build cache", ["go", "clean", "-cache"], optional=True))
        if "go-mod" in keys:
            steps.append(Step("Clean Go module cache", ["go", "clean", "-modcache"], optional=True))
        paths = [k for k in keys if k.startswith("/")]
        if paths:
            steps.append(_rm_step("Delete Cargo caches", paths))
        for k in keys:
            if k.startswith("rustup:"):
                steps.append(Step(f"Uninstall {k[7:]}", ["rustup", "toolchain", "uninstall", k[7:]], optional=True))
        return steps
    return Junk("go-rust", "Go and Rust caches", "Build caches and downloaded crates. Rebuilt when you next compile.",
                sum(i.size for i in items if i.default), items=items, make_steps=make, group="Developer")


def jvm_caches() -> Junk:
    items = _path_items([".gradle/caches", ".gradle/daemon", ".gradle/native", ".android/cache", ".cache/JetBrains", ".cache/Google/AndroidStudio"])
    wrapper = HOME / ".gradle/wrapper/dists"
    if wrapper.is_dir():
        dists = sorted(wrapper.iterdir(), key=lambda d: d.stat().st_mtime)
        for d in dists[:-1]:
            items.append(Item(str(d), f"{_short(str(d))} (older Gradle version)", size_of(d)))
    for rel, note in ((".m2/repository", "Maven packages - re-downloaded"), (".nuget/packages", ".NET packages - re-downloaded")):
        p = HOME / rel
        if p.exists():
            s = size_of(p)
            if s:
                items.append(Item(str(p), _short(str(p)), s, note, default=False))
    return Junk("jvm", "Java, Android and .NET caches", "Gradle, Android, JetBrains, Maven and NuGet caches.",
                sum(i.size for i in items if i.default), items=items, group="Developer",
                make_steps=lambda keys: [_rm_step("Delete build caches", keys)])


def headless_browsers() -> Junk:
    items = _path_items([".cache/ms-playwright", ".cache/puppeteer", ".cache/Cypress", ".cache/selenium", ".cache/chrome-for-testing",
                         ".local/share/chrome-for-testing"], note="test browsers - re-downloaded by `npx playwright install` etc.")
    for i in items:
        i.default = False
    return Junk("headless-browsers", "Test browsers (Playwright, Puppeteer, Cypress)", "Browsers downloaded for automated tests. Each project re-downloads what it needs.",
                sum(i.size for i in items), items=items, group="Developer", default=False, pick=True,
                make_steps=lambda keys: [_rm_step("Delete test browsers", keys)])


def ai_models() -> Junk:
    items = []
    hf = HOME / ".cache/huggingface/hub"
    if hf.is_dir():
        for d in hf.iterdir():
            if d.is_dir() and d.name.startswith(("models--", "datasets--")):
                items.append(Item(str(d), d.name.replace("models--", "model: ").replace("datasets--", "dataset: ").replace("--", "/"), size_of(d), default=False))
    for rel in (".cache/torch", ".cache/whisper", ".cache/lm-studio/models", ".lmstudio/models", ".cache/gpt4all"):
        p = HOME / rel
        if p.exists():
            s = size_of(p)
            if s:
                items.append(Item(str(p), _short(str(p)), s, default=False))
    ollama = HOME / ".ollama/models"
    if ollama.is_dir() and which("ollama"):
        for line in out(["ollama", "list"], timeout=10).splitlines()[1:]:
            name = line.split()[0] if line.split() else ""
            if name:
                items.append(Item(f"ollama:{name}", f"Ollama model {name}", 0, default=False))

    def make(keys: list[str]) -> list[Step]:
        steps = []
        paths = [k for k in keys if k.startswith("/")]
        if paths:
            steps.append(_rm_step("Delete AI models", paths))
        for k in keys:
            if k.startswith("ollama:"):
                steps.append(Step(f"Remove {k[7:]}", ["ollama", "rm", k[7:]], optional=True))
        return steps
    return Junk("ai-models", "Downloaded AI models", "Hugging Face, Ollama, PyTorch and Whisper models. Big, and downloaded again when a project needs them.",
                sum(i.size for i in items), items=items, make_steps=make, group="Developer", default=False, pick=True)


def vscode_old_extensions() -> Junk:
    items: list[Item] = []
    for base in (HOME / ".vscode/extensions", HOME / ".cursor/extensions", HOME / ".windsurf/extensions", HOME / ".vscode-oss/extensions"):
        if not base.is_dir():
            continue
        obsolete = set()
        try:
            obsolete = set(json.loads(read(base / ".obsolete") or "{}").keys())
        except (json.JSONDecodeError, AttributeError):
            pass
        versions: dict[str, list[tuple[tuple, Path]]] = {}
        for d in base.iterdir():
            if not d.is_dir():
                continue
            if d.name in obsolete:
                items.append(Item(str(d), f"{d.name} (marked obsolete)", size_of(d)))
                continue
            m = re.match(r"^(.+?\..+?)-(\d+\.\d+\.\d+)(?:-.+)?$", d.name)
            if m:
                ver = tuple(int(x) for x in m.group(2).split("."))
                versions.setdefault(m.group(1), []).append((ver, d))
        for ext, vs in versions.items():
            vs.sort()
            for _, d in vs[:-1]:
                if str(d) not in {i.key for i in items}:
                    items.append(Item(str(d), f"{d.name} (older version of {ext})", size_of(d)))
    return Junk("vscode-ext", "Old editor extension versions", "VS Code / Cursor keep old copies after extensions update. The newest version of each stays.",
                sum(i.size for i in items), items=items, group="Developer", warn="Close VS Code / Cursor first.",
                make_steps=lambda keys: [_rm_step("Delete old extension versions", keys)])


VSCODE_CACHES = ["Cache", "CachedData", "CachedExtensionVSIXs", "Code Cache", "GPUCache", "logs", "Service Worker/CacheStorage",
                 "CachedProfilesData", "Crashpad/completed", "DawnCache", "DawnGraphiteCache", "DawnWebGPUCache"]


def editor_caches() -> Junk:
    rels = []
    for app in ("Code", "Cursor", "Windsurf", "VSCodium", "Code - Insiders"):
        rels += [f".config/{app}/{c}" for c in VSCODE_CACHES]
    rels += [".cache/zed", ".local/share/zed/logs", ".local/share/JetBrains/Toolbox/logs"]
    return _paths_junk("editor-caches", "Editor caches (VS Code, Cursor, Zed)", "Old editor builds, logs and caches. Settings and extensions are kept.",
                       rels, "Developer", warn="Close your editors first.")


# ---- deep: stale project folders

def _projects_roots() -> list[Path]:
    from .maint import project_roots
    roots = project_roots()
    for extra in ("Desktop", "src", "work", "repos", "git", "github"):
        p = HOME / extra
        if p.is_dir() and p not in roots:
            roots.append(p)
    return roots


BUILD_DIRS = {".next": "Next.js", ".nuxt": "Nuxt", ".svelte-kit": "SvelteKit", ".turbo": "Turborepo", ".parcel-cache": "Parcel",
              ".angular": "Angular", ".expo": "Expo", ".vite": "Vite", ".docusaurus": "Docusaurus", ".astro": "Astro",
              ".output": "Nitro", "storybook-static": "Storybook"}
PY_CACHE_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".nox", ".hypothesis"}


def scan_projects(days: int = 30, max_depth: int = 6) -> dict[str, list[Item]]:
    """One walk over your project folders collecting everything re-creatable."""
    found: dict[str, list[Item]] = {"node_modules": [], "build": [], "venv": [], "pycache": [], "target": [], "git": []}
    cutoff = time.time() - days * 86400
    seen: set[str] = set()
    for root in _projects_roots():
        base_depth = len(root.parts)
        for cur, dirs, files in os.walk(root):
            depth = len(Path(cur).parts) - base_depth
            last = None

            def idle() -> float:
                nonlocal last
                if last is None:
                    last = storage.latest_mtime(cur, skip={"node_modules", ".git", "target", ".venv", "venv"} | set(BUILD_DIRS))
                return last

            for d in list(dirs):
                p = os.path.join(cur, d)
                if p in seen:
                    continue
                if d == "node_modules" and idle() < cutoff:
                    found["node_modules"].append(Item(p, _short(cur), 0, f"idle {int((time.time() - idle()) / 86400)} days"))
                elif d in BUILD_DIRS and idle() < cutoff:
                    found["build"].append(Item(p, f"{_short(cur)} → {d}", 0, BUILD_DIRS[d]))
                elif d == "target" and "Cargo.toml" in files and idle() < cutoff:
                    found["target"].append(Item(p, _short(cur), 0, "Rust build output"))
                elif d in (".venv", "venv", "env") and (os.path.exists(os.path.join(p, "pyvenv.cfg"))) and idle() < time.time() - 60 * 86400:
                    found["venv"].append(Item(p, f"{_short(cur)} → {d}", 0, f"idle {int((time.time() - idle()) / 86400)} days"))
                elif d in PY_CACHE_DIRS:
                    found["pycache"].append(Item(p, _short(p), 0))
                elif d in ("dist", "build") and (os.path.exists(os.path.join(cur, "package.json")) or os.path.exists(os.path.join(cur, "pyproject.toml"))) \
                        and idle() < cutoff and os.path.isdir(os.path.join(cur, ".git")) \
                        and sh(["git", "-C", cur, "check-ignore", "-q", d], timeout=5).ok:
                    found["build"].append(Item(p, f"{_short(cur)} → {d}", 0, "git-ignored build output"))
                elif d == ".git" and depth <= max_depth:
                    found["git"].append(Item(cur, _short(cur), 0))
            skip = {"node_modules", ".git", "target", ".venv", "venv", "env"} | set(BUILD_DIRS) | PY_CACHE_DIRS | {"dist", "build"}
            dirs[:] = [d for d in dirs if d not in skip and not (d.startswith(".") and d not in (".config",))] if depth < max_depth else []
    # sizes (parallel)
    all_items = [i for k in found for i in found[k] if k != "git"]
    with ThreadPoolExecutor(max_workers=6) as ex:
        for item, s in zip(all_items, ex.map(lambda i: storage.dir_size(i.key), all_items)):
            item.size = s
    # big .git folders worth compacting
    big_git = []
    for g in found["git"]:
        s = storage.dir_size(os.path.join(g.key, ".git"))
        if s > 150 * 1024**2:
            big_git.append(Item(g.key, g.label, s // 4, f".git is {s // 1024**2} MB"))
    found["git"] = big_git
    for k in found:
        found[k] = sorted([i for i in found[k] if i.size > 0 or k == "git"], key=lambda i: -i.size)
    return found


def project_junks(days: int = 30) -> list[Junk]:
    f = scan_projects(days)
    res = []

    def mk(id_, title, desc, items, default_items=False, action="Delete"):
        for i in items:
            i.default = default_items
        return Junk(id_, title, desc, sum(i.size for i in items), items=items, group="Developer", deep=True, pick=not default_items,
                    default=default_items, make_steps=lambda keys: [_rm_step(f"{action} {len(keys)} folders", keys)])
    res.append(mk("node-modules", f"node_modules in projects idle {days}+ days", "Run `npm install` (or pnpm/yarn/bun) in a project to get them back.", f["node_modules"]))
    res.append(mk("build-outputs", f"Build folders in projects idle {days}+ days", ".next, .nuxt, .svelte-kit, .turbo, git-ignored dist/build… Rebuilt on the next build.", f["build"]))
    res.append(mk("rust-target", f"Rust target/ folders idle {days}+ days", "Rust build output. `cargo build` recreates it.", f["target"]))
    res.append(mk("py-venvs", "Python virtual environments idle 60+ days", "Recreate with `uv sync` or `python -m venv .venv && pip install -r requirements.txt`.", f["venv"]))
    res.append(mk("py-cache-dirs", "Python cache folders in projects", "__pycache__, .pytest_cache, .mypy_cache, .ruff_cache… always safe to delete.", f["pycache"], default_items=True))
    git_items = f["git"]
    for i in git_items:
        i.default = False
    res.append(Junk("git-gc", "Large git repositories (compact)", "Runs `git gc` to pack history tighter. Nothing is lost; the size shown is an estimate.",
                    sum(i.size for i in git_items), items=git_items, group="Developer", deep=True, pick=True, default=False,
                    make_steps=lambda keys: [Step(f"Compact {os.path.basename(k)}", ["git", "-C", k, "gc", "--prune=now", "--quiet"], optional=True) for k in keys]))
    return res


def old_runtimes() -> Junk:
    items: list[Item] = []
    if (HOME / ".nvm/versions/node").is_dir():
        from .dev import node_versions
        for v in node_versions():
            if not v["protected"]:
                items.append(Item(v["path"], f"Node {v['version']}", size_of(v["path"]), "not your default or used by pm2", default=False))
    py = HOME / ".pyenv/versions"
    if py.is_dir():
        vf = HOME / ".pyenv/version"
        glob_v = read(vf).split()[0] if vf.exists() and read(vf).split() else ""
        for d in sorted(py.iterdir()):
            if d.is_dir() and d.name != glob_v:
                items.append(Item(str(d), f"Python {d.name} (pyenv)", size_of(d), "not your global Python", default=False))
    return Junk("old-runtimes", "Old Node / Python versions", "Versions you're not using. Your default and the ones pm2 runs on are never listed.",
                sum(i.size for i in items), items=items, group="Developer", deep=True, pick=True, default=False,
                make_steps=lambda keys: [_rm_step(f"Remove {len(keys)} old language versions", keys)])


# ================================================================ APPS & BROWSERS

BROWSERS = {
    "Google Chrome": (".config/google-chrome", ".cache/google-chrome"),
    "Chromium": (".config/chromium", ".cache/chromium"),
    "Brave": (".config/BraveSoftware/Brave-Browser", ".cache/BraveSoftware"),
    "Microsoft Edge": (".config/microsoft-edge", ".cache/microsoft-edge"),
    "Vivaldi": (".config/vivaldi", ".cache/vivaldi"),
    "Opera": (".config/opera", ".cache/opera"),
    "Chromium (snap)": ("snap/chromium/common/chromium", "snap/chromium/common/.cache"),
}
PROFILE_CACHES = ["Service Worker/CacheStorage", "Service Worker/ScriptCache", "Code Cache", "GPUCache", "DawnCache", "DawnGraphiteCache",
                  "DawnWebGPUCache", "Application Cache", "File System", "blob_storage"]


def browser_caches() -> Junk:
    items: list[Item] = []
    for name, (cfg, cache) in BROWSERS.items():
        c = HOME / cache
        if c.exists():
            s = size_of(c)
            if s:
                items.append(Item(str(c), f"{name}: page cache", s))
        conf = HOME / cfg
        if conf.is_dir():
            paths = []
            for prof in [conf / "Default", *conf.glob("Profile *")]:
                paths += [str(prof / pc) for pc in PROFILE_CACHES if (prof / pc).exists()]
            for top in ("GrShaderCache", "ShaderCache", "component_crx_cache", "extensions_crx_cache", "Crashpad/completed"):
                if (conf / top).exists():
                    paths.append(str(conf / top))
            if paths:
                s = size_of(*paths)
                if s:
                    items.append(Item("|".join(paths), f"{name}: service worker + code caches", s))
    for ff in [HOME / ".cache/mozilla/firefox", HOME / "snap/firefox/common/.cache/mozilla/firefox", HOME / ".var/app/org.mozilla.firefox/cache",
               HOME / ".cache/zen", HOME / ".cache/librewolf"]:
        if ff.exists():
            s = size_of(ff)
            if s:
                items.append(Item(str(ff), f"Firefox-family cache: {_short(str(ff))}", s))

    def make(keys: list[str]) -> list[Step]:
        paths = [p for k in keys for p in k.split("|")]
        return [_rm_step("Delete browser caches", paths)] if paths else []
    return Junk("browser-caches", "Browser caches", "Cached pages, scripts and images from every browser. Logins, history, bookmarks and passwords are kept.",
                sum(i.size for i in items), items=items, make_steps=make, group="Apps & browsers", warn="Close your browsers first.")


def chrome_ai_model() -> Junk:
    items = []
    for name, (cfg, _) in BROWSERS.items():
        for sub in ("OptGuideOnDeviceModel", "OnDeviceHeadSuggestModel", "optimization_guide_model_store"):
            p = HOME / cfg / sub
            if p.exists():
                s = size_of(p)
                if s > 5 * 1024**2:
                    items.append(Item(str(p), f"{name}: {sub}", s, "built-in AI model"))
    return Junk("browser-ai", "Browsers' built-in AI models", "Chrome/Edge quietly download a multi-GB AI model (Gemini Nano). Delete it, and turn off "
                "'Optimization guide on device' in chrome://flags so it isn't downloaded again.",
                sum(i.size for i in items), items=items, group="Apps & browsers", default=False, warn="Close your browsers first.",
                make_steps=lambda keys: [_rm_step("Delete browser AI models", keys)])


SKIP_ELECTRON = {"google-chrome", "chromium", "BraveSoftware", "microsoft-edge", "vivaldi", "opera", "Code", "Cursor", "Windsurf", "VSCodium", "Code - Insiders"}
ELECTRON_CACHES = ["Cache", "Code Cache", "GPUCache", "DawnCache", "DawnGraphiteCache", "DawnWebGPUCache", "Service Worker/CacheStorage",
                   "Service Worker/ScriptCache", "Crashpad/completed", "logs", "Partitions/*/Cache", "Partitions/*/Code Cache"]


def app_caches() -> Junk:
    """Electron apps (Slack, Discord, Teams, Postman, Obsidian, Notion, Claude…) and a few known app caches."""
    items: list[Item] = []
    conf = HOME / ".config"
    if conf.is_dir():
        for app in sorted(conf.iterdir()):
            if not app.is_dir() or app.name in SKIP_ELECTRON:
                continue
            paths = []
            for c in ELECTRON_CACHES:
                paths += [p for p in glob.glob(str(app / c)) if os.path.exists(p)]
            if paths:
                s = size_of(*paths)
                if s > 1024 * 1024:
                    items.append(Item("|".join(paths), f"{app.name}: caches", s))
    for label, rel in (("Spotify", ".cache/spotify"), ("Spotify (snap)", "snap/spotify/common/.cache"), ("Zoom logs", ".zoom/logs"),
                       ("Telegram media cache", ".local/share/TelegramDesktop/tdata/user_data"), ("Steam shader cache", ".steam/steam/steamapps/shadercache"),
                       ("Wine cache", ".cache/wine"), ("GNOME Software cache", ".cache/gnome-software"), ("Evolution cache", ".cache/evolution"),
                       ("Fontconfig cache", ".cache/fontconfig"), ("Mesa shader cache", ".cache/mesa_shader_cache"),
                       ("Mesa shader cache", ".cache/mesa_shader_cache_db"), ("NVIDIA cache", ".cache/nvidia")):
        p = HOME / rel
        if p.exists():
            s = size_of(p)
            if s > 1024 * 1024:
                items.append(Item(str(p), label, s, default=label not in ("Telegram media cache", "Steam shader cache")))

    def make(keys: list[str]) -> list[Step]:
        paths = [p for k in keys for p in k.split("|")]
        return [_rm_step("Delete app caches", paths)] if paths else []
    return Junk("app-caches", "App caches (Slack, Discord, Spotify, Postman…)", "Temporary files of desktop apps. Your chats, accounts and settings are kept.",
                sum(i.size for i in items if i.default), items=items, make_steps=make, group="Apps & browsers", warn="Close those apps first.")


def thumbnails() -> Junk:
    return _paths_junk("thumbnails", "Thumbnail previews", "Small preview images the file manager made - including for files you deleted long ago.",
                       [".cache/thumbnails"], "Apps & browsers")


def snap_leftovers() -> Junk:
    base = HOME / "snap"
    if not base.is_dir() or not has("snap"):
        return Junk("snap-leftovers", "Data of removed snap apps", "", 0)
    installed = {ln.split()[0] for ln in out(["snap", "list"]).splitlines()[1:] if ln.split()}
    items = [Item(str(d), f"~/snap/{d.name}", size_of(d)) for d in base.iterdir() if d.is_dir() and d.name not in installed]
    return Junk("snap-leftovers", "Data of removed snap apps", "Folders in ~/snap for apps that aren't installed anymore.", sum(i.size for i in items),
                items=items, group="Apps & browsers", make_steps=lambda keys: [_rm_step("Delete leftover snap data", keys)])


def flatpak_leftovers() -> Junk:
    base = HOME / ".var/app"
    if not base.is_dir():
        return Junk("flatpak-leftovers", "Data of removed Flatpak apps", "", 0)
    installed = set(out(["flatpak", "list", "--app", "--columns=application"]).split()) if has("flatpak") else set()
    items = [Item(str(d), f"~/.var/app/{d.name}", size_of(d)) for d in base.iterdir() if d.is_dir() and d.name not in installed]
    return Junk("flatpak-leftovers", "Data of removed Flatpak apps", "Folders in ~/.var/app for apps that aren't installed anymore.", sum(i.size for i in items),
                items=items, group="Apps & browsers", make_steps=lambda keys: [_rm_step("Delete leftover Flatpak data", keys)])


def texlive_cache() -> Junk:
    rels = [str(Path(p).relative_to(HOME)) for p in glob.glob(str(HOME / ".texlive*/texmf-var")) + glob.glob(str(HOME / ".cache/texlive*"))
            + glob.glob(str(HOME / ".texlive*/texmf-var/luatex-cache"))]
    rels = sorted(set(rels))
    return _paths_junk("texlive", "TeX Live font caches", "LaTeX's generated font and format caches. Rebuilt automatically the next time you compile.",
                       rels[:1] if rels and all(r.startswith(rels[0]) for r in rels) else rels, "Apps & browsers")


def home_logs() -> Junk:
    items = []
    for pattern in (".xsession-errors", ".xsession-errors.old", ".local/share/xorg/*.log*", ".npm/_logs", ".pm2/pm2.log", ".cache/*.log",
                    ".local/state/*/log*", "VirtualBox VMs/*/Logs/*.log.[1-9]", ".local/share/gvfs-metadata/*.log"):
        for p in glob.glob(str(HOME / pattern)):
            s = size_of(p)
            if s > 256 * 1024:
                items.append(Item(p, _short(p), s))
    pm2 = [f for f in glob.glob(str(HOME / ".pm2/logs/*.log")) if os.path.getsize(f) > 1024 * 1024]

    def make(keys: list[str]) -> list[Step]:
        steps = []
        files = [k for k in keys if k != "pm2"]
        if files:
            def trunc() -> str:
                for f in files:
                    if os.path.isfile(f):
                        with open(f, "w"):
                            pass
                    elif os.path.isdir(f):
                        _rm_paths([f])()
                return f"emptied {len(files)} logs"
            steps.append(py_step("Empty log files", trunc, "truncate -s 0 " + " ".join(_short(f) for f in files[:5])))
        if "pm2" in keys:
            def trunc_pm2() -> str:
                for f in pm2:
                    with open(f, "w"):
                        pass
                return f"emptied {len(pm2)} pm2 logs"
            steps.append(py_step("Empty pm2 logs (bots keep running)", trunc_pm2, "truncate -s 0 ~/.pm2/logs/*.log"))
        return steps
    if pm2:
        items.append(Item("pm2", f"pm2 bot logs ({len(pm2)} files)", sum(os.path.getsize(f) for f in pm2)))
    return Junk("home-logs", "Log files in your home folder", "Old session logs, npm logs, pm2 logs, VirtualBox logs. Emptied, not deleted, so running apps are fine.",
                sum(i.size for i in items), items=items, make_steps=make, group="Apps & browsers")


# ================================================================ YOUR FILES

def trash() -> Junk:
    t = HOME / ".local/share/Trash"
    size = size_of(t)
    other = []
    for mp in glob.glob("/media/*/*") + glob.glob("/run/media/*/*"):
        tt = os.path.join(mp, f".Trash-{os.getuid()}")
        if os.path.isdir(tt):
            other.append(tt)
    extra = size_of(*other) if other else 0
    return Junk("trash", "Trash", "Files you deleted in the file manager (including on USB drives). Emptying can't be undone.", size + extra,
                [Step("Empty Trash", ["gio", "trash", "--empty"])] if has("gio") else
                [_rm_step("Empty Trash", [str(t / "files"), str(t / "info"), str(t / "expunged")])],
                default=False, group="Your files")


def downloads_old(days: int = 90) -> Junk:
    entries = storage.old_downloads(days)
    items = [Item(e.path, e.name, e.size, default=False) for e in entries]
    return Junk("downloads", f"Downloads older than {days} days", "Moved to the Trash (not deleted), so you can still get them back.",
                sum(i.size for i in items), items=items, group="Your files", deep=True, pick=True, default=False,
                make_steps=lambda keys: [_trash_step(f"Move {len(keys)} downloads to Trash", keys)])


INSTALLER_EXT = (".iso", ".img", ".deb", ".rpm", ".run", ".exe", ".msi", ".dmg", ".pkg", ".apk", ".xz", ".tar.gz", ".tgz", ".zip", ".7z", ".rar")


def installers() -> Junk:
    items = []
    for d in (HOME / "Downloads", HOME / "Desktop"):
        if not d.is_dir():
            continue
        for e in os.scandir(d):
            if e.is_file() and e.name.lower().endswith(INSTALLER_EXT):
                try:
                    s = e.stat().st_size
                except OSError:
                    continue
                if s > 20 * 1024**2:
                    age = int((time.time() - e.stat().st_mtime) / 86400)
                    items.append(Item(e.path, e.name, s, f"{age} days old", default=False))
    items.sort(key=lambda i: -i.size)
    return Junk("installers", "Installers, disk images and archives", "ISOs, .deb/.exe installers and big zips in Downloads - usually not needed once installed or extracted.",
                sum(i.size for i in items), items=items, group="Your files", pick=True, default=False,
                make_steps=lambda keys: [_trash_step(f"Move {len(keys)} files to Trash", keys)])


def duplicates() -> Junk:
    from .dupes import find_duplicates
    groups = find_duplicates([HOME / d for d in ("Downloads", "Documents", "Pictures", "Desktop", "Music", "Videos")])
    items = []
    for g in groups:
        keep = g[0]
        for f in g[1:]:
            items.append(Item(f["path"], _short(f["path"]), f["size"], f"same as {_short(keep['path'])}", default=True))
    return Junk("duplicates", "Duplicate files", "Exact copies (checked byte by byte). The oldest copy of each file is kept; the others go to the Trash.",
                sum(i.size for i in items), items=items, group="Your files", deep=True, pick=True, default=False,
                make_steps=lambda keys: [_trash_step(f"Move {len(keys)} duplicates to Trash", keys)])


def broken_launchers() -> list[str]:
    res = []
    for f in glob.glob(str(HOME / ".local/share/applications/*.desktop")):
        try:
            text = Path(f).read_text(errors="replace")
        except OSError:
            continue
        m = re.search(r"^Exec=(.*)$", text, re.M)
        if not m:
            continue
        parts = m.group(1).replace('"', "").replace("'", "").split()
        i = 0
        if parts and parts[0].endswith("env"):
            i = 1
            while i < len(parts) and "=" in parts[i]:
                i += 1
        if i >= len(parts):
            continue
        cmd = parts[i]
        if cmd.startswith("/"):
            if not os.path.exists(cmd):
                res.append(f)
        elif not shutil.which(cmd):
            res.append(f)
    return res


def launchers() -> Junk:
    files = broken_launchers()
    backup = STATE / "removed-launchers"
    items = []
    for f in files:
        name = re.search(r"^Name=(.*)$", read(f), re.M)
        items.append(Item(f, name.group(1) if name else os.path.basename(f), os.path.getsize(f)))

    def make(keys: list[str]) -> list[Step]:
        def move() -> str:
            backup.mkdir(parents=True, exist_ok=True)
            for f in keys:
                if os.path.exists(f):
                    shutil.move(f, backup / os.path.basename(f))
            return f"moved {len(keys)} launchers to {_short(str(backup))}"
        return [py_step("Remove broken shortcuts", move, f"mv {len(keys)} .desktop files → {_short(str(backup))}")]
    return Junk("launchers", "Broken app shortcuts", "Icons in your app grid for programs that no longer exist (kept in a backup folder).",
                sum(i.size for i in items), items=items, group="Your files", make_steps=make)


def broken_symlinks() -> Junk:
    items = []
    for root in [HOME / d for d in ("Desktop", "Documents", "Downloads", "bin", ".local/bin")]:
        if not root.is_dir():
            continue
        for cur, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in ("node_modules", ".git", ".venv")]
            for n in files + dirs:
                p = os.path.join(cur, n)
                if os.path.islink(p) and not os.path.exists(p):
                    items.append(Item(p, f"{_short(p)} → {os.readlink(p)}", 0))
            if len(items) > 300:
                break
    return Junk("broken-links", "Broken shortcuts (symlinks)", "Links pointing to files that no longer exist.", 0, items=items, group="Your files",
                default=False, make_steps=lambda keys: [_rm_step("Delete broken links", keys)])


# ================================================================ PRIVACY

def recent_files() -> Junk:
    f = HOME / ".local/share/recently-used.xbel"
    size = f.stat().st_size if f.exists() else 0
    count = read(f).count("<bookmark ") if f.exists() else 0

    def clear() -> str:
        f.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<xbel version="1.0"\n xmlns:bookmark="http://www.freedesktop.org/standards/desktop-bookmarks"\n'
                     ' xmlns:mime="http://www.freedesktop.org/standards/shared-mime-info"\n>\n</xbel>\n')
        return f"cleared {count} entries"
    return Junk("recent-files", "Recent files history", f"The list of {count} files you opened recently (shown in Files and app dialogs).",
                size if count else 0, [py_step("Clear recent files", clear, "reset ~/.local/share/recently-used.xbel")] if count else [],
                default=False, group="Privacy")


def clipboard_history() -> Junk:
    paths = glob.glob(str(HOME / ".cache/clipboard-indicator@tudmotu.com/*")) + glob.glob(str(HOME / ".local/share/clipboard-indicator@tudmotu.com/*"))
    size = sum(os.path.getsize(p) for p in paths if os.path.isfile(p))
    return Junk("clipboard", "Clipboard history", "Everything you copied, saved by the Clipboard Indicator extension (may include passwords you pasted).",
                size, [_rm_step("Clear clipboard history", paths)] if paths else [], default=False, group="Privacy")


# ================================================================ scan

QUICK: list[Callable[[], Junk]] = [
    apt_cache, apt_autoremove, dpkg_residual, snap_old, snap_cache, flatpak_unused, journal, rotated_logs, crash_reports, temp_files,
    packagekit_cache, python_caches, js_caches, go_rust_caches, jvm_caches, headless_browsers, ai_models, vscode_old_extensions,
    editor_caches, containers, browser_caches, chrome_ai_model, app_caches, thumbnails, snap_leftovers, flatpak_leftovers, texlive_cache,
    home_logs, waydroid_left, trash, installers, launchers, broken_symlinks, recent_files, clipboard_history,
]
DEEP: list[Callable[[], Junk]] = [old_runtimes, downloads_old, duplicates]


def _safe(fn: Callable[[], Junk]) -> Junk:
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 - one broken check shouldn't stop the scan
        return Junk(fn.__name__, fn.__name__.replace("_", " "), f"Couldn't check: {e}", 0)


def worth_showing(j: Junk) -> bool:
    if not j.steps_for([i.key for i in j.items] if j.items else None) and not j.steps:
        return False
    if j.size is None:
        return True
    return j.size >= 100 * 1024 or any(i.size for i in j.items) or (bool(j.items) and not any(i.size for i in j.items) and j.id in ("dpkg-rc", "broken-links", "git-gc"))


def scan(deep: bool = False, on_result: Callable[[Junk], None] | None = None, workers: int = 6) -> list[Junk]:
    fns = list(QUICK) + (list(DEEP) if deep else [])
    res: list[Junk] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_safe, fn) for fn in fns]
        if deep:
            futs.append(ex.submit(lambda: project_junks()))
        for f in futs:
            r = f.result()
            for j in (r if isinstance(r, list) else [r]):
                if worth_showing(j):
                    res.append(j)
                    if on_result:
                        on_result(j)
    order = {g: i for i, g in enumerate(GROUPS)}
    res.sort(key=lambda j: (order.get(j.group, 9), -(j.size or 0)))
    return res


def safe_user_steps(junks: list[Junk]) -> list[Step]:
    """For the weekly automatic run: only things that never need a password or a decision."""
    keep = {"py-caches", "js-caches", "thumbnails", "home-logs", "vscode-ext"}
    return [s for j in junks if j.id in keep for s in j.steps_for() if not s.root]


def auto_candidates() -> list[Junk]:
    return [_safe(f) for f in (python_caches, js_caches, thumbnails, home_logs, vscode_old_extensions)]


# kept for older callers
def user_caches() -> Junk:
    a, b = python_caches(), js_caches()
    return Junk("user-caches", "Developer caches", "pip, npm and friends", (a.size or 0) + (b.size or 0), items=a.items + b.items, group="Developer",
                make_steps=lambda keys: (a.make_steps([k for k in keys if k in {i.key for i in a.items}]) if a.make_steps else [])
                + (b.make_steps([k for k in keys if k in {i.key for i in b.items}]) if b.make_steps else []))


def pm2_logs() -> Junk:
    return home_logs()

"""Drives and partitions, USB mount/unmount/eject, readable SMART health, swap, a quick speed test, Trash, and
file-type / empty-file / similar-photo finders."""

from __future__ import annotations

import json
import os
import shutil
import time
import urllib.parse
from pathlib import Path
from typing import Callable

from .run import HOME, Step, has, out, py_step

# ---------------------------------------------------------------- drives + partitions

LSBLK_COLS = "NAME,PATH,SIZE,TYPE,FSTYPE,LABEL,MOUNTPOINTS,MODEL,RM,HOTPLUG,TRAN,ROTA,FSUSED,FSAVAIL,UUID,PKNAME"


def parse_lsblk(text: str) -> list[dict]:
    try:
        devs = json.loads(text).get("blockdevices", [])
    except (ValueError, AttributeError):
        return []

    def norm(d: dict) -> dict:
        mps = [m for m in (d.get("mountpoints") or []) if m]
        return {"name": d.get("name", ""), "path": d.get("path") or f"/dev/{d.get('name', '')}", "size": int(d.get("size") or 0),
                "type": d.get("type", ""), "fstype": d.get("fstype") or "", "label": d.get("label") or "", "mounts": mps,
                "model": (d.get("model") or "").strip(), "removable": d.get("rm") in (True, "1", 1) or d.get("hotplug") in (True, "1", 1),
                "tran": d.get("tran") or "", "rota": d.get("rota") in (True, "1", 1), "used": int(d.get("fsused") or 0),
                "avail": int(d.get("fsavail") or 0), "uuid": d.get("uuid") or "",
                "children": [norm(c) for c in d.get("children", []) or []]}
    res = [norm(d) for d in devs]
    return [d for d in res if d["type"] in ("disk", "rom") and not d["name"].startswith(("loop", "zram", "ram"))]


def block_devices() -> list[dict]:
    return parse_lsblk(out(["lsblk", "-J", "-b", "-o", LSBLK_COLS], timeout=15))


def mount_steps(dev: str) -> list[Step]:
    return [Step(f"Mount {dev}", ["udisksctl", "mount", "-b", dev])]


def unmount_steps(dev: str) -> list[Step]:
    return [Step(f"Unmount {dev}", ["udisksctl", "unmount", "-b", dev])]


def eject_steps(disk: dict) -> list[Step]:
    steps = [Step(f"Unmount {p['path']}", ["udisksctl", "unmount", "-b", p["path"]], ok_codes=(0, 1))
             for p in (disk["children"] or [disk]) if p["mounts"]]
    steps.append(Step(f"Power off {disk['model'] or disk['path']} (safe to unplug)", ["udisksctl", "power-off", "-b", disk["path"]]))
    return steps


# ---------------------------------------------------------------- SMART (drive health)

def smart_steps(dev: str) -> list[Step]:
    steps = []
    if not has("smartctl"):
        steps.append(Step("Install smartmontools", ["apt-get", "install", "-y", "smartmontools"], root=True, env={"DEBIAN_FRONTEND": "noninteractive"}))
    steps.append(Step(f"Read the health report of {dev}", ["smartctl", "-j", "-a", dev], root=True, ok_codes=tuple(range(0, 256))))
    return steps


def parse_smart(text: str) -> dict:
    """Plain-language summary of `smartctl -j -a`."""
    start = text.find("{")
    try:
        d = json.loads(text[start:]) if start >= 0 else {}
    except ValueError:
        # the runner may interleave lines; take the largest JSON object
        end = text.rfind("}")
        try:
            d = json.loads(text[start:end + 1])
        except ValueError:
            return {"ok": None, "facts": [], "verdict": "Couldn't read the drive's health report."}
    facts: list[tuple[str, str, str]] = []  # (label, value, level)
    passed = (d.get("smart_status") or {}).get("passed")
    model = d.get("model_name") or d.get("model_family") or ""
    if d.get("temperature", {}).get("current") is not None:
        t = d["temperature"]["current"]
        facts.append(("Temperature", f"{t}°C", "ok" if t < 60 else ("warn" if t < 70 else "bad")))
    if d.get("power_on_time", {}).get("hours") is not None:
        h = d["power_on_time"]["hours"]
        facts.append(("Powered on", f"{h:,} hours ({h / 24 / 365:.1f} years)", "ok"))
    if d.get("power_cycle_count") is not None:
        facts.append(("Times switched on", f"{d['power_cycle_count']:,}", "ok"))
    wear = None
    nv = d.get("nvme_smart_health_information_log") or {}
    if nv:
        wear = nv.get("percentage_used")
        if nv.get("available_spare") is not None:
            sp, th = nv["available_spare"], nv.get("available_spare_threshold", 10)
            facts.append(("Spare blocks left", f"{sp}%", "ok" if sp > th + 10 else ("warn" if sp > th else "bad")))
        if nv.get("media_errors") is not None:
            facts.append(("Data errors", str(nv["media_errors"]), "ok" if nv["media_errors"] == 0 else "bad"))
        if nv.get("unsafe_shutdowns") is not None:
            facts.append(("Unsafe shutdowns", f"{nv['unsafe_shutdowns']:,}", "ok"))
        if nv.get("data_units_written") is not None:
            tb = nv["data_units_written"] * 512000 / 1e12
            facts.append(("Written in its life", f"{tb:.1f} TB", "ok"))
    for a in (d.get("ata_smart_attributes") or {}).get("table", []):
        name, raw = a.get("name", ""), (a.get("raw") or {}).get("value", 0)
        if a.get("id") in (5, 196, 197, 198):
            facts.append((name.replace("_", " "), str(raw), "ok" if raw == 0 else "bad"))
        elif a.get("id") in (177, 231, 233) and wear is None:
            wear = max(0, 100 - int(a.get("value") or 100))
        elif a.get("id") == 241:
            facts.append(("Written in its life", f"{raw * 512 / 1e12:.1f} TB", "ok"))
    if wear is not None:
        facts.insert(0, ("Wear", f"{wear}% used", "ok" if wear < 70 else ("warn" if wear < 90 else "bad")))
    bad = any(lvl == "bad" for _, _, lvl in facts)
    if passed is False:
        verdict, ok = "FAILING: the drive reports it may die soon. Back up now and replace it.", False
    elif bad:
        verdict, ok = "Warning signs: back up important files and keep an eye on it.", False
    elif passed:
        verdict, ok = "Healthy: the drive passes its own self-assessment.", True
    else:
        verdict, ok = "The drive didn't report an overall health result.", None
    return {"ok": ok, "verdict": verdict, "facts": facts, "model": model, "serial": d.get("serial_number", "")}


# ---------------------------------------------------------------- swap

def swap_info() -> list[dict]:
    res = []
    try:
        lines = open("/proc/swaps").read().splitlines()[1:]
    except OSError:
        return res
    for ln in lines:
        p = ln.split()
        if len(p) >= 4:
            res.append({"path": p[0], "type": p[1], "size": int(p[2]) * 1024, "used": int(p[3]) * 1024, "zram": "zram" in p[0]})
    return res


def resize_swapfile_steps(gb: int, path: str = "/swap.img") -> list[Step]:
    if not 1 <= int(gb) <= 256:
        raise ValueError("Swap size must be between 1 and 256 GB")
    p = Path(path)
    if not p.is_absolute() or p == Path("/") or "\n" in path or "\x00" in path:
        raise ValueError("Swap file must be a safe absolute path")
    # Build the replacement first, then switch over. If activation of the new swap
    # fails, the previous file is put back and re-enabled. Parameters are positional
    # shell arguments rather than interpolated strings, so unusual paths cannot inject
    # shell syntax.
    script = r'''
set -euo pipefail
path=$1
gb=$2
tmp="${path}.pc-new.$$"
old="${path}.pc-old.$$"
fstab_bak="/etc/fstab.pc-control-$(date +%Y%m%d-%H%M%S).bak"
cleanup() { rm -f -- "$tmp"; }
trap cleanup EXIT

mkdir -p -- "$(dirname -- "$path")"
if ! fallocate -l "${gb}G" "$tmp"; then
  dd if=/dev/zero of="$tmp" bs=1M count="$((gb * 1024))" status=progress
fi
chmod 600 "$tmp"
mkswap "$tmp"

had_old=0
if [ -e "$path" ]; then
  # Do not delete the current swap if the kernel cannot safely turn it off.
  swapoff "$path"
  mv -- "$path" "$old"
  had_old=1
fi
mv -- "$tmp" "$path"
trap - EXIT

if ! swapon "$path"; then
  rm -f -- "$path"
  if [ "$had_old" = 1 ] && [ -e "$old" ]; then
    mv -- "$old" "$path"
    swapon "$path" || true
  fi
  exit 1
fi

cp -a /etc/fstab "$fstab_bak"
line="$path none swap sw 0 0"
grep -qF -- "$line" /etc/fstab || printf '%s\n' "$line" >> /etc/fstab
rm -f -- "$old"
echo "Swap is active. fstab backup: $fstab_bak"
'''
    return [Step(f"Safely resize the swap file to {gb} GB", ["bash", "-c", script, "pc-swap", str(p), str(int(gb))],
                 root=True, cancellable=False)]


# ---------------------------------------------------------------- quick disk speed test

def speed_test(folder: str | Path = HOME / ".cache", size_mb: int = 512, progress: Callable[[str], None] | None = None) -> dict:
    """Sequential write + read of a temporary file. Uses fsync and drops the file from the page cache so the numbers
    are the disk's, not RAM's."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / "pc-speed-test.bin"
    free = shutil.disk_usage(folder).free
    if free < size_mb * 1024 ** 2 * 2:
        return {"error": "Not enough free space for the test."}
    block = os.urandom(4 * 1024 * 1024)
    try:
        if progress:
            progress("Writing…")
        t0 = time.monotonic()
        fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            for _ in range(size_mb // 4):
                os.write(fd, block)
            os.fsync(fd)
        finally:
            os.close(fd)
        wt = time.monotonic() - t0
        fd = os.open(f, os.O_RDONLY)
        try:
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        finally:
            os.close(fd)
        if progress:
            progress("Reading…")
        t0 = time.monotonic()
        fd = os.open(f, os.O_RDONLY)
        try:
            while os.read(fd, 4 * 1024 * 1024):
                pass
        finally:
            os.close(fd)
        rt = time.monotonic() - t0
    finally:
        try:
            f.unlink()
        except OSError:
            pass
    return {"write_mbs": size_mb / wt if wt else 0, "read_mbs": size_mb / rt if rt else 0, "size_mb": size_mb, "folder": str(folder)}


def speed_verdict(read_mbs: float) -> str:
    if read_mbs > 1500:
        return "NVMe-class speed. Excellent."
    if read_mbs > 400:
        return "SSD speed. Good."
    if read_mbs > 120:
        return "Hard-disk or slow-SSD speed. Fine for storage, slow for the system."
    return "Slow. If this is your system disk, an SSD would make everything much faster."


# ---------------------------------------------------------------- Trash

TRASH = HOME / ".local/share/Trash"


def trash_items() -> list[dict]:
    res = []
    info_dir, files_dir = TRASH / "info", TRASH / "files"
    if not info_dir.is_dir():
        return res
    from .run import py_size
    for info in info_dir.glob("*.trashinfo"):
        name = info.name[:-len(".trashinfo")]
        target = files_dir / name
        orig, when = "", ""
        try:
            for line in info.read_text(errors="replace").splitlines():
                if line.startswith("Path="):
                    orig = urllib.parse.unquote(line[5:])
                elif line.startswith("DeletionDate="):
                    when = line[13:]
        except OSError:
            continue
        if not os.path.lexists(target):
            continue
        size = py_size(target, limit_s=5)
        ts = 0.0
        try:
            ts = time.mktime(time.strptime(when[:19], "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            pass
        res.append({"name": name, "path": str(target), "info": str(info), "original": orig, "deleted": ts, "size": size,
                    "is_dir": target.is_dir()})
    res.sort(key=lambda r: -r["deleted"])
    return res


def restore_trash(item: dict) -> str:
    dest = item["original"]
    if not dest:
        raise OSError("don't know where it came from")
    if os.path.lexists(dest):
        base, ext = os.path.splitext(dest)
        dest = f"{base} (restored){ext}"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.move(item["path"], dest)
    try:
        os.unlink(item["info"])
    except OSError:
        pass
    return dest


def delete_trash_steps(items: list[dict]) -> list[Step]:
    def run() -> str:
        n = 0
        for it in items:
            p = it["path"]
            if not p.startswith(str(TRASH) + "/"):
                continue
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                try:
                    os.unlink(p)
                except OSError:
                    pass
            try:
                os.unlink(it["info"])
            except OSError:
                pass
            n += 1
        return f"deleted {n} item(s) for good"
    return [py_step(f"Delete {len(items)} item(s) from the Trash for good", run, "rm -rf ~/.local/share/Trash/files/<chosen>")]


# ---------------------------------------------------------------- file types

TYPES = {
    "Videos": {"mp4", "mkv", "mov", "avi", "webm", "m4v", "wmv", "flv", "mpg", "mpeg", "3gp"},
    "Photos": {"jpg", "jpeg", "png", "gif", "webp", "heic", "heif", "bmp", "tif", "tiff", "raw", "cr2", "nef", "arw", "dng", "svg", "avif"},
    "Music": {"mp3", "flac", "wav", "ogg", "m4a", "aac", "opus", "wma"},
    "Documents": {"pdf", "doc", "docx", "odt", "xls", "xlsx", "ods", "ppt", "pptx", "odp", "txt", "md", "epub", "rtf", "tex", "csv"},
    "Archives & installers": {"zip", "tar", "gz", "tgz", "xz", "bz2", "7z", "rar", "zst", "iso", "img", "deb", "rpm", "appimage", "exe", "msi", "dmg"},
    "Code": {"py", "js", "ts", "tsx", "jsx", "go", "rs", "java", "c", "cpp", "h", "hpp", "cs", "rb", "php", "html", "css", "scss", "json",
             "yml", "yaml", "toml", "sh", "sql", "vue", "svelte", "kt", "swift", "dart", "lua", "ipynb"},
    "Virtual machines": {"vdi", "vmdk", "qcow2", "vhd", "vhdx", "ova", "ovf"},
}
SKIP_TYPES_DIRS = {".git", "node_modules", ".cache", ".npm", ".nvm", ".cargo", ".rustup", ".pyenv", ".venv", "venv", "__pycache__", ".local",
                   "snap", ".var", ".gradle", ".m2", ".vscode", ".config", ".mozilla"}


def file_types(root: str | Path = HOME, limit_s: float = 90.0, progress: Callable[[str], None] | None = None) -> dict:
    """Space by kind of file in your personal folders (skips caches, apps and code dependencies)."""
    ext_type = {e: t for t, es in TYPES.items() for e in es}
    totals: dict[str, list] = {t: [0, 0] for t in TYPES}
    totals["Other"] = [0, 0]
    exts: dict[str, list] = {}
    t0 = time.monotonic()
    n = 0
    partial = False
    for cur, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_TYPES_DIRS and not (d.startswith(".") and cur == str(root))]
        for name in files:
            fp = os.path.join(cur, name)
            try:
                st = os.lstat(fp)
            except OSError:
                continue
            if not os.path.isfile(fp) or os.path.islink(fp):
                continue
            ext = name.rsplit(".", 1)[-1].lower() if "." in name.lstrip(".") else ""
            t = ext_type.get(ext, "Other")
            size = st.st_blocks * 512
            totals[t][0] += size
            totals[t][1] += 1
            e = exts.setdefault(ext or "(none)", [0, 0])
            e[0] += size
            e[1] += 1
            n += 1
        if progress and n and n % 5000 < len(files):
            progress(f"{n:,} files looked at")
        if time.monotonic() - t0 > limit_s:
            partial = True
            break
    return {"types": {k: {"size": v[0], "count": v[1]} for k, v in totals.items()},
            "exts": sorted(((k, v[0], v[1]) for k, v in exts.items()), key=lambda x: -x[1])[:25], "files": n, "partial": partial}


# ---------------------------------------------------------------- empty folders / empty files

def empty_things(roots: list[Path], limit: int = 2000) -> dict:
    empty_dirs, empty_files = [], []
    for root in roots:
        if not root.is_dir():
            continue
        for cur, dirs, files in os.walk(root, topdown=False):
            base = os.path.basename(cur)
            if any(part in SKIP_TYPES_DIRS for part in Path(cur).parts) or base.startswith("."):
                continue
            for f in files:
                fp = os.path.join(cur, f)
                try:
                    if os.path.isfile(fp) and not os.path.islink(fp) and os.path.getsize(fp) == 0 and not f.startswith(".") \
                            and f not in ("__init__.py", "py.typed", ".gitkeep", ".keep"):
                        empty_files.append(fp)
                except OSError:
                    pass
            try:
                if cur != str(root) and not os.listdir(cur):
                    empty_dirs.append(cur)
            except OSError:
                pass
            if len(empty_dirs) + len(empty_files) > limit:
                break
    return {"dirs": empty_dirs, "files": empty_files}


# ---------------------------------------------------------------- similar photos (perceptual hash)

IMAGE_EXT = {"jpg", "jpeg", "png", "webp", "bmp", "gif", "tif", "tiff", "heic"}


def _dhash(path: str) -> int | None:
    """64-bit difference hash: 9x8 greyscale thumbnail, compare neighbours. Robust to resizing and recompression."""
    try:
        from PIL import Image  # type: ignore
        im = Image.open(path)
        if im.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
            im = Image.alpha_composite(bg, im.convert("RGBA"))
        im = im.convert("L").resize((9, 8))
        px = list(im.getdata())
        w = 9
    except Exception:  # noqa: BLE001 - fall back to GdkPixbuf (always there on a GNOME desktop)
        try:
            import gi
            gi.require_version("GdkPixbuf", "2.0")
            from gi.repository import GdkPixbuf
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 9, 8, False)
            if pb.get_width() != 9 or pb.get_height() != 8:
                pb = pb.scale_simple(9, 8, GdkPixbuf.InterpType.BILINEAR)
            data = pb.get_pixels()
            n, rs = pb.get_n_channels(), pb.get_rowstride()
            px = []
            for y in range(8):
                for x in range(9):
                    o = y * rs + x * n
                    v = (data[o] * 299 + data[o + 1] * 587 + data[o + 2] * 114) // 1000
                    if n == 4:  # transparent areas count as white
                        a = data[o + 3]
                        v = (v * a + 255 * (255 - a)) // 255
                    px.append(v)
            w = 9
        except Exception:  # noqa: BLE001
            return None
    h = 0
    for y in range(8):
        for x in range(8):
            h = (h << 1) | (1 if px[y * w + x] > px[y * w + x + 1] else 0)
    return h


def similar_images(roots: list[Path], max_distance: int = 6, progress: Callable[[str], None] | None = None, limit: int = 20000) -> list[list[dict]]:
    files = []
    for root in roots:
        if not root.is_dir():
            continue
        for cur, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_TYPES_DIRS and not d.startswith(".")]
            for n in names:
                if n.rsplit(".", 1)[-1].lower() in IMAGE_EXT:
                    files.append(os.path.join(cur, n))
            if len(files) >= limit:
                break
    hashes = []
    for i, f in enumerate(files):
        if progress and i % 100 == 0:
            progress(f"{i:,} of {len(files):,} photos")
        h = _dhash(f)
        if h is not None:
            try:
                st = os.stat(f)
            except OSError:
                continue
            hashes.append((h, f, st.st_size, st.st_mtime))
    # Pigeonhole banding: split each 64-bit hash into 8 bytes. Two hashes within 7 bits of each other share at least one
    # identical byte, so only photos sharing a byte in the same position need comparing.
    buckets: dict[tuple[int, int], list[int]] = {}
    for i, (h, *_rest) in enumerate(hashes):
        for band in range(8):
            buckets.setdefault((band, (h >> (band * 8)) & 0xFF), []).append(i)
    parent = list(range(len(hashes)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for members in buckets.values():
        if len(members) < 2 or len(members) > 2000:
            continue
        for a_i, a in enumerate(members):
            for b in members[a_i + 1:]:
                if bin(hashes[a][0] ^ hashes[b][0]).count("1") <= max_distance:
                    ra, rb = find(a), find(b)
                    if ra != rb:
                        parent[rb] = ra
    clusters: dict[int, list[int]] = {}
    for i in range(len(hashes)):
        clusters.setdefault(find(i), []).append(i)
    groups: list[list[dict]] = []
    for members in clusters.values():
        if len(members) < 2:
            continue
        grp = sorted((hashes[i][1:] for i in members), key=lambda x: -x[1])  # biggest (usually best quality) first
        groups.append([{"path": g[0], "size": g[1], "mtime": g[2]} for g in grp])
    groups.sort(key=lambda g: -sum(x["size"] for x in g[1:]))
    return groups

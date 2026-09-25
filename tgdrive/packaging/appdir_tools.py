"""Helpers for build_appimage.sh: trim the AppDir and check its glibc floor.

    python3 appdir_tools.py trim-python  APPDIR
    python3 appdir_tools.py trim-qt      APPDIR
    python3 appdir_tools.py check-glibc  APPDIR MAX      (e.g. 2.28)
    python3 appdir_tools.py sizes        APPDIR
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

# PyQt6 modules the app imports (directly or through another module).
QT_KEEP_MODULES = {
    "QtCore", "QtGui", "QtWidgets", "QtNetwork", "QtSvg", "QtSvgWidgets", "QtDBus",
    "QtWebEngineCore", "QtWebEngineWidgets", "QtWebChannel", "QtPrintSupport", "QtOpenGL", "QtOpenGLWidgets",
    "QtMultimedia", "QtMultimediaWidgets", "QtQuick", "QtQml", "QtQuickWidgets", "QtPositioning",
}
# Plugin folders Qt needs for a widgets + web engine + multimedia app on X11/Wayland.
QT_KEEP_PLUGINS = {
    "platforms", "platformthemes", "platforminputcontexts", "xcbglintegrations", "egldeviceintegrations",
    "wayland-decoration-client", "wayland-graphics-integration-client", "wayland-shell-integration",
    "imageformats", "iconengines", "multimedia", "tls", "networkinformation", "generic", "printsupport",
}


def site_packages(appdir: Path) -> Path:
    return next((appdir / "usr/python/lib").glob("python3.*/site-packages"))


def elf_files(root: Path):
    for p in root.rglob("*"):
        if p.is_file() and not p.is_symlink():
            try:
                with open(p, "rb") as f:
                    if f.read(4) == b"\x7fELF":
                        yield p
            except OSError:
                pass


def needed(path: Path) -> list[str]:
    out = subprocess.run(["objdump", "-p", str(path)], capture_output=True, text=True).stdout
    return re.findall(r"^\s*NEEDED\s+(\S+)", out, re.M)


def glibc_versions(path: Path) -> set[tuple[int, ...]]:
    out = subprocess.run(["objdump", "-T", str(path)], capture_output=True, text=True).stdout
    return {tuple(int(x) for x in v.split(".")) for v in re.findall(r"GLIBC_(\d+(?:\.\d+)+)", out)}


def rm(p: Path) -> int:
    if not p.exists() and not p.is_symlink():
        return 0
    if p.is_dir() and not p.is_symlink():
        size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file() and not f.is_symlink())
        shutil.rmtree(p)
    else:
        size = p.lstat().st_size
        p.unlink()
    return size


def trim_python(appdir: Path) -> None:
    py = appdir / "usr/python"
    lib = next((py / "lib").glob("python3.*"))
    freed = 0
    for name in ("test", "idlelib", "tkinter", "turtledemo", "ensurepip", "lib2to3", "pydoc_data", "unittest/test",
                 "turtle.py", "sqlite3/test", "ctypes/test", "distutils/tests"):
        freed += rm(lib / name)
    for p in list(lib.glob("config-3.*")):
        freed += rm(p)
    for p in list(lib.glob("lib-dynload/_tkinter*")) + list(lib.glob("lib-dynload/_test*")) + \
            list(lib.glob("lib-dynload/xxlimited*")) + list(lib.glob("lib-dynload/_ctypes_test*")):
        freed += rm(p)
    for d in ("include", "share"):
        freed += rm(py / d)
    for p in list((py / "lib").glob("libtcl*")) + list((py / "lib").glob("libtk*")) + \
            list((py / "lib").glob("tcl*")) + list((py / "lib").glob("tk*")) + list((py / "lib").glob("itcl*")) + \
            list((py / "lib").glob("thread2*")) + list((py / "lib").glob("pkgconfig")) + \
            list((py / "lib").glob("*.a")):
        freed += rm(p)
    for p in list((py / "bin").iterdir()):
        if p.name.startswith(("idle", "pydoc", "2to3", "pip")) or p.name.endswith("-config"):
            freed += rm(p)
    sp = site_packages(appdir)
    for p in list(sp.glob("pip")) + list(sp.glob("pip-*")) + list(sp.glob("setuptools*")) + \
            list(sp.glob("_distutils_hack")) + list(sp.glob("distutils-precedence.pth")) + list(sp.glob("pkg_resources")):
        freed += rm(p)
    # C sources, type stubs and test folders shipped inside wheels
    for pat in ("**/*.pyi", "**/*.c", "**/*.pyx", "**/*.pxd", "**/tests"):
        for p in list(sp.glob(pat)):
            if p.exists() or p.is_symlink():
                freed += rm(p)
    print(f"trim-python: freed {freed / 1e6:.1f} MB")


def trim_qt(appdir: Path) -> None:
    sp = site_packages(appdir)
    pyqt = sp / "PyQt6"
    qt = pyqt / "Qt6"
    freed = 0
    # 1. PyQt6 extension modules the app never imports
    for so in pyqt.glob("Qt*.abi3.so"):
        if so.name.split(".")[0] not in QT_KEEP_MODULES:
            freed += rm(so)
    freed += rm(pyqt / "bindings")
    freed += rm(pyqt / "uic")
    freed += rm(pyqt / "lupdate")
    freed += rm(qt / "qml")
    for d in (qt / "plugins").iterdir() if (qt / "plugins").exists() else ():
        if d.name not in QT_KEEP_PLUGINS:
            freed += rm(d)
    # Keep only English + a few UI languages for Qt's own dialogs; web engine locales are kept (small, needed).
    tr = qt / "translations"
    if tr.exists():
        for p in tr.glob("*.qm"):
            if not re.match(r"qt(base|webengine|multimedia)?_(en|hi|de|fr|es|ru|pt|it|ja|zh_CN)\.qm$", p.name):
                freed += rm(p)
        # Chromium's own UI strings (context menus, form validation): same languages
        for p in (tr / "qtwebengine_locales").glob("*.pak"):
            if p.stem not in {"en-US", "en-GB", "hi", "bn", "mr", "ta", "te", "gu", "kn", "ml", "de", "fr", "es",
                              "ru", "pt-BR", "it", "ja", "zh-CN"}:
                freed += rm(p)
    freed += rm(qt / "resources" / "qtwebengine_devtools_resources.pak")  # developer tools are never opened

    # 2. Qt shared libraries nothing left references
    libdir = qt / "lib"
    libs = {p.name: p for p in libdir.glob("*.so*")}
    roots = [p for p in pyqt.glob("*.so") if p.is_file()] + list(elf_files(qt / "plugins")) + \
        [p for p in (qt / "libexec").glob("*") if p.is_file()]
    seen: set[str] = set()
    stack = list(roots)
    while stack:
        f = stack.pop()
        for n in needed(f):
            if n in libs and n not in seen:
                seen.add(n)
                stack.append(libs[n].resolve())
    # ICU and friends are loaded by name at runtime; keep anything that is not a Qt module library
    for name, p in libs.items():
        base = name.split(".so")[0]
        if base.startswith("libQt6") and name not in seen and not any(s.startswith(base + ".so") for s in seen):
            freed += rm(p)

    # 3. plugins whose libraries are now gone would only print load errors
    present = {p.name for p in libdir.glob("*.so*")}
    for plug in list(elf_files(qt / "plugins")):
        missing = [n for n in needed(plug) if n.startswith("libQt6") and n not in present]
        if missing:
            freed += rm(plug)
    print(f"trim-qt: freed {freed / 1e6:.1f} MB")


def check_glibc(appdir: Path, maximum: str) -> None:
    limit = tuple(int(x) for x in maximum.split("."))
    bad = []
    for f in elf_files(appdir):
        vs = glibc_versions(f)
        if vs and max(vs) > limit:
            bad.append((".".join(map(str, max(vs))), f.relative_to(appdir)))
    if bad:
        for v, f in sorted(bad, reverse=True)[:40]:
            print(f"  needs GLIBC_{v}: {f}")
        sys.exit(f"check-glibc: {len(bad)} file(s) need a glibc newer than {maximum}")
    print(f"check-glibc: every binary runs on glibc {maximum}+")


def sizes(appdir: Path) -> None:
    rows = []
    sp = site_packages(appdir)
    for base in (sp, appdir / "usr/python/lib", appdir / "usr/app", sp / "PyQt6/Qt6", sp / "PyQt6/Qt6/lib"):
        for p in base.iterdir():
            total = sum(f.stat().st_size for f in p.rglob("*") if f.is_file() and not f.is_symlink()) \
                if p.is_dir() else p.stat().st_size
            rows.append((total, str(p.relative_to(appdir))))
    for total, name in sorted(rows, reverse=True)[:30]:
        print(f"{total / 1e6:8.1f} MB  {name}")


if __name__ == "__main__":
    cmd, appdir = sys.argv[1], Path(sys.argv[2])
    if cmd == "trim-python":
        trim_python(appdir)
    elif cmd == "trim-qt":
        trim_qt(appdir)
    elif cmd == "check-glibc":
        check_glibc(appdir, sys.argv[3])
    elif cmd == "sizes":
        sizes(appdir)
    else:
        sys.exit(__doc__)

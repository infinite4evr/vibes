#!/usr/bin/env bash
# Build TG Drive as one self-contained AppImage for 64-bit Linux.
#
#   packaging/build_appimage.sh        ->  dist/TG_Drive-<version>-x86_64.AppImage
#
# Runs on any x86_64 Linux with glibc 2.28 or newer (Ubuntu 20.04+, Debian 10+,
# Fedora 29+, RHEL/Alma/Rocky 8+, openSUSE 15.1+, Arch, Mint 20+ …).
#
# Needs: bash, curl, dpkg-deb (or ar + tar with zstd), objdump (binutils), python3,
# uv (or PYTHON_DIST pointing at an unpacked python-build-standalone build),
# and network access to PyPI, GitHub releases and archive.ubuntu.com.
# Everything downloaded is cached in build/cache, so rebuilding is quick.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG="$SRC/packaging"
VERSION="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$SRC/tgdrive/config.py")"
BUILD="${BUILD_DIR:-$SRC/build}"
CACHE="${CACHE_DIR:-$BUILD/cache}"
DIST="${DIST_DIR:-$SRC/dist}"
APPDIR="$BUILD/AppDir"
OUT="$DIST/TG_Drive-$VERSION-x86_64.AppImage"
PY_VER="${PY_VER:-3.12}"
GLIBC_MAX="${GLIBC_MAX:-2.28}"
UBUNTU="http://archive.ubuntu.com/ubuntu/pool"
# X11 helper libraries Qt's xcb platform plugin needs but many desktops don't install
# (built on Ubuntu 22.04; they only use glibc symbols from 2.14 or older).
XCB_DEBS=(
  "universe/x/xcb-util-cursor/libxcb-cursor0_0.1.1-4ubuntu1_amd64.deb"
  "main/x/xcb-util-wm/libxcb-icccm4_0.4.1-1.1build2_amd64.deb"
  "main/x/xcb-util-image/libxcb-image0_0.4.0-2_amd64.deb"
  "main/x/xcb-util-keysyms/libxcb-keysyms1_0.4.0-1build3_amd64.deb"
  "main/x/xcb-util-renderutil/libxcb-render-util0_0.3.9-1build3_amd64.deb"
  "main/x/xcb-util/libxcb-util1_0.4.0-1build2_amd64.deb"
)
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
RUNTIME_URL="https://github.com/AppImage/type2-runtime/releases/download/continuous/runtime-x86_64"

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }
fetch() { [ -s "$2" ] || { curl -fsSL --retry 3 -o "$2.part" "$1" && mv "$2.part" "$2"; } || die "download failed: $1"; }
host_python() { command -v python3 || die "python3 is needed to run the build helpers"; }

[ "$(uname -m)" = x86_64 ] || die "this script builds the x86_64 AppImage and must run on x86_64"
for t in curl objdump; do command -v "$t" >/dev/null || die "'$t' is not installed"; done
mkdir -p "$CACHE" "$DIST"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib" "$APPDIR/usr/app"

# 1 ── portable Python ───────────────────────────────────────────────────────
say "Portable Python $PY_VER"
if [ -z "${PYTHON_DIST:-}" ]; then
  command -v uv >/dev/null || die "install uv (https://docs.astral.sh/uv/) or set PYTHON_DIST"
  UV_PYTHON_INSTALL_DIR="$CACHE/python" uv python install "$PY_VER" >/dev/null
  PYTHON_DIST="$(ls -d "$CACHE"/python/cpython-"$PY_VER".*-linux-x86_64-gnu | sort -V | tail -1)"
fi
[ -x "$PYTHON_DIST/bin/python3" ] || die "no python3 in $PYTHON_DIST"
cp -a "$PYTHON_DIST" "$APPDIR/usr/python"
PY="$APPDIR/usr/python/bin/python3"
find "$APPDIR/usr/python" -name EXTERNALLY-MANAGED -delete

# 2 ── dependencies ──────────────────────────────────────────────────────────
say "Dependencies"
PIP_CACHE_DIR="$CACHE/pip" "$PY" -m pip install --quiet --disable-pip-version-check --no-warn-script-location \
  --no-compile --no-deps --prefer-binary -r "$PKG/requirements-appimage.txt"

# 3 ── the app ───────────────────────────────────────────────────────────────
say "App files"
for d in tgdrive desktop web; do cp -a "$SRC/$d" "$APPDIR/usr/app/"; done
cp "$SRC/run.py" "$APPDIR/usr/app/"
mkdir -p "$APPDIR/usr/app/packaging"
cp -a "$PKG/icons" "$APPDIR/usr/app/packaging/"
cp "$SRC/README.md" "$APPDIR/usr/app/" 2>/dev/null || true
find "$APPDIR/usr/app" -name __pycache__ -prune -exec rm -rf {} +

# Meaning-based search model (MIT licence, from the wordllama wheel)
say "Embedding model"
MODEL="$APPDIR/usr/app/models/wordllama"
mkdir -p "$MODEL" "$CACHE/wheels"
[ -n "$(ls "$CACHE"/wheels/wordllama-*.whl 2>/dev/null)" ] || \
  PIP_CACHE_DIR="$CACHE/pip" "$PY" -m pip download --quiet --disable-pip-version-check --no-deps \
    --only-binary=:all: -d "$CACHE/wheels" "wordllama==0.4.0.post1"
"$PY" - "$(ls "$CACHE"/wheels/wordllama-*.whl | head -1)" "$MODEL" <<'EOF'
import sys, zipfile, pathlib
whl, out = sys.argv[1], pathlib.Path(sys.argv[2])
with zipfile.ZipFile(whl) as z:
    for n in z.namelist():
        base = n.rsplit("/", 1)[-1]
        if base in ("l2_supercat_tokenizer_config.json", "l2_supercat_256.safetensors") or \
                (n.endswith(("LICENSE", "LICENSE.txt", "LICENSE.md")) and ".dist-info/" in n):
            (out / ("LICENSE" if "LICENSE" in base else base)).write_bytes(z.read(n))
EOF
[ -s "$MODEL/l2_supercat_256.safetensors" ] || die "model weights missing from the wordllama wheel"

# 4 ── bundled system libraries ──────────────────────────────────────────────
say "X11 helper libraries"
mkdir -p "$CACHE/debs"
for deb in "${XCB_DEBS[@]}"; do
  f="$CACHE/debs/$(basename "$deb")"
  fetch "$UBUNTU/$deb" "$f"
  tmp="$(mktemp -d)"
  if command -v dpkg-deb >/dev/null; then dpkg-deb -x "$f" "$tmp"
  else (cd "$tmp" && ar x "$f" && tar -xf data.tar.*) >/dev/null || die "unpacking $f needs dpkg-deb, or tar with zstd"
  fi
  cp -a "$tmp"/usr/lib/x86_64-linux-gnu/*.so.* "$APPDIR/usr/lib/"
  rm -rf "$tmp"
done

# 5 ── trim, precompile, verify ──────────────────────────────────────────────
say "Trimming"
"$(host_python)" "$PKG/appdir_tools.py" trim-python "$APPDIR"
"$(host_python)" "$PKG/appdir_tools.py" trim-qt "$APPDIR"
"$PY" -m compileall -q -j 0 -x 'tests|bindings' "$APPDIR/usr/python/lib" "$APPDIR/usr/app" >/dev/null || true
"$(host_python)" "$PKG/appdir_tools.py" check-glibc "$APPDIR" "$GLIBC_MAX"

# 6 ── AppImage metadata ─────────────────────────────────────────────────────
say "Launcher"
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
# TG Drive AppImage entry point.
HERE="$(dirname "$(readlink -f "$0")")"
# Remember the caller's environment so programs started from TG Drive (file manager,
# video player, browser) don't inherit the AppImage's library paths.
export LD_LIBRARY_PATH_ORIG="${LD_LIBRARY_PATH-}"
export PYTHONPATH_ORIG="${PYTHONPATH-}"
export PYTHONHOME_ORIG="${PYTHONHOME-}"
export QT_PLUGIN_PATH_ORIG="${QT_PLUGIN_PATH-}"
export LD_LIBRARY_PATH="$HERE/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
unset PYTHONHOME QT_PLUGIN_PATH QML2_IMPORT_PATH
export PYTHONPATH="$HERE/usr/app"
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1
export TGDRIVE_PACKAGED=1
[ -n "${APPIMAGE-}" ] && export TGDRIVE_LAUNCHER="$APPIMAGE"
if [ -z "${SSL_CERT_FILE-}" ]; then
  for f in /etc/ssl/certs/ca-certificates.crt /etc/pki/tls/certs/ca-bundle.crt /etc/ssl/ca-bundle.pem /etc/ssl/cert.pem; do
    [ -r "$f" ] && { export SSL_CERT_FILE="$f"; break; }
  done
fi
exec "$HERE/usr/python/bin/python3" -s -m desktop "$@"
EOF
chmod +x "$APPDIR/AppRun"

cat > "$APPDIR/tgdrive.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=TG Drive
GenericName=Telegram file manager
Comment=Browse, search, stream and organise every file in your Telegram
Exec=tgdrive %U
Icon=tgdrive
Terminal=false
Categories=Network;FileTransfer;
Keywords=telegram;files;drive;search;cloud;stream;
StartupWMClass=tgdrive
StartupNotify=true
X-AppImage-Version=$VERSION
EOF
cp "$PKG/icons/tgdrive-256.png" "$APPDIR/tgdrive.png"
ln -sf tgdrive.png "$APPDIR/.DirIcon"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp "$PKG/icons/tgdrive-256.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/tgdrive.png"

# 7 ── smoke test before packing ─────────────────────────────────────────────
say "Smoke test"
SMOKE="$(mktemp -d)"   # run from an empty folder so nothing from the source tree gets imported
(cd "$SMOKE" && TGDRIVE_DATA="$SMOKE/data" PYTHONPATH="$APPDIR/usr/app" LD_LIBRARY_PATH="$APPDIR/usr/lib" \
  "$PY" -s -c '
import sys
import tgdrive.api, tgdrive.search, tgdrive.semantic, tgdrive.streaming, run, desktop.app
from tgdrive import textproc, semantic
assert textproc.translit("संविधान"), "transliteration"
m = semantic._Model.get(); assert m is not None, semantic._Model.error
assert m.embed(["test series"]).shape == (1, 256)
import cryptg, numpy, rapidfuzz, snowballstemmer, segno, python_socks, hachoir, tokenizers, safetensors
from PyQt6 import QtCore, QtWidgets, QtWebEngineCore, QtWebEngineWidgets, QtWebChannel, QtMultimedia, QtSvg
assert tgdrive.api.__file__.startswith(sys.argv[1]), tgdrive.api.__file__
print("ok: python", sys.version.split()[0], "qt", QtCore.QT_VERSION_STR)
' "$APPDIR") || die "smoke test failed"
rm -rf "$SMOKE"
"$APPDIR/AppRun" --version

# 8 ── pack ──────────────────────────────────────────────────────────────────
say "Packing"
fetch "$APPIMAGETOOL_URL" "$CACHE/appimagetool"
fetch "$RUNTIME_URL" "$CACHE/runtime-x86_64"
chmod +x "$CACHE/appimagetool"
rm -f "$OUT"
ARCH=x86_64 "$CACHE/appimagetool" --appimage-extract-and-run --no-appstream \
  --runtime-file "$CACHE/runtime-x86_64" "$APPDIR" "$OUT" >"$BUILD/appimagetool.log" 2>&1 \
  || { tail -30 "$BUILD/appimagetool.log"; die "appimagetool failed"; }
chmod +x "$OUT"
say "Built $OUT ($(du -h "$OUT" | cut -f1))"

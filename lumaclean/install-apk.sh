#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APK="$ROOT_DIR/LumaClean.apk"

if ! command -v adb >/dev/null 2>&1; then
  echo "adb was not found. Install Android SDK Platform Tools or, on Ubuntu/Debian, run:"
  echo "  sudo apt update && sudo apt install -y adb"
  exit 1
fi

if [[ ! -f "$APK" ]]; then
  echo "LumaClean.apk was not found. Build it first with:"
  echo "  ./build-apk.sh"
  exit 1
fi

ADB_DEVICES="$(adb devices | awk 'NR>1 && $2=="device" {count++} END {print count+0}')"
if [[ "$ADB_DEVICES" -eq 0 ]]; then
  echo "No authorized Android device was detected."
  echo "Enable USB debugging, connect your phone, accept its authorization prompt, then run:"
  echo "  adb devices"
  exit 1
fi

if [[ "$ADB_DEVICES" -gt 1 ]]; then
  echo "More than one Android device is connected. Use adb manually and select a serial number:"
  echo "  adb devices"
  echo "  adb -s DEVICE_SERIAL install -r LumaClean.apk"
  exit 1
fi

echo "Installing LumaClean.apk…"
adb install -r "$APK"
echo "Done."

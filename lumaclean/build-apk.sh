#!/usr/bin/env bash
set -Eeuo pipefail

# LumaClean one-command APK builder for Linux.
# First run needs internet access so Gradle and Android dependencies can be downloaded.

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

APP_NAME="LumaClean"
APK_OUT="$ROOT_DIR/${APP_NAME}.apk"
GRADLE_VERSION="9.6.0"
GRADLE_DIR="$ROOT_DIR/.gradle-bootstrap/gradle-${GRADLE_VERSION}"
GRADLE_ZIP="$ROOT_DIR/.gradle-bootstrap/gradle-${GRADLE_VERSION}-bin.zip"
GRADLE_URL="https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip"

bold='\033[1m'
green='\033[0;32m'
yellow='\033[0;33m'
red='\033[0;31m'
reset='\033[0m'

info() { printf "%b%s%b\n" "$bold" "$*" "$reset"; }
ok()   { printf "%b✓ %s%b\n" "$green" "$*" "$reset"; }
warn() { printf "%b! %s%b\n" "$yellow" "$*" "$reset"; }
fail() { printf "%b✗ %s%b\n" "$red" "$*" "$reset" >&2; exit 1; }

command_exists() { command -v "$1" >/dev/null 2>&1; }

find_java() {
  if command_exists java; then
    return 0
  fi

  local candidates=(
    "/opt/android-studio/jbr/bin"
    "/usr/local/android-studio/jbr/bin"
    "$HOME/android-studio/jbr/bin"
    "$HOME/.local/share/JetBrains/Toolbox/apps/android-studio/bin/../jbr/bin"
  )

  local p
  for p in "${candidates[@]}"; do
    if [[ -x "$p/java" ]]; then
      export PATH="$p:$PATH"
      export JAVA_HOME="$(cd "$p/.." && pwd)"
      return 0
    fi
  done
  return 1
}

check_java() {
  find_java || fail "Java was not found. Install Android Studio or JDK 17+, then run this script again."

  local version major
  version="$(java -version 2>&1 | awk -F '"' '/version/ {print $2; exit}')"
  major="${version%%.*}"
  if [[ "$major" == "1" ]]; then
    major="$(printf '%s' "$version" | cut -d. -f2)"
  fi

  [[ "$major" =~ ^[0-9]+$ ]] || fail "Could not determine the installed Java version ($version)."
  (( major >= 17 )) || fail "Java 17 or newer is required. Found Java $version."
  ok "Java $version"
}

find_android_sdk() {
  local candidates=()
  [[ -n "${ANDROID_SDK_ROOT:-}" ]] && candidates+=("$ANDROID_SDK_ROOT")
  [[ -n "${ANDROID_HOME:-}" ]] && candidates+=("$ANDROID_HOME")
  candidates+=(
    "$HOME/Android/Sdk"
    "$HOME/Android/sdk"
    "/opt/android-sdk"
    "/usr/local/lib/android/sdk"
    "/usr/lib/android-sdk"
  )

  local sdk
  for sdk in "${candidates[@]}"; do
    if [[ -d "$sdk" ]] && { [[ -d "$sdk/platforms" ]] || [[ -d "$sdk/cmdline-tools" ]] || [[ -d "$sdk/platform-tools" ]]; }; then
      export ANDROID_SDK_ROOT="$sdk"
      export ANDROID_HOME="$sdk"
      return 0
    fi
  done
  return 1
}

check_android_sdk() {
  find_android_sdk || fail $'Android SDK was not found.\n\nEasiest fix:\n  1. Open Android Studio once.\n  2. Tools → SDK Manager.\n  3. Install Android SDK Platform 37.\n  4. Run ./build-apk.sh again.'
  ok "Android SDK: $ANDROID_SDK_ROOT"

  if [[ ! -d "$ANDROID_SDK_ROOT/platforms/android-37" ]]; then
    local sdkmanager=""
    for candidate in \
      "$ANDROID_SDK_ROOT/cmdline-tools/latest/bin/sdkmanager" \
      "$ANDROID_SDK_ROOT/cmdline-tools/bin/sdkmanager" \
      "$ANDROID_SDK_ROOT/tools/bin/sdkmanager"; do
      if [[ -x "$candidate" ]]; then
        sdkmanager="$candidate"
        break
      fi
    done

    if [[ -n "$sdkmanager" ]]; then
      warn "Android SDK Platform 37 is missing."
      printf "Install it now using sdkmanager? [Y/n] "
      read -r answer
      answer="${answer:-Y}"
      if [[ "$answer" =~ ^[Yy]$ ]]; then
        "$sdkmanager" "platforms;android-37" "platform-tools"
      else
        fail "Android SDK Platform 37 is required for this project."
      fi
    else
      fail $'Android SDK Platform 37 is not installed.\nOpen Android Studio → Tools → SDK Manager → install Android SDK Platform 37.'
    fi
  fi
  ok "Android SDK Platform 37"
}

download_file() {
  local url="$1" destination="$2"
  mkdir -p "$(dirname "$destination")"

  if command_exists curl; then
    curl --fail --location --progress-bar "$url" -o "$destination"
  elif command_exists wget; then
    wget --show-progress -O "$destination" "$url"
  else
    fail "Neither curl nor wget is installed. Install one of them and retry."
  fi
}

prepare_gradle() {
  if [[ -x "$ROOT_DIR/gradlew" && -f "$ROOT_DIR/gradle/wrapper/gradle-wrapper.jar" ]]; then
    GRADLE_CMD=("$ROOT_DIR/gradlew")
    ok "Using bundled Gradle wrapper"
    return 0
  fi

  if [[ ! -x "$GRADLE_DIR/bin/gradle" ]]; then
    info "Gradle $GRADLE_VERSION is needed (first build only)."
    if [[ ! -f "$GRADLE_ZIP" ]]; then
      info "Downloading Gradle $GRADLE_VERSION…"
      download_file "$GRADLE_URL" "$GRADLE_ZIP"
    fi

    command_exists unzip || fail "The 'unzip' command is required. Install it with your package manager and retry."
    info "Preparing Gradle…"
    rm -rf "$GRADLE_DIR"
    unzip -q -o "$GRADLE_ZIP" -d "$ROOT_DIR/.gradle-bootstrap"
  fi

  [[ -x "$GRADLE_DIR/bin/gradle" ]] || fail "Gradle setup did not complete correctly."
  GRADLE_CMD=("$GRADLE_DIR/bin/gradle")
  ok "Gradle $GRADLE_VERSION"
}

build_apk() {
  rm -f "$APK_OUT"
  info "Building LumaClean…"
  "${GRADLE_CMD[@]}" --no-daemon :app:assembleDebug

  local built="$ROOT_DIR/app/build/outputs/apk/debug/app-debug.apk"
  [[ -f "$built" ]] || fail "Gradle finished, but the expected APK was not found at app/build/outputs/apk/debug/app-debug.apk"

  cp -f "$built" "$APK_OUT"
  ok "APK created"
  printf "\n%b%s%b\n" "$green$bold" "$APK_OUT" "$reset"
  printf "\nInstall over USB with:\n  adb install -r %q\n" "$APK_OUT"
}

printf "\n%bLumaClean APK Builder%b\n\n" "$bold" "$reset"
check_java
check_android_sdk
prepare_gradle
build_apk

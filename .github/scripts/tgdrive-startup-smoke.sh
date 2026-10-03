#!/usr/bin/env bash
# TG Drive's real launcher entry on the booted emulator, from cold, then once more with a damaged
# preferences file in the data folder: each time TG Drive must stay on a screen of its own (the main
# screen, or its readable error screen), never close straight after the icon. Run by
# tgdrive-android-emulator.sh once the data folder is selected (working directory: tgdrive/android).
set -uo pipefail
mkdir -p out/shots
status=0
prefs='/sdcard/TG Drive/android/preferences.json'

resumed() { adb shell dumpsys activity activities | grep -E "ResumedActivity" | head -1 | tr -d '\r'; }

# The activity the home screen opens: whatever carries MAIN/LAUNCHER, as Android resolves it.
launcher=$(adb shell cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.LAUNCHER app.tgdrive | tr -d '\r' | tail -1)
echo "launcher entry: $launcher"
case "$launcher" in app.tgdrive/*) ;; *) echo "::error::TG Drive has no launcher entry ($launcher)"; exit 1;; esac

# Start TG Drive the way the launcher does, from a stopped app.
launch() {
  adb shell am force-stop app.tgdrive
  adb logcat -c || true
  adb shell am start -W -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -n "$launcher"
  sleep 12   # long enough for a startup crash to have happened
  adb logcat -d | grep -E "TGDrive|AndroidRuntime|ActivityTaskManager|app.tgdrive" > "out/$1-logcat.txt" || true
  adb exec-out screencap -p > "out/shots/$1.png" || true
  adb shell uiautomator dump /sdcard/window.xml > /dev/null 2>&1 && adb shell cat /sdcard/window.xml > "out/$1.xml" || true
}

launch 05-cold-launch
now=$(resumed); echo "after a cold launch: $now"
if echo "$now" | grep -q "app.tgdrive/.MainActivity" && [ -n "$(adb shell pidof app.tgdrive | tr -d '\r')" ]; then
  echo "cold launch stays on the main screen"
else
  echo "::error::A cold launch from the launcher didn't stay on TG Drive's main screen ($now)"; status=1
  tail -n 60 out/05-cold-launch-logcat.txt || true
fi

if adb shell "test -f '$prefs'"; then
  adb shell "cp '$prefs' '$prefs.smoke-backup' && echo 'not json {' > '$prefs'"
  launch 06-damaged-preferences
  now=$(resumed); echo "with damaged preferences: $now"
  if echo "$now" | grep -q "app.tgdrive/" && grep -qi "choose data folder" out/06-damaged-preferences.xml 2>/dev/null; then
    echo "damaged preferences show the error screen with a way out"
  else
    echo "::error::With damaged preferences TG Drive didn't show its error screen ($now)"; status=1
    tail -n 60 out/06-damaged-preferences-logcat.txt || true
  fi
  adb shell "mv '$prefs.smoke-backup' '$prefs'"
else
  echo "::error::No preferences file in the data folder after a launch ($prefs)"; status=1
fi
adb shell am force-stop app.tgdrive
exit $status

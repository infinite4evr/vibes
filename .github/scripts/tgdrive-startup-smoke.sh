#!/usr/bin/env bash
# TG Drive's real launcher entry on the booted emulator, from cold, then with what goes wrong on phones:
# a damaged preferences file, a data folder a cleaner app went through, and a launch whose main thread
# hangs. Each time TG Drive must end up on a screen of its own (the main screen, or its startup screen
# saying what happened), never close straight after the icon or leave the icon up with nothing said.
# Run by tgdrive-android-emulator.sh once the data folder is selected (working directory: tgdrive/android).
set -uo pipefail
mkdir -p out/shots
status=0
data='/sdcard/TG Drive'
prefs="$data/android/preferences.json"

resumed() { adb shell dumpsys activity activities | grep -E "ResumedActivity" | head -1 | tr -d '\r'; }
# The startup steps TG Drive keeps in its own storage (readable here because the staging build is debuggable).
trail() { adb shell run-as app.tgdrive cat files/logs/startup.log 2>/dev/null | tr -d '\r'; }

# The activity the home screen opens: whatever carries MAIN/LAUNCHER, as Android resolves it.
launcher=$(adb shell cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.LAUNCHER app.tgdrive | tr -d '\r' | tail -1)
echo "launcher entry: $launcher"
case "$launcher" in app.tgdrive/*) ;; *) echo "::error::TG Drive has no launcher entry ($launcher)"; exit 1;; esac

# Keep what the screen showed and what was logged, under out/ (named $1).
keep() {
  adb logcat -d | grep -E "TGDrive|AndroidRuntime|ActivityTaskManager|app.tgdrive" > "out/$1-logcat.txt" || true
  adb exec-out screencap -p > "out/shots/$1.png" || true
  adb shell uiautomator dump /sdcard/window.xml > /dev/null 2>&1 && adb shell cat /sdcard/window.xml > "out/$1.xml" || true
}

# Start TG Drive the way the launcher does, from a stopped app.
launch() {
  adb shell am force-stop app.tgdrive
  adb logcat -c || true
  adb shell am start -W -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -n "$launcher"
  sleep 12   # long enough for a startup crash to have happened
  keep "$1"
}

on_main_screen() { echo "$1" | grep -q "app.tgdrive/.MainActivity" && [ -n "$(adb shell pidof app.tgdrive | tr -d '\r')" ]; }

launch 05-cold-launch
now=$(resumed); echo "after a cold launch: $now"
if on_main_screen "$now"; then
  echo "cold launch stays on the main screen"
else
  echo "::error::A cold launch from the launcher didn't stay on TG Drive's main screen ($now)"; status=1
  tail -n 60 out/05-cold-launch-logcat.txt || true
fi

# A damaged preferences file in the data folder: set aside, and TG Drive opens with the phone's own settings
# (it used to stop at an error screen at every launch, until someone found and deleted the file).
if adb shell "test -f '$prefs'"; then
  adb shell "cp '$prefs' '$prefs.smoke-backup' && echo 'not json {' > '$prefs'"
  launch 06-damaged-preferences
  now=$(resumed); echo "with damaged preferences: $now"
  if on_main_screen "$now" && adb shell "test -f '$prefs.damaged'" && adb shell "grep -q '\"app\"' '$prefs'"; then
    echo "damaged preferences are set aside and TG Drive opens"
  else
    echo "::error::With damaged preferences TG Drive didn't open its main screen with a fresh preferences file ($now)"; status=1
    tail -n 60 out/06-damaged-preferences-logcat.txt || true
  fi
  adb shell "mv '$prefs.smoke-backup' '$prefs'; rm -f '$prefs.damaged'"
else
  echo "::error::No preferences file in the data folder after a launch ($prefs)"; status=1
fi

# What cleaner apps remove from shared storage: logs, caches, thumbnails, the .nomedia markers, state folders.
adb shell am force-stop app.tgdrive
adb shell "rm -rf '$data/android/logs' '$data/android/images' '$data/android/state' '$data/service/logs' '$data/service/accounts'/*/thumbs; rm -f '$data/android/.nomedia' '$data/service/.nomedia'"
launch 07-after-a-cleaner-app
now=$(resumed); echo "after a cleaner app: $now"
if on_main_screen "$now" && adb shell "grep -q 'process app' '$data/android/logs/app.log'" \
   && adb shell "test -f '$data/android/.nomedia' && test -f '$data/service/.nomedia'"; then
  echo "after a cleaner app TG Drive opens, logs again and puts its markers back"
else
  echo "::error::After a cleaner app removed TG Drive's logs and caches it didn't open, log, or restore .nomedia ($now)"; status=1
  adb shell "ls -la '$data' '$data/android' '$data/android/logs'" || true
  tail -n 60 out/07-after-a-cleaner-app-logcat.txt || true
fi

# A launch whose main thread never comes back (the test_hang extra, debuggable builds only): within about
# 20 s the startup screen replaces the icon, says where it was stuck, and TG Drive's own storage has the stack.
adb shell am force-stop app.tgdrive
adb logcat -c || true
adb shell am start -n "$launcher" --ez test_hang true > /dev/null
sleep 25
keep 08-hung-launch
now=$(resumed); echo "after a hung launch: $now"
trail > out/startup-trail-hung.txt
if echo "$now" | grep -q "DataLocationActivity" && grep -q "stopped responding" out/08-hung-launch.xml \
   && grep -q "Stuck:" out/startup-trail-hung.txt && grep -q "MainActivity.onCreate" out/startup-trail-hung.txt; then
  echo "a hung launch opens the startup screen with where it was stuck"
else
  echo "::error::A hung launch didn't open the startup screen with where it was stuck ($now)"; status=1
  tail -n 40 out/startup-trail-hung.txt || true
  tail -n 60 out/08-hung-launch-logcat.txt || true
fi

# The next launch doesn't walk into the same trouble blindly: the startup screen says how the last one ended.
launch 09-after-a-hung-launch
now=$(resumed); echo "the launch after a hung one: $now"
if echo "$now" | grep -q "DataLocationActivity" && grep -q "ended before its main screen opened" out/09-after-a-hung-launch.xml; then
  echo "the next launch explains how the last one ended"
else
  echo "::error::The launch after a hung one didn't explain how it ended ($now)"; status=1
fi

# Leave a clean app for the tests that follow.
adb shell am force-stop app.tgdrive
adb shell run-as app.tgdrive rm -f files/launch-pending || true
trail > out/startup-trail.txt
exit $status

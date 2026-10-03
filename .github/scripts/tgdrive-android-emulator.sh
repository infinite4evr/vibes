#!/usr/bin/env bash
# Runs TG Drive's instrumented tests on the booted emulator and collects screenshots and logs
# into out/ (working directory: tgdrive/android).
set -uo pipefail
mkdir -p out/shots
adb logcat -c || true
# A test run against an app that didn't install would only report what an old install does: stop.
adb install -r -g app/build/outputs/apk/staging/app-staging.apk || { echo "::error::Couldn't install the app APK"; exit 1; }
adb install -r -g app/build/outputs/apk/androidTest/staging/app-staging-androidTest.apk || { echo "::error::Couldn't install the test APK"; exit 1; }
status=0
# Run the instrumented tests in [class list] into out/[name].txt; they must finish with at least one
# test passed ("OK (n tests)"): an empty run or a crashed instrumentation is a failure too.
run_tests() {
  adb shell am instrument -w -r -e class "$1" app.tgdrive.test/androidx.test.runner.AndroidJUnitRunner | tee "out/$2.txt"
  if grep -q "FAILURES!!!\|INSTRUMENTATION_FAILED\|Process crashed" "out/$2.txt" || ! grep -Eq '^OK \([1-9][0-9]* tests?\)' "out/$2.txt"; then
    echo "::error::$2: the tests failed or didn't run"; status=1
  fi
}
# The data folder is shared storage (all-files access, granted here as a person would in Settings),
# chosen before anything else runs: TG Drive's service only starts from a selected folder.
grant_storage() { adb shell appops set --uid app.tgdrive MANAGE_EXTERNAL_STORAGE allow || true; }
grant_storage
run_tests app.tgdrive.DataFolderSetup data-folder
# The real launcher entry from cold, a damaged preferences file, a data folder a cleaner app went through, and
# a launch that hangs: TG Drive must show a screen of its own each time, never vanish or leave the icon up.
bash ../../.github/scripts/tgdrive-startup-smoke.sh || status=1
# Data folder lifecycle, durable upload handoff, recovery, startup cache and account switching.
adb shell am instrument -w -r -e class app.tgdrive.ReliabilityTest,app.tgdrive.RecoveryJourneys,app.tgdrive.PortableStorageTest app.tgdrive.test/androidx.test.runner.AndroidJUnitRunner | tee out/reliability.txt
grep -q "FAILURES!!!\|INSTRUMENTATION_FAILED\|Process crashed" out/reliability.txt && status=1
grep -Eq '^OK \([1-9][0-9]* tests?\)' out/reliability.txt || { echo "::error::reliability journeys failed or didn't run"; status=1; }
adb shell am instrument -w -r -e class app.tgdrive.EngineTest app.tgdrive.test/androidx.test.runner.AndroidJUnitRunner | tee out/engine-test.txt
grep -q "FAILURES!!!\|INSTRUMENTATION_FAILED\|Process crashed" out/engine-test.txt && status=1
adb shell am instrument -w -r -e class app.tgdrive.ScreenshotTour app.tgdrive.test/androidx.test.runner.AndroidJUnitRunner | tee out/tour.txt
grep -q "FAILURES!!!\|INSTRUMENTATION_FAILED\|Process crashed" out/tour.txt && status=1
# What people do, through the screens, each result checked against the service.
adb shell am instrument -w -r -e class app.tgdrive.Journeys app.tgdrive.test/androidx.test.runner.AndroidJUnitRunner | tee out/journeys.txt
grep -q "FAILURES!!!\|INSTRUMENTATION_FAILED\|Process crashed" out/journeys.txt && status=1
# The background sync with the app closed: starts the service by binding, syncs, and it stops after.
adb shell am instrument -w -r -e class app.tgdrive.BackgroundSyncTest app.tgdrive.test/androidx.test.runner.AndroidJUnitRunner | tee out/background-sync.txt
grep -q "FAILURES!!!\|INSTRUMENTATION_FAILED\|Process crashed" out/background-sync.txt && status=1
# The crash screen: its test, then a real crash of the running app, which must show the crash
# screen instead of the app vanishing (or closing again at every launch).
adb shell am instrument -w -r -e class app.tgdrive.CrashScreenTest app.tgdrive.test/androidx.test.runner.AndroidJUnitRunner | tee out/crash-screen-test.txt
grep -q "FAILURES!!!\|INSTRUMENTATION_FAILED\|Process crashed" out/crash-screen-test.txt && status=1
adb shell am start -W -n app.tgdrive/.MainActivity > /dev/null
sleep 8
ui_pid=$(adb shell pidof app.tgdrive | tr -d '\r' | awk '{print $1}')   # the interface's process, not :engine
echo "crashing the interface process ($ui_pid)"
adb shell am crash "$ui_pid" || true
sleep 6
adb shell dumpsys activity activities | grep -E "ResumedActivity" | tee out/after-crash.txt
adb exec-out screencap -p > out/shots/43-after-a-real-crash.png || true
if grep -q "CrashActivity" out/after-crash.txt; then echo "crash screen shown after a real crash"
else echo "::error::A crash of the app didn't show the crash screen"; status=1; fi
adb shell am force-stop app.tgdrive || true
adb pull /sdcard/Android/data/app.tgdrive/files/Pictures/tour/. out/shots/ || true
adb shell cat "'/sdcard/TG Drive/service/logs/tgdrive.log'" > out/service-demo.log 2>/dev/null || true
adb shell cat "'/sdcard/TG Drive/android/logs/app.log'" > out/app-demo.log 2>/dev/null || true
adb shell cat "'/sdcard/TG Drive/android/logs/engine.log'" > out/engine-demo.log 2>/dev/null || true
adb shell run-as app.tgdrive cat files/logs/startup.log > out/startup-trail-demo.txt 2>/dev/null || true

# A first start on a fresh install: the real sign-in screens against Telegram (made-up key).
adb shell pm clear app.tgdrive
adb shell pm grant app.tgdrive android.permission.POST_NOTIFICATIONS || true   # as if Allow was tapped
grant_storage   # SignInFlow picks a fresh data folder of its own
adb shell am instrument -w -r -e class app.tgdrive.SignInFlow app.tgdrive.test/androidx.test.runner.AndroidJUnitRunner | tee out/signin.txt
grep -q "FAILURES!!!\|INSTRUMENTATION_FAILED\|Process crashed" out/signin.txt && status=1
adb pull /sdcard/Android/data/app.tgdrive/files/Pictures/tour/. out/shots/ || true
signin=$(adb shell 'ls -d /sdcard/TGDrive-Test-signin-* 2>/dev/null' | tr -d '\r' | tail -1)
adb shell cat "'$signin/android/logs/engine-start.log'" > out/engine-start.log 2>/dev/null || true
echo "---- service start steps"; cat out/engine-start.log || true
adb shell cat "'$signin/service/logs/tgdrive.log'" > out/service.log 2>/dev/null || true
adb shell cat "'$signin/android/logs/app.log'" > out/app.log 2>/dev/null || true
# A big library (100 000 files, 1 700 chats) built on the phone: TG Drive must open to its main screen
# and stay responsive. The test keeps its timings, frame statistics and memory (taken while the app
# still runs) next to the screenshots.
adb shell am instrument -w -r -e class app.tgdrive.BigLibraryTest app.tgdrive.test/androidx.test.runner.AndroidJUnitRunner | tee out/big-library.txt
grep -q "FAILURES!!!\|INSTRUMENTATION_FAILED\|Process crashed" out/big-library.txt && status=1
adb pull /sdcard/Android/data/app.tgdrive/files/Pictures/tour/. out/shots/ || true
cat out/shots/big-library-timings.txt 2>/dev/null || true
grep -E "Janky frames|Total frames rendered|50th|90th|99th" out/shots/big-library-frames.txt | head -8 || true
grep -E "TOTAL PSS|TOTAL RSS" out/shots/big-library-memory-*.txt || true

adb logcat -d > out/logcat.txt || true
grep -E "TGDrive|Journeys|BigLibrary|python|chaquopy|AndroidRuntime|FATAL|ANR in app.tgdrive" out/logcat.txt | tail -n 300 > out/logcat-app.txt || true
echo "---- service log (tail)"; tail -n 60 out/service.log || true
echo "---- app logcat (tail)"; tail -n 120 out/logcat-app.txt || true
ls -la out/shots || true
exit $status

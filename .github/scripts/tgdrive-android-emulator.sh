#!/usr/bin/env bash
# Runs TG Drive's instrumented tests on the booted emulator and collects screenshots and logs
# into out/ (working directory: tgdrive/android).
set -uo pipefail
mkdir -p out/shots
adb logcat -c || true
adb install -r -g app/build/outputs/apk/staging/app-staging.apk
adb install -r -g app/build/outputs/apk/androidTest/staging/app-staging-androidTest.apk
status=0
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
adb shell run-as app.tgdrive cat files/tgdrive/logs/tgdrive.log > out/service-demo.log 2>/dev/null || true
adb shell run-as app.tgdrive cat files/logs/app.log > out/app-demo.log 2>/dev/null || true
adb shell run-as app.tgdrive cat files/logs/engine.log > out/engine-demo.log 2>/dev/null || true

# A first start on a fresh install: the real sign-in screens against Telegram (made-up key).
adb shell pm clear app.tgdrive
adb shell pm grant app.tgdrive android.permission.POST_NOTIFICATIONS || true   # as if Allow was tapped
adb shell am instrument -w -r -e class app.tgdrive.SignInFlow app.tgdrive.test/androidx.test.runner.AndroidJUnitRunner | tee out/signin.txt
grep -q "FAILURES!!!\|INSTRUMENTATION_FAILED\|Process crashed" out/signin.txt && status=1
adb pull /sdcard/Android/data/app.tgdrive/files/Pictures/tour/. out/shots/ || true
adb shell run-as app.tgdrive cat files/engine-start.log > out/engine-start.log 2>/dev/null || true
echo "---- service start steps"; cat out/engine-start.log || true
adb shell run-as app.tgdrive cat files/tgdrive/logs/tgdrive.log > out/service.log 2>/dev/null || true
adb shell run-as app.tgdrive cat files/logs/app.log > out/app.log 2>/dev/null || true
# A big library (100 000 files, 1 700 chats) built on the phone: TG Drive must open to its main screen
# and stay responsive. Frame statistics and memory are kept next to the timings.
adb shell dumpsys gfxinfo app.tgdrive reset > /dev/null 2>&1 || true
adb shell am instrument -w -r -e class app.tgdrive.BigLibraryTest app.tgdrive.test/androidx.test.runner.AndroidJUnitRunner | tee out/big-library.txt
grep -q "FAILURES!!!\|INSTRUMENTATION_FAILED\|Process crashed" out/big-library.txt && status=1
adb shell dumpsys gfxinfo app.tgdrive > out/big-library-frames.txt 2>&1 || true
adb shell dumpsys meminfo app.tgdrive > out/big-library-memory-app.txt 2>&1 || true
adb shell dumpsys meminfo app.tgdrive:engine > out/big-library-memory-engine.txt 2>&1 || true
adb pull /sdcard/Android/data/app.tgdrive/files/Pictures/tour/. out/shots/ || true
grep -E "Janky frames|Total frames|50th|90th|99th" out/big-library-frames.txt | head -8 || true
cat out/shots/big-library-timings.txt 2>/dev/null || true

adb logcat -d > out/logcat.txt || true
grep -E "TGDrive|Journeys|BigLibrary|python|chaquopy|AndroidRuntime|FATAL|ANR in app.tgdrive" out/logcat.txt | tail -n 300 > out/logcat-app.txt || true
echo "---- service log (tail)"; tail -n 60 out/service.log || true
echo "---- app logcat (tail)"; tail -n 120 out/logcat-app.txt || true
ls -la out/shots || true
exit $status

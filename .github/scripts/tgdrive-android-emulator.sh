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
adb pull /sdcard/Android/data/app.tgdrive/files/Pictures/tour out/shots/ || true
adb shell run-as app.tgdrive cat files/engine-start.log > out/engine-start.log 2>/dev/null || true
echo "---- service start steps"; cat out/engine-start.log || true
adb shell run-as app.tgdrive cat files/tgdrive/logs/tgdrive.log > out/service.log 2>/dev/null || true
adb logcat -d > out/logcat.txt || true
grep -E "TGDrive|python|chaquopy|AndroidRuntime|FATAL" out/logcat.txt | tail -n 300 > out/logcat-app.txt || true
echo "---- service log (tail)"; tail -n 60 out/service.log || true
echo "---- app logcat (tail)"; tail -n 120 out/logcat-app.txt || true
ls -la out/shots || true
exit $status

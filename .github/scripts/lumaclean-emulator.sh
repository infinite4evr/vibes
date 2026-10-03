#!/usr/bin/env bash
# LumaClean's instrumented tests on the booted emulator: the recycle bin and copies must never lose a
# file (cancelled, interrupted, storage missing), and the cleanup preview explains what it deletes.
# Working directory: lumaclean.
set -uo pipefail
mkdir -p out
adb logcat -c || true
adb install -r -g app/build/outputs/apk/debug/app-debug.apk || { echo "::error::Couldn't install the app APK"; exit 1; }
adb install -r -g app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk || { echo "::error::Couldn't install the test APK"; exit 1; }
adb shell appops set --uid app.lumaclean MANAGE_EXTERNAL_STORAGE allow || true   # as granted in Settings
status=0
adb shell am instrument -w -r -e class app.lumaclean.FileSafetyTest,app.lumaclean.CleanupPreviewTest \
  app.lumaclean.test/androidx.test.runner.AndroidJUnitRunner | tee out/file-safety.txt
grep -q "FAILURES!!!\|INSTRUMENTATION_FAILED\|Process crashed" out/file-safety.txt && status=1
# An empty or crashed run passes nothing: at least one test must have completed.
grep -Eq '^OK \([1-9][0-9]* tests?\)' out/file-safety.txt || { echo "::error::LumaClean's tests failed or didn't run"; status=1; }
adb logcat -d > out/logcat.txt || true
grep -E "lumaclean|AndroidRuntime|FATAL" out/logcat.txt | tail -n 200 || true
exit $status

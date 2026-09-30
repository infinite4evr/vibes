#!/usr/bin/env bash
# Print only what went wrong in a Gradle build log (compiler errors, failed tasks), last, so the
# end of the job log says it.
log="${1:-build.log}"
echo "================ compiler errors ================"
grep -E '^e: |^\[CXX|error:|ERROR:' "$log" | sed 's#file:///home/runner/work/vibes/vibes/tgdrive/android/##' | head -n 200
echo "================ what went wrong ================"
awk '/What went wrong:/{p=1} p&&/^\* Try:/{p=0} p' "$log" | head -n 60

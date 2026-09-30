#!/usr/bin/env bash
# Print only what went wrong in a Gradle build log, last, so the end of the job log says it:
# the number of errors per file, then the first few errors of each file.
log="${1:-build.log}"
grep -E '^e: ' "$log" | sed 's#file:///home/runner/work/vibes/vibes/tgdrive/android/##' > /tmp/errs.txt || true
echo "================ errors per file ================"
sed -E 's/^e: ([^:]+):.*/\1/' /tmp/errs.txt | sort | uniq -c | sort -rn | head -n 40
echo "================ first errors of each file ================"
awk -F: '{f=$1} count[f]++ < 6' /tmp/errs.txt | head -n 150
grep -E '^\[CXX|error: ' "$log" | head -n 30
echo "================ what went wrong ================"
awk '/What went wrong:/{p=1} p&&/^\* Try:/{p=0} p' "$log" | head -n 40

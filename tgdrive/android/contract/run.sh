#!/usr/bin/env bash
# Starts TG Drive's service (sample data, as the phone starts it) and runs the Android app's data
# layer against it; then checks that sign-in reaches Telegram. Run from tgdrive/android/contract
# after `gradle installDist`, with the Python that has the app's packages.
set -uo pipefail
PY=${PY:-python}
work=$(mktemp -d)
$PY boot.py demo "$work/demo" > "$work/demo.out" 2> "$work/demo.err" &
pid=$!
for i in $(seq 1 120); do tail -1 "$work/demo.out" 2>/dev/null | grep -q '"port"' && break; sleep 0.5; done
info=$(tail -1 "$work/demo.out")
[ -n "$info" ] || { echo "the service didn't start"; cat "$work/demo.err"; exit 1; }
port=$(echo "$info" | $PY -c "import sys,json;print(json.load(sys.stdin)['port'])")
media=$(echo "$info" | $PY -c "import sys,json;print(json.load(sys.stdin)['media_port'])")
build/install/tgdrive-contract/bin/tgdrive-contract "$port" "$media" contract-token contract-media demo
status=$?
kill $pid 2>/dev/null
if [ $status -ne 0 ]; then echo "---- service log"; tail -n 80 "$work/demo/logs/tgdrive.log"; fi

$PY boot.py real "$work/real" > "$work/real.out" 2> "$work/real.err" &
pid=$!
for i in $(seq 1 120); do tail -1 "$work/real.out" 2>/dev/null | grep -q '"port"' && break; sleep 0.5; done
rport=$(tail -1 "$work/real.out" | $PY -c "import sys,json;print(json.load(sys.stdin)['port'])")
$PY telegram_check.py "$rport" || status=1
kill $pid 2>/dev/null
exit $status

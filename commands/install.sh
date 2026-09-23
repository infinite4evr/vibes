#!/usr/bin/env bash
# One-time setup: make every command executable and install Node deps.
# (Making commands global is done by sourcing env.sh - see README.)
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

for dir in "$ROOT"/*/; do
  name="$(basename "$dir")"
  entry="$dir$name"
  [ -f "$entry" ] || { echo "skip  $name (no ./$name entry file)"; continue; }
  chmod +x "$entry"
  [ -f "$dir/package.json" ] && (cd "$dir" && npm install --silent)
  echo "ok    $name"
done

echo
echo "Add this line to ~/.bashrc (or ~/.zshrc), then open a new terminal:"
echo "  source \"$ROOT/env.sh\""

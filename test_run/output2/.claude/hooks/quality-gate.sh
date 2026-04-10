#!/usr/bin/env bash
set -euo pipefail

# Read HookInput JSON from stdin and extract the working directory.
CWD=$(python3 -c "import sys,json; print(json.load(sys.stdin)['cwd'])")

REQ_FILE="$CWD/REQUIREMENTS.md"

if [ ! -f "$REQ_FILE" ]; then
    # No requirements file -- nothing to enforce.
    exit 0
fi

DONE=$(grep -c '\[x\]' "$REQ_FILE" || true)
TODO=$(grep -c '\[ \]' "$REQ_FILE" || true)
TOTAL=$((DONE + TODO))

if [ "$TOTAL" -eq 0 ]; then
    # No checkbox items found -- pass through.
    exit 0
fi

# Calculate completion ratio (integer math: multiply first).
RATIO_OK=$(python3 -c "print(1 if $DONE / $TOTAL >= 0.8 else 0)")

if [ "$RATIO_OK" -eq 0 ]; then
    echo "Quality gate FAILED: only $DONE/$TOTAL requirements completed ($(python3 -c "print(f'{$DONE/$TOTAL:.0%}')")) -- need at least 80%." >&2
    exit 2
fi

exit 0

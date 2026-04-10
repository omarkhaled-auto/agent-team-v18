#!/usr/bin/env bash
set -euo pipefail

# Read HookInput JSON from stdin.
INPUT=$(cat)

TOOL_NAME=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_name','unknown'))")
FILE_PATH=$(echo "$INPUT" | python3 -c "import sys,json; ti=json.load(sys.stdin).get('tool_input',{}); print(ti.get('file_path', ti.get('path','unknown')))")
CWD=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('cwd','.'))")

LOG_DIR="$CWD/.claude/hooks"
mkdir -p "$LOG_DIR"

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
echo "$TIMESTAMP | tool=$TOOL_NAME | file=$FILE_PATH" >> "$LOG_DIR/file-changes.log"

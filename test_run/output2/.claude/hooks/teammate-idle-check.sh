#!/usr/bin/env bash
set -euo pipefail

# Ask Claude to inspect the task list for pending unblocked tasks.
result=$(claude -p "Check TaskList for any pending tasks that are NOT blocked. Reply ONLY with 'PENDING' if unblocked pending tasks exist, or 'DONE' if all tasks are completed or blocked." 2>/dev/null || true)

if echo "$result" | grep -qi "PENDING"; then
    echo "There are still pending unblocked tasks. Resuming work." >&2
    exit 2
fi

# All tasks are done or blocked -- allow idle transition.
exit 0

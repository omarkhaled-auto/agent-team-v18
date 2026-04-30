"""Stage 1A / 1B closeout-smoke prep templates.

Phase 5 closeout-smoke Stage 1A (run-dir
``v18 test runs/phase-5-closeout-stage-1-1a-strict-on-smoke-20260430-103941``)
surfaced two operational defects in the operator-supplied smoke harness:

1. ``watcher.log`` written under the run-dir → Wave B's scope detector
   classified the file as "wave-written out-of-scope", contaminating the
   §M.M11 wave-fail-rate calibration baseline (all M1 + M2 Wave Bs
   spurious-failed via ``SCOPE-VIOLATION-001`` on a file the watcher
   itself wrote).
2. ``launcher.sh`` recorded ``$$`` (the bash launcher's PID) into
   ``AGENT_TEAM_PID.txt`` — when the watcher SIGTERM'd that PID the bash
   process died but the agent-team-v15 Python child reparented to PID 1
   and continued running orphaned for ~10 minutes (~$5+ of additional
   Codex spend, plus ``EXIT_CODE.txt`` never written by the bash-after-
   exit handler that no longer existed).

This module renders signal-safe templates that close both defects:

* :func:`render_watcher_script` — log path lives at
  ``/tmp/watcher-<run_id>.log``, never under the run-dir; milestone
  targets resolved dynamically from ``MASTER_PLAN.json`` so the same
  template handles both unsplit (``milestone-1``) and Phase-5.9-split
  (``milestone-1-a`` / ``milestone-1-b``) shapes without a hard-coded
  ID list.
* :func:`render_launcher_script` — runs agent-team-v15 as a child
  process (background ``&`` + ``wait``) so the launcher's bash process
  survives long enough to trap ``TERM`` / ``INT`` / ``HUP``, propagate
  the signal to the child's process group via ``kill -TERM -<pgid>``
  (preserving the orphan-protect pattern), wait for the child to flush
  its own state, capture the real exit code, and write
  ``EXIT_CODE.txt``. The actual Python child PID is recorded into
  ``AGENT_TEAM_PID.txt`` so external tooling (the watcher itself, an
  operator pkill, etc.) can target the right process.

Both templates ship strings; callers (operators / scripts / tests)
write them to disk under the run-dir before launching.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

__all__ = (
    "render_watcher_script",
    "render_launcher_script",
    "resolve_watcher_milestone_targets",
    "WATCHER_LOG_DIR_DEFAULT",
)


# Keeping the watcher log under ``/tmp/`` (or any operator-overridden
# directory OUTSIDE the run-dir) is the contract that closes the Stage
# 1A scope-violation contamination. The default matches the path used
# in the Stage 1A findings memo's recommended template.
WATCHER_LOG_DIR_DEFAULT = "/tmp"


def resolve_watcher_milestone_targets(
    master_plan_path: str | Path,
    *,
    bound_to_first_two_logical_milestones: bool = True,
) -> list[str]:
    """Resolve the milestone IDs the watcher should wait on.

    Reads ``MASTER_PLAN.json`` and returns the ordered list of milestone
    IDs covering the first two logical milestones (the operator-chosen
    "kill-after-M1+M2" cost-bound). Split-aware:

    * MASTER_PLAN has ``milestone-1-a``, ``milestone-1-b``, ``milestone-2``,
      … → returns ``["milestone-1-a", "milestone-1-b", "milestone-2"]``.
    * MASTER_PLAN has ``milestone-1``, ``milestone-2``, … → returns
      ``["milestone-1", "milestone-2"]``.
    * MASTER_PLAN missing or unparseable → returns the safe default
      ``["milestone-1", "milestone-2"]`` (so the watcher boots even if
      MASTER_PLAN hasn't been written yet at watcher launch — the
      runtime watcher re-reads on every poll loop and converges).

    When *bound_to_first_two_logical_milestones* is ``False``, returns
    ALL milestone IDs in plan order (used by tests / future synthetic
    smokes that want to cover every milestone).
    """

    fallback = ["milestone-1", "milestone-2"]
    try:
        data = json.loads(Path(master_plan_path).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return fallback

    raw = data.get("milestones") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return fallback

    ordered_ids: list[str] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        mid = str(entry.get("id", "") or "").strip()
        if mid:
            ordered_ids.append(mid)

    if not ordered_ids:
        return fallback

    if not bound_to_first_two_logical_milestones:
        return ordered_ids

    # Split detection: a logical milestone is the family of IDs sharing
    # the leading numeric segment (``milestone-<N>`` or ``milestone-<N>-<half>``).
    halves_by_logical: dict[str, list[str]] = {}
    logical_order: list[str] = []
    half_re = re.compile(r"^(milestone-\d+)(?:-[a-z])?$")
    for mid in ordered_ids:
        match = half_re.match(mid)
        if not match:
            # Non-canonical ID — keep it as its own logical key (defensive).
            key = mid
        else:
            key = match.group(1)
        if key not in halves_by_logical:
            halves_by_logical[key] = []
            logical_order.append(key)
        halves_by_logical[key].append(mid)

    targets: list[str] = []
    for logical_key in logical_order[:2]:
        targets.extend(halves_by_logical[logical_key])
    return targets or fallback


def render_watcher_script(
    *,
    run_dir: str | Path,
    master_plan_path: str | Path | None = None,
    log_dir: str = WATCHER_LOG_DIR_DEFAULT,
    poll_seconds: int = 30,
    target_resolver_python: str = "python3",
) -> str:
    """Render the Stage 1 watcher shell script.

    The watcher polls STATE.json every *poll_seconds*; when every
    target milestone (resolved at runtime from MASTER_PLAN.json) is in
    a terminal status (COMPLETE / FAILED / DEGRADED), it sends SIGTERM
    to the AGENT_TEAM_PID — which the launcher template traps and
    forwards to the agent-team-v15 child process group. Logs go to
    ``<log_dir>/watcher-<run_id>.log`` so they CANNOT contaminate the
    run-dir's wave-scope detector (the Stage 1A defect).

    The runtime target-resolution lives inline in the script (Python
    one-liner via *target_resolver_python*) so a mid-run MASTER_PLAN
    update (planner emits a different shape than the operator
    expected) gets picked up on the next poll iteration.
    """

    run_dir_str = str(Path(run_dir))
    master_plan_str = (
        str(master_plan_path)
        if master_plan_path is not None
        else f"{run_dir_str}/.agent-team/MASTER_PLAN.json"
    )
    return f"""#!/usr/bin/env bash
# Phase 5 closeout-smoke Stage 1 watcher (signal-safe + scope-safe).
# Logs to ${{LOG_FILE}} OUTSIDE the run-dir so the wave-scope detector
# cannot mis-attribute the watcher's writes to a Wave-B scope violation.
# Target milestones resolved dynamically from MASTER_PLAN.json on every
# poll so the Phase 5.9 split shape is auto-detected.
set -u

RUN_DIR={run_dir_str!r}
MASTER_PLAN={master_plan_str!r}
STATE_FILE="${{RUN_DIR}}/.agent-team/STATE.json"
PID_FILE="${{RUN_DIR}}/AGENT_TEAM_PID.txt"
LOG_DIR={log_dir!r}
RUN_ID="$(basename "${{RUN_DIR}}")"
LOG_FILE="${{LOG_DIR}}/watcher-${{RUN_ID}}.log"
POLL_SECONDS={int(poll_seconds)}
PY={target_resolver_python!r}

mkdir -p "${{LOG_DIR}}"
log() {{ echo "[watcher $(date -Is)] $*" >> "${{LOG_FILE}}"; }}

log "Stage 1 watcher started; RUN_DIR=${{RUN_DIR}} POLL=${{POLL_SECONDS}}s"
log "Watcher log: ${{LOG_FILE}} (intentionally outside RUN_DIR — Stage 1A defect-fix #1)"

# Resolve target milestone IDs dynamically. Returns space-separated IDs
# on stdout. Falls back to ``milestone-1 milestone-2`` if MASTER_PLAN
# is missing / malformed.
resolve_targets() {{
    "${{PY}}" - "${{MASTER_PLAN}}" <<'PYEOF'
import json, re, sys
fallback = ["milestone-1", "milestone-2"]
path = sys.argv[1]
try:
    data = json.load(open(path, encoding="utf-8"))
except Exception:
    print(" ".join(fallback))
    sys.exit(0)
raw = data.get("milestones") if isinstance(data, dict) else None
if not isinstance(raw, list):
    print(" ".join(fallback))
    sys.exit(0)
ids = []
for entry in raw:
    if isinstance(entry, dict):
        mid = str(entry.get("id", "") or "").strip()
        if mid:
            ids.append(mid)
if not ids:
    print(" ".join(fallback))
    sys.exit(0)
half_re = re.compile(r"^(milestone-\\d+)(?:-[a-z])?$")
groups = []
seen = {{}}
for mid in ids:
    m = half_re.match(mid)
    key = m.group(1) if m else mid
    if key not in seen:
        seen[key] = []
        groups.append(key)
    seen[key].append(mid)
out = []
for g in groups[:2]:
    out.extend(seen[g])
print(" ".join(out or fallback))
PYEOF
}}

terminal() {{
    local status="$1"
    case "${{status}}" in
        COMPLETE|FAILED|DEGRADED) return 0 ;;
        *) return 1 ;;
    esac
}}

while true; do
    if [[ ! -f "${{STATE_FILE}}" ]]; then
        log "STATE.json not yet written; sleeping ${{POLL_SECONDS}}s"
        sleep "${{POLL_SECONDS}}"
        continue
    fi
    TARGETS=$(resolve_targets)
    log "watching milestones: ${{TARGETS}}"
    ALL_TERMINAL=1
    for MID in ${{TARGETS}}; do
        STATUS=$("${{PY}}" -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('milestone_progress', {{}}).get(sys.argv[2], {{}}).get('status', 'PENDING'))" "${{STATE_FILE}}" "${{MID}}" 2>/dev/null || echo PENDING)
        log "  ${{MID}} → ${{STATUS}}"
        if ! terminal "${{STATUS}}"; then
            ALL_TERMINAL=0
            break
        fi
    done
    if [[ "${{ALL_TERMINAL}}" -eq 1 ]]; then
        if [[ ! -s "${{PID_FILE}}" ]]; then
            log "All targets terminal but PID_FILE empty; cannot signal."
            sleep "${{POLL_SECONDS}}"
            continue
        fi
        AGENT_TEAM_PID=$(cat "${{PID_FILE}}")
        # Closeout-remediation reviewer blocker #1 — signal the child's
        # PROCESS GROUP, not the bare child PID. Pre-fix used the
        # positive-PID form, which only delivered SIGTERM to the
        # orchestrator and left every grandchild (Codex CLI, docker
        # compose, npm install, prisma generate, …) reparented to
        # init and still running. The launcher's ``set -m`` makes the
        # child its own PG leader (PGID == AGENT_TEAM_PID), so
        # ``-${{AGENT_TEAM_PID}}`` (negative) targets the entire
        # subtree — orchestrator + every subprocess it owns — in one
        # signal. The launcher's ``wait`` then returns and EXIT_CODE.txt
        # gets written.
        log "All targets terminal — sending SIGTERM to PGID=${{AGENT_TEAM_PID}} (process group)"
        kill -TERM "-${{AGENT_TEAM_PID}}" 2>>"${{LOG_FILE}}" || \\
            log "kill -PG failed (process group already exited?)"
        log "Watcher exiting (signal sent)."
        exit 0
    fi
    sleep "${{POLL_SECONDS}}"
done
"""


def render_launcher_script(
    *,
    run_dir: str | Path,
    repo_root: str | Path,
    venv_activate: str | Path,
    prd_filename: str = "PRD.md",
    config_filename: str = "config.yaml",
    depth: str = "exhaustive",
    milestone_cost_cap_usd: int = 20,
    cumulative_wedge_cap: int = 10,
    stage_label: str = "Stage 1",
    extra_cli_args: Iterable[str] | None = None,
) -> str:
    """Render the Stage 1 launcher shell script.

    Signal-safe pattern:

    1. ``agent-team-v15 … &`` — spawn as a background child so the
       launcher's bash process survives the dispatch and can trap
       signals.
    2. ``echo $! > AGENT_TEAM_PID.txt`` — record the actual Python
       child PID (was ``$$`` pre-remediation, which recorded bash's
       own PID and orphaned the Python child on SIGTERM).
    3. ``trap`` ``TERM`` / ``INT`` / ``HUP`` — forward the signal to
       the child's process group via ``kill -TERM -<pgid>`` (negative
       PID = process-group target). This propagates to any subprocess
       the dispatch spawned (Codex CLI, docker compose, npm install,
       etc.) so nothing reparents to PID 1.
    4. ``wait "$CHILD"`` — block until the child exits OR the trap
       wakes the wait. Either way, ``$?`` from ``wait`` is the child's
       exit code (or ``128 + signal`` when the wait itself is
       interrupted).
    5. Write ``EXIT_CODE.txt`` regardless of how we exited so reviewers
       always see the terminal disposition.

    The trap forwards to the *process group*, not the bare child PID,
    which closes the Stage 1A defect: pre-remediation, the launcher's
    bash exited on SIGTERM and the orphan Python continued to drive
    Codex turns for ~10 minutes.
    """

    run_dir_str = str(Path(run_dir))
    repo_root_str = str(Path(repo_root))
    venv_activate_str = str(Path(venv_activate))
    extras = list(extra_cli_args or ())
    extras_block = "\n".join(f"  {arg} \\" for arg in extras) if extras else ""
    extras_section = f"  \\\n{extras_block}" if extras else ""

    return f"""#!/usr/bin/env bash
# Phase 5 closeout-smoke {stage_label} launcher (signal-safe).
# Pre-remediation defect (closed here): launcher used to ``echo $$ >``
# AGENT_TEAM_PID.txt, recording bash's own PID. SIGTERM'd that PID and
# the Python child reparented to init, ran orphaned, ate Codex spend.
# Post-remediation: spawn as background child + record actual PID +
# trap signals + forward to process group + wait + write EXIT_CODE.
#
# ``set -m`` (monitor mode / job control) is REQUIRED — without it,
# bash places every backgrounded job in the launcher's own process
# group, so ``kill -TERM -<child>`` targets the wrong PG. With ``-m``,
# each backgrounded child is its own process group leader (PGID ==
# child PID), which is the §M.M4 contract: signal the child + every
# subprocess it owns (Codex CLI, docker compose, npm install, …) in
# one shot.
set -u
set -m

RUN_DIR={run_dir_str!r}
REPO_ROOT={repo_root_str!r}
PRD_PATH="${{RUN_DIR}}/{prd_filename}"
CONFIG_PATH="${{RUN_DIR}}/{config_filename}"
PID_FILE="${{RUN_DIR}}/AGENT_TEAM_PID.txt"
EXIT_FILE="${{RUN_DIR}}/EXIT_CODE.txt"
BUILD_LOG="${{RUN_DIR}}/BUILD_LOG.txt"

cd "${{RUN_DIR}}"
echo "[launcher] RUN_DIR=${{RUN_DIR}}"
echo "[launcher] $(date -Is)"
echo "[launcher] launcher_pid=$$"

# Activate the agent-team-v15 venv (Python entry point). Path passed
# in as a template parameter so the operator can target the right
# environment without editing this file.
# shellcheck disable=SC1090
source {venv_activate_str!r}
which agent-team-v15
agent-team-v15 --version
git -C "${{REPO_ROOT}}" rev-parse HEAD > "${{RUN_DIR}}/HEAD_SHA.txt"
echo "[launcher] starting agent-team-v15 — {stage_label} …"

# With ``set -m`` enabled above, each backgrounded job becomes its
# own process group leader (PGID equals the child's PID). That is
# the §M.M4 contract for ``kill -TERM -<pgid>``: targeting the child's
# entire subprocess tree without escaping into the launcher's own
# process group or the operator's parent shell. Job control is the
# portable, in-bash way to set up that PG split — no external
# session-detacher tool needed.

# Spawn the child as a background process so the launcher bash
# survives. ``$!`` after the spawn is the actual Python child PID
# AND the new process group's PGID.
agent-team-v15 \\
  --prd "${{PRD_PATH}}" \\
  --config "${{CONFIG_PATH}}" \\
  --depth "{depth}" \\
  --cwd "${{RUN_DIR}}" \\
  --milestone-cost-cap-usd "{int(milestone_cost_cap_usd)}" \\
  --cumulative-wedge-cap "{int(cumulative_wedge_cap)}"{extras_section} \\
  >> "${{BUILD_LOG}}" 2>&1 &
CHILD=$!
echo "${{CHILD}}" > "${{PID_FILE}}"
echo "[launcher] child PID=${{CHILD}} recorded to ${{PID_FILE}}"

# Forward TERM / INT / HUP to the child's process group so the
# orchestrator + every subprocess it owns (Codex CLI, docker,
# npm, etc.) gets the signal. Negative PID = process-group target.
# Under ``set -m``, the backgrounded child is its own PG leader
# (PGID == CHILD), so ``kill -<sig> -CHILD`` reaches the whole tree.
forward_signal() {{
    local sig="$1"
    echo "[launcher] received ${{sig}}; forwarding to PGID=${{CHILD}}" \\
        | tee -a "${{BUILD_LOG}}"
    if kill -0 "-${{CHILD}}" 2>/dev/null; then
        kill -"${{sig}}" "-${{CHILD}}" 2>/dev/null || true
    else
        # PG kill failed (e.g. monitor mode disabled in some forked
        # context) — fall back to a direct PID kill so we still
        # reach the orchestrator process. Subprocesses may then
        # reparent, but the orchestrator's own SIGTERM handler
        # writes its own state-flush before exit.
        kill -"${{sig}}" "${{CHILD}}" 2>/dev/null || true
    fi
}}
trap 'forward_signal TERM' TERM
trap 'forward_signal INT' INT
trap 'forward_signal HUP' HUP

# Wait for the child to exit. ``wait`` is interrupted by traps, so
# loop until the child is genuinely gone. ``$?`` after ``wait``
# carries the child's exit code (or 128+sig when wait was woken).
EXIT_CODE=0
while kill -0 "${{CHILD}}" 2>/dev/null; do
    if wait "${{CHILD}}"; then
        EXIT_CODE=0
    else
        EXIT_CODE=$?
    fi
done
echo "${{EXIT_CODE}}" > "${{EXIT_FILE}}"
echo "[launcher] exited with EXIT_CODE=${{EXIT_CODE}} at $(date -Is)" \\
    >> "${{BUILD_LOG}}"
exit "${{EXIT_CODE}}"
"""

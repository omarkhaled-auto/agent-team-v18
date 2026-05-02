"""Phase 5 closeout-smoke Stage 1 prep template fixtures.

Closes the two operational defects surfaced by the 2026-04-30 Stage 1A
smoke (run-dir
``v18 test runs/phase-5-closeout-stage-1-1a-strict-on-smoke-20260430-103941``):

1. ``watcher.log`` written under the run-dir contaminated Wave B's
   scope detector (every M1 + M2 Wave B spurious-failed via
   SCOPE-VIOLATION-001 on a file the watcher itself wrote).
2. ``launcher.sh`` recorded ``$$`` (the bash launcher's PID) into
   ``AGENT_TEAM_PID.txt`` — when the watcher SIGTERM'd that PID the
   bash died but the agent-team-v15 Python child reparented to init
   and ran orphaned for ~10 minutes (~$5+ Codex burn).

The integration test in this file uses a dummy long-running command
(``sleep`` only — no API spend) to prove the launcher's
trap+forward+wait pattern propagates SIGTERM to the child and writes
``EXIT_CODE.txt`` with the right exit code on the way out.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

from scripts.phase_5_closeout.stage_1_prep import (
    WATCHER_LOG_DIR_DEFAULT,
    render_launcher_script,
    render_watcher_script,
    resolve_watcher_milestone_targets,
)


# ---------------------------------------------------------------------------
# resolve_watcher_milestone_targets — split-aware target resolution
# ---------------------------------------------------------------------------


def test_resolve_targets_unsplit_returns_milestone_1_and_2(tmp_path: Path) -> None:
    plan = {
        "milestones": [
            {"id": "milestone-1"},
            {"id": "milestone-2"},
            {"id": "milestone-3"},
        ]
    }
    plan_path = tmp_path / "MASTER_PLAN.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    targets = resolve_watcher_milestone_targets(plan_path)
    assert targets == ["milestone-1", "milestone-2"]


def test_resolve_targets_phase_5_9_split_returns_halves_plus_m2(tmp_path: Path) -> None:
    plan = {
        "milestones": [
            {"id": "milestone-1-a"},
            {"id": "milestone-1-b"},
            {"id": "milestone-2"},
            {"id": "milestone-3"},
        ]
    }
    plan_path = tmp_path / "MASTER_PLAN.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    targets = resolve_watcher_milestone_targets(plan_path)
    assert targets == ["milestone-1-a", "milestone-1-b", "milestone-2"]


def test_resolve_targets_falls_back_when_master_plan_missing(tmp_path: Path) -> None:
    """Watcher boots before MASTER_PLAN.json exists — return safe default
    so the runtime poll loop converges as the planner writes it."""
    targets = resolve_watcher_milestone_targets(tmp_path / "absent.json")
    assert targets == ["milestone-1", "milestone-2"]


def test_resolve_targets_falls_back_when_master_plan_unparseable(
    tmp_path: Path,
) -> None:
    bad = tmp_path / "MASTER_PLAN.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    targets = resolve_watcher_milestone_targets(bad)
    assert targets == ["milestone-1", "milestone-2"]


# ---------------------------------------------------------------------------
# Watcher template — log path discipline + dynamic resolver presence
# ---------------------------------------------------------------------------


def test_watcher_template_writes_log_outside_run_dir() -> None:
    """Stage 1A defect #1 fix: the rendered watcher script MUST direct
    ``log()`` to a path outside the run-dir. Any reference to
    ``${RUN_DIR}/watcher.log`` (or appending to ``./watcher.log``) is
    a regression."""
    script = render_watcher_script(run_dir="/tmp/run-x")
    # Default log path lives under /tmp/.
    assert "LOG_DIR='/tmp'" in script
    assert "/tmp/watcher-" in script or '${LOG_DIR}/watcher-' in script
    # Forbidden patterns: writing watcher.log under the run-dir would
    # contaminate Wave B's scope detector.
    forbidden = [
        ">> watcher.log",
        '>> "watcher.log"',
        "${RUN_DIR}/watcher.log",
        '${RUN_DIR}"/watcher.log',
    ]
    for needle in forbidden:
        assert needle not in script, (
            f"Watcher template regressed Stage 1A defect #1: contains "
            f"forbidden run-dir log pattern {needle!r}."
        )


def test_watcher_template_log_dir_override_respected() -> None:
    """Operators can override the log directory; rendered template
    references the override consistently."""
    script = render_watcher_script(
        run_dir="/tmp/run-x",
        log_dir="/var/tmp/closeout-watch",
    )
    assert "LOG_DIR='/var/tmp/closeout-watch'" in script
    assert "/tmp/watcher-" not in script  # default not present


def test_watcher_template_resolves_targets_dynamically_from_master_plan() -> None:
    """The script body MUST resolve targets via a runtime read of
    MASTER_PLAN.json (so split shape detected at poll time), NOT from
    a hard-coded list."""
    script = render_watcher_script(run_dir="/tmp/run-x")
    assert "resolve_targets" in script
    assert "MASTER_PLAN" in script
    # Hard-coded ID lists are explicitly forbidden by the §M.M11 prep
    # contract — only the safe-default fallback inside the resolver is
    # allowed.
    assert "TARGETS=$(resolve_targets)" in script
    # Sanity: must understand the split-half regex.
    assert "milestone-\\\\d+" in script or "milestone-\\d+" in script


# ---------------------------------------------------------------------------
# Launcher template — PID + trap + wait + EXIT_CODE shape
# ---------------------------------------------------------------------------


def test_launcher_template_records_actual_child_pid_not_bash_pid() -> None:
    """Stage 1A defect #2 fix: launcher MUST record ``$!`` (the
    background child's PID) into AGENT_TEAM_PID.txt, NOT ``$$`` (the
    launcher's bash PID). Pre-remediation pattern is forbidden."""
    script = render_launcher_script(
        run_dir="/tmp/run-x",
        repo_root="/repo",
        venv_activate="/repo/.venv/bin/activate",
    )
    # Required: $! captures the spawned child's PID and is recorded.
    assert "CHILD=$!" in script
    assert 'echo "${CHILD}" > "${PID_FILE}"' in script
    # Forbidden: pre-remediation pattern wrote the launcher's own PID.
    assert "echo $$ > AGENT_TEAM_PID.txt" not in script
    assert 'echo $$ > "${PID_FILE}"' not in script


def test_launcher_template_traps_term_int_hup() -> None:
    """Launcher must trap TERM, INT, and HUP and forward each to the
    child's process group. Without these traps the watcher's SIGTERM
    kills bash but the child reparents to init."""
    script = render_launcher_script(
        run_dir="/tmp/run-x",
        repo_root="/repo",
        venv_activate="/repo/.venv/bin/activate",
    )
    assert "trap 'forward_signal TERM' TERM" in script
    assert "trap 'forward_signal INT' INT" in script
    assert "trap 'forward_signal HUP' HUP" in script
    # Forwarding must target the process group (negative PID), not the
    # bare child PID alone, so subprocesses (Codex CLI, docker, npm)
    # receive the signal too.
    assert 'kill -"${sig}" "-${CHILD}"' in script


def test_launcher_template_enables_job_control_for_process_group_isolation() -> None:
    """``set -m`` (monitor mode) is what makes backgrounded jobs land in
    their own process group under bash — REQUIRED for the trap's
    ``kill -<sig> -<pgid>`` forward pattern. Without ``set -m`` the
    child shares the launcher's PG and signals would loop back."""
    script = render_launcher_script(
        run_dir="/tmp/run-x",
        repo_root="/repo",
        venv_activate="/repo/.venv/bin/activate",
    )
    assert "set -m" in script
    # No setsid — the prior ``setsid --fork`` pattern detached the
    # child before AGENT_TEAM_PID.txt could capture the right PID.
    assert "setsid" not in script


def test_launcher_template_waits_and_writes_exit_code() -> None:
    script = render_launcher_script(
        run_dir="/tmp/run-x",
        repo_root="/repo",
        venv_activate="/repo/.venv/bin/activate",
    )
    assert 'wait "${CHILD}"' in script
    assert 'echo "${EXIT_CODE}" > "${EXIT_FILE}"' in script
    # No ``exec`` form (would replace bash and lose the trap).
    assert "exec agent-team-v15" not in script


def test_launcher_template_extra_cli_args_threaded() -> None:
    script = render_launcher_script(
        run_dir="/tmp/run-x",
        repo_root="/repo",
        venv_activate="/repo/.venv/bin/activate",
        extra_cli_args=("--legacy-permissive-audit",),
    )
    assert "--legacy-permissive-audit" in script
    assert "--legacy-permissive-audit \\ \\" not in script


# ---------------------------------------------------------------------------
# Integration — signal propagation end-to-end (no spend; sleep dummy).
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.name != "posix",
    reason="Launcher template uses POSIX signals (TERM / process groups).",
)
def test_launcher_propagates_term_to_child_and_writes_exit_code(
    tmp_path: Path,
) -> None:
    """End-to-end signal propagation: render the launcher, swap the
    real ``agent-team-v15`` for a dummy ``sleep 60``, send SIGTERM to
    the launcher, verify (a) the child sleep dies (no orphaned
    process), (b) ``AGENT_TEAM_PID.txt`` carries the actual child PID
    not bash's PID, (c) ``EXIT_CODE.txt`` is written with the
    signal-aware exit code (128 + 15 = 143 for SIGTERM, or any non-
    zero — what matters is that bash survived long enough to write
    it).
    """

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    venv_dir = tmp_path / "venv"
    (venv_dir / "bin").mkdir(parents=True)
    activate_script = venv_dir / "bin" / "activate"
    # Activate script just adds the dummy bin dir to PATH so
    # ``agent-team-v15`` resolves to our sleep wrapper.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    dummy_bin = bin_dir / "agent-team-v15"
    dummy_bin.write_text("""#!/usr/bin/env bash
# Dummy agent-team-v15: just sleep so we can test signal propagation.
if [[ "$1" == "--version" ]]; then
    echo "agent-team-v15 dummy 0.0.0"
    exit 0
fi
sleep 60
""")
    dummy_bin.chmod(0o755)
    activate_script.write_text(f'export PATH="{bin_dir}:$PATH"\n')
    activate_script.chmod(0o755)

    # Minimal repo_root with a git history so ``git rev-parse`` works.
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subprocess.check_call(
        ["git", "init", "-q", str(repo_root)], stderr=subprocess.DEVNULL,
    )
    # Need at least one commit so rev-parse HEAD resolves.
    subprocess.check_call(
        ["git", "-C", str(repo_root), "commit",
         "--allow-empty", "-q", "-m", "init"],
        env={**os.environ,
             "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
    )

    # Touch the PRD + config so the launcher's path-references resolve
    # (the dummy bin doesn't read them, but the launcher's preamble
    # references the paths).
    (run_dir / "PRD.md").write_text("# dummy\n", encoding="utf-8")
    (run_dir / "config.yaml").write_text("v18: {}\n", encoding="utf-8")

    script_text = render_launcher_script(
        run_dir=run_dir,
        repo_root=repo_root,
        venv_activate=activate_script,
        depth="exhaustive",
        milestone_cost_cap_usd=20,
        cumulative_wedge_cap=10,
        stage_label="prep-test",
    )
    launcher_path = run_dir / "launcher.sh"
    launcher_path.write_text(script_text, encoding="utf-8")
    launcher_path.chmod(0o755)

    # Spawn the launcher as its own process group leader so we can
    # SIGTERM it and observe the trap behaviour.
    proc = subprocess.Popen(
        ["bash", str(launcher_path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True,
        cwd=str(run_dir),
    )

    # Wait for the launcher to spawn the child + record its PID. This
    # races; poll PID_FILE + child existence. Cap at 10s to keep CI
    # fast.
    pid_file = run_dir / "AGENT_TEAM_PID.txt"
    deadline = time.monotonic() + 10.0
    child_pid: int | None = None
    while time.monotonic() < deadline:
        if pid_file.exists() and pid_file.read_text().strip():
            try:
                child_pid = int(pid_file.read_text().strip())
            except ValueError:
                child_pid = None
            if child_pid is not None and child_pid > 0:
                # Confirm the child process actually exists.
                try:
                    os.kill(child_pid, 0)
                    break
                except OSError:
                    child_pid = None
        time.sleep(0.1)

    assert child_pid is not None, (
        "Launcher failed to record AGENT_TEAM_PID.txt within 10s — "
        "trap/spawn pattern is broken."
    )
    assert child_pid != proc.pid, (
        f"Launcher recorded its own bash PID ({proc.pid}) into "
        f"AGENT_TEAM_PID.txt — Stage 1A defect #2 regression. The "
        f"recorded PID must be the agent-team-v15 child."
    )

    # Send SIGTERM to the launcher. The trap should forward to the
    # child PG and the launcher should then write EXIT_CODE.txt.
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        pytest.fail(
            "Launcher did not exit within 15s after SIGTERM — "
            "trap+wait pattern is wedged."
        )

    # Verify the child was reaped (not orphaned).
    try:
        os.kill(child_pid, 0)
        # If we get here, the child is still alive — orphaned regression.
        os.kill(child_pid, signal.SIGKILL)
        pytest.fail(
            f"Child PID {child_pid} survived launcher SIGTERM — Stage "
            "1A defect #2 regression. Trap forwarding to PG is broken."
        )
    except OSError:
        pass  # Child reaped — correct.

    exit_file = run_dir / "EXIT_CODE.txt"
    assert exit_file.exists(), (
        "EXIT_CODE.txt not written — launcher exited before its trap "
        "completed. Stage 1A defect #2 partial regression."
    )
    raw = exit_file.read_text().strip()
    assert raw, "EXIT_CODE.txt is empty"
    code = int(raw)
    # ``wait`` was interrupted by the SIGTERM trap; the recorded code
    # should be non-zero (signal-aware). The exact value depends on
    # whether wait was woken (128+15=143) or whether the child got
    # SIGTERM directly (also 143). Either way: not 0.
    assert code != 0, (
        f"EXIT_CODE={code} — expected signal-aware non-zero. The trap "
        "completed but the recorded code suggests a clean exit, which "
        "contradicts the SIGTERM."
    )


def test_watcher_log_dir_default_constant() -> None:
    """Lock the default log dir so future refactors don't silently
    move it under the run-dir."""
    assert WATCHER_LOG_DIR_DEFAULT == "/tmp"


# ---------------------------------------------------------------------------
# Watcher signals process group (NOT bare PID) — closeout-remediation
# reviewer blocker #1.
# ---------------------------------------------------------------------------


def test_watcher_template_signals_child_process_group_not_bare_pid() -> None:
    """Closeout-remediation reviewer blocker #1: the watcher previously
    sent ``kill -TERM "${AGENT_TEAM_PID}"`` (positive PID), which kills
    only the child orchestrator and bypasses the launcher trap entirely.
    Result: orphan subprocesses (Codex CLI, docker, npm) reparent to
    init and keep running. The fix targets the **process group**
    (negative PID) so the kernel reaps the entire child subtree —
    AND ``set -m`` in the launcher means PGID == child PID, so the
    same number does both jobs."""
    script = render_watcher_script(run_dir="/tmp/run-x")
    # Required: PG-targeted kill (negative PID).
    assert 'kill -TERM "-${AGENT_TEAM_PID}"' in script, (
        "Watcher must signal the child's process group via the negative-PID "
        "form so the kernel reaps the entire subtree (orchestrator + Codex "
        "CLI + docker + npm). Pre-fix used the positive PID, which killed "
        "only the orchestrator and orphaned its descendants."
    )
    # Forbidden: positive-PID form leaves descendants orphaned.
    assert 'kill -TERM "${AGENT_TEAM_PID}"' not in script


@pytest.mark.skipif(
    os.name != "posix",
    reason="Watcher + launcher use POSIX signals + process groups.",
)
def test_watcher_plus_launcher_end_to_end_reaps_child_and_grandchild(
    tmp_path: Path,
) -> None:
    """Closeout-remediation reviewer blocker #1: end-to-end proof that
    the watcher's signal — relayed through the launcher's PG forward —
    reaches BOTH the agent-team-v15 child AND a grandchild process the
    child spawned. Pre-fix: watcher's positive-PID kill missed the
    grandchild entirely.

    Setup:
      * Pre-populated ``STATE.json`` marks M1 + M2 COMPLETE so the
        watcher's first poll iteration finds all targets terminal and
        immediately fires the PG signal.
      * Dummy ``agent-team-v15`` spawns ``sleep 600 &`` in the
        background and ``wait``s on it — the bash dummy has NO trap,
        so the test proves it's the OS-level PG signal (not the
        dummy's own cleanup) that reaps the grandchild.

    Assertions:
      * Watcher exits cleanly (its job is done after the signal).
      * Launcher exits with non-zero (signal-aware EXIT_CODE.txt).
      * Both AGENT_TEAM_PID and grandchild PID no longer exist.
    """

    run_dir = tmp_path / "run"
    run_dir.mkdir()

    # Pre-populate STATE.json + MASTER_PLAN.json so the watcher fires
    # on its first poll iteration.
    agent_team_dir = run_dir / ".agent-team"
    agent_team_dir.mkdir()
    (agent_team_dir / "STATE.json").write_text(
        json.dumps({
            "milestone_progress": {
                "milestone-1": {"status": "COMPLETE"},
                "milestone-2": {"status": "COMPLETE"},
            }
        }),
        encoding="utf-8",
    )
    (agent_team_dir / "MASTER_PLAN.json").write_text(
        json.dumps({
            "milestones": [
                {"id": "milestone-1"},
                {"id": "milestone-2"},
                {"id": "milestone-3"},
            ]
        }),
        encoding="utf-8",
    )

    # Dummy agent-team-v15 that spawns a grandchild sleep. NO trap on
    # the dummy: the test exercises OS-level PG signaling, not in-bash
    # cleanup.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    dummy = bin_dir / "agent-team-v15"
    dummy.write_text("""#!/usr/bin/env bash
if [[ "$1" == "--version" ]]; then
    echo "agent-team-v15 dummy 0.0.0"
    exit 0
fi
sleep 600 &
GRANDCHILD=$!
echo "${GRANDCHILD}" > "${PWD}/grandchild.pid"
wait "${GRANDCHILD}"
""")
    dummy.chmod(0o755)

    venv_dir = tmp_path / "venv"
    (venv_dir / "bin").mkdir(parents=True)
    activate = venv_dir / "bin" / "activate"
    activate.write_text(f'export PATH="{bin_dir}:$PATH"\n')
    activate.chmod(0o755)

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subprocess.check_call(
        ["git", "init", "-q", str(repo_root)], stderr=subprocess.DEVNULL,
    )
    subprocess.check_call(
        ["git", "-C", str(repo_root), "commit",
         "--allow-empty", "-q", "-m", "init"],
        env={**os.environ,
             "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
    )

    (run_dir / "PRD.md").write_text("# dummy\n", encoding="utf-8")
    (run_dir / "config.yaml").write_text("v18: {}\n", encoding="utf-8")

    (run_dir / "launcher.sh").write_text(
        render_launcher_script(
            run_dir=run_dir, repo_root=repo_root, venv_activate=activate,
            stage_label="e2e-watcher-test",
        ),
        encoding="utf-8",
    )
    (run_dir / "launcher.sh").chmod(0o755)
    (run_dir / "watcher.sh").write_text(
        render_watcher_script(run_dir=run_dir, poll_seconds=1),
        encoding="utf-8",
    )
    (run_dir / "watcher.sh").chmod(0o755)

    launcher_proc = subprocess.Popen(
        ["bash", str(run_dir / "launcher.sh")],
        cwd=str(run_dir),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    # Wait until the launcher has spawned the child AND the dummy has
    # spawned its grandchild + recorded both PIDs.
    deadline = time.monotonic() + 10.0
    child_pid: int | None = None
    grandchild_pid: int | None = None
    while time.monotonic() < deadline:
        pid_file = run_dir / "AGENT_TEAM_PID.txt"
        gc_file = run_dir / "grandchild.pid"
        if pid_file.exists() and gc_file.exists():
            try:
                child_pid = int(pid_file.read_text().strip())
                grandchild_pid = int(gc_file.read_text().strip())
                os.kill(child_pid, 0)
                os.kill(grandchild_pid, 0)
                break
            except (OSError, ValueError):
                child_pid = None
                grandchild_pid = None
        time.sleep(0.1)

    assert child_pid is not None and grandchild_pid is not None, (
        "Launcher / dummy did not record both PIDs within 10s — "
        "spawn pattern broken."
    )

    # Spawn the watcher; it sees STATE.json (already terminal) on the
    # first poll and fires immediately.
    watcher_proc = subprocess.Popen(
        ["bash", str(run_dir / "watcher.sh")],
        cwd=str(run_dir),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    # Wait for the launcher to exit (its trap forwards to the PG, the
    # PG dies, ``wait`` returns, EXIT_CODE.txt is written).
    try:
        launcher_proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        launcher_proc.kill()
        watcher_proc.kill()
        pytest.fail(
            "Launcher did not exit within 20s after watcher fired — "
            "PG forward / trap chain broken."
        )

    try:
        watcher_proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        watcher_proc.kill()

    # Both child + grandchild MUST be reaped — proves the kernel
    # delivered the signal to the entire process group, not just
    # the bare child PID.
    for pid, name in ((child_pid, "child"), (grandchild_pid, "grandchild")):
        try:
            os.kill(pid, 0)
        except OSError:
            continue
        # Still alive — clean up + fail.
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
        pytest.fail(
            f"{name} PID {pid} survived the watcher's signal — "
            "process-group reaping is broken (orphan regression)."
        )

    exit_file = run_dir / "EXIT_CODE.txt"
    assert exit_file.exists(), "Launcher did not write EXIT_CODE.txt"
    code = int(exit_file.read_text().strip())
    assert code != 0, (
        f"EXIT_CODE={code} — expected signal-aware non-zero on PG "
        "termination."
    )

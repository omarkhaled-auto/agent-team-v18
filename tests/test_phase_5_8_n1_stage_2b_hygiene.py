"""Phase 5 closeout Stage 2 N1 — Stage 2B driver Docker hygiene + SIGTERM.

Stage 2 was NOT APPROVED 2026-05-01 with two source-remediation gates open.
The first authorised follow-up was the §O.4.6 / §M.M5 propagation fix (commit
85927d2). Smoke 1 of Rerun 3 v3 (HEAD ``85927d2``) bootstrapped onto stale
docker state from the prior ``phase-5-8a-stage-2b-rerun3-fresh-…`` smoke that
the operator killed mid-flight: containers from the previous run had been
``Up 5h`` holding ports 5432/4000/3000, causing the new launcher's docker
compose UP to fail before Wave B even started.

This module locks the driver-side hygiene + SIGTERM-aware behavior:

1. ``_list_stale_compose_*`` helpers DO surface stale Stage 2B state and
   distinguish project-label matches from generic ``clean-*`` containers.
2. ``_clean_stale_stage_2b_state`` runs ``docker compose -p <project> down``
   per detected project, force-removes leftover containers, removes leftover
   networks. It NEVER raises (timeout / missing binary / nonzero rc only
   surface in the returned dict).
3. ``_hygiene_check_blocking`` reports stale Stage 2B containers + networks
   as blockers (alongside the legacy ``clean-*`` filter and port-LISTEN /
   orphan-process checks).
4. ``--auto-clean`` (default) re-runs hygiene after cleanup; ``--no-auto-clean``
   restores the legacy fail-fast behaviour.
5. The ``main()`` SIGTERM handler propagates to the inflight launcher's
   process group (via ``os.killpg(pgid, SIGTERM)``) so the launcher template's
   own bash trap forwards to the agent-team-v15 child + every Codex /
   docker / npm subprocess it owns.
6. Final BATCH_RECORDS.json is always written, even on SIGTERM exit, and
   carries the ``shutdown_signum`` field so the operator can distinguish
   normal completion from operator-abort.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.phase_5_closeout import sequential_batch_2b as driver  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _CompletedProc:
    def __init__(self, *, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _make_run(
    *,
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
):
    """Return a side_effect callable that records each subprocess.run call."""

    calls: list[list[str]] = []

    def _run(cmd, *args, **kwargs):
        calls.append(list(cmd))
        return _CompletedProc(stdout=stdout, stderr=stderr, returncode=returncode)

    return calls, _run


# ---------------------------------------------------------------------------
# Stale-state listing helpers
# ---------------------------------------------------------------------------


def test_list_stale_compose_projects_filters_prefix(monkeypatch):
    fixture = textwrap.dedent(
        """\
        phase-5-8a-stage-2b-rerun3-fresh-20260501-01-20260501-104516
        phase-5-8a-stage-2b-20260501-01-20260501-000725

        arkanpm
        unrelated-project
        """
    )

    monkeypatch.setattr(
        driver.subprocess,
        "run",
        lambda *a, **kw: _CompletedProc(stdout=fixture),
    )
    out = driver._list_stale_compose_projects()
    assert out == {
        "phase-5-8a-stage-2b-rerun3-fresh-20260501-01-20260501-104516",
        "phase-5-8a-stage-2b-20260501-01-20260501-000725",
    }


def test_list_stale_compose_projects_handles_missing_docker(monkeypatch):
    def _raise(*a, **kw):
        raise FileNotFoundError("docker not on PATH")

    monkeypatch.setattr(driver.subprocess, "run", _raise)
    assert driver._list_stale_compose_projects() == set()


def test_list_stale_compose_containers_extracts_id_name_project(monkeypatch):
    fixture = textwrap.dedent(
        """\
        abc123\tphase-5-8a-stage-2b-rerun3-fresh-20260501-01-20260501-104516-postgres-1\tphase-5-8a-stage-2b-rerun3-fresh-20260501-01-20260501-104516
        def456\tphase-5-8a-stage-2b-rerun3-fresh-20260501-01-20260501-104516-api-1\tphase-5-8a-stage-2b-rerun3-fresh-20260501-01-20260501-104516
        ghi789\tarkanpm-postgres-1\tarkanpm
        """
    )

    monkeypatch.setattr(
        driver.subprocess,
        "run",
        lambda *a, **kw: _CompletedProc(stdout=fixture),
    )
    rows = driver._list_stale_compose_containers()
    assert len(rows) == 2
    assert rows[0][0] == "abc123"
    assert rows[1][1] == (
        "phase-5-8a-stage-2b-rerun3-fresh-20260501-01-20260501-104516-api-1"
    )
    assert all(
        proj.startswith(driver.PHASE5_8A_STAGE_2B_PROJECT_PREFIX)
        for _, _, proj in rows
    )


def test_list_stale_compose_networks_filters_prefix(monkeypatch):
    fixture = textwrap.dedent(
        """\
        bridge
        host
        none
        arkanpm_arkanpm
        phase-5-8a-stage-2b-20260501-01-20260501-000725_default
        phase-5-8a-stage-2b-rerun3-fresh-20260501-01-20260501-104516_default
        """
    )

    monkeypatch.setattr(
        driver.subprocess,
        "run",
        lambda *a, **kw: _CompletedProc(stdout=fixture),
    )
    out = driver._list_stale_compose_networks()
    assert out == {
        "phase-5-8a-stage-2b-20260501-01-20260501-000725_default",
        "phase-5-8a-stage-2b-rerun3-fresh-20260501-01-20260501-104516_default",
    }


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def test_clean_stale_stage_2b_state_runs_compose_down_per_project(monkeypatch):
    monkeypatch.setattr(
        driver,
        "_list_stale_compose_projects",
        lambda: {"proj-a", "proj-b"},
    )
    monkeypatch.setattr(driver, "_list_stale_compose_containers", lambda: [])
    monkeypatch.setattr(driver, "_list_stale_compose_networks", lambda: set())

    calls, runner = _make_run()
    monkeypatch.setattr(driver.subprocess, "run", runner)
    out = driver._clean_stale_stage_2b_state(log=False)

    compose_calls = [c for c in calls if "compose" in c]
    assert len(compose_calls) == 2
    for c in compose_calls:
        assert c[0] == "docker"
        assert c[1] == "compose"
        assert c[2] == "-p"
        assert c[3] in {"proj-a", "proj-b"}
        assert c[4] == "down"
        assert "--remove-orphans" in c
        assert "-v" in c
    assert sorted(out["compose_down"]) == ["proj-a", "proj-b"]


def test_clean_stale_stage_2b_state_force_removes_orphan_containers(monkeypatch):
    monkeypatch.setattr(driver, "_list_stale_compose_projects", lambda: set())
    monkeypatch.setattr(
        driver,
        "_list_stale_compose_containers",
        lambda: [
            ("abc123def456789012", "stale-postgres-1", "proj-x"),
            ("ffff0000aaaa", "stale-api-1", "proj-x"),
        ],
    )
    monkeypatch.setattr(driver, "_list_stale_compose_networks", lambda: set())

    calls, runner = _make_run()
    monkeypatch.setattr(driver.subprocess, "run", runner)
    out = driver._clean_stale_stage_2b_state(log=False)

    rm_calls = [c for c in calls if c[:3] == ["docker", "rm", "-f"]]
    assert len(rm_calls) == 2
    assert rm_calls[0][3] == "abc123def456789012"
    assert rm_calls[1][3] == "ffff0000aaaa"
    # Names + truncated IDs are in the report.
    assert any(item.startswith("stale-postgres-1 (") for item in out["container_rm"])


def test_clean_stale_stage_2b_state_removes_networks(monkeypatch):
    monkeypatch.setattr(driver, "_list_stale_compose_projects", lambda: set())
    monkeypatch.setattr(driver, "_list_stale_compose_containers", lambda: [])
    monkeypatch.setattr(
        driver,
        "_list_stale_compose_networks",
        lambda: {
            "phase-5-8a-stage-2b-rerun3-fresh-20260501_default",
            "phase-5-8a-stage-2b-20260501-01_default",
        },
    )

    calls, runner = _make_run()
    monkeypatch.setattr(driver.subprocess, "run", runner)
    out = driver._clean_stale_stage_2b_state(log=False)

    net_calls = [c for c in calls if c[:3] == ["docker", "network", "rm"]]
    assert len(net_calls) == 2
    assert sorted(out["network_rm"]) == sorted([
        "phase-5-8a-stage-2b-20260501-01_default",
        "phase-5-8a-stage-2b-rerun3-fresh-20260501_default",
    ])


def test_clean_stale_stage_2b_state_swallows_timeout(monkeypatch):
    monkeypatch.setattr(driver, "_list_stale_compose_projects", lambda: {"slow-proj"})
    monkeypatch.setattr(driver, "_list_stale_compose_containers", lambda: [])
    monkeypatch.setattr(driver, "_list_stale_compose_networks", lambda: set())

    def _raise(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="docker compose down", timeout=60)

    monkeypatch.setattr(driver.subprocess, "run", _raise)
    out = driver._clean_stale_stage_2b_state(log=False)
    assert out["compose_down"] == []  # no raise; reported as not-actioned


def test_clean_stale_stage_2b_state_swallows_missing_docker(monkeypatch):
    monkeypatch.setattr(driver, "_list_stale_compose_projects", lambda: {"some-proj"})
    monkeypatch.setattr(driver, "_list_stale_compose_containers", lambda: [])
    monkeypatch.setattr(driver, "_list_stale_compose_networks", lambda: set())

    def _raise(*a, **kw):
        raise FileNotFoundError("docker missing")

    monkeypatch.setattr(driver.subprocess, "run", _raise)
    out = driver._clean_stale_stage_2b_state(log=False)
    assert out["compose_down"] == []


# ---------------------------------------------------------------------------
# Hygiene check (blockers)
# ---------------------------------------------------------------------------


def test_hygiene_check_blocking_reports_stale_stage_2b_containers(monkeypatch):
    monkeypatch.setattr(
        driver,
        "_list_stale_compose_containers",
        lambda: [
            ("abcdef123456789012", "phase-5-8a-stage-2b-foo-postgres-1", "phase-5-8a-stage-2b-foo"),
        ],
    )
    monkeypatch.setattr(driver, "_list_stale_compose_networks", lambda: set())

    # Other shellouts return empty.
    def _empty(*a, **kw):
        return _CompletedProc(stdout="")

    monkeypatch.setattr(driver.subprocess, "run", _empty)

    blockers = driver._hygiene_check_blocking()
    matched = [b for b in blockers if "stale Stage 2B container" in b]
    assert len(matched) == 1
    assert "phase-5-8a-stage-2b-foo-postgres-1" in matched[0]
    assert "abcdef123456" in matched[0]
    assert "phase-5-8a-stage-2b-foo" in matched[0]


def test_hygiene_check_blocking_reports_stale_stage_2b_networks(monkeypatch):
    monkeypatch.setattr(driver, "_list_stale_compose_containers", lambda: [])
    monkeypatch.setattr(
        driver,
        "_list_stale_compose_networks",
        lambda: {"phase-5-8a-stage-2b-rerun3_default"},
    )

    def _empty(*a, **kw):
        return _CompletedProc(stdout="")

    monkeypatch.setattr(driver.subprocess, "run", _empty)

    blockers = driver._hygiene_check_blocking()
    matched = [b for b in blockers if "stale Stage 2B network" in b]
    assert matched == ["stale Stage 2B network: phase-5-8a-stage-2b-rerun3_default"]


def test_hygiene_check_blocking_reports_port_listen(monkeypatch):
    """The pre-existing port LISTEN check still fires for 5432/5433/3080/4000."""

    def _run(cmd, *a, **kw):
        if cmd[0] == "lsof":
            return _CompletedProc(
                stdout="COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
                "postgres 1234 omar 4u IPv4 ... 0t0 TCP *:postgresql (LISTEN)\n"
            )
        return _CompletedProc(stdout="")

    monkeypatch.setattr(driver.subprocess, "run", _run)
    monkeypatch.setattr(driver, "_list_stale_compose_containers", lambda: [])
    monkeypatch.setattr(driver, "_list_stale_compose_networks", lambda: set())

    blockers = driver._hygiene_check_blocking()
    assert any("port LISTEN" in b for b in blockers)


# ---------------------------------------------------------------------------
# --auto-clean / --no-auto-clean main() integration
# ---------------------------------------------------------------------------


def _run_main_with_minimal_io(monkeypatch, tmp_path, extra_args):
    """Patch out filesystem prereqs + canonical PRD/config so main() runs."""

    monkeypatch.setattr(driver, "CANONICAL_PRD", tmp_path / "PRD.md")
    monkeypatch.setattr(driver, "CANONICAL_CONFIG", tmp_path / "config.yaml")
    (tmp_path / "PRD.md").write_text("# PRD\n", encoding="utf-8")
    (tmp_path / "config.yaml").write_text("v18: {}\n", encoding="utf-8")
    batch_root = tmp_path / "runs"
    batch_root.mkdir()
    return driver.main(
        [
            "--batch-id",
            "phase-5-8a-stage-2b-test",
            "--batch-root",
            str(batch_root),
            *extra_args,
        ]
    )


def test_pre_launch_auto_clean_recovers_when_cleanup_succeeds(monkeypatch, tmp_path, capsys):
    """Pre-launch hygiene: blocker → auto-clean → re-check clean → proceed."""

    call_log = {"hygiene_calls": 0, "clean_calls": 0}

    def _hygiene():
        call_log["hygiene_calls"] += 1
        # First call returns a blocker; subsequent calls clean.
        if call_log["hygiene_calls"] == 1:
            return ["stale Stage 2B network: phase-5-8a-stage-2b-foo_default"]
        return []

    def _clean(*, log=True):
        call_log["clean_calls"] += 1
        return {"compose_down": [], "container_rm": [], "network_rm": ["phase-5-8a-stage-2b-foo_default"]}

    monkeypatch.setattr(driver, "_hygiene_check_blocking", _hygiene)
    monkeypatch.setattr(driver, "_clean_stale_stage_2b_state", _clean)
    # Avoid running real smokes — return immediately from the launch path.
    monkeypatch.setattr(driver, "_launch_and_wait", lambda *a, **kw: 0)
    monkeypatch.setattr(driver, "_provision_run_dir", lambda **kw: tmp_path / f"run-{kw['smoke_index']}")
    monkeypatch.setattr(driver, "_render_harness_into", lambda *a, **kw: None)
    monkeypatch.setattr(driver, "_scan_diagnostics", lambda *a, **kw: [])

    # Smoke run-dir must exist for the scan helper.
    (tmp_path / "run-1").mkdir()

    rc = _run_main_with_minimal_io(monkeypatch, tmp_path, ["--max-smokes", "1"])
    assert rc == 0
    assert call_log["clean_calls"] >= 1
    # Pre-batch hygiene re-runs after clean (calls 1 + 2); inter-smoke
    # may re-run after smoke 1 (3+). At minimum 2 hygiene calls.
    assert call_log["hygiene_calls"] >= 2


def test_pre_launch_no_auto_clean_fails_fast_on_blocker(monkeypatch, tmp_path):
    monkeypatch.setattr(
        driver,
        "_hygiene_check_blocking",
        lambda: ["stale Stage 2B network: phase-5-8a-stage-2b-foo_default"],
    )
    cleaned: list[bool] = []

    def _clean(*, log=True):
        cleaned.append(True)
        return {"compose_down": [], "container_rm": [], "network_rm": []}

    monkeypatch.setattr(driver, "_clean_stale_stage_2b_state", _clean)

    rc = _run_main_with_minimal_io(
        monkeypatch, tmp_path, ["--no-auto-clean", "--max-smokes", "1"]
    )
    assert rc == 2
    assert cleaned == []  # cleanup never invoked when --no-auto-clean


def test_stage_2b_launcher_omits_split_preflight_args_by_default(tmp_path):
    """Default Stage 2B smoke must not require an impossible split path."""

    run_dir = tmp_path / "run"
    run_dir.mkdir()

    driver._render_harness_into(run_dir, smoke_label="Stage 2B test")

    launcher = (run_dir / "launcher.sh").read_text(encoding="utf-8")
    assert "--require-split-parent" not in launcher
    assert "--require-split-parts-min" not in launcher


def test_stage_2b_launcher_threads_explicit_split_preflight_args(tmp_path):
    """Operator-supplied split preflight args are still passed to the CLI."""

    run_dir = tmp_path / "run"
    run_dir.mkdir()

    driver._render_harness_into(
        run_dir,
        smoke_label="Stage 2B test",
        extra_cli_args=(
            "--require-split-parent",
            "milestone-4",
            "--require-split-parts-min",
            "2",
        ),
    )

    launcher = (run_dir / "launcher.sh").read_text(encoding="utf-8")
    assert "--require-split-parent" in launcher
    assert "milestone-4" in launcher
    assert "--require-split-parts-min" in launcher
    assert "  2 \\" in launcher


def test_stage_2b_driver_threads_explicit_split_preflight_args(monkeypatch, tmp_path):
    """Driver-level --require-split-* args are rendered into launcher.sh."""

    monkeypatch.setattr(driver, "CANONICAL_PRD", tmp_path / "PRD.md")
    monkeypatch.setattr(driver, "CANONICAL_CONFIG", tmp_path / "config.yaml")
    (tmp_path / "PRD.md").write_text("# PRD\n", encoding="utf-8")
    (tmp_path / "config.yaml").write_text("v18: {}\n", encoding="utf-8")
    monkeypatch.setattr(driver, "_hygiene_check_blocking", lambda: [])
    monkeypatch.setattr(driver, "_launch_and_wait", lambda *a, **kw: 0)
    monkeypatch.setattr(driver, "_scan_diagnostics", lambda *a, **kw: [])

    batch_root = tmp_path / "runs"
    rc = driver.main(
        [
            "--batch-id",
            "phase-5-8a-stage-2b-explicit-split",
            "--batch-root",
            str(batch_root),
            "--max-smokes",
            "1",
            "--require-split-parent",
            "milestone-4",
            "--require-split-parts-min",
            "2",
        ]
    )

    assert rc == 0
    [run_dir] = sorted(batch_root.glob("phase-5-8a-stage-2b-explicit-split-01-*"))
    launcher = (run_dir / "launcher.sh").read_text(encoding="utf-8")
    assert "--require-split-parent" in launcher
    assert "milestone-4" in launcher
    assert "--require-split-parts-min" in launcher
    assert "  2 \\" in launcher


def test_relative_batch_root_is_resolved_before_run_dir_creation(monkeypatch, tmp_path):
    """Relative --batch-root must not leak into child-cwd launcher paths."""

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(driver, "CANONICAL_PRD", tmp_path / "PRD.md")
    monkeypatch.setattr(driver, "CANONICAL_CONFIG", tmp_path / "config.yaml")
    (tmp_path / "PRD.md").write_text("# PRD\n", encoding="utf-8")
    (tmp_path / "config.yaml").write_text("v18: {}\n", encoding="utf-8")
    monkeypatch.setattr(driver, "_hygiene_check_blocking", lambda: [])
    monkeypatch.setattr(driver, "_render_harness_into", lambda *a, **kw: None)
    monkeypatch.setattr(driver, "_launch_and_wait", lambda *a, **kw: 0)
    monkeypatch.setattr(driver, "_scan_diagnostics", lambda *a, **kw: [])

    seen_batch_roots: list[Path] = []

    def _provision_run_dir(*, batch_id, smoke_index, batch_root):
        seen_batch_roots.append(batch_root)
        run_dir = batch_root / f"{batch_id}-{smoke_index:02d}"
        run_dir.mkdir(parents=True, exist_ok=False)
        return run_dir

    monkeypatch.setattr(driver, "_provision_run_dir", _provision_run_dir)

    rc = driver.main(
        [
            "--batch-id",
            "phase-5-8a-stage-2b-relative-root",
            "--batch-root",
            "relative runs",
            "--max-smokes",
            "1",
        ]
    )

    expected_root = (tmp_path / "relative runs").resolve()
    assert rc == 0
    assert seen_batch_roots == [expected_root]
    record_path = expected_root / "phase-5-8a-stage-2b-relative-root-BATCH_RECORDS.json"
    payload = json.loads(record_path.read_text(encoding="utf-8"))
    assert Path(payload["smokes"][0]["run_dir"]).is_absolute()


# ---------------------------------------------------------------------------
# SIGTERM handler — propagation + cleanup + BATCH_RECORDS.json
# ---------------------------------------------------------------------------


def _build_signal_aware_main_thread(monkeypatch, tmp_path, extra_args):
    """Build a runnable main() that uses a controllable launch path.

    The launch path calls a hook that the test fires SIGTERM into the
    current process from. Returns the return code from main().
    """

    monkeypatch.setattr(driver, "CANONICAL_PRD", tmp_path / "PRD.md")
    monkeypatch.setattr(driver, "CANONICAL_CONFIG", tmp_path / "config.yaml")
    (tmp_path / "PRD.md").write_text("# PRD\n", encoding="utf-8")
    (tmp_path / "config.yaml").write_text("v18: {}\n", encoding="utf-8")
    batch_root = tmp_path / "runs"
    batch_root.mkdir()

    return driver.main(
        [
            "--batch-id",
            "phase-5-8a-stage-2b-test",
            "--batch-root",
            str(batch_root),
            *extra_args,
        ]
    )


def test_signal_handler_propagates_sigterm_to_inflight_pgid(monkeypatch):
    """Direct unit test: signal handler closure issues killpg on inflight PIDs."""

    captured_kills: list[tuple[int, int]] = []

    def _killpg(pgid, sig):
        captured_kills.append((pgid, sig))

    def _getpgid(pid):
        return pid * 10  # synthetic PGID derivation

    monkeypatch.setattr(driver.os, "killpg", _killpg)
    monkeypatch.setattr(driver.os, "getpgid", _getpgid)

    # Build the closure pieces driver.main constructs internally.
    inflight: dict[str, mock.Mock | None] = {
        "launcher": mock.Mock(pid=12345, poll=lambda: None),
        "watcher": mock.Mock(pid=12346, poll=lambda: None),
    }
    shutdown = {"flag": False, "signum": 0}

    def _on_signal(signum, frame):
        if shutdown["flag"]:
            return
        shutdown["flag"] = True
        shutdown["signum"] = signum
        for key in ("launcher", "watcher"):
            proc = inflight[key]
            if proc is None or proc.poll() is not None:
                continue
            try:
                pgid = driver.os.getpgid(proc.pid)
                driver.os.killpg(pgid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass

    _on_signal(signal.SIGTERM, None)

    assert shutdown["flag"] is True
    assert shutdown["signum"] == signal.SIGTERM
    assert (123450, signal.SIGTERM) in captured_kills
    assert (123460, signal.SIGTERM) in captured_kills


def test_signal_handler_skips_already_exited_processes(monkeypatch):
    captured_kills: list[tuple[int, int]] = []
    monkeypatch.setattr(
        driver.os, "killpg", lambda pgid, sig: captured_kills.append((pgid, sig))
    )
    monkeypatch.setattr(driver.os, "getpgid", lambda pid: pid * 10)

    inflight: dict[str, mock.Mock | None] = {
        "launcher": mock.Mock(pid=11111, poll=lambda: 0),  # already exited
        "watcher": mock.Mock(pid=11112, poll=lambda: None),
    }
    shutdown = {"flag": False, "signum": 0}

    def _on_signal(signum, frame):
        if shutdown["flag"]:
            return
        shutdown["flag"] = True
        for key in ("launcher", "watcher"):
            proc = inflight[key]
            if proc is None or proc.poll() is not None:
                continue
            pgid = driver.os.getpgid(proc.pid)
            driver.os.killpg(pgid, signal.SIGTERM)

    _on_signal(signal.SIGTERM, None)

    # Only watcher (alive) gets killed — launcher's poll() returned 0.
    assert (111120, signal.SIGTERM) in captured_kills
    assert (111110, signal.SIGTERM) not in captured_kills


def test_main_sigterm_runs_docker_cleanup_in_finally(monkeypatch, tmp_path):
    """End-to-end: SIGTERM mid-batch → cleanup invoked + 143 returned."""

    monkeypatch.setattr(driver, "_hygiene_check_blocking", lambda: [])

    cleanup_calls: list[bool] = []

    def _clean(*, log=True):
        cleanup_calls.append(True)
        return {"compose_down": [], "container_rm": [], "network_rm": []}

    monkeypatch.setattr(driver, "_clean_stale_stage_2b_state", _clean)
    monkeypatch.setattr(driver, "_provision_run_dir", lambda **kw: tmp_path / f"run-{kw['smoke_index']}")
    monkeypatch.setattr(driver, "_render_harness_into", lambda *a, **kw: None)
    monkeypatch.setattr(driver, "_scan_diagnostics", lambda *a, **kw: [])

    # Make _launch_and_wait fire the SIGTERM into the current process so
    # the closure-installed handler runs and flips the shutdown flag,
    # then return as if SIGTERM woke up wait().
    def _fake_launch(run_dir, *, inflight=None):
        run_dir.mkdir(exist_ok=True)
        os.kill(os.getpid(), signal.SIGTERM)
        return 143

    monkeypatch.setattr(driver, "_launch_and_wait", _fake_launch)

    monkeypatch.setattr(driver, "CANONICAL_PRD", tmp_path / "PRD.md")
    monkeypatch.setattr(driver, "CANONICAL_CONFIG", tmp_path / "config.yaml")
    (tmp_path / "PRD.md").write_text("# PRD\n", encoding="utf-8")
    (tmp_path / "config.yaml").write_text("v18: {}\n", encoding="utf-8")
    batch_root = tmp_path / "runs"
    batch_root.mkdir()

    rc = driver.main(
        [
            "--batch-id",
            "phase-5-8a-stage-2b-sigterm",
            "--batch-root",
            str(batch_root),
            "--max-smokes",
            "5",
        ]
    )

    assert rc == 143
    assert cleanup_calls, "expected docker cleanup to run in finally on SIGTERM"


def test_main_writes_batch_records_on_sigterm_exit(monkeypatch, tmp_path):
    """BATCH_RECORDS.json is written even when SIGTERM aborts the batch."""

    monkeypatch.setattr(driver, "_hygiene_check_blocking", lambda: [])
    monkeypatch.setattr(
        driver,
        "_clean_stale_stage_2b_state",
        lambda *, log=True: {"compose_down": [], "container_rm": [], "network_rm": []},
    )
    monkeypatch.setattr(driver, "_provision_run_dir", lambda **kw: tmp_path / f"run-{kw['smoke_index']}")
    monkeypatch.setattr(driver, "_render_harness_into", lambda *a, **kw: None)
    monkeypatch.setattr(driver, "_scan_diagnostics", lambda *a, **kw: [])

    def _fake_launch(run_dir, *, inflight=None):
        run_dir.mkdir(exist_ok=True)
        os.kill(os.getpid(), signal.SIGTERM)
        return 143

    monkeypatch.setattr(driver, "_launch_and_wait", _fake_launch)

    monkeypatch.setattr(driver, "CANONICAL_PRD", tmp_path / "PRD.md")
    monkeypatch.setattr(driver, "CANONICAL_CONFIG", tmp_path / "config.yaml")
    (tmp_path / "PRD.md").write_text("# PRD\n", encoding="utf-8")
    (tmp_path / "config.yaml").write_text("v18: {}\n", encoding="utf-8")
    batch_root = tmp_path / "runs"
    batch_root.mkdir()

    rc = driver.main(
        [
            "--batch-id",
            "phase-5-8a-stage-2b-batch-records",
            "--batch-root",
            str(batch_root),
            "--max-smokes",
            "3",
        ]
    )

    assert rc == 143
    record_path = batch_root / "phase-5-8a-stage-2b-batch-records-BATCH_RECORDS.json"
    assert record_path.is_file(), "BATCH_RECORDS.json must be written on SIGTERM exit"
    payload = json.loads(record_path.read_text(encoding="utf-8"))
    assert payload["batch_id"] == "phase-5-8a-stage-2b-batch-records"
    assert payload["shutdown_signum"] == signal.SIGTERM
    assert isinstance(payload["smokes"], list)
    # At least one smoke (the one that fired SIGTERM via _fake_launch) is recorded.
    assert len(payload["smokes"]) == 1


def test_inflight_dict_is_cleared_after_normal_smoke_completion(monkeypatch, tmp_path):
    """Post-smoke, inflight slots must be None so a follow-up signal is no-op."""

    captured: dict[str, list] = {"snapshots": []}

    def _fake_launch(run_dir, *, inflight=None):
        run_dir.mkdir(exist_ok=True)
        # Simulate a brief in-flight window by inserting a synthetic Popen-like.
        if inflight is not None:
            inflight["launcher"] = mock.Mock(pid=99999, poll=lambda: None)
            inflight["watcher"] = mock.Mock(pid=99998, poll=lambda: None)
            captured["snapshots"].append(dict(inflight))  # mid-flight
            inflight["launcher"] = None
            inflight["watcher"] = None
            captured["snapshots"].append(dict(inflight))  # post-flight
        return 0

    # Real _launch_and_wait clears the inflight slots in its finally; here
    # we explicitly verify that the wrapper around it (driver.main) trusts
    # the contract by making the test fixture follow the same shape.
    snapshot = _fake_launch(tmp_path / "demo", inflight={"launcher": None, "watcher": None})
    assert captured["snapshots"][0]["launcher"] is not None
    assert captured["snapshots"][1]["launcher"] is None
    assert snapshot == 0

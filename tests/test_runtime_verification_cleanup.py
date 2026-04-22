"""Cleanup hardening tests for runtime_verification (Issue #11).

Guards the three invariants introduced by the fix:

1. ``docker_cleanup`` calls ``docker compose down -v -t 10`` so Windows
   Docker releases named-volume mounts (node_modules etc.) and each
   container gets a 10-second SIGTERM grace before SIGKILL.
2. ``run_runtime_verification`` wraps the main body in ``try/finally`` so
   cleanup still runs when the fix loop raises an exception.
3. ``cleanup_after=False`` opts out of the down command entirely
   (local-dev / interactive runs keep containers alive).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agent_team_v15 import runtime_verification as rv
from agent_team_v15.runtime_verification import (
    docker_cleanup,
    run_runtime_verification,
)


@pytest.fixture
def fake_compose(tmp_path: Path) -> Path:
    """Create an empty compose file so find_compose_file resolves a real path."""
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    return compose


def test_docker_cleanup_uses_down_v_with_graceful_timeout(tmp_path: Path, fake_compose: Path) -> None:
    """docker_cleanup must issue ``docker compose down -v -t 10``.

    ``-t 10`` is the authoritative compose graceful-shutdown knob
    (SIGTERM, then SIGKILL after 10s) per docker/compose reference —
    replaces the earlier pattern of sleeping before ``down``, which did
    nothing useful since containers kept running during the sleep.
    """
    with patch.object(rv, "_run_docker") as mock_run:
        docker_cleanup(tmp_path, fake_compose)

    assert mock_run.call_count == 1
    positional = mock_run.call_args.args
    assert "down" in positional
    assert "-v" in positional
    # -t <seconds> for graceful SIGTERM window.
    assert "-t" in positional
    t_idx = positional.index("-t")
    assert positional[t_idx + 1] == "10"
    # -v immediately follows down so the volume flag is unambiguously tied
    # to the down subcommand (not a stray global flag).
    down_idx = positional.index("down")
    assert positional[down_idx + 1] == "-v"


def test_cleanup_after_true_triggers_down_v(tmp_path: Path, fake_compose: Path) -> None:
    """Happy path: cleanup_after=True ends with a ``down -v`` invocation."""
    down_v_calls: list[tuple] = []

    def _fake_run_docker(*args: str, cwd=None, timeout=600):
        if "down" in args and "-v" in args:
            down_v_calls.append(args)
        return (0, "", "")

    with patch.object(rv, "check_docker_available", return_value=True), \
         patch.object(rv, "find_compose_file", return_value=fake_compose), \
         patch.object(rv, "docker_build", return_value=[]), \
         patch.object(rv, "docker_start", return_value=[]), \
         patch.object(rv, "_run_docker", side_effect=_fake_run_docker):
        report = run_runtime_verification(
            project_root=tmp_path,
            docker_build_enabled=False,
            docker_start_enabled=False,
            database_init_enabled=False,
            smoke_test_enabled=False,
            cleanup_after=True,
            fix_loop=False,
            max_total_fix_rounds=0,
        )

    assert report.compose_file == str(fake_compose)
    assert len(down_v_calls) == 1, "cleanup_after=True must invoke docker compose down -v exactly once"
    # Graceful-shutdown timeout is passed.
    assert "-t" in down_v_calls[0] and "10" in down_v_calls[0]


def test_cleanup_after_false_skips_cleanup(tmp_path: Path, fake_compose: Path) -> None:
    """Opt-out path: cleanup_after=False must NOT issue a down command from the cleanup step."""
    observed: list[tuple] = []

    def _fake_run_docker(*args: str, cwd=None, timeout=600):
        observed.append(args)
        return (0, "", "")

    with patch.object(rv, "check_docker_available", return_value=True), \
         patch.object(rv, "find_compose_file", return_value=fake_compose), \
         patch.object(rv, "docker_build", return_value=[]), \
         patch.object(rv, "docker_start", return_value=[]), \
         patch.object(rv, "_run_docker", side_effect=_fake_run_docker):
        run_runtime_verification(
            project_root=tmp_path,
            docker_build_enabled=False,
            docker_start_enabled=False,
            database_init_enabled=False,
            smoke_test_enabled=False,
            cleanup_after=False,
            fix_loop=False,
            max_total_fix_rounds=0,
        )

    # No phase is enabled, so no _run_docker calls should occur, and
    # definitely no ``down`` command from the cleanup step.
    assert not any("down" in call for call in observed)


def test_cleanup_runs_in_finally_when_body_raises(tmp_path: Path, fake_compose: Path) -> None:
    """An exception raised inside the fix loop must still trigger cleanup."""
    down_v_calls: list[tuple] = []

    def _fake_run_docker(*args: str, cwd=None, timeout=600):
        if "down" in args and "-v" in args:
            down_v_calls.append(args)
        return (0, "", "")

    def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated docker_build crash")

    with patch.object(rv, "check_docker_available", return_value=True), \
         patch.object(rv, "find_compose_file", return_value=fake_compose), \
         patch.object(rv, "docker_build", side_effect=_boom), \
         patch.object(rv, "docker_start", return_value=[]), \
         patch.object(rv, "_run_docker", side_effect=_fake_run_docker):
        with pytest.raises(RuntimeError, match="simulated docker_build crash"):
            run_runtime_verification(
                project_root=tmp_path,
                docker_build_enabled=True,
                docker_start_enabled=False,
                database_init_enabled=False,
                smoke_test_enabled=False,
                cleanup_after=True,
                fix_loop=False,
                max_total_fix_rounds=0,
            )

    assert len(down_v_calls) == 1, "finally block must run cleanup even when body raises"


def test_cleanup_exception_is_swallowed(tmp_path: Path, fake_compose: Path) -> None:
    """Cleanup itself failing must not mask a successful body or raise post-return."""
    def _fake_run_docker(*args: str, cwd=None, timeout=600):
        if "down" in args:
            raise RuntimeError("docker daemon exploded")
        return (0, "", "")

    with patch.object(rv, "check_docker_available", return_value=True), \
         patch.object(rv, "find_compose_file", return_value=fake_compose), \
         patch.object(rv, "docker_build", return_value=[]), \
         patch.object(rv, "docker_start", return_value=[]), \
         patch.object(rv, "_run_docker", side_effect=_fake_run_docker):
        # Should not raise - cleanup failure is logged and swallowed.
        report = run_runtime_verification(
            project_root=tmp_path,
            docker_build_enabled=False,
            docker_start_enabled=False,
            database_init_enabled=False,
            smoke_test_enabled=False,
            cleanup_after=True,
            fix_loop=False,
            max_total_fix_rounds=0,
        )

    assert report.compose_file == str(fake_compose)


def test_default_cleanup_after_is_true() -> None:
    """Calibration smoke path depends on cleanup_after defaulting to True."""
    import inspect

    sig = inspect.signature(run_runtime_verification)
    assert sig.parameters["cleanup_after"].default is True

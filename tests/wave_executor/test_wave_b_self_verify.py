"""Unit tests for :mod:`agent_team_v15.wave_b_self_verify`.

These tests verify the Wave B in-wave acceptance test helper in isolation:
compose-sanity + docker-build are mocked; no Docker is invoked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_team_v15 import wave_b_self_verify as wbsv
from agent_team_v15.compose_sanity import Violation
from agent_team_v15.runtime_verification import BuildResult


@pytest.fixture(autouse=True)
def _stub_docker_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default every test in this module to a healthy Docker daemon.

    ``run_wave_b_acceptance_test`` now short-circuits with
    ``env_unavailable=True`` when ``check_docker_available()`` is False (see
    the env-skip fix). Tests in this module exercise the ``docker_build``
    path, so they need the daemon check to report True. Tests that
    specifically exercise the env-skip path live in
    ``tests/test_wave_b_self_verify_env_skip.py``.
    """
    monkeypatch.setattr(wbsv, "check_docker_available", lambda: True)


@pytest.fixture
def fake_compose(tmp_path: Path) -> Path:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    return compose


def _install_find_compose(monkeypatch: pytest.MonkeyPatch, result: Path | None) -> None:
    monkeypatch.setattr(
        wbsv, "find_compose_file", lambda _cwd: result,
    )


def _install_validate(monkeypatch: pytest.MonkeyPatch, result) -> None:
    def _fake(compose_file, *, autorepair=True, project_root=None):  # noqa: ANN001, ARG001
        if isinstance(result, BaseException):
            raise result
        return list(result)

    monkeypatch.setattr(wbsv, "validate_compose_build_context", _fake)


def _install_docker_build(monkeypatch: pytest.MonkeyPatch, results: list[BuildResult]) -> None:
    def _fake(project_root, compose_file, timeout=600):  # noqa: ANN001, ARG001
        return list(results)

    monkeypatch.setattr(wbsv, "docker_build", _fake)


def test_acceptance_passes_when_build_clean(
    tmp_path: Path, fake_compose: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_find_compose(monkeypatch, fake_compose)
    _install_validate(monkeypatch, [])
    _install_docker_build(
        monkeypatch,
        [
            BuildResult(service="api", success=True, duration_s=1.2),
            BuildResult(service="web", success=True, duration_s=0.8),
        ],
    )

    result = wbsv.run_wave_b_acceptance_test(tmp_path)

    assert result.passed is True
    assert result.violations == []
    assert result.build_failures == []
    assert result.error_summary == ""
    assert result.retry_prompt_suffix == ""


def test_acceptance_fails_when_compose_violation(
    tmp_path: Path, fake_compose: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    viol = Violation(
        service="api",
        source="../outside",
        resolved_path=Path("/abs/outside"),
        reason="escapes context",
    )
    _install_find_compose(monkeypatch, fake_compose)
    _install_validate(monkeypatch, [viol])
    _install_docker_build(
        monkeypatch, [BuildResult(service="api", success=True, duration_s=0.5)],
    )

    result = wbsv.run_wave_b_acceptance_test(tmp_path, autorepair=True)

    assert result.passed is False
    assert result.violations == [viol]
    assert result.build_failures == []
    assert "escapes context" in result.error_summary
    assert "../outside" in result.retry_prompt_suffix


def test_acceptance_fails_when_docker_build_fails(
    tmp_path: Path, fake_compose: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failure = BuildResult(
        service="api",
        success=False,
        error="failed to compute cache key: '/src/missing': not found",
        duration_s=2.1,
    )
    _install_find_compose(monkeypatch, fake_compose)
    _install_validate(monkeypatch, [])
    _install_docker_build(
        monkeypatch,
        [
            BuildResult(service="web", success=True, duration_s=0.4),
            failure,
        ],
    )

    result = wbsv.run_wave_b_acceptance_test(tmp_path)

    assert result.passed is False
    assert result.violations == []
    assert result.build_failures == [failure]
    assert "failed to compute cache key" in result.error_summary
    assert "api" in result.error_summary
    assert "failed to compute cache key" in result.retry_prompt_suffix


def test_acceptance_passes_when_no_compose_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_find_compose(monkeypatch, None)

    called = {"validate": 0, "build": 0}

    def _boom(*_a, **_kw):  # noqa: ANN001, ANN202, ANN003
        called["validate"] += 1
        return []

    def _boom_build(*_a, **_kw):  # noqa: ANN001, ANN202, ANN003
        called["build"] += 1
        return []

    monkeypatch.setattr(wbsv, "validate_compose_build_context", _boom)
    monkeypatch.setattr(wbsv, "docker_build", _boom_build)

    result = wbsv.run_wave_b_acceptance_test(tmp_path)

    assert result.passed is True
    assert result.violations == []
    assert result.build_failures == []
    assert called == {"validate": 0, "build": 0}


def test_retry_prompt_suffix_structure(
    tmp_path: Path, fake_compose: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    viol = Violation(
        service="api",
        source="../escape",
        resolved_path=Path("/abs/escape"),
        reason="escapes context",
    )
    failure = BuildResult(
        service="web", success=False, error="Dockerfile parse error", duration_s=0.1,
    )
    _install_find_compose(monkeypatch, fake_compose)
    _install_validate(monkeypatch, [viol])
    _install_docker_build(monkeypatch, [failure])

    result = wbsv.run_wave_b_acceptance_test(tmp_path)

    assert "<previous_attempt_failed>" in result.retry_prompt_suffix
    assert "</previous_attempt_failed>" in result.retry_prompt_suffix
    assert "escapes context" in result.retry_prompt_suffix
    assert "Dockerfile parse error" in result.retry_prompt_suffix
    assert "apply_patch" in result.retry_prompt_suffix
    assert "docker compose build" in result.retry_prompt_suffix
    # The retry must re-anchor intent: it should NOT carry away the ORIGINAL
    # wave prompt — that concatenation happens in the caller. The helper only
    # owns the suffix.
    assert "REQUIREMENTS" not in result.retry_prompt_suffix


def test_acceptance_treats_compose_sanity_error_as_violations(
    tmp_path: Path, fake_compose: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When autorepair=False, compose sanity raises — helper must NOT propagate."""
    from agent_team_v15.compose_sanity import ComposeSanityError

    viol = Violation(
        service="api",
        source="../x",
        resolved_path=Path("/tmp/x"),
        reason="missing",
    )
    _install_find_compose(monkeypatch, fake_compose)
    _install_validate(monkeypatch, ComposeSanityError([viol]))
    _install_docker_build(monkeypatch, [])

    result = wbsv.run_wave_b_acceptance_test(tmp_path, autorepair=False)

    assert result.passed is False
    assert result.violations == [viol]


def test_build_stderr_is_truncated(
    tmp_path: Path, fake_compose: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    huge = "X" * 5000
    failure = BuildResult(service="api", success=False, error=huge, duration_s=0.1)
    _install_find_compose(monkeypatch, fake_compose)
    _install_validate(monkeypatch, [])
    _install_docker_build(monkeypatch, [failure])

    result = wbsv.run_wave_b_acceptance_test(tmp_path)

    assert result.passed is False
    # Truncated in error_summary and retry_prompt_suffix, not in build_failures.
    assert "truncated" in result.error_summary
    assert len(result.error_summary) < 5000
    assert result.build_failures[0].error == huge

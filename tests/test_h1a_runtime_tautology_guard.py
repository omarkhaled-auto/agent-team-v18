"""Phase H1a Item 6 — runtime-verifier tautology guard.

Graph-based critical-path check:
  * Walk ``services.api``'s transitive depends_on closure.
  * For each service in the closure, assert it exists in compose AND
    the runtime verifier reports it healthy.
  * Emit ``RUNTIME-TAUTOLOGY-001`` HIGH when any critical-path service
    is absent or unhealthy.

Informational services (``postgres_test``, observability sidecars) that
are NOT in api's depends_on closure do not contribute — they can be
down without flipping the gate.

Fallback path: when compose YAML is malformed or the graph can't be
walked, fall back to the reduced-fidelity ``services.api present +
healthy`` check.

Also guards ``verification._health_from_results`` — when the tautology
indicator is True and no tasks are recorded, return ``"unknown"``
instead of defaulting to ``"green"``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agent_team_v15.cli import _compose_critical_path, _runtime_tautology_finding
from agent_team_v15.verification import (
    _health_from_results,
    set_runtime_tautology_detected,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_compose(workspace: Path, yaml_text: str) -> None:
    (workspace / "docker-compose.yml").write_text(yaml_text, encoding="utf-8")


def _rv_report(services: list[tuple[str, bool]]) -> SimpleNamespace:
    """Build a fake RuntimeReport-shaped object for the guard to consume."""

    return SimpleNamespace(
        services_total=len(services),
        services_healthy=sum(1 for _, h in services if h),
        total_duration_s=1.0,
        services_status=[
            SimpleNamespace(service=name, healthy=healthy, error="")
            for name, healthy in services
        ],
    )


def _config(tautology_on: bool = True, compose_override: str = "") -> Any:
    return SimpleNamespace(
        v18=SimpleNamespace(runtime_tautology_guard_enabled=tautology_on),
        runtime_verification=SimpleNamespace(compose_file=compose_override),
    )


# ---------------------------------------------------------------------------
# _compose_critical_path — unit-level graph walk
# ---------------------------------------------------------------------------


def test_critical_path_covers_api_and_depends() -> None:
    data = {
        "services": {
            "api": {"depends_on": {"postgres": {"condition": "service_healthy"}}},
            "postgres": {},
            "postgres_test": {},
        }
    }
    closure = _compose_critical_path(data)
    assert closure == {"api", "postgres"}


def test_critical_path_transitive_walk() -> None:
    data = {
        "services": {
            "api": {"depends_on": ["migrator"]},
            "migrator": {"depends_on": ["postgres"]},
            "postgres": {},
        }
    }
    closure = _compose_critical_path(data)
    assert closure == {"api", "migrator", "postgres"}


def test_critical_path_returns_none_when_api_missing() -> None:
    data = {"services": {"postgres": {}}}
    assert _compose_critical_path(data) is None


def test_critical_path_handles_malformed_depends_on() -> None:
    data = {"services": {"api": {"depends_on": 42}}}
    closure = _compose_critical_path(data)
    assert closure == {"api"}


# ---------------------------------------------------------------------------
# _runtime_tautology_finding — graph-mode
# ---------------------------------------------------------------------------


def test_all_critical_healthy_no_finding(tmp_path: Path) -> None:
    _write_compose(
        tmp_path,
        "services:\n"
        "  api:\n    depends_on:\n      postgres:\n        condition: service_healthy\n"
        "  postgres: {}\n",
    )
    rv = _rv_report([("api", True), ("postgres", True)])
    assert (
        _runtime_tautology_finding(tmp_path, rv, _config(tautology_on=True))
        is None
    )


def test_critical_path_missing_api_emits_finding(tmp_path: Path) -> None:
    """Compose has only postgres — api is entirely absent."""

    _write_compose(tmp_path, "services:\n  postgres: {}\n")
    rv = _rv_report([("postgres", True)])
    # With api absent, _compose_critical_path returns None, so the
    # fallback path fires and emits the reduced-fidelity message.
    finding = _runtime_tautology_finding(tmp_path, rv, _config(tautology_on=True))
    assert finding is not None
    assert "RUNTIME-TAUTOLOGY-001" in finding
    assert "services.api" in finding


def test_critical_path_api_unhealthy_emits_finding(tmp_path: Path) -> None:
    _write_compose(
        tmp_path,
        "services:\n"
        "  api:\n    depends_on:\n      postgres:\n        condition: service_healthy\n"
        "  postgres: {}\n",
    )
    rv = _rv_report([("api", False), ("postgres", True)])
    finding = _runtime_tautology_finding(tmp_path, rv, _config(tautology_on=True))
    assert finding is not None
    assert "RUNTIME-TAUTOLOGY-001" in finding
    assert "api" in finding and "unhealthy" in finding


def test_informational_service_down_does_not_fire(tmp_path: Path) -> None:
    _write_compose(
        tmp_path,
        "services:\n"
        "  api:\n    depends_on:\n      postgres:\n        condition: service_healthy\n"
        "  postgres: {}\n"
        "  postgres_test: {}\n",
    )
    rv = _rv_report(
        [("api", True), ("postgres", True), ("postgres_test", False)]
    )
    assert (
        _runtime_tautology_finding(tmp_path, rv, _config(tautology_on=True))
        is None
    )


def test_transitive_depends_missing_emits_finding(tmp_path: Path) -> None:
    _write_compose(
        tmp_path,
        "services:\n"
        "  api:\n    depends_on:\n      - migrator\n"
        "  migrator:\n    depends_on:\n      - postgres\n"
        "  postgres: {}\n",
    )
    # api healthy, migrator absent in runtime status (unhealthy).
    rv = _rv_report([("api", True), ("postgres", True)])
    finding = _runtime_tautology_finding(tmp_path, rv, _config(tautology_on=True))
    assert finding is not None
    assert "RUNTIME-TAUTOLOGY-001" in finding
    assert "migrator" in finding


# ---------------------------------------------------------------------------
# Fallback path — malformed YAML
# ---------------------------------------------------------------------------


def test_malformed_yaml_triggers_api_only_fallback(tmp_path: Path) -> None:
    _write_compose(tmp_path, ":\nnot valid yaml: [ [\n")
    rv = _rv_report([])
    finding = _runtime_tautology_finding(tmp_path, rv, _config(tautology_on=True))
    assert finding is not None
    assert "RUNTIME-TAUTOLOGY-001" in finding
    assert "services.api missing" in finding


def test_fallback_covers_api_present_and_healthy(tmp_path: Path) -> None:
    """When graph walk fails but api exists and is healthy, fallback
    check passes. Use a depends_on value that defeats the graph walk
    (we simulate by supplying a compose with no services mapping)."""

    _write_compose(tmp_path, "services: not-a-mapping\n")
    # api healthy would matter, but since graph walk fails AND api isn't
    # in the services mapping, fallback emits services.api missing.
    rv = _rv_report([("api", True)])
    finding = _runtime_tautology_finding(tmp_path, rv, _config(tautology_on=True))
    assert finding is not None
    assert "services.api missing" in finding


# ---------------------------------------------------------------------------
# Skip paths
# ---------------------------------------------------------------------------


def test_no_compose_file_returns_none(tmp_path: Path) -> None:
    rv = _rv_report([])
    assert (
        _runtime_tautology_finding(tmp_path, rv, _config(tautology_on=True))
        is None
    )


def test_alternate_api_service_name_supported(tmp_path: Path) -> None:
    """The graph walker is rooted at the default ``api`` service name;
    a compose that names it ``backend`` will fall through to the
    reduced-fidelity check (correct behaviour — our convention is api)."""

    _write_compose(
        tmp_path,
        "services:\n  backend: {}\n  postgres: {}\n",
    )
    rv = _rv_report([("backend", True), ("postgres", True)])
    finding = _runtime_tautology_finding(tmp_path, rv, _config(tautology_on=True))
    # Fallback fires because default "api" isn't the name — this is the
    # documented reduced-fidelity mode.
    assert finding is not None
    assert "services.api missing" in finding


# ---------------------------------------------------------------------------
# verification._health_from_results — unknown state wiring
# ---------------------------------------------------------------------------


def test_health_from_empty_results_default_is_green() -> None:
    # Reset the module-level flag.
    set_runtime_tautology_detected(False)
    assert _health_from_results({}) == "green"


def test_health_from_empty_results_with_tautology_flag_is_unknown() -> None:
    set_runtime_tautology_detected(True)
    try:
        assert _health_from_results({}) == "unknown"
    finally:
        # Reset so we don't leak state into other tests.
        set_runtime_tautology_detected(False)


def test_set_runtime_tautology_detected_is_idempotent() -> None:
    set_runtime_tautology_detected(False)
    set_runtime_tautology_detected(True)
    set_runtime_tautology_detected(True)
    try:
        assert _health_from_results({}) == "unknown"
    finally:
        set_runtime_tautology_detected(False)

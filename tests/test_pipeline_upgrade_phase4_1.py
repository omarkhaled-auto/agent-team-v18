"""Phase 4.1 of the pipeline upgrade — wave self-verify scope-narrowing.

Plan: ``docs/plans/2026-04-26-pipeline-upgrade-phase4.md`` §D.

Phase 4.1 narrows each wave's in-wave acceptance test (``docker compose
build``) to only the service that wave is responsible for: Wave B builds
``api`` only, Wave D builds ``web`` only, Wave T (full e2e) builds the
full stack. The 2026-04-26 M1 hardening smoke
(``v18 test runs/m1-hardening-smoke-20260426-173745/``) shows Wave B
retried 3 times graded on the FULL compose, with retry-2 failing only on
``service=web`` — a deliverable Wave B was never responsible for. Phase
4.1 closes Risk #23.

The test file is the spec: each fixture asserts one acceptance criterion
from §D AC1..AC6 of the plan. All fixtures load real artifacts from
``tests/fixtures/smoke_2026_04_26/`` (frozen by Phase 4.1 per §0.2 step
4 and §M.8).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "smoke_2026_04_26"


# ---------------------------------------------------------------------------
# Resolver-level tests (`_resolve_per_wave_service_target`)
# ---------------------------------------------------------------------------


def test_resolve_per_wave_service_target_default_mapping() -> None:
    """Default wave-letter → service mapping when no STACK_CONTRACT override."""
    from agent_team_v15.wave_b_self_verify import _resolve_per_wave_service_target

    assert _resolve_per_wave_service_target("B") == ["api"]
    assert _resolve_per_wave_service_target("D") == ["web"]
    assert _resolve_per_wave_service_target("T") == ["api", "web"]
    # Waves that don't run docker self-verify get empty list.
    for wave in ("A", "A5", "C", "scaffold"):
        assert _resolve_per_wave_service_target(wave) == [], wave


def test_resolve_per_wave_service_target_returns_fresh_list_each_call() -> None:
    """Caller mutating the returned list must NOT mutate module-level state."""
    from agent_team_v15.wave_b_self_verify import _resolve_per_wave_service_target

    first = _resolve_per_wave_service_target("B")
    first.append("contaminated")
    second = _resolve_per_wave_service_target("B")
    assert second == ["api"]


def test_resolve_per_wave_service_target_honors_explicit_stack_contract_override() -> None:
    """``wave_self_verify_services`` field on STACK_CONTRACT overrides defaults."""
    from agent_team_v15.wave_b_self_verify import _resolve_per_wave_service_target

    contract = {
        "wave_self_verify_services": {
            "B": ["api-srv"],
            "D": ["web-srv", "edge"],
            "T": ["api-srv", "web-srv"],
        }
    }
    assert _resolve_per_wave_service_target("B", contract) == ["api-srv"]
    assert _resolve_per_wave_service_target("D", contract) == ["web-srv", "edge"]
    assert _resolve_per_wave_service_target("T", contract) == ["api-srv", "web-srv"]


def test_resolve_per_wave_service_target_derives_from_path_prefixes() -> None:
    """When override absent, derive service names from backend/frontend prefixes."""
    from agent_team_v15.wave_b_self_verify import _resolve_per_wave_service_target

    contract = {
        "backend_path_prefix": "services/backend/",
        "frontend_path_prefix": "services/frontend/",
    }
    assert _resolve_per_wave_service_target("B", contract) == ["backend"]
    assert _resolve_per_wave_service_target("D", contract) == ["frontend"]
    assert _resolve_per_wave_service_target("T", contract) == ["backend", "frontend"]


def test_resolve_per_wave_service_target_smoke_stack_contract() -> None:
    """The 2026-04-26 smoke's STACK_CONTRACT.json drives canonical api/web names."""
    from agent_team_v15.wave_b_self_verify import _resolve_per_wave_service_target

    contract = json.loads(
        (FIXTURE_ROOT / "STACK_CONTRACT.json").read_text(encoding="utf-8")
    )
    # The smoke's contract has backend_path_prefix=apps/api/ and
    # frontend_path_prefix=apps/web/ which derive to api / web — matching
    # the actual compose service names (frozen docker-compose.yml).
    assert _resolve_per_wave_service_target("B", contract) == ["api"]
    assert _resolve_per_wave_service_target("D", contract) == ["web"]


# ---------------------------------------------------------------------------
# `docker_build` services-arg propagation
# ---------------------------------------------------------------------------


def test_docker_build_passes_services_to_compose_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When ``services`` is non-None, argv ends with the service names."""
    from agent_team_v15 import runtime_verification as rv

    captured: list[tuple[str, ...]] = []

    def fake_run_docker(*args: str, cwd: str | None = None, timeout: int = 600):
        captured.append(args)
        if "config" in args:
            return (0, "api\nweb\npostgres\n", "")
        return (0, "Successfully built\n", "")

    monkeypatch.setattr(rv, "_run_docker", fake_run_docker)
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")

    results = rv.docker_build(tmp_path, compose, services=["api"])

    # First call discovers services; second is the build.
    assert any("config" in c for c in captured)
    build_calls = [c for c in captured if "build" in c]
    assert len(build_calls) == 1
    assert build_calls[0][-1] == "api"
    # Result list is per-service (only the targeted services).
    assert [r.service for r in results] == ["api"]
    assert all(r.success for r in results)


def test_docker_build_passes_multiple_services(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Multiple services (Wave T contract) are both passed verbatim."""
    from agent_team_v15 import runtime_verification as rv

    captured: list[tuple[str, ...]] = []

    def fake_run_docker(*args: str, cwd: str | None = None, timeout: int = 600):
        captured.append(args)
        if "config" in args:
            return (0, "api\nweb\npostgres\n", "")
        return (0, "Successfully built\n", "")

    monkeypatch.setattr(rv, "_run_docker", fake_run_docker)
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")

    rv.docker_build(tmp_path, compose, services=["api", "web"])

    build_call = next(c for c in captured if "build" in c)
    # Last two positional args are the service names, in order.
    assert build_call[-2:] == ("api", "web")


def test_docker_build_without_services_keeps_legacy_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``services=None`` (default) preserves the all-service build behaviour."""
    from agent_team_v15 import runtime_verification as rv

    captured: list[tuple[str, ...]] = []

    def fake_run_docker(*args: str, cwd: str | None = None, timeout: int = 600):
        captured.append(args)
        if "config" in args:
            return (0, "api\nweb\npostgres\n", "")
        return (0, "Successfully built\n", "")

    monkeypatch.setattr(rv, "_run_docker", fake_run_docker)
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")

    rv.docker_build(tmp_path, compose)

    build_call = next(c for c in captured if "build" in c)
    # No service names at the tail; `--parallel` is the last token.
    assert build_call[-1] == "--parallel"


def test_docker_build_filters_unknown_service_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unknown service names in the requested list are silently dropped.

    Wave D's mapping prescribes ``["web"]`` but a backend-only milestone
    may ship a compose file with no ``web`` service. Passing the
    unknown name verbatim would make ``docker compose build`` fail with
    "no such service"; instead the filter returns an empty result.
    """
    from agent_team_v15 import runtime_verification as rv

    def fake_run_docker(*args: str, cwd: str | None = None, timeout: int = 600):
        if "config" in args:
            return (0, "api\npostgres\n", "")
        return (0, "Successfully built\n", "")

    monkeypatch.setattr(rv, "_run_docker", fake_run_docker)
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")

    results = rv.docker_build(tmp_path, compose, services=["web"])
    assert results == []


# ---------------------------------------------------------------------------
# Wave B self-verify narrowing — AC1, AC4, AC5
# ---------------------------------------------------------------------------


def _patch_wave_b_environment(
    monkeypatch: pytest.MonkeyPatch,
    captured: list[tuple[str, ...]],
    *,
    failing_services: tuple[str, ...] = (),
) -> None:
    """Common stub: docker available, compose discovered, validate clean.

    ``captured`` collects every argv passed to ``_run_docker`` so the test
    can assert which services were targeted.
    """
    from agent_team_v15 import runtime_verification as rv
    from agent_team_v15 import wave_b_self_verify as wbsv

    monkeypatch.setattr(wbsv, "check_docker_available", lambda: True)
    monkeypatch.setattr(
        wbsv, "validate_compose_build_context",
        lambda *a, **kw: [],
    )

    def fake_run_docker(*args: str, cwd: str | None = None, timeout: int = 600):
        captured.append(args)
        if "config" in args:
            return (0, "api\nweb\npostgres\n", "")
        # Simulate per-service failure when the build call targets a
        # service in failing_services.
        if failing_services and any(svc in args for svc in failing_services):
            return (1, "", f"target {failing_services[0]}: failed to solve: exit 1")
        return (0, "Successfully built\n", "")

    monkeypatch.setattr(rv, "_run_docker", fake_run_docker)


def test_wave_b_self_verify_runs_only_api_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC1: Wave B self-verify spawns ``docker compose build api`` (not full)."""
    from agent_team_v15 import wave_b_self_verify as wbsv

    captured: list[tuple[str, ...]] = []
    _patch_wave_b_environment(monkeypatch, captured)
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")

    result = wbsv.run_wave_b_acceptance_test(tmp_path)

    build_calls = [c for c in captured if "build" in c]
    assert len(build_calls) == 1
    assert build_calls[0][-1] == "api", build_calls[0]
    assert result.passed is True


def test_wave_b_self_verify_failure_message_includes_service_attribution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC4: per-wave self-verify failure carries ``service=<name>`` in the summary.

    Phase 4.2 will consume this attribution. Phase 4.1 just preserves it.
    """
    from agent_team_v15 import wave_b_self_verify as wbsv

    captured: list[tuple[str, ...]] = []
    _patch_wave_b_environment(
        monkeypatch, captured, failing_services=("api",),
    )
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")

    result = wbsv.run_wave_b_acceptance_test(tmp_path)

    assert result.passed is False
    assert any(br.service == "api" for br in result.build_failures)
    assert "service=api" in result.error_summary


def test_wave_b_self_verify_disabled_falls_back_to_full_compose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC5: ``narrow_services=False`` restores the legacy all-services build."""
    from agent_team_v15 import wave_b_self_verify as wbsv

    captured: list[tuple[str, ...]] = []
    _patch_wave_b_environment(monkeypatch, captured)
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")

    wbsv.run_wave_b_acceptance_test(tmp_path, narrow_services=False)

    build_call = next(c for c in captured if "build" in c)
    # Legacy shape: trailing token is ``--parallel`` (no service names).
    assert build_call[-1] == "--parallel"


def test_wave_b_self_verify_skipped_when_compose_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defensive: helper short-circuits cleanly when no compose file exists.

    Mirrors the existing contract in
    ``tests/wave_executor/test_wave_b_self_verify.py``: no compose →
    ``passed=True`` and zero docker invocations. Phase 4.1 must not regress
    this path.
    """
    from agent_team_v15 import runtime_verification as rv
    from agent_team_v15 import wave_b_self_verify as wbsv

    monkeypatch.setattr(wbsv, "check_docker_available", lambda: True)
    monkeypatch.setattr(wbsv, "find_compose_file", lambda _cwd: None)

    docker_calls: list[tuple] = []

    def fake_run_docker(*args: str, **kwargs: Any):
        docker_calls.append(args)
        return (0, "", "")

    monkeypatch.setattr(rv, "_run_docker", fake_run_docker)

    result = wbsv.run_wave_b_acceptance_test(tmp_path)
    assert result.passed is True
    assert docker_calls == []


# ---------------------------------------------------------------------------
# Wave D self-verify (NEW module)
# ---------------------------------------------------------------------------


def test_wave_d_self_verify_module_exposes_acceptance_test_and_result() -> None:
    """The new module exports ``run_wave_d_acceptance_test`` + ``WaveDVerifyResult``."""
    from agent_team_v15 import wave_d_self_verify as wdsv

    assert hasattr(wdsv, "run_wave_d_acceptance_test")
    assert hasattr(wdsv, "WaveDVerifyResult")


def test_wave_d_self_verify_runs_only_web_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC2: Wave D self-verify spawns ``docker compose build web`` only."""
    from agent_team_v15 import runtime_verification as rv
    from agent_team_v15 import wave_d_self_verify as wdsv

    monkeypatch.setattr(wdsv, "check_docker_available", lambda: True)
    monkeypatch.setattr(
        wdsv, "validate_compose_build_context", lambda *a, **kw: [],
    )

    captured: list[tuple[str, ...]] = []

    def fake_run_docker(*args: str, cwd: str | None = None, timeout: int = 600):
        captured.append(args)
        if "config" in args:
            return (0, "api\nweb\npostgres\n", "")
        return (0, "Successfully built\n", "")

    monkeypatch.setattr(rv, "_run_docker", fake_run_docker)
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")

    result = wdsv.run_wave_d_acceptance_test(tmp_path)

    build_calls = [c for c in captured if "build" in c]
    assert len(build_calls) == 1
    assert build_calls[0][-1] == "web"
    assert result.passed is True


def test_wave_d_self_verify_failure_carries_service_attribution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wave D failure surfaces ``service=web`` for downstream forensics."""
    from agent_team_v15 import runtime_verification as rv
    from agent_team_v15 import wave_d_self_verify as wdsv

    monkeypatch.setattr(wdsv, "check_docker_available", lambda: True)
    monkeypatch.setattr(
        wdsv, "validate_compose_build_context", lambda *a, **kw: [],
    )

    def fake_run_docker(*args: str, cwd: str | None = None, timeout: int = 600):
        if "config" in args:
            return (0, "api\nweb\npostgres\n", "")
        if "web" in args:
            return (1, "", "target web: failed to solve: exit 1")
        return (0, "Successfully built\n", "")

    monkeypatch.setattr(rv, "_run_docker", fake_run_docker)
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")

    result = wdsv.run_wave_d_acceptance_test(tmp_path)
    assert result.passed is False
    assert any(br.service == "web" for br in result.build_failures)
    assert "service=web" in result.error_summary


def test_wave_d_self_verify_skipped_when_compose_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defensive: Wave D helper returns passed=True for no-docker milestones."""
    from agent_team_v15 import runtime_verification as rv
    from agent_team_v15 import wave_d_self_verify as wdsv

    monkeypatch.setattr(wdsv, "check_docker_available", lambda: True)
    monkeypatch.setattr(wdsv, "find_compose_file", lambda _cwd: None)

    docker_calls: list[tuple] = []

    def fake_run_docker(*args: str, **kwargs: Any):
        docker_calls.append(args)
        return (0, "", "")

    monkeypatch.setattr(rv, "_run_docker", fake_run_docker)

    result = wdsv.run_wave_d_acceptance_test(tmp_path)
    assert result.passed is True
    assert docker_calls == []


def test_wave_d_self_verify_env_unavailable_short_circuits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wave D mirrors Wave B's env_unavailable contract for daemon-down."""
    from agent_team_v15 import wave_d_self_verify as wdsv

    monkeypatch.setattr(wdsv, "check_docker_available", lambda: False)
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr(wdsv, "find_compose_file", lambda _cwd: compose)

    result = wdsv.run_wave_d_acceptance_test(tmp_path)
    assert result.passed is False
    assert result.env_unavailable is True


# ---------------------------------------------------------------------------
# Wave T full-stack contract — AC3
# ---------------------------------------------------------------------------


def test_wave_t_resolver_returns_full_stack_services() -> None:
    """AC3: Wave T's resolver result builds the full stack (api + web)."""
    from agent_team_v15.wave_b_self_verify import _resolve_per_wave_service_target

    assert _resolve_per_wave_service_target("T") == ["api", "web"]


def test_full_compose_build_path_unchanged_when_services_omitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC3 corollary: Phase 6 runtime-verification path (no services arg)
    preserves the all-services build. The existing call shape used by
    ``runtime_verification.run_runtime_verification`` and
    ``endpoint_prober.start_docker_for_probing`` must NOT regress.
    """
    from agent_team_v15 import runtime_verification as rv

    captured: list[tuple[str, ...]] = []

    def fake_run_docker(*args: str, cwd: str | None = None, timeout: int = 600):
        captured.append(args)
        if "config" in args:
            return (0, "api\nweb\npostgres\n", "")
        return (0, "Successfully built\n", "")

    monkeypatch.setattr(rv, "_run_docker", fake_run_docker)
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")

    rv.docker_build(tmp_path, compose)

    build_call = next(c for c in captured if "build" in c)
    # No service-name positional after --parallel.
    assert "api" not in build_call
    assert "web" not in build_call


# ---------------------------------------------------------------------------
# AC6 replay — smoke evidence drives the data-driven proof
# ---------------------------------------------------------------------------


def test_replay_smoke_2026_04_26_resolver_yields_api_for_wave_b() -> None:
    """AC6 (a): the resolver applied to the smoke's STACK_CONTRACT yields
    ``["api"]`` for Wave B — locking the data-driven proof that Phase 4.1's
    narrowing aligns with the smoke's actual compose service-name layout.
    """
    from agent_team_v15.wave_b_self_verify import _resolve_per_wave_service_target

    contract = json.loads(
        (FIXTURE_ROOT / "STACK_CONTRACT.json").read_text(encoding="utf-8")
    )
    assert _resolve_per_wave_service_target("B", contract) == ["api"]


def test_replay_smoke_2026_04_26_retry_2_passes_under_narrowed_self_verify() -> None:
    """AC6 (b): had Phase 4.1 been live during the 2026-04-26 smoke, retry
    2 of Wave B (which got ``service=api`` passing — the only failure was
    on ``service=web``, Wave D's deliverable) would have been declared
    Wave B self-verify PASSED.

    The data-driven proof is in WAVE_FINDINGS.json: each Wave B retry
    entry records ``file: <service>`` for the failing service. retry=2's
    failure is ``file: "web"`` — outside Wave B's narrowed scope, so
    Phase 4.1's per-service self-verify on ``api`` would have observed
    no failure on retry 2 and the milestone would have advanced to Wave D.
    """
    findings = json.loads(
        (FIXTURE_ROOT / "WAVE_FINDINGS.json").read_text(encoding="utf-8")
    )
    wave_b_entries = [
        f for f in findings["findings"]
        if f.get("wave") == "B" and f.get("code") == "WAVE-B-SELF-VERIFY"
    ]
    assert len(wave_b_entries) == 3, wave_b_entries

    # Parse retry index from each message's leading "retry=N" prefix.
    by_retry: dict[int, str] = {}
    for entry in wave_b_entries:
        msg = entry.get("message", "")
        # message starts with "retry=N violations=…"; pull retry id.
        retry_id = int(msg.split(" ", 1)[0].split("=", 1)[1])
        by_retry[retry_id] = entry.get("file", "")

    assert by_retry == {0: "api", 1: "api", 2: "web"}

    # Phase 4.1 narrows Wave B's self-verify to ["api"]. retry=2's only
    # failure is on "web", outside Wave B's scope — narrowed self-verify
    # would have seen no api failure and declared retry-2 passed.
    failing_services_at_retry_2 = {by_retry[2]}
    wave_b_targets = {"api"}
    assert failing_services_at_retry_2.isdisjoint(wave_b_targets), (
        "Phase 4.1 contract: retry-2 of Wave B failed only on services "
        "outside Wave B's narrowed scope — should be declared passed"
    )


# ---------------------------------------------------------------------------
# Config flag — AC5 master kill switch
# ---------------------------------------------------------------------------


def test_audit_team_config_per_wave_self_verify_enabled_default_true() -> None:
    """``AuditTeamConfig.per_wave_self_verify_enabled`` defaults to True.

    AC5 contract: the flag is the master kill switch; default-True means
    Phase 4.1 narrowing is active out of the box. Operators can flip to
    False via config to restore the pre-Phase-4.1 full-compose behaviour.
    """
    from agent_team_v15.config import AuditTeamConfig

    cfg = AuditTeamConfig()
    assert hasattr(cfg, "per_wave_self_verify_enabled")
    assert cfg.per_wave_self_verify_enabled is True


def test_runtime_verification_wave_d_self_verify_flags_default_on() -> None:
    """Wave D self-verify enablement mirrors Wave B's defaults.

    Phase 4.1 introduces a brand-new dispatch site for Wave D, so it
    needs its own ``wave_d_self_verify_enabled`` and
    ``wave_d_self_verify_max_retries`` mirrors of the existing Wave B
    pair on RuntimeVerificationConfig.
    """
    from agent_team_v15.config import RuntimeVerificationConfig

    cfg = RuntimeVerificationConfig()
    assert getattr(cfg, "wave_d_self_verify_enabled", None) is True
    assert getattr(cfg, "wave_d_self_verify_max_retries", None) == 2

"""tests/test_pipeline_upgrade_phase5_6.py — Phase 5.6 unified build gate.

Plan: ``docs/plans/2026-04-28-phase-5-quality-milestone.md`` §I + §M.M5.

Closes:

* **R-#39** — compile-fix vs acceptance-test build-check divergence.
* **R-#40** — compile-fix has no Phase 4.2 retry feedback.
* **R-#44** — build-check scope (wave-scope per-service vs project-scope
  all-services Docker build).

This module covers the AC1-AC4 + AC6 + AC7 fixtures from §I.5 + the
deferred-AC8 source-level contract + the `_run_wave_compile` shim
contract + the `_build_compile_fix_prompt` retry-payload round-trip +
the §M.M5 HINT suffix lint contract + the sync-bridge isolation.

AC5 / AC5a / AC8 LIVE smoke contracts are deferred to the closeout-
smoke checklist per dispatch direction.
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Fixtures + mocks
# ---------------------------------------------------------------------------


def _make_build_result(service: str, success: bool, error: str = "") -> Any:
    from agent_team_v15.runtime_verification import BuildResult

    return BuildResult(
        service=service,
        success=success,
        duration_s=1.0,
        error=error,
    )


def _make_compile_result(
    *,
    passed: bool,
    errors: list[dict[str, Any]] | None = None,
) -> Any:
    from agent_team_v15.compile_profiles import CompileResult

    errs = list(errors or [])
    return CompileResult(
        passed=passed,
        error_count=len(errs),
        errors=errs,
    )


def _patch_wave_d_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tmp_path: Path,
    docker_available: bool = True,
    diagnostic_results: list[Any] | None = None,
    project_results: list[Any] | None = None,
    compile_result: Any | None = None,
) -> dict[str, list[Any]]:
    """Patch the Wave D acceptance helper's environment.

    Returns a captured-calls dict so fixtures can assert on call count
    and argument shape:
        captured["docker_calls"] — list of ``services`` kwargs passed to
            ``docker_build`` (one per call). ``services=None`` means the
            project-scope all-services build.
        captured["compile_calls"] — list of kwargs passed to
            ``run_compile_profile_sync``.
    """
    from agent_team_v15 import wave_d_self_verify as wdsv
    from agent_team_v15 import unified_build_gate as ubg

    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text("services: {}\n", encoding="utf-8")

    captured: dict[str, list[Any]] = {
        "docker_calls": [],
        "compile_calls": [],
    }

    monkeypatch.setattr(wdsv, "find_compose_file", lambda _cwd: compose_file)
    monkeypatch.setattr(wdsv, "check_docker_available", lambda: docker_available)
    monkeypatch.setattr(
        wdsv, "validate_compose_build_context", lambda *a, **kw: [],
    )

    diag = list(diagnostic_results or [_make_build_result("web", True)])
    proj = list(project_results or [_make_build_result("web", True)])

    def fake_docker_build(*args, **kwargs):
        services = kwargs.get("services")
        captured["docker_calls"].append(services)
        if services is None:
            return list(proj)
        return list(diag)

    monkeypatch.setattr(wdsv, "docker_build", fake_docker_build)

    cr = compile_result if compile_result is not None else _make_compile_result(passed=True)

    def fake_run_compile(**kwargs):
        captured["compile_calls"].append(kwargs)
        return cr

    monkeypatch.setattr(ubg, "run_compile_profile_sync", fake_run_compile)

    return captured


def _patch_wave_b_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tmp_path: Path,
    docker_available: bool = True,
    diagnostic_results: list[Any] | None = None,
    project_results: list[Any] | None = None,
    compile_result: Any | None = None,
) -> dict[str, list[Any]]:
    """Wave B mirror of ``_patch_wave_d_env``."""
    from agent_team_v15 import wave_b_self_verify as wbsv
    from agent_team_v15 import unified_build_gate as ubg

    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text("services: {}\n", encoding="utf-8")

    captured: dict[str, list[Any]] = {
        "docker_calls": [],
        "compile_calls": [],
    }

    monkeypatch.setattr(wbsv, "find_compose_file", lambda _cwd: compose_file)
    monkeypatch.setattr(wbsv, "check_docker_available", lambda: docker_available)
    monkeypatch.setattr(
        wbsv, "validate_compose_build_context", lambda *a, **kw: [],
    )

    diag = list(diagnostic_results or [_make_build_result("api", True)])
    proj = list(project_results or [_make_build_result("api", True)])

    def fake_docker_build(*args, **kwargs):
        services = kwargs.get("services")
        captured["docker_calls"].append(services)
        if services is None:
            return list(proj)
        return list(diag)

    monkeypatch.setattr(wbsv, "docker_build", fake_docker_build)

    cr = compile_result if compile_result is not None else _make_compile_result(passed=True)

    def fake_run_compile(**kwargs):
        captured["compile_calls"].append(kwargs)
        return cr

    monkeypatch.setattr(ubg, "run_compile_profile_sync", fake_run_compile)

    return captured


# ---------------------------------------------------------------------------
# AC1 — TSC + project-scope Docker pass → passed=True
# ---------------------------------------------------------------------------


def test_ac1_wave_d_tsc_and_project_docker_both_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC1: when compile profile + project-scope Docker both pass,
    Wave D acceptance passes overall."""
    from agent_team_v15.wave_d_self_verify import run_wave_d_acceptance_test

    captured = _patch_wave_d_env(monkeypatch, tmp_path=tmp_path)

    result = run_wave_d_acceptance_test(tmp_path)

    assert result.passed is True
    assert result.tsc_failures == []
    assert result.project_build_failures == []
    assert result.tsc_env_unavailable is False
    # Two docker_build calls: 5.6a wave-scope (services=["web"]) and
    # 5.6b project-scope (services=None).
    assert captured["docker_calls"] == [["web"], None]
    # Compile profile fired once.
    assert len(captured["compile_calls"]) == 1


# ---------------------------------------------------------------------------
# AC2 — TSC fails, project-scope Docker passes → passed=False
# ---------------------------------------------------------------------------


def test_ac2_wave_d_tsc_fails_docker_passes_passed_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC2: TSC reports real errors; Docker is clean. ``passed=False``,
    ``tsc_failures`` populated, retry suffix carries structured TS data."""
    from agent_team_v15.wave_d_self_verify import run_wave_d_acceptance_test

    tsc_errors = [
        {
            "file": "apps/web/src/page.tsx",
            "line": 42,
            "code": "TS2304",
            "message": "Cannot find name 'foo'.",
        },
        {
            "file": "apps/web/src/api.ts",
            "line": 12,
            "code": "TS2345",
            "message": "Argument type 'string' is not assignable to 'number'.",
        },
    ]
    _patch_wave_d_env(
        monkeypatch,
        tmp_path=tmp_path,
        compile_result=_make_compile_result(passed=False, errors=tsc_errors),
    )

    result = run_wave_d_acceptance_test(tmp_path)

    assert result.passed is False
    assert result.tsc_env_unavailable is False
    # Both TS errors land in the projected list.
    assert len(result.tsc_failures) == 2
    assert "apps/web/src/page.tsx:42 TS2304" in result.tsc_failures[0]
    # Retry suffix carries the canonical tsc-shape so the Phase 4.2
    # extractor will re-derive structured errors on the consumer side.
    assert "TS2304" in result.retry_prompt_suffix
    assert "TS2345" in result.retry_prompt_suffix


# ---------------------------------------------------------------------------
# AC3 — Docker fails, TSC passes → passed=False
# ---------------------------------------------------------------------------


def test_ac3_wave_d_project_docker_fails_tsc_passes_passed_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC3: project-scope all-services Docker build fails; TSC clean.
    ``passed=False``; ``project_build_failures`` populated."""
    from agent_team_v15.wave_d_self_verify import run_wave_d_acceptance_test

    project_failure = _make_build_result(
        "api",
        success=False,
        error=(
            "target api: failed to solve: process "
            "\"pnpm install --frozen-lockfile\" did not complete successfully: "
            "exit code: 1"
        ),
    )
    _patch_wave_d_env(
        monkeypatch,
        tmp_path=tmp_path,
        diagnostic_results=[_make_build_result("web", True)],
        project_results=[
            _make_build_result("web", True),
            project_failure,
        ],
    )

    result = run_wave_d_acceptance_test(tmp_path)

    assert result.passed is False
    assert result.tsc_failures == []
    assert result.tsc_env_unavailable is False
    # Project-scope failure surfaces in the dedicated field.
    assert len(result.project_build_failures) == 1
    assert result.project_build_failures[0].service == "api"
    # Wave-scope diagnostic was clean (the M2 narrow-pass / broad-fail
    # shape — Phase 4.1 service still passed; the project-scope
    # authoritative gate caught the lockfile divergence).
    assert result.build_failures == []
    # Retry suffix labels the project-scope failure authoritative.
    assert "project-scope" in result.retry_prompt_suffix.lower()


# ---------------------------------------------------------------------------
# AC4 — TSC env-unavailable + Docker fails → wave fails on Docker
#       (env_unavailable does NOT suppress Docker failure)
# ---------------------------------------------------------------------------


def test_ac4_tsc_env_unavailable_does_not_suppress_project_docker_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC4 (corrected per scope check-in): TSC env-unavailability MUST
    NOT suppress a project-scope Docker failure. The ``tsc_env_unavailable``
    field is distinct from ``env_unavailable``; a wave can fail on Docker
    even when TSC was env-skipped."""
    from agent_team_v15.wave_d_self_verify import run_wave_d_acceptance_test

    # Compile profile reports ENV_NOT_READY (e.g. pnpm not installed).
    env_unavailable_compile = _make_compile_result(
        passed=False,
        errors=[
            {
                "file": "",
                "line": 0,
                "code": "ENV_NOT_READY",
                "message": "TypeScript not installed locally.",
            },
        ],
    )
    project_failure = _make_build_result(
        "api",
        success=False,
        error="target api: failed to solve",
    )
    _patch_wave_d_env(
        monkeypatch,
        tmp_path=tmp_path,
        project_results=[
            _make_build_result("web", True),
            project_failure,
        ],
        compile_result=env_unavailable_compile,
    )

    result = run_wave_d_acceptance_test(tmp_path)

    # Wave fails on the project-scope Docker failure, regardless of
    # TSC env-unavailability.
    assert result.passed is False
    assert result.tsc_env_unavailable is True
    # tsc_failures is empty because env-unavailability does NOT propagate
    # as real TSC failures.
    assert result.tsc_failures == []
    # Project-scope Docker failure still surfaces — independent of TSC.
    assert len(result.project_build_failures) == 1
    assert result.project_build_failures[0].service == "api"


def test_ac4b_tsc_env_unavailable_with_docker_passing_lets_wave_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC4b: TSC env-unavailable AND project-scope Docker pass → wave
    accepts. ``tsc_env_unavailable=True`` surfaces operator signal but
    does NOT block the wave on its own (it's a env signal, not a code
    defect)."""
    from agent_team_v15.wave_d_self_verify import run_wave_d_acceptance_test

    env_unavailable_compile = _make_compile_result(
        passed=False,
        errors=[
            {
                "file": "",
                "line": 0,
                "code": "MISSING_COMMAND",
                "message": "Command not found: tsc",
            },
        ],
    )
    _patch_wave_d_env(
        monkeypatch,
        tmp_path=tmp_path,
        compile_result=env_unavailable_compile,
    )

    result = run_wave_d_acceptance_test(tmp_path)

    assert result.passed is True
    assert result.tsc_env_unavailable is True
    assert result.tsc_failures == []
    assert result.project_build_failures == []


# ---------------------------------------------------------------------------
# AC6 — kill switch byte-identical to pre-Phase-5.6
# ---------------------------------------------------------------------------


def test_ac6_kill_switch_skips_project_scope_and_compile_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC6: ``tsc_strict_enabled=False`` skips BOTH 5.6b project-scope
    Docker AND 5.6c compile profile. Only the 5.6a wave-scope diagnostic
    runs — byte-identical to pre-Phase-5.6 behaviour."""
    from agent_team_v15.wave_d_self_verify import run_wave_d_acceptance_test

    captured = _patch_wave_d_env(monkeypatch, tmp_path=tmp_path)

    result = run_wave_d_acceptance_test(tmp_path, tsc_strict_enabled=False)

    assert result.passed is True
    # ONLY one docker call (5.6a wave-scope, services=["web"]).
    # 5.6b project-scope and 5.6c compile profile both skipped.
    assert captured["docker_calls"] == [["web"]]
    assert captured["compile_calls"] == []
    assert result.tsc_env_unavailable is False
    assert result.tsc_failures == []
    assert result.project_build_failures == []


# ---------------------------------------------------------------------------
# AC7 — Wave B mirror (project-scope Docker + strict compile both gate
#       through ``tsc_strict_enabled``)
# ---------------------------------------------------------------------------


def test_ac7_wave_b_unified_gate_mirror_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC7: Wave B unified gate mirrors Wave D — both checks pass →
    Wave B accepts."""
    from agent_team_v15.wave_b_self_verify import run_wave_b_acceptance_test

    captured = _patch_wave_b_env(monkeypatch, tmp_path=tmp_path)

    result = run_wave_b_acceptance_test(tmp_path)

    assert result.passed is True
    # Wave-scope narrows to ["api"]; project-scope is services=None.
    assert captured["docker_calls"] == [["api"], None]
    assert len(captured["compile_calls"]) == 1


def test_ac7_wave_b_project_docker_fail_mirrors_wave_d(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC7: Wave B project-scope Docker failure surfaces same shape as
    Wave D's M2 narrow-pass / broad-fail."""
    from agent_team_v15.wave_b_self_verify import run_wave_b_acceptance_test

    _patch_wave_b_env(
        monkeypatch,
        tmp_path=tmp_path,
        diagnostic_results=[_make_build_result("api", True)],
        project_results=[
            _make_build_result("api", True),
            _make_build_result(
                "web",
                success=False,
                error="target web: failed to solve",
            ),
        ],
    )

    result = run_wave_b_acceptance_test(tmp_path)

    assert result.passed is False
    assert result.build_failures == []  # 5.6a wave-scope was clean
    assert len(result.project_build_failures) == 1
    assert result.project_build_failures[0].service == "web"


# ---------------------------------------------------------------------------
# `_run_wave_compile` external contract preservation
# ---------------------------------------------------------------------------


def test_run_wave_compile_external_contract_preserved_phase_5_6() -> None:
    """Phase 5.6 §M.M16 — ``_run_wave_compile`` external contract must
    NOT change (deletion is deferred to follow-up commit). Locks the
    function name + signature shape."""
    from agent_team_v15 import wave_executor

    fn = getattr(wave_executor, "_run_wave_compile", None)
    assert fn is not None, "_run_wave_compile must remain defined in Phase 5.6"
    assert inspect.iscoroutinefunction(fn), "_run_wave_compile must remain async"

    sig = inspect.signature(fn)
    # Positional-or-keyword args (the 7 leading params)
    expected_positional = [
        "run_compile_check",
        "execute_sdk_call",
        "wave_letter",
        "template",
        "config",
        "cwd",
        "milestone",
    ]
    actual_positional = [
        name
        for name, p in sig.parameters.items()
        if p.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.POSITIONAL_ONLY,
        )
    ]
    assert actual_positional == expected_positional, (
        f"_run_wave_compile positional args drifted: {actual_positional}"
    )
    # Keyword-only args
    keyword_only = {
        name: p.default
        for name, p in sig.parameters.items()
        if p.kind == inspect.Parameter.KEYWORD_ONLY
    }
    assert "fallback_used" in keyword_only
    assert "provider_routing" in keyword_only


# ---------------------------------------------------------------------------
# `_build_compile_fix_prompt` retry-payload threading
# ---------------------------------------------------------------------------


def test_build_compile_fix_prompt_threads_phase_4_2_retry_payload() -> None:
    """R-#40 closure: when ``retry_payload`` is supplied, the legacy
    Claude-shaped prompt body includes the block above ``[ERRORS]``."""
    from agent_team_v15.wave_executor import _build_compile_fix_prompt

    class _Stub:
        id = "milestone-1"
        title = "Test milestone"

    errors = [{"file": "x.ts", "line": 1, "code": "TS2304", "message": "name 'x' missing"}]
    payload = "<previous_attempt_failed retry=1 wave=D>...payload body...</previous_attempt_failed>"

    prompt = _build_compile_fix_prompt(
        errors,
        "D",
        _Stub(),
        iteration=1,
        max_iterations=3,
        previous_error_count=2,
        retry_payload=payload,
    )

    assert "<previous_attempt_failed retry=1 wave=D>" in prompt
    # Payload appears BEFORE the [ERRORS] block.
    payload_idx = prompt.find("<previous_attempt_failed")
    errors_idx = prompt.find("[ERRORS]")
    assert payload_idx >= 0 and errors_idx >= 0
    assert payload_idx < errors_idx


def test_build_codex_compile_fix_prompt_threads_retry_payload() -> None:
    """R-#40 closure mirror: Codex shell variant accepts ``retry_payload``
    and inserts it between ``</context>`` and ``<errors>``."""
    from agent_team_v15.codex_fix_prompts import build_codex_compile_fix_prompt

    payload = "<previous_attempt_failed retry=2 wave=B>codex retry payload</previous_attempt_failed>"
    prompt = build_codex_compile_fix_prompt(
        errors=[],
        wave_letter="B",
        milestone_id="milestone-1",
        milestone_title="Test",
        iteration=2,
        max_iterations=3,
        previous_error_count=5,
        current_error_count=3,
        build_command="pnpm build",
        anti_band_aid_rules="(rules)",
        retry_payload=payload,
    )
    assert payload in prompt
    payload_idx = prompt.find(payload)
    errors_idx = prompt.find("<errors>")
    context_idx = prompt.find("</context>")
    assert context_idx >= 0 and payload_idx > context_idx and payload_idx < errors_idx


def test_build_compile_fix_prompt_empty_retry_payload_preserves_legacy_shape() -> None:
    """Backward-compat: when ``retry_payload`` is empty (default), the
    prompt is byte-identical to pre-Phase-5.6 output."""
    from agent_team_v15.wave_executor import _build_compile_fix_prompt

    class _Stub:
        id = "milestone-1"
        title = "Test"

    errors = [{"file": "x.ts", "line": 1, "code": "TS2304", "message": "missing"}]
    legacy_prompt = _build_compile_fix_prompt(
        errors, "D", _Stub(),
        iteration=0,
        max_iterations=3,
        previous_error_count=None,
    )
    # No retry_payload kwarg passed; prompt should not contain payload markers.
    assert "<previous_attempt_failed" not in legacy_prompt
    # The phase-5.6 path still emits the canonical [ERRORS] header.
    assert "[ERRORS]" in legacy_prompt


# ---------------------------------------------------------------------------
# Sync bridge isolation — `run_compile_profile_sync` from inside async
# ---------------------------------------------------------------------------


def test_run_compile_profile_sync_returns_compile_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The thread-pool bridge invokes ``run_wave_compile_check`` and
    returns its ``CompileResult`` to the synchronous caller."""
    from agent_team_v15 import compile_profiles
    from agent_team_v15.unified_build_gate import run_compile_profile_sync

    expected = _make_compile_result(passed=True)

    async def fake_check(**kwargs):
        return expected

    monkeypatch.setattr(compile_profiles, "run_wave_compile_check", fake_check)
    # The bridge imports run_wave_compile_check at runner-time inside
    # the thread; module attribute is the resolution target.
    monkeypatch.setattr(
        "agent_team_v15.unified_build_gate.run_wave_compile_check", fake_check
    )

    actual = run_compile_profile_sync(
        cwd=str(tmp_path),
        wave_letter="D",
        project_root=tmp_path,
    )
    assert actual.passed is True
    assert actual.errors == []


@pytest.mark.asyncio
async def test_run_compile_profile_sync_safe_from_running_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bridge MUST work when called from within an already-running
    event loop. ``asyncio.run`` raises ``RuntimeError`` inside a loop;
    the thread-pool isolation prevents that."""
    from agent_team_v15 import compile_profiles
    from agent_team_v15.unified_build_gate import run_compile_profile_sync

    expected = _make_compile_result(
        passed=False,
        errors=[
            {"file": "x.ts", "line": 1, "code": "TS2345", "message": "type mismatch"},
        ],
    )

    async def fake_check(**kwargs):
        return expected

    monkeypatch.setattr(compile_profiles, "run_wave_compile_check", fake_check)
    monkeypatch.setattr(
        "agent_team_v15.unified_build_gate.run_wave_compile_check", fake_check
    )

    # The fact that we're inside ``async def test_*`` means there's a
    # running loop; the bridge must still complete without RuntimeError.
    actual = run_compile_profile_sync(
        cwd=str(tmp_path),
        wave_letter="B",
        project_root=tmp_path,
    )
    assert actual.passed is False
    assert len(actual.errors) == 1


# ---------------------------------------------------------------------------
# `is_compile_env_unavailable` discrimination
# ---------------------------------------------------------------------------


def test_is_compile_env_unavailable_only_env_codes() -> None:
    """``is_compile_env_unavailable`` returns True iff EVERY error is an
    env-unavailability code. Mixed results (env + real TS) return False
    so real signal dominates."""
    from agent_team_v15.unified_build_gate import is_compile_env_unavailable

    # Pure env-unavailability.
    pure = _make_compile_result(
        passed=False,
        errors=[{"file": "", "line": 0, "code": "ENV_NOT_READY", "message": "..."}],
    )
    assert is_compile_env_unavailable(pure) is True

    # Real TS error.
    real = _make_compile_result(
        passed=False,
        errors=[{"file": "x.ts", "line": 1, "code": "TS2304", "message": "..."}],
    )
    assert is_compile_env_unavailable(real) is False

    # Mixed: env + real → real signal dominates.
    mixed = _make_compile_result(
        passed=False,
        errors=[
            {"file": "", "line": 0, "code": "ENV_NOT_READY", "message": "..."},
            {"file": "x.ts", "line": 1, "code": "TS2304", "message": "..."},
        ],
    )
    assert is_compile_env_unavailable(mixed) is False

    # Passed result (no errors) is not env-unavailable.
    clean = _make_compile_result(passed=True)
    assert is_compile_env_unavailable(clean) is False


# ---------------------------------------------------------------------------
# §M.M5 HINT suffix lint contract
# ---------------------------------------------------------------------------


def test_phase_5_6_hint_suffix_in_wave_b_and_wave_d_prompts() -> None:
    """§M.M5: Wave B and Wave D prompt builders embed the in-wave
    typecheck HINT suffix. The suffix is a productivity nudge, NOT a
    contract — the wave validator is the authoritative gate."""
    from agent_team_v15 import agents

    hint = agents._PHASE_5_6_INWAVE_TYPECHECK_HINT
    assert "wave-grader is the authoritative gate" in hint
    assert "productivity hint" in hint
    assert "Phase 4.2 payload" in hint


def test_phase_5_6_hint_suffix_not_consumed_by_post_wave_validators() -> None:
    """§M.M5: the HINT suffix MUST NOT be referenced by the post-wave
    validator code (``run_wave_b_acceptance_test`` /
    ``run_wave_d_acceptance_test``). Locks the "don't trust the claim"
    contract — the validator runs the compile profile itself rather
    than reading any signal embedded in the HINT or in Claude's
    self-report.
    """
    import agent_team_v15.wave_b_self_verify as wbsv
    import agent_team_v15.wave_d_self_verify as wdsv

    wb_src = inspect.getsource(wbsv)
    wd_src = inspect.getsource(wdsv)
    forbidden = (
        "wave-grader is the authoritative gate",
        "productivity hint",
        "_PHASE_5_6_INWAVE_TYPECHECK_HINT",
    )
    for needle in forbidden:
        assert needle not in wb_src, (
            f"wave_b_self_verify references HINT marker {needle!r}; "
            f"validator MUST NOT consume the HINT suffix."
        )
        assert needle not in wd_src, (
            f"wave_d_self_verify references HINT marker {needle!r}; "
            f"validator MUST NOT consume the HINT suffix."
        )


# ---------------------------------------------------------------------------
# Config — flag default + YAML threading
# ---------------------------------------------------------------------------


def test_runtime_verification_config_tsc_strict_check_enabled_default() -> None:
    """§I.1 default: ``tsc_strict_check_enabled`` ships ``True`` in
    Phase 5.6. §M.M11 calibration smoke is the operator-authorised
    activity that decides whether to flip the default."""
    from agent_team_v15.config import RuntimeVerificationConfig

    cfg = RuntimeVerificationConfig()
    assert cfg.tsc_strict_check_enabled is True


def test_yaml_parser_threads_tsc_strict_check_enabled() -> None:
    """YAML override: ``runtime_verification.tsc_strict_check_enabled:
    false`` flips the flag."""
    import yaml
    import tempfile
    import os
    from agent_team_v15.config import load_config

    yaml_dict = {
        "runtime_verification": {
            "tsc_strict_check_enabled": False,
        },
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as f:
        yaml.safe_dump(yaml_dict, f)
        yaml_path = f.name
    try:
        cfg, _user_overrides = load_config(yaml_path)
        assert cfg.runtime_verification.tsc_strict_check_enabled is False
    finally:
        os.unlink(yaml_path)


# ---------------------------------------------------------------------------
# Wave-D acceptance helper signature additions
# ---------------------------------------------------------------------------


def test_wave_d_acceptance_test_signature_phase_5_6_kwargs() -> None:
    """``run_wave_d_acceptance_test`` gains ``tsc_strict_enabled`` kwarg
    (default ``True``); existing kwargs preserved."""
    from agent_team_v15.wave_d_self_verify import run_wave_d_acceptance_test

    sig = inspect.signature(run_wave_d_acceptance_test)
    assert "tsc_strict_enabled" in sig.parameters
    assert sig.parameters["tsc_strict_enabled"].default is True
    # Phase 4.1 + 4.2 kwargs preserved:
    for name in (
        "narrow_services",
        "stack_contract",
        "modified_files",
        "prior_attempts",
        "this_retry_index",
        "strong_feedback_enabled",
    ):
        assert name in sig.parameters


def test_wave_b_acceptance_test_signature_phase_5_6_kwargs() -> None:
    """Wave B mirror — ``tsc_strict_enabled`` lands; Phase 4.x kwargs
    preserved."""
    from agent_team_v15.wave_b_self_verify import run_wave_b_acceptance_test

    sig = inspect.signature(run_wave_b_acceptance_test)
    assert "tsc_strict_enabled" in sig.parameters
    assert sig.parameters["tsc_strict_enabled"].default is True


# ---------------------------------------------------------------------------
# Result-shape additive contract (existing callers byte-compat)
# ---------------------------------------------------------------------------


def test_wave_d_verify_result_phase_5_6_fields_default_empty() -> None:
    """``WaveDVerifyResult`` gains ``tsc_failures``,
    ``project_build_failures``, ``tsc_env_unavailable``. Defaults are
    empty/False so existing callers (Phase 4.5 cascade epilogue
    ``getattr(_d_result, 'passed', False)``) byte-identical."""
    from agent_team_v15.wave_d_self_verify import WaveDVerifyResult

    r = WaveDVerifyResult(passed=True)
    assert r.tsc_failures == []
    assert r.project_build_failures == []
    assert r.tsc_env_unavailable is False


def test_wave_b_verify_result_phase_5_6_fields_default_empty() -> None:
    """Wave B mirror — same additive contract."""
    from agent_team_v15.wave_b_self_verify import WaveBVerifyResult

    r = WaveBVerifyResult(passed=True)
    assert r.tsc_failures == []
    assert r.project_build_failures == []
    assert r.tsc_env_unavailable is False

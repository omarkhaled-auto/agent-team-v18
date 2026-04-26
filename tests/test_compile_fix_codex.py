"""Phase G Slice 2b — Codex-native compile-fix prompt (flag-gated).

When ``v18.compile_fix_codex_enabled=True`` AND provider routing is
active, the wave executor calls ``_build_compile_fix_prompt(...,
use_codex_shell=True)`` which delegates to
``codex_fix_prompts.build_codex_compile_fix_prompt``. The LOCKED
``_ANTI_BAND_AID_FIX_RULES`` block (``cli.py``) is passed through
verbatim — the Codex builder must not paraphrase it.

Default ``use_codex_shell=False`` preserves the legacy Claude-shaped
prompt byte-for-byte.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent_team_v15 import import_resolvability_scan, quality_checks, wave_executor
from agent_team_v15.cli import _ANTI_BAND_AID_FIX_RULES
from agent_team_v15.codex_fix_prompts import build_codex_compile_fix_prompt
from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.wave_executor import _build_compile_fix_prompt


def _milestone() -> SimpleNamespace:
    return SimpleNamespace(id="M1", title="Users")


def _errors() -> list[dict]:
    return [
        {
            "file": "apps/api/src/users/users.service.ts",
            "line": 42,
            "code": "TS2322",
            "message": "Type 'string' is not assignable to type 'number'.",
        },
    ]


def test_flag_off_emits_legacy_claude_prompt_shape() -> None:
    """Default (use_codex_shell=False) keeps legacy PHASE header."""
    prompt = _build_compile_fix_prompt(
        _errors(),
        wave_letter="B",
        milestone=_milestone(),
        use_codex_shell=False,
    )
    assert prompt.startswith("[PHASE: WAVE B COMPILE FIX]")
    # Legacy shell does NOT emit the Codex JSON output contract tokens.
    assert "residual_error_count" not in prompt


def test_flag_on_emits_codex_shell_prompt() -> None:
    """use_codex_shell=True → Codex shell with output schema inlined."""
    prompt = _build_compile_fix_prompt(
        _errors(),
        wave_letter="B",
        milestone=_milestone(),
        use_codex_shell=True,
    )
    assert "compile-fix agent" in prompt
    assert "<context>" in prompt
    assert "<errors>" in prompt
    # Structured Codex JSON output contract.
    assert "fixed_errors" in prompt
    assert "still_failing" in prompt
    assert "residual_error_count" in prompt


def test_codex_shell_inherits_locked_anti_band_aid_verbatim() -> None:
    """The LOCKED block must appear byte-identical inside the Codex prompt."""
    prompt = _build_compile_fix_prompt(
        _errors(),
        wave_letter="B",
        milestone=_milestone(),
        use_codex_shell=True,
    )
    assert _ANTI_BAND_AID_FIX_RULES in prompt


def test_build_codex_compile_fix_prompt_direct_call_carries_locked() -> None:
    """Direct call to the prompt builder also propagates the LOCKED block."""
    prompt = build_codex_compile_fix_prompt(
        errors=_errors(),
        wave_letter="B",
        milestone_id="M1",
        milestone_title="Users",
        iteration=0,
        max_iterations=3,
        previous_error_count=None,
        current_error_count=1,
        build_command="pnpm build",
        anti_band_aid_rules=_ANTI_BAND_AID_FIX_RULES,
    )
    assert _ANTI_BAND_AID_FIX_RULES in prompt
    # Context placeholders rendered.
    assert "Wave: B" in prompt
    assert "Milestone: M1 — Users" in prompt
    assert "Iteration: 0/3" in prompt
    assert "full lockfiles" in prompt
    assert "broad recursive directory dumps" in prompt


def test_compile_fix_codex_enabled_flag_exists_and_defaults_on() -> None:
    """Compile-fix routing defaults to Codex when provider routing is active."""
    cfg = AgentTeamConfig()
    assert hasattr(cfg.v18, "compile_fix_codex_enabled")
    assert cfg.v18.compile_fix_codex_enabled is True


def test_codex_prompt_handles_missing_errors_gracefully() -> None:
    """Empty error list must not crash the builder."""
    prompt = build_codex_compile_fix_prompt(
        errors=[],
        wave_letter="B",
        milestone_id="M1",
        milestone_title="Users",
        iteration=1,
        max_iterations=3,
        previous_error_count=5,
        current_error_count=0,
        build_command="",
        anti_band_aid_rules=_ANTI_BAND_AID_FIX_RULES,
    )
    # Builder falls back to an explanatory bullet.
    assert "Compiler failed" in prompt or "no structured errors" in prompt


@pytest.mark.asyncio
async def test_wave_b_dto_guard_routes_fixes_to_codex(monkeypatch, tmp_path) -> None:
    captured_prompts: list[str] = []
    scan_calls = {"count": 0}

    violation = quality_checks.Violation(
        check="DTO-PROP-001",
        message="DTO field missing Swagger metadata.",
        file_path="apps/api/src/users/dto/create-user.dto.ts",
        line=1,
        severity="critical",
    )

    def _fake_scan(_root):
        scan_calls["count"] += 1
        if scan_calls["count"] == 1:
            return [violation]
        return []

    async def _fake_codex_fix(prompt: str, *, cwd: str, provider_routing, v18):
        del cwd, provider_routing, v18
        captured_prompts.append(prompt)
        return True, 0.02, ""

    async def _unexpected_watchdog(**_kwargs):
        raise AssertionError("DTO guard should use Codex routing, not the SDK sub-agent path")

    async def _fake_recompile(**_kwargs):
        return SimpleNamespace(
            passed=True,
            iterations=1,
            fix_cost=0.0,
            initial_error_count=0,
        )

    monkeypatch.setattr(quality_checks, "run_dto_contract_scan", _fake_scan)
    monkeypatch.setattr(wave_executor, "_dispatch_wrapped_codex_fix", _fake_codex_fix)
    monkeypatch.setattr(wave_executor, "_invoke_sdk_sub_agent_with_watchdog", _unexpected_watchdog)
    monkeypatch.setattr(wave_executor, "_run_wave_compile", _fake_recompile)

    config = SimpleNamespace(
        v18=SimpleNamespace(codex_fix_routing_enabled=True)
    )
    provider_routing = {
        "provider_map": SimpleNamespace(provider_for=lambda wave: "codex"),
    }

    result = await wave_executor._run_wave_b_dto_contract_guard(
        run_compile_check=AsyncMock(),
        execute_sdk_call=AsyncMock(),
        template="nestjs",
        config=config,
        cwd=str(tmp_path),
        milestone=_milestone(),
        provider_routing=provider_routing,
    )

    assert result.passed is True
    assert captured_prompts
    assert "DTO-PROP-001" in captured_prompts[0]


@pytest.mark.asyncio
async def test_wave_d_frontend_guard_threads_provider_routing_to_recompile(
    monkeypatch, tmp_path
) -> None:
    scan_calls = {"count": 0}
    recompile_calls: list[dict] = []

    violation = quality_checks.Violation(
        check="I18N-HARDCODED-001",
        message="Invalid locale route segment.",
        file_path="apps/web/src/app/[locale]/page.tsx",
        line=1,
        severity="critical",
    )

    def _fake_scan(_root, *, allowed_locales):
        assert allowed_locales == ["en", "ar"]
        scan_calls["count"] += 1
        if scan_calls["count"] == 1:
            return [violation]
        return []

    codex_prompts: list[str] = []

    async def _fake_codex_fix(prompt: str, *, cwd: str, provider_routing, v18):
        del cwd, provider_routing, v18
        codex_prompts.append(prompt)
        return True, 0.01, ""

    async def _unexpected_watchdog(**_kwargs):
        raise AssertionError("Wave D frontend guard should use Codex routing, not SDK sub-agent")

    async def _fake_recompile(**kwargs):
        recompile_calls.append(kwargs)
        assert kwargs["provider_routing"] is provider_routing
        return SimpleNamespace(
            passed=True,
            iterations=1,
            fix_cost=0.0,
            initial_error_count=0,
        )

    monkeypatch.setattr(
        quality_checks,
        "run_frontend_hallucination_scan",
        _fake_scan,
    )
    monkeypatch.setattr(
        import_resolvability_scan,
        "run_import_resolvability_scan",
        lambda _root: [],
    )
    monkeypatch.setattr(
        wave_executor,
        "_invoke_sdk_sub_agent_with_watchdog",
        _unexpected_watchdog,
    )
    monkeypatch.setattr(wave_executor, "_dispatch_wrapped_codex_fix", _fake_codex_fix)
    monkeypatch.setattr(wave_executor, "_run_wave_compile", _fake_recompile)

    provider_routing = {
        "provider_map": SimpleNamespace(provider_for=lambda wave: "codex"),
    }
    result = await wave_executor._run_wave_d_frontend_hallucination_guard(
        run_compile_check=AsyncMock(),
        execute_sdk_call=AsyncMock(),
        template="nextjs",
        config=SimpleNamespace(v18=SimpleNamespace(codex_fix_routing_enabled=True)),
        cwd=str(tmp_path),
        milestone=_milestone(),
        ir={"i18n": {"locales": ["en", "ar"]}},
        provider_routing=provider_routing,
    )

    assert result.passed is True
    assert result.compile_passed is True
    assert recompile_calls
    assert codex_prompts


@pytest.mark.asyncio
async def test_wave_b_dto_guard_codex_failure_fails_gate_without_sdk(
    monkeypatch, tmp_path
) -> None:
    violation = quality_checks.Violation(
        check="DTO-PROP-001",
        message="DTO field missing Swagger metadata.",
        file_path="apps/api/src/users/dto/create-user.dto.ts",
        line=1,
        severity="critical",
    )

    async def _fake_codex_fix(prompt: str, *, cwd: str, provider_routing, v18):
        del prompt, cwd, provider_routing, v18
        return False, 0.03, "app-server unavailable"

    async def _unexpected_watchdog(**_kwargs):
        raise AssertionError("DTO guard must not fall back to SDK sub-agent after Codex failure")

    monkeypatch.setattr(quality_checks, "run_dto_contract_scan", lambda _root: [violation])
    monkeypatch.setattr(wave_executor, "_dispatch_wrapped_codex_fix", _fake_codex_fix)
    monkeypatch.setattr(wave_executor, "_invoke_sdk_sub_agent_with_watchdog", _unexpected_watchdog)

    result = await wave_executor._run_wave_b_dto_contract_guard(
        run_compile_check=AsyncMock(),
        execute_sdk_call=AsyncMock(),
        template="nestjs",
        config=SimpleNamespace(v18=SimpleNamespace(codex_fix_routing_enabled=True)),
        cwd=str(tmp_path),
        milestone=_milestone(),
        provider_routing={
            "provider_map": SimpleNamespace(provider_for=lambda wave: "codex"),
        },
    )

    assert result.passed is False
    assert result.fix_cost == pytest.approx(0.03)
    assert "Codex repair failed" in result.error_message
    assert "app-server unavailable" in result.error_message


@pytest.mark.asyncio
async def test_wave_d_frontend_guard_codex_failure_fails_gate_without_sdk(
    monkeypatch, tmp_path
) -> None:
    violation = quality_checks.Violation(
        check="I18N-HARDCODED-001",
        message="Invalid locale route segment.",
        file_path="apps/web/src/app/[locale]/page.tsx",
        line=1,
        severity="critical",
    )

    async def _fake_codex_fix(prompt: str, *, cwd: str, provider_routing, v18):
        del prompt, cwd, provider_routing, v18
        return False, 0.04, "repair rejected"

    async def _unexpected_watchdog(**_kwargs):
        raise AssertionError("Wave D guard must not fall back to SDK sub-agent after Codex failure")

    monkeypatch.setattr(
        quality_checks,
        "run_frontend_hallucination_scan",
        lambda _root, *, allowed_locales: [violation],
    )
    monkeypatch.setattr(
        import_resolvability_scan,
        "run_import_resolvability_scan",
        lambda _root: [],
    )
    monkeypatch.setattr(wave_executor, "_dispatch_wrapped_codex_fix", _fake_codex_fix)
    monkeypatch.setattr(wave_executor, "_invoke_sdk_sub_agent_with_watchdog", _unexpected_watchdog)

    result = await wave_executor._run_wave_d_frontend_hallucination_guard(
        run_compile_check=AsyncMock(),
        execute_sdk_call=AsyncMock(),
        template="nextjs",
        config=SimpleNamespace(v18=SimpleNamespace(codex_fix_routing_enabled=True)),
        cwd=str(tmp_path),
        milestone=_milestone(),
        ir={"i18n": {"locales": ["en"]}},
        provider_routing={
            "provider_map": SimpleNamespace(provider_for=lambda wave: "codex"),
        },
    )

    assert result.passed is False
    assert result.fix_cost == pytest.approx(0.04)
    assert "Codex repair failed" in result.error_message
    assert "repair rejected" in result.error_message

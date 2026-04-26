"""Tests for A-10/D-15/D-16 compile-fix improvements.

Covers _detect_structural_issues, _build_structural_fix_prompt,
_build_compile_fix_prompt iteration context, and _run_wave_compile
configurable iteration cap.
"""
import json
import pytest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass, field
from typing import Any

from agent_team_v15.wave_executor import (
    _detect_structural_issues,
    _build_structural_fix_prompt,
    _build_compile_fix_prompt,
    _run_wave_compile,
    CompileCheckResult,
)


# ---------------------------------------------------------------------------
# _detect_structural_issues
# ---------------------------------------------------------------------------

def test_detect_structural_issues_valid_package_json(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"name": "test", "version": "1.0.0"}))
    issues = _detect_structural_issues(str(tmp_path), "B")
    assert issues == []


def test_detect_structural_issues_invalid_package_json(tmp_path):
    (tmp_path / "package.json").write_text("{invalid json!!")
    issues = _detect_structural_issues(str(tmp_path), "B")
    assert len(issues) == 1
    assert issues[0]["type"] == "invalid_package_json"


def test_detect_structural_issues_missing_package_json(tmp_path):
    # No package.json at all -- not an error for non-JS projects
    issues = _detect_structural_issues(str(tmp_path), "B")
    assert issues == []


def test_detect_structural_issues_checks_subdirs(tmp_path):
    web_dir = tmp_path / "apps" / "web"
    web_dir.mkdir(parents=True)
    (web_dir / "package.json").write_text(json.dumps({"name": "web-app"}))
    # No root package.json -- should find the one in apps/web/
    issues = _detect_structural_issues(str(tmp_path), "B")
    assert issues == []


# ---------------------------------------------------------------------------
# _build_structural_fix_prompt
# ---------------------------------------------------------------------------

def test_build_structural_fix_prompt_format():
    issues = [
        {"type": "invalid_package_json", "detail": "Unexpected token", "file": "package.json"},
    ]
    milestone = MagicMock(id="M1", title="Scaffold")
    prompt = _build_structural_fix_prompt(issues, "B", milestone)
    assert "[STRUCTURAL ISSUES]" in prompt
    assert "invalid_package_json" in prompt
    assert "Unexpected token" in prompt


# ---------------------------------------------------------------------------
# _build_compile_fix_prompt — iteration context
# ---------------------------------------------------------------------------

def test_build_compile_fix_prompt_iteration_context():
    errors = [{"file": "x.ts", "line": 1, "code": "TS2304", "message": "not found"}]
    prompt = _build_compile_fix_prompt(
        errors, "B", MagicMock(id="M1", title="test"),
        iteration=1, max_iterations=5, previous_error_count=12,
    )
    assert "Compile fix iteration 2/5" in prompt
    assert "12 errors" in prompt


def test_build_compile_fix_prompt_no_context_on_first():
    errors = [{"file": "x.ts", "line": 1, "code": "TS2304", "message": "not found"}]
    prompt = _build_compile_fix_prompt(
        errors, "B", MagicMock(id="M1", title="test"),
        iteration=0, max_iterations=3,
    )
    assert "Compile fix iteration" not in prompt


def test_build_compile_fix_prompt_unchanged_errors_message():
    errors = [{"file": "x.ts", "line": 1, "code": "TS2304", "message": "not found"}]
    prompt = _build_compile_fix_prompt(
        errors, "B", MagicMock(id="M1", title="test"),
        iteration=1, max_iterations=5, previous_error_count=1,
    )
    assert "unchanged" in prompt.lower()


def test_build_compile_fix_prompt_increased_errors_message():
    errors = [
        {"file": "a.ts", "line": 1, "code": "TS2304", "message": "not found"},
        {"file": "b.ts", "line": 2, "code": "TS2304", "message": "not found"},
        {"file": "c.ts", "line": 3, "code": "TS2304", "message": "not found"},
    ]
    prompt = _build_compile_fix_prompt(
        errors, "B", MagicMock(id="M1", title="test"),
        iteration=2, max_iterations=5, previous_error_count=1,
    )
    assert "Revert" in prompt


# ---------------------------------------------------------------------------
# _run_wave_compile — iteration cap
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_wave_compile_uses_5_iterations_on_fallback():
    call_count = 0

    async def mock_invoke(func, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count >= 5:
            return CompileCheckResult(passed=True)
        return CompileCheckResult(
            passed=False,
            errors=[{"file": "x.ts", "line": 1, "code": "TS2304", "message": "not found"}],
        )

    mock_sdk = AsyncMock(return_value=(0.0, MagicMock()))
    milestone = MagicMock(id="m1", title="test", stack_target="typescript")

    with patch("agent_team_v15.wave_executor._detect_structural_issues", return_value=[]):
        with patch("agent_team_v15.wave_executor._invoke", side_effect=mock_invoke):
            with patch(
                "agent_team_v15.wave_executor._invoke_sdk_sub_agent_with_watchdog",
                return_value=(0.0, MagicMock()),
            ):
                result = await _run_wave_compile(
                    MagicMock(), mock_sdk, "B", "nestjs", MagicMock(), "/tmp", milestone,
                    fallback_used=True,
                )
    assert result.passed
    assert call_count == 5


@pytest.mark.asyncio
async def test_run_wave_compile_uses_3_iterations_default():
    call_count = 0

    async def mock_invoke(func, **kwargs):
        nonlocal call_count
        call_count += 1
        return CompileCheckResult(
            passed=False,
            errors=[{"file": "x.ts", "line": 1, "code": "TS2304", "message": "not found"}],
        )

    mock_sdk = AsyncMock(return_value=(0.0, MagicMock()))
    milestone = MagicMock(id="m1", title="test", stack_target="typescript")

    with patch("agent_team_v15.wave_executor._detect_structural_issues", return_value=[]):
        with patch("agent_team_v15.wave_executor._invoke", side_effect=mock_invoke):
            with patch(
                "agent_team_v15.wave_executor._invoke_sdk_sub_agent_with_watchdog",
                return_value=(0.0, MagicMock()),
            ):
                result = await _run_wave_compile(
                    MagicMock(), mock_sdk, "B", "nestjs", MagicMock(), "/tmp", milestone,
                    fallback_used=False,
                )
    assert not result.passed
    assert call_count == 3


@pytest.mark.asyncio
async def test_structural_triage_runs_before_compile_loop():
    """Verify _detect_structural_issues is called before the iteration loop starts."""
    call_order = []

    async def mock_invoke(func, **kwargs):
        call_order.append("compile_check")
        return CompileCheckResult(passed=True)

    def mock_detect(cwd, wave_letter):
        call_order.append("detect_structural")
        return []

    mock_sdk = AsyncMock(return_value=(0.0, MagicMock()))
    milestone = MagicMock(id="m1", title="test", stack_target="typescript")

    with patch("agent_team_v15.wave_executor._detect_structural_issues", side_effect=mock_detect):
        with patch("agent_team_v15.wave_executor._invoke", side_effect=mock_invoke):
            await _run_wave_compile(
                MagicMock(), mock_sdk, "B", "nestjs", MagicMock(), "/tmp", milestone,
            )

    assert call_order[0] == "detect_structural"
    assert "compile_check" in call_order


@pytest.mark.asyncio
async def test_structural_fix_routes_to_codex_when_enabled():
    async def mock_invoke(func, **kwargs):
        del func, kwargs
        return CompileCheckResult(passed=True)

    milestone = MagicMock(id="m1", title="test", stack_target="typescript")
    config = SimpleNamespace(
        v18=SimpleNamespace(
            codex_fix_routing_enabled=True,
            wave_d_merged_enabled=False,
            wave_d_compile_fix_max_attempts=2,
        )
    )
    provider_routing = {
        "provider_map": SimpleNamespace(provider_for=lambda wave: "codex"),
    }

    with patch(
        "agent_team_v15.wave_executor._detect_structural_issues",
        return_value=[{"type": "invalid_package_json", "detail": "bad json", "file": "package.json"}],
    ):
        with patch("agent_team_v15.wave_executor._invoke", side_effect=mock_invoke):
            with patch(
                "agent_team_v15.wave_executor._dispatch_wrapped_codex_fix",
                return_value=(True, 0.05, ""),
            ) as codex_fix:
                with patch(
                    "agent_team_v15.wave_executor._invoke_sdk_sub_agent_with_watchdog",
                    side_effect=AssertionError("structural fix should route to Codex"),
                ):
                    result = await _run_wave_compile(
                        MagicMock(),
                        AsyncMock(),
                        "B",
                        "nestjs",
                        config,
                        "/tmp",
                        milestone,
                        provider_routing=provider_routing,
                    )

    assert result.passed is True
    assert result.fix_cost == pytest.approx(0.05)
    codex_fix.assert_awaited_once()


@pytest.mark.asyncio
async def test_structural_fix_codex_failure_fails_compile_without_sdk():
    milestone = MagicMock(id="m1", title="test", stack_target="typescript")
    config = SimpleNamespace(
        v18=SimpleNamespace(
            codex_fix_routing_enabled=True,
            wave_d_merged_enabled=False,
            wave_d_compile_fix_max_attempts=2,
        )
    )
    provider_routing = {
        "provider_map": SimpleNamespace(provider_for=lambda wave: "codex"),
    }

    with patch(
        "agent_team_v15.wave_executor._detect_structural_issues",
        return_value=[{"type": "invalid_package_json", "detail": "bad json", "file": "package.json"}],
    ):
        with patch(
            "agent_team_v15.wave_executor._dispatch_wrapped_codex_fix",
            return_value=(False, 0.06, "app-server unavailable"),
        ) as codex_fix:
            with patch(
                "agent_team_v15.wave_executor._invoke_sdk_sub_agent_with_watchdog",
                side_effect=AssertionError("structural repair must not fall back to SDK sub-agent"),
            ):
                result = await _run_wave_compile(
                    MagicMock(),
                    AsyncMock(),
                    "B",
                    "nestjs",
                    config,
                    "/tmp",
                    milestone,
                    provider_routing=provider_routing,
                )

    assert result.passed is False
    assert result.fix_cost == pytest.approx(0.06)
    assert result.errors[0]["code"] == "CODEX-REPAIR-FAILED"
    assert "app-server unavailable" in result.errors[0]["message"]
    codex_fix.assert_awaited_once()


@pytest.mark.asyncio
async def test_compile_fix_codex_failure_fails_compile_without_sdk():
    async def mock_invoke(func, **kwargs):
        del func, kwargs
        return CompileCheckResult(
            passed=False,
            initial_error_count=1,
            errors=[{"file": "src/app.ts", "line": 1, "code": "TS2304", "message": "not found"}],
        )

    milestone = MagicMock(id="m1", title="test", stack_target="typescript")
    config = SimpleNamespace(
        v18=SimpleNamespace(
            codex_fix_routing_enabled=True,
            wave_d_merged_enabled=False,
            wave_d_compile_fix_max_attempts=2,
        )
    )
    provider_routing = {
        "provider_map": SimpleNamespace(provider_for=lambda wave: "codex"),
    }

    with patch("agent_team_v15.wave_executor._detect_structural_issues", return_value=[]):
        with patch("agent_team_v15.wave_executor._invoke", side_effect=mock_invoke):
            with patch(
                "agent_team_v15.wave_executor._dispatch_codex_compile_fix",
                return_value=(False, 0.07, "repair refused"),
            ) as codex_fix:
                with patch(
                    "agent_team_v15.wave_executor._invoke_sdk_sub_agent_with_watchdog",
                    side_effect=AssertionError("compile repair must not fall back to SDK sub-agent"),
                ):
                    result = await _run_wave_compile(
                        MagicMock(),
                        AsyncMock(),
                        "B",
                        "nestjs",
                        config,
                        "/tmp",
                        milestone,
                        provider_routing=provider_routing,
                    )

    assert result.passed is False
    assert result.iterations == 1
    assert result.fix_cost == pytest.approx(0.07)
    assert any(error["code"] == "CODEX-REPAIR-FAILED" for error in result.errors)
    assert any("repair refused" in error["message"] for error in result.errors)
    codex_fix.assert_awaited_once()

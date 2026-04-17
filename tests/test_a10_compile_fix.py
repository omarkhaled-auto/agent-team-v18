"""Tests for A-10/D-15/D-16 compile-fix improvements.

Covers _detect_structural_issues, _build_structural_fix_prompt,
_build_compile_fix_prompt iteration context, and _run_wave_compile
configurable iteration cap.
"""
import json
import pytest
from pathlib import Path
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

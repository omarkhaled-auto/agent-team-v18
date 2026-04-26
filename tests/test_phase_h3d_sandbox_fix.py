from __future__ import annotations

import types
from unittest.mock import AsyncMock

import pytest

from agent_team_v15.codex_transport import CodexConfig, CodexResult
from agent_team_v15.provider_router import WaveProviderMap, execute_wave_with_provider


class _FakeCheckpoint:
    def __init__(self, *, file_manifest: dict[str, str] | None = None) -> None:
        self.file_manifest = file_manifest or {}
        self.timestamp = "2026-04-20T00:00:00Z"


class _FakeDiff:
    def __init__(
        self,
        *,
        created: list[str] | None = None,
        modified: list[str] | None = None,
        deleted: list[str] | None = None,
    ) -> None:
        self.created = created or []
        self.modified = modified or []
        self.deleted = deleted or []


def _provider_config(*, blocked_enabled: bool) -> object:
    return types.SimpleNamespace(
        v18=types.SimpleNamespace(
            codex_blocked_prefix_as_failure_enabled=blocked_enabled,
            codex_capture_enabled=False,
            codex_flush_wait_enabled=False,
        ),
        orchestrator=types.SimpleNamespace(model="claude-sonnet-4-6"),
    )


async def _claude_callback(**_kwargs: object) -> float:
    return 0.02


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "final_message, expected_error",
    [
        ("BLOCKED: workspace read-only", "BLOCKED: workspace read-only"),
        ("  BLOCKED: write denied", "BLOCKED: write denied"),
    ],
)
async def test_blocked_prefix_flag_on_treats_success_result_as_failure(
    tmp_path,
    caplog: pytest.LogCaptureFixture,
    final_message: str,
    expected_error: str,
) -> None:
    codex_result = CodexResult(
        success=True,
        model="gpt-5.4",
        final_message=final_message,
        cost_usd=0.11,
        input_tokens=400,
        output_tokens=120,
        reasoning_tokens=30,
    )
    transport = types.SimpleNamespace(
        is_codex_available=lambda: True,
        execute_codex=AsyncMock(return_value=codex_result),
    )

    with caplog.at_level("WARNING"):
        result = await execute_wave_with_provider(
            wave_letter="B",
            prompt="wire backend",
            cwd=str(tmp_path),
            config=_provider_config(blocked_enabled=True),
            provider_map=WaveProviderMap(),
            claude_callback=_claude_callback,
            claude_callback_kwargs={},
            codex_transport_module=transport,
            codex_config=CodexConfig(),
            checkpoint_create=lambda label, cwd: _FakeCheckpoint(),
            checkpoint_diff=lambda pre, post: _FakeDiff(),
        )

    assert codex_result.success is False
    assert codex_result.error == expected_error
    assert result["provider"] == "codex"
    assert result["fallback_used"] is False
    assert result["fallback_reason"] == ""
    assert "codex failed" in result["error_message"].lower()
    assert expected_error in result["error_message"]
    assert any("CODEX-WAVE-B-BLOCKED-001" in record.message for record in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("final_message", ["Great, all done!", ""])
async def test_blocked_prefix_flag_on_ignores_non_blocked_messages(
    tmp_path,
    caplog: pytest.LogCaptureFixture,
    final_message: str,
) -> None:
    codex_result = CodexResult(
        success=True,
        model="gpt-5.4",
        final_message=final_message,
        cost_usd=0.10,
        input_tokens=500,
        output_tokens=200,
        reasoning_tokens=50,
    )
    transport = types.SimpleNamespace(
        is_codex_available=lambda: True,
        execute_codex=AsyncMock(return_value=codex_result),
    )

    with caplog.at_level("WARNING"):
        result = await execute_wave_with_provider(
            wave_letter="B",
            prompt="wire backend",
            cwd=str(tmp_path),
            config=_provider_config(blocked_enabled=True),
            provider_map=WaveProviderMap(),
            claude_callback=_claude_callback,
            claude_callback_kwargs={},
            codex_transport_module=transport,
            codex_config=CodexConfig(),
            checkpoint_create=lambda label, cwd: _FakeCheckpoint(),
            checkpoint_diff=lambda pre, post: _FakeDiff(modified=["artifact.bin"]),
        )

    assert codex_result.success is True
    assert codex_result.error == ""
    assert result["provider"] == "codex"
    assert result["fallback_used"] is False
    assert not any("CODEX-WAVE-B-BLOCKED-001" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_blocked_prefix_flag_on_does_not_rewrite_existing_failure(
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    codex_result = CodexResult(
        success=False,
        exit_code=1,
        model="gpt-5.4",
        final_message="BLOCKED: workspace read-only",
        error="model overloaded",
        cost_usd=0.09,
    )
    transport = types.SimpleNamespace(
        is_codex_available=lambda: True,
        execute_codex=AsyncMock(return_value=codex_result),
    )

    with caplog.at_level("WARNING"):
        result = await execute_wave_with_provider(
            wave_letter="B",
            prompt="wire backend",
            cwd=str(tmp_path),
            config=_provider_config(blocked_enabled=True),
            provider_map=WaveProviderMap(),
            claude_callback=_claude_callback,
            claude_callback_kwargs={},
            codex_transport_module=transport,
            codex_config=CodexConfig(),
            checkpoint_create=lambda label, cwd: _FakeCheckpoint(),
            checkpoint_diff=lambda pre, post: _FakeDiff(),
        )

    assert codex_result.success is False
    assert codex_result.error == "model overloaded"
    assert result["provider"] == "codex"
    assert result["fallback_used"] is False
    assert result["fallback_reason"] == ""
    assert "model overloaded" in result["error_message"]
    assert not any("CODEX-WAVE-B-BLOCKED-001" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_blocked_prefix_flag_off_preserves_zero_diff_hard_failure(
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    codex_result = CodexResult(
        success=True,
        model="gpt-5.4",
        final_message="BLOCKED: workspace read-only",
        cost_usd=0.10,
    )
    transport = types.SimpleNamespace(
        is_codex_available=lambda: True,
        execute_codex=AsyncMock(return_value=codex_result),
    )

    with caplog.at_level("WARNING"):
        result = await execute_wave_with_provider(
            wave_letter="B",
            prompt="wire backend",
            cwd=str(tmp_path),
            config=_provider_config(blocked_enabled=False),
            provider_map=WaveProviderMap(),
            claude_callback=_claude_callback,
            claude_callback_kwargs={},
            codex_transport_module=transport,
            codex_config=CodexConfig(),
            checkpoint_create=lambda label, cwd: _FakeCheckpoint(),
            checkpoint_diff=lambda pre, post: _FakeDiff(),
        )

    assert codex_result.success is True
    assert codex_result.error == ""
    assert result["provider"] == "codex"
    assert result["fallback_used"] is False
    assert result["fallback_reason"] == ""
    assert "no tracked file changes" in result["error_message"].lower()
    assert not any("CODEX-WAVE-B-BLOCKED-001" in record.message for record in caplog.records)

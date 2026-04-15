from __future__ import annotations

import asyncio
import types
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agent_team_v15.codex_transport import CodexConfig, CodexResult
from agent_team_v15.provider_router import WaveProviderMap
from agent_team_v15.wave_executor import (
    _create_checkpoint,
    _diff_checkpoints,
    _execute_wave_sdk,
)


def _config(*, max_retries: int = 1) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        v18=types.SimpleNamespace(
            wave_idle_timeout_seconds=1,
            wave_watchdog_poll_seconds=1,
            wave_watchdog_max_retries=max_retries,
        )
    )


def _routing(transport: object) -> dict[str, object]:
    return {
        "provider_map": WaveProviderMap(B="codex"),
        "codex_transport": transport,
        "codex_config": CodexConfig(timeout_seconds=60, max_retries=0),
        "codex_home": None,
        "checkpoint_create": _create_checkpoint,
        "checkpoint_diff": _diff_checkpoints,
    }


def _milestone() -> types.SimpleNamespace:
    return types.SimpleNamespace(id="M1", title="Orders")


class TestProviderRouterFallbackOnWatchdogTimeout:
    @pytest.mark.asyncio
    async def test_watchdog_timeout_falls_back_to_claude_on_retry(self, tmp_path: Path) -> None:
        transport = types.SimpleNamespace(
            is_codex_available=lambda: True,
            execute_codex=AsyncMock(side_effect=self._wedge_forever),
        )
        claude_prompts: list[str] = []

        async def _claude_cb(prompt: str, **_: object) -> float:
            claude_prompts.append(prompt)
            (tmp_path / "claude-fallback.ts").write_text("export const fallback = true;\n", encoding="utf-8")
            return 0.02

        result = await _execute_wave_sdk(
            execute_sdk_call=_claude_cb,
            wave_letter="B",
            prompt="wire backend",
            config=_config(max_retries=1),
            cwd=str(tmp_path),
            milestone=_milestone(),
            provider_routing=_routing(transport),
        )

        assert result.success is True
        assert result.provider == "claude"
        assert result.fallback_used is True
        assert "watchdog" in result.fallback_reason.lower()
        assert result.retry_count == 1
        assert claude_prompts == ["wire backend"]
        assert transport.execute_codex.await_count == 1

    @pytest.mark.asyncio
    async def test_watchdog_timeout_then_claude_failure_captures_both_errors(self, tmp_path: Path) -> None:
        transport = types.SimpleNamespace(
            is_codex_available=lambda: True,
            execute_codex=AsyncMock(side_effect=self._wedge_forever),
        )

        async def _claude_cb(prompt: str, **_: object) -> float:
            raise RuntimeError("Claude fallback exploded")

        result = await _execute_wave_sdk(
            execute_sdk_call=_claude_cb,
            wave_letter="B",
            prompt="wire backend",
            config=_config(max_retries=1),
            cwd=str(tmp_path),
            milestone=_milestone(),
            provider_routing=_routing(transport),
        )

        assert result.success is False
        assert "watchdog" in result.error_message.lower()
        assert "claude fallback exploded" in result.error_message.lower()
        assert transport.execute_codex.await_count == 1

    @pytest.mark.asyncio
    async def test_watchdog_timeout_does_not_reinvoke_codex(self, tmp_path: Path) -> None:
        transport = types.SimpleNamespace(
            is_codex_available=lambda: True,
            execute_codex=AsyncMock(side_effect=self._wedge_forever),
        )

        async def _claude_cb(prompt: str, **_: object) -> float:
            (tmp_path / "claude-fallback.ts").write_text("export const fallback = true;\n", encoding="utf-8")
            return 0.02

        result = await _execute_wave_sdk(
            execute_sdk_call=_claude_cb,
            wave_letter="B",
            prompt="wire backend",
            config=_config(max_retries=1),
            cwd=str(tmp_path),
            milestone=_milestone(),
            provider_routing=_routing(transport),
        )

        assert result.success is True
        assert transport.execute_codex.await_count == 1

    @pytest.mark.asyncio
    async def test_codex_429_still_falls_back_to_claude(self, tmp_path: Path) -> None:
        transport = types.SimpleNamespace(
            is_codex_available=lambda: True,
            execute_codex=AsyncMock(
                return_value=CodexResult(
                    success=False,
                    exit_code=1,
                    error="Selected model is at capacity. Please try a different model.",
                    model="gpt-5.4",
                    retry_count=0,
                    cost_usd=0.07,
                    input_tokens=120,
                )
            ),
        )

        async def _claude_cb(prompt: str, **_: object) -> float:
            (tmp_path / "claude-fallback.ts").write_text("export const fallback = true;\n", encoding="utf-8")
            return 0.02

        result = await _execute_wave_sdk(
            execute_sdk_call=_claude_cb,
            wave_letter="B",
            prompt="wire backend",
            config=_config(max_retries=1),
            cwd=str(tmp_path),
            milestone=_milestone(),
            provider_routing=_routing(transport),
        )

        assert result.success is True
        assert result.provider == "claude"
        assert result.fallback_used is True
        assert "at capacity" in result.fallback_reason.lower()
        assert result.retry_count == 0
        assert transport.execute_codex.await_count == 1

    @pytest.mark.asyncio
    async def test_codex_success_first_attempt_skips_fallback(self, tmp_path: Path) -> None:
        async def _codex_exec(
            prompt: str,
            cwd: str,
            config: CodexConfig,
            codex_home: Path | None,
            *,
            progress_callback=None,
        ) -> CodexResult:
            (Path(cwd) / "wave-b.ts").write_text("export const waveB = true;\n", encoding="utf-8")
            return CodexResult(success=True, model="gpt-5.4", cost_usd=0.11)

        transport = types.SimpleNamespace(
            is_codex_available=lambda: True,
            execute_codex=AsyncMock(side_effect=_codex_exec),
        )
        claude_mock = AsyncMock(return_value=0.02)

        result = await _execute_wave_sdk(
            execute_sdk_call=claude_mock,
            wave_letter="B",
            prompt="wire backend",
            config=_config(max_retries=1),
            cwd=str(tmp_path),
            milestone=_milestone(),
            provider_routing=_routing(transport),
        )

        assert result.success is True
        assert result.provider == "codex"
        assert result.fallback_used is False
        assert result.retry_count == 0
        assert transport.execute_codex.await_count == 1
        claude_mock.assert_not_awaited()

    @staticmethod
    async def _wedge_forever(
        prompt: str,
        cwd: str,
        config: CodexConfig,
        codex_home: Path | None,
        *,
        progress_callback=None,
    ) -> CodexResult:
        await asyncio.sleep(3600)
        return CodexResult(success=True, model="gpt-5.4")

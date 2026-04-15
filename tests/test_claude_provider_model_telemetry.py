from __future__ import annotations

import asyncio
import json
import types
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agent_team_v15 import wave_executor as wave_executor_module
from agent_team_v15.codex_transport import CodexConfig, CodexResult
from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.provider_router import WaveProviderMap
from agent_team_v15.wave_executor import (
    _create_checkpoint,
    _diff_checkpoints,
    _execute_wave_sdk,
    _execute_wave_t,
    save_wave_telemetry,
)


def _config(*, model: str = "claude-sonnet-4-6") -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.orchestrator.model = model
    cfg.v18.wave_idle_timeout_seconds = 1
    cfg.v18.wave_watchdog_poll_seconds = 1
    cfg.v18.wave_watchdog_max_retries = 1
    cfg.v18.wave_t_max_fix_iterations = 0
    return cfg


def _routing(*, wave_letter: str, transport: object | None) -> dict[str, object]:
    provider_map = WaveProviderMap()
    setattr(provider_map, wave_letter, "codex" if transport is not None else "claude")
    return {
        "provider_map": provider_map,
        "codex_transport": transport,
        "codex_config": CodexConfig(model="gpt-5.4", timeout_seconds=60, max_retries=0),
        "codex_home": None,
        "checkpoint_create": _create_checkpoint,
        "checkpoint_diff": _diff_checkpoints,
    }


def _milestone() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        id="M1",
        title="Orders",
        template="full_stack",
        description="Orders milestone",
        dependencies=[],
        feature_refs=["F-ORDERS"],
        ac_refs=[],
        merge_surfaces=[],
        stack_target="NestJS Next.js",
    )


def _load_telemetry(tmp_path: Path, wave: str) -> dict[str, object]:
    telemetry_path = tmp_path / ".agent-team" / "telemetry" / f"M1-wave-{wave}.json"
    assert telemetry_path.is_file()
    return json.loads(telemetry_path.read_text(encoding="utf-8"))


class TestClaudeProviderModelTelemetry:
    @pytest.mark.asyncio
    async def test_wave_a_direct_claude_telemetry_uses_orchestrator_model(self, tmp_path: Path) -> None:
        cfg = _config(model="claude-sonnet-4-6")

        async def _sdk_call(prompt: str, **_: object) -> float:
            return 0.05

        result = await _execute_wave_sdk(
            execute_sdk_call=_sdk_call,
            wave_letter="A",
            prompt="plan milestone",
            config=cfg,
            cwd=str(tmp_path),
            milestone=_milestone(),
            provider_routing=_routing(wave_letter="A", transport=None),
        )
        save_wave_telemetry(result, str(tmp_path), "M1")
        telemetry = _load_telemetry(tmp_path, "A")

        assert telemetry["provider"] == "claude"
        assert telemetry["provider_model"] == "claude-sonnet-4-6"

    @pytest.mark.asyncio
    async def test_wave_t_telemetry_uses_orchestrator_model(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = _config(model="claude-sonnet-4-6")

        async def _build_prompt(**kwargs: object) -> str:
            return f"wave {kwargs['wave']}"

        async def _sdk_call(**_: object) -> float:
            return 1.0

        async def _compile_check(**_: object) -> dict[str, object]:
            return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

        async def _node_tests(cwd: str, subdir: str, timeout: float):
            return False, 0, 0, ""

        monkeypatch.setattr(wave_executor_module, "_run_node_tests", _node_tests)

        result = await _execute_wave_t(
            execute_sdk_call=_sdk_call,
            build_wave_prompt=_build_prompt,
            run_compile_check=_compile_check,
            milestone=_milestone(),
            ir={"acceptance_criteria": []},
            config=cfg,
            cwd=str(tmp_path),
            template="full_stack",
            wave_artifacts={},
            dependency_artifacts={},
            scaffolded_files=[],
        )
        save_wave_telemetry(result, str(tmp_path), "M1")
        telemetry = _load_telemetry(tmp_path, "T")

        assert telemetry["provider"] == "claude"
        assert telemetry["provider_model"] == "claude-sonnet-4-6"

    @pytest.mark.asyncio
    async def test_codex_wedge_then_claude_fallback_reports_claude_model(self, tmp_path: Path) -> None:
        cfg = _config(model="claude-sonnet-4-6")

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

        transport = types.SimpleNamespace(
            is_codex_available=lambda: True,
            execute_codex=AsyncMock(side_effect=_wedge_forever),
        )

        async def _claude_cb(prompt: str, **_: object) -> float:
            (tmp_path / "claude-fallback.ts").write_text("export const fallback = true;\n", encoding="utf-8")
            return 0.02

        result = await _execute_wave_sdk(
            execute_sdk_call=_claude_cb,
            wave_letter="B",
            prompt="wire backend",
            config=cfg,
            cwd=str(tmp_path),
            milestone=_milestone(),
            provider_routing=_routing(wave_letter="B", transport=transport),
        )
        save_wave_telemetry(result, str(tmp_path), "M1")
        telemetry = _load_telemetry(tmp_path, "B")

        assert telemetry["provider"] == "claude"
        assert telemetry["provider_model"] == "claude-sonnet-4-6"
        assert telemetry["provider_model"] != "gpt-5.4"
        assert telemetry["fallback_used"] is True
        assert telemetry["fallback_reason"]

    @pytest.mark.asyncio
    async def test_codex_success_keeps_codex_provider_model(self, tmp_path: Path) -> None:
        cfg = _config(model="claude-sonnet-4-6")

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

        async def _claude_cb(prompt: str, **_: object) -> float:
            return 0.02

        result = await _execute_wave_sdk(
            execute_sdk_call=_claude_cb,
            wave_letter="B",
            prompt="wire backend",
            config=cfg,
            cwd=str(tmp_path),
            milestone=_milestone(),
            provider_routing=_routing(wave_letter="B", transport=transport),
        )
        save_wave_telemetry(result, str(tmp_path), "M1")
        telemetry = _load_telemetry(tmp_path, "B")

        assert telemetry["provider"] == "codex"
        assert telemetry["provider_model"] == "gpt-5.4"
        assert telemetry["fallback_used"] is False

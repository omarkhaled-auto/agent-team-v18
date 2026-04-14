"""Exhaustive tests for multi-provider wave execution (v18.1).

Covers:
- codex_transport.py   — config, result, prerequisites, CODEX_HOME, JSONL parsing,
                         token/cost accounting, message extraction, success detection
- provider_router.py   — WaveProviderMap, snapshot/rollback, provider dispatch,
                         normalize_code_style, classify_fix_provider
- codex_prompts.py     — prompt wrapping per wave letter
- wave_executor.py     — backward compat, provider routing path, telemetry
- config.py            — V18Config defaults
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_team_v15.codex_transport import (
    CodexConfig,
    CodexResult,
    _check_success,
    _compute_cost,
    _extract_final_message,
    _extract_token_usage,
    _parse_jsonl,
    check_prerequisites,
    cleanup_codex_home,
    create_codex_home,
    execute_codex,
    is_codex_available,
)
from agent_team_v15.codex_prompts import (
    CODEX_WAVE_B_PREAMBLE,
    CODEX_WAVE_B_SUFFIX,
    CODEX_WAVE_D_PREAMBLE,
    CODEX_WAVE_D_SUFFIX,
    wrap_prompt_for_codex,
)
from agent_team_v15.provider_router import (
    WaveProviderMap,
    _normalize_code_style,
    classify_fix_provider,
    execute_wave_with_provider,
    rollback_from_snapshot,
    snapshot_for_rollback,
)
from agent_team_v15.wave_executor import (
    CheckpointDiff,
    WaveCheckpoint,
    WaveResult,
    _create_checkpoint,
    _diff_checkpoints,
    _execute_wave_sdk,
    execute_milestone_waves,
    save_wave_telemetry,
)
from agent_team_v15.config import V18Config, load_config


# ======================================================================
# Helpers / Lightweight fakes
# ======================================================================

@dataclass
class _FakeCheckpoint:
    """Minimal checkpoint stand-in for router tests."""
    wave: str = ""
    timestamp: str = ""
    file_manifest: dict[str, str] = field(default_factory=dict)


class _FakeStreamStdin:
    def __init__(self) -> None:
        self.payload = b""
        self.closed = False

    def write(self, data: bytes) -> None:
        self.payload += data

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


@dataclass
class _FakeDiff:
    created: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)


def _make_checkpoint(manifest: dict[str, str]) -> _FakeCheckpoint:
    return _FakeCheckpoint(wave="test", timestamp="t0", file_manifest=manifest)


def _fake_diff(_pre: Any, _post: Any) -> _FakeDiff:
    return _FakeDiff()


# ======================================================================
# TRANSPORT TESTS — CodexConfig / CodexResult
# ======================================================================

class TestCodexConfig:
    def test_defaults(self):
        cfg = CodexConfig()
        assert cfg.model == "gpt-5.4"
        assert cfg.timeout_seconds == 5400
        assert cfg.max_retries == 1
        assert cfg.reasoning_effort == "high"
        assert cfg.context7_enabled is True
        assert cfg.context7_package == "@upstash/context7-mcp"
        # Both old and new model names should have pricing entries.
        assert "gpt-5.4" in cfg.pricing
        assert "gpt-5.1-codex-max" in cfg.pricing

    def test_custom_values(self):
        cfg = CodexConfig(model="custom-model", timeout_seconds=600, max_retries=3)
        assert cfg.model == "custom-model"
        assert cfg.timeout_seconds == 600
        assert cfg.max_retries == 3


class TestCodexResult:
    def test_defaults(self):
        r = CodexResult()
        assert r.success is False
        assert r.exit_code == -1
        assert r.duration_seconds == 0.0
        assert r.input_tokens == 0
        assert r.output_tokens == 0
        assert r.reasoning_tokens == 0
        assert r.cached_input_tokens == 0
        assert r.cost_usd == 0.0
        assert r.model == ""
        assert r.files_created == []
        assert r.files_modified == []
        assert r.final_message == ""
        assert r.error == ""
        assert r.retry_count == 0

    def test_independent_list_defaults(self):
        """Each instance gets its own list — no shared mutable default."""
        a = CodexResult()
        b = CodexResult()
        a.files_created.append("foo.py")
        assert b.files_created == []


# ======================================================================
# TRANSPORT TESTS — Prerequisite checks
# ======================================================================

class TestIsCodexAvailable:
    def test_true(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/codex" if cmd == "codex" else None)
        assert is_codex_available() is True

    def test_false(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda _cmd: None)
        assert is_codex_available() is False


class TestCheckPrerequisites:
    def test_all_missing(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda _cmd: None)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("CODEX_API_KEY", raising=False)

        import subprocess as _sp

        def _raise_fnf(*_a, **_k):
            raise FileNotFoundError("node not found")

        monkeypatch.setattr(_sp, "check_output", _raise_fnf)

        issues = check_prerequisites()
        assert len(issues) >= 2  # codex missing + node missing
        assert any("codex" in i.lower() for i in issues)
        assert any("node" in i.lower() for i in issues)

    def test_all_present(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda _cmd: "/usr/bin/codex")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        import subprocess as _sp
        monkeypatch.setattr(_sp, "check_output", lambda *a, **kw: "v20.11.0")

        issues = check_prerequisites()
        assert issues == []

    def test_node_too_old(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda _cmd: "/usr/bin/codex")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        import subprocess as _sp
        monkeypatch.setattr(_sp, "check_output", lambda *a, **kw: "v16.3.0")

        issues = check_prerequisites()
        assert any("18" in i for i in issues)

    def test_missing_api_key_is_not_blocking(self, monkeypatch):
        """Local codex auth may come from the CLI, so env keys are not mandatory here."""
        monkeypatch.setattr(shutil, "which", lambda _cmd: "/usr/bin/codex")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("CODEX_API_KEY", raising=False)

        import subprocess as _sp
        monkeypatch.setattr(_sp, "check_output", lambda *a, **kw: "v20.0.0")

        issues = check_prerequisites()
        assert issues == []


# ======================================================================
# TRANSPORT TESTS — CODEX_HOME management
# ======================================================================

class TestCreateCodexHome:
    """Tests run with an isolated HOME so we don't inherit the developer's
    real ~/.codex/config.toml during create_codex_home()."""

    @pytest.fixture(autouse=True)
    def _isolated_home(self, tmp_path, monkeypatch):
        fake_home = tmp_path / "fake_home"
        (fake_home / ".codex").mkdir(parents=True)
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        yield fake_home

    def test_creates_dir_with_config(self):
        cfg = CodexConfig(model="test-model", reasoning_effort="medium")
        home = create_codex_home(cfg)
        try:
            assert home.is_dir()
            config_toml = (home / "config.toml").read_text(encoding="utf-8")
            assert 'model = "test-model"' in config_toml
            assert 'model_reasoning_effort = "medium"' in config_toml
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_context7_section_present(self):
        cfg = CodexConfig(context7_enabled=True)
        home = create_codex_home(cfg)
        try:
            config_toml = (home / "config.toml").read_text(encoding="utf-8")
            assert "[mcp_servers.context7]" in config_toml
            assert 'command = "npx"' in config_toml
            assert cfg.context7_package in config_toml
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_context7_section_absent(self):
        cfg = CodexConfig(context7_enabled=False)
        home = create_codex_home(cfg)
        try:
            config_toml = (home / "config.toml").read_text(encoding="utf-8")
            assert "mcp_servers" not in config_toml
        finally:
            shutil.rmtree(home, ignore_errors=True)


class TestCleanupCodexHome:
    def test_removes_dir(self, tmp_path):
        target = tmp_path / "codex_home_test"
        target.mkdir()
        (target / "config.toml").write_text("model = 'x'\n")
        cleanup_codex_home(target)
        assert not target.exists()

    def test_missing_dir_no_error(self, tmp_path):
        missing = tmp_path / "does_not_exist"
        cleanup_codex_home(missing)  # should not raise


# ======================================================================
# TRANSPORT TESTS — JSONL parsing
# ======================================================================

class TestParseJsonl:
    def test_valid_lines(self):
        output = '{"type":"a","data":1}\n{"type":"b","data":2}\n'
        events = _parse_jsonl(output)
        assert len(events) == 2
        assert events[0] == {"type": "a", "data": 1}
        assert events[1] == {"type": "b", "data": 2}

    def test_mixed_valid_invalid(self):
        output = 'not json\n{"valid":true}\ngarbage\n{"also":"valid"}\n'
        events = _parse_jsonl(output)
        assert len(events) == 2
        assert events[0]["valid"] is True
        assert events[1]["also"] == "valid"

    def test_empty_input(self):
        assert _parse_jsonl("") == []

    def test_blank_lines_skipped(self):
        output = "\n  \n  \n"
        assert _parse_jsonl(output) == []

    def test_single_line(self):
        events = _parse_jsonl('{"k":"v"}')
        assert events == [{"k": "v"}]


# ======================================================================
# TRANSPORT TESTS — Token usage extraction
# ======================================================================

class TestExtractTokenUsage:
    def test_single_event(self):
        result = CodexResult()
        events = [
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 500,
                    "reasoning_tokens": 200,
                    "cached_input_tokens": 300,
                },
            },
        ]
        _extract_token_usage(result, events)
        assert result.input_tokens == 1000
        assert result.output_tokens == 500
        assert result.reasoning_tokens == 200
        assert result.cached_input_tokens == 300

    def test_multiple_events(self):
        result = CodexResult()
        events = [
            {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 50}},
            {"type": "turn.completed", "usage": {"input_tokens": 200, "output_tokens": 75, "reasoning_tokens": 10}},
        ]
        _extract_token_usage(result, events)
        assert result.input_tokens == 300
        assert result.output_tokens == 125
        assert result.reasoning_tokens == 10

    def test_no_usage_key(self):
        result = CodexResult()
        events = [{"type": "turn.completed"}]
        _extract_token_usage(result, events)
        assert result.input_tokens == 0
        assert result.output_tokens == 0

    def test_usage_not_dict(self):
        result = CodexResult()
        events = [{"type": "turn.completed", "usage": "invalid"}]
        _extract_token_usage(result, events)
        assert result.input_tokens == 0

    def test_missing_subfields_default_to_zero(self):
        result = CodexResult()
        events = [{"usage": {"input_tokens": 42}}]
        _extract_token_usage(result, events)
        assert result.input_tokens == 42
        assert result.output_tokens == 0
        assert result.reasoning_tokens == 0
        assert result.cached_input_tokens == 0


# ======================================================================
# TRANSPORT TESTS — Cost computation
# ======================================================================

class TestComputeCost:
    def test_separates_cached(self):
        """uncached = input - cached. No double-counting."""
        result = CodexResult(
            input_tokens=500_000,
            cached_input_tokens=100_000,
            output_tokens=150_000,
        )
        cfg = CodexConfig()  # default pricing for gpt-5.1-codex-max

        cost = _compute_cost(result, cfg)

        # uncached_input = 500K - 100K = 400K
        # cost = 400K * 2.00 / 1M + 100K * 0.50 / 1M + 150K * 8.00 / 1M
        #      = 0.8 + 0.05 + 1.2 = 2.05
        assert cost == pytest.approx(2.05, abs=1e-6)

    def test_unknown_model(self):
        result = CodexResult(input_tokens=100, output_tokens=50)
        cfg = CodexConfig(model="unknown-model-xyz")
        cost = _compute_cost(result, cfg)
        assert cost == 0.0

    def test_zero_tokens(self):
        result = CodexResult()
        cfg = CodexConfig()
        assert _compute_cost(result, cfg) == 0.0

    def test_all_cached(self):
        """When all input is cached, uncached is 0."""
        result = CodexResult(input_tokens=1000, cached_input_tokens=1000, output_tokens=0)
        cfg = CodexConfig()
        cost = _compute_cost(result, cfg)
        # uncached = 0, cached = 1000 * 0.50 / 1M
        expected = 1000 * 0.50 / 1_000_000
        assert cost == pytest.approx(expected, abs=1e-6)

    def test_cached_greater_than_input(self):
        """Edge: cached > input — uncached clamped to 0 via max()."""
        result = CodexResult(input_tokens=100, cached_input_tokens=200, output_tokens=0)
        cfg = CodexConfig()
        cost = _compute_cost(result, cfg)
        # uncached = max(100-200, 0) = 0
        expected = 200 * 0.50 / 1_000_000
        assert cost == pytest.approx(expected, abs=1e-6)


# ======================================================================
# TRANSPORT TESTS — Final message extraction
# ======================================================================

class TestExtractFinalMessage:
    def test_item_completed_agent_message(self):
        result = CodexResult()
        events = [
            {
                "type": "item.completed",
                "item": {"agent_message": "A" * 30},
            },
        ]
        _extract_final_message(result, events)
        assert result.final_message == "A" * 30

    def test_item_completed_content_array(self):
        result = CodexResult()
        events = [
            {
                "type": "item.completed",
                "item": {
                    "content": [{"text": "B" * 25}],
                },
            },
        ]
        _extract_final_message(result, events)
        assert result.final_message == "B" * 25

    def test_fallback_text_field(self):
        result = CodexResult()
        events = [
            {"text": "C" * 50},
        ]
        _extract_final_message(result, events)
        assert result.final_message == "C" * 50

    def test_fallback_message_field(self):
        result = CodexResult()
        events = [
            {"message": "D" * 50},
        ]
        _extract_final_message(result, events)
        assert result.final_message == "D" * 50

    def test_short_text_ignored(self):
        """Text shorter than thresholds is skipped."""
        result = CodexResult()
        events = [
            {"type": "item.completed", "item": {"agent_message": "short"}},
            {"text": "too short"},
        ]
        _extract_final_message(result, events)
        assert result.final_message == ""

    def test_latest_event_preferred(self):
        """Reverse walk means later events win."""
        result = CodexResult()
        events = [
            {"type": "item.completed", "item": {"agent_message": "E" * 30}},
            {"type": "item.completed", "item": {"agent_message": "F" * 30}},
        ]
        _extract_final_message(result, events)
        # Reversed walk — second event checked first
        assert result.final_message == "F" * 30

    def test_empty_events(self):
        result = CodexResult()
        _extract_final_message(result, [])
        assert result.final_message == ""


# ======================================================================
# TRANSPORT TESTS — Success detection
# ======================================================================

class TestCheckSuccess:
    def test_turn_completed(self):
        events = [{"type": "turn.completed"}]
        success, error = _check_success(events)
        assert success is True
        assert error == ""

    def test_turn_failed_dict_error(self):
        events = [{"type": "turn.failed", "error": {"message": "rate limited"}}]
        success, error = _check_success(events)
        assert success is False
        assert "rate limited" in error

    def test_turn_failed_str_error(self):
        events = [{"type": "turn.failed", "error": "string error"}]
        success, error = _check_success(events)
        assert success is False
        assert error == "string error"

    def test_turn_failed_unknown_shape(self):
        events = [{"type": "turn.failed", "error": 42}]
        success, error = _check_success(events)
        assert success is False
        assert "unknown" in error.lower()

    def test_turn_failed_no_message(self):
        events = [{"type": "turn.failed", "error": {}}]
        success, error = _check_success(events)
        assert success is False
        assert "no message" in error.lower()

    def test_no_completion_event(self):
        events = [{"type": "something_else"}]
        success, error = _check_success(events)
        assert success is False
        assert "no completion event" in error.lower()

    def test_empty_events(self):
        success, error = _check_success([])
        assert success is False

    def test_failed_before_completed(self):
        """turn.failed takes priority even if turn.completed also exists later."""
        events = [
            {"type": "turn.failed", "error": {"message": "boom"}},
            {"type": "turn.completed"},
        ]
        success, error = _check_success(events)
        assert success is False
        assert "boom" in error


# ======================================================================
# TRANSPORT TESTS — execute_codex (async, mocked subprocess)
# ======================================================================

class TestExecuteCodex:
    @pytest.fixture(autouse=True)
    def _stub_codex_resolution(self, monkeypatch, tmp_path):
        """Force shutil.which("codex") to return a non-.CMD path so the
        Windows shell branch is skipped and create_subprocess_exec stays
        on the mocked path.  Also isolate HOME so create_codex_home
        doesn't inherit the developer's real ~/.codex.
        """
        monkeypatch.setattr(shutil, "which", lambda _cmd: "/usr/local/bin/codex")
        fake_home = tmp_path / "fake_home"
        (fake_home / ".codex").mkdir(parents=True)
        monkeypatch.setattr(Path, "home", lambda: fake_home)

    @pytest.mark.asyncio
    async def test_success_path(self, monkeypatch, tmp_path):
        """Successful codex exec with valid JSONL returns success."""
        jsonl_output = json.dumps({"type": "turn.completed", "usage": {
            "input_tokens": 100, "output_tokens": 50,
        }}) + "\n"

        async def _fake_create_subprocess_exec(*cmd, **kw):
            proc = AsyncMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(
                jsonl_output.encode(),
                b"",
            ))
            proc.kill = MagicMock()
            proc.wait = AsyncMock()
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)

        cfg = CodexConfig(max_retries=0)
        home = create_codex_home(cfg)
        try:
            result = await execute_codex("test prompt", str(tmp_path), cfg, home)
            assert result.success is True
            assert result.input_tokens == 100
            assert result.output_tokens == 50
            assert result.model == cfg.model
        finally:
            cleanup_codex_home(home)

    @pytest.mark.asyncio
    async def test_command_uses_validated_exec_flags(self, monkeypatch, tmp_path):
        """Transport uses the validated exec shape: JSON, full-auto, --cd, stdin prompt."""
        captured: dict[str, Any] = {}
        jsonl_output = json.dumps({"type": "turn.completed"}) + "\n"

        async def _fake_create_subprocess_exec(*cmd, **kw):
            captured["cmd"] = list(cmd)
            captured["kwargs"] = kw
            proc = AsyncMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(jsonl_output.encode(), b""))
            proc.kill = MagicMock()
            proc.wait = AsyncMock()
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)

        cfg = CodexConfig(max_retries=0)
        home = create_codex_home(cfg)
        try:
            result = await execute_codex("prompt from stdin", str(tmp_path), cfg, home)
            assert result.success is True
        finally:
            cleanup_codex_home(home)

        cmd = captured["cmd"]
        # cmd[0] is the resolved binary path; the fixture stubs it to
        # "/usr/local/bin/codex".  Validate by suffix instead of equality.
        assert cmd[0].endswith("codex")
        assert cmd[1:4] == ["exec", "--json", "--full-auto"]
        assert "--cd" in cmd
        assert cmd[cmd.index("--cd") + 1] == str(tmp_path)
        assert "-m" in cmd
        assert cmd[cmd.index("-m") + 1] == cfg.model
        assert cmd[-1] == "-"
        assert captured["kwargs"]["stdin"] == asyncio.subprocess.PIPE

    @pytest.mark.asyncio
    async def test_timeout_kills_process(self, monkeypatch, tmp_path):
        """Timeouts kill the spawned codex process and wait for cleanup."""
        proc = AsyncMock()
        proc.returncode = None
        proc.kill = MagicMock()
        proc.wait = AsyncMock()

        async def _slow_communicate(*, input=None):
            await asyncio.sleep(3600)

        proc.communicate = _slow_communicate

        async def _fake_create_subprocess_exec(*cmd, **kw):
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)

        cfg = CodexConfig(max_retries=0, timeout_seconds=0.01)
        home = create_codex_home(cfg)
        try:
            result = await execute_codex("prompt", str(tmp_path), cfg, home)
        finally:
            cleanup_codex_home(home)

        assert result.success is False
        assert "timed out" in result.error.lower()
        proc.kill.assert_called_once()
        proc.wait.assert_awaited()

    @pytest.mark.asyncio
    async def test_retry_aggregates_usage_and_cost(self, monkeypatch, tmp_path):
        """Aggregate usage/cost spans all attempts, not just the final one."""
        outputs = [
            json.dumps({
                "type": "turn.failed",
                "error": {"message": "retry me"},
                "usage": {
                    "input_tokens": 100_000,
                    "output_tokens": 20_000,
                    "cached_input_tokens": 10_000,
                },
            }) + "\n",
            json.dumps({
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 200_000,
                    "output_tokens": 30_000,
                },
            }) + "\n",
        ]

        async def _fake_create_subprocess_exec(*cmd, **kw):
            proc = AsyncMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(outputs.pop(0).encode(), b""))
            proc.kill = MagicMock()
            proc.wait = AsyncMock()
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())

        cfg = CodexConfig(max_retries=1)
        home = create_codex_home(cfg)
        try:
            result = await execute_codex("test prompt", str(tmp_path), cfg, home)
        finally:
            cleanup_codex_home(home)

        assert result.success is True
        assert result.retry_count == 1
        assert result.input_tokens == 300_000
        assert result.output_tokens == 50_000
        assert result.cached_input_tokens == 10_000
        assert result.cost_usd == pytest.approx(0.985, abs=1e-6)

    @pytest.mark.asyncio
    async def test_failure_with_retry(self, monkeypatch, tmp_path):
        """Failed codex exec retries up to max_retries."""
        jsonl_output = json.dumps({"type": "turn.failed", "error": {"message": "fail"}}) + "\n"

        call_count = 0

        async def _fake_create_subprocess_exec(*cmd, **kw):
            nonlocal call_count
            call_count += 1
            proc = AsyncMock()
            proc.returncode = 1
            proc.communicate = AsyncMock(return_value=(jsonl_output.encode(), b""))
            proc.kill = MagicMock()
            proc.wait = AsyncMock()
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)
        # Speed up retry sleep
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())

        cfg = CodexConfig(max_retries=1)
        home = create_codex_home(cfg)
        try:
            result = await execute_codex("test prompt", str(tmp_path), cfg, home)
            assert result.success is False
            assert call_count == 2  # 1 initial + 1 retry
            assert result.retry_count == 1
        finally:
            cleanup_codex_home(home)

    @pytest.mark.asyncio
    async def test_creates_own_home_when_none(self, monkeypatch, tmp_path):
        """When codex_home is None, execute_codex creates and cleans up its own."""
        jsonl_output = json.dumps({"type": "turn.completed"}) + "\n"

        created_homes = []

        original_create = create_codex_home

        def _spy_create(config):
            home = original_create(config)
            created_homes.append(home)
            return home

        monkeypatch.setattr(
            "agent_team_v15.codex_transport.create_codex_home", _spy_create
        )

        async def _fake_create_subprocess_exec(*cmd, **kw):
            proc = AsyncMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(jsonl_output.encode(), b""))
            proc.kill = MagicMock()
            proc.wait = AsyncMock()
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)

        cfg = CodexConfig(max_retries=0)
        result = await execute_codex("prompt", str(tmp_path), cfg, codex_home=None)
        assert result.success is True
        assert len(created_homes) == 1
        # Home should be cleaned up
        assert not created_homes[0].exists()

    @pytest.mark.asyncio
    async def test_progress_callback_streams_jsonl_events(self, monkeypatch, tmp_path):
        """Streaming mode forwards Codex JSONL events to the progress callback."""
        progress_events: list[tuple[str, str]] = []

        def _progress_callback(*, message_type: str = "", tool_name: str = "") -> None:
            progress_events.append((message_type, tool_name))

        async def _fake_create_subprocess_exec(*cmd, **kw):
            proc = types.SimpleNamespace()
            proc.returncode = 0
            proc.kill = MagicMock()
            proc.wait = AsyncMock(return_value=0)
            proc.stdin = _FakeStreamStdin()
            proc.stdout = asyncio.StreamReader()
            proc.stderr = asyncio.StreamReader()
            proc.stdout.feed_data(
                (
                    json.dumps(
                        {
                            "type": "item.completed",
                            "item": {"type": "tool_call", "name": "write"},
                        }
                    )
                    + "\n"
                ).encode()
            )
            proc.stdout.feed_data((json.dumps({"type": "turn.completed"}) + "\n").encode())
            proc.stdout.feed_eof()
            proc.stderr.feed_eof()
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)

        cfg = CodexConfig(max_retries=0)
        home = create_codex_home(cfg)
        try:
            result = await execute_codex(
                "progress prompt",
                str(tmp_path),
                cfg,
                home,
                progress_callback=_progress_callback,
            )
        finally:
            cleanup_codex_home(home)

        assert result.success is True
        assert ("item.completed", "write") in progress_events
        assert any(message_type == "turn.completed" for message_type, _ in progress_events)


# ======================================================================
# ROUTER TESTS — WaveProviderMap
# ======================================================================

class TestWaveProviderMap:
    def test_defaults(self):
        m = WaveProviderMap()
        assert m.A == "claude"
        assert m.B == "codex"
        assert m.C == "python"
        assert m.D == "codex"
        assert m.D5 == "claude"
        assert m.E == "claude"

    def test_provider_for(self):
        m = WaveProviderMap()
        assert m.provider_for("A") == "claude"
        assert m.provider_for("B") == "codex"
        assert m.provider_for("C") == "python"
        assert m.provider_for("D") == "codex"
        assert m.provider_for("D5") == "claude"
        assert m.provider_for("UI") == "claude"
        assert m.provider_for("E") == "claude"

    def test_provider_for_unknown(self):
        m = WaveProviderMap()
        assert m.provider_for("Z") == "claude"  # fallback via getattr default

    def test_custom_map(self):
        m = WaveProviderMap(B="claude", D="codex")
        assert m.provider_for("B") == "claude"
        assert m.provider_for("D") == "codex"

    def test_normalizes_wave_and_provider_names(self):
        m = WaveProviderMap(B="CODEX", D=" CODEX ")
        assert m.provider_for("b") == "codex"
        assert m.provider_for("d") == "codex"

    def test_wave_d5_always_routes_to_claude(self):
        m = WaveProviderMap(D5="codex")
        assert m.provider_for("D5") == "claude"


# ======================================================================
# ROUTER TESTS — Snapshot / Rollback
# ======================================================================

class TestSnapshotForRollback:
    def test_reads_files(self, tmp_path):
        (tmp_path / "a.txt").write_bytes(b"hello")
        (tmp_path / "b.txt").write_bytes(b"world")
        checkpoint = _make_checkpoint({"a.txt": "md5a", "b.txt": "md5b"})

        snap = snapshot_for_rollback(str(tmp_path), checkpoint)
        assert snap["a.txt"] == b"hello"
        assert snap["b.txt"] == b"world"

    def test_missing_file_skipped(self, tmp_path):
        checkpoint = _make_checkpoint({"missing.txt": "md5"})
        snap = snapshot_for_rollback(str(tmp_path), checkpoint)
        assert snap == {}

    def test_empty_manifest(self, tmp_path):
        checkpoint = _make_checkpoint({})
        snap = snapshot_for_rollback(str(tmp_path), checkpoint)
        assert snap == {}


class TestRollbackFromSnapshot:
    def test_deletes_created_files(self, tmp_path):
        # File created by codex that needs to be removed on rollback
        created_file = tmp_path / "new_file.ts"
        created_file.write_text("export const x = 1;")

        diff = _FakeDiff(created=["new_file.ts"])
        rollback_from_snapshot(
            str(tmp_path),
            snapshot={},
            pre_checkpoint=_FakeCheckpoint(),
            post_checkpoint=_FakeCheckpoint(),
            checkpoint_diff=lambda _pre, _post: diff,
        )
        assert not created_file.exists()

    def test_restores_modified_files(self, tmp_path):
        target = tmp_path / "existing.ts"
        target.write_text("modified content")

        original_content = b"original content"
        diff = _FakeDiff(modified=["existing.ts"])

        rollback_from_snapshot(
            str(tmp_path),
            snapshot={"existing.ts": original_content},
            pre_checkpoint=_FakeCheckpoint(),
            post_checkpoint=_FakeCheckpoint(),
            checkpoint_diff=lambda _pre, _post: diff,
        )
        assert target.read_bytes() == original_content

    def test_restores_deleted_files(self, tmp_path):
        # File was deleted by codex — restore from snapshot
        original_content = b"was here"
        diff = _FakeDiff(deleted=["removed.ts"])

        rollback_from_snapshot(
            str(tmp_path),
            snapshot={"removed.ts": original_content},
            pre_checkpoint=_FakeCheckpoint(),
            post_checkpoint=_FakeCheckpoint(),
            checkpoint_diff=lambda _pre, _post: diff,
        )
        assert (tmp_path / "removed.ts").read_bytes() == original_content

    def test_modified_not_in_snapshot_skipped(self, tmp_path):
        target = tmp_path / "no_snap.ts"
        target.write_text("keep me")
        diff = _FakeDiff(modified=["no_snap.ts"])

        rollback_from_snapshot(
            str(tmp_path),
            snapshot={},
            pre_checkpoint=_FakeCheckpoint(),
            post_checkpoint=_FakeCheckpoint(),
            checkpoint_diff=lambda _pre, _post: diff,
        )
        assert target.read_text() == "keep me"


# ======================================================================
# ROUTER TESTS — execute_wave_with_provider
# ======================================================================

class TestExecuteWaveWithProvider:
    @pytest.mark.asyncio
    async def test_claude_path(self):
        """Wave A routes to Claude callback."""
        async def _claude_cb(prompt, **kw):
            return 0.05

        result = await execute_wave_with_provider(
            wave_letter="A",
            prompt="do stuff",
            cwd="/fake",
            config={},
            provider_map=WaveProviderMap(),
            claude_callback=_claude_cb,
            claude_callback_kwargs={},
            checkpoint_create=lambda label, cwd: _FakeCheckpoint(),
            checkpoint_diff=_fake_diff,
        )
        assert result["provider"] == "claude"
        assert result["cost"] == pytest.approx(0.05)
        assert result["fallback_used"] is False

    @pytest.mark.asyncio
    async def test_python_noop(self):
        """Wave C (python) returns noop result."""
        result = await execute_wave_with_provider(
            wave_letter="C",
            prompt="generate contracts",
            cwd="/fake",
            config={},
            provider_map=WaveProviderMap(),
            claude_callback=lambda **kw: 0,
            claude_callback_kwargs={},
            checkpoint_create=lambda label, cwd: _FakeCheckpoint(),
            checkpoint_diff=_fake_diff,
        )
        assert result["provider"] == "python"
        assert result["cost"] == 0.0

    @pytest.mark.asyncio
    async def test_codex_path_success(self, tmp_path):
        """Wave B routes to Codex when available and succeeds."""
        codex_result = CodexResult(
            success=True,
            model="gpt-5.1-codex-max",
            cost_usd=0.10,
            input_tokens=500,
            output_tokens=200,
            reasoning_tokens=50,
        )

        transport = types.SimpleNamespace(
            is_codex_available=lambda: True,
            execute_codex=AsyncMock(return_value=codex_result),
        )

        # Setup: create a file so checkpoint works
        (tmp_path / "file.ts").write_text("code")

        pre_cp = _FakeCheckpoint(file_manifest={"file.ts": "hash1"})
        post_cp = _FakeCheckpoint(file_manifest={"file.ts": "hash2", "new.ts": "hash3"})
        cp_calls = []

        def _cp_create(label, cwd):
            cp_calls.append(label)
            if "post" in label:
                return post_cp
            return pre_cp

        def _cp_diff(pre, post):
            return _FakeDiff(created=["new.ts"], modified=["file.ts"])

        result = await execute_wave_with_provider(
            wave_letter="B",
            prompt="wire backend",
            cwd=str(tmp_path),
            config={},
            provider_map=WaveProviderMap(),
            claude_callback=lambda **kw: 0,
            claude_callback_kwargs={},
            codex_transport_module=transport,
            codex_config=CodexConfig(),
            checkpoint_create=_cp_create,
            checkpoint_diff=_cp_diff,
        )
        assert result["provider"] == "codex"
        assert result["cost"] == pytest.approx(0.10)
        assert result["fallback_used"] is False
        assert result["input_tokens"] == 500
        assert result["files_created"] == ["new.ts"]
        assert result["files_modified"] == ["file.ts"]

    @pytest.mark.asyncio
    async def test_codex_unavailable_fallback(self):
        """Wave B falls back to Claude when Codex not available."""
        async def _claude_cb(prompt, **kw):
            return 0.03

        transport = types.SimpleNamespace(
            is_codex_available=lambda: False,
        )

        result = await execute_wave_with_provider(
            wave_letter="B",
            prompt="wire backend",
            cwd="/fake",
            config={},
            provider_map=WaveProviderMap(),
            claude_callback=_claude_cb,
            claude_callback_kwargs={},
            codex_transport_module=transport,
            checkpoint_create=lambda label, cwd: _FakeCheckpoint(),
            checkpoint_diff=_fake_diff,
        )
        assert result["provider"] == "claude"
        assert result["fallback_used"] is True
        assert "not available" in result["fallback_reason"].lower()

    @pytest.mark.asyncio
    async def test_codex_failure_rollback_and_fallback(self, tmp_path):
        """Codex failure triggers checkpoint rollback then Claude fallback."""
        codex_result = CodexResult(
            success=False,
            exit_code=1,
            error="codex crashed",
            model="gpt-5.1-codex-max",
            retry_count=1,
            cost_usd=0.11,
            input_tokens=400,
            output_tokens=120,
            reasoning_tokens=30,
        )

        transport = types.SimpleNamespace(
            is_codex_available=lambda: True,
            execute_codex=AsyncMock(return_value=codex_result),
        )

        # Create a file that codex "modified"
        target = tmp_path / "app.ts"
        target.write_text("original")

        pre_cp = _FakeCheckpoint(file_manifest={"app.ts": "hash1"})

        async def _claude_cb(prompt, **kw):
            return 0.02

        cp_count = [0]

        def _cp_create(label, cwd):
            cp_count[0] += 1
            return _FakeCheckpoint(file_manifest={"app.ts": "hash1"})

        result = await execute_wave_with_provider(
            wave_letter="B",
            prompt="wire backend",
            cwd=str(tmp_path),
            config={},
            provider_map=WaveProviderMap(),
            claude_callback=_claude_cb,
            claude_callback_kwargs={},
            codex_transport_module=transport,
            codex_config=CodexConfig(),
            checkpoint_create=_cp_create,
            checkpoint_diff=_fake_diff,
        )
        assert result["provider"] == "claude"
        assert result["fallback_used"] is True
        assert "codex failed" in result["fallback_reason"].lower()
        assert result["provider_model"] == "gpt-5.1-codex-max"
        assert result["retry_count"] == 1
        assert result["input_tokens"] == 400
        assert result["output_tokens"] == 120
        assert result["reasoning_tokens"] == 30
        assert result["cost"] == pytest.approx(0.13)

    @pytest.mark.asyncio
    async def test_codex_exception_rollback_and_fallback(self, tmp_path):
        """Codex raising an exception triggers rollback + Claude fallback."""
        transport = types.SimpleNamespace(
            is_codex_available=lambda: True,
            execute_codex=AsyncMock(side_effect=RuntimeError("subprocess exploded")),
        )

        async def _claude_cb(prompt, **kw):
            return 0.01

        result = await execute_wave_with_provider(
            wave_letter="B",
            prompt="wire backend",
            cwd=str(tmp_path),
            config={},
            provider_map=WaveProviderMap(),
            claude_callback=_claude_cb,
            claude_callback_kwargs={},
            codex_transport_module=transport,
            codex_config=CodexConfig(),
            checkpoint_create=lambda label, cwd: _FakeCheckpoint(),
            checkpoint_diff=_fake_diff,
        )
        assert result["provider"] == "claude"
        assert result["fallback_used"] is True
        assert "raised" in result["fallback_reason"].lower()

    @pytest.mark.asyncio
    async def test_codex_success_with_no_changes_falls_back(self, tmp_path):
        """A successful Codex run with zero tracked changes is treated as fallback-worthy."""
        codex_result = CodexResult(
            success=True,
            model="gpt-5.1-codex-max",
            cost_usd=0.10,
            input_tokens=500,
            output_tokens=200,
            reasoning_tokens=50,
        )

        transport = types.SimpleNamespace(
            is_codex_available=lambda: True,
            execute_codex=AsyncMock(return_value=codex_result),
        )

        async def _claude_cb(prompt, **kw):
            return 0.02

        result = await execute_wave_with_provider(
            wave_letter="B",
            prompt="wire backend",
            cwd=str(tmp_path),
            config={},
            provider_map=WaveProviderMap(),
            claude_callback=_claude_cb,
            claude_callback_kwargs={},
            codex_transport_module=transport,
            codex_config=CodexConfig(),
            checkpoint_create=lambda label, cwd: _FakeCheckpoint(),
            checkpoint_diff=lambda pre, post: _FakeDiff(),
        )
        assert result["provider"] == "claude"
        assert result["fallback_used"] is True
        assert "no tracked file changes" in result["fallback_reason"].lower()
        assert result["provider_model"] == "gpt-5.1-codex-max"
        assert result["input_tokens"] == 500
        assert result["cost"] == pytest.approx(0.12)

    @pytest.mark.asyncio
    async def test_manual_wave_d_codex_path_works(self, tmp_path):
        """If provider_map_d is set to Codex manually, the Codex path still works."""
        codex_result = CodexResult(
            success=True,
            model="gpt-5.1-codex-max",
            cost_usd=0.04,
        )

        transport = types.SimpleNamespace(
            is_codex_available=lambda: True,
            execute_codex=AsyncMock(return_value=codex_result),
        )

        result = await execute_wave_with_provider(
            wave_letter="D",
            prompt="replace fetches with generated client",
            cwd=str(tmp_path),
            config={},
            provider_map=WaveProviderMap(D="CODEX"),
            claude_callback=lambda **kw: 0,
            claude_callback_kwargs={},
            codex_transport_module=transport,
            codex_config=CodexConfig(),
            checkpoint_create=lambda label, cwd: _FakeCheckpoint(file_manifest={"app.tsx": "hash"}),
            checkpoint_diff=lambda pre, post: _FakeDiff(modified=["app.tsx"]),
        )

        assert result["provider"] == "codex"
        assert result["fallback_used"] is False
        codex_prompt = transport.execute_codex.await_args.args[0]
        assert CODEX_WAVE_D_PREAMBLE in codex_prompt

    @pytest.mark.asyncio
    async def test_wave_d5_always_uses_claude_even_if_map_requests_codex(self, tmp_path):
        transport = types.SimpleNamespace(
            is_codex_available=lambda: True,
            execute_codex=AsyncMock(),
        )

        async def _claude_cb(prompt, **kw):
            return 0.03

        result = await execute_wave_with_provider(
            wave_letter="D5",
            prompt="polish the UI without touching functionality",
            cwd=str(tmp_path),
            config={},
            provider_map=WaveProviderMap(D="codex", D5="codex"),
            claude_callback=_claude_cb,
            claude_callback_kwargs={},
            codex_transport_module=transport,
            codex_config=CodexConfig(),
            checkpoint_create=lambda label, cwd: _FakeCheckpoint(),
            checkpoint_diff=_fake_diff,
        )

        assert result["provider"] == "claude"
        assert result["fallback_used"] is False
        transport.execute_codex.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_transport_module_fallback(self):
        """When codex_transport_module is None, falls back to Claude."""
        async def _claude_cb(prompt, **kw):
            return 0.04

        result = await execute_wave_with_provider(
            wave_letter="B",
            prompt="wire backend",
            cwd="/fake",
            config={},
            provider_map=WaveProviderMap(),
            claude_callback=_claude_cb,
            claude_callback_kwargs={},
            codex_transport_module=None,
            checkpoint_create=lambda label, cwd: _FakeCheckpoint(),
            checkpoint_diff=_fake_diff,
        )
        assert result["provider"] == "claude"
        assert result["fallback_used"] is True
        assert "not provided" in result["fallback_reason"].lower()

    @pytest.mark.asyncio
    async def test_sync_claude_callback_works(self):
        """Sync callbacks are also supported — they get awaited if needed."""
        def _sync_cb(prompt, **kw):
            return 0.07

        result = await execute_wave_with_provider(
            wave_letter="A",
            prompt="plan",
            cwd="/fake",
            config={},
            provider_map=WaveProviderMap(),
            claude_callback=_sync_cb,
            claude_callback_kwargs={},
            checkpoint_create=lambda label, cwd: _FakeCheckpoint(),
            checkpoint_diff=_fake_diff,
        )
        assert result["provider"] == "claude"
        assert result["cost"] == pytest.approx(0.07)


# ======================================================================
# ROUTER TESTS — _normalize_code_style
# ======================================================================

class TestNormalizeCodeStyle:
    @pytest.mark.asyncio
    async def test_non_fatal_on_missing_config(self, tmp_path):
        """Normalization does not raise even if no prettier/eslint config exists."""
        # No .prettierrc or .eslintrc present
        await _normalize_code_style(str(tmp_path), ["app.ts", "index.tsx"])
        # Should not raise

    @pytest.mark.asyncio
    async def test_non_styleable_files_skipped(self, tmp_path):
        """Files without style extensions are skipped."""
        (tmp_path / ".prettierrc").write_text("{}")
        # .py files are not in _STYLE_EXTENSIONS
        await _normalize_code_style(str(tmp_path), ["main.py", "test.rb"])
        # Should be a no-op, no error


# ======================================================================
# ROUTER TESTS — classify_fix_provider
# ======================================================================

class TestClassifyFixProvider:
    def test_issue_type_wiring(self):
        assert classify_fix_provider([], "wiring issue") == "codex"

    def test_issue_type_styling(self):
        assert classify_fix_provider([], "styling problem") == "claude"

    def test_issue_type_controller(self):
        assert classify_fix_provider([], "controller endpoint missing") == "codex"

    def test_issue_type_animation(self):
        assert classify_fix_provider([], "animation glitch") == "claude"

    def test_file_heuristics_backend(self):
        files = ["src/server/user.service.ts", "src/server/auth.controller.ts"]
        assert classify_fix_provider(files, "") == "codex"

    def test_file_heuristics_frontend(self):
        files = ["src/app/components/LoginForm.tsx", "src/app/hooks/useAuth.ts"]
        assert classify_fix_provider(files, "") == "claude"

    def test_issue_overrides_files(self):
        """issue_type='wiring' returns 'codex' even for frontend files."""
        files = ["src/components/Button.tsx", "src/pages/Home.tsx"]
        assert classify_fix_provider(files, "wiring") == "codex"

    def test_empty_inputs(self):
        assert classify_fix_provider([], "") == "claude"  # default when no signal

    def test_mixed_files_codex_wins(self):
        files = [
            "src/server/api/route.ts",
            "src/server/middleware/auth.ts",
            "src/app/page.tsx",
        ]
        # server (1) + api (1) + route (1) + middleware (1) = 4 codex vs page(1) + app(1) = 2 claude
        assert classify_fix_provider(files, "") == "codex"

    def test_module_keyword(self):
        assert classify_fix_provider([], "module registration") == "codex"

    def test_i18n_keyword(self):
        assert classify_fix_provider([], "i18n translation") == "claude"


# ======================================================================
# PROMPT TESTS — wrap_prompt_for_codex
# ======================================================================

class TestWrapPromptForCodex:
    def test_wave_b(self):
        original = "Wire the user service."
        wrapped = wrap_prompt_for_codex("B", original)
        assert wrapped.startswith(CODEX_WAVE_B_PREAMBLE)
        assert wrapped.endswith(CODEX_WAVE_B_SUFFIX)
        assert original in wrapped

    def test_wave_d(self):
        original = "Replace manual fetch calls."
        wrapped = wrap_prompt_for_codex("D", original)
        assert wrapped.startswith(CODEX_WAVE_D_PREAMBLE)
        assert wrapped.endswith(CODEX_WAVE_D_SUFFIX)
        assert original in wrapped

    def test_wave_a_passthrough(self):
        original = "Scaffold the project."
        assert wrap_prompt_for_codex("A", original) == original

    def test_wave_c_passthrough(self):
        original = "Generate contracts."
        assert wrap_prompt_for_codex("C", original) == original

    def test_wave_e_passthrough(self):
        original = "Run integration tests."
        assert wrap_prompt_for_codex("E", original) == original

    def test_lowercase_letter(self):
        """Lowercase letters also match (via .upper())."""
        original = "wire backend"
        wrapped = wrap_prompt_for_codex("b", original)
        assert CODEX_WAVE_B_PREAMBLE in wrapped

    def test_preserves_original_verbatim(self):
        original = "A complex prompt with special chars: <>&\"\n\ttabs"
        wrapped = wrap_prompt_for_codex("B", original)
        assert original in wrapped

    def test_structure_preamble_original_suffix(self):
        original = "UNIQUE_MARKER"
        wrapped = wrap_prompt_for_codex("B", original)
        parts = wrapped.split("UNIQUE_MARKER")
        assert len(parts) == 2
        assert parts[0] == CODEX_WAVE_B_PREAMBLE
        assert parts[1] == CODEX_WAVE_B_SUFFIX

    def test_wave_b_wrapper_mentions_active_backend_tree_and_barrels(self):
        wrapped = wrap_prompt_for_codex("B", "backend prompt")
        assert "Never create a parallel" in wrapped
        assert "index.ts" in wrapped

    def test_wave_d_wrapper_mentions_state_completeness_and_client_override(self):
        wrapped = wrap_prompt_for_codex("D", "frontend prompt")
        assert "generic stack instruction that mentions" in wrapped
        assert "loading, error, empty, and success states" in wrapped


# ======================================================================
# CONFIG TESTS — V18Config defaults
# ======================================================================

class TestV18ConfigDefaults:
    def test_provider_routing_disabled(self):
        cfg = V18Config()
        assert cfg.provider_routing is False

    def test_codex_model(self):
        cfg = V18Config()
        assert cfg.codex_model == "gpt-5.4"

    def test_codex_timeout(self):
        assert V18Config().codex_timeout_seconds == 5400

    def test_codex_timeout_floor(self):
        assert V18Config().codex_timeout_seconds >= 2700

    def test_codex_max_retries(self):
        assert V18Config().codex_max_retries == 1

    def test_codex_reasoning_effort(self):
        assert V18Config().codex_reasoning_effort == "high"

    def test_codex_web_search(self):
        assert V18Config().codex_web_search == "disabled"

    def test_codex_context7(self):
        assert V18Config().codex_context7_enabled is True

    def test_provider_map_b(self):
        assert V18Config().provider_map_b == "codex"

    def test_provider_map_d(self):
        assert V18Config().provider_map_d == "codex"

    def test_wave_d5_enabled(self):
        assert V18Config().wave_d5_enabled is True


class TestV18ConfigLoading:
    def test_quoted_values_are_coerced(self, tmp_path, monkeypatch):
        (tmp_path / "config.yaml").write_text(
            "\n".join([
                "v18:",
                "  provider_routing: 'false'",
                "  codex_timeout_seconds: '900'",
                "  codex_max_retries: '2'",
                "  codex_context7_enabled: 'no'",
                "  provider_map_b: 'CODEX'",
                "  provider_map_d: ' CODEX '",
                "  wave_d5_enabled: 'no'",
                "  wave_idle_timeout_seconds: '120'",
                "  wave_watchdog_poll_seconds: '5'",
                "  wave_watchdog_max_retries: '3'",
                "  sub_agent_idle_timeout_seconds: '60'",
                "  wave_t_enabled: 'yes'",
                "  wave_t_max_fix_iterations: '4'",
            ]),
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)

        cfg, _ = load_config()

        assert cfg.v18.provider_routing is False
        assert cfg.v18.codex_timeout_seconds == 900
        assert cfg.v18.codex_max_retries == 2
        assert cfg.v18.codex_context7_enabled is False
        assert cfg.v18.provider_map_b == "codex"
        assert cfg.v18.provider_map_d == "codex"
        assert cfg.v18.wave_d5_enabled is False
        assert cfg.v18.wave_idle_timeout_seconds == 120
        assert cfg.v18.wave_watchdog_poll_seconds == 5
        assert cfg.v18.wave_watchdog_max_retries == 3
        assert cfg.v18.sub_agent_idle_timeout_seconds == 60
        assert cfg.v18.wave_t_enabled is True
        assert cfg.v18.wave_t_max_fix_iterations == 4


# ======================================================================
# INTEGRATION TESTS — WaveResult backward compatibility
# ======================================================================

class TestWaveResultBackwardCompat:
    def test_wave_only_construction(self):
        """WaveResult can be created with just wave arg (existing code)."""
        wr = WaveResult(wave="A")
        assert wr.wave == "A"
        assert wr.cost == 0.0
        assert wr.success is True
        assert wr.provider == ""

    def test_has_provider_fields(self):
        """WaveResult has all provider routing fields."""
        wr = WaveResult(
            wave="B",
            provider="codex",
            provider_model="gpt-5.1-codex-max",
            fallback_used=False,
            fallback_reason="",
            retry_count=0,
            input_tokens=1000,
            output_tokens=500,
            reasoning_tokens=200,
        )
        assert wr.provider == "codex"
        assert wr.provider_model == "gpt-5.1-codex-max"
        assert wr.fallback_used is False
        assert wr.input_tokens == 1000
        assert wr.output_tokens == 500
        assert wr.reasoning_tokens == 200

    def test_all_defaults_are_zero_or_empty(self):
        wr = WaveResult(wave="X")
        assert wr.provider == ""
        assert wr.provider_model == ""
        assert wr.fallback_used is False
        assert wr.fallback_reason == ""
        assert wr.retry_count == 0
        assert wr.input_tokens == 0
        assert wr.output_tokens == 0
        assert wr.reasoning_tokens == 0


# ======================================================================
# INTEGRATION TESTS — _execute_wave_sdk
# ======================================================================

class TestExecuteWaveSdk:
    @pytest.mark.asyncio
    async def test_no_routing_claude_path(self):
        """provider_routing=None runs existing Claude-only path."""
        async def _sdk_call(prompt, wave, milestone, config, cwd, role):
            return 0.05

        milestone = types.SimpleNamespace(id="M1", title="Test")

        wr = await _execute_wave_sdk(
            execute_sdk_call=_sdk_call,
            wave_letter="A",
            prompt="do stuff",
            config={},
            cwd="/fake",
            milestone=milestone,
            provider_routing=None,
        )
        assert wr.wave == "A"
        assert wr.provider == "claude"
        assert wr.cost == pytest.approx(0.05)
        assert wr.success is True

    @pytest.mark.asyncio
    async def test_with_routing_routes_through_provider(self, tmp_path):
        """provider_routing dict routes through provider router."""
        async def _sdk_call(prompt, **kw):
            return 0.03

        milestone = types.SimpleNamespace(id="M1", title="Test")

        routing = {
            "provider_map": WaveProviderMap(A="claude"),
            "codex_transport": None,
            "codex_config": None,
            "codex_home": None,
            "checkpoint_create": lambda label, cwd: _FakeCheckpoint(),
            "checkpoint_diff": _fake_diff,
        }

        wr = await _execute_wave_sdk(
            execute_sdk_call=_sdk_call,
            wave_letter="A",
            prompt="plan",
            config={},
            cwd=str(tmp_path),
            milestone=milestone,
            provider_routing=routing,
        )
        assert wr.provider == "claude"
        assert wr.success is True

    @pytest.mark.asyncio
    async def test_with_routing_captures_provider_progress_fields(self, tmp_path):
        """Provider-routed waves keep the last streamed message/tool metadata."""

        async def _sdk_call(prompt, **kw):
            return 0.03

        async def _codex_exec(prompt, cwd, config, codex_home, *, progress_callback=None):
            if progress_callback is not None:
                progress_callback(message_type="item.completed", tool_name="write")
            (tmp_path / "wave-b.ts").write_text("export const waveB = true;\n", encoding="utf-8")
            return CodexResult(
                success=True,
                model="gpt-5.4",
                cost_usd=0.12,
            )

        milestone = types.SimpleNamespace(id="M1", title="Test")
        transport = types.SimpleNamespace(
            is_codex_available=lambda: True,
            execute_codex=AsyncMock(side_effect=_codex_exec),
        )
        routing = {
            "provider_map": WaveProviderMap(B="codex"),
            "codex_transport": transport,
            "codex_config": CodexConfig(),
            "codex_home": None,
            "checkpoint_create": lambda label, cwd: _create_checkpoint(label, cwd),
            "checkpoint_diff": _diff_checkpoints,
        }

        wr = await _execute_wave_sdk(
            execute_sdk_call=_sdk_call,
            wave_letter="B",
            prompt="wire",
            config={},
            cwd=str(tmp_path),
            milestone=milestone,
            provider_routing=routing,
        )
        assert wr.provider == "codex"
        assert wr.success is True
        assert wr.last_sdk_message_type == "item.completed"
        assert wr.last_sdk_tool_name == "write"

    @pytest.mark.asyncio
    async def test_with_routing_provider_timeout_writes_hang_report(self, tmp_path):
        """Provider-routed waves inherit the wave watchdog and hang report path."""

        async def _sdk_call(prompt, **kw):
            return 0.03

        async def _codex_exec(prompt, cwd, config, codex_home, *, progress_callback=None):
            await asyncio.sleep(3600)
            return CodexResult(success=True, model="gpt-5.4")

        milestone = types.SimpleNamespace(id="M1", title="Test")
        transport = types.SimpleNamespace(
            is_codex_available=lambda: True,
            execute_codex=AsyncMock(side_effect=_codex_exec),
        )
        config = types.SimpleNamespace(
            v18=types.SimpleNamespace(
                wave_idle_timeout_seconds=1,
                wave_watchdog_poll_seconds=1,
                wave_watchdog_max_retries=0,
            )
        )
        routing = {
            "provider_map": WaveProviderMap(B="codex"),
            "codex_transport": transport,
            "codex_config": CodexConfig(timeout_seconds=60, max_retries=0),
            "codex_home": None,
            "checkpoint_create": lambda label, cwd: _create_checkpoint(label, cwd),
            "checkpoint_diff": _diff_checkpoints,
        }

        wr = await _execute_wave_sdk(
            execute_sdk_call=_sdk_call,
            wave_letter="B",
            prompt="wire",
            config=config,
            cwd=str(tmp_path),
            milestone=milestone,
            provider_routing=routing,
        )
        assert wr.success is False
        assert wr.wave_timed_out is True
        assert "idle timeout" in wr.error_message.lower()
        assert Path(wr.hang_report_path).is_file()

    @pytest.mark.asyncio
    async def test_routing_missing_transport_falls_back(self):
        """Missing codex_transport_module triggers graceful Claude fallback."""
        milestone = types.SimpleNamespace(id="M1", title="Test")

        routing = {
            "provider_map": WaveProviderMap(),
            "codex_transport": None,
            "codex_config": None,
            "codex_home": None,
            "checkpoint_create": lambda label, cwd: _FakeCheckpoint(),
            "checkpoint_diff": _fake_diff,
        }

        wr = await _execute_wave_sdk(
            execute_sdk_call=lambda **kw: 0,
            wave_letter="B",
            prompt="wire",
            config={},
            cwd="/fake",
            milestone=milestone,
            provider_routing=routing,
        )
        # Falls back to Claude successfully rather than erroring
        assert wr.provider == "claude"
        assert wr.fallback_used is True
        assert "not provided" in wr.fallback_reason.lower()

    @pytest.mark.asyncio
    async def test_routing_exception_sets_error(self):
        """If provider routing raises an unexpected exception, WaveResult captures the error."""
        milestone = types.SimpleNamespace(id="M1", title="Test")

        # Passing a non-dict/non-WaveProviderMap to provider_map causes AttributeError
        routing = {
            "provider_map": None,  # Will cause AttributeError in provider_for()
        }

        wr = await _execute_wave_sdk(
            execute_sdk_call=lambda **kw: 0,
            wave_letter="B",
            prompt="wire",
            config={},
            cwd="/fake",
            milestone=milestone,
            provider_routing=routing,
        )
        assert wr.success is False
        assert wr.error_message != ""


# ======================================================================
# INTEGRATION TESTS — save_wave_telemetry
# ======================================================================

class TestSaveWaveTelemetry:
    def test_includes_provider_fields(self, tmp_path):
        wr = WaveResult(
            wave="B",
            cost=0.15,
            provider="codex",
            provider_model="gpt-5.1-codex-max",
            fallback_used=False,
            fallback_reason="",
            retry_count=1,
            input_tokens=2000,
            output_tokens=800,
            reasoning_tokens=300,
        )
        save_wave_telemetry(wr, str(tmp_path), "M1")

        telemetry_path = tmp_path / ".agent-team" / "telemetry" / "M1-wave-B.json"
        assert telemetry_path.is_file()

        data = json.loads(telemetry_path.read_text(encoding="utf-8"))
        assert data["provider"] == "codex"
        assert data["provider_model"] == "gpt-5.1-codex-max"
        assert data["fallback_used"] is False
        assert data["fallback_reason"] == ""
        assert data["retry_count"] == 1
        assert data["input_tokens"] == 2000
        assert data["output_tokens"] == 800
        assert data["reasoning_tokens"] == 300
        assert data["sdk_cost_usd"] == pytest.approx(0.15)

    def test_empty_provider_fields_still_present(self, tmp_path):
        """Even with no provider routing, fields are present with defaults."""
        wr = WaveResult(wave="A")
        save_wave_telemetry(wr, str(tmp_path), "M2")

        telemetry_path = tmp_path / ".agent-team" / "telemetry" / "M2-wave-A.json"
        data = json.loads(telemetry_path.read_text(encoding="utf-8"))
        assert "provider" in data
        assert "provider_model" in data
        assert "fallback_used" in data
        assert "input_tokens" in data
        assert data["provider"] == ""
        assert data["input_tokens"] == 0

    def test_includes_compile_skip_and_rollback_flags(self, tmp_path):
        wr = WaveResult(
            wave="D5",
            provider="claude",
            compile_passed=False,
            compile_skipped=False,
            rolled_back=True,
        )
        save_wave_telemetry(wr, str(tmp_path), "M3")

        data = json.loads(
            (tmp_path / ".agent-team" / "telemetry" / "M3-wave-D5.json").read_text(encoding="utf-8")
        )
        assert data["provider"] == "claude"
        assert data["compile_skipped"] is False
        assert data["rolled_back"] is True


# ======================================================================
# E2E SMOKE TEST — Multi-provider round trip
# ======================================================================

class TestMultiProviderE2E:
    @pytest.mark.asyncio
    async def test_full_routing_round_trip(self, tmp_path):
        """Full provider routing: A=Claude, B=Codex(mock), C=python, D=Codex, D5=Claude.

        Validates:
        1. Config: provider_routing=True
        2. Wave A routes to Claude callback
        3. Wave B routes to Codex (mock) — success path
        4. Wave C is python noop
        5. Wave D routes to Codex by default
        6. Wave D5 routes to Claude regardless of provider map defaults
        7. Each wave has correct provider metadata
        """
        call_log: list[dict] = []

        async def _claude_cb(prompt, **kw):
            call_log.append({"type": "claude", "prompt": prompt[:50]})
            return 0.05

        codex_result = CodexResult(
            success=True,
            model="gpt-5.1-codex-max",
            cost_usd=0.12,
            input_tokens=800,
            output_tokens=300,
            reasoning_tokens=100,
        )

        transport = types.SimpleNamespace(
            is_codex_available=lambda: True,
            execute_codex=AsyncMock(return_value=codex_result),
        )

        provider_map = WaveProviderMap()
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.ts").write_text("code")

        results = {}
        for wave_letter in ["A", "B", "C", "D", "D5"]:
            result = await execute_wave_with_provider(
                wave_letter=wave_letter,
                prompt=f"Execute wave {wave_letter}",
                cwd=str(tmp_path),
                config={},
                provider_map=provider_map,
                claude_callback=_claude_cb,
                claude_callback_kwargs={},
                codex_transport_module=transport,
                codex_config=CodexConfig(),
                checkpoint_create=lambda label, cwd: _FakeCheckpoint(
                    file_manifest={"src/app.ts": "hash"}
                ),
                checkpoint_diff=lambda pre, post: _FakeDiff(
                    created=["src/new.ts"], modified=["src/app.ts"]
                ),
            )
            results[wave_letter] = result

        # Wave A: Claude
        assert results["A"]["provider"] == "claude"
        assert results["A"]["fallback_used"] is False

        # Wave B: Codex
        assert results["B"]["provider"] == "codex"
        assert results["B"]["cost"] == pytest.approx(0.12)
        assert results["B"]["input_tokens"] == 800
        assert results["B"]["fallback_used"] is False

        # Wave C: Python noop
        assert results["C"]["provider"] == "python"
        assert results["C"]["cost"] == 0.0

        # Wave D: Codex
        assert results["D"]["provider"] == "codex"
        assert results["D"]["fallback_used"] is False

        # Wave D5: Claude
        assert results["D5"]["provider"] == "claude"
        assert results["D5"]["fallback_used"] is False

        # Claude callback was called for A and D5, not B/D (codex) or C (python)
        claude_calls = [c for c in call_log if c["type"] == "claude"]
        assert len(claude_calls) == 2

    @pytest.mark.asyncio
    async def test_codex_failure_fallback_e2e(self, tmp_path):
        """Codex fails, checkpoint restored, Claude fallback succeeds."""
        codex_result = CodexResult(success=False, exit_code=1, error="model overloaded")

        transport = types.SimpleNamespace(
            is_codex_available=lambda: True,
            execute_codex=AsyncMock(return_value=codex_result),
        )

        async def _claude_cb(prompt, **kw):
            return 0.06

        rollback_invoked = []
        original_rollback = rollback_from_snapshot

        result = await execute_wave_with_provider(
            wave_letter="B",
            prompt="wire backend",
            cwd=str(tmp_path),
            config={},
            provider_map=WaveProviderMap(),
            claude_callback=_claude_cb,
            claude_callback_kwargs={},
            codex_transport_module=transport,
            codex_config=CodexConfig(),
            checkpoint_create=lambda label, cwd: _FakeCheckpoint(),
            checkpoint_diff=_fake_diff,
        )

        assert result["provider"] == "claude"
        assert result["fallback_used"] is True
        assert "codex failed" in result["fallback_reason"].lower()
        assert result["cost"] == pytest.approx(0.06)

    @pytest.mark.asyncio
    async def test_routing_disabled_zero_codex_calls(self):
        """When provider_routing=None, no codex calls are made."""
        transport = types.SimpleNamespace(
            is_codex_available=lambda: True,
            execute_codex=AsyncMock(),
        )

        async def _sdk_call(prompt, wave, milestone, config, cwd, role):
            return 0.05

        milestone = types.SimpleNamespace(id="M1", title="Test")

        wr = await _execute_wave_sdk(
            execute_sdk_call=_sdk_call,
            wave_letter="B",
            prompt="wire backend",
            config={},
            cwd="/fake",
            milestone=milestone,
            provider_routing=None,  # routing disabled
        )

        assert wr.provider == "claude"
        transport.execute_codex.assert_not_called()

    @pytest.mark.asyncio
    async def test_telemetry_per_wave_provider(self, tmp_path):
        """Telemetry JSON captures correct provider for each wave."""
        waves = {
            "A": WaveResult(wave="A", provider="claude", cost=0.05),
            "B": WaveResult(
                wave="B", provider="codex", provider_model="gpt-5.1-codex-max",
                cost=0.12, input_tokens=800, output_tokens=300,
            ),
            "C": WaveResult(wave="C", provider="python", cost=0.0),
        }

        for w, wr in waves.items():
            save_wave_telemetry(wr, str(tmp_path), "M-E2E")

        for w in ["A", "B", "C"]:
            path = tmp_path / ".agent-team" / "telemetry" / f"M-E2E-wave-{w}.json"
            assert path.is_file()
            data = json.loads(path.read_text(encoding="utf-8"))
            assert data["provider"] == waves[w].provider

        # Check B has model info
        b_data = json.loads(
            (tmp_path / ".agent-team" / "telemetry" / "M-E2E-wave-B.json")
            .read_text(encoding="utf-8")
        )
        assert b_data["provider_model"] == "gpt-5.1-codex-max"
        assert b_data["input_tokens"] == 800

    @pytest.mark.asyncio
    async def test_execute_milestone_waves_rolls_back_codex_failure_before_claude_fallback(self, tmp_path):
        """Real milestone execution keeps only the Claude fallback edits after a Codex failure."""
        root = tmp_path
        milestone = types.SimpleNamespace(
            id="M1",
            title="Orders",
            template="backend_only",
            description="Orders milestone",
            dependencies=[],
            feature_refs=["F-ORDERS"],
            stack_target="NestJS",
        )

        src_dir = root / "src"
        src_dir.mkdir()
        service_path = src_dir / "service.ts"
        service_path.write_text("export const provider = 'before';\n", encoding="utf-8")

        async def _codex_exec(prompt, cwd, config, codex_home, *, progress_callback=None):
            service_path.write_text("export const provider = 'codex-bad';\n", encoding="utf-8")
            return CodexResult(
                success=False,
                model="gpt-5.1-codex-max",
                cost_usd=0.11,
                input_tokens=400,
                output_tokens=120,
                reasoning_tokens=30,
                retry_count=1,
                error="boom",
            )

        transport = types.SimpleNamespace(
            is_codex_available=lambda: True,
            execute_codex=AsyncMock(side_effect=_codex_exec),
        )

        async def build_prompt(**kwargs: object) -> str:
            return f"wave {kwargs['wave']}"

        async def execute_sdk_call(*, wave: str, role: str = "wave", **_: object) -> float:
            if role == "wave" and wave == "B":
                service_path.write_text("export const provider = 'claude-good';\n", encoding="utf-8")
            elif role == "wave":
                (src_dir / f"{wave.lower()}.ts").write_text(
                    f"export const {wave.lower()} = true;\n",
                    encoding="utf-8",
                )
            return 0.02

        async def run_compile_check(**_: object) -> dict[str, object]:
            return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

        async def generate_contracts(**_: object) -> dict[str, object]:
            return {
                "success": True,
                "milestone_spec_path": "",
                "cumulative_spec_path": "",
                "client_exports": [],
                "breaking_changes": [],
                "endpoints_summary": [],
                "files_created": [],
            }

        result = await execute_milestone_waves(
            milestone=milestone,
            ir={},
            config=types.SimpleNamespace(),
            cwd=str(root),
            build_wave_prompt=build_prompt,
            execute_sdk_call=execute_sdk_call,
            run_compile_check=run_compile_check,
            extract_artifacts=lambda **kwargs: {"wave": kwargs["wave"]},
            generate_contracts=generate_contracts,
            run_scaffolding=None,
            save_wave_state=None,
            provider_routing={
                "provider_map": WaveProviderMap(),
                "codex_transport": transport,
                "codex_config": CodexConfig(),
                "codex_home": None,
            },
        )

        assert result.success is True
        wave_b = next(w for w in result.waves if w.wave == "B")
        assert wave_b.provider == "claude"
        assert wave_b.fallback_used is True
        assert wave_b.cost == pytest.approx(0.13)
        assert service_path.read_text(encoding="utf-8") == "export const provider = 'claude-good';\n"

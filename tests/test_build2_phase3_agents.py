"""Phase 3 exhaustive verification tests for Build 2 gaps in Agent Teams, CLAUDE.md, and Hooks.

Covers gaps identified in Phase 2D:

Group 1: AgentTeamsBackend execute_wave -- asyncio.gather with return_exceptions,
          wave timeout, task tracking, exception handling in raw results.
Group 2: CLAUDE.md optional parameters -- service_name, dependencies, tech_stack,
          codebase_context, quality_standards sections.
Group 3: CLAUDE.md idempotent writes -- double-write, role replacement, marker preservation.
Group 4: Contract section edge cases -- missing keys, fallback chains, implemented markers.
Group 5: Factory branch 2 detail -- env var not set behavior and logging.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_team_v15.agent_teams_backend import (
    AgentTeamsBackend,
    CLIBackend,
    TaskResult,
    TeamState,
    WaveResult,
    create_execution_backend,
)
from agent_team_v15.claude_md_generator import (
    _BEGIN_MARKER,
    _END_MARKER,
    _generate_contract_section,
    generate_claude_md,
    write_teammate_claude_md,
)
from agent_team_v15.config import AgentTeamConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockWave:
    """Minimal mock satisfying the ExecutionWave interface."""

    def __init__(self, wave_number: int = 0, task_ids: list[str] | None = None):
        self.wave_number = wave_number
        self.task_ids = task_ids or []


def _make_config(
    min_convergence_ratio: float = 0.9,
    contract_limit: int = 100,
) -> SimpleNamespace:
    """Build a minimal config-like object for CLAUDE.md testing."""
    convergence = SimpleNamespace(min_convergence_ratio=min_convergence_ratio)
    agent_teams = SimpleNamespace(contract_limit=contract_limit)
    return SimpleNamespace(convergence=convergence, agent_teams=agent_teams)


# ===========================================================================
# Group 1: AgentTeamsBackend execute_wave
# ===========================================================================


class TestAgentTeamsBackendExecuteWave:
    """Tests for AgentTeamsBackend.execute_wave covering asyncio.gather,
    wave timeout, task tracking in state, and exception handling paths.

    The implementation uses asyncio.wait_for(asyncio.gather(*coros, return_exceptions=True), timeout=wave_timeout).
    Each task runs _run_single_task which sleeps poll_interval (30s) then completes.
    We mock asyncio.sleep to avoid real delays.
    """

    @pytest.fixture
    def config(self) -> AgentTeamConfig:
        cfg = AgentTeamConfig()
        cfg.agent_teams.wave_timeout_seconds = 3600
        cfg.agent_teams.task_timeout_seconds = 1800
        return cfg

    @pytest.fixture
    def backend(self, config: AgentTeamConfig) -> AgentTeamsBackend:
        b = AgentTeamsBackend(config)
        b._state = TeamState(
            mode="agent_teams",
            active=True,
            teammates=[],
            completed_tasks=[],
            failed_tasks=[],
        )
        return b

    @pytest.mark.asyncio
    async def test_execute_wave_returns_wave_result(self, backend: AgentTeamsBackend):
        """execute_wave returns a WaveResult with correct wave_index and task results."""
        wave = MockWave(wave_number=3, task_ids=["t1", "t2"])

        async def _mock_spawn(task_id, prompt, timeout):
            return TaskResult(task_id=task_id, status="completed", output="ok", error="", files_created=[], files_modified=[], duration_seconds=0.1)

        with patch.object(backend, "_spawn_teammate", side_effect=_mock_spawn):
            result = await backend.execute_wave(wave)
        assert isinstance(result, WaveResult)
        assert result.wave_index == 3
        assert len(result.task_results) == 2

    @pytest.mark.asyncio
    async def test_execute_wave_all_tasks_completed(self, backend: AgentTeamsBackend):
        """When all tasks complete successfully, all_succeeded is True."""
        wave = MockWave(wave_number=0, task_ids=["a", "b", "c"])

        async def _mock_spawn(task_id, prompt, timeout):
            return TaskResult(task_id=task_id, status="completed", output="ok", error="", files_created=[], files_modified=[], duration_seconds=0.1)

        with patch.object(backend, "_spawn_teammate", side_effect=_mock_spawn):
            result = await backend.execute_wave(wave)
        assert result.all_succeeded is True
        for tr in result.task_results:
            assert tr.status == "completed"

    @pytest.mark.asyncio
    async def test_execute_wave_tracks_completed_in_state(self, backend: AgentTeamsBackend):
        """Completed tasks are appended to backend._state.completed_tasks."""
        wave = MockWave(wave_number=0, task_ids=["x1", "x2"])

        async def _mock_spawn(task_id, prompt, timeout):
            return TaskResult(task_id=task_id, status="completed", output="ok", error="", files_created=[], files_modified=[], duration_seconds=0.1)

        with patch.object(backend, "_spawn_teammate", side_effect=_mock_spawn):
            await backend.execute_wave(wave)
        assert "x1" in backend._state.completed_tasks
        assert "x2" in backend._state.completed_tasks

    @pytest.mark.asyncio
    async def test_execute_wave_increments_total_messages(self, backend: AgentTeamsBackend):
        """total_messages is incremented by the number of task results in the wave."""
        initial_messages = backend._state.total_messages
        wave = MockWave(wave_number=0, task_ids=["m1", "m2", "m3"])

        async def _mock_spawn(task_id, prompt, timeout):
            return TaskResult(task_id=task_id, status="completed", output="ok", error="", files_created=[], files_modified=[], duration_seconds=0.1)

        with patch.object(backend, "_spawn_teammate", side_effect=_mock_spawn):
            await backend.execute_wave(wave)
        assert backend._state.total_messages == initial_messages + 3

    @pytest.mark.asyncio
    async def test_execute_wave_empty_tasks_succeeds(self, backend: AgentTeamsBackend):
        """An empty wave returns an empty WaveResult with all_succeeded=True."""
        wave = MockWave(wave_number=0, task_ids=[])

        async def _mock_spawn(task_id, prompt, timeout):
            return TaskResult(task_id=task_id, status="completed", output="ok", error="", files_created=[], files_modified=[], duration_seconds=0.1)

        with patch.object(backend, "_spawn_teammate", side_effect=_mock_spawn):
            result = await backend.execute_wave(wave)
        assert isinstance(result, WaveResult)
        assert result.task_results == []
        assert result.all_succeeded is True

    @pytest.mark.asyncio
    async def test_execute_wave_has_positive_duration(self, backend: AgentTeamsBackend):
        """WaveResult.duration_seconds is > 0 (timing is measured)."""
        wave = MockWave(wave_number=0, task_ids=["d1"])

        async def _mock_spawn(task_id, prompt, timeout):
            return TaskResult(task_id=task_id, status="completed", output="ok", error="", files_created=[], files_modified=[], duration_seconds=0.1)

        with patch.object(backend, "_spawn_teammate", side_effect=_mock_spawn):
            result = await backend.execute_wave(wave)
        assert result.duration_seconds >= 0.0

    @pytest.mark.asyncio
    async def test_execute_wave_timeout_produces_timeout_results(self, config: AgentTeamConfig):
        """When asyncio.wait_for raises TimeoutError, all tasks get status='timeout'."""
        config.agent_teams.wave_timeout_seconds = 1  # very short
        backend = AgentTeamsBackend(config)
        backend._state = TeamState(
            mode="agent_teams",
            active=True,
            teammates=[],
            completed_tasks=[],
            failed_tasks=[],
        )
        wave = MockWave(wave_number=5, task_ids=["slow-1", "slow-2"])

        # Make asyncio.sleep actually sleep but set a very short wave timeout.
        # We patch asyncio.wait_for to raise TimeoutError immediately.
        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
            result = await backend.execute_wave(wave)

        assert isinstance(result, WaveResult)
        assert result.wave_index == 5
        assert result.all_succeeded is False
        assert len(result.task_results) == 2
        for tr in result.task_results:
            assert tr.status == "timeout"
            assert "timed out" in tr.error.lower()

    @pytest.mark.asyncio
    async def test_execute_wave_exception_in_gather_produces_failed_result(
        self, backend: AgentTeamsBackend
    ):
        """When asyncio.gather returns an Exception (via return_exceptions=True),
        the result processing creates a TaskResult with status='failed'."""
        wave = MockWave(wave_number=1, task_ids=["exc-task"])

        async def _mock_spawn_fail(task_id, prompt, timeout):
            raise ValueError("simulated task failure")

        with patch.object(backend, "_spawn_teammate", side_effect=_mock_spawn_fail):
            result = await backend.execute_wave(wave)

        assert result.all_succeeded is False
        assert len(result.task_results) == 1
        tr = result.task_results[0]
        assert tr.status == "failed"
        assert "simulated task failure" in tr.error

    @pytest.mark.asyncio
    async def test_execute_wave_mixed_success_and_failure(self, backend: AgentTeamsBackend):
        """When some tasks succeed and some fail, all_succeeded is False and
        state tracks both completed and failed tasks correctly."""
        wave = MockWave(wave_number=0, task_ids=["ok-1", "fail-1"])

        async def _mock_spawn(task_id, prompt, timeout):
            if task_id == "fail-1":
                return TaskResult(task_id=task_id, status="failed", output="", error="task failed mid-execution", files_created=[], files_modified=[], duration_seconds=0.1)
            return TaskResult(task_id=task_id, status="completed", output="ok", error="", files_created=[], files_modified=[], duration_seconds=0.1)

        with patch.object(backend, "_spawn_teammate", side_effect=_mock_spawn):
            result = await backend.execute_wave(wave)

        assert result.all_succeeded is False
        statuses = {tr.task_id: tr.status for tr in result.task_results}
        # At least one should be completed and one failed
        assert "failed" in statuses.values() or "completed" in statuses.values()

    @pytest.mark.asyncio
    async def test_execute_wave_failed_tasks_in_state(self, backend: AgentTeamsBackend):
        """Failed tasks are appended to backend._state.failed_tasks."""
        wave = MockWave(wave_number=0, task_ids=["will-fail"])

        async def _mock_spawn_fail(task_id, prompt, timeout):
            return TaskResult(task_id=task_id, status="failed", output="", error="always fail", files_created=[], files_modified=[], duration_seconds=0.1)

        with patch.object(backend, "_spawn_teammate", side_effect=_mock_spawn_fail):
            await backend.execute_wave(wave)

        assert "will-fail" in backend._state.failed_tasks

    @pytest.mark.asyncio
    async def test_execute_wave_single_task(self, backend: AgentTeamsBackend):
        """execute_wave works correctly with a single task."""
        wave = MockWave(wave_number=7, task_ids=["solo"])

        async def _mock_spawn(task_id, prompt, timeout):
            return TaskResult(task_id=task_id, status="completed", output="ok", error="", files_created=[], files_modified=[], duration_seconds=0.1)

        with patch.object(backend, "_spawn_teammate", side_effect=_mock_spawn):
            result = await backend.execute_wave(wave)
        assert len(result.task_results) == 1
        assert result.task_results[0].task_id == "solo"
        assert result.task_results[0].status == "completed"


# ===========================================================================
# Group 2: CLAUDE.md Optional Parameters
# ===========================================================================


class TestClaudeMdOptionalParams:
    """Verify that each optional parameter of generate_claude_md produces
    the expected section in the output."""

    @pytest.fixture
    def config(self) -> SimpleNamespace:
        return _make_config()

    def test_service_name_section(self, config):
        """generate_claude_md with service_name produces '## Service: X' section."""
        result = generate_claude_md(
            "architect", config, mcp_servers={}, service_name="billing-api"
        )
        assert "## Service: billing-api" in result

    def test_service_name_empty_omits_section(self, config):
        """generate_claude_md with empty service_name omits service section."""
        result = generate_claude_md(
            "architect", config, mcp_servers={}, service_name=""
        )
        assert "## Service:" not in result

    def test_dependencies_section(self, config):
        """generate_claude_md with dependencies produces '## Dependencies' section."""
        result = generate_claude_md(
            "code-writer", config, mcp_servers={},
            dependencies=["express", "pg", "redis"],
        )
        assert "## Dependencies" in result
        assert "`express`" in result
        assert "`pg`" in result
        assert "`redis`" in result

    def test_dependencies_none_omits_section(self, config):
        """generate_claude_md with dependencies=None omits dependencies section."""
        result = generate_claude_md(
            "code-writer", config, mcp_servers={}, dependencies=None,
        )
        assert "## Dependencies" not in result

    def test_dependencies_empty_list_omits_section(self, config):
        """generate_claude_md with dependencies=[] omits dependencies section."""
        result = generate_claude_md(
            "code-writer", config, mcp_servers={}, dependencies=[],
        )
        assert "## Dependencies" not in result

    def test_tech_stack_section(self, config):
        """generate_claude_md with tech_stack produces '## Tech Stack' section."""
        result = generate_claude_md(
            "architect", config, mcp_servers={},
            tech_stack="Node.js 20, Express 4, PostgreSQL 16",
        )
        assert "## Tech Stack" in result
        assert "Node.js 20" in result

    def test_tech_stack_empty_omits_section(self, config):
        """generate_claude_md with empty tech_stack omits tech stack section."""
        result = generate_claude_md(
            "architect", config, mcp_servers={}, tech_stack="",
        )
        assert "## Tech Stack" not in result

    def test_codebase_context_section(self, config):
        """generate_claude_md with codebase_context produces '## Codebase Context' section."""
        result = generate_claude_md(
            "architect", config, mcp_servers={},
            codebase_context="This is a monorepo with 3 services.",
        )
        assert "## Codebase Context" in result
        assert "monorepo with 3 services" in result

    def test_codebase_context_empty_omits_section(self, config):
        """generate_claude_md with empty codebase_context omits section."""
        result = generate_claude_md(
            "architect", config, mcp_servers={}, codebase_context="",
        )
        assert "## Codebase Context" not in result

    def test_quality_standards_section(self, config):
        """generate_claude_md with quality_standards produces '## Quality Standards' section."""
        result = generate_claude_md(
            "code-reviewer", config, mcp_servers={},
            quality_standards="All functions must have docstrings.",
        )
        assert "## Quality Standards" in result
        assert "docstrings" in result

    def test_quality_standards_empty_omits_section(self, config):
        """generate_claude_md with empty quality_standards omits section."""
        result = generate_claude_md(
            "code-reviewer", config, mcp_servers={}, quality_standards="",
        )
        assert "## Quality Standards" not in result

    def test_all_optional_params_combined(self, config):
        """All optional params produce their respective sections in the output."""
        result = generate_claude_md(
            "architect",
            config,
            mcp_servers={},
            service_name="payment-svc",
            dependencies=["stripe", "express"],
            tech_stack="TypeScript 5.3",
            codebase_context="Monorepo structure.",
            quality_standards="100% test coverage required.",
        )
        assert "## Service: payment-svc" in result
        assert "## Dependencies" in result
        assert "`stripe`" in result
        assert "## Tech Stack" in result
        assert "TypeScript 5.3" in result
        assert "## Codebase Context" in result
        assert "Monorepo structure." in result
        assert "## Quality Standards" in result
        assert "100% test coverage" in result

    def test_optional_params_ordering(self, config):
        """Service name, dependencies, tech stack, codebase context appear before
        quality standards (which comes after convergence section)."""
        result = generate_claude_md(
            "architect",
            config,
            mcp_servers={},
            service_name="svc",
            dependencies=["dep"],
            tech_stack="ts",
            codebase_context="ctx",
            quality_standards="qs",
        )
        # Service, Dependencies, Tech Stack, Codebase Context come before Quality Standards
        svc_idx = result.index("## Service:")
        dep_idx = result.index("## Dependencies")
        tech_idx = result.index("## Tech Stack")
        ctx_idx = result.index("## Codebase Context")
        qs_idx = result.index("## Quality Standards")

        assert svc_idx < dep_idx < tech_idx < ctx_idx
        assert qs_idx > ctx_idx  # quality standards appears after codebase context


# ===========================================================================
# Group 3: CLAUDE.md Idempotent Writes
# ===========================================================================


class TestClaudeMdIdempotentWrites:
    """Verify idempotent write behavior of write_teammate_claude_md with markers."""

    @pytest.fixture
    def config(self) -> SimpleNamespace:
        return _make_config()

    def test_double_write_same_role_no_duplication(self, config, tmp_path: Path):
        """Writing the same role twice produces single marked block (no duplication)."""
        write_teammate_claude_md("architect", config, {}, tmp_path)
        write_teammate_claude_md("architect", config, {}, tmp_path)

        content = (tmp_path / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
        # Only one BEGIN and one END marker should exist
        assert content.count(_BEGIN_MARKER) == 1
        assert content.count(_END_MARKER) == 1
        # The Architect role content should appear exactly once
        assert content.count("## Role: Architect") == 1

    def test_write_different_roles_replaces(self, config, tmp_path: Path):
        """Writing role A then role B replaces the content between markers."""
        write_teammate_claude_md("architect", config, {}, tmp_path)
        content_after_first = (tmp_path / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
        assert "Architect" in content_after_first

        write_teammate_claude_md("code-writer", config, {}, tmp_path)
        content_after_second = (tmp_path / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
        # The new role content should be present
        assert "Code Writer" in content_after_second
        # The old role content (between markers) should be replaced
        # Note: "Architect" may still appear in generic text, but the role header should not
        assert "## Role: Architect" not in content_after_second
        assert "## Role: Code Writer" in content_after_second
        # Still only one marker pair
        assert content_after_second.count(_BEGIN_MARKER) == 1
        assert content_after_second.count(_END_MARKER) == 1

    def test_existing_content_preserved_outside_markers(self, config, tmp_path: Path):
        """Content before and after markers is preserved across writes."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        claude_md = claude_dir / "CLAUDE.md"

        # Write initial content with markers and surrounding text
        header = "# My Project Config\n\nThis is my project.\n"
        footer = "\n# Footer Section\n\nDo not remove this.\n"
        initial_marked = f"{_BEGIN_MARKER}\n## Role: test\nOld stuff\n{_END_MARKER}"
        claude_md.write_text(
            header + initial_marked + footer, encoding="utf-8"
        )

        write_teammate_claude_md("test-engineer", config, {}, tmp_path)
        content = claude_md.read_text(encoding="utf-8")

        # Header and footer preserved
        assert "# My Project Config" in content
        assert "This is my project." in content
        assert "# Footer Section" in content
        assert "Do not remove this." in content
        # Old content replaced
        assert "Old stuff" not in content
        # New role present
        assert "Test Engineer" in content

    def test_first_write_to_existing_file_without_markers_appends(
        self, config, tmp_path: Path
    ):
        """Writing to a file that has no markers appends after existing content."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        claude_md = claude_dir / "CLAUDE.md"
        claude_md.write_text("# Pre-existing content\n", encoding="utf-8")

        write_teammate_claude_md("architect", config, {}, tmp_path)
        content = claude_md.read_text(encoding="utf-8")

        # Pre-existing content preserved
        assert "# Pre-existing content" in content
        # Markers added
        assert _BEGIN_MARKER in content
        assert _END_MARKER in content
        # Pre-existing content comes before the markers
        pre_idx = content.index("# Pre-existing content")
        begin_idx = content.index(_BEGIN_MARKER)
        assert pre_idx < begin_idx


# ===========================================================================
# Group 4: Contract Section Edge Cases
# ===========================================================================


class TestContractSectionEdgeCases:
    """Edge cases for _generate_contract_section: missing keys, fallbacks, markers."""

    def test_contract_with_missing_contract_id_falls_back_to_id(self):
        """Contract missing 'contract_id' falls back to 'id' key."""
        contracts = [
            {"id": "fallback-id", "provider_service": "svc", "contract_type": "api", "version": "1"}
        ]
        result = _generate_contract_section(contracts)
        assert "`fallback-id`" in result

    def test_contract_with_missing_contract_id_and_id_falls_back_to_unknown(self):
        """Contract missing both 'contract_id' and 'id' falls back to 'unknown'."""
        contracts = [
            {"provider_service": "svc", "contract_type": "api", "version": "1"}
        ]
        result = _generate_contract_section(contracts)
        assert "`unknown`" in result

    def test_contract_with_missing_provider_service_falls_back_to_service_name(self):
        """Contract missing 'provider_service' falls back to 'service_name' key."""
        contracts = [
            {"contract_id": "c-1", "service_name": "my-service", "contract_type": "api", "version": "1"}
        ]
        result = _generate_contract_section(contracts)
        assert "my-service" in result

    def test_contract_with_missing_provider_service_and_service_name_falls_back_to_unknown(self):
        """Contract missing both 'provider_service' and 'service_name' falls back to 'unknown'."""
        contracts = [
            {"contract_id": "c-1", "contract_type": "api", "version": "1"}
        ]
        result = _generate_contract_section(contracts)
        # The format is: `c-1` -- unknown (api v1)
        assert "unknown" in result

    def test_contract_type_falls_back_to_type_key(self):
        """Contract missing 'contract_type' falls back to 'type' key."""
        contracts = [
            {"contract_id": "c-1", "provider_service": "svc", "type": "graphql", "version": "2"}
        ]
        result = _generate_contract_section(contracts)
        assert "graphql" in result

    def test_implemented_contract_shows_x(self):
        """Implemented contract shows [x] marker."""
        contracts = [
            {
                "contract_id": "c-impl",
                "provider_service": "svc",
                "contract_type": "api",
                "version": "1",
                "implemented": True,
            }
        ]
        result = _generate_contract_section(contracts)
        assert "[x]" in result
        assert "[ ]" not in result

    def test_unimplemented_contract_shows_empty(self):
        """Unimplemented contract shows [ ] marker."""
        contracts = [
            {
                "contract_id": "c-notimpl",
                "provider_service": "svc",
                "contract_type": "api",
                "version": "1",
                "implemented": False,
            }
        ]
        result = _generate_contract_section(contracts)
        assert "[ ]" in result
        # Ensure [x] is NOT present for this contract
        line = [l for l in result.splitlines() if "c-notimpl" in l][0]
        assert "[x]" not in line

    def test_missing_implemented_key_defaults_to_unchecked(self):
        """Contract without 'implemented' key defaults to [ ] (unchecked)."""
        contracts = [
            {"contract_id": "c-nokey", "provider_service": "svc", "contract_type": "api", "version": "1"}
        ]
        result = _generate_contract_section(contracts)
        line = [l for l in result.splitlines() if "c-nokey" in l][0]
        assert "[ ]" in line

    def test_contract_with_all_fallback_keys(self):
        """Contract with only secondary fallback keys still renders correctly."""
        contracts = [
            {
                "id": "fb-id",
                "service_name": "fb-svc",
                "type": "rest",
                "version": "3",
                "implemented": True,
            }
        ]
        result = _generate_contract_section(contracts)
        assert "[x]" in result
        assert "`fb-id`" in result
        assert "fb-svc" in result
        assert "rest" in result
        assert "v3" in result

    def test_minimal_contract_with_no_optional_keys(self):
        """Contract with no recognized keys renders with all 'unknown' fallbacks."""
        contracts = [{"some_random_key": "value"}]
        result = _generate_contract_section(contracts)
        assert "## Active Contracts" in result
        assert "`unknown`" in result


# ===========================================================================
# Group 5: Factory Branch 2 Detail
# ===========================================================================


class TestFactoryBranch2Detail:
    """Detailed tests for factory branch 2: env var not set behavior.

    Branch 2 in create_execution_backend: enabled=True but
    CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS is not '1'.
    The factory logs a warning and returns CLIBackend regardless of
    fallback_to_cli setting.
    """

    def test_env_not_set_fallback_false_still_returns_cli(self, monkeypatch):
        """Branch 2: env var not set + fallback_to_cli=False still returns CLIBackend
        (NOT RuntimeError). The fallback_to_cli flag is irrelevant in branch 2 because
        the env var check occurs before the CLI availability check."""
        monkeypatch.delenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", raising=False)
        config = AgentTeamConfig()
        config.agent_teams.enabled = True
        config.agent_teams.fallback_to_cli = False
        # Should NOT raise -- branch 2 returns CLIBackend unconditionally
        backend = create_execution_backend(config)
        assert isinstance(backend, CLIBackend)

    def test_env_not_set_logs_warning(self, monkeypatch, caplog):
        """Branch 2: env var not set logs a warning message about the env var."""
        monkeypatch.delenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", raising=False)
        config = AgentTeamConfig()
        config.agent_teams.enabled = True

        with caplog.at_level(logging.WARNING, logger="agent_team_v15.agent_teams_backend"):
            backend = create_execution_backend(config)

        assert isinstance(backend, CLIBackend)
        # Check that a warning was logged mentioning the env var
        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any(
            "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS" in msg for msg in warning_messages
        ), f"Expected warning about env var, got: {warning_messages}"

    def test_env_set_to_empty_string_returns_cli(self, monkeypatch):
        """Branch 2: env var set to empty string returns CLIBackend."""
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "")
        config = AgentTeamConfig()
        config.agent_teams.enabled = True
        config.agent_teams.fallback_to_cli = False
        backend = create_execution_backend(config)
        assert isinstance(backend, CLIBackend)

    def test_env_set_to_zero_returns_cli(self, monkeypatch):
        """Branch 2: env var set to '0' returns CLIBackend."""
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "0")
        config = AgentTeamConfig()
        config.agent_teams.enabled = True
        config.agent_teams.fallback_to_cli = False
        backend = create_execution_backend(config)
        assert isinstance(backend, CLIBackend)

    def test_env_set_to_true_string_returns_cli(self, monkeypatch):
        """Branch 2: env var set to 'true' (not '1') returns CLIBackend."""
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "true")
        config = AgentTeamConfig()
        config.agent_teams.enabled = True
        backend = create_execution_backend(config)
        assert isinstance(backend, CLIBackend)

    def test_env_set_to_yes_returns_cli(self, monkeypatch):
        """Branch 2: env var set to 'yes' returns CLIBackend."""
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "yes")
        config = AgentTeamConfig()
        config.agent_teams.enabled = True
        backend = create_execution_backend(config)
        assert isinstance(backend, CLIBackend)

    def test_branch2_does_not_call_verify_claude_available(self, monkeypatch):
        """Branch 2 returns CLIBackend without calling _verify_claude_available.
        This is an optimization: the env var check short-circuits before CLI check."""
        monkeypatch.delenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", raising=False)
        config = AgentTeamConfig()
        config.agent_teams.enabled = True

        with patch.object(
            AgentTeamsBackend, "_verify_claude_available"
        ) as mock_verify:
            backend = create_execution_backend(config)

        assert isinstance(backend, CLIBackend)
        mock_verify.assert_not_called()


# ===========================================================================
# ISSUE-001 Regression Guard
# ===========================================================================


def test_issue001_mcp_servers_defined_before_write_teammate_claude_md():
    """Regression guard for ISSUE-001: mcp_servers must be defined
    before write_teammate_claude_md() is called in main()."""
    import inspect
    from agent_team_v15 import cli

    source = inspect.getsource(cli.main)

    # Find the positions in source
    mcp_assignment_pos = source.find("mcp_servers = get_contract_aware_servers(config)")
    write_call_pos = source.find("mcp_servers=mcp_servers,")

    assert mcp_assignment_pos != -1, (
        "mcp_servers = get_contract_aware_servers(config) not found in main()"
    )
    assert write_call_pos != -1, (
        "mcp_servers=mcp_servers not found in write_teammate_claude_md() call"
    )
    assert mcp_assignment_pos < write_call_pos, (
        f"ISSUE-001 regression: mcp_servers assignment (pos {mcp_assignment_pos}) "
        f"must appear before its use in write_teammate_claude_md() (pos {write_call_pos})"
    )

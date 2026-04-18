"""N-17: Tests for MCP pre-fetch framework idioms.

Covers:
- Flag ON: _prefetch_framework_idioms queries MCP (mock)
- Flag OFF: no query, empty string returned
- Cache hit: second call returns cached content without re-querying
- MCP failure: returns empty string, no exception
- build_wave_b_prompt with mcp_doc_context embeds [CURRENT FRAMEWORK IDIOMS]
- build_wave_b_prompt with empty mcp_doc_context omits the section
- build_wave_d_prompt with mcp_doc_context embeds section
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_team_v15.agents import build_wave_b_prompt, build_wave_d_prompt
from agent_team_v15.cli import MCP_DOC_QUERIES_BY_WAVE, _prefetch_framework_idioms
from agent_team_v15.config import AgentTeamConfig


def _make_config(*, mcp_enabled: bool = True) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18.mcp_informed_dispatches_enabled = mcp_enabled
    return cfg


def _make_milestone() -> SimpleNamespace:
    return SimpleNamespace(
        id="milestone-1",
        title="Test Milestone",
        scope=[],
        requirements=[],
    )


def _make_ir() -> SimpleNamespace:
    return SimpleNamespace(
        endpoints=[],
        business_rules=[],
        state_machines=[],
        events=[],
        integrations=[],
        integration_items=[],
        acceptance_criteria=[],
    )


class TestMCPDocQueriesByWave:
    """MCP_DOC_QUERIES_BY_WAVE has expected structure."""

    def test_wave_b_queries_exist(self) -> None:
        assert "B" in MCP_DOC_QUERIES_BY_WAVE
        assert len(MCP_DOC_QUERIES_BY_WAVE["B"]) >= 1

    def test_wave_d_queries_exist(self) -> None:
        assert "D" in MCP_DOC_QUERIES_BY_WAVE
        assert len(MCP_DOC_QUERIES_BY_WAVE["D"]) >= 1

    def test_each_query_is_tuple_pair(self) -> None:
        for wave, queries in MCP_DOC_QUERIES_BY_WAVE.items():
            for q in queries:
                assert isinstance(q, tuple), f"Query in wave {wave} is not a tuple"
                assert len(q) == 2, f"Query in wave {wave} does not have 2 elements"


class TestPrefetchFlagOff:
    """When mcp_informed_dispatches_enabled is OFF, returns empty string."""

    @pytest.mark.asyncio
    async def test_returns_empty_string(self, tmp_path: Path) -> None:
        cfg = _make_config(mcp_enabled=False)
        result = await _prefetch_framework_idioms(
            wave="B",
            milestone_id="m1",
            cwd=str(tmp_path),
            config=cfg,
        )
        assert result == ""


class TestPrefetchCacheHit:
    """When cache contains the key, returns cached content without MCP call."""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached(self, tmp_path: Path) -> None:
        cfg = _make_config(mcp_enabled=True)
        cache_dir = tmp_path / ".agent-team"
        cache_dir.mkdir(parents=True)
        cache_key = "m1::B::v1"
        cache_data = {cache_key: "cached docs content"}
        (cache_dir / "framework_idioms_cache.json").write_text(
            json.dumps(cache_data), encoding="utf-8"
        )
        result = await _prefetch_framework_idioms(
            wave="B",
            milestone_id="m1",
            cwd=str(tmp_path),
            config=cfg,
        )
        assert result == "cached docs content"


class TestPrefetchNoQueries:
    """When wave has no queries, returns empty string."""

    @pytest.mark.asyncio
    async def test_unknown_wave_returns_empty(self, tmp_path: Path) -> None:
        cfg = _make_config(mcp_enabled=True)
        result = await _prefetch_framework_idioms(
            wave="Z",
            milestone_id="m1",
            cwd=str(tmp_path),
            config=cfg,
        )
        assert result == ""


class TestPrefetchMCPFailure:
    """When MCP client is unavailable, returns empty string without raising."""

    @pytest.mark.asyncio
    async def test_no_context7_returns_empty(self, tmp_path: Path) -> None:
        cfg = _make_config(mcp_enabled=True)
        with patch(
            "agent_team_v15.mcp_servers.get_context7_only_servers",
            return_value=[],
        ):
            result = await _prefetch_framework_idioms(
                wave="B",
                milestone_id="m1",
                cwd=str(tmp_path),
                config=cfg,
            )
        assert result == ""


class TestBuildWaveBPromptMCPContext:
    """build_wave_b_prompt with/without mcp_doc_context."""

    def test_with_context_embeds_section(self) -> None:
        prompt = build_wave_b_prompt(
            milestone=_make_milestone(),
            ir=_make_ir(),
            wave_a_artifact=None,
            dependency_artifacts=None,
            scaffolded_files=None,
            config=AgentTeamConfig(),
            existing_prompt_framework="",
            mcp_doc_context="Some framework idioms text",
        )
        assert "[CURRENT FRAMEWORK IDIOMS]" in prompt
        assert "Some framework idioms text" in prompt

    def test_without_context_omits_section(self) -> None:
        prompt = build_wave_b_prompt(
            milestone=_make_milestone(),
            ir=_make_ir(),
            wave_a_artifact=None,
            dependency_artifacts=None,
            scaffolded_files=None,
            config=AgentTeamConfig(),
            existing_prompt_framework="",
            mcp_doc_context="",
        )
        assert "[CURRENT FRAMEWORK IDIOMS]" not in prompt


class TestBuildWaveDPromptMCPContext:
    """build_wave_d_prompt with mcp_doc_context embeds [CURRENT FRAMEWORK IDIOMS]."""

    def test_with_context_embeds_section(self) -> None:
        prompt = build_wave_d_prompt(
            milestone=_make_milestone(),
            ir=_make_ir(),
            wave_c_artifact=None,
            scaffolded_files=None,
            config=AgentTeamConfig(),
            existing_prompt_framework="",
            mcp_doc_context="Next.js idioms",
        )
        assert "[CURRENT FRAMEWORK IDIOMS]" in prompt
        assert "Next.js idioms" in prompt

    def test_without_context_omits_section(self) -> None:
        prompt = build_wave_d_prompt(
            milestone=_make_milestone(),
            ir=_make_ir(),
            wave_c_artifact=None,
            scaffolded_files=None,
            config=AgentTeamConfig(),
            existing_prompt_framework="",
            mcp_doc_context="",
        )
        assert "[CURRENT FRAMEWORK IDIOMS]" not in prompt

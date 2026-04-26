"""N-09: Tests for prompt hardener blocks in build_wave_b_prompt and CODEX_WAVE_B_PREAMBLE.

Covers:
- 10 AUD patterns (009/010/012/013/016/018/020/023/024/025) present in Claude path
- Source URLs present
- 10 AUD patterns present in Codex path (CODEX_WAVE_B_PREAMBLE)
- Hardener section ordering: after execution directives, before [YOUR TASK]
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent_team_v15.agents import build_wave_b_prompt
from agent_team_v15.codex_prompts import CODEX_WAVE_B_PREAMBLE
from agent_team_v15.config import AgentTeamConfig


# All 9 pattern IDs we expect
_HARDENER_IDS = [
    "AUD-009",
    "AUD-010",
    "AUD-012",
    "AUD-013",
    "AUD-016",
    "AUD-018",
    "AUD-020",
    "AUD-023",
    "AUD-024",
    "AUD-025",
]


def _make_prompt(**overrides) -> str:
    """Build a wave B prompt with minimal required arguments."""
    milestone = SimpleNamespace(
        id="milestone-1",
        title="Test Milestone",
        scope=[],
        requirements=[],
    )
    ir = SimpleNamespace(
        endpoints=[],
        business_rules=[],
        state_machines=[],
        events=[],
        integrations=[],
        integration_items=[],
        acceptance_criteria=[],
    )
    defaults = dict(
        milestone=milestone,
        ir=ir,
        wave_a_artifact=None,
        dependency_artifacts=None,
        scaffolded_files=None,
        config=AgentTeamConfig(),
        existing_prompt_framework="",
        cwd=None,
        milestone_context=None,
        mcp_doc_context="",
    )
    defaults.update(overrides)
    return build_wave_b_prompt(**defaults)


class TestClaudePathHardeners:
    """Each AUD pattern must appear in the Claude-path build_wave_b_prompt output."""

    @pytest.fixture()
    def prompt_text(self) -> str:
        return _make_prompt()

    @pytest.mark.parametrize("pattern_id", _HARDENER_IDS)
    def test_hardener_pattern_present(self, prompt_text: str, pattern_id: str) -> None:
        assert pattern_id in prompt_text, (
            f"Pattern {pattern_id} missing from build_wave_b_prompt output"
        )

    def test_aud009_source_url(self, prompt_text: str) -> None:
        assert "exception-filters.md" in prompt_text

    def test_aud010_source_url(self, prompt_text: str) -> None:
        assert "techniques/configuration.md" in prompt_text

    def test_aud012_source_url(self, prompt_text: str) -> None:
        assert "encryption-hashing.md" in prompt_text

    def test_aud013_source_url(self, prompt_text: str) -> None:
        assert "techniques/configuration.md" in prompt_text

    def test_aud016_source_url(self, prompt_text: str) -> None:
        assert "recipes/passport.md" in prompt_text

    def test_aud018_source_url(self, prompt_text: str) -> None:
        assert "types-and-parameters.md" in prompt_text

    def test_aud020_source_url(self, prompt_text: str) -> None:
        assert "techniques/validation.md" in prompt_text

    def test_aud023_source_url(self, prompt_text: str) -> None:
        assert "prisma" in prompt_text.lower()

    def test_aud024_source_urls(self, prompt_text: str) -> None:
        assert "docs.nestjs.com/migration-guide" in prompt_text
        assert "expressjs.com/en/guide/migrating-5.html" in prompt_text

    def test_aud024_positive_example_present(self, prompt_text: str) -> None:
        assert "forRoutes('{*splat}')" in prompt_text

    def test_aud025_source_url(self, prompt_text: str) -> None:
        assert "expressjs.com/en/guide/migrating-5.html" in prompt_text

    def test_aud025_positive_example_present(self, prompt_text: str) -> None:
        assert "this.normalizeValue(req.query);" in prompt_text


class TestCodexPathHardeners:
    """All 9 patterns must appear in CODEX_WAVE_B_PREAMBLE."""

    @pytest.mark.parametrize("pattern_id", _HARDENER_IDS)
    def test_preamble_contains_pattern(self, pattern_id: str) -> None:
        assert pattern_id in CODEX_WAVE_B_PREAMBLE, (
            f"Pattern {pattern_id} missing from CODEX_WAVE_B_PREAMBLE"
        )

    def test_preamble_contains_named_wildcard_rule(self) -> None:
        assert "forRoutes('{*splat}')" in CODEX_WAVE_B_PREAMBLE

    def test_preamble_contains_req_query_write_rule(self) -> None:
        assert "req.query" in CODEX_WAVE_B_PREAMBLE
        assert "no longer a writable" in CODEX_WAVE_B_PREAMBLE


class TestHardenerOrdering:
    """Hardener section must appear after execution directives and before [YOUR TASK]."""

    @pytest.fixture()
    def prompt_text(self) -> str:
        return _make_prompt()

    def test_hardeners_after_execution_directives(self, prompt_text: str) -> None:
        exec_idx = prompt_text.find("[EXECUTION DIRECTIVES]")
        aud009_idx = prompt_text.find("AUD-009")
        assert exec_idx >= 0, "[EXECUTION DIRECTIVES] not found"
        assert aud009_idx >= 0, "AUD-009 not found"
        assert aud009_idx > exec_idx, (
            "Hardeners must appear AFTER [EXECUTION DIRECTIVES]"
        )

    def test_hardeners_before_your_task(self, prompt_text: str) -> None:
        aud023_idx = prompt_text.find("AUD-023")
        task_idx = prompt_text.find("[YOUR TASK]")
        assert aud023_idx >= 0, "AUD-023 not found"
        assert task_idx >= 0, "[YOUR TASK] not found"
        assert aud023_idx < task_idx, (
            "Hardeners must appear BEFORE [YOUR TASK]"
        )

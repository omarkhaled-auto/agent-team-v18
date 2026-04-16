"""N-02 (Phase B) tests for Consumer 1 (wave prompt injection) and
Consumer 2 (auditor optional-file suppression).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_team_v15.agents import _format_ownership_claim_section
from agent_team_v15.audit_team import _build_optional_suppression_block
from agent_team_v15.config import AgentTeamConfig, V18Config


def _cfg(flag: bool) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18 = V18Config(ownership_contract_enabled=flag)
    return cfg


# ---------------------------------------------------------------------------
# Consumer 1 — _format_ownership_claim_section (wave-b / wave-d prompts)
# ---------------------------------------------------------------------------


class TestWavePromptInjection:
    def test_returns_empty_list_when_config_none(self) -> None:
        assert _format_ownership_claim_section("wave-b", None) == []

    def test_returns_empty_list_when_flag_off(self) -> None:
        assert _format_ownership_claim_section("wave-b", _cfg(False)) == []

    def test_wave_b_section_lists_12_files_when_flag_on(self) -> None:
        lines = _format_ownership_claim_section("wave-b", _cfg(True))
        # Leading "", header "[FILES YOU OWN]", then one line per file (12)
        assert lines[0] == ""
        assert lines[1] == "[FILES YOU OWN]"
        path_lines = [l for l in lines[2:] if l.startswith("- ")]
        assert len(path_lines) == 12

    def test_wave_d_section_lists_single_wave_d_owned_file(self) -> None:
        lines = _format_ownership_claim_section("wave-d", _cfg(True))
        path_lines = [l for l in lines[2:] if l.startswith("- ")]
        assert len(path_lines) == 1
        assert "apps/web/src/lib/api/client.ts" in path_lines[0]

    def test_unknown_owner_returns_empty(self) -> None:
        assert _format_ownership_claim_section("mystery-owner", _cfg(True)) == []


# ---------------------------------------------------------------------------
# Consumer 2 — audit_team._build_optional_suppression_block
# ---------------------------------------------------------------------------


class TestAuditorOptionalSuppression:
    def test_empty_when_config_none(self) -> None:
        assert _build_optional_suppression_block(None) == ""

    def test_empty_when_flag_off(self) -> None:
        assert _build_optional_suppression_block(_cfg(False)) == ""

    def test_section_lists_all_optional_paths_when_flag_on(self) -> None:
        block = _build_optional_suppression_block(_cfg(True))
        assert "Optional Files" in block
        # All 3 optional paths from the contract must appear
        assert ".editorconfig" in block
        assert ".nvmrc" in block
        assert "apps/api/prisma/seed.ts" in block

    def test_empty_when_config_has_no_v18(self) -> None:
        cfg = SimpleNamespace()
        assert _build_optional_suppression_block(cfg) == ""

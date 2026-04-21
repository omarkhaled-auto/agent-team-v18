"""Phase 1 Task 1.2: MESSAGE_TYPES exposes cross-protocol events."""
from __future__ import annotations

from agent_team_v15.agent_teams_backend import AgentTeamsBackend


def test_message_types_contains_codex_wave_complete():
    assert "CODEX_WAVE_COMPLETE" in AgentTeamsBackend.MESSAGE_TYPES


def test_message_types_contains_steer_request():
    assert "STEER_REQUEST" in AgentTeamsBackend.MESSAGE_TYPES


def test_message_types_preserves_legacy_entries():
    """Rename must not drop existing types that other code paths rely on."""
    required_legacy = {
        "REQUIREMENTS_READY",
        "ARCHITECTURE_READY",
        "WAVE_COMPLETE",
        "REVIEW_RESULTS",
        "DEBUG_FIX_COMPLETE",
        "WIRING_ESCALATION",
        "CONVERGENCE_COMPLETE",
        "TESTING_COMPLETE",
        "ESCALATION_REQUEST",
        "SYSTEM_STATE",
        "RESUME",
    }
    missing = required_legacy - AgentTeamsBackend.MESSAGE_TYPES
    assert not missing, f"Legacy message types dropped: {missing}"
